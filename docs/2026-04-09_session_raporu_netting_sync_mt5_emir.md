# Oturum Raporu — 2026-04-09 — Netting SYNC MT5 Emir Güncelleme

## Özet

`_sync_netting_volume` fonksiyonunda lot ekleme sonrası MT5 bekleyen emirlerin (trailing stop limit + hedef limit) güncellenmemesi sorunu tespit ve düzeltildi.

## Sorun

Kullanıcı hibrit pozisyona (F_ASELS SELL) 1 lot daha eklediğinde:
- `hp.current_sl` bellekte 378.25 → 379.70'e güncellendi (yeni entry'den PRİMNET hesabı)
- **AMA** MT5'teki `buy stop limit` emri hâlâ eski fiyatta (378.25) ve eski volume'da (1 lot) kaldı
- PRİMNET ekranı SL=379.70 gösterirken MT5 gerçek emir 378.25'te → desync

## Kök Neden

`_sync_netting_volume` fonksiyonu lot eklemede:
- ✅ `hp.entry_price`, `hp.current_sl`, `hp.current_tp` güncelliyordu
- ✅ DB güncelliyordu
- ❌ MT5'teki bekleyen emirleri güncellemiyordu

`modify_pending_order` sadece fiyat günceller — volume ve stoplimit (limit fiyat) parametrelerini değiştiremez. Bu yüzden iptal + yeni emir mekanizması gerekiyordu.

## Kanıt (Log)

```
11:47:03 | PRİMNET devir: F_ASELS SELL giriş_prim=1.40 stop_prim=2.90 SL=378.2500
  → MT5 buy stop limit 378.25 (1 lot) yerleştirildi

(Kullanıcı 1 lot daha ekledi → MT5 entry 372.75 → 374.175 ortalaması)

13:12:51 | PRİMNET [F_ASELS] giriş_prim=1.79 güncel_prim=2.07 stop_step=3.79 → SL=381.5500
  → hp.current_sl=379.70 (bellekte güncel) ama MT5 emri hâlâ 378.25 (1 lot)
```

## Düzeltme

**Dosya:** `engine/h_engine.py` (Sarı Bölge — C2)
**Fonksiyon:** `_sync_netting_volume` (Siyah Kapı DEĞİL)

Lot ekleme dalına (satır 949-1021 arası) eklenen mekanizma:

1. Eski trailing stop limit emri iptal (`cancel_pending_order`)
2. Yeni stop fiyatı + limit fiyatı + yeni volume ile `send_stop_limit` gönder
3. `hp.trailing_order_ticket` güncelle
4. Eski hedef limit emri iptal
5. Yeni volume ile `send_limit` gönder
6. `hp.target_order_ticket` güncelle
7. DB'ye yeni ticket'lar kaydet

Başarısızlık durumunda: eski davranış devam eder (software SL/TP backup), log uyarısı yazılır.

## Etki Analizi

| Alan | Etki |
|------|------|
| mt5_bridge.py | Mevcut fonksiyonlar kullanıldı — DEĞİŞİKLİK YOK |
| _trailing_via_stop_limit | Sonraki cycle'da yeni ticket'ı kullanır — OK |
| _cancel_stop_limit_orders | Pozisyon kapatılırken çalışır — OK |
| Kırmızı Bölge | DOKUNULMADI |
| Siyah Kapı | DOKUNULMADI |

## Değişen Dosyalar

| Dosya | Değişiklik |
|-------|-----------|
| `engine/h_engine.py` | +74 satır — `_sync_netting_volume` MT5 emir güncelleme |
| `docs/USTAT_GELISIM_TARIHCESI.md` | #141 eklendi |

## Commit

- Hash: `d031832`
- Mesaj: `fix: #141 — netting lot ekleme sonrası MT5 bekleyen emirleri güncelle`

## Versiyon

5.9.0 — değişiklik tek fonksiyon, versiyon arttırma eşiğine ulaşılmadı.
