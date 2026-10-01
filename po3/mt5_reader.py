from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .levels import build_active_zones, build_context_levels
from .models import MarketSnapshot, PO3Event
from .macro import build_macro


SAO_PAULO = ZoneInfo("America/Sao_Paulo")


class MT5ReadError(RuntimeError):
    pass


def _load_package():
    try:
        import MetaTrader5 as mt5
    except ImportError as exc:
        raise MT5ReadError("Pacote MetaTrader5 nao instalado.") from exc
    return mt5


def _rates_to_bars(rates, *, normalize_timestamp=None, timeframe_seconds: int | None = None,
                   cutoff_at_utc: datetime | None = None) -> list[dict]:
    if rates is None:
        return []
    bars: list[dict] = []
    for row in rates:
        raw_time = int(row["time"])
        opened = normalize_timestamp(raw_time) if normalize_timestamp else datetime.fromtimestamp(raw_time, tz=timezone.utc).astimezone(SAO_PAULO)
        close_time = opened.astimezone(timezone.utc) + timedelta(seconds=timeframe_seconds or 0)
        if cutoff_at_utc is not None and close_time > cutoff_at_utc.astimezone(timezone.utc):
            continue
        bars.append(
            {
                "time": opened,
                "close_time": close_time,
                "known_at": close_time,
                "source_timestamp_raw": raw_time,
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "tick_volume": int(row["tick_volume"]),
            }
        )
    return sorted(bars, key=lambda bar: bar["time"])


def _tf_seconds(mt5, timeframe) -> int:
    mapping = {
        getattr(mt5, "TIMEFRAME_M1", object()): 60,
        getattr(mt5, "TIMEFRAME_M5", object()): 300,
        getattr(mt5, "TIMEFRAME_M15", object()): 900,
        getattr(mt5, "TIMEFRAME_M30", object()): 1800,
        getattr(mt5, "TIMEFRAME_H1", object()): 3600,
        getattr(mt5, "TIMEFRAME_H4", object()): 14400,
        getattr(mt5, "TIMEFRAME_D1", object()): 86400,
        getattr(mt5, "TIMEFRAME_W1", object()): 604800,
        getattr(mt5, "TIMEFRAME_MN1", object()): 31 * 86400,
    }
    return mapping.get(timeframe, 60)


class _CausalRatesProxy:
    """Proxy MT5 que expõe apenas séries fechadas até o cutoff."""
    def __init__(self, mt5, symbol: str, cutoff: datetime, normalize_timestamp):
        self._mt5 = mt5
        self._symbol = symbol
        self._cutoff = cutoff.astimezone(timezone.utc)
        self._normalize = normalize_timestamp

    def __getattr__(self, name):
        return getattr(self._mt5, name)

    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        rates = self._mt5.copy_rates_from_pos(symbol, timeframe, 0, max(count + 2, 200))
        bars = _rates_to_bars(rates, normalize_timestamp=self._normalize,
                               timeframe_seconds=_tf_seconds(self._mt5, timeframe), cutoff_at_utc=self._cutoff)
        # build_macro historically pede start_pos=1 para ignorar a barra atual;
        # como a proxy já removeu barras em formação, manter a remoção é seguro.
        selected = bars[start_pos:start_pos + count]
        return [{"time": int(datetime.fromisoformat(str(x["time"]).replace("Z", "+00:00")).timestamp()),
                 "close": x["close"], "open": x["open"], "high": x["high"], "low": x["low"]} for x in selected]


def read_snapshot_at_cutoff(terminal_path: str, symbol: str, cutoff_at_utc: datetime, *, normalize_timestamp) -> MarketSnapshot:
    """Captura somente o que já era conhecido no cutoff, sem tick posterior."""
    mt5 = _load_package()
    terminal = Path(terminal_path)
    if not terminal.is_file():
        raise MT5ReadError(f"Terminal nao encontrado: {terminal}")
    cutoff = cutoff_at_utc.astimezone(timezone.utc)
    if not mt5.initialize(str(terminal), timeout=8_000):
        raise MT5ReadError(f"Falha ao conectar ao MT5: {mt5.last_error()}")
    try:
        info = mt5.terminal_info()
        if info is None or not bool(info.connected):
            raise MT5ReadError("MT5 aberto, mas sem conexao com o servidor.")
        frames = {"M15": (mt5.TIMEFRAME_M15, 160), "M5": (mt5.TIMEFRAME_M5, 220),
                  "M1": (mt5.TIMEFRAME_M1, 300), "D1": (mt5.TIMEFRAME_D1, 120)}
        bars = {name: _rates_to_bars(mt5.copy_rates_from_pos(symbol, tf, 0, count),
                                     normalize_timestamp=normalize_timestamp,
                                     timeframe_seconds=_tf_seconds(mt5, tf), cutoff_at_utc=cutoff)
                for name, (tf, count) in frames.items()}
        weekly = _rates_to_bars(mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_W1, 0, 120),
                                normalize_timestamp=normalize_timestamp, timeframe_seconds=_tf_seconds(mt5, mt5.TIMEFRAME_W1), cutoff_at_utc=cutoff)
        monthly = _rates_to_bars(mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_MN1, 0, 120),
                                 normalize_timestamp=normalize_timestamp, timeframe_seconds=_tf_seconds(mt5, mt5.TIMEFRAME_MN1), cutoff_at_utc=cutoff)
        for name, values in {**bars, "W1": weekly, "MN1": monthly}.items():
            if len(values) < 2:
                raise MT5ReadError(f"Historico insuficiente para {symbol} {name} no cutoff.")
        levels = build_context_levels(bars["D1"], weekly, monthly)
        zones = {name: build_active_zones(bars[name], name) for name in ("M1", "M5", "M15", "D1")}
        last_bar = bars["M1"][-1] if bars["M1"] else None
        last_price = float(last_bar["close"]) if last_bar else None
        proxy = _CausalRatesProxy(mt5, symbol, cutoff, normalize_timestamp)
        macro_timeframes = {name: timeframe for name, (timeframe, _) in frames.items()}
        macro_timeframes.update({"M30": mt5.TIMEFRAME_M30, "H1": mt5.TIMEFRAME_H1, "H4": mt5.TIMEFRAME_H4})
        macro_frames = {name: build_macro(proxy, symbol, timeframe, as_of=cutoff) for name, timeframe in macro_timeframes.items()}
        macro_frames["W1"] = build_macro(proxy, symbol, mt5.TIMEFRAME_W1, as_of=cutoff)
        macro_frames["MN1"] = build_macro(proxy, symbol, mt5.TIMEFRAME_MN1, as_of=cutoff)
        macro = macro_frames["M15"]
        macro["frames"] = macro_frames
        return MarketSnapshot(symbol=symbol, as_of=cutoff, last_price=last_price, connected=True,
            source="MT5 causal", bars=bars, levels=levels, zones=zones,
            events=[PO3Event(cutoff, "Leitura congelada", "Somente dados conhecidos no cutoff.")],
            notes=["Snapshot causal; sem tick posterior ao cutoff."], account={}, macro=macro)
    finally:
        mt5.shutdown()


def read_snapshot(terminal_path: str, symbol: str) -> MarketSnapshot:
    """Le candles e cotacao. Nao expoe nenhuma operacao de negociacao."""
    mt5 = _load_package()
    terminal = Path(terminal_path)
    if not terminal.is_file():
        raise MT5ReadError(f"Terminal nao encontrado: {terminal}")

    if not mt5.initialize(str(terminal), timeout=8_000):
        raise MT5ReadError(f"Falha ao conectar ao MT5: {mt5.last_error()}")

    try:
        terminal_info = mt5.terminal_info()
        if terminal_info is None or not bool(terminal_info.connected):
            raise MT5ReadError("MT5 aberto, mas sem conexao com o servidor.")

        account_info = mt5.account_info()
        account = {}
        if account_info is not None:
            for name in ("balance", "equity", "margin", "margin_free", "margin_level"):
                value = getattr(account_info, name, None)
                if value is not None:
                    account[name] = float(value)

        frames = {
            "M15": (mt5.TIMEFRAME_M15, 160),
            "M5": (mt5.TIMEFRAME_M5, 220),
            "M1": (mt5.TIMEFRAME_M1, 300),
            "D1": (mt5.TIMEFRAME_D1, 120),
        }
        bars: dict[str, list[dict]] = {}
        for name, (timeframe, count) in frames.items():
            bars[name] = _rates_to_bars(mt5.copy_rates_from_pos(symbol, timeframe, 0, count))
            if len(bars[name]) < 2:
                raise MT5ReadError(f"Historico insuficiente para {symbol} {name}.")

        weekly = _rates_to_bars(mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_W1, 0, 120))
        monthly = _rates_to_bars(mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_MN1, 0, 120))
        daily = bars["D1"]
        levels = build_context_levels(daily, weekly, monthly)
        zones = {"M15": build_daily_zones(daily)}

        tick = mt5.symbol_info_tick(symbol)
        last_price = float(tick.last) if tick is not None and tick.last > 0 else float(bars["M1"][-1]["close"])
        now = datetime.now(SAO_PAULO)
        version = mt5.version()
        source = f"MT5 local {version[0] if version else ''}".strip()
        macro_timeframes = {
            **{name: timeframe for name, (timeframe, _) in frames.items()},
            "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
        }
        macro_frames = {name: build_macro(mt5, symbol, timeframe) for name, timeframe in macro_timeframes.items()}
        macro_frames["W1"] = build_macro(mt5, symbol, mt5.TIMEFRAME_W1)
        macro_frames["MN1"] = build_macro(mt5, symbol, mt5.TIMEFRAME_MN1)
        macro = macro_frames["M15"]
        macro["frames"] = macro_frames
        return MarketSnapshot(
            symbol=symbol,
            as_of=now,
            last_price=last_price,
            connected=True,
            source=source,
            bars=bars,
            levels=levels,
            events=[PO3Event(now, "Leitura atualizada", "Candles D1, M15, M5 e M1 recebidos do MT5 local.")],
            zones=zones,
            notes=["Conexao somente leitura; credenciais nao sao solicitadas pelo painel."],
            account=account,
            macro=macro,
        )
    finally:
        mt5.shutdown()
