from __future__ import annotations

import json
import secrets
from collections.abc import Sequence

import aiosqlite

from app.constants import ACTIVE_STATUSES, EventType, SaleStatus
from app.database import Database, utc_now_iso
from app.exceptions import (
    DuplicateOperation,
    InvalidTransition,
    PermissionDenied,
    ValidationError,
)
from app.models import GuildSettings, Sale
from app.services.locks import KeyedLocks
from app.utils.text import safe_channel_name
from app.utils.validation import ParsedEmail


class SaleService:
    def __init__(self, database: Database) -> None:
        self.db = database
        self.locks = KeyedLocks()

    @staticmethod
    def _active_placeholders() -> str:
        return ",".join("?" for _ in ACTIVE_STATUSES)

    async def _find_duplicate_accounts(
        self,
        connection: aiosqlite.Connection,
        guild_id: int,
        canonical_emails: Sequence[str],
    ) -> list[str]:
        if not canonical_emails:
            return []
        email_marks = ",".join("?" for _ in canonical_emails)
        status_marks = self._active_placeholders()
        parameters: list[object] = [
            guild_id,
            *canonical_emails,
            *(status.value for status in ACTIVE_STATUSES),
        ]
        cursor = await connection.execute(
            f"""
            SELECT DISTINCT a.canonical_email
            FROM sale_accounts a
            JOIN sales s ON s.id = a.sale_id
            WHERE s.guild_id = ?
              AND a.removed_at IS NULL
              AND a.canonical_email IN ({email_marks})
              AND s.status IN ({status_marks})
            """,
            parameters,
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [str(row["canonical_email"]) for row in rows]

    async def _new_verification_code(
        self, connection: aiosqlite.Connection, guild_id: int
    ) -> str:
        for _ in range(30):
            code = f"SK-{secrets.randbelow(90_000) + 10_000}"
            cursor = await connection.execute(
                "SELECT 1 FROM sales WHERE guild_id = ? AND verification_code = ?",
                (guild_id, code),
            )
            exists = await cursor.fetchone()
            await cursor.close()
            if not exists:
                return code
        raise RuntimeError("Não foi possível gerar um código de verificação.")

    async def create_sale(
        self,
        *,
        guild_id: int,
        customer_id: int,
        emails: list[ParsedEmail],
        pix_key: str,
        pix_holder: str,
        interaction_id: int,
        settings: GuildSettings,
    ) -> tuple[Sale, bool]:
        quantity = len(emails)
        if quantity < settings.min_accounts:
            raise ValidationError(
                f"Envie pelo menos {settings.min_accounts} conta(s)."
            )
        if quantity > settings.max_accounts:
            raise ValidationError(
                f"Envie no máximo {settings.max_accounts} conta(s)."
            )

        lock_key = ("create", guild_id, customer_id)
        async with self.locks.hold(lock_key):
            existing = await self.db.get_sale_by_creation_interaction(interaction_id)
            if existing:
                return existing, False

            now = utc_now_iso()
            async with self.db.transaction() as connection:
                cursor = await connection.execute(
                    "SELECT * FROM sales WHERE create_interaction_id = ?",
                    (interaction_id,),
                )
                existing_row = await cursor.fetchone()
                await cursor.close()
                if existing_row:
                    return Sale.from_row(existing_row), False

                status_marks = self._active_placeholders()
                cursor = await connection.execute(
                    f"""
                    SELECT COUNT(*) AS total FROM sales
                    WHERE guild_id = ? AND customer_id = ?
                      AND status IN ({status_marks})
                    """,
                    (
                        guild_id,
                        customer_id,
                        *(status.value for status in ACTIVE_STATUSES),
                    ),
                )
                active_count = int((await cursor.fetchone())["total"])
                await cursor.close()
                if active_count >= settings.max_active_sales:
                    raise ValidationError(
                        "Você já atingiu o limite de vendas abertas."
                    )

                duplicate_emails = await self._find_duplicate_accounts(
                    connection,
                    guild_id,
                    [item.canonical for item in emails],
                )
                if duplicate_emails:
                    raise ValidationError(
                        "Um ou mais G-mails já estão em outra venda ativa."
                    )

                await connection.execute(
                    """
                    INSERT INTO users(guild_id, user_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(guild_id, user_id) DO UPDATE SET
                        updated_at = excluded.updated_at
                    """,
                    (guild_id, customer_id, now, now),
                )
                verification_code = await self._new_verification_code(
                    connection, guild_id
                )
                cursor = await connection.execute(
                    """
                    INSERT INTO sales(
                        guild_id, customer_id, status, unit_price_cents,
                        pix_key, pix_holder, verification_code,
                        create_interaction_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        customer_id,
                        SaleStatus.WAITING.value,
                        settings.unit_price_cents,
                        pix_key,
                        pix_holder,
                        verification_code,
                        interaction_id,
                        now,
                        now,
                    ),
                )
                sale_id = int(cursor.lastrowid or 0)
                await cursor.close()
                ticket_name = safe_channel_name(settings.ticket_prefix, sale_id)
                await connection.execute(
                    "UPDATE sales SET ticket_name = ? WHERE id = ?",
                    (ticket_name, sale_id),
                )
                await connection.executemany(
                    """
                    INSERT INTO sale_accounts(
                        sale_id, email, canonical_email, created_at
                    ) VALUES (?, ?, ?, ?)
                    """,
                    [
                        (sale_id, item.display, item.canonical, now)
                        for item in emails
                    ],
                )
                await connection.execute(
                    """
                    INSERT INTO events(
                        guild_id, sale_id, event_type, actor_id,
                        payload_json, interaction_id, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        guild_id,
                        sale_id,
                        EventType.SALE_CREATED.value,
                        customer_id,
                        json.dumps({"quantity": quantity}),
                        interaction_id,
                        now,
                    ),
                )
                cursor = await connection.execute(
                    "SELECT * FROM sales WHERE id = ?", (sale_id,)
                )
                row = await cursor.fetchone()
                await cursor.close()
                return Sale.from_row(row), True

    async def attach_channel(
        self,
        sale_id: int,
        channel_id: int,
        ticket_name: str,
        *,
        replace_existing: bool = False,
    ) -> Sale:
        now = utc_now_iso()
        async with self.db.transaction() as connection:
            if replace_existing:
                cursor = await connection.execute(
                    """
                    UPDATE sales
                    SET channel_id = ?, ticket_name = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (channel_id, ticket_name, now, sale_id),
                )
            else:
                cursor = await connection.execute(
                    """
                    UPDATE sales
                    SET channel_id = ?, ticket_name = ?, updated_at = ?
                    WHERE id = ? AND (channel_id IS NULL OR channel_id = ?)
                    """,
                    (channel_id, ticket_name, now, sale_id, channel_id),
                )
            if cursor.rowcount != 1:
                await cursor.close()
                raise DuplicateOperation("Esta venda já possui outro ticket.")
            await cursor.close()
            cursor = await connection.execute(
                "SELECT * FROM sales WHERE id = ?", (sale_id,)
            )
            row = await cursor.fetchone()
            await cursor.close()
        return Sale.from_row(row)

    async def attach_workflow_message(
        self,
        sale_id: int,
        message_id: int,
        *,
        stale_message_id: int | None = None,
    ) -> Sale:
        now = utc_now_iso()
        async with self.db.transaction() as connection:
            if stale_message_id is None:
                cursor = await connection.execute(
                    """
                    UPDATE sales
                    SET workflow_message_id = ?, updated_at = ?
                    WHERE id = ? AND (
                        workflow_message_id IS NULL
                        OR workflow_message_id = ?
                    )
                    """,
                    (message_id, now, sale_id, message_id),
                )
            else:
                cursor = await connection.execute(
                    """
                    UPDATE sales
                    SET workflow_message_id = ?, updated_at = ?
                    WHERE id = ? AND workflow_message_id IN (?, ?)
                    """,
                    (
                        message_id,
                        now,
                        sale_id,
                        stale_message_id,
                        message_id,
                    ),
                )
            if cursor.rowcount != 1:
                await cursor.close()
                raise DuplicateOperation(
                    "Esta venda já possui outra mensagem principal."
                )
            await cursor.close()
        sale = await self.db.get_sale(sale_id)
        if not sale:
            raise RuntimeError("Venda não encontrada após salvar a mensagem.")
        return sale

    async def attach_cart_notice(
        self,
        sale_id: int,
        message_id: int | None,
        delete_at: str | None,
    ) -> None:
        now = utc_now_iso()
        async with self.db.transaction() as connection:
            await connection.execute(
                """
                UPDATE sales
                SET cart_notice_message_id = ?, cart_notice_sent_at = ?,
                    cart_notice_delete_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (message_id, now, delete_at, now, sale_id),
            )

    async def mark_creation_failure(self, sale_id: int, reason: str) -> None:
        now = utc_now_iso()
        async with self.db.transaction() as connection:
            cursor = await connection.execute(
                """
                UPDATE sales
                SET status = ?, close_reason = ?, closed_at = ?, updated_at = ?,
                    terminal_processed_at = ?
                WHERE id = ? AND status = ? AND channel_id IS NULL
                """,
                (
                    SaleStatus.CLOSED.value,
                    "Falha ao criar o ticket.",
                    now,
                    now,
                    now,
                    sale_id,
                    SaleStatus.WAITING.value,
                ),
            )
            changed = cursor.rowcount == 1
            await cursor.close()
            if changed:
                await connection.execute(
                    """
                    INSERT INTO events(
                        guild_id, sale_id, event_type, payload_json, created_at
                    )
                    SELECT guild_id, id, ?, ?, ? FROM sales WHERE id = ?
                    """,
                    (
                        EventType.TECHNICAL_FAILURE.value,
                        json.dumps({"operation": "ticket_create", "error": reason[:120]}),
                        now,
                        sale_id,
                    ),
                )

    async def _interaction_was_processed(
        self, connection: aiosqlite.Connection, interaction_id: int
    ) -> bool:
        cursor = await connection.execute(
            "SELECT 1 FROM events WHERE interaction_id = ?", (interaction_id,)
        )
        row = await cursor.fetchone()
        await cursor.close()
        return row is not None

    async def add_accounts(
        self,
        *,
        sale_id: int,
        customer_id: int,
        emails: list[ParsedEmail],
        interaction_id: int,
        settings: GuildSettings,
    ) -> tuple[Sale, bool]:
        now = utc_now_iso()
        async with self.db.transaction() as connection:
            if await self._interaction_was_processed(connection, interaction_id):
                cursor = await connection.execute(
                    "SELECT * FROM sales WHERE id = ?", (sale_id,)
                )
                row = await cursor.fetchone()
                await cursor.close()
                return Sale.from_row(row), False

            cursor = await connection.execute(
                "SELECT * FROM sales WHERE id = ?", (sale_id,)
            )
            row = await cursor.fetchone()
            await cursor.close()
            if not row:
                raise ValidationError("Venda não encontrada.")
            sale = Sale.from_row(row)
            if sale.customer_id != customer_id:
                raise PermissionDenied("Este carrinho não pertence a você.")
            if sale.status not in {SaleStatus.WAITING, SaleStatus.ANALYSIS}:
                raise InvalidTransition("O carrinho já está bloqueado.")

            cursor = await connection.execute(
                """
                SELECT COUNT(*) AS total FROM sale_accounts
                WHERE sale_id = ? AND removed_at IS NULL
                """,
                (sale_id,),
            )
            current_count = int((await cursor.fetchone())["total"])
            await cursor.close()
            if current_count + len(emails) > settings.max_accounts:
                available = max(settings.max_accounts - current_count, 0)
                raise ValidationError(
                    f"Você pode adicionar no máximo {available} conta(s)."
                )

            duplicates = await self._find_duplicate_accounts(
                connection,
                sale.guild_id,
                [item.canonical for item in emails],
            )
            if duplicates:
                raise ValidationError(
                    "Um ou mais G-mails já estão em uma venda ativa."
                )
            await connection.executemany(
                """
                INSERT INTO sale_accounts(
                    sale_id, email, canonical_email, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (sale_id, item.display, item.canonical, now)
                    for item in emails
                ],
            )
            await connection.execute(
                """
                INSERT INTO events(
                    guild_id, sale_id, event_type, actor_id,
                    payload_json, interaction_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sale.guild_id,
                    sale_id,
                    EventType.ACCOUNT_ADDED.value,
                    customer_id,
                    json.dumps({"quantity": len(emails)}),
                    interaction_id,
                    now,
                ),
            )
            await connection.execute(
                "UPDATE sales SET updated_at = ? WHERE id = ?",
                (now, sale_id),
            )
            cursor = await connection.execute(
                "SELECT * FROM sales WHERE id = ?", (sale_id,)
            )
            row = await cursor.fetchone()
            await cursor.close()
            return Sale.from_row(row), True

    async def remove_account(
        self,
        *,
        sale_id: int,
        account_id: int,
        customer_id: int,
        interaction_id: int,
        settings: GuildSettings,
    ) -> tuple[Sale, bool]:
        now = utc_now_iso()
        async with self.db.transaction() as connection:
            if await self._interaction_was_processed(connection, interaction_id):
                cursor = await connection.execute(
                    "SELECT * FROM sales WHERE id = ?", (sale_id,)
                )
                row = await cursor.fetchone()
                await cursor.close()
                return Sale.from_row(row), False
            cursor = await connection.execute(
                "SELECT * FROM sales WHERE id = ?", (sale_id,)
            )
            row = await cursor.fetchone()
            await cursor.close()
            if not row:
                raise ValidationError("Venda não encontrada.")
            sale = Sale.from_row(row)
            if sale.customer_id != customer_id:
                raise PermissionDenied("Este carrinho não pertence a você.")
            if sale.status not in {SaleStatus.WAITING, SaleStatus.ANALYSIS}:
                raise InvalidTransition("O carrinho já está bloqueado.")

            cursor = await connection.execute(
                """
                SELECT COUNT(*) AS total FROM sale_accounts
                WHERE sale_id = ? AND removed_at IS NULL
                """,
                (sale_id,),
            )
            count = int((await cursor.fetchone())["total"])
            await cursor.close()
            if count <= settings.min_accounts:
                raise ValidationError(
                    f"A venda precisa manter {settings.min_accounts} conta(s)."
                )
            cursor = await connection.execute(
                """
                UPDATE sale_accounts SET removed_at = ?
                WHERE id = ? AND sale_id = ? AND removed_at IS NULL
                """,
                (now, account_id, sale_id),
            )
            if cursor.rowcount != 1:
                await cursor.close()
                raise DuplicateOperation("Este Gmail já foi removido.")
            await cursor.close()
            await connection.execute(
                """
                INSERT INTO events(
                    guild_id, sale_id, event_type, actor_id,
                    payload_json, interaction_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sale.guild_id,
                    sale_id,
                    EventType.ACCOUNT_REMOVED.value,
                    customer_id,
                    json.dumps({"quantity": 1}),
                    interaction_id,
                    now,
                ),
            )
            await connection.execute(
                "UPDATE sales SET updated_at = ? WHERE id = ?",
                (now, sale_id),
            )
            cursor = await connection.execute(
                "SELECT * FROM sales WHERE id = ?", (sale_id,)
            )
            row = await cursor.fetchone()
            await cursor.close()
            return Sale.from_row(row), True

    async def edit_pix(
        self,
        *,
        sale_id: int,
        customer_id: int,
        pix_key: str,
        pix_holder: str,
        interaction_id: int,
    ) -> tuple[Sale, bool]:
        now = utc_now_iso()
        async with self.db.transaction() as connection:
            if await self._interaction_was_processed(connection, interaction_id):
                cursor = await connection.execute(
                    "SELECT * FROM sales WHERE id = ?", (sale_id,)
                )
                row = await cursor.fetchone()
                await cursor.close()
                return Sale.from_row(row), False
            cursor = await connection.execute(
                """
                UPDATE sales
                SET pix_key = ?, pix_holder = ?, updated_at = ?
                WHERE id = ? AND customer_id = ?
                  AND status IN (?, ?)
                """,
                (
                    pix_key,
                    pix_holder,
                    now,
                    sale_id,
                    customer_id,
                    SaleStatus.WAITING.value,
                    SaleStatus.ANALYSIS.value,
                ),
            )
            if cursor.rowcount != 1:
                await cursor.close()
                check = await connection.execute(
                    "SELECT customer_id, status FROM sales WHERE id = ?",
                    (sale_id,),
                )
                row = await check.fetchone()
                await check.close()
                if row and int(row["customer_id"]) != customer_id:
                    raise PermissionDenied("Este carrinho não pertence a você.")
                raise InvalidTransition("O carrinho já está bloqueado.")
            await cursor.close()
            cursor = await connection.execute(
                "SELECT guild_id FROM sales WHERE id = ?", (sale_id,)
            )
            guild_id = int((await cursor.fetchone())["guild_id"])
            await cursor.close()
            await connection.execute(
                """
                INSERT INTO events(
                    guild_id, sale_id, event_type, actor_id,
                    interaction_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    sale_id,
                    EventType.PIX_CHANGED.value,
                    customer_id,
                    interaction_id,
                    now,
                ),
            )
            cursor = await connection.execute(
                "SELECT * FROM sales WHERE id = ?", (sale_id,)
            )
            row = await cursor.fetchone()
            await cursor.close()
            return Sale.from_row(row), True

    async def cancel_by_customer(
        self,
        *,
        sale_id: int,
        customer_id: int,
        interaction_id: int,
        settings: GuildSettings,
    ) -> tuple[Sale, bool]:
        if not settings.customer_cancellation_enabled:
            raise InvalidTransition("O cancelamento pelo cliente está desativado.")
        now = utc_now_iso()
        async with self.db.transaction() as connection:
            if await self._interaction_was_processed(connection, interaction_id):
                cursor = await connection.execute(
                    "SELECT * FROM sales WHERE id = ?", (sale_id,)
                )
                row = await cursor.fetchone()
                await cursor.close()
                return Sale.from_row(row), False
            cursor = await connection.execute(
                """
                UPDATE sales
                SET status = ?, close_reason = ?, closed_by_id = ?,
                    closed_at = ?, updated_at = ?
                WHERE id = ? AND customer_id = ?
                  AND status IN (?, ?)
                """,
                (
                    SaleStatus.CLOSED.value,
                    "Cancelada pelo cliente.",
                    customer_id,
                    now,
                    now,
                    sale_id,
                    customer_id,
                    SaleStatus.WAITING.value,
                    SaleStatus.ANALYSIS.value,
                ),
            )
            if cursor.rowcount != 1:
                await cursor.close()
                check = await connection.execute(
                    "SELECT customer_id, status FROM sales WHERE id = ?",
                    (sale_id,),
                )
                row = await check.fetchone()
                await check.close()
                if row and int(row["customer_id"]) != customer_id:
                    raise PermissionDenied("Esta venda não pertence a você.")
                raise InvalidTransition("Esta venda não pode mais ser cancelada.")
            await cursor.close()
            cursor = await connection.execute(
                "SELECT guild_id FROM sales WHERE id = ?", (sale_id,)
            )
            guild_id = int((await cursor.fetchone())["guild_id"])
            await cursor.close()
            await connection.execute(
                """
                INSERT INTO events(
                    guild_id, sale_id, event_type, actor_id,
                    interaction_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    sale_id,
                    EventType.CUSTOMER_CANCELLED.value,
                    customer_id,
                    interaction_id,
                    now,
                ),
            )
            cursor = await connection.execute(
                "SELECT * FROM sales WHERE id = ?", (sale_id,)
            )
            row = await cursor.fetchone()
            await cursor.close()
            return Sale.from_row(row), True

    @staticmethod
    def _require_responsible(
        sale: Sale, actor_id: int, is_admin: bool
    ) -> None:
        if sale.responsible_staff_id == actor_id or is_admin:
            return
        raise PermissionDenied("Somente o atendente responsável pode avançar.")

    async def claim(
        self, *, sale_id: int, staff_id: int, interaction_id: int
    ) -> tuple[Sale, bool]:
        now = utc_now_iso()
        async with self.db.transaction() as connection:
            if await self._interaction_was_processed(connection, interaction_id):
                cursor = await connection.execute(
                    "SELECT * FROM sales WHERE id = ?", (sale_id,)
                )
                row = await cursor.fetchone()
                await cursor.close()
                return Sale.from_row(row), False
            cursor = await connection.execute(
                "SELECT * FROM sales WHERE id = ?", (sale_id,)
            )
            row = await cursor.fetchone()
            await cursor.close()
            if not row:
                raise ValidationError("Venda não encontrada.")
            sale = Sale.from_row(row)
            if (
                sale.status is SaleStatus.ANALYSIS
                and sale.responsible_staff_id == staff_id
            ):
                return sale, False
            if sale.status is not SaleStatus.WAITING:
                if sale.responsible_staff_id:
                    raise InvalidTransition("Esta venda já foi assumida.")
                raise InvalidTransition("Esta venda não está aguardando atendimento.")
            cursor = await connection.execute(
                """
                UPDATE sales
                SET status = ?, responsible_staff_id = ?, claimed_at = ?,
                    updated_at = ?
                WHERE id = ? AND status = ? AND responsible_staff_id IS NULL
                """,
                (
                    SaleStatus.ANALYSIS.value,
                    staff_id,
                    now,
                    now,
                    sale_id,
                    SaleStatus.WAITING.value,
                ),
            )
            if cursor.rowcount != 1:
                await cursor.close()
                raise DuplicateOperation("Outro atendente assumiu esta venda.")
            await cursor.close()
            await connection.execute(
                """
                INSERT INTO events(
                    guild_id, sale_id, event_type, actor_id,
                    interaction_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    sale.guild_id,
                    sale_id,
                    EventType.STAFF_CLAIMED.value,
                    staff_id,
                    interaction_id,
                    now,
                ),
            )
            cursor = await connection.execute(
                "SELECT * FROM sales WHERE id = ?", (sale_id,)
            )
            row = await cursor.fetchone()
            await cursor.close()
            return Sale.from_row(row), True

    async def continue_to_payment(
        self,
        *,
        sale_id: int,
        staff_id: int,
        is_admin: bool,
        interaction_id: int,
    ) -> tuple[Sale, bool]:
        now = utc_now_iso()
        async with self.db.transaction() as connection:
            if await self._interaction_was_processed(connection, interaction_id):
                cursor = await connection.execute(
                    "SELECT * FROM sales WHERE id = ?", (sale_id,)
                )
                row = await cursor.fetchone()
                await cursor.close()
                return Sale.from_row(row), False
            cursor = await connection.execute(
                "SELECT * FROM sales WHERE id = ?", (sale_id,)
            )
            row = await cursor.fetchone()
            await cursor.close()
            if not row:
                raise ValidationError("Venda não encontrada.")
            sale = Sale.from_row(row)
            if sale.status is SaleStatus.PAYMENT:
                return sale, False
            if sale.status is not SaleStatus.ANALYSIS:
                raise InvalidTransition("Esta venda não está em análise.")
            self._require_responsible(sale, staff_id, is_admin)
            cursor = await connection.execute(
                """
                UPDATE sales
                SET status = ?, payment_stage_at = COALESCE(payment_stage_at, ?),
                    updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    SaleStatus.PAYMENT.value,
                    now,
                    now,
                    sale_id,
                    SaleStatus.ANALYSIS.value,
                ),
            )
            if cursor.rowcount != 1:
                await cursor.close()
                raise DuplicateOperation("O estado da venda mudou.")
            await cursor.close()
            await connection.execute(
                """
                INSERT INTO events(
                    guild_id, sale_id, event_type, actor_id,
                    interaction_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    sale.guild_id,
                    sale_id,
                    EventType.PAYMENT_OPENED.value,
                    staff_id,
                    interaction_id,
                    now,
                ),
            )
            cursor = await connection.execute(
                "SELECT * FROM sales WHERE id = ?", (sale_id,)
            )
            row = await cursor.fetchone()
            await cursor.close()
            return Sale.from_row(row), True

    async def back_to_analysis(
        self,
        *,
        sale_id: int,
        staff_id: int,
        is_admin: bool,
        interaction_id: int,
    ) -> tuple[Sale, bool]:
        now = utc_now_iso()
        async with self.db.transaction() as connection:
            if await self._interaction_was_processed(connection, interaction_id):
                cursor = await connection.execute(
                    "SELECT * FROM sales WHERE id = ?", (sale_id,)
                )
                row = await cursor.fetchone()
                await cursor.close()
                return Sale.from_row(row), False
            cursor = await connection.execute(
                "SELECT * FROM sales WHERE id = ?", (sale_id,)
            )
            row = await cursor.fetchone()
            await cursor.close()
            if not row:
                raise ValidationError("Venda não encontrada.")
            sale = Sale.from_row(row)
            if sale.status is SaleStatus.ANALYSIS:
                return sale, False
            if sale.status is not SaleStatus.PAYMENT:
                raise InvalidTransition("A venda não está na etapa de pagamento.")
            self._require_responsible(sale, staff_id, is_admin)
            cursor = await connection.execute(
                """
                UPDATE sales SET status = ?, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    SaleStatus.ANALYSIS.value,
                    now,
                    sale_id,
                    SaleStatus.PAYMENT.value,
                ),
            )
            if cursor.rowcount != 1:
                await cursor.close()
                raise DuplicateOperation("O estado da venda mudou.")
            await cursor.close()
            await connection.execute(
                """
                INSERT INTO events(
                    guild_id, sale_id, event_type, actor_id,
                    interaction_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    sale.guild_id,
                    sale_id,
                    EventType.PAYMENT_REOPENED.value,
                    staff_id,
                    interaction_id,
                    now,
                ),
            )
            cursor = await connection.execute(
                "SELECT * FROM sales WHERE id = ?", (sale_id,)
            )
            row = await cursor.fetchone()
            await cursor.close()
            return Sale.from_row(row), True

    async def confirm_payment(
        self,
        *,
        sale_id: int,
        staff_id: int,
        is_admin: bool,
        interaction_id: int,
    ) -> tuple[Sale, bool]:
        now = utc_now_iso()
        async with self.db.transaction() as connection:
            if await self._interaction_was_processed(connection, interaction_id):
                cursor = await connection.execute(
                    "SELECT * FROM sales WHERE id = ?", (sale_id,)
                )
                row = await cursor.fetchone()
                await cursor.close()
                return Sale.from_row(row), False
            cursor = await connection.execute(
                "SELECT * FROM sales WHERE id = ?", (sale_id,)
            )
            row = await cursor.fetchone()
            await cursor.close()
            if not row:
                raise ValidationError("Venda não encontrada.")
            sale = Sale.from_row(row)
            if sale.status is SaleStatus.PAID:
                return sale, False
            if sale.status is not SaleStatus.PAYMENT:
                raise InvalidTransition("A venda não está na etapa de pagamento.")
            self._require_responsible(sale, staff_id, is_admin)
            cursor = await connection.execute(
                """
                UPDATE sales
                SET status = ?, paid_at = ?, payment_confirmed_by_id = ?,
                    updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    SaleStatus.PAID.value,
                    now,
                    staff_id,
                    now,
                    sale_id,
                    SaleStatus.PAYMENT.value,
                ),
            )
            if cursor.rowcount != 1:
                await cursor.close()
                raise DuplicateOperation("O pagamento já foi alterado.")
            await cursor.close()
            await connection.execute(
                """
                INSERT INTO events(
                    guild_id, sale_id, event_type, actor_id,
                    interaction_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    sale.guild_id,
                    sale_id,
                    EventType.PAYMENT_CONFIRMED.value,
                    staff_id,
                    interaction_id,
                    now,
                ),
            )
            cursor = await connection.execute(
                "SELECT * FROM sales WHERE id = ?", (sale_id,)
            )
            row = await cursor.fetchone()
            await cursor.close()
            return Sale.from_row(row), True

    async def finalize(
        self,
        *,
        sale_id: int,
        staff_id: int,
        is_admin: bool,
        interaction_id: int,
    ) -> tuple[Sale, bool]:
        now = utc_now_iso()
        async with self.db.transaction() as connection:
            if await self._interaction_was_processed(connection, interaction_id):
                cursor = await connection.execute(
                    "SELECT * FROM sales WHERE id = ?", (sale_id,)
                )
                row = await cursor.fetchone()
                await cursor.close()
                return Sale.from_row(row), False
            cursor = await connection.execute(
                "SELECT * FROM sales WHERE id = ?", (sale_id,)
            )
            row = await cursor.fetchone()
            await cursor.close()
            if not row:
                raise ValidationError("Venda não encontrada.")
            sale = Sale.from_row(row)
            if sale.status is SaleStatus.FINALIZED:
                return sale, False
            if sale.status is not SaleStatus.PAID:
                raise InvalidTransition("O pagamento ainda não foi confirmado.")
            self._require_responsible(sale, staff_id, is_admin)
            cursor = await connection.execute(
                """
                UPDATE sales
                SET status = ?, completed_at = ?, completed_by_id = ?,
                    updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (
                    SaleStatus.FINALIZED.value,
                    now,
                    staff_id,
                    now,
                    sale_id,
                    SaleStatus.PAID.value,
                ),
            )
            if cursor.rowcount != 1:
                await cursor.close()
                raise DuplicateOperation("Esta venda já foi finalizada.")
            await cursor.close()
            await connection.execute(
                """
                INSERT INTO events(
                    guild_id, sale_id, event_type, actor_id,
                    interaction_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    sale.guild_id,
                    sale_id,
                    EventType.SALE_FINALIZED.value,
                    staff_id,
                    interaction_id,
                    now,
                ),
            )
            cursor = await connection.execute(
                "SELECT * FROM sales WHERE id = ?", (sale_id,)
            )
            row = await cursor.fetchone()
            await cursor.close()
            return Sale.from_row(row), True

    async def close_by_staff(
        self,
        *,
        sale_id: int,
        staff_id: int,
        is_admin: bool,
        reason: str,
        interaction_id: int,
    ) -> tuple[Sale, bool]:
        now = utc_now_iso()
        async with self.db.transaction() as connection:
            if await self._interaction_was_processed(connection, interaction_id):
                cursor = await connection.execute(
                    "SELECT * FROM sales WHERE id = ?", (sale_id,)
                )
                row = await cursor.fetchone()
                await cursor.close()
                return Sale.from_row(row), False
            cursor = await connection.execute(
                "SELECT * FROM sales WHERE id = ?", (sale_id,)
            )
            row = await cursor.fetchone()
            await cursor.close()
            if not row:
                raise ValidationError("Venda não encontrada.")
            sale = Sale.from_row(row)
            if sale.status is SaleStatus.CLOSED:
                return sale, False
            if sale.status not in {
                SaleStatus.WAITING,
                SaleStatus.ANALYSIS,
                SaleStatus.PAYMENT,
            }:
                raise InvalidTransition("Esta venda não pode ser encerrada.")
            if sale.status is not SaleStatus.WAITING:
                self._require_responsible(sale, staff_id, is_admin)
            cursor = await connection.execute(
                """
                UPDATE sales
                SET status = ?, close_reason = ?, closed_by_id = ?,
                    closed_at = ?, updated_at = ?
                WHERE id = ? AND status IN (?, ?, ?)
                """,
                (
                    SaleStatus.CLOSED.value,
                    reason,
                    staff_id,
                    now,
                    now,
                    sale_id,
                    SaleStatus.WAITING.value,
                    SaleStatus.ANALYSIS.value,
                    SaleStatus.PAYMENT.value,
                ),
            )
            if cursor.rowcount != 1:
                await cursor.close()
                raise DuplicateOperation("O estado da venda mudou.")
            await cursor.close()
            await connection.execute(
                """
                INSERT INTO events(
                    guild_id, sale_id, event_type, actor_id,
                    interaction_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    sale.guild_id,
                    sale_id,
                    EventType.STAFF_CLOSED.value,
                    staff_id,
                    interaction_id,
                    now,
                ),
            )
            cursor = await connection.execute(
                "SELECT * FROM sales WHERE id = ?", (sale_id,)
            )
            row = await cursor.fetchone()
            await cursor.close()
            return Sale.from_row(row), True

    async def record_customer_notified(
        self,
        *,
        sale_id: int,
        staff_id: int,
        is_admin: bool,
        interaction_id: int,
    ) -> tuple[Sale, bool]:
        now = utc_now_iso()
        async with self.db.transaction() as connection:
            if await self._interaction_was_processed(connection, interaction_id):
                cursor = await connection.execute(
                    "SELECT * FROM sales WHERE id = ?", (sale_id,)
                )
                row = await cursor.fetchone()
                await cursor.close()
                return Sale.from_row(row), False
            cursor = await connection.execute(
                "SELECT * FROM sales WHERE id = ?", (sale_id,)
            )
            row = await cursor.fetchone()
            await cursor.close()
            if not row:
                raise ValidationError("Venda não encontrada.")
            sale = Sale.from_row(row)
            if sale.status not in {
                SaleStatus.WAITING,
                SaleStatus.ANALYSIS,
                SaleStatus.PAYMENT,
            }:
                raise InvalidTransition("Esta venda não aceita notificações.")
            if sale.status is not SaleStatus.WAITING:
                self._require_responsible(sale, staff_id, is_admin)
            await connection.execute(
                """
                INSERT INTO events(
                    guild_id, sale_id, event_type, actor_id,
                    interaction_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    sale.guild_id,
                    sale_id,
                    EventType.CUSTOMER_NOTIFIED.value,
                    staff_id,
                    interaction_id,
                    now,
                ),
            )
            return sale, True
