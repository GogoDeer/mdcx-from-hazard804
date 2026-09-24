"""High-performance directory scanner supporting arbitrary multi-level categories."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from .alias_resolver import normalize_name
from .models import TargetActorInfo

logger = logging.getLogger(__name__)

# Common media and metadata extensions defining a video code folder
MEDIA_EXTENSIONS = {
    ".mp4",
    ".mkv",
    ".iso",
    ".ts",
    ".wmv",
    ".avi",
    ".flv",
    ".m4v",
    ".rmvb",
    ".nfo",
    ".xml",
}

# Subfolders that exist inside a code directory and should not be treated as separate code/actor folders
AUXILIARY_DIRS = {
    "extrafanart",
    "images",
    "gallery",
    ".actors",
    "subs",
    "sub",
    "sample",
    "preview",
}

# Directory names to ignore during scanning
IGNORED_NAMES = {
    "$recycle.bin",
    "system volume information",
    ".git",
    ".idea",
    ".vscode",
    ".ds_store",
    "thumbs.db",
    "@eadir",
}

# Generic/fallback actor directory names that do not represent real performers
IGNORED_ACTOR_NAMES = {
    "未知演员",
    "未知",
    "unknown",
    "unknown actor",
    "未分类",
    "其他",
}


@dataclass
class TargetIndex:
    """Pre-cached in-memory index of the entire target archive directory."""

    target_root: Path
    categories: list[str] = field(default_factory=list)
    actors_by_norm: dict[str, TargetActorInfo] = field(default_factory=dict)
    total_actors: int = 0
    total_codes: int = 0
    scan_time: float = 0.0

    def get_actor_by_name(self, name: str) -> TargetActorInfo | None:
        norm = normalize_name(name)
        return self.actors_by_norm.get(norm)

    def add_existing_code(self, actor_norm: str, code_name: str) -> None:
        if actor_norm in self.actors_by_norm:
            self.actors_by_norm[actor_norm].existing_codes.add(code_name)


def is_path_excluded(dirpath: str, root_dir: str, exclude_list: list[str] | None) -> bool:
    """Checks whether a directory path matches any pattern in the exclude list."""
    if not exclude_list:
        return False

    norm_cur = os.path.normpath(dirpath).lower()
    norm_root = os.path.normpath(root_dir).lower()
    try:
        rel_cur = os.path.relpath(norm_cur, norm_root).lower()
    except ValueError:
        rel_cur = ""

    for exc in exclude_list:
        exc_str = str(exc).strip().strip("\"'").rstrip("/\\")
        if not exc_str:
            continue
        norm_exc = os.path.normpath(exc_str).lower()

        # 1. Matches as absolute path or subfolder of absolute path
        if norm_cur == norm_exc or norm_cur.startswith(norm_exc + os.sep):
            return True

        # 2. Matches as relative category name or subfolder of relative path
        if rel_cur and (rel_cur == norm_exc or rel_cur.startswith(norm_exc + os.sep)):
            return True

        # 3. Matches if target_root + exc_str
        abs_from_rel = os.path.normpath(os.path.join(norm_root, norm_exc))
        if norm_cur == abs_from_rel or norm_cur.startswith(abs_from_rel + os.sep):
            return True

    return False


class ArchiveScanner:
    """Scans and indexes target multi-level categories/actors and source intake directories."""

    @staticmethod
    def scan_target(target_path: str | Path, exclude_dirs: list[str] | None = None) -> TargetIndex:
        """
        Scans target archive directory hierarchy with arbitrary multi-level categories:
        TargetRoot / [Category Level 1] / [Category Level 2 ...] / [Actor] / [Code]

        Rule:
        - Skips any directory matched by exclude_dirs.
        - The tail parent directory directly containing a video code folder is the [Actor].
        - Everything between TargetRoot and [Actor] is the [Category] path.
        - Empty leaf directories under categories are also recognized as candidate Actor directories.
        """
        root = Path(target_path)
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(f"Target directory does not exist: {target_path}")

        t0 = time.perf_counter()
        index = TargetIndex(target_root=root)

        categories_set: set[str] = set()

        try:
            for dirpath, dirnames, filenames in os.walk(str(root)):
                # Filter out ignored directories in-place
                dirnames[:] = [d for d in dirnames if d.lower() not in IGNORED_NAMES]

                # Check if current directory or subdirectories are excluded
                if is_path_excluded(dirpath, str(root), exclude_dirs):
                    logger.debug("Excluding target directory: %s", dirpath)
                    dirnames.clear()  # Do not recurse into excluded directory
                    continue

                p = Path(dirpath)
                if p == root:
                    continue

                p_name_lower = p.name.lower()
                if p_name_lower in AUXILIARY_DIRS:
                    continue

                # Check if current directory contains media or metadata files (meaning it's a Code Directory)
                has_media = any(os.path.splitext(f)[1].lower() in MEDIA_EXTENSIONS for f in filenames)

                if has_media:
                    actor_dir = p.parent
                    if actor_dir == root:
                        continue

                    actor_name = actor_dir.name
                    actor_norm = normalize_name(actor_name)
                    code_name = p.name

                    # Multi-level category path (relative to target root)
                    try:
                        cat_rel = str(actor_dir.parent.relative_to(root))
                    except ValueError:
                        cat_rel = actor_dir.parent.name

                    categories_set.add(cat_rel)

                    if actor_norm not in index.actors_by_norm:
                        info = TargetActorInfo(
                            actor_name=actor_name,
                            category=cat_rel,
                            path=actor_dir,
                            existing_codes={code_name},
                        )
                        index.actors_by_norm[actor_norm] = info
                        index.total_actors += 1
                    else:
                        index.actors_by_norm[actor_norm].existing_codes.add(code_name)

                    index.total_codes += 1

                elif not dirnames:
                    # Empty leaf directory: might be an empty actor directory manually created by user
                    if p.parent != root:
                        actor_name = p.name
                        actor_norm = normalize_name(actor_name)
                        try:
                            cat_rel = str(p.parent.relative_to(root))
                        except ValueError:
                            cat_rel = p.parent.name

                        categories_set.add(cat_rel)

                        if actor_norm not in index.actors_by_norm:
                            info = TargetActorInfo(
                                actor_name=actor_name,
                                category=cat_rel,
                                path=p,
                                existing_codes=set(),
                            )
                            index.actors_by_norm[actor_norm] = info
                            index.total_actors += 1

        except (PermissionError, OSError) as e:
            logger.error("Error accessing target root %s: %s", root, e)
            raise

        index.categories = sorted(categories_set)
        index.scan_time = time.perf_counter() - t0
        logger.info(
            "Target scan complete in %.2fs: %d categories (multi-level), %d actors, %d codes",
            index.scan_time,
            len(index.categories),
            index.total_actors,
            index.total_codes,
        )
        return index

    @staticmethod
    def scan_source(source_path: str | Path) -> dict[str, list[Path]]:
        """
        Scans source intake directory hierarchy:
        SourceRoot / [Actor] / [Code]
        Returns a dictionary: actor_name -> list of code directory Paths.
        """
        root = Path(source_path)
        if not root.exists() or not root.is_dir():
            raise FileNotFoundError(f"Source directory does not exist: {source_path}")

        source_map: dict[str, list[Path]] = {}
        try:
            with os.scandir(str(root)) as actor_iter:
                for actor_entry in actor_iter:
                    if not actor_entry.is_dir() or actor_entry.name.lower() in IGNORED_NAMES:
                        continue

                    actor_name = actor_entry.name
                    code_dirs: list[Path] = []
                    try:
                        with os.scandir(actor_entry.path) as code_iter:
                            for code_entry in code_iter:
                                if code_entry.is_dir() and code_entry.name.lower() not in IGNORED_NAMES:
                                    code_dirs.append(Path(code_entry.path))
                    except (PermissionError, OSError) as e:
                        logger.warning("Error reading source actor directory %s: %s", actor_entry.path, e)

                    source_map[actor_name] = code_dirs

        except (PermissionError, OSError) as e:
            logger.error("Error accessing source root %s: %s", root, e)
            raise

        return source_map
