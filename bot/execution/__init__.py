"""
Execution package — trading provider abstraction, MT5 bridge, MetaAPI bridge,
order management, and execution randomization.
"""

from execution.provider import AccountInfo, OrderResult, Position, TradingProvider
from execution.metaapi_bridge import (
    MetaApiConnectionError,
    MetaApiDataError,
    MetaApiError,
    MetaApiProvider,
    MetaApiTradingError,
    METAAPI_TIMEFRAMES,
)
from execution.mt5_bridge import MT5Bridge
from execution.factory import (
    ProviderConfigError,
    TradingProviderFactory,
)
from execution.order_manager import OrderDirection, OrderManager, Signal
from execution.randomizer import ExecutionRandomizer

__all__ = [
    # provider (shared dataclasses + abstract base)
    "AccountInfo",
    "OrderResult",
    "Position",
    "TradingProvider",
    # metaapi_bridge
    "MetaApiConnectionError",
    "MetaApiDataError",
    "MetaApiError",
    "MetaApiProvider",
    "MetaApiTradingError",
    "METAAPI_TIMEFRAMES",
    # mt5_bridge
    "MT5Bridge",
    # factory
    "ProviderConfigError",
    "TradingProviderFactory",
    # order_manager
    "OrderDirection",
    "OrderManager",
    "Signal",
    # randomizer
    "ExecutionRandomizer",
]
