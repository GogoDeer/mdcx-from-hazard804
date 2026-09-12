import pytest

from mdcx.crawlers.base import Context, CrawlerException
from mdcx.crawlers.official_uncensored import (
    crawl_uncensored_official,
    route_uncensored_official,
    route_uncensored_official_candidates,
)
from mdcx.models.model_types import CrawlerInput, Language


def test_route_uncensored_official_candidates():
    # 1. 明确前缀：单站点
    assert route_uncensored_official_candidates("caribpr-072817_001") == [("caribbeancompr", "072817_001")]
    assert route_uncensored_official_candidates("cappv-072817_001") == [("caribbeancompr", "072817_001")]
    assert route_uncensored_official_candidates("1pondo-010120_001") == [("1pondo", "010120_001")]
    assert route_uncensored_official_candidates("heyzo-1234") == [("heyzo", "1234")]

    # 2. 纯数字：下划线，尾号 < 100
    cands_under_small = route_uncensored_official_candidates("072817_001")
    assert cands_under_small == [
        ("1pondo", "072817_001"),
        ("caribbeancompr", "072817_001"),
        ("pacopacomama", "072817_001"),
    ]

    # 3. 纯数字：下划线，尾号 >= 100
    cands_under_large = route_uncensored_official_candidates("072817_150")
    assert cands_under_large == [
        ("pacopacomama", "072817_150"),
        ("1pondo", "072817_150"),
        ("caribbeancompr", "072817_150"),
    ]

    # 4. 纯数字：下划线，两位尾号（天然素人）
    cands_10mu = route_uncensored_official_candidates("072817_01")
    assert cands_10mu == [
        ("10musume", "072817_01"),
        ("1pondo", "072817_01"),
        ("caribbeancompr", "072817_01"),
    ]

    # 5. 纯数字：中划线（加勒比）
    cands_hyphen = route_uncensored_official_candidates("072817-001")
    assert cands_hyphen == [
        ("caribbeancom", "072817-001"),
        ("caribbeancompr", "072817_001"),
        ("1pondo", "072817_001"),
    ]

    # 6. 保证向后兼容的单一路由函数
    assert route_uncensored_official("072817_001") == "1pondo"
    assert route_uncensored_official("caribpr-072817_001") == "caribbeancompr"


class FakeFallbackClient:
    def __init__(self, fail_sites: set[str] | None = None):
        self.fail_sites = fail_sites or set()

    async def get_text(self, url: str, **kwargs) -> tuple[str | None, str]:
        if "1pondo.tv" in url and "1pondo" in self.fail_sites:
            return None, f"GET {url} 失败: HTTP 404"

        if "caribbeancompr.com" in url:
            if "caribbeancompr" in self.fail_sites:
                return None, f"GET {url} 失败: HTTP 404"
            return (
                """
                <html><body>
                  <h1 itemprop="name">加勒比PR测试影片</h1>
                  <ul>
                    <li class="movie-spec"><span class="spec-title">出演:</span><span class="spec-content">测试女优</span></li>
                    <li class="movie-spec"><span class="spec-title">配信日:</span><span class="spec-content">2017-07-28</span></li>
                    <li class="movie-spec"><span class="spec-title">再生時間:</span><span class="spec-content">01:30:00</span></li>
                  </ul>
                  <div itemprop="description">测试简介内容</div>
                </body></html>
                """,
                "",
            )

        return None, f"GET {url} 失败: HTTP 404"


@pytest.mark.asyncio
async def test_crawl_uncensored_official_fallback_success():
    # 模拟 1pondo 404，回退到 caribbeancompr 成功
    client = FakeFallbackClient(fail_sites={"1pondo"})
    ctx = Context(
        input=CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="无码",
            number="072817_001",
            short_number="072817_001",
            language=Language.ZH_CN,
            org_language=Language.JP,
        )
    )

    data = await crawl_uncensored_official(ctx, client, "072817_001")
    assert data is not None
    assert data.title == "加勒比PR测试影片"
    assert data.actors == ["测试女优"]
    assert data.release == "2017-07-28"
    assert data.runtime == "90"
    assert data.studio == "CaribbeancomPR"


@pytest.mark.asyncio
async def test_crawl_uncensored_official_all_fail_raises():
    # 模拟所有站点均 404
    client = FakeFallbackClient(fail_sites={"1pondo", "caribbeancompr", "pacopacomama"})
    ctx = Context(
        input=CrawlerInput(
            appoint_number="",
            appoint_url="",
            file_path=None,
            mosaic="无码",
            number="072817_001",
            short_number="072817_001",
            language=Language.ZH_CN,
            org_language=Language.JP,
        )
    )

    with pytest.raises(CrawlerException) as exc_info:
        await crawl_uncensored_official(ctx, client, "072817_001")
    assert "404" in str(exc_info.value)
