#!/usr/bin/env python3
"""Nyoshin (女体のしんぴ / nyoshin.com) official site scraper."""

import json
import os
import re
from typing import Any, override
from urllib.parse import urlparse

from parsel import Selector

from ..config.enums import Website
from .base import BaseCrawler, Context, CrawlerData, CrawlerException, get_year

RSC_CHUNK_RE = re.compile(r'self\.__next_f\.push\(\[1,\s*"((?:[^"\\]|\\.)*)"\]\)', re.DOTALL)
NYOSHIN_URL_ID_RE = re.compile(r"/(?:moviepages|movie|contents)/n?(\d{3,5})\b", re.IGNORECASE)
NYOSHIN_NUMBER_RE = re.compile(
    r"^(?:nyoshin(?:\.com)?)[-_ ]*n?(?P<pid>\d{3,5})(?:[-_ ].*)?$",
    re.IGNORECASE,
)
NYOSHIN_SEARCH_RE = re.compile(
    r"nyoshin(?:\.com)?[-_ ]*n?(?P<pid>\d{3,5})\b",
    re.IGNORECASE,
)


def extract_nyoshin_id(value: str) -> str | None:
    """从番号、文件名或详情页 URL 中提取纯数字 ID (如 NYOSHIN-n1980 -> '1980')."""
    if not value:
        return None

    str_val = str(value).strip()
    if not str_val:
        return None

    # 1. URL 路径提取
    if "://" in str_val or str_val.startswith("/"):
        path = urlparse(str_val).path
        if m := NYOSHIN_URL_ID_RE.search(path):
            return m.group(1)

    if m := NYOSHIN_URL_ID_RE.search(str_val):
        return m.group(1)

    # 2. 标准番号或文件名含 nyoshin 前缀
    cleaned = os.path.splitext(os.path.basename(str_val))[0].strip("-_. ")
    if m := NYOSHIN_NUMBER_RE.match(cleaned):
        return m.group("pid")

    if m := NYOSHIN_SEARCH_RE.search(str_val):
        return m.group("pid")

    # 3. 路径包含 女体 / 女体のしんぴ / nyoshin 上下文时提取 n1980
    lower_val = str_val.lower()
    if any(k in lower_val for k in ("nyoshin", "女体のしんぴ", "女体")):
        if m := re.search(r"(?i)(?<![a-zA-Z0-9])n(\d{3,5})(?!\d)", str_val):
            return m.group(1)

    return None


def is_nyoshin_number(value: str) -> bool:
    """判断番号或文件路径是否归属女体のしんぴ (nyoshin.com)."""
    return extract_nyoshin_id(value) is not None


def strip_rsc_date(value: str | None) -> str:
    """清洗 Next.js RSC 序列化日期 (如 '$D2020-02-03T00:00:00.000Z' -> '2020-02-03')."""
    if not value:
        return ""
    clean = str(value).removeprefix("$D")
    return clean.split("T")[0] if "T" in clean else clean


def _find_movie_dict_in_obj(obj: Any) -> dict[str, Any] | None:
    """在解析后的 JSON 树中递归查找含 movie 详情字典的节点."""
    if isinstance(obj, dict):
        movie = obj.get("movie")
        if isinstance(movie, dict) and ("id" in movie or "name_utf8" in movie):
            return movie
        for v in obj.values():
            found = _find_movie_dict_in_obj(v)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_movie_dict_in_obj(item)
            if found is not None:
                return found
    return None


def extract_nyoshin_movie_data(html: str) -> dict[str, Any] | None:
    """从 Next.js (React Server Components, RSC) 页面脚本中提取 movie JSON 数据."""
    decoder = json.JSONDecoder()
    for m in RSC_CHUNK_RE.finditer(html):
        try:
            decoded = json.loads('"' + m.group(1) + '"')
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue

        if '"movie":{' not in decoded and '"movie": {' not in decoded:
            continue

        # 优先直接定位 '{"movie":' 并使用 raw_decode 解出该对象
        idx = decoded.find('{"movie":')
        if idx != -1:
            try:
                wrapper, _ = decoder.raw_decode(decoded[idx:])
                if isinstance(wrapper, dict) and isinstance(wrapper.get("movie"), dict):
                    movie = wrapper["movie"]
                    if "id" in movie or "name_utf8" in movie:
                        return movie
            except (json.JSONDecodeError, ValueError):
                pass

        # 回退：解析整行 RSC payload 并递归搜索
        try:
            colon_idx = decoded.index(":")
            data = json.loads(decoded[colon_idx + 1 :])
            found = _find_movie_dict_in_obj(data)
            if found is not None:
                return found
        except (json.JSONDecodeError, IndexError, KeyError, TypeError, ValueError):
            continue

    return None


def _parse_dom_fallback(
    html_text: str, movie_id: str, standard_number: str, detail_url: str, source: str
) -> CrawlerData | None:
    """当 RSC 脚本变化时的 DOM 兜底解析器."""
    sel = Selector(text=html_text)
    title = (
        sel.xpath('//h1[contains(@class, "movie-main-title")]/text()').get("")
        or sel.xpath('//meta[@property="og:title"]/@content').get("")
    ).strip()
    if title and " | " in title:
        title = title.split(" | ")[0].strip()
    if not title:
        return None

    actors = [
        a.strip()
        for a in sel.xpath(
            '//div[contains(@class, "movie-data-list")]//a[contains(@href, "/list/actress/")]/text()'
        ).getall()
        if a.strip()
    ]
    tags = [
        t.strip()
        for t in sel.xpath(
            '//div[contains(@class, "movie-category-tags")]//a[contains(@href, "/list/category/")]/text()'
        ).getall()
        if t.strip()
    ]
    tags = list(dict.fromkeys(tags))

    outline = (
        sel.xpath('string(//p[contains(@class, "detail-comment")])').get("")
        or sel.xpath('//meta[@property="og:description"]/@content').get("")
    ).strip()

    release = ""
    if m_date := re.search(r"公開日\s*[:：]\s*(\d{4}-\d{2}-\d{2})", html_text):
        release = m_date.group(1)

    runtime = ""
    if m_dur := re.search(r"再生時間\s*[:：]\s*(\d{2}):(\d{2}):(\d{2})", html_text):
        h, m, _s = int(m_dur.group(1)), int(m_dur.group(2)), int(m_dur.group(3))
        total_min = h * 60 + m
        runtime = str(max(1, total_min))

    cover_url = (
        sel.xpath('//meta[@property="og:image"]/@content').get("")
        or f"https://www.nyoshin.com/contents/{movie_id}/thum2.jpg"
    ).strip()
    trailer = (
        sel.xpath('//meta[@property="og:video"]/@content').get("")
        or f"https://smovie.nyoshin.com/contents/{movie_id}/sample.mp4"
    ).strip()
    extrafanart = [f"https://www.nyoshin.com/contents/{movie_id}/{i}.jpg" for i in range(1, 11)]

    return CrawlerData(
        number=standard_number,
        title=title,
        originaltitle=title,
        actors=actors,
        all_actors=actors,
        outline=outline,
        originalplot=outline,
        tags=tags,
        release=release,
        year=get_year(release),
        runtime=runtime,
        studio="女体のしんぴ",
        publisher="女体のしんぴ",
        series="女体のしんぴ",
        thumb=cover_url,
        poster=cover_url,
        extrafanart=extrafanart,
        trailer=trailer,
        image_download=False,
        mosaic="无码",
        external_id=detail_url,
        source=source,
    )


class NyoshinCrawler(BaseCrawler):
    """女体のしんぴ (nyoshin.com) 无码官网刮削器."""

    description = "女体のしんぴ（nyoshin.com 无码官网）"
    probe_number = "NYOSHIN-n1980"

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.NYOSHIN

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://www.nyoshin.com"

    @override
    async def _run(self, ctx: Context):
        appoint_url = ctx.input.appoint_url
        number = ctx.input.number
        file_path_str = str(ctx.input.file_path or "")

        movie_id = extract_nyoshin_id(appoint_url) or extract_nyoshin_id(number) or extract_nyoshin_id(file_path_str)
        if not movie_id:
            raise CrawlerException(f"番号中未识别到女体のしんぴ(nyoshin) ID: {number}")

        standard_number = f"NYOSHIN-n{movie_id}"
        detail_url = appoint_url or f"{self.base_url}/moviepages/n{movie_id}"
        ctx.debug_info.detail_urls = [detail_url]

        # 关键：www.nyoshin.com 反向代理根据 Accept: text/html 将请求路由至新版 Next.js 服务；
        # 若缺省 Accept: */* 会落入旧版 EUC-JP 服务并返回 404。
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        cookies = {
            "over18_confirmed": "1",
        }

        html_content, error = await self.async_client.get_text(
            detail_url,
            headers=headers,
            cookies=cookies,
        )
        if html_content is None:
            raise CrawlerException(f"女体のしんぴ网络请求错误: {error}")

        movie = extract_nyoshin_movie_data(html_content)
        if not movie:
            fallback_data = _parse_dom_fallback(
                html_content,
                movie_id=movie_id,
                standard_number=standard_number,
                detail_url=detail_url,
                source=self.site().value,
            )
            if fallback_data is not None:
                return await self.post_process(ctx, fallback_data.to_result())
            raise CrawlerException(f"获取女体のしんぴ详情页数据失败: {detail_url}")

        title_ja = (movie.get("name_utf8") or "").strip()
        title_en = (movie.get("name_en") or "").strip()
        title = title_ja or title_en or standard_number

        act_ja = (movie.get("act_utf8") or "").strip()
        act_en = (movie.get("act_en") or "").strip()
        actors = (
            [a.strip() for a in re.split(r"[,、/／]", act_ja) if a.strip()]
            if act_ja
            else ([a.strip() for a in re.split(r"[,、/／]", act_en) if a.strip()] if act_en else [])
        )

        release = strip_rsc_date(movie.get("ecp_start_date"))
        year = get_year(release)

        detail_obj = movie.get("detail") if isinstance(movie.get("detail"), dict) else {}
        duration_sec = detail_obj.get("duration") or 0
        runtime = str(max(1, int(duration_sec) // 60)) if duration_sec else ""

        memo_ja = (detail_obj.get("memo_utf8") or "").strip()
        memo_en = (detail_obj.get("memo_en") or "").strip()
        outline = memo_ja or memo_en

        tags: list[str] = []
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

        resolved_id = str(movie.get("id") or movie_id).strip()
        cover_url = f"https://www.nyoshin.com/contents/{resolved_id}/thum2.jpg"
        gallery_files = movie.get("galleryFilenames")
        if isinstance(gallery_files, list) and gallery_files:
            extrafanart = [
                f"https://www.nyoshin.com/contents/{resolved_id}/{fname}"
                for fname in gallery_files
                if isinstance(fname, str) and fname.strip()
            ]
        else:
            extrafanart = [f"https://www.nyoshin.com/contents/{resolved_id}/{i}.jpg" for i in range(1, 11)]
        trailer = f"https://smovie.nyoshin.com/contents/{resolved_id}/sample.mp4"

        data = CrawlerData(
            number=standard_number,
            title=title,
            originaltitle=title,
            actors=actors,
            all_actors=actors,
            outline=outline,
            originalplot=outline,
            tags=tags,
            release=release,
            year=year,
            runtime=runtime,
            studio="女体のしんぴ",
            publisher="女体のしんぴ",
            series="女体のしんぴ",
            thumb=cover_url,
            poster=cover_url,
            extrafanart=extrafanart,
            trailer=trailer,
            image_download=False,
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
