"""Unit tests for the StashDB (stashdb.org) Western scene scraper."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from mdcx.config.manager import manager
from mdcx.config.models import Website
from mdcx.crawlers.base import Context, get_crawler
from mdcx.crawlers.stashdb import (
    StashDBCrawler,
    clean_western_title,
    extract_significant_keywords,
    score_stashdb_scene,
)
from mdcx.models.types import CrawlerInput, CrawlerResult
from mdcx.utils.phash import clear_cached_scenes, set_cached_scene


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.post_json = AsyncMock()
    return client


@pytest.fixture
def sample_stashdb_scene() -> dict:
    return {
        "id": "3622e809-c43c-4446-a186-ad757f3faea2",
        "title": "We're Betting It's Half Black",
        "code": None,
        "details": "Kasey Cole is pregnant and looking for answers.",
        "director": "John Doe",
        "date": "2022-12-20",
        "duration": 2160,  # 36 minutes
        "urls": [{"url": "https://stashdb.org/scenes/3622e809-c43c-4446-a186-ad757f3faea2"}],
        "images": [{"url": "https://stashdb.org/image/scene_3622.jpg"}],
        "studio": {"name": "Private Society"},
        "tags": [{"name": "Creampie"}, {"name": "Interracial"}],
        "performers": [
            {
                "as": "",
                "performer": {
                    "name": "Kasey Cole",
                    "gender": "FEMALE",
                    "images": [{"url": "https://stashdb.org/image/kasey.jpg"}],
                },
            },
            {
                "as": "",
                "performer": {
                    "name": "Rion King",
                    "gender": "MALE",
                    "images": [],
                },
            },
        ],
    }


def test_site_and_registration():
    import mdcx.crawlers  # noqa: F401

    assert StashDBCrawler.site() == Website.STASHDB
    assert StashDBCrawler.base_url_() == "https://stashdb.org"
    assert get_crawler(Website.STASHDB) is StashDBCrawler


def test_clean_western_title():
    raw = "Kasey - Were Betting Its Half Black 20-12-2022.1080p.mp4"
    cleaned = clean_western_title(raw)
    assert "1080p" not in cleaned
    assert "20-12-2022" not in cleaned
    assert "mp4" not in cleaned
    assert "Kasey Were Betting Its Half Black" in cleaned


def test_extract_significant_keywords():
    raw = "Kasey Were Betting Its Half Black"
    sig = extract_significant_keywords(raw)
    assert "Kasey" in sig
    assert "Betting" in sig
    assert "Half" in sig
    assert "Black" in sig
    assert "were" not in sig
    assert "its" not in sig


def test_score_stashdb_scene(sample_stashdb_scene):
    score = score_stashdb_scene(
        sample_stashdb_scene,
        query_text="Were Betting Its Half Black",
        file_path=r"I:\Incoming\Vdo\scan\input\孕\PrivateSociety-Kasey\Kasey - Were Betting Its Half Black 20-12-2022.mp4",
    )
    # Title match, studio match (PrivateSociety), performer match (Kasey), date match (2022)
    assert score >= 200


@pytest.mark.asyncio
async def test_run_with_cached_scene(mock_client, sample_stashdb_scene):
    """When scene is cached in _PHASH_SCENE_CACHE, scraper reuses it with 0 network calls."""
    clear_cached_scenes()
    file_path = Path("D:/test/Kasey.mp4")
    set_cached_scene(file_path, sample_stashdb_scene)

    crawler = StashDBCrawler(client=mock_client)
    ctx = Context(input=CrawlerInput.empty())
    ctx.input.file_path = file_path

    res = await crawler._run(ctx)
    assert isinstance(res, CrawlerResult)
    assert res.title == "We're Betting It's Half Black"
    assert res.studio == "Private Society"
    assert res.release == "2022-12-20"
    assert res.runtime == "36"
    assert "Kasey Cole" in res.actors
    assert "Rion King" not in res.actors
    assert "Rion King" in res.all_actors
    # No network calls made
    mock_client.post_json.assert_not_called()


@pytest.mark.asyncio
async def test_run_with_fingerprint_hit(mock_client, sample_stashdb_scene, monkeypatch):
    """When not in cache, queries fingerprints and maps result."""
    clear_cached_scenes()
    manager.config.stashdb_api_key = "test_stashdb_key"
    crawler = StashDBCrawler(client=mock_client)
    crawler._post_graphql = AsyncMock(return_value={"findScenesBySceneFingerprints": [[sample_stashdb_scene]]})
    monkeypatch.setattr("oshash.oshash", lambda p: "oshash_123")
    monkeypatch.setattr("mdcx.utils.phash.compute_video_phash", lambda p: "phash_123")

    ctx = Context(input=CrawlerInput.empty())
    ctx.input.file_path = Path("video.mp4")

    res = await crawler._run(ctx)
    assert isinstance(res, CrawlerResult)
    assert res.external_id == "3622e809-c43c-4446-a186-ad757f3faea2"
    assert res.number == "We're Betting It's Half Black"
    crawler._post_graphql.assert_called_once()


@pytest.mark.asyncio
async def test_run_with_text_search_fallback(mock_client, sample_stashdb_scene, monkeypatch):
    """When fingerprint returns empty, fallback queries queryScenes by text."""
    clear_cached_scenes()
    manager.config.stashdb_api_key = "test_stashdb_key"
    crawler = StashDBCrawler(client=mock_client)

    async def mock_post(ctx, query, variables, operation=""):
        if "FindScenesByHash" in query:
            return {"findScenesBySceneFingerprints": [[], []]}
        if "QueryScenes" in query:
            return {"queryScenes": {"scenes": [sample_stashdb_scene]}}
        return {}

    crawler._post_graphql = AsyncMock(side_effect=mock_post)
    monkeypatch.setattr("oshash.oshash", lambda p: "oshash_123")
    monkeypatch.setattr("mdcx.utils.phash.compute_video_phash", lambda p: "phash_123")

    ctx = Context(input=CrawlerInput.empty())
    ctx.input.file_path = Path("PrivateSociety-Kasey/Kasey - Were Betting Its Half Black 20-12-2022.mp4")

    res = await crawler._run(ctx)
    assert isinstance(res, CrawlerResult)
    assert res.title == "We're Betting It's Half Black"
    assert res.studio == "Private Society"


def test_score_stashdb_scene_rejects_isolated_title_overlap(sample_stashdb_scene):
    """Isolated word overlap without studio or performer/date must score 0."""
    # Simulates the bug where "interview 316" hit "GangBang Creampie 316 Interview"
    score = score_stashdb_scene(
        sample_stashdb_scene,
        query_text="interview 316",
        file_path=r"I:\Incoming\Vdo\scan\input\heydouga 4037-531\heydouga 4037-531-real interview 316 Towa01.wmv",
    )
    assert score == 0


def test_score_stashdb_scene_exact_code_match():
    """Exact scene code match yields 300 points."""
    scene = {"code": "PT-123", "title": "Some PureTaboo Scene", "studio": {"name": "Pure Taboo"}}
    score = score_stashdb_scene(scene, query_text="PT-123", file_path="D:/PT-123.mp4")
    assert score == 300


@pytest.mark.asyncio
async def test_search_fallback_blocked_when_allow_text_search_is_false(mock_client):
    """When allow_text_search is False (non-Western task), text fallback is blocked."""
    crawler = StashDBCrawler(client=mock_client)
    ctx = Context(input=CrawlerInput.empty())
    ctx.input.allow_text_search = False
    ctx.input.number = "INTERVIEW-316"

    res = await crawler._search_fallback(ctx)
    assert res is None


@pytest.mark.asyncio
async def test_search_fallback_rejects_low_score(mock_client):
    """When candidate score is below 180, fallback discards it."""
    crawler = StashDBCrawler(client=mock_client)
    # Scene with only word overlap, no studio or performer
    low_scene = {
        "title": "GangBang Creampie 316 Interview",
        "studio": {"name": "Some Random Studio"},
        "performers": [],
        "date": "2020-01-01",
        "code": None,
    }

    async def mock_post(ctx, query, variables, operation=""):
        return {"queryScenes": {"scenes": [low_scene]}}

    crawler._post_graphql = AsyncMock(side_effect=mock_post)
    ctx = Context(input=CrawlerInput.empty())
    ctx.input.number = "INTERVIEW-316"
    ctx.input.file_path = Path("interview 316.wmv")

    res = await crawler._search_fallback(ctx)
    assert res is None
