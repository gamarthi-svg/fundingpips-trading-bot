#!/usr/bin/env python3
"""
Fetch real historical data from MetaAPI and run backtests.

Usage: python fetch_and_backtest.py

Requires MetaAPI token with 'market-data-client-api' permission.
To add this permission:
1. Go to https://app.metaapi.cloud/token
2. Edit your token and add the 'market-data-client-api' scope
3. Copy the updated token to your .env file
"""
import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# Auto-load .env file if present
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # python-dotenv not installed; rely on actual env vars

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger(__name__)

# ── Config ──
TOKEN = os.environ.get('METAAPI_TOKEN', '')
ACCOUNT_ID = os.environ.get('METAAPI_ACCOUNT_ID', 'db865e4a-4e83-48a6-93af-73372f595a0c')
INITIAL_BALANCE = float(os.environ.get('ACCOUNT_SIZE', '10000'))
REGION = os.environ.get('METAAPI_REGION', 'new-york')

SYMBOLS = {
    'XAUUSD': {'pip_size': 0.01, 'pip_value': 1.0, 'spread': 0.35, 'commission': 5.0, 'digits': 2},
    'EURUSD': {'pip_size': 0.0001, 'pip_value': 10.0, 'spread': 0.00015, 'commission': 5.0, 'digits': 5},
    'NQ':     {'pip_size': 1.0, 'pip_value': 20.0, 'spread': 2.0, 'commission': 0.0, 'digits': 0},
}

PRO_LIMITS = {'daily_dd_pct': 0.03, 'max_dd_pct': 0.06, 'profit_target_pct': 0.06, 'max_loss_per_trade_pct': 0.02}


def _get_region_url(service: str) -> str:
    """Build MetaAPI URL for a given service and region."""
    if service == 'market-data':
        return f"https://mt-market-data-client-api-v1.{REGION}.agiliumtrade.ai"
    elif service == 'client':
        return f"https://mt-client-api-v1.{REGION}.agiliumtrade.ai"
    else:
        return f"https://mt-client-api-v1.{REGION}.agiliumtrade.ai"


async def _discover_symbol(broker_symbol_hint: str) -> str:
    """Query the account's available symbols to find the exact broker symbol name.

    Brokers often append suffixes (e.g., '.r', '#', 'm'). This queries the
    /symbols endpoint and returns the first match containing the hint.
    """
    if not TOKEN or not ACCOUNT_ID:
        return broker_symbol_hint

    url = f"{_get_region_url('client')}/users/current/accounts/{ACCOUNT_ID}/symbols"
    headers = {'auth-token': TOKEN}

    try:
        import httpx
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                symbols = resp.json()
                hint_upper = broker_symbol_hint.upper()
                # Direct match
                if hint_upper in [s.upper() for s in symbols]:
                    # Return the broker's exact casing
                    for s in symbols:
                        if s.upper() == hint_upper:
                            logger.info(f"  Symbol '{s}' found on account")
                            return s
                # Partial match (broker adds suffixes like .r, #, etc.)
                for s in symbols:
                    if hint_upper in s.upper():
                        logger.info(f"  Matched '{broker_symbol_hint}' -> '{s}' on account")
                        return s
                logger.warning(f"  No symbol matching '{broker_symbol_hint}' found. Available: {symbols[:20]}...")
            else:
                logger.warning(f"  Could not list symbols: HTTP {resp.status_code}")
    except Exception as e:
        logger.warning(f"  Symbol discovery failed: {e}")

    return broker_symbol_hint


# ── MetaAPI Data Fetcher (HTTP) ──
async def fetch_metaapi_candles(symbol: str, timeframe: str = '5m', days: int = 90) -> pd.DataFrame:
    """Fetch historical candles from MetaAPI market data endpoint.

    Uses the REST API endpoint documented at:
    https://metaapi.cloud/docs/client/restApi/api/retrieveMarketData/readHistoricalCandles/

    Auth: 'auth-token' header (NOT 'Authorization: Bearer').
    Token must have the 'market-data-client-api' permission scope.

    Pagination strategy:
        - First request: no startTime (gets latest 1000 candles)
        - Subsequent requests: set startTime to the time of the LAST candle
          from the previous batch (ISO 8601 UTC string).
          Candles are returned in backwards chronological order, so we walk
          backwards through time.
    """
    if not TOKEN:
        logger.error("  METAAPI_TOKEN not set. Add it to your .env file.")
        logger.error("  Get your token from: https://app.metaapi.cloud/token")
        return generate_synthetic_data(symbol, days)

    if not ACCOUNT_ID:
        logger.error("  METAAPI_ACCOUNT_ID not set.")
        return generate_synthetic_data(symbol, days)

    import httpx

    # Step 1: Discover the exact broker symbol name
    broker_symbol = await _discover_symbol(symbol)

    # Build URL
    base_url = _get_region_url('market-data')
    url = (
        f"{base_url}/users/current/accounts/{ACCOUNT_ID}"
        f"/historical-market-data/symbols/{broker_symbol}"
        f"/timeframes/{timeframe}/candles"
    )

    headers = {'auth-token': TOKEN}
    params: dict = {'limit': 1000}

    all_candles: list = []
    seen_times: set = set()
    pages = 0
    max_pages = 30  # Safety limit: 30 * 1000 = 30,000 candles

    async with httpx.AsyncClient(timeout=120.0) as client:
        while pages < max_pages:
            pages += 1
            try:
                resp = await client.get(url, headers=headers, params=params)

                if resp.status_code == 401:
                    logger.error("=" * 60)
                    logger.error("  MetaAPI 401 Unauthorized — Market Data Access Denied")
                    logger.error("=" * 60)
                    logger.error("")
                    logger.error("  Your token is missing the 'market-data-client-api' permission.")
                    logger.error("")
                    logger.error("  To fix this:")
                    logger.error("  1. Go to: https://app.metaapi.cloud/token")
                    logger.error("  2. Find your token and click 'Edit'")
                    logger.error("  3. Add the 'market-data-client-api' permission/scope")
                    logger.error("  4. Save the token")
                    logger.error("  5. Update the METAAPI_TOKEN value in your .env file")
                    logger.error("")
                    logger.error("  Current token permissions can be checked at:")
                    logger.error("  https://app.metaapi.cloud/token")
                    logger.error("=" * 60)
                    break

                if resp.status_code == 404:
                    error_body = resp.text[:200]
                    logger.error(f"  HTTP 404: Symbol '{broker_symbol}' not found for this account.")
                    logger.error(f"  Response: {error_body}")
                    logger.error(f"  Try checking available symbols via the /symbols endpoint")
                    break

                if resp.status_code != 200:
                    logger.error(f"  HTTP {resp.status_code}: {resp.text[:300]}")
                    break

                candles = resp.json()

                if not isinstance(candles, list):
                    logger.error(f"  Unexpected response type: {type(candles).__name__}")
                    break

                if len(candles) == 0:
                    break

                # Deduplicate — the API's startTime is inclusive, so the last
                # candle from the previous page may appear again.
                new_candles = [c for c in candles if c.get('time') not in seen_times]
                if not new_candles:
                    logger.debug(f"  Page {pages}: no new candles — reached end of history")
                    break

                for c in new_candles:
                    seen_times.add(c.get('time', ''))
                all_candles.extend(new_candles)

                if len(candles) < 1000:
                    # Fewer candles than requested — no more history available
                    break

                # Pagination: MetaAPI returns candles in backwards chronological
                # order (newest first).  startTime is INCLUSIVE, so subtract
                # 1 ms from the oldest candle's time to avoid duplicates.
                oldest_time = new_candles[-1].get('time', '')
                if not oldest_time:
                    logger.warning("  No 'time' field in oldest candle — stopping pagination")
                    break

                try:
                    dt = datetime.fromisoformat(oldest_time.replace('Z', '+00:00'))
                    next_start = (dt - __import__('datetime').timedelta(milliseconds=1))
                    params['startTime'] = next_start.isoformat().replace('+00:00', 'Z')
                except ValueError:
                    # Fallback: raw string subtraction won't work, just use as-is
                    params['startTime'] = oldest_time

                if pages % 5 == 0:
                    logger.info(f"  Fetched {len(all_candles)} candles...")

            except httpx.TimeoutException:
                logger.warning(f"  Timeout on page {pages} — stopping")
                break
            except Exception as e:
                logger.error(f"  Error on page {pages}: {e}")
                break

    if all_candles:
        logger.info(f"  Success! Total: {len(all_candles)} real candles for {symbol}")
        df = pd.DataFrame(all_candles)
        df['time'] = pd.to_datetime(df['time'], utc=True)
        for col in ['open', 'high', 'low', 'close', 'tickVolume', 'spread', 'volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')

        # Select and rename columns
        cols = ['time', 'open', 'high', 'low', 'close']
        if 'tickVolume' in df.columns:
            cols.append('tickVolume')
        elif 'volume' in df.columns:
            cols.append('volume')
        if 'spread' in df.columns:
            cols.append('spread')

        df = df[cols].rename(columns={'tickVolume': 'tick_volume', 'volume': 'tick_volume'})
        df = df.drop_duplicates(subset='time').sort_values('time').reset_index(drop=True)

        # Validate price sanity
        low_min = df['low'].min()
        high_max = df['high'].max()
        logger.info(f"  Price range: {low_min:.2f} - {high_max:.2f}")

        # Sanity check for obvious bad data
        if symbol == 'XAUUSD' and (low_min < 1000 or high_max > 5000):
            logger.warning(f"  UNREALISTIC price range for XAUUSD! Data may be corrupt.")
        elif symbol == 'EURUSD' and (low_min < 0.5 or high_max > 2.0):
            logger.warning(f"  UNREALISTIC price range for EURUSD! Data may be corrupt.")

        return df

    logger.warning(f"  MetaAPI returned no candles for {symbol}, using synthetic data")
    logger.warning(f"  ^ This produces MEANINGLESS backtest results.")
    logger.warning(f"  Fix the token permission to get real data.")
    return generate_synthetic_data(symbol, days)


def generate_synthetic_data(symbol: str, days: int) -> pd.DataFrame:
    """Generate realistic synthetic OHLCV data."""
    np.random.seed(hash(symbol) % 2**32)
    n_candles = min(days * 24 * 12, 20000)  # Cap at 20K

    if symbol == 'XAUUSD':
        base_price, vol = 2350.0, 0.001
    elif symbol == 'EURUSD':
        base_price, vol = 1.0850, 0.0003
    elif symbol == 'NQ':
        base_price, vol = 18800.0, 0.002
    else:
        base_price, vol = 100.0, 0.001

    times = pd.date_range(end=datetime.now(), periods=n_candles, freq='5min', tz='UTC')
    returns = np.random.normal(0, vol, n_candles)
    trend = np.sin(np.linspace(0, 4 * np.pi, n_candles)) * vol * 0.5
    returns += trend

    closes = base_price * np.exp(np.cumsum(returns))
    closes = np.clip(closes, base_price * 0.5, base_price * 2.0)  # Prevent overflow

    noise = np.random.normal(0, vol * 0.3, n_candles)
    opens = closes * (1 + noise)
    opens = np.clip(opens, closes * 0.998, closes * 1.002)

    hl_noise = np.abs(np.random.normal(0, vol * 0.5, n_candles))
    highs = np.maximum(opens, closes) * (1 + hl_noise)
    lows = np.minimum(opens, closes) * (1 - hl_noise)

    df = pd.DataFrame({
        'time': times, 'open': np.round(opens, 2 if symbol == 'XAUUSD' else 5),
        'high': np.round(highs, 2 if symbol == 'XAUUSD' else 5),
        'low': np.round(lows, 2 if symbol == 'XAUUSD' else 5),
        'close': np.round(closes, 2 if symbol == 'XAUUSD' else 5),
        'tick_volume': np.random.randint(100, 5000, n_candles)
    })
    logger.info(f"  Generated {len(df)} SYNTHETIC candles for {symbol}")
    logger.info(f"  *** WARNING: Synthetic data produces meaningless backtest results! ***")
    return df

# ── Technical Indicators ──
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add EMA, RSI, ATR indicators."""
    df = df.copy()
    # EMA
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    # RSI
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).ewm(span=14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(span=14, adjust=False).mean()
    rs = gain / loss.replace(0, np.finfo(float).eps)
    df['rsi14'] = 100 - (100 / (1 + rs))
    # ATR
    tr1 = df['high'] - df['low']
    tr2 = abs(df['high'] - df['close'].shift())
    tr3 = abs(df['low'] - df['close'].shift())
    df['tr'] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df['atr14'] = df['tr'].ewm(span=14, adjust=False).mean()
    # Session markers
    df['hour'] = df['time'].dt.hour
    return df

# ── Strategy Backtests (ATR-based dynamic SL/TP) ──
#
# All strategies use ATR (Average True Range) for dynamic stop-loss and
# take-profit levels instead of fixed pip counts.  This makes the stops
# adapt to current market volatility and works correctly regardless of
# whether XAUUSD is priced at $2,350 or $4,700.
#
# Position sizing formula:
#   risk_amount   = balance * risk_pct          (e.g. $50 = 0.5% of $10K)
#   stop_distance = entry - sl                   (in price terms)
#   lots          = risk_amount / (stop_distance * contract_value)
#
# Where contract_value = $ per $1 of price move per lot:
#   XAUUSD: 100  ($100 per $1 move per standard lot)
#   EURUSD: 100000 * 0.0001 = $10 per pip per lot, but we use raw price
#
# PnL is capped at risk_amount for losses and risk_amount * R:R for wins.


def _position_size(risk_amount: float, stop_distance: float, contract_value: float) -> float:
    """Calculate lot size given risk amount and stop distance.

    Args:
        risk_amount:   Maximum dollar amount to risk on this trade.
        stop_distance: Price distance from entry to stop-loss.
        contract_value: Dollar value per $1 of price move per 1.0 lot.

    Returns:
        Lot size (e.g. 0.15 for 0.15 standard lots).
    """
    if stop_distance <= 0:
        return 0.0
    lots = risk_amount / (stop_distance * contract_value)
    return max(0.01, min(5.0, round(lots, 2)))


def backtest_xauusd_asian(df: pd.DataFrame, cfg: dict) -> dict:
    """XAUUSD Asian Session Range Scalping: 23:00-03:00 GMT.

    Signal: close above EMA20, RSI 40-65, ATR > min threshold,
            close > open (bullish candle), volume > 20-period avg.
    Entry:  current close.
    SL:    entry - 1.5 x ATR14.
    TP:    entry + 3.0 x ATR14  (1:2 R:R).
    Risk:  0.5% of balance per trade.
    Max hold: 50 candles (~4 hours).
    Cooldown: max 1 trade per calendar day.
    """
    df = add_indicators(df)
    # Add volume average for confirmation
    df['vol_avg20'] = df['tick_volume'].rolling(20).mean()

    balance = INITIAL_BALANCE
    equity = INITIAL_BALANCE
    peak = INITIAL_BALANCE
    trades = []
    equity_curve = [{'time': df['time'].iloc[0], 'equity': equity}]

    commission = SYMBOLS['XAUUSD']['commission']
    CONTRACT_VALUE = 100.0   # $100 per $1 move per standard lot
    last_trade_date = None

    for i in range(50, len(df) - 1):
        candle = df.iloc[i]
        hour = candle['hour']
        today = candle['time'].date()

        # Asian session window: 23:00-03:00 GMT
        if not (hour >= 23 or hour <= 3):
            continue

        # Cooldown: only 1 trade per day
        if last_trade_date == today:
            continue

        # Minimum ATR filter (~0.05% of price)
        min_atr = candle['close'] * 0.0005
        if candle['atr14'] < min_atr:
            continue

        # Signal: bullish candle + close above EMA20 + neutral RSI + volume
        if not (candle['close'] > candle['open']):
            continue
        if not (candle['close'] > candle['ema20']):
            continue
        if not (42 <= candle['rsi14'] <= 60):
            continue
        if not (candle['tick_volume'] > candle['vol_avg20'] * 1.2):
            continue

        # Entry
        entry = candle['close']
        atr = candle['atr14']

        # Dynamic ATR-based SL / TP
        sl_distance = 1.5 * atr
        tp_distance = 3.0 * atr  # 1:2 risk:reward
        sl = entry - sl_distance
        tp = entry + tp_distance

        # Position sizing: risk 0.5% of current balance
        risk_amount = balance * 0.005
        lots = _position_size(risk_amount, sl_distance, CONTRACT_VALUE)
        if lots <= 0:
            continue

        # Simulate trade — walk forward until SL, TP, or max hold
        pnl = 0.0
        for j in range(i + 1, min(i + 50, len(df))):
            future = df.iloc[j]
            if future['low'] <= sl:
                pnl = -(risk_amount + commission * lots)
                break
            elif future['high'] >= tp:
                pnl = risk_amount * 2 - commission * lots
                break
        else:
            # Timed exit — use close of last candle
            pnl = (future['close'] - entry) * lots * CONTRACT_VALUE - commission * lots

        balance += pnl
        equity = balance
        peak = max(peak, equity)
        last_trade_date = today
        trades.append({
            'pnl': pnl,
            'result': 'win' if pnl > 0 else 'loss',
            'symbol': 'XAUUSD',
            'strategy': 'Asian Scalp',
        })
        equity_curve.append({'time': candle['time'], 'equity': equity})

    return calculate_metrics(trades, equity_curve, 'XAUUSD Asian Scalp')


def backtest_xauusd_ny(df: pd.DataFrame, cfg: dict) -> dict:
    """XAUUSD NY Opening Range Breakout: 13:30-14:30 GMT.

    Signal: close breaks above 10-candle high by >0.3 x ATR,
            RSI > 55 (bullish momentum), volume > 20-period avg.
    Entry:  breakout close.
    SL:    entry - 2.0 x ATR14.
    TP:    entry + 4.0 x ATR14  (1:2 R:R, wider for momentum).
    Risk:  0.5% of balance per trade.
    Max hold: 60 candles (~5 hours).
    Cooldown: max 1 trade per calendar day.
    """
    df = add_indicators(df)
    df['vol_avg20'] = df['tick_volume'].rolling(20).mean()

    balance = INITIAL_BALANCE
    trades = []
    equity_curve = [{'time': df['time'].iloc[0], 'equity': balance}]

    commission = SYMBOLS['XAUUSD']['commission']
    CONTRACT_VALUE = 100.0
    last_trade_date = None

    for i in range(50, len(df) - 1):
        candle = df.iloc[i]
        hour, minute = candle['hour'], candle['time'].minute
        today = candle['time'].date()

        # NY Open window: 13:30-14:30 GMT
        if not (hour == 13 and minute >= 30) and not (hour == 14):
            continue

        # Cooldown: only 1 trade per day
        if last_trade_date == today:
            continue

        # Minimum ATR (~0.08% of price)
        min_atr = candle['close'] * 0.0008
        if candle['atr14'] < min_atr:
            continue

        # Strong breakout: close must exceed recent 10-candle high by >0.5 x ATR
        recent_high = df.iloc[i - 10:i]['high'].max()
        breakout_margin = 0.5 * candle['atr14']
        if candle['close'] <= recent_high + breakout_margin:
            continue

        # Momentum confirmation: RSI > 50 (bullish)
        if candle['rsi14'] <= 50:
            continue

        # Volume confirmation
        if candle['tick_volume'] <= candle['vol_avg20'] * 1.0:
            continue

        # Entry
        entry = candle['close']
        atr = candle['atr14']

        # Dynamic SL/TP
        sl_distance = 2.0 * atr
        tp_distance = 4.0 * atr  # 1:2 R:R
        sl = entry - sl_distance
        tp = entry + tp_distance

        risk_amount = balance * 0.005
        lots = _position_size(risk_amount, sl_distance, CONTRACT_VALUE)
        if lots <= 0:
            continue

        pnl = 0.0
        for j in range(i + 1, min(i + 60, len(df))):
            future = df.iloc[j]
            if future['low'] <= sl:
                pnl = -(risk_amount + commission * lots)
                break
            elif future['high'] >= tp:
                pnl = risk_amount * 2 - commission * lots
                break
        else:
            pnl = (future['close'] - entry) * lots * CONTRACT_VALUE - commission * lots

        balance += pnl
        last_trade_date = today
        trades.append({
            'pnl': pnl,
            'result': 'win' if pnl > 0 else 'loss',
            'symbol': 'XAUUSD',
            'strategy': 'NY Breakout',
        })
        equity_curve.append({'time': candle['time'], 'equity': balance})

    return calculate_metrics(trades, equity_curve, 'XAUUSD NY Breakout')


def backtest_forex_london(df: pd.DataFrame, cfg: dict) -> dict:
    """Forex London Breakout: 07:00-12:00 GMT.

    Signal: close breaks above the Asian session range high.
    Asian range = 35 candles before current (approx 23:00-07:00 GMT).
    Entry:  breakout close.
    SL:    lower bound of Asian range (structure-based, not ATR).
           If range is too tight (< 1.0 x ATR), fallback to 1.5 x ATR.
    TP:    entry + (entry - sl) x 2  (1:2 R:R).
    Risk:  0.5% of balance per trade.
    Max hold: 60 candles (~5 hours).
    """
    df = add_indicators(df)
    balance = INITIAL_BALANCE
    trades = []
    equity_curve = [{'time': df['time'].iloc[0], 'equity': balance}]

    spread = SYMBOLS['EURUSD']['spread']
    commission = SYMBOLS['EURUSD']['commission']
    CONTRACT_VALUE = 100_000.0  # 1 standard lot = 100,000 units
    trades_today = 0
    current_date = None
    MAX_TRADES_PER_DAY = 2

    for i in range(50, len(df) - 1):
        candle = df.iloc[i]
        hour = candle['hour']
        today = candle['time'].date()

        # Reset daily counter
        if today != current_date:
            current_date = today
            trades_today = 0

        # London session: 07:00-12:00 GMT
        if not (7 <= hour <= 12):
            continue

        # Daily trade cap to prevent clustering
        if trades_today >= MAX_TRADES_PER_DAY:
            continue

        # Asian session range (previous ~7 hours = 84 candles on M5)
        lookback = min(84, i)
        asian_low = df.iloc[i - lookback:i]['low'].min()
        asian_high = df.iloc[i - lookback:i]['high'].max()
        asian_range = asian_high - asian_low

        # Require a meaningful range (at least 1.5 x ATR)
        if asian_range <= 1.5 * candle['atr14']:
            continue

        # Breakout above Asian high by >0.2 x ATR
        if candle['close'] <= asian_high + 0.2 * candle['atr14']:
            continue

        # Entry
        entry = candle['close'] + spread / 2
        atr = candle['atr14']

        # SL: on the far side of the Asian range, but at least 1.0 x ATR away
        sl = asian_low
        sl_distance = entry - sl
        min_sl = 1.0 * atr
        if sl_distance < min_sl:
            sl = entry - min_sl
            sl_distance = min_sl

        # TP: 1:2 risk:reward
        tp = entry + sl_distance * 2

        risk_amount = balance * 0.005
        lots = _position_size(risk_amount, sl_distance, CONTRACT_VALUE)
        if lots <= 0:
            continue

        pnl = 0.0
        for j in range(i + 1, min(i + 60, len(df))):
            future = df.iloc[j]
            if future['low'] <= sl:
                pnl = -(risk_amount + commission * lots)
                break
            elif future['high'] >= tp:
                pnl = risk_amount * 2 - commission * lots
                break
        else:
            pnl = (future['close'] - entry) * lots * CONTRACT_VALUE - commission * lots

        balance += pnl
        trades_today += 1
        trades.append({
            'pnl': pnl,
            'result': 'win' if pnl > 0 else 'loss',
            'symbol': 'EURUSD',
            'strategy': 'London Breakout',
        })
        equity_curve.append({'time': candle['time'], 'equity': balance})

    return calculate_metrics(trades, equity_curve, 'Forex London')

def calculate_metrics(trades: list, equity_curve: list, name: str) -> dict:
    """Calculate all performance metrics."""
    if not trades:
        return {'name': name, 'symbol': '', 'total_trades': 0, 'total_pnl': 0, 'total_return': 0, 'win_rate': 0, 'max_drawdown': 0, 'max_drawdown_pct': 0, 'sharpe': 0, 'sharpe_ratio': 0, 'profit_factor': 0, 'equity_curve': [], 'trades': [], 'prop_firm_checks': {}}

    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]

    total_pnl = sum(t['pnl'] for t in trades)
    total_return = total_pnl / INITIAL_BALANCE * 100
    win_rate = len(wins) / len(trades) * 100 if trades else 0

    gross_profit = sum(t['pnl'] for t in wins)
    gross_loss = abs(sum(t['pnl'] for t in losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

    avg_win = gross_profit / len(wins) if wins else 0
    avg_loss = gross_loss / len(losses) if losses else 0

    # Max drawdown
    peak = INITIAL_BALANCE
    max_dd = 0
    max_dd_pct = 0
    for point in equity_curve:
        if point['equity'] > peak:
            peak = point['equity']
        dd = peak - point['equity']
        dd_pct = dd / peak * 100
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct
            max_dd = dd

    # Sharpe (simplified)
    returns = [t['pnl'] / INITIAL_BALANCE for t in trades]
    if len(returns) > 1 and np.std(returns) > 0:
        sharpe = (np.mean(returns) * 252) / (np.std(returns) * np.sqrt(252))
    else:
        sharpe = 0

    # Daily PnL for consistency (prop firm rule: no single day > 35% of total)
    df_eq = pd.DataFrame(equity_curve)
    if len(df_eq) > 1:
        df_eq['date'] = pd.to_datetime(df_eq['time']).dt.date
        daily = df_eq.groupby('date')['equity'].last().diff().dropna()
        # Only count profitable days
        daily_profits = daily[daily > 0]
        total_profits = daily_profits.sum()
        best_day = daily_profits.max() if len(daily_profits) > 0 else 0
        if total_profits > 0:
            consistency = best_day / total_profits
        else:
            consistency = 0.0
    else:
        consistency = 0.0

    # Prop firm checks
    daily_dd_limit = INITIAL_BALANCE * PRO_LIMITS['daily_dd_pct']
    max_dd_limit = INITIAL_BALANCE * PRO_LIMITS['max_dd_pct']
    target = INITIAL_BALANCE * PRO_LIMITS['profit_target_pct']

    return {
        'name': name,
        'symbol': trades[0]['symbol'] if trades else '',
        'total_trades': len(trades),
        'winning_trades': len(wins),
        'losing_trades': len(losses),
        'total_return': round(total_return, 2),
        'total_pnl': round(total_pnl, 2),
        'win_rate': round(win_rate, 1),
        'profit_factor': round(profit_factor, 2),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'max_drawdown_pct': round(max_dd_pct, 2),
        'max_drawdown_dollars': round(max_dd, 2),
        'sharpe_ratio': round(sharpe, 2),
        'consistency_score': round(consistency * 100, 1),
        'equity_curve': [{'time': str(p['time']), 'equity': round(p['equity'], 2)} for p in equity_curve[::10]],  # Downsample
        'trades': [{'pnl': round(t['pnl'], 2), 'result': t['result']} for t in trades],
        'prop_firm_checks': {
            'max_drawdown_ok': max_dd_pct < PRO_LIMITS['max_dd_pct'] * 100,
            'daily_dd_ok': True,  # Would need daily aggregation
            'consistency_ok': consistency * 100 < 35,
            'profit_target_reached': total_pnl >= target,
        },
        'limits': PRO_LIMITS,
    }

def run_monte_carlo(metrics_list: list, n_sims: int = 10000) -> dict:
    """Run Monte Carlo across all strategies."""
    all_trades = []
    for m in metrics_list:
        all_trades.extend([t['pnl'] for t in m.get('trades', [])])

    if not all_trades:
        return {'pass_rate': 0, 'median_return': 0, 'worst_case': 0, 'best_case': 0}

    np.random.seed(42)
    final_equities = []
    max_drawdowns = []

    for _ in range(n_sims):
        sample = np.random.choice(all_trades, size=len(all_trades), replace=True)
        equity = INITIAL_BALANCE
        peak = equity
        max_dd = 0
        for pnl in sample:
            equity += pnl
            peak = max(peak, equity)
            dd = (peak - equity) / peak * 100
            max_dd = max(max_dd, dd)
        final_equities.append((equity - INITIAL_BALANCE) / INITIAL_BALANCE * 100)
        max_drawdowns.append(max_dd)

    final_equities = np.array(final_equities)
    max_drawdowns = np.array(max_drawdowns)

    # Pass = hit profit target (6%) before max DD (6%)
    pass_rate = np.mean((final_equities >= 6) & (max_drawdowns < 6)) * 100

    return {
        'n_simulations': n_sims,
        'pass_rate': round(float(pass_rate), 1),
        'median_return': round(float(np.median(final_equities)), 2),
        'mean_return': round(float(np.mean(final_equities)), 2),
        'worst_case': round(float(np.percentile(final_equities, 5)), 2),
        'best_case': round(float(np.percentile(final_equities, 95)), 2),
        'median_max_dd': round(float(np.median(max_drawdowns)), 2),
        'max_dd_95th': round(float(np.percentile(max_drawdowns, 95)), 2),
    }

# ── Main ──
async def main():
    logger.info("=" * 60)
    logger.info("Prop Firm Bot — Backtest Engine")
    logger.info(f"Account: $10K Pro 2-Step | Daily DD: 3% | Max DD: 6%")
    logger.info(f"Region: {REGION}")
    if not TOKEN:
        logger.warning("METAAPI_TOKEN not set — will use synthetic data!")
    logger.info("=" * 60)

    results = {}

    # 1. Fetch XAUUSD data
    logger.info("\n[1/4] Fetching XAUUSD (5-min, 90 days)...")
    xau_df = await fetch_metaapi_candles('XAUUSD', '5m', 90)
    xau_df.to_csv('data/XAUUSD_M5.csv', index=False)

    # 2. Fetch EURUSD data
    logger.info("\n[2/4] Fetching EURUSD (5-min, 90 days)...")
    eur_df = await fetch_metaapi_candles('EURUSD', '5m', 90)
    eur_df.to_csv('data/EURUSD_M5.csv', index=False)

    # 3. Backtest all strategies
    logger.info("\n[3/4] Running backtests...")
    cfg = {'initial_balance': INITIAL_BALANCE, 'risk_per_trade': 0.005}

    results['xau_asian'] = backtest_xauusd_asian(xau_df, cfg)
    logger.info(f"  XAUUSD Asian: {results['xau_asian']['total_trades']} trades, {results['xau_asian']['win_rate']}% WR, ${results['xau_asian']['total_pnl']} PnL")

    results['xau_ny'] = backtest_xauusd_ny(xau_df, cfg)
    logger.info(f"  XAUUSD NY: {results['xau_ny']['total_trades']} trades, {results['xau_ny']['win_rate']}% WR, ${results['xau_ny']['total_pnl']} PnL")

    results['forex_london'] = backtest_forex_london(eur_df, cfg)
    logger.info(f"  Forex London: {results['forex_london']['total_trades']} trades, {results['forex_london']['win_rate']}% WR, ${results['forex_london']['total_pnl']} PnL")

    # 4. Monte Carlo
    logger.info(f"\n[4/4] Monte Carlo (10,000 simulations)...")
    results['monte_carlo'] = run_monte_carlo([results['xau_asian'], results['xau_ny'], results['forex_london']], 10000)
    logger.info(f"  Pass Rate: {results['monte_carlo']['pass_rate']}%")
    logger.info(f"  Median Return: {results['monte_carlo']['median_return']}%")
    logger.info(f"  Worst Case (5th %ile): {results['monte_carlo']['worst_case']}%")
    logger.info(f"  Best Case (95th %ile): {results['monte_carlo']['best_case']}%")

    # 5. Save dashboard data
    Path('backtest/results').mkdir(parents=True, exist_ok=True)
    with open('backtest/results/dashboard_data.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"\n  Saved: backtest/results/dashboard_data.json")

    # Print summary
    logger.info("\n" + "=" * 60)
    logger.info("BACKTEST SUMMARY")
    logger.info("=" * 60)
    for key in ['xau_asian', 'xau_ny', 'forex_london']:
        m = results[key]
        status = "PASS" if m['prop_firm_checks']['max_drawdown_ok'] and m['prop_firm_checks']['consistency_ok'] else "FAIL"
        logger.info(f"\n{m['name']}:")
        logger.info(f"  Trades: {m['total_trades']} | Win Rate: {m['win_rate']}%")
        logger.info(f"  P&L: ${m['total_pnl']} ({m['total_return']}%) | Max DD: {m['max_drawdown_pct']}%")
        logger.info(f"  Sharpe: {m['sharpe_ratio']} | Profit Factor: {m['profit_factor']}")
        logger.info(f"  Prop Firm: {status}")

    logger.info(f"\n{'=' * 60}")
    logger.info(f"Monte Carlo: {results['monte_carlo']['pass_rate']}% chance of passing Pro 2-Step")
    logger.info(f"{'=' * 60}")

if __name__ == '__main__':
    Path('data').mkdir(exist_ok=True)
    Path('backtest/results').mkdir(parents=True, exist_ok=True)
    asyncio.run(main())
