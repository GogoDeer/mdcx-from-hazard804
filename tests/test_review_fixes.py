"""2026-09-23 全面代码审查修复的行为/结构锁。

约定：改这些生产代码形态前先回看本文件 docstring 里记录的原始缺陷。
"""

import asyncio
import os
from pathlib import Path


def asyncio_run_compat(coro):
    return asyncio.run(coro)


SCRAPER = Path("mdcx/core/scraper.py")


def test_write_nfo_failure_must_not_count_as_success():
    """scraper 收尾对 write_nfo() 的 bool 返回值必须消费——失败静默记成功会让
    断点续刮按 mtime 永久跳过缺 NFO 的文件（审查项 #1）。"""
    src = SCRAPER.read_text(encoding="utf-8")
    assert "if not await write_nfo(" in src, "write_nfo 返回值未消费：写失败仍会 save_success_list + set_done"


def test_starting_counter_uses_increment_return_value():
    """increment() 已是锁内原子返回，调用方不得再二次读类属性——并发任务会
    互相覆盖后读到他人计数，count==1 快路径与间歇阈值错乱（审查项 #2）。"""
    src = SCRAPER.read_text(encoding="utf-8")
    assert "count = await Flags.increment(" in src
    assert "Flags.scrape_starting = await Flags.increment(" not in src


NFO_XML = """<?xml version="1.0" encoding="UTF-8"?>
<movie>
  <title>ABCD-123 旧标题</title>
  <originaltitle>旧原标题</originaltitle>
  <num>ABCD-123</num>
  <uniqueid type="javbus">oldid</uniqueid>
</movie>
"""


def test_get_nfo_data_nfo_path_reads_target_file(tmp_path):
    """get_nfo_data 显式 nfo_path 读指定文件（审查项 #5）：源媒体 stem ≠ 命名后的
    目标文件时，NFO 合并必须读目标 *.nfo 而不是按源路径推导的同名 .nfo。"""
    import asyncio

    from mdcx.core.nfo import get_nfo_data

    source_media = tmp_path / "src" / "原始名.mp4"
    target_nfo = tmp_path / "out" / "演员" / "ABCD-123 新名.nfo"
    target_nfo.parent.mkdir(parents=True)
    target_nfo.write_text(NFO_XML, encoding="utf-8")

    data, _info = asyncio.run(get_nfo_data(source_media, "ABCD-123", nfo_path=target_nfo))
    assert data is not None and "旧标题" in data.title

    # 不传 nfo_path 保持旧语义：按源媒体推导 → 读不到该文件
    missing, _ = asyncio.run(get_nfo_data(source_media, "ABCD-123"))
    assert missing is None


def test_write_nfo_merge_reads_target_nfo_file():
    """调用点结构锁：合并分支必须以 nfo_path=nfo_file 读取目标 NFO（审查项 #5）。"""
    src = Path("mdcx/core/nfo.py").read_text(encoding="utf-8")
    assert "await get_nfo_data(file_info.file_path, data.number, nfo_path=nfo_file)" in src


def test_domain_rotation_state_is_task_local():
    """镜像轮换/换域写入是任务级状态（审查项 #3/#javdb_api）：provider 站点级
    缓存爬虫实例、并行任务共享单例，A 任务把 base_url 换到备用镜像后，B 任务
    （乃至主协程）不得看到 A 的换域结果。"""
    import asyncio

    from mdcx.config.enums import Website
    from mdcx.crawlers.base import base as base_mod

    class _StubClient:
        def __init__(self):
            self.seen: list[str] = []

        async def get_text(self, url, headers=None, cookies=None, retry_count=1):
            await asyncio.sleep(0)  # 强制交错
            self.seen.append(url)
            if url.startswith("https://a.test"):
                return None, "SSLError connect failure"
            return "<html></html>", ""

    class _DummyCrawler(base_mod.BaseCrawler):
        _domains = ["https://a.test", "https://b.test", "https://c.test"]

        @classmethod
        def site(cls):
            return Website.JAVBUS

        @classmethod
        def base_url_(cls):
            return "https://a.test"

        def new_context(self, input):  # noqa: A002  与基类签名一致
            return None

        async def _generate_search_url(self, ctx):
            return "https://a.test/s"

        async def _parse_search_page(self, ctx, html, search_url):
            return None

        async def _parse_detail_page(self, ctx, html, detail_url):
            return None

        async def post_process(self, ctx, data):  # 保持与生命周期兼容
            return None

    async def _main():
        client = _StubClient()
        crawler = _DummyCrawler(client=client)
        crawler._init_rotator(crawler._domains, custom_url="")

        class _Ctx:
            @staticmethod
            def debug(_msg):
                pass

        async def task_a():
            html, _err = await crawler._get_text_with_rotate(_Ctx(), "https://a.test/search")
            # 同任务内可见本任务的换域
            assert html is not None
            return crawler.base_url

        async def task_b():
            await asyncio.sleep(0)
            # B 起步时刻：绝不能看到 A 的轮换结果
            return crawler.base_url

        base_after_a, base_seen_by_b = await asyncio.gather(task_a(), task_b())

        assert base_after_a == "https://b.test", f"A 任务换域后自身应见 b.test，实为 {base_after_a}"
        assert base_seen_by_b == "https://a.test", f"B 任务 sees 被污染: {base_seen_by_b}"
        # 主协程（gather 之外）同样不受任务内写入影响
        assert crawler.base_url == "https://a.test"

    asyncio.run(_main())


def test_javdb_api_mirror_state_is_task_local():
    """javdb_api 的成功镜像/mirror 索引同样是任务级状态（审查项 #3 同族）：
    一个任务记录的成功镜像与轮换位置不得泄漏给并行任务或主协程。"""
    import asyncio

    from mdcx.crawlers.javdb_api import JavdbApiCrawler

    crawler = JavdbApiCrawler(client=object())

    async def writer():
        crawler._successful_mirror = "https://mirror-x.com"
        crawler._mirror_index = 2
        return crawler._successful_mirror, crawler._mirror_index

    async def reader():
        return crawler._successful_mirror, crawler._mirror_index

    async def _main():
        wrote, saw = await asyncio.gather(writer(), reader())
        outside = (crawler._successful_mirror, crawler._mirror_index)
        return wrote, saw, outside

    wrote, saw, outside = asyncio.run(_main())

    assert wrote == ("https://mirror-x.com", 2)
    assert saw == ("", 0), f"reader 被并行任务污染: {saw}"
    assert outside == ("", 0), f"主协程被任务内写法污染: {outside}"


def test_gather_group_timeout_keeps_completed_results():
    """组超时只废未完成任务，已完成结果必须保留（审查项 #9）。"""
    import asyncio

    from mdcx.utils.gather_group import GatherGroup

    async def _main():
        async def fast():
            return "ok"

        async def slow():
            await asyncio.sleep(5)
            return "late"

        async with GatherGroup(timeout=0.2) as group:
            group.add(fast())
            group.add(slow())
        return group.results

    results = asyncio.run(_main())
    assert results[0] == "ok", f"已完成结果被超时丢弃: {results}"
    assert isinstance(results[1], TimeoutError)


def test_crawler_batch_timeout_covers_dmm_window():
    """批级超时不得低于 DMM 自调窗口，否则站点被外层斩杀并把降级原因标成
    '请求超时'（审查项 #8）。"""
    from mdcx.config.manager import manager
    from mdcx.core.file_crawler import _crawler_batch_timeout

    dmm_window = manager.config.timeout * (manager.config.retry + 1) * 2
    assert _crawler_batch_timeout() >= dmm_window


def test_status_code_failure_keeps_connection_pool():
    """可重试状态码只换指纹，不重建连接池——session Cookie 不得被抹掉（审查项 #10）。"""
    import asyncio
    from types import SimpleNamespace

    from mdcx.web_async import AsyncWebClient

    calls = []
    fake = SimpleNamespace(
        _closed=False,
        _excluded_fingerprint_by_pool_base={},
        _fingerprint_states_by_pool_base={"http://example.com": object()},
        _pool_manager=SimpleNamespace(reset=lambda k, r: calls.append(k)),
    )
    asyncio.run(
        AsyncWebClient._record_retryable_response_failure(fake, "HTTP 429", pool_key="http://example.com|fp=f1")
    )
    assert calls == [], f"状态码失败不应触发连接池重建: {calls}"
    assert fake._excluded_fingerprint_by_pool_base["http://example.com"] == "f1"
    assert fake._fingerprint_states_by_pool_base == {}


def test_actor_mapping_falls_back_to_original_name():
    """映射表缺目标语言字段时保留原名，不得把 None 写进演员列表（审查项 #14）。"""
    from types import SimpleNamespace

    from mdcx.core import translate as translate_mod

    fake_res = SimpleNamespace(actors=["Yui Hatano"], all_actors=[])
    fake_resources = SimpleNamespace(
        ensure_data_ready=lambda: None,
        get_actor_data=lambda name: {},
    )
    orig_resources = translate_mod.resources
    try:
        translate_mod.resources = fake_resources
        translate_mod.map_actor_names(fake_res)
        translate_mod.map_actor_names(fake_res, True)
    finally:
        translate_mod.resources = orig_resources
    assert fake_res.actors == ["Yui Hatano"], f"演员映射回落异常: {fake_res.actors}"
    assert fake_res.all_actors == []


def _blank_result():
    from mdcx.models.model_types import BaseCrawlerResult

    inst = BaseCrawlerResult.__new__(BaseCrawlerResult)
    inst.title = ""
    return inst


def _stat_result(ino: int, dev: int, nbytes: int, mtime_ns: int):
    sec = mtime_ns // 10**9
    return os.stat_result((0o644, ino, dev, 1, 0, 0, nbytes, float(sec), float(sec), float(sec), mtime_ns))


def test_creat_folder_samestat_guard_rejects_metadata_collision(tmp_path, monkeypatch):
    """samestat 相同但大小/修改时间不一致时不得判定为同一文件（审查项 #16 护栏）。"""
    import aiofiles.os as aos

    from mdcx.config.manager import manager
    from mdcx.core import file as file_mod
    from mdcx.models.model_types import BaseCrawlerResult, OtherInfo

    monkeypatch.setattr(manager.config, "main_mode", 4, raising=False)
    monkeypatch.setattr(manager.config, "update_mode", "b", raising=False)

    fn_stat = _stat_result(ino=5, dev=7, nbytes=100, mtime_ns=1_000)
    f_stat = _stat_result(ino=5, dev=7, nbytes=200, mtime_ns=1_000)
    stats = {"/x/a.mp4": f_stat, "/s/a.mp4": fn_stat}

    async def fake_stat(path):
        return stats[str(path)]

    async def fake_exists(_p):
        return True

    async def fake_isdir(_p):
        return True

    monkeypatch.setattr(aos, "stat", fake_stat)
    monkeypatch.setattr(aos.path, "exists", fake_exists)
    monkeypatch.setattr(aos.path, "isdir", fake_isdir)

    from pathlib import Path

    other = OtherInfo.empty()
    json_data = BaseCrawlerResult.__new__(BaseCrawlerResult)
    json_data.title = ""
    ok = asyncio_run_compat(
        file_mod.creat_folder(
            other,
            json_data,
            Path("/s"),
            Path("/x/a.mp4"),
            Path("/s/a.mp4"),
            Path("/s/a-thumb.jpg"),
            Path("/s/a-poster.jpg"),
        )
    )
    assert ok is False, "dev/ino 相同但大小不同仍被判同一文件——护栏失效"
    assert other.dont_move_movie is False
    assert "同名文件" in (json_data.title or "")


def test_creat_folder_samestat_accepts_identical_metadata(tmp_path, monkeypatch):
    """dev/ino/大小/mtime 全一致时维持原语义：判定同一文件、标记不移动并继承图路径。"""
    import aiofiles.os as aos

    from mdcx.config.manager import manager
    from mdcx.core import file as file_mod
    from mdcx.models.model_types import OtherInfo

    monkeypatch.setattr(manager.config, "main_mode", 4, raising=False)
    monkeypatch.setattr(manager.config, "update_mode", "b", raising=False)

    same = _stat_result(ino=5, dev=7, nbytes=100, mtime_ns=1_000)
    stats = {"/x/a.mp4": same, "/s/a.mp4": same}

    async def fake_stat(path):
        return stats[str(path)]

    async def fake_exists(_p):
        return True

    async def fake_isdir(_p):
        return True

    monkeypatch.setattr(aos, "stat", fake_stat)
    monkeypatch.setattr(aos.path, "exists", fake_exists)
    monkeypatch.setattr(aos.path, "isdir", fake_isdir)

    from pathlib import Path

    other = OtherInfo.empty()
    ok = asyncio_run_compat(
        file_mod.creat_folder(
            other,
            _blank_result(),
            Path("/s"),
            Path("/x/a.mp4"),
            Path("/s/a.mp4"),
            Path("/s/a-thumb.jpg"),
            Path("/s/a-poster.jpg"),
        )
    )
    assert ok is True
    assert other.dont_move_movie is True
    assert other.thumb_path == Path("/s/a-thumb.jpg")
    assert other.poster_path == Path("/s/a-poster.jpg")
