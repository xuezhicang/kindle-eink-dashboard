"""Check the AerisIQ map and save data/aerisiq.json.

Two public requests, the same path real users take
(DNS -> Cloudflare -> nginx -> EWS backend):

  1. GET https://aerisiq.io/map                  must be 200 and the AerisIQ page
  2. GET https://aerisiq.io/api/v1/forecast/run  which run is live

Status saved here:
  OK     both fine
  ERROR  /run answered 503 twice, 30 s apart (a real publish switch only takes
         seconds), or answered with data we can't read
  DOWN   no answer, timeout, or any other HTTP error

LATE (run older than 24 h) depends on the clock, so generate.py decides it.
When /run can't be read, the last run we saw is kept ("last seen").
"""

import json
import sys
import time
from datetime import datetime, timezone

from common import http_get, run_collector

SITE = "https://aerisiq.io"
TIMEOUT = 15
RETRY_WAIT = 30  # the server sends Retry-After: 30 with its 503


class Problem(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def short(text, limit=70):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def check_map():
    try:
        status, body, _ = http_get(f"{SITE}/map", timeout=TIMEOUT)
    except OSError as e:
        raise Problem("DOWN", f"/map: no response ({short(e, 40)})")
    if status != 200:
        raise Problem("DOWN", f"/map: HTTP {status}")
    if b"AerisIQ" not in body:
        raise Problem("DOWN", "/map: page is not the AerisIQ app")


def error_text(body):
    try:
        data = json.loads(body)
        return data.get("error") or data.get("detail") or body[:80]
    except ValueError:
        return body[:80].decode("utf-8", "replace")


def fetch_run():
    for attempt in (1, 2):
        try:
            status, body, _ = http_get(f"{SITE}/api/v1/forecast/run", timeout=TIMEOUT)
        except OSError as e:
            raise Problem("DOWN", f"/run: no response ({short(e, 40)})")
        if status == 503 and attempt == 1:
            time.sleep(RETRY_WAIT)
            continue
        break
    if status == 503:
        raise Problem("ERROR", f"/run: {short(error_text(body))}")
    if status != 200:
        raise Problem("DOWN", f"/run: HTTP {status}")
    try:
        data = json.loads(body)
        times = data["index_to_time"]
        run = {
            "runId": data["run_id"],
            "publishedAt": data["published_at"],
            "endTime": times[str(data["max_index"])],  # last forecast hour, Chicago time
        }
        datetime.strptime(run["runId"], "%Y-%m-%d_%H:%M:%S")  # format check
    except (ValueError, KeyError, TypeError) as e:
        raise Problem("ERROR", f"/run: unexpected data ({short(e, 40)})")
    return run


def fetch(previous):
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    run, run_seen, problem = previous.get("run"), previous.get("runSeenAt"), None
    try:
        run, run_seen = fetch_run(), now
    except Problem as p:
        problem = p
    try:
        check_map()
    except Problem as p:
        if problem is None or p.status == "DOWN":
            problem = p
    return {
        "status": problem.status if problem else "OK",
        "problem": str(problem) if problem else None,
        "run": run,
        "runSeenAt": run_seen,
    }


def describe(payload):
    run = (payload["run"] or {}).get("runId", "none")
    return f"status {payload['status']}, run {run}" + (
        f", problem: {payload['problem']}" if payload["problem"] else "")


if __name__ == "__main__":
    sys.exit(run_collector("aerisiq", fetch, describe))
