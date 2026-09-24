"""Report generation in Markdown and modern HTML formats."""

from __future__ import annotations

import datetime
from pathlib import Path

from .models import MoveItem, MoveStatus, ProcessReport


class ReportGenerator:
    """Generates Markdown and HTML reports from a ProcessReport."""

    @staticmethod
    def generate_markdown(report: ProcessReport) -> str:
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        mode_str = "【模拟预演 (Dry-Run)】" if report.is_dry_run else "【真实执行 (Live Run)】"

        moved_items = [
            it for it in report.items if it.status in (MoveStatus.MOVED, MoveStatus.DRY_RUN_MOVED, MoveStatus.READY)
        ]
        dup_items = [it for it in report.items if it.status == MoveStatus.SKIP_DUPLICATE]
        no_actor_items = [it for it in report.items if it.status == MoveStatus.SKIP_NO_ACTOR]
        error_items = [it for it in report.items if it.status == MoveStatus.ERROR]

        lines = [
            f"# 视频归档整理报告 {mode_str}",
            f"- **生成时间**：{now_str}",
            f"- **源暂存路径**：`{report.source_dir}`",
            f"- **目标归档路径**：`{report.target_dir}`",
            f"- **运行模式**：{'模拟预演 (Dry-Run)' if report.is_dry_run else '正式移动'}",
            f"- **自动清理空目录**：{'是' if report.clean_empty_dirs else '否'}",
        ]
        if report.excluded_dirs:
            lines.append(f"- **排除分类/目录**：{', '.join(f'`{e}`' for e in report.excluded_dirs)}")
        lines.extend(
            [
                f"- **扫描与评估耗时**：{report.scan_time_seconds:.2f} 秒",
                "",
                "## 📊 统计汇总",
                "| 项目 | 数量 | 说明 |",
                "| :--- | :--- | :--- |",
                f"| **源端演员数** | {report.total_source_actors} 位 | 暂存区发现的演员文件夹数 |",
                f"| **源端番号数** | {report.total_source_codes} 个 | 待整理的番号文件夹总数 |",
                f"| **目标分类数** | {report.total_target_categories} 个 | 归档区的分类目录总数 |",
                f"| **目标演员数** | {report.total_target_actors} 位 | 归档区已建档的演员总数 |",
                f"| **{'计划移动' if report.is_dry_run else '成功移动'}** | **{len(moved_items)}** | 目标存在该演员且无番号冲突 |",
                f"| **重复跳过** | **{len(dup_items)}** | 目标分类已存在同名番号目录 |",
                f"| **未建档跳过** | **{len(no_actor_items)}** | 归档区暂未建立该演员目录 |",
                f"| **异常失败** | **{len(error_items)}** | 文件操作或网络权限等异常 |",
                f"| **清理空演员目录** | **{len(report.cleaned_empty_actors)}** 个 | 源端番号全部移走后的空目录 |",
                "",
            ]
        )

        # 1. Moved Items
        lines.append(f"## 🟢 {'计划移动' if report.is_dry_run else '已成功移动'}列表 ({len(moved_items)})")
        if moved_items:
            lines.extend(
                [
                    "| 源演员 | 番号目录 | 目标分类 | 目标演员 | 匹配模式 | 目标完整路径 |",
                    "| :--- | :--- | :--- | :--- | :--- | :--- |",
                ]
            )
            for it in moved_items:
                dest = str(it.target_code_path) if it.target_code_path else "-"
                lines.append(
                    f"| {it.source_actor} | `{it.source_code}` | {it.target_category} | "
                    f"{it.target_actor} | {it.match_type} | `{dest}` |"
                )
        else:
            lines.append("*无符合移动条件的项目。*")
        lines.append("")

        # 2. Duplicates
        lines.append(f"## 🔴 重复番号跳过列表 ({len(dup_items)})")
        if dup_items:
            lines.extend(
                [
                    "| 源演员 | 番号目录 | 目标归属分类/演员 | 跳过原因 |",
                    "| :--- | :--- | :--- | :--- |",
                ]
            )
            for it in dup_items:
                loc = f"{it.target_category} / {it.target_actor}" if it.target_category else "-"
                lines.append(f"| {it.source_actor} | `{it.source_code}` | {loc} | {it.reason} |")
        else:
            lines.append("*未发现重复番号。*")
        lines.append("")

        # 3. No Actor Found
        lines.append(f"## 🟡 目标未建档演员跳过列表 ({len(no_actor_items)})")
        if no_actor_items:
            lines.extend(
                [
                    "| 源演员目录名 | 涉及番号 | 建议处理方案 |",
                    "| :--- | :--- | :--- |",
                ]
            )
            for it in no_actor_items:
                lines.append(
                    f"| {it.source_actor} | `{it.source_code}` | "
                    f"请在 `{report.target_dir}\\<对应分类>` 下手动新建该演员文件夹后重新扫描 |"
                )
        else:
            lines.append("*所有源演员均在归档区已建档。*")
        lines.append("")

        # 4. Cleaned empty dirs
        if report.cleaned_empty_actors:
            action_desc = "计划清理的源端空演员目录" if report.is_dry_run else "已成功清理的源端空演员目录"
            lines.append(f"## 🧹 {action_desc} ({len(report.cleaned_empty_actors)})")
            for act in report.cleaned_empty_actors:
                lines.append(f"- `{act}`")
            lines.append("")

        # 5. Errors
        if error_items:
            lines.append(f"## ⚠️ 异常错误列表 ({len(error_items)})")
            lines.extend(
                [
                    "| 源演员 | 番号 | 错误信息 |",
                    "| :--- | :--- | :--- |",
                ]
            )
            for it in error_items:
                lines.append(f"| {it.source_actor} | `{it.source_code}` | {it.reason} |")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def generate_html(report: ProcessReport) -> str:
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        mode_badge = "预演 (Dry-Run)" if report.is_dry_run else "正式执行"
        badge_color = "#3b82f6" if report.is_dry_run else "#10b981"

        moved_items = [
            it for it in report.items if it.status in (MoveStatus.MOVED, MoveStatus.DRY_RUN_MOVED, MoveStatus.READY)
        ]
        dup_items = [it for it in report.items if it.status == MoveStatus.SKIP_DUPLICATE]
        no_actor_items = [it for it in report.items if it.status == MoveStatus.SKIP_NO_ACTOR]
        error_items = [it for it in report.items if it.status == MoveStatus.ERROR]

        def render_rows(items: list[MoveItem], is_moved=False) -> str:
            if not items:
                return "<tr><td colspan='6' style='text-align:center; color:#6b7280;'>无记录</td></tr>"
            html_rows = []
            for it in items:
                dest = str(it.target_code_path) if it.target_code_path else "-"
                cat = it.target_category or "-"
                act = it.target_actor or "-"
                html_rows.append(
                    f"<tr><td><b>{it.source_actor}</b></td>"
                    f"<td><code>{it.source_code}</code></td>"
                    f"<td>{cat}</td>"
                    f"<td>{act}</td>"
                    f"<td><span class='badge'>{it.match_type}</span></td>"
                    f"<td style='font-size:12px; color:#4b5563;'><code>{dest}</code></td></tr>"
                )
            return "\n".join(html_rows)

        exc_html = (
            f"<div><b>排除分类/目录：</b><code>{', '.join(report.excluded_dirs)}</code></div>"
            if report.excluded_dirs
            else ""
        )

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>视频归档整理报告</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; background-color: #f9fafb; color: #1f2937; margin: 0; padding: 24px; }}
  .container {{ max-width: 1200px; margin: 0 auto; background: #ffffff; border-radius: 12px; padding: 32px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }}
  h1 {{ margin-top: 0; display: flex; align-items: center; gap: 12px; font-size: 24px; }}
  .badge {{ display: inline-block; padding: 4px 10px; border-radius: 9999px; font-size: 13px; font-weight: 600; color: #fff; background-color: {badge_color}; }}
  .meta-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; margin: 20px 0; background: #f3f4f6; padding: 16px; border-radius: 8px; font-size: 14px; }}
  .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 16px; margin: 24px 0; }}
  .card {{ background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; text-align: center; }}
  .card-num {{ font-size: 28px; font-weight: bold; margin-top: 4px; }}
  .card.green .card-num {{ color: #10b981; }}
  .card.red .card-num {{ color: #ef4444; }}
  .card.yellow .card-num {{ color: #f59e0b; }}
  .card.blue .card-num {{ color: #3b82f6; }}
  h2 {{ border-bottom: 2px solid #e5e7eb; padding-bottom: 8px; margin-top: 36px; font-size: 18px; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 14px; }}
  th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid #e5e7eb; }}
  th {{ background: #f9fafb; color: #4b5563; font-weight: 600; }}
  code {{ background: #f3f4f6; padding: 2px 6px; border-radius: 4px; font-family: ui-monospace, monospace; }}
</style>
</head>
<body>
<div class="container">
  <h1>视频归档整理报告 <span class="badge">{mode_badge}</span></h1>
  
  <div class="meta-grid">
    <div><b>生成时间：</b>{now_str}</div>
    <div><b>扫描耗时：</b>{report.scan_time_seconds:.2f} 秒</div>
    <div><b>源暂存路径：</b><code>{report.source_dir}</code></div>
    <div><b>目标归档路径：</b><code>{report.target_dir}</code></div>
    <div><b>自动清理空目录：</b>{"启用" if report.clean_empty_dirs else "未启用"}</div>
    {exc_html}
  </div>

  <div class="stats-grid">
    <div class="card blue"><div>源端番号</div><div class="card-num">{report.total_source_codes}</div></div>
    <div class="card green"><div>{"计划移动" if report.is_dry_run else "成功移动"}</div><div class="card-num">{len(moved_items)}</div></div>
    <div class="card red"><div>重复跳过</div><div class="card-num">{len(dup_items)}</div></div>
    <div class="card yellow"><div>未建档跳过</div><div class="card-num">{len(no_actor_items)}</div></div>
  </div>

  <h2>🟢 {"计划移动" if report.is_dry_run else "成功移动"}列表 ({len(moved_items)})</h2>
  <table>
    <thead><tr><th>源演员</th><th>番号目录</th><th>目标分类</th><th>目标演员</th><th>匹配模式</th><th>目标路径</th></tr></thead>
    <tbody>{render_rows(moved_items, is_moved=True)}</tbody>
  </table>

  <h2>🔴 重复番号跳过列表 ({len(dup_items)})</h2>
  <table>
    <thead><tr><th>源演员</th><th>番号目录</th><th>目标分类</th><th>目标演员</th><th>跳过原因</th></tr></thead>
    <tbody>
"""
        if dup_items:
            for it in dup_items:
                cat = it.target_category or "-"
                act = it.target_actor or "-"
                html += f"<tr><td><b>{it.source_actor}</b></td><td><code>{it.source_code}</code></td><td>{cat}</td><td>{act}</td><td style='color:#ef4444;'>{it.reason}</td></tr>"
        else:
            html += "<tr><td colspan='5' style='text-align:center; color:#6b7280;'>未发现重复番号</td></tr>"

        html += f"""
    </tbody>
  </table>

  <h2>🟡 目标未建档演员跳过列表 ({len(no_actor_items)})</h2>
  <table>
    <thead><tr><th>源演员目录名</th><th>涉及番号</th><th>建议处理方案</th></tr></thead>
    <tbody>
"""
        if no_actor_items:
            for it in no_actor_items:
                html += f"<tr><td><b>{it.source_actor}</b></td><td><code>{it.source_code}</code></td><td style='color:#f59e0b;'>请在 <code>{report.target_dir}\\&lt;分类&gt;</code> 下新建该演员文件夹后重新扫描</td></tr>"
        else:
            html += "<tr><td colspan='3' style='text-align:center; color:#6b7280;'>所有源演员均已建档</td></tr>"

        html += """
    </tbody>
  </table>
"""
        if error_items:
            html += f"""
  <h2>⚠️ 异常错误列表 ({len(error_items)})</h2>
  <table>
    <thead><tr><th>源演员</th><th>番号</th><th>错误信息</th></tr></thead>
    <tbody>
"""
            for it in error_items:
                html += f"<tr><td><b>{it.source_actor}</b></td><td><code>{it.source_code}</code></td><td style='color:#ef4444;'>{it.reason}</td></tr>"
            html += """
    </tbody>
  </table>
"""
        html += """
</div>
</body>
</html>
"""
        return html

    @classmethod
    def save_reports(cls, report: ProcessReport, output_dir: str | Path | None = None) -> tuple[Path, Path]:
        out_dir = Path(output_dir) if output_dir else Path.cwd() / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)

        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        md_file = out_dir / f"archive_report_{stamp}.md"
        html_file = out_dir / f"archive_report_{stamp}.html"

        md_file.write_text(cls.generate_markdown(report), encoding="utf-8")
        html_file.write_text(cls.generate_html(report), encoding="utf-8")

        return md_file, html_file
