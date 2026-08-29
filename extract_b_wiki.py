"""只跑系统 B（有 Schema），提取完整 wiki 页面 — 独立版"""
import os, json, re, time, requests
from pathlib import Path

API_KEY = os.environ.get("QWEN_API_KEY", "sk-xxx")
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL_FAST = "qwen-turbo"
MODEL_STRONG = "qwen-plus"

def call_llm(system, user, model=None):
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    payload = {"model": model or MODEL_STRONG, "messages": [
        {"role": "system", "content": system}, {"role": "user", "content": user}
    ], "temperature": 0.3, "max_tokens": 4000}
    t0 = time.time()
    resp = requests.post(f"{BASE_URL}/chat/completions", headers=headers, json=payload, timeout=120)
    elapsed = time.time() - t0
    if resp.status_code != 200:
        return "", elapsed, {}
    data = resp.json()
    return data["choices"][0]["message"]["content"], elapsed, data.get("usage", {})

# ── 3 篇论文 ──
PAPERS = [
    {"name": "论文1：连续退火温度对DP780力学性能的影响", "chunk": """
3.2 连续退火工艺对高强钢力学性能的影响
实验采用某钢厂CSP线生产的DP780双相钢，化学成分（质量分数%）为：C 0.09, Mn 1.65, Si 0.25, Cr 0.45, Mo 0.15。
冷轧板厚度1.2mm，退火温度分别设定为760°C、790°C、820°C和850°C，保温时间均为120s，冷却速率先以30°C/s快冷至460°C（过时效段），再以10°C/s慢冷至280°C。
结果表明：
(1) 退火温度从760°C升至820°C时，抗拉强度从785MPa提高至842MPa，延伸率从14.2%提高至16.8%，强塑积从11147 MPa·%提高至14146 MPa·%，满足DP780级别要求。
(2) 当退火温度继续升高至850°C时，抗拉强度反而下降至810MPa，延伸率降至15.1%。SEM观察发现马氏体体积分数过高（约35%），且出现了明显的带状组织。
(3) 快冷起始温度（过时效温度）对碳化物析出有显著影响。过时效温度偏低（<440°C）时，碳化物析出充分，屈服强度偏高但延伸率下降；过时效温度偏高（>480°C）时，碳化物粗化，固溶碳含量升高，导致烘烤硬化性（BH值）升高。"""},
    {"name": "论文2：过时效温度对DP980双相钢组织演变的研究", "chunk": """
4.1 过时效温度对微观组织的影响
本实验研究DP980级双相钢（C 0.12, Mn 2.0, Si 0.3, Cr 0.5），退火温度固定为800°C，保温90s，重点考察过时效温度（420°C、440°C、460°C、480°C、500°C）对组织演变的影响。
关键发现：
(1) 过时效温度440-460°C时，碳化物以纳米级Fe3C形式弥散析出，平均粒径约15-25nm，数密度约10^22/m³，屈服强度贡献约120MPa。
(2) 过时效温度升至480°C以上时，碳化物开始Ostwald熟化，平均粒径增大至50-80nm，数密度下降至10^20/m³，析出强化贡献降至约40MPa，但固溶碳含量从0.005%升至0.012%，烘烤硬化值（BH）从15MPa提高至45MPa。
(3) 过时效温度420°C时虽然析出量最大，但延伸率反而最低（仅9.8%），这与析出相在铁素体/马氏体界面偏聚导致的局部脆化有关。TEM观察确认界面处存在连续的碳化物薄膜，厚度约3-5nm。
(4) DP980的最优过时效窗口为450-470°C，此时抗拉强度985MPa，延伸率12.5%，强塑积12312 MPa·%，BH值28MPa。
与DP780的对比：DP980因更高的C和Mn含量，Ms点降低，马氏体体积分数在相同退火温度下更高（约28-32%），这对过时效温度的敏感性更强。"""},
    {"name": "论文3：冷却速率对双相钢残余奥氏体稳定性的影响", "chunk": """
5.3 冷却制度对残余奥氏体稳定性的影响
本研究考察了三种冷却制度对DP780钢残余奥氏体体积分数和稳定性的影响：
方案A：单段快冷 50°C/s 至室温
方案B：两段冷却 30°C/s 至460°C + 10°C/s 至280°C + 空冷
方案C：三段冷却 30°C/s 至500°C + 15°C/s 至350°C + 5°C/s 至200°C + 空冷
退火温度均为790°C，保温120s。
结果：
(1) 方案A：马氏体体积分数最高（38%），残余奥氏体仅2.1%，且稳定性差（Ms=180°C），在室温放置72h后进一步转变为1.5%。抗拉强度870MPa但延伸率仅11.2%。
(2) 方案B：马氏体体积分数25%，残余奥氏体4.8%，稳定性好（Ms=-20°C），72h后仍保持4.5%。抗拉强度830MPa，延伸率16.5%，强塑积13695 MPa·%。这是最优方案。
(3) 方案C：马氏体体积分数20%，残余奥氏体6.2%，但其中30%为不稳定型（Ms>50°C），72h后残余奥氏体降至4.8%。抗拉强度790MPa，延伸率18.2%，但BH值仅8MPa。
关键机制：两段冷却在过时效段（460°C）停留时间足够长（约15s），使碳从马氏体前驱体向奥氏体充分配分，提高了奥氏体的碳含量和稳定性。
碳化物类型分析（TEM+EDS）：
- 方案A：主要为ε-碳化物（亚稳），尺寸5-10nm
- 方案B：Fe3C + 少量Cr-rich M7C3，尺寸15-30nm
- 方案C：粗大Fe3C（50-100nm）+ Cr-rich M23C6"""},
]

SCHEMA = """# Schema — 冷轧钢
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
3. 工艺方案对比"""

ANALYST_BASE = "你是一个专业的知识图谱情报侦察兵。你的【唯一任务】是阅读新摄入的资料，提取其中的核心技术概念，并写一段简短的内容摘要。\n\n⚠️ 极其严格的提取规则：\n1. 只提取真正的技术实体、算法模型名称或核心机制。\n2. 绝对禁止提取论文标题、作者、会议名、或过于泛指的大词。\n3. 每个知识块最多提取 1 到 4 个最核心的概念！\n4. 使用学术界公认的简短缩写。\n5. 所有核心概念必须使用 `英文原名 (中文翻译)` 格式。"

ANALYST_ADDON = "\n\n## 领域编译指南（Schema）\n\n{schema}\n\n## 判断维度（额外要求）\n\n除了提取概念名，还需对每个概念标注：\n- importance: \"核心突破\" / \"关键支撑\" / \"背景知识\" / \"可忽略\"\n- novelty: \"全新概念\" / \"增量补充\" / \"已知重申\"\n\n同时标注：\n- conflicts: 与已有知识库具体页面/概念的矛盾（必须指出是哪个页面或概念）\n- gaps: 知识库中存在的具体缺口（已有X但缺少Y）\n\n输出 JSON 格式：\n{{\n  \"new_concepts\": [\"概念1 (翻译1)\", ...],\n  \"entries\": [\n    {{\"name\": \"概念1 (翻译1)\", \"importance\": \"核心突破\", \"novelty\": \"增量补充\"}}\n  ],\n  \"summary\": \"50-100字摘要\",\n  \"conflicts\": [\"本文发现X，但已有概念[[Y]]中提到Z\"],\n  \"gaps\": [\"知识库已有[[A]]的结论，但缺少B条件下的数据\"]\n}}\n\n⚠️ 矛盾必须引用已有知识库中的具体概念。缺口必须\"已有X但缺少Y\"格式。"

EDITOR_BASE = """你是一个严谨的本地知识库主编。
核心任务：根据【新摄入资料】和【本地已有文件内容】，进行知识融合比对，输出精确的文件修改动作。

⚠️ 核心执行协议：
1. 查重去重：已存在的内容不要重复
2. 全新创建：全新概念才 create 新页
3. 精准融合 edit：已有概念有增量信息时，生成 edit 动作
4. 强制双链：所有技术术语用 [[ ]] 包裹

你必须严格按以下 JSON 格式输出：
{
  "actions": [
    {"type": "create", "file": "concepts/概念名.md", "content": "# 概念名\\n\\n内容...", "rationale": "理由"},
    {"type": "edit", "file": "concepts/已有概念.md", "old_str": "要替换的原文段落", "content": "替换后的新内容", "rationale": "理由"},
    {"type": "append_link", "file": "index.md", "link": "- [[新概念]]", "rationale": "理由"}
  ]
}
type 只能是 create / edit / append_link 三选一。每个 action 必须有 type、file、rationale 字段。"""

EDITOR_ADDON = """\n\n## 知识判断（来自分析师）\n\n{entries_text}\n\n### 融合规则（严格执行）\n\n**页面粒度控制——不要过度拆分：**\n- "核心突破" → 如果已有相关页面，在该页面内展开详写；只有完全新概念才 create\n- "关键支撑" → 一律合并到已有的相关页面中，不创建独立页面\n- "背景知识" → 一句话带过\n- "可忽略" / "已知重申" → 跳过\n\n**矛盾标注——必须锚定具体来源：**\n- 必须写出：与【哪个已有概念/页面】的【哪段内容】矛盾\n- 无法锚定 → 不报告\n\n**缺口识别——具体到已有知识的空白：**\n- 格式："知识库已有 [[A]] 的结论，但缺少 B 条件下的数据"\n- 加在页面末尾 "## 知识缺口" 章节"""


class KB:
    def __init__(self):
        self.pages = {}
        self.index = []
    def ctx(self):
        if not self.pages:
            return "(知识库为空)"
        c = "=== index.md ===\n" + "\n".join(f"- [[{e}]]" for e in self.index) + "\n\n"
        for n, content in self.pages.items():
            c += f"=== concepts/{n}.md (摘要) ===\n{content[:500]}\n\n"
        return c
    def apply(self, text):
        actions = None
        try:
            d = json.loads(text.strip())
            if isinstance(d, dict) and "actions" in d: actions = d["actions"]
            elif isinstance(d, list): actions = d
        except: pass
        if actions is None:
            m = re.search(r'```(?:json)?\s*\n([\s\S]*?)```', text)
            if m:
                try:
                    d = json.loads(m.group(1).strip())
                    if isinstance(d, dict) and "actions" in d: actions = d["actions"]
                except: pass
        if actions is None:
            m = re.search(r'\{[\s\S]*\}', text)
            if m:
                try:
                    d = json.loads(m.group())
                    if isinstance(d, dict) and "actions" in d: actions = d["actions"]
                except: pass
        if actions is None:
            m = re.search(r'\[[\s\S]*\]', text)
            if m:
                try: actions = json.loads(m.group())
                except: pass
        if not actions or not isinstance(actions, list):
            return 0
        count = 0
        for a in actions:
            if not isinstance(a, dict): continue
            t = a.get("type", "") or a.get("action", "")
            f = a.get("file", "").replace("concepts/", "").replace(".md", "")
            if t == "create":
                c = a.get("content", "")
                if c:
                    self.pages[f] = c
                    if f not in self.index: self.index.append(f)
                    count += 1
            elif t == "edit":
                c = a.get("content", "")
                if f in self.pages:
                    old = a.get("old_str", "")
                    if old and old in self.pages[f]:
                        self.pages[f] = self.pages[f].replace(old, c)
                    else:
                        self.pages[f] += "\n\n" + c
                elif c:
                    self.pages[f] = c
                    if f not in self.index: self.index.append(f)
                count += 1
            elif t == "append_link":
                link = a.get("link", a.get("content", ""))
                m2 = re.search(r'\[\[(.+?)\]\]', link)
                if m2 and m2.group(1) not in self.index:
                    self.index.append(m2.group(1))
        return count

# ── 主流程 ──
print("=" * 60)
print("🅱️  重跑系统 B — 提取完整 Wiki")
print("=" * 60)

kb = KB()
all_conflicts = []
all_gaps = []

for i, paper in enumerate(PAPERS, 1):
    print(f"\n📄 [{i}/3] {paper['name']}")
    prompt_a = ANALYST_BASE + ANALYST_ADDON.format(schema=SCHEMA)
    map_r, _, _ = call_llm(prompt_a, f"【新摄入的资料】:\n{paper['chunk']}\n\n请提取核心概念。", MODEL_FAST)
    
    entries, conflicts, gaps = [], [], []
    try:
        m = re.search(r'\{[\s\S]*\}', map_r)
        if m:
            p = json.loads(m.group())
            entries = p.get("entries", [])
            conflicts = p.get("conflicts", [])
            gaps = p.get("gaps", [])
    except: pass
    all_conflicts.extend(conflicts)
    all_gaps.extend(gaps)
    print(f"  判断: {len(entries)}条目, {len(conflicts)}矛盾, {len(gaps)}缺口")
    
    et = json.dumps(entries, ensure_ascii=False, indent=2) if entries else ""
    if conflicts: et += f"\n\n潜在矛盾：{json.dumps(conflicts, ensure_ascii=False)}"
    if gaps: et += f"\n\n知识缺口：{json.dumps(gaps, ensure_ascii=False)}"
    
    ep = EDITOR_BASE
    if entries: ep += EDITOR_ADDON.format(entries_text=et)
    
    user = f"【新摄入的完整资料】:\n{paper['chunk']}\n\n【MAP 提取结果】:\n{map_r}\n\n【本地已有文件内容】:\n{kb.ctx()}\n\n请严格按 JSON 格式输出 actions 数组。"
    red_r, _, _ = call_llm(ep, user, MODEL_STRONG)
    
    n = kb.apply(red_r)
    print(f"  → {n} actions applied, 知识库: {len(kb.pages)}页面")

# ── 输出完整 wiki ──
out = "# 🅱️ Schema 系统生成的 Wiki（完整内容）\n\n"
out += f"> 3 篇冷轧钢论文依次 ingest | {len(kb.pages)} 页面 | {len(kb.index)} 索引\n\n---\n\n"
out += "## 📑 index.md\n\n"
for e in kb.index:
    out += f"- [[{e}]]\n"
out += "\n---\n\n"
for name, content in kb.pages.items():
    out += f"## 📄 {name}.md\n\n{content}\n\n---\n\n"
if all_conflicts:
    out += "## ⚠️ 检测到的矛盾\n\n"
    for c in all_conflicts: out += f"- {c}\n"
    out += "\n"
if all_gaps:
    out += "## 🔍 检测到的知识缺口\n\n"
    for g in all_gaps: out += f"- {g}\n"
    out += "\n"

Path("wiki_B_schema_output.md").write_text(out, encoding="utf-8")
print(f"\n✅ 完整 Wiki 已保存到: wiki_B_schema_output.md ({len(out)} 字)")
