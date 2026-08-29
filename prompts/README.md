# prompts/ — 提示词工程库

将 System Prompt 从 Python 代码中解耦，独立维护、版本可控，像改文档一样调整 Agent 行为。

## 文件说明

| 文件 | 定义 | 调用方 |
|------|------|--------|
| `boss_prompt.py` | 主管 Agent 路由规则：判断任务类型，分发至 Research / Wiki / PPT 分支 | `app.py` |
| `research_prompt.py` | 深度研究协议：英文关键词搜索、交叉验证、结构化输出 | `web_researcher.py` |
| `wiki_prompt.py` | Wiki 维护者提示词，含 `build_analyst_system_prompt()` / `build_writer_system_prompt()` | `wiki_analyst.py` / `wiki_writer.py` |
| `ppt_prompt.py` | PPT 排版指令：布局、配色、内容密度控制 | `ppt_maker.py` 🔧 |

## 提示词加载机制

`wiki_analyst.py` 和 `wiki_editor.py` 各自内置 `instructions` 字符串，在初始化时直接传递给 Agent。
`protocols/` 下的协议文件（purpose.md / schema.md）作为知识库规范的独立维护层，供 Agent 在运行时参考：

```python
from agents.wiki_analyst import WikiAnalyst

analyst = WikiAnalyst()
# Analyst 的 instructions 已内建提取规则（概念提取、双语格式等）
```

## 扩展指引

- **修改 Agent 行为**：编辑对应 `.py` 中的 `instructions` 字符串
- **修改知识库规范**：编辑 `protocols/schema.md` 或 `protocols/purpose.md`（无需改 Python 代码）
- **新增 Agent 类型**：新建 `xxx_agent.py`，在 `instructions` 中定义角色规范，Agent 初始化时自动注入
