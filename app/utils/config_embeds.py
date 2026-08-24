from __future__ import annotations

import discord

from app.models import GuildSettings
from app.utils.money import format_brl


def mention_channel(channel_id: int | None) -> str:
    return f"<#{channel_id}>" if channel_id else "Não configurado"


def mention_role(role_id: int | None) -> str:
    return f"<@&{role_id}>" if role_id else "Não configurado"


def build_config_embed(settings: GuildSettings) -> discord.Embed:
    embed = discord.Embed(
        title="Configuração · SK Store",
        description="Escolha uma área para editar.",
        colour=settings.embed_color,
    )
    embed.add_field(
        name="Preço",
        value=f"{format_brl(settings.unit_price_cents)} · "
        f"{settings.min_accounts}–{settings.max_accounts} contas",
        inline=False,
    )
    embed.add_field(
        name="Painel",
        value=mention_channel(settings.panel_channel_id),
        inline=True,
    )
    embed.add_field(
        name="Tickets",
        value=mention_channel(settings.ticket_category_id),
        inline=True,
    )
    embed.add_field(
        name="Staff",
        value=mention_role(settings.staff_role_id),
        inline=True,
    )
    embed.add_field(
        name="Logs",
        value="Ativos" if settings.logs_enabled else "Desativados",
        inline=True,
    )
    embed.add_field(
        name="Transcripts",
        value="Ativos" if settings.transcripts_enabled else "Desativados",
        inline=True,
    )
    embed.set_footer(text="Alterações são salvas no SQLite")
    return embed


def build_section_embed(
    settings: GuildSettings, title: str, description: str
) -> discord.Embed:
    return discord.Embed(
        title=title, description=description, colour=settings.embed_color
    )
