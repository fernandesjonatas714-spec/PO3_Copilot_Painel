"""Coletor controlado do calendário público do Investing.com.

Não executa ordens, não consulta notícias e não troca automaticamente de fonte.
"""
from __future__ import annotations

from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo
import re
import json


URL = "https://br.investing.com/economic-calendar"
BRASILIA = ZoneInfo("America/Sao_Paulo")
COUNTRIES = {"US", "BR", "EU", "CN", "JP", "GB"}


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._cell = []

    def handle_data(self, data):
        if self._cell is not None:
            text = " ".join(data.split())
            if text:
                self._cell.append(text)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self._row is not None and self._cell is not None:
            self._row.append(" ".join(self._cell).strip())
            self._cell = None
        elif tag == "tr" and self._row:
            self.rows.append(self._row)
            self._row = None


def _importance(text: str) -> str:
    normalized = text.lower().replace("�", "")
    stars = text.count("★")
    if stars >= 3 or "alto" in text.lower():
        return "ALTO"
    if stars == 2 or "médio" in text.lower() or "medio" in text.lower():
        return "MÉDIO"
    # Algumas respostas do Investing entregam a estrela apenas como ícone
    # CSS. Mantemos a filtragem conservadora por eventos macro reconhecidos.
    high_terms = ("payroll", "cpi", "ipc", "ipca", "pce", "fomc", "copom", "selic", "pib", "desemprego", "nonfarm")
    medium_terms = ("juros", "taxa", "emprego", "varejo", "pmi", "produção", "producao", "confiança", "confianca", "hipoteca")
    if any(term in normalized for term in high_terms):
        return "ALTO"
    if any(term in normalized for term in medium_terms):
        return "MÉDIO"
    return "BAIXO"


def _split_event_values(event: str, values: list[str]) -> tuple[str, str, str, str]:
    """Separa título e valores quando o Investing concatena tudo na célula Evento."""
    text = " ".join(str(event).split())
    match = re.search(
        r"^(?P<title>.+?)\s+Atual\s*:\s*(?P<actual>.*?)\s+Cons\s*:\s*(?P<forecast>.*?)\s+Anterior\s*:\s*(?P<previous>.*)$",
        text,
        flags=re.IGNORECASE,
    )
    if match:
        return (
            match.group("title").strip(),
            match.group("previous").strip() or "—",
            match.group("forecast").strip() or "—",
            match.group("actual").strip() or "—",
        )
    return text, (values[-3] if len(values) >= 3 else "—"), (values[-2] if len(values) >= 2 else "—"), (values[-1] if values else "—")


def _event_bias(title: str, actual: str, forecast: str, previous: str = "—") -> str:
    def number(value: str):
        try:
            return float(str(value).replace("%", "").replace(".", "").replace(",", ".").strip())
        except (TypeError, ValueError):
            return None
    a, f, p = number(actual), number(forecast), number(previous)
    if f is None and a is None:
        return "Sem leitura"
    base = f if a is None else a
    reference = p if a is None else f
    if base is None or reference is None:
        return "Sem leitura"
    delta = base - reference
    lower = title.lower()
    inverse = any(term in lower for term in ("infla", "ipc", "cpi", "pce", "juros", "taxa", "desemprego"))
    if abs(delta) < 1e-9:
        return "Neutro"
    if inverse:
        return "Vendedor" if delta > 0 else "Comprador"
    return "Comprador" if delta > 0 else "Vendedor"


def _clean_value(value) -> str:
    text = str(value or "").strip()
    if not text or text in {"-", "N/A", "n/a"} or any(ord(ch) in {0x2014, 0xfffd} for ch in text):
        return "—"
    return text


def _embedded_events(html: str, checked_at: datetime) -> list[dict]:
    """Lê o estado JSON que o Investing usa para renderizar os horários."""
    marker = '"economicCalendarStore":'
    index = html.find(marker)
    if index < 0:
        return []
    start = html.find("{", index + len(marker))
    if start < 0:
        return []
    try:
        store, _ = json.JSONDecoder().raw_decode(html[start:])
    except (ValueError, json.JSONDecodeError):
        return []
    by_date = store.get("calendarEventsByDate", {}) if isinstance(store, dict) else {}
    events: list[dict] = []
    currency_to_country = {"USD": "US", "BRL": "BR", "EUR": "EU", "CNY": "CN"}
    today = checked_at.date().isoformat()
    for day, day_events in by_date.items():
        if str(day) != today:
            continue
        for item in day_events or []:
            if not isinstance(item, dict):
                continue
            country = currency_to_country.get(str(item.get("currency", "")).upper())
            if not country:
                continue
            importance = str(item.get("importance", "1"))
            impact = "ALTO" if importance == "3" else "MÉDIO" if importance == "2" else "BAIXO"
            title = str(item.get("eventLong") or item.get("event") or "").strip()
            event_time = item.get("time")
            dt = None
            try:
                dt = datetime.fromisoformat(str(event_time).replace("Z", "+00:00")).astimezone(BRASILIA)
                hour = dt.strftime("%H:%M")
            except (TypeError, ValueError):
                hour = "Não fornecido"
            if dt is not None and dt.date() != checked_at.date():
                continue
            actual = _clean_value(item.get("actual"))
            forecast = _clean_value(item.get("forecast"))
            previous = _clean_value(item.get("previous"))
            if dt is None or dt > checked_at:
                actual = "—"
            events.append({
                "data": dt.strftime("%d/%m/%Y") if dt is not None else checked_at.strftime("%d/%m/%Y"),
                "pais": country, "evento": title, "impacto": impact, "hora": hour,
                "anterior": previous, "previsao": forecast, "resultado": actual,
                "vies": _event_bias(title, actual, forecast, previous), "fonte": URL,
                "coletado_em": checked_at.isoformat(),
                "datetime": dt,
            })
    return events


def fetch_investing_calendar() -> dict:
    request = Request(URL, headers={"User-Agent": "PO3-Copilot-B3/1.0"})
    checked_at = datetime.now(timezone.utc).astimezone(BRASILIA)
    try:
        with urlopen(request, timeout=12) as response:
            html = response.read().decode("utf-8", errors="replace")
        embedded = _embedded_events(html, checked_at)
        if embedded:
            return {"available": True, "events": embedded[:100], "source": "Investing.com", "message": "Calendário consultado.", "checked_at": checked_at.isoformat()}
        parser = _TableParser()
        parser.feed(html)
        events = []
        for row in parser.rows:
            if len(row) < 3:
                continue
            country = next((item for item in row if item in COUNTRIES), None)
            if not country:
                continue
            event = next((item for item in row if len(item) > 4 and item not in COUNTRIES), None)
            if not event:
                continue
            values = [item for item in row if item != country and item != event]
            event_title, previous, forecast, actual = _split_event_values(event, values)
            previous, forecast, actual = _clean_value(previous), _clean_value(forecast), _clean_value(actual)
            events.append({
                "data": checked_at.strftime("%d/%m/%Y"),
                "pais": country,
                "evento": event_title,
                "impacto": _importance(" ".join(row)),
                "hora": next((item for item in values if re.search(r"\b\d{1,2}:\d{2}\b", item)), "Não fornecido"),
                "anterior": previous,
                "previsao": forecast,
                "resultado": actual,
                "vies": _event_bias(event_title, actual, forecast, previous),
                "fonte": URL,
                "coletado_em": checked_at.isoformat(),
            })
        if not events:
            return {"available": False, "events": [], "source": "Investing.com", "message": "A estrutura do Investing mudou ou não trouxe eventos reconhecíveis.", "checked_at": checked_at.isoformat()}
        return {"available": True, "events": events[:20], "source": "Investing.com", "message": "Calendário consultado.", "checked_at": checked_at.isoformat()}
    except HTTPError as exc:
        return {"available": False, "events": [], "source": "Investing.com", "message": f"Investing retornou HTTP {exc.code}.", "checked_at": checked_at.isoformat()}
    except (TimeoutError, URLError, OSError) as exc:
        return {"available": False, "events": [], "source": "Investing.com", "message": f"Investing indisponível: {type(exc).__name__}.", "checked_at": checked_at.isoformat()}
