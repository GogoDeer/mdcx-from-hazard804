import sys

sys.stdout.reconfigure(encoding="utf-8")
import asyncio
import time
from pathlib import Path

from mdcx.config.manager import manager

manager._path = Path(r"D:\App\SeTools\MDC\MDCx-diy\config-inbox-202609.json")
manager.load()

from mdcx.crawler import CrawlerProvider


async def main():
    with manager.acquire_computed() as computed:
        provider = CrawlerProvider(manager.config, computed.async_client, config_getter=lambda: manager.config)
    from mdcx.core.file import get_file_info_v2

    file_info = await get_file_info_v2(
        Path(r"I:\Incoming\Vdo\scan\input\100521_01-10mu-1080p\100521_01-10mu-1080p.mp4")
    )
    print("Testing get_data for 100521_01...")
    t0 = time.time()
    try:
        data, other = await asyncio.wait_for(provider.get_data(file_info), timeout=60)
        print("Data retrieved:", bool(data), "elapsed:", time.time() - t0)
    except Exception as e:
        print("Exception in get_data:", type(e), e)
    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(main())
