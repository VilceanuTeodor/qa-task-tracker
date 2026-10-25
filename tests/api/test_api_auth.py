"""Sign-up, log-in, tokens and log-out through the JSON API."""
import pytest

from support import unique_name


def test_sign_up_creates_a_regular_user(anon, admin):
    username = unique_name()
    res = anon.post("/api/auth/signup", json={"username": username, "password": "long-enough-pw"})

    assert res.status_code == 201
    body = res.json()
    assert body["username"] == username
    assert body["role"] == "user"
    assert "password" not in body and "password_hash" not in body
    admin.delete(f"/api/admin/users/{body['id']}")


def test_usernames_are_unique_ignoring_case(anon, user):
    res = anon.post("/api/auth/signup", json={"username": user.username.upper(), "password": "long-enough-pw"})

    assert res.status_code == 422
    assert "already taken" in res.json()["detail"]


@pytest.mark.parametrize("username, password, message", [
    ("ab", "long-enough-pw", "Username must be"),
    ("has spaces", "long-enough-pw", "Username must be"),
    ("x" * 31, "long-enough-pw", "Username must be"),
    ("valid_name", "short", "at least 8"),
    ("valid_name", "x" * 129, "at most 128"),
])
def test_sign_up_rejects_invalid_input(anon, username, password, message):
    res = anon.post("/api/auth/signup", json={"username": username, "password": password})

    assert res.status_code == 422
    assert message in res.json()["detail"]


def test_log_in_returns_a_bearer_token(anon, user):
    res = anon.post("/api/auth/login", json={"username": user.username, "password": user.password})

    assert res.status_code == 200
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["username"] == user.username


def test_wrong_password_and_unknown_user_get_the_same_error(anon, user):
    """The error must not reveal whether a username exists."""
    wrong_password = anon.post("/api/auth/login", json={"username": user.username, "password": "wrong-password"})
    unknown_user = anon.post("/api/auth/login", json={"username": unique_name(), "password": "wrong-password"})

    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json() == unknown_user.json() == {"detail": "Invalid username or password"}


def test_me_returns_the_signed_in_user(user):
    res = user.api.get("/api/auth/me")

    assert res.status_code == 200
    assert res.json()["username"] == user.username


@pytest.mark.parametrize("method, path", [
    ("GET", "/api/tasks"),
    ("POST", "/api/tasks"),
    ("GET", "/api/tasks/1"),
    ("GET", "/api/users"),
    ("GET", "/api/auth/me"),
    ("GET", "/api/admin/stats"),
])
def test_requests_without_a_token_are_rejected(anon, method, path):
    assert anon.request(method, path).status_code == 401


def test_a_made_up_token_is_rejected(anon):
    res = anon.get("/api/tasks", headers={"Authorization": "Bearer not-a-real-token"})

    assert res.status_code == 401


def test_log_out_invalidates_the_token(user):
    assert user.api.post("/api/auth/logout").status_code == 204
    assert user.api.get("/api/auth/me").status_code == 401
