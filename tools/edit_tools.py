"""
edit_tools.py — 局部精准编辑工具 (async安全·用户隔离版)
"""
import os
import re
import threading
import contextvars
from pathlib import Path

from core.storage import get_storage

# 锁定操作根目录，绝对不准越界
WIKI_ROOT = Path(__file__).parent.parent / "data" / "wiki"

# ═══════════════════════════════════════════════════════
# 🧵 异步安全上下文（ContextVar：async 协程级隔离）
# ═══════════════════════════════════════════════════════
# 替代 threading.local()：
#   - threading.local 按 OS 线程隔离，但 FastAPI 的 async 端点
#     共享同一个事件循环线程，多个并发请求会互相覆盖
#   - ContextVar 按 async 协程隔离，每个请求有独立的上下文副本
#   - ThreadPoolExecutor.submit() 自动继承父线程的 ContextVar 值
# ═══════════════════════════════════════════════════════
_var_user_id = contextvars.ContextVar("edit_user_id", default="")
_var_kb_name = contextvars.ContextVar("edit_kb_name", default="default")
_var_sub_dir = contextvars.ContextVar("edit_sub_dir", default="")
_var_doc_name = contextvars.ContextVar("edit_doc_name", default="")


def set_context(user_id: str = "", kb_name: str = "default", sub_dir: str = "", doc_name: str = ""):
    """设置当前协程/线程的路由上下文（async 安全，不影响其他请求）"""
    _var_user_id.set(user_id)
    _var_kb_name.set(kb_name)
    _var_sub_dir.set(sub_dir)
    _var_doc_name.set(doc_name)


def get_context() -> dict:
    """获取当前协程/线程的路由上下文"""
    return {
        "user_id": _var_user_id.get(),
        "kb_name": _var_kb_name.get(),
        "sub_dir": _var_sub_dir.get(),
        "doc_name": _var_doc_name.get(),
    }


# ── OKF 上下文（ContextVar，供 create_page 自动注入 frontmatter）──
_var_okf_page_type = contextvars.ContextVar("okf_page_type", default="")
_var_okf_source = contextvars.ContextVar("okf_source", default=None)

def set_okf_context(page_type: str = "", source: list = None):
    """设置当前协程的 OKF 元数据（frontmatter 注入用）"""
    _var_okf_page_type.set(page_type)
    _var_okf_source.set(source or [])

def get_okf_context() -> dict:
    """获取当前协程的 OKF 元数据"""
    return {
        "page_type": _var_okf_page_type.get(),
        "source": _var_okf_source.get() or [],
    }


# ═══════════════════════════════════════════════════════
# 🔒 文件操作锁池（防止 read-modify-write 竞态）
# ═══════════════════════════════════════════════════════
# 同一个文件同时只能有一个线程在做 读→改→写 操作，
# 防止两个线程同时读取相同内容、各自修改、后写覆盖先写。
_file_lock_pool: dict[str, threading.Lock] = {}
_file_lock_pool_guard = threading.Lock()


def _get_file_lock(key: str) -> threading.Lock:
    """获取文件级锁（双检锁，线程安全）"""
    if key not in _file_lock_pool:
        with _file_lock_pool_guard:
            if key not in _file_lock_pool:
                _file_lock_pool[key] = threading.Lock()
    return _file_lock_pool[key]


def _resolve(file_name: str) -> Path:
    """以父文件夹（分类）为中心的统筹路由，支持用户级隔离"""
    ctx = get_context()
    kb_name = ctx["kb_name"]
    sub_dir = ctx["sub_dir"]
    user_id = ctx["user_id"]

    # 用户隔离：data/wiki/{user_id}/{kb_name}/{sub_dir}
    if user_id:
        base_dir = Path(__file__).resolve().parent.parent / "data" / "wiki" / user_id / kb_name / sub_dir
    else:
        base_dir = Path(__file__).resolve().parent.parent / "data" / "wiki" / kb_name / sub_dir

    # 2. 智能路由
    if Path(file_name).name.lower() == "index.md":
        # 强制把 index.md 放在父文件夹的根目录，作为唯一总索引
        final_path = base_dir / "index.md"
    else:
        # 大模型输出的 concepts/xxx.md 或 datasets/xxx.md 直接拼接在父文件夹后面
        final_path = base_dir / file_name

    # 3. 自动创建父级目录（比如自动建好 concepts/）
    final_path.parent.mkdir(parents=True, exist_ok=True)

    return final_path

def _resolve_key(file_name: str) -> str:
    """返回 MinIO 对象 Key（对应本地 _resolve 返回的 Path）"""
    ctx = get_context()
    parts = ["wiki"]
    if ctx["user_id"]:
        parts.append(ctx["user_id"])
    parts.append(ctx["kb_name"])
    if ctx["sub_dir"]:
        parts.append(ctx["sub_dir"])
    if Path(file_name).name.lower() == "index.md":
        parts.append("index.md")
    else:
        parts.append(file_name)
    return "/".join(parts)




def _sanitize_filename(file_name: str) -> str:
    """清洗 LLM 生成的脏文件名：保留 concepts/ 前缀，只清洗文件名部分"""
    import re
    name = file_name.strip()

    # 分离目录前缀和文件名
    if "/" in name:
        dir_part = "/".join(name.split("/")[:-1]) + "/"
        base = name.split("/")[-1]
    else:
        dir_part = ""
        base = name

    # 去 markdown 标记 (###, ##, #, -, *)
    base = re.sub(r"^[#\-*]+\s*", "", base)
    # 先分离 .md 后缀，确保后缀清洗在纯名称上操作
    _has_md = base.lower().endswith(".md")
    if _has_md:
        base = base[:-3]

    # 去 create_ 前缀（英文）
    base = re.sub(r"^create_", "", base)
    # 去中文动作前缀（创建/新建/生成/制作）
    base = re.sub(r"^(创建|新建|生成|制作)\s*", "", base)
    # 去中文后缀（概念页面/概念页/页面/条目/笔记）
    base = re.sub(r"\s*(概念页面|概念页|页面|条目|笔记)\s*$", "", base)

    # 还原 .md 后缀
    if _has_md:
        base = base + ".md"
    # 去 concepts_ 前缀（LLM 有时把目录名拼进文件名）
    base = re.sub(r"^concepts_", "", base)
    # 去双重扩展名 (.md.md → .md)
    while base.endswith(".md.md"):
        base = base[:-3]
    # 去非法字符
    base = re.sub(r'[<>:"|?*]', "", base)
    # 去首尾空格和点
    base = base.strip(" .")

    result = dir_part + base if base else file_name

    # 确保概念文件在 concepts/ 下（除非是 index.md）
    if base and base.lower() != "index.md" and not result.startswith("concepts/"):
        result = "concepts/" + result

    return result


def _clean_tags(tags) -> list[str]:
    """清洗标签脏数据，返回干净的标签列表"""
    clean_tags = []
    if tags:
        if isinstance(tags, str):
            cleaned = tags.replace("[", "").replace("]", "").replace("'", "").replace('"', "")
            clean_tags = [t.strip() for t in cleaned.split(",") if t.strip()]
        elif isinstance(tags, list):
            for t in tags:
                t_str = str(t).replace("[", "").replace("]", "").replace("'", "").replace('"', "").strip()
                if t_str:
                    clean_tags.append(t_str)
    return clean_tags


def _build_body(title: str, tags: list[str], abstract: str, content: str = "",
                page_type: str = "", source: list = None) -> str:
    """生成标准页面模板（统一 MinIO/Local 两种模式的输出格式）
    
    Schema 启用时输出 OKF 兼容的 YAML frontmatter；
    Schema 未启用时保持原有格式（向后兼容）。
    """
    import datetime
    tag_str = " ".join(_clean_tags(tags))
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    abs_text = abstract.replace("\\n", "\n")
    details = (content or "（等待后续扩展）").replace("\\n", "\n")

    # ── OKF frontmatter（仅 Schema 启用时注入）──
    from core.schema_engine import is_enabled as schema_enabled
    frontmatter = ""
    if schema_enabled():
        import yaml
        fm = {
            "type": page_type or "concept",
            "timestamp": now_iso,
            "tags": _clean_tags(tags),
        }
        if source:
            fm["source"] = source
        frontmatter = "---\n" + yaml.dump(fm, allow_unicode=True, default_flow_style=False).strip() + "\n---\n\n"

    body = f"""{frontmatter}# {title}

> **Tags:** {tag_str}
> **Created:** {date_str}

## Abstract
{abs_text}

## Details
{details}

## Related
- 

## References
- 
"""
    return body


# 💡 注意参数里多了 content
def create_page(file_name: str, title: str, tags: list[str], abstract: str, content: str = "",
                page_type: str = "", source: list = None) -> str:
    """严格按照 schema 模板创建新页面，包含模糊去重机制"""
    from pathlib import PurePosixPath

    file_name = _sanitize_filename(file_name)
    s = get_storage()
    key = _resolve_key(file_name)

    # 本地模式下确保目录存在
    path = _resolve(file_name)

    # 🔒 文件锁：查重 + 创建是原子操作，防止并发创建同名文件
    lock = _get_file_lock(key)
    lock.acquire()
    try:
        # ── 统一查重：模糊名称匹配（去 -/_/空格/.md 后比较） ──
        parent_prefix = str(PurePosixPath(key).parent) + "/"
        sibling_keys = s.list_keys(parent_prefix)
        clean_new = PurePosixPath(key).stem.lower().replace("-", "").replace("_", "").replace(" ", "")
        for k in sibling_keys:
            if k.endswith(".md"):
                clean_exist = PurePosixPath(k).stem.lower().replace("-", "").replace("_", "").replace(" ", "")
                if clean_new == clean_exist:
                    return f"⚠️ 拦截重复：{k} 已存在，规避新建：{file_name}"

        # OKF: 自动从上下文拉取 type/source（如果未显式传递）
        if not page_type or not source:
            okf = get_okf_context()
            page_type = page_type or okf["page_type"]
            source = source or okf["source"]

        # 生成标准页面内容（统一模板，消除两个分支的重复代码）
        body = _build_body(title, tags, abstract, content, page_type=page_type, source=source)
        s.write_text(key, body)
        return f"✅ 成功创建页面：{file_name}"
    finally:
        lock.release()


def str_replace(file_name: str, old_str: str, new_str: str) -> str:
    """极其精密的局部替换工具 (带空格宽容 + 活路径路由)"""
    s = get_storage()
    key = _resolve_key(file_name)

    if not s.exists(key):
        return f"❌ 错误：底层工具找不到文件 ({key})"

    # 🔒 文件锁：read → modify → write 必须是原子操作，
    # 防止两个线程同时读取相同内容、各自修改、后写覆盖先写
    lock = _get_file_lock(key)
    lock.acquire()
    try:
        content = s.read_text(key)

        # OKF: 从上下文获取来源，追加到 frontmatter
        okf = get_okf_context()
        okf_sources = okf.get("source", [])

        # 1. 尝试绝对精确匹配
        if old_str in content:
            new_content = content.replace(old_str, new_str, 1)
            new_content = _refresh_timestamp(new_content)
            for src in okf_sources:
                new_content = _append_source(new_content, src)
            s.write_text(key, new_content)
            return f"✅ 成功修改文件：{file_name}"

        # 2. 尝试宽容匹配 (去掉大模型首尾乱加的换行和空格)
        old_str_clean = old_str.strip()
        if old_str_clean and old_str_clean in content:
            new_content = content.replace(old_str_clean, new_str, 1)
            new_content = _refresh_timestamp(new_content)
            for src in okf_sources:
                new_content = _append_source(new_content, src)
            s.write_text(key, new_content)
            return f"✅ 成功修改文件(启用宽容匹配)：{file_name}"

        return f"❌ 找不到旧文本，大模型可能产生了格式幻觉！\n寻找的: {repr(old_str)}"
    finally:
        lock.release()


def _refresh_timestamp(content: str) -> str:
    """更新 frontmatter 中的 timestamp 字段（OKF 兼容）。无 frontmatter 则不动。"""
    import datetime
    if not content.startswith("---"):
        return content
    try:
        now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return re.sub(r'timestamp:\s*["\']?[^"\'\n]+["\']?', f'timestamp: {now_iso}', content, count=1)
    except Exception:
        return content


def _append_source(content: str, new_source: str) -> str:
    """向 frontmatter 的 source 列表追加来源（去重）。无 frontmatter 则不动。"""
    if not content.startswith("---") or not new_source:
        return content
    try:
        import re as _re
        # 检查是否已有 source 字段
        m = _re.search(r'source:\s*\[([^\]]*)\]', content)
        if m:
            existing = [s.strip().strip("'") for s in m.group(1).split(',') if s.strip()]
            if new_source not in existing:
                existing.append(new_source)
                new_list = ', '.join(existing)
                content = content[:m.start()] + f'source: [{new_list}]' + content[m.end():]
        else:
            # 没有 source 字段，在 frontmatter 末尾加
            # 找到第二个 --- （frontmatter 结束标记）
            first_end = content.find('\n---\n', 1)
            if first_end > 0:
                content = content[:first_end] + f'\nsource: [{new_source}]' + content[first_end:]
    except Exception:
        pass
    return content