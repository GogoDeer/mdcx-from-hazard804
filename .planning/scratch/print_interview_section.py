import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

log_path = Path(r"D:\App\SeTools\MDC\MDCx-diy\Log\2026-09-10-14-35-00.txt")
content = log_path.read_text(encoding="utf-8", errors="ignore")

# Find the section containing "heydouga 4037-531-real interview 316"
idx = content.find("heydouga 4037-531-real interview 316")
if idx != -1:
    print(content[idx - 100 : idx + 2000])
else:
    print("Not found")
