from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from app.constants import DEFAULT_SETTINGS
from app.models import GuildSettings

if TYPE_CHECKING:
    from app.bot import SKStoreBot


class ConfigurationService:
    def __init__(self, bot: "SKStoreBot") -> None:
        self.bot = bot

    async def update(
        self,
        *,
        guild_id: int,
        values: Mapping[str, str],
        actor_id: int,
        interaction_id: int,
    ) -> GuildSettings:
        unknown = set(values) - set(DEFAULT_SETTINGS)
        if unknown:
            raise ValueError(f"Configuração desconhecida: {sorted(unknown)!r}")
        changed = await self.bot.database.set_settings_with_event(
            guild_id, values, actor_id, interaction_id
        )
        if changed:
            await self.bot.logs.flush_guild_events(guild_id)
        return await self.bot.database.get_settings(guild_id)
