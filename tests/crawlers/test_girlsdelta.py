"""Unit tests for GirlsDelta (girlsdelta.com) official site scraper."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from parsel import Selector

from mdcx.config.enums import DownloadableFile, FixedScrapingType, Website
from mdcx.core.web import _get_poster_copy_policy
from mdcx.crawlers.base import Context, get_crawler
from mdcx.crawlers.girlsdelta import (
    GirlsDeltaCrawler,
    extract_girlsdelta_id,
    extract_girlsdelta_title_query,
    is_girlsdelta_number,
)
from mdcx.crawlers.official import OfficialCrawler
from mdcx.models.model_types import CrawlerInput, CrawlersResult
from mdcx.number import extract_brand_number, is_uncensored

MOCK_GIRLSDELTA_PRODUCT_HTML = """
<!doctype html>
<html lang="ja">
<head>
  <title>NATSUNA | Girls Delta</title>
  <meta name="description" content="梶原夏奈 NATSUNA official work" />
  <link rel="canonical" href="https://girlsdelta.com/product/1703" />
</head>
<body>
  <div class="prod-navi">
    <div class="row product-row clearfix">
      <div class="large-5 prod-name">NATSUNA</div>
      <div id="head-breadcrumb" class="large-6 breadcrumbs">
        <div class="breadcrumb"><a href="https://girlsdelta.com/model/721/"><span>梶原夏奈</span></a></div>
        <div class="breadcrumb"><span>NATSUNA</span></div>
      </div>
    </div>
  </div>
  <div id="product-main-image">
    <video
      poster="https://girlsdelta.com/pics/product/3b16ecbdf75722f23668dfcdfe630d58/product_top.webp"
      src="https://girlsdelta.com/pics/product/3b16ecbdf75722f23668dfcdfe630d58/movie.mp4"
      id="sample-video"
    ></video>
  </div>
  <div id="product-detail">
    <div class="product-wrapper">
      <h3>作品詳細</h3>
      <div class="product-detail">
        <ul>
          <li><h4>スタジオ</h4><p>GirlsDelta</p></li>
          <li><h4>シリーズ</h4><p>GirlsDelta</p></li>
          <li><h4>作品内容</h4><p>Photo:8, Movie:8</p></li>
          <li>
            <h4>作品カテゴリ</h4>
            <p>
              <a href="https://girlsdelta.com/product-list/3/">ミニスカート</a>
              <a href="https://girlsdelta.com/product-list/26/">4K 動画</a>
            </p>
          </li>
        </ul>
      </div>
      <h3>モデル詳細</h3>
      <div class="product-detail">
        <ul>
          <li><h4>モデル名</h4><p><a href="https://girlsdelta.com/model/721/">梶原夏奈</a></p></li>
          <li><h4>サイズ</h4><p>T153/B100/W65/H86</p></li>
          <li>
            <h4>モデルカテゴリ</h4>
            <p>
              <a href="https://girlsdelta.com/model-list/1/">ナチュラル</a>
              <a href="https://girlsdelta.com/model-list/15/">黒髪</a>
            </p>
          </li>
        </ul>
      </div>
    </div>
  </div>
  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "VideoObject",
    "name": "NATSUNA",
    "description": "梶原夏奈 NATSUNA 4K video release",
    "thumbnailUrl": "https://girlsdelta.com/pics/product/3b16ecbdf75722f23668dfcdfe630d58/product_top.webp",
    "uploadDate": "2022-04-30",
    "url": "https://girlsdelta.com/product/1703",
    "contentUrl": "https://girlsdelta.com/pics/product/3b16ecbdf75722f23668dfcdfe630d58/movie.mp4"
  }
  </script>
</body>
</html>
"""

MOCK_GIRLSDELTA_MODEL_LIST_HTML = """
<div class="searchItem" data-name="梶原夏奈 Natsuna Kajiwara かじわらなつな">
  <div class="search-result clearfix">
    <div class="search-thumbnail"><a href="https://girlsdelta.com/model/721"></a></div>
  </div>
</div>
"""

MOCK_GIRLSDELTA_MODEL_721_HTML = """
<div class="card">
  <div class="search-result clearfix">
    <div class="search-content">
      <h3 class="search-title"><a href="https://girlsdelta.com/product/1704">NATSUNA 2</a></h3>
    </div>
  </div>
  <div class="search-result clearfix">
    <div class="search-content">
      <h3 class="search-title"><a href="https://girlsdelta.com/product/1703">NATSUNA</a></h3>
    </div>
  </div>
</div>
"""


def test_girlsdelta_registration():
    crawler_cls = get_crawler(Website.GIRLSDELTA)
    assert crawler_cls is GirlsDeltaCrawler
    assert GirlsDeltaCrawler.site() == Website.GIRLSDELTA
    assert GirlsDeltaCrawler.base_url_() == "https://girlsdelta.com"


def test_extract_girlsdelta_id():
    assert extract_girlsdelta_id("GIRLSDELTA-1703") == "1703"
    assert extract_girlsdelta_id("GirlsDelta 1703") == "1703"
    assert extract_girlsdelta_id("Girls Delta.com 1703.mp4") == "1703"
    assert extract_girlsdelta_id("GD-1703") == "1703"
    assert extract_girlsdelta_id("GDL-1703") == "1703"
    assert extract_girlsdelta_id("https://girlsdelta.com/product/1703") == "1703"
    assert extract_girlsdelta_id("https://girlsdelta.com/jp/product/1703") == "1703"
    assert extract_girlsdelta_id("GIRLSDELTA-NATSUNA") is None
    assert extract_girlsdelta_id("SSIS-001") is None


def test_extract_girlsdelta_title_query():
    assert extract_girlsdelta_title_query("GIRLSDELTA-NATSUNA") == "NATSUNA"
    assert extract_girlsdelta_title_query("GirlsDelta - NATSUNA 2.mp4") == "NATSUNA 2"
    assert extract_girlsdelta_title_query("Girls Delta.com NATSUNA.mp4") == "NATSUNA"
    assert extract_girlsdelta_title_query("GIRLSDELTA-1703") is None
    assert extract_girlsdelta_title_query("SSIS-001") is None


def test_is_girlsdelta_number_and_get_number():
    assert is_girlsdelta_number("GIRLSDELTA-1703") is True
    assert is_girlsdelta_number("GIRLSDELTA-NATSUNA") is True
    assert is_girlsdelta_number("SSIS-001") is False

    assert extract_brand_number("GirlsDelta-1703.mp4") == "GIRLSDELTA-1703"
    assert extract_brand_number("Girls Delta.com 1703.mp4") == "GIRLSDELTA-1703"
    assert extract_brand_number("GirlsDelta-NATSUNA.mp4") == "GIRLSDELTA-NATSUNA"
    assert is_uncensored("GIRLSDELTA-1703") is True


@pytest.mark.asyncio
async def test_girlsdelta_generate_search_url_by_id_and_title():
    mock_client = MagicMock()
    crawler = GirlsDeltaCrawler(mock_client)

    # 1. Direct ID
    ci = CrawlerInput.empty()
    ci.number = "GIRLSDELTA-1703"
    ctx = Context(input=ci)
    url = await crawler._generate_search_url(ctx)
    assert url == "https://girlsdelta.com/product/1703"

    # 2. Title resolution via /model-list -> /model/721 -> /product/1703
    async def side_effect_get_text(target_url: str):
        if target_url.endswith("/model-list"):
            return (MOCK_GIRLSDELTA_MODEL_LIST_HTML, None)
        if target_url.endswith("/model/721"):
            return (MOCK_GIRLSDELTA_MODEL_721_HTML, None)
        return (None, "404")

    mock_client.get_text = AsyncMock(side_effect=side_effect_get_text)
    ci2 = CrawlerInput.empty()
    ci2.number = "GIRLSDELTA-NATSUNA"
    ctx2 = Context(input=ci2)
    resolved_url = await crawler._generate_search_url(ctx2)
    assert resolved_url == "https://girlsdelta.com/product/1703"


@pytest.mark.asyncio
async def test_girlsdelta_parse_detail_page_uses_sample_webp_as_poster():
    mock_client = MagicMock()
    crawler = GirlsDeltaCrawler(mock_client)

    ci = CrawlerInput.empty()
    ci.number = "GIRLSDELTA-1703"
    ci.file_path = Path("GirlsDelta-1703.mp4")
    ctx = Context(input=ci)

    sel = Selector(text=MOCK_GIRLSDELTA_PRODUCT_HTML)
    data = await crawler._parse_detail_page(ctx, sel, "https://girlsdelta.com/product/1703")

    assert data is not None
    assert data.number == "GIRLSDELTA-1703"
    assert data.title == "NATSUNA 梶原夏奈"
    assert data.actors == ["梶原夏奈"]
    assert data.release == "2022-04-30"
    assert data.year == "2022"
    assert data.studio == "GirlsDelta"
    assert data.series == "GirlsDelta"
    assert data.mosaic == "无码"
    assert data.image_download is True
    assert data.thumb == "https://girlsdelta.com/pics/product/3b16ecbdf75722f23668dfcdfe630d58/product_top.webp"
    assert data.poster == "https://girlsdelta.com/pics/product/3b16ecbdf75722f23668dfcdfe630d58/sample.webp"
    assert data.trailer == "https://girlsdelta.com/pics/product/3b16ecbdf75722f23668dfcdfe630d58/movie.mp4"
    assert "ミニスカート" in data.tags
    assert "4K 動画" in data.tags
    assert "黒髪" in data.tags
    assert "T153/B100/W65/H86" in data.outline


@pytest.mark.asyncio
async def test_official_crawler_delegates_to_girlsdelta():
    mock_client = MagicMock()
    mock_client.get_text = AsyncMock(return_value=(MOCK_GIRLSDELTA_PRODUCT_HTML, None))
    crawler = OfficialCrawler(mock_client)

    ci = CrawlerInput.empty()
    ci.number = "GIRLSDELTA-1703"
    ci.file_path = Path("GirlsDelta-1703.mp4")
    resp = await crawler.run(ci)

    assert resp.data is not None
    assert resp.data.number == "GIRLSDELTA-1703"
    assert resp.data.title == "NATSUNA 梶原夏奈"
    assert resp.data.poster == "https://girlsdelta.com/pics/product/3b16ecbdf75722f23668dfcdfe630d58/sample.webp"
    assert resp.data.thumb == "https://girlsdelta.com/pics/product/3b16ecbdf75722f23668dfcdfe630d58/product_top.webp"


def test_poster_copy_policy_allows_direct_download_for_girlsdelta_sample_webp():
    res = CrawlersResult.empty()
    res.scraping_type = FixedScrapingType.WUMA
    res.image_download = True
    res.thumb = "https://girlsdelta.com/pics/product/3b16ecbdf75722f23668dfcdfe630d58/product_top.webp"
    res.poster = "https://girlsdelta.com/pics/product/3b16ecbdf75722f23668dfcdfe630d58/sample.webp"

    assert _get_poster_copy_policy(res, [DownloadableFile.IGNORE_WUMA]) is False
