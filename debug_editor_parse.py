"""Debug: see what Editor actually returns"""
import requests, json, re

API_KEY = 'sk-xxx'
BASE_URL = 'https://dashscope.aliyuncs.com/compatible-mode/v1'

chunk = 'DP780双相钢退火温度760-850度，820度最优，抗拉强度842MPa，850度性能下降至810MPa'

system = (
    "你是一个严谨的本地知识库主编。\n"
    "你必须严格按以下 JSON 格式输出，不要输出其他格式：\n"
    '{\n'
    '  "actions": [\n'
    '    {"type": "create", "file": "concepts/概念.md", "content": "内容", "rationale": "理由"},\n'
    '    {"type": "append_link", "file": "index.md", "link": "- [[概念]]", "rationale": "理由"}\n'
    '  ]\n'
    '}\n'
    "type 只能是 create / edit / append_link 三选一。"
)

headers = {'Authorization': 'Bearer ' + API_KEY, 'Content-Type': 'application/json'}
payload = {
    'model': 'qwen-plus',
    'messages': [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': '资料：' + chunk + '\n知识库为空，请输出融合决策'}
    ],
    'temperature': 0.3,
    'max_tokens': 2000,
}
resp = requests.post(BASE_URL + '/chat/completions', headers=headers, json=payload, timeout=60)
data = resp.json()
content = data['choices'][0]['message']['content']
print('=== RAW (first 800 chars) ===')
print(content[:800])
print('=== END ===')
print()

# Test all parse strategies
try:
    d = json.loads(content.strip())
    print('Strategy 1 (direct):', type(d).__name__, 'keys:', list(d.keys()) if isinstance(d, dict) else 'list')
except Exception as e:
    print('Strategy 1: FAIL -', e)

m = re.search(r'```(?:json)?\s*\n([\s\S]*?)```', content)
if m:
    try:
        d = json.loads(m.group(1).strip())
        print('Strategy 2 (code block):', type(d).__name__)
    except Exception as e:
        print('Strategy 2: FAIL -', e)
else:
    print('Strategy 2: no match')

m = re.search(r'\{[\s\S]*\}', content)
if m:
    try:
        d = json.loads(m.group())
        print('Strategy 3 (braces):', type(d).__name__, 'keys:', list(d.keys()) if isinstance(d, dict) else '')
        if isinstance(d, dict) and 'actions' in d:
            acts = d['actions']
            print('  actions count:', len(acts), 'first type:', type(acts[0]).__name__ if acts else 'empty')
            if acts and isinstance(acts[0], dict):
                print('  first action keys:', list(acts[0].keys()))
    except Exception as e:
        print('Strategy 3: FAIL -', e)
else:
    print('Strategy 3: no match')
