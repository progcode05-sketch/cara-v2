from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
PACKAGE_DIR = BASE_DIR / ".packages"

if str(PACKAGE_DIR) not in sys.path:
    sys.path.insert(0, str(PACKAGE_DIR))

import uvicorn


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the local Noxlin dashboard.")
    parser.add_argument("--host", default="localhost", help="Host to bind to.")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("NOXLIN_PORT", "3002")),
        help="Port to bind to. Defaults to NOXLIN_PORT or 3002.",
    )
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload on code changes.")
    args = parser.parse_args()

    base_url = f"http://{args.host}:{args.port}"
    os.environ["NOXLIN_APP_BASE_URL"] = base_url
    os.environ["LINKEDIN_REDIRECT_URI"] = f"{base_url}/auth/linkedin/callback"

    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)
