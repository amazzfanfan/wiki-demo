# data/ — 数据输入输出区

读写分离 + 用户物理隔离。

## 目录结构

```
data/
├── memory.db               # SQLite 会话记忆（Agno SqliteDb）
│
├── raw/{user_id}/          # 【只读】原始来源层（按用户隔离）
│   └── *.pdf / *.docx / *.md / *.png ...
│
└── wiki/{user_id}/         # 【可写】维基编译层（按用户隔离）
    └── {workspace}/        # 沙箱
        ├── concepts/       # 知识概念页面（*.md）
        │   └── mocs/       # MOC (Map of Content) 索引页面
        └── index.md        # 沙箱级导航地图
```

## 路径解析

所有路径通过 `core/path_resolver.py` 统一解析：

```python
from core.path_resolver import get_wiki_root, get_concepts_dir, get_index_path

# data/wiki/sybh/邯钢资料论文/concepts/
concepts = get_concepts_dir("sybh", "邯钢资料论文")

# data/wiki/sybh/邯钢资料论文/index.md
index = get_index_path("sybh", "邯钢资料论文")

# data/raw/sybh/
raw = get_raw_root("sybh")
```

## 读写权限矩阵

| 目录 | Agent 读 | Agent 写 | 人类编辑 |
|------|---------|---------|---------|
| `raw/{user_id}/` | ✅ | ❌ 禁止 | ✅ 上传新文件 |
| `wiki/{user_id}/{ws}/concepts/` | ✅ | ✅ via edit_tools | ✅ |
| `wiki/{user_id}/{ws}/index.md` | ✅ | ✅ via edit_tools | ✅ |

## index.md — 沙箱导航

每个沙箱的**全局寻址核心**，包含：
- 概念目录清单
- 最近更新记录
- 跨领域关联索引

每次 `ingest_flow` 完成后必须同步更新；`lint_flow` 定期检查其一致性。

## 安全边界

- `path_resolver.py` 按 `user_id` 隔离路径，用户无法访问他人数据
- `file_tools.py` 强制校验路径，禁止 `../` 跳出 `data/wiki/{user_id}/`
- `edit_tools.py` 所有写入必须通过 `str_replace()` 或 `append_to_log()`
- 原始数据在 `raw/` 中永不修改，支持重新编译（Re-compile）
