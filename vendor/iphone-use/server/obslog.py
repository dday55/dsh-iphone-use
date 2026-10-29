"""Structured stderr events: one JSON object per line.

Local logs stay safe to paste into an issue report: callers pass only identify
the stage and the failure kind. Selectors, typed text, app data, screenshots and
device identifiers never belong in a log line.
"""
import json
import sys
import time


def log_event(event, **fields):
    """Emit one structured event. Never raises: logging must not break a tool."""
    record = {"ts": round(time.time(), 3), "event": event}
    for key, value in fields.items():
        if value is None:
            continue
        record[key] = value
    try:
        sys.stderr.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        sys.stderr.flush()
    except (OSError, TypeError, ValueError):
        pass
