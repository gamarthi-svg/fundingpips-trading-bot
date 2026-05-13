"""
OrderManager - High-level order preparation, execution, and open-position management.

Validates signals against kill-switches and risk limits, delegates execution
to MT5Bridge, manages trailing stops, and tracks per-strategy daily trade counts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple

from execution.mt5_bridge import MT5Bridge, OrderResult

logger = logging.getLogger(__name__)


class OrderDirection(str, Enum):
    """Canonical order direction values."""

    BUY = "buy"
    SELL = "sell"


@dataclass
class Signal:
    """Trading signal emitted by a strategy."""

    strategy_name: str
    symbol: str
    direction: OrderDirection
    volume: float
    sl: Optional[float] = None
    tp: Optional[float] = None
    comment: str = ""
    magic: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Optional partial-close ratios (e.g. [0.5, 0.3, 0.2])
    tp_partial_ratios: Optional[List[float]] = None


# ---------------------------------------------------------------------------
# Protocols for injected dependencies
# ---------------------------------------------------------------------------

class RiskManagerProtocol(Protocol):
    """Minimal interface expected from a risk-manager instance."""

    def check_drawdown(self, account_equity: float, account_balance: float) -> bool:
        """Return True if drawdown limit has NOT been breached."""
        ...

    def max_position_size(self, symbol: str) -> float:
        """Return the maximum allowed position size for *symbol*."""
        ...

    def max_daily_trades(self, strategy_name: str) -> int:
        """Return the maximum daily trades allowed for *strategy_name*."""
        ...


class KillSwitchProtocol(Protocol):
    """Minimal interface expected from a kill-switch instance."""

    @property
    def is_active(self) -> bool:
        """Return True if the kill-switch is engaged (trading halted)."""
        ...


# ---------------------------------------------------------------------------
# Order manager
# ---------------------------------------------------------------------------

class OrderManager:
    """Manages the full order lifecycle: validation, execution, and monitoring.

    Attributes:
        bridge: MT5Bridge instance for sending orders to the terminal.
        daily_trade_counts: Dict mapping (strategy_name, date) -> trade count.
    """

    def __init__(
        self,
        bridge: MT5Bridge,
        kill_switch: KillSwitchProtocol,
    ) -> None:
        """Initialize the order manager.

        Args:
            bridge: An initialised MT5Bridge.
            kill_switch: Kill-switch object with an ``is_active`` property.
        """
        self._bridge = bridge
        self._kill_switch = kill_switch
        self._daily_trade_counts: Dict[Tuple[str, str], int] = {}
        self._today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _reset_counts_if_new_day(self) -> None:
        """Clear daily trade counters when the UTC date rolls over."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._today_str:
            logger.info(
                "New day detected (%s -> %s); resetting daily trade counts",
                self._today_str,
                today,
            )
            self._daily_trade_counts.clear()
            self._today_str = today

    def _get_count_key(self, strategy_name: str) -> Tuple[str, str]:
        """Build the dictionary key for a strategy's daily trade count."""
        return (strategy_name, self._today_str)

    def _increment_trade_count(self, strategy_name: str) -> None:
        """Increment the daily trade counter for a strategy."""
        self._reset_counts_if_new_day()
        key = self._get_count_key(strategy_name)
        self._daily_trade_counts[key] = self._daily_trade_counts.get(key, 0) + 1

    def get_daily_trade_count(self, strategy_name: str) -> int:
        """Return the number of trades executed today for *strategy_name*.

        Args:
            strategy_name: Name of the strategy to query.

        Returns:
            Integer trade count (0 if no trades today).
        """
        self._reset_counts_if_new_day()
        return self._daily_trade_counts.get(self._get_count_key(strategy_name), 0)

    def get_all_daily_counts(self) -> Dict[str, int]:
        """Return a snapshot of today's trade counts per strategy.

        Returns:
            Dict mapping strategy_name -> trade count.
        """
        self._reset_counts_if_new_day()
        return {
            k[0]: v
            for k, v in self._daily_trade_counts.items()
            if k[1] == self._today_str
        }

    # ------------------------------------------------------------------ #
    # Validation
    # ------------------------------------------------------------------ #

    def prepare_order(
        self,
        signal: Signal,
        risk_mgr: RiskManagerProtocol,
    ) -> Tuple[bool, str]:
        """Validate a signal before it is sent to the market.

        Checks (in order):
        1. Kill-switch is NOT active.
        2. MT5 bridge is connected.
        3. Drawdown limit has not been breached.
        4. Position size is within risk-manager limits.
        5. Daily trade count limit has not been reached.

        Args:
            signal: The trading signal to validate.
            risk_mgr: Risk-manager instance implementing RiskManagerProtocol.

        Returns:
            (is_valid, reason) tuple.  *reason* is empty when valid.
        """
        # 1. Kill switch
        if self._kill_switch.is_active:
            logger.warning(
                "Order rejected: kill-switch active | %s %s %s",
                signal.strategy_name,
                signal.symbol,
                signal.direction.value,
            )
            return False, "kill-switch active"

        # 2. Bridge connectivity
        if not self._bridge.is_connected:
            logger.warning(
                "Order rejected: MT5 not connected | %s %s",
                signal.strategy_name,
                signal.symbol,
            )
            return False, "mt5 not connected"

        # 3. Drawdown check
        acct = self._bridge.get_account_info()
        if acct is None:
            logger.warning("Order rejected: cannot read account info")
            return False, "account info unavailable"

        if not risk_mgr.check_drawdown(acct.equity, acct.balance):
            logger.warning(
                "Order rejected: drawdown limit reached | equity=%.2f balance=%.2f",
                acct.equity,
                acct.balance,
            )
            return False, "drawdown limit reached"

        # 4. Position-size limit
        max_size = risk_mgr.max_position_size(signal.symbol)
        if signal.volume > max_size:
            logger.warning(
                "Order rejected: volume %.3f exceeds max %.3f for %s",
                signal.volume,
                max_size,
                signal.symbol,
            )
            return False, f"volume exceeds max {max_size}"

        # 5. Daily trade-count limit
        self._reset_counts_if_new_day()
        max_daily = risk_mgr.max_daily_trades(signal.strategy_name)
        current_count = self.get_daily_trade_count(signal.strategy_name)
        if current_count >= max_daily:
            logger.warning(
                "Order rejected: daily limit reached (%d/%d) for %s",
                current_count,
                max_daily,
                signal.strategy_name,
            )
            return False, f"daily trade limit {max_daily} reached"

        logger.info(
            "Signal validated OK | %s %s %s %.3f",
            signal.strategy_name,
            signal.symbol,
            signal.direction.value,
            signal.volume,
        )
        return True, ""

    # ------------------------------------------------------------------ #
    # Execution
    # ------------------------------------------------------------------ #

    def execute_order(self, signal: Signal) -> OrderResult:
        """Send a validated signal to the MT5 bridge for execution.

        Args:
            signal: A previously-validated Signal instance.

        Returns:
            OrderResult from the bridge.
        """
        logger.info(
            "Executing order | %s %s %s %.3f SL=%s TP=%s",
            signal.strategy_name,
            signal.symbol,
            signal.direction.value,
            signal.volume,
            signal.sl,
            signal.tp,
        )

        result = self._bridge.place_market_order(
            symbol=signal.symbol,
            direction=signal.direction.value,
            volume=signal.volume,
            sl=signal.sl,
            tp=signal.tp,
            magic=signal.magic,
            comment=f"{signal.strategy_name}:{signal.comment}".rstrip(":"),
        )

        if result.success:
            self._increment_trade_count(signal.strategy_name)
            logger.info(
                "Order executed OK | ticket=%d price=%.5f %s",
                result.ticket,
                result.price or 0.0,
                signal.symbol,
            )
        else:
            logger.error(
                "Order failed | %s %s error=%s",
                signal.symbol,
                signal.direction.value,
                result.comment,
            )

        return result

    # ------------------------------------------------------------------ #
    # Open-position management
    # ------------------------------------------------------------------ #

    def manage_open_positions(
        self,
        trailing_stop_callback: Optional[Callable[[List[Any]], None]] = None,
    ) -> Dict[str, Any]:
        """Iterate over open positions and apply management logic.

        Currently supports:
        - Logging current PnL per position.
        - Optional user-provided *trailing_stop_callback* that receives
          the raw position list for custom trailing-stop logic.

        Args:
            trailing_stop_callback: Optional callable(positions) invoked
                after logging.  Can modify stops via the bridge externally.

        Returns:
            Dict with summary statistics:
            {
                "total_positions": int,
                "total_profit": float,
                "symbols": List[str],
                "position_count": int,
            }
        """
        positions = self._bridge.get_positions()
        summary: Dict[str, Any] = {
            "total_positions": len(positions),
            "total_profit": 0.0,
            "symbols": [],
            "position_count": 0,
        }

        if not positions:
            logger.debug("No open positions to manage")
            return summary

        symbols: set[str] = set()
        for pos in positions:
            symbols.add(pos.symbol)
            summary["total_profit"] += pos.profit
            logger.debug(
                "Position | #%d %s %s %.3f P/L=%.2f SL=%.5f TP=%.5f",
                pos.ticket,
                pos.symbol,
                pos.direction,
                pos.volume,
                pos.profit,
                pos.sl,
                pos.tp,
            )

        summary["symbols"] = sorted(symbols)
        summary["position_count"] = len(positions)

        logger.info(
            "Open positions: %d | Symbols: %s | Unrealised P/L: %.2f",
            summary["position_count"],
            ", ".join(summary["symbols"]),
            summary["total_profit"],
        )

        if trailing_stop_callback is not None:
            try:
                trailing_stop_callback(positions)
            except Exception:
                logger.exception("trailing_stop_callback raised an exception")

        return summary

    # ------------------------------------------------------------------ #
    # Bulk operations
    # ------------------------------------------------------------------ #

    def close_all_positions(self, symbol: Optional[str] = None) -> List[OrderResult]:
        """Close all open positions, optionally filtered by symbol.

        Args:
            symbol: If provided, only close positions for this instrument.

        Returns:
            List of OrderResult from each close attempt.
        """
        logger.info("Closing all positions%s", f" for {symbol}" if symbol else "")
        return self._bridge.close_all_positions(symbol=symbol)

    def close_positions_for_strategy(self, magic: int) -> List[OrderResult]:
        """Close all positions opened with a specific magic number.

        Args:
            magic: The magic number identifying the strategy.

        Returns:
            List of OrderResult for each close attempt.
        """
        all_positions = self._bridge.get_positions()
        targets = [p for p in all_positions if p.magic == magic]
        if not targets:
            logger.info("No positions found with magic=%d", magic)
            return []

        results: List[OrderResult] = []
        for pos in targets:
            result = self._bridge.close_position(pos.ticket)
            results.append(result)

        successes = sum(1 for r in results if r.success)
        logger.info(
            "Closed %d/%d positions with magic=%d", successes, len(targets), magic
        )
        return results
