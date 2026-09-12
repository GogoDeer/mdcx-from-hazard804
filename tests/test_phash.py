"""Unit tests for perceptual hash (pHash) module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PIL import Image

from mdcx.utils.phash import compute_phash_from_image, compute_video_phash


def test_phash_from_image_solid():
    """Solid color images should produce deterministic 16-hex hash."""
    black = Image.new("RGB", (100, 100), color=(0, 0, 0))
    h_black = compute_phash_from_image(black)
    assert len(h_black) == 16
    assert isinstance(h_black, str)
    assert h_black == "0000000000000000"

    white = Image.new("RGB", (100, 100), color=(255, 255, 255))
    h_white = compute_phash_from_image(white)
    assert len(h_white) == 16
    assert h_white == compute_phash_from_image(white)


def test_phash_from_image_patterns():
    """Different image patterns should produce different hashes."""
    # Pattern 1: Horizontal stripes
    arr1 = np.zeros((100, 100), dtype=np.uint8)
    arr1[::2, :] = 255
    img1 = Image.fromarray(arr1)
    h1 = compute_phash_from_image(img1)

    # Pattern 2: Vertical stripes
    arr2 = np.zeros((100, 100), dtype=np.uint8)
    arr2[:, ::2] = 255
    img2 = Image.fromarray(arr2)
    h2 = compute_phash_from_image(img2)

    assert len(h1) == 16
    assert len(h2) == 16
    assert h1 != h2


def test_compute_video_phash_file_not_found():
    """Non-existent video path returns None."""
    assert compute_video_phash("non_existent_video_file_123.mp4") is None


def test_compute_video_phash_mocked():
    """Mock PyAV container and frames to test compute_video_phash pipeline."""
    mock_frame = MagicMock()
    # Mock to_image to return an actual small PIL Image
    test_img = Image.new("RGB", (320, 240), color=(128, 64, 32))
    mock_frame.to_image.return_value = test_img

    mock_packet = MagicMock()
    mock_packet.decode.return_value = [mock_frame]

    mock_stream = MagicMock()
    mock_stream.duration = 1000
    mock_stream.time_base = 0.01  # duration = 10s

    mock_container = MagicMock()
    mock_container.streams.video = [mock_stream]
    mock_container.demux.return_value = [mock_packet]

    mock_av = MagicMock()
    mock_av.open.return_value.__enter__.return_value = mock_container

    with patch.dict("sys.modules", {"av": mock_av}):
        with patch.object(Path, "is_file", return_value=True):
            h = compute_video_phash("dummy_test_video.mp4")
            assert h is not None
            assert len(h) == 16
            assert all(c in "0123456789abcdef" for c in h)


def test_phash_scene_cache():
    """Test scene cache operations."""
    from mdcx.utils.phash import clear_cached_scenes, get_cached_scene, set_cached_scene

    clear_cached_scenes()
    p = Path("test_vid.mp4")
    assert get_cached_scene(p) is None

    fake_scene = {"id": "123", "code": "ABC-001", "title": "Test Title"}
    set_cached_scene(p, fake_scene)
    assert get_cached_scene(p) == fake_scene

    clear_cached_scenes()
    assert get_cached_scene(p) is None


@pytest.mark.asyncio
async def test_resolve_number_by_phash_missing_args():
    """Missing API key or non-existent file returns None."""
    from mdcx.utils.phash import resolve_number_by_phash

    assert await resolve_number_by_phash("non_existent_123.mp4", api_key="") is None
    assert await resolve_number_by_phash("non_existent_123.mp4", api_key="test_key") is None


@pytest.mark.asyncio
async def test_resolve_number_by_phash_success(monkeypatch):
    """Test successful pHash number resolution with mocked httpx response."""
    from unittest.mock import AsyncMock

    from mdcx.utils.phash import clear_cached_scenes, get_cached_scene, resolve_number_by_phash

    clear_cached_scenes()
    monkeypatch.setattr("pathlib.Path.is_file", lambda self: True)
    monkeypatch.setattr("mdcx.utils.phash.compute_video_phash", lambda p: "f19ea8f1c0e89983")

    fake_scene = {"id": "scene_123", "code": "HEYZO-1587", "title": "Test Title"}
    mock_post = AsyncMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"data": {"findScenesBySceneFingerprints": [[fake_scene]]}}
    mock_post.return_value = mock_response

    with patch("httpx.AsyncClient.post", mock_post):
        code = await resolve_number_by_phash("dummy_vid.mp4", api_key="valid_key")
        assert code == "HEYZO-1587"
        # Verify scene was cached
        cached = get_cached_scene("dummy_vid.mp4")
        assert cached == fake_scene


@pytest.mark.asyncio
async def test_resolve_number_by_phash_error_handling(monkeypatch):
    """Network errors or 500 status should return None gracefully."""
    from unittest.mock import AsyncMock

    from mdcx.utils.phash import clear_cached_scenes, resolve_number_by_phash

    clear_cached_scenes()
    monkeypatch.setattr("pathlib.Path.is_file", lambda self: True)
    monkeypatch.setattr("mdcx.utils.phash.compute_video_phash", lambda p: "f19ea8f1c0e89983")

    mock_post = AsyncMock(side_effect=Exception("Connection refused"))
    with patch("httpx.AsyncClient.post", mock_post):
        assert await resolve_number_by_phash("dummy_vid.mp4", api_key="valid_key") is None


@pytest.mark.asyncio
async def test_get_file_info_v2_with_phash_enabled(monkeypatch):
    """When use_phash_number is True, pHash resolution takes precedence."""
    from unittest.mock import AsyncMock

    from mdcx.config.manager import manager
    from mdcx.core.file import get_file_info_v2

    manager.config.use_phash_number = True
    manager.config.javstash_api_key = "test_key"

    # Mock resolve_number_by_phash to return HEYZO-1587
    mock_resolve = AsyncMock(return_value="HEYZO-1587")
    monkeypatch.setattr("mdcx.utils.phash.resolve_number_by_phash", mock_resolve)
    monkeypatch.setattr("aiofiles.os.path.islink", AsyncMock(return_value=False))

    # File with irregular name 'abcdef.mp4'
    finfo = await get_file_info_v2(Path("abcdef.mp4"), copy_sub=False)
    assert finfo.number == "HEYZO-1587"
    mock_resolve.assert_called_once()


@pytest.mark.asyncio
async def test_get_file_info_v2_with_phash_fallback_to_regex(monkeypatch):
    """When use_phash_number is True but resolution returns None, fall back to regex."""
    from unittest.mock import AsyncMock

    from mdcx.config.manager import manager
    from mdcx.core.file import get_file_info_v2

    manager.config.use_phash_number = True
    manager.config.javstash_api_key = "test_key"

    mock_resolve = AsyncMock(return_value=None)
    monkeypatch.setattr("mdcx.utils.phash.resolve_number_by_phash", mock_resolve)
    monkeypatch.setattr("aiofiles.os.path.islink", AsyncMock(return_value=False))

    # Regular file STARS-358.mp4
    finfo = await get_file_info_v2(Path("STARS-358.mp4"), copy_sub=False)
    assert finfo.number == "STARS-358"
    mock_resolve.assert_called_once()


@pytest.mark.asyncio
async def test_get_file_info_v2_with_phash_disabled(monkeypatch):
    """When use_phash_number is False, resolve_number_by_phash is never called."""
    from unittest.mock import AsyncMock

    from mdcx.config.manager import manager
    from mdcx.core.file import get_file_info_v2

    manager.config.use_phash_number = False
    manager.config.javstash_api_key = "test_key"

    mock_resolve = AsyncMock()
    monkeypatch.setattr("mdcx.utils.phash.resolve_number_by_phash", mock_resolve)
    monkeypatch.setattr("aiofiles.os.path.islink", AsyncMock(return_value=False))

    finfo = await get_file_info_v2(Path("STARS-358.mp4"), copy_sub=False)
    assert finfo.number == "STARS-358"
    mock_resolve.assert_not_called()


@pytest.mark.asyncio
async def test_get_file_info_v2_with_phash_enabled_but_missing_key(monkeypatch):
    """When use_phash_number is True but javstash_api_key is empty, skips with warning."""
    from unittest.mock import AsyncMock

    from mdcx.config.manager import manager
    from mdcx.core.file import get_file_info_v2
    from mdcx.models.log_buffer import LogBuffer

    manager.config.use_phash_number = True
    manager.config.javstash_api_key = ""
    manager.config.stashdb_api_key = ""

    mock_resolve = AsyncMock()
    monkeypatch.setattr("mdcx.utils.phash.resolve_number_by_phash", mock_resolve)
    monkeypatch.setattr("aiofiles.os.path.islink", AsyncMock(return_value=False))

    finfo = await get_file_info_v2(Path("STARS-358.mp4"), copy_sub=False)
    assert finfo.number == "STARS-358"
    mock_resolve.assert_not_called()
    assert "未配置 JavStash API Key" in LogBuffer.log().get()


@pytest.mark.asyncio
async def test_resolve_number_by_phash_oshash_fallback(monkeypatch):
    """When PHASH does not match, OSHASH match is picked."""
    from mdcx.utils.phash import clear_cached_scenes, resolve_number_by_phash

    clear_cached_scenes()
    monkeypatch.setattr("pathlib.Path.is_file", lambda p: True)
    monkeypatch.setattr("mdcx.utils.phash.compute_video_phash", lambda p: "phash_nomatch")
    monkeypatch.setattr("oshash.oshash", lambda p: "oshash_hit")

    class MockResponse:
        status_code = 200

        def json(self):
            return {
                "data": {
                    "findScenesBySceneFingerprints": [
                        [],  # PHASH empty
                        [{"title": "Scene via OSHASH", "code": None}],  # OSHASH match
                    ]
                }
            }

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, json, headers):
            return MockResponse()

    monkeypatch.setattr("httpx.AsyncClient", MockAsyncClient)

    res = await resolve_number_by_phash("test.mp4", api_key="key")
    assert res == "Scene via OSHASH"


@pytest.mark.asyncio
async def test_resolve_number_priority_javstash_then_stashdb(monkeypatch):
    """JavStash is queried first; if no match, StashDB is queried."""
    from mdcx.utils.phash import clear_cached_scenes, resolve_number_by_phash

    clear_cached_scenes()
    monkeypatch.setattr("pathlib.Path.is_file", lambda p: True)
    monkeypatch.setattr("mdcx.utils.phash.compute_video_phash", lambda p: "phash_val")
    monkeypatch.setattr("oshash.oshash", lambda p: "oshash_val")

    queried_urls = []

    class MockResponse:
        def __init__(self, url):
            self.url = url
            self.status_code = 200

        def json(self):
            if "javstash.org" in self.url:
                # JavStash has no match
                return {"data": {"findScenesBySceneFingerprints": [[], []]}}
            else:
                # StashDB has match
                return {
                    "data": {
                        "findScenesBySceneFingerprints": [
                            [],
                            [{"title": "Kasey Scene", "code": None}],
                        ]
                    }
                }

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, json, headers):
            queried_urls.append(url)
            return MockResponse(url)

    monkeypatch.setattr("httpx.AsyncClient", MockAsyncClient)

    endpoints = [
        {"name": "JavStash", "url": "https://javstash.org", "api_key": "k1"},
        {"name": "StashDB", "url": "https://stashdb.org", "api_key": "k2"},
    ]

    res = await resolve_number_by_phash("test.mp4", endpoints=endpoints)
    assert res == "Kasey Scene"
    assert len(queried_urls) == 2
    assert "javstash.org" in queried_urls[0]
    assert "stashdb.org" in queried_urls[1]
