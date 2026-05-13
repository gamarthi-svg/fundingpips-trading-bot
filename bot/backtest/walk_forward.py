"""
Walk-forward optimisation module for the prop-firm backtester.

Splits historical data into multiple in-sample (IS) / out-of-sample (OOS)
windows, optimises strategy parameters on IS data, validates on OOS data,
and produces a robustness score to detect curve-fitted strategies.
"""

from __future__ import annotations

import itertools
import logging
from copy import deepcopy
from dataclasses import dataclass, field, asdict
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    Type,
)

import numpy as np
import pandas as pd

from .performance import PerformanceAnalyzer, PerformanceMetrics

if TYPE_CHECKING:
    from .engine import BacktestEngine, BacktestConfig, SimulatedTrade

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------
def _param_combinations(param_grid: Dict[str, List[Any]]) -> List[Dict[str, Any]]:
    """Expand a parameter grid into a list of every combination."""
    if not param_grid:
        return [{}]
    keys = list(param_grid.keys())
    values = [param_grid[k] for k in keys]
    return [dict(zip(keys, combo)) for combo in itertools.product(*values)]


def _slice_windows(
    data: pd.DataFrame, n_windows: int, is_pct: float
) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
    """
    Split *data* into *n_windows* overlapping (IS, OOS) pairs.

    The walk-forward scheme used here is **anchored**:
    - IS always starts at the beginning of the data set.
    - OOS follows immediately after IS.
    - Each subsequent window expands the IS period and shifts OOS forward.

    Returns a list of (is_data, oos_data) tuples.
    """
    n = len(data)
    if n < n_windows * 10:
        raise ValueError(
            f"Data too short ({n} rows) for {n_windows} windows. "
            "Need at least 10 rows per window."
        )

    # Determine the total IS size for the final window
    total_is_size = int(n * is_pct)
    oos_total = n - total_is_size

    if oos_total < n_windows:
        raise ValueError(
            f"Not enough OOS data ({oos_total} rows) for {n_windows} windows."
        )

    oos_per_window = oos_total // n_windows
    windows: List[Tuple[pd.DataFrame, pd.DataFrame]] = []

    for i in range(n_windows):
        is_end = total_is_size + i * oos_per_window
        if i == n_windows - 1:
            oos_end = n
        else:
            oos_end = is_end + oos_per_window

        is_data = data.iloc[:is_end]
        oos_data = data.iloc[is_end:oos_end]
        windows.append((is_data, oos_data))

    return windows


def _unanchored_windows(
    data: pd.DataFrame, n_windows: int, is_pct: float
) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
    """
    Alternative: **rolling** (unanchored) windows.
    Each IS window is the same size, rolling forward through the data.
    """
    n = len(data)
    window_size = n // n_windows
    is_size = int(window_size * is_pct)
    oos_size = window_size - is_size

    windows: List[Tuple[pd.DataFrame, pd.DataFrame]] = []
    for i in range(n_windows):
        start = i * window_size
        is_end = start + is_size
        oos_end = start + window_size
        if oos_end > n:
            oos_end = n
        windows.append((data.iloc[start:is_end], data.iloc[is_end:oos_end]))

    return windows


# ---------------------------------------------------------------------------
# Walk-forward result
# ---------------------------------------------------------------------------
@dataclass
class WindowResult:
    """Results for a single walk-forward window."""

    window_index: int
    best_params: Dict[str, Any]
    is_metrics: PerformanceMetrics
    oos_metrics: PerformanceMetrics
    all_is_results: Dict[str, PerformanceMetrics] = field(
        default_factory=dict, repr=False
    )  # param_hash -> metrics for diagnostics


@dataclass
class WalkForwardResult:
    """Aggregated walk-forward optimisation output."""

    windows: List[WindowResult] = field(default_factory=list)
    aggregate_is: PerformanceMetrics = field(
        default_factory=PerformanceMetrics
    )
    aggregate_oos: PerformanceMetrics = field(
        default_factory=PerformanceMetrics
    )
    robustness_score: float = 0.0          # 0-1, higher = more robust
    is_robust: bool = False                # True if robustness_score > 0.6
    best_overall_params: Dict[str, Any] = field(default_factory=dict)
    param_stability_score: float = 0.0     # How stable params are across windows
    degradation_report: Dict[str, float] = field(default_factory=dict)

    def print_summary(self) -> None:
        """Print a formatted summary to stdout."""
        print(self._format_report())

    def _format_report(self) -> str:
        """Build a formatted text report (used by print_summary)."""
        lines = [
            "=" * 70,
            "WALK-FORWARD OPTIMISATION REPORT",
            "=" * 70,
            f"Robustness Score:   {self.robustness_score:.3f} "
            f"({'ROBUST' if self.is_robust else 'FRAGILE - possible curve-fit'})",
            f"Param Stability:    {self.param_stability_score:.3f}",
            f"Best Params:        {self.best_overall_params}",
            "-" * 70,
            "DEGRADATION REPORT (OOS / IS retention)",
            "-" * 70,
        ]
        for metric, retention in self.degradation_report.items():
            status = "OK" if retention >= 0.6 else "WARN"
            lines.append(f"  {metric:<35} {retention:>6.3f}  [{status}]")
        lines.extend(
            [
                "-" * 70,
                "PER-WINDOW SUMMARY",
                "-" * 70,
                self.summary_table().to_string(index=False),
                "=" * 70,
            ]
        )
        # Aggregate IS vs OOS comparison
        lines.extend(
            [
                "",
                "AGGREGATE IS vs OOS",
                "-" * 70,
                f"{'Metric':<25} {'IS':>12} {'OOS':>12} {'Retention':>12}",
                "-" * 70,
            ]
        )
        for field_name in [
            "total_return",
            "sharpe_ratio",
            "sortino_ratio",
            "max_drawdown",
            "win_rate",
            "profit_factor",
            "expectancy",
        ]:
            is_v = getattr(self.aggregate_is, field_name, 0.0)
            oos_v = getattr(self.aggregate_oos, field_name, 0.0)
            ret = oos_v / is_v if is_v != 0 else 0.0
            lines.append(
                f"{field_name:<25} {is_v:>12.2f} {oos_v:>12.2f} {ret:>12.3f}"
            )
        lines.append("=" * 70)
        return "\n".join(lines)

    def to_dict(self) -> dict:
        """Serialise to a plain dictionary."""
        return {
            "robustness_score": self.robustness_score,
            "is_robust": self.is_robust,
            "best_overall_params": self.best_overall_params,
            "param_stability_score": self.param_stability_score,
            "degradation_report": self.degradation_report,
            "n_windows": len(self.windows),
            "aggregate_is": self.aggregate_is.to_dict(),
            "aggregate_oos": self.aggregate_oos.to_dict(),
            "windows": [
                {
                    "window_index": w.window_index,
                    "best_params": w.best_params,
                    "is_metrics": w.is_metrics.to_dict(),
                    "oos_metrics": w.oos_metrics.to_dict(),
                }
                for w in self.windows
            ],
        }

    def summary_table(self) -> pd.DataFrame:
        """Return a summary DataFrame comparing IS vs OOS per window."""
        rows = []
        for w in self.windows:
            rows.append(
                {
                    "window": w.window_index,
                    "is_return": w.is_metrics.total_return,
                    "oos_return": w.oos_metrics.total_return,
                    "is_sharpe": w.is_metrics.sharpe_ratio,
                    "oos_sharpe": w.oos_metrics.sharpe_ratio,
                    "is_maxdd": w.is_metrics.max_drawdown,
                    "oos_maxdd": w.oos_metrics.max_drawdown,
                    "is_winrate": w.is_metrics.win_rate,
                    "oos_winrate": w.oos_metrics.win_rate,
                }
            )
        return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Walk-forward optimiser
# ---------------------------------------------------------------------------
class WalkForwardOptimizer:
    """
    Walk-forward analysis splits data into in-sample (optimisation) and
    out-of-sample (validation) periods.

    Process:
      1. Divide data into N windows.
      2. For each window:
         a. Optimise parameters on IS data.
         b. Test optimised parameters on OOS data.
      3. Aggregate OOS results.
      4. If OOS performance degrades significantly → strategy is curve-fit.
    """

    def __init__(
        self,
        engine: Any = None,                     # BacktestEngine instance
        engine_factory: Optional[Callable[..., Any]] = None,
        strategy: Any = None,                   # Strategy instance (legacy compat)
        strategy_class: Optional[Type[Any]] = None,
        param_grid: Optional[Dict[str, List[Any]]] = None,
        n_windows: int = 5,
        metric_to_optimize: str = "sharpe_ratio",
        maximize: bool = True,
        window_mode: str = "anchored",
    ) -> None:
        """
        Parameters
        ----------
        engine:
            A BacktestEngine instance OR a callable factory that returns one.
            If an instance is provided, it is wrapped into a factory internally.
        engine_factory:
            Explicit callable that returns a fresh BacktestEngine instance.
        strategy:
            Strategy instance or class.  Legacy compatibility alias for strategy_class.
        strategy_class:
            Strategy class to instantiate (must accept **kwargs for params).
        param_grid:
            Mapping of parameter name -> list of values to grid-search.
            Example: {"sl_pips": [8, 10, 12], "rr": [1.5, 2.0, 2.5]}
        n_windows:
            Number of walk-forward windows (can be overridden in optimize()).
        metric_to_optimize:
            Which PerformanceMetrics field to use as the objective.
        maximize:
            If True, higher metric = better; if False, lower = better.
        window_mode:
            "anchored" (expanding IS) or "rolling" (fixed-size IS).
        """
        # Resolve engine / engine_factory
        if engine_factory is not None:
            self.engine_factory = engine_factory
        elif engine is not None:
            # Wrap instance in a factory
            if callable(engine):
                self.engine_factory = engine
            else:
                self._engine_instance = engine
                self.engine_factory = lambda: self._engine_instance
        else:
            raise ValueError("Must provide either 'engine' or 'engine_factory'.")

        # Resolve strategy_class
        sc = strategy_class or strategy
        if sc is None:
            raise ValueError("Must provide 'strategy_class' (or 'strategy' alias).")
        # If an instance was passed, extract its class
        if not isinstance(sc, type):
            self.strategy_class = type(sc)
        else:
            self.strategy_class = sc

        self.param_grid = param_grid or {}
        self.n_windows = n_windows
        self.metric = metric_to_optimize
        self.maximize = maximize
        self.window_mode = window_mode.lower()

        if self.window_mode not in ("anchored", "rolling"):
            raise ValueError("window_mode must be 'anchored' or 'rolling'")

        # Cache: param_hash -> PerformanceMetrics (avoids re-running identical configs)
        self._cache: Dict[str, PerformanceMetrics] = {}

    # ------------------------------------------------------------------ #
    # Main entry point
    # ------------------------------------------------------------------ #
    def optimize(
        self,
        data: pd.DataFrame,
        in_sample_pct: float = 0.70,
        n_windows: int = 5,
    ) -> WalkForwardResult:
        """
        Run walk-forward optimisation.

        Parameters
        ----------
        data:
            Full historical price data (OHLCV format expected).
        in_sample_pct:
            Fraction of data used for in-sample optimisation per window.
        n_windows:
            Number of walk-forward windows.

        Returns
        -------
        WalkForwardResult with per-window results, aggregate OOS metrics,
        robustness score, and parameter stability analysis.
        """
        logger.info(
            "Starting walk-forward optimisation: %d windows, "
            "IS%%=%.2f, mode=%s, metric=%s",
            n_windows,
            in_sample_pct,
            self.window_mode,
            self.metric,
        )

        # Build windows
        if self.window_mode == "anchored":
            windows = _slice_windows(data, n_windows, in_sample_pct)
        else:
            windows = _unanchored_windows(data, n_windows, in_sample_pct)

        all_window_results: List[WindowResult] = []
        is_metrics_list: List[PerformanceMetrics] = []
        oos_metrics_list: List[PerformanceMetrics] = []

        for idx, (is_data, oos_data) in enumerate(windows):
            logger.info(
                "Window %d/%d  |  IS: %d rows  |  OOS: %d rows",
                idx + 1,
                n_windows,
                len(is_data),
                len(oos_data),
            )
            best_params, is_m, oos_m = self._optimize_window(
                is_data, oos_data, self.param_grid
            )
            wr = WindowResult(
                window_index=idx,
                best_params=best_params,
                is_metrics=is_m,
                oos_metrics=oos_m,
            )
            all_window_results.append(wr)
            is_metrics_list.append(is_m)
            oos_metrics_list.append(oos_m)

        # Aggregate OOS equity curve
        aggregate_oos = self._aggregate_metrics(oos_metrics_list)
        aggregate_is = self._aggregate_metrics(is_metrics_list)

        # Robustness
        robustness = self.robustness_score(is_metrics_list, oos_metrics_list)

        # Parameter stability
        best_params_list = [w.best_params for w in all_window_results]
        stability = self._param_stability(best_params_list)

        # Most frequently selected parameters
        best_overall = self._most_frequent_params(best_params_list)

        # Degradation report
        degradation = self._degradation_report(is_metrics_list, oos_metrics_list)

        result = WalkForwardResult(
            windows=all_window_results,
            aggregate_is=aggregate_is,
            aggregate_oos=aggregate_oos,
            robustness_score=robustness,
            is_robust=robustness >= 0.6,
            best_overall_params=best_overall,
            param_stability_score=stability,
            degradation_report=degradation,
        )

        logger.info(
            "Walk-forward complete. Robustness=%.3f  Robust=%s  "
            "Best params=%s",
            result.robustness_score,
            result.is_robust,
            result.best_overall_params,
        )
        return result

    # ------------------------------------------------------------------ #
    # Per-window optimisation
    # ------------------------------------------------------------------ #
    def _optimize_window(
        self,
        is_data: pd.DataFrame,
        oos_data: pd.DataFrame,
        param_grid: Dict[str, List[Any]],
    ) -> Tuple[Dict[str, Any], PerformanceMetrics, PerformanceMetrics]:
        """
        Grid-search all parameter combinations on IS data and return the
        best params along with IS and OOS metrics.
        """
        combos = _param_combinations(param_grid)
        if not combos or combos == [{}]:
            raise ValueError("Empty or invalid parameter grid.")

        best_params: Dict[str, Any] = {}
        best_score = -np.inf if self.maximize else np.inf
        is_best = PerformanceMetrics()
        all_is_results: Dict[str, PerformanceMetrics] = {}

        for combo in combos:
            param_hash = "|".join(f"{k}={v}" for k, v in sorted(combo.items()))

            # Check cache
            if param_hash in self._cache:
                is_m = self._cache[param_hash]
            else:
                is_m = self._run_backtest(is_data, combo)
                self._cache[param_hash] = is_m

            all_is_results[param_hash] = is_m
            score = getattr(is_m, self.metric, 0.0)

            is_better = score > best_score if self.maximize else score < best_score
            if is_better:
                best_score = score
                best_params = combo
                is_best = is_m

        # Run OOS with best params
        oos_m = self._run_backtest(oos_data, best_params)

        return best_params, is_best, oos_m

    # ------------------------------------------------------------------ #
    # Backtest runner (single param set)
    # ------------------------------------------------------------------ #
    def _run_backtest(
        self, data: pd.DataFrame, params: Dict[str, Any]
    ) -> PerformanceMetrics:
        """
        Execute a single backtest run with *params* and return metrics.

        This method instantiates a fresh engine + strategy, runs the
        backtest, and returns PerformanceMetrics.  If the engine raises
        an exception (e.g. insufficient data), a zeroed metrics object
        is returned so grid search can continue.
        """
        try:
            engine = self.engine_factory()
            strategy = self.strategy_class(**params)
            # Assume engine.run() returns (trades, equity_curve, final_balance)
            trades, equity_curve, final_balance = engine.run(
                data=data, strategy=strategy
            )
            # Derive initial balance from the equity curve or engine config
            initial_balance = getattr(
                engine, "initial_balance", equity_curve["equity"].iloc[0]
            )
            config = getattr(engine, "config", None)

            analyser = PerformanceAnalyzer(
                trades=trades,
                equity_curve=equity_curve,
                initial_balance=initial_balance,
                config=config,
            )
            return analyser.calculate_all()
        except Exception as exc:
            logger.debug(
                "Backtest failed for params %s: %s", params, exc, exc_info=True
            )
            # Return zeroed metrics so grid search continues gracefully
            return PerformanceMetrics()

    # ------------------------------------------------------------------ #
    # Robustness scoring
    # ------------------------------------------------------------------ #
    def robustness_score(
        self,
        is_results: List[PerformanceMetrics],
        oos_results: List[PerformanceMetrics],
    ) -> float:
        """
        Compute a robustness score in [0, 1].

        Formula:
            score = mean( min(oos_metric / is_metric, 1.0) )

        Where the metric is sharpe_ratio by default.  A score of 1.0
        means no degradation; 0.0 means complete failure.
        """
        if not is_results or not oos_results:
            return 0.0
        if len(is_results) != len(oos_results):
            raise ValueError("IS and OOS result lists must have same length.")

        ratios = []
        for is_m, oos_m in zip(is_results, oos_results):
            is_val = getattr(is_m, self.metric, 0.0)
            oos_val = getattr(oos_m, self.metric, 0.0)

            # Guard against zero or negative IS values
            if is_val <= 0:
                # If IS was not profitable, any positive OOS is a win
                ratios.append(1.0 if oos_val > 0 else 0.0)
                continue

            ratio = oos_val / is_val
            # Cap at 1.0 (OOS beating IS is fine, we don't penalise)
            ratios.append(min(ratio, 1.0))

        return float(np.mean(ratios)) if ratios else 0.0

    # ------------------------------------------------------------------ #
    # Parameter stability
    # ------------------------------------------------------------------ #
    @staticmethod
    def _param_stability(params_list: List[Dict[str, Any]]) -> float:
        """
        Score how stable the chosen parameters are across windows.

        For each parameter, compute the coefficient of variation (CV)
        across windows.  Return 1 - mean(CV) clamped to [0, 1].
        """
        if not params_list or len(params_list) < 2:
            return 0.0

        # Collect numeric params only
        numeric: Dict[str, List[float]] = {}
        for p in params_list:
            for k, v in p.items():
                if isinstance(v, (int, float)):
                    numeric.setdefault(k, []).append(float(v))

        if not numeric:
            return 0.0

        cvs = []
        for key, vals in numeric.items():
            arr = np.array(vals)
            mean_v = arr.mean()
            if mean_v == 0:
                cvs.append(0.0 if arr.std() == 0 else 1.0)
            else:
                cvs.append(abs(arr.std() / mean_v))

        mean_cv = np.mean(cvs)
        return float(max(0.0, 1.0 - mean_cv))

    @staticmethod
    def _most_frequent_params(
        params_list: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Return the parameter set that appeared most often across windows."""
        if not params_list:
            return {}

        # Hash each param dict
        counts: Dict[str, Tuple[int, Dict[str, Any]]] = {}
        for p in params_list:
            h = "|".join(f"{k}={v}" for k, v in sorted(p.items()))
            if h in counts:
                counts[h] = (counts[h][0] + 1, p)
            else:
                counts[h] = (1, p)

        return max(counts.values(), key=lambda x: x[0])[1]

    # ------------------------------------------------------------------ #
    # Degradation report
    # ------------------------------------------------------------------ #
    def _degradation_report(
        self,
        is_results: List[PerformanceMetrics],
        oos_results: List[PerformanceMetrics],
    ) -> Dict[str, float]:
        """Build a detailed IS vs OOS degradation report."""
        fields = [
            "total_return",
            "sharpe_ratio",
            "sortino_ratio",
            "max_drawdown",
            "win_rate",
            "profit_factor",
            "expectancy",
        ]

        report: Dict[str, float] = {}
        for field_name in fields:
            is_vals = [getattr(r, field_name, 0.0) for r in is_results]
            oos_vals = [getattr(r, field_name, 0.0) for r in oos_results]
            is_mean = np.mean(is_vals) if is_vals else 0.0
            oos_mean = np.mean(oos_vals) if oos_vals else 0.0
            if is_mean != 0:
                report[f"{field_name}_retention"] = oos_mean / is_mean
            else:
                report[f"{field_name}_retention"] = 1.0 if oos_mean >= 0 else 0.0

        return report

    # ------------------------------------------------------------------ #
    # Aggregation helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _aggregate_metrics(metrics_list: List[PerformanceMetrics]) -> PerformanceMetrics:
        """
        Aggregate a list of PerformanceMetrics into a single summary.

        Averages ratios and uses the last equity curve for drawdown.
        """
        if not metrics_list:
            return PerformanceMetrics()

        agg = PerformanceMetrics()
        n = len(metrics_list)

        # Simple averages for scalar fields
        scalar_fields = [
            "total_return",
            "annualized_return",
            "max_drawdown",
            "sharpe_ratio",
            "sortino_ratio",
            "calmar_ratio",
            "profit_factor",
            "win_rate",
            "avg_win",
            "avg_loss",
            "avg_win_loss_ratio",
            "expectancy",
            "expectancy_per_dollar_risked",
            "consistency_score",
            "risk_of_ruin",
            "avg_time_in_market",
        ]

        for field_name in scalar_fields:
            vals = [getattr(m, field_name, 0.0) for m in metrics_list]
            setattr(agg, field_name, float(np.mean(vals)))

        # Sum count fields
        agg.total_trades = sum(m.total_trades for m in metrics_list)
        agg.winning_trades = sum(m.winning_trades for m in metrics_list)
        agg.losing_trades = sum(m.losing_trades for m in metrics_list)
        agg.profitable_days = sum(m.profitable_days for m in metrics_list)
        agg.unprofitable_days = sum(m.unprofitable_days for m in metrics_list)
        agg.max_drawdown_duration = max(
            (m.max_drawdown_duration for m in metrics_list), default=0
        )
        agg.consecutive_wins = max(
            (m.consecutive_wins for m in metrics_list), default=0
        )
        agg.consecutive_losses = max(
            (m.consecutive_losses for m in metrics_list), default=0
        )

        # Max/min extremes
        agg.largest_win = max(
            (m.largest_win for m in metrics_list), default=0.0
        )
        agg.largest_loss = min(
            (m.largest_loss for m in metrics_list), default=0.0
        )

        return agg

    # ------------------------------------------------------------------ #
    # Convenience: optimise + report
    # ------------------------------------------------------------------ #
    def optimize_and_report(
        self,
        data: pd.DataFrame,
        in_sample_pct: float = 0.70,
        n_windows: int = 5,
    ) -> Tuple[WalkForwardResult, str]:
        """Run optimisation and return a formatted text report."""
        result = self.optimize(data, in_sample_pct, n_windows)
        report_lines = [
            "=" * 70,
            "WALK-FORWARD OPTIMISATION REPORT",
            "=" * 70,
            f"Window mode:        {self.window_mode}",
            f"Windows:            {n_windows}",
            f"IS %%:               {in_sample_pct*100:.0f}%",
            f"Objective:          {self.metric} (maximize={self.maximize})",
            "-" * 70,
            f"Robustness Score:   {result.robustness_score:.3f} "
            f"({'ROBUST' if result.is_robust else 'FRAGILE - possible curve-fit'})",
            f"Param Stability:    {result.param_stability_score:.3f}",
            f"Best Params:        {result.best_overall_params}",
            "-" * 70,
            "DEGRADATION REPORT (OOS / IS retention)",
            "-" * 70,
        ]
        for metric, retention in result.degradation_report.items():
            status = "OK" if retention >= 0.6 else "WARN"
            report_lines.append(
                f"  {metric:<35} {retention:>6.3f}  [{status}]"
            )

        report_lines.extend(
            [
                "-" * 70,
                "PER-WINDOW SUMMARY",
                "-" * 70,
                result.summary_table().to_string(index=False),
                "=" * 70,
            ]
        )

        # Aggregate IS vs OOS comparison
        report_lines.extend(
            [
                "",
                "AGGREGATE IS vs OOS",
                "-" * 70,
                f"{'Metric':<25} {'IS':>12} {'OOS':>12} {'Retention':>12}",
                "-" * 70,
            ]
        )
        agg_is = result.aggregate_is
        agg_oos = result.aggregate_oos
        for field_name in [
            "total_return",
            "sharpe_ratio",
            "sortino_ratio",
            "max_drawdown",
            "win_rate",
            "profit_factor",
            "expectancy",
        ]:
            is_v = getattr(agg_is, field_name, 0.0)
            oos_v = getattr(agg_oos, field_name, 0.0)
            ret = oos_v / is_v if is_v != 0 else 0.0
            report_lines.append(
                f"{field_name:<25} {is_v:>12.2f} {oos_v:>12.2f} {ret:>12.3f}"
            )
        report_lines.append("=" * 70)

        return result, "\n".join(report_lines)
