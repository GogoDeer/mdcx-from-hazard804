"""回归测试：读取模式（main_mode=4）未勾选「重新整理分类（HAS_NFO_UPDATE）」时，
严禁将已整理好的影片、NFO、图片或字幕错误移动到 success_folder（如 Media\\Input）。
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from mdcx.config.enums import ReadMode
from mdcx.models.enums import FileMode
from mdcx.models.flags import Flags
from mdcx.models.model_types import CrawlersResult, FileInfo, OtherInfo


def _setup_organized_movie(tmp_path: Path) -> tuple[Path, Path, FileInfo]:
    """构建已整理好的影片目录（模拟 JAV_output/ActorA/ABC-123）与独立输出目录（模拟 Media/Input）。"""
    movie_dir = tmp_path / "JAV_output" / "ActorA" / "ABC-123"
    movie_dir.mkdir(parents=True)
    media_input = tmp_path / "Media" / "Input"
    media_input.mkdir(parents=True)

    video_path = movie_dir / "ABC-123-C.mp4"
    video_path.write_bytes(b"FAKE_VIDEO_DATA")
    (movie_dir / "ABC-123-C.nfo").write_text(
        "<movie><num>ABC-123</num><title>Old Title</title></movie>", encoding="utf-8"
    )
    (movie_dir / "poster.jpg").write_bytes(b"OLD_POSTER")
    (movie_dir / "thumb.jpg").write_bytes(b"OLD_THUMB")
    (movie_dir / "fanart.jpg").write_bytes(b"OLD_FANART")
    (movie_dir / "ABC-123-C.chs.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nsub\n", encoding="utf-8")

    file_info = FileInfo.empty()
    file_info.number = "ABC-123"
    file_info.mosaic = "有码"
    file_info.file_path = video_path
    file_info.folder_path = movie_dir
    file_info.file_name = "ABC-123-C"
    file_info.file_ex = ".mp4"
    file_info.file_show_name = "ABC-123-C.mp4"
    file_info.file_show_path = video_path
    file_info.has_sub = True
    file_info.sub_list = [".chs.srt"]

    return movie_dir, media_input, file_info


@pytest.mark.asyncio
async def test_read_mode_update_nfo_only_keeps_files_in_place(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """读取模式仅勾选 READ_UPDATE_NFO（未勾选 HAS_NFO_UPDATE）时：
    即使全局开启了 success_file_move=True、success_file_rename=True，
    也必须在原目录就地更新 NFO，绝不能将影片、图片、字幕搬移到 success_folder。
    """
    from mdcx.core import scraper as scraper_module

    Flags.reset()
    movie_dir, media_input, file_info = _setup_organized_movie(tmp_path)

    monkeypatch.setattr(scraper_module.manager.config, "main_mode", 4)
    monkeypatch.setattr(scraper_module.manager.config, "read_mode", [ReadMode.READ_UPDATE_NFO])
    monkeypatch.setattr(scraper_module.manager.config, "success_file_move", True)
    monkeypatch.setattr(scraper_module.manager.config, "success_file_rename", True)
    monkeypatch.setattr(scraper_module.manager.config, "soft_link", 0)
    monkeypatch.setattr(scraper_module.manager.config, "auto_link", False)
    monkeypatch.setattr(scraper_module.manager.config, "file_size", "0")
    monkeypatch.setattr(scraper_module.manager.config, "nfo_include_new", [])

    async def fake_check_file(*_args, **_kwargs):
        return True

    def fake_get_movie_path_setting(_file_path=None):
        return SimpleNamespace(success_folder=media_input, movie_path=movie_dir.parent.parent)

    async def fake_get_nfo_data(_file_path: Path, _movie_number: str):
        res = CrawlersResult.empty()
        res.number = "ABC-123"
        res.title = "ABC-123 Existing Title"
        res.actor = "ActorA"
        res.actors = ["ActorA"]
        info = OtherInfo.empty()
        info.poster_path = movie_dir / "poster.jpg"
        info.thumb_path = movie_dir / "thumb.jpg"
        info.fanart_path = movie_dir / "fanart.jpg"
        return res, info

    async def fake_get_video_size(*_args, **_kwargs):
        return "1080P", "H264"

    async def fake_translate_actor(_res):
        return None

    async def fake_translate_title_outline(*_args, **_kwargs):
        return None

    written_nfo_targets: list[tuple[Path, Path, bool]] = []

    async def fake_write_nfo(_file_info, _res, nfo_new_path: Path, folder_new_path: Path, update_nfo: bool):
        written_nfo_targets.append((nfo_new_path, folder_new_path, update_nfo))
        nfo_new_path.write_text("<movie><num>ABC-123</num><title>Updated Title</title></movie>", encoding="utf-8")
        return True

    move_called = False

    async def forbidden_move_movie(*_args, **_kwargs):
        nonlocal move_called
        move_called = True
        return True

    deal_old_called = False

    async def forbidden_deal_old_files(*_args, **_kwargs):
        nonlocal deal_old_called
        deal_old_called = True
        return True, True

    async def noop_async(*_args, **_kwargs):
        return None

    monkeypatch.setattr(scraper_module, "check_file", fake_check_file)
    monkeypatch.setattr(scraper_module, "get_movie_path_setting", fake_get_movie_path_setting)
    monkeypatch.setattr(scraper_module, "get_nfo_data", fake_get_nfo_data)
    monkeypatch.setattr(scraper_module, "get_video_size", fake_get_video_size)
    monkeypatch.setattr(scraper_module, "translate_actor", fake_translate_actor)
    monkeypatch.setattr(scraper_module, "translate_title_outline", fake_translate_title_outline)
    monkeypatch.setattr(scraper_module, "write_nfo", fake_write_nfo)
    monkeypatch.setattr(scraper_module, "move_movie", forbidden_move_movie)
    monkeypatch.setattr(scraper_module, "deal_old_files", forbidden_deal_old_files)
    monkeypatch.setattr(scraper_module, "save_success_list", noop_async)
    monkeypatch.setattr(scraper_module, "compress_images_in_folder_async", noop_async)

    scraper = scraper_module.Scraper(crawler_provider=object())
    res, other = await scraper._process_one_file(file_info, FileMode.Default)

    assert res is not None and other is not None
    assert not move_called, "读取模式未勾选 HAS_NFO_UPDATE 时绝不能调用 move_movie"
    assert not deal_old_called, "读取模式仅更新 NFO（不重下图片、不重新整理）时不应触发 deal_old_files"

    # NFO 必须就地写入原目录的原文件名 .nfo
    assert written_nfo_targets == [(movie_dir / "ABC-123-C.nfo", movie_dir, True)]

    # 原目录所有文件完好无损
    assert (movie_dir / "ABC-123-C.mp4").read_bytes() == b"FAKE_VIDEO_DATA"
    assert (movie_dir / "poster.jpg").read_bytes() == b"OLD_POSTER"
    assert (movie_dir / "thumb.jpg").read_bytes() == b"OLD_THUMB"
    assert (movie_dir / "fanart.jpg").read_bytes() == b"OLD_FANART"
    assert (movie_dir / "ABC-123-C.chs.srt").exists()

    # Media/Input (success_folder) 必须保持为空，没有任何文件被误移过来
    assert list(media_input.iterdir()) == [], f"文件被误移到了 success_folder: {list(media_input.iterdir())}"

    # UI 展示的图片路径与 Manifest 路径保持在原目录
    assert other.poster_path == movie_dir / "poster.jpg"
    assert other.thumb_path == movie_dir / "thumb.jpg"
    assert other.fanart_path == movie_dir / "fanart.jpg"
    assert other.manifest.new_file_path == movie_dir / "ABC-123-C.mp4"
    assert other.manifest.new_folder_path == movie_dir


@pytest.mark.asyncio
async def test_read_mode_redownload_without_reorganize_downloads_in_original_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """读取模式勾选 READ_DOWNLOAD_AGAIN 但未勾选 HAS_NFO_UPDATE 时：
    重下图片与预告片的目标目录必须锚定在原文件夹（movie_dir），绝不能指向 success_folder，且不移动视频。
    """
    from mdcx.core import scraper as scraper_module

    Flags.reset()
    movie_dir, media_input, file_info = _setup_organized_movie(tmp_path)

    monkeypatch.setattr(scraper_module.manager.config, "main_mode", 4)
    monkeypatch.setattr(scraper_module.manager.config, "read_mode", [ReadMode.READ_DOWNLOAD_AGAIN])
    monkeypatch.setattr(scraper_module.manager.config, "success_file_move", True)
    monkeypatch.setattr(scraper_module.manager.config, "success_file_rename", True)
    monkeypatch.setattr(scraper_module.manager.config, "pic_simple_name", True)
    monkeypatch.setattr(scraper_module.manager.config, "soft_link", 0)
    monkeypatch.setattr(scraper_module.manager.config, "auto_link", False)
    monkeypatch.setattr(scraper_module.manager.config, "file_size", "0")

    async def fake_check_file(*_args, **_kwargs):
        return True

    def fake_get_movie_path_setting(_file_path=None):
        return SimpleNamespace(success_folder=media_input, movie_path=movie_dir.parent.parent)

    async def fake_get_nfo_data(_file_path: Path, _movie_number: str):
        res = CrawlersResult.empty()
        res.number = "ABC-123"
        res.title = "ABC-123 Existing Title"
        res.actor = "ActorA"
        res.actors = ["ActorA"]
        return res, OtherInfo.empty()

    async def fake_get_video_size(*_args, **_kwargs):
        return "1080P", "H264"

    async def fake_translate_actor(_res):
        return None

    deal_old_folders: list[tuple[Path, Path]] = []

    async def fake_deal_old_files(_number, _other, folder_old: Path, folder_new: Path, *_args, **_kwargs):
        deal_old_folders.append((folder_old, folder_new))
        return True, True

    download_folders: list[Path] = []

    async def fake_download_images(_self, _res, _other, _file_info, folder_new: Path, *_args, **_kwargs):
        download_folders.append(folder_new)
        return True

    async def fake_write_nfo(*_args, **_kwargs):
        return True

    move_called = False

    async def forbidden_move_movie(*_args, **_kwargs):
        nonlocal move_called
        move_called = True
        return True

    async def noop_async(*_args, **_kwargs):
        return None

    monkeypatch.setattr(scraper_module, "check_file", fake_check_file)
    monkeypatch.setattr(scraper_module, "get_movie_path_setting", fake_get_movie_path_setting)
    monkeypatch.setattr(scraper_module, "get_nfo_data", fake_get_nfo_data)
    monkeypatch.setattr(scraper_module, "get_video_size", fake_get_video_size)
    monkeypatch.setattr(scraper_module, "translate_actor", fake_translate_actor)
    monkeypatch.setattr(scraper_module, "deal_old_files", fake_deal_old_files)
    monkeypatch.setattr(scraper_module.Scraper, "_download_images", fake_download_images)
    monkeypatch.setattr(scraper_module, "trailer_download", noop_async)
    monkeypatch.setattr(scraper_module, "copy_trailer_to_theme_videos", noop_async)
    monkeypatch.setattr(scraper_module, "write_nfo", fake_write_nfo)
    monkeypatch.setattr(scraper_module, "move_movie", forbidden_move_movie)
    monkeypatch.setattr(scraper_module, "save_success_list", noop_async)
    monkeypatch.setattr(scraper_module, "compress_images_in_folder_async", noop_async)

    scraper = scraper_module.Scraper(crawler_provider=object())
    res, other = await scraper._process_one_file(file_info, FileMode.Default)

    assert res is not None and other is not None
    assert not move_called, "未勾选 HAS_NFO_UPDATE 时重下图片不应移动视频"
    assert deal_old_folders == [(movie_dir, movie_dir)], "deal_old_files 新旧目录应均为原目录 movie_dir"
    assert download_folders == [movie_dir], "_download_images 应下载到原目录 movie_dir 而非 success_folder"
    assert list(media_input.iterdir()) == []
