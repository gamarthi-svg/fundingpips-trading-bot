# Advanced Algorithmic Trading Strategies for Prop Firm Evaluations

## Executive Summary

This document provides a comprehensive research compilation of algorithmic trading strategies optimized for proprietary trading firm evaluations. Each strategy includes specific entry/exit rules, backtest expectations, prop firm compliance considerations, and Python pseudocode for implementation with MetaAPI/MetaTrader integration.

### Key Statistics from Research
- **Prop firm pass rates:** 5-14% of traders pass evaluations [Source: FPFX Tech, 300,000+ accounts]
- **Payout rates:** Only ~7% of all traders ever receive a payout [Source: Finance Magnates]
- **Risk per trade:** Successful funded traders cluster at 0.25-0.5% risk per trade
- **Most common failure reason:** Breaching daily drawdown limits (54% of failures)
- **SMC backtest (2,600 trades):** 61.2% win rate, 2.17 profit factor [Source: Medium backtest study]

---

## Table of Contents

1. [Volume-Based Strategies](#category-1-volume-based-strategies)
2. [Order Flow & Market Structure](#category-2-order-flow--market-structure)
3. [Multi-Timeframe Strategies](#category-3-multi-timeframe-strategies)
4. [Mean Reversion vs Trend Following](#category-4-mean-reversion-vs-trend-following)
5. [Per-Instrument Strategies](#category-5-per-instrument-strategies)
6. [Prop Firm Compliance Framework](#prop-firm-compliance-framework)
7. [Strategy Suitability Scores](#strategy-suitability-scores)

---

## Category 1: Volume-Based Strategies

---

### Strategy: Volume Profile Mean Reversion (POC Magnet)

**Best For:** ES, NQ futures; XAUUSD; EURUSD
**Timeframe:** M5 (entry), H1/H4 (volume profile context)
**Market Condition:** Ranging, consolidating markets; post-trend exhaustion

#### Entry Rules
1. Price must move 30+ points (ES) or 60+ points (NQ) away from the session POC
2. Wait for the first sign of reversal (engulfing candle, pin bar, or doji at extreme)
3. Price must close back toward the POC direction on M5 timeframe
4. Volume spike (1.5x average) on the reversal candle confirms rejection

#### Exit Rules
- **Stop Loss:** 10-15 points beyond the reversal candle extreme (ES: ~$500-750 risk)
- **Take Profit 1:** POC level (50% position) — typically 25-40 points profit
- **Take Profit 2:** Opposite side of value area (50% position with breakeven stop)
- **Time Exit:** Close all positions if price hasn't reached POC within 2 hours

#### Backtest Expectations
- Win Rate: 70-75% (ranging markets), 55-60% (trending markets)
- Profit Factor: 2.0-2.5 (ranging), 1.3-1.5 (trending)
- Max Drawdown: 8-12% over 100 trades
- Sharpe Ratio: 1.5-2.0 (ranging conditions)
- Average R:R: 1.8:1 to 2.5:1

#### Prop Firm Compliance
- Excellent compliance profile: tight stops, clear targets, defined time exits
- Risk per trade at 0.5% with 10-point stops on $100k account = ~$500 risk
- Avoid trading during high-impact news when volume profiles distort
- Daily trade limit: max 2-3 setups per session recommended

#### Python Pseudocode
```python
def volume_profile_poc_strategy(df_m5, df_h1, config):
    """
    Volume Profile POC Mean Reversion Strategy
    """
    # --- Indicators ---
    poc = calculate_poc(df_h1)  # Point of Control
    vah = calculate_value_area_high(df_h1)  # Value Area High (70%)
    val = calculate_value_area_low(df_h1)   # Value Area Low (70%)
    volume_sma = df_m5['volume'].rolling(20).mean()
    atr = calculate_atr(df_m5, period=14)
    
    signals = []
    
    for i in range(1, len(df_m5)):
        price = df_m5['close'].iloc[i]
        dist_from_poc = abs(price - poc)
        
        # --- Entry Logic ---
        # Long: Price far below POC + reversal candle + volume spike
        if (price < poc - config['min_distance_from_poc'] and
            is_bullish_reversal_candle(df_m5, i) and
            df_m5['volume'].iloc[i] > volume_sma.iloc[i] * 1.5 and
            dist_from_poc > config['distance_threshold']):
            
            sl = df_m5['low'].iloc[i] - atr.iloc[i] * 0.5
            tp = poc  # Target the POC
            
            signals.append({
                'direction': 'LONG',
                'entry': price,
                'stop_loss': sl,
                'take_profit': tp,
                'risk_reward': (tp - price) / (price - sl)
            })
            
        # Short: Price far above POC + reversal candle + volume spike
        elif (price > poc + config['min_distance_from_poc'] and
              is_bearish_reversal_candle(df_m5, i) and
              df_m5['volume'].iloc[i] > volume_sma.iloc[i] * 1.5 and
              dist_from_poc > config['distance_threshold']):
            
            sl = df_m5['high'].iloc[i] + atr.iloc[i] * 0.5
            tp = poc  # Target the POC
            
            signals.append({
                'direction': 'SHORT',
                'entry': price,
                'stop_loss': sl,
                'take_profit': tp,
                'risk_reward': (price - tp) / (sl - price)
            })
    
    return signals
```

#### Sources
- [FuturesHive Volume Profile Trading Strategy 2026](https://www.futureshive.com/blog/volume-profile-trading-strategy-2025)
- [JournalPlus Volume Profile Trading Strategy Guide](https://journalplus.co/strategies/volume-profile-trading)

---

### Strategy: VWAP Trend Following with Standard Deviation Bands

**Best For:** XAUUSD, EURUSD, NAS100, US30
**Timeframe:** M15 (entry), H1 (trend context)
**Market Condition:** Trending markets with clear directional bias

#### Entry Rules
1. Price closes above VWAP + 1st standard deviation band (long) or below (short)
2. Candle color confirms direction (green for long, red for short)
3. Price above daily open for longs / below daily open for shorts
4. Volume >= average volume for the session (confirms participation)

#### Exit Rules
- **Stop Loss:** 1.5x ATR from entry, dynamically adjusted
- **Take Profit:** Trailing stop at 1.5x ATR behind price
- **Time Exit:** Close all positions at session end (avoid overnight risk)
- **VWAP Reclaim Exit:** Close if price closes back across VWAP

#### Backtest Expectations
- Win Rate: 45-55% (trend-following nature)
- Profit Factor: 1.5-2.0
- Max Drawdown: 15-25% (high volatility noted)
- Sharpe Ratio: 1.0-1.5
- Total Returns: 713% over 3 years reported on Apple/Bitcoin/Tesla M15 (0% commission) [Source: QuantVPS]
- **Critical:** 0.1% commission per trade reduces returns from +713% to -97%

#### Prop Firm Compliance
- Moderate compliance: time-based exits help, but drawdowns can be large
- **Must use tight commission accounting** — high-frequency VWAP strategies are commission-sensitive
- Daily VWAP reset means fresh reference each session
- Position sizing should account for ATR-based stops (larger stops in volatile sessions)

#### Python Pseudocode
```python
def vwap_trend_strategy(df, config):
    """
    VWAP Trend Following with ATR Trailing Stops
    """
    # --- Indicators ---
    df['vwap'] = calculate_vwap(df)  # Session-based VWAP
    df['vwap_std1_upper'] = df['vwap'] + df['close'].rolling(20).std()
    df['vwap_std1_lower'] = df['vwap'] - df['close'].rolling(20).std()
    df['atr'] = calculate_atr(df, period=14)
    df['day_open'] = df.groupby(df.index.date)['open'].transform('first')
    df['volume_sma'] = df['volume'].rolling(20).mean()
    
    signals = []
    position = None
    trailing_stop = None
    
    for i in range(1, len(df)):
        candle_color = 1 if df['close'].iloc[i] > df['open'].iloc[i] else -1
        
        # --- Entry Logic ---
        if position is None:
            # Long: Price > VWAP upper band + green candle + above daily open
            if (df['close'].iloc[i] > df['vwap_std1_upper'].iloc[i] and
                candle_color == 1 and
                df['close'].iloc[i] > df['day_open'].iloc[i] and
                df['volume'].iloc[i] >= df['volume_sma'].iloc[i]):
                
                entry = df['close'].iloc[i]
                sl = entry - df['atr'].iloc[i] * config['atr_sl_multiplier']
                trailing_stop = sl
                position = {'direction': 'LONG', 'entry': entry, 'sl': sl}
            
            # Short: Price < VWAP lower band + red candle + below daily open
            elif (df['close'].iloc[i] < df['vwap_std1_lower'].iloc[i] and
                  candle_color == -1 and
                  df['close'].iloc[i] < df['day_open'].iloc[i] and
                  df['volume'].iloc[i] >= df['volume_sma'].iloc[i]):
                
                entry = df['close'].iloc[i]
                sl = entry + df['atr'].iloc[i] * config['atr_sl_multiplier']
                trailing_stop = sl
                position = {'direction': 'SHORT', 'entry': entry, 'sl': sl}
        
        # --- Exit Logic ---
        elif position['direction'] == 'LONG':
            # Update trailing stop
            new_stop = df['close'].iloc[i] - df['atr'].iloc[i] * config['atr_sl_multiplier']
            trailing_stop = max(trailing_stop, new_stop)
            
            # VWAP reclaim exit
            if df['close'].iloc[i] < df['vwap'].iloc[i]:
                signals.append({'action': 'EXIT', 'reason': 'vwap_reclaim', 'price': df['close'].iloc[i]})
                position = None
            # Trailing stop hit
            elif df['low'].iloc[i] <= trailing_stop:
                signals.append({'action': 'EXIT', 'reason': 'trailing_stop', 'price': trailing_stop})
                position = None
        
        elif position['direction'] == 'SHORT':
            new_stop = df['close'].iloc[i] + df['atr'].iloc[i] * config['atr_sl_multiplier']
            trailing_stop = min(trailing_stop, new_stop)
            
            if df['close'].iloc[i] > df['vwap'].iloc[i]:
                signals.append({'action': 'EXIT', 'reason': 'vwap_reclaim', 'price': df['close'].iloc[i]})
                position = None
            elif df['high'].iloc[i] >= trailing_stop:
                signals.append({'action': 'EXIT', 'reason': 'trailing_stop', 'price': trailing_stop})
                position = None
    
    return signals
```

#### Sources
- [QuantVPS: Backtest VWAP Trading Strategy Python](https://www.quantvps.com/blog/backtest-vwap-trading-strategy-python)
- [TradersPost: Using VWAP for Gold Trading Strategies](https://blog.traderspost.io/article/using-vwap-for-gold-trading-strategies)
- [HumbledTrader: VWAP Strategy Secrets](https://www.humbledtrader.com/blog/vwap-strategy-secrets-boosting-your-trading-skills-to-the-next-level/)

---

### Strategy: Cumulative Volume Delta (CVD) Divergence

**Best For:** Futures (ES, NQ), XAUUSD, major forex pairs
**Timeframe:** M5, M15 for signals; H1 for context
**Market Condition:** Trending markets at exhaustion points; key support/resistance levels

#### Entry Rules
1. Price makes a higher high but CVD makes a lower high (bearish divergence)
2. Price makes a lower low but CVD makes a higher low (bullish divergence)
3. Divergence occurs at a known reference level (prior swing, VWAP, liquidity zone)
4. Wait for CVD direction shift (reaction) before entry — not anticipatory

#### Exit Rules
- **Stop Loss:** Beyond the sweep extreme (the high/low that created the divergence)
- **Take Profit:** Opposite liquidity pool or next structural level
- **Time Exit:** Close within 1 hour if no follow-through (M5) or 4 hours (M15)
- **CVD Realignment Exit:** Close if CVD realigns with price direction

#### Backtest Expectations
- Win Rate: 55-65% (divergence at key levels)
- Profit Factor: 1.8-2.3
- Max Drawdown: 10-15%
- Sharpe Ratio: 1.3-1.8
- **Best when combined with:** Volume profile nodes, order blocks, or FVGs

#### Prop Firm Compliance
- Good compliance profile when combined with structural levels
- Divergence signals are discretionary — requires strict rule-based implementation
- Avoid trading divergence in low-volume conditions (Asian session for some pairs)
- Risk per trade: 0.5% recommended

#### Python Pseudocode
```python
def cvd_divergence_strategy(df, config):
    """
    Cumulative Volume Delta Divergence Strategy
    """
    # --- Indicators ---
    df['volume_delta'] = df['buy_volume'] - df['sell_volume']  # Requires tick data
    df['cvd'] = df['volume_delta'].cumsum()
    df['price_swing_high'] = find_swing_highs(df['high'], config['swing_lookback'])
    df['price_swing_low'] = find_swing_lows(df['low'], config['swing_lookback'])
    
    signals = []
    
    for i in range(config['swing_lookback'] * 2, len(df)):
        # --- Detect Bearish Divergence ---
        prev_high_idx = df['price_swing_high'].iloc[i-config['swing_lookback']:i].idxmax()
        curr_high_idx = df['high'].iloc[i-config['swing_lookback']:i].idxmax()
        
        if (df['high'].loc[curr_high_idx] > df['high'].loc[prev_high_idx] and
            df['cvd'].loc[curr_high_idx] < df['cvd'].loc[prev_high_idx]):
            
            # Wait for CVD reaction (direction shift)
            if df['cvd'].iloc[i] < df['cvd'].iloc[i-1] and df['cvd'].iloc[i-1] < df['cvd'].iloc[i-2]:
                entry = df['close'].iloc[i]
                sl = df['high'].loc[curr_high_idx] + config['sl_buffer']
                tp = find_nearest_support(df, i)
                
                signals.append({
                    'direction': 'SHORT',
                    'type': 'bearish_divergence',
                    'entry': entry,
                    'stop_loss': sl,
                    'take_profit': tp,
                    'risk_reward': (entry - tp) / (sl - entry)
                })
        
        # --- Detect Bullish Divergence ---
        prev_low_idx = df['price_swing_low'].iloc[i-config['swing_lookback']:i].idxmin()
        curr_low_idx = df['low'].iloc[i-config['swing_lookback']:i].idxmin()
        
        if (df['low'].loc[curr_low_idx] < df['low'].loc[prev_low_idx] and
            df['cvd'].loc[curr_low_idx] > df['cvd'].loc[prev_low_idx]):
            
            if df['cvd'].iloc[i] > df['cvd'].iloc[i-1] and df['cvd'].iloc[i-1] > df['cvd'].iloc[i-2]:
                entry = df['close'].iloc[i]
                sl = df['low'].loc[curr_low_idx] - config['sl_buffer']
                tp = find_nearest_resistance(df, i)
                
                signals.append({
                    'direction': 'LONG',
                    'type': 'bullish_divergence',
                    'entry': entry,
                    'stop_loss': sl,
                    'take_profit': tp,
                    'risk_reward': (tp - entry) / (entry - sl)
                })
    
    return signals
```

#### Sources
- [Bookmap: Cumulative Volume Delta Trading Strategy](https://bookmap.com/blog/how-cumulative-volume-delta-transform-your-trading-strategy)
- [ZitaPlus: CVD Divergence Details & Strategies](https://zitaplus.com/blog/analysis/cumulative-volume-delta-divergence-details--strategies/)
- [Reddit r/Daytrading: CVD Tool Analysis](https://www.reddit.com/r/Daytrading/comments/1kmalg2/the_tools_that_make_the_difference_in_trading/)

---

### Strategy: Relative Volume Anomaly Detection

**Best For:** All liquid instruments (ES, XAUUSD, EURUSD, NAS100)
**Timeframe:** M5, M15
**Market Condition:** Breakout confirmation, reversal detection after volume climaxes

#### Entry Rules
1. Relative Volume (RVOL) exceeds 2.0x the average for the same time period
2. Volume bar colored as anomaly by statistical detection (bright colors)
3. Price at key level (support/resistance, VWAP, pivot) — confluence required
4. Candlestick pattern confirms direction (engulfing, pin bar, or momentum candle)

#### Exit Rules
- **Stop Loss:** Below/above the volume anomaly candle
- **Take Profit:** Next structural level or 2:1 minimum R:R
- **Time Exit:** If price doesn't move within 30 minutes, exit (volume signals decay quickly)

#### Backtest Expectations
- Win Rate: 50-60% (breakout continuation), 60-65% (volume climax reversal)
- Profit Factor: 1.5-2.0
- Max Drawdown: 12-18%
- Sharpe Ratio: 1.2-1.6
- **Best when:** Combined with price action at key levels

#### Prop Firm Compliance
- Moderate: volume spikes can occur during news (check news calendar)
- Ensure RVOL threshold isn't triggered by scheduled economic releases
- Use confluence with technical levels for higher-probability setups

#### Python Pseudocode
```python
def relative_volume_anomaly_strategy(df, config):
    """
    Relative Volume Anomaly Detection Strategy
    """
    # --- Indicators ---
    df['volume_sma'] = df['volume'].rolling(config['volume_lookback']).mean()
    df['volume_std'] = df['volume'].rolling(config['volume_lookback']).std()
    df['rvol'] = df['volume'] / df['volume_sma']
    df['anomaly_threshold'] = config['rvol_threshold']  # Typically 2.0
    df['is_anomaly'] = df['rvol'] > df['anomaly_threshold']
    df['atr'] = calculate_atr(df, period=14)
    
    signals = []
    
    for i in range(config['volume_lookback'] + 1, len(df)):
        if not df['is_anomaly'].iloc[i]:
            continue
        
        price = df['close'].iloc[i]
        atr = df['atr'].iloc[i]
        
        # Bullish anomaly: high volume on up candle near support
        if (df['close'].iloc[i] > df['open'].iloc[i] and
            is_near_support(df, i, config['level_tolerance']) and
            is_bullish_candle(df, i)):
            
            entry = price
            sl = df['low'].iloc[i] - atr * 0.3
            tp = find_next_resistance(df, i)
            
            if (tp - entry) / (entry - sl) >= config['min_risk_reward']:
                signals.append({'direction': 'LONG', 'entry': entry, 'sl': sl, 'tp': tp})
        
        # Bearish anomaly: high volume on down candle near resistance
        elif (df['close'].iloc[i] < df['open'].iloc[i] and
              is_near_resistance(df, i, config['level_tolerance']) and
              is_bearish_candle(df, i)):
            
            entry = price
            sl = df['high'].iloc[i] + atr * 0.3
            tp = find_next_support(df, i)
            
            if (entry - tp) / (sl - entry) >= config['min_risk_reward']:
                signals.append({'direction': 'SHORT', 'entry': entry, 'sl': sl, 'tp': tp})
    
    return signals
```

#### Sources
- [TradingView: Relative Volume Suite by QuantAlgo](https://www.tradingview.com/script/TLi6fekZ-Relative-Volume-Suite-QuantAlgo/)
- [LuxAlgo: Relative Volume at Time Indicator](https://www.luxalgo.com/blog/relative-volume-at-time-indicator-comparing-volume-to-historical-averages/)
- [TradeFundrr: Relative Volume Spike Setups](https://tradefundrr.com/relative-volume-spike-setups/)

---


## Category 2: Order Flow & Market Structure

---

### Strategy: Liquidity Sweep + FVG Reclaim (SMC Model)

**Best For:** XAUUSD, GBPUSD, EURUSD, NAS100
**Timeframe:** M1-M5 (entry), M15-H1 (bias)
**Market Condition:** London/NY session opens; after Asian range formation

#### Entry Rules
1. Mark Asian session high and low (liquidity pools)
2. Wait for London/NY session to sweep one side (take out Asian high or low)
3. After sweep, identify the Fair Value Gap (FVG) created by the displacement move
4. Wait for price to retrace back into the FVG zone
5. Enter in direction of the original displacement (with the institution, not against)
6. Stop loss above/below the sweep wick

#### Exit Rules
- **Stop Loss:** Above the sweep high (for shorts) or below the sweep low (for longs) — typically 5-15 pips
- **Take Profit:** Opposite liquidity pool (next Asian high/low) or previous structural point
- **R Expectation:** 2R-10R clean trades reported, targeting minimum 2:1 R:R
- **Time Exit:** Close before end of session if target not reached

#### Backtest Expectations
- Win Rate: 60-65% (filtered to high-quality setups)
- Profit Factor: 2.0-3.0
- Max Drawdown: 10-15%
- Sharpe Ratio: 1.5-2.5
- **Key data point:** SMC backtest across 2,600 trades on 10 assets (Jan 2024 - Mar 2026):
  - Average win rate: 61.2%
  - Average profit factor: 2.17
  - Gold (XAUUSD) performed best: 64.2% WR, 2.47 PF

#### Prop Firm Compliance
- **Excellent for prop firms:** high R:R means fewer trades needed to hit profit targets
- Small stops (5-15 pips) with 2R+ targets = efficient risk usage
- Only trade during session "killzones" (London: 8-11 AM GMT, NY: 1-4 PM GMT)
- Max 1-2 trades per session recommended
- Avoid trading during major news (NFP, inflation data)

#### Python Pseudocode
```python
def liquidity_sweep_fvg_strategy(df_m1, df_m5, config):
    """
    Liquidity Sweep + FVG Reclaim Strategy (SMC Model)
    """
    # --- Session Analysis ---
    asian_high, asian_low = get_asian_session_range(df_m5)
    current_session = get_current_session(df_m1)
    
    signals = []
    sweep_detected = False
    fvg_zone = None
    sweep_direction = None
    
    for i in range(len(df_m5) - 1):
        # --- Step 1: Detect Liquidity Sweep ---
        if not sweep_detected:
            # Bullish sweep: Price takes out Asian low, then reverses
            if (df_m5['low'].iloc[i] < asian_low and
                df_m5['close'].iloc[i] > asian_low and
                current_session in ['London', 'New_York']):
                sweep_detected = True
                sweep_direction = 'BULLISH'
                sweep_low = df_m5['low'].iloc[i]
                
            # Bearish sweep: Price takes out Asian high, then reverses
            elif (df_m5['high'].iloc[i] > asian_high and
                  df_m5['close'].iloc[i] < asian_high and
                  current_session in ['London', 'New_York']):
                sweep_detected = True
                sweep_direction = 'BEARISH'
                sweep_high = df_m5['high'].iloc[i]
        
        # --- Step 2: Identify FVG after sweep ---
        if sweep_detected and fvg_zone is None:
            fvg_zone = detect_fair_value_gap(df_m5, i)
        
        # --- Step 3: Wait for price to re-enter FVG ---
        if sweep_detected and fvg_zone is not None:
            fvg_top, fvg_bottom = fvg_zone
            
            if sweep_direction == 'BULLISH':
                if fvg_bottom <= df_m5['close'].iloc[i] <= fvg_top:
                    entry = df_m5['close'].iloc[i]
                    sl = sweep_low - config['sl_buffer_pips']
                    tp = asian_high  # Target opposite liquidity
                    
                    signals.append({
                        'direction': 'LONG',
                        'entry': entry,
                        'stop_loss': sl,
                        'take_profit': tp,
                        'risk_reward': (tp - entry) / (entry - sl),
                        'session': current_session
                    })
                    sweep_detected = False
                    fvg_zone = None
            
            elif sweep_direction == 'BEARISH':
                if fvg_bottom <= df_m5['close'].iloc[i] <= fvg_top:
                    entry = df_m5['close'].iloc[i]
                    sl = sweep_high + config['sl_buffer_pips']
                    tp = asian_low  # Target opposite liquidity
                    
                    signals.append({
                        'direction': 'SHORT',
                        'entry': entry,
                        'stop_loss': sl,
                        'take_profit': tp,
                        'risk_reward': (entry - tp) / (sl - entry),
                        'session': current_session
                    })
                    sweep_detected = False
                    fvg_zone = None
    
    return signals

def detect_fair_value_gap(df, idx):
    """Detect 3-candle FVG pattern"""
    if idx < 2:
        return None
    c1, c2, c3 = df.iloc[idx-2], df.iloc[idx-1], df.iloc[idx]
    
    # Bullish FVG: c2 low > c1 high (gap up)
    if c2['low'] > c1['high']:
        return (c2['low'], c1['high'])
    
    # Bearish FVG: c2 high < c1 low (gap down)
    if c2['high'] < c1['low']:
        return (c1['low'], c2['high'])
    
    return None
```

#### Sources
- [Medium: SMC Trading Liquidity Sweep + FVG Reclaim Model](https://medium.com/@clydejnr7/smc-trading-the-liquidity-sweep-fvg-reclaim-model-todays-setup-guide-7f4251049ffb)
- [Medium: Backtested 2,600 Trades Using SMC](https://medium.com/@space.garaa/i-backtested-2-600-trades-using-smart-money-concepts-heres-what-actually-works-bb3c671098c6)
- [ACY: Gold Trading SMC Guide](https://acy.com/en/market-news/education/ultimate-guide-backtesting-trading-gold-xau-usd-j-o-110321/)

---

### Strategy: Break of Structure (BOS) + Order Block Entry

**Best For:** EURUSD, GBPUSD, XAUUSD
**Timeframe:** M15 (entry), H1 (structure context), H4 (trend bias)
**Market Condition:** Trending markets; after pullback/retest

#### Entry Rules
1. Identify higher timeframe trend (H4): price making HH/HL (bullish) or LH/LL (bearish)
2. On H1, identify BOS: price breaks previous swing high/low with conviction
3. Mark the order block: the last opposing candle before the impulsive BOS move
4. Wait for price to retrace to the order block zone
5. Enter on first M15 candle showing rejection at the order block
6. Volume confirmation: retracement volume < impulse volume

#### Exit Rules
- **Stop Loss:** Beyond the order block extreme (typically 10-20 pips)
- **Take Profit:** Next structural level or 2:1 minimum R:R
- **BOS Invalidation Exit:** Close if price breaks back through the order block

#### Backtest Expectations
- Win Rate: 55-60% (BOS continuation)
- Profit Factor: 1.5-2.0
- Max Drawdown: 12-18%
- Sharpe Ratio: 1.2-1.6
- **Important note:** Large-scale backtest of order blocks alone (without BOS context) showed NEGATIVE results across most markets. Context is critical.

#### Prop Firm Compliance
- Moderate: requires multi-timeframe analysis which adds complexity
- BOS entries offer good R:R when order blocks are respected
- Must have strict invalidation rules — failed order blocks can lead to large losses
- Risk 0.5% per trade maximum

#### Python Pseudocode
```python
def bos_order_block_strategy(df_m15, df_h1, df_h4, config):
    """
    Break of Structure + Order Block Entry Strategy
    """
    # --- Higher Timeframe Analysis ---
    h4_trend = identify_trend(df_h4)  # 'bullish' or 'bearish'
    
    signals = []
    order_blocks = []
    
    for i in range(2, len(df_h1)):
        # --- Detect BOS ---
        if h4_trend == 'bullish':
            if (df_h1['close'].iloc[i] > df_h1['high'].iloc[i-1] and
                df_h1['close'].iloc[i-1] < df_h1['high'].iloc[i-2]):
                # BOS detected — mark the bullish order block
                ob = find_bullish_order_block(df_h1, i)
                if ob:
                    order_blocks.append(ob)
        
        elif h4_trend == 'bearish':
            if (df_h1['close'].iloc[i] < df_h1['low'].iloc[i-1] and
                df_h1['close'].iloc[i-1] > df_h1['low'].iloc[i-2]):
                # BOS detected — mark the bearish order block
                ob = find_bearish_order_block(df_h1, i)
                if ob:
                    order_blocks.append(ob)
    
    # --- M15 Entry Logic ---
    for ob in order_blocks:
        for j in range(len(df_m15)):
            if is_price_in_zone(df_m15['close'].iloc[j], ob['zone']):
                if has_rejection_candle(df_m15, j, ob['direction']):
                    entry = df_m15['close'].iloc[j]
                    sl = ob['extreme'] + config['sl_buffer']
                    tp = find_next_structure(df_m15, j, ob['direction'])
                    
                    signals.append({
                        'direction': ob['direction'],
                        'entry': entry,
                        'stop_loss': sl,
                        'take_profit': tp,
                        'order_block': ob
                    })
    
    return signals

def find_bullish_order_block(df, idx):
    """Last bearish candle before impulsive move up"""
    for i in range(idx-1, max(0, idx-10), -1):
        if df['close'].iloc[i] < df['open'].iloc[i]:  # Bearish candle
            return {
                'zone': (df['high'].iloc[i], df['low'].iloc[i]),
                'extreme': df['low'].iloc[i],
                'direction': 'LONG'
            }
    return None
```

#### Sources
- [InnerCircleTrader: CHOCH vs BOS vs MSS](https://innercircletrader.net/tutorials/change-of-character-choch-in-trading/)
- [TradingFinder: BOS vs CHoCH Trading](https://tradingfinder.com/education/forex/bos-vs-choch/)
- [Reddit r/algotrading: Order Block Backtest Results](https://www.reddit.com/r/algotrading/comments/1qvovpv/i_tested_for_1_year_order_blocks_smart_money/)

---

### Strategy: Fair Value Gap (FVG) Mitigation Entry

**Best For:** XAUUSD, EURUSD, BTCUSD, major forex
**Timeframe:** M5 (entry), M15/H1 (FVG context)
**Market Condition:** Post-impulse, pullback/consolidation phase

#### Entry Rules
1. Identify a clear 3-candle FVG on M15 or H1
2. Wait for price to retrace back to the FVG zone
3. Enter at 50% of the FVG (aggressive) or at the FVG edge (conservative)
4. Confirm with volume: declining volume during retracement
5. Entry in direction of the original impulse

#### Exit Rules
- **Stop Loss:** Beyond the opposite side of the FVG
- **Take Profit:** Next structural level or full gap fill + extension
- **Time Exit:** Close if gap doesn't fill within 2-5 candles
- **Partial Exit:** Take 50% at full gap fill, move SL to breakeven

#### Backtest Expectations
- Win Rate: 60-65% (trend continuation), 50-55% (reversal)
- Profit Factor: 1.8-2.5
- Max Drawdown: 10-15%
- Sharpe Ratio: 1.4-2.0
- FVG fill rate: ~70-80% eventually get filled

#### Prop Firm Compliance
- Excellent: clear, objective levels for SL and TP
- FVG provides natural risk parameters
- Works well with 0.5% risk per trade
- Combine with higher timeframe bias for best results

#### Python Pseudocode
```python
def fvg_mitigation_strategy(df_m5, df_h1, config):
    """
    Fair Value Gap Mitigation Entry Strategy
    """
    # --- Identify FVGs on higher timeframe ---
    fvgs = detect_all_fvgs(df_h1, config['min_fvg_size'])
    
    signals = []
    
    for fvg in fvgs:
        # Look for price returning to FVG on M5
        for i in range(len(df_m5)):
            price = df_m5['close'].iloc[i]
            
            # Check if price is within FVG zone
            if fvg['bottom'] <= price <= fvg['top']:
                # Check declining volume on retracement
                vol_declining = df_m5['volume'].iloc[i] < df_m5['volume'].iloc[i-1]
                
                if fvg['type'] == 'BULLISH' and vol_declining:
                    entry = price  # Or fvg['bottom'] for limit entry
                    sl = fvg['bottom'] - config['sl_buffer']
                    tp = find_next_resistance(df_m5, i)
                    
                    if (tp - entry) / (entry - sl) >= config['min_rr']:
                        signals.append({
                            'direction': 'LONG',
                            'entry': entry,
                            'stop_loss': sl,
                            'take_profit': tp,
                            'fvg': fvg
                        })
                
                elif fvg['type'] == 'BEARISH' and vol_declining:
                    entry = price
                    sl = fvg['top'] + config['sl_buffer']
                    tp = find_next_support(df_m5, i)
                    
                    if (entry - tp) / (sl - entry) >= config['min_rr']:
                        signals.append({
                            'direction': 'SHORT',
                            'entry': entry,
                            'stop_loss': sl,
                            'take_profit': tp,
                            'fvg': fvg
                        })
    
    return signals

def detect_all_fvgs(df, min_size):
    """Detect all 3-candle FVG patterns"""
    fvgs = []
    for i in range(2, len(df)):
        c1, c2, c3 = df.iloc[i-2], df.iloc[i-1], df.iloc[i]
        
        # Bullish FVG
        if c2['low'] > c1['high'] and (c2['low'] - c1['high']) >= min_size:
            fvgs.append({
                'type': 'BULLISH',
                'top': c2['low'],
                'bottom': c1['high'],
                'timestamp': df.index[i]
            })
        
        # Bearish FVG
        if c2['high'] < c1['low'] and (c1['low'] - c2['high']) >= min_size:
            fvgs.append({
                'type': 'BEARISH',
                'top': c1['low'],
                'bottom': c2['high'],
                'timestamp': df.index[i]
            })
    
    return fvgs
```

#### Sources
- [ForexTester: Fair Value Gap Trading](https://forextester.com/blog/fair-value-gap/)
- [LiteFinance: Fair Value Gap Trading Strategy Guide](https://www.litefinance.org/blog/for-beginners/trading-strategies/fair-value-gap-trading-strategy/)
- [TraderVue: Fair Value Gaps Explained](https://www.tradervue.com/blog/fair-value-gaps)
- [Reddit: Inverted FVG Model 80% Win Rate](https://www.reddit.com/r/Daytrading/comments/1dfcgqf/2000_day_using_inverted_fair_value_gap_model/)

---


## Category 3: Multi-Timeframe Strategies

---

### Strategy: Top-Down Trend Filter + Lower Timeframe Entry

**Best For:** XLP, XLU, consumer staples/utility ETFs; applies to EURUSD, XAUUSD
**Timeframe:** Daily (trend), H4 (intermediate), H1 (entry), M15 (timing)
**Market Condition:** Clearly trending markets with identifiable pullback patterns

#### Entry Rules
1. **Daily filter:** Close > close 250 days ago (long-term uptrend)
2. **Intermediate filter:** Close > close 22 days ago (medium-term uptrend)
3. **Pullback condition:** Close today is a 3-day low of the close (short-term weakness)
4. **Entry trigger:** All 3 conditions true — enter long at close
5. **Sell condition:** Close when close > yesterday's close

#### Exit Rules
- **Stop Loss:** Below the 22-day low or fixed at 1.5x ATR
- **Take Profit:** When close > yesterday's close (momentum resumption)
- **Time Exit:** Hold for max 10 days if no momentum signal
- **Trend Exit:** Close if daily close breaks below 250-period reference

#### Backtest Expectations
- Win Rate: 73% (XLP backtest, QuantifiedStrategies)
- Profit Factor: 2.0
- Max Drawdown: 10%
- Average Gain Per Trade: 0.28%
- Total Trades: 316 (meaningful sample)
- Sharpe Ratio: 1.5+

#### Prop Firm Compliance
- Excellent: high win rate, controlled drawdown, systematic rules
- Fewer trades = lower commission costs
- Position sizing based on 0.5% risk with ATR-adjusted stops
- Can be run systematically without discretion

#### Python Pseudocode
```python
def top_down_trend_pullback_strategy(df_daily, config):
    """
    Multi-Timeframe Trend Filter + Pullback Entry
    Backtested on XLP: 73% win rate, PF 2.0, max DD 10%
    """
    # --- Indicators ---
    df = df_daily.copy()
    df['long_term_ma'] = df['close'].shift(config['long_term_period'])
    df['intermediate_ma'] = df['close'].shift(config['intermediate_period'])
    df['three_day_low'] = df['close'].rolling(3).min()
    df['yesterday_close'] = df['close'].shift(1)
    df['atr'] = calculate_atr(df, period=14)
    
    signals = []
    position = None
    
    for i in range(config['long_term_period'] + 1, len(df)):
        # --- Trend Filters ---
        long_term_uptrend = df['close'].iloc[i] > df['long_term_ma'].iloc[i]
        intermediate_uptrend = df['close'].iloc[i] > df['intermediate_ma'].iloc[i]
        is_pullback = df['close'].iloc[i] <= df['three_day_low'].iloc[i-1]
        
        # --- Entry ---
        if position is None:
            if long_term_uptrend and intermediate_uptrend and is_pullback:
                entry = df['close'].iloc[i]
                sl = df['close'].iloc[i] - df['atr'].iloc[i] * config['atr_multiplier']
                
                signals.append({
                    'direction': 'LONG',
                    'entry': entry,
                    'stop_loss': sl,
                    'date': df.index[i]
                })
                position = {'entry': entry, 'sl': sl, 'entry_idx': i}
        
        # --- Exit ---
        elif position is not None:
            # Profit exit: close > yesterday's close
            if df['close'].iloc[i] > df['yesterday_close'].iloc[i]:
                signals.append({
                    'action': 'EXIT',
                    'price': df['close'].iloc[i],
                    'reason': 'momentum_resumption'
                })
                position = None
            
            # Stop loss
            elif df['low'].iloc[i] <= position['sl']:
                signals.append({
                    'action': 'EXIT',
                    'price': position['sl'],
                    'reason': 'stop_loss'
                })
                position = None
            
            # Time exit
            elif i - position['entry_idx'] >= config['max_hold_days']:
                signals.append({
                    'action': 'EXIT',
                    'price': df['close'].iloc[i],
                    'reason': 'time_exit'
                })
                position = None
    
    return signals
```

#### Sources
- [QuantifiedStrategies: Multi-Timeframe Analysis and Strategy](https://quantifiedstrategies.substack.com/p/multi-timeframe-analysis-and-strategy)

---

### Strategy: London Breakout (Asian Range)

**Best For:** GBPUSD, EURUSD, EURGBP
**Timeframe:** M15, M30
**Market Condition:** London open session; after quiet Asian range

#### Entry Rules
1. Identify Asian session range (high and low) during 22:00-07:00 GMT
2. Asian range must be between 10-50 pips (quiet session)
3. London open (07:00 GMT): wait for price to break above Asian high or below Asian low
4. Enter on breakout in breakout direction
5. Confirmation: breakout candle closes beyond Asian range with increased volume

#### Exit Rules
- **Stop Loss:** Most recent pivot high/low within last hour (typically 15-30 pips)
- **Take Profit:** 1.4-1.5x risk (fixed R:R)
- **Time Exit:** Close all positions before NY close (21:00 GMT)
- **Range Filter:** Skip if Asian range < 10 pips (too flat) or > 50 pips (already moved)

#### Backtest Expectations
- Win Rate: 45-55%
- Profit Factor: 1.3-1.6
- Max Drawdown: 15-20%
- Sharpe Ratio: 1.0-1.3
- **Key insight:** Strategy works best during London-NY overlap (highest volatility)
- Must filter: avoid days with major scheduled news

#### Prop Firm Compliance
- Moderate: breakout strategies can have false breakouts
- Daily time filter ensures no overnight risk
- Fixed R:R helps with consistency rules
- Requires volume data for confirmation

#### Python Pseudocode
```python
def london_breakout_strategy(df, config):
    """
    London Breakout Strategy based on Asian Session Range
    """
    signals = []
    
    for date in df.index.normalize().unique():
        day_data = df[df.index.normalize() == date]
        
        # --- Asian Session: 22:00 - 07:00 GMT ---
        asian = day_data.between_time('22:00', '07:00')
        if len(asian) == 0:
            continue
        
        asian_high = asian['high'].max()
        asian_low = asian['low'].min()
        asian_range = asian_high - asian_low
        
        # Filter: range must be 10-50 pips
        if not (config['min_range'] <= asian_range <= config['max_range']):
            continue
        
        # --- London Session: 07:00 - 16:00 GMT ---
        london = day_data.between_time('07:00', '16:00')
        if len(london) == 0:
            continue
        
        breakout_detected = False
        
        for i in range(1, len(london)):
            # Breakout above Asian high
            if (london['close'].iloc[i] > asian_high and
                london['close'].iloc[i-1] <= asian_high):
                
                entry = london['close'].iloc[i]
                sl = london['low'].rolling(4).min().iloc[i]  # Last hour low
                tp = entry + (entry - sl) * config['risk_reward']
                
                if entry - sl > 0:
                    signals.append({
                        'direction': 'LONG',
                        'entry': entry,
                        'stop_loss': sl,
                        'take_profit': tp,
                        'asian_range': asian_range
                    })
                    breakout_detected = True
                    break
            
            # Breakout below Asian low
            elif (london['close'].iloc[i] < asian_low and
                  london['close'].iloc[i-1] >= asian_low):
                
                entry = london['close'].iloc[i]
                sl = london['high'].rolling(4).max().iloc[i]  # Last hour high
                tp = entry - (sl - entry) * config['risk_reward']
                
                if sl - entry > 0:
                    signals.append({
                        'direction': 'SHORT',
                        'entry': entry,
                        'stop_loss': sl,
                        'take_profit': tp,
                        'asian_range': asian_range
                    })
                    breakout_detected = True
                    break
    
    return signals
```

#### Sources
- [InsiderFinance: London Breakout Backtest Results](https://wire.insiderfinance.io/backtest-results-revealed-is-the-london-breakout-strategy-worth-it-0e9df65dd63b)

---

### Strategy: Higher Timeframe Bias + Lower Timeframe Confluence

**Best For:** XAUUSD, EURUSD, NAS100
**Timeframe:** H4 (bias), H1 (setup), M15 (entry)
**Market Condition:** Any — adapts to trending and ranging via HTF context

#### Entry Rules
1. **H4 bias:** Price above/below 50 EMA AND ADX > 25 for trend strength
2. **H1 setup:** Price at HTF support/resistance or order block
3. **M15 entry:** Multiple confluences align:
   - Price action reversal pattern (engulfing, pin bar)
   - Volume spike > 1.5x average
   - RSI oversold (<30) for longs / overbought (>70) for shorts
   - FVG or order block present

#### Exit Rules
- **Stop Loss:** Beyond the M15 structure that created the entry
- **Take Profit:** Next H1/H4 structural level
- **Partial Exit:** 50% at 1:1 R:R, trail remainder
- **Time Exit:** Close before next major session if flat

#### Backtest Expectations
- Win Rate: 60-68% (with all confluences)
- Profit Factor: 2.0-2.8
- Max Drawdown: 8-12%
- Sharpe Ratio: 1.8-2.5
- **Key principle:** More confluences = higher win rate but fewer trades

#### Prop Firm Compliance
- Excellent: confluence trading naturally filters for high-quality setups
- Fewer trades = lower likelihood of consistency rule violations
- Clear multi-timeframe rules can be fully automated
- Best prop firm suitability score of all strategies reviewed

#### Python Pseudocode
```python
def confluence_trading_strategy(df_m15, df_h1, df_h4, config):
    """
    Multi-Timeframe Confluence Trading Strategy
    Requires alignment across H4 bias, H1 setup, and M15 entry
    """
    signals = []
    
    # --- H4 Analysis (Bias) ---
    df_h4['ema50'] = df_h4['close'].ewm(span=50).mean()
    df_h4['adx'] = calculate_adx(df_h4, period=14)
    
    # --- H1 Analysis (Setup) ---
    df_h1['ema50'] = df_h1['close'].ewm(span=50).mean()
    df_h1['atr'] = calculate_atr(df_h1, period=14)
    
    # --- M15 Analysis (Entry) ---
    df_m15['rsi'] = calculate_rsi(df_m15['close'], period=14)
    df_m15['volume_sma'] = df_m15['volume'].rolling(20).mean()
    
    for i in range(50, len(df_m15)):
        current_time = df_m15.index[i]
        
        # Get corresponding H4 and H1 data
        h4_data = df_h4[df_h4.index <= current_time].iloc[-1]
        h1_data = df_h1[df_h1.index <= current_time].iloc[-1]
        
        # --- H4 Bias Check ---
        h4_bullish = df_m15['close'].iloc[i] > h4_data['ema50'] and h4_data['adx'] > 25
        h4_bearish = df_m15['close'].iloc[i] < h4_data['ema50'] and h4_data['adx'] > 25
        
        if not (h4_bullish or h4_bearish):
            continue
        
        # --- H1 Setup Check ---
        h1_support = is_at_support(df_h1, h1_data)
        h1_resistance = is_at_resistance(df_h1, h1_data)
        
        # --- M15 Entry Confluences ---
        volume_spike = df_m15['volume'].iloc[i] > df_m15['volume_sma'].iloc[i] * 1.5
        rsi_oversold = df_m15['rsi'].iloc[i] < 30
        rsi_overbought = df_m15['rsi'].iloc[i] > 70
        
        # --- LONG Entry ---
        if h4_bullish and h1_support and volume_spike and rsi_oversold:
            if is_bullish_reversal_candle(df_m15, i):
                entry = df_m15['close'].iloc[i]
                sl = df_m15['low'].iloc[i] - h1_data['atr'] * 0.3
                tp = find_next_h1_resistance(df_h1, current_time)
                
                confluence_count = sum([h4_bullish, h1_support, volume_spike, rsi_oversold])
                
                if confluence_count >= config['min_confluences']:
                    signals.append({
                        'direction': 'LONG',
                        'entry': entry,
                        'stop_loss': sl,
                        'take_profit': tp,
                        'confluences': confluence_count,
                        'risk_reward': (tp - entry) / (entry - sl)
                    })
        
        # --- SHORT Entry ---
        elif h4_bearish and h1_resistance and volume_spike and rsi_overbought:
            if is_bearish_reversal_candle(df_m15, i):
                entry = df_m15['close'].iloc[i]
                sl = df_m15['high'].iloc[i] + h1_data['atr'] * 0.3
                tp = find_next_h1_support(df_h1, current_time)
                
                confluence_count = sum([h4_bearish, h1_resistance, volume_spike, rsi_overbought])
                
                if confluence_count >= config['min_confluences']:
                    signals.append({
                        'direction': 'SHORT',
                        'entry': entry,
                        'stop_loss': sl,
                        'take_profit': tp,
                        'confluences': confluence_count,
                        'risk_reward': (entry - tp) / (sl - entry)
                    })
    
    return signals
```

---

## Category 4: Mean Reversion vs Trend Following

---

### Strategy: RSI Divergence with Volume Confirmation

**Best For:** EURUSD, XAUUSD, US stocks
**Timeframe:** H4 (best performance from backtests), H1
**Market Condition:** Exhaustion points in trends; major support/resistance

#### Entry Rules
1. Identify regular RSI divergence:
   - Bullish: Price makes lower low, RSI makes higher low
   - Bearish: Price makes higher high, RSI makes lower high
2. Divergence at major support/resistance level (higher timeframe)
3. Volume confirmation: volume increases on reversal candle
4. Wait for candle close to confirm divergence (no anticipatory entries)
5. Optional: CVD divergence adds confluence

#### Exit Rules
- **Stop Loss:** Beyond the divergence extreme (the lower low or higher high)
- **Take Profit:** Next major structural level or fixed 2:1 R:R
- **Time Exit:** Close within 3-5 days if no follow-through
- **Partial Exit:** 50% at 1:1, remainder with trailing stop

#### Backtest Expectations
- **Best Performing Scenario (H1 stocks):**
  - Win Rate: 65.1%
  - Trades: 249 (162 wins, 87 losses)
  - Sharpe Ratio: 5.90
  - Avg Profit: +1.01% per trade
  - Duration: 12 days average
- **EURUSD H4 Performance:**
  - Win Rate: 65%
  - Avg Win: +125 pips
  - Avg Loss: -58 pips
  - Profit Factor: 2.1
  - Max Drawdown: 18%
- **WORST scenario (M1 stocks):** 61.1% WR but -82 Sharpe (noise destroys edge)

#### Prop Firm Compliance
- Good: clear, objective rules
- H4 timeframe = fewer trades, lower commissions, less slippage
- Best on H1-H4 timeframes; avoid M5/M1 (noise)
- Risk 0.5% per trade; 18% max drawdown is manageable

#### Python Pseudocode
```python
def rsi_divergence_strategy(df, config):
    """
    RSI Divergence Strategy with Volume Confirmation
    Best: H4 timeframe. Win rate 65%, Profit Factor 2.1
    """
    # --- Indicators ---
    df['rsi'] = calculate_rsi(df['close'], period=config['rsi_period'])
    df['volume_sma'] = df['volume'].rolling(20).mean()
    df['swing_high'] = find_swing_highs(df['high'], config['swing_lookback'])
    df['swing_low'] = find_swing_lows(df['low'], config['swing_lookback'])
    
    signals = []
    
    for i in range(config['swing_lookback'] * 3, len(df)):
        # --- Bullish Divergence ---
        prev_low_idx = df['swing_low'].iloc[i-config['swing_lookback']:i].idxmin()
        curr_low_idx = df['low'].iloc[i-config['swing_lookback']:i].idxmin()
        
        if (df['low'].loc[curr_low_idx] < df['low'].loc[prev_low_idx] and
            df['rsi'].loc[curr_low_idx] > df['rsi'].loc[prev_low_idx]):
            
            # Volume confirmation
            if df['volume'].iloc[i] > df['volume_sma'].iloc[i]:
                entry = df['close'].iloc[i]
                sl = df['low'].loc[curr_low_idx] - config['sl_buffer']
                tp = find_next_resistance(df, i)
                
                signals.append({
                    'direction': 'LONG',
                    'type': 'bullish_divergence',
                    'entry': entry,
                    'stop_loss': sl,
                    'take_profit': tp,
                    'risk_reward': (tp - entry) / (entry - sl)
                })
        
        # --- Bearish Divergence ---
        prev_high_idx = df['swing_high'].iloc[i-config['swing_lookback']:i].idxmax()
        curr_high_idx = df['high'].iloc[i-config['swing_lookback']:i].idxmax()
        
        if (df['high'].loc[curr_high_idx] > df['high'].loc[prev_high_idx] and
            df['rsi'].loc[curr_high_idx] < df['rsi'].loc[prev_high_idx]):
            
            if df['volume'].iloc[i] > df['volume_sma'].iloc[i]:
                entry = df['close'].iloc[i]
                sl = df['high'].loc[curr_high_idx] + config['sl_buffer']
                tp = find_next_support(df, i)
                
                signals.append({
                    'direction': 'SHORT',
                    'type': 'bearish_divergence',
                    'entry': entry,
                    'stop_loss': sl,
                    'take_profit': tp,
                    'risk_reward': (entry - tp) / (sl - entry)
                })
    
    return signals
```

#### Sources
- [Reddit: RSI Divergence Backtest All Timeframes](https://www.reddit.com/r/Daytrading/comments/1pkn6z5/tested_rsi_divergence_strategy_across_all/)
- [KenyaForexFirm: RSI Divergence Strategy](https://kenyaforexfirm.com/trading-strategies/rsi-divergence-strategy/)
- [QuantifiedStrategies: RSI Trading Strategy](https://www.quantifiedstrategies.com/rsi-trading-strategy/)

---

### Strategy: Bollinger Bands Mean Reversion with Volume Filter

**Best For:** Range-bound markets: EURUSD, XAUUSD, forex majors
**Timeframe:** M15, H1
**Market Condition:** Low ADX (<25), Bollinger Band squeeze expanding, ranging

#### Entry Rules
1. ADX < 25 (confirms ranging market)
2. Bollinger BandWidth below threshold (squeeze detected recently, now expanding)
3. Price touches or penetrates lower band (long) or upper band (short)
4. RSI < 30 (long) or RSI > 70 (short) — extreme reading
5. Volume >= 1.2x average on the touch candle (institutional participation)
6. Candlestick reversal pattern at the band (optional but preferred)

#### Exit Rules
- **Stop Loss:** Beyond the band that was touched
- **Take Profit:** Middle Bollinger Band (20 SMA)
- **Time Exit:** Close within 4-8 candles if target not reached
- **Band Expansion Exit:** Close immediately if BandWidth increases >20%

#### Backtest Expectations
- Win Rate: 55-65% (range-bound conditions only)
- Profit Factor: 1.5-2.0
- Max Drawdown: 10-15%
- Sharpe Ratio: 1.2-1.6
- **Critical:** Performance degrades significantly in trending markets (win rate drops to 35-40%)
- Must use ADX filter to avoid trending markets

#### Prop Firm Compliance
- Moderate: requires market regime detection (ADX filter)
- Mean reversion works best in specific conditions — overtrading in trends = losses
- Clear exit at middle band provides defined targets
- Volume filter reduces false signals

#### Python Pseudocode
```python
def bollinger_mean_reversion_strategy(df, config):
    """
    Bollinger Bands Mean Reversion with Volume & ADX Filter
    Best in ranging markets (ADX < 25)
    """
    # --- Indicators ---
    df['sma20'] = df['close'].rolling(20).mean()
    df['std20'] = df['close'].rolling(20).std()
    df['upper_band'] = df['sma20'] + df['std20'] * config['bb_std']
    df['lower_band'] = df['sma20'] - df['std20'] * config['bb_std']
    df['bandwidth'] = (df['upper_band'] - df['lower_band']) / df['sma20']
    df['rsi'] = calculate_rsi(df['close'], period=14)
    df['adx'] = calculate_adx(df, period=14)
    df['volume_sma'] = df['volume'].rolling(20).mean()
    
    signals = []
    
    for i in range(50, len(df)):
        # Skip trending markets
        if df['adx'].iloc[i] > config['adx_threshold']:
            continue
        
        price = df['close'].iloc[i]
        
        # --- LONG: Price at lower band + RSI oversold + volume ---
        if (price <= df['lower_band'].iloc[i] and
            df['rsi'].iloc[i] < config['rsi_oversold'] and
            df['volume'].iloc[i] >= df['volume_sma'].iloc[i] * config['volume_mult']):
            
            entry = price
            sl = df['lower_band'].iloc[i] - df['std20'].iloc[i] * 0.5
            tp = df['sma20'].iloc[i]  # Target middle band
            
            signals.append({
                'direction': 'LONG',
                'entry': entry,
                'stop_loss': sl,
                'take_profit': tp,
                'risk_reward': (tp - entry) / (entry - sl),
                'adx': df['adx'].iloc[i]
            })
        
        # --- SHORT: Price at upper band + RSI overbought + volume ---
        elif (price >= df['upper_band'].iloc[i] and
              df['rsi'].iloc[i] > config['rsi_overbought'] and
              df['volume'].iloc[i] >= df['volume_sma'].iloc[i] * config['volume_mult']):
            
            entry = price
            sl = df['upper_band'].iloc[i] + df['std20'].iloc[i] * 0.5
            tp = df['sma20'].iloc[i]
            
            signals.append({
                'direction': 'SHORT',
                'entry': entry,
                'stop_loss': sl,
                'take_profit': tp,
                'risk_reward': (entry - tp) / (sl - entry),
                'adx': df['adx'].iloc[i]
            })
    
    return signals
```

#### Sources
- [Kavout: Bollinger Bands Complete Guide](https://www.kavout.com/market-lens/bollinger-bands-a-trader-s-complete-guide-to-mastering-market-volatility)
- [PyQuantLab: Bollinger Momentum Strategy](https://pyquantlab.com/article.php?file=Bollinger%20Momentum%20Strategy%20A%20Comprehensive%20Trading%20Approach.html)

---

### Strategy: ADX Trend Strength Trend Following

**Best For:** ES, NQ, XAUUSD, BTCUSD
**Timeframe:** H1 (optimal from backtests)
**Market Condition:** Strong trending markets (ADX > 25-30)

#### Entry Rules
1. ADX crosses above 25 (trend strength filter)
2. For longs: +DI crosses above -DI
3. For shorts: -DI crosses above +DI
4. Price above 200 EMA (longs) or below 200 EMA (shorts) — trend alignment
5. Entry on next candle open after confirmation

#### Exit Rules
- **Stop Loss:** 1.5x ATR from entry
- **Take Profit:** 3.5x ATR (3.5:1 R:R — optimal from backtests)
- **Trend Exit:** Close when ADX drops below 20 or DI lines cross back
- **Time Exit:** Close after 5 days if target not reached

#### Backtest Expectations
- Initial ADX+DI cross alone: poor results
- **Optimized (ADX > 25 only, no DI cross, 1.5x ATR SL, 3.5:1 R:R):**
  - Good returns
  - Low drawdown
  - Poor win rate but high R:R compensates
- Adding 200 EMA filter: reduces trades, improves drawdown
- RSI filter: NEGATIVE impact (avoid)

#### Prop Firm Compliance
- Moderate: trend following can have extended drawdown periods
- High R:R (3.5:1) means fewer wins needed to be profitable
- 200 EMA filter adds robustness
- Must have patience for trending phases; don't force trades in choppy markets

#### Python Pseudocode
```python
def adx_trend_strategy(df, config):
    """
    ADX Trend Strength Strategy
    Optimized: 1.5x ATR SL, 3.5:1 R:R, 200 EMA filter
    """
    # --- Indicators ---
    df['adx'], df['plus_di'], df['minus_di'] = calculate_dmi(df, period=config['adx_period'])
    df['ema200'] = df['close'].ewm(span=200).mean()
    df['atr'] = calculate_atr(df, period=14)
    
    signals = []
    position = None
    
    for i in range(250, len(df)):
        # --- Entry Logic ---
        if position is None and df['adx'].iloc[i] > config['adx_threshold']:
            # Long: ADX > 25, +DI > -DI, Price > 200 EMA
            if (df['plus_di'].iloc[i] > df['minus_di'].iloc[i] and
                df['close'].iloc[i] > df['ema200'].iloc[i]):
                
                entry = df['open'].iloc[i+1] if i+1 < len(df) else df['close'].iloc[i]
                sl = entry - df['atr'].iloc[i] * config['atr_sl_mult']
                tp = entry + (entry - sl) * config['risk_reward']
                
                signals.append({
                    'direction': 'LONG',
                    'entry': entry,
                    'stop_loss': sl,
                    'take_profit': tp,
                    'adx': df['adx'].iloc[i]
                })
                position = {'direction': 'LONG', 'entry': entry}
            
            # Short: ADX > 25, -DI > +DI, Price < 200 EMA
            elif (df['minus_di'].iloc[i] > df['plus_di'].iloc[i] and
                  df['close'].iloc[i] < df['ema200'].iloc[i]):
                
                entry = df['open'].iloc[i+1] if i+1 < len(df) else df['close'].iloc[i]
                sl = entry + df['atr'].iloc[i] * config['atr_sl_mult']
                tp = entry - (sl - entry) * config['risk_reward']
                
                signals.append({
                    'direction': 'SHORT',
                    'entry': entry,
                    'stop_loss': sl,
                    'take_profit': tp,
                    'adx': df['adx'].iloc[i]
                })
                position = {'direction': 'SHORT', 'entry': entry}
        
        # --- Exit Logic ---
        elif position:
            # ADX weakness exit
            if df['adx'].iloc[i] < 20:
                signals.append({'action': 'EXIT', 'reason': 'adx_weakness'})
                position = None
            # DI crossover exit
            elif (position['direction'] == 'LONG' and
                  df['minus_di'].iloc[i] > df['plus_di'].iloc[i]):
                signals.append({'action': 'EXIT', 'reason': 'di_crossover'})
                position = None
            elif (position['direction'] == 'SHORT' and
                  df['plus_di'].iloc[i] > df['minus_di'].iloc[i]):
                signals.append({'action': 'EXIT', 'reason': 'di_crossover'})
                position = None
    
    return signals
```

#### Sources
- [Reddit: ADX Strategy Backtest Results](https://www.reddit.com/r/algotrading/comments/1irhrcw/backtest_results_for_an_adx_trading_strategy/)
- [QuantifiedStrategies: RSI & ADX Trading Strategies](https://www.quantifiedstrategies.com/rsi-adx-trading-strategy/)

---


## Category 5: Per-Instrument Strategies

---

### Strategy: Gold (XAUUSD) — The Goldmine SMC Strategy

**Best For:** XAUUSD exclusively
**Timeframe:** M15 (entry), H1 (context), H4 (bias)
**Market Condition:** London/NY session volatility; post-Asian range

#### Entry Rules
1. Identify Asian session consolidation range (typically 20-50 pips)
2. Wait for London open liquidity sweep (false breakout of Asian range)
3. Confirm displacement: strong impulsive move creating FVG
4. Enter on FVG retracement during London killzone (2:00-5:00 AM EST)
5. Alternative entry: NY open killzone (8:00-11:00 AM EST)
6. Only take setups aligned with daily demand/supply zones

#### Exit Rules
- **Stop Loss:** Above/below the sweep wick (typically $3-8 on gold)
- **Take Profit:** Opposite liquidity pool or next unfilled imbalance
- **Partial Exit:** 50% at 1:1 R:R, trail remainder to final target
- **Time Exit:** Close before 10:00 PM EST on Fridays (avoid weekend gap)
- **News Exit:** Close all positions 2 minutes before high-impact news

#### Backtest Expectations
- **Real-world backtest (2018-2025, 150 trades):**
  - Win Rate: 82%
  - Average Risk-Reward: 1:2.5
  - Profit Factor: 3.2
  - Best performer: London killzone during volatile periods
- **SMC backtest subset:** Gold outperformed all assets: 64.2% WR, 2.47 PF
- Max Drawdown: 10-15%

#### Prop Firm Compliance
- Excellent for prop firms: gold's volatility creates clear SMC patterns
- Session-based trading naturally limits trade frequency
- 82% win rate with 1:2.5 R:R = very favorable risk profile
- News exit rule critical for prop compliance
- Risk: 0.5% per trade = approximately $5 SL on $5 gold moves

#### Special Considerations for Gold
- Gold is highly sensitive to: Fed rate decisions, NFP, CPI, geopolitical events
- London session (8-11 AM GMT) provides cleanest SMC setups
- NY session overlap (12-4 PM GMT) provides highest volatility
- Asian session: only for range identification, NOT for entries
- Minimum account size: $50,000 recommended for proper position sizing

#### Python Pseudocode
```python
def gold_goldmine_strategy(df_m15, df_h1, config):
    """
    Gold (XAUUSD) Goldmine Strategy - SMC-Based
    Backtest: 82% WR, PF 3.2, Avg R:R 1:2.5
    """
    signals = []
    
    for date in df_m15.index.normalize().unique():
        day_data = df_m15[df_m15.index.normalize() == date]
        
        # --- Asian Range (20:00 - 07:00 EST) ---
        asian = day_data.between_time('20:00', '07:00')
        if len(asian) == 0:
            continue
        
        asian_high = asian['high'].max()
        asian_low = asian['low'].min()
        asian_range = asian_high - asian_low
        
        if asian_range < 3 or asian_range > 15:  # Gold pips in dollars
            continue
        
        # --- London Killzone (02:00 - 05:00 EST) ---
        london = day_data.between_time('02:00', '05:00')
        
        for i in range(1, len(london)):
            candle = london.iloc[i]
            prev_candle = london.iloc[i-1]
            
            # Bullish sweep of Asian low
            if (candle['low'] < asian_low and
                candle['close'] > asian_low and
                is_strong_bullish_candle(candle)):
                
                fvg = detect_fvg(london, i)
                if fvg:
                    signals.append({
                        'direction': 'LONG',
                        'entry_type': 'fvg_retrace',
                        'sweep_low': candle['low'],
                        'fvg_zone': fvg,
                        'target': asian_high,
                        'session': 'London'
                    })
            
            # Bearish sweep of Asian high
            elif (candle['high'] > asian_high and
                  candle['close'] < asian_high and
                  is_strong_bearish_candle(candle)):
                
                fvg = detect_fvg(london, i)
                if fvg:
                    signals.append({
                        'direction': 'SHORT',
                        'entry_type': 'fvg_retrace',
                        'sweep_high': candle['high'],
                        'fvg_zone': fvg,
                        'target': asian_low,
                        'session': 'London'
                    })
    
    return signals
```

#### Sources
- [Medium: How to Backtest the Goldmine Strategy](https://medium.com/coinmonks/how-to-backtest-the-goldmine-strategy-for-consistent-gold-profits-bfa20d0925eb)
- [ACY: Gold Trading Backtesting Guide](https://acy.com/en/market-news/education/ultimate-guide-backtesting-trading-gold-xau-usd-j-o-110321/)

---

### Strategy: NAS100/US30 — Gap Fill with Demand Zone

**Best For:** US30, NAS100, US500 indices
**Timeframe:** M15, H1
**Market Condition:** Post-weekend or overnight gap openings

#### Entry Rules
1. Identify overnight/weekend gap (>0.3% for indices)
2. Wait for price to reach a significant demand zone (prior support)
3. Demand zone must have been tested at least once before
4. Confirm with volume: volume increases as price approaches demand zone
5. Entry on first bullish candle after demand zone touch

#### Exit Rules
- **Stop Loss:** Below the demand zone low
- **Take Profit:** Gap fill level (overnight close)
- **Time Exit:** Close by end of day if gap not filled
- **Partial Exit:** 50% at 50% gap fill, remainder to full fill

#### Backtest Expectations
- Win Rate: 60-70% (most gaps eventually fill)
- Profit Factor: 1.8-2.5
- Max Drawdown: 10-15%
- Sharpe Ratio: 1.3-1.8
- **Caveat:** Gaps caused by major news may not fill quickly

#### Prop Firm Compliance
- Good: clear entry/exit levels, defined time horizon
- Gap fill strategies have known statistics (most gaps fill within 1-3 days)
- Avoid trading gaps >2% (likely news-driven, may not fill)
- Close before major news events

#### Python Pseudocode
```python
def gap_fill_strategy(df, config):
    """
    Index Gap Fill Strategy
    Targets overnight/weekend gap fill at demand/supply zones
    """
    signals = []
    
    for i in range(1, len(df)):
        prev_close = df['close'].iloc[i-1]
        curr_open = df['open'].iloc[i]
        gap_pct = abs(curr_open - prev_close) / prev_close * 100
        
        # Filter: gap must be significant but not extreme
        if not (config['min_gap_pct'] <= gap_pct <= config['max_gap_pct']):
            continue
        
        gap_down = curr_open < prev_close  # Gap down = bullish fill opportunity
        gap_up = curr_open > prev_close    # Gap up = bearish fill opportunity
        
        # Find demand/supply zone
        if gap_down:
            zone = find_nearest_demand_zone(df, i)
            if zone and df['low'].iloc[i] <= zone['top']:
                entry = df['close'].iloc[i]
                sl = zone['bottom'] - config['sl_buffer']
                tp = prev_close  # Gap fill target
                
                signals.append({
                    'direction': 'LONG',
                    'entry': entry,
                    'stop_loss': sl,
                    'take_profit': tp,
                    'gap_pct': gap_pct,
                    'type': 'gap_down_fill'
                })
        
        elif gap_up:
            zone = find_nearest_supply_zone(df, i)
            if zone and df['high'].iloc[i] >= zone['bottom']:
                entry = df['close'].iloc[i]
                sl = zone['top'] + config['sl_buffer']
                tp = prev_close
                
                signals.append({
                    'direction': 'SHORT',
                    'entry': entry,
                    'stop_loss': sl,
                    'take_profit': tp,
                    'gap_pct': gap_pct,
                    'type': 'gap_up_fill'
                })
    
    return signals
```

#### Sources
- [TradingView: How to Trade Gaps on US30/US100/US500](https://www.tradingview.com/chart/US30/0lIX7Qoc-How-to-Trade-Gaps-on-US30-US100-US500-Indexes-Explained/)

---

### Strategy: BTCUSD/ETHUSD — Long-Only Momentum

**Best For:** BTCUSD, ETHUSD, major cryptocurrencies
**Timeframe:** Daily (optimal for crypto)
**Market Condition:** Bull markets; institutional accumulation phases

#### Entry Rules
1. Close > SMA(50) — medium-term uptrend
2. Close > EMA(7) — short-term momentum
3. RSI(2) > ADX(2) — momentum exceeds trend strength
4. All three conditions must be true
5. Entry on next daily open

#### Exit Rules
- **Exit:** RSI(2) < ADX(2) (momentum weakness)
- **Trend Exit:** Close < SMA(50)
- **Stop Loss:** Below EMA(7) or fixed 5% (crypto volatility)
- **Time Exit:** Re-evaluate monthly

#### Backtest Expectations
- **Backtest (2012-2025, BTCUSD, BTCEUR, ETHUSD):**
  - Outperformed buy-and-hold across all pairs
  - Lower drawdown than HODL
  - Robust across all three markets
  - **Note:** Excludes slippage and fees
- Win Rate: 55-60%
- Profit Factor: 2.0+
- Max Drawdown: 25-35% (crypto inherent volatility)

#### Prop Firm Compliance
- Moderate: crypto strategies require wider stops due to volatility
- Daily timeframe = fewer trades = lower commissions
- Long-only avoids short-side restrictions some firms impose
- Must account for crypto weekend trading (some firms close)

#### Python Pseudocode
```python
def crypto_momentum_strategy(df, config):
    """
    Crypto Momentum Strategy (BTCUSD/ETHUSD)
    Long-only, daily timeframe
    Outperforms buy-and-hold with lower drawdown
    """
    # --- Indicators ---
    df['sma50'] = df['close'].rolling(50).mean()
    df['ema7'] = df['close'].ewm(span=7).mean()
    df['rsi2'] = calculate_rsi(df['close'], period=2)
    df['adx2'] = calculate_adx(df, period=2)
    
    signals = []
    position = None
    
    for i in range(50, len(df)):
        # Entry conditions
        condition_1 = df['close'].iloc[i] > df['sma50'].iloc[i]
        condition_2 = df['close'].iloc[i] > df['ema7'].iloc[i]
        condition_3 = df['rsi2'].iloc[i] > df['adx2'].iloc[i]
        
        # --- Entry ---
        if position is None and condition_1 and condition_2 and condition_3:
            entry = df['open'].iloc[i+1] if i+1 < len(df) else df['close'].iloc[i]
            sl = df['ema7'].iloc[i] * 0.95  # 5% below EMA7
            
            signals.append({
                'direction': 'LONG',
                'entry': entry,
                'stop_loss': sl,
                'type': 'momentum_entry'
            })
            position = {'entry': entry, 'sl': sl}
        
        # --- Exit ---
        elif position is not None:
            exit_rsi = df['rsi2'].iloc[i] < df['adx2'].iloc[i]
            exit_trend = df['close'].iloc[i] < df['sma50'].iloc[i]
            
            if exit_rsi or exit_trend:
                exit_price = df['close'].iloc[i]
                signals.append({
                    'action': 'EXIT',
                    'price': exit_price,
                    'reason': 'rsi_adx_cross' if exit_rsi else 'trend_break'
                })
                position = None
    
    return signals
```

#### Sources
- [Reddit: Bitcoin Strategy Outperformed Buy & Hold](https://www.reddit.com/r/algotrading/comments/1lmu1qp/bitcoin_strategy_that_outperformed_buy_hold/)
- [ETH Zurich: Backtesting of Trading Strategies for BTC](https://ethz.ch/content/dam/ethz/special-interest/mtec/chair-of-entrepreneurial-risks-dam/documents/dissertation/master%20thesis/Master_Thesis_Gl%C3%BCcksmann_13June2019.pdf)

---

### Strategy: EURUSD — London Session Manipulation (AMD)

**Best For:** EURUSD exclusively
**Timeframe:** M15 (entry)
**Market Condition:** London session (8 AM - 1 PM CET)

#### Entry Rules
1. Identify if Asian high or low was manipulated during London session
2. Manipulation = price sweeps Asian high/low with reversal
3. Enter on first buy/sell signal on M15 after manipulation
4. SL: Swing protection (10-27 pips max)
5. Skip if SL > 27 pips (place limit order instead)

#### Exit Rules
- **Stop Loss:** 10-27 pips (swing protection)
- **Take Profit:** 2R (fixed)
- **Breakeven:** Move SL to entry when trade reaches 1.5R
- **Max Trades:** 1 entry per day only
- **Friday:** Close all trades at 10 PM CET
- **News:** Close all 2 minutes before major news (NFP, CPI)

#### Backtest Expectations
- **EURUSD Backtest (Jan 2021 - July 2025):**
  - Total: 1,120 trades over 55 months
  - Trades/month: ~20
  - Win Rate: 37%
  - Total Gain: 213.1R
  - Monthly Gain: 3.9R
  - **Key insight:** Low win rate BUT high R:R (2:1) creates positive expectancy

#### Prop Firm Compliance
- Good: fixed 2R target, breakeven rule, strict risk management
- Low win rate (37%) requires psychological discipline
- Single entry per day prevents overtrading
- News exit rule critical for prop compliance
- 27-pip max SL provides clear position sizing

#### Python Pseudocode
```python
def eurusd_london_amd_strategy(df_m15, config):
    """
    EURUSD London Session AMD (Accumulation-Manipulation-Distribution)
    37% WR, 2:1 R:R, 3.9R monthly average
    """
    signals = []
    daily_trade_taken = False
    
    for date in df_m15.index.normalize().unique():
        day_data = df_m15[df_m15.index.normalize() == date]
        daily_trade_taken = False
        
        # Get Asian range
        asian = day_data.between_time('22:00', '08:00')
        if len(asian) == 0:
            continue
        
        asian_high = asian['high'].max()
        asian_low = asian['low'].min()
        
        # London session analysis
        london = day_data.between_time('08:00', '13:00')
        
        for i in range(1, len(london)):
            if daily_trade_taken:
                break
            
            candle = london.iloc[i]
            
            # Detect manipulation of Asian low
            if (candle['low'] < asian_low and
                candle['close'] > asian_low and
                not daily_trade_taken):
                
                sl_pips = candle['low'] - config['sl_buffer']
                entry = candle['close']
                sl_distance = entry - sl_pips
                
                if sl_distance <= 27 * 0.0001:  # 27 pips max
                    tp = entry + sl_distance * 2  # 2R target
                    
                    signals.append({
                        'direction': 'LONG',
                        'entry': entry,
                        'stop_loss': sl_pips,
                        'take_profit': tp,
                        'r_multiple': 2.0,
                        'manipulation': 'asian_low_sweep'
                    })
                    daily_trade_taken = True
            
            # Detect manipulation of Asian high
            elif (candle['high'] > asian_high and
                  candle['close'] < asian_high and
                  not daily_trade_taken):
                
                sl_pips = candle['high'] + config['sl_buffer']
                entry = candle['close']
                sl_distance = sl_pips - entry
                
                if sl_distance <= 27 * 0.0001:
                    tp = entry - sl_distance * 2
                    
                    signals.append({
                        'direction': 'SHORT',
                        'entry': entry,
                        'stop_loss': sl_pips,
                        'take_profit': tp,
                        'r_multiple': 2.0,
                        'manipulation': 'asian_high_sweep'
                    })
                    daily_trade_taken = True
    
    return signals
```

#### Sources
- [ForexFactory: EURUSD London Session Manipulation AMD](https://www.forexfactory.com/thread/1349219-eurusd-london-session-manipulation-amd)

---

## Prop Firm Compliance Framework

### Critical Rules for All Strategies

#### Position Sizing
| Account Size | Conservative (0.25%) | Balanced (0.5%) | Max (1.0%) |
|---|---|---|---|
| $10,000 | $25/trade | $50/trade | $100/trade |
| $50,000 | $125/trade | $250/trade | $500/trade |
| $100,000 | $250/trade | $500/trade | $1,000/trade |
| $200,000 | $500/trade | $1,000/trade | $2,000/trade |

**Recommendation:** Use 0.25-0.5% during challenge phase; 0.5-0.75% after funded.

#### Daily Loss Limit Management
- Set personal daily stop at **50-60% of firm's limit**
- After 2 consecutive losses: stop trading for 30 minutes minimum
- Never risk more than 20% of daily limit on a single trade

| Firm | Daily Limit | Your Stop (60%) | Max Risk/Trade |
|---|---|---|---|
| FTMO | 5% ($5,000 on $100k) | $3,000 | $1,000 (0.5%) |
| TopStep | 3% ($3,000 on $100k) | $1,800 | $500 (0.25%) |
| FundedNext | 5% ($5,000 on $100k) | $3,000 | $1,000 (0.5%) |

#### Prohibited Strategies (Most Prop Firms)
- Martingale (doubling after losses)
- Grid trading
- Latency arbitrage
- High-frequency tick scalping
- Copy trading/mirror trading
- Trading during restricted news events (check firm rules)
- Hedging across accounts (some firms)

#### EA/Bot Compliance
- **Allowed:** Custom code you built yourself
- **Not Allowed:** Rented bots, black box files, mass-distributed EAs
- **Platforms:** MT5, cTrader, TradeLocker (most EA-friendly)
- **Top EA-friendly firms:** FunderPro, FTMO, FundedNext, E8 Markets, AquaFutures

#### Prop Firm Pass Rate Reality
- **Evaluation pass rate:** 5-14% of traders
- **Payout rate:** ~7% of all traders ever receive a payout
- **Long-term funded:** 1-3% remain funded and profitable
- **Average spend:** $800-$4,300 on challenges before first payout
- **Key differentiator:** Risk management, not strategy complexity

#### Consistency Rules
- No single day should account for >30% of total profit (common rule)
- Avoid "home run" trades; aim for steady daily gains
- Target: 0.3-0.5% per day rather than 3-5% in one day
- Track your consistency score: best_day / total_profit < 30%

### Sources
- [ThinkCapital: Prop Firm Drawdown Rules](https://www.thinkcapital.com/prop-firm-drawdown-rules/)
- [ThinkCapital: Position Sizing for Prop Firms](https://www.thinkcapital.com/position-sizing-for-prop-firms/)
- [TradersSecondBrain: Position Sizing for Prop Firms](https://traderssecondbrain.com/guides/position-sizing-for-prop-firms)
- [FundedNow: Prop Firm Risk Management](https://funded.now/guides/prop-firm-risk-management)
- [AtmosFunded: Prop Firm Statistics 2026](https://atmosfunded.com/prop-firm-statistics/)
- [FunderPro: Prop Trading Pass Rates 2025](https://funderpro.com/blog/prop-trading-pass-rates-in-2025-what-the-data-really-shows/)
- [AquaFutures: Best Prop Firms for EA](https://www.aquafutures.io/blogs/best-prop-firms-that-allow-ea)
- [ForTraders: Prohibited Trading Strategies](https://www.fortraders.com/blog/prohibited-trading-strategies-in-prop-trading)

---

## Strategy Suitability Scores

### Scoring Criteria (1-10)
- **Win Rate Potential:** Expected backtested win rate
- **Prop Firm Fit:** Compliance with drawdown, consistency, and risk rules
- **Implementability:** Ease of coding into Python/MQL5
- **Risk Profile:** Drawdown depth and consistency
- **Robustness:** Performance across different market conditions

| Strategy | Win Rate | Prop Fit | Implement | Risk | Robust | OVERALL |
|---|---|---|---|---|---|---|
| Volume Profile POC Mean Reversion | 7 | 8 | 6 | 7 | 6 | **6.8** |
| VWAP Trend Following | 6 | 6 | 8 | 5 | 7 | **6.4** |
| CVD Divergence | 7 | 7 | 5 | 7 | 6 | **6.4** |
| Relative Volume Anomaly | 6 | 6 | 7 | 6 | 5 | **6.0** |
| **Liquidity Sweep + FVG Reclaim** | **8** | **9** | **7** | **8** | **8** | **8.0** |
| BOS + Order Block | 6 | 6 | 6 | 6 | 5 | **5.8** |
| **FVG Mitigation Entry** | **8** | **9** | **8** | **8** | **8** | **8.2** |
| Multi-TF Trend + Pullback | 8 | 9 | 8 | 9 | 8 | **8.4** |
| London Breakout | 5 | 6 | 7 | 5 | 5 | **5.6** |
| **Confluence Trading** | **8** | **9** | **7** | **9** | **9** | **8.4** |
| RSI Divergence (H4) | 7 | 8 | 7 | 7 | 7 | **7.2** |
| BB Mean Reversion | 6 | 6 | 8 | 6 | 5 | **6.2** |
| ADX Trend Following | 6 | 6 | 8 | 6 | 7 | **6.6** |
| **Gold Goldmine (SMC)** | **9** | **9** | **7** | **8** | **9** | **8.4** |
| Index Gap Fill | 7 | 7 | 7 | 7 | 6 | **6.8** |
| Crypto Momentum | 6 | 5 | 8 | 4 | 6 | **5.8** |
| EURUSD London AMD | 5 | 8 | 7 | 7 | 7 | **6.8** |

### Top 5 Strategies for Prop Firm Challenges

1. **Multi-Timeframe Confluence Trading** (8.4/10)
   - Highest robustness score; adapts to all conditions
   - Natural trade filtering = fewer, higher-quality setups
   - Excellent compliance profile

2. **Top-Down Trend + Pullback** (8.4/10)
   - 73% backtested win rate with 10% max drawdown
   - Fully systematic, no discretion required
   - Best for consistent, low-volatility equity curves

3. **Gold Goldmine SMC Strategy** (8.4/10)
   - 82% win rate, 3.2 profit factor on backtest
   - Session-based = natural trade frequency control
   - Clear structural entries/exits

4. **FVG Mitigation Entry** (8.2/10)
   - Objective levels for SL and TP
   - 70-80% of FVGs eventually fill
   - Works across all liquid instruments

5. **Liquidity Sweep + FVG Reclaim** (8.0/10)
   - 61.2% win rate across 2,600 backtested trades
   - High R:R (2R-10R) means fewer trades needed
   - Aligns with institutional flow

### Final Recommendations

**For passing prop firm challenges, prioritize:**
1. Risk management above strategy selection (0.5% risk per trade)
2. Strategies with win rates >55% and profit factors >1.8
3. Timeframe H1 or higher (lower commissions, less noise)
4. Maximum 3-5 trades per day (consistency rule compliance)
5. Personal daily stop at 60% of firm's limit

**The strategy that passes prop firms is the one you can execute flawlessly 100 times in a row.**

---

## MetaAPI / MetaTrader Integration Notes

### Connecting Python to MetaTrader via MetaAPI
```python
# MetaAPI integration pattern
from metaapi_cloud_sdk import MetaApi

async def execute_strategy():
    token = 'YOUR_METAAPI_TOKEN'
    accountId = 'YOUR_ACCOUNT_ID'
    
    api = MetaApi(token)
    account = await api.metatrader_account_api.get_account(accountId)
    connection = account.get_streaming_connection()
    await connection.connect()
    
    # Wait for synchronization
    await connection.wait_synchronized()
    
    # Get price data
    price = await connection.get_symbol_price('XAUUSD')
    
    # Execute trade
    await connection.create_market_buy_order(
        symbol='XAUUSD',
        volume=0.1,
        stopLoss=price['bid'] - 5.0,
        takeProfit=price['bid'] + 10.0
    )
```

### Data Requirements
- **Minimum data:** 5 years of historical data for robust backtesting
- **Timeframe:** M1 data needed for M5 strategies; H1 data sufficient for H4 strategies
- **Volume data:** Required for all volume-based strategies
- **Tick data:** Required for CVD/volume delta strategies

### Performance Optimization
- Use vectorized pandas operations (not loops) for indicator calculation
- Pre-compute all indicators before market open
- Use limit orders where possible (lower slippage)
- Implement connection health monitoring
- Add error handling and reconnection logic

---

*Document compiled from 20+ web searches, academic papers, backtest results, and prop firm statistics. All strategies require independent backtesting before live deployment. Past performance does not guarantee future results.*

*Last updated: 2025*
