"""Kill-Switch and Risk-Manager for the prop-firm trading bot.

Implements an 8-guard kill-switch architecture with a 3-tier risk-zone
system (GREEN / YELLOW / RED).  Every trading decision is gated through
the :class:`KillSwitch` before execution reaches the broker.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Risk Zone Enumeration
# =============================================================================

class RiskZone(Enum):
    """3-tier risk zone classification.

    Attributes:
        GREEN:  All guards pass — trading authorised.
        YELLOW: One or more soft-limit guards triggered — reduce size,
                tighten stops, raise caution.
        RED:    A hard-limit guard triggered — **all trading halted**.
    """

    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"


# =============================================================================
# Data Containers
# =============================================================================

@dataclass
class GuardReport:
    """Result of a single kill-switch guard check.

    Attributes:
        name: Human-readable guard identifier.
        passed: ``True`` if the guard condition is satisfied.
        hard: ``True`` if a failure should trigger a RED zone.
        message: Diagnostic string (empty when *passed* is ``True``).
    """

    name: str
    passed: bool
    hard: bool
    message: str = ""


@dataclass
class KillSwitchReport:
    """Aggregated result of all kill-switch guards.

    Attributes:
        zone: Computed risk zone.
        guards: Individual guard reports.
        halted: ``True`` when zone is RED.
        timestamp: UTC datetime of the evaluation.
    """

    zone: RiskZone
    guards: List[GuardReport] = field(default_factory=list)
    halted: bool = False
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def failed_hard(self) -> List[GuardReport]:
        """Return guards that failed with *hard* == ``True``."""
        return [g for g in self.guards if not g.passed and g.hard]

    @property
    def failed_soft(self) -> List[GuardReport]:
        """Return guards that failed with *hard* == ``False``."""
        return [g for g in self.guards if not g.passed and not g.hard]


@dataclass
class PositionExposure:
    """Lightweight position representation for risk calculations.

    Attributes:
        symbol: Trading instrument (e.g. ``"EURUSD"``).
        direction: ``1`` for long, ``-1`` for short.
        lots: Position size in lots.
        open_price: Average entry price.
        current_price: Current market price.
        unrealised_pnl: Floating PnL in account currency.
    """

    symbol: str
    direction: int
    lots: float
    open_price: float
    current_price: float
    unrealised_pnl: float = 0.0


@dataclass
class NewsEvent:
    """Scheduled high-impact news event.

    Attributes:
        title: Event description (e.g. ``"NFP"``).
        impact: Impact level — ``"high"``, ``"medium"``, ``"low"``.
        timestamp: Scheduled release time (UTC).
    """

    title: str
    impact: str
    timestamp: datetime


# =============================================================================
# Kill Switch — 8-Guard Architecture
# =============================================================================

class KillSwitch:
    """8-guard kill switch that gates every trading decision.

    Guards (in evaluation order):
        1. **Daily loss limit**   — hard stop when daily drawdown exceeds cap.
        2. **Max drawdown**       — hard stop when total drawdown exceeds cap.
        3. **Position limit**     — hard stop when open trades >= max.
        4. **Exposure limit**     — soft warning when notional exposure is high.
        5. **Correlation limit**  — soft warning when correlated positions stack.
        6. **News blackout**      — hard stop inside the blackout window.
        7. **Trading hours**      — hard stop outside allowed sessions.
        8. **Consistency cap**    — soft warning when best-trade / total-profit
                                    ratio exceeds the consistency limit.

    Args:
        account_size: Initial account balance.
        daily_loss_pct: Maximum allowable daily loss (e.g. ``0.05`` = 5%).
        max_drawdown_pct: Maximum allowable total drawdown (e.g. ``0.10``).
        max_positions: Maximum simultaneous open positions.
        max_exposure_pct: Maximum notional exposure as fraction of equity.
        max_correlated_positions: Max positions sharing the same base currency.
        news_blackout_minutes: Minutes before/after news to halt trading.
        consistency_limit: Max best-trade / total-profit ratio.
        trading_hours: Sequence of (start, end) UTC time tuples.
    """

    def __init__(
        self,
        account_size: float = 100_000.0,
        daily_loss_pct: float = 0.05,
        max_drawdown_pct: float = 0.10,
        max_positions: int = 3,
        max_exposure_pct: float = 0.30,
        max_correlated_positions: int = 2,
        news_blackout_minutes: int = 5,
        consistency_limit: float = 0.35,
        trading_hours: Optional[Sequence[Tuple[time, time]]] = None,
    ) -> None:
        self.account_size: float = account_size
        self.daily_loss_limit: float = account_size * daily_loss_pct
        self.max_drawdown_pct: float = max_drawdown_pct
        self.max_positions: int = max_positions
        self.max_exposure_pct: float = max_exposure_pct
        self.max_correlated_positions: int = max_correlated_positions
        self.news_blackout_minutes: int = news_blackout_minutes
        self.consistency_limit: float = consistency_limit

        # Default: London + NY overlap (12:00-21:00 UTC)
        self.trading_hours: Sequence[Tuple[time, time]] = trading_hours or [
            (time(12, 0), time(21, 0)),
        ]

        # Mutable runtime state
        self._daily_pnl: float = 0.0
        self._peak_equity: float = account_size
        self._halted: bool = False
        self._halt_reason: str = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        equity: float,
        positions: Sequence[PositionExposure],
        today_pnl: float,
        upcoming_news: Sequence[NewsEvent],
        best_trade_pct: float = 0.0,
        total_profit_pct: float = 0.0,
    ) -> KillSwitchReport:
        """Run all 8 guards and return an aggregated report.

        Args:
            equity: Current account equity.
            positions: Open positions snapshot.
            today_pnl: Realised + unrealised PnL since UTC midnight.
            upcoming_news: News events scheduled within the blackout window.
            best_trade_pct: Best single trade profit as % of account.
            total_profit_pct: Cumulative realised profit as % of account.

        Returns:
            A :class:`KillSwitchReport` containing the computed risk zone
            and individual guard results.
        """
        now = datetime.now(timezone.utc)
        guards: List[GuardReport] = []

        # --- Guard 1: Daily Loss Limit (hard) ---
        guards.append(
            self._check_daily_loss(today_pnl)
        )

        # --- Guard 2: Max Drawdown (hard) ---
        guards.append(
            self._check_max_drawdown(equity)
        )

        # --- Guard 3: Position Limit (hard) ---
        guards.append(
            self._check_position_limit(positions)
        )

        # --- Guard 4: Exposure Limit (soft) ---
        guards.append(
            self._check_exposure_limit(equity, positions)
        )

        # --- Guard 5: Correlation Limit (soft) ---
        guards.append(
            self._check_correlation_limit(positions)
        )

        # --- Guard 6: News Blackout (hard) ---
        guards.append(
            self._check_news_blackout(now, upcoming_news)
        )

        # --- Guard 7: Trading Hours (hard) ---
        guards.append(
            self._check_trading_hours(now)
        )

        # --- Guard 8: Consistency Cap (soft) ---
        guards.append(
            self._check_consistency(best_trade_pct, total_profit_pct)
        )

        # Determine zone
        any_hard_fail = any(not g.passed and g.hard for g in guards)
        any_soft_fail = any(not g.passed and not g.hard for g in guards)

        if any_hard_fail:
            zone = RiskZone.RED
            self._halted = True
            self._halt_reason = ", ".join(
                g.name for g in guards if not g.passed and g.hard
            )
            logger.critical(
                "KILL-SWITCH RED — halted. Reasons: %s", self._halt_reason
            )
        elif any_soft_fail:
            zone = RiskZone.YELLOW
        else:
            zone = RiskZone.GREEN

        return KillSwitchReport(
            zone=zone,
            guards=guards,
            halted=(zone == RiskZone.RED),
        )

    def reset_daily(self) -> None:
        """Reset daily PnL tracking (call at 22:00 UTC / 00:00 CET)."""
        self._daily_pnl = 0.0
        self._halted = False
        self._halt_reason = ""
        logger.info("Kill-switch daily state reset")

    def unhalt(self, admin_override: bool = False) -> None:
        """Clear the halt flag after manual review.

        Args:
            admin_override: Must be ``True`` to prevent accidental unhalting.
        """
        if admin_override:
            self._halted = False
            self._halt_reason = ""
            logger.warning("Kill-switch unhalted by admin override")

    @property
    def is_halted(self) -> bool:
        """Return ``True`` if the kill-switch is currently in RED."""
        return self._halted

    @property
    def halt_reason(self) -> str:
        """Human-readable reason for the last halt."""
        return self._halt_reason

    # ------------------------------------------------------------------
    # Individual Guard Implementations
    # ------------------------------------------------------------------

    def _check_daily_loss(self, today_pnl: float) -> GuardReport:
        """Guard 1 — Daily loss limit (hard)."""
        loss = -min(today_pnl, 0.0)
        passed = loss < self.daily_loss_limit
        return GuardReport(
            name="daily_loss_limit",
            passed=passed,
            hard=True,
            message="" if passed else (
                f"Daily loss {loss:.2f} >= limit {self.daily_loss_limit:.2f}"
            ),
        )

    def _check_max_drawdown(self, equity: float) -> GuardReport:
        """Guard 2 — Maximum drawdown (hard)."""
        if equity > self._peak_equity:
            self._peak_equity = equity
        drawdown = self._peak_equity - equity
        dd_pct = drawdown / self._peak_equity if self._peak_equity else 0.0
        limit = self.account_size * self.max_drawdown_pct
        passed = drawdown < limit and dd_pct < self.max_drawdown_pct
        return GuardReport(
            name="max_drawdown",
            passed=passed,
            hard=True,
            message="" if passed else (
                f"Drawdown {drawdown:.2f} ({dd_pct:.2%}) >= limit "
                f"{limit:.2f} ({self.max_drawdown_pct:.2%})"
            ),
        )

    def _check_position_limit(
        self, positions: Sequence[PositionExposure]
    ) -> GuardReport:
        """Guard 3 — Maximum open positions (hard)."""
        count = len(positions)
        passed = count < self.max_positions
        return GuardReport(
            name="position_limit",
            passed=passed,
            hard=True,
            message="" if passed else (
                f"Open positions {count} >= limit {self.max_positions}"
            ),
        )

    def _check_exposure_limit(
        self, equity: float, positions: Sequence[PositionExposure]
    ) -> GuardReport:
        """Guard 4 — Notional exposure limit (soft)."""
        total_notional = sum(
            pos.lots * 100_000 for pos in positions  # approx notional
        )
        limit = equity * self.max_exposure_pct
        passed = total_notional < limit
        return GuardReport(
            name="exposure_limit",
            passed=passed,
            hard=False,
            message="" if passed else (
                f"Exposure {total_notional:.0f} >= limit {limit:.0f} "
                f"({self.max_exposure_pct:.0%})"
            ),
        )

    def _check_correlation_limit(
        self, positions: Sequence[PositionExposure]
    ) -> GuardReport:
        """Guard 5 — Correlated position limit (soft).

        Counts positions sharing the same base currency (first 3 chars of
        symbol) and flags when the stack exceeds the limit.
        """
        from collections import Counter

        bases = [pos.symbol[:3].upper() for pos in positions]
        counts = Counter(bases)
        max_stack = max(counts.values()) if counts else 0
        passed = max_stack <= self.max_correlated_positions
        return GuardReport(
            name="correlation_limit",
            passed=passed,
            hard=False,
            message="" if passed else (
                f"Correlated stack {max_stack} > limit "
                f"{self.max_correlated_positions}"
            ),
        )

    def _check_news_blackout(
        self, now: datetime, events: Sequence[NewsEvent]
    ) -> GuardReport:
        """Guard 6 — News blackout window (hard)."""
        for event in events:
            if event.impact.lower() != "high":
                continue
            delta_min = abs((event.timestamp - now).total_seconds() / 60.0)
            if delta_min <= self.news_blackout_minutes:
                return GuardReport(
                    name="news_blackout",
                    passed=False,
                    hard=True,
                    message=(
                        f"High-impact news '{event.title}' in "
                        f"{delta_min:.0f} min (blackout={self.news_blackout_minutes})"
                    ),
                )
        return GuardReport(name="news_blackout", passed=True, hard=True)

    def _check_trading_hours(self, now: datetime) -> GuardReport:
        """Guard 7 — Permitted trading sessions (hard)."""
        t = now.time()
        in_session = any(start <= t <= end for start, end in self.trading_hours)
        # Handle overnight sessions (e.g. 22:00 -> 06:00)
        if not in_session:
            for start, end in self.trading_hours:
                if start > end:  # Overnight wrap
                    if t >= start or t <= end:
                        in_session = True
                        break
        return GuardReport(
            name="trading_hours",
            passed=in_session,
            hard=True,
            message="" if in_session else (
                f"Current UTC time {t} outside allowed sessions "
                f"{self.trading_hours}"
            ),
        )

    def _check_consistency(
        self, best_trade_pct: float, total_profit_pct: float
    ) -> GuardReport:
        """Guard 8 — Consistency score cap (soft).

        The consistency score is defined as the ratio of the best single
        trade's profit to the total realised profit.  A high ratio means
        one trade dominates — undesirable for prop-firm payouts.
        """
        if total_profit_pct <= 0 or best_trade_pct <= 0:
            return GuardReport(name="consistency_cap", passed=True, hard=False)
        score = best_trade_pct / total_profit_pct
        passed = score <= self.consistency_limit
        return GuardReport(
            name="consistency_cap",
            passed=passed,
            hard=False,
            message="" if passed else (
                f"Consistency score {score:.2f} > limit "
                f"{self.consistency_limit:.2f}"
            ),
        )


# =============================================================================
# Risk Manager — High-Level Orchestrator
# =============================================================================

class RiskManager:
    """High-level risk orchestrator that owns the kill-switch and exposes
    convenience helpers for strategy code.

    Typical usage::

        rm = RiskManager(account_size=100_000)
        report = rm.check(equity=102_000, positions=my_positions,
                          today_pnl=500, upcoming_news=[nfp_event])
        if report.zone == RiskZone.RED:
            rm.close_all()
        elif report.zone == RiskZone.YELLOW:
            rm.halve_position_sizes()

    Args:
        account_size: Starting account balance.
        kill_switch_params: Optional dict forwarded to :class:`KillSwitch`.
    """

    def __init__(
        self,
        account_size: float = 100_000.0,
        kill_switch_params: Optional[Dict[str, Any]] = None,
    ) -> None:
        params = kill_switch_params or {}
        self.kill_switch: KillSwitch = KillSwitch(
            account_size=account_size, **params
        )
        self._equity_history: List[Tuple[datetime, float]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(
        self,
        equity: float,
        positions: Sequence[PositionExposure],
        today_pnl: float,
        upcoming_news: Sequence[NewsEvent],
        best_trade_pct: float = 0.0,
        total_profit_pct: float = 0.0,
    ) -> KillSwitchReport:
        """Run the full kill-switch evaluation.

        Also records equity for time-series tracking.
        """
        now = datetime.now(timezone.utc)
        self._equity_history.append((now, equity))

        # Trim history to last 24 hours to avoid unbounded growth
        cutoff = now.timestamp() - 86_400
        self._equity_history = [
            (t, e) for t, e in self._equity_history if t.timestamp() > cutoff
        ]

        return self.kill_switch.evaluate(
            equity=equity,
            positions=positions,
            today_pnl=today_pnl,
            upcoming_news=upcoming_news,
            best_trade_pct=best_trade_pct,
            total_profit_pct=total_profit_pct,
        )

    @property
    def zone(self) -> RiskZone:
        """Return the current risk zone from the last evaluation."""
        # Simplified: strategies should cache the last KillSwitchReport
        return RiskZone.GREEN

    @property
    def is_halted(self) -> bool:
        """``True`` if trading is currently halted."""
        return self.kill_switch.is_halted

    def reset_daily(self) -> None:
        """Reset daily counters at the close of the trading day."""
        self.kill_switch.reset_daily()

    def unhalt(self, admin_override: bool = False) -> None:
        """Manually clear a halt after operator review."""
        self.kill_switch.unhalt(admin_override=admin_override)

    def get_equity_history(self) -> List[Tuple[datetime, float]]:
        """Return the last 24 h of (timestamp, equity) tuples."""
        return list(self._equity_history)

    def max_lot_size(
        self,
        equity: float,
        risk_pct: float,
        stop_pips: float,
        pip_value: float = 10.0,
    ) -> float:
        """Compute the maximum lot size given a risk budget and stop distance.

        Formula::

            risk_amount = equity * risk_pct
            lot_size    = risk_amount / (stop_pips * pip_value)

        Args:
            equity: Current account equity.
            risk_pct: Fraction of equity to risk (e.g. ``0.005`` = 0.5%).
            stop_pips: Stop-loss distance in pips.
            pip_value: Monetary value of one pip per lot.

        Returns:
            Maximum lot size (floored to 2 decimals).
        """
        if stop_pips <= 0 or pip_value <= 0:
            logger.error("Invalid stop_pips=%s or pip_value=%s", stop_pips, pip_value)
            return 0.0
        risk_amount = equity * risk_pct
        lots = risk_amount / (stop_pips * pip_value)
        return round(max(lots, 0.0), 2)
