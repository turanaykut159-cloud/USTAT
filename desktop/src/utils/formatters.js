/**
 * ÜSTAT v6.0 — Ortak formatlama yardımcıları.
 *
 * Tüm bileşenlerde tekrarlanan formatMoney, formatPrice, pnlClass, elapsed
 * fonksiyonları burada merkezileştirilmiştir.
 *
 * Widget Denetimi H13 — Win rate breakeven eşiği:
 * Aşağıdaki `WIN_RATE_BREAKEVEN_PCT` sabiti ve `winRateClass` helper'ı
 * win rate gösteriminde kullanılan breakeven eşiğinin TEK CANONICAL
 * kaynağıdır. Eski sürümde aynı `50` magic number'ı UstatBrain.jsx:319
 * (kontrat profilleri), Performance.jsx:494 (long), Performance.jsx:503
 * (short) ve TradeHistory.jsx:481 (filtered stats) olmak üzere 4 ayrı
 * yerde tekrarlanıyordu ve drift riski taşıyordu. Bu eşik backend
 * tarafında bir risk/karar parametresi DEĞİLDİR — yalnız UI renk
 * eşiğidir (yeşil/kırmızı). Backend ile ilgili olmadığı için
 * `config/default.json` yerine frontend ortak modülünde tutulur.
 * Değiştirmek isteyen bu dosyaya bakar; tüm bileşenler otomatik takip
 * eder. Flow 4y statik sözleşme testi 4 call site'ın yeniden hardcode
 * 50 girmesini engeller.
 */

export const WIN_RATE_BREAKEVEN_PCT = 50;

/**
 * Win rate yüzdesine göre CSS class döndürür.
 * Breakeven eşiği (%50) veya üstü → 'profit'; altı → 'loss'.
 * `null`/`undefined`/`NaN` değerlerde boş string döner (renk uygulanmaz).
 *
 * Widget Denetimi H13 — canonical atıf:
 * Bu helper `UstatBrain.jsx` kontrat profilleri, `Performance.jsx`
 * Long/Short paneli ve `TradeHistory.jsx` filtered stats tarafından
 * kullanılır.
 */
export function winRateClass(winRate) {
  if (winRate == null || isNaN(winRate)) return '';
  return winRate >= WIN_RATE_BREAKEVEN_PCT ? 'profit' : 'loss';
}

/**
 * Win rate yüzdesine göre CSS custom-property değeri döndürür.
 * Bileşenlerin `style={{ color: ... }}` veya custom component `color=`
 * prop'u beklediği yerlerde (Dashboard StatCard, HybridTrade perf panel)
 * `winRateClass` yerine bu kullanılır. Dönüş değeri `var(--profit)` veya
 * `var(--loss)` — theme.css'teki canonical renk değişkenleri.
 *
 * Widget Denetimi H13 — canonical atıf:
 * Dashboard.jsx hero stat card ve HybridTrade.jsx perf istatistik paneli
 * bu helper'ı kullanır.
 */
export function winRateColor(winRate) {
  if (winRate == null || isNaN(winRate)) return 'var(--muted)';
  return winRate >= WIN_RATE_BREAKEVEN_PCT ? 'var(--profit)' : 'var(--loss)';
}

/**
 * Para birimi formatla (TRY). 2 ondalık, Türkçe locale.
 * Negatif değerlerde `-` prefix eklenir.
 */
export function formatMoney(val) {
  if (val == null || isNaN(val)) return '—';
  const abs = Math.abs(val);
  const formatted = abs.toLocaleString('tr-TR', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return val < 0 ? `-${formatted}` : formatted;
}

/**
 * Fiyat formatla. Varsayılan: 2-5 ondalık (VİOP genel).
 * ManualTrade gibi özel durumlar için min/max parametresi kullanılabilir.
 */
export function formatPrice(val, minDigits = 2, maxDigits = 5) {
  if (val == null || isNaN(val) || val === 0) return '—';
  return val.toLocaleString('tr-TR', {
    minimumFractionDigits: minDigits,
    maximumFractionDigits: maxDigits,
  });
}

/**
 * K/Z değerine göre CSS class döndür.
 * Pozitif → 'profit', negatif → 'loss', sıfır → ''.
 */
export function pnlClass(val) {
  if (val > 0) return 'profit';
  if (val < 0) return 'loss';
  return '';
}

/**
 * Açılış zamanından itibaren geçen süreyi formatla.
 * Örnekler: "5dk", "2sa 30dk", "1g 5sa"
 */
export function elapsed(openTime) {
  if (!openTime) return '—';
  try {
    const ms = Date.now() - new Date(openTime).getTime();
    if (isNaN(ms) || ms < 0) return '—';
    const totalMin = Math.floor(ms / 60000);
    if (totalMin < 60) return `${totalMin}dk`;
    const h = Math.floor(totalMin / 60);
    const m = totalMin % 60;
    if (h < 24) return `${h}sa ${m}dk`;
    const d = Math.floor(h / 24);
    return `${d}g ${h % 24}sa`;
  } catch {
    return '—';
  }
}
