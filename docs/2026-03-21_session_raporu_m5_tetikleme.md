# Oturum Raporu — M5 Sinyal Tetikleme Geçişi

| Alan | Detay |
|------|-------|
| **Tarih** | 2026-03-21 |
| **Versiyon** | 5.7.0 (patch) |
| **Commit** | `83f405a` |
| **Build** | `npm run build` — 0 HATA, 718 modül, 7.93s |

## Yapılan İş

Sinyal tetikleme mekanizması M15 mum kapanışından M5 mum kapanışına geçirildi. SE2 motoru artık M5 verisiyle beslenir.

## Neden

- M15: Sinyal her 15 dakikada bir üretilir → VİOP'ta çok geç
- M5: Sinyal her 5 dakikada bir üretilir → 3x daha hızlı tepki
- SE2'nin 3/9 kaynağı (momentum, volume climax, extreme reversion) M5'te daha güvenilir

## Mimari

```
ÖNCEKİ:  H1(filtre) → M15(tetikleme+sinyal) → M5(giriş zamanlaması)
ŞİMDİ:   H1(filtre) → M15(confluence+filtre) → M5(tetikleme+sinyal)
```

## Değişiklikler

| Dosya | Değişiklik |
|-------|-----------|
| `engine/ogul.py` ⛔ | _is_new_m5_candle() + M5 SE2 beslemesi + MIN_BARS_M5 |
| `engine/ustat.py` ⛔ | Log mesajı güncelleme |
| `docs/USTAT_v5_gelisim_tarihcesi.md` | #49 girdisi |
