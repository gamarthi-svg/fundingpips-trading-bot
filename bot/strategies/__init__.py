"""
Strategy Engine for the prop firm trading bot.

Sub-modules
-----------
base:
    Abstract base class (``Strategy``), ``Signal``, ``Direction``, and
    ``PartialTakeProfit`` definitions.
xauusd:
    XAU/USD dual-session strategy (Asian scalping + NY Opening Range
    Breakout).
nq_futures:
    NQ Futures Opening Range Breakout (Mon/Wed/Fri).
forex:
    London session breakout for EURUSD, GBPUSD, USDJPY.
registry:
    ``SignalRegistry`` that loads strategies based on ``BotPhase``.
"""

from strategies.base import (
    Direction,
    PartialTakeProfit,
    Signal,
    Strategy,
)
from strategies.forex import ForexStrategy
from strategies.nq_futures import NqFuturesStrategy
from strategies.registry import (
    BotPhase,
    SignalRegistry,
    SignalResult,
)
from strategies.xauusd import XauUsdStrategy

__all__ = [
    # base
    "Direction",
    "PartialTakeProfit",
    "Signal",
    "Strategy",
    # strategies
    "XauUsdStrategy",
    "NqFuturesStrategy",
    "ForexStrategy",
    # registry
    "BotPhase",
    "SignalRegistry",
    "SignalResult",
]
