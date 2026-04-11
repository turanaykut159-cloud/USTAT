/**
 * ÜSTAT v6.0 — Operatör kimliği canonical kaynağı.
 *
 * Widget Denetimi H16 — Operatör hardcode'u kanonikleştirildi:
 * Eski sürümde TradeHistory.jsx::handleApprove (satır 366),
 * SideNav.jsx::handleKillSwitch (satır 89) ve TopBar.jsx::handleKsReset
 * (satır 134) `'operator'` literal string'ini doğrudan API çağrılarına
 * geçiriyordu. Sonuç: backend audit log her zaman "APPROVED by operator"
 * yazıyordu — birden fazla operatör çalışsa bile ayırt edilemiyordu.
 * Bu drift Widget Denetimi H16 (Düşük) + K7 (audit trail kullanıcı
 * kimlikli değil) ile birlikte kapsam altına alındı.
 *
 * Bu modül üç sorumluluğu üstlenir:
 *   1. Tek canonical kaynak — `getOperatorName()` her çağrı sitesi için
 *      aynı değeri döndürür (drift imkansız).
 *   2. Kullanıcı tarafından özelleştirilebilir — Settings ekranındaki
 *      "Operatör Adı" alanı `setOperatorName(name)` yoluyla localStorage'a
 *      kaydeder; sonraki tüm onay/kill-switch çağrıları bu değeri kullanır.
 *   3. Geriye uyumlu fallback — localStorage boşsa (yeni kurulum veya
 *      kullanıcı henüz ad girmediyse) `'operator'` döner. Bu sayede
 *      backend audit log mevcut davranışıyla aynı çıktıyı üretir;
 *      `_load_existing_groups` benzeri parse mantığı bozulmaz.
 *
 * Kapsam dışı (bilinçli):
 *   - Backend tarafında approved_by üzerinde whitelist/validation YOKTUR
 *     (audit log serbest metin). Bu modül sadece frontend kanonikleştirme
 *     sağlar; sunucu tarafı operatör doğrulama ileride bir görevdir.
 *   - Birden fazla operatör profili (multi-user) desteği YOKTUR — tek
 *     kullanıcılı masaüstü uygulamasında bir alan yeterli.
 *
 * Drift koruma testi: Flow 4za (test_static_contracts.py)
 *   - operator.js mevcut + 3 export regex doğrulanır
 *   - TradeHistory.jsx, SideNav.jsx, TopBar.jsx içinde literal `'operator'`
 *     parametresi YASAK (regression koruması)
 *   - Üç tüketici dosya errorTaxonomy benzeri stilde import yapmalı
 *   - Settings.jsx setOperatorName helper'ını import etmeli
 */

// localStorage key — Settings ve handler'lar bu sabiti import edebilir.
export const OPERATOR_NAME_KEY = 'ustat_operator_name';

// Geriye uyumluluk fallback'i — kullanıcı ad girmemişse backend audit
// log eski davranışla aynı string'i alır ("APPROVED by operator").
export const DEFAULT_OPERATOR = 'operator';

/**
 * Operatör kimliğini döndür. localStorage'da kayıtlı değer varsa onu,
 * yoksa DEFAULT_OPERATOR ('operator') döner.
 *
 * SSR/test ortamında `localStorage` undefined olabilir; her çağrı
 * try/catch ile sarılı — exception fallback'a düşer, çağıran katmana
 * sızdırılmaz.
 */
export function getOperatorName() {
  try {
    if (typeof localStorage === 'undefined') return DEFAULT_OPERATOR;
    const raw = localStorage.getItem(OPERATOR_NAME_KEY);
    if (raw == null) return DEFAULT_OPERATOR;
    const trimmed = String(raw).trim();
    return trimmed.length > 0 ? trimmed : DEFAULT_OPERATOR;
  } catch {
    return DEFAULT_OPERATOR;
  }
}

/**
 * Operatör adını localStorage'a kaydet. Boş/whitespace değer verilirse
 * kayıt SİLİNİR (kullanıcı varsayılana dönmüş sayılır).
 * Maksimum 64 karakter — backend audit log alanını taşırmamak için.
 *
 * Returns: kaydedilmiş efektif değer (DEFAULT_OPERATOR fallback dahil).
 */
export function setOperatorName(name) {
  try {
    if (typeof localStorage === 'undefined') return DEFAULT_OPERATOR;
    const trimmed = String(name == null ? '' : name).trim().slice(0, 64);
    if (trimmed.length === 0) {
      localStorage.removeItem(OPERATOR_NAME_KEY);
      return DEFAULT_OPERATOR;
    }
    localStorage.setItem(OPERATOR_NAME_KEY, trimmed);
    return trimmed;
  } catch {
    return DEFAULT_OPERATOR;
  }
}
