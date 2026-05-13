"""
MT5Bridge — MetaTrader 5 connection and trading interface.

Handles all direct interactions with the MetaTrader 5 terminal including
account queries, order execution, position management, and market data retrieval.

This refactored version implements the TradingProvider interface so it can be
used interchangeably with the MetaAPI cloud provider.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import MetaTrader5 as mt5
import pandas as pd

from execution.provider import AccountInfo, OrderResult, Position, TradingProvider

logger = logging.getLogger(__name__)


class MT5Bridge(TradingProvider):
    """Bridge to the MetaTrader 5 trading terminal.

    Encapsulates all MT5 API calls and provides a clean Pythonic interface
    for connecting, querying account info, placing orders, managing positions,
    and retrieving OHLCV market data.
    """

    def __init__(
        self,
        login: int,
        password: str,
        server: str,
    ) -> None:
        """Initialize the MT5 bridge with account credentials.

        Args:
            login: MT5 account login number.
            password: MT5 account password.
            server: MT5 broker server name.
        """
        self._login = login
        self._password = password
        self._server = server
        self._connected = False

    # ------------------------------------------------------------------ #
    # Connection lifecycle
    # ------------------------------------------------------------------ #

    async def connect(self) -> bool:
        """Initialize MT5 and log in to the trading account.

        Returns:
            True if connection was successful, False otherwise.
        """
        try:
            # MT5 initialization is blocking; run in a thread pool
            loop = asyncio.get_event_loop()
            initialized = await loop.run_in_executor(None, mt5.initialize)
            if not initialized:
                err = mt5.last_error()
                logger.error("MT5 initialize() failed: %s", err)
                return False

            authorized = await loop.run_in_executor(
                None,
                lambda: mt5.login(
                    login=self._login,
                    password=self._password,
                    server=self._server,
                ),
            )
            if not authorized:
                err = mt5.last_error()
                logger.error("MT5 login failed: %s", err)
                await loop.run_in_executor(None, mt5.shutdown)
                return False

            self._connected = True
            account = mt5.account_info()
            if account is not None:
                logger.info(
                    "MT5 connected | Login=%d Server=%s Balance=%.2f %s",
                    account.login,
                    account.server,
                    account.balance,
                    account.currency,
                )
            return True

        except Exception:
            logger.exception("Unexpected error during MT5 connection")
            return False

    async def disconnect(self) -> None:
        """Shutdown the MT5 connection."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, mt5.shutdown)
        self._connected = False
        logger.info("MT5 disconnected")

    @property
    def is_connected(self) -> bool:
        """Return whether the MT5 terminal is connected."""
        return self._connected and mt5.terminal_info() is not None

    # ------------------------------------------------------------------ #
    # Account info
    # ------------------------------------------------------------------ #

    async def get_account_info(self) -> Optional[AccountInfo]:
        """Retrieve current account information.

        Returns:
            AccountInfo dataclass or None if unavailable.
        """
        try:
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, mt5.account_info)
            if info is None:
                logger.warning("mt5.account_info() returned None")
                return None
            return AccountInfo(
                balance=info.balance,
                equity=info.equity,
                margin=info.margin,
                free_margin=info.margin_free,
                margin_level=info.margin_level,
                leverage=info.leverage,
                currency=info.currency,
                server=info.server,
                login=info.login,
            )
        except Exception:
            logger.exception("Failed to retrieve account info")
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
        """Send a market order to the MT5 terminal.

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
        if direction not in {"buy", "sell"}:
            logger.error("Invalid direction '%s'; must be 'buy' or 'sell'", direction)
            return OrderResult(success=False, comment="invalid direction")

        order_type = mt5.ORDER_TYPE_BUY if direction == "buy" else mt5.ORDER_TYPE_SELL

        request: Dict[str, Any] = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": order_type,
            "deviation": 10,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        if sl is not None:
            request["sl"] = float(sl)
        if tp is not None:
            request["tp"] = float(tp)

        try:
            # Retrieve current price for the order
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                err = mt5.last_error()
                logger.error("No tick data for %s: %s", symbol, err)
                return OrderResult(success=False, comment=f"no tick data: {err}")

            price = tick.ask if direction == "buy" else tick.bid
            request["price"] = price

            result = mt5.order_send(request)

            if result is None:
                err = mt5.last_error()
                logger.error("order_send returned None: %s", err)
                return OrderResult(success=False, comment=f"order_send None: {err}")

            if result.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(
                    "Market order executed | %s %s %.3f @ %.5f ticket=%d",
                    symbol,
                    direction,
                    volume,
                    result.price,
                    result.order,
                )
                return OrderResult(
                    success=True,
                    ticket=result.order,
                    price=result.price,
                    volume=result.volume,
                    comment="executed",
                )

            logger.error(
                "Market order failed | retcode=%d %s %s %.3f",
                result.retcode,
                symbol,
                direction,
                volume,
            )
            return OrderResult(
                success=False,
                error_code=result.retcode,
                comment=f"retcode {result.retcode}",
            )

        except Exception:
            logger.exception("mt5.order_send threw an exception")
            return OrderResult(success=False, comment="order_send exception")

    # ------------------------------------------------------------------ #
    # Position management
    # ------------------------------------------------------------------ #

    async def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """Return a list of currently open positions.

        Args:
            symbol: Optional filter by instrument.

        Returns:
            List of Position dataclass instances.
        """
        try:
            positions = (
                mt5.positions_get(symbol=symbol)
                if symbol
                else mt5.positions_get()
            )
            if positions is None:
                return []

            result: List[Position] = []
            for pos in positions:
                direction = (
                    "buy" if pos.type == mt5.ORDER_TYPE_BUY else "sell"
                )
                result.append(
                    Position(
                        ticket=pos.ticket,
                        symbol=pos.symbol,
                        direction=direction,
                        volume=pos.volume,
                        open_price=pos.price_open,
                        current_price=pos.price_current,
                        sl=pos.sl,
                        tp=pos.tp,
                        swap=pos.swap,
                        profit=pos.profit,
                        open_time=datetime.fromtimestamp(pos.time),
                        magic=pos.magic,
                    )
                )
            return result
        except Exception:
            logger.exception("Failed to retrieve positions")
            return []

    async def close_position(self, ticket: int) -> OrderResult:
        """Close a single open position by ticket.

        Args:
            ticket: Position ticket number.

        Returns:
            OrderResult indicating success or failure.
        """
        try:
            positions = mt5.positions_get(ticket=ticket)
            if not positions:
                logger.warning("No position found for ticket %d", ticket)
                return OrderResult(success=False, comment="position not found")

            pos = positions[0]
            opposite = (
                mt5.ORDER_TYPE_SELL
                if pos.type == mt5.ORDER_TYPE_BUY
                else mt5.ORDER_TYPE_BUY
            )

            tick = mt5.symbol_info_tick(pos.symbol)
            if tick is None:
                err = mt5.last_error()
                logger.error("No tick for %s when closing: %s", pos.symbol, err)
                return OrderResult(success=False, comment=f"no tick: {err}")

            price = tick.bid if opposite == mt5.ORDER_TYPE_SELL else tick.ask

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": pos.ticket,
                "symbol": pos.symbol,
                "volume": pos.volume,
                "type": opposite,
                "price": price,
                "deviation": 10,
                "magic": pos.magic,
                "comment": "close position",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

            result = mt5.order_send(request)
            if result is None:
                err = mt5.last_error()
                logger.error("close_position order_send None: %s", err)
                return OrderResult(success=False, comment=f"order_send None: {err}")

            if result.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info("Position closed | ticket=%d @ %.5f", ticket, result.price)
                return OrderResult(
                    success=True,
                    ticket=result.order,
                    price=result.price,
                    comment="closed",
                )

            logger.error(
                "Failed to close position %d | retcode=%d", ticket, result.retcode
            )
            return OrderResult(
                success=False,
                error_code=result.retcode,
                comment=f"retcode {result.retcode}",
            )

        except Exception:
            logger.exception("Exception while closing position %d", ticket)
            return OrderResult(success=False, comment="exception during close")

    async def close_all_positions(
        self, symbol: Optional[str] = None
    ) -> List[OrderResult]:
        """Close all open positions, optionally filtered by symbol.

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
        logger.info(
            "Closed %d/%d positions",
            sum(1 for r in results if r.success),
            len(results),
        )
        return results

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
        try:
            positions = mt5.positions_get(ticket=ticket)
            if not positions:
                logger.warning("No position found for ticket %d", ticket)
                return OrderResult(success=False, comment="position not found")

            pos = positions[0]

            request = {
                "action": mt5.TRADE_ACTION_SLTP,
                "position": pos.ticket,
                "symbol": pos.symbol,
                "sl": sl if sl is not None else pos.sl,
                "tp": tp if tp is not None else pos.tp,
            }

            result = mt5.order_send(request)
            if result is None:
                err = mt5.last_error()
                logger.error("modify_position order_send None: %s", err)
                return OrderResult(success=False, comment=f"order_send None: {err}")

            if result.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(
                    "Position modified | ticket=%d sl=%s tp=%s",
                    ticket,
                    sl,
                    tp,
                )
                return OrderResult(
                    success=True,
                    ticket=ticket,
                    comment=f"modified sl={sl} tp={tp}",
                )

            logger.error(
                "Failed to modify position %d | retcode=%d", ticket, result.retcode
            )
            return OrderResult(
                success=False,
                error_code=result.retcode,
                comment=f"retcode {result.retcode}",
            )

        except Exception:
            logger.exception("Exception while modifying position %d", ticket)
            return OrderResult(success=False, comment="exception during modify")

    # ------------------------------------------------------------------ #
    # Market data
    # ------------------------------------------------------------------ #

    async def get_rates(
        self,
        symbol: str,
        timeframe: int,
        count: int,
    ) -> pd.DataFrame:
        """Retrieve OHLCV candlestick data from MT5.

        Args:
            symbol: Trading instrument.
            timeframe: MT5 timeframe constant (e.g. mt5.TIMEFRAME_M15).
            count: Number of bars to retrieve.

        Returns:
            DataFrame with columns [open, high, low, close, tick_volume]
            indexed by datetime.  Returns an empty DataFrame on failure.
        """
        try:
            rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
            if rates is None or len(rates) == 0:
                err = mt5.last_error()
                logger.error(
                    "copy_rates_from_pos returned empty for %s tf=%s count=%d: %s",
                    symbol,
                    timeframe,
                    count,
                    err,
                )
                return pd.DataFrame()

            df = pd.DataFrame(rates)
            df["time"] = pd.to_datetime(df["time"], unit="s")
            df.set_index("time", inplace=True)
            df = df.rename(
                columns={
                    "tick_volume": "volume",
                    "real_volume": "real_volume",
                    "spread": "spread",
                }
            )

            # Ensure standard columns exist
            for col in ["open", "high", "low", "close", "volume"]:
                if col not in df.columns:
                    df[col] = 0.0

            logger.debug(
                "Retrieved %d bars for %s tf=%s", len(df), symbol, timeframe
            )
            return df[["open", "high", "low", "close", "volume"]]

        except Exception:
            logger.exception(
                "Exception retrieving rates for %s tf=%s", symbol, timeframe
            )
            return pd.DataFrame()

    # ------------------------------------------------------------------ #
    # Provider identity
    # ------------------------------------------------------------------ #

    def get_provider_name(self) -> str:
        """Return the human-readable provider name."""
        return "MT5 Local"

    # ------------------------------------------------------------------ #
    # Symbol info helpers (sync — convenience methods)
    # ------------------------------------------------------------------ #

    def get_spread(self, symbol: str) -> Optional[float]:
        """Return the current spread for a symbol in points.

        Args:
            symbol: Trading instrument.

        Returns:
            Spread as float or None if unavailable.
        """
        try:
            tick = mt5.symbol_info_tick(symbol)
            if tick is None:
                return None
            info = mt5.symbol_info(symbol)
            if info is None:
                return None
            return float(tick.ask - tick.bid) / info.point
        except Exception:
            logger.exception("Failed to get spread for %s", symbol)
            return None

    def get_point_value(self, symbol: str) -> Optional[float]:
        """Return the point (pipette) value for a symbol.

        Args:
            symbol: Trading instrument.

        Returns:
            Point size or None if unavailable.
        """
        try:
            info = mt5.symbol_info(symbol)
            if info is None:
                return None
            return float(info.point)
        except Exception:
            logger.exception("Failed to get point for %s", symbol)
            return None
