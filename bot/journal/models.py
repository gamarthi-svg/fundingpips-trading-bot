"""
Data models for the prop firm trading bot journal system.

Defines dataclasses for trades, daily summaries, risk events,
performance metrics, and bot status.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import List, Optional


class TradeDirection(str, Enum):
    """Direction of a trade."""
    BUY = "BUY"
    SELL = "SELL"


class TradingSession(str, Enum):
    """Forex trading sessions."""
    ASIA = "Asia"
    LONDON = "London"
    NEW_YORK = "New_York"


class TradingPhase(str, Enum):
    """Phases of the trading day."""
    EVALUATION = "evaluation"
    PROFITABLE = "profitable"
    DRAWDOWN = "drawdown"


class RiskZone(str, Enum):
    """Risk zones indicating proximity to limits."""
    GREEN = "green"
    YELLOW = "yellow"
    ORANGE = "orange"
    RED = "red"


class RiskEventType(str, Enum):
    """Types of risk events that can occur."""
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    DRAWDOWN_WARNING = "drawdown_warning"
    MAX_DRAWDOWN_HIT = "max_drawdown_hit"
    CONSISTENCY_BREACH = "consistency_breach"
    TRADING_PAUSED = "trading_paused"
    TRADING_RESUMED = "trading_resumed"
    EMERGENCY_CLOSE = "emergency_close"


@dataclass
class Trade:
    """Represents a single trade execution.

    Attributes:
        id: Unique identifier for the trade record.
        ticket: Broker-provided ticket number.
        symbol: Trading instrument (e.g., 'EURUSD').
        direction: BUY or SELL.
        entry_price: Price at which the trade was opened.
        exit_price: Price at which the trade was closed.
        volume: Lot size of the trade.
        sl: Stop-loss price level.
        tp: Take-profit price level.
        open_time: UTC datetime when the trade was opened.
        close_time: UTC datetime when the trade was closed.
        profit: Monetary profit/loss of the trade.
        pips: Profit/loss in pips.
        strategy: Name of the strategy that generated the signal.
        session: Trading session (Asia, London, New_York).
        phase: Current trading phase when trade was taken.
        account_balance: Account balance before this trade.
        daily_pnl_before: Daily PnL before this trade was closed.
        zone: Risk zone classification at time of trade.
    """
    id: Optional[int] = None
    ticket: int = 0
    symbol: str = ""
    direction: str = ""
    entry_price: float = 0.0
    exit_price: float = 0.0
    volume: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    open_time: Optional[datetime] = None
    close_time: Optional[datetime] = None
    profit: float = 0.0
    pips: float = 0.0
    strategy: str = ""
    session: str = ""
    phase: str = ""
    account_balance: float = 0.0
    daily_pnl_before: float = 0.0
    zone: str = ""


@dataclass
class DailySummary:
    """Summary of trading activity for a single day.

    Attributes:
        date: The calendar date of the summary.
        total_trades: Total number of closed trades.
        wins: Number of winning trades.
        losses: Number of losing trades.
        gross_profit: Sum of all positive trade profits.
        gross_loss: Sum of all negative trade profits (absolute value).
        net_pnl: Net profit/loss for the day.
        max_dd: Maximum intraday drawdown percentage.
        consistency_score: Consistency metric for the day (0-100).
    """
    date: Optional[datetime] = None
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    net_pnl: float = 0.0
    max_dd: float = 0.0
    consistency_score: float = 0.0


@dataclass
class RiskEvent:
    """Records a risk management event.

    Attributes:
        id: Unique identifier for the event.
        timestamp: UTC datetime when the event occurred.
        event_type: Classification of the risk event.
        description: Human-readable description of the event.
        daily_pnl: Daily PnL at the time of the event.
        drawdown_pct: Current drawdown percentage.
        zone: Risk zone classification.
    """
    id: Optional[int] = None
    timestamp: Optional[datetime] = None
    event_type: str = ""
    description: str = ""
    daily_pnl: float = 0.0
    drawdown_pct: float = 0.0
    zone: str = ""


@dataclass
class PerformanceMetrics:
    """Aggregated performance metrics over a period.

    Attributes:
        total_return: Cumulative return percentage.
        win_rate: Percentage of winning trades (0-100).
        profit_factor: Gross profit divided by gross loss.
        sharpe_ratio: Risk-adjusted return metric.
        max_drawdown: Maximum peak-to-trough drawdown percentage.
    """
    total_return: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0


@dataclass
class BotStatus:
    """Current operational status of the trading bot.

    Attributes:
        phase: Current trading phase.
        zone: Current risk zone.
        is_trading: Whether the bot is actively trading.
        daily_pnl: Current day's net PnL.
        max_drawdown: Current maximum drawdown percentage.
        consistency_score: Running consistency score.
        open_positions: List of currently open position tickets.
    """
    phase: str = ""
    zone: str = ""
    is_trading: bool = False
    daily_pnl: float = 0.0
    max_drawdown: float = 0.0
    consistency_score: float = 0.0
    open_positions: List[int] = field(default_factory=list)


@dataclass
class AccountInfo:
    """Broker account information.

    Attributes:
        balance: Current account balance.
        equity: Current account equity.
        margin: Used margin.
        free_margin: Available margin for trading.
        margin_level: Margin level percentage.
        currency: Account deposit currency.
    """
    balance: float = 0.0
    equity: float = 0.0
    margin: float = 0.0
    free_margin: float = 0.0
    margin_level: float = 0.0
    currency: str = "USD"


@dataclass
class Position:
    """Represents an open trading position.

    Attributes:
        ticket: Broker-provided position ticket.
        symbol: Trading instrument.
        direction: BUY or SELL.
        volume: Position lot size.
        open_price: Entry price.
        current_price: Current market price.
        sl: Stop-loss level.
        tp: Take-profit level.
        swap: Accumulated swap charges.
        profit: Current unrealized profit/loss.
        open_time: UTC datetime when position was opened.
    """
    ticket: int = 0
    symbol: str = ""
    direction: str = ""
    volume: float = 0.0
    open_price: float = 0.0
    current_price: float = 0.0
    sl: float = 0.0
    tp: float = 0.0
    swap: float = 0.0
    profit: float = 0.0
    open_time: Optional[datetime] = None


__all__ = [
    "TradeDirection",
    "TradingSession",
    "TradingPhase",
    "RiskZone",
    "RiskEventType",
    "Trade",
    "DailySummary",
    "RiskEvent",
    "PerformanceMetrics",
    "BotStatus",
    "AccountInfo",
    "Position",
]
