"""NFO file updater for unifying actor names, preserving former stage names in <role>, and appending <tag>."""

from __future__ import annotations

import html
import logging
import os
import re
from pathlib import Path

from .alias_resolver import normalize_name
from .scanner import AUXILIARY_DIRS, IGNORED_NAMES

logger = logging.getLogger(__name__)

_ACTOR_BLOCK_RE = re.compile(r"([ \t]*<actor\b[^>]*>.*?</actor>[ \t]*\r?\n?)", re.DOTALL | re.IGNORECASE)
_SET_BLOCK_RE = re.compile(r"([ \t]*<set\b[^>]*>.*?</set>[ \t]*\r?\n?)", re.DOTALL | re.IGNORECASE)
_NAME_TAG_RE = re.compile(r"([ \t]*<name>)(.*?)(</name>)", re.DOTALL | re.IGNORECASE)
_ROLE_TAG_RE = re.compile(r"([ \t]*<role>)(.*?)(</role>)", re.DOTALL | re.IGNORECASE)
_TAG_LINE_RE = re.compile(r"^([ \t]*)<tag>(.*?)</tag>([ \t]*\r?\n?)", re.MULTILINE | re.IGNORECASE)


def _escape_xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _extract_tag_text(block: str, tag_re: re.Pattern) -> str | None:
    m = tag_re.search(block)
    if not m:
        return None
    return html.unescape(m.group(2)).strip()


def _set_or_insert_role(actor_block: str, role_value: str) -> str:
    """Insert or update <role> inside an <actor> block if no custom role is present."""
    escaped_role = _escape_xml(role_value)
    role_match = _ROLE_TAG_RE.search(actor_block)
    if role_match:
        existing_role = html.unescape(role_match.group(2)).strip()
        if not existing_role or normalize_name(existing_role) == normalize_name(role_value):
            return actor_block[: role_match.start(2)] + escaped_role + actor_block[role_match.end(2) :]
        return actor_block

    # Insert <role> right after <name>...</name>
    name_match = _NAME_TAG_RE.search(actor_block)
    if not name_match:
        return actor_block

    indent_match = re.match(r"^([ \t]*)", name_match.group(1))
    indent = indent_match.group(1) if indent_match else "    "
    newline = "\r\n" if "\r\n" in actor_block else "\n"
    insert_pos = name_match.end(0)
    return actor_block[:insert_pos] + f"{newline}{indent}<role>{escaped_role}</role>" + actor_block[insert_pos:]


def update_nfo_file(
    nfo_path: Path,
    new_actor: str,
    old_names: set[str] | list[str],
) -> bool:
    """Update actor name in a single .nfo file.

    Rules:
    1. <actor><name>: if it matches any name in old_names, replace <name> with new_actor.
       If the original name differs from new_actor and <actor> has no custom <role>,
       preserve the old stage name in <role>old_name</role>.
       Deduplicate if multiple <actor> blocks end up with new_actor.
    2. <set><name>: if it matches any name in old_names, replace <name> with new_actor (and deduplicate).
    3. <tag>: if any <tag> matches or contains an old actor name, keep it and append <tag>new_actor</tag>
       if <tag>new_actor</tag> does not already exist.

    Returns True if the file was modified on disk, False otherwise.
    """
    target_actor = new_actor.strip()
    target_norm = normalize_name(target_actor)
    if not target_norm or not nfo_path.exists():
        return False

    raw_old_list = [str(x).strip() for x in old_names if x and str(x).strip()]
    old_norms = {normalize_name(x) for x in raw_old_list if normalize_name(x)}
    old_norms.add(target_norm)
    non_target_old_norms = old_norms - {target_norm}
    non_target_old_raws = [x for x in raw_old_list if normalize_name(x) in non_target_old_norms and len(x) >= 2]

    try:
        raw_bytes = nfo_path.read_bytes()
    except OSError as e:
        logger.warning("Failed to read NFO %s: %s", nfo_path, e)
        return False

    has_bom = raw_bytes.startswith(b"\xef\xbb\xbf")
    try:
        content = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        content = raw_bytes.decode("gb18030", errors="replace")

    original_content = content
    escaped_target = _escape_xml(target_actor)

    # ── 1. Update & deduplicate <actor> blocks ──────────────────────────────
    actor_matches = list(_ACTOR_BLOCK_RE.finditer(content))
    if actor_matches:
        updated_blocks: list[tuple[re.Match, str, bool, str | None]] = []
        target_actor_seen = False
        first_target_idx: int | None = None
        fallback_role_for_first: str | None = None

        for m in actor_matches:
            block = m.group(1)
            curr_name = _extract_tag_text(block, _NAME_TAG_RE)
            if not curr_name:
                updated_blocks.append((m, block, True, None))
                continue

            curr_norm = normalize_name(curr_name)
            if curr_norm in old_norms:
                old_stage_name = curr_name if curr_name != target_actor else None
                # Replace <name>...</name> with target_actor
                new_block = _NAME_TAG_RE.sub(
                    lambda nm: f"{nm.group(1)}{escaped_target}{nm.group(3)}",
                    block,
                    count=1,
                )
                if old_stage_name:
                    new_block = _set_or_insert_role(new_block, old_stage_name)

                if not target_actor_seen:
                    target_actor_seen = True
                    first_target_idx = len(updated_blocks)
                    updated_blocks.append((m, new_block, True, old_stage_name))
                else:
                    # Duplicate <actor> for the same target actor after merging
                    role_in_dup = _extract_tag_text(new_block, _ROLE_TAG_RE)
                    if role_in_dup and not fallback_role_for_first:
                        fallback_role_for_first = role_in_dup
                    updated_blocks.append((m, new_block, False, old_stage_name))
            else:
                updated_blocks.append((m, block, True, None))

        # If first target block had no role but a deduplicated block had one, preserve it
        if first_target_idx is not None and fallback_role_for_first:
            m0, blk0, keep0, role0 = updated_blocks[first_target_idx]
            if not _extract_tag_text(blk0, _ROLE_TAG_RE):
                blk0 = _set_or_insert_role(blk0, fallback_role_for_first)
                updated_blocks[first_target_idx] = (m0, blk0, keep0, role0)

        # Reconstruct content from back to front
        for m, new_blk, keep, _ in reversed(updated_blocks):
            replacement = new_blk if keep else ""
            content = content[: m.start(1)] + replacement + content[m.end(1) :]

    # ── 2. Update & deduplicate <set> blocks ────────────────────────────────
    set_matches = list(_SET_BLOCK_RE.finditer(content))
    if set_matches:
        target_set_seen = False
        set_updates: list[tuple[re.Match, str]] = []
        for m in set_matches:
            block = m.group(1)
            set_name = _extract_tag_text(block, _NAME_TAG_RE)
            if not set_name:
                continue
            set_norm = normalize_name(set_name)
            if set_norm in old_norms:
                new_block = _NAME_TAG_RE.sub(
                    lambda nm: f"{nm.group(1)}{escaped_target}{nm.group(3)}",
                    block,
                    count=1,
                )
                if not target_set_seen:
                    target_set_seen = True
                    set_updates.append((m, new_block))
                else:
                    set_updates.append((m, ""))
        for m, replacement in reversed(set_updates):
            content = content[: m.start(1)] + replacement + content[m.end(1) :]

    # ── 3. Append <tag>new_actor</tag> if <tag> contains old actor name ─────
    tag_matches = list(_TAG_LINE_RE.finditer(content))
    if tag_matches and non_target_old_norms:
        has_target_tag = False
        last_old_tag_match: re.Match | None = None

        for m in tag_matches:
            tag_val = html.unescape(m.group(2)).strip()
            tag_norm = normalize_name(tag_val)
            if tag_norm == target_norm:
                has_target_tag = True
            if tag_norm in non_target_old_norms or any(old_r in tag_val for old_r in non_target_old_raws):
                last_old_tag_match = m

        if last_old_tag_match is not None and not has_target_tag:
            indent = last_old_tag_match.group(1)
            line_end = last_old_tag_match.group(3)
            newline = line_end if line_end else ("\r\n" if "\r\n" in content else "\n")
            base_line = last_old_tag_match.group(0)
            if not base_line.endswith(("\n", "\r")):
                base_line += newline
            new_tag_line = f"{indent}<tag>{escaped_target}</tag>{newline}"
            insert_pos = last_old_tag_match.end(0)
            content = content[: last_old_tag_match.start(0)] + base_line + new_tag_line + content[insert_pos:]

    if content == original_content:
        return False

    # Atomic write via temporary file
    tmp_path = nfo_path.with_suffix(nfo_path.suffix + ".tmp")
    try:
        encoding = "utf-8-sig" if has_bom else "utf-8"
        tmp_path.write_bytes(content.encode(encoding))
        os.replace(tmp_path, nfo_path)
        return True
    except OSError as e:
        logger.warning("Failed to write updated NFO %s: %s", nfo_path, e)
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        return False


def update_nfos_in_directory(
    root_dir: Path,
    new_actor: str,
    old_names: set[str] | list[str],
) -> int:
    """Recursively update all .nfo files under root_dir (e.g. an actor folder or code folder).

    Returns the number of .nfo files modified.
    """
    if not root_dir.exists():
        return 0

    updated_count = 0
    for dirpath, dirnames, filenames in os.walk(str(root_dir)):
        dirnames[:] = [d for d in dirnames if d.lower() not in IGNORED_NAMES and d.lower() not in AUXILIARY_DIRS]
        for fname in filenames:
            if fname.lower().endswith(".nfo"):
                nfo_file = Path(dirpath) / fname
                if update_nfo_file(nfo_file, new_actor, old_names):
                    updated_count += 1
    return updated_count
