import pytest

from mdcx.crawlers.base import Context
from mdcx.crawlers.official_uncensored import (
    crawl_uncensored_official,
    detail_url_for_uncensored_official,
    normalize_uncensored_official_id,
    route_uncensored_official,
    route_uncensored_official_candidates,
)
from mdcx.models.model_types import CrawlerInput, Language
from mdcx.number import is_uncensored


def test_cat_number_routing():
    # 1. 明确带前缀番号
    assert route_uncensored_official_candidates("C0930-ki170701") == [("c0930", "ki170701")]
    assert route_uncensored_official_candidates("H4610-ki170701") == [("h4610", "ki170701")]
    assert route_uncensored_official_candidates("H0930-ori1665") == [("h0930", "ori1665")]
    assert route_uncensored_official_candidates("c0930_ki221218") == [("c0930", "ki221218")]

    # 2. 单一确定路由
    assert route_uncensored_official("C0930-ki170701") == "c0930"
    assert route_uncensored_official("H4610-ki170701") == "h4610"
    assert route_uncensored_official("H0930-ori1665") == "h0930"

    # 3. ID 归一化与 URL 生成
    assert normalize_uncensored_official_id("C0930-ki170701") == "ki170701"
    assert (
        detail_url_for_uncensored_official("c0930", "ki170701")
        == "https://www.c0930.com/moviepages/ki170701/index.html"
    )
    assert (
        detail_url_for_uncensored_official("h4610", "ki170701")
        == "https://www.h4610.com/moviepages/ki170701/index.html"
    )
    assert (
        detail_url_for_uncensored_official("h0930", "ori1665") == "https://www.h0930.com/moviepages/ori1665/index.html"
    )

    # 4. 无前缀素人 ID 回退列表
    cands = route_uncensored_official_candidates("ki170701")
    assert cands == [("c0930", "ki170701"), ("h4610", "ki170701"), ("h0930", "ki170701")]


def test_cat_number_is_uncensored():
    assert is_uncensored("C0930-ki170701") is True
    assert is_uncensored("H4610-ki170701") is True
    assert is_uncensored("H0930-ori1665") is True
    assert is_uncensored("c0930-ki221218") is True


CAT_MOCK_HTML = """
<!DOCTYPE html>
<html>
<head><meta charset="euc-jp"><title>愛内 智美 29歳 - c0930</title></head>
<body>
  <div class="moviePlay_title">
    <h1><span class="style1">愛内 智美 29歳</span></h1>
    <span id="movietype1"> </span>
  </div>

  <div class="moviePlay_video">
    <video poster="https://www.c0930.com/moviepages/ki170701/images/movie.jpg" controls></video>
  </div>

  <div class="col-sm-4">
    <p>動画を再生するには、videoタグをサポートしたブラウザが必要です。</p>
    <p>【期間限定7/8まで】 智美さんの作品を再公開。一部始終をお楽しみください!!</p>
  </div>

  <dl>
    <dt>年齢</dt><dd>29歳</dd>
    <dt>身長</dt><dd>156cm</dd>
    <dt>3サイズ</dt><dd>98/70/95</dd>
    <dt>タイプ</dt><dd>ミセス　豊満　巨乳</dd>
    <dt>写真</dt><dd>84枚</dd>
    <dt>動画</dt><dd>00:51:29</dd>
    <dt>サイズ</dt><dd>1520 MB</dd>
    <dt>公開日</dt><dd>2017-07-01</dd>
    <dt>プレイ内容</dt><dd>生ハメ　中出し</dd>
  </dl>
</body>
</html>
"""


class FakeCatClient:
    def __init__(self, html: str = CAT_MOCK_HTML, fail_sites: set[str] | None = None):
        self.html = html
        self.fail_sites = fail_sites or set()

    async def get_text(self, url: str, **kwargs) -> tuple[str | None, str]:
        for fail_site in self.fail_sites:
            if fail_site in url:
                return None, f"GET {url} 失败: HTTP 404"
        return self.html, ""


@pytest.mark.asyncio
async def test_crawl_cat_site_parsing():
    client = FakeCatClient()
    ctx = Context(
        input=CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="无码",
            number="C0930-ki170701",
            short_number="C0930-ki170701",
            language=Language.ZH_CN,
            org_language=Language.JP,
        )
    )

    data = await crawl_uncensored_official(ctx, client, "C0930-ki170701")
    assert data is not None
    assert data.number == "C0930-ki170701"
    assert data.title == "愛内 智美 29歳"
    assert data.actors == ["愛内 智美"]
    assert data.release == "2017-07-01"
    assert data.year == "2017"
    assert data.runtime == "51"
    assert data.studio == "C0930"
    assert data.publisher == "C0930"
    assert "ミセス" in data.tags
    assert "巨乳" in data.tags
    assert "中出し" in data.tags
    assert "一部始終をお楽しみください!!" in data.outline
    assert data.thumb == "https://www.c0930.com/moviepages/ki170701/images/movie.jpg"
    assert data.poster == "https://www.c0930.com/moviepages/ki170701/images/movie.jpg"
    assert data.trailer == "https://smovie.c0930.com/moviepages/ki170701/sample.mp4"
    assert data.extrafanart == []
    assert data.mosaic == "无码"
    assert data.source == "c0930"


@pytest.mark.asyncio
async def test_crawl_cat_fallback_probing():
    # 模拟 c0930 404，平滑回退到 h4610 成功
    client = FakeCatClient(fail_sites={"c0930"})
    ctx = Context(
        input=CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="无码",
            number="ki170701",
            short_number="ki170701",
            language=Language.ZH_CN,
            org_language=Language.JP,
        )
    )

    data = await crawl_uncensored_official(ctx, client, "ki170701")
    assert data is not None
    assert data.studio == "H4610"
    assert data.source == "h4610"
    assert data.trailer == "https://smovie.h4610.com/moviepages/ki170701/sample.mp4"
