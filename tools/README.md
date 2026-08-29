# tools/ — 技能工具箱

封装外部能力供 Agent 调用，每个工具文件专注一类操作。

## 文件说明

| 文件 | 能力 | 状态 |
|------|------|------|
| `search_tools.py` | DuckDuckGoTools 联网搜索 + Newspaper4kTools 全文抓取 | ✅ |
| `file_tools.py` | 安全文件操作：路径锁定在 `data/wiki/`，拒绝 `../` 越界遍历 | ✅ |
| `edit_tools.py` | `str_replace` 精密局部替换 + `create_page` 新建页面。含 `_resolve()` 活路径解析 + 同义词防撞 + `threading.local()` 上下文传递 | ✅ |
| `document_parser.py` | 文档解析：PDF（pdfplumber）+ Word（python-docx）读取、文本分块 `extract_text` / `chunk_text` | ✅ |
| `ppt_tools.py` | python-pptx 封装，根据大纲生成 PPT | 🔧 WIP |
| `vision_tools.py` | 图片读取、OCR 等视觉预处理 | 🔧 WIP |

## 并发安全

`edit_tools.py` 使用 `threading.local()` 传递当前请求的 `user_id` 和 `workspace`：

```python
# 工作流启动时设置上下文
from tools.edit_tools import set_context
set_context(user_id="sybh", workspace="邯钢资料论文")

# edit_tools 内部读取
ctx = get_context()
wiki_root = path_resolver.get_wiki_root(ctx.user_id) / ctx.workspace
```

替代了旧版 `os.environ["ACTIVE_KB"]` 全局变量方案，消除了多线程竞态条件。

## 安全隔离

- `file_tools.py` 和 `edit_tools.py` 强制校验路径，所有文件操作被圈禁在 `data/wiki/{user_id}/` 内
- Agent 无法越界写入其他用户的目录
- 所有写入操作（新建、编辑、追加日志）统一通过 `edit_tools.py`，确保审计可追溯
