"""Unit tests for JapanHDV official crawler."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from parsel import Selector

from mdcx.config.enums import Website
from mdcx.crawlers.base import Context, get_crawler
from mdcx.crawlers.japanhdv import (
    JapanhdvCrawler,
    _extract_actress_and_date,
    _normalize_image_url,
    _parse_runtime_minutes,
)
from mdcx.models.model_types import CrawlerInput

MOCK_DETAIL_HTML = """
<!DOCTYPE html>
<html>
<head><title>Yui Watanabe is interviewed by a black man today in her kimono</title></head>
<body>
<h1>Yui Watanabe is interviewed by a black man today in her kimono</h1>
<video poster="//static.japanhdv.com/cache/940x528/50/content/videos/Fuck_With_Black_Men_Yui_Watanabe/scene1/12.jpg">
  <source src="//trailers.japanhdv.com/sample/trailer.mp4" type="video/mp4">
</video>
<div class="video-info">
  <h2>Movie Info:</h2>
  <hr>
  <p><strong>Title: </strong> Yui Watanabe is interviewed by a black man today in her kimono</p>
  <p><strong>Actress: </strong> <a href="https://japanhdv.com/model/yui-watanabe/" rel="tag">Yui Watanabe</a></p>
  <p><strong>Duration:</strong> 58Min 54sec</p>
  <p><strong>Resolution:</strong> 1920x1080</p>
  <p><strong>Categories: </strong> <a href="#">Blowjob</a>, <a href="#">Kimono</a>, <a href="#">Creampie</a></p>
  <p><strong>Series: </strong> <a href="#">Fuck With Black Men</a></p>
</div>
<div class="entry-content">
  <img src="//static.japanhdv.com/cache/220x330/50/content/videos/Fuck_With_Black_Men_Yui_Watanabe/scene1/sample/sample_001.jpg">
  <img src="//static.japanhdv.com/cache/220x330/50/content/videos/Fuck_With_Black_Men_Yui_Watanabe/scene1/sample/sample_002.jpg">
</div>
</body>
</html>
"""

MOCK_MODEL_HTML = """
<!DOCTYPE html>
<html>
<head><title>Yui Watanabe 渡辺結衣 profile</title></head>
<body>
<h1>Yui Watanabe 渡辺結衣</h1>
</body>
</html>
"""


def test_japanhdv_registered():
    crawler_cls = get_crawler(Website.JAPANHDV)
    assert crawler_cls is JapanhdvCrawler
    assert JapanhdvCrawler.site() == Website.JAPANHDV
    assert JapanhdvCrawler.base_url_() == "https://japanhdv.com"


def test_extract_actress_and_date():
    ci = CrawlerInput.empty()
    ci.file_path = Path("I:/Incoming/Vdo/scan/input/JapanHDV/JapanHDV.22.07.17.Yui.Watanabe.mp4")
    ctx = Context(input=ci)
    actress, slug, date_str = _extract_actress_and_date(ctx)
    assert actress == "Yui Watanabe"
    assert slug == "yui-watanabe"
    assert date_str == "2022-07-17"


def test_normalize_image_url():
    raw_poster = "//static.japanhdv.com/cache/940x528/50/content/videos/test/12.jpg"
    high_res = _normalize_image_url(raw_poster, high_res=True)
    assert high_res == "https://static.japanhdv.com/cache/1920x1080/50/content/videos/test/12.jpg"

    raw_sample = "//static.japanhdv.com/cache/220x330/50/content/videos/test/sample_001.jpg"
    norm_sample = _normalize_image_url(raw_sample, high_res=False)
    assert norm_sample == "https://static.japanhdv.com/cache/940x528/50/content/videos/test/sample_001.jpg"


def test_parse_runtime_minutes():
    assert _parse_runtime_minutes("58Min 54sec") == "58"
    assert _parse_runtime_minutes("07Min 33sec") == "07"
    assert _parse_runtime_minutes("29:44") == "29"


@pytest.mark.asyncio
async def test_parse_detail_page():
    mock_client = MagicMock()
    mock_client.get_text = AsyncMock(return_value=(MOCK_MODEL_HTML, None))

    crawler = JapanhdvCrawler(mock_client)
    ci = CrawlerInput.empty()
    ci.number = "JapanHDV.22.07.17"
    ci.file_path = Path("JapanHDV.22.07.17.Yui.Watanabe.mp4")
    ctx = Context(input=ci)

    sel = Selector(MOCK_DETAIL_HTML)
    data = await crawler._parse_detail_page(ctx, sel, "https://japanhdv.com/test-video/")

    assert data is not None
    assert data.title == "Yui Watanabe is interviewed by a black man today in her kimono"
    assert data.actors == ["渡辺結衣"]
    assert "Yui Watanabe" in data.all_actors
    assert data.runtime == "58"
    assert data.series == "Fuck With Black Men"
    assert "Blowjob" in data.tags
    assert "Kimono" in data.tags
    assert (
        data.thumb
        == "https://static.japanhdv.com/cache/1920x1080/50/content/videos/Fuck_With_Black_Men_Yui_Watanabe/scene1/12.jpg"
    )
    assert len(data.extrafanart) == 2
    assert (
        data.extrafanart[0]
        == "https://static.japanhdv.com/cache/940x528/50/content/videos/Fuck_With_Black_Men_Yui_Watanabe/scene1/sample/sample_001.jpg"
    )
    assert data.mosaic == "无码"


def test_brand_check_rejects_javhub():
    from mdcx.crawlers.japanhdv import _is_japanhdv_target

    # JavHub should be rejected
    ci = CrawlerInput.empty()
    ci.file_path = Path("JAVHub.22.07.17.Yura.Hitomi.Naughty.Maid.Fucks.Her.Boss.mp4")
    assert not _is_japanhdv_target(Context(input=ci))

    ci2 = CrawlerInput.empty()
    ci2.number = "Javhub.22.06.30"
    assert not _is_japanhdv_target(Context(input=ci2))

    # FC2, Caribbean, 1pondo should be rejected
    ci_fc2 = CrawlerInput.empty()
    ci_fc2.number = "FC2-PPV-123456"
    assert not _is_japanhdv_target(Context(input=ci_fc2))

    # JapanHDV should be accepted
    ci_jhdv = CrawlerInput.empty()
    ci_jhdv.file_path = Path("Japanhdv.22.08.26-cd26.mp4")
    assert _is_japanhdv_target(Context(input=ci_jhdv))
