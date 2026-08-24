from __future__ import annotations

import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

from app.services.maintenance import MaintenanceService


class MaintenanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_due_ticket_is_really_deleted_and_persisted(self) -> None:
        channel = discord.TextChannel()
        channel.delete = AsyncMock()
        guild = SimpleNamespace(get_channel=Mock(return_value=channel))
        sale = SimpleNamespace(
            id=42,
            guild_id=1,
            channel_id=200,
        )
        bot = SimpleNamespace(
            get_guild=Mock(return_value=guild),
            database=SimpleNamespace(
                mark_ticket_deleted=AsyncMock(),
                set_ticket_delete_at=AsyncMock(),
                postpone_ticket_delete=AsyncMock(),
                record_technical_failure=AsyncMock(),
            ),
            logs=SimpleNamespace(flush_sale_events=AsyncMock()),
        )

        await MaintenanceService(bot)._delete_ticket(sale)

        channel.delete.assert_awaited_once()
        bot.database.mark_ticket_deleted.assert_awaited_once_with(42)
        bot.database.postpone_ticket_delete.assert_not_awaited()

    async def test_http_failure_postpones_instead_of_losing_deadline(self) -> None:
        channel = discord.TextChannel()
        channel.delete = AsyncMock(side_effect=discord.HTTPException())
        guild = SimpleNamespace(get_channel=Mock(return_value=channel))
        sale = SimpleNamespace(id=43, guild_id=1, channel_id=201)
        bot = SimpleNamespace(
            get_guild=Mock(return_value=guild),
            database=SimpleNamespace(
                mark_ticket_deleted=AsyncMock(),
                set_ticket_delete_at=AsyncMock(),
                postpone_ticket_delete=AsyncMock(),
                record_technical_failure=AsyncMock(),
            ),
            logs=SimpleNamespace(flush_sale_events=AsyncMock()),
        )

        await MaintenanceService(bot)._delete_ticket(sale)

        retry_at = datetime.fromisoformat(
            bot.database.postpone_ticket_delete.await_args.args[1]
        )
        remaining = (retry_at - datetime.now(UTC)).total_seconds()
        self.assertGreaterEqual(remaining, 299)
        self.assertLessEqual(remaining, 300)
        bot.database.record_technical_failure.assert_awaited_once()
        bot.database.mark_ticket_deleted.assert_not_awaited()

