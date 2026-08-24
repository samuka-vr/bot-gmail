from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import discord

from app.models import Sale

if TYPE_CHECKING:
    from app.bot import SKStoreBot


LOGGER = logging.getLogger(__name__)


class MaintenanceService:
    """One deadline-driven task; no periodic polling."""

    def __init__(self, bot: "SKStoreBot") -> None:
        self.bot = bot
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(
                self._run(), name="skstore-maintenance"
            )
            self._wake.set()

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    def notify(self) -> None:
        self._wake.set()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _run(self) -> None:
        while True:
            try:
                await self._process_due()
                next_value = await self.bot.database.get_next_maintenance_at()
                self._wake.clear()
                if next_value is None:
                    await self._wake.wait()
                    continue
                deadline = datetime.fromisoformat(next_value)
                timeout = max(
                    0.1, (deadline - datetime.now(UTC)).total_seconds()
                )
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=timeout)
                except TimeoutError:
                    pass
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("Falha no agendador de manutenção")
                await asyncio.sleep(30)

    async def _process_due(self) -> None:
        now = datetime.now(UTC)
        due = await self.bot.database.get_due_maintenance(now.isoformat())
        for sale in due:
            if sale.cart_notice_delete_at and sale.cart_notice_delete_at <= now:
                await self._delete_notice(sale)
            if sale.ticket_delete_at and sale.ticket_delete_at <= now:
                await self._delete_ticket(sale)

    async def _channel(self, sale: Sale) -> discord.TextChannel | None:
        if not sale.channel_id:
            return None
        guild = self.bot.get_guild(sale.guild_id)
        if guild is None:
            return None
        channel = guild.get_channel(sale.channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(sale.channel_id)
            except discord.NotFound:
                return None
        return channel if isinstance(channel, discord.TextChannel) else None

    async def _delete_notice(self, sale: Sale) -> None:
        try:
            channel = await self._channel(sale)
            if channel and sale.cart_notice_message_id:
                message = await channel.fetch_message(sale.cart_notice_message_id)
                await message.delete()
        except discord.NotFound:
            pass
        except discord.Forbidden as exc:
            await self.bot.database.clear_cart_notice_deadline(sale.id)
            await self.bot.database.record_technical_failure(
                guild_id=sale.guild_id,
                sale_id=sale.id,
                operation="cart_notice_delete",
                error_name=type(exc).__name__,
            )
            await self.bot.logs.flush_sale_events(sale.id)
            return
        except discord.HTTPException as exc:
            retry_at = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
            await self.bot.database.postpone_cart_notice(sale.id, retry_at)
            await self.bot.database.record_technical_failure(
                guild_id=sale.guild_id,
                sale_id=sale.id,
                operation="cart_notice_delete",
                error_name=type(exc).__name__,
            )
            await self.bot.logs.flush_sale_events(sale.id)
            return
        await self.bot.database.clear_cart_notice_deadline(sale.id)

    async def _delete_ticket(self, sale: Sale) -> None:
        try:
            channel = await self._channel(sale)
            if channel:
                await channel.delete(
                    reason=f"SK Store: auto-close da venda #{sale.id:04d}"
                )
        except discord.NotFound:
            pass
        except discord.Forbidden as exc:
            await self.bot.database.set_ticket_delete_at(sale.id, None)
            await self.bot.database.record_technical_failure(
                guild_id=sale.guild_id,
                sale_id=sale.id,
                operation="ticket_auto_close",
                error_name=type(exc).__name__,
            )
            await self.bot.logs.flush_sale_events(sale.id)
            return
        except discord.HTTPException as exc:
            retry_at = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
            await self.bot.database.postpone_ticket_delete(sale.id, retry_at)
            await self.bot.database.record_technical_failure(
                guild_id=sale.guild_id,
                sale_id=sale.id,
                operation="ticket_auto_close",
                error_name=type(exc).__name__,
            )
            await self.bot.logs.flush_sale_events(sale.id)
            return
        await self.bot.database.mark_ticket_deleted(sale.id)
