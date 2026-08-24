from __future__ import annotations

import secrets
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import discord

from app.constants import MAX_ACCOUNTS_DISCORD
from app.exceptions import ValidationError
from app.models import GuildSettings
from app.utils.money import parse_brl_to_cents
from app.utils.permissions import require_admin
from app.utils.validation import validate_template, validate_ticket_prefix

if TYPE_CHECKING:
    from app.bot import SKStoreBot


def _url(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValidationError("Use uma URL http ou https válida.")
    if len(cleaned) > 2_000:
        raise ValidationError("A URL é muito longa.")
    return cleaned


def _colour(value: str) -> str:
    cleaned = value.strip().lower().removeprefix("#").removeprefix("0x")
    if len(cleaned) != 6:
        raise ValidationError("Use uma cor hexadecimal com 6 caracteres.")
    try:
        int(cleaned, 16)
    except ValueError as exc:
        raise ValidationError("Use uma cor hexadecimal válida.") from exc
    return cleaned.upper()


def _optional_emoji_id(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""
    if (
        not cleaned.isdigit()
        or not 10**16 <= int(cleaned) <= 2**64 - 1
    ):
        raise ValidationError("Informe somente o ID numérico do emoji.")
    return cleaned


def _integer(value: str, label: str, minimum: int, maximum: int) -> int:
    try:
        number = int(value.strip())
    except ValueError as exc:
        raise ValidationError(f"{label} precisa ser um número inteiro.") from exc
    if not minimum <= number <= maximum:
        raise ValidationError(
            f"{label} deve ficar entre {minimum} e {maximum}."
        )
    return number


def _required_text(value: str, label: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValidationError(f"{label} não pode ficar vazio.")
    return cleaned


def _add_text_input(
    modal: discord.ui.Modal,
    label: str,
    **kwargs: Any,
) -> discord.ui.TextInput:
    component = discord.ui.TextInput(**kwargs)
    modal.add_item(discord.ui.Label(text=label, component=component))
    return component


class _ConfigModal(discord.ui.Modal):
    def __init__(
        self,
        bot: "SKStoreBot",
        settings: GuildSettings,
        *,
        title: str,
        custom_id: str,
    ) -> None:
        super().__init__(
            title=title,
            timeout=600,
            custom_id=f"{custom_id}:{secrets.token_hex(8)}",
        )
        self.bot = bot
        self.settings = settings

    async def save(
        self, interaction: discord.Interaction, values: dict[str, str]
    ) -> None:
        if interaction.guild is None:
            raise ValidationError("Use esta configuração dentro do servidor.")
        if not isinstance(interaction.user, discord.Member):
            raise ValidationError("Use esta configuração dentro do servidor.")
        current = await self.bot.database.get_settings(interaction.guild.id)
        require_admin(interaction.user, current)
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=True, thinking=True)
        await self.bot.configurations.update(
            guild_id=interaction.guild.id,
            values=values,
            actor_id=interaction.user.id,
            interaction_id=interaction.id,
        )

    async def on_error(
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        await self.bot.handle_user_exception(interaction, error)


class PanelTextsModal(_ConfigModal):
    def __init__(self, bot: "SKStoreBot", settings: GuildSettings) -> None:
        super().__init__(
            bot,
            settings,
            title="Textos do painel",
            custom_id="sk:config:panel:texts",
        )
        self.title_input = _add_text_input(
            self,
            "Título",
            default=settings.panel_title,
            max_length=256,
            custom_id="sk:config:panel:title",
        )
        self.description_input = _add_text_input(
            self,
            "Descrição",
            default=settings.panel_description,
            style=discord.TextStyle.paragraph,
            max_length=3_200,
            custom_id="sk:config:panel:description",
        )
        self.footer_input = _add_text_input(
            self,
            "Rodapé",
            default=settings.panel_footer,
            required=False,
            max_length=1_000,
            custom_id="sk:config:panel:footer",
        )
        self.info_input = _add_text_input(
            self,
            "Informação curta",
            default=settings.panel_info_text,
            required=False,
            max_length=1_000,
            custom_id="sk:config:panel:info",
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self.save(
                interaction,
                {
                    "panel_title": _required_text(
                        str(self.title_input), "O título"
                    ),
                    "panel_description": _required_text(
                        str(self.description_input), "A descrição"
                    ),
                    "panel_footer": str(self.footer_input).strip(),
                    "panel_info_text": str(self.info_input).strip(),
                },
            )
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.followup.send(
            "Textos do painel salvos.", ephemeral=True
        )


class PanelActionModal(_ConfigModal):
    def __init__(self, bot: "SKStoreBot", settings: GuildSettings) -> None:
        super().__init__(
            bot,
            settings,
            title="Destaque do painel",
            custom_id="sk:config:panel:action",
        )
        self.button = _add_text_input(
            self,
            "Texto do botão",
            default=settings.panel_button_text,
            max_length=80,
            custom_id="sk:config:panel:button",
        )
        self.price_label = _add_text_input(
            self,
            "Texto do preço",
            default=settings.panel_price_label,
            max_length=256,
            custom_id="sk:config:panel:price_label",
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self.save(
                interaction,
                {
                    "panel_button_text": _required_text(
                        str(self.button), "O texto do botão"
                    ),
                    "panel_price_label": _required_text(
                        str(self.price_label), "O texto do preço"
                    ),
                },
            )
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.followup.send(
            "Destaque do painel salvo.", ephemeral=True
        )


class PricesModal(_ConfigModal):
    def __init__(self, bot: "SKStoreBot", settings: GuildSettings) -> None:
        super().__init__(
            bot,
            settings,
            title="Preços e limites",
            custom_id="sk:config:prices",
        )
        self.price = _add_text_input(
            self,
            "Valor por Gmail",
            placeholder="2,00",
            default=f"{settings.unit_price_cents // 100},{settings.unit_price_cents % 100:02d}",
            max_length=20,
            custom_id="sk:config:prices:unit",
        )
        self.minimum = _add_text_input(
            self,
            "Mínimo de contas",
            default=str(settings.min_accounts),
            max_length=2,
            custom_id="sk:config:prices:min",
        )
        self.maximum = _add_text_input(
            self,
            "Máximo de contas",
            default=str(settings.max_accounts),
            max_length=2,
            custom_id="sk:config:prices:max",
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            cents = parse_brl_to_cents(str(self.price))
            minimum = _integer(
                str(self.minimum), "O mínimo", 1, MAX_ACCOUNTS_DISCORD
            )
            maximum = _integer(
                str(self.maximum), "O máximo", 1, MAX_ACCOUNTS_DISCORD
            )
            if minimum > maximum:
                raise ValidationError("O mínimo não pode ser maior que o máximo.")
            await self.save(
                interaction,
                {
                    "unit_price_cents": str(cents),
                    "min_accounts": str(minimum),
                    "max_accounts": str(maximum),
                },
            )
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.followup.send(
            "Preço e limites salvos.", ephemeral=True
        )


class BrandAppearanceModal(_ConfigModal):
    def __init__(self, bot: "SKStoreBot", settings: GuildSettings) -> None:
        super().__init__(
            bot,
            settings,
            title="Marca e aparência",
            custom_id="sk:config:appearance:brand",
        )
        self.colour = _add_text_input(
            self,
            "Cor hexadecimal",
            default=f"#{settings.embed_color:06X}",
            max_length=8,
            custom_id="sk:config:appearance:colour",
        )
        self.logo = _add_text_input(
            self,
            "URL do logo",
            default=settings.logo_url,
            required=False,
            max_length=2_000,
            custom_id="sk:config:appearance:logo",
        )
        self.banner = _add_text_input(
            self,
            "URL do banner",
            default=settings.banner_url,
            required=False,
            max_length=2_000,
            custom_id="sk:config:appearance:banner",
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self.save(
                interaction,
                {
                    "embed_color": _colour(str(self.colour)),
                    "logo_url": _url(str(self.logo)),
                    "banner_url": _url(str(self.banner)),
                },
            )
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.followup.send(
            "Aparência salva.", ephemeral=True
        )


class IconsAppearanceModal(_ConfigModal):
    def __init__(self, bot: "SKStoreBot", settings: GuildSettings) -> None:
        super().__init__(
            bot,
            settings,
            title="Ícones customizados",
            custom_id="sk:config:appearance:icons",
        )
        values = (
            ("Venda", settings.icon_sell_id, "sell"),
            ("Editar", settings.icon_edit_id, "edit"),
            ("Staff", settings.icon_staff_id, "staff"),
            ("Pagamento", settings.icon_payment_id, "payment"),
        )
        self.inputs: dict[str, discord.ui.TextInput] = {}
        for label, value, key in values:
            item = _add_text_input(
                self,
                f"ID do ícone · {label}",
                default=str(value or ""),
                required=False,
                max_length=20,
                custom_id=f"sk:config:icon:{key}",
            )
            self.inputs[key] = item

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            await self.save(
                interaction,
                {
                    "icon_sell_id": _optional_emoji_id(
                        str(self.inputs["sell"])
                    ),
                    "icon_edit_id": _optional_emoji_id(
                        str(self.inputs["edit"])
                    ),
                    "icon_staff_id": _optional_emoji_id(
                        str(self.inputs["staff"])
                    ),
                    "icon_payment_id": _optional_emoji_id(
                        str(self.inputs["payment"])
                    ),
                },
            )
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.followup.send("Ícones salvos.", ephemeral=True)


class CartMessageModal(_ConfigModal):
    def __init__(self, bot: "SKStoreBot", settings: GuildSettings) -> None:
        super().__init__(
            bot,
            settings,
            title="Mensagem do carrinho",
            custom_id="sk:config:cart:message",
        )
        self.message = _add_text_input(
            self,
            "Mensagem",
            default=settings.cart_message_text,
            style=discord.TextStyle.paragraph,
            min_length=1,
            max_length=1_500,
            custom_id="sk:config:cart:text",
        )
        self.delay = _add_text_input(
            self,
            "Auto-delete em segundos",
            default=str(settings.cart_message_delete_delay),
            max_length=6,
            custom_id="sk:config:cart:delay",
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            message = validate_template(str(self.message))
            delay = _integer(str(self.delay), "O prazo", 5, 86_400)
            await self.save(
                interaction,
                {
                    "cart_message_text": message,
                    "cart_message_delete_delay": str(delay),
                },
            )
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.followup.send(
            "Mensagem do carrinho salva.", ephemeral=True
        )


class GeneralSettingsModal(_ConfigModal):
    def __init__(self, bot: "SKStoreBot", settings: GuildSettings) -> None:
        super().__init__(
            bot,
            settings,
            title="Configurações gerais",
            custom_id="sk:config:general:values",
        )
        self.prefix = _add_text_input(
            self,
            "Prefixo dos tickets",
            default=settings.ticket_prefix,
            max_length=20,
            custom_id="sk:config:general:prefix",
        )
        self.active_limit = _add_text_input(
            self,
            "Vendas ativas por cliente",
            default=str(settings.max_active_sales),
            max_length=2,
            custom_id="sk:config:general:active_limit",
        )
        self.close_delay = _add_text_input(
            self,
            "Fechamento automático em minutos",
            default=str(max(settings.auto_close_delay // 60, 1)),
            max_length=5,
            custom_id="sk:config:general:close_delay",
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            prefix = validate_ticket_prefix(str(self.prefix))
            active_limit = _integer(
                str(self.active_limit), "O limite", 1, 10
            )
            minutes = _integer(
                str(self.close_delay), "O prazo", 1, 10_080
            )
            await self.save(
                interaction,
                {
                    "ticket_prefix": prefix,
                    "max_active_sales": str(active_limit),
                    "auto_close_delay": str(minutes * 60),
                },
            )
        except Exception as exc:
            await self.bot.handle_user_exception(interaction, exc)
            return
        await interaction.followup.send(
            "Configurações gerais salvas.", ephemeral=True
        )
