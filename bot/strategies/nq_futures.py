"""
NQ (E-mini NASDAQ-100) Futures Opening Range Breakout strategy.

Trades only Monday / Wednesday / Friday during the US cash-market open
(13:30-15:30 GMT, 09:30-11:30 ET).  The opening range is formed from the
first 15 minutes of the session.  A breakout is confirmed when the close of
a 5-minute bar lies outside the range, the candle body exceeds 0.8 × ATR(5),
and volume is expanding.

Maximum two trades per calendar day.
"""

from __future__ import annotations

import logging
from datetime import date, time
from typing import Dict, Optional, Set

import numpy as np
import pandas as pd

from strategies.base import Direction, PartialTakeProfit, Signal, Strategy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Session constants (GMT)
# ---------------------------------------------------------------------------
_SESSION_START_GMT = time(13, 30)
_SESSION_END_GMT = time(15, 30)
_OR_MINUTES = 15

# ATR settings
_ATR_PERIOD = 5
_MIN_BODY_ATR_RATIO = 0.8

# Stop distance in NQ points
_SL_POINTS = 10.0

# Partial take-profit schedule: (risk_multiple, percent_to_close)
_TP_SCHEDULE = [
    PartialTakeProfit(ratio=1.5, percent=0.50),
    PartialTakeProfit(ratio=2.5, percent=0.30),
    PartialTakeProfit(ratio=4.0, percent=0.20),
]

# Trading days (Monday=0 … Sunday=6)
_TRADING_DAYS: Set[int] = {0, 2, 4}  # Mon, Wed, Fri


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    """Average True Range."""
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window=period, min_periods=period).mean()


class NqFuturesStrategy(Strategy):
    """
    NQ Futures 5-minute Opening Range Breakout.

    Parameters
    ----------
    sl_points:
        Stop-loss distance in NQ points (default 10).
    max_trades_per_day:
        Maximum number of trades allowed per calendar day (default 2).
    """

    def __init__(
        self,
        sl_points: float = _SL_POINTS,
        max_trades_per_day: int = 2,
    ) -> None:
        super().__init__(name="NqFuturesStrategy", symbol="NQ")
        self.sl_points = sl_points
        self.max_trades_per_day = max_trades_per_day
        # Track trade counts by calendar date (YYYY-MM-DD string)
        self._trades_today: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _is_trading_day(ts: pd.Timestamp) -> bool:
        """Return True if *ts* falls on a permitted trading day."""
        return ts.weekday() in _TRADING_DAYS

    def _trade_count(self, d: date) -> int:
        """Number of trades already taken on *d*."""
        return self._trades_today.get(d.isoformat(), 0)

    def _record_trade(self, d: date) -> None:
        """Increment the trade counter for *d*."""
        key = d.isoformat()
        self._trades_today[key] = self._trades_today.get(key, 0) + 1

    def _can_trade(self, d: date) -> bool:
        """True if we have not reached the daily trade limit."""
        return self._trade_count(d) < self.max_trades_per_day

    @staticmethod
    def _opening_range(df_session: pd.DataFrame) -> Optional[tuple[float, float]]:
        """
        Compute the high/low of the opening range from the first
        *_OR_MINUTES* of the session.

        Returns (or_high, or_low) or None if insufficient data.
        """
        # Determine how many 5-min bars make up the OR
        bars_needed = _OR_MINUTES // 5
        if len(df_session) < bars_needed + 1:
            return None
        or_bars = df_session.iloc[:bars_needed]
        return float(or_bars["high"].max()), float(or_bars["low"].min())

    # ------------------------------------------------------------------
    # Signal generation
    # ------------------------------------------------------------------
    def generate_signal(self, data: pd.DataFrame) -> Optional[Signal]:
        """
        Generate a signal when an ORB setup is validated.

        The DataFrame is expected to contain 5-minute bars that fall
        inside the 13:30-15:30 GMT session window.
        """
        if data.empty or len(data) < _ATR_PERIOD + 3:
            return None

        required = {"open", "high", "low", "close", "volume"}
        if not required.issubset(data.columns):
            logger.warning("Missing columns; have %s", set(data.columns))
            return None

        ts = data.index[-1]
        if isinstance(ts, np.datetime64):
            ts = pd.Timestamp(ts)
        if not self._is_trading_day(ts):
            return None

        today = ts.date()
        if not self._can_trade(today):
            logger.debug("Daily trade limit reached for %s", today)
            return None

        # Compute indicators
        df = data.copy()
        df["atr5"] = _atr(df, _ATR_PERIOD)
        df["body"] = (df["close"] - df["open"]).abs()

        # Identify session bars (13:30-15:30 GMT)
        session_mask = (
            (df.index.time >= _SESSION_START_GMT)
            & (df.index.time <= _SESSION_END_GMT)
        )
        session_bars = df.loc[session_mask]
        if len(session_bars) < 4:
            return None

        or_range = self._opening_range(session_bars)
        if or_range is None:
            return None
        or_high, or_low = or_range

        # Latest *completed* candle (index -2 because -1 may be forming)
        if len(df) < 2:
            return None
        latest = df.iloc[-2]
        prev = df.iloc[-3] if len(df) >= 3 else None

        close = float(latest["close"])
        body = float(latest["body"])
        atr5 = float(latest["atr5"])
        volume = float(latest["volume"])

        if pd.isna(atr5) or atr5 == 0.0:
            return None

        # Body confirmation
        if body < _MIN_BODY_ATR_RATIO * atr5:
            return None

        # Volume filter
        if prev is not None and volume <= float(prev["volume"]):
            return None

        # ---- Long breakout ----
        if close > or_high:
            sl = close - self.sl_points
            confidence = min(0.95, 0.55 + body / (atr5 * 2.0))
            signal = Signal(
                direction=Direction.LONG,
                entry_price=round(close, 2),
                stop_loss=round(sl, 2),
                take_profits=list(_TP_SCHEDULE),
                confidence=round(confidence, 2),
                symbol=self.symbol,
                timestamp=ts,
            )
            self._record_trade(today)
            logger.info(
                "NQ LONG ORB @ %.2f SL=%.2f or_high=%.2f body/atr=%.2f",
                close, sl, or_high, body / atr5,
            )
            return signal

        # ---- Short breakout ----
        if close < or_low:
            sl = close + self.sl_points
            confidence = min(0.95, 0.55 + body / (atr5 * 2.0))
            signal = Signal(
                direction=Direction.SHORT,
                entry_price=round(close, 2),
                stop_loss=round(sl, 2),
                take_profits=list(_TP_SCHEDULE),
                confidence=round(confidence, 2),
                symbol=self.symbol,
                timestamp=ts,
            )
            self._record_trade(today)
            logger.info(
                "NQ SHORT ORB @ %.2f SL=%.2f or_low=%.2f body/atr=%.2f",
                close, sl, or_low, body / atr5,
            )
            return signal

        return None
