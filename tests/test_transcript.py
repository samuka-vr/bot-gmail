from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.constants import SaleStatus
from app.models import Sale, SaleAccount
from app.services.transcripts import TranscriptService


class FakeDatabase:
    async def get_accounts(self, sale_id: int):
        now = datetime.now(UTC)
        return [
            SaleAccount(
                id=1,
                sale_id=sale_id,
                email="conta@gmail.com",
                canonical_email="conta@gmail.com",
                created_at=now,
                removed_at=None,
            )
        ]


class FakeChannel:
    name = "gmail-0042"

    def __init__(self, messages: list[object]) -> None:
        self.messages = messages

    async def history(self, *, limit=None, oldest_first=False):
        for message in self.messages:
            yield message


class FakeAuthor:
    id = 7

    def __str__(self) -> str:
        return "Cliente"


class TranscriptTests(unittest.IsolatedAsyncioTestCase):
    async def test_html_is_self_contained_incremental_and_escaped(self) -> None:
        now = datetime.now(UTC)
        sale = Sale(
            id=42,
            guild_id=1,
            customer_id=100,
            channel_id=200,
            workflow_message_id=300,
            cart_notice_message_id=None,
            cart_notice_sent_at=None,
            status=SaleStatus.FINALIZED,
            responsible_staff_id=500,
            payment_confirmed_by_id=500,
            completed_by_id=500,
            unit_price_cents=200,
            pix_key="cliente@pix.com",
            pix_holder="Cliente <Teste>",
            verification_code="SK-48321",
            ticket_name="gmail-0042",
            close_reason=None,
            closed_by_id=None,
            created_at=now,
            claimed_at=now,
            payment_stage_at=now,
            paid_at=now,
            completed_at=now,
            closed_at=None,
            cart_notice_delete_at=None,
            ticket_delete_at=None,
            transcript_message_id=None,
            transcript_sent_at=None,
            ticket_deleted_at=None,
            terminal_processed_at=None,
            updated_at=now,
        )
        message = SimpleNamespace(
            author=FakeAuthor(),
            created_at=now,
            content="<script>alert('x')</script>",
            attachments=[],
            embeds=[],
        )
        bot = SimpleNamespace(database=FakeDatabase())
        service = TranscriptService(bot)
        path = await service._write_html(
            FakeChannel([message]),
            sale,
            SimpleNamespace(embed_color=0x123456),
        )
        try:
            content = path.read_text(encoding="utf-8")
        finally:
            path.unlink(missing_ok=True)
        self.assertIn("<!doctype html>", content.lower())
        self.assertIn("<style>", content)
        self.assertIn("--accent:#123456", content)
        self.assertIn("class='status'", content)
        self.assertIn("Venda #0042", content)
        self.assertIn("conta@gmail.com", content)
        self.assertIn("Pagamento aberto", content)
        self.assertIn("Finalizada", content)
        self.assertIn("&lt;script&gt;", content)
        self.assertNotIn("<script>alert", content)

    async def test_temporary_file_is_removed_when_generation_fails(self) -> None:
        descriptor, raw_path = tempfile.mkstemp(suffix=".html")
        path = Path(raw_path)

        class BrokenDatabase:
            async def get_accounts(self, sale_id: int):
                raise RuntimeError("database unavailable")

        bot = SimpleNamespace(database=BrokenDatabase())
        service = TranscriptService(bot)
        with patch(
            "app.services.transcripts.tempfile.mkstemp",
            return_value=(descriptor, raw_path),
        ):
            with self.assertRaises(RuntimeError):
                await service._write_html(SimpleNamespace(), SimpleNamespace(id=9))
        self.assertFalse(path.exists())
