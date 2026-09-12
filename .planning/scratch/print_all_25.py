import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

log_path = Path(r"D:\App\SeTools\MDC\MDCx-diy\Log\2026-09-10-14-35-00.txt")
content = log_path.read_text(encoding="utf-8", errors="ignore")

rounds = re.split(r"(?=={30,}\s*\n\s*\d+/25)", content)

for idx, r in enumerate(rounds):
    file_m = re.search(r"🙈 \[file\] (.*)", r)
    if not file_m:
        continue
    file_path = file_m.group(1).strip()
    num_m = re.search(r"🚘 \[number\] (.*)", r)
    number = num_m.group(1).strip() if num_m else "?"

    # Check title
    title_m = re.search(r"title\s*:\s*(.*)", r)
    title = title_m.group(1).strip() if title_m else "?"

    # Check actor
    actor_m = re.search(r"actor\s*:\s*(.*)", r)
    actor = actor_m.group(1).strip() if actor_m else "None"

    # Check studio
    studio_m = re.search(r"studio\s*:\s*(.*)", r)
    studio = studio_m.group(1).strip() if studio_m else "?"

    out_m = re.search(r"🙉 \[Movie\] (.*)", r)
    out_path = out_m.group(1).strip() if out_m else "?"

    # Check website
    web_m = re.search(r"🍀 (?:Data|Thumb) done! \((.*?)\)", r)
    web = web_m.group(1) if web_m else "?"

    print(f"[{idx:02d}] FILE: {file_path}")
    print(f"     NUM : {number} | SITE: {web}")
    print(f"     ACT : {actor} | STUDIO: {studio}")
    print(f"     TTL : {title[:60]}")
    print(f"     OUT : {out_path}\n")
