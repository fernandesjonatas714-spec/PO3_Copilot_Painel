import hashlib
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from po3.analytics import build_evaluation_report
from po3.evaluation_engine import data_quality, descriptive_stats, evaluate_horizon, sample_band
from po3.storage.market_repository import insert_market_state, select_v2_evaluation_data, upsert_outcome
from po3.storage.migrations import migrate


class EvaluationAnalyticsTests(unittest.TestCase):
    def test_sample_bands(self):
        self.assertEqual(sample_band(0), "INSUFICIENTE")
        self.assertEqual(sample_band(29), "INSUFICIENTE")
        self.assertEqual(sample_band(30), "PRELIMINAR")
        self.assertEqual(sample_band(99), "PRELIMINAR")
        self.assertEqual(sample_band(100), "UTIL")
        self.assertEqual(sample_band(199), "UTIL")
        self.assertEqual(sample_band(200), "ROBUSTA")

    def test_percentiles_and_none_without_zero_fabricado(self):
        stats = descriptive_stats([{"x": 1}, {"x": 2}, {"x": 3}, {"x": None}], "x")
        self.assertEqual(stats["count"], 3)
        self.assertEqual(stats["median"], 2)
        self.assertEqual(stats["p25"], 1.5)
        self.assertIsNone(descriptive_stats([], "x")["median"])

    def test_horizon_excludes_non_available_statuses(self):
        states = [{"id": 1, "symbol": "WIN", "cutoff_at_utc": "2026-01-02T13:00:00+00:00"}]
        outcomes = [
            {"market_state_id": 1, "horizon_code": "5m", "status": "PENDENTE", "percentage_change": None},
            {"market_state_id": 1, "horizon_code": "5m", "status": "PENDENTE_DADOS", "percentage_change": None},
            {"market_state_id": 1, "horizon_code": "5m", "status": "SEM_DADO", "percentage_change": None},
            {"market_state_id": 1, "horizon_code": "5m", "status": "DISPONIVEL", "percentage_change": .01,
             "absolute_change": 1, "high_delta": 2, "low_delta": -1},
        ]
        result = evaluate_horizon(states, outcomes, "5m")
        self.assertEqual(result["available_sample_size"], 1)
        self.assertEqual(result["status"]["PENDENTE"], 1)
        self.assertEqual(result["directional_distribution"]["positive"], 1)

    def test_directional_distribution_positive_negative_zero(self):
        outcomes = [{"percentage_change": 1}, {"percentage_change": -1}, {"percentage_change": 0}]
        result = evaluate_horizon([], [], "5m")
        self.assertEqual(result["available_sample_size"], 0)
        from po3.evaluation_engine import directional_distribution
        distribution = directional_distribution(outcomes)
        self.assertEqual((distribution["positive"], distribution["negative"], distribution["zero"]), (1, 1, 1))
        self.assertEqual(distribution["positive_move_rate"], 1 / 3)

    def _db(self):
        fd, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        try: Path(path).unlink(missing_ok=True)
        except OSError: pass
        migrate(path)
        return path

    def test_report_uses_only_v2_tables_and_is_read_only(self):
        path = self._db()
        state_id = insert_market_state({"preco_atual": 100}, path, cutoff_at_utc="2026-01-02T13:00:00+00:00", symbol="WIN")
        upsert_outcome({"market_state_id": state_id, "symbol": "WIN", "horizon_code": "5m",
                        "target_at_utc": "2026-01-02T13:05:00+00:00", "start_price": 100,
                        "future_price": 101, "future_high": 102, "future_low": 99,
                        "high_delta": 2, "low_delta": -1, "absolute_change": 1,
                        "percentage_change": .01, "candles_observed": 5, "status": "DISPONIVEL"}, path)
        before = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        report = build_evaluation_report(path, "WIN", generated_at_utc=datetime(2026, 1, 2, tzinfo=timezone.utc))
        after = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        self.assertEqual(before, after)
        self.assertEqual(report["evaluation_version"], "1.0.0")
        self.assertEqual(report["horizons"]["5m"]["available_sample_size"], 1)
        self.assertEqual(report["horizons"]["15m"]["available_sample_size"], 0)
        states, outcomes = select_v2_evaluation_data(path, "WIN")
        self.assertEqual((len(states), len(outcomes)), (1, 1))
        try: Path(path).unlink(missing_ok=True)
        except OSError: pass

    def test_data_quality_reports_orphan_duplicate_and_invalid_available(self):
        states = [{"id": 1, "symbol": "WIN", "cutoff_at_utc": "2026-01-02T13:00:00+00:00"}]
        outcomes = [
            {"market_state_id": 1, "horizon_code": "5m", "status": "DISPONIVEL", "future_price": None, "percentage_change": None, "start_price": None},
            {"market_state_id": 1, "horizon_code": "5m", "status": "DISPONIVEL", "future_price": 1, "percentage_change": .1, "start_price": 1},
            {"market_state_id": 99, "horizon_code": "15m", "status": "ESTRANHO", "future_price": 1, "percentage_change": .1, "start_price": 1},
        ]
        quality = data_quality(states, outcomes)
        self.assertEqual(quality["orphan_outcomes"], 1)
        self.assertEqual(quality["duplicate_market_state_horizon"], 1)
        self.assertEqual(quality["available_without_future_price"], 1)
        self.assertIn("ESTRANHO", quality["unknown_statuses"])
        self.assertEqual(quality["missing_expected_outcomes"], 3)
        self.assertEqual(quality["market_states_with_missing_outcome"], 1)

    def test_start_price_invalid_when_none_non_numeric_or_non_positive(self):
        states = [{"id": 1, "symbol": "WIN", "cutoff_at_utc": "2026-01-02T13:00:00+00:00"}]
        outcomes = [
            {"market_state_id": 1, "horizon_code": "5m", "status": "PENDENTE", "start_price": None},
            {"market_state_id": 1, "horizon_code": "15m", "status": "PENDENTE", "start_price": "invalido"},
            {"market_state_id": 1, "horizon_code": "30m", "status": "PENDENTE", "start_price": 0},
            {"market_state_id": 1, "horizon_code": "60m", "status": "PENDENTE", "start_price": -1},
            {"market_state_id": 1, "horizon_code": "5m", "status": "PENDENTE", "start_price": 100},
        ]
        self.assertEqual(data_quality(states, outcomes)["start_price_invalid_or_null"], 4)

    def test_temporal_grouping_uses_sao_paulo_for_display_only(self):
        path = self._db()
        state_id = insert_market_state({"preco_atual": 100}, path, cutoff_at_utc="2026-01-02T12:00:00+00:00", symbol="WIN")
        upsert_outcome({"market_state_id": state_id, "symbol": "WIN", "horizon_code": "5m",
                        "target_at_utc": "2026-01-02T12:05:00+00:00", "start_price": 100,
                        "future_price": 100, "future_high": 101, "future_low": 99,
                        "high_delta": 1, "low_delta": -1, "absolute_change": 0,
                        "percentage_change": 0, "candles_observed": 5, "status": "DISPONIVEL"}, path)
        upsert_outcome({"market_state_id": state_id, "symbol": "WIN", "horizon_code": "60m",
                        "target_at_utc": "2026-01-02T13:00:00+00:00", "start_price": 100,
                        "future_price": 102, "future_high": 103, "future_low": 99,
                        "high_delta": 3, "low_delta": -1, "absolute_change": 2,
                        "percentage_change": .02, "candles_observed": 60, "status": "DISPONIVEL"}, path)
        report = build_evaluation_report(path, "WIN")
        self.assertEqual({row["horizon"] for row in report["temporal"]}, {"5m", "60m"})
        self.assertEqual({row["available"] for row in report["temporal"]}, {1})
        try: Path(path).unlink(missing_ok=True)
        except OSError: pass


if __name__ == "__main__":
    unittest.main()
