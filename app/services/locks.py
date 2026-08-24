from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Hashable
from contextlib import asynccontextmanager


class KeyedLocks:
    """Short-lived per-resource locks without an ever-growing cache."""

    def __init__(self) -> None:
        self._guard = asyncio.Lock()
        self._locks: dict[Hashable, tuple[asyncio.Lock, int]] = {}

    @asynccontextmanager
    async def hold(self, key: Hashable) -> AsyncIterator[None]:
        async with self._guard:
            lock, users = self._locks.get(key, (asyncio.Lock(), 0))
            self._locks[key] = (lock, users + 1)
        try:
            async with lock:
                yield
        finally:
            async with self._guard:
                current_lock, users = self._locks[key]
                if users <= 1 and not current_lock.locked():
                    self._locks.pop(key, None)
                else:
                    self._locks[key] = (current_lock, users - 1)
