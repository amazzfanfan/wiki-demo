# Schema A/B 测试报告

**日期**: 2026-07-03  
**模型**: qwen-plus  
**测试领域**: 3 个

## 冷轧钢 — 连续退火

### 🅰️ 当前（无 Schema）— 1.8s

```
[]
```

### 🅱️ 新版（有 Schema）— 8.2s

```
{
  "new_concepts": ["Continuous Annealing (连续退火)", "Overaging Temperature (过时效温度)", "Martensite Volume Fraction (马氏体体积分数)", "Strength-Ductility Balance (强塑平衡)"],
  "entries": [
    {"name": "Continuous Annealing (连续退火)", "importance": "核心突破", "novelty": "增量补充"},
    {"name": "Overaging Temperature (过时效温度)", "importance": "核心突破", "novelty": "增量补充"},
    {"name": "Martensite Volume Fraction (马氏体体积分数)", "importance": "关键支撑", "novelty": "已知重申"},
    {"name": "Strength-Ductility Balance (强塑平衡)", "importance": "核心突破", "novelty": "增量补充"}
  ],
  "summary": "本研究揭示连续退火中退火温度与过时效温度对DP780双相钢强塑性能的非单调调控机制：760–820°C升温提升抗拉强度与延伸率，820°C达最优强塑积；超820°C则因马氏体过量（~35%）及带状组织引发性能回落。过时效温度通过调控碳化物析出/粗化，协同影响屈服强度、延伸率与烘烤硬化性。",
  "conflicts": ["与‘退火温度越高、强度越低’的常规认知不同：本实验显示在760–820°C区间内，强度随退火温度升高而上升，表明该区间内再结晶与碳配分协同优化主导性能提升"],
  "directions": ["建议深入探索：820°C附近奥氏体逆转变动力学与碳在铁素体/马氏体间配分的定量关系；过时效段440–480°C窗口内碳化物尺寸分布与BH值的定量构效模型"]
}
```

---

## 量子计算 — Surface Code

### 🅰️ 当前（无 Schema）— 6.9s

```
核心概念提取：  
`Surface code (表面码)`、`color code (色码)`、`honeycomb code (蜂巢码)`、`threshold theorem (容错阈值定理)`

摘要：  
Surface code 是当前最具实用前景的拓扑量子纠错码，具有约 1% 的高容错阈值（远高于 Steane 码和 Shor 码），其稳定子结构基于二维正方格子上的 star/plaquette 算子。Google 2023 年在 Willow 芯片上首次实验验证了 distance-5/7 surface code 的“below-threshold”缩放行为（逻辑错误率随距离增加而下降）。然而，其大规模应用受限于量子比特开销大、测量错误敏感及边界几何约束。作为对比，color code 支持横跨 Clifford 门但阈值更低（~0.1%）；honeycomb code 则通过动态测量提升效率，尚待大规模实证。三者共同体现拓扑编码在平衡阈值、门操作性与硬件可行性间的权衡路径。
```

### 🅱️ 新版（有 Schema）— 8.4s

```
{
  "new_concepts": ["Surface code (表面码)", "Color code (颜色码)", "Honeycomb code (蜂巢码)", "Star operator (星型算子)", "Plaquette operator (面元算子)"],
  "entries": [
    {"name": "Surface code (表面码)", "importance": "核心突破", "novelty": "增量补充"},
    {"name": "Color code (颜色码)", "importance": "关键支撑", "novelty": "已知重申"},
    {"name": "Honeycomb code (蜂巢码)", "importance": "核心突破", "novelty": "增量补充"},
    {"name": "Star operator (星型算子)", "importance": "背景知识", "novelty": "已知重申"},
    {"name": "Plaquette operator (面元算子)", "importance": "背景知识", "novelty": "已知重申"}
  ],
  "summary": "Surface code 因约1%的高容错阈值和实验验证（Google 2023, distance-5/7）成为当前最可行的拓扑纠错方案；color code 支持横跨Clifford门但阈值更低（0.1%）；honeycomb code 通过动态测量提升效率，尚缺大规模验证。硬件开销（~2d²比特）、测量错误与边界约束是主要工程瓶颈。",
  "conflicts": ["与部分早期文献认知不同：surface code 的实际实验阈值受测量错误显著压制，未达理论1%；'below-threshold'行为（Λ≈2.3）在distance-3→5→7中被首次实证，但该缩放因子低于理想指数抑制预期（需Λ>3才显著优于阈值边界）"],
  "directions": ["建议深入探索：测量错误主导下的有效阈值建模；rough/smooth boundary在超导芯片中的几何优化方案；honeycomb code与surface code在相同硬件平台上的解码开销对比"]
}
```

---

## 深度学习 — ViT vs CNN

### 🅰️ 当前（无 Schema）— 5.4s

```
核心概念提取：  
- Vision Transformer (视觉变换器)  
- Self-Attention (自注意力机制)  
- Patch Embedding (图像块嵌入)  
- Inductive Bias (归纳偏置)  

摘要：  
Vision Transformer (ViT) 通过将图像划分为 patch 并利用 Self-Attention 建立全局依赖，摆脱了 CNN 的卷积归纳偏置，在大规模数据下展现出更强的可扩展性与跨模态兼容性；但其 O(n²) 计算复杂度、对小数据泛化能力弱（因缺乏 Inductive Bias）以及单尺度特征输出等局限，推动了如 Swin Transformer 等改进架构的发展。
```

### 🅱️ 新版（有 Schema）— 7.4s

```
{
  "new_concepts": ["Vision Transformer (视觉变换器)", "patch embedding (图像块嵌入)", "inductive bias (归纳偏置)", "self-attention (自注意力机制)"],
  "entries": [
    {"name": "Vision Transformer (视觉变换器)", "importance": "核心突破", "novelty": "全新概念"},
    {"name": "patch embedding (图像块嵌入)", "importance": "关键支撑", "novelty": "增量补充"},
    {"name": "inductive bias (归纳偏置)", "importance": "关键支撑", "novelty": "已知重申"},
    {"name": "self-attention (自注意力机制)", "importance": "背景知识", "novelty": "已知重申"}
  ],
  "summary": "ViT 首次将纯 Transformer 架构用于图像分类，通过 patch embedding 和位置编码替代卷积；其全局感受野、强扩展性与多模态兼容性构成核心优势，但高计算复杂度、缺乏归纳偏置及单尺度特征限制了其在小数据与密集预测任务中的直接应用。",
  "conflicts": ["与‘Transformer 必须依赖海量数据’的常见认知不同：DeiT 证明 ViT 可通过蒸馏和增强在 ImageNet-1k 上达 83.1%，显著降低数据依赖"],
  "directions": ["建议深入探索：如何在保持 ViT 全局建模能力的同时注入轻量级归纳偏置（如局部注意力约束或 hybrid CNN-ViT 模块）；以及高效多尺度 ViT 架构的设计原理（如 Swin 的 shifted window 机制）"]
}
```

---

