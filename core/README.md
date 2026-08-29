# core/ — 核心基座层

全局基础设施，所有其他模块共享的底层能力。

## 文件说明

| 文件 | 职责 |
|------|------|
| `config.py` | Pydantic `Settings`，读取 `.env` 文件，提供全局单例配置。 |
| `llm_factory.py` | 模型工厂：通过 `OpenAILike` + DashScope 兼容 API 创建 Qwen-Max 实例。 |
| `auth.py` | **JWT 认证系统**：用户注册/登录、Token 签发与验证、白名单控制（`ALLOWED_USERS`）、管理员角色（`get_admin_user` 依赖注入）、密码 bcrypt 哈希。 |
| `model_router.py` | **多供应商 LLM 路由**：支持用户自带 API Key（BYOK），选择不同 LLM 提供商（Qwen / OpenAI / DeepSeek 等），运行时动态切换模型。 |
| `path_resolver.py` | **统一路径解析器**：所有 `data/wiki/` 和 `data/raw/` 路径的唯一入口。实现用户级物理隔离，路径结构 `data/wiki/{user_id}/{workspace}/`。 |
| `task_log.py` | **任务日志系统**：按 `(user_id, workspace)` 隔离的内存环形缓冲区（2000 行），`TaskOutputCapture` 上下文管理器重定向 stdout，支持 SSE 实时流推送。 |

## 架构关系

```
auth.py ──JWT Token──▶ app.py (每个请求验证身份)
    │                       │
    │                  path_resolver.py ──▶ data/wiki/{user_id}/{workspace}/
    │                       │
model_router.py ──▶ llm_factory.py ──▶ Agent 实例
    │
task_log.py ◀── ingest/lint/autofill (stdout 重定向)
    │
    └──▶ /api/admin/task-logs (SSE 推送)
```

## 设计原则

1. **用户隔离**：`path_resolver.py` 确保每个用户只能访问自己的 `data/wiki/{user_id}/` 目录
2. **认证前置**：所有 API 端点通过 `Depends(get_current_user)` 强制鉴权
3. **并发安全**：`task_log.py` 使用线程安全的环形缓冲区，`edit_tools.py` 使用 `threading.local()` 传递上下文（替代旧版 `os.environ` 方案）
4. **配置集中化**：API Key、模型选择、白名单全在 `.env` + `config.py`

## 扩展指引

- **新增 LLM 供应商**：在 `model_router.py` 的供应商注册表中添加条目
- **修改认证策略**：编辑 `auth.py`（如接入 OAuth、LDAP）
- **新增全局配置**：在 `config.py` 的 `Settings` 类中新增字段
