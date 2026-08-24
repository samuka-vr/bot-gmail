from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from app.constants import STATUS_LABELS, SaleStatus
from app.utils.money import format_brl

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
        embed = discord.Embed(
            title="Perfil de vendas",
            colour=settings.embed_color,
        )
        embed.add_field(
            name="Usuário", value=interaction.user.mention, inline=False
        )
        embed.add_field(
            name="Vendas concluídas",
            value=str(profile["completed_sales"]),
            inline=True,
        )
        embed.add_field(
            name="G-mails vendidos",
            value=str(profile["sold_accounts"]),
            inline=True,
        )
        embed.add_field(
            name="Total recebido",
            value=format_brl(profile["received_cents"]),
            inline=True,
        )
        embed.add_field(
            name="Vendas encerradas",
            value=str(profile["closed_sales"]),
            inline=True,
        )
        recent_lines: list[str] = []
        for row in profile["recent"]:
            status = SaleStatus(str(row["status"]))
            total = int(row["unit_price_cents"]) * int(row["account_count"])
            recent_lines.append(
                f"#{int(row['id']):04d} · {STATUS_LABELS[status]} · {format_brl(total)}"
            )
        embed.add_field(
            name="Últimas vendas",
            value="\n".join(recent_lines) if recent_lines else "Nenhuma venda.",
            inline=False,
        )
        embed.set_footer(text="SK Store")
        await interaction.followup.send(embed=embed, ephemeral=True)
