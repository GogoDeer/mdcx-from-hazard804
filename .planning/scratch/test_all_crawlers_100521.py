import sys

sys.stdout.reconfigure(encoding="utf-8")
import asyncio
import time
from pathlib import Path

from mdcx.config.manager import manager

manager._path = Path(r"D:\App\SeTools\MDC\MDCx-diy\config-inbox-202609.json")
manager.load()

from mdcx.config.enums import Website
from mdcx.crawler import CrawlerProvider


async def main():
    sites = [
        Website.IQQTV,
        Website.AVSOX,
        Website.JAVBUS,
        Website.OFFICIAL,
        Website.JAVSTASH,
        Website.JAVDB,
        Website.JAVDB_API,
        Website.JAVDB_APP,
        Website.JAVDAY,
        Website.MISSAV,
        Website.AVENTERTAINMENTS,
        Website.AVSEX,
    ]
    from mdcx.core.file import get_file_info_v2

    file_path = Path(r"I:\Incoming\Vdo\scan\input\100521_01-10mu-1080p\100521_01-10mu-1080p.mp4")
    file_info = await get_file_info_v2(file_path)
    inp = file_info.crawl_task()

    with manager.acquire_computed() as computed:
        provider = CrawlerProvider(manager.config, computed.async_client, config_getter=lambda: manager.config)
        for site in sites:
            print(f"Testing {site.value}...")
            t0 = time.time()
            try:
                crawler = await provider.get(site)
                res = await asyncio.wait_for(crawler.run(inp), timeout=15)
                elapsed = time.time() - t0
                status = "HIT" if res and getattr(res, "success", False) else "MISS/FAIL"
                print(f"  [{site.value}] {status} in {elapsed:.2f}s")
            except TimeoutError:
                print(f"  [{site.value}] TIMEOUT (>15s)")
            except Exception as e:
                elapsed = time.time() - t0
                print(f"  [{site.value}] ERROR: {type(e).__name__}: {e} in {elapsed:.2f}s")
        await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
