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

def _is_same_concept_OLD(name1, name2):
    return bool(_get_aliases(name1) & _get_aliases(name2))

def _is_same_concept_NEW(name1, name2):
    """加强版：需要至少 2 个别名重叠，或完全匹配"""
    a1 = _get_aliases(name1)
    a2 = _get_aliases(name2)
    overlap = a1 & a2
    if not overlap:
        return False
    if len(overlap) >= 2:
        return True
    # 只有 1 个重叠：必须包含 full normalized name（最可靠的那个）
    n1 = name1.lower().replace('-','').replace('_','').replace(' ','')
    n2 = name2.lower().replace('-','').replace('_','').replace(' ','')
    return n1 == n2

logos_stem = 'LOGOS (LLM驱动的端到端扎根理论开发与图式归纳框架)'

test_pairs = [
    ('LOGOS (Consistency)', True),
    ('Descriptive Coverage (LOGOS)', True),
    ('LOGOS (Reusability)', True),
    ('LOGOS框架中的可复用性评估', True),
    ('Reusability (可复用性)', False),
    ('subsumption (上下位关系)', False),
    ('equivalence (等价关系)', False),
    ('orthogonality (正交关系)', False),
    ('Semantic Adequacy (语义充分性)', False),
    ('Parsimoniousness (简约性)', False),
    ('Iterative Codebook Refinement (迭代式代码本优化)', False),
    ('Codebook Quality Metrics (代码本质量评估指标)', False),
    # 同义词测试：这些应该匹配
    ('LOGOS', False),  # 同义词，但只有一个别名
    ('logos', False),  # 完全一样（小写），但不是重复页面
]

print(f'LOGOS aliases: {_get_aliases(logos_stem)}\n')
print(f'{"Title":<55} {"OLD":>4} {"NEW":>4} {"Expected":>8}')
print('-' * 80)
for title, should_match in test_pairs:
    old = _is_same_concept_OLD(logos_stem, title)
    new = _is_same_concept_NEW(logos_stem, title)
    old_ok = '✅' if old == should_match else '❌'
    new_ok = '✅' if new == should_match else '❌'
    print(f'{title:<55} {old!s:>4} {new!s:>4} {"match" if should_match else "no match":>8}')
