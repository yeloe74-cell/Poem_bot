"""Run with ``python -m poem_agent.main`` after configuring .env."""

from __future__ import annotations

import logging

from dotenv import load_dotenv

from poem_agent.config.settings import load_settings
from poem_agent.telegram.bot import create_application


def main() -> None:
    load_dotenv()
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.app.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings.prepare()
    application = create_application(settings)
    logging.getLogger(__name__).info("Starting %s", settings.app.name)
    application.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
