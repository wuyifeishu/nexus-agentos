"""
AgentOS Enterprise — API Key Management.

功能：
  - API Key 创建/撤销/轮转
  - Key 哈希存储（SHA-256），不存明文
  - 前缀匹配快速查找
  - 权限范围（scope）绑定
  - 过期时间 & 用量配额
  - 审计日志联动
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass, field
from enum import StrEnum


class KeyScope(StrEnum):
    """API Key 权限范围。"""

    READ = "read"
    WRITE = "write"
    ADMIN = "admin"
    AGENT_RUN = "agent:run"
    AGENT_MANAGE = "agent:manage"
    TOOLS_ALL = "tools:*"


@dataclass
class APIKey:
    """API Key 实体。只存储哈希，不存明文。"""

    key_id: str  # 唯一标识，如 "ak_abc123"
    key_hash: str  # SHA-256 哈希
    key_prefix: str  # 前 8 位明文，用于快速匹配
    name: str  # 人类可读名称，如 "生产环境 Bot"
    created_by: str  # 创建者
    scopes: list[KeyScope]  # 权限范围
    created_at: float = field(default_factory=time.time)
    expires_at: float | None = None  # 过期时间戳（None = 永不过期）
    last_used_at: float | None = None
    usage_count: int = 0
    revoked: bool = False
    revoked_at: float | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class KeyCreateRequest:
    """创建 API Key 的请求。"""

    name: str
    scopes: list[KeyScope]
    expires_in_days: int | None = None  # None = 永不过期
    metadata: dict = field(default_factory=dict)


@dataclass
class KeyCreateResult:
    """创建结果 — 包含仅此一次可见的明文 Key。"""

    key_id: str
    plaintext_key: str  # ⚠️ 仅返回一次
    key_prefix: str
    scopes: list[KeyScope]
    expires_at: float | None


class APIKeyManager:
    """API Key 全生命周期管理器。

    特性：
      - SHA-256 哈希存储，不存明文
      - 前缀快速查找（前 8 位明文索引）
      - 撤销/轮转/用量追踪
      - 范围校验
    """

    def __init__(self, secret_salt: str = ""):
        self._keys: dict[str, APIKey] = {}  # key_id → APIKey
        self._prefix_index: dict[str, str] = {}  # key_prefix → key_id
        self._secret_salt = secret_salt or secrets.token_hex(16)

    # ── 创建 ──

    def create_key(self, request: KeyCreateRequest, created_by: str = "admin") -> KeyCreateResult:
        """创建新的 API Key。返回仅一次可见的明文。"""
        key_id = f"ak_{secrets.token_hex(12)}"
        plaintext = f"agentos_{secrets.token_hex(24)}"
        key_prefix = plaintext[:12]
        key_hash = self._hash(plaintext)

        expires_at = None
        if request.expires_in_days:
            expires_at = time.time() + request.expires_in_days * 86400

        key = APIKey(
            key_id=key_id,
            key_hash=key_hash,
            key_prefix=key_prefix,
            name=request.name,
            created_by=created_by,
            scopes=request.scopes,
            expires_at=expires_at,
            metadata=request.metadata,
        )

        self._keys[key_id] = key
        self._prefix_index[key_prefix] = key_id

        return KeyCreateResult(
            key_id=key_id,
            plaintext_key=plaintext,
            key_prefix=key_prefix,
            scopes=request.scopes,
            expires_at=expires_at,
        )

    # ── 验证 ──

    def validate_key(self, plaintext: str) -> APIKey | None:
        """验证 API Key 并返回对应的 Key 对象。无效/已撤销/过期返回 None。"""
        key_hash = self._hash(plaintext)

        # 前缀快速定位
        key_prefix = plaintext[:12]
        key_id = self._prefix_index.get(key_prefix)
        if not key_id:
            return None

        key = self._keys.get(key_id)
        if not key:
            return None

        # 恒定时间比对防时序攻击
        if not hmac.compare_digest(key.key_hash, key_hash):
            return None

        if key.revoked:
            return None

        if key.expires_at and time.time() > key.expires_at:
            return None

        # 更新使用记录
        key.last_used_at = time.time()
        key.usage_count += 1

        return key

    def check_scope(self, key: APIKey, required_scope: KeyScope) -> bool:
        """检查 Key 是否拥有指定权限范围。"""
        if KeyScope.ADMIN in key.scopes:
            return True
        return required_scope in key.scopes

    # ── 管理 ──

    def revoke_key(self, key_id: str) -> bool:
        """撤销 API Key。"""
        key = self._keys.get(key_id)
        if not key or key.revoked:
            return False
        key.revoked = True
        key.revoked_at = time.time()
        return True

    def rotate_key(self, key_id: str, created_by: str = "admin") -> KeyCreateResult | None:
        """轮转 API Key：撤销旧 Key，创建新 Key。"""
        old = self._keys.get(key_id)
        if not old or old.revoked:
            return None

        self.revoke_key(key_id)

        expires_in = None
        if old.expires_at:
            remaining = old.expires_at - time.time()
            expires_in = int(max(1, remaining / 86400))

        return self.create_key(
            KeyCreateRequest(
                name=f"{old.name} (rotated)",
                scopes=old.scopes,
                expires_in_days=expires_in,
                metadata={"rotated_from": key_id, **old.metadata},
            ),
            created_by=created_by,
        )

    def list_keys(self) -> list[APIKey]:
        """列出所有 Key（不含明文）。"""
        return sorted(self._keys.values(), key=lambda k: k.created_at, reverse=True)

    def get_key(self, key_id: str) -> APIKey | None:
        """获取单个 Key 信息。"""
        return self._keys.get(key_id)

    def stats(self) -> dict:
        """Key 统计信息。"""
        total = len(self._keys)
        active = sum(1 for k in self._keys.values() if not k.revoked)
        revoked = total - active
        total_usage = sum(k.usage_count for k in self._keys.values())
        return {
            "total": total,
            "active": active,
            "revoked": revoked,
            "total_usage_count": total_usage,
        }

    # ── 内部 ──

    def _hash(self, plaintext: str) -> str:
        """SHA-256 哈希（加盐）。"""
        return hashlib.sha256(f"{self._secret_salt}:{plaintext}".encode()).hexdigest()
