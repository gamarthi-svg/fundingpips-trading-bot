#!/usr/bin/env python3
"""
Production-Grade Risk Management System for Prop Firm Trading Bot.

This module implements a comprehensive risk management framework designed
for proprietary trading firm evaluations. It includes:

    - Five-tier circuit breaker system for drawdown protection
    - Half-Kelly criterion position sizing with safety bounds
    - Portfolio heat tracking (Alexander Elder's 6% rule)
    - Prop firm consistency score tracking
    - Drawdown-based position reduction
    - Firm-specific rule enforcement (FundingPips, FTMO, The5%ers, FundedNext)
    - Pre-trade safety checks with correlation analysis

All components are thread-safe for async usage and persist state to SQLite.

Example::

    from risk.risk_manager_v2 import RiskManager

    risk = RiskManager(account_size=10000, prop_firm='fundingpips', phase='phase1')
    can_trade, reason = risk.pre_trade_check(
        symbol='XAUUSD', direction='buy',
        stop_distance=2.5, strategy='xau_asian'
    )
    if can_trade:
        lots = risk.calculate_position_size(
            stop_distance=2.5, symbol='XAUUSD'
        )

Author: Quantitative Risk Engineering Team
Version: 2.0.0
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

# ---------------------------------------------------------------------------
# Enums & Constants
# ---------------------------------------------------------------------------


class CircuitLevel(Enum):
    """Circuit breaker severity levels."""

    NORMAL = 0
    LEVEL_1 = 1  # DD > 50% of limit  -> reduce risk to 50%
    LEVEL_2 = 2  # DD > 60% of limit  -> reduce risk to 25%
    LEVEL_3 = 3  # DD > 70% of limit  -> reduce risk to 10%
    LEVEL_4 = 4  # DD > 80% of limit  -> STOP all new trades
    LEVEL_5 = 5  # DD > 90% of limit  -> EMERGENCY close all positions


class PropFirm(Enum):
    """Supported proprietary trading firms."""

    FUNDINGPIPS = "fundingpips"
    THE5PERS = "the5pers"
    FTMO = "ftmo"
    FUNDEDNEXT = "fundednext"


class Phase(Enum):
    """Evaluation phases for prop firm challenges."""

    PHASE1 = "phase1"
    PHASE2 = "phase2"
    FUNDED = "funded"


class TradeDirection(Enum):
    """Trade direction."""

    BUY = "buy"
    SELL = "sell"


class HeatZone(Enum):
    """Portfolio heat zones based on Alexander Elder's 6% rule."""

    NORMAL = "normal"      # heat < 4%
    CAUTION = "caution"    # 4% - 5.5%
    DANGER = "danger"      # 5.5% - 6%
    MAX = "max"            # > 6%


class ConsistencyStatus(Enum):
    """Consistency rule compliance status."""

    COMPLIANT = "compliant"
    WARNING = "warning"
    VIOLATION = "violation"


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_TRADES_FOR_KELLY: int = 30
MAX_RISK_PER_TRADE_PCT: float = 0.02  # 2% max
MIN_LOTS: float = 0.01
DEFAULT_RISK_PCT_FALLBACK: float = 0.005  # 0.5% fallback
KELLY_FRACTION: float = 0.5  # Half-Kelly

DD_REDUCTION_BANDS: List[Tuple[float, float, float]] = [
    (0.0, 0.20, 1.00),   # DD 0-20%  -> 100% size
    (0.20, 0.40, 0.75),  # DD 20-40% -> 75% size
    (0.40, 0.60, 0.50),  # DD 40-60% -> 50% size
    (0.60, 0.80, 0.25),  # DD 60-80% -> 25% size
    (0.80, 1.00, 0.10),  # DD 80%+   -> 10% size
]

CIRCUIT_THRESHOLDS: List[Tuple[float, CircuitLevel]] = [
    (0.50, CircuitLevel.LEVEL_1),
    (0.60, CircuitLevel.LEVEL_2),
    (0.70, CircuitLevel.LEVEL_3),
    (0.80, CircuitLevel.LEVEL_4),
    (0.90, CircuitLevel.LEVEL_5),
]

CONSISTENCY_WARNING_THRESHOLD: float = 0.30
CONSISTENCY_VIOLATION_THRESHOLD: float = 0.35

PIPS_PER_LOT: Dict[str, float] = {
    "XAUUSD": 100.0,   # $100 per pip per lot for gold
    "XAGUSD": 50.0,    # $50 per pip per lot for silver
    "default": 10.0,   # $10 per pip per lot for forex
}

WEEKEND_HOLDING_BLOCKED_PAIRS: List[str] = [
    "XAUUSD", "XAGUSD", "USOIL", "BRENT", "NATGAS"
]

MAX_POSITIONS_PER_STRATEGY: int = 2

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class TradeRecord:
    """Represents a single completed trade for performance tracking."""

    trade_id: str
    symbol: str
    direction: str
    entry_time: datetime
    exit_time: Optional[datetime] = None
    pnl: float = 0.0
    lots: float = 0.0
    strategy: str = ""
    day_key: str = field(init=False)

    def __post_init__(self) -> None:
        self.day_key = self.entry_time.strftime("%Y-%m-%d")


@dataclass
class Position:
    """Represents an open position."""

    position_id: str
    symbol: str
    direction: str
    open_time: datetime
    lots: float
    entry_price: float
    stop_loss: float
    take_profit: float
    strategy: str
    risk_amount: float = 0.0

    @property
    def current_risk(self) -> float:
        """Return the risk amount (stop distance * lots * pip_value)."""
        return self.risk_amount


@dataclass
class CircuitState:
    """Current state of the circuit breaker system."""

    level: CircuitLevel = CircuitLevel.NORMAL
    drawdown_pct: float = 0.0
    reduction_factor: float = 1.0
    emergency_close: bool = False
    last_updated: float = field(default_factory=time.time)


@dataclass
class SafetyCheckResult:
    """Result of a pre-trade safety check."""

    is_safe: bool
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Database Manager (SQLite persistence)
# ---------------------------------------------------------------------------


class RiskDatabase:
    """Thread-safe SQLite persistence layer for risk state tracking.

    Attributes:
        db_path: Path to the SQLite database file.
        _lock: Threading lock for concurrent access.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        if db_path is None:
            db_path = os.path.join(
                os.path.dirname(__file__), "risk_state.db"
            )
        self.db_path: str = db_path
        self._lock: threading.Lock = threading.Lock()
        self._local = threading.local()
        self._ensure_tables()

    def _connection(self) -> sqlite3.Connection:
        """Get a thread-local SQLite connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                self.db_path, check_same_thread=False, timeout=30
            )
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _ensure_tables(self) -> None:
        """Create required tables if they do not exist."""
        with self._lock:
            conn = self._connection()
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS trade_history (
                    trade_id    TEXT PRIMARY KEY,
                    symbol      TEXT NOT NULL,
                    direction   TEXT NOT NULL,
                    entry_time  TEXT NOT NULL,
                    exit_time   TEXT,
                    pnl         REAL DEFAULT 0.0,
                    lots        REAL DEFAULT 0.0,
                    strategy    TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS open_positions (
                    position_id TEXT PRIMARY KEY,
                    symbol      TEXT NOT NULL,
                    direction   TEXT NOT NULL,
                    open_time   TEXT NOT NULL,
                    lots        REAL DEFAULT 0.0,
                    entry_price REAL DEFAULT 0.0,
                    stop_loss   REAL DEFAULT 0.0,
                    take_profit REAL DEFAULT 0.0,
                    strategy    TEXT DEFAULT '',
                    risk_amount REAL DEFAULT 0.0
                );

                CREATE TABLE IF NOT EXISTS daily_pnl (
                    day_key     TEXT PRIMARY KEY,
                    total_pnl   REAL DEFAULT 0.0,
                    trade_count INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS circuit_state (
                    id          INTEGER PRIMARY KEY CHECK (id = 1),
                    level       INTEGER DEFAULT 0,
                    drawdown_pct REAL DEFAULT 0.0,
                    reduction_factor REAL DEFAULT 1.0,
                    emergency_close INTEGER DEFAULT 0,
                    last_updated REAL
                );

                CREATE TABLE IF NOT EXISTS account_snapshots (
                    snapshot_time TEXT PRIMARY KEY,
                    balance       REAL DEFAULT 0.0,
                    equity        REAL DEFAULT 0.0,
                    peak_balance  REAL DEFAULT 0.0
                );

                INSERT OR IGNORE INTO circuit_state (id) VALUES (1);
                """
            )
            conn.commit()
            logger.debug("Risk database tables ensured at %s", self.db_path)

    # --- Trade history ---

    def add_trade(self, trade: TradeRecord) -> None:
        """Persist a completed trade to the database."""
        with self._lock:
            conn = self._connection()
            conn.execute(
                """
                INSERT OR REPLACE INTO trade_history
                (trade_id, symbol, direction, entry_time, exit_time, pnl, lots, strategy)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade.trade_id, trade.symbol, trade.direction,
                    trade.entry_time.isoformat(),
                    trade.exit_time.isoformat() if trade.exit_time else None,
                    trade.pnl, trade.lots, trade.strategy,
                ),
            )
            # Update daily PnL aggregation
            conn.execute(
                """
                INSERT INTO daily_pnl (day_key, total_pnl, trade_count)
                VALUES (?, ?, 1)
                ON CONFLICT(day_key) DO UPDATE SET
                    total_pnl = total_pnl + excluded.total_pnl,
                    trade_count = trade_count + 1
                """,
                (trade.day_key, trade.pnl),
            )
            conn.commit()

    def get_trade_history(
        self, strategy: Optional[str] = None, limit: int = 1000
    ) -> List[TradeRecord]:
        """Retrieve trade history, optionally filtered by strategy."""
        with self._lock:
            conn = self._connection()
            params: Tuple[Any, ...]
            if strategy:
                rows = conn.execute(
                    """SELECT * FROM trade_history WHERE strategy = ?
                       ORDER BY entry_time DESC LIMIT ?""",
                    (strategy, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT * FROM trade_history
                       ORDER BY entry_time DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
            return [self._row_to_trade(r) for r in rows]

    @staticmethod
    def _row_to_trade(row: sqlite3.Row) -> TradeRecord:
        """Convert a database row to a TradeRecord."""
        return TradeRecord(
            trade_id=row["trade_id"],
            symbol=row["symbol"],
            direction=row["direction"],
            entry_time=datetime.fromisoformat(row["entry_time"]),
            exit_time=datetime.fromisoformat(row["exit_time"])
            if row["exit_time"] else None,
            pnl=row["pnl"],
            lots=row["lots"],
            strategy=row["strategy"],
        )

    # --- Open positions ---

    def add_open_position(self, pos: Position) -> None:
        """Persist a new open position."""
        with self._lock:
            conn = self._connection()
            conn.execute(
                """
                INSERT OR REPLACE INTO open_positions
                (position_id, symbol, direction, open_time, lots,
                 entry_price, stop_loss, take_profit, strategy, risk_amount)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pos.position_id, pos.symbol, pos.direction,
                    pos.open_time.isoformat(), pos.lots, pos.entry_price,
                    pos.stop_loss, pos.take_profit, pos.strategy, pos.risk_amount,
                ),
            )
            conn.commit()

    def remove_open_position(self, position_id: str) -> None:
        """Remove a closed position from the open positions table."""
        with self._lock:
            conn = self._connection()
            conn.execute(
                "DELETE FROM open_positions WHERE position_id = ?",
                (position_id,),
            )
            conn.commit()

    def get_open_positions(
        self, strategy: Optional[str] = None
    ) -> List[Position]:
        """Retrieve all open positions, optionally filtered by strategy."""
        with self._lock:
            conn = self._connection()
            if strategy:
                rows = conn.execute(
                    "SELECT * FROM open_positions WHERE strategy = ?",
                    (strategy,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM open_positions").fetchall()
            return [self._row_to_position(r) for r in rows]

    @staticmethod
    def _row_to_position(row: sqlite3.Row) -> Position:
        """Convert a database row to a Position."""
        return Position(
            position_id=row["position_id"],
            symbol=row["symbol"],
            direction=row["direction"],
            open_time=datetime.fromisoformat(row["open_time"]),
            lots=row["lots"],
            entry_price=row["entry_price"],
            stop_loss=row["stop_loss"],
            take_profit=row["take_profit"],
            strategy=row["strategy"],
            risk_amount=row["risk_amount"],
        )

    # --- Daily PnL ---

    def get_daily_pnl(self) -> Dict[str, float]:
        """Return a mapping of day_key -> total PnL."""
        with self._lock:
            conn = self._connection()
            rows = conn.execute("SELECT * FROM daily_pnl").fetchall()
            return {r["day_key"]: r["total_pnl"] for r in rows}

    # --- Circuit state ---

    def save_circuit_state(self, state: CircuitState) -> None:
        """Persist the current circuit breaker state."""
        with self._lock:
            conn = self._connection()
            conn.execute(
                """
                UPDATE circuit_state SET
                    level = ?,
                    drawdown_pct = ?,
                    reduction_factor = ?,
                    emergency_close = ?,
                    last_updated = ?
                WHERE id = 1
                """,
                (
                    state.level.value,
                    state.drawdown_pct,
                    state.reduction_factor,
                    1 if state.emergency_close else 0,
                    time.time(),
                ),
            )
            conn.commit()

    def load_circuit_state(self) -> CircuitState:
        """Load the circuit breaker state from the database."""
        with self._lock:
            conn = self._connection()
            row = conn.execute(
                "SELECT * FROM circuit_state WHERE id = 1"
            ).fetchone()
            if row is None:
                return CircuitState()
            return CircuitState(
                level=CircuitLevel(row["level"]),
                drawdown_pct=row["drawdown_pct"],
                reduction_factor=row["reduction_factor"],
                emergency_close=bool(row["emergency_close"]),
                last_updated=row["last_updated"],
            )

    # --- Account snapshots ---

    def save_account_snapshot(
        self, balance: float, equity: float, peak_balance: float
    ) -> None:
        """Persist an account balance snapshot."""
        with self._lock:
            conn = self._connection()
            conn.execute(
                """
                INSERT OR REPLACE INTO account_snapshots
                (snapshot_time, balance, equity, peak_balance)
                VALUES (?, ?, ?, ?)
                """,
                (datetime.now(timezone.utc).isoformat(), balance, equity, peak_balance),
            )
            conn.commit()

    def get_latest_account_snapshot(self) -> Optional[Dict[str, float]]:
        """Return the most recent account snapshot."""
        with self._lock:
            conn = self._connection()
            row = conn.execute(
                """SELECT * FROM account_snapshots
                   ORDER BY snapshot_time DESC LIMIT 1"""
            ).fetchone()
            if row is None:
                return None
            return {
                "balance": row["balance"],
                "equity": row["equity"],
                "peak_balance": row["peak_balance"],
            }


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------


class CircuitBreaker:
    """Five-tier circuit breaker for drawdown protection.

    Evaluates the ratio of current drawdown to the firm's maximum allowed
    drawdown limit and triggers escalating protective actions:

        - Level 1 (DD > 50% of limit): Reduce new position risk to 50%
        - Level 2 (DD > 60% of limit): Reduce new position risk to 25%
        - Level 3 (DD > 70% of limit): Reduce new position risk to 10%
        - Level 4 (DD > 80% of limit): Block ALL new trades
        - Level 5 (DD > 90% of limit): Emergency close all open positions

    The breaker state is persisted to SQLite and recovered on restart.
    """

    def __init__(self, db: RiskDatabase) -> None:
        self._db = db
        self._lock = threading.RLock()
        self._state: CircuitState = db.load_circuit_state()
        logger.info(
            "CircuitBreaker initialised at level %s", self._state.level.name
        )

    def evaluate(
        self, current_drawdown: float, max_drawdown_limit: float
    ) -> CircuitState:
        """Evaluate the circuit breaker given current drawdown.

        Args:
            current_drawdown: Current drawdown in account currency.
            max_drawdown_limit: Maximum allowed drawdown (e.g. 10% of account).

        Returns:
            Updated CircuitState with the active level and reduction factor.

        Raises:
            ValueError: If *max_drawdown_limit* is not positive.
        """
        if max_drawdown_limit <= 0:
            raise ValueError("max_drawdown_limit must be positive")

        with self._lock:
            dd_ratio = current_drawdown / max_drawdown_limit
            dd_ratio = max(0.0, min(1.0, dd_ratio))

            new_level = CircuitLevel.NORMAL
            reduction = 1.0
            emergency = False

            for threshold, level in CIRCUIT_THRESHOLDS:
                if dd_ratio >= threshold:
                    new_level = level
                    if level == CircuitLevel.LEVEL_1:
                        reduction = 0.50
                    elif level == CircuitLevel.LEVEL_2:
                        reduction = 0.25
                    elif level == CircuitLevel.LEVEL_3:
                        reduction = 0.10
                    elif level == CircuitLevel.LEVEL_4:
                        reduction = 0.0
                    elif level == CircuitLevel.LEVEL_5:
                        reduction = 0.0
                        emergency = True
                else:
                    break

            self._state = CircuitState(
                level=new_level,
                drawdown_pct=dd_ratio * 100.0,
                reduction_factor=reduction,
                emergency_close=emergency,
            )
            self._db.save_circuit_state(self._state)

            if new_level != CircuitLevel.NORMAL:
                logger.warning(
                    "Circuit breaker at %s (DD=%.2f%% of limit, reduction=%.0f%%)",
                    new_level.name, dd_ratio * 100, reduction * 100,
                )
            return self._state

    @property
    def state(self) -> CircuitState:
        """Return the current circuit breaker state (read-only copy)."""
        with self._lock:
            return CircuitState(
                level=self._state.level,
                drawdown_pct=self._state.drawdown_pct,
                reduction_factor=self._state.reduction_factor,
                emergency_close=self._state.emergency_close,
            )

    def can_open_new_trades(self) -> bool:
        """Return True if new trades are permitted."""
        with self._lock:
            return self._state.level.value < CircuitLevel.LEVEL_4.value

    def emergency_close_required(self) -> bool:
        """Return True if all positions must be closed immediately."""
        with self._lock:
            return self._state.emergency_close

    def reset(self) -> None:
        """Manually reset the circuit breaker to NORMAL."""
        with self._lock:
            self._state = CircuitState()
            self._db.save_circuit_state(self._state)
            logger.info("Circuit breaker manually reset to NORMAL")


# ---------------------------------------------------------------------------
# Kelly Criterion Position Sizing
# ---------------------------------------------------------------------------


class KellySizing:
    """Half-Kelly position sizing with safety bounds.

    The Kelly criterion computes the optimal fraction of capital to risk:

        f = (p * b - q) / b

    where:
        - p = win rate (probability of winning)
        - q = 1 - p  (probability of losing)
        - b = average win / average loss (payoff ratio)

    To avoid the excessive volatility of full Kelly, this implementation
    uses **Half-Kelly** (f/2) and clamps the result between a minimum lot
    size and a maximum risk per trade (2% of account).

    If fewer than ``MIN_TRADES_FOR_KELLY`` (30) historical trades exist,
    the system falls back to a fixed 0.5% risk per trade.
    """

    def __init__(self, db: RiskDatabase) -> None:
        self._db = db
        self._lock = threading.RLock()
        self._cached_kelly_fraction: Optional[float] = None
        self._cache_timestamp: float = 0.0
        self._cache_ttl: float = 300.0  # 5-minute cache
        logger.info("KellySizing initialised")

    def _needs_refresh(self) -> bool:
        """Return True if the Kelly cache has expired."""
        return (self._cached_kelly_fraction is None
                or time.time() - self._cache_timestamp > self._cache_ttl)

    def _compute_kelly_fraction(self, trades: List[TradeRecord]) -> Optional[float]:
        """Compute the Kelly fraction from a list of completed trades.

        Args:
            trades: List of TradeRecord objects.

        Returns:
            The Half-Kelly fraction (0..1), or *None* if insufficient data.
        """
        if len(trades) < MIN_TRADES_FOR_KELLY:
            return None

        wins: List[float] = [t.pnl for t in trades if t.pnl > 0]
        losses: List[float] = [abs(t.pnl) for t in trades if t.pnl < 0]

        if not wins or not losses:
            return None

        p = len(wins) / len(trades)
        q = 1.0 - p
        avg_win = sum(wins) / len(wins)
        avg_loss = sum(losses) / len(losses)

        if avg_loss == 0:
            return None

        b = avg_win / avg_loss
        raw_kelly = (p * b - q) / b if b != 0 else 0.0

        # Clamp to sensible bounds
        raw_kelly = max(0.0, min(1.0, raw_kelly))
        half_kelly = raw_kelly * KELLY_FRACTION
        logger.debug(
            "Kelly calc: p=%.3f, b=%.3f, raw=%.4f, half=%.4f (n=%d trades)",
            p, b, raw_kelly, half_kelly, len(trades),
        )
        return half_kelly

    def calculate_size(
        self,
        account_balance: float,
        stop_distance_pips: float,
        symbol: str = "XAUUSD",
        strategy: Optional[str] = None,
    ) -> float:
        """Calculate the position size in lots.

        Args:
            account_balance: Current account balance in account currency.
            stop_distance_pips: Distance to stop-loss in pips/points.
            symbol: Trading instrument (affects pip value).
            strategy: Optional strategy name for trade-history filtering.

        Returns:
            Position size in standard lots.

        Raises:
            ValueError: If inputs are invalid (non-positive).
        """
        if account_balance <= 0:
            raise ValueError("account_balance must be positive")
        if stop_distance_pips <= 0:
            raise ValueError("stop_distance_pips must be positive")

        with self._lock:
            pip_value = PIPS_PER_LOT.get(symbol, PIPS_PER_LOT["default"])

            if self._needs_refresh():
                trades = self._db.get_trade_history(strategy=strategy)
                self._cached_kelly_fraction = self._compute_kelly_fraction(trades)
                self._cache_timestamp = time.time()

            kelly = self._cached_kelly_fraction

            if kelly is None:
                # Fallback: fixed 0.5% risk per trade
                risk_amount = account_balance * DEFAULT_RISK_PCT_FALLBACK
                lots = risk_amount / (stop_distance_pips * pip_value)
                logger.debug(
                    "Kelly fallback to %.2f%% risk: %.2f lots",
                    DEFAULT_RISK_PCT_FALLBACK * 100, lots,
                )
            else:
                # Kelly-based sizing: kelly * balance, capped at max risk
                kelly_risk_amount = kelly * account_balance
                max_risk_amount = account_balance * MAX_RISK_PER_TRADE_PCT
                risk_amount = min(kelly_risk_amount, max_risk_amount)
                lots = risk_amount / (stop_distance_pips * pip_value)
                logger.debug(
                    "Kelly size: kelly=%.4f, risk=$%.2f, lots=%.2f",
                    kelly, risk_amount, lots,
                )

            # Clamp to min/max lots
            lots = max(MIN_LOTS, lots)
            return round(lots, 2)

    def get_kelly_stats(self, strategy: Optional[str] = None) -> Dict[str, Any]:
        """Return diagnostic statistics for the Kelly calculation.

        Returns:
            Dictionary with win rate, payoff ratio, Kelly fraction,
            trade count, and fallback status.
        """
        with self._lock:
            trades = self._db.get_trade_history(strategy=strategy)
            kelly = self._compute_kelly_fraction(trades)

            if kelly is None:
                return {
                    "status": "fallback",
                    "fallback_risk_pct": DEFAULT_RISK_PCT_FALLBACK * 100,
                    "trade_count": len(trades),
                    "min_required": MIN_TRADES_FOR_KELLY,
                }

            wins = [t.pnl for t in trades if t.pnl > 0]
            losses = [abs(t.pnl) for t in trades if t.pnl < 0]
            p = len(wins) / len(trades) if trades else 0.0
            avg_win = sum(wins) / len(wins) if wins else 0.0
            avg_loss = sum(losses) / len(losses) if losses else 0.0
            b = avg_win / avg_loss if avg_loss > 0 else 0.0

            return {
                "status": "kelly",
                "win_rate": round(p, 4),
                "payoff_ratio": round(b, 4),
                "half_kelly_fraction": round(kelly, 4),
                "trade_count": len(trades),
                "avg_win": round(avg_win, 2),
                "avg_loss": round(avg_loss, 2),
            }


# ---------------------------------------------------------------------------
# Portfolio Heat Tracker
# ---------------------------------------------------------------------------


class PortfolioHeat:
    """Track total open risk across all strategies.

    Implements **Alexander Elder's 6% rule**:

        - Normal  (heat < 4%):   Full position sizing allowed.
        - Caution (4% - 5.5%):  Reduce new positions by 50%.
        - Danger  (5.5% - 6%):  Reduce new positions by 75%.
        - Max     (> 6%):       NO new positions allowed.

    "Heat" is defined as the total risk amount of all open positions
    divided by the account balance, expressed as a percentage.
    """

    def __init__(self, db: RiskDatabase) -> None:
        self._db = db
        self._lock = threading.RLock()
        logger.info("PortfolioHeat initialised")

    def _current_heat(self, account_balance: float) -> float:
        """Compute current portfolio heat as a fraction (not percentage).

        Args:
            account_balance: Current account balance.

        Returns:
            Heat as a decimal (0.0 - 1.0+).
        """
        if account_balance <= 0:
            return 1.0  # Maximum heat if no valid balance
        positions = self._db.get_open_positions()
        total_risk = sum(p.risk_amount for p in positions)
        return total_risk / account_balance

    def get_zone(self, account_balance: float) -> HeatZone:
        """Determine the current heat zone.

        Args:
            account_balance: Current account balance.

        Returns:
            The active :class:`HeatZone`.
        """
        heat = self._current_heat(account_balance)
        if heat < 0.04:
            return HeatZone.NORMAL
        elif heat < 0.055:
            return HeatZone.CAUTION
        elif heat <= 0.06:
            return HeatZone.DANGER
        else:
            return HeatZone.MAX

    def reduction_factor(self, account_balance: float) -> float:
        """Return the position-size reduction factor based on heat zone.

        Args:
            account_balance: Current account balance.

        Returns:
            Multiplier for new position sizes (1.0 = full size).
        """
        zone = self.get_zone(account_balance)
        mapping = {
            HeatZone.NORMAL: 1.00,
            HeatZone.CAUTION: 0.50,
            HeatZone.DANGER: 0.25,
            HeatZone.MAX: 0.00,
        }
        return mapping[zone]

    def can_add_position(self, account_balance: float) -> bool:
        """Return True if new positions are permitted."""
        return self.get_zone(account_balance) != HeatZone.MAX

    def get_heat_report(self, account_balance: float) -> Dict[str, Any]:
        """Return a diagnostic report of current portfolio heat.

        Returns:
            Dictionary with heat percentage, zone, reduction factor,
            open position count, and total risk amount.
        """
        heat = self._current_heat(account_balance)
        positions = self._db.get_open_positions()
        total_risk = sum(p.risk_amount for p in positions)
        return {
            "heat_pct": round(heat * 100, 2),
            "zone": self.get_zone(account_balance).value,
            "reduction_factor": self.reduction_factor(account_balance),
            "open_positions": len(positions),
            "total_risk": round(total_risk, 2),
            "account_balance": round(account_balance, 2),
        }


# ---------------------------------------------------------------------------
# Consistency Score Calculator
# ---------------------------------------------------------------------------


class ConsistencyTracker:
    """Track prop firm consistency rule compliance.

    Most prop firms require that **no single trading day contributes
    more than 30-35% of total profits**.  This class computes:

        Score = max_single_day_profit / total_profits

    If the score exceeds the violation threshold (> 0.35), the trader
    is in violation and payout may be blocked.
    """

    def __init__(self, db: RiskDatabase) -> None:
        self._db = db
        self._lock = threading.RLock()
        logger.info("ConsistencyTracker initialised")

    def calculate_score(self) -> Tuple[float, ConsistencyStatus]:
        """Calculate the consistency score and status.

        Returns:
            Tuple of (score, status).  Score is 0.0 if no profitable days.
            Status is one of :class:`ConsistencyStatus`.
        """
        with self._lock:
            daily_pnl = self._db.get_daily_pnl()
            profitable_days = {
                d: pnl for d, pnl in daily_pnl.items() if pnl > 0
            }

            if not profitable_days:
                return 0.0, ConsistencyStatus.COMPLIANT

            total_profits = sum(profitable_days.values())
            if total_profits <= 0:
                return 0.0, ConsistencyStatus.COMPLIANT

            max_day_profit = max(profitable_days.values())
            score = max_day_profit / total_profits

            if score > CONSISTENCY_VIOLATION_THRESHOLD:
                status = ConsistencyStatus.VIOLATION
            elif score > CONSISTENCY_WARNING_THRESHOLD:
                status = ConsistencyStatus.WARNING
            else:
                status = ConsistencyStatus.COMPLIANT

            logger.debug(
                "Consistency score=%.3f, status=%s (max_day=%.2f, total=%.2f)",
                score, status.value, max_day_profit, total_profits,
            )
            return score, status

    def is_compliant(self) -> bool:
        """Return True if the consistency rule is NOT violated."""
        _, status = self.calculate_score()
        return status != ConsistencyStatus.VIOLATION

    def get_report(self) -> Dict[str, Any]:
        """Return a detailed consistency report.

        Returns:
            Dictionary with score, status, total profits, max day profit,
            and number of profitable trading days.
        """
        score, status = self.calculate_score()
        daily_pnl = self._db.get_daily_pnl()
        profitable_days = {d: pnl for d, pnl in daily_pnl.items() if pnl > 0}
        return {
            "score": round(score, 4),
            "status": status.value,
            "threshold_warning": CONSISTENCY_WARNING_THRESHOLD,
            "threshold_violation": CONSISTENCY_VIOLATION_THRESHOLD,
            "total_profits": round(sum(profitable_days.values()), 2),
            "max_day_profit": round(max(profitable_days.values()), 2)
            if profitable_days else 0.0,
            "profitable_days": len(profitable_days),
        }


# ---------------------------------------------------------------------------
# Drawdown-Based Position Reduction
# ---------------------------------------------------------------------------


class DrawdownReducer:
    """Reduce position sizes progressively as drawdown increases.

    The reduction follows fixed bands relative to the maximum allowed
    drawdown limit:

        +------------+------------+
        | DD Range   | Size       |
        +------------+------------+
        | 0%  - 20%  | 100%       |
        | 20% - 40%  | 75%        |
        | 40% - 60%  | 50%        |
        | 60% - 80%  | 25%        |
        | 80%+       | 10%        |
        +------------+------------+

    This operates independently from the circuit breaker and serves as
    a smooth, continuous position-size governor.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        logger.info("DrawdownReducer initialised")

    def reduction_factor(
        self, current_drawdown: float, max_drawdown_limit: float
    ) -> float:
        """Return the position-size multiplier based on drawdown band.

        Args:
            current_drawdown: Current drawdown amount.
            max_drawdown_limit: Maximum allowed drawdown limit.

        Returns:
            A multiplier in the range [0.1, 1.0].

        Raises:
            ValueError: If *max_drawdown_limit* is not positive.
        """
        if max_drawdown_limit <= 0:
            raise ValueError("max_drawdown_limit must be positive")

        with self._lock:
            dd_ratio = current_drawdown / max_drawdown_limit
            dd_ratio = max(0.0, min(1.0, dd_ratio))

            for low, high, factor in DD_REDUCTION_BANDS:
                if low <= dd_ratio <= high:
                    logger.debug(
                        "DD reducer: ratio=%.3f -> band %.0f%%-%.0f%% -> %.0f%% size",
                        dd_ratio, low * 100, high * 100, factor * 100,
                    )
                    return factor

            # Fallback (should not reach here due to clamping)
            return 0.10

    def get_band(self, current_drawdown: float, max_drawdown_limit: float) -> str:
        """Return a human-readable description of the current drawdown band."""
        factor = self.reduction_factor(current_drawdown, max_drawdown_limit)
        band_map = {
            1.00: "0-20% DD (100% size)",
            0.75: "20-40% DD (75% size)",
            0.50: "40-60% DD (50% size)",
            0.25: "60-80% DD (25% size)",
            0.10: "80%+ DD (10% size)",
        }
        return band_map.get(factor, "unknown band")


# ---------------------------------------------------------------------------
# Prop Firm Rule Engine
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FirmRules:
    """Immutable container for prop-firm-specific risk rules.

    Attributes:
        firm_name: Human-readable firm name.
        daily_dd_pct: Daily drawdown limit as a percentage (e.g. 5.0).
        max_dd_pct: Maximum / overall drawdown limit as a percentage.
        consistency_threshold: Maximum single-day profit contribution (0.35).
        phase: Current evaluation phase (phase1, phase2, funded).
        profit_target_pct: Profit target for the current phase (optional).
        max_positions_per_strategy: Maximum concurrent positions per strategy.
        weekend_holding: Whether weekend holding is permitted.
        news_trading_allowed: Whether trading during news events is allowed.
    """

    firm_name: str
    daily_dd_pct: float
    max_dd_pct: float
    consistency_threshold: float = CONSISTENCY_VIOLATION_THRESHOLD
    phase: str = "phase1"
    profit_target_pct: Optional[float] = None
    max_positions_per_strategy: int = MAX_POSITIONS_PER_STRATEGY
    weekend_holding: bool = False
    news_trading_allowed: bool = False


class PropFirmRules:
    """Store and enforce prop-firm-specific trading rules.

    Supported firms:
        - **FundingPips**:  consistency rule, daily_dd=5%, max_dd=10%
        - **The5%ers**:     3-step, daily_dd=3%, max_dd=6% (phases 1-2), 5% (funded)
        - **FTMO**:         challenge_dd=5%, verification_dd=5%, funded_dd=5%
        - **FundedNext**:   daily_dd=5%, max_dd=10%
    """

    _RULES: Dict[Tuple[str, str], FirmRules] = {
        # FundingPips
        ("fundingpips", "phase1"): FirmRules(
            firm_name="FundingPips Phase 1",
            daily_dd_pct=5.0,
            max_dd_pct=10.0,
            profit_target_pct=8.0,
        ),
        ("fundingpips", "phase2"): FirmRules(
            firm_name="FundingPips Phase 2",
            daily_dd_pct=5.0,
            max_dd_pct=10.0,
            profit_target_pct=5.0,
        ),
        ("fundingpips", "funded"): FirmRules(
            firm_name="FundingPips Funded",
            daily_dd_pct=5.0,
            max_dd_pct=10.0,
            profit_target_pct=None,
        ),
        # The5%ers
        ("the5pers", "phase1"): FirmRules(
            firm_name="The5%ers Phase 1",
            daily_dd_pct=3.0,
            max_dd_pct=6.0,
            profit_target_pct=6.0,
        ),
        ("the5pers", "phase2"): FirmRules(
            firm_name="The5%ers Phase 2",
            daily_dd_pct=3.0,
            max_dd_pct=6.0,
            profit_target_pct=4.0,
        ),
        ("the5pers", "funded"): FirmRules(
            firm_name="The5%ers Funded",
            daily_dd_pct=3.0,
            max_dd_pct=5.0,
            profit_target_pct=None,
        ),
        # FTMO
        ("ftmo", "phase1"): FirmRules(
            firm_name="FTMO Challenge",
            daily_dd_pct=5.0,
            max_dd_pct=10.0,
            profit_target_pct=10.0,
        ),
        ("ftmo", "phase2"): FirmRules(
            firm_name="FTMO Verification",
            daily_dd_pct=5.0,
            max_dd_pct=10.0,
            profit_target_pct=5.0,
        ),
        ("ftmo", "funded"): FirmRules(
            firm_name="FTMO Funded",
            daily_dd_pct=5.0,
            max_dd_pct=10.0,
            profit_target_pct=None,
        ),
        # FundedNext
        ("fundednext", "phase1"): FirmRules(
            firm_name="FundedNext Phase 1",
            daily_dd_pct=5.0,
            max_dd_pct=10.0,
            profit_target_pct=10.0,
        ),
        ("fundednext", "phase2"): FirmRules(
            firm_name="FundedNext Phase 2",
            daily_dd_pct=5.0,
            max_dd_pct=10.0,
            profit_target_pct=5.0,
        ),
        ("fundednext", "funded"): FirmRules(
            firm_name="FundedNext Funded",
            daily_dd_pct=5.0,
            max_dd_pct=10.0,
            profit_target_pct=None,
        ),
    }

    @classmethod
    def get_rules(
        cls, firm: Union[str, PropFirm], phase: Union[str, Phase] = "phase1"
    ) -> FirmRules:
        """Retrieve the rules for a given firm and phase.

        Args:
            firm: Prop firm identifier (string or :class:`PropFirm` enum).
            phase: Evaluation phase (string or :class:`Phase` enum).

        Returns:
            A :class:`FirmRules` dataclass with the configured limits.

        Raises:
            ValueError: If the firm/phase combination is not supported.
        """
        firm_key = firm.value.lower() if isinstance(firm, PropFirm) else firm.lower()
        phase_key = phase.value if isinstance(phase, Phase) else phase.lower()

        key = (firm_key, phase_key)
        if key not in cls._RULES:
            available = [f"{f}/{p}" for f, p in cls._RULES.keys()]
            raise ValueError(
                f"Unknown firm/phase combination: {firm_key}/{phase_key}. "
                f"Available: {available}"
            )
        return cls._RULES[key]

    @classmethod
    def list_supported(cls) -> List[str]:
        """Return a list of supported firm/phase combinations."""
        return [f"{firm}/{phase}" for firm, phase in cls._RULES.keys()]


# ---------------------------------------------------------------------------
# Correlation Checker
# ---------------------------------------------------------------------------


class CorrelationChecker:
    """Prevent over-concentration by checking symbol correlations.

    Blocks new trades in symbols that are highly correlated with
    already-open positions, reducing portfolio concentration risk.
    """

    # Approximate pairwise correlation matrix (symmetric, 0=uncorrelated, 1=perfect)
    _CORRELATIONS: Dict[Tuple[str, str], float] = {
        # Forex majors
        ("EURUSD", "GBPUSD"): 0.85,
        ("EURUSD", "AUDUSD"): 0.75,
        ("EURUSD", "NZDUSD"): 0.70,
        ("EURUSD", "USDCHF"): -0.85,
        ("EURUSD", "USDJPY"): -0.40,
        ("GBPUSD", "AUDUSD"): 0.80,
        ("GBPUSD", "NZDUSD"): 0.75,
        ("AUDUSD", "NZDUSD"): 0.90,
        ("USDCHF", "USDJPY"): 0.45,
        # Gold and related
        ("XAUUSD", "XAGUSD"): 0.80,
        ("XAUUSD", "USOIL"): 0.35,
        ("XAGUSD", "USOIL"): 0.25,
    }

    CORRELATION_THRESHOLD: float = 0.75  # Block if correlation above this

    def __init__(self) -> None:
        self._lock = threading.RLock()

    def _get_correlation(self, sym1: str, sym2: str) -> float:
        """Return the correlation between two symbols (absolute value)."""
        if sym1 == sym2:
            return 1.0
        key = (sym1, sym2)
        rev_key = (sym2, sym1)
        corr = self._CORRELATIONS.get(key) or self._CORRELATIONS.get(rev_key)
        return abs(corr) if corr else 0.0

    def can_trade(
        self,
        new_symbol: str,
        open_positions: List[Position],
    ) -> Tuple[bool, str]:
        """Check whether a new trade is allowed given existing positions.

        Args:
            new_symbol: The symbol of the proposed trade.
            open_positions: List of currently open positions.

        Returns:
            Tuple of (is_allowed, reason_if_blocked).
        """
        with self._lock:
            for pos in open_positions:
                corr = self._get_correlation(new_symbol, pos.symbol)
                if corr >= self.CORRELATION_THRESHOLD:
                    msg = (
                        f"Correlation block: {new_symbol} vs {pos.symbol} "
                        f"correlation={corr:.2f} >= threshold "
                        f"{self.CORRELATION_THRESHOLD}"
                    )
                    logger.warning(msg)
                    return False, msg
            return True, ""

    def get_correlated_pairs(self, symbol: str) -> List[Tuple[str, float]]:
        """Return all symbols with known correlations to *symbol*."""
        results: List[Tuple[str, float]] = []
        for (s1, s2), corr in self._CORRELATIONS.items():
            if s1 == symbol:
                results.append((s2, abs(corr)))
            elif s2 == symbol:
                results.append((s1, abs(corr)))
        return sorted(results, key=lambda x: x[1], reverse=True)


# ---------------------------------------------------------------------------
# News Event Checker
# ---------------------------------------------------------------------------


class NewsEventChecker:
    """Simple news-event guard that can be extended with a real calendar API.

    By default, blocks trading for high-impact events within a configurable
    window (±30 minutes).  The event list can be populated from an external
    source (ForexFactory, MetaTrader, etc.).
    """

    HIGH_IMPACT_KEYWORDS: List[str] = [
        "NFP", "FOMC", "CPI", "ECB", "BOE", "BOJ",
        "Interest Rate", "Non-Farm", "GDP", "PCE",
    ]

    def __init__(self, block_window_minutes: int = 30) -> None:
        self._lock = threading.RLock()
        self._block_window = timedelta(minutes=block_window_minutes)
        self._events: List[Dict[str, Any]] = []
        logger.info(
            "NewsEventChecker initialised (block_window=%d min)",
            block_window_minutes,
        )

    def set_events(self, events: List[Dict[str, Any]]) -> None:
        """Load the upcoming news-event schedule.

        Each event dict should contain at minimum:
            - ``time``: datetime of the event (UTC)
            - ``impact``: 'high', 'medium', or 'low'
            - ``currency``: affected currency (e.g. 'USD')
        """
        with self._lock:
            self._events = events
            logger.debug("Loaded %d news events", len(events))

    def is_news_blocked(
        self, symbol: str, current_time: Optional[datetime] = None
    ) -> Tuple[bool, Optional[str]]:
        """Check whether trading is blocked due to an upcoming news event.

        Args:
            symbol: The trading instrument (e.g. 'XAUUSD', 'EURUSD').
            current_time: The reference time (defaults to UTC now).

        Returns:
            Tuple of (is_blocked, event_description_or_None).
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)

        with self._lock:
            affected_currencies = self._symbol_to_currencies(symbol)
            for event in self._events:
                if event.get("impact") != "high":
                    continue
                event_time = event.get("time")
                if event_time is None:
                    continue
                if not isinstance(event_time, datetime):
                    try:
                        event_time = datetime.fromisoformat(str(event_time))
                    except (ValueError, TypeError):
                        continue
                if abs((event_time - current_time).total_seconds()) <= \
                        self._block_window.total_seconds():
                    event_currency = event.get("currency", "").upper()
                    if event_currency in affected_currencies:
                        msg = (
                            f"High-impact news: {event.get('title', 'N/A')} "
                            f"at {event_time.isoformat()} "
                            f"({event_currency})"
                        )
                        logger.info("News block: %s", msg)
                        return True, msg
            return False, None

    @staticmethod
    def _symbol_to_currencies(symbol: str) -> List[str]:
        """Extract the component currencies from a forex/metals symbol.

        Examples:
            EURUSD -> ['EUR', 'USD']
            XAUUSD -> ['USD']  (Gold priced in USD)
        """
        sym = symbol.upper()
        # Precious metals
        if sym.startswith("XAU") or sym.startswith("XAG"):
            return [sym[3:]] if len(sym) > 3 else ["USD"]
        # Standard 6-char forex pairs
        if len(sym) == 6:
            return [sym[:3], sym[3:]]
        # Commodities / indices
        if sym in ("USOIL", "BRENT", "NATGAS", "US30", "US100", "DE40"):
            return ["USD"]
        # Default: return the symbol itself
        return [sym]


# ---------------------------------------------------------------------------
# Main Risk Manager
# ---------------------------------------------------------------------------


class RiskManager:
    """Central risk manager that orchestrates all sub-systems.

    This class ties together the circuit breaker, Kelly sizing, portfolio
    heat tracking, consistency scoring, drawdown reduction, correlation
    checking, news-event blocking, and prop-firm rule enforcement into a
    single, cohesive interface.

    Usage::

        risk = RiskManager(
            account_size=10000,
            prop_firm='fundingpips',
            phase='phase1'
        )
        can_trade, reason = risk.pre_trade_check(
            symbol='XAUUSD', direction='buy',
            stop_distance=2.5, strategy='xau_asian'
        )
        if can_trade:
            lots = risk.calculate_position_size(
                stop_distance=2.5, symbol='XAUUSD'
            )

    Args:
        account_size: Starting / current account balance.
        prop_firm: Prop firm identifier (string or :class:`PropFirm`).
        phase: Evaluation phase (string or :class:`Phase`).
        db_path: Optional path to the SQLite database.
        peak_balance: Historical peak balance (defaults to *account_size*).
    """

    def __init__(
        self,
        account_size: float,
        prop_firm: Union[str, PropFirm],
        phase: Union[str, Phase] = "phase1",
        db_path: Optional[str] = None,
        peak_balance: Optional[float] = None,
    ) -> None:
        if account_size <= 0:
            raise ValueError("account_size must be positive")

        self._account_balance: float = account_size
        self._peak_balance: float = peak_balance or account_size
        self._daily_start_balance: float = account_size  # Tracks daily starting balance
        self._prop_firm: str = (
            prop_firm.value if isinstance(prop_firm, PropFirm) else prop_firm
        )
        self._phase: str = (
            phase.value if isinstance(phase, Phase) else phase
        )

        # Resolve firm-specific rules
        self._rules: FirmRules = PropFirmRules.get_rules(
            self._prop_firm, self._phase
        )

        # Initialise SQLite persistence
        self._db = RiskDatabase(db_path)
        self._db.save_account_snapshot(
            balance=account_size,
            equity=account_size,
            peak_balance=self._peak_balance,
        )

        # Sub-systems
        self._circuit = CircuitBreaker(self._db)
        self._kelly = KellySizing(self._db)
        self._heat = PortfolioHeat(self._db)
        self._consistency = ConsistencyTracker(self._db)
        self._reducer = DrawdownReducer()
        self._correlation = CorrelationChecker()
        self._news = NewsEventChecker()

        self._lock = threading.RLock()

        logger.info(
            "RiskManager initialised: firm=%s, phase=%s, balance=%.2f, "
            "daily_dd=%.1f%%, max_dd=%.1f%%",
            self._rules.firm_name, self._phase,
            self._account_balance, self._rules.daily_dd_pct,
            self._rules.max_dd_pct,
        )

    # --- Properties ---

    @property
    def account_balance(self) -> float:
        """Current account balance."""
        with self._lock:
            return self._account_balance

    @account_balance.setter
    def account_balance(self, value: float) -> None:
        """Update account balance and persist snapshot."""
        if value <= 0:
            raise ValueError("account_balance must be positive")
        with self._lock:
            self._account_balance = value
            if value > self._peak_balance:
                self._peak_balance = value
            self._db.save_account_snapshot(
                balance=value, equity=value, peak_balance=self._peak_balance
            )

    @property
    def peak_balance(self) -> float:
        """Historical peak balance."""
        with self._lock:
            return self._peak_balance

    @property
    def rules(self) -> FirmRules:
        """Active prop-firm rules."""
        return self._rules

    @property
    def current_drawdown(self) -> float:
        """Current drawdown from peak balance in account currency."""
        with self._lock:
            return max(0.0, self._peak_balance - self._account_balance)

    @property
    def current_drawdown_pct(self) -> float:
        """Current drawdown from peak as a percentage."""
        with self._lock:
            if self._peak_balance <= 0:
                return 0.0
            return (self.current_drawdown / self._peak_balance) * 100.0

    @property
    def daily_drawdown(self) -> float:
        """Today's drawdown from daily start balance in account currency."""
        with self._lock:
            return max(0.0, self._daily_start_balance - self._account_balance)

    @property
    def daily_start_balance(self) -> float:
        """The account balance at the start of the trading day."""
        with self._lock:
            return self._daily_start_balance

    # --- Core safety check ---

    def pre_trade_check(
        self,
        symbol: str,
        direction: Union[str, TradeDirection],
        stop_distance: float,
        strategy: str,
        current_time: Optional[datetime] = None,
    ) -> Tuple[bool, str]:
        """Run the complete pre-trade safety check.

        Checks (in order):
            1. Daily drawdown limit (hard stop at 60% of limit)
            2. Max drawdown / circuit breaker (stop at 80%)
            3. Consistency rule (no day >35% of profits)
            4. Portfolio heat (< 6%)
            5. Weekend holding restriction
            6. News event check
            7. Max positions per strategy
            8. Correlation check (no over-concentration)

        Args:
            symbol: Trading instrument (e.g. 'XAUUSD').
            direction: 'buy' or 'sell'.
            stop_distance: Stop-loss distance in pips.
            strategy: Strategy identifier.
            current_time: Optional reference time (defaults to UTC now).

        Returns:
            Tuple of (is_safe, reason_if_not).  If *is_safe* is True,
            *reason* is an empty string.
        """
        if current_time is None:
            current_time = datetime.now(timezone.utc)

        direction_str = (
            direction.value if isinstance(direction, TradeDirection) else direction
        )

        with self._lock:
            # ---- 1. Daily drawdown check ----
            daily_dd_limit = self._rules.daily_dd_pct / 100.0 * self._daily_start_balance
            daily_dd = max(0.0, self._daily_start_balance - self._account_balance)
            if daily_dd > daily_dd_limit * 0.60:
                msg = (
                    f"SAFETY: Daily drawdown at ${daily_dd:.2f} "
                    f"({daily_dd/daily_dd_limit*100:.1f}% of ${daily_dd_limit:.2f} limit). "
                    f"Hard stop at 60% of daily limit."
                )
                logger.error(msg)
                return False, msg

            # ---- 2. Circuit breaker / max drawdown ----
            max_dd_limit = self._rules.max_dd_pct / 100.0 * self._account_balance
            circuit_state = self._circuit.evaluate(self.current_drawdown, max_dd_limit)
            if not self._circuit.can_open_new_trades():
                msg = (
                    f"SAFETY: Circuit breaker at {circuit_state.level.name} "
                    f"({circuit_state.drawdown_pct:.1f}% of max DD limit). "
                    f"All new trades blocked."
                )
                logger.error(msg)
                return False, msg

            if self._circuit.emergency_close_required():
                msg = (
                    "SAFETY: EMERGENCY CLOSE triggered by circuit breaker "
                    f"at level {circuit_state.level.name}."
                )
                logger.critical(msg)
                return False, msg

            # ---- 3. Consistency rule ----
            if not self._consistency.is_compliant():
                score, status = self._consistency.calculate_score()
                msg = (
                    f"SAFETY: Consistency violation (score={score:.2f}). "
                    f"Single day >{self._rules.consistency_threshold*100:.0f}% "
                    f"of total profits."
                )
                logger.warning(msg)
                return False, msg

            # ---- 4. Portfolio heat ----
            if not self._heat.can_add_position(self._account_balance):
                heat_report = self._heat.get_heat_report(self._account_balance)
                msg = (
                    f"SAFETY: Portfolio heat at {heat_report['heat_pct']:.2f}%. "
                    f"Max allowed: 6%. No new positions."
                )
                logger.warning(msg)
                return False, msg

            # ---- 5. Weekend holding restriction ----
            if not self._rules.weekend_holding:
                weekday = current_time.weekday()
                hour = current_time.hour
                # Friday after 20:00 UTC -> block
                if weekday == 4 and hour >= 20:
                    msg = (
                        "SAFETY: Weekend holding restriction. "
                        "No new trades after Friday 20:00 UTC."
                    )
                    logger.info(msg)
                    return False, msg
                # Saturday or Sunday -> block
                if weekday in (5, 6):
                    msg = (
                        "SAFETY: Weekend trading not permitted "
                        f"({current_time.strftime('%A')})."
                    )
                    logger.info(msg)
                    return False, msg
                # Check symbol-specific weekend blocks
                if symbol.upper() in WEEKEND_HOLDING_BLOCKED_PAIRS:
                    if weekday == 4 and hour >= 18:
                        msg = (
                            f"SAFETY: {symbol} weekend holding blocked "
                            f"after Friday 18:00 UTC."
                        )
                        logger.info(msg)
                        return False, msg

            # ---- 6. News event check ----
            if not self._rules.news_trading_allowed:
                blocked, news_reason = self._news.is_news_blocked(
                    symbol, current_time
                )
                if blocked:
                    msg = f"SAFETY: News event block. {news_reason}"
                    logger.info(msg)
                    return False, msg

            # ---- 7. Max positions per strategy ----
            open_by_strategy = self._db.get_open_positions(strategy=strategy)
            if len(open_by_strategy) >= self._rules.max_positions_per_strategy:
                msg = (
                    f"SAFETY: Max positions ({self._rules.max_positions_per_strategy}) "
                    f"reached for strategy '{strategy}'."
                )
                logger.info(msg)
                return False, msg

            # ---- 8. Correlation check ----
            all_open = self._db.get_open_positions()
            can_trade_corr, corr_reason = self._correlation.can_trade(
                symbol, all_open
            )
            if not can_trade_corr:
                msg = f"SAFETY: {corr_reason}"
                logger.info(msg)
                return False, msg

            # ---- ALL CLEAR ----
            reduction = self._compute_combined_reduction()
            if reduction < 1.0:
                logger.info(
                    "Pre-trade check PASSED with %.0f%% reduction factor",
                    reduction * 100,
                )
            else:
                logger.debug("Pre-trade check PASSED - full size allowed")
            return True, ""

    def _compute_combined_reduction(self) -> float:
        """Compute the combined position-size reduction factor.

        Takes the minimum (most restrictive) of:
            - Circuit breaker reduction
            - Drawdown reducer
            - Portfolio heat reduction

        Returns:
            Combined reduction factor (0.0 - 1.0).
        """
        with self._lock:
            max_dd_limit = self._rules.max_dd_pct / 100.0 * self._account_balance
            circuit_state = self._circuit.evaluate(self.current_drawdown, max_dd_limit)
            circuit_reduction = circuit_state.reduction_factor

            dd_reduction = self._reducer.reduction_factor(
                self.current_drawdown, max_dd_limit
            )
            heat_reduction = self._heat.reduction_factor(self._account_balance)

            combined = min(circuit_reduction, dd_reduction, heat_reduction)
            logger.debug(
                "Reduction factors: circuit=%.2f, dd=%.2f, heat=%.2f -> combined=%.2f",
                circuit_reduction, dd_reduction, heat_reduction, combined,
            )
            return combined

    # --- Position sizing ---

    def calculate_position_size(
        self,
        stop_distance: float,
        symbol: str = "XAUUSD",
        strategy: Optional[str] = None,
    ) -> float:
        """Calculate the position size in lots after applying all reductions.

        Args:
            stop_distance: Stop-loss distance in pips.
            symbol: Trading instrument.
            strategy: Optional strategy name for Kelly history filtering.

        Returns:
            Position size in standard lots (already reduced).

        Raises:
            ValueError: If inputs are invalid.
        """
        if stop_distance <= 0:
            raise ValueError("stop_distance must be positive")

        with self._lock:
            # Base Kelly size
            base_lots = self._kelly.calculate_size(
                account_balance=self._account_balance,
                stop_distance_pips=stop_distance,
                symbol=symbol,
                strategy=strategy,
            )

            # Apply combined reduction
            reduction = self._compute_combined_reduction()
            final_lots = base_lots * reduction

            # Final floor
            final_lots = max(MIN_LOTS, final_lots)

            logger.info(
                "Position size: %s | stop=%.1f | base=%.2f | "
                "reduction=%.0f%% | final=%.2f lots",
                symbol, stop_distance, base_lots, reduction * 100, final_lots,
            )
            return round(final_lots, 2)

    # --- Trade lifecycle ---

    def on_position_opened(
        self,
        position_id: str,
        symbol: str,
        direction: str,
        lots: float,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        strategy: str,
        risk_amount: float,
    ) -> None:
        """Record a newly opened position.

        Args:
            position_id: Unique position identifier.
            symbol: Trading instrument.
            direction: 'buy' or 'sell'.
            lots: Position size in lots.
            entry_price: Entry price.
            stop_loss: Stop-loss price.
            take_profit: Take-profit price.
            strategy: Strategy identifier.
            risk_amount: Monetary risk of this position.
        """
        position = Position(
            position_id=position_id,
            symbol=symbol,
            direction=direction,
            open_time=datetime.now(timezone.utc),
            lots=lots,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy=strategy,
            risk_amount=risk_amount,
        )
        self._db.add_open_position(position)
        logger.info(
            "Position opened: %s %s %.2f lots @ %.2f (risk=$%.2f)",
            symbol, direction, lots, entry_price, risk_amount,
        )

    def on_position_closed(
        self,
        position_id: str,
        pnl: float,
        exit_price: Optional[float] = None,
    ) -> None:
        """Record a closed position and update daily PnL.

        Args:
            position_id: The position that was closed.
            pnl: Realised profit/loss in account currency.
            exit_price: Optional exit price for logging.
        """
        # Find the position in the database
        all_open = self._db.get_open_positions()
        position = next(
            (p for p in all_open if p.position_id == position_id), None
        )
        if position is None:
            logger.warning("Closed position %s not found in open positions", position_id)
            # Still record a trade with minimal info
            trade = TradeRecord(
                trade_id=position_id,
                symbol="UNKNOWN",
                direction="UNKNOWN",
                entry_time=datetime.now(timezone.utc),
                exit_time=datetime.now(timezone.utc),
                pnl=pnl,
                lots=0.0,
                strategy="UNKNOWN",
            )
        else:
            trade = TradeRecord(
                trade_id=position_id,
                symbol=position.symbol,
                direction=position.direction,
                entry_time=position.open_time,
                exit_time=datetime.now(timezone.utc),
                pnl=pnl,
                lots=position.lots,
                strategy=position.strategy,
            )
            self._db.remove_open_position(position_id)

        self._db.add_trade(trade)

        # Update balance
        with self._lock:
            self.account_balance = self._account_balance + pnl

        logger.info(
            "Position closed: %s | PnL=$%.2f | balance=$%.2f",
            position_id, pnl, self._account_balance,
        )

    # --- News event management ---

    def load_news_events(self, events: List[Dict[str, Any]]) -> None:
        """Load upcoming news events for the news-event checker."""
        self._news.set_events(events)

    # --- Reporting ---

    def get_status_report(self) -> Dict[str, Any]:
        """Return a comprehensive risk status report.

        Returns:
            Dictionary with circuit state, heat report, consistency report,
            Kelly stats, drawdown info, and combined reduction factor.
        """
        with self._lock:
            max_dd_limit = self._rules.max_dd_pct / 100.0 * self._account_balance
            circuit_state = self._circuit.evaluate(self.current_drawdown, max_dd_limit)
            return {
                "account": {
                    "balance": round(self._account_balance, 2),
                    "peak_balance": round(self._peak_balance, 2),
                    "daily_start_balance": round(self._daily_start_balance, 2),
                    "drawdown": round(self.current_drawdown, 2),
                    "drawdown_pct": round(self.current_drawdown_pct, 2),
                    "daily_drawdown": round(self.daily_drawdown, 2),
                },
                "firm_rules": {
                    "firm": self._rules.firm_name,
                    "daily_dd_pct": self._rules.daily_dd_pct,
                    "max_dd_pct": self._rules.max_dd_pct,
                    "phase": self._phase,
                },
                "circuit_breaker": {
                    "level": circuit_state.level.name,
                    "drawdown_pct_of_limit": round(circuit_state.drawdown_pct, 2),
                    "reduction_factor": circuit_state.reduction_factor,
                    "emergency_close": circuit_state.emergency_close,
                },
                "portfolio_heat": self._heat.get_heat_report(self._account_balance),
                "consistency": self._consistency.get_report(),
                "kelly": self._kelly.get_kelly_stats(),
                "drawdown_reduction": {
                    "factor": self._reducer.reduction_factor(
                        self.current_drawdown, max_dd_limit
                    ),
                    "band": self._reducer.get_band(
                        self.current_drawdown, max_dd_limit
                    ),
                },
                "combined_reduction": self._compute_combined_reduction(),
            }

    def reset_daily_balance(self) -> None:
        """Reset the daily start balance to the current balance.

        Call this at the start of each trading day to establish a new
        baseline for daily drawdown tracking.
        """
        with self._lock:
            self._daily_start_balance = self._account_balance
            logger.info(
                "Daily start balance reset to $%.2f", self._account_balance
            )

    def reset(self) -> None:
        """Reset all sub-systems (useful for testing or new evaluation)."""
        with self._lock:
            self._circuit.reset()
            self._daily_start_balance = self._account_balance
            self._peak_balance = self._account_balance
            logger.info("RiskManager reset complete")


# ---------------------------------------------------------------------------
# Convenience function for direct import
# ---------------------------------------------------------------------------

def pre_trade_safety_check(
    account: Dict[str, float],
    positions: List[Position],
    strategies: Dict[str, Any],
    rules: FirmRules,
) -> Tuple[bool, str]:
    """Standalone pre-trade safety check function.

    This is a convenience wrapper that creates a temporary :class:`RiskManager`
    and runs the full safety check without needing to instantiate the class
    directly.

    Args:
        account: Dictionary with ``balance`` and ``peak_balance`` keys.
        positions: List of open :class:`Position` objects.
        strategies: Strategy configuration dict.
        rules: A :class:`FirmRules` dataclass.

    Returns:
        Tuple of (is_safe, reason_if_not).
    """
    balance = account.get("balance", 0.0)
    peak = account.get("peak_balance", balance)
    if balance <= 0:
        return False, "SAFETY: Invalid account balance"

    # Derive firm/phase from rules
    firm_name = rules.firm_name.lower().replace(" ", "_")
    phase = rules.phase

    risk = RiskManager(
        account_size=balance,
        prop_firm=firm_name,
        phase=phase,
        peak_balance=peak,
    )

    # Seed open positions into the DB
    for pos in positions:
        risk._db.add_open_position(pos)

    symbol = strategies.get("symbol", "XAUUSD")
    direction = strategies.get("direction", "buy")
    stop = strategies.get("stop_distance", 2.5)
    strategy = strategies.get("strategy", "default")

    return risk.pre_trade_check(
        symbol=symbol, direction=direction,
        stop_distance=stop, strategy=strategy,
    )


# ---------------------------------------------------------------------------
# Unit test assertions (documentary)
# ---------------------------------------------------------------------------
"""
================================================================================
EXPECTED BEHAVIOUR (unit-test reference)
================================================================================

TestCircuitBreaker::
    test_normal_drawdown -> level=NORMAL, reduction=1.0
    test_dd_55pct_of_limit -> level=LEVEL_1, reduction=0.5
    test_dd_65pct_of_limit -> level=LEVEL_2, reduction=0.25
    test_dd_75pct_of_limit -> level=LEVEL_3, reduction=0.10
    test_dd_85pct_of_limit -> level=LEVEL_4, reduction=0.0, trades_blocked
    test_dd_95pct_of_limit -> level=LEVEL_5, reduction=0.0, emergency_close

TestKellySizing::
    test_insufficient_trades -> fallback to 0.5% risk
    test_profitable_history -> kelly fraction < 1.0
    test_max_risk_cap -> never exceeds 2% of account
    test_min_lots_floor -> never below 0.01 lots

TestPortfolioHeat::
    test_heat_3pct -> zone=NORMAL, reduction=1.0
    test_heat_4_5pct -> zone=CAUTION, reduction=0.5
    test_heat_5_8pct -> zone=DANGER, reduction=0.25
    test_heat_7pct -> zone=MAX, new_positions_blocked

TestConsistencyTracker::
    test_no_trades -> score=0.0, COMPLIANT
    test_balanced_days -> score<0.30, COMPLIANT
    test_one_big_day -> score>0.35, VIOLATION

TestDrawdownReducer::
    test_dd_10pct -> factor=1.0
    test_dd_30pct -> factor=0.75
    test_dd_50pct -> factor=0.50
    test_dd_70pct -> factor=0.25
    test_dd_90pct -> factor=0.10

TestPropFirmRules::
    test_fundingpips_phase1 -> daily_dd=5%, max_dd=10%
    test_ftmo_funded -> daily_dd=5%, max_dd=10%
    test_the5pers_phase2 -> daily_dd=3%, max_dd=6%

TestRiskManagerIntegration::
    test_full_safety_check_pass -> is_safe=True, lots>0
    test_circuit_breaker_blocks -> is_safe=False, reason contains 'Circuit'
    test_weekend_block -> is_safe=False, reason contains 'Weekend'
    test_position_size_reduced -> lots < base_size when DD elevated
    test_correlation_block -> is_safe=False for correlated pairs
================================================================================
"""

if __name__ == "__main__":
    # Quick sanity check when running the module directly
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    print("=" * 60)
    print("Risk Manager v2.0.0 - Prop Firm Trading Bot")
    print("=" * 60)
    print()

    # Show supported firms
    print("Supported prop firms / phases:")
    for combo in PropFirmRules.list_supported():
        parts = combo.split("/")
        rules = PropFirmRules.get_rules(parts[0], parts[1])
        print(
            f"  {combo:25s} -> daily_dd={rules.daily_dd_pct:.1f}%, "
            f"max_dd={rules.max_dd_pct:.1f}%"
        )
    print()

    # Demonstrate RiskManager instantiation
    risk = RiskManager(
        account_size=10000,
        prop_firm=PropFirm.FUNDINGPIPS,
        phase=Phase.PHASE1,
    )
    print(f"Account balance: ${risk.account_balance:,.2f}")
    print(f"Active rules:    {risk.rules.firm_name}")
    print(f"Daily DD limit:  {risk.rules.daily_dd_pct}%")
    print(f"Max DD limit:    {risk.rules.max_dd_pct}%")
    print()

    # Demonstrate a pre-trade check (will pass with a fresh account)
    can_trade, reason = risk.pre_trade_check(
        symbol="XAUUSD", direction="buy",
        stop_distance=2.5, strategy="xau_asian",
    )
    print(f"Pre-trade check: can_trade={can_trade}, reason='{reason}'")
    if can_trade:
        lots = risk.calculate_position_size(stop_distance=2.5, symbol="XAUUSD")
        print(f"Calculated size: {lots:.2f} lots")
    print()
    print("Module loaded successfully.")
