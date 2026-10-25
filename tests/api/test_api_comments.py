"""Comments on tasks through the JSON API."""


def test_add_comment(user, task):
    res = user.api.post(f"/api/tasks/{task['id']}/comments", json={"body": "Reproduced on Chrome"})

    assert res.status_code == 201
    comment = res.json()
    assert comment["body"] == "Reproduced on Chrome"
    assert comment["author"] == user.username, "author comes from the token"
    assert comment["task_id"] == task["id"]


def test_comment_appears_in_list_and_history(user, task):
    comment = user.api.post(f"/api/tasks/{task['id']}/comments", json={"body": "Looks fixed"}).json()

    comments = user.api.get(f"/api/tasks/{task['id']}/comments").json()
    history = user.api.get(f"/api/tasks/{task['id']}/history").json()

    assert comment["id"] in [c["id"] for c in comments]
    assert history[-1]["message"] == "Comment added"


def test_empty_comment_is_rejected(user, task):
    res = user.api.post(f"/api/tasks/{task['id']}/comments", json={"body": "   "})

    assert res.status_code == 422
    assert "Comment is required" in res.json()["detail"]


def test_comment_on_missing_task_returns_404(user):
    assert user.api.post("/api/tasks/999999/comments", json={"body": "Hello?"}).status_code == 404
