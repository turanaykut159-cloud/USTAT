# Oturum Raporu — H17: RiskResponse.graduated_lot_mult Dead Field Kaldırıldı

**Tarih:** 11 Nisan 2026 (Cumartesi — Barış Zamanı)
**Konu:** Widget Denetimi H17 — `api/schemas.py::RiskResponse.graduated_lot_mult` ölü placeholder alanı temizlendi
**Değişiklik Sınıfı:** C1 (Yeşil Bölge)
**İşlem Tipi:** Tek atomik değişiklik (1 schema dosyası + 1 test)

---

## 1. Kapsam

Widget Denetimi `docs/2026-04-11_widget_denetimi.md` Bölüm 16.3 H17:
> **Risk Yönetimi (11.5)** — `graduated_lot_mult` RiskResponse'ta var ama
> frontend'de gösterilmiyor — config'den gelen graduated lot limiti UI'de eksik. (Orta kritiklik)

Bu madde çözüldü — ama audit ipucunun önerdiği biçimde ("frontend'de göster")
değil, tam tersi yönde: **dead field olarak kaldırıldı.** Sebep: graduated
lot mantığı zaten `lot_multiplier` alanı üzerinden aktarılıp UI'de
gösteriliyordu. `graduated_lot_mult` v5.1'de eklenmiş ama hiçbir üretici
veya tüketici kazanmamış yetim bir placeholder idi.

---

## 2. Kök Neden

**Önceki durum** (`api/schemas.py` satır 250-251):

```python
class RiskResponse(BaseModel):
    ...
    # Pozisyon limitleri
    open_positions: int = 0
    max_open_positions: int = 5

    # Graduated lot (v5.1)
    graduated_lot_mult: float = 1.0
    ...
```

`grep -r graduated_lot_mult` tüm projede yalnızca 3 eşleşme buldu:
1. `api/schemas.py` — alan tanımı (yukarıdaki)
2. `docs/2026-04-11_widget_denetimi.md` — audit bulgusu
3. `docs/USTAT_GELISIM_TARIHCESI.md` — tarihçe girişleri

Yani **üretici sıfır, tüketici sıfır.** Ne `api/routes/risk.py::get_risk`
bu alana atama yapıyordu ne de frontend'deki herhangi bir bileşen bu alanı
okuyordu. Her request'te default `1.0` değeri ile dönüyordu — hiçbir gerçek
BABA state'ini yansıtmıyordu.

**BABA'nın graduated lot mantığı nerede?**

`engine/baba.py` içinde iki yerde:

```python
# Satır 1608 (4 ardışık kayıp → lot %50'ye)
verdict.lot_multiplier = 0.50
verdict.reasons.append("4 ardışık kayıp — lot %50")

# Satır 1698-1699 (haftalık/aylık kayıp graduated)
graduated = {1: 0.75, 2: 0.50}
verdict.lot_multiplier *= graduated.get(violations, 0.25)
```

Sonuç `verdict.lot_multiplier` alanına yazılır. `api/routes/risk.py` satır
141'de şu zincir var:

```python
resp.lot_multiplier = verdict.lot_multiplier
```

`RiskResponse.lot_multiplier` alanı (satır 229, `lot_multiplier: float = 1.0`)
bu değeri taşır. `RiskManagement.jsx` satır 275-280:

```jsx
<div>Lot Çarpanı</div>
<div>{risk.lot_multiplier?.toFixed(2) ?? '—'}</div>
```

"Lot Çarpanı" kartı graduated lot değerini zaten gösteriyor. Audit ipucunun
tarif ettiği eksiklik aslında yoktu — sadece yanlış yerden bakılmıştı
(dead `graduated_lot_mult` alanına, canonical `lot_multiplier` alanı yerine).

---

## 3. Yapılan Değişiklikler

### 3.1 `api/schemas.py` — Dead Field Removal

**Önce:**

```python
# Pozisyon limitleri
open_positions: int = 0
max_open_positions: int = 5

# Graduated lot (v5.1)
graduated_lot_mult: float = 1.0
```

**Sonra:**

```python
# Pozisyon limitleri
open_positions: int = 0
max_open_positions: int = 5

# ── Not (Widget Denetimi H17) ──
# Eski `graduated_lot_mult: float = 1.0` v5.1'de placeholder olarak eklenmişti,
# hiçbir üretici tarafından populate edilmiyor, hiçbir frontend tüketicisi yok.
# BABA'nın graduated lot mantığı (0.75, 0.50, 0.25, vb.) zaten `lot_multiplier`
# alanına (line 229) `verdict.lot_multiplier` üzerinden aktarılır ve
# RiskManagement.jsx'te "Lot Çarpanı" kartında görünür. Dead field regression
# koruması: Flow 4t statik sözleşme testi.
```

Net değişiklik: 1 alan silindi, 7 satır yorum eklendi.

### 3.2 `tests/critical_flows/test_static_contracts.py` — Flow 4t

Yeni statik sözleşme testi `test_risk_response_has_no_dead_graduated_lot_mult`
5 aşamalı kontrol yapar:

**(a) Schema'da dead field YASAK:**
```python
field_def_re = re.compile(r"^\s*graduated_lot_mult\s*:\s*", re.MULTILINE)
assert not field_def_re.search(schemas_src)
```
Regex ile sadece Python alan tanımını yakalar — yorum satırındaki
"`graduated_lot_mult`" backtick referansı eşleşmez (regex `^\s*` satır
başı gerektirir, yorum satırları `#` ile başlar).

**(b) Canonical alan korundu:**
```python
assert "lot_multiplier: float" in schemas_src
```

**(c) Route zinciri aktif:**
```python
assert "resp.lot_multiplier = verdict.lot_multiplier" in risk_route_src
```

**(d) UI tüketiyor:**
```python
assert "risk.lot_multiplier" in rm_src
assert "Lot Çarpanı" in rm_src
```

**(e) UI'de dead field referansı YASAK:**
```python
assert "graduated_lot_mult" not in rm_src
```

### 3.3 `docs/USTAT_GELISIM_TARIHCESI.md`

#183 girişi #182'den önce eklendi (1 madde, kapsamlı kök neden + çözüm +
gerekçe bloğu).

---

## 4. Neden Populate Değil Removal?

Audit ipucu "frontend'de göster" diyordu. Dört gerekçe removal'ın daha
doğru çözüm olduğunu gösteriyor:

1. **`verdict.lot_multiplier` zaten graduated lot bilgisini taşıyor.**
   Paralel ikinci bir alan eklemek "hangisi doğru?" belirsizliği yaratır.
   Tek source of truth principle.

2. **`RiskManagement.jsx::Lot Çarpanı` kartı zaten var ve çalışıyor.**
   UI'de graduated lot işlevi eksik değil — sadece yanlış alan adına
   bakılmıştı. İki kart göstermek (biri `graduated_lot_mult`, diğeri
   `lot_multiplier`) kullanıcıyı kafasını karıştırır.

3. **Dead field bakım yükü yaratır.** Bir yıl sonra başka bir geliştirici
   bu alanı görüp "bu ne iş yapıyor?" sorusuyla saati harcar. Temizlik
   dürüst çözüm.

4. **CLAUDE.md Bölüm 3.2 "sihirli sayılar YASAK" kuralı** tam olarak bu
   tür "hep default döndüren placeholder" durumlarına karşı. Alan her
   request'te `1.0` döndürüyordu — bu tam olarak sihirli sabit.

---

## 5. Anayasa Uyumu

- **Kırmızı Bölge dokunuşu:** YOK. `engine/baba.py`, `engine/ogul.py`,
  `engine/mt5_bridge.py`, `config/default.json` — hiçbirine dokunulmadı.
- **Sarı Bölge dokunuşu:** YOK.
- **Yeşil Bölge dosyaları:** `api/schemas.py`,
  `tests/critical_flows/test_static_contracts.py`,
  `docs/USTAT_GELISIM_TARIHCESI.md`.
- **Siyah Kapı fonksiyonu:** Dokunulmadı. `check_risk_limits`,
  `_activate_kill_switch`, `calculate_position_size` korunuyor.
- **Çağrı sırası:** Dokunulmadı (BABA → OĞUL → H-Engine → ÜSTAT).
- **Config değişikliği:** YOK.
- **Motor davranışı:** Değişmedi. Yalnızca ölü şema alanı temizlendi —
  hiçbir üretici/tüketici etkilenmedi (zaten YOKLARDI).

---

## 6. Test ve Build Sonuçları

### 6.1 Kritik akış testleri

```
python -m pytest tests/critical_flows -q --tb=short
```

Sonuç: **53 passed, 3 warnings in 3.70s**. Flow 4t yeni eklendi, 52
baseline dokunulmadan geçti.

### 6.2 Windows production build

```
python .agent/claude_bridge.py build
```

Sonuç: **başarılı**, `ustat-desktop@6.0.0`, 728 modül transform edildi,
2.74s, `index.js` 889.46 kB (gzip 254.84 kB), `index.css` 90.52 kB.

Bundle boyutu H15 ile aynı kaldı (889.46 kB) — beklendiği gibi, çünkü
schema temizliği frontend'de hiçbir referans etkilemiyordu.

---

## 7. Versiyon Durumu

Tek atomik C1 temizlik, ~50 satır net ekleme (çoğu test kodu + yorum).
Versiyon `v6.0.0` korunuyor. Cumulative widget denetimi değişiklikleri
(A-H3, H4, H15, H17) hâlâ minor bump eşiğinin altında.

---

## 8. Dosya Listesi

1. `api/schemas.py` (-1 alan / +7 yorum)
2. `tests/critical_flows/test_static_contracts.py` (+55 satır — Flow 4t)
3. `docs/USTAT_GELISIM_TARIHCESI.md` (+1 madde — #183)
4. `docs/2026-04-11_session_raporu_H17_graduated_lot_mult_dead_field.md` (yeni — bu dosya)

---

## 9. Dokunulmayanlar (Bilinçli)

- **`engine/baba.py` graduated lot mantığı** — Kırmızı Bölge + Siyah
  Kapı, scope dışı. Zaten doğru çalışıyor (`{1: 0.75, 2: 0.50}` dict).
- **`api/routes/risk.py::get_risk`** — `resp.lot_multiplier =
  verdict.lot_multiplier` zinciri değiştirilmedi. Regresyon riski sıfır.
- **`RiskManagement.jsx` "Lot Çarpanı" kartı** — zaten `risk.lot_multiplier`
  okuyor. Dokunulmadı.
- **Config anahtarı eklemek** — `config.engine.graduated_loss_thresholds`
  gibi bir anahtar EKLENMEDİ. Ardışık kayıp → çarpan mapping'i policy
  değil safeguard — config'e çıkarmak saçma esneklik seviyesi olur
  (kullanıcı 3 ardışık kayıp sonrası lot'u 10'a çekebilir mi? → hayır,
  güvenlik).
- **`lot_multiplier: float = 1.0` canonical alan** — korundu, zaten
  doğru çalışan source of truth.

---

## 10. Sonuç

Widget Denetimi H17 maddesi tamamen kapatıldı. `RiskResponse` artık
dead field taşımıyor — schema daha dürüst, gelecekteki bakım yükü
azaltıldı. Graduated lot bilgisinin canonical aktarım yolu
(`verdict.lot_multiplier → resp.lot_multiplier → risk.lot_multiplier →
"Lot Çarpanı" kartı`) Flow 4t testi ile sözleşmelendirildi — gelecekte
ölü alan geri eklenmeye çalışılırsa veya canonical zincir kırılırsa
pre-commit hook commit'i bloklar.

Audit ipucunun "frontend'de göster" önerisi yanıltıcıydı — işlev zaten
UI'de mevcuttu, sadece yanlış alan adına bakılmıştı. Dürüst çözüm:
schema temizliği + regresyon koruması.

Sonraki aday: H8 (NABIZ TABLE_THRESHOLDS — Orta), H12 (Ayarlar açık tema
tıklanabilir ama eksik — Orta) veya H7/H9/H11/H13/H16/H18 (Düşük).
Sıradaki pick aynı disiplinle devam edecek.
