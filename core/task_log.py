"""
core/task_log.py — Per-workspace task progress log (ingest/lint/autofill)
Captures print output from background flows into an in-memory ring buffer,
keyed by (user_id, workspace).
Progress data is also written to shared files for multi-worker visibility.
"""
import io
import json
import re
import sys
import time
import threading
from collections import deque, defaultdict
from datetime import datetime
from pathlib import Path


class TaskLogManager:
    """Global singleton: stores per-(user, workspace) task logs + structured progress."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._logs = defaultdict(lambda: deque(maxlen=2000))
                    cls._instance._meta = {}
                    cls._instance._log_lock = threading.Lock()
                    cls._instance._progress = {}  # key -> structured progress
                    cls._instance._progress_lock = threading.Lock()
        return cls._instance

    # ── 文件持久化路径（跨 worker 共享） ──
    _PROGRESS_DIR = Path(__file__).resolve().parent.parent / "data" / ".ingest_status"
    _LOG_DIR = Path(__file__).resolve().parent.parent / "data" / ".task_logs"
    _LOG_MAX_LINES = 2000  # 与内存 deque maxlen 一致

    def _progress_file(self, user_id: str, workspace: str) -> Path:
        self._PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
        return self._PROGRESS_DIR / f"{user_id}__{workspace}_progress.json"

    def set_progress(self, user_id: str, workspace: str, **kwargs):
        """Update structured progress for a (user, workspace) pair.
        Also writes to a shared file for multi-worker visibility.

        Timestamp protection: if existing progress has a FUTURE 'updated' timestamp
        (set by terminate endpoint), reject older writes to prevent stale threads
        from overwriting the stopping sentinel."""
        key = f"{user_id}:{workspace}"
        now = time.time()
        force = kwargs.pop("force", False)
        new_updated = kwargs.pop("updated", now)
        with self._progress_lock:
            if key not in self._progress:
                self._progress[key] = {
                    "phase": "idle",
                    "current_file": 0,
                    "total_files": 0,
                    "current_file_name": "",
                    "total_chunks": 0,
                    "map_done": 0,
                    "total_concepts": 0,
                    "reduce_done": 0,
                    "started": 0,
                }
            # Timestamp guard: reject writes older than existing timestamp
            existing_updated = self._progress[key].get("updated", 0)
            if not force and new_updated < existing_updated:
                return  # Stale write (e.g. old thread trying to overwrite terminate's stopping)
            self._progress[key].update(kwargs)
            self._progress[key]["updated"] = new_updated
            snapshot = dict(self._progress[key])
        # Write to shared file (non-blocking best-effort)
        try:
            self._progress_file(user_id, workspace).write_text(
                json.dumps(snapshot), encoding="utf-8"
            )
        except Exception:
            pass

    def get_progress(self, user_id: str, workspace: str) -> dict:
        """Read progress: prefer file (shared across workers), fallback to in-memory."""
        key = f"{user_id}:{workspace}"
        fpath = self._progress_file(user_id, workspace)
        try:
            if fpath.exists():
                data = json.loads(fpath.read_text(encoding="utf-8"))
                # Update memory cache with authoritative file data
                with self._progress_lock:
                    self._progress[key] = data
                return data
        except Exception:
            pass
        # Fallback: in-memory (this worker's set_progress may have been called but file not yet synced)
        with self._progress_lock:
            mem = self._progress.get(key)
            if mem:
                return dict(mem)
        return {"phase": "idle"}

    def clear_progress(self, user_id: str = "", workspace: str = ""):
        with self._progress_lock:
            if user_id and workspace:
                self._progress.pop(f"{user_id}:{workspace}", None)
            elif user_id:
                to_remove = [k for k in self._progress if k.startswith(f"{user_id}:")]
                for k in to_remove:
                    self._progress.pop(k, None)
            else:
                self._progress.clear()

    def _log_file(self, user_id: str, workspace: str) -> Path:
        """JSONL 日志文件路径（跨 worker 共享）"""
        self._LOG_DIR.mkdir(parents=True, exist_ok=True)
        return self._LOG_DIR / f"{user_id}__{workspace}.jsonl"

    def _truncate_log_file(self, fpath: Path):
        """日志文件超限时裁剪头部，保留最后 _LOG_MAX_LINES 行"""
        try:
            lines = fpath.read_text(encoding="utf-8").splitlines()
            if len(lines) > self._LOG_MAX_LINES:
                keep = lines[-self._LOG_MAX_LINES:]
                fpath.write_text("\n".join(keep) + "\n", encoding="utf-8")
        except Exception:
            pass

    def append(self, user_id: str, workspace: str, message: str, level: str = "info"):
        key = f"{user_id}:{workspace}"
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "timestamp": time.time(),
            "message": message,
            "level": level,
        }
        with self._log_lock:
            self._logs[key].append(entry)
            self._meta[key] = {
                "user_id": user_id,
                "workspace": workspace,
                "last_active": time.time(),
                "total_lines": len(self._logs[key]),
            }
        # 追加写入 JSONL 文件（跨 worker 可见）
        try:
            fpath = self._log_file(user_id, workspace)
            with open(fpath, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            # 定期截断：每 200 次本 worker 写入检查一次文件大小
            # 用文件大小判断（比读行数快），超过 ~200KB 时截断
            line_count = self._meta.get(key, {}).get("total_lines", 0)
            if line_count % 200 == 0 and line_count > 0:
                try:
                    if fpath.stat().st_size > 200 * 1024:
                        self._truncate_log_file(fpath)
                except OSError:
                    pass
        except Exception:
            pass

    def get_logs(self, user_id: str = "", workspace: str = "", limit: int = 500, since: float = 0):
        # 优先从共享文件读取（跨 worker 可见），内存作为 fallback
        if user_id and workspace:
            fpath = self._log_file(user_id, workspace)
            logs = self._read_log_file(fpath)
            if not logs:
                # Fallback: 文件不存在或为空，读内存（可能是本 worker 刚写入但还没落盘）
                with self._log_lock:
                    key = f"{user_id}:{workspace}"
                    logs = list(self._logs.get(key, []))
        elif user_id:
            # 读该用户所有沙箱的日志文件
            logs = []
            log_dir = self._LOG_DIR
            if log_dir.exists():
                prefix = f"{user_id}__"
                for fpath in log_dir.iterdir():
                    if fpath.name.startswith(prefix) and fpath.suffix == ".jsonl":
                        logs.extend(self._read_log_file(fpath))
            if not logs:
                with self._log_lock:
                    for k, v in self._logs.items():
                        if k.startswith(f"{user_id}:"):
                            logs.extend(list(v))
            logs.sort(key=lambda x: x.get("timestamp", 0))
        else:
            # 读所有日志文件
            logs = []
            log_dir = self._LOG_DIR
            if log_dir.exists():
                for fpath in log_dir.iterdir():
                    if fpath.suffix == ".jsonl":
                        logs.extend(self._read_log_file(fpath))
            if not logs:
                with self._log_lock:
                    for v in self._logs.values():
                        logs.extend(list(v))
            logs.sort(key=lambda x: x.get("timestamp", 0))

        if since > 0:
            logs = [l for l in logs if l.get("timestamp", 0) > since]
        return logs[-limit:]

    @staticmethod
    def _read_log_file(fpath: Path) -> list:
        """从 JSONL 文件读取日志条目"""
        try:
            if not fpath.exists():
                return []
            entries = []
            for line in fpath.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            return entries
        except Exception:
            return []

    def list_keys(self):
        """List all (user, workspace) pairs with metadata."""
        with self._log_lock:
            return [
                {**meta, "key": key}
                for key, meta in self._meta.items()
            ]

    def clear(self, user_id: str = "", workspace: str = ""):
        with self._log_lock:
            if user_id and workspace:
                key = f"{user_id}:{workspace}"
                self._logs.pop(key, None)
                self._meta.pop(key, None)
                # 删除对应的日志文件
                try:
                    self._log_file(user_id, workspace).unlink(missing_ok=True)
                except Exception:
                    pass
            elif user_id:
                to_remove = [k for k in self._logs if k.startswith(f"{user_id}:")]
                for k in to_remove:
                    self._logs.pop(k, None)
                    self._meta.pop(k, None)
                # 删除该用户所有日志文件
                try:
                    log_dir = self._LOG_DIR
                    if log_dir.exists():
                        prefix = f"{user_id}__"
                        for fpath in log_dir.iterdir():
                            if fpath.name.startswith(prefix) and fpath.suffix == ".jsonl":
                                fpath.unlink(missing_ok=True)
                except Exception:
                    pass
            else:
                self._logs.clear()
                self._meta.clear()
                # 删除所有日志文件
                try:
                    log_dir = self._LOG_DIR
                    if log_dir.exists():
                        for fpath in log_dir.iterdir():
                            if fpath.suffix == ".jsonl":
                                fpath.unlink(missing_ok=True)
                except Exception:
                    pass


# Singleton accessor
task_log = TaskLogManager()


# ── Thread-local stdout proxy ──
# Solves the sys.stdout global-replacement bug: when multiple threads in the
# same worker process each enter TaskOutputCapture, they used to wrap each
# other's TeeWriter (sys.stdout = TeeWriter(sys.stdout)), causing all print()
# output to cascade through every TeeWriter -> progress/logs cross-contamination.
#
# New design: sys.stdout is replaced ONCE with this proxy. The proxy checks
# thread-local storage to find the current thread's TeeWriter. Each thread's
# print() only routes through its OWN TeeWriter.
class _ThreadLocalStdout(io.TextIOBase):
    """Process-level stdout proxy that routes writes to per-thread TeeWriters."""

    def __init__(self, original):
        self._original = original
        self._tls = threading.local()

    def _get_writer(self):
        return getattr(self._tls, 'writer', None)

    def _set_writer(self, writer):
        self._tls.writer = writer

    def write(self, text):
        w = self._get_writer()
        if w is not None:
            return w.write(text)
        return self._original.write(text)

    def flush(self):
        try:
            self._original.flush()
        except Exception:
            pass

    def fileno(self):
        return self._original.fileno()

    @property
    def encoding(self):
        return getattr(self._original, 'encoding', 'utf-8')

    def isatty(self):
        return False


# Install the proxy once at module load. All threads share this single object.
_real_stdout = sys.stdout
_thread_local_stdout = _ThreadLocalStdout(_real_stdout)
sys.stdout = _thread_local_stdout


class TaskOutputCapture:
    """
    Context manager that redirects stdout into the task log.
    Thread-safe via thread-local storage: each thread gets its own TeeWriter,
    so concurrent threads in the same worker process don't cross-contaminate.
    Also passes through to original stdout so journalctl still captures it.

    checkpoint_offsets: pre-seed cumulative counters from a previous run's checkpoint
    (used by resume to maintain accurate progress across runs).
    """

    def __init__(self, user_id: str, workspace: str,
                 checkpoint_concepts: int = 0, checkpoint_reduce: int = 0,
                 gen: int = None, gen_fn=None):
        self.user_id = user_id
        self.workspace = workspace
        self._tee_writer = None
        self._cp_concepts = checkpoint_concepts
        self._cp_reduce = checkpoint_reduce
        self._gen = gen
        self._gen_fn = gen_fn

    def __enter__(self):
        self._tee_writer = _TeeWriter(
            _real_stdout, task_log, self.user_id, self.workspace,
            cp_concepts=self._cp_concepts, cp_reduce=self._cp_reduce,
            gen=self._gen, gen_fn=self._gen_fn,
        )
        _thread_local_stdout._set_writer(self._tee_writer)
        return self

    def __exit__(self, *args):
        _thread_local_stdout._set_writer(None)
        self._tee_writer = None


class _TeeWriter(io.TextIOBase):
    """Writes to both original stdout and task log manager.
    Also auto-parses progress patterns to update structured progress.

    Architecture:
    - _cumulative_*: sums from all previously COMPLETED files (or checkpoint pre-seed)
    - _current_file_*: counts for the file currently being processed
    - Progress = cumulative + current (never overwrites, only adds)
    - _RE_COMPLETE: promotes current → cumulative (only when a file fully finishes)
    - _RE_FILE_PROGRESS: captures unfinished current into cumulative (handles
      terminate-then-resume where a file was partially done)
    """

    # Compiled regex patterns for progress extraction
    _RE_FILE_PROGRESS = re.compile(r'\[(\d+)/(\d+)\]\s*提取:\s*(.+)\s*->')
    _RE_CHUNKS = re.compile(r'✂️\s*物理切分为\s*(\d+)\s*个知识块')
    _RE_MAP_DONE = re.compile(r'✅\s*线程\s*\d+\s*提取完毕')
    _RE_SHUFFLE = re.compile(r'Phase 2:\s*SHUFFLE')
    _RE_REDUCE_TOTAL = re.compile(r'发现\s*(\d+)\s*个独立核心概念')
    _RE_REDUCE_PROGRESS = re.compile(r'\[融合\s*(\d+)/(\d+)\]')
    _RE_COMPLETE = re.compile(r'提炼完成|全部完成|全部提炼完成')
    _RE_MAP_START = re.compile(r'Phase 1:\s*MAP')

    def __init__(self, original, log_mgr, user_id, workspace,
                 cp_concepts: int = 0, cp_reduce: int = 0,
                 gen: int = None, gen_fn=None):
        self._original = original
        self._log = log_mgr
        self._uid = user_id
        self._ws = workspace
        self._buffer = ""
        self._gen = gen          # This thread's generation number
        self._gen_fn = gen_fn    # Callable to get current generation

        # ── Cumulative: from completed files (or checkpoint pre-seed) ──
        self._cumulative_chunks = 0
        self._cumulative_map = 0
        self._cumulative_concepts = cp_concepts  # pre-seed from checkpoint
        self._cumulative_reduce = cp_reduce      # pre-seed from checkpoint

        # ── Current file: reset on each new file ──
        self._current_file_chunks = 0
        self._current_file_concepts = 0
        self._current_file_reduce = 0

        # ── Track whether cumulative already includes current file's base ──
        # Prevents double-counting when _RE_REDUCE_TOTAL overwrites total_concepts
        self._current_file_promoted = False

    def _update_progress(self, line: str):
        """Parse a stdout line and update structured progress if it matches a pattern."""

        # ── Generation check: stale thread must not overwrite progress ──
        if self._gen is not None and self._gen_fn and self._gen_fn() != self._gen:
            return  # Old thread superseded (terminate + new resume), skip all updates

        # ── File-level progress: [1/3] 提取: xxx.pdf -> workspace ──
        m = self._RE_FILE_PROGRESS.search(line)
        if m:
            # Previous file ended (complete or terminated).
            # Capture any unfinished work into cumulative so it's not lost.
            if self._current_file_reduce > 0 and not self._current_file_promoted:
                self._cumulative_reduce += self._current_file_reduce
            if self._current_file_concepts > 0 and not self._current_file_promoted:
                # Partial file: add total_concepts as well (some were skipped via checkpoint)
                self._cumulative_concepts += self._current_file_concepts

            # Reset current file counters
            self._current_file_chunks = 0
            self._current_file_concepts = 0
            self._current_file_reduce = 0
            self._current_file_promoted = False

            self._log.set_progress(
                self._uid, self._ws,
                phase="parsing",
                current_file=int(m.group(1)),
                total_files=int(m.group(2)),
                current_file_name=m.group(3).strip(),
                total_chunks=self._cumulative_chunks,
                map_done=self._cumulative_map,
                total_concepts=self._cumulative_concepts,
                reduce_done=self._cumulative_reduce,
                force=True,
            )
            return

        # ── Chunk count ──
        m = self._RE_CHUNKS.search(line)
        if m:
            self._current_file_chunks = int(m.group(1))
            self._log.set_progress(
                self._uid, self._ws,
                total_chunks=self._cumulative_chunks + self._current_file_chunks,
                phase="extracting",
                force=True,
            )
            return

        # ── MAP start ──
        if self._RE_MAP_START.search(line):
            self._log.set_progress(self._uid, self._ws, phase="extracting", force=True)
            return

        # ── MAP chunk done ──
        if self._RE_MAP_DONE.search(line):
            prog = self._log.get_progress(self._uid, self._ws)
            self._log.set_progress(
                self._uid, self._ws,
                map_done=prog.get("map_done", 0) + 1,
                phase="extracting",
                force=True,
            )
            return

        # ── SHUFFLE phase ──
        if self._RE_SHUFFLE.search(line):
            self._log.set_progress(self._uid, self._ws, phase="clustering", force=True)
            return

        # ── REDUCE total concepts ──
        m = self._RE_REDUCE_TOTAL.search(line)
        if m:
            self._current_file_concepts = int(m.group(1))
            self._current_file_reduce = 0
            # total_concepts = all cumulative + this file's concepts
            # (cumulative already includes pre-seed + previous files)
            self._log.set_progress(
                self._uid, self._ws,
                total_concepts=self._cumulative_concepts + self._current_file_concepts,
                phase="merging",
                force=True,
            )
            return

        # ── REDUCE per-concept progress ──
        m = self._RE_REDUCE_PROGRESS.search(line)
        if m:
            self._current_file_reduce = int(m.group(1))
            self._log.set_progress(
                self._uid, self._ws,
                reduce_done=self._cumulative_reduce + self._current_file_reduce,
                phase="merging",
                force=True,
            )
            return

        # ── Complete: file finished all phases ──
        if self._RE_COMPLETE.search(line):
            # Promote current file's counts into cumulative
            self._cumulative_chunks += self._current_file_chunks
            self._cumulative_map += self._current_file_chunks
            self._cumulative_concepts += self._current_file_concepts
            self._cumulative_reduce += self._current_file_concepts
            self._current_file_promoted = True
            # Reset current
            self._current_file_chunks = 0
            self._current_file_concepts = 0
            self._current_file_reduce = 0

            # Check if this thread has been superseded (terminate + resume started new gen)
            # If so, don't write phase=done — it would overwrite the stopping sentinel
            if self._gen is not None and self._gen_fn and self._gen_fn() != self._gen:
                return  # Stale thread, skip progress write

            self._log.set_progress(
                self._uid, self._ws,
                phase="done",
                total_chunks=self._cumulative_chunks,
                map_done=self._cumulative_map,
                total_concepts=self._cumulative_concepts,
                reduce_done=self._cumulative_reduce,
                force=True,
            )
            return

    def write(self, text):
        # Pass through to real stdout (so journalctl still works)
        try:
            self._original.write(text)
            self._original.flush()
        except Exception:
            pass

        # Buffer and split into lines for the task log
        if text:
            self._buffer += text
            while "\n" in self._buffer:
                line, self._buffer = self._buffer.split("\n", 1)
                line = line.strip()
                if line:
                    # Update structured progress
                    self._update_progress(line)

                    # Write to log ring buffer
                    level = "info"
                    if "❌" in line or "ERROR" in line or "失败" in line:
                        level = "error"
                    elif "⚠️" in line or "WARNING" in line:
                        level = "warning"
                    elif "✅" in line or "成功" in line or "完毕" in line:
                        level = "success"
                    self._log.append(self._uid, self._ws, line, level)
        return len(text) if text else 0

    def flush(self):
        try:
            self._original.flush()
        except Exception:
            pass

    def fileno(self):
        return self._original.fileno()

    @property
    def encoding(self):
        return getattr(self._original, "encoding", "utf-8")

    def isatty(self):
        return False
