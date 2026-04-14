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
  return `${sign}${val.toFixed(2)}`;
}

// Grid-snap: motor _calc_primnet_trailing_sl ile ayni algoritma.
// entry_prim offset'ini kullanip step'e yuvarlar (BUY=floor, SELL=ceil).
function snapStopPrim(rawStopPrim, entryPrim, step, direction) {
  if (!step || step <= 0) return rawStopPrim;
  const offset = ((entryPrim % step) + step) % step;
  const adjusted = rawStopPrim - offset;
  const ratio = adjusted / step;
  let snapped;
  if (direction === 'BUY') {
    snapped = Math.floor(ratio) * step + offset;
  } else {
    snapped = Math.ceil(ratio) * step + offset;
  }
  return Math.round(snapped * 100) / 100;
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
  const { prim, stopPrimSnapped, statusClass, isEntry, isStop, isTarget } = row;
  const { entryPrim } = data;
  const dir = data.direction;
  const trail = cfg.trailing_prim;
  // Yon-bilincli karsilastirma metni (BUY: stop > giris = kar; SELL: stop < giris = kar)
  const cmpProfit = dir === 'BUY' ? '>' : '<';
  const cmpLoss = dir === 'BUY' ? '<' : '>';

  if (statusClass === 'unreachable') {
    return `±${cfg.target_prim} hedefinde kapatıldı, buraya ulaşılamaz`;
  }
  if (isTarget || statusClass === 'target') {
    return `HEDEF ±${cfg.target_prim} → İŞLEMİ KAPAT`;
  }
  if (statusClass === 'locked') {
    const sp = stopPrimSnapped;
    const lockedPrim = dir === 'BUY'
      ? sp - entryPrim
      : entryPrim - sp;
    return `Stop ${fmtPrim(sp)} ${cmpProfit} Giriş → ${lockedPrim.toFixed(2)} prim kâr kilitli`;
  }
  if (statusClass === 'breakeven') {
    const sp = stopPrimSnapped;
    return `Stop ${fmtPrim(sp)} = Giriş → Başabaş`;
  }
  if (statusClass === 'trailing') {
    const sp = stopPrimSnapped;
    return `Stop ${fmtPrim(sp)} ${cmpLoss} Giriş → Kilitli kâr yok`;
  }
  if (isEntry) {
    const initialStop = dir === 'BUY' ? entryPrim - trail : entryPrim + trail;
    return `Pozisyon açıldı. Stop: ${fmtPrim(initialStop)} (${dir === 'BUY' ? '-' : '+'}${trail} prim)`;
  }
  if (statusClass === 'open') {
    const initialStop = dir === 'BUY' ? entryPrim - trail : entryPrim + trail;
    return `Zararda. Stop ${fmtPrim(initialStop)}'da`;
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

  // Trailing mesafe SABIT (faz ayrimi yok)
  const trailingDist = cfg.trailing_prim;
  const gridStep = cfg.step_prim || 0.5;

  // Merdiven kademeleri:
  // 1) Tam sayilar: -10 ile +10
  // 2) Hedef kapanis: ±9.5
  // 3) Giris primi (2 ondalik)
  // 4) Stop primi (giris ± trailing, grid snap motor ile ayni)
  // 5) Guncel fiyat (dinamik, kademeler arasina eklenir)
  const stepSet = new Set();

  // 1. Tam sayi kademeler
  for (let i = 10; i >= -10; i--) stepSet.add(i);

  // 2. Hedef kapanis yarimlari
  stepSet.add(9.5); stepSet.add(-9.5);

  // 3. Giris primi — 2 ondalik
  const entryRounded = Math.round(entryPrim * 100) / 100;
  stepSet.add(entryRounded);

  // 4. Ilk stop primi — grid snap (motor ile ayni)
  const stopPrimVal = snapStopPrim(
    dir === 'BUY' ? entryPrim - trailingDist : entryPrim + trailingDist,
    entryPrim, gridStep, dir,
  );
  stepSet.add(stopPrimVal);

  // 5. Guncel fiyatin dinamik satiri
  const currentRounded = Math.round(currentPrim * 100) / 100;
  const isOnFixedStep = [...stepSet].some(s => Math.abs(s - currentPrim) < 0.02);
  if (!isOnFixedStep && currentRounded >= -10 && currentRounded <= 10) {
    stepSet.add(currentRounded);
  }

  // 6. Guncel stop fiyatinin (canli SL) dinamik satiri
  const hasValidSl = pos.current_sl && pos.current_sl > 0 && !isNaN(slPrim);
  const slRounded = Math.round(slPrim * 100) / 100;
  const isSlOnFixedStep = hasValidSl
    ? [...stepSet].some(s => Math.abs(s - slPrim) < 0.02)
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
    let stopPrimSnapped = null;

    const isEntry = Math.abs(prim - entryRounded) < 0.005;
    const isStop = Math.abs(prim - stopPrimVal) < 0.005;
    const isDynamicRow = !isOnFixedStep && Math.abs(prim - currentRounded) < 0.005;
    const isCurrent = isDynamicRow || (isOnFixedStep && Math.abs(prim - currentPrim) < 0.02);
    const isDynamicSlRow = hasValidSl && !isSlOnFixedStep && Math.abs(prim - slRounded) < 0.005;
    const isCurrentStop = hasValidSl && (
      isDynamicSlRow || (isSlOnFixedStep && Math.abs(prim - slPrim) < 0.02)
    );
    const isTarget = Math.abs(prim - tpPrim) < 0.25;

    // T8: Kilitli kar monotonic — canli SL (slPrim) arkasindan ilerler,
    // her satir icin: BUY -> max(rowStop, slPrim), SELL -> min(rowStop, slPrim)

    if (dir === 'BUY') {
      if (prim >= cfg.target_prim) {
        if (Math.abs(prim - cfg.target_prim) < 0.25) {
          status = 'KAPAT'; statusClass = 'target'; fazLabel = 'Hedef';
        } else {
          status = 'ULAŞILAMAZ'; statusClass = 'unreachable';
        }
      } else if (prim > entryPrim && !isEntry) {
        const rawStop = prim - trailingDist;
        const snapped = snapStopPrim(rawStop, entryPrim, gridStep, dir);
        const sp = hasValidSl && slPrim > snapped ? slPrim : snapped;
        stopPrimSnapped = sp;
        stopLevel = fmtPrim(sp);
        const locked = sp - entryPrim;
        if (Math.abs(locked) < 0.005) {
          status = 'BREAKEVEN'; statusClass = 'breakeven';
        } else if (locked > 0) {
          status = 'KÂR KİLİTLİ'; statusClass = 'locked';
          lockedTL = locked * onePrimTL;
        } else {
          status = 'TRAİLİNG'; statusClass = 'trailing';
        }
      } else if (isEntry) {
        status = 'GİRİŞ'; statusClass = 'entry';
        stopPrimSnapped = entryPrim - trailingDist;
        stopLevel = fmtPrim(stopPrimSnapped);
      } else if (prim < entryPrim && prim >= slPrim) {
        status = 'AÇIK'; statusClass = 'open';
      } else if (isStop || (prim < slPrim && prim >= entryPrim - trailingDist - 0.25)) {
        status = 'STOP'; statusClass = 'stop';
        stopLevel = '';
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
        const rawStop = prim + trailingDist;
        const snapped = snapStopPrim(rawStop, entryPrim, gridStep, dir);
        const sp = hasValidSl && slPrim < snapped ? slPrim : snapped;
        stopPrimSnapped = sp;
        stopLevel = fmtPrim(sp);
        const locked = entryPrim - sp;
        if (Math.abs(locked) < 0.005) {
          status = 'BREAKEVEN'; statusClass = 'breakeven';
        } else if (locked > 0) {
          status = 'KÂR KİLİTLİ'; statusClass = 'locked';
          lockedTL = locked * onePrimTL;
        } else {
          status = 'TRAİLİNG'; statusClass = 'trailing';
        }
      } else if (isEntry) {
        status = 'GİRİŞ'; statusClass = 'entry';
        stopPrimSnapped = entryPrim + trailingDist;
        stopLevel = fmtPrim(stopPrimSnapped);
      } else if (prim > entryPrim && prim <= slPrim) {
        status = 'AÇIK'; statusClass = 'open';
      } else if (isStop || (prim > slPrim && prim <= entryPrim + trailingDist + 0.25)) {
        status = 'STOP'; statusClass = 'stop';
        stopLevel = '';
      } else if (prim > slPrim) {
        status = 'DIŞARDA'; statusClass = 'outside';
      }
    }

    rows.push({
      prim, price, pnlTL, status, statusClass, fazLabel,
      lockedTL, stopLevel, stopPrimSnapped,
      isEntry, isCurrent, isStop, isCurrentStop, isTarget,
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
          <span className="pn-rule-item pn-rule-trail">Trailing: {cfg.trailing_prim} prim (SABIT)</span>
          <span className="pn-rule-sep">|</span>
          <span className="pn-rule-item pn-rule-step">Adim: {cfg.step_prim || 0.5} prim (grid)</span>
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
          <span className="pn-foot-item">
            TRAILING STOP: <b className="pn-loss">{fmtPrice(pos.current_sl)}</b>
            {pos.trailing_active ? (
              <span className="pn-foot-sub pn-profit"> · aktif</span>
            ) : (
              <span className="pn-foot-sub"> · beklemede</span>
            )}
          </span>
          <span className="pn-foot-item">TP (hedef): <b className="pn-profit">{fmtPrice(pos.current_tp)}</b></span>
          <span className="pn-foot-item">Lot: <b>{pos.volume}</b></span>
          <span className="pn-foot-item">
            Devir: <b>{pos.transferred_at ? new Date(pos.transferred_at).toLocaleString('tr-TR') : '—'}</b>
          </span>
        </div>
      </div>
    </div>
  );
}
