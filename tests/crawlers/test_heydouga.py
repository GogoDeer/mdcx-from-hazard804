"""Unit tests for Heydouga official site scraper."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from parsel import Selector

from mdcx.config.enums import Website
from mdcx.crawlers.base import Context, get_crawler
from mdcx.crawlers.heydouga import (
    HeydougaCrawler,
    extract_heydouga_parts,
    is_heydouga_number,
)
from mdcx.crawlers.official import OfficialCrawler
from mdcx.models.model_types import CrawlerInput

MOCK_HEYDOUGA_HTML = """
<!DOCTYPE html>
<html lang="ja">
<head>
  <title>【ガチん娘！NK】完全期間限定配信　実録ガチ面接316、317 - とわ - Hey動画 PPV（単品販売）</title>
  <meta property="og:title" content="【ガチん娘！NK】完全期間限定配信　実録ガチ面接316、317 - とわ" />
  <meta property="og:description" content="【Hey動画単品販売】とわの動画単品販売! - 【ガチん娘！NK】完全期間限定配信　実録ガチ面接316、317 - 今回は若くて可愛らしい奥様、とわチャンの出産ビフォーアフターです。" />
  <meta property="og:image" content="https://image01-www.heydouga.com/contents/4037/531/player_thumb.webp" />
</head>
<body>
  <h1>とわ&nbsp;-&nbsp;【ガチん娘！NK】完全期間限定配信　実録ガチ面接316、317</h1>
  <div id="movie-info">
    <div class="row">
      <span class="info-title">主演</span>
      <span class="info-content"><a href="/actor/towa">とわ</a></span>
    </div>
    <div class="row">
      <span class="info-title">配信日</span>
      <span class="info-content">2021-11-17</span>
    </div>
    <div class="row">
      <span class="info-title">提供元</span>
      <span class="info-content"><a href="/provider/4037">ガチん娘！</a></span>
    </div>
  </div>
  <div id="movie-detail-desktop">
    今回は若くて可愛らしい奥様、とわチャンの出産ビフォーアフターです。まずは、妊娠9ヶ月時。
  </div>
  <div id="movie_tag_list">
    <li><a href="#">素人</a></li>
    <li><a href="#">人妻・熟女</a></li>
    <li><a href="#">中出し</a></li>
  </div>
  <script>
    var movie_seq = '133587';
    var provider_id = 4037;
    setEcpEmbedMovieBtn("#embed-movie",{
        site_id:"352",
        movie_src:"https://www.heydouga.com/contents/4037/531/sample.mp4"
    });
  </script>
</body>
</html>
"""


def test_heydouga_registration():
    crawler_cls = get_crawler(Website.HEYDOUGA)
    assert crawler_cls is HeydougaCrawler
    assert HeydougaCrawler.site() == Website.HEYDOUGA
    assert HeydougaCrawler.base_url_() == "https://www.heydouga.com"


def test_extract_heydouga_parts():
    # 1. 纯数字番号
    assert extract_heydouga_parts("4037-531") == ("4037", "531")
    assert extract_heydouga_parts("4030-852") == ("4030", "852")
    assert extract_heydouga_parts("4242-1024") == ("4242", "1024")

    # 2. 带厂牌前缀
    assert extract_heydouga_parts("heydouga-4037-531") == ("4037", "531")
    assert extract_heydouga_parts("HEYDOUGA 4037-531") == ("4037", "531")
    assert extract_heydouga_parts("ppv-heydouga-4037-531") == ("4037", "531")

    # 3. 复杂生肉文件名与路径
    raw_file = "heydouga 4037-531-real interview 316 Towa01.wmv"
    assert extract_heydouga_parts(raw_file) == ("4037", "531")

    # 4. URL 格式提取
    url = "https://www.heydouga.com/moviepages/4037/531/index.html"
    assert extract_heydouga_parts(url) == ("4037", "531")

    # 5. 负例：非 Heydouga 番号
    assert extract_heydouga_parts("FC2-PPV-123456") is None
    assert extract_heydouga_parts("MIDV-001") is None
    assert extract_heydouga_parts("072817_001") is None  # 一本道 6 位日期番号
    assert extract_heydouga_parts("C0930-ki230101") is None


def test_is_heydouga_number():
    assert is_heydouga_number("4037-531") is True
    assert is_heydouga_number("heydouga-4037-531") is True
    assert is_heydouga_number("heydouga 4037-531-real interview 316") is True
    assert is_heydouga_number("FC2-123456") is False
    assert is_heydouga_number("SSIS-001") is False


@pytest.mark.asyncio
async def test_heydouga_generate_search_url():
    mock_client = MagicMock()
    crawler = HeydougaCrawler(mock_client)

    # 1. 正常番号
    ci = CrawlerInput.empty()
    ci.number = "4037-531"
    ctx = Context(input=ci)
    url = await crawler._generate_search_url(ctx)
    assert url == "https://www.heydouga.com/moviepages/4037/531/index.html"

    # 2. 指定 URL
    ci2 = CrawlerInput.empty()
    ci2.appoint_url = "https://www.heydouga.com/moviepages/4030/852/index.html"
    ctx2 = Context(input=ci2)
    assert await crawler._generate_search_url(ctx2) == "https://www.heydouga.com/moviepages/4030/852/index.html"

    # 3. 非 Heydouga 番号返回 None
    ci3 = CrawlerInput.empty()
    ci3.number = "SSIS-123"
    ctx3 = Context(input=ci3)
    assert await crawler._generate_search_url(ctx3) is None


@pytest.mark.asyncio
async def test_heydouga_parse_detail_page():
    mock_client = MagicMock()
    crawler = HeydougaCrawler(mock_client)

    ci = CrawlerInput.empty()
    ci.number = "4037-531"
    ci.file_path = Path("heydouga 4037-531-real interview 316 Towa01.wmv")
    ctx = Context(input=ci)

    sel = Selector(MOCK_HEYDOUGA_HTML)
    data = await crawler._parse_detail_page(ctx, sel, "https://www.heydouga.com/moviepages/4037/531/index.html")

    assert data is not None
    assert data.title == "【ガチん娘！NK】完全期間限定配信　実録ガチ面接316、317 - とわ"
    assert data.actors == ["とわ"]
    assert data.series == "ガチん娘！NK"
    assert "出産ビフォーアフター" in data.outline
    assert data.release == "2021-11-17"
    assert data.year == "2021"
    assert data.thumb == "https://image01-www.heydouga.com/contents/4037/531/player_thumb.webp"
    assert data.poster == "https://image01-www.heydouga.com/contents/4037/531/player_thumb.webp"
    assert data.trailer == "https://www.heydouga.com/contents/4037/531/sample.mp4"
    assert "素人" in data.tags
    assert "中出し" in data.tags
    assert data.mosaic == "无码"
    assert data.studio == "Heydouga (ガチん娘！)"
    assert data.number == "4037-531"


@pytest.mark.asyncio
async def test_official_crawler_delegates_to_heydouga():
    mock_client = MagicMock()
    mock_client.get_text = AsyncMock(return_value=(MOCK_HEYDOUGA_HTML, None))

    official_crawler = OfficialCrawler(client=mock_client)

    ci = CrawlerInput.empty()
    ci.number = "4037-531"
    ci.file_path = Path("heydouga 4037-531-real interview 316 Towa01.wmv")
    ctx = Context(input=ci)

    res = await official_crawler._run(ctx)
    assert res is not None
    assert res.title == "【ガチん娘！NK】完全期間限定配信　実録ガチ面接316、317 - とわ"
    assert res.actors == ["とわ"]
    assert res.thumb == "https://image01-www.heydouga.com/contents/4037/531/player_thumb.webp"
    assert res.source == "official"
