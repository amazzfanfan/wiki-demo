"""
core/model_router.py — 多模型提供商动态路由
支持用户自定义 API Key + 多厂商切换。
"""
import os
from typing import Optional
from dotenv import load_dotenv
from agno.models.openai.like import OpenAILike

load_dotenv()

# ==========================================
# 📋 预置模型提供商配置
# ==========================================
PRESET_PROVIDERS = {
    "qwen": {
        "name": "通义千问 (Qwen)",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model_id": "deepseek-v4-pro",
        "env_key": "QWEN_API_KEY",
    },
    "openai": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model_id": "gpt-4o-mini",
        "env_key": "OPENAI_API_KEY",
    },
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model_id": "deepseek-chat",
        "env_key": "DEEPSEEK_API_KEY",
    },
    "siliconflow": {
        "name": "SiliconFlow (硅基流动)",
        "base_url": "https://api.siliconflow.cn/v1",
        "model_id": "deepseek-ai/DeepSeek-V3",
        "env_key": "SILICONFLOW_API_KEY",
    },
    "glm52": {
        "name": "GLM 5.2 (智谱 · 公司部署)",
        "base_url": "http://10.180.1.202:30000/v1",
        "model_id": "/models/GLM-5.2-W4A8",
        "env_key": "GLM_API_KEY",
    },
    "dsv4pro_internal": {
        "name": "DeepSeek V4 Pro (公司部署)",
        "base_url": "http://10.180.1.206:30000/v1",
        "model_id": "deepseek-v4-pro",
        "env_key": "DSV4PRO_API_KEY",
    },
    "custom": {
        "name": "自定义 (OpenAI 兼容)",
        "base_url": "",
        "model_id": "",
        "env_key": "",
    },
}


def get_model_for_user(user_id: Optional[str] = None, provider: str = "") -> OpenAILike:
    """
    获取用户级 LLM 模型实例。

    优先级：
    1. 用户自定义 API Key（存储在 users.db）
    2. 系统默认 .env 配置

    Args:
        user_id: 用户 ID，None 时回退到系统默认
        provider: 指定提供商，空字符串时自动选择
    """
    # 尝试从用户配置获取
    if user_id:
        from core.auth import get_user_api_key

        # 如果没指定 provider，先尝试用户的默认 provider
        if not provider:
            user_keys = _get_user_default_provider(user_id)
            if user_keys:
                return _create_model(
                    api_key=user_keys["api_key"],
                    base_url=user_keys.get("base_url", ""),
                    model_id=user_keys.get("model_id", ""),
                )

        # 指定了 provider
        if provider:
            user_config = get_user_api_key(user_id, provider)
            if user_config:
                return _create_model(
                    api_key=user_config["api_key"],
                    base_url=user_config.get("base_url", ""),
                    model_id=user_config.get("model_id", ""),
                )

        # 用户没有任何 API Key → 抛错，由 llm_factory 决定是否回退
        raise ValueError(f"用户 {user_id} 未配置任何 API Key")

    # 无 user_id 时才回退到系统默认
    return get_default_model()


def _get_user_default_provider(user_id: str) -> Optional[dict]:
    """获取用户的第一个可用 API Key 配置"""
    from core.auth import get_user_api_keys
    import json

    # 获取完整 keys（需要直接查 DB 获取 api_key）
    from core.auth import _get_users_db
    conn = _get_users_db()
    try:
        row = conn.execute(
            "SELECT api_keys FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if not row:
            return None
        keys = json.loads(row["api_keys"] or "{}")
        # 返回第一个有效的
        for provider, config in keys.items():
            if config.get("api_key"):
                return config
        return None
    finally:
        conn.close()


def get_default_model() -> OpenAILike:
    """获取系统默认模型：公司预置 GLM 5.2 → DSV4Pro → 报错"""
    glm_key = os.getenv("GLM_API_KEY")
    if glm_key:
        return OpenAILike(
            id=os.getenv("GLM_MODEL_ID", "/models/GLM-5.2-W4A8"),
            api_key=glm_key,
            base_url=os.getenv("GLM_BASE_URL", "http://10.180.1.202:30000/v1"),
            role_map={"system": "system", "user": "user", "assistant": "assistant", "tool": "tool"},
        )
    ds_key = os.getenv("DSV4PRO_API_KEY")
    if ds_key:
        return OpenAILike(
            id="deepseek-v4-pro",
            api_key=ds_key,
            base_url=os.getenv("DSV4PRO_BASE_URL", "http://10.180.1.206:30000/v1"),
            role_map={"system": "system", "user": "user", "assistant": "assistant", "tool": "tool"},
        )
    raise ValueError("⚠️ 未找到任何模型 API Key，请检查 .env 或配置自定义 API Key！")


def _create_model(api_key: str, base_url: str, model_id: str) -> OpenAILike:
    """根据参数创建 OpenAI 兼容模型实例"""
    # 查找匹配的 preset 以获取默认值
    for p_name, p_config in PRESET_PROVIDERS.items():
        if base_url and p_config["base_url"] and base_url.startswith(p_config["base_url"][:30]):
            if not model_id:
                model_id = p_config["model_id"]
            break

    if not base_url:
        base_url = os.getenv("DSV4PRO_BASE_URL", "http://10.180.1.206:30000/v1")
    if not model_id:
        model_id = "deepseek-v4-pro"

    return OpenAILike(
        id=model_id,
        api_key=api_key,
        base_url=base_url,
        role_map={"system": "system", "user": "user", "assistant": "assistant", "tool": "tool"},
    )


def list_providers() -> list:
    """列出所有可用的模型提供商"""
    result = []
    for key, config in PRESET_PROVIDERS.items():
        result.append({
            "id": key,
            "name": config["name"],
            "base_url": config["base_url"],
            "default_model": config["model_id"],
            "has_env_key": bool(os.getenv(config["env_key"])) if config["env_key"] else False,
        })
    return result
