"""
asgi.py — production ASGI entrypoint (import target for uvicorn/gunicorn).

    uvicorn server.asgi:app --host 0.0.0.0 --port 8000 --workers 2

Reads the data dir + log level from the environment (see .env.example). For
local dev, `python run.py serve` is the simpler path.
"""
from pipeline.config import runtime
from pipeline.log import setup
from server.app import create_app

setup(runtime.log_level)
app = create_app(runtime.data_dir)
