# workflows/ — 确定性工作流层

用 Workflow 替代自由度过高的 Agent 对话。对于需要按固定步骤执行的操作，必须使用 Workflow 确保每一步都被执行且不可跳过。

所有工作流均接受 `user_id` 参数，通过 `core/path_resolver.py` 解析到用户隔离路径。

## 文件说明

| 文件 | 作用 | 调用方式 |
|------|------|---------|
| `ingest_flow.py` | **摄入流水线**：Map-Reduce 三阶段并发（12线程提取 → 概念聚类 → 逐概念融合） | `IngestFlow(user_id, workspace).run(file_path)` |
| `lint_flow.py` | **审查流水线**：扫描所有 wiki 页面 → 检测死链和孤立页面 → 自动编织反向链接 | `LintFlow(user_id, workspace).run()` |
| `query_flow.py` | **查询路由**：IntentRouter → Team[local_wiki + web_researcher] → summarizer → Markdown | `QueryFlow(user_id, workspace).run(query)` |
| `autofill_flow.py` | **幽灵节点填补**：扫描双链统计入度 → 探测真空节点（有引用无页面）→ 自动合成填充 | `AutoFillFlow(user_id, workspace, threshold).run()` |
| `report_flow.py` | **批量报告生成**：TopicScanner → BulkRetriever → ReportSynthesizer | `ReportFlow(user_id, workspace).run(topic, materials)` |

## ingest_flow.py — Map-Reduce 知识摄取流水线

三阶段并发架构，兼顾效率与质量：

```
原始文档
  │
  ├── [Phase 1: MAP]    12线程并发调用 WikiAnalyst 提取各知识块的概念+摘要
  ├── [Phase 2: SHUFFLE] 按概念聚类（同义词解构引擎：英文名(中文)格式）
  └── [Phase 3: REDUCE] 逐个概念启动 WikiEditor 融合 → WikiWriter 写盘
```

- **Phase 1 MAP**：无锁并发，12 线程同时提取，大幅加速
- **Phase 2 SHUFFLE**：基于双语解构（`Self-Attention (自注意力机制)` 等格式）合并同名碎片
- **Phase 3 REDUCE**：逐概念重启新鲜 `WikiEditor`，消除记忆污染；Token 超限自动截断保护
- **并发安全**：使用 `threading.local()` + `set_context()` 传递 user_id/workspace（替代旧版 `os.environ` 全局变量方案）

## lint_flow.py — 审查流水线

| 检查项 | 说明 |
|--------|------|
| 死链 | `[[target]]` 引用但文件不存在 |
| 孤立页面 | 文件存在但从未被任何 `[[]]` 引用 |
| 反向链接 | 自动为被引用页面追加 backlink |

## query_flow.py — 查询路由

```
用户查询 → IntentRouter (LLM 分类) → chat / scan / summary / query
  → Team[local_wiki + web_researcher] → summarizer → SSE 流式 Markdown
```

- `IntentRouter` 是轻量 Agno Agent，Pydantic `_IntentDecision` 输出意图分类
- ≤3 字符短文本走 fast path 绕过 LLM
- 增强日志：map 摘要、local_concepts、fuzzy_keywords、needs_web_search

## autofill_flow.py — 幽灵节点自动填补

```
全盘扫描 → 统计 [[双链]] 入度 → 过滤真空节点 → 溯源上下文 → 主编合成 → 写盘
```

- 扫描 concepts 目录下所有 Markdown 文件，提取 `[[xxx]]` 双向链接
- 统计每个概念的入度，被引用 ≥ threshold 次但无实体页面的即为「真空节点」
- 自动修复异名假空节点（链接重定向），再对纯正真空节点逐个合成

## report_flow.py — 批量报告生成

```
指定主题 → TopicScanner 扫描相关材料 → BulkRetriever 批量检索 → ReportSynthesizer 分章节合成
```

- 区别于 query_flow：query 是精准概念查找，report 是 bulk 检索 + 章节级结构化输出
- 三 Agent 管道：TopicScanner → BulkRetriever → ReportSynthesizer
- 前端对应 ReportMode.jsx 组件

## 扩展指引

- **新增工作流**：在本目录新建 `xxx_flow.py`，编排已有 Agent 和工具
- **定时执行**：在 `app.py` 或 crontab 中调用 `LintFlow().run()` 定期审查
- **原子性保障**：每步操作完成后立即追加 `log.md`，支持事后审计
- **任务日志**：工作流执行时通过 `core/task_log.py` 的 `TaskOutputCapture` 捕获 stdout，支持管理后台实时查看
