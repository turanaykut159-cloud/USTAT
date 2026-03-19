"""
ÜSTAT v5.5 — MT5 Bridge Sağlık Testi
=====================================
Tüm MT5 API yollarını _safe_call lambda fix üzerinden test eder.
Emir göndermez, sadece okuma + doğrulama yapar.

Kullanım: python health_check.py
"""

import sys
import os
import time
from datetime import datetime, timedelta

# ÜSTAT root'u ekle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import MetaTrader5 as mt5

# ─── Renkli çıktı ───
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"

passed = 0
failed = 0
warnings = 0

def ok(msg):
    global passed
    passed += 1
    print(f"  {GREEN}✓{RESET} {msg}")

def fail(msg):
    global failed
    failed += 1
    print(f"  {RED}✗{RESET} {msg}")

def warn(msg):
    global warnings
    warnings += 1
    print(f"  {YELLOW}⚠{RESET} {msg}")

def header(title):
    print(f"\n{BOLD}{CYAN}{'─'*50}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─'*50}{RESET}")


# ═══════════════════════════════════════════════════
# TEST 1: MT5 Bağlantı
# ═══════════════════════════════════════════════════
header("TEST 1: MT5 Bağlantı")

if not mt5.initialize():
    fail(f"mt5.initialize() başarısız: {mt5.last_error()}")
    print(f"\n{RED}MT5 bağlantısı kurulamadı, testler durduruluyor.{RESET}")
    sys.exit(1)

ok("mt5.initialize() başarılı")

info = mt5.terminal_info()
if info:
    ok(f"terminal_info: build={info.build}, connected={info.connected}")
else:
    fail("terminal_info döndüremedi")

acc = mt5.account_info()
if acc:
    ok(f"account_info: login={acc.login}, balance={acc.balance}, equity={acc.equity}")
else:
    fail("account_info döndüremedi")


# ═══════════════════════════════════════════════════
# TEST 2: _safe_call Lambda Fix (ThreadPoolExecutor)
# ═══════════════════════════════════════════════════
header("TEST 2: _safe_call Lambda Fix")

import concurrent.futures

def safe_call_test(func, *args, **kwargs):
    """_safe_call ile aynı mantık — lambda wrapper."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(lambda: func(*args, **kwargs))
        return future.result(timeout=10.0)

# 2a: symbol_info — positional
try:
    result = safe_call_test(mt5.symbol_info, "F_XU030")
    if result:
        ok(f"symbol_info('F_XU030') via lambda: {result.name}, point={result.point}")
    else:
        fail("symbol_info('F_XU030') None döndü")
except Exception as e:
    fail(f"symbol_info via lambda hata: {e}")

# 2b: symbol_info_tick — positional
try:
    result = safe_call_test(mt5.symbol_info_tick, "F_XU030")
    if result:
        ok(f"symbol_info_tick('F_XU030') via lambda: bid={result.bid}, ask={result.ask}")
    else:
        fail("symbol_info_tick('F_XU030') None döndü")
except Exception as e:
    fail(f"symbol_info_tick via lambda hata: {e}")

# 2c: copy_rates_from_pos — positional
try:
    result = safe_call_test(mt5.copy_rates_from_pos, "F_XU030", mt5.TIMEFRAME_M1, 0, 10)
    if result is not None and len(result) > 0:
        ok(f"copy_rates_from_pos('F_XU030', M1, 0, 10) via lambda: {len(result)} bar")
    else:
        fail("copy_rates_from_pos None veya boş döndü")
except Exception as e:
    fail(f"copy_rates_from_pos via lambda hata: {e}")

# 2d: symbol_select — positional
try:
    result = safe_call_test(mt5.symbol_select, "F_XU030", True)
    if result:
        ok("symbol_select('F_XU030', True) via lambda: True")
    else:
        warn("symbol_select('F_XU030', True) False döndü (zaten seçili olabilir)")
except Exception as e:
    fail(f"symbol_select via lambda hata: {e}")

# 2e: positions_get — keyword
try:
    result = safe_call_test(mt5.positions_get)
    if result is not None:
        ok(f"positions_get() via lambda: {len(result)} açık pozisyon")
        for pos in result:
            print(f"       └─ ticket={pos.ticket}, symbol={pos.symbol}, volume={pos.volume}, profit={pos.profit}")
    else:
        ok("positions_get() via lambda: 0 pozisyon (None=boş)")
except Exception as e:
    fail(f"positions_get via lambda hata: {e}")

# 2f: positions_get with keyword — symbol filter
try:
    result = safe_call_test(mt5.positions_get, symbol="F_ASELS")
    if result is not None:
        ok(f"positions_get(symbol='F_ASELS') via lambda: {len(result)} pozisyon")
    else:
        ok("positions_get(symbol='F_ASELS') via lambda: 0 pozisyon")
except Exception as e:
    fail(f"positions_get(symbol=) via lambda hata: {e}")

# 2g: orders_get — keyword
try:
    result = safe_call_test(mt5.orders_get)
    if result is not None:
        ok(f"orders_get() via lambda: {len(result)} bekleyen emir")
    else:
        ok("orders_get() via lambda: 0 emir")
except Exception as e:
    fail(f"orders_get via lambda hata: {e}")

# 2h: history_deals_get — positional (date_from, date_to)
try:
    date_from = datetime.now() - timedelta(days=1)
    date_to = datetime.now() + timedelta(hours=1)
    result = safe_call_test(mt5.history_deals_get, date_from, date_to)
    if result is not None:
        ok(f"history_deals_get(date_from, date_to) via lambda: {len(result)} deal")
    else:
        ok("history_deals_get: 0 deal (None=boş)")
except Exception as e:
    fail(f"history_deals_get via lambda hata: {e}")

# 2i: history_orders_get — keyword (ticket)
try:
    # Var olmayan ticket ile test — hata vermemeli, boş dönmeli
    result = safe_call_test(mt5.history_orders_get, ticket=999999999)
    ok(f"history_orders_get(ticket=999999999) via lambda: {'boş' if result is None or len(result)==0 else f'{len(result)} order'}")
except Exception as e:
    fail(f"history_orders_get(ticket=) via lambda hata: {e}")


# ═══════════════════════════════════════════════════
# TEST 3: order_send Doğrulama (KURU TEST - Emir göndermez)
# ═══════════════════════════════════════════════════
header("TEST 3: order_send Lambda Fix (Kuru Test)")

# order_check ile test — gerçek emir göndermez
try:
    symbol_info = mt5.symbol_info("F_ASELS")
    if symbol_info:
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": "F_ASELS",
            "volume": 1.0,
            "type": mt5.ORDER_TYPE_BUY,
            "price": symbol_info.ask if symbol_info.ask > 0 else symbol_info.last,
            "deviation": 20,
            "magic": 55555,
            "comment": "USTAT_HEALTH_CHECK",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        # order_check — emir göndermeden doğrulama
        check_result = safe_call_test(mt5.order_check, request)
        if check_result:
            ok(f"order_check via lambda: retcode={check_result.retcode}, comment='{check_result.comment}'")
            if check_result.retcode == 0:
                ok("order_check PASSED — emir geçerli, gönderilebilir durumda")
            elif check_result.retcode == 10014:
                warn(f"order_check: Geçersiz fiyat (piyasa kapalı olabilir)")
            elif check_result.retcode == 10019:
                warn(f"order_check: Yetersiz bakiye")
            else:
                warn(f"order_check retcode={check_result.retcode} — piyasa durumuna bağlı olabilir")
        else:
            fail("order_check None döndü")

        # order_send via lambda — sadece yapıyı test et
        # ThreadPoolExecutor üzerinden geçtiğini doğrula
        print(f"\n  {CYAN}ℹ order_send yapı testi (emir GÖNDERİLMEZ):{RESET}")

        # Lambda'nın argümanları doğru geçirdiğini kontrol et
        def mock_order_send(req):
            """order_send yerine çağrılacak — argüman tipini kontrol eder."""
            if isinstance(req, dict):
                return f"OK: dict alındı, {len(req)} key"
            else:
                return f"HATA: beklenen dict, gelen {type(req)}"

        mock_result = safe_call_test(mock_order_send, request)
        if "OK" in str(mock_result):
            ok(f"Lambda argüman geçişi: {mock_result}")
        else:
            fail(f"Lambda argüman geçişi: {mock_result}")
    else:
        warn("F_ASELS symbol_info alınamadı — sembol listede olmayabilir")
except Exception as e:
    fail(f"order_send yapı testi hata: {e}")


# ═══════════════════════════════════════════════════
# TEST 4: ÜSTAT _safe_call Entegrasyonu
# ═══════════════════════════════════════════════════
header("TEST 4: ÜSTAT MT5Bridge _safe_call Entegrasyonu")

try:
    from engine.mt5_bridge import MT5Bridge
    bridge = MT5Bridge.__new__(MT5Bridge)

    # _safe_call'ın lambda kullandığını doğrula
    import inspect
    source = inspect.getsource(bridge._safe_call)

    if "lambda:" in source and "func(*args, **kwargs)" in source:
        ok("_safe_call lambda fix mevcut: executor.submit(lambda: func(*args, **kwargs))")
    elif "executor.submit(func," in source:
        fail("_safe_call ESKİ SÜRÜM — lambda fix YOK! executor.submit(func, ...) kullanıyor")
    else:
        warn("_safe_call yapısı beklenenden farklı — manuel kontrol gerekli")

    # Timeout parametresi kontrolü
    if "timeout: float" in source:
        ok("_safe_call timeout parametresi mevcut")
    else:
        warn("_safe_call timeout parametresi bulunamadı")

    # Circuit breaker kontrolü
    if "_cb_is_open" in source:
        ok("Circuit breaker kontrolü mevcut")
    else:
        warn("Circuit breaker kontrolü bulunamadı")

except Exception as e:
    fail(f"ÜSTAT MT5Bridge import/kontrol hatası: {e}")


# ═══════════════════════════════════════════════════
# TEST 5: Tüm Semboller Erişim Testi
# ═══════════════════════════════════════════════════
header("TEST 5: Sembol Erişim Testi")

USTAT_SYMBOLS = [
    "F_XU030", "F_ASELS", "F_TCELL", "F_TKFEN", "F_EKGYO",
    "F_AKBNK", "F_HALKB", "F_THYAO", "F_GUBRF", "F_OYAKC",
    "F_KONTR", "F_AKSEN", "F_ASTOR", "F_BRSAN", "F_TUPRS"
]

symbol_errors = []
for sym in USTAT_SYMBOLS:
    try:
        info = safe_call_test(mt5.symbol_info, sym)
        tick = safe_call_test(mt5.symbol_info_tick, sym)
        rates = safe_call_test(mt5.copy_rates_from_pos, sym, mt5.TIMEFRAME_M1, 0, 5)

        issues = []
        if not info:
            issues.append("info=None")
        if not tick:
            issues.append("tick=None")
        if rates is None or len(rates) == 0:
            issues.append("rates=boş")

        if issues:
            warn(f"{sym}: {', '.join(issues)}")
            symbol_errors.append(sym)
        else:
            spread = round(tick.ask - tick.bid, 4) if tick.ask > 0 else "N/A"
            ok(f"{sym}: info✓ tick✓ rates✓ (bid={tick.bid}, spread={spread})")
    except Exception as e:
        fail(f"{sym}: {e}")
        symbol_errors.append(sym)

if not symbol_errors:
    ok(f"Tüm {len(USTAT_SYMBOLS)} sembol erişilebilir")


# ═══════════════════════════════════════════════════
# SONUÇ
# ═══════════════════════════════════════════════════
header("SONUÇ")

total = passed + failed + warnings
print(f"""
  {GREEN}Başarılı : {passed}{RESET}
  {RED}Başarısız: {failed}{RESET}
  {YELLOW}Uyarı    : {warnings}{RESET}
  ─────────────
  Toplam   : {total}
""")

if failed == 0:
    print(f"  {GREEN}{BOLD}═══ TÜM KRİTİK TESTLER GEÇTİ ═══{RESET}")
    print(f"  {GREEN}Lambda fix çalışıyor. Piyasa açıkken emir testi yapılabilir.{RESET}")
elif failed <= 2:
    print(f"  {YELLOW}{BOLD}═══ KÜÇÜK SORUNLAR VAR ═══{RESET}")
    print(f"  {YELLOW}Yukarıdaki başarısız testleri inceleyin.{RESET}")
else:
    print(f"  {RED}{BOLD}═══ KRİTİK HATALAR VAR ═══{RESET}")
    print(f"  {RED}Sistem canlıya alınmamalı! Hataları düzeltin.{RESET}")

mt5.shutdown()
print()
