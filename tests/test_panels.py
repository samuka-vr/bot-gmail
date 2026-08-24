from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

from app.constants import DEFAULT_SETTINGS
from app.models import GuildSettings
from app.services.panels import PanelService


class PanelServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_custom_icon_falls_back_without_blocking_panel(self) -> None:
        settings = GuildSettings.from_mapping(
            {
                **DEFAULT_SETTINGS,
                "panel_channel_id": "10",
                "ticket_category_id": "20",
                "staff_role_id": "30",
                "admin_role_id": "40",
                "icon_sell_id": "123456789",
            }
        )
        message = SimpleNamespace(id=99)
        channel = discord.TextChannel()
        channel.id = 10
        channel.send = AsyncMock(
            side_effect=[discord.HTTPException(), message]
        )
        guild = SimpleNamespace(
            id=1,
            get_channel=Mock(return_value=channel),
            fetch_channel=AsyncMock(),
        )
        database = SimpleNamespace(
            get_settings=AsyncMock(return_value=settings),
            set_settings=AsyncMock(),
        )
        bot = SimpleNamespace(
            tickets=SimpleNamespace(validate_configuration=AsyncMock()),
        )

        result, created = await PanelService(bot, database).publish(guild, 500)

        self.assertIs(result, message)
        self.assertTrue(created)
        self.assertEqual(channel.send.await_count, 2)
        fallback_view = channel.send.await_args_list[1].kwargs["view"]
        self.assertIsNone(fallback_view.children[0].emoji)
        database.set_settings.assert_awaited_once()

