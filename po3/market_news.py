"""Coleta controlada de manchetes de mercado em fontes permitidas.

O módulo não interpreta notícias nem inventa dados; apenas devolve títulos e
links encontrados nas páginas públicas autorizadas pelo projeto.
"""
from __future__ import annotations

from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import re

BRASILIA = ZoneInfo("America/Sao_Paulo")


class _HeadlineParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[tuple[str, str]] = []
        self._href = ""
        self._text: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        attrs_map = dict(attrs)
        if tag == "a":
            self._href = attrs_map.get("href", "")
            self._text = []
            self._depth = 1
        elif self._depth and tag in {"span", "strong", "b"}:
            self._depth += 1

    def handle_data(self, data):
        if self._depth:
            value = " ".join(data.split())
            if value:
                self._text.append(value)

    def handle_endtag(self, tag):
        if tag == "a" and self._depth:
            text = " ".join(self._text).strip()
            if len(text) >= 28:
                self.items.append((text, self._href))
            self._href, self._text, self._depth = "", [], 0


SOURCES = (
    ("InfoMoney", "Brasil", "https://www.infomoney.com.br/mercados/", "https://www.infomoney.com.br"),
    ("Money Times", "Brasil", "https://www.moneytimes.com.br/", "https://www.moneytimes.com.br"),
    ("Investing.com Brasil", "Brasil", "https://br.investing.com/news/headlines", "https://br.investing.com"),
    ("Valor Econômico", "Brasil", "https://valor.globo.com/", "https://valor.globo.com"),
    ("E-Investidor Estadão", "Brasil", "https://einvestidor.estadao.com.br/", "https://einvestidor.estadao.com.br"),
    ("TradingView", "EUA", "https://www.tradingview.com/markets/stock-market-news/", "https://www.tradingview.com"),
    ("Investing.com EUA", "EUA", "https://www.investing.com/news/stock-market-news", "https://www.investing.com"),
    ("Yahoo Finance", "EUA", "https://finance.yahoo.com/news/", "https://finance.yahoo.com"),
    ("CNBC", "EUA", "https://www.cnbc.com/markets/", "https://www.cnbc.com"),
    ("MarketWatch", "EUA", "https://www.marketwatch.com/markets", "https://www.marketwatch.com"),
    ("CME Group", "EUA/Juros", "https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html", "https://www.cmegroup.com"),
)


def _absolute(base: str, href: str) -> str:
    if href.startswith("http"):
        return href
    return base.rstrip("/") + "/" + href.lstrip("/")


def fetch_market_headlines(limit_per_source: int = 6) -> dict:
    checked_at = datetime.now(BRASILIA)
    all_items: list[dict] = []
    statuses: list[str] = []
    for source, region, url, base in SOURCES:
        try:
            request = Request(url, headers={"User-Agent": "PO3-Copilot-B3/1.0"})
            with urlopen(request, timeout=10) as response:
                html = response.read().decode("utf-8", errors="replace")
            parser = _HeadlineParser()
            parser.feed(html)
            seen: set[str] = set()
            count = 0
            for title, href in parser.items:
                clean = re.sub(r"\s+", " ", title).strip()
                key = clean.casefold()
                if key in seen or not href:
                    continue
                seen.add(key)
                all_items.append({"fonte": source, "regiao": region, "titulo": clean, "url": _absolute(base, href)})
                count += 1
                if count >= limit_per_source:
                    break
            statuses.append(f"{source}: {count} manchetes")
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            statuses.append(f"{source}: indisponível ({type(exc).__name__})")
    return {"available": bool(all_items), "items": all_items, "statuses": statuses, "checked_at": checked_at.isoformat()}


def fetch_authorized_quotes() -> dict:
    """Cotações públicas da Yahoo Finance, uma das fontes autorizadas."""
    symbols = {"NASDAQ": "^IXIC", "S&P 500": "^GSPC", "VIX": "^VIX", "Gold": "GC=F", "Oil WTI": "CL=F", "Dólar/BRL": "BRL=X"}
    quotes, statuses = {}, []
    for label, symbol in symbols.items():
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol.replace('^', '%5E').replace('=', '%3D')}?range=5d&interval=1d"
        try:
            request = Request(url, headers={"User-Agent": "PO3-Copilot-B3/1.0"})
            with urlopen(request, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
            result = payload["chart"]["result"][0]
            meta = result.get("meta", {})
            closes = [x for x in result.get("indicators", {}).get("quote", [{}])[0].get("close", []) if x is not None]
            quotes[label] = {"simbolo": symbol, "ultimo": closes[-1] if closes else meta.get("regularMarketPrice"), "fechamento_anterior": meta.get("previousClose"), "fonte": "Yahoo Finance"}
            statuses.append(f"{label}: disponível")
        except (HTTPError, URLError, TimeoutError, OSError, KeyError, IndexError, json.JSONDecodeError) as exc:
            statuses.append(f"{label}: indisponível ({type(exc).__name__})")
    return {"available": bool(quotes), "quotes": quotes, "statuses": statuses}
