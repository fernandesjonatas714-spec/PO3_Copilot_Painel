import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from po3.benchmark import benchmark_report
from po3.evaluation_engine import sample_band
from po3.v2_config import flags
from po3.storage.migrations import migrate


IDS = ("regime_macro", "contexto_domestico", "contexto_tecnico", "risco_evento", "conflito_contexto", "contexto_operacional")


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        Path(self.path).unlink(missing_ok=True)
        migrate(self.path)

    def tearDown(self):
        try:
            Path(self.path).unlink(missing_ok=True)
        except OSError:
            pass

    def decisions(self, values=None, confidence="ALTA", evidence="COMPLETAS"):
        values = values or {key: "NEUTRO" for key in IDS}
        return [{"id_decisao": key, "decisao": values.get(key, "NEUTRO"), "confianca": confidence,
                 "status_evidencias": evidence} for key in IDS]

    def add(self, symbol="WIN", digest="hash-a", model="qwen/qwen3.8-27b:free", decisions=None,
            gate="VALIDO", consensus="CONSENSO", fallback=0, repair=0):
        with sqlite3.connect(self.path) as conn:
            cur = conn.execute("""INSERT INTO decision_observations
                (analysis_run_id,market_state_id,symbol,decision_state_hash,link_status,decisions_json,
                 gate_status,consensus_status,model_configured,model_used,fallback_used,repair_used,
                 decision_engine_version,prompt_version,schema_version,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (self._next_id(conn), 1, symbol, digest, "MATCHED", json.dumps(decisions if decisions is not None else self.decisions()),
                 gate, consensus, model, model, fallback, repair, "1.0", "1.0", "1.0", "2026-01-01T00:00:00Z"))
            return cur.lastrowid

    def _next_id(self, conn):
        return (conn.execute("SELECT COALESCE(MAX(analysis_run_id),0)+1 FROM decision_observations").fetchone()[0])

    def test_valid_six_decisions_and_model_metrics(self):
        self.add(fallback=1, repair=1)
        report = benchmark_report(self.path)
        self.assertEqual(report["total_observations"], 1)
        self.assertEqual(report["usable_observations"], 1)
        metrics = report["models"]["qwen/qwen3.8-27b:free"]
        self.assertEqual((metrics["fallback_count"], metrics["repair_count"]), (1, 1))
        self.assertEqual(report["sample_band"], "INSUFICIENTE")

    def test_invalid_and_incomplete_quality_are_reported(self):
        self.add(decisions="não é json")
        self.add(digest="hash-b", decisions=self.decisions()[:-1])
        report = benchmark_report(self.path)
        self.assertEqual(report["usable_observations"], 0)
        self.assertEqual(report["data_quality"]["invalid_decisions_json"], 1)
        self.assertEqual(report["data_quality"]["incomplete_decision_sets"], 1)

    def test_duplicate_unknown_confidence_and_evidence_are_quality_flags(self):
        values = self.decisions()
        values[-1]["id_decisao"] = values[0]["id_decisao"]
        values[0]["confianca"] = "X"
        values[1]["status_evidencias"] = "X"
        self.add(decisions=values)
        quality = benchmark_report(self.path)["data_quality"]
        self.assertEqual(quality["duplicate_decision_ids"], 1)
        self.assertEqual(quality["unknown_confidence_values"], 1)
        self.assertEqual(quality["unknown_evidence_status"], 1)

    def test_gate_consensus_and_decision_distributions(self):
        self.add(gate="REVISAO", consensus="DIVERGENCIA")
        report = benchmark_report(self.path)
        self.assertEqual(report["gate_distribution"]["REVISAO"]["count"], 1)
        self.assertEqual(report["consensus_distribution"]["DIVERGENCIA"]["count"], 1)
        self.assertEqual(report["decisions"]["regime_macro"]["confidence"]["ALTA"]["count"], 1)

    def test_same_hash_agreement_and_divergence(self):
        self.add(digest="same")
        values = {key: "NEUTRO" for key in IDS}
        values["contexto_operacional"] = "AGUARDAR"
        self.add(digest="same", decisions=self.decisions(values))
        report = benchmark_report(self.path)["stability"]
        self.assertEqual(report["repeated_state_groups"], 1)
        self.assertEqual(report["exact_full_decision_agreement_count"], 0)
        self.assertEqual(report["agreement_by_decision"]["regime_macro"]["rate"], 1.0)

    def test_different_hashes_are_not_compared(self):
        self.add(digest="a")
        self.add(digest="b")
        self.assertEqual(benchmark_report(self.path)["stability"]["repeated_state_groups"], 0)

    def test_cross_model_same_hash_is_descriptive_only(self):
        self.add(digest="same", model="modelo-a")
        self.add(digest="same", model="modelo-b")
        report = benchmark_report(self.path)["cross_model"]
        self.assertEqual(report["cross_model_state_groups"], 1)
        self.assertNotIn("winner", json.dumps(report).lower())
        self.assertNotIn("ranking", json.dumps(report).lower())

    def test_symbol_filter_applies_to_all_observations(self):
        self.add(symbol="WIN", digest="win")
        self.add(symbol="DOL", digest="dol")
        self.assertEqual(benchmark_report(self.path, "WIN")["total_observations"], 1)
        self.assertEqual(benchmark_report(self.path, "DOL")["total_observations"], 1)

    def test_report_is_read_only(self):
        before = Path(self.path).read_bytes()
        benchmark_report(self.path, "WIN")
        after = Path(self.path).read_bytes()
        self.assertEqual(before, after)

    def test_no_latency_or_outcome_quality_claims(self):
        report = benchmark_report(self.path)
        self.assertEqual(report["latency_status"], "INDISPONIVEL")
        encoded = json.dumps(report).lower()
        self.assertNotIn("win_rate", encoded)
        self.assertNotIn("taxa_acerto", encoded)

    def test_missing_models_and_unknown_statuses_are_reported(self):
        self.add(model=None, gate="X", consensus="X")
        report = benchmark_report(self.path)
        self.assertEqual(report["data_quality"]["missing_model_configured"], 1)
        self.assertEqual(report["data_quality"]["missing_model_used"], 1)
        self.assertEqual(report["data_quality"]["unknown_gate_status"], 1)
        self.assertEqual(report["data_quality"]["unknown_consensus_status"], 1)

    def test_fixed_gate_and_consensus_categories_include_unknown_and_zeroes(self):
        self.add(gate="DESCONHECIDO", consensus="DESCONHECIDO")
        report = benchmark_report(self.path)
        self.assertEqual(set(report["gate_distribution"]), {"VALIDO", "REVISAO", "BLOQUEADO", "OUTROS_DESCONHECIDOS"})
        self.assertEqual(set(report["consensus_distribution"]), {"CONSENSO", "DIVERGENCIA", "NAO_EXECUTADA", "OUTROS_DESCONHECIDOS"})
        self.assertEqual(report["gate_distribution"]["OUTROS_DESCONHECIDOS"]["count"], 1)
        self.assertEqual(report["gate_distribution"]["VALIDO"]["count"], 0)
        self.assertEqual(report["consensus_distribution"]["OUTROS_DESCONHECIDOS"]["count"], 1)
        self.assertEqual(report["consensus_distribution"]["CONSENSO"]["count"], 0)

    def test_null_gates_do_not_count_as_agreement(self):
        self.add(digest="same", gate=None)
        self.add(digest="same", gate=None)
        stability = benchmark_report(self.path)["stability"]
        self.assertEqual(stability["gate_agreement"]["eligible_groups"], 0)
        self.assertIsNone(stability["gate_agreement"]["agreement_rate"])

    def test_invalid_confidence_does_not_count_as_agreement(self):
        invalid = self.decisions(confidence="INVALIDA")
        self.add(digest="same", decisions=invalid)
        self.add(digest="same", decisions=invalid)
        item = benchmark_report(self.path)["stability"]["confidence_agreement_by_decision"]["regime_macro"]
        self.assertEqual(item["eligible_groups"], 0)
        self.assertIsNone(item["agreement_rate"])

    def test_identical_executions_count_as_full_agreement(self):
        self.add(digest="same")
        self.add(digest="same")
        stability = benchmark_report(self.path)["stability"]
        self.assertEqual(stability["exact_full_decision_agreement_count"], 1)
        self.assertEqual(stability["exact_full_decision_agreement_rate"], 1.0)

    def test_media_and_baixa_are_preserved_in_distribution(self):
        self.add(decisions=self.decisions(confidence="MEDIA"))
        self.add(digest="baixa", decisions=self.decisions(confidence="BAIXA"))
        distribution = benchmark_report(self.path)["decisions"]["regime_macro"]["confidence"]
        self.assertEqual(distribution["MEDIA"]["count"], 1)
        self.assertEqual(distribution["BAIXA"]["count"], 1)

    def test_sample_band_boundaries(self):
        expected = {29: "INSUFICIENTE", 30: "PRELIMINAR", 99: "PRELIMINAR",
                    100: "UTIL", 199: "UTIL", 200: "ROBUSTA"}
        for size, band in expected.items():
            self.assertEqual(sample_band(size), band)

    def test_repeated_same_model_preserves_all_cross_model_observations(self):
        self.add(digest="same", model="modelo-a")
        self.add(digest="same", model="modelo-a")
        self.add(digest="same", model="modelo-b")
        comparison = benchmark_report(self.path)["cross_model"]["comparisons"][0]
        self.assertEqual(len(comparison["observations_by_model"]["modelo-a"]), 2)
        self.assertEqual(len(comparison["observations_by_model"]["modelo-b"]), 1)

    def test_model_benchmark_flag_remains_disabled(self):
        self.assertFalse(flags()["MODEL_BENCHMARK_ENABLED"])


if __name__ == "__main__":
    unittest.main()
