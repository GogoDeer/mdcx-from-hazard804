# Session Context Handoff — MDCx 开发与排查上下文

> **更新时间**: 2026-09-12 17:10  
> **分支状态**:
> - `mdcx-diy`: `dev-diy` 分支（最新 commit: `c3ae113e`）
> - **安全备份**: `backup-dev-diy-20260912-pre-squash`（锁定在压缩前 `7fbd929e` 状态）
> - **基准上游**: `cdlongbow/main`（最新 commit: `5cb459b4`）
> - **部署产物**: `D:\App\SeTools\MDC\MDCx-diy\MDCx.exe`

---

## 1. 本次会话完成的重要事项与决策背景

### 1.1 Git 默认 Rebase 策略落地
- 按照用户要求，执行了本地 Git 配置：
  - `git config --local pull.rebase true`
  - `git config --local rebase.autoStash true`
- 后续在 `dev-diy` 分支下拉取上游变更时，将自动使用 rebase 模式线性重放，避免产生无意义的交叉 Merge 节点。

### 1.2 历史提交模块化压缩 (Squash) 与基于上游 main 的线性 Rebase
- **背景**: 之前 `dev-diy` 分支累积了 35 个细碎提交，且包含 `8b5ee5a0` 历史 Merge 节点，结构杂乱。
- **实施过程**:
  1. 创建了全量安全备份分支 `backup-dev-diy-20260912-pre-squash`（随时可一键切回回退）；
  2. 提取并吸收了 `cdlongbow/main` 的最新 7 个提交（#93 路径超长保护、#94 ThePornDB/单文件刮削修复等）；
  3. 将本地原本的 35 个细碎修改与 Merge 节点，严格按业务语义压缩为 **5 个高质量线性 Commit**：
     - `b6d095f8` `feat(crawler): add StashDB / JavStash GraphQL scraper and pHash perceptual hash recognition`
     - `ef8fd662` `feat(crawler): add JavHub and JapanHDV crawlers, official uncensored scraping, and language source firewall`
     - `c8cb1d7e` `fix(core): add brand-first number extraction, Emby actor alignment, and stream download deadlock prevention`
     - `4d1b942c` `feat(ui): add NFO provenance tracking and one-click movie restore with AI diagnostics`
     - `c3ae113e` `docs(planning): record session changelog tracking and architecture specifications`
  4. 解决冲突：在 `mdcx/crawlers/theporndb.py` 中将上游的标题打分/日期桶阈值兜底逻辑与本地的语种防火墙逻辑无缝融合；在 `mdcx/core/scraper.py` 中完整继承上游的单文件刮削重置保护逻辑。

### 1.3 核心新功能回顾：UI 右键菜单“还原影片并复制日志给 AI”
- **单选精细化上下文限制**: 仅当树列表中选中**单部影片**时，右键菜单才展示【还原影片并复制日志 (R)】；点击空白处、根节点或多选影片时自动隐藏/禁用。
- **安全还原机制 (`mdcx/core/restore.py`)**: 恢复原视频、原路移回伴随文件（字幕、种子）、清理刮削垃圾（NFO/图片/extra/actors）、注销 `Flags.success_list` 与 `userdata/success.txt`。
- **AI 诊断报告**: 包含配置文件路径、全量日志路径、站点交互日志，一键复制到剪贴板并备份至 `Log/ai_reports/`。

---

## 2. 自动化验证与质量检查

1. **代码规范与格式**:
   - `uv run ruff check`：全部通过，0 errors。
   - `uv run ruff format --check`：397 个文件全量通过（100% 格式对齐）。
2. **UI 结构一致性**:
   - `uv run pytest tests/test_ui_structure.py`：6/6 全部通过。
3. **全量测试套件**:
   - `uv run pytest`：**1847 passed, 8 skipped, 0 failed**（100% 通过）。

---

## 3. 分支状态与后续协作说明

- **本地当前分支**: `dev-diy`，已硬重置为最新线性提交 `c3ae113e`。
- **远程分支状态**: 因本地历史已经过 Squash 和 Rebase，若需要推送到用户的个人 GitHub 远程分支 `origin/dev-diy`，需使用：
  ```bash
  git push --force-with-lease origin dev-diy
  ```
- **安全回滚方式**: 若任何时候需要恢复到压缩前的状态，只需执行：
  ```bash
  git reset --hard backup-dev-diy-20260912-pre-squash
  ```
