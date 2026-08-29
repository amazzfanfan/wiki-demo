import re

def _get_aliases(text):
    aliases = set()
    cleaned = re.sub(r'^(创建|新建|生成|制作)\s*', '', text)
    cleaned = re.sub(r'\s*(概念页面|概念页|页面|条目|笔记)\s*$', '', cleaned).strip()
    if cleaned != text:
        text = cleaned
    clean_text = text.lower().replace('-','').replace('_','').replace(' ','')
    if clean_text: aliases.add(clean_text)
    match = re.match(r'^(.*?)\s*[\(（](.*?)[\)）]', text)
    if match:
        part1 = match.group(1).lower().replace('-','').replace('_','').replace(' ','')
        part2 = match.group(2).lower().replace('-','').replace('_','').replace(' ','')
        if part1: aliases.add(part1)
        if part2: aliases.add(part2)
    return aliases

logos_stem = 'LOGOS (LLM驱动的端到端扎根理论开发与图式归纳框架)'
logos_aliases = _get_aliases(logos_stem)
print(f'LOGOS aliases: {logos_aliases}\n')

more_titles = [
    'Consistency / Stability (一致性/稳定性)',
    'LOGOS Consistency (一致性)',
    'LOGOS (Consistency) 一致性',
    'Descriptive Coverage (LOGOS)',
    'LOGOS的Reusability评估',
    'LOGOS Reusability (可复用性评估)',
    '可复用性 (LOGOS Reusability)',
    'Semantic Adequacy (语义充分性)',
    'Schema Induction (LOGOS图式归纳)',
    'Parsimoniousness (简约性)',
    'Iterative Codebook Refinement (迭代式代码本优化)',
    'Codebook Quality Metrics (代码本质量评估指标)',
]
for t in more_titles:
    t_aliases = _get_aliases(t)
    overlap = logos_aliases & t_aliases
    if overlap:
        print(f'  MATCH: "{t}" -> overlap={overlap}')
    else:
        print(f'  ok: "{t}" -> no overlap')
