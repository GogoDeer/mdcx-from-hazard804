"""Data models for Archive Mover."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


class MoveStatus(StrEnum):
    READY = "待移动"
    MOVED = "移动成功"
    DRY_RUN_MOVED = "模拟移动"
    SKIP_DUPLICATE = "跳过: 目标已存在同番号"
    SKIP_NO_ACTOR = "跳过: 目标未建档该演员"
    ERROR = "异常错误"


@dataclass
class TargetActorInfo:
    """Represents an indexed actor in the target archive directory."""

    actor_name: str
    category: str
    path: Path
    existing_codes: set[str] = field(default_factory=set)


@dataclass
class MoveItem:
    """Represents a single video code folder to be evaluated or moved."""

    source_actor: str
    source_code: str
    source_path: Path
    target_category: str | None = None
    target_actor: str | None = None
    target_actor_path: Path | None = None
    target_code_path: Path | None = None
    status: MoveStatus = MoveStatus.READY
    reason: str = ""
    match_type: str = "none"  # direct, normalized, alias_excel, stash_api, none


@dataclass
class ProcessReport:
    """Complete summary of a scan and/or move operation."""

    source_dir: str
    target_dir: str
    is_dry_run: bool
    clean_empty_dirs: bool
    excluded_dirs: list[str] = field(default_factory=list)
    scan_time_seconds: float = 0.0
    total_source_actors: int = 0
    total_source_codes: int = 0
    total_target_categories: int = 0
    total_target_actors: int = 0
    items: list[MoveItem] = field(default_factory=list)
    cleaned_empty_actors: list[str] = field(default_factory=list)

    @property
    def ready_or_moved_count(self) -> int:
        return sum(
            1 for item in self.items if item.status in (MoveStatus.READY, MoveStatus.MOVED, MoveStatus.DRY_RUN_MOVED)
        )

    @property
    def duplicate_count(self) -> int:
        return sum(1 for item in self.items if item.status == MoveStatus.SKIP_DUPLICATE)

    @property
    def no_actor_count(self) -> int:
        return sum(1 for item in self.items if item.status == MoveStatus.SKIP_NO_ACTOR)

    @property
    def error_count(self) -> int:
        return sum(1 for item in self.items if item.status == MoveStatus.ERROR)
