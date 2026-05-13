"""
Forex London Session Breakout strategy.

Asian range is established between 00:00-07:00 GMT.  During the London
session (07:00-12:00 GMT) a breakout is triggered when the H1 close lies
outside the Asian range.  The strategy supports EURUSD, GBPUSD, and USDJPY.
"""

from __future__ import annotations

import logging
from datetime import time
from typing import List, Optional

import pandas as pd

from strategies.base import Direction, PartialTakeProfit, Signal, Strategy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Session boundaries (GMT)
# ---------------------------------------------------------------------------
_ASIAN_RANGE_START = time(0, 0)
_ASIAN_RANGE_END = time(7, 0)
_LONDON_START = time(7, 0)
_LONDON_END = time(12, 0)

# Stop-loss in pips (converted to price terms per symbol)
_SL_PIPS = 18.0

# R:R target
_RISK_REWARD = 2.0

# Supported symbols and their pip definitions
_PIP_SIZE = {
    "EURUSD": 0.0001,
    "GBPUSD": 0.0001,
    "USDJPY": 0.01,
}


class ForexStrategy(Strategy):
    """
    London session breakout for major FX pairs.

    Parameters
    ----------
    symbol:
        One of ``EURUSD``, ``GBPUSD``, ``USDJPY``.
    sl_pips:
        Stop-loss distance in pips (default 18).
    risk_reward:
        Target risk-reward ratio (default 2.0).
    """

    def __init__(
        self,
        symbol: str = "EURUSD",
        sl_pips: float = _SL_PIPS,
        risk_reward: float = _RISK_REWARD,
    ) -> None:
        if symbol not in _PIP_SIZE:
            raise ValueError(
                f"Unsupported symbol {symbol!r}; "
                f"choose from {list(_PIP_SIZE.keys())}"
            )
        super().__init__(name="ForexStrategy", symbol=symbol)
        self.sl_pips = sl_pips
        self.risk_reward = risk_reward
        self._pip = _PIP_SIZE[symbol]
        self._sl_distance = sl_pips * self._pip

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _asian_range(df: pd.DataFrame) -> Optional[tuple[float, float]]:
        """
        Compute the Asian session high/low from bars between 00:00 and
        07:00 GMT *within the current calendar day*.

        Returns (asian_high, asian_low) or None.
        """
        today = df.index[-1].normalize()
        asian_mask = (
            (df.index >= today + pd.Timedelta(hours=0))
            & (df.index < today + pd.Timedelta(hours=7))
        )
        asian_bars = df.loc[asian_mask]
        if len(asian_bars) < 2:
            return None
        return float(asian_bars["high"].max()), float(asian_bars["low"].min())

    @staticmethod
    def _in_london_session(ts) -> bool:
        """True if *ts* lies within 07:00-12:00 GMT."""
        t = ts.time() if hasattr(ts, "time") else ts
        return _LONDON_START <= t <= _LONDON_END

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------
    def generate_signal(self, data: pd.DataFrame) -> Optional[Signal]:
        """
        Breakout of the Asian range during the London session.

        *data* is expected to be H1 OHLCV with a GMT DatetimeIndex.
        """
        if data.empty or len(data) < 8:
            return None

        required = {"open", "high", "low", "close", "volume"}
        if not required.issubset(data.columns):
            logger.warning("Missing columns; have %s", set(data.columns))
            return None

        ts = data.index[-1]
        if not self._in_london_session(ts):
            return None

        # Compute Asian range for today
        asian = self._asian_range(data)
        if asian is None:
            return None
        asian_high, asian_low = asian

        # Latest completed H1 candle (use -2 to avoid the forming bar)
        if len(data) < 2:
            return None
        latest = data.iloc[-2]
        close = float(latest["close"])

        # Long breakout – close above Asian high during London
        if close > asian_high:
            sl = close - self._sl_distance
            tp = close + (self._sl_distance * self.risk_reward)
            confidence = self._confidence(close, asian_high, asian_low, Direction.LONG)
            signal = Signal(
                direction=Direction.LONG,
                entry_price=round(close, 5),
                stop_loss=round(sl, 5),
                take_profits=[
                    PartialTakeProfit(ratio=self.risk_reward, percent=1.0),
                ],
                confidence=round(confidence, 2),
                symbol=self.symbol,
                timestamp=ts,
            )
            logger.info(
                "FX LONG London breakout %s @ %.5f SL=%.5f "
                "asian_high=%.5f asian_low=%.5f",
                self.symbol, close, sl, asian_high, asian_low,
            )
            return signal

        # Short breakout – close below Asian low during London
        if close < asian_low:
            sl = close + self._sl_distance
            tp = close - (self._sl_distance * self.risk_reward)
            confidence = self._confidence(
                close, asian_high, asian_low, Direction.SHORT
            )
            signal = Signal(
                direction=Direction.SHORT,
                entry_price=round(close, 5),
                stop_loss=round(sl, 5),
                take_profits=[
                    PartialTakeProfit(ratio=self.risk_reward, percent=1.0),
                ],
                confidence=round(confidence, 2),
                symbol=self.symbol,
                timestamp=ts,
            )
            logger.info(
                "FX SHORT London breakout %s @ %.5f SL=%.5f "
                "asian_high=%.5f asian_low=%.5f",
                self.symbol, close, sl, asian_high, asian_low,
            )
            return signal

        return None

    # ------------------------------------------------------------------
    # Confidence scoring
    # ------------------------------------------------------------------
    def _confidence(
        self,
        close: float,
        asian_high: float,
        asian_low: float,
        direction: Direction,
    ) -> float:
        """
        Heuristic confidence based on how decisively price has broken
        the Asian range and the relative width of that range.
        """
        range_width = asian_high - asian_low
        if range_width <= 0.0:
            return 0.5

        if direction == Direction.LONG:
            breakout_distance = close - asian_high
        else:
            breakout_distance = asian_low - close

        # Normalise breakout distance against range width
        ratio = breakout_distance / range_width if range_width > 0 else 0.0
        base = 0.55
        bonus = min(0.35, ratio * 0.5)
        return min(0.95, base + bonus)
