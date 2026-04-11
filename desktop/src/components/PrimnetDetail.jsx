/**
 * PRİMNET Pozisyon Detay Modalı — v5.9
 *
 * Hibrit pozisyona tıklandığında açılır.
 * -10'dan +10'a kadar tüm prim kademelerini gösteren dinamik tablo.
 * Sabit 1.5 prim trailing, kilitli kâr (stop > giriş olduğunda), açıklama kolonu.
 */

import React, { useMemo, useRef, useEffect } from 'react';

// ── Prim hesaplamaları ─────────────────────────────────────────

function priceToPrim(price, refPrice) {
  const onePrim = refPrice * 0.01;
  if (onePrim <= 0) return 0;
  return (price - refPrice) / onePrim;
}

function primToPrice(prim, refPrice) {
  return refPrice + prim * (refPrice * 0.01);
}

function fmtPrim(val) {
  if (val == null || isNaN(val)) return '—';
  const sign = val > 0 ? '+' : '';
  return `${sign}${val.toFixed(1)}`;
}

function fmtPrice(val) {
  if (val == null || isNaN(val) || val === 0) return '—';
  return val.toFixed(2);
}

function fmtMoney(val) {
  if (val == null || isNaN(val)) return '—';
  return `${val >= 0 ? '+' : ''}${val.toFixed(0)}`;
}

function fmtMoneyFull(val) {
  if (val == null || isNaN(val)) return '—';
  return `${val >= 0 ? '+' : ''}${val.toFixed(0)} TL`;
}

// ── Açıklama metni üretici ────────────────────────────────────

function buildExplanation(row, data, cfg) {
  const { prim, statusClass, isEntry, isStop, isTarget } = row;
  const { entryPrim } = data;
  const dir = data.direction;
  const trail = cfg.trailing_prim;

  if (statusClass === 'unreachable') {
    return `+${cfg.target_prim} hedefinde kapatıldı, buraya ulaşılamaz`;
  }
  if (isTarget || statusClass === 'target') {
    return `HEDEF +${cfg.target_prim} → İŞLEMİ KAPAT`;
  }
  if (statusClass === 'locked') {
    const stopPrim = dir === 'BUY'
      ? prim - trail
      : prim + trail;
    const lockedPrim = dir === 'BUY'
      ? stopPrim - entryPrim
      : entryPrim - stopPrim;
    return `Stop ${fmtPrim(stopPrim)} > Giriş → ${lockedPrim.toFixed(1)} prim kâr kilitli`;
  }
  if (statusClass === 'breakeven') {
    const stopPrim = dir === 'BUY'
      ? prim - trail
      : prim + trail;
    return `Stop ${fmtPrim(stopPrim)} = Giriş → Başabaş`;
  }
  if (statusClass === 'trailing') {
    const stopPrim = dir === 'BUY'
      ? prim - trail
      : prim + trail;
    return `Stop ${fmtPrim(stopPrim)} < Giriş → Kilitli kâr yok`;
  }
  if (isEntry) {
    return `Pozisyon açıldı. Stop: ${fmtPrim(entryPrim - trail)} (-${trail} prim)`;
  }
  if (statusClass === 'open') {
    return `Zararda. Stop ${fmtPrim(entryPrim - trail)}'da`;
  }
  if (isStop || statusClass === 'stop') {
    return 'ZARAR DURDUR tetiklendi → KAPAT';
  }
  if (statusClass === 'outside') {
    return 'Stop tetiklenmiş, pozisyon kapalı';
  }
  return '';
}

// ── Prim merdiveni satırları ──────────────────────────────────

function buildLadder(pos, cfg) {
  const ref = pos.reference_price;
  if (!ref || ref <= 0) return null;

  const dir = pos.direction;
  const entryPrim = priceToPrim(pos.entry_price, ref);
  const currentPrim = priceToPrim(pos.current_price, ref);
  const slPrim = priceToPrim(pos.current_sl, ref);
  const tpPrim = priceToPrim(pos.current_tp, ref);
  const onePrimTL = ref * 0.01 * pos.volume * 100; // 1 prim = TL

  const profitPrim = dir === 'BUY'
    ? currentPrim - entryPrim
    : entryPrim - currentPrim;

  // Trailing mesafe SABİT (faz ayrımı yok)
  const trailingDist = cfg.trailing_prim;

  // Merdiven kademeleri:
  // 1) Tam sayılar: -10 ile +10
  // 2) Hedef kapanış: ±9.5
  // 3) Giriş primi (tam değeri, yuvarlanmadan)
  // 4) Stop primi (giriş ± trailing, tam değeri)
  // 5) Güncel fiyat (dinamik, kademeler arasına eklenir)
  const stepSet = new Set();

  // 1. Tam sayı kademeler
  for (let i = 10; i >= -10; i--) stepSet.add(i);

  // 2. Hedef kapanış yarımları
  stepSet.add(9.5); stepSet.add(-9.5);

  // 3. Giriş primi — 0.1 hassasiyetle tabloya ekle
  const entryRounded = Math.round(entryPrim * 10) / 10;
  stepSet.add(entryRounded);

  // 4. Stop primi — giriş ± trailing_prim, 0.1 hassasiyet
  const stopPrimVal = dir === 'BUY'
    ? Math.round((entryPrim - trailingDist) * 10) / 10
    : Math.round((entryPrim + trailingDist) * 10) / 10;
  stepSet.add(stopPrimVal);

  // 5. Güncel fiyatın dinamik satırı
  const currentRounded = Math.round(currentPrim * 10) / 10;
  const isOnFixedStep = [...stepSet].some(s => Math.abs(s - currentPrim) < 0.08);
  if (!isOnFixedStep && currentRounded >= -10 && currentRounded <= 10) {
    stepSet.add(currentRounded);
  }

  // 6. Güncel stop fiyatının (canlı SL) dinamik satırı
  const hasValidSl = pos.current_sl && pos.current_sl > 0 && !isNaN(slPrim);
  const slRounded = Math.round(slPrim * 10) / 10;
  const isSlOnFixedStep = hasValidSl
    ? [...stepSet].some(s => Math.abs(s - slPrim) < 0.08)
    : true;
  if (hasValidSl && !isSlOnFixedStep && slRounded >= -10 && slRounded <= 10) {
    stepSet.add(slRounded);
  }

  const steps = [...stepSet].filter(v => v >= -10 && v <= 10).sort((a, b) => b - a);

  const rows = [];
  for (const prim of steps) {
    const price = primToPrice(prim, ref);
    const pnlTL = dir === 'BUY'
      ? (prim - entryPrim) * onePrimTL
      : (entryPrim - prim) * onePrimTL;

    let status = '';
    let statusClass = '';
    let fazLabel = '';
    let lockedTL = 0;
    let stopLevel = '';

    // Giriş satırı: entryRounded kademe ile eşleşme
    const isEntry = prim === entryRounded;
    // Stop satırı: stopPrimVal kademe ile eşleşme
    const isStop = prim === stopPrimVal;
    // Güncel fiyat satırı: dinamik eklendiyse sadece o, yoksa en yakın kademe
    const isDynamicRow = !isOnFixedStep && prim === currentRounded;
    const isCurrent = isDynamicRow || (isOnFixedStep && Math.abs(prim - currentPrim) < 0.08);
    // Güncel stop satırı (CANLI SL konumu — trailing ile hareket eder)
    const isDynamicSlRow = hasValidSl && !isSlOnFixedStep && prim === slRounded;
    const isCurrentStop = hasValidSl && (
      isDynamicSlRow || (isSlOnFixedStep && Math.abs(prim - slPrim) < 0.08)
    );
    // Hedef satırı
    const isTarget = Math.abs(prim - tpPrim) < 0.25;

    if (dir === 'BUY') {
      if (prim >= cfg.target_prim) {
        if (Math.abs(prim - cfg.target_prim) < 0.25) {
          status = 'KAPAT'; statusClass = 'target'; fazLabel = 'Hedef';
        } else {
          status = 'ULAŞILAMAZ'; statusClass = 'unreachable';
        }
      } else if (prim > entryPrim && !isEntry) {
        // Kâr bölgesi — trailing SABİT
        const sp = prim - trailingDist;
        stopLevel = fmtPrim(sp);
        const locked = sp - entryPrim;
        if (Math.abs(locked) < 0.01) {
          status = 'BREAKEVEN'; statusClass = 'breakeven';
        } else if (locked > 0) {
          status = 'KÂR KİLİTLİ'; statusClass = 'locked';
          lockedTL = locked * onePrimTL;
        } else {
          status = 'TRAİLİNG'; statusClass = 'trailing';
        }
      } else if (isEntry) {
        status = 'GİRİŞ'; statusClass = 'entry';
        stopLevel = fmtPrim(entryPrim - trailingDist);
      } else if (prim < entryPrim && prim >= slPrim) {
        status = 'AÇIK'; statusClass = 'open';
      } else if (isStop || (prim < slPrim && prim >= entryPrim - trailingDist - 0.25)) {
        status = 'STOP'; statusClass = 'stop';
        stopLevel = fmtPrim(slPrim);
      } else if (prim < slPrim) {
        status = 'DIŞARDA'; statusClass = 'outside';
      }
    } else {
      // SELL
      if (prim <= -cfg.target_prim) {
        if (Math.abs(prim + cfg.target_prim) < 0.25) {
          status = 'KAPAT'; statusClass = 'target'; fazLabel = 'Hedef';
        } else {
          status = 'ULAŞILAMAZ'; statusClass = 'unreachable';
        }
      } else if (prim < entryPrim && !isEntry) {
        // Kâr bölgesi — trailing SABİT
        const sp = prim + trailingDist;
        stopLevel = fmtPrim(sp);
        const locked = entryPrim - sp;
        if (Math.abs(locked) < 0.01) {
          status = 'BREAKEVEN'; statusClass = 'breakeven';
        } else if (locked > 0) {
          status = 'KÂR KİLİTLİ'; statusClass = 'locked';
          lockedTL = locked * onePrimTL;
        } else {
          status = 'TRAİLİNG'; statusClass = 'trailing';
        }
      } else if (isEntry) {
        status = 'GİRİŞ'; statusClass = 'entry';
        stopLevel = fmtPrim(entryPrim + trailingDist);
      } else if (prim > entryPrim && prim <= slPrim) {
        status = 'AÇIK'; statusClass = 'open';
      } else if (isStop || (prim > slPrim && prim <= entryPrim + trailingDist + 0.25)) {
        status = 'STOP'; statusClass = 'stop';
        stopLevel = fmtPrim(slPrim);
      } else if (prim > slPrim) {
        status = 'DIŞARDA'; statusClass = 'outside';
      }
    }

    rows.push({
      prim, price, pnlTL, status, statusClass, fazLabel,
      lockedTL, stopLevel, isEntry, isCurrent, isStop, isCurrentStop, isTarget,
    });
  }

  return {
    rows, entryPrim, currentPrim, slPrim, tpPrim,
    profitPrim, trailingDist, onePrimTL, direction: dir,
  };
}

// ── Tavana/tabana yakınlık barı ──────────────────────────────

function ProximityBar({ currentPrim, direction, targetPrim }) {
  // -10 ile +10 arasında pozisyonu göster
  // BUY: +10'a yakınsa iyi, -10'a yakınsa kötü
  // SELL: -10'a yakınsa iyi, +10'a yakınsa kötü
  const pct = ((currentPrim + 10) / 20) * 100;
  const clamped = Math.max(0, Math.min(100, pct));

  const isBuy = direction === 'BUY';
  const profitSide = isBuy ? 'sağ (tavan)' : 'sol (taban)';
  const lossSide = isBuy ? 'sol (taban)' : 'sağ (tavan)';

  return (
    <div className="pn-proximity">
      <span className="pn-prox-label">-10</span>
      <div className="pn-prox-track">
        {/* Giriş çizgisi */}
        <div className="pn-prox-zero" style={{ left: '50%' }} />
        {/* Faz 2 bölgesi */}
        {isBuy ? (
          <div className="pn-prox-faz2" style={{
            left: `${50 + (targetPrim / 20) * 100 - 15}%`,
            width: '15%',
          }} />
        ) : (
          <div className="pn-prox-faz2" style={{
            left: `${50 - (targetPrim / 20) * 100}%`,
            width: '15%',
          }} />
        )}
        {/* Aktif pozisyon */}
        <div
          className={`pn-prox-marker ${currentPrim >= 0 ? 'pn-prox-marker--up' : 'pn-prox-marker--down'}`}
          style={{ left: `${clamped}%` }}
        />
      </div>
      <span className="pn-prox-label">+10</span>
    </div>
  );
}

// ── Ana Bileşen ────────────────────────────────────────────────

export default function PrimnetDetail({ position, primnetConfig, onClose }) {
  const currentRef = useRef(null);

  const data = useMemo(() => {
    if (!position || !primnetConfig) return null;
    return buildLadder(position, primnetConfig);
  }, [position, primnetConfig]);

  // Aktif kademeye otomatik scroll
  useEffect(() => {
    if (currentRef.current) {
      currentRef.current.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }, [data]);

  if (!position) return null;

  const pos = position;
  const cfg = primnetConfig;
  const ref = pos.reference_price;
  const hasData = data && data.rows && data.rows.length > 0;

  return (
    <div className="pn-overlay" onClick={onClose}>
      <div className="pn-modal" onClick={(e) => e.stopPropagation()}>

        {/* ── Başlık ─────────────────────────────── */}
        <div className="pn-header">
          <div className="pn-title">
            <span className="pn-header-badge">PRİMNET</span>
            <span className={`pn-dir pn-dir--${pos.direction.toLowerCase()}`}>
              {pos.direction}
            </span>
            <span className="pn-symbol">{pos.symbol}</span>
            <span className="pn-ticket">#{pos.ticket}</span>
          </div>
          <button className="pn-close" onClick={onClose}>✕</button>
        </div>

        {/* ── Üst özet kartları ──────────────────── */}
        <div className="pn-summary">
          <div className="pn-sum-card">
            <span className="pn-sum-label">Giriş Prim</span>
            <span className="pn-sum-value pn-sum-accent">
              {hasData ? fmtPrim(data.entryPrim) : '—'}
            </span>
          </div>
          <div className="pn-sum-card">
            <span className="pn-sum-label">Güncel Prim</span>
            <span className={`pn-sum-value ${hasData && data.profitPrim >= 0 ? 'pn-profit' : 'pn-loss'}`}>
              {hasData ? fmtPrim(data.currentPrim) : '—'}
            </span>
          </div>
          <div className="pn-sum-card">
            <span className="pn-sum-label">Kâr Primi</span>
            <span className={`pn-sum-value pn-sum-big ${hasData && data.profitPrim >= 0 ? 'pn-profit' : 'pn-loss'}`}>
              {hasData ? fmtPrim(data.profitPrim) : '—'}
            </span>
          </div>
          <div className="pn-sum-card">
            <span className="pn-sum-label">K/Z</span>
            <span className={`pn-sum-value pn-sum-big ${pos.pnl >= 0 ? 'pn-profit' : 'pn-loss'}`}>
              {fmtMoneyFull((pos.pnl || 0) + (pos.swap || 0))}
            </span>
          </div>
          <div className="pn-sum-card">
            <span className="pn-sum-label">Trailing</span>
            <span className="pn-sum-value">
              {hasData ? `${data.trailingDist} prim` : '—'}
            </span>
          </div>
        </div>

        {/* ── Yakınlık barı ─────────────────────── */}
        {hasData && (
          <ProximityBar
            currentPrim={data.currentPrim}
            direction={pos.direction}
            targetPrim={cfg.target_prim}
          />
        )}

        {/* ── Kurallar satırı ──────────────────── */}
        <div className="pn-rules">
          <span className="pn-rule-item pn-rule-trail">Trailing: {cfg.trailing_prim} prim (SABİT)</span>
          <span className="pn-rule-sep">|</span>
          <span className="pn-rule-item pn-rule-target">Hedef: ±{cfg.target_prim} prim</span>
        </div>

        {/* ── Prim merdiveni ───────────────────── */}
        {hasData ? (
          <div className="pn-ladder-wrap">
            <table className="pn-ladder">
              <thead>
                <tr>
                  <th className="pn-th-prim">PRİM</th>
                  <th className="pn-th-price">FİYAT</th>
                  <th className="pn-th-pnl">K/Z (TL)</th>
                  <th className="pn-th-stop">STOP SEV.</th>
                  <th className="pn-th-status">DURUM</th>
                  <th className="pn-th-locked">KİLİTLİ KÂR</th>
                  <th className="pn-th-desc">AÇIKLAMA</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => {
                  const isCurrent = r.isCurrent;
                  let rowCls = `pn-row pn-row--${r.statusClass || 'neutral'}`;
                  if (isCurrent) rowCls += ' pn-row--current pn-pulse';
                  if (r.isCurrentStop && !isCurrent) rowCls += ' pn-row--current-stop pn-pulse-red';
                  if (r.isEntry && !isCurrent && !r.isCurrentStop) rowCls += ' pn-row--entry-mark';

                  const explanation = buildExplanation(r, data, cfg);

                  return (
                    <tr
                      key={r.prim}
                      className={rowCls}
                      ref={isCurrent ? currentRef : null}
                    >
                      <td className="pn-col-prim">
                        {fmtPrim(r.prim)}
                        {r.prim === 0 && <span className="pn-ref-dot">●</span>}
                      </td>
                      <td className="pn-col-price">{r.price.toFixed(2)}</td>
                      <td className={`pn-col-pnl ${r.pnlTL >= 0 ? 'pn-profit' : 'pn-loss'}`}>
                        {fmtMoney(r.pnlTL)}
                      </td>
                      <td className="pn-col-stop">{r.stopLevel}</td>
                      <td className={`pn-col-status pn-st--${r.statusClass}`}>
                        {r.status}
                      </td>
                      <td className="pn-col-locked">
                        {r.lockedTL > 0 ? fmtMoney(r.lockedTL) : (r.statusClass === 'trailing' || r.statusClass === 'breakeven') ? '0' : ''}
                      </td>
                      <td className="pn-col-desc">{explanation}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="pn-no-data">
            <div className="pn-no-data-icon">⏳</div>
            <div className="pn-no-data-title">Referans fiyat mevcut değil</div>
            <div className="pn-no-data-sub">
              MT5'ten tavan/taban limitleri alınamadı. Piyasa açıldığında PRİMNET otomatik aktifleşecek.
            </div>
          </div>
        )}

        {/* ── Alt bilgi ─────────────────────────── */}
        <div className="pn-footer">
          <span className="pn-foot-item">Ref: <b>{fmtPrice(ref)}</b></span>
          <span className="pn-foot-item">SL: <b className="pn-loss">{fmtPrice(pos.current_sl)}</b></span>
          <span className="pn-foot-item">TP: <b className="pn-profit">{fmtPrice(pos.current_tp)}</b></span>
          <span className="pn-foot-item">Lot: <b>{pos.volume}</b></span>
          <span className="pn-foot-item">
            Devir: <b>{pos.transferred_at ? new Date(pos.transferred_at).toLocaleString('tr-TR') : '—'}</b>
          </span>
        </div>
      </div>
    </div>
  );
}
