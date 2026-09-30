"""Replay histórico isolado para avaliar a análise da IA.

Este módulo não altera prompts, modelos, regras ou o snapshot usado pelo painel.
Ele somente lê candles, envia um registro histórico para a IA e grava um relatório.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
import json
import re
from zoneinfo import ZoneInfo

from .ai_service import OpenRouterError, send_message

SAO_PAULO = ZoneInfo("America/Sao_Paulo")


@dataclass(frozen=True)
class ReplayConfig:
    terminal_path: str
    symbol: str
    days: int = 30
    cutoff_hour: int = 10
    cutoff_minute: int = 0
    horizon_minutes: int = 60


def _mt5():
    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise RuntimeError("Pacote MetaTrader5 não instalado.") from exc
    return mt5


def _bars(rates):
    if rates is None:
        return []
    return [{"time": datetime.fromtimestamp(int(row["time"]), tz=ZoneInfo("UTC")).astimezone(SAO_PAULO),
             "open": float(row["open"]), "high": float(row["high"]), "low": float(row["low"]),
             "close": float(row["close"]), "tick_volume": int(row["tick_volume"])} for row in rates]


def _direction(change: float | None) -> str:
    if change is None or abs(change) < 0.002:
        return "neutro"
    return "comprador" if change > 0 else "vendedor"


def _aggregate(bars: list[dict], minutes: int) -> list[dict]:
    """Agrega M1 em um timeframe, sem usar candles posteriores ao corte."""
    buckets: dict[datetime, list[dict]] = {}
    for bar in bars:
        t = bar["time"].replace(second=0, microsecond=0)
        bucket = t - timedelta(minutes=t.minute % minutes)
        buckets.setdefault(bucket, []).append(bar)
    output = []
    for t, rows in sorted(buckets.items()):
        output.append({"time": t, "open": rows[0]["open"], "high": max(x["high"] for x in rows),
                       "low": min(x["low"] for x in rows), "close": rows[-1]["close"],
                       "tick_volume": sum(x["tick_volume"] for x in rows)})
    return output


def _bias_from_text(text: str) -> str:
    match = re.search(r"viés[^\n]{0,80}?\b(comprador|vendedor|neutro)\b", text.lower())
    return match.group(1) if match else "não identificado"


def _quality(text: str) -> dict:
    lower = text.lower()
    required = all(term in lower for term in ("macroeconomia", "impacto na bolsa", "insight operacional"))
    boilerplate = any(term in lower for term in ("como po3 copilot", "minha função é", "não executo ordens"))
    return {"secoes_obrigatorias": required, "boilerplate_indesejado": boilerplate,
            "diferenciou_fato_inferencia": "inferência" in lower or "inferência" in lower,
            "score": int(required) + int(not boilerplate) + int("sem dados" not in lower)}


def _prompt(record: dict) -> str:
    return ("Faça a mesma análise diária do PO3 Copilot usando somente o snapshot histórico abaixo. "
            "Mantenha os três blocos MACROECONOMIA E DIA A DIA, IMPACTO NA BOLSA e INSIGHT OPERACIONAL. "
            "Não invente notícias, calendário ou cotações ausentes; quando não houver fonte histórica, use somente MT5 e indique sem leitura. "
            "Não use qualquer informação posterior ao horário de corte. Responda em português.\n\n" +
            json.dumps(record, ensure_ascii=False, default=str))


def _historical_days(cfg: ReplayConfig) -> list[dict]:
    mt5 = _mt5()
    if not mt5.initialize(cfg.terminal_path, timeout=8_000):
        raise RuntimeError(f"Falha ao conectar ao MT5: {mt5.last_error()}")
    try:
        end = datetime.now(SAO_PAULO)
        start = end - timedelta(days=max(cfg.days + 10, 40))
        rates = mt5.copy_rates_range(cfg.symbol, mt5.TIMEFRAME_M1, start, end)
        bars = _bars(rates)
        grouped: dict[str, list[dict]] = {}
        for bar in bars:
            grouped.setdefault(bar["time"].date().isoformat(), []).append(bar)
        records = []
        for date_text, day_bars in sorted(grouped.items(), reverse=True):
            if len(records) >= cfg.days:
                break
            cutoff = datetime.fromisoformat(date_text).replace(hour=cfg.cutoff_hour, minute=cfg.cutoff_minute, tzinfo=SAO_PAULO)
            before = [b for b in day_bars if b["time"] <= cutoff]
            after = [b for b in day_bars if b["time"] > cutoff]
            if not before or not after:
                continue
            price = before[-1]["close"]
            future = next((b for b in after if b["time"] >= cutoff + timedelta(minutes=cfg.horizon_minutes)), after[-1])
            movement = (future["close"] / price - 1.0) if price else None
            frames = {"M1": before[-240:], "M5": _aggregate(before, 5), "M15": _aggregate(before, 15),
                      "H1": _aggregate(before, 60), "H4": _aggregate(before, 240), "D1": _aggregate(before, 1440)}
            records.append({"data": date_text, "horario_corte": cutoff.isoformat(), "ativo": cfg.symbol,
                            "preco_mt5": price, "movimento_posterior": movement,
                            "direcao_observada": _direction(movement),
                            "dados_historicos": frames,
                            "macro_mt5": {"status": "parcial", "fonte": "MT5", "fatores": "não reconstituídos sem histórico sincronizado dos símbolos externos"},
                            "contexto": {"fonte": "MT5", "calendario_historico": "indisponível", "noticias_historicas": "indisponível"}})
        return records
    finally:
        mt5.shutdown()


def run_replay(cfg: ReplayConfig, output_dir: str | Path) -> Path:
    """Executa o replay e grava JSON/Markdown; falhas de um dia não interrompem os demais."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    started = datetime.now(SAO_PAULO)
    try:
        records = _historical_days(cfg)
    except Exception as exc:
        records = []
        collection_error = f"{type(exc).__name__}: {exc}"
    else:
        collection_error = None
    results = []
    for record in records:
        item = {"data": record["data"], "horario_corte": record["horario_corte"],
                "direcao_observada": record["direcao_observada"], "movimento_posterior": record["movimento_posterior"]}
        try:
            answer = send_message(_prompt(record), system_instruction="Você é um avaliador histórico. Use somente os dados fornecidos e não use conhecimento posterior ao corte.")
            item.update({"status": "avaliado", "resposta": answer, "vies_produzido": _bias_from_text(answer), "qualidade": _quality(answer)})
            item["acerto_direcional"] = item["vies_produzido"] == item["direcao_observada"] if item["vies_produzido"] != "não identificado" else None
        except Exception as exc:
            item.update({"status": "erro", "erro": f"{type(exc).__name__}: {exc}"})
        results.append(item)
    report = {"gerado_em": started.isoformat(), "periodo_solicitado_dias": cfg.days,
              "parametros": {"ativo": cfg.symbol, "horario_corte": f"{cfg.cutoff_hour:02d}:{cfg.cutoff_minute:02d}", "horizonte_minutos": cfg.horizon_minutes},
              "erro_coleta": collection_error, "dias_encontrados": len(records), "resultados": results,
              "observacao": "Relatório de avaliação; nenhum prompt, modelo, regra ou indicador foi alterado."}
    stamp = started.strftime("%Y%m%d_%H%M%S")
    json_path = output / f"replay_{stamp}.json"
    md_path = output / f"replay_{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    accuracy = [r["acerto_direcional"] for r in results if isinstance(r.get("acerto_direcional"), bool)]
    quality_scores = [r.get("qualidade", {}).get("score") for r in results if isinstance(r.get("qualidade"), dict)]
    md = [f"# Avaliação histórica da IA — {stamp}", "", f"- Período solicitado: {cfg.days} dias", f"- Dias encontrados: {len(records)}", f"- Horário de corte: {cfg.cutoff_hour:02d}:{cfg.cutoff_minute:02d} (Brasília)", f"- Acerto direcional: {sum(accuracy)}/{len(accuracy)}" if accuracy else "- Acerto direcional: sem dados", f"- Qualidade estrutural média: {sum(quality_scores)/len(quality_scores):.2f}/3" if quality_scores else "- Qualidade estrutural média: sem dados", "", "## Resultados"]
    for r in results:
        md.append(f"- {r['data']} — {r.get('status')} — viés: {r.get('vies_produzido', '—')} — observado: {r.get('direcao_observada', '—')}")
    if collection_error:
        md.extend(["", f"Erro de coleta: {collection_error}"])
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    return md_path


def build_independent_report(cfg: ReplayConfig, output_dir: str | Path) -> Path:
    """Gera auditoria independente, sem OpenRouter e sem alterar a IA."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    records = _historical_days(cfg)
    directions = {"comprador": 0, "vendedor": 0, "neutro": 0}
    for record in records:
        directions[record["direcao_observada"]] = directions.get(record["direcao_observada"], 0) + 1
    stamp = datetime.now(SAO_PAULO).strftime("%Y%m%d_%H%M%S")
    report = {"tipo": "auditoria_independente", "gerado_em": datetime.now(SAO_PAULO).isoformat(),
              "periodo_solicitado_dias": cfg.days, "dias_avaliados": len(records),
              "periodo": {"inicio": records[-1]["data"] if records else None, "fim": records[0]["data"] if records else None},
              "parametros": {"ativo": cfg.symbol, "horario_corte": f"{cfg.cutoff_hour:02d}:{cfg.cutoff_minute:02d}", "horizonte_minutos": cfg.horizon_minutes},
              "direcoes_observadas": directions, "registros": records,
              "fontes": {"principal": "MT5", "calendario_historico": "não disponível", "noticias_historicas": "não disponível"},
              "observacao": "Auditoria independente; nenhum dado futuro foi enviado à IA e nenhuma regra de produção foi alterada."}
    path = output / f"auditoria_independente_{stamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    md = [f"# Auditoria independente do WIN — {stamp}", "", f"- Dias solicitados: {cfg.days}", f"- Dias avaliados: {len(records)}", f"- Período: {report['periodo']['inicio']} a {report['periodo']['fim']}", f"- Corte diário: {cfg.cutoff_hour:02d}:{cfg.cutoff_minute:02d} (Brasília)", "", "## Movimento posterior observado", ""]
    for key, value in directions.items():
        md.append(f"- {key}: {value} dia(s)")
    md += ["", "## Critérios", "", "- Fonte primária: candles históricos do MT5.", "- Notícias e calendário históricos não foram inventados.", "- O movimento posterior é medido no horizonte configurado após o corte.", "- Este relatório não altera prompts, modelos, regras ou indicadores."]
    md_path = output / f"auditoria_independente_{stamp}.md"
    md_path.write_text("\n".join(md) + "\n", encoding="utf-8")
    return md_path
