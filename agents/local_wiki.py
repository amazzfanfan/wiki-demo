# agents/local_wiki.py
import os
from agno.agent import Agent
from core.llm_factory import get_qwen_model

# ==========================================
# 🚨 核心修复：全新版本的导入路径
# ==========================================
from agno.knowledge.knowledge import Knowledge                    # 统一的 Knowledge 类
from agno.vectordb.lancedb import LanceDb                         # 向量数据库
from agno.knowledge.embedder.openai import OpenAIEmbedder         # Embedder 搬家到这里了

def get_knowledge_base():
    """
    配置 LanceDB 向量知识库
    """
    qwen_embedder = OpenAIEmbedder(
        id="text-embedding-v3",
        api_key=os.getenv("QWEN_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        dimensions=1024
    )

    # 最新版直接使用 Knowledge，不再区分 Local/PDF
    return Knowledge(
        vector_db=LanceDb(
            table_name="my_academic_papers",
            uri="tmp/lancedb",
            embedder=qwen_embedder
        )
    )

def get_local_wiki():
    """
    组装并返回 Local Wiki 专员
    """
    return Agent(
        name="Local Wiki",
        role="本地文献与个人笔记检索专家",
        model=get_qwen_model(),
        knowledge=get_knowledge_base(), # 挂载知识库大脑
        search_knowledge=True,          # 强制开启检索技能
        read_chat_history=True,         # 允许它读取上下文
        instructions=[
            "你是一个严谨的学术助手，负责解答用户关于其本地资料库的问题。",
            "1. 当用户提问时，必须优先调用 `search_knowledge` 工具在本地知识库中寻找答案。",
            "2. 你的回答必须严格基于本地检索到的片段，严禁自己胡编乱造或使用 AI 幻觉生成内容。",
            "3. 在回答末尾，请指明你是参考了本地知识库中的哪一部分得出结论的。"
        ],
        markdown=True,
        debug_mode=True
    )