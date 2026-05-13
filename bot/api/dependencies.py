"""
Dependency injection layer for the trading bot API.

Provides FastAPI Depends() callables for:
    - TradingProvider (broker / execution backend)
    - TradeLogger (SQLite journal)
    - BotState (shared mutable state)
    - BacktestRunner (async backtest job queue)

All singletons are created lazily and cached at module level so they survive
across multiple requests in the same process.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import uuid
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Configuration helpers
# --------------------------------------------------------------------------- #


def _load_config() -> Dict[str, Any]:
    """Build configuration dict from environment and defaults."""
    return {
        "provider": os.environ.get("PROVIDER_TYPE", "mt5").lower(),
        "account": os.environ.get("MT5_ACCOUNT", ""),
        "password": os.environ.get("MT5_PASSWORD", ""),
        "server": os.environ.get("MT5_SERVER", ""),
        "metaapi_token": os.environ.get("METAAPI_TOKEN", ""),
        "metaapi_account_id": os.environ.get("METAAPI_ACCOUNT_ID", ""),
        "db_path": os.environ.get("TRADE_DB_PATH", "trades.db"),
        "phase": os.environ.get("BOT_PHASE", "evaluation"),
    }


# --------------------------------------------------------------------------- #
# Singleton instances (module-level cache)
# --------------------------------------------------------------------------- #

_config: Optional[Dict[str, Any]] = None
_provider: Optional[Any] = None
_db_logger: Optional[Any] = None
_bot_state: Optional["BotState"] = None
_backtest_queue: Optional["BacktestJobQueue"] = None


# --------------------------------------------------------------------------- #
# BotState — shared mutable state for pause / resume / phase
# --------------------------------------------------------------------------- #


@dataclass
class BotState:
    """Thread-safe mutable state for the trading bot."""

    is_trading: bool = True
    is_paused: bool = False
    emergency_triggered: bool = False
    phase: str = "evaluation"
    current_zone: str = "green"
    daily_pnl: float = 0.0
    max_drawdown: float = 0.0
    consistency_score: float = 0.0
    provider_name: str = "unknown"
    connected_at: Optional[datetime] = None
    last_error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_trading": self.is_trading and not self.is_paused,
            "is_paused": self.is_paused,
            "emergency_triggered": self.emergency_triggered,
            "phase": self.phase,
            "zone": self.current_zone,
            "daily_pnl": self.daily_pnl,
            "max_drawdown": self.max_drawdown,
            "consistency_score": self.consistency_score,
            "provider_name": self.provider_name,
            "connected_at": self.connected_at.isoformat() if self.connected_at else None,
            "last_error": self.last_error,
        }


# --------------------------------------------------------------------------- #
# BacktestJobQueue — async job runner for /api/backtest/run
# --------------------------------------------------------------------------- #


@dataclass
class BacktestJob:
    """Represents a single backtest job."""

    job_id: str
    symbol: str
    strategy: str
    timeframe: str
    months: int
    balance: float
    risk: float
    status: str = "pending"  # pending, running, completed, failed
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    result_path: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "symbol": self.symbol,
            "strategy": self.strategy,
            "timeframe": self.timeframe,
            "months": self.months,
            "balance": self.balance,
            "risk": self.risk,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "result_path": self.result_path,
            "error": self.error,
        }


class BacktestJobQueue:
    """Simple in-memory job queue for backtest execution."""

    def __init__(self, max_concurrent: int = 1) -> None:
        self._jobs: Dict[str, BacktestJob] = {}
        self._queue: deque = deque()
        self._max_concurrent = max_concurrent
        self._running = 0

    def submit(self, job: BacktestJob) -> BacktestJob:
        """Add a job to the queue."""
        self._jobs[job.job_id] = job
        self._queue.append(job.job_id)
        logger.info("Backtest job %s submitted (%s %s)", job.job_id, job.symbol, job.strategy)
        return job

    def get(self, job_id: str) -> Optional[BacktestJob]:
        """Retrieve a job by ID."""
        return self._jobs.get(job_id)

    def list_jobs(self, limit: int = 20) -> List[BacktestJob]:
        """Return recent jobs sorted by creation time descending."""
        jobs = sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)
        return jobs[:limit]

    async def process_queue(self) -> None:
        """Background task that processes queued backtest jobs."""
        from backtest.runner import get_strategy
        from backtest.engine import BacktestEngine, BacktestConfig
        from backtest.performance import PerformanceAnalyzer

        while True:
            if self._queue and self._running < self._max_concurrent:
                job_id = self._queue.popleft()
                job = self._jobs.get(job_id)
                if job and job.status == "pending":
                    self._running += 1
                    asyncio.create_task(self._run_job(job))
            await asyncio.sleep(1)

    async def _run_job(self, job: BacktestJob) -> None:
        """Execute a single backtest job."""
        from backtest.runner import get_strategy
        from backtest.engine import BacktestEngine, BacktestConfig
        from backtest.performance import PerformanceAnalyzer

        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        logger.info("Starting backtest job %s", job.job_id)

        try:
            # Generate/fetch data
            data_file = f"data/{job.symbol}_{job.timeframe}.csv"
            data_path = Path(data_file)

            if not data_path.exists():
                # Try to generate sample data
                try:
                    from backtest.data_loader import DataLoader
                    df = DataLoader.generate_sample_data(
                        symbol=job.symbol, months=job.months, timeframe=job.timeframe
                    )
                    data_path.parent.mkdir(parents=True, exist_ok=True)
                    df.to_csv(data_path, index=False)
                    logger.info("Generated sample data for job %s", job.job_id)
                except Exception as e:
                    raise RuntimeError(f"Failed to generate data: {e}") from e

            # Load data
            import pandas as pd
            df = pd.read_csv(data_path)

            # Build strategy and config
            strategy = get_strategy(job.strategy, symbol=job.symbol)
            config = BacktestConfig(
                initial_balance=job.balance,
                risk_per_trade=job.risk,
                symbol=job.symbol,
            )

            # Run backtest
            engine = BacktestEngine(config)
            result = engine.run(df, strategy)

            # Analyze performance
            analyzer = PerformanceAnalyzer(
                result.trades, result.equity_curve, job.balance, config
            )
            metrics = analyzer.calculate_all()

            # Save results
            results_dir = Path("backtest/results")
            results_dir.mkdir(parents=True, exist_ok=True)
            result_path = results_dir / f"backtest_{job.symbol}_{job.strategy}_{job.job_id}.json"

            report_data = {
                "job_id": job.job_id,
                "symbol": job.symbol,
                "strategy": job.strategy,
                "timeframe": job.timeframe,
                "months": job.months,
                "balance": job.balance,
                "risk": job.risk,
                "metrics": metrics.to_dict(),
                "trades": [
                    {
                        "entry_price": getattr(t, "entry_price", None),
                        "exit_price": getattr(t, "exit_price", None),
                        "pnl": getattr(t, "pnl", None),
                        "volume": getattr(t, "volume", None),
                        "direction": getattr(t, "direction", None),
                        "open_time": getattr(t, "open_time", None),
                        "close_time": getattr(t, "close_time", None),
                    }
                    for t in result.trades
                ],
                "equity_curve": result.equity_curve.to_dict("records")
                if hasattr(result.equity_curve, "to_dict")
                else [],
                "run_at": datetime.now(timezone.utc).isoformat(),
            }

            with open(result_path, "w", encoding="utf-8") as f:
                json.dump(report_data, f, indent=2, default=str)

            job.status = "completed"
            job.result_path = str(result_path)
            logger.info("Backtest job %s completed: %s", job.job_id, result_path)

        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
            logger.exception("Backtest job %s failed", job.job_id)

        finally:
            job.completed_at = datetime.now(timezone.utc)
            self._running -= 1


# --------------------------------------------------------------------------- #
# Provider / Logger getters (cached)
# --------------------------------------------------------------------------- #


def get_config() -> Dict[str, Any]:
    """Return the trading bot configuration dict."""
    global _config
    if _config is None:
        _config = _load_config()
    return _config


def get_provider() -> Any:
    """Return (or create) the TradingProvider singleton.

    The provider type is read from the ``PROVIDER_TYPE`` env var
    (``mt5`` or ``metaapi``).  The returned object is **not**
    automatically connected — call ``await provider.connect()``
    before first use.
    """
    global _provider, _bot_state
    if _provider is None:
        cfg = get_config()
        from execution.factory import TradingProviderFactory

        _provider = TradingProviderFactory.create_provider(cfg)
        # Update BotState with provider name
        bs = get_bot_state()
        bs.provider_name = _provider.get_provider_name() if hasattr(_provider, "get_provider_name") else cfg.get("provider", "unknown")
        logger.info("TradingProvider created: %s", bs.provider_name)
    return _provider


def get_db() -> Any:
    """Return (or create) the TradeLogger singleton."""
    global _db_logger
    if _db_logger is None:
        cfg = get_config()
        from journal.logger import TradeLogger

        _db_logger = TradeLogger(db_path=cfg.get("db_path", "trades.db"))
        logger.info("TradeLogger created (db=%s)", cfg.get("db_path", "trades.db"))
    return _db_logger


def get_bot_state() -> BotState:
    """Return the shared BotState singleton."""
    global _bot_state
    if _bot_state is None:
        cfg = get_config()
        _bot_state = BotState(
            phase=cfg.get("phase", "evaluation"),
            is_trading=True,
            connected_at=datetime.now(timezone.utc),
        )
    return _bot_state


def get_backtest_queue() -> BacktestJobQueue:
    """Return the BacktestJobQueue singleton."""
    global _backtest_queue
    if _backtest_queue is None:
        _backtest_queue = BacktestJobQueue(max_concurrent=1)
    return _backtest_queue


# --------------------------------------------------------------------------- #
# FastAPI Depends() wrappers
# --------------------------------------------------------------------------- #

# These are the callables you pass to FastAPI's Depends()


def trading_provider():
    """FastAPI dependency that yields the TradingProvider."""
    return get_provider()


def trade_logger():
    """FastAPI dependency that yields the TradeLogger."""
    return get_db()


def bot_state():
    """FastAPI dependency that yields the BotState."""
    return get_bot_state()


def backtest_queue():
    """FastAPI dependency that yields the BacktestJobQueue."""
    return get_backtest_queue()


__all__ = [
    "get_config",
    "get_provider",
    "get_db",
    "get_bot_state",
    "get_backtest_queue",
    "trading_provider",
    "trade_logger",
    "bot_state",
    "backtest_queue",
    "BotState",
    "BacktestJob",
    "BacktestJobQueue",
]
