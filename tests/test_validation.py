from __future__ import annotations

import unittest

from app.exceptions import ValidationError
from app.services.tickets import topic_matches_sale
from app.utils.money import format_brl, parse_brl_to_cents
from app.utils.text import safe_channel_name, split_lines
from app.utils.validation import (
    parse_gmail,
    parse_gmail_lines,
    render_cart_template,
    validate_pix,
    validate_template,
    validate_ticket_prefix,
)
from app.modals.configuration import _required_text


class ValidationTests(unittest.TestCase):
    def test_required_configuration_text_rejects_whitespace(self) -> None:
        self.assertEqual(_required_text("  SK Store  ", "O título"), "SK Store")
        with self.assertRaises(ValidationError):
            _required_text("   ", "O título")

    def test_money_uses_integer_cents(self) -> None:
        self.assertEqual(parse_brl_to_cents("R$ 2,00"), 200)
        self.assertEqual(parse_brl_to_cents("1.234,56"), 123456)
        self.assertEqual(parse_brl_to_cents("1.234"), 123400)
        self.assertEqual(format_brl(123456), "R$ 1.234,56")
        with self.assertRaises(ValidationError):
            parse_brl_to_cents("0")
        for invalid in ("NaN", "Infinity", "-Infinity", "1e2", "2,999"):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                parse_brl_to_cents(invalid)

    def test_gmail_validation_and_canonicalization(self) -> None:
        parsed = parse_gmail("Nome.Teste@googlemail.com")
        self.assertEqual(parsed.display, "nome.teste@gmail.com")
        self.assertEqual(parsed.canonical, "nometeste@gmail.com")
        for invalid in (
            "nome@yahoo.com",
            "nome..teste@gmail.com",
            "nome+alias@gmail.com",
            "@gmail.com",
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValidationError):
                parse_gmail(invalid)

    def test_duplicate_inside_form_is_blocked(self) -> None:
        with self.assertRaises(ValidationError):
            parse_gmail_lines("nome.teste@gmail.com\nnometeste@gmail.com")

    def test_pix_and_prefix_validation(self) -> None:
        self.assertEqual(
            validate_pix(" chave ", " Nome   Teste "),
            ("chave", "Nome Teste"),
        )
        self.assertEqual(validate_ticket_prefix("gmail-venda"), "gmail-venda")
        with self.assertRaises(ValidationError):
            validate_ticket_prefix("Gmail Venda!")

    def test_template_placeholders(self) -> None:
        template = "{user}, {quantidade} contas por {preco}: {total} · {codigo} · {ticket}"
        self.assertEqual(validate_template(template), template)
        self.assertEqual(
            render_cart_template(
                "{user}: {quantidade} · {total}",
                {"user": "@cliente", "quantidade": "3", "total": "R$ 6,00"},
            ),
            "@cliente: 3 · R$ 6,00",
        )
        with self.assertRaises(ValidationError):
            validate_template("{senha}")
        for malformed in ("{user", "user}", "}{", "{{user}}"):
            with self.subTest(malformed=malformed), self.assertRaises(
                ValidationError
            ):
                validate_template(malformed)

    def test_embed_line_splitting_and_channel_name(self) -> None:
        chunks = split_lines(["a" * 600, "b" * 600])
        self.assertEqual(len(chunks), 2)
        self.assertTrue(all(len(chunk) <= 1024 for chunk in chunks))
        self.assertEqual(safe_channel_name("Gmail Loja", 42), "gmail-loja-0042")

    def test_ticket_topic_match_is_exact(self) -> None:
        self.assertTrue(
            topic_matches_sale("SKSTORE_SALE_ID=4 | Cliente=10", 4)
        )
        self.assertFalse(
            topic_matches_sale("SKSTORE_SALE_ID=42 | Cliente=10", 4)
        )
