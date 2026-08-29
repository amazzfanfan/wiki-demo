"""
core/schema_engine.py — 领域自适应 Schema 引擎（可插拔）

所有 Schema 相关逻辑集中在此模块。
通过 ENABLE_SCHEMA 环境变量控制开关：
  - false（默认）：所有函数返回空/跳过，零开销
  - true：启用 Schema 注入、Phase 0 嗅探、log.md、建议生成

设计原则：
  - 这是 Wiki，不是知识图谱
  - 判断信息（importance/novelty/conflicts/directions）是中间产物
  - 它们指导 Editor 生成更丰富的页面，但不会变成 frontmatter 字段
"""
import os
import datetime
import json

try:
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

ENABLE_SCHEMA = os.environ.get("ENABLE_SCHEMA", "false").lower() == "true"


def is_enabled() -> bool:
    """Schema 功能是否启用"""
    return ENABLE_SCHEMA


# ═══════════════════════════════════════════
# Phase 0: 领域画像嗅探
# ═══════════════════════════════════════════

PHASE0_PROMPT = """你是一个领域知识分析专家。请分析以下文本片段，推断这个领域的知识应该怎么组织。

你的任务不是列出类型，而是生成一份"编译指南"——告诉后续的知识提取系统：
这个领域的知识，怎么组织才算"懂"了？

请输出以下部分（用 Markdown 格式）：

# Schema — {沙箱名称}

> 这是本沙箱的知识编译指南。最后更新：{日期}

## 核心维度

这个领域最重要的判断维度是什么？（1-2 句）

## 什么算重要

- 核心突破：{{定义}}
- 关键支撑：{{定义}}
- 背景知识：{{定义}}
- 可以忽略：{{定义}}

## 命名惯例

- {{2-3 条}}

## 页面风格约定

- {{2-3 条}}

## 交叉引用优先级

什么样的 [[wikilink]] 最有价值？按重要性排序。

1. {{最高优先级的链接类型}}
2. {{次优先级}}
3. {{第三优先级}}

## 待深入方向

- {{当前知识库可能缺少的方向}}

注意：
- 不要列类型清单，要给出组织知识的指导原则
- 从内容语境推断，不要硬套通用分类
- 用中文输出

---

以下是文档片段：

{chunk_1}

---

{chunk_2}
"""


def build_phase0_prompt(workspace_name: str, sample_chunks: list) -> str:
    """构建 Phase 0 嗅探 prompt"""
    chunk_1 = sample_chunks[0][:2000] if len(sample_chunks) > 0 else "(无样本)"
    chunk_2 = sample_chunks[1][:2000] if len(sample_chunks) > 1 else chunk_1
    today = datetime.date.today().isoformat()
    return PHASE0_PROMPT.format(
        沙箱名称=workspace_name,
        日期=today,
        chunk_1=chunk_1,
        chunk_2=chunk_2,
    )


# ═══════════════════════════════════════════
# Analyst Prompt 注入
# ═══════════════════════════════════════════

ANALYST_SCHEMA_INJECTION = """

## 领域编译指南（Schema）

{schema_content}

如果上述 Schema 为空或不适用，请使用你的通用判断力。

## 判断维度（额外要求）

除了提取概念名，还需对每个概念标注：
- importance: "核心突破" / "关键支撑" / "背景知识" / "可忽略"（参考 Schema 中的定义）
- novelty: "全新概念" / "增量补充" / "已知重申"

同时标注：
- conflicts: 与已有知识库中具体页面/概念的矛盾（必须指出是哪个页面或哪个概念，不能泛泛而谈）
- gaps: 知识库中存在的具体缺口（已有 X 但缺少 Y，不是泛泛的"研究方向"）

请在输出 JSON 中包含以下额外字段：
"entries": [
  {{"name": "概念名 (翻译)", "importance": "核心突破", "novelty": "增量补充"}}
],
"conflicts": ["本文发现 X，但已有概念 [[Y]] 中提到 Z，两者存在矛盾"],
"gaps": ["知识库已有 [[A]] 的结论，但缺少 B 条件下的数据"],
"source": "{{当前资料的来源名称（论文标题/文档名，取简短标识即可）}}"

⚠️ 矛盾和缺口规则：
- 每条矛盾必须引用已有知识库中的具体概念或页面名称
- 如果无法锚定到已有知识，不要报告（宁缺毋滥）
- 缺口必须是"已有 X 但缺少 Y"的具体格式，不是"建议研究方向"
"""


def inject_schema_to_analyst(base_instructions: str, schema_content: str) -> str:
    """将 Schema 注入到 Analyst 的 instructions 中。
    
    如果 ENABLE_SCHEMA=false 或 schema_content 为空，返回原始 instructions。
    """
    if not ENABLE_SCHEMA or not schema_content:
        return base_instructions
    return base_instructions + ANALYST_SCHEMA_INJECTION.format(schema_content=schema_content)


# ═══════════════════════════════════════════
# Editor Prompt 注入
# ═══════════════════════════════════════════

EDITOR_ENTRIES_INJECTION = """

## 知识判断（来自分析师，供融合参考）

{entries_text}

### 融合规则（严格执行）

**页面粒度控制——不要过度拆分：**
- "核心突破" → 如果已有相关页面，在该页面内展开详写；只有完全新概念才 create 新页
- "关键支撑" → 一律合并到已有的相关页面中（作为新章节或补充段落），不创建独立页面
- "背景知识" → 在相关页面中一句话带过，不需要展开
- "可忽略" / "已知重申" → 如无增量信息，跳过

**矛盾标注——必须锚定具体来源：**
- 如果检测到潜在矛盾，必须在 ⚠️ 注意 段落中明确写出：与【哪个已有概念/页面】的【哪段内容】矛盾
- 如果无法锚定到已有页面中的具体内容，不要报告矛盾（宁缺毋滥）
- 矛盾的表述应该是："本文发现 X，但已有页面 [[Y]] 中提到 Z"，而不是泛泛的"与常规认知不同"

**缺口识别——具体到已有知识的空白：**
- 不要输出"建议研究方向"这种泛泛而谈的内容
- 要输出具体的知识缺口："知识库已有 [[A]] 的结论，但缺少 B 条件下的数据"
- 缺口信息加在页面末尾的 "## 知识缺口" 章节（不是"待深入"）

⚠️ 重要：不要把这些判断信息写到 frontmatter 里！它们应该自然地融入正文。

**矛盾处理策略（严格执行）：**
- 当检测到矛盾时，不覆盖旧内容
- 在页面末尾添加 "## ⚠️ 矛盾待解决" 章节
- 格式：`> ⚠️ 本文发现 X，但已有页面 [[Y]] 中提到 Z（来源：[论文名]）`
- 保留两个版本，等待人工审核
"""


def inject_entries_to_editor(base_prompt: str, entries: list, conflicts: list, gaps: list) -> str:
    """将 Analyst 的判断信息注入到 Editor 的 prompt 中。
    
    如果 ENABLE_SCHEMA=false 或 entries 为空，返回原始 prompt。
    """
    if not ENABLE_SCHEMA or not entries:
        return base_prompt
    
    entries_text = json.dumps(entries, ensure_ascii=False, indent=2)
    if conflicts:
        entries_text += f"\n\n潜在矛盾（已锚定已有知识）：{json.dumps(conflicts, ensure_ascii=False)}"
    if gaps:
        entries_text += f"\n\n知识缺口（已有X但缺少Y）：{json.dumps(gaps, ensure_ascii=False)}"
    
    return base_prompt + EDITOR_ENTRIES_INJECTION.format(entries_text=entries_text)


# ═══════════════════════════════════════════
# log.md 追加
# ═══════════════════════════════════════════

def build_log_entry(
    action: str,
    doc_name: str,
    details: dict = None,
    actions_summary: list = None,
    conflicts: list = None,
) -> str:
    """构建一条 log.md 条目（OKF 兼容格式）。
    
    action: ingest / query / lint / forge
    doc_name: 文档名称
    details: 可选的统计细节
    actions_summary: 可选的操作摘要列表，如 ["edit: X.md — 加入 Y 数据", "create: Z.md"]
    conflicts: 可选的矛盾列表
    """
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n## {now} — {action} {doc_name}\n"
    
    if actions_summary:
        for act in actions_summary:
            entry += f"- {act}\n"
    
    if conflicts:
        for c in conflicts:
            entry += f"- conflict: {c}\n"
    
    if details:
        for key, value in details.items():
            if isinstance(value, list):
                entry += f"- {key}: {', '.join(str(v) for v in value)}\n"
            else:
                entry += f"- {key}: {value}\n"
    
    return entry


# ═══════════════════════════════════════════
# OKF frontmatter 构建
# ═══════════════════════════════════════════

def build_frontmatter(page_type: str = "concept", tags: list = None, source: list = None) -> str:
    """生成 OKF 兼容的 YAML frontmatter。
    
    仅当 ENABLE_SCHEMA=true 时返回内容，否则返回空字符串。
    """
    if not ENABLE_SCHEMA:
        return ""
    import yaml
    fm = {
        "type": page_type,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tags": tags or [],
    }
    if source:
        fm["source"] = source
    return "---\n" + yaml.dump(fm, allow_unicode=True, default_flow_style=False).strip() + "\n---\n\n"


# ═══════════════════════════════════════════
# Schema 建议生成
# ═══════════════════════════════════════════

SUGGESTION_PROMPT = """分析以下知识库的最近活动日志，检测是否有值得沉淀为 Schema 约定的模式。

已有建议（避免重复）：
{existing_suggestions}

最近活动：
{recent_log}

如果有值得记录的模式，输出格式：

## [{date}] 第 N 条建议

**来源**：...
**观察**：...
**建议**：...
**采纳方式**：告诉系统"把第 N 条建议合并到 schema.md"

---

如果没有新模式，只输出：NO_NEW_SUGGESTIONS"""


def build_suggestion_prompt(existing_suggestions: str, recent_log: str) -> str:
    """构建建议生成 prompt"""
    today = datetime.date.today().isoformat()
    return SUGGESTION_PROMPT.format(
        existing_suggestions=existing_suggestions[-2000:] if existing_suggestions else "(无)",
        recent_log=recent_log[-3000:] if recent_log else "(无)",
        date=today,
    )
