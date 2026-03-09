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
- Son versiyon etiketinden itibaren toplam değişikliği hesapla
- `(eklenen + silinen satır) / toplam kod satırı` oranını bul
- Oran >= %10 ise versiyon yükselt (v5.2 → v5.3 vb.) ve tüm referansları güncelle
- Oran < %10 ise "versiyon yükseltme GEREKMEDİ" notu düş

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
