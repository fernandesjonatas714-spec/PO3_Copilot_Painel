import copy
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from po3.replay_engine import (
    compare_replay_with_observation,
    replay_from_db,
    replay_market_states,
    sanitize_replay_state,
)
from po3.storage.market_repository import insert_market_state
from po3.storage.migrations import migrate
from po3.v2_config import flags


class ReplayTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        Path(self.path).unlink(missing_ok=True)
        migrate(self.path)

    def tearDown(self):
        try:
            Path(self.path).unlink(missing_ok=True)
        except OSError:
            pass

    def state(self, symbol="WIN", cutoff="2026-01-01T10:00:00+00:00", **extra):
        value = {"ativo": symbol, "timestamp": cutoff, "preco_atual": 100, **extra}
        return value

    def test_order_cutoff_then_id_and_deterministic_hash(self):
        states = [{"id": 2, "cutoff_at_utc": "2026-01-01T10:05:00Z", **self.state(cutoff="2026-01-01T10:05:00Z")},
                  {"id": 1, "cutoff_at_utc": "2026-01-01T10:00:00Z", **self.state(cutoff="2026-01-01T10:00:00Z")}]
        result = replay_market_states(states, lambda payload: payload["timestamp"], run_at_utc=None)
        self.assertEqual([row["market_state_id"] for row in result], [1, 2])
        again = replay_market_states(states, lambda payload: payload["timestamp"], run_at_utc=None)
        self.assertEqual([row["state_hash"] for row in result], [row["state_hash"] for row in again])

    def test_recursive_future_sanitization(self):
        state = {"nested": {"future_price": 999, "percentage_change": 10, "safe": 1},
                 "outcomes": {"future_high": 999}, "future_bars": [1], "ok": True}
        sanitized = sanitize_replay_state(state)
        encoded = json.dumps(sanitized).lower()
        for key in ("future_price", "percentage_change", "future_high", "future_bars", "outcomes"):
            self.assertNotIn(key, encoded)
        self.assertEqual(sanitized["nested"]["safe"], 1)

    def test_runner_receives_copy_and_market_state_is_unchanged(self):
        state = {"id": 1, "cutoff_at_utc": "2026-01-01T10:00:00Z", **self.state(), "nested": {"future_price": 9}}
        original = copy.deepcopy(state)
        received = []
        def runner(payload):
            received.append(payload)
            payload["preco_atual"] = 999
            return {"ok": True}
        result = replay_market_states([state], runner)
        self.assertEqual(state, original)
        self.assertEqual(result[0]["status"], "OK")
        self.assertNotIn("future_price", json.dumps(received[0]))

    def test_error_isolated_and_statuses_are_explicit(self):
        states = [{"id": 1, "cutoff_at_utc": "2026-01-01T10:00:00Z", **self.state()},
                  {"id": 2, "cutoff_at_utc": "2026-01-01T10:01:00Z", **self.state(cutoff="2026-01-01T10:01:00Z")}]
        def runner(payload):
            if payload["timestamp"].endswith("10:00:00+00:00"):
                raise ValueError("falha controlada")
            return {"ok": True}
        result = replay_market_states(states, runner)
        self.assertEqual([row["status"] for row in result], ["ERRO", "OK"])
        self.assertEqual(result[0]["error_type"], "ValueError")

    def test_db_filters_symbol_cutoffs_and_limit(self):
        insert_market_state(self.state("WIN", "2026-01-01T10:00:00Z"), self.path, cutoff_at_utc="2026-01-01T10:00:00Z", symbol="WIN")
        insert_market_state(self.state("DOL", "2026-01-01T10:05:00Z"), self.path, cutoff_at_utc="2026-01-01T10:05:00Z", symbol="DOL")
        insert_market_state(self.state("WIN", "2026-01-01T10:10:00Z"), self.path, cutoff_at_utc="2026-01-01T10:10:00Z", symbol="WIN")
        runner = lambda payload: payload["ativo"]
        self.assertEqual(len(replay_from_db(self.path, runner, symbol="WIN")), 2)
        self.assertEqual(len(replay_from_db(self.path, runner, start_cutoff="2026-01-01T10:05:00Z", end_cutoff="2026-01-01T10:10:00Z")), 2)
        self.assertEqual(len(replay_from_db(self.path, runner, limit=1)), 1)

    def test_db_is_read_only_and_outcomes_are_not_used(self):
        state_id = insert_market_state(self.state(), self.path, cutoff_at_utc="2026-01-01T10:00:00Z", symbol="WIN")
        with sqlite3.connect(self.path) as conn:
            conn.execute("INSERT INTO observed_outcomes (market_state_id,symbol,horizon_code,target_at_utc,start_price,status,schema_version,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                         (state_id, "WIN", "5m", "2026-01-01T10:05:00Z", 100, "DISPONIVEL", "2.0", "x", "x"))
        before = Path(self.path).read_bytes()
        replay_from_db(self.path, lambda payload: payload["ativo"])
        self.assertEqual(before, Path(self.path).read_bytes())

    def _add_observation(self, state_id, decisions):
        with sqlite3.connect(self.path) as conn:
            conn.execute("""INSERT INTO decision_observations
                (analysis_run_id,market_state_id,symbol,decision_state_hash,link_status,decisions_json,
                 gate_status,consensus_status,schema_version,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (1, state_id, "WIN", "hash", "MATCHED", json.dumps(decisions), "VALIDO", "CONSENSO", "2.0", "x"))

    def test_compare_matched_equal_and_different_decisions(self):
        state_id = insert_market_state(self.state(), self.path, cutoff_at_utc="2026-01-01T10:00:00Z", symbol="WIN")
        decisions = [{"id_decisao": "regime_macro", "decisao": "MISTO"}]
        self._add_observation(state_id, decisions)
        equal = compare_replay_with_observation(self.path, [{"market_state_id": state_id, "result": {"decisoes": decisions}}])
        different = compare_replay_with_observation(self.path, [{"market_state_id": state_id, "result": {"decisoes": [{"id_decisao": "regime_macro", "decisao": "NEUTRO"}]}}])
        self.assertEqual(equal[0]["decisions"]["regime_macro"], "IGUAL")
        self.assertEqual(different[0]["decisions"]["regime_macro"], "DIFERENTE")

    def test_compare_without_exact_matched_observation_is_unavailable(self):
        result = compare_replay_with_observation(self.path, [{"market_state_id": 999, "result": {}}])
        self.assertEqual(result[0]["status"], "INDISPONIVEL")

    def test_replay_flag_is_disabled_and_no_llm_dependency(self):
        self.assertFalse(flags()["REPLAY_ENABLED"])
        source = Path("po3/replay_engine.py").read_text(encoding="utf-8")
        self.assertNotIn("from po3.ai_service", source)
        self.assertNotIn("import openai", source.lower())


if __name__ == "__main__":
    unittest.main()
