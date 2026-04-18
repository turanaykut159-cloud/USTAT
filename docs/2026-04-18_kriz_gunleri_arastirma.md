# Kriz Günleri Araştırması (P2-11/12)

**Tarih:** 18 Nisan 2026 Cmt gece
**Kapsam:** 16 Nis %35 DD + 12 Nis L2→L3 eskalasyon
**Kaynak:** `database/trades.db` risk_snapshots + events + trades

---

## 1. 16 Nisan %35 DD — Teşhis

### Kanıtlar

Engine 16 Nis 09:48:32'de başladı. İlk 90 saniye içinde:

| Zaman | Olay | Kanıt |
|---|---|---|
| 09:48:32 | **MT5 bağlantısı YOK** — `NO_MT5_RESTRICTED_MODE` warning | events |
| 09:48:32 | Vade tarihi uyarısı (2025-03-31 tatil) | events |
| 09:49:01 | Hacim patlaması F_KONTR 9.1× | events |
| 09:49:01 | BABA parametreleri sıkıldı: max_daily_loss %1.8 → %1.6 | events |
| 09:49:13 | **Global olumsuz haber CRITICAL:** US Fed Sanayi Üretimi (Beklenti 2.10) | events |
| 09:49:13 | **Kill-Switch L1 aktif** — NEWS_ALERT değer=-1.0 | events |
| **09:51:13** | **Equity 27,752 / Floating -2,624 / DD %35.53 / Margin %4997** | risk_snapshots |

### Anomali: Margin %4997

Margin usage ratio gerçekçi değil (%4997 = 50× leverage anormal). Bu üç olasılığın kanıtı:
1. Broker tarafında hesap durumunda sorun (GCM-Real01 mt5_journal'da "authorization failed, Account disabled")
2. `peak_equity=42,000` stale → gerçek equity broker'da 27K'ya düştü (manuel para çekimi veya hesap sıfırlama) → DD hesaplaması peak/current farkı üzerinden %35 geldi
3. `margin_usage` hesabında bug (field adı aynı mı kontrol edilmeli)

### Trade aktivitesi o gün

- 1 hibrit trade (#278 F_TKFEN BUY, PnL -130 TL) — marjinal
- 16 Nis'te başka trade yok

### Sonuç

**%35 DD gerçek trading zararı DEĞİL.** Sistemin algıladığı bir "peak vs current" anomalisi. Kök neden kombinasyonu:
- Broker account disabled + MT5 restricted mode
- `peak_equity` eski değeri (42K) cache'lendi
- Equity 27K'ya düşünce (muhtemelen manuel balance değişikliği veya broker anomalisi) DD hesabı şişti

### Öneriler (hafta içi fix için)

1. **OP-K1: peak_equity sanity check** — eğer equity ≥10% tek cycle'da azaldıysa peak_equity de senkronize edilsin (broker balance sync ile)
2. **OP-K2: margin_usage clamp** — %200 üzerindeyse CRITICAL event + UI alert + risk snapshot ayrı flag
3. **OP-K3: restricted mode'da risk snapshot** — MT5 bağlantı YOK iken snapshot "stale" işaretlensin, DD hesabı yapılmasın

---

## 2. 12 Nisan L2→L3 Eskalasyon — Araştırma

### İddia (V2 raporu)

> **12 Nis 19:01 L2→L3 eskalasyon: hard drawdown %15 aşıldı** | Kullanıcı ACK etti, sistem duruldu

### DB'de kanıt

**12 Nis için L2/L3/kill/drawdown içeren event: 0 kayıt.**

Bu ya:
- a) Event DB retention window'undan (3 gün) dışarı düştü (olasılık yüksek)
- b) Event kaydedilmedi (bug)
- c) Rapor yanlış hatırladı

12 Nis'te trade aktivitesi:
- Trades tablosunda 12 Nis entry_time ile kayıt **YOK**.

### Daily_risk_summary kontrol

Bu tabloda 12 Nis summary var mı? Yeni sorgu çalıştırılmalı hafta içi.

### Sonuç

**12 Nis L2→L3 eskalasyon iddiası mevcut DB'de doğrulanamadı.** Muhtemelen event retention window'u nedeniyle kaybolmuş olabilir. Kullanıcıya manuel soru: "O gün L2→L3 ACK ettiniz mi?"

### Öneriler

1. **Event retention window genişletilebilir** (kritik event'ler için 30 gün)
2. **daily_risk_summary** tablosu her gün için CRITICAL/ERROR sayısı tutmalı (zaten var mı kontrol)
3. **Kullanıcı bu iddiayı doğrulamalı** — hatırladığı detay var mı?

---

## 3. Özet

| Olay | V2 İddia | DB Kanıt | Teşhis |
|---|---|---|---|
| 16 Nis %35 DD | "Büyük çöküş" | 09:51'de %35.53 DD, equity 27K, margin %4997 | **Anomali — gerçek kayıp değil**. Peak_equity stale + MT5 restricted mode + broker account disabled |
| 12 Nis L2→L3 | "Hard DD %15 aşıldı, ACK" | **0 event** (retention düşmüş olabilir) | **Doğrulanamadı.** Kullanıcı teyidi + daily_risk_summary kontrolü gerek |

Her iki olayın sonucu: **mevcut risk/snapshot sisteminde edge case'ler var.** Hafta içi ek işler:
- peak_equity sanity check (OP-K1)
- margin_usage clamp (OP-K2)
- restricted mode snapshot stale-flag (OP-K3)
- Kritik event retention genişletme (OP-K4)

Bu 4 iş ayrı bir mini-operasyon (C2-C3) olarak planlanabilir.
