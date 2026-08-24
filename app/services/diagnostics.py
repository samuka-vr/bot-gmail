from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from app.bot import SKStoreBot


@dataclass(frozen=True, slots=True)
class Check:
    label: str
    passed: bool
    detail: str = ""


class DiagnosticService:
    def __init__(self, bot: "SKStoreBot") -> None:
        self.bot = bot

    async def build(self, guild: discord.Guild) -> discord.Embed:
        settings = await self.bot.database.get_settings(guild.id)
        checks: list[Check] = []

        panel = await self._channel(guild, settings.panel_channel_id)
        category = await self._channel(guild, settings.ticket_category_id)
        logs = await self._channel(guild, settings.logs_channel_id)
        transcripts = await self._channel(
            guild, settings.transcript_channel_id
        )
        staff_role = guild.get_role(settings.staff_role_id or 0)
        admin_role = guild.get_role(settings.admin_role_id or 0)
        bot_member = guild.me
        checks.extend(
            [
                Check("Canal do painel", isinstance(panel, discord.TextChannel)),
                Check(
                    "Categoria de tickets",
                    isinstance(category, discord.CategoryChannel),
                ),
                Check("Canal de logs", isinstance(logs, discord.TextChannel)),
                Check(
                    "Canal de transcripts",
                    isinstance(transcripts, discord.TextChannel),
                ),
                Check(
                    "Cargo de Staff",
                    bool(
                        staff_role
                        and staff_role.id != guild.default_role.id
                    ),
                ),
                Check(
                    "Cargo de Admin/Manager",
                    bool(
                        admin_role
                        and admin_role.id != guild.default_role.id
                    ),
                ),
                Check(
                    "Cargos separados",
                    bool(
                        staff_role
                        and admin_role
                        and staff_role.id != admin_role.id
                    ),
                ),
                Check(
                    "Hierarquia de cargos",
                    bool(
                        bot_member
                        and staff_role
                        and admin_role
                        and bot_member.top_role > staff_role
                        and bot_member.top_role > admin_role
                    ),
                    "bot acima de Staff e Admin",
                ),
            ]
        )
        text_channels = [
            channel
            for channel in (panel, logs, transcripts)
            if isinstance(channel, discord.TextChannel)
        ]
        can_send = bool(bot_member and text_channels) and all(
            channel.permissions_for(bot_member).send_messages
            for channel in text_channels
        )
        can_embed = bool(bot_member and text_channels) and all(
            channel.permissions_for(bot_member).embed_links
            for channel in text_channels
        )
        category_permissions = (
            category.permissions_for(bot_member)
            if bot_member and isinstance(category, discord.CategoryChannel)
            else None
        )
        can_send = bool(
            can_send
            and category_permissions
            and category_permissions.send_messages
        )
        can_embed = bool(
            can_embed
            and category_permissions
            and category_permissions.embed_links
        )
        can_attach = bool(
            bot_member
            and category_permissions
            and category_permissions.attach_files
            and isinstance(transcripts, discord.TextChannel)
            and transcripts.permissions_for(bot_member).attach_files
        )
        checks.extend(
            [
                Check("Enviar mensagens", can_send),
                Check("Enviar embeds", can_embed),
                Check("Anexar transcripts", can_attach),
                Check(
                    "Criar canais de ticket",
                    bool(
                        category_permissions
                        and category_permissions.manage_channels
                    ),
                ),
                Check(
                    "Gerenciar permissões do ticket",
                    bool(
                        category_permissions
                        and category_permissions.manage_roles
                    ),
                ),
                Check(
                    "Ler histórico do ticket",
                    bool(
                        category_permissions
                        and category_permissions.read_message_history
                    ),
                ),
            ]
        )

        checks.append(Check("SQLite gravável", await self.bot.database.writable_check()))
        checks.append(
            Check("Mensagem do painel", await self._panel_exists(panel, settings.panel_message_id))
        )
        persistent = (
            self.bot.persistent_views_added
            and len(self.bot.persistent_views) >= 5
            and all(view.is_persistent() for view in self.bot.persistent_views)
        )
        checks.append(Check("Views persistentes", persistent))
        intents_ok = bool(
            self.bot.intents.guilds
            and self.bot.intents.guild_messages
            and self.bot.intents.message_content
        )
        checks.append(
            Check(
                "Intents obrigatórias",
                intents_ok,
                "guilds, guild_messages, message_content",
            )
        )

        passed = sum(check.passed for check in checks)
        lines = [
            f"[{'OK' if check.passed else 'FALHA'}] {check.label}"
            + (f" — {check.detail}" if check.detail else "")
            for check in checks
        ]
        embed = discord.Embed(
            title="Diagnóstico · SK Store",
            description="\n".join(lines),
            colour=settings.embed_color,
        )
        embed.set_footer(text=f"{passed}/{len(checks)} verificações aprovadas")
        return embed

    async def _channel(
        self, guild: discord.Guild, channel_id: int | None
    ) -> discord.abc.GuildChannel | None:
        if not channel_id:
            return None
        channel = guild.get_channel(channel_id)
        if channel is not None:
            return channel
        try:
            return await guild.fetch_channel(channel_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    @staticmethod
    async def _panel_exists(
        channel: discord.abc.GuildChannel | None, message_id: int | None
    ) -> bool:
        if not isinstance(channel, discord.TextChannel) or not message_id:
            return False
        try:
            await channel.fetch_message(message_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return False
        return True
