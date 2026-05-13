"""
Base strategy module for the prop firm trading bot.

Defines the abstract base class ``Strategy``, the ``Signal`` dataclass,
``Direction`` enum, and ``PartialTakeProfit`` dataclass used across all
strategy implementations.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


class Direction(Enum):
    """Trade direction."""

    LONG = "long"
    SHORT = "short"


@dataclass
class PartialTakeProfit:
    """Partial take-profit level with percentage of position to close."""

    ratio: float
    """Risk-multiple for this partial (e.g. 1.5 means 1.5× risk)."""
    percent: float
    """Percent of position to close at this level (0.0-1.0)."""

    def __post_init__(self) -> None:
        if not 0.0 <= self.percent <= 1.0:
            raise ValueError(f"percent must be in [0.0, 1.0], got {self.percent}")
        if self.ratio <= 0.0:
            raise ValueError(f"ratio must be positive, got {self.ratio}")


@dataclass
class Signal:
    """Trading signal emitted by a strategy."""

    direction: Direction
    entry_price: float
    stop_loss: float
    take_profits: List[PartialTakeProfit]
    confidence: float
    symbol: str
    timestamp: datetime
    strategy_name: str = ""
    """Set by the registry after generation."""

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got {self.confidence}"
            )
        if self.entry_price <= 0.0:
            raise ValueError(f"entry_price must be positive, got {self.entry_price}")
        if self.stop_loss <= 0.0:
            raise ValueError(f"stop_loss must be positive, got {self.stop_loss}")
        if not self.take_profits:
            raise ValueError("take_profits must contain at least one level")

    @property
    def risk_pips(self) -> float:
        """Return the absolute distance from entry to stop-loss in price terms."""
        return abs(self.entry_price - self.stop_loss)

    @property
    def is_long(self) -> bool:
        """True if this is a long signal."""
        return self.direction == Direction.LONG

    @property
    def is_short(self) -> bool:
        """True if this is a short signal."""
        return self.direction == Direction.SHORT


class Strategy(ABC):
    """Abstract base class for all trading strategies."""

    def __init__(self, name: str, symbol: str) -> None:
        self.name = name
        self.symbol = symbol
        logger.info("Initialised strategy %s for %s", name, symbol)

    @abstractmethod
    def generate_signal(self, data: pd.DataFrame) -> Optional[Signal]:
        """
        Analyse *data* and return a ``Signal`` when entry criteria are met,
        otherwise ``None``.

        Parameters
        ----------
        data:
            OHLCV DataFrame with a DatetimeIndex.  Must contain the columns
            ``open``, ``high``, ``low``, ``close``, and ``volume``.

        Returns
        -------
        Signal or None
        """
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r}, symbol={self.symbol!r})"
