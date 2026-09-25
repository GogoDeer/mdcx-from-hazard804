"""Core move planner and execution engine."""

from __future__ import annotations

import logging
import os
import shutil
import time
from collections.abc import Callable
from pathlib import Path

from .alias_resolver import AliasResolver
from .models import MoveItem, MoveStatus, ProcessReport
from .nfo_updater import update_nfos_in_directory
from .scanner import IGNORED_NAMES, ArchiveScanner, TargetIndex

logger = logging.getLogger(__name__)


class ArchiveMover:
    """Coordinates matching, dry-run evaluation, directory moving, and cleanup."""

    def __init__(
        self,
        alias_resolver: AliasResolver | None = None,
        dry_run: bool = True,
        clean_empty_dirs: bool = True,
    ):
        self.alias_resolver = alias_resolver or AliasResolver()
        self.dry_run = dry_run
        self.clean_empty_dirs = clean_empty_dirs

    def evaluate_plan(
        self,
        source_path: str | Path,
        target_path: str | Path,
        exclude_dirs: list[str] | None = None,
        progress_cb: Callable[[int, int, str], None] | None = None,
    ) -> tuple[ProcessReport, TargetIndex]:
        """
        Scans target and source directories, maps actors via aliases, and builds a complete plan.
        Does not alter any files.
        """
        source_root = Path(source_path)
        target_root = Path(target_path)

        t_start = time.perf_counter()

        if progress_cb:
            progress_cb(0, 100, "正在预扫描目标归档目录结构...")

        # 1. Pre-scan target directory with exclusion filter
        target_index = ArchiveScanner.scan_target(target_root, exclude_dirs=exclude_dirs)

        if progress_cb:
            progress_cb(30, 100, "正在扫描源暂存目录...")

        # 2. Scan source directory
        source_map = ArchiveScanner.scan_source(source_root)

        report = ProcessReport(
            source_dir=str(source_root),
            target_dir=str(target_root),
            is_dry_run=self.dry_run,
            clean_empty_dirs=self.clean_empty_dirs,
            excluded_dirs=exclude_dirs or [],
            total_target_categories=len(target_index.categories),
            total_target_actors=target_index.total_actors,
            total_source_actors=len(source_map),
            total_source_codes=sum(len(codes) for codes in source_map.values()),
        )

        total_actors = len(source_map)
        processed_actors = 0

        # 3. Match each actor and evaluate each code directory
        for actor_name, code_paths in source_map.items():
            processed_actors += 1
            if progress_cb and total_actors > 0:
                pct = 30 + int((processed_actors / total_actors) * 60)
                progress_cb(pct, 100, f"正在匹配演员: {actor_name} ({processed_actors}/{total_actors})")

            # Resolve target actor
            target_info, match_type, matched_name = self.alias_resolver.resolve_target_actor(
                actor_name, target_index.actors_by_norm
            )

            for code_path in code_paths:
                code_name = code_path.name
                item = MoveItem(
                    source_actor=actor_name,
                    source_code=code_name,
                    source_path=code_path,
                )

                if target_info is None:
                    item.status = MoveStatus.SKIP_NO_ACTOR
                    item.reason = "目标归档区未找到该演员分类（直接匹配及别名库均未命中）"
                    item.match_type = "none"
                else:
                    item.target_category = target_info.category
                    item.target_actor = target_info.actor_name
                    item.target_actor_path = target_info.path
                    item.target_code_path = target_info.path / code_name
                    item.match_type = match_type

                    # Check for duplicate code
                    if code_name in target_info.existing_codes:
                        item.status = MoveStatus.SKIP_DUPLICATE
                        item.reason = (
                            f"目标已存在相同番号目录 (分类: {target_info.category} / 演员: {target_info.actor_name})"
                        )
                    else:
                        item.status = MoveStatus.READY
                        match_desc = {
                            "direct": "精确匹配",
                            "normalized": "规范化匹配(去空格)",
                            "alias": f"别名库匹配 -> {target_info.actor_name}",
                            "primary_actor": f"多演员首位匹配 -> {target_info.actor_name}",
                            "primary_actor_alias": f"多演员首位别名 -> {target_info.actor_name}",
                        }.get(match_type, match_type)
                        item.reason = f"匹配成功 ({match_desc}) -> [{target_info.category}/{target_info.actor_name}]"

                report.items.append(item)

        report.scan_time_seconds = time.perf_counter() - t_start
        if progress_cb:
            progress_cb(100, 100, "评估扫描完成")

        return report, target_index

    def execute_moves(
        self,
        report: ProcessReport,
        target_index: TargetIndex,
        progress_cb: Callable[[int, int, str], None] | None = None,
    ) -> ProcessReport:
        """
        Executes moves based on the evaluated report.
        If dry_run is True, simulates the moves and marks DRY_RUN_MOVED.
        If dry_run is False, moves directories and cleans empty source actor dirs if configured.
        """
        items_to_move = [item for item in report.items if item.status == MoveStatus.READY]
        total_items = len(items_to_move)

        report.is_dry_run = self.dry_run

        moved_actors: set[str] = set()

        for idx, item in enumerate(items_to_move, 1):
            if progress_cb and total_items > 0:
                pct = int((idx / total_items) * 100)
                action_text = "模拟移动" if self.dry_run else "正在移动"
                progress_cb(pct, 100, f"{action_text}: {item.source_actor}/{item.source_code}")

            if self.dry_run:
                item.status = MoveStatus.DRY_RUN_MOVED
                moved_actors.add(item.source_actor)
                continue

            # Real execution
            try:
                dest_path = item.target_code_path
                if dest_path.exists():
                    item.status = MoveStatus.SKIP_DUPLICATE
                    item.reason = f"执行时目标已存在同名目录: {dest_path}"
                    continue

                shutil.move(str(item.source_path), str(dest_path))
                item.status = MoveStatus.MOVED
                moved_actors.add(item.source_actor)

                # Update target index in memory and synchronize NFO actor names if alias matched
                if item.target_actor:
                    target_index.add_existing_code(item.target_actor, item.source_code)
                    import re as _re

                    old_candidates: set[str] = set()
                    if item.match_type in ("primary_actor", "primary_actor_alias"):
                        parts = [p.strip() for p in _re.split(r"[,，、/|]+", item.source_actor) if p.strip()]
                        if parts:
                            old_candidates.add(parts[0])
                    else:
                        old_candidates.add(item.source_actor)
                    if self.alias_resolver:
                        old_candidates.update(self.alias_resolver.get_actor_aliases(item.target_actor))
                        for c in list(old_candidates):
                            old_candidates.update(self.alias_resolver.get_actor_aliases(c))
                    update_nfos_in_directory(dest_path, item.target_actor, old_candidates)

            except Exception as e:
                logger.error("Failed to move %s -> %s: %s", item.source_path, item.target_code_path, e)
                item.status = MoveStatus.ERROR
                item.reason = f"移动失败异常: {e}"

        # Clean empty source actor directories
        if self.clean_empty_dirs:
            source_root = Path(report.source_dir)
            for actor_name in moved_actors:
                actor_dir = source_root / actor_name
                if not actor_dir.exists() or not actor_dir.is_dir():
                    continue

                # Check remaining non-ignored contents
                remaining = []
                try:
                    with os.scandir(str(actor_dir)) as it:
                        for entry in it:
                            if entry.name.lower() not in IGNORED_NAMES:
                                remaining.append(entry.name)
                except Exception as e:
                    logger.warning("Error checking empty dir %s: %s", actor_dir, e)
                    continue

                if not remaining:
                    if self.dry_run:
                        report.cleaned_empty_actors.append(f"[预演] {actor_name}")
                    else:
                        try:
                            # Remove junk files first if any
                            with os.scandir(str(actor_dir)) as it:
                                for entry in it:
                                    if entry.is_file():
                                        os.remove(entry.path)
                            os.rmdir(str(actor_dir))
                            report.cleaned_empty_actors.append(actor_name)
                            logger.info("Removed empty source actor directory: %s", actor_dir)
                        except Exception as e:
                            logger.warning("Failed to remove empty actor dir %s: %s", actor_dir, e)

        return report
