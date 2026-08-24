from __future__ import annotations

import secrets
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from app.bot import SKStoreBot


class NotifyCustomerModal(discord.ui.Modal, title="Notificar cliente"):
    message = discord.ui.Label(
        text="Mensagem",
        component=discord.ui.TextInput(
            placeholder="Sua venda precisa da sua atenção.",
            style=discord.TextStyle.paragraph,
            min_length=2,
            max_length=500,
            custom_id="sk:modal:notify:message",
        ),
    )

    def __init__(self, bot: "SKStoreBot", sale_id: int) -> None:
        super().__init__(
            timeout=300,
            custom_id=f"sk:modal:notify:{sale_id}:{secrets.token_hex(8)}",
        )
        self.bot = bot
        self.sale_id = sale_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            sent = await self.bot.workflow.notify_customer(
                interaction,
                self.sale_id,
                str(self.message.component).strip(),
            )
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        text = "Cliente notificado." if sent else "A DM do cliente está fechada."
        await interaction.followup.send(text, ephemeral=True)


class CloseSaleModal(discord.ui.Modal, title="Encerrar venda"):
    reason = discord.ui.Label(
        text="Motivo",
        component=discord.ui.TextInput(
            style=discord.TextStyle.paragraph,
            min_length=2,
            max_length=500,
            custom_id="sk:modal:close:reason",
        ),
    )

    def __init__(self, bot: "SKStoreBot", sale_id: int) -> None:
        super().__init__(
            timeout=300,
            custom_id=f"sk:modal:close:{sale_id}:{secrets.token_hex(8)}",
        )
        self.bot = bot
        self.sale_id = sale_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await self.bot.workflow.close_by_staff(
                interaction,
                self.sale_id,
                str(self.reason.component).strip(),
            )
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.followup.send("Venda encerrada.", ephemeral=True)
