"""
Abstract TradingProvider interface.

Defines the contract that all trading provider implementations must fulfil.
This abstraction allows the bot to switch between MT5 (local), MetaAPI (cloud),
and other future execution backends without changing strategy code.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Shared data models
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class AccountInfo:
    """Immutable snapshot of trading account information."""

    balance: float
    equity: float
    margin: float
    free_margin: float
    margin_level: float
    leverage: int
    currency: str
    server: str
    login: int


@dataclass(frozen=True)
class Position:
    """Immutable snapshot of an open position."""

    ticket: int
    symbol: str
    direction: str  # "buy" or "sell"
    volume: float
    open_price: float
    current_price: float
    sl: float
    tp: float
    swap: float
    profit: float
    open_time: datetime
    magic: int


@dataclass
class OrderResult:
    """Result of an order execution or position management attempt."""

    success: bool
    ticket: Optional[int] = None
    price: Optional[float] = None
    volume: Optional[float] = None
    comment: str = ""
    error_code: Optional[int] = None


# --------------------------------------------------------------------------- #
# Abstract provider
# --------------------------------------------------------------------------- #

class TradingProvider(ABC):
    """Abstract base class for all trading execution providers.

    Implementations must provide async methods for account operations,
    order management, position handling, and market data retrieval.
    """

    @abstractmethod
    async def connect(self) -> bool:
        """Establish a connection to the trading backend.

        Returns:
            True if the connection was successful, False otherwise.
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the connection and release resources."""
        ...

    @abstractmethod
    async def get_account_info(self) -> Optional[AccountInfo]:
        """Retrieve current account information.

        Returns:
            AccountInfo snapshot or None if unavailable.
        """
        ...

    @abstractmethod
    async def place_market_order(
        self,
        symbol: str,
        direction: str,
        volume: float,
        sl: Optional[float] = None,
        tp: Optional[float] = None,
        comment: str = "",
    ) -> OrderResult:
        """Send a market order to the trading backend.

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
        ...

    @abstractmethod
    async def close_position(self, ticket: int) -> OrderResult:
        """Close a single open position by ticket.

        Args:
            ticket: Position ticket number.

        Returns:
            OrderResult indicating success or failure.
        """
        ...

    @abstractmethod
    async def close_all_positions(self, symbol: Optional[str] = None) -> List[OrderResult]:
        """Close all open positions, optionally filtered by symbol.

        Args:
            symbol: If provided, only close positions for this instrument.

        Returns:
            List of OrderResult for each close attempt.
        """
        ...

    @abstractmethod
    async def get_positions(self, symbol: Optional[str] = None) -> List[Position]:
        """Return a list of currently open positions.

        Args:
            symbol: Optional filter by instrument.

        Returns:
            List of Position instances.
        """
        ...

    @abstractmethod
    async def get_rates(
        self,
        symbol: str,
        timeframe: int,
        count: int,
    ) -> pd.DataFrame:
        """Retrieve OHLCV candlestick data.

        Args:
            symbol: Trading instrument.
            timeframe: Timeframe constant (provider-specific).
            count: Number of bars to retrieve.

        Returns:
            DataFrame with columns [open, high, low, close, volume]
            indexed by datetime.  Returns an empty DataFrame on failure.
        """
        ...

    @abstractmethod
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
        ...

    @abstractmethod
    def get_provider_name(self) -> str:
        """Return a human-readable provider identifier.

        Returns:
            Short string such as 'MT5 Local' or 'MetaAPI Cloud'.
        """
        ...
