"""JavStash GraphQL scraper — Phase 1 stub.

Full implementation in Phase 2. This skeleton registers the crawler
so it appears in the MDCx engine and can be assigned to website lists.
"""

from typing import TYPE_CHECKING, Any, override

import oshash

from ..config.manager import manager
from ..config.models import Website
from .base import BaseCrawler, Context, CralwerException, CrawlerData

if TYPE_CHECKING:
    from mdcx.web_async import AsyncWebClient


class StashGraphQLCrawler(BaseCrawler):
    """Stash-box GraphQL metadata scraper (javstash.org).

    Phase 1: registered but not functional — `_run` raises NotImplementedError.
    Phase 2: implemented GraphQL transport and extraction logic.
    """

    def __init__(self, client: "AsyncWebClient", base_url: str = "", browser=None):
        super().__init__(client, base_url, browser)
        self.api_key = manager.config.javstash_api_key

    async def _post_graphql(self, ctx: Context, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise CralwerException("请在设置中配置 StashAPI 令牌 (javstash_api_key)")

        headers = {
            "ApiKey": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
        }
        url = f"{self.base_url.rstrip('/')}/graphql"
        ctx.debug(f"GraphQL 请求 URL: {url}")
        json_data = {"query": query, "variables": variables}

        data, error = await self.async_client.post_json(url, json_data=json_data, headers=headers)

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
    async def _run(self, ctx: Context) -> CrawlerData:
        scene = None

        # 1. Direct ID lookup via appoint_url
        if ctx.input.appoint_url:
            import re
            # Stash-box IDs are UUIDs, not just digits
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

        return self._map_scene(scene, ctx)

    def _map_scene(self, scene: dict[str, Any], ctx: Context) -> CrawlerData:
        # Extract fields
        title = scene.get("title", "")
        details = scene.get("details", "")
        release = scene.get("date", "")
        year = release[:4] if release else ""
        # Studio
        studio = scene.get("studio", {}).get("name", "") if scene.get("studio") else ""

        # Tags
        tags = [t["name"] for t in scene.get("tags", [])]

        # Images (Stash-box uses a list of images)
        images = scene.get("images", [])
        screenshot = images[0].get("url", "") if images else ""

        # Duration (top-level field in Stash-box)
        duration = scene.get("duration")

        runtime = ""
        if duration:
            try:
                runtime = str(int(float(duration) / 60))
            except (ValueError, TypeError):
                pass

        # Performers (Stash-box uses PerformerAppearance)
        performers_data = scene.get("performers", [])
        all_actors = []
        actors = []
        actor_photo = {}
        all_actor_photo = {}

        for p_app in performers_data:
            p = p_app.get("performer", {})
            if not p:
                continue
            name = p.get("name", "")
            if not name:
                continue

            all_actors.append(name)
            p_images = p.get("images", [])
            p_photo = p_images[0].get("url", "") if p_images else ""

            if p.get("gender") != "MALE":
                actors.append(name)
                actor_photo[name] = p_photo
            all_actor_photo[name] = p_photo

        # Construct CrawlerData
        data = CrawlerData(
            title=title,
            originaltitle=title,
            outline=details,
            originalplot=details,
            release=release,
            year=year,
            studio=studio,
            publisher=studio,
            tags=tags,
            thumb=screenshot,
            poster=screenshot,
            runtime=runtime,
            number=scene.get("code") or ctx.input.number,
            actors=actors,
            all_actors=all_actors,
            directors=[scene.get("director")] if scene.get("director") else [],
            
            # The following fields are NOT provided by the Stash-box API.
            # We MUST explicitly initialize them to default values (like empty strings or "0.0")
            # to prevent the NotSupport sentinel object from leaking into the core application.
            # If NotSupport leaks into mdcx/core/file_crawler.py, it causes AttributeError
            # when the core attempts string operations (e.g., .replace()) on the metadata.
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

        # Attach dynamic attributes for v1 compat / downstream use
        # (The planner noted these are checked by the v1_compat layer or other consumers)
        data.actor_photo = actor_photo
        data.all_actor_photo = all_actor_photo

        return data

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
