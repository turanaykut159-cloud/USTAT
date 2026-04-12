# Session Raporu — Derin Denetim + Faz A/B Bulgu Kapatma

**Tarih:** 2026-04-11
**Konu:** Sifirdan kapsamli teknik denetim + P0/P1 bulgu kapatma
**Commit A:** f839d4e (Faz A — 5 P0)
**Commit B:** f425063 (Faz B — 14 P1)
**Build:** npm run build 0 hata
**Test:** 71 passed, 0 failed (critical_flows), 10768 test collected (0 error)

---

## 1. Yapilan Is

### Faz 0 — Derin Denetim (rapor)
- 5 paralel uzman agent ile tum kod tabani incelendi (~40K satir)
- 78 bulgu tespit edildi (6 P0, 18 P1, 34 P2, 20 P3)
- Baz raporun (2026-04-11_kapsamli_teknik_denetim_raporu.md) 7/8 iddiasi dogrulandi
- Baz raporun P1-4.3 (WS envelope bug) iddiasi YANLIS cikti — event_bus.py zaten duzeltilmis
- Rapor: `docs/2026-04-11_derin_kapsamli_denetim_raporu.md` (900 satir)

### Faz A — P0 Bulgu Kapatma (5/6)
| # | Bulgu | Dosya | Durum |
|---|---|---|---|
| A1 | pytest.ini testpaths bozuk | pytest.ini, test_static_contracts.py | KAPATILDI |
| A2 | /status.last_cycle olu alan | engine/main.py | KAPATILDI |
| A3 | unread_count limitli | database.py, notifications.py | KAPATILDI |
| A4 | restartMT5 hayalet buton | Settings.jsx | KAPATILDI (disabled) |
| A5 | fail_names NameError | engine/main.py | KAPATILDI |
| A6 | SL/TP korumasiz pozisyon | — | ZATEN DUZELTILMIS (ogul.py:1830-1894) |

### Faz B — P1 Bulgu Kapatma (14/18)
| Kol | Konu | Bulgu sayisi | Durum |
|---|---|---|---|
| 1 | Versiyon drift | B1 (start_ustat v6.0), B2 (App.jsx v6.0) | 2 KAPATILDI |
| 2 | API private sizinti | B5 (getter'lar), B6 (9 route migration), B7 (health), B8 (status.phase) | 6 KAPATILDI |
| 3 | Frontend | B11 (notif prefs getter), B13 (ErrorBoundary), B15 (log seviyesi) | 3 KAPATILDI |
| 4 | Belge | B16 (WATCHDOG sabitleri) | 1 KAPATILDI |
| — | Zaten OK | B9 (killswitch auth — localhost), B10 (manual risk — ManuelMotor icinde) | 2 ACCEPTED |
| — | Ertelenen | B14 (sifre arg), B17 (news timeout) | 2 ERTELENDI |

## 2. Degisiklik Listesi (27 dosya)

### Faz A (7 dosya + rapor)
- `pytest.ini` — testpaths + norecursedirs
- `tests/critical_flows/test_static_contracts.py` — .claude/ exclusion
- `engine/main.py` — _last_cycle_time + fail_names fix
- `engine/database.py` — get_unread_notification_count()
- `api/routes/notifications.py` — global unread count
- `desktop/src/components/Settings.jsx` — restartMT5 disabled
- `docs/2026-04-11_derin_kapsamli_denetim_raporu.md` — yeni

### Faz B (20 dosya)
- `CLAUDE.md` — WATCHDOG sabitleri duzeltme
- `start_ustat.py` — APP_TITLE/splash/log v5.9→v6.0
- `engine/baba.py` — 5 public property
- `engine/h_engine.py` — 6 public property
- `engine/main.py` — is_running property
- `engine/ogul.py` — get_voting_detail (public rename)
- `engine/mt5_bridge.py` — SL/TP log WARNING→ERROR
- `api/deps.py` — is_running getter
- `api/routes/{status,killswitch,risk,settings,live,hybrid_trade,ogul_activity,health}.py` — private→public migration
- `desktop/src/App.jsx` — v6.0 JSDoc + kok ErrorBoundary
- `desktop/src/components/Settings.jsx` — backend notif prefs fetch
- `desktop/src/services/api.js` — getNotificationPrefs()
- `tests/critical_flows/test_static_contracts.py` — primnet test update

## 3. Versiyon Durumu
- Kod: v6.0.0 (degismedi)
- Degisiklik orani: %1.8 (< %10, versiyon artisi gerekmedi)

## 4. Kalan (Faz C/D)
- P2: 34 bulgu — motor alt modul ayrimi, schema ayrimi, test tasarimi
- P3: 20 bulgu — kozmetik, edge case
- Ertelenen P1: B14 (sifre process arg), B17 (news_bridge timeout)
