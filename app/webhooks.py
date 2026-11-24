"""Outgoing webhooks: when something happens in the app, POST a JSON event to registered URLs.

How it works:
1. An action (e.g. creating a task) calls emit("task.created", {...}). That only writes one
   "pending" row per subscribed webhook into webhook_deliveries, which is fast, so the user's
   request never waits for (or fails because of) a receiver.
2. A background worker thread picks up due rows and sends them, one HTTP POST each.
3. A 2xx answer = delivered. Anything else (error status, refused connection, timeout) is retried
   later with increasing waits (WEBHOOK_RETRY_DELAYS). After the last retry it is marked "failed";
   an admin can redeliver it by hand once the receiver works again.

Every attempt is recorded, so the delivery log shows exactly what happened.

What a receiver gets:
    POST <url>
    Content-Type: application/json
    X-Webhook-Event: task.created
    X-Webhook-Id: evt_...          same on every retry, so receivers can ignore duplicates
    X-Webhook-Delivery: 12          this delivery's id
    X-Webhook-Attempt: 1            1 = first try, 2 = first retry, ...
    X-Webhook-Timestamp: 1764000000
    X-Webhook-Signature: sha256=<hex HMAC-SHA256 of "<timestamp>.<body>" with the webhook's secret>
"""
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import secrets
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta
from urllib.parse import urlparse

from app.audit import log_event
from app.db import get_conn
from app.errors import ValidationError

EVENTS = ("task.created", "task.updated", "task.deleted", "comment.added")
TEST_EVENT = "webhook.test"
URL_MAX = 500


class WebhookNotFound(Exception):
    def __init__(self, webhook_id):
        super().__init__(f"Webhook {webhook_id} not found")


class DeliveryNotFound(Exception):
    def __init__(self, delivery_id):
        super().__init__(f"Delivery {delivery_id} not found")


# --- settings (environment variables) -----------------------------------------------

def retry_delays():
    """Seconds to wait before each retry. Default: 10 s, 1 min, 5 min, 30 min (5 attempts in total)."""
    raw = os.environ.get("WEBHOOK_RETRY_DELAYS", "10,60,300,1800")
    try:
        return [float(x) for x in raw.split(",") if x.strip()]
    except ValueError:
        return [10, 60, 300, 1800]


def timeout_seconds():
    return float(os.environ.get("WEBHOOK_TIMEOUT_SECONDS", "5"))


def poll_seconds():
    return float(os.environ.get("WEBHOOK_POLL_SECONDS", "2"))


def block_private_urls():
    """On the hosted app (Render), refuse to call addresses inside the server's own network."""
    default = "true" if os.environ.get("RENDER") else "false"
    return os.environ.get("WEBHOOK_BLOCK_PRIVATE_URLS", default).lower() == "true"


def _now():
    return datetime.now()


def _fmt(dt):
    # Microseconds, so short test retry delays work; the format still sorts correctly as text.
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


# --- signing --------------------------------------------------------------------------

def sign(secret, timestamp, body):
    """The signature a receiver recomputes to check the request really came from us, unchanged."""
    digest = hmac.new(secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify(secret, timestamp, body, signature):
    """What a receiver does (shown here for the docs and the tests)."""
    return hmac.compare_digest(sign(secret, timestamp, body), signature or "")


# --- managing webhooks ------------------------------------------------------------------

def _check_url(url):
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValidationError("Webhook URL must start with http:// or https://")
    if len(url) > URL_MAX:
        raise ValidationError(f"Webhook URL must be at most {URL_MAX} characters")
    return url


def _check_events(events):
    events = [e.strip() for e in (events or ["*"]) if e and e.strip()] or ["*"]
    if events != ["*"]:
        unknown = [e for e in events if e not in EVENTS]
        if unknown:
            raise ValidationError(f"Unknown event(s): {', '.join(unknown)}. Use * or any of: {', '.join(EVENTS)}")
    return events


def _public(row):
    return {"id": row["id"], "url": row["url"], "events": row["events"].split(","),
            "created_by": row["created_by"], "created_at": row["created_at"]}


def create_webhook(url, created_by, events=None):
    """Register a URL. Returns the webhook plus its signing secret (shown only this once)."""
    url, events = _check_url(url), _check_events(events)
    secret = "whsec_" + secrets.token_urlsafe(24)
    with get_conn() as conn:
        row = conn.execute(
            "INSERT INTO webhooks (url, secret, events, created_by, created_at) VALUES (?, ?, ?, ?, ?) RETURNING *",
            (url, secret, ",".join(events), created_by, _fmt(_now())),
        ).fetchone()
    log_event("webhook_created", created_by, webhook_id=row["id"], url=url, events=",".join(events))
    return {**_public(row), "secret": secret}


def list_webhooks():
    with get_conn() as conn:
        return [_public(r) for r in conn.execute("SELECT * FROM webhooks ORDER BY id")]


def get_webhook(webhook_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM webhooks WHERE id = ?", (webhook_id,)).fetchone()
    if row is None:
        raise WebhookNotFound(webhook_id)
    return _public(row)


def delete_webhook(webhook_id, deleted_by):
    hook = get_webhook(webhook_id)
    with get_conn() as conn:
        conn.execute("DELETE FROM webhooks WHERE id = ?", (webhook_id,))   # its deliveries go too
    log_event("webhook_deleted", deleted_by, webhook_id=webhook_id, url=hook["url"])


def list_deliveries(webhook_id, limit=20):
    get_webhook(webhook_id)
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM webhook_deliveries WHERE webhook_id = ? ORDER BY id DESC LIMIT ?",
            (webhook_id, max(1, min(int(limit), 100))),
        ).fetchall()
    return [_delivery_public(r) for r in rows]


def get_delivery(delivery_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM webhook_deliveries WHERE id = ?", (delivery_id,)).fetchone()
    if row is None:
        raise DeliveryNotFound(delivery_id)
    return _delivery_public(row)


def _delivery_public(row):
    keys = ("id", "webhook_id", "event_id", "event", "status", "attempts", "next_attempt_at",
            "last_status_code", "last_error", "created_at", "updated_at")
    return {k: row[k] for k in keys}


def redeliver(delivery_id, actor):
    """Send a delivery again now (e.g. after a receiver outage), with a fresh set of retries."""
    get_delivery(delivery_id)
    now = _fmt(_now())
    with get_conn() as conn:
        conn.execute(
            "UPDATE webhook_deliveries SET status = 'pending', attempts = 0, next_attempt_at = ?, updated_at = ? WHERE id = ?",
            (now, now, delivery_id),
        )
    log_event("webhook_redelivery", actor, delivery_id=delivery_id)
    _wake.set()
    return get_delivery(delivery_id)


def send_test(webhook_id, actor):
    hook = get_webhook(webhook_id)
    _enqueue(TEST_EVENT, {"message": "Test event from Task Tracker"}, actor, only_webhook_id=hook["id"])


# --- queuing events -------------------------------------------------------------------------

def emit(event, data, actor):
    """Queue an event for every webhook subscribed to it. Never raises: webhooks must not break the app."""
    try:
        _enqueue(event, data, actor)
    except Exception:  # noqa: BLE001 - log and carry on, the user's action already succeeded
        logging.getLogger("tracker.webhooks").exception("Could not queue webhook event %s", event)


def _enqueue(event, data, actor, only_webhook_id=None):
    now = _now()
    event_id = f"evt_{uuid.uuid4().hex}"
    # The exact bytes we sign and send are stored, so every retry sends the same body.
    body = json.dumps({"id": event_id, "event": event, "created_at": now.isoformat(timespec="seconds"),
                       "actor": actor, "data": data}, separators=(",", ":"), sort_keys=True)
    with get_conn() as conn:
        hooks = conn.execute("SELECT id, events FROM webhooks ORDER BY id").fetchall()
        targets = [h["id"] for h in hooks
                   if (only_webhook_id is None and ("*" in h["events"].split(",") or event in h["events"].split(",")))
                   or h["id"] == only_webhook_id]
        for webhook_id in targets:
            conn.execute(
                """INSERT INTO webhook_deliveries
                   (webhook_id, event_id, event, payload, status, attempts, next_attempt_at, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 'pending', 0, ?, ?, ?)""",
                (webhook_id, event_id, event, body, _fmt(now), _fmt(now), _fmt(now)),
            )
    if targets:
        _wake.set()


# --- sending (background worker) -------------------------------------------------------------

class _NoRedirects(urllib.request.HTTPRedirectHandler):
    # A redirect would turn our POST into a GET to some other address: treat it as a failed attempt.
    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_NoRedirects)


def _is_private(host):
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except socket.gaierror:
        return False   # can't resolve: let the request fail normally
    return any(ipaddress.ip_address(a).is_private or ipaddress.ip_address(a).is_loopback
               or ipaddress.ip_address(a).is_link_local for a in addresses)


def _send(url, secret, body, headers):
    """One HTTP POST. Returns (status_code or None, error message)."""
    if block_private_urls() and _is_private(urlparse(url).hostname):
        return None, "Blocked: URL points to a private network address"
    timestamp = str(int(time.time()))
    request = urllib.request.Request(url, data=body.encode(), method="POST", headers={
        "Content-Type": "application/json",
        "User-Agent": "TaskTracker-Webhooks/1.0",
        "X-Webhook-Timestamp": timestamp,
        "X-Webhook-Signature": sign(secret, timestamp, body),
        **headers,
    })
    try:
        with _opener.open(request, timeout=timeout_seconds()) as response:
            return response.status, ""
    except urllib.error.HTTPError as e:            # the receiver answered, with an error status
        return e.code, f"HTTP {e.code} {e.reason}"
    except (TimeoutError, socket.timeout):
        return None, f"Timed out after {timeout_seconds():g} s"
    except urllib.error.URLError as e:              # no answer: refused, DNS failure, timeout...
        reason = e.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return None, f"Timed out after {timeout_seconds():g} s"
        return None, f"Connection failed: {reason}"
    except OSError as e:
        return None, f"Connection failed: {e}"


def _claim(delivery_id):
    """Mark a due delivery as 'sending' so it's sent once, even if two workers run."""
    with get_conn() as conn:
        claimed = conn.execute(
            "UPDATE webhook_deliveries SET status = 'sending', updated_at = ? WHERE id = ? AND status = 'pending' RETURNING id",
            (_fmt(_now()), delivery_id),
        ).fetchone()
    return claimed is not None


def _attempt(delivery_id):
    if not _claim(delivery_id):
        return
    with get_conn() as conn:
        row = conn.execute(
            """SELECT d.*, w.url, w.secret FROM webhook_deliveries d JOIN webhooks w ON w.id = d.webhook_id
               WHERE d.id = ?""", (delivery_id,)).fetchone()
    if row is None:      # webhook deleted meanwhile
        return
    attempt = row["attempts"] + 1
    code, error = _send(row["url"], row["secret"], row["payload"], {
        "X-Webhook-Event": row["event"],
        "X-Webhook-Id": row["event_id"],
        "X-Webhook-Delivery": str(row["id"]),
        "X-Webhook-Attempt": str(attempt),
    })
    now = _now()
    delays = retry_delays()
    if code is not None and 200 <= code < 300:
        status, next_at, error = "succeeded", now, ""
    elif attempt <= len(delays):
        status, next_at = "pending", now + timedelta(seconds=delays[attempt - 1])
    else:
        status, next_at = "failed", now
    with get_conn() as conn:
        conn.execute(
            """UPDATE webhook_deliveries SET status = ?, attempts = ?, next_attempt_at = ?,
               last_status_code = ?, last_error = ?, updated_at = ? WHERE id = ?""",
            (status, attempt, _fmt(next_at), code, error[:500], _fmt(now), delivery_id),
        )
    level = logging.WARNING if status != "succeeded" else logging.INFO
    log_event("webhook_attempt", "system", level=level, delivery_id=delivery_id, webhook_id=row["webhook_id"],
              event=row["event"], attempt=attempt, result=status, status_code=code if code is not None else "-",
              error=error or "-", **({"retry_in_s": f"{delays[attempt - 1]:g}"} if status == "pending" else {}))


def process_due(limit=20):
    """Send every delivery that is due now. Returns how many were attempted."""
    with get_conn() as conn:
        due = conn.execute(
            "SELECT id FROM webhook_deliveries WHERE status = 'pending' AND next_attempt_at <= ? ORDER BY next_attempt_at LIMIT ?",
            (_fmt(_now()), limit),
        ).fetchall()
    for row in due:
        _attempt(row["id"])
    return len(due)


_wake = threading.Event()
_stop = threading.Event()
_thread = None


def _worker():
    log = logging.getLogger("tracker.webhooks")
    # A delivery left "sending" by a crash or restart is sent again.
    with get_conn() as conn:
        conn.execute("UPDATE webhook_deliveries SET status = 'pending' WHERE status = 'sending'")
    while not _stop.is_set():
        try:
            if process_due():
                continue
        except Exception:  # noqa: BLE001 - keep the worker alive (e.g. database briefly unavailable)
            log.exception("Webhook worker error")
        _wake.wait(poll_seconds())
        _wake.clear()


def start_worker():
    global _thread
    if _thread is None or not _thread.is_alive():
        _stop.clear()
        _thread = threading.Thread(target=_worker, name="webhook-worker", daemon=True)
        _thread.start()


def stop_worker():
    _stop.set()
    _wake.set()
    if _thread is not None:
        _thread.join(timeout=10)
