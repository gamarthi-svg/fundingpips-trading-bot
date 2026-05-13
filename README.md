# FundingPips Prop Firm Trading Bot

> Automated trading bot for passing FundingPips prop firm evaluation, with a React monitoring dashboard.

## Project Structure

```
.
├── bot/          # Python trading bot (FastAPI backend + strategies)
├── dashboard/    # React monitoring dashboard (TypeScript + Tailwind)
├── .gitignore
└── README.md
```

## Quick Start

### Bot

```bash
pip install -r bot/requirements.txt
cp bot/.env.example bot/.env   # configure your keys
python bot/main.py
```

### Dashboard

```bash
cd dashboard
npm install
npm run dev
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Bot | Python 3.11+, FastAPI, MetaAPI Cloud |
| Dashboard | React 19, TypeScript, Tailwind CSS, shadcn/ui |

## Important Note on Backtest Data

**Real market data is required for meaningful backtest results.**

The backtesting engine fetches historical data via MetaAPI Cloud, which requires the `market-data-client-api` permission on your access token. Without this permission, the system falls back to synthetic data that produces **meaningless results** -- do not rely on them for strategy validation.

## License

MIT
