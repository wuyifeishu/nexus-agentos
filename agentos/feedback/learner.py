"""
AgentOS v0.30 反馈学习系统 — Human-in-the-loop + RLHF hooks。
支持人工评分、偏好学习、持续改进。
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class FeedbackType(StrEnum):
    """反馈类型枚举。"""

    THUMB = "thumb"  # 点赞/踩
    RATING = "rating"  # 1-5星
    CORRECTIVE = "corrective"  # 纠正指令
    PREFERENCE = "preference"  # A/B偏好
    DETAILED = "detailed"  # 详细评价


@dataclass
class FeedbackRecord:
    """反馈记录。"""

    session_id: str
    iteration: int
    feedback_type: FeedbackType
    content: str  # 反馈内容或评分
    original_output: str = ""
    corrected_output: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: dict = field(default_factory=dict)


class FeedbackCollector:
    """反馈收集器 — HITL反馈入口。"""

    def __init__(self, storage_path: str = "./feedback_data.jsonl"):
        self.storage_path = storage_path
        self._records: list[FeedbackRecord] = []
        self._callbacks: list[callable] = []
        if storage_path and os.path.exists(storage_path):
            self._load()

    def collect(self, record: FeedbackRecord):
        self._records.append(record)
        self._save()
        for cb in self._callbacks:
            cb(record)

    def collect_thumbs(self, session_id: str, iteration: int, up: bool):
        self.collect(
            FeedbackRecord(
                session_id=session_id,
                iteration=iteration,
                feedback_type=FeedbackType.THUMB,
                content="up" if up else "down",
            )
        )

    def collect_rating(self, session_id: str, iteration: int, rating: int, comment: str = ""):
        self.collect(
            FeedbackRecord(
                session_id=session_id,
                iteration=iteration,
                feedback_type=FeedbackType.RATING,
                content=str(rating),
                metadata={"comment": comment},
            )
        )

    def collect_corrective(
        self, session_id: str, iteration: int, correction: str, original: str = ""
    ):
        self.collect(
            FeedbackRecord(
                session_id=session_id,
                iteration=iteration,
                feedback_type=FeedbackType.CORRECTIVE,
                content=correction,
                original_output=original,
            )
        )

    def on_feedback(self, callback):
        self._callbacks.append(callback)

    def stats(self) -> dict:
        thumbs = {"up": 0, "down": 0}
        ratings = []
        corrective = 0
        for r in self._records:
            if r.feedback_type == FeedbackType.THUMB:
                if r.content == "up":
                    thumbs["up"] += 1
                else:
                    thumbs["down"] += 1
            elif r.feedback_type == FeedbackType.RATING:
                ratings.append(int(r.content))
            elif r.feedback_type == FeedbackType.CORRECTIVE:
                corrective += 1
        return {
            "total": len(self._records),
            "thumbs_up": thumbs["up"],
            "thumbs_down": thumbs["down"],
            "avg_rating": sum(ratings) / len(ratings) if ratings else 0.0,
            "corrective_count": corrective,
            "satisfaction": thumbs["up"] / max(thumbs["up"] + thumbs["down"], 1),
        }

    def _save(self):
        if not self.storage_path:
            return
        os.makedirs(os.path.dirname(self.storage_path) or ".", exist_ok=True)
        with open(self.storage_path, "a") as f:
            for r in self._records[-1:]:
                f.write(
                    json.dumps(
                        {
                            "session_id": r.session_id,
                            "iteration": r.iteration,
                            "feedback_type": r.feedback_type.value,
                            "content": r.content,
                            "original_output": r.original_output,
                            "corrected_output": r.corrected_output,
                            "timestamp": r.timestamp,
                            "metadata": r.metadata,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )

    def _load(self):
        with open(self.storage_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                self._records.append(
                    FeedbackRecord(
                        session_id=d["session_id"],
                        iteration=d["iteration"],
                        feedback_type=FeedbackType(d["feedback_type"]),
                        content=d["content"],
                        original_output=d.get("original_output", ""),
                        corrected_output=d.get("corrected_output", ""),
                        timestamp=d.get("timestamp", ""),
                        metadata=d.get("metadata", {}),
                    )
                )


class PreferenceLearner:
    """偏好学习器 — 从反馈中提取改进信号。"""

    def __init__(self, window_size: int = 100):
        self.window_size = window_size
        self._recent_patterns: list[dict] = []

    def learn_from_feedback(self, record: FeedbackRecord):
        """从单条反馈中学习。"""
        pattern = {
            "type": record.feedback_type.value,
            "content": record.content[:200],
            "session": record.session_id,
        }
        self._recent_patterns.append(pattern)
        if len(self._recent_patterns) > self.window_size:
            self._recent_patterns = self._recent_patterns[-self.window_size :]

    def get_improvement_hints(self) -> list[str]:
        """获取改进建议。"""
        hints = []
        corrections = [r for r in self._recent_patterns if r["type"] == "corrective"]
        if corrections:
            hints.append(f"最近 {len(corrections)} 条纠正反馈，建议调整输出风格")
        thumbs_down = sum(
            1 for r in self._recent_patterns if r["type"] == "thumb" and r["content"] == "down"
        )
        thumbs_up = sum(
            1 for r in self._recent_patterns if r["type"] == "thumb" and r["content"] == "up"
        )
        if thumbs_down > thumbs_up:
            hints.append("近期满意度下降，建议优化响应质量")
        return hints

    def should_retrain(self, threshold: float = 0.3) -> bool:
        """判断是否应该触发模型微调。"""
        if not self._recent_patterns:
            return False
        negative = sum(1 for r in self._recent_patterns if r["type"] in ("thumb", "corrective"))
        return negative / len(self._recent_patterns) > threshold
