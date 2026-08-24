from __future__ import annotations

import discord


async def send_ephemeral(
    interaction: discord.Interaction,
    content: str,
    *,
    view: discord.ui.View | None = None,
) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=True, view=view)
    else:
        await interaction.response.send_message(
            content, ephemeral=True, view=view
        )


async def send_user_error(
    interaction: discord.Interaction, message: str
) -> None:
    await send_ephemeral(interaction, message)
