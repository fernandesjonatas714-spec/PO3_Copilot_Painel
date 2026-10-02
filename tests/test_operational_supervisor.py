import json
import ast
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from po3.operational_supervisor import build_supervisor_snapshot, operational_state_hash, supervisor_ai_gate
from po3.storage.migrations import migrate
from po3.v2_config import SUPERVISOR_AI_ENABLED


UTC = timezone.utc


class OperationalSupervisorTests(unittest.TestCase):
    def setUp(self):
        fd, name = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        Path(name).unlink()
        self.path = Path(name)
        self._connections = []
        migrate(self.path)
        self.now = datetime(2026, 10, 1, 14, 12, tzinfo=UTC)  # 11:12 BRT
        self._insert_runtime(status="ATIVA", feed="LIVE", clock="ALIGNED")

    def tearDown(self):
        for conn in self._connections:
            conn.close()
        try:
            self.path.unlink(missing_ok=True)
        except PermissionError:
            # O Windows pode manter o handle SQLite até o fim do processo de testes.
            pass

    def _conn(self):
        conn = sqlite3.connect(self.path)
        self._connections.append(conn)
        return conn

    def _insert_runtime(self, status="ATIVA", feed="LIVE", clock="ALIGNED"):
        with self._conn() as c:
            c.execute("""INSERT OR REPLACE INTO collector_runtime_status
                (symbol,status,feed_lag_seconds,last_closed_at_utc,last_tick_at_utc,detail,updated_at,
                 feed_liveness_status,clock_alignment_status,detected_offset_seconds,normalized_tick_at_utc)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                ("WINV26", status, 1.0, self.now.isoformat(), self.now.isoformat(), "ok", self.now.isoformat(), feed, clock, 0.0, self.now.isoformat()))

    def _bar(self, timestamp, close=100.0):
        with self._conn() as c:
            c.execute("""INSERT INTO market_bars_m1
                (symbol,timestamp_utc,open,high,low,close,tick_volume,real_volume,spread,source,schema_version,created_at,source_timestamp_raw,time_offset_seconds)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                ("WINV26", timestamp.isoformat(), close, close + 1, close - 1, close, 1, 1, 0, "test", "2.0", timestamp.isoformat(), int(timestamp.timestamp()), 0))

    def _state(self, cutoff, state_id=None, start_status="DISPONIVEL", start_bar=None, start_price=100.0):
        start_bar = start_bar or cutoff - timedelta(minutes=1)
        payload = {"start_bar_open_time": start_bar.isoformat(), "start_price": start_price, "start_price_status": start_status}
        with self._conn() as c:
            c.execute("""INSERT INTO market_states
              (id,symbol,cutoff_at_utc,created_at,market_state_version,decision_engine_version,prompt_version,schema_version,state_json,state_hash,sources_json,status)
              VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
              (state_id, "WINV26", cutoff.isoformat(), cutoff.isoformat(), "2.0", "v2", "v2", "2.0.0", json.dumps(payload), f"hash-{cutoff.isoformat()}", "{}", "CAPTURADO"))

    def _valid_three(self):
        for i in range(3):
            cutoff = self.now - timedelta(minutes=12 - i * 5)
            self._bar(cutoff - timedelta(minutes=1))
            self._state(cutoff)

    def test_read_only_and_closed_session(self):
        before = self._conn().execute("select count(*) from market_states").fetchone()[0]
        snap = build_supervisor_snapshot(str(self.path), "WINV26", datetime(2026, 10, 1, 22, 0, tzinfo=UTC))
        self.assertEqual(snap["overall_status"], "AGUARDANDO_SESSAO")
        self.assertEqual(self._conn().execute("select count(*) from market_states").fetchone()[0], before)

    def test_stale_off_session_does_not_become_feed_attention(self):
        self._insert_runtime(feed="STALE", clock="UNSTABLE_OFFSET")
        snap = build_supervisor_snapshot(str(self.path), "WINV26", datetime(2026, 10, 1, 22, 0, tzinfo=UTC))
        self.assertEqual(snap["overall_status"], "AGUARDANDO_SESSAO")

    def test_active_stale_and_invalid_clock(self):
        self._insert_runtime(feed="STALE", clock="ALIGNED")
        self.assertEqual(build_supervisor_snapshot(str(self.path), "WINV26", self.now)["overall_status"], "ATENCAO_FEED")
        self._insert_runtime(feed="LIVE", clock="UNSTABLE_OFFSET")
        self.assertEqual(build_supervisor_snapshot(str(self.path), "WINV26", self.now)["overall_status"], "ATENCAO_CLOCK")

    def test_integrity_status_and_security_flags(self):
        snap = build_supervisor_snapshot(str(self.path), "WINV26", self.now)
        self.assertEqual(snap["database"]["integrity_status"], "ok")
        with patch("po3.operational_supervisor.flags", return_value={"AUTO_DECISION_ENGINE": True, "SHADOW_MODE_ENABLED": False, "REPLAY_ENABLED": False, "CALIBRATION_ENABLED": False, "MODEL_BENCHMARK_ENABLED": False}):
            self.assertEqual(build_supervisor_snapshot(str(self.path), "WINV26", self.now)["overall_status"], "ATENCAO_SEGURANCA")

    def test_o1_three_valid_states(self):
        self._valid_three()
        snap = build_supervisor_snapshot(str(self.path), "WINV26", self.now)
        self.assertEqual(snap["o1_validation"]["status"], "APROVADO")
        self.assertEqual(snap["o1_validation"]["valid_states"], 3)

    def test_o1_rejects_duplicate_spacing_start_and_missing_bar(self):
        cutoffs = [self.now - timedelta(minutes=22), self.now - timedelta(minutes=17), self.now - timedelta(minutes=12), self.now - timedelta(minutes=7)]
        for index, cutoff in enumerate(cutoffs):
            self._bar(cutoff - timedelta(minutes=1))
            self._state(cutoff, start_bar=cutoff - timedelta(minutes=2) if index == 1 else None)
        snap = build_supervisor_snapshot(str(self.path), "WINV26", self.now)
        self.assertNotEqual(snap["o1_validation"]["status"], "APROVADO")

    def test_o1_moving_window_uses_three_consecutive_states(self):
        cutoffs = [self.now - timedelta(minutes=22), self.now - timedelta(minutes=17), self.now - timedelta(minutes=12), self.now - timedelta(minutes=7), self.now - timedelta(minutes=2)]
        for index, cutoff in enumerate(cutoffs):
            self._bar(cutoff - timedelta(minutes=1))
            self._state(cutoff, start_bar=cutoff - timedelta(minutes=2) if index == 1 else None)
        snap = build_supervisor_snapshot(str(self.path), "WINV26", self.now)
        self.assertEqual(snap["o1_validation"]["status"], "APROVADO")
        self.assertEqual(len(snap["o1_validation"]["state_ids"]), 3)
        self.assertIn("Cadeia causal aprovada", snap["o1_validation"]["details"])

    def test_o1_four_valid_states_with_gap_never_show_more_than_two(self):
        cutoffs = [self.now - timedelta(minutes=27), self.now - timedelta(minutes=22), self.now - timedelta(minutes=12), self.now - timedelta(minutes=7)]
        for cutoff in cutoffs:
            self._bar(cutoff - timedelta(minutes=1))
            self._state(cutoff)
        snap = build_supervisor_snapshot(str(self.path), "WINV26", self.now)
        self.assertNotEqual(snap["o1_validation"]["status"], "APROVADO")
        self.assertLessEqual(snap["o1_validation"]["valid_states"], 2)

    def test_o1_rejects_wrong_start_bar_and_price(self):
        for i in range(3):
            cutoff = self.now - timedelta(minutes=12 - i * 5)
            self._bar(cutoff - timedelta(minutes=1), close=100)
            self._state(cutoff, start_bar=cutoff - timedelta(minutes=2), start_price=999)
        snap = build_supervisor_snapshot(str(self.path), "WINV26", self.now)
        self.assertNotEqual(snap["o1_validation"]["status"], "APROVADO")

    def test_o1_rejects_missing_exact_start_bar_without_fallback(self):
        for i in range(3):
            cutoff = self.now - timedelta(minutes=12 - i * 5)
            self._state(cutoff)
        snap = build_supervisor_snapshot(str(self.path), "WINV26", self.now)
        self.assertNotEqual(snap["o1_validation"]["status"], "APROVADO")

    def test_security_tables_read_only_and_ai_default_off(self):
        before = {t: self._conn().execute(f"select count(*) from {t}").fetchone()[0] for t in ("decision_observations", "shadow_runs")}
        snap = build_supervisor_snapshot(str(self.path), "WINV26", self.now)
        self.assertFalse(SUPERVISOR_AI_ENABLED)
        self.assertEqual(before["decision_observations"], snap["database"]["decision_observations"])
        self.assertEqual(before["shadow_runs"], snap["database"]["shadow_runs"])

    def test_supervisor_has_explicit_sao_paulo_timezone(self):
        snap = build_supervisor_snapshot(str(self.path), "WINV26", self.now)
        self.assertIn("-03:00", snap["session"]["local_time"])

    def test_ai_gate_same_hash_does_not_call(self):
        snap = build_supervisor_snapshot(str(self.path), "WINV26", self.now)
        state = {"last_supervisor_hash": operational_state_hash(snap), "last_supervisor_status": snap["overall_status"], "last_supervisor_ai_at": self.now - timedelta(minutes=1)}
        self.assertFalse(supervisor_ai_gate(snap, state, self.now)["should_call"])

    def test_ai_gate_normal_change_calls_and_critical_transition_bypasses_once(self):
        snap = build_supervisor_snapshot(str(self.path), "WINV26", self.now)
        state = {"last_supervisor_hash": "old", "last_supervisor_status": "OPERACAO_NORMAL", "last_supervisor_ai_at": self.now - timedelta(seconds=10)}
        snap["overall_status"] = "ATENCAO_FEED"
        decision = supervisor_ai_gate(snap, state, self.now)
        self.assertTrue(decision["should_call"])
        state.update({"last_supervisor_hash": decision["hash"], "last_supervisor_status": "ATENCAO_FEED", "last_supervisor_ai_at": self.now})
        snap["collector"]["detected_offset_seconds"] = 123
        self.assertFalse(supervisor_ai_gate(snap, state, self.now + timedelta(seconds=30))["should_call"])

    def test_ai_gate_defers_change_and_allows_it_after_cooldown(self):
        snap_a = build_supervisor_snapshot(str(self.path), "WINV26", self.now)
        state = {"last_supervisor_hash": operational_state_hash(snap_a), "last_supervisor_status": "AGUARDANDO_SESSAO", "last_supervisor_ai_at": self.now}
        snap_b = dict(snap_a)
        snap_b["overall_status"] = "VALIDANDO_CAUSALIDADE"
        first = supervisor_ai_gate(snap_b, state, self.now + timedelta(seconds=30))
        self.assertFalse(first["should_call"])
        state["last_supervisor_status"] = first["status"]
        second = supervisor_ai_gate(snap_b, state, self.now + timedelta(minutes=5, seconds=1))
        self.assertTrue(second["should_call"])

    def test_ai_gate_critical_persistent_change_respects_cooldown(self):
        snap = build_supervisor_snapshot(str(self.path), "WINV26", self.now)
        snap["overall_status"] = "ATENCAO_FEED"
        state = {"last_supervisor_hash": "old", "last_supervisor_status": "OPERACAO_NORMAL", "last_supervisor_ai_at": self.now}
        first = supervisor_ai_gate(snap, state, self.now + timedelta(seconds=1))
        self.assertTrue(first["should_call"])
        state.update({"last_supervisor_hash": first["hash"], "last_supervisor_status": first["status"], "last_supervisor_ai_at": self.now + timedelta(seconds=1)})
        snap["collector"]["feed_liveness_status"] = "LIVE"
        self.assertFalse(supervisor_ai_gate(snap, state, self.now + timedelta(seconds=30))["should_call"])

    def test_supervisor_fragment_is_fixed_and_has_no_worker_start(self):
        source = Path(__file__).parents[1].joinpath("macro_app.py").read_text(encoding="utf-8")
        self.assertIn('@st.fragment(run_every="15s")', source)
        self.assertIn('run_every=f"{seconds}s" if auto else None', source)
        self.assertNotIn("po3.launcher", source)

    def test_real_narrative_records_status_and_allows_critical_transition(self):
        snapshot = {"symbol": "WINV26", "overall_status": "OPERACAO_NORMAL", "session": {}, "collector": {},
                    "lease": {}, "latest_market_state": None, "outcomes": {}, "security": {}, "o1_validation": {}}
        source = Path(__file__).parents[1].joinpath("macro_app.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == "_supervisor_ai_text")
        source_function = ast.get_source_segment(source, function) or ""
        self.assertIn('st.session_state["last_supervisor_status"] = decision["status"]', source_function)
        state = {"last_supervisor_hash": "narrated", "last_supervisor_status": "OPERACAO_NORMAL", "last_supervisor_ai_at": self.now}
        changed = dict(snapshot)
        changed["overall_status"] = "ATENCAO_FEED"
        changed["collector"] = {"feed_liveness_status": "STALE"}
        decision = supervisor_ai_gate(changed, state, self.now + timedelta(seconds=30))
        self.assertTrue(decision["critical_transition"])
        self.assertTrue(decision["should_call"])

    def test_same_hash_is_stable(self):
        snap = build_supervisor_snapshot(str(self.path), "WINV26", self.now)
        self.assertEqual(operational_state_hash(snap), operational_state_hash(snap))


if __name__ == "__main__":
    unittest.main()
