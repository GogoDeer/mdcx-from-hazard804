import sys

sys.stdout.reconfigure(encoding="utf-8")
import asyncio
from pathlib import Path

from mdcx.config.manager import manager
from mdcx.core.file import get_file_info_v2
from mdcx.core.file_crawler import FileScraper, classify_scrape_task
from mdcx.crawler import CrawlerProvider
from mdcx.utils.phash import clear_cached_scenes

config_path = r"D:\App\SeTools\MDC\MDCx-diy\config-inbox-202609.json"
files = [
    r"I:\Incoming\Vdo\scan\input\孕\PrivateSociety-Kasey\Kasey - She Thinks It Might Be His 26-11-2022.mp4",
    r"I:\Incoming\Vdo\scan\input\孕\PrivateSociety-Kasey\Kasey - Were Betting Its Half Black 20-12-2022.mp4",
]


async def main():
    manager.path = config_path
    manager.load()
    print("Loaded config from:", config_path)
    print("website_oumei:", manager.config.website_oumei)
    print("javstash_api_key:", manager.config.javstash_api_key[:15], "...")
    print("stashdb_api_key:", manager.config.stashdb_api_key[:15], "...")
    print("use_phash_number:", manager.config.use_phash_number)
    print("=" * 60)

    clear_cached_scenes()
    client = manager.computed.async_client
    provider = CrawlerProvider(manager.config, client)
    scraper = FileScraper(manager.config, provider)

    for f in files:
        path = Path(f)
        print(f"\nProcessing: {path.name}")
        if not path.exists():
            print("  ERROR: File not found!")
            continue

        # 1. Step 1: Extract number / info via get_file_info_v2
        file_info = await get_file_info_v2(path, copy_sub=False)
        print(f"  Extracted Number: '{file_info.number}'")

        # 2. Step 2: Scrape via FileScraper (simulating MDCx pipeline)
        task = file_info.crawl_task()
        classification = classify_scrape_task(task, manager.config)
        print(
            f"  Scrape Classification: {classification.scraping_type} (sites: {[s.value for s in classification.sites]})"
        )

        res = await scraper.run(task, file_mode=0)
        if res:
            print("  SUCCESS!")
            print(f"    Title: {res.title}")
            print(f"    Studio: {res.studio}")
            print(f"    Release: {res.release} (Year: {res.year})")
            print(f"    Actors: {res.actor}")
            print(f"    All Actors: {res.all_actor}")
            print(f"    Poster: {res.poster}")
            print(f"    Outline: {res.outline[:60]}...")
        else:
            print("  FAILED to scrape.")
        print("-" * 60)


if __name__ == "__main__":
    asyncio.run(main())
