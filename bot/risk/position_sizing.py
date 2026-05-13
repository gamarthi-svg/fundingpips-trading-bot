"""ATR-based position sizing with correlation-adjusted heat calculator.

Provides volatility-adaptive lot sizing and portfolio-level heat tracking
so that total risk never exceeds the per-trade and per-day budgets set by
the active :class:`~config.settings.BotConfig` risk profile.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)


# =============================================================================
# Data Containers
# =============================================================================

@dataclass
class SizingInput:
    """Parameters required for a single position-sizing calculation.

    Attributes:
        equity: Current account equity.
        atr: Average True Range of the instrument (price units).
        atr_multiplier: Stop distance as a multiple of ATR (e.g. ``1.5``).
        risk_pct: Fraction of equity to risk on this trade.
        pip_value: Monetary value of one pip per standard lot.
        point_size: Size of one point / pip in price terms.
        min_lot: Broker minimum lot size.
        max_lot: Broker maximum lot size.
        lot_step: Lot increment granularity (e.g. ``0.01``).
    """

    equity: float
    atr: float
    atr_multiplier: float = 1.5
    risk_pct: float = 0.005
    pip_value: float = 10.0
    point_size: float = 0.0001
    min_lot: float = 0.01
    max_lot: float = 100.0
    lot_step: float = 0.01


@dataclass
class SizingResult:
    """Output of a position-sizing calculation.

    Attributes:
        lots: Rounded lot size ready for order submission.
        raw_lots: Unrounded theoretical lot size.
        stop_pips: Stop-loss distance in pips.
        stop_price: Stop-loss price level.
        risk_amount: Monetary amount at risk.
        risk_pct: Actual risk as % of equity (may differ from target
                  due to lot-step rounding).
    """

    lots: float
    raw_lots: float
    stop_pips: float
    stop_price: float
    risk_amount: float
    risk_pct: float


@dataclass
class PositionHeat:
    """Risk contribution of a single open position.

    Attributes:
        symbol: Trading instrument.
        lots: Position size.
        risk_amount: Estimated monetary loss if stop is hit.
        risk_pct: Position risk as % of account equity.
        correlation_group: Base currency (first 3 chars) for grouping.
    """

    symbol: str
    lots: float
    risk_amount: float
    risk_pct: float
    correlation_group: str = ""


# =============================================================================
# ATR Position Sizer
# =============================================================================

class ATRPositionSizer:
    """ volatility-based position sizing using ATR-derived stop distance.

    The stop-loss is placed at ``entry +/- atr * atr_multiplier`` and the
    lot size is computed so that the monetary risk equals
    ``equity * risk_pct``.

    Args:
        default_risk_pct: Default risk-per-trade when not overridden per call.
        default_atr_mult: Default ATR multiplier for stop distance.
    """

    def __init__(
        self,
        default_risk_pct: float = 0.005,
        default_atr_mult: float = 1.5,
    ) -> None:
        self.default_risk_pct: float = default_risk_pct
        self.default_atr_mult: float = default_atr_mult

    # ------------------------------------------------------------------
    # Core sizing formula
    # ------------------------------------------------------------------

    def calculate(
        self,
        inp: SizingInput,
        entry_price: Optional[float] = None,
        direction: int = 1,
    ) -> SizingResult:
        """Compute lot size and stop level from ATR-based inputs.

        Algorithm::

            stop_distance_price = atr * atr_multiplier
            stop_pips           = stop_distance_price / point_size
            risk_amount         = equity * risk_pct
            raw_lots            = risk_amount / (stop_pips * pip_value)
            lots                = clamp(round_to_step(raw_lots), min_lot, max_lot)

        Args:
            inp: Populated :class:`SizingInput` instance.
            entry_price: Optional entry price to compute absolute stop level.
            direction: ``1`` for long, ``-1`` for short.

        Returns:
            A :class:`SizingResult` with rounded lots and stop metadata.
        """
        if inp.equity <= 0:
            logger.error("Equity must be > 0, got %s", inp.equity)
            return SizingResult(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        if inp.atr <= 0:
            logger.error("ATR must be > 0, got %s", inp.atr)
            return SizingResult(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        # Stop distance in price terms
        stop_dist_price = inp.atr * inp.atr_multiplier

        # Convert to pips
        stop_pips = stop_dist_price / inp.point_size if inp.point_size else 0.0

        if stop_pips <= 0 or inp.pip_value <= 0:
            logger.error(
                "Invalid stop_pips=%s or pip_value=%s", stop_pips, inp.pip_value
            )
            return SizingResult(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        # Core lot-size formula
        risk_amount = inp.equity * inp.risk_pct
        raw_lots = risk_amount / (stop_pips * inp.pip_value)
        lots = self._round_to_step(raw_lots, inp.lot_step)
        lots = max(lots, inp.min_lot)
        lots = min(lots, inp.max_lot)

        # Recompute actual risk after rounding / clamping
        actual_risk = lots * stop_pips * inp.pip_value
        actual_risk_pct = actual_risk / inp.equity if inp.equity else 0.0

        # Absolute stop price
        stop_price = 0.0
        if entry_price is not None:
            stop_price = entry_price - direction * stop_dist_price

        logger.debug(
            "Sizing: eq=%.2f atr=%.5f stop=%.1fp lots=%.2f risk=%.2f (%.3f%%)",
            inp.equity, inp.atr, stop_pips, lots, actual_risk, actual_risk_pct * 100,
        )

        return SizingResult(
            lots=lots,
            raw_lots=raw_lots,
            stop_pips=stop_pips,
            stop_price=stop_price,
            risk_amount=actual_risk,
            risk_pct=actual_risk_pct,
        )

    def quick_size(
        self,
        equity: float,
        atr: float,
        stop_pips: float,
        risk_pct: Optional[float] = None,
        pip_value: float = 10.0,
    ) -> float:
        """Fast lot-size estimate when stop distance is already known in pips.

        Args:
            equity: Account equity.
            atr: ATR value (logged but not used in calculation).
            stop_pips: Desired stop distance in pips.
            risk_pct: Override default risk percentage.
            pip_value: Pip value per lot.

        Returns:
            Rounded lot size.
        """
        rp = risk_pct if risk_pct is not None else self.default_risk_pct
        if equity <= 0 or stop_pips <= 0 or pip_value <= 0:
            return 0.0
        risk_amount = equity * rp
        lots = risk_amount / (stop_pips * pip_value)
        return round(max(lots, 0.0), 2)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _round_to_step(value: float, step: float) -> float:
        """Round *value* to the nearest multiple of *step*."""
        if step <= 0:
            return value
        return round(value / step) * step


# =============================================================================
# Portfolio Heat Calculator
# =============================================================================

class PortfolioHeatCalculator:
    """Tracks aggregate portfolio heat with correlation adjustment.

    *Portfolio heat* is the total percentage of equity at risk across all
    open positions.  Correlated positions (e.g. EURUSD + EURGBP) increase
    heat non-linearly; this calculator applies a penalty multiplier when
    multiple positions share the same base currency.

    Args:
        correlation_penalty: Additional heat weight per extra correlated
            position (e.g. ``0.15`` = +15% per additional position).
        max_portfolio_heat: Maximum allowable aggregate heat.
    """

    def __init__(
        self,
        correlation_penalty: float = 0.15,
        max_portfolio_heat: float = 0.02,
    ) -> None:
        self.correlation_penalty: float = correlation_penalty
        self.max_portfolio_heat: float = max_portfolio_heat

    # ------------------------------------------------------------------
    # Core heat calculations
    # ------------------------------------------------------------------

    def calculate_heat(
        self, positions: Sequence[PositionHeat]
    ) -> Dict[str, float]:
        """Compute raw and correlation-adjusted portfolio heat.

        Args:
            positions: Sequence of :class:`PositionHeat` snapshots.

        Returns:
            Dictionary with keys:

            - ``raw_heat`` — sum of individual position risk %
            - ``adjusted_heat`` — correlation-penalty-adjusted total
            - ``max_heat`` — configured limit
            - ``breached`` — ``True`` if adjusted_heat > max_heat
        """
        from collections import Counter

        raw_heat = sum(p.risk_pct for p in positions)

        # Correlation adjustment: count positions per base currency
        group_counts = Counter(p.correlation_group for p in positions)
        penalty = 0.0
        for group, count in group_counts.items():
            if count > 1:
                # Each extra position in the same group adds a penalty
                group_risk = sum(
                    p.risk_pct for p in positions if p.correlation_group == group
                )
                penalty += group_risk * self.correlation_penalty * (count - 1)
                logger.debug(
                    "Correlation penalty for %s: +%.4f (count=%d)",
                    group, group_risk * self.correlation_penalty * (count - 1), count,
                )

        adjusted_heat = raw_heat + penalty
        breached = adjusted_heat > self.max_portfolio_heat

        if breached:
            logger.warning(
                "Portfolio heat %.4f > limit %.4f (raw=%.4f penalty=%.4f)",
                adjusted_heat, self.max_portfolio_heat, raw_heat, penalty,
            )

        return {
            "raw_heat": raw_heat,
            "adjusted_heat": adjusted_heat,
            "penalty": penalty,
            "max_heat": self.max_portfolio_heat,
            "breached": breached,
        }

    def can_add_position(
        self,
        current: Sequence[PositionHeat],
        candidate: PositionHeat,
    ) -> bool:
        """Check whether adding *candidate* would keep heat within limits.

        Args:
            current: Currently open positions.
            candidate: Prospective position to add.

        Returns:
            ``True`` if the portfolio would remain within limits.
        """
        simulated = list(current) + [candidate]
        result = self.calculate_heat(simulated)
        return not result["breached"]

    def lot_limit_for_symbol(
        self,
        symbol: str,
        risk_per_lot: float,
        equity: float,
        current_positions: Sequence[PositionHeat],
    ) -> float:
        """Compute the maximum additional lots allowed for *symbol*.

        Derives the remaining risk budget from ``max_portfolio_heat`` and
        converts it back to a lot cap.

        Args:
            symbol: Instrument to trade (e.g. ``"EURUSD"``).
            risk_per_lot: Estimated risk amount per lot for this instrument.
            equity: Current account equity.
            current_positions: Existing open positions.

        Returns:
            Maximum additional lots (may be ``0.0``).
        """
        if equity <= 0 or risk_per_lot <= 0:
            return 0.0

        result = self.calculate_heat(current_positions)
        if result["breached"]:
            return 0.0

        remaining_risk_pct = self.max_portfolio_heat - result["adjusted_heat"]
        remaining_risk_amount = remaining_risk_pct * equity
        max_lots = remaining_risk_amount / risk_per_lot

        logger.debug(
            "Lot limit for %s: %.2f (remaining_risk=%.2f risk/lot=%.2f)",
            symbol, max_lots, remaining_risk_amount, risk_per_lot,
        )

        return round(max(max_lots, 0.0), 2)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    @staticmethod
    def position_heat_from_lots(
        symbol: str,
        lots: float,
        stop_pips: float,
        pip_value: float,
        equity: float,
    ) -> PositionHeat:
        """Create a :class:`PositionHeat` instance from raw parameters.

        Args:
            symbol: Trading instrument.
            lots: Position size.
            stop_pips: Stop distance in pips.
            pip_value: Pip value per lot.
            equity: Account equity.

        Returns:
            Populated :class:`PositionHeat`.
        """
        risk_amount = lots * stop_pips * pip_value
        risk_pct = risk_amount / equity if equity else 0.0
        return PositionHeat(
            symbol=symbol,
            lots=lots,
            risk_amount=risk_amount,
            risk_pct=risk_pct,
            correlation_group=symbol[:3].upper(),
        )

    def heat_summary(
        self, positions: Sequence[PositionHeat]
    ) -> str:
        """Return a human-readable heat summary for logging."""
        result = self.calculate_heat(positions)
        lines = [
            f"Portfolio Heat: {result['adjusted_heat']:.4f}",
            f"  Raw heat:     {result['raw_heat']:.4f}",
            f"  Penalty:      {result['penalty']:.4f}",
            f"  Limit:        {result['max_heat']:.4f}",
            f"  Breached:     {result['breached']}",
        ]
        for pos in positions:
            lines.append(
                f"  {pos.symbol}: {pos.lots:.2f} lots "
                f"({pos.risk_pct:.4f}%)"
            )
        return "\n".join(lines)
