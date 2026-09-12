import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

log_path = Path(r"D:\App\SeTools\MDC\MDCx-diy\Log\2026-09-10-14-35-00.txt")
content = log_path.read_text(encoding="utf-8", errors="ignore")

file_blocks = re.split(r"(?=🙈 \[file\])", content)[1:15]

for i, b in enumerate(file_blocks, 1):
    file_m = re.search(r"🙈 \[file\] (.*)", b)
    f_name = file_m.group(1).strip() if file_m else "?"

    num_m = re.search(r"🚘 \[number\] (.*)", b)
    num = num_m.group(1).strip() if num_m else "?"

    out_m = re.search(r"🙉 \[Movie\] (.*)", b)
    out_p = out_m.group(1).strip() if out_m else "?"

    title_m = re.search(r"title\s*:\s*(.*)", b)
    title = title_m.group(1).strip() if title_m else ""

    actor_m = re.search(r"actors\s*:\s*(.*)", b)
    actor = actor_m.group(1).strip() if actor_m else ""

    studio_m = re.search(r"studio\s*:\s*(.*)", b)
    studio = studio_m.group(1).strip() if studio_m else ""

    web_m = re.search(r"🍀 (?:Data|Thumb) done! \((.*?)\)", b)
    web = web_m.group(1) if web_m else "?"

    print(f"[{i:02d}] 原始文件: {f_name}")
    print(f"     识别番号: {num} (匹配站点: {web})")
    print(f"     标题    : {title}")
    print(f"     演员/片商: {actor} | {studio}")
    print(f"     输出路径: {out_p}")
    print("-" * 80)
