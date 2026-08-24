from __future__ import annotations

import discord


class TicketLinkView(discord.ui.View):
    """Small navigation-only view used in ephemeral messages and DMs."""

    def __init__(self, ticket_url: str) -> None:
        super().__init__(timeout=300)
        self.add_item(
            discord.ui.Button(
                label="Abrir atendimento",
                style=discord.ButtonStyle.link,
                url=ticket_url,
            )
        )
