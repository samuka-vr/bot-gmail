from __future__ import annotations

import discord

from app.constants import STATUS_LABELS, SaleStatus
from app.models import GuildSettings, Sale, SaleAccount
from app.utils.money import format_brl
from app.utils.text import split_lines, truncate


def _base_embed(settings: GuildSettings, *, title: str) -> discord.Embed:
    return discord.Embed(title=title, colour=settings.embed_color)


def build_panel_embed(settings: GuildSettings) -> discord.Embed:
    embed = _base_embed(settings, title=truncate(settings.panel_title, 256))
    # Keep the complete embed below Discord's 6,000-character aggregate limit.
    embed.description = truncate(settings.panel_description, 3_200)
    embed.add_field(
        name=truncate(settings.panel_price_label, 256),
        value=format_brl(settings.unit_price_cents),
        inline=False,
    )
    if settings.panel_info_text:
        embed.add_field(
            name="Informação",
            value=truncate(settings.panel_info_text, 1024),
            inline=False,
        )
    if settings.logo_url:
        embed.set_thumbnail(url=settings.logo_url)
    if settings.banner_url:
        embed.set_image(url=settings.banner_url)
    if settings.panel_footer:
        embed.set_footer(text=truncate(settings.panel_footer, 1_000))
    return embed


def build_sale_embed(
    sale: Sale,
    accounts: list[SaleAccount],
    settings: GuildSettings,
) -> discord.Embed:
    quantity = len(accounts)
    total = quantity * sale.unit_price_cents

    if sale.status is SaleStatus.PAYMENT:
        embed = _base_embed(
            settings, title=f"Pagamento · Venda #{sale.id:04d}"
        )
        embed.description = "Confira os dados antes de confirmar."
    elif sale.status is SaleStatus.PAID:
        embed = _base_embed(
            settings, title=f"Pagamento confirmado · Venda #{sale.id:04d}"
        )
        embed.description = "Pagamento registrado."
    else:
        embed = _base_embed(settings, title=f"Venda #{sale.id:04d}")
        embed.description = STATUS_LABELS[sale.status]
        if sale.status in {SaleStatus.WAITING, SaleStatus.ANALYSIS}:
            embed.description += "\n\nNunca envie senha ou códigos de acesso."

    embed.add_field(name="Cliente", value=f"<@{sale.customer_id}>", inline=True)
    if sale.responsible_staff_id:
        embed.add_field(
            name="Atendente",
            value=f"<@{sale.responsible_staff_id}>",
            inline=True,
        )
    embed.add_field(name="Código", value=sale.verification_code, inline=True)
    embed.add_field(name="Contas", value=str(quantity), inline=True)
    embed.add_field(
        name="Valor por conta",
        value=format_brl(sale.unit_price_cents),
        inline=True,
    )
    embed.add_field(name="Total", value=format_brl(total), inline=True)
    embed.add_field(name="Pix", value=truncate(sale.pix_key, 1024), inline=False)
    embed.add_field(
        name="Titular", value=truncate(sale.pix_holder, 1024), inline=False
    )

    if sale.status in {
        SaleStatus.WAITING,
        SaleStatus.ANALYSIS,
        SaleStatus.FINALIZED,
        SaleStatus.CLOSED,
    }:
        chunks = split_lines([account.email for account in accounts])
        for index, chunk in enumerate(chunks):
            embed.add_field(
                name="G-mails" if index == 0 else "G-mails (continuação)",
                value=chunk,
                inline=False,
            )

    if sale.status is SaleStatus.FINALIZED:
        embed.description = "Venda finalizada."
    elif sale.status is SaleStatus.CLOSED:
        embed.description = "Venda encerrada."
        if sale.close_reason:
            embed.add_field(
                name="Motivo",
                value=truncate(sale.close_reason, 1024),
                inline=False,
            )
    embed.set_footer(text="SK Store")
    return embed
