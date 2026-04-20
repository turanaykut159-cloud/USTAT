# 2026-04-20 — Oturum Raporu: Baseline Güncellemesi ile `monthly_paused` Sıfırlama

**Versiyon:** 6.2.0 (artış yok — 1 dosya, ~50 satır değişim)
**Sınıf:** C2 — Green Zone (`api/routes/settings.py`)
**Commit:** (aşağıda)
**Değiştirilen Dosya Sayısı:** 2 (kod: 1, doküman: 1) + bu rapor

---

## 1. Problem Tanımı

Kullanıcı ekranında `Risk Yönetimi → İşlem İzni: KAPALI` ve altında `"Aylık kayıp limiti — manuel onay bekleniyor"` mesajı vardı. Paradoks:

- `can_trade: false`
- `kill_switch_level: 0` (Yok)
- Aynı anda `risk_reason` monthly_paused'u gösteriyor

Kullanıcı Settings sayfasındaki "Risk Hesaplama Başlangıcı" (baseline_date) alanını değiştirdi ama bayrak temizlenmedi. İki ana soru:

1. Baseline değişimi neden `monthly_paused`'u sıfırlamıyordu?
2. Bu bayrak normalde nerden sıfırlanıyor?

## 2. Kök Neden Analizi

### 2.1 `monthly_paused` Sıfırlama Yolları (Kod Taraması)

Agent-destekli tam tarama:

- **Set:** `engine/baba.py:1591` — `_check_monthly_loss` eşiği aşıldığında `monthly_paused=True` + `_activate_kill_switch(KILL_SWITCH_L2, ...)`
- **Reset (TEK YOL):** `engine/baba.py:2459` — `acknowledge_kill_switch` içinde `monthly_paused = False` + `_clear_kill_switch`
- `_reset_monthly` **DOKUNMAZ** — satır 1460'ta açık yorum: `# monthly_paused SIFIRLANMAZ — manuel onay gerekli`

### 2.2 Baseline Güncellemesinin Eski Davranışı

`api/routes/settings.py::update_risk_baseline` (eski 6 adım):
1. Tarih formatı doğrula
2. Config bellek + dosya güncelle
3. `baba.risk_baseline_date = new_date`
4. `baba_module.RISK_BASELINE_DATE` (data_pipeline uyumu)
5. (yok)
6. `db.set_state("peak_equity", current_equity)` → drawdown sıfırlanır

**`_risk_state["monthly_paused"]` bayrağına hiç dokunulmuyordu.**

### 2.3 UI Kanalı Neden Bozuk

`desktop/src/components/TopBar.jsx:209`:
```jsx
{phase === 'killed' && (<button onClick={handleKsReset}>Sıfırla</button>)}
```

Buton yalnızca `phase === 'killed'` koşulunda görünüyor. Kullanıcının durumu:
- `phase`: muhtemelen `running`
- `kill_switch_level`: 0 (`phase !== 'killed'`)
- `monthly_paused`: True (orphan state)

Yani UI'dan manuel onay kanalı kapalıydı. Üstelik `acknowledge_kill_switch` (`baba.py:2433`) kill_switch_level==NONE iken erken `return False` yapıyor — direkt API çağrısı bile bu orphan durumda çalışmaz.

### 2.4 Kanıt Zinciri

1. `grep "monthly_paused = False"` → TEK sonuç: `baba.py:2459`
2. `acknowledge_kill_switch` gövdesi satır 2421-2461 — L0 early return satır 2433
3. `/api/risk` canlı yanıt (restart öncesi):
   ```
   can_trade: false, kill_switch_level: 0, risk_reason: "Aylık kayıp limiti — manuel onay bekleniyor"
   ```

## 3. Değişiklik Planı ve Sınıflandırma

### 3.1 Sınıf

- **Zone:** Green — `api/routes/settings.py` Kırmızı/Sarı Bölge dışında
- **Class:** C2 — tek dosya, davranış ekleme, Siyah Kapı değişmiyor
- **Yaklaşım:** Mevcut `acknowledge_kill_switch` API'sini ek bir tetikleyiciden (baseline update) çağırmak; L0 orphan durumu için doğrudan state flip

### 3.2 Kullanıcı Talebi (Onay)

> "şuan test sürecince olduğumuz için değiştirelim kurallara dokunma. aynısı kalsın babanın risk limitini sırlayalım ayarlada ki tarihe bağla."

Yorum: (a) Siyah Kapı fonksiyonlarını ve anayasayı bozma, (b) mevcut manuel onay mantığı aynen kalsın, (c) baseline değişimini ek bir manuel onay tetikleyicisi olarak ekle.

### 3.3 Geri Alma Planı

Tek commit, tek dosya: `git revert <hash>` → eski 6-adımlı davranışa döner.

## 4. Uygulanan Değişiklik

### 4.1 `api/routes/settings.py`

**Yeni blok (75 satır, peak_equity reset'inden sonra, final log'dan önce):**

```python
# 7. v6.2 — monthly_paused + aktif kill-switch sıfırla.
# İki senaryo: (a) Kill-switch aktifse acknowledge_kill_switch çağrılır —
# monthly_paused'u da o fonksiyon temizler. (b) Kill-switch L0 ama
# monthly_paused True ise (orphan state) doğrudan False'a çekilir çünkü
# acknowledge L0'da False döner (baba.py:2433). _risk_state kalıcılığı
# bir sonraki BABA cycle'ında _persist_risk_state() ile DB'ye yazılır.
risk_reset_msg = ""
if baba is not None:
    try:
        prev_mp = baba._risk_state.get("monthly_paused", False)
        prev_ks = getattr(baba, "_kill_switch_level", 0)

        if prev_ks > 0:
            ack_ok = baba.acknowledge_kill_switch(user="baseline_reset")
            if ack_ok:
                risk_reset_msg = f"kill-switch L{prev_ks} + monthly_paused temizlendi"
            else:
                risk_reset_msg = (
                    f"kill-switch L{prev_ks} sıfırlama REDDEDİLDİ "
                    f"(açık pozisyon engeli — baba.py:2437)"
                )
        elif prev_mp:
            baba._risk_state["monthly_paused"] = False
            risk_reset_msg = "monthly_paused: True → False (kill-switch L0)"

        if risk_reset_msg:
            logger.info(f"Baseline reset ile risk durumu sıfırlandı: {risk_reset_msg}")
    except Exception as exc:
        logger.warning(f"Risk durumu sıfırlama hatası: {exc}")
```

Response mesajına `risk_reset_msg` eklendi (| ayraçlı).

Docstring 7. adım açıklamasıyla güncellendi.

### 4.2 Ne Değişmedi

- `engine/baba.py` — hiçbir satır
- `acknowledge_kill_switch` gövdesi (AST doğrulandı): L0 early return + `monthly_paused = False` aynen
- `_reset_monthly` — yorum: `# monthly_paused SIFIRLANMAZ — manuel onay gerekli` intakt
- Anayasa Kural 3 (Kill-Switch Monotonluk) — ihlal yok; baseline değişimi operatörün bilinçli eylemi olduğu için manuel onay yerine geçer

## 5. Doğrulama

### 5.1 Statik

- `python3 -c "import ast; ast.parse(...)"` → SYNTAX OK
- AST taraması: `acknowledge_kill_switch` çağrısı + `monthly_paused = False` ataması tespit edildi
- `baba.py` yorumu ve fonksiyon gövdesi değişmedi (hash-benzeri içerik kontrolü)

### 5.2 Test Paketi (Windows ajan, Python 3.14)

```
python -m pytest tests/critical_flows -q --tb=short
119 passed, 3 warnings in 6.31s
```

Tüm 119 kritik akış testi yeşil. Anayasal korumalar ihlal edilmedi.

### 5.3 Canlı API Testi

**Öncesi (restart sonrası):**
```json
GET /api/risk
{ "can_trade": false, "kill_switch_level": 0, "risk_reason": "Aylık kayıp limiti — manuel onay bekleniyor" }
```

**Baseline update çağrısı:**
```json
POST /api/settings/risk-baseline  {"new_date":"2026-04-20"}
{
  "success": true,
  "message": "Risk baseline tarihi güncellendi: 2026-04-19 09:50 → 2026-04-20 | monthly_paused: True → False (kill-switch L0)",
  "old_date": "2026-04-19 09:50",
  "new_date": "2026-04-20"
}
```

**Sonrası (12sn BABA cycle bekledikten sonra):**
```json
GET /api/risk
{ "can_trade": true, "kill_switch_level": 0, "risk_reason": "" }
```

Beklenti ↔ gerçek eşleşti.

## 6. Adımlar (CLAUDE.md §7 İŞLEMİ BİTİR)

| Adım | Durum |
|------|-------|
| 1 — Frontend Build | ATLANDI (backend-only) |
| 1.5 — Kritik akış testleri | ✅ 119/119 pass |
| 2 — Gelişim tarihçesi | ✅ #290 eklendi |
| 3 — Versiyon hesabı | Değişim <%1 → artış yok (6.2.0 aynı) |
| 4 — Versiyon bump | Gereksiz |
| 5 — Git commit | (aşağıda) |
| 6 — Oturum raporu | ✅ bu dosya |

## 7. Git Commit Taslağı

```
fix(settings): baseline güncellemesi monthly_paused ve aktif kill-switch'i de sıfırlar (#290)

- api/routes/settings.py: update_risk_baseline endpoint'ine 7. adım eklendi
- Kill-switch aktifse baba.acknowledge_kill_switch çağrılır (mp de temizlenir)
- Kill-switch L0 ama monthly_paused orphan ise state doğrudan False
- baba.py Siyah Kapı fonksiyonları ve "manuel onay gerekli" yorumu intakt
- Canlı test: stuck state → baseline update → can_trade=true

Kritik akış testleri: 119/119 pass
Test sürecinde, kullanıcı talebi.
```

## 8. Riskler ve Notlar

**Semantik risk:** Baseline değişimi otomatik olarak aylık durdurmayı kaldırıyor. Test sürecinde kullanıcı tarafından istendi; canlı hesapta kullanılırsa operatör baseline oynarken farkında olmadan risk kapısını açabilir. Gelecekte UI tarafında bir onay diyaloğu ("Baseline değişimi mevcut aylık durdurmayı da temizleyecek — devam?") eklenmesi düşünülmeli.

**Persistency:** `monthly_paused = False` değişikliği in-memory `_risk_state`'de yapılıyor; bir sonraki BABA cycle'ında (≤10sn) `_persist_risk_state` ile DB'ye yazılır. Bu arada engine crash olursa değişiklik kaybolur — ama kritik değil, baseline update kaydı config dosyasında kalır, kullanıcı bir sonraki başlatmada tekrar tetikleyebilir.

**Gelecek iyileştirme önerileri:**
1. `/api/risk` yanıtına `monthly_paused: bool` alanı ekle (şu an sadece `risk_reason` üzerinden görünüyor)
2. TopBar "Sıfırla" butonu görünürlük koşulunu genişlet: `phase==='killed' || killLevel>=1 || risk.monthly_paused`
3. Risk Yönetimi sayfasındaki KillSwitchInfoModal'a "Onayla ve Sıfırla" butonu ekle
