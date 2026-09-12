import sys

sys.stdout.reconfigure(encoding="utf-8")
import asyncio
import time
from pathlib import Path

from mdcx.config.manager import manager

manager._path = Path(r"D:\App\SeTools\MDC\MDCx-diy\config-inbox-202609.json")
manager.load()

from mdcx.core.file import get_file_info_v2
from mdcx.core.file_crawler import FileScraper
from mdcx.crawler import CrawlerProvider
from mdcx.models.enums import FileMode


async def main():
    with manager.acquire_computed() as computed:
        provider = CrawlerProvider(manager.config, computed.async_client, config_getter=lambda: manager.config)
        file_path = Path(r"I:\Incoming\Vdo\scan\input\100521_01-10mu-1080p\100521_01-10mu-1080p.mp4")
        file_info = await get_file_info_v2(file_path)
        crawl_task = file_info.crawl_task()
        scraper = FileScraper(manager.config, provider)
        print(f"Starting FileScraper.run for {file_info.number}...")
        t0 = time.time()
        try:
            res = await asyncio.wait_for(scraper.run(crawl_task, FileMode.Default), timeout=60)
            print("FileScraper result title:", res.title if res else None, "elapsed:", time.time() - t0)
        except Exception as e:
            print("Exception:", type(e), e)
        finally:
            await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
