from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from poem_agent.config.settings import Settings
from poem_agent.core.ai_brain import AIBrain
from poem_agent.core.evaluator import ResultEvaluator
from poem_agent.core.planner import Planner
from poem_agent.memory.memory_manager import MemoryManager


@dataclass
class AgentTask:
    task_id: str
    description: str
    priority: int = 1
    status: str = "pending"


class Agent:
    """Top-level orchestration object for the poem channel manager."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.ai = AIBrain()
        self.memory = MemoryManager()
        self.planner = Planner()
        self.evaluator = ResultEvaluator()

    def handle_message(self, incoming_message: str) -> dict[str, Any]:
        intent = self.ai.parse_intent(incoming_message)
        plan = self.planner.build_plan(intent.data)
        result = self.evaluator.evaluate(plan)
        self.memory.record_event({
            "message": incoming_message,
            "intent": intent.data,
            "plan": plan,
            "result": result,
        })
        return {"intent": intent.data, "plan": plan, "result": result}

    def collect_and_analyze(self, poem_text: str) -> dict[str, Any]:
        analysis = self.ai.analyze_poem(poem_text)
        self.memory.record_event({"type": "analysis", "data": analysis.data})
        return analysis.data
