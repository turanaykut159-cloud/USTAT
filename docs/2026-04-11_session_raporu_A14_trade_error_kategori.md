# Oturum Raporu — Widget Denetimi A14 (B17): TRADE_ERROR Kategori Eşlemesi

**Tarih:** 11 Nisan 2026 (Cumartesi — Barış Zamanı)
**Konu:** `TRADE_ERROR` ve `MANUAL_TRADE_ERROR` event tipleri Hata Takip panelinde doğru kategoriye (`emir`) eşlendi
**Değişiklik Sınıfı:** C1 (Yeşil Bölge — iki kategori dict'ine 2'şer anahtar eklendi)
**Versiyon:** v6.0.0 (değişmedi)
**Changelog:** #174
**Commit:** (commit sonrası eklenecek)

---

## 1. Kök Neden (Widget Denetimi Bulgu B17)

Audit `docs/2026-04-11_widget_denetimi.md` Bölüm 16.2 Bulgu B17:

> "Hata Takip (12): `TRADE_ERROR` anahtarı `EVENT_TYPE_CATEGORY` sözlüğünde yok → 'sistem' kategorisine düşüyor, canlı 9x miskategorize. Kritiklik: Yüksek."

Doğrulama:

1. `engine/ogul.py::_execute_signal` iki noktada `TRADE_ERROR` emit ediyor:
   - **Satır 1810** — `send_order()` `None` döndüğünde (emir gönderilemedi). `severity=ERROR`, `action=order_failed`.
   - **Satır 1886** — SL yerleştirme başarısız olup `close_position()` de başarısız olduğunda, yani korumasız pozisyon orphan'ı bırakıldığında. `severity=CRITICAL`, `action=unprotected_position_orphan`. Anayasa Kural #4 ("SL/TP Zorunluluk") ihlali durumunun raporlandığı yer.

2. `engine/manuel_motor.py::execute_manual_trade` bir noktada `MANUAL_TRADE_ERROR` emit ediyor:
   - **Satır 459** — MT5 brokerdan emir reddi veya bilinmeyen MT5 hatası geldiğinde. `severity=ERROR`, `action=manual_order_failed`.

3. Kategori sözlükleri durumu (düzeltme öncesi):
   - `engine/error_tracker.py::ERROR_CATEGORIES` — 24 anahtar vardı; `TRADE_ERROR` ve `MANUAL_TRADE_ERROR` **yoktu**. `ErrorGroup.__init__` satır 86'da `ERROR_CATEGORIES.get(error_type, "diğer")` çağrılıyor → bu tipler "diğer" kategorisine düşüyordu.
   - `api/routes/error_dashboard.py::EVENT_TYPE_CATEGORY` — 46 anahtar vardı (dosya başındaki yorum "error_tracker.py ile aynı" olmasına rağmen ikisi farklıydı); `TRADE_ERROR` ve `MANUAL_TRADE_ERROR` **yoktu**. `_categorize()` default'u "sistem" dönüyordu.

Kullanıcı etkisi: Hata Takip paneli sol menüsünden "emir" kategori filtresine bastığında gerçek trade başarısızlıkları görünmüyor, yerine "sistem" altında karışık duruyordu. Audit canlı ölçümde 9x miskategorize kayıt bulmuş.

## 2. Çözüm

Minimum invazif fix: her iki dict'e iki anahtar eklendi, mevcut anahtarlar dokunulmadı. Kapsamlı dict unification refactor'u bu commit dışında tutuldu (ileride ayrı bir audit maddesi olarak ele alınabilir — iki dict arasındaki tüm divergence temizlenmesi büyük bir iş).

### 2.1 `engine/error_tracker.py` (C1 — Yeşil Bölge)

`ERROR_CATEGORIES` dict'inin "emir" bloğuna ek:

```python
"SLTP_MODIFY_FAIL": "emir",
# Widget Denetimi A14 (B17) — TRADE_ERROR ve MANUAL_TRADE_ERROR
# ogul.py::_execute_signal (send_order fail, orphan) ve
# manuel_motor.py::execute_manual_trade (MT5 reject) bu tipleri emit ediyor.
# Önceden "diğer" kategorisine düşüyordu; "emir" doğru kategoridir.
"TRADE_ERROR": "emir",
"MANUAL_TRADE_ERROR": "emir",
```

Mevcut 24 anahtarın hiçbiri değiştirilmedi; sadece iki yeni giriş eklendi.

### 2.2 `api/routes/error_dashboard.py` (C1 — Yeşil Bölge)

`EVENT_TYPE_CATEGORY` dict'inin "emir" bloğuna aynı ekleme:

```python
"SLTP_MODIFY_FAIL": "emir",
# Widget Denetimi A14 (B17) — TRADE_ERROR ve MANUAL_TRADE_ERROR
# ogul.py ve manuel_motor.py bu tipleri emit ediyor (emir başarısızlığı +
# korumasız pozisyon orphan). Önceden EVENT_TYPE_CATEGORY'de anahtar yoktu
# ve _categorize default'u "sistem" döndürüyordu — Hata Takip panelinde
# canlı TRADE_ERROR kayıtları "sistem" altında birikiyordu. Doğru kategori "emir".
"TRADE_ERROR": "emir",
"MANUAL_TRADE_ERROR": "emir",
"TRADE": "emir",
"TRADE_OPEN": "emir",
"TRADE_CLOSE": "emir",
```

Mevcut 46 anahtarın hiçbiri değiştirilmedi; sadece iki yeni giriş eklendi. Yorum blokta kök neden belgelendi.

## 3. Statik Sözleşme Testi (Flow 4k)

`tests/critical_flows/test_static_contracts.py` içine `test_trade_error_category_mapping_consistent` eklendi. 4 aşamalı doğrulama:

1. **`ERROR_CATEGORIES` kontrolü** — `TRADE_ERROR` ve `MANUAL_TRADE_ERROR` anahtarları mevcut ve her ikisi `"emir"` kategorisine eşli.
2. **`EVENT_TYPE_CATEGORY` kontrolü** — aynı iki anahtar mevcut ve `"emir"` kategorisine eşli.
3. **Parite kontrolü** — iki sözlükte de aynı kategori. Gelecekte biri "emir" diğeri "sistem" yaparsa regression yakalanır.
4. **Emit noktası regression kontrolü** — `engine/ogul.py` dosyasında `event_type="TRADE_ERROR"` string'i hâlâ geçiyor, `engine/manuel_motor.py` dosyasında `event_type="MANUAL_TRADE_ERROR"` string'i hâlâ geçiyor. Biri bu emit noktalarını sessizce kaldırırsa audit bulgusunun artık geçerli olmadığı sinyali test üzerinden verilir (assert hata mesajında belirtiliyor).

## 4. Anayasa Etki Analizi

| Katman | Durum |
|--------|-------|
| Kırmızı Bölge | **Dokunulmadı.** (ogul.py, mt5_bridge.py, baba.py, config/default.json, vs.) |
| Sarı Bölge | **Dokunulmadı.** |
| Yeşil Bölge | `engine/error_tracker.py` (24→26 anahtar), `api/routes/error_dashboard.py` (46→48 anahtar), `tests/critical_flows/test_static_contracts.py` (+Flow 4k). |
| Siyah Kapı | **Dokunulmadı.** `_execute_signal` emit davranışı aynı, `check_risk_limits` dokunulmadı. |
| Değişmez Kurallar | Çağrı sırası, risk kapısı, kill-switch monotonluğu, SL/TP zorunluluğu, EOD kapanış, hard drawdown eşiği — hepsi değişmedi. |

Audit maddesi "A14: Hata Takip kategori fix" için önerilen ikinci aksiyon — "'sistem' kategorisindeki 9 TRADE_ERROR kaydını migration ile yeniden sınıflandır" — bu oturum kapsamı dışında tutuldu. Kategori map'i `_categorize()` ile query-time'da uygulandığı için yeni eklenen anahtarlar **geriye dönük olarak** eski kayıtları da etkiliyor: eski DB kayıtları olduğu gibi kalıyor, ama panel yeniden fetch'lediğinde `/errors/groups` endpoint'i artık "emir" kategori filtresinde gösteriyor. Migration gerekmiyor — map değişikliği zaten retroactive.

## 5. Doğrulama

### 5.1 Kritik Akış Testleri

```
python -m pytest tests/critical_flows -q --tb=short
```

Sonuç: **44 passed in 3.13s** (43 baseline + yeni Flow 4k). 3 syntax uyarısı `test_no_rogue_mt5_initialize_calls` içinde regex kaçış uyarısı — mevcut tech debt, bu commit ile ilgisiz.

### 5.2 Build

Frontend dokunulmadığı için `npm run build` atlandı. Python backend değişiklikleri uvicorn hot-reload veya engine yeniden başlatıldığında aktif olur.

### 5.3 Ham Veri İmpakt Analizi

Canlı DB'de mevcut olan `TRADE_ERROR` / `MANUAL_TRADE_ERROR` kayıtları, fix deploy edildiğinde otomatik olarak "emir" kategori filtresinde görünür hale gelecek. Çünkü:

1. `api/routes/error_dashboard.py::_categorize()` query-time'da çalışır.
2. `error_tracker.py::ErrorGroup.category` ise in-memory grubun oluşturulduğu anda belirlenir — yani runtime başladıktan sonra yeni gelen event'ler doğru kategoride açılır; mevcut grupların `.category` alanı fix öncesi `"diğer"` olarak kaydedildiği için engine yeniden başlatılana kadar eski in-memory gruplar "diğer" kalır. **Eylem:** bu kategori fix'i yayınlandığında engine bir sonraki restart'ta (geceki bakım veya savaş zamanı dışı manuel restart) in-memory gruplar yeniden DB'den inşa edildiğinde doğru kategoriye yerleşir.

Bu nüans audit maddesinin "migration" önerisine karşılık geliyor — ama gerçek bir DB migration değil, sadece **engine restart** yeterli.

## 6. Değişen Dosyalar

1. `engine/error_tracker.py`
2. `api/routes/error_dashboard.py`
3. `tests/critical_flows/test_static_contracts.py`
4. `docs/USTAT_GELISIM_TARIHCESI.md`
5. `docs/2026-04-11_session_raporu_A14_trade_error_kategori.md`

## 7. Versiyon Durumu

Toplam değişen kod satır sayısı ~15. v6.0.0 sabit kaldı. Changelog #174 girişi v6.0.0 "ÜSTAT Plus V6.0" bloğu Fixed başlığı altına #173 ve #172'den önce eklendi.

## 8. Sonraki Adım

Bu A14 kapandı. Kalan audit öncelikleri:

- **A5** — Version sabiti tekilleştirme (H1) — TopBar / Settings runtime fetch
- **A6** — Performance equity vs deposits (B14)
- **A8** — Hibrit MT5 SL/TP görünürlüğü (K10)
- **A10** — TopBar "Günlük K/Z (MT5)" etiketi (B16)
- **A15** — Error resolve message_prefix DB yazımı (B18) — A14'ün devamı niteliğinde
- **A18** — Pozisyon `/5` sayacı config'e bağla (H2)
- **A19** — KILL_HOLD_DURATION config'e taşı (H5)
- **B8** — Dashboard "Otomatik Pozisyon Özeti" total=45 vs winners+losers=31 tutarsızlığı
- **B11** — Monitor Flow Diagram MT5 panosu "BAĞLANTI YOK" hardcode
