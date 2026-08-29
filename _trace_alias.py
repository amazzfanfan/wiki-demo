import re

def _get_aliases_OLD(text):
    aliases = set()
    clean_text = text.lower().replace('-', '').replace('_', '').replace(' ', '')
    if clean_text: aliases.add(clean_text)
    match = re.match(r'^(.*?)\s*[\(（](.*?)[\)）]', text)
    if match:
        part1 = match.group(1).lower().replace('-', '').replace('_', '').replace(' ', '')
        part2 = match.group(2).lower().replace('-', '').replace('_', '').replace(' ', '')
        if part1: aliases.add(part1)
        if part2: aliases.add(part2)
    return aliases

existing = 'LOGOS (基于大语言模型的扎根理论开发与模式归纳框架)'
new_name = '创建 LOGOS 概念页面'

old_a = _get_aliases_OLD(existing)
new_a = _get_aliases_OLD(new_name)

print('=== OLD (original) ===')
print('Existing aliases:', old_a)
print('New name aliases:', new_a)
print('Intersection:', old_a & new_a)
print('Match:', bool(old_a & new_a))

def _get_aliases_NEW(text):
    aliases = set()
    cleaned = re.sub(r'^(创建|新建|生成|制作)\s*', '', text)
    cleaned = re.sub(r'\s*(概念页面|概念页|页面|条目|笔记)\s*$', '', cleaned).strip()
    if cleaned != text: text = cleaned
    clean_text = text.lower().replace('-', '').replace('_', '').replace(' ', '')
    if clean_text: aliases.add(clean_text)
    match = re.match(r'^(.*?)\s*[\(（](.*?)[\)）]', text)
    if match:
        part1 = match.group(1).lower().replace('-', '').replace('_', '').replace(' ', '')
        part2 = match.group(2).lower().replace('-', '').replace('_', '').replace(' ', '')
        if part1: aliases.add(part1)
        if part2: aliases.add(part2)
    return aliases

old_a2 = _get_aliases_NEW(existing)
new_a2 = _get_aliases_NEW(new_name)

print()
print('=== NEW (fixed) ===')
print('Existing aliases:', old_a2)
print('New name aliases:', new_a2)
print('Intersection:', old_a2 & new_a2)
print('Match:', bool(old_a2 & new_a2))
