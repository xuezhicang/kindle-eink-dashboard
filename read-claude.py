"""Read Claude plan limits (5-hour + weekly) and save data/claude.json.

Uses the local Claude Code login. Starts `claude` in stream-json mode and
sends two control requests, `initialize` and `get_usage`. No chat message
is sent, so no quota is used.

get_usage is marked experimental in Claude Code, so we read
rate_limits.five_hour / seven_day first and fall back to the
rate_limits.limits[] list if those fields move.
"""

import sys
from datetime import datetime

from common import (JsonLinesProcess, describe_usage, run_collector,
                    usage_payload, window)

CMD = [
    "claude", "-p",
    "--input-format", "stream-json",
    "--output-format", "stream-json",
    "--verbose",
    "--strict-mcp-config",       # don't start any MCP servers
    "--no-session-persistence",  # don't save a session file
]


def request(proc, request_id, body):
    proc.send({"type": "control_request", "request_id": request_id, "request": body})
    message = proc.wait_for(
        lambda m: m.get("type") == "control_response"
        and (m.get("response") or {}).get("request_id") == request_id)
    response = message["response"]
    if response.get("subtype") != "success":
        raise RuntimeError(f"{body['subtype']}: {response.get('error', 'failed')}")
    return response.get("response") or {}


def to_unix(iso_text):
    if not iso_text:
        return None
    return datetime.fromisoformat(iso_text.replace("Z", "+00:00")).timestamp()


def from_fields(entry, percent_key):
    if not isinstance(entry, dict) or entry.get(percent_key) is None:
        return None
    return window(entry[percent_key], to_unix(entry.get("resets_at")))


def fetch(previous):
    with JsonLinesProcess(CMD, timeout=60) as proc:
        request(proc, "init", {"subtype": "initialize"})
        usage = request(proc, "usage", {"subtype": "get_usage", "skip_behaviors": True})

    if not usage.get("rate_limits_available"):
        raise RuntimeError("plan limits not available for this login "
                           f"(subscription: {usage.get('subscription_type')})")

    limits = usage.get("rate_limits") or {}
    by_kind = {item.get("kind"): item for item in limits.get("limits") or []
               if isinstance(item, dict)}
    return usage_payload({
        "five_hour": (from_fields(limits.get("five_hour"), "utilization")
                      or from_fields(by_kind.get("session"), "percent")),
        "weekly": (from_fields(limits.get("seven_day"), "utilization")
                   or from_fields(by_kind.get("weekly_all"), "percent")),
    })


if __name__ == "__main__":
    sys.exit(run_collector("claude", fetch, describe_usage))
