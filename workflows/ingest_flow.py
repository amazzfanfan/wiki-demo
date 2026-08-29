import sys
import os
import re
import time
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError

from agents.wiki_analyst import WikiAnalyst
from agents.wiki_editor import WikiEditor
from agents.wiki_writer import WikiWriter
from tools.document_parser import extract_text, chunk_text
from tools.edit_tools import _resolve, set_context, _resolve_key
from core.storage import get_storage
from core.path_resolver import USE_MINIO
from core.path_resolver import minio_concepts_prefix, minio_index_key
from core.content_validator import validate_abstract
from core.ingest_control import (
    is_terminate_requested, mark_concept_done,
    is_concept_done, save_file_checkpoint, save_shuffle_result,
)
# ── Schema 领域自适应（可插拔）──
from core.schema_engine import (
    is_enabled as schema_enabled,
    build_phase0_prompt, build_log_entry, build_suggestion_prompt,
)


class IngestFlow:
    """
    知识摄入流水线 (终极形态：Map-Reduce 降维打击版)
    """

    def __init__(self):
        self.analyst = WikiAnalyst()
        self.writer = WikiWriter()
        # Editor 会在循环内动态实例化，防止上下文记忆污染

        # ═══ P0 优化：缓存与索引 ═══
        self._file_cache = {}           # {filepath: content} 文件内容缓存
        self._context_cache = {}        # {concept_tuple: context_str} 上下文缓存
        self._concept_index = {}        # {normalized_name: Path} 概念文件索引

        # ── Schema 领域自适应（可插拔）──
        self._schema_content = ""       # 当前沙箱的 Schema 内容
        self._all_entries = []          # MAP 阶段收集的带判断条目
        self._all_conflicts = []        # MAP 阶段收集的矛盾信息（锚定已有知识）
        self._all_gaps = []             # MAP 阶段收集的知识缺口（已有X但缺少Y）
        self._all_sources = []          # OKF: 本轮 ingest 的来源名称列表
        self._reduce_actions_log = []   # OKF: REDUCE 阶段的操作摘要（用于 log.md）

    def _normalize_name(self, text: str) -> str:
        if not text:
            return ""
        return re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5]', '', text).lower()

    @staticmethod
    def _adaptive_chunk_params(text_len: int) -> tuple[int, int]:
        """根据文档长度自适应选择 chunk_size 和 overlap。
        目标：每个 chunk 有足够上下文让 Analyst 提取 3-5 个概念，
        同时避免碎片化导致概念频次=1。
        """
        if text_len < 3000:
            # 短文档不切分，整块给 Analyst
            return max(text_len, 1), 0
        elif text_len < 8000:
            return 3000, 300
        elif text_len < 20000:
            return 4000, 400
        else:
            # 大文档：保持合理 chunk 数（~4-8 个）
            return 5000, 500

    def _build_concept_index(self):
        """🔧 P0-1: 一次性构建概念文件索引，后续查找 O(1)"""
        index = {}
        if USE_MINIO:
            s = get_storage()
            from tools.edit_tools import get_context
            ctx = get_context()
            prefix = minio_concepts_prefix(ctx["user_id"], ctx["kb_name"])
            all_keys = get_storage().list_keys(prefix)
            for key in all_keys:
                if key.endswith(".md"):
                    stem = key.split("/")[-1].replace(".md", "")
                    norm = self._normalize_name(stem)
                    if norm:
                        index[norm] = key  # MinIO key 字符串
        else:
            concepts_dir = _resolve("concepts")
            if concepts_dir.exists():
                for f in concepts_dir.glob("*.md"):
                    norm = self._normalize_name(f.stem)
                    if norm:
                        index[norm] = f  # 本地 Path 对象
        self._concept_index = index
        print(f"  📇 概念索引已构建: {len(index)} 个文件")

    def _build_canonical_registry(self, concept_payloads: dict) -> dict:
        """🏛️ Canonical Registry：本批次所有合法概念名的权威全集

        来源：
        1. SHUFFLE 产出的概念（display_name + aliases）
        2. KB 已有文件（file stem）

        Editor 只能对这些名字做 create/edit，不允许自行发明新名字。
        Writer 用此注册表做精确验证，彻底消除字符串模糊匹配的不确定性。

        Returns:
            dict: {normalized_name: canonical_display_name}
        """
        registry = {}

        # 1. 当前批次的所有概念（display_name + aliases）
        for norm_key, payload in concept_payloads.items():
            display = payload["display_name"]
            registry[self._normalize_name(display)] = display
            for alias in payload.get("aliases", set()):
                norm_alias = self._normalize_name(alias)
                if norm_alias:
                    registry[norm_alias] = display

        # 2. KB 已有文件
        for norm_name, file_ref in self._concept_index.items():
            if norm_name not in registry:
                if isinstance(file_ref, Path):
                    registry[norm_name] = file_ref.stem
                else:  # MinIO key string
                    registry[norm_name] = file_ref.split("/")[-1].replace(".md", "")

        print(f"  🏛️ Canonical Registry: {len(registry)} 个合法名称")
        return registry

    def _find_existing_file(self, concept: str) -> Path:
        """同义词嗅探器：基于预构建索引 O(1) 查找，回退模糊匹配"""
        norm_c = self._normalize_name(concept)
        if not norm_c:
            return None

        # O(1) 精确命中
        if norm_c in self._concept_index:
            return self._concept_index[norm_c]

        # O(N) 模糊包含匹配（仅对短索引回退）
        if len(norm_c) > 2:
            for norm_f, f in self._concept_index.items():
                if len(norm_f) > 2:
                    if norm_c in norm_f or norm_f in norm_c:
                        return f
        return None

    def _read_file_cached(self, filepath) -> str:
        """🔧 P0-2: 带缓存的文件读取，同一批次内不重复读盘"""
        key = str(filepath)
        if key not in self._file_cache:
            if USE_MINIO and not isinstance(filepath, Path):
                # MinIO 模式：filepath 是 MinIO key 字符串
                self._file_cache[key] = get_storage().read_text(filepath)
            else:
                # 本地模式：filepath 是 Path 对象
                self._file_cache[key] = filepath.read_text(encoding="utf-8")
        return self._file_cache[key]

    def _fetch_local_context(self, concepts: list) -> str:
        """档案管理员：提取上下文，提供给大模型参考（带缓存）
        
        💡 Token 瘦身：只传 index.md 标题列表 + 概念文件 Abstract 段，不传全文。
           Editor 需要知道「哪些概念存在」和「大概是什么」，不需要读全文做融合。
        """
        cache_key = tuple(sorted(concepts))
        if cache_key in self._context_cache:
            return self._context_cache[cache_key]

        context_str = "\n"

        if USE_MINIO:
            s = get_storage()
            from tools.edit_tools import get_context
            ctx = get_context()
            idx_key = minio_index_key(ctx["user_id"], ctx["kb_name"])

            if get_storage().exists(idx_key):
                full = self._read_file_cached(idx_key)
                # 过滤占位符文本，防止 Editor 将其用作 old_str
                full = re.sub(r'等待知识摄入\.\.\.', '', full).strip()
                if len(full) > 8000:
                    toc_lines = [l for l in full.split('\n') if l.strip().startswith('#') or (l.strip().startswith('-') and '[[' in l)]
                    toc = '\n'.join(toc_lines[:200]) if toc_lines else full[:3000]
                    context_str += f"=== index.md (导航地图，已截断) ===\n{toc}\n\n"
                else:
                    context_str += f"=== index.md (导航地图) ===\n{full}\n\n"
            else:
                context_str += "=== index.md (导航地图) ===\n(文件不存在)\n\n"

            for concept in concepts:
                existing_key = self._find_existing_file(concept)
                if existing_key:
                    content = self._read_file_cached(existing_key)
                    file_name = existing_key.split("/")[-1]
                    rel_path = f"concepts/{file_name}"
                    # 📉 只传 Abstract 段（~300字），不传全文（~3000字）
                    abstract = self._extract_abstract(content)
                    context_str += f"=== {rel_path} (摘要) ===\n{abstract}\n\n"
                else:
                    safe_name = concept.replace("/", "_").replace("\\", "_").replace(":", "_").replace("?", "_")
                    context_str += f"=== concepts/{safe_name}.md ===\n(全新概念)\n\n"
        else:
            index_path = _resolve("index.md")

            if index_path.exists():
                full = self._read_file_cached(index_path)
                # 过滤占位符文本，防止 Editor 将其用作 old_str
                full = re.sub(r'等待知识摄入\.\.\.', '', full).strip()
                if len(full) > 8000:
                    toc_lines = [l for l in full.split('\n') if l.strip().startswith('#') or (l.strip().startswith('-') and '[[' in l)]
                    toc = '\n'.join(toc_lines[:200]) if toc_lines else full[:3000]
                    context_str += f"=== index.md (导航地图，已截断) ===\n{toc}\n\n"
                else:
                    context_str += f"=== index.md (导航地图) ===\n{full}\n\n"
            else:
                context_str += "=== index.md (导航地图) ===\n(文件不存在)\n\n"

            for concept in concepts:
                real_file = self._find_existing_file(concept)
                if real_file:
                    content = self._read_file_cached(real_file)
                    rel_path = f"concepts/{real_file.name}"
                    # 📉 只传 Abstract 段（~300字），不传全文（~3000字）
                    abstract = self._extract_abstract(content)
                    context_str += f"=== {rel_path} (摘要) ===\n{abstract}\n\n"
                else:
                    safe_name = concept.replace("/", "_").replace("\\", "_").replace(":", "_").replace("?", "_")
                    context_str += f"=== concepts/{safe_name}.md ===\n(全新概念)\n\n"

        self._context_cache[cache_key] = context_str
        return context_str

    @staticmethod
    @staticmethod
    def _extract_abstract(content: str) -> str:
        """从概念页中提取 Abstract 段摘要（~300字），避免传全文给 LLM。
        
        会过滤掉动作描述（"创建...概念页面"等），回退到 Details 首句。
        兼容 Editor 输出中 Abstract 段内含子标题（如 ## 概述）的情况。
        """
        import re as _re
        _ACTION_PAT = _re.compile(
            r'^(create|edit|append|action\s*=|创建|新建|生成|制作|融合|阐述|补充|添加|为)',
            _re.IGNORECASE
        )
        _MAJOR_SECTIONS = ["## Details", "## Related", "## References", "## 知识缺口"]
        
        def _extract_text_from_section(section_text: str) -> str:
            """从段落文本中跳过子标题，提取实际内容"""
            lines = []
            for line in section_text.strip().split("\n"):
                stripped = line.strip()
                if stripped.startswith("## "):  # 跳过子标题（如 ## 概述）
                    continue
                if stripped and len(stripped) > 10:
                    lines.append(stripped)
            return "\n".join(lines)[:500]
        
        abstract = ""
        # 优先提取 ## Abstract 到下一个主段落（## Details 等）之间的内容
        if "## Abstract" in content:
            after = content.split("## Abstract", 1)[1]
            end_pos = len(after)
            for ms in _MAJOR_SECTIONS:
                pos = after.find(ms)
                if pos != -1 and pos < end_pos:
                    end_pos = pos
            section_text = after[:end_pos]
            abstract = _extract_text_from_section(section_text)
        
        # 检查 abstract 是否是动作描述 → 如果是，回退到 Details 首句
        if abstract and _ACTION_PAT.match(abstract):
            abstract = ""
        
        # 回退：从 Details 段取实际文本
        if not abstract and "## Details" in content:
            details = content.split("## Details", 1)[1]
            end_pos = len(details)
            for ms in ["## Related", "## References", "## 知识缺口"]:
                pos = details.find(ms)
                if pos != -1 and pos < end_pos:
                    end_pos = pos
            section_text = details[:end_pos]
            lines = []
            for line in section_text.strip().split("\n"):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                if stripped and len(stripped) > 10:
                    lines.append(stripped)
                    break
            if lines and not _ACTION_PAT.match(lines[0]):
                abstract = lines[0][:200]
        
        # 最终回退：跳过 frontmatter + 标题行，取实际内容
        if not abstract:
            body = content.split("---\n")[-1] if "---" in content else content
            lines = []
            for line in body.split("\n"):
                stripped = line.strip()
                if stripped.startswith("#") or stripped.startswith(">"):
                    continue
                if stripped:
                    lines.append(stripped)
            return "\n".join(lines)[:300]
        return abstract

    @staticmethod
    def _readable_summary(text: str) -> str:
        """从 Abstract 中提取可读摘要（语义完整，不硬截断）。
        
        规则：
        1. 过滤掉标题行（# 开头）和元信息（> 开头）
        2. 优先按句号/英文句号/换行分割，取第一句
        3. 如果第一句太短（<15字），拼接第二句
        4. 如果第一句太长（>150字），在逗号处断开
        5. 最终不超过 150 字符
        """
        if not text:
            return ""
        # 过滤掉标题行和元信息
        clean_lines = []
        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith(">") or stripped.startswith("---"):
                continue
            clean_lines.append(stripped)
        clean_text = "".join(clean_lines)
        if not clean_text:
            return ""
        # 按句号分割
        sentences = re.split(r'[。\.]+', clean_text)
        sentences = [s.strip() for s in sentences if s.strip()]
        if not sentences:
            return ""
        first = sentences[0]
        # 太短则拼接下一句
        if len(first) < 15 and len(sentences) > 1:
            first = f"{sentences[0]}。{sentences[1]}".strip()
        # 太长则在逗号处断开
        if len(first) > 150:
            parts = re.split(r'[，,]', first)
            built = parts[0]
            for p in parts[1:]:
                if len(built) + len(p) + 1 <= 150:
                    built += f"，{p}"
                else:
                    break
            first = built
        return first[:150].strip()

    def _map_extract(self, chunk, chunk_id):
        """Map 阶段的核心逻辑：只提取，不写盘"""
        try:
            if hasattr(self, '_skip_map') and self._skip_map:
                return 0, chunk, None, "resume-skip"
            print(f"  [Map 线程 {chunk_id}] 🕵️‍♂️ 提取中...")
            analysis_result = self.analyst.analyze(chunk)
            # ── entries 回退：LLM 有时把概念全放进 entries 而留空 new_concepts ──
            if not analysis_result.get("new_concepts") and analysis_result.get("entries"):
                fallback_names = []
                for e in analysis_result["entries"]:
                    name = e.get("name") if isinstance(e, dict) else getattr(e, "name", None)
                    imp = e.get("importance") if isinstance(e, dict) else getattr(e, "importance", "")
                    if name and imp != "可忽略":
                        fallback_names.append(name)
                if fallback_names:
                    analysis_result["new_concepts"] = fallback_names
                    print(f"  -> 🔄 线程 {chunk_id} entries 回退: {len(fallback_names)} 个概念", flush=True)
            if not analysis_result.get("new_concepts"):
                print(f"  -> ⚠️ 线程 {chunk_id} 无核心概念（摘要: {analysis_result.get('summary', '')[:50]}）")
                return chunk_id, chunk, None, "无核心概念"
            return chunk_id, chunk, analysis_result, "成功"
        except Exception as e:
            return chunk_id, chunk, None, f"报错: {str(e)}"

    # ═══════════════════════════════════════════
    # Schema 领域自适应（可插拔，全部 try/except 兆底）
    # ═══════════════════════════════════════════

    def _load_or_infer_schema(self, user_id: str, kb_name: str, sample_chunks: list) -> str:
        """加载已有 Schema 或首次嗅探生成。失败返回空字符串。"""
        if not schema_enabled():
            return ""
        try:
            from core.path_resolver import minio_schema_key, get_schema_path
            s = get_storage()

            # 1. 尝试读取已有 Schema
            if USE_MINIO:
                key = minio_schema_key(user_id, kb_name)
                if s.exists(key):
                    content = s.read_text(key)
                    print(f"  📖 [Schema] 已加载领域编译指南 ({len(content)} 字符)")
                    return content
            else:
                local_path = get_schema_path(user_id, kb_name)
                if local_path.exists():
                    content = local_path.read_text(encoding="utf-8")
                    print(f"  📖 [Schema] 已加载领域编译指南 ({len(content)} 字符)")
                    return content

            # 2. 首次 ingest，触发 Phase 0 嗅探
            print("  🔬 [Schema Phase 0] 首次摄入，推断领域编译约定...")
            prompt = build_phase0_prompt(kb_name, sample_chunks)

            # Schema 是全局唯一的编译指南 + 重试
            from core.llm_factory import get_qwen_model
            from agno.agent import Agent
            from concurrent.futures import ThreadPoolExecutor, TimeoutError

            agent = Agent(
                model=get_qwen_model(role="schema"),
                instructions=["你是一个领域知识分析专家。"],
                stream=False,
            )

            _SCHEMA_TIMEOUT = 120
            schema_text = None
            for _attempt in range(2):  # 最多重试 1 次
                pool = ThreadPoolExecutor(max_workers=1)
                future = pool.submit(agent.run, prompt)
                try:
                    response = future.result(timeout=_SCHEMA_TIMEOUT)
                    schema_text = response.content if hasattr(response, 'content') else str(response)
                    pool.shutdown(wait=False)
                    if schema_text and len(schema_text) > 100:
                        break  # 成功
                    else:
                        print(f"  ⚠️ [Schema] 第 {_attempt+1} 次尝试结果过短，重试...")
                        schema_text = None
                except FuturesTimeoutError:
                    print(f"  ⏰ [Schema] 第 {_attempt+1} 次尝试超时 ({_SCHEMA_TIMEOUT}s)")
                    pool.shutdown(wait=False, cancel_futures=True)
                    schema_text = None
                except Exception as _e:
                    print(f"  ⚠️ [Schema] 第 {_attempt+1} 次尝试异常: {_e}")
                    pool.shutdown(wait=False, cancel_futures=True)
                    schema_text = None

            if schema_text and len(schema_text) > 100:
                # 写入存储
                if USE_MINIO:
                    s.write_text(minio_schema_key(user_id, kb_name), schema_text)
                else:
                    local_path = get_schema_path(user_id, kb_name)
                    local_path.parent.mkdir(parents=True, exist_ok=True)
                    local_path.write_text(schema_text, encoding="utf-8")
                print(f"  ✅ [Schema] 编译指南已生成 ({len(schema_text)} 字符)")
                return schema_text
            else:
                print("  ⚠️ [Schema] 2 次尝试均失败，跳过")
                return ""

        except Exception as e:
            print(f"  ⚠️ [Schema] 加载/嗅探失败（不影响主流程）: {e}")
            return ""

    def _append_log(self, user_id: str, kb_name: str, doc_name: str,
                    map_count: int, shuffle_count: int, reduce_count: int,
                    skip_count: int, error_count: int,
                    actions_log: list = None, conflicts: list = None):
        """追加一条 log.md 记录（OKF 兼容格式）。失败静默。"""
        if not schema_enabled():
            return
        try:
            from core.path_resolver import minio_log_key, get_log_path
            s = get_storage()

            entry = build_log_entry("ingest", doc_name,
                details={
                    "MAP": f"{map_count} 块", "SHUFFLE": f"{shuffle_count} 概念",
                    "REDUCE": f"{reduce_count} 个", "skip": f"{skip_count}",
                    "error": f"{error_count}" if error_count else "0",
                    "source": ', '.join(self._all_sources) if self._all_sources else "",
                },
                actions_summary=actions_log,
                conflicts=conflicts,
            )

            if USE_MINIO:
                key = minio_log_key(user_id, kb_name)
                existing = s.read_text(key) if s.exists(key) else "# 活动日志\n"
                s.write_text(key, existing + entry)
            else:
                local_path = get_log_path(user_id, kb_name)
                local_path.parent.mkdir(parents=True, exist_ok=True)
                existing = local_path.read_text(encoding="utf-8") if local_path.exists() else "# 活动日志\n"
                local_path.write_text(existing + entry, encoding="utf-8")

            print(f"  📝 [log.md] 活动已记录")
        except Exception as e:
            print(f"  ⚠️ [log.md] 写入失败（不影响主流程）: {e}")

    def _maybe_generate_suggestions(self, user_id: str, kb_name: str):
        """REDUCE 后尝试生成 Schema 演化建议。失败静默。"""
        if not schema_enabled():
            return
        try:
            from core.path_resolver import minio_suggestions_key, minio_log_key, get_suggestions_path, get_log_path
            from agno.agent import Agent

            s = get_storage()

            # 读已有建议（避免重复）
            if USE_MINIO:
                sug_key = minio_suggestions_key(user_id, kb_name)
                existing_sug = s.read_text(sug_key) if s.exists(sug_key) else ""
                log_key = minio_log_key(user_id, kb_name)
                recent_log = s.read_text(log_key) if s.exists(log_key) else ""
            else:
                sug_path = get_suggestions_path(user_id, kb_name)
                existing_sug = sug_path.read_text(encoding="utf-8") if sug_path.exists() else ""
                log_path = get_log_path(user_id, kb_name)
                recent_log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""

            if not recent_log.strip():
                return

            prompt = build_suggestion_prompt(existing_sug, recent_log)
            from core.llm_factory import get_qwen_model
            from concurrent.futures import ThreadPoolExecutor, TimeoutError
            agent = Agent(
                model=get_qwen_model(role="schema_suggest"),
                instructions=["你是知识库的 Schema 演化顾问。"],
                stream=False,
            )
            pool = ThreadPoolExecutor(max_workers=1)
            future = pool.submit(agent.run, prompt)
            try:
                response = future.result(timeout=120)
            except FuturesTimeoutError:
                print("  ⏰ [Schema] 建议生成超时，跳过")
                pool.shutdown(wait=False, cancel_futures=True)
                return
            except Exception as _e:
                print(f"  ⚠️ [Schema] 建议生成异常: {_e}")
                pool.shutdown(wait=False, cancel_futures=True)
                return
            pool.shutdown(wait=False)

            result = response.content if hasattr(response, 'content') else str(response)
            if "NO_NEW_SUGGESTIONS" in result:
                return

            # 追加到建议文件
            new_entry = "\n---\n\n" + result
            if USE_MINIO:
                s.write_text(sug_key, existing_sug + new_entry)
            else:
                sug_path = get_suggestions_path(user_id, kb_name)
                sug_path.parent.mkdir(parents=True, exist_ok=True)
                sug_path.write_text(existing_sug + new_entry, encoding="utf-8")

            print(f"  💡 [Schema] 已生成演化建议")
        except Exception as e:
            print(f"  ⚠️ [Schema] 建议生成失败（不影响主流程）: {e}")

    def _categorize_into_index(self, concept_name: str, user_id: str, kb_name: str):
        """系统级 index.md 分类保障：基于关键词匹配将概念归入最佳分类。
        
        不依赖 LLM 的 append_link 动作。幂等：已在 index 中的概念自动跳过。
        保留分类结构（### headers），支持渐进式披露。
        """
        _ZH_STOP = {'的','和','与','或','在','是','了','不','有','也','就','都','而','及',
                    '对','以','到','等','为','被','把','从','向','让','给','着','过','个'}
        _EN_STOP = {'the','a','an','is','are','was','were','be','been','and','or','but','in',
                    'on','at','to','for','of','with','by','as','it','its','this','that','from'}
        
        def _kw(text: str) -> set:
            """提取关键词（中文按字、英文按词）"""
            text = re.sub(r'[\(（].*?[\)）]', '', text)  # 去括号
            words = set()
            for w in re.findall(r'[a-zA-Z]{3,}|[\u4e00-\u9fa5]', text):
                wl = w.lower()
                if wl not in _ZH_STOP and wl not in _EN_STOP and len(wl) >= 2:
                    words.add(wl)
            return words
        
        try:
            s = get_storage()
            if USE_MINIO:
                from core.path_resolver import minio_index_key, minio_concepts_prefix
                idx_key = minio_index_key(user_id, kb_name)
                if not s.exists(idx_key):
                    # 创建初始 index.md
                    initial = f"# {kb_name} - 知识导航\n\n## 概念\n"
                    s.write_text(idx_key, initial)
                index_content = s.read_text(idx_key)
                prefix = minio_concepts_prefix(user_id, kb_name)
                concept_keys = s.list_keys(prefix)
            else:
                from tools.edit_tools import _resolve
                idx_path = _resolve("index.md")
                if not idx_path.exists():
                    # 创建初始 index.md
                    idx_path.parent.mkdir(parents=True, exist_ok=True)
                    idx_path.write_text(f"# {kb_name} - 知识导航\n\n## 概念\n", encoding="utf-8")
                index_content = idx_path.read_text(encoding="utf-8")
                concepts_dir = _resolve("concepts")
                concept_keys = [f for f in concepts_dir.glob("*.md")] if concepts_dir.exists() else []
            
            # ── 幂等检查：已在 index 中则跳过 ──
            norm_concept = self._normalize_name(concept_name)
            existing_links = re.findall(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', index_content)
            for link in existing_links:
                if self._normalize_name(link) == norm_concept:
                    return  # 已在 index 中

            # ── 文件存在性检查：概念文件必须真实存在，否则不写 index（防止空壳/被拒绝的概念进导航）──
            _file_exists = False
            for ck in concept_keys:
                if USE_MINIO:
                    stem = ck.split("/")[-1].replace(".md", "")
                else:
                    stem = ck.stem
                if self._normalize_name(stem) == norm_concept:
                    _file_exists = True
                    break
            if not _file_exists:
                print(f"  ⏭️ [{concept_name}] 概念文件不存在，跳过 index 分类")
                return
            
            # ── 从概念文件提取关键词 ──
            concept_keywords = _kw(concept_name)
            for ck in concept_keys:
                if USE_MINIO:
                    stem = ck.split("/")[-1].replace(".md", "")
                else:
                    stem = ck.stem
                if self._normalize_name(stem) == norm_concept:
                    content = s.read_text(ck) if USE_MINIO else ck.read_text(encoding="utf-8")
                    abstract = self._extract_abstract(content)
                    concept_keywords |= _kw(abstract)
                    # 从 tags 提取
                    tags_match = re.search(r'Tags?:\*\*\s*(.+)', content)
                    if tags_match:
                        concept_keywords |= _kw(tags_match.group(1))
                    break
            
            if not concept_keywords:
                return
            
            # ── 解析 index.md 分类结构 ──
            lines = index_content.split('\n')
            categories = []  # [(header_text, keywords, line_index)]
            for i, line in enumerate(lines):
                m = re.match(r'^(#{2,4})\s+(.+)$', line.strip())
                if m:
                    header = m.group(2).strip()
                    # 跳过导航标题和 MOC
                    if '导航' in header or '知识地图' in header or header.endswith('MOC'):
                        continue
                    categories.append((header, _kw(header), i))
            
            # ── 关键词 overlap 打分 ──
            best_cat = None
            best_score = 0
            for cat_header, cat_kw, cat_line in categories:
                score = len(concept_keywords & cat_kw)
                if score > best_score:
                    best_score = score
                    best_cat = (cat_header, cat_line)
            
            # ── 提取一句话摘要 ──
            summary = ""
            for ck in concept_keys:
                if USE_MINIO:
                    stem = ck.split("/")[-1].replace(".md", "")
                else:
                    stem = ck.stem
                if self._normalize_name(stem) == norm_concept:
                    content = s.read_text(ck) if USE_MINIO else ck.read_text(encoding="utf-8")
                    abstract = self._extract_abstract(content)
                    if abstract:
                        # 取第一句（优先句号，无句号则放宽到逗号或 150 字符）
                        _sentences = re.split(r'[。\.\n]', abstract)
                        _first = _sentences[0].strip()
                        if len(_first) < 15 and len(_sentences) > 1:
                            _first = f"{_sentences[0]}。{_sentences[1]}".strip()
                        if len(_first) > 150:
                            _comma_parts = re.split(r'[，,]', _first)
                            _built = _comma_parts[0]
                            for _cp in _comma_parts[1:]:
                                if len(_built) + len(_cp) + 1 <= 150:
                                    _built += f"，{_cp}"
                                else:
                                    break
                            _first = _built
                        # 正向知识信号检测（无信号 = 动作描述 → 清空）
                        _first = validate_abstract(_first)
                        if _first:
                            summary = _first
                    break
            
            link_line = f"- [[{concept_name}]]"
            if summary:
                link_line += f" — {summary}"
            else:
                # 无有效摘要时不添加 "— "，避免空摘要或泄漏
                pass
            
            # ── 插入逻辑 ──
            MIN_SCORE = 1  # 至少 1 个关键词匹配
            
            if not categories or best_score < MIN_SCORE:
                cat_name = self._infer_category(concept_name, concept_keywords, user_id, kb_name)
                
                # 检查是否已有同名分类（防止 _infer_category 返回重复名）
                _existing_cat = None
                for cat_header, cat_kw, cat_line in categories:
                    if cat_header.strip() == cat_name.strip():
                        _existing_cat = (cat_header, cat_line)
                        break
                
                if _existing_cat:
                    # 同名分类已存在 → 追加到该分类下
                    cat_header, cat_line_idx = _existing_cat
                    cat_level = len(re.match(r'^(#+)', lines[cat_line_idx]).group(1))
                    insert_at = len(lines)
                    for i in range(cat_line_idx + 1, len(lines)):
                        m = re.match(r'^(#+)\s', lines[i])
                        if m and len(m.group(1)) <= cat_level:
                            insert_at = i
                            break
                    pos = insert_at
                    while pos > cat_line_idx + 1 and lines[pos - 1].strip() == '':
                        pos -= 1
                    lines.insert(pos, link_line)
                    new_content = '\n'.join(lines)
                    best_cat = _existing_cat  # for logging
                elif '等待知识摄入' in index_content:
                    # 首次摄入：替换占位符
                    new_content = index_content.replace(
                        '等待知识摄入...',
                        f'## 概念\n\n### {cat_name}\n{link_line}'
                    )
                else:
                    # 追加新分类
                    new_content = index_content.rstrip() + f'\n\n### {cat_name}\n{link_line}\n'
            else:
                # 在最佳分类下插入
                cat_header, cat_line_idx = best_cat
                # 找分类末尾（下一个同级或更高级 header 之前）
                cat_level = len(re.match(r'^(#+)', lines[cat_line_idx]).group(1))
                insert_at = len(lines)
                for i in range(cat_line_idx + 1, len(lines)):
                    m = re.match(r'^(#+)\s', lines[i])
                    if m and len(m.group(1)) <= cat_level:
                        insert_at = i
                        break
                
                # 在 insert_at 之前找最后一个非空行，插入链接
                # 但要先跳过空行
                pos = insert_at
                while pos > cat_line_idx + 1 and lines[pos - 1].strip() == '':
                    pos -= 1
                
                lines.insert(pos, link_line)
                new_content = '\n'.join(lines)
            
            # ── 写回 ──
            if USE_MINIO:
                s.write_text(idx_key, new_content)
            else:
                idx_path = _resolve("index.md")
                idx_path.write_text(new_content, encoding="utf-8")
            
            if best_score >= MIN_SCORE:
                print(f"  🗺️ [{concept_name}] → 归入分类 [{best_cat[0]}]")
            else:
                print(f"  🗺️ [{concept_name}] → 新建分类")
        except Exception as e:
            print(f"  ⚠️ index 分类插入失败（不影响主流程）: {e}")

    def _infer_category(self, concept_name: str, keywords: set, user_id: str = "", kb_name: str = "") -> str:
        """从 schema.md 的领域维度推断分类名（简短，2-8字）。
        
        优先从 schema.md 的"核心维度"/"什么算重要"中提取分类候选，
        用关键词 overlap 匹配最佳分类。无 schema 或无匹配时回退到通用分类。
        """
        schema_categories = []
        
        # ── 尝试从 schema.md 提取分类候选 ──
        try:
            if user_id and kb_name:
                s = get_storage()
                if USE_MINIO:
                    from core.path_resolver import minio_schema_key
                    schema_key = minio_schema_key(user_id, kb_name)
                    if s.exists(schema_key):
                        schema_text = s.read_text(schema_key)
                else:
                    from core.path_resolver import get_schema_path
                    schema_path = get_schema_path(user_id, kb_name)
                    if schema_path.exists():
                        schema_text = schema_path.read_text(encoding="utf-8")
                    else:
                        schema_text = ""
                
                if schema_text:
                    # 核心维度只用作兜底分类（固定标签，不用原文）
                    _has_schema_dim = False
                    dim_match = re.search(r'##\s*核心维度\s*\n+(.+?)(?=\n##|\Z)', schema_text, re.DOTALL)
                    if dim_match:
                        _has_schema_dim = True
                        # 核心维度是宏观描述，不适合当分类名，只标记 schema 可用
                    
                    # 提取 "什么算重要" 中的子标题（核心突破/关键支撑/背景知识）
                    important_match = re.search(r'##\s*什么算重要\s*\n+(.+?)(?=\n##|\Z)', schema_text, re.DOTALL)
                    if important_match:
                        imp_text = important_match.group(1)
                        for m in re.finditer(r'\*\*(.+?)\*\*[：:]\s*(.+?)(?=\n-|\n\*\*|\Z)', imp_text, re.DOTALL):
                            cat_label = m.group(1).strip()  # 如"核心突破"
                            cat_desc = m.group(2).strip()[:40]
                            schema_categories.append((cat_label, cat_desc))
        except Exception:
            pass  # schema 读取失败不影响主流程
        
        # ── 关键词 overlap 匹配 schema 分类 ──
        if schema_categories:
            best_label = None
            best_score = 0
            for item in schema_categories:
                if isinstance(item, tuple):
                    label, desc = item
                    score = len(keywords & self._kw_set(desc))
                else:
                    label = item
                    score = len(keywords & self._kw_set(label))
                if score > best_score:
                    best_score = score
                    best_label = label
            
            if best_score >= 1 and best_label:
                return best_label[:8]
        
        # ── 回退：从概念名提取 ──
        zh_parts = re.findall(r'[\u4e00-\u9fa5]{2,}', concept_name)
        if zh_parts:
            best = max(zh_parts, key=len)
            return best[:6] if len(best) > 6 else best
        en_parts = re.findall(r'[A-Z][a-z]+', concept_name)
        if en_parts:
            return en_parts[0]
        return "核心概念"

    @staticmethod
    def _kw_set(text: str) -> set:
        """从文本提取关键词集合"""
        _stop = {'的','和','与','或','在','是','了','不','有','也','就','都','而','及',
                 '对','以','到','等','为','the','a','an','is','are','and','or','of','to','for'}
        words = set()
        for w in re.findall(r'[a-zA-Z]{3,}|[\u4e00-\u9fa5]', text):
            wl = w.lower()
            if wl not in _stop and len(wl) >= 2:
                words.add(wl)
        return words

    def _update_index_summaries(self, user_id: str, kb_name: str):
        """OKF: 为 index.md 中的链接添加一句话摘要。失败静默。"""
        if not schema_enabled():
            return
        try:
            s = get_storage()
            if USE_MINIO:
                from core.path_resolver import minio_index_key, minio_concepts_prefix
                idx_key = minio_index_key(user_id, kb_name)
                if not s.exists(idx_key):
                    return
                index_content = s.read_text(idx_key)
                prefix = minio_concepts_prefix(user_id, kb_name)
                concept_keys = s.list_keys(prefix)
            else:
                from tools.edit_tools import _resolve
                idx_path = _resolve("index.md")
                if not idx_path.exists():
                    return
                index_content = idx_path.read_text(encoding="utf-8")
                concepts_dir = _resolve("concepts")
                concept_keys = list(concepts_dir.glob("*.md")) if concepts_dir.exists() else []

            # 为每个 [[链接]] 尝试从对应文件中提取一句话摘要
            import re as _re
            links = _re.findall(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', index_content)
            if not links:
                return

            # 构建概念名 → 摘要的映射
            summary_map = {}
            for lk in links:
                norm = self._normalize_name(lk)
                # 查找对应文件
                if USE_MINIO:
                    for ck in concept_keys:
                        stem = ck.split("/")[-1].replace(".md", "")
                        if self._normalize_name(stem) == norm:
                            content = get_storage().read_text(ck)
                            abs_text = self._extract_abstract(content)
                            first_sentence = self._readable_summary(abs_text)
                            if first_sentence:
                                summary_map[lk] = first_sentence
                            break
                else:
                    for cf in concept_keys:
                        if self._normalize_name(cf.stem) == norm:
                            content = cf.read_text(encoding="utf-8")
                            abs_text = self._extract_abstract(content)
                            first_sentence = self._readable_summary(abs_text)
                            if first_sentence:
                                summary_map[lk] = first_sentence
                            break

            if not summary_map:
                return

            # 更新 index.md：在链接后追加摘要
            new_index = index_content
            for lk, summ in summary_map.items():
                # 只更新没有摘要的链接行
                pattern = _re.compile(rf'^(\s*-\s*\[\[{re.escape(lk)}[^\]]*\]\])\s*$', _re.MULTILINE)
                new_index = pattern.sub(rf'\1 — {summ}', new_index, count=1)

            # 写回
            if USE_MINIO:
                s.write_text(idx_key, new_index)
            else:
                idx_path = _resolve("index.md")
                idx_path.write_text(new_index, encoding="utf-8")

            print(f"  📝 [OKF] index.md 已添加 {len(summary_map)} 条摘要")
        except Exception as e:
            print(f"  ⚠️ [OKF] index 摘要更新失败（不影响主流程）: {e}")

    def run(self, input_source: str, kb_name: str = "", user_id: str = "", doc_name: str = "", pending_payloads: dict = None):
        """
        知识摄入入口。
        kb_name: 目标沙箱名称（通过参数传递，避免 os.environ 竞态）
        user_id: 用户 ID（用于路径隔离）
        doc_name: 原始文档名（MinIO 模式下传入，避免使用临时文件名）
        """
        # 在调用任何 _resolve 前，设置线程安全上下文
        set_context(user_id=user_id, kb_name=kb_name or "default", sub_dir="")

        # 早期终止检查：还没开始重活之前快速退出
        if user_id and kb_name and is_terminate_requested(user_id, kb_name):
            print(f"\n🛑 [IngestFlow] 收到终止信号，跳过 {Path(input_source).name}")
            return False  # 返回 False 表示被终止
        # 在调用任何 _resolve 前，设置线程安全上下文
        set_context(user_id=user_id, kb_name=kb_name or "default", sub_dir="")

        # ── Resume 快速路径标记 ──
        _pending = pending_payloads  # None = 正常模式，dict = resume 模式

        print("\n" + "=" * 60)
        print(f"🚀 [IngestFlow] 启动 Map-Reduce 引擎 | 沙箱: {kb_name} | 用户: {user_id}")

        # 设置文档名到上下文
        path = Path(input_source)
        if path.exists() and path.is_file():
            # ── 单文件模式 ──
            _doc = doc_name or path.stem
            set_context(user_id=user_id, kb_name=kb_name or "default", sub_dir="", doc_name=_doc)
            print(f"📄 目标语料：{_doc} ({path.stat().st_size} bytes)", flush=True)
            try:
                raw_text = extract_text(str(path))
            except Exception as e:
                print(f"❌ extract_text 失败: {type(e).__name__}: {e}", flush=True)
                raw_text = ""
            print(f"📝 提取文本: {len(raw_text)} 字符", flush=True)
            if not raw_text.strip():
                print("⚠️ 警告：提取出的文本为空！PDF 可能是扫描图片（需要 OCR）或文件损坏。", flush=True)
            chunk_size, overlap = self._adaptive_chunk_params(len(raw_text))
            chunks = chunk_text(raw_text, chunk_size=chunk_size, overlap=overlap)
            print(f"✂️ 自适应切片: chunk_size={chunk_size}, overlap={overlap} → {len(chunks)} 个知识块", flush=True)
        elif path.exists() and path.is_dir():
            # ── 目录模式：遍历所有文件，合并文本后切块 ──
            SUPPORTED_EXT = {".pdf", ".doc", ".docx", ".md", ".txt"}
            all_text = ""
            file_count = 0
            for file in sorted(path.iterdir()):
                if file.is_file() and file.suffix.lower() in SUPPORTED_EXT:
                    try:
                        text = extract_text(str(file))
                        if text.strip():
                            all_text += f"\n\n--- [{file.name}] ---\n\n" + text
                            file_count += 1
                            print(f"  📄 读取: {file.name} ({len(text)} 字符)")
                    except Exception as e:
                        print(f"  ⚠️ 跳过 {file.name}: {e}")
            if not all_text.strip():
                print("❌ 目录中没有可解析的文件")
                chunks = []
            else:
                print(f"📚 共读取 {file_count} 个文件 ({len(all_text)} 字符)")
                chunk_size, overlap = self._adaptive_chunk_params(len(all_text))
                chunks = chunk_text(all_text, chunk_size=chunk_size, overlap=overlap)
                print(f"✂️ 自适应切片: chunk_size={chunk_size}, overlap={overlap} → {len(chunks)} 个知识块")
        else:
            # 兜底：把 input_source 当原始文本
            chunk_size, overlap = self._adaptive_chunk_params(len(input_source))
            chunks = chunk_text(input_source, chunk_size=chunk_size, overlap=overlap)
            print(f"✂️ 自适应切片: chunk_size={chunk_size}, overlap={overlap} → {len(chunks)} 个知识块")

        # ==========================================
        # 🧬 PHASE 0: Schema 领域嗅探（可插拔）
        # ==========================================
        if schema_enabled() and chunks:
            print("\n" + "=" * 60)
            print("🧬 [Phase 0: Schema] 领域编译约定检查...")
            self._schema_content = self._load_or_infer_schema(user_id, kb_name, chunks[:2])
            if self._schema_content:
                # 用带 Schema 的 instructions 重建 Analyst
                self.analyst = WikiAnalyst(schema_content=self._schema_content)
                print("  ✅ Analyst 已注入领域编译指南")
            else:
                print("  ⏭️ 无 Schema，使用默认提取逻辑")

        # ==========================================
        # 🟢 PHASE 1: MAP (无锁绝对并发)
        # ==========================================
        map_lock = threading.Lock()
        self._skip_map = bool(_pending)  # resume skip
        self._all_entries = []
        self._all_conflicts = []
        self._all_gaps = []
        self._all_sources = []
        self._reduce_actions_log = []

        print("\n" + "=" * 60)
        print("⚡ [Phase 1: MAP] 启动侦察兵并发提取 (释放全部线程)...")

        map_results = []
        max_map_workers = min(len(chunks), 6) if chunks else 1
        print(f"  🔧 MAP 线程池: {max_map_workers} workers")
        with ThreadPoolExecutor(max_workers=max_map_workers) as executor:
            futures = {executor.submit(self._map_extract, chunk, i + 1): i for i, chunk in enumerate(chunks)}

            for future in as_completed(futures):
                try:
                    cid, chunk_text_val, res, status = future.result(timeout=210)
                except FuturesTimeoutError:
                    cid = futures.get(future, "?")
                    print(f"  ⏰ 线程 {cid} 外层超时，跳过")
                    continue

                if res:
                    with map_lock:
                        map_results.append((chunk_text_val, res))
                    print(f"  -> ✅ 线程 {cid} 提取完毕: {res.get('new_concepts')}")

        # ── MAP 结果统计 ──
        timeout_skips = sum(1 for _, res in map_results if res and res.get("summary", "").startswith("(LLM 超时"))
        total_concepts_raw = sum(len(res.get("new_concepts", [])) for _, res in map_results if res)
        print(f"  📊 MAP 完成: {len(map_results)}/{len(chunks)} 块成功, 提取 {total_concepts_raw} 个概念, {len(chunks) - len(map_results)} 块空/超时/失败")
        if timeout_skips:
            print(f"  ⚠️ 其中 {timeout_skips} 块因 LLM 超时被跳过")

        # ── Schema: 聚合 MAP 阶段的判断信息 + 来源追溯 ──
        self._all_sources = []  # OKF: 收集本轮 ingest 的所有来源名称
        if schema_enabled() and map_results:
            for _, res in map_results:
                if res:
                    entries = res.get("entries")
                    if entries:
                        for e in entries:
                            if isinstance(e, dict):
                                self._all_entries.append(e)
                            elif hasattr(e, 'model_dump'):
                                self._all_entries.append(e.model_dump())
                    conflicts = res.get("conflicts")
                    if conflicts:
                        self._all_conflicts.extend(conflicts)
                    gaps = res.get("gaps")
                    if gaps:
                        self._all_gaps.extend(gaps)
                    # OKF: 收集来源
                    src = res.get("source")
                    if src and src not in self._all_sources:
                        self._all_sources.append(src)
            if self._all_entries:
                print(f"  🧠 [Schema] 聚合判断: {len(self._all_entries)} 条目, {len(self._all_conflicts)} 矛盾, {len(self._all_gaps)} 缺口")
            if self._all_sources:
                print(f"  📚 [OKF] 来源: {', '.join(self._all_sources)}")

        # ==========================================
        # 🟡 PHASE 2: SHUFFLE (内存级同义词聚类)
        # ==========================================
        print("\n" + "=" * 60)
        print("🔀 [Phase 2: SHUFFLE] 正在将碎片知识按概念重新洗牌聚类 (启动双语解构引擎)...")

        # 空词黑名单：纯中文单独出现时大概率是泛化概念（"意义""背景"等）
        ZH_STOPWORDS = {"意义", "影响", "作用", "价值", "背景", "历史", "发展",
                        "反思", "动机", "投资", "合作", "素养", "民主化", "采用",
                        "学习", "整合", "协作", "伦理", "责任", "导师", "职业"}

        concept_payloads = {}
        for chunk_text_val, res in map_results:
            concepts = res.get("new_concepts", [])
            summary = res.get("summary", "")

            for raw_c in concepts:
                # 尝试剥离 "English (中文)" 格式
                match = re.match(r'^(.*?)\s*[\(（](.*?)[\)）]', raw_c)
                if match:
                    en_key = match.group(1).strip()
                    zh_alias = match.group(2).strip()
                    full_display = f"{en_key} ({zh_alias})"
                else:
                    en_key = raw_c.strip()
                    zh_alias = ""
                    full_display = en_key

                # 过滤明显不是概念的超长垃圾数据
                if len(en_key.split()) > 4 or len(en_key) > 25:
                    continue

                # 空词黑名单：纯中文且命中停用词 → 丢弃
                if not match and en_key in ZH_STOPWORDS:
                    continue

                norm_c = self._normalize_name(en_key)
                if not norm_c or len(norm_c) < 2:
                    continue

                if norm_c not in concept_payloads:
                    concept_payloads[norm_c] = {
                        "primary_key": en_key,
                        "display_name": full_display,
                        "aliases": set(),
                        "texts": [],
                        "summaries": []
                    }

                if zh_alias:
                    concept_payloads[norm_c]["aliases"].add(zh_alias)

                concept_payloads[norm_c]["texts"].append(chunk_text_val)
                concept_payloads[norm_c]["summaries"].append(summary)

        # 📉 SHUFFLE 过滤：≥1 即可通过（质量关已由 MAP 负责），保留所有概念
        #    极端安全阀：超过上限时按频次截断（正常情况不会触发）
        MAX_CONCEPTS_PER_INGEST = 60
        before_filter = len(concept_payloads)
        if before_filter > MAX_CONCEPTS_PER_INGEST:
            sorted_concepts = sorted(
                concept_payloads.items(),
                key=lambda x: len(x[1]["texts"]),
                reverse=True
            )
            concept_payloads = dict(sorted_concepts[:MAX_CONCEPTS_PER_INGEST])
            capped = before_filter - len(concept_payloads)
            print(f"  🗑️ 安全阀截断: {capped} 个（超过 {MAX_CONCEPTS_PER_INGEST} 上限）")
        else:
            print(f"  ✅ SHUFFLE 通过: {before_filter} 个概念进入 REDUCE")

        # 保存 SHUFFLE 结果到检查点缓存（供 resume 跳过 MAP+SHUFFLE）
        if user_id and kb_name and not _pending:
            _fn = doc_name or (path.name if path.exists() else str(input_source))
            save_shuffle_result(user_id, kb_name, _fn, concept_payloads)

        # Resume 覆盖：如果有 pending_payloads，替换 SHUFFLE 的空结果
        if _pending is not None:
            concept_payloads = _pending
            print(f"  📦 [RESUME] 使用缓存的 SHUFFLE 结果: {len(concept_payloads)} 个概念")

        # ==========================================
        # 🔴 PHASE 3: REDUCE (串行概念融合)
        # ==========================================
        print("\n" + "=" * 60)
        total_concepts = len(concept_payloads)
        print(f"🧠 [Phase 3: REDUCE] 惊人降维！发现 {total_concepts} 个独立核心概念。")

        # 🔧 P0-1: 预构建概念索引（O(N) 一次性扫描，后续查找 O(1)）
        self._build_concept_index()

        # 🏛️ 构建 Canonical Registry（SHUFFLE 概念 + KB 已有文件 = 权威全集）
        self._canonical_registry = self._build_canonical_registry(concept_payloads)

        # 🔧 P0-2: 清空缓存（新批次，防止旧数据干扰）
        self._file_cache.clear()
        self._context_cache.clear()

        t_reduce_start = time.time()

        skipped_count = 0
        error_count = 0
        checkpoint_count = 0  # 从检查点跳过的概念数
        terminated = False
        reduce_pool = ThreadPoolExecutor(max_workers=1)

        for seq, (norm_c, payload) in enumerate(concept_payloads.items(), 1):
            display_name = payload["display_name"]

            # ── 终止检查（每个概念开始前）──
            if user_id and kb_name and is_terminate_requested(user_id, kb_name):
                print(f"\n🛑 [REDUCE] 收到终止信号，在概念 {seq}/{total_concepts} 前停止")
                terminated = True
                break

            # ── 检查点跳过（Resume 时已处理的概念不再重复调 LLM）──
            if user_id and kb_name and is_concept_done(user_id, kb_name, norm_c):
                checkpoint_count += 1
                print(f"  ⏩ [{seq}/{total_concepts}] [{display_name}] 已在检查点中，跳过")
                continue

            print(f"  🔄 [融合 {seq}/{total_concepts}] 目标概念: [{display_name}]")
            t0 = time.time()

            combined_text = "\n\n... (接上文补充资料) ...\n\n".join(payload["texts"])

            # Token 熔断保护
            MAX_CHARS = 20000
            if len(combined_text) > MAX_CHARS:
                print(f"  -> ⚠️ [{display_name}] 过长 ({len(combined_text)} 字符)，已截断")
                combined_text = combined_text[:MAX_CHARS] + "\n\n... [数据过长，出于系统上下文保护已截断，请基于以上核心信息进行融合] ..."

            combined_summary = "\n".join(payload["summaries"])
            existing_context = self._fetch_local_context([display_name])

            # ── 可中断的 LLM 调用 ──
            _merge_uid, _merge_kb = user_id, kb_name
            _merge_entries = self._all_entries or None
            _merge_conflicts = self._all_conflicts or None
            _merge_gaps = self._all_gaps or None
            _merge_sources = self._all_sources or []
            def _do_merge():
                set_context(user_id=_merge_uid, kb_name=_merge_kb or "default", sub_dir="")
                # OKF: 设置来源追溯上下文，供 create_page 自动注入 frontmatter
                from tools.edit_tools import set_okf_context
                set_okf_context(page_type="concept", source=_merge_sources)
                return WikiEditor().merge(
                    raw_text=combined_text,
                    analyst_summary=combined_summary,
                    existing_context=existing_context,
                    entries=_merge_entries,
                    conflicts=_merge_conflicts,
                    gaps=_merge_gaps,
                    canonical_names=list(self._canonical_registry.values()),
                    target_concept=display_name,
                )
            # 硬超时：单个概念融合最多 MERGE_HARD_TIMEOUT 秒（含 Editor 内部重试）
            MERGE_HARD_TIMEOUT = 480
            try:
                merge_future = reduce_pool.submit(_do_merge)
                merge_start = time.time()
                merge_timed_out = False
                while not merge_future.done():
                    if user_id and kb_name and is_terminate_requested(user_id, kb_name):
                        terminated = True
                        break
                    if time.time() - merge_start > MERGE_HARD_TIMEOUT:
                        merge_timed_out = True
                        break
                    try:
                        merge_future.result(timeout=0.5)
                    except FuturesTimeoutError:
                        continue
                if terminated:
                    # ── 优雅终止：如果当前融合已完成，先保存结果再退出 ──
                    if merge_future.done():
                        try:
                            report = merge_future.result(timeout=0)
                            if report and report.get("actions"):
                                self.writer.execute(report)
                                if user_id and kb_name:
                                    mark_concept_done(user_id, kb_name, norm_c)
                                elapsed = time.time() - t0
                                print(f"  -> ✅ [{display_name}] 融合完毕 ({elapsed:.1f}s)（终止前抢救完成）")
                        except Exception as e:
                            print(f"  -> ⚠️ [{display_name}] 终止时保存结果失败: {e}")
                    reduce_pool.shutdown(wait=False)
                    break
                if merge_timed_out:
                    print(f"  -> ⏰ [{display_name}] 外层硬超时 ({MERGE_HARD_TIMEOUT}s)，跳过")
                    error_count += 1
                    if user_id and kb_name:
                        mark_concept_done(user_id, kb_name, norm_c)
                    continue
                report = merge_future.result()

                if report and report.get("actions"):
                    self.writer.execute(report, canonical_registry=self._canonical_registry, target_concept=display_name)
                    # OKF: 记录操作摘要供 log.md 使用
                    if schema_enabled():
                        for act in report["actions"]:
                            act_type = act.get("type", "")
                            act_file = act.get("file", "")
                            if act_type == "create":
                                self._reduce_actions_log.append(f"create: {act_file}")
                            elif act_type == "edit":
                                self._reduce_actions_log.append(f"edit: {act_file}")
                            elif act_type == "append_link":
                                pass  # index 更新不记入
                            elif act_type == "extract_moc":
                                self._reduce_actions_log.append(f"extract_moc: {act_file}")
                else:
                    print(f"  -> 🔔 主编裁定: [{display_name}] 无实质增量信息，跳过写盘。")
                    skipped_count += 1

                # ── 保存检查点（融合成功后立即记录，从待处理列表移除）──
                if user_id and kb_name:
                    mark_concept_done(user_id, kb_name, norm_c)

                # ── 系统级 index.md 分类保障（幂等，不依赖 LLM append_link）──
                if user_id and kb_name:
                    self._categorize_into_index(display_name, user_id, kb_name)

                elapsed = time.time() - t0
                print(f"  -> ✅ [{display_name}] 融合完毕 ({elapsed:.1f}s)")

            except Exception as e:
                elapsed = time.time() - t0
                error_count += 1
                print(f"  -> ❌ 合并 [{display_name}] 时发生致命错误: {e}")
        t_total = time.time() - t_reduce_start
        print("\n" + "=" * 60)
        stats_parts = [f"REDUCE 耗时: {t_total:.1f}s"]
        if checkpoint_count:
            stats_parts.append(f"检查点跳过: {checkpoint_count}")
        if skipped_count:
            stats_parts.append(f"无增量: {skipped_count}")
        if error_count:
            stats_parts.append(f"失败: {error_count}")
        if terminated:
            stats_parts.append("⚠️ 用户终止")
        print(f"✅ [IngestFlow] 摄入完毕 | {' | '.join(stats_parts)} | 知识图谱已延展！")

        # ── Schema: 完成后追加 log.md + 生成建议 + index 摘要（可插拔）──
        if schema_enabled() and not terminated:
            _doc = doc_name or (path.stem if path.exists() else str(input_source))
            map_count = len(map_results)
            self._append_log(
                user_id, kb_name, _doc,
                map_count=map_count,
                shuffle_count=total_concepts,
                reduce_count=total_concepts - skipped_count - error_count,
                skip_count=skipped_count,
                error_count=error_count,
                actions_log=self._reduce_actions_log,
                conflicts=self._all_conflicts if self._all_conflicts else None,
            )
            self._update_index_summaries(user_id, kb_name)
            self._maybe_generate_suggestions(user_id, kb_name)

        # 返回是否被终止（供外层循环判断）
        return not terminated


if __name__ == "__main__":
    # 自动定位项目根目录（支持从项目根或 workflows/ 子目录运行）
    _script_dir = Path(__file__).resolve().parent
    _project_root = _script_dir.parent if _script_dir.name == "workflows" else _script_dir
    raw_dir = _project_root / "data" / "raw"

    if not raw_dir.exists():
        raw_dir.mkdir(parents=True, exist_ok=True)
        print(f"⚠️ 找不到 {raw_dir} 目录，已为您自动创建。请先将数据放入该目录！")
        sys.exit(0)

    # 读取 raw/ 下的所有文件夹（作为沙箱）和 PDF
    items = [p for p in raw_dir.iterdir() if p.is_dir() or p.suffix.lower() == '.pdf']

    if not items:
        print(f"📭 {raw_dir} 目录下空空如也，请先放入包含论文或文档的文件夹。")
        sys.exit(0)

    print("\n" + "=" * 50)
    print("🤖 欢迎使用 LLM-Wiki 本地自动化摄入系统")
    print("=" * 50)
    print("请选择要处理的知识源：\n")

    for i, item in enumerate(items, 1):
        icon = "🗂️" if item.is_dir() else "📄"
        print(f"  [{i}] {icon} {item.name}")
    print("\n" + "=" * 50)

    try:
        choice = input("👉 请输入对应编号 (按 Ctrl+C 退出): ").strip()
        choice_idx = int(choice) - 1
        if choice_idx < 0 or choice_idx >= len(items):
            raise ValueError
    except (ValueError, IndexError):
        print("❌ 输入无效，请输入正确的数字编号。")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n👋 已取消操作。")
        sys.exit(0)

    input_target = items[choice_idx]
    flow = IngestFlow()

    # 💡 核心逻辑适配：如果选择了文件夹，则文件夹名即为专属沙箱名
    if input_target.is_dir():
        files = list(input_target.rglob("*.pdf"))
        print(f"📂 开始深度扫描沙箱文件夹 [{input_target.name}]，共发现 {len(files)} 份语料。")

        # 锁定沙箱名
        kb_name = input_target.stem
        set_context(kb_name=kb_name)
        print(f"📁 知识流向: 锁定专属沙箱 -> [data/wiki/{kb_name}/]")

        for idx, file_path in enumerate(files, 1):
            set_context(kb_name=kb_name, doc_name=file_path.stem)

            print("\n" + "-" * 50)
            print(f"🚀 [批量进度 {idx}/{len(files)}] 正在解析: {file_path.name}")
            flow.run(str(file_path), kb_name=kb_name)

        print(f"\n✅✅ 沙箱 [{kb_name}] 的批量提炼任务已全部完成！")

    # 如果选择了单个文件，则自动以文件名开辟新沙箱
    elif input_target.is_file():
        kb_name = input_target.stem
        set_context(kb_name=kb_name, doc_name=input_target.stem)

        print(f"\n📁 知识流向: 为该文件单独开辟沙箱 -> [data/wiki/{kb_name}/]")
        flow.run(str(input_target), kb_name=kb_name)