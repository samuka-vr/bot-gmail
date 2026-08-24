from __future__ import annotations

from enum import StrEnum


class SaleStatus(StrEnum):
    WAITING = "AGUARDANDO"
    ANALYSIS = "EM_ANALISE"
    PAYMENT = "PAGAMENTO"
    PAID = "PAGO"
    FINALIZED = "FINALIZADO"
    CLOSED = "ENCERRADO"


ACTIVE_STATUSES = (
    SaleStatus.WAITING,
    SaleStatus.ANALYSIS,
    SaleStatus.PAYMENT,
    SaleStatus.PAID,
)
TERMINAL_STATUSES = (SaleStatus.FINALIZED, SaleStatus.CLOSED)

STATUS_LABELS: dict[SaleStatus, str] = {
    SaleStatus.WAITING: "Aguardando atendimento",
    SaleStatus.ANALYSIS: "Em análise",
    SaleStatus.PAYMENT: "Pagamento",
    SaleStatus.PAID: "Pagamento confirmado",
    SaleStatus.FINALIZED: "Finalizada",
    SaleStatus.CLOSED: "Encerrada",
}


class EventType(StrEnum):
    SALE_CREATED = "SALE_CREATED"
    ACCOUNT_ADDED = "ACCOUNT_ADDED"
    ACCOUNT_REMOVED = "ACCOUNT_REMOVED"
    PIX_CHANGED = "PIX_CHANGED"
    STAFF_CLAIMED = "STAFF_CLAIMED"
    CUSTOMER_NOTIFIED = "CUSTOMER_NOTIFIED"
    PAYMENT_OPENED = "PAYMENT_OPENED"
    PAYMENT_REOPENED = "PAYMENT_REOPENED"
    PAYMENT_CONFIRMED = "PAYMENT_CONFIRMED"
    SALE_FINALIZED = "SALE_FINALIZED"
    CUSTOMER_CANCELLED = "CUSTOMER_CANCELLED"
    STAFF_CLOSED = "STAFF_CLOSED"
    CONFIG_CHANGED = "CONFIG_CHANGED"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"


DEFAULT_SETTINGS: dict[str, str] = {
    "panel_title": "Venda seus G-mails para a SK Store",
    "panel_description": (
        "Venda G-mails que você não usa mais ou crie novas contas para vender.\n\n"
        "Pagamento via Pix."
    ),
    "panel_footer": "SK Store",
    "panel_button_text": "Vender Gmail",
    "panel_price_label": "Valor por conta",
    "panel_info_text": "",
    "panel_channel_id": "",
    "panel_message_id": "",
    "panel_message_channel_id": "",
    "ticket_category_id": "",
    "logs_channel_id": "",
    "transcript_channel_id": "",
    "staff_role_id": "",
    "admin_role_id": "",
    "unit_price_cents": "200",
    "min_accounts": "1",
    "max_accounts": "25",
    "embed_color": "1F2937",
    "logo_url": "",
    "banner_url": "",
    "icon_sell_id": "",
    "icon_edit_id": "",
    "icon_staff_id": "",
    "icon_payment_id": "",
    "cart_message_enabled": "true",
    "cart_message_target": "ticket",
    "cart_message_text": (
        "{user}, seu carrinho foi criado. Confira seus dados abaixo."
    ),
    "cart_message_auto_delete": "false",
    "cart_message_delete_delay": "60",
    "logs_enabled": "true",
    "transcripts_enabled": "true",
    "ticket_prefix": "gmail",
    "max_active_sales": "1",
    "customer_cancellation_enabled": "true",
    "dm_notifications_enabled": "true",
    "auto_close_enabled": "true",
    "auto_close_delay": "60",
    "rename_closed_tickets": "true",
}

MAX_ACCOUNTS_DISCORD = 25
SALE_TOPIC_PREFIX = "SKSTORE_SALE_ID="


class CustomID:
    PANEL_SELL = "sk:panel:sell"

    CART_EDIT_WAITING = "sk:sale:waiting:cart_edit"
    CART_CANCEL_WAITING = "sk:sale:waiting:cancel"
    STAFF_CLAIM = "sk:sale:waiting:claim"
    STAFF_ACTIONS_WAITING = "sk:sale:waiting:staff_actions"

    CART_EDIT_ANALYSIS = "sk:sale:analysis:cart_edit"
    CART_CANCEL_ANALYSIS = "sk:sale:analysis:cancel"
    STAFF_CONTINUE = "sk:sale:analysis:continue"
    STAFF_ACTIONS_ANALYSIS = "sk:sale:analysis:staff_actions"

    STAFF_CONFIRM_PAYMENT = "sk:sale:payment:confirm"
    STAFF_ACTIONS_PAYMENT = "sk:sale:payment:staff_actions"
    STAFF_FINALIZE = "sk:sale:paid:finalize"

    REMOVE_ACCOUNT = "sk:sale:remove_account"
    CONFIRM_CANCEL = "sk:sale:confirm_cancel"
    ABORT_CANCEL = "sk:sale:abort_cancel"

    CONFIG_MAIN = "sk:config:main"
