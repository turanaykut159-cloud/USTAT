/**
 * ÜSTAT v5.6 — Ortak formatlama yardımcıları.
 *
 * Tüm bileşenlerde tekrarlanan formatMoney, formatPrice, pnlClass, elapsed
 * fonksiyonları burada merkezileştirilmiştir.
 */

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
