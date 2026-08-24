from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from app.constants import STATUS_LABELS, SaleStatus
from app.utils.money import format_brl
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
        lines: list[str] = []
        for row in rows:
            status = SaleStatus(str(row["status"]))
            count = int(row["account_count"])
            total = count * int(row["unit_price_cents"])
            line = (
                f"#{int(row['id']):04d} · {STATUS_LABELS[status]} · "
                f"<@{int(row['customer_id'])}> · {count} conta(s) · "
                f"{format_brl(total)}"
            )
            if row["channel_id"]:
                line += f" · <#{int(row['channel_id'])}>"
            lines.append(line)
        embed = discord.Embed(
            title="Fila de vendas",
            description="\n".join(lines) if lines else "Nenhuma venda na fila.",
            colour=settings.embed_color,
        )
        embed.set_footer(text=f"Exibindo {len(lines)} venda(s)")
        await interaction.followup.send(embed=embed, ephemeral=True)
