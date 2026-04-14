# A4 — Monitor modStatus Gerçek Sinyallere Bağlandı

**Tarih:** 2026-04-11 (Cumartesi, Barış Zamanı)
**Commit:** `cac5105`
**Kaynak bulgu:** `docs/2026-04-11_widget_denetimi.md` Bölüm 11.4 + Bölüm 17 A4 (B9)
**Değişiklik sınıfı:** C1 — Yeşil Bölge (`desktop/src/components/Monitor.jsx`)
**Changelog girişi:** #168

---

## 1. Özet

Monitor sayfasındaki 5 motor rozetinin (BABA / OĞUL / H-Engine / ÜSTAT / MANUEL)
durum hesabı, gerçek çalışma zamanı sinyallerine bağlandı. En kritik bulgu
`modStatus.manuel = 'ok'` sabit hardcode'uydu: manuel motorda hata olsa bile
rozet asla sarı/kırmızı olmuyordu. Yan bulgu olarak BABA/OĞUL/H-Engine/ÜSTAT
rozetleri `engine_running`, `errorCounts` ve `killLevel >= 2` sinyallerini
kullanmıyordu — motor ölü olsa bile yeşil görünebiliyordu, Anayasa 4.5 Kural
#10'da L2+ durumunda OĞUL/H-Engine'in durduğu halde rozetler hâlâ "AKTİF"
diyebiliyordu.

A4 tüm bu eksiklikleri tek atomik değişiklikte düzeltti: `modStatus` artık
conditional expression ile hesaplanıyor, `errorCounts` artık ölü değişken
değil, `engine_running=false` → tüm rozetler `err`, `killLevel >= 2` →
OĞUL/H-Engine `err`.

## 2. Kök Neden Analizi

### 2.1 Eski kod (Monitor.jsx, satır 233-240)

```jsx
const modStatus = {
  baba: killLevel >= 3 ? 'err' : killLevel > 0 ? 'warn' : 'ok',
  ustat: sysInfo?.cache_stale ? 'warn' : 'ok',
  ogul: layers?.ogul?.daily_loss_stop ? 'err'
        : (orders?.reject_count ?? 0) > 0 || (orders?.timeout_count ?? 0) > 0
        ? 'warn' : 'ok',
  hengine: (layers?.h_engine?.active_hybrid_count ?? 0) > 0 ? 'warn' : 'ok',
  manuel: 'ok',
};
```

### 2.2 Tespit edilen altı problem

1. **MANUEL hardcode** — `manuel: 'ok'` her zaman yeşil. `errorCounts.manuel`
   cycle başında hesaplanıyor ama modStatus tarafından okunmuyor.
2. **engine_running kapısı YOK** — Engine ölü olsa bile `killLevel=0`,
   `cache_stale=false`, `active_hybrid_count=0` → tüm rozetler "ok" yeşil
   görünürdü. Kullanıcı "motor çalışıyor mu?" sorusuna yanlış cevap alırdı.
3. **errorCounts ölü değişken** — 8 satır üstte `(health?.recent_events ||
   []).forEach` ile hesaplanan `errorCounts` sözlüğü sadece detail açılır
   panelinde "HATA: N" olarak gösteriliyordu; modStatus tarafından hiçbir
   rozetin renk hesabında kullanılmıyordu.
4. **OĞUL L2+ kontrolü YOK** — Anayasa 4.5 Kural #10: "BABA günlük/aylık
   kayıp tetiğinde L2 → `_close_ogul_and_hybrid()` → SADECE OĞUL + Hybrid
   kapanır". L2 aktifken OĞUL motoru durmuş oluyor ama Monitor rozeti sadece
   `daily_loss_stop` legacy bayrağına bakıyordu. Yeni merkezileştirme sonrası
   bu bayrak senkron olmayabilir.
5. **H-Engine L2+ kontrolü YOK** — Aynı şekilde L2'de H-Engine durur, rozet
   bunu yansıtmıyordu.
6. **BABA errorCounts'u okumaz** — BABA chip yalnız `killLevel`'e bakıyordu,
   `errorCounts.baba > 0` (BABA log'unda hata) durumunda sarı yapmıyordu.

### 2.3 Audit raporu alıntıları

- Bölüm 11.4.5 MANUEL Kolonu: "🐛 `modStatus.manuel = 'ok'` SABİT HARDCODE
  — manuel motor hatası hiç warn/err göstermez. 🧱"
- Bölüm 11.10: "`modStatus.manuel = 'ok'` sabit — manuel modülde hata hiç
  yansımaz."
- Bölüm 16.2 B9: "KRİTİK · `modStatus.manuel = 'ok'` **sabit hardcode**;
  BABA/ÜSTAT rozetleri sadece `engine_running`'e bağlı → L2 kill-switch
  aktifken bile 'BABA AKTİF' yeşil"

## 3. Atomik Değişiklik

### 3.1 `desktop/src/components/Monitor.jsx` (satır 233-271)

Obje literal'i conditional expression'a çevrildi:

```jsx
const modStatus = !engineRunning
  ? { baba: 'err', ustat: 'err', ogul: 'err', hengine: 'err', manuel: 'err' }
  : {
      baba:
        killLevel >= 3 ? 'err' :
        killLevel > 0 ? 'warn' :
        errorCounts.baba > 0 ? 'warn' : 'ok',
      ustat:
        sysInfo?.cache_stale ? 'warn' :
        errorCounts.ustat > 0 ? 'warn' : 'ok',
      ogul:
        killLevel >= 2 ? 'err' :
        layers?.ogul?.daily_loss_stop ? 'err' :
        errorCounts.ogul > 0 ||
        (orders?.reject_count ?? 0) > 0 ||
        (orders?.timeout_count ?? 0) > 0 ? 'warn' : 'ok',
      hengine:
        killLevel >= 2 ? 'err' :
        errorCounts.hengine > 0 ? 'warn' :
        (layers?.h_engine?.active_hybrid_count ?? 0) > 0 ? 'warn' : 'ok',
      manuel:
        errorCounts.manuel > 0 ? 'warn' : 'ok',
    };
```

**Yeni semantik:**

| Modül | err koşulu | warn koşulu | ok |
|-------|-----------|-------------|-----|
| **BABA** | `!engineRunning` · `killLevel≥3` | `killLevel>0` · `errorCounts.baba>0` | aksi |
| **OĞUL** | `!engineRunning` · `killLevel≥2` · `daily_loss_stop` | `errorCounts.ogul>0` · reject · timeout | aksi |
| **H-Engine** | `!engineRunning` · `killLevel≥2` | `errorCounts.hengine>0` · active_hybrid>0 | aksi |
| **ÜSTAT** | `!engineRunning` | `cache_stale` · `errorCounts.ustat>0` | aksi |
| **MANUEL** | `!engineRunning` | `errorCounts.manuel>0` | aksi |

**Önemli karar:** BABA rozeti `killLevel >= 2` (L2) için `warn` kalır,
`err` değil. Audit 11.4.2: "L2=warn Doğru" — BABA risk motoru olarak L2'de
haberdar ve çalışıyor. OĞUL/H-Engine durduğu için onlar `err`.

### 3.2 `tests/critical_flows/test_static_contracts.py` (Flow 4e)

Yeni statik sözleşme testi `test_monitor_modstatus_not_hardcoded`:

- Monitor.jsx'i text olarak okur, regex ile `modStatus` bloğunu izole eder.
- 4 assertion:
  1. `manuel: 'ok'` / `manuel: "ok"` literal'leri blokta YOK.
  2. `engineRunning` referansı blokta VAR (kapı kontrolü).
  3. `errorCounts` referansı blokta VAR (ölü değişken değil).
  4. `killLevel >= 2` ifadesi blokta VAR (L2+ OĞUL/H-Engine err kapısı).

Regex `const modStatus\s*=(.*?)\n\s*//` ile yalnız blok içini test eder,
dosyanın geri kalanındaki yorum satırları testi bozmaz.

### 3.3 `docs/USTAT_GELISIM_TARIHCESI.md`

`## [6.0.0]` → `### Fixed` bölümüne #168 girişi eklendi. Detaylı kök neden
analizi, 6 problem listesi, yeni semantik tablosu, impact analysis ve
doğrulama sonuçları dahil.

## 4. Dokunulmayanlar (Bilinçli)

- **`errorCounts` substring parse kırılganlığı** — Audit 11.4.2'de bir B
  bulgusu olarak işaretli. `(ev.message || '').toLowerCase().includes('baba')`
  substring araması yanlış pozitif üretebilir ("baba" kelimesi alakasız
  bir mesajda geçerse). Ayrı bir A-maddesi olarak bırakıldı; bu fix'te
  yalnız modStatus referans zincirini düzelttik.
- **`/api/manuel-motor/health` endpoint'i YOK** — Gerçek manuel motor health
  check'i için backend endpoint bulunmuyor. Şu anki çözüm "en azından hata
  event'i varsa rozet warn" — eski tam hardcode'tan net bir iyileşme, tam
  çözüm değil. Gerçek health endpoint'i backend A-maddesi olarak eklenebilir.
- **BABA chip L2=warn** — Audit "L2=warn Doğru" dedi, korundu. BABA risk
  motoru L2'de hâlâ çalışıyor ve karar veriyor, durmuyor.
- **POLL_MS 10000 vs "3sn" yorum çelişkisi** — Audit'te dokümantasyon
  bulgusu olarak işaretli, ayrı maddede ele alınacak.

## 5. Doğrulama

| Kontrol | Sonuç |
|---------|-------|
| critical_flows | **38 passed, 3 warnings in 3.14s** (37 baseline + 1 yeni Flow 4e) |
| Windows build | **728 modules, 2.63s, 0 hata** (`ustat-desktop@6.0.0`, Vite 6.4.1) |
| Pre-commit hook | Commit geçti (hook testleri tekrar çalıştırdı) |
| Git commit | `cac5105`, 3 files changed, +81/-8 |

## 6. Etki Analizi

- **Dosya sayısı:** 1 JSX + 1 test + 1 changelog = 3 dosya
- **Zone dokunuşu:** Yeşil Bölge yalnız (Monitor.jsx listelerde yok)
- **Siyah Kapı dokunusu:** YOK (Monitor.jsx bir React bileşeni, siyah kapı
  fonksiyonu değil)
- **Çağıran zinciri:** Tek — `modStatus.{baba,ustat,ogul,hengine,manuel}`
  değeri `<ModBox status={...}>` prop'una geçer, ModBox onu `<Badge>`'a
  iletir, Badge renk map'ine bakar (`ok`/`warn`/`err`). Başka tüketici yok.
- **Tüketici zinciri:** Tek — Badge bileşeni (satır 43-55).
- **Backend değişikliği:** GEREKSİZ — `/api/health.recent_events`,
  `/api/status.engine_running`, `/api/risk.kill_switch_level` alanları
  zaten mevcut ve kullanılıyordu.
- **Geriye dönük uyumluluk:** %100 — ok/warn/err değer kümesi değişmedi,
  yalnız hesaplama mantığı.

## 7. Deploy Durumu

- Piyasa kapalı (Cumartesi, Barış Zamanı) — deploy güvenli.
- Build üretildi (`desktop/dist/`), Electron restart gerekli (`restart_app`).
- A1 (`baba.py` L2→L3 escalation) + A2 (trade SIGN_MISMATCH) + A3 (notification
  prefs) + A4 (monitor modStatus) dörtlüsü aynı anda canlıya alınabilir.
  A1 restart sırasında mevcut açık pozisyon hard drawdown ≥%15 kontrolü
  ile L3 tetiklenerek kapatılacak (beklenen davranış).

## 8. Follow-Up Maddeleri

- `errorCounts` substring parse kırılganlığı (audit B bulgusu, ayrı madde)
- Backend `/api/manuel-motor/health` endpoint'i (yeni madde)
- Monitor cycle 50ms kırmızı eşik tutarsızlığı (audit 11.10, ayrı A-madde)
- POLL_MS dokümantasyon çelişkisi (audit 11.10)
- `errorCounts.ogul` içinde Unicode 'oğul' araması (toLowerCase sonrası
  Unicode davranışı garanti değil — audit 11.4.2)

## 9. Referanslar

- **Audit raporu:** `docs/2026-04-11_widget_denetimi.md` Bölüm 11.4,
  Bölüm 16.2 B9, Bölüm 17 A4
- **Anayasa:** Kural #10 (L2 → OĞUL+Hybrid kapanır), Kural #3 (kill-switch
  monotonluk yukarı yönde zorunlu)
- **Commit:** `cac5105` — fix(monitor): modStatus gercek sinyallere baglandi
  (Widget Denetimi B9)
- **Changelog:** #168 (`docs/USTAT_GELISIM_TARIHCESI.md`)
