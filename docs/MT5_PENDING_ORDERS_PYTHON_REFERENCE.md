# MT5 Pending Orders - Complete Python API Reference
**Exchange Execution Mode - Real Money Trading**

---

## EXECUTIVE SUMMARY

This document provides the EXACT Python API format for MT5 pending orders (Buy Stop Limit, Sell Stop Limit, Buy Stop, Sell Stop, Buy Limit, Sell Limit) based on MQL5 official documentation. All field names, types, and requirements are specified for GCM Capital VİOP exchange execution.

---

## 1. ORDER FIELD REFERENCE

### 1.1 Trade Request Dictionary Structure

All MT5 order operations use a Python dictionary with the following possible fields:

| Field | Type | TRADE_ACTION_DEAL | TRADE_ACTION_PENDING | TRADE_ACTION_MODIFY | TRADE_ACTION_SLTP | Notes |
|-------|------|:-:|:-:|:-:|:-:|-------|
| `action` | int | **REQUIRED** | **REQUIRED** | **REQUIRED** | **REQUIRED** | mt5.TRADE_ACTION_* constant |
| `magic` | int | Optional | Optional | Optional | Optional | Expert Advisor ID (default 0) |
| `order` | int | N/A | N/A | **REQUIRED** | **REQUIRED** | Ticket of order to modify/close |
| `symbol` | str | **REQUIRED** | **REQUIRED** | Optional* | **REQUIRED** | Trading instrument symbol |
| `volume` | float | **REQUIRED** | **REQUIRED** | Optional | N/A | Lot size (0.01 to max allowed) |
| `price` | float | **REQUIRED** | **REQUIRED** | Optional | N/A | Entry price (for PENDING: trigger/stop price) |
| `stoplimit` | float | N/A | Conditional** | Optional | N/A | Limit price for *_STOP_LIMIT orders only |
| `sl` | float | Optional | Optional | Optional | Optional | Stop loss price (0 = none) |
| `tp` | float | Optional | Optional | Optional | Optional | Take profit price (0 = none) |
| `deviation` | int | Optional | Optional | N/A | N/A | Max price deviation (points, default 10) |
| `type` | int | **REQUIRED** | **REQUIRED** | Optional | N/A | ORDER_TYPE_* constant |
| `type_filling` | int | Optional | Optional | N/A | N/A | ORDER_FILLING_* constant (default ORDER_FILLING_RETURN) |
| `type_time` | int | Optional | Optional | N/A | N/A | ORDER_TIME_* constant |
| `expiration` | int | N/A | Optional | N/A | N/A | Unix timestamp (required for ORDER_TIME_SPECIFIED) |
| `comment` | str | Optional | Optional | Optional | Optional | Max 32 characters |

**Notes:**
- **REQUIRED: Must be specified**
- **Optional: Can be 0/None or omitted**
- **Conditional**: Required ONLY for ORDER_TYPE_BUY_STOP_LIMIT and ORDER_TYPE_SELL_STOP_LIMIT
- *For TRADE_ACTION_MODIFY: symbol can be omitted if order ticket uniquely identifies it

---

## 2. ORDER TYPE CONSTANTS

### 2.1 Market Orders (Immediate Execution)

```python
import MetaTrader5 as mt5

mt5.ORDER_TYPE_BUY       # Market buy
mt5.ORDER_TYPE_SELL      # Market sell
```

### 2.2 Pending Orders (Conditional Execution)

```python
mt5.ORDER_TYPE_BUY_LIMIT       # Buy when price <= limit
mt5.ORDER_TYPE_SELL_LIMIT      # Sell when price >= limit
mt5.ORDER_TYPE_BUY_STOP        # Buy when price >= stop
mt5.ORDER_TYPE_SELL_STOP       # Sell when price <= stop
mt5.ORDER_TYPE_BUY_STOP_LIMIT  # 2-stage: trigger stop → place limit
mt5.ORDER_TYPE_SELL_STOP_LIMIT # 2-stage: trigger stop → place limit
```

---

## 3. COMPLETE ORDER EXAMPLES

### 3.1 BUY STOP LIMIT - PYTHON EXACT FORMAT

**Logic:** When ASK price ≥ `price` (stop trigger), place a BUY LIMIT at `stoplimit`

**Constraint:** `stoplimit < price` (limit MUST be below stop trigger)

```python
import MetaTrader5 as mt5
import datetime

mt5.initialize()

# Example: Buy 1 lot of UEUSOD futures
# When price hits 22.50 (stop), place buy limit at 22.40

request = {
    "action": mt5.TRADE_ACTION_PENDING,          # Pending order
    "symbol": "UEUSOD",                          # Symbol
    "volume": 1.0,                               # Lot size (1.0 = 1 contract)
    "type": mt5.ORDER_TYPE_BUY_STOP_LIMIT,       # Buy stop limit
    "price": 22.50,                              # STOP trigger price (Ask)
    "stoplimit": 22.40,                          # LIMIT price (execution target)
    "sl": 22.30,                                 # Stop loss (optional)
    "tp": 22.70,                                 # Take profit (optional)
    "deviation": 10,                             # Max slippage (points)
    "type_filling": mt5.ORDER_FILLING_RETURN,    # Return unfilled volume (exchange mode)
    "type_time": mt5.ORDER_TIME_GTC,             # Good till canceled
    "magic": 12345,                              # Expert ID
    "comment": "Buy BSL at 22.50/22.40"
}

result = mt5.order_send(request)

if result.retcode == mt5.TRADE_RETCODE_DONE:
    print(f"Order placed: {result.order}")
else:
    print(f"Error: {result.comment}")
```

**Field Meanings:**
- `price=22.50`: The STOP trigger level (when Ask touches this, order activates)
- `stoplimit=22.40`: The LIMIT price once activated (will fill at ≤22.40)

---

### 3.2 SELL STOP LIMIT - PYTHON EXACT FORMAT

**Logic:** When BID price ≤ `price` (stop trigger), place a SELL LIMIT at `stoplimit`

**Constraint:** `stoplimit > price` (limit MUST be above stop trigger)

```python
import MetaTrader5 as mt5

mt5.initialize()

# Example: Sell 1 lot of UEUSOD futures
# When price hits 22.50 (stop), place sell limit at 22.60

request = {
    "action": mt5.TRADE_ACTION_PENDING,
    "symbol": "UEUSOD",
    "volume": 1.0,
    "type": mt5.ORDER_TYPE_SELL_STOP_LIMIT,      # Sell stop limit
    "price": 22.50,                              # STOP trigger price (Bid)
    "stoplimit": 22.60,                          # LIMIT price (execution target)
    "sl": 22.70,                                 # Stop loss
    "tp": 22.30,                                 # Take profit
    "deviation": 10,
    "type_filling": mt5.ORDER_FILLING_RETURN,
    "type_time": mt5.ORDER_TIME_GTC,
    "magic": 12346,
    "comment": "Sell SSL at 22.50/22.60"
}

result = mt5.order_send(request)
```

**Field Meanings:**
- `price=22.50`: The STOP trigger level (when Bid touches this, order activates)
- `stoplimit=22.60`: The LIMIT price once activated (will fill at ≥22.60)

---

### 3.3 BUY STOP - PYTHON EXACT FORMAT

**Logic:** When ASK price ≥ `price`, place a market BUY order immediately

```python
import MetaTrader5 as mt5

mt5.initialize()

# Example: Buy 1 lot when price breaks above 22.50

request = {
    "action": mt5.TRADE_ACTION_PENDING,
    "symbol": "UEUSOD",
    "volume": 1.0,
    "type": mt5.ORDER_TYPE_BUY_STOP,             # Buy stop (no stoplimit needed)
    "price": 22.50,                              # STOP trigger price
    # NOTE: NO stoplimit field for simple stops
    "sl": 22.30,
    "tp": 22.70,
    "deviation": 10,
    "type_filling": mt5.ORDER_FILLING_RETURN,
    "type_time": mt5.ORDER_TIME_GTC,
    "magic": 12347,
    "comment": "Buy Stop at 22.50"
}

result = mt5.order_send(request)
```

---

### 3.4 SELL STOP - PYTHON EXACT FORMAT

**Logic:** When BID price ≤ `price`, place a market SELL order immediately

```python
import MetaTrader5 as mt5

mt5.initialize()

# Example: Sell 1 lot when price breaks below 22.50

request = {
    "action": mt5.TRADE_ACTION_PENDING,
    "symbol": "UEUSOD",
    "volume": 1.0,
    "type": mt5.ORDER_TYPE_SELL_STOP,            # Sell stop
    "price": 22.50,                              # STOP trigger price
    # NOTE: NO stoplimit field for simple stops
    "sl": 22.70,
    "tp": 22.30,
    "deviation": 10,
    "type_filling": mt5.ORDER_FILLING_RETURN,
    "type_time": mt5.ORDER_TIME_GTC,
    "magic": 12348,
    "comment": "Sell Stop at 22.50"
}

result = mt5.order_send(request)
```

---

### 3.5 BUY LIMIT - PYTHON EXACT FORMAT

**Logic:** When ASK price ≤ `price`, place a market BUY order

```python
import MetaTrader5 as mt5

mt5.initialize()

# Example: Buy 1 lot when price drops to 22.40

request = {
    "action": mt5.TRADE_ACTION_PENDING,
    "symbol": "UEUSOD",
    "volume": 1.0,
    "type": mt5.ORDER_TYPE_BUY_LIMIT,            # Buy limit
    "price": 22.40,                              # LIMIT price (execution target)
    # NOTE: NO stoplimit field for simple limits
    "sl": 22.30,
    "tp": 22.70,
    "deviation": 10,
    "type_filling": mt5.ORDER_FILLING_RETURN,
    "type_time": mt5.ORDER_TIME_GTC,
    "magic": 12349,
    "comment": "Buy Limit at 22.40"
}

result = mt5.order_send(request)
```

---

### 3.6 SELL LIMIT - PYTHON EXACT FORMAT

**Logic:** When BID price ≥ `price`, place a market SELL order

```python
import MetaTrader5 as mt5

mt5.initialize()

# Example: Sell 1 lot when price rises to 22.60

request = {
    "action": mt5.TRADE_ACTION_PENDING,
    "symbol": "UEUSOD",
    "volume": 1.0,
    "type": mt5.ORDER_TYPE_SELL_LIMIT,           # Sell limit
    "price": 22.60,                              # LIMIT price (execution target)
    # NOTE: NO stoplimit field for simple limits
    "sl": 22.70,
    "tp": 22.30,
    "deviation": 10,
    "type_filling": mt5.ORDER_FILLING_RETURN,
    "type_time": mt5.ORDER_TIME_GTC,
    "magic": 12350,
    "comment": "Sell Limit at 22.60"
}

result = mt5.order_send(request)
```

---

## 4. MODIFYING PENDING ORDERS

### 4.1 Modify Pending Order Price (TRADE_ACTION_MODIFY)

**Use Case:** Change the trigger price or limit price of an existing pending order

```python
import MetaTrader5 as mt5

mt5.initialize()

# Modify existing order ticket 12345
# Change stop trigger from 22.50 to 22.55

request = {
    "action": mt5.TRADE_ACTION_MODIFY,
    "order": 12345,                              # Existing order ticket (REQUIRED)
    "price": 22.55,                              # NEW stop/limit price
    "stoplimit": 22.45,                          # NEW limit (for *_STOP_LIMIT only)
    "sl": 22.35,                                 # NEW stop loss (optional)
    "tp": 22.75,                                 # NEW take profit (optional)
    "type_time": mt5.ORDER_TIME_GTC,
    "expiration": 0,                             # Keep current expiration
    "comment": "Modified BSL to 22.55/22.45"
}

result = mt5.order_send(request)
```

**IMPORTANT:**
- You CANNOT change order type (BUY→SELL, STOP→LIMIT, etc.)
- You CANNOT change volume
- You CAN change price, stoplimit, sl, tp, expiration

---

### 4.2 Cancel Pending Order (TRADE_ACTION_REMOVE)

**Use Case:** Delete a pending order entirely

```python
import MetaTrader5 as mt5

mt5.initialize()

# Cancel order ticket 12345

request = {
    "action": mt5.TRADE_ACTION_REMOVE,
    "order": 12345,                              # Ticket to cancel (REQUIRED)
    "comment": "Cancelled BSL order"
}

result = mt5.order_send(request)
```

---

## 5. ORDER FILLING TYPES (type_filling)

### 5.1 For Exchange Execution (GCM Capital VİOP)

```python
# Exchange execution: ALWAYS use ORDER_FILLING_RETURN for pending orders
mt5.ORDER_FILLING_RETURN    # Partial fills allowed, rest becomes pending
                             # (default for exchange mode)

# Market execution: OTHER options
mt5.ORDER_FILLING_FOK       # Fill or Kill (all or nothing)
mt5.ORDER_FILLING_IOC       # Immediate or Cancel (fill what possible, cancel rest)
```

**For VİOP Exchange:** Use `ORDER_FILLING_RETURN` for all pending orders. The exchange will handle partial fills appropriately.

---

## 6. ORDER TIME TYPES (type_time)

### 6.1 Expiration Modes for Pending Orders

```python
mt5.ORDER_TIME_GTC         # Good Till Canceled (no expiration)
mt5.ORDER_TIME_DAY         # Good Till End of Day (expires at session close)
mt5.ORDER_TIME_SPECIFIED   # Custom expiration (requires 'expiration' timestamp)
mt5.ORDER_TIME_SPECIFIED_DAY  # Expires at specific date + EOD
```

**Example with ORDER_TIME_SPECIFIED:**

```python
import MetaTrader5 as mt5
import datetime
import time

mt5.initialize()

# Order expires in 2 hours
expiration_time = datetime.datetime.now() + datetime.timedelta(hours=2)
expiration_timestamp = int(time.mktime(expiration_time.timetuple()))

request = {
    "action": mt5.TRADE_ACTION_PENDING,
    "symbol": "UEUSOD",
    "volume": 1.0,
    "type": mt5.ORDER_TYPE_BUY_STOP_LIMIT,
    "price": 22.50,
    "stoplimit": 22.40,
    "type_time": mt5.ORDER_TIME_SPECIFIED,
    "expiration": expiration_timestamp,         # Unix timestamp
    "comment": "Expires in 2 hours"
}

result = mt5.order_send(request)
```

**IMPORTANT for GCM/VİOP:**
- Check SYMBOL_EXPIRATION_MODE property to confirm which modes are supported
- ORDER_TIME_GTC may not be supported on all exchange instruments
- Always test with a small order first

---

## 7. PRICE TRIGGER BEHAVIOR

### 7.1 Which Price Triggers Orders?

| Order Type | Exchange Execution | Trigger Price |
|-----------|:--------:|-----------|
| BUY_STOP, BUY_LIMIT | Exchange | **ASK** price (buy side) |
| SELL_STOP, SELL_LIMIT | Exchange | **BID** price (sell side) |
| BUY_STOP_LIMIT | Exchange | ASK (to trigger), then LIMIT execution |
| SELL_STOP_LIMIT | Exchange | BID (to trigger), then LIMIT execution |

**Note:** MT5 server handles the triggering, not the terminal. For futures (UEUSOD on VİOP), triggering uses the Last executed price, not Bid/Ask.

---

## 8. CRITICAL CONSTRAINTS

### 8.1 Buy Stop Limit Constraints

- `stoplimit < price` (limit MUST be below stop trigger)
- Example: Stop=22.50, Limit=22.40 VALID
- Example: Stop=22.50, Limit=22.60 INVALID

### 8.2 Sell Stop Limit Constraints

- `stoplimit > price` (limit MUST be above stop trigger)
- Example: Stop=22.50, Limit=22.60 VALID
- Example: Stop=22.50, Limit=22.40 INVALID

### 8.3 Minimum Distance (SYMBOL_TRADE_STOPS_LEVEL)

Check the symbol's SYMBOL_TRADE_STOPS_LEVEL property:

```python
# Check minimum distance requirement
symbol_info = mt5.symbol_info("UEUSOD")
min_distance = symbol_info.trade_stops_level

# If min_distance = 0: can place limit = stop price (immediate fill)
# If min_distance = 5: must have at least 5 points distance between stop and limit
```

---

## 9. RETURN VALUE STRUCTURE

```python
result = mt5.order_send(request)

# OrderSendResult contains:
result.retcode         # Return code (mt5.TRADE_RETCODE_DONE = success)
result.deal           # Deal ticket (if filled immediately)
result.order          # Order ticket (pending order ID)
result.volume         # Filled volume
result.price          # Fill price (market orders)
result.bid            # Bid price at request time
result.ask            # Ask price at request time
result.comment        # Broker response comment
result.request_id     # Request ID (async operations)
result.request        # Copy of original request dict

# Common return codes
mt5.TRADE_RETCODE_DONE              # 10009 - Success
mt5.TRADE_RETCODE_INVALID_PRICE     # 10015 - Invalid price
mt5.TRADE_RETCODE_INVALID_VOLUME    # 10014 - Invalid volume
mt5.TRADE_RETCODE_NO_MONEY          # 10019 - Insufficient margin
mt5.TRADE_RETCODE_PRICE_OFF         # 10020 - Price outside limits
mt5.TRADE_RETCODE_MARKET_CLOSED     # 10023 - Market closed
```

---

## 10. COMPLETE WORKING EXAMPLE FOR ÜSTAT

```python
import MetaTrader5 as mt5
import datetime
import time

class MT5OrderManager:

    def __init__(self):
        self.mt5 = mt5
        self.mt5.initialize()

    def place_buy_stop_limit(self, symbol, volume, stop_price, limit_price,
                             sl_price=None, tp_price=None, comment=""):
        """
        Place Buy Stop Limit order.

        Args:
            symbol: Trading symbol (e.g., "UEUSOD")
            volume: Lot size (e.g., 1.0)
            stop_price: Trigger price (when Ask reaches this, place limit)
            limit_price: Limit price (execution target, must be < stop_price)
            sl_price: Stop loss price (optional)
            tp_price: Take profit price (optional)
            comment: Order comment

        Returns:
            OrderSendResult or None if error
        """
        # Validation
        if limit_price >= stop_price:
            raise ValueError(f"BSL: limit ({limit_price}) must be < stop ({stop_price})")

        request = {
            "action": self.mt5.TRADE_ACTION_PENDING,
            "symbol": symbol,
            "volume": volume,
            "type": self.mt5.ORDER_TYPE_BUY_STOP_LIMIT,
            "price": stop_price,
            "stoplimit": limit_price,
            "sl": sl_price or 0,
            "tp": tp_price or 0,
            "deviation": 10,
            "type_filling": self.mt5.ORDER_FILLING_RETURN,
            "type_time": self.mt5.ORDER_TIME_GTC,
            "magic": 20260406,
            "comment": comment or f"BSL {symbol}"
        }

        result = self.mt5.order_send(request)

        if result.retcode != self.mt5.TRADE_RETCODE_DONE:
            print(f"ERROR: {result.comment}")
            return None

        print(f"SUCCESS: Order {result.order} placed at {stop_price}/{limit_price}")
        return result

    def modify_pending_order(self, order_ticket, new_price=None,
                            new_stoplimit=None, new_sl=None, new_tp=None):
        """Modify existing pending order."""

        request = {
            "action": self.mt5.TRADE_ACTION_MODIFY,
            "order": order_ticket,
            "type_time": self.mt5.ORDER_TIME_GTC,
        }

        if new_price is not None:
            request["price"] = new_price
        if new_stoplimit is not None:
            request["stoplimit"] = new_stoplimit
        if new_sl is not None:
            request["sl"] = new_sl
        if new_tp is not None:
            request["tp"] = new_tp

        result = self.mt5.order_send(request)

        if result.retcode != self.mt5.TRADE_RETCODE_DONE:
            print(f"ERROR: {result.comment}")
            return None

        print(f"SUCCESS: Order {order_ticket} modified")
        return result

    def cancel_order(self, order_ticket):
        """Cancel a pending order."""

        request = {
            "action": self.mt5.TRADE_ACTION_REMOVE,
            "order": order_ticket,
        }

        result = self.mt5.order_send(request)

        if result.retcode != self.mt5.TRADE_RETCODE_DONE:
            print(f"ERROR: {result.comment}")
            return None

        print(f"SUCCESS: Order {order_ticket} cancelled")
        return result


# USAGE EXAMPLE
if __name__ == "__main__":
    manager = MT5OrderManager()

    # Place a Buy Stop Limit order
    result = manager.place_buy_stop_limit(
        symbol="UEUSOD",
        volume=1.0,
        stop_price=22.50,      # Trigger when Ask reaches 22.50
        limit_price=22.40,     # Execute at max 22.40
        sl_price=22.30,        # Stop loss at 22.30
        tp_price=22.70,        # Take profit at 22.70
        comment="ÜSTAT BSL Order"
    )

    if result:
        order_ticket = result.order
        print(f"Order placed: {order_ticket}")

        # Later: modify the order
        manager.modify_pending_order(
            order_ticket,
            new_price=22.55,      # New stop trigger
            new_stoplimit=22.45   # New limit price
        )

        # Cancel if needed
        # manager.cancel_order(order_ticket)
```

---

## 11. SOURCES

- [MQL5 Trade Request Structure Documentation](https://www.mql5.com/en/docs/constants/structures/mqltraderequest)
- [MQL5 Order Types Reference](https://www.mql5.com/en/book/automation/experts/experts_order_type)
- [MQL5 Pending Order Placement](https://www.mql5.com/en/book/automation/experts/experts_pending)
- [MQL5 Python order_send Documentation](https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py)
- [MetaTrader 5 Order Execution Logic](https://faq.ampfutures.com/hc/en-us/articles/360008946513-MetaTrader-5-Order-Types-Order-Execution-Logic)
- [Trade Request Operation Types](https://www.mql5.com/en/docs/constants/tradingconstants/enum_trade_request_actions)
- [Modifying Pending Orders](https://www.mql5.com/en/book/automation/experts/experts_modify_order)
- [Order Filling Types](https://www.mql5.com/en/book/automation/experts/experts_execution_filling)
- [Pending Order Expiration Rules](https://www.mql5.com/en/book/automation/symbols/symbols_expiration)

---

## APPENDIX: QUICK REFERENCE TABLE

| Operation | action | type | Required Fields | Optional Fields |
|-----------|--------|------|-----------------|-----------------|
| Buy Stop Limit | TRADE_ACTION_PENDING | ORDER_TYPE_BUY_STOP_LIMIT | symbol, volume, price, stoplimit | sl, tp, comment, magic |
| Sell Stop Limit | TRADE_ACTION_PENDING | ORDER_TYPE_SELL_STOP_LIMIT | symbol, volume, price, stoplimit | sl, tp, comment, magic |
| Buy Stop | TRADE_ACTION_PENDING | ORDER_TYPE_BUY_STOP | symbol, volume, price | stoplimit*, sl, tp, comment |
| Sell Stop | TRADE_ACTION_PENDING | ORDER_TYPE_SELL_STOP | symbol, volume, price | stoplimit*, sl, tp, comment |
| Buy Limit | TRADE_ACTION_PENDING | ORDER_TYPE_BUY_LIMIT | symbol, volume, price | stoplimit*, sl, tp, comment |
| Sell Limit | TRADE_ACTION_PENDING | ORDER_TYPE_SELL_LIMIT | symbol, volume, price | stoplimit*, sl, tp, comment |
| Modify | TRADE_ACTION_MODIFY | N/A | order | price, stoplimit, sl, tp |
| Cancel | TRADE_ACTION_REMOVE | N/A | order | (none) |

*stoplimit should NOT be filled for simple stops/limits (will cause error if present)
