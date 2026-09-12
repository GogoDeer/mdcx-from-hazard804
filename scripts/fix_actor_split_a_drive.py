r"""修复 A:\mov\步兵\肥白大\折原ほのか 下 5 部影片的 NFO 文件。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

TARGET_DIRS = ["061422_001", "090122_001", "101422-001", "113024-001", "HEYZO-1265"]


def update_nfos(
    base_dir: Path = Path(r"A:\mov\步兵\肥白大\折原ほのか"),
    dry_run: bool = False,
) -> int:
    changed_count = 0
    print(f"扫描目录: {base_dir}")
    print(f"模式: {'[Dry Run 仅演练]' if dry_run else '[实际执行修改]'}\n")

    for dir_name in TARGET_DIRS:
        sub = base_dir / dir_name
        if not sub.exists():
            print(f"⚠️ 目录不存在: {sub}")
            continue

        for nfo in sub.glob("*.nfo"):
            original = nfo.read_text(encoding="utf-8", errors="ignore")
            updated = original

            # 替换演员、标签、分类
            updated = updated.replace("<name>神无月丽奈</name>", "<name>折原ほのか</name>")
            updated = updated.replace("<tag>神无月丽奈</tag>", "<tag>折原ほのか</tag>")
            updated = updated.replace("<genre>神无月丽奈</genre>", "<genre>折原ほのか</genre>")

            # 替换头像路径
            updated = updated.replace(
                "/config/metadata/People/神/神无月丽奈/folder.jpg",
                "/config/metadata/People/折/折原ほのか/folder.jpg",
            )

            if updated != original:
                changed_count += 1
                print(f"📝 发现待更新 NFO: {sub.name}/{nfo.name}")
                if not dry_run:
                    nfo.write_text(updated, encoding="utf-8")
                    print(f"  ✅ 成功写入更新: {nfo.name}")
            else:
                print(f"ℹ️ 无需更新: {sub.name}/{nfo.name}")

    print(f"\n共处理 {changed_count} 个 NFO 文件。")
    return changed_count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="更新 A 盘折原ほのか NFO 中的演员名称")
    parser.add_argument("--dry-run", action="store_true", help="只演练不写入")
    args = parser.parse_args()

    update_nfos(dry_run=args.dry_run)
