/**
 * ÜSTAT — Hata Takip Canonical Taxonomy (Error Tracker Taxonomy).
 *
 * Bu dosya frontend tarafı için TEK canonical kaynak olarak kategori +
 * severity renklerini, etiketlerini ve filtre seçeneklerini tanımlar.
 *
 * Widget Denetimi Bulgu H7 (Düşük kritiklik) — Bölüm 16.3:
 *   "ErrorTracker.jsx içinde CATEGORY_COLORS, SEVERITY_COLORS, SEVERITY_LABELS
 *    ve kategori/severity filtre `options` dizileri ayrı ayrı hardcode ediliyordu.
 *    Backend engine/error_tracker.py ERROR_CATEGORIES veya SEVERITY_PRIORITY
 *    değişirse frontend sessizce kopar; drift koruması yoktu."
 *
 * ═══ BACKEND SÖZLEŞMESİ ═══
 *
 * Bu modül backend `engine/error_tracker.py` dosyasındaki iki yapıyla
 * senkron kalmak ZORUNDADIR:
 *
 *   1. `ERROR_CATEGORIES` dict unique values seti → `CATEGORY_COLORS` keys
 *      (engine/error_tracker.py satır ~32)
 *
 *   2. `SEVERITY_PRIORITY` dict keys (CRITICAL/ERROR/WARNING/INFO/DEBUG)
 *      → `SEVERITY_COLORS` keys (frontend badge/filtre DEBUG'ı göstermez)
 *      (engine/error_tracker.py satır ~66)
 *
 * Drift koruması:
 *   `tests/critical_flows/test_static_contracts.py::Flow 4z`
 *   (`test_error_taxonomy_backend_sync`) her CI çalıştırmasında backend
 *   dict'lerini parse eder ve bu modülle karşılaştırır. Backend yeni kategori
 *   eklerse ve bu dosya güncellenmezse testler FAIL eder — sessiz drift imkansız.
 *
 * UX İstisnaları (Drift değil, bilinçli tercih):
 *   - `"diğer"` kategorisi `CATEGORY_COLORS`'ta vardır (UNKNOWN fallback rozeti
 *     için gerekli) ama `CATEGORY_FILTER_OPTIONS`'dan HARİÇTİR — kullanıcıya
 *     "diğer" seçeneği göstermek anlamsız (zaten sınıflandırılmamış hataları
 *     filtrelemenin amacı yok).
 *   - `INFO` ve `DEBUG` seviyeleri `SEVERITY_FILTER_OPTIONS`'dan HARİÇTİR —
 *     `ErrorTracker` paneli zaten sadece WARNING/ERROR/CRITICAL gösterir
 *     (backend `error_tracker.py` `_load_existing_groups` yalnız bu üçünü
 *     yükler — satır ~192-194).
 *   - `SEVERITY_LABELS` UPPERCASE (badge görünümü) ↔ filtre dropdown'ları
 *     Title Case; bu iki farklı görsel bağlam için iki ayrı etiket seti vardır.
 */

// ═══ KATEGORİ RENKLERİ ═══════════════════════════════════════════════
// Sıra backend ERROR_CATEGORIES values sırasıyla eşleşir.
// Her key engine/error_tracker.py::ERROR_CATEGORIES.values() unique set
// içinde bulunmak ZORUNDADIR (Flow 4z doğrular).

export const CATEGORY_COLORS = {
  'bağlantı': '#3b82f6', // MT5 connection & network
  'emir':     '#f59e0b', // Order lifecycle (reject/timeout/partial/SLTP)
  'risk':     '#ef4444', // Kill-switch, drawdown, cooldown
  'sinyal':   '#8b5cf6', // Fake signal, rejected signal
  'netting':  '#ec4899', // Netting mismatch, external close
  'veri':     '#06b6d4', // Data anomaly, stale data
  'sistem':   '#6b7280', // DB, cycle overrun, IPC
  'diğer':    '#9ca3af', // UNKNOWN fallback
};

// ═══ KATEGORİ GÖRÜNEN ADLAR (Turkish Title Case) ════════════════════

export const CATEGORY_LABELS = {
  'bağlantı': 'Bağlantı',
  'emir':     'Emir',
  'risk':     'Risk',
  'sinyal':   'Sinyal',
  'netting':  'Netting',
  'veri':     'Veri',
  'sistem':   'Sistem',
  'diğer':    'Diğer',
};

// UX kararı: "diğer" kullanıcı filtresinde gösterilmez — UNKNOWN fallback'i
// filtrelemenin anlamı yok. Ama CATEGORY_COLORS'ta bulunur (rozette kullanılır).
const CATEGORY_FILTER_EXCLUDE = new Set(['diğer']);

// Filtre dropdown'u için hazır seçenek dizisi. Sıra CATEGORY_COLORS sırasıyla.
export const CATEGORY_FILTER_OPTIONS = Object.keys(CATEGORY_COLORS)
  .filter(cat => !CATEGORY_FILTER_EXCLUDE.has(cat))
  .map(cat => ({ value: cat, label: CATEGORY_LABELS[cat] }));

// ═══ SEVİYE RENKLERİ ═════════════════════════════════════════════════
// Her key backend SEVERITY_PRIORITY keys içinde olmalı. INFO/DEBUG frontend'de
// gösterilmez ama ileride eklenebilir diye INFO tutulur (CATEGORY_COLORS ve
// SEVERITY_COLORS rozetlerinin simetrisi için).

export const SEVERITY_COLORS = {
  CRITICAL: '#ef4444',
  ERROR:    '#f97316',
  WARNING:  '#eab308',
  INFO:     '#3b82f6',
};

// Badge görünümü için UPPERCASE etiketler (hata grupları tablosu rozetleri).
// Kullanım: ErrorTracker.jsx satır 476 `{SEVERITY_LABELS[g.severity] || g.severity}`.

export const SEVERITY_LABELS = {
  CRITICAL: 'KRİTİK',
  ERROR:    'HATA',
  WARNING:  'UYARI',
};

// Filtre dropdown'u için Title Case etiketler (rozet UPPERCASE'den farklı).
const SEVERITY_FILTER_LABELS = {
  CRITICAL: 'Kritik',
  ERROR:    'Hata',
  WARNING:  'Uyarı',
};

// INFO ve DEBUG filtreden hariç — `_load_existing_groups` bu seviyeleri yüklemez
// (error_tracker.py satır 192-194).
export const SEVERITY_FILTER_OPTIONS = Object.keys(SEVERITY_FILTER_LABELS)
  .map(sev => ({ value: sev, label: SEVERITY_FILTER_LABELS[sev] }));
