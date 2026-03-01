# -*- coding: utf-8 -*-
"""
MT5 Tam Gun Tick Analizi -- Inferred BUY/SELL (bid/ask proximity)
27 Subat 2026 (Persembe) 09:45-17:30
F_THYAO0426, F_AKBNK0426, F_ASELS0426
Sadece OKUMA yapar, emir gondermez.
Cikti: Ekran + full_day_inferred_20260227.txt
"""

import sys
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime, timezone
from io import StringIO

MT5_PATH = r"C:\Program Files\GCM MT5 Terminal\terminal64.exe"
SYMBOLS = ["F_THYAO0426", "F_AKBNK0426", "F_ASELS0426"]
OUTPUT_FILE = r"C:\USTAT\tests\full_day_inferred_20260227.txt"

# 27 Subat 2026 VIOP seansi: 09:45-17:30 TR = 06:45-14:30 UTC
SESSION_START = datetime(2026, 2, 27, 6, 45, 0, tzinfo=timezone.utc)
SESSION_END = datetime(2026, 2, 27, 14, 30, 0, tzinfo=timezone.utc)

BIG_TRADE_LOT = 4

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

# Flag sabitleri
FLAG_BUY = 0x08
FLAG_SELL = 0x10


class Output:
    """Ekran + buffer."""
    def __init__(self):
        self._buf = StringIO()

    def pr(self, text=""):
        print(text)
        self._buf.write(text + "\n")

    def text(self):
        return self._buf.getvalue()


out = Output()


def connect():
    if not mt5.initialize(path=MT5_PATH):
        out.pr(f"[HATA] initialize: {mt5.last_error()}")
        return False
    info = mt5.account_info()
    if info is None:
        out.pr(f"[HATA] account_info: {mt5.last_error()}")
        mt5.shutdown()
        return False
    out.pr(f"[OK] MT5 -- Hesap: {info.login}, Bakiye: {info.balance}")
    return True


def fetch_ticks(symbol):
    mt5.symbol_select(symbol, True)
    ticks = mt5.copy_ticks_range(symbol, SESSION_START, SESSION_END, mt5.COPY_TICKS_ALL)
    if ticks is None or len(ticks) == 0:
        out.pr(f"  [UYARI] {symbol}: veri yok -- {mt5.last_error()}")
        return None
    out.pr(f"  [OK] {symbol}: {len(ticks)} tick")
    return ticks


def get_day_minutes(ticks):
    """UTC timestamp -> Turkiye gun-ici dakika."""
    t = ticks['time'].astype(np.int64) + 3 * 3600
    return (t % 86400) // 60  # saat*60 + dakika


def slot_mask(dm, sh, sm, eh, em):
    return (dm >= sh * 60 + sm) & (dm < eh * 60 + em)


def extract_trades(ticks):
    """
    Gercek islem tick'lerini ayikla ve bid/ask proximity ile yon belirle.
    Donus: dict with numpy arrays (indices, is_buy, is_sell, volume, day_minutes, last, bid, ask)
    """
    flags = ticks['flags'].astype(np.int64)
    bid = ticks['bid'].astype(np.float64)
    ask = ticks['ask'].astype(np.float64)
    last = ticks['last'].astype(np.float64)
    vol = ticks['volume'].astype(np.float64)

    # Gercek islem: MT5 flag BUY veya SELL set
    has_trade = ((flags & FLAG_BUY) != 0) | ((flags & FLAG_SELL) != 0)

    # Ayrica bid/ask/last gecerli olmali
    valid = has_trade & (bid > 0) & (ask > 0) & (last > 0)

    v_bid = bid[valid]
    v_ask = ask[valid]
    v_last = last[valid]
    v_vol = vol[valid]

    # Yon belirleme: bid/ask proximity
    mid = (v_bid + v_ask) / 2.0

    # last <= bid -> kesin SELL (satici agresor)
    # last >= ask -> kesin BUY (alici agresor)
    # arada -> mid-point: last >= mid -> BUY, else -> SELL
    at_bid = v_last <= v_bid
    at_ask = v_last >= v_ask
    between = ~at_bid & ~at_ask

    is_buy = at_ask | (between & (v_last >= mid))
    is_sell = at_bid | (between & (v_last < mid))

    dm = get_day_minutes(ticks)
    v_dm = dm[valid]

    return {
        "count": int(np.sum(valid)),
        "is_buy": is_buy,
        "is_sell": is_sell,
        "volume": v_vol,
        "day_minutes": v_dm,
        "last": v_last,
        "bid": v_bid,
        "ask": v_ask,
        "at_bid": at_bid,
        "at_ask": at_ask,
        "between": between,
    }


def analysis1_hourly_trades(trades, symbol_short):
    """Saat bazli gercek BUY/SELL dagilimi (inferred yon)."""
    out.pr(f"\n{'='*70}")
    out.pr(f"ANALIZ 1 -- SAAT BAZLI ISLEM DAGILIMI (inferred) [{symbol_short}]")
    out.pr(f"{'='*70}")

    dm = trades["day_minutes"]
    is_buy = trades["is_buy"]
    is_sell = trades["is_sell"]

    out.pr(f"{'Saat':<15} {'BUY':>8} {'SELL':>8} {'Toplam':>8} {'BUY%':>8}")
    out.pr(f"{'-'*49}")

    total_b = 0
    total_s = 0
    for sh, sm, eh, em, label in TIME_SLOTS:
        m = slot_mask(dm, sh, sm, eh, em)
        bc = int(np.sum(is_buy & m))
        sc = int(np.sum(is_sell & m))
        tt = bc + sc
        pct = bc * 100 / tt if tt > 0 else 0
        total_b += bc
        total_s += sc
        out.pr(f"{label:<15} {bc:>8} {sc:>8} {tt:>8} {pct:>7.1f}%")

    tt = total_b + total_s
    pct = total_b * 100 / tt if tt > 0 else 0
    out.pr(f"{'-'*49}")
    out.pr(f"{'TOPLAM':<15} {total_b:>8} {total_s:>8} {tt:>8} {pct:>7.1f}%")


def analysis2_volume_delta(trades, symbol_short):
    """Saat bazli volume delta (BUY vol - SELL vol)."""
    out.pr(f"\n{'='*70}")
    out.pr(f"ANALIZ 2 -- SAAT BAZLI VOLUME DELTA (inferred) [{symbol_short}]")
    out.pr(f"{'='*70}")

    dm = trades["day_minutes"]
    is_buy = trades["is_buy"]
    is_sell = trades["is_sell"]
    vol = trades["volume"]

    out.pr(f"{'Saat':<15} {'BUY Vol':>10} {'SELL Vol':>10} {'Delta':>10} {'Yon'}")
    out.pr(f"{'-'*60}")

    total_bv = 0.0
    total_sv = 0.0
    slot_deltas = []

    for sh, sm, eh, em, label in TIME_SLOTS:
        m = slot_mask(dm, sh, sm, eh, em)
        bv = float(np.sum(vol[is_buy & m]))
        sv = float(np.sum(vol[is_sell & m]))
        delta = bv - sv
        total_bv += bv
        total_sv += sv
        slot_deltas.append((label, delta))

        if delta > 0:
            yon = "ALIS BASKIN"
        elif delta < 0:
            yon = "SATIS BASKIN"
        else:
            yon = "NOTR"
        out.pr(f"{label:<15} {bv:>10.0f} {sv:>10.0f} {delta:>+10.0f} {yon}")

    total_delta = total_bv - total_sv
    gun_yon = "ALIS BASKIN" if total_delta > 0 else ("SATIS BASKIN" if total_delta < 0 else "NOTR")
    out.pr(f"{'-'*60}")
    out.pr(f"{'GUN TOPLAM':<15} {total_bv:>10.0f} {total_sv:>10.0f} "
           f"{total_delta:>+10.0f} {gun_yon}")

    return slot_deltas


def analysis3_big_trades(trades, symbol_short):
    """Saat bazli buyuk islem (4+ lot) yonu."""
    out.pr(f"\n{'='*70}")
    out.pr(f"ANALIZ 3 -- BUYUK ISLEMLER ({BIG_TRADE_LOT}+ lot) [{symbol_short}]")
    out.pr(f"{'='*70}")

    dm = trades["day_minutes"]
    is_buy = trades["is_buy"]
    is_sell = trades["is_sell"]
    vol = trades["volume"]
    is_big = vol >= BIG_TRADE_LOT

    out.pr(f"{'Saat':<15} {'BigBUY':>8} {'BigSELL':>8} {'Toplam':>8} "
           f"{'BuyVol':>8} {'SellVol':>8} {'MaxVol':>8}")
    out.pr(f"{'-'*67}")

    total_bb = 0
    total_bs = 0
    for sh, sm, eh, em, label in TIME_SLOTS:
        m = slot_mask(dm, sh, sm, eh, em)
        bb = int(np.sum(is_buy & is_big & m))
        bs = int(np.sum(is_sell & is_big & m))
        bv = float(np.sum(vol[is_buy & is_big & m]))
        sv = float(np.sum(vol[is_sell & is_big & m]))
        slot_vols = vol[(is_buy | is_sell) & is_big & m]
        mx = float(np.max(slot_vols)) if len(slot_vols) > 0 else 0
        total_bb += bb
        total_bs += bs
        out.pr(f"{label:<15} {bb:>8} {bs:>8} {bb+bs:>8} "
               f"{bv:>8.0f} {sv:>8.0f} {mx:>8.0f}")

    out.pr(f"{'-'*67}")
    out.pr(f"{'TOPLAM':<15} {total_bb:>8} {total_bs:>8} {total_bb+total_bs:>8}")


def analysis4_price_delta_alignment(ticks, trades, symbol_short):
    """Fiyat hareketi ile volume delta uyumu."""
    out.pr(f"\n{'='*70}")
    out.pr(f"ANALIZ 4 -- FIYAT-DELTA UYUMU [{symbol_short}]")
    out.pr(f"{'='*70}")
    out.pr("Fiyat yukselirken delta pozitif mi? (uyumlu = trend guvenilir)")

    dm_all = get_day_minutes(ticks)
    last_all = ticks['last'].astype(np.float64)
    dm_trades = trades["day_minutes"]
    is_buy = trades["is_buy"]
    is_sell = trades["is_sell"]
    vol = trades["volume"]

    out.pr(f"\n{'Saat':<15} {'Acilis':>10} {'Kapanis':>10} {'Degisim':>10} "
           f"{'VolDelta':>10} {'Uyum'}")
    out.pr(f"{'-'*67}")

    uyumlu = 0
    uyumsuz = 0
    toplam_slot = 0

    for sh, sm, eh, em, label in TIME_SLOTS:
        m_all = slot_mask(dm_all, sh, sm, eh, em)
        m_trade = slot_mask(dm_trades, sh, sm, eh, em)

        # Slot icindeki last fiyatlari (>0 olanlar)
        slot_last = last_all[m_all]
        slot_last_valid = slot_last[slot_last > 0]

        if len(slot_last_valid) < 2:
            out.pr(f"{label:<15} {'--':>10} {'--':>10} {'--':>10} {'--':>10} --")
            continue

        acilis = float(slot_last_valid[0])
        kapanis = float(slot_last_valid[-1])
        degisim = kapanis - acilis

        bv = float(np.sum(vol[is_buy & m_trade]))
        sv = float(np.sum(vol[is_sell & m_trade]))
        delta = bv - sv

        # Uyum: fiyat yukselir+delta pozitif VEYA fiyat duser+delta negatif
        if degisim != 0 and delta != 0:
            toplam_slot += 1
            if (degisim > 0 and delta > 0) or (degisim < 0 and delta < 0):
                uyum = "UYUMLU"
                uyumlu += 1
            else:
                uyum = "UYUMSUZ"
                uyumsuz += 1
        else:
            uyum = "NOTR"

        out.pr(f"{label:<15} {acilis:>10.2f} {kapanis:>10.2f} {degisim:>+10.2f} "
               f"{delta:>+10.0f} {uyum}")

    if toplam_slot > 0:
        uyum_pct = uyumlu * 100 / toplam_slot
        out.pr(f"\nUyum orani: {uyumlu}/{toplam_slot} = %{uyum_pct:.0f}")
        if uyum_pct >= 70:
            out.pr("[YORUM] Yuksek uyum: Volume delta fiyat yonunu destekliyor")
        elif uyum_pct >= 50:
            out.pr("[YORUM] Orta uyum: Karisik sinyaller")
        else:
            out.pr("[YORUM] Dusuk uyum: Volume delta fiyat yonuyle celisiyor")


def analysis5_aggressor_shifts(trades, symbol_short):
    """Agresor degisim anlari (BUY baskin -> SELL baskina gecis)."""
    out.pr(f"\n{'='*70}")
    out.pr(f"ANALIZ 5 -- AGRESOR DEGISIM ANLARI [{symbol_short}]")
    out.pr(f"{'='*70}")
    out.pr("Her 5 dakikalik pencerede BUY/SELL volume delta hesaplanir.")
    out.pr("Delta isaret degistirdiginde 'gecis' olarak isaretlenir.")

    dm = trades["day_minutes"]
    is_buy = trades["is_buy"]
    is_sell = trades["is_sell"]
    vol = trades["volume"]

    # 5 dakikalik pencereler: 09:45'ten 17:30'a
    start_min = 9 * 60 + 45   # 585
    end_min = 17 * 60 + 30     # 1050
    window = 5

    windows = []
    prev_sign = 0  # +1 = BUY baskin, -1 = SELL baskin
    shifts = []

    out.pr(f"\n{'Zaman':<12} {'BuyVol':>8} {'SellVol':>8} {'Delta':>8} "
           f"{'Baskin':<14} {'Gecis'}")
    out.pr(f"{'-'*62}")

    for wstart in range(start_min, end_min, window):
        wend = min(wstart + window, end_min)
        m = (dm >= wstart) & (dm < wend)
        bv = float(np.sum(vol[is_buy & m]))
        sv = float(np.sum(vol[is_sell & m]))
        delta = bv - sv

        if delta > 0:
            current_sign = 1
            baskin = "ALIS BASKIN"
        elif delta < 0:
            current_sign = -1
            baskin = "SATIS BASKIN"
        else:
            current_sign = 0
            baskin = "NOTR"

        # Gecis kontrolu
        gecis = ""
        if prev_sign != 0 and current_sign != 0 and prev_sign != current_sign:
            if current_sign == 1:
                gecis = "<<< SELL->BUY"
            else:
                gecis = "<<< BUY->SELL"
            shifts.append((wstart, gecis))

        if current_sign != 0:
            prev_sign = current_sign

        h = wstart // 60
        mi = wstart % 60
        time_label = f"{h:02d}:{mi:02d}"

        # Sadece aktif pencereleri yazdir (volume > 0)
        if bv > 0 or sv > 0:
            out.pr(f"{time_label:<12} {bv:>8.0f} {sv:>8.0f} {delta:>+8.0f} "
                   f"{baskin:<14} {gecis}")

    out.pr(f"\nToplam agresor degisimi: {len(shifts)}")
    if shifts:
        out.pr("Gecis zamanlari:")
        for wstart, gecis_type in shifts:
            h = wstart // 60
            mi = wstart % 60
            out.pr(f"  {h:02d}:{mi:02d} {gecis_type}")


def run_contract(symbol, all_ticks_store):
    """Tek kontrat icin tum analizleri calistir."""
    ticks = fetch_ticks(symbol)
    if ticks is None:
        return

    short = symbol.replace("F_", "").replace("0426", "")
    trades = extract_trades(ticks)

    if trades["count"] == 0:
        out.pr(f"  [UYARI] {symbol}: gecerli islem tick'i yok")
        return

    all_ticks_store[symbol] = ticks

    out.pr(f"\n\n{'#'*70}")
    out.pr(f"#  {symbol} ({short}) -- 2026-02-27 TAM GUN ANALIZI")
    out.pr(f"#  Toplam tick: {len(ticks)}, Gecerli islem: {trades['count']}")
    out.pr(f"#  Yon belirleme: bid/ask proximity (inferred)")

    # Konum dagilimi
    at_bid_c = int(np.sum(trades["at_bid"]))
    at_ask_c = int(np.sum(trades["at_ask"]))
    between_c = int(np.sum(trades["between"]))
    tc = trades["count"]
    out.pr(f"#  at_bid(SELL): {at_bid_c} ({at_bid_c*100/tc:.0f}%)  "
           f"at_ask(BUY): {at_ask_c} ({at_ask_c*100/tc:.0f}%)  "
           f"mid-point: {between_c} ({between_c*100/tc:.0f}%)")
    out.pr(f"{'#'*70}")

    analysis1_hourly_trades(trades, short)
    slot_deltas = analysis2_volume_delta(trades, short)
    analysis3_big_trades(trades, short)
    analysis4_price_delta_alignment(ticks, trades, short)
    analysis5_aggressor_shifts(trades, short)


def main():
    out.pr("MT5 Tam Gun Inferred BUY/SELL Analizi")
    out.pr("Tarih: 2026-02-27 (Persembe)")
    out.pr(f"Kontratlar: {', '.join(SYMBOLS)}")
    out.pr("Seans: 09:45-17:30 TR / 06:45-14:30 UTC")
    out.pr("Yon belirleme: last vs bid/ask proximity")
    out.pr(f"Calistirma: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    out.pr(f"{'='*70}")

    if not connect():
        sys.exit(1)

    try:
        out.pr("\nTick verisi cekiliyor...")
        all_ticks = {}

        for symbol in SYMBOLS:
            run_contract(symbol, all_ticks)

        # Dosyaya kaydet
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(out.text())
        out.pr(f"\n[OK] Sonuclar kaydedildi: {OUTPUT_FILE}")

    finally:
        mt5.shutdown()
        out.pr("[OK] MT5 baglanti kapatildi.")


if __name__ == "__main__":
    main()
