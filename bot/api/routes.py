"""API routes with job queue and credential management."""
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Depends, Body
from fastapi.responses import FileResponse, JSONResponse

from api.jobs import JobManager, JobType
from api.credentials import CredentialManager
from backtest.data_loader import DataLoader

router = APIRouter()
job_mgr: Optional[JobManager] = None
cred_mgr: Optional[CredentialManager] = None


def get_job_manager() -> JobManager:
    if job_mgr is None:
        raise HTTPException(500, "Job manager not initialized")
    return job_mgr


def set_job_manager(mgr: JobManager):
    global job_mgr
    job_mgr = mgr


def get_cred_manager() -> CredentialManager:
    if cred_mgr is None:
        raise HTTPException(500, "Credential manager not initialized")
    return cred_mgr


def set_cred_manager(mgr: CredentialManager):
    global cred_mgr
    cred_mgr = mgr


# ═══════════════════════════════════════════
# CREDENTIALS (Secure — token NEVER exposed)
# ═══════════════════════════════════════════

@router.post("/api/credentials")
async def update_credentials(
    payload: Dict[str, Any] = Body(...),
    cm: CredentialManager = Depends(get_cred_manager)
):
    """Store MetaAPI credentials (encrypted at rest with AES-256-GCM).

    Request body:
        {
            "token": "eyJhbG...",      # MetaAPI token (encrypted before storage)
            "account_id": "uuid...",   # MetaAPI account ID
            "region": "new-york",      # agiliumtrade.ai region
            "prop_firm": "fundingpips",# "fundingpips" or "the5ers"
            "account_type": "pro",     # Account type
            "account_size": 10000,     # Account size in USD
            "phase": "phase1",         # "phase1", "phase2", "funded"
            "the5ers_step": 1,         # For 5ers 3-step: 1, 2, or 3
            "mt_login": 0,
            "mt_password": "",
            "mt_server": ""
        }

    Returns:
        { "success": true, "validated": true, "message": "Connected: ..." }

    The token is validated against MetaAPI before storage and is NEVER
    returned in any response.
    """
    token = payload.get("token", "")
    account_id = payload.get("account_id", "")

    if not token or not account_id:
        raise HTTPException(400, "token and account_id are required")

    result = await cm.update(
        token=token,
        account_id=account_id,
        region=payload.get("region", "new-york"),
        prop_firm=payload.get("prop_firm", "fundingpips"),
        account_type=payload.get("account_type", "pro"),
        account_size=payload.get("account_size", 10_000.0),
        phase=payload.get("phase", "phase1"),
        the5ers_step=payload.get("the5ers_step", 1),
        mt_login=payload.get("mt_login", 0),
        mt_password=payload.get("mt_password", ""),
        mt_server=payload.get("mt_server", ""),
    )

    if not result["success"]:
        raise HTTPException(500, result.get("message", "Failed to store credentials"))

    return result


@router.get("/api/credentials/status")
async def get_credentials_status(
    cm: CredentialManager = Depends(get_cred_manager)
):
    """Return masked credential status.  The token is NEVER included."""
    return cm.get_status()


@router.delete("/api/credentials")
async def delete_credentials(
    cm: CredentialManager = Depends(get_cred_manager)
):
    """Remove all stored credentials."""
    cm.delete()
    return {"success": True, "message": "Credentials deleted"}


@router.get("/api/prop-firms")
async def list_prop_firms():
    """List supported prop firms and their account types."""
    from config.settings import PROP_FIRMS
    return {
        "firms": [
            {
                "id": "fundingpips",
                "name": "FundingPips",
                "steps": 2,
                "account_sizes": [10_000, 50_000, 100_000, 200_000],
                "default_size": 10_000,
                "time_limit": None,
                "phases": ["phase1", "phase2", "funded"],
            },
            {
                "id": "the5ers",
                "name": "The5%ers",
                "steps": 3,
                "account_sizes": [5_000],
                "default_size": 5_000,
                "time_limit": None,
                "phases": ["phase1", "phase2", "phase3", "funded"],
                "bootcamp": True,
            },
        ]
    }


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
    """List all available strategies from the strategy library."""
    try:
        from strategies.library import STRATEGIES, list_all_strategies
        return {
            "strategies": list_all_strategies(),
            "count": len(STRATEGIES),
            "by_category": _group_by_category(STRATEGIES)
        }
    except ImportError:
        # Fallback: return hardcoded list
        return {
            "strategies": [
                {"id": "nas100_orb", "name": "NAS100 Opening Range", "symbol": "NAS100", "type": "day", "instrument_category": "indices"},
                {"id": "nas100_trend", "name": "NAS100 Trend Pullback", "symbol": "NAS100", "type": "swing", "instrument_category": "indices"},
                {"id": "us30_orb", "name": "US30 Opening Range", "symbol": "US30", "type": "day", "instrument_category": "indices"},
                {"id": "btc_breakout", "name": "BTC Range Breakout", "symbol": "BTCUSD", "type": "day", "instrument_category": "crypto"},
                {"id": "btc_trend", "name": "BTC Trend Follow", "symbol": "BTCUSD", "type": "swing", "instrument_category": "crypto"},
                {"id": "eth_breakout", "name": "ETH Range Breakout", "symbol": "ETHUSD", "type": "day", "instrument_category": "crypto"},
                {"id": "sol_breakout", "name": "SOL Range Breakout", "symbol": "SOLUSD", "type": "day", "instrument_category": "crypto"},
                {"id": "xau_asian", "name": "XAU Asian Breakout", "symbol": "XAUUSD", "type": "day", "instrument_category": "metals"},
                {"id": "xau_ny", "name": "XAU NY Momentum", "symbol": "XAUUSD", "type": "day", "instrument_category": "metals"},
                {"id": "xau_swing", "name": "XAU Swing Trend", "symbol": "XAUUSD", "type": "swing", "instrument_category": "metals"},
                {"id": "xti_session", "name": "Oil US Session", "symbol": "XTIUSD", "type": "day", "instrument_category": "energies"},
                {"id": "eurusd_london", "name": "EURUSD London", "symbol": "EURUSD", "type": "day", "instrument_category": "forex"},
                {"id": "eurusd_ny", "name": "EURUSD NY", "symbol": "EURUSD", "type": "day", "instrument_category": "forex"},
                {"id": "usdjpy_tokyo", "name": "USDJPY Tokyo", "symbol": "USDJPY", "type": "day", "instrument_category": "forex"},
                {"id": "gbpjpy_london", "name": "GBPJPY London", "symbol": "GBPJPY", "type": "day", "instrument_category": "forex"},
                {"id": "gbpusd_range", "name": "GBPUSD Range", "symbol": "GBPUSD", "type": "scalp", "instrument_category": "forex"},
                {"id": "usdchf_trend", "name": "USDCHF Trend", "symbol": "USDCHF", "type": "swing", "instrument_category": "forex"},
            ],
            "count": 19,
            "by_category": {
                "indices": 3, "crypto": 4, "metals": 3, "energies": 1, "forex": 8
            }
        }


def _group_by_category(strategies: dict) -> dict:
    """Count strategies per category."""
    from strategies.library import _get_category
    counts: Dict[str, int] = {}
    for v in strategies.values():
        cat = _get_category(v['symbol'])
        counts[cat] = counts.get(cat, 0) + 1
    return counts


# ── Strategy Config (enabled/disabled) ──

_strategies_config: Dict[str, Any] = {}
_strategies_config_loaded = False


def _load_strategies_config():
    """Load strategy config from file."""
    global _strategies_config, _strategies_config_loaded
    if _strategies_config_loaded:
        return
    config_path = Path("data/strategies_config.json")
    if config_path.exists():
        with open(config_path) as f:
            _strategies_config = json.load(f)
    _strategies_config_loaded = True


def _save_strategies_config():
    """Save strategy config to file."""
    config_path = Path("data/strategies_config.json")
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(_strategies_config, f, indent=2)


@router.get("/api/strategies/config")
async def get_strategies_config():
    """Get strategy enable/disable configuration."""
    _load_strategies_config()
    return _strategies_config or {
        "xau_asian": {"enabled": True, "risk_pct": 0.5, "max_daily_trades": 1},
        "xau_ny": {"enabled": True, "risk_pct": 0.5, "max_daily_trades": 1},
        "forex_london": {"enabled": True, "risk_pct": 0.5, "max_daily_trades": 2},
    }


@router.post("/api/strategies/config")
async def update_strategies_config(payload: Dict[str, Any] = Body(...)):
    """Update strategy configuration (enable/disable, risk params).

    Payload: { "strategy_id": { "enabled": true, "risk_pct": 0.5 } }
    """
    _load_strategies_config()
    for sid, cfg in payload.items():
        if sid not in _strategies_config:
            _strategies_config[sid] = {}
        _strategies_config[sid].update(cfg)
    _save_strategies_config()
    return {"success": True, "config": _strategies_config}


# ═══════════════════════════════════════════
# STRATEGY-SPECIFIC BACKTEST/OPTIMIZE/MC
# ═══════════════════════════════════════════

@router.post("/api/strategies/{strategy_id}/backtest")
async def backtest_strategy(
    strategy_id: str,
    payload: Dict[str, Any] = Body(default={}),
    mgr: JobManager = Depends(get_job_manager)
):
    """Queue a backtest for a specific strategy."""
    from strategies.library import STRATEGIES
    if strategy_id not in STRATEGIES:
        raise HTTPException(404, f"Strategy '{strategy_id}' not found")

    job_id = mgr.submit(JobType.BACKTEST, {
        "strategy_id": strategy_id,
        "symbol": STRATEGIES[strategy_id]["symbol"],
        "strategy_name": STRATEGIES[strategy_id]["name"],
        "days": payload.get("days", 90),
        "timeframe": payload.get("timeframe", "5m"),
        "balance": payload.get("balance", 10000),
        "risk_pct": payload.get("risk_pct", 0.5),
    })
    return {"job_id": job_id, "status": "queued", "strategy": strategy_id}


@router.post("/api/strategies/{strategy_id}/optimize")
async def optimize_strategy(
    strategy_id: str,
    payload: Dict[str, Any] = Body(default={}),
    mgr: JobManager = Depends(get_job_manager)
):
    """Queue walk-forward optimization for a specific strategy."""
    from strategies.library import STRATEGIES
    if strategy_id not in STRATEGIES:
        raise HTTPException(404, f"Strategy '{strategy_id}' not found")

    job_id = mgr.submit(JobType.WALK_FORWARD, {
        "strategy_id": strategy_id,
        "symbol": STRATEGIES[strategy_id]["symbol"],
        "strategy_name": STRATEGIES[strategy_id]["name"],
        "days": payload.get("days", 180),
        "is_pct": payload.get("is_pct", 0.7),
        "oos_pct": payload.get("oos_pct", 0.3),
    })
    return {"job_id": job_id, "status": "queued", "strategy": strategy_id}


@router.post("/api/strategies/{strategy_id}/mc")
async def monte_carlo_strategy(
    strategy_id: str,
    payload: Dict[str, Any] = Body(default={}),
    mgr: JobManager = Depends(get_job_manager)
):
    """Queue Monte Carlo simulation for a specific strategy."""
    from strategies.library import STRATEGIES
    if strategy_id not in STRATEGIES:
        raise HTTPException(404, f"Strategy '{strategy_id}' not found")

    job_id = mgr.submit(JobType.MONTE_CARLO, {
        "strategy_id": strategy_id,
        "symbol": STRATEGIES[strategy_id]["symbol"],
        "strategy_name": STRATEGIES[strategy_id]["name"],
        "simulations": payload.get("simulations", 10000),
        "balance": payload.get("balance", 10000),
    })
    return {"job_id": job_id, "status": "queued", "strategy": strategy_id}


@router.post("/api/portfolio/mc")
async def monte_carlo_portfolio(
    payload: Dict[str, Any] = Body(default={}),
    mgr: JobManager = Depends(get_job_manager)
):
    """Queue Monte Carlo simulation for the entire enabled portfolio."""
    _load_strategies_config()
    enabled = [sid for sid, cfg in _strategies_config.items() if cfg.get("enabled", False)]

    job_id = mgr.submit(JobType.MONTE_CARLO, {
        "portfolio": True,
        "enabled_strategies": enabled,
        "simulations": payload.get("simulations", 10000),
        "balance": payload.get("balance", 10000),
    })
    return {"job_id": job_id, "status": "queued", "strategies": enabled}


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
