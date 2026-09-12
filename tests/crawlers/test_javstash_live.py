"""Live integration tests for the JavStash (Stash-box) GraphQL scraper.

These tests hit the real javstash.org API. They are SKIPPED by default.

    # Run live tests:
    pytest tests/crawlers/test_javstash_live.py --network -v

    # Refresh the offline fixture (for test_javstash.py):
    pytest tests/crawlers/test_javstash_live.py --network --overwrite -v

API key is resolved from (in priority order):
    1. JAVSTASH_API_KEY environment variable
    2. javstash_api_key in the MDCx user config
"""

import json
import os
from pathlib import Path

import pytest

from mdcx.config.manager import manager
from mdcx.core.file_crawler import _deal_res
from mdcx.crawlers.base import Context
from mdcx.crawlers.base.base_types import NOT_SUPPORT, NotSupport
from mdcx.crawlers.javstash import StashGraphQLCrawler
from mdcx.models.model_types import CrawlerInput, CrawlersResult
from mdcx.utils.dataclass import update
from mdcx.web_async import AsyncWebClient

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://javstash.org"
SCENE_UUID = "07adfc8a-97ac-4583-9ebf-73b0ff7cc478"
SCENE_URL = f"{BASE_URL}/scenes/{SCENE_UUID}"
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "javstash_stars358.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_api_key() -> str:
    """Resolve API key from env var or user config. Never hardcoded."""
    if key := os.environ.get("JAVSTASH_API_KEY"):
        return key
    try:
        manager.load()
        if manager.config.javstash_api_key:
            return manager.config.javstash_api_key
    except Exception:
        pass
    pytest.skip("No API key available. Set JAVSTASH_API_KEY env var or configure javstash_api_key in MDCx settings.")


def _make_crawler() -> StashGraphQLCrawler:
    client = AsyncWebClient(timeout=30)
    crawler = StashGraphQLCrawler(client=client, base_url=BASE_URL)
    crawler.api_key = _get_api_key()
    return crawler


def _make_context() -> Context:
    inp = CrawlerInput.empty()
    inp.appoint_url = SCENE_URL
    inp.number = "STARS-358"
    return Context(input=inp)


def _assert_no_sentinel(obj: object, label: str = "") -> None:
    for attr_name in vars(obj):
        val = getattr(obj, attr_name)
        assert not isinstance(val, NotSupport), f"{label}.{attr_name} is NotSupport"
        assert val is not NOT_SUPPORT, f"{label}.{attr_name} is NOT_SUPPORT"


# ---------------------------------------------------------------------------
# Tests (all gated behind --network)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_crawl_returns_valid_data(network):
    """Hit the real API and verify core metadata."""
    if not network:
        pytest.skip("requires --network")

    crawler = _make_crawler()
    data = await crawler._run(_make_context())

    assert isinstance(data, CrawlersResult)
    assert data.number == "STARS-358"
    assert data.external_id == SCENE_UUID
    assert data.title  # non-empty
    assert data.release == "2021-04-08"
    assert data.studio == "SODSTAR"
    assert len(data.actors) >= 1
    assert len(data.directors) >= 1
    assert data.thumb.startswith("http")
    _assert_no_sentinel(data, "CrawlerResult")


@pytest.mark.asyncio
async def test_live_full_pipeline(network):
    """Hit the real API and push through the full _deal_res pipeline."""
    if not network:
        pytest.skip("requires --network")

    crawler = _make_crawler()
    crawler_res = await crawler._run(_make_context())

    final = update(CrawlersResult.empty(), crawler_res)
    final = _deal_res(final)

    _assert_no_sentinel(final, "CrawlersResult")
    assert final.title
    assert final.studio == "SODSTAR"
    assert final.release == "2021-04-08"
    assert final.score == "0.0"
    float(final.score)  # must not raise
    assert final.actor  # v1 compat property
    assert final.director  # v1 compat property


@pytest.mark.asyncio
async def test_refresh_fixture(network, overwrite):
    """Refresh the offline test fixture from the live API.

    Run with: pytest tests/crawlers/test_javstash_live.py --network --overwrite -k refresh
    """
    if not network:
        pytest.skip("requires --network")
    if not overwrite:
        pytest.skip("requires --overwrite to update fixture file")

    crawler = _make_crawler()
    ctx = _make_context()
    ctx.input.appoint_url = ""  # don't use URL path — use ID query directly

    data = await crawler._post_graphql(ctx, crawler.FIND_BY_ID_QUERY, {"id": SCENE_UUID})

    # Sanity check before writing
    scene = data.get("findScene")
    assert scene is not None, "API returned no scene"
    assert scene.get("code") == "STARS-358", f"Unexpected code: {scene.get('code')}"

    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nFixture refreshed: {FIXTURE_PATH} ({FIXTURE_PATH.stat().st_size} bytes)")


@pytest.mark.asyncio
async def test_live_all_queries_schema_validation(network):
    """Verify that all GraphQL queries pass the live Stash-box schema validation (no HTTP 422)."""
    if not network:
        pytest.skip("requires --network")

    import urllib.request

    queries_to_test = [
        ("FIND_BY_ID_QUERY", StashGraphQLCrawler.FIND_BY_ID_QUERY, {"id": SCENE_UUID}),
        (
            "FIND_BY_HASH_QUERY",
            StashGraphQLCrawler.FIND_BY_HASH_QUERY,
            {"fingerprints": [[{"algorithm": "OSHASH", "hash": "0123456789abcdef"}]]},
        ),
        (
            "FIND_BY_NUMBER_QUERY",
            StashGraphQLCrawler.FIND_BY_NUMBER_QUERY,
            {"input": {"text": "STARS-358"}},
        ),
    ]

    for name, query, variables in queries_to_test:
        req = urllib.request.Request(
            f"{BASE_URL}/graphql",
            data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
        )
        try:
            with urllib.request.urlopen(req) as resp:
                assert resp.status == 200, f"{name} failed with status {resp.status}"
                body = json.loads(resp.read().decode("utf-8"))
                errors = body.get("errors", [])
                for err in errors:
                    code = err.get("extensions", {}).get("code", "")
                    assert code != "GRAPHQL_VALIDATION_FAILED", f"{name} schema validation failed: {err}"
        except urllib.error.HTTPError as e:
            pytest.fail(f"{name} returned HTTP {e.code}: {e.read().decode('utf-8')}")
