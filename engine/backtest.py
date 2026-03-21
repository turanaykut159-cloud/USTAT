"""
ÜSTAT v5.7 — Walk-Forward Validasyon Modülü
============================================

OĞUL v2 revizyon planı AŞAMA 5: Sinyal pipeline'ının gerçek VİOP verileri
üzerinde test edilmesi. Paper-trade mantığıyla hiçbir gerçek işlem açmaz.

Kullanım:
    python -m engine.backtest                     # Tüm semboller, son 500 bar
    python -m engine.backtest --symbol F_XU030    # Tek sembol
    python -m engine.backtest --bars 1000         # 1000 bar geriye git
    python -m engine.backtest --regime TREND      # Sadece belirli rejimde test

Çıktı:
    - Üretilen sinyal sayısı, yönleri, güçleri
    - Confluence geçme oranı
    - SE2 kaynak dağılımı
    - Pipeline aşama-aşama survival oranları
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

# ── ÜSTAT motor importları ────────────────────────────────────────────
try:
    from engine.config import Config
    from engine.utils.signal_engine import (
        generate_signal as se2_generate_signal,
        SignalVerdict,
    )
    from engine.utils.price_action import (
        calculate_confluence,
        CONFLUENCE_THRESHOLDS,
        CONFLUENCE_MIN_ENTRY,
    )
    from engine.utils.indicators import (
        adx as calc_adx,
        rsi as calc_rsi,
        atr as calc_atr,
    )
except ImportError as e:
    print(f"[HATA] Motor importları başarısız: {e}")
    print("Çalıştırma: python -m engine.backtest (USTAT kök dizininden)")
    sys.exit(1)


# ═════════════════════════════════════════════════════════════════════
#  BACKTEST MOTORU
# ═════════════════════════════════════════════════════════════════════

class BacktestResult:
    """Tek bir sembol için backtest sonuçları."""

    def __init__(self, symbol: str):
        self.symbol = symbol
        self.total_bars = 0
        self.signals_generated = 0
        self.signals_buy = 0
        self.signals_sell = 0
        self.confluence_pass = 0
        self.confluence_fail = 0
        self.se2_verdicts: list[dict] = []
        self.strength_values: list[float] = []
        self.source_counts: dict[str, int] = {}
        self.rr_values: list[float] = []
        self.regime_distribution: dict[str, int] = {}
        self.pipeline_stages: dict[str, int] = {
            "se2_input": 0,
            "se2_signal": 0,
            "confluence_pass": 0,
            "final_signal": 0,
        }

    def summary(self) -> dict[str, Any]:
        """JSON-uyumlu özet."""
        avg_str = (
            round(np.mean(self.strength_values), 3)
            if self.strength_values
            else 0.0
        )
        avg_rr = (
            round(np.mean(self.rr_values), 2) if self.rr_values else 0.0
        )
        return {
            "symbol": self.symbol,
            "total_bars": self.total_bars,
            "signals": self.signals_generated,
            "buy": self.signals_buy,
            "sell": self.signals_sell,
            "avg_strength": avg_str,
            "avg_rr": avg_rr,
            "confluence_pass_rate": (
                round(
                    self.confluence_pass
                    / max(self.confluence_pass + self.confluence_fail, 1)
                    * 100,
                    1,
                )
            ),
            "pipeline": self.pipeline_stages,
            "top_sources": dict(
                sorted(
                    self.source_counts.items(),
                    key=lambda x: x[1],
                    reverse=True,
                )[:5]
            ),
            "regime_dist": self.regime_distribution,
        }


def run_backtest(
    ohlcv: dict[str, np.ndarray],
    symbol: str,
    regime_type: str = "",
    window: int = 100,
    step: int = 1,
) -> BacktestResult:
    """Walk-forward backtest: pencere kaydırarak sinyal üret.

    Args:
        ohlcv: {"open": ndarray, "high": ..., "low": ..., "close": ..., "volume": ...}
        symbol: Sembol adı
        regime_type: Sabit rejim ("TREND", "RANGE", "VOLATILE") veya "" otomatik
        window: Her adımda kullanılacak bar penceresi
        step: Kaydırma adımı

    Returns:
        BacktestResult nesnesi.
    """
    result = BacktestResult(symbol)
    o, h, l, c, v = ohlcv["open"], ohlcv["high"], ohlcv["low"], ohlcv["close"], ohlcv["volume"]
    n = len(c)
    result.total_bars = n

    if n < window + 10:
        print(f"  [UYARI] {symbol}: Yetersiz veri ({n} bar < {window}+10)")
        return result

    for i in range(window, n, step):
        _o = o[i - window : i]
        _h = h[i - window : i]
        _l = l[i - window : i]
        _c = c[i - window : i]
        _v = v[i - window : i]

        result.pipeline_stages["se2_input"] += 1

        # ── 1) SE2 sinyal üretimi ─────────────────────────────
        verdict: SignalVerdict = se2_generate_signal(
            _o, _h, _l, _c, _v,
            current_price=float(_c[-1]),
            regime_type=regime_type,
        )

        if verdict.should_trade and verdict.direction != "NEUTRAL":
            result.pipeline_stages["se2_signal"] += 1
            result.signals_generated += 1

            if verdict.direction == "BUY":
                result.signals_buy += 1
            else:
                result.signals_sell += 1

            result.rr_values.append(verdict.risk_reward)

            # Kaynak bilgisi parse
            for src_name in (verdict.reason or "").split("[")[-1].replace("]", "").split(","):
                src_clean = src_name.strip().split("(")[0].strip()
                if src_clean:
                    result.source_counts[src_clean] = result.source_counts.get(src_clean, 0) + 1

            # ── 2) Confluence kontrolü ─────────────────────────
            try:
                atr_arr = calc_atr(_h, _l, _c, 14)
                atr_val = float(atr_arr[~np.isnan(atr_arr)][-1])
                adx_arr = calc_adx(_h, _l, _c, 14)
                adx_val = float(adx_arr[~np.isnan(adx_arr)][-1])
                rsi_arr = calc_rsi(_c, 14)
                rsi_val = float(rsi_arr[~np.isnan(rsi_arr)][-1])

                confluence = calculate_confluence(
                    direction=verdict.direction,
                    open_=_o,
                    high=_h,
                    low=_l,
                    close=_c,
                    volume=_v,
                    atr_val=atr_val,
                    adx_val=adx_val,
                    rsi_val=rsi_val,
                    regime_type=regime_type,
                )

                if confluence.can_enter:
                    result.confluence_pass += 1
                    result.pipeline_stages["confluence_pass"] += 1
                else:
                    result.confluence_fail += 1

                # Her iki durumda da sinyal çıkar (v2 soft penalty sayesinde)
                result.pipeline_stages["final_signal"] += 1
                result.strength_values.append(verdict.total_score / 100.0)

                result.se2_verdicts.append({
                    "bar": i,
                    "dir": verdict.direction,
                    "score": round(verdict.total_score, 1),
                    "rr": round(verdict.risk_reward, 2),
                    "conf_pass": confluence.can_enter,
                    "conf_score": round(confluence.total_score, 1),
                })

            except Exception:
                # Confluence hesaplanamazsa bile SE2 sinyali sayılır
                result.pipeline_stages["final_signal"] += 1
                result.strength_values.append(verdict.total_score / 100.0)

    return result


# ═════════════════════════════════════════════════════════════════════
#  VERİ YÜKLEME
# ═════════════════════════════════════════════════════════════════════

def load_ohlcv_from_db(symbol: str, bars: int = 500) -> dict[str, np.ndarray] | None:
    """Veritabanından OHLCV verisi yükle."""
    try:
        from engine.database import Database
        db = Database()
        # candles tablosundan çek
        query = f"""
            SELECT open, high, low, close, volume
            FROM candles
            WHERE symbol = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """
        rows = db.conn.execute(query, (symbol, bars)).fetchall()
        if not rows or len(rows) < 50:
            return None

        rows = list(reversed(rows))  # Eskiden yeniye sırala
        return {
            "open": np.array([r[0] for r in rows], dtype=np.float64),
            "high": np.array([r[1] for r in rows], dtype=np.float64),
            "low": np.array([r[2] for r in rows], dtype=np.float64),
            "close": np.array([r[3] for r in rows], dtype=np.float64),
            "volume": np.array([r[4] for r in rows], dtype=np.float64),
        }
    except Exception as e:
        print(f"  [HATA] DB yükleme başarısız ({symbol}): {e}")
        return None


def load_ohlcv_synthetic(bars: int = 500) -> dict[str, np.ndarray]:
    """Test amaçlı sentetik VİOP benzeri veri üret."""
    np.random.seed(42)
    close = np.cumsum(np.random.randn(bars) * 0.5) + 10000
    high = close + np.abs(np.random.randn(bars)) * 20
    low = close - np.abs(np.random.randn(bars)) * 20
    open_ = close + np.random.randn(bars) * 10
    volume = np.abs(np.random.randn(bars) * 500 + 1000)
    return {
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


# ═════════════════════════════════════════════════════════════════════
#  CLI
# ═════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="ÜSTAT OĞUL v2 Walk-Forward Validasyon"
    )
    parser.add_argument("--symbol", type=str, default="", help="Tek sembol (boş = tümü)")
    parser.add_argument("--bars", type=int, default=500, help="Geriye bakış bar sayısı")
    parser.add_argument("--regime", type=str, default="", help="Sabit rejim: TREND/RANGE/VOLATILE")
    parser.add_argument("--window", type=int, default=100, help="Walk-forward pencere boyutu")
    parser.add_argument("--step", type=int, default=5, help="Kaydırma adımı")
    parser.add_argument("--synthetic", action="store_true", help="Sentetik veri kullan (DB gerekmez)")
    parser.add_argument("--output", type=str, default="", help="JSON çıktı dosyası")
    args = parser.parse_args()

    print("=" * 70)
    print("  ÜSTAT v5.7 — OĞUL v2 Walk-Forward Validasyon")
    print(f"  Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  Rejim: {args.regime or 'OTOMATİK'} | Pencere: {args.window} | Adım: {args.step}")
    print("=" * 70)

    results: list[dict] = []

    if args.synthetic:
        print("\n[SENTETİK VERİ MODU]")
        ohlcv = load_ohlcv_synthetic(args.bars)
        bt = run_backtest(ohlcv, "SYNTHETIC", args.regime, args.window, args.step)
        summary = bt.summary()
        results.append(summary)
        _print_result(summary)
    else:
        symbols = [args.symbol] if args.symbol else _get_watched_symbols()
        for sym in symbols:
            print(f"\n── {sym} ──")
            ohlcv = load_ohlcv_from_db(sym, args.bars)
            if ohlcv is None:
                print(f"  [ATLA] Veri bulunamadı")
                continue
            bt = run_backtest(ohlcv, sym, args.regime, args.window, args.step)
            summary = bt.summary()
            results.append(summary)
            _print_result(summary)

    # ── Genel özet ──
    if results:
        total_signals = sum(r["signals"] for r in results)
        total_bars = sum(r["total_bars"] for r in results)
        print("\n" + "=" * 70)
        print(f"  GENEL ÖZET: {len(results)} sembol, {total_bars} bar, {total_signals} sinyal")
        if total_signals > 0:
            avg_str = np.mean([r["avg_strength"] for r in results if r["signals"] > 0])
            avg_rr = np.mean([r["avg_rr"] for r in results if r["signals"] > 0])
            print(f"  Ort. Güç: {avg_str:.3f} | Ort. R:R: {avg_rr:.2f}")
        print("=" * 70)

    if args.output:
        Path(args.output).write_text(json.dumps(results, indent=2, ensure_ascii=False))
        print(f"\n  Sonuçlar kaydedildi: {args.output}")


def _get_watched_symbols() -> list[str]:
    """MT5 bridge'den izlenen sembolleri al."""
    try:
        from engine.mt5_bridge import WATCHED_SYMBOLS
        return list(WATCHED_SYMBOLS)
    except ImportError:
        return ["F_XU030", "F_USDTRY"]


def _print_result(r: dict):
    """Tek sembol sonucunu yazdır."""
    print(f"  Barlar: {r['total_bars']} | Sinyaller: {r['signals']} (AL:{r['buy']} SAT:{r['sell']})")
    print(f"  Ort. Güç: {r['avg_strength']:.3f} | Ort. R:R: {r['avg_rr']:.2f}")
    print(f"  Confluence geçme: %{r['confluence_pass_rate']}")
    print(f"  Pipeline: {r['pipeline']}")
    if r["top_sources"]:
        src_str = ", ".join(f"{k}:{v}" for k, v in r["top_sources"].items())
        print(f"  Üst kaynaklar: {src_str}")


if __name__ == "__main__":
    main()
