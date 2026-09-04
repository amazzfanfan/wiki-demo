"""
core/llm_factory.py — 统一模型工厂（BYOK 感知，角色可配）

所有 LLM 调用统一走 get_qwen_model(role=...)。
切换提供商只需改 .env 的 DEFAULT_PROVIDER，无需改代码。
"""
import os
import contextvars
from dotenv import load_dotenv
from agno.models.openai.like import OpenAILike

load_dotenv()

# ── 协程级用户上下文（ContextVar：async 安全） ──
# 替代 threading.local()：
#   FastAPI async 端点共享事件循环线程，threading.local 会串号；
#   ContextVar 按协程隔离，每个 HTTP 请求有独立副本。
_var_user_id = contextvars.ContextVar("llm_user_id", default="")
_var_role = contextvars.ContextVar("llm_role", default="user")


def set_user_context(user_id: str = "", role: str = "user"):
    """在请求入口设置当前协程的用户 ID 和角色"""
    _var_user_id.set(user_id)
    _var_role.set(role)


def get_user_context() -> str:
    """获取当前协程的用户 ID"""
    return _var_user_id.get()


def get_user_role() -> str:
    """获取当前协程的用户角色"""
    return _var_role.get()


def _make_model(model_id: str, api_key: str, base_url: str) -> OpenAILike:
    return OpenAILike(
        id=model_id,
        api_key=api_key,
        base_url=base_url,
        role_map={"system": "system", "user": "user", "assistant": "assistant", "tool": "tool"},
    )


# ── 提供商配置表 ──
# 新增提供商：在此加一项即可，所有角色自动可用
_PROVIDERS = {
    "qwen": {
        "key_env": "QWEN_API_KEY",
        "url_env": "QWEN_BASE_URL",
        "url_default": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model_env": "QWEN_MODEL_ID",
        "model_default": "deepseek-v4-pro",
    },
    "dsv4pro": {
        "key_env": "DSV4PRO_API_KEY",
        "url_env": "DSV4PRO_BASE_URL",
        "url_default": "http://your-internal-llm-service:30000",
        "model_env": "DSV4PRO_MODEL_ID",
        "model_default": "/your/model/path",
    },
    "glm": {
        "key_env": "GLM_API_KEY",
        "url_env": "GLM_BASE_URL",
        "url_default": "http://your-internal-llm-service:30000",
        "model_env": "GLM_MODEL_ID",
        "model_default": "/your/model/path",
    },
}

# ── 角色 → 环境变量覆盖 ──
# 设置 MAP_MODEL_ID=xxx 可单独覆盖 MAP 用的模型，不设置则用全局默认
_ROLE_ENV_MAP = {
    "map": "MAP_MODEL_ID",
    "editor": "EDITOR_MODEL_ID",
    "schema": "SCHEMA_MODEL_ID",
    "schema_suggest": "SCHEMA_SUGGEST_MODEL_ID",
    "query": "QUERY_MODEL_ID",
    "research": "RESEARCH_MODEL_ID",
}


def _resolve_model_for_role(role=None):
    """根据 role 查环境变量覆盖，返回 (model_id, provider_hint) 或 (None, None)"""
    if role and role in _ROLE_ENV_MAP:
        env_key = _ROLE_ENV_MAP[role]
        mid = os.environ.get(env_key, "").strip()
        if mid:
            # 从 model_id 推测 provider（含 glm 走 glm，否则走默认）
            provider = "glm" if "glm" in mid.lower() else None
            return mid, provider
    return None, None


def _get_system_model(model_id=None, role=None):
    """系统默认模型选择。

    回退链：
    1. 角色指定的模型（{ROLE}_MODEL_ID 环境变量）
    2. DEFAULT_PROVIDER 指定的提供商
    3. 自动选择第一个有 key 的提供商
    4. 报错
    """
    # 1. 角色覆盖
    role_mid, role_provider = _resolve_model_for_role(role)
    if role_mid and role_provider:
        cfg = _PROVIDERS.get(role_provider)
        if cfg:
            key = os.getenv(cfg["key_env"], "")
            if key:
                return _make_model(role_mid, key, os.getenv(cfg["url_env"], cfg["url_default"]))

    # 如果角色指定了 model_id 但没有对应 provider key，用 model_id 但走默认 provider
    effective_model_id = role_mid or model_id

    # 2. DEFAULT_PROVIDER
    default_provider = os.environ.get("DEFAULT_PROVIDER", "").lower().strip()
    if default_provider and default_provider in _PROVIDERS:
        cfg = _PROVIDERS[default_provider]
        key = os.getenv(cfg["key_env"], "")
        if key:
            return _make_model(
                effective_model_id or os.getenv(cfg["model_env"], cfg["model_default"]),
                key,
                os.getenv(cfg["url_env"], cfg["url_default"]),
            )

    # 3. 自动选择第一个有 key 的
    for name, cfg in _PROVIDERS.items():
        key = os.getenv(cfg["key_env"], "")
        if key:
            return _make_model(
                effective_model_id or os.getenv(cfg["model_env"], cfg["model_default"]),
                key,
                os.getenv(cfg["url_env"], cfg["url_default"]),
            )

    # 4. 全都没有
    raise ValueError(
        "⚠️ 没有可用的模型 API！\n\n"
        "👉 请点击右上角 ⚙️ **设置** → 选择模型厂商 → 输入你的 API Key\n"
        "或在 .env 中配置 DEFAULT_PROVIDER 和对应的 API Key。"
    )


def get_qwen_model(model_id=None, role=None):
    """
    获取 LLM 模型实例（统一入口）。

    优先级：
    1. 用户自己配的 API Key（BYOK，前端设置页）
    2. 角色覆盖（{ROLE}_MODEL_ID 环境变量）
    3. DEFAULT_PROVIDER 指定的提供商
    4. 自动选择第一个有 key 的提供商
    5. 都没有 → 提示用户配置

    切换全局提供商：改 .env 的 DEFAULT_PROVIDER（qwen/dsv4pro/glm）
    切换单个角色：设 MAP_MODEL_ID / EDITOR_MODEL_ID / SCHEMA_MODEL_ID 等
    """
    user_id = get_user_context()
    ctx_role = get_user_role()

    if user_id:
        try:
            from core.model_router import get_model_for_user
            model = get_model_for_user(user_id=user_id)
            # BYOK 用户也尊重角色覆盖的 model_id
            if model_id:
                model.id = model_id
            elif role:
                role_mid, _ = _resolve_model_for_role(role)
                if role_mid:
                    model.id = role_mid
            return model
        except Exception:
            # 用户没配 Key，回退到系统默认
            pass

    try:
        return _get_system_model(model_id=model_id, role=role)
    except Exception:
        raise ValueError(
            "系统默认模型不可用（可能超时或未配置），请自行配置 API Key。\n\n"
            "👉 点击右上角 ⚙️ **设置** → 选择模型厂商 → 输入你的 API Key 即可使用。"
        )
