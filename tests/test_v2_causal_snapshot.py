import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from po3.collection.mt5_m1_collector import CollectorConfig, _default_snapshot_provider
from po3.collection.time_alignment import Mt5TimeAlignmentDetector
from po3.market_state_store import freeze_market_state
from po3.mt5_reader import read_snapshot_at_cutoff
from po3.storage.market_repository import list_states


class CausalFakeMT5:
    TIMEFRAME_M1 = 1
    TIMEFRAME_M5 = 5
    TIMEFRAME_M15 = 15
    TIMEFRAME_M30 = 30
    TIMEFRAME_H1 = 60
    TIMEFRAME_H4 = 240
    TIMEFRAME_D1 = 1440
    TIMEFRAME_W1 = 10080
    TIMEFRAME_MN1 = 43200

    def __init__(self, cutoff):
        self.cutoff = cutoff
        self._periods = {1: 60, 5: 300, 15: 900, 30: 1800, 60: 3600,
                         240: 14400, 1440: 86400, 10080: 604800, 43200: 31 * 86400}

    def initialize(self, *args, **kwargs): return True
    def shutdown(self): return None
    def terminal_info(self): return SimpleNamespace(connected=True)
    def account_info(self): return None
    def version(self): return (1, 0, 0)
    def symbol_info(self, symbol): return SimpleNamespace(name=symbol)
    def symbols_get(self): return []
    def symbol_select(self, symbol, selected): return True
    def symbol_info_tick(self, symbol): raise AssertionError("tick posterior não pode alimentar snapshot causal")

    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        step = self._periods[timeframe]
        rows = []
        for index in range(40, -1, -1):
            opened = self.cutoff - timedelta(seconds=step * index)
            extreme = opened == self.cutoff
            close = 999999.0 if extreme else 100.0 + index
            raw = int(opened.timestamp()) - 10800
            rows.append({"time": raw, "open": close, "high": close + 1,
                         "low": close - 1, "close": close, "tick_volume": 1})
        return rows


class CausalSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.cutoff = datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc)
        self.fake = CausalFakeMT5(self.cutoff)
        detector = Mt5TimeAlignmentDetector()
        for seconds in (0, 10):
            raw = int((self.cutoff - timedelta(hours=3) + timedelta(seconds=seconds)).timestamp())
            detector.observe(raw_tick_time=raw, raw_tick_time_msc=raw * 1000,
                             observed_at_system_utc=self.cutoff + timedelta(seconds=seconds))
        self.detector = detector

    def test_default_provider_uses_causal_snapshot_and_same_offset(self):
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as handle:
            terminal = handle.name
        try:
            with patch("po3.mt5_reader._load_package", return_value=self.fake):
                snapshot, _ = _default_snapshot_provider(
                    CollectorConfig("WIN", ":memory:", terminal_path=terminal),
                    self.cutoff, self.detector)
            self.assertEqual(snapshot.as_of, self.cutoff)
            self.assertEqual(snapshot.source, "MT5 causal")
            self.assertEqual(snapshot.last_price, 101.0)
            for timeframe in ("M1", "M5", "M15", "D1"):
                self.assertTrue(snapshot.bars[timeframe])
                for row in snapshot.bars[timeframe]:
                    self.assertLessEqual(row["close_time"], self.cutoff)
                    self.assertLessEqual(row["known_at"], self.cutoff)
                    self.assertNotEqual(row["close"], 999999.0)
            self.assertTrue(all(str(v.get("as_of", "")).startswith("2026-01-01T17:00")
                                for v in snapshot.macro["frames"].values()))
        finally:
            Path(terminal).unlink(missing_ok=True)

    def test_snapshot_and_collector_use_same_timestamp_normalization(self):
        raw = int((self.cutoff - timedelta(hours=3, minutes=1)).timestamp())
        self.assertEqual(self.detector.normalize(raw), self.cutoff - timedelta(minutes=1))
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as handle:
            terminal = handle.name
        try:
            with patch("po3.mt5_reader._load_package", return_value=self.fake):
                snapshot = read_snapshot_at_cutoff(terminal, "WIN", self.cutoff,
                                                   normalize_timestamp=self.detector.normalize)
            self.assertEqual(snapshot.bars["M1"][-1]["time"], self.cutoff - timedelta(minutes=1))
        finally:
            Path(terminal).unlink(missing_ok=True)

    def test_freeze_preserves_causal_preco_atual_separate_from_start_price(self):
        with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as handle:
            terminal = handle.name
        try:
            with patch("po3.mt5_reader._load_package", return_value=self.fake):
                snapshot = read_snapshot_at_cutoff(terminal, "WIN", self.cutoff,
                                                   normalize_timestamp=self.detector.normalize)
        finally:
            Path(terminal).unlink(missing_ok=True)
        fd, db = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        try:
            freeze_market_state(snapshot, {}, cutoff_at_utc=self.cutoff, db_path=db, symbol="WIN",
                                start_price=77.0, start_bar_open_time=self.cutoff - timedelta(minutes=1),
                                start_price_status="DISPONIVEL")
            state = json.loads(list_states(db, "WIN")[0]["state_json"])
            self.assertEqual(state["preco_atual"], 101.0)
            self.assertEqual(state["snapshot"]["preco_atual"], 101.0)
            self.assertEqual(state["start_price"], 77.0)
            self.assertNotEqual(state["preco_atual"], state["start_price"])
        finally:
            try:
                Path(db).unlink()
            except OSError:
                pass

    def test_daily_cmd_loads_local_mt5_configuration_and_disables_auto_decision(self):
        cmd = Path(__file__).parents[1] / "iniciar_painel_macro.cmd"
        text = cmd.read_text(encoding="utf-8")
        self.assertIn("findstr /b \"MT5_TERMINAL_PATH=\"", text)
        self.assertIn("set \"AUTO_DATA_COLLECTION=true\"", text)
        self.assertIn("set \"AUTO_DECISION_ENGINE=false\"", text)


if __name__ == "__main__": unittest.main()
