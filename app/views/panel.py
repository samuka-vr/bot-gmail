from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from app.constants import CustomID, DEFAULT_SETTINGS
from app.models import GuildSettings
from app.utils.emojis import custom_emoji
from app.utils.interactions import send_user_error

if TYPE_CHECKING:
    from app.bot import SKStoreBot


class PanelView(discord.ui.View):
    def __init__(
        self, bot: "SKStoreBot", settings: GuildSettings | None = None
    ) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        label = (
            settings.panel_button_text
            if settings
            else DEFAULT_SETTINGS["panel_button_text"]
        )
        button = discord.ui.Button(
            label=label[:80],
            style=discord.ButtonStyle.primary,
            custom_id=CustomID.PANEL_SELL,
            emoji=custom_emoji(settings.icon_sell_id if settings else None),
        )
        button.callback = self.sell
        self.add_item(button)

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item[discord.ui.View],
    ) -> None:
        await self.bot.handle_user_exception(interaction, error)

    async def sell(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await send_user_error(interaction, "Use este botão dentro do servidor.")
            return
        try:
            settings = await self.bot.database.get_settings(interaction.guild.id)
            await self.bot.tickets.validate_configuration(interaction.guild, settings)
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        from app.modals.sale import SaleModal

        await interaction.response.send_modal(SaleModal(self.bot))
