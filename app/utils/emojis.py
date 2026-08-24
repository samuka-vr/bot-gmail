from __future__ import annotations

import discord


def custom_emoji(emoji_id: int | None) -> discord.PartialEmoji | None:
    if not emoji_id:
        return None
    return discord.PartialEmoji(name="sk", id=emoji_id)
