# agents/web_researcher.py
from agno.agent import Agent
from core.llm_factory import get_qwen_model
from tools.search_tools import search_web_text, parse_webpage, ask_ai_direct


def get_web_researcher():
    return Agent(
        name="Web Researcher",
        role="全网深度研究与情报分析专员",
        model=get_qwen_model(role="research"),
        tools=[search_web_text, parse_webpage, ask_ai_direct],
        instructions="""你是一名专业的网络研究分析师。你的任务是根据用户问题，
利用联网搜索工具进行深度调研，并输出结构化的研究报告。

工作流程：
1. 用 search_web_text 搜索多个关键词，获取多角度信息
2. 对重要来源用 parse_webpage 深度解析全文
3. 必要时用 ask_ai 获取综合观点
4. 整合所有信息，输出带引用的结构化报告

输出要求：
- 使用 Markdown 格式
- 每条信息标注来源链接
- 区分事实陈述和观点推断""",
        markdown=True,
        debug_mode=True,
    )