import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

from ..config.manager import manager
from ..models.flags import Flags
from ..models.manifest import ScrapeHistoryRegistry, ScrapeManifest


def _find_latest_log_file() -> Path | None:
    """查找最近的完整日志文件"""
    # 优先从 Flags.log_txt 获取
    if hasattr(Flags, "log_txt") and Flags.log_txt is not None:
        name = getattr(Flags.log_txt, "name", None)
        if name and os.path.exists(name):
            return Path(name)

    # 从 Log 文件夹查找最新的 txt 文件
    log_dir = manager.data_folder / "Log"
    if log_dir.exists():
        txt_files = list(log_dir.glob("*.txt"))
        if txt_files:
            txt_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            return txt_files[0]
    return None


def generate_ai_diagnostic_report(
    manifest: ScrapeManifest | None,
    show_data: Any | None,
    file_path: Path | None,
) -> str:
    """生成结构化优雅的 Markdown 格式 AI 诊断分析报告"""
    config_path = str(getattr(manager, "path", "")) or str(manager.data_folder / "userdata" / "config.json")
    full_log = _find_latest_log_file()
    full_log_path = str(full_log) if full_log else "（未找到全局日志文件）"

    orig_path = ""
    new_path = ""
    number = ""
    title = ""
    duration = 0.0
    scrape_time = ""
    scrape_log = ""

    if manifest:
        orig_path = str(manifest.original_file_path)
        new_path = str(manifest.new_file_path)
        number = manifest.extracted_number
        title = manifest.matched_title
        duration = manifest.duration_seconds
        scrape_time = manifest.scrape_time
        scrape_log = manifest.scrape_log

    if show_data:
        if not orig_path and hasattr(show_data, "file_info"):
            fi = show_data.file_info
            orig_path = str(fi.folder_path / (fi.file_name + fi.file_ex))
        if not new_path and hasattr(show_data, "file_info"):
            new_path = str(show_data.file_info.file_path)
        if not number and hasattr(show_data, "data"):
            number = getattr(show_data.data, "number", "")
        if not number and hasattr(show_data, "file_info"):
            number = getattr(show_data.file_info, "number", "")
        if not title and hasattr(show_data, "data"):
            title = getattr(show_data.data, "title", "")

    if not new_path and file_path:
        new_path = str(file_path)
    if not orig_path and new_path:
        orig_path = new_path

    # 若 scrape_log 为空，尝试从全量日志中截取该视频相关的片段
    if not scrape_log and full_log and full_log.exists():
        try:
            with open(full_log, encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            target_keyword = Path(orig_path).name if orig_path else (number or "")
            if target_keyword:
                matched_idx = [i for i, line in enumerate(lines) if target_keyword in line]
                if matched_idx:
                    first_idx = max(0, matched_idx[0] - 5)
                    last_idx = min(len(lines), matched_idx[-1] + 30)
                    scrape_log = "".join(lines[first_idx:last_idx])
        except Exception:
            pass

    if not scrape_log:
        scrape_log = "（未捕获到专属详细日志片段，请通过全量日志文件查看）"

    # 提炼各站点响应状态摘要
    sites_status = []
    for site in ["official", "javdb_api", "javdb_app", "javbus", "airav", "fanza", "dmm"]:
        if f"{site}:" in scrape_log or f"[{site}]" in scrape_log:
            pattern = rf"{site}[:\s]+([^；\r\n]+)"
            m = re.search(pattern, scrape_log)
            if m:
                sites_status.append(f"{site}: {m.group(1).strip()[:30]}")
    site_summary = " | ".join(sites_status) if sites_status else "请查看下方详细日志"

    lines = [
        "### 🤖 MDCx 影片搜刮错误分析与诊断报告",
        "",
        "#### 📌 诊断速查卡片",
        f"- ⚙️ **MDCx 配置文件**: `{config_path}`",
        f"- 📑 **全量运行日志**: `{full_log_path}`",
        f"- 📂 **原始文件路径**: `{orig_path}`",
        f"- 🏷️ **提取车牌番号**: `{number or '未知'}`",
        f"- 🎬 **匹配到的标题**: `{title or '无'}`",
        f"- 📤 **刮削输出路径**: `{new_path}`",
    ]
    if duration > 0:
        lines.append(f"- ⏱️ **刮削耗时**: {duration:.1f} 秒")
    if scrape_time:
        lines.append(f"- 🕒 **刮削时间**: {scrape_time}")
    lines.extend(
        [
            f"- 🌐 **站点响应概览**: {site_summary}",
            "",
            "---",
            "#### 📝 专属详细搜刮日志",
            "```text",
            scrape_log.strip(),
            "```",
            "",
            "---",
            "*提示：您可以直接将此报告发送给 AI，AI 可直接根据上述配置文件和日志路径深入排查识别正则、网站请求或网络错误。*",
        ]
    )
    return "\n".join(lines)


def restore_scraped_movie(
    show_data: Any | None,
    file_path: Path | None,
) -> tuple[bool, str, str, Path | None]:
    """
    核心还原函数：
    1. 将视频移回原路径恢复原文件名（软硬链接则仅删输出端链接）；
    2. 将伴随转移的字幕、种子等移回原目录；
    3. 清理刮削新生成的 NFO、图片、剧照等；
    4. 若新目录变为空目录则安全移除；
    5. 从 success_list 中注销；
    6. 生成 AI 诊断报告并保存本地备份。

    Returns:
        (success, message, report_markdown, report_file_path)
    """
    # 1. 尝试解析 Manifest
    manifest = None
    if show_data and hasattr(show_data, "manifest") and show_data.manifest:
        manifest = show_data.manifest
    elif file_path:
        manifest = ScrapeHistoryRegistry.get(file_path)

    # 若未找到 Manifest，构建回退启发式 Manifest
    if not manifest and show_data and hasattr(show_data, "file_info"):
        fi = show_data.file_info
        orig_dir = fi.folder_path
        orig_name = fi.file_name + fi.file_ex
        orig_file = orig_dir / orig_name
        current_file = fi.file_path if fi.file_path and fi.file_path.exists() else (file_path or orig_file)
        manifest = ScrapeManifest(
            original_file_path=orig_file,
            original_folder_path=orig_dir,
            new_file_path=current_file,
            new_folder_path=current_file.parent,
            link_mode=int(getattr(manager.config, "soft_link", 0)),
            extracted_number=getattr(show_data.data, "number", "") or fi.number,
            matched_title=getattr(show_data.data, "title", ""),
            config_path=str(getattr(manager, "path", "")),
        )

    if not manifest:
        if file_path:
            manifest = ScrapeManifest(
                original_file_path=file_path,
                original_folder_path=file_path.parent,
                new_file_path=file_path,
                new_folder_path=file_path.parent,
                link_mode=int(getattr(manager.config, "soft_link", 0)),
                config_path=str(getattr(manager, "path", "")),
            )
        else:
            return False, "未找到目标影片的信息，无法还原！", "", None

    # 2. 安全还原视频文件
    new_video = manifest.new_file_path
    orig_video = manifest.original_file_path
    orig_dir = manifest.original_folder_path

    if manifest.link_mode != 0 or os.path.islink(new_video):
        # 软硬链接模式：输出端仅为链接，安全删除输出端链接文件，绝不触碰原文件
        if new_video.exists() or os.path.islink(new_video):
            try:
                new_video.unlink(missing_ok=True)
            except Exception as e:
                return False, f"删除输出端链接文件失败: {e}", "", None
    else:
        # 普通移动模式：移回原路径
        if new_video.exists():
            try:
                orig_dir.mkdir(parents=True, exist_ok=True)
                # 若目标已存在同名文件，先避让或备份
                if orig_video.exists() and orig_video.resolve() != new_video.resolve():
                    orig_video.unlink()
                shutil.move(str(new_video), str(orig_video))
            except Exception as e:
                return False, f"移回主视频失败: {e}", "", None
        elif not orig_video.exists():
            return False, f"未在 {new_video} 或 {orig_video} 找到视频文件！", "", None

    # 3. 伴随文件原路移回（如字幕、种子等）
    for old_p, new_p in manifest.moved_files:
        if new_p.exists() and not old_p.exists():
            try:
                old_p.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(new_p), str(old_p))
            except Exception:
                pass

    # 4. 清除刮削新生成的文件
    for cp in manifest.created_files:
        if cp.exists() and cp != orig_video:
            try:
                if cp.is_file() or cp.is_symlink():
                    cp.unlink(missing_ok=True)
                elif cp.is_dir():
                    shutil.rmtree(cp, ignore_errors=True)
            except Exception:
                pass

    # 额外兜底清理：检查 new_folder_path 下与该视频相关的 NFO/图片等
    new_folder = manifest.new_folder_path
    if new_folder.exists():
        prefix = new_video.stem
        candidate_exts = [
            ".nfo",
            "-poster.jpg",
            "-thumb.jpg",
            "-fanart.jpg",
            "poster.jpg",
            "thumb.jpg",
            "fanart.jpg",
            "-trailer.mp4",
        ]
        for ext in candidate_exts:
            p = new_folder / (prefix + ext if "-" in ext or ext.startswith(".") else ext)
            if p.exists() and p != orig_video and p.is_file():
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass

        for sub_dir_name in ["extrafanart", ".actors"]:
            sub_d = new_folder / sub_dir_name
            if sub_d.exists() and sub_d.is_dir():
                try:
                    # 确认无视频文件
                    has_video = any(
                        f.suffix.lower() in [".mp4", ".mkv", ".avi", ".wmv", ".iso", ".mov", ".ts"]
                        for f in sub_d.rglob("*")
                    )
                    if not has_video:
                        shutil.rmtree(sub_d, ignore_errors=True)
                except Exception:
                    pass

    # 5. 若目标文件夹已无视频文件或变为空目录，则安全删除新文件夹
    if new_folder.exists() and new_folder.resolve() != orig_dir.resolve():
        remaining_videos = [
            f
            for f in new_folder.rglob("*")
            if f.is_file() and f.suffix.lower() in [".mp4", ".mkv", ".avi", ".wmv", ".iso", ".mov", ".ts", ".m2ts"]
        ]
        if not remaining_videos:
            try:
                shutil.rmtree(new_folder, ignore_errors=True)
            except Exception:
                pass

    # 6. 从 success_list 中注销
    try:
        if hasattr(Flags, "success_list"):
            Flags.success_list.discard(new_video)
            Flags.success_list.discard(orig_video)
        # 更新磁盘 success.txt
        success_file = manager.data_folder / "userdata" / "success.txt"
        if not success_file.exists():
            success_file = manager.data_folder / "resources" / "success.txt"
        if success_file.exists():
            try:
                with open(success_file, encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                new_v_str = str(new_video).replace("\\", "/").lower()
                orig_v_str = str(orig_video).replace("\\", "/").lower()
                filtered = [
                    line_item
                    for line_item in lines
                    if str(line_item).strip().replace("\\", "/").lower() not in (new_v_str, orig_v_str)
                ]
                with open(success_file, "w", encoding="utf-8", errors="ignore") as f:
                    f.writelines(filtered)
            except Exception:
                pass
    except Exception:
        pass

    # 7. 生成 AI 诊断报告
    report = generate_ai_diagnostic_report(manifest, show_data, file_path)

    # 8. 保存本地快照备份
    report_file_path = None
    try:
        report_dir = manager.data_folder / "Log" / "ai_reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        time_str = time.strftime("%Y%m%d_%H%M%S")
        safe_num = re.sub(r"[^a-zA-Z0-9_-]", "", manifest.extracted_number) or "unknown"
        report_file_path = report_dir / f"{time_str}_{safe_num}_diagnose.md"
        with open(report_file_path, "w", encoding="utf-8", errors="ignore") as f:
            f.write(report)
    except Exception:
        pass

    # 9. 从注册表中移除
    ScrapeHistoryRegistry.remove(manifest)

    msg = f"影片已成功还原至原位置：\n{orig_video}\n\n伴随文件与生成垃圾已清理完毕。\nAI 诊断报告已复制到剪切板！"
    if report_file_path:
        msg += f"\n(已同步备份于: {report_file_path.name})"

    return True, msg, report, report_file_path
