from __future__ import annotations

import importlib
import pkgutil
import unittest

import app


class ImportSmokeTests(unittest.TestCase):
    def test_every_application_module_imports(self) -> None:
        modules = sorted(
            module.name
            for module in pkgutil.walk_packages(app.__path__, prefix="app.")
        )
        failures: list[str] = []
        for module_name in modules:
            try:
                importlib.import_module(module_name)
            except Exception as exc:
                failures.append(
                    f"{module_name}: {type(exc).__name__}: {exc}"
                )
        self.assertEqual(failures, [])
