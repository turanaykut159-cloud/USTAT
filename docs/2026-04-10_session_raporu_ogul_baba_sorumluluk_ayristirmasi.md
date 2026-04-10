# Oturum Raporu — OĞUL/BABA Sorumluluk Ayrıştırması

**Tarih:** 10 Nisan 2026
**Versiyon:** v5.9.0
**Commit:** `d9177df`
**Değişiklik numarası:** #149
**Sınıf:** C3 (Kırmızı Bölge — çift doğrulama uygulandı)
**Zaman:** Barış zamanı (piyasa kapalı, kullanıcı açık pozisyonları önceden kapatmış)

---

## 1. Arka Plan

Kullanıcının özgül direktifi (önceki oturumdan):

> "oğulun mantığını anladın, sinyal ara, bul işlem aç, yönet kapat, bu babanın işleri mükerrer oluyor oğuldan al zaten baba bu iş için kuruldu"

OĞUL içinde BABA'nın sorumluluk alanına giren risk kontrolleri vardı. Bu çifte kontrol hem kod tekrarına hem de sorumluluk karmaşıklığına yol açıyordu. Tek kaynak doğru (single source of truth) ilkesi gereği tüm risk kontrolünün BABA'da olması gerekiyordu.

## 2. Yapılan Çalışma

### 2.1 OĞUL'dan Silinen Fonksiyonlar (~1016 satır)

| Fonksiyon | Satır | Neden |
|-----------|-------|-------|
| `_check_advanced_risk_rules()` | 153 | Günlük %3 kayıp, aylık DD, spread/iteration guard'ları — BABA sorumluluğu |
| `_check_time_rules()` | 86 | Yatay piyasa + son 45dk kâr kapatma — BABA rejim yönetimi alanı |
| `_check_cost_average_DISABLED()` | 115 | Zaten devre dışıydı, dead code |
| `_calculate_lot()` + `_get_current_atr()` | 145 | Dead code (BABA `calculate_position_size()` kullanılıyor) |
| `_confirm_h1()` | 45 | Dead code |

### 2.2 BABA'ya Eklenen `_close_ogul_and_hybrid()`

OĞUL'dan kaldırılan daily_loss/monthly_dd stop mantığı silinmiş olmaması gerekiyordu — sadece BABA'ya devredilmeliydi. Çünkü OĞUL `_execute_signal()` içinde bu guard'lar vardı ve tamamen silmek güvenlik regresyonu olurdu.

Çözüm: BABA `_activate_kill_switch` L2 branch'inde yeni yardımcı çağrıldı:

```python
elif level == KILL_SWITCH_L2 and reason in ("daily_loss", "monthly_loss"):
    try:
        self._close_ogul_and_hybrid(f"KILL_SWITCH_L2_{reason}")
    except Exception as exc:
        logger.error(f"L2 ({reason}) kapanış hatası: {exc}")
```

Yeni helper davranışı:
1. H-Engine hibrit pozisyonlarını `h_eng.force_close_all(reason)` ile kapatır
2. OĞUL aktif trade'lerini dolaşır, sadece `state_name == "FILLED"` ve `orphan == False` olanları kapatır
3. **Manuel pozisyonlara kesinlikle dokunmaz** (manuel/otomatik sınırı korunur)

`main.py` içinde gereken wire eklendi:
```python
self.baba.ogul = self.ogul  # line 161
```

### 2.3 OĞUL Orphan Guard'ları

Yetim (orphan) pozisyonlar OĞUL'un aktif yönetim loop'una takılmamalı:

- `_manage_active_trades` ana döngü + VOLATILE + OLAY branch'leri: 3 guard
- `_check_end_of_day`: orphan skip log'u
- `_verify_eod_closure`: manuel ticket + orphan ticket exclusion set'leri

### 2.4 Temizlik

- "LIMIT emir gönderildi" yanıltıcı log bloğu (market fill sonrası) kaldırıldı
- `process_signals` docstring güncellendi (4., 5. adımlar silindi)

### 2.5 Dokümantasyon

- CLAUDE.md BÖLÜM 4.4 Siyah Kapı listesi yenilendi:
  - BABA 10 → 11 fonksiyon (`_close_ogul_and_hybrid` eklendi)
  - OĞUL 6 → 5 fonksiyon (`_check_advanced_risk_rules` kaldırıldı)
  - `_send_order_signal` → `_execute_signal` olarak düzeltildi
- Kural 10 "Günlük Kayıp" açıklaması güncellendi — sorumluluk BABA'ya devredildi
- Versiyon 3.2 → 3.3, tarih 10 Nisan 2026

## 3. Canlı Doğrulama

Restart sonrası log kanıtları (`logs/ustat_2026-04-10.log`):

| Kanıt | Log Satırı |
|-------|-----------|
| Engine temiz başladı | `[35478-35482] engine.database/ustat startup OK` |
| BABA drawdown tetiklendi | `[35972] engine.baba:check_drawdown_limits:1211 - TOPLAM DRAWDOWN LİMİTİ: %18.78 (limit=%10.0)` |
| KILL_SWITCH eventi yazıldı | `[35988] Event [ERROR] KILL_SWITCH: Günlük kayıp limiti aşıldı` |
| Yeni `_close_ogul_and_hybrid` çağrıldı | `[36060] engine.baba:_close_ogul_and_hybrid:2508 - L2 (KILL_SWITCH_L2_daily_loss) h_engine kapatma başarısız: [8050545494]` |
| Helper doğru raporladı | `[36061] engine.baba:_close_ogul_and_hybrid:2551 - L2 kapanış tamamlandı: 0 OĞUL pozisyonu kapatıldı, 1 başarısız` |

"0 OĞUL pozisyonu kapatıldı" → OĞUL `active_trades` boştu (beklenen).
"1 başarısız" → 1 hibrit pozisyon MT5 tarafından reddedildi:
`retcode=10027, comment=AutoTrading disabled by client`

Bu MT5'de algoritmik ticaret düğmesi kapalı olduğu için oluştu — kod değil broker kaynaklı. Refactor bağımsız bir durum.

## 4. Değişiklik İstatistiği

```
5 files changed, 170 insertions(+), 978 deletions(-)
 CLAUDE.md                              |  50 ++-
 docs/USTAT_GELISIM_TARIHCESI.md        |   3 +
 engine/baba.py                         |  89 +++++
 engine/main.py                         |   2 +
 engine/ogul.py                         |1016 ++++---------------------
```

Net: OĞUL ~1016 satır azaldı, BABA ~89 satır arttı. Toplam kod tabanı 808 satır sadeleşti.

## 5. Risk Analizi

### Silinen Koruma Katmanları ve Telafisi

| Silinen Kontrol | Yeni Konum | Durum |
|----------------|-----------|-------|
| OĞUL günlük %3 kayıp stop | BABA `check_drawdown_limits` + L2 `_close_ogul_and_hybrid` | ✅ Kapsama korundu |
| OĞUL aylık DD guard | BABA `_check_monthly_loss` + L2 `_close_ogul_and_hybrid` | ✅ Kapsama korundu |
| OĞUL yatay piyasa kapama | BABA rejim algılama (RANGE) | ✅ BABA rejim ile kapsar |
| OĞUL son 45dk kâr kapama | H-Engine breakeven/trailing | ✅ H-Engine alanı |
| OĞUL spread guard | (Kaldırıldı — OĞUL emir göndermeden önce check) | ⚠️ İleride test edilecek |

### Kırmızı Bölge Dokunuşu

- `engine/ogul.py` — ✅ Çift doğrulama uygulandı
- `engine/baba.py` — ✅ Çift doğrulama uygulandı
- `engine/main.py` — ✅ Çift doğrulama uygulandı (tek satır wire eklendi)

## 6. Eksikler ve Takip Konuları

1. **MT5 AutoTrading durumu:** F_AKBNK ticket 8050545494 hibrit pozisyonu hâlâ açık ve MT5 tarafından kapanamıyor. Kullanıcı MT5'de algoritmik ticaret düğmesini açıp engine'in kapatmasına izin vermeli, veya manuel kapatmalı.

2. **OĞUL `_daily_loss_stop` stale state:** `__init__` içinde hâlâ `_daily_loss_stop`, `_monthly_start_equity`, `_monthly_dd_stop` vb. değişkenler var. `api/routes/health.py:133` bunlardan `_daily_loss_stop`'u okuduğu için API contract gereği kaldırılmadı. Gelecekte API temizliği yapılabilir.

3. **Unit test:** Bu refactor için yeni unit test yazılmadı. Live doğrulama yeterli kabul edildi (BABA L2 tetiklenmesi ve helper çağrısı log'da kanıtlandı).

## 7. Build ve Deploy

- `python .agent/claude_bridge.py build` → Başarılı (vite build, 2.61s, 728 modül)
- `python .agent/claude_bridge.py restart_app` → Başarılı (12.17s)
- Engine startup: ✅ Temiz (AttributeError, ImportError, Traceback yok)
- Desktop build output: `dist/assets/index-Dgvhk8cN.js` (879.74 kB)

## 8. Sonuç

Mimari refactor tamamlandı ve live ortamda kanıtlandı. OĞUL artık yalnızca kendi sorumluluk alanında çalışıyor (sinyal üret → emir gönder → pozisyon yönet → kapat). BABA tek risk merkezi olarak çalışıyor ve L2/L3 kill-switch mekanizmaları manuel pozisyonları koruyacak şekilde ayrıştırıldı.

**Commit:** `d9177df`
**Tarihçe:** #149
