"""
core/auth.py — JWT 认证 + 用户注册登录 + bcrypt 密码哈希
"""
import os
import json
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import jwt
import bcrypt
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel

# ==========================================
# 🔑 JWT Secret 管理
# ==========================================
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SECRET_FILE = _PROJECT_ROOT / ".jwt_secret"

ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24 * 7  # 7 天


def _load_or_create_secret() -> str:
    """从 .jwt_secret 文件加载密钥，不存在则自动生成"""
    if _SECRET_FILE.exists():
        secret = _SECRET_FILE.read_text(encoding="utf-8").strip()
        if secret:
            return secret

    # 自动生成
    secret = secrets.token_hex(32)
    _SECRET_FILE.write_text(secret, encoding="utf-8")
    print(f"🔑 已自动生成 JWT Secret 并写入 {_SECRET_FILE}")
    return secret


JWT_SECRET = _load_or_create_secret()

# ==========================================
# 🗄️ 用户数据库 (SQLite，与 memory.db 分开)
# ==========================================
_USERS_DB = _PROJECT_ROOT / "data" / "users.db"


def _get_users_db() -> sqlite3.Connection:
    """获取用户数据库连接（自动建表）"""
    _USERS_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_USERS_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT UNIQUE NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            api_keys TEXT DEFAULT '{}',
            role TEXT NOT NULL DEFAULT 'user'
        )
    """)
    # 兼容旧表：如果 role 列不存在则添加
    try:
        conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")
        conn.commit()
    except Exception:
        pass  # 列已存在
    conn.commit()
    return conn


# ==========================================
# 🔐 密码哈希
# ==========================================
def hash_password(password: str) -> str:
    """bcrypt 哈希密码"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """验证明文密码 vs bcrypt 哈希"""
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


# ==========================================
# 🎫 JWT Token 签发 / 校验
# ==========================================
def create_token(user_id: str, username: str, role: str = "user") -> str:
    """签发 JWT Token"""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "username": username,
        "role": role,
        "iat": now,
        "exp": now + timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """解码 JWT Token，失败抛异常"""
    return jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])


# ==========================================
# 👤 用户注册 / 登录
# ==========================================
class AuthRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    token: str
    user_id: str
    username: str
    role: str = "user"


def _get_allowed_users() -> list[str] | None:
    """从环境变量加载注册白名单，返回 None 表示不限制"""
    raw = os.getenv("ALLOWED_USERS", "").strip()
    if not raw:
        return None  # 未设置 = 不限制
    return [u.strip().lower() for u in raw.split(",") if u.strip()]


def register_user(username: str, password: str) -> AuthResponse:
    """注册新用户"""
    if not username or not username.strip():
        raise ValueError("用户名不能为空")
    if not password or len(password) < 4:
        raise ValueError("密码至少 4 位")

    username = username.strip()
    user_id = username.lower().replace(" ", "_")

    # 白名单检查
    allowed = _get_allowed_users()
    if allowed is not None and user_id not in allowed:
        raise ValueError("当前仅允许白名单用户注册，请联系管理员添加账号")

    conn = _get_users_db()
    try:
        # 检查用户名是否已存在
        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            raise ValueError(f"用户名 '{username}' 已被注册")

        pw_hash = hash_password(password)
        
        conn.execute(
            "INSERT INTO users (user_id, username, password_hash) VALUES (?, ?, ?)",
            (user_id, username, pw_hash)
        )
        conn.commit()

        # 确保用户目录存在
        from core.path_resolver import ensure_user_dirs
        ensure_user_dirs(user_id)

        token = create_token(user_id, username, role="user")
        return AuthResponse(token=token, user_id=user_id, username=username, role="user")
    finally:
        conn.close()


def login_user(username: str, password: str) -> AuthResponse:
    """用户登录"""
    username = username.strip()
    conn = _get_users_db()
    try:
        row = conn.execute(
            "SELECT user_id, username, password_hash, role FROM users WHERE username = ?",
            (username,)
        ).fetchone()

        if not row:
            raise ValueError("用户名或密码错误")

        if not verify_password(password, row["password_hash"]):
            raise ValueError("用户名或密码错误")

        user_id = row["user_id"]
        uname = row["username"]
        role = row["role"] if "role" in row.keys() else "user"

        # 确保用户目录存在
        from core.path_resolver import ensure_user_dirs
        ensure_user_dirs(user_id)

        token = create_token(user_id, uname, role=role)
        return AuthResponse(token=token, user_id=user_id, username=uname, role=role)
    finally:
        conn.close()


# ==========================================
# 🛡️ FastAPI 依赖注入：JWT 认证
# ==========================================
_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> dict:
    """
    FastAPI 依赖：从 Authorization header 提取当前用户。
    支持 ?token= query 参数作为 fallback（用于 SSE/EventSource）。
    返回 {"user_id": str, "username": str}
    """
    token = None
    if credentials:
        token = credentials.credentials
    else:
        # Fallback: 从 query 参数获取 token（SSE/EventSource 不支持自定义 header）
        token = request.query_params.get("token")

    if not token:
        raise HTTPException(status_code=401, detail="未提供认证令牌")

    try:
        payload = decode_token(token)
        return {
            "user_id": payload["sub"],
            "username": payload.get("username", payload["sub"]),
            "role": payload.get("role", "user"),
        }
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="令牌已过期，请重新登录")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效的认证令牌")


async def get_admin_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> dict:
    """FastAPI 依赖：必须是 admin 角色"""
    user = await get_current_user(request, credentials)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="仅管理员可访问")
    return user


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Optional[dict]:
    """
    可选认证：有 token 就解析，没有就返回 None。
    用于向后兼容未登录的旧版调用。
    """
    if not credentials:
        return None
    try:
        payload = decode_token(credentials.credentials)
        return {
            "user_id": payload["sub"],
            "username": payload.get("username", payload["sub"]),
        }
    except Exception:
        return None


# ==========================================
# 🔑 用户级 API Key 管理
# ==========================================
def save_user_api_key(user_id: str, provider: str, api_key: str, base_url: str = "", model_id: str = "") -> bool:
    """保存用户的 API Key 配置"""
    import json
    conn = _get_users_db()
    try:
        row = conn.execute(
            "SELECT api_keys FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if not row:
            return False

        keys = json.loads(row["api_keys"] or "{}")
        keys[provider] = {
            "api_key": api_key,
            "base_url": base_url,
            "model_id": model_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        conn.execute(
            "UPDATE users SET api_keys = ? WHERE user_id = ?",
            (json.dumps(keys, ensure_ascii=False), user_id)
        )
        conn.commit()
        return True
    finally:
        conn.close()


def get_user_api_key(user_id: str, provider: str) -> Optional[dict]:
    """获取用户指定 provider 的 API Key 配置"""
    import json
    conn = _get_users_db()
    try:
        row = conn.execute(
            "SELECT api_keys FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if not row:
            return None
        keys = json.loads(row["api_keys"] or "{}")
        return keys.get(provider)
    finally:
        conn.close()


def delete_user_api_key(user_id: str, provider: str) -> bool:
    """删除用户指定 provider 的 API Key 配置，回退到系统默认"""
    import json
    conn = _get_users_db()
    try:
        row = conn.execute(
            "SELECT api_keys FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if not row:
            return False
        keys = json.loads(row["api_keys"] or "{}")
        if provider in keys:
            del keys[provider]
            conn.execute(
                "UPDATE users SET api_keys = ? WHERE user_id = ?",
                (json.dumps(keys, ensure_ascii=False), user_id)
            )
            conn.commit()
        return True
    finally:
        conn.close()


def get_user_api_keys(user_id: str) -> dict:
    """获取用户所有 API Key 配置（隐藏实际 key）"""
    import json
    conn = _get_users_db()
    try:
        row = conn.execute(
            "SELECT api_keys FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if not row:
            return {}
        keys = json.loads(row["api_keys"] or "{}")
        # 隐藏实际 API Key，只显示前8位
        safe_keys = {}
        for provider, config in keys.items():
            safe_config = dict(config)
            if "api_key" in safe_config:
                k = safe_config["api_key"]
                safe_config["api_key_preview"] = k[:8] + "..." if len(k) > 8 else "***"
                del safe_config["api_key"]
            safe_keys[provider] = safe_config
        return safe_keys
    finally:
        conn.close()
