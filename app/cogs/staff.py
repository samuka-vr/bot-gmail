from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from app.utils.embeds import build_queue_embed
from app.utils.permissions import require_staff

if TYPE_CHECKING:
    from app.bot import SKStoreBot


class StaffCog(commands.Cog):
    def __init__(self, bot: "SKStoreBot") -> None:
        self.bot = bot

    @app_commands.command(
        name="fila", description="Mostra a fila atual de vendas."
    )
    @app_commands.guild_only()
    async def queue(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(
            interaction.user, discord.Member
        ):
            return
        try:
            settings = await self.bot.database.get_settings(interaction.guild.id)
            require_staff(interaction.user, settings)
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            rows = await self.bot.database.get_queue_rows(interaction.guild.id)
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        embed = build_queue_embed(rows, settings)
        await interaction.followup.send(embed=embed, ephemeral=True)
