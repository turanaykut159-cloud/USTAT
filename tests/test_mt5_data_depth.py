"""
MT5 Veri Derinliği Test Scripti
================================
TEST 1: Market book + tick verisi temel analizi
TEST 2: Ek veri derinliği kontrolleri (zaman hassasiyeti, flag
        kombinasyonları, çoklu kontrat, volume dağılımı,
        gün içi frekans, spread dağılımı, performans)
Sadece OKUMA yapar, emir göndermez.
"""

import sys
import time as time_module
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime, timedelta, timezone

BASE_SYMBOL = "F_THYAO"
MULTI_SYMBOLS = ["F_THYAO", "F_AKBNK", "F_ASELS"]  # Coklu kontrat testi
MT5_PATH = r"C:\Program Files\GCM MT5 Terminal\terminal64.exe"
MT5_LOGIN = 7023084
MT5_SERVER = "GCM-Real01"
TICK_COUNT = 1000


def connect_mt5() -> bool:
    """MT5'e bağlan ve hesap bilgisini doğrula."""
    if not mt5.initialize(path=MT5_PATH):
        print(f"[HATA] mt5.initialize() basarisiz: {mt5.last_error()}")
        return False

    account_info = mt5.account_info()
    if account_info is None:
        print(f"[HATA] mt5.account_info() None dondu: {mt5.last_error()}")
        mt5.shutdown()
        return False

    print(f"[OK] MT5 baglanti basarili — Hesap: {account_info.login}, "
          f"Sunucu: {account_info.server}, Bakiye: {account_info.balance}")
    return True


def find_active_contract() -> str:
    """
    BASE_SYMBOL icin aktif vadeli kontrati bul.
    MT5'te semboller vade eki ile listelenir: F_THYAO0326 (Mart 2026).
    En son vadeyi (en buyuk MMYY ekini) dondurur.
    """
    print(f"\n{'='*60}")
    print(f"AKTİF KONTRAT ARAMA — {BASE_SYMBOL}*")
    print(f"{'='*60}")

    all_symbols = mt5.symbols_get()
    if all_symbols is None:
        print(f"[HATA] symbols_get() None dondu: {mt5.last_error()}")
        return ""

    # BASE_SYMBOL ile baslayan tum semboller
    matching = [s for s in all_symbols if s.name.startswith(BASE_SYMBOL)]

    if not matching:
        print(f"[HATA] '{BASE_SYMBOL}' ile baslayan sembol bulunamadi")
        print(f"[BILGI] Toplam sembol sayisi: {len(all_symbols)}")
        return ""

    print(f"Bulunan kontratlar ({len(matching)}):")
    for sym in matching:
        trade_status = "ACIK" if sym.trade_mode != 0 else "KAPALI"
        visible_status = "Market Watch'ta" if sym.visible else "gizli"
        print(f"  {sym.name:<20} bid={sym.bid:<10.2f} ask={sym.ask:<10.2f} "
              f"trade={trade_status}, {visible_status}")

    # Vade ekine gore sirala (MMYY → YYMM formatina cevirip sirala)
    def sort_key(sym):
        suffix = sym.name[len(BASE_SYMBOL):]  # ornek: "0326"
        if len(suffix) == 4 and suffix.isdigit():
            month = suffix[:2]
            year = suffix[2:]
            return year + month  # "2603" → kronolojik siralama
        return "0000"

    matching.sort(key=sort_key, reverse=True)
    active_symbol = matching[0].name

    print(f"\n[OK] Aktif kontrat secildi: {active_symbol}")
    return active_symbol


def ensure_symbol_selected(symbol: str) -> bool:
    """Sembolü Market Watch'a ekle ve bilgilerini doğrula."""
    print(f"\n{'='*60}")
    print(f"SEMBOL KONTROL — {symbol}")
    print(f"{'='*60}")

    info = mt5.symbol_info(symbol)
    if info is None:
        print(f"[HATA] symbol_info('{symbol}') None dondu: {mt5.last_error()}")
        return False

    print(f"Sembol bulundu: {info.name}")
    print(f"  visible (Market Watch'ta): {info.visible}")
    print(f"  trade_mode: {info.trade_mode}")
    print(f"  spread: {info.spread}")
    print(f"  point: {info.point}")
    print(f"  bid: {info.bid}")
    print(f"  ask: {info.ask}")

    if not info.visible:
        selected = mt5.symbol_select(symbol, True)
        if not selected:
            print(f"[HATA] symbol_select('{symbol}', True) basarisiz: {mt5.last_error()}")
            return False
        print(f"[OK] Sembol Market Watch'a eklendi")
    else:
        print(f"[OK] Sembol zaten Market Watch'ta aktif")

    return True


def test_market_book(symbol: str) -> bool:
    """Market book (emir defteri) erişimini test et."""
    print(f"\n{'='*60}")
    print(f"MARKET BOOK TESTİ — {symbol}")
    print(f"{'='*60}")

    add_result = mt5.market_book_add(symbol)
    print(f"market_book_add('{symbol}'): {add_result}")

    if not add_result:
        print(f"[UYARI] market_book_add basarisiz: {mt5.last_error()}")
        print("[BILGI] Piyasa kapali olabilir veya sembol desteklenmiyor olabilir.")
        return False

    book = mt5.market_book_get(symbol)
    if book is None or len(book) == 0:
        print(f"[UYARI] market_book_get bos dondu: {mt5.last_error()}")
        print("[BILGI] Piyasa kapali oldugunda emir defteri bos olabilir.")
        mt5.market_book_release(symbol)
        return False

    print(f"[OK] Emir defteri: {len(book)} satir")
    print(f"{'Tip':<10} {'Fiyat':<12} {'Hacim':<10}")
    print(f"{'-'*32}")
    for entry in book:
        entry_type = "ALIS" if entry.type == mt5.BOOK_TYPE_SELL else "SATIS"
        print(f"{entry_type:<10} {entry.price:<12.2f} {entry.volume:<10}")

    mt5.market_book_release(symbol)
    return True


def test_tick_data(symbol: str) -> dict:
    """Son 1 saatlik tick verisini çek ve analiz et."""
    print(f"\n{'='*60}")
    print(f"TICK VERİSİ TESTİ — {symbol}")
    print(f"{'='*60}")

    utc_now = datetime.now(timezone.utc)
    utc_from = utc_now - timedelta(hours=1)

    ticks = mt5.copy_ticks_from(symbol, utc_from, TICK_COUNT, mt5.COPY_TICKS_ALL)

    if ticks is None or len(ticks) == 0:
        print(f"[UYARI] copy_ticks_from bos dondu: {mt5.last_error()}")
        print("[BILGI] Son 1 saatte tick verisi yok. Daha genis aralık deneniyor...")

        utc_from_wide = utc_now - timedelta(days=7)
        ticks = mt5.copy_ticks_from(symbol, utc_from_wide, TICK_COUNT, mt5.COPY_TICKS_ALL)

        if ticks is None or len(ticks) == 0:
            print(f"[HATA] 7 gunluk aralıkta da tick verisi bulunamadi: {mt5.last_error()}")
            return {}

        print(f"[OK] 7 gunluk aralıktan {len(ticks)} tick cekildi")
    else:
        print(f"[OK] Son 1 saatten {len(ticks)} tick cekildi")

    results = analyze_ticks(ticks)
    return results


def analyze_ticks(ticks) -> dict:
    """
    Tick verisini analiz et: flag, volume, last, spread.
    NOT: copy_ticks_from numpy structured array dondurur.
    tick.flags numpy'nin kendi .flags property'si ile cakisir,
    bu yuzden sutun bazli erisim (ticks['flags']) kullanilir.
    """
    import numpy as np

    total_ticks = len(ticks)

    TICK_FLAG_BUY = 0x08
    TICK_FLAG_SELL = 0x10

    # Numpy sutun bazli erisim — tick.flags cakismasi onlenir
    flags_col = ticks['flags'].astype(np.int64)
    volume_col = ticks['volume'].astype(np.float64)
    last_col = ticks['last'].astype(np.float64)
    bid_col = ticks['bid'].astype(np.float64)
    ask_col = ticks['ask'].astype(np.float64)
    time_col = ticks['time'].astype(np.int64)

    buy_flag_count = int(np.sum((flags_col & TICK_FLAG_BUY) != 0))
    sell_flag_count = int(np.sum((flags_col & TICK_FLAG_SELL) != 0))
    volume_filled_count = int(np.sum(volume_col > 0))
    last_filled_count = int(np.sum(last_col > 0))

    # Spread hesabi — bid ve ask ikisi de > 0 olan tick'ler
    valid_spread_mask = (bid_col > 0) & (ask_col > 0)
    spread_values = ask_col[valid_spread_mask] - bid_col[valid_spread_mask]

    avg_spread = float(np.mean(spread_values)) if len(spread_values) > 0 else 0.0
    min_spread = float(np.min(spread_values)) if len(spread_values) > 0 else 0.0
    max_spread = float(np.max(spread_values)) if len(spread_values) > 0 else 0.0

    # Ilk ve son tick zaman damgasi
    first_tick_time = datetime.fromtimestamp(int(time_col[0]), tz=timezone.utc)
    last_tick_time = datetime.fromtimestamp(int(time_col[-1]), tz=timezone.utc)

    # Rapor yazdir
    print(f"\n--- TICK ANALİZ SONUÇLARI ---")
    print(f"Toplam tick sayisi:        {total_ticks}")
    print(f"Zaman araligi:             {first_tick_time} — {last_tick_time}")
    print()
    print(f"TICK_FLAG_BUY iceren:      {buy_flag_count:>6} / {total_ticks}  "
          f"({'VAR' if buy_flag_count > 0 else 'YOK'})")
    print(f"TICK_FLAG_SELL iceren:      {sell_flag_count:>6} / {total_ticks}  "
          f"({'VAR' if sell_flag_count > 0 else 'YOK'})")
    print(f"volume > 0 olan:           {volume_filled_count:>6} / {total_ticks}  "
          f"({'DOLU' if volume_filled_count > 0 else 'BOS'})")
    print(f"last > 0 olan:             {last_filled_count:>6} / {total_ticks}  "
          f"({'DOLU' if last_filled_count > 0 else 'BOS'})")
    print()
    print(f"--- SPREAD ANALİZİ ---")
    print(f"Spread hesaplanabilen:     {len(spread_values)} tick")
    print(f"Ortalama spread:           {avg_spread:.4f}")
    print(f"Min spread:                {min_spread:.4f}")
    print(f"Max spread:                {max_spread:.4f}")

    # Ornek tick'ler (sutun bazli erisim)
    print(f"\n--- ORNEK TICKLER (ilk 5) ---")
    print(f"{'Zaman':<22} {'Bid':<10} {'Ask':<10} {'Last':<10} {'Vol':<8} {'Flags':<8}")
    print(f"{'-'*68}")
    sample_count = min(5, total_ticks)
    for i in range(sample_count):
        tick_time = datetime.fromtimestamp(int(time_col[i]), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        print(f"{tick_time:<22} {float(bid_col[i]):<10.2f} {float(ask_col[i]):<10.2f} "
              f"{float(last_col[i]):<10.2f} {int(volume_col[i]):<8} {int(flags_col[i]):<8}")

    results = {
        "total_ticks": total_ticks,
        "buy_flags": buy_flag_count,
        "sell_flags": sell_flag_count,
        "volume_filled": volume_filled_count,
        "last_filled": last_filled_count,
        "avg_spread": avg_spread,
        "min_spread": min_spread,
        "max_spread": max_spread,
    }
    return results


# ============================================================
# TEST 2: EK VERİ DERİNLİĞİ KONTROLLERİ
# ============================================================

def fetch_ticks_for_analysis(symbol: str, count: int = 5000) -> np.ndarray:
    """Analiz icin yeterli tick verisi cek (7 gunluk fallback)."""
    utc_now = datetime.now(timezone.utc)
    utc_from = utc_now - timedelta(days=7)
    ticks = mt5.copy_ticks_from(symbol, utc_from, count, mt5.COPY_TICKS_ALL)
    if ticks is None or len(ticks) == 0:
        return np.array([])
    return ticks


def test2_tick_time_precision(ticks: np.ndarray):
    """
    TEST 2.1: Tick Zaman Hassasiyeti
    - time_msc alani dolu mu?
    - Ardisik tick'ler arasi minimum sure
    - Tick'ler gercek zamanli mi yoksa gruplanmis mi?
    """
    print(f"\n{'='*60}")
    print("TEST 2.1 — TICK ZAMAN HASSASİYETİ")
    print(f"{'='*60}")

    time_col = ticks['time'].astype(np.int64)
    time_msc_col = ticks['time_msc'].astype(np.int64)

    # time_msc doluluk kontrolu
    msc_filled = int(np.sum(time_msc_col > 0))
    total = len(ticks)
    print(f"time_msc dolu:             {msc_filled} / {total}  "
          f"({'DOLU' if msc_filled > 0 else 'BOS'})")

    if msc_filled > 0:
        # Milisaniye kismini cikar (time_msc - time*1000)
        ms_parts = time_msc_col - (time_col * 1000)
        nonzero_ms = int(np.sum(ms_parts != 0))
        print(f"ms hassasiyeti (!=0):      {nonzero_ms} / {total}  "
              f"({'ms HASSAS' if nonzero_ms > 0 else 'SADECE SANIYE'})")

    # Ardisik tick arasi sure (milisaniye bazinda)
    if len(time_msc_col) > 1:
        diffs_ms = np.diff(time_msc_col)
        # Sadece pozitif farklari al (ayni zaman damgasi olan tick'leri atla)
        positive_diffs = diffs_ms[diffs_ms > 0]

        if len(positive_diffs) > 0:
            min_diff = int(np.min(positive_diffs))
            max_diff = int(np.max(positive_diffs))
            avg_diff = float(np.mean(positive_diffs))
            median_diff = float(np.median(positive_diffs))

            # Ayni zaman damgasina sahip tick sayisi (gruplanmis tick gostergesi)
            zero_diffs = int(np.sum(diffs_ms == 0))

            print(f"\nArdisik tick arasi sureler:")
            print(f"  Min:                     {min_diff} ms")
            print(f"  Max:                     {max_diff} ms")
            print(f"  Ortalama:                {avg_diff:.1f} ms")
            print(f"  Medyan:                  {median_diff:.1f} ms")
            print(f"  Ayni zaman damgali:      {zero_diffs} tick (gruplanmis)")

            if zero_diffs > total * 0.3:
                print(f"  [YORUM] Tick'lerin %{zero_diffs*100//total}'i gruplanmis geliyor")
            else:
                print(f"  [YORUM] Tick'ler buyuk oranda gercek zamanli")
        else:
            print(f"\n[UYARI] Tum tick'ler ayni zaman damgasina sahip")


def test2_flag_combinations(ticks: np.ndarray):
    """
    TEST 2.2: Tick Flag Kombinasyonlari
    - BUY+LAST+VOLUME ayni tick'te birlikte geliyor mu?
    - Sadece BID/ASK degisen tick'ler var mi?
    - Gercek islem vs fiyat guncellemesi ayrimi
    """
    print(f"\n{'='*60}")
    print("TEST 2.2 — TICK FLAG KOMBİNASYONLARI")
    print(f"{'='*60}")

    flags_col = ticks['flags'].astype(np.int64)
    total = len(ticks)

    # MT5 tick flag sabitleri
    TICK_FLAG_BID = 0x02
    TICK_FLAG_ASK = 0x04
    TICK_FLAG_BUY = 0x08
    TICK_FLAG_SELL = 0x10
    TICK_FLAG_LAST = 0x01
    TICK_FLAG_VOLUME = 0x20

    # Flag kombinasyonlari
    has_buy = (flags_col & TICK_FLAG_BUY) != 0
    has_sell = (flags_col & TICK_FLAG_SELL) != 0
    has_last = (flags_col & TICK_FLAG_LAST) != 0
    has_volume = (flags_col & TICK_FLAG_VOLUME) != 0
    has_bid = (flags_col & TICK_FLAG_BID) != 0
    has_ask = (flags_col & TICK_FLAG_ASK) != 0

    # BUY + LAST + VOLUME birlikte
    buy_last_vol = int(np.sum(has_buy & has_last & has_volume))
    sell_last_vol = int(np.sum(has_sell & has_last & has_volume))

    # Sadece BID veya ASK degisen (BUY/SELL flag'siz)
    only_quote = int(np.sum((has_bid | has_ask) & ~has_buy & ~has_sell))

    # Gercek islem tick'leri (BUY veya SELL flag'li)
    trade_ticks = int(np.sum(has_buy | has_sell))

    # Fiyat guncelleme tick'leri (BUY/SELL yok)
    quote_ticks = total - trade_ticks

    print(f"{'Kombinasyon':<35} {'Sayi':>8} {'Oran':>8}")
    print(f"{'-'*53}")
    print(f"{'BUY + LAST + VOLUME birlikte':<35} {buy_last_vol:>8} {buy_last_vol*100/total:>7.1f}%")
    print(f"{'SELL + LAST + VOLUME birlikte':<35} {sell_last_vol:>8} {sell_last_vol*100/total:>7.1f}%")
    print(f"{'Sadece BID/ASK degisimi':<35} {only_quote:>8} {only_quote*100/total:>7.1f}%")
    print(f"{'Gercek islem (BUY|SELL)':<35} {trade_ticks:>8} {trade_ticks*100/total:>7.1f}%")
    print(f"{'Fiyat guncellemesi (diger)':<35} {quote_ticks:>8} {quote_ticks*100/total:>7.1f}%")

    # En sik gorulen flag degerleri
    unique_flags, counts = np.unique(flags_col, return_counts=True)
    sorted_idx = np.argsort(-counts)[:10]

    print(f"\nEn sik flag degerleri (ilk 10):")
    print(f"{'Flag (dec)':<12} {'Flag (hex)':<12} {'Sayi':>8} {'Oran':>8}")
    print(f"{'-'*42}")
    for idx in sorted_idx:
        flag_val = int(unique_flags[idx])
        count = int(counts[idx])
        print(f"{flag_val:<12} {hex(flag_val):<12} {count:>8} {count*100/total:>7.1f}%")


def test2_multi_contract_ticks():
    """
    TEST 2.3: Coklu Kontrat Es Zamanli Tick
    - F_THYAO, F_AKBNK, F_ASELS icin ayni zaman araliginda tick al
    - Tick yogunlugu karsilastirmasi
    - Tick zamanlari ortusme analizi
    """
    print(f"\n{'='*60}")
    print("TEST 2.3 — ÇOKLU KONTRAT EŞ ZAMANLI TICK")
    print(f"{'='*60}")

    all_symbols = mt5.symbols_get()
    if all_symbols is None:
        print("[HATA] symbols_get() basarisiz")
        return

    contract_data = {}

    for base in MULTI_SYMBOLS:
        # Aktif kontrati bul
        matching = [s for s in all_symbols if s.name.startswith(base)]
        if not matching:
            print(f"  [UYARI] {base} icin kontrat bulunamadi")
            continue

        def sort_key(sym):
            suffix = sym.name[len(base):]
            if len(suffix) == 4 and suffix.isdigit():
                return suffix[2:] + suffix[:2]
            return "0000"

        matching.sort(key=sort_key, reverse=True)
        symbol = matching[0].name

        # Market Watch'a ekle
        mt5.symbol_select(symbol, True)

        # Tick cek
        utc_now = datetime.now(timezone.utc)
        utc_from = utc_now - timedelta(days=7)
        ticks = mt5.copy_ticks_from(symbol, utc_from, 5000, mt5.COPY_TICKS_ALL)

        if ticks is not None and len(ticks) > 0:
            contract_data[symbol] = ticks
        else:
            print(f"  [UYARI] {symbol} icin tick verisi alinamadi")

    if len(contract_data) < 2:
        print("[UYARI] Karsilastirma icin yeterli kontrat verisi yok")
        return

    # Tick yogunlugu karsilastirmasi
    print(f"\n{'Kontrat':<20} {'Tick':>8} {'Zaman Araligi':<45} {'Tick/dk':>8}")
    print(f"{'-'*83}")

    time_ranges = {}
    for symbol, ticks in contract_data.items():
        time_col = ticks['time_msc'].astype(np.int64)
        first_ts = int(time_col[0])
        last_ts = int(time_col[-1])
        duration_min = (last_ts - first_ts) / 60000.0 if last_ts > first_ts else 1.0
        tick_per_min = len(ticks) / duration_min

        first_time = datetime.fromtimestamp(first_ts / 1000, tz=timezone.utc).strftime("%m-%d %H:%M")
        last_time = datetime.fromtimestamp(last_ts / 1000, tz=timezone.utc).strftime("%m-%d %H:%M")
        time_range_str = f"{first_time} — {last_time}"

        time_ranges[symbol] = (first_ts, last_ts)
        print(f"{symbol:<20} {len(ticks):>8} {time_range_str:<45} {tick_per_min:>8.1f}")

    # Ortak zaman araligi ve ortusme analizi
    if len(time_ranges) >= 2:
        all_starts = [v[0] for v in time_ranges.values()]
        all_ends = [v[1] for v in time_ranges.values()]
        overlap_start = max(all_starts)
        overlap_end = min(all_ends)

        if overlap_start < overlap_end:
            overlap_duration_min = (overlap_end - overlap_start) / 60000.0
            print(f"\nOrtak zaman araligi: {overlap_duration_min:.1f} dakika")
            print(f"[YORUM] Kontratlar arasi iliski analizi MUMKUN")
        else:
            print(f"\n[YORUM] Tick zamanlari ortusmuyor — karsilastirma sinirli")


def test2_volume_distribution(ticks: np.ndarray):
    """
    TEST 2.4: Tick Volume Dagilimi
    - Volume aralik bazli histogram
    - Buyuk islem esigi belirleme verisi
    """
    print(f"\n{'='*60}")
    print("TEST 2.4 — TICK VOLUME DAĞILIMI")
    print(f"{'='*60}")

    volume_col = ticks['volume'].astype(np.float64)
    total = len(ticks)

    # Sadece volume > 0 olan tick'ler
    nonzero_vol = volume_col[volume_col > 0]

    if len(nonzero_vol) == 0:
        print("[UYARI] Volume > 0 olan tick yok")
        return

    # Aralik bazli histogram
    bins = [
        (1, 5, "1-5 lot"),
        (6, 10, "6-10 lot"),
        (11, 20, "11-20 lot"),
        (21, 50, "21-50 lot"),
        (51, 100, "51-100 lot"),
        (101, float('inf'), "100+ lot"),
    ]

    print(f"\n{'Aralik':<15} {'Sayi':>8} {'Oran':>8} {'Gorsel'}")
    print(f"{'-'*55}")
    for low, high, label in bins:
        if high == float('inf'):
            count = int(np.sum(nonzero_vol >= low))
        else:
            count = int(np.sum((nonzero_vol >= low) & (nonzero_vol <= high)))
        pct = count * 100 / len(nonzero_vol) if len(nonzero_vol) > 0 else 0
        bar = "#" * int(pct / 2)
        print(f"{label:<15} {count:>8} {pct:>7.1f}% {bar}")

    # Istatistikler
    print(f"\nVolume istatistikleri (volume > 0):")
    print(f"  Toplam tick:             {len(nonzero_vol)}")
    print(f"  Ortalama:                {float(np.mean(nonzero_vol)):.1f} lot")
    print(f"  Medyan:                  {float(np.median(nonzero_vol)):.1f} lot")
    print(f"  Max:                     {float(np.max(nonzero_vol)):.0f} lot")
    print(f"  Std sapma:               {float(np.std(nonzero_vol)):.1f} lot")

    # Buyuk islem esigi onerisi (ortalama + 2*std)
    threshold = float(np.mean(nonzero_vol) + 2 * np.std(nonzero_vol))
    big_count = int(np.sum(nonzero_vol >= threshold))
    print(f"\n  Buyuk islem esigi oneri: >= {threshold:.0f} lot "
          f"(ort+2*std, {big_count} tick)")


def test2_intraday_frequency(ticks: np.ndarray):
    """
    TEST 2.5: Gun Ici Tick Frekansi
    - Saat bazli tick sayisi
    - Hangi saatlerde yogunluk var?
    """
    print(f"\n{'='*60}")
    print("TEST 2.5 — GÜN İÇİ TICK FREKANSI")
    print(f"{'='*60}")

    time_col = ticks['time'].astype(np.int64)

    # UTC → Turkiye saati (UTC+3) icin +3 saat ekle
    turkey_offset_sec = 3 * 3600
    local_times = time_col + turkey_offset_sec

    # Her tick'in saatini cikar
    hours = (local_times % 86400) // 3600
    minutes = (local_times % 3600) // 60

    # VİOP seans araliklari (Turkiye saati)
    time_slots = [
        (9, 45, 10, 0, "09:45-10:00"),
        (10, 0, 11, 0, "10:00-11:00"),
        (11, 0, 12, 0, "11:00-12:00"),
        (12, 0, 13, 0, "12:00-13:00"),
        (13, 0, 14, 0, "13:00-14:00"),
        (14, 0, 15, 0, "14:00-15:00"),
        (15, 0, 16, 0, "15:00-16:00"),
        (16, 0, 17, 0, "16:00-17:00"),
        (17, 0, 17, 30, "17:00-17:30"),
    ]

    # Her tick'in dakika cinsinden gun ici pozisyonu
    day_minutes = hours * 60 + minutes

    total_in_slots = 0
    print(f"\n{'Saat Araligi':<15} {'Tick':>8} {'Oran':>8} {'Gorsel'}")
    print(f"{'-'*55}")

    for sh, sm, eh, em, label in time_slots:
        start_min = sh * 60 + sm
        end_min = eh * 60 + em
        count = int(np.sum((day_minutes >= start_min) & (day_minutes < end_min)))
        total_in_slots += count
        pct = count * 100 / len(ticks) if len(ticks) > 0 else 0
        bar = "#" * int(pct / 2)
        print(f"{label:<15} {count:>8} {pct:>7.1f}% {bar}")

    outside = len(ticks) - total_in_slots
    print(f"{'Seans disi':<15} {outside:>8}")


def test2_spread_distribution(ticks: np.ndarray):
    """
    TEST 2.6: Spread Dagilimi
    - Saat bazli ortalama spread
    - Spread ile tick hizi arasinda korelasyon
    """
    print(f"\n{'='*60}")
    print("TEST 2.6 — SPREAD DAĞILIMI (Saat Bazlı)")
    print(f"{'='*60}")

    time_col = ticks['time'].astype(np.int64)
    bid_col = ticks['bid'].astype(np.float64)
    ask_col = ticks['ask'].astype(np.float64)

    # Gecerli spread tick'leri
    valid = (bid_col > 0) & (ask_col > 0)
    spread_col = np.where(valid, ask_col - bid_col, np.nan)

    # UTC → Turkiye saati
    turkey_offset = 3 * 3600
    local_times = time_col + turkey_offset
    hours = (local_times % 86400) // 3600

    print(f"\n{'Saat':<8} {'Tick':>8} {'Ort Spread':>12} {'Min':>10} {'Max':>10}")
    print(f"{'-'*50}")

    hourly_spreads = []
    hourly_counts = []

    for h in range(9, 18):
        mask = (hours == h) & valid
        count = int(np.sum(mask))
        if count > 0:
            spreads_h = spread_col[mask]
            avg_s = float(np.nanmean(spreads_h))
            min_s = float(np.nanmin(spreads_h))
            max_s = float(np.nanmax(spreads_h))
            print(f"{h:02d}:00    {count:>8} {avg_s:>12.4f} {min_s:>10.4f} {max_s:>10.4f}")
            hourly_spreads.append(avg_s)
            hourly_counts.append(count)
        else:
            print(f"{h:02d}:00    {0:>8} {'—':>12} {'—':>10} {'—':>10}")

    # Spread-tick hizi korelasyonu
    if len(hourly_spreads) >= 3 and len(hourly_counts) >= 3:
        spreads_arr = np.array(hourly_spreads)
        counts_arr = np.array(hourly_counts, dtype=np.float64)
        if np.std(spreads_arr) > 0 and np.std(counts_arr) > 0:
            corr = float(np.corrcoef(spreads_arr, counts_arr)[0, 1])
            print(f"\nSpread — Tick Hizi Korelasyonu: {corr:+.3f}")
            if corr < -0.3:
                print("[YORUM] Negatif korelasyon: Yogun saatlerde spread daralir")
            elif corr > 0.3:
                print("[YORUM] Pozitif korelasyon: Yogun saatlerde spread genisler")
            else:
                print("[YORUM] Zayif korelasyon: Spread ve tick hizi bagimsiz")


def test2_performance(symbol: str):
    """
    TEST 2.7: copy_ticks_from Performans Testi
    - 1000, 5000 tick cekme suresi
    - 5 kontrat icin ayri ayri 1000 tick suresi
    """
    print(f"\n{'='*60}")
    print("TEST 2.7 — PERFORMANS TESTİ")
    print(f"{'='*60}")

    utc_from = datetime.now(timezone.utc) - timedelta(days=7)

    # Tek kontrat, farkli buyukluklerde
    print(f"\n{symbol} — Tek kontrat tick cekme suresi:")
    print(f"{'Tick Sayisi':<15} {'Sure (ms)':>12} {'Tick/ms':>10}")
    print(f"{'-'*39}")

    for count in [1000, 5000]:
        start = time_module.perf_counter()
        ticks = mt5.copy_ticks_from(symbol, utc_from, count, mt5.COPY_TICKS_ALL)
        elapsed_ms = (time_module.perf_counter() - start) * 1000
        actual = len(ticks) if ticks is not None else 0
        rate = actual / elapsed_ms if elapsed_ms > 0 else 0
        print(f"{count:<15} {elapsed_ms:>12.1f} {rate:>10.1f}")

    # Coklu kontrat testi
    print(f"\nCoklu kontrat — her biri 1000 tick:")
    print(f"{'Kontrat':<20} {'Sure (ms)':>12} {'Tick':>8}")
    print(f"{'-'*42}")

    all_symbols_info = mt5.symbols_get()
    total_multi_ms = 0

    for base in MULTI_SYMBOLS:
        matching = [s for s in all_symbols_info if s.name.startswith(base)]
        if not matching:
            continue

        def sort_key(sym):
            suffix = sym.name[len(base):]
            if len(suffix) == 4 and suffix.isdigit():
                return suffix[2:] + suffix[:2]
            return "0000"

        matching.sort(key=sort_key, reverse=True)
        sym = matching[0].name
        mt5.symbol_select(sym, True)

        start = time_module.perf_counter()
        ticks = mt5.copy_ticks_from(sym, utc_from, 1000, mt5.COPY_TICKS_ALL)
        elapsed_ms = (time_module.perf_counter() - start) * 1000
        actual = len(ticks) if ticks is not None else 0
        total_multi_ms += elapsed_ms
        print(f"{sym:<20} {elapsed_ms:>12.1f} {actual:>8}")

    print(f"{'TOPLAM':<20} {total_multi_ms:>12.1f}")
    print(f"\n[YORUM] 10sn cycle icinde tick cekme butcesi: "
          f"{total_multi_ms:.0f}ms / 10000ms = %{total_multi_ms/100:.1f}")


def print_summary(symbol: str, book_ok: bool, tick_results: dict):
    """Genel özet yazdır."""
    print(f"\n{'='*60}")
    print(f"GENEL OZET — {symbol}")
    print(f"{'='*60}")
    print(f"Market Book erişimi:       {'BASARILI' if book_ok else 'BASARISIZ (piyasa kapali olabilir)'}")

    if tick_results:
        has_buy = tick_results["buy_flags"] > 0
        has_sell = tick_results["sell_flags"] > 0
        has_volume = tick_results["volume_filled"] > 0
        has_last = tick_results["last_filled"] > 0

        print(f"Tick verisi:               {tick_results['total_ticks']} tick cekildi")
        print(f"BUY flag:                  {'VAR' if has_buy else 'YOK'}")
        print(f"SELL flag:                 {'VAR' if has_sell else 'YOK'}")
        print(f"Volume doluluk:            {'DOLU' if has_volume else 'BOS'}")
        print(f"Last doluluk:              {'DOLU' if has_last else 'BOS'}")
        print(f"Ortalama spread:           {tick_results['avg_spread']:.4f}")
    else:
        print(f"Tick verisi:               ALINAMADI")


def main():
    """Ana akış: bağlan → kontrat bul → sembol seç → market book → tick verisi → özet."""
    print(f"MT5 Veri Derinliği Testi — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Temel sembol: {BASE_SYMBOL}")
    print(f"{'='*60}")

    if not connect_mt5():
        sys.exit(1)

    try:
        # Aktif vadeli kontrati bul (F_THYAO → F_THYAO0326 gibi)
        symbol = find_active_contract()
        if not symbol:
            print("[HATA] Aktif kontrat bulunamadi, cikiliyor.")
            sys.exit(1)

        # Sembolü Market Watch'a ekle
        if not ensure_symbol_selected(symbol):
            print("[HATA] Sembol secilemedi, cikiliyor.")
            sys.exit(1)

        book_ok = test_market_book(symbol)
        tick_results = test_tick_data(symbol)
        print_summary(symbol, book_ok, tick_results)

        # === TEST 2: EK VERİ DERİNLİĞİ KONTROLLERİ ===
        print(f"\n\n{'#'*60}")
        print(f"#  TEST 2 — EK VERİ DERİNLİĞİ KONTROLLERİ")
        print(f"{'#'*60}")

        deep_ticks = fetch_ticks_for_analysis(symbol, 5000)
        if len(deep_ticks) > 0:
            print(f"[OK] Analiz icin {len(deep_ticks)} tick cekildi")
            test2_tick_time_precision(deep_ticks)
            test2_flag_combinations(deep_ticks)
            test2_multi_contract_ticks()
            test2_volume_distribution(deep_ticks)
            test2_intraday_frequency(deep_ticks)
            test2_spread_distribution(deep_ticks)
            test2_performance(symbol)
        else:
            print("[HATA] Ek analiz icin tick verisi alinamadi")
    finally:
        mt5.shutdown()
        print(f"\n[OK] MT5 baglanti kapatildi.")


if __name__ == "__main__":
    main()
