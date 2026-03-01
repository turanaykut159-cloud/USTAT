# -*- coding: utf-8 -*-
"""
USTAT v5.0 — Gunluk Tick Veri Toplama ve Analiz Scripti
Amac: OGUL yeni motor parametre kalibrasyonu icin 5 gunluk veri toplama
Tarih: 2-6 Mart 2026 arasi her gun seans sonrasi calistirilacak
Kontratlar: F_THYAO0426, F_AKBNK0426, F_ASELS0426
Seans: 09:45-17:30 TR / 06:45-14:30 UTC

Kullanim:
  python C:\USTAT\tests\daily_tick_collector.py > C:\USTAT\tests\daily_YYYYMMDD.txt 2>&1

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
import numpy as np
from datetime import datetime, timedelta, timezone
from collections import Counter, defaultdict
import time
import sys
import os

# ============================================================================
# YAPILANDIRMA
# ============================================================================

SYMBOLS = ["F_THYAO0426", "F_AKBNK0426", "F_ASELS0426"]
BIG_TRADE_THRESHOLD = 4  # 27 Subat verisinden: ort + 2*std

# Seans zamanlari (UTC)
SESSION_START_UTC_H = 6
SESSION_START_UTC_M = 45
SESSION_END_UTC_H = 14
SESSION_END_UTC_M = 30

# Bugunun tarihini al (veya parametre olarak gec)
if len(sys.argv) > 1:
    # python script.py 20260302 gibi tarih parametresi
    date_str = sys.argv[1]
    ANALYSIS_DATE = datetime(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:8]))
else:
    ANALYSIS_DATE = datetime.now()

DATE_STR = ANALYSIS_DATE.strftime("%Y-%m-%d")
WEEKDAY = ["Pazartesi","Sali","Carsamba","Persembe","Cuma","Cumartesi","Pazar"][ANALYSIS_DATE.weekday()]


# ============================================================================
# YARDIMCI FONKSIYONLAR
# ============================================================================

def classify_trade(tick):
    """last fiyatinin bid/ask konumuna gore yon belirle"""
    if tick['last'] <= 0 or tick['bid'] <= 0 or tick['ask'] <= 0:
        return 'NEUTRAL'
    if tick['volume'] <= 0:
        return 'NEUTRAL'
    if tick['last'] <= tick['bid']:
        return 'SELL'
    if tick['last'] >= tick['ask']:
        return 'BUY'
    mid = (tick['bid'] + tick['ask']) / 2.0
    if tick['last'] >= mid:
        return 'BUY'
    else:
        return 'SELL'


def is_real_trade(tick):
    """Gercek islem tick'i mi? (BUY veya SELL flag'i var VE volume > 0)"""
    has_buy = (tick['flags'] & 0x08) != 0   # TICK_FLAG_LAST
    has_vol = (tick['flags'] & 0x10) != 0   # TICK_FLAG_VOLUME
    return has_buy and has_vol and tick['volume'] > 0 and tick['last'] > 0


def get_hour_slot(time_msc, start_h=9, start_m=45):
    """time_msc'den TR saatini ve slot'unu hesapla"""
    utc_dt = datetime(1970, 1, 1) + timedelta(milliseconds=int(time_msc))
    tr_dt = utc_dt + timedelta(hours=3)  # UTC+3
    return tr_dt


def format_time_msc(time_msc):
    """time_msc'yi HH:MM:SS.mmm formatinda goster"""
    utc_dt = datetime(1970, 1, 1) + timedelta(milliseconds=int(time_msc))
    tr_dt = utc_dt + timedelta(hours=3)
    return tr_dt.strftime("%H:%M:%S.") + f"{tr_dt.microsecond // 1000:03d}"


def safe_mean(values):
    """Bos liste icin guvenli ortalama"""
    if not values:
        return 0.0
    return sum(values) / len(values)


def safe_median(values):
    """Bos liste icin guvenli medyan"""
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    if n % 2 == 0:
        return (s[n//2 - 1] + s[n//2]) / 2.0
    return s[n//2]


def safe_std(values):
    """Standart sapma"""
    if len(values) < 2:
        return 0.0
    m = safe_mean(values)
    return (sum((x - m) ** 2 for x in values) / (len(values) - 1)) ** 0.5


# ============================================================================
# SAAT DILIMI TANIMLARI
# ============================================================================

HOUR_SLOTS = [
    ("09:45-10:00", 9, 45, 10, 0),
    ("10:00-11:00", 10, 0, 11, 0),
    ("11:00-12:00", 11, 0, 12, 0),
    ("12:00-13:00", 12, 0, 13, 0),
    ("13:00-14:00", 13, 0, 14, 0),
    ("14:00-15:00", 14, 0, 15, 0),
    ("15:00-16:00", 15, 0, 16, 0),
    ("16:00-17:00", 16, 0, 17, 0),
    ("17:00-17:30", 17, 0, 17, 30),
]

FIFTEEN_MIN_SLOTS = []
for h in range(9, 18):
    for m in [0, 15, 30, 45]:
        end_h = h
        end_m = m + 15
        if end_m >= 60:
            end_h += 1
            end_m -= 60
        if h == 9 and m < 45:
            continue
        if h == 17 and m > 15:
            continue
        FIFTEEN_MIN_SLOTS.append((f"{h:02d}:{m:02d}", h, m, end_h, end_m))

FIVE_MIN_SLOTS = []
for h in range(9, 18):
    for m in range(0, 60, 5):
        end_h = h
        end_m = m + 5
        if end_m >= 60:
            end_h += 1
            end_m -= 60
        if h == 9 and m < 45:
            continue
        if h == 17 and m > 25:
            continue
        FIVE_MIN_SLOTS.append((f"{h:02d}:{m:02d}", h, m, end_h, end_m))


def tick_in_slot(tr_dt, sh, sm, eh, em):
    """TR datetime'in slot icerisinde olup olmadigini kontrol et"""
    tick_mins = tr_dt.hour * 60 + tr_dt.minute
    start_mins = sh * 60 + sm
    end_mins = eh * 60 + em
    return start_mins <= tick_mins < end_mins


# ============================================================================
# ANA ANALIZ FONKSIYONLARI
# ============================================================================

def analyze_symbol(symbol, ticks, all_ticks_raw):
    """Tek kontrat icin tum analizleri calistir"""

    # Gercek islemleri filtrele
    real_trades = []
    for t in ticks:
        if is_real_trade(t):
            direction = classify_trade(t)
            tr_dt = get_hour_slot(t['time_msc'])
            spread = t['ask'] - t['bid'] if t['ask'] > 0 and t['bid'] > 0 else 0
            real_trades.append({
                'time_msc': t['time_msc'],
                'tr_dt': tr_dt,
                'bid': t['bid'],
                'ask': t['ask'],
                'last': t['last'],
                'volume': int(t['volume']),
                'flags': int(t['flags']),
                'direction': direction,
                'spread': spread,
            })

    # Tum ticklerden spread ve bid/ask verisi (fiyat guncellemeleri dahil)
    all_ticks_with_time = []
    for t in all_ticks_raw:
        if t['bid'] > 0 and t['ask'] > 0:
            tr_dt = get_hour_slot(t['time_msc'])
            all_ticks_with_time.append({
                'time_msc': t['time_msc'],
                'tr_dt': tr_dt,
                'bid': t['bid'],
                'ask': t['ask'],
                'last': t['last'],
                'volume': int(t['volume']),
                'spread': t['ask'] - t['bid'],
            })

    short_name = symbol.split("_")[1].replace("0426", "")
    buy_count = len([t for t in real_trades if t['direction'] == 'BUY'])
    sell_count = len([t for t in real_trades if t['direction'] == 'SELL'])
    neutral_count = len([t for t in real_trades if t['direction'] == 'NEUTRAL'])

    print()
    print("######################################################################")
    print(f"#  {symbol} ({short_name}) -- {DATE_STR} TAM GUN ANALIZI")
    print(f"#  Toplam tick: {len(all_ticks_raw)}, Gecerli islem: {len(real_trades)}")
    print(f"#  at_bid(SELL): {sell_count} ({sell_count*100/max(len(real_trades),1):.0f}%)"
          f"  at_ask(BUY): {buy_count} ({buy_count*100/max(len(real_trades),1):.0f}%)"
          f"  neutral: {neutral_count}")
    print("######################################################################")

    # ==== ANALIZ 1: SAAT BAZLI BUY/SELL DAGILIMI ====
    print()
    print("=" * 70)
    print(f"ANALIZ 1 -- SAAT BAZLI ISLEM DAGILIMI (inferred) [{short_name}]")
    print("=" * 70)
    print(f"{'Saat':<20} {'BUY':>7} {'SELL':>7} {'Toplam':>8} {'BUY%':>7}")
    print("-" * 50)

    total_buy = total_sell = 0
    for label, sh, sm, eh, em in HOUR_SLOTS:
        b = len([t for t in real_trades if t['direction'] == 'BUY' and tick_in_slot(t['tr_dt'], sh, sm, eh, em)])
        s = len([t for t in real_trades if t['direction'] == 'SELL' and tick_in_slot(t['tr_dt'], sh, sm, eh, em)])
        tot = b + s
        pct = b * 100 / tot if tot > 0 else 0
        print(f"{label:<20} {b:>7d} {s:>7d} {tot:>8d} {pct:>6.1f}%")
        total_buy += b
        total_sell += s
    print("-" * 50)
    tot = total_buy + total_sell
    pct = total_buy * 100 / tot if tot > 0 else 0
    print(f"{'TOPLAM':<20} {total_buy:>7d} {total_sell:>7d} {tot:>8d} {pct:>6.1f}%")

    # ==== ANALIZ 2: SAAT BAZLI VOLUME DELTA ====
    print()
    print("=" * 70)
    print(f"ANALIZ 2 -- SAAT BAZLI VOLUME DELTA (inferred) [{short_name}]")
    print("=" * 70)
    print(f"{'Saat':<20} {'BUY Vol':>9} {'SELL Vol':>9} {'Delta':>9} {'Yon'}")
    print("-" * 60)

    gun_buy_vol = gun_sell_vol = 0
    for label, sh, sm, eh, em in HOUR_SLOTS:
        bv = sum(t['volume'] for t in real_trades if t['direction'] == 'BUY' and tick_in_slot(t['tr_dt'], sh, sm, eh, em))
        sv = sum(t['volume'] for t in real_trades if t['direction'] == 'SELL' and tick_in_slot(t['tr_dt'], sh, sm, eh, em))
        delta = bv - sv
        yon = "ALIS BASKIN" if delta > 0 else ("SATIS BASKIN" if delta < 0 else "NOTR")
        print(f"{label:<20} {bv:>9d} {sv:>9d} {delta:>+9d} {yon}")
        gun_buy_vol += bv
        gun_sell_vol += sv
    print("-" * 60)
    gun_delta = gun_buy_vol - gun_sell_vol
    yon = "ALIS BASKIN" if gun_delta > 0 else ("SATIS BASKIN" if gun_delta < 0 else "NOTR")
    print(f"{'GUN TOPLAM':<20} {gun_buy_vol:>9d} {gun_sell_vol:>9d} {gun_delta:>+9d} {yon}")

    # ==== ANALIZ 3: BUYUK ISLEMLER ====
    print()
    print("=" * 70)
    print(f"ANALIZ 3 -- BUYUK ISLEMLER ({BIG_TRADE_THRESHOLD}+ lot) [{short_name}]")
    print("=" * 70)
    print(f"{'Saat':<18} {'BigBUY':>7} {'BigSELL':>8} {'Toplam':>8} {'BuyVol':>8} {'SellVol':>8} {'MaxVol':>8}")
    print("-" * 70)

    total_bb = total_bs = 0
    for label, sh, sm, eh, em in HOUR_SLOTS:
        slot_trades = [t for t in real_trades if tick_in_slot(t['tr_dt'], sh, sm, eh, em)]
        bb = [t for t in slot_trades if t['direction'] == 'BUY' and t['volume'] >= BIG_TRADE_THRESHOLD]
        bs = [t for t in slot_trades if t['direction'] == 'SELL' and t['volume'] >= BIG_TRADE_THRESHOLD]
        bv = sum(t['volume'] for t in bb)
        sv = sum(t['volume'] for t in bs)
        mx = max([t['volume'] for t in bb + bs], default=0)
        print(f"{label:<18} {len(bb):>7d} {len(bs):>8d} {len(bb)+len(bs):>8d} {bv:>8d} {sv:>8d} {mx:>8d}")
        total_bb += len(bb)
        total_bs += len(bs)
    print("-" * 70)
    print(f"{'TOPLAM':<18} {total_bb:>7d} {total_bs:>8d} {total_bb+total_bs:>8d}")

    # ==== ANALIZ 4: FIYAT-DELTA UYUMU ====
    print()
    print("=" * 70)
    print(f"ANALIZ 4 -- FIYAT-DELTA UYUMU [{short_name}]")
    print("=" * 70)
    print(f"{'Saat':<20} {'Acilis':>9} {'Kapanis':>9} {'Degisim':>9} {'VolDelta':>9} {'Uyum'}")
    print("-" * 65)

    uyumlu = toplam_karsilastirma = 0
    for label, sh, sm, eh, em in HOUR_SLOTS:
        slot_trades = [t for t in real_trades if tick_in_slot(t['tr_dt'], sh, sm, eh, em)]
        if not slot_trades:
            print(f"{label:<20} {'--':>9} {'--':>9} {'--':>9} {'--':>9} --")
            continue
        acilis = slot_trades[0]['last']
        kapanis = slot_trades[-1]['last']
        degisim = kapanis - acilis
        bv = sum(t['volume'] for t in slot_trades if t['direction'] == 'BUY')
        sv = sum(t['volume'] for t in slot_trades if t['direction'] == 'SELL')
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

    if toplam_karsilastirma > 0:
        print(f"\nUyum orani: {uyumlu}/{toplam_karsilastirma} = %{uyumlu*100//toplam_karsilastirma}")

    # ==== ANALIZ 5: AGRESOR DEGISIM ANLARI (5dk pencere) ====
    print()
    print("=" * 70)
    print(f"ANALIZ 5 -- AGRESOR DEGISIM ANLARI [{short_name}]")
    print("=" * 70)
    print(f"{'Zaman':<14} {'BuyVol':>7} {'SellVol':>8} {'Delta':>8} {'Baskin':<18} {'Gecis'}")
    print("-" * 65)

    prev_baskin = None
    gecis_count = 0
    gecis_listesi = []

    for label, sh, sm, eh, em in FIVE_MIN_SLOTS:
        slot_trades = [t for t in real_trades if tick_in_slot(t['tr_dt'], sh, sm, eh, em)]
        if not slot_trades:
            continue
        bv = sum(t['volume'] for t in slot_trades if t['direction'] == 'BUY')
        sv = sum(t['volume'] for t in slot_trades if t['direction'] == 'SELL')
        delta = bv - sv

        if delta > 0:
            baskin = "ALIS BASKIN"
        elif delta < 0:
            baskin = "SATIS BASKIN"
        else:
            baskin = "NOTR"

        gecis_str = ""
        if prev_baskin and baskin != "NOTR" and prev_baskin != "NOTR" and baskin != prev_baskin:
            if prev_baskin == "ALIS BASKIN":
                gecis_str = "<<< BUY->SELL"
            else:
                gecis_str = "<<< SELL->BUY"
            gecis_count += 1
            gecis_listesi.append(f"  {label} {gecis_str}")

        print(f"{label:<14} {bv:>7d} {sv:>8d} {delta:>+8d} {baskin:<18} {gecis_str}")

        if baskin != "NOTR":
            prev_baskin = baskin

    print(f"\nToplam agresor degisimi: {gecis_count}")

    # ==== ANALIZ 6: SAAT BAZLI ORTALAMA SPREAD ====
    print()
    print("=" * 70)
    print(f"ANALIZ 6 -- SAAT BAZLI ORTALAMA SPREAD [{short_name}]")
    print("=" * 70)
    print(f"{'Saat':<20} {'Ort Spread':>10} {'Min':>8} {'Max':>8} {'Medyan':>8} {'Tick Say':>9}")
    print("-" * 65)

    gun_spreads = []
    for label, sh, sm, eh, em in HOUR_SLOTS:
        slot_ticks = [t for t in all_ticks_with_time if tick_in_slot(t['tr_dt'], sh, sm, eh, em)]
        spreads = [t['spread'] for t in slot_ticks if t['spread'] > 0]
        if not spreads:
            print(f"{label:<20} {'--':>10} {'--':>8} {'--':>8} {'--':>8} {0:>9d}")
            continue
        gun_spreads.extend(spreads)
        print(f"{label:<20} {safe_mean(spreads):>10.2f} {min(spreads):>8.2f} {max(spreads):>8.2f} "
              f"{safe_median(spreads):>8.2f} {len(spreads):>9d}")

    if gun_spreads:
        print("-" * 65)
        print(f"{'GUN ORTALAMA':<20} {safe_mean(gun_spreads):>10.2f} {min(gun_spreads):>8.2f} "
              f"{max(gun_spreads):>8.2f} {safe_median(gun_spreads):>8.2f} {len(gun_spreads):>9d}")

    # ==== ANALIZ 7: SAAT BAZLI ORTALAMA LOT BUYUKLUGU ====
    print()
    print("=" * 70)
    print(f"ANALIZ 7 -- SAAT BAZLI ORTALAMA LOT BUYUKLUGU [{short_name}]")
    print("=" * 70)
    print(f"{'Saat':<20} {'Ort Lot':>8} {'Medyan':>8} {'Std':>8} {'Min':>6} {'Max':>6} {'Islem':>7}")
    print("-" * 65)

    for label, sh, sm, eh, em in HOUR_SLOTS:
        slot_trades = [t for t in real_trades if tick_in_slot(t['tr_dt'], sh, sm, eh, em)]
        lots = [t['volume'] for t in slot_trades]
        if not lots:
            print(f"{label:<20} {'--':>8} {'--':>8} {'--':>8} {'--':>6} {'--':>6} {0:>7d}")
            continue
        print(f"{label:<20} {safe_mean(lots):>8.2f} {safe_median(lots):>8.1f} {safe_std(lots):>8.2f} "
              f"{min(lots):>6d} {max(lots):>6d} {len(lots):>7d}")

    # ==== ANALIZ 8: SAAT BAZLI TICK VELOCITY ====
    print()
    print("=" * 70)
    print(f"ANALIZ 8 -- SAAT BAZLI TICK VELOCITY [{short_name}]")
    print("=" * 70)
    print(f"{'Saat':<20} {'Tum Tick':>9} {'Gercek':>8} {'Tick/dk':>8} {'Gercek/dk':>10}")
    print("-" * 58)

    for label, sh, sm, eh, em in HOUR_SLOTS:
        slot_all = [t for t in all_ticks_with_time if tick_in_slot(t['tr_dt'], sh, sm, eh, em)]
        slot_real = [t for t in real_trades if tick_in_slot(t['tr_dt'], sh, sm, eh, em)]
        dakika = (eh * 60 + em - sh * 60 - sm)
        if dakika <= 0:
            dakika = 1
        tick_dk = len(slot_all) / dakika
        real_dk = len(slot_real) / dakika
        print(f"{label:<20} {len(slot_all):>9d} {len(slot_real):>8d} {tick_dk:>8.1f} {real_dk:>10.2f}")

    # ==== ANALIZ 9: TICK RESPONSE TIME (ALGO VS INSAN) ====
    print()
    print("=" * 70)
    print(f"ANALIZ 9 -- TICK RESPONSE TIME / ALGO vs INSAN [{short_name}]")
    print("=" * 70)

    if len(real_trades) >= 2:
        response_times = []
        for i in range(1, len(real_trades)):
            dt_ms = real_trades[i]['time_msc'] - real_trades[i-1]['time_msc']
            if dt_ms > 0:
                response_times.append(dt_ms)

        # Siniflandirma
        algo_hft = len([r for r in response_times if r < 10])
        algo_slow = len([r for r in response_times if 10 <= r < 100])
        algo_semi = len([r for r in response_times if 100 <= r < 500])
        human_fast = len([r for r in response_times if 500 <= r < 2000])
        human_slow = len([r for r in response_times if 2000 <= r < 10000])
        gap = len([r for r in response_times if r >= 10000])
        total_rt = len(response_times)

        print(f"  < 10ms  (HFT/Algo):          {algo_hft:>6d}  ({algo_hft*100/max(total_rt,1):>5.1f}%)")
        print(f"  10-100ms (Yavas Algo):        {algo_slow:>6d}  ({algo_slow*100/max(total_rt,1):>5.1f}%)")
        print(f"  100-500ms (Yari-otomatik):    {algo_semi:>6d}  ({algo_semi*100/max(total_rt,1):>5.1f}%)")
        print(f"  500ms-2sn (Hizli Insan):      {human_fast:>6d}  ({human_fast*100/max(total_rt,1):>5.1f}%)")
        print(f"  2-10sn (Yavas Insan):         {human_slow:>6d}  ({human_slow*100/max(total_rt,1):>5.1f}%)")
        print(f"  > 10sn (Bosluk/Sessizlik):    {gap:>6d}  ({gap*100/max(total_rt,1):>5.1f}%)")
        print()
        algo_total = algo_hft + algo_slow + algo_semi
        human_total = human_fast + human_slow
        active = algo_total + human_total
        if active > 0:
            print(f"  Algo orani (< 500ms):         {algo_total*100/active:>5.1f}%")
            print(f"  Insan orani (500ms-10sn):     {human_total*100/active:>5.1f}%")
        print(f"  Min response:    {min(response_times):>8d} ms")
        print(f"  Medyan response: {int(safe_median(response_times)):>8d} ms")
        print(f"  Ortalama:        {int(safe_mean(response_times)):>8d} ms")
        print(f"  Max response:    {max(response_times):>8d} ms")

        # Saat bazli algo orani
        print()
        print(f"  Saat bazli algo orani (< 500ms / aktif):")
        for label, sh, sm, eh, em in HOUR_SLOTS:
            slot_trades_idx = [i for i, t in enumerate(real_trades) if tick_in_slot(t['tr_dt'], sh, sm, eh, em)]
            if len(slot_trades_idx) < 2:
                continue
            slot_rts = []
            for idx in slot_trades_idx:
                if idx > 0:
                    dt_ms = real_trades[idx]['time_msc'] - real_trades[idx-1]['time_msc']
                    if 0 < dt_ms < 10000:
                        slot_rts.append(dt_ms)
            if slot_rts:
                s_algo = len([r for r in slot_rts if r < 500])
                print(f"    {label}: {s_algo*100/len(slot_rts):>5.1f}% algo ({s_algo}/{len(slot_rts)})")
    else:
        print("  Yeterli veri yok (< 2 gercek islem)")

    # ==== ANALIZ 10: VOLUME PROFILE ====
    print()
    print("=" * 70)
    print(f"ANALIZ 10 -- VOLUME PROFILE (Fiyat Bazli Hacim) [{short_name}]")
    print("=" * 70)

    if real_trades:
        # Fiyat seviyelerine gore hacim dagit
        # Tick size belirle (en kucuk fiyat farki)
        prices = [t['last'] for t in real_trades if t['last'] > 0]
        if prices:
            tick_size = 0.05  # VIOP standart tick
            min_price = min(prices)
            max_price = max(prices)

            # Fiyat bazli hacim
            price_volume = defaultdict(lambda: {'buy': 0, 'sell': 0, 'total': 0})
            for t in real_trades:
                p = round(t['last'] / tick_size) * tick_size  # tick_size'a yuvarla
                p = round(p, 2)
                price_volume[p]['total'] += t['volume']
                if t['direction'] == 'BUY':
                    price_volume[p]['buy'] += t['volume']
                elif t['direction'] == 'SELL':
                    price_volume[p]['sell'] += t['volume']

            # POC (en cok hacim)
            poc_price = max(price_volume, key=lambda p: price_volume[p]['total'])
            poc_volume = price_volume[poc_price]['total']
            total_volume = sum(v['total'] for v in price_volume.values())

            # Value Area (%70)
            sorted_prices = sorted(price_volume.items(), key=lambda x: x[1]['total'], reverse=True)
            va_volume = 0
            va_prices = []
            for p, v in sorted_prices:
                va_volume += v['total']
                va_prices.append(p)
                if va_volume >= total_volume * 0.7:
                    break
            va_high = max(va_prices) if va_prices else max_price
            va_low = min(va_prices) if va_prices else min_price

            print(f"  POC (en cok hacim): {poc_price:.2f} TL ({poc_volume} lot)")
            print(f"  Value Area (%%70):  {va_low:.2f} - {va_high:.2f} TL")
            print(f"  Fiyat araligi:     {min_price:.2f} - {max_price:.2f} TL")
            print(f"  Toplam hacim:      {total_volume} lot")
            print()

            # En yuksek 15 seviye
            print(f"  {'Fiyat':>9} {'Hacim':>7} {'BUY':>6} {'SELL':>6} {'Bar'}")
            print(f"  {'-'*9} {'-'*7} {'-'*6} {'-'*6} {'-'*30}")
            max_vol_display = max(v['total'] for v in price_volume.values())
            for p in sorted(price_volume.keys()):
                v = price_volume[p]
                bar_len = int(v['total'] / max(max_vol_display, 1) * 30)
                bar = "|" * bar_len
                poc_mark = " <-- POC" if p == poc_price else ""
                va_mark = " [VA]" if va_low <= p <= va_high else ""
                print(f"  {p:>9.2f} {v['total']:>7d} {v['buy']:>6d} {v['sell']:>6d} {bar}{poc_mark}{va_mark}")
    else:
        print("  Yeterli veri yok")

    # ==== ANALIZ 11: LOT DAGILIMI PARMAK IZI ====
    print()
    print("=" * 70)
    print(f"ANALIZ 11 -- LOT DAGILIMI PARMAK IZI [{short_name}]")
    print("=" * 70)

    if real_trades:
        lot_counter = Counter(t['volume'] for t in real_trades)
        total_trades = len(real_trades)

        # Beklenen: zipf dagilimi (1 lot en cok, buyudukce azalir)
        # Sapma: belirli bir lot anormal sikliktaysa -> sistematik oyuncu
        print(f"  {'Lot':>5} {'Sayi':>6} {'Oran':>7} {'BUY':>5} {'SELL':>5} {'BUY%':>6} {'Durum'}")
        print(f"  {'-'*5} {'-'*6} {'-'*7} {'-'*5} {'-'*5} {'-'*6} {'-'*15}")

        prev_count = None
        for lot_size in sorted(lot_counter.keys()):
            count = lot_counter[lot_size]
            pct = count * 100 / total_trades
            b = len([t for t in real_trades if t['volume'] == lot_size and t['direction'] == 'BUY'])
            s = len([t for t in real_trades if t['volume'] == lot_size and t['direction'] == 'SELL'])
            buy_pct = b * 100 / count if count > 0 else 0

            # Anormallik tespiti: onceki lot'tan daha sik mi?
            durum = ""
            if prev_count is not None and count > prev_count * 1.5 and lot_size > 1:
                durum = "ANORMAL (yuksek)"
            if count >= 5 and (buy_pct > 80 or buy_pct < 20):
                durum += " TEK YON"
            prev_count = count

            print(f"  {lot_size:>5d} {count:>6d} {pct:>6.1f}% {b:>5d} {s:>5d} {buy_pct:>5.0f}% {durum}")

        # Yuvarlak lot analizi
        round_lots = {5: 0, 10: 0, 15: 0, 20: 0, 25: 0, 50: 0}
        for lot_size, count in lot_counter.items():
            if lot_size in round_lots:
                round_lots[lot_size] = count
        round_total = sum(round_lots.values())
        print(f"\n  Yuvarlak lot toplami: {round_total} islem ({round_total*100/max(total_trades,1):.1f}%)")
        print(f"  [Yuvarlak lot = kurumsal trader isareti]")
    else:
        print("  Yeterli veri yok")

    # ==== ANALIZ 12: SPREAD ASIMETRISI ====
    print()
    print("=" * 70)
    print(f"ANALIZ 12 -- SPREAD ASIMETRISI [{short_name}]")
    print("=" * 70)

    if len(all_ticks_with_time) >= 2:
        print(f"  Spread asimetrisi = (ask_degisim - bid_degisim) / spread")
        print(f"  > 0: ask daha cok hareket etti -> alis baskisi")
        print(f"  < 0: bid daha cok hareket etti -> satis baskisi")
        print()
        print(f"  {'Saat':<20} {'Ort Asimetri':>12} {'Alis Baski':>10} {'Satis Baski':>12} {'Notr':>6}")
        print(f"  {'-'*60}")

        for label, sh, sm, eh, em in HOUR_SLOTS:
            slot_ticks = [t for t in all_ticks_with_time if tick_in_slot(t['tr_dt'], sh, sm, eh, em)]
            if len(slot_ticks) < 2:
                continue
            asymmetries = []
            alis_cnt = satis_cnt = notr_cnt = 0
            for i in range(1, len(slot_ticks)):
                bid_change = slot_ticks[i]['bid'] - slot_ticks[i-1]['bid']
                ask_change = slot_ticks[i]['ask'] - slot_ticks[i-1]['ask']
                spread = slot_ticks[i]['spread']
                if spread > 0 and (abs(bid_change) > 0.001 or abs(ask_change) > 0.001):
                    asym = (ask_change - bid_change) / spread
                    asymmetries.append(asym)
                    if asym > 0.1:
                        alis_cnt += 1
                    elif asym < -0.1:
                        satis_cnt += 1
                    else:
                        notr_cnt += 1
            if asymmetries:
                print(f"  {label:<20} {safe_mean(asymmetries):>+12.4f} {alis_cnt:>10d} {satis_cnt:>12d} {notr_cnt:>6d}")
    else:
        print("  Yeterli veri yok")

    # ==== ANALIZ 13: ISLEM ARASI BEKLEME SURESI DAGILIMI ====
    print()
    print("=" * 70)
    print(f"ANALIZ 13 -- ISLEM ARASI BEKLEME SURESI [{short_name}]")
    print("=" * 70)

    if len(real_trades) >= 2:
        wait_times = []
        for i in range(1, len(real_trades)):
            dt_sec = (real_trades[i]['time_msc'] - real_trades[i-1]['time_msc']) / 1000.0
            if dt_sec > 0:
                wait_times.append(dt_sec)

        # Dagilim
        cluster_fast = len([w for w in wait_times if w < 5])
        normal_1 = len([w for w in wait_times if 5 <= w < 30])
        normal_2 = len([w for w in wait_times if 30 <= w < 60])
        slow_1 = len([w for w in wait_times if 60 <= w < 180])
        slow_2 = len([w for w in wait_times if 180 <= w < 300])
        gap = len([w for w in wait_times if w >= 300])
        total_wt = len(wait_times)

        print(f"  < 5sn   (Cluster/Patlama):    {cluster_fast:>6d}  ({cluster_fast*100/max(total_wt,1):>5.1f}%)")
        print(f"  5-30sn  (Normal):             {normal_1:>6d}  ({normal_1*100/max(total_wt,1):>5.1f}%)")
        print(f"  30-60sn (Yavas):              {normal_2:>6d}  ({normal_2*100/max(total_wt,1):>5.1f}%)")
        print(f"  1-3dk   (Sessiz):             {slow_1:>6d}  ({slow_1*100/max(total_wt,1):>5.1f}%)")
        print(f"  3-5dk   (Cok Sessiz):         {slow_2:>6d}  ({slow_2*100/max(total_wt,1):>5.1f}%)")
        print(f"  > 5dk   (Bosluk):             {gap:>6d}  ({gap*100/max(total_wt,1):>5.1f}%)")
        print()
        print(f"  Min bekleme:     {min(wait_times):>8.1f} sn")
        print(f"  Medyan bekleme:  {safe_median(wait_times):>8.1f} sn")
        print(f"  Ortalama:        {safe_mean(wait_times):>8.1f} sn")
        print(f"  Max bekleme:     {max(wait_times):>8.1f} sn")

        # En uzun 5 bosluk
        print()
        print(f"  En uzun 5 bosluk:")
        sorted_waits = sorted(enumerate(wait_times), key=lambda x: x[1], reverse=True)[:5]
        for idx, wt in sorted_waits:
            if idx < len(real_trades) - 1:
                t1 = format_time_msc(real_trades[idx]['time_msc'])
                t2 = format_time_msc(real_trades[idx+1]['time_msc'])
                print(f"    {t1} -> {t2} : {wt:.0f} sn ({wt/60:.1f} dk)")
    else:
        print("  Yeterli veri yok")

    # ==== ANALIZ 14: 15DK WEIGHTED MOMENTUM HARITASI ====
    print()
    print("=" * 70)
    print(f"ANALIZ 14 -- 15DK WEIGHTED MOMENTUM [{short_name}]")
    print("=" * 70)
    print(f"  momentum = fiyat_degisim * abs(volume_delta)")
    print(f"  Pozitif: guclu yukselis  |  Negatif: guclu dusus  |  0: hareketsiz")
    print()
    print(f"  {'Dilim':<10} {'Fiyat Deg':>10} {'Vol Delta':>10} {'Momentum':>10} {'Yon'}")
    print(f"  {'-'*55}")

    momentums = []
    for label, sh, sm, eh, em in FIFTEEN_MIN_SLOTS:
        slot_trades = [t for t in real_trades if tick_in_slot(t['tr_dt'], sh, sm, eh, em)]
        if not slot_trades:
            continue
        price_chg = slot_trades[-1]['last'] - slot_trades[0]['last']
        bv = sum(t['volume'] for t in slot_trades if t['direction'] == 'BUY')
        sv = sum(t['volume'] for t in slot_trades if t['direction'] == 'SELL')
        delta = bv - sv
        momentum = price_chg * abs(delta)

        if momentum > 0:
            yon = "YUKARI"
        elif momentum < 0:
            yon = "ASAGI"
        else:
            yon = "YATAY"

        # Uyumsuzluk kontrolu
        if price_chg > 0 and delta < 0:
            yon += " [!UYUMSUZ]"
        elif price_chg < 0 and delta > 0:
            yon += " [!UYUMSUZ]"

        momentums.append({'label': label, 'price_chg': price_chg, 'delta': delta, 'momentum': momentum})
        print(f"  {label:<10} {price_chg:>+10.2f} {delta:>+10d} {momentum:>+10.1f} {yon}")

    # ==== ANALIZ 15: GUNLUK OZET ====
    print()
    print("=" * 70)
    print(f"ANALIZ 15 -- GUNLUK OZET [{short_name}]")
    print("=" * 70)

    if real_trades:
        acilis_fiyat = real_trades[0]['last']
        kapanis_fiyat = real_trades[-1]['last']
        en_yuksek = max(t['last'] for t in real_trades)
        en_dusuk = min(t['last'] for t in real_trades)
        gun_range = en_yuksek - en_dusuk

        print(f"  Tarih:                 {DATE_STR} ({WEEKDAY})")
        print(f"  Kontrat:               {symbol}")
        print(f"  Toplam tick:           {len(all_ticks_raw)}")
        print(f"  Gercek islem:          {len(real_trades)}")
        print(f"  Gercek islem orani:    {len(real_trades)*100/max(len(all_ticks_raw),1):.1f}%")
        print(f"  Acilis:                {acilis_fiyat:.2f}")
        print(f"  Kapanis:               {kapanis_fiyat:.2f}")
        print(f"  En Yuksek:             {en_yuksek:.2f}")
        print(f"  En Dusuk:              {en_dusuk:.2f}")
        print(f"  Gun Araligi:           {gun_range:.2f} TL")
        print(f"  Gun Degisim:           {kapanis_fiyat - acilis_fiyat:+.2f} TL ({(kapanis_fiyat - acilis_fiyat)*100/acilis_fiyat:+.2f}%)")
        print(f"  Toplam Hacim:          {gun_buy_vol + gun_sell_vol} lot")
        print(f"  BUY Hacim:             {gun_buy_vol} lot ({gun_buy_vol*100/max(gun_buy_vol+gun_sell_vol,1):.0f}%)")
        print(f"  SELL Hacim:            {gun_sell_vol} lot ({gun_sell_vol*100/max(gun_buy_vol+gun_sell_vol,1):.0f}%)")
        print(f"  Volume Delta:          {gun_delta:+d} lot")
        print(f"  Gun Yonu:              {yon}")
        print(f"  Ort Spread:            {safe_mean(gun_spreads):.2f} TL")
        print(f"  Ort Lot Buyuklugu:     {safe_mean([t['volume'] for t in real_trades]):.2f}")
        print(f"  Buyuk Islem (4+):      {total_bb + total_bs} adet (BUY:{total_bb} SELL:{total_bs})")
        bb_vol = sum(t['volume'] for t in real_trades if t['direction'] == 'BUY' and t['volume'] >= BIG_TRADE_THRESHOLD)
        bs_vol = sum(t['volume'] for t in real_trades if t['direction'] == 'SELL' and t['volume'] >= BIG_TRADE_THRESHOLD)
        if total_bb + total_bs > 0:
            big_buy_ratio = total_bb * 100 / (total_bb + total_bs)
            print(f"  Buyuk Islem BUY%:      {big_buy_ratio:.0f}%")
            print(f"  Buyuk Islem Asimetri:  {total_bb}:{total_bs} (BUY:SELL)")
        print(f"  Agresor Degisim:       {gecis_count} kez")
        if uyumlu + toplam_karsilastirma > 0:
            print(f"  Fiyat-Delta Uyum:      {uyumlu}/{toplam_karsilastirma} ({uyumlu*100//max(toplam_karsilastirma,1)}%)")

    return real_trades


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
        return

    print(f"  [OK] market_book_add({symbol}) basarili")
    time.sleep(1)

    book = mt5.market_book_get(symbol)
    if book is None or len(book) == 0:
        print(f"  [BOS] market_book_get bos dondu. Piyasa kapali olabilir.")
        mt5.market_book_release(symbol)
        return

    print(f"  Emir defteri derinligi: {len(book)} seviye")
    print()
    print(f"  {'Tip':<8} {'Fiyat':>10} {'Hacim':>8}")
    print(f"  {'-'*30}")

    buy_levels = [b for b in book if b.type == mt5.BOOK_TYPE_SELL]  # ask tarafinda satislar
    sell_levels = [b for b in book if b.type == mt5.BOOK_TYPE_BUY]  # bid tarafinda alislar

    for b in book:
        tip = "SELL" if b.type == mt5.BOOK_TYPE_SELL else "BUY"
        print(f"  {tip:<8} {b.price:>10.2f} {b.volume:>8.0f}")

    mt5.market_book_release(symbol)
    print(f"\n  [OK] market_book_release({symbol})")


# ============================================================================
# ANA PROGRAM
# ============================================================================

def main():
    run_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print("=" * 70)
    print(f"USTAT v5.0 — Gunluk Tick Veri Toplama ve Analiz")
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

    all_results = {}

    for symbol in SYMBOLS:
        ticks = mt5.copy_ticks_range(symbol, utc_start, utc_end, mt5.COPY_TICKS_ALL)
        if ticks is None or len(ticks) == 0:
            print(f"  [UYARI] {symbol}: Tick verisi alinamadi veya bos!")
            continue

        print(f"  [OK] {symbol}: {len(ticks)} tick cekildi")

        # numpy structured array'den dict listesine cevir
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

        real_trades = analyze_symbol(symbol, tick_list, tick_list)
        all_results[symbol] = real_trades

    # Market book testi (seans aciksa)
    print()
    print("=" * 70)
    print("MARKET BOOK TESTLERI")
    print("=" * 70)
    for symbol in SYMBOLS:
        test_market_book(symbol)

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
            short = sym.split("_")[1].replace("0426", "")
            print(f" {short:>12}", end="")
        print()
        print(f"  {'-'*25}", end="")
        for _ in all_results:
            print(f" {'-'*12}", end="")
        print()

        # Toplam islem
        print(f"  {'Toplam islem':<25}", end="")
        for sym, trades in all_results.items():
            print(f" {len(trades):>12d}", end="")
        print()

        # Gun delta
        print(f"  {'Volume Delta':<25}", end="")
        for sym, trades in all_results.items():
            bv = sum(t['volume'] for t in trades if t['direction'] == 'BUY')
            sv = sum(t['volume'] for t in trades if t['direction'] == 'SELL')
            print(f" {bv-sv:>+12d}", end="")
        print()

        # Buyuk islem
        print(f"  {'Buyuk islem (4+)':<25}", end="")
        for sym, trades in all_results.items():
            big = len([t for t in trades if t['volume'] >= BIG_TRADE_THRESHOLD])
            print(f" {big:>12d}", end="")
        print()

        # BUY%
        print(f"  {'BUY%':<25}", end="")
        for sym, trades in all_results.items():
            b = len([t for t in trades if t['direction'] == 'BUY'])
            tot = len(trades)
            pct = b * 100 / tot if tot > 0 else 0
            print(f" {pct:>11.1f}%", end="")
        print()

        # Ort spread
        print(f"  {'Ort Spread':<25}", end="")
        for sym, trades in all_results.items():
            spreads = [t['spread'] for t in trades if t['spread'] > 0]
            print(f" {safe_mean(spreads):>11.2f}", end="")
        print()

        # Ort lot
        print(f"  {'Ort Lot':<25}", end="")
        for sym, trades in all_results.items():
            print(f" {safe_mean([t['volume'] for t in trades]):>11.2f}", end="")
        print()

    print()
    print(f"[OK] Analiz tamamlandi: {DATE_STR}")
    print(f"[OK] MT5 baglanti kapatiliyor...")
    mt5.shutdown()
    print(f"[OK] Bitti.")


if __name__ == "__main__":
    main()
