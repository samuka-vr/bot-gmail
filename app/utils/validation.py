from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from app.exceptions import ValidationError


GMAIL_RE = re.compile(
    r"^(?P<local>[a-zA-Z0-9](?:[a-zA-Z0-9.]{0,62}[a-zA-Z0-9])?)@"
    r"(?P<domain>gmail\.com|googlemail\.com)$",
    re.IGNORECASE,
)
TICKET_PREFIX_RE = re.compile(r"^[a-z0-9-]{1,20}$")
PLACEHOLDERS = {
    "user",
    "quantidade",
    "preco",
    "total",
    "codigo",
    "ticket",
}


@dataclass(frozen=True, slots=True)
class ParsedEmail:
    display: str
    canonical: str


def parse_gmail(value: str) -> ParsedEmail:
    email = value.strip().lower()
    match = GMAIL_RE.fullmatch(email)
    if not match or ".." in email:
        raise ValidationError(f"Gmail inválido: {value.strip() or '(vazio)'}")
    local = match.group("local")
    canonical = f"{local.replace('.', '')}@gmail.com"
    return ParsedEmail(display=f"{local}@gmail.com", canonical=canonical)


def parse_gmail_lines(value: str) -> list[ParsedEmail]:
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        raise ValidationError("Informe pelo menos um Gmail.")
    parsed = [parse_gmail(line) for line in lines]
    seen: set[str] = set()
    duplicates: list[str] = []
    for item in parsed:
        if item.canonical in seen:
            duplicates.append(item.display)
        seen.add(item.canonical)
    if duplicates:
        raise ValidationError("Há G-mails repetidos na lista.")
    return parsed


def validate_pix(pix_key: str, holder: str) -> tuple[str, str]:
    key = pix_key.strip()
    name = " ".join(holder.split())
    if not 3 <= len(key) <= 140:
        raise ValidationError("Informe uma chave Pix válida.")
    if not 2 <= len(name) <= 100:
        raise ValidationError("Informe o nome do titular.")
    return key, name


def validate_ticket_prefix(value: str) -> str:
    prefix = value.strip().lower().strip("-")
    if not TICKET_PREFIX_RE.fullmatch(prefix):
        raise ValidationError(
            "Use até 20 caracteres: letras minúsculas, números e hífen."
        )
    return prefix


def validate_template(template: str) -> str:
    if not template.strip():
        raise ValidationError("A mensagem não pode ficar vazia.")
    if len(template) > 1_500:
        raise ValidationError("A mensagem pode ter no máximo 1.500 caracteres.")
    for found in re.findall(r"{([^{}]+)}", template):
        if found not in PLACEHOLDERS:
            raise ValidationError(f"Placeholder não reconhecido: {{{found}}}")
    without_placeholders = re.sub(
        r"{(?:user|quantidade|preco|total|codigo|ticket)}", "", template
    )
    if "{" in without_placeholders or "}" in without_placeholders:
        raise ValidationError("Confira as chaves dos placeholders.")
    return template.strip()


def render_cart_template(
    template: str, values: Mapping[str, str]
) -> str:
    rendered = template
    for key in PLACEHOLDERS:
        if key in values:
            rendered = rendered.replace("{" + key + "}", values[key])
    return rendered
