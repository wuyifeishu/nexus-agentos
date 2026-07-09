"""
file-organizer — 文件整理工具：按类型/日期归类、批量重命名、找重复文件。

Category: utility
"""


def run(
    action: str,
    directory: str = "",
    pattern: str = "*",
    organize_by: str = "type",
    recursive: bool = False,
) -> str:
    """文件整理工具。action: organize/dedupe/stats/recent。organize_by: type/date/size。"""
    import hashlib
    import os
    import shutil
    import time

    if not directory or not os.path.isdir(directory):
        return f"[file-organizer] 目录不存在: {directory}"

    def _walk():
        if recursive:
            for root, _, files in os.walk(directory):
                for f in files:
                    yield os.path.join(root, f)
        else:
            for f in os.listdir(directory):
                fp = os.path.join(directory, f)
                if os.path.isfile(fp):
                    yield fp

    try:
        if action == "stats":
            exts = {}
            sizes = []
            total = 0
            for fp in _walk():
                total += 1
                ext = os.path.splitext(fp)[1].lower() or "(无后缀)"
                exts[ext] = exts.get(ext, 0) + 1
                try:
                    sizes.append(os.path.getsize(fp))
                except Exception:
                    pass
            total_size = sum(sizes)
            lines = [
                f"目录: {directory}",
                f"文件总数: {total}",
                f"总大小: {_fmt_size(total_size)}",
                "",
                "按类型分布:",
            ]
            for ext, cnt in sorted(exts.items(), key=lambda x: -x[1]):
                lines.append(f"  {ext}: {cnt} 个")
            return "\n".join(lines)

        if action == "organize":
            if organize_by not in ("type", "date", "size"):
                return "[file-organizer] organize_by 只支持: type/date/size"
            moved = 0
            for fp in _walk():
                fname = os.path.basename(fp)
                if organize_by == "type":
                    ext = os.path.splitext(fname)[1].lower().lstrip(".") or "other"
                    subdir = os.path.join(directory, ext)
                elif organize_by == "date":
                    mt = os.path.getmtime(fp)
                    ts = time.strftime("%Y-%m", time.localtime(mt))
                    subdir = os.path.join(directory, ts)
                elif organize_by == "size":
                    sz = os.path.getsize(fp)
                    if sz < 1024 * 1024:
                        tier = "small"
                    elif sz < 10 * 1024 * 1024:
                        tier = "medium"
                    elif sz < 100 * 1024 * 1024:
                        tier = "large"
                    else:
                        tier = "xlarge"
                    subdir = os.path.join(directory, tier)
                os.makedirs(subdir, exist_ok=True)
                dst = os.path.join(subdir, fname)
                if fp != dst and not os.path.exists(dst):
                    shutil.move(fp, dst)
                    moved += 1
            return f"已整理 {moved} 个文件 (按 {organize_by}) → {directory}"

        if action == "dedupe":
            seen = {}
            dups = []
            for fp in _walk():
                try:
                    sz = os.path.getsize(fp)
                    with open(fp, "rb") as f:
                        h = hashlib.md5(f.read(8192)).hexdigest()
                    key = f"{sz}_{h}"
                    if key in seen:
                        dups.append((fp, seen[key]))
                    else:
                        seen[key] = fp
                except Exception:
                    pass
            if not dups:
                return "[file-organizer] 未找到重复文件"
            lines = [f"找到 {len(dups)} 组疑似重复:"]
            for dup, orig in dups[:20]:
                lines.append(f"  重复: {dup}")
                lines.append(f"  原始: {orig}")
                lines.append("")
            return "\n".join(lines)

        if action == "recent":
            files = []
            for fp in _walk():
                try:
                    files.append((os.path.getmtime(fp), fp, os.path.getsize(fp)))
                except Exception:
                    pass
            files.sort(key=lambda x: -x[0])
            lines = [f"最近修改的文件 (共{len(files)}个):"]
            for mt, fp, sz in files[:20]:
                ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(mt))
                lines.append(f"  {ts}  {_fmt_size(sz):>8}  {fp}")
            return "\n".join(lines)

        return f"[file-organizer] 未知操作: {action}, 支持: stats/organize/dedupe/recent"
    except Exception as e:
        return f"[file-organizer] 失败: {e}"


def _fmt_size(size):
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


__all__ = ["run"]
