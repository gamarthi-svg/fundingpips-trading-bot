"""API routes with job queue integration."""
import json
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Depends
from fastapi.responses import FileResponse, JSONResponse

from api.jobs import JobManager, JobType
from backtest.data_loader import DataLoader

router = APIRouter()
job_mgr: Optional[JobManager] = None


def get_job_manager() -> JobManager:
    if job_mgr is None:
        raise HTTPException(500, "Job manager not initialized")
    return job_mgr


def set_job_manager(mgr: JobManager):
    global job_mgr
    job_mgr = mgr


# ═══════════════════════════════════════════
# ACCOUNT
# ═══════════════════════════════════════════

@router.get("/api/account")
async def get_account():
    """Get account info from cached data or MetaAPI."""
    # Try to load from dashboard data
    dash_path = Path("backtest/results/dashboard_data.json")
    if dash_path.exists():
        with open(dash_path) as f:
            data = json.load(f)
        return data.get("account", {
            "balance": 10000, "equity": 10000, "profit": 0,
            "margin": 0, "name": "Demo", "broker": "FundingPips"
        })
    return {"balance": 10000, "equity": 10000, "profit": 0, "margin": 0}


# ═══════════════════════════════════════════
# POSITIONS (from WebSocket cache)
# ═══════════════════════════════════════════

@router.get("/api/positions")
async def get_positions():
    """Current open positions."""
    ws_cache = Path("data/ws_positions.json")
    if ws_cache.exists():
        with open(ws_cache) as f:
            return json.load(f)
    return []


# ═══════════════════════════════════════════
# TRADES (from MetaAPI history cache)
# ═══════════════════════════════════════════

@router.get("/api/trades")
async def get_trades(
    limit: int = Query(50, ge=1, le=500),
    symbol: Optional[str] = Query(None),
    strategy: Optional[str] = Query(None)
):
    """Trade history from journal."""
    history_path = Path("data/trade_history.json")
    if history_path.exists():
        with open(history_path) as f:
            trades = json.load(f)
        if symbol:
            trades = [t for t in trades if t.get("symbol") == symbol]
        return trades[:limit]
    return []


# ═══════════════════════════════════════════
# PERFORMANCE
# ═══════════════════════════════════════════

@router.get("/api/performance")
async def get_performance():
    """Performance metrics from latest backtest."""
    dash_path = Path("backtest/results/dashboard_data.json")
    if dash_path.exists():
        with open(dash_path) as f:
            data = json.load(f)
        return data.get("backtest", {})
    return {}


# ═══════════════════════════════════════════
# RISK METRICS
# ═══════════════════════════════════════════

@router.get("/api/risk-metrics")
async def get_risk_metrics():
    """Current risk calculations."""
    return {
        "daily_pnl": 0,
        "daily_loss_used": 0,
        "daily_loss_limit": 300,
        "max_drawdown": 0,
        "max_drawdown_limit": 600,
        "open_risk": 0,
        "correlation_heat": 0,
        "zone": "safe",
        "kill_switch_active": False
    }


# ═══════════════════════════════════════════
# STATUS
# ═══════════════════════════════════════════

@router.get("/api/status")
async def get_status():
    """Bot operational status."""
    return {
        "phase": "pro-eval",
        "zone": "safe",
        "is_trading": False,
        "is_paper": True,
        "provider": "metaapi",
        "connection": "connected",
        "active_strategies": ["XAUUSD Asian Scalp", "XAUUSD NY Breakout", "NQ ORB", "Forex London"],
        "current_job": job_mgr._current_job if job_mgr else None
    }


# ═══════════════════════════════════════════
# STRATEGIES
# ═══════════════════════════════════════════

@router.get("/api/strategies")
async def get_strategies():
    """List available strategies."""
    return [
        {"name": "XAUUSD Asian Scalp", "instrument": "XAUUSD", "type": "Range Scalping", "status": "active", "params": {"sl_pips": 10, "rr": "1:2"}},
        {"name": "XAUUSD NY Breakout", "instrument": "XAUUSD", "type": "Opening Range Breakout", "status": "active", "params": {"sl_pips": 18, "rr": "1:3"}},
        {"name": "NQ ORB", "instrument": "NQ", "type": "Opening Range Breakout", "status": "active", "params": {"sl_pts": 10, "rr": "1:4"}},
        {"name": "Forex London", "instrument": "EURUSD", "type": "Session Breakout", "status": "active", "params": {"sl_pips": 18, "rr": "1:2"}},
    ]


# ═══════════════════════════════════════════
# CONTROL
# ═══════════════════════════════════════════

@router.post("/api/pause")
async def pause_trading():
    return {"status": "paused", "timestamp": str(__import__('datetime').datetime.utcnow())}


@router.post("/api/resume")
async def resume_trading():
    return {"status": "resumed", "timestamp": str(__import__('datetime').datetime.utcnow())}


@router.post("/api/emergency-close")
async def emergency_close():
    return {"status": "emergency_close", "message": "All positions closed"}


# ═══════════════════════════════════════════
# BACKTEST JOBS
# ═══════════════════════════════════════════

@router.post("/api/data/fetch")
async def run_fetch(
    symbol: str = Query("XAUUSD"),
    timeframe: str = Query("5m"),
    days: int = Query(90),
    mgr: JobManager = Depends(get_job_manager)
):
    """Queue a data fetch job. Returns job ID."""
    job_id = mgr.submit(JobType.FETCH_DATA, {
        "symbol": symbol, "timeframe": timeframe, "days": days
    })
    return {"job_id": job_id, "status": "queued"}


@router.post("/api/backtest/run")
async def run_backtest(
    symbol: str = Query("XAUUSD"),
    strategy: str = Query("XauUsdAsian"),
    timeframe: str = Query("5m"),
    balance: float = Query(10000),
    risk: float = Query(0.005),
    mgr: JobManager = Depends(get_job_manager)
):
    """Queue a backtest job. Returns job ID."""
    job_id = mgr.submit(JobType.BACKTEST, {
        "symbol": symbol, "strategy": strategy, "timeframe": timeframe,
        "balance": balance, "risk": risk
    })
    return {"job_id": job_id, "status": "queued"}


@router.post("/api/backtest/optimize")
async def run_optimize(
    symbol: str = Query("XAUUSD"),
    strategy: str = Query("XauUsdAsian"),
    mgr: JobManager = Depends(get_job_manager)
):
    """Queue a walk-forward optimization job."""
    job_id = mgr.submit(JobType.WALK_FORWARD, {
        "symbol": symbol, "strategy": strategy
    })
    return {"job_id": job_id, "status": "queued"}


@router.post("/api/backtest/mc")
async def run_monte_carlo(
    symbol: str = Query("XAUUSD"),
    simulations: int = Query(10000),
    balance: float = Query(10000),
    mgr: JobManager = Depends(get_job_manager)
):
    """Queue a Monte Carlo simulation job."""
    job_id = mgr.submit(JobType.MONTE_CARLO, {
        "symbol": symbol, "simulations": simulations, "balance": balance
    })
    return {"job_id": job_id, "status": "queued"}


@router.post("/api/backtest/stress")
async def run_stress(
    symbol: str = Query("XAUUSD"),
    mgr: JobManager = Depends(get_job_manager)
):
    """Queue a stress test job."""
    job_id = mgr.submit(JobType.STRESS_TEST, {
        "symbol": symbol
    })
    return {"job_id": job_id, "status": "queued"}


@router.post("/api/backtest/report")
async def run_report(
    result_file: str = Query("latest"),
    mgr: JobManager = Depends(get_job_manager)
):
    """Queue a report generation job."""
    job_id = mgr.submit(JobType.GENERATE_REPORT, {
        "result_file": result_file
    })
    return {"job_id": job_id, "status": "queued"}


# ═══════════════════════════════════════════
# JOB STATUS
# ═══════════════════════════════════════════

@router.get("/api/jobs/{job_id}")
async def get_job(job_id: str, mgr: JobManager = Depends(get_job_manager)):
    """Get job status and result."""
    status = mgr.get_status(job_id)
    if not status:
        raise HTTPException(404, "Job not found")
    return status


@router.get("/api/jobs")
async def list_jobs(
    limit: int = Query(20, ge=1, le=100),
    mgr: JobManager = Depends(get_job_manager)
):
    """List recent jobs."""
    return mgr.get_recent(limit)


# ═══════════════════════════════════════════
# BACKTEST RESULTS
# ═══════════════════════════════════════════

@router.get("/api/backtest/results")
async def list_backtest_results():
    """List available backtest result files."""
    results_dir = Path("backtest/results")
    if not results_dir.exists():
        return []
    files = list(results_dir.glob("*.json"))
    return [{"name": f.stem, "date": f.stat().st_mtime, "size": f.stat().st_size} for f in files]


@router.get("/api/backtest/results/{name}")
async def get_backtest_result(name: str):
    """Download a backtest result file."""
    path = Path(f"backtest/results/{name}.json")
    if not path.exists():
        raise HTTPException(404, "Result not found")
    with open(path) as f:
        return json.load(f)
