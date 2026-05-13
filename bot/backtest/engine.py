"""
engine.py - Event-driven backtest engine for prop firm trading bot.

Simulates realistic trade execution with:
    - Spread modeling per instrument
    - Slippage (random 0-1 pip)
    - Commission ($5/lot FX & metals, $0 indices)
    - ATR-based position sizing
    - Partial take-profits
    - Trailing stops
    - Weekend/holiday gap handling

Instruments: XAUUSD (Gold), NQ (Nasdaq futures), EURUSD, GBPUSD, USDJPY
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TradeDirection(Enum):
    """Trade direction."""

    LONG = "long"
    SHORT = "short"


class ExitType(Enum):
    """Reason a trade was closed."""

    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    PARTIAL_TP = "partial_tp"
    TRAILING_STOP = "trailing_stop"
    STRATEGY_CLOSE = "strategy_close"
    END_OF_DATA = "end_of_data"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Signal:
    """A trading signal produced by a strategy.

    Attributes:
        timestamp: Candle timestamp when signal was generated.
        direction: ``TradeDirection.LONG`` or ``TradeDirection.SHORT``.
        symbol: Trading symbol (e.g. ``"XAUUSD"``).
        entry_price: Desired entry price (or ``None`` for market execution).
        stop_loss: Stop-loss price level.
        take_profits: Ordered list of take-profit levels. First is primary TP.
        partial_tp_levels: Optional list of fractions (e.g. ``[0.5, 0.25, 0.25]``)
            specifying how much to close at each TP level. Must sum to 1.0.
        trailing_stop: If ``True``, enable trailing stop after first TP hit.
        trailing_stop_distance: Trail distance in price terms (e.g. ATR).
        confidence: Signal confidence score 0.0-1.0 (for position sizing).
    """

    timestamp: datetime
    direction: TradeDirection
    symbol: str
    stop_loss: float
    take_profits: List[float] = field(default_factory=list)
    entry_price: Optional[float] = None
    partial_tp_levels: Optional[List[float]] = None
    trailing_stop: bool = False
    trailing_stop_distance: Optional[float] = None
    confidence: float = 1.0

    def __post_init__(self):
        if self.partial_tp_levels is None and self.take_profits:
            # Default: close all at first TP
            self.partial_tp_levels = [1.0]
        if self.partial_tp_levels and self.take_profits:
            total = sum(self.partial_tp_levels)
            if not np.isclose(total, 1.0, atol=1e-6):
                # Normalise to sum to 1.0
                self.partial_tp_levels = [x / total for x in self.partial_tp_levels]
            # Ensure same length as take_profits (truncate or extend)
            n_tp = len(self.take_profits)
            n_part = len(self.partial_tp_levels)
            if n_part < n_tp:
                # Extend with zero (remaining TP levels won't trigger partial close)
                self.partial_tp_levels = self.partial_tp_levels + [0.0] * (n_tp - n_part)
            elif n_part > n_tp:
                self.partial_tp_levels = self.partial_tp_levels[:n_tp]


@dataclass
class SimulatedTrade:
    """A fully-simulated trade with full execution details.

    Attributes:
        trade_id: Unique sequential identifier.
        signal: The original ``Signal`` that triggered this trade.
        entry_time: Actual entry timestamp.
        entry_price: Price after spread and slippage.
        exit_time: Exit timestamp (``None`` if still open).
        exit_price: Exit price after spread and slippage.
        position_size: Lot size (standard lots).
        direction: ``TradeDirection``.
        stop_loss: Effective SL price.
        take_profits: Remaining TP levels.
        partial_fills: List of dicts recording partial closes.
        trailing_stop_active: Whether trailing stop is currently active.
        trailing_stop_price: Current trailing stop price level.
        commission: Total commission paid.
        swap: Swap/rollover costs (simplified).
        pnl: Gross profit/loss in USD.
        net_pnl: PnL after commission and swap.
        exit_type: Reason for closure.
        max_drawdown: Maximum adverse excursion in USD.
        max_profit: Maximum favourable excursion in USD.
    """

    trade_id: int
    signal: Signal
    entry_time: datetime
    entry_price: float
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    position_size: float = 0.0
    direction: TradeDirection = TradeDirection.LONG
    stop_loss: float = 0.0
    take_profits: List[float] = field(default_factory=list)
    partial_fills: List[Dict[str, Any]] = field(default_factory=list)
    trailing_stop_active: bool = False
    trailing_stop_price: Optional[float] = None
    commission: float = 0.0
    swap: float = 0.0
    pnl: float = 0.0
    net_pnl: float = 0.0
    exit_type: Optional[ExitType] = None
    max_drawdown: float = 0.0
    max_profit: float = 0.0
    _remaining_size: float = field(default=0.0, repr=False)

    @property
    def is_open(self) -> bool:
        """Whether the trade is still open."""
        return self.exit_time is None

    @property
    def duration(self) -> Optional[timedelta]:
        """Trade duration."""
        if self.exit_time is None:
            return None
        return self.exit_time - self.entry_time

    def to_dict(self) -> Dict[str, Any]:
        """Serialize trade to dictionary."""
        return {
            "trade_id": self.trade_id,
            "symbol": self.signal.symbol,
            "direction": self.direction.value,
            "entry_time": self.entry_time.isoformat(),
            "entry_price": self.entry_price,
            "exit_time": self.exit_time.isoformat() if self.exit_time else None,
            "exit_price": self.exit_price,
            "position_size": self.position_size,
            "stop_loss": self.stop_loss,
            "take_profits": self.take_profits,
            "commission": self.commission,
            "swap": self.swap,
            "pnl": self.pnl,
            "net_pnl": self.net_pnl,
            "exit_type": self.exit_type.value if self.exit_type else None,
            "duration_minutes": (
                self.duration.total_seconds() / 60 if self.duration else None
            ),
            "max_drawdown": self.max_drawdown,
            "max_profit": self.max_profit,
        }


@dataclass
class PerformanceMetrics:
    """Comprehensive performance statistics for a backtest.

    All monetary values are in USD. Percentages are expressed as decimals
    (e.g. 0.15 means 15%%).
    """

    # Returns
    total_return: float = 0.0
    total_return_pct: float = 0.0
    annualized_return: float = 0.0
    annualized_volatility: float = 0.0

    # Risk-adjusted
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0

    # Drawdown
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_drawdown: float = 0.0

    # Trade statistics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    expected_value: float = 0.0

    # Advanced
    avg_trade_pnl: float = 0.0
    avg_trade_duration_min: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    consecutive_wins: int = 0
    consecutive_losses: int = 0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0

    # Prop-firm specific
    max_daily_loss: float = 0.0
    max_daily_loss_pct: float = 0.0
    profit_target_hit: bool = False
    profit_target_pct: float = 0.10  # 10% for most prop firms

    # Equity
    final_balance: float = 0.0
    peak_equity: float = 0.0
    min_equity: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Serialize metrics to dictionary."""
        return {
            k: v for k, v in self.__dict__.items()
        }

    def __str__(self) -> str:
        lines = [
            "=" * 55,
            "           BACKTEST PERFORMANCE REPORT",
            "=" * 55,
            f"  Total Return:        ${self.total_return:>12,.2f}  ({self.total_return_pct*100:+.2f}%)",
            f"  Annualized Return:   {self.annualized_return*100:>11.2f}%",
            f"  Annualized Vol:      {self.annualized_volatility*100:>11.2f}%",
            f"  Sharpe Ratio:        {self.sharpe_ratio:>12.2f}",
            f"  Sortino Ratio:       {self.sortino_ratio:>12.2f}",
            f"  Calmar Ratio:        {self.calmar_ratio:>12.2f}",
            f"  Max Drawdown:        ${self.max_drawdown:>12,.2f}  ({self.max_drawdown_pct*100:.2f}%)",
            f"  Avg Drawdown:        ${self.avg_drawdown:>12,.2f}",
            "",
            f"  Total Trades:        {self.total_trades:>12,d}",
            f"  Win Rate:            {self.win_rate*100:>11.2f}%",
            f"  Profit Factor:       {self.profit_factor:>12.2f}",
            f"  Expected Value:      ${self.expected_value:>12,.2f}",
            f"  Avg Trade PnL:       ${self.avg_trade_pnl:>12,.2f}",
            f"  Avg Win:             ${self.avg_win:>12,.2f}",
            f"  Avg Loss:            ${self.avg_loss:>12,.2f}",
            f"  Largest Win:         ${self.largest_win:>12,.2f}",
            f"  Largest Loss:        ${self.largest_loss:>12,.2f}",
            f"  Max Consec. Wins:    {self.max_consecutive_wins:>12,d}",
            f"  Max Consec. Losses:  {self.max_consecutive_losses:>12,d}",
            "",
            f"  Final Balance:       ${self.final_balance:>12,.2f}",
            f"  Peak Equity:         ${self.peak_equity:>12,.2f}",
            f"  Min Equity:          ${self.min_equity:>12,.2f}",
            f"  Max Daily Loss:      ${self.max_daily_loss:>12,.2f}",
            f"  Profit Target Hit:   {self.profit_target_hit!s:>12}",
            "=" * 55,
        ]
        return "\n".join(lines)


@dataclass
class BacktestConfig:
    """Configuration parameters for the backtest engine.

    Attributes:
        initial_balance: Starting account balance in USD.
        risk_per_trade: Fraction of balance risked per trade (e.g. 0.005 = 0.5%).
        commission_per_lot: Commission in USD per standard lot.
        spread_pips: Dict mapping symbol to spread in *price terms*.
        slippage_pips: Maximum slippage in pips (applied as random 0 to N).
        leverage: Dict mapping symbol to leverage ratio.
        use_atr_sizing: Whether to use ATR-based position sizing.
        atr_period: Lookback period for ATR calculation.
        atr_multiplier: SL distance = ATR × multiplier.
        partial_tp_enabled: Whether partial take-profits are allowed.
        trailing_stop_enabled: Whether trailing stops are enabled.
        funding_pips_rules: Whether to enforce prop-firm risk rules.
        max_daily_loss_pct: Maximum allowed daily loss (prop firm rule).
        profit_target_pct: Profit target to pass challenge.
    """

    initial_balance: float = 100_000.0
    risk_per_trade: float = 0.005          # 0.5%
    commission_per_lot: float = 5.0        # $5 per lot for FX & metals
    commission_indices: float = 0.0        # $0 per contract for indices
    spread_pips: Dict[str, float] = field(default_factory=lambda: {
        "XAUUSD": 0.40,      # $0.40 per ounce
        "NQ": 1.50,          # 1.5 points
        "EURUSD": 0.00015,   # 1.5 pips
        "GBPUSD": 0.00020,   # 2.0 pips
        "USDJPY": 0.015,     # 1.5 pips
    })
    slippage_pips: float = 0.5
    leverage: Dict[str, float] = field(default_factory=lambda: {
        "XAUUSD": 100.0,
        "NQ": 20.0,
        "EURUSD": 100.0,
        "GBPUSD": 100.0,
        "USDJPY": 100.0,
    })
    use_atr_sizing: bool = True
    atr_period: int = 14
    atr_multiplier: float = 1.5
    partial_tp_enabled: bool = True
    trailing_stop_enabled: bool = True
    funding_pips_rules: bool = True
    max_daily_loss_pct: float = 0.05       # 5% max daily loss
    profit_target_pct: float = 0.10        # 10% profit target
    max_trades_per_day: int = 10
    random_seed: Optional[int] = None


@dataclass
class BacktestResult:
    """Container for all results produced by a backtest run.

    Attributes:
        trades: List of all ``SimulatedTrade`` objects.
        equity_curve: DataFrame with equity over time.
        metrics: ``PerformanceMetrics`` summary.
        config: The ``BacktestConfig`` used.
        duration: Wall-clock duration of the backtest.
        symbol: Symbol that was backtested.
        timeframe: Timeframe used.
    """

    trades: List[SimulatedTrade]
    equity_curve: pd.DataFrame
    metrics: PerformanceMetrics
    config: BacktestConfig
    duration: timedelta
    symbol: str = ""
    timeframe: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize results to dictionary (for JSON export)."""
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "config": self.config.__dict__,
            "duration_seconds": self.duration.total_seconds(),
            "metrics": self.metrics.to_dict(),
            "total_trades": len(self.trades),
            "trades": [t.to_dict() for t in self.trades],
            "equity_curve_rows": len(self.equity_curve),
        }


# ---------------------------------------------------------------------------
# Strategy protocol (abstract base)
# ---------------------------------------------------------------------------


class Strategy:
    """Abstract base class for strategies compatible with BacktestEngine.

    Subclasses must override ``on_candle`` to produce signals.
    """

    def on_candle(
        self,
        df: pd.DataFrame,
        current_idx: int,
        open_trades: List[SimulatedTrade],
    ) -> List[Signal]:
        """Process a new candle and optionally emit trading signals.

        Args:
            df: Full DataFrame up to and including the current candle.
            current_idx: Integer index of the current (just-closed) candle.
            open_trades: List of currently open simulated trades.

        Returns:
            List of ``Signal`` objects. Empty list = no action.
        """
        return []

    def should_close(
        self,
        trade: SimulatedTrade,
        df: pd.DataFrame,
        current_idx: int,
    ) -> bool:
        """Return ``True`` if the strategy wants to close this trade.

        Called every candle for each open trade.
        """
        return False


# ---------------------------------------------------------------------------
# Backtest Engine
# ---------------------------------------------------------------------------


class BacktestEngine:
    """Event-driven backtest engine with realistic execution simulation.

    Iterates through historical candle data candle-by-candle, evaluates
    strategy signals, simulates market-order entries/exits with spread,
    slippage, and commission, and tracks equity for performance analysis.

    Example::

        config = BacktestConfig(initial_balance=100_000, risk_per_trade=0.01)
        engine = BacktestEngine(config)
        result = engine.run(my_strategy, df, symbol="XAUUSD", timeframe="H1")
        print(result.metrics)
    """

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.balance: float = config.initial_balance
        self.equity: float = config.initial_balance
        self.peak_equity: float = config.initial_balance
        self.trades: List[SimulatedTrade] = []
        self.equity_curve: List[Dict[str, Any]] = []
        self.open_trades: List[SimulatedTrade] = []
        self._trade_counter: int = 0
        self._current_day: Optional[datetime] = None
        self._daily_pnl: float = 0.0
        self._daily_trades: int = 0
        self._rng = np.random.default_rng(config.random_seed)

        logger.info(
            "BacktestEngine initialised | balance=$%.2f risk=%.2f%%",
            config.initial_balance,
            config.risk_per_trade * 100,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        strategy: Strategy,
        data: pd.DataFrame,
        symbol: str = "XAUUSD",
        timeframe: str = "H1",
    ) -> BacktestResult:
        """Run the backtest over historical data.

        Args:
            strategy: Strategy instance implementing ``on_candle``.
            data: DataFrame with columns ``time, open, high, low, close,
                tick_volume, spread``. Sorted ascending by time.
            symbol: Canonical trading symbol.
            timeframe: Internal timeframe string.

        Returns:
            ``BacktestResult`` with all trades, equity curve, and metrics.
        """
        import time

        t_start = time.monotonic()
        sym = symbol.upper()
        tf = timeframe.upper()

        logger.info(
            "Backtest START | symbol=%s timeframe=%s candles=%d",
            sym,
            tf,
            len(data),
        )

        if data.empty:
            raise ValueError("DataFrame is empty")

        required_cols = {"time", "open", "high", "low", "close"}
        missing = required_cols - set(data.columns)
        if missing:
            raise ValueError(f"DataFrame missing required columns: {missing}")

        df = data.copy().reset_index(drop=True)
        df["time"] = pd.to_datetime(df["time"], utc=True)

        # Pre-calculate ATR for position sizing
        if self.config.use_atr_sizing:
            df["atr"] = self._calculate_atr(df, self.config.atr_period)
        else:
            df["atr"] = (df["high"] - df["low"]).rolling(14).mean()

        df["atr"] = df["atr"].ffill().fillna(df["high"] - df["low"])

        # Reset state
        self.balance = self.config.initial_balance
        self.equity = self.config.initial_balance
        self.peak_equity = self.config.initial_balance
        self.trades = []
        self.equity_curve = []
        self.open_trades = []
        self._trade_counter = 0
        self._current_day = None
        self._daily_pnl = 0.0
        self._daily_trades = 0

        # --- Main event loop ---
        warmup = self.config.atr_period + 5
        for i in range(warmup, len(df)):
            candle = df.iloc[i]
            prev_candle = df.iloc[i - 1] if i > 0 else candle

            self._record_equity(candle)

            # Check for gaps (weekend/holiday)
            gap_detected = self._detect_gap(prev_candle, candle)
            if gap_detected:
                logger.debug("Gap detected at %s", candle["time"])

            # --- Manage open trades ---
            self._manage_open_trades(candle, df, i, strategy)

            # --- Check prop firm daily limits ---
            if self._hit_daily_limit(candle):
                continue  # Skip new trades today

            # --- Generate signals from strategy ---
            try:
                signals = strategy.on_candle(df, i, list(self.open_trades))
            except Exception as exc:
                logger.error("Strategy error at candle %d: %s", i, exc)
                signals = []

            for signal in signals:
                if signal.symbol.upper() != sym:
                    logger.warning(
                        "Signal symbol %s != backtest symbol %s — skipping",
                        signal.symbol,
                        sym,
                    )
                    continue

                trade = self._simulate_entry(signal, candle, df, i)
                if trade is not None:
                    self.open_trades.append(trade)
                    self._daily_trades += 1

        # --- Close remaining open trades at last candle ---
        last_candle = df.iloc[-1]
        for trade in list(self.open_trades):
            self._simulate_exit(trade, last_candle, ExitType.END_OF_DATA)

        # --- Build results ---
        equity_df = self._build_equity_curve_df()
        metrics = self._calculate_metrics(equity_df)

        duration = timedelta(seconds=time.monotonic() - t_start)

        result = BacktestResult(
            trades=self.trades,
            equity_curve=equity_df,
            metrics=metrics,
            config=self.config,
            duration=duration,
            symbol=sym,
            timeframe=tf,
        )

        logger.info(
            "Backtest COMPLETE | trades=%d return=$%.2f (%.2f%%) in %.1fs",
            metrics.total_trades,
            metrics.total_return,
            metrics.total_return_pct * 100,
            duration.total_seconds(),
        )
        return result

    # ------------------------------------------------------------------
    # Entry / Exit simulation
    # ------------------------------------------------------------------

    def _simulate_entry(
        self,
        signal: Signal,
        candle: pd.Series,
        df: pd.DataFrame,
        idx: int,
    ) -> Optional[SimulatedTrade]:
        """Simulate market-order entry with spread and slippage.

        Args:
            signal: The signal to execute.
            candle: Current (just-closed) candle.
            df: Full DataFrame for ATR lookup.
            idx: Current candle index.

        Returns:
            ``SimulatedTrade`` if entry succeeds, else ``None``.
        """
        sym = signal.symbol.upper()
        direction = signal.direction

        # --- Price ---
        spread = self._get_spread(sym)
        base_price = candle["close"]
        if signal.entry_price is not None:
            base_price = signal.entry_price

        # Spread: worse for trader
        entry_price = self._apply_spread(base_price, direction, spread)
        # Slippage: worse for trader
        slippage = self._generate_slippage(sym)
        if direction == TradeDirection.LONG:
            entry_price += slippage
        else:
            entry_price -= slippage

        # --- Stop loss ---
        atr = df.iloc[idx]["atr"] if "atr" in df.columns else 10.0
        stop_loss = signal.stop_loss
        if stop_loss is None or stop_loss <= 0:
            # Derive SL from ATR
            multiplier = self.config.atr_multiplier
            if direction == TradeDirection.LONG:
                stop_loss = entry_price - atr * multiplier
            else:
                stop_loss = entry_price + atr * multiplier

        stop_distance = abs(entry_price - stop_loss)
        if stop_distance == 0:
            logger.warning("Zero stop distance — skipping trade")
            return None

        # --- Position sizing ---
        position_size = self._calculate_position_size(stop_distance, sym)
        position_size *= signal.confidence  # Scale by confidence
        position_size = max(round(position_size, 2), 0.01)  # Min 0.01 lot

        # --- Commission ---
        commission = self._calculate_commission(position_size, sym)

        # Check sufficient balance
        margin_required = self._calculate_margin(position_size, sym)
        if self.balance < margin_required + commission:
            logger.warning(
                "Insufficient balance for trade | balance=$%.2f margin=$%.2f comm=$%.2f",
                self.balance,
                margin_required,
                commission,
            )
            return None

        self._trade_counter += 1

        # Trailing stop setup
        trail_dist = signal.trailing_stop_distance or atr * 1.0
        trail_price = None
        if signal.trailing_stop and self.config.trailing_stop_enabled:
            if direction == TradeDirection.LONG:
                trail_price = entry_price - trail_dist
            else:
                trail_price = entry_price + trail_dist

        trade = SimulatedTrade(
            trade_id=self._trade_counter,
            signal=signal,
            entry_time=candle["time"],
            entry_price=entry_price,
            position_size=position_size,
            direction=direction,
            stop_loss=stop_loss,
            take_profits=list(signal.take_profits),
            trailing_stop_active=signal.trailing_stop and self.config.trailing_stop_enabled,
            trailing_stop_price=trail_price,
            commission=commission,
            _remaining_size=position_size,
        )

        self.balance -= commission

        logger.debug(
            "ENTRY #%d | %s %s | price=%.5f size=%.2f SL=%.5f comm=$%.2f",
            trade.trade_id,
            sym,
            direction.value,
            entry_price,
            position_size,
            stop_loss,
            commission,
        )
        return trade

    def _simulate_exit(
        self,
        trade: SimulatedTrade,
        candle: pd.Series,
        exit_type: ExitType,
    ) -> float:
        """Simulate trade exit with spread and slippage.

        Args:
            trade: The trade to close.
            candle: Current candle for price reference.
            exit_type: Reason for exit.

        Returns:
            Net PnL of the trade.
        """
        sym = trade.signal.symbol.upper()
        direction = trade.direction

        # Determine exit base price
        if exit_type == ExitType.STOP_LOSS:
            base_price = trade.stop_loss
        elif exit_type in (ExitType.TAKE_PROFIT, ExitType.PARTIAL_TP):
            # Use first TP level or candle close
            base_price = trade.take_profits[0] if trade.take_profits else candle["close"]
        elif exit_type == ExitType.TRAILING_STOP:
            base_price = trade.trailing_stop_price if trade.trailing_stop_price else candle["close"]
        else:
            base_price = candle["close"]

        # Apply spread and slippage (always worse for exiting)
        spread = self._get_spread(sym)
        exit_price = self._apply_spread(base_price, direction, spread, exiting=True)
        slippage = self._generate_slippage(sym)
        if direction == TradeDirection.LONG:
            exit_price -= slippage
        else:
            exit_price += slippage

        trade.exit_time = candle["time"]
        trade.exit_price = exit_price
        trade.exit_type = exit_type

        # Calculate PnL
        pip_value = self._get_pip_value(sym)
        price_diff = exit_price - trade.entry_price

        if direction == TradeDirection.SHORT:
            price_diff = -price_diff

        # PnL in USD
        pnl = price_diff * trade.position_size * pip_value
        trade.pnl = pnl
        trade.net_pnl = pnl - trade.commission - trade.swap

        # Update balance
        self.balance += trade.net_pnl

        # Update equity tracking
        self.equity = self.balance
        self.peak_equity = max(self.peak_equity, self.equity)

        # Daily tracking
        self._daily_pnl += trade.net_pnl

        # Record closed trade
        if trade not in self.trades:
            self.trades.append(trade)

        logger.debug(
            "EXIT  #%d | %s | price=%.5f pnl=$%.2f net=$%.2f | %s",
            trade.trade_id,
            exit_type.value,
            exit_price,
            pnl,
            trade.net_pnl,
            trade.duration,
        )
        return trade.net_pnl

    def _manage_open_trades(
        self,
        candle: pd.Series,
        df: pd.DataFrame,
        idx: int,
        strategy: Strategy,
    ) -> None:
        """Check SL, TP, trailing stop, and strategy close for all open trades."""
        closed_ids = set()

        for trade in list(self.open_trades):
            if trade.trade_id in closed_ids:
                continue

            direction = trade.direction
            high = candle["high"]
            low = candle["low"]

            # --- Check stop loss ---
            sl_hit = False
            if direction == TradeDirection.LONG and low <= trade.stop_loss:
                sl_hit = True
            elif direction == TradeDirection.SHORT and high >= trade.stop_loss:
                sl_hit = True

            if sl_hit:
                self._simulate_exit(trade, candle, ExitType.STOP_LOSS)
                closed_ids.add(trade.trade_id)
                continue

            # --- Check take profits (partial or full) ---
            if trade.take_profits:
                tp = trade.take_profits[0]
                tp_hit = False
                if direction == TradeDirection.LONG and high >= tp:
                    tp_hit = True
                elif direction == TradeDirection.SHORT and low <= tp:
                    tp_hit = True

                if tp_hit:
                    partial_levels = trade.signal.partial_tp_levels
                    if (
                        partial_levels
                        and self.config.partial_tp_enabled
                        and len(partial_levels) > 1
                        and trade._remaining_size > 0
                    ):
                        # Partial close
                        self._execute_partial_tp(trade, candle, tp)
                    else:
                        # Full close at TP
                        self._simulate_exit(trade, candle, ExitType.TAKE_PROFIT)
                        closed_ids.add(trade.trade_id)
                    continue

            # --- Update trailing stop ---
            if trade.trailing_stop_active and trade.trailing_stop_price is not None:
                self._update_trailing_stop(trade, candle)

                # Check if trailing stop hit
                ts_hit = False
                if direction == TradeDirection.LONG and low <= trade.trailing_stop_price:
                    ts_hit = True
                elif direction == TradeDirection.SHORT and high >= trade.trailing_stop_price:
                    ts_hit = True

                if ts_hit:
                    self._simulate_exit(trade, candle, ExitType.TRAILING_STOP)
                    closed_ids.add(trade.trade_id)
                    continue

            # --- MAE/MFE tracking ---
            self._update_trade_stats(trade, candle)

            # --- Strategy close signal ---
            try:
                if strategy.should_close(trade, df, idx):
                    self._simulate_exit(trade, candle, ExitType.STRATEGY_CLOSE)
                    closed_ids.add(trade.trade_id)
                    continue
            except Exception as exc:
                logger.error("Strategy should_close error: %s", exc)

        # Remove closed trades
        self.open_trades = [t for t in self.open_trades if t.trade_id not in closed_ids]

    def _execute_partial_tp(
        self,
        trade: SimulatedTrade,
        candle: pd.Series,
        tp_price: float,
    ) -> None:
        """Execute a partial take-profit closure.

        Closes a fraction of the position at the TP level and updates
        remaining size and trailing stop.
        """
        partial_levels = trade.signal.partial_tp_levels
        tp_idx = len(trade.signal.take_profits) - len(trade.take_profits)

        if tp_idx >= len(partial_levels):
            # Full close if out of levels
            self._simulate_exit(trade, candle, ExitType.TAKE_PROFIT)
            return

        fraction = partial_levels[tp_idx]
        close_size = trade._remaining_size * fraction

        # Record partial fill
        pip_value = self._get_pip_value(trade.signal.symbol.upper())
        price_diff = tp_price - trade.entry_price
        if trade.direction == TradeDirection.SHORT:
            price_diff = -price_diff
        partial_pnl = price_diff * close_size * pip_value

        trade.partial_fills.append({
            "time": candle["time"].isoformat(),
            "price": tp_price,
            "fraction": fraction,
            "size_closed": close_size,
            "pnl": partial_pnl,
        })

        # Update remaining
        trade._remaining_size -= close_size
        trade.pnl += partial_pnl

        # Remove this TP level
        trade.take_profits = trade.take_profits[1:]

        # Activate trailing stop if configured
        if trade.trailing_stop and not trade.trailing_stop_active:
            trade.trailing_stop_active = True
            atr_dist = abs(tp_price - trade.entry_price) * 0.5
            if trade.direction == TradeDirection.LONG:
                trade.trailing_stop_price = tp_price - atr_dist
            else:
                trade.trailing_stop_price = tp_price + atr_dist

        logger.debug(
            "PARTIAL #%d | closed %.0f%% at %.5f | remaining=%.2f lots",
            trade.trade_id,
            fraction * 100,
            tp_price,
            trade._remaining_size,
        )

        # If no remaining position, fully close
        if trade._remaining_size <= 0.01:
            trade.position_size = sum(p["size_closed"] for p in trade.partial_fills)
            trade.exit_time = candle["time"]
            trade.exit_price = tp_price
            trade.exit_type = ExitType.TAKE_PROFIT
            trade.net_pnl = trade.pnl - trade.commission - trade.swap
            self.balance += trade.net_pnl
            self.trades.append(trade)
            self.equity = self.balance
            self.peak_equity = max(self.peak_equity, self.equity)

    def _update_trailing_stop(self, trade: SimulatedTrade, candle: pd.Series) -> None:
        """Update trailing stop price if price has moved favourably."""
        if not trade.trailing_stop_active or trade.trailing_stop_price is None:
            return

        direction = trade.direction
        trail_dist = trade.signal.trailing_stop_distance
        if trail_dist is None:
            # Estimate from entry-SL distance
            trail_dist = abs(trade.entry_price - trade.stop_loss) * 0.8

        if direction == TradeDirection.LONG:
            new_ts = candle["close"] - trail_dist
            if new_ts > trade.trailing_stop_price:
                trade.trailing_stop_price = new_ts
        else:
            new_ts = candle["close"] + trail_dist
            if new_ts < trade.trailing_stop_price:
                trade.trailing_stop_price = new_ts

    def _update_trade_stats(self, trade: SimulatedTrade, candle: pd.Series) -> None:
        """Update running MAE/MFE for an open trade."""
        direction = trade.direction
        pip_value = self._get_pip_value(trade.signal.symbol.upper())

        # Current unrealised PnL at candle close
        price_diff_close = candle["close"] - trade.entry_price
        if direction == TradeDirection.SHORT:
            price_diff_close = -price_diff_close
        unrealized = price_diff_close * trade._remaining_size * pip_value

        if unrealized < 0:
            trade.max_drawdown = min(trade.max_drawdown, unrealized)
        else:
            trade.max_profit = max(trade.max_profit, unrealized)

    # ------------------------------------------------------------------
    # Position sizing & pricing
    # ------------------------------------------------------------------

    def _calculate_position_size(self, stop_distance: float, symbol: str) -> float:
        """Calculate lot size based on risk_per_trade and stop distance.

        Formula::

            Position Size (lots) = (Balance * Risk%%) / (StopDistance * PipValue)

        Args:
            stop_distance: Stop-loss distance in price terms.
            symbol: Canonical symbol.

        Returns:
            Position size in standard lots.
        """
        if stop_distance <= 0:
            return 0.01  # Minimum size

        risk_amount = self.balance * self.config.risk_per_trade
        pip_value = self._get_pip_value(symbol)

        # Convert stop_distance to "pips" / points
        pip_size = self._get_pip_size(symbol)
        stop_pips = stop_distance / pip_size

        if pip_value <= 0 or stop_pips <= 0:
            return 0.01

        # Risk $ / (stop in pips * $ per pip per lot) = lots
        lots = risk_amount / (stop_pips * pip_value)
        return round(lots, 2)

    def _calculate_commission(self, position_size: float, symbol: str) -> float:
        """Calculate commission for a trade.

        FX & metals: $5 per standard lot (round-trip = $10).
        Indices (NQ): $0 per contract.

        Args:
            position_size: Position in standard lots.
            symbol: Canonical symbol.

        Returns:
            Commission in USD.
        """
        sym = symbol.upper()
        if sym == "NQ":
            return 0.0
        return self.config.commission_per_lot * position_size

    def _calculate_margin(self, position_size: float, symbol: str) -> float:
        """Calculate required margin for a position.

        Args:
            position_size: Position in standard lots.
            symbol: Canonical symbol.

        Returns:
            Margin requirement in USD.
        """
        sym = symbol.upper()
        leverage = self.config.leverage.get(sym, 100.0)

        # Notional value
        if sym in ("EURUSD", "GBPUSD"):
            notional = position_size * 100_000  # 100k per lot
        elif sym == "USDJPY":
            notional = position_size * 100_000
        elif sym == "XAUUSD":
            notional = position_size * 100 * 2000  # 100 oz × ~$2000/oz
        elif sym == "NQ":
            notional = position_size * 20 * 15_000  # $20/point × ~15k
        else:
            notional = position_size * 100_000

        return notional / leverage

    def _apply_spread(
        self,
        price: float,
        direction: TradeDirection,
        spread: float,
        exiting: bool = False,
    ) -> float:
        """Apply spread to price (always worse for the trader).

        Entry:  Buy at ask (higher), Sell at bid (lower)
        Exit:   Buy at bid (lower), Sell at ask (higher)

        Args:
            price: Base price.
            direction: Trade direction.
            spread: Spread in price terms.
            exiting: Whether this is an exit (reverses spread direction).

        Returns:
            Adjusted price.
        """
        half_spread = spread / 2.0
        if exiting:
            # Reverse: exiting a long = selling at bid (lower)
            if direction == TradeDirection.LONG:
                return price - half_spread
            else:
                return price + half_spread
        else:
            # Entry: buying at ask (higher), selling at bid (lower)
            if direction == TradeDirection.LONG:
                return price + half_spread
            else:
                return price - half_spread

    def _get_spread(self, symbol: str) -> float:
        """Get spread in price terms for a symbol.

        Returns:
            Spread as price difference.
        """
        return self.config.spread_pips.get(symbol.upper(), 0.0002)

    def _get_pip_size(self, symbol: str) -> float:
        """Get the size of 1 pip in price terms for a symbol.

        - XAUUSD: 0.01
        - NQ: 1.0 (point)
        - JPY pairs: 0.01
        - Other FX: 0.0001
        """
        sym = symbol.upper()
        if sym == "XAUUSD":
            return 0.01
        elif sym == "NQ":
            return 1.0
        elif sym == "USDJPY":
            return 0.01
        elif sym in ("EURUSD", "GBPUSD"):
            return 0.0001
        return 0.0001

    def _get_pip_value(self, symbol: str) -> float:
        """Get pip value in USD for 1 standard lot.

        Returns:
            USD value of 1 pip move for 1 standard lot.

        Notes:
            - XAUUSD: $1 per 0.01 move for 1 lot (100 oz)
            - EURUSD: $10 per pip (0.0001) for 1 lot (100k)
            - NQ: $20 per point for 1 contract
            - USDJPY: ~$6.67 per pip (depends on rate, simplified)
        """
        values = {
            "XAUUSD": 1.0,      # $1 per 0.01
            "NQ": 20.0,         # $20 per point
            "EURUSD": 10.0,     # $10 per 0.0001
            "GBPUSD": 10.0,     # $10 per 0.0001
            "USDJPY": 6.67,     # Approximate at 150.00
        }
        return values.get(symbol.upper(), 10.0)

    def _generate_slippage(self, symbol: str) -> float:
        """Generate random slippage in price terms.

        Returns random value between 0 and slippage_pips in price terms.

        Args:
            symbol: Canonical symbol.

        Returns:
            Slippage in price terms (always non-negative).
        """
        pip_size = self._get_pip_size(symbol)
        max_slippage_pips = self.config.slippage_pips
        # Random 0 to max (uniform distribution)
        slippage_pips = self._rng.uniform(0, max_slippage_pips)
        return slippage_pips * pip_size

    # ------------------------------------------------------------------
    # Gap & daily limit handling
    # ------------------------------------------------------------------

    def _detect_gap(self, prev: pd.Series, curr: pd.Series) -> bool:
        """Detect price gap between candles.

        A gap is detected if the current candle's low > previous high (up gap)
        or current high < previous low (down gap) by more than 2x the ATR.

        Args:
            prev: Previous candle.
            curr: Current candle.

        Returns:
            True if a significant gap is detected.
        """
        # Time gap check (more than 3x normal candle duration)
        time_diff = curr["time"] - prev["time"]
        normal_duration = timedelta(minutes=60)  # Default H1
        if time_diff > normal_duration * 3:
            return True

        # Price gap check
        price_gap_up = curr["low"] > prev["high"]
        price_gap_down = curr["high"] < prev["low"]

        return price_gap_up or price_gap_down

    def _hit_daily_limit(self, candle: pd.Series) -> bool:
        """Check if prop firm daily loss limit has been hit.

        Args:
            candle: Current candle (for day tracking).

        Returns:
            True if no new trades should be taken.
        """
        if not self.config.funding_pips_rules:
            return False

        current_day = candle["time"].replace(hour=0, minute=0, second=0, microsecond=0)

        if self._current_day != current_day:
            # New day — reset counters
            self._current_day = current_day
            self._daily_pnl = 0.0
            self._daily_trades = 0

        # Check max daily loss
        daily_loss_limit = -(self.config.initial_balance * self.config.max_daily_loss_pct)
        if self._daily_pnl <= daily_loss_limit:
            logger.warning(
                "Daily loss limit hit | pnl=$%.2f limit=$%.2f — no new trades",
                self._daily_pnl,
                daily_loss_limit,
            )
            return True

        # Check max trades per day
        if self._daily_trades >= self.config.max_trades_per_day:
            return True

        return False

    # ------------------------------------------------------------------
    # ATR calculation
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        """Calculate Average True Range.

        Args:
            df: DataFrame with ``high``, ``low``, ``close`` columns.
            period: ATR lookback period.

        Returns:
            Series of ATR values.
        """
        high = df["high"]
        low = df["low"]
        close = df["close"]

        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.ewm(span=period, adjust=False).mean()
        return atr

    # ------------------------------------------------------------------
    # Equity curve & metrics
    # ------------------------------------------------------------------

    def _record_equity(self, candle: pd.Series) -> None:
        """Record equity snapshot at a candle."""
        # Calculate unrealised PnL
        unrealized = 0.0
        for trade in self.open_trades:
            pip_value = self._get_pip_value(trade.signal.symbol.upper())
            price_diff = candle["close"] - trade.entry_price
            if trade.direction == TradeDirection.SHORT:
                price_diff = -price_diff
            unrealized += price_diff * trade._remaining_size * pip_value

        self.equity = self.balance + unrealized
        self.peak_equity = max(self.peak_equity, self.equity)

        self.equity_curve.append({
            "time": candle["time"],
            "balance": self.balance,
            "equity": self.equity,
            "peak_equity": self.peak_equity,
            "unrealized": unrealized,
            "open_trades": len(self.open_trades),
        })

    def _build_equity_curve_df(self) -> pd.DataFrame:
        """Convert equity curve list to DataFrame with aggregations."""
        if not self.equity_curve:
            return pd.DataFrame()

        df = pd.DataFrame(self.equity_curve)
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.sort_values("time").reset_index(drop=True)

        # Calculate drawdown
        df["drawdown"] = df["peak_equity"] - df["equity"]
        df["drawdown_pct"] = df["drawdown"] / df["peak_equity"]

        # Daily returns
        df["date"] = df["time"].dt.date
        daily = df.groupby("date")["equity"].last().pct_change().fillna(0)
        df["daily_return"] = df["date"].map(daily)

        return df

    def _calculate_metrics(self, equity_df: pd.DataFrame) -> PerformanceMetrics:
        """Calculate comprehensive performance metrics.

        Args:
            equity_df: Equity curve DataFrame.

        Returns:
            ``PerformanceMetrics`` with all statistics.
        """
        metrics = PerformanceMetrics()

        # --- Basic returns ---
        metrics.final_balance = self.balance
        metrics.peak_equity = self.peak_equity
        metrics.min_equity = equity_df["equity"].min() if not equity_df.empty else self.config.initial_balance

        metrics.total_return = self.balance - self.config.initial_balance
        metrics.total_return_pct = (
            metrics.total_return / self.config.initial_balance if self.config.initial_balance else 0
        )

        # --- Time-based metrics ---
        if not equity_df.empty:
            start_time = equity_df["time"].iloc[0]
            end_time = equity_df["time"].iloc[-1]
            years = max((end_time - start_time).total_seconds() / (365.25 * 24 * 3600), 1 / (365.25 * 24))

            metrics.annualized_return = (1 + metrics.total_return_pct) ** (1 / max(years, 0.001)) - 1

            # Daily returns for volatility
            daily_returns = equity_df.groupby(equity_df["time"].dt.date)["equity"].last().pct_change().dropna()
            if len(daily_returns) > 1:
                metrics.annualized_volatility = daily_returns.std() * np.sqrt(252)

                # Sharpe (assume 0% risk-free rate for simplicity)
                if metrics.annualized_volatility > 0:
                    metrics.sharpe_ratio = metrics.annualized_return / metrics.annualized_volatility

                # Sortino
                downside = daily_returns[daily_returns < 0]
                downside_std = downside.std() * np.sqrt(252) if len(downside) > 0 else 0
                if downside_std > 0:
                    metrics.sortino_ratio = metrics.annualized_return / downside_std

            # Max drawdown
            metrics.max_drawdown = equity_df["drawdown"].max()
            metrics.max_drawdown_pct = equity_df["drawdown_pct"].max()
            metrics.avg_drawdown = equity_df["drawdown"].mean()

            # Calmar
            if metrics.max_drawdown_pct > 0:
                metrics.calmar_ratio = metrics.annualized_return / metrics.max_drawdown_pct

            # Max daily loss
            daily_pnl = equity_df.groupby(equity_df["time"].dt.date)["equity"].last().diff().fillna(0)
            metrics.max_daily_loss = daily_pnl.min()
            metrics.max_daily_loss_pct = (
                metrics.max_daily_loss / self.config.initial_balance
                if self.config.initial_balance else 0
            )

        # --- Trade statistics ---
        closed_trades = [t for t in self.trades if t.exit_time is not None]
        metrics.total_trades = len(closed_trades)

        if metrics.total_trades == 0:
            return metrics

        wins = [t for t in closed_trades if t.net_pnl > 0]
        losses = [t for t in closed_trades if t.net_pnl <= 0]

        metrics.winning_trades = len(wins)
        metrics.losing_trades = len(losses)
        metrics.win_rate = len(wins) / metrics.total_trades if metrics.total_trades else 0

        metrics.avg_win = np.mean([t.net_pnl for t in wins]) if wins else 0
        metrics.avg_loss = np.mean([t.net_pnl for t in losses]) if losses else 0

        gross_profit = sum(t.net_pnl for t in wins)
        gross_loss = abs(sum(t.net_pnl for t in losses))
        metrics.profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        metrics.expected_value = (
            metrics.win_rate * metrics.avg_win
            + (1 - metrics.win_rate) * abs(metrics.avg_loss)
            if metrics.total_trades else 0
        )

        metrics.avg_trade_pnl = np.mean([t.net_pnl for t in closed_trades])
        metrics.largest_win = max((t.net_pnl for t in closed_trades), default=0)
        metrics.largest_loss = min((t.net_pnl for t in closed_trades), default=0)

        # Trade duration
        durations = []
        for t in closed_trades:
            if t.duration:
                durations.append(t.duration.total_seconds() / 60)
        metrics.avg_trade_duration_min = np.mean(durations) if durations else 0

        # Consecutive wins/losses
        streaks = []
        current_streak = 0
        current_type = None
        for t in sorted(closed_trades, key=lambda x: x.entry_time):
            is_win = t.net_pnl > 0
            if is_win == current_type:
                current_streak += 1
            else:
                if current_type is not None:
                    streaks.append((current_type, current_streak))
                current_type = is_win
                current_streak = 1
        if current_type is not None:
            streaks.append((current_type, current_streak))

        win_streaks = [s for w, s in streaks if w]
        loss_streaks = [s for w, s in streaks if not w]
        metrics.max_consecutive_wins = max(win_streaks, default=0)
        metrics.max_consecutive_losses = max(loss_streaks, default=0)

        # Prop firm
        metrics.profit_target_pct = self.config.profit_target_pct
        metrics.profit_target_hit = (
            metrics.total_return_pct >= self.config.profit_target_pct
        )

        return metrics


# ---------------------------------------------------------------------------
# Example / smoke-test strategy
# ---------------------------------------------------------------------------


class MovingAverageCrossoverStrategy(Strategy):
    """Simple MA crossover strategy for demonstration/testing.

    Goes long when fast MA crosses above slow MA, short on cross below.
    Uses ATR-based stops.
    """

    def __init__(
        self,
        fast_period: int = 10,
        slow_period: int = 30,
        atr_multiplier_sl: float = 1.5,
        atr_multiplier_tp: float = 3.0,
    ):
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.atr_multiplier_sl = atr_multiplier_sl
        self.atr_multiplier_tp = atr_multiplier_tp
        self.prev_state = None

    def on_candle(
        self,
        df: pd.DataFrame,
        current_idx: int,
        open_trades: List[SimulatedTrade],
    ) -> List[Signal]:
        if current_idx < max(self.slow_period, 50):
            return []

        # Ensure MAs are calculated
        if "fast_ma" not in df.columns:
            df["fast_ma"] = df["close"].ewm(span=self.fast_period, adjust=False).mean()
        if "slow_ma" not in df.columns:
            df["slow_ma"] = df["close"].ewm(span=self.slow_period, adjust=False).mean()

        # Current and previous state
        curr_fast = df.iloc[current_idx]["fast_ma"]
        curr_slow = df.iloc[current_idx]["slow_ma"]
        prev_fast = df.iloc[current_idx - 1]["fast_ma"]
        prev_slow = df.iloc[current_idx - 1]["slow_ma"]

        curr_state = "above" if curr_fast > curr_slow else "below"
        prev_state = "above" if prev_fast > prev_slow else "below"

        signals = []
        candle = df.iloc[current_idx]
        atr = candle.get("atr", candle["close"] * 0.01)
        symbol = "XAUUSD"  # Default; should be parametrised

        # Cross above: bullish
        if prev_state == "below" and curr_state == "above":
            sl = candle["close"] - atr * self.atr_multiplier_sl
            tp = candle["close"] + atr * self.atr_multiplier_tp
            signals.append(Signal(
                timestamp=candle["time"],
                direction=TradeDirection.LONG,
                symbol=symbol,
                stop_loss=sl,
                take_profits=[tp],
                trailing_stop=True,
                trailing_stop_distance=atr,
            ))

        # Cross below: bearish
        elif prev_state == "above" and curr_state == "below":
            sl = candle["close"] + atr * self.atr_multiplier_sl
            tp = candle["close"] - atr * self.atr_multiplier_tp
            signals.append(Signal(
                timestamp=candle["time"],
                direction=TradeDirection.SHORT,
                symbol=symbol,
                stop_loss=sl,
                take_profits=[tp],
                trailing_stop=True,
                trailing_stop_distance=atr,
            ))

        return signals

    def should_close(
        self,
        trade: SimulatedTrade,
        df: pd.DataFrame,
        current_idx: int,
    ) -> bool:
        """Close if MA re-crosses against position."""
        if current_idx < max(self.slow_period, 50):
            return False

        curr_fast = df.iloc[current_idx]["fast_ma"]
        curr_slow = df.iloc[current_idx]["slow_ma"]

        if trade.direction == TradeDirection.LONG and curr_fast < curr_slow:
            return True
        if trade.direction == TradeDirection.SHORT and curr_fast > curr_slow:
            return True
        return False


# ---------------------------------------------------------------------------
# Module-level smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    # Generate synthetic data
    from data_loader import generate_synthetic_data

    start_dt = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end_dt = datetime(2024, 3, 1, tzinfo=timezone.utc)

    df = generate_synthetic_data("XAUUSD", "H1", start_dt, end_dt, seed=42, trend=0.02)
    print(f"Generated {len(df)} candles")

    # Run backtest
    config = BacktestConfig(
        initial_balance=100_000,
        risk_per_trade=0.005,
        slippage_pips=0.3,
        random_seed=42,
    )
    engine = BacktestEngine(config)
    strategy = MovingAverageCrossoverStrategy(fast_period=10, slow_period=30)

    result = engine.run(strategy, df, symbol="XAUUSD", timeframe="H1")

    print("\n" + str(result.metrics))
    print(f"\nBacktest completed in {result.duration.total_seconds():.2f}s")
    print(f"Total trades executed: {len(result.trades)}")
