"""修复存量视频的演员分裂问题：将神无月丽奈重命名并迁移至折原ほのか。"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

# Windows 控制台编码保护
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")


def fix_actor_split(
    source_root: Path = Path(r"I:\Incoming\Vdo\scan-done\神无月丽奈\060526-001"),
    target_root: Path = Path(r"I:\Incoming\Vdo\scan-done\折原ほのか\060526-001"),
    dry_run: bool = False,
) -> bool:
    print(f"源路径: {source_root}")
    print(f"目标路径: {target_root}")

    if not source_root.exists():
        print(f"❌ 源路径不存在: {source_root}")
        return False

    if target_root.exists():
        print(f"❌ 目标路径已存在: {target_root}，请先手动检查！")
        return False

    nfo_file = source_root / "060526-001.nfo"
    if nfo_file.exists():
        content = nfo_file.read_text(encoding="utf-8")
        updated = content.replace("<name>神无月丽奈</name>", "<name>折原ほのか</name>")
        updated = updated.replace("<tag>神无月丽奈</tag>", "<tag>折原ほのか</tag>")
        updated = updated.replace("<genre>神无月丽奈</genre>", "<genre>折原ほのか</genre>")
        if content != updated:
            print("📝 检测到 NFO 文件中的 '神无月丽奈'，准备更新为 '折原ほのか'")
            if not dry_run:
                nfo_file.write_text(updated, encoding="utf-8")
                print("✅ 成功更新 NFO 文件！")
        else:
            print("ℹ️ NFO 文件中未找到 '神无月丽奈' 或已更新。")

    if dry_run:
        print("🔍 [Dry Run] 模拟完成，未实际移动文件。")
        return True

    target_parent = target_root.parent
    target_parent.mkdir(parents=True, exist_ok=True)

    print(f"🚚 正在移动文件夹: {source_root} -> {target_root}")
    shutil.move(str(source_root), str(target_root))
    print("✅ 移动完成！")

    # 清理空的旧演员目录
    old_parent = source_root.parent
    if old_parent.exists() and not any(old_parent.iterdir()):
        try:
            old_parent.rmdir()
            print(f"🧹 清理空目录: {old_parent}")
        except Exception as e:
            print(f"⚠️ 清理空目录失败: {e}")

    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="修复神无月丽奈/折原ほのか存量文件")
    parser.add_argument("--dry-run", action="store_true", help="只演练不修改")
    args = parser.parse_args()

    fix_actor_split(dry_run=args.dry_run)
