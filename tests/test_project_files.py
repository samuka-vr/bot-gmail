from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ProjectFileTests(unittest.TestCase):
    def test_discloud_config_and_dependencies(self) -> None:
        config = (ROOT / "discloud.config").read_text(encoding="utf-8")
        self.assertIn("TYPE=bot", config)
        self.assertIn("MAIN=main.py", config)
        self.assertIn("RAM=100", config)
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertEqual(
            requirements.splitlines(),
            [
                "discord.py==2.7.1",
                "aiosqlite==0.22.1",
                "python-dotenv==1.2.3",
            ],
        )

    def test_env_and_database_are_ignored(self) -> None:
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".env", gitignore)
        self.assertIn("*.db", gitignore)
        self.assertTrue((ROOT / ".env.example").is_file())
        self.assertFalse((ROOT / ".env").exists())

    def test_only_requested_slash_commands_exist(self) -> None:
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "app" / "cogs").glob("*.py")
        )
        names = set(re.findall(r"name=\"([a-z]+)\"", source))
        self.assertEqual(names, {"botconfig", "perfil", "fila", "vender"})

    def test_no_unicode_emoji_in_customer_facing_python(self) -> None:
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "app").rglob("*.py")
        )
        pictographs = [
            char
            for char in source
            if 0x1F000 <= ord(char) <= 0x1FAFF
            or 0x2600 <= ord(char) <= 0x27BF
        ]
        self.assertEqual(pictographs, [])

    def test_no_forbidden_runtime_dependencies(self) -> None:
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
        for forbidden in ("flask", "fastapi", "redis", "mongo", "sqlalchemy", "docker"):
            self.assertNotIn(forbidden, requirements)
