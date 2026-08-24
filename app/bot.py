from __future__ import annotations

import asyncio
import logging

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from app.cogs.sales import SalesCog
from app.cogs.administration import AdministrationCog
from app.cogs.customer import CustomerCog
from app.cogs.staff import StaffCog
from app.config import Environment
from app.database import Database
from app.exceptions import SKStoreError
from app.services.panels import PanelService
from app.services.completion import CompletionService
from app.services.configuration import ConfigurationService
from app.services.diagnostics import DiagnosticService
from app.services.logs import LogService
from app.services.maintenance import MaintenanceService
from app.services.recovery import RecoveryService
from app.services.sales import SaleService
from app.services.tickets import TicketService
from app.services.transcripts import TranscriptService
from app.services.workflow import WorkflowService
from app.utils.interactions import send_user_error
from app.views.panel import PanelView
from app.views.sale import persistent_sale_views


LOGGER = logging.getLogger(__name__)


class SKStoreBot(commands.Bot):
    def __init__(self, environment: Environment) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True

        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
            allowed_mentions=discord.AllowedMentions(
                everyone=False,
                roles=False,
                users=False,
                replied_user=False,
            ),
            member_cache_flags=discord.MemberCacheFlags.none(),
            chunk_guilds_at_startup=False,
            max_messages=50,
        )
        self.environment = environment
        self.database = Database(environment.database_path)
        self.sales = SaleService(self.database)
        self.tickets = TicketService(self.database, self.sales)
        self.workflow = WorkflowService(self)
        self.panels = PanelService(self, self.database)
        self.logs = LogService(self)
        self.transcripts = TranscriptService(self)
        self.maintenance = MaintenanceService(self)
        self.completion = CompletionService(self)
        self.configurations = ConfigurationService(self)
        self.diagnostics = DiagnosticService(self)
        self.recovery = RecoveryService(self)
        self.persistent_views_added = False
        self._recovery_done = False
        self._recovery_lock = asyncio.Lock()

    async def setup_hook(self) -> None:
        await self.database.start()
        await self.add_cog(SalesCog(self))
        await self.add_cog(CustomerCog(self))
        await self.add_cog(StaffCog(self))
        await self.add_cog(AdministrationCog(self))

        self.add_view(PanelView(self))
        for view in persistent_sale_views(self):
            self.add_view(view)
        self.persistent_views_added = True

        if self.environment.sync_commands_on_start:
            if self.environment.dev_guild_id:
                guild = discord.Object(id=self.environment.dev_guild_id)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
            else:
                synced = await self.tree.sync()
            LOGGER.info("Comandos sincronizados: %d", len(synced))

    async def on_ready(self) -> None:
        if self.user:
            LOGGER.info(
                "SK Store conectado como %s em %d servidor(es).",
                self.user,
                len(self.guilds),
            )
        async with self._recovery_lock:
            if not self._recovery_done:
                self.maintenance.start()
                await self.recovery.run()
                self._recovery_done = True

    async def handle_user_exception(
        self, interaction: discord.Interaction, error: Exception
    ) -> None:
        if isinstance(error, SKStoreError):
            message = str(error)
        elif isinstance(error, discord.Forbidden):
            message = "Não tenho permissão para concluir esta ação."
            LOGGER.warning(
                "Permissão Discord negada na interação %s", interaction.id
            )
        elif isinstance(error, discord.NotFound):
            message = "Este recurso não está mais disponível."
        elif isinstance(error, (discord.HTTPException, aiosqlite.Error)):
            message = "Não consegui concluir agora. Tente novamente."
            LOGGER.exception(
                "Falha técnica na interação %s", interaction.id, exc_info=error
            )
        else:
            message = "Algo deu errado. Tente novamente."
            LOGGER.exception(
                "Erro inesperado na interação %s", interaction.id, exc_info=error
            )
        try:
            await send_user_error(interaction, message)
        except discord.HTTPException:
            LOGGER.warning(
                "Não foi possível responder à interação %s", interaction.id
            )

    async def close(self) -> None:
        await self.maintenance.stop()
        try:
            await super().close()
        finally:
            await self.database.close()


async def on_tree_error(
    interaction: discord.Interaction, error: app_commands.AppCommandError
) -> None:
    bot = interaction.client
    if isinstance(bot, SKStoreBot):
        original = getattr(error, "original", error)
        await bot.handle_user_exception(interaction, original)


def create_bot(environment: Environment) -> SKStoreBot:
    bot = SKStoreBot(environment)
    bot.tree.on_error = on_tree_error
    return bot
