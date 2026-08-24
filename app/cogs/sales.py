from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from app.modals.sale import SaleModal

if TYPE_CHECKING:
    from app.bot import SKStoreBot


class SalesCog(commands.Cog):
    def __init__(self, bot: "SKStoreBot") -> None:
        self.bot = bot

    @app_commands.command(
        name="vender", description="Inicia uma venda de G-mails."
    )
    @app_commands.guild_only()
    async def sell(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        try:
            settings = await self.bot.database.get_settings(interaction.guild.id)
            await self.bot.tickets.validate_configuration(
                interaction.guild, settings
            )
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.response.send_modal(SaleModal(self.bot))
