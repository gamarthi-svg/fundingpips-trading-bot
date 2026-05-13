"""Drawdown tracker with daily reset and trailing vs. static modes.

Tracks both balance-based and equity-based drawdown, supports the prop-firm
specific daily-loss rule (reset at 22:00 UTC / 00:00 CET), and can operate
in either *trailing* (peak resets to highest equity) or *static* (peak fixed
at starting balance) mode.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from enum import Enum
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Drawdown Mode Enumeration
# =============================================================================

class DrawdownMode(Enum):
    """Drawdown calculation mode.

    Attributes:
        TRAILING: Peak equity is the highest equity ever seen — drawdown is
            measured from the all-time high.  This is the most conservative
            mode and is used by most prop firms.
        STATIC: Peak is fixed at the starting balance (or a manually set
            value) and never ratchets up.  Useful for evaluation phases
            with fixed loss limits.
    """

    TRAILING = "trailing"
    STATIC = "static"


# =============================================================================
# Data Containers
# =============================================================================

@dataclass
class DrawdownSnapshot:
    """A single point-in-time drawdown reading.

    Attributes:
        timestamp: UTC timestamp of the reading.
        balance: Account balance at the time.
        equity: Account equity at the time.
        peak: Current peak value used for drawdown calculation.
        drawdown_abs: Absolute drawdown from peak in account currency.
        drawdown_pct: Drawdown as a percentage of peak.
        mode: Drawdown mode active at the time.
    """

    timestamp: datetime
    balance: float
    equity: float
    peak: float
    drawdown_abs: float
    drawdown_pct: float
    mode: DrawdownMode


@dataclass
class DailyDrawdown:
    """Drawdown statistics for a single trading day.

    Attributes:
        date: Calendar date (UTC).
        start_equity: Equity at day start.
        min_equity: Lowest equity reached during the day.
        end_equity: Equity at day end.
        peak_equity: Highest equity during the day.
        daily_loss: Largest loss from start equity (absolute).
        daily_loss_pct: Largest loss from start equity (percentage).
    """

    date: str  # ISO-8601 date string "YYYY-MM-DD"
    start_equity: float
    min_equity: float = 0.0
    end_equity: float = 0.0
    peak_equity: float = 0.0
    daily_loss: float = 0.0
    daily_loss_pct: float = 0.0


# =============================================================================
# Drawdown Tracker
# =============================================================================

class DrawdownTracker:
    """Tracks equity/balance drawdown with prop-firm specific rules.

    The FundingPips daily loss limit is calculated from the starting equity
    of each trading day.  At 22:00 UTC (midnight CET) the tracker resets:
    the current equity becomes the new ``day_start_equity`` and the daily
    loss counter is zeroed.

    Args:
        start_balance: Initial account balance.
        mode: Drawdown calculation mode (default: ``DrawdownMode.STATIC``
            during evaluation, ``DrawdownMode.TRAILING`` when funded).
        daily_loss_limit_pct: Maximum allowed daily loss as fraction.
        max_drawdown_pct: Maximum allowed total drawdown as fraction.
        reset_hour_utc: Hour of day (UTC) when daily stats reset.
    """

    def __init__(
        self,
        start_balance: float = 100_000.0,
        mode: DrawdownMode = DrawdownMode.STATIC,
        daily_loss_limit_pct: float = 0.05,
        max_drawdown_pct: float = 0.10,
        reset_hour_utc: int = 22,
    ) -> None:
        self.mode: DrawdownMode = mode
        self.daily_loss_limit_pct: float = daily_loss_limit_pct
        self.max_drawdown_pct: float = max_drawdown_pct
        self.reset_hour_utc: int = reset_hour_utc

        # Peak tracking
        self._start_balance: float = start_balance
        self._peak_equity: float = start_balance
        self._peak_balance: float = start_balance

        # Daily tracking
        self._day_start_equity: float = start_balance
        self._current_date: str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._daily_min_equity: float = start_balance
        self._daily_peak_equity: float = start_balance

        # History
        self._history: List[DrawdownSnapshot] = []
        self._daily_history: List[DailyDrawdown] = []

        logger.info(
            "DrawdownTracker init: balance=%.2f mode=%s daily_limit=%.2f%% "
            "max_dd=%.2f%% reset_hour=%dUTC",
            start_balance,
            mode.value,
            daily_loss_limit_pct * 100,
            max_drawdown_pct * 100,
            reset_hour_utc,
        )

    # ------------------------------------------------------------------
    # Core update
    # ------------------------------------------------------------------

    def update(self, balance: float, equity: float) -> DrawdownSnapshot:
        """Record a new equity/balance reading and compute drawdown.

        Automatically handles the daily reset at the configured UTC hour.

        Args:
            balance: Current account balance.
            equity: Current account equity (balance + open PnL).

        Returns:
            A :class:`DrawdownSnapshot` with current drawdown metrics.
        """
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")

        # --- Daily reset check ---
        if today != self._current_date:
            self._finalize_day()
            self._start_new_day(today, equity)
        elif now.hour == self.reset_hour_utc and now.minute == 0:
            # Soft reset window at the top of the hour
            if self._day_start_equity != equity:
                self._finalize_day()
                self._start_new_day(today, equity)

        # Update peaks
        if equity > self._peak_equity:
            self._peak_equity = equity
        if balance > self._peak_balance:
            self._peak_balance = balance

        # Daily intra-day tracking
        if equity < self._daily_min_equity:
            self._daily_min_equity = equity
        if equity > self._daily_peak_equity:
            self._daily_peak_equity = equity

        # Drawdown calculation
        peak = self._peak_equity if self.mode == DrawdownMode.TRAILING else self._start_balance
        drawdown_abs = max(peak - equity, 0.0)
        drawdown_pct = drawdown_abs / peak if peak > 0 else 0.0

        # Daily loss from day start
        daily_loss = max(self._day_start_equity - equity, 0.0)
        daily_loss_pct = (
            daily_loss / self._day_start_equity
            if self._day_start_equity > 0
            else 0.0
        )

        snapshot = DrawdownSnapshot(
            timestamp=now,
            balance=balance,
            equity=equity,
            peak=peak,
            drawdown_abs=drawdown_abs,
            drawdown_pct=drawdown_pct,
            mode=self.mode,
        )
        self._history.append(snapshot)

        # Check limits
        if drawdown_pct >= self.max_drawdown_pct:
            logger.critical(
                "MAX DRAWDOWN BREACH: %.4f%% >= %.4f%% (peak=%.2f equity=%.2f)",
                drawdown_pct * 100,
                self.max_drawdown_pct * 100,
                peak,
                equity,
            )

        if daily_loss_pct >= self.daily_loss_limit_pct:
            logger.critical(
                "DAILY LOSS BREACH: %.4f%% >= %.4f%% (start=%.2f equity=%.2f)",
                daily_loss_pct * 100,
                self.daily_loss_limit_pct * 100,
                self._day_start_equity,
                equity,
            )

        # Trim history to last 24 hours to prevent unbounded growth
        cutoff = now.timestamp() - 86_400
        self._history = [s for s in self._history if s.timestamp.timestamp() > cutoff]

        return snapshot

    # ------------------------------------------------------------------
    # Daily reset
    # ------------------------------------------------------------------

    def _finalize_day(self) -> None:
        """Save the current day's statistics and archive them."""
        daily_dd = DailyDrawdown(
            date=self._current_date,
            start_equity=self._day_start_equity,
            min_equity=self._daily_min_equity,
            end_equity=self._day_start_equity,  # Will be updated on next tick
            peak_equity=self._daily_peak_equity,
            daily_loss=max(self._day_start_equity - self._daily_min_equity, 0.0),
            daily_loss_pct=0.0,
        )
        if self._day_start_equity > 0:
            daily_dd.daily_loss_pct = (
                daily_dd.daily_loss / self._day_start_equity
            )
        self._daily_history.append(daily_dd)
        logger.info(
            "Day finalized: %s  start=%.2f min=%.2f peak=%.2f loss=%.4f%%",
            daily_dd.date,
            daily_dd.start_equity,
            daily_dd.min_equity,
            daily_dd.peak_equity,
            daily_dd.daily_loss_pct * 100,
        )

    def _start_new_day(self, date: str, equity: float) -> None:
        """Begin a new trading day with *equity* as the starting point."""
        self._current_date = date
        self._day_start_equity = equity
        self._daily_min_equity = equity
        self._daily_peak_equity = equity
        logger.info(
            "New trading day: %s  start_equity=%.2f", date, equity
        )

    def force_daily_reset(self, equity: float) -> None:
        """Manually reset the daily counter (e.g. after a timezone change).

        Args:
            equity: Current equity to use as the new day-start value.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._finalize_day()
        self._start_new_day(today, equity)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def current_drawdown_pct(self) -> float:
        """Return the current total drawdown as a percentage."""
        if not self._history:
            return 0.0
        return self._history[-1].drawdown_pct

    @property
    def current_drawdown_abs(self) -> float:
        """Return the current total drawdown in account currency."""
        if not self._history:
            return 0.0
        return self._history[-1].drawdown_abs

    @property
    def daily_drawdown_pct(self) -> float:
        """Return today's drawdown from the day-start equity."""
        if self._day_start_equity <= 0:
            return 0.0
        return max(self._day_start_equity - self._daily_min_equity, 0.0) / self._day_start_equity

    @property
    def peak_equity(self) -> float:
        """Return the all-time (or static) peak equity."""
        return self._peak_equity

    @property
    def is_daily_limit_breached(self) -> bool:
        """``True`` if today's loss has reached the daily limit."""
        return self.daily_drawdown_pct >= self.daily_loss_limit_pct

    @property
    def is_max_drawdown_breached(self) -> bool:
        """``True`` if total drawdown has reached the maximum limit."""
        return self.current_drawdown_pct >= self.max_drawdown_pct

    @property
    def remaining_daily_risk_pct(self) -> float:
        """Remaining risk budget for today as a fraction."""
        return max(self.daily_loss_limit_pct - self.daily_drawdown_pct, 0.0)

    @property
    def remaining_daily_risk_amount(self) -> float:
        """Remaining risk budget for today in account currency."""
        return self.remaining_daily_risk_pct * self._day_start_equity

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------

    def set_mode(self, mode: DrawdownMode) -> None:
        """Switch drawdown mode at runtime.

        When switching to **TRAILING**, the current equity becomes the new
        peak only if it is higher than the previous peak.

        Args:
            mode: New drawdown mode.
        """
        old_mode = self.mode
        self.mode = mode
        logger.info("Drawdown mode switched: %s -> %s", old_mode.value, mode.value)

    # ------------------------------------------------------------------
    # History access
    # ------------------------------------------------------------------

    def get_history(self) -> List[DrawdownSnapshot]:
        """Return the last 24 hours of drawdown snapshots."""
        return list(self._history)

    def get_daily_history(self) -> List[DailyDrawdown]:
        """Return all archived daily drawdown records."""
        return list(self._daily_history)

    def get_summary(self) -> Dict[str, float]:
        """Return a summary dictionary of current drawdown metrics."""
        return {
            "current_drawdown_pct": self.current_drawdown_pct,
            "current_drawdown_abs": self.current_drawdown_abs,
            "daily_drawdown_pct": self.daily_drawdown_pct,
            "peak_equity": self.peak_equity,
            "day_start_equity": self._day_start_equity,
            "daily_loss_limit_pct": self.daily_loss_limit_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "remaining_daily_risk_pct": self.remaining_daily_risk_pct,
            "remaining_daily_risk_amount": self.remaining_daily_risk_amount,
            "mode": self.mode.value,
        }
