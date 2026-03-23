"""ÜSTAT v5.7 — Haber Köprüsü Modülü (News Bridge).

╔══════════════════════════════════════════════════════════════╗
║  Modül  : engine/news_bridge.py                              ║
║  Versiyon: 1.0.0                                             ║
║  Tarih  : Mart 2026                                          ║
║  Mimar  : Üstat                                              ║
╚══════════════════════════════════════════════════════════════╝

Görev:
    Dış haber kaynaklarından veri çekip sentiment analizi yaparak
    BABA (kötü haber → koruma) ve OĞUL (iyi haber → alım sinyali)
    motorlarına yapılandırılmış haber olayları sağlar.

Mimari:
    NewsProvider (ABC) → SentimentAnalyzer → NewsCache → NewsBridge
                                                          ↓
                                                   BABA / OĞUL

Haber Kaynakları (provider):
    - MT5Provider : MQL5 servis scriptinin dosyaya yazdığı haberleri okur
    - BenzingaProvider : Benzinga Pro API (REST/WebSocket)
    - RSSProvider : Ücretsiz RSS feed'leri (Bloomberg HT vb.)
    - RuleBasedProvider : Anahtar kelime bazlı kural motoru (fallback)

Sentiment Modeli:
    - FinBERT (varsayılan) : Finansal metin için fine-tune edilmiş BERT
    - RuleBased (fallback) : Anahtar kelime sözlüğü bazlı hızlı analiz
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("ustat.news")


# ═════════════════════════════════════════════════════════════════════
#  SABİTLER
# ═════════════════════════════════════════════════════════════════════

# Alpha decay katsayısı: score = base × exp(-DECAY_RATE × elapsed_sec)
# 30s → %50, 60s → %25, 120s → %6, 300s → %0.1
DEFAULT_DECAY_RATE: float = 0.023

# Sentiment eşikleri
DEFAULT_POSITIVE_THRESHOLD: float = 0.5
DEFAULT_NEGATIVE_THRESHOLD: float = -0.3
DEFAULT_CRITICAL_THRESHOLD: float = -0.85

# Haber maksimum yaşı (saniye) — daha eski haberler yok sayılır
DEFAULT_MAX_AGE: int = 300  # 5 dakika

# Cooldown: aynı kategoride ardışık haberler arası minimum süre
DEFAULT_COOLDOWN_SEC: int = 60

# SE2 kaynak ağırlığı
DEFAULT_SE2_WEIGHT: float = 1.3

# Kategori çarpanları (sentiment skoru hesabında)
CATEGORY_MULTIPLIERS: dict[str, float] = {
    "JEOPOLITIK": 1.5,
    "EKONOMIK": 1.3,
    "SEKTOREL": 1.0,
    "SIRKET": 0.8,
    "GENEL": 0.6,
}

# Severity eşikleri (sentiment → severity mapping)
SEVERITY_THRESHOLDS: list[tuple[float, str]] = [
    (-0.85, "CRITICAL"),   # < -0.85
    (-0.70, "HIGH"),       # -0.85 .. -0.70
    (-0.50, "MEDIUM"),     # -0.70 .. -0.50
    (-0.30, "LOW"),        # -0.50 .. -0.30
]

# Lot küçültme çarpanları (severity bazlı)
LOT_REDUCTION: dict[str, float] = {
    "CRITICAL": 0.0,   # İşlem açılmaz
    "HIGH": 0.25,
    "MEDIUM": 0.50,
    "LOW": 0.75,
}

# Sembol → şirket/sektör eşleştirme sözlüğü (VİOP kontratları)
SYMBOL_KEYWORDS: dict[str, list[str]] = {
    "F_AKBNK": ["akbank", "akbnk"],
    "F_ARCLK": ["arçelik", "arcelik", "arclk"],
    "F_ASELS": ["aselsan", "asels", "savunma"],
    "F_BIMAS": ["bim", "bimas", "perakende"],
    "F_EKGYO": ["emlak konut", "ekgyo", "gayrimenkul"],
    "F_EREGL": ["ereğli", "eregli", "eregl", "çelik", "demir"],
    "F_GARAN": ["garanti", "garan", "bbva"],
    "F_GUBRF": ["gübre", "gubre", "gubrf"],
    "F_HALKB": ["halkbank", "halkb"],
    "F_ISCTR": ["iş bankası", "isbank", "isctr", "is bankasi"],
    "F_KCHOL": ["koç", "koc", "kchol"],
    "F_KONTR": ["konya", "kontr", "kontrat"],
    "F_PGSUS": ["pegasus", "pgsus", "havacılık"],
    "F_SAHOL": ["sabancı", "sahol"],
    "F_SISE": ["şişecam", "sisecam", "sise", "cam"],
    "F_TAVHL": ["tav", "tavhl", "havalimanı"],
    "F_TCELL": ["turkcell", "tcell", "telekom"],
    "F_THYAO": ["thy", "thyao", "türk hava", "turk hava", "havayolu"],
    "F_TKFEN": ["tekfen", "tkfen", "inşaat"],
    "F_TOASO": ["tofaş", "toaso", "otomotiv"],
    "F_TUPRS": ["tüpraş", "tupras", "tuprs", "rafineri", "petrol"],
    "F_YKBNK": ["yapı kredi", "ykbnk", "yapi kredi"],
    # Endeks kontratları
    "F_XU030": ["bist30", "xu030", "borsa", "endeks", "bist"],
    "F_USDTRY": ["dolar", "usdtry", "kur", "döviz"],
}

# Genel (tüm sembolü etkileyen) anahtar kelimeler
GLOBAL_KEYWORDS: list[str] = [
    "tcmb", "merkez bankası", "faiz", "enflasyon", "cpi",
    "fed", "ecb", "imf", "nato", "trump", "erdoğan", "erdogan",
    "savaş", "savas", "barış", "baris", "müzakere", "muzakere",
    "yaptırım", "yaptirim", "ambargo", "seçim", "secim",
    "deprem", "tsunami", "kriz", "resesyon", "stagflasyon",
    "brent", "petrol", "altın", "altin", "cds",
]

# Pozitif ve negatif anahtar kelimeler (kural bazlı sentiment için)
POSITIVE_KEYWORDS: list[str] = [
    "yükseldi", "yukseldi", "artış", "artis", "rekor", "kar",
    "pozitif", "iyimser", "büyüme", "buyume", "toparlanma",
    "anlaşma", "anlasma", "müzakere", "muzakere", "barış", "baris",
    "destek", "yatırım", "yatirim", "ihracat", "derecelendirme yükseltti",
    "rally", "boğa", "boga", "alım", "alim", "hedef fiyat yükseltti",
    "temettü", "temettu", "kâr artışı", "gelir artışı",
    "ateşkes", "ateskes", "uzlaşma", "uzlasma",
    "kredi notu", "not yükseltti", "not artışı",
]

NEGATIVE_KEYWORDS: list[str] = [
    "düştü", "dustu", "geriledi", "kayıp", "kayip", "zarar",
    "negatif", "karamsar", "daralma", "küçülme", "kuculme",
    "çatışma", "catisma", "savaş", "savas", "tehdit",
    "yaptırım", "yaptirim", "ambargo", "kriz", "iflas",
    "ayı", "ayi", "satış", "satis", "temerrüt",
    "faiz artışı", "enflasyon yükseldi", "cds yükseldi",
    "dolar yükseldi", "kur şoku", "spread patladı",
    "deprem", "sel", "tsunami", "pandemi",
    "saldırı", "saldiri", "bomba", "terör", "teror",
]


# ═════════════════════════════════════════════════════════════════════
#  VERİ YAPILARI
# ═════════════════════════════════════════════════════════════════════

class NewsCategory(Enum):
    """Haber kategorileri."""
    JEOPOLITIK = "JEOPOLITIK"
    EKONOMIK = "EKONOMIK"
    SEKTOREL = "SEKTOREL"
    SIRKET = "SIRKET"
    GENEL = "GENEL"


class NewsSeverity(Enum):
    """Olumsuz haber ciddiyet seviyeleri."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


@dataclass
class NewsEvent:
    """Tek bir haber olayı."""
    headline: str
    source: str                    # "MT5", "Benzinga", "RuleBased", vb.
    timestamp: float               # Unix timestamp (haberin yayınlanma zamanı)
    category: str = "GENEL"        # JEOPOLITIK, EKONOMIK, SEKTOREL, SIRKET, GENEL
    sentiment_score: float = 0.0   # -1.0 .. +1.0
    confidence: float = 0.0        # 0.0 .. 1.0
    symbols: list[str] = field(default_factory=list)  # Etkilenen semboller
    raw_text: str = ""             # Tam metin (varsa)
    event_id: str = ""             # Benzersiz tanımlayıcı (duplicate tespiti)
    is_global: bool = False        # Tüm piyasayı etkiler mi

    @property
    def age_seconds(self) -> float:
        """Haberin yaşı (saniye)."""
        return time.time() - self.timestamp

    @property
    def severity(self) -> str:
        """Olumsuz haber ciddiyet seviyesi."""
        if self.sentiment_score >= 0:
            return "NONE"
        for threshold, sev in SEVERITY_THRESHOLDS:
            if self.sentiment_score <= threshold:
                return sev
        return "LOW" if self.sentiment_score < DEFAULT_NEGATIVE_THRESHOLD else "NONE"

    @property
    def lot_multiplier(self) -> float:
        """Severity bazlı lot çarpanı."""
        return LOT_REDUCTION.get(self.severity, 1.0)

    def to_dict(self) -> dict:
        """JSON-serializable dict dönüştürmesi."""
        return {
            "headline": self.headline,
            "source": self.source,
            "timestamp": self.timestamp,
            "time_str": datetime.fromtimestamp(self.timestamp).strftime("%H:%M:%S"),
            "category": self.category,
            "sentiment_score": round(self.sentiment_score, 3),
            "confidence": round(self.confidence, 3),
            "symbols": self.symbols,
            "is_global": self.is_global,
            "severity": self.severity,
            "age_seconds": round(self.age_seconds, 1),
            "lot_multiplier": self.lot_multiplier,
            "event_id": self.event_id,
        }


@dataclass
class NewsSignal:
    """Haber bazlı sinyal (OĞUL'a iletilecek)."""
    direction: str = "NEUTRAL"     # BUY / SELL / NEUTRAL
    score: float = 0.0             # 0-20 (SE2 uyumlu)
    confidence: float = 0.0        # 0.0-1.0
    source_event: NewsEvent | None = None
    decay_applied: bool = False


# ═════════════════════════════════════════════════════════════════════
#  SENTIMENT ANALİZCİ
# ═════════════════════════════════════════════════════════════════════

class SentimentAnalyzer:
    """Haber metni sentiment analizi.

    Varsayılan: Kural tabanlı (anahtar kelime).
    İsteğe bağlı: FinBERT (torch + transformers gerekli).
    """

    def __init__(self, model: str = "rule_based"):
        self._model_name = model
        self._finbert_pipeline = None

        if model == "finbert":
            self._init_finbert()

    def _init_finbert(self) -> None:
        """FinBERT modelini yükle (opsiyonel)."""
        try:
            from transformers import pipeline as hf_pipeline
            self._finbert_pipeline = hf_pipeline(
                "sentiment-analysis",
                model="ProsusAI/finbert",
                top_k=None,
            )
            logger.info("FinBERT sentiment modeli yüklendi.")
        except ImportError:
            logger.warning(
                "transformers/torch bulunamadı — kural tabanlı sentiment'e geçiliyor."
            )
            self._model_name = "rule_based"
        except Exception as e:
            logger.error(f"FinBERT yükleme hatası: {e} — kural tabanlı'ya geçiş.")
            self._model_name = "rule_based"

    def analyze(self, text: str) -> tuple[float, float]:
        """Metin sentiment analizi.

        Args:
            text: Haber başlığı veya metni.

        Returns:
            (score, confidence) — score: -1..+1, confidence: 0..1
        """
        if not text or not text.strip():
            return 0.0, 0.0

        if self._model_name == "finbert" and self._finbert_pipeline:
            return self._analyze_finbert(text)
        return self._analyze_rule_based(text)

    def _analyze_finbert(self, text: str) -> tuple[float, float]:
        """FinBERT ile sentiment analizi."""
        try:
            results = self._finbert_pipeline(text[:512])  # Max token limiti
            if not results or not results[0]:
                return 0.0, 0.0

            score_map = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}
            best = max(results[0], key=lambda x: x["score"])
            sentiment = score_map.get(best["label"], 0.0)
            confidence = best["score"]

            # Negatif ve pozitif skorları birleştirerek daha granüler skor
            pos_score = next(
                (r["score"] for r in results[0] if r["label"] == "positive"), 0.0
            )
            neg_score = next(
                (r["score"] for r in results[0] if r["label"] == "negative"), 0.0
            )
            # Continuous score: -1 ile +1 arası
            continuous = pos_score - neg_score
            return continuous, confidence

        except Exception as e:
            logger.error(f"FinBERT analiz hatası: {e}")
            return self._analyze_rule_based(text)

    def _analyze_rule_based(self, text: str) -> tuple[float, float]:
        """Kural tabanlı (anahtar kelime) sentiment analizi."""
        text_lower = text.lower()

        pos_count = sum(1 for kw in POSITIVE_KEYWORDS if kw in text_lower)
        neg_count = sum(1 for kw in NEGATIVE_KEYWORDS if kw in text_lower)
        total = pos_count + neg_count

        if total == 0:
            return 0.0, 0.3  # Nötr, düşük confidence

        # Score: -1 ile +1 arası
        raw_score = (pos_count - neg_count) / total
        # Confidence: eşleşen kelime sayısına göre
        confidence = min(0.5 + total * 0.1, 0.9)

        return raw_score, confidence


# ═════════════════════════════════════════════════════════════════════
#  HABER SAĞLAYICI (Abstract Base)
# ═════════════════════════════════════════════════════════════════════

class NewsProvider(ABC):
    """Haber kaynağı temel sınıfı."""

    @abstractmethod
    def fetch(self) -> list[dict]:
        """Yeni haberleri çek.

        Returns:
            Liste: [{"headline": str, "timestamp": float, "source": str, ...}]
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Kaynak erişilebilir mi?"""
        ...


class MT5FileProvider(NewsProvider):
    """MQL5 servis scriptinin dosyaya yazdığı haberleri okur.

    MQL5 tarafında CalendarValueHistory() → JSON dosya yazılır.
    Python tarafında bu dosya periyodik okunur.

    Dosya formatı (mt5_news.json):
        [
            {
                "id": 123456,
                "headline": "TCMB Faiz Kararı: Sabit",
                "time": 1711191600,
                "currency": "TRY",
                "importance": 3,
                "actual": "45.0",
                "forecast": "45.0",
                "previous": "45.0"
            }
        ]
    """

    def __init__(self, file_path: str = ""):
        self._file_path = file_path or self._default_path()
        self._last_modified: float = 0.0
        self._last_ids: set[int] = set()

    @staticmethod
    def _default_path() -> str:
        """MT5 veri dosyası varsayılan yolu."""
        # MQL5 Common/Files klasörü
        appdata = os.environ.get("APPDATA", "")
        if appdata:
            return os.path.join(
                appdata, "MetaQuotes", "Terminal", "Common", "Files", "ustat_news.json"
            )
        return "ustat_news.json"

    def fetch(self) -> list[dict]:
        """Dosyadan yeni haberleri oku."""
        path = Path(self._file_path)
        if not path.exists():
            return []

        try:
            mtime = path.stat().st_mtime
            if mtime <= self._last_modified:
                return []  # Dosya değişmemiş

            # MQL5 FILE_ANSI → Windows-1254 (Türkçe) veya latin-1
            raw_bytes = path.read_bytes()
            try:
                text = raw_bytes.decode("utf-8")
            except UnicodeDecodeError:
                text = raw_bytes.decode("windows-1254", errors="replace")
            data = json.loads(text)

            self._last_modified = mtime

            # Sadece yeni haberleri döndür
            now = time.time()
            new_events = []
            for item in data:
                news_id = item.get("id", 0)
                if news_id in self._last_ids:
                    continue
                self._last_ids.add(news_id)

                # MT5 Calendar haberleri saatler önceye ait olabilir.
                # Cache TTL'e takılmaması için timestamp'i "okunma anı" olarak ayarla.
                # Orijinal zaman original_time alanında saklanır.
                original_time = item.get("time", now)

                new_events.append({
                    "headline": item.get("headline", ""),
                    "timestamp": now,          # cache TTL için: şimdi okundu
                    "original_time": original_time,  # gerçek haber zamanı
                    "source": "MT5",
                    "importance": item.get("importance", 1),
                    "currency": item.get("currency", ""),
                    "actual": item.get("actual", ""),
                    "forecast": item.get("forecast", ""),
                    "previous": item.get("previous", ""),
                })

            if new_events:
                logger.info(f"MT5 haber dosyasından {len(new_events)} yeni haber okundu.")

            return new_events

        except json.JSONDecodeError as e:
            logger.warning(f"MT5 haber dosyası JSON hatası: {e}")
            return []
        except Exception as e:
            logger.error(f"MT5 haber dosyası okuma hatası: {e}")
            return []

    def is_available(self) -> bool:
        """Dosya mevcut mu?"""
        return Path(self._file_path).exists()


class BenzingaProvider(NewsProvider):
    """Benzinga Pro API üzerinden haber çeker.

    Gereksinim: BENZINGA_API_KEY environment variable.
    API: https://api.benzinga.com/api/v2/news

    NOT: Bu provider opsiyoneldir. API key yoksa devre dışı kalır.
    """

    BASE_URL = "https://api.benzinga.com/api/v2/news"

    def __init__(self, api_key: str = ""):
        self._api_key = api_key or os.environ.get("BENZINGA_API_KEY", "")
        self._last_fetch_time: float = 0.0

    def fetch(self) -> list[dict]:
        """Benzinga API'den haber çek."""
        if not self._api_key:
            return []

        try:
            import requests
            params = {
                "token": self._api_key,
                "pageSize": 20,
                "sort": "created:desc",
            }
            resp = requests.get(self.BASE_URL, params=params, timeout=5)
            resp.raise_for_status()
            data = resp.json()

            events = []
            for item in data:
                created = item.get("created", "")
                try:
                    ts = datetime.fromisoformat(created).timestamp()
                except (ValueError, TypeError):
                    ts = time.time()

                if ts <= self._last_fetch_time:
                    continue

                events.append({
                    "headline": item.get("title", ""),
                    "timestamp": ts,
                    "source": "Benzinga",
                    "url": item.get("url", ""),
                    "tickers": item.get("stocks", []),
                })

            if events:
                self._last_fetch_time = time.time()
                logger.info(f"Benzinga'dan {len(events)} yeni haber çekildi.")

            return events

        except ImportError:
            logger.warning("requests kütüphanesi bulunamadı — Benzinga devre dışı.")
            return []
        except Exception as e:
            logger.error(f"Benzinga API hatası: {e}")
            return []

    def is_available(self) -> bool:
        """API key mevcut mu?"""
        return bool(self._api_key)


class RSSProvider(NewsProvider):
    """Ücretsiz RSS feed'lerinden Türkçe finansal haber çeker.

    Varsayılan feed'ler:
        - Bloomberg HT Piyasa   : https://www.bloomberght.com/rss/piyasa
        - Bloomberg HT Borsa    : https://www.bloomberght.com/rss/borsa
        - Bloomberg HT Döviz    : https://www.bloomberght.com/rss/doviz

    Ek feed'ler config'den eklenebilir.

    Bağımlılık: requests (BenzingaProvider ile ortak, ekstra kurulum gerekmez).
    """

    DEFAULT_FEEDS: list[str] = [
        "https://www.bloomberght.com/rss/piyasa",
        "https://www.bloomberght.com/rss/borsa",
        "https://www.bloomberght.com/rss/doviz",
    ]

    def __init__(self, feeds: list[str] | None = None, fetch_timeout: int = 8):
        self._feeds = feeds if feeds else self.DEFAULT_FEEDS
        self._timeout = fetch_timeout
        self._seen_guids: set[str] = set()
        self._last_fetch_time: float = 0.0
        # Aşırı büyümesini önle — en fazla 5000 guid tut
        self._max_seen: int = 5000

    def fetch(self) -> list[dict]:
        """Tüm RSS feed'lerinden yeni haberleri çek."""
        try:
            import requests
            import xml.etree.ElementTree as ET
        except ImportError:
            logger.warning("requests kütüphanesi bulunamadı — RSS devre dışı.")
            return []

        all_events: list[dict] = []

        for feed_url in self._feeds:
            try:
                resp = requests.get(
                    feed_url,
                    timeout=self._timeout,
                    headers={"User-Agent": "USTAT/5.7 NewsBot"},
                )
                resp.raise_for_status()

                # RSS XML parse
                root = ET.fromstring(resp.content)
                channel = root.find("channel")
                if channel is None:
                    continue

                for item in channel.findall("item"):
                    title = (item.findtext("title") or "").strip()
                    if not title:
                        continue

                    link = (item.findtext("link") or "").strip()
                    guid_el = item.findtext("guid") or link or title
                    pub_date = (item.findtext("pubDate") or "").strip()

                    # Duplicate kontrolü
                    if guid_el in self._seen_guids:
                        continue

                    # pubDate → timestamp
                    ts = self._parse_rss_date(pub_date)

                    all_events.append({
                        "headline": title,
                        "timestamp": ts or time.time(),
                        "source": "RSS",
                        "url": link,
                        "feed": feed_url,
                    })
                    self._seen_guids.add(guid_el)

            except Exception as e:
                logger.warning(f"RSS feed hatası ({feed_url}): {e}")
                continue

        # seen_guids bellek sınırı
        if len(self._seen_guids) > self._max_seen:
            # En eskilerden at — set olduğu için tümünü sil, yeniden ekle
            self._seen_guids.clear()
            logger.debug("RSS seen_guids temizlendi (bellek sınırı).")

        if all_events:
            self._last_fetch_time = time.time()
            logger.info(f"RSS feed'lerinden {len(all_events)} yeni haber çekildi.")

        return all_events

    @staticmethod
    def _parse_rss_date(date_str: str) -> float | None:
        """RFC 2822 / RFC 822 tarih stringini timestamp'e çevir.

        Örnekler:
            'Mon, 23 Mar 2026 14:30:00 +0300'
            'Mon, 23 Mar 2026 14:30:00 GMT'
        """
        if not date_str:
            return None
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(date_str)
            return dt.timestamp()
        except Exception:
            return None

    def is_available(self) -> bool:
        """En az bir feed URL tanımlı mı?"""
        return bool(self._feeds)


# ═════════════════════════════════════════════════════════════════════
#  HABER ÖNBELLEĞİ
# ═════════════════════════════════════════════════════════════════════

class NewsCache:
    """TTL tabanlı haber önbelleği. Duplikasyonu önler."""

    def __init__(self, max_age: int = DEFAULT_MAX_AGE):
        self._events: dict[str, NewsEvent] = {}  # event_id → NewsEvent
        self._max_age = max_age

    def add(self, event: NewsEvent) -> bool:
        """Haberi ekle. Duplicate ise False döner.

        Returns:
            True: Yeni haber eklendi.
            False: Duplicate veya çok eski.
        """
        if event.age_seconds > self._max_age:
            return False
        if event.event_id in self._events:
            return False
        self._events[event.event_id] = event
        return True

    def get_active(self) -> list[NewsEvent]:
        """Aktif (yaşı < max_age) haberleri döndür."""
        self._cleanup()
        return list(self._events.values())

    def get_active_for_symbol(self, symbol: str) -> list[NewsEvent]:
        """Belirli sembol için aktif haberleri döndür."""
        return [
            e for e in self.get_active()
            if symbol in e.symbols or e.is_global
        ]

    def get_worst_sentiment(self) -> Optional[NewsEvent]:
        """En kötü sentiment'li aktif haberi döndür."""
        active = self.get_active()
        if not active:
            return None
        return min(active, key=lambda e: e.sentiment_score)

    def get_best_sentiment(self) -> Optional[NewsEvent]:
        """En iyi sentiment'li aktif haberi döndür."""
        active = self.get_active()
        if not active:
            return None
        return max(active, key=lambda e: e.sentiment_score)

    def _cleanup(self) -> None:
        """Süresi dolmuş haberleri temizle."""
        expired = [
            eid for eid, ev in self._events.items()
            if ev.age_seconds > self._max_age
        ]
        for eid in expired:
            del self._events[eid]

    @property
    def count(self) -> int:
        """Aktif haber sayısı."""
        self._cleanup()
        return len(self._events)


# ═════════════════════════════════════════════════════════════════════
#  ANA KÖPRÜ SINIFI
# ═════════════════════════════════════════════════════════════════════

class NewsBridge:
    """Haber entegrasyonu ana koordinatör sınıfı.

    Engine tarafından her cycle'da çağrılır:
        news_bridge.run_cycle()

    Sonuçlar:
        - get_active_events() → BABA ve dashboard için
        - get_signal_for_symbol(symbol) → OĞUL SE2 10. kaynak için
        - get_worst_event() → BABA _check_olay() için
        - get_lot_multiplier(symbol) → BABA lot küçültme için
    """

    def __init__(self, config=None):
        self._config = config
        self._enabled = self._cfg("news.enabled", True)

        # Sentiment analizcisi
        model_name = self._cfg("news.sentiment_model", "rule_based")
        self._analyzer = SentimentAnalyzer(model=model_name)

        # Haber önbelleği
        max_age = self._cfg("news.max_age_seconds", DEFAULT_MAX_AGE)
        self._cache = NewsCache(max_age=max_age)

        # Haber sağlayıcıları
        self._providers: list[NewsProvider] = []
        self._init_providers()

        # Cooldown izleme (kategori → son haber zamanı)
        self._cooldowns: dict[str, float] = {}
        self._cooldown_sec = self._cfg("news.cooldown_seconds", DEFAULT_COOLDOWN_SEC)

        # Konfigürasyon sabitleri
        self._positive_threshold = self._cfg(
            "news.positive_threshold", DEFAULT_POSITIVE_THRESHOLD
        )
        self._negative_threshold = self._cfg(
            "news.negative_threshold", DEFAULT_NEGATIVE_THRESHOLD
        )
        self._critical_threshold = self._cfg(
            "news.critical_threshold", DEFAULT_CRITICAL_THRESHOLD
        )
        self._decay_rate = self._cfg("news.alpha_decay_rate", DEFAULT_DECAY_RATE)
        self._se2_weight = self._cfg("news.se2_weight", DEFAULT_SE2_WEIGHT)
        self._olay_trigger = self._cfg("news.olay_trigger_sentiment", -0.7)

        # İstatistikler
        self._total_processed: int = 0
        self._total_positive: int = 0
        self._total_negative: int = 0
        self._last_cycle_events: int = 0

        logger.info(
            f"NewsBridge başlatıldı: enabled={self._enabled}, "
            f"model={model_name}, providers={len(self._providers)}"
        )

    def _cfg(self, key: str, default: Any = None) -> Any:
        """Config'den değer oku."""
        if self._config is None:
            return default
        return self._config.get(key, default)

    def _init_providers(self) -> None:
        """Haber sağlayıcılarını başlat."""
        provider_name = self._cfg("news.provider", "mt5")

        if provider_name in ("mt5", "all"):
            file_path = self._cfg("news.mt5_file_path", "")
            self._providers.append(MT5FileProvider(file_path))

        if provider_name in ("benzinga", "all"):
            api_key = self._cfg("news.benzinga_api_key", "")
            self._providers.append(BenzingaProvider(api_key))

        if provider_name in ("rss", "all"):
            rss_feeds = self._cfg("news.rss_feeds", [])
            self._providers.append(RSSProvider(rss_feeds if rss_feeds else None))

        if not self._providers:
            logger.warning("Hiçbir haber sağlayıcısı aktif değil!")

    # ── Public: Ana Cycle ──────────────────────────────────────────

    def run_cycle(self) -> int:
        """Her 10 saniyede engine tarafından çağrılır.

        Returns:
            Yeni işlenen haber sayısı.
        """
        if not self._enabled:
            return 0

        new_count = 0

        for provider in self._providers:
            try:
                raw_events = provider.fetch()
                for raw in raw_events:
                    event = self._process_raw_event(raw)
                    if event and self._cache.add(event):
                        new_count += 1
                        self._total_processed += 1
                        if event.sentiment_score > self._positive_threshold:
                            self._total_positive += 1
                        elif event.sentiment_score < self._negative_threshold:
                            self._total_negative += 1
                        logger.info(
                            f"Yeni haber: [{event.category}] "
                            f"sentiment={event.sentiment_score:+.2f} "
                            f"confidence={event.confidence:.2f} "
                            f"severity={event.severity} "
                            f"symbols={event.symbols} "
                            f"— {event.headline[:80]}"
                        )
            except Exception as e:
                logger.error(f"Haber sağlayıcı hatası ({type(provider).__name__}): {e}")

        self._last_cycle_events = new_count
        return new_count

    def _process_raw_event(self, raw: dict) -> Optional[NewsEvent]:
        """Ham haber verisini NewsEvent'e dönüştür."""
        headline = raw.get("headline", "").strip()
        if not headline:
            return None

        # Cooldown kontrolü
        raw_text = raw.get("raw_text", headline)

        # Sentiment analizi
        score, confidence = self._analyzer.analyze(headline)

        # MT5 Calendar importance → confidence boost
        importance = raw.get("importance", 0)
        if importance >= 3:           # HIGH importance
            confidence = min(1.0, confidence * 1.25)
        elif importance >= 2:         # MODERATE importance
            confidence = min(1.0, confidence * 1.10)

        # Kategori tespiti
        category = self._detect_category(headline)

        # Cooldown kontrolü (MT5 Calendar toplu gelen haberler için skip)
        source = raw.get("source", "unknown")
        now = time.time()
        if source != "MT5":
            last_time = self._cooldowns.get(category, 0)
            if now - last_time < self._cooldown_sec and abs(score) < 0.8:
                # Çok güçlü haberler cooldown'u atlar
                return None
        self._cooldowns[category] = now

        # Sembol eşleştirme
        symbols = self._match_symbols(headline)
        is_global = self._is_global_news(headline)

        # Benzersiz ID
        event_id = f"{raw.get('source', 'unknown')}_{int(raw.get('timestamp', now))}_{hash(headline) % 100000}"

        return NewsEvent(
            headline=headline,
            source=raw.get("source", "unknown"),
            timestamp=raw.get("timestamp", now),
            category=category,
            sentiment_score=score,
            confidence=confidence,
            symbols=symbols,
            raw_text=raw_text,
            event_id=event_id,
            is_global=is_global,
        )

    def _detect_category(self, text: str) -> str:
        """Haber kategorisini belirle."""
        text_lower = self._normalize_turkish(text)

        jeopolitik = ["savaş", "savas", "barış", "baris", "nato", "trump",
                      "erdoğan", "erdogan", "iran", "rusya", "ukrayna",
                      "suriye", "çatışma", "catisma", "ambargo", "yaptırım",
                      "ateşkes", "ateskes", "müzakere", "seçim", "secim"]
        ekonomik = ["faiz", "enflasyon", "tcmb", "fed", "ecb", "imf",
                    "gdp", "büyüme", "buyume", "cari açık", "işsizlik",
                    "issizlik", "cpi", "ppi", "cds", "kredi notu"]
        sektorel = ["sektör", "sektor", "bankacılık", "bankacilik",
                    "enerji", "savunma", "otomotiv", "perakende",
                    "inşaat", "insaat", "turizm", "teknoloji"]

        for kw in jeopolitik:
            if kw in text_lower:
                return "JEOPOLITIK"
        for kw in ekonomik:
            if kw in text_lower:
                return "EKONOMIK"
        for kw in sektorel:
            if kw in text_lower:
                return "SEKTOREL"

        # Şirket ismi varsa SIRKET
        for symbol, keywords in SYMBOL_KEYWORDS.items():
            if not symbol.startswith("F_XU") and not symbol.startswith("F_USD"):
                for kw in keywords:
                    if kw in text_lower:
                        return "SIRKET"

        return "GENEL"

    @staticmethod
    def _normalize_turkish(text: str) -> str:
        """Türkçe karakterleri normalize et (Python İ→i̇ sorununu çözer).

        Python'da İ.lower() = 'i̇' (combining dot above), I.lower() = 'i'.
        Türkçe'de İ→i, I→ı olmalı ama biz keyword eşleştirmesinde
        her ikisini de 'i' olarak normalize ediyoruz.
        """
        # İ (noktalı büyük) → i
        text = text.replace("İ", "i")
        # Standart lower() (I→i, diğer tüm harfler)
        text = text.lower()
        # Python lower() bazen İ→i̇ (combining dot) üretebilir, temizle
        text = text.replace("i\u0307", "i")
        return text

    def _match_symbols(self, text: str) -> list[str]:
        """Haber metninden etkilenen sembolleri çıkar."""
        text_lower = self._normalize_turkish(text)
        matched = []

        for symbol, keywords in SYMBOL_KEYWORDS.items():
            for kw in keywords:
                if kw in text_lower:
                    if symbol not in matched:
                        matched.append(symbol)
                    break

        return matched

    def _is_global_news(self, text: str) -> bool:
        """Haberin tüm piyasayı etkileyip etkilemediğini belirle."""
        text_lower = self._normalize_turkish(text)
        return any(kw in text_lower for kw in GLOBAL_KEYWORDS)

    # ── Public: BABA Entegrasyonu ─────────────────────────────────

    def get_active_events(self) -> list[NewsEvent]:
        """Aktif (süresi dolmamış) tüm haberleri döndür."""
        return self._cache.get_active()

    def get_worst_event(self) -> Optional[NewsEvent]:
        """En kötü sentiment'li aktif haberi döndür."""
        return self._cache.get_worst_sentiment()

    def get_best_event(self) -> Optional[NewsEvent]:
        """En iyi sentiment'li aktif haberi döndür."""
        return self._cache.get_best_sentiment()

    def should_trigger_olay(self) -> Optional[dict]:
        """BABA _check_olay() için: OLAY rejimine geçmeli mi?

        Returns:
            {"reason": str, "trigger": "news", "sentiment": float, "event": NewsEvent}
            veya None.
        """
        worst = self.get_worst_event()
        if worst is None:
            return None

        if worst.sentiment_score <= self._olay_trigger and worst.confidence >= 0.6:
            return {
                "reason": f"Olumsuz haber: {worst.headline[:60]}",
                "trigger": "news",
                "sentiment": worst.sentiment_score,
                "severity": worst.severity,
                "event": worst,
            }
        return None

    def get_news_warnings(self) -> list[dict]:
        """BABA check_early_warnings() için NEWS_ALERT uyarıları.

        Returns:
            EarlyWarning oluşturmak için gereken veri listesi.
        """
        warnings = []
        for event in self.get_active_events():
            if event.sentiment_score < self._negative_threshold:
                severity = "CRITICAL" if event.severity in ("CRITICAL", "HIGH") else "WARNING"
                for symbol in event.symbols:
                    warnings.append({
                        "warning_type": "NEWS_ALERT",
                        "symbol": symbol,
                        "severity": severity,
                        "value": event.sentiment_score,
                        "threshold": self._negative_threshold,
                        "message": f"Olumsuz haber ({event.severity}): {event.headline[:50]}",
                        "event": event,
                    })
                # Global haber → tüm semboller için uyarı
                if event.is_global and not event.symbols:
                    warnings.append({
                        "warning_type": "NEWS_ALERT",
                        "symbol": "GLOBAL",
                        "severity": severity,
                        "value": event.sentiment_score,
                        "threshold": self._negative_threshold,
                        "message": f"Global olumsuz haber ({event.severity}): {event.headline[:50]}",
                        "event": event,
                    })
        return warnings

    def get_lot_multiplier(self, symbol: str) -> float:
        """Sembol için haber bazlı lot çarpanı.

        Sembol-spesifik ve global haberlerin en kötüsünü kullanır.
        Ayrıca, hiçbir sembolle eşleşmeyen ama severity'si yüksek
        haberleri de tüm semboller için uygular (piyasa geneli risk).

        Returns:
            0.0 .. 1.0 (1.0 = normal, 0.0 = işlem açılmaz)
        """
        # Sembol-spesifik + global haberler
        events = self._cache.get_active_for_symbol(symbol)

        # Ek: sembolsüz ve global olmayan ama ciddi haberler de
        # tüm piyasayı etkiler (örn: "savaş ilanı" sembolsüz gelirse)
        all_active = self._cache.get_active()
        for ev in all_active:
            if ev not in events and ev.severity in ("CRITICAL", "HIGH"):
                events.append(ev)

        if not events:
            return 1.0
        # En kötü haberin çarpanını kullan
        worst = min(events, key=lambda e: e.sentiment_score)
        return worst.lot_multiplier

    # ── Public: OĞUL (SE2) Entegrasyonu ────────────────────────────

    def get_signal_for_symbol(self, symbol: str) -> NewsSignal:
        """Belirli sembol için haber bazlı sinyal üret.

        SE2'nin 10. kaynağı olarak kullanılacak.

        Args:
            symbol: VİOP kontrat kodu (örn: "F_THYAO")

        Returns:
            NewsSignal: direction, score (0-20), confidence
        """
        events = self._cache.get_active_for_symbol(symbol)
        if not events:
            return NewsSignal()

        # En iyi pozitif haberi bul
        best = max(events, key=lambda e: e.sentiment_score)

        if best.sentiment_score < self._positive_threshold:
            return NewsSignal()

        if best.confidence < 0.7:
            return NewsSignal()

        # Base skor hesapla
        cat_mult = CATEGORY_MULTIPLIERS.get(best.category, 1.0)
        base_score = best.sentiment_score * best.confidence * cat_mult * 20.0

        # Alpha decay uygula
        decayed_score = base_score * math.exp(-self._decay_rate * best.age_seconds)

        # Minimum skor kontrolü
        if decayed_score < 2.0:
            return NewsSignal()

        direction = "BUY" if best.sentiment_score > 0 else "SELL"

        return NewsSignal(
            direction=direction,
            score=min(decayed_score, 20.0),  # Max 20
            confidence=best.confidence,
            source_event=best,
            decay_applied=True,
        )

    # ── Public: Dashboard / API ────────────────────────────────────

    def get_status(self) -> dict:
        """Dashboard ve API için durum bilgisi."""
        active = self.get_active_events()
        worst = self.get_worst_event()
        best = self.get_best_event()

        return {
            "enabled": self._enabled,
            "provider_count": len(self._providers),
            "active_news_count": len(active),
            "total_processed": self._total_processed,
            "total_positive": self._total_positive,
            "total_negative": self._total_negative,
            "last_cycle_events": self._last_cycle_events,
            "worst_sentiment": worst.sentiment_score if worst else None,
            "worst_headline": worst.headline[:80] if worst else None,
            "worst_severity": worst.severity if worst else None,
            "best_sentiment": best.sentiment_score if best else None,
            "best_headline": best.headline[:80] if best else None,
            "active_events": [e.to_dict() for e in active],
        }

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def active_count(self) -> int:
        return self._cache.count


# ═════════════════════════════════════════════════════════════════════
#  PRE-MARKET BRIEFİNG SİSTEMİ
# ═════════════════════════════════════════════════════════════════════

class PreMarketBriefing:
    """Gece boyunca biriken haberleri analiz edip sabah seansı öncesinde
    BABA, OĞUL ve ÜSTAT motorlarına hazırlık sinyalleri üretir.

    Kullanım:
        - Engine her cycle'da (10s) PreMarketBriefing.check() çağırır
        - 09:30-09:45 arasında (seans öncesi) briefing aktif olur
        - overnight_events'i tarar → risk_score + opportunity_score hesaplar
        - BABA'ya giriş rejimi önerir (NORMAL / DİKKAT / TEHLİKE)
        - OĞUL'a fırsat sinyali gönderir
        - Sonuçları JSON dosyasına yazar (dashboard için)
    """

    # Sabah briefing penceresi (dakika cinsinden seans açılışına göre)
    BRIEFING_WINDOW_BEFORE_MIN = 15   # Seanstan 15 dk önce başla
    BRIEFING_WINDOW_AFTER_MIN  = 5    # Seanstan 5 dk sonrasına kadar geçerli

    # Risk seviyeleri
    RISK_NORMAL   = "NORMAL"     # Risk skoru < 30
    RISK_DIKKAT   = "DIKKAT"     # Risk skoru 30-60
    RISK_TEHLIKE  = "TEHLIKE"    # Risk skoru > 60

    def __init__(self, news_bridge: NewsBridge, config=None):
        self._nb = news_bridge
        self._config = config
        self._last_briefing_date: str = ""
        self._briefing_result: Optional[dict] = None
        self._trading_open = self._parse_time(
            self._cfg("session_filter.trading_open", "09:45")
        )
        self._output_dir = self._cfg("news.premarket_output_dir", "logs")

    def _cfg(self, key: str, default: Any = None) -> Any:
        if self._config is None:
            return default
        return self._config.get(key, default)

    @staticmethod
    def _parse_time(time_str: str) -> tuple[int, int]:
        """'HH:MM' → (hour, minute)"""
        parts = time_str.split(":")
        return int(parts[0]), int(parts[1])

    def check(self) -> Optional[dict]:
        """Her engine cycle'da çağrılır. Briefing zamanıysa analiz yapar.

        Returns:
            Briefing sonuç dict'i veya None (henüz zamanı değilse / bugün zaten yapıldıysa)
        """
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")

        # Bugün zaten yapıldıysa tekrar yapma
        if self._last_briefing_date == today_str:
            return self._briefing_result

        # Briefing penceresi kontrolü
        open_h, open_m = self._trading_open
        open_minutes = open_h * 60 + open_m
        now_minutes = now.hour * 60 + now.minute

        window_start = open_minutes - self.BRIEFING_WINDOW_BEFORE_MIN
        window_end = open_minutes + self.BRIEFING_WINDOW_AFTER_MIN

        if not (window_start <= now_minutes <= window_end):
            return None

        # Briefing zamanı geldi — analiz yap
        logger.info("[PreMarket] Sabah briefing başlatılıyor...")
        result = self._generate_briefing(now)
        self._last_briefing_date = today_str
        self._briefing_result = result

        # JSON'a yaz
        self._save_briefing(result, today_str)

        return result

    def _generate_briefing(self, now: datetime) -> dict:
        """Gece haberlerini analiz et, risk ve fırsat skorlarını hesapla."""

        # MT5FileProvider'dan tüm haberleri oku (max_age filtresi olmadan)
        # Cache'teki aktif + dosyadaki tüm overnight haberler
        overnight_events = self._collect_overnight_events(now)

        if not overnight_events:
            result = {
                "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M"),
                "overnight_count": 0,
                "risk_score": 0.0,
                "opportunity_score": 0.0,
                "risk_level": self.RISK_NORMAL,
                "baba_recommendation": "NORMAL giriş — gece haber yok",
                "ogul_recommendation": "Standart strateji",
                "key_events": [],
                "summary": "Gece boyunca önemli haber akışı olmadı. Normal açılış bekleniyor.",
            }
            logger.info("[PreMarket] Gece haberi yok — NORMAL giriş")
            return result

        # Risk ve fırsat hesapla
        risk_score = 0.0
        opportunity_score = 0.0
        key_events = []

        for ev in overnight_events:
            weight = 1.0
            # Importance bazlı ağırlık
            imp = getattr(ev, '_importance', 0)
            if imp >= 3:
                weight = 2.0
            elif imp >= 2:
                weight = 1.5

            if ev.sentiment_score < 0:
                # Negatif haber → risk
                risk_score += abs(ev.sentiment_score) * ev.confidence * weight * 100
            else:
                # Pozitif haber → fırsat
                opportunity_score += ev.sentiment_score * ev.confidence * weight * 100

            # Yüksek önem veya güçlü sentiment → key event
            if imp >= 2 or abs(ev.sentiment_score) > 0.5:
                key_events.append({
                    "headline": ev.headline,
                    "sentiment": round(ev.sentiment_score, 3),
                    "confidence": round(ev.confidence, 3),
                    "category": ev.category,
                    "symbols": ev.symbols,
                    "is_global": ev.is_global,
                    "severity": ev.severity,
                })

        # Normalize (0-100 aralığı)
        risk_score = min(100.0, risk_score)
        opportunity_score = min(100.0, opportunity_score)

        # Risk seviyesi
        if risk_score > 60:
            risk_level = self.RISK_TEHLIKE
        elif risk_score > 30:
            risk_level = self.RISK_DIKKAT
        else:
            risk_level = self.RISK_NORMAL

        # BABA önerisi
        baba_rec = self._baba_recommendation(risk_level, risk_score, key_events)

        # OĞUL önerisi
        ogul_rec = self._ogul_recommendation(opportunity_score, risk_level, key_events)

        # Özet
        summary = self._build_summary(
            overnight_events, risk_score, opportunity_score, risk_level
        )

        result = {
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M"),
            "overnight_count": len(overnight_events),
            "risk_score": round(risk_score, 1),
            "opportunity_score": round(opportunity_score, 1),
            "risk_level": risk_level,
            "baba_recommendation": baba_rec,
            "ogul_recommendation": ogul_rec,
            "key_events": key_events[:10],  # En fazla 10 key event
            "summary": summary,
        }

        logger.info(
            f"[PreMarket] Briefing tamamlandı: "
            f"{len(overnight_events)} haber, risk={risk_score:.0f}, "
            f"fırsat={opportunity_score:.0f}, seviye={risk_level}"
        )

        return result

    def _collect_overnight_events(self, now: datetime) -> list[NewsEvent]:
        """Cache'teki aktif haberler + dosyadan gece haberleri."""
        events = list(self._nb.get_active_events())

        # MT5 dosyasından direkt oku (max_age sınırı olmadan)
        for provider in self._nb._providers:
            if isinstance(provider, MT5FileProvider):
                try:
                    path = Path(provider._file_path)
                    if not path.exists():
                        continue
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    # Gece saatleri: dünkü seans kapanışından bugünkü açılışa kadar
                    yesterday_close = now.replace(
                        hour=18, minute=0, second=0, microsecond=0
                    )
                    if now.hour < 18:
                        from datetime import timedelta
                        yesterday_close -= timedelta(days=1)

                    for item in data:
                        ts = item.get("time", 0)
                        if yesterday_close.timestamp() <= ts <= now.timestamp():
                            headline = item.get("headline", "")
                            if not headline:
                                continue
                            # Sentiment analizi
                            score, conf = self._nb._analyzer.analyze(headline)
                            imp = item.get("importance", 0)
                            if imp >= 3:
                                conf = min(1.0, conf * 1.25)

                            event = NewsEvent(
                                headline=headline,
                                source="MT5_OVERNIGHT",
                                timestamp=ts,
                                category=self._nb._detect_category(headline),
                                sentiment_score=score,
                                confidence=conf,
                                symbols=self._nb._match_symbols(headline),
                                is_global=self._nb._is_global_news(headline),
                                event_id=f"overnight_{item.get('id', hash(headline) % 100000)}",
                            )
                            event._importance = imp
                            events.append(event)

                except Exception as e:
                    logger.warning(f"[PreMarket] Overnight dosya okuma hatası: {e}")

        # Duplicate'leri kaldır (headline bazlı)
        seen = set()
        unique = []
        for ev in events:
            if ev.headline not in seen:
                seen.add(ev.headline)
                unique.append(ev)

        return unique

    def _baba_recommendation(self, risk_level: str, risk_score: float,
                              key_events: list[dict]) -> str:
        """BABA motoru için giriş önerisi."""
        if risk_level == self.RISK_TEHLIKE:
            global_events = [e for e in key_events if e.get("is_global")]
            if global_events:
                return (
                    f"TEHLİKE — Risk skoru: {risk_score:.0f}/100. "
                    f"Global risk haberleri var. "
                    f"Lot çarpanı ×0.3 önerisi. İlk 5 dakika işlem açma. "
                    f"OLAY rejimi hazır tut."
                )
            return (
                f"TEHLİKE — Risk skoru: {risk_score:.0f}/100. "
                f"Lot çarpanı ×0.5 önerisi. Dikkatli giriş."
            )
        elif risk_level == self.RISK_DIKKAT:
            return (
                f"DİKKAT — Risk skoru: {risk_score:.0f}/100. "
                f"Lot çarpanı ×0.7 önerisi. Normal giriş ama L1 uyarı aktif."
            )
        return "NORMAL giriş — Gece risk haberi düşük seviyede."

    def _ogul_recommendation(self, opp_score: float, risk_level: str,
                              key_events: list[dict]) -> str:
        """OĞUL motoru için fırsat önerisi."""
        if risk_level == self.RISK_TEHLIKE:
            return "BEKLE — Risk çok yüksek, fırsat sinyalleri bastırılıyor."

        positive_events = [e for e in key_events if e.get("sentiment", 0) > 0.3]
        if opp_score > 50 and positive_events:
            symbols = set()
            for e in positive_events:
                symbols.update(e.get("symbols", []))
            sym_str = ", ".join(symbols) if symbols else "genel piyasa"
            return (
                f"FIRSAT — Skor: {opp_score:.0f}/100. "
                f"Pozitif haberler: {sym_str}. "
                f"SE2 haber kaynağı aktif, BUY bias hazır."
            )
        elif opp_score > 20:
            return f"HAFİF POZİTİF — Skor: {opp_score:.0f}/100. Standart strateji."

        return "Standart strateji — belirgin fırsat sinyali yok."

    def _build_summary(self, events: list[NewsEvent], risk: float,
                        opp: float, level: str) -> str:
        """Türkçe özet metin oluştur."""
        total = len(events)
        neg = sum(1 for e in events if e.sentiment_score < -0.3)
        pos = sum(1 for e in events if e.sentiment_score > 0.3)
        neutral = total - neg - pos

        parts = [
            f"Gece boyunca {total} haber tespit edildi",
            f"({pos} olumlu, {neg} olumsuz, {neutral} nötr).",
        ]

        if level == self.RISK_TEHLIKE:
            parts.append(
                f"Risk seviyesi TEHLİKE ({risk:.0f}/100). "
                "Seans açılışında dikkatli olunmalı."
            )
        elif level == self.RISK_DIKKAT:
            parts.append(
                f"Risk seviyesi DİKKAT ({risk:.0f}/100). "
                "Normal açılış bekleniyor ancak izleme gerekli."
            )
        else:
            parts.append("Normal açılış bekleniyor.")

        if opp > 40:
            parts.append(f"Fırsat skoru: {opp:.0f}/100 — pozitif sinyaller mevcut.")

        return " ".join(parts)

    def _save_briefing(self, result: dict, date_str: str) -> None:
        """Briefing sonucunu JSON'a yaz."""
        try:
            out_dir = Path(self._output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"premarket_briefing_{date_str}.json"

            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            logger.info(f"[PreMarket] Briefing kaydedildi: {out_path}")
        except Exception as e:
            logger.error(f"[PreMarket] Briefing kayıt hatası: {e}")

    def get_latest_briefing(self) -> Optional[dict]:
        """Dashboard/API için en son briefing sonucunu döndür."""
        return self._briefing_result

    def force_briefing(self) -> dict:
        """Manuel tetikleme — test ve geliştirme için."""
        result = self._generate_briefing(datetime.now())
        self._briefing_result = result
        self._last_briefing_date = datetime.now().strftime("%Y-%m-%d")
        self._save_briefing(result, self._last_briefing_date)
        return result
