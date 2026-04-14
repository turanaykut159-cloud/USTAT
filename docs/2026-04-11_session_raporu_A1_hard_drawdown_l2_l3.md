# Oturum Raporu — A1: Anayasa Kural #6 L2→L3 Eskalasyon Fix

**Tarih:** 2026-04-11 Cumartesi (Barış Zamanı — piyasa kapalı)
**Commit:** `6bf3235`
**Sınıf:** C4 (Siyah Kapı #1 `check_risk_limits` — ADDITIVE bug fix)
**Bölge:** Kırmızı Bölge #1 (`engine/baba.py`)
**Kaynak bulgu:** `docs/2026-04-11_widget_denetimi.md` Bölüm 16.2 B1
**Aksiyon:** Widget Denetimi Aksiyon A1

---

## 1. Özet

Widget denetiminde canlı `/api/risk` çıktısında tespit edilen mantıksal çelişki:

- `total_drawdown_pct = 0.304293` (%30.43)
- `kill_switch_level = 2` (L2)
- `hard_drawdown = 0.15` (%15 limit)
- `kill_switch_details.reason = "daily_loss"` @ `2026-04-11T16:10:49`

Anayasa Kural #6 "hard drawdown ≥%15 → L3 otomatik" davranışı ölü görünüyordu — sistem %30 drawdown'a rağmen L2'de takılıp kalmıştı. Kök neden: `check_risk_limits` fonksiyonunda L2 aktifken koşulsuz early-return yapılıyordu ve `_check_hard_drawdown` çağrısı sadece L0/L1 seviyesinde çalışıyordu.

## 2. Kök Neden Analizi (Kanıt)

### 2.1 Kod okuma
- `engine/baba.py::check_risk_limits` (satır 1472-1563) okundu.
- `engine/baba.py::_check_hard_drawdown` (satır 1817-1844) okundu.
- Grep sonucu: `_check_hard_drawdown` tüm kod tabanında **tek çağrı noktası** (`check_risk_limits` içinde).

### 2.2 Çağrı akışı
```
check_risk_limits:
  1472 ── fonksiyon girişi
  1496 ── if _kill_switch_level == KILL_SWITCH_L3: return (L3 final)
  1509 ── if _kill_switch_level == KILL_SWITCH_L2:
              verdict.can_trade = False
              ...
              return verdict     ◄── KOŞULSUZ RETURN (BUG)
  1554 ── _check_hard_drawdown(...)  ◄── L2 iken asla ulaşılamaz
```

### 2.3 Canlı doğrulama
`/api/risk` çıktısı (saat 14:xx civarı) `floating_loss` büyümesine rağmen `triggered_at=16:10:49` L2 seviyesinde donmuştu — 10 saniyede bir `check_risk_limits` çağrıldığı halde `_check_hard_drawdown` hiçbir zaman tetiklenmemişti.

### 2.4 Anayasa uyum analizi
- **Kural #3 monotonluk:** "Seviye sadece yukarı gider: L1→L2→L3. Otomatik düşürme YASAK." — Yukarı yönde eskalasyon (L2→L3) monotonluğa **uygun** ve zorunlu.
- **Kural #6:** "Felaket drawdown ≥%15 → L3 → tüm pozisyonlar anında kapatılır" — Ön koşulsuz, rejim/seviye bağımsız olmalı.

Çelişki: Kural #6 varken Kural #3 hiçbir zaman L2→L3 yolunu engellemez. Mevcut kod Kural #3'ü hatalı olarak "L2'den çıkmak yasak" olarak yorumluyordu; doğrusu "L2'den L1/L0'a düşüş yasak".

## 3. Atomik Değişiklik

### 3.1 Kod değişikliği
**Dosya:** `engine/baba.py` (Kırmızı Bölge #1, Siyah Kapı #1)
**Fonksiyon:** `check_risk_limits`
**Net satır:** +20 ekleme, 0 silme

L2 return bloğunun başına hard drawdown eskalasyon kontrolü eklendi:

```python
if self._kill_switch_level == KILL_SWITCH_L2:
    # v5.9.4 — Anayasa Kural #6 ESKALASYON FIX (Widget Denetimi B1):
    # Önceki kodda bu blok koşulsuz return ediyordu → _check_hard_drawdown
    # sadece L0/L1 seviyesinde çalışıyordu → L2 aktifken drawdown
    # %15'i aşsa bile L3'e otomatik yükselmiyordu. Kural #3 monotonluk
    # SADECE düşürmeyi yasaklar; yukarı yönde eskalasyon (L2→L3) zorunludur.
    dd_check_l2 = self._check_hard_drawdown(risk_params, snap=snap)
    if dd_check_l2 == "hard":
        self._activate_kill_switch(
            KILL_SWITCH_L3, "hard_drawdown",
            f"L2→L3 eskalasyon: hard drawdown limiti aşıldı "
            f"(>{risk_params.hard_drawdown*100:.0f}%)",
        )
        verdict.can_trade = False
        verdict.lot_multiplier = 0.0
        verdict.risk_multiplier = 0.0
        verdict.kill_switch_level = KILL_SWITCH_L3
        verdict.reason = "Hard drawdown — L2→L3 tam kapanış"
        verdict.blocked_symbols = list(self._killed_symbols)
        return verdict
    # ─── orijinal L2 davranışı (değiştirilmedi) ───
    verdict.can_trade = False
    ...
    return verdict
```

### 3.2 Etki sınırlaması
- **Yeni state:** YOK. `_check_hard_drawdown`, `_activate_kill_switch`, `_close_all_positions` zincirleri zaten mevcuttu.
- **İmza değişikliği:** YOK.
- **Tüketici zinciri:** `ogul.py::_execute_signal` BABA `can_trade` kapısı aynen çalışır — değişim yok.
- **L0/L1 → L3 yolu:** Satır 1554'teki orijinal `_check_hard_drawdown` çağrısı silinmedi, ikinci tetik noktası olarak korundu.
- **Davranış genişlemesi:** SADECE L2 iken drawdown ≥%15 olursa L3'e yükselir. Bu durum zaten Kural #6'da tanımlıydı, sadece kapalıydı.

## 4. Statik Sözleşme Testi

**Dosya:** `tests/critical_flows/test_static_contracts.py`
**Yeni test:** `test_check_risk_limits_escalates_l2_to_l3_on_hard_drawdown` (Flow 4b)

```python
def test_check_risk_limits_escalates_l2_to_l3_on_hard_drawdown():
    from engine.baba import Baba
    src = inspect.getsource(Baba.check_risk_limits)
    assert "KILL_SWITCH_L2" in src
    assert "_check_hard_drawdown" in src
    l2_block_start = src.find("KILL_SWITCH_L2:")
    assert l2_block_start > 0
    l2_block = src[l2_block_start:l2_block_start + 2500]
    assert "_check_hard_drawdown" in l2_block
    assert "KILL_SWITCH_L3" in l2_block
    assert "hard_drawdown" in l2_block
```

Pre-commit hook `.githooks/pre-commit` bu testi çalıştırır. Gelecekte refactor sırasında eskalasyon bloğu silinirse commit bloklanır.

## 5. Doğrulama

### 5.1 Critical flows
```
tests/critical_flows — 35 passed, 3 warnings in 2.43s
```
34 baseline (A1 öncesi) + 1 yeni = 35. Regresyon yok.

### 5.2 Syntax
`engine/baba.py` py_compile temiz.

### 5.3 Etki analizi özeti
| Alan | Durum |
|------|-------|
| Dosya sayısı | 1 (`baba.py`) |
| Fonksiyon | 1 (`check_risk_limits`) |
| Net satır | +20 / -0 |
| İmza değişimi | Yok |
| State değişimi | Yok |
| Tüketici kırığı | Yok |
| Black Door ihlali | Yok (ADDITIVE bug fix, Anayasa Kural #6'yı fonksiyonel hale getirir) |

## 6. Deploy Durumu

- **Commit:** `6bf3235` `main` branch'inde.
- **Build:** N/A (frontend değişikliği yok, engine Python).
- **Restart:** **YAPILMADI.** Piyasa açık, engine canlı. Deploy zamanlaması kullanıcı kontrolünde.
- **Deploy beklentisi:** `restart_app` çalıştırıldığında bir sonraki 10sn döngüsünde `check_risk_limits` L2 bloğuna girip `_check_hard_drawdown` çağrısını yapacak, mevcut `total_drawdown_pct=0.3043 > 0.15` koşulu nedeniyle L3'e yükseltip tek açık pozisyonu kapatacak. **Bu beklenen ve istenen davranıştır** — sistem zaten %30 drawdown'da olduğu için L3 otomatik tetiği gerçekleşmesi gereken korunma.

## 7. Sonraki Adımlar (Widget Denetimi)

| ID | Durum | Açıklama |
|----|-------|----------|
| A1 | ✅ Commit tamam, deploy bekliyor | Bu oturum |
| A2 | ⏳ Sıradaki | Trade data güvenilirliği (F_TOASO BUY exit<entry pnl=+2705 bug) |
| A3 | ⏳ | Notification preferences gerçek binding |
| A4 | ⏳ | Monitor engine status (kill_switch_level göz ardı ediliyor) |
| A5 | ⚠️ İptal adayı | Versiyon hardcode — ancak commit #164 ile v6.0.0 legitimate, audit H1 yanlış |

## 8. Referanslar
- Denetim raporu: `docs/2026-04-11_widget_denetimi.md` (Bölüm 16.2 B1, Bölüm 17 A1)
- Changelog: `docs/USTAT_GELISIM_TARIHCESI.md` entry #165 (Security)
- CLAUDE.md: Bölüm 4.4 Siyah Kapı #1, Bölüm 4.5 Kural #3 #6, Bölüm 7 İşlemi Bitir prosedürü
- USTAT_ANAYASA.md v2.0
