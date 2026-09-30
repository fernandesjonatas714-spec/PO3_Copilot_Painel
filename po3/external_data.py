"""Dados externos públicos, sem chave de API e sem envio de ordens."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from .investing_calendar import fetch_investing_calendar
from .market_news import fetch_authorized_quotes, fetch_market_headlines
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from zoneinfo import ZoneInfo
import json

BRASILIA = ZoneInfo("America/Sao_Paulo")
OFFICIAL_SOURCES = ("BCB", "IBGE", "FGV", "B3", "Federal Reserve", "BLS", "BEA", "Census Bureau")
RELEVANT_EVENT_TERMS = (
    "infla", "ipca", "cpi", "pce", "payroll", "emprego", "desemprego", "folha",
    "juros", "taxa", "selic", "copom", "fomc", "fed", "pib", "varejo", "pmi",
    "produção", "producao", "confiança", "confianca", "dólar", "dolar", "petróleo", "petroleo",
)


def filter_relevant_events(events: list[dict]) -> list[dict]:
    """Mantém somente eventos de 2 ou 3 estrelas que podem mexer no WIN, DOL ou juros."""
    result = []
    for event in events:
        impact = str(event.get("impacto", "")).upper()
        title = str(event.get("evento", "")).lower()
        country = str(event.get("pais", "")).upper()
        if impact not in {"MÉDIO", "MEDIO", "ALTO", "HIGH", "3"}:
            continue
        if country not in {"BR", "US", "EU", "CN"}:
            continue
        if not any(term in title for term in RELEVANT_EVENT_TERMS):
            continue
        result.append(event)
    return result


def _number(value):
    try:
        if value in (None, "", "-", "null"):
            return None
        return float(str(value).replace(",", ".").replace("%", ""))
    except (TypeError, ValueError):
        return None


def _impact_bias(item: dict) -> str:
    actual = _number(item.get("actual"))
    forecast = _number(item.get("forecast"))
    if actual is None or forecast is None:
        return "Neutro"
    title = str(item.get("event", "")).lower()
    delta = actual - forecast
    if "juros" in title or "taxa" in title or "infla" in title:
        return "Vendedor" if delta > 0 else "Comprador" if delta < 0 else "Neutro"
    if "desemprego" in title or "jobless" in title:
        return "Vendedor" if delta > 0 else "Comprador" if delta < 0 else "Neutro"
    return "Comprador" if delta > 0 else "Vendedor" if delta < 0 else "Neutro"


def fetch_official_calendar() -> dict:
    """Consulta somente o Investing; fontes de notícias permanecem bloqueadas."""
    result = fetch_investing_calendar()
    result["news_sources"] = []
    return result


def fetch_daily_context() -> dict:
    """Retorna calendário Investing + manchetes autorizadas para a análise manual."""
    calendar = fetch_official_calendar()
    if calendar.get("available"):
        relevant = filter_relevant_events(calendar.get("events", []))
        calendar = {**calendar, "events": relevant[:30], "relevantes_filtrados": True}
    news = fetch_market_headlines()
    quotes = fetch_authorized_quotes()
    return {"calendar": calendar, "news": news, "quotes": quotes}

def get_next_high_impact_event(events: list[dict], now: datetime | None = None) -> dict | None:
    for event in events:
        if str(event.get("impacto", "")).upper() in {"ALTO", "HIGH", "3"}:
            return event
    return None
