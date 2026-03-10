# Session Raporu — 2026-03-10 (Manuel Force-Close Fix + Aktif Pozisyon Kartlari)

## Yapilan Is

### Bug Fix: Manuel Islem Force-Close (Birincil Sorun)
- **Semptom:** Manuel Islem Paneli'nden acilan pozisyonlar (F_AKBNK, F_HALKB) ~1300ms icinde otomatik kapaniyordu. Panel hala "acik" gosteriyordu (hayalet pozisyon).
- **Kok Neden:** `mt5_bridge.py:send_order()` SL/TP eklemeyi `TRADE_ACTION_SLTP` ile deniyor. GCM VIOP desteklemiyor (retcode=10035). 3 basarisiz denemeden sonra pozisyonu force-close ediyor.
- **Cozum:** `manuel_motor.py:open_manual_trade()` artik `sl=0, tp=0` gonderiyor. ManuelMotor tasariminda SL/TP yonetimi yok — degerler sadece bellekte risk gostergesi olarak tutuluyor.

### Bug Fix: BABA Fake Sinyal (Ikincil)
- `baba.py:analyze_fake_signals()` tum MT5 pozisyonlarini tariyordu, manuel/otomatik ayrimi yoktu.
- Manuel pozisyon ticket'lari artik `manual_tickets` set'i ile fake analizden muaf.

### Bug Fix: SENT State Race Condition (Ikincil)
- SENT state'teki trade MT5'te yoksa `sync_positions()` `continue` ile atliyordu → hayalet pozisyon.
- `SENT_EXPIRE_SEC = 30.0` timeout eklendi, asildigi zaman `external_close` olarak isleniyor.

### Feature: Aktif Manuel Pozisyonlar Karti
- ManualTrade.jsx'a HybridTrade panelindeki aktif pozisyon tablosuyla ayni stilde kart eklendi.
- Tablo: Sembol, Yon, Lot, Giris Fiy., Anlik Fiy., K/Z, Sure, Islem (Kapat butonu).
- 10s auto-refresh, TOPLAM footer.

### Feature: Aktif Otomatik Pozisyonlar Karti
- AutoTrading.jsx'a full-width aktif pozisyon tablosu eklendi.
- Tablo: Sembol, Yon, Strateji, Lot, Giris Fiy., Anlik Fiy., SL, TP, K/Z, Oy, Sure.
- Sag kolondaki ozet kart korundu.

### Versiyon Yukseltme: v5.3 → v5.4
- Kumulatif degisiklik orani: %10.47 (4887 satir / 46669 toplam)
- 40 dosyada versiyon referanslari guncellendi (fonksiyonel sabitler + UI + JSDoc + metadata)

## Degisiklik Ozeti

| Dosya | Degisiklik |
|-------|-----------|
| engine/manuel_motor.py | sl=0,tp=0 + force_closed kontrolu + SENT timeout |
| engine/baba.py | manual_tickets muafiyeti |
| engine/main.py | baba.manuel_motor cross-ref |
| desktop/src/components/ManualTrade.jsx | Aktif pozisyon karti |
| desktop/src/components/AutoTrading.jsx | Aktif pozisyon tablosu |
| 40 dosya | v5.3 → v5.4 versiyon guncellemesi |

## Teknik Detaylar
- **Etkilenen motorlar:** ManuelMotor, BABA
- **Etkilenen UI:** ManualTrade, AutoTrading, Settings, TopBar, LockScreen
- **GCM VIOP SLTP kisiti:** TRADE_ACTION_SLTP retcode=10035 (desteklenmiyor). Bu bilinen bir kisit (#1 gelisim tarihcesi).

## Versiyon Durumu
- **Onceki:** v5.3
- **Sonraki:** v5.4
- **Oran:** %10.47

## Commit
- `8cd3c04` — fix: Manuel Islem force-close bugu + aktif pozisyon kartlari
- `cc9b7b3` — feat: versiyon yukseltme v5.3 → v5.4

## Build Sonucu
- `npm run build` → 0 hata, 717 modul, 2.31s
- Chunk uyarisi (764kB > 500kB) — bilinen durum, code-split onerisi
