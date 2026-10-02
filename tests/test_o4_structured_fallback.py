import json
import unittest
from datetime import datetime
from dataclasses import replace

from po3.demo_data import build_demo_snapshot
from po3.decision_engine.engine import DecisionEngine
from po3.decision_engine.market_state import build_market_state


class O4StructuredFallbackTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = replace(build_demo_snapshot(), connected=True, as_of=datetime.now().astimezone())
        self.context = {"calendar": {"available": True, "events": []}, "news": {"statuses": []}}
        self.keys = ("regime_macro", "contexto_domestico", "contexto_tecnico", "risco_evento", "conflito_contexto", "contexto_operacional")
        self.values = {"regime_macro": "MISTO", "contexto_domestico": "NEUTRO", "contexto_tecnico": "NEUTRO", "risco_evento": "5", "conflito_contexto": "SIM", "contexto_operacional": "AGUARDAR"}
        self.types = {"regime_macro": "CHOICE", "contexto_domestico": "CHOICE", "contexto_tecnico": "CHOICE", "risco_evento": "SCORE", "conflito_contexto": "NOUL", "contexto_operacional": "CHOICE"}

    def valid_response(self, model):
        return {"content": json.dumps({"decisoes": [{"id_decisao": key, "tipo": self.types[key], "pergunta": "?", "decisao": self.values[key], "confianca": "MEDIA", "status_evidencias": "COMPLETAS"} for key in self.keys]}), "model_used": model, "model_configured": "qwen/qwen3.8-27b:free", "fallback_used": model != "qwen/qwen3.8-27b:free"}

    def test_qwen_invalid_repair_invalid_uses_next_free_model(self):
        calls = []
        def sender(message, model_override=None, allow_model_fallback=True):
            calls.append((model_override, "repair" if "Corrija" in message else "decision"))
            if model_override == "qwen/qwen3.8-27b:free":
                return {"content": "invalido"}
            return self.valid_response(model_override)
        result = DecisionEngine(sender, "qwen/qwen3.8-27b:free").run(self.snapshot, self.context)
        self.assertEqual(len(result.decisions), 6)
        self.assertTrue(result.fallback_used)
        self.assertTrue(result.repair_used)
        self.assertEqual(result.model_used, "google/gemma-4-31b-it:free")
        self.assertIn("qwen/qwen3.8-27b:free", result.model_attempts)

    def test_all_models_invalid_returns_controlled_error(self):
        def sender(message, model_override=None, allow_model_fallback=True):
            return {"content": "invalido", "model_used": model_override}
        result = DecisionEngine(sender, "qwen/qwen3.8-27b:free").run(self.snapshot, self.context)
        self.assertEqual(result.error, "RESPOSTA_LLM_INVALIDA")
        self.assertEqual(len(result.decisions), 0)

    def test_factual_collector_has_no_ai_worker_import(self):
        from pathlib import Path
        source = Path(__file__).parents[1].joinpath("po3", "collection", "mt5_m1_collector.py").read_text(encoding="utf-8")
        self.assertNotIn("from po3.ai_service", source)
        self.assertNotIn("from po3.shadow_runner", source)
        self.assertNotIn("from po3.auto_decision", source)

    def test_ai_worker_is_mt5_independent_and_has_own_lease(self):
        from pathlib import Path
        source = Path(__file__).parents[1].joinpath("po3", "ai_worker.py").read_text(encoding="utf-8")
        self.assertNotIn("MetaTrader5", source)
        self.assertIn('lease_name: str = "po3-ai"', source)
        self.assertNotIn("observed_outcomes", source)


if __name__ == "__main__":
    unittest.main()
