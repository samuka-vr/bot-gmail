from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

from app.constants import DEFAULT_SETTINGS
from app.models import GuildSettings
from app.services.diagnostics import DiagnosticService


class TopRole:
    def __gt__(self, other: object) -> bool:
        return True


class DiagnosticTests(unittest.IsolatedAsyncioTestCase):
    async def test_complete_diagnostic_is_grouped_and_clear(self) -> None:
        permissions = SimpleNamespace(
            send_messages=True,
            embed_links=True,
            attach_files=True,
            manage_channels=True,
            manage_roles=True,
            read_message_history=True,
        )

        def text_channel(channel_id: int) -> discord.TextChannel:
            channel = discord.TextChannel()
            channel.id = channel_id
            channel.permissions_for = Mock(return_value=permissions)
            channel.fetch_message = AsyncMock(return_value=object())
            return channel

        panel = text_channel(1)
        logs = text_channel(3)
        transcripts = text_channel(4)
        category = discord.CategoryChannel()
        category.id = 2
        category.permissions_for = Mock(return_value=permissions)

        default_role = discord.Role()
        default_role.id = 9
        staff_role = discord.Role()
        staff_role.id = 10
        admin_role = discord.Role()
        admin_role.id = 11
        bot_member = SimpleNamespace(top_role=TopRole())
        channels = {1: panel, 2: category, 3: logs, 4: transcripts}
        roles = {10: staff_role, 11: admin_role}
        guild = SimpleNamespace(
            id=100,
            me=bot_member,
            default_role=default_role,
            get_channel=Mock(side_effect=channels.get),
            fetch_channel=AsyncMock(),
            get_role=Mock(side_effect=lambda role_id: roles.get(role_id)),
            get_emoji=Mock(return_value=None),
        )
        settings = GuildSettings.from_mapping(
            {
                **DEFAULT_SETTINGS,
                "panel_channel_id": "1",
                "panel_message_id": "99",
                "ticket_category_id": "2",
                "logs_channel_id": "3",
                "transcript_channel_id": "4",
                "staff_role_id": "10",
                "admin_role_id": "11",
            }
        )
        persistent = [SimpleNamespace(is_persistent=Mock(return_value=True))] * 5
        bot = SimpleNamespace(
            database=SimpleNamespace(
                get_settings=AsyncMock(return_value=settings),
                writable_check=AsyncMock(return_value=True),
            ),
            maintenance=SimpleNamespace(running=True),
            persistent_views_added=True,
            persistent_views=persistent,
            intents=SimpleNamespace(
                guilds=True,
                guild_messages=True,
                message_content=True,
            ),
            get_emoji=Mock(return_value=None),
            fetch_application_emojis=AsyncMock(return_value=[]),
        )

        embed = await DiagnosticService(bot).build(guild)

        self.assertEqual(
            [field.name for field in embed.fields],
            ["Configuração · 8/8", "Permissões · 6/6", "Sistema · 7/7"],
        )
        self.assertEqual(embed.footer.text, "21/21 verificações aprovadas")
        self.assertNotIn("FALHA", "\n".join(field.value for field in embed.fields))
