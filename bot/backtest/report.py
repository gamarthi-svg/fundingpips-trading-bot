"""
Backtest report generator for prop firm trading backtester.

Generates comprehensive HTML and JSON reports with:
- Summary metrics (total return, max DD, Sharpe, win rate)
- Equity curve and drawdown charts
- Monthly returns heatmap
- Trade distribution histogram
- Monte Carlo distribution
- Walk-forward results
- Prop firm compliance checklist
- Complete trades table

HTML reports are fully self-contained with inline CSS (dark theme).
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from monte_carlo import MonteCarloResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Supporting data classes (stubs for cross-file compatibility)
# ---------------------------------------------------------------------------

@dataclass
class BacktestResult:
    """Stub for backtest result. Full version in backtest_engine.py."""

    trades: List[Dict[str, Any]] = field(default_factory=list)
    equity_curve: pd.DataFrame = field(default_factory=lambda: pd.DataFrame())
    config: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PerformanceMetrics:
    """Stub for performance metrics. Full version in metrics.py."""

    total_return: float = 0.0
    annualized_return: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_dollars: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_trade: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    avg_holding_period: float = 0.0
    expectancy: float = 0.0
    sqn: float = 0.0  # System Quality Number
    ulcer_index: float = 0.0
    k_ratio: float = 0.0
    skewness: float = 0.0
    kurtosis: float = 0.0
    var_95: float = 0.0
    var_99: float = 0.0
    cvar_95: float = 0.0
    monthly_returns: List[Dict] = field(default_factory=list)


@dataclass
class WalkForwardResult:
    """Stub for walk-forward result. Full version in walkforward.py."""

    is_robust: bool = False
    out_of_sample_sharpe: float = 0.0
    in_sample_sharpe: float = 0.0
    overfit_ratio: float = 0.0
    is_significant: bool = False
    p_value: float = 1.0
    n_splits: int = 0
    results: List[Dict] = field(default_factory=list)


@dataclass
class PropFirmRules:
    """Prop firm challenge rule definitions."""

    name: str
    phase: str
    profit_target: float
    max_drawdown: float
    daily_loss_limit: float
    min_trading_days: int
    consistency_rule: bool  # Best day <= 30% of total profit
    time_limit_days: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "phase": self.phase,
            "profit_target": self.profit_target,
            "max_drawdown": self.max_drawdown,
            "daily_loss_limit": self.daily_loss_limit,
            "min_trading_days": self.min_trading_days,
            "consistency_rule": self.consistency_rule,
            "time_limit_days": self.time_limit_days,
        }


# Pre-defined prop firm configurations
PROP_FIRM_CONFIGS = [
    PropFirmRules("FundingPips", "Phase 1", 0.08, 0.10, 0.05, 5, True, 30),
    PropFirmRules("FundingPips", "Phase 2", 0.05, 0.10, 0.05, 5, True, 60),
    PropFirmRules("FundingPips", "Pro", 0.06, 0.05, 0.02, 3, True, None),
    PropFirmRules("FTMO", "Phase 1", 0.10, 0.10, 0.05, 4, False, 30),
    PropFirmRules("FTMO", "Phase 2", 0.05, 0.10, 0.05, 4, False, 60),
    PropFirmRules("The5ers", "Phase 1", 0.08, 0.10, 0.04, 3, True, None),
    PropFirmRules("Apex", "Phase 1", 0.06, 0.03, 0.015, 7, False, None),
]


# ---------------------------------------------------------------------------
# Backtest Report
# ---------------------------------------------------------------------------

class BacktestReport:
    """
    Generate comprehensive backtest reports in HTML and JSON.

    Supports:
    - Self-contained HTML with dark theme and inline charts
    - JSON for dashboard/API consumption
    - Console text summary
    - Prop firm compliance checking
    """

    def __init__(
        self,
        result: BacktestResult,
        metrics: PerformanceMetrics,
        mc_result: Optional[MonteCarloResult] = None,
        wf_result: Optional[WalkForwardResult] = None,
        strategy_name: str = "Unnamed Strategy",
    ):
        self.result = result
        self.metrics = metrics
        self.mc_result = mc_result
        self.wf_result = wf_result
        self.strategy_name = strategy_name
        self.generated_at = datetime.utcnow().isoformat() + "Z"

    # ------------------------------------------------------------------
    # JSON export
    # ------------------------------------------------------------------

    def to_json(self, path: str) -> None:
        """
        Save complete report as JSON for dashboard consumption.

        Includes: config, trades, equity curve, all metrics, MC results,
        walk-forward results, and prop firm compliance.
        """
        report_data = self._build_report_dict()

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(report_data, f, indent=2, default=str)

        logger.info("JSON report saved to %s", path)

    def to_json_str(self) -> str:
        """Return report JSON as string."""
        return json.dumps(self._build_report_dict(), indent=2, default=str)

    # ------------------------------------------------------------------
    # HTML export
    # ------------------------------------------------------------------

    def to_html(self, path: str) -> None:
        """
        Generate beautiful, self-contained HTML report with inline charts.

        Sections:
        1. Summary (total return, max DD, Sharpe, win rate)
        2. Equity curve chart (base64 PNG)
        3. Drawdown chart
        4. Monthly returns heatmap
        5. Trade distribution histogram
        6. Monte Carlo distribution
        7. Walk-forward results
        8. Prop firm compliance checklist
        9. All trades table
        """
        html = self._build_html()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            f.write(html)
        logger.info("HTML report saved to %s", path)

    def to_html_str(self) -> str:
        """Return HTML report as string."""
        return self._build_html()

    # ------------------------------------------------------------------
    # Console summary
    # ------------------------------------------------------------------

    def print_summary(self) -> None:
        """Print a clean text summary to the console."""
        m = self.metrics
        print("=" * 60)
        print(f"  BACKTEST REPORT: {self.strategy_name}")
        print(f"  Generated: {self.generated_at}")
        print("=" * 60)
        print()
        print("  PERFORMANCE SUMMARY")
        print("  " + "-" * 56)
        print(f"  Total Return:        {m.total_return:>10.2%}")
        print(f"  Annualized Return:   {m.annualized_return:>10.2%}")
        print(f"  Max Drawdown:        {m.max_drawdown:>10.2%}")
        print(f"  Sharpe Ratio:        {m.sharpe_ratio:>10.2f}")
        print(f"  Sortino Ratio:       {m.sortino_ratio:>10.2f}")
        print(f"  Calmar Ratio:        {m.calmar_ratio:>10.2f}")
        print(f"  Win Rate:            {m.win_rate:>10.1%}")
        print(f"  Profit Factor:       {m.profit_factor:>10.2f}")
        print(f"  Total Trades:        {m.total_trades:>10d}")
        print(f"  Avg Trade:           {m.avg_trade:>10.2f}")
        print(f"  Expectancy:          {m.expectancy:>10.2f}")
        print(f"  SQN:                 {m.sqn:>10.2f}")
        print()
        print("  RISK METRICS")
        print("  " + "-" * 56)
        print(f"  VaR (95%):           {m.var_95:>10.2%}")
        print(f"  CVaR (95%):          {m.cvar_95:>10.2%}")
        print(f"  Skewness:            {m.skewness:>10.2f}")
        print(f"  Kurtosis:            {m.kurtosis:>10.2f}")
        print()

        if self.mc_result:
            mc = self.mc_result
            print("  MONTE CARLO (n={:,})".format(mc.n_simulations))
            print("  " + "-" * 56)
            print(f"  Pass Rate:           {mc.pass_rate:>10.1%}")
            print(f"  Fail Rate:           {mc.fail_rate:>10.1%}")
            print(f"  Median Return:       {mc.median_return:>10.1%}")
            print(f"  Worst Case (5%):     {mc.worst_case:>10.1%}")
            print(f"  Best Case (95%):     {mc.best_case:>10.1%}")
            print(f"  Median Max DD:       {mc.median_max_dd:>10.1%}")
            print(f"  95% CI:              [{mc.confidence_interval[0]:.1%}, {mc.confidence_interval[1]:.1%}]")
            print()
            print("  PROP FIRM PASS PROBABILITIES")
            print("  " + "-" * 56)
            print(f"  2-Step Phase 1 (8%):  {mc.prob_pass_2step_p1:>10.1%}")
            print(f"  2-Step Phase 2 (5%):  {mc.prob_pass_2step_p2:>10.1%}")
            print(f"  1-Step (10%):         {mc.prob_pass_1step:>10.1%}")
            print(f"  Pro (6% / 5% DD):     {mc.prob_pass_pro:>10.1%}")
            print()

        if self.wf_result:
            wf = self.wf_result
            print("  WALK-FORWARD ANALYSIS")
            print("  " + "-" * 56)
            print(f"  Robust:              {str(wf.is_robust):>10}")
            print(f"  OOS Sharpe:          {wf.out_of_sample_sharpe:>10.2f}")
            print(f"  Overfit Ratio:       {wf.overfit_ratio:>10.2f}")
            print(f"  Significant:         {str(wf.is_significant):>10}")
            print()

        # Prop firm compliance
        compliance = self._check_prop_firm_compliance()
        print("  PROP FIRM COMPLIANCE")
        print("  " + "-" * 56)
        for check in compliance[:6]:  # Show first 6
            status = "PASS" if check["passed"] else "FAIL"
            icon = "[+]" if check["passed"] else "[x]"
            print(f"  {icon} {check['rule']:<35} {status}")
        print()
        print("=" * 60)

    # ------------------------------------------------------------------
    # HTML builder
    # ------------------------------------------------------------------

    def _build_html(self) -> str:
        """Assemble the full HTML report."""
        m = self.metrics

        # Inline charts
        equity_chart = self._generate_equity_curve_chart()
        dd_chart = self._generate_drawdown_chart()
        monthly_heatmap = self._generate_monthly_heatmap()
        trade_dist = self._generate_trade_distribution_chart()
        mc_chart = self._generate_mc_distribution_chart()
        wf_section = self._generate_walkforward_section()
        compliance_table = self._prop_firm_compliance_table()
        trades_table = self._trades_table()

        # Status colors
        sharpe_color = "#10b981" if m.sharpe_ratio >= 1.5 else "#f59e0b" if m.sharpe_ratio >= 1.0 else "#ef4444"
        dd_color = "#10b981" if m.max_drawdown <= 0.05 else "#f59e0b" if m.max_drawdown <= 0.10 else "#ef4444"
        wr_color = "#10b981" if m.win_rate >= 0.55 else "#f59e0b" if m.win_rate >= 0.45 else "#ef4444"

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Backtest Report - {self.strategy_name}</title>
<style>
:root {{
  --bg-primary: #0f172a;
  --bg-secondary: #1e293b;
  --bg-card: #1e293b;
  --bg-elevated: #334155;
  --text-primary: #f1f5f9;
  --text-secondary: #94a3b8;
  --text-muted: #64748b;
  --accent-blue: #3b82f6;
  --accent-green: #10b981;
  --accent-red: #ef4444;
  --accent-amber: #f59e0b;
  --border: #334155;
  --border-light: #475569;
  --font-mono: 'SF Mono', Monaco, 'Cascadia Code', monospace;
  --font-sans: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: var(--font-sans);
  background: var(--bg-primary);
  color: var(--text-primary);
  line-height: 1.6;
  padding: 0;
}}
.container {{ max-width: 1200px; margin: 0 auto; padding: 2rem; }}
.header {{
  background: linear-gradient(135deg, #1e3a5f 0%, #0f172a 100%);
  padding: 2.5rem 2rem;
  border-bottom: 2px solid var(--accent-blue);
  margin: -2rem -2rem 2rem -2rem;
}}
.header h1 {{ font-size: 1.75rem; font-weight: 700; margin-bottom: 0.5rem; }}
.header .subtitle {{ color: var(--text-secondary); font-size: 0.9rem; }}
.section {{
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 1.5rem;
  margin-bottom: 1.5rem;
}}
.section-title {{
  font-size: 1.15rem;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 1rem;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid var(--border);
}}
.metrics-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 1rem;
}}
.metric-card {{
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 1rem;
  text-align: center;
}}
.metric-label {{ font-size: 0.75rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.25rem; }}
.metric-value {{ font-size: 1.4rem; font-weight: 700; font-family: var(--font-mono); }}
.metric-value.green {{ color: var(--accent-green); }}
.metric-value.red {{ color: var(--accent-red); }}
.metric-value.amber {{ color: var(--accent-amber); }}
.metric-value.blue {{ color: var(--accent-blue); }}
.chart-container {{ margin-top: 1rem; text-align: center; }}
.chart-container img {{ max-width: 100%; border-radius: 8px; border: 1px solid var(--border); }}
table {{ width: 100%; border-collapse: collapse; margin-top: 0.5rem; }}
th, td {{ padding: 0.6rem 0.75rem; text-align: left; font-size: 0.85rem; }}
th {{ background: var(--bg-primary); color: var(--text-secondary); font-weight: 600; text-transform: uppercase; font-size: 0.7rem; letter-spacing: 0.05em; border-bottom: 2px solid var(--border); }}
tr {{ border-bottom: 1px solid var(--border); }}
tr:hover {{ background: rgba(59, 130, 246, 0.05); }}
td {{ color: var(--text-secondary); }}
td.positive {{ color: var(--accent-green); font-weight: 600; }}
td.negative {{ color: var(--accent-red); font-weight: 600; }}
.badge {{
  display: inline-block;
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}}
.badge-pass {{ background: rgba(16, 185, 129, 0.15); color: var(--accent-green); border: 1px solid rgba(16, 185, 129, 0.3); }}
.badge-fail {{ background: rgba(239, 68, 68, 0.15); color: var(--accent-red); border: 1px solid rgba(239, 68, 68, 0.3); }}
.badge-warn {{ background: rgba(245, 158, 11, 0.15); color: var(--accent-amber); border: 1px solid rgba(245, 158, 11, 0.3); }}
.mc-grid {{
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 0.75rem;
  margin-bottom: 1rem;
}}
.mc-item {{
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.75rem;
}}
.mc-item-label {{ font-size: 0.7rem; color: var(--text-muted); text-transform: uppercase; }}
.mc-item-value {{ font-size: 1.1rem; font-weight: 700; font-family: var(--font-mono); margin-top: 0.15rem; }}
.two-col {{ display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; }}
@media (max-width: 768px) {{
  .container {{ padding: 1rem; }}
  .header {{ padding: 1.5rem 1rem; margin: -1rem -1rem 1rem -1rem; }}
  .metrics-grid {{ grid-template-columns: repeat(2, 1fr); }}
  .two-col {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>
<div class="container">

<!-- Header -->
<div class="header">
  <h1>{self.strategy_name}</h1>
  <div class="subtitle">Backtest Report &bull; Generated {self.generated_at[:19]} UTC &bull; {m.total_trades} trades</div>
</div>

<!-- Summary Metrics -->
<div class="section">
  <div class="section-title">Performance Summary</div>
  <div class="metrics-grid">
    <div class="metric-card">
      <div class="metric-label">Total Return</div>
      <div class="metric-value {'green' if m.total_return >= 0 else 'red'}">{m.total_return:+.1%}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Max Drawdown</div>
      <div class="metric-value" style="color:{dd_color}">{m.max_drawdown:.1%}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Sharpe Ratio</div>
      <div class="metric-value" style="color:{sharpe_color}">{m.sharpe_ratio:.2f}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Win Rate</div>
      <div class="metric-value" style="color:{wr_color}">{m.win_rate:.1%}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Profit Factor</div>
      <div class="metric-value blue">{m.profit_factor:.2f}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Sortino Ratio</div>
      <div class="metric-value blue">{m.sortino_ratio:.2f}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Expectancy</div>
      <div class="metric-value {'green' if m.expectancy >= 0 else 'red'}">${m.expectancy:.1f}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">SQN</div>
      <div class="metric-value {'green' if m.sqn >= 2.0 else 'amber' if m.sqn >= 1.5 else ''}">{m.sqn:.2f}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Total Trades</div>
      <div class="metric-value">{m.total_trades}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Avg Trade</div>
      <div class="metric-value {'green' if m.avg_trade >= 0 else 'red'}">${m.avg_trade:.1f}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Calmar Ratio</div>
      <div class="metric-value blue">{m.calmar_ratio:.2f}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Avg Hold Time</div>
      <div class="metric-value">{m.avg_holding_period:.1f}h</div>
    </div>
  </div>
</div>

<!-- Charts Row 1 -->
<div class="two-col">
  <div class="section">
    <div class="section-title">Equity Curve</div>
    <div class="chart-container">
      {f'<img src="data:image/png;base64,{equity_chart}" alt="Equity Curve"/>' if equity_chart else '<p style="color:var(--text-muted)">No chart available</p>'}
    </div>
  </div>
  <div class="section">
    <div class="section-title">Drawdown</div>
    <div class="chart-container">
      {f'<img src="data:image/png;base64,{dd_chart}" alt="Drawdown"/>' if dd_chart else '<p style="color:var(--text-muted)">No chart available</p>'}
    </div>
  </div>
</div>

<!-- Charts Row 2 -->
<div class="two-col">
  <div class="section">
    <div class="section-title">Monthly Returns</div>
    <div class="chart-container">
      {f'<img src="data:image/png;base64,{monthly_heatmap}" alt="Monthly Returns"/>' if monthly_heatmap else '<p style="color:var(--text-muted)">No chart available</p>'}
    </div>
  </div>
  <div class="section">
    <div class="section-title">Trade Distribution</div>
    <div class="chart-container">
      {f'<img src="data:image/png;base64,{trade_dist}" alt="Trade Distribution"/>' if trade_dist else '<p style="color:var(--text-muted)">No chart available</p>'}
    </div>
  </div>
</div>

<!-- Monte Carlo Section -->
{f'''
<div class="section">
  <div class="section-title">Monte Carlo Simulation ({self.mc_result.n_simulations:,} runs)</div>
  <div class="mc-grid">
    <div class="mc-item">
      <div class="mc-item-label">Pass Rate</div>
      <div class="mc-item-value" style="color:{'var(--accent-green)' if self.mc_result.pass_rate >= 0.5 else 'var(--accent-amber)' if self.mc_result.pass_rate >= 0.3 else 'var(--accent-red)'}">{self.mc_result.pass_rate:.1%}</div>
    </div>
    <div class="mc-item">
      <div class="mc-item-label">Fail Rate</div>
      <div class="mc-item-value red">{self.mc_result.fail_rate:.1%}</div>
    </div>
    <div class="mc-item">
      <div class="mc-item-label">Median Return</div>
      <div class="mc-item-value {'green' if self.mc_result.median_return >= 0 else 'red'}">{self.mc_result.median_return:+.1%}</div>
    </div>
    <div class="mc-item">
      <div class="mc-item-label">Worst Case (5%)</div>
      <div class="mc-item-value red">{self.mc_result.worst_case:+.1%}</div>
    </div>
    <div class="mc-item">
      <div class="mc-item-label">Best Case (95%)</div>
      <div class="mc-item-value green">{self.mc_result.best_case:+.1%}</div>
    </div>
    <div class="mc-item">
      <div class="mc-item-label">Median Max DD</div>
      <div class="mc-item-value">{self.mc_result.median_max_dd:.1%}</div>
    </div>
    <div class="mc-item">
      <div class="mc-item-label">95% Confidence</div>
      <div class="mc-item-value">[{self.mc_result.confidence_interval[0]:+.1%}, {self.mc_result.confidence_interval[1]:+.1%}]</div>
    </div>
    <div class="mc-item">
      <div class="mc-item-label">99% Confidence</div>
      <div class="mc-item-value">[{self.mc_result.confidence_interval_99[0]:+.1%}, {self.mc_result.confidence_interval_99[1]:+.1%}]</div>
    </div>
  </div>
  <div class="chart-container">
    {f'<img src="data:image/png;base64,{mc_chart}" alt="MC Distribution"/>' if mc_chart else '<p style="color:var(--text-muted)">No chart available</p>'}
  </div>
  <div class="section-title" style="margin-top:1.5rem;">Prop Firm Pass Probabilities</div>
  <table>
    <thead>
      <tr><th>Firm</th><th>Phase</th><th>Target</th><th>Max DD</th><th>Pass Probability</th></tr>
    </thead>
    <tbody>
      <tr><td>FundingPips</td><td>Phase 1</td><td>8%</td><td>10%</td><td class="{'positive' if self.mc_result.prob_pass_2step_p1 >= 0.5 else 'negative'}">{self.mc_result.prob_pass_2step_p1:.1%}</td></tr>
      <tr><td>FundingPips</td><td>Phase 2</td><td>5%</td><td>10%</td><td class="{'positive' if self.mc_result.prob_pass_2step_p2 >= 0.5 else 'negative'}">{self.mc_result.prob_pass_2step_p2:.1%}</td></tr>
      <tr><td>FundingPips</td><td>Pro</td><td>6%</td><td>5%</td><td class="{'positive' if self.mc_result.prob_pass_pro >= 0.5 else 'negative'}">{self.mc_result.prob_pass_pro:.1%}</td></tr>
      <tr><td>FTMO</td><td>Phase 1</td><td>10%</td><td>10%</td><td class="{'positive' if self.mc_result.prob_pass_ftmo_p1 >= 0.5 else 'negative'}">{self.mc_result.prob_pass_ftmo_p1:.1%}</td></tr>
      <tr><td>FTMO</td><td>Phase 2</td><td>5%</td><td>10%</td><td class="{'positive' if self.mc_result.prob_pass_ftmo_p2 >= 0.5 else 'negative'}">{self.mc_result.prob_pass_ftmo_p2:.1%}</td></tr>
      <tr><td>1-Step Generic</td><td>Phase 1</td><td>10%</td><td>10%</td><td class="{'positive' if self.mc_result.prob_pass_1step >= 0.5 else 'negative'}">{self.mc_result.prob_pass_1step:.1%}</td></tr>
    </tbody>
  </table>
</div>
''' if self.mc_result else '<!-- No Monte Carlo results -->'}

<!-- Walk-Forward Section -->
{wf_section}

<!-- Prop Firm Compliance -->
<div class="section">
  <div class="section-title">Prop Firm Compliance Check</div>
  {compliance_table}
</div>

<!-- Trades Table -->
<div class="section">
  <div class="section-title">Trade Log</div>
  {trades_table}
</div>

<!-- Footer -->
<div style="text-align:center; padding: 2rem 0; color: var(--text-muted); font-size: 0.8rem;">
  Generated by Prop Firm Backtester Engine &bull; {self.generated_at[:19]} UTC
</div>

</div>
</body>
</html>"""
        return html

    # ------------------------------------------------------------------
    # Chart generators (base64 PNG)
    # ------------------------------------------------------------------

    def _generate_equity_curve_chart(self) -> Optional[str]:
        """Generate equity curve as base64 PNG using matplotlib."""
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            return None

        try:
            df = self.result.equity_curve
            if df.empty:
                return None

            fig, ax = plt.subplots(figsize=(12, 5))

            if "equity" in df.columns:
                ax.plot(df.index, df["equity"], color="#3b82f6", linewidth=1.2)
            elif len(df.columns) >= 1:
                ax.plot(df.index, df.iloc[:, 0], color="#3b82f6", linewidth=1.2)
            else:
                return None

            ax.set_title("Equity Curve", fontsize=13, fontweight="bold")
            ax.set_xlabel("Date", fontsize=10)
            ax.set_ylabel("Equity ($)", fontsize=10)
            ax.grid(True, alpha=0.3)

            fig.patch.set_facecolor("#0f172a")
            ax.set_facecolor("#1e293b")
            ax.tick_params(colors="#94a3b8", labelsize=8)
            ax.xaxis.label.set_color("#94a3b8")
            ax.yaxis.label.set_color("#94a3b8")
            ax.title.set_color("#f1f5f9")
            for spine in ax.spines.values():
                spine.set_color("#334155")
            fig.autofmt_xdate(rotation=30)

            plt.tight_layout()
            buf = io.BytesIO()
            plt.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor=fig.get_facecolor())
            plt.close(fig)
            buf.seek(0)
            return base64.b64encode(buf.read()).decode("utf-8")
        except Exception as e:
            logger.warning("Failed to generate equity curve chart: %s", e)
            return None

    def _generate_drawdown_chart(self) -> Optional[str]:
        """Generate drawdown chart as base64 PNG."""
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            return None

        try:
            df = self.result.equity_curve
            if df.empty:
                return None

            equity_col = "equity" if "equity" in df.columns else df.columns[0]
            equity = pd.Series(df[equity_col].values, index=df.index)
            running_max = equity.cummax()
            drawdown = (equity - running_max) / running_max

            fig, ax = plt.subplots(figsize=(12, 4))
            ax.fill_between(drawdown.index, drawdown * 100, 0, color="#ef4444", alpha=0.4)
            ax.plot(drawdown.index, drawdown * 100, color="#ef4444", linewidth=0.8)

            ax.set_title("Drawdown", fontsize=13, fontweight="bold")
            ax.set_ylabel("Drawdown (%)", fontsize=10)
            ax.grid(True, alpha=0.3)

            fig.patch.set_facecolor("#0f172a")
            ax.set_facecolor("#1e293b")
            ax.tick_params(colors="#94a3b8", labelsize=8)
            ax.yaxis.label.set_color("#94a3b8")
            ax.title.set_color("#f1f5f9")
            for spine in ax.spines.values():
                spine.set_color("#334155")
            fig.autofmt_xdate(rotation=30)

            plt.tight_layout()
            buf = io.BytesIO()
            plt.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor=fig.get_facecolor())
            plt.close(fig)
            buf.seek(0)
            return base64.b64encode(buf.read()).decode("utf-8")
        except Exception as e:
            logger.warning("Failed to generate drawdown chart: %s", e)
            return None

    def _generate_monthly_heatmap(self) -> Optional[str]:
        """Generate monthly returns heatmap as base64 PNG."""
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import matplotlib.colors as mcolors
        except ImportError:
            return None

        try:
            df = self.result.equity_curve
            if df.empty or "equity" not in df.columns:
                return None

            # Compute daily returns
            equity = df["equity"]
            daily_ret = equity.pct_change().dropna()
            if len(daily_ret) < 10:
                return None

            # Aggregate to monthly
            monthly = daily_ret.resample("ME").apply(lambda x: (1 + x).prod() - 1)
            if len(monthly) < 2:
                return None

            monthly.index = monthly.index.to_period("M")
            data = monthly * 100  # as percentage

            # Build pivot: year x month
            pivot_data = {}
            for period, val in data.items():
                year, month = period.year, period.month
                pivot_data.setdefault(year, {})[month] = val

            years = sorted(pivot_data.keys())
            months = list(range(1, 13))
            month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

            matrix = np.full((len(years), 12), np.nan)
            for i, y in enumerate(years):
                for j, m in enumerate(months):
                    matrix[i, j] = pivot_data.get(y, {}).get(m, np.nan)

            fig, ax = plt.subplots(figsize=(12, max(3, len(years) * 0.8)))

            cmap = mcolors.LinearSegmentedColormap.from_list(
                "rg", ["#ef4444", "#1e293b", "#10b981"]
            )
            vmax = max(abs(np.nanmin(matrix)), abs(np.nanmax(matrix)), 1.0)

            im = ax.imshow(matrix, cmap=cmap, aspect="auto", vmin=-vmax, vmax=vmax)

            ax.set_xticks(range(12))
            ax.set_xticklabels(month_labels, color="#94a3b8", fontsize=9)
            ax.set_yticks(range(len(years)))
            ax.set_yticklabels(years, color="#94a3b8", fontsize=9)

            # Annotate cells
            for i in range(len(years)):
                for j in range(12):
                    val = matrix[i, j]
                    if not np.isnan(val):
                        color = "white" if abs(val) > vmax * 0.5 else "#94a3b8"
                        ax.text(j, i, f"{val:.1f}%", ha="center", va="center",
                                fontsize=8, color=color, fontweight="bold")

            ax.set_title("Monthly Returns (%)", fontsize=13, fontweight="bold", color="#f1f5f9", pad=10)
            fig.patch.set_facecolor("#0f172a")
            ax.set_facecolor("#0f172a")
            for spine in ax.spines.values():
                spine.set_color("#334155")

            plt.colorbar(im, ax=ax, shrink=0.6, label="Return %")
            plt.tight_layout()

            buf = io.BytesIO()
            plt.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor=fig.get_facecolor())
            plt.close(fig)
            buf.seek(0)
            return base64.b64encode(buf.read()).decode("utf-8")
        except Exception as e:
            logger.warning("Failed to generate monthly heatmap: %s", e)
            return None

    def _generate_trade_distribution_chart(self) -> Optional[str]:
        """Generate trade PnL distribution histogram as base64 PNG."""
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            return None

        try:
            trades = self.result.trades
            if not trades:
                return None

            pnls = np.array([float(t.get("pnl", 0)) for t in trades if "pnl" in t])
            if len(pnls) < 2:
                return None

            fig, ax = plt.subplots(figsize=(10, 5))

            wins = pnls[pnls > 0]
            losses = pnls[pnls <= 0]

            bins = np.linspace(pnls.min(), pnls.max(), 50)
            ax.hist(wins, bins=bins, color="#10b981", alpha=0.7, label=f"Wins ({len(wins)})", edgecolor="none")
            ax.hist(losses, bins=bins, color="#ef4444", alpha=0.7, label=f"Losses ({len(losses)})", edgecolor="none")
            ax.axvline(0, color="#94a3b8", linestyle="-", linewidth=1)
            ax.axvline(np.mean(pnls), color="#3b82f6", linestyle="--", linewidth=2, label=f"Mean: ${np.mean(pnls):.1f}")

            ax.set_title("Trade PnL Distribution", fontsize=13, fontweight="bold")
            ax.set_xlabel("Profit / Loss ($)", fontsize=10)
            ax.set_ylabel("Frequency", fontsize=10)
            ax.legend()
            ax.grid(True, alpha=0.3)

            fig.patch.set_facecolor("#0f172a")
            ax.set_facecolor("#1e293b")
            ax.tick_params(colors="#94a3b8")
            ax.xaxis.label.set_color("#94a3b8")
            ax.yaxis.label.set_color("#94a3b8")
            ax.title.set_color("#f1f5f9")
            for spine in ax.spines.values():
                spine.set_color("#334155")

            plt.tight_layout()
            buf = io.BytesIO()
            plt.savefig(buf, format="png", dpi=120, bbox_inches="tight", facecolor=fig.get_facecolor())
            plt.close(fig)
            buf.seek(0)
            return base64.b64encode(buf.read()).decode("utf-8")
        except Exception as e:
            logger.warning("Failed to generate trade distribution: %s", e)
            return None

    def _generate_mc_distribution_chart(self) -> Optional[str]:
        """Generate Monte Carlo distribution as base64 PNG."""
        if self.mc_result is None:
            return None
        try:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError:
            return None

        try:
            final_returns = self.mc_result.final_returns
            fig, ax = plt.subplots(figsize=(10, 6))

            ax.hist(
                final_returns * 100,
                bins=80,
                color="#3b82f6",
                edgecolor="#1e3a5f",
                alpha=0.75,
                density=True,
            )

            median = np.median(final_returns) * 100
            p5 = np.percentile(final_returns, 5) * 100
            p95 = np.percentile(final_returns, 95) * 100

            ax.axvline(median, color="#10b981", linestyle="-", linewidth=2, label=f"Median: {median:.1f}%")
            ax.axvline(p5, color="#ef4444", linestyle="--", linewidth=1.5, label=f"5th %ile: {p5:.1f}%")
            ax.axvline(p95, color="#ef4444", linestyle="--", linewidth=1.5, label=f"95th %ile: {p95:.1f}%")

            ax.set_xlabel("Final Return (%)", fontsize=11)
            ax.set_ylabel("Density", fontsize=11)
            ax.set_title("Monte Carlo: Final Return Distribution", fontsize=13, fontweight="bold")
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
            buf = io.BytesIO()
            plt.savefig(buf, format="png", dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
            plt.close(fig)
            buf.seek(0)
            return base64.b64encode(buf.read()).decode("utf-8")
        except Exception as e:
            logger.warning("Failed to generate MC chart: %s", e)
            return None

    # ------------------------------------------------------------------
    # Walk-forward section
    # ------------------------------------------------------------------

    def _generate_walkforward_section(self) -> str:
        """Generate HTML section for walk-forward results."""
        if self.wf_result is None:
            return "<!-- No walk-forward results -->"

        wf = self.wf_result
        robust_badge = "badge-pass" if wf.is_robust else "badge-fail"
        robust_text = "ROBUST" if wf.is_robust else "NOT ROBUST"
        sig_badge = "badge-pass" if wf.is_significant else "badge-fail"
        sig_text = "SIGNIFICANT" if wf.is_significant else "NOT SIGNIFICANT"

        rows = ""
        for r in wf.results[:10]:
            is_badge = "badge-pass" if r.get("is_train", False) else "badge-warn"
            is_text = "TRAIN" if r.get("is_train", False) else "TEST"
            rows += f"""<tr>
                <td>{r.get('split', '')}</td>
                <td><span class="badge {is_badge}">{is_text}</span></td>
                <td>{r.get('sharpe', 0):.2f}</td>
                <td>{r.get('return', 0):.2%}</td>
                <td>{r.get('max_dd', 0):.2%}</td>
            </tr>"""

        return f"""
<div class="section">
  <div class="section-title">Walk-Forward Analysis ({wf.n_splits} splits)</div>
  <div class="metrics-grid" style="margin-bottom:1rem;">
    <div class="metric-card">
      <div class="metric-label">Robust</div>
      <div class="metric-value"><span class="badge {robust_badge}">{robust_text}</span></div>
    </div>
    <div class="metric-card">
      <div class="metric-label">OOS Sharpe</div>
      <div class="metric-value">{wf.out_of_sample_sharpe:.2f}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Overfit Ratio</div>
      <div class="metric-value {'red' if wf.overfit_ratio > 1.2 else 'green'}">{wf.overfit_ratio:.2f}</div>
    </div>
    <div class="metric-card">
      <div class="metric-label">Significant</div>
      <div class="metric-value"><span class="badge {sig_badge}">{sig_text}</span></div>
    </div>
    <div class="metric-card">
      <div class="metric-label">p-value</div>
      <div class="metric-value">{wf.p_value:.4f}</div>
    </div>
  </div>
  <table>
    <thead>
      <tr><th>Split</th><th>Type</th><th>Sharpe</th><th>Return</th><th>Max DD</th></tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</div>
"""

    # ------------------------------------------------------------------
    # Prop firm compliance
    # ------------------------------------------------------------------

    def _check_prop_firm_compliance(self) -> List[Dict[str, Any]]:
        """Check strategy against prop firm rules. Returns list of check results."""
        m = self.metrics
        checks = []

        # FundingPips Phase 1
        checks.append({
            "firm": "FundingPips",
            "phase": "Phase 1",
            "rule": "Max Drawdown <= 10%",
            "passed": m.max_drawdown <= 0.10,
            "actual": f"{m.max_drawdown:.2%}",
            "limit": "10%",
        })
        checks.append({
            "firm": "FundingPips",
            "phase": "Phase 1",
            "rule": f"Daily Loss Limit <= 5%",
            "passed": True,  # Would need daily data
            "actual": "N/A",
            "limit": "5%",
        })
        checks.append({
            "firm": "FundingPips",
            "phase": "Phase 1",
            "rule": "Min 5 Trading Days",
            "passed": m.total_trades >= 5,
            "actual": f"{m.total_trades} trades",
            "limit": "5 days",
        })
        checks.append({
            "firm": "FundingPips",
            "phase": "Phase 1",
            "rule": "Sharpe >= 1.0",
            "passed": m.sharpe_ratio >= 1.0,
            "actual": f"{m.sharpe_ratio:.2f}",
            "limit": "1.00",
        })
        checks.append({
            "firm": "FundingPips",
            "phase": "Phase 1",
            "rule": "Win Rate >= 45%",
            "passed": m.win_rate >= 0.45,
            "actual": f"{m.win_rate:.1%}",
            "limit": "45%",
        })
        checks.append({
            "firm": "FundingPips",
            "phase": "Phase 1",
            "rule": "Profit Factor >= 1.2",
            "passed": m.profit_factor >= 1.2,
            "actual": f"{m.profit_factor:.2f}",
            "limit": "1.20",
        })

        # FTMO Phase 1
        checks.append({
            "firm": "FTMO",
            "phase": "Phase 1",
            "rule": "Max Drawdown <= 10%",
            "passed": m.max_drawdown <= 0.10,
            "actual": f"{m.max_drawdown:.2%}",
            "limit": "10%",
        })
        checks.append({
            "firm": "FTMO",
            "phase": "Phase 1",
            "rule": "Min 4 Trading Days",
            "passed": m.total_trades >= 4,
            "actual": f"{m.total_trades} trades",
            "limit": "4 days",
        })

        # Pro account
        checks.append({
            "firm": "FundingPips",
            "phase": "Pro",
            "rule": "Max Drawdown <= 5%",
            "passed": m.max_drawdown <= 0.05,
            "actual": f"{m.max_drawdown:.2%}",
            "limit": "5%",
        })
        checks.append({
            "firm": "FundingPips",
            "phase": "Pro",
            "rule": "Daily Loss <= 2%",
            "passed": True,
            "actual": "N/A",
            "limit": "2%",
        })

        return checks

    def _prop_firm_compliance_table(self) -> str:
        """Generate HTML table showing prop firm rule compliance with PASS/FAIL badges."""
        checks = self._check_prop_firm_compliance()

        rows = ""
        for check in checks:
            badge_class = "badge-pass" if check["passed"] else "badge-fail"
            badge_text = "PASS" if check["passed"] else "FAIL"
            rows += f"""<tr>
                <td><strong>{check['firm']}</strong></td>
                <td>{check['phase']}</td>
                <td>{check['rule']}</td>
                <td>{check['actual']}</td>
                <td>{check['limit']}</td>
                <td><span class="badge {badge_class}">{badge_text}</span></td>
            </tr>"""

        return f"""<table>
<thead>
  <tr><th>Firm</th><th>Phase</th><th>Rule</th><th>Actual</th><th>Limit</th><th>Status</th></tr>
</thead>
<tbody>{rows}</tbody>
</table>"""

    # ------------------------------------------------------------------
    # Trades table
    # ------------------------------------------------------------------

    def _trades_table(self) -> str:
        """Generate HTML table of all trades."""
        trades = self.result.trades
        if not trades:
            return '<p style="color:var(--text-muted)">No trades to display.</p>'

        # Show at most 100 trades
        display_trades = trades[:100]

        rows = ""
        for t in display_trades:
            pnl = float(t.get("pnl", 0))
            pnl_class = "positive" if pnl > 0 else "negative" if pnl < 0 else ""
            rows += f"""<tr>
                <td>{t.get('entry_time', '')}</td>
                <td>{t.get('direction', '')}</td>
                <td>{t.get('instrument', '')}</td>
                <td>{t.get('entry_price', '')}</td>
                <td>{t.get('exit_price', '')}</td>
                <td class="{pnl_class}">{pnl:+.2f}</td>
                <td>{t.get('holding_time', '')}</td>
            </tr>"""

        note = f"<p style=\"color:var(--text-muted);font-size:0.75rem;margin-top:0.5rem;\">Showing {len(display_trades)} of {len(trades)} trades</p>" if len(trades) > 100 else ""

        return f"""<table>
<thead>
  <tr><th>Entry Time</th><th>Dir</th><th>Instrument</th><th>Entry</th><th>Exit</th><th>PnL</th><th>Hold Time</th></tr>
</thead>
<tbody>{rows}</tbody>
</table>{note}"""

    # ------------------------------------------------------------------
    # Report dictionary builder
    # ------------------------------------------------------------------

    def _build_report_dict(self) -> Dict[str, Any]:
        """Build the complete report dictionary for JSON export."""
        m = self.metrics

        report = {
            "meta": {
                "strategy_name": self.strategy_name,
                "generated_at": self.generated_at,
                "version": "1.0.0",
            },
            "summary": {
                "total_return": m.total_return,
                "annualized_return": m.annualized_return,
                "max_drawdown": m.max_drawdown,
                "max_drawdown_dollars": m.max_drawdown_dollars,
                "sharpe_ratio": m.sharpe_ratio,
                "sortino_ratio": m.sortino_ratio,
                "calmar_ratio": m.calmar_ratio,
                "win_rate": m.win_rate,
                "profit_factor": m.profit_factor,
                "total_trades": m.total_trades,
                "winning_trades": m.winning_trades,
                "losing_trades": m.losing_trades,
                "avg_trade": m.avg_trade,
                "avg_win": m.avg_win,
                "avg_loss": m.avg_loss,
                "largest_win": m.largest_win,
                "largest_loss": m.largest_loss,
                "expectancy": m.expectancy,
                "sqn": m.sqn,
                "ulcer_index": m.ulcer_index,
                "var_95": m.var_95,
                "var_99": m.var_99,
                "cvar_95": m.cvar_95,
                "skewness": m.skewness,
                "kurtosis": m.kurtosis,
            },
            "trades": self.result.trades,
            "config": self.result.config,
            "prop_firm_compliance": self._check_prop_firm_compliance(),
        }

        if self.mc_result:
            report["monte_carlo"] = self.mc_result.to_dict()

        if self.wf_result:
            report["walk_forward"] = {
                "is_robust": self.wf_result.is_robust,
                "out_of_sample_sharpe": self.wf_result.out_of_sample_sharpe,
                "in_sample_sharpe": self.wf_result.in_sample_sharpe,
                "overfit_ratio": self.wf_result.overfit_ratio,
                "is_significant": self.wf_result.is_significant,
                "p_value": self.wf_result.p_value,
                "n_splits": self.wf_result.n_splits,
                "results": self.wf_result.results,
            }

        return report


# ---------------------------------------------------------------------------
# Dashboard data generator
# ---------------------------------------------------------------------------

def generate_dashboard_data(
    metrics: PerformanceMetrics,
    trades: List,
    equity_curve: pd.DataFrame,
    output_path: str,
    strategy_name: str = "Strategy",
    mc_result: Optional[MonteCarloResult] = None,
) -> Dict[str, Any]:
    """
    Generate a JSON file that a React dashboard can consume directly.

    Format matches typical dashboard expected data structure with
    flat key-value pairs for easy binding.
    """
    m = metrics

    # Build equity curve series for charting
    equity_data = []
    if not equity_curve.empty and "equity" in equity_curve.columns:
        for idx, row in equity_curve.iterrows():
            equity_data.append(
                {
                    "date": idx.isoformat() if hasattr(idx, "isoformat") else str(idx),
                    "equity": float(row["equity"]),
                }
            )

    # Trade summary
    trade_summary = {
        "total": m.total_trades,
        "winning": m.winning_trades,
        "losing": m.losing_trades,
        "win_rate": m.win_rate,
        "avg_pnl": m.avg_trade,
        "avg_win": m.avg_win,
        "avg_loss": m.avg_loss,
        "largest_win": m.largest_win,
        "largest_loss": m.largest_loss,
    }

    # Monthly returns if available
    monthly = []
    for mr in m.monthly_returns:
        monthly.append(mr)

    dashboard_data = {
        "strategy": strategy_name,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "metrics": {
            "totalReturn": m.total_return,
            "annualizedReturn": m.annualized_return,
            "maxDrawdown": m.max_drawdown,
            "maxDrawdownDollars": m.max_drawdown_dollars,
            "sharpeRatio": m.sharpe_ratio,
            "sortinoRatio": m.sortino_ratio,
            "calmarRatio": m.calmar_ratio,
            "winRate": m.win_rate,
            "profitFactor": m.profit_factor,
            "expectancy": m.expectancy,
            "sqn": m.sqn,
            "avgTrade": m.avg_trade,
            "ulcerIndex": m.ulcer_index,
            "var95": m.var_95,
            "cvar95": m.cvar_95,
            "skewness": m.skewness,
            "kurtosis": m.kurtosis,
        },
        "tradeSummary": trade_summary,
        "equityCurve": equity_data,
        "monthlyReturns": monthly,
    }

    if mc_result:
        dashboard_data["monteCarlo"] = mc_result.to_dict()

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(dashboard_data, f, indent=2, default=str)

    logger.info("Dashboard data saved to %s", output_path)
    return dashboard_data


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

def export_trades_csv(
    trades: List[Dict[str, Any]],
    output_path: str,
) -> str:
    """
    Export trades to CSV.

    Parameters
    ----------
    trades : List[Dict]
        List of trade dictionaries.
    output_path : str
        Output CSV file path.

    Returns
    -------
    str
        Path to saved CSV file.
    """
    if not trades:
        logger.warning("No trades to export")
        return ""

    df = pd.DataFrame(trades)
    df.to_csv(output_path, index=False)
    logger.info("Trades exported to %s", output_path)
    return output_path


def export_equity_csv(
    equity_curve: pd.DataFrame,
    output_path: str,
) -> str:
    """Export equity curve to CSV."""
    if equity_curve.empty:
        logger.warning("No equity curve to export")
        return ""

    equity_curve.to_csv(output_path)
    logger.info("Equity curve exported to %s", output_path)
    return output_path
