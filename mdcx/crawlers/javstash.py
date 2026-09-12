"""JavStash GraphQL scraper — StashBox implementation."""

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, override

import oshash

from ..config.manager import manager
from ..config.models import Website
from ..models.log_buffer import LogBuffer
from .base import Context, CrawlerException
from .stashbox_base import BaseStashBoxCrawler

if TYPE_CHECKING:
    pass


def check_boundary_match(code: str, cand: str) -> bool:
    """检查 candidate 是否作为独立 token 存在于 code 中，防止如 SSIS-123 误匹配 SSIS-1234。"""
    if not cand or not code:
        return False

    code_lower = code.lower()
    cand_lower = cand.lower()
    idx = code_lower.find(cand_lower)
    if idx == -1:
        return False

    # 检查后导字符：必须由非字母数字分隔符（如 -、_）隔开或已到达结尾
    after_idx = idx + len(cand_lower)
    if after_idx < len(code_lower):
        next_char = code_lower[after_idx]
        if next_char.isalnum():
            return False

    # 检查前导字符：必须由非字母数字分隔符隔开或已到达开头
    if idx > 0:
        prev_char = code_lower[idx - 1]
        if prev_char.isalnum():
            return False

    return True


def generate_javstash_candidates(number: str, file_path: str = "") -> list[str]:
    """生成针对 JavStash (Stash-box) 的高精度番号候选列表。

    规则：
    1. 区分 _ 和 - 分隔符，严禁无差别交叉混淆（_ 为一本道/10musume/paco，- 为加勒比）。
    2. 对无码番号自动补全 JavStash 规范 code 后缀（-1pon, -carib, -10mu, -paco）。
    3. 结合文件名/路径中的厂牌特征词进行前置优先。
    """
    candidates: list[str] = []
    seen: set[str] = set()

    def add(c: str):
        c_clean = c.strip()
        if c_clean and c_clean.lower() not in seen:
            seen.add(c_clean.lower())
            candidates.append(c_clean)

    # 原始番号优先加入
    if number:
        add(number)

    # 提取所有上下文文本（番号自身 + 文件主名 + 父目录）
    context_text = number or ""
    if file_path:
        p = Path(file_path)
        context_text += f" {p.stem} {p.parent.name}"

    context_lower = context_text.lower()

    # 检测厂牌线索
    has_1pon = any(k in context_lower for k in ("1pon", "1pondo", "一本道"))
    has_carib = any(k in context_lower for k in ("carib", "cappv", "加勒比"))
    has_10mu = any(k in context_lower for k in ("10mu", "10musume", "天然むすめ"))
    has_paco = any(k in context_lower for k in ("paco", "pacopacomama", "パコパコママ"))

    # 匹配 6位日期+编号 模式 (\d{6}[-_]\d{2,4})
    m = re.search(r"(\d{6})([-_])(\d{2,4})", number or "")
    if not m and file_path:
        m = re.search(r"(\d{6})([-_])(\d{2,4})", Path(file_path).stem)

    if m:
        head, sep, tail = m.group(1), m.group(2), m.group(3)
        num_len = len(tail)

        if sep == "_":
            # 下划线分隔：一本道、天然むすめ、パコパコママ
            if has_carib:
                add(f"{head}-{tail}-carib")
                add(f"{head}-{tail}")

            if num_len == 2:
                # 2位数字尾号：天然むすめ专属
                add(f"{head}_{tail}-10mu")
                add(f"{head}_{tail}")
            else:
                # 3或4位数字尾号：一本道 或 パコパコママ
                if has_paco:
                    add(f"{head}_{tail}-paco")
                    add(f"{head}_{tail}-1pon")
                else:
                    add(f"{head}_{tail}-1pon")
                    add(f"{head}_{tail}-paco")
                add(f"{head}_{tail}")

        elif sep == "-":
            # 连字符分隔：加勒比专属
            if has_1pon:
                add(f"{head}_{tail}-1pon")
                add(f"{head}_{tail}")
            elif has_10mu:
                add(f"{head}_{tail}-10mu")
                add(f"{head}_{tail}")
            elif has_paco:
                add(f"{head}_{tail}-paco")
                add(f"{head}_{tail}")
            else:
                add(f"{head}-{tail}-carib")
    return candidates


def score_scene_match(
    scene: dict[str, Any],
    candidate: str,
    original_number: str = "",
    file_path: str = "",
) -> int:
    """对 JavStash 返回的 scene 进行契合度评分。

    返回分数：> 0 表示合格匹配，越高越好；<= 0 表示不匹配/冲突，坚决丢弃。
    """
    code = (scene.get("code") or "").strip()
    studio = (scene.get("studio") or {}).get("name", "") if scene.get("studio") else ""
    urls = [u.get("url", "") for u in scene.get("urls", []) if isinstance(u, dict)]

    if not code:
        return 0

    score = 0
    code_lower = code.lower()
    cand_lower = candidate.strip().lower()
    orig_lower = (original_number or "").strip().lower()

    if not cand_lower and not orig_lower:
        return 100

    # 检查日期无码的分隔符一致性（这是防止 011123_001 误匹配 011123-001-carib 的核心防线）
    m_target = re.search(r"(\d{6})([-_])(\d{2,4})", orig_lower or cand_lower)
    m_code = re.search(r"(\d{6})([-_])(\d{2,4})", code_lower)

    if m_target and m_code:
        t_head, t_sep, t_tail = m_target.group(1), m_target.group(2), m_target.group(3)
        c_head, c_sep, c_tail = m_code.group(1), m_code.group(2), m_code.group(3)

        if t_head == c_head and t_tail == c_tail:
            if t_sep == c_sep:
                score += 300
            else:
                # 致命冲突：一个是 _ 一个是 -，说明不是同一个厂商的片！
                return -1000
        else:
            # 日期或编号不一致
            return -1000

    # 厂商契合度与排他判定
    if m_target:
        sep = m_target.group(2)
        if sep == "_":
            if any(s in studio for s in ("一本道", "天然むすめ", "パコパコママ", "1Pondo", "10musume", "pacopacomama")):
                score += 200
            elif any(s in studio for s in ("カリビアンコム", "加勒比", "Caribbeancom")):
                return -1000  # 下划线番号绝不是加勒比！
        elif sep == "-":
            if any(s in studio for s in ("カリビアンコム", "加勒比", "Caribbeancom")):
                score += 200
            elif any(
                s in studio for s in ("一本道", "天然むすめ", "パコパコママ", "1Pondo", "10musume", "pacopacomama")
            ):
                return -1000  # 连字符番号绝不是一本道！

    # 1. code 与候选词完全一致
    if code_lower == cand_lower:
        score += 1000
    # 2. code 拥有完全匹配的前缀 (如 code 为 "011123_001-1pon", cand 为 "011123_001")
    elif code_lower.startswith(f"{cand_lower}-") or code_lower.startswith(f"{cand_lower}_"):
        score += 800
    # 3. code 包含候选词且边界独立，或候选词包含 code (如 CAPPV-081817_001 包含 081817_001)
    elif check_boundary_match(code_lower, cand_lower) or check_boundary_match(cand_lower, code_lower):
        score += 500
    elif m_target and m_code and t_head == c_head and t_tail == c_tail and t_sep == c_sep:
        score += 500
    else:
        return 0

    # 上下文或 URL 辅助加分
    context_text = f"{file_path} {original_number}".lower()
    if "1pon" in context_text and any("1pondo" in u for u in urls):
        score += 100
    if "carib" in context_text and any("caribbeancom" in u for u in urls):
        score += 100

    return score


def select_best_scene(
    scenes: list[dict[str, Any]],
    candidate: str,
    original_number: str = "",
    file_path: str = "",
) -> dict[str, Any] | None:
    """从候选场景列表中评估并选择契合度最高的有效场景。若无合格匹配则返回 None。"""
    best_scene = None
    best_score = 0
    for scene in scenes:
        s = score_scene_match(scene, candidate, original_number, file_path)
        if s > best_score:
            best_score = s
            best_scene = scene
    return best_scene


class StashGraphQLCrawler(BaseStashBoxCrawler):
    """Stash-box GraphQL metadata scraper (javstash.org)."""

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.JAVSTASH

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://javstash.org"

    @override
    def get_api_key(self) -> str:
        return manager.config.javstash_api_key

    @override
    def get_server_url(self) -> str:
        return getattr(manager.config, "javstash_url", "https://javstash.org")

    @override
    def get_display_name(self) -> str:
        return "JavStash"

    @override
    async def _post_graphql(
        self, ctx: Context, query: str, variables: dict[str, Any], operation: str = ""
    ) -> dict[str, Any]:
        api_key = self.get_api_key()
        if not api_key:
            raise CrawlerException("请在设置中配置 StashAPI 令牌 (javstash_api_key)")
        return await super()._post_graphql(ctx, query, variables, operation)

    FIND_BY_NUMBER_QUERY = BaseStashBoxCrawler.FIND_BY_QUERY_SCENES

    @override
    async def _find_by_fingerprints(self, ctx: Context) -> dict[str, Any] | None:
        if not ctx.input.file_path:
            return None

        file_str = str(ctx.input.file_path)
        from ..utils.phash import get_cached_scene, set_cached_scene

        cached_scene = get_cached_scene(file_str)
        if cached_scene:
            ctx.debug(f"复用预查缓存匹配到场景: {cached_scene.get('title')}")
            LogBuffer.log().write(f"\n 💡 [JavStash] 命中预查指纹缓存: {cached_scene.get('title')}")
            return cached_scene

        fingerprints_query: list[list[dict[str, str]]] = []
        fp_labels: list[str] = []

        # 2a. OSHASH (fast header/footer checksum)
        try:
            oshash_value = oshash.oshash(file_str)
            if oshash_value:
                fingerprints_query.append([{"algorithm": "OSHASH", "hash": oshash_value}])
                fp_labels.append(f"OSHASH:{oshash_value}")
                ctx.debug(f"计算 oshash: {oshash_value}")
        except Exception as e:
            ctx.debug(f"⚠️ OSHASH 计算异常: {e}")

        # 2b. PHASH (perceptual hash, resilient to re-encoding/remuxing)
        try:
            from ..utils.phash import compute_video_phash

            phash_value = compute_video_phash(file_str)
            if phash_value:
                fingerprints_query.append([{"algorithm": "PHASH", "hash": phash_value}])
                fp_labels.append(f"PHASH:{phash_value}")
                ctx.debug(f"计算 phash: {phash_value}")
        except Exception as e:
            ctx.debug(f"⚠️ PHASH 计算异常: {e}")

        if not fingerprints_query:
            return None

        try:
            ctx.debug(f"正在通过指纹检索 JavStash: {', '.join(fp_labels)}")
            data = await self._post_graphql(
                ctx,
                self.FIND_BY_HASH_QUERY,
                {"fingerprints": fingerprints_query},
                operation="指纹检索",
            )
            scenes_nested = data.get("findScenesBySceneFingerprints", [])
            if scenes_nested and isinstance(scenes_nested, list):
                for idx, scene_matches in enumerate(scenes_nested):
                    if scene_matches:
                        best = select_best_scene(
                            scene_matches,
                            ctx.input.number or "",
                            ctx.input.number or "",
                            file_str,
                        )
                        scene = best or scene_matches[0]
                        set_cached_scene(file_str, scene)
                        label = fp_labels[idx] if idx < len(fp_labels) else "HASH"
                        ctx.debug(f"通过 {label} 匹配到场景: {scene.get('title')}")
                        LogBuffer.log().write(f"\n 💡 [JavStash] 视频指纹({label})命中场景: {scene.get('title')}")
                        return scene
        except Exception as e:
            ctx.debug(f"⚠️ JavStash 指纹检索未命中或异常: {e}")

        return None

    @override
    async def _search_fallback(self, ctx: Context) -> dict[str, Any] | None:
        file_path_str = str(ctx.input.file_path) if ctx.input.file_path else ""
        candidates = generate_javstash_candidates(ctx.input.number, file_path_str)
        ctx.debug(f"JavStash 生成检索候选词: {candidates}")

        for cand in candidates:
            # 1. 优先使用 Stash-box code 字段精确匹配 (EQUALS)
            ctx.debug(f"尝试按番号精确搜索: {cand}")
            data = await self._post_graphql(
                ctx,
                self.FIND_BY_NUMBER_QUERY,
                {"input": {"code": {"value": cand, "modifier": "EQUALS"}}},
                operation=f"番号精确检索({cand})",
            )
            scenes = data.get("queryScenes", {}).get("scenes", [])
            best = select_best_scene(scenes, cand, ctx.input.number, file_path_str)
            if best:
                ctx.debug(f"通过番号精确匹配 [{cand}] 命中场景: {best.get('title')}")
                LogBuffer.log().write(f"\n 🟢 [JavStash] 番号精确匹配 [{cand}] 命中: {best.get('title')}")
                return best

            # 2. 尝试使用 Stash-box code 包含匹配 (INCLUDES)
            ctx.debug(f"尝试按番号包含搜索: {cand}")
            data = await self._post_graphql(
                ctx,
                self.FIND_BY_NUMBER_QUERY,
                {"input": {"code": {"value": cand, "modifier": "INCLUDES"}}},
                operation=f"番号包含检索({cand})",
            )
            scenes = data.get("queryScenes", {}).get("scenes", [])
            best = select_best_scene(scenes, cand, ctx.input.number, file_path_str)
            if best:
                ctx.debug(f"通过番号包含匹配 [{cand}] 命中场景: {best.get('title')}")
                LogBuffer.log().write(f"\n 🟢 [JavStash] 番号包含匹配 [{cand}] 命中: {best.get('title')}")
                return best

            # 3. 回退 Stash-box 全文模糊匹配 (text)
            ctx.debug(f"尝试按文本模糊搜索: {cand}")
            data = await self._post_graphql(
                ctx,
                self.FIND_BY_NUMBER_QUERY,
                {"input": {"text": cand}},
                operation=f"文本模糊检索({cand})",
            )
            scenes = data.get("queryScenes", {}).get("scenes", [])
            best = select_best_scene(scenes, cand, ctx.input.number, file_path_str)
            if best:
                ctx.debug(f"通过文本模糊匹配 [{cand}] 命中场景: {best.get('title')}")
                LogBuffer.log().write(f"\n 🟢 [JavStash] 文本模糊检索 [{cand}] 命中: {best.get('title')}")
                return best

        return None
