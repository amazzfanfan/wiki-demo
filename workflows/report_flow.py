"""
workflows/report_flow.py — 深度报告生成流水线
TopicScanner → BulkRetriever → ReportSynthesizer
用户倾泻资料，指定主题，自动提取并生成结构化深度报告。
"""
import json
import asyncio
import re
from pathlib import Path
from typing import Optional

from agents.wiki_analyst import WikiAnalyst
from tools.search_tools import search_web_text
from core.path_resolver import get_wiki_root, get_concepts_dir, USE_MINIO


class ReportFlow:
    """
    深度报告生成引擎。
    与 QA 模式的区别：
    - QA：精准概念查询，小范围检索
    - Report：全库批量检索 + 章节级深度合成
    """

    def __init__(self, user_id: str = ""):
        self.user_id = user_id
        self.analyst = WikiAnalyst()

    async def generate(
        self,
        topic: str,
        workspace: str,
        outline: str = "",
        session_id: str = "",
    ):
        """
        报告生成主流程（SSE 流式输出）

        流程：
        1. TopicScanner: 分析主题，生成检索关键词 + 建议大纲
        2. BulkRetriever: 全库批量检索本地知识 + 联网补充
        3. ReportSynthesizer: 逐章节深度合成报告
        """
        def log(msg):
            return f"data: {json.dumps({'type': 'log', 'content': msg})}\n\n"

        wiki_root = get_wiki_root(self.user_id)
        ws_dir = wiki_root / workspace
        concepts_dir = ws_dir / "concepts"

        yield log(f"📝 [报告生成] 主题: {topic} | 工作区: {workspace}")
        await asyncio.sleep(0.01)

        # ==========================================
        # Phase 1: Topic Scanner — 分析主题，生成大纲
        # ==========================================
        yield log("🔍 Phase 1: 扫描主题，生成检索策略...")
        await asyncio.sleep(0.1)

        # 读取 index 和所有概念标题
        available_titles = []
        index_content = ""

        if USE_MINIO:
            from core.storage import get_storage
            from core.path_resolver import minio_concepts_prefix, minio_index_key
            s = get_storage()
            # 获取概念列表
            prefix = minio_concepts_prefix(self.user_id, workspace)
            all_keys = s.list_keys(prefix)
            concept_keys = [k for k in all_keys if k.endswith(".md") 
                           and not k.endswith("/index.md") 
                           and "/mocs/" not in k]
            available_titles = [k.split("/")[-1].replace(".md", "") for k in concept_keys]
            # 读取 index
            index_key = minio_index_key(self.user_id, workspace)
            if s.exists(index_key):
                index_content = s.read_text(index_key)[:3000]
        else:
            # 本地模式
            index_path = ws_dir / "index.md"
            if concepts_dir.exists():
                available_titles = [f.stem for f in concepts_dir.glob("*.md") if f.stem.lower() != "index"]
            if index_path.exists():
                index_content = index_path.read_text(encoding="utf-8")[:3000]

        # 用 LLM 生成大纲和检索策略
        from agno.agent import Agent
        from core.llm_factory import get_qwen_model

        model = get_qwen_model(role="report")

        scanner = Agent(
            model=model,
            instructions=[
                "你是一个报告策划专家。根据用户主题和本地知识库，生成报告大纲和检索关键词。",
                "输出 JSON 格式：",
                '{"outline": [{"chapter": "章节名", "keywords": ["关键词1","关键词2"]}], "search_queries": ["联网检索词"]}',
                "大纲 3-5 章，每章 2-3 个关键词。",
            ],
            stream=False,
        )

        scan_prompt = f"主题: {topic}\n\n本地知识库目录:\n{index_content}\n\n已有概念: {', '.join(available_titles[:50])}"
        if outline:
            scan_prompt += f"\n\n用户指定大纲:\n{outline}"

        try:
            scan_result = scanner.run(scan_prompt)
            scan_text = scan_result.content if hasattr(scan_result, 'content') else str(scan_result)
            # 尝试解析 JSON
            report_plan = _extract_json(scan_text)
            if not report_plan:
                # 降级为默认大纲
                report_plan = {
                    "outline": [
                        {"chapter": "概述与背景", "keywords": [topic]},
                        {"chapter": "核心原理", "keywords": [topic, "原理"]},
                        {"chapter": "应用与案例", "keywords": [topic, "应用"]},
                        {"chapter": "总结与展望", "keywords": [topic, "未来"]},
                    ],
                    "search_queries": [topic],
                }
            yield log(f"📋 大纲生成完毕: {len(report_plan.get('outline', []))} 章")
            await asyncio.sleep(0.1)
        except Exception as e:
            yield log(f"⚠️ 大纲生成异常，使用默认模板: {e}")
            report_plan = {
                "outline": [
                    {"chapter": "概述", "keywords": [topic]},
                    {"chapter": "详细分析", "keywords": [topic]},
                    {"chapter": "总结", "keywords": [topic]},
                ],
                "search_queries": [topic],
            }

        # ==========================================
        # Phase 2: Bulk Retriever — 批量检索
        # ==========================================
        yield log("📚 Phase 2: 全库批量检索...")
        await asyncio.sleep(0.1)

        all_local_context = ""
        all_web_context = ""

        # 2a. 本地检索
        if USE_MINIO:
            from core.storage import get_storage
            from core.path_resolver import minio_concepts_prefix
            s = get_storage()
            prefix = minio_concepts_prefix(self.user_id, workspace)
            all_keys = s.list_keys(prefix)
            concept_keys = [k for k in all_keys if k.endswith(".md") 
                           and not k.endswith("/index.md") 
                           and "/mocs/" not in k]

            if concept_keys:
                all_keywords = set()
                for ch in report_plan.get("outline", []):
                    for kw in ch.get("keywords", []):
                        all_keywords.add(kw.lower())

                yield log(f"🔍 正在扫描 {len(available_titles)} 个本地概念...")
                await asyncio.sleep(0.1)

                matched_keys = set()
                for key in concept_keys:
                    name = key.split("/")[-1].replace(".md", "").lower()
                    for kw in all_keywords:
                        if kw in name or name in kw:
                            matched_keys.add(key)
                            break

                # 读取匹配的文件内容（限制总量）
                MAX_CHARS = 20000
                char_count = 0
                for key in matched_keys:
                    if char_count >= MAX_CHARS:
                        break
                    try:
                        content = s.read_text(key)
                        if char_count + len(content) > MAX_CHARS:
                            content = content[:MAX_CHARS - char_count]
                        name = key.split("/")[-1].replace(".md", "")
                        all_local_context += f"\n=== {name} ===\n{content}\n"
                        char_count += len(content)
                    except Exception:
                        pass

                yield log(f"📂 本地命中 {len(matched_keys)} 个概念 ({char_count} 字符)")
                await asyncio.sleep(0.1)
        elif concepts_dir.exists():
            # 本地模式
            all_keywords = set()
            for ch in report_plan.get("outline", []):
                for kw in ch.get("keywords", []):
                    all_keywords.add(kw.lower())

            yield log(f"🔍 正在扫描 {len(available_titles)} 个本地概念...")
            await asyncio.sleep(0.1)

            matched_files = set()
            for fp in concepts_dir.glob("*.md"):
                if fp.stem.lower() == "index":
                    continue
                title_lower = fp.stem.lower()
                for kw in all_keywords:
                    if kw in title_lower or title_lower in kw:
                        matched_files.add(fp)
                        break

            # 读取匹配的文件内容（限制总量）
            MAX_CHARS = 20000
            char_count = 0
            for fp in matched_files:
                if char_count >= MAX_CHARS:
                    break
                try:
                    content = fp.read_text(encoding="utf-8")
                    if char_count + len(content) > MAX_CHARS:
                        content = content[:MAX_CHARS - char_count]
                    all_local_context += f"\n=== {fp.stem} ===\n{content}\n"
                    char_count += len(content)
                except Exception:
                    pass

            yield log(f"📂 本地命中 {len(matched_files)} 个概念 ({char_count} 字符)")
            await asyncio.sleep(0.1)

        # 2b. 联网检索
        search_queries = report_plan.get("search_queries", [topic])
        for sq in search_queries[:3]:
            yield log(f"🌐 联网检索: [{sq}]")
            try:
                web = search_web_text(sq)
                if web:
                    all_web_context += f"\n--- Web: {sq} ---\n{web[:3000]}\n"
            except Exception:
                pass
            await asyncio.sleep(0.1)

        yield log("📦 检索素材装填完毕")
        await asyncio.sleep(0.1)

        # ==========================================
        # Phase 3: Report Synthesizer — 逐章合成
        # ==========================================
        yield log("✍️ Phase 3: 开始逐章合成深度报告...")
        await asyncio.sleep(0.1)

        # 报告头部
        report_header = "# " + topic + " — 深度研究报告\n\n> 由 LLM-Wiki OS 自动生成\n\n"
        yield "data: " + json.dumps({"type": "text", "content": report_header}) + "\n\n"

        chapters = report_plan.get("outline", [])

        for i, chapter in enumerate(chapters, 1):
            ch_name = chapter.get("chapter", f"第{i}章")
            ch_keywords = chapter.get("keywords", [topic])

            yield log(f"📝 正在合成: 第{i}章 - {ch_name}")
            await asyncio.sleep(0.05)

            # 每章使用独立的合成 Agent
            from pydantic import BaseModel, Field

            synthesizer = Agent(
                model=model,
                instructions=[
                    f"你是一个学术报告撰写专家。请根据提供的素材，为报告的「{ch_name}」章节撰写详细内容。",
                    "要求：",
                    "- 学术风格，逻辑严密",
                    "- 1500-2500 字",
                    "- 引用本地知识时注明来源概念名",
                    "- 使用 Markdown 格式（标题用 ## / ###，适当使用列表和表格）",
                    "- 不要编造数据，如果信息不足就明确说明",
                ],
                stream=True,
            )

            ch_prompt = (
                "报告主题: " + topic + "\n"
                "当前章节: " + ch_name + "\n"
                "章节关键词: " + ", ".join(ch_keywords) + "\n\n"
                "【本地知识素材】:\n" + all_local_context[:6000] + "\n\n"
                "【联网检索素材】:\n" + all_web_context[:4000] + "\n\n"
                "请撰写「" + ch_name + "」章节的完整内容。"
            )

            ch_header = "\n## " + str(i) + ". " + ch_name + "\n\n"
            yield "data: " + json.dumps({"type": "text", "content": ch_header}) + "\n\n"

            try:
                for chunk in synthesizer.run(ch_prompt):
                    text = chunk.content if hasattr(chunk, "content") else str(chunk)
                    if text and text != "None":
                        yield "data: " + json.dumps({"type": "text", "content": text}) + "\n\n"
                        await asyncio.sleep(0.01)
            except Exception as e:
                err_msg = "\n> 本章生成异常: " + str(e) + "\n"
                yield "data: " + json.dumps({"type": "text", "content": err_msg}) + "\n\n"

            yield log(f"✅ 第{i}章 [{ch_name}] 合成完毕")
            await asyncio.sleep(0.1)

        # 报告尾部
        footer = "\n\n---\n\n*报告生成完毕 · 共 " + str(len(chapters)) + " 章 · " + topic + "*\n"
        yield "data: " + json.dumps({"type": "text", "content": footer}) + "\n\n"
        yield log("🎉 报告生成完毕！")
        yield f"data: {json.dumps({'type': 'done'})}\n\n"


def _extract_json(text: str) -> Optional[dict]:
    """从 LLM 输出中提取 JSON 对象"""
    # 尝试直接解析
    try:
        return json.loads(text)
    except Exception:
        pass

    # 尝试从 markdown code block 提取
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass

    # 尝试找到 { } 块
    match = re.search(r'\{[^{}]*"outline"[^{}]*\[.*?\]\s*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass

    return None
