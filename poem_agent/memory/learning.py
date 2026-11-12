from __future__ import annotations

from typing import Any


class LearningEngine:
    """Captures feedback and updates simple heuristics for better future decisions."""

    def __init__(self) -> None:
        self.feedback: list[dict[str, Any]] = []

    def record_feedback(self, *, poem_key: str, owner_feedback: str, approved: bool) -> None:
        self.feedback.append({
            "poem_key": poem_key,
            "owner_feedback": owner_feedback,
            "approved": approved,
        })

    def summary(self) -> dict[str, Any]:
        approved = sum(1 for item in self.feedback if item.get("approved"))
        return {"total_feedback": len(self.feedback), "approved_count": approved}
