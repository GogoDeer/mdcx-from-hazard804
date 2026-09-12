import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

log_path = Path(r"D:\App\SeTools\MDC\MDCx-diy\Log\2026-09-10-14-35-00.txt")
content = log_path.read_text(encoding="utf-8", errors="ignore")

# Let's parse each video block from the log
# Blocks often start with:
# 🔍 开始刮削: [filename] or similar
# Or we can split by:
# 🐵 [Movie] [input_path]
# Let's inspect what patterns exist

entries = re.findall(
    r"(🐵 \[Movie\] (.*?)\n.*?"
    r"number\s+:\s+(.*?)\n.*?"
    r"title\s+:\s+(.*?)\n.*?"
    r"(?:originaltitle\s+:\s+(.*?)\n)?"
    r"(?:actor\s+:\s+(.*?)\n)?"
    r"(?:studio\s+:\s+(.*?)\n)?"
    r".*?🙉 \[Movie\] (.*?)\n)",
    content,
    re.DOTALL,
)

print(f"Regex matched {len(entries)} full movie scrape records.")

if not entries:
    # Try alternative matching
    print("Alternative pattern search...")
    # Find all '🐵 [Movie]' positions
    movie_positions = [m.start() for m in re.finditer(r"🐵 \[Movie\]", content)]
    print(f"Found {len(movie_positions)} '🐵 [Movie]' markers")
    for i, pos in enumerate(movie_positions):
        end_pos = movie_positions[i + 1] if i + 1 < len(movie_positions) else len(content)
        chunk = content[pos:end_pos]

        input_m = re.search(r"🐵 \[Movie\] (.*)", chunk)
        output_m = re.search(r"🙉 \[Movie\] (.*)", chunk)
        num_m = re.search(r"number\s+:\s+(.*)", chunk)
        title_m = re.search(r"title\s+:\s+(.*)", chunk)
        otitle_m = re.search(r"originaltitle\s+:\s+(.*)", chunk)
        actor_m = re.search(r"actor\s+:\s+(.*)", chunk)
        studio_m = re.search(r"studio\s+:\s+(.*)", chunk)
        website_m = re.search(r"🍀 Thumb done! \((.*?)\)", chunk)
        data_done_m = re.search(r"🍀 Data done!", chunk)

        # also find which crawler was used:
        # e.g. 🟢 javdb_api, 🟢 fcdb, 🟢 javbus, etc.
        green_sites = re.findall(r"🟢 ([\w\-_]+)", chunk)

        print(f"\n[{i + 1}/25] ========================================")
        print(f"  Input File  : {input_m.group(1).strip() if input_m else '?'}")
        print(f"  Extracted No: {num_m.group(1).strip() if num_m else '?'}")
        print(f"  Matched Site: {green_sites[-1] if green_sites else (website_m.group(1) if website_m else '?')}")
        print(f"  Title       : {title_m.group(1).strip() if title_m else '?'}")
        if otitle_m:
            print(f"  Orig Title  : {otitle_m.group(1).strip()}")
        print(f"  Actor       : {actor_m.group(1).strip() if actor_m else 'None/Unknown'}")
        print(f"  Studio      : {studio_m.group(1).strip() if studio_m else '?'}")
        print(f"  Output Path : {output_m.group(1).strip() if output_m else '?'}")
