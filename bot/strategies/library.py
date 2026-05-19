"""
Comprehensive Strategy Library for Prop Firm Trading
====================================================
Covers 15+ instruments across Indices, Crypto, Commodities, and Forex.
Multiple strategy types: scalping, day trading (breakout), swing trend following.
All strategies include prop firm compliance checks and ATR-based risk management.
"""

# ── Imports ──
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, Tuple, List, Callable
from dataclasses import dataclass, field
from datetime import datetime, time
import warnings

warnings.filterwarnings("ignore")

# ── Contract Values ($ per $1 move per standard lot) ──
CONTRACT_VALUES = {
    "XAUUSD": 100,      # $100 per $1 per lot
    "NAS100": 20,       # $20 per point per lot
    "US30": 5,          # $5 per point per lot
    "BTCUSD": 1,        # $1 per $1 per lot
    "ETHUSD": 1,
    "SOLUSD": 1,
    "DOGEUSD": 1,
    "XRPUSD": 1,
    "LTCUSD": 1,
    "XTIUSD": 1000,     # 1000 barrels per lot
    "EURUSD": 100_000,
    "USDJPY": 100_000,
    "GBPJPY": 100_000,
    "GBPUSD": 100_000,
    "USDCHF": 100_000,
}

# ── Session Hours (GMT) ──
SESSION_HOURS = {
    "asian": {"start": time(0, 0), "end": time(8, 0)},      # 00:00-08:00 GMT
    "london": {"start": time(8, 0), "end": time(16, 0)},    # 08:00-16:00 GMT
    "us": {"start": time(13, 0), "end": time(21, 0)},       # 13:00-21:00 GMT
    "london_ny_overlap": {"start": time(13, 0), "end": time(16, 0)},
}

# ── Instrument-Specific Session Mapping ──
INSTRUMENT_SESSIONS = {
    "NAS100": ["us"],
    "US30": ["us"],
    "BTCUSD": ["asian", "london", "us"],   # 24/7 - all sessions
    "ETHUSD": ["asian", "london", "us"],
    "SOLUSD": ["asian", "london", "us"],
    "DOGEUSD": ["asian", "london", "us"],
    "XRPUSD": ["asian", "london", "us"],
    "LTCUSD": ["asian", "london", "us"],
    "XAUUSD": ["london", "us"],
    "XTIUSD": ["us"],
    "EURUSD": ["london", "london_ny_overlap"],
    "USDJPY": ["asian", "london"],
    "GBPJPY": ["london", "london_ny_overlap"],
    "GBPUSD": ["london", "london_ny_overlap"],
    "USDCHF": ["london", "us"],
}

# ── Minimum ATR Filters (in price terms, skip if ATR below this) ──
MIN_ATR = {
    "NAS100": 15.0,
    "US30": 50.0,
    "BTCUSD": 150.0,
    "ETHUSD": 10.0,
    "SOLUSD": 0.50,
    "DOGEUSD": 0.002,
    "XRPUSD": 0.01,
    "LTCUSD": 1.0,
    "XAUUSD": 2.0,
    "XTIUSD": 0.30,
    "EURUSD": 0.0005,
    "USDJPY": 0.05,
    "GBPJPY": 0.10,
    "GBPUSD": 0.001,
    "USDCHF": 0.001,
}

# ── Default Spread Estimates (in price terms) ──
DEFAULT_SPREADS = {
    "NAS100": 1.5,
    "US30": 3.0,
    "BTCUSD": 15.0,
    "ETHUSD": 1.5,
    "SOLUSD": 0.05,
    "DOGEUSD": 0.0002,
    "XRPUSD": 0.001,
    "LTCUSD": 0.10,
    "XAUUSD": 0.30,
    "XTIUSD": 0.03,
    "EURUSD": 0.0001,
    "USDJPY": 0.010,
    "GBPJPY": 0.020,
    "GBPUSD": 0.0002,
    "USDCHF": 0.0002,
}


# ── Strategy Configuration Dataclass ──
@dataclass
class StrategyConfig:
    """Configuration for all strategies."""
    symbol: str
    account_size: float = 10_000.0
    risk_per_trade: float = 0.005        # 0.5% per trade
    daily_dd_limit: float = 0.03         # 3% daily drawdown limit
    max_dd_limit: float = 0.06           # 6% max drawdown limit
    peak_equity: float = None            # Track peak for DD calculation
    current_equity: float = None         # Current equity
    daily_pnl: float = 0.0               # Today's PnL
    trades_today: int = 0                # Trade counter today
    max_trades_per_day: int = 5          # Max trades per day across all strategies
    max_trades_per_session: int = 2      # Max trades per session
    consistency_limit_pct: float = 0.35  # No single day >35% of profits
    timeframe: str = "M5"                # Default 5-minute timeframe
    # Swing-specific
    max_trades_per_2days: int = 1        # For swing strategies
    # Strategy-specific parameters
    ema_fast: int = 20
    ema_medium: int = 50
    ema_slow: int = 200
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    atr_period: int = 14
    atr_multiplier_sl: float = 1.5       # Will be overridden per strategy
    atr_multiplier_tp: float = 3.0       # Will be overridden per strategy
    volume_ma_period: int = 20
    # ORB-specific
    orb_lookback_bars: int = 20          # 20 bars = ~2 hours on M5
    orb_range_pct: float = 0.3           # Min range as % of price
    # Internal state
    _trade_history: list = field(default_factory=list)
    _daily_trades: Dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        if self.peak_equity is None:
            self.peak_equity = self.account_size
        if self.current_equity is None:
            self.current_equity = self.account_size


# ── Indicator Helpers ──
def add_indicators(df: pd.DataFrame,
                   ema_fast: int = 20,
                   ema_medium: int = 50,
                   ema_slow: int = 200,
                   rsi_period: int = 14,
                   atr_period: int = 14,
                   bb_period: int = 20,
                   bb_std: float = 2.0,
                   macd_fast: int = 12,
                   macd_slow: int = 26,
                   macd_signal: int = 9,
                   volume_ma_period: int = 20) -> pd.DataFrame:
    """
    Add EMA, RSI, ATR, Volume MA, Bollinger Bands, MACD to dataframe.
    Expects columns: open, high, low, close, volume (all lowercase).
    """
    df = df.copy()

    # Ensure lowercase columns
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df.columns:
            df[col.lower()] = df[col]

    required = ["open", "high", "low", "close"]
    for r in required:
        if r not in df.columns:
            raise ValueError(f"Missing required column: {r}")

    # EMAs
    df["ema_fast"] = df["close"].ewm(span=ema_fast, adjust=False).mean()
    df["ema_medium"] = df["close"].ewm(span=ema_medium, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=ema_slow, adjust=False).mean()

    # RSI
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / rsi_period, min_periods=rsi_period).mean()
    avg_loss = loss.ewm(alpha=1.0 / rsi_period, min_periods=rsi_period).mean()
    rs = avg_gain / avg_loss
    df["rsi"] = 100.0 - (100.0 / (1.0 + rs))

    # ATR (Average True Range)
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1.0 / atr_period, min_periods=atr_period).mean()

    # ATR in pips/points (for logging)
    df["atr_points"] = df["atr"]

    # Bollinger Bands
    df["bb_middle"] = df["close"].rolling(window=bb_period).mean()
    bb_std_dev = df["close"].rolling(window=bb_period).std()
    df["bb_upper"] = df["bb_middle"] + bb_std * bb_std_dev
    df["bb_lower"] = df["bb_middle"] - bb_std * bb_std_dev
    df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_middle"]
    df["bb_pct"] = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"])

    # MACD
    ema_macd_fast = df["close"].ewm(span=macd_fast, adjust=False).mean()
    ema_macd_slow = df["close"].ewm(span=macd_slow, adjust=False).mean()
    df["macd"] = ema_macd_fast - ema_macd_slow
    df["macd_signal"] = df["macd"].ewm(span=macd_signal, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]

    # Volume MA
    if "volume" in df.columns:
        df["volume_ma"] = df["volume"].rolling(window=volume_ma_period).mean()
        df["volume_ratio"] = df["volume"] / df["volume_ma"]
    else:
        df["volume"] = 1000.0
        df["volume_ma"] = 1000.0
        df["volume_ratio"] = 1.0

    # Trend detection
    df["trend_up"] = (df["ema_fast"] > df["ema_medium"]) & (df["ema_medium"] > df["ema_slow"])
    df["trend_down"] = (df["ema_fast"] < df["ema_medium"]) & (df["ema_medium"] < df["ema_slow"])

    return df


def get_session_mask(df: pd.DataFrame, session: str) -> pd.Series:
    """
    Return boolean mask for rows within a given session.
    Expects df index to be DatetimeIndex.
    """
    if not isinstance(df.index, pd.DatetimeIndex):
        raise ValueError("DataFrame index must be DatetimeIndex")
    s = SESSION_HOURS.get(session)
    if s is None:
        return pd.Series(True, index=df.index)
    times = df.index.time
    mask = (times >= s["start"]) & (times <= s["end"])
    return mask


# ── Prop Firm Compliance ──
def check_prop_firm_compliance(
    equity: float,
    peak: float,
    daily_pnl: float,
    daily_dd_limit: float = 0.03,
    max_dd_limit: float = 0.06,
    daily_trades: int = 0,
    max_trades_per_day: int = 5,
    consistency_limit_pct: float = 0.35,
    total_profit: float = 0.0,
    best_day_profit: float = 0.0,
) -> Tuple[bool, str]:
    """
    Check if a new trade would violate prop firm rules.
    Returns: (allowed: bool, reason: str)
    """
    # 1. Check max drawdown limit (>80% of limit used)
    max_dd_used = (peak - equity) / peak if peak > 0 else 0
    if max_dd_used > max_dd_limit * 0.80:
        return False, (
            f"MAX DD EXCEEDED: {max_dd_used:.2%} used "
            f"(limit {max_dd_limit:.0%}, 80% threshold {max_dd_limit * 0.80:.1%})"
        )

    # 2. Check daily drawdown limit
    daily_dd = -daily_pnl / peak if daily_pnl < 0 else 0
    if daily_dd > daily_dd_limit * 0.80:
        return False, (
            f"DAILY DD EXCEEDED: {daily_dd:.2%} today "
            f"(limit {daily_dd_limit:.0%}, 80% threshold {daily_dd_limit * 0.80:.1%})"
        )

    # 3. Check max trades per day
    if daily_trades >= max_trades_per_day:
        return False, f"MAX TRADES TODAY: {daily_trades}/{max_trades_per_day}"

    # 4. Check consistency score (no single day >35% of profits)
    if total_profit > 0 and best_day_profit > 0:
        consistency_score = best_day_profit / total_profit
        if consistency_score > consistency_limit_pct:
            return False, (
                f"CONSISTENCY VIOLATION: best day = "
                f"{consistency_score:.1%} of profits (limit {consistency_limit_pct:.0%})"
            )

    return True, "PASS"


def check_min_atr(symbol: str, current_atr: float) -> Tuple[bool, str]:
    """
    Check if ATR is sufficient for trading (spread won't eat the trade).
    """
    min_atr = MIN_ATR.get(symbol, 0.0)
    spread = DEFAULT_SPREADS.get(symbol, 0.0)
    if min_atr <= 0:
        return True, "PASS (no minimum)"
    if current_atr < min_atr:
        return False, f"ATR TOO LOW: {current_atr:.4f} < {min_atr:.4f} minimum"
    # Check ATR is at least 3x spread (trade must have room)
    if current_atr < spread * 3:
        return False, f"ATR < 3x SPREAD: {current_atr:.4f} vs spread {spread:.4f}"
    return True, f"PASS (ATR={current_atr:.4f})"


def calculate_position_size(
    balance: float,
    risk_pct: float,
    stop_distance: float,
    contract_value: float,
    max_position_pct: float = 0.10,      # Max 10% of balance in margin
) -> Tuple[float, float, float]:
    """
    Calculate position size in lots based on risk.

    Parameters:
        balance: Account balance
        risk_pct: Risk per trade (0.005 = 0.5%)
        stop_distance: Stop loss distance in price terms
        contract_value: $ per $1 move per lot
        max_position_pct: Maximum position as % of balance

    Returns:
        (lots, risk_amount, notional_exposure)
    """
    if stop_distance <= 0 or contract_value <= 0:
        return 0.0, 0.0, 0.0

    risk_amount = balance * risk_pct
    lots = risk_amount / (stop_distance * contract_value)

    # Enforce max position size
    max_position_value = balance * max_position_pct
    max_lots_by_position = max_position_value / contract_value if contract_value > 0 else 0
    lots = min(lots, max_lots_by_position)

    # Round to 2 decimal places for standard lots
    lots = round(lots, 2)

    if lots < 0.01:
        lots = 0.01  # Minimum lot size

    risk_amount = lots * stop_distance * contract_value
    notional = lots * contract_value

    return lots, risk_amount, notional


def build_signal_dict(
    symbol: str,
    strategy_name: str,
    signal: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    lots: float,
    risk_amount: float,
    reason: str,
    atr: float,
    session: str = "",
    trend_direction: str = "",
    confidence: str = "medium",
) -> Dict[str, Any]:
    """
    Build a standardized signal/metrics dictionary.
    signal: 'buy', 'sell', or 'none'
    """
    risk_reward = 0.0
    if stop_loss > 0 and entry_price > 0:
        sl_distance = abs(entry_price - stop_loss)
        tp_distance = abs(take_profit - entry_price)
        risk_reward = tp_distance / sl_distance if sl_distance > 0 else 0.0

    return {
        "symbol": symbol,
        "strategy": strategy_name,
        "signal": signal,                    # 'buy', 'sell', 'none'
        "entry_price": round(entry_price, 5) if entry_price > 0 else 0,
        "stop_loss": round(stop_loss, 5) if stop_loss > 0 else 0,
        "take_profit": round(take_profit, 5) if take_profit > 0 else 0,
        "lots": lots,
        "risk_amount": round(risk_amount, 2),
        "risk_reward": round(risk_reward, 2),
        "atr": round(atr, 5) if atr > 0 else 0,
        "reason": reason,
        "session": session,
        "trend_direction": trend_direction,
        "confidence": confidence,
        "timestamp": datetime.utcnow().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════
# === INDEX STRATEGIES ===
# ═══════════════════════════════════════════════════════════════

def strategy_nas100_orb(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """
    NAS100 Opening Range Breakout (Day Trading)
    ============================================
    Session: US Open 13:00-16:00 GMT (primary)
    Signal: Price breaks 20-bar (100-min) opening range after US open.
    SL: 1.5x ATR, TP: 3.0x ATR (1:2 R:R)
    Entry: Break above/below OR high/low with volume confirmation.
    Risk: 0.5% per trade, max 1 trade per day.
    """
    symbol = cfg.symbol or "NAS100"
    strategy_name = "NAS100_ORB"

    # Need sufficient data
    if len(df) < 200:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0, "Insufficient data (< 200 bars)", 0)

    df = add_indicators(df, ema_fast=cfg.ema_fast, ema_medium=cfg.ema_medium,
                        ema_slow=cfg.ema_slow, rsi_period=cfg.rsi_period,
                        atr_period=cfg.atr_period)

    i = -1  # Current (most recent) bar
    current = df.iloc[i]
    prev = df.iloc[i - 1]
    atr = current["atr"]
    price = current["close"]

    # Prop firm compliance
    compliance_ok, compliance_reason = check_prop_firm_compliance(
        cfg.current_equity, cfg.peak_equity, cfg.daily_pnl,
        cfg.daily_dd_limit, cfg.max_dd_limit,
        cfg.trades_today, cfg.max_trades_per_day,
        cfg.consistency_limit_pct,
    )
    if not compliance_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"COMPLIANCE FAIL: {compliance_reason}", atr)

    # Min ATR filter
    atr_ok, atr_reason = check_min_atr(symbol, atr)
    if not atr_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"ATR FILTER: {atr_reason}", atr)

    # Session filter: US session only
    if not isinstance(df.index, pd.DatetimeIndex):
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "DatetimeIndex required", atr)
    bar_time = df.index[i].time() if hasattr(df.index[i], "time") else df.index[i].to_pydatetime().time()
    us_start = SESSION_HOURS["us"]["start"]
    us_end = SESSION_HOURS["us"]["end"]
    if not (us_start <= bar_time <= us_end):
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"Outside US session: {bar_time}", atr)

    # Opening Range calculation: last N bars before current
    orb_bars = cfg.orb_lookback_bars  # 20 bars = 100 min on M5
    if len(df) < orb_bars + 10:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data for ORB", atr)

    # Use the range from the orb_bars preceding the current bar
    orb_window = df.iloc[-(orb_bars + 1):-1]
    orb_high = orb_window["high"].max()
    orb_low = orb_window["low"].min()
    orb_range = orb_high - orb_low

    # Minimum range check: must be > 0.3% of price
    min_range = price * cfg.orb_range_pct
    if orb_range < min_range:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"ORB range too small: {orb_range:.2f} < {min_range:.2f}", atr)

    # Check for breakout on current or previous bar
    broke_above = current["high"] > orb_high and prev["high"] <= orb_high
    broke_below = current["low"] < orb_low and prev["low"] >= orb_low

    if not (broke_above or broke_below):
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "No ORB breakout detected", atr)

    # Volume confirmation: volume > 1.5x average
    vol_confirmed = current.get("volume_ratio", 1.0) > 1.5 if "volume_ratio" in current else True

    # RSI filter: don't buy if overbought, don't sell if oversold
    rsi = current["rsi"]
    signal = "none"
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    reason = ""
    trend_dir = ""

    if broke_above and vol_confirmed and rsi < cfg.rsi_overbought:
        signal = "buy"
        entry_price = price
        stop_loss = entry_price - 1.5 * atr
        take_profit = entry_price + 3.0 * atr
        trend_dir = "uptrend"
        reason = (
            f"ORB LONG: broke above {orb_high:.1f}, "
            f"range={orb_range:.1f}, RSI={rsi:.1f}, vol={current.get('volume_ratio', 1):.1f}x"
        )
    elif broke_below and vol_confirmed and rsi > cfg.rsi_oversold:
        signal = "sell"
        entry_price = price
        stop_loss = entry_price + 1.5 * atr
        take_profit = entry_price - 3.0 * atr
        trend_dir = "downtrend"
        reason = (
            f"ORB SHORT: broke below {orb_low:.1f}, "
            f"range={orb_range:.1f}, RSI={rsi:.1f}, vol={current.get('volume_ratio', 1):.1f}x"
        )
    else:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"Filters not met: RSI={rsi:.1f}, vol_ok={vol_confirmed}", atr)

    # Position sizing
    sl_distance = abs(entry_price - stop_loss)
    contract_value = CONTRACT_VALUES.get(symbol, 20)
    lots, risk_amount, _ = calculate_position_size(
        cfg.current_equity, cfg.risk_per_trade, sl_distance, contract_value
    )

    confidence = "high" if current.get("volume_ratio", 1) > 2.0 else "medium"
    return build_signal_dict(
        symbol, strategy_name, signal, entry_price, stop_loss, take_profit,
        lots, risk_amount, reason, atr, session="us", trend_direction=trend_dir,
        confidence=confidence,
    )


def strategy_nas100_trend_pullback(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """
    NAS100 EMA20 Pullback in Trend (Swing, 1-2 day hold)
    =====================================================
    Signal: EMA50 > EMA200 trend, price pulls back to EMA20, RSI 40-60.
    SL: 2.0x ATR, TP: 4.0x ATR (1:2 R:R)
    Risk: 0.5% per trade, max 1 trade per 2 days.
    """
    symbol = cfg.symbol or "NAS100"
    strategy_name = "NAS100_TREND_SWING"

    if len(df) < 250:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data (< 250 bars)", 0)

    df = add_indicators(df, ema_fast=20, ema_medium=50, ema_slow=200,
                        rsi_period=14, atr_period=14)

    i = -1
    current = df.iloc[i]
    prev = df.iloc[i - 1]
    atr = current["atr"]
    price = current["close"]

    # Prop firm compliance
    compliance_ok, compliance_reason = check_prop_firm_compliance(
        cfg.current_equity, cfg.peak_equity, cfg.daily_pnl,
        cfg.daily_dd_limit, cfg.max_dd_limit,
        cfg.trades_today, cfg.max_trades_per_day,
        cfg.consistency_limit_pct,
    )
    if not compliance_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"COMPLIANCE FAIL: {compliance_reason}", atr)

    atr_ok, atr_reason = check_min_atr(symbol, atr)
    if not atr_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"ATR FILTER: {atr_reason}", atr)

    # Trend check
    trend_up = current["ema_medium"] > current["ema_slow"]
    trend_down = current["ema_medium"] < current["ema_slow"]
    if not (trend_up or trend_down):
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "No clear trend (EMA50 vs EMA200)", atr)

    # Pullback: price near EMA20 (within 0.5 ATR)
    ema20_dist = abs(price - current["ema_fast"])
    pullback_zone = ema20_dist < 0.5 * atr

    if not pullback_zone:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"No pullback to EMA20: dist={ema20_dist:.1f}, ATR={atr:.1f}", atr)

    # RSI filter: 40-60 for long, 40-60 for short (neutral zone)
    rsi = current["rsi"]
    signal = "none"
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    trend_dir = ""
    reason = ""

    if trend_up and 35 < rsi < 65:
        signal = "buy"
        entry_price = price
        stop_loss = entry_price - 2.0 * atr
        take_profit = entry_price + 4.0 * atr
        trend_dir = "uptrend"
        reason = (
            f"SWING LONG: EMA50>EMA200, pullback to EMA20, "
            f"RSI={rsi:.1f}, EMA20_dist={ema20_dist:.1f}"
        )
    elif trend_down and 35 < rsi < 65:
        signal = "sell"
        entry_price = price
        stop_loss = entry_price + 2.0 * atr
        take_profit = entry_price - 4.0 * atr
        trend_dir = "downtrend"
        reason = (
            f"SWING SHORT: EMA50<EMA200, pullback to EMA20, "
            f"RSI={rsi:.1f}, EMA20_dist={ema20_dist:.1f}"
        )
    else:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"RSI out of range: {rsi:.1f}", atr)

    # Position sizing
    sl_distance = abs(entry_price - stop_loss)
    contract_value = CONTRACT_VALUES.get(symbol, 20)
    lots, risk_amount, _ = calculate_position_size(
        cfg.current_equity, cfg.risk_per_trade, sl_distance, contract_value
    )

    return build_signal_dict(
        symbol, strategy_name, signal, entry_price, stop_loss, take_profit,
        lots, risk_amount, reason, atr, session="us", trend_direction=trend_dir,
        confidence="medium",
    )


def strategy_nas100_scalp(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """
    NAS100 Session Scalping (10-20 points, 15-30 min hold)
    ======================================================
    Signal: EMA cross + RSI confirmation + volume spike.
    SL: 1.0x ATR, TP: 2.0x ATR (1:2 R:R)
    Risk: 0.5%, max 2 trades per session.
    """
    symbol = cfg.symbol or "NAS100"
    strategy_name = "NAS100_SCALP"

    if len(df) < 100:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data", 0)

    df = add_indicators(df, ema_fast=9, ema_medium=21, ema_slow=50,
                        rsi_period=7, atr_period=7, volume_ma_period=10)

    i = -1
    current = df.iloc[i]
    prev1 = df.iloc[i - 1]
    prev2 = df.iloc[i - 2]
    atr = current["atr"]
    price = current["close"]

    # Compliance
    compliance_ok, compliance_reason = check_prop_firm_compliance(
        cfg.current_equity, cfg.peak_equity, cfg.daily_pnl,
        cfg.daily_dd_limit, cfg.max_dd_limit,
        cfg.trades_today, cfg.max_trades_per_day,
        cfg.consistency_limit_pct,
    )
    if not compliance_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"COMPLIANCE FAIL: {compliance_reason}", atr)

    atr_ok, atr_reason = check_min_atr(symbol, atr)
    if not atr_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"ATR FILTER: {atr_reason}", atr)

    # Session filter
    if isinstance(df.index, pd.DatetimeIndex):
        bar_time = df.index[i].time() if hasattr(df.index[i], "time") else df.index[i].to_pydatetime().time()
        us_start = SESSION_HOURS["us"]["start"]
        us_end = SESSION_HOURS["us"]["end"]
        if not (us_start <= bar_time <= us_end):
            return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                     f"Outside US session: {bar_time}", atr)

    # EMA cross detection
    fast_cross_up = (prev1["ema_fast"] <= prev1["ema_medium"]) and (current["ema_fast"] > current["ema_medium"])
    fast_cross_down = (prev1["ema_fast"] >= prev1["ema_medium"]) and (current["ema_fast"] < current["ema_medium"])

    # RSI confirmation
    rsi = current["rsi"]
    rsi_long_ok = 40 < rsi < 70
    rsi_short_ok = 30 < rsi < 60

    # Volume spike
    vol_ok = current.get("volume_ratio", 1.0) > 1.3

    signal = "none"
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    trend_dir = ""
    reason = ""

    if fast_cross_up and rsi_long_ok and vol_ok:
        signal = "buy"
        entry_price = price
        stop_loss = entry_price - 1.0 * atr
        take_profit = entry_price + 2.0 * atr
        trend_dir = "up"
        reason = (
            f"SCALP LONG: EMA9x21 up, RSI={rsi:.1f}, "
            f"vol={current.get('volume_ratio', 1):.1f}x"
        )
    elif fast_cross_down and rsi_short_ok and vol_ok:
        signal = "sell"
        entry_price = price
        stop_loss = entry_price + 1.0 * atr
        take_profit = entry_price - 2.0 * atr
        trend_dir = "down"
        reason = (
            f"SCALP SHORT: EMA9x21 down, RSI={rsi:.1f}, "
            f"vol={current.get('volume_ratio', 1):.1f}x"
        )
    else:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"No signal: cross_up={fast_cross_up}, cross_down={fast_cross_down}, "
                                 f"RSI={rsi:.1f}, vol_ok={vol_ok}", atr)

    sl_distance = abs(entry_price - stop_loss)
    contract_value = CONTRACT_VALUES.get(symbol, 20)
    lots, risk_amount, _ = calculate_position_size(
        cfg.current_equity, cfg.risk_per_trade, sl_distance, contract_value
    )

    confidence = "high" if current.get("volume_ratio", 1) > 2.0 else "medium"
    return build_signal_dict(
        symbol, strategy_name, signal, entry_price, stop_loss, take_profit,
        lots, risk_amount, reason, atr, session="us", trend_direction=trend_dir,
        confidence=confidence,
    )


def strategy_us30_orb(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """
    US30 Opening Range Breakout (Day Trading)
    ==========================================
    Similar to NAS100 ORB but with wider stops (US30 has larger point values).
    SL: 1.5x ATR, TP: 3.0x ATR
    Session: US Open 13:00-16:00 GMT
    """
    symbol = cfg.symbol or "US30"
    strategy_name = "US30_ORB"

    if len(df) < 200:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data (< 200 bars)", 0)

    df = add_indicators(df, ema_fast=cfg.ema_fast, ema_medium=cfg.ema_medium,
                        ema_slow=cfg.ema_slow, rsi_period=cfg.rsi_period,
                        atr_period=cfg.atr_period)

    i = -1
    current = df.iloc[i]
    prev = df.iloc[i - 1]
    atr = current["atr"]
    price = current["close"]

    # Prop firm compliance
    compliance_ok, compliance_reason = check_prop_firm_compliance(
        cfg.current_equity, cfg.peak_equity, cfg.daily_pnl,
        cfg.daily_dd_limit, cfg.max_dd_limit,
        cfg.trades_today, cfg.max_trades_per_day,
        cfg.consistency_limit_pct,
    )
    if not compliance_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"COMPLIANCE FAIL: {compliance_reason}", atr)

    atr_ok, atr_reason = check_min_atr(symbol, atr)
    if not atr_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"ATR FILTER: {atr_reason}", atr)

    # Session filter
    if isinstance(df.index, pd.DatetimeIndex):
        bar_time = df.index[i].time() if hasattr(df.index[i], "time") else df.index[i].to_pydatetime().time()
        us_start = SESSION_HOURS["us"]["start"]
        us_end = SESSION_HOURS["us"]["end"]
        if not (us_start <= bar_time <= us_end):
            return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                     f"Outside US session: {bar_time}", atr)

    # ORB calculation
    orb_bars = cfg.orb_lookback_bars
    if len(df) < orb_bars + 10:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data for ORB", atr)

    orb_window = df.iloc[-(orb_bars + 1):-1]
    orb_high = orb_window["high"].max()
    orb_low = orb_window["low"].min()
    orb_range = orb_high - orb_low
    min_range = price * cfg.orb_range_pct

    if orb_range < min_range:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"ORB range too small: {orb_range:.1f} < {min_range:.1f}", atr)

    broke_above = current["high"] > orb_high and prev["high"] <= orb_high
    broke_below = current["low"] < orb_low and prev["low"] >= orb_low

    if not (broke_above or broke_below):
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "No ORB breakout detected", atr)

    vol_confirmed = current.get("volume_ratio", 1.0) > 1.5 if "volume_ratio" in current else True
    rsi = current["rsi"]

    signal = "none"
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    trend_dir = ""
    reason = ""

    if broke_above and vol_confirmed and rsi < cfg.rsi_overbought:
        signal = "buy"
        entry_price = price
        stop_loss = entry_price - 1.5 * atr
        take_profit = entry_price + 3.0 * atr
        trend_dir = "uptrend"
        reason = (
            f"ORB LONG: broke {orb_high:.0f}, range={orb_range:.0f}, "
            f"RSI={rsi:.1f}, vol={current.get('volume_ratio', 1):.1f}x"
        )
    elif broke_below and vol_confirmed and rsi > cfg.rsi_oversold:
        signal = "sell"
        entry_price = price
        stop_loss = entry_price + 1.5 * atr
        take_profit = entry_price - 3.0 * atr
        trend_dir = "downtrend"
        reason = (
            f"ORB SHORT: broke {orb_low:.0f}, range={orb_range:.0f}, "
            f"RSI={rsi:.1f}, vol={current.get('volume_ratio', 1):.1f}x"
        )
    else:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"Filters: RSI={rsi:.1f}, vol_ok={vol_confirmed}", atr)

    sl_distance = abs(entry_price - stop_loss)
    contract_value = CONTRACT_VALUES.get(symbol, 5)
    lots, risk_amount, _ = calculate_position_size(
        cfg.current_equity, cfg.risk_per_trade, sl_distance, contract_value
    )

    confidence = "high" if current.get("volume_ratio", 1) > 2.0 else "medium"
    return build_signal_dict(
        symbol, strategy_name, signal, entry_price, stop_loss, take_profit,
        lots, risk_amount, reason, atr, session="us", trend_direction=trend_dir,
        confidence=confidence,
    )


# ═══════════════════════════════════════════════════════════════
# === CRYPTO STRATEGIES ===
# ═══════════════════════════════════════════════════════════════

def strategy_crypto_breakout(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """
    Crypto 4H Range Breakout (Day Trading, 24/7)
    =============================================
    Signal: 48-bar (4-hour) consolidation range breakout with volume.
    Works for all crypto symbols (BTC, ETH, SOL, DOGE, XRP, LTC).
    SL: 1.5x ATR, TP: 3.0x ATR (1:2 R:R)
    Risk: 0.5% per trade, max 1 trade per 4h cycle.

    Parameters from cfg:
        symbol: e.g. 'BTCUSD', 'ETHUSD', etc.
    """
    symbol = cfg.symbol
    if not symbol:
        return build_signal_dict("UNKNOWN", "CRYPTO_BREAKOUT", "none", 0, 0, 0, 0, 0,
                                 "No symbol specified", 0)
    strategy_name = f"{symbol}_BREAKOUT"

    if len(df) < 200:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data (< 200 bars)", 0)

    df = add_indicators(df, ema_fast=cfg.ema_fast, ema_medium=cfg.ema_medium,
                        ema_slow=cfg.ema_slow, rsi_period=cfg.rsi_period,
                        atr_period=cfg.atr_period)

    i = -1
    current = df.iloc[i]
    prev = df.iloc[i - 1]
    atr = current["atr"]
    price = current["close"]

    # Prop firm compliance
    compliance_ok, compliance_reason = check_prop_firm_compliance(
        cfg.current_equity, cfg.peak_equity, cfg.daily_pnl,
        cfg.daily_dd_limit, cfg.max_dd_limit,
        cfg.trades_today, cfg.max_trades_per_day,
        cfg.consistency_limit_pct,
    )
    if not compliance_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"COMPLIANCE FAIL: {compliance_reason}", atr)

    atr_ok, atr_reason = check_min_atr(symbol, atr)
    if not atr_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"ATR FILTER: {atr_reason}", atr)

    # 4H range = 48 bars on M5
    range_bars = 48
    if len(df) < range_bars + 10:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data for range", atr)

    range_window = df.iloc[-(range_bars + 1):-1]
    range_high = range_window["high"].max()
    range_low = range_window["low"].min()
    range_size = range_high - range_low

    # Min range check: ATR must be meaningful relative to price
    min_range = price * 0.005  # 0.5% of price
    if range_size < min_range:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"4H range too small: {range_size:.2f} < {min_range:.2f}", atr)

    # Breakout detection
    broke_above = current["high"] > range_high and prev["high"] <= range_high
    broke_below = current["low"] < range_low and prev["low"] >= range_low

    if not (broke_above or broke_below):
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "No 4H range breakout", atr)

    # Volume confirmation: > 1.5x average
    vol_ok = current.get("volume_ratio", 1.0) > 1.5 if "volume_ratio" in current else True

    # RSI filter: don't fight extremes
    rsi = current["rsi"]

    signal = "none"
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    trend_dir = ""
    reason = ""

    if broke_above and vol_ok and rsi < 75:
        signal = "buy"
        entry_price = price
        stop_loss = entry_price - 1.5 * atr
        take_profit = entry_price + 3.0 * atr
        trend_dir = "breakout_up"
        reason = (
            f"CRYPTO LONG: broke 4H high {range_high:.2f}, "
            f"range={range_size:.2f}, RSI={rsi:.1f}, vol={current.get('volume_ratio', 1):.1f}x"
        )
    elif broke_below and vol_ok and rsi > 25:
        signal = "sell"
        entry_price = price
        stop_loss = entry_price + 1.5 * atr
        take_profit = entry_price - 3.0 * atr
        trend_dir = "breakout_down"
        reason = (
            f"CRYPTO SHORT: broke 4H low {range_low:.2f}, "
            f"range={range_size:.2f}, RSI={rsi:.1f}, vol={current.get('volume_ratio', 1):.1f}x"
        )
    else:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"Filters: RSI={rsi:.1f}, vol_ok={vol_ok}", atr)

    sl_distance = abs(entry_price - stop_loss)
    contract_value = CONTRACT_VALUES.get(symbol, 1)
    lots, risk_amount, _ = calculate_position_size(
        cfg.current_equity, cfg.risk_per_trade, sl_distance, contract_value
    )

    confidence = "high" if current.get("volume_ratio", 1) > 2.5 else "medium"
    return build_signal_dict(
        symbol, strategy_name, signal, entry_price, stop_loss, take_profit,
        lots, risk_amount, reason, atr, session="24/7", trend_direction=trend_dir,
        confidence=confidence,
    )


def strategy_crypto_trend(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """
    Crypto EMA50 Trend Following (Swing, 1-3 day hold)
    ===================================================
    Signal: EMA20 > EMA50 > EMA200, pullback to EMA20.
    SL: 2.5x ATR, TP: 5.0x ATR (1:2 R:R)
    Risk: 0.5%, max 1 trade per 2 days.
    Works for all crypto symbols.
    """
    symbol = cfg.symbol
    if not symbol:
        return build_signal_dict("UNKNOWN", "CRYPTO_TREND", "none", 0, 0, 0, 0, 0,
                                 "No symbol specified", 0)
    strategy_name = f"{symbol}_TREND_SWING"

    if len(df) < 300:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data (< 300 bars)", 0)

    df = add_indicators(df, ema_fast=20, ema_medium=50, ema_slow=200,
                        rsi_period=14, atr_period=14)

    i = -1
    current = df.iloc[i]
    atr = current["atr"]
    price = current["close"]

    # Prop firm compliance
    compliance_ok, compliance_reason = check_prop_firm_compliance(
        cfg.current_equity, cfg.peak_equity, cfg.daily_pnl,
        cfg.daily_dd_limit, cfg.max_dd_limit,
        cfg.trades_today, cfg.max_trades_per_day,
        cfg.consistency_limit_pct,
    )
    if not compliance_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"COMPLIANCE FAIL: {compliance_reason}", atr)

    atr_ok, atr_reason = check_min_atr(symbol, atr)
    if not atr_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"ATR FILTER: {atr_reason}", atr)

    # Triple EMA trend check
    strong_uptrend = (current["ema_fast"] > current["ema_medium"]) and \
                     (current["ema_medium"] > current["ema_slow"])
    strong_downtrend = (current["ema_fast"] < current["ema_medium"]) and \
                       (current["ema_medium"] < current["ema_slow"])

    if not (strong_uptrend or strong_downtrend):
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "No strong triple EMA trend", atr)

    # Pullback to EMA20
    ema20_dist = abs(price - current["ema_fast"])
    pullback_zone = ema20_dist < 1.0 * atr  # Wider for crypto volatility

    if not pullback_zone:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"No pullback to EMA20: dist={ema20_dist:.2f}", atr)

    # RSI confirmation
    rsi = current["rsi"]
    macd_hist = current.get("macd_hist", 0)

    signal = "none"
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    trend_dir = ""
    reason = ""

    if strong_uptrend and 30 < rsi < 65 and macd_hist > 0:
        signal = "buy"
        entry_price = price
        stop_loss = entry_price - 2.5 * atr
        take_profit = entry_price + 5.0 * atr
        trend_dir = "strong_uptrend"
        reason = (
            f"SWING LONG: EMA20>50>200, pullback to EMA20, "
            f"RSI={rsi:.1f}, MACD_hist={macd_hist:.4f}"
        )
    elif strong_downtrend and 35 < rsi < 70 and macd_hist < 0:
        signal = "sell"
        entry_price = price
        stop_loss = entry_price + 2.5 * atr
        take_profit = entry_price - 5.0 * atr
        trend_dir = "strong_downtrend"
        reason = (
            f"SWING SHORT: EMA20<50<200, pullback to EMA20, "
            f"RSI={rsi:.1f}, MACD_hist={macd_hist:.4f}"
        )
    else:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"Filters: RSI={rsi:.1f}, MACD={macd_hist:.4f}", atr)

    sl_distance = abs(entry_price - stop_loss)
    contract_value = CONTRACT_VALUES.get(symbol, 1)
    lots, risk_amount, _ = calculate_position_size(
        cfg.current_equity, cfg.risk_per_trade, sl_distance, contract_value
    )

    return build_signal_dict(
        symbol, strategy_name, signal, entry_price, stop_loss, take_profit,
        lots, risk_amount, reason, atr, session="24/7", trend_direction=trend_dir,
        confidence="medium",
    )


def strategy_crypto_scalp(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """
    Crypto Scalping (EMA cross + RSI, 15-30 min hold)
    ==================================================
    Signal: Fast EMA cross on M5 with RSI and volume.
    SL: 1.0x ATR, TP: 2.0x ATR
    Risk: 0.5%, max 2 trades per 4h.
    Works for all crypto symbols.
    """
    symbol = cfg.symbol
    if not symbol:
        return build_signal_dict("UNKNOWN", "CRYPTO_SCALP", "none", 0, 0, 0, 0, 0,
                                 "No symbol specified", 0)
    strategy_name = f"{symbol}_SCALP"

    if len(df) < 100:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data", 0)

    df = add_indicators(df, ema_fast=9, ema_medium=21, ema_slow=50,
                        rsi_period=7, atr_period=7, volume_ma_period=10)

    i = -1
    current = df.iloc[i]
    prev1 = df.iloc[i - 1]
    atr = current["atr"]
    price = current["close"]

    # Compliance
    compliance_ok, compliance_reason = check_prop_firm_compliance(
        cfg.current_equity, cfg.peak_equity, cfg.daily_pnl,
        cfg.daily_dd_limit, cfg.max_dd_limit,
        cfg.trades_today, cfg.max_trades_per_day,
        cfg.consistency_limit_pct,
    )
    if not compliance_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"COMPLIANCE FAIL: {compliance_reason}", atr)

    atr_ok, atr_reason = check_min_atr(symbol, atr)
    if not atr_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"ATR FILTER: {atr_reason}", atr)

    # EMA cross
    cross_up = (prev1["ema_fast"] <= prev1["ema_medium"]) and (current["ema_fast"] > current["ema_medium"])
    cross_down = (prev1["ema_fast"] >= prev1["ema_medium"]) and (current["ema_fast"] < current["ema_medium"])

    rsi = current["rsi"]
    vol_ok = current.get("volume_ratio", 1.0) > 1.3

    signal = "none"
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    trend_dir = ""
    reason = ""

    if cross_up and 40 < rsi < 70 and vol_ok:
        signal = "buy"
        entry_price = price
        stop_loss = entry_price - 1.0 * atr
        take_profit = entry_price + 2.0 * atr
        trend_dir = "up"
        reason = (
            f"SCALP LONG: EMA9x21 cross up, RSI={rsi:.1f}, "
            f"vol={current.get('volume_ratio', 1):.1f}x"
        )
    elif cross_down and 30 < rsi < 60 and vol_ok:
        signal = "sell"
        entry_price = price
        stop_loss = entry_price + 1.0 * atr
        take_profit = entry_price - 2.0 * atr
        trend_dir = "down"
        reason = (
            f"SCALP SHORT: EMA9x21 cross down, RSI={rsi:.1f}, "
            f"vol={current.get('volume_ratio', 1):.1f}x"
        )
    else:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"No signal: cross_up={cross_up}, cross_down={cross_down}, "
                                 f"RSI={rsi:.1f}", atr)

    sl_distance = abs(entry_price - stop_loss)
    contract_value = CONTRACT_VALUES.get(symbol, 1)
    lots, risk_amount, _ = calculate_position_size(
        cfg.current_equity, cfg.risk_per_trade, sl_distance, contract_value
    )

    confidence = "high" if current.get("volume_ratio", 1) > 2.0 else "medium"
    return build_signal_dict(
        symbol, strategy_name, signal, entry_price, stop_loss, take_profit,
        lots, risk_amount, reason, atr, session="24/7", trend_direction=trend_dir,
        confidence=confidence,
    )


# ═══════════════════════════════════════════════════════════════
# === COMMODITY STRATEGIES ===
# ═══════════════════════════════════════════════════════════════

def strategy_xauusd_asian_breakout(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """
    XAUUSD Asian Range Breakout (Day Trading)
    ==========================================
    Signal: London open breaks Asian session range (00:00-08:00 GMT).
    SL: 1.5x ATR, TP: 3.0x ATR (1:2 R:R)
    Session: London open 08:00 GMT
    Risk: 0.5%, max 1 trade per day.
    """
    symbol = cfg.symbol or "XAUUSD"
    strategy_name = "XAUUSD_ASIAN_BREAKOUT"

    if len(df) < 200:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data (< 200 bars)", 0)

    df = add_indicators(df, ema_fast=cfg.ema_fast, ema_medium=cfg.ema_medium,
                        ema_slow=cfg.ema_slow, rsi_period=cfg.rsi_period,
                        atr_period=cfg.atr_period)

    i = -1
    current = df.iloc[i]
    prev = df.iloc[i - 1]
    atr = current["atr"]
    price = current["close"]

    # Prop firm compliance
    compliance_ok, compliance_reason = check_prop_firm_compliance(
        cfg.current_equity, cfg.peak_equity, cfg.daily_pnl,
        cfg.daily_dd_limit, cfg.max_dd_limit,
        cfg.trades_today, cfg.max_trades_per_day,
        cfg.consistency_limit_pct,
    )
    if not compliance_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"COMPLIANCE FAIL: {compliance_reason}", atr)

    atr_ok, atr_reason = check_min_atr(symbol, atr)
    if not atr_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"ATR FILTER: {atr_reason}", atr)

    # Session filter: London session (08:00-16:00 GMT)
    if not isinstance(df.index, pd.DatetimeIndex):
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "DatetimeIndex required", atr)
    bar_time = df.index[i].time() if hasattr(df.index[i], "time") else df.index[i].to_pydatetime().time()
    london_start = SESSION_HOURS["london"]["start"]
    london_end = time(11, 0)  # Only first 3 hours of London
    if not (london_start <= bar_time <= london_end):
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"Outside London open window: {bar_time}", atr)

    # Asian session range: look back to find Asian session bars
    # Asian session = 00:00-08:00 GMT = 96 bars on M5
    asian_bars = 96
    if len(df) < asian_bars + 10:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data for Asian range", atr)

    # Get the Asian session range from previous day's Asian session
    asian_window = df.iloc[-(asian_bars + 10):-10]
    asian_high = asian_window["high"].max()
    asian_low = asian_window["low"].min()
    asian_range = asian_high - asian_low

    if asian_range < atr * 2:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"Asian range too small: {asian_range:.2f} < 2xATR", atr)

    # Breakout check
    broke_above = current["high"] > asian_high and prev["high"] <= asian_high
    broke_below = current["low"] < asian_low and prev["low"] >= asian_low

    if not (broke_above or broke_below):
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "No Asian range breakout", atr)

    vol_ok = current.get("volume_ratio", 1.0) > 1.5 if "volume_ratio" in current else True
    rsi = current["rsi"]

    signal = "none"
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    trend_dir = ""
    reason = ""

    if broke_above and vol_ok and rsi < 75:
        signal = "buy"
        entry_price = price
        stop_loss = entry_price - 1.5 * atr
        take_profit = entry_price + 3.0 * atr
        trend_dir = "london_breakout_up"
        reason = (
            f"ASIAN BO LONG: broke {asian_high:.2f}, Asian range={asian_range:.2f}, "
            f"RSI={rsi:.1f}, vol={current.get('volume_ratio', 1):.1f}x"
        )
    elif broke_below and vol_ok and rsi > 25:
        signal = "sell"
        entry_price = price
        stop_loss = entry_price + 1.5 * atr
        take_profit = entry_price - 3.0 * atr
        trend_dir = "london_breakout_down"
        reason = (
            f"ASIAN BO SHORT: broke {asian_low:.2f}, Asian range={asian_range:.2f}, "
            f"RSI={rsi:.1f}, vol={current.get('volume_ratio', 1):.1f}x"
        )
    else:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"Filters: RSI={rsi:.1f}, vol={vol_ok}", atr)

    sl_distance = abs(entry_price - stop_loss)
    contract_value = CONTRACT_VALUES.get(symbol, 100)
    lots, risk_amount, _ = calculate_position_size(
        cfg.current_equity, cfg.risk_per_trade, sl_distance, contract_value
    )

    return build_signal_dict(
        symbol, strategy_name, signal, entry_price, stop_loss, take_profit,
        lots, risk_amount, reason, atr, session="london", trend_direction=trend_dir,
        confidence="medium",
    )


def strategy_xauusd_ny_momentum(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """
    XAUUSD NY Session Momentum (Day Trading)
    =========================================
    Signal: NY open momentum with volume confirmation.
    Uses MACD + RSI for directional bias.
    SL: 1.5x ATR, TP: 3.0x ATR (1:2 R:R)
    Session: US 13:00-16:00 GMT
    """
    symbol = cfg.symbol or "XAUUSD"
    strategy_name = "XAUUSD_NY_MOMENTUM"

    if len(df) < 200:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data", 0)

    df = add_indicators(df, ema_fast=9, ema_medium=21, ema_slow=50,
                        rsi_period=14, atr_period=14)

    i = -1
    current = df.iloc[i]
    prev1 = df.iloc[i - 1]
    prev2 = df.iloc[i - 2]
    atr = current["atr"]
    price = current["close"]

    # Prop firm compliance
    compliance_ok, compliance_reason = check_prop_firm_compliance(
        cfg.current_equity, cfg.peak_equity, cfg.daily_pnl,
        cfg.daily_dd_limit, cfg.max_dd_limit,
        cfg.trades_today, cfg.max_trades_per_day,
        cfg.consistency_limit_pct,
    )
    if not compliance_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"COMPLIANCE FAIL: {compliance_reason}", atr)

    atr_ok, atr_reason = check_min_atr(symbol, atr)
    if not atr_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"ATR FILTER: {atr_reason}", atr)

    # Session filter: US session first 3 hours
    if isinstance(df.index, pd.DatetimeIndex):
        bar_time = df.index[i].time() if hasattr(df.index[i], "time") else df.index[i].to_pydatetime().time()
        us_start = SESSION_HOURS["us"]["start"]
        us_early_end = time(16, 0)
        if not (us_start <= bar_time <= us_early_end):
            return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                     f"Outside US session window: {bar_time}", atr)

    # MACD momentum
    macd_hist = current["macd_hist"]
    prev_macd_hist = prev1["macd_hist"]
    macd_rising = macd_hist > prev_macd_hist and macd_hist > 0
    macd_falling = macd_hist < prev_macd_hist and macd_hist < 0

    # RSI
    rsi = current["rsi"]

    # EMA alignment
    above_ema21 = price > current["ema_medium"]
    below_ema21 = price < current["ema_medium"]

    # Volume
    vol_ok = current.get("volume_ratio", 1.0) > 1.5

    signal = "none"
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    trend_dir = ""
    reason = ""

    if macd_rising and above_ema21 and vol_ok and 45 < rsi < 75:
        signal = "buy"
        entry_price = price
        stop_loss = entry_price - 1.5 * atr
        take_profit = entry_price + 3.0 * atr
        trend_dir = "ny_momentum_up"
        reason = (
            f"NY MOM LONG: MACD rising + EMA21 support, "
            f"RSI={rsi:.1f}, vol={current.get('volume_ratio', 1):.1f}x, MACD_hist={macd_hist:.4f}"
        )
    elif macd_falling and below_ema21 and vol_ok and 25 < rsi < 55:
        signal = "sell"
        entry_price = price
        stop_loss = entry_price + 1.5 * atr
        take_profit = entry_price - 3.0 * atr
        trend_dir = "ny_momentum_down"
        reason = (
            f"NY MOM SHORT: MACD falling + below EMA21, "
            f"RSI={rsi:.1f}, vol={current.get('volume_ratio', 1):.1f}x, MACD_hist={macd_hist:.4f}"
        )
    else:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"No momentum: MACD_rising={macd_rising}, above_EMA={above_ema21}, "
                                 f"RSI={rsi:.1f}, vol_ok={vol_ok}", atr)

    sl_distance = abs(entry_price - stop_loss)
    contract_value = CONTRACT_VALUES.get(symbol, 100)
    lots, risk_amount, _ = calculate_position_size(
        cfg.current_equity, cfg.risk_per_trade, sl_distance, contract_value
    )

    return build_signal_dict(
        symbol, strategy_name, signal, entry_price, stop_loss, take_profit,
        lots, risk_amount, reason, atr, session="us", trend_direction=trend_dir,
        confidence="medium",
    )


def strategy_xauusd_swing(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """
    XAUUSD Swing Trend Following (1-3 day hold)
    ============================================
    Signal: Daily EMA50 trend, 4H pullback to EMA20, RSI 35-65.
    SL: 2.0x ATR, TP: 4.0x ATR (1:2 R:R)
    Risk: 0.5%, max 1 trade per 2 days.
    """
    symbol = cfg.symbol or "XAUUSD"
    strategy_name = "XAUUSD_SWING_TREND"

    if len(df) < 300:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data (< 300 bars)", 0)

    df = add_indicators(df, ema_fast=20, ema_medium=50, ema_slow=200,
                        rsi_period=14, atr_period=14)

    i = -1
    current = df.iloc[i]
    atr = current["atr"]
    price = current["close"]

    # Prop firm compliance
    compliance_ok, compliance_reason = check_prop_firm_compliance(
        cfg.current_equity, cfg.peak_equity, cfg.daily_pnl,
        cfg.daily_dd_limit, cfg.max_dd_limit,
        cfg.trades_today, cfg.max_trades_per_day,
        cfg.consistency_limit_pct,
    )
    if not compliance_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"COMPLIANCE FAIL: {compliance_reason}", atr)

    atr_ok, atr_reason = check_min_atr(symbol, atr)
    if not atr_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"ATR FILTER: {atr_reason}", atr)

    # Trend: EMA50 vs EMA200
    trend_up = current["ema_medium"] > current["ema_slow"]
    trend_down = current["ema_medium"] < current["ema_slow"]

    if not (trend_up or trend_down):
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "No clear trend (EMA50 vs EMA200)", atr)

    # Pullback to EMA20
    ema20_dist = abs(price - current["ema_fast"])
    pullback_zone = ema20_dist < 0.5 * atr

    if not pullback_zone:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"No pullback to EMA20: dist={ema20_dist:.2f}", atr)

    # RSI
    rsi = current["rsi"]

    signal = "none"
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    trend_dir = ""
    reason = ""

    if trend_up and 35 < rsi < 65:
        signal = "buy"
        entry_price = price
        stop_loss = entry_price - 2.0 * atr
        take_profit = entry_price + 4.0 * atr
        trend_dir = "swing_uptrend"
        reason = (
            f"SWING LONG: EMA50>EMA200, pullback to EMA20, RSI={rsi:.1f}, "
            f"dist_to_EMA20={ema20_dist:.2f}"
        )
    elif trend_down and 35 < rsi < 65:
        signal = "sell"
        entry_price = price
        stop_loss = entry_price + 2.0 * atr
        take_profit = entry_price - 4.0 * atr
        trend_dir = "swing_downtrend"
        reason = (
            f"SWING SHORT: EMA50<EMA200, pullback to EMA20, RSI={rsi:.1f}, "
            f"dist_to_EMA20={ema20_dist:.2f}"
        )
    else:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"RSI out of range: {rsi:.1f}", atr)

    sl_distance = abs(entry_price - stop_loss)
    contract_value = CONTRACT_VALUES.get(symbol, 100)
    lots, risk_amount, _ = calculate_position_size(
        cfg.current_equity, cfg.risk_per_trade, sl_distance, contract_value
    )

    return build_signal_dict(
        symbol, strategy_name, signal, entry_price, stop_loss, take_profit,
        lots, risk_amount, reason, atr, session="london", trend_direction=trend_dir,
        confidence="medium",
    )


def strategy_xauusd_scalp(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """
    XAUUSD Session Scalping (10-20 pips, 15-30 min)
    ================================================
    Signal: Bollinger Band bounce + RSI reversal in ranging market.
    SL: 1.0x ATR, TP: 2.0x ATR (1:2 R:R)
    Session: London or US overlap.
    """
    symbol = cfg.symbol or "XAUUSD"
    strategy_name = "XAUUSD_SCALP"

    if len(df) < 100:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data", 0)

    df = add_indicators(df, ema_fast=9, ema_medium=21, ema_slow=50,
                        rsi_period=7, atr_period=7)

    i = -1
    current = df.iloc[i]
    prev1 = df.iloc[i - 1]
    atr = current["atr"]
    price = current["close"]

    # Compliance
    compliance_ok, compliance_reason = check_prop_firm_compliance(
        cfg.current_equity, cfg.peak_equity, cfg.daily_pnl,
        cfg.daily_dd_limit, cfg.max_dd_limit,
        cfg.trades_today, cfg.max_trades_per_day,
        cfg.consistency_limit_pct,
    )
    if not compliance_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"COMPLIANCE FAIL: {compliance_reason}", atr)

    atr_ok, atr_reason = check_min_atr(symbol, atr)
    if not atr_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"ATR FILTER: {atr_reason}", atr)

    # Session filter: London or US
    if isinstance(df.index, pd.DatetimeIndex):
        bar_time = df.index[i].time() if hasattr(df.index[i], "time") else df.index[i].to_pydatetime().time()
        london_start = SESSION_HOURS["london"]["start"]
        london_end = SESSION_HOURS["london"]["end"]
        us_start = SESSION_HOURS["us"]["start"]
        us_end = time(18, 0)
        in_session = (london_start <= bar_time <= london_end) or (us_start <= bar_time <= us_end)
        if not in_session:
            return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                     f"Outside trading session: {bar_time}", atr)

    # Range market detection: Bollinger Band width < 0.02 (2%)
    bb_width = current.get("bb_width", 0)
    ranging = bb_width < 0.02

    # Bollinger Band bounce
    near_lower = current["close"] <= current["bb_lower"] + 0.3 * atr
    near_upper = current["close"] >= current["bb_upper"] - 0.3 * atr

    rsi = current["rsi"]
    rsi_reversal_up = (prev1["rsi"] < 30) and (rsi > prev1["rsi"])  # RSI bouncing off oversold
    rsi_reversal_down = (prev1["rsi"] > 70) and (rsi < prev1["rsi"])  # RSI bouncing off overbought

    signal = "none"
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    trend_dir = ""
    reason = ""

    if near_lower and rsi_reversal_up:
        signal = "buy"
        entry_price = price
        stop_loss = entry_price - 1.0 * atr
        take_profit = entry_price + 2.0 * atr
        trend_dir = "range_bounce_up"
        reason = f"SCALP LONG: BB lower bounce, RSI reversal {prev1['rsi']:.1f}->{rsi:.1f}"
    elif near_upper and rsi_reversal_down:
        signal = "sell"
        entry_price = price
        stop_loss = entry_price + 1.0 * atr
        take_profit = entry_price - 2.0 * atr
        trend_dir = "range_bounce_down"
        reason = f"SCALP SHORT: BB upper bounce, RSI reversal {prev1['rsi']:.1f}->{rsi:.1f}"
    else:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"No setup: near_lower={near_lower}, near_upper={near_upper}, "
                                 f"RSI={rsi:.1f}, BB_width={bb_width:.4f}", atr)

    sl_distance = abs(entry_price - stop_loss)
    contract_value = CONTRACT_VALUES.get(symbol, 100)
    lots, risk_amount, _ = calculate_position_size(
        cfg.current_equity, cfg.risk_per_trade, sl_distance, contract_value
    )

    return build_signal_dict(
        symbol, strategy_name, signal, entry_price, stop_loss, take_profit,
        lots, risk_amount, reason, atr, session="london/us", trend_direction=trend_dir,
        confidence="medium",
    )


def strategy_xtiusd_session(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """
    XTIUSD (WTI Crude Oil) US Session Breakout (Day Trading)
    =========================================================
    Signal: NYMEX open volatility expansion after overnight consolidation.
    Aware of inventory report days (Wednesdays 14:30 GMT).
    SL: 1.5x ATR, TP: 3.0x ATR (1:2 R:R)
    Session: US 13:00-16:00 GMT
    Risk: 0.5%, max 1 trade per day.
    """
    symbol = cfg.symbol or "XTIUSD"
    strategy_name = "XTIUSD_US_SESSION"

    if len(df) < 200:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data", 0)

    df = add_indicators(df, ema_fast=9, ema_medium=21, ema_slow=50,
                        rsi_period=14, atr_period=14)

    i = -1
    current = df.iloc[i]
    prev = df.iloc[i - 1]
    atr = current["atr"]
    price = current["close"]

    # Prop firm compliance
    compliance_ok, compliance_reason = check_prop_firm_compliance(
        cfg.current_equity, cfg.peak_equity, cfg.daily_pnl,
        cfg.daily_dd_limit, cfg.max_dd_limit,
        cfg.trades_today, cfg.max_trades_per_day,
        cfg.consistency_limit_pct,
    )
    if not compliance_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"COMPLIANCE FAIL: {compliance_reason}", atr)

    atr_ok, atr_reason = check_min_atr(symbol, atr)
    if not atr_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"ATR FILTER: {atr_reason}", atr)

    # Session filter: US session first 3 hours
    if isinstance(df.index, pd.DatetimeIndex):
        bar_time = df.index[i].time() if hasattr(df.index[i], "time") else df.index[i].to_pydatetime().time()
        us_start = SESSION_HOURS["us"]["start"]
        us_end = time(16, 30)
        if not (us_start <= bar_time <= us_end):
            return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                     f"Outside US session: {bar_time}", atr)

    # Pre-session range (overnight Asian + London consolidation)
    # Look back ~36 bars (3 hours) for consolidation
    pre_bars = 36
    if len(df) < pre_bars + 10:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient pre-session data", atr)

    pre_session = df.iloc[-(pre_bars + 1):-1]
    pre_high = pre_session["high"].max()
    pre_low = pre_session["low"].min()
    pre_range = pre_high - pre_low

    if pre_range < atr * 1.5:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"Pre-session range too small: {pre_range:.3f}", atr)

    # Breakout
    broke_above = current["high"] > pre_high and prev["high"] <= pre_high
    broke_below = current["low"] < pre_low and prev["low"] >= pre_low

    if not (broke_above or broke_below):
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "No session breakout", atr)

    vol_ok = current.get("volume_ratio", 1.0) > 1.5
    rsi = current["rsi"]

    # Check if inventory report day (Wednesday ~14:30 GMT)
    is_inventory_day = False
    if isinstance(df.index, pd.DatetimeIndex):
        weekday = df.index[i].weekday()
        is_inventory_day = (weekday == 2)  # Wednesday

    signal = "none"
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    trend_dir = ""
    reason = ""

    # Extra caution on inventory days - require stronger confirmation
    inventory_adjustment = 1.5 if is_inventory_day else 1.0

    if broke_above and vol_ok and rsi < 75:
        signal = "buy"
        entry_price = price
        stop_loss = entry_price - 1.5 * atr * inventory_adjustment
        take_profit = entry_price + 3.0 * atr
        trend_dir = "oil_breakout_up"
        reason = (
            f"OIL SESSION LONG: broke {pre_high:.2f}, range={pre_range:.2f}, "
            f"RSI={rsi:.1f}, vol={current.get('volume_ratio', 1):.1f}x"
        )
        if is_inventory_day:
            reason += " [INVENTORY DAY - wider SL]"
    elif broke_below and vol_ok and rsi > 25:
        signal = "sell"
        entry_price = price
        stop_loss = entry_price + 1.5 * atr * inventory_adjustment
        take_profit = entry_price - 3.0 * atr
        trend_dir = "oil_breakout_down"
        reason = (
            f"OIL SESSION SHORT: broke {pre_low:.2f}, range={pre_range:.2f}, "
            f"RSI={rsi:.1f}, vol={current.get('volume_ratio', 1):.1f}x"
        )
        if is_inventory_day:
            reason += " [INVENTORY DAY - wider SL]"
    else:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"Filters: RSI={rsi:.1f}, vol={vol_ok}", atr)

    sl_distance = abs(entry_price - stop_loss)
    contract_value = CONTRACT_VALUES.get(symbol, 1000)
    lots, risk_amount, _ = calculate_position_size(
        cfg.current_equity, cfg.risk_per_trade, sl_distance, contract_value
    )

    return build_signal_dict(
        symbol, strategy_name, signal, entry_price, stop_loss, take_profit,
        lots, risk_amount, reason, atr, session="us", trend_direction=trend_dir,
        confidence="medium",
    )


def strategy_xtiusd_trend(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """
    XTIUSD Trend Following Swing (1-3 day hold)
    ============================================
    Signal: EMA50/200 trend, pullback to EMA20.
    SL: 2.0x ATR, TP: 4.0x ATR (1:2 R:R)
    """
    symbol = cfg.symbol or "XTIUSD"
    strategy_name = "XTIUSD_TREND_SWING"

    if len(df) < 300:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data", 0)

    df = add_indicators(df, ema_fast=20, ema_medium=50, ema_slow=200,
                        rsi_period=14, atr_period=14)

    i = -1
    current = df.iloc[i]
    atr = current["atr"]
    price = current["close"]

    compliance_ok, compliance_reason = check_prop_firm_compliance(
        cfg.current_equity, cfg.peak_equity, cfg.daily_pnl,
        cfg.daily_dd_limit, cfg.max_dd_limit,
        cfg.trades_today, cfg.max_trades_per_day,
        cfg.consistency_limit_pct,
    )
    if not compliance_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"COMPLIANCE FAIL: {compliance_reason}", atr)

    atr_ok, atr_reason = check_min_atr(symbol, atr)
    if not atr_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"ATR FILTER: {atr_reason}", atr)

    trend_up = current["ema_medium"] > current["ema_slow"]
    trend_down = current["ema_medium"] < current["ema_slow"]

    if not (trend_up or trend_down):
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "No clear trend", atr)

    ema20_dist = abs(price - current["ema_fast"])
    pullback_zone = ema20_dist < 0.5 * atr

    if not pullback_zone:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"No pullback: dist={ema20_dist:.3f}", atr)

    rsi = current["rsi"]

    signal = "none"
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    trend_dir = ""
    reason = ""

    if trend_up and 35 < rsi < 65:
        signal = "buy"
        entry_price = price
        stop_loss = entry_price - 2.0 * atr
        take_profit = entry_price + 4.0 * atr
        trend_dir = "oil_uptrend"
        reason = f"OIL SWING LONG: EMA50>200, pullback EMA20, RSI={rsi:.1f}"
    elif trend_down and 35 < rsi < 65:
        signal = "sell"
        entry_price = price
        stop_loss = entry_price + 2.0 * atr
        take_profit = entry_price - 4.0 * atr
        trend_dir = "oil_downtrend"
        reason = f"OIL SWING SHORT: EMA50<200, pullback EMA20, RSI={rsi:.1f}"
    else:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"RSI out of range: {rsi:.1f}", atr)

    sl_distance = abs(entry_price - stop_loss)
    contract_value = CONTRACT_VALUES.get(symbol, 1000)
    lots, risk_amount, _ = calculate_position_size(
        cfg.current_equity, cfg.risk_per_trade, sl_distance, contract_value
    )

    return build_signal_dict(
        symbol, strategy_name, signal, entry_price, stop_loss, take_profit,
        lots, risk_amount, reason, atr, session="us", trend_direction=trend_dir,
        confidence="medium",
    )


# ═══════════════════════════════════════════════════════════════
# === FOREX STRATEGIES ===
# ═══════════════════════════════════════════════════════════════

def strategy_forex_london_breakout(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """
    Forex London Opening Range Breakout (Day Trading)
    ==================================================
    Signal: Price breaks Asian session range at London open (08:00 GMT).
    Uses EMA21 for directional bias.
    SL: 1.5x ATR, TP: 3.0x ATR (1:2 R:R)
    Session: London 08:00-11:00 GMT (first 3 hours)
    Risk: 0.5%, max 1 trade per day.

    Works for: EURUSD, USDJPY, GBPJPY, GBPUSD
    """
    symbol = cfg.symbol
    if not symbol:
        return build_signal_dict("UNKNOWN", "FX_LONDON_BO", "none", 0, 0, 0, 0, 0,
                                 "No symbol specified", 0)
    strategy_name = f"{symbol}_LONDON_BREAKOUT"

    if len(df) < 200:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data", 0)

    df = add_indicators(df, ema_fast=9, ema_medium=21, ema_slow=50,
                        rsi_period=14, atr_period=14)

    i = -1
    current = df.iloc[i]
    prev = df.iloc[i - 1]
    atr = current["atr"]
    price = current["close"]

    # Prop firm compliance
    compliance_ok, compliance_reason = check_prop_firm_compliance(
        cfg.current_equity, cfg.peak_equity, cfg.daily_pnl,
        cfg.daily_dd_limit, cfg.max_dd_limit,
        cfg.trades_today, cfg.max_trades_per_day,
        cfg.consistency_limit_pct,
    )
    if not compliance_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"COMPLIANCE FAIL: {compliance_reason}", atr)

    atr_ok, atr_reason = check_min_atr(symbol, atr)
    if not atr_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"ATR FILTER: {atr_reason}", atr)

    # Session filter: London open window
    if not isinstance(df.index, pd.DatetimeIndex):
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "DatetimeIndex required", atr)
    bar_time = df.index[i].time() if hasattr(df.index[i], "time") else df.index[i].to_pydatetime().time()
    london_start = SESSION_HOURS["london"]["start"]
    london_early_end = time(11, 0)
    if not (london_start <= bar_time <= london_early_end):
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"Outside London open: {bar_time}", atr)

    # Asian session range: 00:00-08:00 GMT = 96 M5 bars
    asian_bars = 96
    if len(df) < asian_bars + 10:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data for Asian range", atr)

    asian_window = df.iloc[-(asian_bars + 10):-10]
    asian_high = asian_window["high"].max()
    asian_low = asian_window["low"].min()
    asian_range = asian_high - asian_low

    # Minimum range: must be at least 1.5x ATR
    if asian_range < atr * 1.5:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"Asian range too small: {asian_range:.5f}", atr)

    # Breakout detection
    broke_above = current["high"] > asian_high and prev["high"] <= asian_high
    broke_below = current["low"] < asian_low and prev["low"] >= asian_low

    if not (broke_above or broke_below):
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "No London breakout", atr)

    # EMA21 bias: don't trade against the short-term trend
    above_ema21 = price > current["ema_medium"]
    below_ema21 = price < current["ema_medium"]

    vol_ok = current.get("volume_ratio", 1.0) > 1.3
    rsi = current["rsi"]

    signal = "none"
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    trend_dir = ""
    reason = ""

    if broke_above and above_ema21 and vol_ok and rsi < 75:
        signal = "buy"
        entry_price = price
        stop_loss = entry_price - 1.5 * atr
        take_profit = entry_price + 3.0 * atr
        trend_dir = "london_break_up"
        reason = (
            f"LONDON BO LONG: broke {asian_high:.5f}, range={asian_range:.5f}, "
            f"RSI={rsi:.1f}, vol={current.get('volume_ratio', 1):.1f}x"
        )
    elif broke_below and below_ema21 and vol_ok and rsi > 25:
        signal = "sell"
        entry_price = price
        stop_loss = entry_price + 1.5 * atr
        take_profit = entry_price - 3.0 * atr
        trend_dir = "london_break_down"
        reason = (
            f"LONDON BO SHORT: broke {asian_low:.5f}, range={asian_range:.5f}, "
            f"RSI={rsi:.1f}, vol={current.get('volume_ratio', 1):.1f}x"
        )
    else:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"Filters: above_EMA={above_ema21}, RSI={rsi:.1f}, vol={vol_ok}", atr)

    sl_distance = abs(entry_price - stop_loss)
    contract_value = CONTRACT_VALUES.get(symbol, 100_000)
    lots, risk_amount, _ = calculate_position_size(
        cfg.current_equity, cfg.risk_per_trade, sl_distance, contract_value
    )

    return build_signal_dict(
        symbol, strategy_name, signal, entry_price, stop_loss, take_profit,
        lots, risk_amount, reason, atr, session="london", trend_direction=trend_dir,
        confidence="medium",
    )


def strategy_forex_ny_momentum(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """
    Forex NY Session Momentum (Day Trading)
    ========================================
    Signal: Post-London continuation into NY session (13:00 GMT).
    Uses MACD + EMA9/21 alignment.
    SL: 1.5x ATR, TP: 3.0x ATR (1:2 R:R)
    Session: US 13:00-16:00 GMT
    Risk: 0.5%, max 1 trade per day.

    Works for: EURUSD primarily, also GBPUSD
    """
    symbol = cfg.symbol
    if not symbol:
        return build_signal_dict("UNKNOWN", "FX_NY_MOM", "none", 0, 0, 0, 0, 0,
                                 "No symbol specified", 0)
    strategy_name = f"{symbol}_NY_MOMENTUM"

    if len(df) < 200:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data", 0)

    df = add_indicators(df, ema_fast=9, ema_medium=21, ema_slow=50,
                        rsi_period=14, atr_period=14)

    i = -1
    current = df.iloc[i]
    prev1 = df.iloc[i - 1]
    prev2 = df.iloc[i - 2]
    atr = current["atr"]
    price = current["close"]

    # Prop firm compliance
    compliance_ok, compliance_reason = check_prop_firm_compliance(
        cfg.current_equity, cfg.peak_equity, cfg.daily_pnl,
        cfg.daily_dd_limit, cfg.max_dd_limit,
        cfg.trades_today, cfg.max_trades_per_day,
        cfg.consistency_limit_pct,
    )
    if not compliance_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"COMPLIANCE FAIL: {compliance_reason}", atr)

    atr_ok, atr_reason = check_min_atr(symbol, atr)
    if not atr_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"ATR FILTER: {atr_reason}", atr)

    # Session filter: US session first 3 hours
    if isinstance(df.index, pd.DatetimeIndex):
        bar_time = df.index[i].time() if hasattr(df.index[i], "time") else df.index[i].to_pydatetime().time()
        us_start = SESSION_HOURS["us"]["start"]
        us_end = time(16, 0)
        if not (us_start <= bar_time <= us_end):
            return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                     f"Outside US session: {bar_time}", atr)

    # Momentum: EMA9 > EMA21 and MACD rising
    ema_bull = current["ema_fast"] > current["ema_medium"]
    ema_bear = current["ema_fast"] < current["ema_medium"]

    macd_rising = current["macd_hist"] > prev1["macd_hist"] and current["macd_hist"] > 0
    macd_falling = current["macd_hist"] < prev1["macd_hist"] and current["macd_hist"] < 0

    rsi = current["rsi"]
    vol_ok = current.get("volume_ratio", 1.0) > 1.3

    signal = "none"
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    trend_dir = ""
    reason = ""

    if ema_bull and macd_rising and vol_ok and 45 < rsi < 75:
        signal = "buy"
        entry_price = price
        stop_loss = entry_price - 1.5 * atr
        take_profit = entry_price + 3.0 * atr
        trend_dir = "ny_momentum_up"
        reason = (
            f"NY MOM LONG: EMA9>21, MACD rising, "
            f"RSI={rsi:.1f}, vol={current.get('volume_ratio', 1):.1f}x"
        )
    elif ema_bear and macd_falling and vol_ok and 25 < rsi < 55:
        signal = "sell"
        entry_price = price
        stop_loss = entry_price + 1.5 * atr
        take_profit = entry_price - 3.0 * atr
        trend_dir = "ny_momentum_down"
        reason = (
            f"NY MOM SHORT: EMA9<21, MACD falling, "
            f"RSI={rsi:.1f}, vol={current.get('volume_ratio', 1):.1f}x"
        )
    else:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"No momentum: EMA_bull={ema_bull}, MACD_rising={macd_rising}, "
                                 f"RSI={rsi:.1f}", atr)

    sl_distance = abs(entry_price - stop_loss)
    contract_value = CONTRACT_VALUES.get(symbol, 100_000)
    lots, risk_amount, _ = calculate_position_size(
        cfg.current_equity, cfg.risk_per_trade, sl_distance, contract_value
    )

    return build_signal_dict(
        symbol, strategy_name, signal, entry_price, stop_loss, take_profit,
        lots, risk_amount, reason, atr, session="us", trend_direction=trend_dir,
        confidence="medium",
    )


def strategy_forex_trend_swing(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """
    Forex Trend Following Swing (1-3 day hold)
    ===========================================
    Signal: EMA50/200 trend, 4H pullback to EMA20.
    SL: 2.0x ATR, TP: 4.0x ATR (1:2 R:R)
    Risk: 0.5%, max 1 trade per 2 days.

    Works for: USDCHF, EURUSD, GBPUSD, USDJPY
    """
    symbol = cfg.symbol
    if not symbol:
        return build_signal_dict("UNKNOWN", "FX_TREND_SWING", "none", 0, 0, 0, 0, 0,
                                 "No symbol specified", 0)
    strategy_name = f"{symbol}_TREND_SWING"

    if len(df) < 300:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data", 0)

    df = add_indicators(df, ema_fast=20, ema_medium=50, ema_slow=200,
                        rsi_period=14, atr_period=14)

    i = -1
    current = df.iloc[i]
    atr = current["atr"]
    price = current["close"]

    # Prop firm compliance
    compliance_ok, compliance_reason = check_prop_firm_compliance(
        cfg.current_equity, cfg.peak_equity, cfg.daily_pnl,
        cfg.daily_dd_limit, cfg.max_dd_limit,
        cfg.trades_today, cfg.max_trades_per_day,
        cfg.consistency_limit_pct,
    )
    if not compliance_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"COMPLIANCE FAIL: {compliance_reason}", atr)

    atr_ok, atr_reason = check_min_atr(symbol, atr)
    if not atr_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"ATR FILTER: {atr_reason}", atr)

    trend_up = current["ema_medium"] > current["ema_slow"]
    trend_down = current["ema_medium"] < current["ema_slow"]

    if not (trend_up or trend_down):
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "No clear trend", atr)

    ema20_dist = abs(price - current["ema_fast"])
    pullback_zone = ema20_dist < 0.5 * atr

    if not pullback_zone:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"No pullback: dist={ema20_dist:.5f}", atr)

    rsi = current["rsi"]
    macd_hist = current.get("macd_hist", 0)

    signal = "none"
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    trend_dir = ""
    reason = ""

    if trend_up and 35 < rsi < 65 and macd_hist > -0.001:
        signal = "buy"
        entry_price = price
        stop_loss = entry_price - 2.0 * atr
        take_profit = entry_price + 4.0 * atr
        trend_dir = "swing_uptrend"
        reason = f"SWING LONG: EMA50>200, pullback EMA20, RSI={rsi:.1f}"
    elif trend_down and 35 < rsi < 65 and macd_hist < 0.001:
        signal = "sell"
        entry_price = price
        stop_loss = entry_price + 2.0 * atr
        take_profit = entry_price - 4.0 * atr
        trend_dir = "swing_downtrend"
        reason = f"SWING SHORT: EMA50<200, pullback EMA20, RSI={rsi:.1f}"
    else:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"Filters: RSI={rsi:.1f}, MACD={macd_hist:.6f}", atr)

    sl_distance = abs(entry_price - stop_loss)
    contract_value = CONTRACT_VALUES.get(symbol, 100_000)
    lots, risk_amount, _ = calculate_position_size(
        cfg.current_equity, cfg.risk_per_trade, sl_distance, contract_value
    )

    return build_signal_dict(
        symbol, strategy_name, signal, entry_price, stop_loss, take_profit,
        lots, risk_amount, reason, atr, session="london", trend_direction=trend_dir,
        confidence="medium",
    )


def strategy_forex_range_scalp(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """
    Forex Range Scalping (Asian Session)
    =====================================
    Signal: Bollinger Band bounce in ranging market during Asian session.
    Uses RSI for confirmation of reversal.
    SL: 1.0x ATR, TP: 2.0x ATR (1:2 R:R)
    Session: Asian 00:00-08:00 GMT
    Risk: 0.5%, max 2 trades per session.

    Works for: GBPUSD, EURUSD, USDJPY
    """
    symbol = cfg.symbol
    if not symbol:
        return build_signal_dict("UNKNOWN", "FX_RANGE_SCALP", "none", 0, 0, 0, 0, 0,
                                 "No symbol specified", 0)
    strategy_name = f"{symbol}_RANGE_SCALP"

    if len(df) < 100:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data", 0)

    df = add_indicators(df, ema_fast=9, ema_medium=21, ema_slow=50,
                        rsi_period=7, atr_period=7)

    i = -1
    current = df.iloc[i]
    prev1 = df.iloc[i - 1]
    atr = current["atr"]
    price = current["close"]

    # Prop firm compliance
    compliance_ok, compliance_reason = check_prop_firm_compliance(
        cfg.current_equity, cfg.peak_equity, cfg.daily_pnl,
        cfg.daily_dd_limit, cfg.max_dd_limit,
        cfg.trades_today, cfg.max_trades_per_day,
        cfg.consistency_limit_pct,
    )
    if not compliance_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"COMPLIANCE FAIL: {compliance_reason}", atr)

    atr_ok, atr_reason = check_min_atr(symbol, atr)
    if not atr_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"ATR FILTER: {atr_reason}", atr)

    # Session filter: Asian session only
    if isinstance(df.index, pd.DatetimeIndex):
        bar_time = df.index[i].time() if hasattr(df.index[i], "time") else df.index[i].to_pydatetime().time()
        asian_start = SESSION_HOURS["asian"]["start"]
        asian_end = SESSION_HOURS["asian"]["end"]
        if not (asian_start <= bar_time <= asian_end):
            return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                     f"Outside Asian session: {bar_time}", atr)

    # Range market detection: Bollinger width < 0.01 (1%) for forex
    bb_width = current.get("bb_width", 0)
    ranging = bb_width < 0.01

    if not ranging:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"Not ranging: BB_width={bb_width:.5f}", atr)

    # Bollinger Band bounce signals
    near_lower = price <= current["bb_lower"] + 0.2 * atr
    near_upper = price >= current["bb_upper"] - 0.2 * atr

    rsi = current["rsi"]
    rsi_bounce_up = (prev1["rsi"] < 30) and (rsi > prev1["rsi"])
    rsi_bounce_down = (prev1["rsi"] > 70) and (rsi < prev1["rsi"])

    signal = "none"
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    trend_dir = ""
    reason = ""

    if near_lower and rsi_bounce_up:
        signal = "buy"
        entry_price = price
        stop_loss = entry_price - 1.0 * atr
        take_profit = entry_price + 2.0 * atr
        trend_dir = "range_bounce_up"
        reason = (
            f"SCALP LONG: BB lower bounce, RSI {prev1['rsi']:.1f}->{rsi:.1f}, "
            f"BB_width={bb_width:.5f}"
        )
    elif near_upper and rsi_bounce_down:
        signal = "sell"
        entry_price = price
        stop_loss = entry_price + 1.0 * atr
        take_profit = entry_price - 2.0 * atr
        trend_dir = "range_bounce_down"
        reason = (
            f"SCALP SHORT: BB upper bounce, RSI {prev1['rsi']:.1f}->{rsi:.1f}, "
            f"BB_width={bb_width:.5f}"
        )
    else:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"No setup: near_lower={near_lower}, near_upper={near_upper}, "
                                 f"RSI={rsi:.1f}", atr)

    sl_distance = abs(entry_price - stop_loss)
    contract_value = CONTRACT_VALUES.get(symbol, 100_000)
    lots, risk_amount, _ = calculate_position_size(
        cfg.current_equity, cfg.risk_per_trade, sl_distance, contract_value
    )

    return build_signal_dict(
        symbol, strategy_name, signal, entry_price, stop_loss, take_profit,
        lots, risk_amount, reason, atr, session="asian", trend_direction=trend_dir,
        confidence="medium",
    )


def strategy_forex_scalp(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """
    Forex Session Scalping (EMA cross + RSI, 15-30 min hold)
    =========================================================
    Signal: Fast EMA cross with RSI and volume in session.
    SL: 1.0x ATR, TP: 2.0x ATR
    Session: London or US
    Risk: 0.5%, max 2 trades per session.
    """
    symbol = cfg.symbol
    if not symbol:
        return build_signal_dict("UNKNOWN", "FX_SCALP", "none", 0, 0, 0, 0, 0,
                                 "No symbol specified", 0)
    strategy_name = f"{symbol}_SCALP"

    if len(df) < 100:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data", 0)

    df = add_indicators(df, ema_fast=9, ema_medium=21, ema_slow=50,
                        rsi_period=7, atr_period=7, volume_ma_period=10)

    i = -1
    current = df.iloc[i]
    prev1 = df.iloc[i - 1]
    atr = current["atr"]
    price = current["close"]

    # Prop firm compliance
    compliance_ok, compliance_reason = check_prop_firm_compliance(
        cfg.current_equity, cfg.peak_equity, cfg.daily_pnl,
        cfg.daily_dd_limit, cfg.max_dd_limit,
        cfg.trades_today, cfg.max_trades_per_day,
        cfg.consistency_limit_pct,
    )
    if not compliance_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"COMPLIANCE FAIL: {compliance_reason}", atr)

    atr_ok, atr_reason = check_min_atr(symbol, atr)
    if not atr_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"ATR FILTER: {atr_reason}", atr)

    # Session filter: London or US
    if isinstance(df.index, pd.DatetimeIndex):
        bar_time = df.index[i].time() if hasattr(df.index[i], "time") else df.index[i].to_pydatetime().time()
        london_start = SESSION_HOURS["london"]["start"]
        london_end = SESSION_HOURS["london"]["end"]
        us_start = SESSION_HOURS["us"]["start"]
        us_end = time(18, 0)
        in_session = (london_start <= bar_time <= london_end) or (us_start <= bar_time <= us_end)
        if not in_session:
            return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                     f"Outside session: {bar_time}", atr)

    # EMA cross
    cross_up = (prev1["ema_fast"] <= prev1["ema_medium"]) and (current["ema_fast"] > current["ema_medium"])
    cross_down = (prev1["ema_fast"] >= prev1["ema_medium"]) and (current["ema_fast"] < current["ema_medium"])

    rsi = current["rsi"]
    vol_ok = current.get("volume_ratio", 1.0) > 1.2

    signal = "none"
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    trend_dir = ""
    reason = ""

    if cross_up and 40 < rsi < 70 and vol_ok:
        signal = "buy"
        entry_price = price
        stop_loss = entry_price - 1.0 * atr
        take_profit = entry_price + 2.0 * atr
        trend_dir = "up"
        reason = (
            f"SCALP LONG: EMA9x21 cross, RSI={rsi:.1f}, "
            f"vol={current.get('volume_ratio', 1):.1f}x"
        )
    elif cross_down and 30 < rsi < 60 and vol_ok:
        signal = "sell"
        entry_price = price
        stop_loss = entry_price + 1.0 * atr
        take_profit = entry_price - 2.0 * atr
        trend_dir = "down"
        reason = (
            f"SCALP SHORT: EMA9x21 cross, RSI={rsi:.1f}, "
            f"vol={current.get('volume_ratio', 1):.1f}x"
        )
    else:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"No signal: cross_up={cross_up}, RSI={rsi:.1f}", atr)

    sl_distance = abs(entry_price - stop_loss)
    contract_value = CONTRACT_VALUES.get(symbol, 100_000)
    lots, risk_amount, _ = calculate_position_size(
        cfg.current_equity, cfg.risk_per_trade, sl_distance, contract_value
    )

    confidence = "high" if current.get("volume_ratio", 1) > 2.0 else "medium"
    return build_signal_dict(
        symbol, strategy_name, signal, entry_price, stop_loss, take_profit,
        lots, risk_amount, reason, atr, session="london/us", trend_direction=trend_dir,
        confidence=confidence,
    )


# ═══════════════════════════════════════════════════════════════
# === VOLUME-BASED & SMART MONEY STRATEGIES ===
# ═══════════════════════════════════════════════════════════════

def _calculate_volume_profile(df: pd.DataFrame, lookback: int = 100, num_bins: int = 24) -> Tuple[float, float, float]:
    """
    Calculate rolling volume profile: POC, VAH, VAL.

    Returns:
        (poc_price, vah_price, val_price)
        POC = price level with highest volume
        VAH/VAL = Value Area High/Low (contains ~70% of volume)
    """
    window = df.iloc[-lookback:].copy()
    if len(window) < lookback // 2:
        return 0.0, 0.0, 0.0

    price_min = window["low"].min()
    price_max = window["high"].max()
    if price_max <= price_min:
        return window["close"].iloc[-1], price_max, price_min

    # Create price bins and sum volume per bin
    bins = np.linspace(price_min, price_max, num_bins + 1)
    bin_centers = (bins[:-1] + bins[1:]) / 2

    # Assign each candle's volume to bins based on typical price
    typical = (window["high"] + window["low"] + window["close"]) / 3
    volumes = window["volume"].values if "volume" in window.columns else np.ones(len(window))

    vol_per_bin = np.zeros(num_bins)
    for i in range(num_bins):
        mask = (typical.values >= bins[i]) & (typical.values < bins[i + 1])
        vol_per_bin[i] = volumes[mask].sum()

    # Handle edge case for max price
    vol_per_bin[-1] += volumes[typical.values >= bins[-1]].sum()

    if vol_per_bin.sum() <= 0:
        return window["close"].iloc[-1], price_max, price_min

    # POC = bin with highest volume
    poc_idx = np.argmax(vol_per_bin)
    poc = bin_centers[poc_idx]

    # Value Area: find contiguous region around POC containing 70% of volume
    total_vol = vol_per_bin.sum()
    target_vol = total_vol * 0.70

    # Expand outward from POC until we hit 70% of volume
    current_vol = vol_per_bin[poc_idx]
    low_idx = poc_idx
    high_idx = poc_idx

    while current_vol < target_vol and (low_idx > 0 or high_idx < num_bins - 1):
        vol_below = vol_per_bin[low_idx - 1] if low_idx > 0 else 0
        vol_above = vol_per_bin[high_idx + 1] if high_idx < num_bins - 1 else 0

        if vol_above >= vol_below and high_idx < num_bins - 1:
            high_idx += 1
            current_vol += vol_above
        elif low_idx > 0:
            low_idx -= 1
            current_vol += vol_below
        else:
            break

    val = bin_centers[low_idx]
    vah = bin_centers[high_idx]

    return poc, vah, val


def _calculate_vwap(df: pd.DataFrame, anchor_idx: int = 0) -> Tuple[pd.Series, pd.Series]:
    """
    Calculate anchored VWAP with standard deviation bands.

    Parameters:
        df: DataFrame with high, low, close, volume
        anchor_idx: Index to anchor VWAP from (0 = start of df)

    Returns:
        (vwap_series, std_dev_series)
    """
    window = df.iloc[anchor_idx:].copy()
    typical_price = (window["high"] + window["low"] + window["close"]) / 3
    volume = window["volume"] if "volume" in window.columns else pd.Series(1.0, index=window.index)

    cum_vol_x_price = (typical_price * volume).cumsum()
    cum_vol = volume.cumsum()

    vwap = cum_vol_x_price / cum_vol.replace(0, np.nan)

    # Standard deviation of typical price from VWAP, weighted by volume
    squared_dev = ((typical_price - vwap) ** 2) * volume
    cum_squared_dev = squared_dev.cumsum()
    cum_vol_safe = cum_vol.replace(0, np.nan)
    variance = cum_squared_dev / cum_vol_safe
    std_dev = np.sqrt(variance)

    # Reindex back to full DataFrame
    full_vwap = pd.Series(np.nan, index=df.index)
    full_std = pd.Series(np.nan, index=df.index)
    full_vwap.loc[vwap.index] = vwap
    full_std.loc[std_dev.index] = std_dev

    # Forward fill so we always have values
    full_vwap = full_vwap.ffill()
    full_std = full_std.ffill()

    return full_vwap, full_std


def _find_swing_points(df: pd.DataFrame, lookback: int = 50, window: int = 5) -> Tuple[float, float]:
    """
    Find recent swing high and swing low.

    Parameters:
        df: DataFrame with high, low
        lookback: How many bars to look back
        window: Number of bars on each side for swing confirmation

    Returns:
        (swing_high, swing_low)
    """
    if len(df) < lookback + window * 2:
        return df["high"].iloc[-1], df["low"].iloc[-1]

    recent = df.iloc[-lookback:]
    swing_high = recent["high"].max()
    swing_low = recent["low"].min()

    return swing_high, swing_low


def strategy_volume_profile_poc(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """
    Volume Profile Point of Control (POC) Bounce Strategy
    ======================================================
    Logic:
    - Calculate rolling volume profile (lookback 100 candles)
    - Find POC (price with highest volume in the range)
    - Find Value Area (70% of volume) -> VAH (high) and VAL (low)
    - When price returns to POC from outside VA -> trade the bounce
    - Bullish: price below VAL, returns to POC with volume > avg
    - Bearish: price above VAH, returns to POC with volume > avg

    SL: 1.5x ATR beyond the entry side of VA
    TP: 3.0x ATR toward the opposite side of VA
    Risk: 0.5% per trade
    Max 1 trade per 4 hours

    Expected: 70-75% WR in ranging markets
    """
    symbol = cfg.symbol or "UNKNOWN"
    strategy_name = f"{symbol}_VP_POC_BOUNCE"

    if len(df) < 200:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data (< 200 bars)", 0)

    df = add_indicators(df, ema_fast=cfg.ema_fast, ema_medium=cfg.ema_medium,
                        ema_slow=cfg.ema_slow, rsi_period=cfg.rsi_period,
                        atr_period=cfg.atr_period)

    i = -1
    current = df.iloc[i]
    prev = df.iloc[i - 1]
    atr = current["atr"]
    price = current["close"]

    # Prop firm compliance
    compliance_ok, compliance_reason = check_prop_firm_compliance(
        cfg.current_equity, cfg.peak_equity, cfg.daily_pnl,
        cfg.daily_dd_limit, cfg.max_dd_limit,
        cfg.trades_today, cfg.max_trades_per_day,
        cfg.consistency_limit_pct,
    )
    if not compliance_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"COMPLIANCE FAIL: {compliance_reason}", atr)

    atr_ok, atr_reason = check_min_atr(symbol, atr)
    if not atr_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"ATR FILTER: {atr_reason}", atr)

    # Calculate volume profile
    poc, vah, val = _calculate_volume_profile(df, lookback=100, num_bins=24)
    if poc <= 0 or vah <= 0 or val <= 0:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Volume profile calculation failed", atr)

    va_range = vah - val
    if va_range < atr * 0.5:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"VA too narrow: {va_range:.4f}", atr)

    # Position relative to Value Area
    prev_inside_va = val <= prev["close"] <= vah

    # Volume confirmation: volume > 1.2x average
    vol_confirmed = current.get("volume_ratio", 1.0) > 1.2 if "volume_ratio" in current else True

    # RSI for confirmation
    rsi = current["rsi"]

    signal = "none"
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    trend_dir = ""
    reason = ""

    # Define price position conditions
    price_inside_va = val <= price <= vah
    price_crossed_up = prev["close"] < val and price >= val
    price_bouncing_off_poc = abs(price - poc) < 0.3 * atr and prev["close"] < poc and price >= poc
    price_crossed_down = prev["close"] > vah and price <= vah
    price_rejecting_poc = abs(price - poc) < 0.3 * atr and prev["close"] > poc and price <= poc

    # Bullish: price was below VAL, now returning toward POC from below
    if (price_inside_va and price_crossed_up and vol_confirmed and rsi < 60) or \
       (price_bouncing_off_poc and vol_confirmed and rsi < 65):
        signal = "buy"
        entry_price = price
        stop_loss = entry_price - 1.5 * atr
        take_profit = entry_price + 3.0 * atr
        if take_profit <= entry_price:
            take_profit = vah if vah > entry_price else entry_price + 3.0 * atr
        trend_dir = "vp_poc_bounce_up"
        reason = (
            f"VP POC LONG: price={price:.2f} reentered VA "
            f"(VAL={val:.2f}, POC={poc:.2f}, VAH={vah:.2f}), "
            f"RSI={rsi:.1f}, vol={current.get('volume_ratio', 1):.1f}x"
        )

    # Bearish: price was above VAH, now returning toward POC from above
    elif (price_inside_va and price_crossed_down and vol_confirmed and rsi > 40) or \
         (price_rejecting_poc and vol_confirmed and rsi > 35):
        signal = "sell"
        entry_price = price
        stop_loss = entry_price + 1.5 * atr
        take_profit = entry_price - 3.0 * atr
        if take_profit >= entry_price:
            take_profit = val if val < entry_price else entry_price - 3.0 * atr
        trend_dir = "vp_poc_bounce_down"
        reason = (
            f"VP POC SHORT: price={price:.2f} reentered VA "
            f"(VAH={vah:.2f}, POC={poc:.2f}, VAL={val:.2f}), "
            f"RSI={rsi:.1f}, vol={current.get('volume_ratio', 1):.1f}x"
        )

    if signal == "none":
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"No VP setup: price={price:.2f}, POC={poc:.2f}, "
                                 f"VA=[{val:.2f}-{vah:.2f}], vol_ok={vol_confirmed}", atr)

    # Position sizing
    sl_distance = abs(entry_price - stop_loss)
    contract_value = CONTRACT_VALUES.get(symbol, 1)
    lots, risk_amount, _ = calculate_position_size(
        cfg.current_equity, cfg.risk_per_trade, sl_distance, contract_value
    )

    confidence = "high" if current.get("volume_ratio", 1) > 1.8 else "medium"
    return build_signal_dict(
        symbol, strategy_name, signal, entry_price, stop_loss, take_profit,
        lots, risk_amount, reason, atr, session="", trend_direction=trend_dir,
        confidence=confidence,
    )


def strategy_vwap_reversion(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """
    VWAP (Volume Weighted Average Price) Mean Reversion
    ====================================================
    Logic:
    - Calculate anchored VWAP (anchor at session open)
    - Calculate standard deviation bands (1 sigma, 2 sigma, 3 sigma)
    - When price hits 2 sigma band with RSI > 70 (overbought) or < 30 (oversold)
    - Trade reversion back toward VWAP
    - Volume must be > 1.2x average to confirm conviction

    SL: Beyond 3 sigma band
    TP: VWAP line
    Risk: 0.5% per trade
    Max 2 trades per session

    Expected: 55-65% WR
    """
    symbol = cfg.symbol or "UNKNOWN"
    strategy_name = f"{symbol}_VWAP_REVERSION"

    if len(df) < 100:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data (< 100 bars)", 0)

    df = add_indicators(df, ema_fast=cfg.ema_fast, ema_medium=cfg.ema_medium,
                        ema_slow=cfg.ema_slow, rsi_period=cfg.rsi_period,
                        atr_period=cfg.atr_period)

    i = -1
    current = df.iloc[i]
    prev1 = df.iloc[i - 1]
    atr = current["atr"]
    price = current["close"]

    # Prop firm compliance
    compliance_ok, compliance_reason = check_prop_firm_compliance(
        cfg.current_equity, cfg.peak_equity, cfg.daily_pnl,
        cfg.daily_dd_limit, cfg.max_dd_limit,
        cfg.trades_today, cfg.max_trades_per_day,
        cfg.consistency_limit_pct,
    )
    if not compliance_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"COMPLIANCE FAIL: {compliance_reason}", atr)

    atr_ok, atr_reason = check_min_atr(symbol, atr)
    if not atr_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"ATR FILTER: {atr_reason}", atr)

    # Calculate VWAP with standard deviation bands
    vwap, std_dev = _calculate_vwap(df, anchor_idx=0)

    current_vwap = vwap.iloc[i]
    current_std = std_dev.iloc[i]
    prev_vwap = vwap.iloc[i - 1]
    prev_std = std_dev.iloc[i - 1]

    if pd.isna(current_vwap) or pd.isna(current_std) or current_std <= 0:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "VWAP calculation failed", atr)

    # Sigma bands
    upper_2sigma = current_vwap + 2.0 * current_std
    lower_2sigma = current_vwap - 2.0 * current_std
    upper_3sigma = current_vwap + 3.0 * current_std
    lower_3sigma = current_vwap - 3.0 * current_std

    # Volume confirmation
    vol_confirmed = current.get("volume_ratio", 1.0) > 1.2 if "volume_ratio" in current else True

    # RSI
    rsi = current["rsi"]

    signal = "none"
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    trend_dir = ""
    reason = ""

    # Define VWAP band conditions
    price_at_or_below_2sigma = price <= lower_2sigma or prev1["close"] <= (prev_vwap - 2.0 * prev_std)
    price_reverting_up = price > prev1["close"]  # Current bar moving up
    price_at_or_above_2sigma = price >= upper_2sigma or prev1["close"] >= (prev_vwap + 2.0 * prev_std)
    price_reverting_down = price < prev1["close"]  # Current bar moving down

    # Long: Price hit or exceeded 2 sigma lower band, RSI oversold, reverting toward VWAP
    if price_at_or_below_2sigma and vol_confirmed and rsi < 35 and price_reverting_up:
        signal = "buy"
        entry_price = price
        stop_loss = lower_3sigma - 0.5 * atr  # Beyond 3 sigma
        take_profit = current_vwap  # Target: VWAP
        if take_profit <= entry_price:
            take_profit = entry_price + 2.0 * atr
        trend_dir = "vwap_revert_up"
        reason = (
            f"VWAP REVERT LONG: price={price:.2f} at/below 2sigma "
            f"(VWAP={current_vwap:.2f}, 2s={lower_2sigma:.2f}), "
            f"RSI={rsi:.1f}, vol={current.get('volume_ratio', 1):.1f}x"
        )

    # Short: Price hit or exceeded 2 sigma upper band, RSI overbought, reverting toward VWAP
    elif price_at_or_above_2sigma and vol_confirmed and rsi > 65 and price_reverting_down:
        signal = "sell"
        entry_price = price
        stop_loss = upper_3sigma + 0.5 * atr  # Beyond 3 sigma
        take_profit = current_vwap  # Target: VWAP
        if take_profit >= entry_price:
            take_profit = entry_price - 2.0 * atr
        trend_dir = "vwap_revert_down"
        reason = (
            f"VWAP REVERT SHORT: price={price:.2f} at/above 2sigma "
            f"(VWAP={current_vwap:.2f}, 2s={upper_2sigma:.2f}), "
            f"RSI={rsi:.1f}, vol={current.get('volume_ratio', 1):.1f}x"
        )

    if signal == "none":
        # Check if we're near VWAP already - no trade needed
        dist_from_vwap = abs(price - current_vwap) / current_std if current_std > 0 else 0
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"No VWAP setup: price={price:.2f}, VWAP={current_vwap:.2f}, "
                                 f"dist={dist_from_vwap:.1f}sigma, RSI={rsi:.1f}", atr)

    # Position sizing
    sl_distance = abs(entry_price - stop_loss)
    contract_value = CONTRACT_VALUES.get(symbol, 1)
    lots, risk_amount, _ = calculate_position_size(
        cfg.current_equity, cfg.risk_per_trade, sl_distance, contract_value
    )

    confidence = "high" if current.get("volume_ratio", 1) > 1.8 else "medium"
    return build_signal_dict(
        symbol, strategy_name, signal, entry_price, stop_loss, take_profit,
        lots, risk_amount, reason, atr, session="", trend_direction=trend_dir,
        confidence=confidence,
    )


def strategy_delta_divergence(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """
    Volume Delta / CVD Divergence Strategy
    ========================================
    Logic:
    - Calculate Volume Delta per candle (ask_vol - bid_vol proxy)
    - Calculate Cumulative Volume Delta (CVD)
    - Bullish divergence: price makes lower low, CVD makes higher low
    - Bearish divergence: price makes higher high, CVD makes lower high
    - Entry on divergence confirmation + EMA20 support

    SL: 1.5x ATR
    TP: 3.0x ATR
    Risk: 0.5% per trade
    Max 1 trade per 6 hours

    Expected: 55-65% WR
    """
    symbol = cfg.symbol or "UNKNOWN"
    strategy_name = f"{symbol}_DELTA_DIVERGENCE"

    if len(df) < 200:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data (< 200 bars)", 0)

    df = add_indicators(df, ema_fast=cfg.ema_fast, ema_medium=cfg.ema_medium,
                        ema_slow=cfg.ema_slow, rsi_period=cfg.rsi_period,
                        atr_period=cfg.atr_period)

    i = -1
    current = df.iloc[i]
    atr = current["atr"]
    price = current["close"]

    # Prop firm compliance
    compliance_ok, compliance_reason = check_prop_firm_compliance(
        cfg.current_equity, cfg.peak_equity, cfg.daily_pnl,
        cfg.daily_dd_limit, cfg.max_dd_limit,
        cfg.trades_today, cfg.max_trades_per_day,
        cfg.consistency_limit_pct,
    )
    if not compliance_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"COMPLIANCE FAIL: {compliance_reason}", atr)

    atr_ok, atr_reason = check_min_atr(symbol, atr)
    if not atr_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"ATR FILTER: {atr_reason}", atr)

    # Calculate Volume Delta using (close - open) / (high - low) * volume as proxy
    hl_range = df["high"] - df["low"]
    hl_range = hl_range.replace(0, np.nan)

    bullish_ratio = (df["close"] - df["open"]) / hl_range
    bullish_ratio = bullish_ratio.fillna(0).clip(-1, 1)

    volume = df["volume"] if "volume" in df.columns else pd.Series(1000.0, index=df.index)
    delta = bullish_ratio * volume

    # Cumulative Volume Delta
    cvd = delta.cumsum()

    # Need at least 20 bars of lookback for divergence detection
    div_lookback = 20
    if len(df) < div_lookback + 5:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data for divergence", atr)

    # Find recent price lows/highs and CVD values
    recent_prices = df["close"].iloc[-div_lookback:]
    recent_cvd = cvd.iloc[-div_lookback:]

    # Get the lowest price and its CVD in the lookback
    price_low_idx = recent_prices.idxmin()
    price_high_idx = recent_prices.idxmax()
    price_low = recent_prices.min()
    price_high = recent_prices.max()
    cvd_at_price_low = cvd.loc[price_low_idx]
    cvd_at_price_high = cvd.loc[price_high_idx]

    # Get current CVD and compare to recent extremes
    current_cvd = cvd.iloc[i]

    # Bullish divergence: price makes lower low but CVD makes higher low
    price_near_low = abs(price - price_low) < 0.5 * atr or price < price_low
    cvd_higher_low = current_cvd > cvd_at_price_low

    # Bearish divergence: price makes higher high but CVD makes lower high
    price_near_high = abs(price - price_high) < 0.5 * atr or price > price_high
    cvd_lower_high = current_cvd < cvd_at_price_high

    # Volume confirmation
    vol_confirmed = current.get("volume_ratio", 1.0) > 1.2 if "volume_ratio" in current else True

    # RSI
    rsi = current["rsi"]

    # EMA20 support/resistance
    above_ema20 = price > current["ema_fast"]
    below_ema20 = price < current["ema_fast"]

    signal = "none"
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    trend_dir = ""
    reason = ""

    # Bullish divergence: price lower low + CVD higher low + EMA20 support
    if price_near_low and cvd_higher_low and above_ema20 and vol_confirmed and rsi < 50:
        signal = "buy"
        entry_price = price
        stop_loss = entry_price - 1.5 * atr
        take_profit = entry_price + 3.0 * atr
        trend_dir = "delta_div_bullish"
        reason = (
            f"DELTA DIV LONG: price near low={price_low:.2f} "
            f"but CVD rising ({cvd_at_price_low:.0f}->{current_cvd:.0f}), "
            f"RSI={rsi:.1f}, vol={current.get('volume_ratio', 1):.1f}x"
        )

    # Bearish divergence: price higher high + CVD lower high + EMA20 resistance
    elif price_near_high and cvd_lower_high and below_ema20 and vol_confirmed and rsi > 50:
        signal = "sell"
        entry_price = price
        stop_loss = entry_price + 1.5 * atr
        take_profit = entry_price - 3.0 * atr
        trend_dir = "delta_div_bearish"
        reason = (
            f"DELTA DIV SHORT: price near high={price_high:.2f} "
            f"but CVD falling ({cvd_at_price_high:.0f}->{current_cvd:.0f}), "
            f"RSI={rsi:.1f}, vol={current.get('volume_ratio', 1):.1f}x"
        )

    if signal == "none":
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"No divergence: price_low={price_low:.2f}, price_high={price_high:.2f}, "
                                 f"cvd_low={cvd_at_price_low:.0f}, cvd_high={cvd_at_price_high:.0f}, "
                                 f"current_cvd={current_cvd:.0f}, RSI={rsi:.1f}", atr)

    # Position sizing
    sl_distance = abs(entry_price - stop_loss)
    contract_value = CONTRACT_VALUES.get(symbol, 1)
    lots, risk_amount, _ = calculate_position_size(
        cfg.current_equity, cfg.risk_per_trade, sl_distance, contract_value
    )

    confidence = "high" if vol_confirmed and abs(current_cvd - cvd_at_price_low) > abs(cvd_at_price_high - cvd_at_price_low) * 0.3 else "medium"
    return build_signal_dict(
        symbol, strategy_name, signal, entry_price, stop_loss, take_profit,
        lots, risk_amount, reason, atr, session="", trend_direction=trend_dir,
        confidence=confidence,
    )


def strategy_fvg_mitigation(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """
    Smart Money Concepts: Fair Value Gap (FVG) Mitigation Entry
    ============================================================
    Logic:
    - Detect FVG: 3-candle pattern where candle 1 high < candle 3 low (bullish FVG)
    - Or candle 1 low > candle 3 high (bearish FVG)
    - Wait for price to return to the FVG zone (mitigation)
    - Entry at 50% of FVG with stop beyond the FVG
    - FVGs fill 70-80% of the time -> high probability setup

    SL: Beyond the FVG extreme
    TP: 2.0x the FVG width (1:2 R:R minimum)
    Risk: 0.5% per trade
    Max 1 trade per FVG (once filled, it's done)

    Expected: 60-65% WR, 70-80% fill rate
    """
    symbol = cfg.symbol or "UNKNOWN"
    strategy_name = f"{symbol}_FVG_MITIGATION"

    if len(df) < 100:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data (< 100 bars)", 0)

    df = add_indicators(df, ema_fast=cfg.ema_fast, ema_medium=cfg.ema_medium,
                        ema_slow=cfg.ema_slow, rsi_period=cfg.rsi_period,
                        atr_period=cfg.atr_period)

    i = -1
    current = df.iloc[i]
    atr = current["atr"]
    price = current["close"]

    # Prop firm compliance
    compliance_ok, compliance_reason = check_prop_firm_compliance(
        cfg.current_equity, cfg.peak_equity, cfg.daily_pnl,
        cfg.daily_dd_limit, cfg.max_dd_limit,
        cfg.trades_today, cfg.max_trades_per_day,
        cfg.consistency_limit_pct,
    )
    if not compliance_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"COMPLIANCE FAIL: {compliance_reason}", atr)

    atr_ok, atr_reason = check_min_atr(symbol, atr)
    if not atr_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"ATR FILTER: {atr_reason}", atr)

    # Scan recent history for FVGs and check for mitigation
    fvg_lookback = 30  # Look back 30 bars for FVGs
    if len(df) < fvg_lookback + 5:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data for FVG scan", atr)

    # Check the most recent potential FVGs for mitigation
    bullish_fvg_found = False
    bearish_fvg_found = False
    fvg_top = 0.0
    fvg_bottom = 0.0
    fvg_width = 0.0
    fvg_type = ""

    # Scan for bullish FVG: c1_high < c3_low (gap up)
    for offset in range(3, min(fvg_lookback, len(df) - 3)):
        c1 = df.iloc[-(offset + 2)]
        c3 = df.iloc[-offset]

        # Bullish FVG: candle 1 high < candle 3 low
        if c1["high"] < c3["low"]:
            gap_top = c3["low"]
            gap_bottom = c1["high"]

            # Check if price has returned to/mitigated the FVG (current price is within or near FVG)
            if gap_bottom * 0.999 <= price <= gap_top * 1.001:
                bullish_fvg_found = True
                fvg_top = gap_top
                fvg_bottom = gap_bottom
                fvg_width = gap_top - gap_bottom
                fvg_type = "bullish"
                break

        # Bearish FVG: candle 1 low > candle 3 high
        if c1["low"] > c3["high"]:
            gap_top = c1["low"]
            gap_bottom = c3["high"]

            # Check if price has returned to/mitigated the FVG
            if gap_bottom * 0.999 <= price <= gap_top * 1.001:
                bearish_fvg_found = True
                fvg_top = gap_top
                fvg_bottom = gap_bottom
                fvg_width = gap_top - gap_bottom
                fvg_type = "bearish"
                break

    if not (bullish_fvg_found or bearish_fvg_found):
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "No FVG mitigation setup found", atr)

    # Volume confirmation
    vol_confirmed = current.get("volume_ratio", 1.0) > 1.1 if "volume_ratio" in current else True

    # RSI filter
    rsi = current["rsi"]

    signal = "none"
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    trend_dir = ""
    reason = ""

    # Bullish FVG mitigation entry
    if bullish_fvg_found and vol_confirmed and rsi < 65:
        signal = "buy"
        entry_price = price
        # SL below the FVG bottom
        stop_loss = fvg_bottom - 1.0 * atr
        # TP: 2x FVG width (1:2 minimum R:R), or toward the FVG top + extension
        tp_from_width = entry_price + 2.0 * fvg_width
        tp_from_fvg_top = fvg_top + 1.0 * atr
        take_profit = max(tp_from_width, tp_from_fvg_top)
        trend_dir = "fvg_bullish_mitigation"
        reason = (
            f"FVG LONG: mitigating bullish FVG [{fvg_bottom:.2f}-{fvg_top:.2f}], "
            f"width={fvg_width:.2f}, entry={entry_price:.2f}, "
            f"RSI={rsi:.1f}, vol={current.get('volume_ratio', 1):.1f}x"
        )

    # Bearish FVG mitigation entry
    elif bearish_fvg_found and vol_confirmed and rsi > 35:
        signal = "sell"
        entry_price = price
        # SL above the FVG top
        stop_loss = fvg_top + 1.0 * atr
        # TP: 2x FVG width
        tp_from_width = entry_price - 2.0 * fvg_width
        tp_from_fvg_bottom = fvg_bottom - 1.0 * atr
        take_profit = min(tp_from_width, tp_from_fvg_bottom)
        trend_dir = "fvg_bearish_mitigation"
        reason = (
            f"FVG SHORT: mitigating bearish FVG [{fvg_bottom:.2f}-{fvg_top:.2f}], "
            f"width={fvg_width:.2f}, entry={entry_price:.2f}, "
            f"RSI={rsi:.1f}, vol={current.get('volume_ratio', 1):.1f}x"
        )

    if signal == "none":
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"FVG found but filters not met: type={fvg_type}, "
                                 f"RSI={rsi:.1f}, vol_ok={vol_confirmed}", atr)

    # Ensure minimum R:R of 1:1.5
    sl_dist = abs(entry_price - stop_loss)
    tp_dist = abs(take_profit - entry_price)
    if tp_dist / sl_dist < 1.5 and sl_dist > 0:
        if signal == "buy":
            take_profit = entry_price + 1.5 * sl_dist
        else:
            take_profit = entry_price - 1.5 * sl_dist

    # Position sizing
    sl_distance = abs(entry_price - stop_loss)
    contract_value = CONTRACT_VALUES.get(symbol, 1)
    lots, risk_amount, _ = calculate_position_size(
        cfg.current_equity, cfg.risk_per_trade, sl_distance, contract_value
    )

    confidence = "high" if fvg_width > atr * 0.5 else "medium"
    return build_signal_dict(
        symbol, strategy_name, signal, entry_price, stop_loss, take_profit,
        lots, risk_amount, reason, atr, session="", trend_direction=trend_dir,
        confidence=confidence,
    )


def strategy_liquidity_sweep(df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """
    Liquidity Sweep + FVG Reclaim Strategy
    ========================================
    Logic:
    - Identify recent swing highs/lows (liquidity pools)
    - Detect sweep: wick goes above swing high but closes below (bullish fakeout)
    - Or wick goes below swing low but closes above (bearish fakeout)
    - After sweep, look for FVG formation in reclaim direction
    - Entry on FVG mitigation after sweep confirmation

    SL: Beyond the sweep wick extreme
    TP: 3.0x ATR toward next liquidity pool
    Risk: 0.5% per trade
    Max 1 trade per sweep

    Expected: 61% WR, 2.17 PF (from 2600-trade backtest)
    """
    symbol = cfg.symbol or "UNKNOWN"
    strategy_name = f"{symbol}_LIQUIDITY_SWEEP"

    if len(df) < 200:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data (< 200 bars)", 0)

    df = add_indicators(df, ema_fast=cfg.ema_fast, ema_medium=cfg.ema_medium,
                        ema_slow=cfg.ema_slow, rsi_period=cfg.rsi_period,
                        atr_period=cfg.atr_period)

    i = -1
    current = df.iloc[i]
    atr = current["atr"]
    price = current["close"]

    # Prop firm compliance
    compliance_ok, compliance_reason = check_prop_firm_compliance(
        cfg.current_equity, cfg.peak_equity, cfg.daily_pnl,
        cfg.daily_dd_limit, cfg.max_dd_limit,
        cfg.trades_today, cfg.max_trades_per_day,
        cfg.consistency_limit_pct,
    )
    if not compliance_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"COMPLIANCE FAIL: {compliance_reason}", atr)

    atr_ok, atr_reason = check_min_atr(symbol, atr)
    if not atr_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"ATR FILTER: {atr_reason}", atr)

    # Find recent swing points (liquidity pools)
    swing_lookback = 50
    swing_high, swing_low = _find_swing_points(df, lookback=swing_lookback, window=5)

    # Volume confirmation
    vol_confirmed = current.get("volume_ratio", 1.0) > 1.2 if "volume_ratio" in current else True

    # RSI
    rsi = current["rsi"]

    signal = "none"
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    trend_dir = ""
    reason = ""

    # === Bullish sweep: wick above swing high, close below (fakeout) ===
    sweep_up_detected = False
    sweep_down_detected = False
    sweep_wick_high = 0.0
    sweep_wick_low = 0.0

    # Check current and previous 2 bars for sweep patterns
    for bar_idx in [i, i - 1, i - 2]:
        bar = df.iloc[bar_idx]
        bar_prev = df.iloc[bar_idx - 1]

        # Bullish sweep: wick went above recent swing high but close is below
        if bar["high"] > swing_high and bar["close"] < swing_high and bar["close"] < bar_prev["close"]:
            sweep_up_detected = True
            sweep_wick_high = bar["high"]

        # Bearish sweep: wick went below recent swing low but close is above
        if bar["low"] < swing_low and bar["close"] > swing_low and bar["close"] > bar_prev["close"]:
            sweep_down_detected = True
            sweep_wick_low = bar["low"]

    # After bullish sweep: look for reclaim (price moving back up, forming FVG)
    if sweep_up_detected:
        # Check for FVG formation in the reclaim direction (bullish FVG)
        for offset in range(3, min(15, len(df) - 3)):
            c1 = df.iloc[-(offset + 2)]
            c3 = df.iloc[-offset]

            # Bullish FVG after sweep
            if c1["high"] < c3["low"]:
                fvg_top = c3["low"]
                fvg_bottom = c1["high"]

                # Price is now mitigating the bullish FVG
                if fvg_bottom * 0.999 <= price <= fvg_top * 1.001:
                    if vol_confirmed and rsi < 65:
                        signal = "buy"
                        entry_price = price
                        stop_loss = sweep_wick_high + 0.5 * atr if sweep_wick_high > 0 else entry_price - 2.0 * atr
                        take_profit = entry_price + 3.0 * atr
                        trend_dir = "liq_sweep_bullish"
                        reason = (
                            f"LIQ SWEEP LONG: swept high={swing_high:.2f} "
                            f"(wick={sweep_wick_high:.2f}), now mitigating FVG "
                            f"[{fvg_bottom:.2f}-{fvg_top:.2f}], "
                            f"RSI={rsi:.1f}, vol={current.get('volume_ratio', 1):.1f}x"
                        )
                        break

    # After bearish sweep: look for reclaim (price moving back down, forming FVG)
    elif sweep_down_detected:
        # Check for FVG formation in the reclaim direction (bearish FVG)
        for offset in range(3, min(15, len(df) - 3)):
            c1 = df.iloc[-(offset + 2)]
            c3 = df.iloc[-offset]

            # Bearish FVG after sweep
            if c1["low"] > c3["high"]:
                fvg_top = c1["low"]
                fvg_bottom = c3["high"]

                # Price is now mitigating the bearish FVG
                if fvg_bottom * 0.999 <= price <= fvg_top * 1.001:
                    if vol_confirmed and rsi > 35:
                        signal = "sell"
                        entry_price = price
                        stop_loss = sweep_wick_low - 0.5 * atr if sweep_wick_low > 0 else entry_price + 2.0 * atr
                        take_profit = entry_price - 3.0 * atr
                        trend_dir = "liq_sweep_bearish"
                        reason = (
                            f"LIQ SWEEP SHORT: swept low={swing_low:.2f} "
                            f"(wick={sweep_wick_low:.2f}), now mitigating FVG "
                            f"[{fvg_bottom:.2f}-{fvg_top:.2f}], "
                            f"RSI={rsi:.1f}, vol={current.get('volume_ratio', 1):.1f}x"
                        )
                        break

    if signal == "none":
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"No sweep setup: sweep_up={sweep_up_detected}, "
                                 f"sweep_down={sweep_down_detected}, "
                                 f"swing_high={swing_high:.2f}, swing_low={swing_low:.2f}, "
                                 f"RSI={rsi:.1f}", atr)

    # Position sizing
    sl_distance = abs(entry_price - stop_loss)
    contract_value = CONTRACT_VALUES.get(symbol, 1)
    lots, risk_amount, _ = calculate_position_size(
        cfg.current_equity, cfg.risk_per_trade, sl_distance, contract_value
    )

    confidence = "high" if vol_confirmed else "medium"
    return build_signal_dict(
        symbol, strategy_name, signal, entry_price, stop_loss, take_profit,
        lots, risk_amount, reason, atr, session="", trend_direction=trend_dir,
        confidence=confidence,
    )


def strategy_mtf_confluence(df_m5: pd.DataFrame, df_h1: pd.DataFrame,
                            df_h4: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """
    Multi-Timeframe Confluence: H4 Bias + H1 Setup + M5 Entry
    ==========================================================
    Logic:
    - H4: Determine trend (EMA50 > EMA200 = bullish bias)
    - H1: Look for pullback to EMA20 in H4 direction
    - M5: Wait for reversal candle at H1 EMA20 + volume spike
    - Entry on M5 close in H4 direction

    SL: Below H1 swing low (for longs) / Above H1 swing high (for shorts)
    TP: Next H4 resistance / 2x SL distance
    Risk: 0.5% per trade
    Max 1 trade per H4 candle

    Expected: 60-68% WR (highest robustness score)

    Note: This strategy requires 3 DataFrames of different timeframes.
    """
    symbol = cfg.symbol or "UNKNOWN"
    strategy_name = f"{symbol}_MTF_CONFLUENCE"

    # Validate inputs
    if df_m5 is None or df_h1 is None or df_h4 is None:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Missing timeframe data (need M5, H1, H4)", 0)

    if len(df_m5) < 100 or len(df_h1) < 100 or len(df_h4) < 50:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "Insufficient data for MTF analysis", 0)

    # Add indicators to each timeframe
    df_m5 = add_indicators(df_m5, ema_fast=cfg.ema_fast, ema_medium=cfg.ema_medium,
                           ema_slow=cfg.ema_slow, rsi_period=cfg.rsi_period,
                           atr_period=cfg.atr_period)
    df_h1 = add_indicators(df_h1, ema_fast=cfg.ema_fast, ema_medium=cfg.ema_medium,
                           ema_slow=cfg.ema_slow, rsi_period=cfg.rsi_period,
                           atr_period=cfg.atr_period)
    df_h4 = add_indicators(df_h4, ema_fast=cfg.ema_fast, ema_medium=cfg.ema_medium,
                           ema_slow=cfg.ema_slow, rsi_period=cfg.rsi_period,
                           atr_period=cfg.atr_period)

    # Current bars
    m5_current = df_m5.iloc[-1]
    m5_prev = df_m5.iloc[-2]
    h1_current = df_h1.iloc[-1]
    h4_current = df_h4.iloc[-1]

    atr = m5_current["atr"]
    price = m5_current["close"]

    # Prop firm compliance
    compliance_ok, compliance_reason = check_prop_firm_compliance(
        cfg.current_equity, cfg.peak_equity, cfg.daily_pnl,
        cfg.daily_dd_limit, cfg.max_dd_limit,
        cfg.trades_today, cfg.max_trades_per_day,
        cfg.consistency_limit_pct,
    )
    if not compliance_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"COMPLIANCE FAIL: {compliance_reason}", atr)

    atr_ok, atr_reason = check_min_atr(symbol, atr)
    if not atr_ok:
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"ATR FILTER: {atr_reason}", atr)

    # === H4 BIAS: Trend Direction ===
    h4_bullish = h4_current["ema_medium"] > h4_current["ema_slow"]
    h4_bearish = h4_current["ema_medium"] < h4_current["ema_slow"]

    if not (h4_bullish or h4_bearish):
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 "No clear H4 trend", atr)

    # === H1 SETUP: Pullback to EMA20 in H4 direction ===
    h1_price = h1_current["close"]
    h1_ema20 = h1_current["ema_fast"]

    # For longs: H1 price near EMA20 (pullback in bullish H4 trend)
    h1_atr = h1_current["atr"] if not pd.isna(h1_current.get("atr", np.nan)) else atr * 3
    h1_pullback_long = abs(h1_price - h1_ema20) < 1.0 * h1_atr

    # For shorts: H1 price near EMA20 (pullback in bearish H4 trend)
    h1_pullback_short = abs(h1_price - h1_ema20) < 1.0 * h1_atr

    # === M5 ENTRY: Reversal candle at H1 EMA20 zone + volume ===
    # Check if M5 price is in the H1 EMA20 zone (approximate)
    m5_near_h1_ema20 = abs(price - h1_ema20) < 2.0 * atr

    # Volume spike on M5
    vol_spike = m5_current.get("volume_ratio", 1.0) > 1.5 if "volume_ratio" in m5_current else True

    # M5 reversal candle pattern
    m5_bullish_reversal = (m5_current["close"] > m5_prev["close"] and
                           m5_prev["close"] <= m5_prev["open"] and
                           m5_current["close"] > m5_current["open"])
    m5_bearish_reversal = (m5_current["close"] < m5_prev["close"] and
                           m5_prev["close"] >= m5_prev["open"] and
                           m5_current["close"] < m5_current["open"])

    # RSI confirmation
    rsi = m5_current["rsi"]

    signal = "none"
    entry_price = 0.0
    stop_loss = 0.0
    take_profit = 0.0
    trend_dir = ""
    reason = ""

    # === LONG SETUP: H4 bullish + H1 pullback to EMA20 + M5 reversal ===
    if h4_bullish and h1_pullback_long and m5_near_h1_ema20 and m5_bullish_reversal and vol_spike and rsi < 65:
        signal = "buy"
        entry_price = price

        # SL: below H1 swing low
        h1_swing_low = df_h1["low"].iloc[-20:].min()
        stop_loss = min(h1_swing_low - 0.5 * atr, entry_price - 1.5 * atr)

        # TP: 2x SL distance (minimum 1:2 R:R)
        sl_dist = entry_price - stop_loss
        take_profit = entry_price + 2.0 * sl_dist

        trend_dir = "mtf_confluence_long"
        reason = (
            f"MTF LONG: H4 bullish (EMA50>EMA200), H1 pullback to EMA20={h1_ema20:.2f}, "
            f"M5 reversal at {price:.2f}, RSI={rsi:.1f}, vol={m5_current.get('volume_ratio', 1):.1f}x"
        )

    # === SHORT SETUP: H4 bearish + H1 pullback to EMA20 + M5 reversal ===
    elif h4_bearish and h1_pullback_short and m5_near_h1_ema20 and m5_bearish_reversal and vol_spike and rsi > 35:
        signal = "sell"
        entry_price = price

        # SL: above H1 swing high
        h1_swing_high = df_h1["high"].iloc[-20:].max()
        stop_loss = max(h1_swing_high + 0.5 * atr, entry_price + 1.5 * atr)

        # TP: 2x SL distance
        sl_dist = stop_loss - entry_price
        take_profit = entry_price - 2.0 * sl_dist

        trend_dir = "mtf_confluence_short"
        reason = (
            f"MTF SHORT: H4 bearish (EMA50<EMA200), H1 pullback to EMA20={h1_ema20:.2f}, "
            f"M5 reversal at {price:.2f}, RSI={rsi:.1f}, vol={m5_current.get('volume_ratio', 1):.1f}x"
        )

    if signal == "none":
        h4_trend = "bullish" if h4_bullish else "bearish" if h4_bearish else "none"
        return build_signal_dict(symbol, strategy_name, "none", 0, 0, 0, 0, 0,
                                 f"No MTF setup: H4={h4_trend}, "
                                 f"H1_pullback_long={h1_pullback_long}, "
                                 f"H1_pullback_short={h1_pullback_short}, "
                                 f"M5_near_H1_EMA20={m5_near_h1_ema20}, "
                                 f"M5_bull_rev={m5_bullish_reversal}, "
                                 f"M5_bear_rev={m5_bearish_reversal}, "
                                 f"vol_spike={vol_spike}, RSI={rsi:.1f}", atr)

    # Position sizing
    sl_distance = abs(entry_price - stop_loss)
    contract_value = CONTRACT_VALUES.get(symbol, 1)
    lots, risk_amount, _ = calculate_position_size(
        cfg.current_equity, cfg.risk_per_trade, sl_distance, contract_value
    )

    confidence = "high" if vol_spike and ((h4_bullish and m5_bullish_reversal) or (h4_bearish and m5_bearish_reversal)) else "medium"
    return build_signal_dict(
        symbol, strategy_name, signal, entry_price, stop_loss, take_profit,
        lots, risk_amount, reason, atr, session="", trend_direction=trend_dir,
        confidence=confidence,
    )


# ═══════════════════════════════════════════════════════════════
# === BACKTEST / METRICS HELPERS ===
# ═══════════════════════════════════════════════════════════════

def calculate_metrics(trades: List[Dict[str, Any]], initial_balance: float = 10_000.0) -> Dict[str, Any]:
    """
    Calculate performance metrics from a list of completed trade dicts.
    Each trade dict must have: 'entry_price', 'stop_loss', 'take_profit', 'signal',
    and optionally 'exit_price' or 'result' ('win'/'loss').

    Returns standard metrics dict for prop firm evaluation.
    """
    if not trades:
        return {
            "total_trades": 0,
            "winning_trades": 0,
            "losing_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "total_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "sharpe_ratio": 0.0,
            "avg_risk_reward": 0.0,
            "avg_trade_pnl": 0.0,
            "best_day_pct": 0.0,
            "consistency_score": 1.0,
            "final_balance": initial_balance,
        }

    balance = initial_balance
    equity_curve = [balance]
    wins = 0
    losses = 0
    total_profit = 0.0
    total_loss = 0.0
    daily_pnls: Dict[str, float] = {}

    for trade in trades:
        signal = trade.get("signal", "")
        entry = trade.get("entry_price", 0)
        sl = trade.get("stop_loss", 0)
        tp = trade.get("take_profit", 0)
        risk = trade.get("risk_amount", 0)

        if entry <= 0 or signal == "none":
            continue

        # Determine outcome: if exit_price provided use it, else simulate
        exit_price = trade.get("exit_price")
        result = trade.get("result")

        if result == "win":
            pnl = risk * 2.0  # Assume 1:2 R:R achieved
            wins += 1
            total_profit += pnl
        elif result == "loss":
            pnl = -risk
            losses += 1
            total_loss += abs(pnl)
        elif exit_price and exit_price > 0:
            if signal == "buy":
                pnl = (exit_price - entry) / (entry - sl) * risk if (entry - sl) != 0 else 0
            else:
                pnl = (entry - exit_price) / (sl - entry) * risk if (sl - entry) != 0 else 0
            if pnl > 0:
                wins += 1
                total_profit += pnl
            else:
                losses += 1
                total_loss += abs(pnl)
        else:
            # Default: assume 50% win rate simulation for metrics
            sl_dist = abs(entry - sl)
            tp_dist = abs(tp - entry)
            if sl_dist > 0:
                rr = tp_dist / sl_dist
                # Simulate outcome based on random but use fixed for reproducibility
                expected_pnl = (rr * risk * 0.45) - (risk * 0.55)  # 45% WR assumption
                pnl = expected_pnl
                if pnl > 0:
                    wins += 1
                    total_profit += pnl
                else:
                    losses += 1
                    total_loss += abs(pnl)
            else:
                pnl = 0

        balance += pnl
        equity_curve.append(balance)

        # Track daily PnL
        ts = trade.get("timestamp", "")
        if ts:
            day_key = ts[:10] if len(ts) >= 10 else ts
            daily_pnls[day_key] = daily_pnls.get(day_key, 0.0) + pnl

    total_trades = wins + losses
    win_rate = wins / total_trades if total_trades > 0 else 0.0
    profit_factor = total_profit / total_loss if total_loss > 0 else float("inf")

    # Max drawdown
    peak = initial_balance
    max_dd = 0.0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # Total return
    total_return_pct = (balance - initial_balance) / initial_balance * 100 if initial_balance > 0 else 0

    # Sharpe (simplified)
    returns = [equity_curve[i] / equity_curve[i - 1] - 1 for i in range(1, len(equity_curve))]
    if len(returns) > 1 and np.std(returns) > 0:
        sharpe = (np.mean(returns) / np.std(returns)) * np.sqrt(252)
    else:
        sharpe = 0.0

    # Risk/reward
    avg_rr = np.mean([t.get("risk_reward", 0) for t in trades if t.get("risk_reward", 0) > 0]) if trades else 0

    # Consistency: best day / total profits
    best_day = max(daily_pnls.values()) if daily_pnls else 0
    total_pnl = sum(daily_pnls.values())
    consistency_score = 1.0 - (best_day / total_pnl if total_pnl > 0 else 0)

    return {
        "total_trades": total_trades,
        "winning_trades": wins,
        "losing_trades": losses,
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 4),
        "total_return_pct": round(total_return_pct, 4),
        "max_drawdown_pct": round(max_dd * 100, 4),
        "sharpe_ratio": round(sharpe, 4),
        "avg_risk_reward": round(avg_rr, 2),
        "avg_trade_pnl": round((balance - initial_balance) / total_trades, 2) if total_trades > 0 else 0,
        "best_day_pct": round(best_day / initial_balance * 100, 4) if initial_balance > 0 else 0,
        "consistency_score": round(consistency_score, 4),
        "final_balance": round(balance, 2),
        "daily_pnls": daily_pnls,
    }


# ═══════════════════════════════════════════════════════════════
# === STRATEGY REGISTRY ===
# ═══════════════════════════════════════════════════════════════

STRATEGIES = {
    # ── INDICES ──
    "nas100_orb": {
        "name": "NAS100 Opening Range Breakout",
        "symbol": "NAS100",
        "type": "day",
        "category": "indices",
        "func": strategy_nas100_orb,
        "sessions": ["us"],
        "description": "US open 20-bar range breakout with volume confirmation",
    },
    "nas100_trend": {
        "name": "NAS100 Trend Pullback Swing",
        "symbol": "NAS100",
        "type": "swing",
        "category": "indices",
        "func": strategy_nas100_trend_pullback,
        "sessions": ["us"],
        "description": "EMA50/200 trend, pullback to EMA20, 1-2 day hold",
    },
    "nas100_scalp": {
        "name": "NAS100 Session Scalp",
        "symbol": "NAS100",
        "type": "scalp",
        "category": "indices",
        "func": strategy_nas100_scalp,
        "sessions": ["us"],
        "description": "EMA9/21 cross + RSI, 15-30 min hold",
    },
    "us30_orb": {
        "name": "US30 Opening Range Breakout",
        "symbol": "US30",
        "type": "day",
        "category": "indices",
        "func": strategy_us30_orb,
        "sessions": ["us"],
        "description": "US open range breakout, wider stops for Dow",
    },

    # ── CRYPTO ──
    "btc_breakout": {
        "name": "BTC 4H Range Breakout",
        "symbol": "BTCUSD",
        "type": "day",
        "category": "crypto",
        "func": strategy_crypto_breakout,
        "sessions": ["24/7"],
        "description": "4H consolidation range breakout, 24/7",
    },
    "btc_trend": {
        "name": "BTC Trend Swing",
        "symbol": "BTCUSD",
        "type": "swing",
        "category": "crypto",
        "func": strategy_crypto_trend,
        "sessions": ["24/7"],
        "description": "EMA20/50/200 trend following, 1-3 day hold",
    },
    "btc_scalp": {
        "name": "BTC Scalp",
        "symbol": "BTCUSD",
        "type": "scalp",
        "category": "crypto",
        "func": strategy_crypto_scalp,
        "sessions": ["24/7"],
        "description": "EMA cross scalp, 15-30 min hold",
    },
    "eth_breakout": {
        "name": "ETH 4H Range Breakout",
        "symbol": "ETHUSD",
        "type": "day",
        "category": "crypto",
        "func": strategy_crypto_breakout,
        "sessions": ["24/7"],
        "description": "4H consolidation range breakout, 24/7",
    },
    "eth_trend": {
        "name": "ETH Trend Swing",
        "symbol": "ETHUSD",
        "type": "swing",
        "category": "crypto",
        "func": strategy_crypto_trend,
        "sessions": ["24/7"],
        "description": "EMA20/50/200 trend following, 1-3 day hold",
    },
    "eth_scalp": {
        "name": "ETH Scalp",
        "symbol": "ETHUSD",
        "type": "scalp",
        "category": "crypto",
        "func": strategy_crypto_scalp,
        "sessions": ["24/7"],
        "description": "EMA cross scalp, 15-30 min hold",
    },
    "sol_breakout": {
        "name": "SOL 4H Range Breakout",
        "symbol": "SOLUSD",
        "type": "day",
        "category": "crypto",
        "func": strategy_crypto_breakout,
        "sessions": ["24/7"],
        "description": "4H consolidation range breakout, 24/7",
    },
    "sol_trend": {
        "name": "SOL Trend Swing",
        "symbol": "SOLUSD",
        "type": "swing",
        "category": "crypto",
        "func": strategy_crypto_trend,
        "sessions": ["24/7"],
        "description": "EMA20/50/200 trend following, 1-3 day hold",
    },
    "sol_scalp": {
        "name": "SOL Scalp",
        "symbol": "SOLUSD",
        "type": "scalp",
        "category": "crypto",
        "func": strategy_crypto_scalp,
        "sessions": ["24/7"],
        "description": "EMA cross scalp, 15-30 min hold",
    },
    "doge_breakout": {
        "name": "DOGE 4H Range Breakout",
        "symbol": "DOGEUSD",
        "type": "day",
        "category": "crypto",
        "func": strategy_crypto_breakout,
        "sessions": ["24/7"],
        "description": "4H consolidation range breakout, 24/7",
    },
    "doge_scalp": {
        "name": "DOGE Scalp",
        "symbol": "DOGEUSD",
        "type": "scalp",
        "category": "crypto",
        "func": strategy_crypto_scalp,
        "sessions": ["24/7"],
        "description": "EMA cross scalp, 15-30 min hold",
    },
    "xrp_breakout": {
        "name": "XRP 4H Range Breakout",
        "symbol": "XRPUSD",
        "type": "day",
        "category": "crypto",
        "func": strategy_crypto_breakout,
        "sessions": ["24/7"],
        "description": "4H consolidation range breakout, 24/7",
    },
    "xrp_scalp": {
        "name": "XRP Scalp",
        "symbol": "XRPUSD",
        "type": "scalp",
        "category": "crypto",
        "func": strategy_crypto_scalp,
        "sessions": ["24/7"],
        "description": "EMA cross scalp, 15-30 min hold",
    },
    "ltc_breakout": {
        "name": "LTC 4H Range Breakout",
        "symbol": "LTCUSD",
        "type": "day",
        "category": "crypto",
        "func": strategy_crypto_breakout,
        "sessions": ["24/7"],
        "description": "4H consolidation range breakout, 24/7",
    },
    "ltc_scalp": {
        "name": "LTC Scalp",
        "symbol": "LTCUSD",
        "type": "scalp",
        "category": "crypto",
        "func": strategy_crypto_scalp,
        "sessions": ["24/7"],
        "description": "EMA cross scalp, 15-30 min hold",
    },

    # ── COMMODITIES / METALS ──
    "xau_asian": {
        "name": "XAUUSD Asian Breakout",
        "symbol": "XAUUSD",
        "type": "day",
        "category": "metals",
        "func": strategy_xauusd_asian_breakout,
        "sessions": ["london"],
        "description": "London open breaks Asian range",
    },
    "xau_ny": {
        "name": "XAUUSD NY Momentum",
        "symbol": "XAUUSD",
        "type": "day",
        "category": "metals",
        "func": strategy_xauusd_ny_momentum,
        "sessions": ["us"],
        "description": "NY open MACD momentum",
    },
    "xau_swing": {
        "name": "XAUUSD Swing Trend",
        "symbol": "XAUUSD",
        "type": "swing",
        "category": "metals",
        "func": strategy_xauusd_swing,
        "sessions": ["london", "us"],
        "description": "EMA50/200 trend, EMA20 pullback, 1-3 day",
    },
    "xau_scalp": {
        "name": "XAUUSD BB Scalp",
        "symbol": "XAUUSD",
        "type": "scalp",
        "category": "metals",
        "func": strategy_xauusd_scalp,
        "sessions": ["london", "us"],
        "description": "Bollinger Band bounce, 15-30 min",
    },

    # ── ENERGIES ──
    "xti_session": {
        "name": "XTIUSD US Session Breakout",
        "symbol": "XTIUSD",
        "type": "day",
        "category": "energies",
        "func": strategy_xtiusd_session,
        "sessions": ["us"],
        "description": "NYMEX open volatility breakout, inventory aware",
    },
    "xti_trend": {
        "name": "XTIUSD Trend Swing",
        "symbol": "XTIUSD",
        "type": "swing",
        "category": "energies",
        "func": strategy_xtiusd_trend,
        "sessions": ["us"],
        "description": "EMA50/200 trend, EMA20 pullback, 1-3 day",
    },

    # ── VOLUME-BASED STRATEGIES ──
    "volume_profile_poc": {
        "name": "Volume Profile POC Bounce",
        "symbol": "NAS100",
        "type": "day",
        "category": "volume_based",
        "func": strategy_volume_profile_poc,
        "sessions": ["us", "london"],
        "description": "Volume Profile POC bounce from outside Value Area, 70-75% WR in ranging markets",
    },
    "vwap_reversion": {
        "name": "VWAP Mean Reversion",
        "symbol": "NAS100",
        "type": "scalp",
        "category": "volume_based",
        "func": strategy_vwap_reversion,
        "sessions": ["us", "london"],
        "description": "VWAP 2-sigma band mean reversion with RSI confirmation, 55-65% WR",
    },
    "delta_divergence": {
        "name": "Volume Delta / CVD Divergence",
        "symbol": "BTCUSD",
        "type": "day",
        "category": "volume_based",
        "func": strategy_delta_divergence,
        "sessions": ["24/7"],
        "description": "CVD divergence with price + EMA20 support, 55-65% WR",
    },

    # ── SMART MONEY CONCEPTS ──
    "fvg_mitigation": {
        "name": "Fair Value Gap Mitigation",
        "symbol": "XAUUSD",
        "type": "day",
        "category": "smart_money",
        "func": strategy_fvg_mitigation,
        "sessions": ["london", "us"],
        "description": "SMC FVG 3-candle pattern mitigation entry, 60-65% WR, 70-80% fill rate",
    },
    "liquidity_sweep": {
        "name": "Liquidity Sweep + FVG Reclaim",
        "symbol": "EURUSD",
        "type": "day",
        "category": "smart_money",
        "func": strategy_liquidity_sweep,
        "sessions": ["london", "us"],
        "description": "Liquidity sweep fakeout followed by FVG reclaim, 61% WR, 2.17 PF",
    },

    # ── MULTI-TIMEFRAME STRATEGIES ──
    "mtf_confluence": {
        "name": "Multi-Timeframe Confluence",
        "symbol": "EURUSD",
        "type": "swing",
        "category": "multi_timeframe",
        "func": strategy_mtf_confluence,
        "sessions": ["london", "us"],
        "description": "H4 bias + H1 setup + M5 entry, highest robustness, 60-68% WR",
    },

    # ── FOREX ──
    "eurusd_london": {
        "name": "EURUSD London Breakout",
        "symbol": "EURUSD",
        "type": "day",
        "category": "forex",
        "func": strategy_forex_london_breakout,
        "sessions": ["london"],
        "description": "London open Asian range breakout",
    },
    "eurusd_ny": {
        "name": "EURUSD NY Momentum",
        "symbol": "EURUSD",
        "type": "day",
        "category": "forex",
        "func": strategy_forex_ny_momentum,
        "sessions": ["us"],
        "description": "Post-London NY continuation",
    },
    "eurusd_trend": {
        "name": "EURUSD Trend Swing",
        "symbol": "EURUSD",
        "type": "swing",
        "category": "forex",
        "func": strategy_forex_trend_swing,
        "sessions": ["london"],
        "description": "EMA50/200 trend, EMA20 pullback",
    },
    "eurusd_scalp": {
        "name": "EURUSD Scalp",
        "symbol": "EURUSD",
        "type": "scalp",
        "category": "forex",
        "func": strategy_forex_scalp,
        "sessions": ["london", "us"],
        "description": "EMA cross scalp",
    },
    "usdjpy_tokyo": {
        "name": "USDJPY London Breakout",
        "symbol": "USDJPY",
        "type": "day",
        "category": "forex",
        "func": strategy_forex_london_breakout,
        "sessions": ["london"],
        "description": "London open breakout, trends well in London",
    },
    "usdjpy_trend": {
        "name": "USDJPY Trend Swing",
        "symbol": "USDJPY",
        "type": "swing",
        "category": "forex",
        "func": strategy_forex_trend_swing,
        "sessions": ["london"],
        "description": "EMA50/200 trend following",
    },
    "usdjpy_scalp": {
        "name": "USDJPY Scalp",
        "symbol": "USDJPY",
        "type": "scalp",
        "category": "forex",
        "func": strategy_forex_scalp,
        "sessions": ["london", "us"],
        "description": "EMA cross scalp",
    },
    "gbpjpy_london": {
        "name": "GBPJPY London Breakout",
        "symbol": "GBPJPY",
        "type": "day",
        "category": "forex",
        "func": strategy_forex_london_breakout,
        "sessions": ["london"],
        "description": "Volatile London session breakout",
    },
    "gbpjpy_trend": {
        "name": "GBPJPY Trend Swing",
        "symbol": "GBPJPY",
        "type": "swing",
        "category": "forex",
        "func": strategy_forex_trend_swing,
        "sessions": ["london"],
        "description": "EMA50/200 trend following for volatile GBPJPY",
    },
    "gbpjpy_scalp": {
        "name": "GBPJPY Scalp",
        "symbol": "GBPJPY",
        "type": "scalp",
        "category": "forex",
        "func": strategy_forex_scalp,
        "sessions": ["london", "us"],
        "description": "EMA cross scalp",
    },
    "gbpusd_range": {
        "name": "GBPUSD Asian Range Scalp",
        "symbol": "GBPUSD",
        "type": "scalp",
        "category": "forex",
        "func": strategy_forex_range_scalp,
        "sessions": ["asian"],
        "description": "Bollinger Band bounce in Asian ranging session",
    },
    "gbpusd_london": {
        "name": "GBPUSD London Breakout",
        "symbol": "GBPUSD",
        "type": "day",
        "category": "forex",
        "func": strategy_forex_london_breakout,
        "sessions": ["london"],
        "description": "London open breakout",
    },
    "gbpusd_trend": {
        "name": "GBPUSD Trend Swing",
        "symbol": "GBPUSD",
        "type": "swing",
        "category": "forex",
        "func": strategy_forex_trend_swing,
        "sessions": ["london"],
        "description": "EMA50/200 trend following",
    },
    "usdchf_trend": {
        "name": "USDCHF Trend Swing",
        "symbol": "USDCHF",
        "type": "swing",
        "category": "forex",
        "func": strategy_forex_trend_swing,
        "sessions": ["london", "us"],
        "description": "EMA50/200 trend, inverse EURUSD correlation",
    },
    "usdchf_london": {
        "name": "USDCHF London Breakout",
        "symbol": "USDCHF",
        "type": "day",
        "category": "forex",
        "func": strategy_forex_london_breakout,
        "sessions": ["london"],
        "description": "London open breakout",
    },
    "usdchf_scalp": {
        "name": "USDCHF Scalp",
        "symbol": "USDCHF",
        "type": "scalp",
        "category": "forex",
        "func": strategy_forex_scalp,
        "sessions": ["london", "us"],
        "description": "EMA cross scalp",
    },
}


# ═══════════════════════════════════════════════════════════════
# === CONVENIENCE FUNCTIONS ===
# ═══════════════════════════════════════════════════════════════

def run_strategy(name: str, df: pd.DataFrame, cfg: StrategyConfig) -> dict:
    """Run a strategy by name from the registry."""
    if name not in STRATEGIES:
        raise ValueError(
            f"Unknown strategy: '{name}'. "
            f"Available: {list(STRATEGIES.keys())}"
        )
    return STRATEGIES[name]["func"](df, cfg)


def get_strategies_for_symbol(symbol: str) -> Dict[str, Dict]:
    """Get all strategies that trade a given symbol."""
    return {k: v for k, v in STRATEGIES.items() if v["symbol"] == symbol}


def get_strategies_for_category(category: str) -> Dict[str, Dict]:
    """Get all strategies for a given category (indices, crypto, metals, energies, forex)."""
    return {k: v for k, v in STRATEGIES.items() if v.get("category") == category}


def get_strategies_for_session(session: str) -> Dict[str, Dict]:
    """Get all strategies active in a given session (asian, london, us, 24/7)."""
    result = {}
    for k, v in STRATEGIES.items():
        if session in v.get("sessions", []):
            result[k] = v
    return result


def list_all_strategies() -> List[Dict[str, Any]]:
    """Return a list of all strategy metadata (for dashboard)."""
    return [
        {
            "id": k,
            "name": v["name"],
            "symbol": v["symbol"],
            "type": v["type"],
            "category": v.get("category", "unknown"),
            "sessions": v.get("sessions", []),
            "description": v.get("description", ""),
        }
        for k, v in STRATEGIES.items()
    ]


def get_strategy_count() -> Dict[str, int]:
    """Get counts of strategies by various dimensions."""
    all_s = list_all_strategies()
    return {
        "total": len(all_s),
        "by_category": {
            cat: len([s for s in all_s if s["category"] == cat])
            for cat in set(s["category"] for s in all_s)
        },
        "by_type": {
            typ: len([s for s in all_s if s["type"] == typ])
            for typ in set(s["type"] for s in all_s)
        },
        "by_symbol": {
            sym: len([s for s in all_s if s["symbol"] == sym])
            for sym in set(s["symbol"] for s in all_s)
        },
    }


def print_strategy_summary():
    """Print a formatted summary of all strategies."""
    counts = get_strategy_count()
    print("=" * 60)
    print("STRATEGY LIBRARY SUMMARY")
    print("=" * 60)
    print(f"\nTotal Strategies: {counts['total']}")
    print(f"\nBy Category:")
    for cat, cnt in sorted(counts["by_category"].items()):
        print(f"  {cat.upper():12s}: {cnt}")
    print(f"\nBy Type:")
    for typ, cnt in sorted(counts["by_type"].items()):
        print(f"  {typ:12s}: {cnt}")
    print(f"\nBy Symbol:")
    for sym, cnt in sorted(counts["by_symbol"].items(), key=lambda x: -x[1]):
        print(f"  {sym:12s}: {cnt}")
    print("=" * 60)


# ═══════════════════════════════════════════════════════════════
# === MAIN / SELF-TEST ===
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print_strategy_summary()
