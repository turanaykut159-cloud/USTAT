/**
 * ÜSTAT v5.7 — Ana Dashboard ekranı.
 *
 * Layout:
 *   Üst:    4 stat kartı (Günlük İşlem, Başarı Oranı, Net K/Z, Profit Factor)
 *   Hesap:  Bakiye, Varlık, Teminat, Serbest Teminat, Floating K/Z, Günlük K/Z
 *   Orta:   Açık Pozisyonlar — TAM ÖZELLİKLİ (Swap, Yönetim, Süre, Rejim, Hibrit)
 *   Alt:    Son 5 işlem tablosu (tam genişlik)
 *
 * Veri kaynakları:
 *   REST:  getTradeStats, getPerformance, getTrades, getStatus, getPositions,
 *          getAccount, getHybridStatus (10sn poll)
 *   WS:    connectLiveWS → equity + status + position + hybrid gerçek zamanlı
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  DndContext,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core';
import {
  SortableContext,
  rectSortingStrategy,
  arrayMove,
} from '@dnd-kit/sortable';
import {
  getTradeStats, getPerformance, getTrades, getStatus,
  getAccount, getPositions, closePosition, connectLiveWS,
  getHybridStatus, checkHybridTransfer, transferToHybrid,
  getNewsActive, getNotifications, markNotificationRead, markAllNotificationsRead,
  getRisk,
} from '../services/api';
// Widget Denetimi H13: Dashboard hero stat card "Başarı Oranı" win rate
// renk değeri canonical kaynağa bağlandı — eski satır 589 hardcode
// `>= 50 ? var(--profit) : var(--loss)` kullanıyordu. Drift koruması
// Flow 4y ile sağlanır.
import { formatMoney, formatPrice, pnlClass, elapsed, winRateColor } from '../utils/formatters';
import ConfirmModal from './ConfirmModal';
import PrimnetDetail from './PrimnetDetail';
import SortableCard from './SortableCard';
import NewsPanel from './NewsPanel';
import './NewsPanel.css';

// ── Yardımcılar ──────────────────────────────────────────────────

function formatPct(val) {
  if (val == null || isNaN(val)) return '—';
  return `%${val.toFixed(1)}`;
}

function formatPF(val) {
  if (val == null || isNaN(val) || val === 0) return '—';
  return val.toFixed(2);
}

/** Timestamp → tarih + saat (gg.aa.yyyy HH:mm) */
function shortTime(ts) {
  if (!ts) return '';
  try {
    const d = new Date(ts);
    return d.toLocaleString('tr-TR', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return '';
  }
}

/** Teminat kullanım oranı (%) */
function marginUsagePct(margin, equity) {
  if (!margin || !equity || equity <= 0) return 0;
  return (margin / equity) * 100;
}

// Bilinen otomatik stratejiler
const KNOWN_AUTO_STRATEGIES = ['trend_follow', 'mean_reversion', 'breakout'];

// ── Sekme geçişi cache — unmount/remount'ta "Yükleniyor" flash'ını önler ──
// Modül seviyesinde tutulur: React state yıkılsa bile veri kalır.
let _dashCache = null;   // { stats, perf, recentTrades, status, account, livePositions, hybridTickets }
let _dashLoaded = false; // en az 1 kez başarılı fetchAll yapıldı mı?

// ═══════════════════════════════════════════════════════════════════
//  DASHBOARD
// ═══════════════════════════════════════════════════════════════════

export default function Dashboard() {
  const navigate = useNavigate();

  // ── State (cache varsa ondan başlat → "Yükleniyor" flash'ı olmaz) ──
  const [stats, setStats] = useState(
    _dashCache?.stats ?? { total_trades: 0, win_rate: 0, total_pnl: 0 },
  );
  const [perf, setPerf] = useState(
    _dashCache?.perf ?? { profit_factor: 0, equity_curve: [] },
  );
  const [recentTrades, setRecentTrades] = useState(_dashCache?.recentTrades ?? []);
  const [status, setStatus] = useState(
    _dashCache?.status ?? { regime: 'TREND', regime_confidence: 0, engine_running: false, daily_trade_count: 0 },
  );
  const [account, setAccount] = useState(
    _dashCache?.account ?? { balance: 0, equity: 0, margin: 0, free_margin: 0, floating_pnl: 0 },
  );
  const [livePositions, setLivePositions] = useState(_dashCache?.livePositions ?? []);
  // v6.0 — Widget Denetimi A18 / H2: max_open_positions artık config'den okunur.
  // Dashboard pozisyon rozetinde "n / X" formatında — eski hardcode "/5" yerine.
  // Backend zinciri: config/default.json::risk.max_open_positions → /api/risk (RiskResponse)
  // → getRisk() → riskState state → JSX render. Fallback 5 geriye dönük uyumluluk için.
  const [riskState, setRiskState] = useState(_dashCache?.riskState ?? null);
  // İlk kez açılıyorsa loading göster, daha önce yüklendiyse gösterme
  const [initialLoading, setInitialLoading] = useState(!_dashLoaded);
  const [closingTicket, setClosingTicket] = useState(null);
  const [hybridTickets, setHybridTickets] = useState(_dashCache?.hybridTickets ?? new Set());
  const [hybridPositions, setHybridPositions] = useState([]);
  const [primnetConfig, setPrimnetConfig] = useState(null);
  const [selectedHybridPos, setSelectedHybridPos] = useState(null);
  const [transferringTicket, setTransferringTicket] = useState(null);

  // WebSocket kaynak canlı veri
  const [liveEquity, setLiveEquity] = useState(null);
  const [wsState, setWsState] = useState('disconnected'); // 'connected' | 'reconnecting' | 'disconnected'
  const [equityStale, setEquityStale] = useState(false);
  const wsRef = useRef(null);

  // v5.7.1: Haber verileri (WebSocket'ten güncellenir)
  const [newsData, setNewsData] = useState(null);

  // Hata gösterimi (window.alert yerine)
  const [apiError, setApiError] = useState(null);
  const [errorModal, setErrorModal] = useState(null); // { title, message }

  // ── Bildirim sistemi ───────────────────────────────────────────
  const [notifications, setNotifications] = useState([]);
  const [showNotifPanel, setShowNotifPanel] = useState(false);
  const unreadCount = notifications.filter((n) => !n.read).length;

  // v6.0 — Widget Denetimi A3/S1: Bildirim tercihleri (Settings ile aynı anahtar).
  // `tradeAlert` kapalıysa hybrid_* WS bildirimleri drawer'a eklenmez.
  // Storage event dinleyicisi Settings sayfasında toggle değişince otomatik
  // güncelleme sağlar.
  const NOTIF_PREFS_KEY = 'ustat_notification_prefs';
  const NOTIF_PREFS_DEFAULT = {
    soundEnabled: true,
    killSwitchAlert: true,
    tradeAlert: true,
    drawdownAlert: true,
    regimeAlert: false,
  };
  const readNotifPrefs = () => {
    try {
      const saved = localStorage.getItem(NOTIF_PREFS_KEY);
      return saved ? { ...NOTIF_PREFS_DEFAULT, ...JSON.parse(saved) } : NOTIF_PREFS_DEFAULT;
    } catch {
      return NOTIF_PREFS_DEFAULT;
    }
  };
  const notifPrefsRef = useRef(readNotifPrefs());
  useEffect(() => {
    const onStorage = (e) => {
      if (e.key === NOTIF_PREFS_KEY) {
        notifPrefsRef.current = readNotifPrefs();
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);
  // Bildirim tipini tercih anahtarına eşler. Şu an sadece hybrid_* aktif
  // (gerçek davranışa bağlı tek kategori). Diğer tipler filtrelenmez.
  const shouldShowNotification = (msg) => {
    const prefs = notifPrefsRef.current || NOTIF_PREFS_DEFAULT;
    const t = msg?.notif_type || msg?.type || '';
    if (typeof t === 'string' && t.startsWith('hybrid_')) {
      return prefs.tradeAlert !== false;
    }
    return true;
  };

  // Süre yenileme tetikleyici (30sn)
  const [, setTick] = useState(new Date());

  // ── Sürükle-bırak kart sıralaması (@dnd-kit) ────────────────
  const DEFAULT_CARD_ORDER = ['stat_daily', 'stat_winrate', 'stat_pnl', 'stat_pf', 'account', 'positions', 'trades', 'news'];
  const DASH_STORAGE_KEY = 'ustat_dashboard_card_order';

  const [cardOrder, setCardOrder] = useState(() => {
    try {
      const saved = localStorage.getItem(DASH_STORAGE_KEY);
      if (saved) {
        const parsed = JSON.parse(saved);
        // Tüm beklenen ID'ler mevcut mu kontrol et
        if (Array.isArray(parsed) && parsed.length === DEFAULT_CARD_ORDER.length
            && DEFAULT_CARD_ORDER.every(id => parsed.includes(id))) return parsed;
      }
    } catch { /* bozuk veri — varsayılana dön */ }
    return DEFAULT_CARD_ORDER;
  });

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } })
  );

  const handleDragEnd = useCallback((event) => {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    setCardOrder((prev) => {
      const oldIndex = prev.indexOf(active.id);
      const newIndex = prev.indexOf(over.id);
      if (oldIndex === -1 || newIndex === -1) return prev;
      const reordered = arrayMove(prev, oldIndex, newIndex);
      try { localStorage.setItem(DASH_STORAGE_KEY, JSON.stringify(reordered)); } catch {}
      return reordered;
    });
  }, []);

  const handleResetOrder = useCallback(() => {
    setCardOrder(DEFAULT_CARD_ORDER);
    try { localStorage.setItem(DASH_STORAGE_KEY, JSON.stringify(DEFAULT_CARD_ORDER)); } catch {}
  }, []);

  const CARD_LABELS = {
    stat_daily: 'Günlük İşlem',
    stat_winrate: 'Başarı Oranı',
    stat_pnl: 'Net K/Z',
    stat_pf: 'Profit Factor',
    account: 'Hesap Durumu',
    positions: 'Açık Pozisyonlar',
    trades: 'Son İşlemler',
    news: 'Haber Akışı',
  };

  // ── Trade/Stats veri çekme (WS event-driven) ────────────────────
  const fetchTradeData = useCallback(async () => {
    const [s, p, t] = await Promise.all([
      getTradeStats(),
      getPerformance(30),
      getTrades({ limit: 5 }),
    ]);
    setStats(s);
    setPerf(p);
    setRecentTrades(t.trades || []);
  }, []);

  // ── Durum/Pozisyon veri çekme (REST fallback, 30sn) ────────────
  const fetchAll = useCallback(async () => {
    try {
      const [s, p, t, st, acc, pos, hybrid, rk] = await Promise.all([
        getTradeStats(),
        getPerformance(30),
        getTrades({ limit: 5 }),
        getStatus(),
        getAccount(),
        getPositions(),
        getHybridStatus(),
        getRisk(), // A18: max_open_positions için config zincirinden oku
      ]);
      setStats(s);
      setPerf(p);
      setRecentTrades(t.trades || []);
      setStatus(st);
      setAccount(acc);
      setLivePositions(pos.positions || []);
      setRiskState(rk || null);
      const tickets = (hybrid.positions || []).map((hp) => hp.ticket).filter(Boolean);
      setHybridTickets(new Set(tickets));
      setHybridPositions(hybrid.positions || []);
      if (hybrid.primnet) setPrimnetConfig(hybrid.primnet);
      setApiError(null); // Başarılı fetch → hata banner'ını temizle

      // ── v5.7.2: News REST polling (WS Chrome'da çalışmıyorsa fallback) ──
      try {
        const newsResp = await getNewsActive();
        if (newsResp && newsResp.events) {
          setNewsData({
            type: 'news',
            active_count: newsResp.count || newsResp.events.length,
            events: newsResp.events,
            worst_sentiment: newsResp.events.length > 0
              ? Math.min(...newsResp.events.map(e => e.sentiment_score))
              : null,
            best_sentiment: newsResp.events.length > 0
              ? Math.max(...newsResp.events.map(e => e.sentiment_score))
              : null,
          });
        }
      } catch (_) { /* news polling opsiyonel */ }

      // ── Cache güncelle — sonraki mount'larda anında gösterilir ──
      _dashCache = {
        stats: s, perf: p, recentTrades: t.trades || [],
        status: st, account: acc, livePositions: pos.positions || [],
        hybridTickets: new Set(tickets),
        riskState: rk || null, // A18: max_open_positions cache'i
      };
      _dashLoaded = true;
    } catch (err) {
      console.error('[Dashboard] fetchAll:', err?.message ?? err);
      setApiError('Veri yüklenemedi. API erişilebilir mi kontrol edin.');
    } finally {
      setInitialLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
    // DB'den bildirimleri yükle (başlangıç)
    getNotifications({ limit: 50 }).then((resp) => {
      if (resp.notifications) {
        // v6.0 — Widget Denetimi A3/S1: tercihler DB kaynaklı bildirimleri de kapılar.
        const filtered = resp.notifications.filter((n) => shouldShowNotification({ type: n.type, notif_type: n.type }));
        setNotifications(filtered.map((n) => ({
          id: n.id,
          type: n.type,
          title: n.title,
          message: n.message,
          severity: n.severity,
          read: n.read,
          timestamp: n.timestamp,
          dbId: n.id,
        })));
      }
    });
    const iv = setInterval(fetchAll, 10000);
    return () => clearInterval(iv);
  }, [fetchAll]);

  // ── Süre yenileme (30sn) ─────────────────────────────────────────
  useEffect(() => {
    const iv = setInterval(() => setTick(new Date()), 30000);
    return () => clearInterval(iv);
  }, []);

  // ── Equity staleness kontrolü (10 saniye eşik) ──────────────────
  useEffect(() => {
    const iv = setInterval(() => {
      if (liveEquity && liveEquity.ts) {
        const ageSec = Date.now() / 1000 - liveEquity.ts;
        setEquityStale(ageSec > 10);
      } else {
        setEquityStale(wsState !== 'connected');
      }
    }, 2000);
    return () => clearInterval(iv);
  }, [liveEquity, wsState]);

  // ── WebSocket canlı veri ─────────────────────────────────────────
  useEffect(() => {
    const { close } = connectLiveWS(
      (messages) => {
        const arr = Array.isArray(messages) ? messages : [messages];
        for (const msg of arr) {
          if (msg.type === 'equity') {
            setLiveEquity(msg);
            setEquityStale(false);
            // Margin/free_margin artık WS'ten de geliyor (2sn, REST 30sn yerine)
            if (msg.margin != null) {
              setAccount((prev) => ({
                ...prev,
                margin: msg.margin,
                free_margin: msg.free_margin,
              }));
            }
          }
          if (msg.type === 'status') {
            setStatus((prev) => ({
              ...prev,
              regime: msg.regime || prev.regime,
              can_trade: msg.can_trade,
              kill_switch_level: msg.kill_switch_level,
            }));
          }
          if (msg.type === 'position') {
            setLivePositions(msg.positions || []);
          }
          if (msg.type === 'hybrid') {
            const tickets = new Set((msg.positions || []).map((hp) => hp.ticket));
            setHybridTickets(tickets);
          }
          if (msg.type === 'news') {
            setNewsData(msg);
          }
          if (msg.type === 'trade_closed' || msg.type === 'position_closed') {
            fetchTradeData();
          }
          if (msg.type === 'notification') {
            // v6.0 — Widget Denetimi A3/S1: tercihler drawer'ı kapılar.
            if (!shouldShowNotification(msg)) {
              return;
            }
            setNotifications((prev) => [
              { id: Date.now(), read: false, ...msg },
              ...prev,
            ].slice(0, 50));
          }
        }
      },
      null,
      (newState) => setWsState(newState),
    );

    wsRef.current = close;
    return () => {
      if (wsRef.current) wsRef.current();
    };
  }, [fetchTradeData]);

  // ── İşlemi Kapat ─────────────────────────────────────────────────
  const handleClosePosition = useCallback(async (ticket) => {
    if (closingTicket != null) return;
    setClosingTicket(ticket);
    try {
      await closePosition(ticket);
      await fetchAll();
    } catch (err) {
      setErrorModal({
        title: 'Pozisyon Kapatma Hatası',
        message: 'Kapatma hatası: ' + (err?.message ?? String(err)),
      });
    } finally {
      setClosingTicket(null);
    }
  }, [closingTicket, fetchAll]);

  // ── Hibrite Devret ────────────────────────────────────────────────
  const handleTransferToHybrid = useCallback(async (ticket) => {
    if (transferringTicket != null) return;
    setTransferringTicket(ticket);
    try {
      const check = await checkHybridTransfer(ticket);
      if (!check.can_transfer) {
        setErrorModal({
          title: 'Hibrite Devir',
          message: 'Hibrite devir yapılamaz: ' + (check.reason || 'Bilinmeyen hata'),
        });
        return;
      }
      const result = await transferToHybrid(ticket);
      if (result.success) {
        setHybridTickets((prev) => new Set([...prev, ticket]));
      } else {
        // Backend zaten enrich_message() ile cok satirli zengin metin dondurur
        // (Neden + Nasil duzeltilir + retcode). Prefix eklemeden ham mesaji goster.
        setErrorModal({
          title: 'Devir Hatası',
          message: result.message || 'Bilinmeyen hata — devir tamamlanamadı.',
        });
      }
    } catch (err) {
      setErrorModal({
        title: 'Devir Hatası',
        message: 'Devir isteği gönderilemedi: ' + (err?.message ?? String(err)),
      });
    } finally {
      setTransferringTicket(null);
    }
  }, [transferringTicket]);

  // ── Hesaplamalar ─────────────────────────────────────────────────
  const regime = status.regime || 'TREND';
  const totalFloating = (livePositions || []).reduce((s, p) => s + (p.pnl || 0), 0);
  const totalLot = (livePositions || []).reduce((s, p) => s + (p.volume || 0), 0);
  const totalSwap = (livePositions || []).reduce((s, p) => s + (p.swap || 0), 0);
  // Stale durumda REST fallback kullan
  const eq = equityStale
    ? account.equity
    : (liveEquity?.equity ?? account.equity);
  const marginPct = marginUsagePct(account.margin, eq);

  if (initialLoading) {
    return (
      <div className="dashboard">
        <div className="dash-loading-wrap">
          <p className="dash-loading">Yükleniyor...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="dashboard">

      {/* ═══ BİLDİRİM BUTONU ═══════════════════════════════════════ */}
      <div className="dash-notif-bar">
        <button
          className={`dash-notif-btn${unreadCount > 0 ? ' dash-notif-btn--pulse' : ''}`}
          onClick={() => setShowNotifPanel((v) => !v)}
          title={unreadCount > 0 ? `${unreadCount} okunmamış bildirim` : 'Bildirimler'}
        >
          {unreadCount > 0 ? `Bildirimler (${unreadCount})` : 'Bildirimler'}
        </button>
      </div>

      {/* ═══ BİLDİRİM PANELİ ═════════════════════════════════════ */}
      {showNotifPanel && (
        <div className="dash-notif-panel">
          <div className="dash-notif-header">
            <span>Bildirimler</span>
            {unreadCount > 0 && (
              <button
                className="dash-notif-mark-all"
                onClick={() => {
                  markAllNotificationsRead();
                  setNotifications((prev) =>
                    prev.map((n) => ({ ...n, read: true }))
                  );
                }}
              >
                Tümünü okundu yap
              </button>
            )}
          </div>
          {notifications.length === 0 ? (
            <div className="dash-notif-empty">Bildirim yok</div>
          ) : (
            <div className="dash-notif-list">
              {notifications.map((n) => (
                <div
                  key={n.id}
                  className={`dash-notif-item${n.read ? '' : ' dash-notif-item--unread'}`}
                  onClick={() => {
                    if (n.dbId) markNotificationRead(n.dbId);
                    setNotifications((prev) =>
                      prev.map((x) => x.id === n.id ? { ...x, read: true } : x)
                    );
                  }}
                >
                  <div className="dash-notif-title">
                    {n.severity === 'warning' ? '!' : ''} {n.title || 'Bildirim'}
                  </div>
                  <div className="dash-notif-msg">{n.message || ''}</div>
                  <div className="dash-notif-time">
                    {n.timestamp ? shortTime(n.timestamp) : ''}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ═══ SÜRÜKLE-BIRAK KART SİSTEMİ ══════════════════════════ */}
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
        <button
          type="button"
          className="grid-reset-btn"
          onClick={handleResetOrder}
          title="Kartları varsayılan sıraya döndür"
        >
          ↺ Sıfırla
        </button>
      </div>

      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext items={cardOrder} strategy={rectSortingStrategy}>
        <div className="dash-dnd-grid">

      {cardOrder.map((cardId) => {
        switch (cardId) {

        /* ═══ STAT KARTLARI (her biri ayrı sürüklenebilir) ═════════ */
        case 'stat_daily':
          return (
            <SortableCard key="stat_daily" id="stat_daily" label={CARD_LABELS.stat_daily} className="dash-stat-item">
              <StatCard
                label="Günlük İşlem"
                sublabel="bugün"
                value={status.daily_trade_count || 0}
                total={stats.total_trades}
                icon="📊"
              />
            </SortableCard>
          );

        case 'stat_winrate':
          return (
            <SortableCard key="stat_winrate" id="stat_winrate" label={CARD_LABELS.stat_winrate} className="dash-stat-item">
              <StatCard
                label="Başarı Oranı"
                value={formatPct(stats.win_rate)}
                detail={`${stats.winning_trades || 0}W / ${stats.losing_trades || 0}L`}
                icon="🎯"
                color={winRateColor(stats.win_rate)}
              />
            </SortableCard>
          );

        case 'stat_pnl':
          return (
            <SortableCard key="stat_pnl" id="stat_pnl" label={CARD_LABELS.stat_pnl} className="dash-stat-item">
              <StatCard
                label="Net Kâr/Zarar"
                value={formatMoney(stats.total_pnl)}
                detail="Kapanan işlemler toplamı (DB)"
                icon="💰"
                color={stats.total_pnl >= 0 ? 'var(--profit)' : 'var(--loss)'}
              />
            </SortableCard>
          );

        case 'stat_pf':
          return (
            <SortableCard key="stat_pf" id="stat_pf" label={CARD_LABELS.stat_pf} className="dash-stat-item">
              <StatCard
                label="Profit Factor"
                value={formatPF(perf.profit_factor)}
                icon="📐"
                color={perf.profit_factor >= 1.5 ? 'var(--profit)' : perf.profit_factor >= 1 ? 'var(--warning)' : 'var(--loss)'}
              />
            </SortableCard>
          );

        /* ═══ HESAP DURUMU (canlı) ═════════════════════════════════ */
        case 'account':
          return (
            <SortableCard key="account" id="account" label={CARD_LABELS.account} className="dash-full-item">
      {(equityStale || wsState === 'reconnecting' || status.data_fresh === false || status.circuit_breaker_active) && (
        <div className="dash-stale-banner">
          {status.circuit_breaker_active
            ? '🔴 MT5 bağlantı krizi — circuit breaker aktif, otomatik yeniden deneme bekleniyor'
            : status.data_fresh === false
            ? '⚠ Engine verisi eski — son başarılı cycle 60+ saniye önce'
            : wsState === 'reconnecting'
            ? '⚠ Bağlantı koptu — yeniden bağlanıyor...'
            : '⚠ Veri eski — son güncelleme 10+ saniye önce'}
        </div>
      )}
      {apiError && (
        <div className="dash-api-error-banner">
          ⚠ {apiError}
        </div>
      )}
      <div className="dash-account-strip">
        <AccountItem
          label="Bakiye"
          value={formatMoney(equityStale ? account.balance : (liveEquity?.balance ?? account.balance))}
        />
        <AccountItem
          label="Varlık"
          value={formatMoney(eq)}
        />
        <AccountItem
          label="Teminat"
          value={formatMoney(account.margin)}
        />
        <AccountItem
          label="Serbest Teminat"
          value={formatMoney(account.free_margin)}
        />
        <AccountItem
          label="Floating K/Z"
          value={formatMoney(equityStale ? account.floating_pnl : (liveEquity?.floating_pnl ?? account.floating_pnl))}
          cls={pnlClass(equityStale ? account.floating_pnl : (liveEquity?.floating_pnl ?? account.floating_pnl))}
        />
        <AccountItem
          label="Günlük K/Z"
          value={formatMoney(equityStale ? account.daily_pnl : (liveEquity?.daily_pnl ?? account.daily_pnl))}
          cls={pnlClass(equityStale ? account.daily_pnl : (liveEquity?.daily_pnl ?? account.daily_pnl))}
        />
      </div>
            </SortableCard>
          );

        /* ═══ ORTA: Açık Pozisyonlar (TAM ÖZELLİKLİ) ═══════════════ */
        case 'positions':
          return (
            <SortableCard key="positions" id="positions" label={CARD_LABELS.positions} className="dash-full-item">
      <div className="dash-positions-row">
        <div className="dash-card dash-card--full">
          <div className="dash-card-header">
            <h3>Açık Pozisyonlar</h3>
            <div className="dash-card-header-right">
              <span className="dash-card-badge">
                {/* A18: "/5" eski hardcode'u, artık riskState.max_open_positions (config zinciri). */}
                {(livePositions || []).length} / {riskState?.max_open_positions ?? 5}
              </span>
              {account.margin > 0 && (
                <span className={`dash-margin-badge ${marginPct > 80 ? 'danger' : marginPct > 50 ? 'warn' : ''}`}>
                  Teminat: %{marginPct.toFixed(1)}
                </span>
              )}
            </div>
          </div>
          {(livePositions || []).length === 0 ? (
            <div className="dash-positions-empty">
              <span>📭</span> Açık pozisyon yok
            </div>
          ) : (
            <table className="dash-positions-table">
              <thead>
                <tr>
                  <th>Sembol</th>
                  <th>Yön</th>
                  <th>Lot</th>
                  <th>Giriş Fiy.</th>
                  <th>Anlık Fiy.</th>
                  <th>SL</th>
                  <th>TP</th>
                  <th>Swap</th>
                  <th>K/Z</th>
                  <th>Tür</th>
                  <th>Yönetim</th>
                  <th>Süre</th>
                  <th>Rejim</th>
                  <th>İşlem</th>
                </tr>
              </thead>
              <tbody>
                {(livePositions || []).map((pos) => {
                  const pnl = pos.pnl || 0;
                  const rowCls = pnl > 0 ? 'op-row-profit' : pnl < 0 ? 'op-row-loss' : '';
                  const isHybrid = hybridTickets.has(pos.ticket);

                  // Tür: API'den gelen tur kullan; yoksa fallback
                  const apiTur = (pos.tur || '').trim();
                  let turLabel = apiTur;
                  let turClass = 'manual';
                  if (apiTur === 'Hibrit' || apiTur === 'Otomatik' || apiTur === 'Manuel' || apiTur === 'MT5') {
                    turClass = apiTur === 'Hibrit' ? 'hybrid' : apiTur === 'Otomatik' ? 'auto' : apiTur === 'MT5' ? 'mt5' : 'manual';
                  } else {
                    const stratLower = (pos.strategy || '').toLowerCase().trim();
                    const isAuto = KNOWN_AUTO_STRATEGIES.includes(stratLower);
                    turLabel = isHybrid ? 'Hibrit' : isAuto ? 'Otomatik' : 'Manuel';
                    turClass = isHybrid ? 'hybrid' : isAuto ? 'auto' : 'manual';
                  }

                  return (
                    <tr key={pos.ticket || pos.symbol} className={rowCls}>
                      <td className="mono op-symbol">{pos.symbol}</td>
                      <td>
                        <span className={`dir-badge dir-badge--${(pos.direction || '').toLowerCase()}`}>
                          {pos.direction}
                        </span>
                      </td>
                      <td className="mono">{pos.volume?.toFixed(2) ?? '—'}</td>
                      <td className="mono">{formatPrice(pos.entry_price)}</td>
                      <td className="mono">{formatPrice(pos.current_price)}</td>
                      <td className="mono text-dim">{formatPrice(pos.sl)}</td>
                      <td className="mono text-dim">{formatPrice(pos.tp)}</td>
                      <td className={`mono text-dim ${pnlClass(pos.swap || 0)}`}>
                        {formatMoney(pos.swap || 0)}
                      </td>
                      <td className={`mono op-pnl-cell ${pnlClass(pnl)}`}>
                        <b>{formatMoney(pnl)}</b>
                      </td>
                      <td className="op-tur-cell">
                        <span className={`op-tur-badge op-tur--${turClass}`}>
                          {turLabel}
                        </span>
                      </td>
                      <td className="op-mgmt-cell">
                        {pos.tp1_hit && <span className="op-mgmt-badge op-mgmt--tp1" title="TP1 yarı kapanış yapıldı">TP1</span>}
                        {pos.breakeven_hit && <span className="op-mgmt-badge op-mgmt--be" title="Breakeven çekildi">BE</span>}
                        {pos.cost_averaged && <span className="op-mgmt-badge op-mgmt--avg" title="Maliyetlendirme yapıldı">MA</span>}
                        {(pos.voting_score != null && pos.voting_score > 0) && (
                          <span className={`op-mgmt-badge op-mgmt--vote${pos.voting_score >= 3 ? '-strong' : '-weak'}`}
                            title={`Oylama skoru: ${pos.voting_score}/4`}>
                            {pos.voting_score}/4
                          </span>
                        )}
                      </td>
                      <td className="text-dim">{elapsed(pos.open_time)}</td>
                      <td>
                        <span className={`op-regime-tag op-regime--${(regime || '').toLowerCase()}`}>
                          {regime}
                        </span>
                      </td>
                      <td className="op-action-cell">
                        <button
                          type="button"
                          className="op-close-btn"
                          onClick={() => handleClosePosition(pos.ticket)}
                          disabled={closingTicket === pos.ticket}
                          title="Bu pozisyonu kapat"
                        >
                          {closingTicket === pos.ticket ? 'Kapatılıyor...' : 'İşlemi Kapat'}
                        </button>
                        {isHybrid ? (
                          <button
                            type="button"
                            className="op-hybrid-link-btn"
                            onClick={() => {
                              const hp = hybridPositions.find((h) => h.ticket === pos.ticket);
                              if (hp) setSelectedHybridPos(hp);
                            }}
                            title="PRİMNET detayını görüntüle"
                          >
                            PRİMNET
                          </button>
                        ) : (
                          <button
                            type="button"
                            className="op-hybrid-btn"
                            onClick={() => handleTransferToHybrid(pos.ticket)}
                            disabled={transferringTicket === pos.ticket}
                            title="Robot yönetimine devret"
                          >
                            {transferringTicket === pos.ticket ? 'Devrediliyor...' : 'Hibrite Devret'}
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr className="op-footer-row">
                  <td colSpan={2}><b>TOPLAM</b></td>
                  <td className="mono"><b>{totalLot.toFixed(2)}</b></td>
                  <td colSpan={4}></td>
                  <td className="mono text-dim">
                    {formatMoney(totalSwap)}
                  </td>
                  <td className={`mono ${pnlClass(totalFloating)}`}>
                    <b>{formatMoney(totalFloating)}</b>
                  </td>
                  <td colSpan={5}></td>
                </tr>
              </tfoot>
            </table>
          )}
        </div>
      </div>
            </SortableCard>
          );

        /* ═══ ALT: Son İşlemler (tam genişlik) ══════════════════════ */
        case 'trades':
          return (
            <SortableCard key="trades" id="trades" label={CARD_LABELS.trades} className="dash-full-item">
      <div className="dash-bottom-row">
        <div className="dash-card">
          <h3>
            Son İşlemler
            {(() => {
              const unapproved = recentTrades.filter(
                (t) => !(t.exit_reason || '').includes('APPROVED')
              ).length;
              return unapproved > 0 ? (
                <span className="dash-unapproved-badge" title="Onaylanmamış işlem sayısı">
                  {unapproved} onaysız
                </span>
              ) : null;
            })()}
          </h3>
          {recentTrades.length > 0 ? (
            <table className="dash-trades-table">
              <thead>
                <tr>
                  <th>Sembol</th>
                  <th>Yön</th>
                  <th>Strateji</th>
                  <th>Lot</th>
                  <th>K/Z</th>
                  <th>Zaman</th>
                </tr>
              </thead>
              <tbody>
                {recentTrades.map((t, i) => (
                  <tr key={t.id || i}>
                    <td className="mono">{t.symbol}</td>
                    <td>
                      <span className={`dir-badge dir-badge--${t.direction?.toLowerCase()}`}>
                        {t.direction}
                      </span>
                    </td>
                    <td className="text-dim">{t.strategy || '—'}</td>
                    <td className="mono">{t.lot?.toFixed(2) ?? '—'}</td>
                    <td className={`mono ${pnlClass(t.pnl)}`}>
                      {formatMoney(t.pnl)}
                    </td>
                    <td className="text-dim">{shortTime(t.exit_time || t.entry_time)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="dash-empty-msg">Henüz işlem yok</div>
          )}
        </div>
      </div>
            </SortableCard>
          );

        /* ═══ HABER PANELİ (v5.7.1) ══════════════════════════════════ */
        case 'news':
          return (
            <SortableCard key="news" id="news" label={CARD_LABELS.news} className="dash-full-item">
              <NewsPanel newsData={newsData} />
            </SortableCard>
          );

        default:
          return null;
        }
      })}

        </div>
        </SortableContext>
      </DndContext>

      {/* ═══ HATA MODAL (window.alert yerine) ═════════════════════ */}
      {/* ═══ PRİMNET DETAY MODALI ══════════════════════════════════ */}
      {selectedHybridPos && primnetConfig && (
        <PrimnetDetail
          position={selectedHybridPos}
          primnetConfig={primnetConfig}
          onClose={() => setSelectedHybridPos(null)}
        />
      )}

      <ConfirmModal
        open={errorModal != null}
        title={errorModal?.title || 'Hata'}
        message={errorModal?.message || ''}
        variant="danger"
        confirmLabel="Tamam"
        onConfirm={() => setErrorModal(null)}
        onCancel={() => setErrorModal(null)}
      />
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════════
//  ALT BİLEŞENLER
// ═══════════════════════════════════════════════════════════════════

const AccountItem = React.memo(function AccountItem({ label, value, cls }) {
  return (
    <div className="dash-account-item">
      <span className="dash-account-label">{label}</span>
      <span className={`dash-account-value ${cls || ''}`}>
        {value} <span className="dash-account-suffix">TRY</span>
      </span>
    </div>
  );
});


const StatCard = React.memo(function StatCard({ label, sublabel, value, total, detail, icon, color }) {
  return (
    <div className="dash-stat-card">
      <div className="dash-stat-top">
        <span className="dash-stat-icon">{icon}</span>
        <span className="dash-stat-label">{label}</span>
      </div>
      <div className="dash-stat-value" style={color ? { color } : undefined}>
        {value}
      </div>
      {sublabel && total != null && (
        <div className="dash-stat-sub">
          {sublabel} — Toplam: {total}
        </div>
      )}
      {detail && (
        <div className="dash-stat-sub">{detail}</div>
      )}
    </div>
  );
});
