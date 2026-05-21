"""Execution engine — paper/live mode separation with dedup and full logging.

The execution engine sits between the validation layer and the broker.
It guarantees:
  - Paper mode: zero real-money risk, simulated fills with slippage
  - Live mode: real orders via KiteConnect, full audit trail
  - Dedup: every order has a unique dedup_key; re-submission is rejected
  - Complete audit: every order request + broker response is stored before/after
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger

from ops_api.config import OpsApiConfig
from ops_api.db import DatabaseManager
from ops_api.position_manager import PositionManager

_UTC_STR = "%Y-%m-%dT%H:%M:%S.%fZ"


def _utcnow() -> str:
    return datetime.utcnow().isoformat()


def _generate_id() -> str:
    import uuid

    return str(uuid.uuid4())


def _compute_dedup_key(signal_id: str, symbol: str, side: str) -> str:
    """Stable dedup key: signal + symbol + side."""
    return f"{signal_id}:{symbol}:{side}"


class PaperBroker:
    """Simulated broker for paper trading."""

    def __init__(self, config: OpsApiConfig) -> None:
        self.config = config
        self._counter = 0

    def place_order(
        self,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        order_type: str = "LIMIT",
        strategy: str = "",
    ) -> dict[str, Any]:
        self._counter += 1
        order_id = f"PAPER_{self._counter:06d}"

        slippage = 3.0
        fill_price = price + slippage if side == "BUY" else price - slippage

        logger.info(
            "[PAPER] {} {} x{} @ {} (order_id={})",
            side,
            symbol,
            quantity,
            fill_price,
            order_id,
        )

        return {
            "external_order_id": order_id,
            "filled_price": fill_price,
            "filled_quantity": quantity,
            "status": "filled",
            "broker_response": {
                "mode": "paper",
                "slippage": slippage,
            },
            "error_message": "",
        }


class ExecutionEngine:
    """Orchestrates order execution with full audit trail.

    Args:
        config: Ops API configuration.
        db: Database manager for persistence.
        kite_client: Optional real KiteClient instance for live mode.
    """

    def __init__(
        self,
        config: OpsApiConfig,
        db: DatabaseManager,
        kite_client: Any = None,
        position_manager: PositionManager | None = None,
    ) -> None:
        self.config = config
        self.db = db
        self.kite = kite_client
        self.paper = PaperBroker(config)
        self._position_manager = position_manager

    def execute(
        self,
        signal: dict[str, Any],
        validation: dict[str, Any],
        mode: str = "paper",
    ) -> dict[str, Any]:
        """Execute a validated signal.

        Args:
            signal: NormalizedSignal as dict.
            validation: ValidationResult as dict (must have passed=True).
            mode: ``"paper"`` or ``"live"``.

        Returns:
            Dict with execution result details.
        """
        # ── Guard: cannot execute unvalidated signals ────────────────
        if not validation.get("passed", False):
            return {
                "status": "rejected",
                "error": "Cannot execute unvalidated signal",
            }

        symbol = signal.get("symbol", "")
        side = signal.get("side", "BUY")
        price = signal.get("price", 0.0)
        strategy = signal.get("strategy", "")
        quantity = self._resolve_quantity(symbol)

        dedup_key = _compute_dedup_key(signal.get("id", ""), symbol, side)

        # ── Dedup check ──────────────────────────────────────────────
        existing = self.db.get_order_by_dedup_key(dedup_key)
        if existing:
            logger.warning(
                "Dedup hit for dedup_key={} — order already exists (id={})",
                dedup_key,
                existing["id"],
            )
            return {
                "status": "duplicate",
                "order_id": existing["id"],
                "external_order_id": existing.get("external_order_id"),
                "error": "Order already submitted",
            }

        # ── Create order record ──────────────────────────────────────
        order_uuid = _generate_id()
        order = {
            "id": order_uuid,
            "signal_id": signal.get("id", ""),
            "validation_id": validation.get("id", ""),
            "mode": mode,
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "price": price,
            "order_type": "LIMIT",
            "status": "pending",
            "external_order_id": None,
            "strategy": strategy,
            "dedup_key": dedup_key,
            "data_source": "production",
            "error_message": "",
            "created_at": _utcnow(),
            "updated_at": None,
            "session_id": signal.get("session_id", ""),
        }
        self.db.insert_order(order)

        logger.info(
            "Executing {} order: {} {} x{} @ {} (dedup_key={})",
            mode.upper(),
            side,
            symbol,
            quantity,
            price,
            dedup_key,
        )

        # ── Execute via appropriate broker ───────────────────────────
        try:
            if mode == "live" and self.kite is not None:
                result = self._execute_live(
                    symbol, side, quantity, price, order_type="LIMIT", strategy=strategy
                )
            else:
                result = self.paper.place_order(
                    symbol, side, quantity, price, strategy=strategy
                )

            # ── Update order with result ─────────────────────────────
            updates: dict[str, Any] = {
                "status": result.get("status", "rejected"),
                "external_order_id": result.get("external_order_id"),
                "error_message": result.get("error_message", ""),
            }
            self.db.update_order(order_uuid, updates)

            # Position lifecycle mutation (Phase 4)
            if self._position_manager is not None and result.get("status") == "filled":
                try:
                    mutation = self._position_manager.open_or_adjust(
                        symbol=result.get("symbol", signal.get("symbol", "")),
                        side=result.get("side", signal.get("side", "")),
                        quantity=result.get("filled_quantity", signal.get("quantity", 0)),
                        price=result.get("filled_price", signal.get("price", 0.0)),
                        strategy_id=signal.get("strategy", ""),
                    )
                    result["position_mutation"] = {
                        "action": mutation.action,
                        "realized_pnl_delta": mutation.realized_pnl_delta,
                    }
                except Exception:
                    logger.exception("Position mutation failed after fill for {}", signal.get("symbol"))

            logger.info(
                "Order {}: status={} external_id={}",
                order_uuid,
                updates["status"],
                updates.get("external_order_id"),
            )

            return {
                "status": updates["status"],
                "order_id": order_uuid,
                "external_order_id": updates["external_order_id"],
                "filled_price": result.get("filled_price", price),
                "filled_quantity": result.get("filled_quantity", quantity),
                "error": result.get("error_message", ""),
            }

        except Exception as e:
            error_msg = str(e)
            logger.exception("Order execution failed for order_id={}", order_uuid)

            self.db.update_order(
                order_uuid,
                {
                    "status": "failed",
                    "error_message": error_msg,
                    "external_order_id": None,
                },
            )

            return {
                "status": "failed",
                "order_id": order_uuid,
                "external_order_id": None,
                "error": error_msg,
            }

    def _execute_live(
        self,
        symbol: str,
        side: str,
        quantity: int,
        price: float,
        order_type: str = "LIMIT",
        strategy: str = "",
    ) -> dict[str, Any]:
        """Execute a real order via KiteConnect."""
        if self.kite is None:
            return {
                "status": "failed",
                "error_message": "Kite client not available",
                "filled_price": 0.0,
                "filled_quantity": 0,
                "external_order_id": None,
                "broker_response": {},
            }

        transaction_type = "BUY" if side == "BUY" else "SELL"

        try:
            order_id = self.kite.place_order(
                exchange="NFO",
                tradingsymbol=symbol,
                transaction_type=transaction_type,
                quantity=quantity,
                price=price,
                order_type=order_type,
                product="MIS",
                variety="regular",
                tag=strategy,
            )

            logger.info(
                "[LIVE] Order placed: {} {} x{} @ {} order_id={}",
                transaction_type,
                symbol,
                quantity,
                price,
                order_id,
            )

            return {
                "status": "submitted",
                "external_order_id": str(order_id),
                "filled_price": price,
                "filled_quantity": 0,
                "error_message": "",
                "broker_response": {"order_id": str(order_id)},
            }

        except Exception as e:
            logger.exception(
                "[LIVE] Order failed for {} {} x{}", side, symbol, quantity
            )
            return {
                "status": "failed",
                "external_order_id": None,
                "filled_price": 0.0,
                "filled_quantity": 0,
                "error_message": str(e),
                "broker_response": {},
            }

    def flatten(self) -> dict[str, Any]:
        """Close all open positions (emergency flatten).

        Currently synthetic paper-mode lifecycle closure.
        Future live flatten must route through broker execution.
        """
        logger.warning("FLATTEN command received — closing all positions")
        if self._position_manager is None:
            return {"status": "completed", "action": "flatten", "detail": "No position manager configured"}
        results = self._position_manager.flatten()
        return {
            "status": "completed",
            "action": "flatten",
            "detail": f"Closed {len(results)} position(s)",
            "closed_positions": [
                {"symbol": r.symbol, "realized_pnl": r.realized_pnl_delta} for r in results
            ],
        }

    def _resolve_quantity(self, symbol: str) -> int:
        """Resolve order quantity based on instrument and lot size."""
        # Default: 1 lot of NIFTY (50) or BANKNIFTY (25)
        if "BANKNIFTY" in symbol:
            return 25
        return 50
