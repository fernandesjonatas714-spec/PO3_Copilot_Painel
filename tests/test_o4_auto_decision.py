import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from po3.auto_decision import process_pending_auto_decisions
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
        result = {"decisoes": [{"id_decisao": "contexto_operacional", "decisao": "AGUARDAR", "confianca": "MEDIA"}],
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

    def test_official_path_does_not_use_outcomes(self):
        source = Path(__file__).parents[1].joinpath("po3", "auto_decision.py").read_text(encoding="utf-8")
        self.assertNotIn("observed_outcomes", source)
        self.assertNotIn("market_bars_m1", source)

    def test_launcher_enables_auto_decision_without_orders(self):
        launcher = Path(__file__).parents[1].joinpath("iniciar_painel_macro.cmd").read_text(encoding="utf-8")
        self.assertIn('set "AUTO_DECISION_ENGINE=true"', launcher)
        collector = Path(__file__).parents[1].joinpath("po3", "collection", "mt5_m1_collector.py").read_text(encoding="utf-8")
        self.assertIn("process_pending_auto_decisions", collector)
        self.assertNotIn("order_send", collector)


if __name__ == "__main__":
    unittest.main()
