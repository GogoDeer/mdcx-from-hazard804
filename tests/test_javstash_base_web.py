import pytest

from mdcx.base import web as base_web
from mdcx.config.manager import manager


def test_check_javstash_api_key_empty(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(manager.config, "javstash_api_key", "")
    logged = []
    monkeypatch.setattr(base_web.signal, "show_log_text", logged.append)

    tips = base_web.check_javstash_api_key()
    assert "未填写 API Key" in tips
    assert len(logged) == 1
    assert "JavStash" in logged[0]


def test_check_javstash_api_key_dict_response_success(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(manager.config, "javstash_api_key", "valid_key")
    monkeypatch.setattr(manager.config, "javstash_url", "https://javstash.org")
    logged = []
    monkeypatch.setattr(base_web.signal, "show_log_text", logged.append)

    class FakeClient:
        async def post_json(self, endpoint, json_data=None, headers=None):
            return {"data": {"me": {"name": "gogodeer"}}}, ""

    class FakeComputed:
        async_client = FakeClient()

    class FakeLease:
        def __enter__(self):
            return FakeComputed()

        def __exit__(self, exc_type, exc_val, exc_tb):
            return None

    monkeypatch.setattr(manager, "acquire_computed", lambda: FakeLease())

    tips = base_web.check_javstash_api_key()
    assert "连接正常" in tips
    assert "gogodeer" in tips
    assert len(logged) == 1
    assert logged[0] == " ✅ JavStash 连接正常！欢迎，gogodeer"


def test_check_javstash_api_key_dict_response_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(manager.config, "javstash_api_key", "bad_key")
    monkeypatch.setattr(manager.config, "javstash_url", "https://javstash.org")
    logged = []
    monkeypatch.setattr(base_web.signal, "show_log_text", logged.append)

    class FakeClient:
        async def post_json(self, endpoint, json_data=None, headers=None):
            return {"errors": [{"message": "Invalid API key"}]}, ""

    class FakeComputed:
        async_client = FakeClient()

    class FakeLease:
        def __enter__(self):
            return FakeComputed()

        def __exit__(self, exc_type, exc_val, exc_tb):
            return None

    monkeypatch.setattr(manager, "acquire_computed", lambda: FakeLease())

    tips = base_web.check_javstash_api_key()
    assert "密钥无效" in tips
    assert len(logged) == 1
    assert logged[0].startswith(" ❌ JavStash")
