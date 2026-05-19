# Prop Firm Compliance & Risk Management Best Practices
## Comprehensive Research for Trading Bot Implementation

**Research Date:** 2025  
**Sources:** 20+ industry sources, prop firm rulebooks, trading statistics  
**Purpose:** Actionable, code-ready rules for bot-based prop firm trading

---

# TOP 20 MOST CRITICAL RULES/TECHNIQUES - PRIORITIZED

| Rank | Rule/Technique | Severity | Category | Est. Failure Rate |
|------|---------------|----------|----------|-------------------|
| 1 | Daily Drawdown Limit Breach | CRITICAL | Compliance | 40-50% of failures |
| 2 | Max/Trailing Drawdown Breach | CRITICAL | Compliance | 25-30% of failures |
| 3 | Consistency Rule Violation | CRITICAL | Compliance | 15-20% of failures |
| 4 | Kelly Criterion Position Sizing (Half-Kelly) | CRITICAL | Risk Management | N/A |
| 5 | Risk of Ruin < 1% Target | CRITICAL | Risk Management | N/A |
| 6 | News Trading Ban Violation (Tier 1 Events) | HIGH | Compliance | 5-8% of failures |
| 7 | Martingale/Grid Strategy Detection | HIGH | Compliance | 3-5% of failures |
| 8 | Portfolio Heat Limit (6% Max Open Risk) | HIGH | Risk Management | N/A |
| 9 | Weekend Holding Restriction Violation | HIGH | Compliance | 2-3% of failures |
| 10 | Copy Trading/IP/Device Detection | HIGH | Compliance | 2-3% of failures |
| 11 | Inactivity Rule (30-Day Closure) | MEDIUM | Compliance | 2% of failures |
| 12 | Max Lot Size / Position Limits | MEDIUM | Compliance | 1-2% of failures |
| 13 | HFT/Latency Arbitrage Detection | MEDIUM | Compliance | 1% of failures |
| 14 | Fractional Kelly (1/4 to 1/2) Sizing | MEDIUM | Risk Management | N/A |
| 15 | Correlation-Based Position Reduction | MEDIUM | Risk Management | N/A |
| 16 | Slippage + Spread + Commission Model | MEDIUM | Execution | N/A |
| 17 | Optimal f (Ralph Vince) Sizing | MEDIUM | Risk Management | N/A |
| 18 | Drawdown-Based Position Reduction (50% Rule) | MEDIUM | Risk Management | N/A |
| 19 | Circuit Breaker - Strategy Shutdown | MEDIUM | Risk Management | N/A |
| 20 | Minimum Trading Days Requirement | LOW | Compliance | 1% of failures |

---

# SECTION 1: PROP FIRM HIDDEN RULES & PITFALLS

## Rule: Daily Drawdown Limit Breach
**Priority:** CRITICAL  
**Applies To:** ALL FIRMS (FTMO, FundedNext, FundingPips, The5%ers, Apex, etc.)

### Description
The #1 reason traders fail prop firm challenges (40-50% of all failures). Daily drawdown is the maximum loss allowed in a single trading day. Two calculation methods exist:

**Balance-Based (trader-friendly):**
- Limit = Start-of-Day Balance - (Account Size * Daily Loss %)
- Example: $100k account, 5% daily limit = $5,000 max loss from $100k start
- Floating losses on open trades still count toward equity breach

**Equity-Based (stricter):**
- Limit = Current Equity - (Highest Equity Point * Daily Loss %)
- Example: If equity hits $105k intraday, new limit = $105k - $5k = $100k
- Giving back profits can breach the rule even at break-even

**Key Firm Differences:**
| Firm | Daily Loss | Method |
|------|-----------|--------|
| FTMO | 5% | Equity-based |
| FundedNext Stellar 2-Step | 5% | Equity or balance, whichever is higher |
| FundedNext Stellar 1-Step | 3% | Equity or balance, whichever is higher |
| FundingPips | 3% | Static from starting balance |
| The5%ers High Stakes | 5% | Equity-based |
| Apex Trader Funding | None | No daily drawdown (trailing only) |

### Implementation
```python
def check_daily_drawdown(account_balance, current_equity, 
                         daily_loss_pct, start_of_day_balance,
                         firm_calculation_method='equity_based'):
    """
    Check if current equity breaches daily drawdown limit.
    Returns: (is_breach, remaining_buffer, warning_level)
    """
    if firm_calculation_method == 'equity_based':
        # Equity-based: uses highest equity point reached
        high_water_mark = max(start_of_day_balance, current_equity)
        daily_limit = high_water_mark * daily_loss_pct
        breach_level = high_water_mark - daily_limit
    else:
        # Balance-based: uses start of day balance
        daily_limit = start_of_day_balance * daily_loss_pct
        breach_level = start_of_day_balance - daily_limit
    
    remaining_buffer = current_equity - breach_level
    
    if current_equity <= breach_level:
        return True, remaining_buffer, 'BREACH'
    elif remaining_buffer < daily_limit * 0.3:
        return False, remaining_buffer, 'CRITICAL'
    elif remaining_buffer < daily_limit * 0.5:
        return False, remaining_buffer, 'WARNING'
    else:
        return False, remaining_buffer, 'SAFE'

def get_personal_stop_limit(firm_daily_limit, safety_buffer=0.4):
    """
    Set personal stop well below firm limit.
    Default 40% buffer means on 5% firm limit, stop at 3%.
    """
    return firm_daily_limit * (1 - safety_buffer)
```

### Consequences of Violation
- IMMEDIATE account termination
- Loss of all challenge fees
- For funded accounts: loss of funded status, forfeiture of pending payouts
- Must purchase new evaluation to restart

### Sources
- [thinkcapital.com/prop-firm-drawdown-rules](https://www.thinkcapital.com/prop-firm-drawdown-rules/)
- [audacity.capital/daily-vs-max-drawdown](https://audacity.capital/trading-guides/daily-vs-max-drawdown/)
- [t4tcapitalfm.com/5-most-common-reasons-traders-fail](https://t4tcapitalfm.com/blog/the-5-most-common-reasons-traders-fail-prop-firm-challenges/)

---

## Rule: Maximum/Trailing Drawdown Breach
**Priority:** CRITICAL  
**Applies To:** ALL FIRMS

### Description
The second most common failure mode (25-30%). Max drawdown is the total loss allowed over the account's lifetime. Two types:

**Static/Fixed Drawdown:**
- Loss limit stays fixed at initial balance * max_drawdown_pct
- Example: $100k account, 10% static = hard floor at $90k
- Profits expand the buffer (balance $110k = $20k buffer)
- Used by: FundingPips, FundedNext (some programs)

**Trailing Drawdown:**
- Loss limit trails highest equity/balance reached
- Example: $100k account, 10% trailing, equity peaks at $108k
- New floor = $108k - $10k = $98k
- Giving back profits can breach even above starting balance
- Used by: FTMO, FundedNext Stellar Instant, Apex, The5%ers

**Key Firm Max Drawdown Limits:**
| Firm | Max Drawdown | Type |
|------|-------------|------|
| FTMO | 10% | Static (trailing in funded) |
| FundedNext Stellar 2-Step | 10% | Static |
| FundedNext Stellar Instant | 6% | Trailing |
| FundingPips | 6% | Static |
| The5%ers Bootcamp | 4% | Static per stage |
| Apex Trader Funding | Varies | Trailing threshold |
| FundedPips | 6% | Static |

### Implementation
```python
def check_max_drawdown(current_balance, current_equity, 
                       initial_balance, high_water_mark,
                       max_drawdown_pct, drawdown_type='static'):
    """
    Check if account breaches maximum drawdown limit.
    Returns: (is_breach, floor_price, distance_to_floor)
    """
    if drawdown_type == 'static':
        floor_price = initial_balance * (1 - max_drawdown_pct)
    else:  # trailing
        floor_price = high_water_mark * (1 - max_drawdown_pct)
    
    # Use equity (not balance) for the check - this is critical
    distance_to_floor = current_equity - floor_price
    is_breach = current_equity <= floor_price
    
    return is_breach, floor_price, distance_to_floor

def update_high_water_mark(current_equity, previous_hwm):
    """Track highest equity for trailing drawdown calculations."""
    return max(current_equity, previous_hwm)
```

### Consequences of Violation
- Account immediately terminated
- All progress lost
- No refund of evaluation fees
- Must restart from evaluation phase

### Sources
- [funderpro.com/master-prop-firm-drawdown-rules](https://funderpro.com/blog/master-prop-firm-drawdown-rules-in-2025/)
- [thinkcapital.com/prop-firm-drawdown-rules](https://www.thinkcapital.com/prop-firm-drawdown-rules/)

---

## Rule: Consistency Rule Violation
**Priority:** CRITICAL  
**Applies To:** FundingPips, Apex, MyFundedFutures, FunderPro, The5%ers (some programs)

### Description
The consistency rule limits how much of total profit can come from a single trading day. It prevents "one-hit wonder" passes where a trader gets lucky on one big trade.

**Formula:**  
`Consistency Score = Best Day Profit / Total Profit`

**Thresholds by Firm:**
| Firm | Consistency Threshold | Applies |
|------|----------------------|---------|
| Apex | 30% | Payout requests |
| FundingPips Zero | 15% | Payouts only |
| FundingPips 1-Step/2-Step | 35% | On-demand payouts |
| FunderPro | 40% | Payouts |
| MyFundedFutures | 50% | Evaluation + payouts |
| The5%ers | None (most programs) | N/A |

**Example Breach:**
- Total profit: $3,000
- Best day profit: $1,200
- Consistency: $1,200 / $3,000 = 40%
- With 30% rule: BREACH
- Fix needed: Must grow total to $1,200 / 0.30 = $4,000 minimum

**Note:** Consistency rule does NOT terminate account - it blocks payouts/evaluation progress.

### Implementation
```python
def check_consistency_rule(daily_pnl_list, firm_threshold):
    """
    Check consistency rule compliance.
    Returns: (is_compliant, current_ratio, profit_needed_to_fix)
    """
    total_profit = sum(p for p in daily_pnl_list if p > 0)
    if total_profit <= 0:
        return True, 0.0, 0.0
    
    best_day = max(daily_pnl_list)
    current_ratio = best_day / total_profit if total_profit > 0 else 0
    
    is_compliant = current_ratio <= firm_threshold
    
    # Calculate how much more profit is needed to fix breach
    if not is_compliant:
        # best_day / new_total = threshold
        # new_total = best_day / threshold
        required_total = best_day / firm_threshold
        profit_needed = required_total - total_profit
    else:
        profit_needed = 0.0
    
    return is_compliant, current_ratio, profit_needed

def get_daily_profit_cap(total_profit_so_far, firm_threshold, 
                         trades_already_today=0):
    """
    Calculate max safe profit for today to stay compliant.
    Conservative: target ratio at 80% of threshold.
    """
    conservative_threshold = firm_threshold * 0.8
    max_today = total_profit_so_far * conservative_threshold / \
                (1 - conservative_threshold)
    return max_today
```

### Consequences of Violation
- Payout blocked (account NOT terminated)
- Cannot advance to funded stage
- Must trade additional days to dilute best day's contribution
- Evaluation extended until compliance restored

### Sources
- [quantvps.com/consistency-rule](https://www.quantvps.com/blog/what-is-the-consistency-rule-for-funded-accounts)
- [phidiaspropfirm.com/consistency-rule](https://phidiaspropfirm.com/education/consistency-rule)
- [quantvps.com/apex-pa-account-rules](https://www.quantvps.com/blog/apex-pa-account-rules)

---

## Rule: News Trading Ban Violation
**Priority:** HIGH  
**Applies To:** Most firms (especially funded accounts)

### Description
Trading during high-impact economic news events is heavily restricted. Most firms enforce a "blackout window" around Tier 1 news releases.

**Tier 1 News Events (always restricted):**
- FOMC Interest Rate Decision (8x per year)
- Non-Farm Payrolls (1st Friday monthly, 8:30 AM ET)
- CPI / Core CPI (monthly)
- FOMC Press Conference / Minutes

**Common Blackout Windows:**
| Firm | Buffer Time | Applies To |
|------|------------|------------|
| Most firms | 2 min before + 2 min after | Evaluation + funded |
| PropFirmPro | 5 min before + 5 min after | Funded accounts |
| Take Profit Trader | 1 min before + 1 min after | Funded (PRO/PRO+) |
| FundedPips | Prohibited entirely | Funded accounts |
| FTMO Challenge | No restriction | Challenge phase only |
| FTMO Funded | 2 min before + 2 min after | Funded accounts |

**Critical Traps:**
- Pending orders triggering during blackout = VIOLATION
- Stop-loss/take-profit executing during window = VIOLATION (some firms)
- Must be flat (no positions, no pending orders) during blackout
- Instrument-specific: USD pairs affected during NFP, Oil during EIA reports

### Implementation
```python
import pandas as pd
from datetime import datetime, timedelta

TIER1_NEWS_EVENTS = {
    'NFP': {'day': 'first_friday', 'time': '08:30', 'tz': 'US/Eastern',
            'affected_instruments': ['EURUSD','GBPUSD','USDJPY','USDCAD',
                                     'AUDUSD','NZDUSD','USDCHF','XAUUSD',
                                     'US30','US500','USTEC']},
    'FOMC_RATE': {'day': 'scheduled', 'time': '14:00', 'tz': 'US/Eastern',
                  'affected_instruments': ['ALL']},
    'CPI': {'day': 'monthly', 'time': '08:30', 'tz': 'US/Eastern',
            'affected_instruments': ['USD_pairs','GOLD','US_indices']},
}

def is_in_news_blackout(current_time, event_time, 
                        buffer_before_min=2, buffer_after_min=2):
    """Check if current time falls within news blackout window."""
    blackout_start = event_time - timedelta(minutes=buffer_before_min)
    blackout_end = event_time + timedelta(minutes=buffer_after_min)
    return blackout_start <= current_time <= blackout_end

def should_block_trade(instrument, current_time, upcoming_events,
                       account_phase='funded'):
    """
    Determine if a trade should be blocked due to news restrictions.
    Returns: (can_trade, reason, minutes_until_safe)
    """
    if account_phase == 'challenge':
        # Some firms allow news trading in challenge
        return True, 'Challenge phase - news allowed', 0
    
    for event in upcoming_events:
        if is_in_news_blackout(current_time, event['time'], 
                               event.get('buffer_before', 2),
                               event.get('buffer_after', 2)):
            if instrument in event['affected_instruments'] or 'ALL' in event['affected_instruments']:
                minutes_until_safe = ((event['time'] + timedelta(
                    minutes=event.get('buffer_after', 2))) - current_time).total_seconds() / 60
                return False, f"Blackout: {event['name']}", minutes_until_safe
    
    return True, 'No active blackout', 0

def flatten_before_news(open_positions, pending_orders, 
                        event_time, buffer_minutes=3):
    """Close all positions and cancel pending orders before news."""
    close_deadline = event_time - timedelta(minutes=buffer_minutes)
    # Returns signals to close all positions and cancel all pending orders
    return {
        'action': 'FLATTEN_ALL',
        'deadline': close_deadline,
        'positions_to_close': open_positions,
        'orders_to_cancel': pending_orders
    }
```

### Consequences of Violation
- Funded accounts: IMMEDIATE termination (most firms)
- Evaluation: Usually warning or disqualification
- Profits from news trades forfeited
- No appeals process at most firms

### Sources
- [help.propfirmpro.com/news-weekend-trading](https://help.propfirmpro.com/help-center-article/news-weekend-trading-restrictions)
- [myfxbook.com/news-trading-rules](https://www.myfxbook.com/articles/news-trading-rules-why-they-exist--how-to-avoid-violations/34)
- [tradingfinder.com/ftmo/rules](https://tradingfinder.com/props/ftmo/rules/)
- [eltraderfinanciado.com/news-trading-rule](https://www.eltraderfinanciado.com/en/blog/prop-firm-news-trading-rule)

---

## Rule: Weekend Holding Restriction
**Priority:** HIGH  
**Applies To:** Most forex/CFD firms; All futures firms

### Description
Many prop firms prohibit holding positions over weekends due to gap risk. Rules vary significantly:

| Firm | Weekend Holding | Notes |
|------|----------------|-------|
| FundingPips | NOT ALLOWED (funded) | Must close before Friday close |
| FTMO Challenge | Allowed | No restriction |
| FTMO Funded (Swing) | Allowed | Only with Swing account type |
| FundedNext | Allowed | No restrictions |
| Apex Trader Funding | NOT ALLOWED | Auto-close at 4:59 PM ET |
| The5%ers | Allowed | Most programs |
| Take Profit Trader | NOT ALLOWED | All positions closed Friday |

**Key Risk:** Weekend gaps can exceed stop losses, causing losses larger than expected and potentially breaching drawdown limits.

### Implementation
```python
from datetime import datetime, time
import pytz

def is_weekend_hold_allowed(current_time_utc, firm_rules):
    """Check if positions can be held over weekend."""
    if firm_rules.get('weekend_holding', True):
        return True, 'Weekend holding allowed'
    
    # Check if we're approaching Friday market close
    et = pytz.timezone('US/Eastern')
    current_et = current_time_utc.astimezone(et)
    
    if current_et.weekday() == 4:  # Friday
        close_time = firm_rules.get('friday_close_time', time(16, 0))
        if current_et.time() >= close_time:
            return False, 'Market closed - weekend hold not allowed'
        # Issue warning if within 2 hours of close
        warning_time = datetime.combine(current_et.date(), close_time) - timedelta(hours=2)
        if current_et >= warning_time.replace(tzinfo=et):
            return True, 'WARNING: Must close before {} ET'.format(close_time)
    
    if current_et.weekday() in [5, 6]:  # Saturday, Sunday
        return False, 'Weekend - markets closed'
    
    return True, 'Weekday trading - normal hours'

def get_friday_flatten_time(firm_rules):
    """Get the deadline for closing positions on Friday."""
    et = pytz.timezone('US/Eastern')
    close_time = firm_rules.get('friday_close_time', time(16, 0))
    buffer_min = firm_rules.get('friday_close_buffer_min', 30)
    return (datetime.combine(datetime.now(et).date(), close_time) - 
            timedelta(minutes=buffer_min))
```

### Consequences of Violation
- Account termination (strict firms)
- Profits from weekend-held positions forfeited
- Position forcibly closed at market open (with potential slippage)

### Sources
- [help.propfirmpro.com/news-weekend-trading](https://help.propfirmpro.com/help-center-article/news-weekend-trading-restrictions)
- [fundingpips review](https://www.dailyforex.com/prop-firms/fundingpips-review)

---

## Rule: Forbidden Strategies (Martingale, Grid, HFT, Latency Arb)
**Priority:** HIGH  
**Applies To:** ALL FIRMS

### Description
Prop firms maintain a list of prohibited strategies. Using them results in immediate account termination.

**Permanently Banned Strategies:**

| Strategy | Why Banned | Detection Method |
|----------|-----------|-----------------|
| Martingale | Exponential risk, guaranteed blowup | Position size doubling after losses |
| Grid Trading | Unlimited risk accumulation | Fixed-interval order clusters |
| Latency Arbitrage | Exploits feed delays | Order timing analysis vs market data |
| HFT | Overwhelms infrastructure | Order rate > 10-50/minute sustained |
| Copy Trading | Evaluation integrity fraud | Trade correlation across accounts |
| Hedge Arbitrage | Risk-free exploitation | Opposing positions across correlated instruments |
| Tick Scalping | Platform manipulation | Sub-second hold times |

**Warning Signs That Trigger Review:**
- Position size doubling after each loss
- More than 50 orders per minute
- Hold times under 5 seconds
- Trade correlation > 90% with known EAs
- Orders placed at exact same time as other accounts

### Implementation
```python
def detect_martingale(trade_history, lookback=10):
    """
    Detect martingale-like position sizing pattern.
    Returns: (is_martingale, confidence_score, reason)
    """
    recent_trades = trade_history[-lookback:]
    losing_streak_sizes = []
    
    for i in range(1, len(recent_trades)):
        prev = recent_trades[i-1]
        curr = recent_trades[i]
        if prev['pnl'] < 0 and curr['size'] >= prev['size'] * 1.8:
            losing_streak_sizes.append({
                'prev_size': prev['size'],
                'curr_size': curr['size'],
                'multiplier': curr['size'] / prev['size']
            })
    
    if len(losing_streak_sizes) >= 2:
        avg_multiplier = sum(x['multiplier'] for x in losing_streak_sizes) / len(losing_streak_sizes)
        return True, min(0.95, 0.5 + len(losing_streak_sizes) * 0.15), \
               f"Position size doubling detected: {avg_multiplier:.1f}x after losses"
    
    return False, 0.0, 'No martingale pattern detected'

def detect_hft_activity(order_history, time_window_seconds=60):
    """
    Detect high-frequency trading patterns.
    Returns: (is_hft, orders_per_minute, reason)
    """
    if len(order_history) < 20:
        return False, 0, 'Insufficient order history'
    
    # Count orders in last time window
    now = order_history[-1]['timestamp']
    window_start = now - time_window_seconds
    recent_orders = [o for o in order_history if o['timestamp'] >= window_start]
    
    orders_per_minute = len(recent_orders) * (60 / time_window_seconds)
    
    if orders_per_minute > 50:
        return True, orders_per_minute, f"HFT detected: {orders_per_minute:.0f} orders/min"
    elif orders_per_minute > 20:
        return False, orders_per_minute, f"WARNING: Elevated order rate: {orders_per_minute:.0f}/min"
    
    return False, orders_per_minute, 'Normal order rate'

def detect_grid_trading(open_orders, price_grid_threshold=0.001):
    """
    Detect grid-like order placement pattern.
    Returns: (is_grid, confidence, reason)
    """
    if len(open_orders) < 4:
        return False, 0.0, 'Insufficient orders'
    
    # Check for regular price intervals between orders
    prices = sorted([o['price'] for o in open_orders])
    intervals = [prices[i] - prices[i-1] for i in range(1, len(prices))]
    
    if len(intervals) < 3:
        return False, 0.0, 'Insufficient intervals'
    
    # Check if intervals are roughly equal (grid pattern)
    avg_interval = sum(intervals) / len(intervals)
    if avg_interval == 0:
        return False, 0.0, 'Zero intervals'
    
    variance = sum((i - avg_interval)**2 for i in intervals) / len(intervals)
    cv = (variance ** 0.5) / avg_interval  # Coefficient of variation
    
    if cv < 0.1 and len(intervals) >= 4:  # Very regular spacing
        return True, 0.9, f"Grid pattern: {len(intervals)} orders at regular {avg_interval:.5f} intervals"
    
    return False, 0.0, 'No grid pattern'
```

### Consequences of Violation
- IMMEDIATE account termination
- Profit forfeiture
- Permanent ban from platform
- Some firms share ban data across industry
- No refund of evaluation fees

### Sources
- [nexusfi.com/prohibited-strategies](https://nexusfi.com/a/prop-firms/prohibited-strategies-funded-accounts)
- [fortraders.com/prohibited-trading-strategies](https://www.fortraders.com/blog/prohibited-trading-strategies-in-prop-trading)
- [medium.com/hidden-rules-prop-firms](https://medium.com/@foxifytrade/the-hidden-rules-that-make-most-prop-firms-impossible-to-win-f89ce5300017)

---

## Rule: Copy Trading / IP Address / Device Detection
**Priority:** HIGH  
**Applies To:** ALL FIRMS

### Description
Prop firms actively detect and ban copy trading. They monitor:

1. **Trade Timing Correlation:** Multiple accounts entering at identical timestamps
2. **IP Address Analysis:** Same IP across multiple funded accounts
3. **Device Fingerprinting:** Same hardware/software signature
4. **Lot Size Patterns:** Identical position sizes across correlated accounts
5. **Signal Service Indicators:** Trades matching known signal providers

**Detection Thresholds:**
- Trade entry time correlation > 95% across 10+ trades = FLAG
- Same IP on 3+ active funded accounts = REVIEW
- Trade direction/size correlation > 90% with external signal service = BAN

### Implementation
```python
def check_copy_trading_risk(account_trades, all_account_trades,
                           ip_address, known_ips_for_account):
    """
    Assess copy trading risk indicators.
    Returns risk score 0-1 and warnings.
    """
    risk_score = 0.0
    warnings = []
    
    # Check IP correlation
    if ip_address in known_ips_for_account and len(known_ips_for_account) > 2:
        risk_score += 0.3
        warnings.append(f"IP shared with {len(known_ips_for_account)} accounts")
    
    # Check trade timing correlation with other accounts
    if all_account_trades:
        for other_id, other_trades in all_account_trades.items():
            if other_id == account_trades[0].get('account_id'):
                continue
            correlation = calculate_trade_timing_correlation(
                account_trades, other_trades
            )
            if correlation > 0.95:
                risk_score += 0.5
                warnings.append(f"Trade timing {correlation:.1%} correlated with {other_id}")
            elif correlation > 0.8:
                risk_score += 0.2
                warnings.append(f"Elevated timing correlation: {correlation:.1%}")
    
    return min(risk_score, 1.0), warnings

def calculate_trade_timing_correlation(trades_a, trades_b, tolerance_seconds=5):
    """Calculate what % of trades in A have matching entry in B within tolerance."""
    if not trades_a or not trades_b:
        return 0.0
    
    matches = 0
    for trade_a in trades_a:
        for trade_b in trades_b:
            time_diff = abs((trade_a['entry_time'] - trade_b['entry_time']).total_seconds())
            if time_diff <= tolerance_seconds:
                matches += 1
                break
    
    return matches / len(trades_a)
```

### Consequences of Violation
- Account termination
- Profit forfeiture
- Permanent ban from platform
- Potential industry-wide blacklist

### Sources
- [fundedaccountpro.com/copy-trading-detection](https://fundedaccountpro.com/guides/how-do-prop-firms-detect-copy-trading)
- [reddit.com/r/algotrading/prop-firms-banning-strategies](https://www.reddit.com/r/algotrading/comments/1bh15lf/deeper_reason_behind_prop_firms_banning_certain/)

---

## Rule: Inactivity Rule (Account Dormancy)
**Priority:** MEDIUM  
**Applies To:** Most funded accounts (not evaluations)

### Description
Funded accounts are closed after a period of inactivity. Requirements vary:

| Firm | Inactivity Period | Qualifying Day Requirement |
|------|------------------|---------------------------|
| Apex | 30 days | 2 days with $50+ net profit per rolling 30 days |
| Most firms | 30 days | At least 1 trade closed |
| Some firms | 14-21 days | Warning at 50% threshold |

**Critical Detail:** A "qualifying day" typically requires:
1. At least one trade opened AND closed
2. Net profit above minimum threshold (often $50)
3. Losing days do NOT count

### Implementation
```python
from datetime import datetime, timedelta

def check_inactivity_status(last_qualifying_trade_date, 
                            current_date, 
                            firm_inactivity_days=30,
                            warning_threshold_days=15):
    """
    Check account inactivity status.
    Returns: (status, days_remaining, action_needed)
    """
    days_since_activity = (current_date - last_qualifying_trade_date).days
    
    if days_since_activity >= firm_inactivity_days:
        return 'TERMINATED', 0, 'Account closed - purchase new evaluation'
    elif days_since_activity >= warning_threshold_days:
        days_left = firm_inactivity_days - days_since_activity
        return 'DORMANT', days_left, f'Place qualifying trade within {days_left} days'
    elif days_since_activity >= warning_threshold_days * 0.7:
        days_left = firm_inactivity_days - days_since_activity
        return 'WARNING', days_left, f'Approaching inactivity - trade soon'
    
    return 'ACTIVE', firm_inactivity_days - days_since_activity, 'No action needed'

def is_qualifying_day(trades_today, min_profit=50.0):
    """Check if today's trading meets qualifying day criteria."""
    if not trades_today:
        return False, 'No trades executed'
    
    net_pnl = sum(t['pnl'] for t in trades_today)
    if net_pnl < min_profit:
        return False, f'Net profit ${net_pnl:.2f} below ${min_profit} threshold'
    
    trades_closed = sum(1 for t in trades_today if t['status'] == 'closed')
    if trades_closed == 0:
        return False, 'No completed trades'
    
    return True, f'Qualifying day: ${net_pnl:.2f} profit, {trades_closed} trades'
```

### Consequences of Violation
- Account permanently closed after 30 days
- Cannot be reinstated
- Must purchase new evaluation
- All progress lost

### Sources
- [damnpropfirms.com/inactivity-rule](https://damnpropfirms.com/glossary/inactivity-rule/)
- [propfirmmatch.com/futures/prop-firm-rules](https://propfirmmatch.com/futures/prop-firm-rules)

---

## Rule: Maximum Lot Size / Position Limits
**Priority:** MEDIUM  
**Applies To:** Varies by firm

### Description
Some firms enforce maximum lot sizes to prevent excessive concentration risk.

| Firm | Lot Limit | Notes |
|------|----------|-------|
| FundingPips | Yes (not specified) | Enforced in evaluation |
| FundedNext | No hard cap | Must manage margin responsibly |
| Apex Trader Funding | Contract-specific | See account size table below |
| Blueberry Funded | Yes | Scales with account size |
| Most modern firms | No limit | Replaced by drawdown limits |

**Apex Trader Funding Contract Limits:**
| Account Size | Max Contracts (Micros) |
|-------------|----------------------|
| $25,000 | 4 (40) |
| $50,000 | 10 (100) |
| $100,000 | 14 (140) |
| $150,000 | 17 (170) |
| $250,000 | 27 (270) |
| $300,000 | 35 (350) |

### Implementation
```python
def check_lot_size_limit(proposed_lots, instrument, account_size, 
                         firm_max_lots=None):
    """
    Validate proposed position size against firm limits.
    Returns: (is_allowed, max_allowed, reason)
    """
    if firm_max_lots is None:
        # No explicit limit - use risk-based limit
        max_risk_lots = calculate_risk_based_max_lots(account_size)
        return (proposed_lots <= max_risk_lots, max_risk_lots,
                f"Risk-based limit: {max_risk_lots:.2f} lots")
    
    if proposed_lots > firm_max_lots:
        return False, firm_max_lots, \
               f"Exceeds max {firm_max_lots} lots for {instrument}"
    
    return True, firm_max_lots, 'Within limits'

def calculate_risk_based_max_lots(account_size, risk_pct=0.02,
                                   stop_loss_pips=50, pip_value=10):
    """Calculate max lots based on risk percentage."""
    risk_amount = account_size * risk_pct
    max_lots = risk_amount / (stop_loss_pips * pip_value)
    return max_lots
```

### Consequences of Violation
- Warning for minor breaches
- Account review for significant breaches
- Termination for repeated/flagrant violations

---

# SECTION 2: RISK MANAGEMENT MODELS

## Technique: Kelly Criterion Position Sizing
**Priority:** CRITICAL  
**Applies To:** All strategies, all firms

### Description
The Kelly Criterion calculates the optimal fraction of capital to risk per trade based on win rate and reward-to-risk ratio. It maximizes long-term geometric growth.

**Formula:**  
`Kelly % = W - [(1 - W) / R]`

Where:
- W = Win probability (0 to 1)
- R = Win/Loss ratio (average winner / average loser)
- q = 1 - W (loss probability)

**Alternative Formula:**  
`f = (bp - q) / b`  
Where b = odds (avg win / avg loss), p = win rate

**Example:**
- Win rate: 55% (W = 0.55)
- Avg winner: $1,500
- Avg loser: $1,000
- R = 1,500 / 1,000 = 1.5
- Kelly % = 0.55 - [(1 - 0.55) / 1.5] = 0.55 - 0.30 = 0.25 or **25%**

**Critical Warning: NEVER use Full Kelly.**  
Full Kelly produces 50-70% drawdowns. Use fractional Kelly:

| Kelly Fraction | Risk % | Growth Retained | Drawdown Reduction |
|---------------|--------|----------------|-------------------|
| Full Kelly | 25% | 100% | 0% |
| Half Kelly | 12.5% | ~75% | ~50% |
| Quarter Kelly | 6.25% | ~50% | ~75% |
| Eighth Kelly | 3.125% | ~30% | ~90% |

**Recommendation for Prop Firms: Use Half-Kelly maximum, Quarter-Kelly preferred.**

### Implementation
```python
import math

def kelly_criterion(win_rate, avg_win, avg_loss):
    """
    Calculate Kelly Criterion percentage.
    Returns: (full_kelly, half_kelly, quarter_kelly)
    """
    if avg_loss == 0 or win_rate <= 0 or win_rate >= 1:
        return 0.0, 0.0, 0.0
    
    win_loss_ratio = avg_win / avg_loss
    
    # Kelly formula: f = W - [(1-W)/R]
    full_kelly = win_rate - ((1 - win_rate) / win_loss_ratio)
    
    # Clamp to reasonable bounds
    full_kelly = max(0.0, min(full_kelly, 1.0))
    
    return full_kelly, full_kelly / 2, full_kelly / 4

def kelly_based_position_size(account_balance, win_rate, avg_win, avg_loss,
                               kelly_fraction=0.25,  # Quarter-Kelly default
                               max_risk_pct=0.02):    # Hard cap at 2%
    """
    Calculate position size using fractional Kelly with hard cap.
    """
    full_k, half_k, quarter_k = kelly_criterion(win_rate, avg_win, avg_loss)
    
    # Use requested fraction
    kelly_risk = full_k * kelly_fraction
    
    # Apply hard cap
    risk_pct = min(kelly_risk, max_risk_pct)
    
    risk_amount = account_balance * risk_pct
    
    return {
        'risk_pct': risk_pct,
        'risk_amount': risk_amount,
        'full_kelly': full_k,
        'used_kelly_fraction': kelly_fraction,
        'capped': kelly_risk > max_risk_pct
    }

def adaptive_kelly_sizing(trade_history, lookback_trades=50,
                          kelly_fraction=0.25):
    """
    Calculate position size based on recent trade performance.
    """
    if len(trade_history) < 20:
        # Insufficient data - use conservative default
        return {'risk_pct': 0.005, 'reason': 'Insufficient trade history'}
    
    recent = trade_history[-lookback_trades:]
    wins = [t['pnl'] for t in recent if t['pnl'] > 0]
    losses = [t['pnl'] for t in recent if t['pnl'] <= 0]
    
    win_rate = len(wins) / len(recent)
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 1
    
    result = kelly_based_position_size(
        account_balance=100000,  # placeholder
        win_rate=win_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        kelly_fraction=kelly_fraction
    )
    
    result['win_rate'] = win_rate
    result['avg_win'] = avg_win
    result['avg_loss'] = avg_loss
    result['sample_size'] = len(recent)
    
    return result
```

### Sources
- [zerodha.com/kellys-criterion](https://zerodha.com/varsity/chapter/kellys-criterion/)
- [abovethegreenline.com/kelly-criterion-trading](https://abovethegreenline.com/kelly-criterion-trading/)
- [backtestbase.com/kelly-criterion-calculator](https://www.backtestbase.com/education/how-much-risk-per-trade)

---

## Technique: Optimal f (Ralph Vince)
**Priority:** MEDIUM  
**Applies To:** Strategies with complete trade history

### Description
Optimal f, developed by Ralph Vince, uses the actual sequence of trade P&L rather than just win rate and ratio. It finds the fraction of capital that maximizes Terminal Wealth Relative (TWR).

**Formula:**  
`TWR(f) = Product[1 + f * (trade_i / |worst_loss|)]` for all trades i

Optimal f = the value of f (0 to 1) that maximizes TWR

**Key Differences from Kelly:**
- Kelly uses win rate + ratio (distribution-based)
- Optimal f uses actual trade sequence
- Optimal f can differ significantly for same win/loss stats in different order

**Practical Use:**
- Like Kelly, use 25-50% of Optimal f in practice
- Recalculate after every 20-30 trades
- Sensitive to worst-case loss - one extreme outlier can skew results

### Implementation
```python
def calculate_optimal_f(trade_pnl_list, granularity=0.001):
    """
    Calculate Optimal f from trade history.
    Returns: (optimal_f, max_twr, worst_loss)
    """
    if not trade_pnl_list or len(trade_pnl_list) < 10:
        return 0.0, 0.0, 0.0
    
    worst_loss = abs(min(trade_pnl_list))
    if worst_loss == 0:
        worst_loss = 0.01  # Avoid division by zero
    
    best_f = 0.0
    best_twr = 0.0
    
    # Search for optimal f from 0 to 1
    f = 0.0
    while f <= 1.0:
        twr = 1.0
        for pnl in trade_pnl_list:
            hpr = 1 + f * (pnl / worst_loss)  # Holding Period Return
            if hpr <= 0:
                twr = 0
                break
            twr *= hpr
        
        if twr > best_twr:
            best_twr = twr
            best_f = f
        
        f += granularity
    
    return best_f, best_twr, worst_loss

def optimal_f_position_size(account_balance, trade_history,
                            fraction_of_optimal=0.25):
    """
    Calculate position size using fractional Optimal f.
    """
    opt_f, twr, worst_loss = calculate_optimal_f(trade_history)
    
    practical_f = opt_f * fraction_of_optimal
    
    # Convert to practical position sizing
    risk_amount = account_balance * practical_f
    
    return {
        'optimal_f': opt_f,
        'practical_f': practical_f,
        'risk_amount': risk_amount,
        'twr_at_optimal': twr,
        'worst_loss': worst_loss
    }
```

### Sources
- [pineify.app/optimal-f-calculator](https://pineify.app/optimal-f-calculator)
- [quantifiedstrategies.com/optimal-f](https://www.quantifiedstrategies.com/optimal-f-money-management/)

---

## Technique: Risk of Ruin Calculation
**Priority:** CRITICAL  
**Applies To:** All prop firm trading

### Description
Risk of Ruin (RoR) calculates the probability of hitting a catastrophic drawdown level. For prop firms, "ruin" = hitting the firm's max drawdown limit (not total account wipeout).

**Simplified RoR Formula:**  
`RoR = ((1 - Edge) / (1 + Edge)) ^ (Capital_Units)`

Where:
- Edge = (Win% * AvgWin - Loss% * AvgLoss) / (Win% * AvgWin + Loss% * AvgLoss)
- Capital_Units = Drawdown_Limit / Risk_Per_Trade

**Key Insight for Prop Firms:**
A $100k account with 10% max drawdown = $10,000 ruin threshold
At $500 risk per trade = 20 capital units
With 50% win rate and 1.5:1 R:R, RoR ≈ 5.7%

**Target: Keep RoR below 1% for prop firm trading.**

### Implementation
```python
def risk_of_ruin(win_rate, avg_win, avg_loss, risk_per_trade, 
                 drawdown_limit, max_iterations=1000):
    """
    Calculate Risk of Ruin using Monte Carlo simulation.
    Returns: (ror_pct, median_drawdown, worst_case_95)
    """
    import random
    
    ruin_count = 0
    all_max_drawdowns = []
    
    for _ in range(max_iterations):
        equity = drawdown_limit / 0.10  # Approximate account size
        peak = equity
        max_dd = 0
        ruined = False
        
        for trade in range(500):  # Simulate 500 trades
            if random.random() < win_rate:
                pnl = avg_win * risk_per_trade / avg_loss
            else:
                pnl = -risk_per_trade
            
            equity += pnl
            
            if equity > peak:
                peak = equity
            
            dd = (peak - equity) / peak
            max_dd = max(max_dd, dd)
            
            if equity <= peak * (1 - 0.10):  # 10% drawdown = ruin
                ruined = True
                break
        
        if ruined:
            ruin_count += 1
        all_max_drawdowns.append(max_dd)
    
    ror_pct = (ruin_count / max_iterations) * 100
    median_dd = sorted(all_max_drawdowns)[len(all_max_drawdowns)//2] * 100
    worst_95 = sorted(all_max_drawdowns)[int(max_iterations * 0.95)] * 100
    
    return ror_pct, median_dd, worst_95

def get_safe_risk_per_trade(win_rate, avg_win, avg_loss,
                            drawdown_limit, target_ror=0.01):
    """
    Find the risk per trade that achieves target Risk of Ruin.
    """
    for risk_pct in [0.005, 0.01, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05]:
        ror, _, _ = risk_of_ruin(win_rate, avg_win, avg_loss,
                                  risk_pct * drawdown_limit / 0.10,
                                  drawdown_limit)
        if ror <= target_ror * 100:
            return risk_pct, ror
    
    return 0.005, 999  # Ultra-conservative fallback
```

### Sources
- [journalplus.co/risk-of-ruin](https://journalplus.co/learn/guides/risk-of-ruin-guide)

---

## Technique: Drawdown-Based Position Reduction (50% Rule)
**Priority:** MEDIUM  
**Applies To:** All strategies during drawdown periods

### Description
When account enters a drawdown, reduce position size proportionally. This preserves capital during losing streaks and accelerates recovery.

**The 50% Rule:**
- At 50% of max allowed drawdown: reduce position size by 50%
- At 75% of max allowed drawdown: reduce position size by 75%
- At 90% of max allowed drawdown: STOP TRADING

**Example:**
- Max allowed drawdown: 10% ($10k on $100k account)
- At 5% drawdown ($5k): Trade at 50% normal size
- At 7.5% drawdown ($7.5k): Trade at 25% normal size
- At 9% drawdown ($9k): STOP ALL TRADING

### Implementation
```python
def drawdown_based_sizing(normal_risk_pct, current_drawdown_pct,
                          max_allowed_drawdown_pct,
                          firm_daily_limit_pct=None,
                          current_daily_pnl_pct=0.0):
    """
    Calculate reduced position size based on drawdown proximity.
    Returns: (adjusted_risk_pct, trading_status, reason)
    """
    drawdown_ratio = current_drawdown_pct / max_allowed_drawdown_pct
    
    # Circuit breaker levels
    if drawdown_ratio >= 0.95:
        return 0.0, 'HALTED', f'CRITICAL: {current_drawdown_pct:.1%} drawdown (95% of max)'
    
    if drawdown_ratio >= 0.90:
        return 0.0, 'HALTED', f'HALT: {current_drawdown_pct:.1%} drawdown (90% of max)'
    
    if drawdown_ratio >= 0.75:
        adjusted = normal_risk_pct * 0.25
        return adjusted, 'RESTRICTED', f'25% size: {current_drawdown_pct:.1%} drawdown (75%+ of max)'
    
    if drawdown_ratio >= 0.50:
        adjusted = normal_risk_pct * 0.50
        return adjusted, 'CAUTION', f'50% size: {current_drawdown_pct:.1%} drawdown (50%+ of max)'
    
    if drawdown_ratio >= 0.30:
        adjusted = normal_risk_pct * 0.75
        return adjusted, 'NORMAL', f'75% size: {current_drawdown_pct:.1%} drawdown (30%+ of max)'
    
    return normal_risk_pct, 'NORMAL', f'Full size: {current_drawdown_pct:.1%} drawdown'

def should_pause_trading(daily_pnl_pct, firm_daily_limit_pct, 
                        pause_threshold=0.6):
    """
    Pause trading for the day if approaching daily limit.
    """
    daily_usage = abs(daily_pnl_pct) / firm_daily_limit_pct if firm_daily_limit_pct > 0 else 0
    
    if daily_usage >= 1.0:
        return True, 'DAILY_LIMIT_HIT', 'Daily drawdown limit reached'
    elif daily_usage >= pause_threshold:
        return True, 'PAUSE_WARNING', f'{daily_usage:.0%} of daily limit used - pause trading'
    
    return False, 'OK', f'{daily_usage:.0%} of daily limit used'
```

---

# SECTION 3: MULTI-STRATEGY PORTFOLIO MANAGEMENT

## Technique: Portfolio Heat Management
**Priority:** HIGH  
**Applies To:** Multi-position, multi-strategy trading

### Description
Portfolio heat = total percentage of account equity at risk across ALL simultaneously open positions. Even if each trade risks only 1%, five correlated 1% trades behave like a single 5% trade during a market shock.

**Alexander Elder's 6% Rule:**
- Risk no more than 2% on any single trade
- Never let cumulative open risk exceed 6% of account equity per month
- When 6% threshold is hit: STOP adding positions for the rest of the month

**Practical Caps by Style:**
| Trading Style | Max Portfolio Heat |
|--------------|-------------------|
| Conservative Position Trading | 3% |
| Active Swing Trading | 6% |
| Short-term Scalping | 10% |
| Prop Firm Conservative | 4-5% |

### Implementation
```python
def calculate_portfolio_heat(open_positions, account_equity):
    """
    Calculate total portfolio heat as % of account equity.
    """
    total_dollar_risk = 0.0
    
    for pos in open_positions:
        if pos.get('stop_price'):
            dollar_risk = abs(pos['entry_price'] - pos['stop_price']) * pos['size']
        else:
            # No stop = full position value at risk
            dollar_risk = pos['position_value']
        total_dollar_risk += dollar_risk
    
    heat_pct = (total_dollar_risk / account_equity) * 100
    return heat_pct, total_dollar_risk

def can_add_position(open_positions, account_equity, 
                     new_position_risk,
                     max_heat_pct=6.0,
                     max_single_trade_pct=2.0):
    """
    Determine if a new position can be added without exceeding heat limit.
    """
    current_heat, _ = calculate_portfolio_heat(open_positions, account_equity)
    
    if current_heat >= max_heat_pct:
        return False, f'Heat at {current_heat:.1f}% (max {max_heat_pct}%)'
    
    projected_heat = current_heat + (new_position_risk / account_equity * 100)
    
    if projected_heat > max_heat_pct:
        return False, f'Would exceed heat: {projected_heat:.1f}% > {max_heat_pct}%'
    
    if new_position_risk / account_equity * 100 > max_single_trade_pct:
        return False, f'Single trade risk exceeds {max_single_trade_pct}%'
    
    return True, f'OK: Heat would be {projected_heat:.1f}%'

def get_correlation_adjusted_heat(open_positions, correlation_matrix):
    """
    Adjust portfolio heat for correlated positions.
    Correlated positions increase effective heat.
    """
    base_heat = sum(p['risk_pct'] for p in open_positions)
    
    # Add correlation penalty
    correlation_penalty = 0.0
    for i in range(len(open_positions)):
        for j in range(i + 1, len(open_positions)):
            pair_corr = correlation_matrix.get(
                (open_positions[i]['instrument'], open_positions[j]['instrument']), 0
            )
            if pair_corr > 0.5:  # Positively correlated
                correlation_penalty += pair_corr * 0.5 * \
                    min(open_positions[i]['risk_pct'], open_positions[j]['risk_pct'])
    
    adjusted_heat = base_heat + correlation_penalty
    return adjusted_heat
```

### Sources
- [journalplus.co/portfolio-heat](https://journalplus.co/learn/glossary/portfolio-heat)

---

## Technique: Correlation-Based Portfolio Allocation
**Priority:** MEDIUM  
**Applies To:** Multi-strategy, multi-instrument bots

### Description
Measure correlation between strategies/instruments to ensure true diversification. During market stress, correlations often spike toward 1.0, making "diversified" portfolios move together.

**Correlation Guidelines:**
| Correlation | Interpretation | Action |
|------------|---------------|--------|
| 0.0 to 0.2 | Uncorrelated | Ideal - full diversification benefit |
| 0.2 to 0.5 | Weak positive | Acceptable - some diversification |
| 0.5 to 0.7 | Moderate positive | Reduce combined size |
| 0.7 to 1.0 | Highly correlated | Trade as single position |

**Common Forex Correlations:**
- EURUSD + GBPUSD: ~+0.85 (highly correlated)
- EURUSD + USDCHF: ~-0.95 (near perfect inverse)
- AUDUSD + Gold: ~+0.75 (positive)
- USDJPY + US equities: ~+0.60 (positive)

### Implementation
```python
import numpy as np

def calculate_strategy_correlation(returns_a, returns_b, min_samples=20):
    """
    Calculate Pearson correlation between two strategy return series.
    """
    if len(returns_a) < min_samples or len(returns_b) < min_samples:
        return 0.0, 'Insufficient data'
    
    correlation = np.corrcoef(returns_a, returns_b)[0, 1]
    
    if np.isnan(correlation):
        return 0.0, 'Calculation error'
    
    # Interpretation
    abs_corr = abs(correlation)
    if abs_corr < 0.2:
        interpretation = 'Uncorrelated - full diversification'
    elif abs_corr < 0.5:
        interpretation = 'Weak correlation - acceptable'
    elif abs_corr < 0.7:
        interpretation = 'Moderate correlation - reduce combined size'
    else:
        interpretation = 'Highly correlated - treat as one position'
    
    return correlation, interpretation

def adjust_size_for_correlation(base_size_a, base_size_b, correlation,
                                max_combined_exposure=1.0):
    """
    Reduce individual position sizes when strategies are correlated.
    """
    abs_corr = abs(correlation)
    
    if abs_corr < 0.3:
        # Low correlation - no adjustment needed
        return base_size_a, base_size_b, 'No adjustment needed'
    
    if abs_corr < 0.7:
        # Moderate correlation - reduce by correlation factor
        reduction = (abs_corr - 0.3) / 0.7  # 0 to ~0.57
        adj_a = base_size_a * (1 - reduction * 0.5)
        adj_b = base_size_b * (1 - reduction * 0.5)
        return adj_a, adj_b, f'Reduced {reduction*50:.0f}% due to {abs_corr:.2f} correlation'
    
    # High correlation - trade largest only
    if base_size_a >= base_size_b:
        return base_size_a, 0, f'High correlation {abs_corr:.2f} - trade A only'
    else:
        return 0, base_size_b, f'High correlation {abs_corr:.2f} - trade B only'

def build_correlation_matrix(strategy_returns_dict):
    """
    Build correlation matrix for all strategies.
    Returns pandas DataFrame.
    """
    import pandas as pd
    
    df = pd.DataFrame(strategy_returns_dict)
    corr_matrix = df.corr()
    
    return corr_matrix
```

---

## Technique: Circuit Breakers - Strategy Shutdown
**Priority:** MEDIUM  
**Applies To:** Multi-strategy bots, all prop firm trading

### Description
Circuit breakers automatically halt all trading when predefined risk thresholds are breached. Essential for preventing catastrophic losses during abnormal market conditions.

**Circuit Breaker Levels:**

| Level | Trigger | Action |
|-------|---------|--------|
| Yellow (Warning) | 50% of daily limit used | Reduce size 50%, alert only |
| Orange (Caution) | 75% of daily limit used | Reduce size 75%, no new positions |
| Red (Halt) | 90% of daily limit used | Close all positions, stop for day |
| Black (Emergency) | Daily limit hit or 90% of max drawdown | Emergency flatten, shutdown all strategies |

### Implementation
```python
from enum import Enum

class CircuitLevel(Enum):
    GREEN = 1    # Normal operation
    YELLOW = 2   # Warning - reduce size
    ORANGE = 3   # Caution - no new positions
    RED = 4      # Halt - close all, stop for day
    BLACK = 5    # Emergency - total shutdown

class CircuitBreaker:
    def __init__(self, firm_daily_limit_pct, firm_max_drawdown_pct,
                 account_size):
        self.firm_daily_limit = firm_daily_limit_pct
        self.firm_max_dd = firm_max_drawdown_pct
        self.account_size = account_size
        self.current_level = CircuitLevel.GREEN
        self.daily_pnl = 0.0
        self.peak_equity = account_size
        self.current_equity = account_size
        self.is_halted = False
        
    def update(self, current_equity, daily_pnl):
        """Update circuit breaker state."""
        self.current_equity = current_equity
        self.daily_pnl = daily_pnl
        
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity
        
        current_drawdown = (self.peak_equity - current_equity) / self.peak_equity
        daily_usage = abs(daily_pnl) / self.firm_daily_limit if self.firm_daily_limit > 0 else 0
        max_dd_usage = current_drawdown / self.firm_max_dd if self.firm_max_dd > 0 else 0
        
        # Determine circuit level
        if max_dd_usage >= 0.90 or daily_usage >= 1.0:
            self.current_level = CircuitLevel.BLACK
            self.is_halted = True
        elif daily_usage >= 0.90 or max_dd_usage >= 0.75:
            self.current_level = CircuitLevel.RED
            self.is_halted = True
        elif daily_usage >= 0.75 or max_dd_usage >= 0.50:
            self.current_level = CircuitLevel.ORANGE
        elif daily_usage >= 0.50 or max_dd_usage >= 0.30:
            self.current_level = CircuitLevel.YELLOW
        else:
            self.current_level = CircuitLevel.GREEN
            self.is_halted = False
        
        return self.current_level, self._get_action()
    
    def _get_action(self):
        """Get required action for current circuit level."""
        actions = {
            CircuitLevel.GREEN: {'trade': True, 'size_multiplier': 1.0, 
                                 'new_positions': True, 'alert': False},
            CircuitLevel.YELLOW: {'trade': True, 'size_multiplier': 0.5,
                                  'new_positions': True, 'alert': True},
            CircuitLevel.ORANGE: {'trade': True, 'size_multiplier': 0.25,
                                  'new_positions': False, 'alert': True},
            CircuitLevel.RED: {'trade': False, 'size_multiplier': 0.0,
                               'new_positions': False, 'alert': True,
                               'flatten': True},
            CircuitLevel.BLACK: {'trade': False, 'size_multiplier': 0.0,
                                 'new_positions': False, 'alert': True,
                                 'flatten': True, 'shutdown': True}
        }
        return actions[self.current_level]
    
    def can_trade(self):
        return not self.is_halted and self.current_level.value <= CircuitLevel.YELLOW.value
    
    def get_position_size_multiplier(self):
        return self._get_action()['size_multiplier']
```

---

# SECTION 4: PROP FIRM-SPECIFIC RULES

## Firm: FundingPips
**Priority:** HIGH

### Key Rules Summary
- **Max Daily Loss:** 3% of starting balance
- **Max Overall Loss:** 6% static from starting balance
- **Consistency Rule:** 35% (on-demand payouts for 1-Step/2-Step), 15% (Zero account)
- **Min Trading Days:** 3 profitable days per evaluation phase
- **Min Profitable Days (Zero):** 7 per 30-day period, min 0.25% return per day
- **Weekend Holding:** NOT ALLOWED on funded accounts
- **News Trading:** NOT ALLOWED on funded accounts
- **Max Daily Profit:** 45% of account value (funded stage)
- **Inactivity:** 30 days = account closure
- **Prohibited:** HFT, latency arbitrage, hedging, grid, martingale, copy trading

### Implementation
```python
FUNDINGPIPS_RULES = {
    'max_daily_loss_pct': 0.03,
    'max_overall_loss_pct': 0.06,
    'drawdown_type': 'static',
    'consistency_threshold': 0.35,
    'consistency_threshold_zero': 0.15,
    'min_trading_days': 3,
    'min_profitable_days_per_30': 7,
    'min_daily_profit_pct': 0.0025,
    'weekend_holding_allowed': False,
    'news_trading_allowed': False,
    'max_daily_profit_pct': 0.45,
    'inactivity_days': 30,
    'prohibited_strategies': ['HFT', 'latency_arbitrage', 'hedging', 
                               'grid', 'martingale', 'copy_trading'],
    'allowed_eas': True,  # But must own the code
    'platforms': ['MT5', 'MatchTrader', 'cTrader']
}
```

### Sources
- [dailyforex.com/fundingpips-review](https://www.dailyforex.com/prop-firms/fundingpips-review)
- [fxempire.com/fundingpips](https://www.fxempire.com/prop-firms/fundingpips)

---

## Firm: FTMO
**Priority:** HIGH

### Key Rules Summary
- **Challenge Phase 1 Profit Target:** 10%
- **Challenge Phase 2 Profit Target:** 5%
- **Max Daily Loss:** 5% (equity-based)
- **Max Overall Loss:** 10%
- **Min Trading Days:** 4 per phase
- **Time Limit:** None (unlimited)
- **News Trading:** Allowed in challenge; 2-min buffer in funded (Swing accounts exempt)
- **Weekend Holding:** Allowed in challenge; Swing account only in funded
- **EA/Bots:** Allowed (must be your own)
- **Scaling Plan:** Long-term scaling up to $2M
- **Refund:** Evaluation fee refunded after first payout

### Implementation
```python
FTMO_RULES = {
    'phase1_profit_target': 0.10,
    'phase2_profit_target': 0.05,
    'max_daily_loss_pct': 0.05,
    'max_overall_loss_pct': 0.10,
    'drawdown_type': 'equity_based',
    'min_trading_days_per_phase': 4,
    'time_limit': None,
    'news_trading_challenge': True,
    'news_trading_funded': False,
    'news_buffer_min': 2,
    'weekend_holding_challenge': True,
    'weekend_holding_funded': 'swing_only',
    'ea_allowed': True,
    'scaling_plan': True,
    'fee_refundable': True,
    'profit_split_start': 0.80,
    'profit_split_max': 0.90
}
```

### Sources
- [edgeflo.com/ftmo-rules](https://www.edgeflo.com/blog/ftmo-rules)
- [tradingfinder.com/ftmo/rules](https://tradingfinder.com/props/ftmo/rules/)
- [fundednext.com/fundednext-vs-ftmo](https://fundednext.com/blog/fundednext-vs-ftmo)

---

## Firm: The5%ers
**Priority:** HIGH

### Key Rules Summary

**Bootcamp Program:**
- Entry: $95 + $205 for live account
- Challenge: 3 stages, each requiring 6% profit
- Max Loss: 5% per stage (funded: 4% max loss)
- Leverage: 1:10
- Time Limit: 12 months
- Stop Loss: REQUIRED
- Open Risk: Max 2% allowed
- Scaling: Every 5% gain = +$25K until $300K, then larger increments to $4M cap
- Profit Split: 50/50 initially, 75/25 after first target, 100/0 at $2.5M

**High Stakes Program:**
- Two-step: 8% Phase 1, 5% Phase 2
- Max Loss: 10%, Daily: 5%
- Leverage: 1:100
- Min Profitable Days: 3 (0.5% min per day)
- Time Limit: 30 days Phase 1, 60 days Phase 2
- Scaling: Every 10% to $500K cap
- Profit Split: 80/20 initially, 100/0 at $350K
- Monthly Salary: $4,000 at scale

**Prohibited:** Tick scalping, latency arbitrage, reverse arbitrage, hedge arbitrage, HFT, emulators

### Implementation
```python
THE5ERS_RULES = {
    'bootcamp': {
        'stages': 3,
        'profit_target_per_stage': 0.06,
        'max_loss_challenge': 0.05,
        'max_loss_funded': 0.04,
        'leverage': 10,
        'time_limit_months': 12,
        'stop_loss_required': True,
        'max_open_risk_pct': 0.02,
        'scaling_increment': 25000,
        'scaling_trigger': 0.05,
        'profit_split_tiers': [(0, 0.50), (1, 0.75), (2500000, 1.0)]
    },
    'high_stakes': {
        'phases': 2,
        'phase1_target': 0.08,
        'phase2_target': 0.05,
        'max_loss': 0.10,
        'max_daily_loss': 0.05,
        'leverage': 100,
        'min_profitable_days': 3,
        'min_daily_profit_pct': 0.005,
        'time_limit_phase1_days': 30,
        'time_limit_phase2_days': 60,
        'scaling_trigger': 0.10,
        'scaling_cap': 500000,
        'profit_split_tiers': [(0, 0.80), (350000, 1.0)]
    },
    'prohibited_strategies': ['tick_scalping', 'latency_arbitrage',
                               'reverse_arbitrage', 'hedge_arbitrage',
                               'HFT', 'emulators']
}
```

### Sources
- [the5ers.com/bootcamp](https://the5ers.com/bootcamp/)
- [reddit.com/r/Forex/the5ers-comparison](https://www.reddit.com/r/Forex/comments/140djxj/comparison_of_the5ers_prop_firm_programs/)

---

## Firm: FundedNext
**Priority:** HIGH

### Key Rules Summary

**Stellar 2-Step:**
- Phase 1: 8% profit target
- Phase 2: 5% profit target
- Max Daily Loss: 5% (equity or balance, whichever is higher)
- Max Overall Loss: 10%
- Min Trading Days: 5
- Time Limit: None
- Profit Split: Up to 95% with add-ons

**Stellar 1-Step:**
- Profit Target: 10%
- Max Daily Loss: 3%
- Max Overall Loss: 6%
- Min Trading Days: 2
- Time Limit: None

**Stellar Instant:**
- No evaluation
- Max Loss: 6% trailing
- No daily loss limit
- No minimum trading days
- Profit Share: 70-80% tier-based
- On-demand payouts at 5% growth

**General:**
- News Trading: Allowed
- Weekend Holding: Allowed
- EAs/Bots: Allowed
- No max lot size (manage margin responsibly)

### Implementation
```python
FUNDEDNEXT_RULES = {
    'stellar_2step': {
        'phase1_target': 0.08,
        'phase2_target': 0.05,
        'max_daily_loss_pct': 0.05,
        'max_overall_loss_pct': 0.10,
        'drawdown_method': 'equity_or_balance_higher',
        'min_trading_days': 5,
        'time_limit': None,
        'profit_split_max': 0.95
    },
    'stellar_1step': {
        'profit_target': 0.10,
        'max_daily_loss_pct': 0.03,
        'max_overall_loss_pct': 0.06,
        'min_trading_days': 2,
        'time_limit': None
    },
    'stellar_instant': {
        'no_evaluation': True,
        'max_loss_pct': 0.06,
        'drawdown_type': 'trailing',
        'daily_loss_limit': None,
        'min_trading_days': 0,
        'profit_share_tier1': 0.70,
        'profit_share_tier2': 0.80,
        'payout_trigger': 0.05  # 5% growth
    },
    'general': {
        'news_trading_allowed': True,
        'weekend_holding_allowed': True,
        'ea_allowed': True,
        'max_lot_size': None,
        'scaling_double_at': 0.10  # 10% growth doubles account
    }
}
```

### Sources
- [fundednext.com/instant-funding-vs-challenge](https://fundednext.com/blog/instant-funding-vs-challenge-models)
- [luxalgo.com/fundednext-review](https://www.luxalgo.com/blog/prop-firm-review-fundednext-instant-funding/)

---

## Firm: Apex Trader Funding
**Priority:** HIGH

### Key Rules Summary
- **No Daily Drawdown:** Unique - only trailing threshold
- **Trailing Drawdown:** Varies by account size (see table below)
- **No Time Limit:** Unlimited
- **Min Trading Days:** 7
- **Trading Day:** 6 PM one day to 5 PM next day (ET)
- **All Trades Close By:** 4:59 PM ET daily
- **News Trading:** Allowed in evaluation; restricted in funded
- **Consistency Rule:** 30% (no single day > 30% of total profit)
- **Contract Scaling:** Half contracts until safety net reached
- **Weekend Holding:** NOT ALLOWED
- **First $25K Earnings:** 100% to trader
- **Profit Split After $25K:** 90/10
- **Payouts:** Every 8 days, 2 per month max

**Trailing Drawdown by Account Size:**
| Account | Profit Target | Trailing Limit | Contracts |
|---------|--------------|----------------|-----------|
| $25K | $1,500 | $1,500 | 4 |
| $50K | $3,000 | $2,500 | 10 |
| $100K | $6,000 | $3,000 | 14 |
| $150K | $9,000 | $5,000 | 17 |
| $250K | $15,000 | $6,500 | 27 |
| $300K | $20,000 | $7,500 | 35 |

### Implementation
```python
APEX_RULES = {
    'daily_drawdown': None,  # No daily drawdown!
    'drawdown_type': 'trailing_threshold',
    'min_trading_days': 7,
    'trading_day_hours': {'start': '18:00', 'end': '17:00', 'tz': 'US/Eastern'},
    'daily_close_time': '16:59',
    'timezone': 'US/Eastern',
    'consistency_threshold': 0.30,
    'contract_scaling_required': True,
    'scaling_until_safety_net': True,
    'weekend_holding': False,
    'news_trading_evaluation': True,
    'news_trading_funded': False,
    'first_payout_days': 8,
    'first_25k_split': 1.0,  # 100%
    'split_after_25k': 0.90,
    'payouts_per_month': 2,
    
    'account_specs': {
        25000: {'profit_target': 1500, 'trailing': 1500, 'contracts': 4},
        50000: {'profit_target': 3000, 'trailing': 2500, 'contracts': 10},
        100000: {'profit_target': 6000, 'trailing': 3000, 'contracts': 14},
        150000: {'profit_target': 9000, 'trailing': 5000, 'contracts': 17},
        250000: {'profit_target': 15000, 'trailing': 6500, 'contracts': 27},
        300000: {'profit_target': 20000, 'trailing': 7500, 'contracts': 35}
    }
}
```

### Sources
- [apextraderfunding.com](https://apextraderfunding.com/)
- [quantvps.com/apex-pa-account-rules](https://www.quantvps.com/blog/apex-pa-account-rules)
- [livestreamtrading.com/apex-review](https://livestreamtrading.com/apex-funded-trader-review/)

---

# SECTION 5: TRADE EXECUTION BEST PRACTICES

## Technique: Slippage, Spread & Commission Model
**Priority:** MEDIUM  
**Applies To:** All strategies, all instruments

### Description
Transaction costs directly determine strategy profitability. A strategy that shows 2% edge in backtests may be unprofitable after accounting for all-in costs.

**Average Spreads (Major Pairs, Raw ECN Accounts):**
| Pair | Typical Spread | All-In Cost (Spread + Commission) |
|------|---------------|-----------------------------------|
| EUR/USD | 0.1-0.3 pips | $1-5 per lot |
| GBP/USD | 0.2-0.5 pips | $2-6 per lot |
| USD/JPY | 0.1-0.4 pips | $1-5 per lot |
| USD/CAD | 0.3-0.9 pips | $3-9 per lot |
| AUD/USD | 0.2-0.6 pips | $2-6 per lot |
| XAU/USD | 10-30 cents | $5-15 per lot |
| US30 | 1-3 points | $5-15 per lot |

**Slippage Models:**
| Market Condition | Typical Slippage |
|-----------------|-----------------|
| Normal liquid market | 0.1-0.5 pips |
| Low liquidity (Asian session) | 0.5-1.5 pips |
| News events (Tier 1) | 2-10+ pips |
| Market open (Sunday) | 1-5 pips |

### Implementation
```python
# Transaction cost model for profitability analysis
SPREAD_COSTS = {
    'EURUSD': {'spread_pips': 0.2, 'commission_per_lot': 7.0, 'pip_value': 10.0},
    'GBPUSD': {'spread_pips': 0.4, 'commission_per_lot': 7.0, 'pip_value': 10.0},
    'USDJPY': {'spread_pips': 0.3, 'commission_per_lot': 7.0, 'pip_value': 9.0},
    'USDCAD': {'spread_pips': 0.6, 'commission_per_lot': 7.0, 'pip_value': 7.5},
    'AUDUSD': {'spread_pips': 0.4, 'commission_per_lot': 7.0, 'pip_value': 10.0},
    'XAUUSD': {'spread_pips': 20.0, 'commission_per_lot': 7.0, 'pip_value': 1.0},
    'US30': {'spread_pips': 2.0, 'commission_per_lot': 5.0, 'pip_value': 1.0},
}

SLIPPAGE_MODEL = {
    'normal': 0.3,
    'low_liquidity': 1.0,
    'news': 3.0,
    'market_open': 2.0
}

def calculate_all_in_cost(instrument, lots, market_condition='normal',
                          is_round_trip=True):
    """
    Calculate total transaction cost for a trade.
    Returns cost in account currency.
    """
    spec = SPREAD_COSTS.get(instrument, SPREAD_COSTS['EURUSD'])
    
    # Spread cost
    spread_cost = spec['spread_pips'] * spec['pip_value'] * lots
    
    # Commission (round trip = open + close)
    commission = spec['commission_per_lot'] * lots * (2 if is_round_trip else 1)
    
    # Slippage (one-way, applied to entry)
    slippage = SLIPPAGE_MODEL.get(market_condition, 0.3) * spec['pip_value'] * lots
    
    total = spread_cost + commission + slippage
    
    return {
        'spread_cost': spread_cost,
        'commission': commission,
        'slippage_estimate': slippage,
        'total_cost': total,
        'cost_in_pips': total / (spec['pip_value'] * lots) if lots > 0 else 0
    }

def is_strategy_profitable_after_costs(expected_pips_per_trade, 
                                       instrument, lots,
                                       win_rate, market_condition='normal'):
    """
    Check if expected edge survives transaction costs.
    """
    costs = calculate_all_in_cost(instrument, lots, market_condition)
    cost_pips = costs['cost_in_pips']
    
    # After-cost expected return per trade
    net_pips = expected_pips_per_trade - cost_pips
    
    # Expected value
    ev = (win_rate * net_pips) - ((1 - win_rate) * (expected_pips_per_trade / 2))
    
    return {
        'gross_edge_pips': expected_pips_per_trade,
        'cost_pips': cost_pips,
        'net_edge_pips': net_pips,
        'expected_value': ev,
        'is_profitable': ev > 0,
        'cost_as_pct_of_edge': (cost_pips / expected_pips_per_trade * 100) 
                                if expected_pips_per_trade > 0 else 0
    }
```

### Sources
- [fxtrendo.com/forex-currency-pairs](https://fxtrendo.com/forex-currency-pairs/)
- [newyorkcityservers.com/lowest-spread-forex-brokers](https://newyorkcityservers.com/blog/lowest-spread-forex-brokers-2026)
- [vtmarkets.com/best-currency-pairs](https://www.vtmarkets.com/discover/best-currency-pairs-to-trade-top-10-forex-pairs-guide/)

---

# SECTION 6: BOT BEHAVIOR THAT FAILS

## Rule: Common Bot Failure Patterns
**Priority:** HIGH  
**Applies To:** All algorithmic trading on prop firms

### Description
95% of trading bots lose money within 90 days. In prop firm challenges, only 5-10% of bots pass. The most common failure modes:

**1. Overfitting to Historical Data**
- Backtested Sharpe ratios are poor predictors of live performance (R² < 0.025)
- 44% of published strategies fail on new data
- Strategy optimized for specific conditions fails when regime changes

**2. Ignoring Transaction Costs**
- Spreads and commissions erode up to 30% of gains
- Bots that work in commission-free backtests fail in live trading
- Slippage during volatile periods exceeds normal expectations by 10x

**3. Inability to Adapt to Market Changes**
- Trending strategies fail in ranging markets (and vice versa)
- Correlations spike during crisis (diversification disappears)
- Volatility regime changes destroy calibrated position sizing

**4. Poor Risk Management**
- 52% of bot accounts fail within 3 months
- Fixed position sizes don't account for changing volatility
- No drawdown-based reduction
- No circuit breakers

**5. News Event Crashes**
- Unprotected exposure during Tier 1 news
- 5-tick stop can slip 15-20 ticks during NFP
- Liquidity evaporates - stops fill at catastrophic prices

### Implementation
```python
# Bot safety checklist - run before every trading session

def pre_session_safety_check(account, open_positions, pending_orders,
                             today_trades, firm_rules, strategy_stats):
    """
    Comprehensive pre-session safety check for trading bots.
    Returns: (is_safe_to_trade, actions_required, risk_level)
    """
    issues = []
    risk_level = 'GREEN'
    actions = []
    
    # 1. Check drawdown proximity
    current_dd = account.get_current_drawdown_pct()
    max_dd = firm_rules['max_overall_loss_pct']
    dd_ratio = current_dd / max_dd if max_dd > 0 else 0
    
    if dd_ratio >= 0.90:
        issues.append(f"CRITICAL: {current_dd:.1%} drawdown (90%+ of max)")
        risk_level = 'RED'
        actions.append('HALT_TRADING')
    elif dd_ratio >= 0.70:
        issues.append(f"WARNING: {current_dd:.1%} drawdown (70%+ of max)")
        risk_level = 'ORANGE'
        actions.append('REDUCE_SIZE_50')
    
    # 2. Check daily loss proximity
    daily_pnl_pct = account.get_today_pnl_pct()
    daily_limit = firm_rules.get('max_daily_loss_pct', 0.05)
    daily_ratio = abs(daily_pnl_pct) / daily_limit if daily_limit > 0 else 0
    
    if daily_ratio >= 0.90:
        issues.append(f"CRITICAL: {abs(daily_pnl_pct):.1%} of daily limit used")
        risk_level = max(risk_level, 'RED')
        actions.append('HALT_FOR_DAY')
    elif daily_ratio >= 0.60:
        issues.append(f"CAUTION: {abs(daily_pnl_pct):.1%} of daily limit used")
        risk_level = max(risk_level, 'YELLOW')
        actions.append('REDUCE_SIZE_50')
    
    # 3. Check consistency rule
    if 'consistency_threshold' in firm_rules:
        daily_pnls = account.get_daily_pnl_history()
        best_day = max(daily_pnls) if daily_pnls else 0
        total_profit = sum(p for p in daily_pnls if p > 0)
        if total_profit > 0:
            ratio = best_day / total_profit
            if ratio > firm_rules['consistency_threshold']:
                issues.append(f"CONSISTENCY: {ratio:.1%} > {firm_rules['consistency_threshold']:.1%} threshold")
                actions.append('LIMIT_DAILY_PROFIT')
    
    # 4. Check for martingale behavior
    recent_trades = today_trades[-10:]
    is_martingale, confidence, reason = detect_martingale(recent_trades)
    if is_martingale and confidence > 0.7:
        issues.append(f"MARTINGALE DETECTED: {reason}")
        risk_level = 'RED'
        actions.append('HALT_TRADING')
    
    # 5. Check win rate validity (minimum sample)
    if strategy_stats['total_trades'] < 30:
        issues.append(f"LOW SAMPLE: Only {strategy_stats['total_trades']} trades - use conservative sizing")
        actions.append('USE_EIGHTH_KELLY')
    
    # 6. Check for approaching news events
    upcoming_news = get_upcoming_tier1_news()
    for news in upcoming_news:
        minutes_until = news.minutes_until
        if minutes_until < 30:
            issues.append(f"NEWS WARNING: {news.name} in {minutes_until} minutes")
            actions.append('FLATTEN_BEFORE_NEWS')
            risk_level = max(risk_level, 'ORANGE')
    
    # 7. Check weekend hold (Friday afternoon)
    if is_friday_afternoon() and not firm_rules.get('weekend_holding_allowed', True):
        issues.append("WEEKEND: Must close all positions before market close")
        actions.append('FLATTEN_ALL')
    
    # 8. Check inactivity
    days_since_trade = account.days_since_last_trade()
    if days_since_trade > 20:
        issues.append(f"INACTIVITY: {days_since_trade} days since last trade")
        actions.append('PLACE_MINIMUM_TRADE')
    
    is_safe = risk_level not in ['RED'] and 'HALT_TRADING' not in actions
    
    return is_safe, actions, risk_level, issues
```

### Sources
- [fortraders.com/trading-bots-lose-money](https://www.fortraders.com/blog/trading-bots-lose-money)
- [t4tcapitalfm.com/5-common-reasons-traders-fail](https://t4tcapitalfm.com/blog/the-5-most-common-reasons-traders-fail-prop-firm-challenges/)
- [fxreplay.com/why-traders-fail](https://fxreplay.com/learn/why-most-traders-fail-prop-firm-challenges-and-how-fx-replay-can-help-you-pass)

---

# APPENDIX A: QUICK REFERENCE - FIRM RULE COMPARISON

| Rule | FTMO | FundedNext | FundingPips | The5%ers | Apex |
|------|------|-----------|-------------|----------|------|
| Daily Loss | 5% equity | 5%/3% equity | 3% static | 5% (High Stakes) | None |
| Max Loss | 10% | 10%/6% | 6% static | 10%/4% | Trailing |
| Consistency | No | No | 35%/15% | No | 30% |
| Min Days | 4/phase | 5/2/0 | 3 | 3 | 7 |
| Weekend Hold | Swing only | Yes | No (funded) | Yes | No |
| News Trading | 2-min buffer | Yes | No (funded) | Yes | Eval only |
| EAs/Bots | Yes | Yes | Yes | Yes | Yes |
| Time Limit | None | None | None | 12mo/30-60d | None |
| Martingale | Banned | Banned | Banned | Banned | Banned |
| Profit Split | 80-90% | Up to 95% | Varies | 50-100% | 90-100% |

---

# APPENDIX B: POSITION SIZING DECISION TREE

```
START
  |
  v
Do you have 50+ trades of history?
  |
  +-- YES --> Calculate Kelly Criterion
  |              |
  |              v
  |         Use Quarter-Kelly (25% of full)
  |              |
  |              v
  |         Cap at 1% risk per trade
  |              |
  |              v
  |         Are you in drawdown?
  |              |
  |              +-- YES (>30% of max) --> Reduce to Eighth-Kelly
  |              |
  |              +-- NO --> Use Quarter-Kelly
  |
  +-- NO (< 50 trades) --> Use Fixed Fractional
                |
                v
           Risk 0.5% per trade
                |
                v
           After 30 trades --> Half-Kelly
                |
                v
           After 50 trades --> Quarter-Kelly
```

---

# APPENDIX C: DAILY PRE-TRADING CHECKLIST (BOT INTEGRATION)

```python
DAILY_BOT_CHECKLIST = {
    'risk_checks': {
        'account_drawdown_pct': '< 30% of max allowed',
        'daily_loss_used_pct': '< 50% of daily limit',
        'portfolio_heat': '< 6% of equity',
        'positions_correlated': 'Check correlation < 0.7'
    },
    'compliance_checks': {
        'news_blackout': 'No Tier 1 news in next 30 min',
        'weekend_hold': 'Friday? Must close by 4 PM ET',
        'lot_size_within_limit': 'Check firm max lots',
        'consistency_rule': 'Best day < 80% of threshold',
        'inactivity_counter': '< 20 days since last trade'
    },
    'strategy_checks': {
        'win_rate_valid': '>= 30 trades in sample',
        'kelly_fraction': 'Quarter-Kelly for < 100 trades',
        'circuit_breaker': 'GREEN or YELLOW only',
        'no_martingale_pattern': 'No size doubling after losses',
        'expected_value_positive': 'Edge > 2x transaction costs'
    },
    'execution_checks': {
        'spread_normal': '< 3x average spread',
        'slippage_model_updated': 'Current volatility regime',
        'commission_accounted': 'In profit target calculation',
        'pending_orders_reviewed': 'No orders near news time'
    }
}
```

---

*Document compiled from 20+ industry sources. Rules change frequently - always verify current terms with your specific prop firm before trading.*
