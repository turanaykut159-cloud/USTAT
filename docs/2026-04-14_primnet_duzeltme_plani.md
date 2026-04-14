# PRIMNET Düzeltme Planı — 14 Nisan 2026 Akşam (Barış Zamanı)

**Kaynak:** `docs/2026-04-14_primnet_canli_gozlem_notlari.md` (20 anlık gözlem, 14 tespit)
**Başlama:** 18:15 sonrası (Savaş Zamanı bittiğinde)
**Toplam tahmini süre:** 6-8 saat
**Strateji:** Önce log analizi (kod yazmadan kök neden kesinleştir) → UI paketi → Motor bulguları → İşlemi Bitir

---

## 1. Önceliklendirme Matrisi

| Öncelik | Tespit | Kategori | Bölge | Sınıf | Finansal Risk | Fix Süresi |
|---|---|---|---|---|---|---|
| **P0** | T12 | cancel+place SL gap (~300ms korumasız) | 🔴 `mt5_bridge.py` | C4 | YÜKSEK | 2-3sa |
| **P0** | T8 | Tablo yanıltıcı kâr (canlı kanıt: +18 vs 595 TL) | 🟢 `PrimnetDetail.jsx` | C2 | KARAR YANILGISI | 1sa |
| **P1** | T16 | Trailing update atomicity/threshold | 🟡 `h_engine.py` (log ilk) | C2 | ORTA (kâr erozyonu) | 1-2sa |
| **P1** | T10.1 | SELL AÇIKLAMA ters yön | 🟢 `PrimnetDetail.jsx` | C1 | KARAR YANILGISI | 30dk |
| **P1** | T9 | Footer-MT5 sync gecikmesi (snapshot timing) | 🟢 frontend | C1 | Sadece UI | 30dk |
| **P2** | T1 | Tablo grid vs broker grid farkı | 🟢 `PrimnetDetail.jsx` | C1 | UI | 30dk |
| **P2** | T2 | "SL" etiketi yanıltıcı (trailing/profit-lock) | 🟢 frontend + şema | C1 | UI | 30dk |
| **P2** | T4 | "STOP SEV" kolonu ZARAR DURDUR satırlarında kafa karışıklığı | 🟢 frontend | C1 | UI | 20dk |
| **P2** | T5 | Tabloda -3.5 kademesi eksik | 🟢 frontend | C1 | UI | 15dk |
| **P2** | T6 | Güncel prim/K-Z ondalık tutarsızlığı | 🟢 frontend | C1 | UI | 15dk |
| **P3** | T3 | TP tick snap 2 tick sapma | 🟢 frontend (sadece gösterim) | C1 | Kozmetik | 20dk |
| **P3** | T11.10 | Manuel close tracker cleanup (log audit) | 🟢 `ogul.py` (sadece audit) | C0 | Sadece veri temizliği | 30dk |
| **P3** | T13 | Manuel kapanış slippage koruması (audit) | 🟡 `ogul.py` | C2 | Low | 1sa |
| **P3** | T15 | VİOP netting aynı sembol davranışı (audit) | Sadece log | C0 | Bilinmez | 30dk |
| **SKIP** | T7 | Paralel pozisyon yönetimi | Çalışıyor zaten ✓ | — | Yok | 0 |
| **SKIP** | T14 | Orphan pending cleanup | Broker otomatik yapıyor ✓ | — | Yok | 0 |

---

## 2. Faz 1: Log Analizi (Kod YAZMADAN, ~45 dk)

Motor tarafı tespitlerin kök nedenini kesinleştirmek için. Bu fazda sadece okuma, `ustat_agent.py` komutları kullanılır. Kod dokunulmaz.

### 2.1 T12 cancel+place pattern doğrulama

```bash
python .agent/claude_bridge.py search_all_logs "F_KONTR.*modify_position"
python .agent/claude_bridge.py search_all_logs "F_KONTR.*cancel.*stop_limit"
python .agent/claude_bridge.py search_all_logs "trailing_update.*order_send"
```

**Beklenen çıktı:** `modify_position` çağrısı VAR mı yoksa her trailing_update cancel+place zinciri mi? Zaman damgaları arasında SL-sız anın boyutu kaç ms?

### 2.2 T16 trailing update frequency

```bash
python .agent/claude_bridge.py search_all_logs "F_ASELS.*8050579260.*trailing"
python .agent/claude_bridge.py search_all_logs "F_ASELS.*8050579260.*peak"
```

**Beklenen:** Peak prim değişim aralıkları + trailing_update event zaman serisi. Her tick'te mi update ediliyor, yoksa threshold var mı?

### 2.3 T13 manuel kapanış slippage

```bash
python .agent/claude_bridge.py search_all_logs "F_KONTR.*MANUAL_REMOVE"
python .agent/claude_bridge.py search_all_logs "8050570106.*close_position"
```

### 2.4 T15 VİOP netting davranışı

```bash
python .agent/claude_bridge.py db_query "SELECT * FROM trades WHERE symbol='F_AKBNK0426' ORDER BY ticket DESC LIMIT 10"
python .agent/claude_bridge.py search_all_logs "F_AKBNK.*8050573843"
python .agent/claude_bridge.py search_all_logs "F_AKBNK.*8050580101"
```

**Beklenen:** İki F_AKBNK BUY ayrı ID olarak tracker'da mı yoksa netting ile birleşmiş mi?

### 2.5 Çıktı: Log Analiz Raporu

`docs/2026-04-14_log_analiz_raporu.md` yazılır. Her tespit için "doğrulandı / reddedildi / belirsiz" kararı + kanıt satır numaraları. Faz 2'ye bu raporla girilir.

---

## 3. Faz 2: Kod Okuma (YAZMADAN, ~30 dk)

Dokunulacak her dosya kök-kuyruğa kadar okunur. Fonksiyon imzaları, call graph çıkarılır.

| Dosya | Odak | Amaç |
|---|---|---|
| `engine/mt5_bridge.py` | `send_order`, `modify_position`, `close_position`, `_safe_call` | T12 cancel+place vs modify yolu tespit |
| `engine/h_engine.py` | trailing loop, peak tracker, stop update trigger | T16 threshold var mı? |
| `desktop/src/components/PrimnetDetail.jsx` | render mantığı, AÇIKLAMA formülleri, direction kontrolü | T1, T2, T4, T5, T6, T8, T10.1 |
| `api/schemas.py` + `api/routes/hybrid_trade.py` | PRIMNET payload şeması | T8 için lock amount doğru field var mı? |
| `engine/ogul.py` | `_execute_signal`, `_close_position`, manuel close handler | T13, T11.10 |
| `config/default.json` | trailing step, threshold değerleri | T16 sabit var mı? |

Çıktı: `tools/impact_map.py <dosya>` ile her hedef için çağrı zinciri. Etki raporu.

---

## 4. Faz 3: UI Düzeltme Paketi (Yeşil Bölge Paketi)

**Dokunulan dosya:** `desktop/src/components/PrimnetDetail.jsx` (tek dosya, tek build)
**Bölge:** Yeşil
**Sınıf:** C1-C2
**Süre:** ~3 saat
**Ön koşul:** Faz 2 kod okuması tamam
**Test:** Manuel (4 pozisyon: BUY+SELL × F_KONTR+F_ASELS) + screenshot karşılaştırma

### 4.1 Alt görevler (atomic, her biri ayrı commit)

#### 4.1.1 T10.1 — SELL AÇIKLAMA yön-asimetri
- `direction === 'BUY' ? 1 : -1` yön çarpanı ekle
- Karşılaştırma sembollerini direction'a göre ters çevir (`<` ↔ `>`)
- "Stop X (işaret) prim" gösterimini yön-aware yap
- Test: F_ASELS SELL tablosu açıkken her satırın AÇIKLAMA'sı mantıksal doğru olmalı

#### 4.1.2 T8 — Tablo güncel geri döndüğünde yanıltıcı kâr
- Peak-based kilitli kâr kolonu ekle: `locked_profit = (peak - giris) * sign * lot * multiplier`
- "KİLİTLİ KÂR" değeri artık peak'e göre hesaplanır, güncel prime göre değil
- Güncel prim peak'ten geriye düştüğünde kilitli kâr DÜŞMEZ (monotonic visual)
- Footer'da "Anlık gerçekleşmemiş K/Z: X" + "Kilitli kâr: Y" ayrı satır

#### 4.1.3 T1 — Tablo grid vs broker grid
- Faz 1 sonucuna göre: eğer broker continuous ise tablo da continuous olsun (0.1 prim adım, dense)
- Aktif satır highlight'ı güncel prime birebir snap

#### 4.1.4 T2 — "SL" etiketi yeniden adlandırma
- Footer'da: SL → "STOP SEVİYESİ" veya "TRAILING STOP" (yönüne göre)
- Tooltip ekle: "Giriş+1.5 prim: initial SL / Profit-lock: trailing stop"

#### 4.1.5 T4 — ZARAR DURDUR satırlarında STOP SEV. kolonu
- STOP ve ULAŞILMAZ satırlarında STOP SEV. hücresi boş render edilmeli (bilgisel anlamı yok)

#### 4.1.6 T5 — Eksik kademe
- Tablo 0.1 prim grid'e geçiyorsa zaten çözülür (T1 ile aynı fix)
- Eğer grid korunacaksa -3.5 satırı manuel eklenir

#### 4.1.7 T6 — Ondalık tutarsızlık
- Güncel prim ve K/Z tek ondalık gösterim: `toFixed(1)`
- Footer'da aynı hassasiyet

#### 4.1.8 T9 — Footer-MT5 snapshot timing
- Footer değerleri WebSocket stream'den (anlık) çekiliyor mu yoksa polling mi?
- Eğer polling (~1-3sn) ise WebSocket'e taşı veya gecikmeyi kullanıcıya göster ("devir: XX:XX:XX")

#### 4.1.9 T3 — TP tick snap gösterimi
- Broker'dan okunan TP değeri %1.018 çarpanı sonrası 2 tick sapmasını log'la
- Kozmetik: Footer'da gerçek broker TP gösteriliyor, sorun yok (sadece dokümante et)

### 4.2 Build + Test

```bash
python .agent/claude_bridge.py build           # npm run build
python .agent/claude_bridge.py restart_app     # Electron yeniden
```

Manuel test çekirdeği:
- F_ASELS SELL aç + peak hareket yaptır → AÇIKLAMA doğru yönlü mü?
- F_AKBNK BUY aç + peak hareket yaptır → Kilitli kâr monotonic mi?
- Güncel prim geri döndüğünde KİLİTLİ KÂR düşmüyor (T8)

---

## 5. Faz 4: Motor Düzeltmeleri (Kırmızı/Sarı Bölge)

**⚠ Bu faz kullanıcı onayı gerektirir — Anayasa Bölüm 9 C3/C4**

### 5.1 T12 — cancel+place → modify_position (🔴 Kırmızı Bölge, C4)

**Pre-flight checklist:**
- [ ] Faz 1 log analizi `modify_position` mı yoksa `cancel+place` mi kullanılıyor net gösterdi
- [ ] Anayasa Kural 4 (SL/TP zorunluluk) ihlal edilmiyor mu kontrol
- [ ] Siyah Kapı fonksiyonu değişiyor (`send_order` #17 veya `modify_position` #19) — kanıtlı bug fix
- [ ] Geri alma: tek commit, `git revert <hash>`
- [ ] Kullanıcı AÇIK ONAY verdi mi ("evet", "yap")

**Yaklaşım:**
- `engine/mt5_bridge.py` içinde trailing update yolu net ayrılır
- Eğer mevcut kod cancel+place kullanıyorsa → `modify_position` wrapper yazılır
- modify fail olursa → cancel+place fallback (ama sadece sonunda)
- Her iki adımın da logu tam atılır

**Test (zorunlu):**
- `tests/critical_flows/` altında yeni test: `test_trailing_uses_modify_not_cancel.py`
- Mock broker, trailing tetikle, `modify_position` çağrısı yapıldı mı assert et
- Olmazsa commit YASAK

### 5.2 T16 — Trailing update atomicity (🟡 Sarı Bölge, C2)

**Pre-flight:**
- [ ] Faz 1 log analizi threshold var mı yoksa yok mu kesin yanıt verdi
- [ ] Eğer threshold yok ise → Anlık #16 düzeltmesi doğru, sorun yok, düzeltme GEREKMEZ, sadece dokümante et
- [ ] Eğer threshold var ise → `h_engine.py` trailing trigger kodu okunur, davranış sabitlenir

**Muhtemel yol:**
- `engine/h_engine.py` trailing loop'ta peak güncellemesi her tick yapılmalı (zaten yapılıyor olabilir)
- Stop `modify_position` çağrısı her peak değişiminde atılmalı (eğer atılmıyorsa eksik)
- Config'e `trailing_update_min_delta` parametresi eklenirse (örn. 0.1 prim) threshold kontrollü olur — ama Anayasa "1.5 prim offset" ile çelişmemeli

### 5.3 T13 — Manuel kapanış slippage audit (🟡 Sarı Bölge, C0-C2)

**Yaklaşım:**
- `engine/ogul.py` manuel close handler okunur
- MT5 kısmi fill durumunda ne yapıyor kontrol edilir
- Eğer koruma eksik ise slippage limit eklenir (config'den `max_slippage_atr_mult`)
- Aksi halde sadece dokümante et

### 5.4 T11.10 + T15 — Tracker + Netting audit (sadece audit, kod yok)

- `ogul.py` trade tracker çıktısını incele
- Aynı sembol aynı yön iki pozisyon durumunda tracker davranışını dokümante et
- Fix gerekmezse T7 + T14 gibi SKIP kategorisine al

---

## 6. Faz 5: İşlemi Bitir (Bölüm 7 Protokolü)

Her commit için:

### 6.1 Kritik akış testleri (zorunlu)
```bash
python -m pytest tests/critical_flows -q --tb=short
```
**N passed olmalı. Başarısız test VARSA commit YASAK.**

### 6.2 Build
```bash
python .agent/claude_bridge.py build   # 0 hata
```

### 6.3 Restart + Doğrulama
```bash
python .agent/claude_bridge.py restart_app
```
Manuel screenshot ile "düzeltildi" kanıtı.

### 6.4 Git commit (atomic, tespit başına ayrı)
```
fix(primnet-ui): SELL AÇIKLAMA yön-asimetri düzeltildi (T10.1)
fix(primnet-ui): tablo kilitli kâr monotonic (T8 canlı kanıtına göre)
fix(mt5-bridge): trailing modify_position kullan, cancel+place kaldırıldı (T12)
...
```

### 6.5 Gelişim Tarihçesi
`docs/USTAT_GELISIM_TARIHCESI.md` — Keep a Changelog formatı.

### 6.6 Versiyon kontrol
Oran hesabı Bölüm 7 ADIM 3. Eğer ≥%10 → v5.9 → v6.0 artır (15 noktada güncelleme).

### 6.7 Oturum raporu
`docs/2026-04-14_session_raporu_primnet_duzeltme.md`

---

## 7. Risk ve Geri Alma

### 7.1 En riskli iş: T12
- Kırmızı Bölge + Siyah Kapı fonksiyon değişikliği
- `modify_position` fail olursa pozisyon korumasız kalma riski VAR
- Mitigation: modify başarısız → mevcut cancel+place fallback'e düş, her iki yol da log atılır
- Geri alma: `git revert <hash>` + restart_app

### 7.2 UI paketi
- Yeşil Bölge, tek dosya
- Fail scenario: Render hatası → frontend crash (ErrorBoundary yakalar)
- Geri alma: `git revert <hash>` + `npm run build` + `restart_app`

### 7.3 Faz 1 log analizi
- Sadece okuma, risk yok
- `ustat_agent.py` komutları read-only

---

## 8. Zamanlama

| Saat | Faz | Not |
|---|---|---|
| 18:15 | Piyasa kapanış | Barış Zamanı başlar |
| 18:15-19:00 | Faz 1: Log analizi | Kod yazılmaz |
| 19:00-19:30 | Faz 2: Kod okuma | Kod yazılmaz |
| 19:30-22:30 | Faz 3: UI paketi | 8 atomic commit |
| 22:30-01:30 | Faz 4: Motor | T12 kullanıcı onayı ile |
| 01:30-02:30 | Faz 5: Test + commit + belge | İşlemi Bitir |

**Yarın sabaha hazır:** Tüm fixler merged, versiyon güncellenmiş (gerekirse), yeni gün piyasa açılışı temiz başlar.

---

## 9. Kullanıcı Onay Noktaları

Bu plan aşağıdaki onay noktalarında kullanıcıya soracak:

1. **Plan onayı (şimdi):** Bu plan doğru mu, faz sırası uygun mu?
2. **Faz 1 sonrası:** Log analiz raporu çıktısı + güncellenmiş öncelik listesi → devam et mi?
3. **Faz 4 öncesi:** T12 için Kırmızı Bölge dokunuşu → AÇIK ONAY gerekli
4. **Versiyon artışı:** %10 eşik aşıldıysa v6.0'a çıkıyoruz, onay gerekli
5. **Son doğrulama:** İşlemi Bitir sonrası kullanıcı ekran görüntüsü ile teyit

---

## 10. Bu planda OLMAYAN şeyler (kapsam dışı)

- Yeni özellik geliştirme
- Performans optimizasyonu
- Tema/stil değişikliği
- Backend API yeniden yapılandırma
- Test altyapısı genişletme (sadece kritik akış için yeni test)
- Anayasa'ya dokunma
- Dört Motor mimarisinde değişiklik

Bu plan **sadece PRIMNET tespit düzeltmesi** kapsamındadır.
