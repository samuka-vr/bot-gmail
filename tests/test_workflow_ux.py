from __future__ import annotations

import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import discord

from app.constants import DEFAULT_SETTINGS, SaleStatus
from app.models import GuildSettings
from app.services.workflow import WorkflowService


def sale_stub(**changes: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": 42,
        "guild_id": 1,
        "customer_id": 100,
        "channel_id": 200,
        "cart_notice_sent_at": None,
        "status": SaleStatus.ANALYSIS,
        "responsible_staff_id": 500,
        "unit_price_cents": 200,
        "verification_code": "SK-48321",
        "updated_at": datetime.now(UTC),
    }
    values.update(changes)
    return SimpleNamespace(**values)


class WorkflowCommunicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_dm_cart_notice_uses_branded_embed_and_ticket_link(self) -> None:
        settings = GuildSettings.from_mapping(
            {
                **DEFAULT_SETTINGS,
                "cart_message_target": "dm",
                "cart_message_text": (
                    "{user}, recebemos {quantidade} contas. Código: {codigo}."
                ),
            }
        )
        sale = sale_stub(status=SaleStatus.WAITING, responsible_staff_id=None)
        customer = SimpleNamespace(
            id=100,
            mention="<@100>",
            send=AsyncMock(),
        )
        channel = SimpleNamespace(id=200, mention="<#200>")
        bot = SimpleNamespace(
            database=SimpleNamespace(
                get_settings=AsyncMock(return_value=settings),
                get_accounts=AsyncMock(return_value=[object(), object()]),
            ),
            sales=SimpleNamespace(attach_cart_notice=AsyncMock()),
            maintenance=SimpleNamespace(notify=Mock()),
        )

        await WorkflowService(bot)._send_cart_notice(channel, customer, sale)

        customer.send.assert_awaited_once()
        sent = customer.send.await_args.kwargs
        self.assertEqual(sent["embed"].title, "SK Store · Venda #0042")
        self.assertIn("Você, recebemos 2 contas", sent["embed"].description)
        self.assertNotIn("<@100>", sent["embed"].description)
        self.assertEqual(
            sent["view"].children[0].url,
            "https://discord.com/channels/1/200",
        )
        bot.sales.attach_cart_notice.assert_awaited_once_with(42, None, None)

    async def test_staff_dm_has_no_fake_mention_and_records_delivery(self) -> None:
        settings = GuildSettings.from_mapping(DEFAULT_SETTINGS)
        sale = sale_stub()
        customer = SimpleNamespace(send=AsyncMock())
        staff = SimpleNamespace(
            id=500,
            display_name="Atendente",
            guild_permissions=SimpleNamespace(
                administrator=False,
                manage_guild=False,
            ),
            roles=[],
        )
        interaction = SimpleNamespace(id=900, user=staff)
        bot = SimpleNamespace(
            database=SimpleNamespace(get_sale=AsyncMock(return_value=sale)),
            sales=SimpleNamespace(
                locks=SimpleNamespace(),
                record_customer_notified=AsyncMock(return_value=(sale, True)),
            ),
            get_user=Mock(return_value=customer),
            fetch_user=AsyncMock(),
            logs=SimpleNamespace(flush_sale_events=AsyncMock()),
        )
        workflow = WorkflowService(bot)
        workflow._staff_context = AsyncMock(return_value=(staff, settings))

        class Lock:
            async def __aenter__(self) -> None:
                return None

            async def __aexit__(self, *args: object) -> None:
                return None

        bot.sales.locks.hold = Mock(return_value=Lock())

        delivered = await workflow.notify_customer(
            interaction, 42, "Sua venda precisa da sua atenção."
        )

        self.assertTrue(delivered)
        sent = customer.send.await_args.kwargs
        self.assertNotIn("<@", sent["embed"].description)
        self.assertEqual(sent["view"].children[0].label, "Abrir atendimento")
        bot.sales.record_customer_notified.assert_awaited_once()
        bot.logs.flush_sale_events.assert_awaited_once_with(42)

    async def test_closed_dm_is_reported_without_recording_delivery(self) -> None:
        settings = GuildSettings.from_mapping(DEFAULT_SETTINGS)
        sale = sale_stub()
        customer = SimpleNamespace(send=AsyncMock(side_effect=discord.Forbidden()))
        staff = SimpleNamespace(
            id=500,
            display_name="Atendente",
            guild_permissions=SimpleNamespace(
                administrator=False,
                manage_guild=False,
            ),
            roles=[],
        )
        interaction = SimpleNamespace(id=901, user=staff)
        bot = SimpleNamespace(
            database=SimpleNamespace(get_sale=AsyncMock(return_value=sale)),
            sales=SimpleNamespace(
                locks=SimpleNamespace(),
                record_customer_notified=AsyncMock(),
            ),
            get_user=Mock(return_value=customer),
            fetch_user=AsyncMock(),
            logs=SimpleNamespace(flush_sale_events=AsyncMock()),
        )
        workflow = WorkflowService(bot)
        workflow._staff_context = AsyncMock(return_value=(staff, settings))

        class Lock:
            async def __aenter__(self) -> None:
                return None

            async def __aexit__(self, *args: object) -> None:
                return None

        bot.sales.locks.hold = Mock(return_value=Lock())

        delivered = await workflow.notify_customer(
            interaction, 42, "Confira o atendimento."
        )

        self.assertFalse(delivered)
        bot.sales.record_customer_notified.assert_not_awaited()
