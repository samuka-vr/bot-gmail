from __future__ import annotations

import discord


def allowed_user_mentions(user_id: int) -> discord.AllowedMentions:
    """Allow exactly one user mention without enabling roles or everyone."""
    return discord.AllowedMentions(
        everyone=False,
        roles=False,
        users=[discord.Object(id=user_id)],
        replied_user=False,
    )
