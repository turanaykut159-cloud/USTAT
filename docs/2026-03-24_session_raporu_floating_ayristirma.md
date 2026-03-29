# Oturum Raporu — Motor Bazlı Floating Ayrıştırma (CEO Option C)

**Tarih:** 2026-03-24
**Konu:** BABA floating kontrolünün motor bazlı ayrıştırılması
**Commit:** `85912a9`
**Versiyon:** v5.7.0 → v5.7.1

---

## Problem

BABA'nın `_check_floating_loss()` fonksiyonu tüm hesaptaki floating PnL'yi tek havuzda değerlendiriyordu. Hibrit motorun -150 TRY floating kaybı %1.5 eşiğini aşıyor ve OĞUL'un yeni işlem açması engelleniyordu — OĞUL'un kendi floating'i 0 TRY olmasına rağmen.

## Çözüm Mimarisi (İki Katmanlı)

### Katman 1 — Motor Bazlı Risk (%1.5)
- `data_pipeline.update_risk_snapshot()` floating PnL'yi ticket bazlı üç motora ayırır
- BABA sadece `ogul_floating_pnl`'ye bakarak %1.5 kontrolü yapar
- Hibrit/Manuel zararları OĞUL'u bloke etmez

### Katman 2 — Master Koruma (%5)
- Yeni `_check_master_floating()` metodu tüm motorların toplam floating'ini kontrol eder
- %5 eşiği aşılırsa Kill-Switch L2 tetiklenir — tüm motorlar durur
- Kontrolsüz büyümeye karşı son savunma hattı

## Veri Akışı

```
main.py._update_data()
  ├─ h_engine.hybrid_positions.keys() → hybrid_tickets
  ├─ manuel_motor.active_trades → manuel_tickets
  ├─ pipeline.set_engine_tickets(hybrid, manuel)
  └─ pipeline.run_cycle()
       └─ update_risk_snapshot()
            ├─ floating_pnl (toplam — geriye dönük uyumlu)
            ├─ ogul_floating_pnl (ticket dışı pozisyonlar)
            ├─ hybrid_floating_pnl
            └─ manuel_floating_pnl

baba.check_risk_limits()
  ├─ #8: _check_floating_loss() → ogul_floating_pnl < %1.5
  └─ #8.5: _check_master_floating() → floating_pnl < %5
```

## Değişen Dosyalar

| Dosya | Değişiklik | Satır |
|-------|-----------|-------|
| `engine/data_pipeline.py` | `set_engine_tickets()` + motor bazlı floating | +45 |
| `engine/baba.py` | OĞUL bazlı kontrol + master koruma | +80 |
| `engine/main.py` | Ticket aktarım entegrasyonu | +17 |
| `engine/__init__.py` | v5.7.0 → v5.7.1 | +1 |
| `docs/USTAT_v5_gelisim_tarihcesi.md` | #62 girişi | +30 |

## Geriye Dönük Uyumluluk

Eski snapshot'larda `ogul_floating_pnl` anahtarı yoksa, `_check_floating_loss()` toplam `floating_pnl`'ye fallback yapar. İlk yeni snapshot'tan itibaren otomatik geçiş.

## Build Durumu

Syntax check: ✅ OK (data_pipeline.py, baba.py, main.py)

## Sınıflandırma

C3 — Kritik fonksiyon düzeltmesi (mimari değişiklik)
