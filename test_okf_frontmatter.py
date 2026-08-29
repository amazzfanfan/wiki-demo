"""OKF frontmatter 生成测试 (ENABLE_SCHEMA=true)"""
import sys, os
sys.path.insert(0, '.')
os.environ['ENABLE_SCHEMA'] = 'true'

# Force reimport with ENABLE_SCHEMA=true
import importlib
import core.schema_engine
importlib.reload(core.schema_engine)

from core.schema_engine import is_enabled, build_frontmatter, build_log_entry
print(f'ENABLE_SCHEMA = {is_enabled()}')
assert is_enabled(), 'Schema should be enabled!'

# 1. Frontmatter generation
fm = build_frontmatter('工艺参数', ['退火', 'DP780'], ['论文1_DP780退火温度'])
print('\n=== Frontmatter ===')
print(fm)
assert '---' in fm
assert 'type: 工艺参数' in fm
assert 'timestamp:' in fm
assert '论文1_DP780退火温度' in fm
print('[OK] frontmatter generation')

# 2. _build_body with schema
import tools.edit_tools
importlib.reload(tools.edit_tools)
from tools.edit_tools import _build_body

body = _build_body(
    title='退火温度 (Annealing Temperature)',
    tags=['退火', 'DP780'],
    abstract='退火温度是连续退火工艺中控制双相钢组织演变的关键参数。',
    content='详细内容...',
    page_type='工艺参数',
    source=['论文1_DP780退火温度']
)
print('\n=== Full Page Body ===')
print(body[:500])
assert body.startswith('---'), 'Should start with frontmatter!'
assert 'type: 工艺参数' in body
assert '论文1_DP780退火温度' in body
assert '# 退火温度 (Annealing Temperature)' in body
print('[OK] _build_body with OKF frontmatter')

# 3. _build_body without schema (backward compat)
os.environ['ENABLE_SCHEMA'] = 'false'
importlib.reload(core.schema_engine)
importlib.reload(tools.edit_tools)
from tools.edit_tools import _build_body as _build_body_off

body_off = _build_body_off(
    title='退火温度',
    tags=['退火'],
    abstract='摘要内容',
    content='详细内容',
    page_type='工艺参数',
    source=['论文1']
)
assert not body_off.startswith('---'), f'Should NOT start with frontmatter when disabled! Got: {body_off[:50]}'
assert '# 退火温度' in body_off
print('[OK] backward compat: no frontmatter when disabled')

# 4. _append_source edge cases
from tools.edit_tools import _append_source

# No frontmatter → no change
plain = '# Hello\nNo frontmatter here.'
assert _append_source(plain, 'paper1') == plain
print('[OK] _append_source: no-op on plain content')

# Existing source → append
with_source = '---\ntype: concept\ntimestamp: 2026-01-01T00:00:00Z\nsource: [paper1]\ntags: [x]\n---\n# Test'
result = _append_source(with_source, 'paper2')
assert 'paper2' in result
assert 'paper1' in result
print(f'[OK] _append_source: appended to existing list')
print(f'  Result source line: {[l for l in result.split(chr(10)) if "source" in l]}')

# Duplicate → no change
result2 = _append_source(result, 'paper1')
assert result2 == result
print('[OK] _append_source: dedup works')

# 5. _refresh_timestamp
from tools.edit_tools import _refresh_timestamp
import datetime
old = '---\ntype: x\ntimestamp: 2020-01-01T00:00:00Z\n---\n# T'
refreshed = _refresh_timestamp(old)
assert '2020-01-01' not in refreshed
today = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d')
assert today in refreshed
print(f'[OK] _refresh_timestamp: {today} in refreshed')

# No frontmatter → no change
assert _refresh_timestamp('# No FM') == '# No FM'
print('[OK] _refresh_timestamp: no-op on plain content')

print('\n=== ALL OKF TESTS PASSED ===')
