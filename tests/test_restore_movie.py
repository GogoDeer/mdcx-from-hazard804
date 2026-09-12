from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mdcx.config.manager import manager
from mdcx.core.restore import generate_ai_diagnostic_report, restore_scraped_movie
from mdcx.models.flags import Flags
from mdcx.models.manifest import ScrapeHistoryRegistry, ScrapeManifest


@pytest.fixture(autouse=True)
def clean_registry(tmp_path):
    ScrapeHistoryRegistry.clear()
    original_data_folder = manager.data_folder
    manager.data_folder = tmp_path
    (tmp_path / "userdata").mkdir(parents=True, exist_ok=True)
    (tmp_path / "Log" / "ai_reports").mkdir(parents=True, exist_ok=True)
    yield
    manager.data_folder = original_data_folder
    ScrapeHistoryRegistry.clear()


def test_restore_scraped_movie_normal_mode(tmp_path):
    # 准备原始目录与文件
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    orig_video = input_dir / "test_movie.mp4"
    orig_video.write_bytes(b"dummy video data")
    orig_sub = input_dir / "test_movie.zh.srt"
    orig_sub.write_text("subtitle content", encoding="utf-8")
    orig_torrent = input_dir / "test_movie.torrent"
    orig_torrent.write_bytes(b"torrent data")

    # 模拟刮削后输出目录与文件
    output_dir = tmp_path / "output" / "ACTOR" / "ABC-123"
    output_dir.mkdir(parents=True)
    new_video = output_dir / "ABC-123.mp4"
    new_sub = output_dir / "ABC-123.zh.srt"
    new_torrent = output_dir / "ABC-123.torrent"
    nfo_file = output_dir / "ABC-123.nfo"
    poster_file = output_dir / "ABC-123-poster.jpg"
    thumb_file = output_dir / "ABC-123-thumb.jpg"
    fanart_file = output_dir / "ABC-123-fanart.jpg"

    # 移动文件模拟刮削
    orig_video.rename(new_video)
    orig_sub.rename(new_sub)
    orig_torrent.rename(new_torrent)
    nfo_file.write_text("<movie>info</movie>", encoding="utf-8")
    poster_file.write_bytes(b"poster")
    thumb_file.write_bytes(b"thumb")
    fanart_file.write_bytes(b"fanart")

    # 建立 extrafanart 目录
    extra_dir = output_dir / "extrafanart"
    extra_dir.mkdir()
    (extra_dir / "fanart1.jpg").write_bytes(b"extra fanart")

    # 构建 Manifest
    manifest = ScrapeManifest(
        original_file_path=orig_video,
        original_folder_path=input_dir,
        new_file_path=new_video,
        new_folder_path=output_dir,
        link_mode=0,
        moved_files=[(orig_sub, new_sub), (orig_torrent, new_torrent)],
        created_files=[nfo_file, poster_file, thumb_file, fanart_file],
        created_dirs=[output_dir],
        extracted_number="ABC-123",
        matched_title="测试影片标题",
        scrape_log="[official] 抓取失败\n[javdb] 200 OK 匹配成功",
        duration_seconds=5.2,
        scrape_time="2026-09-10 12:00:00",
        config_path=str(tmp_path / "userdata" / "config.json"),
        full_log_path=str(tmp_path / "Log" / "all.txt"),
    )
    ScrapeHistoryRegistry.save(manifest)

    # 模拟 success.txt 和 Flags.success_list
    success_file = tmp_path / "userdata" / "success.txt"
    success_file.write_text(f"{new_video}\n", encoding="utf-8")
    Flags.success_list.add(new_video)

    show_data = MagicMock()
    show_data.manifest = manifest

    # 执行还原
    success, msg, report, report_path = restore_scraped_movie(show_data, new_video)

    assert success is True
    assert "已成功还原至原位置" in msg

    # 验证原视频和伴随文件已复原
    assert orig_video.exists()
    assert orig_video.read_bytes() == b"dummy video data"
    assert orig_sub.exists()
    assert orig_sub.read_text(encoding="utf-8") == "subtitle content"
    assert orig_torrent.exists()

    # 验证新生成的文件与目录已被清除
    assert not new_video.exists()
    assert not nfo_file.exists()
    assert not poster_file.exists()
    assert not extra_dir.exists()
    assert not output_dir.exists()

    # 验证 success_list 已注销
    assert new_video not in Flags.success_list
    assert (
        str(new_video).replace("\\", "/").lower()
        not in success_file.read_text(encoding="utf-8").replace("\\", "/").lower()
    )

    # 验证 AI 诊断报告包含配置文件与日志路径
    assert "### 🤖 MDCx 影片搜刮错误分析与诊断报告" in report
    assert "⚙️ **MDCx 配置文件**" in report
    assert "📑 **全量运行日志**" in report
    assert "ABC-123" in report
    assert "测试影片标题" in report
    assert report_path is not None
    assert report_path.exists()


def test_restore_scraped_movie_link_mode(tmp_path):
    # 软链接模式测试：原文件必须绝对保持完好，仅删除输出端
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    orig_video = input_dir / "linked_movie.mp4"
    orig_video.write_bytes(b"original real video content")

    output_dir = tmp_path / "output" / "LINKED"
    output_dir.mkdir(parents=True)
    new_video = output_dir / "LINKED.mp4"
    new_video.write_bytes(b"simulated link or symlink")
    nfo_file = output_dir / "LINKED.nfo"
    nfo_file.write_text("<movie/>", encoding="utf-8")

    manifest = ScrapeManifest(
        original_file_path=orig_video,
        original_folder_path=input_dir,
        new_file_path=new_video,
        new_folder_path=output_dir,
        link_mode=1,  # 软链接模式
        created_files=[nfo_file],
        created_dirs=[output_dir],
        extracted_number="LINK-001",
    )
    ScrapeHistoryRegistry.save(manifest)

    show_data = MagicMock()
    show_data.manifest = manifest

    success, msg, report, _ = restore_scraped_movie(show_data, new_video)

    assert success is True
    # 原文件必须完好无损
    assert orig_video.exists()
    assert orig_video.read_bytes() == b"original real video content"
    # 输出端文件已被清除
    assert not new_video.exists()
    assert not nfo_file.exists()


def test_generate_ai_diagnostic_report_fields(tmp_path):
    report = generate_ai_diagnostic_report(
        manifest=None,
        show_data=None,
        file_path=Path("D:/Incoming/Test-999.mp4"),
    )
    assert "### 🤖 MDCx 影片搜刮错误分析与诊断报告" in report
    assert "⚙️ **MDCx 配置文件**" in report
    assert "📑 **全量运行日志**" in report
    assert "Test-999.mp4" in report
