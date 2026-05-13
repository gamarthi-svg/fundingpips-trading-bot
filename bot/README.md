# Trading Bot

> Core Python trading engine for FundingPips prop firm evaluation.

## Features

- **4 Strategies**
  - XAUUSD Asian Breakout
  - XAUUSD New York Momentum
  - NQ Futures Opening Range Breakout
  - Forex London Session
- **3-Tier Risk Management** -- daily loss limit, trailing max drawdown, hard stop
- **MetaAPI Cloud Integration** -- paper & live trading modes
- **Backtesting** -- walk-forward optimization + Monte Carlo simulation

## Directory Structure

```
.
├── api/              # FastAPI routes, WebSocket, server
├── backtest/         # Backtest engine, walk-forward, Monte Carlo, reports
├── config/           # Settings & prop firm phase configs
├── execution/        # Order management, MetaAPI bridge, providers
├── journal/          # Trade logging & models
├── risk/             # Drawdown, position sizing, risk manager
├── strategies/       # Strategy implementations + base class + registry
├── utils/            # Notifications & time utilities
├── main.py           # Server entry point (FastAPI)
├── fetch_and_backtest.py
├── requirements.txt
├── Dockerfile
├── config.json
└── .env.example
```

## Configuration

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Required variables include `METAAPI_TOKEN`, `ACCOUNT_ID`, and `ENVIRONMENT`.

## Running

```bash
# Server mode (API + WebSocket)
python main.py

# Backtest mode
python fetch_and_backtest.py
```
