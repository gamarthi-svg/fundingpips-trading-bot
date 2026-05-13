"""
Performance metrics and analytics for prop firm trading backtester.

Calculates comprehensive performance statistics including prop-firm-specific
checks such as consistency score, daily loss limits, and risk of ruin.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from datetime import timedelta
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd
from scipy import stats

if TYPE_CHECKING:
    from .engine import BacktestEngine, BacktestConfig, SimulatedTrade

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: safe division
# ---------------------------------------------------------------------------
def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    """Return a / b, or *default* when b is zero or NaN."""
    if b == 0 or np.isnan(b) or np.isinf(b):
        return default
    return a / b


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class PerformanceMetrics:
    """All key performance metrics from a single backtest run."""

    # -- Returns -----------------------------------------------------------
    total_return: float = 0.0               # Total % return
    total_return_dollars: float = 0.0       # Total $ return
    annualized_return: float = 0.0          # CAGR

    # -- Risk --------------------------------------------------------------
    max_drawdown: float = 0.0               # Maximum drawdown % (negative)
    max_drawdown_dollars: float = 0.0       # Maximum drawdown $
    max_drawdown_duration: int = 0          # Max DD duration in calendar days

    # -- Ratios ------------------------------------------------------------
    sharpe_ratio: float = 0.0               # (return - risk_free) / std_dev
    sortino_ratio: float = 0.0              # (return - risk_free) / downside_std
    calmar_ratio: float = 0.0               # annual_return / |max_drawdown|
    profit_factor: float = 0.0              # gross_profit / gross_loss

    # -- Trade stats -------------------------------------------------------
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    breakeven_trades: int = 0
    win_rate: float = 0.0                   # %
    avg_win: float = 0.0                    # Average winning trade $
    avg_loss: float = 0.0                   # Average losing trade $
    avg_win_loss_ratio: float = 0.0         # avg_win / |avg_loss|
    largest_win: float = 0.0
    largest_loss: float = 0.0

    # -- Expectancy --------------------------------------------------------
    expectancy: float = 0.0                 # (win_rate * avg_win) - (loss_rate * avg_loss)
    expectancy_per_dollar_risked: float = 0.0

    # -- Consistency (prop-firm specific) ----------------------------------
    best_day_pct: float = 0.0               # Best day as % of total profit
    consistency_score: float = 0.0          # best_day / total_profit  (< 35 %)
    profitable_days: int = 0
    unprofitable_days: int = 0
    consecutive_wins: int = 0
    consecutive_losses: int = 0

    # -- Time --------------------------------------------------------------
    avg_trade_duration: timedelta = field(default_factory=lambda: timedelta(0))
    avg_time_in_market: float = 0.0         # % of time with open positions

    # -- Prop-firm specific ------------------------------------------------
    days_to_profit_target: int = 0          # Days to reach profit target
    risk_of_ruin: float = 0.0               # Probability of hitting max DD

    # -- Extra (populated by the analyser) ---------------------------------
    monthly_returns: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(), repr=False
    )
    drawdown_series: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(), repr=False
    )
    daily_pnl: pd.DataFrame = field(
        default_factory=lambda: pd.DataFrame(), repr=False
    )
    trade_returns: List[float] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict:
        """Serialise metrics to a plain dict (DataFrames → list/dict)."""
        d = asdict(self)
        # Convert non-serialisable objects
        d["avg_trade_duration"] = str(self.avg_trade_duration)
        d["monthly_returns"] = (
            self.monthly_returns.to_dict("records")
            if not self.monthly_returns.empty
            else []
        )
        d["drawdown_series"] = (
            self.drawdown_series.to_dict("records")
            if not self.drawdown_series.empty
            else []
        )
        d["daily_pnl"] = (
            self.daily_pnl.to_dict("records")
            if not self.daily_pnl.empty
            else []
        )
        d.pop("trade_returns", None)
        return d


# ---------------------------------------------------------------------------
# Performance Analyser
# ---------------------------------------------------------------------------
class PerformanceAnalyzer:
    """Calculate all performance metrics from backtest results."""

    def __init__(
        self,
        trades: List[Any],  # SimulatedTrade
        equity_curve: pd.DataFrame,
        initial_balance: float,
        config: Any,  # BacktestConfig
    ) -> None:
        self.trades: List[Any] = trades
        self.equity_curve: pd.DataFrame = equity_curve.copy()
        self.initial_balance: float = initial_balance
        self.config: Any = config

        # Ensure equity_curve has a DatetimeIndex
        if not isinstance(self.equity_curve.index, pd.DatetimeIndex):
            if "timestamp" in self.equity_curve.columns:
                self.equity_curve["timestamp"] = pd.to_datetime(
                    self.equity_curve["timestamp"]
                )
                self.equity_curve = self.equity_curve.set_index("timestamp")
            elif "date" in self.equity_curve.columns:
                self.equity_curve["date"] = pd.to_datetime(self.equity_curve["date"])
                self.equity_curve = self.equity_curve.set_index("date")

        # Ensure we have an 'equity' column
        if "equity" not in self.equity_curve.columns:
            if "balance" in self.equity_curve.columns:
                self.equity_curve = self.equity_curve.rename(
                    columns={"balance": "equity"}
                )
            elif "close" in self.equity_curve.columns:
                self.equity_curve = self.equity_curve.rename(
                    columns={"close": "equity"}
                )
            else:
                # Assume single column is equity
                self.equity_curve.columns = ["equity"]

        self._dd: Optional[pd.DataFrame] = None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def calculate_all(self) -> PerformanceMetrics:
        """Calculate the full set of performance metrics in one call."""
        logger.info("Calculating performance metrics …")
        m = PerformanceMetrics()

        # 1. Returns
        self._calc_returns(m)

        # 2. Drawdown
        self._calc_drawdown(m)

        # 3. Ratios
        m.sharpe_ratio = self.calculate_sharpe()
        m.sortino_ratio = self.calculate_sortino()
        m.calmar_ratio = self.calculate_calmar()
        m.profit_factor = self.calculate_profit_factor()

        # 4. Trade stats
        self._calc_trade_stats(m)

        # 5. Expectancy
        self._calc_expectancy(m)

        # 6. Consistency / daily PnL
        self._calc_consistency(m)

        # 7. Time metrics
        self._calc_time_metrics(m)

        # 8. Prop-firm checks
        m.risk_of_ruin = self.calculate_risk_of_ruin()

        # Attach auxiliary data
        m.drawdown_series = self.calculate_drawdown_series()
        m.monthly_returns = self.calculate_monthly_returns()
        m.daily_pnl = self.calculate_daily_pnl()
        m.trade_returns = [t.pnl for t in self.trades] if self.trades else []

        logger.info("Performance metrics calculation complete.")
        return m

    # ------------------------------------------------------------------ #
    # Returns
    # ------------------------------------------------------------------ #
    def _calc_returns(self, m: PerformanceMetrics) -> None:
        eq = self.equity_curve["equity"]
        if eq.empty:
            return
        start = eq.iloc[0]
        end = eq.iloc[-1]
        m.total_return_dollars = end - start
        m.total_return = _safe_div(m.total_return_dollars, start, 0.0) * 100

        # Annualised (CAGR)
        days = (eq.index[-1] - eq.index[0]).days
        if days > 0:
            years = days / 365.25
            m.annualized_return = (
                (end / start) ** (1 / years) - 1
            ) * 100
        else:
            m.annualized_return = m.total_return

    # ------------------------------------------------------------------ #
    # Drawdown
    # ------------------------------------------------------------------ #
    def calculate_drawdown_series(self) -> pd.DataFrame:
        """Return a DataFrame with timestamp, equity, peak, drawdown_pct."""
        eq = self.equity_curve["equity"]
        peak = eq.cummax()
        dd = (eq - peak) / peak * 100  # negative values
        return pd.DataFrame(
            {
                "equity": eq,
                "peak": peak,
                "drawdown_pct": dd,
            },
            index=eq.index,
        )

    def _calc_drawdown(self, m: PerformanceMetrics) -> None:
        dd_df = self.calculate_drawdown_series()
        self._dd = dd_df
        m.max_drawdown = dd_df["drawdown_pct"].min()  # most negative
        peak_at_dd = dd_df["peak"][dd_df["drawdown_pct"] == m.max_drawdown].iloc[0]
        m.max_drawdown_dollars = m.max_drawdown / 100.0 * peak_at_dd

        # Duration: longest streak where equity < running peak
        below_peak = dd_df["drawdown_pct"] < 0
        if below_peak.any():
            # Label contiguous groups
            groups = (below_peak != below_peak.shift()).cumsum()
            durations = below_peak.groupby(groups).apply(
                lambda s: (s.index[-1] - s.index[0]).days + 1 if s.any() else 0
            )
            m.max_drawdown_duration = int(durations.max())
        else:
            m.max_drawdown_duration = 0

    # ------------------------------------------------------------------ #
    # Ratios
    # ------------------------------------------------------------------ #
    def calculate_sharpe(self, risk_free_rate: float = 0.02) -> float:
        """Annualised Sharpe ratio from daily returns."""
        eq = self.equity_curve["equity"]
        if len(eq) < 2:
            return 0.0
        daily_ret = eq.pct_change().dropna()
        if daily_ret.std() == 0 or daily_ret.empty:
            return 0.0
        excess = daily_ret - risk_free_rate / 252
        sharpe = excess.mean() / daily_ret.std() * np.sqrt(252)
        return float(sharpe)

    def calculate_sortino(self, risk_free_rate: float = 0.02) -> float:
        """Sortino ratio using downside deviation only."""
        eq = self.equity_curve["equity"]
        if len(eq) < 2:
            return 0.0
        daily_ret = eq.pct_change().dropna()
        downside = daily_ret[daily_ret < 0]
        if downside.empty or downside.std() == 0:
            return 0.0
        excess = daily_ret.mean() - risk_free_rate / 252
        sortino = excess / downside.std() * np.sqrt(252)
        return float(sortino)

    def calculate_calmar(self) -> float:
        """Calmar ratio = annualised return / |max drawdown|."""
        eq = self.equity_curve["equity"]
        if len(eq) < 2:
            return 0.0
        dd = self.calculate_drawdown_series()
        max_dd = abs(dd["drawdown_pct"].min())
        start, end = eq.iloc[0], eq.iloc[-1]
        days = (eq.index[-1] - eq.index[0]).days
        if days <= 0 or max_dd == 0 or start <= 0:
            return 0.0
        cagr = ((end / start) ** (365.25 / days) - 1) * 100
        return cagr / max_dd

    def calculate_profit_factor(self) -> float:
        """Gross profit / gross loss."""
        if not self.trades:
            return 0.0
        gross_profit = sum(t.pnl for t in self.trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in self.trades if t.pnl < 0))
        return _safe_div(gross_profit, gross_loss, 0.0)

    # ------------------------------------------------------------------ #
    # Trade statistics
    # ------------------------------------------------------------------ #
    def _calc_trade_stats(self, m: PerformanceMetrics) -> None:
        if not self.trades:
            return
        pnls = np.array([t.pnl for t in self.trades])
        m.total_trades = len(pnls)
        m.winning_trades = int(np.sum(pnls > 0))
        m.losing_trades = int(np.sum(pnls < 0))
        m.breakeven_trades = int(np.sum(pnls == 0))
        m.win_rate = m.winning_trades / m.total_trades * 100 if m.total_trades else 0.0

        wins = pnls[pnls > 0]
        losses = pnls[pnls < 0]
        m.avg_win = float(wins.mean()) if len(wins) else 0.0
        m.avg_loss = float(losses.mean()) if len(losses) else 0.0
        m.avg_win_loss_ratio = _safe_div(m.avg_win, abs(m.avg_loss), 0.0)
        m.largest_win = float(wins.max()) if len(wins) else 0.0
        m.largest_loss = float(losses.min()) if len(losses) else 0.0

        # Consecutive streaks
        signs = np.sign(pnls)
        m.consecutive_wins = self._max_consecutive(signs, 1)
        m.consecutive_losses = self._max_consecutive(signs, -1)

    @staticmethod
    def _max_consecutive(signs: np.ndarray, target: int) -> int:
        """Maximum consecutive occurrences of *target* in *signs*."""
        if signs.size == 0:
            return 0
        max_streak = cur = 0
        for s in signs:
            if s == target:
                cur += 1
                max_streak = max(max_streak, cur)
            else:
                cur = 0
        return max_streak

    # ------------------------------------------------------------------ #
    # Expectancy
    # ------------------------------------------------------------------ #
    def _calc_expectancy(self, m: PerformanceMetrics) -> None:
        if not self.trades or m.total_trades == 0:
            return
        loss_rate = 1 - (m.win_rate / 100.0)
        m.expectancy = (m.win_rate / 100.0) * m.avg_win + loss_rate * m.avg_loss
        avg_risk = abs(m.avg_loss) if m.avg_loss != 0 else 1.0
        m.expectancy_per_dollar_risked = _safe_div(m.expectancy, avg_risk, 0.0)

    # ------------------------------------------------------------------ #
    # Consistency (prop-firm)
    # ------------------------------------------------------------------ #
    def calculate_daily_pnl(self) -> pd.DataFrame:
        """Daily P&L for prop-firm consistency checks."""
        eq = self.equity_curve["equity"]
        if eq.empty:
            return pd.DataFrame()
        daily = eq.resample("D").last().dropna()
        pnl = daily.diff().fillna(daily.iloc[0] - self.initial_balance)
        return pd.DataFrame({"equity": daily, "daily_pnl": pnl}, index=daily.index)

    def calculate_monthly_returns(self) -> pd.DataFrame:
        """Monthly return table for consistency analysis."""
        eq = self.equity_curve["equity"]
        if eq.empty:
            return pd.DataFrame()
        monthly = eq.resample("ME").last().dropna()
        ret = monthly.pct_change().fillna(
            (monthly.iloc[0] - self.initial_balance) / self.initial_balance
        )
        return pd.DataFrame(
            {
                "end_equity": monthly,
                "monthly_return": ret * 100,
                "monthly_pnl": monthly.diff().fillna(
                    monthly.iloc[0] - self.initial_balance
                ),
            },
            index=monthly.index,
        )

    def _calc_consistency(self, m: PerformanceMetrics) -> None:
        daily = self.calculate_daily_pnl()
        if daily.empty:
            return
        pnl = daily["daily_pnl"]
        total_profit = pnl[pnl > 0].sum()
        total_loss = abs(pnl[pnl < 0].sum())
        m.profitable_days = int((pnl > 0).sum())
        m.unprofitable_days = int((pnl < 0).sum())

        if total_profit > 0:
            best_day = pnl.max()
            m.best_day_pct = best_day / total_profit * 100
            m.consistency_score = m.best_day_pct
        else:
            m.best_day_pct = 0.0
            m.consistency_score = 0.0

    # ------------------------------------------------------------------ #
    # Time metrics
    # ------------------------------------------------------------------ #
    def _calc_time_metrics(self, m: PerformanceMetrics) -> None:
        # Average trade duration
        durations = [
            getattr(t, "duration", None)
            for t in self.trades
            if getattr(t, "duration", None) is not None
        ]
        if durations:
            m.avg_trade_duration = sum(durations, timedelta(0)) / len(durations)

        # Time in market
        eq = self.equity_curve["equity"]
        if len(eq) > 1:
            # Assume equity curve is sampled uniformly (e.g. per bar)
            total_bars = len(eq)
            # crude proxy: bars where equity differs from previous bar
            bars_in_market = int((eq.diff().fillna(0) != 0).sum())
            m.avg_time_in_market = bars_in_market / total_bars * 100

    # ------------------------------------------------------------------ #
    # Risk of ruin
    # ------------------------------------------------------------------ #
    def calculate_risk_of_ruin(self, max_risk: float = 0.10) -> float:
        """
        Probability of hitting the maximum drawdown (ruin).

        Uses a simplified formula derived from a random-walk model:
            R = ((1 - W) / W) ^ (C / R)
        where W = win-rate (decimal), C = max consecutive losses before ruin,
        R = max risk fraction per trade.
        """
        if not self.trades:
            return 1.0

        pnls = np.array([t.pnl for t in self.trades])
        wins = pnls[pnls > 0]
        losses = pnls[pnls < 0]
        if len(wins) == 0:
            return 1.0
        if len(losses) == 0:
            return 0.0

        win_rate = len(wins) / len(pnls)
        avg_loss = abs(float(losses.mean()))
        if avg_loss == 0:
            return 0.0

        # Consecutive losses before hitting max_risk of equity
        initial = self.initial_balance
        c = int(max_risk * initial / avg_loss)
        if c <= 0:
            return 1.0

        if win_rate >= 0.9999:
            return 0.0

        # Classic formula: R = ((1-W)/W)^C
        ratio = (1 - win_rate) / win_rate
        if ratio <= 0:
            return 0.0
        try:
            ruin = ratio**c
        except OverflowError:
            ruin = 1.0
        return float(min(ruin, 1.0))

    # ------------------------------------------------------------------ #
    # Prop-firm checks
    # ------------------------------------------------------------------ #
    def passes_prop_firm_checks(
        self, limits: Optional[Dict[str, float]] = None
    ) -> Dict[str, bool]:
        """
        Check whether the backtest would pass typical prop-firm rules.

        Default limits mirror common instant-funding prop-firm constraints:
            max_drawdown_pct   : 10.0
            daily_loss_limit   : 5.0
            consistency_score  : 35.0
            min_trading_days   : 4
            min_total_return   : 8.0   (profit target)
        """
        if limits is None:
            limits = {
                "max_drawdown_pct": 10.0,
                "daily_loss_limit": 5.0,
                "consistency_score": 35.0,
                "min_trading_days": 4,
                "min_total_return": 8.0,
            }

        # Need metrics first
        m = self.calculate_all()

        daily = m.daily_pnl
        daily_limit_breaches = 0
        if not daily.empty and "daily_pnl" in daily.columns:
            dd_pct = daily["daily_pnl"] / self.initial_balance * 100
            daily_limit_breaches = int((dd_pct < -limits["daily_loss_limit"]).sum())

        results = {
            "pass_max_drawdown": abs(m.max_drawdown) <= limits["max_drawdown_pct"],
            "pass_daily_loss_limit": daily_limit_breaches == 0,
            "pass_consistency": m.consistency_score <= limits["consistency_score"],
            "pass_min_trading_days": m.profitable_days + m.unprofitable_days
            >= limits["min_trading_days"],
            "pass_profit_target": m.total_return >= limits["min_total_return"],
            "daily_limit_breaches": daily_limit_breaches,
            "consistency_score": round(m.consistency_score, 2),
            "max_drawdown_pct": round(m.max_drawdown, 2),
        }
        results["overall_pass"] = all(
            v for k, v in results.items() if k.startswith("pass_")
        )
        return results

    def to_dict(self) -> dict:
        """Calculate and export all metrics as a serialisable dict."""
        return self.calculate_all().to_dict()


# ---------------------------------------------------------------------------
# Monte-Carlo helpers
# ---------------------------------------------------------------------------
def monte_carlo_simulation(
    trade_returns: np.ndarray,
    n_simulations: int = 10_000,
    initial_balance: float = 100_000.0,
    risk_per_trade: float = 0.01,
) -> Dict[str, float]:
    """
    Run a simple Monte-Carlo simulation over *trade_returns*.

    Returns a dict with median max-drawdown, 95 %-tile max-drawdown,
    median final equity, and probability of ruin (50 % DD).
    """
    if trade_returns.size == 0:
        return {}

    max_dds = np.zeros(n_simulations)
    final_equities = np.zeros(n_simulations)
    ruin_count = 0

    for i in range(n_simulations):
        np.random.shuffle(trade_returns)
        equity = initial_balance
        peak = equity
        max_dd = 0.0
        for ret in trade_returns:
            equity += ret
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd
            if equity <= initial_balance * 0.5:
                ruin_count += 1
                break
        max_dds[i] = max_dd
        final_equities[i] = equity

    return {
        "median_max_dd_pct": float(np.median(max_dds) * 100),
        "p95_max_dd_pct": float(np.percentile(max_dds, 95) * 100),
        "median_final_equity": float(np.median(final_equities)),
        "prob_ruin_50pct": ruin_count / n_simulations,
        "n_simulations": n_simulations,
    }


# ---------------------------------------------------------------------------
# Reporting helper
# ---------------------------------------------------------------------------
def format_metrics_report(metrics: PerformanceMetrics) -> str:
    """Pretty-print a PerformanceMetrics instance."""
    lines = [
        "=" * 60,
        "PERFORMANCE REPORT",
        "=" * 60,
        f"{'Total Return:':<30} {metrics.total_return:>10.2f}%  (${metrics.total_return_dollars:,.2f})",
        f"{'Annualized Return (CAGR):':<30} {metrics.annualized_return:>10.2f}%",
        "-" * 60,
        f"{'Max Drawdown:':<30} {metrics.max_drawdown:>10.2f}%  (${metrics.max_drawdown_dollars:,.2f})",
        f"{'Max DD Duration:':<30} {metrics.max_drawdown_duration:>10d} days",
        "-" * 60,
        f"{'Sharpe Ratio:':<30} {metrics.sharpe_ratio:>10.2f}",
        f"{'Sortino Ratio:':<30} {metrics.sortino_ratio:>10.2f}",
        f"{'Calmar Ratio:':<30} {metrics.calmar_ratio:>10.2f}",
        f"{'Profit Factor:':<30} {metrics.profit_factor:>10.2f}",
        "-" * 60,
        f"{'Total Trades:':<30} {metrics.total_trades:>10d}",
        f"{'Win Rate:':<30} {metrics.win_rate:>10.2f}%  ({metrics.winning_trades}W / {metrics.losing_trades}L)",
        f"{'Avg Win / Avg Loss:':<30} {metrics.avg_win:>10.2f} / {metrics.avg_loss:>10.2f}",
        f"{'Win/Loss Ratio:':<30} {metrics.avg_win_loss_ratio:>10.2f}",
        f"{'Largest Win:':<30} ${metrics.largest_win:>10,.2f}",
        f"{'Largest Loss:':<30} ${metrics.largest_loss:>10,.2f}",
        "-" * 60,
        f"{'Expectancy:':<30} ${metrics.expectancy:>10.2f}",
        f"{'Expectancy/$Risked:':<30} {metrics.expectancy_per_dollar_risked:>10.4f}",
        "-" * 60,
        f"{'Consistency Score:':<30} {metrics.consistency_score:>10.2f}%  (limit: 35%)",
        f"{'Profitable Days:':<30} {metrics.profitable_days:>10d}",
        f"{'Consecutive Wins:':<30} {metrics.consecutive_wins:>10d}",
        f"{'Consecutive Losses:':<30} {metrics.consecutive_losses:>10d}",
        "-" * 60,
        f"{'Risk of Ruin:':<30} {metrics.risk_of_ruin:>10.4f}",
        f"{'Avg Trade Duration:':<30} {str(metrics.avg_trade_duration):>10s}",
        "=" * 60,
    ]
    return "\n".join(lines)
