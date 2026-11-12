from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from poem_agent.core.reasoning import ReasoningEngine


@dataclass
class PlanStep:
    name: str
    action: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass
class Plan:
    steps: list[PlanStep]
    summary: str


class Planner:
    """Creates a task plan from an intent and reasoning context."""

    def __init__(self) -> None:
        self.reasoner = ReasoningEngine()

    def build_plan(self, intent: dict[str, Any]) -> list[dict[str, Any]]:
        action = intent.get("action", "unknown")
        steps: list[PlanStep] = []
        steps.append(PlanStep("validate_intent", "validate", {"action": action}))
        steps.append(PlanStep("collect_context", "analyze_context", {"message": str(intent)}))
        if action in {"post_poem", "approve_draft", "schedule_poem"}:
            steps.append(PlanStep("approval_gate", "require_owner_approval", {"required": True}))
        if action in {"post_poem", "schedule_poem"}:
            steps.append(PlanStep("publish", "prepare_publication", {"channel": "target"}))
        return [step.__dict__ for step in steps]
