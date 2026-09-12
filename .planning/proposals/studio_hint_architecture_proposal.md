# RFC: 非侵入式厂牌线索（Studio Hint）提取与按需拼装架构设计

- **状态**：提案草稿 (Draft / Proposal)
- **创建时间**：2026-09-08
- **目标**：在完全避免上游（Upstream）合并冲突的前提下，提供全局统一的厂牌线索识别能力，供 JavStash、FC2、分类路由等模块按需使用。

---

## 1. 背景与动机 (Motivation)

### 1.1 核心痛点
1. **无码日期番号天然重叠**：
   - 日本主要无码片商均使用“6位日期+编号”格式，例如：
     - 一本道 (1Pondo)：`011123_001`（标准为下划线）
     - 加勒比 (Caribbeancom)：`011123-001`（标准为连字符）
     - 天然むすめ (10musume)：`011123_01`（标准为2位尾号）
     - パコパコママ (pacopacomama)：`011123_001`
   - 当用户文件名分隔符不规范（例如全存成了下划线或连字符），或者在聚合数据库（如 JavStash / Stash-box）中搜索时，如果仅按纯数字检索，极其容易匹配到错误厂牌的影片。
2. **聚合数据库的厂牌规范后缀**：
   - JavStash 要求或推荐带有厂牌后缀（如 `011123_001-1pon`、`011123-001-carib`），但其他传统搜刮器（JavBus, JavDB, 官网）如果接收到带后缀的番号则会直接 404。
3. **路径中蕴含丰富厂牌线索**：
   - 用户的存储目录通常包含片商信息（如 `.../一本道/011123_001.mp4` 或 `.../Caribbean/011123-001.mp4`），或者文件名含有 `1pon`、`carib`、`fc2`。

---

## 2. 上游（Upstream）兼容性与冲突风险评估

| 方案 | 修改范围 | 优点 | 与上游冲突风险 |
| :--- | :--- | :--- | :--- |
| **方案 A：侵入式全局修改**<br>(改 `FileInfo` / `get_file_info_v2`) | `mdcx/models/model_types.py`<br>`mdcx/core/file.py`<br>`mdcx/core/file_crawler.py` | 全局第一步就有 `studio_hint` 属性 | **极高**<br>• `get_file_info_v2` 是上游变更最频繁的代码核心，几乎每次 upstream merge 都会产生冲突；<br>• Python dataclass 字段继承容易产生初始化参数错位。 |
| **方案 B：爬虫内部零散解析**<br>(当前已上线的临时方案) | 仅在 `mdcx/crawlers/javstash.py` 内部 | 改动最小，当前已完全解决一本道/加勒比混淆 | **极低**<br>但其他爬虫（如 FC2、路由分类器）无法复用逻辑，未来可能重复编写路径检查。 |
| **方案 C：非侵入式独立工具模块**<br>(🌟 **本提案推荐方案**) | **新建** `mdcx/utils/studio_hints.py`<br>爬虫按需导入 | • **零上游冲突**（新文件在 Git 合并时永远不会冲突）；<br>• 核心模型不变，完全复用已有的 `file_path`；<br>• 全局统一维护厂牌字典，所有爬虫均可按需调用。 | **极低 (近乎为零)** |

---

## 3. 架构设计：非侵入式独立工具模块 (`studio_hints.py`)

### 3.1 核心数据结构与枚举
```python
from enum import Enum
from pathlib import Path
import re

class StudioHint(str, Enum):
    UNKNOWN = ""
    PONDO = "1pondo"              # 一本道
    CARIBBEAN = "caribbeancom"    # 加勒比
    TENMUSUME = "10musume"        # 天然むすめ
    PACOPACO = "pacopacomama"    # パコパコママ
    FC2 = "fc2"                  # FC2 / FC2-PPV
    HEYZO = "heyzo"              # HEYZO
    TOKYO_HOT = "tokyo-hot"      # 东京热
```

### 3.2 厂牌关键词与特征字典
```python
STUDIO_KEYWORDS: dict[StudioHint, list[str]] = {
    StudioHint.PONDO: ["1pon", "1pondo", "一本道"],
    StudioHint.CARIBBEAN: ["carib", "caribbean", "caribbeancom", "加勒比", "cappv"],
    StudioHint.TENMUSUME: ["10mu", "10musume", "天然むすめ", "天然素人"],
    StudioHint.PACOPACO: ["paco", "pacopacomama", "パコパコママ"],
    StudioHint.FC2: ["fc2", "fc2ppv", "fc2-ppv", "fc2_ppv"],
    StudioHint.HEYZO: ["heyzo"],
    StudioHint.TOKYO_HOT: ["tokyo-hot", "tokyohot", "东京热", "東京熱"],
}
```

### 3.3 启发式推导优先级引擎
推导函数 `detect_studio_hint(number: str, file_path: Path | str | None = None) -> StudioHint` 遵循以下优先级：

1. **强特征：番号前缀或固定格式（权重最高）**：
   - 番号以 `FC2` 开头（如 `FC2-PPV-123456`）$\rightarrow$ 直接判定为 `StudioHint.FC2`；
   - 番号以 `HEYZO` 开头 $\rightarrow$ `StudioHint.HEYZO`；
   - 番号以 `CAPPV` 开头 $\rightarrow$ `StudioHint.CARIBBEAN`；
   - 6位日期+2位尾号（`\d{6}_\d{2}`）$\rightarrow$ 极高概率为 `StudioHint.TENMUSUME`。
2. **强特征：文件全路径中的明确片商目录/关键词**：
   - 提取上下文文本：`f"{Path(file_path).stem} {Path(file_path).parent.name} {Path(file_path).parent.parent.name}"`；
   - 使用独立词边界或关键词匹配字典，匹配到即返回对应厂牌。
3. **次特征：日期番号的分隔符语义**：
   - `\d{6}_\d{3}`（下划线）：判定为一本道系（`StudioHint.PONDO`，或在有 paco 提示时为 `PACOPACO`）；
   - `\d{6}-\d{3}`（连字符）：判定为加勒比系（`StudioHint.CARIBBEAN`）。
4. **无特征**：
   - 返回 `StudioHint.UNKNOWN`。

---

## 4. 各模块消费与装配方式

### 4.1 JavStash 爬虫 (`mdcx/crawlers/javstash.py`)
JavStash 仅需调用该工具函数，不再自行维护字符串解析逻辑：
```python
from ..utils.studio_hints import StudioHint, detect_studio_hint

hint = detect_studio_hint(ctx.input.number, ctx.input.file_path)

if hint == StudioHint.PONDO:
    candidates.append(f"{core_number}-1pon")
elif hint == StudioHint.CARIBBEAN:
    candidates.append(f"{core_number}-carib")
elif hint == StudioHint.TENMUSUME:
    candidates.append(f"{core_number}-10mu")
elif hint == StudioHint.PACOPACO:
    candidates.append(f"{core_number}-paco")
```

### 4.2 路由分类与优先级调度 (`classify_scrape_task`)
在 `file_crawler.py` 或调度器中：
```python
hint = detect_studio_hint(task_input.number, task_input.file_path)
if hint == StudioHint.FC2:
    # 优先将 FC2 / FC2PPVDB / JavDB 提到最高优先级
    ...
```

---

## 5. 后续实施路径 (When Ready to Implement)

如果后续决定正式实现，仅需执行以下 3 个极简步骤：

1. **新建文件**：`mdcx/utils/studio_hints.py`，编写纯函数实现与正则匹配；
2. **单测覆盖**：在 `tests/test_studio_hints.py` 中编写 20+ 个不同路径格式的覆盖用例；
3. **对接调用**：将 `mdcx/crawlers/javstash.py` 内部私有的 `generate_javstash_candidates` 对接该函数。

**结论**：该方案能以 **零上游代码污染、零合并冲突风险** 的优雅架构，完美实现全局厂牌线索的识别与多场景复用。
