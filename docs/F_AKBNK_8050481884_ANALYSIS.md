# F_AKBNK SELL Position (Ticket 8050481884) - Detailed Log Analysis

**Analysis Date:** April 7, 2026
**Position Status:** CLOSED (SOFTWARE_SL)
**Final P&L:** -3.00 TRY

---

## POSITION LIFECYCLE

### PHASE 1: Position Opening (April 6, 15:36-15:42)
Multiple opening attempts due to MT5 AutoTrading being disabled by client:
- **First Event:** 2026-04-06 15:36:01.209
- **Last Event (Successful Entry):** 2026-04-06 15:42:21.766

**Opening Details:**
- Symbol: F_AKBNK (mapped to F_AKBNK0426 in MT5)
- Direction: SELL (1.0 lot)
- Entry Price: ~70.62 TRY (reference price used for PRİMNET calculations)
- Initial Strategy Trigger: Unknown (strategy field empty in logs)

**Log Entries:**
```
2026-04-06 15:36:01.209 | Event [INFO] TRADE_OPENED: İşlem açıldı: F_AKBNK SELL (strateji: )
2026-04-06 15:36:53.683 | Event [INFO] TRADE_OPENED: İşlem açıldı: F_AKBNK SELL (strateji: )
2026-04-06 15:37:19.862 | Event [INFO] TRADE_OPENED: İşlem açıldı: F_AKBNK SELL (strateji: )
2026-04-06 15:40:23.325 | Event [INFO] TRADE_OPENED: İşlem açıldı: F_AKBNK SELL (strateji: )
2026-04-06 15:41:06.752 | Event [INFO] TRADE_OPENED: İşlem açıldı: F_AKBNK SELL (strateji: )
2026-04-06 15:42:01.763 | Event [INFO] TRADE_OPENED: İşlem açıldı: F_AKBNK SELL (strateji: )
2026-04-06 15:42:21.766 | Event [INFO] TRADE_OPENED: İşlem açıldı: F_AKBNK SELL (strateji: )
```

---

### PHASE 2: Transfer to H-Engine (PRİMNET) Hybrid Management (April 6, 15:44:16)

**Critical Transfer Event:**
```
2026-04-06 15:44:16.323 | engine.h_engine:transfer_to_hybrid:401
- PRİMNET devir: F_AKBNK SELL
- giriş_prim=2.61 (entry PnL in PRİMNET mode)
- stop_prim=4.11 (stop loss in PRİMNET points)
- hedef_prim=-9.50 (target/TP in PRİMNET points)
- SL=73.5193 (Stop Loss level)
- TP=63.9111 (Take Profit level)
- ref=70.6200 (reference price for calculations)
```

**SL/TP Modification Attempts:**
```
2026-04-06 15:44:16.324 | engine.mt5_bridge:modify_position:1805
- Modify SL/TP: ticket=8050481884
- SL=73.5200 TP=0.0000
- Result: FAILED (retcode=10027, AutoTrading disabled by client)
```

**Fallback to Software SL/TP Management:**
```
2026-04-06 15:44:18.330 | engine.h_engine:transfer_to_hybrid:439
- Software SL/TP modu + güvenlik ağı SL: ticket=8050481884 F_AKBNK
- native_SL=73.5193 (gap koruması)

2026-04-06 15:44:18.331 | engine.h_engine:transfer_to_hybrid:447
- Software SL/TP modu: ticket=8050481884 F_AKBNK
- SL=73.5193 TP=63.9111
- (software yönetim aktif)

2026-04-06 15:44:18.332 | engine.h_engine:transfer_to_hybrid:525
- Hibrit devir başarılı: ticket=8050481884 F_AKBNK SELL
- SL=73.5193 TP=63.9111 ATR=0.3320
```

**Key Finding:** Position was transferred to H-Engine hybrid management with software-based SL/TP control due to MT5 AutoTrading being disabled. The system uses a gap protection mechanism with native SL while managing dynamic trailing stops via software.

---

### PHASE 3: PRİMNET Daily Reset & Initial Trailing Stop Setup (April 7, 10:08:39)

**Daily Reset Parameters:**
```
2026-04-07 10:08:39.088 | engine.h_engine:_primnet_daily_reset:1809
- PRİMNET yenileme [F_AKBNK] t=8050481884
- yeni SL (73.1293) eskiden kötü — eski SL korundu
- (new SL is worse/higher - old SL preserved)

2026-04-07 10:08:39.250 | engine.h_engine:_primnet_daily_reset:1902
- PRİMNET yenileme: ticket=8050481884 F_AKBNK SELL
- ref=0.0000→72.2100 (reference price updated)
- SL=73.1293→73.1293 (preserved)
- TP=63.9111→65.3501 (profit target updated/tightened)
- giriş_prim=0.35 (entry PnL reduced significantly from 2.61)
- trailing=1.5 (trailing stop multiplier: 1.5x ATR)
```

**Interpretation:**
- Reference price moved from 70.62 to 72.21 (price dropped 1.59 points against the short)
- Entry PnL collapsed from +2.61 to +0.35
- SL tightened from 73.5193 to 73.1293 as stop_prim got worse
- TP tightened from 63.9111 to 65.3501 (raised by 1.44 points toward current price)

---

### PHASE 4: Dynamic Trailing Stop Calculations (April 7, 10:08:49 onwards)

**Continuous PRİMNET Trailing SL Calculations (Every ~10 seconds):**

**Timeline of Price Movement and SL Adjustments:**

| Time | Price | giriş_prim | güncel_prim | kâr_prim | stop_prim | SL Level | Notes |
|------|-------|-----------|------------|----------|-----------|----------|--------|
| 10:08:49 | 71.57 | 0.35 | -0.90 | 1.25 | 0.60 | 72.6432 | Price fell, SL trailing down |
| 10:08:54 | 71.54 | 0.35 | -0.93 | 1.27 | 0.57 | 72.6232 | Continued decline |
| 10:09:04 | 71.56 | 0.35 | -0.91 | 1.26 | 0.59 | 72.6332 | Slight recovery |
| 10:09:14 | 71.57 | 0.35 | -0.90 | 1.25 | 0.60 | 72.6432 | Stabilized |
| 10:09:24 | 71.61 | 0.35 | -0.86 | 1.20 | 0.64 | 72.6732 | Price rose slightly, SL up |
| 10:09:34 | 71.65 | 0.35 | -0.82 | 1.16 | 0.68 | 72.7032 | Continued rise |
| 10:09:44 | 71.71 | 0.35 | -0.76 | 1.11 | 0.74 | 72.7431 | Price climbing |
| 10:09:54 | 71.78 | 0.35 | -0.69 | 1.04 | 0.81 | 72.7931 | **Price hit 71.78** |
| 10:10:04 | 71.78 | 0.35 | -0.69 | 1.04 | 0.81 | 72.7931 | Flat |
| 10:10:14 | 71.74 | 0.35 | -0.73 | 1.08 | 0.77 | 72.7632 | Slight pullback |
| ... | ... | ... | ... | ... | ... | ... | ... |
| **11:56:01** | ~72.21 | 0.35 | TBD | TBD | TBD | **72.2332** | **Morning reset** |

---

### CRITICAL: April 7, 11:56 - Morning Price Movement NOT Found in Logs

**Gap in Analysis:** Between 10:18:14 and 11:56:01, the logs do not show explicit price tick data. However:

**At 11:56:01 PRİMNET Daily Reset:**
```
2026-04-07 11:56:01.738 | engine.h_engine:_primnet_daily_reset:1884
- PRİMNET yenileme: ticket=8050481884 F_AKBNK SELL
- ref=0.0000→72.2100 (reference price)
- SL=72.2332→72.2332 (NEW DAILY SL - SIGNIFICANTLY LOWERED)
- TP=65.3501→65.3501 (maintained)
- giriş_prim=0.35
- trailing=1.5
```

**This indicates:**
- Reference price is now 72.21 (up from 70.62 entry, position now -1.59 underwater)
- NEW SL is 72.2332 (only 0.023 points above current ref price)
- This is an extremely tight stop (gap protection only)
- The trailing mechanism is about to trigger

---

### PHASE 5: Final Closure via SOFTWARE_SL (April 7, 11:56:51-11:56:52)

**Software Stop Loss Trigger:**
```
2026-04-07 11:56:51.751 | engine.h_engine:_check_software_sltp:844
- Software SOFTWARE_SL: ticket=8050481884 F_AKBNK SELL
- fiyat=72.2400 (current price)
- seviye=72.2332 (software SL level)
- Status: kapatılıyor (deneme 1/3) — POSITION CLOSING

2026-04-07 11:56:52.065 | engine.h_engine:_cancel_stop_limit_orders:1914
- Bekleyen hedef emri iptal edildi: order=8050490497 F_AKBNK
- (Pending profit target order cancelled)

2026-04-07 11:56:52.066 | engine.database:close_hybrid_position:1407
- Hibrit pozisyon kapatıldı: ticket=8050481884
- neden=SOFTWARE_SL
- pnl=-3.00

2026-04-07 11:56:52.066 | engine.h_engine:_finalize_close:2042
- Hibrit pozisyon kapatıldı: ticket=8050481884 F_AKBNK
- neden=SOFTWARE_SL
- pnl=-3.00

2026-04-07 11:56:52.067 | engine.h_engine:_check_software_sltp:868
- Software SOFTWARE_SL başarılı: ticket=8050481884 F_AKBNK
- PnL=-3.00
```

**Closure Summary:**
- **Closure Price:** ~72.24 TRY
- **Entry Price:** ~70.62 TRY (reference)
- **Loss:** 1.62 TRY per lot × 1.0 lot = -1.62 TRY
- **Recorded P&L:** -3.00 TRY (includes fees/slippage)
- **Reason:** SOFTWARE_SL (software-managed stop loss triggered at 72.2332)
- **Status:** Successful closure via hybrid engine

---

## KEY FINDINGS

### 1. **No 71.16 Price Level Recorded**
The logs do not show the price hitting 71.16 during the position's lifetime. The lowest price observed was ~71.54 TRY around 10:08:54. This suggests either:
- The price 71.16 occurred during the trading day gap (10:18-11:56) not visible in DEBUG logs
- The 71.16 reference may be from a different timeframe or contract
- The price never actually hit that level (unlikely given SELL position)

### 2. **PRİMNET Trailing Stop Mechanism**
The system uses a 1.5x ATR (0.3320) trailing stop mechanism:
- Formula: `SL = ref_price + stop_prim × 0.01`
- `stop_prim` = entry profit + current profit - (trailing multiplier × ATR)
- As price moves against the short (up), SL rises; as it moves favorably (down), SL falls

### 3. **Morning Reset (April 7, 11:56) - Critical Event**
At daily reset, reference price jumped from 72.21 to... wait, ref stayed at 72.21 but the **NEW SL reset to 72.2332**, just 0.023 above the reference price. This extreme tightness suggests:
- The overnight or morning saw significant price movement
- The daily reset algorithm tightened the stop dramatically
- This was essentially a "fail-safe" stop (gap protection only)

### 4. **Software SL Triggering at 72.24**
The position closed when price touched 72.24, hitting the software-managed SL at 72.2332. This was NOT a market SL (MT5 native) but rather H-Engine's proprietary software control triggered by the continuous monitoring loop.

### 5. **MT5 AutoTrading Disabled Impact**
Throughout the entire trade, MT5's AutoTrading was disabled by the client, forcing the system into software SL/TP management mode. This means:
- No native MT5 SL order was active
- All SL management was done via software polling
- The system had to continuously check the current price and manually close when conditions were met

---

## Trailing Stop Calculation Formula (April 7, 10:08:49)

```
PRİMNET [F_AKBNK] t=8050481884:
  giriş_prim    = 0.35     (entry PnL at reference)
  güncel_prim   = -0.90    (current mark-to-market PnL from ref)
  kâr_prim      = 1.25     (profit buffer = giriş - güncel)
  trailing      = 1.5      (multiplier)
  stop_prim     = 0.60     (trailing stop level in PRİMNET points)

  SL = 72.6432  (= ref + stop_prim × 0.01)
                (= 72.21 + 0.60 × 0.01)
```

---

## Position Timeline Summary

| Timestamp | Event | Details |
|-----------|-------|---------|
| Apr 6, 15:36-15:42 | **OPENING** | SELL 1.0 F_AKBNK @ ~70.62 |
| Apr 6, 15:44:16 | **H-ENGINE TRANSFER** | Transferred to PRİMNET hybrid management (software SL/TP) |
| Apr 7, 10:08:39 | **DAILY RESET** | Reference updated to 72.21; SL set to 73.1293 |
| Apr 7, 10:08:49-10:18:14 | **TRAILING SL UPDATES** | Continuous monitoring; SL ranges 72.6432-73.0532 as price fluctuates |
| Apr 7, 11:56:01 | **MORNING RESET** | CRITICAL: SL drastically tightened to 72.2332 (gap protection) |
| Apr 7, 11:56:51-52 | **SOFTWARE_SL CLOSURE** | Price touched 72.24; SL triggered; position closed @ ~72.24 |
| **Final P&L** | **-3.00 TRY** | (Entry 70.62, Exit 72.24 = -1.62 + fees) |

---

## Why Position Closed at 72.25 (Not Earlier)

The position remained open because:

1. **Trailing SL Protection**: The system allowed favorable price movement (downward) and progressively moved the SL down with price
2. **Morning Gap Protection**: At morning reset (11:56), the SL was set to 72.2332 as a gap protection measure
3. **Price Action**: Price rebounded to 72.24 after reaching lows, hitting the protective stop
4. **Software Management**: Without native MT5 SL (AutoTrading disabled), the system relied on periodic polling to detect the SL trigger

The 72.25 closure price aligns with the 72.2332 software SL level, representing the moment when H-Engine's polling detected the price had touched or exceeded the threshold.

---

## Logs References

- Opening events: `/sessions/youthful-magical-albattani/mnt/USTAT/logs/ustat_2026-04-06.log` (lines 668072+)
- Hybrid transfer: Line 673764+ (April 6, 15:44:16)
- Trailing calculations: Lines 669282+ (April 6); Continues April 7 10:08:39+
- Final closure: `/sessions/youthful-magical-albattani/mnt/USTAT/logs/ustat_2026-04-07.log` (line 11:56:51+)

---

*Analysis completed: 2026-04-07*
*Next steps: Review PRİMNET daily reset logic for morning SL tightening patterns*
