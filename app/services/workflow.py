from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import discord

from app.constants import SaleStatus, TERMINAL_STATUSES
from app.exceptions import (
    DuplicateOperation,
    InvalidTransition,
    PermissionDenied,
    SKStoreError,
)
from app.models import GuildSettings, Sale
from app.utils.embeds import build_sale_embed
from app.utils.money import format_brl
from app.utils.permissions import is_admin, require_staff
from app.utils.text import truncate
from app.utils.validation import ParsedEmail, render_cart_template
from app.views.cart import CustomerCancelView, RemoveAccountView
from app.views.sale import sale_view

if TYPE_CHECKING:
    from app.bot import SKStoreBot


LOGGER = logging.getLogger(__name__)


class WorkflowService:
    def __init__(self, bot: "SKStoreBot") -> None:
        self.bot = bot

    async def _safe_ticket_message(
        self,
        channel: discord.TextChannel,
        sale: Sale,
        content: str,
        operation: str,
    ) -> None:
        try:
            await channel.send(
                content,
                allowed_mentions=discord.AllowedMentions(
                    everyone=False,
                    roles=False,
                    users=[discord.Object(id=sale.customer_id)],
                    replied_user=False,
                ),
            )
        except (discord.Forbidden, discord.HTTPException) as exc:
            LOGGER.warning(
                "Falha ao enviar atualização da venda %s: %s",
                sale.id,
                operation,
            )
            try:
                await self.bot.database.record_technical_failure(
                    guild_id=sale.guild_id,
                    sale_id=sale.id,
                    operation=operation,
                    error_name=type(exc).__name__,
                )
            except Exception:
                LOGGER.exception(
                    "Falha ao registrar erro técnico da venda %s", sale.id
                )

    async def render_terminal(
        self, channel: discord.TextChannel, sale: Sale
    ) -> None:
        try:
            await self.render_sale(channel, sale)
        except Exception as exc:
            LOGGER.exception(
                "Falha ao atualizar a interface terminal da venda %s",
                sale.id,
                exc_info=exc,
            )
            try:
                await self.bot.database.record_technical_failure(
                    guild_id=sale.guild_id,
                    sale_id=sale.id,
                    operation="terminal_render",
                    error_name=type(exc).__name__,
                )
            except Exception:
                LOGGER.exception(
                    "Falha ao registrar erro técnico da venda %s", sale.id
                )

    async def open_sale(
        self,
        interaction: discord.Interaction,
        emails: list[ParsedEmail],
        pix_key: str,
        pix_holder: str,
    ) -> discord.TextChannel:
        guild = interaction.guild
        if guild is None or not isinstance(interaction.user, discord.Member):
            raise SKStoreError("Use este formulário dentro do servidor.")
        settings = await self.bot.database.get_settings(guild.id)
        await self.bot.tickets.validate_configuration(guild, settings)
        sale, created = await self.bot.sales.create_sale(
            guild_id=guild.id,
            customer_id=interaction.user.id,
            emails=emails,
            pix_key=pix_key,
            pix_holder=pix_holder,
            interaction_id=interaction.id,
            settings=settings,
        )
        async with self.bot.sales.locks.hold(("workflow", sale.id)):
            sale = await self.bot.database.get_sale(sale.id) or sale
            if sale.status in TERMINAL_STATUSES:
                raise InvalidTransition(
                    "Esta tentativa foi encerrada. Abra o formulário novamente."
                )
            try:
                channel = await self.bot.tickets.create_or_find(
                    guild, interaction.user, sale, settings
                )
            except Exception as exc:
                await self.bot.sales.mark_creation_failure(
                    sale.id, type(exc).__name__
                )
                await self.bot.logs.flush_sale_events(sale.id)
                raise

            sale = await self.bot.database.get_sale(sale.id) or sale
            await self.render_sale(channel, sale)
            await self._send_cart_notice(channel, interaction.user, sale)
            if created:
                await self.bot.logs.flush_sale_events(sale.id)
            return channel

    async def render_sale(
        self, channel: discord.TextChannel, sale: Sale
    ) -> discord.Message:
        sale = await self.bot.database.get_sale(sale.id) or sale
        settings = await self.bot.database.get_settings(sale.guild_id)
        accounts = await self.bot.database.get_accounts(sale.id)
        embed = build_sale_embed(sale, accounts, settings)
        view = sale_view(self.bot, sale.status, settings)
        message: discord.Message | None = None
        stale_message_id: int | None = None
        if sale.workflow_message_id:
            try:
                message = await channel.fetch_message(sale.workflow_message_id)
            except discord.NotFound:
                message = None
                stale_message_id = sale.workflow_message_id
            except (discord.Forbidden, discord.HTTPException):
                raise
        if message:
            await message.edit(embed=embed, view=view, content=None)
        else:
            message = await channel.send(embed=embed, view=view)
            try:
                await self.bot.sales.attach_workflow_message(
                    sale.id,
                    message.id,
                    stale_message_id=stale_message_id,
                )
            except DuplicateOperation:
                try:
                    await message.delete()
                except (
                    discord.NotFound,
                    discord.Forbidden,
                    discord.HTTPException,
                ):
                    pass
                current = await self.bot.database.get_sale(sale.id)
                if not current or not current.workflow_message_id:
                    raise
                message = await channel.fetch_message(
                    current.workflow_message_id
                )
                await message.edit(embed=embed, view=view, content=None)
        return message

    async def _send_cart_notice(
        self,
        channel: discord.TextChannel,
        customer: discord.User | discord.Member,
        sale: Sale,
    ) -> None:
        settings = await self.bot.database.get_settings(sale.guild_id)
        if not settings.cart_message_enabled or sale.cart_notice_sent_at:
            return
        accounts = await self.bot.database.get_accounts(sale.id)
        quantity = len(accounts)
        ticket_url = f"https://discord.com/channels/{sale.guild_id}/{channel.id}"
        values = {
            "user": customer.mention,
            "quantidade": str(quantity),
            "preco": format_brl(sale.unit_price_cents),
            "total": format_brl(sale.unit_price_cents * quantity),
            "codigo": sale.verification_code,
            "ticket": channel.mention,
        }
        content = render_cart_template(settings.cart_message_text, values)
        content = truncate(content, 2_000)

        notice: discord.Message | None = None
        allowed = discord.AllowedMentions(
            everyone=False, roles=False, users=[customer], replied_user=False
        )
        if settings.cart_message_target in {"ticket", "both"}:
            notice = await channel.send(content, allowed_mentions=allowed)
        if settings.cart_message_target in {"dm", "both"}:
            dm_content = content.replace(channel.mention, ticket_url)
            try:
                await customer.send(
                    dm_content,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except (discord.Forbidden, discord.HTTPException):
                LOGGER.info("DM automática indisponível para venda %s", sale.id)

        delete_at = None
        if notice and settings.cart_message_auto_delete:
            delete_at = (
                datetime.now(UTC)
                + timedelta(seconds=settings.cart_message_delete_delay)
            ).isoformat()
        await self.bot.sales.attach_cart_notice(
            sale.id, notice.id if notice else None, delete_at
        )
        if delete_at:
            self.bot.maintenance.notify()

    async def _sale_for_interaction(self, interaction: discord.Interaction) -> Sale:
        if interaction.channel_id is None:
            raise SKStoreError("Venda não encontrada.")
        sale = await self.bot.database.get_sale_by_channel(interaction.channel_id)
        if not sale:
            raise SKStoreError("Este canal não está ligado a uma venda.")
        return sale

    @staticmethod
    def _require_customer(interaction: discord.Interaction, sale: Sale) -> None:
        if interaction.user.id != sale.customer_id:
            raise PermissionDenied("Este carrinho não pertence a você.")
        if sale.status not in {SaleStatus.WAITING, SaleStatus.ANALYSIS}:
            raise InvalidTransition("O carrinho já está bloqueado.")

    async def handle_cart_edit(
        self, interaction: discord.Interaction, action: str
    ) -> None:
        try:
            sale = await self._sale_for_interaction(interaction)
            self._require_customer(interaction, sale)
            if action == "add":
                from app.modals.cart import AddGmailModal

                await interaction.response.send_modal(
                    AddGmailModal(self.bot, sale.id)
                )
                return
            if action == "pix":
                from app.modals.cart import EditPixModal

                await interaction.response.send_modal(
                    EditPixModal(
                        self.bot, sale.id, sale.pix_key, sale.pix_holder
                    )
                )
                return
            if action == "remove":
                accounts = await self.bot.database.get_accounts(sale.id)
                settings = await self.bot.database.get_settings(sale.guild_id)
                if len(accounts) <= settings.min_accounts:
                    raise InvalidTransition(
                        f"A venda precisa manter {settings.min_accounts} conta(s)."
                    )
                await interaction.response.send_message(
                    "Escolha uma conta para remover.",
                    ephemeral=True,
                    view=RemoveAccountView(
                        self.bot, sale.id, sale.customer_id, accounts
                    ),
                )
                return
            raise SKStoreError("Ação de carrinho inválida.")
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)

    async def request_customer_cancel(
        self, interaction: discord.Interaction
    ) -> None:
        try:
            sale = await self._sale_for_interaction(interaction)
            self._require_customer(interaction, sale)
            settings = await self.bot.database.get_settings(sale.guild_id)
            if not settings.customer_cancellation_enabled:
                raise InvalidTransition(
                    "O cancelamento pelo cliente está desativado."
                )
            await interaction.response.send_message(
                "Cancelar esta venda?",
                ephemeral=True,
                view=CustomerCancelView(
                    self.bot, sale.id, sale.customer_id
                ),
            )
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)

    async def add_accounts(
        self,
        interaction: discord.Interaction,
        sale_id: int,
        emails: list[ParsedEmail],
    ) -> None:
        sale = await self.bot.database.get_sale(sale_id)
        if not sale:
            raise SKStoreError("Venda não encontrada.")
        settings = await self.bot.database.get_settings(sale.guild_id)
        async with self.bot.sales.locks.hold(("workflow", sale.id)):
            sale, changed = await self.bot.sales.add_accounts(
                sale_id=sale.id,
                customer_id=interaction.user.id,
                emails=emails,
                interaction_id=interaction.id,
                settings=settings,
            )
            if isinstance(interaction.channel, discord.TextChannel):
                await self.render_sale(interaction.channel, sale)
            if changed:
                await self.bot.logs.flush_sale_events(sale.id)

    async def remove_account(
        self,
        interaction: discord.Interaction,
        sale_id: int,
        account_id: int,
    ) -> None:
        sale = await self.bot.database.get_sale(sale_id)
        if not sale:
            raise SKStoreError("Venda não encontrada.")
        settings = await self.bot.database.get_settings(sale.guild_id)
        async with self.bot.sales.locks.hold(("workflow", sale.id)):
            sale, changed = await self.bot.sales.remove_account(
                sale_id=sale.id,
                account_id=account_id,
                customer_id=interaction.user.id,
                interaction_id=interaction.id,
                settings=settings,
            )
            if isinstance(interaction.channel, discord.TextChannel):
                await self.render_sale(interaction.channel, sale)
            if changed:
                await self.bot.logs.flush_sale_events(sale.id)

    async def edit_pix(
        self,
        interaction: discord.Interaction,
        sale_id: int,
        pix_key: str,
        pix_holder: str,
    ) -> None:
        async with self.bot.sales.locks.hold(("workflow", sale_id)):
            sale, changed = await self.bot.sales.edit_pix(
                sale_id=sale_id,
                customer_id=interaction.user.id,
                pix_key=pix_key,
                pix_holder=pix_holder,
                interaction_id=interaction.id,
            )
            if isinstance(interaction.channel, discord.TextChannel):
                await self.render_sale(interaction.channel, sale)
            if changed:
                await self.bot.logs.flush_sale_events(sale.id)

    async def cancel_by_customer(
        self, interaction: discord.Interaction, sale_id: int
    ) -> None:
        sale = await self.bot.database.get_sale(sale_id)
        if not sale:
            raise SKStoreError("Venda não encontrada.")
        settings = await self.bot.database.get_settings(sale.guild_id)
        async with self.bot.sales.locks.hold(("workflow", sale.id)):
            sale, changed = await self.bot.sales.cancel_by_customer(
                sale_id=sale.id,
                customer_id=interaction.user.id,
                interaction_id=interaction.id,
                settings=settings,
            )
            if isinstance(interaction.channel, discord.TextChannel):
                await self.render_terminal(interaction.channel, sale)
                if changed:
                    await self._safe_ticket_message(
                        interaction.channel,
                        sale,
                        f"<@{sale.customer_id}>, sua venda foi cancelada.",
                        "customer_cancel_notice",
                    )
                await self.bot.completion.finish(
                    interaction.channel, sale, settings
                )

    async def lock_ticket(
        self,
        channel: discord.TextChannel,
        sale: Sale,
        settings: GuildSettings,
    ) -> None:
        guild = channel.guild
        try:
            customer = guild.get_member(sale.customer_id)
            if customer is None:
                customer = await guild.fetch_member(sale.customer_id)
            await channel.set_permissions(
                customer,
                view_channel=True,
                send_messages=False,
                read_message_history=True,
                reason=f"SK Store: venda #{sale.id:04d} encerrada",
            )
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
            LOGGER.warning("Não foi possível bloquear cliente da venda %s", sale.id)
            await self.bot.database.record_technical_failure(
                guild_id=sale.guild_id,
                sale_id=sale.id,
                operation="customer_ticket_lock",
                error_name=type(exc).__name__,
            )
        staff_role = guild.get_role(settings.staff_role_id or 0)
        if staff_role:
            try:
                await channel.set_permissions(
                    staff_role,
                    view_channel=True,
                    send_messages=False,
                    read_message_history=True,
                    reason=f"SK Store: venda #{sale.id:04d} encerrada",
                )
            except (discord.Forbidden, discord.HTTPException) as exc:
                LOGGER.warning("Não foi possível bloquear Staff da venda %s", sale.id)
                await self.bot.database.record_technical_failure(
                    guild_id=sale.guild_id,
                    sale_id=sale.id,
                    operation="staff_ticket_lock",
                    error_name=type(exc).__name__,
                )
        else:
            await self.bot.database.record_technical_failure(
                guild_id=sale.guild_id,
                sale_id=sale.id,
                operation="staff_ticket_lock",
                error_name="RoleNotFound",
            )
        prefix = (
            "finalizado-"
            if sale.status is SaleStatus.FINALIZED
            else "encerrado-"
        )
        if settings.rename_closed_tickets and not channel.name.startswith(prefix):
            try:
                await channel.edit(
                    name=f"{prefix}{channel.name}"[:100],
                    reason=f"SK Store: venda #{sale.id:04d} encerrada",
                )
            except (discord.Forbidden, discord.HTTPException) as exc:
                LOGGER.warning("Não foi possível renomear venda %s", sale.id)
                await self.bot.database.record_technical_failure(
                    guild_id=sale.guild_id,
                    sale_id=sale.id,
                    operation="ticket_rename",
                    error_name=type(exc).__name__,
                )

    async def claim(self, interaction: discord.Interaction) -> None:
        try:
            sale = await self._sale_for_interaction(interaction)
            member, settings = await self._staff_context(interaction, sale)
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            async with self.bot.sales.locks.hold(("workflow", sale.id)):
                sale, changed = await self.bot.sales.claim(
                    sale_id=sale.id,
                    staff_id=member.id,
                    interaction_id=interaction.id,
                )
                if isinstance(interaction.channel, discord.TextChannel):
                    await self.render_sale(interaction.channel, sale)
                    if changed:
                        await self._safe_ticket_message(
                            interaction.channel,
                            sale,
                            f"<@{sale.customer_id}>, seu atendimento foi assumido "
                            f"por <@{member.id}>.",
                            "claim_notice",
                        )
                if changed:
                    await self.bot.logs.flush_sale_events(sale.id)
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.followup.send("Venda assumida.", ephemeral=True)

    async def _staff_context(
        self, interaction: discord.Interaction, sale: Sale
    ) -> tuple[discord.Member, GuildSettings]:
        if interaction.guild is None or not isinstance(
            interaction.user, discord.Member
        ):
            raise PermissionDenied("Use esta ação dentro do servidor.")
        settings = await self.bot.database.get_settings(sale.guild_id)
        require_staff(interaction.user, settings)
        return interaction.user, settings

    async def handle_staff_action(
        self, interaction: discord.Interaction, action: str
    ) -> None:
        try:
            sale = await self._sale_for_interaction(interaction)
            await self._staff_context(interaction, sale)
            if action == "notify":
                from app.modals.staff import NotifyCustomerModal

                await interaction.response.send_modal(
                    NotifyCustomerModal(self.bot, sale.id)
                )
                return
            if action == "close":
                from app.modals.staff import CloseSaleModal

                await interaction.response.send_modal(
                    CloseSaleModal(self.bot, sale.id)
                )
                return
            if action == "back":
                await interaction.response.defer(ephemeral=True, thinking=True)
                await self.back_to_analysis(interaction, sale.id)
                await interaction.followup.send(
                    "Venda devolvida para análise.", ephemeral=True
                )
                return
            raise SKStoreError("Ação da equipe inválida.")
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)

    async def continue_to_payment(
        self, interaction: discord.Interaction
    ) -> None:
        try:
            sale = await self._sale_for_interaction(interaction)
            member, settings = await self._staff_context(interaction, sale)
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            async with self.bot.sales.locks.hold(("workflow", sale.id)):
                sale, changed = await self.bot.sales.continue_to_payment(
                    sale_id=sale.id,
                    staff_id=member.id,
                    is_admin=is_admin(member, settings),
                    interaction_id=interaction.id,
                )
                if isinstance(interaction.channel, discord.TextChannel):
                    await self.render_sale(interaction.channel, sale)
                if changed:
                    await self.bot.logs.flush_sale_events(sale.id)
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.followup.send(
            "Etapa de pagamento aberta.", ephemeral=True
        )

    async def back_to_analysis(
        self, interaction: discord.Interaction, sale_id: int
    ) -> None:
        sale = await self.bot.database.get_sale(sale_id)
        if not sale:
            raise SKStoreError("Venda não encontrada.")
        member, settings = await self._staff_context(interaction, sale)
        async with self.bot.sales.locks.hold(("workflow", sale.id)):
            sale, changed = await self.bot.sales.back_to_analysis(
                sale_id=sale.id,
                staff_id=member.id,
                is_admin=is_admin(member, settings),
                interaction_id=interaction.id,
            )
            if isinstance(interaction.channel, discord.TextChannel):
                await self.render_sale(interaction.channel, sale)
            if changed:
                await self.bot.logs.flush_sale_events(sale.id)

    async def confirm_payment(self, interaction: discord.Interaction) -> None:
        try:
            sale = await self._sale_for_interaction(interaction)
            member, settings = await self._staff_context(interaction, sale)
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            async with self.bot.sales.locks.hold(("workflow", sale.id)):
                sale, changed = await self.bot.sales.confirm_payment(
                    sale_id=sale.id,
                    staff_id=member.id,
                    is_admin=is_admin(member, settings),
                    interaction_id=interaction.id,
                )
                if isinstance(interaction.channel, discord.TextChannel):
                    await self.render_sale(interaction.channel, sale)
                    if changed:
                        await self._safe_ticket_message(
                            interaction.channel,
                            sale,
                            f"<@{sale.customer_id}>, pagamento confirmado.",
                            "payment_notice",
                        )
                if changed:
                    await self.bot.logs.flush_sale_events(sale.id)
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.followup.send(
            "Pagamento confirmado.", ephemeral=True
        )

    async def finalize(self, interaction: discord.Interaction) -> None:
        try:
            sale = await self._sale_for_interaction(interaction)
            member, settings = await self._staff_context(interaction, sale)
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            async with self.bot.sales.locks.hold(("workflow", sale.id)):
                sale, changed = await self.bot.sales.finalize(
                    sale_id=sale.id,
                    staff_id=member.id,
                    is_admin=is_admin(member, settings),
                    interaction_id=interaction.id,
                )
                if isinstance(interaction.channel, discord.TextChannel):
                    if changed:
                        await self._safe_ticket_message(
                            interaction.channel,
                            sale,
                            f"<@{sale.customer_id}>, sua venda foi finalizada.",
                            "finalized_notice",
                        )
                    await self.render_terminal(interaction.channel, sale)
                    await self.bot.completion.finish(
                        interaction.channel, sale, settings
                    )
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.followup.send("Venda finalizada.", ephemeral=True)

    async def notify_customer(
        self,
        interaction: discord.Interaction,
        sale_id: int,
        message: str,
    ) -> bool:
        if not 2 <= len(message) <= 500:
            raise SKStoreError("Escreva uma mensagem curta.")
        async with self.bot.sales.locks.hold(("workflow", sale_id)):
            sale = await self.bot.database.get_sale(sale_id)
            if not sale:
                raise SKStoreError("Venda não encontrada.")
            member, settings = await self._staff_context(interaction, sale)
            if not settings.dm_notifications_enabled:
                raise InvalidTransition("As notificações por DM estão desativadas.")
            if sale.status not in {
                SaleStatus.WAITING,
                SaleStatus.ANALYSIS,
                SaleStatus.PAYMENT,
            }:
                raise InvalidTransition("Esta venda não aceita notificações.")
            if (
                sale.status is not SaleStatus.WAITING
                and sale.responsible_staff_id != member.id
                and not is_admin(member, settings)
            ):
                raise PermissionDenied(
                    "Somente o atendente responsável pode avançar."
                )
            ticket_url = (
                f"https://discord.com/channels/{sale.guild_id}/{sale.channel_id}"
            )
            try:
                customer = self.bot.get_user(sale.customer_id)
                if customer is None:
                    customer = await self.bot.fetch_user(sale.customer_id)
                await customer.send(
                    f"<@{sale.customer_id}>, {message}\n\n"
                    f"Volte ao atendimento: {ticket_url}",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except (discord.Forbidden, discord.NotFound):
                return False
            except discord.HTTPException:
                raise
            _, changed = await self.bot.sales.record_customer_notified(
                sale_id=sale.id,
                staff_id=member.id,
                is_admin=is_admin(member, settings),
                interaction_id=interaction.id,
            )
            if changed:
                await self.bot.logs.flush_sale_events(sale.id)
            return True

    async def close_by_staff(
        self,
        interaction: discord.Interaction,
        sale_id: int,
        reason: str,
    ) -> None:
        sale = await self.bot.database.get_sale(sale_id)
        if not sale:
            raise SKStoreError("Venda não encontrada.")
        member, settings = await self._staff_context(interaction, sale)
        reason = " ".join(reason.split())
        if not 2 <= len(reason) <= 500:
            raise SKStoreError("Informe um motivo curto.")
        async with self.bot.sales.locks.hold(("workflow", sale.id)):
            sale, changed = await self.bot.sales.close_by_staff(
                sale_id=sale.id,
                staff_id=member.id,
                is_admin=is_admin(member, settings),
                reason=reason,
                interaction_id=interaction.id,
            )
            if isinstance(interaction.channel, discord.TextChannel):
                if changed:
                    await self._safe_ticket_message(
                        interaction.channel,
                        sale,
                        f"<@{sale.customer_id}>, sua venda foi encerrada.\n"
                        f"Motivo: {reason}",
                        "staff_close_notice",
                    )
                await self.render_terminal(interaction.channel, sale)
                await self.bot.completion.finish(
                    interaction.channel, sale, settings
                )
