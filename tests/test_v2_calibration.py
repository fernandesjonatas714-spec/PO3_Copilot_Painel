import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from po3.calibration import backfill_observations, calibration_report, record_observation_for_analysis, state_hash
from po3.storage.market_repository import insert_market_state, upsert_outcome
from po3.storage.migrations import migrate
from po3.learning_store import save_analysis


class CalibrationObservationTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        Path(self.path).unlink(missing_ok=True)
        migrate(self.path)

    def tearDown(self):
        try: Path(self.path).unlink(missing_ok=True)
        except OSError: pass

    def state(self, timestamp="2026-01-02T13:00:00+00:00"):
        return {"ativo": "WIN", "timestamp": timestamp, "preco_atual": 100,
                "tecnico": {}, "mercado_domestico": {}, "mercado_externo": {},
                "calendario": {}, "noticias": [], "fontes": [], "qualidade_dados": {}, "snapshot": {}}

    def analysis(self, state, decision="CONTEXTO_COMPRADOR", confidence="ALTA"):
        return {"versoes": {"decision_engine": "1.0.0", "prompt": "1.0.0"},
                "state": state, "decisoes": [{"id_decisao": "contexto_operacional", "decisao": decision,
                "confianca": confidence}], "gate": {"status": "VALIDO"},
                "consenso": {"status": "CONSENSO"}, "modelo_configurado": "qwen/qwen3.8-27b:free",
                "modelo_utilizado": "qwen/qwen3.8-27b:free", "fallback_utilizado": False,
                "reparo_json_utilizado": False}

    def add_analysis(self, state, decision="CONTEXTO_COMPRADOR", confidence="ALTA"):
        with sqlite3.connect(self.path) as c:
            cur = c.execute("INSERT INTO analysis_runs (created_at,symbol,price,bias,response,context_json,snapshot_json) VALUES (?,?,?,?,?,?,?)",
                            ("2026-01-02T13:00:00+00:00", "WIN", 100, "neutro", "texto",
                             json.dumps({"_structured": self.analysis(state, decision, confidence)}), json.dumps(state)))
            return cur.lastrowid

    def add_outcome(self, state_id, horizon="5m", change=.01):
        upsert_outcome({"market_state_id": state_id, "symbol": "WIN", "horizon_code": horizon,
                        "target_at_utc": "2026-01-02T13:05:00+00:00", "start_price": 100,
                        "future_price": 100 + change, "future_high": 101, "future_low": 99,
                        "high_delta": 1, "low_delta": -1, "absolute_change": change,
                        "percentage_change": change / 100, "candles_observed": 5,
                        "status": "DISPONIVEL"}, self.path)

    def test_exact_match_and_idempotence(self):
        state = self.state()
        state_id = insert_market_state(state, self.path, cutoff_at_utc=state["timestamp"], symbol="WIN")
        analysis_id = self.add_analysis(state)
        self.assertEqual(record_observation_for_analysis(analysis_id, self.path), "MATCHED")
        self.assertEqual(record_observation_for_analysis(analysis_id, self.path), "MATCHED")
        with sqlite3.connect(self.path) as c:
            self.assertEqual(c.execute("select count(*) from decision_observations").fetchone()[0], 1)
            self.assertEqual(c.execute("select market_state_id from decision_observations").fetchone()[0], state_id)

    def test_unmatched_does_not_use_nearby_timestamp(self):
        state = self.state()
        insert_market_state(state, self.path, cutoff_at_utc=state["timestamp"], symbol="WIN")
        analysis_id = self.add_analysis(self.state("2026-01-02T13:01:00+00:00"))
        self.assertEqual(record_observation_for_analysis(analysis_id, self.path), "UNMATCHED")

    def test_ambiguous_when_canonical_state_has_two_candidates(self):
        state = self.state()
        insert_market_state(state, self.path, cutoff_at_utc="2026-01-02T13:00:00+00:00", symbol="WIN")
        insert_market_state(state, self.path, cutoff_at_utc="2026-01-02T13:05:00+00:00", symbol="WIN")
        analysis_id = self.add_analysis(state)
        self.assertEqual(record_observation_for_analysis(analysis_id, self.path), "AMBIGUOUS")

    def test_backfill_reports_all_link_statuses(self):
        state = self.state()
        insert_market_state(state, self.path, cutoff_at_utc=state["timestamp"], symbol="WIN")
        self.add_analysis(state)
        self.add_analysis(self.state("2026-01-02T13:01:00+00:00"))
        self.assertEqual(backfill_observations(self.path)["total_analysis_runs"], 2)
        result = backfill_observations(self.path)
        self.assertEqual((result["MATCHED"], result["UNMATCHED"], result["AMBIGUOUS"]), (1, 1, 0))

    def test_observational_metrics_separate_confidence_horizon_and_alignment(self):
        for index, (decision, confidence, change) in enumerate((("CONTEXTO_COMPRADOR", "ALTA", .01), ("CONTEXTO_VENDEDOR", "MEDIA", -.01))):
            state = self.state(f"2026-01-02T13:{index:02d}:00+00:00")
            state_id = insert_market_state(state, self.path, cutoff_at_utc=state["timestamp"], symbol="WIN")
            analysis_id = self.add_analysis(state, decision, confidence)
            self.assertEqual(record_observation_for_analysis(analysis_id, self.path), "MATCHED")
            self.add_outcome(state_id, "5m", change)
        report = calibration_report(self.path, "WIN", generated_at_utc=datetime(2026, 1, 2, tzinfo=timezone.utc))
        self.assertEqual(report["horizons"]["5m"]["ALTA"]["aligned_count"], 1)
        self.assertEqual(report["horizons"]["5m"]["MEDIA"]["aligned_count"], 1)
        self.assertEqual(report["horizons"]["15m"]["ALTA"]["sample_size"], 0)
        self.assertNotIn("taxa_acerto", json.dumps(report))
        self.assertNotIn("win_rate", json.dumps(report))

    def test_abstentions_have_no_directional_alignment(self):
        state = self.state()
        state_id = insert_market_state(state, self.path, cutoff_at_utc=state["timestamp"], symbol="WIN")
        analysis_id = self.add_analysis(state, "AGUARDAR", "BAIXA")
        record_observation_for_analysis(analysis_id, self.path)
        self.add_outcome(state_id)
        report = calibration_report(self.path, "WIN")
        self.assertEqual(report["horizons"]["5m"]["BAIXA"]["sample_size"], 0)
        self.assertEqual(report["abstentions"]["5m:AGUARDAR"]["sample_size"], 1)

    def test_market_state_and_outcome_unchanged_by_report(self):
        state = self.state()
        state_id = insert_market_state(state, self.path, cutoff_at_utc=state["timestamp"], symbol="WIN")
        analysis_id = self.add_analysis(state)
        record_observation_for_analysis(analysis_id, self.path)
        self.add_outcome(state_id)
        with sqlite3.connect(self.path) as c:
            before = c.execute("select state_json from market_states").fetchone()[0]
            outcome_before = c.execute("select percentage_change from observed_outcomes").fetchone()[0]
        calibration_report(self.path, "WIN")
        with sqlite3.connect(self.path) as c:
            self.assertEqual(c.execute("select state_json from market_states").fetchone()[0], before)
            self.assertEqual(c.execute("select percentage_change from observed_outcomes").fetchone()[0], outcome_before)

    def test_state_hash_ignores_only_metadata(self):
        state = self.state()
        altered = {**state, "captured_at_utc": "later"}
        self.assertEqual(state_hash(state), state_hash(altered))

    def test_save_analysis_persists_observation_without_breaking_operational_save(self):
        snapshot = type("Snapshot", (), {"symbol": "WIN", "last_price": 100, "macro": {"bias": "neutro"}})()
        analysis_id = save_analysis(snapshot, {"_structured": self.analysis(self.state())}, "texto", self.path)
        with sqlite3.connect(self.path) as c:
            row = c.execute("select analysis_run_id,link_status from decision_observations").fetchone()
        self.assertEqual(row, (analysis_id, "UNMATCHED"))


if __name__ == "__main__":
    unittest.main()
