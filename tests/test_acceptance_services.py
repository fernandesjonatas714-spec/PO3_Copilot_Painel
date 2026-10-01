import json
import os
import tempfile
import uuid
from pathlib import Path
import unittest
from datetime import datetime
from unittest.mock import patch
from urllib.error import HTTPError

from po3.ai_service import OpenRouterConfig, OpenRouterError, load_config, send_message_detailed
from po3.demo_data import build_demo_snapshot
from po3.learning_store import save_analysis, recent_analyses

class _Response:
    def __init__(self, payload): self.payload=payload
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def read(self): return json.dumps(self.payload).encode()

class AcceptanceServiceTests(unittest.TestCase):
    def test_paid_model_is_rejected(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY":"test-key","OPENROUTER_MODEL":"openai/example"}, clear=False):
            with self.assertRaises(OpenRouterError): load_config()

    def test_fallback_and_real_model_are_recorded(self):
        config=OpenRouterConfig("test-key","qwen/qwen3.8-27b:free")
        calls=[]
        def fake_urlopen(request, timeout, context):
            calls.append(json.loads(request.data.decode()))
            return _Response({"model":"google/gemma-4-31b-it:free","choices":[{"message":{"content":"ok"}}]})
        with patch("po3.ai_service.urlopen", side_effect=fake_urlopen):
            result=send_message_detailed("teste",config=config)
        self.assertEqual(result["model_used"],"google/gemma-4-31b-it:free")
        self.assertTrue(result["fallback_used"])
        self.assertTrue(all(str(m).endswith(":free") for m in result["attempts"]))

    def test_total_model_failure_is_controlled(self):
        config=OpenRouterConfig("test-key","qwen/qwen3.8-27b:free")
        with patch("po3.ai_service.urlopen", side_effect=TimeoutError()):
            with self.assertRaises(OpenRouterError): send_message_detailed("teste",config=config)

    def test_old_and_structured_history_remain_readable(self):
        db=os.path.join(tempfile.gettempdir(),f"po3_acceptance_history_{uuid.uuid4().hex}.sqlite")
        try:
            snapshot=build_demo_snapshot()
            old_id=save_analysis(snapshot,{},"historico antigo",db)
            structured={"_structured":{"gate":{"status":"VALIDO"},"modelo_utilizado":"qwen/qwen3.8-27b:free","decisoes":[]}}
            new_id=save_analysis(snapshot,structured,"historico novo",db)
            rows=recent_analyses(10,db)
            self.assertEqual({"historico antigo","historico novo"},{row["resposta"] for row in rows})
            self.assertTrue(any(row["status"]=="VALIDO" for row in rows))
        finally:
            try: os.remove(db)
            except OSError: pass

    def test_feature_flag_contract_is_explicit_in_source(self):
        source=Path("macro_app.py").read_text(encoding="utf-8")
        self.assertIn("DECISION_ENGINE_ENABLED",source)
        self.assertIn("_run_daily_analysis_legacy",source)
        self.assertIn("DecisionEngine",source)

if __name__ == "__main__": unittest.main()
