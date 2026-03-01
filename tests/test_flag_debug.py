# -*- coding: utf-8 -*-
"""
BUY/SELL Flag Debug -- F_THYAO0426
27 Subat 2026 14:00-15:00 arasi gercek islem tick'leri.
Sadece OKUMA yapar, emir gondermez.
"""

import sys
import numpy as np
import MetaTrader5 as mt5
from datetime import datetime, timezone

MT5_PATH = r"C:\Program Files\GCM MT5 Terminal\terminal64.exe"
SYMBOL = "F_THYAO0426"

# 14:00-15:00 TR = 11:00-12:00 UTC
RANGE_START = datetime(2026, 2, 27, 11, 0, 0, tzinfo=timezone.utc)
RANGE_END = datetime(2026, 2, 27, 12, 0, 0, tzinfo=timezone.utc)

# MT5 tick flag sabitleri
FLAG_TICK_LAST = 0x01       # 1
FLAG_TICK_BID = 0x02        # 2
FLAG_TICK_ASK = 0x04        # 4
FLAG_TICK_BUY = 0x08        # 8
FLAG_TICK_SELL = 0x10       # 16
FLAG_TICK_VOLUME = 0x20     # 32


def main():
    if not mt5.initialize(path=MT5_PATH):
        print(f"[HATA] initialize basarisiz: {mt5.last_error()}")
        sys.exit(1)

    info = mt5.account_info()
    if info is None:
        print(f"[HATA] account_info None: {mt5.last_error()}")
        mt5.shutdown()
        sys.exit(1)

    print(f"[OK] MT5 baglanti -- Hesap: {info.login}")

    mt5.symbol_select(SYMBOL, True)
    ticks = mt5.copy_ticks_range(SYMBOL, RANGE_START, RANGE_END, mt5.COPY_TICKS_ALL)

    if ticks is None or len(ticks) == 0:
        print(f"[HATA] Tick verisi alinamadi: {mt5.last_error()}")
        mt5.shutdown()
        sys.exit(1)

    print(f"[OK] {SYMBOL} 14:00-15:00 TR arasi: {len(ticks)} tick cekildi")

    # Sutun bazli erisim
    flags_col = ticks['flags'].astype(np.int64)
    time_msc_col = ticks['time_msc'].astype(np.int64)
    bid_col = ticks['bid'].astype(np.float64)
    ask_col = ticks['ask'].astype(np.float64)
    last_col = ticks['last'].astype(np.float64)
    volume_col = ticks['volume'].astype(np.float64)

    # Gercek islem tick'leri: BUY veya SELL flag'li
    has_buy = (flags_col & FLAG_TICK_BUY) != 0
    has_sell = (flags_col & FLAG_TICK_SELL) != 0
    is_trade = has_buy | has_sell
    trade_indices = np.where(is_trade)[0]

    print(f"Gercek islem tick sayisi: {len(trade_indices)}")

    # ============================================================
    # 1. ILK 20 GERCEK ISLEM TICK'I DETAYLI LISTESI
    # ============================================================
    print(f"\n{'='*110}")
    print("1. ILK 20 GERCEK ISLEM TICK'I")
    print(f"{'='*110}")

    sample = trade_indices[:20]
    print(f"{'#':<4} {'time_msc':<18} {'bid':<10} {'ask':<10} {'last':<10} "
          f"{'vol':<6} {'flags':>6} {'flags_bin':<14} "
          f"{'&0x08':>6} {'&0x10':>6} {'&0x20':>6} {'Sonuc'}")
    print(f"{'-'*110}")

    for seq, idx in enumerate(sample):
        t_msc = int(time_msc_col[idx])
        bid = float(bid_col[idx])
        ask = float(ask_col[idx])
        last = float(last_col[idx])
        vol = float(volume_col[idx])
        flg = int(flags_col[idx])

        dt = datetime.fromtimestamp(t_msc / 1000, tz=timezone.utc)
        turkey_h = (dt.hour + 3) % 24
        time_str = f"{turkey_h:02d}:{dt.minute:02d}:{dt.second:02d}.{t_msc % 1000:03d}"

        flag_bin = format(flg, '012b')
        and_buy = flg & FLAG_TICK_BUY
        and_sell = flg & FLAG_TICK_SELL
        and_vol = flg & FLAG_TICK_VOLUME

        b = "BUY" if and_buy else ""
        s = "SELL" if and_sell else ""
        sonuc = "+".join(filter(None, [b, s]))

        print(f"{seq+1:<4} {time_str:<18} {bid:<10.2f} {ask:<10.2f} {last:<10.2f} "
              f"{vol:<6.0f} {flg:>6} {flag_bin:<14} "
              f"{and_buy:>6} {and_sell:>6} {and_vol:>6} {sonuc}")

    # ============================================================
    # 2. AYNI TICK'TE HEM BUY HEM SELL VAR MI?
    # ============================================================
    print(f"\n{'='*110}")
    print("2. BUY/SELL FLAG KESISIM ANALIZI")
    print(f"{'='*110}")

    both_count = int(np.sum(has_buy & has_sell))
    only_buy = int(np.sum(has_buy & ~has_sell))
    only_sell = int(np.sum(has_sell & ~has_buy))
    neither = int(np.sum(~has_buy & ~has_sell))
    total = len(ticks)
    trade_total = len(trade_indices)

    print(f"Toplam tick:                           {total}")
    print(f"Gercek islem (BUY|SELL):               {trade_total}")

    # ============================================================
    # 3. FLAG KOMBINASYON SAYILARI
    # ============================================================
    print(f"\n{'='*110}")
    print("3. FLAG KOMBINASYON SAYILARI")
    print(f"{'='*110}")
    print(f"Sadece BUY  (flag & 0x08, flag & 0x10 == 0):  {only_buy}")
    print(f"Sadece SELL (flag & 0x10, flag & 0x08 == 0):  {only_sell}")
    print(f"Hem BUY hem SELL (her iki flag birden):        {both_count}")
    print(f"Ne BUY ne SELL (fiyat guncelleme):             {neither}")

    if both_count > 0:
        pct = both_count * 100 / trade_total if trade_total > 0 else 0
        print(f"\n[BULGU] Gercek islem tick'lerinin %{pct:.1f}'inde "
              f"HEM BUY HEM SELL flag birlikte var!")

    # ============================================================
    # 4. LAST FIYATI ILE YON TAHMINI (bid/ask proximity)
    # ============================================================
    print(f"\n{'='*110}")
    print("4. LAST FIYATI ILE YON TAHMINI (bid/ask proximity)")
    print(f"{'='*110}")
    print("last <= bid  -> SATIS (seller aggressor, satici fiyati kabul etmis)")
    print("last >= ask  -> ALIS  (buyer aggressor, alici fiyati kabul etmis)")
    print("bid < last < ask -> BELIRSIZ (mid-point ile siniflandirilir)")

    # Trade tick'lerinin verileri
    t_bid = bid_col[is_trade]
    t_ask = ask_col[is_trade]
    t_last = last_col[is_trade]
    t_vol = volume_col[is_trade]
    t_time_msc = time_msc_col[is_trade]

    # Gecerli tick'ler (bid, ask, last hepsi > 0)
    valid = (t_bid > 0) & (t_ask > 0) & (t_last > 0)
    valid_count = int(np.sum(valid))

    if valid_count == 0:
        print("[UYARI] Gecerli bid/ask/last verisi yok")
    else:
        v_bid = t_bid[valid]
        v_ask = t_ask[valid]
        v_last = t_last[valid]
        v_vol = t_vol[valid]
        v_time_msc = t_time_msc[valid]

        # --- Yon belirleme ---
        # 1) last <= bid -> kesin SATIS
        # 2) last >= ask -> kesin ALIS
        # 3) bid < last < ask -> mid-point: last >= mid -> BUY, last < mid -> SELL
        mid = (v_bid + v_ask) / 2.0

        at_bid = v_last <= v_bid          # kesin SATIS
        at_ask = v_last >= v_ask          # kesin ALIS
        between = ~at_bid & ~at_ask       # arada kalanlar

        # Arada kalanlar icin mid-point kurali
        between_buy = between & (v_last >= mid)
        between_sell = between & (v_last < mid)

        # Nihai siniflandirma
        inferred_buy = at_ask | between_buy
        inferred_sell = at_bid | between_sell

        buy_count = int(np.sum(inferred_buy))
        sell_count = int(np.sum(inferred_sell))

        buy_vol = float(np.sum(v_vol[inferred_buy]))
        sell_vol = float(np.sum(v_vol[inferred_sell]))

        print(f"\nGecerli islem tick'i:     {valid_count}")
        print(f"\nFiyat konumu dagilimi:")
        print(f"  last <= bid (kesin SATIS):    {int(np.sum(at_bid)):>6}")
        print(f"  last >= ask (kesin ALIS):     {int(np.sum(at_ask)):>6}")
        print(f"  bid < last < ask (arada):     {int(np.sum(between)):>6}")
        print(f"    -> mid-point BUY:           {int(np.sum(between_buy)):>6}")
        print(f"    -> mid-point SELL:          {int(np.sum(between_sell)):>6}")

        print(f"\nNihai siniflandirma:")
        print(f"  Inferred BUY:           {buy_count:>6}  "
              f"({buy_count*100/valid_count:.1f}%)")
        print(f"  Inferred SELL:          {sell_count:>6}  "
              f"({sell_count*100/valid_count:.1f}%)")
        print(f"  BUY Volume:             {buy_vol:>6.0f} lot")
        print(f"  SELL Volume:            {sell_vol:>6.0f} lot")
        print(f"  Volume Delta:           {buy_vol - sell_vol:>+6.0f} lot")

        if buy_vol > sell_vol:
            print(f"\n[SONUC] 14:00-15:00 arasi ALIS BASKIN "
                  f"(delta: +{buy_vol - sell_vol:.0f} lot)")
        elif sell_vol > buy_vol:
            print(f"\n[SONUC] 14:00-15:00 arasi SATIS BASKIN "
                  f"(delta: {buy_vol - sell_vol:.0f} lot)")
        else:
            print(f"\n[SONUC] 14:00-15:00 arasi NOTR (delta: 0)")

        # Ilk 20 tick ornegi: inferred yon ile
        print(f"\nIlk 20 islem -- inferred yon:")
        print(f"{'#':<4} {'Zaman':<16} {'Bid':<10} {'Ask':<10} {'Last':<10} "
              f"{'Mid':<10} {'Vol':<6} {'Konum':<12} {'Yon'}")
        print(f"{'-'*88}")

        sample_count = min(20, valid_count)
        for seq in range(sample_count):
            b = float(v_bid[seq])
            a = float(v_ask[seq])
            l = float(v_last[seq])
            m = float(mid[seq])
            v = float(v_vol[seq])
            tmsc = int(v_time_msc[seq])

            dt = datetime.fromtimestamp(tmsc / 1000, tz=timezone.utc)
            turkey_h = (dt.hour + 3) % 24
            ts = f"{turkey_h:02d}:{dt.minute:02d}:{dt.second:02d}.{tmsc%1000:03d}"

            if l <= b:
                konum = "at_bid"
                direction = "SELL"
            elif l >= a:
                konum = "at_ask"
                direction = "BUY"
            elif l >= m:
                konum = "above_mid"
                direction = "BUY"
            else:
                konum = "below_mid"
                direction = "SELL"

            print(f"{seq+1:<4} {ts:<16} {b:<10.2f} {a:<10.2f} {l:<10.2f} "
                  f"{m:<10.2f} {v:<6.0f} {konum:<12} {direction}")

    # ============================================================
    # EK: TUM BENZERSIZ FLAG DEGERLERI
    # ============================================================
    print(f"\n{'='*110}")
    print("EK: TUM BENZERSIZ FLAG DEGERLERI")
    print(f"{'='*110}")
    unique_flags, counts = np.unique(flags_col, return_counts=True)
    sorted_idx = np.argsort(-counts)

    print(f"{'Flag(dec)':<10} {'Flag(hex)':<10} {'Binary':<16} {'Sayi':>8} "
          f"{'BUY':>5} {'SELL':>5} {'LAST':>5} {'BID':>5} {'ASK':>5} {'VOL':>5}")
    print(f"{'-'*80}")
    for idx in sorted_idx:
        fv = int(unique_flags[idx])
        fc = int(counts[idx])
        fb = format(fv, '012b')
        print(f"{fv:<10} {hex(fv):<10} {fb:<16} {fc:>8} "
              f"{'X' if fv & 0x08 else '-':>5} "
              f"{'X' if fv & 0x10 else '-':>5} "
              f"{'X' if fv & 0x01 else '-':>5} "
              f"{'X' if fv & 0x02 else '-':>5} "
              f"{'X' if fv & 0x04 else '-':>5} "
              f"{'X' if fv & 0x20 else '-':>5}")

    mt5.shutdown()
    print(f"\n[OK] MT5 baglanti kapatildi.")


if __name__ == "__main__":
    main()
