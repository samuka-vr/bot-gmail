from __future__ import annotations

import discord

from app.models import GuildSettings
from app.utils.money import format_brl


def mention_channel(channel_id: int | None) -> str:
    return f"<#{channel_id}>" if channel_id else "Não configurado"


def mention_role(role_id: int | None) -> str:
    return f"<@&{role_id}>" if role_id else "Não configurado"


def configuration_readiness(
    settings: GuildSettings,
) -> tuple[int, int, list[str]]:
    checks = [
        ("canal do painel", bool(settings.panel_channel_id)),
        ("categoria dos tickets", bool(settings.ticket_category_id)),
        ("cargo de Staff", bool(settings.staff_role_id)),
        ("cargo de Admin/Manager", bool(settings.admin_role_id)),
        (
            "preço e limites",
            settings.unit_price_cents > 0
            and 1 <= settings.min_accounts <= settings.max_accounts,
        ),
        (
            "canal de logs",
            not settings.logs_enabled or bool(settings.logs_channel_id),
        ),
        (
            "canal de transcripts",
            not settings.transcripts_enabled
            or bool(settings.transcript_channel_id),
        ),
    ]
    missing = [label for label, passed in checks if not passed]
    return len(checks) - len(missing), len(checks), missing


def build_config_embed(settings: GuildSettings) -> discord.Embed:
    passed, total, missing = configuration_readiness(settings)
    if missing:
        readiness = f"Pendente: {', '.join(missing)}."
    else:
        readiness = "Configuração essencial pronta."
    embed = discord.Embed(
        title="Configuração · SK Store",
        description=(
            f"Configuração principal · **{passed}/{total}**\n"
            f"{readiness}"
        ),
        colour=settings.embed_color,
    )
    embed.add_field(
        name="Operação",
        value=(
            f"Preço: **{format_brl(settings.unit_price_cents)}**\n"
            f"Limites: {settings.min_accounts}–{settings.max_accounts} contas\n"
            "Fechamento automático: "
            f"{'Ativo' if settings.auto_close_enabled else 'Desativado'}"
        ),
        inline=False,
    )
    embed.add_field(
        name="Estrutura",
        value=(
            f"Painel: {mention_channel(settings.panel_channel_id)}\n"
            f"Tickets: {mention_channel(settings.ticket_category_id)}\n"
            f"Staff: {mention_role(settings.staff_role_id)}\n"
            f"Admin: {mention_role(settings.admin_role_id)}"
        ),
        inline=False,
    )
    embed.add_field(
        name="Registros",
        value=(
            f"Logs: {'Ativos' if settings.logs_enabled else 'Desativados'} · "
            f"{mention_channel(settings.logs_channel_id)}\n"
            f"Transcripts: "
            f"{'Ativos' if settings.transcripts_enabled else 'Desativados'} · "
            f"{mention_channel(settings.transcript_channel_id)}"
        ),
        inline=False,
    )
    panel_state = "Painel publicado" if settings.panel_message_id else "Painel não publicado"
    embed.set_footer(text=f"{panel_state} · Alterações salvas no SQLite")
    return embed


def build_section_embed(
    settings: GuildSettings, title: str, description: str
) -> discord.Embed:
    return discord.Embed(
        title=title, description=description, colour=settings.embed_color
    )
