from __future__ import annotations

import logging
import re

import discord

from app.constants import SALE_TOPIC_PREFIX, TERMINAL_STATUSES
from app.database import Database
from app.exceptions import (
    DuplicateOperation,
    MissingConfiguration,
    ResourceUnavailable,
)
from app.models import GuildSettings, Sale
from app.services.sales import SaleService


LOGGER = logging.getLogger(__name__)
_SALE_TOPIC_RE = re.compile(
    r"^Atendimento privado · Venda #(?P<sale_id>\d+) · SK Store$"
)


def format_sale_topic(sale_id: int) -> str:
    return f"Atendimento privado · Venda #{sale_id:04d} · SK Store"


def topic_matches_sale(topic: str | None, sale_id: int) -> bool:
    if not topic:
        return False
    marker = topic.partition("|")[0].strip()
    if marker == f"{SALE_TOPIC_PREFIX}{sale_id}":
        return True
    match = _SALE_TOPIC_RE.fullmatch(topic.strip())
    return bool(match and int(match.group("sale_id")) == sale_id)


class TicketService:
    def __init__(self, database: Database, sales: SaleService) -> None:
        self.db = database
        self.sales = sales

    @staticmethod
    def _overwrite_matches(
        overwrite: discord.PermissionOverwrite,
        expected: dict[str, bool],
    ) -> bool:
        return all(getattr(overwrite, key) is value for key, value in expected.items())

    async def _sync_access(
        self,
        channel: discord.TextChannel,
        guild: discord.Guild,
        customer: discord.Member | None,
        sale: Sale,
        settings: GuildSettings,
    ) -> None:
        staff_role = guild.get_role(settings.staff_role_id or 0)
        admin_role = guild.get_role(settings.admin_role_id or 0)
        bot_member = guild.me
        if staff_role is None or admin_role is None or bot_member is None:
            raise MissingConfiguration("Confira os cargos configurados em /botconfig.")

        reason = f"SK Store: permissões da venda #{sale.id:04d}"
        locked = sale.status in TERMINAL_STATUSES
        expected: list[tuple[discord.Role | discord.Member, dict[str, bool]]] = [
            (guild.default_role, {"view_channel": False}),
            (
                staff_role,
                {
                    "view_channel": True,
                    "send_messages": not locked,
                    "read_message_history": True,
                    "attach_files": True,
                },
            ),
            (
                admin_role,
                {
                    "view_channel": True,
                    "send_messages": True,
                    "read_message_history": True,
                    "attach_files": True,
                },
            ),
            (
                bot_member,
                {
                    "view_channel": True,
                    "send_messages": True,
                    "read_message_history": True,
                    "embed_links": True,
                    "attach_files": True,
                    "manage_channels": True,
                },
            ),
        ]
        if customer is not None:
            expected.append(
                (
                    customer,
                    {
                        "view_channel": True,
                        "send_messages": not locked,
                        "read_message_history": True,
                        "attach_files": True,
                    },
                )
            )

        allowed_role_ids = {
            guild.default_role.id,
            staff_role.id,
            admin_role.id,
        }
        for target, overwrite in channel.overwrites.items():
            if (
                isinstance(target, discord.Role)
                and target.id not in allowed_role_ids
                and overwrite.view_channel is True
            ):
                await channel.set_permissions(target, overwrite=None, reason=reason)

        for target, values in expected:
            current = channel.overwrites_for(target)
            if self._overwrite_matches(current, values):
                continue
            await channel.set_permissions(
                target,
                overwrite=discord.PermissionOverwrite(**values),
                reason=reason,
            )

        expected_topic = format_sale_topic(sale.id)
        if channel.topic != expected_topic:
            try:
                await channel.edit(topic=expected_topic, reason=reason)
            except (discord.Forbidden, discord.HTTPException):
                LOGGER.warning(
                    "Não foi possível atualizar o tópico da venda %s",
                    sale.id,
                )

    async def sync_guild_permissions(
        self, guild: discord.Guild, settings: GuildSettings
    ) -> int:
        synced = 0
        after_id = 0
        customers: dict[int, discord.Member | None] = {}
        while True:
            sales = await self.db.get_ticket_sales(
                guild.id, after_id=after_id, limit=100
            )
            if not sales:
                break
            for sale in sales:
                after_id = sale.id
                if not sale.channel_id:
                    continue
                channel = guild.get_channel(sale.channel_id)
                if channel is None:
                    try:
                        channel = await guild.fetch_channel(sale.channel_id)
                    except discord.NotFound:
                        continue
                if not isinstance(channel, discord.TextChannel):
                    continue
                if sale.customer_id not in customers:
                    customer = guild.get_member(sale.customer_id)
                    if customer is None:
                        try:
                            customer = await guild.fetch_member(sale.customer_id)
                        except discord.NotFound:
                            customer = None
                    customers[sale.customer_id] = customer
                await self._sync_access(
                    channel,
                    guild,
                    customers[sale.customer_id],
                    sale,
                    settings,
                )
                synced += 1
        return synced

    async def _category(
        self, guild: discord.Guild, category_id: int | None
    ) -> discord.CategoryChannel:
        if not category_id:
            raise MissingConfiguration("Configure a categoria de tickets em /botconfig.")
        channel = guild.get_channel(category_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(category_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as exc:
                raise ResourceUnavailable(
                    "A categoria de tickets não está disponível."
                ) from exc
        if not isinstance(channel, discord.CategoryChannel):
            raise MissingConfiguration(
                "O destino dos tickets precisa ser uma categoria."
            )
        return channel

    async def validate_configuration(
        self, guild: discord.Guild, settings: GuildSettings
    ) -> discord.CategoryChannel:
        category = await self._category(guild, settings.ticket_category_id)
        staff_role = guild.get_role(settings.staff_role_id or 0)
        if staff_role is None or staff_role.id == guild.default_role.id:
            raise MissingConfiguration("Configure um cargo de Staff em /botconfig.")
        admin_role = guild.get_role(settings.admin_role_id or 0)
        if admin_role is None or admin_role.id == guild.default_role.id:
            raise MissingConfiguration(
                "Configure um cargo de Admin/Manager em /botconfig."
            )
        if staff_role.id == admin_role.id:
            raise MissingConfiguration("Use cargos diferentes para Staff e Admin.")
        if guild.me is None:
            raise ResourceUnavailable("Não consegui localizar meu usuário no servidor.")
        if not (
            guild.me.top_role > staff_role
            and guild.me.top_role > admin_role
        ):
            raise ResourceUnavailable(
                "O cargo do bot precisa ficar acima dos cargos de Staff e Admin."
            )
        permissions = category.permissions_for(guild.me)
        required_permissions = {
            "ver canais": permissions.view_channel,
            "enviar mensagens": permissions.send_messages,
            "inserir links": permissions.embed_links,
            "anexar arquivos": permissions.attach_files,
            "ler histórico": permissions.read_message_history,
            "gerenciar canais": permissions.manage_channels,
            "gerenciar cargos": permissions.manage_roles,
        }
        missing = [
            label
            for label, enabled in required_permissions.items()
            if not enabled
        ]
        if missing:
            raise ResourceUnavailable(
                "Faltam permissões na categoria: " + ", ".join(missing) + "."
            )
        return category

    async def create_or_find(
        self,
        guild: discord.Guild,
        customer: discord.Member | None,
        sale: Sale,
        settings: GuildSettings,
    ) -> discord.TextChannel:
        category = await self.validate_configuration(guild, settings)
        stale_channel = False
        if sale.channel_id:
            existing = guild.get_channel(sale.channel_id)
            if isinstance(existing, discord.TextChannel):
                await self._sync_access(
                    existing, guild, customer, sale, settings
                )
                return existing
            try:
                fetched = await guild.fetch_channel(sale.channel_id)
            except discord.NotFound:
                fetched = None
            except (discord.Forbidden, discord.HTTPException) as exc:
                raise ResourceUnavailable(
                    "Não consegui consultar o ticket salvo."
                ) from exc
            if isinstance(fetched, discord.TextChannel):
                await self._sync_access(
                    fetched, guild, customer, sale, settings
                )
                return fetched
            stale_channel = True

        for channel in category.text_channels:
            if topic_matches_sale(channel.topic, sale.id):
                await self.sales.attach_channel(
                    sale.id,
                    channel.id,
                    channel.name,
                    replace_existing=stale_channel,
                )
                await self._sync_access(
                    channel, guild, customer, sale, settings
                )
                return channel

        staff_role = guild.get_role(settings.staff_role_id or 0)
        admin_role = guild.get_role(settings.admin_role_id or 0)
        bot_member = guild.me
        if staff_role is None or admin_role is None or bot_member is None:
            raise MissingConfiguration("Confira os cargos configurados em /botconfig.")
        if customer is None:
            raise ResourceUnavailable(
                "O cliente não está mais no servidor e o ticket não existe."
            )

        overwrites: dict[
            discord.Role | discord.Member,
            discord.PermissionOverwrite,
        ] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            customer: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            ),
            staff_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            ),
            admin_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
            ),
            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                embed_links=True,
                attach_files=True,
                manage_channels=True,
            ),
        }
        name = sale.ticket_name or f"gmail-{sale.id:04d}"
        channel = await guild.create_text_channel(
            name=name,
            category=category,
            overwrites=overwrites,
            topic=format_sale_topic(sale.id),
            reason=f"SK Store: venda #{sale.id:04d}",
        )
        try:
            await self.sales.attach_channel(
                sale.id,
                channel.id,
                channel.name,
                replace_existing=stale_channel,
            )
        except DuplicateOperation:
            current = await self.db.get_sale(sale.id)
            if not current or not current.channel_id:
                raise
            try:
                await channel.delete(
                    reason=f"SK Store: ticket duplicado da venda #{sale.id:04d}"
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
            existing = guild.get_channel(current.channel_id)
            if existing is None:
                try:
                    existing = await guild.fetch_channel(current.channel_id)
                except (
                    discord.NotFound,
                    discord.Forbidden,
                    discord.HTTPException,
                ) as exc:
                    raise ResourceUnavailable(
                        "A venda já possui um ticket, mas ele não está disponível."
                    ) from exc
            if isinstance(existing, discord.TextChannel):
                return existing
            raise ResourceUnavailable(
                "O ticket salvo para esta venda não é um canal de texto."
            )
        except Exception:
            try:
                await channel.delete(
                    reason=f"SK Store: criação incompleta da venda #{sale.id:04d}"
                )
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass
            raise
        return channel
