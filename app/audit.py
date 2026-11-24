"""Audit log: one line per meaningful user action (who did what, to what).

Lines go to standard output, where every place the app runs collects them:
the terminal (python run.py), `docker compose logs`, and Render's Logs tab.
Example line:

    2026-11-24 14:03:12 INFO tracker.audit: action=task_updated actor=alice task_id=7 fields=status,assignee

Never log secrets: no passwords, tokens or session cookies, and no comment text.
"""
import json
import logging
import os
import sys

logger = logging.getLogger("tracker.audit")


def configure_logging():
    """Send the app's own log lines to stdout. LOG_LEVEL (default INFO) controls how much is shown."""
    app_logger = logging.getLogger("tracker")
    if not app_logger.handlers:  # don't add a second handler when uvicorn reloads the app
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
        app_logger.addHandler(handler)
    app_logger.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    app_logger.propagate = False  # uvicorn has its own handlers; avoid printing lines twice


def _value(v):
    # key=value pairs stay on one line and easy to search: quote anything with spaces,
    # and escape newlines so user input (e.g. a task title) can't fake extra log lines.
    text = str(v)
    if text == "" or any(c in text for c in ' "=\n\r\t'):
        return json.dumps(text)
    return text


def log_event(action, actor, level=logging.INFO, **details):
    fields = " ".join(f"{key}={_value(value)}" for key, value in details.items())
    logger.log(level, "action=%s actor=%s %s", action, _value(actor or "-"), fields)
