"""Command Line Interface for Archive Mover."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .alias_resolver import AliasResolver
from .mover import ArchiveMover
from .reporter import ReportGenerator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="视频归档智能整理工具 (Archive Mover)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--source",
        "-s",
        default=r"\\192.168.1.8\ZoneB\temp\9-13\无码",
        help="源暂存目录 (Source intake directory)",
    )
    parser.add_argument(
        "--target",
        "-t",
        default=r"\\192.168.1.8\ZoneB\mov\步兵",
        help="目标归档目录 (Target archive directory containing categories)",
    )
    parser.add_argument(
        "--actor-db",
        "-d",
        default=str(Path(__file__).resolve().parents[2] / "userdata" / "actor_database.xlsx"),
        help="本地演员别名库 Excel 路径",
    )
    parser.add_argument(
        "--no-actor-db",
        action="store_true",
        help="禁用本地 Excel 演员别名库",
    )
    parser.add_argument(
        "--stash-url",
        default="",
        help="Stash 服务器地址 (例如: http://192.168.1.8:9999)",
    )
    parser.add_argument(
        "--stash-key",
        default="",
        help="Stash API 令牌 (ApiKey)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="正式执行移动操作 (默认仅为模拟预演 --dry-run)",
    )
    parser.add_argument(
        "--clean-empty",
        action="store_true",
        default=True,
        help="移动完成后自动清理源端已变空的演员文件夹",
    )
    parser.add_argument(
        "--no-clean-empty",
        dest="clean_empty",
        action="store_false",
        help="移动完成后保留源端空演员文件夹",
    )
    parser.add_argument(
        "--exclude",
        "-e",
        action="append",
        default=[],
        help="排除的目标归档分类或目录 (可多次指定或用逗号分隔，如: -e 流出 -e 专题\\肛交)",
    )
    parser.add_argument(
        "--report-dir",
        default=str(Path(__file__).resolve().parents[2] / "reports"),
        help="报告生成存放目录",
    )
    return parser


def run_cli(args: argparse.Namespace | None = None) -> int:
    if args is None:
        parser = build_parser()
        args = parser.parse_args()

    dry_run = not args.execute

    exclude_dirs: list[str] = []
    if args.exclude:
        for exc in args.exclude:
            for part in str(exc).split(","):
                if part.strip():
                    exclude_dirs.append(part.strip())

    print("=" * 65)
    print(" 🎬 视频归档智能整理工具 (Archive Mover)")
    print(f" 模式: {'【模拟预演 Dry-Run (安全，不触碰文件)】' if dry_run else '【正式执行 Live-Run】'}")
    print(f" 源暂存目录: {args.source}")
    print(f" 目标归档目录: {args.target}")
    if exclude_dirs:
        print(f" 排除分类目录: {', '.join(exclude_dirs)}")
    print("=" * 65)

    # 1. Initialize Alias Resolver
    alias_resolver = AliasResolver(
        excel_path=None if args.no_actor_db else args.actor_db,
        stash_url=args.stash_url,
        stash_api_key=args.stash_key,
    )

    if not args.no_actor_db and Path(args.actor_db).exists():
        print(f"📖 正在加载本地演员别名库: {args.actor_db}...")
        count = alias_resolver.load_excel()
        print(f"   已加载 {count} 位演员别名记录")

    if args.stash_url:
        print(f"🌐 正在连接 Stash API ({args.stash_url})...")
        s_count = alias_resolver.load_stash()
        print(f"   已从 Stash 载入 {s_count} 位 Performer 数据")

    # 2. Evaluate Plan
    mover = ArchiveMover(
        alias_resolver=alias_resolver,
        dry_run=dry_run,
        clean_empty_dirs=args.clean_empty,
    )

    def print_progress(pct: int, total: int, msg: str):
        bar_len = 25
        filled = int((pct / total) * bar_len)
        bar = "█" * filled + "░" * (bar_len - filled)
        sys.stdout.write(f"\r[{bar}] {pct}% - {msg[:40]:<40}")
        sys.stdout.flush()

    print("\n🔍 正在扫描并分析匹配关系...")
    try:
        report, target_index = mover.evaluate_plan(
            args.source,
            args.target,
            exclude_dirs=exclude_dirs,
            progress_cb=print_progress,
        )
        print("\n")
    except Exception as e:
        print(f"\n❌ 扫描失败: {e}")
        return 1

    # 3. Print Quick Summary
    moved_candidates = [it for it in report.items if it.status.value in ("待移动", "模拟移动", "移动成功")]
    dup_items = [it for it in report.items if "重复" in it.status.value]
    no_actor_items = [it for it in report.items if "未建档" in it.status.value]

    print("-" * 65)
    print(f" 📊 扫描分析结果 (耗时: {report.scan_time_seconds:.2f}s):")
    print(f"   • 目标端: {report.total_target_categories} 个分类, {report.total_target_actors} 位演员")
    print(f"   • 源端发现: {report.total_source_actors} 位演员, 共 {report.total_source_codes} 个番号")
    print(f"   • 🟢 {'计划移动' if dry_run else '可移动'}: {len(moved_candidates)} 个")
    print(f"   • 🔴 重复跳过: {len(dup_items)} 个")
    print(f"   • 🟡 目标未建档: {len(no_actor_items)} 个")
    print("-" * 65)

    # 4. Execute (or dry-run execute)
    print(f"\n🚀 正在执行{'模拟' if dry_run else '真实'}移动...")
    mover.execute_moves(report, target_index, progress_cb=print_progress)
    print("\n")

    # 5. Generate Reports
    md_file, html_file = ReportGenerator.save_reports(report, args.report_dir)
    print("=" * 65)
    print(" 🎉 整理完成！报告已保存至:")
    print(f"   📄 Markdown 报告: {md_file}")
    print(f"   🌐 HTML 报告:     {html_file}")
    print("=" * 65)

    if dry_run and len(moved_candidates) > 0:
        print("\n💡 提示：当前为【模拟预演】。如确认无误，可加上 --execute 参数正式移动：")
        print("   uv run python tools/archive_mover/run.py --execute")

    return 0


if __name__ == "__main__":
    sys.exit(run_cli())
