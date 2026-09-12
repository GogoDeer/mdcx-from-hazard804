"""Base crawler for Stash-Box GraphQL servers (JavStash, StashDB, etc.).

Encapsulates:
- GraphQL schema queries (SceneFragment, findScenesBySceneFingerprints, findScene by ID)
- Fingerprint querying (pHash + OSHASH) with caching in _PHASH_SCENE_CACHE
- Mapping Stash-box Scene dictionary to MDCx CrawlerData / CrawlerResult
- Lifecycle execution template
"""

import re
from typing import TYPE_CHECKING, Any, override

import oshash

from mdcx.models.model_types import CrawlerResult

from ..models.log_buffer import LogBuffer
from ..utils.javstash_utils import STASH_HEADERS
from ..utils.phash import compute_video_phash, get_cached_scene, set_cached_scene
from .base import BaseCrawler, Context, CrawlerData, CrawlerException

if TYPE_CHECKING:
    from mdcx.web_async import AsyncWebClient


class BaseStashBoxCrawler(BaseCrawler):
    """Abstract base crawler for Stash-Box GraphQL instances."""

    SCENE_FRAGMENT = """
    fragment SceneFragment on Scene {
      id
      title
      code
      details
      director
      date
      duration
      urls {
        url
      }
      images {
        url
      }
      studio {
        name
      }
      tags {
        name
      }
      performers {
        as
        performer {
          name
          gender
          images {
            url
          }
        }
      }
    }
    """

    FIND_BY_HASH_QUERY = (
        """
    query FindScenesByHash($fingerprints: [[FingerprintQueryInput!]!]!) {
      findScenesBySceneFingerprints(fingerprints: $fingerprints) {
        ...SceneFragment
      }
    }
    """
        + SCENE_FRAGMENT
    )

    FIND_BY_ID_QUERY = (
        """
    query FindScene($id: ID!) {
      findScene(id: $id) {
        ...SceneFragment
      }
    }
    """
        + SCENE_FRAGMENT
    )

    FIND_BY_QUERY_SCENES = (
        """
    query QueryScenes($input: SceneQueryInput!) {
      queryScenes(input: $input) {
        count
        scenes {
          ...SceneFragment
        }
      }
    }
    """
        + SCENE_FRAGMENT
    )

    def __init__(self, client: "AsyncWebClient", base_url: str = "", browser=None):
        super().__init__(client, base_url, browser)

    def get_api_key(self) -> str:
        """Return the API key for this Stash-box instance."""
        raise NotImplementedError

    def get_server_url(self) -> str:
        """Return the configured base URL for this Stash-box instance."""
        raise NotImplementedError

    def get_display_name(self) -> str:
        """Return the user-friendly display name (e.g. JavStash, StashDB)."""
        return self.site().value.capitalize()

    async def _post_graphql(
        self, ctx: Context, query: str, variables: dict[str, Any], operation: str = ""
    ) -> dict[str, Any]:
        api_key = self.get_api_key()
        name = self.get_display_name()
        if not api_key:
            raise CrawlerException(f"请在设置中配置 {name} API 令牌")

        headers = {**STASH_HEADERS, "ApiKey": api_key, "Accept": "application/json"}
        base_url = (self.get_server_url() or self.base_url_()).rstrip("/")
        url = f"{base_url}/graphql"
        op_info = f" [{operation}]" if operation else ""
        ctx.debug(f"{name} GraphQL{op_info} 请求 URL: {url}, 变量: {variables}")

        data, error = await self.async_client.post_json(
            url, json_data={"query": query, "variables": variables}, headers=headers
        )

        if error:
            ctx.debug(f"{name} GraphQL{op_info} 请求异常: {error}")
            raise CrawlerException(f"{name}{op_info} GraphQL 请求失败: {error}")

        if not data or "data" not in data:
            errors = data.get("errors") if data else None
            error_msg = errors[0].get("message") if errors else "未知错误"
            ctx.debug(f"{name} GraphQL{op_info} 返回错误: {error_msg}")
            raise CrawlerException(f"{name}{op_info} GraphQL 返回错误: {error_msg}")

        return data["data"]

    async def _find_by_fingerprints(self, ctx: Context) -> dict[str, Any] | None:
        if not ctx.input.file_path:
            return None

        file_str = str(ctx.input.file_path)
        name = self.get_display_name()

        # Check in-memory cache first
        cached_scene = get_cached_scene(file_str)
        if cached_scene:
            ctx.debug(f"复用预查指纹缓存匹配到场景: {cached_scene.get('title')}")
            LogBuffer.log().write(f"\n 💡 [{name}] 命中指纹缓存: {cached_scene.get('title')}")
            return cached_scene

        fingerprints_query: list[list[dict[str, str]]] = []
        fp_labels: list[str] = []

        # 1. OSHASH (fast header/footer checksum)
        try:
            oshash_value = oshash.oshash(file_str)
            if oshash_value:
                fingerprints_query.append([{"algorithm": "OSHASH", "hash": oshash_value}])
                fp_labels.append(f"OSHASH:{oshash_value}")
                ctx.debug(f"计算 oshash: {oshash_value}")
        except Exception as e:
            ctx.debug(f"⚠️ OSHASH 计算异常: {e}")

        # 2. PHASH (perceptual hash across 25 frames)
        phash_idx = None
        try:
            phash_value = compute_video_phash(file_str)
            if phash_value:
                phash_idx = len(fingerprints_query)
                fingerprints_query.append([{"algorithm": "PHASH", "hash": phash_value}])
                fp_labels.append(f"PHASH:{phash_value}")
                ctx.debug(f"计算 phash: {phash_value}")
        except Exception as e:
            ctx.debug(f"⚠️ PHASH 计算异常: {e}")

        if not fingerprints_query:
            return None

        try:
            ctx.debug(f"正在通过指纹检索 {name}: {', '.join(fp_labels)}")
            data = await self._post_graphql(
                ctx,
                self.FIND_BY_HASH_QUERY,
                {"fingerprints": fingerprints_query},
                operation="指纹检索",
            )
            scenes_nested = data.get("findScenesBySceneFingerprints", [])
            if not isinstance(scenes_nested, list) or not scenes_nested:
                return None

            # Priority 1: Check PHASH match first if present
            if phash_idx is not None and len(scenes_nested) > phash_idx and scenes_nested[phash_idx]:
                scene = scenes_nested[phash_idx][0]
                set_cached_scene(file_str, scene)
                ctx.debug(f"通过 PHASH 匹配到场景: {scene.get('title')}")
                LogBuffer.log().write(f"\n 💡 [{name}] 视频指纹(PHASH)命中场景: {scene.get('title')}")
                return scene

            # Priority 2: Check other fingerprint matches (e.g. OSHASH)
            for idx, scene_matches in enumerate(scenes_nested):
                if scene_matches:
                    scene = scene_matches[0]
                    set_cached_scene(file_str, scene)
                    label = fp_labels[idx] if idx < len(fp_labels) else "HASH"
                    ctx.debug(f"通过 {label} 匹配到场景: {scene.get('title')}")
                    LogBuffer.log().write(f"\n 💡 [{name}] 视频指纹({label})命中场景: {scene.get('title')}")
                    return scene

        except Exception as e:
            ctx.debug(f"⚠️ {name} 指纹检索异常: {e}")

        return None

    def _map_scene(self, scene: dict[str, Any], ctx: Context) -> CrawlerData:
        release = scene.get("date", "")
        studio = scene.get("studio", {}).get("name", "") if scene.get("studio") else ""

        runtime = ""
        try:
            if d := scene.get("duration"):
                runtime = str(int(float(d) / 60))
        except (ValueError, TypeError):
            pass

        actors: list[str] = []
        all_actors: list[str] = []
        for p_app in scene.get("performers", []):
            p = p_app.get("performer") or {}
            p_name = p.get("name", "")
            if not p_name:
                continue
            all_actors.append(p_name)
            if p.get("gender") != "MALE":
                actors.append(p_name)

        title = scene.get("title", "")
        details = scene.get("details", "")
        images = scene.get("images", [])
        screenshot = images[0].get("url", "") if images else ""

        number = scene.get("code") or scene.get("title") or ctx.input.number

        return CrawlerData(
            title=title,
            originaltitle=title,
            outline=details,
            originalplot=details,
            release=release,
            year=release[:4] if release else "",
            studio=studio,
            publisher=studio,
            tags=[t["name"] for t in scene.get("tags", [])],
            thumb=screenshot,
            poster=screenshot,
            runtime=runtime,
            number=number,
            actors=actors,
            all_actors=all_actors,
            directors=[scene.get("director")] if scene.get("director") else [],
            extrafanart=[],
            score="0.0",
            mosaic="",
            series="",
            wanted="",
            trailer="",
            external_id=str(scene.get("id")),
            image_download=False,
            source=self.site().value,
        )

    async def _search_fallback(self, ctx: Context) -> dict[str, Any] | None:
        """Fallback search implementation for subclasses (text / number / studio)."""
        raise NotImplementedError

    @override
    async def _run(self, ctx: Context) -> CrawlerResult:
        scene = None
        name = self.get_display_name()

        # 1. Direct ID lookup via appoint_url
        if ctx.input.appoint_url:
            match = re.search(r"/scenes/([a-f0-9-]+)", ctx.input.appoint_url, re.I)
            if match:
                scene_id = match.group(1)
                ctx.debug(f"通过 URL 解析到 ID: {scene_id}")
                data = await self._post_graphql(ctx, self.FIND_BY_ID_QUERY, {"id": scene_id}, operation="ID直接检索")
                scene = data.get("findScene")
                if scene:
                    ctx.debug(f"通过 ID 查找到场景: {scene.get('title')}")
                    LogBuffer.log().write(f"\n 💡 [{name}] 通过 URL 指定 ID 命中: {scene.get('title')}")

        # 2. Fingerprint lookup (pHash / OSHASH / pre-cached)
        if not scene and ctx.input.file_path:
            scene = await self._find_by_fingerprints(ctx)

        # 3. Fallback search (query / code / text)
        if not scene:
            scene = await self._search_fallback(ctx)

        if not scene:
            raise CrawlerException("未找到匹配场景")

        data = self._map_scene(scene, ctx)
        return await self.post_process(ctx, data.to_result())

    @override
    async def _generate_search_url(self, ctx: Context):
        raise NotImplementedError

    @override
    async def _parse_search_page(self, ctx: Context, html, search_url: str):
        raise NotImplementedError

    @override
    async def _parse_detail_page(self, ctx: Context, html, detail_url: str):
        raise NotImplementedError
