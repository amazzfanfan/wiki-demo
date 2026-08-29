"""
Schema 重新评判 — 带代价信息的 LLM-as-Judge
明确告知裁判：系统 B 耗时 3 倍、Token 2 倍
"""
import os, json, time, requests

API_KEY = os.environ.get("QWEN_API_KEY", "sk-xxx")
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL = "qwen-plus"

def call_llm(system_prompt, user_text):
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.3,
        "max_tokens": 4000,
    }
    t0 = time.time()
    resp = requests.post(f"{BASE_URL}/chat/completions", headers=headers, json=payload, timeout=120)
    elapsed = time.time() - t0
    data = resp.json()
    return data["choices"][0]["message"]["content"], elapsed

# ── 从上次报告提取两个系统的实际输出 ──

SYSTEM_A_MAP = "[]"
SYSTEM_A_EDITOR = """[
  {
    "action": "edit",
    "file": "concepts/退火.md",
    "old_str": "退火是一种热处理工艺，将材料加热到一定温度后保温，再缓慢冷却。\\n目的是消除内应力、细化晶粒、改善加工性能。",
    "content": "退火是一种热处理工艺...（扩展了冷却路径、增加了罩式退火/连续退火对比、DP780实验数据760-820°C区间、过时效温度影响等详细内容）"
  },
  {
    "action": "append_link",
    "file": "index.md",
    "link": "- [[连续退火]]"
  },
  {
    "action": "create",
    "file": "concepts/连续退火.md",
    "content": "# 连续退火 (Continuous Annealing)\\n\\n连续退火是冷轧高强钢生产中实现组织精准调控的关键热处理工艺...（含关键工艺参数、工业约束、关联概念等，约800字深度页面）"
  }
]"""

SYSTEM_B_MAP = """{
  "new_concepts": ["Continuous Annealing (连续退火)", "Overaging Temperature (过时效温度)", "Martensite Volume Fraction (马氏体体积分数)", "Carbide Precipitation (碳化物析出)"],
  "entries": [
    {"name": "Continuous Annealing (连续退火)", "importance": "核心突破", "novelty": "增量补充"},
    {"name": "Overaging Temperature (过时效温度)", "importance": "关键支撑", "novelty": "增量补充"},
    {"name": "Martensite Volume Fraction (马氏体体积分数)", "importance": "关键支撑", "novelty": "增量补充"},
    {"name": "Carbide Precipitation (碳化物析出)", "importance": "关键支撑", "novelty": "增量补充"}
  ],
  "conflicts": ["过时效温度对碳化物析出的影响与传统认知可能存在差异", "高温退火导致力学性能下降的现象需要进一步验证"],
  "directions": ["研究不同退火温度下微观组织演变的定量关系", "探索更优的冷却速率控制策略以改善板形质量", "分析碳化物粗化对材料长期性能的影响"]
}"""

SYSTEM_B_EDITOR = """[
  生成了 5 个 actions：
  1. create concepts/Continuous_Annealing.md — 含"关键发现"、"⚠️ 注意"（矛盾标注）、"待深入"章节，约600字
  2. append_link index.md — "- [[Continuous Annealing]]"
  3. edit concepts/退火.md — 扩展定义，增加连续退火/罩式退火/过时效退火三种形态
  4. create concepts/Overaging_Temperature.md — 独立页面，含作用机制（三档温度分析）、⚠️ 矛盾标注、待深入，约500字
  5. create concepts/Martensite_Volume_Fraction.md — 独立页面，含工艺依赖性、性能耦合、⚠️ 注意、待深入，约500字
  6. create concepts/Carbide_Precipitation.md — 独立页面，含动力学调控、性能耦合、⚠️ 注意、待深入，约500字
  
  总计：新建 4 个独立概念页 + 编辑 1 个已有页 + 4 条索引链接
  每个页面结构：定义→机制→工艺依赖性→⚠️ 矛盾/注意→待深入方向→[[wikilink]]
]"""

# ── 完整 B 版 Editor 输出（从报告中截取关键部分）──
SYSTEM_B_EDITOR_FULL = """[
  {
    "action": "create",
    "file": "concepts/Continuous_Annealing.md",
    "content": "# Continuous Annealing (连续退火)\\n\\n...核心特征为：加热速率快（约15°C/s）、保温时间短（60–180 s）、冷却路径精确可控...\\n\\n## 关键发现\\n- 退火温度760–820°C区间内，抗拉强度由785 MPa升至842 MPa...\\n- 850°C时出现性能反常下降...马氏体体积分数异常升高至≈35%...\\n\\n⚠️ 注意\\n- 高温退火导致力学性能下降的现象尚未在现有文献中形成统一机理解释...\\n- 过时效温度对碳化物析出的影响与传统热处理理论存在潜在差异...\\n\\n## 待深入\\n- 研究不同退火温度下微观组织演变的定量关系...\\n- 探索更优的冷却速率控制策略...\\n- 分析碳化物粗化对材料长期性能的影响..."
  },
  {
    "action": "create",
    "file": "concepts/Overaging_Temperature.md",
    "content": "# Overaging Temperature (过时效温度)\\n\\n...典型范围440–480°C，用于调控碳化物的熟化动力学...\\n\\n⚠️ 注意\\n- 过时效温度对碳化物析出的影响规律与经典时效理论存在表观矛盾...\\n\\n## 待深入\\n- 建立过时效温度与碳化物平均尺寸、数密度的定量映射..."
  },
  {
    "action": "create",
    "file": "concepts/Martensite_Volume_Fraction.md",
    "content": "# Martensite Volume Fraction (马氏体体积分数)\\n\\n...核心组织参数...\\n\\n⚠️ 注意\\n- 实验中850°C退火导致MVF异常升至35%...\\n\\n## 待深入\\n- 开发基于机器视觉的MVF实时估算模型..."
  },
  {
    "action": "create",
    "file": "concepts/Carbide_Precipitation.md",
    "content": "# Carbide Precipitation (碳化物析出)\\n\\n...关键的亚稳相变行为...\\n\\n⚠️ 注意\\n- 过时效温度对碳化物析出的影响与传统认知可能存在差异...\\n\\n## 待深入\\n- 分析碳化物粗化对材料长期性能的影响..."
  },
  {
    "action": "edit",
    "file": "concepts/退火.md",
    "content": "...扩展为含连续退火/罩式退火/过时效退火三种形态的综合页面..."
  }
]"""

JUDGE_PROMPT = """你是一个知识管理系统的评测专家。你的评判必须**严苛、务实、不偏不倚**。

请对比以下两个知识提取+融合系统的输出，给出公正评价。

⚠️ **重要背景：代价差异巨大**
- 系统 A 总耗时 **21 秒**，消耗 **3,015 tokens**
- 系统 B 总耗时 **68 秒**，消耗 **6,192 tokens**
- **系统 B 的耗时是 A 的 3.2 倍，Token 消耗是 A 的 2.1 倍**

你的评判必须认真考虑这个代价差异。
- 如果 B 的质量提升不足以弥补 3 倍时间和 2 倍 Token 的代价，请明确说出来。
- 不要因为"新功能"就自动给高分。新功能必须有与之匹配的收益才值得。
- 考虑实际生产场景：用户每天可能 ingest 几十篇文档，3 倍延迟意味着什么？
- 考虑成本：2 倍 Token 在大规模使用时意味着多少额外 API 费用？
- 如果 B 的改进只是"锦上添花"而非"质的飞跃"，请降低评分。

## 系统 A（无 Schema，当前系统）

**MAP 提取结果：**
```
（空列表，模型未提取到概念，但 Editor 靠自身知识补全了）
```

**Editor 融合决策（生成 3 个 actions）：**
1. edit concepts/退火.md — 大幅扩展内容（增加连续退火对比、DP780 实验数据 760-850°C、过时效温度影响、碳化物析出规律），约 400 字新增
2. append_link index.md — 新增 [[连续退火]] 链接
3. create concepts/连续退火.md — 全新深度页面（工艺参数、工业约束、关联概念），约 800 字

**最终产出：2 个概念页（1 新建 + 1 编辑）+ 1 条索引链接**

---

## 系统 B（有 Schema，新系统）

**MAP 提取结果：**
```json
{SYSTEM_B_MAP}
```

**Editor 融合决策（生成 7 个 actions）：**
{SYSTEM_B_EDITOR_FULL}

**最终产出：4 个新建概念页 + 1 个编辑 + 4 条索引链接**

---

## 评判维度（请逐一打分 1-10 并说明理由）

### 1. 质量提升 vs 代价比
系统 B 比 A 多花了 3 倍时间、2 倍 Token。
- 多出来的 47 秒和 3177 个 Token，换来了什么？
- 这些改进在用户日常使用中能感知到吗？
- 如果用户每天 ingest 30 篇文档，B 比 A 多花 23 分钟 + 95K tokens（约 ¥2-3），值得吗？

### 2. 页面质量对比
- A 的「连续退火」页面质量如何？
- B 多创建的 3 个页面（过时效温度、马氏体体积分数、碳化物析出）是否真的需要独立成页？
- 还是说 A 把它们内联在连续退火页面里就足够了？

### 3. 判断信息的价值
- B 的 importance/novelty/conflicts/directions 这些信息，最终体现在页面上了吗？
- 体现的方式是否自然？还是强行塞入？

### 4. 矛盾检测的实际效用
- B 检测到的 2 个矛盾，是真矛盾还是假矛盾？
- A 没有检测矛盾，但它的内容里其实已经包含了矛盾信息（850°C 性能下降）

### 5. 可维护性
- B 生成了 4 个新页面，A 只生成 1 个。长期积累后，B 的知识库会不会过于碎片化？
- 概念拆得太细（过时效温度单独一页）是否反而增加浏览负担？

### 6. 综合推荐
综合考虑质量、代价、可维护性，你会推荐哪个？

请用中文回答，打分要严厉，不要因为 B 是"新功能"就放水。
"""

print("=" * 70)
print("⚖️  重新评判 — 带代价信息的 LLM-as-Judge")
print("=" * 70)
print(f"   模型: {MODEL}")
print(f"   关键差异: B 耗时 3.2x, Token 2.1x")
print()

prompt = JUDGE_PROMPT.replace("{SYSTEM_B_MAP}", SYSTEM_B_MAP).replace("{SYSTEM_B_EDITOR_FULL}", SYSTEM_B_EDITOR_FULL)

result, elapsed = call_llm("你是一个严苛、务实的知识管理系统评测专家。你的评判标准：任何改进都必须证明其 ROI（投入产出比）。", prompt)

print(f"⏱️  评判耗时: {elapsed:.1f}s")
print()
print(result)

# 保存
with open("test_schema_rejudge_report.md", "w", encoding="utf-8") as f:
    f.write("# Schema 重新评判报告（带代价信息）\n\n")
    f.write(f"**日期**: 2026-07-03  \n")
    f.write(f"**模型**: {MODEL}  \n")
    f.write(f"**关键背景**: 系统 B 耗时 68s（A 的 3.2 倍），Token 6192（A 的 2.1 倍）\n\n")
    f.write("---\n\n")
    f.write(result)

print("\n✅ 报告已保存到 test_schema_rejudge_report.md")
