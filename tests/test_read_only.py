from __future__ import annotations

import unittest
from pathlib import Path


class ReadOnlyContractTests(unittest.TestCase):
    def test_application_has_no_trade_submission_api(self) -> None:
        project = Path(__file__).resolve().parents[1]
        forbidden = ["order" + "_send", "TRADE_" + "ACTION", "ORDER_" + "TYPE_BUY", "ORDER_" + "TYPE_SELL"]
        inspected: list[str] = []
        for path in project.rglob("*.py"):
            if "tests" in path.parts or ".venv" in path.parts:
                continue
            inspected.append(str(path.relative_to(project)))
            content = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, content, f"Token proibido em {path.name}: {token}")
        self.assertTrue(inspected)


if __name__ == "__main__":
    unittest.main()
