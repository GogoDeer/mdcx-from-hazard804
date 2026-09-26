#!/usr/bin/env python3
"""GirlsDelta (girlsdelta.com) official site scraper."""

import json
import os
import re
from typing import Any, override
from urllib.parse import urlparse

from parsel import Selector

from ..config.enums import Website
from .base import BaseCrawler, Context, CrawlerData, get_year

try:
    from .base import CrawlerException
except ImportError:
    from .base import CralwerException as CrawlerException  # type: ignore[no-redef]

GIRLSDELTA_URL_ID_RE = re.compile(r"/product/(\d+)", re.IGNORECASE)
GIRLSDELTA_ID_RE = re.compile(
    r"^(?:girls[-_ ]*delta(?:\.com)?|gdl|gd)[-_ ]*(?P<pid>\d{1,5})$",
    re.IGNORECASE,
)
GIRLSDELTA_BRAND_ID_SEARCH_RE = re.compile(
    r"(?:girls[-_ ]*delta(?:\.com)?|gdl)[-_ ]*(?P<pid>\d{1,5})\b",
    re.IGNORECASE,
)
GIRLSDELTA_TITLE_RE = re.compile(
    r"^(?:girls[-_ ]*delta(?:\.com)?|gdl)[-_ ]+(?P<title>[a-zA-Z]{2,20}(?:[-_ ][a-zA-Z]{2,20})?(?:[-_ ]\d{1,2})?)$",
    re.IGNORECASE,
)
GIRLSDELTA_HASH_RE = re.compile(r"/pics/product/([a-f0-9]{32})/", re.IGNORECASE)


def extract_girlsdelta_id(value: str) -> str | None:
    """Extract numeric product ID from URL, number, or filename (e.g. GIRLSDELTA-1703 -> 1703)."""
    if not value:
        return None

    str_val = str(value).strip()
    if not str_val:
        return None

    if "://" in str_val or str_val.startswith("/"):
        path = urlparse(str_val).path
        if m := GIRLSDELTA_URL_ID_RE.search(path):
            return m.group(1)

    if url_m := GIRLSDELTA_URL_ID_RE.search(str_val):
        return url_m.group(1)

    cleaned = os.path.splitext(os.path.basename(str_val))[0].strip("-_. ")
    if m := GIRLSDELTA_ID_RE.match(cleaned):
        return m.group("pid")

    if m := GIRLSDELTA_BRAND_ID_SEARCH_RE.search(cleaned):
        return m.group("pid")

    return None


def extract_girlsdelta_title_query(value: str) -> str | None:
    """Extract product title query from number or filename (e.g. GIRLSDELTA-NATSUNA-2 -> NATSUNA 2)."""
    if not value:
        return None

    str_val = str(value).strip()
    if not str_val or extract_girlsdelta_id(str_val):
        return None

    cleaned = os.path.splitext(os.path.basename(str_val))[0].strip("-_. ")
    if m := GIRLSDELTA_TITLE_RE.match(cleaned):
        raw_title = re.sub(r"[-_ ]+", " ", m.group("title")).strip()
        if raw_title and not raw_title.isdigit():
            return raw_title.upper()

    return None


def is_girlsdelta_number(value: str) -> bool:
    """Check whether the number or filename belongs to GirlsDelta."""
    return extract_girlsdelta_id(value) is not None or extract_girlsdelta_title_query(value) is not None


def _extract_video_json_ld(html: Selector) -> dict[str, Any]:
    """Parse Schema.org VideoObject JSON-LD embedded in product detail page."""
    for raw in html.xpath('//script[@type="application/ld+json"]/text()').getall():
        try:
            data = json.loads(raw.strip())
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and data.get("@type") == "VideoObject":
            return data
    return {}


class GirlsDeltaCrawler(BaseCrawler):
    """GirlsDelta (girlsdelta.com) official site scraper."""

    description = "GirlsDelta（ガールズデルタ无码官网）"
    probe_number = "GIRLSDELTA-1703"

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.GIRLSDELTA

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://girlsdelta.com"

    async def _resolve_title_to_product_url(self, ctx: Context, title_query: str) -> str | None:
        """Resolve a product title like 'NATSUNA' or 'MAIHA 2' via /model-list -> /model/<id>."""
        tokens = title_query.split()
        if not tokens:
            return None
        given_name = tokens[0]

        model_list_url = f"{self.base_url}/model-list"
        ctx.debug_info.search_urls.append(model_list_url)
        html_text, err = await self.async_client.get_text(model_list_url)
        if not html_text:
            ctx.debug(f"GirlsDelta 获取 model-list 失败: {err}")
            return None

        sel = Selector(text=html_text)
        candidate_model_urls: list[str] = []
        pattern = re.compile(rf"\b{re.escape(given_name)}\b", re.IGNORECASE)
        for item in sel.css("div.searchItem"):
            data_name = item.attrib.get("data-name", "")
            if pattern.search(data_name):
                href = item.css("a[href*='/model/']::attr(href)").get("")
                if href:
                    full_url = href if href.startswith("http") else f"{self.base_url}{href}"
                    if full_url not in candidate_model_urls:
                        candidate_model_urls.append(full_url)

        norm_target = re.sub(r"[-_ ]+", " ", title_query).strip().upper()
        for model_url in candidate_model_urls[:5]:
            m_html, _ = await self.async_client.get_text(model_url)
            if not m_html:
                continue
            m_sel = Selector(text=m_html)
            fallback_url: str | None = None
            for link in m_sel.css(".search-title a[href*='/product/']"):
                p_title = re.sub(r"[-_ ]+", " ", (link.xpath("string()").get("") or "")).strip().upper()
                p_href = link.attrib.get("href", "")
                if not p_href:
                    continue
                p_url = p_href if p_href.startswith("http") else f"{self.base_url}{p_href}"
                if fallback_url is None:
                    fallback_url = p_url
                if p_title == norm_target:
                    return p_url
            if len(tokens) == 1 and fallback_url:
                return fallback_url

        return None

    @override
    async def _generate_search_url(self, ctx: Context) -> list[str] | str | None:
        if ctx.input.appoint_url:
            return ctx.input.appoint_url

        raw_target = str(ctx.input.number or ctx.input.file_path or "")
        pid = extract_girlsdelta_id(raw_target) or extract_girlsdelta_id(str(ctx.input.file_path or ""))
        if pid:
            detail_url = f"{self.base_url}/product/{pid}"
            ctx.debug(f"GirlsDelta 生成直通详情页: {detail_url}")
            return detail_url

        title_query = extract_girlsdelta_title_query(raw_target) or extract_girlsdelta_title_query(
            str(ctx.input.file_path or "")
        )
        if title_query:
            resolved = await self._resolve_title_to_product_url(ctx, title_query)
            if resolved:
                ctx.debug(f"GirlsDelta 按作品名 '{title_query}' 解析到详情页: {resolved}")
                return resolved

        ctx.debug("未识别到有效的 GirlsDelta 编号或作品名，跳过 GirlsDelta 官方爬虫")
        return None

    @override
    async def _parse_search_page(self, ctx: Context, html: Selector, search_url: str) -> list[str] | str | None:
        return search_url

    @override
    async def _parse_detail_page(self, ctx: Context, html: Selector, detail_url: str) -> CrawlerData | None:
        canonical = html.xpath("//link[@rel='canonical']/@href").get("") or detail_url
        pid = (
            extract_girlsdelta_id(canonical)
            or extract_girlsdelta_id(detail_url)
            or extract_girlsdelta_id(str(ctx.input.number or ctx.input.file_path or ""))
        )
        if not pid:
            raise CrawlerException(f"无法从 URL 或番号提取 GirlsDelta 编号: {detail_url}")

        video_ld = _extract_video_json_ld(html)

        # 1. 提取产品标题 (例如 NATSUNA) 与女优名 (例如 梶原夏奈)
        prod_name = (
            html.css("div.prod-name::text").get("")
            or str(video_ld.get("name") or "")
            or html.xpath("//div[@id='head-breadcrumb']//span[@itemprop='name']/text()").getall()[-1:]
            or ""
        )
        if isinstance(prod_name, list):
            prod_name = prod_name[0] if prod_name else ""
        prod_name = str(prod_name).strip()

        actress = (
            html.xpath(
                "//div[@id='product-detail']//h4[contains(., 'モデル名')]/following-sibling::p[1]//a/text()"
            ).get("")
            or html.xpath("//div[@id='head-breadcrumb']//a[contains(@href, '/model/')]//span/text()").get("")
            or ""
        ).strip()

        if not prod_name and not actress:
            raise CrawlerException(f"GirlsDelta 详情页未找到有效作品信息: {detail_url}")

        clean_title = f"{prod_name} {actress}".strip() if (prod_name and actress) else (prod_name or actress)
        actors = [actress] if actress else []

        # 2. 提取 32 位资源 Hash 与图片 / 预告片 URL
        raw_html_text = html.get() or ""
        thumb_from_ld = str(video_ld.get("thumbnailUrl") or "").strip()
        video_poster = html.xpath("//video[@id='sample-video']/@poster").get("").strip()
        hash_match = (
            GIRLSDELTA_HASH_RE.search(thumb_from_ld)
            or GIRLSDELTA_HASH_RE.search(video_poster)
            or GIRLSDELTA_HASH_RE.search(raw_html_text)
        )
        product_hash = hash_match.group(1) if hash_match else ""

        thumb = thumb_from_ld or video_poster
        if not thumb and product_hash:
            thumb = f"{self.base_url}/pics/product/{product_hash}/product_top.webp"

        # 使用 1000x1500 (2:3) 的 sample.webp 作为竖版海报 poster.jpg
        poster = f"{self.base_url}/pics/product/{product_hash}/sample.webp" if product_hash else thumb

        extrafanart: list[str] = []
        if product_hash:
            extrafanart = [
                f"{self.base_url}/pics/product/{product_hash}/sample.webp",
                f"{self.base_url}/pics/product/{product_hash}/product_top.jpg",
            ]

        trailer = (
            str(video_ld.get("contentUrl") or "").strip()
            or html.xpath("//video[@id='sample-video']/@src").get("").strip()
            or (f"{self.base_url}/pics/product/{product_hash}/movie.mp4" if product_hash else "")
        )

        # 3. 发行日期 (uploadDate)
        release = str(video_ld.get("uploadDate") or "").strip()
        if not release:
            reviews = video_ld.get("review")
            if isinstance(reviews, list) and reviews:
                dates = [
                    str(r.get("datePublished", "")).strip()
                    for r in reviews
                    if isinstance(r, dict) and r.get("datePublished")
                ]
                if dates:
                    release = min(dates)

        # 4. 分类与标签 (作品カテゴリ + モデルカテゴリ)
        raw_tags = html.xpath(
            "//div[@id='product-detail']//h4[contains(., 'カテゴリ')]/following-sibling::p[1]//a/text()"
        ).getall()
        tags: list[str] = []
        for t in raw_tags:
            t_clean = t.strip()
            if t_clean and t_clean not in tags:
                tags.append(t_clean)

        # 5. 厂商与系列
        studio = (
            html.xpath("//div[@id='product-detail']//h4[contains(., 'スタジオ')]/following-sibling::p[1]/text()")
            .get("")
            .strip()
            or "GirlsDelta"
        )
        series = (
            html.xpath("//div[@id='product-detail']//h4[contains(., 'シリーズ')]/following-sibling::p[1]/text()")
            .get("")
            .strip()
            or studio
        )

        # 6. 简介 (尺寸数据 + 页面描述)
        size_info = (
            html.xpath("//div[@id='product-detail']//h4[contains(., 'サイズ')]/following-sibling::p[1]/text()")
            .get("")
            .strip()
        )
        content_spec = (
            html.xpath("//div[@id='product-detail']//h4[contains(., '作品内容')]/following-sibling::p[1]/text()")
            .get("")
            .strip()
        )
        meta_desc = (
            str(video_ld.get("description") or "").strip()
            or html.xpath("//meta[@property='og:description']/@content").get("").strip()
            or html.xpath("//meta[@name='description']/@content").get("").strip()
        )
        outline_parts = [p for p in (meta_desc, f"サイズ: {size_info}" if size_info else "", content_spec) if p]
        outline = "\n".join(outline_parts)

        standard_number = f"GIRLSDELTA-{pid}"
        if ctx.input.number and re.match(r"^GD-\d+$", ctx.input.number, re.IGNORECASE):
            standard_number = ctx.input.number.upper()

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
            extrafanart=extrafanart,
            trailer=trailer,
            image_download=True,
            mosaic="无码",
            external_id=canonical,
        )
