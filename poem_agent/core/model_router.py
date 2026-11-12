from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from poem_agent.config.model_config import ModelSpec, get_model_for_task


@dataclass(frozen=True)
class ModelRoute:
    task: str
    model: ModelSpec
    reason: str


class ModelRouter:
    """Selects the best model for a task according to capability and task type."""

    def __init__(self) -> None:
        self.history: list[ModelRoute] = []

    def route(self, task: str, *, preferred_provider: str | None = None) -> ModelRoute:
        spec = get_model_for_task(task, preferred_provider=preferred_provider)
        route = ModelRoute(task=task, model=spec, reason=f"Selected default {spec.task} model")
        self.history.append(route)
        return route

    def last_route(self) -> ModelRoute | None:
        return self.history[-1] if self.history else None
