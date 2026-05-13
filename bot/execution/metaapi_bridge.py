"""
MetaApiProvider — MetaAPI.cloud integration for the prop firm trading bot.

MetaAPI is a cloud service that connects to MT4/MT5 accounts without
installing a local terminal.  This provider implements the TradingProvider
interface using the ``metaapi-cloud-sdk`` package.

Key features:
- RPC-based trading (market orders, position management)
- Streaming connection for real-time market data
- Automatic reconnection with exponential back-off
- Full error handling for MetaAPI-specific exceptions
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from execution.provider import AccountInfo, OrderResult, Position, TradingProvider

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# MetaAPI SDK imports — guarded so the file can be imported without the SDK
# --------------------------------------------------------------------------- #

try:
    from metaapi_cloud_sdk import MetaApi
    from metaapi_cloud_sdk.metaApi.models import (
        date,
        datetime as meta_datetime,
    )

    METAAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    MetaApi = None  # type: ignore[misc, assignment]
    METAAPI_AVAILABLE = False
    logger.warning(
        "metaapi-cloud-sdk is not installed.  MetaApiProvider will not function.  "
        "Install it with: pip install metaapi-cloud-sdk>=21.0.0"
    )


# --------------------------------------------------------------------------- #
# Timeframe mapping: MT5 constants -> MetaAPI strings
# --------------------------------------------------------------------------- #

METAAPI_TIMEFRAMES: Dict[int, str] = {
    1: "1m",    # M1
    5: "5m",    # M5
    15: "15m",  # M15
    30: "30m",  # M30
    60: "1h",   # H1
    240: "4h",  # H4
    1440: "1d", # D1
    10080: "1w", # W1
    43200: "1M", # MN1
}

# Reverse mapping for convenience
METAAPI_TIMEFRAMES_REVERSE: Dict[str, int] = {v: k for k, v in METAAPI_TIMEFRAMES.items()}


# --------------------------------------------------------------------------- #
# Custom exceptions
# --------------------------------------------------------------------------- #

class MetaApiError(Exception):
    """Base exception for MetaAPI-specific errors."""

    def __init__(self, message: str, error_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.error_code = error_code


class MetaApiConnectionError(MetaApiError):
    """Raised when the MetaAPI connection fails."""
    pass


class MetaApiTradingError(MetaApiError):
    """Raised when a trading operation via MetaAPI fails."""
    pass


class MetaApiDataError(MetaApiError):
    """Raised when market data retrieval via MetaAPI fails."""
    pass


# --------------------------------------------------------------------------- #
# MetaApiProvider
# --------------------------------------------------------------------------- #

class MetaApiProvider(TradingProvider):
    """Cloud-based trading provider via MetaAPI.

    Connects to a broker's MT4/MT5 account through the MetaAPI cloud service,
    eliminating the need for a locally installed terminal.

    Usage::

        provider = MetaApiProvider(
            token="your_metaapi_token",
            account_id="your_account_id",
        )
        connected = await provider.connect()
        info = await provider.get_account_info()
    """

    def __init__(
        self,
        token: str,
        account_id: str,
        domain: str = "agiliumtrade.ai",
        reconnect_attempts: int = 3,
        reconnect_delay: float = 5.0,
    ) -> None:
        """Initialize the MetaAPI provider.

        Args:
            token: MetaAPI access token from https://app.metaapi.cloud/token.
            account_id: MetaAPI account ID (the UUID for your linked MT account).
            domain: MetaAPI region domain (default: agiliumtrade.ai).
            reconnect_attempts: Number of reconnection attempts on failure.
            reconnect_delay: Seconds to wait between reconnection attempts.
        """
        self._token = token
        self._account_id = account_id
        self._domain = domain
        self._reconnect_attempts = reconnect_attempts
        self._reconnect_delay = reconnect_delay

        self._api: Any = None
        self._account: Any = None
        self._connection: Any = None
        self._connected = False

        if not METAAPI_AVAILABLE:
            logger.error(
                "metaapi-cloud-sdk is not installed.  "
                "MetaApiProvider will not be able to connect."
            )

    # ------------------------------------------------------------------ #
    # Connection lifecycle
    # ------------------------------------------------------------------ #

    async def connect(self) -> bool:
        """Connect to MetaAPI and synchronise with the MT terminal.

        1. Creates the MetaApi client.
        2. Retrieves the linked account resource.
        3. Opens a streaming RPC connection.
        4. Waits until terminal state is synchronised.

        Returns:
            True if connected and synchronised, False otherwise.
        """
        if not METAAPI_AVAILABLE:
            logger.error("Cannot connect — metaapi-cloud-sdk is not installed")
            return False

        for attempt in range(1, self._reconnect_attempts + 1):
            try:
                logger.info(
                    "MetaAPI connecting (attempt %d/%d) | account=%s",
                    attempt,
                    self._reconnect_attempts,
                    self._account_id,
                )

                self._api = MetaApi(self._token, {"domain": self._domain})
                self._account = await self._api.metatrader_account_api.get_account(
                    self._account_id
                )

                if self._account is None:
                    raise MetaApiConnectionError(
                        f"Account {self._account_id} not found.  "
                        "Verify the account ID in the MetaAPI dashboard."
                    )

                logger.debug(
                    "MetaAPI account retrieved | login=%s server=%s state=%s",
                    getattr(self._account, "login", "?"),
                    getattr(self._account, "server", "?"),
                    getattr(self._account, "state", "?"),
                )

                self._connection = self._account.get_rpc_connection()
                await self._connection.connect()
                await self._connection.wait_synchronized()

                self._connected = True
                logger.info("MetaAPI connected and synchronised | account=%s", self._account_id)
                return True

            except Exception as exc:
                logger.warning(
                    "MetaAPI connection attempt %d failed: %s", attempt, exc
                )
                if attempt < self._reconnect_attempts:
                    await asyncio.sleep(self._reconnect_delay * attempt)
                else:
                    logger.error(
                        "MetaAPI connection failed after %d attempts", self._reconnect_attempts
                    )
                    self._connected = False
                    return False

        return False

    async def disconnect(self) -> None:
        """Close the MetaAPI connection and release resources."""
        try:
            if self._connection is not None:
                await self._connection.close()
        except Exception as exc:
            logger.warning("Error closing MetaAPI connection: %s", exc)
        finally:
            self._connection = None
            self._account = None
            self._api = None
            self._connected = False
            logger.info("MetaAPI disconnected")

    @property
    def is_connected(self) -> bool:
        """Return whether the MetaAPI connection is active and synchronised."""
        return self._connected and self._connection is not None

    # ------------------------------------------------------------------ #
    # Account info
    # ------------------------------------------------------------------ #

    async def get_account_info(self) -> Optional[AccountInfo]:
        """Retrieve current account information via MetaAPI.

        Returns:
            AccountInfo snapshot or None if unavailable.
        """
        if not self._ensure_connected():
            return None

        try:
            info = await self._connection.get_account_information()
            if info is None:
                logger.warning("MetaAPI get_account_information() returned None")
                return None

            return AccountInfo(
                balance=float(info.balance),
                equity=float(info.equity),
                margin=float(info.margin),
                free_margin=float(info.margin_free),
                margin_level=float(info.margin_level) if info.margin_level else 0.0,
                leverage=int(info.leverage),
                currency=str(info.currency),
                server=str(info.server),
                login=int(info.login),
            )
        except Exception as exc:
            logger.exception("MetaAPI failed to retrieve account info: %s", exc)
            return None

    # ------------------------------------------------------------------ #
    # Order placement
    # ------------------------------------------------------------------ #

    async def place_market_order(
        self,
        symbol: str,
        direction: str,
        volume: float,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        comment: str = "",
    ) -> OrderResult:
        """Send a market order via MetaAPI RPC.

        Args:
            symbol: Trading instrument (e.g. 'XAUUSD').
            direction: 'buy' or 'sell'.
            volume: Lot size to trade.
            sl: Optional stop-loss price.
            tp: Optional take-profit price.
            comment: Order comment string.

        Returns:
            OrderResult with execution details.
        """
        if not self._ensure_connected():
            return OrderResult(success=False, comment="not connected")

        if direction not in {"buy", "sell"}:
            logger.error("Invalid direction '%s'; must be 'buy' or 'sell'", direction)
            return OrderResult(success=False, comment="invalid direction")

        try:
            options: Dict[str, Any] = {}
            if comment:
                options["comment"] = comment

            if direction == "buy":
                result = await self._connection.create_market_buy_order(
                    symbol=symbol,
                    volume=float(volume),
                    stop_loss=sl,
                    take_profit=tp,
                    options=options if options else None,
                )
            else:
                result = await self._connection.create_market_sell_order(
                    symbol=symbol,
                    volume=float(volume),
                    stop_loss=sl,
                    take_profit=tp,
                    options=options if options else None,
                )

            if result is None:
                return OrderResult(success=False, comment="create_market_order returned None")

            logger.info(
                "Market order executed via MetaAPI | %s %s %.3f @ %.5f ticket=%s",
                symbol,
                direction,
                volume,
                getattr(result, "price", 0.0),
                getattr(result, "order_id", "?"),
            )

            return OrderResult(
                success=True,
                ticket=getattr(result, "order_id", None) or getattr(result, "ticket", None),
                price=getattr(result, "price", None),
                volume=getattr(result, "volume", None),
                comment="executed",
            )

        except Exception as exc:
            logger.exception(
                "MetaAPI market order failed | %s %s %.3f: %s",
                symbol,
                direction,
                volume,
                exc,
            )
            return OrderResult(
                success=False,
                comment=f"MetaAPI error: {exc}",
            )

    # ------------------------------------------------------------------ #
    # Position management
    # ------------------------------------------------------------------ #

    async def close_position(self, ticket: int) -> OrderResult:
        """Close a single open position by ticket via MetaAPI.

        Args:
            ticket: Position ticket number.

        Returns:
            OrderResult indicating success or failure.
        """
        if not self._ensure_connected():
            return OrderResult(success=False, comment="not connected")

        try:
            result = await self._connection.close_position(
                position_id=str(ticket),
            )

            logger.info("Position closed via MetaAPI | ticket=%d", ticket)
            return OrderResult(
                success=True,
                ticket=ticket,
                price=getattr(result, "price", None),
                comment="closed",
            )

        except Exception as exc:
            logger.exception(
                "MetaAPI close_position failed for ticket %d: %s", ticket, exc
            )
            return OrderResult(
                success=False,
                ticket=ticket,
                comment=f"close error: {exc}",
            )

    async def close_all_positions(self, symbol: Optional[str] = None) -> List[OrderResult]:
        """Close all open positions via MetaAPI.

        Args:
            symbol: If provided, only close positions for this instrument.

        Returns:
            List of OrderResult for each close attempt.
        """
        if not self._ensure_connected():
            return [OrderResult(success=False, comment="not connected")]

        positions = await self.get_positions(symbol=symbol)
        if not positions:
            logger.info("No open positions to close")
            return []

        results: List[OrderResult] = []
        for pos in positions:
            result = await self.close_position(pos.ticket)
            results.append(result)

        closed = sum(1 for r in results if r.success)
        logger.info(
            "MetaAPI closed %d/%d positions (%s)",
            closed,
            len(results),
            f"symbol={symbol}" if symbol else "all symbols",
        )
        return results

    async def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """Return a list of currently open positions via MetaAPI.

        Args:
            symbol: Optional filter by instrument.

        Returns:
            List of Position instances.
        """
        if not self._ensure_connected():
            return []

        try:
            raw_positions = await self._connection.get_positions()
            if raw_positions is None:
                return []

            result: List[Position] = []
            for pos in raw_positions:
                pos_symbol = getattr(pos, "symbol", "")

                # Filter by symbol if requested
                if symbol and pos_symbol != symbol:
                    continue

                direction = "buy" if getattr(pos, "type", "").lower() in ("buy", "order_type_buy") else "sell"

                # Parse open time
                open_time_raw = getattr(pos, "open_time", None)
                if isinstance(open_time_raw, datetime):
                    open_time = open_time_raw
                elif isinstance(open_time_raw, (int, float)):
                    open_time = datetime.fromtimestamp(open_time_raw)
                else:
                    open_time = datetime.utcnow()

                result.append(
                    Position(
                        ticket=int(getattr(pos, "id", getattr(pos, "ticket", 0))),
                        symbol=str(pos_symbol),
                        direction=direction,
                        volume=float(getattr(pos, "volume", 0.0)),
                        open_price=float(getattr(pos, "open_price", 0.0)),
                        current_price=float(getattr(pos, "current_price", getattr(pos, "price", 0.0))),
                        sl=float(getattr(pos, "stop_loss", 0.0) or 0.0),
                        tp=float(getattr(pos, "take_profit", 0.0) or 0.0),
                        swap=float(getattr(pos, "swap", 0.0) or 0.0),
                        profit=float(getattr(pos, "profit", 0.0) or 0.0),
                        open_time=open_time,
                        magic=int(getattr(pos, "magic", 0) or 0),
                    )
                )

            return result

        except Exception as exc:
            logger.exception("MetaAPI failed to retrieve positions: %s", exc)
            return []

    # ------------------------------------------------------------------ #
    # Market data
    # ------------------------------------------------------------------ #

    async def get_rates(
        self,
        symbol: str,
        timeframe: int,
        count: int,
    ) -> pd.DataFrame:
        """Retrieve OHLCV candlestick data via MetaAPI.

        Args:
            symbol: Trading instrument.
            timeframe: MT5 timeframe constant (e.g. 15 for M15).
            count: Number of bars to retrieve.

        Returns:
            DataFrame with columns [open, high, low, close, tick_volume]
            indexed by datetime.  Returns an empty DataFrame on failure.
        """
        if not self._ensure_connected():
            return pd.DataFrame()

        tf_str = METAAPI_TIMEFRAMES.get(timeframe)
        if tf_str is None:
            logger.error(
                "Unsupported timeframe %d for MetaAPI.  "
                "Supported: %s",
                timeframe,
                list(METAAPI_TIMEFRAMES.keys()),
            )
            return pd.DataFrame()

        try:
            candles = await self._connection.get_candles(
                symbol=symbol,
                timeframe=tf_str,
                offset=0,
                limit=count,
            )

            if candles is None or len(candles) == 0:
                logger.warning(
                    "MetaAPI get_candles returned empty for %s tf=%s count=%d",
                    symbol,
                    tf_str,
                    count,
                )
                return pd.DataFrame()

            records: List[Dict[str, Any]] = []
            for candle in candles:
                time_raw = getattr(candle, "time", getattr(candle, "timestamp", None))
                if isinstance(time_raw, datetime):
                    dt = time_raw
                elif isinstance(time_raw, (int, float)):
                    dt = datetime.fromtimestamp(time_raw)
                elif isinstance(time_raw, str):
                    dt = datetime.fromisoformat(time_raw.replace("Z", "+00:00"))
                else:
                    continue

                records.append({
                    "time": dt,
                    "open": float(getattr(candle, "open", 0.0)),
                    "high": float(getattr(candle, "high", 0.0)),
                    "low": float(getattr(candle, "low", 0.0)),
                    "close": float(getattr(candle, "close", 0.0)),
                    "volume": int(getattr(candle, "tick_volume", getattr(candle, "volume", 0))),
                })

            if not records:
                return pd.DataFrame()

            df = pd.DataFrame(records)
            df.set_index("time", inplace=True)
            df.sort_index(inplace=True)

            logger.debug(
                "MetaAPI retrieved %d bars for %s tf=%s", len(df), symbol, tf_str
            )
            return df

        except Exception as exc:
            logger.exception(
                "MetaAPI failed to retrieve candles for %s tf=%s: %s",
                symbol,
                tf_str,
                exc,
            )
            return pd.DataFrame()

    # ------------------------------------------------------------------ #
    # Position modification
    # ------------------------------------------------------------------ #

    async def modify_position(
        self,
        ticket: int,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
    ) -> OrderResult:
        """Modify stop-loss and/or take-profit on an existing position.

        Args:
            ticket: Position ticket number.
            sl: New stop-loss price (None to leave unchanged).
            tp: New take-profit price (None to leave unchanged).

        Returns:
            OrderResult indicating success or failure.
        """
        if not self._ensure_connected():
            return OrderResult(success=False, comment="not connected")

        if sl is None and tp is None:
            return OrderResult(success=False, comment="nothing to modify")

        try:
            result = await self._connection.modify_position(
                position_id=str(ticket),
                stop_loss=sl,
                take_profit=tp,
            )

            logger.info(
                "Position modified via MetaAPI | ticket=%d sl=%s tp=%s",
                ticket,
                sl,
                tp,
            )
            return OrderResult(
                success=True,
                ticket=ticket,
                comment=f"modified sl={sl} tp={tp}",
            )

        except Exception as exc:
            logger.exception(
                "MetaAPI modify_position failed for ticket %d: %s", ticket, exc
            )
            return OrderResult(
                success=False,
                ticket=ticket,
                comment=f"modify error: {exc}",
            )

    # ------------------------------------------------------------------ #
    # Streaming market data
    # ------------------------------------------------------------------ #

    async def subscribe_to_market_data(self, symbol: str) -> bool:
        """Subscribe to real-time price streaming for a symbol.

        This enables the streaming connection to push live price quotes
        for the given instrument, reducing latency for subsequent
        ``get_symbol_price`` calls.

        Args:
            symbol: Trading instrument to subscribe to (e.g. 'XAUUSD').

        Returns:
            True if subscription was successful.
        """
        if not self._ensure_connected():
            logger.warning("Cannot subscribe — not connected")
            return False

        try:
            # Use the underlying terminal state to subscribe to market data
            await self._connection.subscribe_to_market_data(symbol)
            logger.info("Subscribed to market data for %s", symbol)
            return True
        except Exception as exc:
            # MetaAPI streaming may require a separate streaming connection
            logger.warning(
                "Market data subscription for %s may need streaming connection: %s",
                symbol,
                exc,
            )
            return False

    async def get_symbol_price(self, symbol: str) -> Optional[Dict[str, float]]:
        """Get the current bid/ask for a symbol.

        Args:
            symbol: Trading instrument.

        Returns:
            Dict with 'bid' and 'ask' keys, or None on failure.
        """
        if not self._ensure_connected():
            return None

        try:
            price = await self._connection.get_symbol_price(symbol)
            if price is None:
                return None

            return {
                "bid": float(getattr(price, "bid", 0.0)),
                "ask": float(getattr(price, "ask", 0.0)),
                "timestamp": getattr(price, "time", None),
            }
        except Exception as exc:
            logger.exception(
                "MetaAPI failed to get price for %s: %s", symbol, exc
            )
            return None

    async def get_symbol_specification(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get trading specification for a symbol.

        Args:
            symbol: Trading instrument.

        Returns:
            Dict with symbol specs (digits, volume min/max, etc.).
        """
        if not self._ensure_connected():
            return None

        try:
            spec = await self._connection.get_symbol_specification(symbol)
            if spec is None:
                return None

            return {
                "symbol": str(getattr(spec, "symbol", symbol)),
                "digits": int(getattr(spec, "digits", 0)),
                "volume_min": float(getattr(spec, "volume_min", 0.0)),
                "volume_max": float(getattr(spec, "volume_max", 0.0)),
                "volume_step": float(getattr(spec, "volume_step", 0.0)),
                "contract_size": float(getattr(spec, "contract_size", 0.0)),
                "point": float(getattr(spec, "point", 0.0)),
            }
        except Exception as exc:
            logger.exception(
                "MetaAPI failed to get specification for %s: %s", symbol, exc
            )
            return None

    # ------------------------------------------------------------------ #
    # Provider identity
    # ------------------------------------------------------------------ #

    def get_provider_name(self) -> str:
        """Return the human-readable provider name."""
        return "MetaAPI Cloud"

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _ensure_connected(self) -> bool:
        """Check connection state and log a warning if disconnected.

        Returns:
            True if the RPC connection is ready.
        """
        if not self.is_connected:
            logger.warning("MetaAPI is not connected — call connect() first")
            return False
        return True
