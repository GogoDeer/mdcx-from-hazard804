"""#22 爬虫 recording 回放：夹具命中/镜像忽略 host/未命中/JSON POST，以及整链离线回放。

三条整链样例覆盖两种请求形态：
- xcity：HTTP 404 → HTML 回退链（ABF-050，真实站点抓取样本）；
- avmoo：JSON API 两段 POST（search + getMovie）；
- javdb_api：镜像轮询链——录像 host 与运行时轮换域名错位，靠忽略 host 的匹配命中。

录像归档在 tests/crawlers/data/recordings/<site>/<number>.json；真站重录用
RecordingClient 包裹 AsyncWebClient 后 save_cassette 覆盖同名文件。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mdcx.crawlers.avmoo import AvmooCrawler
from mdcx.crawlers.javdb_api import JavdbApiCrawler
from mdcx.crawlers.xcity import XcityCrawler
from mdcx.models.model_types import CrawlerInput
from tests.crawlers.recording import (
    Cassette,
    Interaction,
    RecordingClient,
    ReplayClient,
    load_cassette,
    save_cassette,
)

DATA_DIR = Path(__file__).resolve().parent / "data"
RECORDINGS = DATA_DIR / "recordings"


def test_replay_get_text_exact_url_hit():
    cassette = Cassette(
        site="demo",
        number="X",
        interactions=[
            Interaction(method="GET", url="https://a.example/page", body="<html>ok</html>"),
        ],
    )
    client = ReplayClient(cassette)
    text, error = _run(client.get_text("https://a.example/page"))
    assert error == ""
    assert text == "<html>ok</html>"


def test_replay_get_text_ignores_host_for_mirrors():
    """javdb_api 一类镜像轮询：同一 path+query 换 host 应命中同一条录像。"""
    cassette = Cassette(
        interactions=[
            Interaction(method="GET", url="https://mirror1.example/search?q=1&f=all", body="hit"),
        ],
    )
    client = ReplayClient(cassette)
    text, error = _run(client.get_text("https://mirror2.example/search?f=all&q=1"))
    assert error == ""
    assert text == "hit"


def test_replay_miss_returns_none_and_error():
    client = ReplayClient(Cassette())
    text, error = _run(client.get_text("https://missing.example/x"))
    assert text is None
    assert "cassette miss" in error
    assert "GET" in error


def test_replay_get_json_and_post_json():
    cassette = Cassette(
        interactions=[
            Interaction(
                method="GET",
                url="https://api.example/item",
                content_type="application/json",
                body={"ok": True, "n": 1},
            ),
            Interaction(
                method="POST",
                url="https://api.example/search",
                content_type="application/json",
                body={"code": 200, "data": [{"id": "a"}]},
            ),
        ],
    )
    client = ReplayClient(cassette)
    data, error = _run(client.get_json("https://api.example/item"))
    assert error == ""
    assert data == {"ok": True, "n": 1}
    data, error = _run(client.post_json("https://api.example/search", data="[]"))
    assert error == ""
    assert data["data"][0]["id"] == "a"


def test_cassette_roundtrip_on_disk(tmp_path: Path):
    cassette = Cassette(
        site="demo",
        number="N-1",
        recorded_at="2026-09-23T00:00:00+00:00",
        interactions=[
            Interaction(method="GET", url="https://a.example/", body="<p>hi</p>"),
        ],
    )
    path = tmp_path / "demo.json"
    save_cassette(path, cassette)
    loaded = load_cassette(path)
    assert loaded.site == "demo"
    assert loaded.number == "N-1"
    text, error = _run(ReplayClient(loaded).get_text("https://a.example/"))
    assert error == ""
    assert text == "<p>hi</p>"


@pytest.mark.asyncio
async def test_recording_client_wraps_inner_and_dumps_cassette():
    class Stub:
        async def get_text(self, url: str, **kwargs):
            return f"body:{url}", ""

    recorder = RecordingClient(Stub())
    text, error = await recorder.get_text("https://rec.example/a")
    assert text == "body:https://rec.example/a"
    assert error == ""
    cassette = recorder.to_cassette(site="rec", number="A")
    assert cassette.site == "rec"
    assert len(cassette.interactions) == 1
    replay = ReplayClient(cassette)
    replayed, replay_error = await replay.get_text("https://rec.example/a")
    assert replay_error == ""
    assert replayed == text


@pytest.mark.asyncio
async def test_xcity_replay_uses_html_fallback_cassette():
    """磁盘录像 ABF-050 回放整条 xcity 链路（API 404 → HTML 回退）。"""
    cassette = load_cassette(RECORDINGS / "xcity" / "abf-050.json")
    crawler = XcityCrawler(client=ReplayClient(cassette))
    response = await crawler.run(_input("ABF-050"))
    assert response.data is not None
    assert response.data.number == "ABF-050"
    assert "美ノ嶋めぐり" in response.data.title
    assert "美ノ嶋めぐり" in response.data.actors
    assert response.data.release == "2023-12-08"
    assert response.data.runtime == "214"
    assert response.data.studio == "プレステージ"


@pytest.mark.asyncio
async def test_avmoo_replay_json_api_cassette(monkeypatch: pytest.MonkeyPatch):
    """磁盘录像 SSNI-804 回放 avmoo JSON API：search + getMovie 两段 POST。"""

    async def _fixed_domain(self, ctx):
        return "https://avmoo.shop"

    monkeypatch.setattr(AvmooCrawler, "_resolve_domain", _fixed_domain)
    cassette = load_cassette(RECORDINGS / "avmoo" / "ssni-804.json")
    crawler = AvmooCrawler(client=ReplayClient(cassette), base_url="https://avmoo.shop")
    response = await crawler.run(_input("SSNI-804"))
    assert response.data is not None
    assert response.data.source == "avmoo"
    assert response.data.number == "SSNI-804"
    assert response.data.title == "巨乳上司と童貞部下"
    assert response.data.release == "2020-06-14"
    assert response.data.actors == ["Aika Yumeno"]
    assert response.data.mosaic == "有码"


@pytest.mark.asyncio
async def test_javdb_api_replay_survives_mirror_rotation(monkeypatch: pytest.MonkeyPatch):
    """javdb_api 镜像轮询：录像存镜像 A 的 URL，运行时从另一镜像发起也须命中。

    `_try_mirrors` 逐镜像拼 `{mirror}{path}` 轮换重试，回放靠忽略 host 的
    归一匹配命中同一条录像——不依赖运行时选中哪个镜像。
    """
    html_dir = DATA_DIR / "javdb_api"
    cassette = _javdb_ipx535_cassette(html_dir)
    crawler = JavdbApiCrawler(client=ReplayClient(cassette), base_url="https://mirror-host-b.example")

    async def _no_throttle(self, ctx, request_type: str, url: str) -> None:
        return None

    monkeypatch.setattr(crawler, "_throttle_page_request", _no_throttle.__get__(crawler))
    response = await crawler.run(_input("IPX-535"))
    assert response.data is not None
    assert response.data.source == "javdb_api"
    assert response.data.number == "IPX-535"
    assert response.data.title == "3・2・1 GO！ いきなり追撃ピストンSEX"
    assert response.data.release == "2024-01-15"
    assert response.data.runtime == "120"
    assert response.data.actors == ["桜空もも"]


def _javdb_ipx535_cassette(html_dir: Path) -> Cassette:
    """构造自现有离线夹具：搜索页真实抓取样本 + 详情页样本（路径与 host 无关）。"""
    return Cassette(
        site="javdb_api",
        number="IPX-535",
        recorded_at="2026-09-23T00:00:00+00:00",
        interactions=[
            Interaction(
                method="GET",
                # 刻意用与 base_url 不同的镜像 host：锁"换 host 仍命中"
                url="https://javdb-mirror-a.example/search?f=all&q=IPX-535&page=1",
                body=(html_dir / "search_list.html").read_text(encoding="utf-8"),
            ),
            Interaction(
                method="GET",
                url="https://javdb-mirror-a.example/v/abc123",
                body=(html_dir / "detail_full.html").read_text(encoding="utf-8"),
            ),
        ],
    )


def _input(number: str) -> CrawlerInput:
    data = CrawlerInput.empty()
    data.number = number
    return data


def _run(coro):
    import asyncio

    return asyncio.run(coro)
