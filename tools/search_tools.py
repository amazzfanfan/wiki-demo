"""
tools/search_tools.py — 赛博触角 (阿里云 IQS 全家桶大满贯版)
"""
import os
import requests
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# ==========================================
# ⚙️ 0. 环境与全局安全设置
# ==========================================
load_dotenv()
os.environ['NO_PROXY'] = '*'  # 防 10053 物理拦截

ALIYUN_API_KEY = os.environ.get("ALIYUN_API_KEY", "")

# 官方四大核心 Endpoint
URL_SEARCH = "https://cloud-iqs.aliyuncs.com/search/unified"
URL_SCRAPE = "https://cloud-iqs.aliyuncs.com/readpage/scrape"
URL_READ_BASIC = "https://cloud-iqs.aliyuncs.com/readpage/basic"
URL_AI_ANSWER = "https://cloud-iqs.aliyuncs.com/ai/answer"

# ==========================================
# 🛡️ 1. 数据契约定义
# ==========================================
class ImageItem(BaseModel):
    title: str = Field(default="未知图片", description="网页或图片标题")
    image_url: str = Field(alias="imageUrl", description="图片直链")
    host_url: str = Field(default="", alias="hostPageUrl", description="来源网站链接")

# ==========================================
# ⚙️ 2. 智能底层发射器 (自动切换鉴权模式)
# ==========================================
def _execute_iqs_request(url: str, payload: dict, auth_type: str = "Bearer", timeout: int = 15) -> dict:
    """底层发射器：自动处理 Bearer 和 X-API-Key 两种鉴权逻辑"""
    if not ALIYUN_API_KEY:
        print("  ⚠️ [Tools] 未配置 ALIYUN_API_KEY，触角已断开。")
        return {}

    headers = {"Content-Type": "application/json"}

    # 巧妙避开阿里云的鉴权陷阱
    if auth_type == "Bearer":
        headers["Authorization"] = f"Bearer {ALIYUN_API_KEY}"
    elif auth_type == "X-API-Key":
        headers["X-API-Key"] = ALIYUN_API_KEY

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=timeout,
            verify=False
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout:
        print(f"  ❌ [Tools] API 请求超时 (15s)。")
    except requests.exceptions.RequestException as e:
        print(f"  ❌ [Tools] 网络底层异常: {e}")
    except Exception as e:
        print(f"  ❌ [Tools] 数据解析异常: {e}")

    return {}

# ==========================================
# 🕸️ 3. 核心武器暴露层 (四位一体)
# ==========================================

def search_web_text(query: str, num_results: int = 5) -> str:
    """[功能 1] 标准全网搜索 (文本)"""
    print(f"  🌐 [Tools] 触角发射：正在检索全网文献 -> [{query}]")

    payload = {
        "query": query,
        "engineType": "Generic",
        "numResults": num_results,
        "contents": {
            "mainText": False,
            "markdownText": True,
            "richMainBody": False,
            "summary": True, # 如果收费报错，可改为 False
            "rerankScore": True
        }
    }

    data = _execute_iqs_request(URL_SEARCH, payload, auth_type="Bearer")
    page_items = data.get("pageItems", [])

    if not page_items:
        return "未检索到相关外部信息。"

    report = []
    for idx, item in enumerate(page_items[:num_results], 1):
        title = item.get("title", "未知标题")
        link = item.get("link", "")
        content = item.get("summary", item.get("snippet", ""))

        slice_str = f"**[{idx}] {title}**\n> {content}\n- 来源: {link}\n"
        if item.get("markdownText"):
            slice_str += f"- 核心提取: {item.get('markdownText')[:200]}...\n"

        report.append(slice_str)

    return "\n".join(report)


def search_multimodal_image(query: str) -> List[ImageItem]:
    """[功能 2] 极简搜图 (依据你抓到的 Curl)"""
    print(f"  👁️ [Tools] 触角发射：正在捕获视觉素材 -> [{query}]")

    # 根据你的 curl，搜图只需传最简单的 query
    payload = {"query": query}

    data = _execute_iqs_request(URL_SEARCH, payload, auth_type="Bearer")

    valid_images = []
    for item in data.get("pageItems", []):
        images = item.get("images", [])
        if not images:
            continue

        try:
            img_obj = ImageItem(
                title=item.get("title", "未知素材"),
                imageUrl=images[0],
                hostPageUrl=item.get("link", "")
            )
            valid_images.append(img_obj)
        except Exception:
            pass

    return valid_images


def parse_webpage(url: str, use_advanced: bool = True) -> str:
    """[功能 3] 网页深度解析 (支持标准和增强双模式)"""
    print(f"  📄 [Tools] 触角下潜：正在解析目标网页 -> [{url}]")

    target_url = URL_SCRAPE if use_advanced else URL_READ_BASIC
    payload = {
        "url": url,
        "maxAge": 0,
        "formats": ["markdown"] # 对于 Agent 来说，直接要 markdown 最好
    }

    # ⚠️ 注意这里自动切换了 X-API-Key 鉴权
    data = _execute_iqs_request(target_url, payload, auth_type="X-API-Key")

    # 根据阿里云常规返回格式提取，具体字段可根据真实返回值微调
    return data.get("data", {}).get("markdown", "网页解析失败或无正文返回。")


def ask_ai_direct(query: str) -> str:
    """[功能 4] 阿里云直连 AI 问答"""
    print(f"  🧠 [Tools] 触角直连：调用阿里云原生 AI 回答 -> [{query}]")

    payload = {
        "query": query,
        "useModel": "pro"
    }

    data = _execute_iqs_request(URL_AI_ANSWER, payload, auth_type="Bearer")
    # 假设答案在 data["answer"]，需根据实际情况调整
    return data.get("answer", data.get("content", "AI接口未返回有效答案。"))