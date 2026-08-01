"""Unit tests for the JavStash (Stash-box) GraphQL scraper.

These tests use mocked HTTP and a saved API response fixture — no network required.
They test parsing logic, field mapping, sentinel handling, and error paths.

The fixture file was captured from javstash.org and can be refreshed with:
    python scratch/capture_fixture.py
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from mdcx.config.manager import manager
from mdcx.config.models import Website
from mdcx.core.file_crawler import _deal_res
from mdcx.crawlers.base import Context, CralwerException
from mdcx.crawlers.base.types import NOT_SUPPORT, CrawlerData, NotSupport
from mdcx.crawlers.javstash import StashGraphQLCrawler
from mdcx.models.types import CrawlerInput, CrawlersResult
from mdcx.utils.dataclass import update

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.post_json = AsyncMock()
    return client


@pytest.fixture
def stars358_scene() -> dict:
    """Real STARS-358 scene data from the javstash.org API."""
    data = _load_fixture("javstash_stars358.json")
    return data["findScene"]


# ---------------------------------------------------------------------------
# API key and error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_api_key_raises(mock_client):
    manager.config.javstash_api_key = ""
    crawler = StashGraphQLCrawler(client=mock_client)
    ctx = Context(input=CrawlerInput.empty())

    with pytest.raises(CralwerException, match="请在设置中配置 StashAPI 令牌"):
        await crawler._post_graphql(ctx, "query { }", {})


@pytest.mark.asyncio
async def test_graphql_error_response_raises(mock_client):
    manager.config.javstash_api_key = "test_key"
    crawler = StashGraphQLCrawler(client=mock_client)
    mock_client.post_json.return_value = (
        {"errors": [{"message": "field not found"}]},
        None,
    )
    ctx = Context(input=CrawlerInput.empty())

    with pytest.raises(CralwerException, match="field not found"):
        await crawler._post_graphql(ctx, "query { }", {})


@pytest.mark.asyncio
async def test_graphql_http_error_raises(mock_client):
    manager.config.javstash_api_key = "test_key"
    crawler = StashGraphQLCrawler(client=mock_client)
    mock_client.post_json.return_value = (None, "HTTP 422")
    ctx = Context(input=CrawlerInput.empty())

    with pytest.raises(CralwerException, match="GraphQL 请求失败"):
        await crawler._post_graphql(ctx, "query { }", {})


# ---------------------------------------------------------------------------
# _run pipeline paths (testing URL, Hash, Number fallbacks)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_with_url_id(mock_client, stars358_scene):
    manager.config.javstash_api_key = "test_key"
    crawler = StashGraphQLCrawler(client=mock_client)
    crawler._post_graphql = AsyncMock(return_value={"findScene": stars358_scene})
    
    ctx = Context(input=CrawlerInput.empty())
    ctx.input.appoint_url = "https://javstash.org/scenes/07adfc8a-97ac-4583-9ebf-73b0ff7cc478"
    
    data = await crawler._run(ctx)
    assert data.external_id == "07adfc8a-97ac-4583-9ebf-73b0ff7cc478"
    crawler._post_graphql.assert_called_once()
    args = crawler._post_graphql.call_args[0]
    assert args[2] == {"id": "07adfc8a-97ac-4583-9ebf-73b0ff7cc478"}

@pytest.mark.asyncio
async def test_run_with_number(mock_client, stars358_scene):
    manager.config.javstash_api_key = "test_key"
    crawler = StashGraphQLCrawler(client=mock_client)
    crawler._post_graphql = AsyncMock(return_value={"findScenes": {"scenes": [stars358_scene]}})
    
    ctx = Context(input=CrawlerInput.empty())
    ctx.input.number = "STARS-358"
    
    data = await crawler._run(ctx)
    assert data.external_id == "07adfc8a-97ac-4583-9ebf-73b0ff7cc478"

@pytest.mark.asyncio
async def test_run_not_found(mock_client):
    manager.config.javstash_api_key = "test_key"
    crawler = StashGraphQLCrawler(client=mock_client)
    crawler._post_graphql = AsyncMock(return_value={"findScenes": {"scenes": []}})
    
    ctx = Context(input=CrawlerInput.empty())
    ctx.input.number = "NOT-FOUND"
    
    with pytest.raises(CralwerException, match="未找到匹配场景"):
        await crawler._run(ctx)

@pytest.mark.asyncio
async def test_run_with_valid_post_graphql(mock_client, stars358_scene):
    manager.config.javstash_api_key = "test_key"
    crawler = StashGraphQLCrawler(client=mock_client)
    # Testing _post_graphql directly to cover line 56
    mock_client.post_json.return_value = ({"data": {"findScene": stars358_scene}}, None)
    ctx = Context(input=CrawlerInput.empty())
    data = await crawler._post_graphql(ctx, "query", {})
    assert "findScene" in data


# ---------------------------------------------------------------------------
# _map_scene — field extraction from real fixture
# ---------------------------------------------------------------------------


def test_map_scene_core_fields(mock_client, stars358_scene):
    manager.config.javstash_api_key = "test_key"
    crawler = StashGraphQLCrawler(client=mock_client)
    ctx = Context(input=CrawlerInput.empty())
    ctx.input.number = "STARS-358"

    data = crawler._map_scene(stars358_scene, ctx)

    assert data.number == "STARS-358"
    assert data.external_id == "07adfc8a-97ac-4583-9ebf-73b0ff7cc478"
    assert data.source == "javstash"
    assert data.release == "2021-04-08"
    assert data.year == "2021"
    assert data.studio == "SODSTAR"
    assert data.publisher == "SODSTAR"
    assert data.title.startswith("「先輩、うち来て資料作れば？」")


def test_map_scene_performers(mock_client, stars358_scene):
    manager.config.javstash_api_key = "test_key"
    crawler = StashGraphQLCrawler(client=mock_client)
    ctx = Context(input=CrawlerInput.empty())

    data = crawler._map_scene(stars358_scene, ctx)

    assert "戸田真琴" in data.actors
    assert "戸田真琴" in data.all_actors


def test_map_scene_director(mock_client, stars358_scene):
    manager.config.javstash_api_key = "test_key"
    crawler = StashGraphQLCrawler(client=mock_client)
    ctx = Context(input=CrawlerInput.empty())

    data = crawler._map_scene(stars358_scene, ctx)

    assert data.directors == ["前田文豪"]


def test_map_scene_tags(mock_client, stars358_scene):
    manager.config.javstash_api_key = "test_key"
    crawler = StashGraphQLCrawler(client=mock_client)
    ctx = Context(input=CrawlerInput.empty())

    data = crawler._map_scene(stars358_scene, ctx)

    assert isinstance(data.tags, list)
    assert len(data.tags) >= 5
    assert "単体作品" in data.tags


def test_map_scene_runtime(mock_client, stars358_scene):
    manager.config.javstash_api_key = "test_key"
    crawler = StashGraphQLCrawler(client=mock_client)
    ctx = Context(input=CrawlerInput.empty())

    data = crawler._map_scene(stars358_scene, ctx)

    # 7737 seconds → 128 minutes
    assert data.runtime == "128"


def test_map_scene_image(mock_client, stars358_scene):
    manager.config.javstash_api_key = "test_key"
    crawler = StashGraphQLCrawler(client=mock_client)
    ctx = Context(input=CrawlerInput.empty())

    data = crawler._map_scene(stars358_scene, ctx)

    assert data.thumb.startswith("https://javstash.org/images/")
    assert data.poster == data.thumb


# ---------------------------------------------------------------------------
# Sentinel leakage — no NotSupport in any field
# ---------------------------------------------------------------------------


def test_map_scene_no_sentinel_leakage(mock_client, stars358_scene):
    """Every field in CrawlerData must be a real value, never NotSupport."""
    manager.config.javstash_api_key = "test_key"
    crawler = StashGraphQLCrawler(client=mock_client)
    ctx = Context(input=CrawlerInput.empty())

    data = crawler._map_scene(stars358_scene, ctx)

    for attr_name in vars(data):
        val = getattr(data, attr_name)
        assert not isinstance(val, NotSupport), f"CrawlerData.{attr_name} is NotSupport"
        assert val is not NOT_SUPPORT, f"CrawlerData.{attr_name} is NOT_SUPPORT singleton"


def test_map_scene_string_fields_are_strings(mock_client, stars358_scene):
    """Fields consumed by _deal_res must be actual strings."""
    manager.config.javstash_api_key = "test_key"
    crawler = StashGraphQLCrawler(client=mock_client)
    ctx = Context(input=CrawlerInput.empty())

    data = crawler._map_scene(stars358_scene, ctx)

    for field in ("score", "mosaic", "series", "wanted", "trailer"):
        val = getattr(data, field)
        assert isinstance(val, str), f"{field} is {type(val).__name__}, expected str"


# ---------------------------------------------------------------------------
# Full pipeline: CrawlerData → CrawlerResult → CrawlersResult → _deal_res
# ---------------------------------------------------------------------------


def test_full_pipeline_no_crash(mock_client, stars358_scene):
    """End-to-end pipeline must not crash on JavStash data."""
    manager.config.javstash_api_key = "test_key"
    crawler = StashGraphQLCrawler(client=mock_client)
    ctx = Context(input=CrawlerInput.empty())
    ctx.input.number = "STARS-358"

    crawler_data = crawler._map_scene(stars358_scene, ctx)
    result_v2 = crawler_data.to_result()
    final = update(CrawlersResult.empty(), result_v2)
    final = _deal_res(final)

    # Core fields survive the pipeline
    assert final.title.startswith("「先輩")
    assert final.studio == "SODSTAR"
    assert final.release == "2021-04-08"
    assert final.score == "0.0"
    assert final.director == "前田文豪"
    assert "戸田真琴" in final.actor


def test_full_pipeline_no_html_entities(mock_client, stars358_scene):
    """_deal_res must have unescaped any HTML entities."""
    manager.config.javstash_api_key = "test_key"
    crawler = StashGraphQLCrawler(client=mock_client)
    ctx = Context(input=CrawlerInput.empty())

    crawler_data = crawler._map_scene(stars358_scene, ctx)
    result_v2 = crawler_data.to_result()
    final = update(CrawlersResult.empty(), result_v2)
    final = _deal_res(final)

    for field in ("title", "originaltitle", "outline", "originalplot", "studio", "publisher"):
        val = getattr(final, field)
        assert "&amp;" not in val, f"{field} contains &amp;"
        assert "<br/>" not in val, f"{field} contains <br/>"


# ---------------------------------------------------------------------------
# _map_scene edge cases — missing/empty data
# ---------------------------------------------------------------------------


def test_map_scene_no_director(mock_client):
    """Scene without a director → directors should be an empty list."""
    manager.config.javstash_api_key = "test_key"
    crawler = StashGraphQLCrawler(client=mock_client)
    ctx = Context(input=CrawlerInput.empty())
    ctx.input.number = "TEST-001"

    scene = {"id": "aaa", "title": "No Director", "code": "TEST-001",
             "date": "2024-01-01", "performers": [], "studio": None,
             "tags": [], "images": []}

    data = crawler._map_scene(scene, ctx)
    assert data.directors == []


def test_map_scene_no_images(mock_client):
    """Scene without images → thumb should be empty string."""
    manager.config.javstash_api_key = "test_key"
    crawler = StashGraphQLCrawler(client=mock_client)
    ctx = Context(input=CrawlerInput.empty())
    ctx.input.number = "TEST-002"

    scene = {"id": "bbb", "title": "No Image", "code": "TEST-002",
             "date": "", "performers": [], "studio": None,
             "tags": [], "images": []}

    data = crawler._map_scene(scene, ctx)
    assert data.thumb == ""
    assert data.poster == ""
    assert data.release == ""
    assert data.year == ""


def test_map_scene_male_performer_excluded_from_actors(mock_client):
    """Male performers go into all_actors but not actors."""
    manager.config.javstash_api_key = "test_key"
    crawler = StashGraphQLCrawler(client=mock_client)
    ctx = Context(input=CrawlerInput.empty())
    ctx.input.number = "TEST-003"

    scene = {
        "id": "ccc", "title": "Mixed", "code": "TEST-003",
        "date": "2024-06-01", "studio": {"name": "TestStudio"},
        "tags": [], "images": [],
        "performers": [
            {"performer": {"name": "Actress", "gender": "FEMALE", "images": []}},
            {"performer": {"name": "Actor", "gender": "MALE", "images": []}},
        ],
    }

    data = crawler._map_scene(scene, ctx)
    assert data.actors == ["Actress"]
    assert data.all_actors == ["Actress", "Actor"]


def test_map_scene_invalid_duration(mock_client, stars358_scene):
    """Test duration that cannot be parsed to integer."""
    manager.config.javstash_api_key = "test_key"
    crawler = StashGraphQLCrawler(client=mock_client)
    ctx = Context(input=CrawlerInput.empty())
    stars358_scene["duration"] = "invalid"
    data = crawler._map_scene(stars358_scene, ctx)
    assert data.runtime == ""

def test_map_scene_empty_performer(mock_client, stars358_scene):
    """Test empty performer data."""
    manager.config.javstash_api_key = "test_key"
    crawler = StashGraphQLCrawler(client=mock_client)
    ctx = Context(input=CrawlerInput.empty())
    stars358_scene["performers"] = [{"performer": {}}, {"performer": {"name": ""}}]
    data = crawler._map_scene(stars358_scene, ctx)
    assert data.actors == []
    assert data.all_actors == []

@pytest.mark.asyncio
async def test_not_implemented_methods(mock_client):
    """Test methods that should raise NotImplementedError."""
    crawler = StashGraphQLCrawler(client=mock_client)
    ctx = Context(input=CrawlerInput.empty())
    
    with pytest.raises(NotImplementedError):
        await crawler._generate_search_url(ctx)
        
    with pytest.raises(NotImplementedError):
        await crawler._parse_search_page(ctx, "", "")
        
    with pytest.raises(NotImplementedError):
        await crawler._parse_detail_page(ctx, "", "")

# ---------------------------------------------------------------------------
# _deal_res edge cases (unit-level, no network)
# ---------------------------------------------------------------------------


def test_deal_res_score_non_numeric():
    res = CrawlersResult.empty()
    res.score = "not-a-number"
    result = _deal_res(res)
    assert result.score == "0.0"


def test_deal_res_score_valid():
    res = CrawlersResult.empty()
    res.score = "8.53"
    result = _deal_res(res)
    assert result.score == "8.5"


def test_deal_res_html_entities():
    res = CrawlersResult.empty()
    res.title = "Test &amp; Title"
    res.studio = "Studio &lt;X&gt;"
    res.outline = "Hello<br/>World"
    result = _deal_res(res)
    assert result.title == "Test & Title"
    assert result.studio == "Studio <X>"
    assert result.outline == "HelloWorld"


# ---------------------------------------------------------------------------
# Crawler registration
# ---------------------------------------------------------------------------


def test_site_returns_javstash():
    assert StashGraphQLCrawler.site() == Website.JAVSTASH


def test_base_url_is_javstash():
    assert StashGraphQLCrawler.base_url_() == "https://javstash.org"
