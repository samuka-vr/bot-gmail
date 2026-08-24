from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from app.constants import CustomID
from app.models import SaleAccount

if TYPE_CHECKING:
    from app.bot import SKStoreBot


class RemoveAccountSelect(discord.ui.Select):
    def __init__(
        self,
        bot: "SKStoreBot",
        sale_id: int,
        customer_id: int,
        accounts: list[SaleAccount],
    ) -> None:
        super().__init__(
            placeholder="Escolha o Gmail",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label=account.email, value=str(account.id))
                for account in accounts[:25]
            ],
            custom_id=CustomID.REMOVE_ACCOUNT,
        )
        self.bot = bot
        self.sale_id = sale_id
        self.customer_id = customer_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.customer_id:
            await interaction.response.send_message(
                "Este carrinho não pertence a você.", ephemeral=True
            )
            return
        await interaction.response.defer()
        try:
            await self.bot.workflow.remove_account(
                interaction, self.sale_id, int(self.values[0])
            )
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.edit_original_response(
            content="Gmail removido.", view=None
        )


class RemoveAccountView(discord.ui.View):
    def __init__(
        self,
        bot: "SKStoreBot",
        sale_id: int,
        customer_id: int,
        accounts: list[SaleAccount],
    ) -> None:
        super().__init__(timeout=180)
        self.add_item(
            RemoveAccountSelect(bot, sale_id, customer_id, accounts)
        )


class CustomerCancelView(discord.ui.View):
    def __init__(
        self, bot: "SKStoreBot", sale_id: int, customer_id: int
    ) -> None:
        super().__init__(timeout=60)
        self.bot = bot
        self.sale_id = sale_id
        self.customer_id = customer_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.customer_id:
            return True
        await interaction.response.send_message(
            "Esta confirmação não pertence a você.", ephemeral=True
        )
        return False

    @discord.ui.button(
        label="Confirmar cancelamento",
        style=discord.ButtonStyle.danger,
        custom_id=CustomID.CONFIRM_CANCEL,
    )
    async def confirm(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await interaction.response.defer()
        try:
            await self.bot.workflow.cancel_by_customer(
                interaction, self.sale_id
            )
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.edit_original_response(
            content="Venda cancelada.", view=None
        )
        self.stop()

    @discord.ui.button(
        label="Manter venda",
        style=discord.ButtonStyle.secondary,
        custom_id=CustomID.ABORT_CANCEL,
    )
    async def abort(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await interaction.response.edit_message(
            content="A venda continua aberta.", view=None
        )
        self.stop()
