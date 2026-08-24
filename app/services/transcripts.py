from __future__ import annotations

import html
import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

import discord

from app.constants import STATUS_LABELS
from app.exceptions import MissingConfiguration, ResourceUnavailable
from app.models import GuildSettings, Sale, SaleAccount
from app.utils.money import format_brl

if TYPE_CHECKING:
    from app.bot import SKStoreBot


LOGGER = logging.getLogger(__name__)


class TranscriptService:
    def __init__(self, bot: "SKStoreBot") -> None:
        self.bot = bot

    async def create_and_send(
        self,
        ticket: discord.TextChannel,
        sale: Sale,
        settings: GuildSettings,
    ) -> discord.Message:
        destination = await self._destination(ticket.guild, settings)
        path = await self._write_html(ticket, sale)
        try:
            message = await destination.send(
                content=f"Transcript · Venda #{sale.id:04d}",
                file=discord.File(
                    path,
                    filename=f"transcript-venda-{sale.id:04d}.html",
                ),
            )
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                LOGGER.warning("Não foi possível remover o transcript temporário")
        await self.bot.database.mark_transcript_sent(sale.id, message.id)
        return message

    async def _destination(
        self, guild: discord.Guild, settings: GuildSettings
    ) -> discord.TextChannel:
        if not settings.transcript_channel_id:
            raise MissingConfiguration("Configure o canal de transcripts.")
        channel = guild.get_channel(settings.transcript_channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(settings.transcript_channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
                raise ResourceUnavailable(
                    "O canal de transcripts não está disponível."
                ) from exc
        if not isinstance(channel, discord.TextChannel):
            raise MissingConfiguration(
                "O canal de transcripts precisa ser um canal de texto."
            )
        return channel

    async def _write_html(
        self, ticket: discord.TextChannel, sale: Sale
    ) -> Path:
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f"sk-transcript-{sale.id}-", suffix=".html"
        )
        path = Path(raw_path)
        try:
            accounts = await self.bot.database.get_accounts(sale.id)
            file_object = os.fdopen(descriptor, "w", encoding="utf-8")
            descriptor = -1
            with file_object as output:
                self._write_header(output, ticket, sale, accounts)
                async for message in ticket.history(
                    limit=None, oldest_first=True
                ):
                    self._write_message(output, message)
                output.write("</section></main></body></html>")
        except Exception:
            if descriptor >= 0:
                os.close(descriptor)
            try:
                path.unlink(missing_ok=True)
            except OSError:
                LOGGER.warning(
                    "Não foi possível remover o transcript temporário incompleto"
                )
            raise
        return path

    @staticmethod
    def _write_header(
        output: TextIO,
        ticket: discord.TextChannel,
        sale: Sale,
        accounts: list[SaleAccount],
    ) -> None:
        account_lines = "<br>".join(
            html.escape(account.email) for account in accounts
        )
        total = len(accounts) * sale.unit_price_cents

        def timestamp(value: object) -> str:
            return html.escape(value.isoformat()) if value else "-"

        output.write(
            "<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>Venda #{sale.id:04d}</title><style>"
            ":root{color-scheme:dark}body{margin:0;background:#111318;color:#edf0f5;"
            "font:15px system-ui,-apple-system,sans-serif}main{max-width:900px;"
            "margin:auto;padding:24px}.card{background:#1b1f27;border:1px solid #303642;"
            "border-radius:12px;padding:18px;margin-bottom:18px}.meta{display:grid;"
            "grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}.label{"
            "color:#9ca6b6;font-size:12px;text-transform:uppercase}.message{display:grid;"
            "grid-template-columns:170px 1fr;gap:14px;padding:14px 0;border-top:1px solid "
            "#2a303a}.author{font-weight:650}.time{color:#9ca6b6;font-size:12px}.body{"
            "white-space:pre-wrap;word-break:break-word}a{color:#8ab4ff}.embed{"
            "border-left:3px solid #6b7280;padding-left:10px;margin-top:8px}@media(max-width:"
            "640px){main{padding:12px}.message{grid-template-columns:1fr;gap:5px}}"
            "</style></head><body><main>"
            f"<section class='card'><h1>Venda #{sale.id:04d}</h1>"
            "<div class='meta'>"
            f"<div><div class='label'>Ticket</div>{html.escape(ticket.name)}</div>"
            "<div><div class='label'>Status final</div>"
            f"{html.escape(STATUS_LABELS[sale.status])}</div>"
            f"<div><div class='label'>Cliente</div>{sale.customer_id}</div>"
            f"<div><div class='label'>Staff</div>{sale.responsible_staff_id or '-'}</div>"
            "<div><div class='label'>Pagamento confirmado por</div>"
            f"{sale.payment_confirmed_by_id or '-'}</div>"
            "<div><div class='label'>Finalizada por</div>"
            f"{sale.completed_by_id or sale.closed_by_id or '-'}</div>"
            f"<div><div class='label'>Código</div>{html.escape(sale.verification_code)}</div>"
            f"<div><div class='label'>Contas</div>{len(accounts)}</div>"
            f"<div><div class='label'>Preço</div>{format_brl(sale.unit_price_cents)}</div>"
            f"<div><div class='label'>Total</div>{format_brl(total)}</div>"
            f"<div><div class='label'>Pix</div>{html.escape(sale.pix_key)}</div>"
            f"<div><div class='label'>Titular</div>{html.escape(sale.pix_holder)}</div>"
            "</div>"
            f"<p><span class='label'>G-mails</span><br>{account_lines}</p>"
            "<p><span class='label'>Motivo do encerramento</span><br>"
            f"{html.escape(sale.close_reason or '-')}</p>"
            "<div class='meta'>"
            f"<div><div class='label'>Criada</div>{timestamp(sale.created_at)}</div>"
            f"<div><div class='label'>Assumida</div>{timestamp(sale.claimed_at)}</div>"
            "<div><div class='label'>Pagamento aberto</div>"
            f"{timestamp(sale.payment_stage_at)}</div>"
            f"<div><div class='label'>Paga</div>{timestamp(sale.paid_at)}</div>"
            f"<div><div class='label'>Finalizada</div>{timestamp(sale.completed_at)}</div>"
            f"<div><div class='label'>Encerrada</div>{timestamp(sale.closed_at)}</div>"
            "</div>"
            "</section><section class='card'><h2>Mensagens</h2>"
        )

    @staticmethod
    def _write_message(output: TextIO, message: discord.Message) -> None:
        author = html.escape(str(message.author))
        content = html.escape(message.content or "")
        output.write(
            "<article class='message'>"
            f"<div><div class='author'>{author}</div>"
            f"<div class='time'>{message.created_at.isoformat()}</div>"
            f"<div class='time'>ID {message.author.id}</div></div>"
            f"<div class='body'>{content}"
        )
        for attachment in message.attachments:
            url = html.escape(attachment.url, quote=True)
            name = html.escape(attachment.filename)
            output.write(f"<div><a href='{url}'>{name}</a></div>")
        for embed in message.embeds:
            output.write("<div class='embed'>")
            if embed.title:
                output.write(f"<strong>{html.escape(embed.title)}</strong><br>")
            if embed.description:
                output.write(html.escape(embed.description))
            for field in embed.fields:
                output.write(
                    f"<div><b>{html.escape(field.name)}</b><br>"
                    f"{html.escape(field.value)}</div>"
                )
            output.write("</div>")
        output.write("</div></article>")
