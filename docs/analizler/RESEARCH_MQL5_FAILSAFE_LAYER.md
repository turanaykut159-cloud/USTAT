# MQL5 Safety & Position Management as Failsafe Layer for Python Trading System
**Date:** 2026-04-01
**Project:** ÜSTAT v5.9
**Research Focus:** MQL5 capabilities for backup safety layer

---

## EXECUTIVE SUMMARY

MQL5 Expert Advisors (EAs) are fully capable of serving as an independent failsafe/backup layer for the Python trading system. Key findings:

- **Expert Advisors CAN**: Place orders, modify SL/TP, close positions, monitor drawdown, execute time-based closures, monitor account equity
- **Services CANNOT**: Trade directly (no chart binding, limited event handling)
- **Recommendation**: Use Expert Advisor (not Service) as failsafe layer
- **Detection Pattern**: Heartbeat file monitoring can detect Python process death and trigger MQL5 override
- **Independence**: MQL5 EA operates directly against MT5 terminal/broker (no Python dependency)

---

## SECTION 1: MQL5 EXPERT ADVISORS vs SERVICES

### 1.1 Expert Advisor Capabilities (RECOMMENDED FOR FAILSAFE)

**Expert Advisors are the correct choice for a safety failsafe layer.**

| Capability | Expert Advisor | Service |
|------------|-----------------|---------|
| **Place Orders** | ✓ YES | ✗ NO |
| **Modify SL/TP** | ✓ YES | ✗ NO |
| **Close Positions** | ✓ YES | ✗ NO |
| **Chart Binding** | Required (single chart) | ✗ Not applicable |
| **Event Handling** | OnTick, OnTimer, OnStart, OnDeinit | OnStart only |
| **Real-time Monitoring** | ✓ Full - responds to ticks | Limited - no ticks |
| **Account Info Access** | ✓ YES | ✓ YES |
| **Position Enumeration** | ✓ YES | ✓ YES |
| **Direct Trading** | ✓ YES (primary purpose) | ✗ NO (background tasks) |

**Source:** [Services - Creating application programs - MQL5 Programming for Traders](https://www.mql5.com/en/book/applications/script_service/services)

### 1.2 Expert Advisor Architecture for Failsafe Layer

```
Failsafe EA Running on MT5 (Chart Attachment)
├── OnInit()
│   ├── Load last known Python heartbeat timestamp from file
│   ├── Initialize timer (EventSetTimer)
│   └── Set local variables for monitoring
│
├── OnTick()
│   ├── Triggered on every price tick
│   ├── Check positions, account equity, risk status
│   └── Monitor heartbeat in background
│
├── OnTimer() [Recommended Approach]
│   ├── Fixed interval monitoring (e.g., 5-10 second timer)
│   ├── Check Python heartbeat file
│   │   ├── If timestamp fresh (within 30 seconds) → Continue normally
│   │   └── If timestamp stale (>30 seconds) → ACTIVATE FAILSAFE
│   ├── Drawdown monitoring
│   ├── Time-based position closure checks
│   └── Account equity checks
│
└── OnDeinit()
    └── Cleanup (close positions if failsafe mode active)
```

**Why OnTimer over OnTick for Failsafe:**
- OnTick only fires when there's market activity (can miss frozen markets)
- OnTimer runs at fixed intervals regardless of tick flow
- More reliable for monitoring external process health

---

## SECTION 2: ORDER MANAGEMENT CAPABILITIES

### 2.1 Placing Orders (OrderSend)

**MQL5 FULL CAPABILITY:** Can place market orders, pending orders, with SL/TP in single call or separate calls.

#### Basic Order Placement Pattern

```cpp
#include <Trade/Trade.mqh>

CTrade trade;  // Standard library class

void PlaceOrder(string symbol, ENUM_ORDER_TYPE type, double volume,
                double entry_price, double sl, double tp) {

    MqlTradeRequest request = {};
    MqlTradeResult result = {};

    request.action = TRADE_ACTION_DEAL;
    request.symbol = symbol;
    request.volume = volume;
    request.type = type;  // ORDER_TYPE_BUY or ORDER_TYPE_SELL
    request.price = entry_price;
    request.sl = sl;      // Stop Loss
    request.tp = tp;      // Take Profit

    if (!OrderSend(request, result)) {
        Print("Order send failed: ", GetLastError());
    } else {
        Print("Order ticket: ", result.order);
    }
}
```

**Key Point:** SL/TP can be set in the same OrderSend call, making protection guaranteed.

**Sources:**
- [Order Strategies. Multi-Purpose Expert Advisor - MQL5 Articles](https://www.mql5.com/en/articles/495)
- [What Are Expert Advisors in MetaTrader 5 and How They Work](https://justmarkets.com/trading-articles/learning/what-are-expert-advisors-eas-in-metatrader-5)

### 2.2 Modifying Stop Loss and Take Profit (TRADE_ACTION_SLTP)

**MQL5 FULL CAPABILITY:** Can modify SL/TP independently without reopening position.

#### Modification Pattern

```cpp
void ModifyPositionSLTP(ulong ticket, double new_sl, double new_tp) {
    MqlTradeRequest request = {};
    MqlTradeResult result = {};

    request.action = TRADE_ACTION_SLTP;
    request.position = ticket;
    request.sl = new_sl;
    request.tp = new_tp;

    if (!OrderSend(request, result)) {
        Print("Modify failed: ", GetLastError());
    }
}
```

**Sources:**
- [How to Create Your Own Trailing Stop - MQL5 Articles](https://www.mql5.com/en/articles/134)
- [How to develop any type of Trailing Stop and connect to an EA - MQL5 Articles](https://www.mql5.com/en/articles/14862)

### 2.3 Closing Positions (TRADE_ACTION_DEAL or PositionClose)

**MQL5 FULL CAPABILITY:** Can close individual positions or all positions with full control.

#### Standard Approach (CTrade Class)

```cpp
#include <Trade/Trade.mqh>

CTrade trade;

void CloseAllPositions() {
    int total = PositionsTotal();

    // Loop from end to start (prevents index skipping)
    for (int i = total - 1; i >= 0; i--) {
        if (PositionSelectByIndex(i)) {
            string symbol = PositionGetString(POSITION_SYMBOL);
            ulong ticket = PositionGetInteger(POSITION_TICKET);

            if (trade.PositionClose(symbol)) {
                Print("Closed position: ", ticket);
            }
        }
    }
}

void CloseSpecificPosition(ulong ticket) {
    if (PositionSelectByTicket(ticket)) {
        string symbol = PositionGetString(POSITION_SYMBOL);
        trade.PositionClose(symbol);
    }
}
```

#### Raw OrderSend Approach

```cpp
void ClosePositionDirect(string symbol, int volume) {
    MqlTradeRequest request = {};
    MqlTradeResult result = {};

    request.action = TRADE_ACTION_DEAL;
    request.symbol = symbol;
    request.volume = volume;
    request.type = ORDER_TYPE_SELL;  // Opposite of original
    request.type_filling = ORDER_FILLING_IOC;

    OrderSend(request, result);
}
```

**Critical Point:** Always close positions from END to START when looping to prevent index skipping.

**Sources:**
- [PositionClose(const string,ulong) - CTrade - Trade Classes](https://www.mql5.com/en/docs/standardlibrary/tradeclasses/ctrade/ctradepositionclose)
- [How to close a position - MQL5 Forum](https://www.mql5.com/en/forum/203592)

---

## SECTION 3: POSITION ENUMERATION & MONITORING

### 3.1 Position Enumeration Pattern

**MQL5 FULL CAPABILITY:** Can enumerate, select, and inspect all positions with full property access.

#### Complete Enumeration Example

```cpp
void AnalyzeAllPositions() {
    int total = PositionsTotal();

    for (int i = 0; i < total; i++) {
        // Select position by index
        if (PositionSelectByIndex(i)) {

            // Read properties
            ulong ticket = PositionGetInteger(POSITION_TICKET);
            string symbol = PositionGetString(POSITION_SYMBOL);
            ENUM_POSITION_TYPE pos_type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
            double volume = PositionGetDouble(POSITION_VOLUME);
            double entry_price = PositionGetDouble(POSITION_PRICE_OPEN);
            double current_price = PositionGetDouble(POSITION_PRICE_CURRENT);
            double profit = PositionGetDouble(POSITION_PROFIT);
            double sl = PositionGetDouble(POSITION_SL);
            double tp = PositionGetDouble(POSITION_TP);
            datetime open_time = (datetime)PositionGetInteger(POSITION_TIME);

            Print("Position ", ticket, " | ", symbol,
                  " | Type: ", pos_type,
                  " | Profit: ", profit,
                  " | SL: ", sl, " TP: ", tp);
        }
    }
}
```

#### Key Position Properties

| Property | Method | Returns |
|----------|--------|---------|
| Ticket | `PositionGetInteger(POSITION_TICKET)` | Position unique ID |
| Symbol | `PositionGetString(POSITION_SYMBOL)` | Trading pair |
| Type | `PositionGetInteger(POSITION_TYPE)` | BUY=0, SELL=1 |
| Volume | `PositionGetDouble(POSITION_VOLUME)` | Current volume |
| Entry Price | `PositionGetDouble(POSITION_PRICE_OPEN)` | Opening price |
| Current Price | `PositionGetDouble(POSITION_PRICE_CURRENT)` | Latest price |
| Profit/Loss | `PositionGetDouble(POSITION_PROFIT)` | P&L in account currency |
| SL | `PositionGetDouble(POSITION_SL)` | Stop Loss level |
| TP | `PositionGetDouble(POSITION_TP)` | Take Profit level |
| Open Time | `PositionGetInteger(POSITION_TIME)` | When opened |

**Sources:**
- [Documentation on MQL5: PositionGetTicket / Trade Functions](https://www.mql5.com/en/docs/trading/positiongetticket)
- [Getting the list of positions - Trading automation](https://www.mql5.com/en/book/automation/experts/experts_position_list)

---

## SECTION 4: TRAILING STOP IMPLEMENTATION

### 4.1 Trailing Stop Pattern

**MQL5 FULL CAPABILITY:** Can independently manage trailing stops without Python coordination.

#### Standalone Trailing Stop EA

```cpp
#include <Trade/Trade.mqh>

input double TrailingDistance = 50;  // Points to trail
input int UpdateInterval = 10;       // Seconds between updates

CTrade trade;
datetime last_update = 0;

void OnTick() {
    // Update trailing stops when price moves
    ManageTrailingStops();
}

void ManageTrailingStops() {
    int total = PositionsTotal();

    for (int i = 0; i < total; i++) {
        if (PositionSelectByIndex(i)) {

            string symbol = PositionGetString(POSITION_SYMBOL);
            double current_sl = PositionGetDouble(POSITION_SL);
            ENUM_POSITION_TYPE pos_type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);

            // Get symbol's tick info
            MqlTick tick;
            if (!SymbolInfoTick(symbol, tick)) continue;

            double new_sl = 0;

            if (pos_type == POSITION_TYPE_BUY) {
                // For buy: move SL up as price rises
                new_sl = tick.bid - TrailingDistance * SymbolInfoDouble(symbol, SYMBOL_POINT);
                if (new_sl > current_sl) {
                    ModifyPositionSL(PositionGetInteger(POSITION_TICKET), new_sl);
                }
            }
            else if (pos_type == POSITION_TYPE_SELL) {
                // For sell: move SL down as price falls
                new_sl = tick.ask + TrailingDistance * SymbolInfoDouble(symbol, SYMBOL_POINT);
                if (new_sl < current_sl || current_sl == 0) {
                    ModifyPositionSL(PositionGetInteger(POSITION_TICKET), new_sl);
                }
            }
        }
    }
}

void ModifyPositionSL(ulong ticket, double new_sl) {
    MqlTradeRequest request = {};
    MqlTradeResult result = {};

    request.action = TRADE_ACTION_SLTP;
    request.position = ticket;
    request.sl = new_sl;

    OrderSend(request, result);
}
```

**Key Advantage:** This runs independently in MT5 terminal, survives Python crash.

**Sources:**
- [How to Create Your Own Trailing Stop - MQL5 Articles](https://www.mql5.com/en/articles/134)
- [How to develop any type of Trailing Stop and connect to an EA](https://www.mql5.com/en/articles/14862)

---

## SECTION 5: TIME-BASED POSITION CLOSURE (17:45 SHUTDOWN)

### 5.1 End-of-Day Closure Pattern

**MQL5 FULL CAPABILITY:** Can close all positions at specific time without Python.

#### Reliable EOD Closure Implementation

```cpp
input string EODCloseTime = "17:45";  // HH:MM format

void OnTimer() {
    // Called every N seconds via EventSetTimer()

    // Get server time (preferred for Forex/futures)
    datetime now = TimeCurrent();
    MqlDateTime time_struct;
    TimeToStruct(now, time_struct);

    // Parse desired close time
    int desired_hour = 17;
    int desired_minute = 45;

    // Check if we've reached the close time window
    if (time_struct.hour == desired_hour && time_struct.min == desired_minute) {
        CloseAllPositionsForEOD();
    }
}

void CloseAllPositionsForEOD() {
    int total = PositionsTotal();
    int closed_count = 0;

    // Must loop from end to start to prevent skipping
    for (int i = total - 1; i >= 0; i--) {
        if (PositionSelectByIndex(i)) {
            string symbol = PositionGetString(POSITION_SYMBOL);

            MqlTradeRequest request = {};
            MqlTradeResult result = {};

            request.action = TRADE_ACTION_DEAL;
            request.symbol = symbol;
            request.volume = PositionGetDouble(POSITION_VOLUME);
            request.type_filling = ORDER_FILLING_IOC;

            // Opposite of position type
            ENUM_POSITION_TYPE ptype = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
            request.type = (ptype == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;

            if (OrderSend(request, result)) {
                closed_count++;
            }
        }
    }

    Print("EOD: Closed ", closed_count, " positions at ",
          time_struct.hour, ":", time_struct.min);
}
```

#### Time Considerations

Three time sources available:

| Time Source | Use Case | Notes |
|-------------|----------|-------|
| `TimeCurrent()` | Server time | **RECOMMENDED** for trading close |
| `TimeLocal()` | Local computer time | Subject to computer clock |
| `TimeTradeServer()` | Broker server time | Same as TimeCurrent() |

**Use `TimeCurrent()` for broker-relative timing.**

**Sources:**
- [Simple EA closing all trades at specific time - MQL5 Forum](https://www.mql5.com/en/forum/280588)
- [Learn how to deal with date and time in MQL5 - MQL5 Articles](https://www.mql5.com/en/articles/13466)

---

## SECTION 6: DRAWDOWN MONITORING & THRESHOLD-BASED CLOSURE

### 6.1 Account Equity Monitoring Pattern

**MQL5 FULL CAPABILITY:** Can monitor account equity and close positions on threshold breach.

#### Comprehensive Drawdown Monitoring

```cpp
input double MaxDailyDrawdownPercent = 3.0;      // %
input double MaxTotalDrawdownPercent = 15.0;     // % (felaket level)
input double MaxFloatingLossPercent = 1.5;       // % on open positions

void OnTimer() {
    // Called every 10-30 seconds
    CheckDrawdownLimits();
}

void CheckDrawdownLimits() {
    // Get account information
    double account_balance = AccountInfoDouble(ACCOUNT_BALANCE);
    double account_equity = AccountInfoDouble(ACCOUNT_EQUITY);
    double account_margin = AccountInfoDouble(ACCOUNT_MARGIN);
    double account_margin_free = AccountInfoDouble(ACCOUNT_MARGIN_FREE);

    // Calculate drawdown metrics
    double total_drawdown = account_balance - account_equity;
    double total_drawdown_pct = (total_drawdown / account_balance) * 100.0;

    double floating_loss = 0;
    int total = PositionsTotal();
    for (int i = 0; i < total; i++) {
        if (PositionSelectByIndex(i)) {
            double profit = PositionGetDouble(POSITION_PROFIT);
            if (profit < 0) floating_loss += MathAbs(profit);
        }
    }
    double floating_loss_pct = (floating_loss / account_balance) * 100.0;

    Print("Balance: ", account_balance,
          " | Equity: ", account_equity,
          " | Total DD: ", total_drawdown_pct, "%",
          " | Float DD: ", floating_loss_pct, "%");

    // TIER 1: Hard drawdown (>15% = CATASTROPHIC)
    if (total_drawdown_pct >= MaxTotalDrawdownPercent) {
        Print("CRITICAL: Hard drawdown ", total_drawdown_pct, "% reached!");
        CloseAllPositionsEmergency();
        return;
    }

    // TIER 2: Daily drawdown threshold
    if (total_drawdown_pct >= MaxDailyDrawdownPercent) {
        Print("WARNING: Daily drawdown ", total_drawdown_pct, "% reached!");
        CloseAllPositionsEmergency();
        return;
    }

    // TIER 3: Floating loss limit
    if (floating_loss_pct >= MaxFloatingLossPercent) {
        Print("INFO: Floating loss ", floating_loss_pct, "% reached. No new trades.");
        // Signal to Python: block new trades (or just close here)
    }
}

void CloseAllPositionsEmergency() {
    int total = PositionsTotal();

    for (int i = total - 1; i >= 0; i--) {
        if (PositionSelectByIndex(i)) {
            string symbol = PositionGetString(POSITION_SYMBOL);

            MqlTradeRequest request = {};
            MqlTradeResult result = {};

            request.action = TRADE_ACTION_DEAL;
            request.symbol = symbol;
            request.volume = PositionGetDouble(POSITION_VOLUME);
            request.type_filling = ORDER_FILLING_IOC;

            ENUM_POSITION_TYPE ptype = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
            request.type = (ptype == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;

            OrderSend(request, result);
        }
    }

    Print("EMERGENCY: All positions closed. Drawdown threshold breached.");
}
```

#### Account Info Properties Reference

```cpp
// Key AccountInfoDouble() properties:

double balance = AccountInfoDouble(ACCOUNT_BALANCE);
// Current account balance (sum of closed trades + initial deposit)

double equity = AccountInfoDouble(ACCOUNT_EQUITY);
// Account equity = balance + floating P/L from open trades

double margin = AccountInfoDouble(ACCOUNT_MARGIN);
// Used margin (locked for open positions)

double margin_free = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
// Free margin available for new trades

// Derived calculations:
double drawdown = balance - equity;           // Absolute loss in account currency
double drawdown_pct = (drawdown / balance) * 100.0;  // Percentage
```

**Sources:**
- [Drawdown Limiter User Guide](https://www.mql5.com/en/blogs/post/752215)
- [Documentation on MQL5: AccountInfoDouble](https://www.mql5.com/en/docs/account/accountinfodouble)
- [Account Properties - Environment State](https://www.mql5.com/en/docs/constants/environment_state/accountinformation)

---

## SECTION 7: HEARTBEAT DETECTION - PYTHON PROCESS MONITORING

### 7.1 Failsafe Activation Trigger

**MQL5 CAPABILITY:** Can detect Python process death via file heartbeat pattern and activate full override.

#### Architecture: Heartbeat Detection

```
Python Trading System (every 10 seconds)
├── Updates: C:\Users\pc\Desktop\USTAT\.heartbeat
│   ├── Writes: timestamp (ISO format)
│   └── Pattern: atomic write (temp + rename)
│
MQL5 Failsafe EA (OnTimer every 5 seconds)
├── Read: C:\Users\pc\Desktop\USTAT\.heartbeat
├── Parse: timestamp
├── Logic:
│   ├── If (now - timestamp) < 30 seconds → Normal operation
│   ├── If (now - timestamp) >= 30 seconds → FAILSAFE ACTIVATED
│   │   ├── Close all positions immediately
│   │   ├── Block new trades
│   │   └── Write alert file
│   └── If file doesn't exist → FAILSAFE ACTIVATED
└── Recovery:
    └── When heartbeat resumes → Resume normal operation
```

#### MQL5 File Reading Implementation

```cpp
#include <Trade/Trade.mqh>

input string HeartbeatFilePath = "C:\\Users\\pc\\Desktop\\USTAT\\.heartbeat";
input int HeartbeatTimeoutSeconds = 30;
input int FailsafeCheckIntervalSeconds = 5;

CTrade trade;
bool failsafe_active = false;
datetime last_heartbeat = 0;

void OnInit() {
    // Set up timer: check every N seconds
    EventSetTimer(FailsafeCheckIntervalSeconds);
}

void OnTimer() {
    CheckPythonHeartbeat();
}

void CheckPythonHeartbeat() {
    string heartbeat_timestamp = ReadHeartbeatFile();

    if (heartbeat_timestamp == "") {
        // File doesn't exist or can't be read
        if (!failsafe_active) {
            Print("ERROR: Heartbeat file not found. ACTIVATING FAILSAFE.");
            ActivateFailsafe();
        }
        return;
    }

    // Parse timestamp
    datetime heartbeat_time = StringToTime(heartbeat_timestamp);
    datetime now = TimeCurrent();
    int time_diff = (int)(now - heartbeat_time);

    if (time_diff > HeartbeatTimeoutSeconds) {
        // Python process appears dead
        if (!failsafe_active) {
            Print("ERROR: Heartbeat stale by ", time_diff,
                  " seconds. ACTIVATING FAILSAFE.");
            ActivateFailsafe();
        }
    } else {
        // Heartbeat fresh - Python alive
        if (failsafe_active) {
            Print("INFO: Heartbeat resumed. DEACTIVATING FAILSAFE.");
            DeactivateFailsafe();
        }
    }
}

string ReadHeartbeatFile() {
    int file_handle = FileOpen(HeartbeatFilePath, FILE_READ | FILE_TXT);

    if (file_handle == INVALID_HANDLE) {
        return "";  // File not found or can't open
    }

    string timestamp = FileReadString(file_handle);
    FileClose(file_handle);

    return timestamp;
}

void ActivateFailsafe() {
    failsafe_active = true;
    Print("FAILSAFE ACTIVATED at ", TimeCurrent());

    // STEP 1: Close all positions immediately
    CloseAllPositionsFailsafe();

    // STEP 2: Write alert log
    WriteFailsafeAlert("FAILSAFE_ACTIVATED", "Python process heartbeat lost");

    // STEP 3: Optional: Pause EA to prevent trading
    // (Or keep it running for continuous monitoring)
}

void DeactivateFailsafe() {
    failsafe_active = false;
    Print("FAILSAFE DEACTIVATED at ", TimeCurrent());
    WriteFailsafeAlert("FAILSAFE_DEACTIVATED", "Python process heartbeat resumed");
}

void CloseAllPositionsFailsafe() {
    int total = PositionsTotal();
    int closed = 0;

    for (int i = total - 1; i >= 0; i--) {
        if (PositionSelectByIndex(i)) {
            string symbol = PositionGetString(POSITION_SYMBOL);
            double volume = PositionGetDouble(POSITION_VOLUME);
            ENUM_POSITION_TYPE ptype = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);

            MqlTradeRequest request = {};
            MqlTradeResult result = {};

            request.action = TRADE_ACTION_DEAL;
            request.symbol = symbol;
            request.volume = volume;
            request.type_filling = ORDER_FILLING_IOC;
            request.type = (ptype == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;

            if (OrderSend(request, result)) {
                closed++;
            } else {
                Print("Failed to close position: ", GetLastError());
            }
        }
    }

    Print("Failsafe: Closed ", closed, " positions");
}

void WriteFailsafeAlert(string event_type, string message) {
    string alert_file = "failsafe_alerts_" + TimeToString(TimeCurrent(), TIME_DATE) + ".txt";

    int handle = FileOpen(alert_file, FILE_READ | FILE_WRITE | FILE_TXT);
    if (handle != INVALID_HANDLE) {
        FileSeek(handle, 0, SEEK_END);
        FileWrite(handle, TimeToString(TimeCurrent(), TIME_DATE | TIME_MINUTES) +
                         " | " + event_type + " | " + message);
        FileClose(handle);
    }
}

void OnDeinit(const int reason) {
    EventKillTimer();
}
```

#### Python Side: Writing Heartbeat

```python
# In engine/main.py during _run_single_cycle()

import time
from datetime import datetime

def _update_heartbeat():
    """Write heartbeat timestamp that MQL5 EA monitors"""
    heartbeat_file = r"C:\Users\pc\Desktop\USTAT\.heartbeat"
    timestamp = datetime.utcnow().isoformat()

    try:
        # Atomic write: temp + rename
        temp_file = heartbeat_file + ".tmp"
        with open(temp_file, "w") as f:
            f.write(timestamp)
        os.replace(temp_file, heartbeat_file)
    except Exception as e:
        logger.error(f"Failed to update heartbeat: {e}")

# Call this every cycle (every 10 seconds)
def _run_single_cycle():
    # ... existing code ...

    # At END of cycle
    self._update_heartbeat()
```

**Sources:**
- [How to Catch VPS Crashes Automatically](https://www.mql5.com/en/blogs/post/765973)
- [MT5 Monitoring Heartbeat](https://www.mql5.com/en/market/product/96473)
- [Metatrader Uptime Monitoring MT5](https://www.mql5.com/en/market/product/115683)

---

## SECTION 8: EVENT HANDLERS - WHICH TO USE

### 8.1 Event Handler Comparison

| Handler | Trigger | Use Case | Frequency |
|---------|---------|----------|-----------|
| `OnTick()` | New market tick arrives | Price-based logic | Every tick (varies) |
| `OnTimer()` | Timer interval elapsed | Time-based checks | Fixed interval (1ms-60s) |
| `OnInit()` | EA attached to chart | Initialization | Once |
| `OnDeinit()` | EA removed from chart | Cleanup | Once |

### 8.2 Recommended for Failsafe: OnTimer

```cpp
void OnInit() {
    // Set timer for 5-10 second intervals
    EventSetTimer(5);  // 5 seconds
}

void OnTimer() {
    // This executes every 5 seconds regardless of market activity

    CheckPythonHeartbeat();        // Critical
    CheckDrawdownLimits();         // Critical
    CheckEndOfDayTime();           // Critical
    ManageTrailingStops();         // Optional (if Python crashes)
}

void OnDeinit(const int reason) {
    EventKillTimer();              // Always clean up
}
```

**Why OnTimer is better for failsafe:**
- Does NOT depend on market ticks (works on frozen markets)
- Reliable fixed intervals
- Better for time-based triggers
- Works even when symbol has no activity

**OnTick alternatives:**
- Can be unreliable during low liquidity
- May miss monitors on inactive symbols
- Good for price-based checks, not time-based

**Sources:**
- [Documentation on MQL5: OnTimer](https://www.mql5.com/en/docs/event_handlers/ontimer)
- [Documentation on MQL5: OnTick](https://www.mql5.com/en/docs/event_handlers/ontick)

---

## SECTION 9: ALERT & NOTIFICATION SYSTEM

### 9.1 In-Terminal Alerts

**MQL5 CAPABILITY:** Can send push notifications to MetaTrader mobile app and terminal alerts.

```cpp
// Simple terminal alert (appears in MT5 bottom bar)
void SendAlert(string message) {
    Alert(message);  // Popup + sound
    Print(message);  // Log to journal
}

// Example usage
void ActivateFailsafe() {
    SendAlert("FAILSAFE ACTIVATED: Python process not responding!");
}
```

### 9.2 Push Notifications to Mobile

**Requirements:**
1. User must enable in MT5: Tools → Options → Notifications tab
2. User must provide MetaQuotes ID
3. Set `EnablePushNotifications = true` in EA

```cpp
input bool EnablePushNotifications = true;

void OnInit() {
    // MQL5 automatically sends to configured mobile app
}

void SendCriticalAlert(string message) {
    if (EnablePushNotifications) {
        Alert("CRITICAL: " + message);  // Will push if configured
    }
}
```

### 9.3 File-Based Alerting (For Integration)

```cpp
void LogAlert(string level, string message) {
    string log_file = "mql5_failsafe_" + TimeToString(TimeCurrent(), TIME_DATE) + ".log";

    int handle = FileOpen(log_file, FILE_READ | FILE_WRITE | FILE_TXT);
    if (handle != INVALID_HANDLE) {
        FileSeek(handle, 0, SEEK_END);
        FileWrite(handle, TimeToString(TimeCurrent(), TIME_DATE | TIME_MINUTES | TIME_SECONDS) +
                         " [" + level + "] " + message);
        FileClose(handle);
    }
}
```

**Sources:**
- [Documentation on MQL5: OnTimer](https://www.mql5.com/en/docs/event_handlers/ontimer)
- [Trade Notifications - MQL5 Market](https://www.mql5.com/en/market/product/116795)

---

## SECTION 10: FAILSAFE EA ARCHITECTURE - COMPLETE TEMPLATE

### 10.1 Full Skeleton Code

```cpp
//+------------------------------------------------------------------+
//| ÜSTAT Failsafe EA v1.0
//| Safety layer for Python trading system
//| Monitors heartbeat, drawdown, time-based closure, EOD
//+------------------------------------------------------------------+

#include <Trade/Trade.mqh>
#include <Trade/Trade.mqh>

// ==========================
// INPUT PARAMETERS
// ==========================

input string HeartbeatFilePath = "C:\\Users\\pc\\Desktop\\USTAT\\.heartbeat";
input int HeartbeatTimeoutSeconds = 30;
input int HeartbeatCheckInterval = 5;

input double MaxDailyDrawdownPercent = 3.0;
input double MaxTotalDrawdownPercent = 15.0;

input string EODCloseTime = "17:45";
input bool EnableEODClose = true;

input bool EnableTrailingStop = false;
input double TrailingDistancePoints = 50;

// ==========================
// GLOBAL VARIABLES
// ==========================

CTrade trade;
bool failsafe_active = false;
bool eod_closure_executed = false;

// ==========================
// INITIALIZATION
// ==========================

void OnInit() {
    Print("ÜSTAT Failsafe EA initialized");
    Print("Heartbeat file: ", HeartbeatFilePath);
    Print("Timeout: ", HeartbeatTimeoutSeconds, " seconds");

    // Start monitoring timer
    EventSetTimer(HeartbeatCheckInterval);

    eod_closure_executed = false;
}

// ==========================
// MAIN LOOP
// ==========================

void OnTimer() {
    // Order of operations is CRITICAL

    // 1. Check Python heartbeat (highest priority)
    CheckPythonHeartbeat();

    // 2. Check drawdown limits
    CheckDrawdownLimits();

    // 3. Check EOD closure time
    if (EnableEODClose) {
        CheckEndOfDayTime();
    }

    // 4. Manage trailing stops (if enabled)
    if (EnableTrailingStop && !failsafe_active) {
        ManageTrailingStops();
    }
}

// ==========================
// HEARTBEAT MONITORING
// ==========================

void CheckPythonHeartbeat() {
    string heartbeat_timestamp = ReadHeartbeatFile();

    if (heartbeat_timestamp == "") {
        if (!failsafe_active) {
            Print("FAILSAFE: Heartbeat file not found or unreadable");
            ActivateFailsafe("HEARTBEAT_FILE_MISSING");
        }
        return;
    }

    datetime heartbeat_time = StringToTime(heartbeat_timestamp);
    datetime now = TimeCurrent();
    int time_diff = (int)(now - heartbeat_time);

    if (time_diff > HeartbeatTimeoutSeconds) {
        if (!failsafe_active) {
            Print("FAILSAFE: Heartbeat stale by ", time_diff, " seconds");
            ActivateFailsafe("HEARTBEAT_TIMEOUT");
        }
    } else {
        if (failsafe_active) {
            Print("FAILSAFE: Heartbeat recovered, deactivating");
            DeactivateFailsafe();
        }
    }
}

string ReadHeartbeatFile() {
    int file_handle = FileOpen(HeartbeatFilePath, FILE_READ | FILE_TXT);

    if (file_handle == INVALID_HANDLE) {
        return "";
    }

    string timestamp = FileReadString(file_handle);
    FileClose(file_handle);

    return timestamp;
}

void ActivateFailsafe(string reason) {
    failsafe_active = true;

    LogAlert("CRITICAL", "FAILSAFE ACTIVATED - " + reason);
    Alert("ÜSTAT FAILSAFE ACTIVATED: " + reason);

    // Close all positions immediately
    CloseAllPositions();

    // Optional: Stop EA
    // Print("Stopping EA to prevent further trading");
    // ExpertRemove();
}

void DeactivateFailsafe() {
    failsafe_active = false;
    LogAlert("INFO", "Failsafe deactivated - heartbeat resumed");
}

// ==========================
// DRAWDOWN MONITORING
// ==========================

void CheckDrawdownLimits() {
    double balance = AccountInfoDouble(ACCOUNT_BALANCE);
    double equity = AccountInfoDouble(ACCOUNT_EQUITY);

    double total_drawdown = balance - equity;
    double total_drawdown_pct = (total_drawdown / balance) * 100.0;

    // Hard limit (L3)
    if (total_drawdown_pct >= MaxTotalDrawdownPercent) {
        LogAlert("CRITICAL", "Hard drawdown " +
                 DoubleToString(total_drawdown_pct, 2) + "% - CLOSING ALL");
        CloseAllPositions();
        return;
    }

    // Daily limit
    if (total_drawdown_pct >= MaxDailyDrawdownPercent) {
        if (!failsafe_active) {
            LogAlert("WARNING", "Daily drawdown " +
                     DoubleToString(total_drawdown_pct, 2) + "% - CLOSING ALL");
            CloseAllPositions();
        }
    }
}

// ==========================
// END-OF-DAY CLOSURE
// ==========================

void CheckEndOfDayTime() {
    datetime now = TimeCurrent();
    MqlDateTime time_struct;
    TimeToStruct(now, time_struct);

    // Parse EOD time (format: HH:MM)
    int eod_hour = 17;
    int eod_minute = 45;

    if (time_struct.hour == eod_hour && time_struct.min == eod_minute) {
        if (!eod_closure_executed) {
            eod_closure_executed = true;

            LogAlert("INFO", "EOD time reached - closing all positions");
            CloseAllPositions();
        }
    } else if (time_struct.hour == 18) {
        // Reset flag after closure hour
        eod_closure_executed = false;
    }
}

// ==========================
// POSITION MANAGEMENT
// ==========================

void CloseAllPositions() {
    int total = PositionsTotal();

    for (int i = total - 1; i >= 0; i--) {
        if (PositionSelectByIndex(i)) {
            string symbol = PositionGetString(POSITION_SYMBOL);
            double volume = PositionGetDouble(POSITION_VOLUME);
            ENUM_POSITION_TYPE ptype = (ENUM_POSITION_TYPE)
                                       PositionGetInteger(POSITION_TYPE);

            MqlTradeRequest request = {};
            MqlTradeResult result = {};

            request.action = TRADE_ACTION_DEAL;
            request.symbol = symbol;
            request.volume = volume;
            request.type_filling = ORDER_FILLING_IOC;
            request.type = (ptype == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;

            if (!OrderSend(request, result)) {
                LogAlert("ERROR", "Failed to close position: " + IntToString(GetLastError()));
            }
        }
    }

    Print("Position closure command executed. Remaining: ", PositionsTotal());
}

void ManageTrailingStops() {
    int total = PositionsTotal();

    for (int i = 0; i < total; i++) {
        if (PositionSelectByIndex(i)) {
            string symbol = PositionGetString(POSITION_SYMBOL);
            double current_sl = PositionGetDouble(POSITION_SL);
            ENUM_POSITION_TYPE ptype = (ENUM_POSITION_TYPE)
                                       PositionGetInteger(POSITION_TYPE);

            MqlTick tick;
            if (!SymbolInfoTick(symbol, tick)) continue;

            double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
            double new_sl = 0;

            if (ptype == POSITION_TYPE_BUY) {
                new_sl = tick.bid - TrailingDistancePoints * point;
                if (new_sl > current_sl) {
                    UpdatePositionSL(PositionGetInteger(POSITION_TICKET), new_sl);
                }
            } else {
                new_sl = tick.ask + TrailingDistancePoints * point;
                if (new_sl < current_sl || current_sl == 0) {
                    UpdatePositionSL(PositionGetInteger(POSITION_TICKET), new_sl);
                }
            }
        }
    }
}

void UpdatePositionSL(ulong ticket, double new_sl) {
    MqlTradeRequest request = {};
    MqlTradeResult result = {};

    request.action = TRADE_ACTION_SLTP;
    request.position = ticket;
    request.sl = new_sl;

    OrderSend(request, result);
}

// ==========================
// LOGGING
// ==========================

void LogAlert(string level, string message) {
    string log_file = "failsafe_" + TimeToString(TimeCurrent(), TIME_DATE) + ".log";

    int handle = FileOpen(log_file, FILE_READ | FILE_WRITE | FILE_TXT);
    if (handle != INVALID_HANDLE) {
        FileSeek(handle, 0, SEEK_END);
        FileWrite(handle, TimeToString(TimeCurrent(), TIME_DATE | TIME_MINUTES | TIME_SECONDS) +
                         " [" + level + "] " + message);
        FileClose(handle);
    }

    Print(message);
}

// ==========================
// CLEANUP
// ==========================

void OnDeinit(const int reason) {
    EventKillTimer();
    Print("ÜSTAT Failsafe EA deinitialized");
}
```

---

## SECTION 11: DEPLOYMENT & INTEGRATION GUIDE

### 11.1 Deployment Checklist

```
[ ] 1. Compile MQL5 EA in MetaEditor
      └─ No errors, no warnings

[ ] 2. Attach EA to single chart in MT5
      └─ Use EURUSD H1 or GBP USD H1 (high liquidity)
      └─ Set AllowLiveTrading = true (properties dialog)

[ ] 3. Configure Python heartbeat writing
      └─ Add _update_heartbeat() to engine/main.py
      └─ Verify file appears: .heartbeat (check every cycle)

[ ] 4. Test in demo account first
      └─ Verify heartbeat detection works
      └─ Simulate Python crash (delete .heartbeat)
      └─ Verify failsafe triggers immediately

[ ] 5. Verify log output
      └─ Check MT5 journal tab
      └─ Check failsafe_YYYY-MM-DD.log file

[ ] 6. Move to live account
      └─ Use same config, only change trading symbols
```

### 11.2 Testing Scenarios

**Scenario 1: Python Crash Simulation**
```
1. Start Python + EA, let it run for 30 seconds
2. Kill python.exe or pause start_ustat.py
3. Wait for heartbeat timeout (30 sec default)
4. Verify:
   - EA detects stale heartbeat
   - All positions closed
   - failsafe_YYYY-MM-DD.log shows timestamps
   - MT5 journal shows "FAILSAFE ACTIVATED"
```

**Scenario 2: Drawdown Trigger**
```
1. Open some losing positions manually
2. Reduce MaxDailyDrawdownPercent to trigger threshold
3. Verify:
   - EA calculates correct drawdown%
   - Closes all positions when threshold breached
   - Log shows timestamp
```

**Scenario 3: EOD Closure**
```
1. Set system time to 17:44
2. Let EA run timer check
3. At 17:45, verify:
   - All positions closed
   - eod_closure_executed flag set
   - Log shows EOD event
```

### 11.3 Integration with Python

**In `engine/main.py`:**

```python
import os
from datetime import datetime

def _update_heartbeat(self):
    """Write heartbeat file for MQL5 failsafe EA to monitor"""
    heartbeat_file = os.path.join(
        self.ustat_root,
        ".heartbeat"
    )

    try:
        timestamp = datetime.utcnow().isoformat()

        # Atomic write: write to temp, then rename
        temp_file = heartbeat_file + ".tmp"
        with open(temp_file, "w") as f:
            f.write(timestamp)

        # Atomic rename
        if os.path.exists(heartbeat_file):
            os.remove(heartbeat_file)
        os.rename(temp_file, heartbeat_file)

        return True
    except Exception as e:
        self.logger.error(f"Heartbeat write failed: {e}")
        return False

async def _run_single_cycle(self):
    """Main 10-second trading cycle"""

    try:
        # ... existing 4-motor code ...
        # BABA, OĞUL, H-Engine, ÜSTAT

        # At END of cycle, ALWAYS update heartbeat
        self._update_heartbeat()

    except Exception as e:
        self.logger.error(f"Cycle failed: {e}")
        # Even on error, try heartbeat
        self._update_heartbeat()
```

---

## SECTION 12: RISK ASSESSMENT & LIMITATIONS

### 12.1 What MQL5 Failsafe CAN Do

✓ Detect Python process death via heartbeat timeout
✓ Close ALL positions immediately on threshold breach
✓ Enforce time-based position closure (17:45 EOD)
✓ Monitor account equity and drawdown continuously
✓ Manage trailing stops independently
✓ Generate alerts and logs
✓ Survive Python crashes (runs inside MT5 terminal)
✓ Place new orders if configured (market orders, pending)

### 12.2 What MQL5 Failsafe CANNOT Do

✗ Parse complex Python logic or signals
✗ Access Python databases (trades.db, ustat.db)
✗ Modify Python settings or config dynamically
✗ Sync position state between systems perfectly (eventual consistency)
✗ Prevent orders already in flight (only prevents new ones)
✗ Handle multi-symbol coordination across sessions
✗ Access external APIs that Python uses (news, custom data)

### 12.3 Edge Cases & Risks

| Risk | Mitigation |
|------|-----------|
| **Double closure** (Python + MQL5 close same position) | Both send market order - broker rejects duplicate, no harm |
| **SL/TP modification race** (Python modifies while MQL5 trying) | Use timeout on MT5 calls, accept first success |
| **File system latency** | Write heartbeat to disk atomically, poll frequently (5-10s) |
| **Time skew** (computer clock wrong) | Use `TimeCurrent()` (broker time) not `TimeLocal()` |
| **Broker requote** | Use ORDER_FILLING_IOC (immediate or cancel, no slippage) |
| **Network lag** | 8-second timeout on MT5 API calls, with retries |

---

## SECTION 13: RECOMMENDED ARCHITECTURE

### 13.1 Optimal Multi-Layer Safety

```
Layer 1: Python (Primary Decision Maker)
├─ BABA: Risk checks
├─ OĞUL: Signals + position management
├─ H-Engine: Trailing stops
└─ Check points: can_trade, drawdown checks

     ↓ (writes .heartbeat every 10 sec)

Layer 2: MQL5 EA (Failsafe Guardian)
├─ OnTimer every 5 seconds
├─ Check heartbeat (L1 failsafe)
├─ Check drawdown (L2 failsafe)
├─ Check EOD time (L3 failsafe)
└─ Action: Close all positions if thresholds breach
            OR if heartbeat dies

     ↓

Layer 3: Manual Kill-Switch (Human Override)
└─ Dashboard button / API endpoint
   → Triggers graceful shutdown OR emergency close
```

### 13.2 Communication Flow

```
Python Engine                      MT5 Terminal
├── Cycle 1 (10s)                  ├── EA OnInit
│   ├─ Heartbeat: 2026-04-01T10:00:00Z
│   └─ Trade 1, Trade 2
│
├── Cycle 2 (20s)                  ├── Timer 1 (5s)
│   ├─ Heartbeat: 2026-04-01T10:00:10Z
│   └─ Trade 3
│
├── Cycle 3 (30s)                  ├── Timer 2 (10s)
│   ├─ Heartbeat: 2026-04-01T10:00:20Z ←── Read: Fresh ✓
│   └─ Trade 4
│
├── CRASH 💥                         ├── Timer 3 (15s)
│  (Python stops)                    │   (Can't read: .heartbeat gone)
│
│                                   ├── Timer 4 (20s)
│                                   │   Timeout: 20s - Still fresh
│                                   │
│                                   ├── Timer 5 (25s)
│                                   │   Timeout: 25s - Still fresh
│                                   │
│                                   ├── Timer 6 (30s)
│                                   │   Timeout: 30s ← THRESHOLD!
│                                   │   ACTION: Close all positions
│                                   │   Alert: "FAILSAFE ACTIVATED"
```

---

## SECTION 14: SOURCES & REFERENCES

**Order Management:**
- [Order Strategies. Multi-Purpose Expert Advisor](https://www.mql5.com/en/articles/495)
- [What Are Expert Advisors in MetaTrader 5](https://justmarkets.com/trading-articles/learning/what-are-expert-advisors-eas-in-metatrader-5)

**Trailing Stops:**
- [How to Create Your Own Trailing Stop](https://www.mql5.com/en/articles/134)
- [How to develop any type of Trailing Stop](https://www.mql5.com/en/articles/14862)

**Position Management:**
- [PositionClose() - Trade Classes](https://www.mql5.com/en/docs/standardlibrary/tradeclasses/ctrade/ctradepositionclose)
- [Getting the list of positions](https://www.mql5.com/en/book/automation/experts/experts_position_list)

**Account Info:**
- [AccountInfoDouble](https://www.mql5.com/en/docs/account/accountinfodouble)
- [Account Properties](https://www.mql5.com/en/docs/constants/environment_state/accountinformation)

**Time-Based Operations:**
- [Simple EA closing all trades at specific time](https://www.mql5.com/en/forum/280588)
- [Learn how to deal with date and time in MQL5](https://www.mql5.com/en/articles/13466)

**Drawdown Monitoring:**
- [Drawdown Limiter User Guide](https://www.mql5.com/en/blogs/post/752215)

**Heartbeat & Failsafe:**
- [How to Catch VPS Crashes Automatically](https://www.mql5.com/en/blogs/post/765973)
- [MT5 Monitoring Heartbeat](https://www.mql5.com/en/market/product/96473)

**Events & Timers:**
- [OnTimer Event Handling](https://www.mql5.com/en/docs/event_handlers/ontimer)
- [OnTick Event Handling](https://www.mql5.com/en/docs/event_handlers/ontick)

**Services vs Expert Advisors:**
- [Services - Creating application programs](https://www.mql5.com/en/book/applications/script_service/services)

---

## CONCLUSION

**MQL5 Expert Advisors are a robust, proven technology for implementing a failsafe/backup layer for Python trading systems.** The architecture outlined in this research provides:

1. **Heartbeat Detection** - Monitors Python process every 5-10 seconds
2. **Automatic Position Closure** - Can close all positions in <1 second
3. **Drawdown Monitoring** - Independent threshold enforcement
4. **Time-Based Closure** - EOD closure at specific times
5. **Complete Independence** - Runs in MT5, survives Python crashes
6. **Simplicity** - ~300-400 lines of MQL5 code

**Recommended next steps:**
1. Code the failsafe EA using template in Section 10
2. Test in demo account (Sections 11.2)
3. Integrate heartbeat writing in Python (Section 11.3)
4. Deploy on live account with monitoring

**Estimated implementation time:** 4-6 hours (code + testing)

---

**End of Research Document**
