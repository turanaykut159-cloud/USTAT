"""
MT5 OTP Otomasyon Script'i.

USTAT Electron uygulamasindan subprocess olarak cagrilir.
win32gui ile MT5 OTP dialog'unu bulur, OTP'yi yazar ve onaylar.

Pencere tespiti:
  - MT5 ana pencere: class adi "MetaQuotes::MetaTrader" ile bulunur
  - OTP dialog: ayni PID'e ait top-level #32770, baslik "&Giris..."
  - OTP Edit: "Tek kullanimlik sifre:" Static label'indan sonraki Edit
  - OK butonu: "Tamam" baslikli Button

Kullanim:
    python mt5_automator.py --otp 123456
    python mt5_automator.py --check

Cikis kodlari:
    0: Basarili
    1: MT5 penceresi bulunamadi
    2: OTP dialog'u bulunamadi
    3: OTP girisi basarisiz
    4: Genel hata
"""

import argparse
import json
import sys
import time

import win32gui
import win32con
import win32process


# ── MT5 ana pencere tespiti ───────────────────────────────────────

def find_mt5_hwnd():
    """
    MT5 ana penceresini bul.
    Class adi "MetaQuotes::MetaTrader" iceren pencereyi arar.
    """
    result = {"hwnd": None}

    def callback(hwnd, _):
        try:
            if "MetaQuotes::MetaTrader" in win32gui.GetClassName(hwnd):
                result["hwnd"] = hwnd
                return False
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(callback, None)
    except Exception:
        pass

    return result["hwnd"]


def get_mt5_pid(mt5_hwnd):
    """MT5 penceresinin PID'ini al."""
    try:
        _, pid = win32process.GetWindowThreadProcessId(mt5_hwnd)
        return pid
    except Exception:
        return None


# ── OTP dialog tespiti ────────────────────────────────────────────

def find_login_dialog(mt5_pid):
    """
    MT5'in giris dialog'unu bul.

    GCM MT5'te bu dialog:
      - Ayri bir top-level pencere (MT5'in child'i degil)
      - Ayni PID'e ait
      - Class: #32770
      - Baslik: "&Giris..." veya "Giris" iceren

    Baslik eslesme olmazsa, ayni PID'e ait gorunur #32770 dialog da kabul edilir.
    """
    if mt5_pid is None:
        return None

    candidates = []

    def callback(hwnd, results):
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid != mt5_pid:
                return True

            cls = win32gui.GetClassName(hwnd)
            if cls != "#32770":
                return True

            visible = win32gui.IsWindowVisible(hwnd)
            if not visible:
                return True

            title = win32gui.GetWindowText(hwnd)
            results.append({"hwnd": hwnd, "title": title})
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(callback, candidates)
    except Exception:
        pass

    if not candidates:
        return None

    # Oncelik: baslikta "giris" veya "login" olan
    for c in candidates:
        t = c["title"].lower().replace("&", "")
        if "giris" in t or "giri" in t or "login" in t:
            return c["hwnd"]

    # Yoksa baslikli herhangi bir #32770
    for c in candidates:
        if c["title"].strip():
            return c["hwnd"]

    # Son care: ilk gorunur #32770
    return candidates[0]["hwnd"]


def find_otp_edit(dialog_hwnd):
    """
    Giris dialog'unda OTP Edit kontrolunu bul.

    Yontem: Dialog'un direkt child'larini sirayla gez.
    "Tek kullanimlik" iceren Static'i bul, ondan sonraki ilk Edit = OTP alani.
    """
    # Direkt child'lari sirayla gez (GetWindow ile, recursive degil)
    children = []
    child = win32gui.GetWindow(dialog_hwnd, win32con.GW_CHILD)
    while child:
        try:
            cls = win32gui.GetClassName(child)
            title = win32gui.GetWindowText(child)
            visible = win32gui.IsWindowVisible(child)
            children.append({"hwnd": child, "class": cls, "title": title, "visible": visible})
        except Exception:
            pass
        try:
            child = win32gui.GetWindow(child, win32con.GW_HWNDNEXT)
        except Exception:
            break

    # "Tek kullanimlik" label'ini bul, sonraki Edit'i al
    found_label = False
    for c in children:
        if found_label and c["class"] == "Edit":
            return c["hwnd"]
        if c["class"] == "Static" and "tek kullan" in c["title"].lower():
            found_label = True

    return None


def find_ok_button(dialog_hwnd):
    """
    Giris dialog'unda Tamam/OK butonunu bul.
    """
    result = {"hwnd": None}

    def callback(hwnd, _):
        try:
            if win32gui.GetClassName(hwnd) != "Button":
                return True
            title = win32gui.GetWindowText(hwnd).lower()
            if title in ("tamam", "ok"):
                result["hwnd"] = hwnd
                return False
        except Exception:
            pass
        return True

    try:
        win32gui.EnumChildWindows(dialog_hwnd, callback, None)
    except Exception:
        pass

    return result["hwnd"]


# ── OTP gonder ────────────────────────────────────────────────────

def send_otp(otp_code):
    """
    MT5 Giris dialog'una OTP kodunu gonder.

    Adimlar:
      0. Admin kontrolu (UIPI: normal user -> admin pencereye mesaj gonderemez)
      1. MT5 ana penceresini bul (class ile)
      2. Ayni PID'e ait &Giris... dialog'unu bul
      3. "Tek kullanimlik sifre:" label'indan sonraki Edit'i bul
      4. WM_SETTEXT ile OTP yaz
      5. Tamam butonuna WM_COMMAND gonder
    """
    # 0. Admin kontrolu — UIPI guard
    # MT5, -Verb RunAs ile admin olarak baslatiliyor.
    # Bu script de admin olmali, aksi halde SendMessageW/PostMessage
    # "Erisim engellendi (5)" hatasi verir.
    import ctypes as _ctypes
    if not _ctypes.windll.shell32.IsUserAnAdmin():
        return {
            "success": False,
            "message": "UIPI: Bu script admin olarak calistirilmalidir. "
                       "MT5 admin olarak calisiyor, Python da admin olmali. "
                       "USTAT'i masaustu ikonundan baslatin (admin elevation).",
            "code": 5,
        }

    # 1. MT5 penceresini bul
    mt5_hwnd = find_mt5_hwnd()
    if mt5_hwnd is None:
        return {"success": False, "message": "MT5 penceresi bulunamadi. MT5 acik mi?", "code": 1}

    mt5_pid = get_mt5_pid(mt5_hwnd)

    # 2. Giris dialog'unu bul (5sn bekle, dialog gec acilabilir)
    dialog_hwnd = None
    for _ in range(10):
        dialog_hwnd = find_login_dialog(mt5_pid)
        if dialog_hwnd is not None:
            break
        time.sleep(0.5)

    if dialog_hwnd is None:
        return {
            "success": False,
            "message": "MT5 Giris dialog'u bulunamadi. MT5 login ekrani acik mi?",
            "code": 2,
        }

    dialog_title = win32gui.GetWindowText(dialog_hwnd)

    # 3. OTP Edit'i bul
    otp_edit = find_otp_edit(dialog_hwnd)
    if otp_edit is None:
        return {
            "success": False,
            "message": "OTP giris alani bulunamadi. Dialog: " + dialog_title,
            "code": 2,
        }

    # 4. Tamam butonunu bul
    ok_btn = find_ok_button(dialog_hwnd)
    if ok_btn is None:
        return {
            "success": False,
            "message": "Tamam butonu bulunamadi. Dialog: " + dialog_title,
            "code": 2,
        }

    # 5. OTP yaz + Tamam'a tikla
    try:
        import ctypes

        # Dialog'u one getir
        try:
            win32gui.SetForegroundWindow(dialog_hwnd)
        except Exception:
            pass
        time.sleep(0.2)

        # OTP Edit'e yaz
        # NOT: win32gui.SendMessage(WM_SETTEXT) Python 3.14'te cross-process
        #   string marshaling sorunu var. ctypes.SendMessageW kullan.
        #   c_wchar_p ile string acikca Unicode pointer'a donusturulur.
        ctypes.windll.user32.SendMessageW(
            otp_edit, win32con.WM_SETTEXT, 0, ctypes.c_wchar_p(otp_code)
        )
        time.sleep(0.2)

        # Yazilan degeri dogrula
        buf_size = 32
        buf = ctypes.create_unicode_buffer(buf_size)
        ctypes.windll.user32.SendMessageW(otp_edit, win32con.WM_GETTEXT, buf_size, buf)
        written = buf.value

        # WM_SETTEXT basarisiz olduysa WM_CHAR fallback
        if written != otp_code:
            # Alani temizle
            ctypes.windll.user32.SendMessageW(
                otp_edit, win32con.WM_SETTEXT, 0, ctypes.c_wchar_p("")
            )
            time.sleep(0.1)
            # Her karakteri tek tek gonder (klavye simülasyonu)
            for ch in otp_code:
                win32gui.PostMessage(otp_edit, win32con.WM_CHAR, ord(ch), 0)
                time.sleep(0.03)
            time.sleep(0.2)
            # Tekrar dogrula
            ctypes.windll.user32.SendMessageW(otp_edit, win32con.WM_GETTEXT, buf_size, buf)
            written = buf.value

        if written != otp_code:
            return {
                "success": False,
                "message": "OTP yazma dogrulanamadi. Yazilan: '{}', beklenen: '{}'".format(written, otp_code),
                "code": 3,
            }

        # Tamam butonuna tikla
        # NOT: BM_CLICK cross-process'te guvenilir degil.
        #   BM_CLICK dahili olarak SetFocus + SetCapture yapar,
        #   bunlar cross-process'te basarisiz olur (ozellikle
        #   USTAT penceresi alwaysOnTop ise MT5 foreground olamaz).
        #
        # COZUM: WM_COMMAND gonder. Bu, Windows'un buton tiklandiginda
        #   dialog'a gonderdigiyle ayni mesajdir.
        #   wParam = MAKEWPARAM(ctrl_id, BN_CLICKED) = ctrl_id (BN_CLICKED=0)
        #   lParam = button handle
        ctrl_id = ctypes.windll.user32.GetDlgCtrlID(ok_btn)
        if ctrl_id:
            win32gui.PostMessage(
                dialog_hwnd, win32con.WM_COMMAND, ctrl_id, ok_btn
            )
        else:
            # Fallback: BM_CLICK (eski yontem)
            win32gui.PostMessage(ok_btn, win32con.BM_CLICK, 0, 0)
        time.sleep(0.5)

        return {
            "success": True,
            "message": "OTP gonderildi. Dialog: " + dialog_title,
        }

    except Exception as e:
        return {"success": False, "message": "OTP gonderme hatasi: " + str(e), "code": 3}


# ── Durum kontrol ─────────────────────────────────────────────────

def check_mt5_status():
    """MT5 pencere ve dialog durumunu kontrol et."""
    mt5_hwnd = find_mt5_hwnd()
    if mt5_hwnd is None:
        return {"mt5_found": False, "otp_dialog": False, "message": "MT5 penceresi bulunamadi"}

    mt5_title = win32gui.GetWindowText(mt5_hwnd)
    mt5_class = win32gui.GetClassName(mt5_hwnd)
    mt5_pid = get_mt5_pid(mt5_hwnd)

    result = {
        "mt5_found": True,
        "mt5_title": mt5_title,
        "mt5_class": mt5_class,
        "mt5_pid": mt5_pid,
        "otp_dialog": False,
    }

    dialog_hwnd = find_login_dialog(mt5_pid)
    if dialog_hwnd is None:
        result["message"] = "Giris dialog'u bulunamadi (MT5 zaten bagli olabilir)"
        return result

    dialog_title = win32gui.GetWindowText(dialog_hwnd)
    otp_edit = find_otp_edit(dialog_hwnd)
    ok_btn = find_ok_button(dialog_hwnd)

    result["otp_dialog"] = True
    result["dialog_title"] = dialog_title
    result["dialog_hwnd"] = dialog_hwnd
    result["otp_edit_found"] = otp_edit is not None
    result["ok_button_found"] = ok_btn is not None

    if otp_edit and ok_btn:
        result["message"] = "Hazir: OTP alani ve Tamam butonu bulundu"
    elif otp_edit:
        result["message"] = "OTP alani bulundu ama Tamam butonu yok"
    else:
        result["message"] = "Giris dialog'u acik ama OTP alani bulunamadi"

    return result


# ── CLI ───────────────────────────────────────────────────────────

def output_result(result, output_file=None, exit_code=0):
    """Sonucu stdout veya dosyaya yaz.

    NEDEN --output:
      PowerShell Start-Process -Verb RunAs ile calistirilan process'in
      stdout'u parent process tarafindan capture edilemez (elevated session).
      Sonuc temp dosyaya yazilir, Electron dosyadan okur.
    """
    text = json.dumps(result)
    if output_file:
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception as e:
            # Dosya yazma basarisiz — stdout'a yaz (fallback)
            print(json.dumps({"success": False, "message": f"Output dosya hatasi: {e}"}))
            sys.exit(4)
    else:
        print(text)
    sys.exit(exit_code)


def main():
    parser = argparse.ArgumentParser(description="MT5 OTP Otomasyon")
    parser.add_argument("--otp", type=str, help="Gonderilecek OTP kodu")
    parser.add_argument("--check", action="store_true", help="MT5 durumunu kontrol et")
    parser.add_argument("--output", type=str, help="Sonucu JSON dosyasina yaz (stdout yerine)")
    args = parser.parse_args()

    try:
        if args.check:
            result = check_mt5_status()
            output_result(result, args.output, 0)

        if args.otp:
            result = send_otp(args.otp)
            output_result(result, args.output, 0 if result["success"] else result.get("code", 4))

        parser.print_help()
        sys.exit(4)

    except Exception as e:
        output_result({"success": False, "message": str(e), "code": 4}, args.output, 4)


if __name__ == "__main__":
    main()
