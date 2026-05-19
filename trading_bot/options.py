"""Option instrument cache and ATM strike selection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

import pytz

_IST = pytz.timezone("Asia/Kolkata")

# Strikes are on Thursday; public holidays shift to Wednesday/Friday
_EXPIRY_WEEKDAY = 3  # Thursday


@dataclass(frozen=True)
class OptionContract:
    """A single NFO option contract."""

    instrument_token: int
    trading_symbol: str
    name: str  # "NIFTY" or "BANKNIFTY"
    expiry: datetime
    strike: float
    option_type: str  # "CE" or "PE"
    lot_size: int
    exchange: str = "NFO"


class InstrumentCache:
    """In-memory cache of NFO option contracts, loaded once at startup."""

    def __init__(self) -> None:
        self._contracts: list[OptionContract] = []
        self._by_token: dict[int, OptionContract] = {}
        self._loaded = False

    @property
    def loaded(self) -> bool:
        return self._loaded

    def load(self, kite_instruments: list[dict[str, Any]]) -> None:
        """Parse the output of kite.instruments('NFO')."""
        contracts: list[OptionContract] = []

        for row in kite_instruments:
            name = row.get("name", "")
            if name not in ("NIFTY", "BANKNIFTY"):
                continue

            inst_type = row.get("instrument_type", "")
            if inst_type not in ("CE", "PE"):
                continue

            expiry_raw = row.get("expiry")
            if expiry_raw is None:
                continue

            # Safe expiry handling for string / datetime / date
            if isinstance(expiry_raw, str):
                expiry = datetime.fromisoformat(expiry_raw)
            elif isinstance(expiry_raw, datetime):
                expiry = expiry_raw
            elif isinstance(expiry_raw, date):
                expiry = datetime.combine(expiry_raw, time(0, 0))
            else:
                continue

            if expiry.tzinfo is None:
                expiry = _IST.localize(expiry)

            contract = OptionContract(
                instrument_token=int(row["instrument_token"]),
                trading_symbol=str(row["tradingsymbol"]),
                name=name,
                expiry=expiry,
                strike=float(row["strike"]),
                option_type=inst_type,
                lot_size=int(row["lot_size"]),
            )

            contracts.append(contract)
            self._by_token[contract.instrument_token] = contract

        self._contracts = contracts
        self._loaded = True

    def get_all(self) -> list[OptionContract]:
        return list(self._contracts)

    def by_token(self, token: int) -> OptionContract | None:
        return self._by_token.get(token)

    def filter(
        self,
        index: str,
        option_type: str | None = None,
        expiry: datetime | None = None,
    ) -> list[OptionContract]:
        """Filter cached contracts by index name, optionally by type and expiry."""
        result = [c for c in self._contracts if c.name == index]

        if option_type:
            result = [c for c in result if c.option_type == option_type]

        if expiry:
            result = [c for c in result if c.expiry.date() == expiry.date()]

        return result


def get_weekly_expiry(reference_date: datetime | None = None) -> datetime:
    """Return the nearest weekly expiry (Thursday)."""
    if reference_date is None:
        reference_date = datetime.now(_IST)

    today = reference_date
    days_ahead = _EXPIRY_WEEKDAY - today.weekday()

    if days_ahead < 0 or (days_ahead == 0 and today.hour >= 15):
        days_ahead += 7

    expiry = today + timedelta(days=days_ahead)

    return expiry.replace(hour=15, minute=30, second=0, microsecond=0)


def get_atm_strike(underlying_price: float, index: str, config) -> float:
    """Round underlying price to nearest ATM strike."""
    interval = (
        config.nifty_strike_interval
        if index == "NIFTY"
        else config.banknifty_strike_interval
    )
    return round(underlying_price / interval) * interval


def select_option(
    cache: InstrumentCache,
    index: str,
    option_type: str,  # "CE" or "PE"
    underlying_price: float,
    config,
) -> OptionContract | None:
    """Select the ATM option contract for the given index and type."""
    if underlying_price <= 0:
        return None

    expiry = get_weekly_expiry()
    strike = get_atm_strike(underlying_price, index, config)

    candidates = cache.filter(index, option_type, expiry)

    # Try ATM first, then ATM-1, then ATM+1
    for offset in (0, -1, 1):
        target = strike + offset * (
            config.nifty_strike_interval
            if index == "NIFTY"
            else config.banknifty_strike_interval
        )

        for c in candidates:
            if abs(c.strike - target) < 0.01:
                return c

    return None


def get_lot_size(index: str, config) -> int:
    """Return lot size for the given index."""
    return config.nifty_lot_size if index == "NIFTY" else config.banknifty_lot_size


def get_underlying_symbol(index: str) -> str:
    """Return the Kite ticker symbol for the underlying index."""
    if index == "NIFTY":
        return "NSE:NIFTY 50"
    return "NSE:NIFTY BANK"


__all__ = [
    "InstrumentCache",
    "OptionContract",
    "get_atm_strike",
    "get_lot_size",
    "get_underlying_symbol",
    "get_weekly_expiry",
    "select_option",
]
