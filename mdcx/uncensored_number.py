#!/usr/bin/env python3
import os
import re

# [Fix] 支持加勒比、一本道等日期番号厂牌前缀
UNCENSORED_PREFIXES = (
    "1pondo",
    "1pon",
    "10musume",
    "10mu",
    "caribbeancom",
    "caribbeancompr",
    "carib",
    "cappv",
    "caribpr",
    "pacopacomama",
    "pacoma",
    "paco",
)

_PREFIX_REGEX_PART = "|".join(UNCENSORED_PREFIXES)

# [Fix] 支持 C0930 / H4610 / H0930 无码厂牌前缀
CAT_PREFIXES = (
    "c0930",
    "h4610",
    "h0930",
)

_CAT_PREFIX_REGEX_PART = "|".join(CAT_PREFIXES)

# 1. 厂牌前缀格式：caribpr-072817_001, CAPPV_072817_001
PREFIX_PATTERN = re.compile(
    rf"^(?P<prefix>{_PREFIX_REGEX_PART})[-_ ]*(?P<head>\d{{6}})(?P<sep>[-_])(?P<tail>\d{{2,4}})(?:[-_.]|$)",
    re.IGNORECASE,
)

# 2. 厂牌后缀格式：072817_001-caribpr, 072817_001_cappv, 072817_001-caribpr-1080p
SUFFIX_PATTERN = re.compile(
    rf"^(?P<head>\d{{6}})(?P<sep>[-_])(?P<tail>\d{{2,4}})[-_ ]+(?P<suffix>{_PREFIX_REGEX_PART})(?:[-_.]|$)",
    re.IGNORECASE,
)

# 3. 纯无码数字格式：072817_001, 072817-001
PURE_DIGIT_PATTERN = re.compile(
    r"^(?P<head>\d{6})(?P<sep>[-_])(?P<tail>\d{2,4})$",
    re.IGNORECASE,
)

# 4. 父目录中的厂牌+番号格式（如 CAPPV-072817_001-FHD, [CAPPV] 072817_001）
PARENT_DIR_PATTERN = re.compile(
    rf"\[?(?P<prefix>{_PREFIX_REGEX_PART})\]?[-_ ]*(?P<head>\d{{6}})(?P<sep>[-_])(?P<tail>\d{{2,4}})",
    re.IGNORECASE,
)

# 5. CAT 厂牌前缀格式：C0930-ki170701, H4610_ki170701, H0930-ori1665
CAT_PREFIX_PATTERN = re.compile(
    rf"^(?P<prefix>{_CAT_PREFIX_REGEX_PART})[-_ ]*(?P<id>[a-z]+\d+)(?:[-_.]|$)",
    re.IGNORECASE,
)

# 6. CAT 厂牌后缀格式：ki170701-c0930, ori1665-h0930
CAT_SUFFIX_PATTERN = re.compile(
    rf"^(?P<id>[a-z]+\d+)[-_ ]+(?P<suffix>{_CAT_PREFIX_REGEX_PART})(?:[-_.]|$)",
    re.IGNORECASE,
)

# 7. CAT 父目录格式：[C0930] ki170701, H4610-ki170701
CAT_PARENT_DIR_PATTERN = re.compile(
    rf"\[?(?P<prefix>{_CAT_PREFIX_REGEX_PART})\]?[-_ ]*(?P<id>[a-z]+\d+)",
    re.IGNORECASE,
)


def parse_uncensored_number(filepath: str = "", filename: str = "") -> str | None:
    """模块化解析无码番号（保留或智能推导厂牌前缀，避免与上游合并冲突）。

    优先级：
    1. 文件名自身携带的前缀 (如 caribpr-072817_001, C0930-ki170701)
    2. 文件名自身携带的后缀 (如 072817_001-caribpr-1080p, ki170701-c0930)
    3. 父目录推导 (如父目录为 CAPPV-072817_001-FHD, C0930-ki170701)
    4. 纯数字无码番号 (如 072817_001, 072817-001)
    """
    cleaned_name = (filename or "").strip("-_. ")
    if not cleaned_name and filepath:
        cleaned_name = os.path.splitext(os.path.basename(filepath))[0].strip("-_. ")

    if not cleaned_name:
        return None

    # 1. 前缀匹配
    if match := PREFIX_PATTERN.match(cleaned_name):
        prefix = match.group("prefix").upper()
        head = match.group("head")
        sep = match.group("sep")
        tail = match.group("tail")
        return f"{prefix}-{head}{sep}{tail}"

    if match := CAT_PREFIX_PATTERN.match(cleaned_name):
        prefix = match.group("prefix").upper()
        cat_id = match.group("id").lower()
        return f"{prefix}-{cat_id}"

    # 2. 后缀匹配
    if match := SUFFIX_PATTERN.match(cleaned_name):
        suffix = match.group("suffix").upper()
        head = match.group("head")
        sep = match.group("sep")
        tail = match.group("tail")
        return f"{suffix}-{head}{sep}{tail}"

    if match := CAT_SUFFIX_PATTERN.match(cleaned_name):
        suffix = match.group("suffix").upper()
        cat_id = match.group("id").lower()
        return f"{suffix}-{cat_id}"

    # 3. 父目录辅助推导
    if filepath:
        parent_dir = os.path.basename(os.path.dirname(filepath)).strip()
        if parent_match := PARENT_DIR_PATTERN.search(parent_dir):
            p_prefix = parent_match.group("prefix").upper()
            p_head = parent_match.group("head")
            p_sep = parent_match.group("sep")
            p_tail = parent_match.group("tail")

            # 校验文件名是否匹配该 head 和 tail
            if cleaned_name.startswith(f"{p_head}{p_sep}{p_tail}") or cleaned_name == f"{p_head}{p_sep}{p_tail}":
                return f"{p_prefix}-{p_head}{p_sep}{p_tail}"

        if cat_parent_match := CAT_PARENT_DIR_PATTERN.search(parent_dir):
            p_prefix = cat_parent_match.group("prefix").upper()
            p_id = cat_parent_match.group("id").lower()
            if cleaned_name.lower().startswith(p_id) or cleaned_name.lower() == p_id:
                return f"{p_prefix}-{p_id}"

    # 4. 纯数字格式
    if match := PURE_DIGIT_PATTERN.fullmatch(cleaned_name):
        head = match.group("head")
        sep = match.group("sep")
        tail = match.group("tail")
        return f"{head}{sep}{tail}"

    return None
