"""
log.py — minimal structured logging to stdout.

Container-friendly: one stdout handler, timestamp + level + logger name. Level
comes from SCREENER_LOG_LEVEL / LOG_LEVEL (default INFO). Call setup() once at
process start (run.py, server). Operational/warn/error paths use this; module
loggers are obtained with logging.getLogger("<name>").

Stage progress still uses print() — it goes to stdout and is captured by the
platform; converting every line buys little and adds churn.
"""
import logging
import sys

_CONFIGURED = False


def setup(level: str = "INFO") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-5s %(name)s: %(message)s", "%H:%M:%S"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    _CONFIGURED = True
