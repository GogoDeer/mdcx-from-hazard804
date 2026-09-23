"""#22 爬虫 recording 回放框架：录制一次真实 HTTP 响应，之后离线重放整条爬虫链路。

背景（TODO #22）：爬虫回归此前只有两档——FakeClient 手写返回值（与站点真实响应
漂移，站点改版测不出来）或直接打真站（CI 不可靠）。本框架把一次真实抓取持久化为
cassette（JSON 夹具），测试把 `ReplayClient` 注入爬虫的 `client=` 离线重放，
搜索/详情/镜像回退/解析器整条链路一起被回归覆盖。

- `RecordingClient` 包裹真实 `mdcx.web_async.AsyncWebClient`，记录爬虫全部文本/JSON
  交互，`to_cassette()` + `save_cassette()` 覆盖同名归档即完成一次真站重录
  （重录需可用网络环境，产物仍走本框架离线回放）。cassette 按站点归档在
  `tests/crawlers/data/recordings/`。
- `ReplayClient` 方法签名兼容 `AsyncWebClient` 的文本/JSON 接口子集
  （`get_text/get_content/get_json/post_text/post_json`，返回 `(data|None, error)`），
  注入即换轨，生产路径零改动。
- 镜像轮询站点（javdb_api 等）同一 path+query 换 host 命中同一条录像；
  未命中一律硬报错（fail-closed），防止静默漏录让回放"假绿"。
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse

# get_content 的二进制体在 JSON 夹具里的编码标记
_B64_KEY = "__b64__"


@dataclass
class Interaction:
    method: str
    url: str
    body: Any = ""
    status: int = 200
    error: str = ""
    content_type: str = ""

    @property
    def failed(self) -> bool:
        return self.error != ""

    def as_text(self) -> str:
        if isinstance(self.body, str):
            if _B64_KEY in self.body:
                raise ValueError("二进制录像不能按文本回放")
            return self.body
        return json.dumps(self.body, ensure_ascii=False)

    def as_json(self) -> Any:
        if isinstance(self.body, (dict, list)):
            return self.body
        return json.loads(self.body)

    def as_content(self) -> bytes:
        if isinstance(self.body, dict) and _B64_KEY in self.body:
            return base64.b64decode(self.body[_B64_KEY])
        text = self.as_text()
        return text.encode("utf-8")

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": self.method,
            "url": self.url,
            "body": self.body,
            "status": self.status,
            "error": self.error,
            "content_type": self.content_type,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Interaction:
        return cls(
            method=data["method"],
            url=data["url"],
            body=data.get("body", ""),
            status=data.get("status", 200),
            error=data.get("error", ""),
            content_type=data.get("content_type", ""),
        )


@dataclass
class Cassette:
    site: str = ""
    number: str = ""
    recorded_at: str = ""
    interactions: list[Interaction] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "site": self.site,
            "number": self.number,
            "recorded_at": self.recorded_at,
            "interactions": [i.to_dict() for i in self.interactions],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Cassette:
        return cls(
            site=data.get("site", ""),
            number=data.get("number", ""),
            recorded_at=data.get("recorded_at", ""),
            interactions=[Interaction.from_dict(i) for i in data.get("interactions", [])],
        )


def save_cassette(path: Path, cassette: Cassette) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(cassette.to_dict(), ensure_ascii=False, indent=2)
    path.write_text(text, encoding="utf-8")


def load_cassette(path: Path) -> Cassette:
    return Cassette.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _mirror_key(url: str) -> tuple[str, str]:
    """镜像等价键：忽略 host、query 参数排序，同 path+query 换域名视为同一请求。"""
    parsed = urlparse(url)
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    return parsed.path, query


class ReplayClient:
    """按 cassette 重放 HTTP 交互，方法子集签名兼容 AsyncWebClient。"""

    def __init__(self, cassette: Cassette):
        self.cassette = cassette
        self._exact: dict[tuple[str, str], Interaction] = {}
        self._mirror: dict[tuple[str, tuple[str, str]], Interaction] = {}
        for it in cassette.interactions:
            self._exact.setdefault((it.method, it.url), it)
            self._mirror.setdefault((it.method, _mirror_key(it.url)), it)

    def _find(self, method: str, url: str) -> Interaction | None:
        # 精确 URL 优先；再按镜像键（换 host / query 换序）兜底
        found = self._exact.get((method, url))
        if found is not None:
            return found
        return self._mirror.get((method, _mirror_key(url)))

    def _miss(self, method: str, url: str) -> tuple[None, str]:
        return None, f"cassette miss: {method} {url}"

    async def get_text(self, url: str, **kwargs: Any) -> tuple[str | None, str]:
        return self._replay_text("GET", url)

    async def get_content(self, url: str, **kwargs: Any) -> tuple[bytes | None, str]:
        it = self._find("GET", url)
        if it is None:
            return self._miss("GET", url)
        if it.failed:
            return None, it.error
        return it.as_content(), ""

    async def get_json(self, url: str, **kwargs: Any) -> tuple[Any | None, str]:
        it = self._find("GET", url)
        if it is None:
            return self._miss("GET", url)
        if it.failed:
            return None, it.error
        return it.as_json(), ""

    async def post_text(
        self, url: str, *, data: Any = None, json_data: Any = None, **kwargs: Any
    ) -> tuple[str | None, str]:
        return self._replay_text("POST", url)

    async def post_json(
        self, url: str, *, data: Any = None, json_data: Any = None, **kwargs: Any
    ) -> tuple[Any | None, str]:
        it = self._find("POST", url)
        if it is None:
            return self._miss("POST", url)
        if it.failed:
            return None, it.error
        return it.as_json(), ""

    def _replay_text(self, method: str, url: str) -> tuple[str | None, str]:
        it = self._find(method, url)
        if it is None:
            return self._miss(method, url)
        if it.failed:
            return None, it.error
        return it.as_text(), ""


class RecordingClient:
    """包裹真实 AsyncWebClient 记录全部文本/JSON 交互；`--network` 手工重录专用。"""

    def __init__(self, inner: Any):
        self._inner = inner
        self.interactions: list[Interaction] = []

    async def get_text(self, url: str, **kwargs: Any) -> tuple[str | None, str]:
        return self._record("GET", url, await self._inner.get_text(url, **kwargs))

    async def get_content(self, url: str, **kwargs: Any) -> tuple[bytes | None, str]:
        result, error = await self._inner.get_content(url, **kwargs)
        body: Any = ""
        if result is not None:
            body = {_B64_KEY: base64.b64encode(result).decode("ascii")}
        self._append(Interaction(method="GET", url=url, body=body, status=200 if error == "" else 0, error=error))
        return result, error

    async def get_json(self, url: str, **kwargs: Any) -> tuple[Any | None, str]:
        return self._record("GET", url, await self._inner.get_json(url, **kwargs), json_body=True)

    async def post_text(
        self, url: str, *, data: Any = None, json_data: Any = None, **kwargs: Any
    ) -> tuple[str | None, str]:
        return self._record("POST", url, await self._inner.post_text(url, data=data, json_data=json_data, **kwargs))

    async def post_json(
        self, url: str, *, data: Any = None, json_data: Any = None, **kwargs: Any
    ) -> tuple[Any | None, str]:
        return self._record(
            "POST", url, await self._inner.post_json(url, data=data, json_data=json_data, **kwargs), json_body=True
        )

    def to_cassette(self, *, site: str = "", number: str = "") -> Cassette:
        return Cassette(
            site=site,
            number=number,
            recorded_at=datetime.now(UTC).isoformat(timespec="seconds"),
            interactions=list(self.interactions),
        )

    def _record(
        self, method: str, url: str, result: tuple[Any | None, str], *, json_body: bool = False
    ) -> tuple[Any | None, str]:
        body, error = result
        self.interactions.append(
            Interaction(
                method=method,
                url=url,
                body=body if body is not None else "",
                status=200 if error == "" else 0,
                error=error,
                content_type="application/json" if json_body else "",
            )
        )
        return body, error

    def _append(self, it: Interaction) -> None:
        self.interactions.append(it)
