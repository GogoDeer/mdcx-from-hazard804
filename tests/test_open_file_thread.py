"""Unit tests for open_file_thread on Windows paths containing commas."""

from pathlib import Path
from unittest.mock import MagicMock

from mdcx.utils import file as file_utils


def test_open_file_thread_windows_play_uses_startfile(monkeypatch):
    """Playing a video on Windows should use os.startfile so commas in multi-actor paths do not break."""
    monkeypatch.setattr(file_utils, "IS_WINDOWS", True)
    mock_startfile = MagicMock()
    mock_popen = MagicMock()
    monkeypatch.setattr(file_utils.os, "startfile", mock_startfile, raising=False)
    monkeypatch.setattr(file_utils.subprocess, "Popen", mock_popen)

    target = Path(r"A:\temp\scan\output\川村千咲,安西千寻,水岛美香\030421_442-paco\030421_442-paco.mp4")
    file_utils.open_file_thread(target, is_dir=False)

    mock_startfile.assert_called_once_with(str(target))
    mock_popen.assert_not_called()


def test_open_file_thread_windows_select_quotes_comma_path(monkeypatch):
    """Opening folder on Windows should quote path in explorer /select so commas are not parsed as delimiters."""
    monkeypatch.setattr(file_utils, "IS_WINDOWS", True)
    mock_popen = MagicMock()
    monkeypatch.setattr(file_utils.subprocess, "Popen", mock_popen)

    target = Path(r"A:\temp\scan\output\川村千咲,安西千寻,水岛美香\030421_442-paco\030421_442-paco.mp4")
    file_utils.open_file_thread(target, is_dir=True)

    mock_popen.assert_called_once_with(f'explorer /select,"{target}"')
