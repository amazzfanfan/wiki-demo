# Agents — 多智能体系统

基于 **Agno** 框架的多智能体 Wiki 知识库构建系统。每个 Agent 各司其职，通过结构化中间产物（Pydantic Reports）协作，实现知识摄取、分析、融合的自动化流水线。

## Agent 一览

| Agent | 模型 | 工具 | 职责 | 状态 |
|---|---|---|---|---|
| `web_researcher.py` | Qwen-Max (`get_qwen_model()`) | DuckDuckGo + Newspaper4k | 全网深度搜索与网页内容抓取 | ✅ |
| `local_wiki.py` | Qwen-Max (`get_qwen_model()`) | LanceDB 知识库 (Knowledge) | 本地知识库只读查询 | ✅ |
| `wiki_analyst.py` | Qwen-Max | 无（纯文本分析） | **只读分析**：侦察兵，从资料提取概念+摘要，输出 `AnalysisReport` | ✅ |
| `wiki_writer.py` | 无（纯执行器） | `edit_tools` | **只写执行**：接收 Report，执行 create/edit/append_link | ✅ |
| `wiki_editor.py` | Qwen-Max | 无（纯决策） | **主编**：比对新旧知识，输出 `EditorReport` 融合动作 | ✅ |
| `wiki_query.py` | Qwen-Max | 无（纯决策） | **查询路由器**：`WikiRouter` 决定本地概念命中 + 模糊搜索 + 是否需要联网 | ✅ |
| `ppt_maker.py` | — | `ppt_tools` | PPT 生成 | 🔧 WIP |
| `vision_analyst.py` | — | `vision_tools` | 视觉分析 | 🔧 WIP |

## 核心架构：两步思维链 (Two-Step CoT)

```
wiki_analyst (只读分析) ──AnalysisReport──▶ wiki_writer (只写执行)
        │                                      │
   分析新资料                              操作磁盘文件
   提取概念+摘要                           create_page / str_replace
   输出 AnalysisReport                     append_link
```

**为什么分两步？**
1. **分析阶段**（`wiki_analyst`）：纯文本推理，不碰磁盘。专注理解资料、提取概念、建立关联。
2. **执行阶段**（`wiki_writer`）：纯 Python 执行器，不做分析。接收 `AnalysisReport` / `EditorReport` 后直接调用 `edit_tools` 操作文件系统。

## 分析师-主编-撰稿人 三级流水线

完整的知识摄取链路：

```
新资料 ──▶ wiki_analyst ──▶ AnalysisReport ──▶ wiki_editor ──▶ EditorReport ──▶ wiki_writer ──▶ Wiki Pages
```

1. **分析师**（`wiki_analyst`）：从新资料提取概念与摘要，输出 `AnalysisReport`（不碰磁盘）
2. **主编**（`wiki_editor`）：调用 `local_wiki` 检索已有知识，对比新旧内容，生成精确的 `EditorReport` 融合动作（create / edit / append_link）
3. **撰稿人**（`wiki_writer`）：执行 `EditorReport` 中的操作，含同义词防撞雷达和活路径解析

**分层设计原则**：

| 层 | 职责 | Agent | 特征 |
|---|---|---|---|
| **数据层** | 获取原始资料 | `web_researcher`, `local_wiki` | 外部输入 |
| **分析层** | 提取结构化知识 | `wiki_analyst` | 只读不写，输出 `AnalysisReport` |
| **决策层** | 融合新旧知识 | `wiki_editor` | 只读决策，输出 `EditorReport` + `Action` |
| **执行层** | 持久化到磁盘 | `wiki_writer` | 只写不分析，纯执行器 |

## 查询路由器 (wiki_query.py)

`WikiRouter` 是查询链路的决策 Agent，输出 `RouteDecision`：

```python
class RouteDecision(BaseModel):
    local_concepts: List[str]   # 精确命中的 [[概念名称]] 列表
    fuzzy_keywords: List[str]   # 同义词/缩写/核心术语（扩大搜索面）
    needs_web_search: bool      # 是否需要联网搜索
    search_query: str           # 外部搜索的精准查询词
```

## Prompt 内联机制

所有 Agent 的 `instructions` 字符串直接内联在各自的 `.py` 文件中，**不再依赖 `prompts/` 目录**。

```python
# 示例：wiki_analyst.py 内联 instructions
class WikiAnalyst(Agent):
    instructions = """你是一个知识库侦察兵..."""
```

`protocols/` 下的协议文件（`purpose.md` / `schema.md`）作为知识库规范的独立维护层，Agent 运行时按需读取参考。

## 关键文件

| 路径 | 说明 |
|---|---|
| `core/llm_factory.py` | 模型工厂，`get_qwen_model()` 统一提供 LLM 实例 |
| `tools/edit_tools.py` | Wiki 页面编辑工具集（含 `_resolve` 活路径解析 + `threading.local()` 上下文） |
| `tools/document_parser.py` | 文档解析与分块（pdfplumber `extract_text` / `chunk_text`） |
| `tools/search_tools.py` | 搜索工具集 |

## 核心数据结构

### `AnalysisReport`（分析师输出）
```python
class AnalysisReport(BaseModel):
    new_concepts: List[str]    # 核心概念列表（强制双语：英文名 (中文)）
    summary: str               # 约50-100字内容摘要
```

### `EditorReport`（主编输出）
```python
class Action(BaseModel):
    type: Literal["create", "edit", "append_link"]
    file: str
    title / tags / abstract / old_str / content / link_to / rationale

class EditorReport(BaseModel):
    actions: List[Action]
```

> **设计哲学**：让每个 Agent 做好一件事，通过结构化的中间产物传递信息，而非直接操作共享状态。分析与执行分离，决策与写入分离。
