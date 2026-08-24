from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

import discord

from app.database import Database
from app.exceptions import MissingConfiguration, ResourceUnavailable
from app.services.locks import KeyedLocks
from app.utils.embeds import build_panel_embed
from app.views.panel import PanelView

if TYPE_CHECKING:
    from app.bot import SKStoreBot


LOGGER = logging.getLogger(__name__)


class PanelService:
    def __init__(self, bot: "SKStoreBot", database: Database) -> None:
        self.bot = bot
        self.db = database
        self.locks = KeyedLocks()

    async def publish(
        self, guild: discord.Guild, actor_id: int | None
    ) -> tuple[discord.Message, bool]:
        async with self.locks.hold(("panel", guild.id)):
            return await self._publish(guild, actor_id)

    async def _publish(
        self, guild: discord.Guild, actor_id: int | None
    ) -> tuple[discord.Message, bool]:
        settings = await self.db.get_settings(guild.id)
        await self.bot.tickets.validate_configuration(guild, settings)
        if not settings.panel_channel_id:
            raise MissingConfiguration("Configure o canal do painel em /botconfig.")
        channel = guild.get_channel(settings.panel_channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(settings.panel_channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
                raise ResourceUnavailable("O canal do painel não está disponível.") from exc
        if not isinstance(channel, discord.TextChannel):
            raise MissingConfiguration("O painel precisa usar um canal de texto.")

        embed = build_panel_embed(settings)
        view = PanelView(self.bot, settings)
        fallback_view = PanelView(
            self.bot,
            replace(settings, icon_sell_id=None),
        )

        async def send_panel(
            destination: discord.TextChannel,
        ) -> discord.Message:
            try:
                return await destination.send(embed=embed, view=view)
            except discord.Forbidden:
                raise
            except discord.HTTPException:
                if not settings.icon_sell_id:
                    raise
                LOGGER.warning("Publicando painel sem ícone personalizado")
                return await destination.send(embed=embed, view=fallback_view)

        async def edit_panel(target: discord.Message) -> None:
            try:
                await target.edit(embed=embed, view=view, content=None)
            except discord.Forbidden:
                raise
            except discord.HTTPException:
                if not settings.icon_sell_id:
                    raise
                LOGGER.warning("Atualizando painel sem ícone personalizado")
                await target.edit(
                    embed=embed,
                    view=fallback_view,
                    content=None,
                )

        message: discord.Message | None = None
        created = False
        if settings.panel_message_id:
            message_channel_id = (
                settings.panel_message_channel_id
                or settings.panel_channel_id
            )
            message_channel = guild.get_channel(message_channel_id)
            if message_channel is None:
                try:
                    message_channel = await guild.fetch_channel(
                        message_channel_id
                    )
                except discord.NotFound:
                    message_channel = None
                except (discord.Forbidden, discord.HTTPException) as exc:
                    raise ResourceUnavailable(
                        "Não consegui consultar o canal do painel atual."
                    ) from exc
            if message_channel is not None and not isinstance(
                message_channel, discord.TextChannel
            ):
                message_channel = None
            try:
                if isinstance(message_channel, discord.TextChannel):
                    message = await message_channel.fetch_message(
                        settings.panel_message_id
                    )
            except discord.NotFound:
                message = None
            except (discord.Forbidden, discord.HTTPException) as exc:
                raise ResourceUnavailable(
                    "Não consegui consultar a mensagem atual do painel."
                ) from exc
        if message and message.channel.id == channel.id:
            await edit_panel(message)
            await self.db.set_settings(
                guild.id,
                {
                    "panel_message_id": str(message.id),
                    "panel_message_channel_id": str(channel.id),
                },
                actor_id,
            )
        elif message:
            replacement = await send_panel(channel)
            try:
                await self.db.set_settings(
                    guild.id,
                    {
                        "panel_message_id": str(replacement.id),
                        "panel_message_channel_id": str(channel.id),
                    },
                    actor_id,
                )
            except Exception:
                try:
                    await replacement.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
                raise
            try:
                await message.delete()
            except discord.NotFound:
                pass
            except (discord.Forbidden, discord.HTTPException) as exc:
                await self.db.set_settings(
                    guild.id,
                    {
                        "panel_message_id": str(message.id),
                        "panel_message_channel_id": str(message.channel.id),
                    },
                    actor_id,
                )
                try:
                    await replacement.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
                raise ResourceUnavailable(
                    "Não consegui remover o painel do canal anterior."
                ) from exc
            message = replacement
            created = True
        else:
            message = await send_panel(channel)
            try:
                await self.db.set_settings(
                    guild.id,
                    {
                        "panel_message_id": str(message.id),
                        "panel_message_channel_id": str(channel.id),
                    },
                    actor_id,
                )
            except Exception:
                try:
                    await message.delete()
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
                raise
            created = True
        return message, created
