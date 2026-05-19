# Research Synthesis: Production-Ready Prop Firm Trading Bot

## Date: 2026-05-20

---

## Key Insight: Only 10% Pass Prop Firm Challenges

The #1 finding across all research: **only 10% of traders pass prop firm evaluations**, and most failures come from **drawdown breaches, not profit shortfalls**. The bot must prioritize capital preservation above profit generation.

---

## 1. STRATEGY RESEARCH — Top 16 Strategies Documented

### Top 5 by Prop Firm Suitability Score

| Rank | Strategy | Score | WR | PF | Max DD |
|------|----------|-------|-----|-----|--------|
| 1 | Multi-Timeframe Confluence Trading | 8.4/10 | 60-68% | 2.0-2.8 | <12% |
| 2 | Top-Down Trend + Pullback | 8.4/10 | 73% | 2.0 | 10% |
| 3 | Gold SMC (London Killzone) | 8.4/10 | 82% | 3.2 | Low |
| 4 | FVG Mitigation Entry | 8.2/10 | 60-65% | 1.8-2.5 | Low |
| 5 | Liquidity Sweep + FVG Reclaim | 8.0/10 | 61.2% | 2.17 | Moderate |

### Critical Finding: Volume-Based Strategies Work

| Strategy Type | Win Rate | Best Market |
|---------------|----------|-------------|
| Volume Profile POC bounce | 70-75% | Ranging |
| VWAP mean reversion | 55-65% | Intraday |
| CVD divergence | 55-65% | Reversals |
| Relative volume breakout | 50-60% | Breakouts |

### Key Technical Concepts for Implementation

**1. Volume Profile (highest priority)**
- POC (Point of Control): price with most volume — acts as magnet
- Value Area (VAH/VAL): 70% of volume range — support/resistance
- HVNs (High Volume Nodes): congestion zones — expect bounce
- LVNs (Low Volume Nodes): gaps — price moves fast through

**2. Volume Delta / CVD**
- Delta = ask volume - bid volume per bar
- CVD (Cumulative) divergence from price = reversal signal
- Absorption: high delta but price doesn't move = institutional defending

**3. Smart Money Concepts (SMC)**
- BOS (Break of Structure): price breaks previous high/low
- CHoCH (Change of Character): shift from bullish to bearish structure
- FVG (Fair Value Gap): 3-candle imbalance, ~70-80% fill rate
- Order Blocks: last opposing candle before a strong move
- Liquidity Sweeps: stops run above/below structure before reversal

**4. Multi-Timeframe Confluence**
- H4 bias → H1 setup → M15 entry → M5 confirmation
- All timeframes must align for highest probability entry
- Reduces false signals by 40-60%

---

## 2. COMPLIANCE & RISK — Top 20 Critical Rules

### The Three Killers (40-50% of failures)

| # | Rule | Impact | Prevention |
|---|------|--------|------------|
| 1 | Daily Drawdown Breach | 40-50% failures | Hard stop at 60% of limit |
| 2 | Max Drawdown Breach | 25-30% failures | Circuit breaker at 80% of limit |
| 3 | Consistency Rule Violation | 15-20% failures | No single day >30% of profits |

### Risk Management Must-Haves

**Kelly Criterion (Half-Kelly for safety):**
```
f = (p*b - q) / b
where p = win rate, q = loss rate (1-p), b = avg win / avg loss
Position size = f/2 * account * risk_per_trade
```

**Portfolio Heat (Alexander Elder's 6% rule):**
- Never risk more than 6% of account across all open positions
- If heat exceeds 4% → reduce new position sizes
- If heat exceeds 5.5% → stop taking new trades

**Circuit Breaker System (5-tier):**
| Level | Condition | Action |
|-------|-----------|--------|
| 1 | DD > 50% of limit | Reduce risk to 50% |
| 2 | DD > 60% of limit | Reduce risk to 25% |
| 3 | DD > 70% of limit | Reduce risk to 10% |
| 4 | DD > 80% of limit | STOP all new trades |
| 5 | DD > 90% of limit | EMERGENCY close all |

### Prop Firm-Specific Gotchas

- **FundingPips**: Consistency rule is strict — no single trade >30% of daily profit
- **The5%ers**: 3-step means phase tracking is essential
- **FTMO**: Different rules for Challenge vs Verification
- **Apex**: No daily loss limit (futures only)
- **FundedNext**: Instant funding option available

---

## 3. UI/UX DESIGN — Complete Design System

### Color Palette (Dark Theme)

| Token | Hex | Usage |
|-------|-----|-------|
| bg-primary | #0B0E11 | Main background |
| bg-surface | #151A21 | Cards, panels |
| bg-elevated | #1E2530 | Hover states, active |
| border | #2A3441 | Borders, dividers |
| text-primary | #E8ECF1 | Headlines, primary data |
| text-secondary | #8B95A5 | Labels, descriptions |
| text-muted | #5C6677 | Timestamps, inactive |
| buy | #00C853 | Profits, buy signals |
| sell | #FF5252 | Losses, sell signals |
| warning | #FFB300 | Alerts, warnings |
| info | #448AFF | Information, links |
| accent | #F0B90B | Primary actions, highlights |
| chart-1 | #2962FF | Line 1 |
| chart-2 | #00C853 | Line 2 |
| chart-3 | #FF6D00 | Line 3 |

### Typography
- Primary: Inter (sans-serif) for UI
- Monospace: JetBrains Mono for numbers/prices
- Scale: 10px micro → 12px small → 14px body → 16px medium → 20px large → 24px xl → 32px display

### Layout Pattern
- Sidebar navigation (left, 64px collapsed, 240px expanded)
- Main content area (flexible)
- Right panel (optional: watchlist, order entry)
- Top bar: account summary, connection status, alerts

### Component Specs
- **Account Card**: Balance large display, equity below, P&L color-coded, margin bar
- **Position Table**: Live P&L flash green/red, sticky headers, sortable
- **Strategy Cards**: Toggle switch, sparkline mini-chart, performance badges
- **Risk Gauge**: Circular progress ring, color-coded zones
- **Job Queue**: Progress bars, status badges, cancel buttons
- **Toast Notifications**: 5 variants (success/error/warning/info/trade)

---

## 4. IMPLEMENTATION ROADMAP

### Phase 1: Risk Manager Upgrade (highest impact)
- [ ] Implement circuit breaker (5-tier)
- [ ] Add Kelly Criterion position sizing
- [ ] Add portfolio heat tracking
- [ ] Add consistency score calculator
- [ ] Add drawdown-based position reduction

### Phase 2: Strategy Enhancement
- [ ] Add Volume Profile indicator (POC, VAH, VAL, HVN, LVN)
- [ ] Add Volume Delta / CVD indicator
- [ ] Add FVG (Fair Value Gap) detection
- [ ] Add Order Block detection
- [ ] Add Liquidity Sweep detection
- [ ] Add multi-timeframe confirmation
- [ ] Add VWAP strategies

### Phase 3: Backend Architecture
- [ ] Add WebSocket for real-time data
- [ ] Add real-time position sync from MetaAPI
- [ ] Add trade execution engine
- [ ] Add correlation calculator between strategies
- [ ] Add portfolio-level risk tracking

### Phase 4: UI/UX Overhaul
- [ ] Implement new design system (colors, typography)
- [ ] Add sidebar navigation
- [ ] Add real-time chart component
- [ ] Redesign all cards with new specs
- [ ] Add sparkline charts to strategy cards
- [ ] Add risk gauge component
- [ ] Add proper loading skeletons
- [ ] Add keyboard shortcuts
