from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str
    task: str
    base_url: str | None = None
    supports_tools: bool = False
    cost_index: float = 1.0
    latency_ms: int = 1000


MODEL_REGISTRY: dict[str, ModelSpec] = {
    "poetry-analysis": ModelSpec(
        provider="openrouter",
        model="openai/gpt-4o-mini",
        task="poetry-analysis",
        base_url="https://openrouter.ai/api/v1",
        supports_tools=False,
        cost_index=1.0,
        latency_ms=1200,
    ),
    "reasoning": ModelSpec(
        provider="openrouter",
        model="anthropic/claude-3.5-sonnet",
        task="reasoning",
        base_url="https://openrouter.ai/api/v1",
        supports_tools=True,
        cost_index=2.1,
        latency_ms=1800,
    ),
    "classification": ModelSpec(
        provider="openrouter",
        model="openai/gpt-4o-mini",
        task="classification",
        base_url="https://openrouter.ai/api/v1",
        supports_tools=False,
        cost_index=0.9,
        latency_ms=900,
    ),
    "burmese": ModelSpec(
        provider="openrouter",
        model="google/gemini-2.0-flash-001",
        task="burmese",
        base_url="https://openrouter.ai/api/v1",
        supports_tools=False,
        cost_index=1.1,
        latency_ms=1100,
    ),
    "simple": ModelSpec(
        provider="openrouter",
        model="openai/gpt-4o-mini",
        task="simple",
        base_url="https://openrouter.ai/api/v1",
        supports_tools=False,
        cost_index=0.7,
        latency_ms=800,
    ),
}


def get_model_for_task(task: str, *, preferred_provider: str | None = None) -> ModelSpec:
    key = task.lower().replace(" ", "-")
    if key in MODEL_REGISTRY:
        return MODEL_REGISTRY[key]
    return MODEL_REGISTRY["simple"]
