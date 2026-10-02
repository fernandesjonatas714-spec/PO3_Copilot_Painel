import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from po3.ai_analysis_window import (
    current_ai_window_status,
    ensure_ai_analysis_baseline,
    is_ai_analysis_window_open,
    next_ai_analysis_window,
    state_is_after_baseline,
)
from po3.storage.market_repository import insert_market_state
from po3.storage.migrations import migrate


TZ = ZoneInfo("America/Sao_Paulo")


class AIAnalysisWindowTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "AI_ANALYSIS_WINDOW_ENABLED": "true",
            "AI_ANALYSIS_START": "08:45",
            "AI_ANALYSIS_END": "18:00",
            "AI_ANALYSIS_TIMEZONE": "America/Sao_Paulo",
        }, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def at(self, hour, minute, day=2):
        return datetime(2026, 10, day, hour, minute, tzinfo=TZ)

    def test_boundaries_and_weekends(self):
        self.assertFalse(is_ai_analysis_window_open(self.at(8, 44)))
        self.assertTrue(is_ai_analysis_window_open(self.at(8, 45)))
        self.assertTrue(is_ai_analysis_window_open(self.at(12, 0)))
        self.assertTrue(is_ai_analysis_window_open(self.at(17, 59)))
        self.assertFalse(is_ai_analysis_window_open(self.at(18, 0)))
        self.assertFalse(is_ai_analysis_window_open(self.at(18, 1)))
        self.assertFalse(is_ai_analysis_window_open(self.at(12, 0, day=3)))  # sábado
        self.assertFalse(is_ai_analysis_window_open(self.at(12, 0, day=4)))  # domingo

    def test_timezone_and_next_open(self):
        status = current_ai_window_status(self.at(18, 1))
        self.assertEqual(status["timezone"], "America/Sao_Paulo")
        self.assertEqual(status["reason"], "FORA_JANELA_IA")
        self.assertEqual(next_ai_analysis_window(self.at(18, 1)).astimezone(TZ).strftime("%H:%M"), "08:45")

    def test_watermark_excludes_backlog_and_allows_new_state(self):
        fd, name = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        path = Path(name)
        path.unlink(missing_ok=True)
        try:
            migrate(path)
            old = {"ativo": "WINV26", "timestamp": "2026-10-02T10:00:00+00:00", "preco_atual": 100,
                   "tecnico": {}, "mercado_domestico": {}, "mercado_externo": {}, "calendario": {},
                   "noticias": [], "fontes": [], "qualidade_dados": {}, "snapshot": {}}
            old_id = insert_market_state(old, path, cutoff_at_utc="2026-10-02T10:00:00+00:00", symbol="WINV26")
            baseline = ensure_ai_analysis_baseline(path, "WINV26", now=self.at(10, 30))
            self.assertFalse(state_is_after_baseline(old_id, old["timestamp"], baseline))
            new_id = insert_market_state(old, path, cutoff_at_utc="2026-10-02T10:05:00+00:00", symbol="WINV26")
            self.assertTrue(state_is_after_baseline(new_id, old["timestamp"].replace("10:00", "10:05"), baseline))
        finally:
            try:
                path.unlink(missing_ok=True)
            except PermissionError:
                pass

    def test_official_outside_window_does_not_start(self):
        from po3.auto_decision import process_pending_auto_decisions
        fd, name = tempfile.mkstemp(suffix=".sqlite"); os.close(fd)
        path = Path(name); path.unlink(missing_ok=True)
        try:
            migrate(path)
            state = {"ativo": "WINV26", "timestamp": "2026-10-02T22:00:00+00:00", "preco_atual": 100,
                     "tecnico": {}, "mercado_domestico": {}, "mercado_externo": {}, "calendario": {},
                     "noticias": [], "fontes": [], "qualidade_dados": {}, "snapshot": {}}
            insert_market_state(state, path, cutoff_at_utc="2026-10-02T22:00:00+00:00", symbol="WINV26")
            with patch("po3.auto_decision._runner") as runner:
                result = process_pending_auto_decisions(path, symbol="WINV26", enforce_window=True, now=self.at(18, 1))
            self.assertEqual(result["status"], "FORA_JANELA_IA")
            runner.assert_not_called()
        finally:
            try:
                path.unlink(missing_ok=True)
            except PermissionError:
                pass

    def test_supervisor_ai_outside_window_is_deterministic_only(self):
        from po3.operational_supervisor import supervisor_ai_gate
        result = supervisor_ai_gate({"overall_status": "ATENCAO_FEED"}, {}, self.at(20, 0))
        self.assertFalse(result["should_call"])
        self.assertEqual(result["reason"], "FORA_JANELA_IA")

    def test_shadow_and_jev_do_not_call_external_runner_outside_window(self):
        from po3.shadow_mode import process_pending_shadow_states
        from po3.jev_worker import process_pending_jev_states
        fd, name = tempfile.mkstemp(suffix=".sqlite"); os.close(fd)
        path = Path(name); path.unlink(missing_ok=True)
        try:
            migrate(path)
            with patch("po3.shadow_mode.SHADOW_MODE_ENABLED", True), \
                 patch("po3.jev_worker.JEV_SHADOW_ENABLED", True):
                shadow_runner = lambda payload: (_ for _ in ()).throw(AssertionError("Shadow chamado"))
                jev_runner = lambda state, questions: (_ for _ in ()).throw(AssertionError("Jev chamado"))
                shadow = process_pending_shadow_states(path, shadow_runner, enforce_window=True, now=self.at(18, 1))
                jev = process_pending_jev_states(path, jev_runner, enforce_window=True, now=self.at(18, 1))
            self.assertEqual(shadow["status"], "FORA_JANELA_IA")
            self.assertEqual(jev["status"], "FORA_JANELA_IA")
        finally:
            try:
                path.unlink(missing_ok=True)
            except PermissionError:
                pass

    def test_official_window_starts_after_baseline_without_backlog(self):
        from po3.auto_decision import process_pending_auto_decisions
        fd, name = tempfile.mkstemp(suffix=".sqlite"); os.close(fd)
        path = Path(name); path.unlink(missing_ok=True)
        state = {"ativo": "WINV26", "timestamp": "2026-10-02T10:00:00+00:00", "preco_atual": 100,
                 "tecnico": {}, "mercado_domestico": {}, "mercado_externo": {}, "calendario": {},
                 "noticias": [], "fontes": [], "qualidade_dados": {}, "snapshot": {}}
        result = {"decisoes": [{"id_decisao": key, "decisao": "AGUARDAR", "confianca": "MEDIA"}
                                for key in ("regime_macro", "contexto_domestico", "contexto_tecnico",
                                            "risco_evento", "conflito_contexto", "contexto_operacional")],
                  "gate": {"status": "VALIDO"}, "consenso": {"status": "NAO_EXECUTADA"},
                  "modelo_utilizado": "modelo-free"}
        try:
            migrate(path)
            insert_market_state(state, path, cutoff_at_utc="2026-10-02T10:00:00+00:00", symbol="WINV26")
            with patch("po3.auto_decision._runner", return_value=(result, "narrativa")), \
                 patch("po3.auto_decision.configured_model_name", return_value="modelo-free"):
                first = process_pending_auto_decisions(path, symbol="WINV26", enforce_window=True, now=self.at(10, 30))
                self.assertEqual(first["selected"], 0)
                insert_market_state(state, path, cutoff_at_utc="2026-10-02T10:05:00+00:00", symbol="WINV26")
                second = process_pending_auto_decisions(path, symbol="WINV26", enforce_window=True, now=self.at(10, 31))
            self.assertEqual(second["created"], 1)
            with sqlite3.connect(path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM official_decision_runs").fetchone()[0], 1)
        finally:
            try:
                path.unlink(missing_ok=True)
            except PermissionError:
                pass


if __name__ == "__main__":
    unittest.main()
