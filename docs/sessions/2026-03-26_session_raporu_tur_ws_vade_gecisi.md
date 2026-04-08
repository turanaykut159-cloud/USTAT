# Oturum Raporu — 26 Mart 2026 (TÜR WS Fix + Vade Geçişi GCM Paraleli)

**Tarih:** 26 Mart 2026
**Versiyon:** v5.8.0 (değişmedi — diff oranı %3.3, eşik %10 altında)
**Oturum Konuları:** WebSocket TÜR tutarsızlığı, OĞUL NOTR araştırması, vade geçişi GCM paraleli

---

## 1. Yapılan İşler

### 1.1 WebSocket TÜR Sütunu Düzeltmesi (#74)

**Sorun:** Dashboard pozisyon tablosunda TÜR sütunu "Manuel" ve "MT5" arasında flipping yapıyordu. REST endpoint doğru, WS endpoint yanlış değer döndürüyordu.

**Kök Neden:** `api/routes/live.py` WS endpoint'i ManuelMotor'un in-memory `source` alanını okuyor, `positions.py` REST endpoint'i ise DB sorgusu kullanıyordu. ManuelMotor'un `restore_active_trades()` sırasındaki yanlış kayıt yüklemesi nedeniyle source bilgisi tutarsızdı.

**Çözüm:** WS endpoint'e `positions.py`'den `_source_for_position()` ve `_tur_for_position()` import edildi. Her iki endpoint artık aynı DB-tabanlı çözümleme kullanıyor. Debug loglama temizlendi.

**Commit:** `04f03ed`

### 1.2 Vade Geçişi GCM Paraleli (#75)

**Sorun:** OĞUL tüm gün NOTR kaldı, hiç otomatik işlem açmadı.

**Kök Neden:** `EXPIRY_NO_NEW_TRADE_DAYS = 3` parametresi 31 Mart vade sonuna 3 iş günü kala (26 Mart) tüm eski vade kontratlarını Top 5'ten dışlıyordu. 15 kontratın tamamı elendi → Top 5 boş → sinyal üretimi imkansız.

**GCM MT5 Modeli Araştırması:**
- GCM aynı anda 3 vade ayını aktif tutar
- Sadece son işlem gününde eski vadeden işlem açtırmaz
- Aynı gün yeni vade kontratını "visible" yapar → `_resolve_symbols()` otomatik geçer
- Gözlem süresi yoktur

**Çözüm:**
- `EXPIRY_NO_NEW_TRADE_DAYS: 3 → 1` (sadece son gün bloke)
- `EXPIRY_OBSERVATION_DAYS: 2 → 0` (gözlem bekleme yok)
- Filtre listesine `"close"` eklendi (son gün kontratlar Top 5'e girmesin)

**Doğrulama:** Değişiklik sonrası Top 5: F_TKFEN, F_HALKB, F_EKGYO, F_GUBRF, F_KONTR (5 kontrat seçildi).

**Commit:** `3af1583`

### 1.3 Gelişim Tarihçesi

Girişler #74 ve #75 eklendi.

**Commit:** `e98302f`

---

## 2. Değişiklik Listesi

| Dosya | Bölge | Değişiklik |
|-------|-------|-----------|
| `api/routes/live.py` | Yeşil | DB-tabanlı source import + WS döngü güncelleme |
| `api/routes/positions.py` | Yeşil | Debug loglama temizliği |
| `engine/top5_selection.py` | Yeşil | 3 sabit güncelleme + filtre listesi düzeltmesi |
| `docs/USTAT_v5_gelisim_tarihcesi.md` | C0 | #74 ve #75 girişleri |

---

## 3. Versiyon Durumu

- **Mevcut:** v5.8.0
- **Diff oranı:** %3.3 (2261 satır / 68533 toplam) → %10 eşiği altında → versiyon artırımı yok
- **Son 3 commit:** `04f03ed`, `3af1583`, `e98302f`

---

## 4. 31 Mart Vade Geçişi Beklenen Davranış

1. **26-30 Mart:** Normal işlem — Mart 2026 vadesi kontratları Top 5'te
2. **31 Mart (son işlem günü):** Mart 2026 kontratları `"close"` statüsünde → Top 5'ten dışlanır. GCM MT5 Nisan 2026 kontratlarını visible yapar → `_resolve_symbols()` otomatik Nisan vadelerine geçer → OĞUL Nisan vadelerinden işlem açar
3. **1 Nisan:** Gözlem süresi yok (`OBSERVATION_DAYS = 0`) → Nisan kontratları normal statüde → kesintisiz işlem

---

## 5. Build Durumu

Desktop build yapılmadı — bu oturumda UI değişikliği yok (sadece API ve engine değişiklikleri).
