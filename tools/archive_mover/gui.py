"""Modern PyQt6 Graphical User Interface for Archive Mover — unified dark theme."""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
import webbrowser
from pathlib import Path

from PyQt6.QtCore import QObject, QPointF, Qt, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPalette, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .alias_resolver import AliasResolver, test_stash_connection
from .models import MoveItem, MoveStatus, ProcessReport
from .mover import ArchiveMover
from .reporter import ReportGenerator
from .scanner import TargetIndex

logger = logging.getLogger(__name__)


def _get_config_path() -> Path:
    """Return the configuration file path in userdata directory."""
    userdata_dir = Path(__file__).resolve().parents[2] / "userdata"
    if userdata_dir.exists():
        return userdata_dir / "archive_mover_config.json"
    return Path(__file__).parent / "config.json"


# ── Colour palette ────────────────────────────────────────────────────────────
BG_DEEP = "#0f1117"  # window background
BG_CARD = "#1a1d27"  # cards / panels
BG_WIDGET = "#222535"  # input fields, table background
BG_HOVER = "#2a2e3f"  # hover on inputs
BORDER = "#2e3250"  # subtle separator
BORDER_FOCUS = "#4f6cff"  # input focus ring

TEXT_PRIMARY = "#e2e8f0"  # main text
TEXT_SECONDARY = "#94a3b8"  # labels, sub-text
TEXT_DIM = "#64748b"  # placeholder / disabled

ACCENT_BLUE = "#4f6cff"
ACCENT_GREEN = "#22c55e"
ACCENT_RED = "#ef4444"
ACCENT_AMBER = "#f59e0b"
ACCENT_INDIGO = "#818cf8"

BTN_SCAN_BG = "#3b4fd8"
BTN_SCAN_HOVER = "#4f6cff"
BTN_EXEC_BG = "#166534"
BTN_EXEC_HOVER = "#16a34a"
BTN_REPORT_BG = "#374151"
BTN_REPORT_HOVER = "#4b5563"
BTN_BROWSE_BG = "#1e2130"
BTN_BROWSE_HOVER = "#2a2e3f"

ROW_EVEN = "#1a1d27"
ROW_ODD = "#1e2235"
ROW_SELECTED = "#2a3160"

# Path to the bundled checkmark PNG (used in QSS for checkbox indicator)
_CHECKMARK_PNG = Path(__file__).parent / "_checkmark.png"

# Path to the application icon (ICO for Windows taskbar/window, PNG as fallback)
_APP_ICON_ICO = Path(__file__).parent / "app_icon.ico"
_APP_ICON_PNG = Path(__file__).parent / "app_icon.png"
APP_ICON_PATH = _APP_ICON_ICO if _APP_ICON_ICO.exists() else _APP_ICON_PNG


def _ensure_checkmark_icon() -> str:
    """Ensure a high-contrast, antialiased white checkmark PNG exists for QCheckBox."""
    if not _CHECKMARK_PNG.exists() or _CHECKMARK_PNG.stat().st_size == 0:
        img = QImage(32, 32, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(Qt.GlobalColor.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor("#ffffff"), 4.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.drawLine(QPointF(6, 17), QPointF(13, 24))
        p.drawLine(QPointF(13, 24), QPointF(26, 8))
        p.end()
        img.save(str(_CHECKMARK_PNG), "PNG")
    return str(_CHECKMARK_PNG).replace("\\", "/")


def _build_qss() -> str:
    """Build the global stylesheet with the correct runtime checkmark icon path."""
    checkmark_path = _ensure_checkmark_icon()
    return f"""
/* ── App / Window ── */
QMainWindow, QDialog, QWidget {{
    background-color: {BG_DEEP};
    color: {TEXT_PRIMARY};
}}

/* ── GroupBox ── */
QGroupBox {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 10px;
    padding: 12px 10px 10px 10px;
    font-weight: 600;
    font-size: 13px;
    color: {TEXT_PRIMARY};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    top: -2px;
    padding: 0 4px;
    color: {ACCENT_INDIGO};
}}

/* ── Labels ── */
QLabel {{
    background: transparent;
    color: {TEXT_SECONDARY};
    font-size: 12px;
}}

/* ── Line Edits ── */
QLineEdit {{
    background-color: {BG_WIDGET};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 5px 8px;
    color: {TEXT_PRIMARY};
    font-size: 12px;
    selection-background-color: {ACCENT_BLUE};
}}
QLineEdit:focus {{
    border: 1px solid {BORDER_FOCUS};
}}
QLineEdit:disabled {{
    background-color: {BG_CARD};
    color: {TEXT_DIM};
    border-color: {BORDER};
}}
QLineEdit::placeholder {{
    color: {TEXT_DIM};
}}

/* ── CheckBox ── */
QCheckBox {{
    color: {TEXT_SECONDARY};
    spacing: 8px;
    font-size: 12px;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1.5px solid {BORDER};
    background-color: {BG_WIDGET};
}}
QCheckBox::indicator:hover {{
    border-color: {BORDER_FOCUS};
    background-color: {BG_HOVER};
}}
QCheckBox::indicator:checked {{
    background-color: {ACCENT_BLUE};
    border-color: {ACCENT_BLUE};
    image: url("{checkmark_path}");
}}
QCheckBox::indicator:checked:hover {{
    background-color: {BTN_SCAN_HOVER};
    border-color: {BTN_SCAN_HOVER};
}}

/* ── Push Buttons (default) ── */
QPushButton {{
    background-color: {BTN_BROWSE_BG};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 5px;
    padding: 5px 12px;
    font-size: 12px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {BTN_BROWSE_HOVER};
    border-color: {BORDER_FOCUS};
}}
QPushButton:pressed {{
    background-color: {BG_DEEP};
}}
QPushButton:disabled {{
    background-color: {BG_CARD};
    color: {TEXT_DIM};
    border-color: {BORDER};
}}

/* Named button styles are applied inline */

/* ── Progress Bar ── */
QProgressBar {{
    background-color: {BG_WIDGET};
    border: 1px solid {BORDER};
    border-radius: 4px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background-color: {ACCENT_BLUE};
    border-radius: 3px;
}}

/* ── TabWidget / TabBar ── */
QTabWidget::pane {{
    border: none;
    background: transparent;
}}
QTabBar {{
    background: transparent;
}}
QTabBar::tab {{
    background-color: {BG_CARD};
    color: {TEXT_SECONDARY};
    border: 1px solid {BORDER};
    border-bottom: none;
    border-radius: 5px 5px 0 0;
    padding: 5px 14px;
    margin-right: 2px;
    font-size: 12px;
}}
QTabBar::tab:selected {{
    background-color: {BG_WIDGET};
    color: {TEXT_PRIMARY};
    border-bottom: 2px solid {ACCENT_BLUE};
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{
    background-color: {BG_HOVER};
    color: {TEXT_PRIMARY};
}}

/* ── Table ── */
QTableWidget {{
    background-color: {BG_WIDGET};
    alternate-background-color: {ROW_ODD};
    border: 1px solid {BORDER};
    border-radius: 0 0 6px 6px;
    gridline-color: {BORDER};
    color: {TEXT_PRIMARY};
    font-size: 12px;
    selection-background-color: {ROW_SELECTED};
    selection-color: {TEXT_PRIMARY};
    outline: none;
}}
QTableWidget::item {{
    padding: 3px 6px;
    border: none;
}}
QTableWidget::item:selected {{
    background-color: {ROW_SELECTED};
}}
QHeaderView::section {{
    background-color: {BG_DEEP};
    color: {TEXT_SECONDARY};
    border: none;
    border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
    padding: 5px 8px;
    font-weight: 600;
    font-size: 12px;
}}
QHeaderView::section:last {{
    border-right: none;
}}

/* ── Scrollbars ── */
QScrollBar:vertical {{
    background: {BG_DEEP};
    width: 8px;
    margin: 0;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {TEXT_DIM};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: {BG_DEEP};
    height: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER};
    border-radius: 4px;
    min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {TEXT_DIM};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ── Splitter ── */
QSplitter::handle {{
    background-color: {BORDER};
}}
QSplitter::handle:vertical {{
    height: 4px;
}}

/* ── MessageBox / Dialog ── */
QMessageBox {{
    background-color: {BG_CARD};
}}
QMessageBox QLabel {{
    color: {TEXT_PRIMARY};
}}
QMessageBox QPushButton {{
    min-width: 80px;
}}

/* ── ToolTip ── */
QToolTip {{
    background-color: {BG_CARD};
    color: {TEXT_PRIMARY};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 4px 8px;
}}
"""


class WorkerSignals(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(object, object)
    error = pyqtSignal(str)


_ACTIVE_TEST_WORKERS: set[QObject] = set()


class StashTesterWorker(QObject):
    finished = pyqtSignal(int, int, bool, str)  # (source_id, seq, is_success, message)

    def __init__(self, source_id: int, seq: int, url: str, api_key: str):
        super().__init__()
        self.source_id = source_id
        self.seq = seq
        self.url = url
        self.api_key = api_key
        self.signals = self

    def start(self):
        import threading

        def _run():
            try:
                ok, msg = test_stash_connection(self.url, self.api_key)
                self.finished.emit(self.source_id, self.seq, ok, msg)
            except Exception:
                pass
            finally:
                _ACTIVE_TEST_WORKERS.discard(self)

        threading.Thread(target=_run, daemon=True).start()


class EvaluationWorker(QThread):
    def __init__(
        self,
        mover: ArchiveMover,
        source_path: str,
        target_path: str,
        exclude_dirs: list[str] | None = None,
    ):
        super().__init__()
        self.mover = mover
        self.source_path = source_path
        self.target_path = target_path
        self.exclude_dirs = exclude_dirs
        self.signals = WorkerSignals()

    def run(self):
        try:
            report, target_index = self.mover.evaluate_plan(
                self.source_path,
                self.target_path,
                exclude_dirs=self.exclude_dirs,
                progress_cb=self.signals.progress.emit,
            )
            self.signals.finished.emit(report, target_index)
        except Exception as e:
            self.signals.error.emit(str(e))


class ExecutionWorker(QThread):
    def __init__(self, mover: ArchiveMover, report: ProcessReport, target_index: TargetIndex):
        super().__init__()
        self.mover = mover
        self.report = report
        self.target_index = target_index
        self.signals = WorkerSignals()

    def run(self):
        try:
            res_report = self.mover.execute_moves(
                self.report,
                self.target_index,
                progress_cb=self.signals.progress.emit,
            )
            self.signals.finished.emit(res_report, self.target_index)
        except Exception as e:
            self.signals.error.emit(str(e))


# Dedicated signals for duplicate-actor scan (returns list of result dicts, resolver)
class DupActorSignals(QObject):
    finished = pyqtSignal(list, object)  # duplicates: list[dict], resolver: object
    error = pyqtSignal(str)


class DuplicateActorWorker(QThread):
    """Scans the target archive and finds actor/alias names that share the same performer cluster
    or normalized name, but appear in multiple directories (different categories or alias conflict)."""

    def __init__(
        self,
        target_path: str,
        exclude_dirs: list[str] | None = None,
        alias_resolver: AliasResolver | None = None,
        db_path: str = "",
        stash_sources: list[tuple[str, str]] | None = None,
        ignored_dup_groups: list[dict] | None = None,
    ):
        super().__init__()
        self.target_path = target_path
        self.exclude_dirs = exclude_dirs
        self.alias_resolver = alias_resolver
        self.db_path = db_path
        self.stash_sources = stash_sources or []
        self.ignored_dup_groups = ignored_dup_groups or []
        self.signals = DupActorSignals()

    def run(self):
        try:
            import os as _os
            from collections import defaultdict
            from pathlib import Path as _Path

            from .alias_resolver import AliasResolver, normalize_name
            from .scanner import AUXILIARY_DIRS, IGNORED_ACTOR_NAMES, IGNORED_NAMES, MEDIA_EXTENSIONS, is_path_excluded

            root = _Path(self.target_path)
            if not root.exists():
                raise FileNotFoundError(f"目标目录不存在: {self.target_path}")

            ignored_actor_norms = {normalize_name(x) for x in IGNORED_ACTOR_NAMES}

            # 1. 确保别名库准备就绪（独立扫描时若未加载，则在子线程自动加载并合并）
            resolver = self.alias_resolver
            if resolver is None and (self.db_path or self.stash_sources):
                resolver = AliasResolver(
                    excel_path=self.db_path if _Path(self.db_path).exists() else None,
                    disjoint_groups=self.ignored_dup_groups,
                )
                if self.db_path and _Path(self.db_path).exists():
                    resolver.load_excel()
                for s_url, s_key in self.stash_sources:
                    resolver.load_stash(s_url, s_key)
                resolver.consolidate_clusters()
            elif resolver is not None and self.ignored_dup_groups:
                resolver.set_disjoint_groups(self.ignored_dup_groups)

            # 预处理屏蔽列表（支持按演员名集合屏蔽，也支持按目录路径集合屏蔽）
            ignored_name_sets: list[set[str]] = []
            ignored_path_sets: list[set[str]] = []
            for ig in self.ignored_dup_groups:
                if not isinstance(ig, dict):
                    continue
                n_set = {normalize_name(n) for n in ig.get("names", []) if n and normalize_name(n)}
                if len(n_set) >= 2:
                    ignored_name_sets.append(n_set)
                p_set = {_os.path.normcase(_os.path.normpath(p)) for p in ig.get("paths", []) if p}
                if len(p_set) >= 2:
                    ignored_path_sets.append(p_set)

            # 2. 遍历目标归档库，提取所有包含视频文件的演员目录
            norm_to_entries: dict[str, list[dict]] = defaultdict(list)
            code_parent_seen: set[str] = set()

            for dirpath, dirnames, filenames in _os.walk(str(root)):
                dirnames[:] = [d for d in dirnames if d.lower() not in IGNORED_NAMES]
                if is_path_excluded(dirpath, str(root), self.exclude_dirs):
                    dirnames.clear()
                    continue
                p = _Path(dirpath)
                if p == root:
                    continue
                if p.name.lower() in AUXILIARY_DIRS:
                    continue
                has_media = any(_os.path.splitext(f)[1].lower() in MEDIA_EXTENSIONS for f in filenames)
                if has_media:
                    actor_dir = p.parent
                    if actor_dir == root:
                        continue
                    key = str(actor_dir)
                    if key in code_parent_seen:
                        continue
                    code_parent_seen.add(key)
                    actor_name = actor_dir.name
                    norm = normalize_name(actor_name)
                    # 排除非真实演员目录（如 scrape 无法获取演员的集合目录“未知演员”）
                    if not norm or norm in ignored_actor_norms:
                        continue
                    try:
                        cat_rel = str(actor_dir.parent.relative_to(root))
                    except ValueError:
                        cat_rel = actor_dir.parent.name
                    norm_to_entries[norm].append(
                        {
                            "raw_name": actor_name,
                            "category": cat_rel,
                            "path": str(actor_dir),
                        }
                    )

            # 3. 别名识别与聚类归一化（仅当别名唯一且非多人共用撞名时才跨名归并）
            cluster_groups: dict[str, list[dict]] = defaultdict(list)

            if resolver and resolver._clusters:
                for norm, entries in norm_to_entries.items():
                    if resolver.is_unambiguous_alias(norm):
                        cid = resolver._name_to_cluster_ids[norm][0]
                        cluster_groups[f"cid_{cid}"].extend(entries)
                    else:
                        cluster_groups[f"norm_{norm}"].extend(entries)
            else:
                for norm, entries in norm_to_entries.items():
                    cluster_groups[f"norm_{norm}"].extend(entries)

            # 4. 判定重复演员与诊断（并按用户屏蔽列表拆分/过滤已确认非同一人的目录）
            duplicates: list[dict] = []
            for _gkey, raw_entries in cluster_groups.items():
                # 若同一簇中包含被用户标记为“非同一演员”的名字对，将其拆分为互不冲突的子组
                sub_groups: list[list[dict]] = []
                for entry in raw_entries:
                    e_norm = normalize_name(entry["raw_name"])
                    placed = False
                    for sg in sub_groups:
                        conflict = any(
                            any(
                                e_norm in ig_ns and normalize_name(existing["raw_name"]) in ig_ns
                                for ig_ns in ignored_name_sets
                            )
                            for existing in sg
                            if normalize_name(existing["raw_name"]) != e_norm
                        )
                        if not conflict:
                            sg.append(entry)
                            placed = True
                            break
                    if not placed:
                        sub_groups.append([entry])

                for entries in sub_groups:
                    unique_paths = {e["path"] for e in entries}
                    if len(unique_paths) < 2:
                        continue

                    unique_names = list(dict.fromkeys(e["raw_name"] for e in entries))
                    norm_paths = {_os.path.normcase(_os.path.normpath(p)) for p in unique_paths}
                    norm_names = {normalize_name(n) for n in unique_names if normalize_name(n)}

                    # 若整个候选组的路径集合或名字集合已在屏蔽列表中，跳过不提示
                    if len(norm_names) >= 2 and any(norm_names.issubset(ig_ns) for ig_ns in ignored_name_sets):
                        continue
                    if any(norm_paths.issubset(ig_ps) for ig_ps in ignored_path_sets):
                        continue

                    unique_cats = list(dict.fromkeys(e["category"] for e in entries))
                    canonical_name = max(unique_names, key=len)

                    # 诊断特征类型
                    if len(unique_names) > 1:
                        alias_pair = " <=> ".join(unique_names[:3])
                        if len(unique_cats) == 1:
                            diag = f"⚠️ 同分类别名冲突 ({alias_pair})"
                        else:
                            diag = f"⚠️ 别名跨分类重复 ({alias_pair})"
                    else:
                        if len(unique_cats) > 1:
                            diag = f"📂 同名分散于 {len(unique_cats)} 个不同分类"
                        else:
                            diag = f"⚠️ 重复子目录 (共 {len(unique_paths)} 处)"

                    duplicates.append(
                        {
                            "canonical_name": canonical_name,
                            "diag": diag,
                            "entries": sorted(entries, key=lambda x: (x["category"], x["raw_name"])),
                        }
                    )

            # 排序：别名冲突优先排前，便于重点排查
            duplicates.sort(key=lambda d: (0 if "⚠️" in d["diag"] else 1, d["canonical_name"]))

            self.signals.finished.emit(duplicates, resolver)
        except Exception as e:
            self.signals.error.emit(str(e))


class StatCard(QWidget):
    """A compact stats card with title + big coloured number."""

    def __init__(self, title: str, init_val: str, accent: str, parent=None):
        super().__init__(parent)
        self._accent = accent
        self.setObjectName("statCard")
        self.setStyleSheet(
            f"QWidget#statCard {{ background-color: {BG_CARD}; border: 1px solid {BORDER}; border-radius: 8px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(3)

        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet(f"font-size: 11px; color: {TEXT_DIM}; font-weight: 500; background: transparent;")

        self.lbl_val = QLabel(init_val)
        self.lbl_val.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {accent}; background: transparent;")

        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_val)

    def set_value(self, text: str) -> None:
        self.lbl_val.setText(text)


def _make_separator() -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.Shape.HLine)
    sep.setStyleSheet(f"color: {BORDER}; background: {BORDER};")
    sep.setFixedHeight(1)
    return sep


def _label(text: str, width: int = 0) -> QLabel:
    lbl = QLabel(text)
    if width:
        lbl.setFixedWidth(width)
    return lbl


def _browse_btn() -> QPushButton:
    btn = QPushButton("浏览…")
    btn.setFixedWidth(64)
    btn.setToolTip("选择文件夹")
    return btn


class ArchiveMoverWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("视频归档智能整理工具 (Archive Mover)")
        self.resize(1160, 820)
        if APP_ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(APP_ICON_PATH)))

        self.last_report: ProcessReport | None = None
        self.last_target_index: TargetIndex | None = None
        self.last_html_report: Path | None = None
        self.last_alias_resolver: AliasResolver | None = None
        self._stash_test_seq: dict[int, int] = {1: 0, 2: 0}
        self.ignored_dup_groups: list[dict] = [
            {
                "names": ["かわいまゆ", "北見唯奈"],
                "paths": [],
                "label": "かわいまゆ ≠ 北見唯奈",
            }
        ]

        self._init_ui()
        self._load_settings()
        self._update_ignored_btn_label()
        self._connect_auto_save()

        # 启动时自动测试已启用的 Stash 源
        if self.chk_stash1.isChecked():
            self._test_stash_async(1)
        if self.chk_stash2.isChecked():
            self._test_stash_async(2)

    # ─────────────────────────────────────────────────────── UI Construction ─
    def _init_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setSpacing(0)
        root_layout.setContentsMargins(0, 0, 0, 0)

        # ── Top section (config + controls + stats) — fixed height ──────────
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(14, 12, 14, 8)
        top_layout.setSpacing(8)

        # Path config group
        top_layout.addWidget(self._build_path_group())
        top_layout.addWidget(_make_separator())

        # Action bar
        top_layout.addLayout(self._build_action_bar())

        # Progress + status
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        top_layout.addWidget(self.progress_bar)

        self.lbl_status = QLabel("就绪  ·  请确认路径后点击【扫描评估】")
        self.lbl_status.setStyleSheet(f"color: {TEXT_DIM}; font-size: 12px; padding: 1px 0;")
        top_layout.addWidget(self.lbl_status)

        top_layout.addWidget(_make_separator())

        # Stats cards
        top_layout.addWidget(self._build_stats_bar())

        top_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        # ── Bottom section (tabs + table) — fills remaining space ────────────
        bottom_widget = self._build_table_section()

        # ── Splitter so user can drag to resize top vs table ─────────────────
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setHandleWidth(4)
        splitter.addWidget(top_widget)
        splitter.addWidget(bottom_widget)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 380])

        root_layout.addWidget(splitter)

    def _build_path_group(self) -> QGroupBox:
        grp = QGroupBox("📁  路径配置")
        layout = QVBoxLayout(grp)
        layout.setSpacing(6)
        LABEL_W = 120

        # Source
        h_src = QHBoxLayout()
        h_src.addWidget(_label("源暂存目录：", LABEL_W))
        self.txt_source = QLineEdit(r"\\192.168.1.8\ZoneB\temp\9-13\无码")
        h_src.addWidget(self.txt_source)
        btn_src = _browse_btn()
        btn_src.clicked.connect(lambda: self._browse_dir(self.txt_source))
        h_src.addWidget(btn_src)
        layout.addLayout(h_src)

        # Target
        h_tgt = QHBoxLayout()
        h_tgt.addWidget(_label("目标归档目录：", LABEL_W))
        self.txt_target = QLineEdit(r"\\192.168.1.8\ZoneB\mov\步兵")
        h_tgt.addWidget(self.txt_target)
        btn_tgt = _browse_btn()
        btn_tgt.clicked.connect(lambda: self._browse_dir(self.txt_target))
        h_tgt.addWidget(btn_tgt)
        layout.addLayout(h_tgt)

        # Actor DB + Exclude (two columns)
        h_bottom = QHBoxLayout()
        h_bottom.setSpacing(10)

        h_db = QHBoxLayout()
        h_db.addWidget(_label("演员别名库：", LABEL_W))
        default_db = str(Path(__file__).resolve().parents[2] / "userdata" / "actor_database.xlsx")
        self.txt_db = QLineEdit(default_db)
        h_db.addWidget(self.txt_db)
        btn_db = _browse_btn()
        btn_db.clicked.connect(self._browse_excel_file)
        h_db.addWidget(btn_db)
        h_bottom.addLayout(h_db, 3)

        h_exc = QHBoxLayout()
        h_exc.addWidget(_label("排除目录：", 72))
        self.txt_exclude = QLineEdit("流出")
        self.txt_exclude.setPlaceholderText("多个用逗号分隔，如: 流出, 合集")
        h_exc.addWidget(self.txt_exclude)
        h_bottom.addLayout(h_exc, 2)

        layout.addLayout(h_bottom)

        # Stash API Source 1
        h_stash1 = QHBoxLayout()
        self.chk_stash1 = QCheckBox("启用 Stash 源 1")
        self.chk_stash1.setFixedWidth(125)
        self.chk_stash1.toggled.connect(self._toggle_stash1_inputs)
        h_stash1.addWidget(self.chk_stash1)
        h_stash1.addWidget(_label("地址：", 40))
        self.txt_stash1_url = QLineEdit("http://192.168.1.8:9999")
        self.txt_stash1_url.setEnabled(False)
        h_stash1.addWidget(self.txt_stash1_url, 3)
        h_stash1.addWidget(_label("  ApiKey：", 60))
        self.txt_stash1_key = QLineEdit()
        self.txt_stash1_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_stash1_key.setPlaceholderText("未开鉴权可留空")
        self.txt_stash1_key.setEnabled(False)
        h_stash1.addWidget(self.txt_stash1_key, 2)

        self.lbl_stash1_status = QLabel("")
        self.lbl_stash1_status.setFixedSize(64, 28)
        self.lbl_stash1_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_stash1_status.setVisible(False)
        h_stash1.addWidget(self.lbl_stash1_status)

        self.btn_stash1_test = QPushButton("测试")
        self.btn_stash1_test.setFixedSize(64, 28)
        self.btn_stash1_test.setEnabled(False)
        self.btn_stash1_test.setToolTip("手动测试此 Stash 源与 ApiKey 是否配置成功")
        self.btn_stash1_test.setStyleSheet(
            f"QPushButton {{ background-color: {BTN_BROWSE_BG}; color: {TEXT_SECONDARY}; border: 1px solid {BORDER};"
            f" border-radius: 5px; font-size: 12px; font-weight: 500; padding: 0px; }}"
            f"QPushButton:hover {{ background-color: {BTN_BROWSE_HOVER}; color: {TEXT_PRIMARY}; }}"
            f"QPushButton:disabled {{ background-color: transparent; color: {TEXT_DIM}; border-color: transparent; }}"
        )
        self.btn_stash1_test.clicked.connect(lambda: self._test_stash_async(1))
        h_stash1.addWidget(self.btn_stash1_test)
        layout.addLayout(h_stash1)

        # Stash API Source 2
        h_stash2 = QHBoxLayout()
        self.chk_stash2 = QCheckBox("启用 Stash 源 2")
        self.chk_stash2.setFixedWidth(125)
        self.chk_stash2.toggled.connect(self._toggle_stash2_inputs)
        h_stash2.addWidget(self.chk_stash2)
        h_stash2.addWidget(_label("地址：", 40))
        self.txt_stash2_url = QLineEdit("")
        self.txt_stash2_url.setPlaceholderText("例如 http://192.168.1.x:9999")
        self.txt_stash2_url.setEnabled(False)
        h_stash2.addWidget(self.txt_stash2_url, 3)
        h_stash2.addWidget(_label("  ApiKey：", 60))
        self.txt_stash2_key = QLineEdit()
        self.txt_stash2_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.txt_stash2_key.setPlaceholderText("未开鉴权可留空")
        self.txt_stash2_key.setEnabled(False)
        h_stash2.addWidget(self.txt_stash2_key, 2)

        self.lbl_stash2_status = QLabel("")
        self.lbl_stash2_status.setFixedSize(64, 28)
        self.lbl_stash2_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_stash2_status.setVisible(False)
        h_stash2.addWidget(self.lbl_stash2_status)

        self.btn_stash2_test = QPushButton("测试")
        self.btn_stash2_test.setFixedSize(64, 28)
        self.btn_stash2_test.setEnabled(False)
        self.btn_stash2_test.setToolTip("手动测试此 Stash 源与 ApiKey 是否配置成功")
        self.btn_stash2_test.setStyleSheet(
            f"QPushButton {{ background-color: {BTN_BROWSE_BG}; color: {TEXT_SECONDARY}; border: 1px solid {BORDER};"
            f" border-radius: 5px; font-size: 12px; font-weight: 500; padding: 0px; }}"
            f"QPushButton:hover {{ background-color: {BTN_BROWSE_HOVER}; color: {TEXT_PRIMARY}; }}"
            f"QPushButton:disabled {{ background-color: transparent; color: {TEXT_DIM}; border-color: transparent; }}"
        )
        self.btn_stash2_test.clicked.connect(lambda: self._test_stash_async(2))
        h_stash2.addWidget(self.btn_stash2_test)
        layout.addLayout(h_stash2)

        return grp

    def _build_action_bar(self) -> QHBoxLayout:
        bar = QHBoxLayout()
        bar.setSpacing(10)

        self.chk_dry_run = QCheckBox("模拟预演")
        self.chk_dry_run.setChecked(True)
        self.chk_dry_run.setStyleSheet(f"QCheckBox {{ color: {ACCENT_BLUE}; font-weight: 700; font-size: 13px; }}")
        bar.addWidget(self.chk_dry_run)

        self.chk_clean_empty = QCheckBox("清理源端空目录")
        self.chk_clean_empty.setChecked(True)
        self.chk_clean_empty.setStyleSheet(f"QCheckBox {{ color: {TEXT_SECONDARY}; font-size: 12px; }}")
        bar.addWidget(self.chk_clean_empty)

        bar.addStretch()

        self.btn_scan = QPushButton("扫描评估")
        self.btn_scan.setFixedHeight(34)
        self.btn_scan.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_scan.setStyleSheet(
            f"QPushButton {{ background-color: {BTN_SCAN_BG}; color: #fff; border: none; border-radius: 6px;"
            f" padding: 0 18px; font-weight: 700; font-size: 13px; }}"
            f"QPushButton:hover {{ background-color: {BTN_SCAN_HOVER}; }}"
            f"QPushButton:pressed {{ background-color: #2a3ab0; }}"
            f"QPushButton:disabled {{ background-color: #1e2130; color: {TEXT_DIM}; }}"
        )
        self.btn_scan.clicked.connect(self._start_evaluation)
        bar.addWidget(self.btn_scan)

        self.btn_execute = QPushButton("执行移动")
        self.btn_execute.setFixedHeight(34)
        self.btn_execute.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_execute.setEnabled(False)
        self.btn_execute.setStyleSheet(
            f"QPushButton {{ background-color: {BTN_EXEC_BG}; color: #fff; border: none; border-radius: 6px;"
            f" padding: 0 18px; font-weight: 700; font-size: 13px; }}"
            f"QPushButton:hover {{ background-color: {BTN_EXEC_HOVER}; }}"
            f"QPushButton:pressed {{ background-color: #14532d; }}"
            f"QPushButton:disabled {{ background-color: #1e2130; color: {TEXT_DIM}; }}"
        )
        self.btn_execute.clicked.connect(self._start_execution)
        bar.addWidget(self.btn_execute)

        self.btn_open_report = QPushButton("查看报告")
        self.btn_open_report.setFixedHeight(34)
        self.btn_open_report.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_open_report.setEnabled(False)
        self.btn_open_report.setStyleSheet(
            f"QPushButton {{ background-color: #0284c7; color: #ffffff; border: 1px solid #38bdf8;"
            f" border-radius: 6px; padding: 0 16px; font-weight: 700; font-size: 13px; }}"
            f"QPushButton:hover {{ background-color: #0369a1; border-color: #7dd3fc; }}"
            f"QPushButton:pressed {{ background-color: #0c4a6e; }}"
            f"QPushButton:disabled {{ background-color: #1e2130; color: {TEXT_DIM}; border: 1px solid {BORDER}; font-weight: normal; }}"
        )
        self.btn_open_report.clicked.connect(self._open_latest_report)
        bar.addWidget(self.btn_open_report)

        return bar

    def _build_stats_bar(self) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(8)

        self.card_total = StatCard("源端番号", "—", ACCENT_BLUE)
        self.card_target = StatCard("归档库已建档", "—", ACCENT_INDIGO)
        self.card_move = StatCard("计划 / 成功移动", "—", ACCENT_GREEN)
        self.card_dup = StatCard("重复跳过", "—", ACCENT_RED)
        self.card_no_act = StatCard("未建档跳过", "—", ACCENT_AMBER)

        for card in (self.card_total, self.card_target, self.card_move, self.card_dup, self.card_no_act):
            layout.addWidget(card)

        return container

    def _build_table_section(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(14, 6, 14, 10)
        layout.setSpacing(0)

        # ── Main tab widget with two real pages ──────────────────────────────
        self.main_tabs = QTabWidget()
        self.main_tabs.setTabPosition(QTabWidget.TabPosition.North)
        layout.addWidget(self.main_tabs)

        # ── Page 1: Move plan sub-tabs + table ──────────────────────────────
        page_move = QWidget()
        page_move_layout = QVBoxLayout(page_move)
        page_move_layout.setContentsMargins(0, 6, 0, 0)
        page_move_layout.setSpacing(0)

        # Filter sub-tabs (visual only — pane hidden)
        self.tab_widget = QTabWidget()
        self.tab_widget.setTabPosition(QTabWidget.TabPosition.North)
        self.tab_widget.setStyleSheet("QTabWidget::pane { border: none; max-height: 0px; }")
        for label in ("全部 (0)", "待移动/已移动 (0)", "重复跳过 (0)", "未建档跳过 (0)"):
            self.tab_widget.addTab(QWidget(), label)
        self.tab_widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.tab_widget.currentChanged.connect(self._filter_table_by_tab)
        page_move_layout.addWidget(self.tab_widget)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["状态", "源演员", "番号目录", "目标分类", "目标演员", "匹配方式", "说明 / 原因"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setDefaultSectionSize(26)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setFrameShape(QFrame.Shape.NoFrame)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.cellDoubleClicked.connect(self._on_table_double_clicked)
        page_move_layout.addWidget(self.table)

        self.main_tabs.addTab(page_move, "归档计划")

        # ── Page 2: Duplicate-actor scan ────────────────────────────────────
        page_dup = QWidget()
        page_dup_layout = QVBoxLayout(page_dup)
        page_dup_layout.setContentsMargins(0, 8, 0, 0)
        page_dup_layout.setSpacing(6)

        # Toolbar for dup scan
        dup_toolbar = QHBoxLayout()
        self.lbl_dup_status = QLabel("扫描归档库，找出同名演员存在于多个分类目录的情况。")
        self.lbl_dup_status.setStyleSheet(f"color: {TEXT_DIM}; font-size: 12px;")
        dup_toolbar.addWidget(self.lbl_dup_status)
        dup_toolbar.addStretch()

        self.btn_manage_ignored = QPushButton("🚫 屏蔽列表 (0)")
        self.btn_manage_ignored.setFixedHeight(30)
        self.btn_manage_ignored.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_manage_ignored.setToolTip("查看或管理已确认非同一人的屏蔽演员组合，列表内的组合不再重复提示")
        self.btn_manage_ignored.setStyleSheet(
            f"QPushButton {{ background-color: {BTN_BROWSE_BG}; color: {TEXT_SECONDARY}; border: 1px solid {BORDER};"
            f" border-radius: 5px; padding: 0 12px; font-weight: 600; font-size: 12px; }}"
            f"QPushButton:hover {{ background-color: {BTN_BROWSE_HOVER}; color: {TEXT_PRIMARY}; }}"
        )
        self.btn_manage_ignored.clicked.connect(self._open_ignored_dup_dialog)
        dup_toolbar.addWidget(self.btn_manage_ignored)

        self.btn_scan_dup = QPushButton("扫描重复演员目录")
        self.btn_scan_dup.setFixedHeight(30)
        self.btn_scan_dup.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_scan_dup.setStyleSheet(
            f"QPushButton {{ background-color: #4a1d7a; color: #e9d5ff; border: none; border-radius: 5px;"
            f" padding: 0 14px; font-weight: 600; font-size: 12px; }}"
            f"QPushButton:hover {{ background-color: #6d28d9; }}"
            f"QPushButton:disabled {{ background-color: {BG_CARD}; color: {TEXT_DIM}; }}"
        )
        self.btn_scan_dup.clicked.connect(self._start_dup_scan)
        dup_toolbar.addWidget(self.btn_scan_dup)
        page_dup_layout.addLayout(dup_toolbar)

        self.dup_table = QTableWidget()
        self.dup_table.setColumnCount(5)
        self.dup_table.setHorizontalHeaderLabels(
            ["统一演员 (主身份)", "实际目录名", "所属分类", "重复诊断特征", "完整目录路径"]
        )
        self.dup_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.dup_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.dup_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.dup_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.dup_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.dup_table.verticalHeader().setDefaultSectionSize(26)
        self.dup_table.verticalHeader().setVisible(False)
        self.dup_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.dup_table.setAlternatingRowColors(True)
        self.dup_table.setShowGrid(False)
        self.dup_table.setFrameShape(QFrame.Shape.NoFrame)
        self.dup_table.cellDoubleClicked.connect(self._on_dup_table_double_clicked)
        self.dup_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.dup_table.customContextMenuRequested.connect(self._show_dup_table_context_menu)
        page_dup_layout.addWidget(self.dup_table)

        self.main_tabs.addTab(page_dup, "重复演员目录 (0)")

        return container

    # ─────────────────────────────────────────────────────── Slots / Logic ───
    def _toggle_stash1_inputs(self, checked: bool):
        self.txt_stash1_url.setEnabled(checked)
        self.txt_stash1_key.setEnabled(checked)
        self.btn_stash1_test.setEnabled(checked)
        if not getattr(self, "_is_loading_settings", False):
            if checked:
                self._test_stash_async(1)
            else:
                self._stash_test_seq[1] = self._stash_test_seq.get(1, 0) + 1
                self._set_stash_status(1, "idle", "")

    def _toggle_stash2_inputs(self, checked: bool):
        self.txt_stash2_url.setEnabled(checked)
        self.txt_stash2_key.setEnabled(checked)
        self.btn_stash2_test.setEnabled(checked)
        if not getattr(self, "_is_loading_settings", False):
            if checked:
                self._test_stash_async(2)
            else:
                self._stash_test_seq[2] = self._stash_test_seq.get(2, 0) + 1
                self._set_stash_status(2, "idle", "")

    def _test_stash_async(self, source_id: int):
        """Asynchronously test Stash connectivity and ApiKey."""
        if source_id == 1:
            url = self.txt_stash1_url.text().strip()
            key = self.txt_stash1_key.text().strip()
            self.btn_stash1_test.setEnabled(False)
        else:
            url = self.txt_stash2_url.text().strip()
            key = self.txt_stash2_key.text().strip()
            self.btn_stash2_test.setEnabled(False)

        self._stash_test_seq[source_id] = self._stash_test_seq.get(source_id, 0) + 1
        seq = self._stash_test_seq[source_id]

        if not url:
            self._set_stash_status(source_id, "failed", "地址未填写")
            if source_id == 1:
                self.btn_stash1_test.setEnabled(self.chk_stash1.isChecked())
            else:
                self.btn_stash2_test.setEnabled(self.chk_stash2.isChecked())
            return

        self._set_stash_status(source_id, "testing", "测试中…")

        worker = StashTesterWorker(source_id, seq, url, key)
        _ACTIVE_TEST_WORKERS.add(worker)
        worker.signals.finished.connect(self._on_stash_test_result)
        worker.start()

    def _set_stash_status(self, source_id: int, state: str, message: str):
        lbl = self.lbl_stash1_status if source_id == 1 else self.lbl_stash2_status
        if state == "testing":
            lbl.setText("⏳ 验证")
            lbl.setStyleSheet(
                "QLabel { color: #f59e0b; font-weight: 500; background-color: rgba(245, 158, 11, 0.12);"
                " border: 1px solid rgba(245, 158, 11, 0.3); border-radius: 5px; font-size: 12px; padding: 0px; }"
            )
            lbl.setToolTip("正在连接并验证 ApiKey…")
            lbl.setVisible(True)
        elif state == "success":
            lbl.setText("🟢 正常")
            lbl.setStyleSheet(
                "QLabel { color: #22c55e; font-weight: 600; background-color: rgba(34, 197, 94, 0.15);"
                " border: 1px solid rgba(34, 197, 94, 0.35); border-radius: 5px; font-size: 12px; padding: 0px; }"
            )
            lbl.setToolTip(f"Stash 源 {source_id} 配置成功: {message}")
            lbl.setVisible(True)
        elif state == "failed":
            lbl.setText("🔴 失败")
            lbl.setStyleSheet(
                "QLabel { color: #ef4444; font-weight: 600; background-color: rgba(239, 68, 68, 0.15);"
                " border: 1px solid rgba(239, 68, 68, 0.35); border-radius: 5px; font-size: 12px; padding: 0px; }"
            )
            lbl.setToolTip(f"Stash 源 {source_id} 验证失败: {message}")
            lbl.setVisible(True)
        else:
            lbl.setText("")
            lbl.setStyleSheet("")
            lbl.setToolTip("")
            lbl.setVisible(False)

    @pyqtSlot(int, int, bool, str)
    def _on_stash_test_result(self, source_id: int, seq: int, is_success: bool, message: str):
        if seq != self._stash_test_seq.get(source_id, 0):
            return
        state = "success" if is_success else "failed"
        self._set_stash_status(source_id, state, message)
        if source_id == 1:
            self.btn_stash1_test.setEnabled(self.chk_stash1.isChecked())
        else:
            self.btn_stash2_test.setEnabled(self.chk_stash2.isChecked())

    def _get_enabled_stash_sources(self) -> list[tuple[str, str]]:
        sources = []
        if self.chk_stash1.isChecked():
            u1 = self.txt_stash1_url.text().strip()
            k1 = self.txt_stash1_key.text().strip()
            if u1:
                sources.append((u1, k1))
        if self.chk_stash2.isChecked():
            u2 = self.txt_stash2_url.text().strip()
            k2 = self.txt_stash2_key.text().strip()
            if u2:
                sources.append((u2, k2))
        return sources

    def _browse_dir(self, line_edit: QLineEdit):
        curr = line_edit.text()
        chosen = QFileDialog.getExistingDirectory(self, "选择文件夹", curr if Path(curr).exists() else "")
        if chosen:
            line_edit.setText(chosen)
            self._save_settings()

    def _browse_excel_file(self):
        curr = self.txt_db.text()
        chosen, _ = QFileDialog.getOpenFileName(
            self, "选择演员别名 Excel 文件", curr if Path(curr).exists() else "", "Excel Files (*.xlsx *.xls)"
        )
        if chosen:
            self.txt_db.setText(chosen)
            self._save_settings()

    def _connect_auto_save(self):
        """Connect UI input signals to auto-save settings and auto-test Stash connections."""
        self.txt_source.editingFinished.connect(self._save_settings)
        self.txt_target.editingFinished.connect(self._save_settings)
        self.txt_db.editingFinished.connect(self._save_settings)
        self.txt_exclude.editingFinished.connect(self._save_settings)
        self.chk_stash1.toggled.connect(self._save_settings)
        self.txt_stash1_url.editingFinished.connect(self._save_settings)
        self.txt_stash1_url.editingFinished.connect(
            lambda: self._test_stash_async(1) if self.chk_stash1.isChecked() else None
        )
        self.txt_stash1_key.editingFinished.connect(self._save_settings)
        self.txt_stash1_key.editingFinished.connect(
            lambda: self._test_stash_async(1) if self.chk_stash1.isChecked() else None
        )
        self.chk_stash2.toggled.connect(self._save_settings)
        self.txt_stash2_url.editingFinished.connect(self._save_settings)
        self.txt_stash2_url.editingFinished.connect(
            lambda: self._test_stash_async(2) if self.chk_stash2.isChecked() else None
        )
        self.txt_stash2_key.editingFinished.connect(self._save_settings)
        self.txt_stash2_key.editingFinished.connect(
            lambda: self._test_stash_async(2) if self.chk_stash2.isChecked() else None
        )
        self.chk_dry_run.toggled.connect(self._save_settings)
        self.chk_clean_empty.toggled.connect(self._save_settings)

    def _save_settings(self):
        """Save current GUI configuration to JSON file."""
        if getattr(self, "_is_loading_settings", False):
            return
        config_path = _get_config_path()
        data = {
            "source_path": self.txt_source.text().strip(),
            "target_path": self.txt_target.text().strip(),
            "db_path": self.txt_db.text().strip(),
            "exclude_dirs": self.txt_exclude.text().strip(),
            "stash1_enabled": self.chk_stash1.isChecked(),
            "stash1_url": self.txt_stash1_url.text().strip(),
            "stash1_key": self.txt_stash1_key.text().strip(),
            "stash2_enabled": self.chk_stash2.isChecked(),
            "stash2_url": self.txt_stash2_url.text().strip(),
            "stash2_key": self.txt_stash2_key.text().strip(),
            "dry_run": self.chk_dry_run.isChecked(),
            "clean_empty": self.chk_clean_empty.isChecked(),
            "ignored_dup_groups": self.ignored_dup_groups,
        }
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug("Archive mover settings saved to %s", config_path)
        except Exception as e:
            logger.warning("Failed to save settings to %s: %s", config_path, e)

    def _load_settings(self):
        """Load GUI configuration from JSON file if available."""
        self._is_loading_settings = True
        try:
            config_path = _get_config_path()
            if not config_path.exists():
                return
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return
            if "source_path" in data and data["source_path"] is not None:
                self.txt_source.setText(str(data["source_path"]))
            if "target_path" in data and data["target_path"] is not None:
                self.txt_target.setText(str(data["target_path"]))
            if "db_path" in data and data["db_path"] is not None:
                self.txt_db.setText(str(data["db_path"]))
            if "exclude_dirs" in data and data["exclude_dirs"] is not None:
                self.txt_exclude.setText(str(data["exclude_dirs"]))

            if "stash1_enabled" in data:
                self.chk_stash1.setChecked(bool(data["stash1_enabled"]))
            if "stash1_url" in data and data["stash1_url"] is not None:
                self.txt_stash1_url.setText(str(data["stash1_url"]))
            if "stash1_key" in data and data["stash1_key"] is not None:
                self.txt_stash1_key.setText(str(data["stash1_key"]))

            if "stash2_enabled" in data:
                self.chk_stash2.setChecked(bool(data["stash2_enabled"]))
            if "stash2_url" in data and data["stash2_url"] is not None:
                self.txt_stash2_url.setText(str(data["stash2_url"]))
            if "stash2_key" in data and data["stash2_key"] is not None:
                self.txt_stash2_key.setText(str(data["stash2_key"]))

            if "dry_run" in data:
                self.chk_dry_run.setChecked(bool(data["dry_run"]))
            if "clean_empty" in data:
                self.chk_clean_empty.setChecked(bool(data["clean_empty"]))
            if "ignored_dup_groups" in data and isinstance(data["ignored_dup_groups"], list):
                self.ignored_dup_groups = data["ignored_dup_groups"]
            logger.debug("Archive mover settings loaded from %s", config_path)
        except Exception as e:
            logger.warning("Failed to load settings from %s: %s", config_path, e)
        finally:
            self._is_loading_settings = False

    def closeEvent(self, event):
        self._save_settings()
        super().closeEvent(event)

    def _parse_exclude_dirs(self) -> list[str]:
        raw = self.txt_exclude.text().strip()
        if not raw:
            return []
        return [p.strip() for p in re.split(r"[,;，；\n]+", raw) if p.strip()]

    def _start_evaluation(self):
        self._save_settings()
        source = self.txt_source.text().strip()
        target = self.txt_target.text().strip()
        db_path = self.txt_db.text().strip()

        if not source or not target:
            QMessageBox.warning(self, "警告", "源暂存目录和目标归档目录不能为空！")
            return

        self.btn_scan.setEnabled(False)
        self.btn_execute.setEnabled(False)
        self.btn_open_report.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self._set_status("正在加载别名库并预扫描目标目录结构…")

        alias_resolver = AliasResolver(
            excel_path=db_path if Path(db_path).exists() else None,
            disjoint_groups=self.ignored_dup_groups,
        )
        if Path(db_path).exists():
            alias_resolver.load_excel()

        # 加载所有启用的 Stash 源 (源 1 + 源 2)
        for s_url, s_key in self._get_enabled_stash_sources():
            alias_resolver.load_stash(s_url, s_key)

        # 连通合并去重 Excel 与多个 Stash 源的全部演员别名
        alias_resolver.consolidate_clusters()

        self.last_alias_resolver = alias_resolver  # keep for dup scan

        mover = ArchiveMover(
            alias_resolver=alias_resolver,
            dry_run=self.chk_dry_run.isChecked(),
            clean_empty_dirs=self.chk_clean_empty.isChecked(),
        )

        self.eval_worker = EvaluationWorker(mover, source, target, exclude_dirs=self._parse_exclude_dirs())
        self.eval_worker.signals.progress.connect(self._on_progress)
        self.eval_worker.signals.finished.connect(self._on_evaluation_finished)
        self.eval_worker.signals.error.connect(self._on_worker_error)
        self.eval_worker.start()

    def _start_execution(self):
        if not self.last_report or not self.last_target_index:
            return

        dry_run = self.chk_dry_run.isChecked()
        items_to_move = [it for it in self.last_report.items if it.status == MoveStatus.READY]

        if not items_to_move:
            QMessageBox.information(self, "提示", "当前没有可移动的项目。")
            return

        if not dry_run:
            ret = QMessageBox.question(
                self,
                "确认正式移动",
                f"当前为【真实执行模式】！\n即将把 {len(items_to_move)} 个番号目录移动到归档区对应演员目录下。\n确定继续吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return

        self.btn_scan.setEnabled(False)
        self.btn_execute.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        mover = ArchiveMover(
            dry_run=dry_run,
            clean_empty_dirs=self.chk_clean_empty.isChecked(),
        )
        self.exec_worker = ExecutionWorker(mover, self.last_report, self.last_target_index)
        self.exec_worker.signals.progress.connect(self._on_progress)
        self.exec_worker.signals.finished.connect(self._on_execution_finished)
        self.exec_worker.signals.error.connect(self._on_worker_error)
        self.exec_worker.start()

    @pyqtSlot(int, int, str)
    def _on_progress(self, pct: int, _total: int, msg: str):
        self.progress_bar.setValue(pct)
        self._set_status(msg)

    @pyqtSlot(object, object)
    def _on_evaluation_finished(self, report: ProcessReport, target_index: TargetIndex):
        self.last_report = report
        self.last_target_index = target_index
        self.btn_scan.setEnabled(True)
        self.progress_bar.setVisible(False)

        report_dir = Path(__file__).resolve().parents[2] / "reports"
        _, html_file = ReportGenerator.save_reports(report, report_dir)
        self.last_html_report = html_file
        self.btn_open_report.setEnabled(True)

        ready_count = report.ready_or_moved_count
        self.btn_execute.setEnabled(ready_count > 0)

        self.card_total.set_value(str(report.total_source_codes))
        self.card_target.set_value(f"{report.total_target_actors} 演员 ({report.total_target_categories} 分类)")
        self.card_move.set_value(str(ready_count))
        self.card_dup.set_value(str(report.duplicate_count))
        self.card_no_act.set_value(str(report.no_actor_count))

        self._set_status(
            f"✅  评估完成 (耗时 {report.scan_time_seconds:.2f}s)  ·  "
            f"可移动 {ready_count} 个  ·  重复跳过 {report.duplicate_count} 个  ·  未建档 {report.no_actor_count} 个",
            ok=True,
        )
        self._render_table()
        # Automatically kick off duplicate-actor scan using already-loaded alias resolver
        self._start_dup_scan(auto=True)

    @pyqtSlot(object, object)
    def _on_execution_finished(self, report: ProcessReport, _target_index: TargetIndex):
        self.last_report = report
        self.btn_scan.setEnabled(True)
        self.btn_execute.setEnabled(False)
        self.progress_bar.setVisible(False)

        report_dir = Path(__file__).resolve().parents[2] / "reports"
        _, html_file = ReportGenerator.save_reports(report, report_dir)
        self.last_html_report = html_file

        moved_count = sum(1 for it in report.items if it.status in (MoveStatus.MOVED, MoveStatus.DRY_RUN_MOVED))
        cleaned_str = f"  ·  清理空目录 {len(report.cleaned_empty_actors)} 个" if report.cleaned_empty_actors else ""
        action = "模拟移动" if report.is_dry_run else "移动"
        self._set_status(f"🎉  {action}完成  ·  处理 {moved_count} 个番号{cleaned_str}", ok=True)
        self._render_table()
        QMessageBox.information(
            self,
            "完成",
            f"{'模拟移动' if report.is_dry_run else '真实移动'}完成！\n成功处理 {moved_count} 个番号{cleaned_str.strip()}。",
        )

    @pyqtSlot(str)
    def _on_worker_error(self, err_msg: str):
        self.btn_scan.setEnabled(True)
        self.btn_execute.setEnabled(True)
        self.progress_bar.setVisible(False)
        self._set_status(f"❌  发生错误: {err_msg}", error=True)
        QMessageBox.critical(self, "错误", f"操作失败:\n{err_msg}")

    def _set_status(self, msg: str, *, ok: bool = False, error: bool = False):
        if error:
            color = ACCENT_RED
        elif ok:
            color = ACCENT_GREEN
        else:
            color = TEXT_DIM
        self.lbl_status.setStyleSheet(f"color: {color}; font-size: 12px; padding: 1px 0;")
        self.lbl_status.setText(msg)

    def _render_table(self):
        if not self.last_report:
            return
        all_items = self.last_report.items
        moved = [it for it in all_items if it.status in (MoveStatus.READY, MoveStatus.MOVED, MoveStatus.DRY_RUN_MOVED)]
        dup = [it for it in all_items if it.status == MoveStatus.SKIP_DUPLICATE]
        no_act = [it for it in all_items if it.status == MoveStatus.SKIP_NO_ACTOR]

        self.tab_widget.setTabText(0, f"全部 ({len(all_items)})")
        self.tab_widget.setTabText(1, f"待移动/已移动 ({len(moved)})")
        self.tab_widget.setTabText(2, f"重复跳过 ({len(dup)})")
        self.tab_widget.setTabText(3, f"未建档跳过 ({len(no_act)})")

        self._filter_table_by_tab(self.tab_widget.currentIndex())

    def _filter_table_by_tab(self, index: int):
        if not self.last_report:
            return
        all_items = self.last_report.items
        if index == 1:
            filtered = [
                it for it in all_items if it.status in (MoveStatus.READY, MoveStatus.MOVED, MoveStatus.DRY_RUN_MOVED)
            ]
        elif index == 2:
            filtered = [it for it in all_items if it.status == MoveStatus.SKIP_DUPLICATE]
        elif index == 3:
            filtered = [it for it in all_items if it.status == MoveStatus.SKIP_NO_ACTOR]
        else:
            filtered = all_items

        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(len(filtered))
        for row, it in enumerate(filtered):
            st_item = QTableWidgetItem(it.status.value)
            if it.status in (MoveStatus.READY, MoveStatus.MOVED, MoveStatus.DRY_RUN_MOVED):
                st_item.setForeground(QColor(ACCENT_GREEN))
            elif it.status == MoveStatus.SKIP_DUPLICATE:
                st_item.setForeground(QColor(ACCENT_RED))
            elif it.status == MoveStatus.SKIP_NO_ACTOR:
                st_item.setForeground(QColor(ACCENT_AMBER))

            self.table.setItem(row, 0, st_item)
            self.table.setItem(row, 1, QTableWidgetItem(it.source_actor))
            self.table.setItem(row, 2, QTableWidgetItem(it.source_code))
            self.table.setItem(row, 3, QTableWidgetItem(it.target_category or "—"))
            self.table.setItem(row, 4, QTableWidgetItem(it.target_actor or "—"))
            self.table.setItem(row, 5, QTableWidgetItem(it.match_type))
            self.table.setItem(row, 6, QTableWidgetItem(it.reason))

            st_item.setData(100, it)
        self.table.setUpdatesEnabled(True)

    def _on_table_double_clicked(self, row: int, _col: int):
        item = self.table.item(row, 0)
        if not item:
            return
        move_item: MoveItem = item.data(100)
        if move_item and move_item.source_path.exists():
            os.startfile(str(move_item.source_path))

    def _open_latest_report(self):
        if self.last_html_report and self.last_html_report.exists():
            webbrowser.open(self.last_html_report.as_uri())

    # ── Duplicate-actor scan ─────────────────────────────────────────────────
    def _update_ignored_btn_label(self):
        if hasattr(self, "btn_manage_ignored"):
            self.btn_manage_ignored.setText(f"🚫 屏蔽列表 ({len(self.ignored_dup_groups)})")

    def _start_dup_scan(self, *, auto: bool = False):
        self._save_settings()
        target = self.txt_target.text().strip()
        if not target:
            if not auto:
                QMessageBox.warning(self, "警告", "请先填写目标归档目录！")
            return

        self.btn_scan_dup.setEnabled(False)
        self.lbl_dup_status.setStyleSheet(f"color: {TEXT_DIM}; font-size: 12px;")
        self.lbl_dup_status.setText("正在扫描归档库并比对演员别名库，检测重复建档…")
        self.dup_table.setRowCount(0)
        self.main_tabs.setTabText(1, "重复演员目录 (扫描中…)")

        db_path = self.txt_db.text().strip()
        stash_sources = self._get_enabled_stash_sources()

        self.dup_worker = DuplicateActorWorker(
            target_path=target,
            exclude_dirs=self._parse_exclude_dirs() or None,
            alias_resolver=self.last_alias_resolver,
            db_path=db_path,
            stash_sources=stash_sources,
            ignored_dup_groups=self.ignored_dup_groups,
        )
        self.dup_worker.signals.finished.connect(self._on_dup_finished)
        self.dup_worker.signals.error.connect(self._on_dup_error)
        self.dup_worker.start()

    @pyqtSlot(list, object)
    def _on_dup_finished(self, duplicates: list, resolver: object):
        self.btn_scan_dup.setEnabled(True)
        if resolver:
            self.last_alias_resolver = resolver

        count = len(duplicates)
        if not duplicates:
            self.main_tabs.setTabText(1, "重复演员目录 (0)")
            self.lbl_dup_status.setStyleSheet(f"color: {ACCENT_GREEN}; font-size: 12px;")
            self.lbl_dup_status.setText("✅ 目标归档库未发现同名或别名重复的演员目录，库容结构整洁。")
            return

        self.main_tabs.setTabText(1, f"⚠️ 重复演员目录 ({count})")
        total_dirs = sum(len(d["entries"]) for d in duplicates)
        self.lbl_dup_status.setStyleSheet(f"color: {ACCENT_AMBER}; font-size: 12px;")
        self.lbl_dup_status.setText(
            f"⚠️ 发现 {count} 位演员存在重复建档（共涉及 {total_dirs} 个归档目录），双击任意行可在资源管理器中定位。"
        )

        # 状态栏轻提示
        curr_status = self.lbl_status.text()
        if "评估完成" in curr_status and "重复/别名演员" not in curr_status:
            self.lbl_status.setText(f"{curr_status}  ·  ⚠️ 归档库检测到 {count} 位重复/别名演员")

        self.dup_table.setUpdatesEnabled(False)
        self.dup_table.setRowCount(total_dirs)

        row = 0
        for d in duplicates:
            canonical_name = d["canonical_name"]
            diag_str = d["diag"]
            entries = d["entries"]

            first = True
            for entry in entries:
                # 列 0: 统一演员名
                if first:
                    name_item = QTableWidgetItem(f"★ {canonical_name}")
                    name_item.setForeground(QColor(ACCENT_AMBER))
                    font = name_item.font()
                    font.setBold(True)
                    name_item.setFont(font)
                else:
                    name_item = QTableWidgetItem("  ↳ 同上")
                    name_item.setForeground(QColor(TEXT_DIM))

                # 存储单行路径 (100)、整组数据 (101)、当前条目 (102)
                name_item.setData(100, entry["path"])
                name_item.setData(101, d)
                name_item.setData(102, entry)
                self.dup_table.setItem(row, 0, name_item)

                # 列 1: 实际目录名
                dir_item = QTableWidgetItem(entry["raw_name"])
                if entry["raw_name"] != canonical_name:
                    dir_item.setForeground(QColor("#a78bfa"))  # 别名目录用浅紫色标出
                self.dup_table.setItem(row, 1, dir_item)

                # 列 2: 分类相对路径
                cat_item = QTableWidgetItem(entry["category"])
                self.dup_table.setItem(row, 2, cat_item)

                # 列 3: 重复诊断特征
                diag_item = QTableWidgetItem(diag_str if first else "")
                if "⚠️" in diag_str:
                    diag_item.setForeground(QColor(ACCENT_AMBER))
                else:
                    diag_item.setForeground(QColor(ACCENT_BLUE))
                self.dup_table.setItem(row, 3, diag_item)

                # 列 4: 完整路径
                path_item = QTableWidgetItem(entry["path"])
                path_item.setForeground(QColor(TEXT_DIM))
                self.dup_table.setItem(row, 4, path_item)

                first = False
                row += 1

        self.dup_table.setUpdatesEnabled(True)

    @pyqtSlot(str)
    def _on_dup_error(self, err_msg: str):
        self.btn_scan_dup.setEnabled(True)
        self.main_tabs.setTabText(1, "重复演员目录 (错误)")
        self.lbl_dup_status.setStyleSheet(f"color: {ACCENT_RED}; font-size: 12px;")
        self.lbl_dup_status.setText(f"扫描失败: {err_msg}")
        QMessageBox.critical(self, "错误", f"重复演员扫描失败:\n{err_msg}")

    def _on_dup_table_double_clicked(self, row: int, _col: int):
        """双击表格行时，同时打开该演员的所有相关重复目录。"""
        item = self.dup_table.item(row, 0)
        if not item:
            return

        group_data = item.data(101)
        if group_data and "entries" in group_data:
            all_entries = group_data["entries"]
            canonical_name = group_data.get("canonical_name", "该演员")
            opened = 0
            for entry in all_entries:
                p = Path(entry.get("path", ""))
                if p.exists():
                    os.startfile(str(p))
                    opened += 1
            if opened:
                self._set_status(f"📂 已在资源管理器中同时打开「{canonical_name}」的全部 {opened} 个相关目录", ok=True)
            return

        single_path = str(item.data(100) or "")
        if not single_path:
            path_item = self.dup_table.item(row, 4)
            if path_item:
                single_path = path_item.text()
        if single_path and Path(single_path).exists():
            os.startfile(single_path)

    def _show_dup_table_context_menu(self, pos):
        """右键点击重复演员表格行，弹出快捷操作与合并菜单。"""
        item = self.dup_table.itemAt(pos)
        if not item:
            return
        row = item.row()
        item0 = self.dup_table.item(row, 0)
        if not item0:
            return

        group_data = item0.data(101)
        curr_entry = item0.data(102)
        if not group_data or not curr_entry:
            return

        canonical_name = group_data.get("canonical_name", "该演员")
        curr_path = curr_entry.get("path", "")
        all_entries = group_data.get("entries", [])
        other_entries = [e for e in all_entries if e.get("path") != curr_path]

        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background-color: {BG_CARD}; color: {TEXT_PRIMARY}; border: 1px solid {BORDER}; padding: 4px; border-radius: 6px; }}"
            f"QMenu::item {{ padding: 6px 20px; border-radius: 4px; font-size: 12px; }}"
            f"QMenu::item:selected {{ background-color: {ACCENT_BLUE}; color: #ffffff; }}"
        )

        act_open_curr = menu.addAction(f"📁 打开当前目录 ({curr_entry.get('category')})")
        act_open_all = menu.addAction(f"📂 同时打开该演员全部目录 ({len(all_entries)} 个)")
        menu.addSeparator()

        act_merge = None
        if other_entries:
            act_merge = menu.addAction(f"🔀 将「{canonical_name}」的其他 {len(other_entries)} 个目录合并到此...")

        unique_names = list(dict.fromkeys(e.get("raw_name", "") for e in all_entries if e.get("raw_name")))
        names_desc = " ≠ ".join(unique_names[:3]) if len(unique_names) > 1 else canonical_name
        act_copy_fp = menu.addAction(f"📋 复制误报信息 ({names_desc})")
        act_ignore = menu.addAction(f"🚫 确认非同一演员：加入屏蔽列表 ({names_desc})")

        action = menu.exec(self.dup_table.viewport().mapToGlobal(pos))
        if action == act_open_curr:
            if Path(curr_path).exists():
                os.startfile(curr_path)
        elif action == act_open_all:
            for e in all_entries:
                p = Path(e.get("path", ""))
                if p.exists():
                    os.startfile(str(p))
        elif act_merge and action == act_merge:
            self._merge_duplicate_actor_dirs(group_data, curr_entry, other_entries)
        elif action == act_copy_fp:
            self._copy_dup_false_positive_info(group_data)
        elif action == act_ignore:
            self._ignore_duplicate_actor_group(group_data)

    def _copy_dup_false_positive_info(self, group_data: dict) -> str:
        """生成选中重复演员组的误报诊断描述文本（含目录路径与示例番号子目录）并复制到剪贴板。"""
        from .scanner import AUXILIARY_DIRS, IGNORED_NAMES

        canonical_name = group_data.get("canonical_name", "该演员")
        diag = group_data.get("diag", "")
        entries = group_data.get("entries", [])

        lines = [
            "下面这组目录被扫描为同一演员（疑似误报），请排查原因：",
            f"- 统一演员名：{canonical_name}",
        ]
        if diag:
            lines.append(f"- 诊断特征：{diag}")
        lines.append("- 涉及目录：")

        for idx, entry in enumerate(entries, start=1):
            raw_name = entry.get("raw_name", "")
            category = entry.get("category", "")
            path_str = entry.get("path", "")
            lines.append(f"  {idx}. [{category} / {raw_name}] {path_str}")

            p = Path(path_str) if path_str else None
            if p and p.exists() and p.is_dir():
                try:
                    sample_children = []
                    for child in sorted(p.iterdir(), key=lambda c: c.name):
                        if not child.is_dir():
                            continue
                        low_name = child.name.lower()
                        if low_name in IGNORED_NAMES or low_name in AUXILIARY_DIRS:
                            continue
                        sample_children.append(str(child))
                        if len(sample_children) >= 2:
                            break
                    for sample_path in sample_children:
                        lines.append(f"     示例番号路径：{sample_path}")
                except OSError:
                    pass

        text = "\n".join(lines)
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
        self._set_status(f"📋 已复制「{canonical_name}」的误报描述与路径到剪贴板，可直接粘贴给 AI 分析", ok=True)
        return text

    def _ignore_duplicate_actor_group(self, group_data: dict):
        """将当前选中的重复演员组加入屏蔽列表（确认不是同一人），后续不再扫描提示。"""
        entries = group_data.get("entries", [])
        if not entries:
            return
        unique_names = sorted({e.get("raw_name", "") for e in entries if e.get("raw_name")})
        unique_paths = sorted({e.get("path", "") for e in entries if e.get("path")})
        cats_desc = " | ".join(f"{e.get('category', '')}/{e.get('raw_name', '')}" for e in entries[:4])
        if len(unique_names) >= 2:
            label = f"{' ≠ '.join(unique_names)} ({cats_desc})"
        else:
            label = f"{unique_names[0] if unique_names else '同名不同人'} ({cats_desc})"

        rule = {
            "names": unique_names if len(unique_names) >= 2 else [],
            "paths": unique_paths,
            "label": label,
        }
        self.ignored_dup_groups.append(rule)
        if self.last_alias_resolver is not None:
            self.last_alias_resolver.set_disjoint_groups(self.ignored_dup_groups)
        self._update_ignored_btn_label()
        self._save_settings()
        self._set_status(f"🚫 已加入屏蔽列表：{label}（后续扫描将不再作为同一演员提示）", ok=True)
        self._start_dup_scan(auto=True)

    def _open_ignored_dup_dialog(self):
        """弹出屏蔽列表管理窗口，支持查看、手动添加撞名组合、或移除已有屏蔽项。"""
        dlg = QDialog(self)
        dlg.setWindowTitle("管理非同一演员屏蔽列表")
        dlg.resize(580, 380)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        tip = QLabel(
            "以下演员/目录组合已被确认为【同名不同人 / 别名误关联】，"
            "在重复演员目录扫描与归档移动评估时将不再把她们视为同一演员："
        )
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(tip)

        list_widget = QListWidget()
        list_widget.setStyleSheet(
            f"QListWidget {{ background-color: {BG_WIDGET}; border: 1px solid {BORDER}; border-radius: 6px; padding: 4px; color: {TEXT_PRIMARY}; font-size: 12px; }}"
            f"QListWidget::item {{ padding: 6px 8px; border-radius: 4px; }}"
            f"QListWidget::item:selected {{ background-color: {ROW_SELECTED}; color: #ffffff; }}"
        )
        layout.addWidget(list_widget)

        changed = False

        def _refresh_list():
            list_widget.clear()
            for idx, ig in enumerate(self.ignored_dup_groups):
                lbl_text = ig.get("label") or " ≠ ".join(ig.get("names", [])) or " | ".join(ig.get("paths", []))
                it = QListWidgetItem(f"{idx + 1}.  {lbl_text}")
                it.setData(Qt.ItemDataRole.UserRole, idx)
                list_widget.addItem(it)

        _refresh_list()

        btn_bar = QHBoxLayout()
        btn_add = QPushButton("➕ 手动添加非同一人组合")
        btn_add.setFixedHeight(30)
        btn_add.setCursor(Qt.CursorShape.PointingHandCursor)

        btn_del = QPushButton("🗑️ 移除选中项")
        btn_del.setFixedHeight(30)
        btn_del.setCursor(Qt.CursorShape.PointingHandCursor)

        btn_close = QPushButton("关闭")
        btn_close.setFixedHeight(30)
        btn_close.setFixedWidth(80)
        btn_close.setCursor(Qt.CursorShape.PointingHandCursor)

        def _on_add():
            nonlocal changed
            text, ok = QInputDialog.getText(
                dlg,
                "添加非同一演员屏蔽组合",
                "请输入需要隔离的 2 个或多个演员名（用逗号分隔，例如：北見唯奈, かわいまゆ）：",
            )
            if not ok or not text.strip():
                return
            names = [p.strip() for p in re.split(r"[,，、/|]+", text.strip()) if p.strip()]
            unique_names = list(dict.fromkeys(names))
            if len(unique_names) < 2:
                QMessageBox.warning(dlg, "提示", "请至少输入 2 个不同的演员名称（用逗号分隔）。")
                return
            self.ignored_dup_groups.append(
                {
                    "names": unique_names,
                    "paths": [],
                    "label": " ≠ ".join(unique_names),
                }
            )
            changed = True
            _refresh_list()

        def _on_del():
            nonlocal changed
            curr = list_widget.currentItem()
            if not curr:
                return
            idx = curr.data(Qt.ItemDataRole.UserRole)
            if isinstance(idx, int) and 0 <= idx < len(self.ignored_dup_groups):
                self.ignored_dup_groups.pop(idx)
                changed = True
                _refresh_list()

        btn_add.clicked.connect(_on_add)
        btn_del.clicked.connect(_on_del)
        btn_close.clicked.connect(dlg.accept)

        btn_bar.addWidget(btn_add)
        btn_bar.addWidget(btn_del)
        btn_bar.addStretch()
        btn_bar.addWidget(btn_close)
        layout.addLayout(btn_bar)

        dlg.exec()

        if changed:
            if self.last_alias_resolver is not None:
                self.last_alias_resolver.set_disjoint_groups(self.ignored_dup_groups)
            self._update_ignored_btn_label()
            self._save_settings()
            if self.txt_target.text().strip():
                self._start_dup_scan(auto=True)

    def _merge_duplicate_actor_dirs(self, group_data: dict, target_entry: dict, source_entries: list[dict]):
        """将同名/别名演员的其他目录下的番号移动合并到选中的目标目录，并清理源空目录。
        规则：
        1. 若目标目录已存在同名番号目录，提醒用户查看同名目录，同时停止操作；
        2. 若其上层分类目录也已空置，不需要把上层分类目录删除，只清理空的源演员目录。
        """
        canonical_name = group_data.get("canonical_name", "该演员")
        target_path = Path(target_entry["path"])
        target_cat = target_entry["category"]

        if not target_path.exists():
            QMessageBox.warning(self, "错误", f"目标保留目录不存在:\n{target_path}")
            return

        from .scanner import IGNORED_NAMES

        # ── 1. 冲突预检：检查目标目录是否存在同名番号 ───────────────────
        conflicts = []
        for s in source_entries:
            src_p = Path(s["path"])
            if not src_p.exists():
                continue
            for child in src_p.iterdir():
                if child.name.lower() in IGNORED_NAMES:
                    continue
                dest = target_path / child.name
                if dest.exists():
                    conflicts.append((child.name, child, dest, s["category"]))

        # 如果检测到同名番号目录，提醒用户查看同名目录并立即停止操作！
        if conflicts:
            conflict_lines = []
            for name, src_item, dest_item, _cat in conflicts[:8]:
                conflict_lines.append(f"• 番号: 【{name}】\n  源端位置: {src_item}\n  目标已存在: {dest_item}")
            if len(conflicts) > 8:
                conflict_lines.append(f"• ... 另外还有 {len(conflicts) - 8} 个同名番号冲突")

            conflict_text = "\n\n".join(conflict_lines)

            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("检测到同名番号 - 操作已终止")
            box.setText(
                f"目标保留目录中已存在 {len(conflicts)} 个同名番号目录，合并操作已安全终止！\n\n"
                f"为避免覆盖破坏或数据混乱，系统未执行任何移动操作。\n"
                f"请点击下方按钮打开同名目录对比视频文件，人工处理后再进行合并。\n\n"
                f"冲突清单:\n{conflict_text}"
            )
            btn_open_dirs = box.addButton("打开同名目录对比", QMessageBox.ButtonRole.ActionRole)
            box.addButton("关闭", QMessageBox.ButtonRole.RejectRole)
            box.exec()

            if box.clickedButton() == btn_open_dirs:
                # 自动在资源管理器中打开第一组冲突的源目录和目标目录供用户比对
                first_src = conflicts[0][1]
                first_dest = conflicts[0][2]
                if first_dest.exists():
                    os.startfile(str(first_dest))
                if first_src.exists():
                    os.startfile(str(first_src))

            self._set_status(
                f"⚠️ 演员「{canonical_name}」合并终止: 发现 {len(conflicts)} 个同名番号冲突，请先核对",
                ok=False,
            )
            return

        # ── 2. 无冲突时弹出确认提示 ─────────────────────────────────────
        sources_info = []
        for s in source_entries:
            p = Path(s["path"])
            count = len(list(p.iterdir())) if p.exists() else 0
            sources_info.append(f"• 【{s['category']}】 {s['raw_name']} ({count} 个项目)\n  路径: {p}")

        sources_text = "\n".join(sources_info)
        confirm_msg = (
            f"确定要执行演员目录合并吗？\n\n"
            f"【目标保留目录】:\n"
            f"• 【{target_cat}】 {target_entry['raw_name']}\n"
            f"  路径: {target_path}\n\n"
            f"【将被合并并清理的源目录】 ({len(source_entries)} 个):\n"
            f"{sources_text}\n\n"
            f"【合并规则】:\n"
            f"1. 经预检，未发现同名冲突番号；\n"
            f"2. 将源目录下的所有番号子目录移动到目标保留目录下；\n"
            f"3. 移动完成后，仅清理/删除源端的空演员目录（上层分类目录始终保留）。\n\n"
            f"确认立即执行合并吗？"
        )

        ret = QMessageBox.question(
            self,
            f"确认合并演员目录 - {canonical_name}",
            confirm_msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return

        moved_codes = 0
        cleaned_dirs = 0
        errors = []

        for s in source_entries:
            src_p = Path(s["path"])
            if not src_p.exists():
                continue

            try:
                for child in list(src_p.iterdir()):
                    if child.name.lower() in IGNORED_NAMES:
                        try:
                            if child.is_dir():
                                shutil.rmtree(str(child), ignore_errors=True)
                            else:
                                child.unlink()
                        except Exception:
                            pass
                        continue

                    dest = target_path / child.name
                    shutil.move(str(child), str(dest))
                    moved_codes += 1

                # 检查并清理源演员目录（仅清理空的源演员目录，不删除上层分类目录）
                remaining = [f for f in src_p.iterdir() if f.name.lower() not in IGNORED_NAMES]
                if not remaining:
                    shutil.rmtree(str(src_p), ignore_errors=True)
                    cleaned_dirs += 1
            except Exception as e:
                errors.append(f"处理目录 {src_p.name} 时出错: {e}")

        if errors:
            err_text = "\n".join(errors[:5])
            QMessageBox.warning(
                self,
                "合并完成 (存在部分警告)",
                f"已移动 {moved_codes} 个番号目录，清理了 {cleaned_dirs} 个源目录。\n\n部分目录处理出错:\n{err_text}",
            )
        else:
            QMessageBox.information(
                self,
                "合并成功",
                f"✅ 演员「{canonical_name}」合并完成！\n\n"
                f"• 共移动 {moved_codes} 个番号目录至目标保留目录\n"
                f"• 成功清理 {cleaned_dirs} 个空的源演员目录（分类目录已完整保留）",
            )

        self._set_status(f"✅ 演员「{canonical_name}」目录合并完成，共移动 {moved_codes} 个项目", ok=True)

        # 自动重新扫描刷新重复演员列表
        self._start_dup_scan(auto=True)


# ── Entry point ───────────────────────────────────────────────────────────────
def run_gui():
    try:
        userdata_dir = Path(__file__).resolve().parents[2] / "userdata"
        userdata_dir.mkdir(parents=True, exist_ok=True)
        log_file = userdata_dir / "archive_mover.log"
        handlers: list[logging.Handler] = [logging.FileHandler(log_file, encoding="utf-8")]
        if sys.stderr is not None:
            handlers.append(logging.StreamHandler())
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            handlers=handlers,
        )
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Base dark palette so native widgets also dark-ify
    palette = QPalette()
    dark = QColor(BG_DEEP)
    mid = QColor(BG_CARD)
    text = QColor(TEXT_PRIMARY)
    palette.setColor(QPalette.ColorRole.Window, dark)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, QColor(BG_WIDGET))
    palette.setColor(QPalette.ColorRole.AlternateBase, mid)
    palette.setColor(QPalette.ColorRole.ToolTipBase, mid)
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, mid)
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ROW_SELECTED))
    palette.setColor(QPalette.ColorRole.HighlightedText, text)
    palette.setColor(QPalette.ColorRole.Mid, QColor(BORDER))
    palette.setColor(QPalette.ColorRole.Dark, QColor(BG_DEEP))
    app.setPalette(palette)

    app.setStyleSheet(_build_qss())

    font = QFont("Microsoft YaHei", 9)
    app.setFont(font)

    # Set Windows taskbar AppUserModelID to ensure taskbar uses the dedicated app icon
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("mdcx.archive.mover.gui")
    except Exception:
        pass

    if APP_ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(APP_ICON_PATH)))

    window = ArchiveMoverWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(run_gui())
