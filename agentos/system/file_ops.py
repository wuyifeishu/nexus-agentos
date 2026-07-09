"""
文件操作模块 — 带权限检查的文件系统读写。

设计原则:
- 所有操作前检查权限
- 读操作可穿透任意路径
- 写操作区分沙箱/全盘
- 操作结果统一为 FileOpResult
"""

from __future__ import annotations

import mimetypes
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime

from agentos.system.permissions import (
    PermissionDenied,
    PermissionTier,
    SystemPermissionManager,
)


@dataclass
class FileListing:
    """文件/目录条目。"""

    name: str
    path: str
    is_dir: bool
    size_bytes: int = 0
    modified_at: str = ""
    mime_type: str = ""


@dataclass
class FileOpResult:
    """文件操作结果。"""

    success: bool
    action: str  # read/write/delete/move/copy/mkdir/list
    path: str
    content: str = ""  # 读取的内容
    listing: list[FileListing] = field(default_factory=list)
    error: str = ""
    bytes_written: int = 0


class FileOperator:
    """文件操作器 — 带权限检查的文件系统接口。"""

    def __init__(self, perm_manager: SystemPermissionManager, session_id: str):
        self._pm = perm_manager
        self._sid = session_id

    # ── 读取操作 ──

    def read(self, file_path: str) -> FileOpResult:
        """读取文件内容。"""
        path = os.path.abspath(os.path.expanduser(file_path))
        try:
            self._pm.require(self._sid, PermissionTier.READ, path)
        except PermissionDenied as e:
            return FileOpResult(success=False, action="read", path=path, error=str(e))

        try:
            # 自动检测是否为文本文件
            mime, _ = mimetypes.guess_type(path)
            if (
                mime
                and mime.startswith("text/")
                or path.endswith(
                    (
                        ".py",
                        ".md",
                        ".txt",
                        ".json",
                        ".yaml",
                        ".yml",
                        ".toml",
                        ".cfg",
                        ".ini",
                        ".log",
                        ".csv",
                        ".xml",
                        ".html",
                        ".css",
                        ".js",
                        ".ts",
                        ".sh",
                        ".bash",
                        ".env",
                        ".gitignore",
                    )
                )
            ):
                with open(path, encoding="utf-8", errors="replace") as f:
                    content = f.read()
                return FileOpResult(success=True, action="read", path=path, content=content)
            else:
                # 二进制文件返回预览
                size = os.path.getsize(path)
                return FileOpResult(
                    success=True,
                    action="read",
                    path=path,
                    content=f"[Binary file, {self._format_size(size)}]",
                )
        except Exception as e:
            return FileOpResult(success=False, action="read", path=path, error=str(e))

    def read_bytes(self, file_path: str, max_bytes: int = 1024 * 1024) -> FileOpResult:
        """读取二进制文件（限制大小）。"""
        path = os.path.abspath(os.path.expanduser(file_path))
        try:
            self._pm.require(self._sid, PermissionTier.READ, path)
        except PermissionDenied as e:
            return FileOpResult(success=False, action="read", path=path, error=str(e))

        try:
            with open(path, "rb") as f:
                data = f.read(max_bytes)
            # Base64 编码返回
            import base64

            encoded = base64.b64encode(data).decode("ascii")
            return FileOpResult(
                success=True,
                action="read",
                path=path,
                content=encoded,
                bytes_written=len(data),
            )
        except Exception as e:
            return FileOpResult(success=False, action="read", path=path, error=str(e))

    # ── 列表操作 ──

    def list_dir(self, dir_path: str, show_hidden: bool = False) -> FileOpResult:
        """列出目录内容。"""
        path = os.path.abspath(os.path.expanduser(dir_path))
        try:
            self._pm.require(self._sid, PermissionTier.READ, path)
        except PermissionDenied as e:
            return FileOpResult(success=False, action="list", path=path, error=str(e))

        if not os.path.isdir(path):
            return FileOpResult(success=False, action="list", path=path, error=f"不是目录: {path}")

        try:
            entries = []
            for name in sorted(os.listdir(path)):
                if not show_hidden and name.startswith("."):
                    continue
                full = os.path.join(path, name)
                stat = os.stat(full)
                mime, _ = mimetypes.guess_type(full)
                entries.append(
                    FileListing(
                        name=name,
                        path=full,
                        is_dir=os.path.isdir(full),
                        size_bytes=stat.st_size,
                        modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                        mime_type=mime
                        or (
                            "inode/directory" if os.path.isdir(full) else "application/octet-stream"
                        ),
                    )
                )
            return FileOpResult(success=True, action="list", path=path, listing=entries)
        except Exception as e:
            return FileOpResult(success=False, action="list", path=path, error=str(e))

    def search(self, root_dir: str, pattern: str, max_depth: int = 5) -> FileOpResult:
        """递归搜索文件（类似 find + glob）。"""
        import fnmatch

        path = os.path.abspath(os.path.expanduser(root_dir))
        try:
            self._pm.require(self._sid, PermissionTier.READ, path)
        except PermissionDenied as e:
            return FileOpResult(success=False, action="list", path=path, error=str(e))

        results: list[FileListing] = []
        try:
            for dirpath, dirnames, filenames in os.walk(path):
                depth = dirpath[len(path) :].count(os.sep)
                if depth >= max_depth:
                    dirnames.clear()
                    continue
                # 跳过隐藏目录
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for fname in filenames:
                    if fnmatch.fnmatch(fname, pattern):
                        full = os.path.join(dirpath, fname)
                        stat = os.stat(full)
                        results.append(
                            FileListing(
                                name=fname,
                                path=full,
                                is_dir=False,
                                size_bytes=stat.st_size,
                                modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(),
                            )
                        )
            return FileOpResult(success=True, action="list", path=path, listing=results)
        except Exception as e:
            return FileOpResult(success=False, action="list", path=path, error=str(e))

    # ── 写入操作 ──

    def write(self, file_path: str, content: str) -> FileOpResult:
        """写入文本文件。"""
        path = os.path.abspath(os.path.expanduser(file_path))
        # 判断需要沙箱还是全盘权限
        sandbox_paths = ["/tmp/agentos/", "/home/marvis/Marvis/"]
        needs_full = not any(path.startswith(sp) for sp in sandbox_paths)
        tier = PermissionTier.WRITE_ALL if needs_full else PermissionTier.WRITE_SANDBOX

        try:
            self._pm.require(self._sid, tier, path)
        except PermissionDenied as e:
            return FileOpResult(success=False, action="write", path=path, error=str(e))

        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return FileOpResult(
                success=True,
                action="write",
                path=path,
                bytes_written=len(content.encode("utf-8")),
            )
        except Exception as e:
            return FileOpResult(success=False, action="write", path=path, error=str(e))

    def write_bytes(self, file_path: str, data: bytes) -> FileOpResult:
        """写入二进制文件。"""
        path = os.path.abspath(os.path.expanduser(file_path))
        sandbox_paths = ["/tmp/agentos/", "/home/marvis/Marvis/"]
        needs_full = not any(path.startswith(sp) for sp in sandbox_paths)
        tier = PermissionTier.WRITE_ALL if needs_full else PermissionTier.WRITE_SANDBOX

        try:
            self._pm.require(self._sid, tier, path)
        except PermissionDenied as e:
            return FileOpResult(success=False, action="write", path=path, error=str(e))

        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "wb") as f:
                f.write(data)
            return FileOpResult(success=True, action="write", path=path, bytes_written=len(data))
        except Exception as e:
            return FileOpResult(success=False, action="write", path=path, error=str(e))

    # ── 删除/移动 ──

    def delete(self, target_path: str) -> FileOpResult:
        """删除文件或目录（高风险，需 WRITE_ALL 权限）。"""
        path = os.path.abspath(os.path.expanduser(target_path))
        try:
            self._pm.require(self._sid, PermissionTier.WRITE_ALL, path)
        except PermissionDenied as e:
            return FileOpResult(success=False, action="delete", path=path, error=str(e))

        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            return FileOpResult(success=True, action="delete", path=path)
        except Exception as e:
            return FileOpResult(success=False, action="delete", path=path, error=str(e))

    def move(self, src: str, dst: str) -> FileOpResult:
        """移动/重命名文件。"""
        src_path = os.path.abspath(os.path.expanduser(src))
        dst_path = os.path.abspath(os.path.expanduser(dst))
        try:
            self._pm.require(self._sid, PermissionTier.WRITE_ALL, src_path)
            self._pm.require(self._sid, PermissionTier.WRITE_ALL, dst_path)
        except PermissionDenied as e:
            return FileOpResult(success=False, action="move", path=src_path, error=str(e))

        try:
            shutil.move(src_path, dst_path)
            return FileOpResult(success=True, action="move", path=dst_path)
        except Exception as e:
            return FileOpResult(success=False, action="move", path=src_path, error=str(e))

    def mkdir(self, dir_path: str) -> FileOpResult:
        """创建目录。"""
        path = os.path.abspath(os.path.expanduser(dir_path))
        sandbox_paths = ["/tmp/agentos/", "/home/marvis/Marvis/"]
        needs_full = not any(path.startswith(sp) for sp in sandbox_paths)
        tier = PermissionTier.WRITE_ALL if needs_full else PermissionTier.WRITE_SANDBOX

        try:
            self._pm.require(self._sid, tier, path)
        except PermissionDenied as e:
            return FileOpResult(success=False, action="mkdir", path=path, error=str(e))

        try:
            os.makedirs(path, exist_ok=True)
            return FileOpResult(success=True, action="mkdir", path=path)
        except Exception as e:
            return FileOpResult(success=False, action="mkdir", path=path, error=str(e))

    # ── 文件信息 ──

    def stat(self, file_path: str) -> FileOpResult:
        """获取文件/目录详细信息。"""
        path = os.path.abspath(os.path.expanduser(file_path))
        try:
            self._pm.require(self._sid, PermissionTier.READ, path)
        except PermissionDenied as e:
            return FileOpResult(success=False, action="read", path=path, error=str(e))

        try:
            st = os.stat(path)
            info_lines = [
                f"路径: {path}",
                f"类型: {'目录' if os.path.isdir(path) else '文件'}",
                f"大小: {self._format_size(st.st_size)}",
                f"权限: {oct(st.st_mode)[-3:]}",
                f"修改时间: {datetime.fromtimestamp(st.st_mtime).isoformat()}",
                f"创建时间: {datetime.fromtimestamp(st.st_ctime).isoformat()}",
                f"inode: {st.st_ino}",
            ]
            return FileOpResult(
                success=True, action="read", path=path, content="\n".join(info_lines)
            )
        except Exception as e:
            return FileOpResult(success=False, action="read", path=path, error=str(e))

    # ── 工具 ──

    @staticmethod
    def _format_size(size: int) -> str:
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"
