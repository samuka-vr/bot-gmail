from __future__ import annotations

import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.constants import EventType, SaleStatus
from app.services.logs import LogService


class LogEmbedTests(unittest.IsolatedAsyncioTestCase):
    async def test_sale_log_is_compact_and_does_not_list_accounts(self) -> None:
        bot = SimpleNamespace(
            database=SimpleNamespace(
                get_accounts=AsyncMock(return_value=[object(), object(), object()])
            )
        )
        event = {
            "event_type": EventType.PAYMENT_CONFIRMED.value,
            "created_at": datetime.now(UTC).isoformat(),
            "actor_id": 500,
            "payload_json": "{}",
        }
        sale = SimpleNamespace(
            id=42,
            customer_id=100,
            channel_id=200,
            status=SaleStatus.PAID,
            unit_price_cents=200,
            close_reason=None,
        )

        embed = await LogService(bot)._build_embed(event, sale, 0x1F2937)

        self.assertEqual(embed.title, "Venda #0042 · Pagamento confirmado")
        self.assertIn("**Cliente:** <@100>", embed.description)
        self.assertIn("**Resumo:** 3 contas · R$ 6,00", embed.description)
        self.assertLessEqual(len(embed.fields), 1)
        self.assertNotIn("gmail.com", embed.description)
