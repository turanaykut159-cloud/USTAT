"""
MT5 Tam Gün Tick Analizi — 27 Şubat 2026 (Perşembe)
=====================================================
F_THYAO0426, F_AKBNK0426, F_ASELS0426 için 09:45-17:30 arası
tüm tick verisi çekilir ve 6 boyutlu analiz yapılır.

Sadece OKUMA yapar, emir göndermez.

Cikti: Ekran + full_day_analysis_20260227.txt
"""

import sys
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime, timezone
from io import StringIO

# --- SABITLER ---
MT5_PATH = r"C:\Program Files\GCM MT5 Terminal\terminal64.exe"
SYMBOLS = ["F_THYAO0426", "F_AKBNK0426", "F_ASELS0426"]
OUTPUT_FILE = r"C:\USTAT\tests\full_day_analysis_20260227.txt"

# 27 Şubat 2026 VİOP seansı (UTC+3 → UTC)
# 09:45 TR = 06:45 UTC,  17:30 TR = 14:30 UTC
ANALYSIS_DATE = "2026-02-27"
SESSION_START_UTC = datetime(2026, 2, 27, 6, 45, 0, tzinfo=timezone.utc)
SESSION_END_UTC = datetime(2026, 2, 27, 14, 30, 0, tzinfo=timezone.utc)

# Saat aralıkları (Türkiye saati)
TIME_SLOTS = [
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

# MT5 tick flag sabitleri
TICK_FLAG_BUY = 0x08
TICK_FLAG_SELL = 0x10

# Büyük işlem eşiği (lot)
BIG_TRADE_THRESHOLD = 4


class DualOutput:
    """Hem ekrana hem StringIO buffer'a yazar."""

    def __init__(self):
        self.buffer = StringIO()

    def print(self, text: str = ""):
        print(text)
        self.buffer.write(text + "\n")

    def get_text(self) -> str:
        return self.buffer.getvalue()


# --- Global çıktı nesnesi ---
out = DualOutput()


def connect_mt5() -> bool:
    """MT5'e bağlan."""
    if not mt5.initialize(path=MT5_PATH):
        out.print(f"[HATA] mt5.initialize() basarisiz: {mt5.last_error()}")
        return False

    info = mt5.account_info()
    if info is None:
        out.print(f"[HATA] mt5.account_info() None: {mt5.last_error()}")
        mt5.shutdown()
        return False

    out.print(f"[OK] MT5 baglanti — Hesap: {info.login}, "
              f"Sunucu: {info.server}, Bakiye: {info.balance}")
    return True


def fetch_day_ticks(symbol: str) -> np.ndarray:
    """27 Şubat 2026 tam gün tick'lerini çek."""
    mt5.symbol_select(symbol, True)

    ticks = mt5.copy_ticks_range(
        symbol, SESSION_START_UTC, SESSION_END_UTC, mt5.COPY_TICKS_ALL
    )

    if ticks is None or len(ticks) == 0:
        out.print(f"  [UYARI] {symbol}: tick verisi alinamadi — {mt5.last_error()}")
        return np.array([])

    out.print(f"  [OK] {symbol}: {len(ticks)} tick cekildi")
    return ticks


def get_turkey_day_minutes(ticks: np.ndarray) -> np.ndarray:
    """Tick zamanlarını Türkiye saati gün-içi dakika cinsine çevir."""
    time_col = ticks['time'].astype(np.int64)
    turkey_offset = 3 * 3600  # UTC+3
    local_sec = time_col + turkey_offset
    hours = (local_sec % 86400) // 3600
    minutes = (local_sec % 3600) // 60
    return hours * 60 + minutes


def slot_mask(day_minutes: np.ndarray, sh: int, sm: int, eh: int, em: int) -> np.ndarray:
    """Verilen saat aralığı için boolean maske döndür."""
    start = sh * 60 + sm
    end = eh * 60 + em
    return (day_minutes >= start) & (day_minutes < end)


def analyze_hourly_trades(ticks: np.ndarray, day_minutes: np.ndarray) -> list:
    """
    Analiz 1: Saat bazlı gerçek işlem (BUY/SELL flag'li) dağılımı.
    Dönüş: [(label, buy_count, sell_count, total_trade, total_tick), ...]
    """
    flags = ticks['flags'].astype(np.int64)
    is_buy = (flags & TICK_FLAG_BUY) != 0
    is_sell = (flags & TICK_FLAG_SELL) != 0

    rows = []
    for sh, sm, eh, em, label in TIME_SLOTS:
        m = slot_mask(day_minutes, sh, sm, eh, em)
        buy_c = int(np.sum(is_buy & m))
        sell_c = int(np.sum(is_sell & m))
        total_trade = buy_c + sell_c
        total_tick = int(np.sum(m))
        rows.append((label, buy_c, sell_c, total_trade, total_tick))
    return rows


def analyze_volume_delta(ticks: np.ndarray, day_minutes: np.ndarray) -> list:
    """
    Analiz 2: Saat bazlı volume delta (BUY volume - SELL volume).
    Dönüş: [(label, buy_vol, sell_vol, delta), ...]
    """
    flags = ticks['flags'].astype(np.int64)
    volume = ticks['volume'].astype(np.float64)
    is_buy = (flags & TICK_FLAG_BUY) != 0
    is_sell = (flags & TICK_FLAG_SELL) != 0

    rows = []
    for sh, sm, eh, em, label in TIME_SLOTS:
        m = slot_mask(day_minutes, sh, sm, eh, em)
        buy_vol = float(np.sum(volume[is_buy & m]))
        sell_vol = float(np.sum(volume[is_sell & m]))
        delta = buy_vol - sell_vol
        rows.append((label, buy_vol, sell_vol, delta))
    return rows


def analyze_big_trades(ticks: np.ndarray, day_minutes: np.ndarray) -> list:
    """
    Analiz 3: Saat bazlı büyük işlem (4+ lot) sayısı ve yönü.
    Dönüş: [(label, big_buy, big_sell, big_total, max_vol), ...]
    """
    flags = ticks['flags'].astype(np.int64)
    volume = ticks['volume'].astype(np.float64)
    is_buy = (flags & TICK_FLAG_BUY) != 0
    is_sell = (flags & TICK_FLAG_SELL) != 0
    is_big = volume >= BIG_TRADE_THRESHOLD

    rows = []
    for sh, sm, eh, em, label in TIME_SLOTS:
        m = slot_mask(day_minutes, sh, sm, eh, em)
        big_buy = int(np.sum(is_buy & is_big & m))
        big_sell = int(np.sum(is_sell & is_big & m))
        big_total = big_buy + big_sell
        slot_vols = volume[m & (is_buy | is_sell)]
        max_vol = float(np.max(slot_vols)) if len(slot_vols) > 0 else 0
        rows.append((label, big_buy, big_sell, big_total, max_vol))
    return rows


def analyze_tick_speed(ticks: np.ndarray, day_minutes: np.ndarray) -> list:
    """
    Analiz 4: Saat bazlı tick hızı (tick/dakika).
    Dönüş: [(label, tick_count, duration_min, tick_per_min), ...]
    """
    rows = []
    for sh, sm, eh, em, label in TIME_SLOTS:
        m = slot_mask(day_minutes, sh, sm, eh, em)
        count = int(np.sum(m))
        duration_min = (eh * 60 + em) - (sh * 60 + sm)
        tpm = count / duration_min if duration_min > 0 else 0
        rows.append((label, count, duration_min, tpm))
    return rows


def analyze_spread(ticks: np.ndarray, day_minutes: np.ndarray) -> list:
    """
    Analiz 5: Saat bazlı spread ortalaması.
    Dönüş: [(label, avg_spread, min_spread, max_spread, count), ...]
    """
    bid = ticks['bid'].astype(np.float64)
    ask = ticks['ask'].astype(np.float64)
    valid = (bid > 0) & (ask > 0)
    spread = np.where(valid, ask - bid, np.nan)

    rows = []
    for sh, sm, eh, em, label in TIME_SLOTS:
        m = slot_mask(day_minutes, sh, sm, eh, em) & valid
        count = int(np.sum(m))
        if count > 0:
            s = spread[m]
            rows.append((label, float(np.nanmean(s)), float(np.nanmin(s)),
                         float(np.nanmax(s)), count))
        else:
            rows.append((label, 0, 0, 0, 0))
    return rows


def analyze_cross_contract_timing(all_ticks: dict):
    """
    Analiz 6: Kontratlar arası tick zamanlaması karşılaştırması.
    Her saat aralığında hangi kontrat ilk BUY/SELL tick'i üretmiş?
    """
    out.print(f"\n{'='*70}")
    out.print("ANALİZ 6 — KONTRATLAR ARASI ZAMANLAMA KARŞILAŞTIRMASI")
    out.print(f"{'='*70}")
    out.print("Her saat araliginda ilk gercek islem (BUY/SELL) tick'ini")
    out.print("hangi kontrat uretti?")

    # Her kontrat için trade tick zamanlarını hazırla
    contract_trade_times = {}
    for symbol, ticks in all_ticks.items():
        flags = ticks['flags'].astype(np.int64)
        time_msc = ticks['time_msc'].astype(np.int64)
        is_trade = ((flags & TICK_FLAG_BUY) != 0) | ((flags & TICK_FLAG_SELL) != 0)
        trade_times_msc = time_msc[is_trade]

        # Türkiye saati gün-içi dakika
        time_sec = ticks['time'].astype(np.int64)
        turkey_sec = time_sec + 3 * 3600
        hours = (turkey_sec % 86400) // 3600
        minutes = (turkey_sec % 3600) // 60
        dm = hours * 60 + minutes
        trade_dm = dm[is_trade]

        contract_trade_times[symbol] = (trade_times_msc, trade_dm)

    # Kısa isim
    short_names = {}
    for sym in all_ticks:
        # F_THYAO0426 → THYAO
        base = sym.replace("F_", "").replace("0426", "")
        short_names[sym] = base

    header_syms = "   ".join(f"{short_names[s]:<12}" for s in all_ticks)
    out.print(f"\n{'Saat':<15} {header_syms}  {'Ilk Hareket'}")
    out.print(f"{'-'*75}")

    for sh, sm, eh, em, label in TIME_SLOTS:
        start_min = sh * 60 + sm
        end_min = eh * 60 + em

        first_times = {}
        time_strs = []

        for symbol in all_ticks:
            trade_msc, trade_dm = contract_trade_times[symbol]
            in_slot = (trade_dm >= start_min) & (trade_dm < end_min)
            slot_times = trade_msc[in_slot]

            if len(slot_times) > 0:
                first_msc = int(np.min(slot_times))
                first_times[symbol] = first_msc
                # msc → saat:dk:sn.ms formatı
                first_dt = datetime.fromtimestamp(first_msc / 1000, tz=timezone.utc)
                turkey_dt_h = (first_dt.hour + 3) % 24
                ts = f"{turkey_dt_h:02d}:{first_dt.minute:02d}:{first_dt.second:02d}.{first_msc % 1000:03d}"
                time_strs.append(f"{ts:<15}")
            else:
                time_strs.append(f"{'—':<15}")

        # En erken hareket eden
        if first_times:
            earliest_sym = min(first_times, key=first_times.get)
            earliest_name = short_names[earliest_sym]
        else:
            earliest_name = "—"

        line = f"{label:<15} {''.join(time_strs)} {earliest_name}"
        out.print(line)

    # Genel liderlik tablosu
    out.print(f"\nGenel liderlik (tum saat aralikları):")
    leader_counts = {sym: 0 for sym in all_ticks}

    for sh, sm, eh, em, label in TIME_SLOTS:
        start_min = sh * 60 + sm
        end_min = eh * 60 + em
        first_times = {}
        for symbol in all_ticks:
            trade_msc, trade_dm = contract_trade_times[symbol]
            in_slot = (trade_dm >= start_min) & (trade_dm < end_min)
            slot_times = trade_msc[in_slot]
            if len(slot_times) > 0:
                first_times[symbol] = int(np.min(slot_times))

        if first_times:
            earliest = min(first_times, key=first_times.get)
            leader_counts[earliest] += 1

    for sym, count in sorted(leader_counts.items(), key=lambda x: -x[1]):
        out.print(f"  {short_names[sym]:<12} {count} kez ilk hareket")


def print_contract_analysis(symbol: str, ticks: np.ndarray):
    """Tek kontrat için 5 analizi yazdır."""
    short = symbol.replace("F_", "").replace("0426", "")
    day_minutes = get_turkey_day_minutes(ticks)

    total_ticks = len(ticks)
    flags = ticks['flags'].astype(np.int64)
    total_trades = int(np.sum(((flags & TICK_FLAG_BUY) != 0) | ((flags & TICK_FLAG_SELL) != 0)))

    out.print(f"\n\n{'#'*70}")
    out.print(f"#  {symbol} ({short}) — {ANALYSIS_DATE} TAM GÜN ANALİZİ")
    out.print(f"#  Toplam: {total_ticks} tick, {total_trades} gercek islem")
    out.print(f"{'#'*70}")

    # --- Analiz 1: Gerçek İşlem Dağılımı ---
    out.print(f"\n{'='*70}")
    out.print(f"ANALİZ 1 — SAAT BAZLI GERÇEK İŞLEM DAĞILIMI ({short})")
    out.print(f"{'='*70}")
    trades = analyze_hourly_trades(ticks, day_minutes)

    out.print(f"{'Saat':<15} {'BUY':>8} {'SELL':>8} {'Toplam':>8} "
              f"{'%Tick':>8} {'Tick':>8}")
    out.print(f"{'-'*57}")
    for label, bc, sc, tt, tc in trades:
        pct = tt * 100 / tc if tc > 0 else 0
        out.print(f"{label:<15} {bc:>8} {sc:>8} {tt:>8} {pct:>7.1f}% {tc:>8}")

    sum_buy = sum(r[1] for r in trades)
    sum_sell = sum(r[2] for r in trades)
    sum_trade = sum(r[3] for r in trades)
    sum_tick = sum(r[4] for r in trades)
    out.print(f"{'-'*57}")
    out.print(f"{'TOPLAM':<15} {sum_buy:>8} {sum_sell:>8} {sum_trade:>8} "
              f"{'':>8} {sum_tick:>8}")

    # --- Analiz 2: Volume Delta ---
    out.print(f"\n{'='*70}")
    out.print(f"ANALİZ 2 — SAAT BAZLI VOLUME DELTA ({short})")
    out.print(f"{'='*70}")
    vd = analyze_volume_delta(ticks, day_minutes)

    out.print(f"{'Saat':<15} {'BUY Vol':>10} {'SELL Vol':>10} {'Delta':>10} {'Yon'}")
    out.print(f"{'-'*55}")
    for label, bv, sv, delta in vd:
        direction = "ALIS BASKIN" if delta > 0 else ("SATIS BASKIN" if delta < 0 else "NOTR")
        out.print(f"{label:<15} {bv:>10.0f} {sv:>10.0f} {delta:>+10.0f} {direction}")

    sum_bv = sum(r[1] for r in vd)
    sum_sv = sum(r[2] for r in vd)
    sum_delta = sum_bv - sum_sv
    gun_yon = "ALIS BASKIN" if sum_delta > 0 else ("SATIS BASKIN" if sum_delta < 0 else "NOTR")
    out.print(f"{'-'*55}")
    out.print(f"{'GUN TOPLAM':<15} {sum_bv:>10.0f} {sum_sv:>10.0f} {sum_delta:>+10.0f} {gun_yon}")

    # --- Analiz 3: Büyük İşlemler ---
    out.print(f"\n{'='*70}")
    out.print(f"ANALİZ 3 — BÜYÜK İŞLEMLER ({BIG_TRADE_THRESHOLD}+ lot) ({short})")
    out.print(f"{'='*70}")
    bt = analyze_big_trades(ticks, day_minutes)

    out.print(f"{'Saat':<15} {'BigBUY':>8} {'BigSELL':>8} {'Toplam':>8} {'MaxVol':>8}")
    out.print(f"{'-'*49}")
    for label, bb, bs, total, mv in bt:
        out.print(f"{label:<15} {bb:>8} {bs:>8} {total:>8} {mv:>8.0f}")

    sum_bb = sum(r[1] for r in bt)
    sum_bs = sum(r[2] for r in bt)
    out.print(f"{'-'*49}")
    out.print(f"{'TOPLAM':<15} {sum_bb:>8} {sum_bs:>8} {sum_bb + sum_bs:>8}")

    # --- Analiz 4: Tick Hızı ---
    out.print(f"\n{'='*70}")
    out.print(f"ANALİZ 4 — TICK HIZI ({short})")
    out.print(f"{'='*70}")
    ts = analyze_tick_speed(ticks, day_minutes)

    out.print(f"{'Saat':<15} {'Tick':>8} {'Dakika':>8} {'Tick/dk':>10} {'Gorsel'}")
    out.print(f"{'-'*60}")
    max_tpm = max(r[3] for r in ts) if ts else 1
    for label, count, dur, tpm in ts:
        bar_len = int(tpm / max_tpm * 30) if max_tpm > 0 else 0
        bar = "#" * bar_len
        out.print(f"{label:<15} {count:>8} {dur:>8} {tpm:>10.1f} {bar}")

    # --- Analiz 5: Spread ---
    out.print(f"\n{'='*70}")
    out.print(f"ANALİZ 5 — SPREAD DAĞILIMI ({short})")
    out.print(f"{'='*70}")
    sp = analyze_spread(ticks, day_minutes)

    out.print(f"{'Saat':<15} {'Ort':>10} {'Min':>10} {'Max':>10} {'Tick':>8}")
    out.print(f"{'-'*55}")
    for label, avg, mn, mx, cnt in sp:
        if cnt > 0:
            out.print(f"{label:<15} {avg:>10.4f} {mn:>10.4f} {mx:>10.4f} {cnt:>8}")
        else:
            out.print(f"{label:<15} {'—':>10} {'—':>10} {'—':>10} {0:>8}")


def main():
    """Ana akış."""
    out.print(f"MT5 Tam Gun Tick Analizi — {ANALYSIS_DATE}")
    out.print(f"Kontratlar: {', '.join(SYMBOLS)}")
    out.print(f"Seans: 09:45-17:30 (TR) / 06:45-14:30 (UTC)")
    out.print(f"Calistirma: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    out.print(f"{'='*70}")

    if not connect_mt5():
        sys.exit(1)

    try:
        # Tick verisi çek
        out.print(f"\nTick verisi cekiliyor...")
        all_ticks = {}
        for symbol in SYMBOLS:
            ticks = fetch_day_ticks(symbol)
            if len(ticks) > 0:
                all_ticks[symbol] = ticks

        if not all_ticks:
            out.print("[HATA] Hicbir kontrat icin tick verisi alinamadi")
            sys.exit(1)

        # Her kontrat için analiz 1-5
        for symbol, ticks in all_ticks.items():
            print_contract_analysis(symbol, ticks)

        # Analiz 6: Kontratlar arası zamanlama (en az 2 kontrat gerekli)
        if len(all_ticks) >= 2:
            analyze_cross_contract_timing(all_ticks)
        else:
            out.print("\n[UYARI] Kontratlar arasi analiz icin en az 2 kontrat gerekli")

        # Dosyaya kaydet
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(out.get_text())
        out.print(f"\n[OK] Sonuclar kaydedildi: {OUTPUT_FILE}")

    finally:
        mt5.shutdown()
        out.print(f"[OK] MT5 baglanti kapatildi.")


if __name__ == "__main__":
    main()
