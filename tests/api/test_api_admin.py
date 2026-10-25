"""Admin-only endpoints and the permission rules around them."""
import pytest

from support import Api, unique_name


@pytest.mark.parametrize("method, path", [
    ("GET", "/api/admin/stats"),
    ("GET", "/api/admin/users"),
    ("PATCH", "/api/admin/users/1"),
    ("DELETE", "/api/admin/users/1"),
])
def test_regular_users_are_forbidden(user, method, path):
    res = user.api.request(method, path, json={"role": "user"})

    assert res.status_code == 403
    assert res.json()["detail"] == "Admin access required"


def test_stats_add_up(admin, task):
    stats = admin.get("/api/admin/stats").json()

    assert set(stats["tasks_by_status"]) == {"To Do", "In Progress", "In Review", "Done"}
    assert sum(stats["tasks_by_status"].values()) == stats["total_tasks"]
    assert stats["total_tasks"] >= 1
    assert stats["total_users"] >= 2


def test_user_list_never_exposes_password_hashes(admin, user):
    res = admin.get("/api/admin/users")

    assert user.id in [u["id"] for u in res.json()]
    assert "password" not in res.text and "pbkdf2" not in res.text


def test_promote_and_demote_a_user(admin, user):
    promoted = admin.patch(f"/api/admin/users/{user.id}", json={"role": "admin"})
    assert promoted.status_code == 200 and promoted.json()["role"] == "admin"
    assert user.api.get("/api/admin/stats").status_code == 200, "new admin gets admin access"

    demoted = admin.patch(f"/api/admin/users/{user.id}", json={"role": "user"})
    assert demoted.json()["role"] == "user"
    assert user.api.get("/api/admin/stats").status_code == 403


def test_invalid_role_is_rejected(admin, user):
    assert admin.patch(f"/api/admin/users/{user.id}", json={"role": "superuser"}).status_code == 422


def test_admin_cannot_demote_or_delete_themselves(admin):
    me = admin.get("/api/auth/me").json()

    demote = admin.patch(f"/api/admin/users/{me['id']}", json={"role": "user"})
    delete = admin.delete(f"/api/admin/users/{me['id']}")

    assert demote.status_code == 422 and "own role" in demote.json()["detail"]
    assert delete.status_code == 422 and "own account" in delete.json()["detail"]


def test_deleting_a_user_signs_them_out(admin, base_url):
    username = unique_name()
    signup = Api(base_url).post("/api/auth/signup", json={"username": username, "password": "long-enough-pw"})
    victim = Api(base_url).login(username, "long-enough-pw")

    assert admin.delete(f"/api/admin/users/{signup.json()['id']}").status_code == 204
    assert victim.get("/api/auth/me").status_code == 401


def test_delete_missing_user_returns_404(admin):
    assert admin.delete("/api/admin/users/999999").status_code == 404
