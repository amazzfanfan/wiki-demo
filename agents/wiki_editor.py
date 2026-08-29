"""
wiki_editor.py — 知识主编 (比对与决策)
"""
import json
from pydantic import BaseModel, Field, field_validator, model_validator
from typing import List, Any, Optional, Literal
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from agno.agent import Agent
from core.llm_factory import get_qwen_model
from core.schema_engine import is_enabled, inject_entries_to_editor
from core.content_validator import is_substantive_content, validate_abstract

# 单次 LLM 调用超时（秒）——融合比提取更复杂，给更多时间
LLM_TIMEOUT_SECONDS = 240

# 🔄 自我验证循环最大尝试次数（格式错误 + 内容质量各 1 次重试）
MAX_ATTEMPTS = 3


# 💡 我们把 Action 的定义移交给了主编，因为只有它才有权下达动作指令
class Action(BaseModel):
    type: Literal["create", "edit", "append_link", "extract_moc"] = Field(description="必须严格使用这四个词之一")
    file: str = Field(description="文件路径")
    title: Optional[str] = Field(default=None)
    tags: Optional[List[str]] = Field(default=None)
    abstract: Optional[str] = Field(default=None)
    old_str: Optional[str] = Field(default=None)
    content: Optional[str] = Field(default=None)
    link_to: Optional[str] = Field(default=None)
    rationale: str = Field(description="操作理由")

    @model_validator(mode='before')
    @classmethod
    def fix_llm_field_names(cls, data: Any) -> Any:
        """容错：LLM 偶尔用 action/target/reason 代替 type/file/rationale"""
        if isinstance(data, dict):
            # action → type
            if 'action' in data and 'type' not in data:
                data['type'] = data.pop('action')
            # target / file_path / file_name / path → file
            if 'target' in data and 'file' not in data:
                data['file'] = data.pop('target')
            if 'file_path' in data and 'file' not in data:
                data['file'] = data.pop('file_path')
            if 'file_name' in data and 'file' not in data:
                data['file'] = data.pop('file_name')
            if 'path' in data and 'file' not in data:
                data['file'] = data.pop('path')
            # reason/reasoning → rationale
            if 'reason' in data and 'rationale' not in data:
                data['rationale'] = data.pop('reason')
            elif 'reasoning' in data and 'rationale' not in data:
                data['rationale'] = data.pop('reasoning')
            # description → rationale (fallback)
            if 'description' in data and 'rationale' not in data:
                data['rationale'] = data.pop('description')
            # 兜底：如果 rationale 仍然缺失，给个默认值
            if 'rationale' not in data:
                data['rationale'] = 'LLM 未提供理由'
            # 智能推断：type=create 但缺少 file 时，从 title 推断文件名
            if 'file' not in data and data.get('type') == 'create':
                title = data.get('title', '') or 'untitled'
                safe = title.replace('/', '_').replace('\\', '_').replace(':', '_').replace('?', '_')
                data['file'] = f'concepts/{safe}.md'
            # append_link 默认目标就是 index.md
            if 'file' not in data and data.get('type') == 'append_link':
                data['file'] = 'index.md'
        return data

    @field_validator('tags', mode='before')
    @classmethod
    def ensure_list(cls, v: Any):
        if isinstance(v, str):
            return [tag.strip() for tag in v.split(',') if tag.strip()]
        return v


class EditorReport(BaseModel):
    actions: List[Action] = Field(description="精准的比对修改动作列表")


class WikiEditor:
    def __init__(self):
        # 💡 主编的核心 SOP：严禁盲猜，必须基于旧文件内容进行精准修改
        self.instructions = """你是一个严谨的本地知识库主编。
        你的核心任务是：根据【新摄入资料】和【本地已有文件内容】，进行知识融合比对，并输出精确的文件修改动作(actions)。

        ⚠️ 核心执行协议：
        1. 【查重与去重】：如果新资料的内容在【本地已有文件】中已经存在，或者没有实质性的新信息，请直接忽略，不要生成任何动作！
        2. 【全新创建】：如果这是一个全新的概念（本地没有它的文件），生成 'create' 动作。
           - `file` 字段只写概念名称路径（如 `concepts/LOGOS.md`），绝对不要包含动作描述词（如"创建"、"概念页面"、"新建条目"）！
           - `title` 字段只写概念名称（如 `LOGOS (基于大语言模型的扎根理论框架)`），不要写"创建XX页面"！
           - 正文需包含详实的深度笔记，并大量使用 [[双链]]。
           - 随后，必须附带一个 'append_link' 动作，将其分类追加到 index.md。
        3. 【精准融合 (edit)】：如果本地已经存在该概念的文件，且新资料提供了增量细节（如新公式、新应用场景）：
           - 必须生成 'edit' 动作。
           - `old_str`：必须从【本地已有文件内容】中一字不差地复制需要被替换/扩展的原有段落！
           - `content`：写入融合了新旧知识的全新段落。
        4. 【强制双链格式】：所有技术术语、模型名称必须用 [[概念名]] 格式包裹。
           - ❌ 绝对禁止使用 markdown 链接格式：[text](url)、[text](#wiki:...) 等一律禁止！
           - ✅ 唯一合法格式：[[Byte-level BPE]]、[[BPE (字节对编码)]]
           - 如果你发现自己写了 `[` 后面跟 `](`，立即停止并改写为 `[[...]]`。
        5.【专注原则】：在当前的决策中，你只被允许修改你在【本地已有文件内容】中亲眼看到的文件（如 index.md 和当前的目标概念文件）。绝对、绝对不允许尝试去 edit 任何未在此上下文中展示的旧文件！
        6. 【内容自检】（最高优先级）：在输出每个 create/edit 的 content 前，自检：
           - content 是否在讲**领域知识**（定义、原理、公式、对比、举例）？
           - 还是在讲**操作指令**（"创建XX页面""融合XX内容""补充到导航"）？
           - ❌ 操作指令不是知识！如果你的 content 读起来像任务描述，必须重写为实际知识内容。
           - ✅ 检验标准：如果遮住概念名，单看 content 能学到东西吗？不能就是废内容。
        7. 【渐进式披露 (extract_moc)】（最高警戒）：在修改 `index.md` 时，必须时刻监控信息密度！
           - ⚡ 触发条件：当你准备向 `index.md` 的某个 `### 标题` 下追加链接时，如果发现该标题下现有的 `[[具体知识点]]` 链接数量达到或超过 7 个，你绝对不能继续使用 'append_link'！
           - 🛠️ 强制动作：你必须改为输出 'extract_moc' 动作，将该标题下的所有旧链接与你的新链接，一起打包提取为一个独立的 MOC (导航地图) 文件。
           - `old_str`：必须包含该标题和下方所有的旧链接（用于底层的雷达精确锁定与折叠）。
           - `title`：新子地图的名称（如 "YOLO系列演进 MOC"）。
           - `content`：新子地图的完整正文（包含领域摘要、分类标题以及所有的具体链接）。
        """
        self.agent = Agent(
            model=get_qwen_model(role="editor"),
            instructions=[self.instructions],
            output_schema=EditorReport,
            stream=False
        )

    def _parse_response(self, response) -> Optional[dict]:
        """解析 LLM 响应为 EditorReport dict，失败返回 None + 错误信息"""
        if isinstance(response.content, str):
            # 🔧 JSON 修复兜底：手动修正 LLM 常用的错误字段名
            raw = response.content.strip()
            # 提取 JSON 块
            if '```json' in raw:
                raw = raw.split('```json', 1)[1].split('```', 1)[0].strip()
            elif '```' in raw:
                raw = raw.split('```', 1)[1].split('```', 1)[0].strip()
            try:
                data = json.loads(raw)
                # 修复每个 action 的字段名
                for act in data.get('actions', []):
                    if 'action' in act and 'type' not in act:
                        act['type'] = act.pop('action')
                    if 'target' in act and 'file' not in act:
                        act['file'] = act.pop('target')
                    if 'file_path' in act and 'file' not in act:
                        act['file'] = act.pop('file_path')
                    if 'file_name' in act and 'file' not in act:
                        act['file'] = act.pop('file_name')
                    if 'path' in act and 'file' not in act:
                        act['file'] = act.pop('path')
                    if 'reason' in act and 'rationale' not in act:
                        act['rationale'] = act.pop('reason')
                    elif 'reasoning' in act and 'rationale' not in act:
                        act['rationale'] = act.pop('reasoning')
                    elif 'description' in act and 'rationale' not in act:
                        act['rationale'] = act.pop('description')
                    if 'rationale' not in act:
                        act['rationale'] = 'LLM 未提供理由'
                    # 🧠 智能推断 file 字段
                    if 'file' not in act:
                        if act.get('type') == 'create':
                            title = act.get('title', '') or 'untitled'
                            safe = title.replace('/', '_').replace('\\', '_').replace(':', '_').replace('?', '_')
                            act['file'] = f'concepts/{safe}.md'
                        elif act.get('type') == 'append_link':
                            act['file'] = 'index.md'
                report = EditorReport.model_validate(data)
                print(f"  🔧 JSON 修复成功，恢复 {len(report.actions)} 个 actions")
                return report.model_dump()
            except Exception as fix_err:
                self._last_error = str(fix_err)
                return None

        # response.content 已经是 Pydantic 对象（Agno 原生解析成功）
        return response.content.model_dump()

    def merge(self, raw_text: str, analyst_summary: str, existing_context: str,
              entries: list = None, conflicts: list = None, gaps: list = None,
              canonical_names: list = None, target_concept: str = None) -> dict:
        print("\n[WikiEditor] 🧠 主编正在比对新旧知识，生成精准融合指令...")

        user_prompt = f"""
        【新资料摘要】:
        {analyst_summary}

        【新摄入的完整资料】:
        {raw_text}

        ---
        【本地已有文件内容】(供查重、对比和提取 old_str 参考):
        {existing_context}
        """

        # 🎯 当前概念锚定：Editor 只能为这一个概念生成 actions
        if target_concept:
            user_prompt += f"""
        ---
        🎯 【当前融合目标】: {target_concept}
        你正在处理这一个概念的融合任务。你只能为这个概念生成 create/edit/merge_into/append_link actions。
        ⚠️ 绝对禁止为其他概念创建新页面！资料中涉及的其他概念内容，作为当前概念的正文写入。
        ✅ 但你仍然必须为该概念生成 append_link action，将其分类追加到 index.md 导航地图中。
        
        🔀 【变体合并】: 如果当前目标概念在实质上只是某个已有概念的变体、子类型或实现方式
        （例如 "Inverted Dropout" 是 "Dropout" 的变体），
        你可以输出 merge_into action 将内容追加到已有页面，而不是创建独立页面：
        {{"type": "merge_into", "file": "concepts/已有概念.md", "content": "关于变体的知识内容...", "rationale": "理由"}}
        ⚠️ merge_into 的 file 必须指向已存在的文件，content 必须包含该变体的实质知识（定义、原理、公式、对比）。
        ⚠️ 只有当目标概念确实只是已有概念的变体时才用 merge_into，不要用 merge_into 来偷懒。
        """

        # 🏛️ Canonical Registry 约束：Editor 只能用注册表里的名字
        if canonical_names:
            names_list = '\n'.join(f'  - {n}' for n in canonical_names)
            user_prompt += f"""
        ---
        🏛️ 【合法概念注册表】（最高优先级约束）:
        以下是本批次所有合法概念名称，你只能对这些名字做 create 或 edit：
        {names_list}

        ⚠️ 强制规则：
        - 每个 create/edit action 的 file 和 title 必须与上表中的某个名字 EXACT 匹配
        - 禁止自行发明注册表中不存在的概念名（包括子概念、翻译变体、缩写等）
        - 如果资料涉及注册表外的概念，作为当前概念的正文内容写入，不要单独建页
        """

        user_prompt += """
        请严格按 JSON 格式输出 actions。如果找不到原文字符串，绝对不要编造 old_str！
        """

        # ── Schema 判断信息注入（可插拔）──
        user_prompt = inject_entries_to_editor(user_prompt, entries, conflicts, gaps)

        # 自我验证循环：最多尝试 MAX_ATTEMPTS 次（首次 + 重试）
        self._last_error = "未知错误"
        for attempt in range(MAX_ATTEMPTS):
            prompt = user_prompt
            if attempt > 0:
                # 区分错误类型：内容质量 vs 格式
                if "内容质量" in self._last_error:
                    prompt += f"""

⚠️⚠️⚠️ 上一次输出的内容质量不合格，已被拒绝！
{self._last_error}

请重新生成 create/edit 的 content 字段，确保：
1. content 是实际的领域知识（定义、原理、公式、对比、举例），而不是任务描述
2. ❌ 禁止写"创建XX页面""融合XX内容""补充到导航"——这些是操作指令，不是知识
3. ✅ 检验标准：遮住概念名，单看 content 能学到东西吗？
"""
                    print(f"  🔄 [WikiEditor] 第 {attempt+1} 次尝试（内容质量修正）...")
                else:
                    prompt += f"""

⚠️⚠️⚠️ 上一次输出格式有误，已被拒绝！请严格遵守以下字段名规则：
- 每个 action 必须使用 "type" 字段（不是 "action"）
- 每个 action 必须使用 "file" 字段（不是 "file_path"、"path" 或 "target"）
- 每个 action 必须包含 "rationale" 字段说明理由
- type 只能是 create / edit / append_link / extract_moc 四选一
上次错误：{self._last_error}
"""
                    print(f"  🔄 [WikiEditor] 第 {attempt+1} 次尝试（格式修正）...")

            # 超时保护：不用 with 语句（with 退出时会 shutdown(wait=True) 卡死）
            pool = ThreadPoolExecutor(max_workers=1)
            future = pool.submit(self.agent.run, prompt)
            try:
                response = future.result(timeout=LLM_TIMEOUT_SECONDS)
            except FuturesTimeoutError:
                print(f"\n⏰ [WikiEditor] LLM 调用超时 ({LLM_TIMEOUT_SECONDS}s)，跳过此概念")
                pool.shutdown(wait=False, cancel_futures=True)
                return {"actions": []}
            pool.shutdown(wait=False)

            result = self._parse_response(response)
            if result is not None:
                # ── 内容质量验证：检查每个 create/edit 的 content 是否含实质知识 ──
                _content_errors = []
                for act in result.get("actions", []):
                    if act.get("type") in ("create", "edit", "merge_into"):
                        _content = (act.get("content") or "").strip()
                        _title = act.get("title") or act.get("file", "")
                        _ok, _reason = is_substantive_content(_content, concept_name=_title, min_score=2)
                        if not _ok:
                            _content_errors.append(f"  - [{act['type']}] {_title}: {_reason}")
                        # 摘要也检查
                        if act.get("type") == "create" and act.get("abstract"):
                            cleaned = validate_abstract(act["abstract"])
                            if not cleaned:
                                act["abstract"] = ""  # 清空无效摘要
                
                if _content_errors:
                    self._last_error = "内容质量不合格:\n" + "\n".join(_content_errors)
                    print(f"  ⚠️ 第 {attempt+1} 次尝试内容质量不合格:")
                    for e in _content_errors:
                        print(f"    {e}")
                    if attempt < MAX_ATTEMPTS - 1:
                        continue  # 重试
                    else:
                        print(f"  ⚠️ 达到最大重试次数，丢弃不合格的 actions")
                        return {"actions": []}  # 质量不达标，宁可不出
                
                if attempt > 0:
                    print(f"  ✅ 重试成功！")
                return result
            else:
                print(f"  ❌ 第 {attempt+1} 次尝试解析失败: {self._last_error}")
                if attempt < MAX_ATTEMPTS - 1:
                    continue  # 还有重试机会

        # 所有尝试均失败
        print(f"  ❌ {MAX_ATTEMPTS} 次尝试均失败，放弃此概念")
        return {"actions": []}
