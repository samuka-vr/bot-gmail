from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from app.utils.config_embeds import build_config_embed
from app.utils.permissions import require_admin
from app.views.configuration import BotConfigView

if TYPE_CHECKING:
    from app.bot import SKStoreBot


class AdministrationCog(commands.Cog):
    def __init__(self, bot: "SKStoreBot") -> None:
        self.bot = bot

    @app_commands.command(
        name="botconfig", description="Configura o sistema da SK Store."
    )
    @app_commands.guild_only()
    async def botconfig(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(
            interaction.user, discord.Member
        ):
            return
        try:
            settings = await self.bot.database.get_settings(interaction.guild.id)
            require_admin(interaction.user, settings)
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.response.send_message(
            embed=build_config_embed(settings),
            view=BotConfigView(self.bot, interaction.user.id),
            ephemeral=True,
        )
