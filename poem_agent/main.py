from __future__ import annotations

from poem_agent.config.settings import load_settings
from poem_agent.core.agent import Agent


def main() -> None:
    settings = load_settings()
    agent = Agent(settings)
    print(f"Poem Bot agent started with environment: {settings.app.environment}")
    print("Workflow ready: collect, analyze, approve, schedule, publish.")


if __name__ == "__main__":
    main()
