from __future__ import annotations

import discord

from app.exceptions import PermissionDenied
from app.models import GuildSettings


def _has_role(member: discord.Member, role_id: int | None) -> bool:
    return bool(role_id and any(role.id == role_id for role in member.roles))


def is_admin(member: discord.Member, settings: GuildSettings) -> bool:
    permissions = member.guild_permissions
    return bool(
        permissions.administrator
        or permissions.manage_guild
        or _has_role(member, settings.admin_role_id)
    )


def is_staff(member: discord.Member, settings: GuildSettings) -> bool:
    return is_admin(member, settings) or _has_role(member, settings.staff_role_id)


def require_admin(member: discord.Member, settings: GuildSettings) -> None:
    if not is_admin(member, settings):
        raise PermissionDenied("Você não pode configurar este bot.")


def require_staff(member: discord.Member, settings: GuildSettings) -> None:
    if not is_staff(member, settings):
        raise PermissionDenied("Esta ação é exclusiva da equipe.")
