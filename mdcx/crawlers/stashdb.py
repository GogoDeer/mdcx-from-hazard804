"""StashDB GraphQL metadata scraper (stashdb.org) for Western scenes."""

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, override

from ..config.manager import manager
from ..config.models import Website
from ..models.log_buffer import LogBuffer
from .base import Context
from .stashbox_base import BaseStashBoxCrawler

if TYPE_CHECKING:
    pass

# Common English stop words to strip when creating search tokens
_STOP_WORDS = {
    "the",
    "a",
    "an",
    "and",
    "or",
    "in",
    "on",
    "at",
    "to",
    "for",
    "of",
    "with",
    "by",
    "its",
    "were",
    "is",
    "it",
    "be",
    "this",
    "that",
    "from",
}


def clean_western_title(raw_text: str) -> str:
    """Clean video filename into search query tokens by stripping dates, codecs, and tags."""
    text = raw_text
    # Remove file extensions if present
    text = re.sub(r"\.(mp4|mkv|avi|wmv|mov|flv|webm)$", "", text, flags=re.I)
    # Remove dates (DD-MM-YYYY, YYYY-MM-DD, YY.MM.DD)
    text = re.sub(r"\b\d{1,2}[-_.]\d{1,2}[-_.]\d{2,4}\b", " ", text)
    text = re.sub(r"\b\d{4}[-_.]\d{1,2}[-_.]\d{1,2}\b", " ", text)
    # Remove common video / quality tags
    tags = (
        r"\b(1080p|720p|2160p|4k|8k|hd|sd|uhd|fhd|hevc|h264|x264|x265|aac|mp3|"
        r"cd\d|part\d|vol\d|act\d|xxx|jav|leak|uncensored|restored)\b"
    )
    text = re.sub(tags, " ", text, flags=re.I)
    # Replace separators with space
    text = re.sub(r"[-_.]+", " ", text)
    # Collapse whitespace
    return " ".join(text.split()).strip()


def extract_significant_keywords(text: str) -> list[str]:
    """Extract significant keywords by removing stopwords and short tokens."""
    tokens = re.findall(r"[a-zA-Z0-9']+", text)
    significant = [t for t in tokens if len(t) > 2 and t.lower() not in _STOP_WORDS]
    return significant


def _norm(s: str) -> str:
    """Normalize string by removing all non-alphanumeric characters and lowercasing."""
    return re.sub(r"[^a-zA-Z0-9]+", "", s).lower()


def score_stashdb_scene(
    scene: dict[str, Any],
    query_text: str,
    file_path: str = "",
) -> int:
    """Score a candidate scene returned by StashDB.

    Evaluates:
    - Title word overlap & normalized title match
    - Performer presence in filename / path
    - Studio presence in filename / path (handling space/hyphen differences)
    - Date / Year presence in filename / path (handling DD-MM-YYYY vs YYYY-MM-DD)
    """
    raw_title = scene.get("title") or ""
    title = raw_title.strip().lower()
    studio = (scene.get("studio") or {}).get("name", "").strip().lower()
    scene_date = (scene.get("date") or "").strip()
    scene_code = (scene.get("code") or "").strip().lower()
    performers = [
        (p.get("performer") or {}).get("name", "").strip().lower()
        for p in scene.get("performers", [])
        if p.get("performer")
    ]

    context = f"{file_path} {query_text}".lower()
    norm_context = _norm(context)
    query_clean = query_text.strip().lower()

    # 0. Exact scene code match (e.g. PT-123, EA-456, SWEET-01)
    if scene_code and (
        scene_code == query_clean
        or f"[{scene_code}]" in norm_context
        or f" {scene_code} " in f" {context} "
        or f"-{scene_code}-" in f"-{context.replace(' ', '-')}-"
    ):
        return 300

    # Match components
    has_studio = bool(studio and (studio in context or _norm(studio) in norm_context))
    has_perf = False
    for perf in performers:
        if not perf:
            continue
        if perf in context or _norm(perf) in norm_context:
            has_perf = True
            break
        # Check individual name tokens (e.g. "kasey" from "kasey cole")
        perf_tokens = [t for t in perf.split() if len(t) >= 4]
        if any(t in context for t in perf_tokens):
            has_perf = True
            break

    has_date = False
    date_patterns = []
    if scene_date:
        parts = scene_date.split("-")
        if len(parts) == 3:
            y, m, d = parts[0], parts[1], parts[2]
            date_patterns = [
                f"{y}-{m}-{d}",
                f"{d}-{m}-{y}",
                f"{y}.{m}.{d}",
                f"{d}.{m}.{y}",
                f"{y}_{m}_{d}",
                f"{d}_{m}_{y}",
            ]
            if any(dp in context for dp in date_patterns):
                has_date = True
        elif scene_date in context:
            has_date = True

    has_exact_title = bool((title and title in context) or (raw_title and _norm(raw_title) in norm_context))

    # STRICT GATE:
    # A Western scene without exact code MUST have studio match, OR (performer AND date), OR exact full title.
    # Discard isolated word overlap (like "interview 316") without studio or performer confirmation!
    if not has_studio and not (has_perf and has_date) and not has_exact_title:
        return 0

    score = 0
    # 1. Studio match
    if has_studio:
        score += 100

    # 2. Performer match
    if has_perf:
        score += 80

    # 3. Date match
    if has_date:
        score += 100
    elif scene_date and len(scene_date) >= 4 and scene_date[:4] in context:
        score += 30

    # 4. Title match
    if has_exact_title:
        score += 150
    else:
        title_words = set(re.findall(r"[a-zA-Z0-9]+", title))
        query_words = set(re.findall(r"[a-zA-Z0-9]+", query_clean))
        if title_words and query_words:
            overlap = title_words.intersection(query_words)
            score += int((len(overlap) / max(len(title_words), 1)) * 50)

    return score


class StashDBCrawler(BaseStashBoxCrawler):
    """StashDB GraphQL metadata scraper (stashdb.org) for Western scenes."""

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.STASHDB

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://stashdb.org"

    @override
    def get_api_key(self) -> str:
        return (
            getattr(manager.config, "stashdb_api_key", "").strip()
            or getattr(manager.config, "javstash_api_key", "").strip()
        )

    @override
    def get_server_url(self) -> str:
        return getattr(manager.config, "stashdb_url", "https://stashdb.org")

    @override
    def get_display_name(self) -> str:
        return "StashDB"

    @override
    async def _search_fallback(self, ctx: Context) -> dict[str, Any] | None:
        """Search StashDB scenes via text query when fingerprint lookup does not hit."""
        if not getattr(ctx.input, "allow_text_search", True):
            ctx.debug("非欧美任务已启用安全防护，禁止 StashDB 执行文本模糊搜索")
            return None

        file_path_str = str(ctx.input.file_path) if ctx.input.file_path else ""
        raw_number = ctx.input.number or ""

        # Candidates to try
        candidates: list[str] = []

        # 1. If file_path is available, extract cleaned title from stem
        if file_path_str:
            stem = Path(file_path_str).stem
            cleaned = clean_western_title(stem)
            if cleaned:
                candidates.append(cleaned)
            # Significant keywords (dropping stopwords)
            sig_words = extract_significant_keywords(stem)
            if sig_words and len(sig_words) >= 2:
                candidates.append(" ".join(sig_words[:5]))

        # 2. Cleaned raw number / input
        if raw_number:
            cleaned_num = clean_western_title(raw_number)
            if cleaned_num and cleaned_num not in candidates:
                candidates.append(cleaned_num)
            sig_num = extract_significant_keywords(raw_number)
            if sig_num and len(sig_num) >= 2:
                sig_num_str = " ".join(sig_num[:5])
                if sig_num_str not in candidates:
                    candidates.append(sig_num_str)

        ctx.debug(f"StashDB 生成文本检索候选词: {candidates}")

        best_scene = None
        best_score = 0

        for cand in candidates:
            ctx.debug(f"尝试按文本检索 StashDB: {cand}")
            try:
                data = await self._post_graphql(
                    ctx,
                    self.FIND_BY_QUERY_SCENES,
                    {"input": {"text": cand}},
                    operation=f"文本检索({cand})",
                )
                scenes = data.get("queryScenes", {}).get("scenes", [])
                for scene in scenes:
                    s = score_stashdb_scene(scene, cand, file_path_str)
                    if s > best_score:
                        best_score = s
                        best_scene = scene

                # If high-confidence match found, stop searching
                if best_score >= 180:
                    break
            except Exception as e:
                ctx.debug(f"⚠️ StashDB 文本检索 [{cand}] 异常: {e}")

        MIN_ACCEPT_SCORE = 180
        if best_scene and best_score >= MIN_ACCEPT_SCORE:
            ctx.debug(f"StashDB 文本检索命中最佳场景 (得分: {best_score}): {best_scene.get('title')}")
            LogBuffer.log().write(f"\n 🟢 [StashDB] 文本检索命中: {best_scene.get('title')} (得分: {best_score})")
            return best_scene

        if best_scene:
            ctx.debug(
                f"StashDB 候选场景得分过低 ({best_score} < {MIN_ACCEPT_SCORE})，放弃采信: {best_scene.get('title')}"
            )

        return None
