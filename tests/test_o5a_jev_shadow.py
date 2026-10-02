import json
import gc
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from po3.jev_questions import JEV_QUESTION_VERSION, build_jev_questions
from po3.jev_service import JevConfig, JevError, send_jev_decisions
from po3.jev_comparison import compare_market_state
from po3.jev_worker import JEV_ENGINE_VERSION, process_pending_jev_states, run_jev_for_market_state
from po3.storage.market_repository import insert_market_state
from po3.storage.migrations import migrate


IDS = ("regime_macro", "contexto_domestico", "contexto_tecnico", "risco_evento", "conflito_contexto", "contexto_operacional")


class _Response:
    status = 200
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return json.dumps(self.body).encode()


class O5AJevTests(unittest.TestCase):
    def setUp(self):
        fd, name = tempfile.mkstemp(suffix=".sqlite"); os.close(fd); Path(name).unlink(missing_ok=True)
        self.path = Path(name); migrate(self.path)

    def tearDown(self):
        gc.collect()
        try:
            self.path.unlink(missing_ok=True)
        except PermissionError:
            # O Windows pode aguardar a coleta de conexões SQLite temporárias.
            pass

    def state(self, calendar=True):
        return {"ativo": "WINV26", "timestamp": datetime.now(timezone.utc).isoformat(), "preco_atual": 100.0,
                "tecnico": {}, "mercado_domestico": {}, "mercado_externo": {}, "calendario": {},
                "noticias": [], "fontes": [], "qualidade_dados": {"mt5_conectado": True, "calendario_disponivel": calendar}, "snapshot": {}}

    def answers(self, score=4, noul=0.2):
        return [{"decision_id": "regime_macro", "answer": "MISTO", "confidence": 0.8},
                {"decision_id": "contexto_domestico", "answer": "NEUTRO", "confidence": 0.8},
                {"decision_id": "contexto_tecnico", "answer": "NEUTRO", "confidence": 0.8},
                {"decision_id": "risco_evento", "raw_score": score, "confidence": 0.8},
                {"decision_id": "conflito_contexto", "noul_probability": noul, "confidence": 0.8},
                {"decision_id": "contexto_operacional", "answer": "AGUARDAR", "confidence": 0.8}]

    def test_questions_have_six_typed_contracts(self):
        questions = build_jev_questions()
        self.assertEqual(set(questions), set(IDS))
        self.assertEqual(questions["risco_evento"]["type"], "score")
        self.assertEqual(questions["conflito_contexto"]["type"], "noul")

    def test_service_normalizes_usage_and_model(self):
        body = {"model": "typesafe/jev-1.13", "answers": self.answers(), "usage": {"input_tokens": 10, "output_tokens": 20, "cost": 0.01}, "id": "req-1"}
        with patch("po3.jev_service.urlopen", return_value=_Response(body)):
            result = send_jev_decisions(self.state(), build_jev_questions(), config=JevConfig("secret"))
        self.assertEqual(result["model_used"], "typesafe/jev-1.13")
        self.assertEqual((result["input_tokens"], result["output_tokens"], result["cost_usd"]), (10, 20, 0.01))

    def test_service_rejects_answer_shape_without_retry(self):
        with patch("po3.jev_service.urlopen", return_value=_Response({"answers": []})):
            with self.assertRaisesRegex(JevError, "seis respostas"):
                send_jev_decisions(self.state(), build_jev_questions(), config=JevConfig("secret"))

    def test_one_call_per_state_and_normalization(self):
        state_id = insert_market_state(self.state(), self.path, cutoff_at_utc="2026-01-01T10:00:00+00:00", symbol="WINV26")
        calls = []
        def runner(state, questions): calls.append((state, questions)); return {"model_used": "typesafe/jev-1.13", "answers": self.answers(score=9, noul=.5), "cost_usd": .2}
        with patch("po3.jev_worker.JEV_SHADOW_ENABLED", True):
            first = run_jev_for_market_state(self.path, state_id, runner)
            second = run_jev_for_market_state(self.path, state_id, runner)
        self.assertEqual(len(calls), 1); self.assertEqual(first["status"], "OK"); self.assertFalse(second["runner_called"])
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("SELECT status,external_call_performed,cost_usd,answers_json FROM jev_shadow_runs").fetchone()
        answers = json.loads(row[3])
        self.assertEqual(row[:3], ("OK", 1, .2)); self.assertEqual(answers[3]["normalized_answer"], 10.0); self.assertEqual(answers[4]["normalized_answer"], "SIM")

    def test_critical_calendar_blocks_without_external_call(self):
        state_id = insert_market_state(self.state(calendar=False), self.path, cutoff_at_utc="2026-01-01T10:00:00+00:00", symbol="WINV26")
        runner = Mock()
        with patch("po3.jev_worker.JEV_SHADOW_ENABLED", True):
            result = run_jev_for_market_state(self.path, state_id, runner)
        runner.assert_not_called(); self.assertEqual(result["status"], "BLOQUEADO")
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute("SELECT external_call_performed,cost_usd,error_type FROM jev_shadow_runs").fetchone(), (0, 0.0, "DADOS_CRITICOS_AUSENTES"))

    def test_risk_ten_does_not_block(self):
        state_id = insert_market_state(self.state(), self.path, cutoff_at_utc="2026-01-01T10:00:00+00:00", symbol="WINV26")
        with patch("po3.jev_worker.JEV_SHADOW_ENABLED", True):
            result = run_jev_for_market_state(self.path, state_id, lambda s, q: {"answers": self.answers(score=9), "cost_usd": 0})
        self.assertEqual(result["status"], "OK")

    def test_fifo_and_symbol_filter(self):
        for minute, symbol in ((0, "WINV26"), (5, "DOL"), (10, "WINV26")):
            insert_market_state(self.state(), self.path, cutoff_at_utc=f"2026-01-01T10:{minute:02d}:00+00:00", symbol=symbol)
        seen = []
        def runner(state, questions): seen.append(state["ativo"]); return {"answers": self.answers()}
        with patch("po3.jev_worker.JEV_SHADOW_ENABLED", True):
            process_pending_jev_states(self.path, runner, symbol="WINV26", limit=1)
            process_pending_jev_states(self.path, runner, symbol="WINV26", limit=1)
        self.assertEqual(seen, ["WINV26", "WINV26"])
        with sqlite3.connect(self.path) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM jev_shadow_runs WHERE symbol='DOL'").fetchone()[0], 0)

    def test_stale_running_run_is_recovered_without_duplicate(self):
        state_id = insert_market_state(self.state(), self.path, cutoff_at_utc="2026-01-01T10:00:00+00:00", symbol="WINV26")
        with sqlite3.connect(self.path) as conn:
            conn.execute("""INSERT INTO jev_shadow_runs
                (market_state_id,symbol,cutoff_at_utc,state_hash,jev_engine_version,jev_question_version,
                 model_configured,status,created_at_utc) VALUES (?,?,?,?,?,?,?,?,?)""",
                (state_id, "WINV26", "2026-01-01T10:00:00+00:00", "hash", JEV_ENGINE_VERSION,
                 JEV_QUESTION_VERSION, "typesafe/jev-1.13", "RUNNING", "2020-01-01T00:00:00+00:00"))
            run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        with patch("po3.jev_worker.JEV_SHADOW_ENABLED", True):
            result = run_jev_for_market_state(self.path, state_id, lambda s, q: {"answers": self.answers()})
        self.assertTrue(result["recovered"])
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("SELECT id,status,recovered_after_restart FROM jev_shadow_runs").fetchone()
        self.assertEqual(row, (run_id, "OK", 1))

    def test_worker_lease_name_is_separate(self):
        source = Path(__file__).parents[1].joinpath("po3", "jev_worker.py").read_text(encoding="utf-8")
        self.assertIn('lease_name: str = "po3-jev"', source)
        self.assertNotIn("observed_outcomes", source)

    def test_launcher_starts_jev_only_when_explicitly_enabled(self):
        launcher = Path(__file__).parents[1].joinpath("po3", "launcher.py").read_text(encoding="utf-8")
        cmd = Path(__file__).parents[1].joinpath("iniciar_painel_macro.cmd").read_text(encoding="utf-8")
        self.assertIn("po3.jev_worker", launcher)
        self.assertIn('JEV_SHADOW_ENABLED', launcher)
        self.assertIn('if not defined JEV_SHADOW_ENABLED set "JEV_SHADOW_ENABLED=false"', cmd)

    def test_jev_schema_is_migrated(self):
        with sqlite3.connect(self.path) as conn:
            self.assertIsNotNone(conn.execute("SELECT name FROM sqlite_master WHERE name='jev_shadow_runs'").fetchone())

    def test_comparison_is_read_only_and_reports_unavailable_without_runs(self):
        before = self.path.stat().st_mtime_ns
        result = compare_market_state(self.path, 999)
        self.assertEqual(result["status"], "INDISPONIVEL")
        self.assertEqual(before, self.path.stat().st_mtime_ns)


if __name__ == "__main__": unittest.main()
