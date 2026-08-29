import re, os

files = {}
paths = {
    'app': 'app.py',
    'ingest': 'workflows/ingest_flow.py',
    'lint': 'workflows/lint_flow.py',
    'edit': 'tools/edit_tools.py',
    'analyst': 'agents/wiki_analyst.py',
    'editor': 'agents/wiki_editor.py',
    'storage': 'core/storage.py',
    'writer': 'agents/wiki_writer.py',
    'resolver': 'core/path_resolver.py',
}

for name, path in paths.items():
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as fh:
            files[name] = fh.read()
    else:
        files[name] = ''

app = files['app']

# 1. API endpoints
endpoints = re.findall(r'@(app|router)\.(get|post|put|delete|patch)\(', app)
print(f"[1] API endpoints: {len(endpoints)}")

# 2. Thread pools in ingest
ingest = files['ingest']
pools = re.findall(r'ThreadPoolExecutor\(max_workers=(\d+)\)', ingest)
print(f"[2] ThreadPool in ingest_flow: max_workers={pools}")

# 3. Locks
for name in ['app', 'ingest', 'edit', 'writer']:
    locks = len(re.findall(r'Lock\(\)|threading\.Lock|asyncio\.Lock', files[name]))
    if locks: print(f"[3] Locks in {name}: {locks}")

# 4. SSE/Stream
sse = len(re.findall(r'EventSourceResponse|StreamingResponse', app))
print(f"[4] SSE/Stream endpoints: {sse}")

# 5. LLM call sites
all_code = '\n'.join(files.values())
llm = len(re.findall(r'\.run\(|agent\.run|Agent\(', all_code))
print(f"[5] LLM call sites (all files): {llm}")

# 6. SQLite
sqlite = len(re.findall(r'sqlite|SQLite|memory\.db', app, re.I))
print(f"[6] SQLite refs in app.py: {sqlite}")

# 7. Global mutable state
globals_found = re.findall(r'(_active_ingests|_task_logs|_ingest_threads|global )', app)
print(f"[7] Global mutable state refs: {len(globals_found)}")

# 8. MinIO connection
storage = files['storage']
pool = re.findall(r'Pool|pool_size|max_connections|Minio\(', storage)
print(f"[8] MinIO: {pool}")

# 9. threading.local
tlocal = re.findall(r'threading\.local\(\)', all_code)
print(f"[9] threading.local() instances: {len(tlocal)}")

# 10. async def vs def endpoints
async_eps = len(re.findall(r'async def ', app))
sync_eps = len(re.findall(r'^def ', app, re.M))
print(f"[10] async def: {async_eps}, sync def: {sync_eps}")

# 11. Uvicorn workers check
import subprocess
r = subprocess.run(['netstat', '-ano'], capture_output=True, text=True)
listening = [l for l in r.stdout.split('\n') if '8888' in l and 'LISTENING' in l]
print(f"[11] Listening on 8888: {listening}")

# 12. File size
for name, code in files.items():
    if code:
        print(f"  {name}: {len(code)} chars, {code.count(chr(10))} lines")
