from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from app.models import Sale

if TYPE_CHECKING:
    from app.bot import SKStoreBot


LOGGER = logging.getLogger(__name__)


class RecoveryService:
    def __init__(self, bot: "SKStoreBot") -> None:
        self.bot = bot

    async def run(self) -> None:
        active_after_id = 0
        while True:
            active = await self.bot.database.get_active_sales(
                after_id=active_after_id, limit=100
            )
            if not active:
                break
            for sale in active:
                active_after_id = sale.id
                guild = self.bot.get_guild(sale.guild_id)
                if guild is None:
                    continue
                try:
                    settings = await self.bot.database.get_settings(sale.guild_id)
                    customer = guild.get_member(sale.customer_id)
                    if customer is None:
                        try:
                            customer = await guild.fetch_member(sale.customer_id)
                        except discord.NotFound:
                            customer = None
                    channel = await self.bot.tickets.create_or_find(
                        guild, customer, sale, settings
                    )
                    current = await self.bot.database.get_sale(sale.id) or sale
                    await self.bot.workflow.render_sale(channel, current)
                except Exception as exc:
                    LOGGER.exception(
                        "Falha ao recuperar venda ativa %s",
                        sale.id,
                        exc_info=exc,
                    )
                    await self.bot.database.record_technical_failure(
                        guild_id=sale.guild_id,
                        sale_id=sale.id,
                        operation="active_sale_recovery",
                        error_name=type(exc).__name__,
                    )

        terminal_after_id = 0
        while True:
            terminal = await self.bot.database.get_terminal_recovery_batch(
                after_id=terminal_after_id, limit=100
            )
            if not terminal:
                break
            for sale in terminal:
                terminal_after_id = sale.id
                await self._recover_terminal(sale)

        await self.bot.logs.flush_all()

    async def _recover_terminal(self, sale: Sale) -> None:
        guild = self.bot.get_guild(sale.guild_id)
        if guild is None or not sale.channel_id:
            return
        channel = guild.get_channel(sale.channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(sale.channel_id)
            except discord.NotFound:
                await self.bot.database.mark_ticket_deleted(sale.id)
                await self.bot.database.mark_terminal_processed(sale.id)
                await self.bot.database.record_technical_failure(
                    guild_id=sale.guild_id,
                    sale_id=sale.id,
                    operation="terminal_channel_recovery",
                    error_name="NotFound",
                )
                return
            except (discord.Forbidden, discord.HTTPException) as exc:
                await self.bot.database.record_technical_failure(
                    guild_id=sale.guild_id,
                    sale_id=sale.id,
                    operation="terminal_channel_recovery",
                    error_name=type(exc).__name__,
                )
                return
        if not isinstance(channel, discord.TextChannel):
            await self.bot.database.mark_ticket_deleted(sale.id)
            await self.bot.database.mark_terminal_processed(sale.id)
            await self.bot.database.record_technical_failure(
                guild_id=sale.guild_id,
                sale_id=sale.id,
                operation="terminal_channel_recovery",
                error_name="InvalidChannelType",
            )
            return
        try:
            settings = await self.bot.database.get_settings(sale.guild_id)
            await self.bot.workflow.render_terminal(channel, sale)
            await self.bot.completion.finish(channel, sale, settings)
        except Exception as exc:
            LOGGER.exception("Falha ao concluir recuperação da venda %s", sale.id)
            await self.bot.database.record_technical_failure(
                guild_id=sale.guild_id,
                sale_id=sale.id,
                operation="terminal_sale_recovery",
                error_name=type(exc).__name__,
            )
