from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

import discord

from app.utils.validation import parse_gmail_lines, validate_pix

if TYPE_CHECKING:
    from app.bot import SKStoreBot


class SaleModal(discord.ui.Modal, title="Vender Gmail"):
    accounts = discord.ui.Label(
        text="Gmails",
        component=discord.ui.TextInput(
            placeholder="Um Gmail por linha",
            style=discord.TextStyle.paragraph,
            min_length=1,
            max_length=2_000,
            required=True,
            custom_id="sk:modal:sale:accounts",
        ),
    )
    pix_key = discord.ui.Label(
        text="Chave Pix",
        component=discord.ui.TextInput(
            min_length=3,
            max_length=140,
            required=True,
            custom_id="sk:modal:sale:pix_key",
        ),
    )
    pix_holder = discord.ui.Label(
        text="Nome do titular",
        component=discord.ui.TextInput(
            min_length=2,
            max_length=100,
            required=True,
            custom_id="sk:modal:sale:pix_holder",
        ),
    )

    def __init__(self, bot: "SKStoreBot") -> None:
        super().__init__(
            timeout=300,
            custom_id=f"sk:modal:sale:{secrets.token_hex(8)}",
        )
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            emails = parse_gmail_lines(str(self.accounts.component))
            pix_key, holder = validate_pix(
                str(self.pix_key.component),
                str(self.pix_holder.component),
            )
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            channel = await self.bot.workflow.open_sale(
                interaction, emails, pix_key, holder
            )
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.followup.send(
            f"Recebemos sua venda. Acompanhe em {channel.mention}.",
            ephemeral=True,
        )

    async def on_error(
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        await self.bot.handle_user_exception(interaction, error)
