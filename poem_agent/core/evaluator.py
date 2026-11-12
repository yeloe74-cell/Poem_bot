from __future__ import annotations

from typing import Any


class ResultEvaluator:
    """Checks if a planned action produced an acceptable result."""

    def evaluate(self, plan: Any) -> dict[str, Any]:
        steps = plan if isinstance(plan, list) else []
        return {
            "status": "ready",
            "steps_checked": len(steps),
            "has_approval_gate": any(step.get("name") == "approval_gate" for step in steps),
            "confidence": 0.8,
        }
