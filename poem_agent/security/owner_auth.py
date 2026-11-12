"""Owner identity checks."""

from poem_agent.config.settings import Settings


def is_owner(settings: Settings, user_id: int | None) -> bool:
    return user_id is not None and user_id in settings.telegram.owner_ids
