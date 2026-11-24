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
def base_url(tmp_path_factory):
    """The test app's address. Playwright uses it too, so page.goto("/login") just works."""
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

        yield url

        server.terminate()
        server.wait(timeout=10)


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
