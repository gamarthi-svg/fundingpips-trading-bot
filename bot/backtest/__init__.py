"""
Prop Firm Trading Bot - Backtesting Framework

Modules:
    data_loader  -- Historical OHLCV data loading from MetaAPI, CSV, yfinance, or synthetic
    engine       -- Event-driven backtest engine with realistic execution simulation

Example:
    from backtest.data_loader import DataLoader, generate_synthetic_data
    from backtest.engine import BacktestEngine, BacktestConfig, MovingAverageCrossoverStrategy

    # Load data
    loader = DataLoader(source="csv", data_dir="./data")
    df = asyncio.run(loader.fetch_candles("XAUUSD", "H1", start, end))

    # Run backtest
    config = BacktestConfig(initial_balance=100_000, risk_per_trade=0.005)
    engine = BacktestEngine(config)
    result = engine.run(strategy, df, symbol="XAUUSD", timeframe="H1")
    print(result.metrics)
"""

__version__ = "1.0.0"
