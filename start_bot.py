"""Single-entry orchestrator for the Zerodha trading bot.

Generates a fresh access token, then starts the trading loop.
Run once daily before market open (cron / systemd timer handles this at 9 AM IST).

Handles SIGTERM/SIGINT for graceful shutdown under systemd supervision.

Usage:
    python start_bot.py
"""

from __future__ import annotations

import signal
import sys

from loguru import logger

logger.remove()
logger.add(sys.stderr, level="INFO")
logger.add("trading_bot.log", rotation="10 MB", level="DEBUG")

# ── Graceful shutdown flag ──────────────────────────────────────────────

_shutdown = False


def _handle_sigterm(signum: int, _frame) -> None:
    global _shutdown
    if _shutdown:
        return  # already shutting down
    _shutdown = True
    sig_name = signal.Signals(signum).name
    logger.warning("Received {} — shutting down gracefully", sig_name)


signal.signal(signal.SIGTERM, _handle_sigterm)
signal.signal(signal.SIGINT, _handle_sigterm)


def main() -> None:
    logger.info("=== Trading bot startup ===")

    # ── Step 1: Generate fresh access token ─────────────────────────────
    logger.info("Generating Kite access token...")
    try:
        from generate_token import main as generate_token

        generate_token()
    except SystemExit as exc:
        if exc.code != 0:
            logger.error("Token generation failed — aborting startup")
            sys.exit(1)
    except Exception:
        logger.exception("Token generation failed — aborting startup")
        sys.exit(1)

    # ── Check for shutdown signal (e.g. systemd stop during token gen) ──
    if _shutdown:
        logger.info("Shutdown requested — skipping trading loop")
        return

    # ── Step 2: Start trading loop ──────────────────────────────────────
    logger.info("Token ready — starting trading loop")
    try:
        from trading_bot.main import main as trading_loop

        trading_loop()
    except Exception:
        logger.exception("Trading loop crashed")
        sys.exit(1)


if __name__ == "__main__":
    main()
