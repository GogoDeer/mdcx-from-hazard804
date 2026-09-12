#!/usr/bin/env python3
"""JavHub (tour.javhub.com) official site scraper."""

import json
import os
import re
from pathlib import Path
from typing import Any, override
from urllib.parse import quote_plus

from parsel import Selector

from ..config.models import Website
from .base import BaseCrawler, Context, CrawlerData

try:
    from .base import CrawlerException
except ImportError:
    from .base import CralwerException as CrawlerException  # type: ignore[no-redef]


def _is_javhub_target(ctx: Context) -> bool:
    """Strictly verify if the target belongs to JavHub and exclude other brands."""
    if ctx.input.appoint_url:
        return "javhub.com" in ctx.input.appoint_url.lower()

    file_path_str = str(ctx.input.file_path or ctx.input.number or "")
    base_name = os.path.splitext(os.path.basename(file_path_str))[0].lower()

    # 1. 排除明确属于其他厂牌的文件
    excluded_brands = (
        "japanhdv",
        "fc2",
        "carib",
        "caribbean",
        "1pondo",
        "10musume",
        "pacopacomama",
        "heyzo",
        "muramura",
        "tokyohot",
        "siro",
        "kin8tengoku",
        "realdivas",
        "heydouga",
    )
    for b in excluded_brands:
        if re.search(rf"\b{b}\b", base_name):
            return False

    # 2. 必须明确包含 JavHub 标识
    if "javhub" in base_name or "jav-hub" in base_name or "jav_hub" in base_name:
        return True
    if re.search(r"\bjav\s*hub\b", base_name):
        return True

    return False


def _get_video_duration_seconds(file_path: Path | str | None) -> float:
    """Read exact video duration in seconds using PyAV or OpenCV."""
    if not file_path:
        return 0.0
    p = Path(file_path)
    if not p.is_file():
        return 0.0
    # Try PyAV (fast header parse, <0.1s)
    try:
        import av

        with av.open(str(file_path)) as container:
            if container.duration is not None:
                return float(container.duration) / av.time_base
    except Exception:
        pass
    # Try OpenCV fallback
    try:
        import cv2

        cap = cv2.VideoCapture(str(file_path))
        fps = cap.get(cv2.CAP_PROP_FPS)
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        cap.release()
        if fps > 0:
            return frames / fps
    except Exception:
        pass
    return 0.0


def _extract_javhub_info(ctx: Context) -> tuple[str, list[str], str, float]:
    """Extract (performer_query, keywords, date_str, target_duration) from file or number."""
    file_path_str = str(ctx.input.file_path or ctx.input.number or "")
    base_name = os.path.splitext(os.path.basename(file_path_str))[0]

    # Date pattern: 22.07.17 or 2022.07.17 or 22-07-17
    date_match = re.search(r"(\d{2,4})[._\-](\d{2})[._\-](\d{2})", base_name)
    date_str = ""
    if date_match:
        y, m, d = date_match.groups()
        if len(y) == 2:
            y = f"20{y}"
        date_str = f"{y}-{m}-{d}"

    # Clean filename
    cleaned = re.sub(r"(?i)jav\s*hub", "", base_name)
    cleaned = re.sub(r"\d{2,4}[._\-]\d{2}[._\-]\d{2}", "", cleaned)
    cleaned = re.sub(r"(?i)\b(1080p|720p|4k|hd|fhd|sd|x264|x265|h264|h265|aac)\b", "", cleaned)
    cleaned = re.sub(r"(?i)[._\- ]*(?:cd|part|disc|ch)[._\- ]*\d+[a-z]*", "", cleaned)
    cleaned = re.sub(r"[-_.]+", " ", cleaned).strip()

    # Performer query candidates
    tokens = cleaned.split()
    keywords = [t.lower() for t in tokens if len(t) > 2]

    # Typically first 2 words are the primary actress (e.g. 'Yura Hitomi', 'Maso Mask')
    performer_query = " ".join(tokens[:2]) if len(tokens) >= 2 else (tokens[0] if tokens else "")

    target_duration = _get_video_duration_seconds(ctx.input.file_path)

    return performer_query, keywords, date_str, target_duration


class JavhubCrawler(BaseCrawler):
    """JavHub (tour.javhub.com) official site scraper."""

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.JAVHUB

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://tour.javhub.com"

    @override
    async def _generate_search_url(self, ctx: Context) -> list[str] | str | None:
        if ctx.input.appoint_url:
            return ctx.input.appoint_url

        if not _is_javhub_target(ctx):
            ctx.debug("非 JavHub 目标影片，跳过 JavHub 爬虫")
            return None

        performer_query, keywords, _, _ = _extract_javhub_info(ctx)
        urls = []
        if performer_query:
            urls.append(f"{self.base_url}/search?q={quote_plus(performer_query)}")
        if len(keywords) >= 3:
            # Also try first 3 words
            alt_query = " ".join(keywords[:3])
            urls.append(f"{self.base_url}/search?q={quote_plus(alt_query)}")

        return urls if urls else None

    @override
    async def _parse_search_page(self, ctx: Context, html: Selector, search_url: str) -> list[str] | str | None:
        next_data_raw = html.xpath('//script[@id="__NEXT_DATA__"]/text()').get()
        if not next_data_raw:
            ctx.debug("JavHub 搜索页未找到 __NEXT_DATA__")
            return None

        try:
            data = json.loads(next_data_raw)
        except Exception as e:
            ctx.debug(f"JavHub 解析 __NEXT_DATA__ JSON 失败: {e}")
            return None

        props = data.get("props", {}).get("pageProps", {})
        contents = props.get("contents", {})
        candidates = (
            contents.get("data", []) if isinstance(contents, dict) else (contents if isinstance(contents, list) else [])
        )
        if not candidates:
            ctx.debug("JavHub 搜索结果列表为空")
            return None

        _, keywords, file_date, target_dur = _extract_javhub_info(ctx)
        ctx.debug(f"JavHub 搜索结果候选数: {len(candidates)}, 目标时长: {target_dur:.1f}s, 关键词: {keywords}")

        # Score candidates
        scored_candidates: list[tuple[int, dict[str, Any]]] = []
        for c in candidates:
            score = 0
            dur = float(c.get("seconds_duration") or 0)
            desc = (c.get("description") or "").lower()
            title = (c.get("title") or "").lower()
            tags = [t.lower() for t in c.get("tags", [])]
            models = [m.lower() for m in c.get("models", [])]

            # 1. Duration match (huge weight)
            if target_dur > 0 and dur > 0:
                diff = abs(dur - target_dur)
                if diff <= 5:
                    score += 100
                elif diff <= 30:
                    score += 50
                elif diff <= 120:
                    score += 20

            # 2. Keyword matching in description/tags/title
            for kw in keywords:
                if kw in desc or kw in title or any(kw in t for t in tags) or any(kw in m for m in models):
                    score += 20

            # 3. Date matching
            pub_date = c.get("publish_date") or ""
            if file_date and file_date in pub_date:
                score += 30

            scored_candidates.append((score, c))

        # Sort descending by score
        scored_candidates.sort(key=lambda x: x[0], reverse=True)

        ordered_urls = []
        for score, c in scored_candidates:
            slug = c.get("slug")
            if slug:
                url = f"{self.base_url}/videos/{slug}"
                ctx.debug(
                    f"  JavHub 候选: {c.get('title')} (得分: {score}, 时长: {c.get('seconds_duration')}s) -> {url}"
                )
                ordered_urls.append(url)

        return ordered_urls if ordered_urls else None

    @override
    async def _parse_detail_page(self, ctx: Context, html: Selector, detail_url: str) -> CrawlerData | None:
        next_data_raw = html.xpath('//script[@id="__NEXT_DATA__"]/text()').get()
        if not next_data_raw:
            ctx.debug("JavHub 详情页未找到 __NEXT_DATA__")
            return None

        try:
            data = json.loads(next_data_raw)
        except Exception as e:
            ctx.debug(f"JavHub 解析详情页 JSON 失败: {e}")
            return None

        props = data.get("props", {}).get("pageProps", {})
        content = props.get("content") or {}
        if not content:
            raise CrawlerException(f"JavHub 详情页未找到 content 数据: {detail_url}")

        title = content.get("title", "").strip()
        description = (content.get("description") or "").strip()
        publish_date = content.get("publish_date") or ""
        release = publish_date.split()[0].replace("/", "-") if publish_date else ""
        year = release[:4] if release else ""

        seconds_duration = content.get("seconds_duration") or 0
        runtime = str(int(seconds_duration / 60)) if seconds_duration else ""

        models = content.get("models", [])
        actors = [m.strip() for m in models if m.strip()]
        all_actors = list(actors)

        tags = content.get("tags", [])
        if not isinstance(tags, list):
            tags = []

        thumb = content.get("thumb") or ""
        poster = thumb

        # Extra gallery fanarts
        extrafanart = []
        sample_thumbs = content.get("thumbs", [])
        if isinstance(sample_thumbs, list):
            extrafanart.extend([img for img in sample_thumbs if isinstance(img, str) and img.startswith("http")])

        previews_full = content.get("previews", {}).get("full", [])
        if isinstance(previews_full, list):
            extrafanart.extend([img for img in previews_full if isinstance(img, str) and img.startswith("http")])

        # Remove duplicate images
        extrafanart = list(dict.fromkeys(extrafanart))

        trailer = content.get("trailer_url") or ""

        number = ctx.input.number or (f"JAVHub.{release.replace('-', '.')}" if release else "JAVHub")

        return CrawlerData(
            number=number,
            title=title,
            originaltitle=title,
            actors=actors,
            all_actors=all_actors,
            outline=description,
            originalplot=description,
            tags=tags,
            release=release,
            year=year,
            runtime=runtime,
            series="JavHub",
            studio="JavHub",
            publisher="JavHub",
            thumb=thumb,
            poster=poster,
            extrafanart=extrafanart,
            trailer=trailer,
            image_download=True,
            mosaic="无码",
            external_id=detail_url,
        )
