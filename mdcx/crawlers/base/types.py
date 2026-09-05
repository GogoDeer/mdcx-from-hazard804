import re
from dataclasses import dataclass, field
from re import Pattern

from mdcx.core.mosaic import normalize_mosaic
from mdcx.models.log_buffer import LogBuffer
from mdcx.models.types import CrawlerDebugInfo, CrawlerInput, CrawlerResult
from mdcx.utils.dataclass import update_valid


class XPath(str):
    """XPath 选择器字符串类型."""
    ...


class CSSSelector(str):
    """CSS 选择器字符串类型."""
    ...


class NotSupport:
    """表示该字段在当前抓取器中不受支持."""
    ...


# 表示字段不支持抓取的常量对象
NOT_SUPPORT = NotSupport()

# 字段值类型定义：可以是泛型 T，或者是 None，或者是 NOT_SUPPORT
type FieldValue[T = str] = T | None | NotSupport
# 字段结果类型别名
type FieldRes[T = str] = FieldValue[T]

# 抓取器支持的选择器类型集合
type SelectorType = XPath | CSSSelector | Pattern | str


def c(selector: str) -> CSSSelector:
    """CSS 选择器便捷构造函数."""
    return CSSSelector(selector)


def x(selector: str) -> XPath:
    """XPath 选择器便捷构造函数."""
    return XPath(selector)


def r(pattern: str) -> Pattern:
    """正则模式便捷构造函数."""
    return re.compile(pattern)


def is_valid[T](v: FieldValue[T]) -> bool:
    """判断字段值是否有效 (非 None 且非 NOT_SUPPORT)."""
    if v is None or v is NOT_SUPPORT:
        return False
    if type(v).__name__ == "NotSupport":
        return False
    return bool(v)


@dataclass
class CrawlerData:
    """
    抓取器抓取到的原始数据模型.
    默认所有字段均为 NOT_SUPPORT.
    """
    title: FieldValue = NOT_SUPPORT
    actors: FieldValue[list[str]] = NOT_SUPPORT
    all_actors: FieldValue[list[str]] = NOT_SUPPORT
    directors: FieldValue[list[str]] = NOT_SUPPORT
    extrafanart: FieldValue[list[str]] = NOT_SUPPORT
    originalplot: FieldValue = NOT_SUPPORT
    originaltitle: FieldValue = NOT_SUPPORT
    outline: FieldValue = NOT_SUPPORT
    poster: FieldValue = NOT_SUPPORT
    publisher: FieldValue = NOT_SUPPORT
    release: FieldValue = NOT_SUPPORT
    runtime: FieldValue = NOT_SUPPORT
    score: FieldValue = NOT_SUPPORT
    series: FieldValue = NOT_SUPPORT
    studio: FieldValue = NOT_SUPPORT
    tags: FieldValue[list[str]] = NOT_SUPPORT
    thumb: FieldValue = NOT_SUPPORT
    trailer: FieldValue = NOT_SUPPORT
    wanted: FieldValue = NOT_SUPPORT
    year: FieldValue = NOT_SUPPORT
    image_download: FieldValue[bool] = NOT_SUPPORT
    number: FieldValue = NOT_SUPPORT
    mosaic: FieldValue = NOT_SUPPORT
    external_id: FieldValue = NOT_SUPPORT
    source: FieldValue = NOT_SUPPORT

    def to_result(self) -> "CrawlerResult":
        """将当前数据转换为最终的抓取结果对象，并过滤无效字段."""
        result = update_valid(CrawlerResult.empty(), self, is_valid)
        result.mosaic = normalize_mosaic(result.mosaic)
        return result


class CralwerException(Exception):
    """抓取器异常基类 (注意: 拼写为 Cralwer 以保持兼容性)."""
    ...


@dataclass
class Context:
    """抓取执行上下文，包含输入信息和调试信息."""
    input: CrawlerInput  # crawler 的原始输入
    debug_info: "CrawlerDebugInfo" = field(default_factory=CrawlerDebugInfo)

    def debug(self, message: str):
        """记录调试信息."""
        self.debug_info.logs.append(message)
        # 将调试信息写入日志缓冲区
        LogBuffer.log().write(f"\n 🕷 [DEBUG] {message}")
