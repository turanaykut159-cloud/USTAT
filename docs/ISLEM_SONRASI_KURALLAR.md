# ÜSTAT — İşlem Sonrası Kurallar (ASLA UNUTMA)

**Kullanıcı talebi (2026-03-05):** Masaüstü kullanım; her işlemden sonra aşağıdakiler uygulanacak.

## 1. Masaüstü uygulaması güncellenecek

- ÜSTAT **masaüstü (Electron + React)** üzerinden kullanılıyor.
- Yapılan her değişiklikte, ilgili kısım **masaüstü uygulamasında** da güncellenmelidir.
- Masaüstü kodu: `desktop/` (React: `desktop/src/components/`, `desktop/src/services/`, `desktop/src/styles/`).
- API/engine değişikliği backend’i etkiler; UI/UX değişikliği `desktop/src` içinde yapılır. Her iki tarafta da gerekli güncellemeler yapılmalıdır.

## 2. Uygulama gelişim tarihçesi güncellenecek

- Her işlem/görev tamamlandıktan sonra **gelişim tarihçesi** dosyasına yeni madde eklenir.
- Dosya: **`docs/USTAT_v5_gelisim_tarihcesi.md`**
- Format: Mevcut maddelerdeki gibi (Tarih, Neden, Kök Neden, Değişiklikler tablosu, Eklenen/Çıkartılan).

---

**Özet:** Her işlemden sonra → (1) Masaüstü uygulaması güncellenecek, (2) Uygulama gelişim tarihçesi güncellenecek. **Bunları asla unutma.**
