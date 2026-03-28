/**
 * PRİMNET Pozisyon Detay Modalı
 *
 * Hibrit pozisyona tıklandığında açılır.
 * Prim merdiveni (scale) üzerinde giriş, güncel fiyat, stop ve hedef gösterir.
 * Faz durumu, kilitli kâr ve pozisyon bilgilerini profesyonel görünümle sunar.
 */

import React, { useMemo } from 'react';

// ── Prim hesaplamaları ─────────────────────────────────────────

function priceToPrim(price, refPrice) {
  const onePrim = refPrice * 0.01;
  if (onePrim <= 0) return 0;
  return (price - refPrice) / onePrim;
}

function primToPrice(prim, refPrice) {
  return refPrice + prim * (refPrice * 0.01);
}

function formatPrim(val) {
  if (val == null || isNaN(val)) return '—';
  const sign = val > 0 ? '+' : '';
  return `${sign}${val.toFixed(2)}`;
}

function formatPrice(val) {
  if (val == null || isNaN(val) || val === 0) return '—';
  return val.toFixed(4);
}

function formatMoney(val) {
  if (val == null || isNaN(val)) return '—';
  const sign = val > 0 ? '+' : '';
  return `${sign}${val.toFixed(0)} TL`;
}

// ── Prim merdiveni satırı oluştur ──────────────────────────────

function buildLadder(pos, cfg) {
  const ref = pos.reference_price;
  if (!ref || ref <= 0) return [];

  const dir = pos.direction;
  const entryPrim = priceToPrim(pos.entry_price, ref);
  const currentPrim = priceToPrim(pos.current_price, ref);
  const slPrim = priceToPrim(pos.current_sl, ref);
  const tpPrim = priceToPrim(pos.current_tp, ref);
  const onePrimTL = ref * 0.01 * pos.volume * 100; // 1 prim = TL

  const profitPrim = dir === 'BUY'
    ? currentPrim - entryPrim
    : entryPrim - currentPrim;

  // Faz belirleme
  const faz = profitPrim >= cfg.faz2_activation_prim ? 2 : 1;
  const trailingDist = faz === 2 ? cfg.faz2_trailing_prim : cfg.faz1_stop_prim;

  // Merdiven: -10 ile +10 arası (0.5 adım)
  const rows = [];
  for (let prim = 10; prim >= -10; prim -= 0.5) {
    const price = primToPrice(prim, ref);
    const pnlTL = dir === 'BUY'
      ? (prim - entryPrim) * onePrimTL
      : (entryPrim - prim) * onePrimTL;

    // Durum belirle
    let status = '';
    let statusClass = '';
    let fazLabel = '';
    let lockedTL = 0;

    const isEntry = Math.abs(prim - entryPrim) < 0.25;
    const isCurrent = Math.abs(prim - currentPrim) < 0.25;
    const isStop = Math.abs(prim - slPrim) < 0.25;
    const isTarget = Math.abs(prim - tpPrim) < 0.25;

    // BUY yönü için
    if (dir === 'BUY') {
      if (prim >= cfg.target_prim) {
        if (Math.abs(prim - cfg.target_prim) < 0.25) {
          status = 'HEDEF KAPANIŞ';
          statusClass = 'target';
          fazLabel = 'Hedef';
        } else {
          status = 'ULAŞILAMAZ';
          statusClass = 'unreachable';
        }
      } else if (prim > entryPrim && prim >= entryPrim + cfg.faz2_activation_prim) {
        status = 'TRAİLİNG';
        statusClass = 'trailing';
        fazLabel = 'Faz 2';
        lockedTL = (prim - trailingDist - entryPrim) * onePrimTL;
        if (lockedTL < 0) lockedTL = 0;
      } else if (prim > entryPrim) {
        status = 'TRAİLİNG';
        statusClass = 'trailing';
        fazLabel = 'Faz 1';
      } else if (isEntry) {
        status = 'GİRİŞ';
        statusClass = 'entry';
      } else if (prim < entryPrim && prim >= slPrim) {
        status = 'AÇIK';
        statusClass = 'open';
        fazLabel = 'Faz 1';
      } else if (isStop || (prim < slPrim && prim >= entryPrim - cfg.faz1_stop_prim - 0.25)) {
        status = 'STOP';
        statusClass = 'stop';
        fazLabel = 'Faz 1';
      } else if (prim < slPrim) {
        status = 'DIŞARDA';
        statusClass = 'outside';
      }
    } else {
      // SELL yönü
      if (prim <= -cfg.target_prim) {
        if (Math.abs(prim + cfg.target_prim) < 0.25) {
          status = 'HEDEF KAPANIŞ';
          statusClass = 'target';
          fazLabel = 'Hedef';
        } else {
          status = 'ULAŞILAMAZ';
          statusClass = 'unreachable';
        }
      } else if (prim < entryPrim && entryPrim - prim >= cfg.faz2_activation_prim) {
        status = 'TRAİLİNG';
        statusClass = 'trailing';
        fazLabel = 'Faz 2';
        lockedTL = (entryPrim - prim - trailingDist) * onePrimTL;
        if (lockedTL < 0) lockedTL = 0;
      } else if (prim < entryPrim) {
        status = 'TRAİLİNG';
        statusClass = 'trailing';
        fazLabel = 'Faz 1';
      } else if (isEntry) {
        status = 'GİRİŞ';
        statusClass = 'entry';
      } else if (prim > entryPrim && prim <= slPrim) {
        status = 'AÇIK';
        statusClass = 'open';
        fazLabel = 'Faz 1';
      } else if (isStop || (prim > slPrim && prim <= entryPrim + cfg.faz1_stop_prim + 0.25)) {
        status = 'STOP';
        statusClass = 'stop';
        fazLabel = 'Faz 1';
      } else if (prim > slPrim) {
        status = 'DIŞARDA';
        statusClass = 'outside';
      }
    }

    rows.push({
      prim,
      price,
      pnlTL,
      status,
      statusClass,
      fazLabel,
      lockedTL,
      isEntry,
      isCurrent,
      isStop,
      isTarget,
    });
  }

  return { rows, entryPrim, currentPrim, slPrim, tpPrim, profitPrim, faz, trailingDist, onePrimTL };
}

// ── Ana Bileşen ────────────────────────────────────────────────

export default function PrimnetDetail({ position, primnetConfig, onClose }) {
  const data = useMemo(() => {
    if (!position || !primnetConfig) return null;
    return buildLadder(position, primnetConfig);
  }, [position, primnetConfig]);

  if (!position) return null;

  const pos = position;
  const cfg = primnetConfig;
  const ref = pos.reference_price;
  const hasData = data && data.rows && data.rows.length > 0;

  return (
    <div className="pn-overlay" onClick={onClose}>
      <div className="pn-modal" onClick={(e) => e.stopPropagation()}>

        {/* Başlık */}
        <div className="pn-header">
          <div className="pn-title">
            <span className={`pn-dir pn-dir--${pos.direction.toLowerCase()}`}>
              {pos.direction}
            </span>
            <span className="pn-symbol">{pos.symbol}</span>
            <span className="pn-ticket">#{pos.ticket}</span>
          </div>
          <button className="pn-close" onClick={onClose}>X</button>
        </div>

        {/* Özet kartları */}
        <div className="pn-summary">
          <div className="pn-sum-card">
            <span className="pn-sum-label">Giriş Prim</span>
            <span className="pn-sum-value">{hasData ? formatPrim(data.entryPrim) : '—'}</span>
          </div>
          <div className="pn-sum-card">
            <span className="pn-sum-label">Güncel Prim</span>
            <span className={`pn-sum-value ${hasData && data.profitPrim >= 0 ? 'pn-profit' : 'pn-loss'}`}>
              {hasData ? formatPrim(data.currentPrim) : '—'}
            </span>
          </div>
          <div className="pn-sum-card">
            <span className="pn-sum-label">Faz</span>
            <span className={`pn-sum-value ${hasData && data.faz === 2 ? 'pn-profit' : ''}`}>
              {hasData ? `Faz ${data.faz}` : '—'}
            </span>
          </div>
          <div className="pn-sum-card">
            <span className="pn-sum-label">Kâr Primi</span>
            <span className={`pn-sum-value ${hasData && data.profitPrim >= 0 ? 'pn-profit' : 'pn-loss'}`}>
              {hasData ? formatPrim(data.profitPrim) : '—'}
            </span>
          </div>
          <div className="pn-sum-card">
            <span className="pn-sum-label">K/Z</span>
            <span className={`pn-sum-value ${pos.pnl >= 0 ? 'pn-profit' : 'pn-loss'}`}>
              {formatMoney(pos.pnl + pos.swap)}
            </span>
          </div>
          <div className="pn-sum-card">
            <span className="pn-sum-label">Trailing</span>
            <span className="pn-sum-value">
              {hasData ? `${data.trailingDist} prim` : '—'}
            </span>
          </div>
        </div>

        {/* PRİMNET kuralları */}
        <div className="pn-rules">
          Stop: {cfg.faz1_stop_prim} prim | Faz 2: +{cfg.faz2_activation_prim} prim |
          Trailing: {cfg.faz2_trailing_prim} prim | Hedef: {cfg.target_prim} prim
        </div>

        {/* Prim merdiveni */}
        {hasData ? (
          <div className="pn-ladder-wrap">
            <table className="pn-ladder">
              <thead>
                <tr>
                  <th>Prim</th>
                  <th>Fiyat</th>
                  <th>K/Z</th>
                  <th>Stop</th>
                  <th>Durum</th>
                  <th>Faz</th>
                  <th>Kilitli</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => {
                  let rowCls = `pn-row pn-row--${r.statusClass || 'neutral'}`;
                  if (r.isCurrent) rowCls += ' pn-row--current';
                  if (r.isEntry) rowCls += ' pn-row--entry-mark';

                  // Stop seviyesini göster
                  let stopCol = '';
                  if (r.isStop) stopCol = formatPrim(data.slPrim);

                  return (
                    <tr key={r.prim} className={rowCls}>
                      <td className="pn-col-prim">{formatPrim(r.prim)}</td>
                      <td className="pn-col-price">{r.price.toFixed(2)}</td>
                      <td className={`pn-col-pnl ${r.pnlTL >= 0 ? 'pn-profit' : 'pn-loss'}`}>
                        {r.pnlTL.toFixed(0)}
                      </td>
                      <td className="pn-col-stop">{stopCol}</td>
                      <td className={`pn-col-status pn-st--${r.statusClass}`}>{r.status}</td>
                      <td className="pn-col-faz">{r.fazLabel}</td>
                      <td className="pn-col-locked">
                        {r.lockedTL > 0 ? `${r.lockedTL.toFixed(0)}` : ''}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="pn-no-data">Referans fiyat mevcut değil — PRİMNET verisi gösterilemiyor</div>
        )}

        {/* Alt bilgi */}
        <div className="pn-footer">
          <span>Ref: {formatPrice(ref)}</span>
          <span>SL: {formatPrice(pos.current_sl)}</span>
          <span>TP: {formatPrice(pos.current_tp)}</span>
          <span>Lot: {pos.volume}</span>
          <span>Devir: {pos.transferred_at ? new Date(pos.transferred_at).toLocaleString('tr-TR') : '—'}</span>
        </div>
      </div>
    </div>
  );
}
