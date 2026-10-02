import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from po3.auto_decision import process_pending_auto_decisions, run_auto_decision_for_market_state
from po3.decision_engine.schemas import DECISION_ENGINE_VERSION, PROMPT_VERSION
from po3.storage.migrations import migrate
from po3.storage.market_repository import insert_market_state


class O4AutoDecisionTests(unittest.TestCase):
    def setUp(self):
        fd, name = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        Path(name).unlink(missing_ok=True)
        self.path = Path(name)
        migrate(self.path)

    def tearDown(self):
        try:
            self.path.unlink(missing_ok=True)
        except PermissionError:
            pass

    def _state(self, cutoff="2026-01-01T10:00:00+00:00"):
        return {
            "ativo": "WINV26", "timestamp": cutoff, "preco_atual": 100.0,
            "tecnico": {}, "mercado_domestico": {}, "mercado_externo": {},
            "calendario": {}, "noticias": [], "fontes": [],
            "qualidade_dados": {}, "snapshot": {},
        }

    def test_new_market_state_generates_one_official_analysis_and_restart_is_idempotent(self):
        state_id = insert_market_state(self._state(), self.path,
                                       cutoff_at_utc="2026-01-01T10:00:00+00:00", symbol="WINV26")
        result = {"decisoes": [{"id_decisao": key, "decisao": "AGUARDAR", "confianca": "MEDIA"} for key in ("regime_macro", "contexto_domestico", "contexto_tecnico", "risco_evento", "conflito_contexto", "contexto_operacional")],
                  "gate": {"status": "VALIDO"}, "consenso": {"status": "NAO_EXECUTADA"},
                  "modelo_utilizado": "modelo-free", "fallback_utilizado": False,
                  "reparo_json_utilizado": False}
        with patch("po3.auto_decision._runner", return_value=(result, "MACROECONOMIA E DIA A DIA\n\nIMPACTO NA BOLSA\n\nINSIGHT OPERACIONAL")), \
             patch("po3.auto_decision.configured_model_name", return_value="modelo-free"):
            first = process_pending_auto_decisions(self.path, symbol="WINV26", limit=1)
            second = process_pending_auto_decisions(self.path, symbol="WINV26", limit=1)
        self.assertEqual(first["created"], 1)
        self.assertEqual(second["created"], 0)
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("SELECT market_state_id,state_hash,gate_status,consensus_status,status,narrative FROM official_decision_runs").fetchone()
            count = conn.execute("SELECT COUNT(*) FROM official_decision_runs").fetchone()[0]
        self.assertEqual(count, 1)
        self.assertEqual(row[0], state_id)
        self.assertTrue(row[1])
        self.assertEqual(row[2:], ("VALIDO", "NAO_EXECUTADA", "OK", "MACROECONOMIA E DIA A DIA\n\nIMPACTO NA BOLSA\n\nINSIGHT OPERACIONAL"))

    def test_pending_selection_is_by_frozen_state_and_version(self):
        for index, cutoff in enumerate(("2026-01-01T10:00:00+00:00", "2026-01-01T10:05:00+00:00")):
            insert_market_state(self._state(cutoff), self.path, cutoff_at_utc=cutoff, symbol="WINV26")
        result = {"decisoes": [], "gate": {"status": "BLOQUEADO"}, "consenso": {"status": "NAO_EXECUTADA"}, "erro": "DADOS_CRITICOS_AUSENTES"}
        with patch("po3.auto_decision._runner", return_value=(result, None)), patch("po3.auto_decision.configured_model_name", return_value="modelo-free"):
            process_pending_auto_decisions(self.path, symbol="WINV26", limit=1)
            process_pending_auto_decisions(self.path, symbol="WINV26", limit=1)
        with sqlite3.connect(self.path) as conn:
            rows = conn.execute("SELECT market_state_id,decision_engine_version,prompt_version FROM official_decision_runs ORDER BY market_state_id").fetchall()
        self.assertEqual([row[0] for row in rows], [1, 2])
        self.assertEqual(rows[0][1:], (DECISION_ENGINE_VERSION, PROMPT_VERSION))

    def test_calendar_missing_persists_blocked_without_narrative(self):
        state_id = insert_market_state(
            self._state(), self.path,
            cutoff_at_utc="2026-01-01T10:00:00+00:00", symbol="WINV26",
        )
        with patch("po3.auto_decision.send_message_detailed") as llm, \
             patch("po3.auto_decision.configured_model_name", return_value="modelo-free"):
            result = run_auto_decision_for_market_state(
                self.path, state_id, model_configured="modelo-free",
            )
        llm.assert_not_called()
        self.assertEqual(result["status"], "BLOQUEADO")
        with sqlite3.connect(self.path) as conn:
            row = conn.execute(
                "SELECT decision_status,narrative_status,narrative,gate_status,decisions_json "
                "FROM official_decision_runs WHERE market_state_id=?", (state_id,)
            ).fetchone()
        self.assertEqual(row[:4], ("BLOQUEADO", "NAO_EXECUTADA", None, "BLOQUEADO"))
        self.assertEqual(json.loads(row[4])["erro"], "DADOS_CRITICOS_AUSENTES")

    def test_pending_queue_is_fifo_and_does_not_starve_old_states(self):
        cutoffs = {
            62: "2026-01-01T10:00:00+00:00",
            63: "2026-01-01T10:05:00+00:00",
            64: "2026-01-01T10:10:00+00:00",
        }
        ids = {}
        for key in (64, 63, 62):
            ids[key] = insert_market_state(self._state(cutoffs[key]), self.path,
                                            cutoff_at_utc=cutoffs[key], symbol="WINV26")
        result = {"decisoes": [], "gate": {"status": "BLOQUEADO"},
                  "consenso": {"status": "NAO_EXECUTADA"},
                  "erro": "DADOS_CRITICOS_AUSENTES"}
        with patch("po3.auto_decision._runner", return_value=(result, None)), \
             patch("po3.auto_decision.configured_model_name", return_value="modelo-free"):
            selected = [process_pending_auto_decisions(self.path, symbol="WINV26", limit=1)
                        for _ in range(3)]
        with sqlite3.connect(self.path) as conn:
            order = [row[0] for row in conn.execute(
                "SELECT market_state_id FROM official_decision_runs ORDER BY cutoff_at_utc ASC")]
        self.assertEqual(order, [ids[62], ids[63], ids[64]])

    def test_pending_queue_selects_oldest_when_middle_is_already_processed(self):
        cutoffs = {
            62: "2026-01-01T10:00:00+00:00",
            63: "2026-01-01T10:05:00+00:00",
            64: "2026-01-01T10:10:00+00:00",
        }
        ids = {key: insert_market_state(self._state(value), self.path,
                                         cutoff_at_utc=value, symbol="WINV26")
               for key, value in cutoffs.items()}
        result = {"decisoes": [], "gate": {"status": "BLOQUEADO"},
                  "consenso": {"status": "NAO_EXECUTADA"},
                  "erro": "DADOS_CRITICOS_AUSENTES"}
        with patch("po3.auto_decision._runner", return_value=(result, None)), \
             patch("po3.auto_decision.configured_model_name", return_value="modelo-free"):
            process_pending_auto_decisions(self.path, symbol="WINV26", limit=1)
            # Recria o cenário: o estado do meio fica processado primeiro.
            with sqlite3.connect(self.path) as conn:
                conn.execute("DELETE FROM official_decision_runs WHERE market_state_id IN (?,?)",
                             (ids[62], ids[64]))
                conn.commit()
            selected = process_pending_auto_decisions(self.path, symbol="WINV26", limit=1)
        with sqlite3.connect(self.path) as conn:
            selected_state = conn.execute(
                "SELECT market_state_id FROM official_decision_runs WHERE id=?",
                (selected["results"][0]["id"],),
            ).fetchone()[0]
        self.assertEqual(selected_state, ids[62])

    def test_orphan_processing_run_is_recovered_in_same_row(self):
        state_id = insert_market_state(self._state(), self.path,
                                       cutoff_at_utc="2026-01-01T10:00:00+00:00", symbol="WINV26")
        old = "2020-01-01T00:00:00+00:00"
        with sqlite3.connect(self.path) as conn:
            conn.execute("""INSERT INTO official_decision_runs
                (market_state_id,symbol,cutoff_at_utc,state_hash,decision_engine_version,
                 prompt_version,schema_version,model_configured,decisions_json,status,created_at_utc,
                 worker_owner_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (state_id, "WINV26", "2026-01-01T10:00:00+00:00", "hash", DECISION_ENGINE_VERSION,
                 PROMPT_VERSION, "2.0.0", "modelo-free", "{}", "PROCESSANDO", old, "worker-antigo"))
            run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        result = {"decisoes": [], "gate": {"status": "BLOQUEADO"},
                  "consenso": {"status": "NAO_EXECUTADA"},
                  "erro": "DADOS_CRITICOS_AUSENTES"}
        with patch("po3.auto_decision._runner", return_value=(result, None)), \
             patch("po3.auto_decision.configured_model_name", return_value="modelo-free"):
            processed = process_pending_auto_decisions(self.path, symbol="WINV26", limit=1)
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("SELECT id,status,recovered_after_restart FROM official_decision_runs").fetchone()
            count = conn.execute("SELECT COUNT(*) FROM official_decision_runs").fetchone()[0]
        self.assertEqual(processed["created"], 1)
        self.assertEqual(row, (run_id, "BLOQUEADO", 1))
        self.assertEqual(count, 1)

    def test_recent_processing_run_with_active_owner_is_not_stolen(self):
        state_id = insert_market_state(self._state(), self.path,
                                       cutoff_at_utc="2026-01-01T10:00:00+00:00", symbol="WINV26")
        with sqlite3.connect(self.path) as conn:
            conn.execute("""INSERT INTO official_decision_runs
                (market_state_id,symbol,cutoff_at_utc,state_hash,decision_engine_version,
                 prompt_version,schema_version,model_configured,decisions_json,status,created_at_utc,
                 worker_owner_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (state_id, "WINV26", "2026-01-01T10:00:00+00:00", "hash", DECISION_ENGINE_VERSION,
                 PROMPT_VERSION, "2.0.0", "modelo-free", "{}", "PROCESSANDO",
                 "2026-01-01T10:00:00+00:00", "worker-ativo"))
            conn.execute("INSERT INTO collector_leases VALUES (?,?,?,?,?,?,?)",
                         ("po3-ai", "WINV26", "worker-ativo", 1, "2026-01-01T10:00:00+00:00",
                          "2026-01-01T10:01:00+00:00", "2999-01-01T00:00:00+00:00"))
        with patch("po3.auto_decision.configured_model_name", return_value="modelo-free"):
            processed = process_pending_auto_decisions(self.path, symbol="WINV26", limit=1)
        self.assertEqual(processed["selected"], 0)

    def test_official_path_does_not_use_outcomes(self):
        source = Path(__file__).parents[1].joinpath("po3", "auto_decision.py").read_text(encoding="utf-8")
        self.assertNotIn("observed_outcomes", source)
        self.assertNotIn("market_bars_m1", source)

    def test_decision_and_narrative_models_are_persisted_separately(self):
        state_id = insert_market_state(self._state(), self.path,
                                       cutoff_at_utc="2026-01-01T10:00:00+00:00", symbol="WINV26")
        result = {"decisoes": [{"id_decisao": key, "decisao": "AGUARDAR", "confianca": "MEDIA"}
                                for key in ("regime_macro", "contexto_domestico", "contexto_tecnico",
                                            "risco_evento", "conflito_contexto", "contexto_operacional")],
                  "gate": {"status": "VALIDO"}, "consenso": {"status": "NAO_EXECUTADA"},
                  "modelo_utilizado": "google/gemma-4-31b-it:free",
                  "decision_model_used": "google/gemma-4-31b-it:free",
                  "decision_model_attempts": ["qwen/qwen3.8-27b:free", "google/gemma-4-31b-it:free"],
                  "decision_fallback_used": True, "decision_repair_used": True,
                  "narrative_model_used": "qwen/qwen3.8-27b:free",
                  "narrative_fallback_used": False}
        with patch("po3.auto_decision._runner", return_value=(result, "MACROECONOMIA E DIA A DIA\n\nIMPACTO NA BOLSA\n\nINSIGHT OPERACIONAL")), \
             patch("po3.auto_decision.configured_model_name", return_value="qwen/qwen3.8-27b:free"):
            created = process_pending_auto_decisions(self.path, symbol="WINV26", limit=1)
        self.assertEqual(created["created"], 1)
        with sqlite3.connect(self.path) as conn:
            row = conn.execute("""SELECT model_used,decision_model_used,decision_model_attempts_json,
                decision_fallback_used,decision_repair_used,narrative_model_used,narrative_fallback_used
                FROM official_decision_runs WHERE market_state_id=?""", (state_id,)).fetchone()
        self.assertEqual(row[0], "google/gemma-4-31b-it:free")
        self.assertEqual(row[1], "google/gemma-4-31b-it:free")
        self.assertIn("qwen/qwen3.8-27b:free", row[2])
        self.assertEqual(row[3:5], (1, 1))
        self.assertEqual(row[5:], ("qwen/qwen3.8-27b:free", 0))

    def test_launcher_enables_auto_decision_without_orders(self):
        launcher = Path(__file__).parents[1].joinpath("iniciar_painel_macro.cmd").read_text(encoding="utf-8")
        self.assertIn('set "AUTO_DECISION_ENGINE=true"', launcher)
        collector = Path(__file__).parents[1].joinpath("po3", "collection", "mt5_m1_collector.py").read_text(encoding="utf-8")
        self.assertNotIn("process_pending_auto_decisions", collector)
        ai_worker = Path(__file__).parents[1].joinpath("po3", "ai_worker.py").read_text(encoding="utf-8")
        self.assertIn("process_pending_auto_decisions", ai_worker)
        self.assertNotIn("order_send", collector)


if __name__ == "__main__":
    unittest.main()
