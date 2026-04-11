# Oturum Raporu — Widget Denetimi B11: Monitor MT5 Panosu Dinamikleştirme

**Tarih:** 11 Nisan 2026 (Cumartesi — Barış Zamanı)
**Konu:** Monitor Flow Diagram ÜSTAT ModBox `MT5` detail satırı `mt5Connected` state'ine bağlandı
**Değişiklik Sınıfı:** C1 (Yeşil Bölge — tek dosya, tek satır içerik değişikliği + yorum)
**Versiyon:** v6.0.0 (değişmedi)
**Changelog:** #175
**Commit:** (commit sonrası eklenecek)

---

## 1. Kök Neden (Widget Denetimi Bulgu B11)

Audit `docs/2026-04-11_widget_denetimi.md` Bölüm 16.2 Bulgu B11:

> "Monitor · Flow Diagram MT5 panosu (11.4): Her durumda 'MT5 BAĞLANTI YOK' yazıyor (mt5Connected state var ama detail'da kullanılmıyor) — MT5 aslında bağlı. Kritiklik: Yüksek."

Kod tabanı doğrulama:

1. `desktop/src/components/Monitor.jsx` **satır 265**: `const mt5Connected = status?.mt5_connected ?? false;` — state zaten hesaplanıyor.

2. **Satır 503–504** (Bölüm [B] Gateway paneli sub metni): `mt5Connected` doğru şekilde kullanılıyor:
   ```jsx
   sub={mt5Connected ? 'GCM · bağlı' : 'bağlantı yok'}
   color={mt5Connected ? '#7c4dff' : '#e74c3c'}
   ```

3. **Satır 540** (aynı panelin detail satırı): Yine dinamik:
   ```jsx
   ['BAĞLANTI', mt5Connected ? '✓ CANLI' : '✗ KOPUK', mt5Connected ? '#2ecc71' : '#e74c3c'],
   ```

4. **Satır 766** (Bölüm [C] Flow Diagram ÜSTAT geniş ModBox detail satırı) — sorunun olduğu yer:
   ```jsx
   ['MT5', 'BAĞLANTI YOK', '#556680'],
   ```
   Bu satır sabit string + gri renk. MT5 bağlı olsa bile burada "BAĞLANTI YOK" görünüyordu. Kullanıcı Monitor ekranına baktığında GATEWAY paneli "✓ CANLI" ama Flow Diagram "BAĞLANTI YOK" diyor — tutarsız ve yanıltıcı.

Kullanıcı etkisi: Monitor ekranı yazılım durumunu canlı izlemek için açılan ana ekran. Bu panel her zaman "BAĞLANTI YOK" dediği için kullanıcı sistemin çalışıp çalışmadığına dair güvenini yitiriyor, panik alarmı veriyor veya tam tersi gerçek bir kopuk durumu fark etmiyor çünkü "her zaman öyle yazıyor" alışkanlığı oluşuyor.

## 2. Çözüm

Aynı dosyada [B] Gateway paneli için zaten geçerli olan dinamik pattern [C] Flow Diagram ÜSTAT ModBox'ına uygulandı. Tek satır değişikliği, 3 satır yorum dokümantasyonu.

### 2.1 `desktop/src/components/Monitor.jsx` (C1 — Yeşil Bölge)

**Öncesi** (satır 766):
```jsx
details={[
  ['SON ÇALIŞMA', layers?.ustat?.last_run_time ? fmtTime(layers.ustat.last_run_time) : '—'],
  ['DB BOYUT', `${sysInfo?.db_file_size_mb ?? 0} MB`],
  ['MT5', 'BAĞLANTI YOK', '#556680'],
  ['HATA', `${errorCounts.ustat} bugün`, errorCounts.ustat > 0 ? '#f39c12' : undefined],
]}
```

**Sonrası:**
```jsx
details={[
  ['SON ÇALIŞMA', layers?.ustat?.last_run_time ? fmtTime(layers.ustat.last_run_time) : '—'],
  ['DB BOYUT', `${sysInfo?.db_file_size_mb ?? 0} MB`],
  // Widget Denetimi B11 fix — gerçek mt5Connected state'ine bağlandı
  // (önce 'BAĞLANTI YOK' hardcode'du; mt5Connected hesaplanıyor ama
  // burada kullanılmıyordu, bu yüzden MT5 bağlıyken bile "YOK" görünüyordu).
  ['MT5', mt5Connected ? '✓ BAĞLI' : '✗ KOPUK', mt5Connected ? '#2ecc71' : '#e74c3c'],
  ['HATA', `${errorCounts.ustat} bugün`, errorCounts.ustat > 0 ? '#f39c12' : undefined],
]}
```

Değişiklik kapsamı:
- Etiket: `MT5` (aynı)
- Değer: `'BAĞLANTI YOK'` (sabit) → `mt5Connected ? '✓ BAĞLI' : '✗ KOPUK'` (dinamik)
- Renk: `'#556680'` (nötr gri, sabit) → `mt5Connected ? '#2ecc71' : '#e74c3c'` (yeşil / kırmızı, dinamik)

Pattern [B] panelinde zaten kanıtlanmış — aynısı kullanıldı. Yeni state introduce edilmedi, yeni prop eklenmedi.

## 3. Statik Sözleşme Testi (Flow 4l)

`tests/critical_flows/test_static_contracts.py` içine `test_monitor_mt5_panel_uses_dynamic_state` eklendi. 3 aşamalı doğrulama:

1. **State kontrolü** — `const mt5Connected` string'i Monitor.jsx'te hâlâ mevcut. Birisi bu state'i kaldırmaya kalkarsa test düşer.
2. **Hardcode regression kontrolü** — `['MT5', 'BAĞLANTI YOK'` string'i dosyada YOK. B11 fix geri alınırsa veya yeni bir yerde aynı hardcode eklenirse test düşer.
3. **Dinamik pattern kontrolü** — `['MT5', mt5Connected` string'i dosyada mevcut. Doğru pattern'in varlığını kanıtlar.

Bu üç assertion birlikte regression koruması sağlıyor: fix geri alınamaz, hardcode yeniden eklenemez, state silinemez.

## 4. Anayasa Etki Analizi

| Katman | Durum |
|--------|-------|
| Kırmızı Bölge | **Dokunulmadı.** Backend, config, engine, API — hiçbiri değişmedi. |
| Sarı Bölge | **Dokunulmadı.** |
| Yeşil Bölge | `desktop/src/components/Monitor.jsx` (tek satır içerik değişikliği + 3 satır yorum), `tests/critical_flows/test_static_contracts.py` (+Flow 4l). |
| Siyah Kapı | **Dokunulmadı.** |
| Değişmez Kurallar | Çağrı sırası, risk kapısı, kill-switch monotonluğu, SL/TP zorunluluğu, EOD kapanış, hard drawdown eşiği — hepsi değişmedi. MT5 heartbeat mekanizması dokunulmadı. |

Kapsam son derece dar: tek JSX satırının içeriği hardcoded string'den state-bağlı ternary'e çevrildi. Render edildiği şekil ve konum aynı, sadece içeriği canlı veriye bağlandı.

## 5. Doğrulama

### 5.1 Kritik Akış Testleri

```
python -m pytest tests/critical_flows -q --tb=short
```

Sonuç: **45 passed in 3.15s** (44 baseline + yeni Flow 4l). Mevcut 3 syntax uyarısı `test_no_rogue_mt5_initialize_calls` içinde regex kaçış sorunu — bu commit ile ilgisiz, backlog.

### 5.2 Windows Production Build

```
python .agent/claude_bridge.py build
```

Sonuç:
- 728 modül dönüştürüldü
- 2.70 saniye
- 0 hata
- `index.js` 886.40 kB (gzip: 253.79 kB)
- `index.css` 90.52 kB (gzip: 15.07 kB)

### 5.3 Canlı Doğrulama Yöntemi

Uygulama yeniden başlatıldığında ve MT5 bağlı durumdayken Monitor ekranı açılırsa:
- [B] Gateway paneli: "GCM · bağlı" + yeşil "✓ CANLI" (önceden doğruydu, dokunulmadı)
- [C] Flow Diagram ÜSTAT paneli: "MT5: ✓ BAĞLI" yeşil (önceden "MT5: BAĞLANTI YOK" gri — **düzeltildi**)

MT5 gerçekten koptuğunda:
- [B] Gateway paneli: "bağlantı yok" + kırmızı "✗ KOPUK"
- [C] Flow Diagram ÜSTAT paneli: "MT5: ✗ KOPUK" kırmızı

Renk ve metin iki panel arasında artık senkron. Kullanıcı çelişkili bilgi görmüyor.

## 6. Değişen Dosyalar

1. `desktop/src/components/Monitor.jsx`
2. `tests/critical_flows/test_static_contracts.py`
3. `docs/USTAT_GELISIM_TARIHCESI.md`
4. `docs/2026-04-11_session_raporu_B11_monitor_mt5_panosu.md`

## 7. Versiyon Durumu

Değişen satır sayısı ~10 (kod + yorum). v6.0.0 sabit kaldı. Changelog #175 girişi v6.0.0 "ÜSTAT Plus V6.0" bloğu Fixed başlığı altına #174, #173, #172'den önce eklendi.

## 8. Sonraki Adım

Bu B11 kapandı. Kalan audit öncelikleri:

- **A5** — Version sabiti tekilleştirme (H1) — TopBar / Settings runtime fetch, daha geniş kapsamlı
- **A6** — Performance equity vs deposits (B14) — deposit/withdrawal tracking gerekir, orta karmaşıklık
- **A8** — Hibrit MT5 SL/TP görünürlüğü (K10) — Dashboard tablosu için
- **A10** — TopBar "Günlük K/Z (MT5)" etiketi (B16) — basit label fix
- **A15** — Error resolve message_prefix (B18) — A14'ün devamı, DB schema kontrolü
- **A18** — Pozisyon `/5` sayacı config'e bağla (H2) — basit config bind
- **A19** — KILL_HOLD_DURATION config'e taşı (H5) — basit sabit taşıma
- **B8** — Dashboard "Otomatik Pozisyon Özeti" 45 vs 31 tutarsızlığı
