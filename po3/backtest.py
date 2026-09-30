from __future__ import annotations
import pandas as pd

def _zones(df: pd.DataFrame, min_body_factor: float = 1.5):
    zones = []
    typical = (df.close - df.open).abs().mean()
    for i in range(2, len(df)-1):
        a, c = df.iloc[i-2], df.iloc[i]
        if c.low > a.high: zones.append((c.time, "COMPRA", "FVG", float(a.high), float(c.low)))
        elif c.high < a.low: zones.append((c.time, "VENDA", "FVG", float(c.high), float(a.low)))
    for i in range(len(df)-2):
        base, impulse = df.iloc[i], df.iloc[i+1]
        if abs(impulse.close-impulse.open) >= max(abs(base.close-base.open)*min_body_factor, typical*min_body_factor):
            direction = "COMPRA" if impulse.close > impulse.open else "VENDA"
            opposite = (direction == "COMPRA" and base.close < base.open) or (direction == "VENDA" and base.close > base.open)
            if opposite: zones.append((base.time, direction, "OB", float(base.low), float(base.high)))
    return zones

def run_confluence(m5: pd.DataFrame, m1: pd.DataFrame, rr: float = 2.0) -> dict:
    m5, m1 = m5.sort_values("time").reset_index(drop=True), m1.sort_values("time").reset_index(drop=True)
    zones5, zones1 = _zones(m5), _zones(m1)
    # Uma região do M5 não pode gerar várias entradas sobrepostas.
    filtered = []
    for zone in sorted(zones5, key=lambda z: z[0]):
        if any(zone[1] == old[1] and zone[3] <= old[4] and zone[4] >= old[3] for old in filtered):
            continue
        filtered.append(zone)
    zones5 = filtered
    trades = []
    used_entries = set()
    blocked_until = -1
    for t, direction, kind, low, high in zones5:
        confirmations = [z for z in zones1 if z[0] > t and z[1] == direction and z[3] <= high and z[4] >= low]
        if not confirmations: continue
        confirm = confirmations[0]; entry_i = m1.index[m1.time > confirm[0]]
        if len(entry_i) == 0: continue
        entry_i = int(entry_i[0]); entry = float(m1.iloc[entry_i].open)
        if entry_i in used_entries or entry_i <= blocked_until:
            continue
        used_entries.add(entry_i)
        risk = max(entry-low, high-entry) if direction == "COMPRA" else max(high-entry, entry-low)
        if risk <= 0: continue
        stop = low - 1 if direction == "COMPRA" else high + 1
        target = entry + rr*abs(entry-stop) if direction == "COMPRA" else entry - rr*abs(entry-stop)
        result = None
        exit_i = None
        for j, (_, bar) in enumerate(m1.iloc[entry_i+1:entry_i+301].iterrows(), start=entry_i+1):
            if direction == "COMPRA":
                if bar.low <= stop: result = -1; exit_i = j; break
                if bar.high >= target: result = rr; exit_i = j; break
            else:
                if bar.high >= stop: result = -1; exit_i = j; break
                if bar.low <= target: result = rr; exit_i = j; break
        if result is not None: trades.append(result)
        if exit_i is not None:
            blocked_until = exit_i
    wins = sum(x > 0 for x in trades)
    return {"trades": len(trades), "wins": wins, "losses": len(trades)-wins, "win_rate": wins/len(trades) if trades else None, "r_net": sum(trades)}
