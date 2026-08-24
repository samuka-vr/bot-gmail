from __future__ import annotations

from typing import Any


class AppCommandError(Exception):
    pass


def command(**kwargs: Any):
    def decorator(func: Any) -> Any:
        return func

    return decorator


def guild_only():
    def decorator(func: Any) -> Any:
        return func

    return decorator
