"""
Multi-Agent Trading System inspired by TradingAgents (arXiv:2412.20138).

Replicates the collaborative trading firm dynamics with specialized agents
that debate before making trading decisions. No LLM required — agents use
technical analysis and rule-based reasoning.

Architecture:
    1. BullResearcher — Analyzes bullish signals, finds supporting evidence
    2. BearResearcher — Analyzes bearish signals, finds counter-evidence
    3. TechnicalAnalyst — Analyzes indicators (EMA, RSI, ATR, Volume Profile)
    4. SentimentAnalyst — Analyzes market sentiment from price action
    5. RiskManagerAgent — Checks if proposed trade violates risk rules
    6. HeadTrader — Synthesizes all inputs, debates, makes final decision

The process:
    1. Bull and Bear researchers independently analyze market data
    2. Technical Analyst computes indicator readings
    3. Sentiment Analyst assesses market mood
    4. All agents submit their analysis
    5. A DEBATE occurs where agents argue their positions
    6. Risk Manager evaluates the proposed trade
    7. Trader makes the final decision (BUY/SELL/HOLD) with confidence score
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

# ──────────────────────────────────────────────────────────────
# Logging Setup
# ──────────────────────────────────────────────────────────────

LOG_DIR = Path("/mnt/agents/output/project/logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("TradingAgents")
logger.setLevel(logging.DEBUG)

_file_handler = logging.FileHandler(LOG_DIR / "trading_agents.log")
_file_handler.setLevel(logging.DEBUG)
_file_formatter = logging.Formatter(
    "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
)
_file_handler.setFormatter(_file_formatter)
logger.addHandler(_file_handler)

_console_handler = logging.StreamHandler()
_console_handler.setLevel(logging.INFO)
_console_formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(message)s"
)
_console_handler.setFormatter(_console_formatter)
logger.addHandler(_console_handler)

# ──────────────────────────────────────────────────────────────
# Data Models
# ──────────────────────────────────────────────────────────────


class Direction(str, Enum):
    """Trade direction enumeration."""
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class Sentiment(str, Enum):
    """Market sentiment enumeration."""
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass
class AgentOpinion:
    """Opinion returned by a trading agent after analysis.

    Attributes:
        agent_name: Name of the agent providing the opinion.
        direction: Overall direction — 'bullish', 'bearish', or 'neutral'.
        confidence: Confidence score between 0.0 and 1.0.
        reasoning: Human-readable explanation of the analysis.
        key_signals: List of specific signals that informed the opinion.
        metadata: Additional structured data from the analysis.
        timestamp: When the opinion was generated.
    """
    agent_name: str
    direction: str
    confidence: float
    reasoning: str
    key_signals: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def __post_init__(self) -> None:
        """Validate fields after initialization."""
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"Confidence must be in [0.0, 1.0], got {self.confidence}"
            )


@dataclass
class RiskAssessment:
    """Risk assessment result from the RiskManagerAgent.

    Attributes:
        approved: Whether the proposed trade passes all risk checks.
        risk_level: Risk level as 'low', 'medium', 'high', 'critical'.
        checks_passed: Number of risk checks passed.
        checks_failed: Number of risk checks failed.
        max_position_size: Maximum allowed position size.
        daily_drawdown_pct: Current daily drawdown percentage.
        reasoning: Detailed explanation of the risk assessment.
        violations: List of specific risk violations if any.
    """
    approved: bool
    risk_level: str
    checks_passed: int
    checks_failed: int
    max_position_size: float
    daily_drawdown_pct: float
    reasoning: str
    violations: List[str] = field(default_factory=list)


@dataclass
class TradeDecision:
    """Final trade decision from the HeadTrader.

    Attributes:
        direction: 'buy', 'sell', or 'hold'.
        confidence: Confidence score between 0.0 and 1.0.
        size: Position size in lots.
        entry_price: Proposed entry price.
        stop_loss: Proposed stop loss price.
        take_profit: Proposed take profit price.
        agent_votes: How each agent voted.
        debate_summary: Summary of the agent debate.
        risk_approved: Whether risk manager approved.
        timestamp: When the decision was made.
    """
    direction: str
    confidence: float
    size: float
    entry_price: float
    stop_loss: float
    take_profit: float
    agent_votes: Dict[str, str] = field(default_factory=dict)
    debate_summary: str = ""
    risk_approved: bool = False
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class IndicatorReadings:
    """Technical indicator readings from the TechnicalAnalyst.

    Attributes:
        rsi: Current RSI value (0-100).
        rsi_trend: RSI trend direction.
        macd_line: MACD line value.
        macd_signal: MACD signal line value.
        macd_histogram: MACD histogram value.
        macd_histogram_trend: Whether histogram is increasing/decreasing.
        ema_alignment: EMA alignment status.
        ema_20: EMA 20 value.
        ema_50: EMA 50 value.
        ema_200: EMA 200 value.
        bollinger_pct_b: %B value (0-1).
        bollinger_width: Bollinger Band width.
        atr: Average True Range.
        atr_percent: ATR as percentage of price.
        vwap: Volume Weighted Average Price.
        volume_trend: Volume trend direction.
        adx: Average Directional Index.
    """
    rsi: float
    rsi_trend: str
    macd_line: float
    macd_signal: float
    macd_histogram: float
    macd_histogram_trend: str
    ema_alignment: str
    ema_20: float
    ema_50: float
    ema_200: float
    bollinger_pct_b: float
    bollinger_width: float
    atr: float
    atr_percent: float
    vwap: float
    volume_trend: str
    adx: float


# ──────────────────────────────────────────────────────────────
# Technical Indicator Utilities
# ──────────────────────────────────────────────────────────────


def compute_ema(series: pd.Series, period: int) -> pd.Series:
    """Compute Exponential Moving Average.

    Args:
        series: Price series.
        period: EMA period.

    Returns:
        EMA series.
    """
    return series.ewm(span=period, adjust=False).mean()


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Compute Relative Strength Index.

    Args:
        series: Close price series.
        period: RSI period (default 14).

    Returns:
        RSI series (0-100).
    """
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    return 100.0 - (100.0 / (1.0 + rs))


def compute_macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """Compute MACD line, signal line, and histogram.

    Args:
        series: Close price series.
        fast: Fast EMA period.
        slow: Slow EMA period.
        signal: Signal EMA period.

    Returns:
        Tuple of (macd_line, signal_line, histogram).
    """
    ema_fast = compute_ema(series, fast)
    ema_slow = compute_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = compute_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def compute_atr(
    df: pd.DataFrame, period: int = 14
) -> pd.Series:
    """Compute Average True Range.

    Args:
        df: DataFrame with 'high', 'low', 'close' columns.
        period: ATR period.

    Returns:
        ATR series.
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def compute_bollinger_bands(
    series: pd.Series, period: int = 20, std_dev: float = 2.0
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series]:
    """Compute Bollinger Bands.

    Args:
        series: Close price series.
        period: SMA period.
        std_dev: Number of standard deviations.

    Returns:
        Tuple of (middle, upper, lower, pct_b).
    """
    middle = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    pct_b = (series - lower) / ((upper - lower) + 1e-10)
    return middle, upper, lower, pct_b


def compute_vwap(df: pd.DataFrame) -> pd.Series:
    """Compute Volume Weighted Average Price.

    Args:
        df: DataFrame with 'high', 'low', 'close', 'tick_volume' columns.

    Returns:
        VWAP series.
    """
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    cumulative_tp_vol = (typical_price * df["tick_volume"]).cumsum()
    cumulative_vol = df["tick_volume"].cumsum()
    return cumulative_tp_vol / (cumulative_vol + 1e-10)


def compute_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute Average Directional Index.

    Args:
        df: DataFrame with 'high', 'low', 'close' columns.
        period: ADX period.

    Returns:
        ADX series.
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.clip(lower=0.0)
    minus_dm = minus_dm.clip(lower=0.0)
    plus_dm = plus_dm.where(plus_dm > minus_dm, 0.0)
    minus_dm = minus_dm.where(minus_dm > plus_dm, 0.0)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.ewm(span=period, adjust=False).mean()
    plus_di = 100.0 * (plus_dm.ewm(span=period, adjust=False).mean() / (atr + 1e-10))
    minus_di = 100.0 * (minus_dm.ewm(span=period, adjust=False).mean() / (atr + 1e-10))
    dx = 100.0 * ((plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10))
    return dx.ewm(span=period, adjust=False).mean()


def detect_candle_pattern(
    open_p: float, high: float, low: float, close: float
) -> str:
    """Detect basic candlestick patterns.

    Args:
        open_p: Open price.
        high: High price.
        low: Low price.
        close: Close price.

    Returns:
        Pattern name or 'none'.
    """
    body = abs(close - open_p)
    total_range = high - low
    upper_shadow = high - max(open_p, close)
    lower_shadow = min(open_p, close) - low

    if total_range == 0:
        return "doji"

    body_pct = body / total_range

    # Doji: very small body
    if body_pct < 0.1:
        return "doji"

    # Hammer: small body at top, long lower shadow
    if body_pct < 0.3 and lower_shadow > 2 * body and upper_shadow < body:
        if close > open_p:
            return "hammer"
        return "hanging_man"

    # Inverted hammer: small body at bottom, long upper shadow
    if body_pct < 0.3 and upper_shadow > 2 * body and lower_shadow < body:
        if close > open_p:
            return "inverted_hammer"
        return "shooting_star"

    # Marubozu: large body, very small shadows
    if body_pct > 0.8:
        if close > open_p:
            return "bullish_marubozu"
        return "bearish_marubozu"

    # Spinning top: small body with significant upper and lower shadows
    if body_pct < 0.3 and upper_shadow > body and lower_shadow > body:
        return "spinning_top"

    return "none"


# ──────────────────────────────────────────────────────────────
# Persistence Layer
# ──────────────────────────────────────────────────────────────


class AgentPerformanceTracker:
    """Track agent accuracy over time using SQLite.

    Maintains a database of agent predictions and outcomes to compute
    accuracy statistics. Used to weight agent opinions dynamically.

    Attributes:
        db_path: Path to the SQLite database file.
        lock: Thread-safe lock for database access.
    """

    def __init__(self, db_path: Optional[str] = None) -> None:
        """Initialize the performance tracker.

        Args:
            db_path: Path to SQLite database. Uses default if None.
        """
        if db_path is None:
            db_path = "/mnt/agents/output/project/data/agent_performance.db"
        self.db_path = db_path
        self.lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        """Create the performance tracking tables if they don't exist."""
        with self.lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    agent_name TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    predicted_direction TEXT NOT NULL,
                    actual_direction TEXT,
                    confidence REAL NOT NULL,
                    was_correct INTEGER,
                    timestamp TEXT NOT NULL,
                    metadata TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS trade_decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    decision_direction TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    size REAL NOT NULL,
                    entry_price REAL,
                    exit_price REAL,
                    pnl REAL,
                    timestamp TEXT NOT NULL,
                    debate_summary TEXT
                )
                """
            )
            conn.commit()

    def record_prediction(
        self,
        agent_name: str,
        symbol: str,
        predicted_direction: str,
        confidence: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a prediction from an agent.

        Args:
            agent_name: Name of the agent.
            symbol: Trading symbol.
            predicted_direction: Predicted direction.
            confidence: Confidence score.
            metadata: Optional metadata dict.
        """
        with self.lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO agent_predictions
                (agent_name, symbol, predicted_direction, confidence, timestamp, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    agent_name,
                    symbol,
                    predicted_direction,
                    confidence,
                    datetime.utcnow().isoformat(),
                    json.dumps(metadata) if metadata else None,
                ),
            )
            conn.commit()

    def record_outcome(
        self,
        agent_name: str,
        symbol: str,
        actual_direction: str,
    ) -> None:
        """Update the most recent prediction with the actual outcome.

        Args:
            agent_name: Name of the agent.
            symbol: Trading symbol.
            actual_direction: Actual price direction.
        """
        with self.lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            # Find the most recent un-evaluated prediction
            cursor.execute(
                """
                SELECT id, predicted_direction FROM agent_predictions
                WHERE agent_name = ? AND symbol = ? AND was_correct IS NULL
                ORDER BY timestamp DESC LIMIT 1
                """,
                (agent_name, symbol),
            )
            row = cursor.fetchone()
            if row:
                pred_id, predicted = row
                was_correct = 1 if predicted == actual_direction else 0
                cursor.execute(
                    """
                    UPDATE agent_predictions
                    SET actual_direction = ?, was_correct = ?
                    WHERE id = ?
                    """,
                    (actual_direction, was_correct, pred_id),
                )
                conn.commit()

    def get_agent_accuracy(self, agent_name: str, window: int = 50) -> float:
        """Get the accuracy of an agent over the last N predictions.

        Args:
            agent_name: Name of the agent.
            window: Number of recent predictions to consider.

        Returns:
            Accuracy ratio (0.0 to 1.0). Returns 0.5 if no data.
        """
        with self.lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT was_correct FROM agent_predictions
                WHERE agent_name = ? AND was_correct IS NOT NULL
                ORDER BY timestamp DESC LIMIT ?
                """,
                (agent_name, window),
            )
            rows = cursor.fetchall()
            if not rows:
                return 0.5  # Default neutral accuracy
            correct = sum(1 for row in rows if row[0] == 1)
            return correct / len(rows)

    def get_all_agent_stats(self, window: int = 50) -> Dict[str, Dict[str, float]]:
        """Get accuracy stats for all agents.

        Args:
            window: Number of recent predictions per agent.

        Returns:
            Dict mapping agent name to stats dict.
        """
        with self.lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT DISTINCT agent_name FROM agent_predictions
                """
            )
            agents = [row[0] for row in cursor.fetchall()]

        stats: Dict[str, Dict[str, float]] = {}
        for agent in agents:
            accuracy = self.get_agent_accuracy(agent, window)
            with self.lock, sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT COUNT(*) FROM agent_predictions
                    WHERE agent_name = ? AND was_correct IS NOT NULL
                    """,
                    (agent,),
                )
                total = cursor.fetchone()[0]
            stats[agent] = {
                "accuracy": accuracy,
                "total_predictions": float(total),
                "weight": self._accuracy_to_weight(accuracy),
            }
        return stats

    @staticmethod
    def _accuracy_to_weight(accuracy: float) -> float:
        """Convert accuracy to a weight factor.

        Uses a sigmoid-like mapping to amplify differences in accuracy.

        Args:
            accuracy: Accuracy ratio (0.0 to 1.0).

        Returns:
            Weight factor (0.5 to 2.0).
        """
        # Map [0, 1] to [0.5, 2.0] with center at 0.5 -> 1.0
        return 0.5 + 1.5 * accuracy

    def record_trade_decision(self, decision: TradeDecision, symbol: str) -> None:
        """Record a final trade decision.

        Args:
            decision: The trade decision.
            symbol: Trading symbol.
        """
        with self.lock, sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO trade_decisions
                (symbol, decision_direction, confidence, size, entry_price,
                 timestamp, debate_summary)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    symbol,
                    decision.direction,
                    decision.confidence,
                    decision.size,
                    decision.entry_price,
                    decision.timestamp.isoformat(),
                    decision.debate_summary,
                ),
            )
            conn.commit()


class AgentWeightStore:
    """Store and manage agent weights using JSON file.

    Provides configurable weighting of agent opinions.
    Weights can be adjusted based on performance over time.

    Attributes:
        weights_path: Path to the JSON weights file.
        default_weights: Default weights for each agent.
    """

    DEFAULT_WEIGHTS: Dict[str, float] = {
        "BullResearcher": 1.0,
        "BearResearcher": 1.0,
        "TechnicalAnalyst": 1.2,
        "SentimentAnalyst": 0.9,
        "RiskManagerAgent": 2.0,
    }

    def __init__(self, weights_path: Optional[str] = None) -> None:
        """Initialize the weight store.

        Args:
            weights_path: Path to JSON weights file. Uses default if None.
        """
        if weights_path is None:
            weights_path = "/mnt/agents/output/project/data/agent_weights.json"
        self.weights_path = weights_path
        self._weights: Dict[str, float] = dict(self.DEFAULT_WEIGHTS)
        self._load_weights()

    def _load_weights(self) -> None:
        """Load weights from JSON file or use defaults."""
        if os.path.exists(self.weights_path):
            try:
                with open(self.weights_path, "r") as f:
                    loaded = json.load(f)
                    self._weights.update(loaded)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning("Failed to load weights: %s. Using defaults.", e)

    def save_weights(self) -> None:
        """Save current weights to JSON file."""
        os.makedirs(os.path.dirname(self.weights_path), exist_ok=True)
        with open(self.weights_path, "w") as f:
            json.dump(self._weights, f, indent=2)

    def get_weight(self, agent_name: str) -> float:
        """Get weight for a specific agent.

        Args:
            agent_name: Name of the agent.

        Returns:
            Weight value (default 1.0 if not found).
        """
        return self._weights.get(agent_name, 1.0)

    def set_weight(self, agent_name: str, weight: float) -> None:
        """Set weight for a specific agent.

        Args:
            agent_name: Name of the agent.
            weight: New weight value.
        """
        self._weights[agent_name] = weight
        self.save_weights()

    def update_from_performance(
        self, performance_tracker: AgentPerformanceTracker, window: int = 50
    ) -> None:
        """Update weights based on agent performance.

        Args:
            performance_tracker: Performance tracker instance.
            window: Number of recent predictions to consider.
        """
        stats = performance_tracker.get_all_agent_stats(window)
        for agent_name, agent_stats in stats.items():
            new_weight = AgentPerformanceTracker._accuracy_to_weight(
                agent_stats["accuracy"]
            )
            self._weights[agent_name] = new_weight
        self.save_weights()
        logger.info("Updated agent weights from performance: %s", self._weights)

    def get_all_weights(self) -> Dict[str, float]:
        """Get all current weights.

        Returns:
            Dict mapping agent name to weight.
        """
        return dict(self._weights)


# ──────────────────────────────────────────────────────────────
# Base Trading Agent
# ──────────────────────────────────────────────────────────────


class TradingAgent(ABC):
    """Abstract base class for all trading agents.

    All specialized agents inherit from this class and implement
    the ``analyze`` method to provide their market assessment.

    Attributes:
        name: Human-readable agent name.
        role: Description of the agent's role.
    """

    name: str = "BaseAgent"
    role: str = "Base trading agent"

    def __init__(self) -> None:
        """Initialize the trading agent."""
        self.logger = logging.getLogger(f"TradingAgents.{self.name}")

    @abstractmethod
    async def analyze(self, data: Dict[str, Any]) -> AgentOpinion:
        """Analyze market data and return an opinion.

        Args:
            data: Dictionary containing market data including:
                - 'df': pd.DataFrame with OHLCV data
                - 'symbol': Trading symbol
                - 'account_size': Current account size
                - 'current_drawdown': Current drawdown percentage
                - Additional context as needed.

        Returns:
            AgentOpinion with the agent's analysis.
        """
        ...

    async def safe_analyze(self, data: Dict[str, Any]) -> AgentOpinion:
        """Wrap analyze with error handling.

        If the agent's analysis fails, returns a neutral opinion
        rather than crashing the entire system.

        Args:
            data: Market data dictionary.

        Returns:
            AgentOpinion (neutral fallback on error).
        """
        try:
            return await self.analyze(data)
        except Exception as e:
            self.logger.error(
                "Agent %s analysis failed: %s", self.name, e, exc_info=True
            )
            return AgentOpinion(
                agent_name=self.name,
                direction="neutral",
                confidence=0.0,
                reasoning=f"Analysis failed: {str(e)}",
                key_signals=["error"],
            )


# ──────────────────────────────────────────────────────────────
# BullResearcher Agent
# ──────────────────────────────────────────────────────────────


class BullResearcher(TradingAgent):
    """Finds bullish signals in market data.

    Analyzes trend direction, momentum, volume, support levels,
    breakout patterns, and EMA alignment. Each bullish signal
    contributes to the overall bullish confidence score.

    Signals tracked:
        - Price > EMA20 > EMA50 (bullish alignment)
        - RSI between 50-70 (bullish momentum)
        - MACD histogram > 0 and increasing
        - Close > VWAP
        - Volume > 20-period average
        - Higher highs and higher lows
    """

    name = "BullResearcher"
    role = "Finds bullish signals and supporting evidence"

    async def analyze(self, data: Dict[str, Any]) -> AgentOpinion:
        """Analyze market data for bullish signals.

        Args:
            data: Market data dictionary with 'df' (DataFrame) and 'symbol'.

        Returns:
            AgentOpinion with bullish assessment.
        """
        df: pd.DataFrame = data["df"].copy()
        symbol: str = data.get("symbol", "UNKNOWN")

        if len(df) < 55:
            return AgentOpinion(
                agent_name=self.name,
                direction="neutral",
                confidence=0.0,
                reasoning="Insufficient data for bullish analysis.",
                key_signals=["insufficient_data"],
            )

        signals: List[str] = []
        close = df["close"]
        latest = df.iloc[-1]

        # Signal 1: EMA alignment — Price > EMA20 > EMA50
        ema_20 = compute_ema(close, 20)
        ema_50 = compute_ema(close, 50)
        if latest["close"] > ema_20.iloc[-1] > ema_50.iloc[-1]:
            signals.append("price_above_ema20_above_ema50")

        # Signal 2: RSI between 50-70 (bullish momentum zone)
        rsi = compute_rsi(close, 14)
        latest_rsi = rsi.iloc[-1]
        if 50 <= latest_rsi <= 70:
            signals.append("rsi_bullish_momentum_zone")
        elif latest_rsi > 70:
            signals.append("rsi_overbought_caution")

        # Signal 3: MACD histogram > 0 and increasing
        _, _, hist = compute_macd(close)
        if len(hist) >= 3:
            latest_hist = hist.iloc[-1]
            prev_hist = hist.iloc[-2]
            if latest_hist > 0:
                signals.append("macd_histogram_positive")
                if latest_hist > prev_hist:
                    signals.append("macd_histogram_increasing")

        # Signal 4: Close > VWAP
        vwap = compute_vwap(df)
        if latest["close"] > vwap.iloc[-1]:
            signals.append("price_above_vwap")

        # Signal 5: Volume > 20-period average
        if "tick_volume" in df.columns:
            vol_ma = df["tick_volume"].rolling(20).mean()
            if latest["tick_volume"] > vol_ma.iloc[-1]:
                signals.append("volume_above_average")

        # Signal 6: Higher highs and higher lows
        if len(df) >= 10:
            recent = df.tail(10)
            highs = recent["high"].values
            lows = recent["low"].values
            # Check for higher highs
            hh = highs[-1] > highs[0]
            hl = lows[-1] > lows[0]
            if hh and hl:
                signals.append("higher_highs_higher_lows")
            elif hh:
                signals.append("higher_highs")

        # Signal 7: ADX > 25 (strong trend)
        adx = compute_adx(df)
        if adx.iloc[-1] > 25:
            signals.append("strong_trend_adx")

        # Signal 8: Price above EMA200 (long-term bullish)
        ema_200 = compute_ema(close, 200)
        if latest["close"] > ema_200.iloc[-1]:
            signals.append("price_above_ema200")

        # Calculate confidence
        total_possible = 8
        confidence = min(len(signals) / total_possible, 1.0)

        # Build reasoning
        if signals:
            reasoning = (
                f"BullResearcher found {len(signals)} bullish signals for "
                f"{symbol}: {', '.join(signals)}. "
                f"RSI={latest_rsi:.1f}, MACD_hist={hist.iloc[-1]:.4f}. "
                f"Confidence={confidence:.2f}."
            )
            direction = "bullish" if confidence >= 0.3 else "neutral"
        else:
            reasoning = f"No bullish signals found for {symbol}."
            direction = "neutral"
            confidence = 0.0

        return AgentOpinion(
            agent_name=self.name,
            direction=direction,
            confidence=confidence,
            reasoning=reasoning,
            key_signals=signals,
            metadata={
                "rsi": float(latest_rsi),
                "macd_histogram": float(hist.iloc[-1]),
                "adx": float(adx.iloc[-1]),
                "signal_count": len(signals),
            },
        )


# ──────────────────────────────────────────────────────────────
# BearResearcher Agent
# ──────────────────────────────────────────────────────────────


class BearResearcher(TradingAgent):
    """Finds bearish signals in market data.

    Analyzes resistance levels, overbought conditions, bearish divergence,
    weakening momentum, and distribution patterns. Each bearish signal
    contributes to the overall bearish confidence score.

    Signals tracked:
        - Price < EMA20 < EMA50 (bearish alignment)
        - RSI between 30-50 (bearish momentum) or > 70 (overbought)
        - MACD histogram < 0 and decreasing
        - Close < VWAP
        - Volume > 20-period average (distribution)
        - Lower highs and lower lows
    """

    name = "BearResearcher"
    role = "Finds bearish signals and counter-evidence"

    async def analyze(self, data: Dict[str, Any]) -> AgentOpinion:
        """Analyze market data for bearish signals.

        Args:
            data: Market data dictionary with 'df' (DataFrame) and 'symbol'.

        Returns:
            AgentOpinion with bearish assessment.
        """
        df: pd.DataFrame = data["df"].copy()
        symbol: str = data.get("symbol", "UNKNOWN")

        if len(df) < 55:
            return AgentOpinion(
                agent_name=self.name,
                direction="neutral",
                confidence=0.0,
                reasoning="Insufficient data for bearish analysis.",
                key_signals=["insufficient_data"],
            )

        signals: List[str] = []
        close = df["close"]
        latest = df.iloc[-1]

        # Signal 1: EMA alignment — Price < EMA20 < EMA50
        ema_20 = compute_ema(close, 20)
        ema_50 = compute_ema(close, 50)
        if latest["close"] < ema_20.iloc[-1] < ema_50.iloc[-1]:
            signals.append("price_below_ema20_below_ema50")

        # Signal 2: RSI in bearish zone (30-50) or overbought > 70
        rsi = compute_rsi(close, 14)
        latest_rsi = rsi.iloc[-1]
        if 30 <= latest_rsi <= 50:
            signals.append("rsi_bearish_momentum_zone")
        elif latest_rsi > 70:
            signals.append("rsi_overbought_bearish_reversal")
        elif latest_rsi < 30:
            signals.append("rsi_oversold_bounce_possible")

        # Signal 3: MACD histogram < 0 and decreasing
        _, _, hist = compute_macd(close)
        if len(hist) >= 3:
            latest_hist = hist.iloc[-1]
            prev_hist = hist.iloc[-2]
            if latest_hist < 0:
                signals.append("macd_histogram_negative")
                if latest_hist < prev_hist:
                    signals.append("macd_histogram_decreasing")

        # Signal 4: Close < VWAP
        vwap = compute_vwap(df)
        if latest["close"] < vwap.iloc[-1]:
            signals.append("price_below_vwap")

        # Signal 5: High volume on down move (distribution)
        if "tick_volume" in df.columns:
            vol_ma = df["tick_volume"].rolling(20).mean()
            if latest["tick_volume"] > vol_ma.iloc[-1] * 1.5 and latest["close"] < df["open"].iloc[-1]:
                signals.append("high_volume_distribution")

        # Signal 6: Lower highs and lower lows
        if len(df) >= 10:
            recent = df.tail(10)
            highs = recent["high"].values
            lows = recent["low"].values
            lh = highs[-1] < highs[0]
            ll = lows[-1] < lows[0]
            if lh and ll:
                signals.append("lower_highs_lower_lows")
            elif lh:
                signals.append("lower_highs")

        # Signal 7: ADX > 25 with bearish price action
        adx = compute_adx(df)
        if adx.iloc[-1] > 25 and latest["close"] < ema_20.iloc[-1]:
            signals.append("strong_bearish_trend")

        # Signal 8: Price below EMA200 (long-term bearish)
        ema_200 = compute_ema(close, 200)
        if latest["close"] < ema_200.iloc[-1]:
            signals.append("price_below_ema200")

        # Signal 9: Bearish engulfing in last 3 candles
        if len(df) >= 3:
            for i in range(-3, 0):
                row = df.iloc[i]
                body = row["close"] - row["open"]
                if body < 0 and abs(body) > (df["high"].iloc[i] - df["low"].iloc[i]) * 0.6:
                    signals.append(f"bearish_candle_at_idx_{i}")
                    break

        # Calculate confidence
        total_possible = 9
        confidence = min(len(signals) / total_possible, 1.0)

        # Build reasoning
        if signals:
            reasoning = (
                f"BearResearcher found {len(signals)} bearish signals for "
                f"{symbol}: {', '.join(signals)}. "
                f"RSI={latest_rsi:.1f}, MACD_hist={hist.iloc[-1]:.4f}. "
                f"Confidence={confidence:.2f}."
            )
            direction = "bearish" if confidence >= 0.3 else "neutral"
        else:
            reasoning = f"No bearish signals found for {symbol}."
            direction = "neutral"
            confidence = 0.0

        return AgentOpinion(
            agent_name=self.name,
            direction=direction,
            confidence=confidence,
            reasoning=reasoning,
            key_signals=signals,
            metadata={
                "rsi": float(latest_rsi),
                "macd_histogram": float(hist.iloc[-1]),
                "adx": float(adx.iloc[-1]),
                "signal_count": len(signals),
            },
        )


# ──────────────────────────────────────────────────────────────
# TechnicalAnalyst Agent
# ──────────────────────────────────────────────────────────────


class TechnicalAnalyst(TradingAgent):
    """Computes technical indicator readings.

    Analyzes RSI, MACD, EMA alignment, Bollinger Bands, ATR,
    Volume Profile, and VWAP position. Returns a neutral opinion
    with detailed indicator readings that other agents can use.

    This agent is data-focused: it computes and reports indicator
    values rather than taking a directional stance.
    """

    name = "TechnicalAnalyst"
    role = "Computes technical indicator readings"

    async def analyze(self, data: Dict[str, Any]) -> AgentOpinion:
        """Compute all technical indicators and return readings.

        Args:
            data: Market data dictionary with 'df' (DataFrame) and 'symbol'.

        Returns:
            AgentOpinion with neutral direction and detailed indicator data.
        """
        df: pd.DataFrame = data["df"].copy()
        symbol: str = data.get("symbol", "UNKNOWN")

        if len(df) < 55:
            return AgentOpinion(
                agent_name=self.name,
                direction="neutral",
                confidence=0.0,
                reasoning="Insufficient data for technical analysis.",
                key_signals=["insufficient_data"],
            )

        close = df["close"]
        latest = df.iloc[-1]

        # RSI
        rsi = compute_rsi(close, 14)
        rsi_value = float(rsi.iloc[-1])
        rsi_trend = "rising" if rsi.iloc[-1] > rsi.iloc[-5] else "falling"

        # MACD
        macd_line, macd_signal, hist = compute_macd(close)
        macd_hist_value = float(hist.iloc[-1])
        macd_hist_trend = (
            "increasing"
            if len(hist) >= 3 and hist.iloc[-1] > hist.iloc[-2]
            else "decreasing"
        )

        # EMA alignment
        ema_20 = compute_ema(close, 20)
        ema_50 = compute_ema(close, 50)
        ema_200 = compute_ema(close, 200)

        latest_close = latest["close"]
        e20 = ema_20.iloc[-1]
        e50 = ema_50.iloc[-1]
        e200 = ema_200.iloc[-1]

        if latest_close > e20 > e50 > e200:
            ema_alignment = "strongly_bullish"
        elif latest_close > e20 > e50:
            ema_alignment = "bullish"
        elif latest_close < e20 < e50 < e200:
            ema_alignment = "strongly_bearish"
        elif latest_close < e20 < e50:
            ema_alignment = "bearish"
        else:
            ema_alignment = "mixed"

        # Bollinger Bands
        _, upper, lower, pct_b = compute_bollinger_bands(close)
        bb_width = float(((upper.iloc[-1] - lower.iloc[-1]) / e20) * 100)

        # ATR
        atr = compute_atr(df)
        atr_value = float(atr.iloc[-1])
        atr_pct = float((atr_value / latest_close) * 100)

        # VWAP
        vwap = compute_vwap(df)
        vwap_value = float(vwap.iloc[-1])

        # Volume trend
        volume_trend = "neutral"
        if "tick_volume" in df.columns:
            vol_ma5 = df["tick_volume"].tail(5).mean()
            vol_ma20 = df["tick_volume"].tail(20).mean()
            if vol_ma5 > vol_ma20 * 1.1:
                volume_trend = "increasing"
            elif vol_ma5 < vol_ma20 * 0.9:
                volume_trend = "decreasing"

        # ADX
        adx = compute_adx(df)
        adx_value = float(adx.iloc[-1])

        # Determine a mild directional bias based on indicators
        bull_points = 0
        bear_points = 0
        signals: List[str] = []

        if rsi_value > 55:
            bull_points += 1
            signals.append("rsi_above_55")
        elif rsi_value < 45:
            bear_points += 1
            signals.append("rsi_below_45")

        if macd_hist_value > 0:
            bull_points += 1
            signals.append("macd_positive")
        else:
            bear_points += 1
            signals.append("macd_negative")

        if "bullish" in ema_alignment:
            bull_points += 1
            signals.append("ema_bullish")
        elif "bearish" in ema_alignment:
            bear_points += 1
            signals.append("ema_bearish")

        if latest_close > vwap_value:
            bull_points += 1
            signals.append("above_vwap")
        else:
            bear_points += 1
            signals.append("below_vwap")

        if adx_value > 25:
            signals.append("strong_trend")

        direction = "neutral"
        confidence = 0.3
        if bull_points > bear_points + 1:
            direction = "bullish"
            confidence = 0.5
        elif bear_points > bull_points + 1:
            direction = "bearish"
            confidence = 0.5

        readings = IndicatorReadings(
            rsi=rsi_value,
            rsi_trend=rsi_trend,
            macd_line=float(macd_line.iloc[-1]),
            macd_signal=float(macd_signal.iloc[-1]),
            macd_histogram=macd_hist_value,
            macd_histogram_trend=macd_hist_trend,
            ema_alignment=ema_alignment,
            ema_20=float(e20),
            ema_50=float(e50),
            ema_200=float(e200),
            bollinger_pct_b=float(pct_b.iloc[-1]),
            bollinger_width=bb_width,
            atr=atr_value,
            atr_percent=atr_pct,
            vwap=vwap_value,
            volume_trend=volume_trend,
            adx=adx_value,
        )

        reasoning = (
            f"Technical analysis for {symbol}: "
            f"RSI={rsi_value:.1f} ({rsi_trend}), "
            f"MACD_hist={macd_hist_value:.4f} ({macd_hist_trend}), "
            f"EMA={ema_alignment}, "
            f"BB_width={bb_width:.1f}%, "
            f"ATR={atr_value:.2f} ({atr_pct:.2f}%), "
            f"ADX={adx_value:.1f}, "
            f"Volume={volume_trend}."
        )

        return AgentOpinion(
            agent_name=self.name,
            direction=direction,
            confidence=confidence,
            reasoning=reasoning,
            key_signals=signals,
            metadata={"indicators": asdict(readings)},
        )


# ──────────────────────────────────────────────────────────────
# SentimentAnalyst Agent
# ──────────────────────────────────────────────────────────────


class SentimentAnalyst(TradingAgent):
    """Assesses market sentiment from price action.

    Analyzes recent candle patterns, volume sentiment, price velocity,
    and volatility regime to determine the overall market mood.

    Unlike the TechnicalAnalyst, this agent focuses on the qualitative
    feel of the market — momentum, urgency, and participation.
    """

    name = "SentimentAnalyst"
    role = "Assesses market sentiment from price action"

    async def analyze(self, data: Dict[str, Any]) -> AgentOpinion:
        """Analyze price action to determine market sentiment.

        Args:
            data: Market data dictionary with 'df' (DataFrame) and 'symbol'.

        Returns:
            AgentOpinion with sentiment assessment.
        """
        df: pd.DataFrame = data["df"].copy()
        symbol: str = data.get("symbol", "UNKNOWN")

        if len(df) < 10:
            return AgentOpinion(
                agent_name=self.name,
                direction="neutral",
                confidence=0.0,
                reasoning="Insufficient data for sentiment analysis.",
                key_signals=["insufficient_data"],
            )

        signals: List[str] = []
        latest = df.iloc[-1]
        close = df["close"]

        # 1. Analyze last 5 candle patterns
        recent_candles = df.tail(5)
        candle_patterns: List[str] = []
        bullish_patterns = 0
        bearish_patterns = 0

        for _, row in recent_candles.iterrows():
            pattern = detect_candle_pattern(
                row["open"], row["high"], row["low"], row["close"]
            )
            candle_patterns.append(pattern)
            if pattern in ("hammer", "inverted_hammer", "bullish_marubozu"):
                bullish_patterns += 1
            elif pattern in ("hanging_man", "shooting_star", "bearish_marubozu"):
                bearish_patterns += 1

        if bullish_patterns >= 2:
            signals.append(f"bullish_candle_patterns:{bullish_patterns}")
        if bearish_patterns >= 2:
            signals.append(f"bearish_candle_patterns:{bearish_patterns}")

        # 2. Volume sentiment
        volume_sentiment = "neutral"
        if "tick_volume" in df.columns and len(df) >= 20:
            vol_recent = df["tick_volume"].tail(5).mean()
            vol_baseline = df["tick_volume"].tail(20).mean()
            if vol_recent > vol_baseline * 1.2:
                volume_sentiment = "increasing"
                signals.append("volume_increasing")
            elif vol_recent < vol_baseline * 0.8:
                volume_sentiment = "decreasing"
                signals.append("volume_decreasing")

            # Volume confirmation: rising price with rising volume = strong
            price_change = (close.iloc[-1] - close.iloc[-5]) / close.iloc[-5] * 100
            if price_change > 0.5 and volume_sentiment == "increasing":
                signals.append("volume_confirming_bullish")
            elif price_change < -0.5 and volume_sentiment == "increasing":
                signals.append("volume_confirming_bearish")

        # 3. Price velocity (acceleration/deceleration)
        if len(close) >= 10:
            returns = close.pct_change().dropna()
            velocity_5 = returns.tail(5).sum()
            velocity_10 = returns.tail(10).sum()

            if abs(velocity_5) > abs(velocity_10 * 0.8):
                if velocity_5 > 0:
                    signals.append("price_accelerating_up")
                else:
                    signals.append("price_accelerating_down")
            else:
                signals.append("price_decelerating")

        # 4. Volatility regime
        if len(df) >= 20:
            atr = compute_atr(df)
            recent_atr = atr.tail(5).mean()
            baseline_atr = atr.tail(20).mean()
            volatility_regime = "contracting"
            if recent_atr > baseline_atr * 1.1:
                volatility_regime = "expanding"
                signals.append("volatility_expanding")
            elif recent_atr < baseline_atr * 0.9:
                volatility_regime = "contracting"
                signals.append("volatility_contracting")
            else:
                volatility_regime = "stable"
                signals.append("volatility_stable")

        # 5. Consecutive same-direction candles
        if len(df) >= 5:
            bodies = df["close"] - df["open"]
            recent_bodies = bodies.tail(5)
            positive_count = (recent_bodies > 0).sum()
            negative_count = (recent_bodies < 0).sum()
            if positive_count >= 4:
                signals.append("strong_buying_pressure:4of5")
            elif negative_count >= 4:
                signals.append("strong_selling_pressure:4of5")

        # Determine direction and confidence
        bull_signals = sum(1 for s in signals if "bullish" in s or "accelerating_up" in s or "buying" in s)
        bear_signals = sum(1 for s in signals if "bearish" in s or "accelerating_down" in s or "selling" in s)

        total_signals = len(signals)
        if total_signals == 0:
            direction = "neutral"
            confidence = 0.0
        else:
            if bull_signals > bear_signals:
                direction = "bullish"
                confidence = min(bull_signals / total_signals, 1.0)
            elif bear_signals > bull_signals:
                direction = "bearish"
                confidence = min(bear_signals / total_signals, 1.0)
            else:
                direction = "neutral"
                confidence = 0.3

        reasoning = (
            f"Sentiment analysis for {symbol}: "
            f"Recent candles: {candle_patterns}. "
            f"Volume: {volume_sentiment}. "
            f"Found {len(signals)} signals: {signals}. "
            f"Overall: {direction} with confidence {confidence:.2f}."
        )

        return AgentOpinion(
            agent_name=self.name,
            direction=direction,
            confidence=confidence,
            reasoning=reasoning,
            key_signals=signals,
            metadata={
                "candle_patterns": candle_patterns,
                "volume_sentiment": volume_sentiment,
                "bull_signals": bull_signals,
                "bear_signals": bear_signals,
            },
        )


# ──────────────────────────────────────────────────────────────
# RiskManagerAgent
# ──────────────────────────────────────────────────────────────


class RiskManagerAgent(TradingAgent):
    """Evaluates trade risk before execution.

    Checks drawdown limits, position sizing, portfolio heat,
    daily loss limits, and other risk constraints. This agent
    has veto power — if it rejects a trade, the trade is blocked.

    Risk Rules:
        - Daily drawdown < 60% of daily limit
        - Max drawdown < 80% of max limit
        - Portfolio heat < 6%
        - Position size within limits (max 2% risk per trade)
        - No weekend holding (if applicable)
        - Volatility-adjusted position sizing
    """

    name = "RiskManagerAgent"
    role = "Evaluates trade risk before execution"

    # Default risk limits (can be overridden via config)
    DEFAULT_DAILY_LOSS_LIMIT_PCT: float = 2.0  # 2% of account per day
    DEFAULT_MAX_DRAWDOWN_PCT: float = 10.0  # 10% max drawdown
    DEFAULT_MAX_PORTFOLIO_HEAT_PCT: float = 6.0  # 6% total risk
    DEFAULT_MAX_RISK_PER_TRADE_PCT: float = 2.0  # 2% risk per trade
    DEFAULT_MAX_POSITION_SIZE_PCT: float = 10.0  # 10% of account

    def __init__(self, config: Optional[Dict[str, float]] = None) -> None:
        """Initialize the RiskManagerAgent.

        Args:
            config: Optional dict with risk limit overrides:
                - 'daily_loss_limit_pct'
                - 'max_drawdown_pct'
                - 'max_portfolio_heat_pct'
                - 'max_risk_per_trade_pct'
                - 'max_position_size_pct'
        """
        super().__init__()
        self.config = config or {}
        self.daily_loss_limit = self.config.get(
            "daily_loss_limit_pct", self.DEFAULT_DAILY_LOSS_LIMIT_PCT
        )
        self.max_drawdown_limit = self.config.get(
            "max_drawdown_pct", self.DEFAULT_MAX_DRAWDOWN_PCT
        )
        self.max_portfolio_heat = self.config.get(
            "max_portfolio_heat_pct", self.DEFAULT_MAX_PORTFOLIO_HEAT_PCT
        )
        self.max_risk_per_trade = self.config.get(
            "max_risk_per_trade_pct", self.DEFAULT_MAX_RISK_PER_TRADE_PCT
        )
        self.max_position_size_pct = self.config.get(
            "max_position_size_pct", self.DEFAULT_MAX_POSITION_SIZE_PCT
        )

    async def analyze(self, data: Dict[str, Any]) -> AgentOpinion:
        """Evaluate risk for a proposed trade.

        Args:
            data: Market data dictionary containing:
                - 'df': OHLCV DataFrame
                - 'symbol': Trading symbol
                - 'account_size': Current account balance
                - 'current_drawdown': Current drawdown percentage
                - 'daily_pnl': Current daily P&L
                - 'open_positions': List of open positions
                - 'proposed_direction': 'buy' or 'sell'
                - 'proposed_size': Proposed position size

        Returns:
            AgentOpinion with risk assessment. Direction is 'bullish' if
            approved (risk is acceptable), 'bearish' if rejected.
        """
        symbol: str = data.get("symbol", "UNKNOWN")
        account_size: float = data.get("account_size", 10000.0)
        current_drawdown: float = data.get("current_drawdown", 0.0)
        daily_pnl: float = data.get("daily_pnl", 0.0)
        open_positions: List[Dict[str, Any]] = data.get("open_positions", [])
        proposed_direction: str = data.get("proposed_direction", "hold")
        proposed_size: float = data.get("proposed_size", 0.0)

        checks_passed = 0
        checks_failed = 0
        violations: List[str] = []

        # Check 1: Daily drawdown < 60% of limit
        daily_dd_pct = abs(daily_pnl) / max(account_size, 1.0) * 100
        daily_threshold = self.daily_loss_limit * 0.6
        if daily_dd_pct < daily_threshold:
            checks_passed += 1
        else:
            checks_failed += 1
            violations.append(
                f"Daily drawdown {daily_dd_pct:.2f}% exceeds 60% of limit "
                f"({daily_threshold:.2f}%)"
            )

        # Check 2: Max drawdown < 80% of limit
        max_dd_threshold = self.max_drawdown_limit * 0.8
        if current_drawdown < max_dd_threshold:
            checks_passed += 1
        else:
            checks_failed += 1
            violations.append(
                f"Max drawdown {current_drawdown:.2f}% exceeds 80% of limit "
                f"({max_dd_threshold:.2f}%)"
            )

        # Check 3: Portfolio heat < 6%
        total_risk = sum(
            pos.get("risk_amount", 0.0) for pos in open_positions
        )
        portfolio_heat = (total_risk / max(account_size, 1.0)) * 100
        if portfolio_heat < self.max_portfolio_heat:
            checks_passed += 1
        else:
            checks_failed += 1
            violations.append(
                f"Portfolio heat {portfolio_heat:.2f}% exceeds limit "
                f"{self.max_portfolio_heat:.2f}%"
            )

        # Check 4: Position size within limits
        position_value = proposed_size * data.get("current_price", 0.0)
        position_pct = (position_value / max(account_size, 1.0)) * 100
        if position_pct < self.max_position_size_pct:
            checks_passed += 1
        else:
            checks_failed += 1
            violations.append(
                f"Position size {position_pct:.2f}% exceeds limit "
                f"{self.max_position_size_pct:.2f}%"
            )

        # Check 5: Risk per trade < 2%
        df = data.get("df")
        if df is not None and len(df) > 14:
            atr = compute_atr(df)
            current_atr = atr.iloc[-1]
            # Assume 2x ATR stop
            risk_per_unit = current_atr * 2
            risk_amount = proposed_size * risk_per_unit
            risk_pct = (risk_amount / max(account_size, 1.0)) * 100
            if risk_pct < self.max_risk_per_trade:
                checks_passed += 1
            else:
                checks_failed += 1
                violations.append(
                    f"Risk per trade {risk_pct:.2f}% exceeds limit "
                    f"{self.max_risk_per_trade:.2f}%"
                )
        else:
            checks_passed += 1  # Skip if no data

        # Check 6: No weekend holding
        now = datetime.utcnow()
        if now.weekday() == 4 and now.hour >= 20:
            checks_failed += 1
            violations.append("Weekend holding not allowed")
        else:
            checks_passed += 1

        # Overall assessment
        total_checks = checks_passed + checks_failed
        approved = checks_failed == 0

        if approved:
            risk_level = "low"
            direction = "bullish"  # Risk is acceptable
            confidence = 1.0
        elif checks_failed <= 1:
            risk_level = "medium"
            direction = "neutral"
            confidence = 0.5
        else:
            risk_level = "high"
            direction = "bearish"
            confidence = min(checks_failed / total_checks, 1.0)

        reasoning = (
            f"Risk assessment for {symbol} {proposed_direction}: "
            f"{checks_passed}/{total_checks} checks passed. "
            f"Risk level: {risk_level}. "
            + ("All clear." if approved else f"Violations: {violations}")
        )

        return AgentOpinion(
            agent_name=self.name,
            direction=direction,
            confidence=confidence,
            reasoning=reasoning,
            key_signals=["risk_approved"] if approved else violations,
            metadata={
                "risk_level": risk_level,
                "checks_passed": checks_passed,
                "checks_failed": checks_failed,
                "daily_drawdown_pct": daily_dd_pct,
                "portfolio_heat": portfolio_heat,
                "approved": approved,
            },
        )

    def get_risk_assessment(self, data: Dict[str, Any]) -> RiskAssessment:
        """Get detailed risk assessment as a structured object.

        Args:
            data: Market data dictionary.

        Returns:
            RiskAssessment with full details.
        """
        opinion = asyncio.get_event_loop().run_until_complete(self.analyze(data))
        return RiskAssessment(
            approved=opinion.metadata.get("approved", False),
            risk_level=opinion.metadata.get("risk_level", "unknown"),
            checks_passed=opinion.metadata.get("checks_passed", 0),
            checks_failed=opinion.metadata.get("checks_failed", 0),
            max_position_size=self._calculate_max_position(data),
            daily_drawdown_pct=opinion.metadata.get("daily_drawdown_pct", 0.0),
            reasoning=opinion.reasoning,
            violations=[s for s in opinion.key_signals if s != "risk_approved"],
        )

    def _calculate_max_position(self, data: Dict[str, Any]) -> float:
        """Calculate maximum allowed position size.

        Args:
            data: Market data dictionary.

        Returns:
            Maximum position size in lots.
        """
        account_size = data.get("account_size", 10000.0)
        max_risk_amount = account_size * (self.max_risk_per_trade / 100.0)
        df = data.get("df")
        if df is not None and len(df) > 14:
            atr = compute_atr(df).iloc[-1]
            risk_per_lot = atr * 2  # 2x ATR stop
            if risk_per_lot > 0:
                return max_risk_amount / risk_per_lot
        return account_size * (self.max_position_size_pct / 100.0) / max(
            data.get("current_price", 1.0), 1.0
        )


# ──────────────────────────────────────────────────────────────
# HeadTrader Agent
# ──────────────────────────────────────────────────────────────


class HeadTrader(TradingAgent):
    """Synthesizes all opinions and makes the final trading decision.

    Collects all agent opinions, weighs them by track record,
    checks for consensus or disagreement, and makes the final
    BUY/SELL/HOLD decision with position sizing.

    Decision Logic:
        bullish_score = weighted sum of bullish opinions
        bearish_score = weighted sum of bearish opinions

        if bullish_score > bearish_score + 0.3 and risk_approved:
            direction = 'buy'
        elif bearish_score > bullish_score + 0.3 and risk_approved:
            direction = 'sell'
        else:
            direction = 'hold'

        confidence = |bullish_score - bearish_score|
        size = kelly_sizing(confidence, account_size)
    """

    name = "HeadTrader"
    role = "Synthesizes all inputs and makes the final decision"

    def __init__(
        self,
        weight_store: Optional[AgentWeightStore] = None,
        performance_tracker: Optional[AgentPerformanceTracker] = None,
    ) -> None:
        """Initialize the HeadTrader.

        Args:
            weight_store: Agent weight store for opinion weighting.
            performance_tracker: Performance tracker for accuracy weighting.
        """
        super().__init__()
        self.weight_store = weight_store or AgentWeightStore()
        self.performance_tracker = performance_tracker or AgentPerformanceTracker()

    async def analyze(self, data: Dict[str, Any]) -> AgentOpinion:
        """This method is not used directly — use ``make_decision`` instead."""
        return AgentOpinion(
            agent_name=self.name,
            direction="neutral",
            confidence=0.0,
            reasoning="HeadTrader uses make_decision(), not analyze().",
        )

    def make_decision(
        self,
        opinions: List[AgentOpinion],
        risk_opinion: AgentOpinion,
        debate_summary: str,
        data: Dict[str, Any],
    ) -> TradeDecision:
        """Synthesize all agent opinions into a final trade decision.

        Args:
            opinions: List of all agent opinions (excluding risk).
            risk_opinion: Risk manager's opinion.
            debate_summary: Summary of the agent debate.
            data: Market data with account_size, symbol, current_price.

        Returns:
            TradeDecision with direction, size, stops, and reasoning.
        """
        symbol = data.get("symbol", "UNKNOWN")
        account_size = data.get("account_size", 10000.0)
        current_price = data.get("current_price", 0.0)
        df = data.get("df")

        # Calculate weighted scores
        bullish_score = 0.0
        bearish_score = 0.0
        agent_votes: Dict[str, str] = {}

        for opinion in opinions:
            weight = self.weight_store.get_weight(opinion.agent_name)
            # Adjust weight by agent accuracy
            accuracy = self.performance_tracker.get_agent_accuracy(
                opinion.agent_name, window=50
            )
            accuracy_weight = AgentPerformanceTracker._accuracy_to_weight(accuracy)
            combined_weight = weight * accuracy_weight

            agent_votes[opinion.agent_name] = opinion.direction

            if opinion.direction == "bullish":
                bullish_score += opinion.confidence * combined_weight
            elif opinion.direction == "bearish":
                bearish_score += opinion.confidence * combined_weight

        # Risk manager opinion
        risk_approved = risk_opinion.metadata.get("approved", False)
        risk_weight = self.weight_store.get_weight("RiskManagerAgent")
        agent_votes["RiskManagerAgent"] = (
            "approved" if risk_approved else "rejected"
        )

        # Apply risk manager weight (veto power)
        if risk_opinion.direction == "bearish":
            bearish_score += risk_opinion.confidence * risk_weight

        # Decision threshold
        threshold = 0.3
        score_diff = bullish_score - bearish_score

        if bullish_score > bearish_score + threshold and risk_approved:
            direction = "buy"
            confidence = min(abs(score_diff) / (bullish_score + bearish_score + 0.1), 1.0)
        elif bearish_score > bullish_score + threshold and risk_approved:
            direction = "sell"
            confidence = min(abs(score_diff) / (bullish_score + bearish_score + 0.1), 1.0)
        else:
            direction = "hold"
            confidence = min(abs(score_diff) / (bullish_score + bearish_score + 0.1), 0.5)

        # Calculate stop loss and take profit using ATR
        entry_price = current_price
        stop_loss = entry_price
        take_profit = entry_price

        if df is not None and len(df) > 14 and direction != "hold":
            atr = compute_atr(df).iloc[-1]
            if direction == "buy":
                stop_loss = entry_price - (atr * 2.0)
                take_profit = entry_price + (atr * 3.0)  # 1.5:1 reward/risk
            else:
                stop_loss = entry_price + (atr * 2.0)
                take_profit = entry_price - (atr * 3.0)

        # Position sizing using fractional Kelly
        size = self._kelly_sizing(confidence, account_size, entry_price, stop_loss)

        # Cap position size
        max_size = account_size * 0.10 / max(entry_price, 1.0)  # Max 10% of account
        size = min(size, max_size)

        if direction == "hold":
            size = 0.0

        reasoning = (
            f"HeadTrader decision for {symbol}: {direction.upper()} "
            f"(confidence={confidence:.2f}, size={size:.4f}). "
            f"Bullish score: {bullish_score:.2f}, Bearish score: {bearish_score:.2f}. "
            f"Risk approved: {risk_approved}."
        )

        self.logger.info(reasoning)

        return TradeDecision(
            direction=direction,
            confidence=confidence,
            size=size,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            agent_votes=agent_votes,
            debate_summary=debate_summary,
            risk_approved=risk_approved,
        )

    @staticmethod
    def _kelly_sizing(
        confidence: float,
        account_size: float,
        entry_price: float,
        stop_loss: float,
    ) -> float:
        """Calculate position size using fractional Kelly criterion.

        Uses a conservative quarter-Kelly approach for safety.

        Args:
            confidence: Win probability (0.0 to 1.0).
            account_size: Total account size.
            entry_price: Entry price.
            stop_loss: Stop loss price.

        Returns:
            Position size in lots/units.
        """
        if entry_price <= 0 or confidence <= 0.5:
            return 0.0

        # Risk per unit
        risk_per_unit = abs(entry_price - stop_loss)
        if risk_per_unit == 0:
            return 0.0

        # Kelly fraction: f* = (p*b - q) / b
        # Where p = win probability, q = loss probability, b = win/loss ratio
        # Simplified: use confidence as edge estimate
        p = confidence
        q = 1.0 - p
        # Assume 1.5:1 reward/risk ratio
        b = 1.5

        kelly_fraction = (p * b - q) / b
        kelly_fraction = max(kelly_fraction, 0.0)

        # Quarter-Kelly for safety
        fractional_kelly = kelly_fraction * 0.25

        # Risk amount
        risk_amount = account_size * fractional_kelly

        # Convert to position size
        size = risk_amount / risk_per_unit

        return max(size, 0.0)


# ──────────────────────────────────────────────────────────────
# MultiAgentTrader — Orchestrator
# ──────────────────────────────────────────────────────────────


class MultiAgentTrader:
    """Orchestrates the multi-agent trading process.

    Coordinates all specialized agents to analyze market data,
    debate their findings, assess risk, and produce a final
    trade decision.

    Usage:
        trader = MultiAgentTrader(account_size=10000)
        decision = await trader.evaluate(df, symbol='XAUUSD')
        if decision.direction != 'hold':
            await execute_trade(decision)

    Attributes:
        account_size: Current account balance.
        agents: Dict of all trading agents by name.
        performance_tracker: SQLite-based performance tracking.
        weight_store: JSON-based agent weight management.
    """

    def __init__(
        self,
        account_size: float = 10000.0,
        risk_config: Optional[Dict[str, float]] = None,
        db_path: Optional[str] = None,
        weights_path: Optional[str] = None,
    ) -> None:
        """Initialize the multi-agent trading system.

        Args:
            account_size: Starting account size.
            risk_config: Optional risk limit overrides.
            db_path: Path to SQLite database.
            weights_path: Path to JSON weights file.
        """
        self.account_size = account_size
        self.performance_tracker = AgentPerformanceTracker(db_path)
        self.weight_store = AgentWeightStore(weights_path)

        # Initialize all agents
        self.agents: Dict[str, TradingAgent] = {
            "BullResearcher": BullResearcher(),
            "BearResearcher": BearResearcher(),
            "TechnicalAnalyst": TechnicalAnalyst(),
            "SentimentAnalyst": SentimentAnalyst(),
            "RiskManagerAgent": RiskManagerAgent(config=risk_config),
        }

        self.head_trader = HeadTrader(self.weight_store, self.performance_tracker)
        self.logger = logging.getLogger("TradingAgents.MultiAgentTrader")

    async def evaluate(
        self,
        df: pd.DataFrame,
        symbol: str,
        current_price: Optional[float] = None,
        open_positions: Optional[List[Dict[str, Any]]] = None,
        daily_pnl: float = 0.0,
        current_drawdown: float = 0.0,
    ) -> TradeDecision:
        """Run the full multi-agent evaluation pipeline.

        Pipeline:
            1. Bull researcher analyzes
            2. Bear researcher analyzes
            3. Technical analyst computes
            4. Sentiment analyst assesses
            5. Debate — compile all opinions
            6. Risk manager evaluates
            7. Head trader decides

        Args:
            df: OHLCV DataFrame with columns: open, high, low, close, tick_volume.
            symbol: Trading symbol (e.g., 'XAUUSD').
            current_price: Current market price (uses last close if None).
            open_positions: List of currently open positions.
            daily_pnl: Current daily P&L.
            current_drawdown: Current drawdown percentage.

        Returns:
            TradeDecision with final direction, size, stops.
        """
        if current_price is None:
            current_price = float(df["close"].iloc[-1])
        if open_positions is None:
            open_positions = []

        self.logger.info(
            "Starting multi-agent evaluation for %s at %.2f", symbol, current_price
        )

        # Prepare data context
        data = {
            "df": df,
            "symbol": symbol,
            "account_size": self.account_size,
            "current_price": current_price,
            "open_positions": open_positions,
            "daily_pnl": daily_pnl,
            "current_drawdown": current_drawdown,
        }

        # ── Phase 1: Run all analysis agents in parallel ──
        analysis_agents = [
            name
            for name, agent in self.agents.items()
            if name != "RiskManagerAgent"
        ]

        tasks = [
            self.agents[name].safe_analyze(data) for name in analysis_agents
        ]
        opinions = await asyncio.gather(*tasks)

        self.logger.info(
            "Collected %d agent opinions for %s", len(opinions), symbol
        )
        for op in opinions:
            self.logger.debug(
                "  %s: %s (confidence=%.2f)", op.agent_name, op.direction, op.confidence
            )

        # ── Phase 2: Run debate ──
        debate_summary = await self.run_debate(list(opinions))
        self.logger.info("Debate summary for %s:\n%s", symbol, debate_summary)

        # ── Phase 3: Risk assessment ──
        # Determine provisional direction from debate
        bullish_count = sum(1 for op in opinions if op.direction == "bullish")
        bearish_count = sum(1 for op in opinions if op.direction == "bearish")
        provisional_direction = (
            "buy" if bullish_count > bearish_count else "sell"
        )

        risk_data = {
            **data,
            "proposed_direction": provisional_direction,
            "proposed_size": 1.0,  # Will be adjusted by HeadTrader
        }
        risk_opinion = await self.agents["RiskManagerAgent"].safe_analyze(risk_data)
        self.logger.info("Risk assessment: %s", risk_opinion.reasoning)

        # ── Phase 4: HeadTrader makes final decision ──
        decision = self.head_trader.make_decision(
            opinions=list(opinions),
            risk_opinion=risk_opinion,
            debate_summary=debate_summary,
            data=data,
        )

        # ── Phase 5: Record predictions ──
        self._record_predictions(opinions, risk_opinion, decision, symbol)
        self.performance_tracker.record_trade_decision(decision, symbol)

        self.logger.info(
            "Final decision for %s: %s (confidence=%.2f, size=%.4f)",
            symbol,
            decision.direction.upper(),
            decision.confidence,
            decision.size,
        )

        return decision

    async def run_debate(self, opinions: List[AgentOpinion]) -> str:
        """Compile agent opinions into a debate summary.

        Shows areas of agreement and disagreement. Highlights
        consensus signals vs conflicting ones.

        Args:
            opinions: List of all agent opinions.

        Returns:
            Formatted debate summary string.
        """
        lines: List[str] = []
        lines.append("=" * 60)
        lines.append("MULTI-AGENT DEBATE SUMMARY")
        lines.append("=" * 60)

        # Group by direction
        bullish = [op for op in opinions if op.direction == "bullish"]
        bearish = [op for op in opinions if op.direction == "bearish"]
        neutral = [op for op in opinions if op.direction == "neutral"]

        lines.append(f"\nBULLISH agents ({len(bullish)}):")
        for op in bullish:
            lines.append(
                f"  [{op.agent_name:20s}] confidence={op.confidence:.2f} | "
                f"{op.reasoning[:80]}"
            )

        lines.append(f"\nBEARISH agents ({len(bearish)}):")
        for op in bearish:
            lines.append(
                f"  [{op.agent_name:20s}] confidence={op.confidence:.2f} | "
                f"{op.reasoning[:80]}"
            )

        lines.append(f"\nNEUTRAL agents ({len(neutral)}):")
        for op in neutral:
            lines.append(
                f"  [{op.agent_name:20s}] confidence={op.confidence:.2f} | "
                f"{op.reasoning[:80]}"
            )

        # Find consensus signals
        all_signals: Dict[str, int] = {}
        for op in opinions:
            for signal in op.key_signals:
                all_signals[signal] = all_signals.get(signal, 0) + 1

        if all_signals:
            lines.append("\n--- Consensus Signals ---")
            # Signals mentioned by multiple agents
            consensus = {
                s: c for s, c in all_signals.items() if c >= 2 and s != "error"
            }
            if consensus:
                for signal, count in sorted(
                    consensus.items(), key=lambda x: -x[1]
                ):
                    lines.append(f"  [{count}x] {signal}")
            else:
                lines.append("  No strong consensus signals found.")

            # Points of disagreement
            lines.append("\n--- Points of Disagreement ---")
            bull_signals = set()
            bear_signals = set()
            for op in opinions:
                if op.direction == "bullish":
                    bull_signals.update(op.key_signals)
                elif op.direction == "bearish":
                    bear_signals.update(op.key_signals)
            disagreements = bull_signals & bear_signals
            if disagreements:
                lines.append(f"  Signals seen in both camps: {disagreements}")
            else:
                lines.append("  Clear separation between bull and bear signals.")

        # Summary
        if len(bullish) > len(bearish) and len(bullish) > len(neutral):
            lines.append(f"\n>> CONSENSUS: BULLISH ({len(bullish)}/{len(opinions)} agents)")
        elif len(bearish) > len(bullish) and len(bearish) > len(neutral):
            lines.append(f"\n>> CONSENSUS: BEARISH ({len(bearish)}/{len(opinions)} agents)")
        else:
            lines.append(f"\n>> NO CLEAR CONSENSUS ({len(bullish)} bull, {len(bearish)} bear, {len(neutral)} neutral)")

        lines.append("=" * 60)
        return "\n".join(lines)

    def get_agent_performance(self) -> Dict[str, Dict[str, float]]:
        """Track how accurate each agent has been.

        Used to weight agent opinions over time. Agents with
        better track records get more weight in decisions.

        Returns:
            Dict mapping agent name to performance stats.
        """
        return self.performance_tracker.get_all_agent_stats(window=50)

    def update_weights_from_performance(self) -> None:
        """Update agent weights based on recent performance."""
        self.weight_store.update_from_performance(self.performance_tracker)
        self.logger.info("Agent weights updated from performance data.")

    def _record_predictions(
        self,
        opinions: List[AgentOpinion],
        risk_opinion: AgentOpinion,
        decision: TradeDecision,
        symbol: str,
    ) -> None:
        """Record all agent predictions for later outcome tracking.

        Args:
            opinions: Analysis agent opinions.
            risk_opinion: Risk manager opinion.
            decision: Final trade decision.
            symbol: Trading symbol.
        """
        all_opinions = list(opinions) + [risk_opinion]
        for opinion in all_opinions:
            self.performance_tracker.record_prediction(
                agent_name=opinion.agent_name,
                symbol=symbol,
                predicted_direction=opinion.direction,
                confidence=opinion.confidence,
                metadata={"key_signals": opinion.key_signals},
            )

    def record_trade_outcome(
        self,
        symbol: str,
        actual_direction: str,
    ) -> None:
        """Record the actual outcome of a trade for all agents.

        This should be called after a trade closes to update
        agent accuracy tracking.

        Args:
            symbol: Trading symbol.
            actual_direction: Actual price direction ('bullish', 'bearish', 'neutral').
        """
        for agent_name in self.agents:
            self.performance_tracker.record_outcome(
                agent_name=agent_name,
                symbol=symbol,
                actual_direction=actual_direction,
            )
        self.logger.info(
            "Recorded trade outcome for %s: %s", symbol, actual_direction
        )


# ──────────────────────────────────────────────────────────────
# Convenience Factory Functions
# ──────────────────────────────────────────────────────────────


def create_default_trader(
    account_size: float = 10000.0,
) -> MultiAgentTrader:
    """Create a multi-agent trader with default configuration.

    Args:
        account_size: Starting account size.

    Returns:
        Configured MultiAgentTrader instance.
    """
    return MultiAgentTrader(account_size=account_size)


# ──────────────────────────────────────────────────────────────
# Module-level exports
# ──────────────────────────────────────────────────────────────

__all__ = [
    # Data models
    "Direction",
    "Sentiment",
    "AgentOpinion",
    "RiskAssessment",
    "TradeDecision",
    "IndicatorReadings",
    # Technical utilities
    "compute_ema",
    "compute_rsi",
    "compute_macd",
    "compute_atr",
    "compute_bollinger_bands",
    "compute_vwap",
    "compute_adx",
    "detect_candle_pattern",
    # Persistence
    "AgentPerformanceTracker",
    "AgentWeightStore",
    # Agents
    "TradingAgent",
    "BullResearcher",
    "BearResearcher",
    "TechnicalAnalyst",
    "SentimentAnalyst",
    "RiskManagerAgent",
    "HeadTrader",
    # Orchestrator
    "MultiAgentTrader",
    "create_default_trader",
]
