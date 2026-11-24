"""The title-suggestion endpoints, as a client sees them. The test app has no API key, so
these check the safe behaviour around the feature; the AI logic itself is in tests/unit."""
import requests

from support import Api


def test_api_requires_login(anon):
    assert anon.post("/api/ai/suggest-title", json={"description": "x"}).status_code == 401


def test_api_says_not_configured_without_a_key(user):
    res = user.api.post("/api/ai/suggest-title", json={"description": "Users get logged out too soon"})
    assert res.status_code == 503
    assert "not configured" in res.json()["detail"]


def test_api_rejects_a_missing_description(user):
    assert user.api.post("/api/ai/suggest-title", json={}).status_code == 422


def test_web_route_requires_login(base_url):
    res = requests.post(f"{base_url}/tasks/suggest-title", json={"description": "x"}, allow_redirects=False)
    assert res.status_code == 303 and "/login" in res.headers["location"]


def test_key_is_never_exposed_in_pages_or_docs(base_url, user):
    # The page and the API schema must not contain anything that looks like an Anthropic key.
    page = requests.get(f"{base_url}/login").text
    schema = Api(base_url).get("/openapi.json").text
    assert "sk-ant-" not in page and "sk-ant-" not in schema


def test_api_accepts_previous_titles_but_not_unlimited_ones(user):
    ok = user.api.post("/api/ai/suggest-title", json={"description": "x", "previous": ["A", "B"]})
    assert ok.status_code == 503   # accepted by the schema; only "not configured" in the test app
    too_many = user.api.post("/api/ai/suggest-title", json={"description": "x", "previous": ["t"] * 21})
    assert too_many.status_code == 422
