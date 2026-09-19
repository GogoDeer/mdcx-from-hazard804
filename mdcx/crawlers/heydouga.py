#!/usr/bin/env python3
"""Heydouga (Hey動画) official site scraper."""

import json
import os
import re
from typing import override

from parsel import Selector

from ..config.models import Website
from .base import BaseCrawler, Context, CrawlerData, get_year

try:
    from .base import CrawlerException
except ImportError:
    from .base import CralwerException as CrawlerException  # type: ignore[no-redef]

HEYDOUGA_PATTERN = re.compile(
    r"^(?:heydouga|hey_douga|hey-douga|ppv-heydouga)?[-_ ]*(?P<provider>\d{4})[-_ ](?P<movie>\d{3,4})$",
    re.IGNORECASE,
)


def extract_heydouga_parts(value: str) -> tuple[str, str] | None:
    """从番号字符串、文件名或 URL 中提取 (provider_id, movie_id)。"""
    if not value:
        return None

    str_val = str(value).strip()

    # 1. 从详情页 URL 提取: .../moviepages/4037/531/index.html
    if url_match := re.search(r"/moviepages/(\d{4})/(\d{3,4})", str_val, re.IGNORECASE):
        return url_match.group(1), url_match.group(2)

    cleaned = os.path.splitext(os.path.basename(str_val))[0].strip("-_. ")

    # 2. 完整匹配常见番号格式: 4037-531, heydouga-4037-531, ppv-heydouga-4037-531
    if m := HEYDOUGA_PATTERN.match(cleaned):
        return m.group("provider"), m.group("movie")

    # 3. 显式带有 heydouga 厂牌名 + 4位-3~4位数字
    if brand_match := re.search(r"heydouga[-_ ]*(\d{4})[-_](\d{3,4})", str_val, re.IGNORECASE):
        return brand_match.group(1), brand_match.group(2)

    # 4. 纯数字两段式: 4xxx-xxx
    if num_match := re.search(r"\b(4\d{3})[-_](\d{3,4})\b", str_val):
        return num_match.group(1), num_match.group(2)

    return None


def is_heydouga_number(number: str) -> bool:
    """判断是否属于 Heydouga 番号格式。"""
    return extract_heydouga_parts(number) is not None


class HeydougaCrawler(BaseCrawler):
    """Heydouga (heydouga.com) official site scraper."""

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.HEYDOUGA

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://www.heydouga.com"

    @override
    async def _generate_search_url(self, ctx: Context) -> list[str] | str | None:
        if ctx.input.appoint_url:
            return ctx.input.appoint_url

        parts = extract_heydouga_parts(str(ctx.input.file_path or ctx.input.number))
        if not parts:
            ctx.debug("未识别到有效的 Heydouga 编号，跳过 Heydouga 官方爬虫")
            return None

        provider_id, movie_id = parts
        detail_url = f"{self.base_url}/moviepages/{provider_id}/{movie_id}/index.html"
        ctx.debug(f"Heydouga 生成直通详情页: {detail_url}")
        return detail_url

    @override
    async def _parse_search_page(self, ctx: Context, html: Selector, search_url: str) -> list[str] | str | None:
        return search_url

    @override
    async def _parse_detail_page(self, ctx: Context, html: Selector, detail_url: str) -> CrawlerData | None:
        parts = extract_heydouga_parts(detail_url)
        if not parts:
            parts = extract_heydouga_parts(str(ctx.input.file_path or ctx.input.number))
        if not parts:
            raise CrawlerException(f"无法从 URL 或番号提取 Heydouga 编号: {detail_url}")

        provider_id, movie_id = parts

        # 1. 标题提取
        og_title = html.xpath("//meta[@property='og:title']/@content").get("")
        raw_title = og_title or html.xpath("//title/text()").get("") or html.css("h1::text").get("") or ""
        raw_title = raw_title.strip()
        if not raw_title:
            raise CrawlerException(f"Heydouga 详情页未找到标题: {detail_url}")

        clean_title = re.sub(r"\s*-\s*Hey動画.*$", "", raw_title).strip()
        clean_title = re.sub(r"\s*&#45;\s*", " - ", clean_title)
        clean_title = re.sub(r"&nbsp;", " ", clean_title)

        # 2. 女优名提取
        actress = ""
        # 优先从页面主演标签提取
        actress_from_info = html.xpath(
            '//*[@id="movie-info"]//span[contains(.,"主演") or contains(.,"出演")]/following-sibling::span//a/text()'
        ).getall()
        if actress_from_info:
            actress = actress_from_info[0].strip()

        # 其次从 og:description 的 "【Hey動画単品販売】XXXの動画単品販売!" 提取
        if not actress:
            desc = html.xpath("//meta[@property='og:description']/@content").get("") or ""
            if m := re.search(r"【Hey動画単品販売】(.*?)の動画", desc):
                actress = m.group(1).strip()

        # 再次从标题末尾的 " - 女优名" 提取
        if not actress and " - " in clean_title:
            actress = clean_title.split(" - ")[-1].strip()

        actors = [actress] if actress else []

        # 3. 系列 Series 提取
        series = ""
        if m := re.search(r"【(.*?)】", clean_title):
            series = m.group(1).strip()

        # 4. 剧情简介 Outline
        outline = (
            html.xpath("//*[@id='movie-detail-desktop']").xpath("string()").get("").strip()
            or html.xpath("//*[@id='movie-detail-mobile']").xpath("string()").get("").strip()
            or html.xpath("//meta[@property='og:description']/@content").get("").strip()
            or html.xpath("//meta[@name='description']/@content").get("").strip()
        )

        # 5. 配信日 Release 提取
        release_raw = html.xpath(
            '//*[@id="movie-info"]//span[contains(.,"配信日") or contains(.,"公開日")]/following-sibling::span/text()'
        ).get("")
        release = ""
        if release_raw:
            if dm := re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", release_raw):
                y, m, d = dm.groups()
                release = f"{y}-{int(m):02d}-{int(d):02d}"

        # 6. 高清封面海报 Thumb & Poster
        thumb = html.xpath("//meta[@property='og:image']/@content").get("")
        if not thumb:
            thumb = f"https://image01-www.heydouga.com/contents/{provider_id}/{movie_id}/player_thumb.webp"
        poster = thumb

        # 7. 预告片 Trailer
        sample_mp4 = html.xpath("//script[contains(text(), 'sample.mp4')]").re_first(
            r'movie_src\s*:\s*"(https:[^"]+sample\.mp4)"'
        )
        if not sample_mp4:
            sample_mp4 = f"https://www.heydouga.com/contents/{provider_id}/{movie_id}/sample.mp4"

        # 8. 标签 Tags 提取（支持静态标签及 AJAX API 动态补充）
        tags = [
            t.strip()
            for t in html.xpath(
                "//*[@id='movie_tag_list']//li//a/text() | //*[@id='movie_tag_list']//li/text()"
            ).getall()
            if t.strip() and t.strip() != "読み込み中…"
        ]
        if not tags:
            movie_seq = html.xpath("//script[contains(text(), 'movie_seq')]").re_first(
                r"movie_seq\s*=\s*['\"](\d+)['\"]"
            )
            if movie_seq:
                try:
                    tag_url = f"{self.base_url}/get_movie_tag_all/"
                    tag_headers = {
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "X-Requested-With": "XMLHttpRequest",
                    }
                    tag_data = {"movie_seq": movie_seq, "provider_id": provider_id, "lang": "ja"}
                    tag_resp, _ = await self.async_client.post_text(tag_url, data=tag_data, headers=tag_headers)
                    if tag_resp:
                        tag_json = json.loads(tag_resp)
                        if tag_json.get("result") == 0:
                            tags = [t.get("tag_name") for t in tag_json.get("tag", []) if t.get("tag_name")]
                except Exception as e:
                    ctx.debug(f"获取 Heydouga 标签 API 失败: {e}")

        # 9. 厂商与发行商
        studio = "Heydouga"
        provider_name = html.xpath(
            '//*[@id="movie-info"]//span[contains(.,"提供元")]/following-sibling::span//text()'
        ).get("")
        if provider_name and provider_name.strip():
            studio = f"Heydouga ({provider_name.strip()})"

        standard_number = f"HEYDOUGA-{provider_id}-{movie_id}"
        if ctx.input.number and re.match(r"^HEYDOUGA-\d+-\d+$", ctx.input.number, re.IGNORECASE):
            standard_number = ctx.input.number.upper()
        elif ctx.input.number and re.match(r"^\d{4}-\d{3,4}$", ctx.input.number):
            standard_number = ctx.input.number

        return CrawlerData(
            number=standard_number,
            title=clean_title,
            originaltitle=clean_title,
            actors=actors,
            all_actors=actors,
            outline=outline,
            originalplot=outline,
            tags=tags,
            release=release,
            year=get_year(release),
            runtime="",
            series=series,
            studio=studio,
            publisher=studio,
            thumb=thumb,
            poster=poster,
            extrafanart=[],
            trailer=sample_mp4,
            image_download=True,
            mosaic="无码",
            external_id=detail_url,
        )
