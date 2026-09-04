"""
core/storage.py — 统一存储后端（本地 / MinIO）

设计理念：
  - 采用「策略模式」：StorageBackend 定义统一接口，MinIO / Local 各自实现
  - 通过 get_storage() 工厂函数获取实例，调用方无需关心底层是 MinIO 还是本地
  - 消除 app.py 中 65 处 `if USE_MINIO` 分支，所有存储操作统一走 get_storage()
  - MinIO 模式下 client 单例复用（避免每次操作都建立新连接）
  - Local 模式下 key 直接映射到 data/ 目录（保持与旧版行为一致）

使用方式：
    from core.storage import get_storage

    s = get_storage()
    content = s.read_text("wiki/hwd/ws1/concepts/LoRA.md")
    s.write_text("wiki/hwd/ws1/concepts/QLoRA.md", "# QLoRA\\n...")
    keys = s.list_keys("wiki/hwd/ws1/concepts/")

注意：
  - 本模块只负责「存储层」的读写抽象
  - MinIO 对象 key 的路径拼接仍由 core/path_resolver.py 的 minio_*() 函数负责
  - 环境变量 USE_MINIO 控制后端选择（true → MinIO，其他 → Local）
"""

import io
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

# ── 加载 .env（确保本模块先于 path_resolver 被导入时也能拿到环境变量）──
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass  # python-dotenv 未安装，依赖系统环境变量或 IDE 注入

# ── 全局开关：是否使用 MinIO 作为存储后端 ──
USE_MINIO = os.environ.get("USE_MINIO", "false").lower() == "true"


# ═══════════════════════════════════════════
# 抽象基类 — 定义统一接口
# ═══════════════════════════════════════════

class StorageBackend(ABC):
    """
    统一存储接口。

    所有存储操作（读/写/删/列举/上传/下载）都通过此抽象类定义，
    子类负责具体实现。调用方只需面向此接口编程。

    key 的含义：
      - MinIO 模式：对象键，如 "wiki/hwd/ws1/concepts/LoRA.md"
      - Local 模式：相对于 data/ 的路径，如 "wiki/hwd/ws1/concepts/LoRA.md"
        （Local 模式会自动拼接 data/ 前缀，调用方无需关心）
    """

    # ── 文本读写 ──

    @abstractmethod
    def read_text(self, key: str) -> str:
        """读取文本内容（UTF-8 解码）"""
        pass

    @abstractmethod
    def write_text(self, key: str, content: str):
        """写入文本内容（UTF-8 编码，content_type 为 text/markdown）"""
        pass

    # ── 二进制读写 ──

    @abstractmethod
    def read_bytes(self, key: str) -> bytes:
        """读取二进制内容（用于 PDF、图片等非文本文件）"""
        pass

    @abstractmethod
    def write_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream"):
        """写入二进制内容（用于接收前端上传的文件流等）"""
        pass

    # ── 查询与列举 ──

    @abstractmethod
    def exists(self, key: str) -> bool:
        """检查指定 key 的对象是否存在"""
        pass

    @abstractmethod
    def list_keys(self, prefix: str) -> list[str]:
        """
        列举指定前缀下的所有对象键。

        示例：
            list_keys("wiki/hwd/ws1/concepts/")
            → ["wiki/hwd/ws1/concepts/LoRA.md", "wiki/hwd/ws1/concepts/QLoRA.md", ...]
        """
        pass

    # ── 删除 ──

    @abstractmethod
    def delete(self, key: str):
        """删除单个对象"""
        pass

    @abstractmethod
    def delete_prefix(self, prefix: str) -> int:
        """
        批量删除指定前缀下的所有对象。
        返回成功删除的数量。
        """
        pass

    # ── 本地文件互传 ──

    @abstractmethod
    def download_to(self, key: str, local_path: Path):
        """将对象下载到本地文件路径（摄入时临时使用，用完即删）"""
        pass

    @abstractmethod
    def upload_from(self, key: str, local_path: Path):
        """将本地文件上传为对象"""
        pass


# ═══════════════════════════════════════════
# MinIO 实现
# ═══════════════════════════════════════════

class MinIOBackend(StorageBackend):
    """
    MinIO 对象存储后端。

    特点：
      - client 在 __init__ 时创建一次，后续所有操作复用（避免连接开销）
      - bucket 从环境变量 MINIO_BUCKET 读取，默认 "wiki-test"
      - 所有操作直接面向 MinIO 服务器，不在本地留任何文件

    与旧版 storage.py 的区别：
      - 旧版：模块级函数 + 每次 get_client() 新建 Minio 实例
      - 新版：类封装 + client 单例复用
    """

    def __init__(self):
        from minio import Minio

        self._client = Minio(
            endpoint=os.environ.get("MINIO_ENDPOINT", "localhost:9000"),
            access_key=os.environ.get("MINIO_ACCESS_KEY", ""),
            secret_key=os.environ.get("MINIO_SECRET_KEY", ""),
            secure=False,
        )
        self.bucket = os.environ.get("MINIO_BUCKET", "your_bucket")

    # ── 文本读写 ──

    def read_text(self, key: str) -> str:
        """从 MinIO 读取对象并解码为 UTF-8 字符串"""
        resp = self._client.get_object(self.bucket, key)
        try:
            return resp.read().decode("utf-8")
        finally:
            # 必须关闭并释放连接，否则连接池会耗尽
            resp.close()
            resp.release_conn()

    def write_text(self, key: str, content: str):
        """将字符串编码为 UTF-8 后写入 MinIO"""
        data = content.encode("utf-8")
        self._client.put_object(
            self.bucket, key, io.BytesIO(data),
            length=len(data), content_type="text/markdown"
        )

    # ── 二进制读写 ──

    def read_bytes(self, key: str) -> bytes:
        """从 MinIO 读取对象的原始字节"""
        resp = self._client.get_object(self.bucket, key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    def write_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream"):
        """将字节数据写入 MinIO（用于接收前端上传的文件流）"""
        self._client.put_object(
            self.bucket, key, io.BytesIO(data),
            length=len(data), content_type=content_type
        )

    # ── 查询与列举 ──

    def exists(self, key: str) -> bool:
        """通过 stat_object 检查对象是否存在（不存在时抛 S3Error）"""
        from minio.error import S3Error
        try:
            self._client.stat_object(self.bucket, key)
            return True
        except S3Error:
            return False

    def list_keys(self, prefix: str) -> list[str]:
        """列举指定前缀下的所有对象键（recursive=True 递归子目录）"""
        return [
            obj.object_name
            for obj in self._client.list_objects(
                self.bucket, prefix=prefix, recursive=True
            )
        ]

    # ── 删除 ──

    def delete(self, key: str):
        """删除 MinIO 中的单个对象"""
        self._client.remove_object(self.bucket, key)

    def delete_prefix(self, prefix: str) -> int:
        """
        批量删除指定前缀下的所有对象。
        使用 MinIO 的 remove_objects 批量接口，比逐个删除高效。
        返回成功删除的数量。
        """
        from minio.deleteobjects import DeleteObject

        keys = self.list_keys(prefix)
        if not keys:
            return 0

        # 批量删除（一次调用处理多个对象）
        errors = list(self._client.remove_objects(
            self.bucket,
            [DeleteObject(key) for key in keys]
        ))
        if errors:
            print(f"⚠️ MinIO 批量删除 {prefix} 有 {len(errors)} 个对象删除失败", flush=True)
        return len(keys) - len(errors)

    # ── 本地文件互传 ──

    def download_to(self, key: str, local_path: Path):
        """
        从 MinIO 下载文件到本地路径。
        主要用于摄入时临时下载 raw 文件（用完即删，不在本地保留）。
        """
        self._client.fget_object(self.bucket, key, str(local_path))

    def upload_from(self, key: str, local_path: Path):
        """将本地文件上传到 MinIO（fput_object 自动处理大文件分片）"""
        self._client.fput_object(self.bucket, key, str(local_path))


# ═══════════════════════════════════════════
# 本地文件系统实现
# ═══════════════════════════════════════════

class LocalBackend(StorageBackend):
    """
    本地文件系统后端。

    特点：
      - key 直接映射到 data/ 目录下的文件路径
      - 例如 key="wiki/hwd/ws1/concepts/LoRA.md" → data/wiki/hwd/ws1/concepts/LoRA.md
      - 写入时自动创建父目录（mkdir -p 等效）
      - 删除时静默处理（文件不存在不报错）

    适用场景：
      - 开发/调试（不需要 MinIO 服务器）
      - USE_MINIO=false 时的默认后端
    """

    def __init__(self):
        # 数据根目录：项目根/data/
        self.root = Path(__file__).resolve().parent.parent / "data"

    def _resolve(self, key: str) -> Path:
        """将对象键映射到本地绝对路径"""
        return self.root / key

    # ── 文本读写 ──

    def read_text(self, key: str) -> str:
        """读取本地文件的 UTF-8 文本内容"""
        return self._resolve(key).read_text(encoding="utf-8")

    def write_text(self, key: str, content: str):
        """写入文本到本地文件（自动创建父目录）"""
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    # ── 二进制读写 ──

    def read_bytes(self, key: str) -> bytes:
        """读取本地文件的原始字节"""
        return self._resolve(key).read_bytes()

    def write_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream"):
        """写入字节到本地文件（自动创建父目录）"""
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    # ── 查询与列举 ──

    def exists(self, key: str) -> bool:
        """检查本地文件是否存在"""
        return self._resolve(key).exists()

    def list_keys(self, prefix: str) -> list[str]:
        """
        列举指定前缀下的所有文件。

        行为：
          - 如果 prefix 指向一个目录（如 "wiki/hwd/ws1/concepts/"），递归列出其下所有文件
          - 如果 prefix 不是目录，按 glob 前缀匹配
        返回的 key 格式与 MinIO 一致（正斜杠分隔）。
        """
        base = self._resolve(prefix)

        if base.is_dir():
            # prefix 是目录 → 递归列出所有文件
            return [
                str(p.relative_to(self.root)).replace("\\", "/")
                for p in base.rglob("*")
                if p.is_file()
            ]

        # prefix 可能是文件前缀（如 "wiki/hwd/ws1/concepts/L"）→ glob 匹配
        parent = base.parent
        if not parent.exists():
            return []
        pattern = base.name + "*"
        return [
            str(p.relative_to(self.root)).replace("\\", "/")
            for p in parent.rglob(pattern)
            if p.is_file()
        ]

    # ── 删除 ──

    def delete(self, key: str):
        """删除本地文件（不存在时静默跳过）"""
        path = self._resolve(key)
        if path.exists():
            path.unlink()

    def delete_prefix(self, prefix: str) -> int:
        """删除指定前缀下的所有本地文件，返回删除数量"""
        keys = self.list_keys(prefix)
        count = 0
        for key in keys:
            path = self._resolve(key)
            if path.exists():
                path.unlink()
                count += 1
        return count

    # ── 本地文件互传（Local 模式下等价于文件拷贝）──

    def download_to(self, key: str, local_path: Path):
        """将数据文件拷贝到指定本地路径"""
        import shutil
        src = self._resolve(key)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, local_path)

    def upload_from(self, key: str, local_path: Path):
        """将指定本地文件拷贝到数据存储目录"""
        import shutil
        dest = self._resolve(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_path, dest)


# ═══════════════════════════════════════════
# 工厂函数 — 获取存储后端实例
# ═══════════════════════════════════════════

_instance: Optional[StorageBackend] = None


def get_storage() -> StorageBackend:
    """
    获取存储后端实例（进程级单例）。

    根据环境变量 USE_MINIO 选择后端：
      - USE_MINIO=true  → MinIOBackend（对象存储）
      - USE_MINIO=false → LocalBackend（本地文件系统）

    单例保证：同一进程内只创建一个 client 实例，避免重复连接开销。

    用法：
        from core.storage import get_storage
        s = get_storage()
        content = s.read_text("wiki/hwd/ws1/concepts/LoRA.md")
    """
    global _instance
    if _instance is None:
        _instance = MinIOBackend() if USE_MINIO else LocalBackend()
    return _instance
