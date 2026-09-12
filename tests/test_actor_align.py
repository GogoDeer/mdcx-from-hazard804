"""媒体服务器演员对齐模块单元测试。"""

from __future__ import annotations

import httpx
import pytest

from mdcx.config.manager import manager
from mdcx.core.actor_align import (
    align_actor_with_media_server,
    clear_media_server_actor_cache,
)
from mdcx.core.translate import map_actor_names
from mdcx.models.model_types import CrawlersResult


@pytest.fixture(autouse=True)
def _reset_align_cache():
    """每次测试前重置缓存，防止测试间污染。"""
    clear_media_server_actor_cache()
    yield
    clear_media_server_actor_cache()


def test_disabled_by_config(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(manager.config, "align_media_server_actors", False)
    monkeypatch.setattr(manager.config, "api_key", "test-key")
    monkeypatch.setattr(manager.config, "emby_url", "http://127.0.0.1:8096")

    actor_data = {
        "zh_cn": "神无月丽奈",
        "jp": "神無月れな",
        "keyword": ["折原ほのか"],
    }
    result = align_actor_with_media_server("折原ほのか", "神无月丽奈", actor_data)
    assert result == "神无月丽奈"


def test_missing_api_key_or_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(manager.config, "align_media_server_actors", True)
    monkeypatch.setattr(manager.config, "api_key", "")
    monkeypatch.setattr(manager.config, "emby_url", "http://127.0.0.1:8096")

    actor_data = {"zh_cn": "神无月丽奈", "keyword": ["折原ほのか"]}
    assert align_actor_with_media_server("折原ほのか", "神无月丽奈", actor_data) == "神无月丽奈"

    monkeypatch.setattr(manager.config, "api_key", "test-key")
    monkeypatch.setattr(manager.config, "emby_url", "")
    assert align_actor_with_media_server("折原ほのか", "神无月丽奈", actor_data) == "神无月丽奈"


def test_single_match_aligned(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(manager.config, "align_media_server_actors", True)
    monkeypatch.setattr(manager.config, "api_key", "test-key")
    monkeypatch.setattr(manager.config, "emby_url", "http://127.0.0.1:8096")
    monkeypatch.setattr(manager.config, "server_type", "jellyfin")

    fake_persons_response = {
        "Items": [
            {"Name": "折原ほのか", "Id": "p1"},
            {"Name": "白石真琴", "Id": "p2"},
        ]
    }

    def fake_get(url: str, headers=None, params=None):
        req = httpx.Request("GET", url, params=params)
        if "/Persons" in url:
            return httpx.Response(200, json=fake_persons_response, request=req)
        return httpx.Response(404, request=req)

    monkeypatch.setattr(httpx.Client, "get", lambda self, url, **kwargs: fake_get(url, **kwargs))

    actor_data = {
        "zh_cn": "神无月丽奈",
        "jp": "神無月れな",
        "keyword": ["折原ほのか", "大谷桜"],
    }
    result = align_actor_with_media_server("折原ほのか", "神无月丽奈", actor_data)
    assert result == "折原ほのか"


def test_multi_match_picks_highest_movie_count(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(manager.config, "align_media_server_actors", True)
    monkeypatch.setattr(manager.config, "api_key", "test-key")
    monkeypatch.setattr(manager.config, "emby_url", "http://127.0.0.1:8096")
    monkeypatch.setattr(manager.config, "server_type", "jellyfin")

    fake_persons_response = {
        "Items": [
            {"Name": "折原ほのか", "Id": "p1"},
            {"Name": "神无月丽奈", "Id": "p2"},
        ]
    }

    def fake_get(url: str, headers=None, params=None):
        req = httpx.Request("GET", url, params=params)
        if "/Persons" in url:
            return httpx.Response(200, json=fake_persons_response, request=req)
        if "/Items" in url:
            person = (params or {}).get("Person")
            count = 14 if person == "折原ほのか" else (5 if person == "神无月丽奈" else 0)
            return httpx.Response(200, json={"TotalRecordCount": count}, request=req)
        return httpx.Response(404, request=req)

    monkeypatch.setattr(httpx.Client, "get", lambda self, url, **kwargs: fake_get(url, **kwargs))

    actor_data = {
        "zh_cn": "神无月丽奈",
        "jp": "神無月れな",
        "keyword": ["折原ほのか"],
    }
    result = align_actor_with_media_server("折原ほのか", "神无月丽奈", actor_data)
    assert result == "折原ほのか"


def test_no_match_returns_mapped_name(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(manager.config, "align_media_server_actors", True)
    monkeypatch.setattr(manager.config, "api_key", "test-key")
    monkeypatch.setattr(manager.config, "emby_url", "http://127.0.0.1:8096")

    fake_persons_response = {
        "Items": [
            {"Name": "其他演员A", "Id": "p1"},
            {"Name": "其他演员B", "Id": "p2"},
        ]
    }

    def fake_get(url: str, headers=None, params=None):
        req = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json=fake_persons_response, request=req)

    monkeypatch.setattr(httpx.Client, "get", lambda self, url, **kwargs: fake_get(url, **kwargs))

    actor_data = {
        "zh_cn": "神无月丽奈",
        "jp": "神無月れな",
        "keyword": ["折原ほのか"],
    }
    result = align_actor_with_media_server("折原ほのか", "神无月丽奈", actor_data)
    assert result == "神无月丽奈"


def test_network_error_graceful_fallback(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(manager.config, "align_media_server_actors", True)
    monkeypatch.setattr(manager.config, "api_key", "test-key")
    monkeypatch.setattr(manager.config, "emby_url", "http://127.0.0.1:8096")

    def fake_get_error(url: str, **kwargs):
        raise httpx.ConnectTimeout("Connection timed out")

    monkeypatch.setattr(httpx.Client, "get", fake_get_error)

    actor_data = {
        "zh_cn": "神无月丽奈",
        "jp": "神無月れな",
        "keyword": ["折原ほのか"],
    }
    result = align_actor_with_media_server("折原ほのか", "神无月丽奈", actor_data)
    assert result == "神无月丽奈"


def test_caching_behavior(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(manager.config, "align_media_server_actors", True)
    monkeypatch.setattr(manager.config, "api_key", "test-key")
    monkeypatch.setattr(manager.config, "emby_url", "http://127.0.0.1:8096")

    call_count = {"persons": 0}

    def fake_get(url: str, headers=None, params=None):
        req = httpx.Request("GET", url, params=params)
        if "/Persons" in url:
            call_count["persons"] += 1
            return httpx.Response(200, json={"Items": [{"Name": "折原ほのか", "Id": "p1"}]}, request=req)
        return httpx.Response(404, request=req)

    monkeypatch.setattr(httpx.Client, "get", lambda self, url, **kwargs: fake_get(url, **kwargs))

    actor_data = {"zh_cn": "神无月丽奈", "keyword": ["折原ほのか"]}
    # First call triggers network
    res1 = align_actor_with_media_server("折原ほのか", "神无月丽奈", actor_data)
    assert res1 == "折原ほのか"
    assert call_count["persons"] == 1

    # Second call should hit memory cache directly
    res2 = align_actor_with_media_server("折原ほのか", "神无月丽奈", actor_data)
    assert res2 == "折原ほのか"
    assert call_count["persons"] == 1


def test_map_actor_names_integration(monkeypatch: pytest.MonkeyPatch):
    from mdcx.config.resources import resources

    monkeypatch.setattr(manager.config, "align_media_server_actors", True)
    monkeypatch.setattr(manager.config, "api_key", "test-key")
    monkeypatch.setattr(manager.config, "emby_url", "http://127.0.0.1:8096")

    # Mock server response with 折原ほのか
    def fake_get(url: str, headers=None, params=None):
        req = httpx.Request("GET", url, params=params)
        return httpx.Response(200, json={"Items": [{"Name": "折原ほのか", "Id": "p1"}]}, request=req)

    monkeypatch.setattr(httpx.Client, "get", lambda self, url, **kwargs: fake_get(url, **kwargs))

    # Mock get_actor_data to return 折原ほのか info
    def fake_get_actor_data(name: str):
        if name == "折原ほのか":
            return {
                "zh_cn": "神无月丽奈",
                "jp": "神無月れな",
                "zh_tw": "神無月麗奈",
                "keyword": ["折原ほのか"],
                "has_name": True,
            }
        return {"zh_cn": name, "jp": name, "zh_tw": name, "keyword": [name], "has_name": False}

    monkeypatch.setattr(resources, "get_actor_data", fake_get_actor_data)

    res = CrawlersResult.empty()
    res.number = "060526-001"
    res.title = "测试影片"
    res.actors = ["折原ほのか"]
    res.all_actors = ["折原ほのか"]

    map_actor_names(res)
    assert res.actors == ["折原ほのか"]
    assert res.actor == "折原ほのか"
