from __future__ import annotations
import logging

LOGGER = logging.getLogger("po3.decision_engine")
def configure_logging():
    if not LOGGER.handlers:
        handler=logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        LOGGER.addHandler(handler)
        LOGGER.setLevel(logging.INFO)