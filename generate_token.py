"""Generate a Zerodha Kite Connect access token via the Kite API.

No browser automation needed — uses the same JSON endpoints the login page calls.

Usage:
    uv run python generate_token.py

Requires these in .env or credentials.env:
    KITE_USER_ID, KITE_PASSWORD, KITE_TOTP_SECRET, KITE_API_KEY, KITE_API_SECRET

Dependencies: pip install requests pyotp kiteconnect python-dotenv loguru
"""

from __future__ import annotations

import os
import sys
from urllib.parse import parse_qs, urlparse

from loguru import logger


def _load_dotenv() -> None:
    """Load credentials.env then .env so env vars are available."""
    try:
        import dotenv

        dotenv.load_dotenv("credentials.env")
        dotenv.load_dotenv(".env", override=False)
    except ImportError:
        pass


_ENV_KEYS = (
    "KITE_USER_ID",
    "KITE_PASSWORD",
    "KITE_TOTP_SECRET",
    "KITE_API_KEY",
    "KITE_API_SECRET",
)


def load_credentials() -> dict[str, str]:
    """Read all required credentials from environment / dotenv files."""
    _load_dotenv()

    creds = {}
    missing: list[str] = []

    for key in _ENV_KEYS:
        val = os.environ.get(key, "").strip()
        if not val:
            missing.append(key)
        creds[key] = val

    if missing:
        logger.error("Missing credential(s): {}", ", ".join(missing))
        sys.exit(1)

    return creds


def get_request_token(
    user_id: str,
    password: str,
    totp_secret: str,
    api_key: str,
) -> str:
    """Log in to Kite, complete 2FA, and extract the ``request_token``.

    Uses the same JSON API endpoints that the Kite web login page calls,
    so no browser or local redirect server is required.
    """
    import pyotp
    import requests

    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0"

    # ── Step 1: Password login ──────────────────────────────────────────
    login_resp = session.post(
        "https://kite.zerodha.com/api/login",
        data={"user_id": user_id, "password": password},
    )
    login_data = login_resp.json()

    if login_data.get("status") != "success":
        msg = login_data.get("message", "unknown error")
        raise RuntimeError(f"Login failed: {msg}")

    request_id: str = login_data["data"]["request_id"]
    logger.info("Password login OK")

    # ── Step 2: TOTP ────────────────────────────────────────────────────
    totp_code = pyotp.TOTP(totp_secret).now()
    twofa_resp = session.post(
        "https://kite.zerodha.com/api/twofa",
        data={
            "user_id": user_id,
            "request_id": request_id,
            "twofa_value": totp_code,
        },
    )
    twofa_data = twofa_resp.json()

    if twofa_data.get("status") != "success":
        msg = twofa_data.get("message", "unknown error")
        raise RuntimeError(f"TOTP failed: {msg}")

    logger.info("TOTP OK")

    # ── Step 3: Get request_token via OAuth redirect ────────────────────
    # Hit kite.trade which redirects through kite.zerodha.com. Since our
    # session is already authenticated, the final 302 will carry the
    # request_token to the app's registered redirect URI (127.0.0.1:8000).
    # We DON'T follow that final hop — we extract the token from its URL.
    connect_url = f"https://kite.trade/connect/login?api_key={api_key}&v=3"

    # Manually follow redirects up to 5 hops. Stop before attempting to
    # connect to the app's local redirect URI (127.0.0.1:8000).
    _LOCAL_HOSTS = {"127.0.0.1", "localhost"}
    MAX_HOPS = 5
    url: str = connect_url
    last_location: str | None = None

    for _ in range(MAX_HOPS):
        resp = session.get(url, allow_redirects=False)
        resp.raise_for_status()
        last_location = resp.headers.get("Location")
        if last_location is None:
            break
        # If the next hop targets localhost, the request_token is already
        # in the URL — extract it without connecting.
        host = urlparse(last_location).hostname or ""
        if host in _LOCAL_HOSTS:
            break
        url = last_location

    if not last_location:
        raise RuntimeError(
            f"Redirect chain ended without Location header (final status={resp.status_code})"
        )

    parsed = urlparse(last_location)
    token = parse_qs(parsed.query).get("request_token")
    if not token:
        raise RuntimeError(f"No request_token in redirect Location: {last_location}")

    logger.info("request_token obtained")
    return token[0]


def exchange_token(api_key: str, api_secret: str, request_token: str) -> str:
    """Exchange a ``request_token`` for an ``access_token`` via KiteConnect."""
    from kiteconnect import KiteConnect

    kite = KiteConnect(api_key=api_key)
    session = kite.generate_session(request_token, api_secret=api_secret)

    access_token: str | None = session.get("access_token")
    if not access_token:
        raise RuntimeError("No access_token in session response")

    logger.info("Access token obtained ({} chars)", len(access_token))
    return access_token


def update_env_file(access_token: str) -> None:
    """Write ``TB_KITE_ACCESS_TOKEN`` into ``.env``."""
    from dotenv import set_key

    set_key(".env", "TB_KITE_ACCESS_TOKEN", access_token, quote_mode="always")
    logger.info("TB_KITE_ACCESS_TOKEN written to .env")


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level="INFO")

    creds = load_credentials()

    try:
        request_token = get_request_token(
            user_id=creds["KITE_USER_ID"],
            password=creds["KITE_PASSWORD"],
            totp_secret=creds["KITE_TOTP_SECRET"],
            api_key=creds["KITE_API_KEY"],
        )

        access_token = exchange_token(
            api_key=creds["KITE_API_KEY"],
            api_secret=creds["KITE_API_SECRET"],
            request_token=request_token,
        )

        update_env_file(access_token)
        logger.info("Token generation completed successfully.")

    except Exception:
        logger.exception("Token generation failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
