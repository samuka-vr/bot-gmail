from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord

from app.models import GuildSettings

if TYPE_CHECKING:
    from app.bot import SKStoreBot


@dataclass(frozen=True, slots=True)
class Check:
    label: str
    passed: bool
    detail: str = ""
    group: str = "Sistema"


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
                Check(
                    "Canal do painel",
                    isinstance(panel, discord.TextChannel),
                    group="Configuração",
                ),
                Check(
                    "Categoria de tickets",
                    isinstance(category, discord.CategoryChannel),
                    group="Configuração",
                ),
                Check(
                    "Canal de logs",
                    not settings.logs_enabled
                    or isinstance(logs, discord.TextChannel),
                    group="Configuração",
                ),
                Check(
                    "Canal de transcripts",
                    not settings.transcripts_enabled
                    or isinstance(transcripts, discord.TextChannel),
                    group="Configuração",
                ),
                Check(
                    "Cargo de Staff",
                    bool(
                        staff_role
                        and staff_role.id != guild.default_role.id
                    ),
                    group="Configuração",
                ),
                Check(
                    "Cargo de Admin/Manager",
                    bool(
                        admin_role
                        and admin_role.id != guild.default_role.id
                    ),
                    group="Configuração",
                ),
                Check(
                    "Cargos separados",
                    bool(
                        staff_role
                        and admin_role
                        and staff_role.id != admin_role.id
                    ),
                    group="Configuração",
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
                    "Configuração",
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
        can_attach = not settings.transcripts_enabled or bool(
            bot_member
            and category_permissions
            and category_permissions.attach_files
            and isinstance(transcripts, discord.TextChannel)
            and transcripts.permissions_for(bot_member).attach_files
        )
        checks.extend(
            [
                Check(
                    "Enviar mensagens", can_send, group="Permissões"
                ),
                Check("Enviar embeds", can_embed, group="Permissões"),
                Check(
                    "Anexar transcripts", can_attach, group="Permissões"
                ),
                Check(
                    "Criar canais de ticket",
                    bool(
                        category_permissions
                        and category_permissions.manage_channels
                    ),
                    group="Permissões",
                ),
                Check(
                    "Gerenciar permissões do ticket",
                    bool(
                        category_permissions
                        and category_permissions.manage_roles
                    ),
                    group="Permissões",
                ),
                Check(
                    "Ler histórico do ticket",
                    bool(
                        category_permissions
                        and category_permissions.read_message_history
                    ),
                    group="Permissões",
                ),
            ]
        )

        checks.append(
            Check("SQLite gravável", await self.bot.database.writable_check())
        )
        checks.append(
            Check("Mensagem do painel", await self._panel_exists(panel, settings.panel_message_id))
        )
        persistent = (
            self.bot.persistent_views_added
            and len(self.bot.persistent_views) >= 5
            and all(view.is_persistent() for view in self.bot.persistent_views)
        )
        checks.append(Check("Views persistentes", persistent))
        checks.append(
            Check(
                "Agendador de fechamento",
                self.bot.maintenance.running,
            )
        )
        checks.append(
            Check(
                "Prazo do auto-close",
                not settings.auto_close_enabled
                or settings.auto_close_delay >= 30,
                (
                    f"{settings.auto_close_delay} s"
                    if settings.auto_close_enabled
                    else "desativado"
                ),
            )
        )
        icons_ok, icons_detail = await self._custom_icons(guild, settings)
        checks.append(Check("Ícones personalizados", icons_ok, icons_detail))
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
        embed = discord.Embed(
            title="Diagnóstico · SK Store",
            description=(
                "Confira as pendências antes de publicar ou atualizar o painel."
            ),
            colour=settings.embed_color,
        )
        for group in ("Configuração", "Permissões", "Sistema"):
            grouped = [check for check in checks if check.group == group]
            group_passed = sum(check.passed for check in grouped)
            lines = [
                f"[{'OK' if check.passed else 'FALHA'}] {check.label}"
                + (f" — {check.detail}" if check.detail else "")
                for check in grouped
            ]
            embed.add_field(
                name=f"{group} · {group_passed}/{len(grouped)}",
                value="\n".join(lines),
                inline=False,
            )
        embed.set_footer(text=f"{passed}/{len(checks)} verificações aprovadas")
        return embed

    async def _custom_icons(
        self, guild: discord.Guild, settings: GuildSettings
    ) -> tuple[bool, str]:
        icon_ids = {
            int(icon_id)
            for icon_id in (
                settings.icon_sell_id,
                settings.icon_edit_id,
                settings.icon_staff_id,
                settings.icon_payment_id,
            )
            if icon_id
        }
        if not icon_ids:
            return True, "não configurados"

        available = {
            emoji_id
            for emoji_id in icon_ids
            if guild.get_emoji(emoji_id) is not None
            or self.bot.get_emoji(emoji_id) is not None
        }
        fetcher = getattr(self.bot, "fetch_application_emojis", None)
        if fetcher is not None:
            try:
                available.update(emoji.id for emoji in await fetcher())
            except (discord.Forbidden, discord.HTTPException):
                pass
        missing = sorted(icon_ids - available)
        if missing:
            return False, "não encontrados: " + ", ".join(map(str, missing))
        return True, f"{len(icon_ids)} disponíveis"

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
