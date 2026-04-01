#!/usr/bin/env python3
"""
Dialectic — Entry point

Run with: python run.py

Set PRODUCTION=1 for production mode (disables reload, uses multiple workers).
"""

import os
import uvicorn

# WHY: Load .env before anything else so DATABASE_URL, JWT_SECRET_KEY, etc.
# are available to all modules at import time. Shell-level env vars take
# precedence over .env (dotenv default), so ANTHROPIC_API_KEY set in the
# shell doesn't need to be duplicated in the file.
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"), override=False)
except ImportError:
    pass  # python-dotenv not installed; fall back to shell environment

if __name__ == "__main__":
    is_production = os.environ.get("PRODUCTION", "").lower() in ("1", "true", "yes")
    workers = int(os.environ.get("WEB_CONCURRENCY", "1"))

    port = int(os.environ.get("PORT", "8002"))

    if is_production:
        uvicorn.run(
            "api.main:app",
            host="0.0.0.0",
            port=port,
            reload=False,
            workers=workers if workers > 1 else 2,
            log_level="warning",
            access_log=True,
        )
    else:
        uvicorn.run(
            "api.main:app",
            host="0.0.0.0",
            port=port,
            reload=True,
            log_level="info",
        )
