#!/usr/bin/env python3
"""JapanHDV.com official crawler implementation."""

import os
import re
from typing import override
from urllib.parse import quote_plus

from parsel import Selector

from ..config.manager import manager
from ..config.models import Website
from .base import BaseCrawler, Context, CrawlerData

try:
    from .base import CrawlerException
except ImportError:
    from .base import CralwerException as CrawlerException  # type: ignore[no-redef]


def _is_japanhdv_target(ctx: Context) -> bool:
    """Strictly verify if the target belongs to JapanHDV and exclude other brands."""
    if ctx.input.appoint_url:
        return "japanhdv.com" in ctx.input.appoint_url.lower()

    file_path_str = str(ctx.input.file_path or ctx.input.number or "")
    base_name = os.path.splitext(os.path.basename(file_path_str))[0].lower()

    # 1. 严格排除明确属于其他厂牌/前缀的文件
    excluded_brands = (
        "javhub",
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

    # 2. 必须明确包含 JapanHDV 标识
    if "japanhdv" in base_name or "japan-hdv" in base_name or "japan_hdv" in base_name:
        return True
    if re.search(r"\bjapan\s*hdv\b", base_name):
        return True

    return False


def _extract_actress_and_date(ctx: Context) -> tuple[str, str, str]:
    """Extract (actress_name, actress_slug, date_str) from file_path or number."""
    file_path_str = str(ctx.input.file_path or ctx.input.number)
    base_name = os.path.splitext(os.path.basename(file_path_str))[0]

    # Date pattern: 22.07.17 or 2022.07.17 or 22-07-17
    date_match = re.search(r"(\d{2,4})[._\-](\d{2})[._\-](\d{2})", base_name)
    date_str = ""
    if date_match:
        y, m, d = date_match.groups()
        if len(y) == 2:
            y = f"20{y}"
        date_str = f"{y}-{m}-{d}"

    # Actress name: remove JapanHDV prefix and date, then clean up
    cleaned = re.sub(r"(?i)japan\s*hdv", "", base_name)
    cleaned = re.sub(r"\d{2,4}[._\-]\d{2}[._\-]\d{2}", "", cleaned)
    # Remove common technical tags
    cleaned = re.sub(r"(?i)\b(1080p|720p|4k|hd|fhd|sd|x264|x265|h264|h265|aac)\b", "", cleaned)
    # Remove CD part tags like -cd1, -cd26, part1, etc.
    cleaned = re.sub(r"(?i)[._\- ]*(?:cd|part|disc|ch)[._\- ]*\d+[a-z]*", "", cleaned)
    cleaned = re.sub(r"[-_.]+", " ", cleaned).strip()

    # Reject if only digits or too short
    actress_name = ""
    if cleaned and not re.fullmatch(r"[\d\s]+", cleaned) and len(cleaned) >= 2:
        actress_name = cleaned.strip()

    actress_slug = re.sub(r"\s+", "-", actress_name.lower()) if actress_name else ""

    return actress_name, actress_slug, date_str


def _normalize_image_url(url: str, high_res: bool = False) -> str:
    """Ensure https: scheme and convert thumbnail cache size to high res."""
    if not url:
        return ""
    if url.startswith("//"):
        url = f"https:{url}"
    if high_res:
        # Cover: 940x528 / 220x330 -> 1920x1080
        url = url.replace("/cache/940x528/", "/cache/1920x1080/").replace("/cache/220x330/", "/cache/1920x1080/")
    else:
        # Sample photo: 220x330 -> 940x528
        url = url.replace("/cache/220x330/", "/cache/940x528/")
    return url


def _parse_runtime_minutes(duration_text: str) -> str:
    """Parse '58Min 54sec' or '58:54' into total minutes string."""
    if not duration_text:
        return ""
    m_match = re.search(r"(\d+)\s*(?:min|m|分)", duration_text, re.IGNORECASE)
    if m_match:
        return m_match.group(1)
    colon_match = re.search(r"(\d+):(\d+)", duration_text)
    if colon_match:
        return colon_match.group(1)
    digits = re.findall(r"\d+", duration_text)
    return digits[0] if digits else ""


class JapanhdvCrawler(BaseCrawler):
    """JapanHDV (japanhdv.com) official site scraper."""

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.JAPANHDV

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://japanhdv.com"

    async def _resolve_scene_from_theporndb(self, ctx: Context) -> tuple[str, str]:
        """Query ThePornDB API to resolve exact scene title and actress if token is available."""
        if not _is_japanhdv_target(ctx):
            return "", ""

        token = getattr(manager.config, "theporndb_api_token", "") or ""
        token = token.strip()
        if not token:
            return "", ""

        file_name = os.path.basename(str(ctx.input.file_path or ctx.input.number))
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "MDCx",
        }
        # 1. Try ?parse={file_name}
        url = f"https://api.theporndb.net/scenes?parse={quote_plus(file_name)}"
        try:
            data, error = await self.async_client.get_json(url, headers=headers)
            if data and "data" in data and data["data"]:
                item = data["data"][0]
                matched_title = item.get("title", "")
                performers = [p.get("name") for p in item.get("performers", []) if p.get("name")]
                actress = performers[0] if performers else ""
                if matched_title:
                    ctx.debug(f"ThePornDB parse 命中场景标题: {matched_title}")
                    return matched_title, actress
        except Exception as e:
            ctx.debug(f"ThePornDB parse 检索失败: {e}")

        # 2. Fallback to ?q=japanhdv+{date_str}
        _, _, date_str = _extract_actress_and_date(ctx)
        if date_str:
            q_url = f"https://api.theporndb.net/scenes?q={quote_plus(f'japanhdv {date_str}')}"
            try:
                data, error = await self.async_client.get_json(q_url, headers=headers)
                if data and "data" in data and data["data"]:
                    for item in data["data"]:
                        if item.get("date") == date_str:
                            matched_title = item.get("title", "")
                            performers = [p.get("name") for p in item.get("performers", []) if p.get("name")]
                            actress = performers[0] if performers else ""
                            if matched_title:
                                ctx.debug(f"ThePornDB q={date_str} 命中场景标题: {matched_title}")
                                return matched_title, actress
            except Exception as e:
                ctx.debug(f"ThePornDB 按日期检索失败: {e}")

        return "", ""

    @override
    async def _generate_search_url(self, ctx: Context) -> list[str] | str | None:
        if ctx.input.appoint_url:
            return ctx.input.appoint_url

        if not _is_japanhdv_target(ctx):
            ctx.debug("非 JapanHDV 目标影片，跳过 JapanHDV 爬虫")
            return None

        # Check if ThePornDB can provide exact scene title
        tpdb_title, tpdb_actress = await self._resolve_scene_from_theporndb(ctx)
        actress_name, actress_slug, _ = _extract_actress_and_date(ctx)
        if not actress_name and tpdb_actress:
            actress_name = tpdb_actress
            actress_slug = re.sub(r"\s+", "-", actress_name.lower())

        urls = []
        if tpdb_title:
            short_query = " ".join(tpdb_title.split()[:5])
            urls.append(f"{self.base_url}/?s={quote_plus(short_query)}")
        if actress_slug:
            urls.append(f"{self.base_url}/model/{actress_slug}/")
        if actress_name:
            urls.append(f"{self.base_url}/?s={quote_plus(actress_name)}")
        if not urls:
            urls.append(f"{self.base_url}/?s={quote_plus(ctx.input.number)}")
        return urls

    @override
    async def _parse_search_page(self, ctx: Context, html: Selector, search_url: str) -> list[str] | str | None:
        actress_name, _, _ = _extract_actress_and_date(ctx)

        # 优先通过官方专用缩略图链接选择器提取视频地址
        prev_links = html.css("a.video-thumb-prev::attr(href)").getall()
        if prev_links:
            candidates = [link for link in prev_links if link and link.startswith("http")]
            if candidates:
                ctx.debug(f"通过 a.video-thumb-prev 发现视频候选: {len(candidates)} 个")
                if len(candidates) == 1:
                    return candidates
                if actress_name:
                    actress_words = [w.lower() for w in actress_name.split() if len(w) > 1]
                    filtered = [c for c in candidates if any(w in c.lower() for w in actress_words)]
                    if filtered:
                        return filtered
                return candidates

        candidates: list[str] = []
        # Find all video links
        for a in html.css("a"):
            href = a.attrib.get("href", "")
            if not href or not href.startswith("http"):
                continue
            if "japanhdv.com" not in href:
                continue
            # Exclude tax/nav links
            if any(
                k in href
                for k in [
                    "/tag/",
                    "/category/",
                    "/model/",
                    "/series/",
                    "/membership",
                    "/login",
                    "/wp-content",
                    "/feed",
                    "/learn-more",
                    "/japan-porn",
                    "/models",
                    "/network",
                    "/categories",
                ]
            ):
                continue
            if href.rstrip("/") == self.base_url:
                continue

            if href not in candidates:
                candidates.append(href)

        if not candidates:
            ctx.debug(f"搜索页面未发现视频候选: {search_url}")
            return None

        ctx.debug(f"发现候选视频链接: {len(candidates)} 个")

        # If only 1 candidate, return it
        if len(candidates) == 1:
            return candidates

        # If actress name is known, prioritize candidate URLs containing actress words
        actress_words = [w.lower() for w in actress_name.split() if len(w) > 1]
        filtered = []
        for c in candidates:
            c_lower = c.lower()
            if all(w in c_lower for w in actress_words):
                filtered.append(c)

        return filtered or candidates

    @override
    async def _parse_detail_page(self, ctx: Context, html: Selector, detail_url: str) -> CrawlerData | None:
        title = html.css("h1::text, .entry-title::text").get("").strip()
        if not title:
            raise CrawlerException(f"JapanHDV 详情页未解析到标题: {detail_url}")

        # Meta fields from .video-info block
        duration_texts = html.xpath(
            '//div[contains(@class, "video-info")]//p[strong[contains(text(), "Duration")]]/text()'
        ).getall()
        duration_str = "".join(duration_texts).strip()
        runtime = _parse_runtime_minutes(duration_str)

        # Tags / Categories
        tags = html.xpath(
            '//div[contains(@class, "video-info")]//p[strong[contains(text(), "Categories")]]//a/text()'
        ).getall()
        tags = [t.strip() for t in tags if t.strip()]

        # Series
        series_texts = html.xpath(
            '//div[contains(@class, "video-info")]//p[strong[contains(text(), "Series")]]//a/text()'
        ).getall()
        series = "".join(series_texts).strip()
        if not series:
            series_link = html.css("a[href*='/series/']::text").get()
            if series_link and series_link.strip().lower() != "jav series":
                series = series_link.strip()

        # Actress extraction:
        actress_link = html.xpath('//div[contains(@class, "video-info")]//p[strong[contains(text(), "Actress")]]//a')
        english_name = actress_link.xpath("text()").get("").strip()
        model_url = actress_link.xpath("@href").get("").strip()

        japanese_name = ""
        if model_url:
            if model_url.startswith("//"):
                model_url = f"https:{model_url}"
            try:
                # Fetch model page to extract Japanese Kanji name (e.g. "Yui Watanabe 渡辺結衣")
                model_text, error = await self.async_client.get_text(model_url)
                if model_text and not error:
                    m_sel = Selector(model_text)
                    model_h1 = m_sel.css("h1::text").get("").strip()
                    kanji_match = re.findall(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]+", model_h1)
                    if kanji_match:
                        japanese_name = "".join(kanji_match)
            except Exception as e:
                ctx.debug(f"获取女优专页汉字名失败: {e}")

        main_actor = japanese_name or english_name or _extract_actress_and_date(ctx)[0]
        actors = [main_actor] if main_actor else []
        all_actors = [a for a in [japanese_name, english_name] if a] or actors

        # Poster / Thumb
        video_poster = html.css("video::attr(poster)").get("")
        if not video_poster:
            video_poster = html.css(".video-player img::attr(src)").get("")

        poster = _normalize_image_url(video_poster, high_res=False)
        thumb = _normalize_image_url(video_poster, high_res=True)

        # Extrafanart (sample images)
        sample_imgs = html.css("img[src*='sample']::attr(src)").getall()
        extrafanart = [_normalize_image_url(img, high_res=False) for img in sample_imgs if img]

        # Trailer
        trailer_src = html.css("video source::attr(src)").get("")
        trailer = f"https:{trailer_src}" if trailer_src.startswith("//") else trailer_src

        # Release date
        _, _, file_date = _extract_actress_and_date(ctx)
        release = file_date or ""
        year = release[:4] if release else ""

        number = ctx.input.number
        studio = "JapanHDV"

        return CrawlerData(
            number=number,
            title=title,
            originaltitle=title,
            actors=actors,
            all_actors=all_actors,
            outline=f"{title}\nSeries: {series}\nActress: {main_actor}",
            originalplot=title,
            tags=tags,
            release=release,
            year=year,
            runtime=runtime,
            series=series,
            studio=studio,
            publisher=studio,
            thumb=thumb,
            poster=poster,
            extrafanart=extrafanart,
            trailer=trailer,
            image_download=True,
            mosaic="无码",
            external_id=detail_url,
        )
