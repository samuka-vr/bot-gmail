from __future__ import annotations

from typing import TYPE_CHECKING

import discord

from app.exceptions import ValidationError
from app.modals.configuration import (
    BrandAppearanceModal,
    CartMessageModal,
    GeneralSettingsModal,
    IconsAppearanceModal,
    PanelActionModal,
    PanelTextsModal,
    PricesModal,
)
from app.models import GuildSettings
from app.utils.config_embeds import (
    build_config_embed,
    build_section_embed,
    mention_channel,
    mention_role,
)
from app.utils.money import format_brl
from app.utils.permissions import is_admin
from app.utils.validation import render_cart_template

if TYPE_CHECKING:
    from app.bot import SKStoreBot


async def show_main(
    interaction: discord.Interaction, bot: "SKStoreBot", owner_id: int
) -> None:
    if interaction.guild is None:
        return
    settings = await bot.database.get_settings(interaction.guild.id)
    await interaction.response.edit_message(
        embed=build_config_embed(settings),
        view=BotConfigView(bot, owner_id),
    )


class ConfigView(discord.ui.View):
    def __init__(
        self,
        bot: "SKStoreBot",
        owner_id: int,
        *,
        add_back: bool = False,
        back_row: int | None = None,
    ) -> None:
        super().__init__(timeout=900)
        self.bot = bot
        self.owner_id = owner_id
        if add_back:
            button = discord.ui.Button(
                label="Voltar",
                style=discord.ButtonStyle.secondary,
                custom_id=f"sk:config:back:{self.__class__.__name__.lower()}",
                row=back_row,
            )
            button.callback = self.back
            self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Esta configuração não pertence a você.", ephemeral=True
            )
            return False
        if interaction.guild is None or not isinstance(
            interaction.user, discord.Member
        ):
            return False
        settings = await self.bot.database.get_settings(interaction.guild.id)
        if not is_admin(interaction.user, settings):
            await interaction.response.send_message(
                "Você não pode configurar este bot.", ephemeral=True
            )
            return False
        return True

    async def back(self, interaction: discord.Interaction) -> None:
        await show_main(interaction, self.bot, self.owner_id)

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: Exception,
        item: discord.ui.Item[discord.ui.View],
    ) -> None:
        await self.bot.handle_user_exception(interaction, error)


class MainConfigSelect(discord.ui.Select):
    def __init__(self, bot: "SKStoreBot", owner_id: int) -> None:
        super().__init__(
            placeholder="Configurar bot",
            custom_id="sk:config:main:select",
            options=[
                discord.SelectOption(label="Painel", value="panel"),
                discord.SelectOption(label="Canais", value="channels"),
                discord.SelectOption(label="Cargos", value="roles"),
                discord.SelectOption(label="Preços", value="prices"),
                discord.SelectOption(label="Aparência", value="appearance"),
                discord.SelectOption(
                    label="Mensagem do carrinho", value="cart_message"
                ),
                discord.SelectOption(label="Logs", value="logs"),
                discord.SelectOption(
                    label="Configurações gerais", value="general"
                ),
                discord.SelectOption(
                    label="Publicar / Atualizar painel", value="publish"
                ),
                discord.SelectOption(label="Diagnóstico", value="diagnostic"),
            ],
        )
        self.bot = bot
        self.owner_id = owner_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        settings = await self.bot.database.get_settings(interaction.guild.id)
        action = self.values[0]
        if action == "panel":
            await interaction.response.edit_message(
                embed=build_section_embed(
                    settings,
                    "Painel",
                    "Edite os textos ou o destaque do painel público.",
                ),
                view=PanelConfigView(self.bot, self.owner_id, settings),
            )
        elif action == "channels":
            await interaction.response.edit_message(
                embed=channels_embed(settings),
                view=ChannelsConfigView(self.bot, self.owner_id, settings),
            )
        elif action == "roles":
            await interaction.response.edit_message(
                embed=roles_embed(settings),
                view=RolesConfigView(self.bot, self.owner_id, settings),
            )
        elif action == "prices":
            await interaction.response.send_modal(PricesModal(self.bot, settings))
        elif action == "appearance":
            await interaction.response.edit_message(
                embed=build_section_embed(
                    settings,
                    "Aparência",
                    f"Cor atual: #{settings.embed_color:06X}\n"
                    "Logo, banner e ícones customizados são opcionais.",
                ),
                view=AppearanceConfigView(self.bot, self.owner_id, settings),
            )
        elif action == "cart_message":
            await interaction.response.edit_message(
                embed=cart_message_embed(settings),
                view=CartMessageConfigView(self.bot, self.owner_id, settings),
            )
        elif action == "logs":
            await interaction.response.edit_message(
                embed=logs_embed(settings),
                view=LogsConfigView(self.bot, self.owner_id, settings),
            )
        elif action == "general":
            await interaction.response.edit_message(
                embed=general_embed(settings),
                view=GeneralConfigView(self.bot, self.owner_id, settings),
            )
        elif action == "publish":
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                message, created = await self.bot.panels.publish(
                    interaction.guild, interaction.user.id
                )
                await self.bot.configurations.update(
                    guild_id=interaction.guild.id,
                    values={"panel_message_id": str(message.id)},
                    actor_id=interaction.user.id,
                    interaction_id=interaction.id,
                )
            except Exception as exc:
                await self.bot.handle_user_exception(interaction, exc)
                return
            verb = "publicado" if created else "atualizado"
            await interaction.followup.send(
                f"Painel {verb}: {message.jump_url}", ephemeral=True
            )
        elif action == "diagnostic":
            await interaction.response.defer(ephemeral=True, thinking=True)
            try:
                embed = await self.bot.diagnostics.build(interaction.guild)
            except Exception as exc:
                await self.bot.handle_user_exception(interaction, exc)
                return
            await interaction.edit_original_response(
                embed=embed,
                view=BotConfigView(self.bot, self.owner_id),
            )


class BotConfigView(ConfigView):
    def __init__(self, bot: "SKStoreBot", owner_id: int) -> None:
        super().__init__(bot, owner_id)
        self.add_item(MainConfigSelect(bot, owner_id))


class PanelConfigView(ConfigView):
    def __init__(
        self, bot: "SKStoreBot", owner_id: int, settings: GuildSettings
    ) -> None:
        super().__init__(bot, owner_id, add_back=True, back_row=1)
        self.settings = settings
        texts = discord.ui.Button(
            label="Editar textos",
            style=discord.ButtonStyle.secondary,
            custom_id="sk:config:panel:texts_button",
            row=0,
        )
        action = discord.ui.Button(
            label="Editar destaque",
            style=discord.ButtonStyle.secondary,
            custom_id="sk:config:panel:action_button",
            row=0,
        )
        texts.callback = self.edit_texts
        action.callback = self.edit_action
        self.add_item(texts)
        self.add_item(action)

    async def edit_texts(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            PanelTextsModal(self.bot, self.settings)
        )

    async def edit_action(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            PanelActionModal(self.bot, self.settings)
        )


def channels_embed(settings: GuildSettings) -> discord.Embed:
    return build_section_embed(
        settings,
        "Canais",
        f"Painel: {mention_channel(settings.panel_channel_id)}\n"
        f"Categoria: {mention_channel(settings.ticket_category_id)}\n"
        f"Logs: {mention_channel(settings.logs_channel_id)}\n"
        f"Transcripts: {mention_channel(settings.transcript_channel_id)}",
    )


class SettingChannelSelect(discord.ui.ChannelSelect):
    def __init__(
        self,
        bot: "SKStoreBot",
        owner_id: int,
        setting_key: str,
        placeholder: str,
        channel_types: list[discord.ChannelType],
        row: int,
        custom_id_prefix: str = "sk:config:channel",
    ) -> None:
        super().__init__(
            placeholder=placeholder,
            channel_types=channel_types,
            min_values=1,
            max_values=1,
            custom_id=f"{custom_id_prefix}:{setting_key}",
            row=row,
        )
        self.bot = bot
        self.owner_id = owner_id
        self.setting_key = setting_key

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        await interaction.response.defer()
        try:
            settings = await self.bot.configurations.update(
                guild_id=interaction.guild.id,
                values={self.setting_key: str(self.values[0].id)},
                actor_id=interaction.user.id,
                interaction_id=interaction.id,
            )
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.edit_original_response(
            embed=channels_embed(settings),
            view=ChannelsConfigView(self.bot, self.owner_id, settings),
        )


class ChannelsConfigView(ConfigView):
    def __init__(
        self, bot: "SKStoreBot", owner_id: int, settings: GuildSettings
    ) -> None:
        super().__init__(bot, owner_id, add_back=True, back_row=4)
        self.add_item(
            SettingChannelSelect(
                bot,
                owner_id,
                "panel_channel_id",
                "Canal do painel",
                [discord.ChannelType.text],
                0,
            )
        )
        self.add_item(
            SettingChannelSelect(
                bot,
                owner_id,
                "ticket_category_id",
                "Categoria dos tickets",
                [discord.ChannelType.category],
                1,
            )
        )
        self.add_item(
            SettingChannelSelect(
                bot,
                owner_id,
                "logs_channel_id",
                "Canal de logs",
                [discord.ChannelType.text],
                2,
            )
        )
        self.add_item(
            SettingChannelSelect(
                bot,
                owner_id,
                "transcript_channel_id",
                "Canal de transcripts",
                [discord.ChannelType.text],
                3,
            )
        )


def roles_embed(settings: GuildSettings) -> discord.Embed:
    return build_section_embed(
        settings,
        "Cargos",
        f"Staff: {mention_role(settings.staff_role_id)}\n"
        f"Admin/Manager: {mention_role(settings.admin_role_id)}",
    )


class SettingRoleSelect(discord.ui.RoleSelect):
    def __init__(
        self,
        bot: "SKStoreBot",
        owner_id: int,
        setting_key: str,
        placeholder: str,
        row: int,
    ) -> None:
        super().__init__(
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            custom_id=f"sk:config:role:{setting_key}",
            row=row,
        )
        self.bot = bot
        self.owner_id = owner_id
        self.setting_key = setting_key

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        selected = self.values[0]
        if selected.id == interaction.guild.default_role.id:
            raise ValidationError("Escolha um cargo diferente de @everyone.")
        current = await self.bot.database.get_settings(interaction.guild.id)
        other_role_id = (
            current.admin_role_id
            if self.setting_key == "staff_role_id"
            else current.staff_role_id
        )
        if other_role_id == selected.id:
            raise ValidationError("Use cargos diferentes para Staff e Admin.")
        bot_member = interaction.guild.me
        if bot_member is None or not bot_member.top_role > selected:
            raise ValidationError(
                "O cargo do bot precisa ficar acima do cargo escolhido."
            )
        await interaction.response.defer()
        try:
            settings = await self.bot.configurations.update(
                guild_id=interaction.guild.id,
                values={self.setting_key: str(selected.id)},
                actor_id=interaction.user.id,
                interaction_id=interaction.id,
            )
            staff_role = interaction.guild.get_role(settings.staff_role_id or 0)
            admin_role = interaction.guild.get_role(settings.admin_role_id or 0)
            if staff_role and admin_role:
                await self.bot.tickets.sync_guild_permissions(
                    interaction.guild, settings
                )
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.edit_original_response(
            embed=roles_embed(settings),
            view=RolesConfigView(self.bot, self.owner_id, settings),
        )


class RolesConfigView(ConfigView):
    def __init__(
        self, bot: "SKStoreBot", owner_id: int, settings: GuildSettings
    ) -> None:
        super().__init__(bot, owner_id, add_back=True, back_row=2)
        self.add_item(
            SettingRoleSelect(
                bot, owner_id, "staff_role_id", "Cargo de Staff", 0
            )
        )
        self.add_item(
            SettingRoleSelect(
                bot,
                owner_id,
                "admin_role_id",
                "Cargo de Admin/Manager",
                1,
            )
        )


class AppearanceConfigView(ConfigView):
    def __init__(
        self, bot: "SKStoreBot", owner_id: int, settings: GuildSettings
    ) -> None:
        super().__init__(bot, owner_id, add_back=True, back_row=1)
        self.settings = settings
        brand = discord.ui.Button(
            label="Marca",
            style=discord.ButtonStyle.secondary,
            custom_id="sk:config:appearance:brand_button",
            row=0,
        )
        icons = discord.ui.Button(
            label="Ícones",
            style=discord.ButtonStyle.secondary,
            custom_id="sk:config:appearance:icons_button",
            row=0,
        )
        brand.callback = self.edit_brand
        icons.callback = self.edit_icons
        self.add_item(brand)
        self.add_item(icons)

    async def edit_brand(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            BrandAppearanceModal(self.bot, self.settings)
        )

    async def edit_icons(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            IconsAppearanceModal(self.bot, self.settings)
        )


def cart_message_embed(settings: GuildSettings) -> discord.Embed:
    target_label = {
        "ticket": "Ticket",
        "dm": "DM",
        "both": "Ticket e DM",
    }.get(settings.cart_message_target, "Inválido")
    preview = render_cart_template(
        settings.cart_message_text,
        {
            "user": "@cliente",
            "quantidade": "3",
            "preco": format_brl(settings.unit_price_cents),
            "total": format_brl(settings.unit_price_cents * 3),
            "codigo": "SK-48321",
            "ticket": "#gmail-0042",
        },
    )[:700]
    return build_section_embed(
        settings,
        "Mensagem do carrinho",
        f"Estado: {'Ativa' if settings.cart_message_enabled else 'Desativada'}\n"
        f"Destino: {target_label}\n"
        f"Auto-delete: {'Ativo' if settings.cart_message_auto_delete else 'Desativado'}\n\n"
        f"Prévia:\n{preview}",
    )


class CartTargetSelect(discord.ui.Select):
    def __init__(
        self, bot: "SKStoreBot", owner_id: int, settings: GuildSettings
    ) -> None:
        options = [
            discord.SelectOption(
                label="No ticket", value="ticket", default=settings.cart_message_target == "ticket"
            ),
            discord.SelectOption(
                label="Na DM", value="dm", default=settings.cart_message_target == "dm"
            ),
            discord.SelectOption(
                label="Ticket e DM", value="both", default=settings.cart_message_target == "both"
            ),
        ]
        super().__init__(
            placeholder="Destino da mensagem",
            options=options,
            custom_id="sk:config:cart:target",
            row=0,
        )
        self.bot = bot
        self.owner_id = owner_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        await interaction.response.defer()
        settings = await self.bot.configurations.update(
            guild_id=interaction.guild.id,
            values={"cart_message_target": self.values[0]},
            actor_id=interaction.user.id,
            interaction_id=interaction.id,
        )
        await interaction.edit_original_response(
            embed=cart_message_embed(settings),
            view=CartMessageConfigView(self.bot, self.owner_id, settings),
        )


class CartToggleSelect(discord.ui.Select):
    def __init__(
        self, bot: "SKStoreBot", owner_id: int, settings: GuildSettings
    ) -> None:
        super().__init__(
            placeholder="Opções da mensagem",
            min_values=0,
            max_values=2,
            options=[
                discord.SelectOption(
                    label="Mensagem ativa",
                    value="enabled",
                    default=settings.cart_message_enabled,
                ),
                discord.SelectOption(
                    label="Auto-delete ativo",
                    value="auto_delete",
                    default=settings.cart_message_auto_delete,
                ),
            ],
            custom_id="sk:config:cart:toggles",
            row=1,
        )
        self.bot = bot
        self.owner_id = owner_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        await interaction.response.defer()
        settings = await self.bot.configurations.update(
            guild_id=interaction.guild.id,
            values={
                "cart_message_enabled": str("enabled" in self.values).lower(),
                "cart_message_auto_delete": str(
                    "auto_delete" in self.values
                ).lower(),
            },
            actor_id=interaction.user.id,
            interaction_id=interaction.id,
        )
        await interaction.edit_original_response(
            embed=cart_message_embed(settings),
            view=CartMessageConfigView(self.bot, self.owner_id, settings),
        )


class CartMessageConfigView(ConfigView):
    def __init__(
        self, bot: "SKStoreBot", owner_id: int, settings: GuildSettings
    ) -> None:
        super().__init__(bot, owner_id, add_back=True, back_row=3)
        self.settings = settings
        self.add_item(CartTargetSelect(bot, owner_id, settings))
        self.add_item(CartToggleSelect(bot, owner_id, settings))
        button = discord.ui.Button(
            label="Editar texto e prazo",
            style=discord.ButtonStyle.secondary,
            custom_id="sk:config:cart:edit_button",
            row=2,
        )
        button.callback = self.edit_message
        self.add_item(button)

    async def edit_message(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            CartMessageModal(self.bot, self.settings)
        )


def logs_embed(settings: GuildSettings) -> discord.Embed:
    return build_section_embed(
        settings,
        "Logs",
        f"Logs: {'Ativos' if settings.logs_enabled else 'Desativados'}\n"
        f"Canal: {mention_channel(settings.logs_channel_id)}\n"
        f"Transcripts: {'Ativos' if settings.transcripts_enabled else 'Desativados'}\n"
        f"Canal: {mention_channel(settings.transcript_channel_id)}",
    )


class LogsToggleSelect(discord.ui.Select):
    def __init__(
        self, bot: "SKStoreBot", owner_id: int, settings: GuildSettings
    ) -> None:
        super().__init__(
            placeholder="Recursos de registro",
            min_values=0,
            max_values=2,
            options=[
                discord.SelectOption(
                    label="Logs ativos",
                    value="logs",
                    default=settings.logs_enabled,
                ),
                discord.SelectOption(
                    label="Transcripts ativos",
                    value="transcripts",
                    default=settings.transcripts_enabled,
                ),
            ],
            custom_id="sk:config:logs:toggles",
            row=0,
        )
        self.bot = bot
        self.owner_id = owner_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        await interaction.response.defer()
        settings = await self.bot.configurations.update(
            guild_id=interaction.guild.id,
            values={
                "logs_enabled": str("logs" in self.values).lower(),
                "transcripts_enabled": str(
                    "transcripts" in self.values
                ).lower(),
            },
            actor_id=interaction.user.id,
            interaction_id=interaction.id,
        )
        await interaction.edit_original_response(
            embed=logs_embed(settings),
            view=LogsConfigView(self.bot, self.owner_id, settings),
        )


class LogChannelSelect(SettingChannelSelect):
    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        await interaction.response.defer()
        settings = await self.bot.configurations.update(
            guild_id=interaction.guild.id,
            values={self.setting_key: str(self.values[0].id)},
            actor_id=interaction.user.id,
            interaction_id=interaction.id,
        )
        await interaction.edit_original_response(
            embed=logs_embed(settings),
            view=LogsConfigView(self.bot, self.owner_id, settings),
        )


class LogsConfigView(ConfigView):
    def __init__(
        self, bot: "SKStoreBot", owner_id: int, settings: GuildSettings
    ) -> None:
        super().__init__(bot, owner_id, add_back=True, back_row=3)
        self.add_item(LogsToggleSelect(bot, owner_id, settings))
        self.add_item(
            LogChannelSelect(
                bot,
                owner_id,
                "logs_channel_id",
                "Canal de logs",
                [discord.ChannelType.text],
                1,
                "sk:config:logs_channel",
            )
        )
        self.add_item(
            LogChannelSelect(
                bot,
                owner_id,
                "transcript_channel_id",
                "Canal de transcripts",
                [discord.ChannelType.text],
                2,
                "sk:config:logs_channel",
            )
        )


def general_embed(settings: GuildSettings) -> discord.Embed:
    return build_section_embed(
        settings,
        "Configurações gerais",
        f"Prefixo: {settings.ticket_prefix}\n"
        f"Vendas ativas por cliente: {settings.max_active_sales}\n"
        f"Auto-close: {'Ativo' if settings.auto_close_enabled else 'Desativado'}\n"
        f"Prazo: {settings.auto_close_delay // 60} min",
    )


class GeneralToggleSelect(discord.ui.Select):
    KEYS = {
        "cancellation": "customer_cancellation_enabled",
        "dm": "dm_notifications_enabled",
        "auto_close": "auto_close_enabled",
        "rename": "rename_closed_tickets",
        "transcripts": "transcripts_enabled",
        "cart": "cart_message_enabled",
    }

    def __init__(
        self, bot: "SKStoreBot", owner_id: int, settings: GuildSettings
    ) -> None:
        defaults = {
            "cancellation": settings.customer_cancellation_enabled,
            "dm": settings.dm_notifications_enabled,
            "auto_close": settings.auto_close_enabled,
            "rename": settings.rename_closed_tickets,
            "transcripts": settings.transcripts_enabled,
            "cart": settings.cart_message_enabled,
        }
        labels = {
            "cancellation": "Cancelamento pelo cliente",
            "dm": "Notificações por DM",
            "auto_close": "Auto-close",
            "rename": "Renomear tickets encerrados",
            "transcripts": "Transcripts",
            "cart": "Mensagem automática do carrinho",
        }
        super().__init__(
            placeholder="Recursos gerais",
            min_values=0,
            max_values=len(self.KEYS),
            options=[
                discord.SelectOption(
                    label=labels[key], value=key, default=defaults[key]
                )
                for key in self.KEYS
            ],
            custom_id="sk:config:general:toggles",
            row=0,
        )
        self.bot = bot
        self.owner_id = owner_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        await interaction.response.defer()
        values = {
            setting: str(option in self.values).lower()
            for option, setting in self.KEYS.items()
        }
        settings = await self.bot.configurations.update(
            guild_id=interaction.guild.id,
            values=values,
            actor_id=interaction.user.id,
            interaction_id=interaction.id,
        )
        await interaction.edit_original_response(
            embed=general_embed(settings),
            view=GeneralConfigView(self.bot, self.owner_id, settings),
        )


class GeneralConfigView(ConfigView):
    def __init__(
        self, bot: "SKStoreBot", owner_id: int, settings: GuildSettings
    ) -> None:
        super().__init__(bot, owner_id, add_back=True, back_row=2)
        self.settings = settings
        self.add_item(GeneralToggleSelect(bot, owner_id, settings))
        button = discord.ui.Button(
            label="Editar limites",
            style=discord.ButtonStyle.secondary,
            custom_id="sk:config:general:values_button",
            row=1,
        )
        button.callback = self.edit_values
        self.add_item(button)

    async def edit_values(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(
            GeneralSettingsModal(self.bot, self.settings)
        )
