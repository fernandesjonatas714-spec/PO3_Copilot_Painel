"""Leitura macro local do MT5, sem negociação e sem fontes inventadas."""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from statistics import mean, pstdev
import re


GROUPS = {
    "B3": (1.00, ("IBOV", "IND", "IBOVESPA")),
    "Dólar": (-0.85, ("DOL", "WDO", "USDBRL")),
    "Juros": (-0.50, ("DI1", "DI1FUT", "DI1J27")),
    "Exterior": (0.55, ("US500", "US100", "SPX500", "SP500", "SPX", "SPXI11", "NASD11", "NAS100", "USTEC", "NASDAQ", "QQQ", "NQ", "NQFUT")),
    "Volatilidade": (-0.45, ("VIX", "VIX.F", "VIXUSD", "VOLX")),
    "Commodities": (0.30, ("IRON", "IRONORE", "FEF", "USOIL", "OIL", "XAUUSD", "GOLD", "GOLD11", "CLPV26", "CLPF27", "CLPZ26", "CLFUT")),
}

LEADERS = {
    "Petróleo": ("PETR4", "PETR3"),
    "Mineração": ("VALE3",),
    "Itaú": ("ITUB4", "ITUB3"),
    "Bradesco": ("BBDC4", "BBDC3"),
    "Banco do Brasil": ("BBAS3",),
    "B3": ("B3SA3",),
    "Eletrobras": ("ELET3", "ELET6"),
    "Suzano": ("SUZB3",),
    "Weg": ("WEGE3",),
    "Ambev": ("ABEV3",),
}


def _resolve(mt5, aliases: tuple[str, ...]):
    for alias in aliases:
        info = mt5.symbol_info(alias)
        if info is not None:
            return alias
    try:
        names = [(str(getattr(info, "name", "")), str(getattr(info, "name", "")).upper()) for info in (mt5.symbols_get() or ())]
        for alias in aliases:
            if len(alias) < 4:
                for original, upper in names:
                    suffix = upper[len(alias):] if upper.startswith(alias) else ""
                    year = int(suffix[-2:]) if len(suffix) == 3 and suffix[-2:].isdigit() else 0
                    if upper.startswith(alias) and re.match(r"^[FGHJKMNQUVXZ]\d{2}$", suffix) and 20 <= year <= 40:
                        return original
            else:
                for original, upper in names:
                    if upper.startswith(alias):
                        return original
    except Exception:
        return None
    return None


def _series(mt5, symbol: str, timeframe, count=100):
    try:
        if not mt5.symbol_select(symbol, True):
            return []
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 1, count)
    except Exception:
        return []
    if rates is None or len(rates) < 25:
        return []
    return [float(x["close"]) for x in rates if isfinite(float(x["close"])) and float(x["close"]) > 0]


def _returns(values):
    return [(values[i] / values[i - 1]) - 1.0 for i in range(1, len(values)) if values[i - 1]]


def _direction(values):
    if len(values) < 21:
        return None
    return max(-1.0, min(1.0, (values[-1] / values[-21] - 1.0) / 0.015))


def _corr(a, b):
    n = min(len(a), len(b))
    if n < 20:
        return None
    x, y = a[-n:], b[-n:]
    mx, my = mean(x), mean(y)
    den = sum((u - mx) ** 2 for u in x) * sum((v - my) ** 2 for v in y)
    if den <= 0:
        return None
    return max(-1.0, min(1.0, sum((u-mx)*(v-my) for u,v in zip(x,y)) / den**0.5))


def build_macro(mt5, primary: str, timeframe) -> dict:
    """Calcula um score condicional aos símbolos que o MT5 realmente fornece."""
    base_symbol = primary
    base = _series(mt5, base_symbol, timeframe)
    if len(base) < 25:
        return {"available": False, "score": None, "confidence": "baixa", "factors": [], "expected": {k:list(v[1]) for k,v in GROUPS.items()}, "note": "Histórico do WIN insuficiente."}
    base_ret = _returns(base)
    factors, missing = [], []
    for group, (weight, aliases) in GROUPS.items():
        symbol = _resolve(mt5, aliases)
        if not symbol:
            missing.append(group)
            continue
        values = _series(mt5, symbol, timeframe)
        direction = _direction(values)
        if direction is None:
            missing.append(group)
            continue
        corr = _corr(base_ret, _returns(values))
        if corr is None:
            missing.append(group)
            continue
        contribution = direction * corr * weight
        factors.append({"grupo": group, "simbolo": symbol, "direcao": direction, "correlacao": corr, "contribuicao": contribution})
    leaders, leaders_missing = [], []
    for name, aliases in LEADERS.items():
        symbol = _resolve(mt5, aliases)
        values = _series(mt5, symbol, timeframe) if symbol else []
        direction = _direction(values) if values else None
        if symbol and direction is not None:
            leaders.append({"ativo": name, "simbolo": symbol, "direcao": direction})
        else:
            leaders_missing.append(name)
    total_weight = sum(abs(x["correlacao"] * GROUPS[x["grupo"]][0]) for x in factors)
    raw = sum(x["contribuicao"] for x in factors)
    score = max(-100.0, min(100.0, 100.0 * raw / total_weight)) if total_weight else None
    confidence = "alta" if len(factors) >= 4 and total_weight >= 1.2 else "média" if len(factors) >= 2 else "baixa"
    if score is None:
        bias = "indisponível"
    elif score >= 20:
        bias = "comprador"
    elif score <= -20:
        bias = "vendedor"
    else:
        bias = "neutro"
    positive = sum(x["direcao"] > 0 for x in leaders)
    negative = sum(x["direcao"] < 0 for x in leaders)
    flat = len(leaders) - positive - negative
    short_return = (base[-1] / base[-5] - 1.0) if len(base) >= 5 else None
    long_return = (base[-1] / base[-21] - 1.0) if len(base) >= 21 else None
    volatility = pstdev(base_ret[-20:]) if len(base_ret) >= 20 else None
    return {"available": bool(factors), "score": score, "bias": bias, "confidence": confidence,
            "factors": factors, "leaders": leaders, "leaders_missing": leaders_missing,
            "breadth": {"positive": positive, "negative": negative, "flat": flat, "total": len(leaders)},
            "market": {"return_short": short_return, "return_long": long_return, "volatility": volatility},
            "missing": missing, "expected": {k:list(v[1]) for k,v in GROUPS.items()}, "timeframe": str(timeframe), "as_of": datetime.now(timezone.utc).isoformat()}
