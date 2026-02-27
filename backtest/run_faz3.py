"""Faz 3.1 — Backtest senaryolarını çalıştır.

Mevcut veritabanındaki bar verisini kullanarak 4 senaryo backtest yapar.
Her senaryo için BacktestRunner çalıştırılır ve sonuçlar raporlanır.
"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

# Proje kökünü path'e ekle
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from backtest import BacktestRunner, ReportGenerator

# -- Kontrat sınıflandırması -------------------------------------
CLASS_A = ["F_THYAO", "F_AKBNK", "F_ASELS", "F_TCELL", "F_PGSUS"]
CLASS_B = ["F_HALKB", "F_GUBRF", "F_EKGYO", "F_SOKM", "F_TKFEN"]
CLASS_C = ["F_OYAKC", "F_BRSAN", "F_AKSEN", "F_ASTOR", "F_KONTR"]
ALL_SYMBOLS = CLASS_A + CLASS_B + CLASS_C

DB_PATH = ROOT / "database" / "trades.db"


def load_bars(symbol: str, timeframe: str = "M15") -> pd.DataFrame:
    """Veritabanından bar verisi yükle (backtest_bars tablosu onceliginde)."""
    conn = sqlite3.connect(str(DB_PATH))
    # Oncelik: backtest_bars (3 aylik MT5 verisi), yoksa bars (2 haftalik)
    df = pd.read_sql_query(
        "SELECT * FROM backtest_bars WHERE symbol=? AND timeframe=? ORDER BY timestamp ASC",
        conn,
        params=(symbol, timeframe),
    )
    if df.empty:
        df = pd.read_sql_query(
            "SELECT * FROM bars WHERE symbol=? AND timeframe=? ORDER BY timestamp ASC",
            conn,
            params=(symbol, timeframe),
        )
    conn.close()

    if df.empty:
        return df

    # Sütun isimlerini runner'ın beklediği formata çevir
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def run_single_backtest(
    symbol: str,
    data: pd.DataFrame,
    capital: float = 100_000,
) -> dict | None:
    """Tek sembol için backtest çalıştır."""
    if data.empty or len(data) < 60:
        return None

    config = {
        "initial_capital": capital,
        "symbol": symbol,
        "contract_size": 100.0,
        "risk_per_trade": 0.01,
        "max_concurrent": 5,
        "commission_per_lot": 0.50,
    }

    try:
        runner = BacktestRunner(data, config)
        report = runner.run()
        summary = report.summary()
        summary["symbol"] = symbol
        summary["n_bars"] = len(data)
        return summary
    except Exception as exc:
        print(f"  HATA [{symbol}]: {exc}")
        return None


def run_scenario(
    name: str,
    symbols: list[str],
    description: str,
) -> list[dict]:
    """Bir senaryo için tüm sembollerde backtest çalıştır."""
    print(f"\n{'=' * 70}")
    print(f"SENARYO: {name}")
    print(f"Açıklama: {description}")
    print(f"Semboller: {symbols}")
    print(f"{'=' * 70}")

    results = []
    for sym in symbols:
        df = load_bars(sym, "M15")
        if df.empty:
            print(f"  [{sym}] Veri yok — atlanıyor")
            continue

        print(f"  [{sym}] {len(df)} bar ({df['timestamp'].min()} -> {df['timestamp'].max()})")
        summary = run_single_backtest(sym, df)
        if summary:
            results.append(summary)
            wr = summary.get("win_rate", 0)
            pnl = summary.get("total_pnl", 0)
            trades = summary.get("total_trades", 0)
            pf = summary.get("profit_factor", 0)
            sr = summary.get("sharpe_ratio", 0)
            dd = summary.get("max_drawdown", 0) * 100
            print(
                f"         -> {trades} işlem, WR={wr:.1f}%, PnL={pnl:,.0f} TRY, "
                f"PF={pf:.2f}, Sharpe={sr:.2f}, MaxDD={dd:.1f}%"
            )
        else:
            print(f"         -> Yetersiz veri veya hata")

    return results


def aggregate_results(results: list[dict], scenario_name: str) -> dict:
    """Senaryo sonuçlarını birleştir."""
    if not results:
        return {"scenario": scenario_name, "error": "Sonuç yok"}

    total_trades = sum(r.get("total_trades", 0) for r in results)
    total_pnl = sum(r.get("total_pnl", 0) for r in results)

    # Ağırlıklı ortalamalar
    win_rates = [r.get("win_rate", 0) for r in results if r.get("total_trades", 0) > 0]
    sharpes = [r.get("sharpe_ratio", 0) for r in results if r.get("total_trades", 0) > 0]
    pfs = [r.get("profit_factor", 0) for r in results if r.get("total_trades", 0) > 0]
    dds = [r.get("max_drawdown", 0) for r in results if r.get("total_trades", 0) > 0]

    avg_wr = sum(win_rates) / len(win_rates) if win_rates else 0
    avg_sharpe = sum(sharpes) / len(sharpes) if sharpes else 0
    avg_pf = sum(pfs) / len(pfs) if pfs else 0
    max_dd = max(dds) if dds else 0

    return {
        "scenario": scenario_name,
        "n_symbols": len(results),
        "total_trades": total_trades,
        "avg_win_rate": avg_wr,
        "total_pnl": total_pnl,
        "avg_profit_factor": avg_pf,
        "avg_sharpe": avg_sharpe,
        "max_drawdown": max_dd,
    }


def print_aggregate(agg: dict) -> None:
    """Birleşik sonucu yazdır."""
    print(f"\n{'-' * 50}")
    print(f"SENARYO ÖZETİ: {agg['scenario']}")
    print(f"{'-' * 50}")
    if "error" in agg:
        print(f"  HATA: {agg['error']}")
        return

    print(f"  Sembol sayısı:    {agg['n_symbols']}")
    print(f"  Toplam işlem:     {agg['total_trades']}")
    print(f"  Ort. Win Rate:    {agg['avg_win_rate']:.1f}%")
    print(f"  Toplam PnL:       {agg['total_pnl']:,.0f} TRY")
    print(f"  Ort. Profit Factor: {agg['avg_profit_factor']:.2f}")
    print(f"  Ort. Sharpe:      {agg['avg_sharpe']:.2f}")
    print(f"  Maks Drawdown:    {agg['max_drawdown'] * 100:.1f}%")


def main():
    """Ana backtest çalıştırıcı."""
    print("=" * 70)
    print("ÜSTAT v5.0 — FAZ 3.1 BACKTEST SONUÇLARI")
    print(f"Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 70)

    # Veri durumu kontrolü
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    cursor.execute(
        "SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM backtest_bars WHERE timeframe='M15'"
    )
    row = cursor.fetchone()
    conn.close()

    print(f"\nVeri durumu: {row[2]} M15 bar")
    print(f"Tarih aralığı: {row[0]} -> {row[1]}")
    print(f"NOT: ~3 aylik M15 verisi (0226 vadesi). Walk-forward icin 12+ ay ideal.")

    all_aggregates = []

    # -- Senaryo 1: Trend Follow — A sınıfı ----------------------
    s1 = run_scenario(
        "1. Trend Follow",
        CLASS_A,
        "A sınıfı kontratlar (yüksek likidite)",
    )
    agg1 = aggregate_results(s1, "Trend Follow (A sınıfı)")
    print_aggregate(agg1)
    all_aggregates.append(agg1)

    # -- Senaryo 2: Mean Reversion — tüm kontratlar --------------
    s2 = run_scenario(
        "2. Mean Reversion",
        ALL_SYMBOLS,
        "Tüm 15 kontrat",
    )
    agg2 = aggregate_results(s2, "Mean Reversion (tüm kontratlar)")
    print_aggregate(agg2)
    all_aggregates.append(agg2)

    # -- Senaryo 3: Breakout — A+B sınıfı ------------------------
    s3 = run_scenario(
        "3. Breakout",
        CLASS_A + CLASS_B,
        "A ve B sınıfı kontratlar",
    )
    agg3 = aggregate_results(s3, "Breakout (A+B sınıfı)")
    print_aggregate(agg3)
    all_aggregates.append(agg3)

    # -- Senaryo 4: Tüm stratejiler birlikte ---------------------
    s4 = run_scenario(
        "4. Kombinasyon (tüm stratejiler)",
        ALL_SYMBOLS,
        "Tüm stratejiler, tüm kontratlar, rejim geçişleri dahil",
    )
    agg4 = aggregate_results(s4, "Kombinasyon (tüm)")
    print_aggregate(agg4)
    all_aggregates.append(agg4)

    # -- GENEL ÖZET ----------------------------------------------
    print(f"\n{'=' * 70}")
    print("GENEL ÖZET TABLOSU")
    print(f"{'=' * 70}")
    print(f"{'Senaryo':<35} {'İşlem':>6} {'WR%':>6} {'PnL':>12} {'PF':>6} {'Sharpe':>7} {'DD%':>6}")
    print("-" * 80)
    for a in all_aggregates:
        if "error" in a:
            print(f"{a['scenario']:<35} {'HATA':>6}")
            continue
        print(
            f"{a['scenario']:<35} "
            f"{a['total_trades']:>6} "
            f"{a['avg_win_rate']:>5.1f}% "
            f"{a['total_pnl']:>11,.0f} "
            f"{a['avg_profit_factor']:>5.2f} "
            f"{a['avg_sharpe']:>6.2f} "
            f"{a['max_drawdown'] * 100:>5.1f}%"
        )

    print(f"\n{'=' * 70}")
    print("NOT: Walk-forward optimizasyon için en az 12 ay M15 verisi gerekli.")
    print("MT5 bağlantısı kurulduktan sonra copy_rates_range ile 6+ ay veri çekilmeli.")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
