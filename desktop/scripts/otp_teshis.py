"""
OTP Teşhis Script'i — Gerçek veri topla, tahmin yapma.

MT5 login dialog'unun iç yapısını detaylı olarak raporlar:
  - Dialog'un tüm child kontrollerini listeler
  - find_otp_edit()'in seçtiği HWND'yi gösterir
  - O HWND'ye WM_SETTEXT/WM_GETTEXT testi yapar
  - Kontrol durumunu (enabled, visible, style) raporlar

Kullanım:
    python otp_teshis.py
"""

import ctypes
import ctypes.wintypes
import sys
import json

import win32gui
import win32con
import win32process

# ── SendMessageW hazırla ──────────────────────────────────────────
SendMessageW = ctypes.windll.user32.SendMessageW
SendMessageW.argtypes = [
    ctypes.wintypes.HWND,
    ctypes.wintypes.UINT,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
]
SendMessageW.restype = ctypes.wintypes.LPARAM

# c_wchar_p'yi LPARAM'a cast etmek için
def send_set_text(hwnd, text):
    """WM_SETTEXT gönder — ctypes ile."""
    lp = ctypes.c_wchar_p(text)
    return SendMessageW(hwnd, win32con.WM_SETTEXT, 0, ctypes.cast(lp, ctypes.wintypes.LPARAM))

def send_get_text(hwnd):
    """WM_GETTEXT gönder — ctypes ile."""
    buf = ctypes.create_unicode_buffer(256)
    SendMessageW(hwnd, win32con.WM_GETTEXT, 256, ctypes.cast(buf, ctypes.wintypes.LPARAM))
    return buf.value


def get_window_style(hwnd):
    """Pencere stilini al."""
    try:
        return win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
    except:
        return 0


def style_flags(style):
    """Önemli stil bayraklarını metin olarak döndür."""
    flags = []
    if style & win32con.WS_VISIBLE:
        flags.append("VISIBLE")
    else:
        flags.append("HIDDEN")
    if style & win32con.WS_DISABLED:
        flags.append("DISABLED")
    else:
        flags.append("ENABLED")
    if style & win32con.WS_CHILD:
        flags.append("CHILD")
    # Edit-specific
    if style & 0x0800:  # ES_READONLY
        flags.append("READONLY")
    if style & 0x0020:  # ES_PASSWORD
        flags.append("PASSWORD")
    return " | ".join(flags)


def print_sep(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def main():
    print_sep("OTP TEŞHİS — Gerçek Veri Toplama")

    # 1. MT5 ana penceresini bul
    print("\n[1] MT5 ana penceresi aranıyor...")
    mt5_hwnd = None

    def find_mt5(hwnd, _):
        nonlocal mt5_hwnd
        try:
            cls = win32gui.GetClassName(hwnd)
            if "MetaQuotes::MetaTrader" in cls:
                mt5_hwnd = hwnd
                return False
        except:
            pass
        return True

    try:
        win32gui.EnumWindows(find_mt5, None)
    except:
        pass

    if mt5_hwnd is None:
        print("  ❌ MT5 penceresi BULUNAMADI. MT5 açık mı?")
        return

    mt5_class = win32gui.GetClassName(mt5_hwnd)
    mt5_title = win32gui.GetWindowText(mt5_hwnd)
    _, mt5_pid = win32process.GetWindowThreadProcessId(mt5_hwnd)
    print(f"  ✅ MT5 bulundu")
    print(f"     HWND : {mt5_hwnd} (0x{mt5_hwnd:08X})")
    print(f"     Class: {mt5_class}")
    print(f"     Title: {mt5_title}")
    print(f"     PID  : {mt5_pid}")

    # 2. Login dialog'unu bul
    print("\n[2] Login dialog'u aranıyor (PID={})...".format(mt5_pid))
    dialogs = []

    def find_dialogs(hwnd, results):
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid != mt5_pid:
                return True
            cls = win32gui.GetClassName(hwnd)
            if cls != "#32770":
                return True
            visible = win32gui.IsWindowVisible(hwnd)
            title = win32gui.GetWindowText(hwnd)
            style = get_window_style(hwnd)
            results.append({
                "hwnd": hwnd,
                "class": cls,
                "title": title,
                "visible": visible,
                "style": style,
            })
        except:
            pass
        return True

    try:
        win32gui.EnumWindows(find_dialogs, dialogs)
    except:
        pass

    print(f"  Bulunan #32770 dialog sayısı: {len(dialogs)}")
    for i, d in enumerate(dialogs):
        print(f"  [{i}] HWND=0x{d['hwnd']:08X} title='{d['title']}' visible={d['visible']} style={style_flags(d['style'])}")

    # "giris" veya "login" içereni seç
    dialog_hwnd = None
    for d in dialogs:
        t = d["title"].lower().replace("&", "")
        if ("giris" in t or "giri" in t or "login" in t) and d["visible"]:
            dialog_hwnd = d["hwnd"]
            break

    if dialog_hwnd is None:
        for d in dialogs:
            if d["visible"] and d["title"].strip():
                dialog_hwnd = d["hwnd"]
                break

    if dialog_hwnd is None and dialogs:
        dialog_hwnd = dialogs[0]["hwnd"]

    if dialog_hwnd is None:
        print("  ❌ Login dialog'u BULUNAMADI")
        return

    dialog_title = win32gui.GetWindowText(dialog_hwnd)
    print(f"\n  ✅ Seçilen dialog: HWND=0x{dialog_hwnd:08X} title='{dialog_title}'")

    # 3. Dialog'un TÜM direct child'larını listele
    print_sep("Dialog Child Kontrollerı (sırayla)")

    children = []
    child = win32gui.GetWindow(dialog_hwnd, win32con.GW_CHILD)
    idx = 0
    while child:
        try:
            cls = win32gui.GetClassName(child)
            title = win32gui.GetWindowText(child)
            visible = win32gui.IsWindowVisible(child)
            enabled = win32gui.IsWindowEnabled(child)
            style = get_window_style(child)
            ctrl_id = ctypes.windll.user32.GetDlgCtrlID(child)

            children.append({
                "idx": idx,
                "hwnd": child,
                "class": cls,
                "title": title,
                "visible": visible,
                "enabled": enabled,
                "style": style,
                "ctrl_id": ctrl_id,
            })

            mark = ""
            if cls == "Edit":
                mark = " ◄◄◄ EDIT"
            elif cls == "Static" and "tek kullan" in title.lower():
                mark = " ◄◄◄ OTP LABEL"
            elif cls == "Button" and title.lower() in ("tamam", "ok"):
                mark = " ◄◄◄ OK BUTTON"

            print(f"  [{idx:2d}] HWND=0x{child:08X} class={cls:12s} id={ctrl_id:5d} "
                  f"vis={int(visible)} ena={int(enabled)} "
                  f"title='{title[:40]}'{mark}")
        except Exception as e:
            print(f"  [{idx:2d}] HWND=0x{child:08X} HATA: {e}")
        idx += 1
        try:
            child = win32gui.GetWindow(child, win32con.GW_HWNDNEXT)
        except:
            break

    print(f"\n  Toplam child sayısı: {idx}")

    # 4. EnumChildWindows ile de tara (recursive)
    print_sep("EnumChildWindows (recursive) — tüm Edit kontrolleri")

    all_edits = []

    def find_all_edits(hwnd, results):
        try:
            cls = win32gui.GetClassName(hwnd)
            if cls == "Edit":
                title = win32gui.GetWindowText(hwnd)
                visible = win32gui.IsWindowVisible(hwnd)
                enabled = win32gui.IsWindowEnabled(hwnd)
                style = get_window_style(hwnd)
                ctrl_id = ctypes.windll.user32.GetDlgCtrlID(hwnd)
                parent = win32gui.GetParent(hwnd)
                results.append({
                    "hwnd": hwnd,
                    "title": title,
                    "visible": visible,
                    "enabled": enabled,
                    "style": style,
                    "ctrl_id": ctrl_id,
                    "parent": parent,
                })
        except:
            pass
        return True

    try:
        win32gui.EnumChildWindows(dialog_hwnd, find_all_edits, all_edits)
    except:
        pass

    print(f"  Bulunan Edit sayısı: {len(all_edits)}")
    for i, e in enumerate(all_edits):
        flags = style_flags(e["style"])
        direct = "DIRECT" if e["parent"] == dialog_hwnd else f"parent=0x{e['parent']:08X}"
        print(f"  [{i}] HWND=0x{e['hwnd']:08X} id={e['ctrl_id']:5d} "
              f"vis={int(e['visible'])} ena={int(e['enabled'])} "
              f"{direct} flags=[{flags}] "
              f"text='{e['title'][:30]}'")

    # 5. find_otp_edit mantığını simüle et
    print_sep("find_otp_edit() Simülasyonu")

    found_label = False
    otp_edit_hwnd = None
    for c in children:
        if found_label and c["class"] == "Edit":
            otp_edit_hwnd = c["hwnd"]
            print(f"  ✅ OTP Edit bulundu: [{c['idx']}] HWND=0x{c['hwnd']:08X}")
            print(f"     Class  : {c['class']}")
            print(f"     Title  : '{c['title']}'")
            print(f"     Visible: {c['visible']}")
            print(f"     Enabled: {c['enabled']}")
            print(f"     Ctrl ID: {c['ctrl_id']}")
            print(f"     Style  : 0x{c['style']:08X} [{style_flags(c['style'])}]")
            break
        if c["class"] == "Static" and "tek kullan" in c["title"].lower():
            found_label = True
            print(f"  ✅ OTP Label bulundu: [{c['idx']}] title='{c['title']}'")

    if otp_edit_hwnd is None:
        print("  ❌ find_otp_edit() Edit BULAMADI!")
        print("     'Tek kullanımlık' içeren Static label bulunamadı veya")
        print("     label'dan sonra Edit kontrolü yok.")

        # Alternatif: tüm Edit'leri dene
        if all_edits:
            print(f"\n  Alternatif: {len(all_edits)} Edit kontrolü var, hepsini test edelim...")
            for i, e in enumerate(all_edits):
                test_write(e["hwnd"], f"Edit[{i}]", "TEST")
        return

    # 6. OTP Edit'e yazma testi
    print_sep("WM_SETTEXT / WM_GETTEXT Testi")

    test_write(otp_edit_hwnd, "OTP Edit", "999999")

    # 7. Tüm Edit'lere yazma testi
    if len(all_edits) > 1:
        print_sep("TÜM Edit Kontrollerine Yazma Testi")
        for i, e in enumerate(all_edits):
            if e["hwnd"] != otp_edit_hwnd:
                test_write(e["hwnd"], f"Edit[{i}] (0x{e['hwnd']:08X})", f"T{i}")

    # 8. Tamam butonu
    print_sep("Tamam Butonu")
    ok_btn = None
    for c in children:
        if c["class"] == "Button" and c["title"].lower() in ("tamam", "ok"):
            ok_btn = c
            break

    if ok_btn:
        print(f"  ✅ Tamam butonu bulundu: HWND=0x{ok_btn['hwnd']:08X}")
        print(f"     Title  : '{ok_btn['title']}'")
        print(f"     Enabled: {ok_btn['enabled']}")
        print(f"     Ctrl ID: {ok_btn['ctrl_id']}")
    else:
        print("  ❌ Tamam butonu BULUNAMADI")

    # 9. UIPI kontrolü
    print_sep("İzin / UIPI Kontrolü")
    try:
        import ctypes.wintypes
        process = ctypes.windll.kernel32.GetCurrentProcess()

        # Token aç
        token = ctypes.wintypes.HANDLE()
        ctypes.windll.advapi32.OpenProcessToken(
            process, 0x0008, ctypes.byref(token)  # TOKEN_QUERY
        )

        # Integrity level
        # TokenIntegrityLevel = 25
        info_size = ctypes.wintypes.DWORD()
        ctypes.windll.advapi32.GetTokenInformation(
            token, 25, None, 0, ctypes.byref(info_size)
        )

        print(f"  Bu script'in PID'i: {ctypes.windll.kernel32.GetCurrentProcessId()}")
        print(f"  MT5'in PID'i      : {mt5_pid}")

        # IsProcessDPI aware vb. kontroller
        foreground = win32gui.GetForegroundWindow()
        fg_title = win32gui.GetWindowText(foreground) if foreground else "(yok)"
        print(f"  Foreground pencere : 0x{foreground:08X} '{fg_title}'")

        ctypes.windll.kernel32.CloseHandle(token)
    except Exception as e:
        print(f"  UIPI kontrol hatası: {e}")

    print_sep("TEŞHİS TAMAMLANDI")
    print("  Bu çıktıyı kopyalayıp paylaşın.")


def test_write(hwnd, label, test_value):
    """Bir Edit kontrolüne yazma/okuma testi yap."""
    print(f"\n  --- {label} (HWND=0x{hwnd:08X}) ---")

    # Önce mevcut değeri oku
    try:
        current = send_get_text(hwnd)
        print(f"  [1] Mevcut değer (WM_GETTEXT)  : '{current}'")
    except Exception as e:
        print(f"  [1] WM_GETTEXT HATA: {e}")
        return

    # WM_SETTEXT ile yaz
    try:
        ret = send_set_text(hwnd, test_value)
        print(f"  [2] WM_SETTEXT('{test_value}') dönüş: {ret}")
    except Exception as e:
        print(f"  [2] WM_SETTEXT HATA: {e}")

    # Tekrar oku
    try:
        after = send_get_text(hwnd)
        print(f"  [3] Sonraki değer (WM_GETTEXT) : '{after}'")
    except Exception as e:
        print(f"  [3] WM_GETTEXT HATA: {e}")
        return

    if after == test_value:
        print(f"  ✅ BAŞARILI — '{test_value}' yazıldı ve doğrulandı")
    else:
        print(f"  ❌ BAŞARISIZ — beklenen: '{test_value}', okunan: '{after}'")

        # WM_CHAR fallback testi
        print(f"  [4] WM_CHAR fallback deneniyor...")
        try:
            # Temizle
            send_set_text(hwnd, "")
            import time
            time.sleep(0.1)
            for ch in test_value:
                win32gui.PostMessage(hwnd, win32con.WM_CHAR, ord(ch), 0)
                time.sleep(0.03)
            time.sleep(0.2)
            after2 = send_get_text(hwnd)
            print(f"  [5] WM_CHAR sonrası (WM_GETTEXT): '{after2}'")
            if after2 == test_value:
                print(f"  ✅ WM_CHAR BAŞARILI")
            else:
                print(f"  ❌ WM_CHAR da BAŞARISIZ")
        except Exception as e:
            print(f"  [4] WM_CHAR HATA: {e}")

        # SendMessage return value kontrolü
        print(f"  [6] SendMessageW return value detaylı kontrol...")
        try:
            # GetLastError kontrolü
            ctypes.windll.kernel32.SetLastError(0)
            ret2 = send_set_text(hwnd, test_value)
            last_err = ctypes.windll.kernel32.GetLastError()
            print(f"      SendMessageW return: {ret2}, GetLastError: {last_err}")

            # IsWindow kontrolü
            is_wnd = ctypes.windll.user32.IsWindow(hwnd)
            print(f"      IsWindow({hwnd}): {is_wnd}")

            # GetWindowThreadProcessId
            target_pid = ctypes.wintypes.DWORD()
            target_tid = ctypes.windll.user32.GetWindowThreadProcessId(
                hwnd, ctypes.byref(target_pid)
            )
            print(f"      Target TID={target_tid}, PID={target_pid.value}")

        except Exception as e:
            print(f"      Detaylı kontrol hatası: {e}")


if __name__ == "__main__":
    main()
