"""
encryption — 哈希摘要、Base64 编解码（纯 Python stdlib）。

Category: security
"""


def run(action: str, text: str = "", file_path: str = "", algorithm: str = "sha256") -> str:
    """加密/哈希工具。action: hash/base64_encode/base64_decode/uuid。algorithm: sha256/md5/sha1/sha512。"""
    import base64
    import hashlib
    import os
    import uuid

    def _input():
        if file_path and os.path.isfile(file_path):
            with open(file_path, "rb") as f:
                return f.read()
        return text.encode("utf-8")

    try:
        if action == "hash":
            data = _input()
            algo = algorithm.lower()
            if algo == "md5":
                h = hashlib.md5(data).hexdigest()
            elif algo == "sha1":
                h = hashlib.sha1(data).hexdigest()
            elif algo == "sha256":
                h = hashlib.sha256(data).hexdigest()
            elif algo == "sha512":
                h = hashlib.sha512(data).hexdigest()
            else:
                return f"[encryption] 不支持的算法: {algorithm}, 可用: md5/sha1/sha256/sha512"
            src = file_path if file_path else f"'{text[:30]}...'" if len(text) > 30 else f"'{text}'"
            return f"{algo.upper()}({src}) = {h}"

        if action == "base64_encode":
            data = _input()
            encoded = base64.b64encode(data).decode("utf-8")
            return encoded

        if action == "base64_decode":
            data = text.encode("utf-8") if text else _input()
            try:
                decoded = base64.b64decode(data).decode("utf-8")
            except Exception:
                decoded = base64.b64decode(data).decode("latin-1")  # might be binary
            return decoded

        if action == "uuid":
            return f"UUID4: {uuid.uuid4()}\nUUID1: {uuid.uuid1()}"

        return f"[encryption] 未知操作: {action}, 支持: hash/base64_encode/base64_decode/uuid"
    except Exception as e:
        return f"[encryption] 失败: {e}"


__all__ = ["run"]
