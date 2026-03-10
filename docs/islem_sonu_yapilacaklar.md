# İşlem Sonu Yapılacaklar

"işlemi bitir" komutu verildiğinde aşağıdaki adımları SIRAYLA uygula:

---

## 1. Masaüstü Uygulamasını Güncelle
- Backend/engine'de kullanıcı-görünür veriyi etkileyen değişiklik varsa → API schema + route + React bileşenlerine yansıt
- Dev server başlat (`ustat-dev`) ve değişikliklerin doğru render edildiğini önizlemede kontrol et
- `npm run build` çalıştır → 0 hata olmalı

## 2. Gelişim Tarihçesi Yaz
- `docs/USTAT_v5_gelisim_tarihcesi.md` dosyasına yeni kayıt ekle
- Format: `## #XX — Başlık (tarih)` + tablo (tarih, neden) + değişiklikler tablosu + eklenen/çıkartılan listesi

## 3. Versiyon Kontrol
- Son versiyon etiketinden itibaren KÜMÜLATİF toplam değişikliği hesapla
- Komut: `git diff --stat <son_versiyon_commit>..HEAD` ile satır bazlı ölç
- `(eklenen + silinen satır) / toplam kod satırı` oranını bul
- Oran >= %10 ise versiyon yükselt ve AŞAĞIDAKİ TÜM DOSYALARI güncelle
- Oran < %10 ise "versiyon yükseltme GEREKMEDİ (%X.X)" notu düş

### Versiyon Güncelleme Noktaları (Tam Liste)

Versiyon yükseltildiğinde aşağıdaki TÜM dosyalar güncellenmelidir.

#### A. Fonksiyonel Sabitler (ZORUNLU — kod/UI'da kullanılır)
| # | Dosya | Satır | İçerik |
|---|-------|-------|--------|
| 1 | `engine/__init__.py` | 3 | `VERSION = "X.Y.0"` |
| 2 | `config/default.json` | 2 | `"version": "X.Y.0"` |
| 3 | `api/server.py` | 55 | `API_VERSION = "X.Y.0"` |
| 4 | `api/schemas.py` | 21 | `version: str = "X.Y.0"` |
| 5 | `desktop/package.json` | 3 | `"version": "X.Y.0"` |
| 6 | `desktop/src/components/Settings.jsx` | 22 | `const VERSION = 'X.Y';` |

#### B. Render Edilen UI Elemanları (ZORUNLU — kullanıcı görür)
| # | Dosya | Satır | İçerik |
|---|-------|-------|--------|
| 7 | `desktop/main.js` | 33 | `const APP_TITLE = 'ÜSTAT vX.Y';` |
| 8 | `desktop/main.js` | 46 | Splash HTML: `<span>vX.Y</span>` |
| 9 | `desktop/src/components/TopBar.jsx` | 98 | `<span className="version">vX.Y</span>` |
| 10 | `desktop/src/components/LockScreen.jsx` | 373 | `<span className="version">vX.Y</span>` |

#### C. Açıklama/Metadata (güncellenirse iyi olur)
| # | Dosya | Satır | İçerik |
|---|-------|-------|--------|
| 11 | `desktop/package.json` | 4 | `"description": "ÜSTAT vX.Y — VİOP..."` |
| 12 | `api/server.py` | 1 | Docstring: `ÜSTAT vX.Y API` |
| 13 | `start_ustat.py` | 2 | Docstring: `USTAT vX.Y - Baslatici` |
| 14 | `start_ustat.py` | 304 | Log: `USTAT vX.Y Baslatici` |
| 15 | `start_ustat.bat` | 2 | Yorum: `USTAT vX.Y` |
| 16 | `start_ustat.vbs` | 1 | Yorum: `USTAT vX.Y` |

#### D. Electron Process Dosyaları (JSDoc başlıkları)
| # | Dosya |
|---|-------|
| 17 | `desktop/main.js` |
| 18 | `desktop/preload.js` |
| 19 | `desktop/mt5Manager.js` |

#### E. React Bileşenleri (JSDoc başlıkları — `* ÜSTAT vX.Y`)
| # | Dosya |
|---|-------|
| 20 | `desktop/src/App.jsx` |
| 21 | `desktop/src/main.jsx` |
| 22 | `desktop/src/components/Dashboard.jsx` |
| 23 | `desktop/src/components/AutoTrading.jsx` |
| 24 | `desktop/src/components/ManualTrade.jsx` |
| 25 | `desktop/src/components/HybridTrade.jsx` |
| 26 | `desktop/src/components/OpenPositions.jsx` |
| 27 | `desktop/src/components/TradeHistory.jsx` |
| 28 | `desktop/src/components/RiskManagement.jsx` |
| 29 | `desktop/src/components/Performance.jsx` |
| 30 | `desktop/src/components/Settings.jsx` |
| 31 | `desktop/src/components/TopBar.jsx` |
| 32 | `desktop/src/components/SideNav.jsx` |
| 33 | `desktop/src/components/LockScreen.jsx` |
| 34 | `desktop/src/components/Monitor.jsx` |
| 35 | `desktop/src/components/ErrorBoundary.jsx` |
| 36 | `desktop/src/components/ConfirmModal.jsx` |

#### F. Servis/Utility Dosyaları (JSDoc başlıkları)
| # | Dosya |
|---|-------|
| 37 | `desktop/src/services/api.js` |
| 38 | `desktop/src/services/mt5Launcher.js` |
| 39 | `desktop/src/utils/formatters.js` |

#### G. Stil Dosyası (CSS yorum başlığı)
| # | Dosya |
|---|-------|
| 40 | `desktop/src/styles/theme.css` |

> **Not:** `package-lock.json` dokunma — `npm install` otomatik günceller.
> **Not:** `docs/` klasöründeki markdown dosyaları (gelişim tarihçesi vb.) versiyon geçiş kaydıyla güncellenir, tek tek aranmaz.

## 4. Git Commit
- Sadece bu session'da değiştirilen dosyaları stage'le (git add ile tek tek)
- Açıklayıcı commit mesajı yaz (feat/fix/refactor prefix)
- `git status` ile commit başarısını doğrula

## 5. PR (Opsiyonel)
- Kullanıcı açıkça isterse `gh pr create` ile pull request oluştur
- İstemezse bu adımı atla

## 6. Session Raporu Yaz
- `docs/YYYY-MM-DD_session_raporu_konu.md` dosyası oluştur
- İçerik: yapılan iş, değişiklik özeti, teknik detaylar, versiyon durumu, commit hash, build sonucu
