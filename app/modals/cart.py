from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

import discord

from app.utils.validation import parse_gmail_lines, validate_pix

if TYPE_CHECKING:
    from app.bot import SKStoreBot


class AddGmailModal(discord.ui.Modal, title="Adicionar Gmail"):
    accounts = discord.ui.Label(
        text="Gmails",
        component=discord.ui.TextInput(
            placeholder="Um Gmail por linha",
            style=discord.TextStyle.paragraph,
            min_length=1,
            max_length=2_000,
            custom_id="sk:modal:add:accounts",
        ),
    )

    def __init__(self, bot: "SKStoreBot", sale_id: int) -> None:
        super().__init__(
            timeout=300,
            custom_id=f"sk:modal:add:{sale_id}:{secrets.token_hex(8)}",
        )
        self.bot = bot
        self.sale_id = sale_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            emails = parse_gmail_lines(str(self.accounts.component))
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await self.bot.workflow.add_accounts(
                interaction, self.sale_id, emails
            )
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.followup.send("Carrinho atualizado.", ephemeral=True)


class EditPixModal(discord.ui.Modal, title="Editar Pix"):
    def __init__(
        self,
        bot: "SKStoreBot",
        sale_id: int,
        current_key: str,
        current_holder: str,
    ) -> None:
        super().__init__(
            timeout=300,
            custom_id=f"sk:modal:pix:{sale_id}:{secrets.token_hex(8)}",
        )
        self.bot = bot
        self.sale_id = sale_id
        self.pix_key = discord.ui.TextInput(
            min_length=3,
            max_length=140,
            default=current_key[:140],
            custom_id="sk:modal:pix:key",
        )
        self.pix_holder = discord.ui.TextInput(
            min_length=2,
            max_length=100,
            default=current_holder[:100],
            custom_id="sk:modal:pix:holder",
        )
        self.add_item(
            discord.ui.Label(text="Chave Pix", component=self.pix_key)
        )
        self.add_item(
            discord.ui.Label(
                text="Nome do titular", component=self.pix_holder
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            key, holder = validate_pix(
                str(self.pix_key), str(self.pix_holder)
            )
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await self.bot.workflow.edit_pix(
                interaction, self.sale_id, key, holder
            )
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.followup.send("Pix atualizado.", ephemeral=True)
