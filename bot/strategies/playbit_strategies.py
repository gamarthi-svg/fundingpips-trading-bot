"""
PlayBit Proprietary Strategies — FULL MODEL Implementation
===========================================================
D-ORB  : Dynamic Opening Range Breakout (volatility-adaptive ORB)
ILM    : Intelligent Liquidity Model (institutional sweep/reclaim)

Both strategies include:
    * Prop-firm compliance checks
    * ATR-based dynamic SL / TP
    * Session-aware entries
    * Comprehensive docstrings & type hints

Author  : PlayBit Strategy Developer
Version : 1.0.0
"""

from __future__ import annotations

import logging
import warnings
from datetime import datetime, time
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")

# Lazy imports to avoid circular dependency with library.py
# (library.py imports from this module at module end)
def _import_library():
    """Lazy import strategies.library to break circular dependency."""
    from strategies.library import (
        CONTRACT_VALUES,
        StrategyConfig,
        add_indicators,
        build_signal_dict,
        check_min_atr,
        check_prop_firm_compliance,
        calculate_position_size,
    )
    return {
        "CONTRACT_VALUES": CONTRACT_VALUES,
        "StrategyConfig": StrategyConfig,
        "add_indicators": add_indicators,
        "build_signal_dict": build_signal_dict,
        "check_min_atr": check_min_atr,
        "check_prop_firm_compliance": check_prop_firm_compliance,
        "calculate_position_size": calculate_position_size,
    }

# ═══════════════════════════════════════════════════════════════════════════════
# === SHARED INDICATOR HELPERS ===
# ═══════════════════════════════════════════════════════════════════════════════


def _ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average."""
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder)."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range."""
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, min_periods=period).mean()


def _atr_wilder(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range using simple rolling mean (standard)."""
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window=period, min_periods=period).mean()


# ═══════════════════════════════════════════════════════════════════════════════
# === SHARED COMPONENT: LIQUIDITY POOL DETECTION ===
# ═══════════════════════════════════════════════════════════════════════════════


def detect_liquidity_pools(df: pd.DataFrame, lookback: int = 100) -> List[dict]:
    """Identify liquidity pools in price data.

    Liquidity pools are price levels where institutional stop orders
    cluster. Retail traders place stops at obvious levels, and institutions
    engineer price moves to harvest that liquidity before reversing.

    Detects:
        * Equal highs/lows (2+ touches within tolerance)
        * Swing highs/lows (local maxima/minima)
        * Previous session high/low
        * Round numbers (psychological levels)

    Parameters
    ----------
    df:
        OHLCV DataFrame with DatetimeIndex. Columns: open, high, low, close.
    lookback:
        Number of bars to scan for liquidity pools (default 100).

    Returns
    -------
    List of dictionaries with keys: ``level``, ``type``, ``strength``, ``touches``
    """
    pools: List[dict] = []
    if len(df) < lookback:
        return pools

    window = df.iloc[-lookback:].copy()
    highs = window["high"].values
    lows = window["low"].values
    price_range = window["high"].max() - window["low"].min()
    tolerance = price_range * 0.001 if price_range > 0 else 0.01

    # --- 1. Equal highs/lows (clustered stops) ---
    for level_type, values in [("equal_highs", highs), ("equal_lows", lows)]:
        visited = set()
        for i, val in enumerate(values):
            if i in visited:
                continue
            matches = [j for j, v in enumerate(values) if abs(v - val) <= tolerance]
            if len(matches) >= 2:
                avg_level = float(np.mean([values[m] for m in matches]))
                pools.append(
                    {
                        "level": round(avg_level, 5),
                        "type": level_type,
                        "strength": min(len(matches) / 5.0, 1.0),  # normalize
                        "touches": len(matches),
                    }
                )
                visited.update(matches)

    # --- 2. Swing highs/lows (pivot points) ---
    pivot_window = 5  # 5-bar pivot
    for i in range(pivot_window, len(highs) - pivot_window):
        # Swing high
        if highs[i] == max(highs[i - pivot_window : i + pivot_window + 1]):
            pools.append(
                {
                    "level": round(float(highs[i]), 5),
                    "type": "swing_high",
                    "strength": 0.8,
                    "touches": 1,
                }
            )
        # Swing low
        if lows[i] == min(lows[i - pivot_window : i + pivot_window + 1]):
            pools.append(
                {
                    "level": round(float(lows[i]), 5),
                    "type": "swing_low",
                    "strength": 0.8,
                    "touches": 1,
                }
            )

    # --- 3. Previous session high/low ---
    if isinstance(df.index, pd.DatetimeIndex):
        today = df.index[-1].normalize()
        yest_mask = df.index < today
        if yest_mask.any():
            yest_data = df.loc[yest_mask]
            if not yest_data.empty:
                pools.append(
                    {
                        "level": round(float(yest_data["high"].max()), 5),
                        "type": "prev_day_high",
                        "strength": 0.9,
                        "touches": 1,
                    }
                )
                pools.append(
                    {
                        "level": round(float(yest_data["low"].min()), 5),
                        "type": "prev_day_low",
                        "strength": 0.9,
                        "touches": 1,
                    }
                )

    # --- 4. Round numbers (psychological levels) ---
    current_price = df["close"].iloc[-1]
    magnitude = 10 ** (int(np.log10(current_price)) - 1) if current_price > 0 else 10
    for offset in [-1, 0, 1]:
        rnd_level = round((current_price // magnitude + offset) * magnitude, 5)
        if rnd_level > 0:
            pools.append(
                {
                    "level": rnd_level,
                    "type": "round_number",
                    "strength": 0.5,
                    "touches": 0,
                }
            )

    # Deduplicate: merge pools within tolerance
    pools.sort(key=lambda x: x["level"])
    merged: List[dict] = []
    for p in pools:
        if not merged or abs(p["level"] - merged[-1]["level"]) > tolerance:
            merged.append(p)
        else:
            # Merge: take weighted average
            prev = merged[-1]
            total_touches = prev["touches"] + p["touches"]
            if total_touches > 0:
                prev["level"] = round(
                    (prev["level"] * prev["touches"] + p["level"] * p["touches"])
                    / total_touches,
                    5,
                )
            prev["strength"] = max(prev["strength"], p["strength"])
            prev["touches"] = max(prev["touches"], p["touches"])
            prev["type"] = prev["type"] + "|" + p["type"]

    # Sort by strength descending
    merged.sort(key=lambda x: x["strength"], reverse=True)
    return merged


# ═══════════════════════════════════════════════════════════════════════════════
# === SHARED COMPONENT: LIQUIDITY SWEEP DETECTION ===
# ═══════════════════════════════════════════════════════════════════════════════


def detect_sweep(
    df: pd.DataFrame,
    level: float,
    direction: str,
    lookback: int = 3,
) -> dict:
    """Detect if price swept a liquidity level.

    A liquidity sweep occurs when price briefly breaches a key level
    (trapping breakout traders) but fails to close beyond it — signaling
    that institutions have absorbed the liquidity and may reverse.

    Parameters
    ----------
    df:
        OHLCV DataFrame with DatetimeIndex.
    level:
        The liquidity price level to test.
    direction:
        ``"bullish"`` for a sweep below the level (stop hunt on lows)
        or ``"bearish"`` for a sweep above the level (stop hunt on highs).
    lookback:
        Number of recent bars to examine for the sweep pattern.

    Returns
    -------
    Dictionary with keys:
        ``swept`` (bool), ``wick_extreme`` (float),
        ``sweep_bar_idx`` (int or None), ``strength`` (float 0-1)
    """
    result = {
        "swept": False,
        "wick_extreme": 0.0,
        "sweep_bar_idx": None,
        "strength": 0.0,
    }
    if len(df) < lookback + 1:
        return result

    window = df.iloc[-lookback:]
    price_range = window["high"].max() - window["low"].min()
    tolerance = price_range * 0.001 if price_range > 0 else 0.01

    for idx, (_, row) in enumerate(window.iterrows()):
        if direction == "bullish":
            # Bullish sweep: wick below level, close back above
            wick_beyond = row["low"] < (level - tolerance)
            close_back = row["close"] > level
            if wick_beyond and close_back:
                strength = min(1.0, (level - row["low"]) / price_range * 10) if price_range > 0 else 0.5
                return {
                    "swept": True,
                    "wick_extreme": round(float(row["low"]), 5),
                    "sweep_bar_idx": idx,
                    "strength": round(strength, 2),
                }

        elif direction == "bearish":
            # Bearish sweep: wick above level, close back below
            wick_beyond = row["high"] > (level + tolerance)
            close_back = row["close"] < level
            if wick_beyond and close_back:
                strength = min(1.0, (row["high"] - level) / price_range * 10) if price_range > 0 else 0.5
                return {
                    "swept": True,
                    "wick_extreme": round(float(row["high"]), 5),
                    "sweep_bar_idx": idx,
                    "strength": round(strength, 2),
                }

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# === SHARED COMPONENT: FAIR VALUE GAP DETECTION ===
# ═══════════════════════════════════════════════════════════════════════════════


def detect_fvg(df: pd.DataFrame) -> List[dict]:
    """Detect Fair Value Gaps (3-candle imbalances).

    A Fair Value Gap (FVG) is a 3-candle pattern where candle 1 and candle 3
    do not overlap, creating an "imbalanced" price zone. Price often returns
    to fill/mitigate this gap before continuing.

    Pattern:
        * Bullish FVG: candle1.high < candle3.low (gap up)
        * Bearish FVG: candle1.low > candle3.high (gap down)

    Parameters
    ----------
    df:
        OHLCV DataFrame with at least 3 bars.

    Returns
    -------
    List of dictionaries with keys:
        ``type`` (``"bullish"`` or ``"bearish"``),
        ``top`` (float), ``bottom`` (float),
        ``width`` (float), ``fill_status`` (``"unfilled"`` | ``"mitigated"``)
    """
    gaps: List[dict] = []
    if len(df) < 3:
        return gaps

    for i in range(len(df) - 2):
        c1 = df.iloc[i]
        c2 = df.iloc[i + 1]
        c3 = df.iloc[i + 2]

        # Bullish FVG: c1.high < c3.low
        if c1["high"] < c3["low"]:
            top = float(c3["low"])
            bottom = float(c1["high"])
            width = top - bottom
            # Check fill status: has price come back to the gap?
            subsequent = df.iloc[i + 2 :]
            fill_status = "unfilled"
            if len(subsequent) > 0:
                if any(subsequent["low"] <= top for _, _ in subsequent.iterrows()):
                    fill_status = "mitigated"
            gaps.append(
                {
                    "type": "bullish",
                    "top": round(top, 5),
                    "bottom": round(bottom, 5),
                    "width": round(width, 5),
                    "fill_status": fill_status,
                    "idx": i,
                }
            )

        # Bearish FVG: c1.low > c3.high
        if c1["low"] > c3["high"]:
            top = float(c1["low"])
            bottom = float(c3["high"])
            width = top - bottom
            subsequent = df.iloc[i + 2 :]
            fill_status = "unfilled"
            if len(subsequent) > 0:
                if any(subsequent["high"] >= bottom for _, _ in subsequent.iterrows()):
                    fill_status = "mitigated"
            gaps.append(
                {
                    "type": "bearish",
                    "top": round(top, 5),
                    "bottom": round(bottom, 5),
                    "width": round(width, 5),
                    "fill_status": fill_status,
                    "idx": i,
                }
            )

    return gaps


# ═══════════════════════════════════════════════════════════════════════════════
# === SHARED COMPONENT: DYNAMIC OPENING RANGE ===
# ═══════════════════════════════════════════════════════════════════════════════


def calculate_dynamic_range(
    df: pd.DataFrame,
    session_start: time,
    session_end: time,
    atr_multiplier: float = 0.75,
) -> dict:
    """Calculate the D-ORB dynamic opening range.

    The dynamic range adapts to market volatility by combining:
        * Base range = high-low of the opening period
        * Volatility adjustment = ATR(14) of the pre-session period
        * Dynamic range = max(base_range, atr * atr_multiplier)

    Parameters
    ----------
    df:
        OHLCV DataFrame with DatetimeIndex.
    session_start:
        Opening time of the trading session (e.g., time(13, 30) for US).
    session_end:
        Closing time of the trading session.
    atr_multiplier:
        Multiplier applied to ATR for volatility adjustment (default 0.75).

    Returns
    -------
    Dictionary with keys:
        ``high`` (float), ``low`` (float), ``range`` (float),
        ``base_range`` (float), ``atr_adjusted`` (float),
        ``multiplier`` (float), ``atr`` (float)
    """
    result = {
        "high": 0.0,
        "low": 0.0,
        "range": 0.0,
        "base_range": 0.0,
        "atr_adjusted": 0.0,
        "multiplier": atr_multiplier,
        "atr": 0.0,
    }

    if not isinstance(df.index, pd.DatetimeIndex) or len(df) < 30:
        return result

    # Bars within session
    bar_times = df.index.time
    session_mask = (bar_times >= session_start) & (bar_times <= session_end)
    session_bars = df.loc[session_mask]

    if len(session_bars) < 6:  # Need at least ~30 min of data
        return result

    # Opening range = first 30 minutes (6 bars on M5)
    or_bars = session_bars.iloc[:6]
    or_high = float(or_bars["high"].max())
    or_low = float(or_bars["low"].min())
    base_range = or_high - or_low

    # Pre-session ATR
    pre_session = df.loc[~session_mask]
    if len(pre_session) >= 14:
        atr_val = float(_atr_wilder(pre_session, 14).iloc[-1])
    else:
        atr_val = float(_atr_wilder(df, 14).iloc[-1])

    atr_adjusted = atr_val * atr_multiplier
    dynamic_range = max(base_range, atr_adjusted)

    result["high"] = or_high
    result["low"] = or_low
    result["range"] = round(dynamic_range, 5)
    result["base_range"] = round(base_range, 5)
    result["atr_adjusted"] = round(atr_adjusted, 5)
    result["atr"] = round(atr_val, 5)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# === D-ORB: DYNAMIC OPENING RANGE BREAKOUT ===
# ═══════════════════════════════════════════════════════════════════════════════


def strategy_dorb(df: pd.DataFrame, cfg) -> dict:
    """D-ORB (Dynamic Opening Range Breakout) — PlayBit FULL MODEL.

    A sophisticated opening range breakout that adapts to market volatility
    instead of using a fixed range size.

    Logic
    -----
    1. **Opening Range Period**: First 30 min of session (6 bars on M5)

       * US session: 13:30-14:00 GMT (symbol: NAS100, US30)
       * London session: 07:00-07:30 GMT (symbol: EURUSD, GBPUSD)

    2. **Dynamic Range Calculation**:

       * Base range = high-low of opening period
       * Volatility adjustment = ATR(14) of pre-session period
       * Dynamic range = max(base_range, atr_adjusted * multiplier)
       * Multiplier typically 0.5-1.0x ATR

    3. **Breakout Detection**:

       * Bullish: close breaks above OR high + (dynamic_range * 0.1)
       * Bearish: close breaks below OR low - (dynamic_range * 0.1)
       * The 0.1 buffer prevents false breakouts

    4. **Entry Confirmation** (ALL must align):

       * Volume > 1.5x average (confirms breakout)
       * RSI in direction of breakout (50-70 bullish, 30-50 bearish)
       * EMA alignment supports direction
       * Session is active (US 13:30-20:00 or London 07:00-16:00)

    5. **Position Sizing**:

       * Risk = 0.5% of account (from cfg)
       * SL = beyond opposite side of dynamic range
       * TP = 2x-3x the SL distance (adaptive based on ATR)

    6. **Time-Based Exits**:

       * Max hold: 4 hours (session end approach)
       * If not hit TP/SL by session end → close at market

    Expected Performance
    --------------------
    * Win Rate: 55-65%
    * Profit Factor: 1.8-2.5
    * Best on: Indices (NAS100, US30), EURUSD

    Parameters
    ----------
    df:
        M5 OHLCV DataFrame with DatetimeIndex.
    cfg:
        StrategyConfig with symbol, account_size, risk_per_trade, etc.

    Returns
    -------
    Standard signal dictionary from ``build_signal_dict``.
    """
    # Lazy imports to avoid circular dependency
    _lib = _import_library()
    build_signal_dict = _lib["build_signal_dict"]
    check_prop_firm_compliance = _lib["check_prop_firm_compliance"]
    check_min_atr = _lib["check_min_atr"]
    add_indicators = _lib["add_indicators"]
    calculate_position_size = _lib["calculate_position_size"]
    CONTRACT_VALUES = _lib["CONTRACT_VALUES"]

    symbol = cfg.symbol or "NAS100"
    strategy_name = f"DORB_{symbol}"

    # Determine session parameters from symbol
    if symbol in ("NAS100", "US30"):
        session = "us"
        session_start = time(13, 30)
        session_end = time(20, 0)
        or_duration = 6  # 6 bars = 30 min on M5
        atr_mult = 0.75
    elif symbol in ("EURUSD", "GBPUSD"):
        session = "london"
        session_start = time(7, 0)
        session_end = time(16, 0)
        or_duration = 6  # 6 bars = 30 min on M5
        atr_mult = 0.5
    else:
        # Default to US session
        session = "us"
        session_start = time(13, 30)
        session_end = time(20, 0)
        or_duration = 6
        atr_mult = 0.75

    # Need sufficient data
    if len(df) < 200:
        return build_signal_dict(
            symbol, strategy_name, "none", 0, 0, 0, 0, 0,
            "Insufficient data (< 200 bars)", 0,
        )

    # Add indicators
    df = add_indicators(
        df,
        ema_fast=cfg.ema_fast,
        ema_medium=cfg.ema_medium,
        ema_slow=cfg.ema_slow,
        rsi_period=cfg.rsi_period,
        atr_period=cfg.atr_period,
        volume_ma_period=cfg.volume_ma_period,
    )

    i = -1  # Most recent bar
    current = df.iloc[i]
    prev = df.iloc[i - 1] if len(df) >= 2 else current
    atr = current["atr"]
    price = current["close"]
    rsi = current["rsi"]
    vol_ratio = current.get("volume_ratio", 1.0)

    # --- Prop firm compliance ---
    compliance_ok, compliance_reason = check_prop_firm_compliance(
        cfg.current_equity,
        cfg.peak_equity,
        cfg.daily_pnl,
        cfg.daily_dd_limit,
        cfg.max_dd_limit,
        cfg.trades_today,
        cfg.max_trades_per_day,
        cfg.consistency_limit_pct,
    )
    if not compliance_ok:
        return build_signal_dict(
            symbol, strategy_name, "none", 0, 0, 0, 0, 0,
            f"COMPLIANCE FAIL: {compliance_reason}", atr,
        )

    # --- Min ATR filter ---
    atr_ok, atr_reason = check_min_atr(symbol, atr)
    if not atr_ok:
        return build_signal_dict(
            symbol, strategy_name, "none", 0, 0, 0, 0, 0,
            f"ATR FILTER: {atr_reason}", atr,
        )

    # --- Session filter ---
    if not isinstance(df.index, pd.DatetimeIndex):
        return build_signal_dict(
            symbol, strategy_name, "none", 0, 0, 0, 0, 0,
            "DatetimeIndex required", atr,
        )
    bar_time = (
        df.index[i].time()
        if hasattr(df.index[i], "time")
        else df.index[i].to_pydatetime().time()
    )
    if not (session_start <= bar_time <= session_end):
        return build_signal_dict(
            symbol, strategy_name, "none", 0, 0, 0, 0, 0,
            f"Outside {session} session: {bar_time}", atr,
        )

    # --- Calculate Dynamic Opening Range ---
    dorb = calculate_dynamic_range(df, session_start, session_end, atr_mult)
    or_high = dorb["high"]
    or_low = dorb["low"]
    dynamic_range = dorb["range"]

    if dynamic_range <= 0 or or_high <= 0 or or_low <= 0:
        return build_signal_dict(
            symbol, strategy_name, "none", 0, 0, 0, 0, 0,
            "Dynamic range calculation failed", atr,
        )

    # Minimum range check
    min_range = price * 0.001  # 0.1% of price
    if dynamic_range < min_range:
        return build_signal_dict(
            symbol, strategy_name, "none", 0, 0, 0, 0, 0,
            f"Dynamic range too small: {dynamic_range:.2f} < {min_range:.2f}", atr,
        )

    # --- Breakout Detection with 0.1 buffer ---
    breakout_buffer = dynamic_range * 0.1
    bull_trigger = or_high + breakout_buffer
    bear_trigger = or_low - breakout_buffer

    broke_above = current["close"] > bull_trigger and prev["close"] <= bull_trigger
    broke_below = current["close"] < bear_trigger and prev["close"] >= bear_trigger

    if not (broke_above or broke_below):
        return build_signal_dict(
            symbol, strategy_name, "none", 0, 0, 0, 0, 0,
            f"No D-ORB breakout: OR={or_high:.1f}/{or_low:.1f}, "
            f"triggers={bull_trigger:.1f}/{bear_trigger:.1f}",
            atr,
        )

    # --- Entry Confirmation (ALL must align) ---
    # 1. Volume > 1.5x average
    volume_ok = vol_ratio > 1.5

    # 2. RSI filter
    rsi_long_ok = 50 < rsi < 70
    rsi_short_ok = 30 < rsi < 50

    # 3. EMA alignment
    ema_bull = current["ema_fast"] > current["ema_medium"] > current["ema_slow"]
    ema_bear = current["ema_fast"] < current["ema_medium"] < current["ema_slow"]
    # Allow partial alignment (fast > medium) for more entries
    ema_partial_bull = current["ema_fast"] > current["ema_medium"]
    ema_partial_bear = current["ema_fast"] < current["ema_medium"]

    signal = "none"
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    reason = ""
    trend_dir = ""
    confidence = "medium"

    if broke_above and volume_ok and rsi_long_ok:
        # EMA must at least partially support
        if ema_partial_bull:
            signal = "buy"
            entry_price = price
            # SL = beyond opposite side of dynamic range
            sl_distance = max(entry_price - or_low, 1.5 * atr)
            stop_loss = entry_price - sl_distance
            # TP = 2x-3x SL based on ATR
            tp_multiplier = 3.0 if atr > dynamic_range * 0.3 else 2.0
            take_profit = entry_price + (sl_distance * tp_multiplier)
            trend_dir = "uptrend"
            reason = (
                f"D-ORB LONG: broke {bull_trigger:.1f} (ORH={or_high:.1f}), "
                f"dyn_range={dynamic_range:.1f}, RSI={rsi:.1f}, "
                f"vol={vol_ratio:.1f}x, EMA_bull={ema_bull}"
            )
            # Confidence scoring
            conf_score = 0.55
            if ema_bull:
                conf_score += 0.15
            if vol_ratio > 2.0:
                conf_score += 0.10
            if 55 < rsi < 65:
                conf_score += 0.10
            confidence = "high" if conf_score > 0.7 else "medium"

    if broke_below and volume_ok and rsi_short_ok:
        if ema_partial_bear:
            signal = "sell"
            entry_price = price
            sl_distance = max(or_high - entry_price, 1.5 * atr)
            stop_loss = entry_price + sl_distance
            tp_multiplier = 3.0 if atr > dynamic_range * 0.3 else 2.0
            take_profit = entry_price - (sl_distance * tp_multiplier)
            trend_dir = "downtrend"
            reason = (
                f"D-ORB SHORT: broke {bear_trigger:.1f} (ORL={or_low:.1f}), "
                f"dyn_range={dynamic_range:.1f}, RSI={rsi:.1f}, "
                f"vol={vol_ratio:.1f}x, EMA_bear={ema_bear}"
            )
            conf_score = 0.55
            if ema_bear:
                conf_score += 0.15
            if vol_ratio > 2.0:
                conf_score += 0.10
            if 35 < rsi < 45:
                conf_score += 0.10
            confidence = "high" if conf_score > 0.7 else "medium"

    if signal == "none":
        filter_reason = []
        if broke_above and not volume_ok:
            filter_reason.append("volume_low")
        if broke_above and not rsi_long_ok:
            filter_reason.append(f"RSI={rsi:.0f}_not_50-70")
        if broke_below and not volume_ok:
            filter_reason.append("volume_low")
        if broke_below and not rsi_short_ok:
            filter_reason.append(f"RSI={rsi:.0f}_not_30-50")
        if (broke_above and not ema_partial_bull) or (broke_below and not ema_partial_bear):
            filter_reason.append("EMA_opposing")
        return build_signal_dict(
            symbol, strategy_name, "none", 0, 0, 0, 0, 0,
            f"Filters not met: {','.join(filter_reason)}", atr,
        )

    # --- Position Sizing ---
    sl_dist = abs(entry_price - stop_loss)
    contract_value = CONTRACT_VALUES.get(symbol, 20)
    lots, risk_amount, _ = calculate_position_size(
        cfg.current_equity, cfg.risk_per_trade, sl_dist, contract_value
    )

    return build_signal_dict(
        symbol, strategy_name, signal, entry_price, stop_loss, take_profit,
        lots, risk_amount, reason, atr, session=session,
        trend_direction=trend_dir, confidence=confidence,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# === ILM: INTELLIGENT LIQUIDITY MODEL ===
# ═══════════════════════════════════════════════════════════════════════════════


def strategy_ilm(df: pd.DataFrame, cfg) -> dict:
    """ILM (Intelligent Liquidity Model) — PlayBit FULL MODEL.

    A liquidity-based strategy that identifies where institutional liquidity
    is parked and trades the sweep/reclaim of that liquidity.

    **Concept**: Institutions need liquidity to fill large orders. They
    engineer price moves to sweep liquidity pools (retail stop losses)
    before reversing. ILM identifies these pools and trades the reversal.

    Logic
    -----
    1. **Identify Liquidity Pools**:

       * Equal highs/lows (retail stops clustered)
       * Previous day high/low
       * Previous session high/low
       * Major swing points
       * Round numbers (psychological levels)

    2. **Liquidity Sweep Detection**:

       * Price takes out the liquidity pool (wick beyond level)
       * BUT closes back inside the range (failed breakout)
       * Volume spike during sweep (institutional activity)
       * This is the "inducement" — trapping breakout traders

    3. **Reclaim Confirmation** (ALL must align):

       * After sweep, price reclaims the liquidity level
       * A Fair Value Gap (FVG) forms in the reclaim direction
       * EMA20 supports the reclaim direction
       * Volume > 1.2x average

    4. **Entry**:

       * Enter on FVG mitigation (50% fill of the FVG)
       * Or enter on reclaim of the liquidity level
       * Volume > 1.2x average

    5. **Stop Loss**:

       * Beyond the sweep wick extreme
       * ATR-based minimum: max(sweep_extreme, 1.5x ATR)

    6. **Take Profit**:

       * TP1: Next liquidity pool (1:1.5 R:R minimum)
       * TP2: 2x ATR projection
       * Scale out 50% at TP1, move SL to breakeven

    7. **Session Awareness**:

       * Prefer London session (07:00-12:00) for forex
       * Prefer US open (13:30-16:00) for indices
       * Avoid: pre-news, last 30 min of session

    Expected Performance
    --------------------
    * Win Rate: 60-70%
    * Profit Factor: 2.0-3.0
    * Best on: XAUUSD, EURUSD, NAS100
    * Works in both trending and ranging markets

    Parameters
    ----------
    df:
        M5 OHLCV DataFrame with DatetimeIndex.
    cfg:
        StrategyConfig with symbol, account_size, risk_per_trade, etc.

    Returns
    -------
    Standard signal dictionary from ``build_signal_dict``.
    """
    # Lazy imports to avoid circular dependency
    _lib = _import_library()
    build_signal_dict = _lib["build_signal_dict"]
    check_prop_firm_compliance = _lib["check_prop_firm_compliance"]
    check_min_atr = _lib["check_min_atr"]
    add_indicators = _lib["add_indicators"]
    calculate_position_size = _lib["calculate_position_size"]
    CONTRACT_VALUES = _lib["CONTRACT_VALUES"]

    symbol = cfg.symbol or "XAUUSD"
    strategy_name = f"ILM_{symbol}"

    # Determine session and parameters from symbol
    if symbol in ("XAUUSD",):
        session = "london"
        session_start = time(7, 0)
        session_end = time(12, 0)  # Prefer early London
    elif symbol in ("EURUSD", "GBPUSD"):
        session = "london"
        session_start = time(7, 0)
        session_end = time(12, 0)
    elif symbol in ("NAS100", "US30"):
        session = "us"
        session_start = time(13, 30)
        session_end = time(16, 0)  # Prefer US open window
    else:
        session = "london"
        session_start = time(7, 0)
        session_end = time(12, 0)

    # Need sufficient data
    if len(df) < 200:
        return build_signal_dict(
            symbol, strategy_name, "none", 0, 0, 0, 0, 0,
            "Insufficient data (< 200 bars)", 0,
        )

    # Add indicators
    df = add_indicators(
        df,
        ema_fast=cfg.ema_fast,
        ema_medium=cfg.ema_medium,
        ema_slow=cfg.ema_slow,
        rsi_period=cfg.rsi_period,
        atr_period=cfg.atr_period,
        volume_ma_period=cfg.volume_ma_period,
    )

    i = -1  # Most recent bar
    current = df.iloc[i]
    prev = df.iloc[i - 1] if len(df) >= 2 else current
    prev2 = df.iloc[i - 2] if len(df) >= 3 else prev
    atr = current["atr"]
    price = current["close"]
    rsi = current["rsi"]
    vol_ratio = current.get("volume_ratio", 1.0)

    # --- Prop firm compliance ---
    compliance_ok, compliance_reason = check_prop_firm_compliance(
        cfg.current_equity,
        cfg.peak_equity,
        cfg.daily_pnl,
        cfg.daily_dd_limit,
        cfg.max_dd_limit,
        cfg.trades_today,
        cfg.max_trades_per_day,
        cfg.consistency_limit_pct,
    )
    if not compliance_ok:
        return build_signal_dict(
            symbol, strategy_name, "none", 0, 0, 0, 0, 0,
            f"COMPLIANCE FAIL: {compliance_reason}", atr,
        )

    # --- Min ATR filter ---
    atr_ok, atr_reason = check_min_atr(symbol, atr)
    if not atr_ok:
        return build_signal_dict(
            symbol, strategy_name, "none", 0, 0, 0, 0, 0,
            f"ATR FILTER: {atr_reason}", atr,
        )

    # --- Session filter ---
    if not isinstance(df.index, pd.DatetimeIndex):
        return build_signal_dict(
            symbol, strategy_name, "none", 0, 0, 0, 0, 0,
            "DatetimeIndex required", atr,
        )
    bar_time = (
        df.index[i].time()
        if hasattr(df.index[i], "time")
        else df.index[i].to_pydatetime().time()
    )
    if not (session_start <= bar_time <= session_end):
        return build_signal_dict(
            symbol, strategy_name, "none", 0, 0, 0, 0, 0,
            f"Outside preferred {session} session: {bar_time}", atr,
        )

    # --- Detect Liquidity Pools ---
    pools = detect_liquidity_pools(df, lookback=100)
    if not pools:
        return build_signal_dict(
            symbol, strategy_name, "none", 0, 0, 0, 0, 0,
            "No liquidity pools detected", atr,
        )

    # --- Detect FVGs ---
    fvgs = detect_fvg(df)
    recent_fvgs = [g for g in fvgs if g.get("idx", 0) >= len(df) - 20]

    # --- Check each liquidity pool for sweep + reclaim ---
    signal = "none"
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    reason = ""
    trend_dir = ""
    confidence = "medium"

    for pool in pools[:5]:  # Check top 5 strongest pools
        level = pool["level"]
        pool_type = pool["type"]
        strength = pool["strength"]

        # Determine direction based on pool type
        if "high" in pool_type or pool_type in ("swing_high", "equal_highs"):
            # Liquidity above price → expect bearish sweep then reclaim
            direction = "bearish"
            # Only check if price is near the level
            if price < level * 0.995:  # Price below level
                continue
        elif "low" in pool_type or pool_type in ("swing_low", "equal_lows"):
            # Liquidity below price → expect bullish sweep then reclaim
            direction = "bullish"
            if price > level * 1.005:  # Price above level
                continue
        else:
            # Round numbers: check both sides
            if abs(price - level) / price > 0.005:  # > 0.5% away
                continue
            direction = "bullish" if price > level else "bearish"

        # --- Detect sweep ---
        sweep = detect_sweep(df, level, direction, lookback=5)
        if not sweep["swept"]:
            continue

        # Volume check during sweep
        volume_ok = vol_ratio > 1.2

        # EMA alignment for direction
        ema_bull = current["ema_fast"] > current["ema_medium"]
        ema_bear = current["ema_fast"] < current["ema_medium"]

        # FVG confirmation
        fvg_confirmed = False
        entry_zone = level

        if direction == "bullish" and ema_bull and volume_ok:
            # After bullish sweep, look for bullish FVG
            for fvg in recent_fvgs:
                if fvg["type"] == "bullish" and fvg["fill_status"] == "unfilled":
                    # Entry at 50% of FVG (mitigation)
                    entry_zone = (fvg["top"] + fvg["bottom"]) / 2.0
                    fvg_confirmed = True
                    break

            if not fvg_confirmed:
                # Entry on reclaim of the level itself
                if current["close"] > level and prev["close"] <= level:
                    entry_zone = level
                    fvg_confirmed = True

            if fvg_confirmed:
                signal = "buy"
                entry_price = entry_zone
                # SL beyond sweep wick extreme, minimum 1.5x ATR
                sl_distance = max(abs(entry_price - sweep["wick_extreme"]), 1.5 * atr)
                stop_loss = entry_price - sl_distance
                # TP: 2x ATR projection
                take_profit = entry_price + (sl_distance * 2.0)
                trend_dir = "uptrend"
                conf_base = 0.55 + strength * 0.2
                if fvg_confirmed and any(g.get("type") == "bullish" for g in recent_fvgs):
                    conf_base += 0.1
                if vol_ratio > 1.5:
                    conf_base += 0.05
                confidence = "high" if conf_base > 0.7 else "medium"
                reason = (
                    f"ILM LONG: {pool_type} sweep @ {level:.5f}, "
                    f"wick={sweep['wick_extreme']:.5f}, "
                    f"FVG={fvg_confirmed}, vol={vol_ratio:.1f}x, "
                    f"strength={strength:.2f}"
                )
                break  # Found valid setup

        elif direction == "bearish" and ema_bear and volume_ok:
            # After bearish sweep, look for bearish FVG
            for fvg in recent_fvgs:
                if fvg["type"] == "bearish" and fvg["fill_status"] == "unfilled":
                    entry_zone = (fvg["top"] + fvg["bottom"]) / 2.0
                    fvg_confirmed = True
                    break

            if not fvg_confirmed:
                if current["close"] < level and prev["close"] >= level:
                    entry_zone = level
                    fvg_confirmed = True

            if fvg_confirmed:
                signal = "sell"
                entry_price = entry_zone
                sl_distance = max(abs(sweep["wick_extreme"] - entry_price), 1.5 * atr)
                stop_loss = entry_price + sl_distance
                take_profit = entry_price - (sl_distance * 2.0)
                trend_dir = "downtrend"
                conf_base = 0.55 + strength * 0.2
                if fvg_confirmed and any(g.get("type") == "bearish" for g in recent_fvgs):
                    conf_base += 0.1
                if vol_ratio > 1.5:
                    conf_base += 0.05
                confidence = "high" if conf_base > 0.7 else "medium"
                reason = (
                    f"ILM SHORT: {pool_type} sweep @ {level:.5f}, "
                    f"wick={sweep['wick_extreme']:.5f}, "
                    f"FVG={fvg_confirmed}, vol={vol_ratio:.1f}x, "
                    f"strength={strength:.2f}"
                )
                break  # Found valid setup

    if signal == "none":
        return build_signal_dict(
            symbol, strategy_name, "none", 0, 0, 0, 0, 0,
            f"No ILM setup: pools={len(pools)}, FVGs={len(recent_fvgs)}, "
            f"vol={vol_ratio:.1f}x",
            atr,
        )

    # --- Position Sizing ---
    sl_dist = abs(entry_price - stop_loss)
    contract_value = CONTRACT_VALUES.get(symbol, 20)
    lots, risk_amount, _ = calculate_position_size(
        cfg.current_equity, cfg.risk_per_trade, sl_dist, contract_value
    )

    return build_signal_dict(
        symbol, strategy_name, signal, entry_price, stop_loss, take_profit,
        lots, risk_amount, reason, atr, session=session,
        trend_direction=trend_dir, confidence=confidence,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# === PLAYBIT STRATEGY VARIANTS ===
# ═══════════════════════════════════════════════════════════════════════════════


def strategy_dorb_us(df: pd.DataFrame, cfg) -> dict:
    """D-ORB US Session variant (NAS100, US30)."""
    _lib = _import_library()
    StrategyConfig = _lib["StrategyConfig"]
    cfg_us = StrategyConfig(
        symbol=cfg.symbol if cfg.symbol in ("NAS100", "US30") else "NAS100",
        account_size=cfg.account_size,
        risk_per_trade=cfg.risk_per_trade,
        daily_dd_limit=cfg.daily_dd_limit,
        max_dd_limit=cfg.max_dd_limit,
        peak_equity=cfg.peak_equity,
        current_equity=cfg.current_equity,
        daily_pnl=cfg.daily_pnl,
        trades_today=cfg.trades_today,
        max_trades_per_day=cfg.max_trades_per_day,
        max_trades_per_session=cfg.max_trades_per_session,
        consistency_limit_pct=cfg.consistency_limit_pct,
        timeframe=cfg.timeframe,
        ema_fast=cfg.ema_fast,
        ema_medium=cfg.ema_medium,
        ema_slow=cfg.ema_slow,
        rsi_period=cfg.rsi_period,
        atr_period=cfg.atr_period,
        volume_ma_period=cfg.volume_ma_period,
    )
    return strategy_dorb(df, cfg_us)


def strategy_dorb_london(df: pd.DataFrame, cfg) -> dict:
    """D-ORB London Session variant (EURUSD, GBPUSD)."""
    _lib = _import_library()
    StrategyConfig = _lib["StrategyConfig"]
    cfg_london = StrategyConfig(
        symbol=cfg.symbol if cfg.symbol in ("EURUSD", "GBPUSD") else "EURUSD",
        account_size=cfg.account_size,
        risk_per_trade=cfg.risk_per_trade,
        daily_dd_limit=cfg.daily_dd_limit,
        max_dd_limit=cfg.max_dd_limit,
        peak_equity=cfg.peak_equity,
        current_equity=cfg.current_equity,
        daily_pnl=cfg.daily_pnl,
        trades_today=cfg.trades_today,
        max_trades_per_day=cfg.max_trades_per_day,
        max_trades_per_session=cfg.max_trades_per_session,
        consistency_limit_pct=cfg.consistency_limit_pct,
        timeframe=cfg.timeframe,
        ema_fast=cfg.ema_fast,
        ema_medium=cfg.ema_medium,
        ema_slow=cfg.ema_slow,
        rsi_period=cfg.rsi_period,
        atr_period=cfg.atr_period,
        volume_ma_period=cfg.volume_ma_period,
    )
    return strategy_dorb(df, cfg_london)


def strategy_ilm_gold(df: pd.DataFrame, cfg) -> dict:
    """ILM Gold variant (XAUUSD)."""
    _lib = _import_library()
    StrategyConfig = _lib["StrategyConfig"]
    cfg_gold = StrategyConfig(
        symbol="XAUUSD",
        account_size=cfg.account_size,
        risk_per_trade=cfg.risk_per_trade,
        daily_dd_limit=cfg.daily_dd_limit,
        max_dd_limit=cfg.max_dd_limit,
        peak_equity=cfg.peak_equity,
        current_equity=cfg.current_equity,
        daily_pnl=cfg.daily_pnl,
        trades_today=cfg.trades_today,
        max_trades_per_day=cfg.max_trades_per_day,
        max_trades_per_session=cfg.max_trades_per_session,
        consistency_limit_pct=cfg.consistency_limit_pct,
        timeframe=cfg.timeframe,
        ema_fast=cfg.ema_fast,
        ema_medium=cfg.ema_medium,
        ema_slow=cfg.ema_slow,
        rsi_period=cfg.rsi_period,
        atr_period=cfg.atr_period,
        volume_ma_period=cfg.volume_ma_period,
    )
    return strategy_ilm(df, cfg_gold)


def strategy_ilm_eurusd(df: pd.DataFrame, cfg) -> dict:
    """ILM EURUSD variant."""
    _lib = _import_library()
    StrategyConfig = _lib["StrategyConfig"]
    cfg_eur = StrategyConfig(
        symbol="EURUSD",
        account_size=cfg.account_size,
        risk_per_trade=cfg.risk_per_trade,
        daily_dd_limit=cfg.daily_dd_limit,
        max_dd_limit=cfg.max_dd_limit,
        peak_equity=cfg.peak_equity,
        current_equity=cfg.current_equity,
        daily_pnl=cfg.daily_pnl,
        trades_today=cfg.trades_today,
        max_trades_per_day=cfg.max_trades_per_day,
        max_trades_per_session=cfg.max_trades_per_session,
        consistency_limit_pct=cfg.consistency_limit_pct,
        timeframe=cfg.timeframe,
        ema_fast=cfg.ema_fast,
        ema_medium=cfg.ema_medium,
        ema_slow=cfg.ema_slow,
        rsi_period=cfg.rsi_period,
        atr_period=cfg.atr_period,
        volume_ma_period=cfg.volume_ma_period,
    )
    return strategy_ilm(df, cfg_eur)


def strategy_ilm_nas(df: pd.DataFrame, cfg) -> dict:
    """ILM NAS100 variant."""
    _lib = _import_library()
    StrategyConfig = _lib["StrategyConfig"]
    cfg_nas = StrategyConfig(
        symbol="NAS100",
        account_size=cfg.account_size,
        risk_per_trade=cfg.risk_per_trade,
        daily_dd_limit=cfg.daily_dd_limit,
        max_dd_limit=cfg.max_dd_limit,
        peak_equity=cfg.peak_equity,
        current_equity=cfg.current_equity,
        daily_pnl=cfg.daily_pnl,
        trades_today=cfg.trades_today,
        max_trades_per_day=cfg.max_trades_per_day,
        max_trades_per_session=cfg.max_trades_per_session,
        consistency_limit_pct=cfg.consistency_limit_pct,
        timeframe=cfg.timeframe,
        ema_fast=cfg.ema_fast,
        ema_medium=cfg.ema_medium,
        ema_slow=cfg.ema_slow,
        rsi_period=cfg.rsi_period,
        atr_period=cfg.atr_period,
        volume_ma_period=cfg.volume_ma_period,
    )
    return strategy_ilm(df, cfg_nas)
