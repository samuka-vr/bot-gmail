"""Small Discord API shape used only for offline structural tests."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from enum import Enum
from types import SimpleNamespace
from typing import Any


class ButtonStyle:
    primary = 1
    secondary = 2
    success = 3
    danger = 4


class TextStyle:
    short = 1
    paragraph = 2


class ChannelType(Enum):
    text = 0
    category = 4


class Intents:
    guilds = False
    guild_messages = False
    message_content = False

    @classmethod
    def none(cls) -> "Intents":
        return cls()


class MemberCacheFlags:
    @classmethod
    def none(cls) -> "MemberCacheFlags":
        return cls()


@dataclass
class Object:
    id: int


@dataclass
class PartialEmoji:
    name: str
    id: int


@dataclass
class SelectOption:
    label: str
    value: str
    description: str | None = None
    emoji: Any = None
    default: bool = False


class AllowedMentions:
    def __init__(self, **kwargs: Any) -> None:
        self.values = kwargs

    @classmethod
    def none(cls) -> "AllowedMentions":
        return cls(everyone=False, roles=False, users=False)


class Embed:
    def __init__(
        self,
        *,
        title: str | None = None,
        description: str | None = None,
        colour: int | None = None,
        timestamp: Any = None,
    ) -> None:
        self.title = title
        self.description = description
        self.colour = colour
        self.timestamp = timestamp
        self.fields: list[SimpleNamespace] = []
        self.footer = SimpleNamespace(text=None)
        self.thumbnail = SimpleNamespace(url=None)
        self.image = SimpleNamespace(url=None)

    def add_field(self, *, name: str, value: str, inline: bool = True) -> None:
        self.fields.append(SimpleNamespace(name=name, value=value, inline=inline))

    def set_footer(self, *, text: str) -> None:
        self.footer = SimpleNamespace(text=text)

    def set_thumbnail(self, *, url: str) -> None:
        self.thumbnail = SimpleNamespace(url=url)

    def set_image(self, *, url: str) -> None:
        self.image = SimpleNamespace(url=url)


class Item:
    def __init__(self, *, custom_id: str | None = None, row: int | None = None) -> None:
        self.custom_id = custom_id
        self.row = row
        self.callback = None
        self.view = None


class Button(Item):
    def __init__(
        self,
        *,
        label: str | None = None,
        style: int,
        custom_id: str | None = None,
        emoji: Any = None,
        row: int | None = None,
    ) -> None:
        super().__init__(custom_id=custom_id, row=row)
        self.label = label
        self.style = style
        self.emoji = emoji


class Select(Item):
    def __init__(
        self,
        *,
        placeholder: str | None = None,
        min_values: int = 1,
        max_values: int = 1,
        options: list[SelectOption] | None = None,
        custom_id: str | None = None,
        row: int | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(custom_id=custom_id, row=row)
        self.placeholder = placeholder
        self.min_values = min_values
        self.max_values = max_values
        self.options = list(options or [])
        self.values: list[str] = []


class ChannelSelect(Select):
    pass


class RoleSelect(Select):
    pass


class TextInput(Item):
    def __init__(
        self,
        *,
        label: str | None = None,
        default: str = "",
        custom_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(custom_id=custom_id)
        self.label = label
        self.default = default
        self.value = default

    def __str__(self) -> str:
        return self.value


class Label(Item):
    def __init__(
        self,
        *,
        text: str,
        component: TextInput,
        description: str | None = None,
    ) -> None:
        super().__init__()
        self.text = text
        self.component = component
        self.description = description


def button(**metadata: Any):
    def decorator(func: Any) -> Any:
        func.__discord_item__ = ("button", metadata)
        return func

    return decorator


def select(**metadata: Any):
    def decorator(func: Any) -> Any:
        func.__discord_item__ = ("select", metadata)
        return func

    return decorator


class View:
    def __init__(self, *, timeout: float | None = 180) -> None:
        self.timeout = timeout
        self.children: list[Item] = []
        decorated: list[tuple[str, Any, tuple[str, dict[str, Any]]]] = []
        for cls in reversed(type(self).mro()):
            for name, value in vars(cls).items():
                metadata = getattr(value, "__discord_item__", None)
                if metadata:
                    decorated.append((name, value, metadata))
        seen: set[str] = set()
        for name, func, (kind, metadata) in decorated:
            if name in seen:
                continue
            seen.add(name)
            item = Button(**metadata) if kind == "button" else Select(**metadata)

            async def callback(interaction: Any, _item: Item = item, _func: Any = func):
                return await _func(self, interaction, _item)

            item.callback = callback
            self.add_item(item)
            setattr(self, name, item)

    def add_item(self, item: Item) -> None:
        item.view = self
        self.children.append(item)

    def remove_item(self, item: Item) -> None:
        if item in self.children:
            self.children.remove(item)

    def is_persistent(self) -> bool:
        return self.timeout is None and all(item.custom_id for item in self.children)

    def stop(self) -> None:
        return None


class Modal:
    def __init_subclass__(cls, **kwargs: Any) -> None:
        kwargs.pop("title", None)
        return super().__init_subclass__()

    def __init__(
        self,
        *,
        title: str | None = None,
        timeout: float | None = None,
        custom_id: str | None = None,
    ) -> None:
        self.title = title
        self.timeout = timeout
        self.custom_id = custom_id
        self.children: list[Item] = []
        for name, value in vars(type(self)).items():
            if isinstance(value, (TextInput, Label)):
                item = copy.deepcopy(value)
                setattr(self, name, item)
                self.add_item(item)

    def add_item(self, item: Item) -> None:
        self.children.append(item)


ui = SimpleNamespace(
    View=View,
    Modal=Modal,
    Button=Button,
    Select=Select,
    ChannelSelect=ChannelSelect,
    RoleSelect=RoleSelect,
    TextInput=TextInput,
    Label=Label,
    Item=Item,
    button=button,
    select=select,
)


class Interaction:
    pass


class Message:
    pass


class User:
    pass


class Member:
    pass


class Role:
    pass


class Guild:
    pass


class TextChannel:
    pass


class CategoryChannel:
    pass


class PermissionOverwrite:
    def __init__(self, **kwargs: Any) -> None:
        self.values = kwargs


class File:
    def __init__(self, path: Any, *, filename: str | None = None) -> None:
        self.path = path
        self.filename = filename


class DiscordException(Exception):
    pass


class HTTPException(DiscordException):
    pass


class Forbidden(HTTPException):
    pass


class NotFound(HTTPException):
    pass


abc = SimpleNamespace(GuildChannel=object)
