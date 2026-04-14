# Test Arıza Analizi — 15 Başarısız Testin Kök Neden İncelemesi

**Tarih:** 11 Nisan 2026
**Kapsam:** `tests/test_ogul_200.py` (4 FAIL) + `tests/test_hybrid_100.py` (11 FAIL)
**Kaynak:** Kod ve git log doğrulaması (varsayım yok)

---

## Özet

| | |
|---|---|
| **Toplam başarısız test** | 15 |
| **Kod kaynaklı bug** | **0** |
| **Test debt (güncellenmemiş test)** | **15** |
| **Üretime etki** | **Yok** |

Tüm başarısızlıklar, kodun bilinçli değişikliklerine test paketinin ayak uyduramamasından kaynaklanıyor. Üretim kodu doğru, çekirdek koruma katmanları sağlam (critical_flows 34/34, stress_10000 10003/10003 PASS).

---

## Grup A — H-Engine Testleri (11 başarısız)

### A1: PRİMNET hesap sapmaları (7 test)

**Etkilenen testler:**
- `TestPrimCalc::test_015_prim_to_price`
- `TestFaz1::test_029_faz1_boundary`
- `TestFaz1::test_030_faz1_to_faz2_transition`
- `TestFaz2::test_033_buy_faz2_tighter`
- `TestFaz2::test_037_faz2_locked_profit`
- `TestFaz2::test_038_faz2_near_target`
- `TestFaz2::test_042_faz2_big_jump`

**Kök neden — KANITLANDI:**

Git commit **`9020e43`** (31 Mart 2026, Turan Aykut):

> "fix: PRİMNET sabit 1.5 prim trailing — Faz 1/Faz 2 ayrımı kaldırıldı
> Eski: Faz1=1.5, Faz2=1.0 trailing (kâr>=2.0'da geçiş), Faz1'de kilitli kâr yok.
> Yeni: HER ZAMAN 1.5 prim sabit trailing, stop > giriş olduğunda kilitli kâr otomatik.
> - config: faz1_stop_prim/faz2_activation/faz2_trailing → tek trailing_prim"

**Test dosyası satır 44-49** hâlâ ESKİ şemayı kullanıyor:
```python
"primnet": {
    "faz1_stop_prim": 1.5,
    "faz2_activation_prim": 2.0,
    "faz2_trailing_prim": 1.0,   # ← Artık yok
    "target_prim": 9.5,
},
```

**Mevcut kod** (`h_engine.py:157-159`):
```python
self._primnet_trailing = primnet_cfg.get("trailing_prim", 1.5)
self._primnet_target   = primnet_cfg.get("target_prim", 9.5)
self._primnet_step     = primnet_cfg.get("step_prim", 0.5)
```

Test config'inde `trailing_prim` yok → kod default 1.5 kullanıyor. Ancak test assertion'ları eski Faz2 değeri olan 1.0'a göre yazılmış (`test_033: expected 2.0, got 1.49` = current 3.0 − trailing 1.5 = 1.5 ≈ 1.49 fp).

**Test yorum satırları kanıt:**
```python
# test_030: expected_sl = 2.5 - 1.0  # "Faz 2 mesafe"
# test_033: "Faz2 SL: beklenen 2.0" (trailing=1.0 varsayımıyla)
```

**Karar:** Bilinçli, onaylı, commit'lenmiş parametre değişikliği. **Kod doğru.** Test güncellenmeli.

**Fix önerisi:**
1. `HYBRID_CONFIG` dict'inde `primnet` bloğu yeni şemaya çevrilir: `trailing_prim`, `target_prim`, `step_prim`
2. `TestFaz1` ve `TestFaz2` sınıfları tek sınıf `TestPrimnetTrailing` altında birleştirilir
3. Assertion değerleri yeni referans tablosuyla (`h_engine.py:2120-2169`) yeniden hesaplanır
4. Yeni test docstring'leri eski Faz1/Faz2 terminolojisi içermez

---

### A2: SELL pozisyonu KeyError (4 test)

**Etkilenen testler:**
- `TestFaz1::test_026_sell_faz1_start`
- `TestFaz1::test_027_sell_faz1_improve`
- `TestFaz1::test_028_sell_faz1_no_regress`
- `TestFaz2::test_035_sell_faz2`

**Kök neden — KANITLANDI:**

Gerçek bridge (`mt5_bridge.py:1952`) pozisyon tipini STRING'e normalize ediyor:
```python
"type": "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL",
```

Test mock'u (`test_hybrid_100.py:188`) INT döndürüyor:
```python
"type": 0 if direction == "BUY" else 1,
```

H-Engine yön tutarlılık kontrolü (`h_engine.py:776-789`):
```python
mt5_direction = mt5_pos.get("type")  # "BUY" veya "SELL" (string bekliyor)
if mt5_direction and mt5_direction != hp.direction:
    # DIRECTION_FLIP → pozisyon otomatik kapatılır
```

- **BUY test senaryosu:** `mt5_direction = 0` (int) → `if 0 and ...` kısa devre → kontrol atlanır (yanlışlıkla geçer)
- **SELL test senaryosu:** `mt5_direction = 1` (int) → `if 1 and 1 != "SELL":` → **DIRECTION_FLIP alarmı tetiklenir** → pozisyon `_finalize_close` ile kapatılır → sonraki assertion'da `hybrid_positions[1001]` zaten silinmiş → **KeyError: 1001**

Log kanıtı:
```
CRITICAL | engine.h_engine - YÖN DEĞİŞİMİ TESPİTİ: ticket=1001 F_AKBNK beklenen=SELL MT5=1
```

**Karar:** Test mock, gerçek bridge kontratıyla uyumsuz. **Kod doğru.**

**Fix önerisi:**
```python
# MockMT5.add_position içinde:
"type": direction,   # "BUY" veya "SELL" string olarak (bridge gibi)
```

**Yan fayda:** BUY testlerinin "tesadüfen" geçmesi de düzelir — gerçek kontrata uyan davranış elde edilir.

---

## Grup B — OĞUL Testleri (4 başarısız)

### B1: `test_11_monthly_dd_blocks` — obsolete davranış

**Test içeriği (satır 653-660):**
```python
def test_11_monthly_dd_blocks(self):
    ogul = make_ogul()
    ogul._monthly_dd_warn = True            # ← dinamik attribute
    ogul._execute_signal(signal, regime)
    ogul.mt5.send_order.assert_not_called()
```

**Kök neden — KANITLANDI:**

`grep -n "_monthly_dd_warn" engine/ogul.py` → **0 match**. Bu attribute kodda yok.

**Anayasa Kural 10** (CLAUDE.md):
> "BABA günlük/aylık kayıp tetiğinde L2 kill-switch devreye girer → `_close_ogul_and_hybrid()` çağrılır... OĞUL artık kendi günlük kayıp check'i yapmaz — tek merkez BABA'dır"

**Karar:** Test eski davranışı arıyor — sorumluluk BABA'ya devredildi.

**Fix önerisi:** Test iki seçenekle düzeltilebilir:
- **Seçenek 1 (temiz):** Test silinir, migration notu eklenir (`critical_flows/test_static_contracts.py` zaten Kural 10'u genel olarak koruyor — `_close_ogul_and_hybrid` varlığını test ediyor)
- **Seçenek 2 (daha eksiksiz):** Test migrasyonu — BABA'ya `monthly_loss_pct = -8.0` verilip `_check_monthly_loss()` tetiklendiği doğrulanır, OĞUL + Hybrid kapanması beklenir

Tavsiye: **Seçenek 1** — static_contracts zaten kurala bekçilik yapıyor, bu test gereksiz duplikasyon.

---

### B2: `test_03/test_04 sl_tightened_after_2h` — modify_position → send_stop migrasyonu

**Test beklentisi:**
```python
ogul._mode_protect("F_THYAO", trade, 1.5)
ogul.mt5.modify_position.assert_called()
```

**Mevcut kod** (`ogul.py:2653-2664`):
```python
if hours >= 2:
    if trade.direction == "BUY":
        new_sl = trade.entry_price - 0.5 * atr_val
        if new_sl > trade.sl:
            if self._sltp.update_trailing_sl(trade, new_sl):   # ← modify_position yerine
                logger.info(f"KORUMA 2saat SL sıkılaştırıldı [{symbol}]: SL={new_sl:.4f}")
```

Log kanıtı (test çıktısından):
```
INFO | engine.ogul_sltp - OgulSLTP başlatıldı (plain STOP modu)
INFO | engine.ogul_sltp - OĞUL SL Stop yerleştirildi [F_THYAO]: order=<MagicMock...send_stop>
INFO | engine.ogul - KORUMA 2saat SL sıkılaştırıldı [F_THYAO]: SL=100.7500
```

**Kanıt:** SL sıkılaştırma ÇALIŞIYOR — sadece `send_stop` yolundan, direkt `modify_position`'dan değil. Bu değişiklik commit `a670e48` ile yapılmış görünüyor: "#120 — Stop Limit → plain STOP/LIMIT migrasyonu".

**Karar:** **Kod doğru.** Test eski API yolunu izliyor.

**Fix önerisi:**
```python
# Seçenek A — davranışa göre assert (önerilen):
original_sl = trade.sl
ogul._mode_protect("F_THYAO", trade, 1.5)
assert trade.sl > original_sl   # BUY için
# veya SELL için: assert trade.sl < original_sl

# Seçenek B — yeni API'ye göre mock:
ogul._sltp.update_trailing_sl = MagicMock(return_value=True)
ogul._mode_protect("F_THYAO", trade, 1.5)
ogul._sltp.update_trailing_sl.assert_called_once()
```

Tavsiye: **Seçenek A** — davranış testi daha dayanıklıdır (gelecekte SL sıkılaştırma yolu tekrar değişirse test yine yeşil kalır).

---

### B3: `test_12_process_signals_olay_regime` — MagicMock karşılaştırma hatası

**Hata noktası** (`ogul.py:562`):
```python
if self.baba and getattr(self.baba, "kill_switch_level", 0) >= 3:
```

**Kök neden — KANITLANDI:**

`make_mock_baba()` fonksiyonu (`test_ogul_200.py:146-155`) şu alanları set ediyor:
- `check_correlation_limits`, `is_symbol_killed`, `calculate_position_size`, `increment_daily_trade_count`

Ama `kill_switch_level` **set edilmiyor**. MagicMock davranışı: set edilmemiş attribute erişimi → **yeni MagicMock** döner (`0` değil!). Dolayısıyla:
```python
getattr(baba, "kill_switch_level", 0)  # → MagicMock (çünkü attr "var" sayılır)
MagicMock >= 3                          # → TypeError
```

**Neden sadece bu test etkileniyor?** Diğer OĞUL testleri `_execute_signal()`'ı doğrudan çağırır (process_signals bypass). Sadece test_12 `process_signals()` yolunu izler, bu yüzden 562. satıra ilk varan testtir.

**Karar:** Test fixture eksikliği. **Kod doğru** (hatta 562. satır bir savunma katmanı — L3 bypass koruması).

**Fix önerisi** — `make_mock_baba`'ya eklenecek:
```python
baba.kill_switch_level = 0   # L0 (güvenli varsayılan)
```

Bu tek satırlık ekleme, tüm testlerin L0 varsayımını sağlamlaştırır — çok düşük riskli.

---

## Uygulama Planı

Her grup ayrı atomik commit. Sıra: en düşük riskli önce.

| Sıra | Grup | Dosya | Değişiklik türü | Risk | Etki |
|---|---|---|---|---|---|
| 1 | B3 | `tests/test_ogul_200.py` | Fixture tek satır (`baba.kill_switch_level = 0`) | 🟢 Çok düşük | +1 PASS |
| 2 | A2 | `tests/test_hybrid_100.py` | MockMT5 `type` field string'e çevir | 🟢 Çok düşük | +4 PASS |
| 3 | B2 | `tests/test_ogul_200.py` | test_03/04 davranış assert'e çevir | 🟢 Düşük | +2 PASS |
| 4 | B1 | `tests/test_ogul_200.py` | test_11 sil (obsolete) | 🟢 Düşük | +1 PASS (test sayısı azalır) |
| 5 | A1 | `tests/test_hybrid_100.py` | TestFaz1/Faz2 yeniden yaz | 🟡 Orta (çok satır) | +7 PASS |

**Her adımdan sonra:**
1. İlgili test paketi `pytest` ile koşulur (yeşile dönmeli)
2. `pytest tests/critical_flows -q --tb=short` regresyon kontrolü (34/34 kalmalı)
3. Sonuç kullanıcıyla teyit edilir
4. Tek atomik commit

**Toplam hedef:** 10.624/10.624 (%100)

---

## Kırmızı Bölge Değerlendirmesi

Yapılacak değişikliklerin hiçbiri Kırmızı Bölge dosyalarına dokunmuyor:
- ❌ `engine/baba.py` — dokunulmaz
- ❌ `engine/ogul.py` — dokunulmaz
- ❌ `engine/h_engine.py` — dokunulmaz (Sarı Bölge ama bu iş için de gereksiz)
- ❌ `config/default.json` — dokunulmaz
- ✅ `tests/test_ogul_200.py` — Yeşil Bölge
- ✅ `tests/test_hybrid_100.py` — Yeşil Bölge

**Anayasa ihlali riski: Yok.**

**Siyah Kapı fonksiyon değişikliği: Yok** — üretim kodu hiç değiştirilmiyor.

---

## Sonuç

Sistemin kalbi (BABA risk, OĞUL emir, MT5 bridge, H-Engine primnet, data pipeline, news filter, kill-switch, EOD, drawdown) **%100 sağlam**. Başarısız 15 test sadece, test paketinin geçmişteki bilinçli kod değişikliklerine henüz senkronize edilmediğini gösteriyor.

Canlı sisteme hiçbir fonksiyonel risk yok. Düzeltmeler sadece test senaryolarını günceller — üretim davranışına hiç dokunmaz.
