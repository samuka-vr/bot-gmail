from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

from app.constants import ACTIVE_STATUSES, DEFAULT_SETTINGS
from app.models import GuildSettings, Sale, SaleAccount


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Database:
    """One lightweight SQLite connection with serialized transactions and reads."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._connection: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    @property
    def connection(self) -> aiosqlite.Connection:
        if self._connection is None:
            raise RuntimeError("O banco ainda não foi inicializado.")
        return self._connection

    async def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self.path)
        self._connection.row_factory = aiosqlite.Row
        await self._connection.execute("PRAGMA foreign_keys = ON")
        await self._connection.execute("PRAGMA journal_mode = WAL")
        await self._connection.execute("PRAGMA synchronous = NORMAL")
        await self._connection.execute("PRAGMA busy_timeout = 5000")
        await self._connection.commit()
        await self._migrate()

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()
            self._connection = None

    async def _migrate(self) -> None:
        await self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )
            """
        )
        await self.connection.commit()

        cursor = await self.connection.execute(
            "SELECT version FROM schema_migrations"
        )
        rows = await cursor.fetchall()
        await cursor.close()
        applied = {int(row["version"]) for row in rows}

        migrations_dir = Path(__file__).with_name("migrations")
        for migration_path in sorted(migrations_dir.glob("[0-9][0-9][0-9]_*.sql")):
            version = int(migration_path.name.split("_", 1)[0])
            if version in applied:
                continue
            sql = migration_path.read_text(encoding="utf-8")
            name = migration_path.name.replace("'", "''")
            applied_at = utc_now_iso().replace("'", "''")
            script = (
                "BEGIN IMMEDIATE;\n"
                f"{sql}\n"
                "INSERT INTO schema_migrations(version, name, applied_at) "
                f"VALUES ({version}, '{name}', '{applied_at}');\n"
                "COMMIT;"
            )
            async with self._write_lock:
                try:
                    await self.connection.executescript(script)
                except Exception:
                    if self.connection.in_transaction:
                        await self.connection.rollback()
                    raise

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        async with self._write_lock:
            await self.connection.execute("BEGIN IMMEDIATE")
            try:
                yield self.connection
            except Exception:
                await self.connection.rollback()
                raise
            else:
                await self.connection.commit()

    async def fetchone(
        self, sql: str, parameters: Sequence[Any] = ()
    ) -> aiosqlite.Row | None:
        async with self._write_lock:
            cursor = await self.connection.execute(sql, parameters)
            row = await cursor.fetchone()
            await cursor.close()
            return row

    async def fetchall(
        self, sql: str, parameters: Sequence[Any] = ()
    ) -> list[aiosqlite.Row]:
        async with self._write_lock:
            cursor = await self.connection.execute(sql, parameters)
            rows = await cursor.fetchall()
            await cursor.close()
            return list(rows)

    async def ensure_default_settings(self, guild_id: int) -> None:
        now = utc_now_iso()
        values = [
            (guild_id, key, value, now)
            for key, value in DEFAULT_SETTINGS.items()
        ]
        async with self.transaction() as connection:
            await connection.executemany(
                """
                INSERT OR IGNORE INTO settings(guild_id, key, value, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                values,
            )

    async def get_settings(self, guild_id: int) -> GuildSettings:
        rows = await self.fetchall(
            "SELECT key, value FROM settings WHERE guild_id = ?", (guild_id,)
        )
        values = {
            str(row["key"]): str(row["value"])
            for row in rows
        }
        if not set(DEFAULT_SETTINGS).issubset(values):
            await self.ensure_default_settings(guild_id)
            rows = await self.fetchall(
                "SELECT key, value FROM settings WHERE guild_id = ?",
                (guild_id,),
            )
            values = {
                str(row["key"]): str(row["value"])
                for row in rows
            }
        return GuildSettings.from_mapping(values)

    async def set_settings(
        self,
        guild_id: int,
        values: Mapping[str, str],
        actor_id: int | None,
    ) -> None:
        unknown = set(values) - set(DEFAULT_SETTINGS)
        if unknown:
            raise ValueError(f"Configuração desconhecida: {sorted(unknown)!r}")
        now = utc_now_iso()
        async with self.transaction() as connection:
            await connection.executemany(
                """
                INSERT INTO settings(
                    guild_id, key, value, updated_at, updated_by_id
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at,
                    updated_by_id = excluded.updated_by_id
                """,
                [
                    (guild_id, key, value, now, actor_id)
                    for key, value in values.items()
                ],
            )

    async def set_settings_with_event(
        self,
        guild_id: int,
        values: Mapping[str, str],
        actor_id: int,
        interaction_id: int,
    ) -> bool:
        unknown = set(values) - set(DEFAULT_SETTINGS)
        if unknown:
            raise ValueError(f"Configuração desconhecida: {sorted(unknown)!r}")
        now = utc_now_iso()
        async with self.transaction() as connection:
            cursor = await connection.execute(
                "SELECT 1 FROM events WHERE interaction_id = ?",
                (interaction_id,),
            )
            processed = await cursor.fetchone()
            await cursor.close()
            if processed:
                return False
            await connection.executemany(
                """
                INSERT INTO settings(
                    guild_id, key, value, updated_at, updated_by_id
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at,
                    updated_by_id = excluded.updated_by_id
                """,
                [
                    (guild_id, key, value, now, actor_id)
                    for key, value in values.items()
                ],
            )
            await connection.execute(
                """
                INSERT INTO events(
                    guild_id, event_type, actor_id, payload_json,
                    interaction_id, created_at
                ) VALUES (?, 'CONFIG_CHANGED', ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    actor_id,
                    json.dumps({"keys": sorted(values)}),
                    interaction_id,
                    now,
                ),
            )
            return True

    async def get_sale(self, sale_id: int) -> Sale | None:
        row = await self.fetchone("SELECT * FROM sales WHERE id = ?", (sale_id,))
        return Sale.from_row(row) if row else None

    async def get_sale_by_channel(self, channel_id: int) -> Sale | None:
        row = await self.fetchone(
            "SELECT * FROM sales WHERE channel_id = ?", (channel_id,)
        )
        return Sale.from_row(row) if row else None

    async def get_sale_by_creation_interaction(
        self, interaction_id: int
    ) -> Sale | None:
        row = await self.fetchone(
            "SELECT * FROM sales WHERE create_interaction_id = ?",
            (interaction_id,),
        )
        return Sale.from_row(row) if row else None

    async def get_accounts(
        self, sale_id: int, *, include_removed: bool = False
    ) -> list[SaleAccount]:
        condition = "" if include_removed else "AND removed_at IS NULL"
        rows = await self.fetchall(
            f"""
            SELECT * FROM sale_accounts
            WHERE sale_id = ? {condition}
            ORDER BY id
            """,
            (sale_id,),
        )
        return [SaleAccount.from_row(row) for row in rows]

    async def get_active_sales(
        self,
        guild_id: int | None = None,
        *,
        after_id: int = 0,
        limit: int | None = None,
    ) -> list[Sale]:
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        parameters: list[Any] = [status.value for status in ACTIVE_STATUSES]
        guild_filter = ""
        if guild_id is not None:
            guild_filter = "AND guild_id = ?"
            parameters.append(guild_id)
        parameters.append(after_id)
        limit_clause = ""
        if limit is not None:
            limit_clause = "LIMIT ?"
            parameters.append(limit)
        rows = await self.fetchall(
            f"""
            SELECT * FROM sales
            WHERE status IN ({placeholders}) {guild_filter}
              AND id > ?
            ORDER BY id
            {limit_clause}
            """,
            parameters,
        )
        return [Sale.from_row(row) for row in rows]

    async def get_queue_rows(self, guild_id: int, limit: int = 20) -> list[aiosqlite.Row]:
        placeholders = ",".join("?" for _ in ACTIVE_STATUSES)
        return await self.fetchall(
            f"""
            SELECT s.*, COUNT(a.id) AS account_count
            FROM sales AS s
            LEFT JOIN sale_accounts AS a
              ON a.sale_id = s.id AND a.removed_at IS NULL
            WHERE s.guild_id = ? AND s.status IN ({placeholders})
            GROUP BY s.id
            ORDER BY s.created_at
            LIMIT ?
            """,
            (
                guild_id,
                *(status.value for status in ACTIVE_STATUSES),
                limit,
            ),
        )

    async def get_ticket_sales(
        self,
        guild_id: int,
        *,
        after_id: int = 0,
        limit: int = 100,
    ) -> list[Sale]:
        rows = await self.fetchall(
            """
            SELECT * FROM sales
            WHERE guild_id = ?
              AND channel_id IS NOT NULL
              AND ticket_deleted_at IS NULL
              AND id > ?
            ORDER BY id
            LIMIT ?
            """,
            (guild_id, after_id, limit),
        )
        return [Sale.from_row(row) for row in rows]

    async def get_profile(self, guild_id: int, user_id: int) -> dict[str, Any]:
        summary = await self.fetchone(
            """
            SELECT
                SUM(CASE WHEN status = 'FINALIZADO' THEN 1 ELSE 0 END)
                    AS completed_sales,
                SUM(CASE
                    WHEN status = 'ENCERRADO'
                     AND closed_by_id = customer_id
                    THEN 1 ELSE 0
                END) AS cancelled_sales,
                COALESCE(SUM(
                    CASE WHEN status = 'FINALIZADO' THEN unit_price_cents * (
                        SELECT COUNT(*) FROM sale_accounts a
                        WHERE a.sale_id = sales.id AND a.removed_at IS NULL
                    ) ELSE 0 END
                ), 0) AS received_cents,
                COALESCE(SUM(
                    CASE WHEN status = 'FINALIZADO' THEN (
                        SELECT COUNT(*) FROM sale_accounts a
                        WHERE a.sale_id = sales.id AND a.removed_at IS NULL
                    ) ELSE 0 END
                ), 0) AS sold_accounts
            FROM sales
            WHERE guild_id = ? AND customer_id = ?
            """,
            (guild_id, user_id),
        )
        recent = await self.fetchall(
            """
            SELECT s.*, COUNT(a.id) AS account_count
            FROM sales s
            LEFT JOIN sale_accounts a
              ON a.sale_id = s.id AND a.removed_at IS NULL
            WHERE s.guild_id = ? AND s.customer_id = ?
            GROUP BY s.id
            ORDER BY s.created_at DESC
            LIMIT 5
            """,
            (guild_id, user_id),
        )
        return {
            "completed_sales": int(summary["completed_sales"] or 0),
            "cancelled_sales": int(summary["cancelled_sales"] or 0),
            "received_cents": int(summary["received_cents"] or 0),
            "sold_accounts": int(summary["sold_accounts"] or 0),
            "recent": recent,
        }

    async def writable_check(self) -> bool:
        async with self._write_lock:
            try:
                await self.connection.execute("BEGIN IMMEDIATE")
                await self.connection.rollback()
            except aiosqlite.Error:
                if self.connection.in_transaction:
                    await self.connection.rollback()
                return False
        row = await self.fetchone("PRAGMA quick_check")
        return bool(row and row[0] == "ok")

    async def get_pending_events(
        self,
        *,
        sale_id: int | None = None,
        guild_id: int | None = None,
        limit: int = 100,
    ) -> list[aiosqlite.Row]:
        clauses = ["delivered_at IS NULL"]
        parameters: list[Any] = []
        if sale_id is not None:
            clauses.append("sale_id = ?")
            parameters.append(sale_id)
        if guild_id is not None:
            clauses.append("guild_id = ?")
            parameters.append(guild_id)
        parameters.append(limit)
        return await self.fetchall(
            f"""
            SELECT * FROM events
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at, id
            LIMIT ?
            """,
            parameters,
        )

    async def mark_event_delivery(
        self, event_id: int, *, delivered: bool, error: str | None = None
    ) -> None:
        async with self.transaction() as connection:
            await connection.execute(
                """
                UPDATE events
                SET delivered_at = ?, delivery_error = ?
                WHERE id = ?
                """,
                (utc_now_iso() if delivered else None, error, event_id),
            )

    async def mark_events_skipped(self, event_ids: Sequence[int]) -> None:
        if not event_ids:
            return
        now = utc_now_iso()
        async with self.transaction() as connection:
            await connection.executemany(
                """
                UPDATE events
                SET delivered_at = ?, delivery_error = 'logs_disabled'
                WHERE id = ? AND delivered_at IS NULL
                """,
                [(now, event_id) for event_id in event_ids],
            )

    async def record_technical_failure(
        self,
        *,
        guild_id: int,
        sale_id: int | None,
        operation: str,
        error_name: str,
    ) -> None:
        async with self.transaction() as connection:
            await connection.execute(
                """
                INSERT INTO events(
                    guild_id, sale_id, event_type, payload_json, created_at
                ) VALUES (?, ?, 'TECHNICAL_FAILURE', ?, ?)
                """,
                (
                    guild_id,
                    sale_id,
                    json.dumps(
                        {
                            "operation": operation[:80],
                            "error": error_name[:80],
                        }
                    ),
                    utc_now_iso(),
                ),
            )

    async def mark_transcript_sent(
        self, sale_id: int, message_id: int
    ) -> None:
        async with self.transaction() as connection:
            await connection.execute(
                """
                UPDATE sales
                SET transcript_message_id = ?, transcript_sent_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (message_id, utc_now_iso(), utc_now_iso(), sale_id),
            )

    async def set_ticket_delete_at(
        self, sale_id: int, delete_at: str | None
    ) -> None:
        async with self.transaction() as connection:
            await connection.execute(
                """
                UPDATE sales SET ticket_delete_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (delete_at, utc_now_iso(), sale_id),
            )

    async def get_due_maintenance(self, now: str) -> list[Sale]:
        rows = await self.fetchall(
            """
            SELECT * FROM sales
            WHERE (cart_notice_delete_at IS NOT NULL
                   AND cart_notice_delete_at <= ?)
               OR (ticket_delete_at IS NOT NULL
                   AND ticket_delete_at <= ?)
            ORDER BY COALESCE(cart_notice_delete_at, ticket_delete_at)
            LIMIT 25
            """,
            (now, now),
        )
        return [Sale.from_row(row) for row in rows]

    async def get_next_maintenance_at(self) -> str | None:
        row = await self.fetchone(
            """
            SELECT MIN(deadline) AS deadline FROM (
                SELECT cart_notice_delete_at AS deadline FROM sales
                WHERE cart_notice_delete_at IS NOT NULL
                UNION ALL
                SELECT ticket_delete_at AS deadline FROM sales
                WHERE ticket_delete_at IS NOT NULL
            )
            """
        )
        return str(row["deadline"]) if row and row["deadline"] else None

    async def clear_cart_notice_deadline(self, sale_id: int) -> None:
        async with self.transaction() as connection:
            await connection.execute(
                """
                UPDATE sales
                SET cart_notice_delete_at = NULL,
                    cart_notice_message_id = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (utc_now_iso(), sale_id),
            )

    async def postpone_cart_notice(self, sale_id: int, retry_at: str) -> None:
        async with self.transaction() as connection:
            await connection.execute(
                "UPDATE sales SET cart_notice_delete_at = ? WHERE id = ?",
                (retry_at, sale_id),
            )

    async def mark_ticket_deleted(self, sale_id: int) -> None:
        now = utc_now_iso()
        async with self.transaction() as connection:
            await connection.execute(
                """
                UPDATE sales
                SET ticket_delete_at = NULL, ticket_deleted_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (now, now, sale_id),
            )

    async def postpone_ticket_delete(self, sale_id: int, retry_at: str) -> None:
        async with self.transaction() as connection:
            await connection.execute(
                "UPDATE sales SET ticket_delete_at = ? WHERE id = ?",
                (retry_at, sale_id),
            )

    async def get_terminal_recovery_batch(
        self, *, after_id: int, limit: int = 100
    ) -> list[Sale]:
        rows = await self.fetchall(
            """
            SELECT s.* FROM sales AS s
            WHERE s.status IN ('FINALIZADO', 'ENCERRADO')
              AND s.channel_id IS NOT NULL
              AND s.ticket_deleted_at IS NULL
              AND s.id > ?
              AND (
                  s.terminal_processed_at IS NULL
                  OR (
                      s.transcript_sent_at IS NULL
                      AND EXISTS (
                          SELECT 1 FROM settings AS cfg
                          WHERE cfg.guild_id = s.guild_id
                            AND cfg.key = 'transcripts_enabled'
                            AND LOWER(cfg.value) = 'true'
                      )
                  )
              )
            ORDER BY s.id
            LIMIT ?
            """,
            (after_id, limit),
        )
        return [Sale.from_row(row) for row in rows]

    async def mark_terminal_processed(self, sale_id: int) -> None:
        now = utc_now_iso()
        async with self.transaction() as connection:
            await connection.execute(
                """
                UPDATE sales
                SET terminal_processed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now, now, sale_id),
            )
