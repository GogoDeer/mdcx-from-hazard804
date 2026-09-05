"""JavStash GraphQL scraper — StashBox implementation."""

import re
from typing import TYPE_CHECKING, Any, override

import oshash

from ..config.manager import manager
from ..config.models import Website
from ..utils.javstash_utils import STASH_HEADERS
from mdcx.models.types import CrawlerResult
from .base import BaseCrawler, Context, CralwerException, CrawlerData

if TYPE_CHECKING:
    from mdcx.web_async import AsyncWebClient


class StashGraphQLCrawler(BaseCrawler):
    """Stash-box GraphQL metadata scraper (javstash.org)."""

    def __init__(self, client: "AsyncWebClient", base_url: str = "", browser=None):
        super().__init__(client, base_url, browser)

    async def _post_graphql(self, ctx: Context, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        api_key = manager.config.javstash_api_key
        if not api_key:
            raise CralwerException("请在设置中配置 StashAPI 令牌 (javstash_api_key)")

        headers = {**STASH_HEADERS, "ApiKey": api_key, "Accept": "application/json"}
        url = f"{self.base_url.rstrip('/')}/graphql"
        ctx.debug(f"GraphQL 请求 URL: {url}")

        data, error = await self.async_client.post_json(url, json_data={"query": query, "variables": variables}, headers=headers)

        if error:
            ctx.debug(f"GraphQL 请求异常: {error}")
            raise CralwerException(f"GraphQL 请求失败: {error}")

        if not data or "data" not in data:
            errors = data.get("errors") if data else None
            error_msg = errors[0].get("message") if errors else "未知错误"
            ctx.debug(f"GraphQL 返回错误: {error_msg}")
            raise CralwerException(f"GraphQL 返回错误: {error_msg}")

        return data["data"]

    @classmethod
    @override
    def site(cls) -> Website:
        return Website.JAVSTASH

    @classmethod
    @override
    def base_url_(cls) -> str:
        return "https://javstash.org"

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

    FIND_BY_HASH_QUERY = """
    query FindScenesByHash($oshash: String, $checksum: String) {
      findScenesBySceneFingerprints(fingerprints: [
        { algorithm: OSHASH, hash: $oshash },
        { algorithm: MD5, hash: $checksum }
      ]) {
        ...SceneFragment
      }
    }
    """ + SCENE_FRAGMENT

    FIND_BY_NUMBER_QUERY = """
    query FindScenes($q: String) {
      findScenes(scene_filter: { text: $q }) {
        scenes {
          ...SceneFragment
        }
      }
    }
    """ + SCENE_FRAGMENT

    FIND_BY_ID_QUERY = """
    query FindScene($id: ID!) {
      findScene(id: $id) {
        ...SceneFragment
      }
    }
    """ + SCENE_FRAGMENT

    @override
    async def _run(self, ctx: Context) -> CrawlerResult:
        scene = None

        # 1. Direct ID lookup via appoint_url
        if ctx.input.appoint_url:
            match = re.search(r"/scenes/([a-f0-9-]+)", ctx.input.appoint_url, re.I)
            if match:
                scene_id = match.group(1)
                ctx.debug(f"通过 URL 解析到 ID: {scene_id}")
                data = await self._post_graphql(ctx, self.FIND_BY_ID_QUERY, {"id": scene_id})
                scene = data.get("findScene")
                if scene:
                    ctx.debug(f"通过 ID 查找到场景: {scene.get('title')}")

        # 2. Hash lookup
        if not scene and ctx.input.file_path:
            try:
                oshash_value = oshash.oshash(str(ctx.input.file_path))
                ctx.debug(f"计算 oshash: {oshash_value}")
                data = await self._post_graphql(
                    ctx, self.FIND_BY_HASH_QUERY, {"oshash": oshash_value, "checksum": None}
                )
                scenes = data.get("findScenesBySceneFingerprints", [])
                if scenes:
                    scene = scenes[0]
            except Exception as e:
                ctx.debug(f"⚠️ oshash 计算失败，跳过哈希搜索: {e}")

        # 3. Number fallback
        if not scene and ctx.input.number:
            ctx.debug(f"尝试按番号搜索: {ctx.input.number}")
            data = await self._post_graphql(ctx, self.FIND_BY_NUMBER_QUERY, {"q": ctx.input.number})
            scenes = data.get("findScenes", {}).get("scenes", [])
            if scenes:
                scene = scenes[0]

        if not scene:
            raise CralwerException("未找到匹配场景")

        data = self._map_scene(scene, ctx)
        return await self.post_process(ctx, data.to_result())

    def _map_scene(self, scene: dict[str, Any], ctx: Context) -> CrawlerData:
        release = scene.get("date", "")
        studio = scene.get("studio", {}).get("name", "") if scene.get("studio") else ""

        # Duration: Stash-box returns seconds as a number
        runtime = ""
        try:
            if d := scene.get("duration"):
                runtime = str(int(float(d) / 60))
        except (ValueError, TypeError):
            pass

        # Performers: split by gender
        actors: list[str] = []
        all_actors: list[str] = []
        for p_app in scene.get("performers", []):
            p = p_app.get("performer") or {}
            name = p.get("name", "")
            if not name:
                continue
            all_actors.append(name)
            if p.get("gender") != "MALE":
                actors.append(name)

        title = scene.get("title", "")
        details = scene.get("details", "")
        images = scene.get("images", [])
        screenshot = images[0].get("url", "") if images else ""

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
            number=scene.get("code") or ctx.input.number,
            actors=actors,
            all_actors=all_actors,
            directors=[scene.get("director")] if scene.get("director") else [],
            # Fields not provided by Stash-box: set to explicit defaults so the
            # NOT_SUPPORT sentinel never leaks into downstream string operations.
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

    # The following abstract methods are required by GenericBaseCrawler
    # but since _run is overridden, they will never be called.

    @override
    async def _generate_search_url(self, ctx: Context):
        raise NotImplementedError

    @override
    async def _parse_search_page(self, ctx: Context, html, search_url: str):
        raise NotImplementedError

    @override
    async def _parse_detail_page(self, ctx: Context, html, detail_url: str):
        raise NotImplementedError
