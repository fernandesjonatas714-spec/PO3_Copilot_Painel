"""Feature flags da camada V2; todos conservadores por padrão."""
from __future__ import annotations
import os
def _enabled(name:str, default:bool=False)->bool:
    return os.getenv(name, "true" if default else "false").strip().lower() in {"1","true","sim","yes"}
AUTO_DATA_COLLECTION = _enabled("AUTO_DATA_COLLECTION", False)
AUTO_DECISION_ENGINE = _enabled("AUTO_DECISION_ENGINE", False)
REPLAY_ENABLED = _enabled("REPLAY_ENABLED", False)
def flags()->dict:
    return {"AUTO_DATA_COLLECTION":AUTO_DATA_COLLECTION,"AUTO_DECISION_ENGINE":AUTO_DECISION_ENGINE,"REPLAY_ENABLED":REPLAY_ENABLED}
