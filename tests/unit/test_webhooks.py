"""Webhook signing and URL safety, without any server."""
import pytest

from app import webhooks


def test_signature_round_trip_and_tampering():
    secret, ts, body = "whsec_test", "1764000000", '{"event":"task.created"}'
    signature = webhooks.sign(secret, ts, body)
    assert signature.startswith("sha256=") and len(signature) == 7 + 64
    assert webhooks.verify(secret, ts, body, signature)
    assert not webhooks.verify(secret, ts, body + " ", signature)        # body changed
    assert not webhooks.verify(secret, "1764000001", body, signature)    # timestamp changed
    assert not webhooks.verify("whsec_other", ts, body, signature)       # wrong secret
    assert not webhooks.verify(secret, ts, body, None)


def test_retry_delays_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("WEBHOOK_RETRY_DELAYS", "1, 5,30")
    assert webhooks.retry_delays() == [1, 5, 30]
    monkeypatch.setenv("WEBHOOK_RETRY_DELAYS", "nonsense")
    assert webhooks.retry_delays() == [10, 60, 300, 1800]


def test_private_addresses_are_blocked_when_enabled(monkeypatch):
    monkeypatch.setenv("WEBHOOK_BLOCK_PRIVATE_URLS", "true")
    code, error = webhooks._send("http://127.0.0.1:9/hook", "s", "{}", {})
    assert code is None and "private network" in error


@pytest.mark.parametrize("on_render, expected", [(True, True), (False, False)])
def test_private_blocking_defaults_on_only_on_render(monkeypatch, on_render, expected):
    monkeypatch.delenv("WEBHOOK_BLOCK_PRIVATE_URLS", raising=False)
    if on_render:
        monkeypatch.setenv("RENDER", "true")
    else:
        monkeypatch.delenv("RENDER", raising=False)
    assert webhooks.block_private_urls() is expected
