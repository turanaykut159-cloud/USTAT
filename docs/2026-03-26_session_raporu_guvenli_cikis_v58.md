# Oturum Raporu — 26 Mart 2026

## Güvenli Çıkış Düzeltmesi & v5.8.0 Versiyon Artırma

---

### Yapılan İş Özeti

1. **Güvenli çıkış sorunu çözüldü**: Kullanıcı "Güvenli Çıkış" yaptığında uygulama artık otomatik yeniden başlamıyor. Üç watchdog katmanı (start_ustat.py, ustat_agent.py, desktop/main.js) shutdown.signal dosyasını tutarlı şekilde işliyor.

2. **Watchdog singleton mekanizması eklendi**: Timestamp-based PID kilidi ile birden fazla watchdog çalışması engellendi. İlk deneme (OpenProcess) crash recovery'yi bozdu → timestamp-based yaklaşıma geçildi.

3. **Crash recovery doğrulandı**: Force-kill sonrası watchdog 15 saniyede restart #1'i tamamladı.

4. **v5.7 → v5.8 versiyon artırma**: %39.6 değişiklik oranı (>= %10 eşik) nedeniyle versiyon artırıldı. 12 dosya güncellendi.

5. **Claude hatasız çalışma araştırması**: 10 ajan görevlendirildi. 5 katmanlı savunma sistemi önerildi (CLAUDE.md optimizasyonu, Hooks, Skills, Git Pre-Commit, Doğrulama Ajanı).

---

### Değişiklik Listesi (Dosya Bazında)

| Dosya | Değişiklik |
|-------|-----------|
| `start_ustat.py` | shutdown.signal silme kaldırıldı, singleton watchdog (timestamp-based), koşullu signal temizlik, restart öncesi signal kontrolü, PID cleanup |
| `ustat_agent.py` | `_check_and_heal()` ve `_try_restart_ustat()` başında shutdown.signal kontrolü |
| `engine/__init__.py` | VERSION: 5.7.1 → 5.8.0 |
| `config/default.json` | version: 5.7.0 → 5.8.0 |
| `api/server.py` | API_VERSION: 5.7.0 → 5.8.0, docstring v5.8 |
| `api/schemas.py` | StatusResponse version: 5.7.0 → 5.8.0 |
| `desktop/package.json` | version: 5.7.0 → 5.8.0, description v5.8 |
| `desktop/main.js` | APP_TITLE v5.8, splash HTML v5.8, docstring v5.8 |
| `desktop/preload.js` | JSDoc v5.8 |
| `desktop/src/components/TopBar.jsx` | Logo + JSDoc v5.8 |
| `desktop/src/components/LockScreen.jsx` | Ekran + JSDoc v5.8 |
| `desktop/src/components/Settings.jsx` | JSDoc v5.8 |
| `desktop/src/services/mt5Launcher.js` | JSDoc v5.8 |
| `create_shortcut.ps1` | Kısayol adı + Description v5.8 |
| `update_shortcut.ps1` | $newName + Description v5.8 |
| `docs/USTAT_v5_gelisim_tarihcesi.md` | #71 girişi + başlık v5.8 |

---

### Teknik Detaylar ve Kanıtlar

**Kök Neden 1 — Signal silme yarışı:**
- `check_shutdown_signal()` satır 333-334: `os.remove()` kaldırıldı
- Kanıt: İki watchdog çalışırken ilki signal'i siliyor → ikincisi göremiyordu

**Kök Neden 2 — Singleton PID kilidi regresyonu:**
- `OpenProcess()` ile PID kontrolü: eski process child'lar nedeniyle hayatta kaldı
- Kanıt: startup.log "Baska bir watchdog zaten calisiyor (PID 14132)" ama PID 14132 watchdog loop'u çoktan durmuştu
- Çözüm: Timestamp-based heartbeat (her 15sn güncelleme, >60sn stale)

**Kök Neden 3 — Ajan bağımsız restart:**
- `_check_and_heal()` ve `_try_restart_ustat()` shutdown.signal kontrolü yoktu
- Çözüm: Her iki metoda signal kontrolü eklendi

**Test sonuçları (4/4 geçer):**
1. Crash recovery: API force-kill → restart #1 ✅
2. Güvenli çıkış: signal + stop → restart yok ✅
3. Taze signal engeli: 87sn signal → main() "iptal" ✅
4. Ertesi gün başlatma: 305sn signal → temizle + başlat ✅

---

### Versiyon Durumu

- **Artırıldı**: v5.7 → v5.8
- **Neden**: v5.7.0 commit'inden (91e56b2) bu yana %39.6 değişiklik oranı (eşik: %10)
- **Hesaplama**: (18,284 eklenen + 1,859 silinen) / 50,802 toplam kod satırı = %39.6

---

### Commit

- **Hash**: `419373e`
- **Mesaj**: `feat: v5.8.0 — guvenli cikis fix + watchdog singleton + versiyon artirma (#71)`
- **Dosya sayısı**: 16 dosya, 1620 ekleme, 226 silme

---

### Build Sonucu

UI değişikliği sadece versiyon numarası güncellemesi (JSDoc + string). Fonksiyonel değişiklik yok. Build çalıştırılması kullanıcı tarafından yapılacak (kısayol güncelleme ile birlikte):

```powershell
cd C:\Users\pc\Desktop\USTAT\desktop
npm run build
PowerShell -ExecutionPolicy Bypass -File C:\Users\pc\Desktop\USTAT\update_shortcut.ps1
```

---

### Ek Çıktılar

- `RAPORLAR/Claude_Hatasiz_Calisma_Rehberi.docx` — 10 ajanlık araştırma raporu (5 katmanlı savunma sistemi önerisi)
