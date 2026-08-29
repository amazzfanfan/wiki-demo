"""
Schema 集成测试 — 模拟完整 MAP→SHUFFLE→REDUCE 流程
对比 ENABLE_SCHEMA=false vs true 的最终页面质量

用法：
    python test_schema_integration.py
"""
import os
import sys
import json
import time
import requests

# ═══ API 配置 ═══
API_KEY = os.environ.get("QWEN_API_KEY", "sk-xxx")
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL_FAST = "qwen-turbo"   # MAP 用轻量模型
MODEL_STRONG = "qwen-plus"  # REDUCE 用强模型

# ═══ 测试数据 ═══
TEST_CHUNK = """
3.2 连续退火工艺对高强钢力学性能的影响

连续退火是冷轧高强钢生产中的核心热处理工序。退火温度直接影响奥氏体再结晶行为和碳化物析出动力学，
进而决定最终产品的力学性能。

实验采用某钢厂CSP线生产的DP780双相钢，化学成分（质量分数%）为：C 0.09, Mn 1.65, Si 0.25, 
Cr 0.45, Mo 0.15。冷轧板厚度1.2mm，退火温度分别设定为760°C、790°C、820°C和850°C，
保温时间均为120s，冷却速率先以30°C/s快冷至460°C（过时效段），再以10°C/s慢冷至280°C。

结果表明：
(1) 退火温度从760°C升至820°C时，抗拉强度从785MPa提高至842MPa，延伸率从14.2%提高至16.8%，
    强塑积从11147 MPa·%提高至14146 MPa·%，满足DP780级别要求。
(2) 当退火温度继续升高至850°C时，抗拉强度反而下降至810MPa，延伸率降至15.1%。
    SEM观察发现马氏体体积分数过高（约35%），且出现了明显的带状组织。
(3) 快冷起始温度（过时效温度）对碳化物析出有显著影响。过时效温度偏低（<440°C）时，
    碳化物析出充分，屈服强度偏高但延伸率下降；过时效温度偏高（>480°C）时，
    碳化物粗化，固溶碳含量升高，导致烘烤硬化性（BH值）升高。

与传统的罩式退火相比，连续退火具有加热速度快（约15°C/s）、保温时间短（60-180s）、
冷却可控性好等优势，特别适合生产双相钢、TRIP钢等先进高强钢。但设备投资较大，
对张力控制和板形控制的要求更高。
"""

TEST_SCHEMA = """# Schema — 冷轧钢

> 这是本沙箱的知识编译指南。

## 核心维度
冷轧钢领域的核心是"工艺参数 → 微观组织 → 力学性能"的因果链。
重要度按"对最终产品力学性能的影响程度"排序。

## 什么算重要
- 核心突破：揭示了工艺参数与力学性能之间新关系或新机制的发现
- 关键支撑：验证核心突破的实验数据、定量结果
- 背景知识：教科书级别的工艺原理
- 可以忽略：通用的冶金学基础知识、设备型号等工程细节

## 命名惯例
- 工艺参数用 参数名(单位) 格式
- 性能指标用 指标名(单位) 格式

## 页面风格约定
- 每个工艺页面必须包含：输入→过程→输出→对性能的影响
- 实验数据必须标注测试条件
- 非单调关系（如温度升高先升后降）必须显式标注

## 交叉引用优先级
1. 工艺参数 → 力学性能 因果链
2. 微观组织 → 力学性能 关系
3. 工艺方案对比

## 待深入方向
- 本沙箱目前缺少 检测方法 相关知识
"""

# ═══ 当前系统使用的 Prompt（从 wiki_analyst.py 复制）══
CURRENT_ANALYST_PROMPT = """你是一个专业的知识图谱情报侦察兵。
你的【唯一任务】是阅读新摄入的资料，提取其中的核心技术概念，并写一段简短的内容摘要。

⚠️ 极其严格的提取规则：
1. 【实体标准】：只提取真正的技术实体、算法模型名称或核心机制。
2. 【严禁项】：绝对禁止提取论文标题、作者、会议名、或过于泛指的大词。
3. 【宁缺毋滥】：每个知识块最多提取 1 到 4 个最核心的概念！若无核心实体，返回空列表 []。
4. 【名称洗牌】：使用学术界公认的简短缩写（如把 "Region Proposal Networks" 统一为 "RPN"）。
5. 🌐【强制双语格式】：所有核心概念必须强制使用 `英文原名 (中文翻译)` 的标准格式输出！即使原文全是英文或全是中文，你也必须补齐另一种语言。
   ✅ 正确示范：`Self-Attention (自注意力机制)`, `YOLO (单阶段目标检测算法)`, `CNN (卷积神经网络)`
   ❌ 错误示范：`Self-Attention`, `自注意力机制`, `Self-Attention（自注意力机制）等`
"""

CURRENT_EDITOR_PROMPT = """你是一个严谨的本地知识库主编。
你的核心任务是：根据【新摄入资料】和【本地已有文件内容】，进行知识融合比对，并输出精确的文件修改动作(actions)。

⚠️ 核心执行协议：
1. 【查重与去重】：如果新资料的内容在【本地已有文件】中已经存在，或者没有实质性的新信息，请直接忽略，不要生成任何动作！
2. 【全新创建】：如果这是一个全新的概念（本地没有它的文件），生成 'create' 动作。正文需包含详实的深度笔记，并大量使用 [[双链]]。随后，必须附带一个 'append_link' 动作，将其分类追加到 index.md。
3. 【精准融合 (edit)】：如果本地已经存在该概念的文件，且新资料提供了增量细节：
   - 必须生成 'edit' 动作。
   - `old_str`：必须从【本地已有文件内容】中一字不差地复制需要被替换/扩展的原有段落！
   - `content`：写入融合了新旧知识的全新段落。
4. 【强制双链】：所有技术术语、模型名称必须用 [[ ]] 包裹。
"""

# ═══ API 调用 ═══

def call_llm(system_prompt: str, user_text: str, model: str = None) -> tuple:
    """调用 LLM，返回 (响应文本, 耗时, token用量)"""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model or MODEL_STRONG,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.3,
        "max_tokens": 3000,
    }
    t0 = time.time()
    resp = requests.post(f"{BASE_URL}/chat/completions", headers=headers, json=payload, timeout=90)
    elapsed = time.time() - t0
    if resp.status_code != 200:
        print(f"  ❌ API Error {resp.status_code}: {resp.text[:200]}")
        return "", elapsed, {}
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    return content, elapsed, usage


# ══════════════════════════════════════════════════════════
# 测试 A：当前系统（无 Schema）
# ══════════════════════════════════════════════════════════

def test_current_system():
    """模拟当前系统的 MAP → Editor 流程"""
    print("\n" + "═" * 70)
    print("🅰️  当前系统（ENABLE_SCHEMA=false）")
    print("═" * 70)

    # ── MAP ──
    print("\n📍 Phase 1: MAP（提取概念）...")
    map_result, map_time, map_usage = call_llm(
        CURRENT_ANALYST_PROMPT,
        f"【新摄入的资料】:\n{TEST_CHUNK}\n\n请提取核心概念并生成摘要。",
        model=MODEL_FAST,
    )
    print(f"  ⏱️ {map_time:.1f}s | tokens: {map_usage}")
    print(f"  📝 提取结果:\n{map_result[:500]}")

    # ── REDUCE (Editor) ──
    print("\n📍 Phase 3: REDUCE（融合决策）...")
    # 模拟一个已有的概念页面（简化版）
    existing_context = """=== index.md (导航地图) ===
# 冷轧钢知识库

### 热处理工艺
- [[退火]]
- [[淬火]]

### 力学性能
- [[抗拉强度]]
- [[延伸率]]

=== concepts/退火.md (摘要) ===
# 退火 (Annealing)

退火是一种热处理工艺，将材料加热到一定温度后保温，再缓慢冷却。
目的是消除内应力、细化晶粒、改善加工性能。
"""
    editor_prompt = f"""{CURRENT_EDITOR_PROMPT}

【新资料摘要】:
{map_result}

【新摄入的完整资料】:
{TEST_CHUNK}

---
【本地已有文件内容】(供查重、对比和提取 old_str 参考):
{existing_context}

请严格按 JSON 格式输出 actions。如果找不到原文字符串，绝对不要编造 old_str！
"""
    editor_result, editor_time, editor_usage = call_llm(
        "你是一个严谨的本地知识库主编。",
        editor_prompt,
        model=MODEL_STRONG,
    )
    print(f"  ⏱️ {editor_time:.1f}s | tokens: {editor_usage}")
    print(f"  📝 融合决策:\n{editor_result[:1000]}")

    return {
        "map_result": map_result,
        "map_time": map_time,
        "map_usage": map_usage,
        "editor_result": editor_result,
        "editor_time": editor_time,
        "editor_usage": editor_usage,
        "total_time": map_time + editor_time,
    }


# ══════════════════════════════════════════════════════════
# 测试 B：启用 Schema 的系统
# ══════════════════════════════════════════════════════════

def test_schema_system():
    """模拟启用 Schema 后的 MAP → SHUFFLE → REDUCE 流程"""
    print("\n" + "═" * 70)
    print("🅱️  Schema 系统（ENABLE_SCHEMA=true）")
    print("═" * 70)

    # ── Phase 0: Schema 已有（跳过嗅探）──
    print(f"\n📍 Phase 0: Schema 已加载 ({len(TEST_SCHEMA)} 字符)")

    # ── MAP（注入 Schema）──
    print("\n📍 Phase 1: MAP（提取概念 + 判断）...")
    schema_analyst_prompt = f"""{CURRENT_ANALYST_PROMPT}

## 领域编译指南（Schema）

{TEST_SCHEMA}

## 额外判断维度

除了提取概念名，还需对每个概念标注：
- importance: "核心突破" / "关键支撑" / "背景知识" / "可忽略"（参考 Schema 中的定义）
- novelty: "全新概念" / "增量补充" / "已知重申"

同时标注：
- conflicts: 与已有知识或常见认知的潜在矛盾
- directions: 值得深入探索的方向

请在输出 JSON 中包含以下格式：
{{
  "new_concepts": ["概念1 (翻译1)", ...],
  "entries": [
    {{"name": "概念1 (翻译1)", "importance": "核心突破", "novelty": "增量补充"}}
  ],
  "summary": "50-100字摘要",
  "conflicts": ["..."],
  "directions": ["..."]
}}
"""
    map_result, map_time, map_usage = call_llm(
        schema_analyst_prompt,
        f"【新摄入的资料】:\n{TEST_CHUNK}\n\n请提取核心概念并做出判断。",
        model=MODEL_FAST,
    )
    print(f"  ⏱️ {map_time:.1f}s | tokens: {map_usage}")
    print(f"  📝 提取结果:\n{map_result[:800]}")

    # 解析 entries
    entries = []
    conflicts = []
    directions = []
    try:
        parsed = json.loads(map_result)
        entries = parsed.get("entries", [])
        conflicts = parsed.get("conflicts", [])
        directions = parsed.get("directions", [])
    except json.JSONDecodeError:
        # 尝试从文本中提取 JSON
        import re
        json_match = re.search(r'\{[\s\S]*\}', map_result)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                entries = parsed.get("entries", [])
                conflicts = parsed.get("conflicts", [])
                directions = parsed.get("directions", [])
            except:
                pass
    print(f"  🧠 判断聚合: {len(entries)} 条目, {len(conflicts)} 矛盾, {len(directions)} 方向")

    # ── REDUCE (Editor 消费判断信息) ──
    print("\n📍 Phase 3: REDUCE（融合决策 + Schema 判断）...")
    existing_context = """=== index.md (导航地图) ===
# 冷轧钢知识库

### 热处理工艺
- [[退火]]
- [[淬火]]

### 力学性能
- [[抗拉强度]]
- [[延伸率]]

=== concepts/退火.md (摘要) ===
# 退火 (Annealing)

退火是一种热处理工艺，将材料加热到一定温度后保温，再缓慢冷却。
目的是消除内应力、细化晶粒、改善加工性能。
"""

    entries_text = json.dumps(entries, ensure_ascii=False, indent=2) if entries else ""
    if conflicts:
        entries_text += f"\n\n潜在矛盾：{json.dumps(conflicts, ensure_ascii=False)}"
    if directions:
        entries_text += f"\n\n深入方向：{json.dumps(directions, ensure_ascii=False)}"

    schema_editor_injection = f"""

## 知识判断（来自分析师，供融合参考）

{entries_text}

融合时请参考以上判断（注意：这是 Wiki，不是知识图谱）：
- 核心突破 → 独立页面，详细展开，加"关键发现"章节
- 关键支撑 → 合并到相关页面，补充细节
- 背景知识 → 简要提及即可
- 已知重申 → 如无增量信息可跳过
- 潜在矛盾 → 在页面正文中加 ⚠️ **注意** 段落
- 深入方向 → 在页面末尾加"## 待深入"章节

⚠️ 重要：不要把这些判断信息写到 frontmatter 里！它们应该自然地融入正文。
"""

    editor_prompt = f"""{CURRENT_EDITOR_PROMPT}
{schema_editor_injection}

【新资料摘要】:
{map_result}

【新摄入的完整资料】:
{TEST_CHUNK}

---
【本地已有文件内容】(供查重、对比和提取 old_str 参考):
{existing_context}

请严格按 JSON 格式输出 actions。如果找不到原文字符串，绝对不要编造 old_str！
"""
    editor_result, editor_time, editor_usage = call_llm(
        "你是一个严谨的本地知识库主编。",
        editor_prompt,
        model=MODEL_STRONG,
    )
    print(f"  ⏱️ {editor_time:.1f}s | tokens: {editor_usage}")
    print(f"  📝 融合决策:\n{editor_result[:1500]}")

    return {
        "map_result": map_result,
        "map_time": map_time,
        "map_usage": map_usage,
        "entries": entries,
        "conflicts": conflicts,
        "directions": directions,
        "editor_result": editor_result,
        "editor_time": editor_time,
        "editor_usage": editor_usage,
        "total_time": map_time + editor_time,
    }


# ══════════════════════════════════════════════════════════
# LLM-as-Judge 自动评分
# ══════════════════════════════════════════════════════════

def llm_judge(result_a: dict, result_b: dict) -> str:
    """让 LLM 当裁判，对比两个系统的输出质量"""
    print("\n" + "═" * 70)
    print("⚖️  LLM-as-Judge 自动评分")
    print("═" * 70)

    judge_prompt = f"""你是一个知识管理系统评测专家。请对比以下两个知识提取+融合系统的输出，评估哪个更好。

## 系统 A（无 Schema，当前系统）

### MAP 提取结果：
{result_a['map_result']}

### Editor 融合决策：
{result_a['editor_result']}

---

## 系统 B（有 Schema，新系统）

### MAP 提取结果：
{result_b['map_result']}

### Editor 融合决策：
{result_b['editor_result']}

---

请从以下维度评分（1-10）并说明理由：

1. **重要性判断**：是否正确区分了核心知识和背景知识？
2. **领域感知**：是否体现了对冷轧钢领域的理解？
3. **矛盾检测**：是否发现了反直觉的知识？
4. **页面丰富度**：生成的页面内容是否有深度？
5. **Wiki 纯度**：是否保持了 Wiki 风格（而非知识图谱）？
6. **实用性**：哪个系统对用户更有价值？

最后给出综合推荐和理由。
"""
    result, elapsed, _ = call_llm(
        "你是一个公正的知识管理系统评测专家。请客观对比两个系统的输出。",
        judge_prompt,
        model=MODEL_STRONG,
    )
    print(f"  ⏱️ {elapsed:.1f}s")
    print(f"\n{result}")
    return result


# ══════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════

def main():
    print("=" * 70)
    print("🧪 Schema 集成测试 — 模拟 MAP→SHUFFLE→REDUCE 完整流程")
    print(f"   MAP 模型: {MODEL_FAST} | REDUCE 模型: {MODEL_STRONG}")
    print(f"   测试数据: 冷轧钢连续退火论文片段 ({len(TEST_CHUNK)} 字符)")
    print("=" * 70)

    # 运行两个系统
    result_a = test_current_system()
    result_b = test_schema_system()

    # 对比统计
    print("\n" + "═" * 70)
    print("📊 统计对比")
    print("═" * 70)
    print(f"{'指标':<20} {'🅰️ 无Schema':<20} {'🅱️ 有Schema':<20} {'差异':<15}")
    print("─" * 75)
    print(f"{'MAP 耗时':<20} {result_a['map_time']:<20.1f} {result_b['map_time']:<20.1f} {result_b['map_time']-result_a['map_time']:+.1f}s")
    print(f"{'REDUCE 耗时':<20} {result_a['editor_time']:<20.1f} {result_b['editor_time']:<20.1f} {result_b['editor_time']-result_a['editor_time']:+.1f}s")
    print(f"{'总耗时':<20} {result_a['total_time']:<20.1f} {result_b['total_time']:<20.1f} {result_b['total_time']-result_a['total_time']:+.1f}s")
    a_tokens = (result_a['map_usage'].get('total_tokens', 0) + result_a['editor_usage'].get('total_tokens', 0))
    b_tokens = (result_b['map_usage'].get('total_tokens', 0) + result_b['editor_usage'].get('total_tokens', 0))
    print(f"{'总 Token':<20} {a_tokens:<20} {b_tokens:<20} {b_tokens-a_tokens:+}")
    print(f"{'MAP Token':<20} {result_a['map_usage'].get('total_tokens', 0):<20} {result_b['map_usage'].get('total_tokens', 0):<20} {result_b['map_usage'].get('total_tokens', 0)-result_a['map_usage'].get('total_tokens', 0):+}")

    # Schema 特有指标
    print(f"\n{'Schema 特有指标':<20}")
    print(f"{'entries':<20} {'—':<20} {len(result_b['entries']):<20}")
    print(f"{'conflicts':<20} {'—':<20} {len(result_b['conflicts']):<20}")
    print(f"{'directions':<20} {'—':<20} {len(result_b['directions']):<20}")

    # LLM-as-Judge
    judge_result = llm_judge(result_a, result_b)

    # 保存报告
    report_file = "test_schema_integration_report.md"
    with open(report_file, "w", encoding="utf-8") as f:
        f.write("# Schema 集成测试报告\n\n")
        f.write(f"**日期**: 2026-07-03  \n")
        f.write(f"**MAP 模型**: {MODEL_FAST} | **REDUCE 模型**: {MODEL_STRONG}  \n\n")

        f.write("## 统计对比\n\n")
        f.write(f"| 指标 | 🅰️ 无Schema | 🅱️ 有Schema | 差异 |\n")
        f.write(f"|------|-------------|-------------|------|\n")
        f.write(f"| MAP 耗时 | {result_a['map_time']:.1f}s | {result_b['map_time']:.1f}s | {result_b['map_time']-result_a['map_time']:+.1f}s |\n")
        f.write(f"| REDUCE 耗时 | {result_a['editor_time']:.1f}s | {result_b['editor_time']:.1f}s | {result_b['editor_time']-result_a['editor_time']:+.1f}s |\n")
        f.write(f"| 总耗时 | {result_a['total_time']:.1f}s | {result_b['total_time']:.1f}s | {result_b['total_time']-result_a['total_time']:+.1f}s |\n")
        f.write(f"| 总 Token | {a_tokens} | {b_tokens} | {b_tokens-a_tokens:+} |\n\n")

        f.write("## 🅰️ 当前系统（无 Schema）\n\n")
        f.write(f"### MAP 输出\n```\n{result_a['map_result']}\n```\n\n")
        f.write(f"### Editor 输出\n```\n{result_a['editor_result']}\n```\n\n")

        f.write("## 🅱️ Schema 系统\n\n")
        f.write(f"### MAP 输出\n```\n{result_b['map_result']}\n```\n\n")
        f.write(f"### 判断信息\n- Entries: {json.dumps(result_b['entries'], ensure_ascii=False)}\n")
        f.write(f"- Conflicts: {json.dumps(result_b['conflicts'], ensure_ascii=False)}\n")
        f.write(f"- Directions: {json.dumps(result_b['directions'], ensure_ascii=False)}\n\n")
        f.write(f"### Editor 输出\n```\n{result_b['editor_result']}\n```\n\n")

        f.write("## ⚖️ LLM-as-Judge 评分\n\n")
        f.write(judge_result + "\n")

    print(f"\n✅ 完整报告已保存到 {report_file}")


if __name__ == "__main__":
    main()
