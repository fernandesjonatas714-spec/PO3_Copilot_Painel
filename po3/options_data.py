"""Leitura segura de uma cadeia de opções a partir de CSV local."""
from __future__ import annotations

from pathlib import Path
from datetime import date, timedelta
from urllib.request import urlopen
import pandas as pd

REQUIRED = {"expiry", "strike", "type", "last", "volume"}

def load_options_csv(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame.columns = [str(c).strip().lower() for c in frame.columns]
    missing = REQUIRED - set(frame.columns)
    if missing:
        raise ValueError("CSV de opções sem colunas: " + ", ".join(sorted(missing)))
    frame["type"] = frame["type"].astype(str).str.upper().str[0].map({"C": "Call", "P": "Put"}).fillna(frame["type"])
    for col in ["strike", "last", "volume"]:
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame["expiry"] = pd.to_datetime(frame["expiry"], errors="coerce")
    return frame.dropna(subset=["expiry", "strike"]).copy()

def find_latest_csv(folder: str | Path) -> Path | None:
    files = sorted(Path(folder).glob("*.csv"), key=lambda item: item.stat().st_mtime, reverse=True)
    return files[0] if files else None

def auto_download_b3(folder: str | Path, days: int = 7) -> Path | None:
    """Tenta obter CSV diário público da B3; ignora respostas que não sejam cadeia válida."""
    target = Path(folder)
    target.mkdir(parents=True, exist_ok=True)
    for offset in range(days):
        day = date.today() - timedelta(days=offset)
        stamp = day.strftime("%Y%m%d")
        iso = day.isoformat()
        for name in (f"BDI_02_{stamp}.csv", f"BDI_{stamp}.csv"):
            url = f"https://arquivos.b3.com.br/bdi/download/bdi/{iso}/{name}"
            try:
                with urlopen(url, timeout=8) as response:
                    raw = response.read()
                frame = pd.read_csv(__import__("io").BytesIO(raw), sep=None, engine="python")
                frame.columns = [str(c).strip().lower() for c in frame.columns]
                if REQUIRED.issubset(frame.columns):
                    path = target / f"b3_{stamp}.csv"
                    frame.to_csv(path, index=False)
                    return path
            except Exception:
                continue
    return find_latest_csv(target)

def option_summary(frame: pd.DataFrame) -> dict[str, object]:
    if frame.empty:
        return {"put_call": None, "call_strike": None, "put_strike": None, "levels": pd.DataFrame()}
    grouped = frame.groupby(["strike", "type"], as_index=False)[["volume"]].sum()
    levels = grouped.sort_values(["volume"], ascending=False).head(12)
    call_peak = levels.loc[levels["type"] == "Call", "strike"].iloc[0] if (levels["type"] == "Call").any() else None
    put_peak = levels.loc[levels["type"] == "Put", "strike"].iloc[0] if (levels["type"] == "Put").any() else None
    return {"call_strike": call_peak, "put_strike": put_peak, "levels": levels}
