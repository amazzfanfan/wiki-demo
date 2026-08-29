"""
autofill_flow.py - 幽灵节点实例化引擎 (知识黑洞自动填补)
"""
import os
import re
import json
import asyncio
from pathlib import Path
from collections import Counter

from agents.wiki_editor import WikiEditor
from agents.wiki_writer import WikiWriter
from tools.edit_tools import _resolve, set_context
from core.path_resolver import get_wiki_root, USE_MINIO
from core.llm_factory import set_user_context


class AutoFillFlow:
    def __init__(self, threshold: int = 5):
        """
        :param threshold: 触发自动填补的最小入度(默认被提及 5 次及以上就触发)
        """
        self.threshold = threshold
        self.writer = WikiWriter()

    def _normalize_name(self, text: str) -> str:
        if not text: return ""
        return re.sub(r'[^a-zA-Z0-9\u4e00-\u9fa5]', '', text).lower()

    async def stream_run(self, kb_name: str, user_id: str = ""):
        """
        🚀 Web 端专用的真空节点流式实例化引擎
        """
        def format_log(msg: str):
            return f"data: {json.dumps({'type': 'log', 'content': msg})}\n\n"

        yield format_log(f"🕳️ [AutoFill Flow] 启动知识黑洞探测器 | 🎯 锁定目标沙箱: {kb_name}")
        await asyncio.sleep(0.01)

        # 设置线程安全上下文(替代 os.environ,解决并发竞态)
        set_user_context(user_id=user_id)  # LLM API Key 路由
        set_context(user_id=user_id, kb_name=kb_name, sub_dir="")

        if USE_MINIO:
            # ═══════════════════════════════════════════
            # MinIO 模式
            # ═══════════════════════════════════════════
            from core.storage import get_storage
            from core.path_resolver import minio_concepts_prefix, minio_concept_key

            s = get_storage()
            prefix = minio_concepts_prefix(user_id, kb_name)
            all_keys = s.list_keys(prefix)
            concept_keys = [k for k in all_keys if k.endswith(".md") 
                           and not k.endswith("/index.md") 
                           and "/mocs/" not in k]

            if not concept_keys:
                # Check if raw files exist (sandbox might be completely empty)
                from core.path_resolver import minio_raw_prefix
                raw_prefix = minio_raw_prefix(user_id, kb_name)
                raw_keys = s.list_keys(raw_prefix)
                if not raw_keys:
                    yield format_log(f"⚠️ 沙箱 [{kb_name}] 是空的，请先上传文档并执行摄入，生成知识图谱后再填补黑洞。")
                else:
                    yield format_log(f"⚠️ 沙箱 [{kb_name}] 有原始文档但尚未摄入，请先执行摄入生成知识图谱。")
                return

            # 1. 扫描与入度统计
            link_counter = Counter()
            backlinks_context = {}

            yield format_log("📡 正在全盘解构物理文件并精确提取双向引用权重...")
            await asyncio.sleep(0.01)

            # 构建文件名索引
            name_to_key = {}  # clean_name -> key
            for key in concept_keys:
                name = key.split("/")[-1].replace(".md", "")
                name_to_key[name] = key

            for key in concept_keys:
                name = key.split("/")[-1].replace(".md", "")
                try:
                    content = s.read_text(key)
                except Exception:
                    continue
                links = re.findall(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', content)
                for link in links:
                    clean_link = link.strip()
                    if not clean_link: continue
                    link_counter[clean_link] += 1
                    if clean_link not in backlinks_context:
                        backlinks_context[clean_link] = []
                    if name not in backlinks_context[clean_link]:
                        backlinks_context[clean_link].append(name)

            # 2. 过滤、锁定与【偷天换日】底层链接修复
            target_ghosts = []
            existing_names = list(name_to_key.keys())

            def _get_real_target_if_exists_minio(ghost_name: str, names: list) -> str:
                def _get_aliases(text: str) -> set:
                    aliases = set()
                    clean_text = text.lower().replace("-", "").replace("_", "").replace(" ", "")
                    if clean_text: aliases.add(clean_text)
                    match = re.match(r'^(.*?)\s*[\(（](.*?)[\)）]', text)
                    if match:
                        part1 = match.group(1).lower().replace("-", "").replace("_", "").replace(" ", "")
                        part2 = match.group(2).lower().replace("-", "").replace("_", "").replace(" ", "")
                        if part1: aliases.add(part1)
                        if part2: aliases.add(part2)
                    return aliases
                ghost_aliases = _get_aliases(ghost_name)
                for n in names:
                    if ghost_aliases & _get_aliases(n):
                        return n
                return ""

            yield format_log("🛠️ [自愈系统] 正在清理异名同义假空节点并自动重定向物理指针...")
            await asyncio.sleep(0.01)

            for link, count in link_counter.items():
                real_target = _get_real_target_if_exists_minio(link, existing_names)
                if real_target:
                    if link != real_target:
                        yield format_log(f"  -> 🔀 [偷天换日] 修复假空节点 [{link}] -> 真实归宿 [{real_target}]")
                        await asyncio.sleep(0.01)
                        for source_file in backlinks_context[link]:
                            source_key = name_to_key.get(source_file)
                            if source_key:
                                try:
                                    content = s.read_text(source_key)
                                    pattern = re.compile(rf'\[\[{re.escape(link)}(?:\|([^\]]+))?\]\]')
                                    new_content = pattern.sub(lambda m: f"[[{real_target}|{m.group(1) or link}]]", content)
                                    if new_content != content:
                                        s.write_text(source_key, new_content)
                                except Exception:
                                    pass
                else:
                    if count >= self.threshold:
                        target_ghosts.append((link, count))

            target_ghosts.sort(key=lambda x: x[1], reverse=True)

            if not target_ghosts:
                yield format_log("✅ 经脉调理完毕：当前图谱极其健康，未发现任何触发阈值的真空知识黑洞。")
                return

            yield format_log(f"🎯 警报！全库共探测到 {len(target_ghosts)} 个严重高频真空节点 (被引用 >= {self.threshold}次)：")
            await asyncio.sleep(0.01)

            # 3. 逐个召唤主编进行物理填补
            yield format_log("🪄 正在物理启动熔炉，呼叫 WikiEditor / WikiWriter 智能体合成真空实体...")
            await asyncio.sleep(0.01)

            filled_nodes = []  # 记录成功填补的节点名

            for node, count in target_ghosts:
                yield format_log(f"✨ [实例化中] 正在驱动大模型提取上下文并合成新实体: [{node}]")
                await asyncio.sleep(0.01)

                source_docs_str = ""
                for source_file in backlinks_context[node][:3]:
                    source_key = name_to_key.get(source_file)
                    if source_key:
                        try:
                            snippet = s.read_text(source_key)[:600]
                            source_docs_str += f"\n=== {source_file} (提及了该概念) ===\n{snippet}...\n"
                        except Exception:
                            pass

                prompt_text = (
                    f"你是一个知识图谱修复专家。目前系统内有一个核心概念【{node}】被多次引用，"
                    f"但其独立条目缺失。请基于你的通用知识，以及下面提供的一些本地关联文档的上下文，"
                    f"直接生成关于【{node}】的详细百科解释。\n\n"
                    f"关联上下文参考：\n{source_docs_str}"
                )

                try:
                    fresh_editor = WikiEditor()
                    # 同步 LLM 调用放入线程池，避免阻塞事件循环
                    report = await asyncio.to_thread(
                        fresh_editor.merge,
                        raw_text=prompt_text,
                        analyst_summary=f"这是一个高频核心实体，必须创建一个全新的详细词条：{node}",
                        existing_context=f"=== concepts/{node}.md ===\n(全新概念，待你创建)\n"
                    )

                    if report and report.get("actions"):
                        # 快照：填补前的概念文件列表
                        _before_keys = set(k for k in s.list_keys(prefix) if k.endswith(".md"))
                        
                        writer_results = self.writer.execute(report)
                        
                        # 快照：填补后找出新建的文件
                        _after_keys = set(k for k in s.list_keys(prefix) if k.endswith(".md"))
                        _new_keys = _after_keys - _before_keys
                        
                        # 如果快照没捕捉到（名字相同但内容重建），回退到 node.md
                        if not _new_keys:
                            fallback_key = minio_concept_key(user_id, kb_name, f"{node}.md")
                            if s.exists(fallback_key):
                                _new_keys = {fallback_key}
                        
                        # 给新生成的实体打上"待审批草稿"烙印
                        DRAFT_TAG = "<" + "!-- AUTOFILL_DRAFT --" + ">"
                        tagged_count = 0
                        for new_key in _new_keys:
                            if DRAFT_TAG not in s.read_text(new_key):
                                old_content = s.read_text(new_key)
                                s.write_text(new_key, DRAFT_TAG + "\n" + old_content)
                                tagged_count += 1
                        
                        if tagged_count > 0:
                            names = [k.split("/")[-1] for k in _new_keys]
                            yield format_log(f"  -> 📝 [物理落盘] 自动生成草稿成功，已送入 Inbox 待审: {', '.join(names)}")
                            filled_nodes.append(node)
                        else:
                            yield format_log(f"  -> ⚠️ Writer 执行完成但未能创建新文件（可能内容被拦截）: [{node}]")
                            if writer_results:
                                for wr in writer_results[:3]:
                                    yield format_log(f"     └─ {wr}")
                    else:
                        yield format_log(f"  -> ⏭️ 智能主编拒绝生成词条: [{node}]")
                    await asyncio.sleep(0.01)
                except Exception as e:
                    yield format_log(f"  -> ❌ 填补节点 [{node}] 发生未知阻断: {e}")

            # 📝 写入 log.md（OKF 兼容）
            if filled_nodes:
                try:
                    from core.schema_engine import is_enabled as schema_enabled, build_log_entry
                    if schema_enabled():
                        from core.path_resolver import minio_log_key
                        entry = build_log_entry(
                            "autofill", "知识黑洞填补",
                            details={
                                "filled": f"{len(filled_nodes)} 个",
                                "nodes": ", ".join(filled_nodes),
                                "threshold": str(self.threshold),
                            }
                        )
                        log_key = minio_log_key(user_id, kb_name)
                        existing_log = s.read_text(log_key) if s.exists(log_key) else "# 活动日志\n"
                        s.write_text(log_key, existing_log + entry)
                except Exception as e:
                    yield format_log(f"  ⚠️ log.md 写入失败（不影响结果）: {e}")

            yield format_log("✅ [AutoFill Flow] 真空幽灵实体全部实例化完毕，图谱暗物质已清除！")
            return

        # ═══════════════════════════════════════════
        # 本地模式（保持原样）
        # ═══════════════════════════════════════════
        concepts_dir = get_wiki_root(user_id) / kb_name / "concepts"
        if not concepts_dir.exists():
            # Check if raw files exist
            raw_dir = get_wiki_root(user_id) / kb_name / "raw" if user_id else Path("data/raw") / kb_name
            if not raw_dir.exists() or not list(raw_dir.glob("*")):
                yield format_log(f"⚠️ 沙箱 [{kb_name}] 是空的，请先上传文档并执行摄入，生成知识图谱后再填补黑洞。")
            else:
                yield format_log(f"⚠️ 沙箱 [{kb_name}] 有原始文档但尚未摄入，请先执行摄入生成知识图谱。")
            return

        # ==========================================
        # 1. 扫描与入度统计
        # ==========================================
        link_counter = Counter()
        backlinks_context = {}  # 记录谁引用了它，用于给大模型提供溯源上下文

        yield format_log("📡 正在全盘解构物理文件并精确提取双向引用权重...")
        await asyncio.sleep(0.01)

        for file_path in concepts_dir.glob("*.md"):
            content = file_path.read_text(encoding="utf-8")
            links = re.findall(r'\[\[([^\]|]+)(?:\|[^\]]+)?\]\]', content)

            for link in links:
                clean_link = link.strip()
                if not clean_link: continue

                link_counter[clean_link] += 1
                if clean_link not in backlinks_context:
                    backlinks_context[clean_link] = []
                if file_path.stem not in backlinks_context[clean_link]:
                    backlinks_context[clean_link].append(file_path.stem)

        # ==========================================
        # 2. 过滤、锁定与【偷天换日】底层链接修复
        # ==========================================
        target_ghosts = []
        existing_files = list(concepts_dir.glob("*.md"))

        def _get_real_target_if_exists(ghost_name: str, files: list) -> str:
            """基于括号解构的别名集合交集法"""
            def _get_aliases(text: str) -> set:
                aliases = set()
                clean_text = text.lower().replace("-", "").replace("_", "").replace(" ", "")
                if clean_text: aliases.add(clean_text)
                match = re.match(r'^(.*?)\s*[\(（](.*?)[\)）]', text)
                if match:
                    part1 = match.group(1).lower().replace("-", "").replace("_", "").replace(" ", "")
                    part2 = match.group(2).lower().replace("-", "").replace("_", "").replace(" ", "")
                    if part1: aliases.add(part1)
                    if part2: aliases.add(part2)
                return aliases

            ghost_aliases = _get_aliases(ghost_name)
            for ex_file in files:
                ex_aliases = _get_aliases(ex_file.stem)
                if ghost_aliases & ex_aliases:
                    return ex_file.stem
            return ""

        yield format_log("🛠️ [自愈系统] 正在清理异名同义假空节点并自动重定向物理指针...")
        await asyncio.sleep(0.01)

        for link, count in link_counter.items():
            real_target = _get_real_target_if_exists(link, existing_files)

            if real_target:
                if link != real_target:
                    yield format_log(f"  -> 🔀 [偷天换日] 修复假空节点 [{link}] -> 真实归宿 [{real_target}]")
                    await asyncio.sleep(0.01)
                    for source_file in backlinks_context[link]:
                        source_path = concepts_dir / f"{source_file}.md"
                        if source_path.exists():
                            content = source_path.read_text(encoding="utf-8")
                            pattern = re.compile(rf'\[\[{re.escape(link)}(?:\|([^\]]+))?\]\]')
                            new_content = pattern.sub(lambda m: f"[[{real_target}|{m.group(1) or link}]]", content)

                            if new_content != content:
                                source_path.write_text(new_content, encoding="utf-8")
            else:
                if count >= self.threshold:
                    target_ghosts.append((link, count))

        target_ghosts.sort(key=lambda x: x[1], reverse=True)

        if not target_ghosts:
            yield format_log("✅ 经脉调理完毕：当前图谱极其健康，未发现任何触发阈值的真空知识黑洞。")
            return

        yield format_log(f"🎯 警报！全库共探测到 {len(target_ghosts)} 个严重高频真空节点 (被引用 >= {self.threshold}次)：")
        await asyncio.sleep(0.01)

        # ==========================================
        # 3. 逐个召唤主编进行物理填补
        # ==========================================
        yield format_log("🪄 正在物理启动熔炉，呼叫 WikiEditor / WikiWriter 智能体合成真空实体...")
        await asyncio.sleep(0.01)

        filled_nodes = []  # 记录成功填补的节点名

        for node, count in target_ghosts:
            yield format_log(f"✨ [实例化中] 正在驱动大模型提取上下文并合成新实体: [{node}]")
            await asyncio.sleep(0.01)

            source_docs_str = ""
            for source_file in backlinks_context[node][:3]:
                source_path = concepts_dir / f"{source_file}.md"
                if source_path.exists():
                    snippet = source_path.read_text(encoding='utf-8')[:600]
                    source_docs_str += f"\n=== {source_file} (提及了该概念) ===\n{snippet}...\n"

            prompt_text = (
                f"你是一个知识图谱修复专家。目前系统内有一个核心概念【{node}】被多次引用，"
                f"但其独立条目缺失。请基于你的通用知识，以及下面提供的一些本地关联文档的上下文，"
                f"直接生成关于【{node}】的详细百科解释。\n\n"
                f"关联上下文参考：\n{source_docs_str}"
            )

            try:
                fresh_editor = WikiEditor()
                # 同步 LLM 调用放入线程池，避免阻塞事件循环
                report = await asyncio.to_thread(
                    fresh_editor.merge,
                    raw_text=prompt_text,
                    analyst_summary=f"这是一个高频核心实体，必须创建一个全新的详细词条：{node}",
                    existing_context=f"=== concepts/{node}.md ===\n(全新概念，待你创建)\n"
                )

                if report and report.get("actions"):
                    # 快照：填补前的概念文件列表
                    _before_files = set(f.stem for f in concepts_dir.glob("*.md"))
                    
                    writer_results = self.writer.execute(report)
                    
                    # 快照：填补后找出新建的文件
                    _after_files = set(f.stem for f in concepts_dir.glob("*.md"))
                    _new_stems = _after_files - _before_files
                    
                    # 回退：如果快照没捕捉到
                    if not _new_stems:
                        fallback = concepts_dir / f"{node}.md"
                        if fallback.exists():
                            _new_stems = {node}
                    
                    # 给新生成的实体打上"待审批草稿"烙印
                    DRAFT_TAG = "<" + "!-- AUTOFILL_DRAFT --" + ">"
                    tagged_count = 0
                    for stem in _new_stems:
                        target_file = concepts_dir / f"{stem}.md"
                        if target_file.exists():
                            old_content = target_file.read_text(encoding="utf-8")
                            if DRAFT_TAG not in old_content:
                                target_file.write_text(DRAFT_TAG + "\n" + old_content, encoding="utf-8")
                                tagged_count += 1
                    
                    if tagged_count > 0:
                        yield format_log(f"  -> 📝 [物理落盘] 自动生成草稿成功，已送入 Inbox 待审: {', '.join(s+'.md' for s in _new_stems)}")
                        filled_nodes.append(node)
                    else:
                        yield format_log(f"  -> ⚠️ Writer 执行完成但未能创建新文件（可能内容被拦截）: [{node}]")
                        if writer_results:
                            for wr in writer_results[:3]:
                                yield format_log(f"     └─ {wr}")
                else:
                    yield format_log(f"  -> ⏭️ 智能主编拒绝生成词条: [{node}]")
                await asyncio.sleep(0.01)
            except Exception as e:
                yield format_log(f"  -> ❌ 填补节点 [{node}] 发生未知阻断: {e}")

        # 📝 写入 log.md（OKF 兼容）
        if filled_nodes:
            try:
                from core.schema_engine import is_enabled as schema_enabled, build_log_entry
                if schema_enabled():
                    from core.path_resolver import get_log_path
                    entry = build_log_entry(
                        "autofill", "知识黑洞填补",
                        details={
                            "filled": f"{len(filled_nodes)} 个",
                            "nodes": ", ".join(filled_nodes),
                            "threshold": str(self.threshold),
                        }
                    )
                    log_path = get_log_path(user_id, kb_name)
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    existing_log = log_path.read_text(encoding="utf-8") if log_path.exists() else "# 活动日志\n"
                    log_path.write_text(existing_log + entry, encoding="utf-8")
            except Exception as e:
                yield format_log(f"  ⚠️ log.md 写入失败（不影响结果）: {e}")

        yield format_log("✅ [AutoFill Flow] 真空幽灵实体全部实例化完毕，图谱暗物质已清除！")

    def run(self):
        """保留单机终端调试脚本兼容性"""
        wiki_dir = Path(__file__).resolve().parent.parent / "data" / "wiki"
        if not wiki_dir.exists():
            return
        kbs = [p for p in wiki_dir.iterdir() if p.is_dir()]
        if not kbs: return
        print("\n📂 请选择本地沙箱:")
        for i, kb in enumerate(kbs, 1):
            print(f"  [{i}] {kb.name}")
        choice = input("👉 输入编号: ").strip()
        selected_kb = kbs[int(choice) - 1].name

        async def run_cli():
            async for log in self.stream_run(selected_kb):
                clean_line = log.replace("data: ", "").strip()
                if clean_line:
                    try:
                        print(json.loads(clean_line).get("content", ""))
                    except: pass
        asyncio.run(run_cli())


if __name__ == "__main__":
    flow = AutoFillFlow(threshold=5)
    flow.run()