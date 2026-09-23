# 用户指令记忆

只记长期有效的行为规范、构建发布、排错方法与环境约束；实现细节以代码、测试、文档为准。本文件不受 150 行限制（用户 2026-09-06 明示），但只记"以后每次都该怎么做"；遇可记内容主动写入，不等提醒。

## 协作与提交纪律

- 简体中文回复；面向小白按"现象和影响 → 原因 → 可执行步骤"；日期一律北京时间 (UTC+8) 并注明。
- 改动前说明内容与原因；**用户明确要求才提交/推送**；直接在当前分支操作。
- 检查链：改 .py 后 `uv run quick-check`；提交前 `uv run check --skip-hook-install`。**pre-push 自动分流**（与 CI 一致）：推送范围全为 `.md`/`.mdx`/`.monkeycode/`/`docs/`/`wiki/` 时只查空白，含代码才全量——docs 提交秒推勿等全量；新分支无基线保守全量。**hooksPath 是本地 git config，环境重置后静默失效**——`git config core.hooksPath` 为空则补 `git config core.hooksPath .githooks`，同时恢复 pre-push 与署名 hook）。全绿判定=退出码零 + 无 error 行（mypy 输出可能被 tail 截断；`ruff check` 过 ≠ format 过，改 .py 必须 `ruff format` 落地，`scripts/` 同在范围）。xlsx 出厂库校验按路径改动跳过。
- 禁 `git add -A` 裹残留（先 .gitignore 排除）；**commit message 不手写 Co-authored-by**（prepare-commit-msg hook 自动追加，手写重复）。
- **changelog discipline**：提交前更新 changelog 当前版本条目；版本号归属用户、不擅自开新段；写法=用户视角发布说明（留议题号/现象/结果，删排查叙事与哈希）。未发版条目被后续议题取代时合并重写成最终形态。版本同步 `scripts/bump.py --version <YYYYMMDD> --name <X.Y.Z>`（需管道喂确认 y；`--check` 验四处一致）；**"已发版"判据=数字 tag 已推送**（`git ls-remote --tags origin`）。
- 站点/爬虫/配置改动同步检查：UI 文案、README/docs、爬虫总数、`config/migrations.py` 旧值清洗（漏迁移→pydantic 校验失败→"保存不生效"）。**写死数字前 grep 代码核实**；高频漂移锚点：默认网站源顺序、代理域名列表、命名变量表、设置 Tab 名、字段优先级数、指纹池、默认窗口尺寸（`_adaptive_window_sizes` 原生/隐藏边框两档+矩阵逐档断言，改默认尺寸测试/文档三处同步）；爬虫数 README 四处+FEATURES 标题第五处。
- **Wiki 纪律**：`wiki/` 是 GitHub Wiki 内容源（14 页分站）；功能改动回填对应主题页+_Sidebar/Home；议题通用答案回填 FAQ；Wiki 仓库需用户先网页建首页才能克隆。
- 长任务标准做法：background_terminal + checkpoint 落盘断点续传（后台终端约 1 小时回收，wrapper 45-50 分钟自重启）+ 分批落盘 + 进度看落盘文件不看 stdout。
- 功能移除类需求先调研证据（活跃度/共享依赖/成本）再答；用户转述与代码矛盾时以代码为准。

## GitHub 议题处理

- 凭据：`TOKEN=$(printf "protocol=https\nhost=github.com\n\n" | git credential fill | sed -n 's/^password=//p')`（值禁回显/落盘；`gh api user` 403 正常；未认证直连 api 撞 IP 限流）。截图 `curl -sL` 下载后 Read，多图并行。gh 命令前先 export GH_TOKEN 同款取法。
- **回帖姿势**：JSON POST `-d @file` + `Content-Type: application/json`；多行中文 body 用 `python3 << 'PYEOF'` + `json.dump` 生成；POST 失败先 `json.tool` 校验；发送后验证 html_url。回帖礼貌先行；一段描述常夹多诉求，逐项回应。
- **采纳原则：以代码/文档证据+根因是否为真为准**，不信报告人语气/坚持次数；不合理时礼貌附代码依据，欢迎补充复现；我方既往回复可能措辞误导，引用前先审自己。**"真 bug"标准**：现有功能与自身设计/数据语义矛盾或渲染错误；与个人审美/习惯不符=个性需求。
- **对不尊重开发者的报告人（z291173301，#178 辱骂）：个性需求一律不采纳，回帖引导 fork；仅真 bug 动代码，不惯着**。**已发版的偏好类改动不回滚**（回滚=行为倒退+返工）；对其回帖简短坚定附依据，不做长篇驳斥/大规模盘点。诉求摇摆=返工源：动手前锁验收口径，同块代码改两次即停下对齐；施压型/纯验证型用实测脚本定量证伪后关单。
- 报告人多用 Windows 原生边框：界面几何类议题先确认是否默认隐藏边框；非默认配置的观感差异以隐藏边框实测仲裁，不为偏好改代码。
- 版本定性用状态区指纹（配置文件名+版本号）+日志/UI 特征串反推构建落点，不信自报版本；先判"待修复"还是"已修待发版"。**同报告人连续多议题先横向看历史再定夺**。
- 软件内说明文本句子=用户眼中的事实清单：覆盖面/例外写成显式注记，塞句尾等于没写。

## 排错与验证方法论

- **行为修复流程：先复现测试跑红→修→绿→反向验证**；结构约束用 AST 哨兵锁位置并反向喂失效代码。**测试必须喂生产形态数据**（生产构建函数取值/真实页面快照入 tests/fixtures，手写夹具漂移假红假绿）。pytest-asyncio strict：文件内全是 async 才用文件级 `pytestmark`，混合同步测试必须逐函数加标记（否则 PytestWarning 刷屏）。
- **"本地全绿≠CI"**三维度：输出截断 / Python 版本语义（3.13 模块级带值注解立即求值 vs 3.14 PEP 649 延迟，单例声明用无注解赋值）/ 平台差异。Windows 坑：`subprocess.run(text=True)` 显式 `encoding="utf-8", errors="replace"`（GBK 炸）；glob `[XX]` 是字符类+Windows 路径大小写不敏感（"已清理"断言用 list 过滤而非 glob）；**Qt 多主窗收尾段错误**——同进程构造 ≥2 个 MyMAinWindow（含 QSystemTrayIcon）收尾 SIGSEGV/退码1，rerun 不可消除（conftest 全绿 `os._exit(0)` 兜底），管道里 `$?` 被 tail 吃，退出码判定必先 `>file; echo $?`；CI 红绿二分用诊断 PR 探针，每档至少采样 2 次再定性（幸存者偏差教训）。同类 flake 教训：Windows `heightForWidth` 读 QLabel 文档缓存 setText 后滞后返回旧高度——布局高度断言与生产计算必须同源公式（fontMetrics.boundingRect）。
- **「未命中/空结果」是业务常态，不得与被标记的同"通道故障"混计**（404 不记错误率，真实限流信号只有 403/429/连接异常）；模型哨兵默认值（"0000-00-00"）truthy 会被放行，下发前按格式白名单归一化（宽度解析支持 `- / .`、紧凑 YYYYMMDD）；集合合并 bug 第一嫌疑=有无 dedupe；日志/汇总字段带决策上下文（host/失败分类）。
- 报错先验证真失败还是通知误伤；触发链每一环落实（"可达"≠"正常路径会走到"）；泄漏/累积类先写最小复现脚本量化。**subagent 与外部 AI 结论不可直接采信**：要求"已排除假设清单+理由"，每条独立复现后采纳。**数据治理前必须全量抽查实证**，不纯代码推断。
- 持久化快照三必备：原子写（tmp+`os.replace`）/按快照比对才清 dirty/退出路径强制落盘；写后无回验是"日志说成功但文件不存在"第一嫌疑；传全局列表一律 `list(...)` 快照。开关组合不生效先画清每个开关的写入端/读取端。WinError 123 先实测真实失败串（常是云盘文件名长度超限）。
- 「关工具窗连带主进程退出」两条根因按触发分诊：①主窗藏托盘关最后可见窗=`quitOnLastWindowClosed`；②取数中关 `WA_DeleteOnClose` 对话框=线程未等齐 abort——closeEvent 必须 cancel/等齐全部线程，超时 `setParent(None)` 卸父子再放行。
- 测试耗时诊断 `--durations=15`→单测 profile→打桩计数；真凶=生产节流真实 sleep（autouse patch）与偷跑网络（conftest 断网桩）。大范围撤回 `git revert --no-commit <多提交>` 合并单撤销；哨兵被行为测试覆盖即删、同域测试并入主回归文件。TRAWL/分发包端到端对账启动假设；bun 按 cwd 装依赖；大 zip 远程验尸用 GET+Range 读中央目录；cmd bat chcp 65001 中文注释错位——rem 注释避特殊结构。

## 环境与并发约定

- **环境重置后才建环境**：`pip3 install --break-system-packages uv -i 清华镜像` → `uv python install 3.13`（`UV_PYTHON_INSTALL_MIRROR` ghproxy）→ `uv sync`（后台 20 分钟级）+ `export UV_DEFAULT_INDEX=清华镜像`。**持 UV_DEFAULT_INDEX 跑 `uv run` 会把 uv.lock 全部 index URL 重写为镜像域（禁入库），提交前 `git checkout -- uv.lock` 核对**。PyQt 测试装 ci.yaml apt 列表并 `QT_QPA_PLATFORM=offscreen`。
- background_terminal 是 sh(dash)：`[[ ]]` 会空转，POSIX 语法或 `bash -c`；后台终端内 `git credential fill` 拿不到凭据，token 在前台 bash 取。仓库根 `config.json` 是脏配置，验证配置/网络用临时配置指 `manager.path`；devbox 代理 127.0.0.1:7890 可能无进程，排查先临时关。
- 后台线程跑异步一律走全局 `AsyncBackgroundExecutor`（禁手动 new_event_loop/run_until_complete/run sync 在 QThread，AST 哨兵锁；curl_cffi 定时器注册死 loop → Windows "Python-CFFI error"）；后台协程 `utils/qt_thread.py::run_in_background`，结果经 Qt signal 回主线程，新增后跑 `scripts/check_thread_safety.py`；文件间 FIRST_COMPLETED 滑窗、文件内 gather。curl_cffi 流式关闭=`quit_now.set()`+`await aclose()`；close() 只是发起 abort，内部任务必须有人等；"Task was destroyed"先疑 cancel 无人消费；sync/async 成对入口成对审计（取消打断收尾租约泄漏三件套：shield 释放/finally 恒释/逐实例 suppress）。内网服务（Emby 等）走轻量 httpx 直连，不蹭爬虫指纹栈。LogBuffer 归因：写入按 `_ROOT` contextvar，`process_one_file` 入口 `new_root()` 断兄弟继承。
- `CancelledError` 在结果收集点与 Exception 同级软着陆（单项记 CANCELLED），整轮取消只由 cancel_event 负责。Emby/Jellyfin `UpdateItem` 对 Genres/Tags/ProviderIds 空引用坑——payload 三者恒非 null；日期归一化收口模型层单一出口。

## UI 开发与排错

- **改 UI 先改 `.ui`（唯一权威源）** → pyuic+`scripts/fix_qt_enums.py`+`ruff format` → `tests/test_ui_structure.py`（同步锁）；小文案可 .ui/.py 同步手改（避免整文件重生成噪音），禁止只改 .py。**PyQt 测试**：每个含 Qt 的文件顶部（PyQt6 import 前）自持 `QT_QPA_PLATFORM=offscreen`；fixture 构造后停 QTimer；qFatal 栈无 Python 行号查 QTimer 槽与 dummy 桩缺方法；conftest dummy 双陷阱（实例属性遮蔽/加方法必同步桩）。隔离配置 `monkeypatch.chdir(tmp_path)`。
- **绝对定位同步军规**（一族实证汇总）：①`setGeometry` 不触发子组件 resizeEvent（须 `resize()`）；QStackedWidget 只 resize 当前页，先 resize 全 pages 再算内部几何；②容器几何变化后 invalidate()+activate()；③平移一律「设计基准坐标+extra」双向幂等（正=extra 即缩回），增量平移漂移；④同步清单与设计器控件清单一一对账；⑤min 宽 `layout.minimumSize()`、高 `sizeHint()`，禁 childrenRect；⑥底部余量按页属性（浮框遮挡页 ≥72px）；⑦.ui 残留 maximumSize 静默夹断拉伸——删节点重编译；⑧改公式前 grep 变量名同步 tests/ 既有断言；⑨改默认窗口尺寸三处同步（_adaptive_window_sizes/docs/matrix 测试）。
- **重影/重叠先问渲染层还是定义层**：同 cell 定义层检测假绿，需 .ui 文本级哨兵；控件被盖住点不到=zorder，解析 XML 断 zorder 顺序；实机截图与 offscreen 矛盾以实机为准。填充类拉伸与锚定平移两种手段勿混；**改布局先锁整体设计语言**，布局类诉求先复述目标形态再动手，同区域改两次即停下对齐。
- QLabel `ScaledContents=True` 二次缩放陷阱：框比例动态变化时须 KeepAspectRatioByExpanding 预渲到精确框尺寸（改图框宽高比前先查渲染模式）。**Windows 原生边框首帧时序**：尺寸后 resizeEvent 驱动的同步首帧可能被吞——`_apply_adaptive_default_size` 尾部双拍（0ms+300ms）幂等勿回退；类似问题优先怀疑时序而非几何公式。「自愈型错位」同理。**reparent 进滚动容器**：控件与设计器清单一一对账，sync 幂等补漏禁 `if 已构建 return`；动态高度 QLabel 先 setText 再 heightForWidth。窗口状态汇聚点审计：grep `setState|activateWindow|showNormal|show|hide` 全库枚举加「可见且未最小化」守卫。

## 站点、打包与发布

- 当前注册爬虫 36。javdb 无码破解需 Cookie；**javdb 三源**：javdb（网页）/javdb_api（镜像站）/javdb_app（App API 最稳）；**thejavdb_api 与 javdb 无关**；App 签名见 docs/JAVDB_APP_SIGNATURE.md，env `MDCX_JAVDB_APP_SIG_*` 免改码覆盖，搜索 limit≤50、分页须 `movie_sort_by=release`；javdb 图源无水印 `tp.spfcas.com`（App 专用，在 `base/web.py`）。dev 走代理工具：`uv run python -m scripts.dev_proxy start|status|test <url>|stop`；超时≠站点死亡、连通验证必须 curl_cffi impersonate、批量探测校验 data.title 防假阳性。
- HTTP 错误串携带截断响应体（Emby 400 根因常在 body）；番号归一化前导数字双重语义（studio 名单数字保留 vs DMM `9` 前缀剥掉），改正则前 grep 全部分支防误伤。删站影响面=注册表+Website 枚举+默认 proxy 列表+migrations 清洗+UI，查证给方案不擅动。
- **打包**：只有字符串动态导入才需 hidden-import（哨兵 `test_build_hidden_imports` 锁）；**所有打包入口（ci 冒烟/release/build-windows/build-linux）改 fail-closed，缺 `build/sr_tools` 即硬失败——四条工作流必须先 `fetch_sr_tools --platform current`**（哨兵 test_sr_bundling 锁顺序）。**Release**：推纯数字 tag 触发 release.yml；产物名 `MDCx-<版本>-<平台>-<架构>-<完整sha>.<后缀>`；正文取 changelog 当前段；重发=删 release+`git tag -f` 指向新 HEAD+push tag。※已发过版本号可能被用户拍板「删版重发」承载后续修复（不新开版本段）。Actions：runner 标签会整体下线（macos-15-intel 接替 Intel）、setup-uv 无裸主版本浮动标签（须全版本号）。
- **ASIN/演员库治理方法论**（散点）：证据强度 tenhow cid 映射>条码>标题 NFKC>图像（仅兜底）；软校验按发现路径分流（条码=hard、库命中=免验、软匹配=三步链必验：cid 旁证→标题门+真合集词否决→图像兜底；演员名兜底是错挂重灾区）；批量导入走去重入口；合并判定禁用 or 链（短路吞带副作用侧）；数据治理前先 Counter 识别导入批次；openpyxl 删行=读出→去重→重写；DMM cid 前缀映射+数字双态（5 位 digital/3 位 mono 并存）；cid 正则 `^(\d*)([a-z]+)(\d+)([a-z]?)[a-z]?$`→`系列-{int:03d}`；出厂库更新须用户确认后执行。
