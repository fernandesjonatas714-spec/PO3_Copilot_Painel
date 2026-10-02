import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from po3.decision_engine.gate import apply_gate
from po3.decision_engine.schemas import CHOICES, Decision, DECISION_ENGINE_VERSION, PROMPT_VERSION, SCHEMA_VERSION, validate_decision
from po3.decision_engine.market_state import MarketState
from po3.shadow_mode import process_pending_shadow_states
from po3.shadow_runner import _hydrate_market_state
from po3.operational_supervisor import build_supervisor_snapshot
from po3.storage.migrations import migrate
from po3.storage.market_repository import insert_market_state
import po3.shadow_mode as shadow


class O3ShadowOperationalTests(unittest.TestCase):
    def _frozen_state(self, symbol="WINV26", timestamp="2026-01-01T10:00:00+00:00"):
        return MarketState(
            ativo=symbol, timestamp=timestamp, preco_atual=100.0,
            tecnico={"candles": {}, "niveis": {}, "zonas": {}, "confluencia": []},
            mercado_domestico={"macro": {"factors": []}, "fatores": [], "lideres": []},
            mercado_externo={}, calendario={"available": False}, noticias=[], fontes=[],
            qualidade_dados={"mt5_conectado": True, "fontes_disponiveis": False, "calendario_disponivel": False},
            snapshot={"ativo": symbol, "timestamp": timestamp, "preco_atual": 100.0},
        ).to_dict()

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

    def test_event_risk_ten_with_buyer_or_seller_context_is_valid(self):
        for context in ("CONTEXTO_COMPRADOR", "CONTEXTO_VENDEDOR"):
            risk = validate_decision({"id_decisao": "risco_evento", "tipo": "SCORE", "pergunta": "risco", "decisao": "10", "confianca": "ALTA", "status_evidencias": "COMPLETAS"})
            operational = validate_decision({"id_decisao": "contexto_operacional", "tipo": "CHOICE", "pergunta": "contexto", "decisao": context, "confianca": "ALTA", "status_evidencias": "COMPLETAS"})
            self.assertEqual(risk.decisao, "10")
            self.assertEqual(operational.decisao, context)

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

    def test_frozen_market_state_is_hydrated_without_reconstruction(self):
        original = self._frozen_state()
        hydrated = _hydrate_market_state(original)
        self.assertEqual(hydrated.to_dict(), original)
        self.assertFalse(hydrated.qualidade_dados["fontes_disponiveis"])
        self.assertEqual(hydrated.noticias, [])
        self.assertEqual(hydrated.fontes, [])

    def test_shadow_runner_passes_exact_state_to_decision_engine(self):
        from po3.shadow_runner import build_shadow_decision_runner
        original = self._frozen_state()
        seen = {}

        class FakeResult:
            def to_dict(self):
                return {"gate": {"status": "REVISAO"}, "consenso": {"status": "NAO_EXECUTADA"}, "decisoes": []}

        class FakeEngine:
            def __init__(self, *_args):
                pass

            def run_market_state(self, state):
                seen["state"] = state
                return FakeResult()

        with patch("po3.shadow_runner.DecisionEngine", FakeEngine), patch("po3.shadow_runner.configured_model_name", return_value="modelo"):
            runner, _ = build_shadow_decision_runner()
            runner(original)
        self.assertEqual(seen["state"].to_dict(), original)

    def test_invalid_frozen_timestamp_is_rejected_without_now_fallback(self):
        state = self._frozen_state(timestamp="horário inválido")
        with self.assertRaisesRegex(ValueError, "timestamp inválido"):
            _hydrate_market_state(state)

    def test_legacy_versions_use_current_shadow_versions_and_new_version_is_distinct(self):
        fd, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd); Path(path).unlink(missing_ok=True); migrate(path)
        previous = shadow.SHADOW_MODE_ENABLED; shadow.SHADOW_MODE_ENABLED = True
        try:
            state_id = insert_market_state(self._frozen_state(), path, cutoff_at_utc="2026-01-01T10:00:00+00:00", symbol="WINV26",
                                           versions={"decision_engine": "v2", "prompt": "v2"})
            runner = lambda payload: {"decisoes": [], "gate": {"status": "REVISAO"}, "consenso": {"status": "NAO_EXECUTADA"}}
            process_pending_shadow_states(path, runner, model_configured="modelo", symbol="WINV26")
            with sqlite3.connect(path) as conn:
                row = conn.execute("SELECT decision_engine_version,prompt_version FROM shadow_runs").fetchone()
            self.assertEqual(row, (DECISION_ENGINE_VERSION, PROMPT_VERSION))
            process_pending_shadow_states(path, runner, model_configured="modelo", symbol="WINV26")
            with sqlite3.connect(path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM shadow_runs").fetchone()[0], 1)
            process_pending_shadow_states(path, runner, model_configured="modelo", symbol="WINV26", decision_engine_version="9.9.9", prompt_version="9.9.9")
            with sqlite3.connect(path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM shadow_runs").fetchone()[0], 2)
        finally:
            shadow.SHADOW_MODE_ENABLED = previous
            try: Path(path).unlink(missing_ok=True)
            except PermissionError: pass

    def test_symbol_filter_leaves_other_asset_pending(self):
        fd, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd); Path(path).unlink(missing_ok=True); migrate(path)
        previous = shadow.SHADOW_MODE_ENABLED; shadow.SHADOW_MODE_ENABLED = True
        try:
            for symbol in ("WINV26", "DOL"):
                insert_market_state(self._frozen_state(symbol=symbol), path, cutoff_at_utc="2026-01-01T10:00:00+00:00", symbol=symbol)
            process_pending_shadow_states(path, lambda payload: {"decisoes": []}, model_configured="modelo", symbol="WINV26")
            with sqlite3.connect(path) as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM shadow_runs WHERE symbol='WINV26'").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM shadow_runs WHERE symbol='DOL'").fetchone()[0], 0)
        finally:
            shadow.SHADOW_MODE_ENABLED = previous
            try: Path(path).unlink(missing_ok=True)
            except PermissionError: pass

    def test_supervisor_signals_shadow_error(self):
        fd, path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd); Path(path).unlink(missing_ok=True); migrate(path)
        previous = shadow.SHADOW_MODE_ENABLED; shadow.SHADOW_MODE_ENABLED = True
        try:
            insert_market_state(self._frozen_state(), path, cutoff_at_utc="2026-01-01T10:00:00+00:00", symbol="WINV26")
            with sqlite3.connect(path) as conn:
                state_id = conn.execute("SELECT id FROM market_states").fetchone()[0]
                conn.execute("INSERT INTO shadow_runs (market_state_id,symbol,cutoff_at_utc,state_hash,shadow_mode_version,decision_engine_version,prompt_version,schema_version,model_configured,decisions_json,status,created_at_utc,error_type) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (state_id, "WINV26", "2026-01-01T10:00:00+00:00", "h", "1.0.0", DECISION_ENGINE_VERSION, PROMPT_VERSION, SCHEMA_VERSION, "modelo", "[]", "ERRO", "2026-01-01T10:00:00+00:00", "RuntimeError"))
                conn.commit()
            with patch("po3.operational_supervisor.flags", return_value={"AUTO_DECISION_ENGINE": False, "SHADOW_MODE_ENABLED": True, "REPLAY_ENABLED": False, "CALIBRATION_ENABLED": False, "MODEL_BENCHMARK_ENABLED": False}):
                snapshot = build_supervisor_snapshot(path, "WINV26")
            self.assertEqual(snapshot["overall_status"], "ATENCAO_SHADOW")
        finally:
            shadow.SHADOW_MODE_ENABLED = previous
            try: Path(path).unlink(missing_ok=True)
            except PermissionError: pass


if __name__ == "__main__":
    unittest.main()
