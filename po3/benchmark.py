"""Benchmark offline de avaliações já registradas."""
def compare(runs_a:list[dict], runs_b:list[dict])->dict:
    return {"versao_a":len(runs_a),"versao_b":len(runs_b),"diferenca":len(runs_b)-len(runs_a)}
