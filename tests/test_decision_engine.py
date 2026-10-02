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

class DecisionEngineAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = replace(build_demo_snapshot(), connected=True, as_of=datetime.now().astimezone())
        self.context = {"calendar":{"available":True,"events":[]}, "news":{"statuses":[]}}

    def items(self, confidence="MEDIA", status="PARCIAIS"):
        values={"regime_macro":"MISTO","contexto_domestico":"NEUTRO","contexto_tecnico":"CONFLITANTE","risco_evento":"5","conflito_contexto":"SIM","contexto_operacional":"AGUARDAR"}
        types={"regime_macro":"CHOICE","contexto_domestico":"CHOICE","contexto_tecnico":"CHOICE","risco_evento":"SCORE","conflito_contexto":"NOUL","contexto_operacional":"CHOICE"}
        return [{"id_decisao":key,"tipo":types[key],"pergunta":"?","decisao":value,"confianca":confidence,"status_evidencias":status,"evidencias":[]} for key,value in values.items()]

    def response(self, items=None, model="qwen/qwen3.8-27b:free", fallback=False):
        return {"content":json.dumps({"decisoes":items or self.items()}, ensure_ascii=False),"model_configured":model,"model_used":model,"fallback_used":fallback}

    def test_json_invalid_repairable_once(self):
        calls=[]
        def fake(message):
            calls.append(message)
            return {"content":"invalido"} if len(calls)==1 else self.response()
        result=DecisionEngine(fake,"qwen/qwen3.8-27b:free").run(self.snapshot,self.context)
        self.assertEqual(len(result.decisions),6); self.assertTrue(result.repair_used); self.assertEqual(len(calls),2)

    def test_json_non_repairable_is_blocked(self):
        calls=[]
        def fake(message):
            calls.append(message); return {"content":"invalido"}
        result=DecisionEngine(fake,"qwen/qwen3.8-27b:free").run(self.snapshot,self.context)
        self.assertEqual(result.gate.status,"BLOQUEADO"); self.assertEqual(result.error,"RESPOSTA_LLM_INVALIDA"); self.assertEqual(len(calls),2)

    def test_invalid_confidence_status_noul_and_score_are_rejected(self):
        item=self.items(); item[0]["confianca"]="X"
        with self.assertRaises(ValueError): validate_decision(item[0])
        item=self.items(); item[0]["status_evidencias"]="X"
        with self.assertRaises(ValueError): validate_decision(item[0])
        item=self.items(); item[4]["decisao"]="TALVEZ"
        with self.assertRaises(ValueError): validate_decision(item[4])

    def test_score_bounds_are_rejected(self):
        for score in ("-1","11"):
            item=self.items(); item[3]["decisao"]=score
            result=DecisionEngine(lambda m:self.response(item),"qwen/qwen3.8-27b:free").run(self.snapshot,self.context)
            self.assertEqual(result.error,"RESPOSTA_LLM_INVALIDA")

    def test_second_analysis_triggered_only_when_needed(self):
        calls=[]
        low=self.items(confidence="BAIXA")
        def fake(message): calls.append(message); return self.response(low)
        result=DecisionEngine(fake,"qwen/qwen3.8-27b:free").run(self.snapshot,self.context)
        self.assertEqual(result.gate.status,"REVISAO"); self.assertEqual(len(result.second_decisions),6); self.assertEqual(len(calls),2)
        calls.clear()
        high=self.items(confidence="ALTA", status="COMPLETAS")
        result=DecisionEngine(lambda m:(calls.append(m) or self.response(high)),"qwen/qwen3.8-27b:free").run(self.snapshot,self.context)
        self.assertEqual(result.consensus["status"],"NAO_EXECUTADA"); self.assertEqual(len(calls),1)

    def test_consensus_and_divergence(self):
        first=self.items(confidence="ALTA",status="COMPLETAS"); second=self.items(confidence="ALTA",status="COMPLETAS")
        state=[self.response(first),self.response(second)]
        result=DecisionEngine(lambda m:state.pop(0),"qwen/qwen3.8-27b:free").run(self.snapshot,self.context)
        self.assertEqual(result.consensus["status"],"NAO_EXECUTADA")
        first=self.items(confidence="BAIXA"); second=self.items(confidence="BAIXA"); second[0]["decisao"]="AVERSAO_A_RISCO"
        state=[self.response(first),self.response(second)]
        result=DecisionEngine(lambda m:state.pop(0),"qwen/qwen3.8-27b:free").run(self.snapshot,self.context)
        self.assertEqual(result.consensus["status"],"DIVERGENCIA")

    def test_calendar_unavailable_and_stale_mt5_block(self):
        state=build_market_state(self.snapshot,{"calendar":{"available":False},"news":{}})
        self.assertEqual(apply_gate(validate_market_state(state),[]).status,"BLOQUEADO")
        old=replace(self.snapshot, as_of=datetime(2020,1,1,tzinfo=datetime.now().astimezone().tzinfo))
        state=build_market_state(old,self.context)
        self.assertEqual(apply_gate(validate_market_state(state),[]).status,"BLOQUEADO")

    def test_calendar_unavailable_blocks_before_any_llm_call(self):
        state = build_market_state(self.snapshot, {"calendar": {"available": False}, "news": {}})
        calls = []
        result = DecisionEngine(lambda message: calls.append(message), "qwen/qwen3.8-27b:free").run_market_state(state)
        self.assertEqual(calls, [])
        self.assertEqual(result.error, "DADOS_CRITICOS_AUSENTES")
        self.assertEqual(result.gate.status, "BLOQUEADO")
        self.assertEqual(result.decisions, [])
        self.assertEqual(result.consensus["status"], "NAO_EXECUTADA")

    def test_risk_event_score_ten_is_informational_with_valid_data(self):
        items = self.items(confidence="ALTA", status="COMPLETAS")
        items[3]["decisao"] = "10"
        result = DecisionEngine(lambda message: self.response(items), "qwen/qwen3.8-27b:free").run(
            self.snapshot, self.context
        )
        self.assertEqual(len(result.decisions), 6)
        self.assertNotEqual(result.gate.status, "BLOQUEADO")

    def test_sem_setup_is_not_blocked_gate(self):
        items=self.items(confidence="ALTA",status="COMPLETAS"); items[-1]["decisao"]="SEM_SETUP"
        result=DecisionEngine(lambda m:self.response(items),"qwen/qwen3.8-27b:free").run(self.snapshot,self.context)
        self.assertEqual(result.gate.status,"VALIDO"); self.assertEqual(result.decisions[-1].decisao,"SEM_SETUP")

    def test_second_analysis_uses_same_state_and_independent_prompt(self):
        prompts=[]; low=self.items(confidence="BAIXA")
        def fake(message): prompts.append(message); return self.response(low)
        result=DecisionEngine(fake,"qwen/qwen3.8-27b:free").run(self.snapshot,self.context)
        self.assertEqual(len(prompts),2); self.assertEqual(prompts[0],prompts[1]); self.assertEqual(result.second_model_used,"qwen/qwen3.8-27b:free")
