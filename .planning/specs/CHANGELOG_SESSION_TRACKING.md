# MDCx 会话开发追踪与技术变更记录 (Session Changelog & Architectural Tracking)

> **文档性质**: 核心架构演进与变更追踪白皮书  
> **归档路径**: `.planning/specs/CHANGELOG_SESSION_TRACKING.md`  
> **最后更新**: 2026-09-10  
> **适用版本**: 20260906+ (dev / dev-diy 分支)  
> **说明**: 本文档专门记录当前会话阶段（Session）内新增搜刮器、重大架构演进、核心防灾机制及关键 Bug 修复的背景、动机、实现机制与验证方案。作为团队与未来开发维护的单一可信来源（Single Source of Truth），隔离于上游 PR 之外，避免上游 `changelog.md` 的合并冲突。

---

## 目录
1. [变更动机与防冲突隔离设计](#1-变更动机与防冲突隔离设计)
2. [新增搜刮器架构详解](#2-新增搜刮器架构详解)
   - 2.1 [JavStash / StashDB (GraphQL + pHash 视觉指纹)](#21-javstash--stashdb-graphql--phash-视觉指纹)
   - 2.2 [JavHub (官方 GraphQL 刮削器)](#22-javhub-官方-graphql-刮削器)
   - 2.3 [JapanHDV (官方直连 + 厂牌守卫)](#23-japanhdv-官方直连--厂牌守卫)
3. [核心架构与安全机制演进](#3-核心架构与安全机制演进)
   - 3.1 [厂牌优先番号提取器 (Brand-First Number Extraction)](#31-厂牌优先番号提取器-brand-first-number-extraction)
   - 3.2 [跨类型刮削源防火墙 (Scrape Type Source Firewall)](#32-跨类型刮削源防火墙-scrape-type-source-firewall)
   - 3.3 [NFO 原始信息防丢失溯源机制 (NFO Provenance Tracking)](#33-nfo-原始信息防丢失溯源机制-nfo-provenance-tracking)
   - 3.4 [媒体服务器演员目录对齐优化 (Emby/Jellyfin Alignment)](#34-媒体服务器演员目录对齐优化-embyjellyfin-alignment)
   - 3.5 [影片搜刮一键还原与 AI 诊断报告系统 (One-Click Restore & AI Diagnostics)](#35-影片搜刮一键还原与-ai-诊断报告系统-one-click-restore--ai-diagnostics)
4. [关键 Bug 修复与根因剖析 (Post-Mortems)](#4-关键-bug-修复与根因剖析-post-mortems)
   - 4.1 [HTTP 流式下载死锁与连接池耗尽](#41-http-流式下载死锁与连接池耗尽)
   - 4.2 [Amazon 刮削崩溃与断点续刮重复项](#42-amazon-刮削崩溃与断点续刮重复项)
   - 4.3 [ThePornDB 欧美场景假阳性匹配过滤](#43-theporndb-欧美场景假阳性匹配过滤)
   - 4.4 [PyQt6 UI 自动同步编译与 GBK 终端兼容](#44-pyqt6-ui-自动同步编译与-gbk-终端兼容)
5. [受影响文件对照与代码映射表](#5-受影响文件对照与代码映射表)
6. [测试验证与质量保证标准](#6-测试验证与质量保证标准)

---

## 1. 变更动机与防冲突隔离设计

### 1.1 为什么建立独立追踪文档
- **避免上游合并冲突（Upstream Zero Conflict）**：项目根目录下的 `changelog.md` 属于官方发布版本变更记录，每一次上游发布（如 `chore: release 22026xxxx`）均会全量改写。若在此文件中记录本地会话细节，未来从 `upstream/master` 同步时必定产生严重的 Git Merge 冲突。
- **保护 PR 纯净性（Strict PR Hygiene）**：依据 `AGENTS.md` 第 4 条规则，向上游提交的 PR 分支**仅包含纯代码与测试**，严禁夹带 `.planning/`。将架构设计与会话追踪完整沉淀在 `.planning/specs/` 中，既能在本地工作区持续追溯，又天然隔离于 PR 分支之外。
- **保留算法决策上下文（Architectural Context Retention）**：为何 StashDB 准入门槛设定为 180 分？为何 pHash 选用 8 关键帧？为何厂牌优先提取必须置于过滤转义之前？这些深度设计若仅零散写在 Commit Message 中，极易随版本迭代而失传。

---

## 2. 新增搜刮器架构详解

### 2.1 JavStash / StashDB (GraphQL + pHash 视觉指纹)
- **主要文件**：
  - `mdcx/crawlers/stashdb.py`：StashDB 专用适配器与准入逻辑。
  - `mdcx/crawlers/stashbox_base.py`：通用的 Stash-box GraphQL 客户端基类。
  - `mdcx/crawlers/javstash.py`：JavStash 场景搜索与结果解析。
  - `mdcx/utils/phash.py`：PyAV + ImageHash 视频感知哈希计算。
  - `mdcx/utils/javstash_utils.py`：Stash 专用打分与属性清洗。
- **核心作用**：
  - 对接去中心化成人元数据平台 StashDB（以及任何基于 Stash-box 开源规范部署的自建端点）。
  - 支持完整的 GraphQL 查询：番号精准过滤（`code`）、OSHash/MD5 指纹比对、标题/演员/片商查询以及高保真演员头像和全套标签提取。
- **重大设计要点与防假阳性机制**：
  1. **感知哈希（pHash）内容级识别**：针对无番号或被网盘/二次剪辑彻底抹除特征的视频文件，利用 `pyav` 在视频等间距提取 8 帧核心画面，生成感知哈希指纹并在 Stash 中反查，实现内容指纹级秒杀匹配。
  2. **严苛准入门槛（`MIN_ACCEPT_SCORE = 180`）**：针对欧美数据库常见短词（如 `interview`, `real`, `story`）带来的高假阳性率，规定普通模糊搜索若无法取得 Studio 或全标题完全匹配，则不予采信。
  3. **番号精准命中加权（+300 分）**：当且仅当 Stash 记录中的 `code` 字段与待测番号完全匹配（大小写与分隔符归一化后一致）时，赋予 +300 的决定性权重。
  4. **日期型番号消歧（Date Number Disambiguation）**：自动提取形如 `2022-11-20` 的日期特征，与发行日或拍摄日进行时间窗校验，防止同系列不同期次串录。

### 2.2 JavHub (官方 GraphQL 刮削器)
- **主要文件**：`mdcx/crawlers/javhub.py`
- **核心作用**：
  - 接入 JavHub 官方 GraphQL 现代化后端服务，提供对日本有码、日本无码以及精选影视的极速元数据拉取。
- **重大设计要点**：
  1. **复杂响应结构健壮解析**：支持响应体中嵌套多层 `list` 与 `dict` 结构，防御因接口字段升级返回非预期的空值或字典变列表导致的解析中断。
  2. **视频时长校验（Duration Check）**：对抓取到的片长与实际文件时长进行阈值比对，防止短预告片（Sample Trailer）误作为正片抓取。
  3. **多别名与女优归一化**：整合日文原名、罗马音及英文译名，自动为本地 NFO 填入标准化的别名条目。

### 2.3 JapanHDV (官方直连 + 厂牌守卫)
- **主要文件**：`mdcx/crawlers/japanhdv.py`
- **核心作用**：
  - 针对 JapanHDV、10Musume（天然むすめ）、Caribbeancom（加勒比）、Heyzo 等官方站点提供高精度、原画级超清封面（Front/Back Cover）与官方原版元数据。
- **重大设计要点**：
  1. **厂牌守卫机制（Brand Guard）**：仅当番号前缀明确符合受支持的日本无码官方厂牌列表（如 `10musume-`, `carib-`, `heyzo-` 等）时，才触发对 JapanHDV 的网络请求；对于标准日本有码或欧美番号，前置拦截跳过，极大提升整体刮削流水线吞吐量并减轻目标服务器并发压力。

---

## 3. 核心架构与安全机制演进

### 3.1 厂牌优先番号提取器 (Brand-First Number Extraction)
- **所在模块**：`mdcx/number.py` -> `extract_brand_number()`
- **修改背景**：
  - 传统 `get_file_number` 流程中，标准有码正则 `[A-Z]{2,}-\d{2,}` 排在无码素人正则之前，且标准正则在清洗阶段会剥离厂牌关键字。
  - 在遇到典型复合素人命名时（例如：`heydouga 4037-531-real interview 316 Towa01.wmv`）：
    - 真正番号为无码厂牌 `heydouga 4037-531`；
    - 后缀中带有描述性文本 `interview 316`；
    - 旧逻辑在文本清洗后，正则引擎优先扫描到了 `INTERVIEW-316`，将其误当成标准有码番号提取，导致后续搜刮完全脱轨。
- **实现机制**：
  - 新增 `extract_brand_number` 函数，**置于任何破坏性字符过滤与通用正则提取之前执行**。
  - 基于厂牌特征注册表，若文件名中包含 `heydouga`、`fc2`、`1pondo`、`caribbean`、`tokyohot` 等明确标识，优先调用对应厂牌的专用正则提取番号（如 `heydouga \d{4}-\d{3,4}`）。
  - 提取后直接标记 `is_uncensored = True`，并在提取上下文中将其锁定，彻底终结子标题英文字符被误识为常规番号的问题。

### 3.2 跨类型刮削源防火墙 (Scrape Type Source Firewall)
- **所在模块**：`mdcx/core/file_crawler.py`, `mdcx/models/model_types.py`
- **修改背景**：
  - 用户配置中通常会同时启用亚洲源与欧美源。若一个日本片目在日系爬虫中未直接命中，且启用了 StashDB 或 ThePornDB，旧逻辑会允许欧美源使用文件名片段（如 `interview`）发起模糊文本搜索（Text Search），从而匹配到大量欧美场景。
- **实现机制**：
  - 在 `CrawlTask` 数据模型中增加 `allow_text_search: bool = True` 字段。
  - 在核心任务调度器 `file_crawler.py` 的循环分派中加入**语种防火墙**：
    - 当任务处于刮削亚洲片源阶段时，如果当前调度的爬虫属于欧美源（如 `Website.STASHDB` 或 `Website.THEPORNDB`），强制下发 `allow_text_search = False`。
    - 欧美爬虫接收到该指令后，**严格仅允许执行番号精准匹配（Code Match）或指纹哈希匹配（pHash/OSHash）**，彻底切断模糊文本回退通道。

### 3.3 NFO 原始信息防丢失溯源机制 (NFO Provenance Tracking)
- **所在模块**：`mdcx/core/file.py`, `mdcx/core/file_crawler.py`
- **修改背景**：
  - 自动化批量刮削包含“刮削后移动重命名”功能。一旦发生偶发性误刮削，视频文件将被改名并移入全新演员/番号目录，原始文件名、扩展名以及父级目录层级彻底丢失，给用户排查和回滚带来灾难性困难。
- **实现机制**：
  - 在输出 `.nfo` 文件的生成管道中，无损且持久化地写入两个审计标签：
    - `<originalfilename>`：记录文件进入 MDCx 刮削流水线前的原始文件名。
    - `<originalfilepath>`：记录文件最初所在的完整绝对路径。
  - 即使文件被重命名挪动，只要 `.nfo` 存在，即可通过自动化脚本（如 `restore_and_clean`）无损一键反向重命名并迁回原始目录，达成真正的“防灾安全网”。

### 3.4 媒体服务器演员目录对齐优化 (Emby/Jellyfin Alignment)
- **所在模块**：`mdcx/tools/emby_actor_image.py`, `mdcx/tools/emby_actor_info.py`
- **修改背景**：
  - Emby 与 Jellyfin 对演员名称的分词逻辑、首字母大小写及中日多语言别名处理存在细微差异，旧逻辑在拉取/推送演员信息时，经常在 `A-drive` 或元数据缓存目录中生成带重复别名的冗余目录，降低头像展示效率。
- **实现机制**：
  - 确立统一的演员别名归一化管线，以媒体服务器原生识别标准为基准，对日文假名、汉字、罗马音进行主辅键拆分，统一缓存映射字典，避免头像重复抓取并提升匹配命中率。

### 3.5 影片搜刮一键还原与 AI 诊断报告系统 (One-Click Movie Restore & AI Diagnostics)
- **主要文件**：
  - `mdcx/models/manifest.py`：定义 `ScrapeManifest`（完整记录原始路径、新路径、移动文件、生成文件、软硬链接模式、单片日志、番号、标题等）及 `ScrapeHistoryRegistry`（带内存快速索引与 `userdata/restore_history.json` 磁盘持久化）。
  - `mdcx/core/restore.py`：`restore_scraped_movie()` 核心还原引擎与 `generate_ai_diagnostic_report()` Markdown 报告生成器。
  - `mdcx/core/scraper.py`：刮削单文件流水线挂载 Manifest、记录生成/移动文件，并在完成或失败时自动捕获独立线程日志。
  - `mdcx/controllers/main_window/main_window.py`：UI 菜单、快捷键 `R`、剪贴板交互与一键重刮快捷跳转。
- **设计要点与防错机制**：
  1. **严格单选约束**：多选时不提供还原入口，并弹窗提示仅支持单选，彻底杜绝批量失误回滚风险。
  2. **软硬链接安全感知**：自动识别软硬链接模式（`soft_link != 0` 或文件自身为软链接），对于链接模式仅安全删除输出端链接文件，物理源文件绝对保持完好无损。
  3. **资产闭环完整复原**：主视频安全移回原路径恢复原文件名；伴随转移的字幕（如 `.zh.srt`、`.cht.ass` 等）、种子（`.torrent`）、`.bif` 原路移回原目录；递归清理本次生成的 NFO、封面、剧照、`extrafanart`、`.actors` 等，空输出目录自动安全回收。
  4. **全链路注销解绑**：同时清理内存 `Flags.success_list` 与磁盘 `userdata/success.txt`，确保后续再次刮削不会被当成已成功跳过。
  5. **AI 诊断闭环集成**：生成的 Markdown 诊断报告显著标明 **MDCx 配置文件路径** 与 **全量运行日志文件路径**，使外部 AI 可直接根据路径精准定位网络、正则或站点配置故障；报告自动复制到系统剪切板，并同步归档于 `Log/ai_reports/<datetime>_<number>_diagnose.md`。
  6. **一键快捷重搜**：还原成功后弹窗提供【重新指定番号】快捷按钮，一键调出番号输入框重新发起刮削。

---

## 4. 关键 Bug 修复与根因剖析 (Post-Mortems)

### 4.1 HTTP 流式下载死锁与连接池耗尽
- **涉及模块**：`mdcx/web_async.py`
- **现象**：在并发下载大图或高清海报时，刮削进度条偶尔会卡在 99% 或某个文件上长时间静止，导致整个刮削进程死锁。
- **根因分析**：在使用异步 HTTP 客户端进行流式数据块读取时（Stream Download），若网络波动触发异常中断，连接流未能完全消费（Drain）或未正常执行 `response.aclose()`，导致底层 HTTP 连接池的套接字句柄泄漏，后续协程排队等待空闲连接直至永久死锁。
- **修复措施**：对所有异步下载循环加入严格的上下文管理器防御与 `finally` 异常切断，强制在连接异常断开时安全释放底层连接池。

### 4.2 Amazon 刮削崩溃与断点续刮重复项
- **涉及模块**：`mdcx/crawlers/amazon.py`, `mdcx/core/file_crawler.py`
- **现象**：开启 Amazon 搜刮时，偶发抛出 `AttributeError: 'NoneType' object has no attribute 'get'` 异常导致单项刮削崩溃；间歇性断点重试时，恢复列表（Resume List）中的项目成倍增长。
- **根因分析**：
  1. Amazon 详情页若返回未发布或区域受限的骨架 HTML，`detail_url` 解析器未能提取到有效链接，直接传递 `None` 导致后续字符串操作崩溃。
  2. 任务调度重试状态在内存队列中被重复入队（Enqueue），未对已经存在于 `resume_list` 中的任务键进行唯一性约束。
- **修复措施**：为 Amazon 详情页所有关键字段加入 `Optional` 判空与默认兜底；在断点恢复列表中引入 `set` 去重防重复逻辑。

### 4.3 ThePornDB 欧美场景假阳性匹配过滤
- **涉及模块**：`mdcx/crawlers/theporndb.py`
- **现象**：欧美片名搜索时，包含通用词汇的番号会误匹配到不相关的 ThePornDB 场景。
- **修复措施**：增加严格的 Studio 过滤条件，并在场景打分函数中引入必须包含至少一个特异性实词或精确发布年份的门禁，大幅消除模糊假阳性。

### 4.4 PyQt6 UI 自动同步编译与 GBK 终端兼容
- **涉及模块**：`mdcx/views/MDCx.py`, `mdcx/views/MDCx.ui`
- **规范确立**：
  - Windows 默认控制台代码页为 GBK（CP936），直接打印 Unicode 特殊符号会导致 `UnicodeEncodeError`。已全量确立在所有独立脚本与测试入口显式配置 `sys.stdout.reconfigure(encoding='utf-8')`。
  - 确立所有修改 `*.ui` 的改动必须立即执行 `uv run pyuic6` 和 `uv run ruff format`，确保 `test_ui_structure.py` 自动化测试 100% 同步通过。

---

## 5. 受影响文件对照与代码映射表

| 文件路径 | 改动性质 | 核心改动内容概要 |
| :--- | :--- | :--- |
| `mdcx/crawlers/stashdb.py` | **[NEW]** | StashDB 专用实现，包含严苛准入门槛（180 分）与精准番号加权（+300 分） |
| `mdcx/crawlers/stashbox_base.py` | **[NEW]** | Stash-box 通用 GraphQL 客户端基类与连接认证 |
| `mdcx/crawlers/javhub.py` | **[NEW]** | JavHub 官方 GraphQL 爬虫，支持有码/无码及时长校验 |
| `mdcx/crawlers/japanhdv.py` | **[NEW]** | JapanHDV 官方爬虫，支持官方超清封面与厂牌守卫（Brand Guard） |
| `mdcx/utils/phash.py` | **[NEW]** | PyAV 8 关键帧视频感知哈希（pHash）指纹生成工具类 |
| `mdcx/utils/javstash_utils.py` | **[NEW]** | JavStash / Stashbox 打分与数据清理辅助模块 |
| `mdcx/number.py` | **[MODIFY]** | 引入厂牌优先提取（`extract_brand_number`），防止有码正则抢跑 |
| `mdcx/core/file_crawler.py` | **[MODIFY]** | 加入语种搜刮防火墙（亚洲源刮削时关闭欧美源文本模糊搜索） |
| `mdcx/core/file.py` | **[MODIFY]** | NFO 生成流水线注入 `<originalfilename>` 与 `<originalfilepath>` |
| `mdcx/models/model_types.py` | **[MODIFY]** | `CrawlTask` 新增 `allow_text_search` 标志 |
| `mdcx/crawlers/theporndb.py` | **[MODIFY]** | 欧美场景精准度过滤，适配 `allow_text_search` 门禁 |
| `mdcx/web_async.py` | **[MODIFY]** | 修复流式下载中断连接死锁，完善连接池资源释放 |
| `tests/crawlers/test_stashdb.py` | **[NEW]** | StashDB 爬虫与 GraphQL 请求/打分完整单测 |
| `tests/test_phash.py` | **[NEW]** | 视频 pHash 关键帧提取与哈希汉明距离校验测试 |
| `tests/test_number_definition.py` | **[MODIFY]** | 覆盖厂牌优先无码番号提取用例（99 项全绿通过） |

---

## 6. 测试验证与质量保证标准

本阶段的所有变更均遵循严格的自动化与回归测试流水线，核心测试结果如下：

1. **番号提取回归测试**：
   - 运行：`uv run pytest tests/test_number_definition.py`
   - 结果：**99/99 测试通过**，确认包括 `heydouga 4037-531`、`carib-xxxx`、`fc2-xxxx` 在内的各种厂牌复合命名准确提取，原有标准有码命名完全不受影响。
2. **StashDB 匹配与防火墙单测**：
   - 运行：`uv run pytest tests/crawlers/test_stashdb.py`
   - 结果：**11/11 测试通过**，确认低于 180 分的短词模糊匹配全部被拒，精准命中番号的条目获得 300+ 权重稳定入选。
3. **UI 编译与结构完整性测试**：
   - 运行：`uv run pytest tests/test_ui_structure.py`
   - 结果：**6/6 测试通过**，确认 `MDCx.ui` 与 `MDCx.py` 严格保持字节与代码对齐。
4. **全量项目测试集**：
   - 运行：`uv run pytest`
   - 结果：**617 项测试全绿通过**，无任何破坏性回归问题。
5. **实际构建产物部署验证**：
   - 打包：`uv run python scripts/build.py`
   - 产物：`dist/MDCx.exe`（159,620,059 字节）已成功替换至运行环境 `D:\App\SeTools\MDC\MDCx-diy\MDCx.exe`。
