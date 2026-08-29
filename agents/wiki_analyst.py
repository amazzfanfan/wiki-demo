from pydantic import BaseModel, Field
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from agno.agent import Agent
from core.llm_factory import get_qwen_model
from core.schema_engine import is_enabled, inject_schema_to_analyst

# 单次 LLM 调用超时（秒）
LLM_TIMEOUT_SECONDS = 180


# 💡 变化 1：把 Action 类彻底删除了！它不配拥有这个权力。
# 💡 变化 2：AnalysisReport 里去掉了 actions，加上了一个 summary 备用。
class ConceptEntry(BaseModel):
    """带判断的知识条目（Schema 启用时使用）"""
    name: str = Field(description="概念名称，双语格式")
    importance: str = Field(default="背景知识", description="核心突破 / 关键支撑 / 背景知识 / 可忽略")
    novelty: str = Field(default="已知重申", description="全新概念 / 增量补充 / 已知重申")


class AnalysisReport(BaseModel):
    new_concepts: List[str] = Field(description="从新资料中提取出的核心概念列表（如算法、模型、架构、术语等）")
    summary: str = Field(description="新资料的核心内容摘要（约50-100字），用于后续提供上下文")
    # ── Schema 扩展字段（可插拔，默认为空不影响现有链路）──
    entries: Optional[List[ConceptEntry]] = Field(default=None, description="带判断的知识条目（Schema 启用时）")
    conflicts: Optional[List[str]] = Field(default=None, description="与已有知识库具体页面/概念的矛盾（必须锚定来源）")
    gaps: Optional[List[str]] = Field(default=None, description="具体知识缺口：已有X但缺少Y")
    source: Optional[str] = Field(default=None, description="资料来源名称（论文名/文档名），用于 OKF 来源追溯")


class WikiAnalyst:
    def __init__(self, schema_content: str = ""):
        # 💡 变化 3：Prompt 彻底大换血，告诉它：你只是个看材料的，别管怎么存！
        self.instructions = """你是一个专业的知识图谱情报侦察兵。
                你的【唯一任务】是阅读新摄入的资料，提取其中的核心技术概念，并写一段简短的内容摘要。

                ⚠️ 极其严格的提取规则：
                1. 【实体标准】：只提取论文中**直接定义、讨论并有具体技术内涵**的实体、算法、模型、框架或核心机制。提取的概念必须在原文中有明确的定义或技术描述，而非仅被关键词提及。
                2. 【严禁项】：绝对禁止提取论文标题、作者、会议名、或过于泛指的大词。
                3. 【适度提取】：每个知识块提取 1 到 6 个核心概念，包括主要方法和重要的辅助机制。若无核心实体，返回空列表 []。
                4. 【名称洗牌】：使用学术界公认的简短缩写（如把 "Region Proposal Networks" 统一为 "RPN"）。
                5. 🌐【强制双语格式】：所有核心概念必须强制使用 `英文原名 (中文翻译)` 的标准格式输出！即使原文全是英文或全是中文，你也必须补齐另一种语言。
                   ✅ 正确示范：`Self-Attention (自注意力机制)`, `YOLO (单阶段目标检测算法)`, `CNN (卷积神经网络)`
                   ❌ 错误示范：`Self-Attention`, `自注意力机制`, `Self-Attention（自注意力机制）等`
                6. 🚫【反幻觉判断标准 — 符合以下任一条件的不是概念，禁止提取】：
                   a. 去掉修饰词后只剩日常用语（如"意义""反思""投资""背景"）→ 不是技术概念
                   b. 原文没有给出技术定义或具体方法描述，只是顺带提及 → 不是可提取的概念
                   c. 描述的是某个事物的"意义/影响/历史/价值"而非具体技术机制 → 不是技术概念
                """
        # ── Schema 注入（可插拔）──
        effective_instructions = inject_schema_to_analyst(self.instructions, schema_content)
        
        # 📉 分层模型：MAP 提取是简单任务，用轻量模型省 90% 费用
        self.agent = Agent(
            model=get_qwen_model(role="map"),
            instructions=[effective_instructions],
            output_schema=AnalysisReport,
            stream=False
        )

    def analyze(self, raw_text: str) -> dict:
        # 💡 变化 4：它不需要再读取本地 index.md 了，减轻它的认知负担。
        print("\n[WikiAnalyst] 🕵️‍♂️ 侦察兵正在阅读新资料并提取概念...")

        user_prompt = f"""
        【新摄入的资料】:
        {raw_text}

        请提取核心概念并生成摘要。
        """
        # 超时保护：防止 LLM 卡住导致整个流水线停滞
        # ⚠️ 不用 with 语句，因为 with 退出时会 shutdown(wait=True)
        # 即使 timeout 了也会等底层 HTTP 请求真正结束，卡死后续线程
        pool = ThreadPoolExecutor(max_workers=1)
        future = pool.submit(self.agent.run, user_prompt)
        try:
            response = future.result(timeout=LLM_TIMEOUT_SECONDS)
        except FuturesTimeoutError:
            print(f"\n⏰ [WikiAnalyst] LLM 调用超时 ({LLM_TIMEOUT_SECONDS}s)，跳过此块")
            pool.shutdown(wait=False, cancel_futures=True)  # 不等待，让后台自行结束
            return {"new_concepts": [], "summary": "(LLM 超时，未提取)"}
        pool.shutdown(wait=False)

        if isinstance(response.content, str):
            print("\n🚨 Pydantic 解析失败！原始字符串是：\n", response.content)
            raise ValueError("大模型未返回合法的 Pydantic 对象。")

        return response.content.model_dump()