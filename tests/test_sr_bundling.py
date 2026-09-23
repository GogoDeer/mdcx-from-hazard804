"""构建期超分工具拉取与内嵌回归（全程离线）：校验门禁、幂等、按平台内嵌。"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from mdcx.config.resources import resources
from mdcx.core import super_resolution as sr
from scripts import build as build_mod
from scripts import fetch_sr_tools as fetch


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    from mdcx.config.manager import manager

    monkeypatch.setattr(resources, "u", lambda rel: tmp_path / rel)
    monkeypatch.setattr(manager.config, "poster_sr_enabled", True)
    yield


def _write_binary(tool_dir: Path, tool: str) -> None:
    """在给定目录下造一个「可执行文件」占位。

    文件名必须复用生产侧的 `sr._binary_name()` 推导（Windows 带 .exe），
    否则测试夹具与运行时查找路径又会在 Windows 上错位。
    """
    tool_dir.mkdir(parents=True, exist_ok=True)
    (tool_dir / sr._binary_name(tool)).write_text("#!/bin/sh\nexit 0")


def _make_tool_zip(tool: str) -> bytes:
    """构造官方形态的 zip：顶层目录 `<tool>/`，二进制名按平台推导。"""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(f"{tool}/{sr._binary_name(tool)}", b"fake binary")
        zf.writestr(f"{tool}/models/dummy.param", b"dummy")
    return buffer.getvalue()


def test_fetch_tool_verifies_checksum_and_extracts(tmp_path, monkeypatch):
    tool = "realesrgan"
    platform = sr._PLATFORM.get(sys.platform) or ""
    data = _make_tool_zip(tool)
    monkeypatch.setattr(fetch, "_TOOL_CHECKSUMS", {tool: {platform: hashlib.sha256(data).hexdigest()}})
    monkeypatch.setattr(fetch, "_download", lambda url: data)

    result = fetch.fetch_tool(tool, platform, tmp_path / "sr_tools")
    assert result.startswith("就绪")
    assert fetch.is_ready(tmp_path / "sr_tools", tool)


def test_fetch_tool_rejects_checksum_mismatch(tmp_path, monkeypatch):
    tool = "waifu2x"
    platform = sr._PLATFORM.get(sys.platform) or ""
    monkeypatch.setattr(fetch, "_TOOL_CHECKSUMS", {tool: {platform: "1" * 64}})
    monkeypatch.setattr(fetch, "_download", lambda url: _make_tool_zip(tool))

    with pytest.raises(RuntimeError, match="sha256"):
        fetch.fetch_tool(tool, platform, tmp_path / "sr_tools")


def test_fetch_tool_skips_download_when_ready(tmp_path, monkeypatch):
    tool = "realesrgan"
    target = tmp_path / "sr_tools" / tool
    binary = target / sr._binary_name(tool)
    _write_binary(target, tool)
    binary.chmod(0o755)

    def fail(url):
        raise AssertionError("已就绪时不应发起下载")

    monkeypatch.setattr(fetch, "_download", fail)
    assert "跳过" in fetch.fetch_tool(tool, sr._PLATFORM.get(sys.platform) or "", tmp_path / "sr_tools")


@pytest.mark.asyncio
async def test_bundled_layout_matches_runtime_lookup(tmp_path, monkeypatch):
    """打包资源目录 `sr_tools/<tool>` 必须与运行时 `_MEIPASS/sr_tools/<tool>` 查找路径一致，
    且内置工具要释放到 userdata 缓存目录后使用（打包解压目录不保证可写）。"""
    data_root = tmp_path / "data"
    monkeypatch.setattr(resources, "u", lambda rel: data_root / rel)
    mei = tmp_path / "mei" / "sr_tools" / "realesrgan"
    _write_binary(mei, "realesrgan")
    monkeypatch.setattr(sr.sys, "_MEIPASS", str(tmp_path / "mei"), raising=False)

    assert sr._builtin_dir("realesrgan") == mei
    resolved = await sr.ensure_binary("realesrgan")
    assert resolved is not None and resolved.is_file()
    assert resolved == sr.binary_path("realesrgan")


def test_build_args_include_sr_tools_only_for_windows_and_linux(tmp_path, monkeypatch):
    """一体包资源只进 Windows/Linux 包；macOS 不内嵌（签名/公证与 Gatekeeper 风险）。"""
    root = tmp_path / "sr_tools" / "realesrgan"
    root.mkdir(parents=True)
    (root / "realesrgan").write_text("#!/bin/sh\nexit 0")
    monkeypatch.setattr(build_mod, "SR_TOOLS_DIR", str(tmp_path / "sr_tools"))

    for system, expected in (("Windows", True), ("Linux", True), ("Darwin", False)):
        monkeypatch.setattr(build_mod.platform, "system", lambda s=system: s)
        manager = build_mod.BuildManager("MDCx", "20260921", create_dmg=False, debug=True)
        args = manager._sr_tools_binary_args()
        marker = f"{os.pathsep}sr_tools/"
        assert any(marker in item for item in args) is expected, f"{system}: {args}"


def test_build_args_fail_closed_when_sr_tools_missing(tmp_path, monkeypatch):
    """Windows/Linux 缺工具目录必须硬失败（v2.1.1 实证：静默跳过导致一体包未内嵌）。"""
    monkeypatch.setattr(build_mod, "SR_TOOLS_DIR", str(tmp_path / "no_such_dir"))

    for system in ("Windows", "Linux"):
        monkeypatch.setattr(build_mod.platform, "system", lambda s=system: s)
        manager = build_mod.BuildManager("MDCx", "20260921", create_dmg=False, debug=True)
        with pytest.raises(build_mod.BuildError, match="超分工具目录"):
            manager._sr_tools_binary_args()

    # macOS 不内嵌，缺目录仍放行
    monkeypatch.setattr(build_mod.platform, "system", lambda: "Darwin")
    manager = build_mod.BuildManager("MDCx", "20260921", create_dmg=False, debug=True)
    assert manager._sr_tools_binary_args() == []


def test_build_args_fail_closed_when_sr_tools_empty(tmp_path, monkeypatch):
    """Windows/Linux 目录存在但无工具子目录必须硬失败（空目录 --add-binary 为空会静默漏打）。"""
    empty = tmp_path / "sr_tools"
    empty.mkdir()
    monkeypatch.setattr(build_mod, "SR_TOOLS_DIR", str(empty))

    for system in ("Windows", "Linux"):
        monkeypatch.setattr(build_mod.platform, "system", lambda s=system: s)
        manager = build_mod.BuildManager("MDCx", "20260921", create_dmg=False, debug=True)
        with pytest.raises(build_mod.BuildError, match="为空"):
            manager._sr_tools_binary_args()

    monkeypatch.setattr(build_mod.platform, "system", lambda: "Darwin")
    manager = build_mod.BuildManager("MDCx", "20260921", create_dmg=False, debug=True)
    assert manager._sr_tools_binary_args() == []


def test_cleanup_preserves_sr_tools(tmp_path, monkeypatch):
    """`_cleanup` 整清 build/ 时必须保留 SR_TOOLS_DIR（v2.1.1 实证：工具被清掉后打包静默缺工具）。"""
    monkeypatch.chdir(tmp_path)
    keep = tmp_path / "build" / "sr_tools" / "realesrgan"
    keep.mkdir(parents=True)
    (keep / "realesrgan-ncnn-vulkan").write_text("binary")
    stale = tmp_path / "build" / "MDCx"
    stale.mkdir(parents=True)
    (stale / "Analysis-00.toc").write_text("toc")

    manager = build_mod.BuildManager("MDCx", "20260921", create_dmg=False, debug=True)
    manager._cleanup()

    assert keep.is_dir() and (keep / "realesrgan-ncnn-vulkan").is_file()
    assert not stale.exists()


def _is_macos_build(text: str, build_idx: int) -> bool:
    return "--create-dmg" in text[max(0, build_idx - 500) : build_idx]


def test_packaging_workflows_fetch_sr_tools_before_build():
    """Windows/Linux 打包工作流必须先 fetch 再 build。

    CI 冒烟实证：build.py 缺工具已硬失败，但 ci.yaml / 手动打包工作流漏了
    `scripts.fetch_sr_tools`，Windows job 测试全绿后在冒烟步 BuildError。
    macOS 不内嵌超分，release.yml 的 create-dmg 构建允许没有配对 fetch。
    ci.yaml 现有 Windows + Linux 两处冒烟，必须各自 fetch 后再 build。
    """
    root = Path(".github/workflows")
    for name in ("ci.yaml", "release.yml", "build-windows.yml", "build-linux.yml"):
        text = (root / name).read_text(encoding="utf-8")
        fetch_idxs = [m.start() for m in re.finditer(r"scripts\.fetch_sr_tools", text)]
        build_idxs = [m.start() for m in re.finditer(r"scripts/build\.py", text)]
        assert fetch_idxs, f"{name} 缺少 scripts.fetch_sr_tools"
        assert build_idxs, f"{name} 缺少 scripts/build.py"
        win_linux_builds = [i for i in build_idxs if not _is_macos_build(text, i)]
        assert win_linux_builds, f"{name} 缺少 Windows/Linux 的 scripts/build.py"
        if name == "ci.yaml":
            assert len(fetch_idxs) == len(win_linux_builds) >= 2, (
                f"ci.yaml 冒烟 fetch/build 次数应对等且不少于 2: fetch={len(fetch_idxs)} build={len(win_linux_builds)}"
            )
            for fetch_idx, build_idx in zip(fetch_idxs, win_linux_builds, strict=True):
                assert fetch_idx < build_idx, "ci.yaml 每处冒烟必须先 fetch_sr_tools 再 build.py"
            continue
        assert all(fetch_idxs[0] < build_idx for build_idx in win_linux_builds), (
            f"{name} 必须先 fetch_sr_tools 再跑 Windows/Linux 的 build.py"
        )


def test_ci_linux_smoke_job_exists():
    """Linux 打包参数（省略图标、超分 --add-binary）须在 PR/主干冒烟，不能等到发版才暴露。"""
    text = Path(".github/workflows/ci.yaml").read_text(encoding="utf-8")
    assert "name: Linux Build Smoke" in text
    assert "sr-tools-linux-" in text
    assert text.count("scripts.fetch_sr_tools") >= 2
    assert text.count("scripts/build.py") >= 2


def test_release_prechecks_all_platforms():
    """发版产物预检必须覆盖 macOS / Windows / Linux，缺文件时在 upload 前硬失败。"""
    text = Path(".github/workflows/release.yml").read_text(encoding="utf-8")
    for name in (
        "Pre-check macOS artifact for release upload",
        "Pre-check Windows artifact for release upload",
        "Pre-check Linux artifact for release upload",
    ):
        assert name in text, f"release.yml 缺少 {name}"
    assert "dist/MDCx-${{ matrix.arch }}.dmg" in text
    assert "dist/MDCx.exe" in text
    assert 'artifact="dist/MDCx"' in text


def test_sr_tools_cache_action_is_v6():
    """SR 工具缓存必须用 actions/cache@v6（Node 24），与 #140 口径一致。"""
    root = Path(".github/workflows")
    pattern = re.compile(r"uses:\s*actions/cache@v(\d+)")
    for name in ("ci.yaml", "release.yml", "build-windows.yml", "build-linux.yml", "update-sr-tools.yml"):
        text = (root / name).read_text(encoding="utf-8")
        versions = pattern.findall(text)
        assert versions, f"{name} 未使用 actions/cache"
        assert all(v == "6" for v in versions), f"{name} 仍有非 v6 的 actions/cache: {versions}"


def test_update_sr_tools_pins_python_and_linux_qt_libs():
    """周预热必须钉 Python 3.13，Linux 系统库与 ci.yaml 对齐，否则 fetch 在 import PyQt6 时红。"""
    text = Path(".github/workflows/update-sr-tools.yml").read_text(encoding="utf-8")
    assert "python-version:" in text and "3.13" in text
    for pkg in (
        "libqt6core6",
        "libqt6gui6",
        "libqt6widgets6",
        "libxcb-cursor0",
        "libxcb-xinerama0",
        "libxcb-icccm4",
        "libxcb-image0",
        "libxcb-keysyms1",
        "libxcb-randr0",
        "libxcb-render-util0",
        "libxcb-shape0",
    ):
        assert pkg in text, f"update-sr-tools.yml Linux 依赖缺少 {pkg}"


def test_sr_tools_cache_keys_rotate_with_baseline_fingerprint():
    """SR 工具缓存 key 必须携带基准文件指纹，防止旧缓存静默打旧版工具。

    actions/cache 对已存在的 key 永不覆写，而 fetch 的 is_ready 命中后不校验 sha256：
    固定 key 时升级 `_TOOL_DOWNLOAD_URLS`/`_TOOL_CHECKSUMS` 后所有工作流（含预热任务）
    都命中旧缓存并幂等跳过，新基准永远进不了产物（2026-09-22 审查实证形态）。
    """
    root = Path(".github/workflows")
    pattern = re.compile(r"path:\s*build/sr_tools\s*\n\s*key:\s*(.+)")
    seen_files = set()
    for name in ("ci.yaml", "release.yml", "build-windows.yml", "build-linux.yml", "update-sr-tools.yml"):
        text = (root / name).read_text(encoding="utf-8")
        keys = pattern.findall(text)
        assert keys, f"{name} 未找到 build/sr_tools 的缓存 key 配置"
        seen_files.add(name)
        for key in keys:
            assert "hashFiles('mdcx/core/super_resolution.py')" in key, f"{name} 的 sr 工具缓存 key 未随基准轮换: {key}"
    assert seen_files == {"ci.yaml", "release.yml", "build-windows.yml", "build-linux.yml", "update-sr-tools.yml"}
