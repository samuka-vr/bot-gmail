from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from app.constants import CustomID, SaleStatus
from app.models import GuildSettings
from app.utils.emojis import custom_emoji

if TYPE_CHECKING:
    from app.bot import SKStoreBot


class _BotView(discord.ui.View):
    def __init__(self, bot: "SKStoreBot", *, timeout: float | None = None) -> None:
        super().__init__(timeout=timeout)
        self.bot = bot

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item[discord.ui.View],
    ) -> None:
        await self.bot.handle_user_exception(interaction, error)


class WaitingSaleView(_BotView):
    def __init__(
        self, bot: "SKStoreBot", settings: GuildSettings | None = None
    ) -> None:
        super().__init__(bot, timeout=None)
        if settings:
            self.claim.emoji = custom_emoji(settings.icon_staff_id)
            icon = custom_emoji(settings.icon_edit_id)
            for option in self.cart_edit.options:
                option.emoji = icon
            if not settings.customer_cancellation_enabled:
                self.remove_item(self.cancel)
            if not settings.dm_notifications_enabled:
                self.staff_actions.options = [
                    option
                    for option in self.staff_actions.options
                    if option.value != "notify"
                ]

    @discord.ui.select(
        placeholder="Editar carrinho",
        custom_id=CustomID.CART_EDIT_WAITING,
        options=[
            discord.SelectOption(label="Adicionar Gmail", value="add"),
            discord.SelectOption(label="Remover Gmail", value="remove"),
            discord.SelectOption(label="Editar Pix", value="pix"),
        ],
        row=0,
    )
    async def cart_edit(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ) -> None:
        await self.bot.workflow.handle_cart_edit(interaction, select.values[0])

    @discord.ui.button(
        label="Cancelar venda",
        style=discord.ButtonStyle.danger,
        custom_id=CustomID.CART_CANCEL_WAITING,
        row=1,
    )
    async def cancel(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await self.bot.workflow.request_customer_cancel(interaction)

    @discord.ui.button(
        label="Assumir",
        style=discord.ButtonStyle.primary,
        custom_id=CustomID.STAFF_CLAIM,
        row=2,
    )
    async def claim(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await self.bot.workflow.claim(interaction)

    @discord.ui.select(
        placeholder="Ações",
        custom_id=CustomID.STAFF_ACTIONS_WAITING,
        options=[
            discord.SelectOption(label="Notificar cliente", value="notify"),
            discord.SelectOption(label="Encerrar venda", value="close"),
        ],
        row=3,
    )
    async def staff_actions(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ) -> None:
        await self.bot.workflow.handle_staff_action(
            interaction, select.values[0]
        )


class AnalysisSaleView(_BotView):
    def __init__(
        self, bot: "SKStoreBot", settings: GuildSettings | None = None
    ) -> None:
        super().__init__(bot, timeout=None)
        if settings:
            self.continue_payment.emoji = custom_emoji(settings.icon_payment_id)
            icon = custom_emoji(settings.icon_edit_id)
            for option in self.cart_edit.options:
                option.emoji = icon
            if not settings.customer_cancellation_enabled:
                self.remove_item(self.cancel)
            if not settings.dm_notifications_enabled:
                self.staff_actions.options = [
                    option
                    for option in self.staff_actions.options
                    if option.value != "notify"
                ]

    @discord.ui.select(
        placeholder="Editar carrinho",
        custom_id=CustomID.CART_EDIT_ANALYSIS,
        options=[
            discord.SelectOption(label="Adicionar Gmail", value="add"),
            discord.SelectOption(label="Remover Gmail", value="remove"),
            discord.SelectOption(label="Editar Pix", value="pix"),
        ],
        row=0,
    )
    async def cart_edit(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ) -> None:
        await self.bot.workflow.handle_cart_edit(interaction, select.values[0])

    @discord.ui.button(
        label="Cancelar venda",
        style=discord.ButtonStyle.danger,
        custom_id=CustomID.CART_CANCEL_ANALYSIS,
        row=1,
    )
    async def cancel(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await self.bot.workflow.request_customer_cancel(interaction)

    @discord.ui.button(
        label="Continuar para pagamento",
        style=discord.ButtonStyle.primary,
        custom_id=CustomID.STAFF_CONTINUE,
        row=2,
    )
    async def continue_payment(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await self.bot.workflow.continue_to_payment(interaction)

    @discord.ui.select(
        placeholder="Ações",
        custom_id=CustomID.STAFF_ACTIONS_ANALYSIS,
        options=[
            discord.SelectOption(label="Notificar cliente", value="notify"),
            discord.SelectOption(label="Encerrar venda", value="close"),
        ],
        row=3,
    )
    async def staff_actions(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ) -> None:
        await self.bot.workflow.handle_staff_action(
            interaction, select.values[0]
        )


class PaymentSaleView(_BotView):
    def __init__(
        self, bot: "SKStoreBot", settings: GuildSettings | None = None
    ) -> None:
        super().__init__(bot, timeout=None)
        if settings:
            self.confirm_payment.emoji = custom_emoji(settings.icon_payment_id)
            if not settings.dm_notifications_enabled:
                self.staff_actions.options = [
                    option
                    for option in self.staff_actions.options
                    if option.value != "notify"
                ]

    @discord.ui.button(
        label="Confirmar pagamento",
        style=discord.ButtonStyle.primary,
        custom_id=CustomID.STAFF_CONFIRM_PAYMENT,
        row=0,
    )
    async def confirm_payment(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await self.bot.workflow.confirm_payment(interaction)

    @discord.ui.select(
        placeholder="Ações",
        custom_id=CustomID.STAFF_ACTIONS_PAYMENT,
        options=[
            discord.SelectOption(label="Voltar", value="back"),
            discord.SelectOption(label="Notificar cliente", value="notify"),
            discord.SelectOption(label="Encerrar venda", value="close"),
        ],
        row=1,
    )
    async def staff_actions(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ) -> None:
        await self.bot.workflow.handle_staff_action(
            interaction, select.values[0]
        )


class PaidSaleView(_BotView):
    def __init__(
        self, bot: "SKStoreBot", settings: GuildSettings | None = None
    ) -> None:
        super().__init__(bot, timeout=None)
        if settings:
            self.finalize.emoji = custom_emoji(settings.icon_payment_id)

    @discord.ui.button(
        label="Finalizar venda",
        style=discord.ButtonStyle.primary,
        custom_id=CustomID.STAFF_FINALIZE,
    )
    async def finalize(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        await self.bot.workflow.finalize(interaction)


def sale_view(
    bot: "SKStoreBot", status: SaleStatus, settings: GuildSettings | None = None
) -> discord.ui.View | None:
    if status is SaleStatus.WAITING:
        return WaitingSaleView(bot, settings)
    if status is SaleStatus.ANALYSIS:
        return AnalysisSaleView(bot, settings)
    if status is SaleStatus.PAYMENT:
        return PaymentSaleView(bot, settings)
    if status is SaleStatus.PAID:
        return PaidSaleView(bot, settings)
    return None


def persistent_sale_views(bot: "SKStoreBot") -> list[discord.ui.View]:
    return [
        WaitingSaleView(bot),
        AnalysisSaleView(bot),
        PaymentSaleView(bot),
        PaidSaleView(bot),
    ]
