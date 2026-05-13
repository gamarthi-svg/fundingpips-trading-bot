"""
WebSocket endpoint for real-time trading data streaming.

Provides a ConnectionManager that handles client connections and broadcasts
live trading data (account info, positions, PnL, risk zone) to all connected
dashboard clients every 2 seconds.

Usage:
    The WebSocket is mounted at ``/ws`` by the FastAPI application factory.
    Dashboard clients connect to ``ws://<host>:<port>/ws`` and receive
    a JSON payload on each tick.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

# Dependency injection
from api.dependencies import (
    get_bot_state,
    get_db,
    get_provider,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# --------------------------------------------------------------------------- #
# Connection Manager
# --------------------------------------------------------------------------- #


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts messages.

    Attributes:
        active_connections: List of currently connected WebSocket clients.
    """

    def __init__(self) -> None:
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept a new WebSocket connection and add to the pool.

        Args:
            websocket: The incoming WebSocket connection.
        """
        await websocket.accept()
        self.active_connections.append(websocket)
        client_host = websocket.client.host if websocket.client else "unknown"
        logger.info("WebSocket client connected from %s (total: %d)", client_host, len(self.active_connections))

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a WebSocket connection from the pool.

        Args:
            websocket: The WebSocket connection to remove.
        """
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info("WebSocket client disconnected (total: %d)", len(self.active_connections))

    async def broadcast(self, message: Dict[str, Any]) -> None:
        """Send a JSON message to all connected clients.

        Dead connections are automatically cleaned up.

        Args:
            message: JSON-serialisable dict to broadcast.
        """
        disconnected: List[WebSocket] = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        # Clean up dead connections
        for conn in disconnected:
            self.disconnect(conn)

    async def send_to(self, websocket: WebSocket, message: Dict[str, Any]) -> bool:
        """Send a JSON message to a specific client.

        Args:
            websocket: Target WebSocket connection.
            message: JSON-serialisable dict.

        Returns:
            True if the message was sent successfully.
        """
        try:
            await websocket.send_json(message)
            return True
        except Exception:
            self.disconnect(websocket)
            return False


# Global singleton
manager = ConnectionManager()


# --------------------------------------------------------------------------- #
# Live Data Gathering
# --------------------------------------------------------------------------- #


async def get_live_data() -> Dict[str, Any]:
    """Gather all real-time data from the trading system.

    This function is called every 2 seconds to collect:
        - Account info (balance, equity, margin)
        - Open positions (with unrealised PnL)
        - Daily realised PnL from the trade journal
        - Current risk zone from bot state
        - Consistency score
        - Active trading sessions

    Returns:
        Dict with timestamp, account, positions, daily_pnl, risk_zone,
        consistency_score, open_positions_count, and session_info.

    Note:
        If the broker provider is not connected, returns cached/last-known
        values with a ``provider_connected: false`` flag.
    """
    state = get_bot_state()

    # Default response skeleton
    data: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": "tick",
        "provider_connected": False,
        "provider_name": state.provider_name,
    }

    # --- Account info ---
    try:
        provider = get_provider()
        account = await provider.get_account_info()
        if account is not None:
            data["provider_connected"] = True
            data["account"] = {
                "balance": float(getattr(account, "balance", 0.0)),
                "equity": float(getattr(account, "equity", 0.0)),
                "margin": float(getattr(account, "margin", 0.0)),
                "free_margin": float(getattr(account, "free_margin", 0.0)),
                "margin_level": float(getattr(account, "margin_level", 0.0)),
                "currency": getattr(account, "currency", "USD"),
            }
        else:
            data["account"] = None
    except Exception as exc:
        logger.debug("WebSocket: account info unavailable: %s", exc)
        data["account"] = None

    # --- Positions ---
    positions_list: List[Dict[str, Any]] = []
    try:
        provider = get_provider()
        positions = await provider.get_positions()
        for pos in positions:
            positions_list.append({
                "ticket": getattr(pos, "ticket", 0),
                "symbol": getattr(pos, "symbol", ""),
                "direction": getattr(pos, "direction", ""),
                "volume": getattr(pos, "volume", 0.0),
                "open_price": getattr(pos, "open_price", 0.0),
                "current_price": getattr(pos, "current_price", 0.0),
                "sl": getattr(pos, "sl", 0.0),
                "tp": getattr(pos, "tp", 0.0),
                "profit": getattr(pos, "profit", 0.0),
                "open_time": (
                    pos.open_time.isoformat()
                    if getattr(pos, "open_time", None) is not None
                    else None
                ),
            })
        data["positions"] = positions_list
    except Exception as exc:
        logger.debug("WebSocket: positions unavailable: %s", exc)
        data["positions"] = []

    # --- Daily PnL (from trade journal) ---
    try:
        db = get_db()
        from datetime import date
        today = date.today()
        summary = db.get_daily_summary(today)
        data["daily_pnl"] = round(getattr(summary, "net_pnl", 0.0), 2)
        data["daily_trades"] = getattr(summary, "total_trades", 0)
        data["daily_wins"] = getattr(summary, "wins", 0)
        data["daily_losses"] = getattr(summary, "losses", 0)
    except Exception as exc:
        logger.debug("WebSocket: daily summary unavailable: %s", exc)
        data["daily_pnl"] = state.daily_pnl
        data["daily_trades"] = 0
        data["daily_wins"] = 0
        data["daily_losses"] = 0

    # --- Bot state / Risk ---
    data["risk_zone"] = state.current_zone
    data["is_trading"] = state.is_trading and not state.is_paused
    data["is_paused"] = state.is_paused
    data["phase"] = state.phase
    data["consistency_score"] = round(state.consistency_score, 2)
    data["max_drawdown"] = round(state.max_drawdown, 2)
    data["open_positions_count"] = len(positions_list)

    # --- Unrealised PnL from positions ---
    unrealised_pnl = sum(p.get("profit", 0.0) for p in positions_list)
    data["unrealised_pnl"] = round(unrealised_pnl, 2)

    # --- Active sessions ---
    try:
        from session.manager import SessionManager
        sm = SessionManager()
        active_sessions = sm.get_active_sessions()
        data["active_sessions"] = active_sessions
    except Exception:
        data["active_sessions"] = []

    return data


# --------------------------------------------------------------------------- #
# WebSocket Endpoint
# --------------------------------------------------------------------------- #


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time trading data streaming.

    Clients receive a JSON payload every 2 seconds containing:
        - timestamp: ISO timestamp of the tick
        - type: "tick"
        - provider_connected: bool
        - provider_name: str
        - account: balance, equity, margin, free_margin, margin_level
        - positions: list of open positions with unrealised PnL
        - daily_pnl: realised PnL for today
        - daily_trades/wins/losses: trade count breakdown
        - risk_zone: green/yellow/red
        - is_trading: bool
        - is_paused: bool
        - phase: evaluation/funded_early/funded_scaled
        - consistency_score: 0-100
        - max_drawdown: percentage
        - open_positions_count: int
        - unrealised_pnl: float
        - active_sessions: list of active session names

    Clients can also send commands:
        - ``{"action": "ping"}`` → receives ``{"type": "pong"}``
    """
    await manager.connect(websocket)

    # Send initial welcome message
    await manager.send_to(websocket, {
        "type": "connected",
        "message": "Welcome to Prop Firm Trading Bot WebSocket",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })

    try:
        while True:
            # Try to read any incoming message (non-blocking with timeout)
            try:
                message = await asyncio.wait_for(
                    websocket.receive_json(),
                    timeout=0.5,
                )
                # Handle client commands
                if isinstance(message, dict) and message.get("action") == "ping":
                    await manager.send_to(websocket, {
                        "type": "pong",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
            except asyncio.TimeoutError:
                pass  # No message from client, continue with broadcast

            # Gather and send live data
            try:
                data = await get_live_data()
                await websocket.send_json(data)
            except Exception as exc:
                logger.warning("WebSocket send error: %s", exc)
                break

            # Throttle to ~0.5 Hz (every 2 seconds)
            await asyncio.sleep(2)

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected cleanly")
    except Exception as exc:
        logger.warning("WebSocket error: %s", exc)
    finally:
        manager.disconnect(websocket)


__all__ = ["router", "manager", "get_live_data"]
