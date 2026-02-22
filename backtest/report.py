"""Backtest rapor üretici.

Backtest sonuçlarını analiz eder ve rapor oluşturur.

Çıktılar:
    - Özet istatistikler (Sharpe, DD, win rate, PF, ...)
    - HTML rapor (Jinja2 şablon + matplotlib grafikler)
    - PDF rapor (matplotlib PdfPages)
    - Grafikler: equity curve, drawdown, MC dağılım, sensitivity tornado
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt                           # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages      # noqa: E402

from engine.logger import get_logger

logger = get_logger(__name__)

# Jinja2 koşullu import
try:
    from jinja2 import Environment, BaseLoader
    HAS_JINJA2 = True
except ImportError:
    HAS_JINJA2 = False
    logger.warning("jinja2 yüklü değil — HTML rapor kullanılamaz")


# ═════════════════════════════════════════════════════════════════════
#  BACKTEST RAPOR VERİ MODELİ
# ═════════════════════════════════════════════════════════════════════


@dataclass
class BacktestReport:
    """Backtest raporu."""

    trades: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)
    initial_capital: float = 100_000

    def summary(self) -> dict:
        """Özet istatistikleri hesapla.

        Returns:
            İstatistik sözlüğü.
        """
        if not self.trades:
            return {"total_trades": 0}

        pnls = [t.get("pnl", 0) for t in self.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]

        equity = np.array(self.equity_curve)
        peak = np.maximum.accumulate(equity)
        drawdown = (peak - equity) / peak
        max_dd = float(drawdown.max()) if len(drawdown) > 0 else 0

        return {
            "total_trades": len(self.trades),
            "win_rate": len(wins) / len(self.trades) * 100 if self.trades else 0,
            "total_pnl": sum(pnls),
            "avg_win": float(np.mean(wins)) if wins else 0,
            "avg_loss": float(np.mean(losses)) if losses else 0,
            "profit_factor": abs(sum(wins) / sum(losses)) if losses else 0,
            "max_drawdown": max_dd,
            "sharpe_ratio": self._sharpe_ratio(pnls),
        }

    def _sharpe_ratio(self, pnls: list, risk_free: float = 0.0) -> float:
        """Sharpe ratio hesapla.

        Args:
            pnls: P&L listesi.
            risk_free: Risksiz getiri oranı.

        Returns:
            Sharpe ratio.
        """
        if not pnls or np.std(pnls) == 0:
            return 0.0
        return float((np.mean(pnls) - risk_free) / np.std(pnls))

    def print_summary(self) -> None:
        """Özeti konsola yazdır."""
        s = self.summary()
        logger.info("=== Backtest Raporu ===")
        for key, value in s.items():
            logger.info(f"  {key}: {value}")


# ═════════════════════════════════════════════════════════════════════
#  HTML ŞABLON (Gömülü — harici dosya gereksiz)
# ═════════════════════════════════════════════════════════════════════

HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <title>USTAT Backtest Raporu</title>
    <style>
        body { font-family: 'Segoe UI', sans-serif; margin: 40px;
               background: #f5f5f5; color: #222; }
        .container { max-width: 1200px; margin: 0 auto; background: white;
                     padding: 30px; border-radius: 8px;
                     box-shadow: 0 2px 8px rgba(0,0,0,.1); }
        h1, h2, h3 { color: #1a1a2e; }
        table { border-collapse: collapse; width: 100%; margin: 15px 0; }
        th, td { border: 1px solid #ddd; padding: 8px 10px; text-align: right; }
        th { background: #1a1a2e; color: white; }
        tr:nth-child(even) { background: #f9f9f9; }
        .metric-grid { display: grid; grid-template-columns: repeat(4, 1fr);
                       gap: 15px; margin: 20px 0; }
        .metric-card { background: #f0f4ff; padding: 15px; border-radius: 6px;
                       text-align: center; }
        .metric-value { font-size: 24px; font-weight: bold; color: #1a1a2e; }
        .metric-label { font-size: 12px; color: #666; margin-top: 4px; }
        .pass { color: #27ae60; font-weight: bold; }
        .fail { color: #e74c3c; font-weight: bold; }
        img { max-width: 100%%; height: auto; margin: 10px 0; }
        .section { margin: 30px 0; border-top: 2px solid #eee; padding-top: 20px; }
    </style>
</head>
<body>
<div class="container">
    <h1>USTAT Backtest Raporu</h1>
    <p>Olusturulma: {{ generated_at }}</p>

    <div class="section">
        <h2>Ozet</h2>
        <div class="metric-grid">
            {% for key, value in summary.items() %}
            <div class="metric-card">
                <div class="metric-value">{{ value }}</div>
                <div class="metric-label">{{ key }}</div>
            </div>
            {% endfor %}
        </div>
    </div>

    {% if equity_chart_path %}
    <div class="section">
        <h2>Equity Curve</h2>
        <img src="{{ equity_chart_path }}" alt="Equity Curve">
    </div>
    {% endif %}

    {% if drawdown_chart_path %}
    <div class="section">
        <h2>Drawdown</h2>
        <img src="{{ drawdown_chart_path }}" alt="Drawdown">
    </div>
    {% endif %}

    {% if walk_forward %}
    <div class="section">
        <h2>Walk-Forward OOS Sonuclari</h2>
        <table>
            <tr><th>Pencere</th><th>OOS Donem</th><th>Islem</th>
                <th>PnL</th><th>Win Rate</th><th>Maks DD</th></tr>
            {% for w in walk_forward.windows %}
            <tr>
                <td>{{ w.window_id }}</td>
                <td>{{ w.oos_start[:10] }} — {{ w.oos_end[:10] }}</td>
                <td>{{ w.oos_metrics.total_trades }}</td>
                <td>{{ "%.2f"|format(w.oos_metrics.total_pnl) }}</td>
                <td>{{ "%.1f"|format(w.oos_metrics.win_rate) }}%</td>
                <td>{{ "%.2f"|format(w.oos_metrics.max_drawdown * 100) }}%</td>
            </tr>
            {% endfor %}
        </table>
        <p>OOS Tutarlilik:
            <span class="{{ 'pass' if walk_forward.passed else 'fail' }}">
                {{ "%.1f"|format(walk_forward.aggregate_metrics.oos_consistency) }}%
            </span>
        </p>
    </div>
    {% endif %}

    {% if monte_carlo %}
    <div class="section">
        <h2>Monte Carlo Analizi</h2>
        <p>Permutasyon: {{ monte_carlo.n_permutations }}</p>
        <p>%95 Maks DD: {{ "%.2f"|format(monte_carlo.percentile_95_dd * 100) }}%</p>
        <p>Sonuc:
            <span class="{{ 'pass' if monte_carlo.passed else 'fail' }}">
                {{ "GECTI" if monte_carlo.passed else "KALDI" }}
            </span>
            (esik: {{ "%.0f"|format(monte_carlo.threshold * 100) }}%)
        </p>
        {% if mc_chart_path %}
        <img src="{{ mc_chart_path }}" alt="MC DD Dagilimi">
        {% endif %}
    </div>
    {% endif %}

    {% if stress_tests %}
    <div class="section">
        <h2>Stres Test Sonuclari</h2>
        <table>
            <tr><th>Senaryo</th><th>Donem</th><th>Islem</th>
                <th>PnL</th><th>Maks DD</th><th>Sonuc</th></tr>
            {% for r in stress_tests %}
            <tr>
                <td>{{ r.scenario.name }}</td>
                <td>{{ r.scenario.start_date }} — {{ r.scenario.end_date }}</td>
                <td>{{ r.n_trades }}</td>
                <td>{{ "%.2f"|format(r.total_pnl) }}</td>
                <td>{{ "%.2f"|format(r.max_drawdown * 100) }}%</td>
                <td class="{{ 'pass' if r.passed else 'fail' }}">
                    {{ "GECTI" if r.passed else "KALDI" }}</td>
            </tr>
            {% endfor %}
        </table>
    </div>
    {% endif %}

    {% if sensitivity %}
    <div class="section">
        <h2>Parametre Hassasiyeti</h2>
        <p>Genel Dayaniklilik:
            <span class="{{ 'pass' if sensitivity.overall_resilient else 'fail' }}">
                {{ "EVET" if sensitivity.overall_resilient else "HAYIR" }}
            </span>
        </p>
        {% if sensitivity.sensitive_params %}
        <p>Hassas parametreler: {{ sensitivity.sensitive_params | join(", ") }}</p>
        {% endif %}
        {% if sensitivity_chart_path %}
        <img src="{{ sensitivity_chart_path }}" alt="Sensitivity Tornado">
        {% endif %}
    </div>
    {% endif %}

    <div class="section">
        <h2>Islem Listesi</h2>
        <table>
            <tr><th>#</th><th>Yon</th><th>Strateji</th><th>Giris</th>
                <th>Cikis</th><th>PnL</th><th>Cikis Nedeni</th></tr>
            {% for t in trades[:50] %}
            <tr>
                <td>{{ loop.index }}</td>
                <td>{{ t.direction }}</td>
                <td>{{ t.strategy }}</td>
                <td>{{ "%.4f"|format(t.entry_price) }}</td>
                <td>{{ "%.4f"|format(t.exit_price) }}</td>
                <td style="color: {{ '#27ae60' if t.pnl > 0 else '#e74c3c' }}">
                    {{ "%.2f"|format(t.pnl) }}</td>
                <td>{{ t.exit_reason }}</td>
            </tr>
            {% endfor %}
        </table>
        {% if trades|length > 50 %}
        <p><em>Ilk 50 / {{ trades|length }} islem gosteriliyor.</em></p>
        {% endif %}
    </div>
</div>
</body>
</html>
"""


# ═════════════════════════════════════════════════════════════════════
#  RAPOR ÜRETİCİ
# ═════════════════════════════════════════════════════════════════════


class ReportGenerator:
    """HTML ve PDF backtest raporu üret.

    Args:
        output_dir: Çıktı dosyalarının yazılacağı klasör.
    """

    def __init__(self, output_dir: str = "backtest_reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ── Grafik çizimi ───────────────────────────────────────────────

    def _plot_equity_curve(self, equity: list[float], path: Path) -> None:
        """Equity curve grafiği oluştur."""
        fig, ax = plt.subplots(figsize=(12, 4))
        ax.plot(equity, color="#2196F3", linewidth=1)
        ax.fill_between(range(len(equity)), equity, alpha=0.1, color="#2196F3")
        ax.set_title("Equity Curve", fontsize=14)
        ax.set_ylabel("Equity (TRY)")
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(str(path), dpi=150, bbox_inches="tight")
        plt.close(fig)

    def _plot_drawdown(self, equity: list[float], path: Path) -> None:
        """Drawdown grafiği oluştur."""
        eq = np.array(equity)
        peak = np.maximum.accumulate(eq)
        dd = (peak - eq) / peak * 100

        fig, ax = plt.subplots(figsize=(12, 3))
        ax.fill_between(range(len(dd)), dd, color="#F44336", alpha=0.5)
        ax.set_title("Drawdown (%)", fontsize=14)
        ax.set_ylabel("Drawdown %")
        ax.invert_yaxis()
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(str(path), dpi=150, bbox_inches="tight")
        plt.close(fig)

    def _plot_mc_distribution(
        self,
        max_dds: list[float],
        threshold: float,
        path: Path,
    ) -> None:
        """Monte Carlo maks DD dağılım histogramı."""
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.hist(
            [d * 100 for d in max_dds],
            bins=50,
            color="#9C27B0",
            alpha=0.7,
        )
        ax.axvline(
            threshold * 100,
            color="red",
            linestyle="--",
            label=f"Esik ({threshold * 100:.0f}%)",
        )
        pct95 = float(np.percentile([d * 100 for d in max_dds], 95))
        ax.axvline(
            pct95,
            color="orange",
            linestyle="--",
            label=f"%95 ({pct95:.1f}%)",
        )
        ax.set_title("Monte Carlo Maks DD Dagilimi", fontsize=14)
        ax.set_xlabel("Maks Drawdown (%)")
        ax.set_ylabel("Frekans")
        ax.legend()
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(str(path), dpi=150, bbox_inches="tight")
        plt.close(fig)

    def _plot_sensitivity_tornado(
        self,
        variations: list,
        path: Path,
    ) -> None:
        """Parametre hassasiyeti tornado grafiği."""
        # Parametreye göre grupla
        param_impacts: dict[str, list[float]] = {}
        for v in variations:
            if v.param_name not in param_impacts:
                param_impacts[v.param_name] = []
            param_impacts[v.param_name].append(v.sharpe_change_pct)

        params = list(param_impacts.keys())
        ranges = [
            max(abs(min(vals)), abs(max(vals)))
            for vals in param_impacts.values()
        ]

        # Etkiye göre sırala
        sorted_pairs = sorted(
            zip(params, ranges), key=lambda x: x[1], reverse=True,
        )
        params = [p for p, _ in sorted_pairs[:15]]
        ranges = [r for _, r in sorted_pairs[:15]]

        fig, ax = plt.subplots(figsize=(10, max(4, len(params) * 0.4)))
        colors = ["#F44336" if r > 50 else "#4CAF50" for r in ranges]
        ax.barh(params, ranges, color=colors, alpha=0.7)
        ax.axvline(50, color="red", linestyle="--", alpha=0.5, label="%50 esik")
        ax.set_xlabel("Maks Sharpe Degisimi (%)")
        ax.set_title("Parametre Hassasiyeti (Sharpe Etkisi)", fontsize=14)
        ax.legend()
        ax.grid(True, alpha=0.3, axis="x")
        fig.tight_layout()
        fig.savefig(str(path), dpi=150, bbox_inches="tight")
        plt.close(fig)

    # ── HTML rapor ──────────────────────────────────────────────────

    def generate_html(
        self,
        report: BacktestReport,
        walk_forward: Any = None,
        monte_carlo: Any = None,
        stress_tests: list | None = None,
        sensitivity: Any = None,
        filename: str = "backtest_report.html",
    ) -> Path:
        """HTML rapor üret.

        Args:
            report: Ana backtest raporu.
            walk_forward: Walk-forward sonucu (opsiyonel).
            monte_carlo: Monte Carlo sonucu (opsiyonel).
            stress_tests: Stres test sonuçları (opsiyonel).
            sensitivity: Hassasiyet sonucu (opsiyonel).
            filename: Çıktı dosya adı.

        Returns:
            Oluşturulan HTML dosyasının yolu.
        """
        if not HAS_JINJA2:
            raise ImportError("HTML rapor için jinja2 gerekli")

        # Grafikleri oluştur
        equity_path = self.output_dir / "equity_curve.png"
        dd_path = self.output_dir / "drawdown.png"

        if report.equity_curve:
            self._plot_equity_curve(report.equity_curve, equity_path)
            self._plot_drawdown(report.equity_curve, dd_path)

        mc_chart_path: str | None = None
        if monte_carlo and hasattr(monte_carlo, "max_dd_distribution"):
            mc_path = self.output_dir / "mc_distribution.png"
            self._plot_mc_distribution(
                monte_carlo.max_dd_distribution, monte_carlo.threshold, mc_path,
            )
            mc_chart_path = str(mc_path.name)

        sensitivity_chart_path: str | None = None
        if sensitivity and hasattr(sensitivity, "variations"):
            sens_path = self.output_dir / "sensitivity_tornado.png"
            self._plot_sensitivity_tornado(sensitivity.variations, sens_path)
            sensitivity_chart_path = str(sens_path.name)

        # Özet değerlerini formatla
        summary = report.summary()
        formatted_summary: dict[str, str] = {}
        for k, v in summary.items():
            if isinstance(v, float):
                if "rate" in k:
                    formatted_summary[k] = f"{v:.1f}%"
                elif "drawdown" in k:
                    formatted_summary[k] = f"{v * 100:.2f}%"
                elif "ratio" in k:
                    formatted_summary[k] = f"{v:.3f}"
                else:
                    formatted_summary[k] = f"{v:,.2f}"
            else:
                formatted_summary[k] = str(v)

        # Şablonu render et
        env = Environment(loader=BaseLoader())
        template = env.from_string(HTML_TEMPLATE)

        html = template.render(
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
            summary=formatted_summary,
            equity_chart_path=(
                str(equity_path.name) if report.equity_curve else None
            ),
            drawdown_chart_path=(
                str(dd_path.name) if report.equity_curve else None
            ),
            walk_forward=walk_forward,
            monte_carlo=monte_carlo,
            mc_chart_path=mc_chart_path,
            stress_tests=stress_tests,
            sensitivity=sensitivity,
            sensitivity_chart_path=sensitivity_chart_path,
            trades=report.trades,
        )

        output_path = self.output_dir / filename
        output_path.write_text(html, encoding="utf-8")
        logger.info(f"HTML rapor olusturuldu: {output_path}")
        return output_path

    # ── PDF rapor ───────────────────────────────────────────────────

    def generate_pdf(
        self,
        report: BacktestReport,
        filename: str = "backtest_report.pdf",
    ) -> Path:
        """Matplotlib ile çok sayfalı PDF rapor üret.

        weasyprint gerektirmez — sadece matplotlib kullanır.

        Args:
            report: Backtest raporu.
            filename: Çıktı dosya adı.

        Returns:
            Oluşturulan PDF dosyasının yolu.
        """
        output_path = self.output_dir / filename

        with PdfPages(str(output_path)) as pdf:
            # Sayfa 1: Özet
            fig, ax = plt.subplots(figsize=(11, 8.5))
            ax.axis("off")
            summary = report.summary()
            text = "USTAT Backtest Raporu\n" + "=" * 50 + "\n\n"
            for k, v in summary.items():
                if isinstance(v, float):
                    text += f"{k:>20s}: {v:>12.4f}\n"
                else:
                    text += f"{k:>20s}: {str(v):>12s}\n"
            ax.text(
                0.1, 0.9, text,
                transform=ax.transAxes,
                fontsize=11,
                verticalalignment="top",
                fontfamily="monospace",
            )
            pdf.savefig(fig)
            plt.close(fig)

            # Sayfa 2: Equity curve + drawdown
            if report.equity_curve:
                fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8.5))

                ax1.plot(report.equity_curve, color="#2196F3")
                ax1.set_title("Equity Curve")
                ax1.set_ylabel("Equity (TRY)")
                ax1.grid(True, alpha=0.3)

                eq = np.array(report.equity_curve)
                peak = np.maximum.accumulate(eq)
                dd = (peak - eq) / peak * 100
                ax2.fill_between(
                    range(len(dd)), dd, color="#F44336", alpha=0.5,
                )
                ax2.set_title("Drawdown (%)")
                ax2.set_ylabel("DD %")
                ax2.invert_yaxis()
                ax2.grid(True, alpha=0.3)

                fig.tight_layout()
                pdf.savefig(fig)
                plt.close(fig)

        logger.info(f"PDF rapor olusturuldu: {output_path}")
        return output_path
