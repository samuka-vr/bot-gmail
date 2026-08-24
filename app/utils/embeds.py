from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

import discord

from app.constants import STATUS_LABELS, SaleStatus
from app.models import GuildSettings, Sale, SaleAccount
from app.utils.money import format_brl
from app.utils.text import split_lines, truncate


_SALE_TITLE_STATUS = {
    SaleStatus.WAITING: "Aguardando",
    SaleStatus.ANALYSIS: "Em análise",
    SaleStatus.PAYMENT: "Pagamento",
    SaleStatus.PAID: "Pagamento confirmado",
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
        value=f"**{format_brl(settings.unit_price_cents)}**",
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
    embed.timestamp = sale.updated_at
    account_label = "1 conta" if quantity == 1 else f"{quantity} contas"
    summary = [
        f"**Cliente:** <@{sale.customer_id}>",
    ]
    if sale.responsible_staff_id:
        summary.append(f"**Atendente:** <@{sale.responsible_staff_id}>")
    summary.extend(
        (
            f"**Código:** `{sale.verification_code}`",
            "",
            f"**{account_label} · {format_brl(sale.unit_price_cents)} cada**",
            f"Total a receber: **{format_brl(total)}**",
        )
    )
    if sale.status in {SaleStatus.FINALIZED, SaleStatus.CLOSED}:
        summary.append("")
        if sale.ticket_delete_at:
            unix_time = int(sale.ticket_delete_at.timestamp())
            summary.append(f"Este ticket será fechado <t:{unix_time}:R>.")
        else:
            summary.append("Ticket encerrado e bloqueado.")
    embed.description = "\n".join(summary)

    if sale.status is SaleStatus.CLOSED and sale.close_reason:
        embed.add_field(
            name="Encerramento",
            value=f"**Motivo:** {truncate(sale.close_reason, 1_000)}",
            inline=False,
        )

    embed.add_field(
        name="Recebimento via Pix",
        value=(
            f"**Chave:** `{truncate(sale.pix_key, 900)}`\n"
            f"**Titular:** {truncate(sale.pix_holder, 900)}"
        ),
        inline=False,
    )

    if sale.status in {
        SaleStatus.WAITING,
        SaleStatus.ANALYSIS,
    }:
        chunks = split_lines([f"`{account.email}`" for account in accounts])
        for index, chunk in enumerate(chunks):
            embed.add_field(
                name=(
                    f"Contas enviadas · {quantity}"
                    if index == 0
                    else "Contas enviadas · continuação"
                ),
                value=chunk,
                inline=False,
            )

    brand = truncate(settings.panel_footer or "SK Store", 900)
    if sale.status in {SaleStatus.WAITING, SaleStatus.ANALYSIS}:
        footer = f"Nunca envie senha ou código de acesso. · {brand}"
    elif sale.status is SaleStatus.PAYMENT:
        footer = f"Carrinho bloqueado · {brand}"
    elif sale.status is SaleStatus.PAID:
        footer = f"Pagamento confirmado · {brand}"
    else:
        footer = brand
    embed.set_footer(text=truncate(footer, 1_000))
    if settings.logo_url:
        embed.set_thumbnail(url=settings.logo_url)
    return embed


def build_customer_dm_embed(
    sale: Sale,
    settings: GuildSettings,
    message: str,
    *,
    staff_name: str | None = None,
) -> discord.Embed:
    embed = _base_embed(
        settings,
        title=f"SK Store · Venda #{sale.id:04d}",
    )
    embed.description = truncate(message.strip(), 4_000)
    footer = f"Mensagem de {staff_name} · SK Store" if staff_name else "SK Store"
    embed.set_footer(text=truncate(footer, 1_000))
    if settings.logo_url:
        embed.set_thumbnail(url=settings.logo_url)
    return embed


def _row_value(row: Mapping[str, object], key: str) -> object:
    return row[key]


def _unix_timestamp(value: object) -> int | None:
    if isinstance(value, datetime):
        current = value
    elif isinstance(value, str) and value:
        try:
            current = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return int(current.timestamp())


def build_profile_embed(
    profile: Mapping[str, object],
    user_id: int,
    settings: GuildSettings,
) -> discord.Embed:
    embed = _base_embed(settings, title="Perfil de vendas")
    embed.description = (
        f"<@{user_id}>\n"
        f"Vendas canceladas: **{int(profile['cancelled_sales'])}**"
    )
    embed.add_field(
        name="Concluídas",
        value=str(int(profile["completed_sales"])),
        inline=True,
    )
    embed.add_field(
        name="Contas vendidas",
        value=str(int(profile["sold_accounts"])),
        inline=True,
    )
    embed.add_field(
        name="Total recebido",
        value=format_brl(int(profile["received_cents"])),
        inline=True,
    )

    recent_lines: list[str] = []
    recent = profile.get("recent", [])
    if isinstance(recent, Sequence):
        for row in recent:
            status = SaleStatus(str(_row_value(row, "status")))
            total = int(_row_value(row, "unit_price_cents")) * int(
                _row_value(row, "account_count")
            )
            line = (
                f"#{int(_row_value(row, 'id')):04d} · "
                f"{STATUS_LABELS[status]} · {format_brl(total)}"
            )
            created = _unix_timestamp(_row_value(row, "created_at"))
            if created:
                line += f" · <t:{created}:d>"
            recent_lines.append(line)
    embed.add_field(
        name="Últimas vendas",
        value="\n".join(recent_lines) if recent_lines else "Nenhuma venda.",
        inline=False,
    )
    embed.set_footer(text=truncate(settings.panel_footer or "SK Store", 1_000))
    if settings.logo_url:
        embed.set_thumbnail(url=settings.logo_url)
    return embed


_QUEUE_STATUS_LABELS = {
    SaleStatus.WAITING: "Aguardando",
    SaleStatus.ANALYSIS: "Em análise",
    SaleStatus.PAYMENT: "Pagamento",
    SaleStatus.PAID: "Pagamento confirmado",
}


def build_queue_embed(
    rows: Sequence[Mapping[str, object]], settings: GuildSettings
) -> discord.Embed:
    groups: dict[SaleStatus, list[str]] = {
        status: []
        for status in (
            SaleStatus.WAITING,
            SaleStatus.ANALYSIS,
            SaleStatus.PAYMENT,
            SaleStatus.PAID,
        )
    }
    for row in rows:
        status = SaleStatus(str(_row_value(row, "status")))
        count = int(_row_value(row, "account_count"))
        total = count * int(_row_value(row, "unit_price_cents"))
        account_label = "1 conta" if count == 1 else f"{count} contas"
        line = (
            f"#{int(_row_value(row, 'id')):04d} · "
            f"<@{int(_row_value(row, 'customer_id'))}>"
        )
        staff_id = _row_value(row, "responsible_staff_id")
        if staff_id:
            line += f" · <@{int(staff_id)}>"
        line += f" · {account_label} · {format_brl(total)}"
        created = _unix_timestamp(_row_value(row, "created_at"))
        if created:
            line += f" · <t:{created}:R>"
        channel_id = _row_value(row, "channel_id")
        if channel_id:
            line += f" · <#{int(channel_id)}>"
        groups[status].append(line)

    embed = _base_embed(settings, title=f"Fila de vendas · {len(rows)}")
    if not rows:
        embed.description = "Nenhuma venda na fila."
    for status, lines in groups.items():
        if not lines:
            continue
        chunks = split_lines(lines)
        for index, chunk in enumerate(chunks):
            name = (
                f"{_QUEUE_STATUS_LABELS[status]} · {len(lines)}"
                if index == 0
                else f"{_QUEUE_STATUS_LABELS[status]} · continuação"
            )
            embed.add_field(name=name, value=chunk, inline=False)
    embed.set_footer(text="Até 20 vendas ativas")
    return embed
