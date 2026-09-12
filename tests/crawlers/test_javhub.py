"""Unit tests for JavHub official crawler."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from parsel import Selector

from mdcx.config.enums import Website
from mdcx.crawlers.base import Context, get_crawler
from mdcx.crawlers.javhub import (
    JavhubCrawler,
    _extract_javhub_info,
    _is_javhub_target,
)
from mdcx.models.model_types import CrawlerInput

MOCK_DETAIL_JSON = {
    "props": {
        "pageProps": {
            "content": {
                "id": 952,
                "title": "Yura Hitomi",
                "slug": "yura-hitomi-1",
                "publish_date": "2020/11/21 12:00:00",
                "seconds_duration": 3436,
                "videos_duration": "57:16",
                "description": "As soon as the guy came over Yura Hitomi went into the other room to undress in her maid outfit...",
                "thumb": "https://c75416c5b2.mjedge.net/5/f/a/5/6/5fa56176252fb/jav0410_yura_hitomi_01.jpg",
                "thumbs": ["https://c75416c5b2.mjedge.net/sample1.jpg", "https://c75416c5b2.mjedge.net/sample2.jpg"],
                "previews": {"full": ["https://c75416c5b2.mjedge.net/preview1.jpg"]},
                "trailer_url": "https://c73f9ed7c5.mjedge.net/trailer.mp4",
                "models": ["Yura Hitomi"],
                "tags": ["Trimmed Pussy", "Shower", "Maid Outfit", "Creampie"],
            }
        }
    }
}

MOCK_DETAIL_HTML = f"""
<!DOCTYPE html>
<html>
<head><title>Yura Hitomi - JavHub</title></head>
<body>
<script id="__NEXT_DATA__" type="application/json">
{json.dumps(MOCK_DETAIL_JSON)}
</script>
</body>
</html>
"""

MOCK_SEARCH_JSON = {
    "props": {
        "pageProps": {
            "contents": {
                "total": 2,
                "data": [
                    {
                        "id": 1218,
                        "title": "Hitomi Yura",
                        "slug": "hitomi-yura",
                        "publish_date": "2022/09/23 12:00:00",
                        "seconds_duration": 3437,
                        "description": "Sensual day with blue bra...",
                        "models": ["Yura Hitomi"],
                        "tags": ["Toys"],
                    },
                    {
                        "id": 952,
                        "title": "Yura Hitomi",
                        "slug": "yura-hitomi-1",
                        "publish_date": "2020/11/21 12:00:00",
                        "seconds_duration": 3436,
                        "description": "Naughty maid in shower...",
                        "models": ["Yura Hitomi"],
                        "tags": ["Maid Outfit"],
                    },
                ],
            }
        }
    }
}

MOCK_SEARCH_HTML = f"""
<!DOCTYPE html>
<html>
<head><title>Search - JavHub</title></head>
<body>
<script id="__NEXT_DATA__" type="application/json">
{json.dumps(MOCK_SEARCH_JSON)}
</script>
</body>
</html>
"""


def test_javhub_registered():
    crawler_cls = get_crawler(Website.JAVHUB)
    assert crawler_cls is JavhubCrawler
    assert JavhubCrawler.site() == Website.JAVHUB
    assert JavhubCrawler.base_url_() == "https://tour.javhub.com"


def test_is_javhub_target():
    # JavHub should be accepted
    ci1 = CrawlerInput.empty()
    ci1.file_path = Path("JAVHub.22.07.17.Yura.Hitomi.Naughty.Maid.Fucks.Her.Boss.mp4")
    assert _is_javhub_target(Context(input=ci1))

    ci2 = CrawlerInput.empty()
    ci2.number = "Javhub.22.06.30"
    assert _is_javhub_target(Context(input=ci2))

    # Other brands should be rejected
    ci3 = CrawlerInput.empty()
    ci3.file_path = Path("Japanhdv.22.08.26-cd26.mp4")
    assert not _is_javhub_target(Context(input=ci3))

    ci4 = CrawlerInput.empty()
    ci4.number = "FC2-PPV-123456"
    assert not _is_javhub_target(Context(input=ci4))


def test_extract_javhub_info():
    ci = CrawlerInput.empty()
    ci.file_path = Path("JAVHub.22.07.17.Yura.Hitomi.Naughty.Maid.Fucks.Her.Boss.mp4")
    ctx = Context(input=ci)

    performer, keywords, date_str, dur = _extract_javhub_info(ctx)
    assert performer == "Yura Hitomi"
    assert "naughty" in keywords
    assert "maid" in keywords
    assert date_str == "2022-07-17"


@pytest.mark.asyncio
async def test_parse_search_page_scoring():
    mock_client = MagicMock()
    crawler = JavhubCrawler(mock_client)

    ci = CrawlerInput.empty()
    ci.file_path = Path("JAVHub.22.07.17.Yura.Hitomi.Naughty.Maid.Fucks.Her.Boss.mp4")
    ctx = Context(input=ci)

    sel = Selector(MOCK_SEARCH_HTML)
    urls = await crawler._parse_search_page(ctx, sel, "https://tour.javhub.com/search/yura")

    assert urls is not None
    # yura-hitomi-1 should be ranked #1 because of "maid" keyword match in description/tags
    assert "yura-hitomi-1" in urls[0]


@pytest.mark.asyncio
async def test_parse_detail_page():
    mock_client = MagicMock()
    crawler = JavhubCrawler(mock_client)

    ci = CrawlerInput.empty()
    ci.number = "Javhub.22.07.17"
    ctx = Context(input=ci)

    sel = Selector(MOCK_DETAIL_HTML)
    data = await crawler._parse_detail_page(ctx, sel, "https://tour.javhub.com/videos/yura-hitomi-1")

    assert data is not None
    assert data.title == "Yura Hitomi"
    assert data.actors == ["Yura Hitomi"]
    assert data.studio == "JavHub"
    assert data.release == "2020-11-21"
    assert data.year == "2020"
    assert data.runtime == "57"
    assert "Maid Outfit" in data.tags
    assert data.thumb == "https://c75416c5b2.mjedge.net/5/f/a/5/6/5fa56176252fb/jav0410_yura_hitomi_01.jpg"
    assert data.poster == data.thumb
    assert len(data.extrafanart) == 3
    assert data.mosaic == "无码"
    assert data.trailer == "https://c73f9ed7c5.mjedge.net/trailer.mp4"
