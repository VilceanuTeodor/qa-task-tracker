"""Helpers shared by the API and UI tests."""
import uuid

import requests

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "test-admin-password"


def unique_name(prefix="qa"):
    """A username/title that no other test uses, so tests never clash."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class Api:
    """A tiny client for the app's JSON API. Sends the bearer token if it has one."""

    def __init__(self, base_url, token=None):
        self.base_url = base_url
        self.session = requests.Session()
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def request(self, method, path, **kwargs):
        return self.session.request(method, self.base_url + path, timeout=10, **kwargs)

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def post(self, path, **kwargs):
        return self.request("POST", path, **kwargs)

    def patch(self, path, **kwargs):
        return self.request("PATCH", path, **kwargs)

    def delete(self, path, **kwargs):
        return self.request("DELETE", path, **kwargs)

    def login(self, username, password):
        """Log in and return a new Api that acts as that user."""
        res = self.post("/api/auth/login", json={"username": username, "password": password})
        res.raise_for_status()
        return Api(self.base_url, res.json()["access_token"])


def delete_user_named(admin, username):
    """Clean up an account a test created through the UI."""
    for account in admin.get("/api/admin/users").json():
        if account["username"] == username:
            admin.delete(f"/api/admin/users/{account['id']}")


def sign_in(page, username, password):
    """Sign in through the real login form."""
    page.goto("/login")
    page.get_by_test_id("input-username").fill(username)
    page.get_by_test_id("input-password").fill(password)
    page.get_by_test_id("submit-login").click()
