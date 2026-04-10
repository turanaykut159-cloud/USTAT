"""ÜSTAT — MT5 Retcode Registry ve kullanıcı dostu hata mesajları.

Bu modül MT5 `order_send` ve `order_check` dönüş kodlarını (retcode) anlamlı,
kullanıcı odaklı mesajlara çevirir. Kuru teknik mesaj ("retcode=10027") yerine
"MT5 terminalinde Algo Trading butonu kapalı. Ctrl+E ile açın." gibi net
eylem talimatı üretir.

Amacı:
    1. Modal'larda kör hata gösterimini bitirmek
    2. Kullanıcıya TAM OLARAK ne yapması gerektiğini söylemek
    3. Log mesajlarının da aynı kelime dağarcığına oturmasını sağlamak
    4. Yeni retcode'ları tek yerden eklemeyi mümkün kılmak

Kullanım:
    >>> from engine.mt5_errors import describe_mt5_error, enrich_message
    >>> info = describe_mt5_error(10027, "AutoTrading disabled by client")
    >>> print(info["user_message"])
    'MT5 terminalinde Algo Trading butonu kapalı...'

Kaynaklar:
    MetaQuotes — Trade Server Return Codes tablosu
    https://www.mql5.com/en/docs/constants/errorswarnings/enum_trade_return_codes
"""

from __future__ import annotations

from typing import Any

# ═══════════════════════════════════════════════════════════════════
#  EYLEM KATEGORİLERİ
# ═══════════════════════════════════════════════════════════════════

# Kullanıcı bu hatayı tarafında düzeltmeli (terminal ayarı, bağlantı vb.)
ACTION_USER_FIX = "user_fix"

# Config/kod değişikliği gerekli — geliştirici müdahalesi
ACTION_CONFIG_FIX = "config_fix"

# Geçici — tekrar denenebilir (ağ, slippage, market kapalı)
ACTION_RETRY = "retry"

# Broker kabul etmedi — iş mantığı hatası, emir iptal
ACTION_REJECT = "reject"

# Fatal — çağrı zinciri kesilsin, log kaydı yeterli
ACTION_FATAL = "fatal"


# ═══════════════════════════════════════════════════════════════════
#  REGISTRY — MT5 retcode → kullanıcı mesajı eşleşmesi
# ═══════════════════════════════════════════════════════════════════
#
# Anahtar: MT5 TRADE_RETCODE_* sabitinin sayısal değeri
# Değer: {
#   "code":         MT5 sabiti adı (debug için)
#   "tech":         Kısa teknik açıklama (log için)
#   "user_message": Kullanıcıya gösterilecek net mesaj (modal için)
#   "hint":         Kullanıcının TAM OLARAK ne yapması gerektiği (modal altı)
#   "action":       Eylem kategorisi (yukarıdaki ACTION_* sabitleri)
# }

MT5_ERROR_REGISTRY: dict[int, dict[str, str]] = {
    10004: {
        "code": "TRADE_RETCODE_REQUOTE",
        "tech": "Fiyat değişti — requote",
        "user_message": "Fiyat değişti, işlem tekrar denenecek.",
        "hint": "Bu geçici bir hatadır. Sistem otomatik yeniden dener.",
        "action": ACTION_RETRY,
    },
    10006: {
        "code": "TRADE_RETCODE_REJECT",
        "tech": "İstek broker tarafından reddedildi",
        "user_message": "Broker işlemi reddetti.",
        "hint": "Lütfen MT5 terminalindeki ayrıntılı mesajı kontrol edin.",
        "action": ACTION_REJECT,
    },
    10007: {
        "code": "TRADE_RETCODE_CANCEL",
        "tech": "İstek işlemci tarafından iptal edildi",
        "user_message": "İşlem iptal edildi.",
        "hint": "Tekrar denenebilir.",
        "action": ACTION_RETRY,
    },
    10010: {
        "code": "TRADE_RETCODE_DONE_PARTIAL",
        "tech": "Kısmi dolum",
        "user_message": "Emir kısmi olarak doldu.",
        "hint": "Kalan miktar için ek emir gerekebilir.",
        "action": ACTION_RETRY,
    },
    10013: {
        "code": "TRADE_RETCODE_INVALID",
        "tech": "Geçersiz istek",
        "user_message": "Geçersiz emir isteği.",
        "hint": "Fiyat veya lot parametreleri hatalı — geliştirici kontrolü gerekli.",
        "action": ACTION_CONFIG_FIX,
    },
    10014: {
        "code": "TRADE_RETCODE_INVALID_VOLUME",
        "tech": "Geçersiz lot",
        "user_message": "Lot miktarı geçersiz.",
        "hint": "Lot, sembolün min/max/step değerlerine uygun olmalı. Config'teki risk_per_trade_pct kontrol edilmeli.",
        "action": ACTION_CONFIG_FIX,
    },
    10015: {
        "code": "TRADE_RETCODE_INVALID_PRICE",
        "tech": "Geçersiz fiyat",
        "user_message": "Emir fiyatı geçersiz.",
        "hint": "Fiyat, güncel piyasa fiyatına veya tick_size'a uygun değil. Kontrat vadeye yakın olabilir.",
        "action": ACTION_REJECT,
    },
    10016: {
        "code": "TRADE_RETCODE_INVALID_STOPS",
        "tech": "Geçersiz SL/TP seviyeleri",
        "user_message": "SL/TP seviyeleri kabul edilmedi.",
        "hint": "SL veya TP fiyata çok yakın (stop_level kuralı). ATR çarpanı artırılabilir.",
        "action": ACTION_REJECT,
    },
    10017: {
        "code": "TRADE_RETCODE_TRADE_DISABLED",
        "tech": "İşlem devre dışı",
        "user_message": "Bu sembolde işlem devre dışı.",
        "hint": "Kontrat vadesi dolmuş veya broker devre dışı bırakmış olabilir. Farklı vade denenebilir.",
        "action": ACTION_REJECT,
    },
    10018: {
        "code": "TRADE_RETCODE_MARKET_CLOSED",
        "tech": "Piyasa kapalı",
        "user_message": "Piyasa şu anda kapalı.",
        "hint": "VİOP işlem saatleri: 09:30 – 18:15. Sonraki seansı bekleyin.",
        "action": ACTION_RETRY,
    },
    10019: {
        "code": "TRADE_RETCODE_NO_MONEY",
        "tech": "Yetersiz bakiye",
        "user_message": "Hesap bakiyesi yetersiz.",
        "hint": "Teminat ihtiyacı karşılanmıyor. Mevcut pozisyonları azaltın veya ek teminat yatırın.",
        "action": ACTION_REJECT,
    },
    10020: {
        "code": "TRADE_RETCODE_PRICE_CHANGED",
        "tech": "Fiyat değişti",
        "user_message": "Fiyat değişti, emir yeniden denenecek.",
        "hint": "Geçici — sistem otomatik tekrar dener.",
        "action": ACTION_RETRY,
    },
    10021: {
        "code": "TRADE_RETCODE_PRICE_OFF",
        "tech": "Fiyat güncel değil",
        "user_message": "Fiyat alınamadı, piyasa hareketi durmuş olabilir.",
        "hint": "Birkaç saniye bekleyin, sistem yeniden dener.",
        "action": ACTION_RETRY,
    },
    10022: {
        "code": "TRADE_RETCODE_INVALID_EXPIRATION",
        "tech": "Geçersiz expiration",
        "user_message": "Emir geçerlilik süresi broker tarafından kabul edilmedi.",
        "hint": "type_time parametresi ORDER_TIME_DAY yapılmalı (GCM VİOP).",
        "action": ACTION_CONFIG_FIX,
    },
    10023: {
        "code": "TRADE_RETCODE_ORDER_CHANGED",
        "tech": "Durum değişti",
        "user_message": "Emir durumu güncellenmeden önce değişti.",
        "hint": "Broker tarafında eşzamanlı değişiklik oldu. Tekrar deneyin.",
        "action": ACTION_RETRY,
    },
    10024: {
        "code": "TRADE_RETCODE_TOO_MANY_REQUESTS",
        "tech": "İstek yağmuru",
        "user_message": "Çok fazla istek gönderildi, broker frenledi.",
        "hint": "Kısa bir bekleme sonrası tekrar denenir.",
        "action": ACTION_RETRY,
    },
    10025: {
        "code": "TRADE_RETCODE_NO_CHANGES",
        "tech": "Değişiklik yok",
        "user_message": "Emirde değiştirilecek bir şey yok.",
        "hint": "Gönderilen değerler mevcut değerlerle aynı.",
        "action": ACTION_REJECT,
    },
    10026: {
        "code": "TRADE_RETCODE_SERVER_DISABLES_AT",
        "tech": "Sunucu AutoTrading kapalı",
        "user_message": "Broker sunucusu otomatik işlemi devre dışı bırakmış.",
        "hint": "Bu broker tarafı bir ayardır. GCM destek ekibiyle iletişime geçin.",
        "action": ACTION_USER_FIX,
    },
    10027: {
        "code": "TRADE_RETCODE_CLIENT_DISABLES_AT",
        "tech": "MT5 Algo Trading kapalı",
        "user_message": "MT5 terminalinde Algo Trading butonu KAPALI.",
        "hint": (
            "MT5 penceresini açın, üstteki araç çubuğunda 'Algo Trading' butonuna "
            "tıklayın (veya Ctrl+E). Buton yeşil olduğunda ÜSTAT emir gönderebilir. "
            "Her MT5 restart'ından sonra bu ayar sıfırlanabilir."
        ),
        "action": ACTION_USER_FIX,
    },
    10028: {
        "code": "TRADE_RETCODE_LOCKED",
        "tech": "İstek kilitli",
        "user_message": "İstek broker tarafında kilitlendi.",
        "hint": "Bir önceki istek işlenirken yeni istek geldi. Tekrar denenir.",
        "action": ACTION_RETRY,
    },
    10029: {
        "code": "TRADE_RETCODE_FROZEN",
        "tech": "Emir/pozisyon dondurulmuş",
        "user_message": "Emir veya pozisyon dondurulmuş.",
        "hint": "Broker tarafından bakım veya risk sebebiyle dondurulmuş.",
        "action": ACTION_REJECT,
    },
    10030: {
        "code": "TRADE_RETCODE_INVALID_FILL",
        "tech": "Geçersiz fill tipi",
        "user_message": "Dolum tipi kabul edilmedi.",
        "hint": "type_filling ORDER_FILLING_RETURN olmalı (GCM VİOP).",
        "action": ACTION_CONFIG_FIX,
    },
    10031: {
        "code": "TRADE_RETCODE_CONNECTION",
        "tech": "Bağlantı yok",
        "user_message": "MT5 terminali broker'a bağlı değil.",
        "hint": "MT5 penceresini kontrol edin. Sağ altta yeşil bağlantı göstergesi olmalı.",
        "action": ACTION_USER_FIX,
    },
    10032: {
        "code": "TRADE_RETCODE_ONLY_REAL",
        "tech": "Yalnız gerçek hesap",
        "user_message": "Bu işlem yalnızca gerçek hesapta yapılabilir.",
        "hint": "Demo hesapta bu işlem desteklenmiyor.",
        "action": ACTION_REJECT,
    },
    10033: {
        "code": "TRADE_RETCODE_LIMIT_ORDERS",
        "tech": "Bekleyen emir limiti",
        "user_message": "Bekleyen emir sayısı limite ulaştı.",
        "hint": "Broker tarafındaki maks bekleyen emir sayısı aşıldı.",
        "action": ACTION_REJECT,
    },
    10034: {
        "code": "TRADE_RETCODE_LIMIT_VOLUME",
        "tech": "Toplam hacim limiti",
        "user_message": "Sembolde toplam pozisyon hacmi limite ulaştı.",
        "hint": "Aynı sembolde daha fazla pozisyon açılamaz. Mevcut pozisyon azaltılmalı.",
        "action": ACTION_REJECT,
    },
    10035: {
        "code": "TRADE_RETCODE_INVALID_ORDER",
        "tech": "Geçersiz emir tipi",
        "user_message": "Bu emir tipi broker tarafından kabul edilmiyor.",
        "hint": (
            "GCM VİOP düz STOP emirlerini kabul etmez, yalnızca STOP LIMIT. "
            "Config'te hybrid.native_sltp=false olmalı ve use_stop_limit=true."
        ),
        "action": ACTION_CONFIG_FIX,
    },
    10036: {
        "code": "TRADE_RETCODE_POSITION_CLOSED",
        "tech": "Pozisyon zaten kapalı",
        "user_message": "Pozisyon zaten kapatılmış.",
        "hint": "Bu işlem için gerekli pozisyon bulunamadı — eşzamanlı kapanmış olabilir.",
        "action": ACTION_REJECT,
    },
    10038: {
        "code": "TRADE_RETCODE_INVALID_CLOSE_VOLUME",
        "tech": "Geçersiz kapanış hacmi",
        "user_message": "Kapatma hacmi pozisyondan farklı.",
        "hint": "Kısmi kapanış hatalı — tüm pozisyonu kapatın.",
        "action": ACTION_REJECT,
    },
    10039: {
        "code": "TRADE_RETCODE_CLOSE_ORDER_EXIST",
        "tech": "Kapatma emri zaten var",
        "user_message": "Bu pozisyon için açık bir kapatma emri mevcut.",
        "hint": "Önceki kapatma işlemi bitmeden yenisi gönderilemez.",
        "action": ACTION_REJECT,
    },
    10040: {
        "code": "TRADE_RETCODE_LIMIT_POSITIONS",
        "tech": "Pozisyon limiti",
        "user_message": "Maksimum açık pozisyon sayısı aşıldı.",
        "hint": "Yeni pozisyon açmak için mevcut bir pozisyonu kapatın.",
        "action": ACTION_REJECT,
    },
    10041: {
        "code": "TRADE_RETCODE_REJECT_CANCEL",
        "tech": "Pending emir iptali reddedildi",
        "user_message": "Bekleyen emir iptali reddedildi.",
        "hint": "Emir zaten tetiklenmiş veya broker tarafında işleniyor olabilir.",
        "action": ACTION_REJECT,
    },
    10044: {
        "code": "TRADE_RETCODE_HEDGE_PROHIBITED",
        "tech": "Hedge yasak",
        "user_message": "Bu hesapta hedge (ters yön) işlemi yasaktır.",
        "hint": "VİOP netting modundadır — aynı sembolde ters yön pozisyon açılamaz.",
        "action": ACTION_REJECT,
    },
}


# ═══════════════════════════════════════════════════════════════════
#  PUBLIC API
# ═══════════════════════════════════════════════════════════════════

def describe_mt5_error(
    retcode: int | None = None,
    comment: str | None = None,
    last_error: Any | None = None,
    exception: Any | None = None,
) -> dict[str, str]:
    """MT5 hatasını yapısal olarak çöz.

    Args:
        retcode: MT5 order_send / order_check dönüş kodu.
        comment: Broker tarafından döndürülen serbest metin.
        last_error: ``mt5.last_error()`` çağrısının sonucu.
        exception: Çağrı istisna attıysa onun metni.

    Returns:
        ``{"code", "tech", "user_message", "hint", "action", "retcode"}``
        anahtarlı sözlük. Tanımsız bir retcode için "Bilinmeyen MT5 hatası"
        girdisi döner ve teknik detaylar hint'e eklenir.
    """
    info: dict[str, str] = {
        "code": "UNKNOWN",
        "tech": "Bilinmeyen MT5 hatası",
        "user_message": "MT5 işlemi başarısız oldu.",
        "hint": "",
        "action": ACTION_FATAL,
        "retcode": str(retcode) if retcode is not None else "",
    }

    if retcode is not None and retcode in MT5_ERROR_REGISTRY:
        entry = MT5_ERROR_REGISTRY[retcode]
        info["code"] = entry["code"]
        info["tech"] = entry["tech"]
        info["user_message"] = entry["user_message"]
        info["hint"] = entry["hint"]
        info["action"] = entry["action"]

    # Broker comment varsa hint'in sonuna düş
    extras: list[str] = []
    if comment:
        extras.append(f"Broker: {comment}")
    if last_error:
        extras.append(f"MT5: {last_error}")
    if exception:
        extras.append(f"İstisna: {exception}")

    if extras:
        if info["hint"]:
            info["hint"] = info["hint"] + "\n\n" + " | ".join(extras)
        else:
            info["hint"] = " | ".join(extras)

    return info


def enrich_message(base_message: str, error_detail: dict[str, Any] | None) -> str:
    """Taban hata mesajına zengin MT5 açıklaması ekle.

    Bu yardımcı, ``mt5_bridge._last_*_error`` gibi hata sözlüklerini
    kullanıcıya gösterilecek çok satırlı mesaja çevirir.

    Args:
        base_message: Zenginleştirilecek taban mesaj (ör. "Devir iptal").
        error_detail: ``_last_modify_error``, ``_last_stop_limit_error`` gibi
            dict. ``{"retcode", "comment", "last_error", "exception"}`` alanları
            olabilir.

    Returns:
        Çok satırlı, kullanıcı dostu mesaj. ``error_detail`` boşsa taban
        mesaj olduğu gibi döner.
    """
    if not error_detail:
        return base_message

    info = describe_mt5_error(
        retcode=error_detail.get("retcode"),
        comment=error_detail.get("comment"),
        last_error=error_detail.get("last_error"),
        exception=error_detail.get("exception"),
    )

    lines: list[str] = [base_message]

    # MT5 açıklaması
    if info["user_message"] and info["user_message"] != "MT5 işlemi başarısız oldu.":
        lines.append("")
        lines.append(f"Neden: {info['user_message']}")
    elif info["tech"] != "Bilinmeyen MT5 hatası":
        lines.append("")
        lines.append(f"Neden: {info['tech']}")

    # Hint
    if info["hint"]:
        lines.append("")
        lines.append(f"Nasıl düzeltilir: {info['hint']}")

    # Teknik koda her zaman son satırda yer ver
    retcode_str = info.get("retcode", "")
    if retcode_str:
        lines.append("")
        lines.append(f"[MT5 retcode={retcode_str} — {info['code']}]")

    return "\n".join(lines)


def user_action_for(retcode: int | None) -> str:
    """Bir retcode için beklenen kullanıcı eylem kategorisini döndür.

    Args:
        retcode: MT5 retcode.

    Returns:
        ACTION_* sabitlerinden biri.
    """
    if retcode is None or retcode not in MT5_ERROR_REGISTRY:
        return ACTION_FATAL
    return MT5_ERROR_REGISTRY[retcode]["action"]


__all__ = [
    "ACTION_USER_FIX",
    "ACTION_CONFIG_FIX",
    "ACTION_RETRY",
    "ACTION_REJECT",
    "ACTION_FATAL",
    "MT5_ERROR_REGISTRY",
    "describe_mt5_error",
    "enrich_message",
    "user_action_for",
]
