"""Shared helpers for the collectors (read-*.py).

Every collector writes data/<source>.json with the same envelope:

    {
      "source": "codex",
      "ok": true,                 # did THIS run succeed?
      "fetchedAt": "...",         # time of this run (UTC, ISO 8601)
      "lastOkAt": "...",          # time of the last successful run
      "error": null,              # short message when ok is false
      ...payload...               # source specific, e.g. "windows" or "weather"
    }

When a run fails, the previous payload and lastOkAt are kept, so the
dashboard can still show the last known values (marked "as of ...").
"""

import json
import os
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
USER_AGENT = "kindle-dashboard/1.0"
ENVELOPE = ("source", "ok", "fetchedAt", "lastOkAt", "error")


def read_env(path=os.path.join(HERE, ".env")):
    """Parse KEY=VALUE lines of .env (comments and blank lines ignored)."""
    values = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    return values


def http_get(url, timeout=15):
    """GET url. Returns (status, body_bytes, headers); HTTP errors are returned, not raised.

    Network problems (DNS, refused, timeout) still raise OSError.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), response.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


# ---------- usage limits (Codex, Claude) ----------

def window(used_percent, resets_at):
    """Build one normalized usage window. resets_at is Unix seconds or None.

    Reset times are rounded to the nearest minute: the APIs return them with
    sub-second jitter (09:59:59.9 one run, 10:00:00.4 the next), which would
    otherwise make the screen flip between 3:59 and 4:00.
    """
    used = max(0.0, min(100.0, float(used_percent)))
    resets = round(float(resets_at) / 60) * 60 if resets_at is not None else None
    return {"usedPercent": used, "resetsAt": resets}


def usage_payload(windows):
    if not any(windows.values()):
        raise RuntimeError("no 5-hour or weekly window in the response")
    return {"windows": windows}


def describe_usage(payload):
    parts = []
    for key, label in (("five_hour", "5-hour"), ("weekly", "weekly")):
        w = payload["windows"].get(key)
        parts.append(f"{label} {100 - w['usedPercent']:.0f}% left" if w else f"{label} n/a")
    return ", ".join(parts)


class JsonLinesProcess:
    """A child process that speaks one JSON object per line on stdin/stdout.

    The whole conversation has one deadline; when it passes, the child is
    killed and wait_for() raises.
    """

    def __init__(self, cmd, timeout):
        self.timed_out = False
        # stderr is inherited, so the child's warnings end up in logs/run.log.
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, text=True)
        self.timer = threading.Timer(timeout, self._on_timeout)
        self.timer.start()

    def _on_timeout(self):
        self.timed_out = True
        self.proc.kill()

    def send(self, message):
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def wait_for(self, match):
        """Return the first message for which match(message) is true."""
        for line in self.proc.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if isinstance(message, dict) and match(message):
                return message
        if self.timed_out:
            raise RuntimeError("timed out")
        raise RuntimeError(f"exited with code {self.proc.wait()}")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.timer.cancel()
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()


# ---------- collector runner ----------

def run_collector(source, fetch, describe):
    """Run fetch(previous) -> payload dict, save data/<source>.json, return exit code.

    `previous` is the last saved file (or {}), for collectors that need it.
    """
    path = os.path.join(DATA_DIR, f"{source}.json")
    try:
        with open(path, encoding="utf-8") as f:
            previous = json.load(f)
    except (OSError, ValueError):
        previous = {}

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        payload = fetch(previous)
        result = {"source": source, "ok": True, "fetchedAt": now,
                  "lastOkAt": now, "error": None, **payload}
        print(f"{source}: ok, {describe(payload)}")
        code = 0
    except Exception as e:  # noqa: BLE001 - any failure is recorded, never fatal
        error = f"{type(e).__name__}: {e}"[:200]
        kept = {k: v for k, v in previous.items() if k not in ENVELOPE}
        result = {"source": source, "ok": False, "fetchedAt": now,
                  "lastOkAt": previous.get("lastOkAt"), "error": error, **kept}
        print(f"{source}: FAILED, {error} (keeping last data)", file=sys.stderr)
        code = 1

    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    os.replace(tmp, path)  # atomic: the renderer never sees a half-written file
    return code
