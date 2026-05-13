# Monitoring Dashboard

> React-based monitoring UI for the FundingPips trading bot.

## Features

- Real-time P&L display
- Strategy on/off controls
- Backtest job queue
- Account metrics & status

## Setup

```bash
npm install
npm run dev
```

## Build

```bash
npm run build
```

## Backend Connection

The dashboard connects to the FastAPI backend at `http://localhost:8000` via REST API and WebSocket.
