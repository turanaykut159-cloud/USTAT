/**
 * ÜSTAT v5.2 — System Monitor bileşeni.
 *
 * Eski: SystemHealth + SystemLog → Yeni: tek Monitor sayfası.
 * Tüm modüllerin durumu, emir akışı, log, performans, risk panelleri.
 *
 * Veri kaynakları:
 *   getHealth()    → cycle, mt5, orders, layers, recent_events, system
 *   getStatus()    → engine_running, mt5_connected, kill_switch_level
 *   getRisk()      → drawdown, kill_switch, can_trade
 *   getAccount()   → daily_pnl, balance, equity
 *   getPositions() → count, positions[]
 *   getEvents()    → son olaylar (log akışı)
 *
 * Poll: 3sn  |  Saat + VİOP: 1sn
 */

import { useState, useEffect } from 'react';
import {
  getHealth,
  getStatus,
  getRisk,
  getAccount,
  getPositions,
  getEvents,
} from '../services/api';
import { formatMoney } from '../utils/formatters';

// ── Renk paleti (modül bazlı) ────────────────────────────────────
const COLORS = {
  baba: '#e74c3c',
  ogul: '#f39c12',
  ustat: '#4a9eff',
  hengine: '#00d4aa',
  manuel: '#ff6b9d',
  hibrit: '#a855f7',
  mt5: '#7c4dff',
};

const POLL_MS = 3000;

// ── Yardımcı bileşenler ──────────────────────────────────────────

function Badge({ status }) {
  const colors = { ok: '#2ecc71', warn: '#f39c12', err: '#e74c3c' };
  return (
    <span
      style={{
        display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
        background: colors[status] || '#2ecc71',
        animation: status !== 'ok' ? 'mnPulse 1s infinite' : 'none',
        flexShrink: 0,
      }}
    />
  );
}

function StatCard({ label, value, sub, color }) {
  return (
    <div style={{
      background: '#0d1220', border: '1px solid #1a2540', borderRadius: 8,
      padding: '11px 13px', position: 'relative', overflow: 'hidden',
    }}>
      <div style={{ position: 'absolute', top: 0, left: 0, width: 3, height: '100%', background: color }} />
      <div style={{ fontSize: 8, letterSpacing: 3, color: '#3a5070', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 'bold', color }}>{value}</div>
      <div style={{ fontSize: 8, color: '#3a5070', marginTop: 2 }}>{sub}</div>
    </div>
  );
}

function ModBox({ name, role, color, status, metric, metricLabel, details, fill }) {
  const [hov, setHov] = useState(false);
  return (
    <div
      style={{
        width: 128, background: '#111828', border: `1.5px solid ${color}`,
        borderRadius: 10, padding: '12px 10px 10px', position: 'relative',
        boxShadow: `0 0 18px -6px ${color}`, cursor: 'pointer',
        transform: hov ? 'translateY(-3px)' : 'none', transition: 'transform 0.2s',
      }}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
    >
      <div style={{ position: 'absolute', top: -1, left: 8, right: 8, height: 2, background: color, borderRadius: 2, opacity: 0.6 }} />
      <div style={{ position: 'absolute', top: 7, right: 7 }}><Badge status={status} /></div>
      <div style={{ fontSize: 12, fontWeight: 'bold', color, letterSpacing: 3, textAlign: 'center', marginBottom: 2 }}>{name}</div>
      <div style={{ fontSize: 7, color: '#3a5070', letterSpacing: 2, textAlign: 'center', marginBottom: 8 }}>{role}</div>
      <div style={{ fontSize: 18, fontWeight: 'bold', color: '#e0eeff', textAlign: 'center', marginBottom: 1 }}>{metric}</div>
      <div style={{ fontSize: 7, color: '#3a5070', textAlign: 'center', letterSpacing: 1, marginBottom: 8 }}>{metricLabel}</div>
      <div style={{ borderTop: '1px solid #1a2540', paddingTop: 6, display: 'flex', flexDirection: 'column', gap: 3 }}>
        {details.map(([k, v, vc], i) => (
          <div key={i} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 8, color: '#4a6080' }}>
            <span>{k}</span><span style={{ color: vc || '#8ab0d0' }}>{v}</span>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 7, height: 3, background: '#1a2540', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{ width: `${fill}%`, height: '100%', background: color, borderRadius: 2 }} />
      </div>
    </div>
  );
}

function Arrow({ c1, c2, label }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 50, flexShrink: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', width: '100%' }}>
        <div style={{ flex: 1, height: 2, background: `linear-gradient(90deg,${c1},${c2})`, position: 'relative', overflow: 'hidden' }}>
          <div style={{ position: 'absolute', top: 0, left: '-40%', width: '40%', height: '100%', background: 'linear-gradient(90deg,transparent,rgba(255,255,255,0.7),transparent)', animation: 'mnFlowH 2s linear infinite' }} />
        </div>
        <div style={{ width: 0, height: 0, borderTop: '5px solid transparent', borderBottom: '5px solid transparent', borderLeft: `7px solid ${c2}` }} />
      </div>
      <div style={{ fontSize: 7, color: '#2a3a55', letterSpacing: 1, marginTop: 3 }}>{label}</div>
    </div>
  );
}

function ResponseBar({ label, value, max, color }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 8, color: '#3a5070', marginBottom: 3 }}>
        <span>{label}</span><span style={{ color }}>{value}ms</span>
      </div>
      <div style={{ height: 4, background: '#1a2540', borderRadius: 2, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 2, transition: 'width 0.5s' }} />
      </div>
    </div>
  );
}

// ── Ana bileşen ──────────────────────────────────────────────────

export default function Monitor() {
  // ── API state ────────────────────────────────────────────────
  const [health, setHealth] = useState(null);
  const [status, setStatus] = useState(null);
  const [risk, setRisk] = useState(null);
  const [account, setAccount] = useState(null);
  const [positions, setPositions] = useState(null);
  const [events, setEvents] = useState([]);

  // ── Frontend state ───────────────────────────────────────────
  const [time, setTime] = useState('');
  const [marketStatus, setMarketStatus] = useState('KAPALI');

  // ── 3sn API poll ─────────────────────────────────────────────
  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const [h, s, r, a, p, e] = await Promise.all([
          getHealth(),
          getStatus(),
          getRisk(),
          getAccount(),
          getPositions(),
          getEvents({ limit: 20 }),
        ]);
        if (!active) return;
        setHealth(h);
        setStatus(s);
        setRisk(r);
        setAccount(a);
        setPositions(p);
        setEvents(e.events || []);
      } catch (err) {
        console.error('[Monitor] Poll hatası:', err);
      }
    };
    poll();
    const id = setInterval(poll, POLL_MS);
    return () => { active = false; clearInterval(id); };
  }, []);

  // ── 1sn saat + VİOP durumu ───────────────────────────────────
  useEffect(() => {
    const tick = () => {
      const n = new Date();
      const h = n.getHours(), m = n.getMinutes(), s = n.getSeconds();
      setTime([h, m, s].map(x => String(x).padStart(2, '0')).join(':'));
      // VİOP Vadeli İşlem seansı: 09:30 – 18:15
      const mins = h * 60 + m;
      setMarketStatus(mins >= 570 && mins < 1095 ? 'AÇIK' : 'KAPALI');
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  // ── Türetilmiş veriler ───────────────────────────────────────
  const cycle = health?.cycle || {};
  const mt5 = health?.mt5 || {};
  const orders = health?.orders || {};
  const layers = health?.layers || {};
  const sysInfo = health?.system || {};
  const lastCycle = cycle?.last_cycle;
  const steps = lastCycle?.steps || {};

  const engineRunning = status?.engine_running ?? false;
  const mt5Connected = status?.mt5_connected ?? false;
  const killLevel = Math.max(status?.kill_switch_level ?? 0, risk?.kill_switch_level ?? 0);

  const dailyPnl = account?.daily_pnl ?? 0;
  const posCount = positions?.count ?? 0;
  const posList = positions?.positions || [];
  const posSymbols = posList
    .slice(0, 3)
    .map(p => (p.symbol || '').replace('F_', '').replace(/\d{4}$/, ''))
    .join(' · ') + (posList.length > 3 ? ' …' : '');

  const ddPct = ((risk?.daily_drawdown_pct ?? 0) * 100).toFixed(1);
  const ddLimit = ((risk?.max_daily_loss ?? 0.018) * 100).toFixed(1);
  const mt5Ping = mt5?.last_ping_ms ?? 0;
  const cycleAvg = cycle?.avg_ms ?? 0;
  const uptimeSec = sysInfo?.engine_uptime_seconds ?? status?.uptime_seconds ?? 0;

  // ── Modül hata sayacı (event'lerden) ──────────────────────────
  const errorCounts = { baba: 0, ogul: 0, ustat: 0, hengine: 0, manuel: 0, hibrit: 0 };
  (health?.recent_events || []).forEach(ev => {
    if (ev.severity === 'ERROR' || ev.severity === 'CRITICAL') {
      const msg = (ev.message || '').toLowerCase();
      if (msg.includes('baba')) errorCounts.baba++;
      else if (msg.includes('ogul') || msg.includes('oğul')) errorCounts.ogul++;
      else if (msg.includes('ustat') || msg.includes('üstat')) errorCounts.ustat++;
      else if (msg.includes('h-engine') || msg.includes('h_engine')) errorCounts.hengine++;
      else if (msg.includes('manuel') || msg.includes('manual')) errorCounts.manuel++;
      else if (msg.includes('hibrit') || msg.includes('hybrid')) errorCounts.hibrit++;
    }
  });

  // ── Modül durumları ──────────────────────────────────────────
  const modStatus = {
    baba: killLevel >= 3 ? 'err' : killLevel > 0 ? 'warn' : 'ok',
    ogul: layers?.ogul?.daily_loss_stop ? 'err' : 'ok',
    ustat: sysInfo?.cache_stale ? 'warn' : 'ok',
    hengine: (layers?.h_engine?.active_hybrid_count ?? 0) > 0 ? 'warn' : 'ok',
    manuel: 'ok',
    hibrit: 'ok',
  };

  // ── Yardımcı fonksiyonlar ────────────────────────────────────
  const fmtUptime = (sec) => {
    if (!sec || sec <= 0) return '—';
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    if (h > 0) return `${h}s ${m}dk`;
    return `${m}dk`;
  };

  const fmtTime = (ts) => {
    if (!ts) return '--:--:--';
    try {
      const d = new Date(ts);
      if (isNaN(d.getTime())) return '--:--:--';
      return [d.getHours(), d.getMinutes(), d.getSeconds()]
        .map(x => String(x).padStart(2, '0')).join(':');
    } catch { return '--:--:--'; }
  };

  const fmtTimestamp = (unixTs) => {
    if (!unixTs) return '--:--:--';
    try {
      const d = new Date(unixTs * 1000);
      return [d.getHours(), d.getMinutes(), d.getSeconds()]
        .map(x => String(x).padStart(2, '0')).join(':');
    } catch { return '--:--:--'; }
  };

  const sevToType = (sev) => {
    switch (sev) {
      case 'CRITICAL': case 'ERROR': return 'error';
      case 'WARNING': return 'warn';
      case 'INFO': return 'info';
      default: return 'ok';
    }
  };

  const logColor = { ok: '#2ecc71', info: '#4a9eff', warn: '#f39c12', error: '#e74c3c' };
  const mktColor = { 'AÇIK': '#2ecc71', 'KAPALI': '#e74c3c' };

  // ── Emir listesi ─────────────────────────────────────────────
  const last10 = orders?.last_10 || [];

  // ── Risk Drawdown hesaplamaları ──────────────────────────────
  const ddDaily = (risk?.daily_drawdown_pct ?? 0) * 100;
  const ddWeekly = (risk?.weekly_drawdown_pct ?? 0) * 100;
  const limDaily = (risk?.max_daily_loss ?? 0.018) * 100;
  const limWeekly = (risk?.max_weekly_loss ?? 0.04) * 100;
  const floatingPnl = risk?.floating_pnl ?? 0;
  const floatingLimit = (risk?.equity || 1) * (risk?.max_floating_loss || 0.015);
  const floatingPct = floatingLimit > 0 ? Math.min(Math.abs(floatingPnl) / floatingLimit * 100, 100) : 0;

  // Kill-switch level thresholds (yaklaşık hesaplama)
  const ksLevels = [
    { lvl: 'L1', label: 'UYARI', pct: (limDaily * 0.5).toFixed(1) },
    { lvl: 'L2', label: 'DURDUR', pct: (limDaily * 0.75).toFixed(1) },
    { lvl: 'L3', label: 'KRİTİK', pct: limDaily.toFixed(1) },
  ];

  // ═════════════════════════════════════════════════════════════
  // RENDER
  // ═════════════════════════════════════════════════════════════

  return (
    <div className="mn-page">
      <style>{`
        @keyframes mnPulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:0.3;transform:scale(0.8)} }
        @keyframes mnFlowH { 0%{left:-40%} 100%{left:100%} }
        @keyframes mnFlowV { 0%{top:-40%} 100%{top:100%} }
        .mn-page::-webkit-scrollbar{width:3px}
        .mn-page::-webkit-scrollbar-thumb{background:#1a2540;border-radius:2px}
      `}</style>

      {/* ═══ [A] HEADER ══════════════════════════════════════════ */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: 16, paddingBottom: 12, borderBottom: '1px solid #1a2540',
      }}>
        <div>
          <div style={{ fontSize: 14, letterSpacing: 5, color: '#4a9eff', fontWeight: 'bold' }}>
            ÜSTAT · System Monitor
          </div>
          <div style={{ fontSize: 8, color: '#3a5070', letterSpacing: 3, marginTop: 2 }}>
            VİOP ALGORİTMİK TİCARET SİSTEMİ
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10, color: mktColor[marketStatus], letterSpacing: 2 }}>
            <span style={{
              width: 7, height: 7, borderRadius: '50%', background: mktColor[marketStatus],
              display: 'inline-block', animation: marketStatus === 'AÇIK' ? 'mnPulse 2s infinite' : 'none',
            }} />
            VİOP {marketStatus}
          </div>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 6, fontSize: 10,
            color: engineRunning ? '#2ecc71' : '#e74c3c', letterSpacing: 2,
          }}>
            <span style={{
              width: 7, height: 7, borderRadius: '50%',
              background: engineRunning ? '#2ecc71' : '#e74c3c',
              display: 'inline-block', animation: engineRunning ? 'mnPulse 1.8s infinite' : 'none',
            }} />
            SİSTEM {engineRunning ? 'AKTİF' : 'PASİF'}
          </div>
          {killLevel > 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 10, color: '#e74c3c', letterSpacing: 2, fontWeight: 'bold' }}>
              ⛔ KILL-SWITCH L{killLevel}
            </div>
          )}
          <div style={{ fontSize: 11, color: '#3a5880', letterSpacing: 2 }}>{time}</div>
        </div>
      </div>

      {/* ═══ [B] STATS BAR ═══════════════════════════════════════ */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6,1fr)', gap: 8, marginBottom: 16 }}>
        <StatCard
          label="GÜNLÜK P&L"
          value={dailyPnl >= 0 ? `+${formatMoney(dailyPnl)}` : formatMoney(dailyPnl)}
          sub="TL · bugün"
          color={dailyPnl >= 0 ? '#2ecc71' : '#e74c3c'}
        />
        <StatCard
          label="AKTİF POZİSYON"
          value={String(posCount)}
          sub={posSymbols || '—'}
          color="#4a9eff"
        />
        <StatCard
          label="DRAWDOWN"
          value={`%${ddPct}`}
          sub={`limit %${ddLimit}`}
          color={parseFloat(ddPct) > parseFloat(ddLimit) * 0.5 ? '#f39c12' : '#2ecc71'}
        />
        <StatCard
          label="MT5 PİNG"
          value={`${mt5Ping}ms`}
          sub={mt5Connected ? 'GCM · bağlı' : 'bağlantı yok'}
          color={mt5Connected ? '#7c4dff' : '#e74c3c'}
        />
        <StatCard
          label="DÖNGÜ SÜRESİ"
          value={`${cycleAvg}ms`}
          sub="ortalama döngü"
          color={cycleAvg > 50 ? '#e74c3c' : '#00d4aa'}
        />
        <StatCard
          label="UPTIME"
          value={fmtUptime(uptimeSec)}
          sub={`${sysInfo?.cycle_count ?? 0} döngü`}
          color="#00d4aa"
        />
      </div>

      {/* ═══ [C] FLOW DIAGRAM ════════════════════════════════════ */}
      <div style={{
        background: '#0d1220', border: '1px solid #1a2540', borderRadius: 10,
        padding: '26px 28px 20px', marginBottom: 14, position: 'relative',
      }}>
        <div style={{ position: 'absolute', top: 9, left: 16, fontSize: 8, letterSpacing: 3, color: '#253550' }}>
          MODÜL MİMARİSİ · CANLI DURUM
        </div>

        {/* MT5 kutusu (üst) */}
        <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 0 }}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <div style={{
              background: '#111828', border: `1.5px solid ${COLORS.mt5}`, borderRadius: 10,
              padding: '9px 28px', boxShadow: `0 0 16px -6px ${COLORS.mt5}`,
              minWidth: 260, textAlign: 'center',
            }}>
              <div style={{ fontSize: 11, fontWeight: 'bold', color: COLORS.mt5, letterSpacing: 3, marginBottom: 2 }}>
                MT5 · GCM MENKUL
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-around', marginTop: 4 }}>
                {[
                  ['BAĞLANTI', mt5Connected ? '✓ CANLI' : '✗ KOPUK', mt5Connected ? '#2ecc71' : '#e74c3c'],
                  ['PİNG', `${mt5Ping}ms`, '#9a80ff'],
                  ['KOPMA', `${mt5?.disconnect_count ?? 0}`, '#9a80ff'],
                  ['UPTIME', fmtUptime(mt5?.mt5_uptime_seconds ?? 0), '#9a80ff'],
                ].map(([k, v, c], i) => (
                  <div key={i} style={{ fontSize: 8, color: '#4a6080', textAlign: 'center' }}>
                    <div style={{ color: '#2a3a55', marginBottom: 2 }}>{k}</div>
                    <div style={{ color: c }}>{v}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* MT5'ten aşağı 3 ok */}
            <div style={{ display: 'flex', gap: 80, marginTop: 0 }}>
              {[['OĞUL', COLORS.ogul], ['MANUEL', COLORS.manuel], ['HİBRİT', COLORS.hibrit]].map(([lbl, c]) => (
                <div key={lbl} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                  <div style={{
                    width: 2, height: 22,
                    background: `linear-gradient(180deg,${COLORS.mt5},${c})`,
                    position: 'relative', overflow: 'hidden',
                  }}>
                    <div style={{
                      position: 'absolute', left: 0, top: '-40%', width: '100%', height: '40%',
                      background: 'linear-gradient(180deg,transparent,rgba(255,255,255,0.5),transparent)',
                      animation: 'mnFlowV 1.5s linear infinite',
                    }} />
                  </div>
                  <div style={{ width: 0, height: 0, borderLeft: '4px solid transparent', borderRight: '4px solid transparent', borderTop: `6px solid ${c}` }} />
                  <div style={{ fontSize: 7, color: '#2a3a55', letterSpacing: 1, marginTop: 2 }}>{lbl}</div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Modül sırası */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', marginTop: 4 }}>
          <ModBox
            name="BABA" role="RİSK YÖNETİMİ" color={COLORS.baba}
            status={modStatus.baba}
            metric={`L${killLevel}`} metricLabel="KİLL-SWİTCH"
            details={[
              ['BLOKE', `${(layers?.baba?.killed_symbols || []).length} sembol`],
              ['DD LİMİT', `%${ddLimit}`],
              ['HATA', `${errorCounts.baba} bugün`, errorCounts.baba > 0 ? '#f39c12' : undefined],
            ]}
            fill={Math.min(killLevel * 33, 100)}
          />
          <Arrow c1={COLORS.baba} c2={COLORS.ogul} label="ONAY" />

          <ModBox
            name="OĞUL" role="SİNYAL YÜRÜTME" color={COLORS.ogul}
            status={modStatus.ogul}
            metric={String(layers?.ogul?.active_trade_count ?? 0)} metricLabel="AKTİF İŞLEM"
            details={[
              ['SEMBOLLER', `${(layers?.ogul?.active_symbols || []).length} adet`],
              ['KAYIP STOP', layers?.ogul?.daily_loss_stop ? 'AKTİF' : 'KAPALI', layers?.ogul?.daily_loss_stop ? '#e74c3c' : undefined],
              ['HATA', `${errorCounts.ogul} bugün`, errorCounts.ogul > 0 ? '#f39c12' : undefined],
            ]}
            fill={Math.min((layers?.ogul?.active_trade_count ?? 0) * 20, 100)}
          />
          <Arrow c1={COLORS.ogul} c2={COLORS.ustat} label="KONTRAT" />

          <ModBox
            name="ÜSTAT" role="KONTRAT SEÇİMİ" color={COLORS.ustat}
            status={modStatus.ustat}
            metric={sysInfo?.cache_stale ? '⚠' : '✓'} metricLabel="CACHE DURUMU"
            details={[
              ['SON ÇALIŞMA', layers?.ustat?.last_run_time || '—'],
              ['DB BOYUT', `${sysInfo?.db_file_size_mb ?? 0} MB`],
              ['HATA', `${errorCounts.ustat} bugün`, errorCounts.ustat > 0 ? '#f39c12' : undefined],
            ]}
            fill={sysInfo?.cache_stale ? 30 : 90}
          />
          <Arrow c1={COLORS.ustat} c2={COLORS.hengine} label="H-SYNC" />

          <ModBox
            name="H-ENGINE" role="HYBRID MOD" color={COLORS.hengine}
            status={modStatus.hengine}
            metric={String(layers?.h_engine?.active_hybrid_count ?? 0)} metricLabel="HİBRİT POZ."
            details={[
              ['GÜNLÜK P&L', `${layers?.h_engine?.daily_pnl ?? 0} TL`],
              ['LİMİT', `${layers?.h_engine?.daily_limit ?? 0} TL`],
              ['HATA', `${errorCounts.hengine} bugün`, errorCounts.hengine > 0 ? '#f39c12' : undefined],
            ]}
            fill={layers?.h_engine?.daily_limit
              ? Math.min(Math.abs(layers?.h_engine?.daily_pnl ?? 0) / layers.h_engine.daily_limit * 100, 100)
              : 0}
          />
          <Arrow c1={COLORS.hengine} c2={COLORS.manuel} label="SYNC" />

          <ModBox
            name="MANUEL" role="MANUEL MOTOR" color={COLORS.manuel}
            status={modStatus.manuel}
            metric={String(risk?.daily_trade_count ?? 0)} metricLabel="GÜNLÜK EMİR"
            details={[
              ['MAKSİMUM', `${risk?.max_daily_trades ?? 5} emir`],
              ['ARD. KAYIP', `${risk?.consecutive_losses ?? 0}/${risk?.consecutive_loss_limit ?? 3}`],
              ['HATA', `${errorCounts.manuel} bugün`, errorCounts.manuel > 0 ? '#f39c12' : undefined],
            ]}
            fill={risk?.max_daily_trades
              ? Math.min((risk?.daily_trade_count ?? 0) / risk.max_daily_trades * 100, 100)
              : 0}
          />
          <Arrow c1={COLORS.manuel} c2={COLORS.hibrit} label="SYNC" />

          <ModBox
            name="HİBRİT" role="HİBRİT MOTOR" color={COLORS.hibrit}
            status={modStatus.hibrit}
            metric={String(orders?.success_count ?? 0)} metricLabel="BAŞARILI EMİR"
            details={[
              ['RED', `${orders?.reject_count ?? 0}`],
              ['TIMEOUT', `${orders?.timeout_count ?? 0}`],
              ['HATA', `${errorCounts.hibrit} bugün`, errorCounts.hibrit > 0 ? '#f39c12' : undefined],
            ]}
            fill={
              (orders?.success_count ?? 0) + (orders?.reject_count ?? 0) + (orders?.timeout_count ?? 0) > 0
                ? Math.min((orders.success_count / ((orders.success_count ?? 0) + (orders.reject_count ?? 0) + (orders.timeout_count ?? 0))) * 100, 100)
                : 0
            }
          />
        </div>
      </div>

      {/* ═══ [D] EMİR AKIŞ TABLOSU ══════════════════════════════ */}
      <div style={{
        background: '#0d1220', border: '1px solid #1a2540', borderRadius: 10,
        padding: '14px 16px', marginBottom: 14,
      }}>
        <div style={{ fontSize: 8, letterSpacing: 3, color: '#253550', marginBottom: 10 }}>
          EMİR AKIŞ TABLOSU · SON {last10.length} EMİR
        </div>
        <div style={{
          display: 'grid', gridTemplateColumns: '70px 140px 60px 70px 65px 65px',
          gap: '0 8px', fontSize: 8, color: '#2a3a55', letterSpacing: 1,
          marginBottom: 6, paddingBottom: 6, borderBottom: '1px solid #1a2540',
        }}>
          {['ZAMAN', 'KONTRAT', 'YÖN', 'DURUM', 'SÜRESİ', 'KAYMA'].map(h => <div key={h}>{h}</div>)}
        </div>
        <div style={{ maxHeight: 160, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 4 }}>
          {last10.length === 0 && (
            <div style={{ fontSize: 9, color: '#2a3a55', textAlign: 'center', padding: 16 }}>Henüz emir yok</div>
          )}
          {last10.map((o, i) => {
            const dir = o.direction === 'BUY' || o.direction === 'LONG' ? 'LONG' : 'SHORT';
            const mt5St = o.success ? 'FILLED' : o.retcode === -1 ? 'TIMEOUT' : 'RED';
            return (
              <div key={i} style={{
                display: 'grid', gridTemplateColumns: '70px 140px 60px 70px 65px 65px',
                gap: '0 8px', fontSize: 9, padding: '4px 0', borderBottom: '1px solid #0f1828',
              }}>
                <div style={{ color: '#3a5070' }}>{fmtTimestamp(o.timestamp)}</div>
                <div style={{ color: '#8ab0d0' }}>{o.symbol}</div>
                <div style={{ color: dir === 'LONG' ? '#2ecc71' : '#e74c3c', fontWeight: 'bold' }}>{dir}</div>
                <div style={{ color: o.success ? '#2ecc71' : '#e74c3c' }}>{mt5St}</div>
                <div style={{ color: o.duration_ms > 50 ? '#f39c12' : '#4a6080' }}>{o.duration_ms}ms</div>
                <div style={{ color: Math.abs(o.slippage ?? 0) > 0 ? '#f39c12' : '#4a6080' }}>{(o.slippage ?? 0).toFixed(4)}</div>
              </div>
            );
          })}
        </div>
      </div>

      {/* ═══ [E] ALT 3'LÜ GRID ══════════════════════════════════ */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>

        {/* ── [E1] LOG AKIŞI ──────────────────────────────────── */}
        <div style={{ background: '#0d1220', border: '1px solid #1a2540', borderRadius: 10, padding: '14px 14px 10px' }}>
          <div style={{ fontSize: 8, letterSpacing: 3, color: '#253550', marginBottom: 10 }}>SİSTEM LOG AKIŞI</div>
          <div style={{ height: 200, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 3 }}>
            {events.length === 0 && (
              <div style={{ fontSize: 9, color: '#2a3a55', textAlign: 'center', padding: 16 }}>Olay yok</div>
            )}
            {events.map((ev, i) => {
              const t = sevToType(ev.severity);
              return (
                <div
                  key={ev.id || i}
                  style={{
                    fontSize: 9, display: 'flex', gap: 8, padding: '3px 5px', borderRadius: 3,
                    color: logColor[t],
                    background: t === 'warn' ? 'rgba(243,156,18,0.05)' : t === 'error' ? 'rgba(231,76,60,0.07)' : 'transparent',
                  }}
                >
                  <span style={{ color: '#2a3a55', flexShrink: 0 }}>{fmtTime(ev.timestamp)}</span>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ev.message}</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* ── [E2] PERFORMANS ─────────────────────────────────── */}
        <div style={{ background: '#0d1220', border: '1px solid #1a2540', borderRadius: 10, padding: '14px 14px 10px' }}>
          <div style={{ fontSize: 8, letterSpacing: 3, color: '#253550', marginBottom: 12 }}>PERFORMANS · DÖNGÜ ADIMLARI</div>
          <ResponseBar label="BABA DÖNGÜ" value={steps.baba_cycle ?? 0} max={50} color={COLORS.baba} />
          <ResponseBar label="OĞUL SİNYAL" value={steps.ogul_signals ?? 0} max={100} color={COLORS.ogul} />
          <ResponseBar label="ÜSTAT BEYİN" value={steps.ustat_brain ?? 0} max={50} color={COLORS.ustat} />
          <ResponseBar label="H-ENGINE" value={steps.h_engine ?? 0} max={50} color={COLORS.hengine} />
          <ResponseBar label="VERİ GÜNCELLEME" value={steps.data_update ?? 0} max={100} color="#8ab0d0" />
          <ResponseBar label="TOPLAM DÖNGÜ" value={lastCycle?.total_ms ?? 0} max={300} color="#00d4aa" />

          <div style={{ marginTop: 10, fontSize: 8, letterSpacing: 3, color: '#253550', marginBottom: 8 }}>DÖNGÜ İSTATİSTİK</div>
          <div style={{ display: 'flex', gap: 8 }}>
            {[
              ['ORT', `${cycle?.avg_ms ?? 0}ms`, '#8ab0d0'],
              ['MAX', `${cycle?.max_ms ?? 0}ms`, (cycle?.max_ms ?? 0) > 100 ? '#f39c12' : '#8ab0d0'],
              ['AŞIM', `${cycle?.overrun_count ?? 0}`, (cycle?.overrun_count ?? 0) > 0 ? '#e74c3c' : '#2ecc71'],
            ].map(([k, v, c]) => (
              <div key={k} style={{ flex: 1, background: '#0a0e18', borderRadius: 4, padding: '5px 6px', textAlign: 'center' }}>
                <div style={{ fontSize: 12, fontWeight: 'bold', color: c }}>{v}</div>
                <div style={{ fontSize: 7, color: '#2a3a55', letterSpacing: 1 }}>{k}</div>
              </div>
            ))}
          </div>
        </div>

        {/* ── [E3] RISK & KILL-SWITCH ─────────────────────────── */}
        <div style={{ background: '#0d1220', border: '1px solid #1a2540', borderRadius: 10, padding: '14px 14px 10px' }}>
          <div style={{ fontSize: 8, letterSpacing: 3, color: '#253550', marginBottom: 10 }}>RİSK & KİLL-SWİTCH</div>

          {/* Kill-switch seviyeleri */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
            {ksLevels.map(({ lvl, label, pct }) => {
              const lvlNum = parseInt(lvl.slice(1));
              const active = killLevel >= lvlNum;
              return (
                <div
                  key={lvl}
                  style={{
                    flex: 1,
                    background: active ? 'rgba(231,76,60,0.15)' : '#0a0e18',
                    border: `1px solid ${active ? '#e74c3c' : '#1a2540'}`,
                    borderRadius: 6, padding: '8px 6px', textAlign: 'center',
                  }}
                >
                  <div style={{ fontSize: 16, fontWeight: 'bold', color: active ? '#e74c3c' : '#2a3a55', marginBottom: 2 }}>{lvl}</div>
                  <div style={{ fontSize: 7, color: '#3a5070', letterSpacing: 1 }}>{label}</div>
                  <div style={{ fontSize: 8, color: '#1e3050', marginTop: 2 }}>%{pct}</div>
                </div>
              );
            })}
          </div>

          {/* Drawdown barları */}
          {[
            ['GÜNLÜK DD', `%${ddDaily.toFixed(1)} / %${limDaily.toFixed(1)}`, limDaily > 0 ? (ddDaily / limDaily) * 100 : 0, ddDaily > limDaily * 0.5 ? '#f39c12' : '#2ecc71'],
            ['HAFTALIK DD', `%${ddWeekly.toFixed(1)} / %${limWeekly.toFixed(1)}`, limWeekly > 0 ? (ddWeekly / limWeekly) * 100 : 0, ddWeekly > limWeekly * 0.5 ? '#f39c12' : '#2ecc71'],
            ['FLOATING P&L', `${floatingPnl.toFixed(0)} TL`, floatingPct, floatingPnl < 0 ? '#e74c3c' : '#2ecc71'],
          ].map(([lbl, val, pct, clr], i) => (
            <div key={i}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 8, color: '#3a5070', marginBottom: 3 }}>
                <span>{lbl}</span><span>{val}</span>
              </div>
              <div style={{ height: 4, background: '#1a2540', borderRadius: 2, overflow: 'hidden', marginBottom: 7 }}>
                <div style={{ width: `${Math.min(pct, 100)}%`, height: '100%', background: clr, borderRadius: 2 }} />
              </div>
            </div>
          ))}

          {/* Modül hata sayacı */}
          <div style={{ fontSize: 8, letterSpacing: 3, color: '#253550', marginBottom: 8, marginTop: 4 }}>HATA SAYACI · BUGÜN</div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 5 }}>
            {Object.entries(errorCounts).map(([mod, cnt]) => (
              <div key={mod} style={{ background: '#0a0e18', borderRadius: 4, padding: '5px 6px', textAlign: 'center' }}>
                <div style={{ fontSize: 14, fontWeight: 'bold', color: cnt > 0 ? '#f39c12' : '#2a3a55' }}>{cnt}</div>
                <div style={{ fontSize: 7, color: '#2a3a55', letterSpacing: 1 }}>{mod.toUpperCase()}</div>
              </div>
            ))}
          </div>
        </div>

      </div>
    </div>
  );
}
