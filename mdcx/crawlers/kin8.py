#!/usr/bin/env python3
import json
import re
from typing import Any, override
from urllib.parse import urlparse

from ..config.enums import Website
from .base import BaseCrawler, Context, CrawlerData, CrawlerException, get_year

RSC_CHUNK_RE = re.compile(r'self\.__next_f\.push\(\[1,\s*"((?:[^"\\]|\\.)*)"\]\)', re.DOTALL)
KIN8_NUMBER_RE = re.compile(r"^(?:KIN8(?:TENGOKU)?[-_ ]*)?(\d{3,})(?:-.*)?$", re.IGNORECASE)
KIN8_URL_ID_RE = re.compile(r"/(?:moviepages|movie)/(\d+)|/(\d{3,})/?$")


def extract_kin8_id(number_or_url: str) -> str | None:
    """从番号字符串或直接 URL 中提取纯数字 ID (例如 KIN8-3678 -> 3678)."""
    val = (number_or_url or "").strip()
    if not val:
        return None

    # 1. 尝试从 URL 路径解析
    if "://" in val or val.startswith("/"):
        path = urlparse(val).path
        if match := KIN8_URL_ID_RE.search(path):
            for group in match.groups():
                if group:
                    return group

    # 2. 尝试从番号规范正则解析
    # 处理类似 KIN8-3678, KIN8TENGOKU-3678, kin8-3678-4k, kin8_3678
    if match := re.search(r"KIN8(?:TENGOKU)?[-_ ]*(\d{3,})", val, re.IGNORECASE):
        return match.group(1)

    # 3. 纯数字兜底（如果已经直接输入了 3678 等）
    if match := re.search(r"^\d{3,5}$", val):
        return match.group(0)

    return None


def extract_nextjs_movie_data(html: str) -> dict[str, Any] | None:
    """从 Next.js (React Server Components, RSC) 页面脚本中提取 movie JSON 数据."""
    for m in RSC_CHUNK_RE.finditer(html):
        try:
            decoded = json.loads('"' + m.group(1) + '"')
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue

        if '"movie"' not in decoded:
            continue

        try:
            colon_idx = decoded.index(":")
            data = json.loads(decoded[colon_idx + 1 :])
            # Next.js RSC payload tree: data[0][3]["movie"]
            if isinstance(data, list) and len(data) > 0 and len(data[0]) > 3:
                movie = data[0][3].get("movie")
                if isinstance(movie, dict):
                    return movie
        except (json.JSONDecodeError, IndexError, KeyError, TypeError, ValueError):
            continue

    return None


def strip_rsc_date(value: str | None) -> str:
    """清洗 RSC 序列化日期 (如 '$D2023-02-18T00:00:00.000Z' -> '2023-02-18')."""
    if not value:
        return ""
    clean = value.removeprefix("$D")
    return clean.split("T")[0] if "T" in clean else clean


class Kin8Crawler(BaseCrawler):
    description = "金8天国（无码专属）"
    probe_number = "KIN8-3678"

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.KIN8

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://en.kin8tengoku.com"

    @override
    async def _run(self, ctx: Context):
        appoint_url = ctx.input.appoint_url
        number = ctx.input.number

        movie_id = extract_kin8_id(appoint_url) if appoint_url else extract_kin8_id(number)
        if not movie_id:
            raise CrawlerException(f"番号中未识别到金8天国ID: {number}")

        standard_number = f"KIN8-{movie_id}"
        detail_url = appoint_url or f"{self.base_url}/movie/{movie_id}"
        ctx.debug_info.detail_urls = [detail_url]

        html_content, error = await self.async_client.get_text(detail_url)
        if html_content is None or "self.__next_f" not in html_content:
            # 备用域名探测 (enexbabes)
            fallback_url = f"https://enexbabes.kin8tengoku.com/movie/{movie_id}"
            html_content, error = await self.async_client.get_text(fallback_url)
            if html_content is not None and "self.__next_f" in html_content:
                detail_url = fallback_url
                ctx.debug_info.detail_urls = [detail_url]

        if html_content is None:
            raise CrawlerException(f"金8天国网络请求错误: {error}")

        movie = extract_nextjs_movie_data(html_content)
        if not movie:
            raise CrawlerException(f"获取金8天国详情页数据失败: {detail_url}")

        title_ja = (movie.get("name_utf8") or "").strip()
        title_en = (movie.get("name_en") or "").strip()
        title = title_ja or title_en or standard_number

        act_ja = (movie.get("act_utf8") or "").strip()
        act_en = (movie.get("act_en") or "").strip()
        actors = [act_ja] if act_ja else ([act_en] if act_en else [])
        all_actors = [a for a in [act_ja, act_en] if a] or actors

        release = strip_rsc_date(movie.get("ecp_start_date"))
        year = get_year(release)

        duration_sec = movie.get("detail", {}).get("duration") or 0
        runtime = str(max(1, int(duration_sec) // 60)) if duration_sec else ""

        memo = (movie.get("detail", {}).get("memo_utf8") or "").strip()

        # 过滤 categories 中的管理属性 (op_flag_...)
        tags = []
        for cat in movie.get("categories", []):
            if not isinstance(cat, dict):
                continue
            if cat.get("category_key_name"):
                continue
            t_ja = (cat.get("category_name_utf8") or "").strip()
            t_en = (cat.get("category_name_en") or "").strip()
            if t_ja:
                tags.append(t_ja)
            elif t_en:
                tags.append(t_en)
        tags = list(dict.fromkeys(tags))

        # 静态封面、缩略图与剧照
        cover_url = f"https://www.kin8tengoku.com/{movie_id}/pht/1.jpg"
        extrafanart = [f"https://www.kin8tengoku.com/{movie_id}/pht/{i}.jpg" for i in range(2, 6)]
        trailer = f"https://smovie.kin8tengoku.com/sample_mobile_template/{movie_id}/hls-1800k.mp4"

        data = CrawlerData(
            number=standard_number,
            title=title,
            originaltitle=title,
            actors=actors,
            all_actors=all_actors,
            outline=memo,
            originalplot=memo,
            tags=tags,
            release=release,
            year=year,
            runtime=runtime,
            studio="kin8tengoku",
            publisher="kin8tengoku",
            thumb=cover_url,
            poster=cover_url,
            extrafanart=extrafanart,
            trailer=trailer,
            image_download=True,
            mosaic="无码",
            external_id=detail_url,
            source=self.site().value,
        )

        return await self.post_process(ctx, data.to_result())

    @override
    async def _generate_search_url(self, ctx: Context) -> list[str] | str | None:
        return None

    @override
    async def _parse_search_page(self, ctx: Context, html, search_url: str) -> list[str] | str | None:
        return None

    @override
    async def _parse_detail_page(self, ctx: Context, html, detail_url: str) -> CrawlerData | None:
        return None
