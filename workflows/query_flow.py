"""
workflows/query_flow.py — 查询流水线 (v0.2 用户级隔离版)
"""
import sys
import re
import difflib
from pathlib import Path
import json
import asyncio

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from tools.search_tools import search_web_text, search_multimodal_image
from agents.wiki_query import WikiRouter, WikiResponder
from core.path_resolver import get_wiki_root, list_workspaces, USE_MINIO


class QueryFlow:
    def __init__(self, user_id: str = ""):
        self.user_id = user_id
        self.router = WikiRouter()
        self.responder = WikiResponder()
        self.wiki_root = get_wiki_root(user_id)

    def _get_workspace_list(self) -> list:
        return list_workspaces(self.user_id)

    def _read_specific_map(self, workspace_name: str) -> str:
        if USE_MINIO:
            from core.storage import get_storage
            from core.path_resolver import minio_index_key
            s = get_storage()
            key = minio_index_key(self.user_id, workspace_name)
            if s.exists(key):
                return s.read_text(key)
            return "该工作区暂无导航地图。"
        # 本地模式
        map_path = self.wiki_root / workspace_name / "index.md"
        if map_path.exists():
            return map_path.read_text(encoding="utf-8")
        return "该工作区暂无导航地图。"

    def _read_local_concepts(self, workspace_name: str, concepts: list) -> str:
        """在选定的工作区内提取特定概念（双向拆解 + 别名雷达网 + difflib 容错）"""
        context = ""

        if USE_MINIO:
            from core.storage import get_storage
            from core.path_resolver import minio_concepts_prefix
            s = get_storage()
            prefix = minio_concepts_prefix(self.user_id, workspace_name)
            all_keys = s.list_keys(prefix)
            concept_keys = [k for k in all_keys if k.endswith(".md") 
                           and not k.endswith("/index.md") 
                           and "/mocs/" not in k]

            if not concept_keys:
                return context

            # 建立多重别名雷达图
            alias_map = {}  # alias -> key
            for key in concept_keys:
                stem = key.split("/")[-1].replace(".md", "").lower()
                alias_map[stem] = key
                file_parts = [p.strip() for p in re.split(r'[(（)）]', stem) if p.strip()]
                for p in file_parts:
                    if p not in alias_map:
                        alias_map[p] = key

            available_aliases = list(alias_map.keys())

            for concept in concepts:
                clean_concept = concept.replace("[", "").replace("]", "").strip()
                safe_name = clean_concept.replace("/", "_").replace("\\", "_")
                lower_name = safe_name.lower()

                # 防线 1：直接命中
                if lower_name in alias_map:
                    match_key = alias_map[lower_name]
                    try:
                        content = s.read_text(match_key)
                        match_name = match_key.split("/")[-1]
                        context += f"【🚨本地知识 == {match_name} ==】\n{content}\n\n"
                        print(f"  -> 📂 提取: {match_name}")
                    except Exception:
                        pass
                    continue

                # 防线 2：反向拆解
                parts = [p.strip() for p in re.split(r'[(（)）]', lower_name) if p.strip()]
                found = False
                for part in parts:
                    if part in alias_map:
                        part_key = alias_map[part]
                        try:
                            content = s.read_text(part_key)
                            part_name = part_key.split("/")[-1]
                            context += f"【🚨本地拆解 == {part_name} ==】\n{content}\n\n"
                            print(f"  -> 🔍 反向拆解命中: {part_name}")
                            found = True
                            break
                        except Exception:
                            pass
                if found:
                    continue

                # 防线 3：相似度容错
                close = difflib.get_close_matches(lower_name, available_aliases, n=1, cutoff=0.85)
                if close:
                    match_key = alias_map[close[0]]
                    try:
                        content = s.read_text(match_key)
                        match_name = match_key.split("/")[-1]
                        context += f"【🚨本地相似 == {match_name} ==】\n{content}\n\n"
                        print(f"  -> 🧲 相似纠错: {match_name}")
                    except Exception:
                        pass
                else:
                    print(f"  ❌ 未找到: [{safe_name}]")

            return context

        # ── 本地模式 ──
        concepts_dir = self.wiki_root / workspace_name / "concepts"

        if not concepts_dir.exists():
            return context

        all_md_files = list(concepts_dir.glob("*.md"))

        # 建立多重别名雷达图
        alias_map = {}
        for f in all_md_files:
            stem = f.stem.lower()
            alias_map[stem] = f
            file_parts = [p.strip() for p in re.split(r'[(（)）]', stem) if p.strip()]
            for p in file_parts:
                if p not in alias_map:
                    alias_map[p] = f

        available_aliases = list(alias_map.keys())

        for concept in concepts:
            clean_concept = concept.replace("[", "").replace("]", "").strip()
            safe_name = clean_concept.replace("/", "_").replace("\\", "_")
            lower_name = safe_name.lower()

            # 防线 1：直接命中
            if lower_name in alias_map:
                match_file = alias_map[lower_name]
                context += f"【🚨本地知识 == {match_file.name} ==】\n{match_file.read_text(encoding='utf-8')}\n\n"
                print(f"  -> 📂 提取: {match_file.name}")
                continue

            # 防线 2：反向拆解
            parts = [p.strip() for p in re.split(r'[(（)）]', lower_name) if p.strip()]
            found = False
            for part in parts:
                if part in alias_map:
                    part_file = alias_map[part]
                    context += f"【🚨本地拆解 == {part_file.name} ==】\n{part_file.read_text(encoding='utf-8')}\n\n"
                    print(f"  -> 🔍 反向拆解命中: {part_file.name}")
                    found = True
                    break
            if found:
                continue

            # 防线 3：相似度容错
            close = difflib.get_close_matches(lower_name, available_aliases, n=1, cutoff=0.85)
            if close:
                match_file = alias_map[close[0]]
                context += f"【🚨本地相似 == {match_file.name} ==】\n{match_file.read_text(encoding='utf-8')}\n\n"
                print(f"  -> 🧲 相似纠错: {match_file.name}")
            else:
                print(f"  ❌ 未找到: [{safe_name}]")

        return context

    def _fuzzy_find_local_files(self, workspace_name: str, fuzzy_keywords: list) -> str:
        if not fuzzy_keywords:
            return ""

        if USE_MINIO:
            from core.storage import get_storage
            from core.path_resolver import minio_wiki_prefix
            s = get_storage()
            prefix = minio_wiki_prefix(self.user_id, workspace_name)
            all_keys = s.list_keys(prefix)
            md_keys = [k for k in all_keys if k.endswith(".md")]

            context = ""
            found = set()
            for kw in fuzzy_keywords:
                if not kw.strip():
                    continue
                kw_lower = kw.lower()
                for key in md_keys:
                    name = key.split("/")[-1].replace(".md", "").lower()
                    if kw_lower in name and key not in found:
                        found.add(key)
                        try:
                            content = s.read_text(key)
                            display_name = key.split("/")[-1]
                            context += f"【🚨模糊命中 == {display_name} ==】\n{content}\n\n"
                        except Exception:
                            pass
            return context

        # ── 本地模式 ──
        workspace_dir = self.wiki_root / workspace_name
        if not workspace_dir.exists():
            return ""

        context = ""
        found = set()
        all_md = list(workspace_dir.rglob("*.md"))

        for kw in fuzzy_keywords:
            if not kw.strip():
                continue
            kw_lower = kw.lower()
            for fp in all_md:
                if kw_lower in fp.stem.lower() and fp not in found:
                    found.add(fp)
                    try:
                        context += f"【🚨模糊命中 == {fp.name} ==】\n{fp.read_text(encoding='utf-8')}\n\n"
                    except Exception:
                        pass
        return context

    @staticmethod
    def _extract_matched_concepts(context: str) -> list[str]:
        """从拼接后的 wiki 上下文标题中提取实际命中的概念页名称。"""
        if not context:
            return []
        seen = set()
        matched = []
        for raw_name in re.findall(r"==\s*(.*?)\s*==", context):
            name = raw_name.strip()
            if name.endswith(".md"):
                name = name[:-3]
            if name and name not in seen:
                seen.add(name)
                matched.append(name)
        return matched

    def retrieve_context(
        self,
        user_question: str,
        target_workspace: str,
        user_id: str = "",
        max_chars: int = 20000,
    ) -> dict:
        """给外部 Agent 使用的 wiki 检索入口：只返回知识上下文，不生成最终答案。"""
        if user_id and user_id != self.user_id:
            self.user_id = user_id
            self.wiki_root = get_wiki_root(user_id)

        target_workspace = (target_workspace or "").strip()
        if not target_workspace:
            return {
                "source": "wiki",
                "workspace": "",
                "query": user_question,
                "local_concepts": [],
                "fuzzy_keywords": [],
                "matched_concepts": [],
                "local_context": "",
                "context_chars": 0,
                "needs_web_search": False,
                "search_query": user_question,
            }

        index_map = self._read_specific_map(target_workspace)
        decision = self.router.route(user_question, index_map)
        local_concepts = decision.get("local_concepts", []) or []
        fuzzy_keywords = decision.get("fuzzy_keywords", []) or []
        needs_web = bool(decision.get("needs_web_search", True))
        search_query = decision.get("search_query", user_question) or user_question

        local_context = ""
        if local_concepts:
            local_context += self._read_local_concepts(target_workspace, local_concepts)
        if fuzzy_keywords:
            local_context += self._fuzzy_find_local_files(target_workspace, fuzzy_keywords)

        matched_concepts = self._extract_matched_concepts(local_context)
        original_chars = len(local_context)
        if max_chars and max_chars > 0 and original_chars > max_chars:
            local_context = local_context[:max_chars]

        return {
            "source": "wiki",
            "workspace": target_workspace,
            "query": user_question,
            "local_concepts": local_concepts,
            "fuzzy_keywords": fuzzy_keywords,
            "matched_concepts": matched_concepts,
            "local_context": local_context,
            "context_chars": len(local_context),
            "needs_web_search": needs_web,
            "search_query": search_query,
        }

    def execute(self, user_question: str, target_workspace: str = ""):
        """CLI 入口"""
        print(f"\n👤 {user_question}")
        if not target_workspace:
            print("⚠️ 未指定工作区")
            return

        index_map = self._read_specific_map(target_workspace)
        try:
            decision = self.router.route(user_question, index_map)
        except Exception as e:
            print(f"❌ 路由崩溃: {e}")
            return

        local_context = ""
        lc = decision.get("local_concepts", [])
        fk = decision.get("fuzzy_keywords", [])
        if lc:
            local_context += self._read_local_concepts(target_workspace, lc)
        if fk:
            local_context += self._fuzzy_find_local_files(target_workspace, fk)

        web_context, image_context = "", ""
        if decision.get("needs_web_search", True):
            sq = decision.get("search_query", user_question)
            web_context = search_web_text(sq)
            images = search_multimodal_image(sq)
            if images:
                image_context = f"![{images[0].title}]({images[0].image_url})"

        try:
            for chunk in self.responder.answer(user_question, local_context, web_context, image_context):
                text = chunk.content if hasattr(chunk, 'content') else str(chunk)
                if text and text != "None":
                    print(text, end="", flush=True)
            print()
        except Exception as e:
            print(f"\n❌ {e}")

    async def stream_execute(
        self,
        user_question: str,
        target_workspace: str,
        history: list = None,
        user_id: str = "",
        session_id: str = "",
        web_search_enabled: bool = None,  # None=自动决策, True=强制联网, False=仅本地
    ):
        """Web 端流式生成器 (SSE)"""
        if history is None:
            history = []

        # 如果传入了 user_id 且与实例不同，临时切换
        if user_id and user_id != self.user_id:
            self.user_id = user_id
            self.wiki_root = get_wiki_root(user_id)

        def log(msg):
            print(f"  [{self.user_id}] {msg}")
            return f"data: {json.dumps({'type': 'log', 'content': msg})}\n\n"

        yield log(f"👤 收到提问: {user_question}")
        await asyncio.sleep(0.01)
        yield log(f"📁 工作区: [{target_workspace or '全局漫游'}]")
        await asyncio.sleep(0.01)

        local_concepts, fuzzy_keywords = [], []
        needs_web, search_query = True, user_question

        if target_workspace:
            yield log("🗺️ 读取局部地图...")
            index_map = self._read_specific_map(target_workspace)
            index_preview = index_map[:200].replace("\n", " ") if index_map else "(空)"
            yield log(f"   📋 地图摘要: {index_preview}...")
            await asyncio.sleep(0.01)

            try:
                decision = self.router.route(user_question, index_map)
                local_concepts = decision.get("local_concepts", [])
                fuzzy_keywords = decision.get("fuzzy_keywords", [])
                needs_web = decision.get("needs_web_search", True)
                search_query = decision.get("search_query", user_question)

                # 前端强制覆盖路由器的自动决策
                if web_search_enabled is not None:
                    needs_web = web_search_enabled
                    override_label = "强制联网" if web_search_enabled else "仅本地"
                    yield log(f"⚙️ 用户手动覆盖联网策略: {override_label}")

                yield log(f"🎯 寻路裁决完毕")
                yield log(f"   🧩 识别本地概念: {local_concepts or '(无)'}")
                yield log(f"   🔤 模糊关键词: {fuzzy_keywords or '(无)'}")
                yield log(f"   🌐 是否需要联网: {'是' if needs_web else '否'}")
                yield log(f"   🔎 联网搜索词: [{search_query}]")
                await asyncio.sleep(0.01)

                # 打印路由原始决策到后端控制台
                print(f"  [DEBUG] Router decision: {json.dumps(decision, ensure_ascii=False, indent=2)}")
            except Exception as e:
                yield log(f"❌ 路由异常: {e}")
                import traceback
                traceback.print_exc()

        yield log("🚚 装载本地弹药...")
        local_context = ""
        if target_workspace:
            if local_concepts:
                local_context += self._read_local_concepts(target_workspace, local_concepts)
                for c in local_concepts:
                    # 检查是否真的命中了文件
                    matched = False
                    if USE_MINIO:
                        from core.storage import get_storage
                        from core.path_resolver import minio_concepts_prefix
                        s = get_storage()
                        prefix = minio_concepts_prefix(self.user_id, target_workspace)
                        all_keys = s.list_keys(prefix)
                        c_clean = c.lower().replace(" ", "")
                        for key in all_keys:
                            if key.endswith(".md") and not key.endswith("/index.md"):
                                name = key.split("/")[-1].replace(".md", "").lower().replace(" ", "")
                                if c_clean in name:
                                    matched = True
                                    display_name = key.split("/")[-1]
                                    yield log(f"   📂 精确命中: {display_name}")
                                    break
                    else:
                        concepts_dir = self.wiki_root / target_workspace / "concepts"
                        if concepts_dir.exists():
                            for f in concepts_dir.glob("*.md"):
                                if c.lower().replace(" ", "") in f.stem.lower().replace(" ", ""):
                                    matched = True
                                    yield log(f"   📂 精确命中: {f.name}")
                                    break
                    if not matched:
                        yield log(f"   ❌ 本地未找到: [{c}]")
                yield log(f"   ✅ 精确装载完成: {len(local_concepts)} 个概念")
            if fuzzy_keywords:
                pre_len = len(local_context)
                local_context += self._fuzzy_find_local_files(target_workspace, fuzzy_keywords)
                post_len = len(local_context)
                hit_count = local_context[pre_len:].count("🚨模糊命中")
                yield log(f"   🔍 模糊嗅探: {len(fuzzy_keywords)} 个关键词, 命中 {hit_count} 个文件")

        if local_context:
            yield log(f"   📦 本地弹药总量: {len(local_context)} 字符")
        else:
            yield log(f"   📭 本地弹药为空 (无相关概念)")
        await asyncio.sleep(0.01)

        web_context, image_context = "", ""
        images = None
        if needs_web and search_query:
            yield log(f"🌐 全网检索: [{search_query}]")
            web_context = search_web_text(search_query)
            yield log(f"   📄 联网文本: {len(web_context)} 字符")
            images = search_multimodal_image(search_query)
            if images:
                img = images[0]
                # 用来源网页 URL 而非 CDN 直链（防盗链）
                ref_url = getattr(img, 'host_page_url', '') or img.image_url
                image_context = f"{img.title}: {ref_url}"
                yield log(f"   🖼️ 参考来源: {img.title}")
            else:
                yield log(f"   🖼️ 无相关图片")

        # 历史记忆合流
        if history:
            hist_str = "【前情对话】\n"
            for msg in history[-5:]:
                role = "用户" if msg.get('role') == 'user' else 'AI'
                hist_str += f"{role}: {msg.get('content')}\n"
            local_context = hist_str + "\n" + local_context

        yield log("🗣️ 弹药装填完毕，开始生成回答：")
        await asyncio.sleep(0.01)

        try:
            for chunk in self.responder.answer(user_question, local_context, web_context, image_context):
                text = chunk.content if hasattr(chunk, 'content') else str(chunk)
                if text and text != "None":
                    yield f"data: {json.dumps({'type': 'text', 'content': text})}\n\n"
                    await asyncio.sleep(0.01)

            if images:
                img = images[0]
                ref_url = getattr(img, 'host_page_url', '') or img.image_url
                ref_md = f"\n\n---\n### 🌐 检索参考来源\n🔗 [{img.title}]({ref_url})\n"
                yield f"data: {json.dumps({'type': 'text', 'content': ref_md})}\n\n"
        except Exception as e:
            yield log(f"❌ 答疑崩溃: {e}")

        yield f"data: {json.dumps({'type': 'done'})}\n\n"


# CLI 入口
if __name__ == "__main__":
    flow = QueryFlow()
    workspaces = flow._get_workspace_list()

    print("\n" + "=" * 60)
    print("🚀 LLM-Wiki 终端控制台")
    print("=" * 60)

    if not workspaces:
        print("\n⚠️ 未检测到工作区！")
        target_ws = ""
    else:
        print("\n📂 选择工作区：")
        print("  [0] 🌍 全局漫游")
        for i, ws in enumerate(workspaces, 1):
            print(f"  [{i}] 📁 {ws}")
        choice = input("\n👉 编号: ").strip()
        target_ws = ""
        if choice.isdigit() and 0 < int(choice) <= len(workspaces):
            target_ws = workspaces[int(choice) - 1]

    print(f"\n✅ 锁定: [{target_ws or '全局漫游'}]")

    while True:
        try:
            q = input("\n👤 问题: ").strip()
            if q.lower() in ('exit', 'quit'):
                break
            if q:
                flow.execute(q, target_workspace=target_ws)
        except KeyboardInterrupt:
            break
