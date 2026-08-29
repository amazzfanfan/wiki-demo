"""
app.py — LLM-Wiki OS 后端中枢 (v0.2.0)
JWT 用户隔离 + 多轮会话记忆 + API Key 管理 + 报告合成
"""
import os
import sys
import re
import json
import uuid
import time
import threading
import contextvars
from pathlib import Path
from typing import List, Dict, Any, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

# 确保能正常加载同级及子目录模块
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# ── 内部模块 ──
from core.path_resolver import (
    get_wiki_root, get_raw_root, get_concepts_dir, get_index_path,
    get_memory_db_path, ensure_user_dirs, list_workspaces, get_default_workspace,
    PROJECT_ROOT, USE_MINIO,
)


# ═══════════════════════════════════════════
# MinIO 辅助函数（前端 API 共用）
# ═══════════════════════════════════════════

def _minio_list_concepts(user_id: str, workspace: str) -> list:
    """列出 MinIO 中指定沙箱的所有概念文件 key（排除 index.md 和 mocs/）"""
    from core.storage import get_storage
    from core.path_resolver import minio_concepts_prefix
    s = get_storage()
    prefix = minio_concepts_prefix(user_id, workspace)
    all_keys = s.list_keys(prefix)
    return [k for k in all_keys if k.endswith(".md") and not k.endswith("/index.md") and "/mocs/" not in k]


def _minio_concept_name(key: str) -> str:
    """从 MinIO key 提取概念名（不含 .md 后缀）"""
    return key.split("/")[-1].replace(".md", "")
from core.auth import (
    AuthRequest, AuthResponse,
    register_user, login_user,
    get_current_user, get_optional_user, get_admin_user,
    save_user_api_key, delete_user_api_key, get_user_api_keys,
    decode_token,
)
from core.ingest_control import (
    request_terminate, clear_terminate, is_terminate_requested,
    get_checkpoint, clear_checkpoint, clear_shuffle_cache, mark_terminated, save_file_checkpoint,
    load_shuffle_cache, get_pending_concepts, mark_concept_done,
)
from core.llm_factory import set_user_context
from core.model_router import get_model_for_user, list_providers
from core.llm_factory import get_qwen_model

from workflows.query_flow import QueryFlow
from workflows.lint_flow import LintFlow
from workflows.autofill_flow import AutoFillFlow
from workflows.ingest_flow import IngestFlow
from core.task_log import task_log, TaskOutputCapture


# ==========================================
# 🚀 应用生命周期
# ==========================================
def _backfill_api_keys():
    """启动时回填：给没有 API Key 的老用户分配系统默认 Key"""
    default_key = os.getenv("QWEN_API_KEY", "")
    if not default_key:
        return
    from core.auth import _get_users_db
    conn = _get_users_db()
    try:
        rows = conn.execute("SELECT user_id, api_keys FROM users").fetchall()
        count = 0
        for row in rows:
            keys = json.loads(row["api_keys"] or "{}")
            has_key = any(v.get("api_key") for v in keys.values())
            if not has_key:
                keys["qwen"] = {
                    "api_key": default_key,
                    "base_url": os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
                    "model_id": os.getenv("QWEN_MODEL_ID", "deepseek-v4-pro"),
                }
                conn.execute(
                    "UPDATE users SET api_keys = ? WHERE user_id = ?",
                    (json.dumps(keys, ensure_ascii=False), row["user_id"])
                )
                count += 1
        if count:
            conn.commit()
            print(f"🔑 已为 {count} 个老用户回填系统默认 API Key")
    except Exception as e:
        print(f"⚠️ API Key 回填失败: {e}")
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(application: FastAPI):
    """启动 / 关闭钩子"""
    # 启动时初始化
    _init_memory_db()
    # _backfill_api_keys()  # 已禁用：不自动分配，让用户走系统默认 DEFAULT_PROVIDER
    print("🧠 LLM-Wiki OS v0.2.0 已启动")
    yield
    print("👋 LLM-Wiki OS 正在关闭...")


app = FastAPI(title="LLM-Wiki OS Backend", version="0.2.0", lifespan=lifespan)

# CORS（生产环境应改为白名单）
_cors_origins = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _set_user_context_middleware(request: Request, call_next):
    """从 JWT 提取 user_id + role 写入 ContextVar，让 llm_factory 自动选模型"""
    user_id = ""
    role = "user"
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        try:
            payload = decode_token(token)
            user_id = payload.get("sub", "")
            role = payload.get("role", "user")
        except Exception:
            pass
    # SSE 端点用 query param 传 token
    if not user_id:
        token = request.query_params.get("token", "")
        if token:
            try:
                payload = decode_token(token)
                user_id = payload.get("sub", "")
                role = payload.get("role", "user")
            except Exception:
                pass
    set_user_context(user_id, role=role)
    response = await call_next(request)
    return response


# ==========================================
# 🧠 Agno 记忆数据库（单例）
# ==========================================
_memory_db = None


def _init_memory_db():
    global _memory_db
    from agno.db.sqlite import SqliteDb
    db_path = get_memory_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _memory_db = SqliteDb(db_file=str(db_path))
    # 启用 WAL 模式以支持并发读写
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.close()
    print(f"📦 Memory DB: {db_path}")


def get_memory_db():
    """获取全局 Agno SqliteDb 实例"""
    if _memory_db is None:
        _init_memory_db()
    return _memory_db


# ==========================================
# 🏭 工作流工厂（按 user_id 动态创建）
# ==========================================
_query_flow_cache: Dict[str, QueryFlow] = {}


def get_query_flow(user_id: str = "") -> QueryFlow:
    """获取用户专属 QueryFlow 实例"""
    if user_id not in _query_flow_cache:
        _query_flow_cache[user_id] = QueryFlow(user_id=user_id)
    return _query_flow_cache[user_id]


# LintFlow / AutoFillFlow 保持全局，但传入 user_id
lint_flow = LintFlow()
autofill_flow = AutoFillFlow(threshold=5)


# ==========================================
# 📋 Pydantic 数据模型
# ==========================================
class ChatRequest(BaseModel):
    query: str
    workspace: Optional[str] = ""
    history: List[Dict[str, Any]] = []
    intent_override: Optional[str] = None
    session_id: Optional[str] = ""
    web_search_enabled: Optional[bool] = None  # None=自动决策, True=强制联网, False=仅本地


class WikiRetrieveRequest(BaseModel):
    query: str
    workspace: str
    max_chars: int = Field(default=20000, ge=1000, le=80000)


class ForgeRequest(BaseModel):
    action: str
    workspace: str


class SandboxCreate(BaseModel):
    name: str


class FileEditRequest(BaseModel):
    workspace: str
    file_id: str
    content: str


class ApiKeySaveRequest(BaseModel):
    provider: str
    api_key: str
    base_url: str = ""
    model_id: str = ""


class ReportRequest(BaseModel):
    topic: str
    workspace: str
    outline: Optional[str] = ""
    session_id: Optional[str] = ""


# ==========================================
# 🧠 意图路由器 (LLM Agent)
# ==========================================
class Intent:
    CHAT = "chat"
    SCAN = "scan"
    SUMMARY = "summary"
    QUERY = "query"
    ERROR = "error"


from pydantic import BaseModel as _PB, Field as _F
from typing import Literal as _L


class _IntentDecision(_PB):
    intent: _L["chat", "scan", "summary", "query"] = _F(
        description="chat(闲聊)/scan(扫描)/summary(概览)/query(知识查询)"
    )


class IntentRouter:
    def __init__(self):
        from agno.agent import Agent
        self.agent = Agent(
            model=get_qwen_model(),
            instructions=[
                "你是一个意图分类器。根据用户输入判断意图。",
                "- chat：打招呼、闲聊、夸赞、问AI身份",
                "- scan：询问知识库有什么概念/节点",
                "- summary：总结/概览知识库",
                "- query：具体知识问题，需检索资料",
                "不确定时优先 query。"
            ],
            output_schema=_IntentDecision,
            stream=False,
        )

    def classify(self, query: str) -> str:
        if not query or not query.strip():
            return Intent.ERROR
        q = query.strip()
        if len(q) <= 3 and re.match(r'^[\s\u4e00-\u9fa5a-zA-Z]{1,3}$', q):
            return Intent.CHAT
        try:
            result = self.agent.run(q)
            if hasattr(result.content, 'model_dump'):
                return result.content.model_dump()['intent']
            if hasattr(result.content, 'intent'):
                return result.content.intent
            text = str(result.content).lower()
            for tag in ['chat', 'scan', 'summary', 'query']:
                if tag in text:
                    return tag
        except Exception:
            pass
        return Intent.QUERY


_intent_router = None


def classify_intent(query: str) -> str:
    global _intent_router
    if _intent_router is None:
        _intent_router = IntentRouter()
    return _intent_router.classify(query)


# ==========================================
# 🏥 健康检查
# ==========================================
@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        "version": "0.2.0",
        "timestamp": time.time(),
        "memory_db": str(get_memory_db_path()),
    }


# ==========================================
# 🔐 认证端点
# ==========================================
@app.post("/api/auth/register", response_model=AuthResponse)
async def api_register(req: AuthRequest):
    try:
        return register_user(req.username, req.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/auth/login", response_model=AuthResponse)
async def api_login(req: AuthRequest):
    try:
        return login_user(req.username, req.password)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))


@app.get("/api/auth/me")
async def api_me(user=Depends(get_current_user)):
    return {"user_id": user["user_id"], "username": user["username"]}


# ==========================================
# 🔑 API Key 管理
# ==========================================
@app.get("/api/settings/providers")
async def api_list_providers(user=Depends(get_current_user)):
    """列出所有模型提供商 + 用户已配置的"""
    providers = list_providers()
    user_keys = get_user_api_keys(user["user_id"])
    for p in providers:
        p["configured"] = p["id"] in user_keys
        if p["id"] in user_keys:
            p["user_config"] = user_keys[p["id"]]
    return providers


@app.post("/api/settings/api-key")
async def api_save_key(req: ApiKeySaveRequest, user=Depends(get_current_user)):
    """保存用户 API Key（保存后自动清除 QueryFlow 缓存以切换模型）"""
    if not req.api_key or len(req.api_key) < 8:
        raise HTTPException(status_code=400, detail="API Key 太短")
    ok = save_user_api_key(user["user_id"], req.provider, req.api_key, req.base_url, req.model_id)
    if not ok:
        raise HTTPException(status_code=404, detail="用户不存在")
    # 清除该用户的 QueryFlow 缓存，下次请求会用新模型重建
    _query_flow_cache.pop(user["user_id"], None)
    return {"status": "success", "provider": req.provider}


@app.delete("/api/settings/api-key/{provider}")
async def api_delete_key(provider: str, user=Depends(get_current_user)):
    """删除用户指定 provider 的 API Key，回退到系统默认模型"""
    ok = delete_user_api_key(user["user_id"], provider)
    if not ok:
        raise HTTPException(status_code=404, detail="用户不存在")
    _query_flow_cache.pop(user["user_id"], None)
    return {"status": "success", "provider": provider}


# ==========================================
# 📝 会话历史管理
# ==========================================
@app.get("/api/sessions")
async def api_list_sessions(
    workspace: str = Query(default=""),
    user=Depends(get_current_user),
):
    """列出用户在指定工作区的历史会话"""
    db = get_memory_db()
    user_id = user["user_id"]
    from agno.db.base import SessionType
    all_sessions = db.get_sessions(user_id=user_id, session_type=SessionType.AGENT)

    # 按工作区前缀过滤
    prefix = f"{user_id}:{workspace}:" if workspace else f"{user_id}:"
    filtered = []
    for s in all_sessions:
        sid = s.session_id if hasattr(s, 'session_id') else (s.get('session_id', '') if isinstance(s, dict) else '')
        if sid.startswith(prefix):
            entry = {
                "session_id": sid,
                "created_at": getattr(s, 'created_at', None) or (s.get('created_at') if isinstance(s, dict) else None),
                "updated_at": getattr(s, 'updated_at', None) or (s.get('updated_at') if isinstance(s, dict) else None),
            }
            # 尝试提取 session name
            session_data = getattr(s, 'session_data', None) or (s.get('session_data') if isinstance(s, dict) else None)
            if session_data and isinstance(session_data, dict):
                entry["name"] = session_data.get("session_name", "")
            else:
                entry["name"] = ""
            filtered.append(entry)

    # 按 updated_at 倒序
    filtered.sort(key=lambda x: x.get("updated_at") or 0, reverse=True)
    return filtered


@app.post("/api/sessions/create")
async def api_create_session(
    workspace: str = Query(default=""),
    user=Depends(get_current_user),
):
    """创建新会话，返回 session_id"""
    uid = user["user_id"]
    ws = workspace or "global"
    session_id = f"{uid}:{ws}:{uuid.uuid4().hex[:12]}"
    return {"session_id": session_id, "workspace": ws}


@app.delete("/api/sessions/{session_id}")
async def api_delete_session(session_id: str, user=Depends(get_current_user)):
    """删除指定会话"""
    uid = user["user_id"]
    if not session_id.startswith(f"{uid}:"):
        raise HTTPException(status_code=403, detail="无权删除此会话")

    db = get_memory_db()
    try:
        db.delete_session(session_id)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sessions/{session_id}/messages")
async def api_get_session_messages(session_id: str, user=Depends(get_current_user)):
    """获取指定会话的历史消息"""
    uid = user["user_id"]
    if not session_id.startswith(f"{uid}:"):
        raise HTTPException(status_code=403, detail="无权查看此会话")

    try:
        import sqlite3 as _sqlite
        db_path = str(get_memory_db_path())
        conn = _sqlite.connect(db_path)
        try:
            row = conn.execute(
                "SELECT runs FROM agno_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if not row:
                return {"session_id": session_id, "messages": []}

            messages = []
            runs_raw = row[0]
            if runs_raw:
                runs = json.loads(runs_raw) if isinstance(runs_raw, str) else runs_raw
                if isinstance(runs, str):
                    runs = json.loads(runs)
                for run in runs:
                    if isinstance(run, str):
                        run = json.loads(run)
                    run_msgs = run.get('messages', [])
                    if isinstance(run_msgs, str):
                        run_msgs = json.loads(run_msgs)
                    for m in run_msgs:
                        if isinstance(m, str):
                            m = json.loads(m)
                        role = m.get('role', '')
                        content = m.get('content', '')
                        if role in ('user', 'assistant') and content:
                            messages.append({"role": role, "content": str(content)[:5000]})

            return {"session_id": session_id, "messages": messages}
        finally:
            conn.close()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# 🔍 管理员监控 API
# ==========================================
@app.get("/api/admin/users")
async def admin_list_users(admin=Depends(get_admin_user)):
    """列出所有用户及其统计信息"""
    import sqlite3 as _sqlite
    conn = _sqlite.connect(str(get_memory_db_path()))
    try:
        # 从 users.db 获取用户列表
        uconn = _sqlite.connect(str(PROJECT_ROOT / "data" / "users.db"))
        uconn.row_factory = _sqlite.Row
        try:
            users = uconn.execute(
                "SELECT user_id, username, role, created_at FROM users ORDER BY created_at DESC"
            ).fetchall()
            result = []
            for u in users:
                # 统计该用户的会话数
                session_count = conn.execute(
                    "SELECT COUNT(*) FROM agno_sessions WHERE user_id = ?", (u["user_id"],)
                ).fetchone()[0]
                # 最新消息时间
                last_row = conn.execute(
                    "SELECT MAX(updated_at) FROM agno_sessions WHERE user_id = ?", (u["user_id"],)
                ).fetchone()
                last_active = last_row[0] if last_row and last_row[0] else None
                result.append({
                    "user_id": u["user_id"],
                    "username": u["username"],
                    "role": u["role"] if "role" in u.keys() else "user",
                    "created_at": u["created_at"],
                    "session_count": session_count,
                    "last_active": last_active,
                })
            return result
        finally:
            uconn.close()
    finally:
        conn.close()


@app.get("/api/admin/sessions")
async def admin_list_all_sessions(
    user_id: str = Query(default=""),
    admin=Depends(get_admin_user),
):
    """列出所有用户的会话（管理员视角）"""
    import sqlite3 as _sqlite
    db_path = str(get_memory_db_path())
    conn = _sqlite.connect(db_path)
    conn.row_factory = _sqlite.Row
    try:
        if user_id:
            rows = conn.execute(
                "SELECT session_id, user_id, session_data, created_at, updated_at FROM agno_sessions WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT session_id, user_id, session_data, created_at, updated_at FROM agno_sessions ORDER BY updated_at DESC LIMIT 200"
            ).fetchall()

        sessions = []
        for r in rows:
            entry = {
                "session_id": r["session_id"],
                "user_id": r["user_id"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "name": "",
            }
            sd = json.loads(r["session_data"]) if r["session_data"] else {}
            if isinstance(sd, dict):
                entry["name"] = sd.get("session_name", "")
            sessions.append(entry)
        return sessions
    finally:
        conn.close()


@app.get("/api/admin/logs")
async def admin_stream_logs(request: Request, admin=Depends(get_admin_user)):
    """管理员实时日志流 (SSE) — 推送 systemd journal"""
    import subprocess

    async def log_stream():
        import asyncio
        proc = None
        # 先发送最近 200 行历史日志
        try:
            result = subprocess.run(
                ["journalctl", "-u", "llm-wiki", "-n", "200", "--no-pager", "-o", "short-iso"],
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.splitlines():
                yield f"data: {json.dumps({'type': 'log', 'content': line})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'log', 'content': f'⚠️ 无法读取 journalctl: {e}'})}\n\n"
            yield f"data: {json.dumps({'type': 'log', 'content': '提示: journalctl 仅在 systemd 管理的服务器上可用'})}\n\n"

        yield f"data: {json.dumps({'type': 'log', 'content': '── 历史日志结束，以下为实时推送 ──'})}\n\n"

        # 实时跟踪新日志
        try:
            proc = subprocess.Popen(
                ["journalctl", "-u", "llm-wiki", "-f", "--no-pager", "-o", "short-iso"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            while True:
                line = await asyncio.get_event_loop().run_in_executor(
                    None, proc.stdout.readline
                )
                if not line:
                    break
                line = line.rstrip('\n')
                if line:
                    yield f"data: {json.dumps({'type': 'log', 'content': line})}\n\n"
        except (asyncio.CancelledError, GeneratorExit):
            pass
        except Exception as e:
            yield f"data: {json.dumps({'type': 'log', 'content': f'⚠️ 日志流断开: {e}'})}\n\n"
        finally:
            if proc:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except Exception:
                    proc.kill()

    return StreamingResponse(log_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/admin/server-status")
async def admin_server_status(admin=Depends(get_admin_user)):
    """服务器运行状态概览"""
    import subprocess
    info = {}
    try:
        r = subprocess.run(["systemctl", "is-active", "llm-wiki"], capture_output=True, text=True, timeout=5)
        info["service"] = r.stdout.strip()
    except Exception:
        info["service"] = "unknown"
    try:
        r = subprocess.run(["uptime"], capture_output=True, text=True, timeout=5)
        info["uptime"] = r.stdout.strip()
    except Exception:
        info["uptime"] = "unknown"
    try:
        r = subprocess.run(["df", "-h", "/mnt/vdb"], capture_output=True, text=True, timeout=5)
        lines = r.stdout.strip().splitlines()
        info["disk"] = lines[-1] if len(lines) > 1 else "unknown"
    except Exception:
        info["disk"] = "unknown"
    try:
        r = subprocess.run(["free", "-h"], capture_output=True, text=True, timeout=5)
        lines = r.stdout.strip().splitlines()
        info["memory"] = lines[1] if len(lines) > 1 else "unknown"
    except Exception:
        info["memory"] = "unknown"
    return info


# ==========================================
# 📋 任务日志 (Task Logs)
# ==========================================
@app.get("/api/admin/task-logs")
async def admin_list_task_logs(admin=Depends(get_admin_user)):
    """列出所有有任务日志的 user:workspace 组合"""
    return task_log.list_keys()


@app.get("/api/admin/task-logs/{user_id}/{workspace}")
async def admin_get_task_logs(user_id: str, workspace: str, limit: int = 500, since: float = 0, admin=Depends(get_admin_user)):
    """获取指定 user:workspace 的任务日志"""
    logs = task_log.get_logs(user_id=user_id, workspace=workspace, limit=limit, since=since)
    return {"user_id": user_id, "workspace": workspace, "logs": logs, "total": len(logs)}


@app.get("/api/admin/task-logs/{user_id}/{workspace}/stream")
async def admin_stream_task_logs(user_id: str, workspace: str, request: Request, admin=Depends(get_admin_user)):
    """SSE 实时推送任务日志"""
    import asyncio

    async def stream():
        import asyncio
        last_ts = 0
        # 先发送历史日志
        history = task_log.get_logs(user_id=user_id, workspace=workspace, limit=200)
        for entry in history:
            yield f"data: {json.dumps(entry)}\n\n"
            last_ts = max(last_ts, entry.get("timestamp", 0))
        yield f"data: {json.dumps({'time': '', 'message': '── 历史日志结束，以下为实时推送 ──', 'level': 'info'})}\n\n"

        # 实时轮询新日志 — 用 try/except 检测断开（is_disconnected 在 uvicorn 下不可靠）
        try:
            while True:
                await asyncio.sleep(0.5)
                new_logs = task_log.get_logs(user_id=user_id, workspace=workspace, limit=50, since=last_ts)
                for entry in new_logs:
                    ts = entry.get("timestamp", 0)
                    if ts > last_ts:
                        yield f"data: {json.dumps(entry)}\n\n"
                        last_ts = ts
        except (asyncio.CancelledError, GeneratorExit):
            pass

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.delete("/api/admin/task-logs/{user_id}/{workspace}")
async def admin_clear_task_logs(user_id: str, workspace: str, admin=Depends(get_admin_user)):
    """清除指定 user:workspace 的任务日志"""
    task_log.clear(user_id=user_id, workspace=workspace)
    return {"status": "cleared"}


# ── 用户级任务日志（非管理员，只看自己的） ──
# 用文件存储摄入状态，解决多 worker 进程内存不共享的问题
_INGEST_STATUS_DIR = PROJECT_ROOT / "data" / ".ingest_status"
_INGEST_STATUS_DIR.mkdir(parents=True, exist_ok=True)

# ── Generation counter: prevents old threads from overwriting new thread's status ──
_ingest_gen_lock = threading.Lock()
_ingest_gen = {}  # (user_id, workspace) -> generation number

def _next_ingest_gen(user_id: str, workspace: str) -> int:
    """Increment and return a new generation number for this (user, workspace).
    同时持久化到文件，确保跨 Worker 可见。"""
    key = (user_id, workspace)
    with _ingest_gen_lock:
        new_gen = _ingest_gen.get(key, 0) + 1
        _ingest_gen[key] = new_gen
        # 写入状态文件，让其他 Worker 的 _current_ingest_gen() 能看到
        fpath = _INGEST_STATUS_DIR / f"{user_id}__{workspace}.json"
        try:
            data = {}
            if fpath.exists():
                data = json.loads(fpath.read_text(encoding="utf-8"))
            data["gen"] = new_gen
            fpath.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            pass
        return new_gen

def _current_ingest_gen(user_id: str, workspace: str) -> int:
    """Return max(in-memory gen, file gen) — ensures cross-worker visibility."""
    key = (user_id, workspace)
    with _ingest_gen_lock:
        mem_gen = _ingest_gen.get(key, 0)
    # Also check file (shared across workers)
    file_gen = 0
    try:
        fpath = _INGEST_STATUS_DIR / f"{user_id}__{workspace}.json"
        if fpath.exists():
            data = json.loads(fpath.read_text(encoding="utf-8"))
            file_gen = data.get("gen", 0)
    except Exception:
        pass
    result = max(mem_gen, file_gen)
    # Sync memory with the higher value
    with _ingest_gen_lock:
        if result > _ingest_gen.get(key, 0):
            _ingest_gen[key] = result
    return result

def _write_ingest_status(user_id: str, workspace: str, status: str, files: int = 0, started: float = 0, gen: int = None):
    """写入摄入状态到共享文件（多 worker 可见）。gen 用于防止旧线程覆盖新线程。"""
    fpath = _INGEST_STATUS_DIR / f"{user_id}__{workspace}.json"
    data = {"status": status, "files": files, "started": started}
    if gen is not None:
        data["gen"] = gen
    try:
        fpath.write_text(json.dumps(data), encoding="utf-8")
    except Exception:
        pass

def _read_ingest_status(user_id: str, workspace: str) -> dict:
    """从共享文件读取摄入状态"""
    fpath = _INGEST_STATUS_DIR / f"{user_id}__{workspace}.json"
    try:
        if fpath.exists():
            return json.loads(fpath.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"status": "idle", "files": 0, "started": 0}


@app.get("/api/task-logs/{workspace}/stream")
async def user_stream_task_logs(workspace: str, request: Request, user=Depends(get_current_user)):
    """用户级 SSE：实时推送当前 workspace 的任务日志"""
    import asyncio
    user_id = user["user_id"]

    async def stream():
        last_ts = 0
        last_progress_ts = 0
        # 先发历史
        history = task_log.get_logs(user_id=user_id, workspace=workspace, limit=200)
        for entry in history:
            yield f"data: {json.dumps(entry)}\n\n"
            last_ts = max(last_ts, entry.get("timestamp", 0))
        # 发当前进度快照（仅当摄入真正在进行时才发送，防止 SSE 重连时回放残留的 done/stopping 快照）
        cur_status_init = _read_ingest_status(user_id, workspace)
        if cur_status_init.get("status") == "ingesting":
            prog = task_log.get_progress(user_id, workspace)
            if prog.get("phase", "idle") not in ("idle",):
                yield f"data: {json.dumps({'type': 'progress', **prog})}\n\n"
                last_progress_ts = prog.get("updated", 0)
        else:
            # 摄入未进行中：发送 idle 状态 + 真实进度（前端需要看到 phase=done 来显示完成卡片）
            prog = task_log.get_progress(user_id, workspace)
            yield f"data: {json.dumps({'type': 'progress', 'status': 'idle', **prog})}\n\n"
        yield f"data: {json.dumps({'time': '', 'message': '── 实时推送中 ──', 'level': 'info'})}\n\n"

        try:
            last_status = cur_status_init.get("status", "idle")
            while True:
                await asyncio.sleep(0.5)
                new_logs = task_log.get_logs(user_id=user_id, workspace=workspace, limit=50, since=last_ts)
                for entry in new_logs:
                    ts = entry.get("timestamp", 0)
                    if ts > last_ts:
                        yield f"data: {json.dumps(entry)}\n\n"
                        last_ts = ts
                # 进度变化时也推送（但仅在摄入中时，避免终止后推送残留旧进度）
                cur_status = _read_ingest_status(user_id, workspace)
                cur_st = cur_status.get("status", "idle")
                prog = task_log.get_progress(user_id, workspace)
                prog_ts = prog.get("updated", 0)
                if prog_ts > last_progress_ts and cur_st == "ingesting":
                    yield f"data: {json.dumps({'type': 'progress', **prog})}\n\n"
                    last_progress_ts = prog_ts
                # 状态变更时发送信号（特别是 ingesting → stopping/idle 的转换）
                if cur_st != last_status:
                    if cur_st == "ingesting":
                        yield f"data: {json.dumps({'type': 'progress', **prog})}\n\n"
                        last_progress_ts = prog_ts
                    else:
                        # stopping / idle: 发送信号让前端知道后台已停，但保留实际进度 phase
                        # 这样前端能看到 phase="done" 并显示完成卡片
                        # 关键修复：如果进度文件有 phase=done 但还没推送过（因为 cur_st 已非 ingesting），
                        # 确保在此状态变更事件中包含最新进度
                        _evt = {'type': 'progress', 'status': cur_st, **prog}
                        print(f"🔔 [SSE] status={last_status}→{cur_st} phase={prog.get('phase')} total_concepts={prog.get('total_concepts')} reduce_done={prog.get('reduce_done')}", flush=True)
                        yield f"data: {json.dumps(_evt)}\n\n"
                        # 如果 phase=done 且之前未推送过（进度时间戳未更新），再发一次显式的进度事件
                        if prog.get('phase') == 'done' and prog_ts > last_progress_ts:
                            yield f"data: {json.dumps({'type': 'progress', **prog})}\n\n"
                            last_progress_ts = prog_ts
                    last_status = cur_st
        except (asyncio.CancelledError, GeneratorExit):
            pass

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/task-logs/{workspace}/status")
async def user_task_status(workspace: str, user=Depends(get_current_user)):
    """查询当前 workspace 是否正在摄入（含结构化进度）"""
    user_id = user["user_id"]
    info = _read_ingest_status(user_id, workspace)
    progress = task_log.get_progress(user_id, workspace)
    return {**info, "workspace": workspace, "progress": progress}


@app.get("/api/admin/sessions/{session_id}/messages")
async def admin_get_session_messages(session_id: str, admin=Depends(get_admin_user)):
    """管理员查看任意用户的会话消息"""
    import sqlite3 as _sqlite
    db_path = str(get_memory_db_path())
    conn = _sqlite.connect(db_path)
    try:
        row = conn.execute(
            "SELECT runs, user_id FROM agno_sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if not row:
            return {"session_id": session_id, "messages": []}

        messages = []
        runs_raw = row[0]
        if runs_raw:
            runs = json.loads(runs_raw) if isinstance(runs_raw, str) else runs_raw
            if isinstance(runs, str):
                runs = json.loads(runs)
            for run in runs:
                if isinstance(run, str):
                    run = json.loads(run)
                run_msgs = run.get('messages', [])
                if isinstance(run_msgs, str):
                    run_msgs = json.loads(run_msgs)
                for m in run_msgs:
                    if isinstance(m, str):
                        m = json.loads(m)
                    role = m.get('role', '')
                    content = m.get('content', '')
                    if role in ('user', 'assistant') and content:
                        messages.append({"role": role, "content": str(content)[:5000]})

        return {"session_id": session_id, "user_id": row[1], "messages": messages}
    finally:
        conn.close()


# ==========================================
# 🗣️ 1. 探求模式接口 (Query Mode)
# ==========================================
# ── 问候/帮助关键词拦截 → 返回使用引导 ──
_HELP_KEYWORDS = {
    "你好", "hello", "hi", "hey", "嗨",
    "你可以做什么", "你能做什么", "怎么用", "如何使用", "使用说明",
    "帮助", "help", "功能", "教程",
    "what can you do", "how to use",
}

_HELP_GUIDE = """👋 **欢迎使用 LLM-Wiki 知识研究系统！**

这是一个由 AI 多智能体驱动的私人知识库，以下是核心功能：

---

### 📤 上传资料（织网模式）
1. 切换到右上角 **「织网模式」**
2. 在 **「赛博熔炉」** 面板拖拽上传 PDF / Word / Markdown 文件
3. AI 会自动提取概念、建立双链、编织知识图谱

### 🔍 查询知识（探求模式）
1. 切换到 **「探求模式」**
2. 在底部输入框直接提问，例如：
   - *“板形控制的基本原理是什么？”*
   - *“冷轧带钢的张力控制有哪些方法？”*
3. AI 会先查本地知识库，不够时自动联网搜索

### 🗺️ 知识图谱
- 织网模式的力导向图展示概念之间的关联
- 点击节点可阅读概念详情，支持双链跳转

### 📋 隔离审批
- AI 不确定的新概念会进入 **「隔离审批区」**
- 你可以预览 → 批准入库 / 废弃

### 🔧 审查 & 修复
- 织网模式下点击 **「重织死链」** 和 **「填补黑洞」**
- AI 会检测断裂链接并自动补全缺失页面

### 📊 报告生成
- 切换到 **「报告模式」**
- 指定主题，AI 批量检索相关材料并生成结构化报告

---

💡 **提示**：先在左侧选择一个 **沙箱（Workspace）**，所有操作都在该沙箱内进行。"""


def _is_help_query(query: str) -> bool:
    q = query.lower().strip()
    if len(q) > 30:
        return False
    return any(kw in q for kw in _HELP_KEYWORDS)


@app.get("/api/intent/debug")
async def debug_intent(query: str, user=Depends(get_current_user)):
    return {"intent": classify_intent(query), "query": query}


@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest, user=Depends(get_current_user)):
    """流式应答中枢 — 五向意图分发器"""
    try:
        query = request.query.strip()
        workspace = request.workspace
        user_id = user["user_id"]
        session_id = request.session_id or f"{user_id}:{workspace or 'global'}:{uuid.uuid4().hex[:12]}"

        # ── 问候/帮助拦截 → 返回使用引导 ──
        if _is_help_query(query):
            async def help_stream():
                yield f"data: {json.dumps({'type': 'log', 'content': '📖 检测到使用引导请求'})}\n\n"
                yield f"data: {json.dumps({'type': 'text', 'content': _HELP_GUIDE})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return StreamingResponse(
                _wrap_stream_with_save(help_stream(), user_id, session_id, query),
                media_type="text/event-stream",
            )

        if request.intent_override and request.intent_override in (
            Intent.CHAT, Intent.SCAN, Intent.SUMMARY, Intent.QUERY
        ):
            intent = request.intent_override
        else:
            intent = classify_intent(query)

        print(f"🧠 [{user_id}] '{query[:40]}' -> {intent}")

        if intent == Intent.ERROR:
            async def error_stream():
                yield f"data: {json.dumps({'type': 'text', 'content': '⚠️ 请输入你的问题或指令。'})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return StreamingResponse(error_stream(), media_type="text/event-stream")

        if intent == Intent.CHAT:
            return StreamingResponse(
                _wrap_stream_with_save(
                    _stream_chat_reply(query, history=request.history, user_id=user_id, session_id=session_id),
                    user_id, session_id, query
                ),
                media_type="text/event-stream",
            )

        if intent == Intent.SCAN:
            return StreamingResponse(
                _wrap_stream_with_save(
                    _stream_scan_response(query, workspace, user_id),
                    user_id, session_id, query
                ),
                media_type="text/event-stream",
            )

        if intent == Intent.SUMMARY:
            return StreamingResponse(
                _wrap_stream_with_save(
                    _stream_summary_response(query, workspace, user_id, session_id),
                    user_id, session_id, query
                ),
                media_type="text/event-stream",
            )

        # QUERY 模式
        qf = get_query_flow(user_id)
        return StreamingResponse(
            _wrap_stream_with_save(
                qf.stream_execute(
                    user_question=query,
                    target_workspace=workspace,
                    history=request.history,
                    user_id=user_id,
                    session_id=session_id,
                    web_search_enabled=request.web_search_enabled,
                ),
                user_id, session_id, query
            ),
            media_type="text/event-stream",
        )
    except HTTPException:
        raise
    except ValueError as e:
        # 用户未配置 API Key 等业务错误 → 推送友好的 SSE 错误消息
        err_msg = str(e)
        async def error_stream():
            yield f"data: {json.dumps({'type': 'error', 'content': err_msg})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")
    except Exception as e:
        err_msg = f"系统异常: {str(e)}"
        async def error_stream():
            yield f"data: {json.dumps({'type': 'error', 'content': err_msg})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")


@app.post("/api/wiki/retrieve")
async def wiki_retrieve_endpoint(request: WikiRetrieveRequest, user=Depends(get_current_user)):
    """
    外部 Agent 检索入口：只返回当前沙箱的 wiki 上下文，不生成最终回答。

    典型用途：
    - voice agent 把本项目当作结构化知识源；
    - 先获取 local_context，再由调用方自己的 Agent 生成口语化/业务化回答。
    """
    query = request.query.strip()
    workspace = request.workspace.strip()
    user_id = user["user_id"]

    if not query:
        raise HTTPException(status_code=400, detail="query required")
    if not workspace:
        raise HTTPException(status_code=400, detail="workspace required")
    if ".." in workspace or "/" in workspace or "\\" in workspace:
        raise HTTPException(status_code=400, detail="invalid workspace name")

    qf = get_query_flow(user_id)
    try:
        return qf.retrieve_context(
            user_question=query,
            target_workspace=workspace,
            user_id=user_id,
            max_chars=request.max_chars,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"wiki retrieve failed: {e}")


# ==========================================
#  📦 会话持久化（统一存储所有意图的对话）
# ==========================================
def _save_session_message(user_id: str, session_id: str, user_msg: str, assistant_msg: str):
    """将一轮对话追加到 agno_sessions 表"""
    import sqlite3 as _sqlite
    db_path = str(get_memory_db_path())
    conn = _sqlite.connect(db_path)
    try:
        # 确保表存在
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agno_sessions (
                session_id TEXT PRIMARY KEY,
                session_type TEXT DEFAULT 'agent',
                agent_id TEXT,
                team_id TEXT,
                workflow_id TEXT,
                user_id TEXT,
                session_data TEXT,
                agent_data TEXT,
                team_data TEXT,
                workflow_data TEXT,
                metadata TEXT,
                runs TEXT,
                summary TEXT,
                created_at REAL,
                updated_at REAL
            )
        """)

        now = time.time()
        new_run = {
            "run_id": uuid.uuid4().hex,
            "user_id": user_id,
            "session_id": session_id,
            "messages": [
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": assistant_msg[:5000]},
            ],
            "created_at": now,
            "status": "completed",
        }

        row = conn.execute(
            "SELECT runs, session_data FROM agno_sessions WHERE session_id = ?",
            (session_id,)
        ).fetchone()

        if row:
            runs = json.loads(row[0]) if row[0] else []
            runs.append(new_run)
            conn.execute(
                "UPDATE agno_sessions SET runs = ?, updated_at = ? WHERE session_id = ?",
                (json.dumps(runs, ensure_ascii=False), now, session_id)
            )
        else:
            # 新会话：用第一条用户消息作为会话名
            session_name = user_msg[:30].strip()
            if len(user_msg) > 30:
                session_name += "..."
            session_data = json.dumps({"session_name": session_name}, ensure_ascii=False)
            conn.execute(
                "INSERT INTO agno_sessions (session_id, session_type, user_id, session_data, runs, created_at, updated_at) VALUES (?, 'agent', ?, ?, ?, ?, ?)",
                (session_id, user_id, session_data, json.dumps([new_run], ensure_ascii=False), now, now)
            )
        conn.commit()
    except Exception as e:
        print(f"  [WARN] save session error: {e}")
    finally:
        conn.close()


async def _wrap_stream_with_save(stream_gen, user_id, session_id, user_query):
    """包装 SSE 流，在流结束时自动保存对话到 DB"""
    assistant_text = ""
    try:
        async for chunk in stream_gen:
            # 从 SSE chunk 中提取 assistant 文本
            if chunk.startswith("data: "):
                try:
                    data = json.loads(chunk[6:].strip())
                    if data.get("type") == "text":
                        assistant_text += data.get("content", "")
                except:
                    pass
            yield chunk
    finally:
        if assistant_text:
            _save_session_message(user_id, session_id, user_query, assistant_text)


# ==========================================
#  意图分轨处理函数
# ==========================================
async def _stream_chat_reply(query: str, history: list = None, user_id: str = "", session_id: str = ""):
    """闲聊轨道：LLM 直接回复，挂载 db 实现多轮记忆"""
    from agno.agent import Agent

    model = get_model_for_user(user_id)
    agent = Agent(
        model=model,
        instructions=[
            "你是一个 AI 向导，回答简短、有趣、有个性。",
            "不要调用任何外部工具或知识库，直接基于你的常识回复。",
            "回复控制在 100 字以内。",
        ],
        stream=True,
    )

    system_prompt = f"用户说：{query}"
    if history:
        ctx = "【前情回顾】\n"
        for msg in history[-5:]:
            role = "用户" if msg.get('role') == 'user' else 'AI'
            ctx += f"{role}: {msg.get('content')}\n"
        system_prompt = f"{ctx}\n用户最新消息：{query}"

    try:
        response = agent.run(system_prompt)
        for chunk in response:
            text = chunk.content if hasattr(chunk, 'content') else str(chunk)
            if text and text != "None":
                yield f"data: {json.dumps({'type': 'text', 'content': text})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'type': 'text', 'content': f'⚠️ 闲聊模块异常: {str(e)}'})}\n\n"
    yield f"data: {json.dumps({'type': 'done'})}\n\n"


async def _stream_scan_response(query: str, workspace: str, user_id: str = ""):
    """扫描轨道：全局 or 指定沙箱"""
    import asyncio

    wiki_base = get_wiki_root(user_id)

    if not workspace or not workspace.strip():
        all_ws = list_workspaces(user_id)
        if not all_ws:
            content = "🔭 系统中尚未创建任何知识沙箱。\n\n请先创建沙箱并摄入原始资料。"
            yield f"data: {json.dumps({'type': 'log', 'content': '📡 [全局扫描] 未找到任何沙箱'})}\n\n"
            for i in range(0, len(content), 15):
                yield f"data: {json.dumps({'type': 'text', 'content': content[i:i+15]})}\n\n"
                await asyncio.sleep(0.02)
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        yield f"data: {json.dumps({'type': 'log', 'content': f'📡 [全局扫描] 正在扫描 {len(all_ws)} 个沙箱 ...'})}\n\n"
        await asyncio.sleep(0.3)

        total_nodes = 0
        ws_stats = []
        for ws_name in all_ws:
            count = 0
            if USE_MINIO:
                count = len(_minio_list_concepts(user_id, ws_name))
            else:
                concepts_dir = get_concepts_dir(user_id, ws_name)
                if concepts_dir.exists():
                    count = len([f for f in concepts_dir.glob("*.md") if f.stem.lower() != "index"])
            total_nodes += count
            ws_stats.append((ws_name, count))

        lines = [f"📡 全局扫描完毕，共检测到 **{len(all_ws)}** 个沙箱 / **{total_nodes}** 个知识节点：\n"]
        lines.append("| 沙箱 | 节点数 | 状态 |")
        lines.append("|------|--------|------|")
        for ws_name, count in ws_stats:
            status = "✅ 已激活" if count > 0 else "⭕ 虚空"
            lines.append(f"| {ws_name} | {count} | {status} |")
        lines.append("\n💡 在左侧切换沙箱隔离区可深入查看具体节点。")
        content = "\n".join(lines)
        for i in range(0, len(content), 15):
            yield f"data: {json.dumps({'type': 'text', 'content': content[i:i+15]})}\n\n"
            await asyncio.sleep(0.02)
        yield f"data: {json.dumps({'type': 'done'})}\n\n"
        return

    # 指定沙箱扫描
    available = []
    if USE_MINIO:
        concept_keys = _minio_list_concepts(user_id, workspace)
        available = sorted([_minio_concept_name(k) for k in concept_keys])
    else:
        concepts_dir = get_concepts_dir(user_id, workspace)
        if concepts_dir.exists():
            available = sorted([f.stem for f in concepts_dir.glob("*.md") if f.stem.lower() != "index"])

    if available:
        group_size = 8
        groups = [available[i:i + group_size] for i in range(0, len(available), group_size)]
        display_lines = [f"📡 扫描完毕，在沙箱 **{workspace}** 中检测到 **{len(available)}** 个知识节点：\n"]
        for group in groups:
            display_lines.append(f"{' | '.join(f'`{c}`' for c in group)}")
        display_lines.append(f"\n💡 点击图谱节点或直接输入问题即可深入探索。")
        content = "\n".join(display_lines)
    else:
        content = (f"🔭 沙箱 **{workspace}** 中尚未生成任何知识节点。\n\n"
                   f"试着拖拽一些原始资料到赛博熔炉中进行首次摄入吧！")

    yield f"data: {json.dumps({'type': 'log', 'content': f'📡 [扫描] 正在读取沙箱 [{workspace}] ...'})}\n\n"
    await asyncio.sleep(0.3)
    for i in range(0, len(content), 15):
        yield f"data: {json.dumps({'type': 'text', 'content': content[i:i+15]})}\n\n"
        await asyncio.sleep(0.02)
    yield f"data: {json.dumps({'type': 'done'})}\n\n"


async def _stream_summary_response(query: str, workspace: str, user_id: str = "", session_id: str = ""):
    """概览轨道：读取 index.md + LLM 总结，挂载 db"""
    import asyncio
    from agno.agent import Agent

    if not workspace or not workspace.strip():
        workspace = get_default_workspace(user_id)
        if not workspace:
            content = "📋 系统中尚未创建任何知识沙箱，无法生成概览。"
            for i in range(0, len(content), 15):
                yield f"data: {json.dumps({'type': 'text', 'content': content[i:i+15]})}\n\n"
                await asyncio.sleep(0.02)
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

    index_content = None
    if USE_MINIO:
        from core.storage import get_storage
        from core.path_resolver import minio_index_key
        s = get_storage()
        _idx_key = minio_index_key(user_id, workspace)
        if s.exists(_idx_key):
            index_content = s.read_text(_idx_key)
    else:
        index_path = get_index_path(user_id, workspace)
        if index_path.exists():
            index_content = index_path.read_text(encoding="utf-8")

    yield f"data: {json.dumps({'type': 'log', 'content': '📋 [概览] 正在读取导航地图 ...'})}\n\n"
    await asyncio.sleep(0.3)

    if index_content is not None:
        if len(index_content.strip()) < 50:
            content = f"📋 沙箱 **{workspace}** 的导航地图几乎空白。\n\n建议先进行知识摄入。"
            for i in range(0, len(content), 15):
                yield f"data: {json.dumps({'type': 'text', 'content': content[i:i+15]})}\n\n"
                await asyncio.sleep(0.02)
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
            return

        model = get_model_for_user(user_id)
        agent = Agent(
            model=model,
            db=get_memory_db(),
            user_id=user_id,
            session_id=session_id,
            num_history_runs=5,
            instructions=[
                "你是一位知识库架构师。根据导航地图总结核心内容领域和知识结构。",
                "回答控制在 200 字以内，使用 Markdown 格式。",
            ],
            stream=True,
        )
        prompt = f"【用户问题】: {query}\n\n【导航地图】:\n{index_content[:4000]}"
        try:
            response = agent.run(prompt)
            for chunk in response:
                text = chunk.content if hasattr(chunk, 'content') else str(chunk)
                if text and text != "None":
                    yield f"data: {json.dumps({'type': 'text', 'content': text})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'text', 'content': f'⚠️ 概览模块异常: {str(e)}'})}\n\n"
    else:
        content = f"📋 沙箱 **{workspace}** 中尚未建立导航地图。\n\n建议先摄入原始资料。"
        for i in range(0, len(content), 15):
            yield f"data: {json.dumps({'type': 'text', 'content': content[i:i+15]})}\n\n"
            await asyncio.sleep(0.02)
    yield f"data: {json.dumps({'type': 'done'})}\n\n"


# ==========================================
# 🕸️ 2. 织网模式 (Forge Mode)
# ==========================================
@app.post("/api/forge")
async def forge_endpoint(request: ForgeRequest, user=Depends(get_current_user)):
    if not request.workspace:
        raise HTTPException(status_code=400, detail="必须指定隔离沙箱！")

    user_id = user["user_id"]

    async def run_forge_task():
        action_name = "织网" if request.action == "reweave" else "填补黑洞" if request.action == "fill_blackhole" else request.action
        task_log.append(user_id, request.workspace, f"🔥 [锻造炉] 启动: {action_name}", "info")
        try:
            if request.action == "reweave":
                async for log in lint_flow.stream_run(request.workspace, user_id=user_id):
                    # 同时写入任务日志
                    try:
                        data = json.loads(log.replace("data: ", "").strip())
                        if data.get("type") == "log":
                            task_log.append(user_id, request.workspace, data["content"])
                    except Exception:
                        pass
                    yield log
            elif request.action == "fill_blackhole":
                async for log in autofill_flow.stream_run(request.workspace, user_id=user_id):
                    try:
                        data = json.loads(log.replace("data: ", "").strip())
                        if data.get("type") == "log":
                            task_log.append(user_id, request.workspace, data["content"])
                    except Exception:
                        pass
                    yield log
            else:
                yield f"data: {json.dumps({'type': 'log', 'content': '❌ 未知的织网指令。'})}\n\n"
        except Exception as e:
            task_log.append(user_id, request.workspace, f"💥 熔炉崩溃: {str(e)}", "error")
            yield f"data: {json.dumps({'type': 'log', 'content': f'💥 熔炉崩溃: {str(e)}'})}\n\n"
        task_log.append(user_id, request.workspace, f"✅ [锻造炉] {action_name} 完成", "success")
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(run_forge_task(), media_type="text/event-stream")


# ==========================================
# 🗂️ 3. 沙箱管理
# ==========================================
@app.post("/api/workspaces/create")
async def create_workspace(req: SandboxCreate, user=Depends(get_current_user)):
    user_id = user["user_id"]
    safe_name = re.sub(r'[\\/*?:"<>|]', "", req.name).strip()
    if not safe_name:
        raise HTTPException(status_code=400, detail="非法的沙箱名称！")

    try:
        # 🛡️ 防御性清理：创建新沙箱前，清除同名沙箱的所有残留状态
        # 场景：旧沙箱被终止/删除后状态文件残留 → 新沙箱不应继承旧检查点
        _base = Path(__file__).resolve().parent / "data"
        _stale_files = [
            _base / ".ingest_status" / f"{user_id}__{safe_name}.json",
            _base / ".ingest_status" / f"{user_id}__{safe_name}_progress.json",
            _base / ".ingest_control" / f"{user_id}__{safe_name}.checkpoint.json",
            _base / ".ingest_control" / f"{user_id}__{safe_name}.flag",
            _base / ".task_logs" / f"{user_id}__{safe_name}.jsonl",
        ]
        for _sf in _stale_files:
            _sf.unlink(missing_ok=True)
        # 清理内存状态
        task_log.clear(user_id=user_id, workspace=safe_name)
        task_log.clear_progress(user_id=user_id, workspace=safe_name)
        clear_checkpoint(user_id, safe_name)
        clear_terminate(user_id, safe_name)

        if USE_MINIO:
            # MinIO 模式：只初始化 index.md，不创建本地目录
            from core.storage import get_storage
            from core.path_resolver import minio_index_key
            s = get_storage()
            idx_key = minio_index_key(user_id, safe_name)
            s.write_text(idx_key, f"# {safe_name} - 知识导航\n\n等待知识摄入...\n")
        else:
            # 本地模式：创建本地目录
            wiki_dir = get_wiki_root(user_id) / safe_name / "concepts"
            raw_dir = get_raw_root(user_id) / safe_name
            wiki_dir.mkdir(parents=True, exist_ok=True)
            raw_dir.mkdir(parents=True, exist_ok=True)

        return {"status": "success", "workspace": safe_name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"开荒失败: {str(e)}")


@app.delete("/api/workspaces/{name}")
async def delete_workspace(name: str, user=Depends(get_current_user)):
    """彻底删除一个沙箱及其所有数据"""
    user_id = user["user_id"]
    safe_name = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    if not safe_name:
        raise HTTPException(status_code=400, detail="非法的沙箱名称！")

    import shutil
    base = Path(__file__).resolve().parent / "data"
    dirs_to_clean = [
        base / "wiki" / user_id / safe_name,       # wiki 数据
        base / "raw" / user_id / safe_name,          # 原始上传
    ]
    files_to_clean = [
        base / ".ingest_status" / f"{user_id}__{safe_name}.json",           # 摄入状态
        base / ".ingest_status" / f"{user_id}__{safe_name}_progress.json", # 进度数据
        base / ".ingest_control" / f"{user_id}__{safe_name}.checkpoint.json", # 检查点
        base / ".ingest_control" / f"{user_id}__{safe_name}.flag",          # 终止标记
        base / ".task_logs" / f"{user_id}__{safe_name}.jsonl",             # 任务日志
    ]

    deleted = []
    for d in dirs_to_clean:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            deleted.append(str(d))
    for f in files_to_clean:
        if f.exists():
            f.unlink(missing_ok=True)
            deleted.append(str(f))

    # 清理内存中的任务日志 + 进度 + 检查点 + 终止标记
    task_log.clear(user_id=user_id, workspace=safe_name)
    task_log.clear_progress(user_id=user_id, workspace=safe_name)
    clear_checkpoint(user_id, safe_name)
    clear_terminate(user_id, safe_name)

    # MinIO 模式：同时清理 MinIO 中的对象
    minio_deleted = 0
    if USE_MINIO:
        from core.storage import get_storage
        from core.path_resolver import minio_wiki_prefix, minio_raw_prefix
        s = get_storage()
        wiki_prefix = minio_wiki_prefix(user_id, safe_name)
        raw_prefix = minio_raw_prefix(user_id, safe_name)
        minio_deleted += s.delete_prefix(wiki_prefix)
        minio_deleted += s.delete_prefix(raw_prefix)

    total = len(deleted) + minio_deleted
    print(f"🗑️ 沙箱已删除: {user_id}/{safe_name}, 本地清理 {len(deleted)} 项, MinIO 清理 {minio_deleted} 个对象", flush=True)
    return {"status": "success", "deleted": total, "local_deleted": len(deleted), "minio_deleted": minio_deleted}


# ==========================================
# 📥 4. 文件上传（含校验）
# ==========================================
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md", ".pptx", ".ppt", ".xlsx", ".csv", ".html"}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


@app.post("/api/upload")
async def upload_batch_endpoint(
    workspace: str = Form(...),
    files: List[UploadFile] = File(...),
    user=Depends(get_current_user),
):
    user_id = user["user_id"]
    if not workspace:
        raise HTTPException(status_code=400, detail="必须指定目标沙箱！")
    if not files:
        raise HTTPException(status_code=400, detail="未检测到任何文件！")

    # 沙箱名校验：防止路径穿越和非法字符
    if ".." in workspace or "/" in workspace or "\\" in workspace:
        raise HTTPException(status_code=400, detail="沙箱名包含非法字符")
    # 允许中文、英文、数字、下划线、连字符、空格
    if not re.match(r'^[\w\u4e00-\u9fa5\s\-.]+$', workspace):
        raise HTTPException(status_code=400, detail=f"沙箱名 '{workspace}' 包含特殊字符，只允许中英文、数字、下划线、连字符和空格")

    # 文件名校验：清理危险字符
    for f in files:
        if f.filename:
            fname = Path(f.filename).name  # 去掉任何路径成分
            if ".." in fname or fname.startswith("."):
                raise HTTPException(status_code=400, detail=f"文件名非法: {f.filename}")

    # 文件校验
    for f in files:
        ext = Path(f.filename).suffix.lower() if f.filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")
        if f.size and f.size > MAX_FILE_SIZE:
            raise HTTPException(status_code=400, detail=f"文件 {f.filename} 超过 50MB 限制")

    # ── 根据 USE_MINIO 决定文件存储方式 ──
    from core.path_resolver import USE_MINIO

    saved_paths = []   # MinIO 模式：临时文件路径 | 本地模式：持久路径
    saved_keys = []    # MinIO 模式：待归档的 MinIO Key
    file_contents = {} # MinIO 模式：文件名 → 字节数据（后台线程归档用）

    try:
        import tempfile
        if USE_MINIO:
            # MinIO 模式：写入临时文件直接解析，后台异步归档到 MinIO raw/
            # 省去"先传 MinIO 再下载回来"的网络往返
            for f in files:
                safe_filename = Path(f.filename).name if f.filename else "unnamed"
                contents = await f.read()
                suffix = Path(safe_filename).suffix
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                    tmp.write(contents)
                    tmp_path = tmp.name
                saved_paths.append(tmp_path)
                saved_keys.append(f"raw/{user_id}/{workspace}/{safe_filename}")
                file_contents[safe_filename] = contents
                print(f"  📄 上传: {safe_filename} ({len(contents)} bytes)", flush=True)
        else:
            # 本地模式：写入 data/raw/{workspace}/
            raw_dir = get_raw_root(user_id) / workspace
            raw_dir.mkdir(parents=True, exist_ok=True)
            for f in files:
                safe_filename = Path(f.filename).name if f.filename else "unnamed"
                file_path = raw_dir / safe_filename
                contents = await f.read()
                file_path.write_bytes(contents)
                saved_paths.append(file_path)
                print(f"  📄 上传: {safe_filename} ({len(contents)} bytes)", flush=True)

        total_files = len(saved_paths)

        # 后台线程：用参数传递代替 os.environ 污染，输出捕获到任务日志
        # Generation counter: 防止旧线程 finally 覆盖新线程的 status
        my_gen = _next_ingest_gen(user_id, workspace)

        def run_background_batch():
            # 新摄入开始：清除终止标记和旧检查点（新上传 = 全新开始）
            clear_terminate(user_id, workspace)
            clear_checkpoint(user_id, workspace)  # New ingest: clear old checkpoint

            _write_ingest_status(user_id, workspace, "ingesting", files=total_files, started=time.time(), gen=my_gen)
            # 初始化结构化进度
            task_log.set_progress(
                user_id, workspace,
                phase="parsing", current_file=0, total_files=total_files,
                current_file_name="", total_chunks=0, map_done=0,
                total_concepts=0, reduce_done=0, started=time.time(),
                updated=time.time() + 99999,
            )
            terminated = False
            try:
                with TaskOutputCapture(
                    user_id=user_id, workspace=workspace,
                    gen=my_gen, gen_fn=lambda: _current_ingest_gen(user_id, workspace),
                ):
                    task_log.append(user_id, workspace, f"🚀 [批量摄入流] 启动，共 {total_files} 个文件。AI 正在提炼中，请耐心等待...", "info")
                    flow = IngestFlow()

                    if USE_MINIO:
                        from core.storage import get_storage
                        s = get_storage()
                        for i, (tmp_path, key) in enumerate(zip(saved_paths, saved_keys), 1):
                            # ── 每个文件前检查：终止信号 + generation 被取代 ──
                            if _current_ingest_gen(user_id, workspace) != my_gen:
                                task_log.append(user_id, workspace, "⚡ 新的摄入任务已启动，旧线程自动退出", "info")
                                terminated = True
                                break
                            if is_terminate_requested(user_id, workspace):
                                task_log.append(user_id, workspace, f"🛑 用户手动终止，已完成 {i-1}/{total_files} 个文件", "warning")
                                terminated = True
                                break

                            filename = key.split("/")[-1]
                            print(f"\n🚀 [{user_id}] [{i}/{total_files}] 提取: {filename} -> {workspace}")
                            try:
                                # 异步归档到 MinIO raw/（不阻塞解析）
                                try:
                                    s.write_bytes(key, file_contents[filename])
                                except Exception as e:
                                    print(f"⚠️ MinIO 归档失败（不影响解析）: {e}")
                                # 直接用临时文件解析，传入原始文件名避免日志显示临时名
                                result = flow.run(tmp_path, kb_name=workspace, user_id=user_id, doc_name=Path(filename).stem)
                                if result is False:
                                    terminated = True
                                    task_log.append(user_id, workspace, f"🛑 摄入在文件 {filename} 内被终止", "warning")
                                    break
                                if _current_ingest_gen(user_id, workspace) == my_gen:
                                    save_file_checkpoint(user_id, workspace, filename)
                            except Exception as e:
                                print(f"❌ 提取 {filename} 失败: {e}")
                            finally:
                                # 解析完删除临时文件
                                Path(tmp_path).unlink(missing_ok=True)
                    else:
                        # 本地模式：直接读本地路径
                        for i, fp in enumerate(saved_paths, 1):
                            # ── 每个文件前检查：终止信号 + generation 被取代 ──
                            if _current_ingest_gen(user_id, workspace) != my_gen:
                                task_log.append(user_id, workspace, "⚡ 新的摄入任务已启动，旧线程自动退出", "info")
                                terminated = True
                                break
                            if is_terminate_requested(user_id, workspace):
                                task_log.append(user_id, workspace, f"🛑 用户手动终止，已完成 {i-1}/{total_files} 个文件", "warning")
                                terminated = True
                                break

                            print(f"\n🚀 [{user_id}] [{i}/{total_files}] 提取: {fp.name} -> {workspace}")
                            try:
                                result = flow.run(str(fp), kb_name=workspace, user_id=user_id)
                                if result is False:
                                    terminated = True
                                    task_log.append(user_id, workspace, f"🛑 摄入在文件 {fp.name} 内被终止", "warning")
                                    break
                                if _current_ingest_gen(user_id, workspace) == my_gen:
                                    save_file_checkpoint(user_id, workspace, fp.name)
                            except Exception as e:
                                print(f"❌ 提取 {fp.name} 失败: {e}")

                    if not terminated:
                        task_log.append(user_id, workspace, f"✅ [{user_id}] 全部提炼完成！共处理 {total_files} 个文件", "success")
            finally:
                # 只有当前 generation 的线程才能写 status（防止旧线程覆盖新线程）
                if _current_ingest_gen(user_id, workspace) == my_gen:
                    if terminated:
                        mark_terminated(user_id, workspace)
                        # 终止时：仅将 phase 改为 idle，保留进度数据（不归零）
                        task_log.set_progress(user_id, workspace, phase="idle")
                    else:
                        # 正常完成：显式设置 phase=done（_RE_COMPLETE 可能未被触发）
                        clear_shuffle_cache(user_id, workspace)
                        prog = task_log.get_progress(user_id, workspace)
                        task_log.set_progress(
                            user_id, workspace,
                            phase="done",
                            total_concepts=prog.get("total_concepts", 0),
                            reduce_done=prog.get("reduce_done", 0),
                            force=True,
                        )
                    _write_ingest_status(user_id, workspace, "idle", gen=my_gen)

        _ctx = contextvars.copy_context()
        threading.Thread(target=_ctx.run, args=(run_background_batch,), daemon=True).start()

        return {
            "status": "success",
            "message": f"成功落盘 {len(files)} 个文件",
            "files": [f.filename for f in files],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"落盘失败: {str(e)}")


# ==========================================
# ⏹️ 摄入控制（终止 / 继续 / 状态）
# ==========================================
@app.post("/api/ingest/terminate")
async def terminate_ingest(
    workspace: str = Form(...),
    user=Depends(get_current_user),
):
    """终止当前摄入流水线（立即返回，后台线程在下一个检查点自动停止）"""
    user_id = user["user_id"]
    # 1. 写终止标记（后台线程在概念/文件间隙检查此标记）
    request_terminate(user_id, workspace)
    # 2. 写 stopping 到状态文件（表示后台线程正在停止中）
    #    旧线程 finally 会在 generation 匹配时写 idle
    _write_ingest_status(user_id, workspace, "stopping")
    # 3. 写 stopping 到进度文件（带未来时间戳，防止旧线程覆盖）
    #    前端 poll/SSE 看到 phase=stopping 时忽略更新
    task_log.set_progress(
        user_id, workspace,
        phase="stopping", current_file=0, total_files=0,
        current_file_name="", total_chunks=0, map_done=0,
        total_concepts=0, reduce_done=0, started=0,
        updated=time.time() + 9999,  # 未来时间戳，防止旧线程的 set_progress 覆盖
    )
    task_log.append(user_id, workspace, "🛑 摄入已停止，后台任务将在当前操作完成后自动退出", "warning")
    return {"status": "ok", "message": "摄入已停止"}


@app.post("/api/ingest/resume")
async def resume_ingest(
    workspace: str = Form(...),
    user=Depends(get_current_user),
):
    """
    继续摄入：清除终止标记，重新处理 raw 目录中的所有文件。
    已处理的概念会从检查点跳过，只对新概念调用 LLM。
    """
    user_id = user["user_id"]

    # 不再检查 status 文件——generation counter 保证旧线程不会干扰新线程
    # 用户点击“继续”时，旧线程可能仍在跑 LLM（最长 300s），但 gen 已递增
    # 旧线程 finally 检查 gen 不匹配会跳过写入

    # 清除终止标记
    clear_terminate(user_id, workspace)
    print(f"🔄 [RESUME] user={user_id} workspace={workspace}", flush=True)

    # 获取检查点信息
    cp = get_checkpoint(user_id, workspace)
    done_concepts = len(cp.get("done_concepts", []))
    done_files = set(cp.get("files_done", []))

    if USE_MINIO:
        # ── MinIO 模式：从 MinIO raw/ 下载文件到临时目录 ──
        from core.storage import get_storage
        from core.path_resolver import minio_raw_prefix

        s = get_storage()
        raw_prefix = minio_raw_prefix(user_id, workspace)
        all_keys = s.list_keys(raw_prefix)
        if not all_keys:
            raise HTTPException(status_code=404, detail="MinIO raw/ 中未找到已上传的原始文件")

        # 过滤已完成文件
        all_filenames = [k.split("/")[-1] for k in all_keys if k.split("/")[-1]]
        remaining_items = [(k, k.split("/")[-1]) for k in all_keys
                           if k.split("/")[-1] not in done_files]
        print(f"🔄 [RESUME/MINIO] raw_keys={[k.split('/')[-1] for k in all_keys]} done_files={done_files} remaining={len(remaining_items)}", flush=True)

        if not remaining_items:
            raise HTTPException(status_code=400, detail=f"所有文件均已处理完成（{len(done_files)} 个），无需继续摄入")

        remaining_count = len(remaining_items)

        # Load SHUFFLE cache for resume fast path
        shuffle_cache = load_shuffle_cache(user_id, workspace) or {}
        pending_total = max(0, sum(len(v) for v in shuffle_cache.values()) - done_concepts)
        if shuffle_cache:
            print(f"  \U0001f4e6 [RESUME] SHUFFLE cache: {len(shuffle_cache)} files, {pending_total} pending concepts", flush=True)

        resume_gen = _next_ingest_gen(user_id, workspace)
        _write_ingest_status(user_id, workspace, "ingesting", files=remaining_count, started=time.time(), gen=resume_gen)
        _resume_phase = "merging" if shuffle_cache else "parsing"
        task_log.set_progress(
            user_id, workspace,
            phase=_resume_phase, current_file=0, total_files=remaining_count,
            current_file_name="", total_chunks=0, map_done=0,
            total_concepts=done_concepts + pending_total, reduce_done=done_concepts,
            started=time.time(),
            updated=time.time() + 99999,
        )

        def run_resume_batch():
            clear_terminate(user_id, workspace)
            terminated = False
            try:
                with TaskOutputCapture(
                    user_id=user_id, workspace=workspace,
                    checkpoint_concepts=done_concepts, checkpoint_reduce=done_concepts,
                    gen=resume_gen, gen_fn=lambda: _current_ingest_gen(user_id, workspace),
                ):
                    task_log.append(
                        user_id, workspace,
                        f"🔄 [继续摄入/MINIO] 重启流水线，共 {remaining_count} 个待处理文件"
                        f"（跳过 {len(done_files)} 个已完成文件）。"
                        f"已有 {done_concepts} 个概念在检查点中将被跳过。", "info"
                    )
                    import tempfile
                    flow = IngestFlow()
                    for i, (key, filename) in enumerate(remaining_items, 1):
                        if _current_ingest_gen(user_id, workspace) != resume_gen:
                            task_log.append(user_id, workspace, "⚡ 新的摄入任务已启动，旧线程自动退出", "info")
                            terminated = True
                            break
                        if is_terminate_requested(user_id, workspace):
                            task_log.append(user_id, workspace, f"🛑 用户再次终止", "warning")
                            terminated = True
                            break
                        print(f"\n🚀 [{user_id}] [resume {i}/{remaining_count}] {filename} (from MinIO)")
                        try:
                            # 下载到临时文件
                            suffix = Path(filename).suffix
                            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                                tmp_path = tmp.name
                            s.download_to(key, Path(tmp_path))
                            _pending = shuffle_cache.get(Path(filename).stem)  # key matches save_shuffle_result(_fn=doc_name=stem)
                            result = flow.run(tmp_path, kb_name=workspace, user_id=user_id, doc_name=Path(filename).stem, pending_payloads=_pending)
                            Path(tmp_path).unlink(missing_ok=True)
                            if result is False:
                                terminated = True
                                break
                            if _current_ingest_gen(user_id, workspace) == resume_gen:
                                save_file_checkpoint(user_id, workspace, filename)
                        except Exception as e:
                            print(f"❌ {filename} 失败: {e}")

                    if not terminated:
                        task_log.append(user_id, workspace, f"✅ [继续摄入/MINIO] 全部完成！", "success")
            finally:
                if _current_ingest_gen(user_id, workspace) == resume_gen:
                    if terminated:
                        mark_terminated(user_id, workspace)
                        # 终止时：仅将 phase 改为 idle，保留进度数据（不归零）
                        task_log.set_progress(user_id, workspace, phase="idle")
                    else:
                        # 正常完成：显式设置 phase=done
                        clear_shuffle_cache(user_id, workspace)
                        prog = task_log.get_progress(user_id, workspace)
                        task_log.set_progress(
                            user_id, workspace,
                            phase="done",
                            total_concepts=prog.get("total_concepts", 0),
                            reduce_done=prog.get("reduce_done", 0),
                            force=True,
                        )
                    _write_ingest_status(user_id, workspace, "idle", gen=resume_gen)

        _ctx = contextvars.copy_context()
        threading.Thread(target=_ctx.run, args=(run_resume_batch,), daemon=True).start()

        return {
            "status": "ok",
            "message": f"继续摄入已启动，{remaining_count} 个文件（跳过 {len(done_files)} 个已完成），{done_concepts} 个概念将从检查点跳过",
            "files": [fn for _, fn in remaining_items],
            "checkpoint_concepts": done_concepts,
            "skipped_files": list(done_files),
            "cache_mode": len(done_files) > 0,
        }

    # ── 本地模式 ──
    raw_dir = get_raw_root(user_id) / workspace
    if not raw_dir.exists():
        print(f"❌ [RESUME] raw_dir not found: {raw_dir}", flush=True)
        raise HTTPException(status_code=404, detail="没有找到已上传的原始文件")

    saved_paths = sorted(raw_dir.iterdir())
    saved_paths = [f for f in saved_paths if f.is_file()]
    if not saved_paths:
        raise HTTPException(status_code=404, detail="raw 目录为空")

    remaining_paths = [f for f in saved_paths if f.name not in done_files]
    shuffle_cache_local = load_shuffle_cache(user_id, workspace) or {}
    pending_total_local = max(0, sum(len(v) for v in shuffle_cache_local.values()) - done_concepts)
    print(f"🔄 [RESUME] raw_files={[f.name for f in saved_paths]} done_files={done_files} remaining={len(remaining_paths)} done_concepts={done_concepts}", flush=True)

    if not remaining_paths:
        raise HTTPException(status_code=400, detail=f"所有文件均已处理完成（{len(done_files)} 个），无需继续摄入")

    # Generation counter: 防止旧线程 finally 覆盖新线程的 status
    resume_gen = _next_ingest_gen(user_id, workspace)

    # 在启动线程前先写好初始状态（避免 SSE 连上时读到旧的 idle）
    _write_ingest_status(user_id, workspace, "ingesting", files=len(remaining_paths), started=time.time(), gen=resume_gen)
    _resume_phase_local = "merging" if shuffle_cache_local else "parsing"
    task_log.set_progress(
        user_id, workspace,
        phase=_resume_phase_local, current_file=0, total_files=len(remaining_paths),
        current_file_name="", total_chunks=0, map_done=0,
        total_concepts=done_concepts + pending_total_local, reduce_done=done_concepts,
        started=time.time(),
        updated=time.time() + 99999,
    )

    # 启动后台线程重新处理（只处理未完成文件）
    def run_resume_batch():
        clear_terminate(user_id, workspace)
        terminated = False
        try:
            # 传入检查点偏移量，让 _TeeWriter 的累计计数器从上次停止处继续
            with TaskOutputCapture(
                user_id=user_id, workspace=workspace,
                checkpoint_concepts=done_concepts, checkpoint_reduce=done_concepts,
                gen=resume_gen, gen_fn=lambda: _current_ingest_gen(user_id, workspace),
            ):
                task_log.append(
                    user_id, workspace,
                    f"🔄 [继续摄入] 重启流水线，共 {len(remaining_paths)} 个待处理文件"
                    f"（跳过 {len(done_files)} 个已完成文件）。"
                    f"已有 {done_concepts} 个概念在检查点中将被跳过。", "info"
                )
                flow = IngestFlow()
                for i, fp in enumerate(remaining_paths, 1):
                    if _current_ingest_gen(user_id, workspace) != resume_gen:
                        task_log.append(user_id, workspace, "⚡ 新的摄入任务已启动，旧线程自动退出", "info")
                        terminated = True
                        break
                    if is_terminate_requested(user_id, workspace):
                        task_log.append(user_id, workspace, f"🛑 用户再次终止", "warning")
                        terminated = True
                        break
                    print(f"\n🚀 [{user_id}] [resume {i}/{len(remaining_paths)}] {fp.name}")
                    try:
                        _pending_local = shuffle_cache_local.get(fp.name)
                        result = flow.run(str(fp), kb_name=workspace, user_id=user_id, pending_payloads=_pending_local)
                        if result is False:
                            terminated = True
                            break
                        if _current_ingest_gen(user_id, workspace) == resume_gen:
                            save_file_checkpoint(user_id, workspace, fp.name)
                    except Exception as e:
                        print(f"❌ {fp.name} 失败: {e}")

                if not terminated:
                    task_log.append(user_id, workspace, f"✅ [继续摄入] 全部完成！", "success")
        finally:
            # 只有当前 generation 的线程才能写 status（防止旧线程覆盖新线程）
            if _current_ingest_gen(user_id, workspace) == resume_gen:
                if terminated:
                    mark_terminated(user_id, workspace)
                    # 终止时：仅将 phase 改为 idle，保留进度数据（不归零）
                    task_log.set_progress(user_id, workspace, phase="idle")
                else:
                    # 正常完成：显式设置 phase=done
                    clear_shuffle_cache(user_id, workspace)
                    prog = task_log.get_progress(user_id, workspace)
                    task_log.set_progress(
                        user_id, workspace,
                        phase="done",
                        total_concepts=prog.get("total_concepts", 0),
                        reduce_done=prog.get("reduce_done", 0),
                        force=True,
                    )
                _write_ingest_status(user_id, workspace, "idle", gen=resume_gen)

    _ctx = contextvars.copy_context()
    threading.Thread(target=_ctx.run, args=(run_resume_batch,), daemon=True).start()

    return {
        "status": "ok",
        "message": f"继续摄入已启动，{len(remaining_paths)} 个文件（跳过 {len(done_files)} 个已完成），{done_concepts} 个概念将从检查点跳过",
        "files": [f.name for f in remaining_paths],
        "checkpoint_concepts": done_concepts,
        "skipped_files": list(done_files),
        "cache_mode": len(done_files) > 0,
    }


@app.get("/api/ingest/checkpoint")
async def get_ingest_checkpoint(
    workspace: str,
    user=Depends(get_current_user),
):
    """获取检查点信息（已处理的概念和文件数）"""
    user_id = user["user_id"]
    cp = get_checkpoint(user_id, workspace)
    done = len(cp.get("done_concepts", []))
    pending = get_pending_concepts(user_id, workspace)
    return {
        "concepts": done,
        "done_concepts": done,
        "pending_concepts": pending,
        "files_done": len(cp.get("files_done", [])),
        "terminated_at": cp.get("terminated_at"),
        "has_checkpoint": pending > 0 or cp.get("terminated_at") is not None,
        "has_shuffle_cache": pending > 0,
    }


@app.post("/api/ingest/clear-checkpoint")
async def clear_ingest_checkpoint(
    workspace: str = Form(...),
    user=Depends(get_current_user),
):
    """清除检查点（下次摄入将从头开始）"""
    user_id = user["user_id"]
    clear_checkpoint(user_id, workspace)
    clear_terminate(user_id, workspace)
    return {"status": "ok", "message": "检查点和终止标记已清除"}


# ==========================================
# 🔍 5. 基础接口 (Workspaces & Graph)
# ==========================================
@app.get("/api/workspaces")
async def get_workspaces(user=Depends(get_current_user)):
    user_id = user["user_id"]

    if USE_MINIO:
        from core.storage import get_storage
        from core.path_resolver import minio_wiki_prefix
        # MinIO 模式：列出 wiki/{user_id}/ 下的所有前缀作为沙箱
        s = get_storage()
        prefix = minio_wiki_prefix(user_id)
        all_keys = s.list_keys(prefix)
        # 从 key 中提取沙箱名（第三级目录）
        workspaces = set()
        for key in all_keys:
            # key 格式: wiki/{user_id}/{workspace}/...
            parts = key.split("/")
            if len(parts) >= 3 and parts[2]:
                workspaces.add(parts[2])
        return sorted(list(workspaces), reverse=True)

    # ── 本地模式 ──
    return list_workspaces(user_id)


@app.get("/api/graph")
async def get_graph(workspace: str, user=Depends(get_current_user)):
    user_id = user["user_id"]

    if USE_MINIO:
        from core.storage import get_storage
        s = get_storage()
        # 1. 列出所有概念文件
        concept_keys = _minio_list_concepts(user_id, workspace)
        if not concept_keys:
            return {"nodes": [], "links": []}

        # 2. 构建节点集合 + 别名索引（支持简称匹配）
        #    过滤掉 DRAFT 标记的文件（未审批，不应出现在星图中）
        DRAFT_TAG = "<!-- AUTOFILL_DRAFT -->"
        nodes = []
        node_set = set()
        _alias_map = {}  # normalized -> canonical (for backend link resolution)
        _aliases = {}    # raw_wikilink_text -> canonical_node_id (for frontend)
        _draft_keys = set()  # 记录 DRAFT 文件，后续跳过
        for key in concept_keys:
            # 跳过 DRAFT 文件（未审批）
            try:
                _content_check = s.read_text(key)
                if DRAFT_TAG in _content_check:
                    _draft_keys.add(key)
                    continue
            except Exception:
                pass
            name = _minio_concept_name(key)
            nodes.append({"id": name, "group": 1})
            node_set.add(name.lower())
            # 注册别名：全名、括号内中文名、括号前英文名
            _norm = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5]', '', name).lower()
            _alias_map[_norm] = name
            _en = re.match(r'^([A-Za-z][A-Za-z0-9 _-]*)', name)
            if _en:
                _en_clean = re.sub(r'[^a-zA-Z0-9]', '', _en.group(1)).lower()
                _alias_map[_en_clean] = name
                _aliases[_en.group(1).strip()] = name  # "BPE" -> "BPE (字节对编码)"
            _zh = re.findall(r'[\u4e00-\u9fa5]{2,}', name)
            for z in _zh:
                _alias_map[z.lower()] = name
                _aliases[z] = name  # "字节对编码" -> "BPE (字节对编码)"

        # 3. 读取每个概念内容，提取 [[链接]] 构建边
        links = []
        _seen_links = set()
        for key in concept_keys:
            if key in _draft_keys:
                continue
            source = _minio_concept_name(key)
            try:
                content = s.read_text(key)
            except Exception:
                continue
            for match in re.findall(r'\[\[(.*?)\]\]', content):
                target = match.split("|")[0].strip()
                if target.lower() == "index":
                    continue
                # 精确匹配 → 别名匹配
                resolved = None
                if target.lower() in node_set:
                    resolved = target
                else:
                    _t_norm = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5]', '', target).lower()
                    if _t_norm in _alias_map:
                        resolved = _alias_map[_t_norm]
                if resolved and resolved != source:
                    _link_key = (source, resolved)
                    if _link_key not in _seen_links:
                        _seen_links.add(_link_key)
                        links.append({"source": source, "target": resolved})

        return {"nodes": nodes, "links": links, "aliases": _aliases}

    # ── 本地模式 ──
    base_dir = get_wiki_root(user_id) / workspace
    concepts_dir = base_dir / "concepts"
    search_dir = concepts_dir if concepts_dir.exists() else base_dir

    if not base_dir.exists():
        return {"nodes": [], "links": []}

    DRAFT_TAG = "<!-- AUTOFILL_DRAFT -->"
    nodes, links, node_set = [], [], set()
    _alias_map = {}  # normalized_alias -> canonical_node_id
    _aliases = {}    # raw_wikilink_text -> canonical_node_id (for frontend)
    _draft_files = set()  # DRAFT 文件 stem 集合
    try:
        for fp in search_dir.rglob("*.md"):
            name = fp.stem
            if name.lower() == "index":
                continue
            # 跳过 DRAFT 文件（未审批）
            try:
                _fc = fp.read_text(encoding="utf-8")
                if DRAFT_TAG in _fc:
                    _draft_files.add(name.lower())
                    continue
            except Exception:
                pass
            nodes.append({"id": name, "group": 1})
            node_set.add(name.lower())
            # 注册别名
            _norm = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5]', '', name).lower()
            _alias_map[_norm] = name
            _en = re.match(r'^([A-Za-z][A-Za-z0-9 _-]*)', name)
            if _en:
                _en_clean = re.sub(r'[^a-zA-Z0-9]', '', _en.group(1)).lower()
                _alias_map[_en_clean] = name
                _aliases[_en.group(1).strip()] = name
            _zh = re.findall(r'[\u4e00-\u9fa5]{2,}', name)
            for z in _zh:
                _alias_map[z.lower()] = name
                _aliases[z] = name

        _seen_links = set()
        for fp in search_dir.rglob("*.md"):
            source = fp.stem
            if source.lower() == "index" or source.lower() in _draft_files:
                continue
            content = fp.read_text(encoding="utf-8")
            for match in re.findall(r'\[\[(.*?)\]\]', content):
                target = match.split("|")[0].strip()
                if target.lower() == "index":
                    continue
                resolved = None
                if target.lower() in node_set:
                    resolved = target
                else:
                    _t_norm = re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5]', '', target).lower()
                    if _t_norm in _alias_map:
                        resolved = _alias_map[_t_norm]
                if resolved and resolved != source:
                    _link_key = (source, resolved)
                    if _link_key not in _seen_links:
                        _seen_links.add(_link_key)
                        links.append({"source": source, "target": resolved})

        return {"nodes": nodes, "links": links, "aliases": _aliases}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# 📖 概念详情 (Concept Detail)
# ==========================================
@app.get("/api/concept")
async def get_concept(workspace: str, name: str, user=Depends(get_current_user)):
    """读取指定概念的 Markdown 文件内容"""
    user_id = user["user_id"]
    if not workspace or not name:
        raise HTTPException(status_code=400, detail="缺少 workspace 或 name 参数")

    if USE_MINIO:
        from core.storage import get_storage
        from core.path_resolver import minio_concept_key, minio_concepts_prefix

        s = get_storage()
        # 1. 精确匹配
        key = minio_concept_key(user_id, workspace, f"{name}.md")
        if s.exists(key):
            content = s.read_text(key)
            return {"content": content, "name": name, "path": f"concepts/{name}.md"}

        # 2. 模糊搜索（在子目录中查找）
        prefix = minio_concepts_prefix(user_id, workspace)
        all_keys = s.list_keys(prefix)
        for k in all_keys:
            if k.endswith(f"/{name}.md"):
                content = s.read_text(k)
                rel_path = k.replace(prefix, "")
                return {"content": content, "name": name, "path": rel_path}

        raise HTTPException(status_code=404, detail=f"概念 [{name}] 不存在于沙箱 [{workspace}]")

    # ── 本地模式 ──
    base_dir = get_wiki_root(user_id) / workspace
    concepts_dir = base_dir / "concepts"

    candidates = []
    exact = concepts_dir / f"{name}.md"
    if exact.exists():
        candidates.append(exact)
    else:
        for fp in concepts_dir.rglob(f"{name}.md"):
            candidates.append(fp)
            break

    if not candidates:
        raise HTTPException(status_code=404, detail=f"概念 [{name}] 不存在于沙箱 [{workspace}]")

    try:
        content = candidates[0].read_text(encoding="utf-8")
        return {"content": content, "name": name, "path": str(candidates[0].relative_to(base_dir))}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==========================================
# 📥 6. 隔离审批区 (Inbox)
# ==========================================
DRAFT_TAG = "<" + "!-- AUTOFILL_DRAFT --" + ">"


@app.get("/api/inbox")
async def get_inbox(workspace: str, user=Depends(get_current_user)):
    if not workspace:
        return []
    user_id = user["user_id"]

    if USE_MINIO:
        from core.storage import get_storage
        s = get_storage()
        concept_keys = _minio_list_concepts(user_id, workspace)
        files = []
        for key in concept_keys:
            try:
                content = s.read_text(key)
            except Exception:
                continue
            if DRAFT_TAG not in content:
                continue
            name = _minio_concept_name(key)
            clean = re.sub(r'<.*?AUTOFILL_DRAFT.*?>', '', content)
            clean = re.sub(r'[#*\[\]\n]', ' ', clean)[:40].strip()
            files.append({
                "id": name,
                "title": name,
                "excerpt": f"{clean}..." if clean else "无正文内容...",
                "timestamp": 0,
            })
        return files[:4]

    # ── 本地模式 ──
    concepts_dir = get_concepts_dir(user_id, workspace)
    if not concepts_dir.exists():
        return []

    files = []
    try:
        for f in concepts_dir.glob("*.md"):
            if f.stem.lower() == "index":
                continue
            content = f.read_text(encoding="utf-8")
            if DRAFT_TAG not in content:
                continue
            stat = f.stat()
            clean = re.sub(r'<.*?AUTOFILL_DRAFT.*?>', '', content)
            clean = re.sub(r'[#*\[\]\n]', ' ', clean)[:40].strip()
            files.append({
                "id": f.stem,
                "title": f.stem,
                "excerpt": f"{clean}..." if clean else "无正文内容...",
                "timestamp": stat.st_mtime,
            })
        files.sort(key=lambda x: x["timestamp"], reverse=True)
        return files[:4]
    except Exception:
        return []


@app.post("/api/inbox/approve")
async def approve_inbox_file(workspace: str, file_id: str, user=Depends(get_current_user)):
    user_id = user["user_id"]

    if USE_MINIO:
        from core.storage import get_storage
        from core.path_resolver import minio_concept_key
        s = get_storage()
        key = minio_concept_key(user_id, workspace, f"{file_id}.md")
        if s.exists(key):
            content = s.read_text(key)
            content = content.replace(DRAFT_TAG + "\n", "").replace(DRAFT_TAG, "")
            s.write_text(key, content)
        return {"status": "success"}

    # ── 本地模式 ──
    filepath = get_concepts_dir(user_id, workspace) / f"{file_id}.md"
    if filepath.exists():
        content = filepath.read_text(encoding="utf-8")
        content = content.replace(DRAFT_TAG + "\n", "").replace(DRAFT_TAG, "")
        filepath.write_text(content, encoding="utf-8")
    return {"status": "success"}


# ==========================================
# 📡 7. 需求雷达 (Radar)
# ==========================================
@app.get("/api/radar")
async def get_radar(workspace: str, user=Depends(get_current_user)):
    if not workspace:
        return []
    user_id = user["user_id"]

    if USE_MINIO:
        from collections import Counter

        from core.storage import get_storage
        s = get_storage()
        concept_keys = _minio_list_concepts(user_id, workspace)
        if not concept_keys:
            return []

        link_counter = Counter()
        existing_names = []
        for key in concept_keys:
            name = _minio_concept_name(key)
            existing_names.append(name)
            try:
                content = s.read_text(key)
            except Exception:
                continue
            for link in re.findall(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', content):
                clean = link.strip()
                if clean:
                    link_counter[clean] += 1

        def _get_real_target(ghost: str, names: list) -> str:
            def _aliases(text: str) -> set:
                a = set()
                c = text.lower().replace("-", "").replace("_", "").replace(" ", "")
                if c:
                    a.add(c)
                m = re.match(r'^(.*?)\s*[\(（](.*?)[\)）]', text)
                if m:
                    for p in [m.group(1), m.group(2)]:
                        p = p.lower().replace("-", "").replace("_", "").replace(" ", "")
                        if p:
                            a.add(p)
                return a
            ga = _aliases(ghost)
            for n in names:
                if ga & _aliases(n):
                    return n
            return ""

        ghosts = []
        for link, count in link_counter.items():
            real = _get_real_target(link, existing_names)
            if not real and link.lower() != "index" and count >= 1:
                ghosts.append((link, count))
        ghosts.sort(key=lambda x: x[1], reverse=True)

        return [
            {"concept": name, "urgency": min(100, count * 12), "mentions": count}
            for name, count in ghosts[:5]
        ]

    # ── 本地模式 ──
    concepts_dir = get_concepts_dir(user_id, workspace)
    if not concepts_dir.exists():
        return []

    from collections import Counter
    existing_files = list(concepts_dir.glob("*.md"))
    link_counter = Counter()

    try:
        for fp in existing_files:
            content = fp.read_text(encoding="utf-8")
            for link in re.findall(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', content):
                clean = link.strip()
                if clean:
                    link_counter[clean] += 1

        def _get_real_target(ghost: str, files: list) -> str:
            def _aliases(text: str) -> set:
                a = set()
                c = text.lower().replace("-", "").replace("_", "").replace(" ", "")
                if c:
                    a.add(c)
                m = re.match(r'^(.*?)\s*[\(（](.*?)[\)）]', text)
                if m:
                    for p in [m.group(1), m.group(2)]:
                        p = p.lower().replace("-", "").replace("_", "").replace(" ", "")
                        if p:
                            a.add(p)
                return a

            ga = _aliases(ghost)
            for f in files:
                if ga & _aliases(f.stem):
                    return f.stem
            return ""

        ghosts = []
        for link, count in link_counter.items():
            real = _get_real_target(link, existing_files)
            if not real and link.lower() != "index" and count >= 1:
                ghosts.append((link, count))
        ghosts.sort(key=lambda x: x[1], reverse=True)

        return [
            {"concept": name, "urgency": min(100, count * 12), "mentions": count}
            for name, count in ghosts[:5]
        ]
    except Exception:
        return []


# ==========================================
# ⚖️ 8. Inbox 物理审批 (CRUD)
# ==========================================
@app.get("/api/inbox/file")
async def get_inbox_file(workspace: str, file_id: str, user=Depends(get_current_user)):
    user_id = user["user_id"]

    if USE_MINIO:
        from core.storage import get_storage
        from core.path_resolver import minio_concept_key
        s = get_storage()
        key = minio_concept_key(user_id, workspace, f"{file_id}.md")
        if not s.exists(key):
            raise HTTPException(status_code=404)
        content = s.read_text(key).replace(DRAFT_TAG + "\n", "")
        return {"content": content}

    # ── 本地模式 ──
    filepath = get_concepts_dir(user_id, workspace) / f"{file_id}.md"
    if not filepath.exists():
        raise HTTPException(status_code=404)
    content = filepath.read_text(encoding="utf-8").replace(DRAFT_TAG + "\n", "")
    return {"content": content}


@app.post("/api/inbox/reject")
async def reject_inbox_file(workspace: str, file_id: str, user=Depends(get_current_user)):
    user_id = user["user_id"]

    if USE_MINIO:
        from core.storage import get_storage
        from core.path_resolver import minio_concept_key
        s = get_storage()
        key = minio_concept_key(user_id, workspace, f"{file_id}.md")
        if s.exists(key):
            s.delete(key)
        return {"status": "success"}

    # ── 本地模式 ──
    filepath = get_concepts_dir(user_id, workspace) / f"{file_id}.md"
    if filepath.exists():
        filepath.unlink()
    return {"status": "success"}


# ==========================================
# 📊 9. 报告生成 (Stage 3)
# ==========================================
@app.post("/api/report")
async def report_endpoint(request: ReportRequest, user=Depends(get_current_user)):
    user_id = user["user_id"]
    if not request.workspace:
        raise HTTPException(status_code=400, detail="必须指定工作区")

    from workflows.report_flow import ReportFlow
    rf = ReportFlow(user_id=user_id)
    session_id = request.session_id or f"{user_id}:{request.workspace}:report"

    return StreamingResponse(
        rf.generate(
            topic=request.topic,
            workspace=request.workspace,
            outline=request.outline or "",
            session_id=session_id,
        ),
        media_type="text/event-stream",
    )


# ==========================================
# 🌐 SPA 前端入口 (Vite 开发代理或静态文件)
# ==========================================
from starlette.responses import FileResponse, RedirectResponse
from starlette.staticfiles import StaticFiles

DIST_DIR = PROJECT_ROOT / "web" / "dist"

if DIST_DIR.exists():
    # 生产模式：挂载静态文件
    app.mount("/assets", StaticFiles(directory=str(DIST_DIR / "assets")), name="static_assets")

    @app.get("/")
    async def spa_index_prod():
        return FileResponse(str(DIST_DIR / "index.html"))

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        """SPA 路由回退"""
        file_path = DIST_DIR / full_path
        if file_path.is_file():
            return FileResponse(str(file_path))
        return FileResponse(str(DIST_DIR / "index.html"))
else:
    @app.get("/")
    async def spa_index_dev():
        return RedirectResponse(url="http://localhost:3000")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8888, workers=4)
