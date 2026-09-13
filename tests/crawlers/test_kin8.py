import json

import pytest

from mdcx.config.enums import Language
from mdcx.crawlers.kin8 import (
    Kin8Crawler,
    extract_kin8_id,
    extract_nextjs_movie_data,
    strip_rsc_date,
)
from mdcx.crawlers.official import OfficialCrawler
from mdcx.models.model_types import CrawlerInput


def make_input(number: str, appoint_url: str = "") -> CrawlerInput:
    return CrawlerInput(
        appoint_number="",
        appoint_url=appoint_url,
        file_path=None,
        mosaic="",
        number=number,
        short_number=number,
        language=Language.JP,
        org_language=Language.JP,
    )


def test_extract_kin8_id():
    assert extract_kin8_id("KIN8-3678") == "3678"
    assert extract_kin8_id("kin8-3678-4K") == "3678"
    assert extract_kin8_id("kin8_3678") == "3678"
    assert extract_kin8_id("KIN8TENGOKU-3678") == "3678"
    assert extract_kin8_id("3678") == "3678"
    assert extract_kin8_id("https://en.kin8tengoku.com/movie/3678") == "3678"
    assert extract_kin8_id("https://www.kin8tengoku.com/moviepages/3678/index.html") == "3678"
    assert extract_kin8_id("https://enexbabes.kin8tengoku.com/3678/") == "3678"
    assert extract_kin8_id("SSIS-001") is None
    assert extract_kin8_id("") is None


def test_strip_rsc_date():
    assert strip_rsc_date("$D2023-02-18T00:00:00.000Z") == "2023-02-18"
    assert strip_rsc_date("2023-02-18") == "2023-02-18"
    assert strip_rsc_date(None) == ""


def test_extract_nextjs_movie_data():
    movie_obj = {
        "movie_id": "3678",
        "name_utf8": "TEENの妄想エッチ Kamilia",
        "name_en": "Delusion Sex of Cutie",
        "act_utf8": "カミリア",
        "act_en": "Kamilia",
        "ecp_start_date": "$D2023-02-18T00:00:00.000Z",
        "detail": {
            "duration": 1646,
            "memo_utf8": "18歳のカミリアちゃん！",
        },
        "categories": [
            {"category_name_utf8": "フェラチオ", "category_name_en": "Blowjobs"},
            {"category_name_utf8": "HD動画", "category_key_name": "op_flag_hd"},
        ],
    }
    rsc_tree = [[3, "something", "movie", {"movie": movie_obj}]]
    encoded_json = json.dumps(rsc_tree)
    # RSC inlines string literals inside JS function calls
    payload = json.dumps(f"15:{encoded_json}")
    mock_html = f"<html><body><script>self.__next_f.push([1,{payload}])</script></body></html>"

    extracted = extract_nextjs_movie_data(mock_html)
    assert extracted is not None
    assert extracted["movie_id"] == "3678"
    assert extracted["name_utf8"] == "TEENの妄想エッチ Kamilia"
    assert extracted["act_utf8"] == "カミリア"


@pytest.mark.asyncio
async def test_kin8_crawler_run_success():
    movie_obj = {
        "movie_id": "3678",
        "name_utf8": "TEENの妄想エッチ Kamilia",
        "name_en": "Delusion Sex of Cutie",
        "act_utf8": "カミリア",
        "act_en": "Kamilia",
        "ecp_start_date": "$D2023-02-18T00:00:00.000Z",
        "detail": {
            "duration": 1646,
            "memo_utf8": "18歳のカミリアちゃん！",
        },
        "categories": [
            {"category_name_utf8": "フェラチオ", "category_name_en": "Blowjobs"},
            {"category_name_utf8": "ぶっかけ", "category_name_en": "Bukkake"},
            {"category_name_utf8": "低画质", "category_key_name": "op_flag_lowqualitymovie"},
        ],
    }
    rsc_tree = [[3, "something", "movie", {"movie": movie_obj}]]
    encoded_json = json.dumps(rsc_tree)
    payload = json.dumps(f"15:{encoded_json}")
    mock_html = f"<script>self.__next_f.push([1,{payload}])</script>"

    class MockAsyncClient:
        async def get_text(self, url: str):
            return mock_html, ""

    crawler = Kin8Crawler(client=MockAsyncClient())
    resp = await crawler.run(make_input("KIN8-3678"))

    assert resp.debug_info.error is None
    data = resp.data
    assert data is not None
    assert data.number == "KIN8-3678"
    assert data.title == "TEENの妄想エッチ Kamilia"
    assert data.actors == ["カミリア"]
    assert data.all_actors == ["カミリア", "Kamilia"]
    assert data.release == "2023-02-18"
    assert data.year == "2023"
    assert data.runtime == "27"
    assert data.outline == "18歳のカミリアちゃん！"
    assert data.tags == ["フェラチオ", "ぶっかけ"]
    assert data.studio == "kin8tengoku"
    assert data.thumb == "https://www.kin8tengoku.com/3678/pht/1.jpg"
    assert data.poster == "https://www.kin8tengoku.com/3678/pht/1.jpg"
    assert len(data.extrafanart) == 4
    assert data.extrafanart[0] == "https://www.kin8tengoku.com/3678/pht/2.jpg"
    assert data.trailer == "https://smovie.kin8tengoku.com/sample_mobile_template/3678/hls-1800k.mp4"
    assert data.source == "kin8"


@pytest.mark.asyncio
async def test_official_crawler_routes_kin8():
    movie_obj = {
        "movie_id": "3678",
        "name_utf8": "TEENの妄想エッチ Kamilia",
        "name_en": "Delusion Sex of Cutie",
        "act_utf8": "カミリア",
        "act_en": "Kamilia",
        "ecp_start_date": "$D2023-02-18T00:00:00.000Z",
        "detail": {
            "duration": 1646,
            "memo_utf8": "18歳のカミリアちゃん！",
        },
        "categories": [],
    }
    rsc_tree = [[3, "something", "movie", {"movie": movie_obj}]]
    encoded_json = json.dumps(rsc_tree)
    payload = json.dumps(f"15:{encoded_json}")
    mock_html = f"<script>self.__next_f.push([1,{payload}])</script>"

    class MockAsyncClient:
        async def get_text(self, url: str):
            return mock_html, ""

    crawler = OfficialCrawler(client=MockAsyncClient())
    resp = await crawler.run(make_input("KIN8-3678"))

    assert resp.debug_info.error is None
    assert resp.data is not None
    assert resp.data.number == "KIN8-3678"
    assert resp.data.source == "official"


@pytest.mark.asyncio
async def test_kin8_crawler_invalid_number():
    class MockAsyncClient:
        async def get_text(self, url: str):
            return "", ""

    crawler = Kin8Crawler(client=MockAsyncClient())
    resp = await crawler.run(make_input("INVALID-CAR"))
    assert resp.debug_info.error is not None
    assert "未识别到金8天国ID" in str(resp.debug_info.error)


@pytest.mark.asyncio
async def test_kin8_crawler_network_error():
    class MockAsyncClient:
        async def get_text(self, url: str):
            return None, "Connection timeout"

    crawler = Kin8Crawler(client=MockAsyncClient())
    resp = await crawler.run(make_input("KIN8-3678"))
    assert resp.debug_info.error is not None
    assert "网络请求错误" in str(resp.debug_info.error)


@pytest.mark.asyncio
async def test_kin8_crawler_missing_movie_data():
    class MockAsyncClient:
        async def get_text(self, url: str):
            return '<html><body>self.__next_f.push([1,"no movie payload"])</body></html>', ""

    crawler = Kin8Crawler(client=MockAsyncClient())
    resp = await crawler.run(make_input("KIN8-3678"))
    assert resp.debug_info.error is not None
    assert "获取金8天国详情页数据失败" in str(resp.debug_info.error)
