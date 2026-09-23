"""SQLite 刮削状态缓存层。

持久化每个源文件的刮削处理状态，实现断点续刮与失败跨会话重试。
这是轻量状态层：权威元数据仍是 NFO，权威演员库仍是 xlsx，本模块只记录
"谁刮过、结果如何"。数据库损坏或不可用时回退到内存模式，不影响主流程。
"""

import json
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from ..signals import signal

# 失败自动重试的最大次数（设计决策：默认 3 次，达到后不再自动重试，仅手动强制）
MAX_RETRY_COUNT = 3
_BATCH_COMMIT_SIZE = 32

# done记录的解析代版本：解析/数据修正逻辑有修复的发版时把此常量 +1，
# 旧版本写的 done 断点续刮自动放行重刮（修复随发版自动追平存量库，TODO #1-B）。
SCRAPE_SCHEMA_VERSION = 1

# 站点明确"查无此番号"的失败写 7 天负面缓存：期内跳过不重刮、不占自动重试
# 预算、不进恢复队列（TODO #1-A）。到期自动放行——站点可能后来才收录。
NOT_FOUND_TTL_SECONDS = 7 * 86400
FAILURE_REASON_NOT_FOUND = "not_found"

# 明确"查无"语义词表——只收判定确定性高的短语，宽泛词（如裸"不存在"）会误伤
# "文件不存在"这类真实故障，把它们关进 7 天不重试的黑盒。
_NOT_FOUND_HINTS = (
    "未匹配到番号",
    "未找到番号",
    "番号不存在",
    "查无此番号",
    "番号未收录",
    "未收录该番号",
    "此番号不存在",
    "404",
    "not found",
)


def classify_failure(error: str) -> str:
    """从失败文本判定失败类别。当前仅识别 not_found；其余返回 ""（普通失败）。"""
    if not error:
        return ""
    lowered = error.lower()
    for hint in _NOT_FOUND_HINTS:
        if hint in lowered:
            return FAILURE_REASON_NOT_FOUND
    return ""


@dataclass
class ScrapeState:
    """单文件的刮削状态记录。"""

    file_path: str  # 源文件绝对路径
    mtime: float  # 处理时的源文件 mtime
    status: str  # "done" / "failed"
    number: str = ""  # 刮到的番号（成功时）
    fail_count: int = 0  # 连续失败次数
    scraped_at: float = 0.0  # 最后处理时间戳
    error: str = ""  # 最后错误信息（失败时）
    origin_path: str = ""  # 失败前的源文件路径（失败文件被移入 failed_folder 时与 file_path 不同）
    failure_reason: str = ""  # 失败类别（""普通 / "not_found" 站点查无，走负面缓存）
    state_version: int = 0  # 记录写入时的解析代版本（SCRAPE_SCHEMA_VERSION）


class ScrapeStateCache:
    """基于 SQLite（标准库 sqlite3，WAL 模式）的刮削状态缓存访问层。"""

    def __init__(self, db_path: Path, log_fn=None):
        self._db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()  # 刮削为多协程并发写，SQLite 单写者需串行化
        self._pending_writes = 0
        self._log = log_fn or (lambda msg: signal.add_log(f" [刮削缓存] {msg}"))

    # ------------------------------------------------------------------
    # 连接生命周期
    # ------------------------------------------------------------------

    def open(self) -> bool:
        """打开数据库（WAL 模式 + 建表）。失败返回 False（回退内存模式）。"""
        if self._conn is not None:
            return True
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path), timeout=10.0)
            conn.row_factory = sqlite3.Row  # 按列名访问行
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scrape_state (
                    file_path  TEXT PRIMARY KEY,
                    mtime      REAL NOT NULL,
                    status     TEXT NOT NULL,
                    number     TEXT NOT NULL DEFAULT '',
                    fail_count INTEGER NOT NULL DEFAULT 0,
                    scraped_at REAL NOT NULL,
                    error      TEXT NOT NULL DEFAULT ''
                )
                """
            )
            # 迁移：旧表无 summary_json 列时补齐（存相似推荐所需的结果摘要）
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(scrape_state)").fetchall()}
            if "summary_json" not in columns:
                conn.execute("ALTER TABLE scrape_state ADD COLUMN summary_json TEXT NOT NULL DEFAULT ''")
            # 迁移：origin_path 存失败前的源文件路径（全库审查 B5）——
            # set_failed 的 key 是移入 failed_folder 后的路径，失败目录在扫描
            # 集合之外时 cleanup_missing 会误判"源文件已不存在"删光 failed 记录，
            # 跨会话恢复（list_pending）随之失效
            if "origin_path" not in columns:
                conn.execute("ALTER TABLE scrape_state ADD COLUMN origin_path TEXT NOT NULL DEFAULT ''")
            # 迁移：failure_reason 失败类别（负面缓存）与 state_version 解析代版本（TODO #1-A/B）
            if "failure_reason" not in columns:
                conn.execute("ALTER TABLE scrape_state ADD COLUMN failure_reason TEXT NOT NULL DEFAULT ''")
            if "state_version" not in columns:
                conn.execute("ALTER TABLE scrape_state ADD COLUMN state_version INTEGER NOT NULL DEFAULT 0")
            conn.commit()
            self._conn = conn
            self._pending_writes = 0
            return True
        except Exception as e:
            self._log(f"数据库打开失败，回退内存模式: {e}")
            if self._conn is not None:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
            return False

    def close(self) -> None:
        if self._conn is not None:
            try:
                self.flush()
                self._conn.close()
            except Exception as e:
                self._log(f"数据库关闭失败: {e}")
            self._conn = None
            self._pending_writes = 0

    def is_usable(self) -> bool:
        return self._conn is not None

    # ------------------------------------------------------------------
    # 状态读写
    # ------------------------------------------------------------------

    def _execute(self, sql: str, params: tuple = (), commit: bool = True) -> bool:
        """执行写 SQL，失败记日志返回 False（尽力而为，不中断主流程）。"""
        if self._conn is None:
            return False
        try:
            with self._lock:
                self._conn.execute(sql, params)
                self._pending_writes += 1
                if commit or self._pending_writes >= _BATCH_COMMIT_SIZE:
                    self._conn.commit()
                    self._pending_writes = 0
            return True
        except Exception as e:
            # commit 失败（如 database is locked 超时）时事务悬挂打开，后续
            # 写会追加进旧事务混入下次提交——rollback 回到干净边界并把计数
            # 归零，丢弃的只是本批未提交状态（与"失败返回 False"语义一致）
            try:
                with self._lock:
                    self._conn.rollback()
                    self._pending_writes = 0
            except Exception:
                pass
            self._log(f"数据库写入失败: {e}")
            return False

    def flush(self) -> bool:
        """提交刮削期间积累的状态写入。"""
        if self._conn is None:
            return False
        try:
            with self._lock:
                if self._pending_writes:
                    self._conn.commit()
                    self._pending_writes = 0
            return True
        except Exception as e:
            # 同 _execute：commit 失败 rollback 清边界，防悬挂事务混入后续提交
            try:
                with self._lock:
                    self._conn.rollback()
                    self._pending_writes = 0
            except Exception:
                pass
            self._log(f"数据库提交失败: {e}")
            return False

    def _fetch(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        if self._conn is None:
            return []
        try:
            with self._lock:
                rows = self._conn.execute(sql, params).fetchall()
            return rows
        except Exception as e:
            self._log(f"数据库查询失败: {e}")
            return []

    def get_state(self, file_path: Path) -> ScrapeState | None:
        rows = self._fetch(
            "SELECT file_path, mtime, status, number, fail_count, scraped_at, error, origin_path, "
            "failure_reason, state_version FROM scrape_state WHERE file_path = ?",
            (str(file_path),),
        )
        if not rows:
            return None
        row = rows[0]
        return ScrapeState(
            file_path=row["file_path"],
            mtime=row["mtime"],
            status=row["status"],
            number=row["number"],
            fail_count=row["fail_count"],
            scraped_at=row["scraped_at"],
            error=row["error"],
            origin_path=row["origin_path"],
            failure_reason=row["failure_reason"],
            state_version=row["state_version"],
        )

    def set_done(
        self,
        file_path: Path,
        mtime: float,
        number: str = "",
        summary: dict | None = None,
        commit: bool = True,
    ) -> None:
        import time

        summary_json = json.dumps(summary, ensure_ascii=False) if summary else ""
        self._execute(
            """
            INSERT INTO scrape_state (file_path, mtime, status, number, fail_count, scraped_at, error,
                                      summary_json, failure_reason, state_version)
            VALUES (?, ?, 'done', ?, 0, ?, '', ?, '', ?)
            ON CONFLICT(file_path) DO UPDATE SET
                mtime=excluded.mtime,
                status='done',
                number=excluded.number,
                fail_count=0,
                scraped_at=excluded.scraped_at,
                error='',
                summary_json=excluded.summary_json,
                failure_reason='',
                state_version=excluded.state_version
            """,
            (str(file_path), mtime, number, time.time(), summary_json, SCRAPE_SCHEMA_VERSION),
            commit=commit,
        )

    def set_failed(
        self,
        file_path: Path,
        mtime: float,
        error: str = "",
        commit: bool = True,
        origin_path: Path | None = None,
        failure_reason: str = "",
    ) -> None:
        """记录失败状态。

        origin_path：失败前的源文件路径。文件刮削失败被移入 failed_folder 后
        file_path 是移动后的路径——与扫描集合无交集，cleanup_missing 按
        origin 判存活才能保住 failed 记录（全库审查 B5）。
        """
        import time

        reason = failure_reason or classify_failure(error)
        self._execute(
            """
            INSERT INTO scrape_state (file_path, mtime, status, number, fail_count, scraped_at, error,
                                      origin_path, failure_reason)
            VALUES (?, ?, 'failed', '', 1, ?, ?, ?, ?)
            ON CONFLICT(file_path) DO UPDATE SET
                mtime=excluded.mtime,
                status='failed',
                fail_count=fail_count + 1,
                scraped_at=excluded.scraped_at,
                error=excluded.error,
                origin_path=excluded.origin_path,
                failure_reason=excluded.failure_reason
            """,
            (str(file_path), mtime, time.time(), error, str(origin_path) if origin_path else "", reason),
            commit=commit,
        )

    # ------------------------------------------------------------------
    # 判断逻辑
    # ------------------------------------------------------------------

    def should_skip(self, file_path: Path, mtime: float, force: bool = False) -> bool:
        """断点续刮判断：done 且 mtime 未变且未强制 → True（跳过）。

        - force=True：无条件不跳过（手动强制重新刮削）
        - 状态缺失 / failed / mtime 变化 → 不跳过
        """
        if force:
            return False
        import time

        state = self.get_state(file_path)
        if state is None:
            return False
        if state.status == "failed":
            if state.failure_reason == FAILURE_REASON_NOT_FOUND:
                # 负面缓存：TTL 内跳过；文件被改过（改名/修正番号笔误）立即放行；到期自动重刮
                if abs(state.mtime - mtime) >= 1e-6:
                    return False
                return (time.time() - state.scraped_at) < NOT_FOUND_TTL_SECONDS
            return False
        if state.status != "done":
            return False
        if state.state_version != SCRAPE_SCHEMA_VERSION:
            return False
        return abs(state.mtime - mtime) < 1e-6

    def should_retry(self, file_path: Path, max_retries: int = MAX_RETRY_COUNT) -> bool:
        """失败重试判断：fail_count < max_retries → True（重新入队）。

        仅对 failed 状态生效；done 或无记录返回 False。
        """
        state = self.get_state(file_path)
        if state is None or state.status != "failed":
            return False
        if state.failure_reason == FAILURE_REASON_NOT_FOUND:
            # 站点查无走 TTL 与手动重置通道，不占失败重试预算
            return False
        return state.fail_count < max_retries

    # ------------------------------------------------------------------
    # 队列恢复与清理
    # ------------------------------------------------------------------

    def list_pending(self, existing: set[Path], max_retries: int = MAX_RETRY_COUNT) -> list[Path]:
        """返回待处理文件列表（failed 且未超限）。

        existing：本次扫描到的源文件集合，仅返回其中仍存在的文件。
        """
        rows = self._fetch(
            "SELECT file_path, fail_count FROM scrape_state WHERE status = 'failed' AND failure_reason != 'not_found'",
        )
        pending = []
        for row in rows:
            p = Path(row["file_path"])
            if row["fail_count"] < max_retries and p in existing:
                pending.append(p)
        return pending

    def list_success_summaries(self) -> list[dict]:
        """返回全部成功刮削的结果摘要（供跨会话相似推荐等使用）。

        每条摘要包含 number/title/tags/series/studio/actors/release/runtime，
        以及相似推荐特征扩展字段 mosaic/publisher/directors/score。
        无 summary_json 的旧记录会被跳过。
        """
        rows = self._fetch(
            "SELECT summary_json FROM scrape_state WHERE status = 'done' AND summary_json != ''",
        )
        summaries = []
        for row in rows:
            try:
                data = json.loads(row["summary_json"])
            except (ValueError, TypeError):
                continue
            if isinstance(data, dict) and data:
                summaries.append(data)
        return summaries

    def cleanup_missing(self, existing: set[Path]) -> int:
        """清理源文件已不存在的过期记录，返回清理条数。

        failed 记录优先按 origin_path（失败前源路径）判存活——key 是移入
        failed_folder 后的路径，独立失败目录配置下与扫描集合无交集，
        按 key 判会把全部 failed 记录误删（跨会话恢复失效，全库审查 B5）。
        """
        rows = self._fetch("SELECT file_path, status, origin_path FROM scrape_state")
        existing_str = {str(p) for p in existing}
        removed = 0
        for row in rows:
            raw_path = row["file_path"]
            if row["status"] == "failed" and row["origin_path"]:
                # failed 记录：源路径（origin）或失败目录内路径（key）任一存活即保留
                if str(Path(raw_path)) in existing_str or row["origin_path"] in existing_str:
                    continue
            else:
                if str(Path(raw_path)) in existing_str:
                    continue
            # commit=False 批量积累，共享一个事务（原逐条独立事务，大库数千条产生数千次 commit）
            if self._execute("DELETE FROM scrape_state WHERE file_path = ?", (raw_path,), commit=False):
                removed += 1
        self.flush()
        return removed

    def clear(self) -> None:
        """清空全部状态（供手动重置用）。"""
        self._execute("DELETE FROM scrape_state")

    # ------------------------------------------------------------------
    # 缓存管理 UI 支撑
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """聚合统计：返回 done/failed/failed_exhausted/total 计数 + db 路径/大小。

        - failed_exhausted：fail_count >= MAX_RETRY_COUNT 的失败记录（已不会自动重试）。
        - db_size_kb：数据库文件大小（KB），不存在或不可读为 0。
        """
        result: dict = {
            "done": 0,
            "failed": 0,
            "failed_exhausted": 0,
            "not_found": 0,
            "total": 0,
            "db_path": str(self._db_path),
            "db_size_kb": 0,
        }
        rows = self._fetch("SELECT status, COUNT(*) AS cnt FROM scrape_state GROUP BY status")
        for row in rows:
            s, cnt = row["status"], row["cnt"]
            result["total"] += cnt
            if s == "done":
                result["done"] = cnt
            elif s == "failed":
                result["failed"] = cnt
        nf = self._fetch(
            "SELECT COUNT(*) AS cnt FROM scrape_state WHERE status='failed' AND failure_reason='not_found'",
        )
        if nf:
            result["not_found"] = nf[0]["cnt"]
        ex = self._fetch(
            "SELECT COUNT(*) AS cnt FROM scrape_state WHERE status='failed' AND fail_count >= ?",
            (MAX_RETRY_COUNT,),
        )
        if ex:
            result["failed_exhausted"] = ex[0]["cnt"]
        try:
            result["db_size_kb"] = round(self._db_path.stat().st_size / 1024, 1) if self._db_path.exists() else 0
        except Exception:
            pass
        return result

    def list_failed_detail(self, limit: int = 500) -> list[ScrapeState]:
        """返回失败记录详情（含 error/fail_count），按最后处理时间倒序，限 limit 条。"""
        rows = self._fetch(
            "SELECT file_path, mtime, status, number, fail_count, scraped_at, error, origin_path, "
            "failure_reason, state_version FROM scrape_state WHERE status='failed' "
            "ORDER BY scraped_at DESC LIMIT ?",
            (limit,),
        )
        return [
            ScrapeState(
                file_path=r["file_path"],
                mtime=r["mtime"],
                status=r["status"],
                number=r["number"],
                fail_count=r["fail_count"],
                scraped_at=r["scraped_at"],
                origin_path=r["origin_path"],
                error=r["error"],
                failure_reason=r["failure_reason"],
                state_version=r["state_version"],
            )
            for r in rows
        ]

    def delete_state(self, file_path: Path) -> bool:
        """删除单文件状态记录（强制下次重刮）。

        删记录后 should_skip/should_retry 均返回 False，下次扫描自然重新刮削处理。
        记录不存在也返回 True，语义是"该记录不存在"。
        """
        return self._execute("DELETE FROM scrape_state WHERE file_path = ?", (str(file_path),))

    # 字段缺失检测默认只看这些关键字段（tags/series 天生可空不计）；
    # runtime 的 "0" 视为缺失——站点改版期刮到全空片的典型特征（TODO #1-C）
    INCOMPLETE_DEFAULT_FIELDS = ("title", "actors", "release", "runtime")

    def list_incomplete(self, required_fields: tuple[str, ...] | list[str] = INCOMPLETE_DEFAULT_FIELDS) -> list[dict]:
        """列出"done 但关键字段为空"的记录（数据源=刮削时存的结果摘要）。

        返回 [{file_path, number, missing: [缺失字段名]}]。无 summary_json 的
        旧记录不列出——没有摘要就没有判定依据，旧的不滥判——但这类记录会被字段检测漏掉（已知边界）。
        """
        rows = self._fetch(
            "SELECT file_path, number, summary_json FROM scrape_state WHERE status = 'done' AND summary_json != ''",
        )
        result: list[dict] = []
        for row in rows:
            try:
                summary = json.loads(row["summary_json"])
            except (ValueError, TypeError):
                continue
            if not isinstance(summary, dict):
                continue
            missing: list[str] = []
            for field in required_fields:
                value = summary.get(field)
                if value in (None, "", [], "0"):
                    missing.append(field)
            if missing:
                result.append({"file_path": row["file_path"], "number": row["number"], "missing": missing})
        return result
