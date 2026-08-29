"""
core/path_resolver.py — 统一路径解析器（用户级隔离）
所有 data/wiki/ 和 data/raw/ 路径必须通过此模块获取。
"""
from pathlib import Path
import os

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass  # python-dotenv 未安装，依赖系统环境变量或 IDE 注入

USE_MINIO = os.environ.get("USE_MINIO", "false").lower() == "true"

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_data_root() -> Path:
    """项目数据根目录"""
    return PROJECT_ROOT / "data"


def get_wiki_root(user_id: str = "") -> Path:
    """
    获取 wiki 根目录。
    - user_id 为空时返回 data/wiki（向后兼容 / 全局操作）
    - user_id 非空时返回 data/wiki/{user_id}
    """
    base = get_data_root() / "wiki"
    if user_id:
        return base / user_id
    return base


def get_raw_root(user_id: str = "") -> Path:
    """
    获取 raw 文件根目录。
    - user_id 为空时返回 data/raw（向后兼容）
    - user_id 非空时返回 data/raw/{user_id}
    """
    base = get_data_root() / "raw"
    if user_id:
        return base / user_id
    return base


def get_concepts_dir(user_id: str, workspace: str) -> Path:
    """获取指定用户 + 沙箱的 concepts 目录"""
    return get_wiki_root(user_id) / workspace / "concepts"


def get_index_path(user_id: str, workspace: str) -> Path:
    """获取指定用户 + 沙箱的 index.md 路径"""
    return get_wiki_root(user_id) / workspace / "index.md"


def get_memory_db_path() -> Path:
    """SQLite 会话记忆数据库路径"""
    return get_data_root() / "memory.db"


def ensure_user_dirs(user_id: str):
    """确保用户级目录结构存在"""
    if not user_id:
        return
    wiki_root = get_wiki_root(user_id)
    raw_root = get_raw_root(user_id)
    wiki_root.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)


def list_workspaces(user_id: str = "") -> list:
    """列出指定用户的所有沙箱名称（按 mtime 倒序）"""
    wiki_root = get_wiki_root(user_id)
    if not wiki_root.exists():
        return []
    try:
        # 一次性消费 iterdir() 生成器，防止并发创建目录时 RuntimeError
        entries = list(wiki_root.iterdir())
        workspaces = [d for d in entries if d.is_dir()]
        workspaces.sort(key=lambda d: d.stat().st_mtime, reverse=True)
        return [w.name for w in workspaces]
    except (OSError, RuntimeError):
        # 目录不存在或并发冲突时安全返回
        return []


def get_default_workspace(user_id: str = "") -> str:
    """自动选取默认工作区（最新修改的那个）"""
    all_ws = list_workspaces(user_id)
    return all_ws[0] if all_ws else ""

# ═══════════════════════════════════════════
# MinIO 对象 Key 路径
# ═══════════════════════════════════════════

def minio_wiki_prefix(user_id: str = "", workspace: str = "") -> str:
    parts = ["wiki"]
    if user_id:
        parts.append(user_id)
    if workspace:
        parts.append(workspace)
    return "/".join(parts) + "/"

def minio_raw_prefix(user_id: str = "", workspace: str = "") -> str:
    parts = ["raw"]
    if user_id:
        parts.append(user_id)
    if workspace:
        parts.append(workspace)
    return "/".join(parts) + "/"

def minio_concepts_prefix(user_id: str, workspace: str) -> str:
    return minio_wiki_prefix(user_id, workspace) + "concepts/"

def minio_index_key(user_id: str, workspace: str) -> str:
    return minio_wiki_prefix(user_id, workspace) + "index.md"

def minio_concept_key(user_id: str, workspace: str, file_name: str) -> str:
    return minio_wiki_prefix(user_id, workspace) + "concepts/" + file_name

# ═══════════════════════════════════════════
# Schema 层（领域自适应，可插拔）
# ═══════════════════════════════════════════

def minio_schema_key(user_id: str, workspace: str) -> str:
    """领域编译指南 (Schema) 的 MinIO key"""
    return minio_wiki_prefix(user_id, workspace) + "schema.md"

def minio_log_key(user_id: str, workspace: str) -> str:
    """活动日志 (log.md) 的 MinIO key"""
    return minio_wiki_prefix(user_id, workspace) + "log.md"

def minio_suggestions_key(user_id: str, workspace: str) -> str:
    """Schema 演化建议 (schema_suggestions.md) 的 MinIO key"""
    return minio_wiki_prefix(user_id, workspace) + "schema_suggestions.md"

def get_schema_path(user_id: str, workspace: str) -> Path:
    """Schema 本地路径"""
    return get_wiki_root(user_id) / workspace / "schema.md"

def get_log_path(user_id: str, workspace: str) -> Path:
    """活动日志本地路径"""
    return get_wiki_root(user_id) / workspace / "log.md"

def get_suggestions_path(user_id: str, workspace: str) -> Path:
    """Schema 建议本地路径"""
    return get_wiki_root(user_id) / workspace / "schema_suggestions.md"
