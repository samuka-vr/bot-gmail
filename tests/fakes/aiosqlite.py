"""Synchronous sqlite3 compatibility layer used only by the local test suite."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

Row = sqlite3.Row
Error = sqlite3.Error


class Cursor:
    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self._cursor = cursor

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def lastrowid(self) -> int | None:
        return self._cursor.lastrowid

    async def fetchone(self) -> Row | None:
        return self._cursor.fetchone()

    async def fetchall(self) -> list[Row]:
        return self._cursor.fetchall()

    async def close(self) -> None:
        self._cursor.close()


class Connection:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @property
    def row_factory(self) -> Any:
        return self._connection.row_factory

    @row_factory.setter
    def row_factory(self, value: Any) -> None:
        self._connection.row_factory = value

    @property
    def in_transaction(self) -> bool:
        return self._connection.in_transaction

    async def execute(
        self, sql: str, parameters: Sequence[Any] = ()
    ) -> Cursor:
        return Cursor(self._connection.execute(sql, parameters))

    async def executemany(
        self, sql: str, values: Iterable[Sequence[Any]]
    ) -> Cursor:
        return Cursor(self._connection.executemany(sql, values))

    async def executescript(self, sql: str) -> Cursor:
        return Cursor(self._connection.executescript(sql))

    async def commit(self) -> None:
        self._connection.commit()

    async def rollback(self) -> None:
        self._connection.rollback()

    async def close(self) -> None:
        self._connection.close()


async def connect(path: str | Path) -> Connection:
    return Connection(sqlite3.connect(path))
