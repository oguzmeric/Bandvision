"""`python -m bantvision.analyzer [--host 0.0.0.0] [--port 8090]`"""
from __future__ import annotations

import argparse

import uvicorn

from .app import create_app


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m bantvision.analyzer", description="BantVision video analiz sunucusu")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8090)
    a = ap.parse_args()
    uvicorn.run(create_app(), host=a.host, port=a.port)


if __name__ == "__main__":
    main()
