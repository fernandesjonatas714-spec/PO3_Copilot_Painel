"""Feature flags da camada V2; coleta factual ativa e decisão automática bloqueada."""
from __future__ import annotations
import os

def _enabled(name: str, default: bool = False) -> bool:
    return os.getenv(name, "true" if default else "false").strip().lower() in {"1", "true", "sim", "yes"}

try:
    OFFICIAL_ANALYSIS_MAX_SECONDS = max(1.0, float(os.getenv("OFFICIAL_ANALYSIS_MAX_SECONDS", "120")))
except ValueError:
    OFFICIAL_ANALYSIS_MAX_SECONDS = 120.0

AUTO_DATA_COLLECTION = _enabled("AUTO_DATA_COLLECTION", True)
MARKET_STATE_SNAPSHOT_ENABLED = _enabled("MARKET_STATE_SNAPSHOT_ENABLED", True)
OUTCOME_TRACKING_ENABLED = _enabled("OUTCOME_TRACKING_ENABLED", True)
EVALUATION_ENGINE_ENABLED = _enabled("EVALUATION_ENGINE_ENABLED", True)
CALIBRATION_ENABLED = _enabled("CALIBRATION_ENABLED", False)
AUTO_DECISION_ENGINE = _enabled("AUTO_DECISION_ENGINE", False)
MODEL_BENCHMARK_ENABLED = _enabled("MODEL_BENCHMARK_ENABLED", False)
CALIBRATED_CONFIDENCE_UI_ENABLED = _enabled("CALIBRATED_CONFIDENCE_UI_ENABLED", False)
REPLAY_ENABLED = _enabled("REPLAY_ENABLED", False)
SHADOW_MODE_ENABLED = _enabled("SHADOW_MODE_ENABLED", False)
JEV_SHADOW_ENABLED = _enabled("JEV_SHADOW_ENABLED", False)
SUPERVISOR_AI_ENABLED = _enabled("SUPERVISOR_AI_ENABLED", False)

def flags() -> dict:
    from po3.ai_analysis_window import window_config
    ai_window = window_config()
    return {
        "AUTO_DATA_COLLECTION": AUTO_DATA_COLLECTION,
        "MARKET_STATE_SNAPSHOT_ENABLED": MARKET_STATE_SNAPSHOT_ENABLED,
        "OUTCOME_TRACKING_ENABLED": OUTCOME_TRACKING_ENABLED,
        "EVALUATION_ENGINE_ENABLED": EVALUATION_ENGINE_ENABLED,
        "CALIBRATION_ENABLED": CALIBRATION_ENABLED,
        "AUTO_DECISION_ENGINE": AUTO_DECISION_ENGINE,
        "MODEL_BENCHMARK_ENABLED": MODEL_BENCHMARK_ENABLED,
        "CALIBRATED_CONFIDENCE_UI_ENABLED": CALIBRATED_CONFIDENCE_UI_ENABLED,
        "REPLAY_ENABLED": REPLAY_ENABLED,
        "SHADOW_MODE_ENABLED": SHADOW_MODE_ENABLED,
        "JEV_SHADOW_ENABLED": JEV_SHADOW_ENABLED,
        "SUPERVISOR_AI_ENABLED": SUPERVISOR_AI_ENABLED,
        "OFFICIAL_ANALYSIS_MAX_SECONDS": OFFICIAL_ANALYSIS_MAX_SECONDS,
        "AI_ANALYSIS_WINDOW_ENABLED": ai_window["enabled"],
        "AI_ANALYSIS_START": ai_window["start_text"],
        "AI_ANALYSIS_END": ai_window["end_text"],
        "AI_ANALYSIS_TIMEZONE": ai_window["timezone"],
    }
