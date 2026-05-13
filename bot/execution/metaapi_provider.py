"""
MetaAPIProvider — TradingProvider adapter for MetaAPI.cloud.

Implements the ``TradingProvider`` interface by delegating to the MetaAPI
REST and WebSocket endpoints.  This allows the bot to trade through cloud
MT5/MT4 accounts without a local terminal.

Install the SDK::

    pip install metaapi-cloud-sdk
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from execution.mt5_bridge import AccountInfo, OrderResult, Position
from execution.provider import TradingProvider

logger = logging.getLogger(__name__)


class MetaAPIProvider(TradingProvider):
    """Async TradingProvider backed by MetaAPI.cloud.

    Communicates with MetaAPI's REST API for market data and account queries,
    and the RPC API for order execution.
    """

    def __init__(self, token: str, account_id: str) -> None:
        """Initialise the MetaAPI provider.

        Args:
            token: MetaAPI API access token.
            account_id: MetaAPI provisioning profile / account ID.
        """
        self._token = token
        self._account_id = account_id
        self._connected = False
        self._metaapi_account: Any = None
        self._rpc_api: Any = None

    # ------------------------------------------------------------------ #
    # TradingProvider interface
    # ------------------------------------------------------------------ #

    async def connect(self) -> bool:
        """Connect to MetaAPI and ensure the account is deployed.

        Returns:
            True if the connection and deployment were successful.
        """
        try:
            from metaapi_cloud_sdk import MetaApi
        except ImportError:
            logger.error(
                "metaapi-cloud-sdk is not installed. Run: pip install metaapi-cloud-sdk"
            )
            return False

        try:
            api = MetaApi(token=self._token)
            account = await api.metatrader_account_api.get_account(self._account_id)

            if account.state not in ("DEPLOYED", "DEPLOYING"):
                logger.info("Deploying MetaAPI account %s...", self._account_id)
                await account.deploy()

            # Wait for the account to be ready
            await account.wait_connected()

            self._metaapi_account = account
            self._rpc_api = account.get_rpc_connection()
            await self._rpc_api.connect()

            self._connected = True
            logger.info(
                "MetaAPI connected | account=%s server=%s",
                self._account_id,
                account.server_name,
            )
            return True

        except Exception:
            logger.exception("MetaAPI connection failed")
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Close the MetaAPI connection."""
        if self._rpc_api is not None:
            try:
                await self._rpc_api.close()
            except Exception:
                logger.exception("Error closing MetaAPI RPC connection")
        self._connected = False
        self._metaapi_account = None
        self._rpc_api = None
        logger.info("MetaAPI disconnected")

    @property
    def is_connected(self) -> bool:
        """Return whether the MetaAPI connection is active."""
        return self._connected

    async def get_account_info(self) -> Optional[AccountInfo]:
        """Retrieve current account information.

        Returns:
            AccountInfo snapshot or None if unavailable.
        """
        if self._rpc_api is None:
            return None
        try:
            info = await self._rpc_api.get_account_information()
            return AccountInfo(
                balance=info.get("balance", 0.0),
                equity=info.get("equity", 0.0),
                margin=info.get("margin", 0.0),
                free_margin=info.get("freeMargin", 0.0),
                margin_level=info.get("marginLevel", 0.0),
                leverage=info.get("leverage", 0),
                currency=info.get("currency", ""),
                server=info.get("server", ""),
                login=info.get("login", 0),
            )
        except Exception:
            logger.exception("Failed to fetch MetaAPI account info")
            return None

    async def place_market_order(
        self,
        symbol: str,
        direction: str,
        volume: float,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        comment: str = "",
    ) -> OrderResult:
        """Send a market order via MetaAPI.

        Args:
            symbol: Trading instrument.
            direction: 'buy' or 'sell'.
            volume: Lot size to trade.
            sl: Optional stop-loss price.
            tp: Optional take-profit price.
            comment: Order comment string.

        Returns:
            OrderResult with execution details.
        """
        if self._rpc_api is None:
            return OrderResult(success=False, comment="not connected")

        try:
            result = await self._rpc_api.trade(
                symbol=symbol,
                action_type=("ORDER_TYPE_BUY" if direction == "buy" else "ORDER_TYPE_SELL"),
                volume=float(volume),
                stop_loss=sl,
                take_profit=tp,
                comment=comment,
            )
            return OrderResult(
                success=True,
                ticket=result.get("orderId"),
                price=result.get("price"),
                volume=result.get("volume"),
                comment="executed",
            )
        except Exception as exc:
            logger.error("MetaAPI order failed: %s", exc)
            return OrderResult(success=False, comment=str(exc))

    async def close_position(self, ticket: int) -> OrderResult:
        """Close a single open position by ticket.

        Args:
            ticket: Position ticket number.

        Returns:
            OrderResult indicating success or failure.
        """
        if self._rpc_api is None:
            return OrderResult(success=False, comment="not connected")
        try:
            result = await self._rpc_api.close_position(ticket)
            return OrderResult(
                success=True,
                ticket=result.get("orderId"),
                price=result.get("price"),
                comment="closed",
            )
        except Exception as exc:
            logger.error("MetaAPI close_position failed for ticket %d: %s", ticket, exc)
            return OrderResult(success=False, comment=str(exc))

    async def close_all_positions(self, symbol: Optional[str] = None) -> List[OrderResult]:
        """Close all open positions via MetaAPI.

        Args:
            symbol: If provided, only close positions for this instrument.

        Returns:
            List of OrderResult for each close attempt.
        """
        positions = await self.get_positions(symbol=symbol)
        if not positions:
            logger.info("No open positions to close")
            return []

        results: List[OrderResult] = []
        for pos in positions:
            result = await self.close_position(pos.ticket)
            results.append(result)

        successes = sum(1 for r in results if r.success)
        logger.info("Closed %d/%d positions via MetaAPI", successes, len(results))
        return results

    async def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """Return a list of currently open positions.

        Args:
            symbol: Optional filter by instrument.

        Returns:
            List of Position instances.
        """
        if self._rpc_api is None:
            return []
        try:
            raw = await self._rpc_api.get_positions()
            if symbol:
                raw = [p for p in raw if p.get("symbol") == symbol]

            results: List[Position] = []
            for pos in raw:
                results.append(
                    Position(
                        ticket=pos.get("id", 0),
                        symbol=pos.get("symbol", ""),
                        direction=("buy" if pos.get("type") == "POSITION_TYPE_BUY" else "sell"),
                        volume=pos.get("volume", 0.0),
                        open_price=pos.get("openPrice", 0.0),
                        current_price=pos.get("currentPrice", 0.0),
                        sl=pos.get("stopLoss", 0.0),
                        tp=pos.get("takeProfit", 0.0),
                        swap=pos.get("swap", 0.0),
                        profit=pos.get("profit", 0.0),
                        open_time=datetime.now(timezone.utc),  # MetaAPI format varies — parse if available
                        magic=pos.get("magic", 0),
                    )
                )
            return results
        except Exception:
            logger.exception("Failed to retrieve MetaAPI positions")
            return []

    async def get_rates(
        self,
        symbol: str,
        timeframe: int,
        count: int,
    ) -> pd.DataFrame:
        """Retrieve OHLCV candlestick data via MetaAPI.

        Args:
            symbol: Trading instrument.
            timeframe: Timeframe in minutes (e.g. 15 for M15).
            count: Number of bars to retrieve.

        Returns:
            DataFrame with OHLCV data. Returns an empty DataFrame on failure.
        """
        if self._rpc_api is None:
            return pd.DataFrame()
        try:
            # Map minute timeframe to MetaAPI timeframe string
            tf_map = {
                1: "1m", 5: "5m", 15: "15m", 30: "30m",
                60: "1h", 240: "4h", 1440: "1d", 10080: "1w",
            }
            tf_str = tf_map.get(timeframe, "15m")
            candles = await self._rpc_api.get_candles(symbol, tf_str, count)
            if not candles:
                return pd.DataFrame()

            df = pd.DataFrame(candles)
            if "timestamp" in df.columns:
                df["time"] = pd.to_datetime(df["timestamp"], unit="ms")
                df.set_index("time", inplace=True)
            return df
        except Exception:
            logger.exception("Failed to retrieve MetaAPI rates for %s", symbol)
            return pd.DataFrame()

    async def modify_position(
        self,
        ticket: int,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
    ) -> OrderResult:
        """Modify SL/TP on an existing position via MetaAPI.

        Args:
            ticket: Position ticket number.
            sl: New stop-loss price (None to leave unchanged).
            tp: New take-profit price (None to leave unchanged).

        Returns:
            OrderResult indicating success or failure.
        """
        if self._rpc_api is None:
            return OrderResult(success=False, comment="not connected")
        try:
            result = await self._rpc_api.modify_position(
                position_id=ticket, stop_loss=sl, take_profit=tp
            )
            return OrderResult(
                success=True, ticket=result.get("orderId"), comment="modified"
            )
        except Exception as exc:
            logger.error("MetaAPI modify_position failed for ticket %d: %s", ticket, exc)
            return OrderResult(success=False, comment=str(exc))

    def get_provider_name(self) -> str:
        """Return a human-readable provider identifier.

        Returns:
            ``"MetaAPI Cloud"``
        """
        return "MetaAPI Cloud"
