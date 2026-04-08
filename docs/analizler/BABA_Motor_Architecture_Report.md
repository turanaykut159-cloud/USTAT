# BABA Motor Architecture - ÜSTAT V5.9 Complete Analysis

## Executive Summary

BABA (Beşiktaş Autonomous Binary Algorithm) is a comprehensive risk management engine for the ÜSTAT V5.9 trading platform. It operates as the system's safety layer, responsible for regime detection, position sizing, multi-layered loss management, correlation control, and kill-switch mechanisms. BABA processes market data every 10 seconds in 3032 lines of Python code and maintains multiple levels of protection against market anomalies and trading losses.

---

## 1. CORE ARCHITECTURE

### 1.1 Main File Location
```
/sessions/inspiring-kind-archimedes/mnt/USTAT/engine/baba.py
```

### 1.2 BABA Class Initialization
The `Baba` class is initialized with:
- **Config**: System configuration object
- **Database**: Persistent storage for risk state and events
- **MT5Bridge**: Connection to MetaTrader 5 terminal
- **Error Tracker**: Failure logging mechanism

### 1.3 Key Supporting Files
```
/sessions/inspiring-kind-archimedes/mnt/USTAT/engine/models/risk.py      # RiskParams, RiskVerdict, FakeAnalysis
/sessions/inspiring-kind-archimedes/mnt/USTAT/engine/models/regime.py    # RegimeType, Regime, EarlyWarning
/sessions/inspiring-kind-archimedes/mnt/USTAT/config/default.json        # Configuration parameters
```

---

## 2. MARKET REGIME DETECTION (4-Regime System)

### 2.1 Regime Classification Hierarchy
BABA detects market regimes with strict priority ordering:

#### Regime 1: OLAY (Event/Crisis Mode)
**When Triggered:**
- Central Bank (TCMB/FED) decision day between 12:00-15:30 (Turkish time)
- USD/TRY moves >2.0% in any 5-minute period
- Contract expiration in final 2 days (if `EXPIRY_DAYS=0`, this is disabled in v5.9)

**Risk Multiplier:** 0.0 (100% position reduction - no new trades)
**Action:** Activates Kill-Switch Level 2 (system pause)

#### Regime 2: VOLATILE (High Volatility)
**Detection Logic (Priority):**
1. ATR > ATR_mean × 2.5
2. Spread > normal_spread × 4.0 (increased from 3.0 in v14)
3. Price movement > 2.5% in last bar

**Threshold Voting:** Requires ≥40% of symbol votes (increased from 30%)

**Risk Multiplier:** 0.25 (75% position reduction)
**Action:** Blocks new trades, enables trailing-only protection

#### Regime 3: TREND (Strong Directional Move)
**All Conditions Required:**
1. ADX > 25.0 (strength of trend)
2. |EMA_fast(9) - EMA_slow(21)| expanding over time
3. Last 5 bars: 4 of them in same direction

**Risk Multiplier:** 1.0 (normal position sizing)
**Allowed Strategies:** TREND_FOLLOW, BREAKOUT

#### Regime 4: RANGE (Sideways/Consolidation)
**Conditions:**
- ADX < 20.0
- Bollinger Band width < 0.8 × average width
- Narrow price range

**Risk Multiplier:** 0.7 (30% position reduction)
**Allowed Strategies:** MEAN_REVERSION, BREAKOUT

### 2.2 Regime Detection Algorithm (`detect_regime()`)

**Step 1:** Check OLAY conditions (absolute priority)

**Step 2:** Symbol-by-symbol technical voting
- 15 WATCHED_SYMBOLS analyzed independently
- Voting weights by liquidity class: A=3, B=2, C=1
- Calculate ADX, ATR ratio, BB width ratio for each

**Step 3:** Determine winner
```
if VOLATILE_votes / total ≥ 40% → VOLATILE
else → max(TREND, RANGE, VOLATILE) votes
```

**Step 4:** ADX override check (Fix 7)
- If winner=RANGE but avg_ADX > 25 → override to TREND
- Prevents ADX contradiction

**Step 5:** Hysteresis filter (CEO-FAZ1)
- Regime change only confirmed after 2 consecutive cycles with same result
- Prevents ping-pong switching
- Maintains `_confirmed_regime` vs `_pending_regime`

### 2.3 Regime Confidence Score
```
confidence = votes[winner] / total_votes
```
Ranges 0.0-1.0, logged for analysis

---

## 3. POSITION SIZING ENGINE

### 3.1 Core Sizing Formula
```
lot = (equity × risk% × regime_mult) / (ATR × contract_size)
```

**Parameters:**
- `equity`: Current account balance
- `risk%`: Risk per trade (default 1%)
- `regime_mult`: 1.0 (TREND) to 0.0 (OLAY)
- `ATR`: 14-period Average True Range
- `contract_size`: 100.0 (default for futures)

### 3.2 Hard Caps & Protections
1. **Risk Cap Hard Limit:** min(risk_per_trade, 2.0%)
   - Single trade cannot risk more than 2% (hard coded constant)

2. **Lot Rounding:**
   - Rounds down to volume_step
   - Minimum = volume_min (usually 1 lot)
   - Maximum = max_position_size (config limit)

3. **Graduated Lot Schedule** (consecutive loss penalty)
   - 0 losses: normal lot
   - 1 loss: lot × 0.75
   - 2 losses: lot × 0.50
   - 3+ losses: lot = 0 (cooldown enforced)

4. **Weekly Loss Halving**
   - If weekly loss ≥ 4% → all new positions: lot × 0.5

### 3.3 Floor Logic (Fix 2)
If rounding produces 0 but base_lot ≥ vol_min × 0.5:
```
Apply vol_min (minimum 1 lot)
```
Ensures small position is opened if calculation warrants it

### 3.4 Output Format
Returns rounded lot size (2 decimal places)
```
calc_position_size(symbol, risk_params, atr, equity) → float
```

---

## 4. MULTI-LAYERED LOSS MANAGEMENT

### 4.1 Loss Hierarchy & Triggers

#### Tier 1: Daily Loss (Intraday)
**Threshold:** 1.8% of daily start equity
**Trigger:** Calculated from `daily_pnl` snapshot
**Action:** Kill-Switch L2 → system pause
**Reset:** Daily at 09:30 (new day)

#### Tier 2: Weekly Loss
**Threshold:** 4.0% of weekly start equity
**Reset:** Every Monday at 09:30
**Action:** Lot multiplier → 0.5 (half positions for rest of week)

#### Tier 3: Monthly Loss
**Threshold:** 7.0% of month start equity
**Reset:** Monthly on 1st at 09:30
**Action:** Kill-Switch L2 → system pause, manual approval required

#### Tier 4: Hard Drawdown (Peak-to-Trough)
**Soft Limit:** 10.0% from peak equity
**Hard Limit:** 15.0% from peak equity
**Action:** Kill-Switch L3 → complete position closure

#### Tier 5: Floating Loss (Open Position Loss)
**Threshold:** 2.0% of account (OĞUL positions only)
**Master Floating:** 5.0% across all motors
**Action:**
- OĞUL: Blocks new trades
- Master: Kill-Switch L2

### 4.2 Reset Mechanics

**Daily Reset** (`_reset_daily()`)
```
Triggers: date change from previous
Updates: daily_reset_equity, daily_reset_date
Clears: daily_trade_count
```

**Weekly Reset** (`_reset_weekly()`)
```
Triggers: new week (Monday detection)
Updates: weekly_reset_week
Clears: weekly_loss_halved flag
```

**Monthly Reset** (`_reset_monthly()`)
```
Triggers: new month
Updates: monthly_reset_month
Clears: monthly_paused flag
```

### 4.3 Risk State Persistence
BABA saves state to database (JSON serialized):
```
{
  "daily_reset_date": "2026-04-02",
  "daily_trade_count": 2,
  "daily_auto_trade_count": 2,
  "daily_manual_trade_count": 0,
  "weekly_loss_halved": false,
  "consecutive_losses": 0,
  "cooldown_until": null,
  ...
}
```

On restart, `_restore_risk_state()` reloads from DB with type conversion.

---

## 5. EARLY WARNING SYSTEM (Real-Time Anomaly Detection)

### 5.1 Four Warning Types

#### Warning 1: Spread Spike
**Detection:** Current spread > average_spread × threshold
**Thresholds by Liquidity:**
- Class A: 3.0×
- Class B: 4.0×
- Class C: 5.0×

**Severity:** WARNING (normal) or CRITICAL (>threshold × 1.5)

#### Warning 2: Price Shock
**Detection:** |close[-1] - close[-2]| / close[-2] > threshold%
**Thresholds by Liquidity:**
- Class A: 1.5%
- Class B: 2.0%
- Class C: 3.0%

**Data:** M1 bars (1-minute)

#### Warning 3: Volume Spike
**Detection:** 5-min volume > 20-bar average × 5.0
**Cooldown:** 10 seconds per symbol (prevents duplicate alerts)

#### Warning 4: USD/TRY Shock
**Detection:** USD/TRY moves > 0.5% in 5-minute candle
**Global Impact:** Affects all 15 watched symbols

### 5.2 Spread & USD/TRY History Buffers
- **Ring buffers** (deque, thread-safe append)
- **Size:** Dynamically calculated = max(10, 300 / cycle_interval)
  - Default: 300 / 10 = 30 candles
- **Update:** Every cycle in `_update_spread_history()` and `_update_usdtry_history()`

### 5.3 Kill-Switch Trigger from Warnings
```python
for warning in active_warnings:
    if warning.severity == "CRITICAL" and warning.symbol != "USDTRY":
        activate_kill_switch_l1(symbol, reason)
```

---

## 6. CORRELATION & CONCENTRATION LIMITS

### 6.1 Three-Layer Correlation Check
Called before each new trade to validate `check_correlation_limits()`:

#### Layer 1: Same Direction Limit
```
Max 3 open positions in same direction (BUY or SELL)
```

#### Layer 2: Sector Concentration
```
Max 2 same-sector positions in same direction
```
**Sectors Defined:**
- Havacılık: F_THYAO, F_PGSUS
- Bankacılık: F_AKBNK, F_HALKB
- Teknoloji: F_ASELS, F_TCELL
- Kimya: F_GUBRF
- Gayrimenkul: F_EKGYO
- Perakende: F_SOKM
- Holding: F_TKFEN
- Sanayi: F_OYAKC, F_BRSAN
- Enerji: F_AKSEN, F_ASTOR
- Diğer: F_KONTR

#### Layer 3: Index Weight Score
```
score = abs(sum(lot_i × xu030_weight_i × sign_i))
Max allowed: 0.25
```

**XU030 Weights (Approximate, quarterly updated):**
```
F_THYAO: 12%,  F_AKBNK: 8%,   F_ASELS: 7%,
F_TCELL: 5%,   F_HALKB: 3%,   F_PGSUS: 4%,
F_GUBRF: 2%,   F_EKGYO: 3%,   F_SOKM: 2%,
F_TKFEN: 3%,   F_OYAKC: 1%,   F_BRSAN: 1%,
F_AKSEN: 2%,   F_ASTOR: 1%,   F_KONTR: 0%
```

### 6.2 Trade Rejection Verdicts
If any layer violated → `RiskVerdict.can_trade = False`

---

## 7. CONSECUTIVE LOSS & COOLDOWN MECHANISM

### 7.1 Consecutive Loss Tracking
- **Threshold:** 3 losing trades in a row
- **Detection:** `_update_consecutive_losses()` checks last N trade results
- **Penalty:** Graduated lot reduction (75% → 50% → stop)

### 7.2 Cooldown Activation
When consecutive_loss ≥ limit:
```
_start_cooldown(risk_params)
- cooldown_until = now + 2 hours (config: cooldown_hours)
- Save to risk_state
- Activate Kill-Switch L2 "consecutive_loss"
```

**Duration:** 2-4 hours (configurable, default 2h in v14)

### 7.3 Cooldown Check
```python
if _is_in_cooldown():
    verdict.can_trade = False
    return "Cooldown active"
```

---

## 8. KILL-SWITCH SYSTEM (3 Levels)

### 8.1 Kill-Switch Levels

**Level 0: None**
- Normal operation
- Risk checks applied

**Level 1: Contract Kill** (L1)
- `_killed_symbols` set tracks disabled symbols
- Specific contract(s) blocked
- Triggered by: CRITICAL early warnings (spread/price/volume spikes)
- Other symbols still tradeable
- No automatic recovery

**Level 2: System Pause** (L2)
- `can_trade = False` (system-wide)
- `lot_multiplier = 0.0` (position reduction)
- `risk_multiplier` varies by trigger:
  - "olay_regime" → 0.15 (very small positions allowed)
  - "daily_loss" / "consecutive_loss" → 0.0 (full stop)
  - Other → 0.25 (restricted)
- Triggered by:
  - OLAY regime detection
  - Daily loss threshold exceeded
  - Weekly loss → partial (lot halving)
  - Consecutive loss cooldown
  - Master floating loss (>5%)
- Auto-recovery: OLAY regime ends → auto-clear if "olay_regime" reason

**Level 3: Complete Closure** (L3)
- `can_trade = False`
- `lot_multiplier = 0.0`
- `risk_multiplier = 0.0` (absolute stop)
- ALL OPEN POSITIONS CLOSED
- Requires manual acknowledgment: `acknowledge_kill_switch(user)`
- Triggered by:
  - Hard drawdown >15%
  - Max drawdown >10%
  - Manual operator request
- Locked positions stored in `_last_l3_failed_tickets` for manual review

### 8.2 Kill-Switch State Variables
```python
_kill_switch_level: int = 0  # Current level
_kill_switch_details: dict   # {reason, message, timestamp}
_killed_symbols: set[str]    # L1-blocked symbols
_ks_lock: threading.Lock()   # Atomic state transitions
_last_l3_failed_tickets: list[int]  # Positions that failed to close
_unprotected_positions: list[dict]  # Positions missing SL/TP
```

### 8.3 Kill-Switch Clear
Manual or automatic clearing:
```
_clear_kill_switch(reason: str)
- Set _kill_switch_level = 0
- Clear _kill_switch_details
- Clear _killed_symbols (only if reason demands)
- Log to DB
```

---

## 9. FAKE SIGNAL DETECTION (4-Layer Analysis)

### 9.1 Fake Signal Score System
**Threshold:** Score ≥ 6/6 (maximum) → AUTO-CLOSE position
**Warning:** Score = 5/5 → log warning, monitor

Each layer has weight:
- Volume: weight 1
- Spread: weight 2
- Multi-TF: weight 1
- Momentum: weight 2
- **Total max:** 6 points

### 9.2 Layer 1: Volume Analysis
**Check:** `volume_ratio = current_vol / 20-bar_avg < 0.7`
**Interpretation:** No volume confirmation
**Score:** 1 (if triggered)

### 9.3 Layer 2: Spread Analysis
**Check:** `spread / avg > threshold`
**Thresholds:**
- Class A: > 2.5×
- Class B: > 3.5×
- Class C: > 5.0×
**Interpretation:** Liquidity evaporated
**Score:** 2 (if triggered)

### 9.4 Layer 3: Multi-Timeframe Analysis
**Check:** Direction agreement across M5, M15, H1
- EMA-9 crossover logic: `close > ema9 → BUY`
- Require ≥ 2 of 3 timeframes agreeing with position
**Interpretation:** Higher timeframes disagree
**Score:** 1 (if < 2/3 agree)

### 9.5 Layer 4: Momentum Divergence
**Checks:**
1. RSI > 80 (overbought) OR RSI < 20 (oversold)
2. MACD histogram divergence:
   - BUY position: histogram < 0 (bearish)
   - SELL position: histogram > 0 (bullish)

**Interpretation:** Extreme momentum + trend disagreement
**Score:** 2 (if both conditions met)

### 9.6 Auto-Close Logic
```python
if total_score ≥ 6:
    close_position(ticket)
    log FAKE_SIGNAL event
    update trade record with fake_score
```

**Exclusion:** Manual positions (manuel_motor.active_trades) are immune

### 9.7 Analysis Frequency
- Called every 3 cycles (30 seconds) = `_cycle_count % 3 == 0`

---

## 10. RISK CHECK ENTRY POINT: `check_risk_limits()`

### 10.1 Complete Verdict Flow

**Input:** RiskParams object

**Output:** RiskVerdict with:
- `can_trade: bool`
- `lot_multiplier: float` [0.0, 1.0]
- `risk_multiplier: float` [0.0, 1.0]
- `kill_switch_level: int` [0, 1, 2, 3]
- `reason: str` (explanation if blocked)
- `blocked_symbols: list[str]` (L1 killed symbols)

### 10.2 Verdict Decision Tree

```
1. If K3 active → can_trade=False, lot=0.0, reason="K3 active"
2. If K2 active → can_trade=False, lot=0.0, risk_mult=0.15-0.25
3. If unprotected_positions exist → can_trade=False
4. If monthly_paused → can_trade=False
5. If daily_loss_exceeded → activate_k2, can_trade=False
6. If hard_drawdown → activate_k3, can_trade=False
7. If max_drawdown → activate_k3, can_trade=False
8. If monthly_loss → monthly_paused=True, activate_k2, can_trade=False
9. If weekly_loss → lot_multiplier=0.5
10. If floating_loss (OĞUL) → can_trade=False
11. If master_floating (all) → activate_k2, can_trade=False
12. If daily_trades ≥ limit → can_trade=False
13. If total_positions ≥ max_total → can_trade=False
14. If margin_reserve < 20% → can_trade=False
15. If in_cooldown → can_trade=False
16. If consecutive_loss ≥ limit → activate_k2, can_trade=False
17. Else → can_trade=True
```

---

## 11. MAIN CYCLE: `run_cycle()`

### 11.1 Called Every 10 Seconds
Entry point from engine main loop:
```
run_cycle(pipeline: DataPipeline | None) → Regime
```

### 11.2 Execution Sequence

1. **Increment cycle counter** (for 3-cycle fake analysis)

2. **Process ÜSTAT notifications** (risk param changes logged)

3. **Update history buffers** (if pipeline provided)
   - `_update_spread_history(pipeline)`
   - `_update_usdtry_history()`

4. **Detect market regime**
   - Call `detect_regime()`
   - Apply hysteresis filtering
   - Store in `self.current_regime`

5. **Check early warnings**
   - Call `check_early_warnings()`
   - Store in `self.active_warnings`

6. **Fake signal analysis** (every 3 cycles = 30 seconds)
   - Call `analyze_fake_signals()` if `_cycle_count % 3 == 0`
   - Auto-close if score ≥ 6

7. **Period resets**
   - Call `_check_period_resets()`
   - Reset daily/weekly/monthly if needed

8. **Kill-switch triggers**
   - Call `_evaluate_kill_switch_triggers()`
   - Activate L1 for CRITICAL warnings
   - Activate L2 for OLAY regime

9. **Persist risk state** to DB

10. **Return detected regime**

### 11.3 Cycle Timing
- Interval: 10 seconds (configurable: `engine.cycle_interval`)
- Fake analysis: every 3 cycles (30 seconds)
- Total overhead per cycle: <100ms (non-blocking)

---

## 12. INTEGRATION WITH OTHER COMPONENTS

### 12.1 Integration Points

**BABA → OĞUL (Automated Motor)**
- `calculate_position_size()`: Used for lot calculation
- `check_risk_limits()`: Must pass before trade
- `check_correlation_limits()`: Validates symbol/direction
- `current_regime`: Strategy selection filter
- `active_warnings`: Position close triggers

**BABA → Manuel Motor (Manual Trade Manager)**
- `increment_daily_trade_count("manual")`: Tracks manual trades
- Immune to fake signal analysis
- Immune to regime restrictions (but risk limits apply)

**BABA → Main Engine**
- `run_cycle()`: Called by event loop
- `set_news_bridge()`: Receives news event triggers
- Receives MT5Bridge reference for position/account queries

**BABA ← Data Pipeline**
- M5 bars for regime detection
- M1 bars for price shocks
- M15, H1 for multi-TF analysis
- Spread/volume from MT5 tick data

### 12.2 Data Flow
```
MT5Bridge (positions, ticks, account)
    ↓
DataPipeline (historical bars)
    ↓
run_cycle() [every 10s]
    ├→ detect_regime() → Regime
    ├→ check_early_warnings() → list[EarlyWarning]
    ├→ analyze_fake_signals() → list[FakeAnalysis]
    └→ _evaluate_kill_switch_triggers() → Kill-Switch L1/L2

check_risk_limits(risk_params) → RiskVerdict
    ↓
OĞUL / ManuelMotor (uses verdict)
```

---

## 13. CONFIGURATION PARAMETERS

**File:** `/sessions/inspiring-kind-archimedes/mnt/USTAT/config/default.json`

### 13.1 Risk Section
```json
{
  "risk": {
    "max_daily_loss_pct": 0.018,          // 1.8%
    "max_total_drawdown_pct": 0.1,        // 10%
    "hard_drawdown_pct": 0.15,            // 15%
    "risk_per_trade_pct": 0.01,           // 1%
    "max_weekly_loss_pct": 0.04,          // 4%
    "max_monthly_loss_pct": 0.07,         // 7%
    "max_floating_loss_pct": 0.015,       // 1.5%
    "max_daily_trades": 5,                // Auto trades limit
    "consecutive_loss_limit": 3,          // Cooldown trigger
    "cooldown_hours": 4,                  // Recovery time
    "master_floating_loss_pct": 0.05,     // 5% all motors
    "baseline_date": "2026-04-01 00:01"   // Loss calc start
  }
}
```

### 13.2 Engine Section
```json
{
  "engine": {
    "cycle_interval": 10,              // Seconds
    "margin_reserve_pct": 0.2,         // 20% free margin
    "max_total_positions": 8,          // All motors combined
    "paper_mode": false                // Live/backtest
  }
}
```

### 13.3 Indicators Section
```json
{
  "indicators": {
    "ema_fast": 9,
    "ema_slow": 21,
    "adx_period": 14,
    "atr_period": 14,
    "bb_period": 20,
    "bb_std": 2.0
  }
}
```

---

## 14. WATCHED SYMBOLS (15 Contracts)

**Default Symbols:**
```
F_THYAO   (Turkish Airlines - Havacılık)
F_AKBNK   (Akbank - Bankacılık)
F_ASELS   (Aselsan - Teknoloji)
F_TCELL   (Turkcell - Teknoloji)
F_HALKB   (Halkbank - Bankacılık)
F_PGSUS   (Pegasus - Havacılık)
F_GUBRF   (Gubretas - Kimya)
F_EKGYO   (Emlak Konut - Gayrimenkul)
F_SOKM    (Soktas - Perakende)
F_TKFEN   (Tekfen - Holding)
F_OYAKC   (Oyak Çimento - Sanayi)
F_BRSAN   (Borsan - Sanayi)
F_AKSEN   (Aksen - Enerji)
F_ASTOR   (Astor - Enerji)
F_KONTR   (Kontraktor)
```

---

## 15. CENTRAL BANK & HOLIDAY CALENDARS

### 15.1 TCMB PPK Dates
- 2025: Jan 23, Feb 20, Mar 20, Apr 17, May 22, Jun 19, Jul 24, Aug 21, Sep 18, Oct 23, Nov 20, Dec 25
- 2026: Monthly (estimated 3rd Thursday of each month)

### 15.2 FED FOMC Dates
- 2025: Jan 29, Mar 19, May 7, Jun 18, Jul 30, Sep 17, Oct 29, Dec 10
- 2026: Jan 28, Mar 18, May 6, Jun 17, Jul 29, Sep 16, Oct 28, Dec 16

### 15.3 VİOP Expiry Dates
- Monthly last business day
- Special handling: Bayram half-days → vade moves to prior business day
- Example: May 2026 = 25th (Mon) due to Kurban Bayramı arefe on 26th

**Validation:** `validate_expiry_dates()` checks for weekends/holidays

---

## 16. THREADING & ATOMICITY

### 16.1 Thread-Safe Structures

**Ring Buffers (deque):**
- `_spread_history[symbol]: deque[float]` - atomic append/pop
- `_usdtry_history: deque[float]` - atomic append/pop
- Auto-truncates to max length

**Locks:**
- `_ks_lock`: Kill-switch state transitions (prevents race)
- `_rs_lock`: Risk-state read/write serialization

### 16.2 Fail-Safe Mode (Anayasa 4.9)
If MT5 query fails during risk check:
```
except Exception:
    verdict.can_trade = False
    reason = "MT5 query failed (fail-safe)"
    return verdict
```
Defaults to SAFE (no trading) on any exception

---

## 17. LOGGING & PERSISTENCE

### 17.1 Event Types Logged to Database

- **REGIME_CHANGE**: New regime detected
- **EARLY_WARNING**: Spread/price/volume/USD-TRY spike
- **FAKE_SIGNAL**: 4-layer analysis score ≥6
- **DRAWDOWN_LIMIT**: Loss threshold triggered
- **KILL_SWITCH_L1/L2/L3**: Level activation/clear
- **USTAT_NOTIFICATION**: Risk param changes from UI

### 17.2 Log Levels
- **ERROR**: Kill-switch L3, failed position closes, MT5 errors
- **WARNING**: Early warnings, fake signals, cooldowns
- **INFO**: Regime changes, resets, permission grants
- **DEBUG**: Position sizing details, hysteresis, fake analysis details

---

## 18. DATA STRUCTURES

### 18.1 Regime Dataclass
```python
@dataclass
class Regime:
    regime_type: RegimeType        # TREND, RANGE, VOLATILE, OLAY
    confidence: float              # 0.0-1.0
    risk_multiplier: float         # 0.0-1.0
    adx_value: float               # Last ADX
    atr_ratio: float               # ATR / mean
    bb_width_ratio: float          # BB width / mean
    details: dict                  # Per-symbol breakdown
    allowed_strategies: list[StrategyType]
```

### 18.2 RiskVerdict Dataclass
```python
@dataclass
class RiskVerdict:
    can_trade: bool                # Trading permission
    lot_multiplier: float          # 0.0-1.0
    risk_multiplier: float         # 0.0-1.0 (v5.9.2+)
    reason: str                    # Block explanation
    kill_switch_level: int         # 0-3
    blocked_symbols: list[str]     # L1 kills
    details: dict                  # Extra info
```

### 18.3 FakeAnalysis Dataclass
```python
@dataclass
class FakeAnalysis:
    symbol: str
    direction: str                 # BUY / SELL
    ticket: int                    # MT5 position ID
    volume_layer: FakeLayerResult  # Score 0-1
    spread_layer: FakeLayerResult  # Score 0-2
    multi_tf_layer: FakeLayerResult # Score 0-1
    momentum_layer: FakeLayerResult # Score 0-2
    # total_score property: max 6
```

---

## 19. CRITICAL CONSTANTS (Hard-Coded)

| Constant | Value | Purpose |
|----------|-------|---------|
| ADX_TREND_THRESHOLD | 25.0 | TREND regime minimum |
| ADX_RANGE_THRESHOLD | 20.0 | RANGE regime maximum |
| ATR_VOLATILE_MULT | 2.5 | VOLATILE threshold (v14) |
| SPREAD_VOLATILE_MULT | 4.0 | Spread VOLATILE (v14) |
| PRICE_MOVE_PCT | 2.5 | Price shock VOLATILE % |
| VOLATILE_VOTE_PCT | 0.40 | VOLATILE win threshold % |
| EMA_FAST | 9 | Fast EMA period |
| EMA_SLOW | 21 | Slow EMA period |
| FAKE_SCORE_THRESHOLD | 6 | Auto-close fake signal |
| FAKE_VOLUME_RATIO_MIN | 0.7 | Volume ratio fake check |
| KILL_SWITCH_L1 | 1 | Contract kill level |
| KILL_SWITCH_L2 | 2 | System pause level |
| KILL_SWITCH_L3 | 3 | Complete closure level |

---

## 20. TYPICAL WORKFLOW EXAMPLE

### Scenario: Morning Trading Session (TREND Regime)

```
09:45 - Market opens
  run_cycle() #1
  ├→ detect_regime() → TREND (ADX=28, confidence=0.85)
  ├→ risk_multiplier = 1.0
  ├→ check_early_warnings() → [empty]
  └→ active_warnings = []

09:55
  run_cycle() #2
  └→ Regime stable

10:05 (cycle #3 - fake analysis triggered)
  run_cycle() #3
  ├→ Fake analysis on OĞUL positions
  ├→ Position F_THYAO: score=2 (normal)
  └→ No closes

10:15 - Signal generated (TREND_FOLLOW)
  OĞUL requests trade:
  ├→ Symbol: F_AKBNK, Direction: BUY
  ├→ Risk check: check_risk_limits() → RiskVerdict(can_trade=True)
  ├→ Correlation: check_correlation_limits() → OK
  ├→ Sizing: calculate_position_size() → 2.5 lots
  ├→ Daily trades: 1/5 remaining
  └→ Order opened

10:25 - Spread spike detected
  run_cycle() #4
  ├→ check_early_warnings() →
  │  EarlyWarning(SPREAD_SPIKE, F_AKBNK, 5.2×, CRITICAL)
  ├→ activate_kill_switch_l1(F_AKBNK, "Spread spike 5.2×")
  └→ F_AKBNK blocked

10:35 - Drawdown check (cycle #5)
  run_cycle() #5
  ├→ Daily PnL: -1.2% (within -1.8% limit)
  ├→ RiskVerdict: can_trade=True, reason=""
  └→ Continue

12:00 - Central Bank announcement time
  run_cycle() #13 (OLAY block window)
  ├→ detect_regime() → OLAY (Central Bank date)
  ├→ risk_multiplier = 0.0
  ├→ _activate_kill_switch(L2, "olay_regime", "...")
  └→ No new trades until 15:30

15:35 - OLAY window ends
  run_cycle() #50+
  ├→ detect_regime() → TREND (back to normal)
  ├→ _clear_kill_switch("OLAY ended")
  └→ Resume normal trading

17:45 - Market close
  Session ends
```

---

## 21. VERSION HISTORY (Key Changes)

### v13.0 (Current - Referenced in Code)
- Added 4-layer fake signal analysis
- Refined OLAY window timing (12:00-15:30)
- Added master floating loss (5%)
- V14 parameters integrated

### v5.9.2 (Recent Fixes)
- Fixed L3 → K3 risk_multiplier = 0.0 (was 1.0)
- Graduated lot schedule fixes
- Margin reserve (20%) double-layered checks
- Unprotected position tracking (CEO-FAZ1)

### v5.8 (CEO-FAZ Initiatives)
- Regime hysteresis (2-cycle confirmation)
- Margin reserve percentage checks
- Unprotected positions list

### v5.7.1
- News bridge integration
- Floating loss per-motor (OĞUL specific)
- ÜSTAT notification queue

---

## 22. SUMMARY: BABA ARCHITECTURE

BABA operates as ÜSTAT V5.9's central risk authority through:

1. **10-second cycle** monitoring 15 liquid futures contracts
2. **4-regime classification** with strict detection hierarchy
3. **Dynamic position sizing** with hard caps and graduated penalties
4. **5-tier loss management** from daily to peak-drawdown
5. **Real-time anomaly detection** (spread, price, volume, FX shocks)
6. **Correlation enforcement** across 3 dimensions
7. **4-layer fake signal detection** with auto-close at score 6
8. **3-level kill-switch** from symbol-level to full system lockdown
9. **Thread-safe state** with DB persistence and restart recovery
10. **Integrated with OĞUL, ManuelMotor, DataPipeline, MT5Bridge**

**Core Design Principle:** Defense in depth with fail-safe defaults. When in doubt, BABA says "no."

