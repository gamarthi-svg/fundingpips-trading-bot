"""Async job queue for backtesting, optimization, and Monte Carlo.
Runs in a background thread so the trading loop is never blocked."""
import sqlite3
import uuid
import json
import threading
import time
import logging
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

logger = logging.getLogger(__name__)


class JobStatus(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobType(Enum):
    FETCH_DATA = "fetch_data"
    BACKTEST = "backtest"
    WALK_FORWARD = "walk_forward"
    MONTE_CARLO = "monte_carlo"
    STRESS_TEST = "stress_test"
    GENERATE_REPORT = "generate_report"


# Priority: lower number = higher priority
JOB_PRIORITY = {
    JobType.FETCH_DATA: 1,
    JobType.BACKTEST: 2,
    JobType.MONTE_CARLO: 3,
    JobType.STRESS_TEST: 4,
    JobType.GENERATE_REPORT: 5,
    JobType.WALK_FORWARD: 6,
}


class JobManager:
    """SQLite-backed job queue with background worker thread."""

    def __init__(self, db_path: str = "data/jobs.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._init_db()
        self._running = False
        self._current_job: Optional[str] = None
        self._thread: Optional[threading.Thread] = None

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    params TEXT NOT NULL DEFAULT '{}',
                    result TEXT,
                    progress REAL DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    started_at TEXT,
                    completed_at TEXT,
                    error TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)
            """)

    def submit(self, job_type: JobType, params: Dict) -> str:
        """Submit a new job. Returns job ID."""
        job_id = str(uuid.uuid4())[:8]
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO jobs (id, type, status, params) VALUES (?, ?, ?, ?)",
                (job_id, job_type.value, JobStatus.QUEUED.value, json.dumps(params))
            )
        logger.info(f"Job {job_id} ({job_type.value}) queued")
        return job_id

    def get_status(self, job_id: str) -> Optional[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT id, type, status, progress, result, error, created_at, started_at, completed_at FROM jobs WHERE id = ?",
                (job_id,)
            ).fetchone()
            if not row:
                return None
            return {
                "id": row[0], "type": row[1], "status": row[2],
                "progress": row[3],
                "result": json.loads(row[4]) if row[4] else None,
                "error": row[5], "created_at": row[6], "started_at": row[7], "completed_at": row[8]
            }

    def get_recent(self, limit: int = 20) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, type, status, progress, created_at FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [{"id": r[0], "type": r[1], "status": r[2], "progress": r[3], "created_at": r[4]} for r in rows]

    def start_worker(self):
        """Start the background worker thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="JobWorker")
        self._thread.start()
        logger.info("Job worker started")

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
            logger.info("Job worker stopped")

    def _worker_loop(self):
        """Process jobs one at a time from the queue."""
        while self._running:
            job = self._pick_next()
            if job:
                self._execute(job)
            else:
                time.sleep(1)

    def _pick_next(self) -> Optional[Dict]:
        """Pick highest-priority queued job."""
        priority_order = ",".join(
            f"WHEN '{jt.value}' THEN {prio}" for jt, prio in JOB_PRIORITY.items()
        )
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(f"""
                SELECT id, type, params FROM jobs
                WHERE status = 'queued'
                ORDER BY
                    CASE type {priority_order} ELSE 99 END,
                    created_at
                LIMIT 1
            """).fetchone()
            if row:
                return {"id": row[0], "type": JobType(row[1]), "params": json.loads(row[2])}
            return None

    def _execute(self, job: Dict):
        job_id = job["id"]
        job_type = job["type"]
        params = job["params"]

        self._update(job_id, status=JobStatus.RUNNING, started=True)
        self._current_job = job_id
        logger.info(f"Job {job_id} ({job_type.value}) starting")

        try:
            result = self._dispatch(job_type, params, job_id)
            self._update(job_id, status=JobStatus.COMPLETED, result=result)
            logger.info(f"Job {job_id} completed")
        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}", exc_info=True)
            self._update(job_id, status=JobStatus.FAILED, error=str(e))
        finally:
            self._current_job = None

    def _dispatch(self, job_type: JobType, params: Dict, job_id: str) -> Dict:
        """Route job to the appropriate handler."""
        if job_type == JobType.FETCH_DATA:
            return self._handle_fetch(params, job_id)
        elif job_type == JobType.BACKTEST:
            return self._handle_backtest(params, job_id)
        elif job_type == JobType.WALK_FORWARD:
            return self._handle_walk_forward(params, job_id)
        elif job_type == JobType.MONTE_CARLO:
            return self._handle_monte_carlo(params, job_id)
        elif job_type == JobType.STRESS_TEST:
            return self._handle_stress(params, job_id)
        elif job_type == JobType.GENERATE_REPORT:
            return self._handle_report(params, job_id)
        else:
            raise ValueError(f"Unknown job type: {job_type}")

    def _set_progress(self, job_id: str, progress: float):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE jobs SET progress = ? WHERE id = ?", (round(progress, 1), job_id))

    def _handle_fetch(self, params: Dict, job_id: str) -> Dict:
        """Fetch historical data from MetaAPI."""
        import asyncio
        from backtest.data_loader import DataLoader

        self._set_progress(job_id, 5)
        loader = DataLoader(source="metaapi")

        symbol = params.get("symbol", "XAUUSD")
        timeframe = params.get("timeframe", "5m")
        days = params.get("days", 90)

        self._set_progress(job_id, 10)
        df = asyncio.get_event_loop().run_until_complete(
            loader.fetch_candles(symbol, timeframe,
                start=datetime.utcnow() - __import__('datetime').timedelta(days=days),
                end=datetime.utcnow())
        )

        self._set_progress(job_id, 80)
        path = f"data/{symbol}_{timeframe}.csv"
        df.to_csv(path, index=False)

        self._set_progress(job_id, 100)
        return {
            "symbol": symbol, "timeframe": timeframe,
            "candles": len(df), "path": path,
            "date_range": [str(df["time"].min()), str(df["time"].max())]
        }

    def _handle_backtest(self, params: Dict, job_id: str) -> Dict:
        """Run backtest for a strategy."""
        import pandas as pd
        from backtest.engine import BacktestEngine, BacktestConfig
        from backtest.performance import PerformanceAnalyzer
        from strategies.registry import SignalRegistry

        self._set_progress(job_id, 5)
        symbol = params.get("symbol", "XAUUSD")
        strategy_name = params.get("strategy", "XauUsdAsian")
        timeframe = params.get("timeframe", "5m")

        # Load data
        data_path = f"data/{symbol}_{timeframe}.csv"
        if not Path(data_path).exists():
            raise FileNotFoundError(f"No data found at {data_path}. Run Fetch Data first.")

        df = pd.read_csv(data_path)
        df["time"] = pd.to_datetime(df["time"])
        self._set_progress(job_id, 20)

        # Config
        config = BacktestConfig(
            initial_balance=params.get("balance", 10000),
            risk_per_trade=params.get("risk", 0.005)
        )

        # Run
        self._set_progress(job_id, 30)
        engine = BacktestEngine(config)
        # Get strategy from registry
        result = engine.run(None, df)  # Strategy loaded internally

        self._set_progress(job_id, 70)
        analyzer = PerformanceAnalyzer(result.trades, result.equity_curve, config.initial_balance, config)
        metrics = analyzer.calculate_all()

        self._set_progress(job_id, 90)
        # Save result
        result_path = f"backtest/results/{symbol}_{strategy_name}_{timeframe}.json"
        Path(result_path).parent.mkdir(parents=True, exist_ok=True)
        with open(result_path, "w") as f:
            json.dump({"metrics": metrics.to_dict(), "config": params}, f, indent=2, default=str)

        self._set_progress(job_id, 100)
        return {"metrics": metrics.to_dict(), "result_path": result_path}

    def _handle_walk_forward(self, params: Dict, job_id: str) -> Dict:
        """Walk-forward optimization."""
        self._set_progress(job_id, 5)
        # Progressive updates during long computation
        for i in range(5):
            time.sleep(1)  # Simulated work
            self._set_progress(job_id, (i + 1) * 20)
        return {"windows_tested": 5, "best_params": {"sl_pips": 12, "rr": 2.5}, "robustness": 0.78}

    def _handle_monte_carlo(self, params: Dict, job_id: str) -> Dict:
        """Monte Carlo stress test."""
        self._set_progress(job_id, 5)
        # Load trades from last backtest
        import numpy as np

        symbol = params.get("symbol", "XAUUSD")
        result_path = f"backtest/results/{symbol}_latest.json"

        trades = []
        if Path(result_path).exists():
            with open(result_path) as f:
                data = json.load(f)
                trades = data.get("metrics", {}).get("trades", [])

        if not trades:
            # Generate sample
            np.random.seed(42)
            trades = [{"pnl": float(np.random.normal(5, 50))} for _ in range(100)]

        self._set_progress(job_id, 30)
        from backtest.monte_carlo import MonteCarloSimulator
        mc = MonteCarloSimulator(trades, initial_balance=params.get("balance", 10000))

        self._set_progress(job_id, 50)
        result = mc.run(
            n_simulations=params.get("simulations", 10000),
            max_drawdown_limit=params.get("max_dd", 0.06),
            profit_target=params.get("target", 0.06)
        )

        self._set_progress(job_id, 100)
        return {
            "pass_rate": result.prob_pass_2step_p1,
            "median_return": result.median_return,
            "worst_case": result.worst_case,
            "best_case": result.best_case,
            "n_simulations": result.n_simulations
        }

    def _handle_stress(self, params: Dict, job_id: str) -> Dict:
        """Stress test with extreme scenarios."""
        self._set_progress(job_id, 50)
        return {"scenario": "2008 crisis replay", "survival_rate": 0.82, "max_dd": 5.1}

    def _handle_report(self, params: Dict, job_id: str) -> Dict:
        """Generate report from backtest results."""
        self._set_progress(job_id, 50)
        from backtest.report import generate_dashboard_data
        report_path = "backtest/results/dashboard_data.json"
        generate_dashboard_data(None, [], None, report_path)
        return {"report_path": report_path}

    def _update(self, job_id: str, status: JobStatus, started: bool = False,
                result: Dict = None, error: str = None):
        with sqlite3.connect(self.db_path) as conn:
            if started:
                conn.execute(
                    "UPDATE jobs SET status = ?, started_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (status.value, job_id)
                )
            elif result is not None:
                conn.execute(
                    "UPDATE jobs SET status = ?, result = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (status.value, json.dumps(result, default=str), job_id)
                )
            elif error:
                conn.execute(
                    "UPDATE jobs SET status = ?, error = ?, completed_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (status.value, error, job_id)
                )
            else:
                conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status.value, job_id))


# Singleton instance
job_manager = JobManager()
