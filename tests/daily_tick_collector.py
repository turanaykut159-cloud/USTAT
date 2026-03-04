# -*- coding: utf-8 -*-
"""
USTAT v5.0 — Gunluk Tick Veri Toplama ve Analiz Scripti (Optimize Edilmis)
Amac: OGUL yeni motor parametre kalibrasyonu icin 5 gunluk veri toplama
Tarih: 2-6 Mart 2026 arasi her gun seans sonrasi calistirilacak
Kontratlar: F_THYAO0326, F_AKBNK0326, F_ASELS0326, F_GARAN0326, F_KCHOL0326
Seans: 09:45-17:30 TR / 06:45-14:30 UTC

Kullanim:
  python daily_tick_collector.py              # bugunun tarihini kullanir
  python daily_tick_collector.py 20260302     # belirli tarih

Cikti:
  stdout  -> insan-okunabilir rapor
  JSON    -> daily_YYYYMMDD.json (makine-okunabilir, gunler arasi karsilastirma icin)

15 Metrik:
  1.  Saat bazli inferred BUY/SELL dagilimi
  2.  Saat bazli volume delta
  3.  Saat bazli buyuk islemler (4+ lot)
  4.  Fiyat-delta uyumu
  5.  Agresor degisim anlari (5dk pencere)
  6.  Saat bazli ortalama spread
  7.  Saat bazli ortalama lot buyuklugu
  8.  Saat bazli tick velocity (gercek islem tick/dakika)
  9.  Tick response time dagilimi (algo vs insan orani)
  10. Volume profile (fiyat bazli hacim, POC, value area)
  11. Lot dagilimi parmak izi (anormal lot frekanslari)
  12. Spread asimetrisi (bid vs ask hareket farki)
  13. Islem arasi bekleme suresi dagilimi
  14. 15dk weighted momentum haritasi
  15. Gunluk ozet
  EK: Market book testi (seans icinde)
"""

import MetaTrader5 as mt5
from datetime import datetime, timedelta, timezone
from collections import Counter, defaultdict
import json
import time
import sys
import os
import math

# ============================================================================
# YAPILANDIRMA
# ============================================================================

SYMBOLS = ["F_THYAO0326", "F_AKBNK0326", "F_ASELS0326", "F_GARAN0326", "F_KCHOL0326"]
BIG_TRADE_THRESHOLD = 4  # 27 Subat verisinden: ort + 2*std

# Seans zamanlari (UTC)
SESSION_START_UTC_H = 6
SESSION_START_UTC_M = 45
SESSION_END_UTC_H = 14
SESSION_END_UTC_M = 30

# Tarih parametresi
if len(sys.argv) > 1:
    date_str = sys.argv[1]
    ANALYSIS_DATE = datetime(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
else:
    ANALYSIS_DATE = datetime.now()

DATE_STR = ANALYSIS_DATE.strftime("%Y-%m-%d")
WEEKDAY_NAMES = ["Pazartesi", "Sali", "Carsamba", "Persembe", "Cuma", "Cumartesi", "Pazar"]
WEEKDAY = WEEKDAY_NAMES[ANALYSIS_DATE.weekday()]

# JSON cikti dosyasi
JSON_OUTPUT = f"daily_{ANALYSIS_DATE.strftime('%Y%m%d')}.json"


# ============================================================================
# SAAT / SLOT TANIMLARI — bir kez hesapla, her yerde kullan
# ============================================================================

def _build_slots(step_minutes, start_h=9, start_m=45, end_h=17, end_m=30):
    """Verilen adim buyuklugune gore slot listesi olustur.
    Her slot: (label, start_total_minutes, end_total_minutes)
    Dakika bazli integer karsilastirma — datetime obje olusturmaktan cok daha hizli.
    """
    slots = []
    cursor_h, cursor_m = start_h, start_m
    limit = end_h * 60 + end_m
    while cursor_h * 60 + cursor_m < limit:
        s_min = cursor_h * 60 + cursor_m
        # adim kadar ilerle
        e_min = s_min + step_minutes
        if e_min > limit:
            e_min = limit
        e_h, e_m = divmod(e_min, 60)
        label = f"{cursor_h:02d}:{cursor_m:02d}-{e_h:02d}:{e_m:02d}"
        slots.append((label, s_min, e_min))
        cursor_h, cursor_m = e_h, e_m
    return slots

# Sabit slotlar: ozel seans yapisi (09:45-10:00 = 15dk, sonra 60dk bloklar, son 17:00-17:30 = 30dk)
HOUR_SLOTS = [
    ("09:45-10:00",  9 * 60 + 45, 10 * 60 +  0),
    ("10:00-11:00", 10 * 60 +  0, 11 * 60 +  0),
    ("11:00-12:00", 11 * 60 +  0, 12 * 60 +  0),
    ("12:00-13:00", 12 * 60 +  0, 13 * 60 +  0),
    ("13:00-14:00", 13 * 60 +  0, 14 * 60 +  0),
    ("14:00-15:00", 14 * 60 +  0, 15 * 60 +  0),
    ("15:00-16:00", 15 * 60 +  0, 16 * 60 +  0),
    ("16:00-17:00", 16 * 60 +  0, 17 * 60 +  0),
    ("17:00-17:30", 17 * 60 +  0, 17 * 60 + 30),
]

FIFTEEN_MIN_SLOTS = _build_slots(15)
FIVE_MIN_SLOTS = _build_slots(5)


# ============================================================================
# YARDIMCI FONKSIYONLAR
# ============================================================================

# UTC+3 offset (milisaniye)
_UTC3_OFFSET_MS = 3 * 3600 * 1000
# epoch
_EPOCH = datetime(1970, 1, 1)


def _time_msc_to_tr_minutes(time_msc):
    """time_msc -> TR saat:dakika (toplam dakika olarak).
    datetime objesi olusturmadan integer aritmetik ile hesaplar.
    """
    total_sec = (time_msc + _UTC3_OFFSET_MS) // 1000
    # gun icindeki saniye
    day_sec = total_sec % 86400
    return day_sec // 60


def _time_msc_to_tr_hms(time_msc):
    """time_msc -> (hour, minute, second, millisecond) tuple — format icin."""
    total_ms = time_msc + _UTC3_OFFSET_MS
    day_ms = total_ms % 86_400_000
    h = day_ms // 3_600_000
    rem = day_ms % 3_600_000
    m = rem // 60_000
    rem2 = rem % 60_000
    s = rem2 // 1000
    ms = rem2 % 1000
    return (h, m, s, ms)


def format_time_msc(time_msc):
    """time_msc'yi HH:MM:SS.mmm formatinda goster"""
    h, m, s, ms = _time_msc_to_tr_hms(time_msc)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def classify_trade(last, bid, ask, volume):
    """last fiyatinin bid/ask konumuna gore yon belirle"""
    if last <= 0 or bid <= 0 or ask <= 0 or volume <= 0:
        return 0  # NEUTRAL = 0, BUY = 1, SELL = -1  (integer ile karsilastirma daha hizli)
    if last <= bid:
        return -1
    if last >= ask:
        return 1
    mid = (bid + ask) * 0.5
    return 1 if last >= mid else -1


# Yon sabitleri
DIR_BUY = 1
DIR_SELL = -1
DIR_NEUTRAL = 0
DIR_LABELS = {DIR_BUY: "BUY", DIR_SELL: "SELL", DIR_NEUTRAL: "NEUTRAL"}


def is_real_trade_flags(flags, volume, last):
    """Gercek islem tick'i mi? Inline-friendly."""
    return (flags & 0x18) == 0x18 and volume > 0 and last > 0


def safe_mean(values):
    n = len(values)
    if n == 0:
        return 0.0
    return sum(values) / n


def safe_median(values):
    n = len(values)
    if n == 0:
        return 0.0
    s = sorted(values)
    if n & 1:
        return s[n >> 1]
    return (s[(n >> 1) - 1] + s[n >> 1]) * 0.5


def safe_std(values):
    n = len(values)
    if n < 2:
        return 0.0
    m = sum(values) / n
    return math.sqrt(sum((x - m) ** 2 for x in values) / (n - 1))


def _slot_index(tr_min, slots):
    """Verilen TR dakikasinin hangi slot'a dustugunu bul. Binary search."""
    lo, hi = 0, len(slots) - 1
    while lo <= hi:
        mid = (lo + hi) >> 1
        _, s_start, s_end = slots[mid]
        if tr_min < s_start:
            hi = mid - 1
        elif tr_min >= s_end:
            lo = mid + 1
        else:
            return mid
    return -1


# ============================================================================
# TICK ISLEME — tek gecis, tum veriyi hazirla
# ============================================================================

def process_ticks(raw_ticks, tick_size_from_mt5):
    """Ham tick verisini tek geciste isle.

    Dondurulenler:
        real_trades  : list of dict — sadece gercek islemler
        all_ticks    : list of dict — tum tick'ler (spread/bid/ask analizi icin)
        hourly_trades: dict[slot_idx -> list of int] — real_trades indeksleri
        hourly_all   : dict[slot_idx -> list of int] — all_ticks indeksleri
        five_min_trades : dict[slot_idx -> list of int]
        fifteen_min_trades : dict[slot_idx -> list of int]
    """
    real_trades = []
    all_ticks = []

    # Slot bazli indeks gruplari — ön-gruplama
    hourly_trades = defaultdict(list)
    hourly_all = defaultdict(list)
    five_min_trades = defaultdict(list)
    fifteen_min_trades = defaultdict(list)

    real_idx = 0
    all_idx = 0

    for t in raw_ticks:
        time_msc = int(t['time_msc'])
        bid = float(t['bid'])
        ask = float(t['ask'])
        last = float(t['last'])
        volume = int(t['volume'])
        flags = int(t['flags'])

        tr_min = _time_msc_to_tr_minutes(time_msc)
        spread = ask - bid if ask > 0 and bid > 0 else 0.0

        # Tum tick kaydi (bid/ask olan)
        if bid > 0 and ask > 0:
            all_ticks.append({
                'time_msc': time_msc,
                'tr_min': tr_min,
                'bid': bid,
                'ask': ask,
                'last': last,
                'volume': volume,
                'spread': spread,
            })
            h_idx = _slot_index(tr_min, HOUR_SLOTS)
            if h_idx >= 0:
                hourly_all[h_idx].append(all_idx)
            all_idx += 1

        # Gercek islem mi?
        if is_real_trade_flags(flags, volume, last):
            direction = classify_trade(last, bid, ask, volume)
            real_trades.append({
                'time_msc': time_msc,
                'tr_min': tr_min,
                'bid': bid,
                'ask': ask,
                'last': last,
                'volume': volume,
                'flags': flags,
                'direction': direction,
                'spread': spread,
            })
            # Slot gruplama
            h_idx = _slot_index(tr_min, HOUR_SLOTS)
            if h_idx >= 0:
                hourly_trades[h_idx].append(real_idx)

            f5_idx = _slot_index(tr_min, FIVE_MIN_SLOTS)
            if f5_idx >= 0:
                five_min_trades[f5_idx].append(real_idx)

            f15_idx = _slot_index(tr_min, FIFTEEN_MIN_SLOTS)
            if f15_idx >= 0:
                fifteen_min_trades[f15_idx].append(real_idx)

            real_idx += 1

    return (real_trades, all_ticks,
            hourly_trades, hourly_all,
            five_min_trades, fifteen_min_trades)


# ============================================================================
# ANALIZ FONKSIYONLARI
# ============================================================================

def analyze_symbol(symbol, raw_ticks, tick_size_from_mt5):
    """Tek kontrat icin tum analizleri calistir. Tek gecis + ön-gruplanmis indeksler."""

    (real_trades, all_ticks,
     hourly_trades, hourly_all,
     five_min_trades, fifteen_min_trades) = process_ticks(raw_ticks, tick_size_from_mt5)

    raw = symbol.split("_")[1]
    short_name = raw[:-4] if len(raw) > 4 else raw  # son 4 karakter (MMYY) kes: THYAO0326 -> THYAO
    total_real = len(real_trades)
    total_raw = len(raw_ticks)

    buy_count = sum(1 for t in real_trades if t['direction'] == DIR_BUY)
    sell_count = sum(1 for t in real_trades if t['direction'] == DIR_SELL)
    neutral_count = total_real - buy_count - sell_count

    # JSON icin sonuclari topla
    json_data = {
        'symbol': symbol,
        'short_name': short_name,
        'date': DATE_STR,
        'weekday': WEEKDAY,
        'total_ticks': total_raw,
        'real_trades': total_real,
        'buy_count': buy_count,
        'sell_count': sell_count,
        'neutral_count': neutral_count,
        'tick_size': tick_size_from_mt5,
        'analyses': {},
    }

    print()
    print("######################################################################")
    print(f"#  {symbol} ({short_name}) -- {DATE_STR} TAM GUN ANALIZI")
    print(f"#  Toplam tick: {total_raw}, Gecerli islem: {total_real}")
    print(f"#  at_bid(SELL): {sell_count} ({sell_count * 100 / max(total_real, 1):.0f}%)"
          f"  at_ask(BUY): {buy_count} ({buy_count * 100 / max(total_real, 1):.0f}%)"
          f"  neutral: {neutral_count}")
    print("######################################################################")

    # ---- Yardimci: slot icindeki trade'lerden hizli istatistik ----
    def _slot_buysell(slot_indices):
        """Slot icindeki BUY/SELL adet ve hacim."""
        b_cnt = s_cnt = 0
        b_vol = s_vol = 0
        for idx in slot_indices:
            t = real_trades[idx]
            v = t['volume']
            d = t['direction']
            if d == DIR_BUY:
                b_cnt += 1
                b_vol += v
            elif d == DIR_SELL:
                s_cnt += 1
                s_vol += v
        return b_cnt, s_cnt, b_vol, s_vol

    # ==================================================================
    # ANALIZ 1: SAAT BAZLI BUY/SELL DAGILIMI
    # ==================================================================
    print()
    print("=" * 70)
    print(f"ANALIZ 1 -- SAAT BAZLI ISLEM DAGILIMI (inferred) [{short_name}]")
    print("=" * 70)
    print(f"{'Saat':<20} {'BUY':>7} {'SELL':>7} {'Toplam':>8} {'BUY%':>7}")
    print("-" * 50)

    a1_data = []
    total_buy = total_sell = 0
    for si, (label, _, _) in enumerate(HOUR_SLOTS):
        b_cnt, s_cnt, _, _ = _slot_buysell(hourly_trades.get(si, []))
        tot = b_cnt + s_cnt
        pct = b_cnt * 100 / tot if tot > 0 else 0
        print(f"{label:<20} {b_cnt:>7d} {s_cnt:>7d} {tot:>8d} {pct:>6.1f}%")
        total_buy += b_cnt
        total_sell += s_cnt
        a1_data.append({'slot': label, 'buy': b_cnt, 'sell': s_cnt})
    print("-" * 50)
    tot = total_buy + total_sell
    pct = total_buy * 100 / tot if tot > 0 else 0
    print(f"{'TOPLAM':<20} {total_buy:>7d} {total_sell:>7d} {tot:>8d} {pct:>6.1f}%")
    json_data['analyses']['1_hourly_buysell'] = a1_data

    # ==================================================================
    # ANALIZ 2: SAAT BAZLI VOLUME DELTA
    # ==================================================================
    print()
    print("=" * 70)
    print(f"ANALIZ 2 -- SAAT BAZLI VOLUME DELTA (inferred) [{short_name}]")
    print("=" * 70)
    print(f"{'Saat':<20} {'BUY Vol':>9} {'SELL Vol':>9} {'Delta':>9} {'Yon'}")
    print("-" * 60)

    a2_data = []
    gun_buy_vol = gun_sell_vol = 0
    for si, (label, _, _) in enumerate(HOUR_SLOTS):
        _, _, bv, sv = _slot_buysell(hourly_trades.get(si, []))
        delta = bv - sv
        yon = "ALIS BASKIN" if delta > 0 else ("SATIS BASKIN" if delta < 0 else "NOTR")
        print(f"{label:<20} {bv:>9d} {sv:>9d} {delta:>+9d} {yon}")
        gun_buy_vol += bv
        gun_sell_vol += sv
        a2_data.append({'slot': label, 'buy_vol': bv, 'sell_vol': sv, 'delta': delta})
    print("-" * 60)
    gun_delta = gun_buy_vol - gun_sell_vol
    yon = "ALIS BASKIN" if gun_delta > 0 else ("SATIS BASKIN" if gun_delta < 0 else "NOTR")
    print(f"{'GUN TOPLAM':<20} {gun_buy_vol:>9d} {gun_sell_vol:>9d} {gun_delta:>+9d} {yon}")
    json_data['analyses']['2_hourly_volume_delta'] = a2_data

    # ==================================================================
    # ANALIZ 3: BUYUK ISLEMLER
    # ==================================================================
    print()
    print("=" * 70)
    print(f"ANALIZ 3 -- BUYUK ISLEMLER ({BIG_TRADE_THRESHOLD}+ lot) [{short_name}]")
    print("=" * 70)
    print(f"{'Saat':<18} {'BigBUY':>7} {'BigSELL':>8} {'Toplam':>8} {'BuyVol':>8} {'SellVol':>8} {'MaxVol':>8}")
    print("-" * 70)

    a3_data = []
    total_bb = total_bs = 0
    for si, (label, _, _) in enumerate(HOUR_SLOTS):
        indices = hourly_trades.get(si, [])
        bb_cnt = bs_cnt = 0
        bb_vol = bs_vol = 0
        max_vol = 0
        for idx in indices:
            t = real_trades[idx]
            v = t['volume']
            d = t['direction']
            if v >= BIG_TRADE_THRESHOLD:
                if v > max_vol:
                    max_vol = v
                if d == DIR_BUY:
                    bb_cnt += 1
                    bb_vol += v
                elif d == DIR_SELL:
                    bs_cnt += 1
                    bs_vol += v
        print(f"{label:<18} {bb_cnt:>7d} {bs_cnt:>8d} {bb_cnt + bs_cnt:>8d} {bb_vol:>8d} {bs_vol:>8d} {max_vol:>8d}")
        total_bb += bb_cnt
        total_bs += bs_cnt
        a3_data.append({'slot': label, 'big_buy': bb_cnt, 'big_sell': bs_cnt, 'buy_vol': bb_vol, 'sell_vol': bs_vol, 'max_vol': max_vol})
    print("-" * 70)
    print(f"{'TOPLAM':<18} {total_bb:>7d} {total_bs:>8d} {total_bb + total_bs:>8d}")
    json_data['analyses']['3_big_trades'] = a3_data

    # ==================================================================
    # ANALIZ 4: FIYAT-DELTA UYUMU
    # ==================================================================
    print()
    print("=" * 70)
    print(f"ANALIZ 4 -- FIYAT-DELTA UYUMU [{short_name}]")
    print("=" * 70)
    print(f"{'Saat':<20} {'Acilis':>9} {'Kapanis':>9} {'Degisim':>9} {'VolDelta':>9} {'Uyum'}")
    print("-" * 65)

    a4_data = []
    uyumlu = toplam_karsilastirma = 0
    for si, (label, _, _) in enumerate(HOUR_SLOTS):
        indices = hourly_trades.get(si, [])
        if not indices:
            print(f"{label:<20} {'--':>9} {'--':>9} {'--':>9} {'--':>9} --")
            continue
        first_t = real_trades[indices[0]]
        last_t = real_trades[indices[-1]]
        acilis = first_t['last']
        kapanis = last_t['last']
        degisim = kapanis - acilis
        _, _, bv, sv = _slot_buysell(indices)
        delta = bv - sv

        if abs(degisim) < 0.01 and abs(delta) < 2:
            uyum_str = "NOTR"
        elif (degisim > 0 and delta > 0) or (degisim < 0 and delta < 0):
            uyum_str = "UYUMLU"
            uyumlu += 1
            toplam_karsilastirma += 1
        else:
            uyum_str = "UYUMSUZ"
            toplam_karsilastirma += 1

        print(f"{label:<20} {acilis:>9.2f} {kapanis:>9.2f} {degisim:>+9.2f} {delta:>+9d} {uyum_str}")
        a4_data.append({'slot': label, 'open': acilis, 'close': kapanis, 'price_chg': round(degisim, 2), 'vol_delta': delta, 'uyum': uyum_str})

    if toplam_karsilastirma > 0:
        print(f"\nUyum orani: {uyumlu}/{toplam_karsilastirma} = %{uyumlu * 100 // toplam_karsilastirma}")
    json_data['analyses']['4_price_delta_alignment'] = {'slots': a4_data, 'uyumlu': uyumlu, 'toplam': toplam_karsilastirma}

    # ==================================================================
    # ANALIZ 5: AGRESOR DEGISIM ANLARI (5dk pencere)
    # ==================================================================
    print()
    print("=" * 70)
    print(f"ANALIZ 5 -- AGRESOR DEGISIM ANLARI [{short_name}]")
    print("=" * 70)
    print(f"{'Zaman':<14} {'BuyVol':>7} {'SellVol':>8} {'Delta':>8} {'Baskin':<18} {'Gecis'}")
    print("-" * 65)

    prev_baskin = None
    gecis_count = 0
    a5_data = []

    for si, (label, _, _) in enumerate(FIVE_MIN_SLOTS):
        indices = five_min_trades.get(si, [])
        if not indices:
            continue
        _, _, bv, sv = _slot_buysell(indices)
        delta = bv - sv

        if delta > 0:
            baskin = "ALIS BASKIN"
            baskin_code = 1
        elif delta < 0:
            baskin = "SATIS BASKIN"
            baskin_code = -1
        else:
            baskin = "NOTR"
            baskin_code = 0

        gecis_str = ""
        if prev_baskin and baskin_code != 0 and prev_baskin != 0 and baskin_code != prev_baskin:
            gecis_str = "<<< BUY->SELL" if prev_baskin == 1 else "<<< SELL->BUY"
            gecis_count += 1

        print(f"{label:<14} {bv:>7d} {sv:>8d} {delta:>+8d} {baskin:<18} {gecis_str}")
        a5_data.append({'slot': label, 'buy_vol': bv, 'sell_vol': sv, 'delta': delta, 'dominant': baskin_code, 'shift': gecis_str})

        if baskin_code != 0:
            prev_baskin = baskin_code

    print(f"\nToplam agresor degisimi: {gecis_count}")
    json_data['analyses']['5_aggressor_shifts'] = {'shifts': a5_data, 'total_shifts': gecis_count}

    # ==================================================================
    # ANALIZ 6: SAAT BAZLI ORTALAMA SPREAD
    # ==================================================================
    print()
    print("=" * 70)
    print(f"ANALIZ 6 -- SAAT BAZLI ORTALAMA SPREAD [{short_name}]")
    print("=" * 70)
    print(f"{'Saat':<20} {'Ort Spread':>10} {'Min':>8} {'Max':>8} {'Medyan':>8} {'Tick Say':>9}")
    print("-" * 65)

    a6_data = []
    gun_spreads = []
    for si, (label, _, _) in enumerate(HOUR_SLOTS):
        indices = hourly_all.get(si, [])
        spreads = [all_ticks[i]['spread'] for i in indices if all_ticks[i]['spread'] > 0]
        if not spreads:
            print(f"{label:<20} {'--':>10} {'--':>8} {'--':>8} {'--':>8} {0:>9d}")
            continue
        gun_spreads.extend(spreads)
        avg_s = safe_mean(spreads)
        min_s = min(spreads)
        max_s = max(spreads)
        med_s = safe_median(spreads)
        print(f"{label:<20} {avg_s:>10.2f} {min_s:>8.2f} {max_s:>8.2f} {med_s:>8.2f} {len(spreads):>9d}")
        a6_data.append({'slot': label, 'avg': round(avg_s, 4), 'min': round(min_s, 4), 'max': round(max_s, 4), 'median': round(med_s, 4), 'count': len(spreads)})

    if gun_spreads:
        print("-" * 65)
        print(f"{'GUN ORTALAMA':<20} {safe_mean(gun_spreads):>10.2f} {min(gun_spreads):>8.2f} "
              f"{max(gun_spreads):>8.2f} {safe_median(gun_spreads):>8.2f} {len(gun_spreads):>9d}")
    json_data['analyses']['6_hourly_spread'] = a6_data

    # ==================================================================
    # ANALIZ 7: SAAT BAZLI ORTALAMA LOT BUYUKLUGU
    # ==================================================================
    print()
    print("=" * 70)
    print(f"ANALIZ 7 -- SAAT BAZLI ORTALAMA LOT BUYUKLUGU [{short_name}]")
    print("=" * 70)
    print(f"{'Saat':<20} {'Ort Lot':>8} {'Medyan':>8} {'Std':>8} {'Min':>6} {'Max':>6} {'Islem':>7}")
    print("-" * 65)

    a7_data = []
    for si, (label, _, _) in enumerate(HOUR_SLOTS):
        indices = hourly_trades.get(si, [])
        lots = [real_trades[i]['volume'] for i in indices]
        if not lots:
            print(f"{label:<20} {'--':>8} {'--':>8} {'--':>8} {'--':>6} {'--':>6} {0:>7d}")
            continue
        print(f"{label:<20} {safe_mean(lots):>8.2f} {safe_median(lots):>8.1f} {safe_std(lots):>8.2f} "
              f"{min(lots):>6d} {max(lots):>6d} {len(lots):>7d}")
        a7_data.append({'slot': label, 'avg': round(safe_mean(lots), 2), 'median': safe_median(lots), 'std': round(safe_std(lots), 2), 'min': min(lots), 'max': max(lots), 'count': len(lots)})
    json_data['analyses']['7_hourly_lot_size'] = a7_data

    # ==================================================================
    # ANALIZ 8: SAAT BAZLI TICK VELOCITY
    # ==================================================================
    print()
    print("=" * 70)
    print(f"ANALIZ 8 -- SAAT BAZLI TICK VELOCITY [{short_name}]")
    print("=" * 70)
    print(f"{'Saat':<20} {'Tum Tick':>9} {'Gercek':>8} {'Tick/dk':>8} {'Gercek/dk':>10}")
    print("-" * 58)

    a8_data = []
    for si, (label, s_min, e_min) in enumerate(HOUR_SLOTS):
        n_all = len(hourly_all.get(si, []))
        n_real = len(hourly_trades.get(si, []))
        dakika = e_min - s_min
        if dakika <= 0:
            dakika = 1
        tick_dk = n_all / dakika
        real_dk = n_real / dakika
        print(f"{label:<20} {n_all:>9d} {n_real:>8d} {tick_dk:>8.1f} {real_dk:>10.2f}")
        a8_data.append({'slot': label, 'total_ticks': n_all, 'real_trades': n_real, 'tick_per_min': round(tick_dk, 1), 'trade_per_min': round(real_dk, 2)})
    json_data['analyses']['8_tick_velocity'] = a8_data

    # ==================================================================
    # ANALIZ 9: TICK RESPONSE TIME / ALGO vs INSAN
    # ==================================================================
    print()
    print("=" * 70)
    print(f"ANALIZ 9 -- TICK RESPONSE TIME / ALGO vs INSAN [{short_name}]")
    print("=" * 70)

    a9_data = {}
    if total_real >= 2:
        # Tum response time'lari tek geciste hesapla
        response_times = []
        prev_msc = real_trades[0]['time_msc']
        for i in range(1, total_real):
            dt_ms = real_trades[i]['time_msc'] - prev_msc
            prev_msc = real_trades[i]['time_msc']
            if dt_ms > 0:
                response_times.append(dt_ms)

        # Siniflandirma — tek gecis
        algo_hft = algo_slow = algo_semi = human_fast = human_slow = gap = 0
        for r in response_times:
            if r < 10:
                algo_hft += 1
            elif r < 100:
                algo_slow += 1
            elif r < 500:
                algo_semi += 1
            elif r < 2000:
                human_fast += 1
            elif r < 10000:
                human_slow += 1
            else:
                gap += 1
        total_rt = len(response_times)

        print(f"  < 10ms  (HFT/Algo):          {algo_hft:>6d}  ({algo_hft * 100 / max(total_rt, 1):>5.1f}%)")
        print(f"  10-100ms (Yavas Algo):        {algo_slow:>6d}  ({algo_slow * 100 / max(total_rt, 1):>5.1f}%)")
        print(f"  100-500ms (Yari-otomatik):    {algo_semi:>6d}  ({algo_semi * 100 / max(total_rt, 1):>5.1f}%)")
        print(f"  500ms-2sn (Hizli Insan):      {human_fast:>6d}  ({human_fast * 100 / max(total_rt, 1):>5.1f}%)")
        print(f"  2-10sn (Yavas Insan):         {human_slow:>6d}  ({human_slow * 100 / max(total_rt, 1):>5.1f}%)")
        print(f"  > 10sn (Bosluk/Sessizlik):    {gap:>6d}  ({gap * 100 / max(total_rt, 1):>5.1f}%)")
        print()
        algo_total = algo_hft + algo_slow + algo_semi
        human_total = human_fast + human_slow
        active = algo_total + human_total
        if active > 0:
            print(f"  Algo orani (< 500ms):         {algo_total * 100 / active:>5.1f}%")
            print(f"  Insan orani (500ms-10sn):     {human_total * 100 / active:>5.1f}%")
        if response_times:
            rt_sorted = sorted(response_times)
            print(f"  Min response:    {rt_sorted[0]:>8d} ms")
            print(f"  Medyan response: {int(safe_median(response_times)):>8d} ms")
            print(f"  Ortalama:        {int(safe_mean(response_times)):>8d} ms")
            print(f"  Max response:    {rt_sorted[-1]:>8d} ms")

        a9_data = {
            'hft': algo_hft, 'slow_algo': algo_slow, 'semi_auto': algo_semi,
            'fast_human': human_fast, 'slow_human': human_slow, 'gap': gap,
            'algo_pct': round(algo_total * 100 / max(active, 1), 1),
            'human_pct': round(human_total * 100 / max(active, 1), 1),
            'min_ms': rt_sorted[0] if response_times else 0,
            'median_ms': int(safe_median(response_times)),
            'mean_ms': int(safe_mean(response_times)),
            'max_ms': rt_sorted[-1] if response_times else 0,
        }

        # Saat bazli algo orani — ön-gruplanmis indekslerle
        print()
        print(f"  Saat bazli algo orani (< 500ms / aktif):")
        a9_hourly = []
        for si, (label, _, _) in enumerate(HOUR_SLOTS):
            indices = hourly_trades.get(si, [])
            if len(indices) < 2:
                continue
            slot_rts = []
            for k in range(1, len(indices)):
                dt_ms = real_trades[indices[k]]['time_msc'] - real_trades[indices[k] - 1]['time_msc']
                if 0 < dt_ms < 10000:
                    slot_rts.append(dt_ms)
            if slot_rts:
                s_algo = sum(1 for r in slot_rts if r < 500)
                pct = s_algo * 100 / len(slot_rts)
                print(f"    {label}: {pct:>5.1f}% algo ({s_algo}/{len(slot_rts)})")
                a9_hourly.append({'slot': label, 'algo_pct': round(pct, 1), 'algo_cnt': s_algo, 'total': len(slot_rts)})
        a9_data['hourly'] = a9_hourly
    else:
        print("  Yeterli veri yok (< 2 gercek islem)")
    json_data['analyses']['9_response_time'] = a9_data

    # ==================================================================
    # ANALIZ 10: VOLUME PROFILE
    # ==================================================================
    print()
    print("=" * 70)
    print(f"ANALIZ 10 -- VOLUME PROFILE (Fiyat Bazli Hacim) [{short_name}]")
    print("=" * 70)

    a10_data = {}
    if real_trades:
        tick_size = tick_size_from_mt5 if tick_size_from_mt5 > 0 else 0.05

        # Fiyat bazli hacim — tek gecis
        price_volume = defaultdict(lambda: [0, 0, 0])  # [total, buy, sell]
        min_price = float('inf')
        max_price = 0.0
        total_volume = 0
        for t in real_trades:
            p = round(t['last'] / tick_size) * tick_size
            p = round(p, 4)
            v = t['volume']
            d = t['direction']
            pv = price_volume[p]
            pv[0] += v
            total_volume += v
            if d == DIR_BUY:
                pv[1] += v
            elif d == DIR_SELL:
                pv[2] += v
            if t['last'] < min_price:
                min_price = t['last']
            if t['last'] > max_price:
                max_price = t['last']

        # POC
        poc_price = max(price_volume, key=lambda p: price_volume[p][0])
        poc_volume = price_volume[poc_price][0]

        # Value Area (%70)
        sorted_by_vol = sorted(price_volume.items(), key=lambda x: x[1][0], reverse=True)
        va_volume = 0
        va_prices = []
        target = total_volume * 0.7
        for p, v in sorted_by_vol:
            va_volume += v[0]
            va_prices.append(p)
            if va_volume >= target:
                break
        va_high = max(va_prices) if va_prices else max_price
        va_low = min(va_prices) if va_prices else min_price

        print(f"  POC (en cok hacim): {poc_price:.2f} TL ({poc_volume} lot)")
        print(f"  Value Area (%%70):  {va_low:.2f} - {va_high:.2f} TL")
        print(f"  Fiyat araligi:     {min_price:.2f} - {max_price:.2f} TL")
        print(f"  Toplam hacim:      {total_volume} lot")
        print()

        max_vol_display = max(v[0] for v in price_volume.values())
        print(f"  {'Fiyat':>9} {'Hacim':>7} {'BUY':>6} {'SELL':>6} {'Bar'}")
        print(f"  {'-' * 9} {'-' * 7} {'-' * 6} {'-' * 6} {'-' * 30}")
        for p in sorted(price_volume.keys()):
            v = price_volume[p]
            bar_len = int(v[0] / max(max_vol_display, 1) * 30)
            bar = "|" * bar_len
            marks = ""
            if p == poc_price:
                marks += " <-- POC"
            if va_low <= p <= va_high:
                marks += " [VA]"
            print(f"  {p:>9.2f} {v[0]:>7d} {v[1]:>6d} {v[2]:>6d} {bar}{marks}")

        a10_data = {
            'poc_price': round(poc_price, 4), 'poc_volume': poc_volume,
            'va_low': round(va_low, 4), 'va_high': round(va_high, 4),
            'min_price': round(min_price, 4), 'max_price': round(max_price, 4),
            'total_volume': total_volume,
            'profile': {str(round(p, 4)): {'total': v[0], 'buy': v[1], 'sell': v[2]} for p, v in sorted(price_volume.items())},
        }
    else:
        print("  Yeterli veri yok")
    json_data['analyses']['10_volume_profile'] = a10_data

    # ==================================================================
    # ANALIZ 11: LOT DAGILIMI PARMAK IZI
    # ==================================================================
    print()
    print("=" * 70)
    print(f"ANALIZ 11 -- LOT DAGILIMI PARMAK IZI [{short_name}]")
    print("=" * 70)

    a11_data = {}
    if real_trades:
        # Tek geciste lot counter + yon bazli counter
        lot_counter = Counter()
        lot_buy_counter = Counter()
        lot_sell_counter = Counter()
        for t in real_trades:
            v = t['volume']
            lot_counter[v] += 1
            if t['direction'] == DIR_BUY:
                lot_buy_counter[v] += 1
            elif t['direction'] == DIR_SELL:
                lot_sell_counter[v] += 1

        total_trades_cnt = total_real
        print(f"  {'Lot':>5} {'Sayi':>6} {'Oran':>7} {'BUY':>5} {'SELL':>5} {'BUY%':>6} {'Durum'}")
        print(f"  {'-' * 5} {'-' * 6} {'-' * 7} {'-' * 5} {'-' * 5} {'-' * 6} {'-' * 15}")

        sorted_lots = sorted(lot_counter.keys())
        lot_details = []

        # Zipf bazli beklenti: lot_1_count / lot_size
        lot_1_count = lot_counter.get(1, 0)

        prev_count = None
        for lot_size in sorted_lots:
            count = lot_counter[lot_size]
            pct = count * 100 / total_trades_cnt
            b = lot_buy_counter.get(lot_size, 0)
            s = lot_sell_counter.get(lot_size, 0)
            buy_pct = b * 100 / count if count > 0 else 0

            durum = ""
            # Zipf beklentisi: count ~ lot_1_count / lot_size
            if lot_1_count > 0 and lot_size > 1:
                expected = lot_1_count / lot_size
                if count > expected * 2.5 and count >= 5:
                    durum = "ANORMAL (yuksek)"
            if count >= 5 and (buy_pct > 80 or buy_pct < 20):
                durum += " TEK YON" if not durum else " + TEK YON"
            prev_count = count

            print(f"  {lot_size:>5d} {count:>6d} {pct:>6.1f}% {b:>5d} {s:>5d} {buy_pct:>5.0f}% {durum}")
            lot_details.append({'lot': lot_size, 'count': count, 'pct': round(pct, 1), 'buy': b, 'sell': s, 'buy_pct': round(buy_pct, 1), 'flag': durum.strip()})

        # Yuvarlak lot analizi
        round_lot_sizes = [5, 10, 15, 20, 25, 50]
        round_total = sum(lot_counter.get(ls, 0) for ls in round_lot_sizes)
        print(f"\n  Yuvarlak lot toplami: {round_total} islem ({round_total * 100 / max(total_trades_cnt, 1):.1f}%)")
        print(f"  [Yuvarlak lot = kurumsal trader isareti]")

        a11_data = {'lots': lot_details, 'round_lot_count': round_total, 'round_lot_pct': round(round_total * 100 / max(total_trades_cnt, 1), 1)}
    else:
        print("  Yeterli veri yok")
    json_data['analyses']['11_lot_fingerprint'] = a11_data

    # ==================================================================
    # ANALIZ 12: SPREAD ASIMETRISI
    # ==================================================================
    print()
    print("=" * 70)
    print(f"ANALIZ 12 -- SPREAD ASIMETRISI [{short_name}]")
    print("=" * 70)

    a12_data = []
    if len(all_ticks) >= 2:
        print(f"  Spread asimetrisi = (ask_degisim - bid_degisim) / spread")
        print(f"  > 0: ask daha cok hareket etti -> alis baskisi")
        print(f"  < 0: bid daha cok hareket etti -> satis baskisi")
        print()
        print(f"  {'Saat':<20} {'Ort Asimetri':>12} {'Alis Baski':>10} {'Satis Baski':>12} {'Notr':>6}")
        print(f"  {'-' * 60}")

        for si, (label, _, _) in enumerate(HOUR_SLOTS):
            indices = hourly_all.get(si, [])
            if len(indices) < 2:
                continue
            asym_sum = 0.0
            asym_count = 0
            alis_cnt = satis_cnt = notr_cnt = 0
            for k in range(1, len(indices)):
                cur = all_ticks[indices[k]]
                prev = all_ticks[indices[k - 1]]
                bid_change = cur['bid'] - prev['bid']
                ask_change = cur['ask'] - prev['ask']
                spread = cur['spread']
                if spread > 0 and (abs(bid_change) > 0.001 or abs(ask_change) > 0.001):
                    asym = (ask_change - bid_change) / spread
                    asym_sum += asym
                    asym_count += 1
                    if asym > 0.1:
                        alis_cnt += 1
                    elif asym < -0.1:
                        satis_cnt += 1
                    else:
                        notr_cnt += 1
            if asym_count > 0:
                avg_asym = asym_sum / asym_count
                print(f"  {label:<20} {avg_asym:>+12.4f} {alis_cnt:>10d} {satis_cnt:>12d} {notr_cnt:>6d}")
                a12_data.append({'slot': label, 'avg_asymmetry': round(avg_asym, 6), 'buy_pressure': alis_cnt, 'sell_pressure': satis_cnt, 'neutral': notr_cnt})
    else:
        print("  Yeterli veri yok")
    json_data['analyses']['12_spread_asymmetry'] = a12_data

    # ==================================================================
    # ANALIZ 13: ISLEM ARASI BEKLEME SURESI DAGILIMI
    # ==================================================================
    print()
    print("=" * 70)
    print(f"ANALIZ 13 -- ISLEM ARASI BEKLEME SURESI [{short_name}]")
    print("=" * 70)

    a13_data = {}
    if total_real >= 2:
        # Tek gecis — response_times zaten hesaplandi ama burada saniye cinsinden lazim
        wait_times = []
        for i in range(1, total_real):
            dt_sec = (real_trades[i]['time_msc'] - real_trades[i - 1]['time_msc']) / 1000.0
            if dt_sec > 0:
                wait_times.append(dt_sec)

        cluster_fast = normal_1 = normal_2 = slow_1 = slow_2 = gap_w = 0
        for w in wait_times:
            if w < 5:
                cluster_fast += 1
            elif w < 30:
                normal_1 += 1
            elif w < 60:
                normal_2 += 1
            elif w < 180:
                slow_1 += 1
            elif w < 300:
                slow_2 += 1
            else:
                gap_w += 1
        total_wt = len(wait_times)

        print(f"  < 5sn   (Cluster/Patlama):    {cluster_fast:>6d}  ({cluster_fast * 100 / max(total_wt, 1):>5.1f}%)")
        print(f"  5-30sn  (Normal):             {normal_1:>6d}  ({normal_1 * 100 / max(total_wt, 1):>5.1f}%)")
        print(f"  30-60sn (Yavas):              {normal_2:>6d}  ({normal_2 * 100 / max(total_wt, 1):>5.1f}%)")
        print(f"  1-3dk   (Sessiz):             {slow_1:>6d}  ({slow_1 * 100 / max(total_wt, 1):>5.1f}%)")
        print(f"  3-5dk   (Cok Sessiz):         {slow_2:>6d}  ({slow_2 * 100 / max(total_wt, 1):>5.1f}%)")
        print(f"  > 5dk   (Bosluk):             {gap_w:>6d}  ({gap_w * 100 / max(total_wt, 1):>5.1f}%)")
        print()

        wt_sorted = sorted(wait_times)
        print(f"  Min bekleme:     {wt_sorted[0]:>8.1f} sn")
        print(f"  Medyan bekleme:  {safe_median(wait_times):>8.1f} sn")
        print(f"  Ortalama:        {safe_mean(wait_times):>8.1f} sn")
        print(f"  Max bekleme:     {wt_sorted[-1]:>8.1f} sn")

        # En uzun 5 bosluk
        print()
        print(f"  En uzun 5 bosluk:")
        top5_idx = sorted(range(len(wait_times)), key=lambda i: wait_times[i], reverse=True)[:5]
        top5_gaps = []
        for idx in top5_idx:
            wt = wait_times[idx]
            t1 = format_time_msc(real_trades[idx]['time_msc'])
            t2 = format_time_msc(real_trades[idx + 1]['time_msc'])
            print(f"    {t1} -> {t2} : {wt:.0f} sn ({wt / 60:.1f} dk)")
            top5_gaps.append({'from': t1, 'to': t2, 'seconds': round(wt, 1)})

        a13_data = {
            'cluster': cluster_fast, 'normal': normal_1, 'slow': normal_2,
            'quiet': slow_1, 'very_quiet': slow_2, 'gap': gap_w,
            'min_sec': round(wt_sorted[0], 1), 'median_sec': round(safe_median(wait_times), 1),
            'mean_sec': round(safe_mean(wait_times), 1), 'max_sec': round(wt_sorted[-1], 1),
            'top5_gaps': top5_gaps,
        }
    else:
        print("  Yeterli veri yok")
    json_data['analyses']['13_wait_time'] = a13_data

    # ==================================================================
    # ANALIZ 14: 15DK WEIGHTED MOMENTUM HARITASI
    # ==================================================================
    print()
    print("=" * 70)
    print(f"ANALIZ 14 -- 15DK WEIGHTED MOMENTUM [{short_name}]")
    print("=" * 70)
    print(f"  momentum = fiyat_degisim * abs(volume_delta)")
    print(f"  Pozitif: guclu yukselis  |  Negatif: guclu dusus  |  0: hareketsiz")
    print()
    print(f"  {'Dilim':<10} {'Fiyat Deg':>10} {'Vol Delta':>10} {'Momentum':>10} {'Yon'}")
    print(f"  {'-' * 55}")

    a14_data = []
    for si, (label, _, _) in enumerate(FIFTEEN_MIN_SLOTS):
        indices = fifteen_min_trades.get(si, [])
        if not indices:
            continue
        first_t = real_trades[indices[0]]
        last_t = real_trades[indices[-1]]
        price_chg = last_t['last'] - first_t['last']
        _, _, bv, sv = _slot_buysell(indices)
        delta = bv - sv
        momentum = price_chg * abs(delta)

        yon = "YUKARI" if momentum > 0 else ("ASAGI" if momentum < 0 else "YATAY")
        if price_chg > 0 and delta < 0:
            yon += " [!UYUMSUZ]"
        elif price_chg < 0 and delta > 0:
            yon += " [!UYUMSUZ]"

        print(f"  {label:<10} {price_chg:>+10.2f} {delta:>+10d} {momentum:>+10.1f} {yon}")
        a14_data.append({'slot': label, 'price_chg': round(price_chg, 4), 'vol_delta': delta, 'momentum': round(momentum, 1), 'direction': yon})
    json_data['analyses']['14_momentum_map'] = a14_data

    # ==================================================================
    # ANALIZ 15: GUNLUK OZET
    # ==================================================================
    print()
    print("=" * 70)
    print(f"ANALIZ 15 -- GUNLUK OZET [{short_name}]")
    print("=" * 70)

    a15_data = {}
    if real_trades:
        acilis_fiyat = real_trades[0]['last']
        kapanis_fiyat = real_trades[-1]['last']
        en_yuksek = max(t['last'] for t in real_trades)
        en_dusuk = min(t['last'] for t in real_trades)
        gun_range = en_yuksek - en_dusuk
        avg_spread = safe_mean(gun_spreads) if gun_spreads else 0
        avg_lot = safe_mean([t['volume'] for t in real_trades])

        # Buyuk islem hacimleri
        bb_vol = sum(t['volume'] for t in real_trades if t['direction'] == DIR_BUY and t['volume'] >= BIG_TRADE_THRESHOLD)
        bs_vol = sum(t['volume'] for t in real_trades if t['direction'] == DIR_SELL and t['volume'] >= BIG_TRADE_THRESHOLD)

        print(f"  Tarih:                 {DATE_STR} ({WEEKDAY})")
        print(f"  Kontrat:               {symbol}")
        print(f"  Toplam tick:           {total_raw}")
        print(f"  Gercek islem:          {total_real}")
        print(f"  Gercek islem orani:    {total_real * 100 / max(total_raw, 1):.1f}%")
        print(f"  Acilis:                {acilis_fiyat:.2f}")
        print(f"  Kapanis:               {kapanis_fiyat:.2f}")
        print(f"  En Yuksek:             {en_yuksek:.2f}")
        print(f"  En Dusuk:              {en_dusuk:.2f}")
        print(f"  Gun Araligi:           {gun_range:.2f} TL")
        deg = kapanis_fiyat - acilis_fiyat
        print(f"  Gun Degisim:           {deg:+.2f} TL ({deg * 100 / acilis_fiyat:+.2f}%)")
        print(f"  Toplam Hacim:          {gun_buy_vol + gun_sell_vol} lot")
        total_vol = gun_buy_vol + gun_sell_vol
        print(f"  BUY Hacim:             {gun_buy_vol} lot ({gun_buy_vol * 100 / max(total_vol, 1):.0f}%)")
        print(f"  SELL Hacim:            {gun_sell_vol} lot ({gun_sell_vol * 100 / max(total_vol, 1):.0f}%)")
        print(f"  Volume Delta:          {gun_delta:+d} lot")
        print(f"  Gun Yonu:              {yon}")
        print(f"  Ort Spread:            {avg_spread:.2f} TL")
        print(f"  Ort Lot Buyuklugu:     {avg_lot:.2f}")
        print(f"  Buyuk Islem (4+):      {total_bb + total_bs} adet (BUY:{total_bb} SELL:{total_bs})")
        if total_bb + total_bs > 0:
            big_buy_ratio = total_bb * 100 / (total_bb + total_bs)
            print(f"  Buyuk Islem BUY%:      {big_buy_ratio:.0f}%")
            print(f"  Buyuk Islem Asimetri:  {total_bb}:{total_bs} (BUY:SELL)")
        print(f"  Agresor Degisim:       {gecis_count} kez")
        if toplam_karsilastirma > 0:
            print(f"  Fiyat-Delta Uyum:      {uyumlu}/{toplam_karsilastirma} ({uyumlu * 100 // max(toplam_karsilastirma, 1)}%)")

        a15_data = {
            'open': round(acilis_fiyat, 4), 'close': round(kapanis_fiyat, 4),
            'high': round(en_yuksek, 4), 'low': round(en_dusuk, 4),
            'range': round(gun_range, 4), 'change': round(deg, 4),
            'change_pct': round(deg * 100 / acilis_fiyat, 2),
            'total_volume': total_vol, 'buy_volume': gun_buy_vol, 'sell_volume': gun_sell_vol,
            'volume_delta': gun_delta,
            'avg_spread': round(avg_spread, 4), 'avg_lot': round(avg_lot, 2),
            'big_trades': total_bb + total_bs, 'big_buy': total_bb, 'big_sell': total_bs,
            'aggressor_shifts': gecis_count,
            'alignment_ratio': f"{uyumlu}/{toplam_karsilastirma}" if toplam_karsilastirma > 0 else "N/A",
        }
    json_data['analyses']['15_daily_summary'] = a15_data

    return json_data


# ============================================================================
# MARKET BOOK TESTI (EK)
# ============================================================================

def test_market_book(symbol):
    """Market book (emir defteri) testi — seans icinde calistirilmali"""
    print()
    print("=" * 70)
    print(f"EK: MARKET BOOK TESTI [{symbol}]")
    print("=" * 70)

    result = mt5.market_book_add(symbol)
    if not result:
        print(f"  [BASARISIZ] market_book_add({symbol}) False dondu.")
        print(f"  GCM bu kontrat icin emir defteri saglamiyor olabilir.")
        print(f"  Veya piyasa kapali.")
        return None

    print(f"  [OK] market_book_add({symbol}) basarili")
    time.sleep(1)

    book = mt5.market_book_get(symbol)
    mt5.market_book_release(symbol)

    if book is None or len(book) == 0:
        print(f"  [BOS] market_book_get bos dondu. Piyasa kapali olabilir.")
        return None

    print(f"  Emir defteri derinligi: {len(book)} seviye")
    print()
    print(f"  {'Tip':<8} {'Fiyat':>10} {'Hacim':>8}")
    print(f"  {'-' * 30}")

    book_data = []
    for b in book:
        tip = "SELL" if b.type == mt5.BOOK_TYPE_SELL else "BUY"
        print(f"  {tip:<8} {b.price:>10.2f} {b.volume:>8.0f}")
        book_data.append({'type': tip, 'price': b.price, 'volume': int(b.volume)})

    print(f"\n  [OK] market_book_release({symbol})")
    return book_data


# ============================================================================
# ANA PROGRAM
# ============================================================================

def main():
    run_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("=" * 70)
    print(f"USTAT v5.0 — Gunluk Tick Veri Toplama ve Analiz (Optimize)")
    print(f"Tarih: {DATE_STR} ({WEEKDAY})")
    print(f"Kontratlar: {', '.join(SYMBOLS)}")
    print(f"Seans: 09:45-17:30 TR / 06:45-14:30 UTC")
    print(f"Yon belirleme: last vs bid/ask proximity (inferred)")
    print(f"Calistirma: {run_time}")
    print("=" * 70)

    # MT5 baglantisi
    if not mt5.initialize():
        print(f"[HATA] MT5 baslatilamadi: {mt5.last_error()}")
        return

    info = mt5.account_info()
    if info:
        print(f"[OK] MT5 -- Hesap: {info.login}, Bakiye: {info.balance}")
    else:
        print("[HATA] Hesap bilgisi alinamadi")
        mt5.shutdown()
        return

    # Seans zamanlari (UTC)
    utc_start = datetime(
        ANALYSIS_DATE.year, ANALYSIS_DATE.month, ANALYSIS_DATE.day,
        SESSION_START_UTC_H, SESSION_START_UTC_M, 0,
        tzinfo=timezone.utc
    )
    utc_end = datetime(
        ANALYSIS_DATE.year, ANALYSIS_DATE.month, ANALYSIS_DATE.day,
        SESSION_END_UTC_H, SESSION_END_UTC_M, 0,
        tzinfo=timezone.utc
    )

    print(f"\nTick verisi cekiliyor ({DATE_STR})...")

    all_json_results = {
        'date': DATE_STR,
        'weekday': WEEKDAY,
        'run_time': run_time,
        'symbols': {},
    }

    all_results = {}

    for symbol in SYMBOLS:
        # Dinamik tick_size
        sym_info = mt5.symbol_info(symbol)
        tick_size = 0.05  # fallback
        if sym_info:
            tick_size = sym_info.trade_tick_size if sym_info.trade_tick_size > 0 else 0.05

        ticks = mt5.copy_ticks_range(symbol, utc_start, utc_end, mt5.COPY_TICKS_ALL)
        if ticks is None or len(ticks) == 0:
            print(f"  [UYARI] {symbol}: Tick verisi alinamadi veya bos!")
            continue

        print(f"  [OK] {symbol}: {len(ticks)} tick cekildi (tick_size={tick_size})")

        # numpy structured array -> list of dict (tek gecis)
        tick_list = []
        for t in ticks:
            tick_list.append({
                'time': int(t['time']),
                'time_msc': int(t['time_msc']),
                'bid': float(t['bid']),
                'ask': float(t['ask']),
                'last': float(t['last']),
                'volume': int(t['volume']),
                'flags': int(t['flags']),
            })

        symbol_json = analyze_symbol(symbol, tick_list, tick_size)
        all_json_results['symbols'][symbol] = symbol_json
        all_results[symbol] = symbol_json

    # Market book testi (seans aciksa)
    print()
    print("=" * 70)
    print("MARKET BOOK TESTLERI")
    print("=" * 70)
    for symbol in SYMBOLS:
        book_data = test_market_book(symbol)
        if book_data and symbol in all_json_results['symbols']:
            all_json_results['symbols'][symbol]['market_book'] = book_data

    # Kontratlar arasi karsilastirma
    if len(all_results) >= 2:
        print()
        print()
        print("######################################################################")
        print("#  KONTRATLAR ARASI KARSILASTIRMA")
        print("######################################################################")
        print()
        print(f"  {'Metrik':<25}", end="")
        for sym in all_results:
            short = all_results[sym]['short_name']
            print(f" {short:>12}", end="")
        print()
        print(f"  {'-' * 25}", end="")
        for _ in all_results:
            print(f" {'-' * 12}", end="")
        print()

        def _print_metric(label, extractor):
            print(f"  {label:<25}", end="")
            for sym, data in all_results.items():
                val = extractor(data)
                if isinstance(val, float):
                    print(f" {val:>12.2f}", end="")
                elif isinstance(val, str):
                    print(f" {val:>12}", end="")
                else:
                    print(f" {val:>12d}", end="")
            print()

        _print_metric("Toplam islem", lambda d: d['real_trades'])
        _print_metric("Volume Delta",
                       lambda d: d['analyses'].get('15_daily_summary', {}).get('volume_delta', 0))
        _print_metric("Buyuk islem (4+)",
                       lambda d: d['analyses'].get('15_daily_summary', {}).get('big_trades', 0))
        _print_metric("BUY%",
                       lambda d: f"{d['buy_count'] * 100 / max(d['real_trades'], 1):.1f}%")
        _print_metric("Ort Spread",
                       lambda d: d['analyses'].get('15_daily_summary', {}).get('avg_spread', 0.0))
        _print_metric("Ort Lot",
                       lambda d: d['analyses'].get('15_daily_summary', {}).get('avg_lot', 0.0))

        # JSON'a da ekle
        comparison = {}
        for sym, data in all_results.items():
            summary = data['analyses'].get('15_daily_summary', {})
            comparison[sym] = {
                'real_trades': data['real_trades'],
                'volume_delta': summary.get('volume_delta', 0),
                'big_trades': summary.get('big_trades', 0),
                'buy_pct': round(data['buy_count'] * 100 / max(data['real_trades'], 1), 1),
                'avg_spread': summary.get('avg_spread', 0),
                'avg_lot': summary.get('avg_lot', 0),
            }
        all_json_results['comparison'] = comparison

    # JSON cikti
    json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), JSON_OUTPUT)
    try:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(all_json_results, f, ensure_ascii=False, indent=2)
        print(f"\n[OK] JSON cikti: {json_path}")
    except Exception as e:
        print(f"\n[HATA] JSON yazma hatasi: {e}")

    print()
    print(f"[OK] Analiz tamamlandi: {DATE_STR}")
    print(f"[OK] MT5 baglanti kapatiliyor...")
    mt5.shutdown()
    print(f"[OK] Bitti.")


if __name__ == "__main__":
    main()
