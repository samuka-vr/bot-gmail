from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING

import aiosqlite
import discord

from app.constants import STATUS_LABELS, EventType
from app.models import GuildSettings, Sale
from app.utils.money import format_brl
from app.utils.text import truncate

if TYPE_CHECKING:
    from app.bot import SKStoreBot


LOGGER = logging.getLogger(__name__)

EVENT_LABELS: dict[str, str] = {
    EventType.SALE_CREATED.value: "Venda criada",
    EventType.ACCOUNT_ADDED.value: "Gmail adicionado",
    EventType.ACCOUNT_REMOVED.value: "Gmail removido",
    EventType.PIX_CHANGED.value: "Pix alterado",
    EventType.STAFF_CLAIMED.value: "Venda assumida",
    EventType.CUSTOMER_NOTIFIED.value: "Cliente notificado",
    EventType.PAYMENT_OPENED.value: "Pagamento aberto",
    EventType.PAYMENT_REOPENED.value: "Retorno para análise",
    EventType.PAYMENT_CONFIRMED.value: "Pagamento confirmado",
    EventType.SALE_FINALIZED.value: "Venda finalizada",
    EventType.CUSTOMER_CANCELLED.value: "Cliente cancelou",
    EventType.STAFF_CLOSED.value: "Venda encerrada",
    EventType.CONFIG_CHANGED.value: "Configuração alterada",
    EventType.TECHNICAL_FAILURE.value: "Falha técnica",
}


class LogService:
    def __init__(self, bot: "SKStoreBot") -> None:
        self.bot = bot

    async def flush_sale_events(self, sale_id: int) -> None:
        await self._flush_scope(sale_id=sale_id)

    async def flush_guild_events(self, guild_id: int) -> None:
        await self._flush_scope(guild_id=guild_id)

    async def _flush_scope(
        self,
        *,
        sale_id: int | None = None,
        guild_id: int | None = None,
    ) -> None:
        for _ in range(5):
            rows = await self.bot.database.get_pending_events(
                sale_id=sale_id,
                guild_id=guild_id,
                limit=100,
            )
            if not rows:
                return
            completed = await self._flush(rows)
            if completed == 0 or len(rows) < 100:
                return

    async def flush_all(self) -> None:
        for _ in range(10):
            rows = await self.bot.database.get_pending_events(limit=100)
            if not rows:
                return
            completed = await self._flush(rows)
            if completed == 0:
                return
            if len(rows) < 100:
                return

    async def _resolve_log_channel(
        self, guild_id: int, channel_id: int
    ) -> discord.TextChannel | None:
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return None
        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None
        return channel if isinstance(channel, discord.TextChannel) else None

    async def _flush(self, rows: list[aiosqlite.Row]) -> int:
        settings_cache: dict[int, GuildSettings] = {}
        channel_cache: dict[tuple[int, int], discord.TextChannel | None] = {}
        sale_cache: dict[int, Sale | None] = {}
        completed = 0
        for event in rows:
            event_id = int(event["id"])
            guild_id = int(event["guild_id"])
            settings = settings_cache.get(guild_id)
            if settings is None:
                settings = await self.bot.database.get_settings(guild_id)
                settings_cache[guild_id] = settings
            if not settings.logs_enabled:
                await self.bot.database.mark_events_skipped([event_id])
                completed += 1
                continue
            if not settings.logs_channel_id:
                await self.bot.database.mark_event_delivery(
                    event_id, delivered=False, error="logs_channel_not_configured"
                )
                continue
            key = (guild_id, settings.logs_channel_id)
            if key not in channel_cache:
                channel_cache[key] = await self._resolve_log_channel(*key)
            channel = channel_cache[key]
            if channel is None:
                await self.bot.database.mark_event_delivery(
                    event_id, delivered=False, error="logs_channel_unavailable"
                )
                continue

            sale: Sale | None = None
            if event["sale_id"]:
                sale_id = int(event["sale_id"])
                if sale_id not in sale_cache:
                    sale_cache[sale_id] = await self.bot.database.get_sale(sale_id)
                sale = sale_cache[sale_id]
            embed = await self._build_embed(event, sale, settings.embed_color)
            try:
                await channel.send(embed=embed)
            except (discord.Forbidden, discord.HTTPException) as exc:
                await self.bot.database.mark_event_delivery(
                    event_id,
                    delivered=False,
                    error=type(exc).__name__,
                )
                LOGGER.warning("Falha ao enviar log do evento %s", event_id)
                continue
            await self.bot.database.mark_event_delivery(
                event_id, delivered=True
            )
            completed += 1
        return completed

    async def _build_embed(
        self, event: aiosqlite.Row, sale: Sale | None, colour: int
    ) -> discord.Embed:
        event_type = str(event["event_type"])
        label = EVENT_LABELS.get(event_type, "Evento da SK Store")
        title = f"Venda #{sale.id:04d} · {label}" if sale else label
        embed = discord.Embed(
            title=title,
            colour=colour,
            timestamp=datetime.fromisoformat(str(event["created_at"])),
        )
        summary: list[str] = []
        if sale:
            accounts = await self.bot.database.get_accounts(sale.id)
            quantity = len(accounts)
            account_label = "1 conta" if quantity == 1 else f"{quantity} contas"
            summary.append(f"**Cliente:** <@{sale.customer_id}>")
            if sale.channel_id:
                summary.append(f"**Ticket:** <#{sale.channel_id}>")
            summary.append(
                f"**Resumo:** {account_label} · "
                f"{format_brl(quantity * sale.unit_price_cents)}"
            )
        if event["actor_id"]:
            summary.append(f"**Responsável:** <@{int(event['actor_id'])}>")
        if summary:
            embed.description = "\n".join(summary)
        try:
            payload = json.loads(str(event["payload_json"] or "{}"))
        except json.JSONDecodeError:
            payload = {}
        if "quantity" in payload:
            embed.add_field(
                name="Alteração",
                value=f"{int(payload['quantity'])} conta(s)",
                inline=False,
            )
        if (
            sale
            and sale.close_reason
            and event_type
            in {
                EventType.CUSTOMER_CANCELLED.value,
                EventType.STAFF_CLOSED.value,
            }
        ):
            embed.add_field(
                name="Motivo",
                value=truncate(sale.close_reason, 500),
                inline=False,
            )
        if event_type == EventType.CONFIG_CHANGED.value:
            keys = payload.get("keys", [])
            if isinstance(keys, list) and keys:
                embed.add_field(
                    name="Campos",
                    value=truncate(", ".join(map(str, keys)), 500),
                    inline=False,
                )
        if event_type == EventType.TECHNICAL_FAILURE.value:
            operation = str(payload.get("operation", "indefinida"))[:100]
            error = str(payload.get("error", "erro"))[:100]
            embed.add_field(
                name="Detalhe", value=f"{operation} · {error}", inline=False
            )
        footer = STATUS_LABELS[sale.status] if sale else "SK Store"
        embed.set_footer(text=f"{footer} · SK Store" if sale else footer)
        return embed
