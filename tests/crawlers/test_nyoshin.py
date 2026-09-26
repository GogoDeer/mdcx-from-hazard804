"""Unit tests for Nyoshin (女体のしんぴ / nyoshin.com) official site scraper."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from mdcx.config.enums import FixedScrapingType, Website
from mdcx.core.file_crawler import classify_scrape_task
from mdcx.crawlers.base import get_crawler
from mdcx.crawlers.nyoshin import (
    NyoshinCrawler,
    extract_nyoshin_id,
    extract_nyoshin_movie_data,
    is_nyoshin_number,
)
from mdcx.crawlers.official import OfficialCrawler
from mdcx.models.model_types import CrawlerInput, CrawlTask
from mdcx.number import extract_brand_number, get_file_number, get_number_letters, is_uncensored

MOCK_NYOSHIN_RSC_HTML = r"""
<!DOCTYPE html>
<html lang="ja">
<head>
  <title>超アナルアングル | かな | 女体のしんぴ</title>
  <meta property="og:title" content="超アナルアングル | かな | 女体のしんぴ" />
  <meta property="og:description" content="今回のモデルはかなちゃん24歳、サービス業を営む女の子。" />
  <meta property="og:image" content="https://www.nyoshin.com/contents/1980/thum2.jpg" />
  <meta property="og:video" content="https://smovie.nyoshin.com/contents/1980/sample.mp4" />
</head>
<body>
  <h1 class="movie-main-title">超アナルアングル</h1>
  <div class="movie-data-list">
    <a href="/list/actress/1686">かな</a>
    <span>公開日 : 2020-02-03</span>
    <span>再生時間 : 00:19:43</span>
  </div>
  <div class="movie-category-tags">
    <a href="/list/category/16">オナニー</a>
    <a href="/list/category/14">アナル</a>
  </div>
  <p class="detail-comment">今回のモデルはかなちゃん24歳、サービス業を営む女の子。</p>
  <script>self.__next_f.push([1,"f:[\"$\",\"$L15\",null,{\"movie\":{\"id\":1980,\"name_utf8\":\"超アナルアングル\",\"name_en\":\"Super Anal Angle\",\"act_utf8\":\"かな\",\"act_en\":\"Kana\",\"ecp_start_date\":\"$D2020-02-03T00:00:00.000Z\",\"detail\":{\"movie_id\":1980,\"duration\":1183,\"memo_utf8\":\"今回のモデルはかなちゃん24歳、サービス業を営む女の子。\"},\"categories\":[{\"category_id\":16,\"category_name_utf8\":\"オナニー\",\"category_name_en\":\"Masturbation\",\"category_key_name\":null},{\"category_id\":14,\"category_name_utf8\":\"アナル\",\"category_name_en\":\"Anal\",\"category_key_name\":null},{\"category_id\":33,\"category_name_utf8\":\"HDダウンロード可\",\"category_name_en\":\"HD\",\"category_key_name\":\"op_flag_dl_hd\"}],\"galleryFilenames\":[\"1.jpg\",\"2.jpg\",\"3.jpg\"]}}]\n"])</script>
</body>
</html>
"""

MOCK_NYOSHIN_DOM_ONLY_HTML = """
<!DOCTYPE html>
<html lang="ja">
<head>
  <meta property="og:image" content="https://www.nyoshin.com/contents/1489/thum2.jpg" />
  <meta property="og:video" content="https://smovie.nyoshin.com/contents/1489/sample.mp4" />
</head>
<body>
  <h1 class="movie-main-title">着替え劇場</h1>
  <div class="movie-data-list">
    <a href="/list/actress/1205">しんぴな娘たち</a>
    <span>公開日 : 2017-05-06</span>
    <span>再生時間 : 00:21:11</span>
  </div>
  <div class="movie-category-tags">
    <a href="/list/category/20">コスプレ</a>
    <a href="/list/category/24">脚フェチ</a>
  </div>
  <p class="detail-comment">コスプレ衣装への生着替えをじっくり観察。</p>
</body>
</html>
"""


def test_nyoshin_registration():
    crawler_cls = get_crawler(Website.NYOSHIN)
    assert crawler_cls is NyoshinCrawler


@pytest.mark.parametrize(
    ("raw_name", "filepath", "expected"),
    [
        ("nyoshin_n1980", r"A:\temp\scan\input\女体\nyoshin_n1980.wmv", "NYOSHIN-n1980"),
        ("nyoshin-1489", r"A:\temp\scan\input\nyoshin-1489.mp4", "NYOSHIN-n1489"),
        ("n1525", r"A:\temp\scan\input\女体\n1525.wmv", "NYOSHIN-n1525"),
        ("n1987", r"A:\temp\scan\input\女体のしんぴ\n1987.wmv", "NYOSHIN-n1987"),
    ],
)
def test_nyoshin_brand_number_extraction(raw_name: str, filepath: str, expected: str):
    assert extract_brand_number(raw_name, filepath) == expected
    assert get_file_number(filepath, []) == expected
    assert is_uncensored(expected) is True
    assert get_number_letters(expected) == "NYOSHIN"


@pytest.mark.parametrize(
    ("val", "expected_id"),
    [
        ("NYOSHIN-n1980", "1980"),
        ("nyoshin_n1489.wmv", "1489"),
        ("https://www.nyoshin.com/moviepages/n1527", "1527"),
        ("https://www.nyoshin.com/moviepages/1581", "1581"),
        (r"A:\temp\scan\input\女体\n1972.wmv", "1972"),
    ],
)
def test_extract_nyoshin_id(val: str, expected_id: str):
    assert extract_nyoshin_id(val) == expected_id
    assert is_nyoshin_number(val) is True


def test_extract_nyoshin_rsc_movie():
    movie = extract_nyoshin_movie_data(MOCK_NYOSHIN_RSC_HTML)
    assert movie is not None
    assert movie["id"] == 1980
    assert movie["name_utf8"] == "超アナルアングル"
    assert movie["act_utf8"] == "かな"


def test_classify_scrape_task_routes_nyoshin():
    task = CrawlTask.empty()
    task.number = "NYOSHIN-n1980"
    task.file_path = Path(r"A:\temp\scan\input\女体\nyoshin_n1980.wmv")
    dummy_config = MagicMock()
    dummy_config.fixed_scraping_type = FixedScrapingType.AUTO
    classification = classify_scrape_task(task, dummy_config)
    assert classification.scraping_type == FixedScrapingType.WUMA
    assert classification.website == Website.NYOSHIN
    assert classification.mosaic == "无码"


@pytest.mark.asyncio
async def test_nyoshin_crawler_rsc_parsing():
    mock_client = MagicMock()
    mock_client.get_text = AsyncMock(return_value=(MOCK_NYOSHIN_RSC_HTML, ""))

    crawler = NyoshinCrawler(client=mock_client)
    crawler_input = CrawlerInput.empty()
    crawler_input.number = "NYOSHIN-n1980"
    crawler_input.file_path = Path(r"A:\temp\scan\input\女体\nyoshin_n1980.wmv")

    response = await crawler.run(crawler_input)
    assert response.debug_info.error is None
    assert response.data is not None

    data = response.data
    assert data.number == "NYOSHIN-n1980"
    assert data.title == "超アナルアングル"
    assert data.actors == ["かな"]
    assert data.release == "2020-02-03"
    assert data.year == "2020"
    assert data.runtime == "19"
    assert data.studio == "女体のしんぴ"
    assert data.publisher == "女体のしんぴ"
    assert data.series == "女体のしんぴ"
    assert data.tags == ["オナニー", "アナル"]
    assert data.thumb == "https://www.nyoshin.com/contents/1980/thum2.jpg"
    assert data.poster == "https://www.nyoshin.com/contents/1980/thum2.jpg"
    assert data.extrafanart == [
        "https://www.nyoshin.com/contents/1980/1.jpg",
        "https://www.nyoshin.com/contents/1980/2.jpg",
        "https://www.nyoshin.com/contents/1980/3.jpg",
    ]
    assert data.trailer == "https://smovie.nyoshin.com/contents/1980/sample.mp4"
    assert data.mosaic == "无码"
    assert data.image_download is False

    # Verify Accept header and over18_confirmed cookie were sent
    call_kwargs = mock_client.get_text.call_args.kwargs
    assert "text/html" in call_kwargs["headers"]["Accept"]
    assert call_kwargs["cookies"]["over18_confirmed"] == "1"


@pytest.mark.asyncio
async def test_nyoshin_crawler_dom_fallback_and_official_delegation():
    mock_client = MagicMock()
    mock_client.get_text = AsyncMock(return_value=(MOCK_NYOSHIN_DOM_ONLY_HTML, ""))

    official = OfficialCrawler(client=mock_client)
    crawler_input = CrawlerInput.empty()
    crawler_input.number = "NYOSHIN-n1489"
    crawler_input.file_path = Path(r"A:\temp\scan\input\女体\nyoshin_n1489.wmv")

    response = await official.run(crawler_input)
    assert response.debug_info.error is None
    assert response.data is not None

    data = response.data
    assert data.number == "NYOSHIN-n1489"
    assert data.title == "着替え劇場"
    assert data.actors == ["しんぴな娘たち"]
    assert data.release == "2017-05-06"
    assert data.runtime == "21"
    assert data.tags == ["コスプレ", "脚フェチ"]
    assert data.source == Website.OFFICIAL.value
