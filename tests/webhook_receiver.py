"""A fake webhook receiver for tests: a tiny HTTP server we fully control.

    fake.status = 500   -> answers every request with HTTP 500 (receiver is broken)
    fake.delay = 3      -> waits 3 s before answering (receiver is slow)
    fake.stop()         -> nothing listens on the port any more (receiver is down)
    fake.start()        -> back up on the same port and URL
    fake.requests       -> everything received: [{"headers": {...}, "body": "...", "json": {...}}]
"""
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeReceiver:
    def __init__(self):
        self.port = _free_port()
        self.url = f"http://127.0.0.1:{self.port}/hook"
        self.status = 200
        self.delay = 0
        self.requests = []
        self._lock = threading.Lock()
        self._server = None

    def start(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
                with fake._lock:
                    fake.requests.append({"headers": dict(self.headers), "body": body, "json": json.loads(body)})
                if fake.delay:
                    time.sleep(fake.delay)
                self.send_response(fake.status)
                self.end_headers()
                self.wfile.write(b"ok" if fake.status < 300 else b"error")

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def received(self, event=None, **match):
        """Requests for `event` whose data contains the given values (e.g. task_id=5)."""
        with self._lock:
            found = [r for r in self.requests if event is None or r["json"]["event"] == event]
        for key, value in match.items():
            found = [r for r in found if _lookup(r["json"]["data"], key) == value]
        return found


def _lookup(data, key):
    if key == "task_id":
        return data.get("task", {}).get("id", data.get("task_id"))
    return data.get(key)
