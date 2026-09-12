import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

log_path = Path(r"D:\App\SeTools\MDC\MDCx-diy\Log\2026-09-10-14-35-00.txt")
content = log_path.read_text(encoding="utf-8", errors="ignore")

# Split the content by the completion lines or round markers:
# ========================================
# x/25 (xx.xx%) round(1) ...

rounds = re.split(r"(?=={30,}\s*\n\s*\d+/25)", content)
print(f"Total round splits: {len(rounds)}")

results = []

for idx, r in enumerate(rounds):
    # check if this round has 🙈 [file]
    file_m = re.search(r"🙈 \[file\] (.*)", r)
    if not file_m:
        continue

    file_path = file_m.group(1).strip()
    num_m = re.search(r"🚘 \[number\] (.*)", r)
    number = num_m.group(1).strip() if num_m else "?"

    # pHash info
    phash_hit = "未命中/未启用"
    if "✅ [pHash识别] 成功通过指纹精准命中" in r:
        phash_m = re.search(r"✅ \[pHash识别\] 成功通过指纹精准命中 (.*)", r)
        phash_hit = f"命中: {phash_m.group(1).strip()}" if phash_m else "命中"
    elif "🟡 [pHash识别] 视频指纹在 JavStash / StashDB 中均未收录" in r:
        phash_hit = "JavStash/StashDB 未收录指纹 -> 回退正则"

    # title
    title_m = re.search(r"📌 title \s*=+\s*.*?\n\s*🟢 ([\w\-_]+)\s*\n\s*↳(.*)", r)
    title_site = title_m.group(1) if title_m else "?"
    title_val = title_m.group(2).strip() if title_m else "?"

    # actors
    actors_m = re.search(r"📌 (?:actors|all_actors) \s*=+\s*.*?\n\s*🟢 ([\w\-_]+)\s*\n\s*↳(.*)", r)
    actor_val = actors_m.group(2).strip() if actors_m else "无/未提取"

    # studio
    studio_m = re.search(r"📌 studio \s*=+\s*.*?\n\s*🟢 ([\w\-_]+)\s*\n\s*↳(.*)", r)
    studio_val = studio_m.group(2).strip() if studio_m else "?"

    # output movie
    out_m = re.search(r"🙉 \[Movie\] (.*)", r)
    out_val = out_m.group(1).strip() if out_m else "?"

    results.append(
        {
            "file": file_path,
            "number": number,
            "phash": phash_hit,
            "title": title_val,
            "title_site": title_site,
            "actor": actor_val,
            "studio": studio_val,
            "output": out_val,
        }
    )

print(f"\nParsed {len(results)} movies:")
for i, item in enumerate(results, 1):
    print(f"\n[{i:02d}] 原始文件: {item['file']}")
    print(f"     识别番号: {item['number']}")
    print(f"     指纹状态: {item['phash']}")
    print(f"     来源站点: {item['title_site']}")
    print(f"     标题    : {item['title'][:60]}...")
    print(f"     演员    : {item['actor']}")
    print(f"     片商    : {item['studio']}")
    print(f"     输出路径: {item['output']}")
