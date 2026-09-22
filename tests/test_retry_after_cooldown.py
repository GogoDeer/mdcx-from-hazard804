"""429/503 Retry-After 冷却回归：解析、记录、发请求前等待、上限截断。

站点明确回 Retry-After 时按其值暂停该 host 的请求（跨协程共享截止点），
冷却等待发生在限速桶之前；无 Retry-After 头时行为与旧版一致。
"""

import asyncio
import time
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from types import SimpleNamespace

import pytest

import mdcx.web_async as web_async_mod
from mdcx.web_async import AsyncWebClient


def _resp(status_code: int, headers: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(status_code=status_code, headers=headers or {}, content=b"x", url="")


def _install_fake_sleep(monkeypatch) -> list[float]:
    """记录所有 asyncio.sleep 请求秒数并让真实等待跳过。"""
    sleeps: list[float] = []
    real_sleep = asyncio.sleep

    async def fake_sleep(delay, *args, **kwargs):
        sleeps.append(float(delay))
        return await real_sleep(0)

    monkeypatch.setattr(web_async_mod.asyncio, "sleep", fake_sleep)
    return sleeps


def _bare_client() -> AsyncWebClient:
    client = AsyncWebClient(timeout=1)

    async def _noop(*args, **kwargs):
        return None

    client._record_retryable_response_failure = _noop
    return client


def test_parse_retry_after_seconds_variants():
    client = _bare_client()
    client._retry_after_cap_seconds = 60.0

    assert client._parse_retry_after_seconds(_resp(429, {"Retry-After": "30"})) == 30.0
    assert client._parse_retry_after_seconds(_resp(429, {"Retry-After": "9999"})) == 60.0
    assert client._parse_retry_after_seconds(_resp(429, {"Retry-After": "0"})) is None
    assert client._parse_retry_after_seconds(_resp(429, {})) is None
    assert client._parse_retry_after_seconds(_resp(429, {"Retry-After": "garbage"})) is None

    future = format_datetime(datetime.now(UTC) + timedelta(seconds=20), usegmt=True)
    parsed = client._parse_retry_after_seconds(_resp(429, {"Retry-After": future}))
    assert parsed is not None
    assert 15.0 <= parsed <= 21.0, f"HTTP-date 应折算为 ~20s，实际 {parsed}"


@pytest.mark.asyncio
async def test_429_with_retry_after_cooldowns_host_and_recovers(monkeypatch):
    """首个请求 429 带 Retry-After：记录冷却、重试在冷却点后发出、随后成功。"""
    client = _bare_client()
    sleeps = _install_fake_sleep(monkeypatch)
    responses = [_resp(429, {"Retry-After": "20"}), _resp(200)]

    async def fake_curl_request(**kwargs):
        return responses.pop(0)

    client._curl_request = fake_curl_request

    resp, error = await asyncio.wait_for(client.request("GET", "https://example.com/page"), timeout=5)

    assert resp is not None and resp.status_code == 200, f"429 冷却后应重试成功: {error}"
    until = client._retry_after_until.get("example.com")
    assert until is not None and until > time.monotonic() + 15, "Retry-After 冷却截止点未记录"
    assert any(s >= 15 for s in sleeps), f"重试等待未按 Retry-After 冷却: {sleeps}"


@pytest.mark.asyncio
async def test_cooldown_holds_next_request_before_send(monkeypatch):
    """冷却期内新请求必须先等待再出网（含并发兄弟请求共享截止点）。"""
    client = _bare_client()
    sleeps = _install_fake_sleep(monkeypatch)
    client._retry_after_until["example.com"] = time.monotonic() + 30

    calls = {"n": 0}

    async def fake_curl_request(**kwargs):
        calls["n"] += 1
        return _resp(200)

    client._curl_request = fake_curl_request

    resp, _error = await asyncio.wait_for(client.request("GET", "https://example.com/page"), timeout=5)

    assert resp is not None
    assert calls["n"] == 1
    assert any(s >= 29 for s in sleeps), f"发送前未等待剩余冷却: {sleeps}"


@pytest.mark.asyncio
async def test_429_without_retry_after_header_keeps_old_behavior(monkeypatch):
    """无 Retry-After 头的 429：记录旧行为不变，不写冷却表。"""
    client = _bare_client()
    _install_fake_sleep(monkeypatch)
    responses = [_resp(429), _resp(200)]

    async def fake_curl_request(**kwargs):
        return responses.pop(0)

    client._curl_request = fake_curl_request

    resp, error = await asyncio.wait_for(client.request("GET", "https://example.com/page"), timeout=5)

    assert resp is not None and resp.status_code == 200, f"无头 429 应照常重试成功: {error}"
    assert "example.com" not in client._retry_after_until
