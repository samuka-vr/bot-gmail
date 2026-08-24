from __future__ import annotations

import asyncio
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.constants import SaleStatus
from app.database import Database
from app.exceptions import (
    DuplicateOperation,
    InvalidTransition,
    PermissionDenied,
    ValidationError,
)
from app.services.sales import SaleService
from app.services.locks import KeyedLocks
from app.services.panels import PanelService
from app.utils.validation import parse_gmail_lines


class BusinessFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp_dir.name) / "skstore.db")
        await self.db.start()
        self.sales = SaleService(self.db)
        self.settings = await self.db.get_settings(1)
        self.interaction_id = 10_000

    async def asyncTearDown(self) -> None:
        await self.db.close()
        self.temp_dir.cleanup()

    def next_id(self) -> int:
        self.interaction_id += 1
        return self.interaction_id

    async def create(
        self,
        email_text: str,
        *,
        customer_id: int = 100,
        interaction_id: int | None = None,
    ):
        return await self.sales.create_sale(
            guild_id=1,
            customer_id=customer_id,
            emails=parse_gmail_lines(email_text),
            pix_key="cliente@pix.com",
            pix_holder="Cliente Teste",
            interaction_id=interaction_id or self.next_id(),
            settings=self.settings,
        )

    async def test_migrations_and_writable_check(self) -> None:
        row = await self.db.fetchone(
            "SELECT COUNT(*) AS total FROM schema_migrations"
        )
        self.assertEqual(row["total"], 7)
        self.assertTrue(await self.db.writable_check())
        settings = await self.db.get_settings(1)
        self.assertTrue(settings.auto_close_enabled)
        self.assertEqual(settings.auto_close_delay, 60)
        foreign_key_errors = await self.db.fetchall("PRAGMA foreign_key_check")
        self.assertEqual(foreign_key_errors, [])
        columns = {
            str(row["name"])
            for row in await self.db.fetchall("PRAGMA table_info(sales)")
        }
        self.assertTrue(
            {
                "status",
                "unit_price_cents",
                "payment_confirmed_by_id",
                "completed_by_id",
                "cart_notice_sent_at",
                "transcript_sent_at",
                "terminal_processed_at",
            }.issubset(columns)
        )

    async def test_auto_close_migration_updates_legacy_defaults(self) -> None:
        await self.db.set_settings(
            1,
            {
                "auto_close_enabled": "false",
                "auto_close_delay": "3600",
            },
            actor_id=999,
        )
        await self.db.connection.execute(
            "DELETE FROM schema_migrations WHERE version = 7"
        )
        await self.db.connection.commit()
        await self.db.close()
        await self.db.start()

        settings = await self.db.get_settings(1)
        self.assertTrue(settings.auto_close_enabled)
        self.assertEqual(settings.auto_close_delay, 60)

    async def test_create_sale_is_idempotent(self) -> None:
        interaction_id = self.next_id()
        sale, created = await self.create(
            "um@gmail.com\ndois@gmail.com", interaction_id=interaction_id
        )
        repeated, repeated_created = await self.create(
            "um@gmail.com\ndois@gmail.com", interaction_id=interaction_id
        )
        self.assertTrue(created)
        self.assertFalse(repeated_created)
        self.assertEqual(sale.id, repeated.id)
        self.assertEqual(sale.status, SaleStatus.WAITING)
        self.assertRegex(sale.verification_code, r"^SK-\d{5}$")
        self.assertEqual(len(await self.db.get_accounts(sale.id)), 2)

    async def test_duplicate_canonical_gmail_is_blocked_across_active_sales(self) -> None:
        await self.create("nome.teste@gmail.com", customer_id=100)
        with self.assertRaises(ValidationError):
            await self.create("nometeste@googlemail.com", customer_id=200)

    async def test_duplicate_check_is_isolated_by_guild(self) -> None:
        first, _ = await self.create("loja@gmail.com", customer_id=100)
        settings = await self.db.get_settings(2)
        second, created = await self.sales.create_sale(
            guild_id=2,
            customer_id=100,
            emails=parse_gmail_lines("lo.ja@gmail.com"),
            pix_key="cliente@pix.com",
            pix_holder="Cliente Teste",
            interaction_id=self.next_id(),
            settings=settings,
        )
        self.assertTrue(created)
        self.assertNotEqual(first.id, second.id)

    async def test_active_sale_limit_is_enforced(self) -> None:
        await self.create("primeiro@gmail.com", customer_id=100)
        with self.assertRaises(ValidationError):
            await self.create("segundo@gmail.com", customer_id=100)

    async def test_ticket_attachment_blocks_duplicates_and_allows_recovery(self) -> None:
        sale, _ = await self.create("ticket@gmail.com")
        attached = await self.sales.attach_channel(
            sale.id, 500, "gmail-0001"
        )
        self.assertEqual(attached.channel_id, 500)
        repeated = await self.sales.attach_channel(
            sale.id, 500, "gmail-0001"
        )
        self.assertEqual(repeated.channel_id, 500)
        with self.assertRaises(DuplicateOperation):
            await self.sales.attach_channel(sale.id, 501, "gmail-0001")
        recovered = await self.sales.attach_channel(
            sale.id,
            501,
            "gmail-0001",
            replace_existing=True,
        )
        self.assertEqual(recovered.channel_id, 501)

    async def test_workflow_message_attachment_is_idempotent(self) -> None:
        sale, _ = await self.create("mensagem@gmail.com")
        attached = await self.sales.attach_workflow_message(sale.id, 700)
        self.assertEqual(attached.workflow_message_id, 700)
        repeated = await self.sales.attach_workflow_message(sale.id, 700)
        self.assertEqual(repeated.workflow_message_id, 700)
        with self.assertRaises(DuplicateOperation):
            await self.sales.attach_workflow_message(sale.id, 701)
        recovered = await self.sales.attach_workflow_message(
            sale.id,
            701,
            stale_message_id=700,
        )
        self.assertEqual(recovered.workflow_message_id, 701)

    async def test_cart_add_remove_edit_and_minimum(self) -> None:
        sale, _ = await self.create("um@gmail.com\ndois@gmail.com")
        sale, changed = await self.sales.add_accounts(
            sale_id=sale.id,
            customer_id=100,
            emails=parse_gmail_lines("tres@gmail.com"),
            interaction_id=self.next_id(),
            settings=self.settings,
        )
        self.assertTrue(changed)
        self.assertEqual(len(await self.db.get_accounts(sale.id)), 3)
        with self.assertRaises(ValidationError):
            await self.sales.add_accounts(
                sale_id=sale.id,
                customer_id=100,
                emails=parse_gmail_lines("t.res@gmail.com"),
                interaction_id=self.next_id(),
                settings=self.settings,
            )

        accounts = await self.db.get_accounts(sale.id)
        await self.sales.remove_account(
            sale_id=sale.id,
            account_id=accounts[0].id,
            customer_id=100,
            interaction_id=self.next_id(),
            settings=self.settings,
        )
        accounts = await self.db.get_accounts(sale.id)
        await self.sales.remove_account(
            sale_id=sale.id,
            account_id=accounts[0].id,
            customer_id=100,
            interaction_id=self.next_id(),
            settings=self.settings,
        )
        accounts = await self.db.get_accounts(sale.id)
        with self.assertRaises(ValidationError):
            await self.sales.remove_account(
                sale_id=sale.id,
                account_id=accounts[0].id,
                customer_id=100,
                interaction_id=self.next_id(),
                settings=self.settings,
            )

        updated, changed = await self.sales.edit_pix(
            sale_id=sale.id,
            customer_id=100,
            pix_key="11999999999",
            pix_holder="Novo Titular",
            interaction_id=self.next_id(),
        )
        self.assertTrue(changed)
        self.assertEqual(updated.pix_key, "11999999999")
        self.assertEqual(updated.pix_holder, "Novo Titular")

    async def test_customer_cancellation_locks_cart(self) -> None:
        sale, _ = await self.create("cancelar@gmail.com")
        interaction_id = self.next_id()
        closed, changed = await self.sales.cancel_by_customer(
            sale_id=sale.id,
            customer_id=100,
            interaction_id=interaction_id,
            settings=self.settings,
        )
        self.assertTrue(changed)
        self.assertEqual(closed.status, SaleStatus.CLOSED)
        repeated, repeated_changed = await self.sales.cancel_by_customer(
            sale_id=sale.id,
            customer_id=100,
            interaction_id=interaction_id,
            settings=self.settings,
        )
        self.assertFalse(repeated_changed)
        self.assertEqual(repeated.status, SaleStatus.CLOSED)
        with self.assertRaises(InvalidTransition):
            await self.sales.edit_pix(
                sale_id=sale.id,
                customer_id=100,
                pix_key="nova-chave",
                pix_holder="Titular",
                interaction_id=self.next_id(),
            )

    async def test_customer_cannot_change_another_customers_cart(self) -> None:
        sale, _ = await self.create("privado@gmail.com", customer_id=100)
        with self.assertRaises(PermissionDenied):
            await self.sales.edit_pix(
                sale_id=sale.id,
                customer_id=200,
                pix_key="outra-chave",
                pix_holder="Outro Titular",
                interaction_id=self.next_id(),
            )
        with self.assertRaises(PermissionDenied):
            await self.sales.add_accounts(
                sale_id=sale.id,
                customer_id=200,
                emails=parse_gmail_lines("outra@gmail.com"),
                interaction_id=self.next_id(),
                settings=self.settings,
            )

    async def test_claim_conflict_and_staff_ownership(self) -> None:
        sale, _ = await self.create("claim@gmail.com")
        claimed, changed = await self.sales.claim(
            sale_id=sale.id,
            staff_id=10,
            interaction_id=self.next_id(),
        )
        self.assertTrue(changed)
        self.assertEqual(claimed.status, SaleStatus.ANALYSIS)
        self.assertEqual(claimed.responsible_staff_id, 10)
        with self.assertRaises(InvalidTransition):
            await self.sales.claim(
                sale_id=sale.id,
                staff_id=11,
                interaction_id=self.next_id(),
            )
        with self.assertRaises(PermissionDenied):
            await self.sales.continue_to_payment(
                sale_id=sale.id,
                staff_id=11,
                is_admin=False,
                interaction_id=self.next_id(),
            )

    async def test_complete_staff_state_machine_with_admin_override(self) -> None:
        sale, _ = await self.create("fluxo@gmail.com")
        sale, _ = await self.sales.claim(
            sale_id=sale.id,
            staff_id=10,
            interaction_id=self.next_id(),
        )
        sale, changed = await self.sales.continue_to_payment(
            sale_id=sale.id,
            staff_id=99,
            is_admin=True,
            interaction_id=self.next_id(),
        )
        self.assertTrue(changed)
        self.assertEqual(sale.status, SaleStatus.PAYMENT)
        self.assertIsNotNone(sale.payment_stage_at)
        sale, _ = await self.sales.back_to_analysis(
            sale_id=sale.id,
            staff_id=10,
            is_admin=False,
            interaction_id=self.next_id(),
        )
        self.assertEqual(sale.status, SaleStatus.ANALYSIS)
        sale, _ = await self.sales.continue_to_payment(
            sale_id=sale.id,
            staff_id=10,
            is_admin=False,
            interaction_id=self.next_id(),
        )
        sale, _ = await self.sales.confirm_payment(
            sale_id=sale.id,
            staff_id=10,
            is_admin=False,
            interaction_id=self.next_id(),
        )
        self.assertEqual(sale.status, SaleStatus.PAID)
        self.assertEqual(sale.payment_confirmed_by_id, 10)
        with self.assertRaises(InvalidTransition):
            await self.sales.close_by_staff(
                sale_id=sale.id,
                staff_id=10,
                is_admin=False,
                reason="Não deve encerrar.",
                interaction_id=self.next_id(),
            )
        sale, _ = await self.sales.finalize(
            sale_id=sale.id,
            staff_id=10,
            is_admin=False,
            interaction_id=self.next_id(),
        )
        self.assertEqual(sale.status, SaleStatus.FINALIZED)
        self.assertEqual(sale.completed_by_id, 10)
        self.assertIsNotNone(sale.completed_at)

    async def test_payment_locks_customer_and_invalid_transitions(self) -> None:
        sale, _ = await self.create("bloqueio@gmail.com")
        with self.assertRaises(InvalidTransition):
            await self.sales.confirm_payment(
                sale_id=sale.id,
                staff_id=10,
                is_admin=True,
                interaction_id=self.next_id(),
            )
        sale, _ = await self.sales.claim(
            sale_id=sale.id,
            staff_id=10,
            interaction_id=self.next_id(),
        )
        sale, _ = await self.sales.continue_to_payment(
            sale_id=sale.id,
            staff_id=10,
            is_admin=False,
            interaction_id=self.next_id(),
        )
        with self.assertRaises(InvalidTransition):
            await self.sales.edit_pix(
                sale_id=sale.id,
                customer_id=100,
                pix_key="outra-chave",
                pix_holder="Titular",
                interaction_id=self.next_id(),
            )
        with self.assertRaises(InvalidTransition):
            await self.sales.cancel_by_customer(
                sale_id=sale.id,
                customer_id=100,
                interaction_id=self.next_id(),
                settings=self.settings,
            )

    async def test_database_state_survives_restart(self) -> None:
        sale, _ = await self.create("reinicio@gmail.com")
        path = self.db.path
        await self.db.close()
        reopened = Database(path)
        await reopened.start()
        self.db = reopened
        self.sales = SaleService(reopened)
        persisted = await reopened.get_sale(sale.id)
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted.status, SaleStatus.WAITING)
        self.assertEqual(len(await reopened.get_accounts(sale.id)), 1)

    async def test_staff_can_close_waiting_sale_with_reason(self) -> None:
        sale, _ = await self.create("fechar@gmail.com")
        sale, changed = await self.sales.close_by_staff(
            sale_id=sale.id,
            staff_id=10,
            is_admin=False,
            reason="Conta não elegível.",
            interaction_id=self.next_id(),
        )
        self.assertTrue(changed)
        self.assertEqual(sale.status, SaleStatus.CLOSED)
        self.assertEqual(sale.closed_by_id, 10)
        self.assertEqual(sale.close_reason, "Conta não elegível.")

    async def test_ticket_creation_failure_is_terminal_and_recoverable(self) -> None:
        sale, _ = await self.create("falha@gmail.com")
        await self.sales.mark_creation_failure(sale.id, "Forbidden")
        failed = await self.db.get_sale(sale.id)
        self.assertEqual(failed.status, SaleStatus.CLOSED)
        self.assertIsNotNone(failed.terminal_processed_at)
        self.assertIsNone(failed.channel_id)

    async def test_profile_and_queue_aggregations(self) -> None:
        sale, _ = await self.create("perfil1@gmail.com\nperfil2@gmail.com")
        sale, _ = await self.sales.claim(
            sale_id=sale.id,
            staff_id=10,
            interaction_id=self.next_id(),
        )
        sale, _ = await self.sales.continue_to_payment(
            sale_id=sale.id,
            staff_id=10,
            is_admin=False,
            interaction_id=self.next_id(),
        )
        sale, _ = await self.sales.confirm_payment(
            sale_id=sale.id,
            staff_id=10,
            is_admin=False,
            interaction_id=self.next_id(),
        )
        await self.sales.finalize(
            sale_id=sale.id,
            staff_id=10,
            is_admin=False,
            interaction_id=self.next_id(),
        )
        second, _ = await self.create("perfil3@gmail.com")
        await self.sales.cancel_by_customer(
            sale_id=second.id,
            customer_id=100,
            interaction_id=self.next_id(),
            settings=self.settings,
        )
        profile = await self.db.get_profile(1, 100)
        self.assertEqual(profile["completed_sales"], 1)
        self.assertEqual(profile["closed_sales"], 1)
        self.assertEqual(profile["sold_accounts"], 2)
        self.assertEqual(profile["received_cents"], 400)

        waiting, _ = await self.create("fila@gmail.com", customer_id=200)
        rows = await self.db.get_queue_rows(1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(int(rows[0]["id"]), waiting.id)
        self.assertEqual(int(rows[0]["account_count"]), 1)

    async def test_configuration_update_is_idempotent(self) -> None:
        interaction_id = self.next_id()
        changed = await self.db.set_settings_with_event(
            1,
            {"unit_price_cents": "250"},
            999,
            interaction_id,
        )
        repeated = await self.db.set_settings_with_event(
            1,
            {"unit_price_cents": "999"},
            999,
            interaction_id,
        )
        self.assertTrue(changed)
        self.assertFalse(repeated)
        settings = await self.db.get_settings(1)
        self.assertEqual(settings.unit_price_cents, 250)
        pending = await self.db.get_pending_events(guild_id=1)
        self.assertEqual(
            [row["event_type"] for row in pending].count("CONFIG_CHANGED"), 1
        )

    async def test_maintenance_deadlines_are_persisted(self) -> None:
        sale, _ = await self.create("prazo@gmail.com")
        delete_at = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
        await self.db.set_ticket_delete_at(sale.id, delete_at)
        self.assertEqual(await self.db.get_next_maintenance_at(), delete_at)

    async def test_dm_only_cart_notice_is_persisted(self) -> None:
        sale, _ = await self.create("aviso@gmail.com")
        await self.sales.attach_cart_notice(sale.id, None, None)
        persisted = await self.db.get_sale(sale.id)
        self.assertIsNotNone(persisted.cart_notice_sent_at)
        self.assertIsNone(persisted.cart_notice_message_id)

    async def test_active_recovery_queries_are_paginated(self) -> None:
        first, _ = await self.create("lote1@gmail.com", customer_id=101)
        second, _ = await self.create("lote2@gmail.com", customer_id=102)
        third, _ = await self.create("lote3@gmail.com", customer_id=103)
        page_one = await self.db.get_active_sales(after_id=0, limit=2)
        page_two = await self.db.get_active_sales(
            after_id=page_one[-1].id, limit=2
        )
        self.assertEqual([sale.id for sale in page_one], [first.id, second.id])
        self.assertEqual([sale.id for sale in page_two], [third.id])

    async def test_terminal_recovery_respects_transcript_setting(self) -> None:
        sale, _ = await self.create("terminal@gmail.com")
        sale, _ = await self.sales.claim(
            sale_id=sale.id,
            staff_id=10,
            interaction_id=self.next_id(),
        )
        sale, _ = await self.sales.continue_to_payment(
            sale_id=sale.id,
            staff_id=10,
            is_admin=False,
            interaction_id=self.next_id(),
        )
        sale, _ = await self.sales.confirm_payment(
            sale_id=sale.id,
            staff_id=10,
            is_admin=False,
            interaction_id=self.next_id(),
        )
        sale, _ = await self.sales.finalize(
            sale_id=sale.id,
            staff_id=10,
            is_admin=False,
            interaction_id=self.next_id(),
        )
        await self.sales.attach_channel(sale.id, 800, "gmail-terminal")
        self.assertEqual(
            [item.id for item in await self.db.get_terminal_recovery_batch(after_id=0)],
            [sale.id],
        )
        await self.db.mark_terminal_processed(sale.id)
        self.assertEqual(
            [item.id for item in await self.db.get_terminal_recovery_batch(after_id=0)],
            [sale.id],
        )
        await self.db.set_settings(
            1, {"transcripts_enabled": "false"}, actor_id=999
        )
        self.assertEqual(
            await self.db.get_terminal_recovery_batch(after_id=0), []
        )


class PanelConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_panel_publication_is_serialized_per_guild(self) -> None:
        class ProbePanelService(PanelService):
            def __init__(self) -> None:
                self.locks = KeyedLocks()
                self.active = 0
                self.peak = 0

            async def _publish(self, guild, actor_id):
                self.active += 1
                self.peak = max(self.peak, self.active)
                await asyncio.sleep(0)
                self.active -= 1
                return actor_id, True

        class Guild:
            id = 123

        service = ProbePanelService()
        results = await asyncio.gather(
            service.publish(Guild(), 1),
            service.publish(Guild(), 2),
        )
        self.assertEqual(service.peak, 1)
        self.assertEqual(results, [(1, True), (2, True)])
