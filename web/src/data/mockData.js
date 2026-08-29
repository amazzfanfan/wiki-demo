export const mockSandboxes = [
  { id: 1, name: 'sandbox-alpha', status: 'active', files: 23, lastUpdate: '2 分钟前' },
  { id: 2, name: 'sandbox-beta', status: 'idle', files: 17, lastUpdate: '18 分钟前' },
  { id: 3, name: 'sandbox-gamma', status: 'processing', files: 31, lastUpdate: '刚刚' },
]

export const mockGraphNodes = [
  { id: 'transformer', label: 'Transformer', group: 'core', val: 20 },
  { id: 'attention', label: '自注意力机制', group: 'core', val: 18 },
  { id: 'embeddings', label: '词嵌入', group: 'core', val: 15 },
  { id: 'bert', label: 'BERT', group: 'model', val: 16 },
  { id: 'gpt', label: 'GPT', group: 'model', val: 17 },
  { id: 'rlhf', label: 'RLHF', group: 'training', val: 14 },
  { id: 'rag', label: 'RAG', group: 'architecture', val: 16 },
  { id: 'fine-tuning', label: '微调', group: 'training', val: 13 },
  { id: 'prompt', label: 'Prompt 工程', group: 'architecture', val: 12 },
  { id: 'tokenization', label: '分词器', group: 'core', val: 10 },
  { id: 'mamba', label: 'Mamba 架构', group: 'model', val: 11 },
  { id: 'moe', label: '混合专家 MoE', group: 'architecture', val: 14 },
  { id: 'quantization', label: '量化', group: 'training', val: 9 },
  { id: 'distillation', label: '知识蒸馏', group: 'training', val: 10 },
]

export const mockGraphLinks = [
  { source: 'transformer', target: 'attention' },
  { source: 'transformer', target: 'embeddings' },
  { source: 'transformer', target: 'bert' },
  { source: 'transformer', target: 'gpt' },
  { source: 'bert', target: 'fine-tuning' },
  { source: 'gpt', target: 'rlhf' },
  { source: 'gpt', target: 'prompt' },
  { source: 'rag', target: 'embeddings' },
  { source: 'rag', target: 'transformer' },
  { source: 'attention', target: 'tokenization' },
  { source: 'mamba', target: 'transformer' },
  { source: 'moe', target: 'gpt' },
  { source: 'quantization', target: 'distillation' },
  { source: 'distillation', target: 'bert' },
  { source: 'mamba', target: 'attention' },
  { source: 'moe', target: 'transformer' },
  { source: 'rlhf', target: 'prompt' },
]

export const mockInboxItems = [
  { id: 1, title: 'Transformer.md', source: '需求雷达触发', status: 'pending' },
  { id: 2, title: 'Mamba架构.md', source: '幽灵节点自动填充', status: 'pending' },
  { id: 3, title: 'RLHF.md', source: '同义词合并', status: 'approved' },
]

export const mockRadarItems = [
  { id: 1, term: 'Mamba架构', count: 2, total: 3, color: 'yellow' },
  { id: 2, term: '思维链推理', count: 1, total: 3, color: 'yellow' },
  { id: 3, term: 'LoRA 微调', count: 3, total: 3, color: 'red' },
  { id: 4, term: 'KV Cache', count: 1, total: 2, color: 'yellow' },
]

export const mockAuditLogs = [
  { id: 1, user: 'Hayden', action: '批准了节点 [Transformer] 入库', time: '10:42', type: 'human' },
  { id: 2, user: '系统', action: '合并了同义词 "自注意力" → "Self-Attention"', time: '10:38', type: 'system' },
  { id: 3, user: 'Hayden', action: '拒绝了草稿 [Mamba架构-v2]', time: '10:35', type: 'human' },
  { id: 4, user: '系统', action: '检测到 3 条死链，已加入修复队列', time: '10:30', type: 'system' },
  { id: 5, user: '系统', action: '完成 lint_flow 审查，0 孤立页面', time: '10:28', type: 'system' },
  { id: 6, user: 'Hayden', action: '触发了 autofill_flow 幽灵节点填补', time: '10:15', type: 'human' },
  { id: 7, user: '系统', action: '新节点 [知识蒸馏] 已通过审核入库', time: '10:10', type: 'system' },
  { id: 8, user: '系统', action: 'MAP 阶段完成，提取 12 个概念碎片', time: '09:58', type: 'system' },
]

export const mockQueryResponse = `## Transformer 架构核心原理

Transformer 是一种基于**自注意力机制（Self-Attention）**的序列到序列模型架构，完全摒弃了传统的 RNN/CNN 结构。

### 关键组件

1. **多头注意力（Multi-Head Attention）**
   - 将输入投影到多个子空间，分别计算注意力后拼接
   - 公式：\`MultiHead(Q,K,V) = Concat(head₁,...,headₙ)Wᴼ\`

2. **位置编码（Positional Encoding）**
   - 由于没有序列顺序，需要通过正弦函数注入位置信息

3. **层归一化 + 残差连接**
   - 每个子层都采用 \`LayerNorm(x + Sublayer(x))\` 结构

### 与 RAG 的关系

在 [[rag]] 系统中，Transformer 作为编码器的核心，负责将文档和查询映射到同一向量空间，从而实现语义相似度匹配。

> 参考资料: "Attention Is All You Need" (Vaswani et al., 2017)`
