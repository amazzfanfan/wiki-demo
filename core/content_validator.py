"""
content_validator.py — 内容实质性正向检测

核心思路：不维护黑名单，而是检测内容是否携带「知识信号」。
知识内容必然包含：定义、数值、因果、对比、举例等结构化信息。
动作描述（"创建XX页面，融合..."）不包含任何知识信号 → 自然被拦截。
"""
import re


# ═══════════════════════════════════════════════
# 知识信号（正向指标）
# ═══════════════════════════════════════════════
_KNOWLEDGE_SIGNALS = [
    # 定义式
    r'是[指一种]', r'是指', r'定义为', r'被称[为作]', r'即[：:，,\s]',
    r'本质[上是为]', r'属[于是]', r'由.*组成', r'包[含括](?:了)?',
    # 数值/量化
    r'\d+\.?\d*\s*[%％]', r'\d{4}[年\-/]',
    r'(?:O|复杂度|时间|空间)[\s(（]*[O\(]',
    # 因果/推导
    r'因此[，,]', r'所以[，,]', r'由于.*[，,].*[所以因此]',
    r'导致', r'使得', r'从而',
    # 对比
    r'(?:相比|对比|不同|区别|优[劣势]|类似)[于与]',
    r'而(?:非|是)', r'尽管', r'虽然.*但是',
    # 举例/枚举
    r'(?:例如|比如|如[：:]|典型[的地])',
    r'(?:第一|首先|其一|一方面)',
    # 公式/数学
    r'[≈≥≤∑∏∫∂]', r'log[_₂]',
    r'(?<![a-zA-Z_])[a-zA-Z](?:_[a-zA-Z0-9])?\s*=\s*[a-zA-Z0-9(]',  # x = ..., f(x) = ..., θ_1 = ...
    r'\$.*?\$',  # LaTeX inline math
    r'\$\$.*?\$\$',  # LaTeX block math
    # 过程/机制
    r'(?:通过|利用|基于|采用).{4,}(?:来|进行|实现)',
    r'(?:步骤|阶段|过程|流程)',
    # 引用/来源
    r'\[\[.+\]\]',  # wikilinks（真实知识会引用其他概念）
]

# 编译一次
_KNOWLEDGE_PATTERNS = [re.compile(p) for p in _KNOWLEDGE_SIGNALS]

# 自引用检测（提到知识库系统本身 → 不是知识内容）
_SELF_REF = re.compile(
    r'概念页面|词条页面|知识页面|笔记页面|'
    r'创建.*页[面条]?|新建.*页[面条]?|生成.*页[面条]?|'
    r'融合.*到|补充.*到|追加.*到|添加到.*导航|'
    r'wikilink|双链|内部链接|'
    r'知识(?:库|图谱|系统)|'
    r'index\.md|导航地图|'
    r'新资料|已有文件|本地已有|'
    r'^action\s*=|action\s*=\s*(?:create|edit|append)',  # Editor JSON 泄漏
    re.IGNORECASE
)


def knowledge_score(text: str) -> int:
    """统计文本中命中的知识信号数量。"""
    if not text:
        return 0
    return sum(1 for p in _KNOWLEDGE_PATTERNS if p.search(text))


def is_substantive_content(text: str, concept_name: str = "", min_score: int = 2) -> tuple[bool, str]:
    """
    正向检测：内容是实质性知识还是动作描述/空壳？
    
    返回 (is_ok, reason)
    
    策略：
    1. 长度底线（<80字符直接拒绝）
    2. 自引用检测（提到"概念页面""双链"等 → 这是操作指令不是知识）
    3. 知识信号计分（≥2 个不同类型信号 = 通过）
    4. 概念关联性（如果给了 concept_name，检查内容是否真的在讲这个概念）
    """
    if not text or not text.strip():
        return False, "内容为空"
    
    clean = text.strip()
    
    # ── 1. 长度底线 ──
    if len(clean) < 80:
        return False, f"内容过短（{len(clean)}字符 < 80）"
    
    # ── 2. 自引用：内容在谈论知识库操作而非领域知识 ──
    self_refs = _SELF_REF.findall(clean)
    if self_refs:
        # 容忍度：如果内容足够长（>500字符）且知识信号丰富，容忍 1 次自引用
        if len(clean) < 500 or len(self_refs) > 1:
            return False, f"内容包含自引用（{'、'.join(list(set(self_refs))[:3])}），疑似操作指令而非知识"
    
    # ── 3. 知识信号正向计分 ──
    score = knowledge_score(clean)
    if score < min_score:
        return False, f"知识信号不足（{score}/{min_score}），内容缺少定义/数值/因果/对比等实质信息"
    
    # ── 4. 概念关联性（可选） ──
    if concept_name:
        # 提取概念名中的关键词（去括号、去停用词）
        name_core = re.sub(r'[\(（].*?[\)）]', '', concept_name).strip()
        name_tokens = [t for t in re.findall(r'[a-zA-Z]{2,}|[\u4e00-\u9fa5]{2,}', name_core) if len(t) >= 2]
        if name_tokens:
            # 至少有一个关键词出现在内容中
            found = any(t.lower() in clean.lower() for t in name_tokens)
            if not found:
                return False, f"内容未提及概念核心词（{'、'.join(name_tokens)}）"
    
    return True, "OK"


def validate_abstract(abstract: str) -> str:
    """清洗摘要：如果是动作描述则返回空串。"""
    if not abstract or not abstract.strip():
        return ""
    
    a = abstract.strip()
    
    # 自引用 → 清空
    if _SELF_REF.search(a):
        return ""
    
    # 纯动作描述（无任何知识信号）→ 清空
    if knowledge_score(a) == 0 and len(a) < 120:
        return ""
    
    return a
