import json
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtWidgets import QApplication, QMainWindow

from mdcx.config.manager import manager
from mdcx.controllers.main_window.load_config import load_config
from mdcx.controllers.main_window.save_config import save_config
from mdcx.utils.javstash_utils import verify_stashbox_connection_sync
from mdcx.views.MDCx import Ui_MDCx


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_ui_stashdb_widgets_exist(qapp):
    """Verify that all StashDB widgets exist in the generated UI class."""
    window = QMainWindow()
    ui = Ui_MDCx()
    ui.setupUi(window)

    assert hasattr(ui, "lineEdit_stashdb_url")
    assert hasattr(ui, "lineEdit_stashdb_api_key")
    assert hasattr(ui, "pushButton_test_stashdb")
    assert hasattr(ui, "label_stashdb_test_result")
    assert hasattr(ui, "label_stashdb_guide")
    assert hasattr(ui, "checkBox_use_phash_number")

    assert ui.lineEdit_stashdb_url.text() == "https://stashdb.org"
    assert ui.pushButton_test_stashdb.text() == "测试连接"
    assert "https://stashdb.org/" in ui.label_stashdb_guide.text()
    assert "pHash" in ui.checkBox_use_phash_number.text()


def test_stashdb_connection_sync_messages():
    """Verify connection verification messages formatted for StashDB."""
    # Empty inputs
    ok, msg = verify_stashbox_connection_sync("", "", service_name="StashDB")
    assert not ok
    assert "未填写" in msg

    # Success response
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = json.dumps({"data": {"me": {"name": "Bob"}}}).encode("utf-8")

    with patch("urllib.request.build_opener") as mock_opener:
        mock_instance = MagicMock()
        mock_instance.open.return_value.__enter__.return_value = mock_resp
        mock_opener.return_value = mock_instance

        ok, msg = verify_stashbox_connection_sync("https://stashdb.org", "test_key", service_name="StashDB")
        assert ok is True
        assert "Bob" in msg

    # GraphQL Error response
    err_resp = MagicMock()
    err_resp.status = 200
    err_resp.read.return_value = json.dumps({"errors": [{"message": "Invalid API Key"}]}).encode("utf-8")

    with patch("urllib.request.build_opener") as mock_opener:
        mock_instance = MagicMock()
        mock_instance.open.return_value.__enter__.return_value = err_resp
        mock_opener.return_value = mock_instance

        ok, msg = verify_stashbox_connection_sync("https://stashdb.org", "bad_key", service_name="StashDB")
        assert ok is False
        assert "StashDB 密钥无效" in msg


def test_load_and_save_config_stashdb(qapp, monkeypatch):
    """Verify load_config and save_config correctly synchronize StashDB fields."""
    window = QMainWindow()
    ui = Ui_MDCx()
    ui.setupUi(window)

    fake_self = MagicMock()
    fake_self.Ui = ui

    orig_key = manager.config.stashdb_api_key
    orig_url = manager.config.stashdb_url
    orig_use = manager.config.use_phash_number
    try:
        # Setup config values
        manager.config.stashdb_api_key = "stashdb_secret_key_123"
        manager.config.stashdb_url = "https://custom.stashdb.org"
        manager.config.use_phash_number = True
        monkeypatch.setattr(manager, "save", MagicMock(), raising=False)

        # Test load_config
        load_config(fake_self)
        assert ui.lineEdit_stashdb_api_key.text() == "stashdb_secret_key_123"
        assert ui.lineEdit_stashdb_url.text() == "https://custom.stashdb.org"
        assert ui.checkBox_use_phash_number.isChecked() is True

        # Change values in UI and test save_config
        ui.lineEdit_stashdb_api_key.setText("new_stashdb_key_456")
        ui.lineEdit_stashdb_url.setText("https://stashdb.org")
        ui.checkBox_use_phash_number.setChecked(False)

        save_config(fake_self)
        assert manager.config.stashdb_api_key == "new_stashdb_key_456"
        assert manager.config.stashdb_url == "https://stashdb.org"
        assert manager.config.use_phash_number is False
    finally:
        manager.config.stashdb_api_key = orig_key
        manager.config.stashdb_url = orig_url
        manager.config.use_phash_number = orig_use
