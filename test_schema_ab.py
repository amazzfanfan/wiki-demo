"""
Schema A/B 测试 — 对比无 Schema vs 有 Schema 的 Analyst 提取质量
独立脚本，不依赖项目代码，直接调 DashScope OpenAI-compatible API
"""
import json
import os
import time
import requests

# ═══ API 配置 ═══
API_KEY = "sk-xxx"
BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL = "qwen-plus"  # 用中等模型，平衡成本和质量

# ═══ 测试数据 ═══

CHUNK_COLD_ROLL = """
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
对张力控制和板形控制的要求更高。在实际生产中，退火炉内的张力波动是导致板形不良
（如边浪、中浪）的主要原因之一。
"""

CHUNK_QUANTUM = """
4.1 Surface Code 的容错阈值与实验进展

Surface code 是目前最有前景的拓扑量子纠错码之一。它定义在二维正方格子上，
每个物理量子比特位于格子的边上，稳定子算子包括顶点处的X型算子（star operator）
和面心处的Z型算子（plaquette operator）。

Surface code 的关键优势在于其较高的容错阈值。理论分析表明，在独立去极化噪声模型下，
surface code 的阈值约为 p_th ≈ 1%（即每个物理量子比特的错误率低于1%时，
增加编码距离可以指数级地降低逻辑错误率）。这与 Steane [[7,1,3]] 码（阈值约 10^-4）
和 Shor [[9,1,3]] 码（阈值约 10^-3）相比有数量级的提升。

Google 在 2023 年的里程碑实验中，使用 72 量子比特 Willow 芯片实现了 distance-5 和 
distance-7 的 surface code。实验结果显示，将编码距离从 3 增加到 5 再到 7，
逻辑错误率分别降低了 2.14 倍和 2.47 倍（即 Λ ≈ 2.3），首次展示了表面码的
"below-threshold"扩展行为——增加冗余确实能改善逻辑量子比特的可靠性。

然而，surface code 的实际部署面临几个关键挑战：
(1) 量子比特数量开销巨大：一个 distance-d 的 surface code 需要约 2d² 个物理量子比特，
    实现一个有用的逻辑量子比特可能需要 d=27（约 1500 个物理量子比特）。
(2) 测量错误（measurement error）显著降低实际阈值，需要使用重复测量和时空解码器。
(3) 边界条件对码字容量有重要影响：rough boundary 和 smooth boundary 分别对应
    X 型和 Z 型逻辑算子，实际芯片布局中两种边界的几何约束限制了码的可扩展性。

与 surface code 形成对比的是 color code，它定义在三色可着色的二维格子上，
支持 transversal 实现所有 Clifford 门，但容错阈值较低（约 0.1%）。
最新的 honeycomb code（Google 2022）则通过动态测量序列实现了更高的效率，
但尚未在大规模实验中验证。
"""

CHUNK_DL = """
5.3 Vision Transformer (ViT) 与 CNN 的对比分析

Vision Transformer (ViT) 由 Dosovitskiy 等人于 2020 年提出，将 Transformer 架构
直接应用于图像分类任务，不引入任何卷积操作。ViT 将输入图像切分为固定大小的 patch
（如 16×16），将每个 patch 线性投影为 embedding 向量，加入位置编码后送入标准
Transformer encoder。

在 ImageNet-21k 预训练后微调至 ImageNet-1k 的设置下，ViT-L/16 达到了 87.76% 的
Top-1 准确率，超越了当时最强的 CNN 模型（EfficientNet-L2 的 86.7%）。
后续变体 DeiT（Data-efficient Image Transformers）通过知识蒸馏和数据增强策略，
在仅使用 ImageNet-1k 训练的情况下达到了 83.1%，证明了 ViT 不一定需要海量预训练数据。

ViT 的核心优势在于：
(1) 全局感受野：self-attention 从第一层就建立了全局依赖，而 CNN 需要堆叠多层才能
    获得大感受野。这对需要理解全局结构的任务（如语义分割、目标检测）尤为重要。
(2) 可扩展性（scaling law）：ViT 的性能随模型规模和预训练数据量的增长呈现更平滑的
    幂律关系，而 CNN 在某个点之后会出现性能饱和。
(3) 与 NLP 架构统一：ViT 使得视觉和语言模型可以共享同一套 Transformer 架构，
    为多模态模型（如 CLIP、DALL-E）奠定了基础。

然而，ViT 也存在明显的局限：
(1) 计算复杂度为 O(n²)：对于高分辨率图像，patch 数量 n 急剧增加（如 448×448 图像
    在 patch_size=16 时有 784 个 patch），导致计算和内存开销巨大。
(2) 缺乏归纳偏置（inductive bias）：ViT 不假设平移不变性和局部性，这使其在小数据集上
    表现不如 CNN（CNN 的 inductive bias 在小数据场景是优势而非劣势）。
(3) 中间特征的多尺度性差：标准 ViT 输出单一尺度的特征图，而 CNN 天然产生多尺度
    金字塔特征（如 ResNet 的 stage1-4），这使得 ViT 在密集预测任务上需要额外的
    多尺度改造（如 Swin Transformer 的 shifted window + hierarchical design）。
"""

# ═══ Prompt 定义 ═══

CURRENT_ANALYST_PROMPT = """你是一个专业的知识图谱情报侦察兵。
你的【唯一任务】是阅读新摄入的资料，提取其中的核心技术概念，并写一段简短的内容摘要。

⚠️ 极其严格的提取规则：
1. 【实体标准】：只提取真正的技术实体、算法模型名称或核心机制。
2. 【严禁项】：绝对禁止提取论文标题、作者、会议名、或过于泛指的大词。
3. 【宁缺毋滥】：每个知识块最多提取 1 到 4 个最核心的概念！若无核心实体，返回空列表 []。
4. 【名称洗牌】：使用学术界公认的简短缩写。
5. 🌐【强制双语格式】：所有核心概念必须强制使用 `英文原名 (中文翻译)` 的标准格式输出！"""

SCHEMA_COLD_ROLL = """## 领域编译指南（Schema）

### 核心维度
冷轧钢领域的核心是"工艺参数 → 微观组织 → 力学性能"的因果链。
重要度按"对最终产品力学性能的影响程度"排序。

### 什么算重要
- 核心突破：揭示了工艺参数与力学性能之间新关系或新机制的发现
- 关键支撑：验证核心突破的实验数据、定量结果
- 背景知识：教科书级别的工艺原理（如"退火可以软化材料"）
- 可以忽略：通用的冶金学基础知识、设备型号等工程细节

### 交叉引用优先级
1. 工艺参数 → 力学性能 因果链（如：退火温度 → 抗拉强度）
2. 微观组织 → 力学性能 关系（如：马氏体含量 → 强度）
3. 工艺方案对比（如：连续退火 vs 罩式退火）"""

SCHEMA_QUANTUM = """## 领域编译指南（Schema）

### 核心维度
量子计算领域的核心是"纠错码类型 → 容错阈值 → 硬件开销"的三角关系。
重要度按"容错阈值高低"和"实验验证程度"排序。

### 什么算重要
- 核心突破：达到新容错阈值或首次实验验证某种纠错码的里程碑
- 关键支撑：阈值分析、编码距离与错误率关系的定量数据
- 背景知识：量子纠错的基本原理（如 stabilizer formalism）
- 可以忽略：纯理论推导（未经实验验证的）、过于细节的电路设计

### 交叉引用优先级
1. 纠错码 → 容错阈值 对比
2. 纠错码 → 硬件需求 关系
3. 实验进展 → 理论阈值 的差距分析"""

SCHEMA_DL = """## 领域编译指南（Schema）

### 核心维度
深度学习视觉领域的核心是"架构设计 → 归纳偏置 → 任务适用性"的三角关系。
重要度按"对下游任务的影响"和"SOTA 刷新程度"排序。

### 什么算重要
- 核心突破：引入新架构范式或打破 SOTA 的工作
- 关键支撑：对比实验数据、ablation study 结果
- 背景知识：CNN/Transformer 的基本操作（如卷积、注意力）
- 可以忽略：特定数据集的预处理细节、超参数搜索过程

### 交叉引用优先级
1. 架构 → 任务适用性 关系
2. 架构变体之间的演进关系
3. 优势 vs 局限 的对比分析"""

# ═══ 新版 Analyst Prompt（注入 Schema + 判断维度）══

NEW_ANALYST_PROMPT_TEMPLATE = """你是一个专业的知识编译分析师。
你的任务不只是提取概念名，而是对每段知识做出判断：什么重要、什么是新的、有没有矛盾。

{schema}

⚠️ 提取规则：
1. 【实体标准】：只提取真正的技术实体、算法模型名称或核心机制。
2. 【严禁项】：绝对禁止提取论文标题、作者、会议名、或过于泛指的大词。
3. 【宁缺毋滥】：每个知识块最多提取 1 到 4 个最核心的概念！若无核心实体，返回空列表。
4. 🌐【强制双语格式】：所有核心概念使用 `英文原名 (中文翻译)` 格式。
5. 【判断维度】：对每个概念，额外标注：
   - importance: "核心突破" / "关键支撑" / "背景知识" / "可忽略"（参考 Schema 中的定义）
   - novelty: "全新概念" / "增量补充" / "已知重申"
6. 【矛盾检测】：如果发现与常见认知矛盾的信息，标注在 conflicts 中。
7. 【深入方向】：如果发现值得深入探索的方向，标注在 directions 中。

请严格按以下 JSON 格式输出：
{{
  "new_concepts": ["概念1 (翻译1)", "概念2 (翻译2)"],
  "entries": [
    {{"name": "概念1 (翻译1)", "importance": "核心突破", "novelty": "增量补充"}},
    {{"name": "概念2 (翻译2)", "importance": "关键支撑", "novelty": "已知重申"}}
  ],
  "summary": "50-100字摘要",
  "conflicts": ["与XX的常见认知不同：..."],
  "directions": ["建议深入探索：..."]
}}"""


def call_llm(system_prompt: str, user_text: str) -> str:
    """调用 LLM，返回原始文本"""
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"【新摄入的资料】:\n{user_text}\n\n请提取核心概念并生成摘要。"}
        ],
        "temperature": 0.3,
        "max_tokens": 2000,
    }
    resp = requests.post(f"{BASE_URL}/chat/completions", headers=headers, json=payload, timeout=90)
    if resp.status_code != 200:
        print(f"  ❌ API 错误: {resp.status_code}")
        print(f"  响应: {resp.text[:500]}")
        raise RuntimeError(f"API 调用失败: {resp.status_code}")
    return resp.json()["choices"][0]["message"]["content"]


def run_ab_test():
    """执行 A/B 测试"""
    test_cases = [
        ("冷轧钢 — 连续退火", CHUNK_COLD_ROLL, SCHEMA_COLD_ROLL),
        ("量子计算 — Surface Code", CHUNK_QUANTUM, SCHEMA_QUANTUM),
        ("深度学习 — ViT vs CNN", CHUNK_DL, SCHEMA_DL),
    ]

    results = []

    for domain_name, chunk, schema in test_cases:
        print(f"\n{'='*70}")
        print(f"📚 测试领域: {domain_name}")
        print(f"{'='*70}")

        # ── A: 当前 prompt（无 Schema）──
        print("\n🅰️  调用 LLM（当前 prompt，无 Schema）...")
        t0 = time.time()
        result_a = call_llm(CURRENT_ANALYST_PROMPT, chunk)
        time_a = time.time() - t0
        print(f"  ⏱️  耗时: {time_a:.1f}s")

        # ── B: 新 prompt（有 Schema）──
        new_prompt = NEW_ANALYST_PROMPT_TEMPLATE.replace("{schema}", schema)
        print("\n🅱️  调用 LLM（新 prompt，有 Schema）...")
        t0 = time.time()
        result_b = call_llm(new_prompt, chunk)
        time_b = time.time() - t0
        print(f"  ⏱️  耗时: {time_b:.1f}s")

        results.append({
            "domain": domain_name,
            "result_a": result_a,
            "result_b": result_b,
            "time_a": time_a,
            "time_b": time_b,
        })

        # 打印对比
        print(f"\n{'─'*70}")
        print(f"📊 A/B 对比 — {domain_name}")
        print(f"{'─'*70}")
        print(f"\n🅰️  当前（无 Schema）：")
        print(result_a)
        print(f"\n🅱️  新版（有 Schema）：")
        print(result_b)
        print(f"\n⏱️  耗时对比: A={time_a:.1f}s vs B={time_b:.1f}s")

    # ── 保存完整结果 ──
    output_file = "test_schema_ab_results.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n\n✅ 完整结果已保存到 {output_file}")

    # ── 输出 Markdown 对比报告 ──
    md_file = "test_schema_ab_report.md"
    with open(md_file, "w", encoding="utf-8") as f:
        f.write("# Schema A/B 测试报告\n\n")
        f.write(f"**日期**: 2026-07-03  \n")
        f.write(f"**模型**: {MODEL}  \n")
        f.write(f"**测试领域**: {len(results)} 个\n\n")

        for r in results:
            f.write(f"## {r['domain']}\n\n")
            f.write(f"### 🅰️ 当前（无 Schema）— {r['time_a']:.1f}s\n\n")
            f.write(f"```\n{r['result_a']}\n```\n\n")
            f.write(f"### 🅱️ 新版（有 Schema）— {r['time_b']:.1f}s\n\n")
            f.write(f"```\n{r['result_b']}\n```\n\n")
            f.write("---\n\n")

    print(f"✅ Markdown 报告已保存到 {md_file}")


if __name__ == "__main__":
    run_ab_test()
