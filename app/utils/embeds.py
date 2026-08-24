from __future__ import annotations

import discord

from app.constants import SaleStatus
from app.models import GuildSettings, Sale, SaleAccount
from app.utils.money import format_brl
from app.utils.text import split_lines, truncate


_SALE_TITLE_STATUS = {
    SaleStatus.WAITING: "Aguardando",
    SaleStatus.ANALYSIS: "Em análise",
    SaleStatus.PAYMENT: "Pagamento",
    SaleStatus.PAID: "Pago",
    SaleStatus.FINALIZED: "Finalizada",
    SaleStatus.CLOSED: "Encerrada",
}


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

    embed = _base_embed(
        settings,
        title=f"Venda #{sale.id:04d} · {_SALE_TITLE_STATUS[sale.status]}",
    )
    account_label = "1 conta" if quantity == 1 else f"{quantity} contas"
    summary = [
        f"**Cliente:** <@{sale.customer_id}>",
    ]
    if sale.responsible_staff_id:
        summary.append(f"**Atendente:** <@{sale.responsible_staff_id}>")
    summary.extend(
        (
            f"**Código:** `{sale.verification_code}`",
            f"**Resumo:** {account_label} · "
            f"{format_brl(sale.unit_price_cents)}/un",
            f"**Total:** {format_brl(total)}",
        )
    )
    embed.description = "\n".join(summary)

    if sale.status is SaleStatus.CLOSED and sale.close_reason:
        embed.add_field(
            name="Encerramento",
            value=f"**Motivo:** {truncate(sale.close_reason, 1_000)}",
            inline=False,
        )

    embed.add_field(
        name="Pagamento",
        value=(
            f"**Pix:** `{truncate(sale.pix_key, 900)}`\n"
            f"**Titular:** {truncate(sale.pix_holder, 900)}"
        ),
        inline=False,
    )

    if sale.status in {
        SaleStatus.WAITING,
        SaleStatus.ANALYSIS,
        SaleStatus.FINALIZED,
        SaleStatus.CLOSED,
    }:
        chunks = split_lines([f"`{account.email}`" for account in accounts])
        for index, chunk in enumerate(chunks):
            embed.add_field(
                name=(
                    f"G-mails · {quantity}"
                    if index == 0
                    else "G-mails · continuação"
                ),
                value=chunk,
                inline=False,
            )

    brand = truncate(settings.panel_footer or "SK Store", 900)
    if sale.status in {SaleStatus.WAITING, SaleStatus.ANALYSIS}:
        footer = f"Nunca envie senhas ou códigos de acesso. · {brand}"
    elif sale.status in {SaleStatus.FINALIZED, SaleStatus.CLOSED} and (
        settings.auto_close_enabled
    ):
        minutes = max(1, (settings.auto_close_delay + 59) // 60)
        footer = f"Fechamento automático em {minutes} min · {brand}"
    else:
        footer = brand
    embed.set_footer(text=truncate(footer, 1_000))
    if settings.logo_url:
        embed.set_thumbnail(url=settings.logo_url)
    return embed
