import os
import tempfile
import unittest
import gc
from datetime import datetime, timezone
from pathlib import Path

from po3.storage.market_repository import (
    collection_status,
    insert_market_state,
    upsert_outcome,
    get_outcomes,
)


class OperationalClosureTests(unittest.TestCase):
    def setUp(self):
        fd, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        self.db = Path(path)
        self.cutoff = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
        self.state_id = insert_market_state(
            {"preco_atual": 100.0, "start_price": 99.0,
             "start_price_status": "DISPONIVEL",
             "start_bar_open_time": "2026-01-01T09:59:00+00:00"},
            self.db, cutoff_at_utc=self.cutoff, symbol="WIN",
        )

    def tearDown(self):
        gc.collect()
        try:
            self.db.unlink(missing_ok=True)
        except PermissionError:
            # Windows may release an SQLite handle a moment after the test.
            # The file is temporary and is intentionally not part of the repo.
            pass

    def _make_outcome(self, *, status="DISPONIVEL", suffix="a"):
        return {
            "market_state_id": self.state_id,
            "symbol": "WIN",
            "horizon_code": "5m",
            "target_at_utc": "2026-01-01T10:05:00+00:00",
            "observed_at_utc": f"2026-01-01T10:06:0{suffix}+00:00" if suffix.isdigit() else "2026-01-01T10:06:00+00:00",
            "start_price": 99.0,
            "future_price": 101.0,
            "future_high": 102.0,
            "future_low": 98.0,
            "high_delta": 3.0,
            "low_delta": -1.0,
            "absolute_change": 2.0,
            "percentage_change": 2.0202,
            "candles_observed": 5,
            "status": status,
            "created_at": "2026-01-01T10:05:30+00:00",
        }

    def test_disponivel_outcome_is_factually_immutable(self):
        original = self._make_outcome()
        upsert_outcome(original, self.db)
        before = get_outcomes(self.db, self.state_id)[0]
        for index in range(5):
            changed = {**original,
                       "observed_at_utc": f"2026-01-01T10:1{index}:00+00:00",
                       "start_price": 500.0 + index,
                       "future_price": 600.0 + index,
                       "future_high": 700.0 + index,
                       "future_low": 400.0 + index,
                       "high_delta": 200.0 + index,
                       "low_delta": -100.0 - index,
                       "absolute_change": 100.0 + index,
                       "percentage_change": 50.0 + index,
                       "candles_observed": 99 + index,
                       "created_at": f"2026-01-01T11:0{index}:00+00:00",
                       "status": "PENDENTE"}
            upsert_outcome(changed, self.db)
        after = get_outcomes(self.db, self.state_id)[0]
        self.assertEqual(len(get_outcomes(self.db, self.state_id)), 1)
        for field in ("created_at", "observed_at_utc", "start_price", "future_price",
                      "future_high", "future_low", "high_delta", "low_delta",
                      "absolute_change", "percentage_change", "candles_observed",
                      "updated_at"):
            self.assertEqual(after[field], before[field], field)
        self.assertEqual(after["status"], "DISPONIVEL")

    def test_collection_status_separates_pending_data(self):
        pending = self._make_outcome(status="PENDENTE_DADOS")
        pending["horizon_code"] = "15m"
        pending["target_at_utc"] = "2026-01-01T10:15:00+00:00"
        pending["observed_at_utc"] = None
        upsert_outcome(pending, self.db)
        unavailable = self._make_outcome(status="START_PRICE_INDISPONIVEL")
        unavailable["horizon_code"] = "30m"
        unavailable["target_at_utc"] = "2026-01-01T10:30:00+00:00"
        upsert_outcome(unavailable, self.db)
        status = collection_status("WIN", self.db)
        self.assertEqual(status["outcomes_pendentes"], 1)
        self.assertEqual(status["outcomes_start_price_indisponivel"], 1)


if __name__ == "__main__":
    unittest.main()
