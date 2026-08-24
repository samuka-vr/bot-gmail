from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from app.utils.embeds import build_profile_embed

if TYPE_CHECKING:
    from app.bot import SKStoreBot


class CustomerCog(commands.Cog):
    def __init__(self, bot: "SKStoreBot") -> None:
        self.bot = bot

    @app_commands.command(
        name="perfil", description="Mostra seu histórico de vendas."
    )
    @app_commands.guild_only()
    async def profile(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            profile = await self.bot.database.get_profile(
                interaction.guild.id, interaction.user.id
            )
            settings = await self.bot.database.get_settings(interaction.guild.id)
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        embed = build_profile_embed(profile, interaction.user.id, settings)
        await interaction.followup.send(embed=embed, ephemeral=True)
