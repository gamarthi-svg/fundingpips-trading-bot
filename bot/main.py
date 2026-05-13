#!/usr/bin/env python3
"""
Prop Firm Trading Bot — Main Async Entry Point.

This module implements the primary asynchronous trading loop for a prop-firm-
compliant algorithmic trading system. It orchestrates configuration loading,
trading-provider connectivity (MT5 or MetaAPI), risk management, strategy
signal generation, trade execution, session tracking, news filtering, structured
logging, and a FastAPI dashboard.

The provider backend is selected via ``TradingProviderFactory`` so the same
code path works with both local MT5 and cloud MetaAPI accounts.

Usage::

    python main.py

Environment variables (see ``.env.example``)::

    MT5_ACCOUNT   — MetaTrader 5 account number
    MT5_PASSWORD  — MetaTrader 5 password
    MT5_SERVER    — MetaTrader 5 broker server name
    METAAPI_TOKEN — MetaAPI.cloud token (when provider=metaapi)
    METAAPI_ACCOUNT_ID — MetaAPI account ID (when provider=metaapi)
    TELEGRAM_BOT_TOKEN  — Telegram bot API token
    TELEGRAM_CHAT_ID    — Target Telegram chat/channel ID
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import signal
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI

# ---------------------------------------------------------------------------
# Internal project imports
# ---------------------------------------------------------------------------
from config import load_config  # noqa: E402
from execution import OrderManager  # noqa: E402
from execution.factory import TradingProviderFactory  # noqa: E402
from journal import TradeLogger  # noqa: E402
from risk import KillSwitchError, RiskManager  # noqa: E402
from session import SessionManager  # noqa: E402
from strategies import SignalRegistry  # noqa: E402
from utils import NotificationManager  # noqa: E402

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("trading_bot")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TICK_INTERVAL: float = 5.0  # seconds between loop iterations
DASHBOARD_PORT: int = 8080
CONFIG_PATH: Path = Path("config.json")

# Connection retry constants
CONNECT_MAX_RETRIES: int = 3
CONNECT_RETRY_DELAY_BASE: float = 2.0  # seconds — doubled on each retry

# ---------------------------------------------------------------------------
# Global state (mutable, protected by shutdown logic)
# ---------------------------------------------------------------------------
_shutdown_event: asyncio.Event = asyncio.Event()
_components: dict[str, Any] = {}


# ===========================================================================
# FastAPI dashboard
# ===========================================================================

dashboard_app = FastAPI(title="Prop Firm Trading Bot Dashboard", version="1.0.0")


@dashboard_app.get("/health")
async def health_check() -> dict[str, str]:
    """Liveness probe for container orchestrators."""
    return {"status": "ok"}


@dashboard_app.get("/state")
async def get_state() -> dict[str, Any]:
    """Return current bot state snapshot including active provider info."""
    state: dict[str, Any] = {
        "running": not _shutdown_event.is_set(),
        "provider": {},
    }

    # --- Provider info ------------------------------------------------------
    provider = _components.get("provider")
    if provider is not None:
        try:
            state["provider"]["name"] = provider.get_provider_name()
            state["provider"]["connected"] = provider.is_connected
        except Exception:
            state["provider"]["error"] = "unable to query provider"
    else:
        state["provider"]["status"] = "not initialised"

    # --- Risk manager -------------------------------------------------------
    rm = _components.get("risk_manager")
    if rm is not None:
        try:
            state["risk"] = rm.summary()
        except Exception:
            state["risk"] = {}

    # --- Order manager / positions ------------------------------------------
    om = _components.get("order_manager")
    if om is not None:
        try:
            state["positions"] = om.position_count()
        except Exception:
            state["positions"] = 0

    return state


def _run_dashboard() -> None:
    """Blocking call to start uvicorn — intended to run in a thread."""
    uvicorn.run(
        dashboard_app,
        host="0.0.0.0",
        port=DASHBOARD_PORT,
        log_level="warning",
        access_log=False,
    )


# ===========================================================================
# Component initialisation helpers
# ===========================================================================

def _init_components(cfg: dict[str, Any]) -> dict[str, Any]:
    """Instantiate all trading subsystems.

    Parameters
    ----------
    cfg:
        Parsed configuration dict (from ``config.json``).

    Returns
    -------
    dict[str, Any]
        Mapping of component name -> instance.
    """
    components: dict[str, Any] = {}

    # --- Trading provider (factory-selected backend) ------------------------
    # The factory inspects cfg (and env vars) to decide between MT5 local
    # and MetaAPI cloud.  The resulting object implements TradingProvider.
    components["provider"] = TradingProviderFactory.create_provider(cfg)

    # --- Phase management ---------------------------------------------------
    from risk import PhaseManager  # noqa: F811
    components["phase_manager"] = PhaseManager(cfg)

    # --- Risk management ----------------------------------------------------
    components["risk_manager"] = RiskManager(cfg)

    # --- Strategy / signal pipeline -----------------------------------------
    components["signal_registry"] = SignalRegistry(cfg)

    # --- Execution ----------------------------------------------------------
    # OrderManager receives the provider so it can delegate order execution.
    components["order_manager"] = OrderManager(cfg)

    # --- Session tracking ---------------------------------------------------
    components["session_manager"] = SessionManager(cfg)

    # --- News filter --------------------------------------------------------
    try:
        from session import NewsFilter  # noqa: F811
        components["news_filter"] = NewsFilter(cfg)
    except Exception as exc:  # pragma: no cover
        logger.warning("NewsFilter unavailable: %s", exc)
        components["news_filter"] = None

    # --- Trade journal ------------------------------------------------------
    components["trade_logger"] = TradeLogger(cfg)

    # --- Notifications ------------------------------------------------------
    components["notifier"] = NotificationManager(cfg)

    return components


# ===========================================================================
# Provider connection with retry
# ===========================================================================

async def _connect_provider_with_retry(
    provider: Any,
    max_retries: int = CONNECT_MAX_RETRIES,
    base_delay: float = CONNECT_RETRY_DELAY_BASE,
) -> bool:
    """Connect to the trading provider with exponential-backoff retries.

    Parameters
    ----------
    provider:
        TradingProvider instance (has ``connect()`` coroutine).
    max_retries:
        Maximum number of connection attempts.
    base_delay:
        Initial delay between retries in seconds.

    Returns
    -------
    bool
        True if connected successfully.

    Raises
    ------
    SystemExit
        If all retries are exhausted.
    """
    for attempt in range(1, max_retries + 1):
        try:
            connected = await provider.connect()
            if connected:
                logger.info(
                    "Provider '%s' connected (attempt %d/%d)",
                    provider.get_provider_name(),
                    attempt,
                    max_retries,
                )
                return True
            logger.warning(
                "Provider connect returned False on attempt %d/%d",
                attempt,
                max_retries,
            )
        except Exception as exc:
            logger.error(
                "Provider connection error on attempt %d/%d: %s",
                attempt,
                max_retries,
                exc,
            )

        if attempt < max_retries:
            delay = base_delay * (2 ** (attempt - 1))
            logger.info("Retrying provider connection in %.1f seconds...", delay)
            await asyncio.sleep(delay)

    logger.critical(
        "Failed to connect to provider '%s' after %d attempts",
        provider.get_provider_name(),
        max_retries,
    )
    return False


# ===========================================================================
# Core trading loop
# ===========================================================================

async def _tick(components: dict[str, Any], cfg: dict[str, Any]) -> None:
    """Execute a single iteration of the trading loop.

    Steps (in order):
    1. Refresh account info from the active trading provider.
    2. Update trading phase if profit / drawdown thresholds are crossed.
    3. Update risk metrics and abort if the kill switch fires.
    4. Validate session timing and check for news blackouts.
    5. Fetch market data and generate signals from active strategies.
    6. Execute the highest-confidence signal (with mild randomisation).
    7. Log the trade and push a dashboard / Telegram update.
    """
    provider = components["provider"]
    phase_mgr = components["phase_manager"]
    risk_mgr: RiskManager = components["risk_manager"]
    signal_reg: SignalRegistry = components["signal_registry"]
    order_mgr: OrderManager = components["order_manager"]
    session_mgr: SessionManager = components["session_manager"]
    news_filter = components.get("news_filter")
    trade_logger: TradeLogger = components["trade_logger"]
    notifier: NotificationManager = components["notifier"]

    # ------------------------------------------------------------------
    # 1. Account info (async provider call)
    # ------------------------------------------------------------------
    try:
        account_info = await provider.get_account_info()
    except Exception as exc:
        logger.error("Failed to fetch account info: %s", exc)
        return

    balance = account_info.balance
    equity = account_info.equity

    # ------------------------------------------------------------------
    # 2. Phase management
    # ------------------------------------------------------------------
    try:
        phase_changed = phase_mgr.update(equity=equity)
        if phase_changed:
            logger.info("Phase changed to: %s", phase_mgr.current_phase)
            notifier.push(f"Phase changed: {phase_mgr.current_phase}")
    except Exception as exc:
        logger.error("Phase manager error: %s", exc)

    # ------------------------------------------------------------------
    # 3. Risk metrics & kill switch (async positions call)
    # ------------------------------------------------------------------
    try:
        open_positions = await provider.get_positions()
        risk_mgr.update(balance=balance, equity=equity, open_positions=open_positions)
        risk_mgr.check_limits()
    except KillSwitchError as exc:
        logger.critical("Kill switch activated: %s", exc)
        notifier.push(f"KILL SWITCH: {exc}")
        _shutdown_event.set()
        return
    except Exception as exc:
        logger.error("Risk manager error: %s", exc)
        return

    # ------------------------------------------------------------------
    # 4. Session validity & news blackout
    # ------------------------------------------------------------------
    try:
        if not session_mgr.is_valid():
            logger.debug("Outside trading session — skipping tick.")
            return
    except Exception as exc:
        logger.error("Session manager error: %s", exc)
        return

    if news_filter is not None:
        try:
            if await news_filter.in_blackout():
                logger.debug("News blackout active — skipping signal generation.")
                return
        except Exception as exc:
            logger.error("News filter error: %s", exc)

    # ------------------------------------------------------------------
    # 5. Market data & signal generation (async rates call)
    # ------------------------------------------------------------------
    instruments: list[str] = cfg.get("instruments", [])
    if not instruments:
        logger.warning("No instruments configured.")
        return

    all_signals: list[dict[str, Any]] = []
    for symbol in instruments:
        try:
            rates = await provider.get_rates(symbol, timeframe=cfg.get("timeframe", 15), count=100)
            if rates is None or len(rates) == 0:
                continue
            signals = signal_reg.generate(symbol=symbol, ticks=rates)
            all_signals.extend(signals)
        except Exception as exc:
            logger.error("Signal generation error for %s: %s", symbol, exc)

    if not all_signals:
        logger.debug("No signals generated this tick.")
        return

    # Sort by descending confidence
    all_signals.sort(key=lambda s: s.get("confidence", 0.0), reverse=True)

    # ------------------------------------------------------------------
    # 6. Execute best signal with randomisation
    # ------------------------------------------------------------------
    best_signal = all_signals[0]

    # Mild randomisation: 15 % chance to skip the top signal and try the
    # second-best (when available). This reduces predictability without
    # materially degrading performance.
    if len(all_signals) > 1 and random.random() < 0.15:
        best_signal = all_signals[1]
        logger.info("Randomised signal selection — using second-best signal.")

    try:
        ticket = order_mgr.execute(signal=best_signal, risk_profile=risk_mgr.current_profile())
        if ticket is not None:
            logger.info(
                "Executed %s on %s (ticket=%s, confidence=%.2f)",
                best_signal.get("direction"),
                best_signal.get("symbol"),
                ticket,
                best_signal.get("confidence", 0.0),
            )

            # 7. Log trade & push notifications
            trade_logger.log(
                signal=best_signal,
                ticket=ticket,
                balance=balance,
                equity=equity,
            )
            notifier.push(
                f"Trade executed: {best_signal.get('symbol')} "
                f"{best_signal.get('direction')} (conf={best_signal.get('confidence', 0):.2f})"
            )
        else:
            logger.info("Signal filtered by execution layer — no trade.")
    except Exception as exc:
        logger.error("Execution error: %s", exc)
        notifier.push(f"Execution error: {exc}")


# ===========================================================================
# Main loop
# ===========================================================================

async def main_loop() -> None:
    """Run the complete trading lifecycle.

    1. Load configuration from ``config.json``.
    2. Create trading provider via factory (MT5 or MetaAPI).
    3. Connect to the provider with retry logic.
    4. Initialise all subsystems.
    5. Start FastAPI dashboard in background.
    6. Run the tick loop every :data:`TICK_INTERVAL` seconds.
    7. On shutdown: close all positions, disconnect provider.
    """
    # --- Logging setup ------------------------------------------------------
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("trading_bot.log", encoding="utf-8"),
        ],
    )
    logger.info("=" * 60)
    logger.info("Prop Firm Trading Bot starting up")
    logger.info("=" * 60)

    # --- Environment variables ----------------------------------------------
    env_path = Path(".env")
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
        logger.info("Loaded environment from .env")

    # --- Configuration ------------------------------------------------------
    cfg = load_config(CONFIG_PATH)
    logger.info("Configuration loaded from %s", CONFIG_PATH)

    # --- Provider selection & display ---------------------------------------
    provider_type = cfg.get("provider", "mt5")
    logger.info("Trading provider type configured: %s", provider_type)

    # --- Component initialisation -------------------------------------------
    global _components
    _components = _init_components(cfg)
    provider = _components["provider"]
    logger.info(
        "Provider '%s' initialised via TradingProviderFactory",
        provider.get_provider_name(),
    )
    logger.info("All subsystems initialised")

    # --- Provider connection (with retry) -----------------------------------
    connected = await _connect_provider_with_retry(provider)
    if not connected:
        logger.critical("Unable to establish provider connection — exiting")
        sys.exit(1)

    _components["notifier"].push(
        f"Bot connected to {provider.get_provider_name()}"
    )

    # --- Dashboard (background thread) --------------------------------------
    dashboard_task = asyncio.get_event_loop().run_in_executor(None, _run_dashboard)
    logger.info("Dashboard server started on port %d", DASHBOARD_PORT)

    # --- Graceful shutdown --------------------------------------------------
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _request_shutdown)

    logger.info(
        "Signal handlers registered — ready for trading via %s",
        provider.get_provider_name(),
    )

    try:
        while not _shutdown_event.is_set():
            await _tick(_components, cfg)
            try:
                await asyncio.wait_for(
                    _shutdown_event.wait(), timeout=TICK_INTERVAL
                )
            except asyncio.TimeoutError:
                pass  # Normal — loop continues
    finally:
        logger.info("Shutdown sequence initiated")
        await _shutdown_cleanup()
        # Cancel dashboard thread gracefully (uvicorn will exit when process ends)
        dashboard_task.cancel()
        logger.info("Bot shut down cleanly")


def _request_shutdown() -> None:
    """Signal handler — triggers the async shutdown path."""
    logger.info("Shutdown signal received")
    _shutdown_event.set()


async def _shutdown_cleanup() -> None:
    """Close positions and disconnect from the active trading provider."""
    provider = _components.get("provider")
    order_mgr: OrderManager | None = _components.get("order_manager")
    notifier: NotificationManager | None = _components.get("notifier")

    # Close all open positions via async provider
    if provider is not None:
        try:
            logger.info("Closing all open positions via %s", provider.get_provider_name())
            results = await provider.close_all_positions()
            successes = sum(1 for r in results if r.success)
            logger.info("Closed %d/%d positions", successes, len(results))
            if notifier:
                notifier.push(
                    f"All positions closed ({successes}/{len(results)}) — bot shutting down"
                )
        except Exception as exc:
            logger.error("Error closing positions: %s", exc)

    # Disconnect provider
    if provider is not None:
        try:
            await provider.disconnect()
            logger.info("Provider '%s' disconnected", provider.get_provider_name())
        except Exception as exc:
            logger.error("Error disconnecting provider: %s", exc)


# ===========================================================================
# Entry point
# ===========================================================================

if __name__ == "__main__":
    try:
        asyncio.run(main_loop())
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt — exiting")
        sys.exit(0)
