# Oturum Raporu — A8 (K10): Hibrit SL/TP Görünürlüğü Dashboard'da

**Tarih:** 11 Nisan 2026 (Pazar, Barış Zamanı)
**Bulgu:** Widget Denetimi A8 (K10) — Dashboard (3.3) hibrit pozisyonlarda sanal koruma görünmüyor
**Sınıf:** C2 (Sarı Bölge — `api/routes/positions.py`)
**Zaman dilimi:** Pazar — piyasa kapalı, Barış Zamanı
**Anayasa uyumu:** Siyah Kapı yok ✓, Kırmızı Bölge yok ✓, Sarı Bölge gerekçeli ✓

---

## 1. Kök Neden

Dashboard "Açık Pozisyonlar" tablosunda SL/TP kolonları `pos.sl` ve `pos.tp` ile doğrudan MT5 native değerlerini gösteriyordu. Hibrit strateji ile açılan pozisyonlarda bu değerler genelde 0 gelir çünkü:

- H-Engine hibrit pozisyonlara MT5 native SL/TP GÖNDERMEZ (design kararı: sanal koruma + çabuk trailing için)
- Gerçek koruma `engine/h_engine.py::HybridPosition.current_sl` / `.current_tp` alanlarında sanal olarak tutulur
- H-Engine `run_cycle` her 10 saniyede breakeven / trailing / TP1 / EOD güncellemelerini bu iki alan üzerinden hesaplar

Sonuç: Dashboard'da hibrit satır kullanıcıya "SL ve TP yok → pozisyon korumasız" izlenimi verir. Gerçekte sanal koruma aktif ama UI bunu göstermiyor. Audit K10 kritik/orta sınıf: finansal yanıltma potansiyeli.

## 2. Çözüm (4 dosya + 1 test)

### 2.1 Schema Genişletme — `api/schemas.py`

`PositionItem` modeline iki yeni opsiyonel alan:

```python
hybrid_sl: float = 0.0
hybrid_tp: float = 0.0
```

Default 0.0 → geriye dönük uyumlu. Frontend eski bir sürümü çalıştıran kullanıcı crash yaşamaz. Schema yorumu Flow 4zb test referansını içerir.

### 2.2 Route Doldurma — `api/routes/positions.py`

`get_positions` içinde her pozisyon için:

```python
hybrid_sl_val = 0.0
hybrid_tp_val = 0.0
if ticket in hybrid_tickets and h_engine:
    hp = h_engine.hybrid_positions.get(ticket)
    if hp is not None:
        hybrid_sl_val = float(getattr(hp, "current_sl", 0.0) or 0.0)
        hybrid_tp_val = float(getattr(hp, "current_tp", 0.0) or 0.0)
```

Defensive read path:
- `ticket in hybrid_tickets` kontrolü — manuel/otomatik/MT5 satırlarında hiç çalışmaz
- `h_engine is None` guard — lifespan sırasında engine henüz hazır değilse çökmez
- `hybrid_positions.get(ticket)` — dict key miss guard (timing race'te NoneType AttributeError yerine 0.0 döner)
- `getattr(..., 0.0)` — HybridPosition dataclass değişirse crash'e yol açmaz

Manuel/Otomatik/MT5 satırlarında varsayılan 0.0 kalır (frontend bu değeri göstermez, mevcut MT5 native SL/TP gösterimini korur).

### 2.3 Dashboard UI — `desktop/src/components/Dashboard.jsx`

SL ve TP hücreleri koşullu mantıkla yeniden yazıldı:

```jsx
<td
  className={`mono text-dim ${(turClass === 'hybrid' && !(pos.sl > 0)) ? 'op-hybrid-virtual' : ''}`}
  title={
    (turClass === 'hybrid' && !(pos.sl > 0) && (pos.hybrid_sl || 0) > 0)
      ? 'Bu değer MT5 native değil, H-Engine sanal korumadır (breakeven/trailing/EOD yönetimi).'
      : ''
  }
>
  {(turClass === 'hybrid' && !(pos.sl > 0) && (pos.hybrid_sl || 0) > 0)
    ? <em>{formatPrice(pos.hybrid_sl)}</em>
    : formatPrice(pos.sl)}
</td>
```

Davranış matrisi:

| Satır türü | MT5 native `sl` | Gösterim |
|---|---|---|
| Hibrit | 0 | `pos.hybrid_sl` italik + tooltip |
| Hibrit | >0 | MT5 native (öncelik MT5'e) |
| Otomatik / Manuel / MT5 | herhangi | Mevcut davranış (değişmedi) |

TP hücresi aynı mantıkla. Öncelik MT5 native'de çünkü hibrit pozisyon MT5 native SL/TP aldıysa (nadir ama mümkün, örn. H-Engine bilinçli olarak native set ettiyse), o gerçek güvenlik katmanıdır. Sanal SL/TP fallback.

CSS class `op-hybrid-virtual` — opsiyonel, stillendirme için placeholder. Mevcut `text-dim` korunuyor (hücre henüz yumuşak görünür).

### 2.4 Flow 4zb — Statik Sözleşme Testi

`tests/critical_flows/test_static_contracts.py` içine `test_hybrid_sltp_visibility_in_positions_response` eklendi (5 aşama):

1. **Schema alanları** — `hybrid_sl: float =` ve `hybrid_tp: float =` regex eşleşmesi
2. **Route hybrid_positions okuyor** — `h_engine.hybrid_positions` + `current_sl` + `current_tp` string aramaları
3. **Route kwarg veriyor** — `hybrid_sl=hybrid_sl_val` + `hybrid_tp=hybrid_tp_val` regex eşleşmesi
4. **Dashboard referansları** — `pos.hybrid_sl` + `pos.hybrid_tp` + "sanal koruma" tooltip marker'ı
5. **Audit markerları** — `A8` + `K10` marker'ları schema + route + dashboard dosyalarında

## 3. Anayasa Uyumu

| Kontrol | Sonuç |
|---|---|
| Siyah Kapı dokunusu | Yok — `get_positions` korunan fonksiyon listesinde değil |
| Kırmızı Bölge | Yok |
| Sarı Bölge | `api/routes/positions.py` dokunuldu — gerekçe: hibrit SL/TP frontend'e sadece burada geçebilir. Değişiklik additive, mevcut alanlar (`sl`, `tp`, `tur`, `pnl`) aynen korunuyor. Manuel/Otomatik/MT5 satırlarının davranışı değişmedi. Defensive guard'lar eklendi (None check + getattr fallback) |
| Çağrı sırası | Değişmedi |
| Config | Değişmedi |
| Backend motor davranışı | H-Engine run_cycle dokunulmadı |
| Schema geriye uyum | `hybrid_sl` / `hybrid_tp` default 0.0 — eski client crash etmez |
| Piyasa zamanı | Barış Zamanı (Pazar) ✓ |

## 4. Test ve Build

**Kritik akış testleri:**
```
python -m pytest tests/critical_flows -q --tb=short
61 passed, 3 warnings in 3.54s
```

Baseline 60 → 61 (Flow 4zb eklendi). İlk koşuda yeşil.

**Production build:**
```
python .agent/claude_bridge.py build
ustat-desktop@6.0.0
vite v6.4.1 building for production...
✓ 730 modules transformed
dist/assets/index-BHiPf3Rm.js   892.07 kB │ gzip: 255.77 kB
✓ built in 2.68s
```

Modül sayısı aynı (730), bundle +0.57 kB (Dashboard koşullu mantık + tooltip metni).

## 5. Değişiklik Özeti

| Dosya | Tür | Satır |
|---|---|---|
| `api/schemas.py` | DEĞİŞTİ | +12 / 0 |
| `api/routes/positions.py` | DEĞİŞTİ | +16 / 0 |
| `desktop/src/components/Dashboard.jsx` | DEĞİŞTİ | +28 / 2 |
| `tests/critical_flows/test_static_contracts.py` | DEĞİŞTİ | +90 / 0 |
| `docs/USTAT_GELISIM_TARIHCESI.md` | DEĞİŞTİ | +1 / 0 |
| `docs/2026-04-11_session_raporu_A8_hybrid_sltp_visibility.md` | YENİ | +~180 |

**Toplam:** 4 değişiklik dosyası + 1 yeni test + 1 changelog girişi + 1 oturum raporu.

## 6. Sonraki Maddeler

A8 kapatıldı. Backlog'da sırada:

- **A15** — Error resolve `message_prefix` DB yazımı (B18, Orta)
- **A6** — Performans equity vs deposit ayrımı (B14, Yüksek)
- **B8** — Otomatik Pozisyon Özeti duplicate + sayısal tutarsızlık (Yüksek)

Mandate: otonom olarak devam et.
