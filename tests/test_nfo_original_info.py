from pathlib import Path

import pytest

from mdcx.config.enums import NfoMergeStrategy
from mdcx.core import nfo as nfo_module
from mdcx.core.nfo_merger import merge_nfo_fields
from mdcx.models.model_types import CrawlersResult, FileInfo


class _RenderedTitle:
    def __init__(self, text: str):
        self.text = text


def _build_file_info(tmp_path: Path) -> FileInfo:
    file_info = FileInfo.empty()
    file_info.number = "JAVHub.22.09.15"
    file_info.file_path = tmp_path / "JAVHub.22.09.15.Maso.Mask.mp4"
    file_info.folder_path = tmp_path
    file_info.file_name = "JAVHub.22.09.15.Maso.Mask.mp4"
    return file_info


@pytest.mark.asyncio
async def test_write_and_read_nfo_original_file_info(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(nfo_module.manager.config, "download_files", [])
    monkeypatch.setattr(nfo_module.manager.config, "keep_files", [])
    monkeypatch.setattr(nfo_module.manager.config, "outline_format", [])
    monkeypatch.setattr(nfo_module.manager.config, "main_mode", 1)
    monkeypatch.setattr(nfo_module.manager.config, "naming_media", "number title")
    monkeypatch.setattr(nfo_module.manager.config, "update_titletemplate", "number title")
    monkeypatch.setattr(nfo_module.manager.config, "nfo_include_new", [])
    monkeypatch.setattr(nfo_module.manager.config, "nfo_tagline", "")
    monkeypatch.setattr(nfo_module.manager.config, "actor_no_name", "佚名")
    monkeypatch.setattr(nfo_module, "render_name", lambda *args, **kwargs: _RenderedTitle("Maso Mask"))

    file_info = _build_file_info(tmp_path)
    data = CrawlersResult.empty()
    data.number = "Javhub.22.09.15"
    data.title = "Maso Mask"

    nfo_file = tmp_path / "Javhub.22.09.15.nfo"
    ok = await nfo_module.write_nfo(file_info, data, nfo_file, tmp_path, update=True)
    assert ok is True
    assert nfo_file.exists()

    content = nfo_file.read_text(encoding="utf-8")
    assert "<originalfilename>JAVHub.22.09.15.Maso.Mask.mp4</originalfilename>" in content
    assert f"<originalfilepath>{str(file_info.file_path)}</originalfilepath>" in content

    # Test reading back via get_nfo_data
    video_file = tmp_path / "Javhub.22.09.15.mp4"
    video_file.write_bytes(b"")
    loaded_data, _ = await nfo_module.get_nfo_data(video_file, "Javhub.22.09.15")
    assert loaded_data is not None
    assert loaded_data.originalfilename == "JAVHub.22.09.15.Maso.Mask.mp4"
    assert loaded_data.originalfilepath == str(file_info.file_path)


@pytest.mark.asyncio
async def test_write_nfo_preserves_existing_original_info_on_rescrape(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(nfo_module.manager.config, "download_files", [])
    monkeypatch.setattr(nfo_module.manager.config, "keep_files", [])
    monkeypatch.setattr(nfo_module.manager.config, "outline_format", [])
    monkeypatch.setattr(nfo_module.manager.config, "main_mode", 1)
    monkeypatch.setattr(nfo_module.manager.config, "naming_media", "number title")
    monkeypatch.setattr(nfo_module.manager.config, "update_titletemplate", "number title")
    monkeypatch.setattr(nfo_module.manager.config, "nfo_include_new", [])
    monkeypatch.setattr(nfo_module.manager.config, "nfo_tagline", "")
    monkeypatch.setattr(nfo_module.manager.config, "actor_no_name", "佚名")
    monkeypatch.setattr(nfo_module, "render_name", lambda *args, **kwargs: _RenderedTitle("Maso Mask"))

    # Initial NFO already has original filename from pre-scrape
    nfo_file = tmp_path / "Javhub.22.09.15.nfo"
    nfo_file.write_text(
        """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<movie>
  <title>Maso Mask</title>
  <num>Javhub.22.09.15</num>
  <originalfilename>TRUE_ORIGINAL.22.09.15.mp4</originalfilename>
  <originalfilepath>I:/incoming/TRUE_ORIGINAL.22.09.15.mp4</originalfilepath>
</movie>
""",
        encoding="utf-8",
    )

    # Now re-scrape the file in output folder
    file_info = FileInfo.empty()
    file_info.number = "Javhub.22.09.15"
    file_info.file_name = "Javhub.22.09.15.mp4"
    file_info.file_path = tmp_path / "Javhub.22.09.15.mp4"
    file_info.folder_path = tmp_path

    new_data = CrawlersResult.empty()
    new_data.number = "Javhub.22.09.15"
    new_data.title = "Maso Mask New"

    ok = await nfo_module.write_nfo(file_info, new_data, nfo_file, tmp_path, update=True)
    assert ok is True

    # Check that TRUE_ORIGINAL was preserved
    content = nfo_file.read_text(encoding="utf-8")
    assert "<originalfilename>TRUE_ORIGINAL.22.09.15.mp4</originalfilename>" in content
    assert "<originalfilepath>I:/incoming/TRUE_ORIGINAL.22.09.15.mp4</originalfilepath>" in content


def test_merge_nfo_fields_inherits_original_info():
    scraped = CrawlersResult.empty()
    scraped.number = "ABC-123"
    scraped.title = "Scraped Title"

    existing_nfo = CrawlersResult.empty()
    existing_nfo.number = "ABC-123"
    existing_nfo.title = "Existing Title"
    existing_nfo.originalfilename = "ORIG_ABC.mp4"
    existing_nfo.originalfilepath = "/path/to/ORIG_ABC.mp4"

    merged = merge_nfo_fields(scraped, existing_nfo, NfoMergeStrategy.PREFER_NFO)
    assert merged.originalfilename == "ORIG_ABC.mp4"
    assert merged.originalfilepath == "/path/to/ORIG_ABC.mp4"
