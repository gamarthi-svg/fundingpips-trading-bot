"""Risk management package for the prop-firm trading bot.

Provides kill-switch guards, position sizing, drawdown tracking,
and portfolio heat calculation — all tailored for FundingPips
2-step evaluation rules.
"""

from risk.manager import (
    GuardReport,
    KillSwitch,
    KillSwitchReport,
    NewsEvent,
    PositionExposure,
    RiskManager,
    RiskZone,
)
from risk.position_sizing import (
    ATRPositionSizer,
    PortfolioHeatCalculator,
    PositionHeat,
    SizingInput,
    SizingResult,
)
from risk.drawdown import (
    DailyDrawdown,
    DrawdownMode,
    DrawdownSnapshot,
    DrawdownTracker,
)

__all__ = [
    "ATRPositionSizer",
    "DailyDrawdown",
    "DrawdownMode",
    "DrawdownSnapshot",
    "DrawdownTracker",
    "GuardReport",
    "KillSwitch",
    "KillSwitchReport",
    "NewsEvent",
    "PortfolioHeatCalculator",
    "PositionExposure",
    "PositionHeat",
    "RiskManager",
    "RiskZone",
    "SizingInput",
    "SizingResult",
]
