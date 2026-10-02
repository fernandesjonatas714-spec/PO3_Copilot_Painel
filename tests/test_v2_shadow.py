import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

import po3.shadow_mode as shadow
from po3.shadow_mode import process_pending_shadow_states, run_shadow_for_market_state, shadow_report
from po3.storage.market_repository import insert_market_state
from po3.storage.migrations import migrate
from po3.v2_config import flags


class ShadowModeTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        Path(self.path).unlink(missing_ok=True)
        migrate(self.path)
        self.previous = shadow.SHADOW_MODE_ENABLED

    def tearDown(self):
        shadow.SHADOW_MODE_ENABLED = self.previous
        try:
            Path(self.path).unlink(missing_ok=True)
        except OSError:
            pass

    def state(self, symbol="WIN", cutoff="2026-01-01T10:00:00Z"):
        return {"ativo": symbol, "timestamp": cutoff, "preco_atual": 100,
                "nested": {"future_price": 999, "percentage_change": 10}, "outcomes": {"future_high": 999}}

    def runner_result(self):
        ids = ("regime_macro", "contexto_domestico", "contexto_tecnico", "risco_evento", "conflito_contexto", "contexto_operacional")
        return {"decisoes": [{"id_decisao": key, "decisao": "NEUTRO", "confianca": "MEDIA", "status_evidencias": "COMPLETAS"} for key in ids],
                "gate": {"status": "VALIDO"}, "consenso": {"status": "CONSENSO"},
                "modelo_utilizado": "modelo-fake", "fallback_utilizado": True, "reparo_json_utilizado": True}

    def add_state(self, symbol="WIN", cutoff="2026-01-01T10:00:00Z"):
        return insert_market_state(self.state(symbol, cutoff), self.path, cutoff_at_utc=cutoff, symbol=symbol)

    def test_flag_false_does_not_call_runner(self):
        state_id = self.add_state()
        called = []
        result = run_shadow_for_market_state(self.path, state_id, lambda payload: called.append(payload))
        self.assertFalse(called)
        self.assertEqual(result["status"], "DESABILITADO")
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM shadow_runs").fetchone()[0], 0)

    def test_exact_payload_sanitized_and_persisted(self):
        shadow.SHADOW_MODE_ENABLED = True
        state_id = self.add_state()
        received = []
        result = run_shadow_for_market_state(self.path, state_id, lambda payload: received.append(payload) or self.runner_result(), model_configured="modelo-fake")
        self.assertEqual(result["status"], "OK")
        self.assertNotIn("future_price", json.dumps(received[0]))
        self.assertNotIn("percentage_change", json.dumps(received[0]))
        self.assertNotIn("outcomes", received[0])
        self.assertNotIn("market_state_id", received[0])
        self.assertNotIn("symbol", received[0])
        self.assertNotIn("cutoff_at_utc", received[0])
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("SELECT status,gate_status,consensus_status,model_used,fallback_used,repair_used,decisions_json FROM shadow_runs").fetchone()
        self.assertEqual(row[:6], ("OK", "VALIDO", "CONSENSO", "modelo-fake", 1, 1))
        self.assertEqual(len(json.loads(row[6])), 6)

    def test_idempotency_and_restart_do_not_call_runner_again(self):
        shadow.SHADOW_MODE_ENABLED = True
        state_id = self.add_state()
        calls = []
        runner = lambda payload: calls.append(payload) or self.runner_result()
        first = run_shadow_for_market_state(self.path, state_id, runner, model_configured="modelo-fake")
        second = run_shadow_for_market_state(self.path, state_id, runner, model_configured="modelo-fake")
        self.assertTrue(first["created"])
        self.assertFalse(second["created"])
        self.assertEqual(len(calls), 1)
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM shadow_runs").fetchone()[0], 1)

    def test_orphan_running_shadow_is_recovered_in_same_row(self):
        shadow.SHADOW_MODE_ENABLED = True
        state_id = self.add_state()
        with sqlite3.connect(self.path) as conn:
            conn.execute("""INSERT INTO shadow_runs
                (market_state_id,symbol,cutoff_at_utc,state_hash,shadow_mode_version,
                 decision_engine_version,prompt_version,schema_version,model_configured,
                 decisions_json,status,created_at_utc,worker_owner_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (state_id, "WIN", "2026-01-01T10:00:00Z", "hash", shadow.SHADOW_MODE_VERSION,
                 "1.1.0", "1.1.0", "2.0.0", "modelo-fake", "[]", "RUNNING",
                 "2020-01-01T00:00:00+00:00", "worker-antigo"))
            run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        result = run_shadow_for_market_state(self.path, state_id, lambda payload: self.runner_result(), model_configured="modelo-fake")
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("SELECT id,status,recovered_after_restart FROM shadow_runs").fetchone()
            count = conn.execute("SELECT COUNT(*) FROM shadow_runs").fetchone()[0]
        self.assertEqual(result["created"], True)
        self.assertEqual(row, (run_id, "OK", 1))
        self.assertEqual(count, 1)

    def test_recent_running_shadow_with_active_owner_is_not_stolen(self):
        shadow.SHADOW_MODE_ENABLED = True
        state_id = self.add_state()
        with sqlite3.connect(self.path) as conn:
            conn.execute("""INSERT INTO shadow_runs
                (market_state_id,symbol,cutoff_at_utc,state_hash,shadow_mode_version,
                 decision_engine_version,prompt_version,schema_version,model_configured,
                 decisions_json,status,created_at_utc,worker_owner_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (state_id, "WIN", "2026-01-01T10:00:00Z", "hash", shadow.SHADOW_MODE_VERSION,
                 "1.1.0", "1.1.0", "2.0.0", "modelo-fake", "[]", "RUNNING",
                 "2026-01-01T10:00:00+00:00", "worker-ativo"))
            conn.execute("INSERT INTO collector_leases VALUES (?,?,?,?,?,?,?)",
                         ("po3-ai", "WIN", "worker-ativo", 1, "2026-01-01T10:00:00+00:00",
                          "2026-01-01T10:01:00+00:00", "2999-01-01T00:00:00+00:00"))
        calls = []
        result = run_shadow_for_market_state(self.path, state_id,
                                              lambda payload: calls.append(payload) or self.runner_result(),
                                              model_configured="modelo-fake")
        self.assertFalse(result["created"])
        self.assertFalse(calls)

    def test_error_does_not_block_next_state(self):
        shadow.SHADOW_MODE_ENABLED = True
        first, second = self.add_state(cutoff="2026-01-01T10:00:00Z"), self.add_state(cutoff="2026-01-01T10:05:00Z")
        calls = []
        def runner(payload):
            calls.append(payload)
            if len(calls) == 1:
                raise RuntimeError("falha")
            return self.runner_result()
        summary = process_pending_shadow_states(self.path, runner, limit=10, model_configured="modelo-fake")
        self.assertEqual((summary["created"], summary["ERRO"], summary["OK"]), (2, 1, 1))

    def test_pending_processing_order_and_symbol_report_filter(self):
        shadow.SHADOW_MODE_ENABLED = True
        self.add_state("DOL", "2026-01-01T10:05:00Z")
        self.add_state("WIN", "2026-01-01T10:00:00Z")
        process_pending_shadow_states(self.path, lambda payload: self.runner_result(), model_configured="modelo-fake")
        self.assertEqual(shadow_report(self.path, "WIN")["total_runs"], 1)
        self.assertEqual(shadow_report(self.path, "DOL")["total_runs"], 1)
        self.assertEqual(shadow_report(self.path)["OK"], 2)

    def test_backlog_progresses_with_limit_one_without_starvation(self):
        shadow.SHADOW_MODE_ENABLED = True
        states = [self.add_state(cutoff=f"2026-01-01T10:0{i}:00Z") for i in range(3)]
        seen = []
        runner = lambda payload: seen.append(payload["timestamp"]) or self.runner_result()
        for expected in states:
            summary = process_pending_shadow_states(self.path, runner, limit=1, model_configured="modelo-fake")
            self.assertEqual((summary["created"], summary["ignored"]), (1, 0))
        fourth = process_pending_shadow_states(self.path, runner, limit=1, model_configured="modelo-fake")
        self.assertEqual((fourth["created"], fourth["ignored"], len(seen)), (0, 0, 3))
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM shadow_runs").fetchone()[0], 3)
        self.assertEqual(seen, [f"2026-01-01T10:0{i}:00Z" for i in range(3)])

    def test_backlog_runner_order_uses_cutoff_then_id(self):
        shadow.SHADOW_MODE_ENABLED = True
        first = self.add_state(cutoff="2026-01-01T10:05:00Z")
        second = self.add_state(cutoff="2026-01-01T10:00:00Z")
        third = self.add_state(symbol="DOL", cutoff="2026-01-01T10:00:00Z")
        received = []
        process_pending_shadow_states(self.path, lambda payload: received.append(payload["timestamp"]) or self.runner_result(), limit=10, model_configured="modelo-fake")
        self.assertEqual(received, ["2026-01-01T10:00:00Z", "2026-01-01T10:00:00Z", "2026-01-01T10:05:00Z"])
        self.assertEqual([second, third, first], sorted([second, third, first], key=lambda value: (self._cutoff(value), value)))

    def _cutoff(self, state_id):
        with sqlite3.connect(self.path) as conn:
            return conn.execute("SELECT cutoff_at_utc FROM market_states WHERE id=?", (state_id,)).fetchone()[0]

    def test_concurrent_same_configuration_creates_one_run_and_calls_runner_once(self):
        shadow.SHADOW_MODE_ENABLED = True
        state_id = self.add_state()
        calls = []
        lock = threading.Lock()
        def runner(payload):
            with lock:
                calls.append(payload)
            time.sleep(0.05)
            return self.runner_result()
        results = []
        def invoke():
            results.append(run_shadow_for_market_state(self.path, state_id, runner, model_configured="modelo-fake"))
        threads = [threading.Thread(target=invoke) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(results), 2)
        self.assertEqual(sum(result["created"] for result in results), 1)
        self.assertEqual(sum(result.get("reason") == "IDEMPOTENTE" for result in results), 1)
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM shadow_runs").fetchone()[0], 1)

    def test_report_is_read_only_and_flag_remains_false_by_default(self):
        before = Path(self.path).read_bytes()
        shadow_report(self.path)
        self.assertEqual(before, Path(self.path).read_bytes())
        self.assertFalse(flags()["AUTO_DECISION_ENGINE"])
        self.assertFalse(flags()["SHADOW_MODE_ENABLED"])


if __name__ == "__main__":
    unittest.main()
