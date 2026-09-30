import json
import unittest
from dataclasses import replace
from datetime import datetime
from po3.demo_data import build_demo_snapshot
from po3.decision_engine.market_state import build_market_state
from po3.decision_engine.validator import validate_market_state
from po3.decision_engine.schemas import validate_decision
from po3.decision_engine.gate import apply_gate
from po3.decision_engine.engine import DecisionEngine

class DecisionEngineTests(unittest.TestCase):
    def state(self):
        snap=replace(build_demo_snapshot(), connected=True, as_of=datetime.now().astimezone())
        return build_market_state(snap, {"calendar":{"available":True,"events":[]},"news":{"statuses":[]}})

    def test_market_state_valid(self):
        result=validate_market_state(self.state())
        self.assertEqual(result.status, "VALIDOS")

    def test_market_state_partial(self):
        snap=build_demo_snapshot()
        state=build_market_state(snap, {"calendar":{"available":False},"news":{}})
        result=validate_market_state(state)
        self.assertIn(result.status, {"INSUFICIENTES", "PARCIAIS"})

    def test_choice_and_score_validation(self):
        self.assertEqual(validate_decision({"id_decisao":"regime_macro","tipo":"CHOICE","pergunta":"?","decisao":"MISTO"}).decisao, "MISTO")
        self.assertEqual(validate_decision({"id_decisao":"risco_evento","tipo":"SCORE","pergunta":"?","decisao":"7"}).decisao, "7")

    def test_invalid_choice_and_score(self):
        with self.assertRaises(ValueError): validate_decision({"id_decisao":"regime_macro","tipo":"CHOICE","pergunta":"?","decisao":"COMPRA"})
        with self.assertRaises(ValueError): validate_decision({"id_decisao":"risco_evento","tipo":"SCORE","pergunta":"?","decisao":"11"})

    def test_gate_blocked_when_data_is_stale(self):
        snap=build_demo_snapshot(); state=build_market_state(snap, {"calendar":{"available":False},"news":{}})
        validation=validate_market_state(state)
        gate=apply_gate(validation, [])
        self.assertEqual(gate.status, "BLOQUEADO")

    def test_engine_parses_six_decisions(self):
        items=[]
        values={"regime_macro":"MISTO","contexto_domestico":"NEUTRO","contexto_tecnico":"CONFLITANTE","risco_evento":"5","conflito_contexto":"SIM","contexto_operacional":"AGUARDAR"}
        types={"regime_macro":"CHOICE","contexto_domestico":"CHOICE","contexto_tecnico":"CHOICE","risco_evento":"SCORE","conflito_contexto":"NOUL","contexto_operacional":"CHOICE"}
        for key,value in values.items(): items.append({"id_decisao":key,"tipo":types[key],"pergunta":"?","decisao":value,"confianca":"MEDIA","status_evidencias":"PARCIAIS","evidencias":[]})
        def fake(message): return {"content":json.dumps({"decisoes":items}),"model_configured":"qwen/qwen3.8-27b:free","model_used":"qwen/qwen3.8-27b:free","fallback_used":False}
        snap=replace(build_demo_snapshot(), connected=True, as_of=datetime.now().astimezone())
        result=DecisionEngine(fake,"qwen/qwen3.8-27b:free").run(snap,{"calendar":{"available":True},"news":{}})
        self.assertEqual(len(result.decisions),6)

if __name__ == "__main__": unittest.main()