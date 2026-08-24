from __future__ import annotations

import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from app.services.completion import CompletionService


class CompletionTests(unittest.IsolatedAsyncioTestCase):
    async def test_terminal_sale_schedules_ticket_auto_close(self) -> None:
        closed_at = datetime.now(UTC)
        sale = SimpleNamespace(
            id=42,
            guild_id=1,
            transcript_sent_at=None,
            completed_at=None,
            closed_at=closed_at,
            ticket_delete_at=None,
            ticket_deleted_at=None,
        )
        settings = SimpleNamespace(
            transcripts_enabled=False,
            auto_close_enabled=True,
            auto_close_delay=60,
        )
        bot = SimpleNamespace(
            database=SimpleNamespace(
                get_sale=AsyncMock(return_value=sale),
                set_ticket_delete_at=AsyncMock(),
                mark_terminal_processed=AsyncMock(),
            ),
            logs=SimpleNamespace(flush_sale_events=AsyncMock()),
            workflow=SimpleNamespace(lock_ticket=AsyncMock()),
            maintenance=SimpleNamespace(notify=Mock()),
        )

        await CompletionService(bot).finish(SimpleNamespace(), sale, settings)

        scheduled = datetime.fromisoformat(
            bot.database.set_ticket_delete_at.await_args.args[1]
        )
        self.assertEqual((scheduled - closed_at).total_seconds(), 60)
        bot.maintenance.notify.assert_called_once_with()
        bot.database.mark_terminal_processed.assert_awaited_once_with(42)

    async def test_disabled_auto_close_only_locks_ticket(self) -> None:
        sale = SimpleNamespace(
            id=43,
            guild_id=1,
            transcript_sent_at=None,
            completed_at=None,
            closed_at=datetime.now(UTC),
            ticket_delete_at=None,
            ticket_deleted_at=None,
        )
        settings = SimpleNamespace(
            transcripts_enabled=False,
            auto_close_enabled=False,
            auto_close_delay=60,
        )
        bot = SimpleNamespace(
            database=SimpleNamespace(
                get_sale=AsyncMock(return_value=sale),
                set_ticket_delete_at=AsyncMock(),
                mark_terminal_processed=AsyncMock(),
            ),
            logs=SimpleNamespace(flush_sale_events=AsyncMock()),
            workflow=SimpleNamespace(lock_ticket=AsyncMock()),
            maintenance=SimpleNamespace(notify=Mock()),
        )

        await CompletionService(bot).finish(SimpleNamespace(), sale, settings)

        bot.workflow.lock_ticket.assert_awaited_once()
        bot.database.set_ticket_delete_at.assert_not_awaited()
        bot.maintenance.notify.assert_not_called()
