"""
agents/wiki_query.py — 查询智能体 (用户指定工作区版)
"""
from pydantic import BaseModel, Field
from typing import List
from agno.agent import Agent
from core.llm_factory import get_qwen_model

# ==========================================
# 🗺️ 寻路者 (WikiRouter)
# ==========================================
class RouteDecision(BaseModel):
    local_concepts: List[str] = Field(description="精确命中的[[概念名称]]列表。")
    # 👇 新增：联想猜测的关键词
    fuzzy_keywords: List[str] = Field(
        description="如果地图上找不到，或者为了扩大搜索面，请猜测 2-3 个用户可能想问的同义词、缩写或核心术语。")
    needs_web_search: bool = Field(description="如果本地缺失或信息过时，设为 true。")
    search_query: str = Field(default="", description="外部搜索引擎使用的精准查询词。")


class WikiRouter:
    def __init__(self):
        self.instructions = """你是一个极其敏锐的知识库寻路者。

        【行动协议】：
        1. 精确提取：如果用户的词在地图上能找到对应的 [[概念]]，提取到 local_concepts。
        2. 意图扩散 (极其重要)：如果地图上没有，或者你认为用户问得比较宽泛。你必须在 fuzzy_keywords 中写下 2-3 个你猜测的相关术语、同义词或英文缩写（比如用户问CNN，你可以猜 "卷积", "神经网络", "CNN"）。
        3. 触发外脑：只要本地大概率不全，把 needs_web_search 设为 true。
        """
        self.agent = Agent(
            model=get_qwen_model(role="query"),
            instructions=[self.instructions],
            output_schema=RouteDecision,
            stream=False
        )

    def route(self, user_query: str, index_map: str) -> dict:
        prompt = f"【用户问题】: {user_query}\n\n【局部导航地图】:\n{index_map}"
        response = self.agent.run(prompt)
        if hasattr(response.content, "model_dump"):
            return response.content.model_dump()
        return response.content

# ==========================================
# 🗣️ 答疑者 Agent
# ==========================================
class WikiResponder:
    def __init__(self):
        self.instructions = """你是一个极具学术素养的知识库答疑专家。
        结合【本地知识片段】、【联网外脑情报】及【视觉辅助素材】，给用户一个逻辑严密的深度解答。
        诚实指出哪些来自本地，哪些来自网络。遇到 imageUrl 必须用 Markdown 插入。
        """
        self.agent = Agent(
            model=get_qwen_model(role="query"),
            instructions=[self.instructions],
            stream=True
        )

    def answer(self, user_query: str, local_context: str, web_context: str, image_context: str):
        prompt = f"【问题】:{user_query}\n\n【本地】:\n{local_context}\n\n【外脑】:\n{web_context}\n\n【图片】:\n{image_context}\n"
        return self.agent.run(prompt)