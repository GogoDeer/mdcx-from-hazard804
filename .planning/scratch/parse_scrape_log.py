import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

log_path = Path(r"D:\App\SeTools\MDC\MDCx-diy\Log\2026-09-10-14-35-00.txt")
content = log_path.read_text(encoding="utf-8", errors="ignore")

# Split by movie blocks or search patterns
# Look for:
# "Start scrape: ..." or "Find 25 movies"
print(f"Log size: {len(content)} characters")

# Find the list of movies found at start
found_match = re.search(r"🔎 Searching all videos, Please wait\.\.\..*?📺 Find (\d+) movies", content, re.DOTALL)
if found_match:
    print(found_match.group(0)[:500])

# Let's extract all movie scraping entries
# Patterns like:
# 🕷 [timestamp] [index]/[total] [filename] 刮削完成！
# or [Movie] output path
# or number : ...
lines = content.splitlines()
current_movie = {}
movies = []

movie_starts = [
    i
    for i, line in enumerate(lines)
    if "Start scrape:" in line or "开始刮削" in line or "Scraping (" in line or "[Movie]" in line
]
print(f"Found {len(movie_starts)} markers")

# Let's search for all completed movies:
# 🕷 14:xx:xx x/25 xxx.mp4 刮削完成！用时 xx 秒！
completed = re.findall(r"🕷 \d+:\d+:\d+ \d+/25 (.*?) 刮削完成！用时 ([\d\.]+) 秒！", content)
print(f"Completed count: {len(completed)}")
for f, t in completed:
    print(f"  - {f} ({t}s)")
