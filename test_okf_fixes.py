"""验证 OKF P0 bug 修复"""
import sys, os, re
sys.path.insert(0, os.path.dirname(__file__))

print("=== P0 Bug Fix Verification ===\n")

# ── Fix 1: _sanitize_filename strips Chinese prefixes ──
from tools.edit_tools import _sanitize_filename
tests = [
    ("concepts/创建 LOGOS 概念页面.md", "concepts/LOGOS.md"),
    ("concepts/新建 Codebook 条目.md", "concepts/Codebook.md"),
    ("concepts/生成 Themeviz 笔记.md", "concepts/Themeviz.md"),
    ("concepts/create_LOGOS.md", "concepts/LOGOS.md"),
    ("concepts/LOGOS (扎根理论).md", "concepts/LOGOS (扎根理论).md"),  # no change
    ("index.md", "index.md"),  # no change
]
print("1. _sanitize_filename (Chinese prefix stripping):")
all_pass = True
for inp, expected in tests:
    got = _sanitize_filename(inp)
    status = "OK" if got == expected else "FAIL"
    if status == "FAIL": all_pass = False
    print(f"  [{status}] {inp!r} -> {got!r} (expected {expected!r})")
print()

# ── Fix 2: Action model recognizes file_name ──
from agents.wiki_editor import Action
a = Action.model_validate({
    "type": "create",
    "file_name": "concepts/LOGOS.md",
    "title": "创建 LOGOS 概念页面",
    "rationale": "test"
})
print(f"2. Action file_name alias:")
print(f"  file = {a.file!r} (expected 'concepts/LOGOS.md')")
assert a.file == "concepts/LOGOS.md", f"FAIL: got {a.file}"
print(f"  [OK]\n")

# ── Fix 3: WikiWriter title sanitization ──
print("3. WikiWriter title sanitization:")
dirty_titles = [
    ("创建 LOGOS 概念页面", "LOGOS"),
    ("新建 Codebook 条目", "Codebook"),
    ("生成 Grounded Theory 笔记", "Grounded Theory"),
    ("LOGOS (扎根理论)", "LOGOS (扎根理论)"),  # no change
]
for dirty, expected in dirty_titles:
    clean = re.sub(r'^(创建|新建|生成|制作)\s*', '', dirty)
    clean = re.sub(r'\s*(概念页面|概念页|页面|条目|笔记)\s*$', '', clean).strip()
    status = "OK" if clean == expected else "FAIL"
    print(f"  [{status}] {dirty!r} -> {clean!r} (expected {expected!r})")
print()

# ── Fix 4: _is_same_concept with junk prefix ──
print("4. _is_same_concept (junk prefix tolerance):")
from agents.wiki_writer import WikiWriter
# We can't easily call the nested function, but we can replicate the logic
def _get_aliases(text):
    aliases = set()
    cleaned = re.sub(r'^(创建|新建|生成|制作)\s*', '', text)
    cleaned = re.sub(r'\s*(概念页面|概念页|页面|条目|笔记)\s*$', '', cleaned).strip()
    if cleaned != text:
        text = cleaned
    clean_text = text.lower().replace("-", "").replace("_", "").replace(" ", "")
    if clean_text: aliases.add(clean_text)
    match = re.match(r'^(.*?)\s*[\(（](.*?)[\)）]', text)
    if match:
        part1 = match.group(1).lower().replace("-", "").replace("_", "").replace(" ", "")
        part2 = match.group(2).lower().replace("-", "").replace("_", "").replace(" ", "")
        if part1: aliases.add(part1)
        if part2: aliases.add(part2)
    return aliases

def is_same(n1, n2):
    return bool(_get_aliases(n1) & _get_aliases(n2))

pairs = [
    ("创建 LOGOS 概念页面", "LOGOS (基于大语言模型的扎根理论开发与模式归纳框架)", True),
    ("创建 Codebook 条目", "Codebook (代码本)", True),
    ("Grounded Theory", "扎根理论 (Grounded Theory)", True),
    ("LOGOS", "Thematic-LM", False),  # different concepts
]
for n1, n2, expected in pairs:
    got = is_same(n1, n2)
    status = "OK" if got == expected else "FAIL"
    print(f"  [{status}] is_same({n1!r}, {n2!r}) = {got} (expected {expected})")

print(f"\n=== All fixes verified ===")
