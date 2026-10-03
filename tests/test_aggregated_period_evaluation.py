import os
import gc
import time
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from po3.analytics import build_evaluation_report
from po3.storage.market_repository import insert_m1_bars
from po3.storage.migrations import migrate


class AggregatedPeriodEvaluationTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        Path(self.path).unlink(missing_ok=True)
        migrate(self.path)

    def tearDown(self):
        gc.collect()
        for _ in range(5):
            try:
                Path(self.path).unlink(missing_ok=True)
                break
            except PermissionError:
                time.sleep(0.05)

    def _bar(self, timestamp, open_price, close, high, low):
        return {"symbol": "WIN", "timestamp_utc": timestamp, "open": open_price,
                "close": close, "high": high, "low": low,
                "source_timestamp_raw": 1, "time_offset_seconds": 10800}

    def test_daily_weekly_monthly_use_direct_factual_prices(self):
        bars = [
            self._bar("2026-01-05T12:00:00+00:00", 100, 100, 120, 95),
            self._bar("2026-01-05T21:29:00+00:00", 100, 110, 115, 98),
            self._bar("2026-01-06T12:00:00+00:00", 200, 200, 220, 170),
            self._bar("2026-01-06T21:29:00+00:00", 200, 180, 210, 175),
            self._bar("2026-02-02T12:00:00+00:00", 300, 300, 330, 280),
            self._bar("2026-02-02T21:29:00+00:00", 300, 320, 325, 290),
        ]
        insert_m1_bars(bars, self.path)
        report = build_evaluation_report(
            self.path, "WIN", generated_at_utc=datetime(2026, 3, 2, tzinfo=timezone.utc)
        )
        daily = report["horizons"]["Diário"]
        self.assertEqual(daily["available_sample_size"], 3)
        self.assertAlmostEqual(daily["metrics"]["absolute_change"]["median"], 10)
        self.assertAlmostEqual(daily["metrics"]["absolute_change"]["p25"], -5)
        self.assertAlmostEqual(daily["metrics"]["high_delta"]["median"], 20)
        self.assertAlmostEqual(daily["metrics"]["low_delta"]["median"], -20)
        self.assertEqual(report["horizons"]["Semanal"]["available_sample_size"], 2)
        self.assertEqual(report["horizons"]["Mensal"]["available_sample_size"], 2)
        self.assertEqual(set(report["horizons"]), {"5m", "15m", "30m", "60m", "Diário", "Semanal", "Mensal"})

    def test_incomplete_current_period_is_excluded(self):
        insert_m1_bars([
            self._bar("2026-03-02T12:00:00+00:00", 100, 101, 102, 99),
            self._bar("2026-03-02T21:29:00+00:00", 101, 103, 104, 100),
            self._bar("2026-03-03T12:00:00+00:00", 200, 201, 202, 199),
        ], self.path)
        report = build_evaluation_report(
            self.path, "WIN", generated_at_utc=datetime(2026, 3, 3, 15, tzinfo=timezone.utc)
        )
        self.assertEqual(report["horizons"]["Diário"]["available_sample_size"], 1)

    def test_future_bars_do_not_enter_completed_periods(self):
        insert_m1_bars([
            self._bar("2026-01-05T12:00:00+00:00", 100, 100, 110, 95),
            self._bar("2026-01-05T21:29:00+00:00", 100, 105, 108, 98),
            self._bar("2026-01-06T12:00:00+00:00", 999, 999, 1000, 900),
        ], self.path)
        report = build_evaluation_report(
            self.path, "WIN", generated_at_utc=datetime(2026, 1, 6, 15, tzinfo=timezone.utc)
        )
        daily = report["horizons"]["Diário"]
        self.assertEqual(daily["available_sample_size"], 1)
        self.assertEqual(daily["metrics"]["absolute_change"]["median"], 5)


if __name__ == "__main__":
    unittest.main()
