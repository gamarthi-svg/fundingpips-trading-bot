"""
XAU/USD (Gold) trading strategy.

Implements a dual-session approach:
* **Asian Session** (23:00-03:00 GMT) – range-scalping via EMA(20)
  crossover + RSI(14) filter.
* **NY Open** (13:30-14:30 GMT) – 5-minute Opening Range Breakout with
  ATR-based body confirmation and volume filter.
"""

from __future__ import annotations

import logging
from datetime import datetime, time
from typing import Optional

import pandas as pd
import numpy as np

from strategies.base import Direction, PartialTakeProfit, Signal, Strategy

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Session boundaries (GMT)
# ---------------------------------------------------------------------------
_ASIAN_START = time(23, 0)
_ASIAN_END = time(3, 0)
_NY_START = time(13, 30)
_NY_END = time(14, 30)

# Fixed stop distances (in price terms – 1 pip XAU/USD = 0.10)
_PIP_XAU = 0.10
_ASIAN_SL_PIPS = 10.0 * _PIP_XAU          # 10-pip stop
_NY_SL_PIPS = 18.0 * _PIP_XAU             # 18-pip stop

# Indicator parameters
_EMA_PERIOD = 20
_RSI_PERIOD = 14
_ATR_PERIOD = 5

# Minimum body-to-ATR ratio for a valid breakout candle
_MIN_BODY_ATR_RATIO = 0.8

# RSI thresholds for Asian range-scalping
_RSI_OVERBOUGHT = 65.0
_RSI_OVERSOLD = 35.0


def _in_session(t: time, start: time, end: time) -> bool:
    """Return True if *t* lies inside the half-open session [start, end).

    Handles the overnight wrap-around (e.g. 23:00 -> 03:00).
    """
    if start < end:
        return start <= t < end
    # overnight session
    return t >= start or t < end


def _ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average."""
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def _rsi(series: pd.Series, period: int) -> pd.Series:
    """Relative Strength Index (Wilder)."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def _atr(df: pd.DataFrame, period: int) -> pd.Series:
    """Average True Range."""
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window=period, min_periods=period).mean()


class XauUsdStrategy(Strategy):
    """
    XAU/USD strategy with Asian scalping and NY Opening Range Breakout.

    Parameters
    ----------
    asian_sl_pips:
        Stop-loss distance in pips for the Asian session (default 10).
    ny_sl_pips:
        Stop-loss distance in pips for the NY session (default 18).
    """

    def __init__(
        self,
        asian_sl_pips: float = 10.0,
        ny_sl_pips: float = 18.0,
    ) -> None:
        super().__init__(name="XauUsdStrategy", symbol="XAUUSD")
        self.asian_sl_pips = asian_sl_pips
        self.ny_sl_pips = ny_sl_pips
        self._asian_sl = asian_sl_pips * _PIP_XAU
        self._ny_sl = ny_sl_pips * _PIP_XAU

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _current_gmt_time(self, data: pd.DataFrame) -> time:
        """Extract the GMT time component from the last candle."""
        ts = data.index[-1]
        if isinstance(ts, pd.Timestamp):
            return ts.time()
        # numpy datetime64 / plain datetime
        return pd.Timestamp(ts).time()

    def _compute_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """Append EMA, RSI, ATR columns to *data*."""
        df = data.copy()
        df["ema20"] = _ema(df["close"], _EMA_PERIOD)
        df["rsi14"] = _rsi(df["close"], _RSI_PERIOD)
        df["atr5"] = _atr(df, _ATR_PERIOD)
        df["body"] = (df["close"] - df["open"]).abs()
        return df

    # ------------------------------------------------------------------
    # Asian session – range scalping
    # ------------------------------------------------------------------
    def _asian_signal(self, df: pd.DataFrame) -> Optional[Signal]:
        """EMA crossover + RSI filter scalping inside Asian session."""
        i = -1
        ema = df["ema20"].iloc[i]
        rsi = df["rsi14"].iloc[i]
        close = df["close"].iloc[i]

        # Need enough history
        if len(df) < _EMA_PERIOD + 2:
            return None

        prev_close = df["close"].iloc[-2]
        prev_ema = df["ema20"].iloc[-2]

        # Bullish crossover: price crosses above EMA with RSI not overbought
        if prev_close <= prev_ema and close > ema and rsi < _RSI_OVERBOUGHT:
            sl = close - self._asian_sl
            tp_price = close + (self._asian_sl * 2.0)   # 1:2 R:R
            signal = Signal(
                direction=Direction.LONG,
                entry_price=round(close, 2),
                stop_loss=round(sl, 2),
                take_profits=[
                    PartialTakeProfit(ratio=2.0, percent=1.0),
                ],
                confidence=round(0.5 + (rsi / 200.0), 2),  # ~0.5-0.8 range
                symbol=self.symbol,
                timestamp=df.index[-1],
            )
            logger.debug(
                "Asian LONG signal @ %.2f SL=%.2f RSI=%.1f", close, sl, rsi
            )
            return signal

        # Bearish crossover: price crosses below EMA with RSI not oversold
        if prev_close >= prev_ema and close < ema and rsi > _RSI_OVERSOLD:
            sl = close + self._asian_sl
            tp_price = close - (self._asian_sl * 2.0)
            signal = Signal(
                direction=Direction.SHORT,
                entry_price=round(close, 2),
                stop_loss=round(sl, 2),
                take_profits=[
                    PartialTakeProfit(ratio=2.0, percent=1.0),
                ],
                confidence=round(0.5 + ((100.0 - rsi) / 200.0), 2),
                symbol=self.symbol,
                timestamp=df.index[-1],
            )
            logger.debug(
                "Asian SHORT signal @ %.2f SL=%.2f RSI=%.1f", close, sl, rsi
            )
            return signal

        return None

    # ------------------------------------------------------------------
    # NY Open – Opening Range Breakout
    # ------------------------------------------------------------------
    def _ny_signal(self, df: pd.DataFrame) -> Optional[Signal]:
        """5-minute ORB during NY open window."""
        if len(df) < _ATR_PERIOD + 5:
            return None

        # The OR period is the first 15 minutes of the NY session window.
        # We assume *df* already contains only 5-min bars that fall inside
        # the NY open window.  We therefore use the first 3 bars of the
        # passed slice as the opening range.
        ny_bars = df.loc[
            df.index.time >= _NY_START
        ]
        if len(ny_bars) < 4:
            return None

        or_bars = ny_bars.iloc[:3]          # first 15 minutes (3 × 5-min)
        or_high = or_bars["high"].max()
        or_low = or_bars["low"].min()
        or_mid = (or_high + or_low) / 2.0

        # Latest completed candle (the one before the current forming bar)
        latest = df.iloc[-2]
        atr5 = df["atr5"].iloc[-2]
        body = latest["body"]
        prev_volume = df["volume"].iloc[-3] if len(df) >= 3 else 0

        if pd.isna(atr5) or atr5 == 0.0:
            return None

        # Body must be > 0.8 × ATR
        if body < _MIN_BODY_ATR_RATIO * atr5:
            return None

        # Volume filter
        if latest["volume"] <= prev_volume:
            return None

        close = latest["close"]

        # Long breakout – close above OR high
        if close > or_high:
            sl = close - self._ny_sl
            signal = Signal(
                direction=Direction.LONG,
                entry_price=round(close, 2),
                stop_loss=round(sl, 2),
                take_profits=[
                    PartialTakeProfit(ratio=1.5, percent=0.5),
                    PartialTakeProfit(ratio=3.0, percent=0.5),
                ],
                confidence=round(min(0.95, 0.6 + body / (atr5 * 2.0)), 2),
                symbol=self.symbol,
                timestamp=df.index[-1],
            )
            logger.debug(
                "NY LONG ORB @ %.2f SL=%.2f body/atr=%.2f",
                close, sl, body / atr5,
            )
            return signal

        # Short breakout – close below OR low
        if close < or_low:
            sl = close + self._ny_sl
            signal = Signal(
                direction=Direction.SHORT,
                entry_price=round(close, 2),
                stop_loss=round(sl, 2),
                take_profits=[
                    PartialTakeProfit(ratio=1.5, percent=0.5),
                    PartialTakeProfit(ratio=3.0, percent=0.5),
                ],
                confidence=round(min(0.95, 0.6 + body / (atr5 * 2.0)), 2),
                symbol=self.symbol,
                timestamp=df.index[-1],
            )
            logger.debug(
                "NY SHORT ORB @ %.2f SL=%.2f body/atr=%.2f",
                close, sl, body / atr5,
            )
            return signal

        return None

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------
    def generate_signal(self, data: pd.DataFrame) -> Optional[Signal]:
        """
        Route to the correct session logic based on the GMT timestamp of
        the latest candle.
        """
        if data.empty or len(data) < _EMA_PERIOD:
            return None

        # Ensure required columns exist
        required = {"open", "high", "low", "close", "volume"}
        if not required.issubset(data.columns):
            logger.warning("Missing columns in data; have %s", set(data.columns))
            return None

        df = self._compute_indicators(data)
        t = self._current_gmt_time(data)

        # Asian session (overnight wrap-around)
        if _in_session(t, _ASIAN_START, _ASIAN_END):
            logger.debug("Routing to Asian session logic (t=%s)", t)
            return self._asian_signal(df)

        # NY Open session
        if _in_session(t, _NY_START, _NY_END):
            logger.debug("Routing to NY Open session logic (t=%s)", t)
            return self._ny_signal(df)

        # Outside active sessions
        return None
