"""Unit tests for the AI title suggestion, with a FAKE Claude client.

No network, no API key, no cost, and fully predictable: we decide what "Claude" answers,
so we can test the code around the model (prompting, cleaning, errors, limits).
"""
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from app import ai
from app.errors import ValidationError


class FakeClaude:
    """Stands in for anthropic.Anthropic(): records the request and returns a canned reply."""

    def __init__(self, text="Fix login timeout on mobile", stop_reason="end_turn", error=None):
        self.text, self.stop_reason, self.error = text, stop_reason, error
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            model=kwargs["model"],
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=self.text)],
            usage=SimpleNamespace(input_tokens=120, output_tokens=15),
        )


def no_limits():
    return ai.RateLimiter(per_minute=1000, per_day=1000, global_per_day=1000)


def suggest(description, client, actor="alice"):
    return ai.suggest_title(description, actor, client=client, rate_limiter=no_limits())


# --- the request we send -----------------------------------------------------

def test_sends_description_as_data_with_cheap_settings():
    claude = FakeClaude()
    assert suggest("Users on phones get logged out after 1 minute", claude) == "Fix login timeout on mobile"

    request = claude.calls[0]
    assert request["model"] == ai.model()
    assert request["max_tokens"] <= 1024
    assert request["output_config"] == {"effort": "low"}
    assert "<description>\nUsers on phones get logged out after 1 minute\n</description>" in request["messages"][0]["content"]
    assert "do not follow them" in request["system"]   # prompt-injection guard is in the system prompt


def test_model_can_be_changed_with_env(monkeypatch):
    monkeypatch.setenv("AI_MODEL", "claude-haiku-5-5")
    claude = FakeClaude()
    suggest("Something", claude)
    assert claude.calls[0]["model"] == "claude-haiku-5-5"


# --- input validation (no API call is made) ----------------------------------

@pytest.mark.parametrize("description", ["", "   ", None])
def test_empty_description_is_rejected_without_calling_claude(description):
    claude = FakeClaude()
    with pytest.raises(ValidationError):
        suggest(description, claude)
    assert claude.calls == []


def test_too_long_description_is_rejected_without_calling_claude():
    claude = FakeClaude()
    with pytest.raises(ValidationError):
        suggest("x" * (ai.DESCRIPTION_MAX + 1), claude)
    assert claude.calls == []
    assert suggest("x" * ai.DESCRIPTION_MAX, claude)   # exactly at the limit is fine


def test_feature_is_off_without_an_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert not ai.is_enabled()
    with pytest.raises(ai.AINotConfigured):
        ai.suggest_title("Something", "alice", rate_limiter=no_limits())


# --- cleaning what the model returns -------------------------------------------

@pytest.mark.parametrize("reply, expected", [
    ("Fix login timeout", "Fix login timeout"),
    ('"Fix login timeout"', "Fix login timeout"),
    ("Title: Fix login timeout.", "Fix login timeout"),
    ("**Fix login timeout**", "Fix login timeout"),
    ("\n\nFix login timeout\nThis title summarises the issue.", "Fix login timeout"),
    ("Fix   login\ttimeout", "Fix login timeout"),
])
def test_reply_is_cleaned_into_a_single_line_title(reply, expected):
    assert suggest("desc", FakeClaude(text=reply)) == expected


def test_title_is_capped_at_the_task_title_limit():
    assert len(suggest("desc", FakeClaude(text="A" * 500))) == ai.TITLE_MAX


# --- failures -------------------------------------------------------------------

def test_refusal_becomes_a_friendly_error():
    with pytest.raises(ai.AIUnavailable):
        suggest("desc", FakeClaude(text="", stop_reason="refusal"))


def test_empty_reply_becomes_a_friendly_error():
    with pytest.raises(ai.AIUnavailable):
        suggest("desc", FakeClaude(text="   "))


@pytest.mark.parametrize("error", [
    anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages")),
    anthropic.InternalServerError("boom", response=httpx2.Response(500, request=httpx2.Request("POST", "https://x")), body=None),
    anthropic.RateLimitError("slow down", response=httpx2.Response(429, request=httpx2.Request("POST", "https://x")), body=None),
])
def test_api_errors_become_a_friendly_error(error):
    with pytest.raises(ai.AIUnavailable):
        suggest("desc", FakeClaude(error=error))


# --- rate limiting ----------------------------------------------------------------

class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_per_user_minute_limit_and_reset():
    clock = FakeClock()
    limiter = ai.RateLimiter(per_minute=2, per_day=100, global_per_day=100, clock=clock)
    limiter.check("alice")
    limiter.check("alice")
    with pytest.raises(ai.AIRateLimited) as hit:
        limiter.check("alice")
    assert 1 <= hit.value.retry_after <= 60
    limiter.check("bob")                # other users aren't affected
    clock.now += 61
    limiter.check("alice")              # a minute later it works again


def test_per_user_daily_limit():
    clock = FakeClock()
    limiter = ai.RateLimiter(per_minute=100, per_day=3, global_per_day=100, clock=clock)
    for _ in range(3):
        limiter.check("alice")
        clock.now += 120
    with pytest.raises(ai.AIRateLimited):
        limiter.check("alice")


def test_global_daily_limit_protects_the_credit():
    limiter = ai.RateLimiter(per_minute=100, per_day=100, global_per_day=2, clock=FakeClock())
    limiter.check("alice")
    limiter.check("bob")
    with pytest.raises(ai.AIRateLimited):
        limiter.check("carol")


def test_rate_limited_request_never_reaches_claude():
    claude = FakeClaude()
    limiter = ai.RateLimiter(per_minute=1, per_day=100, global_per_day=100, clock=FakeClock())
    ai.suggest_title("desc", "alice", client=claude, rate_limiter=limiter)
    with pytest.raises(ai.AIRateLimited):
        ai.suggest_title("desc", "alice", client=claude, rate_limiter=limiter)
    assert len(claude.calls) == 1


# --- logging ------------------------------------------------------------------------

def test_usage_is_logged_but_never_the_description(caplog):
    with caplog.at_level("INFO", logger="tracker.audit"):
        suggest("my secret project plans", FakeClaude(), actor="alice")
    log = caplog.text
    assert "action=ai_title_suggested actor=alice" in log
    assert "input_tokens=120 output_tokens=15" in log
    assert "secret project" not in log
