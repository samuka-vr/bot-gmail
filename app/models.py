from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from app.constants import DEFAULT_SETTINGS, SaleStatus


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


@dataclass(frozen=True, slots=True)
class Sale:
    id: int
    guild_id: int
    customer_id: int
    channel_id: int | None
    workflow_message_id: int | None
    cart_notice_message_id: int | None
    cart_notice_sent_at: datetime | None
    status: SaleStatus
    responsible_staff_id: int | None
    payment_confirmed_by_id: int | None
    completed_by_id: int | None
    unit_price_cents: int
    pix_key: str
    pix_holder: str
    verification_code: str
    ticket_name: str | None
    close_reason: str | None
    closed_by_id: int | None
    created_at: datetime
    claimed_at: datetime | None
    payment_stage_at: datetime | None
    paid_at: datetime | None
    completed_at: datetime | None
    closed_at: datetime | None
    cart_notice_delete_at: datetime | None
    ticket_delete_at: datetime | None
    transcript_message_id: int | None
    transcript_sent_at: datetime | None
    ticket_deleted_at: datetime | None
    terminal_processed_at: datetime | None
    updated_at: datetime

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Sale":
        return cls(
            id=int(row["id"]),
            guild_id=int(row["guild_id"]),
            customer_id=int(row["customer_id"]),
            channel_id=int(row["channel_id"]) if row["channel_id"] else None,
            workflow_message_id=(
                int(row["workflow_message_id"])
                if row["workflow_message_id"]
                else None
            ),
            cart_notice_message_id=(
                int(row["cart_notice_message_id"])
                if row["cart_notice_message_id"]
                else None
            ),
            cart_notice_sent_at=_dt(row["cart_notice_sent_at"]),
            status=SaleStatus(row["status"]),
            responsible_staff_id=(
                int(row["responsible_staff_id"])
                if row["responsible_staff_id"]
                else None
            ),
            payment_confirmed_by_id=(
                int(row["payment_confirmed_by_id"])
                if row["payment_confirmed_by_id"]
                else None
            ),
            completed_by_id=(
                int(row["completed_by_id"])
                if row["completed_by_id"]
                else None
            ),
            unit_price_cents=int(row["unit_price_cents"]),
            pix_key=str(row["pix_key"]),
            pix_holder=str(row["pix_holder"]),
            verification_code=str(row["verification_code"]),
            ticket_name=row["ticket_name"],
            close_reason=row["close_reason"],
            closed_by_id=int(row["closed_by_id"]) if row["closed_by_id"] else None,
            created_at=_dt(row["created_at"]),  # type: ignore[arg-type]
            claimed_at=_dt(row["claimed_at"]),
            payment_stage_at=_dt(row["payment_stage_at"]),
            paid_at=_dt(row["paid_at"]),
            completed_at=_dt(row["completed_at"]),
            closed_at=_dt(row["closed_at"]),
            cart_notice_delete_at=_dt(row["cart_notice_delete_at"]),
            ticket_delete_at=_dt(row["ticket_delete_at"]),
            transcript_message_id=(
                int(row["transcript_message_id"])
                if row["transcript_message_id"]
                else None
            ),
            transcript_sent_at=_dt(row["transcript_sent_at"]),
            ticket_deleted_at=_dt(row["ticket_deleted_at"]),
            terminal_processed_at=_dt(row["terminal_processed_at"]),
            updated_at=_dt(row["updated_at"]),  # type: ignore[arg-type]
        )


@dataclass(frozen=True, slots=True)
class SaleAccount:
    id: int
    sale_id: int
    email: str
    canonical_email: str
    created_at: datetime
    removed_at: datetime | None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "SaleAccount":
        return cls(
            id=int(row["id"]),
            sale_id=int(row["sale_id"]),
            email=str(row["email"]),
            canonical_email=str(row["canonical_email"]),
            created_at=_dt(row["created_at"]),  # type: ignore[arg-type]
            removed_at=_dt(row["removed_at"]),
        )


def _bool(value: str) -> bool:
    return value.lower() == "true"


def _optional_id(value: str) -> int | None:
    return int(value) if value else None


@dataclass(frozen=True, slots=True)
class GuildSettings:
    panel_title: str
    panel_description: str
    panel_footer: str
    panel_button_text: str
    panel_price_label: str
    panel_info_text: str
    panel_channel_id: int | None
    panel_message_id: int | None
    panel_message_channel_id: int | None
    ticket_category_id: int | None
    logs_channel_id: int | None
    transcript_channel_id: int | None
    staff_role_id: int | None
    admin_role_id: int | None
    unit_price_cents: int
    min_accounts: int
    max_accounts: int
    embed_color: int
    logo_url: str
    banner_url: str
    icon_sell_id: int | None
    icon_edit_id: int | None
    icon_staff_id: int | None
    icon_payment_id: int | None
    cart_message_enabled: bool
    cart_message_target: str
    cart_message_text: str
    cart_message_auto_delete: bool
    cart_message_delete_delay: int
    logs_enabled: bool
    transcripts_enabled: bool
    ticket_prefix: str
    max_active_sales: int
    customer_cancellation_enabled: bool
    dm_notifications_enabled: bool
    auto_close_enabled: bool
    auto_close_delay: int
    rename_closed_tickets: bool

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> "GuildSettings":
        merged = dict(DEFAULT_SETTINGS)
        merged.update(values)
        return cls(
            panel_title=merged["panel_title"],
            panel_description=merged["panel_description"],
            panel_footer=merged["panel_footer"],
            panel_button_text=merged["panel_button_text"],
            panel_price_label=merged["panel_price_label"],
            panel_info_text=merged["panel_info_text"],
            panel_channel_id=_optional_id(merged["panel_channel_id"]),
            panel_message_id=_optional_id(merged["panel_message_id"]),
            panel_message_channel_id=_optional_id(
                merged["panel_message_channel_id"]
            ),
            ticket_category_id=_optional_id(merged["ticket_category_id"]),
            logs_channel_id=_optional_id(merged["logs_channel_id"]),
            transcript_channel_id=_optional_id(
                merged["transcript_channel_id"]
            ),
            staff_role_id=_optional_id(merged["staff_role_id"]),
            admin_role_id=_optional_id(merged["admin_role_id"]),
            unit_price_cents=int(merged["unit_price_cents"]),
            min_accounts=int(merged["min_accounts"]),
            max_accounts=int(merged["max_accounts"]),
            embed_color=int(merged["embed_color"], 16),
            logo_url=merged["logo_url"],
            banner_url=merged["banner_url"],
            icon_sell_id=_optional_id(merged["icon_sell_id"]),
            icon_edit_id=_optional_id(merged["icon_edit_id"]),
            icon_staff_id=_optional_id(merged["icon_staff_id"]),
            icon_payment_id=_optional_id(merged["icon_payment_id"]),
            cart_message_enabled=_bool(merged["cart_message_enabled"]),
            cart_message_target=merged["cart_message_target"],
            cart_message_text=merged["cart_message_text"],
            cart_message_auto_delete=_bool(
                merged["cart_message_auto_delete"]
            ),
            cart_message_delete_delay=int(
                merged["cart_message_delete_delay"]
            ),
            logs_enabled=_bool(merged["logs_enabled"]),
            transcripts_enabled=_bool(merged["transcripts_enabled"]),
            ticket_prefix=merged["ticket_prefix"],
            max_active_sales=int(merged["max_active_sales"]),
            customer_cancellation_enabled=_bool(
                merged["customer_cancellation_enabled"]
            ),
            dm_notifications_enabled=_bool(
                merged["dm_notifications_enabled"]
            ),
            auto_close_enabled=_bool(merged["auto_close_enabled"]),
            auto_close_delay=int(merged["auto_close_delay"]),
            rename_closed_tickets=_bool(
                merged["rename_closed_tickets"]
            ),
        )
