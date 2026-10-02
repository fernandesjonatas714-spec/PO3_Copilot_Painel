import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from po3.decision_engine.gate import apply_gate
from po3.decision_engine.schemas import CHOICES, Decision, DECISION_ENGINE_VERSION, PROMPT_VERSION, SCHEMA_VERSION, validate_decision
from po3.shadow_mode import process_pending_shadow_states
from po3.storage.migrations import migrate
from po3.storage.market_repository import insert_market_state
import po3.shadow_mode as shadow


class O3ShadowOperationalTests(unittest.TestCase):
    def test_event_risk_is_informational_and_never_event_block(self):
        self.assertEqual(CHOICES["contexto_operacional"], {
            "CONTEXTO_COMPRADOR", "CONTEXTO_VENDEDOR", "AGUARDAR", "SEM_SETUP", "INDETERMINADO"
        })
        decision = validate_decision({
            "id_decisao": "risco_evento", "tipo": "SCORE", "pergunta": "risco",
            "decisao": "10", "confianca": "ALTA", "status_evidencias": "COMPLETAS",
        })
        validation = SimpleNamespace(bloqueado=False, status="VALIDOS", dados_ausentes=[])
        gate = apply_gate(validation, [decision])
        self.assertNotEqual(gate.status, "BLOQUEADO")

    def test_shadow_backlog_is_idempotent_and_only_writes_shadow_runs(self):
        fd, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        Path(path).unlink(missing_ok=True)
        try:
            migrate(path)
            insert_market_state({"ativo": "WIN", "timestamp": "2026-01-01T10:00:00+00:00", "preco_atual": 100}, path,
                                cutoff_at_utc="2026-01-01T10:00:00+00:00", symbol="WIN")
            shadow.SHADOW_MODE_ENABLED = True
            runner = lambda payload: {"decisoes": [], "gate": {"status": "REVISAO"}, "consenso": {"status": "NAO_EXECUTADA"}}
            with sqlite3.connect(path) as conn:
                before = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("market_states", "observed_outcomes", "decision_observations")}
            process_pending_shadow_states(path, runner, model_configured="modelo-free", limit=1)
            process_pending_shadow_states(path, runner, model_configured="modelo-free", limit=1)
            with sqlite3.connect(path) as conn:
                after = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in before}
            self.assertEqual(before, after)
            with sqlite3.connect(path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM shadow_runs").fetchone()[0], 1)
        finally:
            shadow.SHADOW_MODE_ENABLED = False
            try:
                Path(path).unlink(missing_ok=True)
            except PermissionError:
                # SQLite no Windows pode manter o handle até a coleta do GC;
                # o arquivo temporário não pertence ao projeto.
                pass

    def test_launcher_enables_shadow_only_in_official_flow(self):
        launcher = Path("iniciar_painel_macro.cmd").read_text(encoding="utf-8")
        self.assertIn('set "SHADOW_MODE_ENABLED=true"', launcher)

    def test_version_metadata_incremented_coherently(self):
        self.assertEqual(DECISION_ENGINE_VERSION, PROMPT_VERSION)
        self.assertEqual(PROMPT_VERSION, SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
