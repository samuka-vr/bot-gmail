from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from app.exceptions import ValidationError


def parse_brl_to_cents(value: str) -> int:
    cleaned = value.strip().replace("R$", "").replace(" ", "")
    if "," in cleaned:
        if not re.fullmatch(
            r"(?:\d{1,3}(?:\.\d{3})+|\d+),\d{1,2}", cleaned
        ):
            raise ValidationError("Informe um valor válido, como 2,00.")
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", cleaned):
        cleaned = cleaned.replace(".", "")
    elif not re.fullmatch(r"\d+(?:\.\d{1,2})?", cleaned):
        raise ValidationError("Informe um valor válido, como 2,00.")
    try:
        amount = Decimal(cleaned).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValidationError("Informe um valor válido, como 2,00.") from exc
    if not amount.is_finite():
        raise ValidationError("Informe um valor válido, como 2,00.")
    if amount <= 0:
        raise ValidationError("O valor deve ser maior que zero.")
    cents = int(amount * 100)
    if cents > 100_000_000:
        raise ValidationError("O valor informado é muito alto.")
    return cents


def format_brl(cents: int) -> str:
    if cents < 0:
        sign = "-"
        cents = abs(cents)
    else:
        sign = ""
    reais, centavos = divmod(cents, 100)
    grouped = f"{reais:,}".replace(",", ".")
    return f"{sign}R$ {grouped},{centavos:02d}"
