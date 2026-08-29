import os

from minio import Minio
from pathlib import Path

endpoint = os.getenv("MINIO_ENDPOINT")
access_key = os.getenv("MINIO_ACCESS_KEY")
secret_key = os.getenv("MINIO_SECRET_KEY")
BUCKET = os.getenv("MINIO_BUCKET", "wiki-test")

if not endpoint or not access_key or not secret_key:
    raise RuntimeError("请先配置 MINIO_ENDPOINT、MINIO_ACCESS_KEY 和 MINIO_SECRET_KEY")

client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=False)
count = 0
for f in Path("data").rglob("*"):
    if not f.is_file():
        continue
    if f.suffix in (".db",) or "lancedb" in str(f) or "__pycache__" in str(f):
        print(f"⏭️  跳过: {f.name}")
        continue
    key = str(f.relative_to(Path("data"))).replace("\\", "/")
    # 加 wiki/ 或 raw/ 前缀取决于路径本身
    # 因为 relative_to(data) 已经包含 wiki/ 或 raw/
    full_key = key
    client.fput_object(BUCKET, full_key, str(f))
    count += 1
    print(f"✅ {full_key}")
print(f"\n迁移完成，共上传 {count} 个文件")
