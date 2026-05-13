"""
MT5Provider — TradingProvider adapter for the local MetaTrader 5 terminal.

Wraps the existing synchronous ``MT5Bridge`` and exposes the async
``TradingProvider`` interface by running blocking calls in an executor.
"""

from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

import MetaTrader5 as mt5
import pandas as pd

from execution.mt5_bridge import AccountInfo, MT5Bridge, OrderResult, Position
from execution.provider import TradingProvider

logger = logging.getLogger(__name__)


class MT5Provider(TradingProvider):
    """Async TradingProvider backed by the local MT5 terminal.

    Delegates all trading operations to an internal ``MT5Bridge`` instance,
    running blocking MT5 API calls in the default thread pool so they do not
    block the asyncio event loop.
    """

    def __init__(self, login: int, password: str, server: str) -> None:
        """Initialise the MT5 provider with account credentials.

        Args:
            login: MT5 account login number.
            password: MT5 account password.
            server: MT5 broker server name.
        """
        self._bridge = MT5Bridge(login=login, password=password, server=server)
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # ------------------------------------------------------------------ #
    # Internal helper
    # ------------------------------------------------------------------ #

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        """Return the running event loop (cached)."""
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        return self._loop

    def _run_in_executor(self, func, *args):
        """Run a blocking function in the thread pool."""
        loop = self._get_loop()
        return loop.run_in_executor(None, func, *args)

    # ------------------------------------------------------------------ #
    # TradingProvider interface
    # ------------------------------------------------------------------ #

    async def connect(self) -> bool:
        """Connect to the MT5 terminal.

        Returns:
            True if connection was successful.
        """
        result = await self._run_in_executor(self._bridge.connect)
        return result

    async def disconnect(self) -> None:
        """Shutdown the MT5 connection."""
        await self._run_in_executor(self._bridge.disconnect)

    @property
    def is_connected(self) -> bool:
        """Return whether the MT5 terminal is connected."""
        return self._bridge.is_connected

    async def get_account_info(self) -> Optional[AccountInfo]:
        """Retrieve current account information.

        Returns:
            AccountInfo snapshot or None if unavailable.
        """
        return await self._run_in_executor(self._bridge.get_account_info)

    async def place_market_order(
        self,
        symbol: str,
        direction: str,
        volume: float,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        comment: str = "",
    ) -> OrderResult:
        """Send a market order.

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
        return await self._run_in_executor(
            self._bridge.place_market_order,
            symbol,
            direction,
            volume,
            sl,
            tp,
            0,  # magic
            comment,
        )

    async def close_position(self, ticket: int) -> OrderResult:
        """Close a single open position by ticket.

        Args:
            ticket: Position ticket number.

        Returns:
            OrderResult indicating success or failure.
        """
        return await self._run_in_executor(self._bridge.close_position, ticket)

    async def close_all_positions(self, symbol: Optional[str] = None) -> List[OrderResult]:
        """Close all open positions, optionally filtered by symbol.

        Args:
            symbol: If provided, only close positions for this instrument.

        Returns:
            List of OrderResult for each close attempt.
        """
        return await self._run_in_executor(self._bridge.close_all_positions, symbol)

    async def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """Return a list of currently open positions.

        Args:
            symbol: Optional filter by instrument.

        Returns:
            List of Position instances.
        """
        return await self._run_in_executor(self._bridge.get_positions, symbol)

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
            DataFrame with OHLCV data. Returns an empty DataFrame on failure.
        """
        return await self._run_in_executor(
            self._bridge.get_rates, symbol, timeframe, count
        )

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

        Raises:
            NotImplementedError: MT5Bridge does not currently support position modification.
        """
        raise NotImplementedError("Position modification not yet implemented for MT5 provider")

    def get_provider_name(self) -> str:
        """Return a human-readable provider identifier.

        Returns:
            ``"MT5 Local"``
        """
        return "MT5 Local"
