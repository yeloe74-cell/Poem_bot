from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ReasoningContext:
    instructions: list[str]
    constraints: list[str]


class ReasoningEngine:
    """Transforms a request into a reliable action plan with simple guardrails."""

    def __init__(self) -> None:
        self.default_constraints = [
            "Never publish without owner approval.",
            "Keep the poem channel mission as the primary objective.",
            "Do not use unverified image licenses.",
        ]

    def reason(self, user_input: str) -> ReasoningContext:
        tokens = [part.strip() for part in user_input.split() if part.strip()]
        instructions = []
        if "တင်" in user_input or "post" in user_input.lower():
            instructions.append("publish or prepare a post")
        if "ဖျက်" in user_input or "reject" in user_input.lower():
            instructions.append("remove or reject content")
        if "နောက်မှ" in user_input or "schedule" in user_input.lower():
            instructions.append("schedule the task")
        if not instructions:
            instructions.append("analyze the request")
        return ReasoningContext(instructions=instructions, constraints=self.default_constraints)
