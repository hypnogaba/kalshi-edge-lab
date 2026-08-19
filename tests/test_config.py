import pytest

from common.config import get, kalshi_demo


def test_get_required_raises_when_missing(monkeypatch):
    monkeypatch.delenv("SOME_VAR", raising=False)
    with pytest.raises(RuntimeError):
        get("SOME_VAR", required=True)


def test_kalshi_demo_reads_env(monkeypatch):
    monkeypatch.setenv("KALSHI_DEMO_KEY_ID", "kid")
    monkeypatch.setenv("KALSHI_DEMO_PRIVATE_KEY_PATH", "secrets/x.pem")
    monkeypatch.setenv("KALSHI_DEMO_WS", "wss://demo/ws")
    monkeypatch.setenv("KALSHI_DEMO_API_BASE", "https://demo/api")
    cfg = kalshi_demo()
    assert cfg.key_id == "kid"
    assert cfg.private_key_path == "secrets/x.pem"
    assert cfg.ws_url == "wss://demo/ws"
    assert cfg.api_base == "https://demo/api"
