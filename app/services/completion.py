from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import discord

from app.models import GuildSettings, Sale

if TYPE_CHECKING:
    from app.bot import SKStoreBot


LOGGER = logging.getLogger(__name__)


class CompletionService:
    def __init__(self, bot: "SKStoreBot") -> None:
        self.bot = bot

    async def finish(
        self,
        channel: discord.TextChannel,
        sale: Sale,
        settings: GuildSettings,
    ) -> Sale:
        if settings.transcripts_enabled and not sale.transcript_sent_at:
            try:
                await self.bot.transcripts.create_and_send(
                    channel, sale, settings
                )
            except Exception as exc:
                LOGGER.exception(
                    "Falha no transcript da venda %s", sale.id, exc_info=exc
                )
                await self.bot.database.record_technical_failure(
                    guild_id=sale.guild_id,
                    sale_id=sale.id,
                    operation="transcript",
                    error_name=type(exc).__name__,
                )

        await self.bot.logs.flush_sale_events(sale.id)
        await self.bot.workflow.lock_ticket(channel, sale, settings)
        await self.bot.logs.flush_sale_events(sale.id)

        refreshed = await self.bot.database.get_sale(sale.id)
        if (
            settings.auto_close_enabled
            and refreshed
            and refreshed.ticket_delete_at is None
            and refreshed.ticket_deleted_at is None
        ):
            delete_at = datetime.now(UTC) + timedelta(
                seconds=max(settings.auto_close_delay, 30)
            )
            await self.bot.database.set_ticket_delete_at(
                sale.id, delete_at.isoformat()
            )
            self.bot.maintenance.notify()
            refreshed = await self.bot.database.get_sale(sale.id) or refreshed
        await self.bot.database.mark_terminal_processed(sale.id)
        return refreshed or sale
