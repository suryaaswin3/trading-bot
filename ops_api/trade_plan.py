"""Pre-defined trade plans for disciplined execution.

A TradePlan encodes session-level constraints that gate all signal execution —
both scanner and webhook paths. Plans are loaded at session start and enforced
by a check gate in StrategyEngine.process().
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlanCheckResult:
    """Result of checking a signal against the trade plan."""

    approved: bool
    reason: str = ""


@dataclass
class TradePlan:
    """Pre-defined constraints for a trading session.

    These override the static config thresholds in QualityConfig,
    RegimeConfig, and ConfirmationConfig when set.
    """

    plan_id: str = "default"

    # ── Trade count limits ────────────────────────────────────────────
    max_trades_per_session: int = 5

    # ── Quality gate override (None = use QualityConfig default) ───────
    min_quality: float | None = None

    # ── Regime gate override (None = use RegimeConfig default) ─────────
    allowed_regimes: tuple[str, ...] = ("TREND", "VOLATILE")

    # ── Confirmation gate override (None = use ConfirmationConfig) ─────
    min_alignment: float | None = None

    # ── Risk limits ───────────────────────────────────────────────────
    max_daily_loss: float = 5000.0
    max_daily_gain: float = 10000.0
    risk_budget: float = 50000.0

    # ── Position sizing ───────────────────────────────────────────────
    position_size_mode: str = "fixed"  # "fixed" | "percent" | "remaining_budget"
    position_size_value: float = 1.0  # lots if "fixed", fraction if "percent"

    def check(self, session_metrics: dict[str, Any]) -> PlanCheckResult:
        """Check current session metrics against plan constraints.

        Args:
            session_metrics: Dict with keys like ``trades``, ``final_pnl``,
                ``peak_pnl``, ``max_drawdown``.

        Returns:
            PlanCheckResult with approved=True/False and reason string.
        """
        trades = session_metrics.get("trades", 0)
        pnl = session_metrics.get("final_pnl", 0.0)

        if trades >= self.max_trades_per_session:
            return PlanCheckResult(
                approved=False,
                reason=f"Max trades ({self.max_trades_per_session}) reached for session",
            )

        if pnl <= -self.max_daily_loss:
            return PlanCheckResult(
                approved=False,
                reason=f"Daily loss limit ({self.max_daily_loss}) breached (PnL={pnl:.2f})",
            )

        if pnl >= self.max_daily_gain:
            return PlanCheckResult(
                approved=False,
                reason=f"Daily gain limit ({self.max_daily_gain}) reached (PnL={pnl:.2f})",
            )

        return PlanCheckResult(approved=True, reason="")

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "max_trades_per_session": self.max_trades_per_session,
            "min_quality": self.min_quality,
            "allowed_regimes": list(self.allowed_regimes),
            "min_alignment": self.min_alignment,
            "max_daily_loss": self.max_daily_loss,
            "max_daily_gain": self.max_daily_gain,
            "risk_budget": self.risk_budget,
            "position_size_mode": self.position_size_mode,
            "position_size_value": self.position_size_value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TradePlan:
        return cls(
            plan_id=data.get("plan_id", "default"),
            max_trades_per_session=data.get("max_trades_per_session", 5),
            min_quality=data.get("min_quality"),
            allowed_regimes=tuple(data.get("allowed_regimes", ["TREND", "VOLATILE"])),
            min_alignment=data.get("min_alignment"),
            max_daily_loss=data.get("max_daily_loss", 5000.0),
            max_daily_gain=data.get("max_daily_gain", 10000.0),
            risk_budget=data.get("risk_budget", 50000.0),
            position_size_mode=data.get("position_size_mode", "fixed"),
            position_size_value=data.get("position_size_value", 1.0),
        )


# ── Module-level active plan ────────────────────────────────────────────

_active_plan: TradePlan = TradePlan()


def get_active_plan() -> TradePlan:
    """Return the currently active trade plan."""
    return _active_plan


def set_active_plan(plan: TradePlan) -> None:
    """Set the active trade plan."""
    global _active_plan
    _active_plan = plan


def reset_plan() -> None:
    """Reset to default plan."""
    global _active_plan
    _active_plan = TradePlan()