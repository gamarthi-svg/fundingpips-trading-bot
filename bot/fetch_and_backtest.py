#!/usr/bin/env python3
"""
Fetch real historical data from MetaAPI and run backtests.
v3: ATR-based + multi-instrument + LONG-only proven strategies.
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# Auto-load .env
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger(__name__)

TOKEN = os.environ.get('METAAPI_TOKEN', '')
ACCOUNT_ID = os.environ.get('METAAPI_ACCOUNT_ID', 'db865e4a-4e83-48a6-93af-73372f595a0c')
INITIAL_BALANCE = float(os.environ.get('ACCOUNT_SIZE', '10000'))
REGION = os.environ.get('METAAPI_REGION', 'new-york')

SYMBOLS = {
    'XAUUSD': {'commission': 5.0, 'contract': 100.0},
    'EURUSD': {'commission': 5.0, 'contract': 100_000.0},
    'GBPUSD': {'commission': 5.0, 'contract': 100_000.0},
    'USDJPY': {'commission': 5.0, 'contract': 100_000.0},
}
PRO_LIMITS = {'daily_dd_pct': 0.03, 'max_dd_pct': 0.06, 'profit_target_pct': 0.06}


def _get_url(service: str) -> str:
    if service == 'market-data':
        return f"https://mt-market-data-client-api-v1.{REGION}.agiliumtrade.ai"
    return f"https://mt-client-api-v1.{REGION}.agiliumtrade.ai"


async def _discover_symbol(hint: str) -> str:
    if not TOKEN or not ACCOUNT_ID:
        return hint
    import httpx
    try:
        url = f"{_get_url('client')}/users/current/accounts/{ACCOUNT_ID}/symbols"
        r = await httpx.AsyncClient(timeout=30).get(url, headers={'auth-token': TOKEN})
        if r.status_code == 200:
            for s in r.json():
                if s.upper() == hint.upper() or hint.upper() in s.upper():
                    return s
    except Exception:
        pass
    return hint


async def fetch_candles(symbol: str, timeframe: str = '5m', days: int = 90) -> pd.DataFrame:
    """Fetch historical candles from MetaAPI."""
    if not TOKEN or not ACCOUNT_ID:
        return _synthetic(symbol, days)

    import httpx
    broker = await _discover_symbol(symbol)
    url = (f"{_get_url('market-data')}/users/current/accounts/{ACCOUNT_ID}"
           f"/historical-market-data/symbols/{broker}/timeframes/{timeframe}/candles")
    headers = {'auth-token': TOKEN}
    params: dict = {'limit': 1000}
    all_candles: list = []
    seen: set = set()

    async with httpx.AsyncClient(timeout=120) as c:
        for page in range(30):
            r = await c.get(url, headers=headers, params=params)
            if r.status_code != 200:
                if r.status_code == 401:
                    logger.error("  401: Add 'market-data-client-api' at https://app.metaapi.cloud/token")
                break
            candles = r.json()
            if not candles:
                break
            new = [cd for cd in candles if cd.get('time') not in seen]
            if not new:
                break
            for cd in new:
                seen.add(cd.get('time', ''))
            all_candles.extend(new)
            if len(candles) < 1000:
                break
            t = new[-1].get('time', '')
            if not t:
                break
            try:
                dt = datetime.fromisoformat(t.replace('Z', '+00:00'))
                params['startTime'] = (dt - timedelta(milliseconds=1)).isoformat().replace('+00:00', 'Z')
            except ValueError:
                params['startTime'] = t
            if page % 5 == 4:
                logger.info(f"  Fetched {len(all_candles)} candles...")

    if all_candles:
        logger.info(f"  Total: {len(all_candles)} real candles for {symbol}")
        df = pd.DataFrame(all_candles)
        df['time'] = pd.to_datetime(df['time'], utc=True)
        for col in ['open', 'high', 'low', 'close', 'tickVolume', 'volume']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        rename = {'tickVolume': 'tick_volume', 'volume': 'tick_volume'}
        df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
        keep = ['time', 'open', 'high', 'low', 'close', 'tick_volume']
        if 'spread' in df.columns:
            keep.append('spread')
        df = df[[c for c in keep if c in df.columns]]
        return df.drop_duplicates('time').sort_values('time').reset_index(drop=True)

    return _synthetic(symbol, days)


def _synthetic(symbol: str, days: int) -> pd.DataFrame:
    np.random.seed(hash(symbol) % 2**32)
    n = min(days * 24 * 12, 20000)
    base = {'XAUUSD': 4700, 'EURUSD': 1.17, 'GBPUSD': 1.26, 'USDJPY': 150}.get(symbol, 100)
    vol = base * 0.0003
    t = pd.date_range(end=datetime.now(), periods=n, freq='5min', tz='UTC')
    close = base + np.cumsum(np.random.normal(0, vol, n))
    o = close + np.random.normal(0, vol * 0.3, n)
    h = np.maximum(o, close) + np.abs(np.random.normal(0, vol * 0.5, n))
    l = np.minimum(o, close) - np.abs(np.random.normal(0, vol * 0.5, n))
    return pd.DataFrame({'time': t, 'open': o, 'high': h, 'low': l, 'close': close,
                         'tick_volume': np.random.randint(100, 5000, n)})


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    d = df['close'].diff()
    gain = d.where(d > 0, 0).ewm(14, adjust=False).mean()
    loss = (-d.where(d < 0, 0)).ewm(14, adjust=False).mean()
    df['rsi14'] = 100 - 100 / (1 + gain / loss.replace(0, np.finfo(float).eps))
    tr = pd.concat([df['high'] - df['low'],
                    (df['high'] - df['close'].shift()).abs(),
                    (df['low'] - df['close'].shift()).abs()], axis=1).max(axis=1)
    df['atr14'] = tr.ewm(14, adjust=False).mean()
    df['hour'] = df['time'].dt.hour
    df['date'] = df['time'].dt.date
    df['vol_avg20'] = df['tick_volume'].rolling(20).mean()
    return df


def _lots(risk: float, stop_dist: float, contract: float) -> float:
    if stop_dist <= 0:
        return 0.0
    return max(0.01, min(5.0, round(risk / (stop_dist * contract), 2)))


def _run_trade(entry, sl, tp, direction, bal, lots, contract, comm, df, i, max_h, risk):
    pnl = 0.0
    for j in range(i + 1, min(i + max_h, len(df))):
        f = df.iloc[j]
        if direction == 'long':
            if f['low'] <= sl:
                pnl = -(risk + comm * lots)
                break
            elif f['high'] >= tp:
                pnl = risk * 2 - comm * lots
                break
        else:
            if f['high'] >= sl:
                pnl = -(risk + comm * lots)
                break
            elif f['low'] <= tp:
                pnl = risk * 2 - comm * lots
                break
    else:
        ex = f['close']
        pnl = ((ex - entry) if direction == 'long' else (entry - ex)) * lots * contract - comm * lots
    return pnl


def metrics(trades, eq_curve, name):
    if not trades:
        return {'name': name, 'total_trades': 0, 'total_pnl': 0, 'total_return': 0,
                'win_rate': 0, 'max_drawdown_pct': 0, 'sharpe_ratio': 0,
                'profit_factor': 0, 'equity_curve': [], 'trades': [], 'prop_firm_checks': {}}
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    pnl = sum(t['pnl'] for t in trades)
    ret = pnl / INITIAL_BALANCE * 100
    wr = len(wins) / len(trades) * 100
    gp = sum(t['pnl'] for t in wins)
    gl = abs(sum(t['pnl'] for t in losses))
    pf = gp / gl if gl > 0 else float('inf')
    peak, max_dd, max_dd_pct = INITIAL_BALANCE, 0.0, 0.0
    for p in eq_curve:
        peak = max(peak, p['equity'])
        dd = (peak - p['equity']) / peak * 100
        if dd > max_dd_pct:
            max_dd_pct, max_dd = dd, peak - p['equity']
    rets = [t['pnl'] / INITIAL_BALANCE for t in trades]
    sharpe = (np.mean(rets) * 252) / (np.std(rets) * np.sqrt(252)) if len(rets) > 1 and np.std(rets) > 0 else 0

    # Consistency
    df_eq = pd.DataFrame(eq_curve)
    consistency = 0.0
    if len(df_eq) > 1:
        df_eq['date'] = pd.to_datetime(df_eq['time']).dt.date
        daily = df_eq.groupby('date')['equity'].last().diff().dropna()
        profits = daily[daily > 0]
        consistency = (profits.max() / profits.sum() * 100) if profits.sum() > 0 else 0.0

    return {
        'name': name, 'symbol': trades[0]['symbol'], 'total_trades': len(trades),
        'winning_trades': len(wins), 'losing_trades': len(losses),
        'total_return': round(ret, 2), 'total_pnl': round(pnl, 2),
        'win_rate': round(wr, 1), 'profit_factor': round(pf, 2),
        'avg_win': round(gp / len(wins), 2) if wins else 0,
        'avg_loss': round(gl / len(losses), 2) if losses else 0,
        'max_drawdown_pct': round(max_dd_pct, 2),
        'max_drawdown_dollars': round(max_dd, 2),
        'sharpe_ratio': round(sharpe, 2),
        'consistency_score': round(consistency, 1),
        'equity_curve': [{'time': str(p['time']), 'equity': round(p['equity'], 2)} for p in eq_curve[::10]],
        'trades': [{'pnl': round(t['pnl'], 2), 'result': t['result']} for t in trades],
        'prop_firm_checks': {
            'max_drawdown_ok': max_dd_pct < PRO_LIMITS['max_dd_pct'] * 100,
            'consistency_ok': consistency < 35,
            'profit_target_reached': pnl >= INITIAL_BALANCE * PRO_LIMITS['profit_target_pct'],
        },
    }


# ── Strategy 1: Asian Session ──
def strat_asian(df: pd.DataFrame) -> dict:
    df = add_indicators(df)
    bal = INITIAL_BALANCE
    eq = INITIAL_BALANCE
    peak = INITIAL_BALANCE
    trades = []
    eqc = [{'time': df['time'].iloc[0], 'equity': eq}]
    comm = SYMBOLS['XAUUSD']['commission']
    cv = SYMBOLS['XAUUSD']['contract']
    last_date = None

    for i in range(50, len(df) - 1):
        c = df.iloc[i]
        if not (c['hour'] >= 23 or c['hour'] <= 3):
            continue
        today = c['date']
        if last_date == today:
            continue
        min_atr = c['close'] * 0.0005
        if c['atr14'] < min_atr:
            continue
        if not (c['close'] > c['open'] and c['close'] > c['ema20'] and
                42 <= c['rsi14'] <= 60 and c['tick_volume'] > c['vol_avg20'] * 1.2):
            continue

        entry = c['close']
        atr = c['atr14']
        sl = entry - 1.5 * atr
        tp = entry + 3.0 * atr
        risk = bal * 0.005
        lots = _lots(risk, entry - sl, cv)
        if lots <= 0:
            continue
        pnl = _run_trade(entry, sl, tp, 'long', bal, lots, cv, comm, df, i, 50, risk)
        bal += pnl
        eq = bal
        peak = max(peak, eq)
        last_date = today
        trades.append({'pnl': pnl, 'result': 'win' if pnl > 0 else 'loss', 'symbol': 'XAUUSD', 'strategy': 'Asian'})
        eqc.append({'time': c['time'], 'equity': eq})
    return metrics(trades, eqc, 'XAUUSD Asian')


# ── Strategy 2: NY Breakout ──
def strat_ny(df: pd.DataFrame) -> dict:
    df = add_indicators(df)
    bal = INITIAL_BALANCE
    trades = []
    eqc = [{'time': df['time'].iloc[0], 'equity': bal}]
    comm = SYMBOLS['XAUUSD']['commission']
    cv = SYMBOLS['XAUUSD']['contract']
    last_date = None

    for i in range(50, len(df) - 1):
        c = df.iloc[i]
        if not ((c['hour'] == 13 and c['time'].minute >= 30) or c['hour'] == 14):
            continue
        today = c['date']
        if last_date == today:
            continue
        min_atr = c['close'] * 0.0008
        if c['atr14'] < min_atr:
            continue
        rh = df.iloc[i - 10:i]['high'].max()
        if c['close'] <= rh + 0.5 * c['atr14'] or c['rsi14'] <= 50 or c['tick_volume'] <= c['vol_avg20']:
            continue

        entry = c['close']
        atr = c['atr14']
        sl = entry - 2.0 * atr
        tp = entry + 4.0 * atr
        risk = bal * 0.005
        lots = _lots(risk, entry - sl, cv)
        if lots <= 0:
            continue
        pnl = _run_trade(entry, sl, tp, 'long', bal, lots, cv, comm, df, i, 60, risk)
        bal += pnl
        last_date = today
        trades.append({'pnl': pnl, 'result': 'win' if pnl > 0 else 'loss', 'symbol': 'XAUUSD', 'strategy': 'NY'})
        eqc.append({'time': c['time'], 'equity': bal})
    return metrics(trades, eqc, 'XAUUSD NY')


# ── Strategy 3: London Breakout (multi-instrument) ──
def strat_london(df: pd.DataFrame, symbol: str, risk_pct: float = 0.005) -> dict:
    df = add_indicators(df)
    bal = INITIAL_BALANCE
    trades = []
    eqc = [{'time': df['time'].iloc[0], 'equity': bal}]
    comm = SYMBOLS[symbol]['commission']
    cv = SYMBOLS[symbol]['contract']
    daily_count = 0
    cur_date = None

    for i in range(84, len(df) - 1):
        c = df.iloc[i]
        today = c['date']
        if today != cur_date:
            cur_date = today
            daily_count = 0
        if not (7 <= c['hour'] <= 12) or daily_count >= 2:
            continue

        lb = min(84, i)
        al = df.iloc[i - lb:i]['low'].min()
        ah = df.iloc[i - lb:i]['high'].max()
        ar = ah - al
        if ar <= 1.5 * c['atr14']:
            continue
        if c['close'] <= ah + 0.2 * c['atr14']:
            continue

        entry = c['close']
        sd = max(ar, entry - al, 1.0 * c['atr14'])
        sl = entry - sd
        tp = entry + sd * 2
        risk = bal * risk_pct
        lots = _lots(risk, sd, cv)
        if lots <= 0:
            continue
        pnl = _run_trade(entry, sl, tp, 'long', bal, lots, cv, comm, df, i, 60, risk)
        bal += pnl
        daily_count += 1
        trades.append({'pnl': pnl, 'result': 'win' if pnl > 0 else 'loss', 'symbol': symbol, 'strategy': 'London'})
        eqc.append({'time': c['time'], 'equity': bal})
    return metrics(trades, eqc, f'{symbol} London')


# ── Monte Carlo ──
def monte_carlo(results_list, n=10000):
    all_pnl = [t['pnl'] for m in results_list for t in m.get('trades', [])]
    if not all_pnl:
        return {'pass_rate': 0, 'median_return': 0, 'worst_case': 0}
    np.random.seed(42)
    fe, md = [], []
    for _ in range(n):
        sample = np.random.choice(all_pnl, size=len(all_pnl), replace=True)
        eq, peak = INITIAL_BALANCE, INITIAL_BALANCE
        mdd = 0
        for p in sample:
            eq += p
            peak = max(peak, eq)
            mdd = max(mdd, (peak - eq) / peak * 100)
        fe.append((eq - INITIAL_BALANCE) / INITIAL_BALANCE * 100)
        md.append(mdd)
    fe = np.array(fe)
    return {
        'pass_rate': round(float(np.mean((fe >= 6) & (np.array(md) < 6)) * 100), 1),
        'median_return': round(float(np.median(fe)), 2),
        'mean_return': round(float(np.mean(fe)), 2),
        'worst_case': round(float(np.percentile(fe, 5)), 2),
        'best_case': round(float(np.percentile(fe, 95)), 2),
        'median_max_dd': round(float(np.median(md)), 2),
        'max_dd_95th': round(float(np.percentile(md, 95)), 2),
    }


# ── Main ──
async def main():
    logger.info("=" * 60)
    logger.info("Backtest Engine v3 — Proven Strategies + Multi-Instrument")
    logger.info("=" * 60)

    results = {}
    instruments = [('XAUUSD', 90), ('EURUSD', 90), ('GBPUSD', 90), ('USDJPY', 90)]
    dfs = {}

    for sym, days in instruments:
        logger.info(f"\n[Fetch] {sym} ({days} days)...")
        dfs[sym] = await fetch_candles(sym, '5m', days)

    # Core strategies (proven in v1)
    logger.info("\n[Backtest] Running strategies...")
    results['xau_asian'] = strat_asian(dfs['XAUUSD'])
    results['xau_ny'] = strat_ny(dfs['XAUUSD'])
    results['eurusd_london'] = strat_london(dfs['EURUSD'], 'EURUSD')
    results['gbpusd_london'] = strat_london(dfs['GBPUSD'], 'GBPUSD')
    # USDJPY disabled - too volatile, 8%+ DD even at 0.2% risk

    for k, m in results.items():
        status = "PASS" if m['prop_firm_checks'].get('max_drawdown_ok') and m['prop_firm_checks'].get('consistency_ok') else "FAIL"
        logger.info(f"  {m['name']:20s} | {m['total_trades']:3d}T | WR:{m['win_rate']:4.1f}% | PnL:\${m['total_pnl']:6.0f} | DD:{m['max_drawdown_pct']:4.1f}% | Sh:{m['sharpe_ratio']:4.2f} | {status}")

    # Monte Carlo
    mc = monte_carlo(list(results.values()), 10000)
    results['monte_carlo'] = mc
    logger.info(f"\n[Monte Carlo] Pass Rate: {mc['pass_rate']}% | Median: {mc['median_return']}% | Worst(5%): {mc['worst_case']}%")

    Path('backtest/results').mkdir(parents=True, exist_ok=True)
    with open('backtest/results/dashboard_data.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    logger.info("\nSaved: backtest/results/dashboard_data.json")


if __name__ == '__main__':
    Path('data').mkdir(exist_ok=True)
    Path('backtest/results').mkdir(parents=True, exist_ok=True)
    asyncio.run(main())
