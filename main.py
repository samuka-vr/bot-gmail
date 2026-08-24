from __future__ import annotations

import logging

from app.bot import create_bot
from app.config import Environment


def main() -> None:
    environment = Environment.load()
    logging.basicConfig(
        level=getattr(logging, environment.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    bot = create_bot(environment)
    bot.run(environment.token, log_handler=None)


if __name__ == "__main__":
    main()
