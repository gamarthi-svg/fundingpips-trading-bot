"""
Monte Carlo stress testing for prop firm trading backtester.

Runs thousands of simulations by reshuffling trade sequences to determine
the statistical distribution of possible outcomes, including probabilities
of passing prop firm evaluations and hitting drawdown limits.
"""

from __future__ import annotations

import base64
import io
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SimulatedTrade:
    """Minimal trade record for Monte Carlo input."""

    pnl: float
    direction: str = "long"  # "long" | "short"
    entry_time: Optional[str] = None
    exit_time: Optional[str] = None
    instrument: str = ""


@dataclass
class SimulationResult:
    """Result of a single Monte Carlo simulation run."""

    final_equity: float
    max_drawdown: float
    total_return: float
    hit_target: bool
    hit_max_dd: bool
    n_trades: int
    path: np.ndarray
    days_to_target: Optional[float] = None
    days_to_fail: Optional[float] = None
    max_daily_loss_hit: bool = False


@dataclass
class MonteCarloResult:
    """Aggregated results from all Monte Carlo simulations."""

    n_simulations: int
    pass_rate: float  # % that hit target before max DD
    fail_rate: float  # % that hit max DD first
    still_running: float  # % still running (neither)

    median_return: float
    mean_return: float
    worst_case: float  # 5th percentile
    best_case: float  # 95th percentile

    median_max_dd: float
    mean_max_dd: float
    max_dd_95th: float
    max_dd_99th: float

    median_days_to_target: float
    median_days_to_fail: float

    confidence_interval: Tuple[float, float]
    confidence_interval_99: Tuple[float, float]

    # Prop firm specific pass probabilities
    prob_pass_2step_p1: float  # Phase 1: 8% profit target, 10% max DD
    prob_pass_2step_p2: float  # Phase 2: 5% profit target, 10% max DD
    prob_pass_1step: float  # 1-Step: 10% profit target, 10% max DD
    prob_pass_pro: float  # Pro: 6% profit target, 5% max DD
    prob_pass_ftmo_p1: float  # FTMO Phase 1: 10% profit, 10% max DD
    prob_pass_ftmo_p2: float  # FTMO Phase 2: 5% profit, 10% max DD

    # Distributions
    final_returns: np.ndarray = field(repr=False)
    max_drawdowns: np.ndarray = field(repr=False)
    simulations: Optional[List[SimulationResult]] = field(
        default=None, repr=False
    )

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "n_simulations": self.n_simulations,
            "pass_rate": round(self.pass_rate, 4),
            "fail_rate": round(self.fail_rate, 4),
            "still_running": round(self.still_running, 4),
            "median_return": round(self.median_return, 4),
            "mean_return": round(self.mean_return, 4),
            "worst_case": round(self.worst_case, 4),
            "best_case": round(self.best_case, 4),
            "median_max_dd": round(self.median_max_dd, 4),
            "mean_max_dd": round(self.mean_max_dd, 4),
            "max_dd_95th": round(self.max_dd_95th, 4),
            "max_dd_99th": round(self.max_dd_99th, 4),
            "median_days_to_target": (
                round(self.median_days_to_target, 1)
                if self.median_days_to_target is not None
                else None
            ),
            "median_days_to_fail": (
                round(self.median_days_to_fail, 1)
                if self.median_days_to_fail is not None
                else None
            ),
            "confidence_interval": (
                round(self.confidence_interval[0], 4),
                round(self.confidence_interval[1], 4),
            ),
            "confidence_interval_99": (
                round(self.confidence_interval_99[0], 4),
                round(self.confidence_interval_99[1], 4),
            ),
            "prop_firm_probabilities": {
                "prob_pass_2step_p1": round(self.prob_pass_2step_p1, 4),
                "prob_pass_2step_p2": round(self.prob_pass_2step_p2, 4),
                "prob_pass_1step": round(self.prob_pass_1step, 4),
                "prob_pass_pro": round(self.prob_pass_pro, 4),
                "prob_pass_ftmo_p1": round(self.prob_pass_ftmo_p1, 4),
                "prob_pass_ftmo_p2": round(self.prob_pass_ftmo_p2, 4),
            },
        }


# ---------------------------------------------------------------------------
# Core simulator
# ---------------------------------------------------------------------------

class MonteCarloSimulator:
    """
    Runs 10,000+ Monte Carlo simulations by reshuffling trade sequences
    to determine the statistical distribution of possible outcomes.

    Key outputs:
    - Probability of passing prop firm evaluation
    - Probability of hitting max drawdown
    - Distribution of final returns
    - Confidence intervals for all metrics
    """

    def __init__(
        self,
        trades: List[SimulatedTrade],
        initial_balance: float = 100_000.0,
    ):
        if not trades:
            raise ValueError(" trades list cannot be empty")
        self.trades = trades
        self.initial_balance = float(initial_balance)
        self.rng = np.random.default_rng(seed=42)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        n_simulations: int = 10_000,
        max_drawdown_limit: float = 0.10,
        profit_target: float = 0.08,
        daily_loss_limit: float = 0.05,
        trades_per_sim: Optional[int] = None,
        avg_trades_per_day: float = 3.0,
    ) -> MonteCarloResult:
        """
        Run Monte Carlo simulation.

        Parameters
        ----------
        n_simulations : int
            Number of Monte Carlo runs (default 10,000).
        max_drawdown_limit : float
            Max allowed drawdown as fraction (e.g. 0.10 = 10%).
        profit_target : float
            Profit target as fraction (e.g. 0.08 = 8%).
        daily_loss_limit : float
            Daily loss limit as fraction (e.g. 0.05 = 5%).
        trades_per_sim : int, optional
            Number of trades per simulation. Defaults to len(self.trades).
        avg_trades_per_day : float
            Average trades per day for timeline estimation.

        Returns
        -------
        MonteCarloResult
            Aggregated statistical results from all simulations.
        """
        if n_simulations < 100:
            raise ValueError("n_simulations must be >= 100")
        if max_drawdown_limit <= 0 or profit_target <= 0:
            raise ValueError("limits and targets must be positive")

        n_trades = trades_per_sim or len(self.trades)
        trade_returns = np.array([t.pnl for t in self.trades], dtype=np.float64)

        logger.info(
            "Starting Monte Carlo: %d simulations, %d trades each, "
            "target=%.1f%%, max_dd=%.1f%%",
            n_simulations,
            n_trades,
            profit_target * 100,
            max_drawdown_limit * 100,
        )

        simulations: List[SimulationResult] = []
        for i in range(n_simulations):
            if i % 2_000 == 0 and i > 0:
                logger.info("  ... completed %d simulations", i)
            sim = self._simulate_one(
                n_trades=n_trades,
                trade_returns=trade_returns,
                max_drawdown_limit=max_drawdown_limit,
                profit_target=profit_target,
                daily_loss_limit=daily_loss_limit,
                avg_trades_per_day=avg_trades_per_day,
            )
            simulations.append(sim)

        result = self._aggregate_results(
            simulations=simulations,
            n_simulations=n_simulations,
            avg_trades_per_day=avg_trades_per_day,
        )
        result.simulations = simulations

        logger.info(
            "Monte Carlo complete: pass_rate=%.2f%%, median_return=%.2f%%",
            result.pass_rate * 100,
            result.median_return * 100,
        )
        return result

    def run_prop_firm_analysis(
        self,
        n_simulations: int = 10_000,
        avg_trades_per_day: float = 3.0,
    ) -> Dict[str, MonteCarloResult]:
        """
        Run Monte Carlo for multiple prop firm challenge configurations.

        Returns a dictionary keyed by challenge type, each containing
        a full MonteCarloResult.
        """
        configs = {
            "2step_p1": {"target": 0.08, "max_dd": 0.10, "label": "2-Step Phase 1"},
            "2step_p2": {"target": 0.05, "max_dd": 0.10, "label": "2-Step Phase 2"},
            "1step": {"target": 0.10, "max_dd": 0.10, "label": "1-Step"},
            "pro": {"target": 0.06, "max_dd": 0.05, "label": "Pro"},
            "ftmo_p1": {"target": 0.10, "max_dd": 0.10, "label": "FTMO Phase 1"},
            "ftmo_p2": {"target": 0.05, "max_dd": 0.10, "label": "FTMO Phase 2"},
        }

        results: Dict[str, MonteCarloResult] = {}
        for key, cfg in configs.items():
            logger.info("Running prop firm analysis: %s", cfg["label"])
            results[key] = self.run(
                n_simulations=n_simulations,
                max_drawdown_limit=cfg["max_dd"],
                profit_target=cfg["target"],
                avg_trades_per_day=avg_trades_per_day,
            )
        return results

    def calculate_pass_rate(
        self,
        results: List[SimulationResult],
        target: float,
        max_dd: float,
    ) -> float:
        """
        Calculate % of simulations that hit profit target before max DD.

        A "pass" means the equity curve reaches (initial * (1 + target))
        before it drops to (initial * (1 - max_dd)).
        """
        target_equity = self.initial_balance * (1.0 + target)
        dd_equity = self.initial_balance * (1.0 - max_dd)

        passes = 0
        total = len(results)
        if total == 0:
            return 0.0

        for sim in results:
            path = sim.path
            # Find first occurrence of either condition
            hit_target = np.any(path >= target_equity)
            hit_dd = np.any(path <= dd_equity)

            if hit_target and hit_dd:
                # Whichever happened first
                idx_target = np.argmax(path >= target_equity)
                idx_dd = np.argmax(path <= dd_equity)
                if idx_target < idx_dd:
                    passes += 1
            elif hit_target:
                passes += 1
            # else: hit DD only or neither = fail

        return passes / total

    def calculate_confidence_intervals(
        self,
        values: np.ndarray,
        confidence: float = 0.95,
    ) -> Tuple[float, float]:
        """
        Calculate percentile-based confidence interval.

        Uses the percentile method (non-parametric) which is robust
        to non-normal distributions common in trading returns.
        """
        if len(values) == 0:
            return (0.0, 0.0)
        alpha = 1.0 - confidence
        lower = float(np.percentile(values, alpha / 2 * 100))
        upper = float(np.percentile(values, (1.0 - alpha / 2) * 100))
        return (lower, upper)

    def plot_distribution(
        self,
        final_returns: np.ndarray,
        save_path: Optional[str] = None,
        title: str = "Monte Carlo: Final Return Distribution",
    ) -> Optional[str]:
        """
        Generate histogram of final returns with key percentiles marked.

        Returns base64-encoded PNG if save_path is None, else saves to file.
        """
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            logger.warning("matplotlib not available; skipping plot")
            return None

        fig, ax = plt.subplots(figsize=(10, 6))

        # Histogram
        ax.hist(
            final_returns * 100,
            bins=80,
            color="#3b82f6",
            edgecolor="#1e3a5f",
            alpha=0.75,
            density=True,
        )

        # Percentile lines
        median = np.median(final_returns) * 100
        p5 = np.percentile(final_returns, 5) * 100
        p95 = np.percentile(final_returns, 95) * 100

        ax.axvline(median, color="#10b981", linestyle="-", linewidth=2, label=f"Median: {median:.1f}%")
        ax.axvline(p5, color="#ef4444", linestyle="--", linewidth=1.5, label=f"5th %ile: {p5:.1f}%")
        ax.axvline(p95, color="#ef4444", linestyle="--", linewidth=1.5, label=f"95th %ile: {p95:.1f}%")

        ax.set_xlabel("Final Return (%)", fontsize=11)
        ax.set_ylabel("Density", fontsize=11)
        ax.set_title(title, fontsize=13, fontweight="bold")
        ax.legend(loc="upper left")
        ax.grid(True, alpha=0.3)
        fig.patch.set_facecolor("#0f172a")
        ax.set_facecolor("#1e293b")
        ax.tick_params(colors="#cbd5e1")
        ax.xaxis.label.set_color("#cbd5e1")
        ax.yaxis.label.set_color("#cbd5e1")
        ax.title.set_color("#f1f5f9")
        for spine in ax.spines.values():
            spine.set_color("#334155")

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
            plt.close(fig)
            logger.info("Saved MC distribution plot to %s", save_path)
            return save_path

        # Return base64
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        b64 = base64.b64encode(buf.read()).decode("utf-8")
        return b64

    def plot_equity_paths(
        self,
        simulations: List[SimulationResult],
        save_path: Optional[str] = None,
        n_paths: int = 200,
    ) -> Optional[str]:
        """
        Plot a sample of equity paths from Monte Carlo simulations.

        Returns base64-encoded PNG if save_path is None.
        """
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            logger.warning("matplotlib not available; skipping plot")
            return None

        fig, ax = plt.subplots(figsize=(12, 6))

        sample_indices = self.rng.choice(
            len(simulations), size=min(n_paths, len(simulations)), replace=False
        )

        for idx in sample_indices:
            path = simulations[idx].path
            color = "#10b981" if simulations[idx].hit_target else "#64748b"
            ax.plot(path / 1_000, color=color, alpha=0.15, linewidth=0.5)

        ax.set_xlabel("Trade Number", fontsize=11)
        ax.set_ylabel("Equity ($K)", fontsize=11)
        ax.set_title("Monte Carlo Equity Paths (Sample)", fontsize=13, fontweight="bold")
        ax.grid(True, alpha=0.3)
        fig.patch.set_facecolor("#0f172a")
        ax.set_facecolor("#1e293b")
        ax.tick_params(colors="#cbd5e1")
        ax.xaxis.label.set_color("#cbd5e1")
        ax.yaxis.label.set_color("#cbd5e1")
        ax.title.set_color("#f1f5f9")
        for spine in ax.spines.values():
            spine.set_color("#334155")

        plt.tight_layout()

        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
            plt.close(fig)
            return save_path

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode("utf-8")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _simulate_one(
        self,
        n_trades: int,
        trade_returns: np.ndarray,
        max_drawdown_limit: float,
        profit_target: float,
        daily_loss_limit: float,
        avg_trades_per_day: float,
    ) -> SimulationResult:
        """
        Run a single Monte Carlo simulation.

        Randomly samples N trades (with replacement), builds equity curve,
        and records outcome.
        """
        # Sample returns with replacement
        sampled = self.rng.choice(trade_returns, size=n_trades, replace=True)

        # Build equity curve
        equity = self.initial_balance + np.cumsum(sampled)
        equity = np.insert(equity, 0, self.initial_balance)

        # Running peak and drawdown
        running_peak = np.maximum.accumulate(equity)
        drawdowns = (running_peak - equity) / running_peak
        max_dd = float(np.max(drawdowns))

        total_return = (equity[-1] - self.initial_balance) / self.initial_balance

        # Check target hit
        target_equity = self.initial_balance * (1.0 + profit_target)
        hit_target = bool(np.any(equity >= target_equity))

        # Check max DD hit
        dd_limit_equity = self.initial_balance * (1.0 - max_drawdown_limit)
        hit_max_dd = bool(np.any(equity <= dd_limit_equity))

        # Determine primary outcome (which happened first)
        if hit_target and hit_max_dd:
            idx_target = int(np.argmax(equity >= target_equity))
            idx_dd = int(np.argmax(equity <= dd_limit_equity))
            if idx_target < idx_dd:
                hit_max_dd = False
            else:
                hit_target = False

        # Estimate days based on trade count
        days_to_target = None
        days_to_fail = None
        if hit_target:
            idx = int(np.argmax(equity >= target_equity))
            days_to_target = idx / avg_trades_per_day
        if hit_max_dd:
            idx = int(np.argmax(equity <= dd_limit_equity))
            days_to_fail = idx / avg_trades_per_day

        return SimulationResult(
            final_equity=float(equity[-1]),
            max_drawdown=max_dd,
            total_return=total_return,
            hit_target=hit_target,
            hit_max_dd=hit_max_dd,
            n_trades=n_trades,
            path=equity,
            days_to_target=days_to_target,
            days_to_fail=days_to_fail,
        )

    def _aggregate_results(
        self,
        simulations: List[SimulationResult],
        n_simulations: int,
        avg_trades_per_day: float,
    ) -> MonteCarloResult:
        """Aggregate individual simulation results into summary statistics."""

        final_returns = np.array([s.total_return for s in simulations])
        max_drawdowns = np.array([s.max_drawdown for s in simulations])

        # Default target/DD for summary metrics
        default_target = 0.08
        default_max_dd = 0.10

        pass_rate = self.calculate_pass_rate(
            simulations, target=default_target, max_dd=default_max_dd
        )
        fail_rate = float(np.mean([s.hit_max_dd for s in simulations]))
        still_running = 1.0 - pass_rate - fail_rate
        # Clamp to handle floating point edge cases
        still_running = max(0.0, still_running)

        median_return = float(np.median(final_returns))
        mean_return = float(np.mean(final_returns))
        worst_case = float(np.percentile(final_returns, 5))
        best_case = float(np.percentile(final_returns, 95))

        median_max_dd = float(np.median(max_drawdowns))
        mean_max_dd = float(np.mean(max_drawdowns))
        max_dd_95th = float(np.percentile(max_drawdowns, 95))
        max_dd_99th = float(np.percentile(max_drawdowns, 99))

        days_to_target = [s.days_to_target for s in simulations if s.days_to_target is not None]
        days_to_fail = [s.days_to_fail for s in simulations if s.days_to_fail is not None]

        median_days_to_target = float(np.median(days_to_target)) if days_to_target else None
        median_days_to_fail = float(np.median(days_to_fail)) if days_to_fail else None

        ci_95 = self.calculate_confidence_intervals(final_returns, 0.95)
        ci_99 = self.calculate_confidence_intervals(final_returns, 0.99)

        # Prop firm specific pass probabilities
        prob_pass_2step_p1 = self.calculate_pass_rate(simulations, 0.08, 0.10)
        prob_pass_2step_p2 = self.calculate_pass_rate(simulations, 0.05, 0.10)
        prob_pass_1step = self.calculate_pass_rate(simulations, 0.10, 0.10)
        prob_pass_pro = self.calculate_pass_rate(simulations, 0.06, 0.05)
        prob_pass_ftmo_p1 = self.calculate_pass_rate(simulations, 0.10, 0.10)
        prob_pass_ftmo_p2 = self.calculate_pass_rate(simulations, 0.05, 0.10)

        return MonteCarloResult(
            n_simulations=n_simulations,
            pass_rate=pass_rate,
            fail_rate=fail_rate,
            still_running=still_running,
            median_return=median_return,
            mean_return=mean_return,
            worst_case=worst_case,
            best_case=best_case,
            median_max_dd=median_max_dd,
            mean_max_dd=mean_max_dd,
            max_dd_95th=max_dd_95th,
            max_dd_99th=max_dd_99th,
            median_days_to_target=median_days_to_target,
            median_days_to_fail=median_days_to_fail,
            confidence_interval=ci_95,
            confidence_interval_99=ci_99,
            prob_pass_2step_p1=prob_pass_2step_p1,
            prob_pass_2step_p2=prob_pass_2step_p2,
            prob_pass_1step=prob_pass_1step,
            prob_pass_pro=prob_pass_pro,
            prob_pass_ftmo_p1=prob_pass_ftmo_p1,
            prob_pass_ftmo_p2=prob_pass_ftmo_p2,
            final_returns=final_returns,
            max_drawdowns=max_drawdowns,
        )


# ---------------------------------------------------------------------------
# Bootstrap confidence for performance metrics
# ---------------------------------------------------------------------------

def bootstrap_metric(
    values: np.ndarray,
    metric_fn,
    n_bootstrap: int = 5_000,
    confidence: float = 0.95,
    seed: int = 42,
) -> Tuple[float, float, float]:
    """
    Bootstrap confidence interval for any metric function.

    Parameters
    ----------
    values : np.ndarray
        Array of values to bootstrap from.
    metric_fn : callable
        Function that takes an array and returns a scalar metric.
    n_bootstrap : int
        Number of bootstrap samples.
    confidence : float
        Confidence level.

    Returns
    -------
    (point_estimate, lower_bound, upper_bound)
    """
    rng = np.random.default_rng(seed)
    point = metric_fn(values)
    bootstrapped = []
    n = len(values)

    for _ in range(n_bootstrap):
        sample = rng.choice(values, size=n, replace=True)
        bootstrapped.append(metric_fn(sample))

    boot_arr = np.array(bootstrapped)
    alpha = 1.0 - confidence
    lower = float(np.percentile(boot_arr, alpha / 2 * 100))
    upper = float(np.percentile(boot_arr, (1.0 - alpha / 2) * 100))

    return float(point), lower, upper


def bootstrap_sharpe_ratio(
    returns: np.ndarray,
    risk_free_rate: float = 0.0,
    n_bootstrap: int = 5_000,
    confidence: float = 0.95,
    seed: int = 42,
) -> Tuple[float, float, float]:
    """Bootstrap confidence interval for Sharpe ratio."""

    def _sharpe(x):
        if len(x) < 2 or np.std(x, ddof=1) == 0:
            return 0.0
        return (np.mean(x) - risk_free_rate) / np.std(x, ddof=1) * np.sqrt(252)

    return bootstrap_metric(returns, _sharpe, n_bootstrap, confidence, seed)


def bootstrap_sortino_ratio(
    returns: np.ndarray,
    risk_free_rate: float = 0.0,
    n_bootstrap: int = 5_000,
    confidence: float = 0.95,
    seed: int = 42,
) -> Tuple[float, float, float]:
    """Bootstrap confidence interval for Sortino ratio."""

    def _sortino(x):
        if len(x) < 2:
            return 0.0
        downside = x[x < 0]
        if len(downside) == 0 or np.std(downside, ddof=1) == 0:
            return float("inf") if np.mean(x) > risk_free_rate else 0.0
        return (np.mean(x) - risk_free_rate) / np.std(downside, ddof=1) * np.sqrt(252)

    return bootstrap_metric(returns, _sortino, n_bootstrap, confidence, seed)


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

def run_monte_carlo(
    trade_pnls: List[float],
    initial_balance: float = 100_000.0,
    n_simulations: int = 10_000,
    max_drawdown_limit: float = 0.10,
    profit_target: float = 0.08,
    **kwargs,
) -> MonteCarloResult:
    """
    Convenience function to run MC simulation from raw PnL values.

    Parameters
    ----------
    trade_pnls : List[float]
        List of trade profit/loss values in currency.
    initial_balance : float
        Starting account balance.
    n_simulations : int
        Number of MC runs.
    max_drawdown_limit : float
        Maximum allowed drawdown fraction.
    profit_target : float
        Profit target fraction.
    **kwargs
        Additional arguments passed to MonteCarloSimulator.run().

    Returns
    -------
    MonteCarloResult
    """
    trades = [SimulatedTrade(pnl=p) for p in trade_pnls]
    sim = MonteCarloSimulator(trades, initial_balance)
    return sim.run(
        n_simulations=n_simulations,
        max_drawdown_limit=max_drawdown_limit,
        profit_target=profit_target,
        **kwargs,
    )
