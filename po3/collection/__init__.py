"""Coleta M1 fechada, independente da interface Streamlit."""
from .mt5_m1_collector import CollectorConfig, collect_once, closed_m1_bars
__all__ = ["CollectorConfig", "collect_once", "closed_m1_bars"]
