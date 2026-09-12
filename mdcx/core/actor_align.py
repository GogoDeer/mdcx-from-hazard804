"""媒体服务器（Jellyfin/Emby）演员名称优先智能对齐模块。

当演员存在多个艺名/别名（如：折原ほのか / 神無月れな / 神无月丽奈），
优先与用户现存媒体库中的既有演员名称对齐，防止同一演员被分裂为多个条目和文件夹。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

from ..config.manager import manager
from ..models.log_buffer import LogBuffer
from ..tools.emby_shared import _build_jellyfin_headers

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 600.0  # 缓存 10 分钟
FAILURE_BACKOFF_SECONDS = 60.0  # 失败后 60 秒内不再重试网络连接

_lock = threading.Lock()
_server_actors: dict[str, str] | None = None  # name -> id
_normalized_actors: dict[str, str] | None = None  # lowercase_name -> original_cased_name
_movie_counts: dict[str, int] = {}  # name -> movie_count
_aligned_cache: dict[tuple[str, str], str] = {}  # (original_name, mapped_name) -> aligned_name
_last_fetch_time: float = 0.0
_fetch_failed_time: float = 0.0


def clear_media_server_actor_cache() -> None:
    """清理内存缓存（供测试与重新加载配置时调用）。"""
    global _server_actors, _normalized_actors, _last_fetch_time, _fetch_failed_time
    with _lock:
        _server_actors = None
        _normalized_actors = None
        _movie_counts.clear()
        _aligned_cache.clear()
        _last_fetch_time = 0.0
        _fetch_failed_time = 0.0


def _is_alignment_enabled() -> bool:
    """检查是否满足开启媒体服务器演员对齐的条件。"""
    if not getattr(manager.config, "align_media_server_actors", True):
        return False
    if not manager.config.api_key:
        return False
    emby_url = str(manager.config.emby_url or "").strip()
    if not emby_url:
        return False
    return True


def _fetch_server_actors() -> dict[str, str] | None:
    """从媒体服务器（Jellyfin/Emby）拉取全体演员列表索引。"""
    global _server_actors, _normalized_actors, _last_fetch_time, _fetch_failed_time

    now = time.time()
    if now - _fetch_failed_time < FAILURE_BACKOFF_SECONDS:
        return None

    if _server_actors is not None and (now - _last_fetch_time < CACHE_TTL_SECONDS):
        return _server_actors

    base_url = str(manager.config.emby_url).rstrip("/")
    headers = _build_jellyfin_headers()
    is_emby = manager.config.server_type == "emby"

    try:
        # 本地媒体服务器请求绕过系统代理
        with httpx.Client(timeout=8.0, follow_redirects=True, trust_env=False) as client:
            if is_emby:
                # Emby 首选 /emby/Persons，备选 /Persons
                resp = client.get(
                    f"{base_url}/emby/Persons",
                    headers=headers,
                    params={
                        "personTypes": "Actor",
                        "fields": "Name",
                        "userId": manager.config.user_id,
                        "limit": 10000,
                    },
                )
                if resp.status_code != 200:
                    resp = client.get(
                        f"{base_url}/Persons",
                        headers=headers,
                        params={"limit": 10000, "fields": "Name"},
                    )
            else:
                # Jellyfin 首选 /Persons，备选 /Items?includeItemTypes=Person
                resp = client.get(
                    f"{base_url}/Persons",
                    headers=headers,
                    params={"limit": 10000, "fields": "Name"},
                )
                if resp.status_code != 200:
                    resp = client.get(
                        f"{base_url}/Items",
                        headers=headers,
                        params={
                            "includeItemTypes": "Person",
                            "recursive": "true",
                            "fields": "Name",
                            "limit": 10000,
                            "userId": manager.config.user_id,
                        },
                    )

            if resp.status_code != 200:
                logger.debug(
                    "拉取媒体服务器演员列表返回非200状态码: %d %s",
                    resp.status_code,
                    resp.text[:100],
                )
                _fetch_failed_time = time.time()
                return None

            items = resp.json().get("Items", [])
            actors_map: dict[str, str] = {}
            normalized_map: dict[str, str] = {}
            for item in items:
                name = item.get("Name")
                if name:
                    actor_id = item.get("Id", "")
                    actors_map[name] = actor_id
                    normalized_map[name.lower()] = name

            _server_actors = actors_map
            _normalized_actors = normalized_map
            _last_fetch_time = time.time()
            return _server_actors

    except Exception as e:
        logger.debug("连接媒体服务器获取演员索引异常: %s", e)
        _fetch_failed_time = time.time()
        return None


def _get_movie_count_for_actor(actor_name: str) -> int:
    """查询指定演员在媒体服务器中的影片数量。"""
    if actor_name in _movie_counts:
        return _movie_counts[actor_name]

    base_url = str(manager.config.emby_url).rstrip("/")
    headers = _build_jellyfin_headers()
    is_emby = manager.config.server_type == "emby"

    url = f"{base_url}/emby/Items" if is_emby else f"{base_url}/Items"
    params = {
        "Person": actor_name,
        "Recursive": "true",
        "IncludeItemTypes": "Movie",
        "Limit": 0,
    }

    try:
        with httpx.Client(timeout=4.0, follow_redirects=True, trust_env=False) as client:
            resp = client.get(url, headers=headers, params=params)
            if resp.status_code != 200 and is_emby:
                # 备选路径
                resp = client.get(f"{base_url}/Items", headers=headers, params=params)
            if resp.status_code == 200:
                count = int(resp.json().get("TotalRecordCount", 0))
                _movie_counts[actor_name] = count
                return count
    except Exception as e:
        logger.debug("查询演员 %s 影片数失败: %s", actor_name, e)

    _movie_counts[actor_name] = 0
    return 0


def align_actor_with_media_server(
    original_name: str,
    mapped_name: str,
    actor_data: dict[str, Any] | None = None,
) -> str:
    """根据媒体服务器（Jellyfin/Emby）既有数据智能对齐演员名称。

    Args:
        original_name: 刮削网页提取出的原始演员名（如 '折原ほのか'）
        mapped_name: 经 actor_database.xlsx 翻译后的名称（如 '神无月丽奈'）
        actor_data: 从 resources.get_actor_data 查出的该演员完整字典

    Returns:
        对齐后的演员名称
    """
    if not mapped_name:
        return mapped_name

    if not _is_alignment_enabled():
        return mapped_name

    cache_key = (original_name or "", mapped_name)
    with _lock:
        if cache_key in _aligned_cache:
            return _aligned_cache[cache_key]

        server_actors = _fetch_server_actors()
        if not server_actors:
            return mapped_name

        normalized_actors = _normalized_actors or {}

        # 1. 收集该演员的全部马甲与别名
        aliases: list[str] = []

        def _add_alias(alias: Any) -> None:
            if alias and isinstance(alias, str):
                s = alias.strip()
                if s and s not in aliases:
                    aliases.append(s)

        _add_alias(mapped_name)
        _add_alias(original_name)
        if actor_data:
            _add_alias(actor_data.get("zh_cn"))
            _add_alias(actor_data.get("jp"))
            _add_alias(actor_data.get("zh_tw"))
            keywords = actor_data.get("keyword")
            if isinstance(keywords, list):
                for kw in keywords:
                    _add_alias(kw)
            elif isinstance(keywords, str):
                for kw in keywords.split(","):
                    _add_alias(kw)

        # 2. 与媒体库已有演员取交集
        matched_in_server: list[str] = []
        for alias in aliases:
            if alias in server_actors:
                matched_in_server.append(alias)
            elif alias.lower() in normalized_actors:
                matched_in_server.append(normalized_actors[alias.lower()])

        # 去重保留原有顺序
        matched_in_server = list(dict.fromkeys(matched_in_server))

        # 3. 决策决断
        if not matched_in_server:
            # 媒体库中尚无该演员任何马甲，遵循 Excel 默认翻译
            chosen = mapped_name
        elif len(matched_in_server) == 1:
            # 仅命中 1 个马甲（最普遍情况），直接对齐
            chosen = matched_in_server[0]
            if chosen != mapped_name:
                LogBuffer.log().write(f"\n 💡 [演员对齐] 命中媒体库已有演员: '{mapped_name}' -> '{chosen}'")
        else:
            # 同时命中多个马甲，查询影片数量决胜负
            counts = {a: _get_movie_count_for_actor(a) for a in matched_in_server}
            max_count = max(counts.values())
            top_candidates = [a for a, c in counts.items() if c == max_count]

            if mapped_name in top_candidates:
                chosen = mapped_name
            elif original_name in top_candidates:
                chosen = original_name
            else:
                chosen = top_candidates[0]

            if chosen != mapped_name:
                counts_str = ", ".join(f"'{k}': {v}部" for k, v in counts.items())
                LogBuffer.log().write(
                    f"\n 💡 [演员对齐] 媒体库存在多个别名 ({counts_str})，选择作品最多者: '{mapped_name}' -> '{chosen}'"
                )

        _aligned_cache[cache_key] = chosen
        return chosen
