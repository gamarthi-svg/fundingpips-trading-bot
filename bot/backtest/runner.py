#!/usr/bin/env python3
"""
Backtest CLI runner.

Usage:
    # Fetch data first
    python -m backtest.runner fetch --symbol XAUUSD --timeframe M5 --months 6

    # Run backtest
    python -m backtest.runner backtest --symbol XAUUSD --strategy XauUsdAsian --data data/XAUUSD_M5.csv

    # Optimize parameters
    python -m backtest.runner optimize --symbol XAUUSD --strategy XauUsdAsian --param-sl "8:15" --param-rr "1.5:3.0"

    # Monte Carlo stress test
    python -m backtest.runner stress --results results/backtest_XAUUSD.json --simulations 10000

    # Full pipeline: fetch + backtest + optimize + report
    python -m backtest.runner full --symbol XAUUSD --strategy XauUsdAsian --timeframe M5 --months 6

    # Generate dashboard data
    python -m backtest.runner dashboard --results results/backtest_XAUUSD.json --output dashboard_data.json
"""

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging(level: int = logging.INFO) -> None:
    """Configure root logger for CLI output."""
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )


# ---------------------------------------------------------------------------
# Strategy registry (lazy imports to avoid hard deps at module load time)
# ---------------------------------------------------------------------------

def get_strategy(name: str, **kwargs: Any) -> Any:
    """Get strategy instance by name with optional parameter overrides."""
    strategies = {
        'XauUsdAsian': None,
        'XauUsdNY': None,
        'NqOrb': None,
        'ForexLondon': None,
    }

    if name in ('XauUsdAsian', 'XauUsdNY'):
        from strategies.xauusd import XauUsdStrategy
        strategies['XauUsdAsian'] = XauUsdStrategy
        strategies['XauUsdNY'] = XauUsdStrategy
    elif name == 'NqOrb':
        from strategies.nq_futures import NqFuturesStrategy
        strategies['NqOrb'] = NqFuturesStrategy
    elif name == 'ForexLondon':
        from strategies.forex import ForexStrategy
        strategies['ForexLondon'] = ForexStrategy

    strategy_class = strategies.get(name)
    if not strategy_class:
        raise ValueError(
            f"Unknown strategy: {name}. Available: {list(strategies.keys())}"
        )
    return strategy_class(**kwargs)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _parse_param_range(param_str: str) -> tuple[float, float]:
    """Parse a 'start:end' string into (start, end) floats."""
    try:
        parts = param_str.split(':')
        if len(parts) != 2:
            raise ValueError("Format must be 'start:end'")
        return float(parts[0]), float(parts[1])
    except (ValueError, IndexError) as exc:
        raise ValueError(f"Invalid parameter range: {param_str}") from exc


def _ensure_dir(path: str) -> Path:
    """Ensure directory exists, create if needed."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _load_results(results_path: str) -> Dict[str, Any]:
    """Load JSON backtest results from disk."""
    path = Path(results_path)
    if not path.exists():
        raise FileNotFoundError(f"Results file not found: {results_path}")
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save_results(data: Dict[str, Any], output_path: str) -> Path:
    """Save results dict as JSON to disk."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, default=str)
    logger.info("Results saved to %s", path)
    return path


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------

async def cmd_fetch(args: argparse.Namespace) -> None:
    """Fetch historical data from MetaAPI or generate sample data."""
    from backtest.data_loader import DataLoader

    symbol: str = args.symbol
    timeframe: str = args.timeframe
    months: int = args.months
    source: str = args.source
    output_dir: str = args.output

    output_path = _ensure_dir(output_dir)

    if source == 'sample':
        logger.info("Generating sample data for %s %s (%d months)", symbol, timeframe, months)
        df = DataLoader.generate_sample_data(symbol=symbol, months=months, timeframe=timeframe)
    elif source == 'csv':
        logger.info("Loading from CSV for %s", symbol)
        df = DataLoader.from_csv(f"{output_dir}/{symbol}_{timeframe}.csv")
    elif source == 'metaapi':
        logger.info("Fetching %s %s from MetaAPI (%d months)", symbol, timeframe, months)
        df = await DataLoader.from_metaapi(symbol=symbol, timeframe=timeframe, months=months)
    else:
        raise ValueError(f"Unknown data source: {source}")

    out_file = output_path / f"{symbol}_{timeframe}.csv"
    df.to_csv(out_file, index=False)
    logger.info("Data saved: %s (%d rows)", out_file, len(df))


async def cmd_backtest(args: argparse.Namespace) -> None:
    """Run a single backtest."""
    from backtest.engine import BacktestEngine, BacktestConfig
    from backtest.performance import PerformanceAnalyzer
    from backtest.report import BacktestReport

    symbol: str = args.symbol
    strategy_name: str = args.strategy
    data_path: str = args.data
    balance: float = args.balance
    risk: float = args.risk
    output_dir: str = args.output

    if not Path(data_path).exists():
        raise FileNotFoundError(f"Data file not found: {data_path}")

    logger.info("=" * 60)
    logger.info("BACKTEST | %s | Strategy: %s | Balance: %.0f | Risk: %.2f%%",
                symbol, strategy_name, balance, risk * 100)
    logger.info("=" * 60)

    # Load data
    df = DataLoader.from_csv(data_path)
    logger.info("Loaded %d rows from %s", len(df), data_path)

    # Build strategy and config
    strategy = get_strategy(strategy_name, symbol=symbol)
    config = BacktestConfig(
        initial_balance=balance,
        risk_per_trade=risk,
        symbol=symbol,
    )

    # Run engine
    engine = BacktestEngine(config)
    result = engine.run(df, strategy)

    # Analyze performance
    analyzer = PerformanceAnalyzer(result.trades, result.equity_curve)
    metrics = analyzer.compute_all()

    # Report
    report = BacktestReport(result, metrics)
    report.print_summary()

    # Save
    out_dir = _ensure_dir(output_dir)
    out_path = out_dir / f"backtest_{symbol}_{strategy_name}.json"
    _save_results(report.to_dict(), str(out_path))

    logger.info("Backtest complete. Results: %s", out_path)


async def cmd_optimize(args: argparse.Namespace) -> None:
    """Run walk-forward optimization."""
    from backtest.engine import BacktestEngine, BacktestConfig
    from backtest.walk_forward import WalkForwardOptimizer

    symbol: str = args.symbol
    strategy_name: str = args.strategy
    data_path: str = args.data
    sl_min, sl_max = _parse_param_range(args.param_sl)
    rr_min, rr_max = _parse_param_range(args.param_rr)
    n_windows: int = args.windows

    if not Path(data_path).exists():
        raise FileNotFoundError(f"Data file not found: {data_path}")

    logger.info("=" * 60)
    logger.info("WALK-FORWARD OPTIMIZATION | %s | Strategy: %s", symbol, strategy_name)
    logger.info("  SL range: %.1f - %.1f | RR range: %.1f - %.1f | Windows: %d",
                sl_min, sl_max, rr_min, rr_max, n_windows)
    logger.info("=" * 60)

    df = DataLoader.from_csv(data_path)
    logger.info("Loaded %d rows", len(df))

    # Parameter grid
    param_grid: Dict[str, Any] = {
        'stop_loss_pips': [sl_min, (sl_min + sl_max) / 2, sl_max],
        'risk_reward': [rr_min, (rr_min + rr_max) / 2, rr_max],
    }

    config = BacktestConfig(
        initial_balance=100_000,
        risk_per_trade=0.005,
        symbol=symbol,
    )

    strategy = get_strategy(strategy_name, symbol=symbol)
    engine = BacktestEngine(config)

    optimizer = WalkForwardOptimizer(
        engine=engine,
        strategy=strategy,
        param_grid=param_grid,
        n_windows=n_windows,
    )

    wf_result = optimizer.optimize(df)
    wf_result.print_summary()

    # Save best params
    out_path = _ensure_dir("results") / f"optimize_{symbol}_{strategy_name}.json"
    _save_results(wf_result.to_dict(), str(out_path))
    logger.info("Optimization complete. Best params saved to %s", out_path)


async def cmd_stress(args: argparse.Namespace) -> None:
    """Run Monte Carlo stress test on existing results."""
    from backtest.monte_carlo import MonteCarloSimulator

    results_path: str = args.results
    n_simulations: int = args.simulations
    max_dd_threshold: float = args.max_dd
    target_return: float = args.target

    logger.info("=" * 60)
    logger.info("MONTE CARLO STRESS TEST | Simulations: %d", n_simulations)
    logger.info("  Max DD threshold: %.1f%% | Target return: %.1f%%",
                max_dd_threshold * 100, target_return * 100)
    logger.info("=" * 60)

    results = _load_results(results_path)
    trades = results.get('trades', [])

    if not trades:
        logger.error("No trades found in results file")
        return

    mc = MonteCarloSimulator(n_simulations=n_simulations, random_seed=42)
    mc_result = mc.simulate(trades)

    logger.info("--- Monte Carlo Results ---")
    logger.info("  Simulations run    : %d", mc_result.n_simulations)
    logger.info("  Avg final return   : %.2f%%", mc_result.avg_final_return * 100)
    logger.info("  Worst-case return  : %.2f%%", mc_result.worst_case_return * 100)
    logger.info("  Avg max drawdown   : %.2f%%", mc_result.avg_max_drawdown * 100)
    logger.info("  P(drawdown > %.1f%%): %.2f%%",
                max_dd_threshold * 100, mc_result.prob_exceed_max_dd(max_dd_threshold) * 100)
    logger.info("  P(return   > %.1f%%): %.2f%%",
                target_return * 100, mc_result.prob_exceed_target(target_return) * 100)
    logger.info("  95%% CI return      : [%.2f%%, %.2f%%]",
                mc_result.ci_95_return[0] * 100, mc_result.ci_95_return[1] * 100)
    logger.info("  Sharpe ratio dist   : %.2f (± %.2f)",
                mc_result.avg_sharpe, mc_result.sharpe_std)

    # Save
    out_path = _ensure_dir("results") / "monte_carlo_stress.json"
    _save_results(mc_result.to_dict(), str(out_path))
    logger.info("Stress test complete. Results: %s", out_path)


async def cmd_full(args: argparse.Namespace) -> None:
    """Full pipeline: fetch -> backtest -> optimize -> MC -> report."""
    symbol: str = args.symbol
    strategy_name: str = args.strategy
    timeframe: str = args.timeframe
    months: int = args.months
    balance: float = args.balance

    logger.info("=" * 70)
    logger.info("FULL PIPELINE | %s | %s | %s | %d months | Balance %.0f",
                symbol, strategy_name, timeframe, months, balance)
    logger.info("=" * 70)

    # Step 1: Fetch data
    logger.info("\n[Step 1/5] Fetching data...")
    fetch_ns = argparse.Namespace(
        symbol=symbol, timeframe=timeframe, months=months,
        source='sample', output='data/'
    )
    await cmd_fetch(fetch_ns)
    data_file = f"data/{symbol}_{timeframe}.csv"

    # Step 2: Backtest
    logger.info("\n[Step 2/5] Running backtest...")
    backtest_ns = argparse.Namespace(
        symbol=symbol, strategy=strategy_name, data=data_file,
        balance=balance, risk=0.005, output='results/'
    )
    await cmd_backtest(backtest_ns)

    # Step 3: Optimize
    logger.info("\n[Step 3/5] Running walk-forward optimization...")
    optimize_ns = argparse.Namespace(
        symbol=symbol, strategy=strategy_name, data=data_file,
        param_sl='8:15', param_rr='1.5:3.0', windows=5,
    )
    await cmd_optimize(optimize_ns)

    # Step 4: Monte Carlo stress test
    logger.info("\n[Step 4/5] Monte Carlo stress test...")
    results_file = f"results/backtest_{symbol}_{strategy_name}.json"
    stress_ns = argparse.Namespace(
        results=results_file, simulations=10_000, max_dd=0.10, target=0.08,
    )
    await cmd_stress(stress_ns)

    # Step 5: Dashboard data
    logger.info("\n[Step 5/5] Generating dashboard data...")
    dashboard_ns = argparse.Namespace(
        results=results_file, output=f"results/dashboard_{symbol}.json",
    )
    cmd_dashboard(dashboard_ns)

    logger.info("\n" + "=" * 70)
    logger.info("FULL PIPELINE COMPLETE")
    logger.info("  Data    : %s", data_file)
    logger.info("  Results : %s", results_file)
    logger.info("  Dashboard: results/dashboard_%s.json", symbol)
    logger.info("=" * 70)


def cmd_dashboard(args: argparse.Namespace) -> None:
    """Generate dashboard-compatible JSON from backtest results."""
    from backtest.report import generate_dashboard_data

    results_path: str = args.results
    output_path: str = args.output

    logger.info("Generating dashboard data from %s", results_path)

    results = _load_results(results_path)
    dashboard_data = generate_dashboard_data(results)

    _save_results(dashboard_data, output_path)
    logger.info("Dashboard data saved to %s", output_path)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description='Prop Firm Trading Bot Backtester',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fetch sample data
  python -m backtest.runner fetch --symbol XAUUSD --timeframe M5 --months 6

  # Run single backtest
  python -m backtest.runner backtest --symbol XAUUSD --strategy XauUsdAsian --data data/XAUUSD_M5.csv

  # Walk-forward optimize
  python -m backtest.runner optimize --symbol XAUUSD --strategy XauUsdAsian --data data/XAUUSD_M5.csv

  # Monte Carlo stress test
  python -m backtest.runner stress --results results/backtest_XAUUSD.json

  # Full pipeline
  python -m backtest.runner full --symbol XAUUSD --strategy XauUsdAsian --timeframe M5 --months 6

  # Dashboard JSON
  python -m backtest.runner dashboard --results results/backtest_XAUUSD.json
        """,
    )
    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # fetch
    fetch_parser = subparsers.add_parser('fetch', help='Fetch historical data')
    fetch_parser.add_argument('--symbol', required=True, help='Trading symbol (e.g. XAUUSD)')
    fetch_parser.add_argument('--timeframe', default='M5', help='Candle timeframe')
    fetch_parser.add_argument('--months', type=int, default=6, help='Months of history')
    fetch_parser.add_argument(
        '--source', default='metaapi', choices=['metaapi', 'csv', 'sample'],
        help='Data source',
    )
    fetch_parser.add_argument('--output', default='data/', help='Output directory')

    # backtest
    backtest_parser = subparsers.add_parser('backtest', help='Run backtest')
    backtest_parser.add_argument('--symbol', required=True, help='Trading symbol')
    backtest_parser.add_argument('--strategy', required=True,
                                 choices=['XauUsdAsian', 'XauUsdNY', 'NqOrb', 'ForexLondon'],
                                 help='Strategy name')
    backtest_parser.add_argument('--data', required=True, help='Path to OHLCV CSV')
    backtest_parser.add_argument('--balance', type=float, default=100_000,
                                 help='Initial account balance')
    backtest_parser.add_argument('--risk', type=float, default=0.005,
                                 help='Risk per trade (fraction)')
    backtest_parser.add_argument('--output', default='results/', help='Output directory')

    # optimize
    optimize_parser = subparsers.add_parser('optimize', help='Walk-forward optimization')
    optimize_parser.add_argument('--symbol', required=True)
    optimize_parser.add_argument('--strategy', required=True,
                                 choices=['XauUsdAsian', 'XauUsdNY', 'NqOrb', 'ForexLondon'])
    optimize_parser.add_argument('--data', required=True, help='Path to OHLCV CSV')
    optimize_parser.add_argument('--param-sl', default='8:15',
                                 help='Stop-loss range as "min:max"')
    optimize_parser.add_argument('--param-rr', default='1.5:3.0',
                                 help='Risk:reward range as "min:max"')
    optimize_parser.add_argument('--windows', type=int, default=5,
                                 help='Number of walk-forward windows')

    # stress
    stress_parser = subparsers.add_parser('stress', help='Monte Carlo stress test')
    stress_parser.add_argument('--results', required=True,
                               help='Path to backtest results JSON')
    stress_parser.add_argument('--simulations', type=int, default=10_000,
                               help='Number of MC simulations')
    stress_parser.add_argument('--max-dd', type=float, default=0.10,
                               help='Max drawdown threshold for probability calc')
    stress_parser.add_argument('--target', type=float, default=0.08,
                               help='Target return for probability calc')

    # full
    full_parser = subparsers.add_parser('full', help='Full pipeline')
    full_parser.add_argument('--symbol', required=True)
    full_parser.add_argument('--strategy', required=True,
                             choices=['XauUsdAsian', 'XauUsdNY', 'NqOrb', 'ForexLondon'])
    full_parser.add_argument('--timeframe', default='M5')
    full_parser.add_argument('--months', type=int, default=6)
    full_parser.add_argument('--balance', type=float, default=100_000)

    # dashboard
    dash_parser = subparsers.add_parser('dashboard', help='Generate dashboard data')
    dash_parser.add_argument('--results', required=True,
                             help='Path to backtest results JSON')
    dash_parser.add_argument('--output', default='dashboard_data.json',
                             help='Output dashboard JSON path')

    args = parser.parse_args()

    setup_logging()

    if args.command == 'fetch':
        asyncio.run(cmd_fetch(args))
    elif args.command == 'backtest':
        asyncio.run(cmd_backtest(args))
    elif args.command == 'optimize':
        asyncio.run(cmd_optimize(args))
    elif args.command == 'stress':
        asyncio.run(cmd_stress(args))
    elif args.command == 'full':
        asyncio.run(cmd_full(args))
    elif args.command == 'dashboard':
        cmd_dashboard(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
