"""Read Codex plan limits (5-hour + weekly) and save data/codex.json.

Uses the local Codex login (CODEX_HOME, default ~/.codex) through
`codex app-server` and its `account/rateLimits/read` request.
"""

import sys

from common import (JsonLinesProcess, describe_usage, run_collector,
                    usage_payload, window)

CLIENT_INFO = {"name": "kindle_dashboard", "title": "Kindle AI Usage Dashboard",
               "version": "1.0.0"}
WINDOW_KEYS = {300: "five_hour", 10080: "weekly"}  # windowDurationMins -> our key


def reply(proc, request_id):
    message = proc.wait_for(lambda m: m.get("id") == request_id)
    if message.get("error"):
        raise RuntimeError(message["error"].get("message", "request failed"))
    return message.get("result") or {}


def fetch(previous):
    with JsonLinesProcess(["codex", "app-server"], timeout=60) as proc:
        proc.send({"id": 1, "method": "initialize",
                   "params": {"clientInfo": CLIENT_INFO}})
        reply(proc, 1)
        proc.send({"method": "initialized", "params": {}})
        proc.send({"id": 2, "method": "account/rateLimits/read", "params": {}})
        result = reply(proc, 2)

    limits = ((result.get("rateLimitsByLimitId") or {}).get("codex")
              or result.get("rateLimits") or {})
    windows = {"five_hour": None, "weekly": None}
    for w in (limits.get("primary"), limits.get("secondary")):
        key = WINDOW_KEYS.get((w or {}).get("windowDurationMins"))
        if key and w.get("usedPercent") is not None:
            windows[key] = window(w["usedPercent"], w.get("resetsAt"))
    return usage_payload(windows)


if __name__ == "__main__":
    sys.exit(run_collector("codex", fetch, describe_usage))
