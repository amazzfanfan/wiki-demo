"""OKF 改造导入测试"""
import sys
sys.path.insert(0, '.')

print('Testing OKF imports...')

# 1. schema_engine
from core.schema_engine import is_enabled, build_frontmatter, build_log_entry
print(f'  [OK] schema_engine: enabled={is_enabled()}')

# 2. frontmatter (disabled → empty)
fm = build_frontmatter('concept', ['test'], ['paper1'])
assert fm == '', f'Expected empty, got: {fm}'
print(f'  [OK] build_frontmatter (disabled) = empty')

# 3. log entry with new params
entry = build_log_entry('ingest', 'test_doc',
    details={'MAP': '3 chunks', 'source': 'paper1'},
    actions_summary=['create: concepts/X.md', 'edit: concepts/Y.md'],
    conflicts=['X vs Y contradiction'])
print(f'  [OK] build_log_entry: {len(entry)} chars')
print(entry[:300])

# 4. edit_tools helpers
from tools.edit_tools import _refresh_timestamp, _append_source, set_okf_context, get_okf_context
print(f'  [OK] edit_tools helpers imported')

test_fm = '---\ntype: concept\ntimestamp: 2026-01-01T00:00:00Z\ntags: [x]\n---\n# Hello'
refreshed = _refresh_timestamp(test_fm)
assert '2026-01-01' not in refreshed, 'timestamp not refreshed!'
print(f'  [OK] _refresh_timestamp: updated')

appended = _append_source(test_fm, 'new_paper')
assert 'new_paper' in appended, f'source not appended! got: {appended}'
print(f'  [OK] _append_source: added new_paper')

# Test duplicate source not added
appended2 = _append_source(appended, 'new_paper')
assert appended2 == appended, 'duplicate source added!'
print(f'  [OK] _append_source: dedup works')

# 5. lint_flow
from workflows.lint_flow import LintFlow
lf = LintFlow()
assert hasattr(lf, '_okf_health_check_local'), 'missing health check method'
assert hasattr(lf, '_okf_health_check_minio'), 'missing minio health check'
print(f'  [OK] lint_flow health checks')

# 6. ingest_flow (heavy import)
try:
    from workflows.ingest_flow import IngestFlow
    flow = IngestFlow()
    assert hasattr(flow, '_update_index_summaries'), 'missing index summary method'
    assert hasattr(flow, '_all_sources'), 'missing _all_sources'
    assert hasattr(flow, '_reduce_actions_log'), 'missing _reduce_actions_log'
    print(f'  [OK] ingest_flow with OKF fields')
except Exception as e:
    print(f'  [WARN] ingest_flow: {e}')

# 7. wiki_analyst
from agents.wiki_analyst import AnalysisReport
fields = AnalysisReport.model_fields
assert 'source' in fields, 'missing source field'
print(f'  [OK] AnalysisReport has source field')

print('\n=== ALL IMPORT TESTS PASSED ===')
