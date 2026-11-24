"""Test setup shared by every test (pytest loads this file automatically).

Starts a throwaway copy of the app on a free port with an empty temporary
database, so the tests never touch your real tracker.db.
"""
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from support import ADMIN_PASSWORD, ADMIN_USERNAME, Api, unique_name

ROOT = Path(__file__).resolve().parent.parent


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def app_server(tmp_path_factory):
    """Starts the test app. Gives its address and the file its output (incl. the audit log) goes to."""
    tmp = tmp_path_factory.mktemp("app")
    port = _free_port()
    env = {
        **os.environ,
        "TRACKER_DB": str(tmp / "test.db"),
        "ADMIN_USERNAME": ADMIN_USERNAME,
        "ADMIN_PASSWORD": ADMIN_PASSWORD,
        # Never test against a DATABASE_URL left in the shell (it could be production).
        # Only TEST_DATABASE_URL, set on purpose, runs the tests on PostgreSQL.
        "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", ""),
        # Test errors (some tests crash the app on purpose) must never reach Sentry.
        "SENTRY_DSN": "",
        # The test app never calls the real Claude API (no cost, no flaky answers).
        # AI logic is tested with a fake client in tests/unit; tests/live calls the real API on request.
        "ANTHROPIC_API_KEY": "",
        # Webhooks: retry after 0.5 s and 1 s (3 attempts), give up waiting after 1 s, check the
        # queue often, and allow 127.0.0.1 receivers, so the outage tests take seconds, not hours.
        "WEBHOOK_RETRY_DELAYS": "0.5,1",
        "WEBHOOK_TIMEOUT_SECONDS": "1",
        "WEBHOOK_POLL_SECONDS": "0.1",
        "WEBHOOK_BLOCK_PRIVATE_URLS": "false",
    }
    log_path = tmp / "server.log"
    with open(log_path, "w") as log:
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
        )
        url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 20
        while True:
            if server.poll() is not None:
                raise RuntimeError(f"The app crashed on startup, see {log_path}")
            try:
                if requests.get(url + "/login", timeout=1).status_code == 200:
                    break
            except requests.ConnectionError:
                pass
            if time.monotonic() > deadline:
                server.kill()
                raise RuntimeError(f"The app didn't start within 20 seconds, see {log_path}")
            time.sleep(0.2)

        yield SimpleNamespace(url=url, log_path=log_path)

        server.terminate()
        server.wait(timeout=10)


@pytest.fixture(scope="session")
def base_url(app_server):
    """The test app's address. Playwright uses it too, so page.goto("/login") just works."""
    return app_server.url


@pytest.fixture
def server_log(app_server):
    """Read the app's output so far, e.g. to check what the audit log recorded."""
    return lambda: app_server.log_path.read_text(encoding="utf-8", errors="replace")


@pytest.fixture
def anon(base_url):
    """API client with no token (a signed-out visitor)."""
    return Api(base_url)


@pytest.fixture(scope="session")
def admin(base_url):
    """API client signed in as the admin."""
    return Api(base_url).login(ADMIN_USERNAME, ADMIN_PASSWORD)


@pytest.fixture
def user(base_url, admin):
    """A brand-new regular user for one test; deleted again afterwards."""
    username, password = unique_name(), secrets.token_urlsafe(12)
    res = Api(base_url).post("/api/auth/signup", json={"username": username, "password": password})
    res.raise_for_status()
    account = SimpleNamespace(
        id=res.json()["id"],
        username=username,
        password=password,
        api=Api(base_url).login(username, password),
    )
    yield account
    admin.delete(f"/api/admin/users/{account.id}")


@pytest.fixture
def task(user, admin):
    """A task created by `user`; deleted again afterwards."""
    res = user.api.post("/api/tasks", json={"title": unique_name("Task")})
    res.raise_for_status()
    created = res.json()
    yield created
    admin.delete(f"/api/tasks/{created['id']}")


@pytest.fixture
def receiver():
    """A fake webhook receiver (like webhook.site) that a test can make work, fail, slow down or go offline."""
    from webhook_receiver import FakeReceiver
    fake = FakeReceiver()
    fake.start()
    yield fake
    fake.stop()
