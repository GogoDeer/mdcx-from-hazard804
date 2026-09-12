import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from mdcx.utils.javstash_utils import verify_stashbox_connection_sync

config_path = Path(r"D:\App\SeTools\MDC\MDCx-diy\config-inbox-202609.json")
if not config_path.exists():
    print(f"Config file not found: {config_path}")
    sys.exit(1)

with open(config_path, encoding="utf-8") as f:
    config = json.load(f)

url = config.get("stashdb_url", "https://stashdb.org")
api_key = config.get("stashdb_api_key", "")
use_proxy = config.get("use_proxy", False)
proxy = config.get("proxy", "") if use_proxy else None

print(f"Testing StashDB with URL: {url}")
print(f"API Key present: {bool(api_key)}")
print(f"Proxy: {proxy}")

success, tip = verify_stashbox_connection_sync(url, api_key, proxy=proxy, timeout=15, service_name="StashDB")
print(f"Result success: {success}")
print(f"Result message: {tip}")
