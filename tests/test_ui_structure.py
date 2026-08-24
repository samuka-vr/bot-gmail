from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime

import discord

from app.constants import DEFAULT_SETTINGS, SaleStatus
from app.models import GuildSettings, Sale, SaleAccount
from app.modals.sale import SaleModal
from app.modals.cart import AddGmailModal, EditPixModal
from app.modals.configuration import (
    BrandAppearanceModal,
    CartMessageModal,
    GeneralSettingsModal,
    IconsAppearanceModal,
    PanelActionModal,
    PanelTextsModal,
    PricesModal,
)
from app.modals.staff import CloseSaleModal, NotifyCustomerModal
from app.utils.embeds import (
    build_customer_dm_embed,
    build_panel_embed,
    build_profile_embed,
    build_queue_embed,
    build_sale_embed,
)
from app.utils.config_embeds import build_config_embed, configuration_readiness
from app.utils.mentions import allowed_user_mentions
from app.views.configuration import (
    AppearanceConfigView,
    BotConfigView,
    CartMessageConfigView,
    ChannelsConfigView,
    GeneralConfigView,
    LogsConfigView,
    PanelConfigView,
    RolesConfigView,
)
from app.views.panel import PanelView
from app.views.links import TicketLinkView
from app.views.sale import (
    AnalysisSaleView,
    PaidSaleView,
    PaymentSaleView,
    WaitingSaleView,
)


class DummyBot:
    pass


def sample_sale(status: SaleStatus) -> Sale:
    now = datetime.now(UTC)
    return Sale(
        id=42,
        guild_id=1,
        customer_id=100,
        channel_id=200,
        workflow_message_id=300,
        cart_notice_message_id=None,
        cart_notice_sent_at=None,
        status=status,
        responsible_staff_id=500 if status is not SaleStatus.WAITING else None,
        payment_confirmed_by_id=500 if status is SaleStatus.PAID else None,
        completed_by_id=500 if status is SaleStatus.FINALIZED else None,
        unit_price_cents=200,
        pix_key="cliente@pix.com",
        pix_holder="Cliente Teste",
        verification_code="SK-48321",
        ticket_name="gmail-0042",
        close_reason="Motivo curto" if status is SaleStatus.CLOSED else None,
        closed_by_id=500 if status is SaleStatus.CLOSED else None,
        created_at=now,
        claimed_at=now if status is not SaleStatus.WAITING else None,
        payment_stage_at=(
            now
            if status
            in {SaleStatus.PAYMENT, SaleStatus.PAID, SaleStatus.FINALIZED}
            else None
        ),
        paid_at=now if status in {SaleStatus.PAID, SaleStatus.FINALIZED} else None,
        completed_at=now if status is SaleStatus.FINALIZED else None,
        closed_at=now if status is SaleStatus.CLOSED else None,
        cart_notice_delete_at=None,
        ticket_delete_at=None,
        transcript_message_id=None,
        transcript_sent_at=None,
        ticket_deleted_at=None,
        terminal_processed_at=None,
        updated_at=now,
    )


def sample_accounts(quantity: int = 3) -> list[SaleAccount]:
    now = datetime.now(UTC)
    return [
        SaleAccount(
            id=index,
            sale_id=42,
            email=f"gmail{index}@gmail.com",
            canonical_email=f"gmail{index}@gmail.com",
            created_at=now,
            removed_at=None,
        )
        for index in range(1, quantity + 1)
    ]


class PersistentViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bot = DummyBot()
        self.settings = GuildSettings.from_mapping(DEFAULT_SETTINGS)

    def test_all_public_views_are_persistent_and_ids_are_unique(self) -> None:
        views = [
            PanelView(self.bot, self.settings),
            WaitingSaleView(self.bot, self.settings),
            AnalysisSaleView(self.bot, self.settings),
            PaymentSaleView(self.bot, self.settings),
            PaidSaleView(self.bot, self.settings),
        ]
        custom_ids: list[str] = []
        for view in views:
            self.assertTrue(view.is_persistent(), type(view).__name__)
            custom_ids.extend(item.custom_id for item in view.children)
        self.assertEqual(len(custom_ids), len(set(custom_ids)))
        self.assertTrue(all(len(custom_id) <= 100 for custom_id in custom_ids))

    def test_each_state_shows_only_current_actions(self) -> None:
        waiting = WaitingSaleView(self.bot, self.settings)
        analysis = AnalysisSaleView(self.bot, self.settings)
        payment = PaymentSaleView(self.bot, self.settings)
        paid = PaidSaleView(self.bot, self.settings)

        def labels(view: discord.ui.View) -> list[str]:
            return [
                getattr(item, "label", getattr(item, "placeholder", ""))
                for item in view.children
            ]

        self.assertEqual(
            labels(waiting),
            [
                "Editar carrinho",
                "Assumir",
                "Cancelar venda",
                "Ações da equipe",
            ],
        )
        self.assertEqual(
            labels(analysis),
            [
                "Editar carrinho",
                "Continuar para pagamento",
                "Cancelar venda",
                "Ações da equipe",
            ],
        )
        self.assertEqual(
            labels(payment),
            ["Confirmar pagamento", "Ações da equipe"],
        )
        self.assertEqual([item.label for item in paid.children], ["Finalizar venda"])
        self.assertEqual(waiting.children[1].style, discord.ButtonStyle.primary)
        self.assertEqual(waiting.children[2].style, discord.ButtonStyle.danger)
        self.assertEqual(analysis.children[1].style, discord.ButtonStyle.primary)
        self.assertEqual(analysis.children[2].style, discord.ButtonStyle.danger)
        self.assertEqual({item.row for item in waiting.children}, {0, 1, 2})
        self.assertEqual({item.row for item in analysis.children}, {0, 1, 2})

    def test_disabled_customer_features_are_hidden(self) -> None:
        settings = GuildSettings.from_mapping(
            {
                **DEFAULT_SETTINGS,
                "customer_cancellation_enabled": "false",
                "dm_notifications_enabled": "false",
            }
        )
        waiting = WaitingSaleView(self.bot, settings)
        analysis = AnalysisSaleView(self.bot, settings)
        payment = PaymentSaleView(self.bot, settings)
        self.assertNotIn(
            "Cancelar venda", [getattr(item, "label", None) for item in waiting.children]
        )
        self.assertNotIn(
            "Cancelar venda", [getattr(item, "label", None) for item in analysis.children]
        )
        for view in (waiting, analysis, payment):
            staff_menu = next(
                item
                for item in view.children
                if getattr(item, "placeholder", None) == "Ações da equipe"
            )
            self.assertNotIn("notify", [option.value for option in staff_menu.options])

    def test_sale_modal_has_only_required_three_fields(self) -> None:
        modal = SaleModal(self.bot)
        labels = [item.text for item in modal.children]
        self.assertEqual(labels, ["Gmails", "Chave Pix", "Nome do titular"])
        forbidden = {"senha", "2fa", "cookie", "token", "código de recuperação"}
        self.assertFalse(any(term in " ".join(labels).lower() for term in forbidden))
        self.assertEqual(
            modal.children[0].description,
            "Um endereço por linha. Nunca envie senha.",
        )

    def test_ticket_link_view_is_small_and_uses_a_real_link_button(self) -> None:
        view = TicketLinkView("https://discord.com/channels/1/2")
        self.assertEqual(len(view.children), 1)
        button = view.children[0]
        self.assertEqual(button.label, "Abrir atendimento")
        self.assertEqual(button.style, discord.ButtonStyle.link)
        self.assertEqual(button.url, "https://discord.com/channels/1/2")
        self.assertIsNone(button.custom_id)

    def test_concurrent_modals_receive_unique_dispatch_ids(self) -> None:
        constructors = (
            lambda: SaleModal(self.bot),
            lambda: AddGmailModal(self.bot, 42),
            lambda: EditPixModal(self.bot, 42, "chave", "Titular"),
            lambda: NotifyCustomerModal(self.bot, 42),
            lambda: CloseSaleModal(self.bot, 42),
            lambda: PanelTextsModal(self.bot, self.settings),
        )
        for constructor in constructors:
            first = constructor()
            second = constructor()
            self.assertNotEqual(first.custom_id, second.custom_id)
            self.assertLessEqual(len(first.custom_id), 100)

    def test_all_modals_use_current_labeled_inputs_and_component_limits(self) -> None:
        modals = [
            SaleModal(self.bot),
            AddGmailModal(self.bot, 42),
            EditPixModal(self.bot, 42, "chave", "Titular"),
            NotifyCustomerModal(self.bot, 42),
            CloseSaleModal(self.bot, 42),
            PanelTextsModal(self.bot, self.settings),
            PanelActionModal(self.bot, self.settings),
            PricesModal(self.bot, self.settings),
            BrandAppearanceModal(self.bot, self.settings),
            IconsAppearanceModal(self.bot, self.settings),
            CartMessageModal(self.bot, self.settings),
            GeneralSettingsModal(self.bot, self.settings),
        ]
        for modal in modals:
            self.assertLessEqual(len(modal.children), 5)
            self.assertTrue(
                all(isinstance(item, discord.ui.Label) for item in modal.children),
                type(modal).__name__,
            )
            input_ids = [item.component.custom_id for item in modal.children]
            self.assertEqual(len(input_ids), len(set(input_ids)))

    def test_botconfig_grouping_and_component_counts(self) -> None:
        main = BotConfigView(self.bot, 1)
        self.assertEqual(len(main.children), 1)
        self.assertEqual(len(main.children[0].options), 10)
        views = [
            PanelConfigView(self.bot, 1, self.settings),
            ChannelsConfigView(self.bot, 1, self.settings),
            RolesConfigView(self.bot, 1, self.settings),
            AppearanceConfigView(self.bot, 1, self.settings),
            CartMessageConfigView(self.bot, 1, self.settings),
            LogsConfigView(self.bot, 1, self.settings),
            GeneralConfigView(self.bot, 1, self.settings),
        ]
        self.assertTrue(all(len(view.children) <= 5 for view in views))
        for view in views:
            ids = [item.custom_id for item in view.children]
            self.assertEqual(len(ids), len(set(ids)), type(view).__name__)

    def test_botconfig_summarizes_readiness_without_extra_controls(self) -> None:
        passed, total, missing = configuration_readiness(self.settings)
        self.assertEqual((passed, total), (1, 7))
        self.assertIn("canal do painel", missing)
        embed = build_config_embed(self.settings)
        self.assertIn("1/7", embed.description)
        self.assertEqual(
            [field.name for field in embed.fields],
            ["Operação", "Estrutura", "Registros"],
        )


class EmbedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = GuildSettings.from_mapping(DEFAULT_SETTINGS)

    def test_panel_embed_is_compact_and_branded(self) -> None:
        embed = build_panel_embed(self.settings)
        self.assertEqual(embed.title, "Venda contas Gmail para a SK Store")
        self.assertEqual(embed.fields[0].name, "Valor por conta")
        self.assertEqual(embed.fields[0].value, "**R$ 2,00**")

    def test_panel_embed_stays_within_discord_aggregate_limit(self) -> None:
        settings = GuildSettings.from_mapping(
            {
                **DEFAULT_SETTINGS,
                "panel_title": "T" * 256,
                "panel_description": "D" * 4_000,
                "panel_footer": "R" * 2_000,
                "panel_price_label": "P" * 256,
                "panel_info_text": "I" * 1_000,
            }
        )
        embed = build_panel_embed(settings)
        total = len(embed.title or "") + len(embed.description or "")
        total += sum(
            len(field.name) + len(field.value) for field in embed.fields
        )
        total += len(embed.footer.text or "")
        self.assertLessEqual(total, 6_000)

    def test_cart_and_payment_embeds(self) -> None:
        accounts = sample_accounts()
        waiting_sale = sample_sale(SaleStatus.WAITING)
        cart = build_sale_embed(waiting_sale, accounts, self.settings)
        fields = {field.name: field.value for field in cart.fields}
        self.assertEqual(cart.title, "Venda #0042 · Aguardando")
        self.assertIn("**3 contas · R$ 2,00 cada**", cart.description)
        self.assertIn("Total a receber: **R$ 6,00**", cart.description)
        self.assertIn(
            "**Chave:** `cliente@pix.com`",
            fields["Recebimento via Pix"],
        )
        self.assertTrue(
            any(name.startswith("Contas enviadas · 3") for name in fields)
        )
        self.assertLessEqual(len(cart.fields), 2)
        self.assertEqual(cart.timestamp, waiting_sale.updated_at)

        payment = build_sale_embed(
            sample_sale(SaleStatus.PAYMENT), accounts, self.settings
        )
        self.assertEqual(payment.title, "Venda #0042 · Pagamento")
        self.assertEqual(len(payment.fields), 1)
        self.assertFalse(
            any(field.name.startswith("Contas enviadas") for field in payment.fields)
        )

        terminal = build_sale_embed(
            sample_sale(SaleStatus.FINALIZED), accounts, self.settings
        )
        self.assertFalse(
            any(field.name.startswith("Contas enviadas") for field in terminal.fields)
        )

        delete_at = datetime.now(UTC)
        terminal_with_deadline = build_sale_embed(
            replace(
                sample_sale(SaleStatus.CLOSED),
                ticket_delete_at=delete_at,
            ),
            accounts,
            self.settings,
        )
        self.assertIn(
            f"<t:{int(delete_at.timestamp())}:R>",
            terminal_with_deadline.description,
        )

    def test_sale_embed_uses_configured_logo_as_thumbnail(self) -> None:
        settings = GuildSettings.from_mapping(
            {**DEFAULT_SETTINGS, "logo_url": "https://example.com/logo.png"}
        )
        embed = build_sale_embed(
            sample_sale(SaleStatus.WAITING), sample_accounts(1), settings
        )
        self.assertEqual(embed.thumbnail.url, "https://example.com/logo.png")

    def test_customer_mentions_allow_only_the_target_user(self) -> None:
        mentions = allowed_user_mentions(123)
        self.assertFalse(mentions.values["everyone"])
        self.assertFalse(mentions.values["roles"])
        self.assertFalse(mentions.values["replied_user"])
        self.assertEqual([user.id for user in mentions.values["users"]], [123])

    def test_customer_dm_is_branded_without_a_fake_user_mention(self) -> None:
        embed = build_customer_dm_embed(
            sample_sale(SaleStatus.ANALYSIS),
            self.settings,
            "Sua venda precisa da sua atenção.",
            staff_name="Atendente",
        )
        self.assertEqual(embed.title, "SK Store · Venda #0042")
        self.assertEqual(embed.description, "Sua venda precisa da sua atenção.")
        self.assertNotIn("<@", embed.description)
        self.assertIn("Atendente", embed.footer.text)

    def test_profile_and_queue_embeds_are_grouped_and_compact(self) -> None:
        now = datetime.now(UTC)
        profile = {
            "completed_sales": 12,
            "sold_accounts": 48,
            "received_cents": 9_600,
            "cancelled_sales": 2,
            "recent": [
                {
                    "id": 42,
                    "status": SaleStatus.FINALIZED.value,
                    "unit_price_cents": 200,
                    "account_count": 3,
                    "created_at": now.isoformat(),
                }
            ],
        }
        profile_embed = build_profile_embed(profile, 100, self.settings)
        self.assertEqual(len(profile_embed.fields), 4)
        self.assertIn("Vendas canceladas: **2**", profile_embed.description)

        rows = [
            {
                "id": 42,
                "status": SaleStatus.WAITING.value,
                "customer_id": 100,
                "responsible_staff_id": None,
                "unit_price_cents": 200,
                "account_count": 3,
                "channel_id": 200,
                "created_at": now.isoformat(),
            },
            {
                "id": 43,
                "status": SaleStatus.ANALYSIS.value,
                "customer_id": 101,
                "responsible_staff_id": 500,
                "unit_price_cents": 200,
                "account_count": 2,
                "channel_id": 201,
                "created_at": now.isoformat(),
            },
        ]
        queue_embed = build_queue_embed(rows, self.settings)
        self.assertEqual(queue_embed.title, "Fila de vendas · 2")
        self.assertEqual(len(queue_embed.fields), 2)
        self.assertEqual(queue_embed.fields[0].name, "Aguardando · 1")
        self.assertEqual(queue_embed.fields[1].name, "Em análise · 1")

    def test_cart_embed_stays_within_discord_limits_at_maximum(self) -> None:
        now = datetime.now(UTC)
        accounts = [
            SaleAccount(
                id=index,
                sale_id=42,
                email=f"{'a' * 58}{index:02d}@gmail.com",
                canonical_email=f"{'a' * 58}{index:02d}@gmail.com",
                created_at=now,
                removed_at=None,
            )
            for index in range(25)
        ]
        sale = replace(
            sample_sale(SaleStatus.WAITING),
            pix_key="p" * 140,
            pix_holder="t" * 100,
        )
        embed = build_sale_embed(sale, accounts, self.settings)
        total = len(embed.title or "") + len(embed.description or "")
        total += sum(
            len(field.name) + len(field.value) for field in embed.fields
        )
        total += len(embed.footer.text or "")
        self.assertLessEqual(len(embed.fields), 25)
        self.assertTrue(all(len(field.value) <= 1_024 for field in embed.fields))
        self.assertLessEqual(total, 6_000)
