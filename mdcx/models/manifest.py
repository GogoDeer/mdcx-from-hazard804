import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config.manager import manager


@dataclass
class ScrapeManifest:
    # 原始文件与目录
    original_file_path: Path
    original_folder_path: Path
    # 刮削后的视频路径与目录
    new_file_path: Path
    new_folder_path: Path
    # 伴随转移的原文件（如字幕、种子、Bif、预告片等）：[(old_path, new_path), ...]
    moved_files: list[tuple[Path, Path]] = field(default_factory=list)
    # 本次刮削新生成/下载的文件：[nfo, poster, thumb, fanart, extrafanart, trailer, ...]
    created_files: list[Path] = field(default_factory=list)
    # 本次刮削创建的文件夹（若还原后为空可删除）
    created_dirs: list[Path] = field(default_factory=list)
    # 链接模式（0: 普通移动, 1: 软链接, 2: 硬链接）
    link_mode: int = 0
    # 刮削日志片段
    scrape_log: str = ""
    # 元数据信息（用于 AI 诊断报告）
    extracted_number: str = ""
    matched_title: str = ""
    scrape_time: str = ""
    duration_seconds: float = 0.0
    config_path: str = ""
    full_log_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_file_path": str(self.original_file_path),
            "original_folder_path": str(self.original_folder_path),
            "new_file_path": str(self.new_file_path),
            "new_folder_path": str(self.new_folder_path),
            "moved_files": [[str(old_p), str(new_p)] for old_p, new_p in self.moved_files],
            "created_files": [str(p) for p in self.created_files],
            "created_dirs": [str(p) for p in self.created_dirs],
            "link_mode": self.link_mode,
            "scrape_log": self.scrape_log,
            "extracted_number": self.extracted_number,
            "matched_title": self.matched_title,
            "scrape_time": self.scrape_time,
            "duration_seconds": self.duration_seconds,
            "config_path": self.config_path,
            "full_log_path": self.full_log_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScrapeManifest":
        return cls(
            original_file_path=Path(data.get("original_file_path", "")),
            original_folder_path=Path(data.get("original_folder_path", "")),
            new_file_path=Path(data.get("new_file_path", "")),
            new_folder_path=Path(data.get("new_folder_path", "")),
            moved_files=[(Path(pair[0]), Path(pair[1])) for pair in data.get("moved_files", []) if len(pair) == 2],
            created_files=[Path(p) for p in data.get("created_files", [])],
            created_dirs=[Path(p) for p in data.get("created_dirs", [])],
            link_mode=data.get("link_mode", 0),
            scrape_log=data.get("scrape_log", ""),
            extracted_number=data.get("extracted_number", ""),
            matched_title=data.get("matched_title", ""),
            scrape_time=data.get("scrape_time", ""),
            duration_seconds=float(data.get("duration_seconds", 0.0)),
            config_path=data.get("config_path", ""),
            full_log_path=data.get("full_log_path", ""),
        )


class ScrapeHistoryRegistry:
    """线程安全的刮削清单注册表，提供内存高速查找与磁盘持久化。"""

    _registry: dict[str, ScrapeManifest] = {}
    _max_entries: int = 200

    @classmethod
    def clear(cls) -> None:
        """清空注册表内存缓存"""
        cls._registry.clear()

    @classmethod
    def clear_cache(cls) -> None:
        """清空注册表内存缓存 (按规约命名)"""
        cls._registry.clear()

    @classmethod
    def _get_history_file(cls) -> Path:
        userdata = manager.data_folder / "userdata"
        userdata.mkdir(parents=True, exist_ok=True)
        return userdata / "restore_history.json"

    @classmethod
    def save(cls, manifest: ScrapeManifest) -> None:
        if not manifest.new_file_path and not manifest.original_file_path:
            return
        if manifest.new_file_path:
            cls._registry[str(manifest.new_file_path).replace("\\", "/").lower()] = manifest
        if manifest.original_file_path:
            cls._registry[str(manifest.original_file_path).replace("\\", "/").lower()] = manifest
        cls._persist_to_disk()

    @classmethod
    def get(cls, path: Path | str) -> ScrapeManifest | None:
        if not path:
            return None
        norm_key = str(path).replace("\\", "/").lower()
        if norm_key in cls._registry:
            return cls._registry[norm_key]
        # 尝试从磁盘重新加载
        cls._load_from_disk()
        return cls._registry.get(norm_key)

    @classmethod
    def remove(cls, manifest: ScrapeManifest) -> None:
        keys_to_remove = []
        if manifest.new_file_path:
            keys_to_remove.append(str(manifest.new_file_path).replace("\\", "/").lower())
        if manifest.original_file_path:
            keys_to_remove.append(str(manifest.original_file_path).replace("\\", "/").lower())
        for k in keys_to_remove:
            cls._registry.pop(k, None)
        cls._persist_to_disk()

    @classmethod
    def _persist_to_disk(cls) -> None:
        try:
            history_file = cls._get_history_file()
            manifests = list({id(m): m for m in cls._registry.values()}.values())
            manifests = manifests[-cls._max_entries :]
            data = [m.to_dict() for m in manifests]
            with open(history_file, "w", encoding="utf-8", errors="ignore") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    @classmethod
    def _load_from_disk(cls) -> None:
        try:
            history_file = cls._get_history_file()
            if not history_file.exists():
                return
            with open(history_file, encoding="utf-8", errors="ignore") as f:
                data = json.load(f)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        manifest = ScrapeManifest.from_dict(item)
                        if manifest.new_file_path:
                            cls._registry[str(manifest.new_file_path).replace("\\", "/").lower()] = manifest
                        if manifest.original_file_path:
                            cls._registry[str(manifest.original_file_path).replace("\\", "/").lower()] = manifest
        except Exception:
            pass
