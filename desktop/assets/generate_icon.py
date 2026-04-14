"""
USTAT v5.0 - Profesyonel ikon olusturucu.
Pillow ile 256x256 ikon cizer, PNG + ICO olarak kaydeder.

Tasarim:
  - Koyu gradyan arka plan (yuvarlak koseler)
  - Altin/amber "U" harfi (umlaut ile)
  - Yukselen grafik cizgisi (yesil)
  - Mumlar (candlestick)
  - Ince cerceve
"""

from PIL import Image, ImageDraw, ImageFont
import os

SIZE = 256
ICON_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]

# Renkler
BG_DARK = (13, 17, 23)        # #0d1117
BG_LIGHT = (22, 27, 34)       # #161b22
BORDER = (48, 54, 61)         # #30363d
GOLD = (255, 183, 50)         # #FFB732 - altin
GOLD_DARK = (218, 145, 20)    # #DA9114
GREEN = (63, 185, 80)         # #3fb950
GREEN_DARK = (35, 134, 54)    # #238636
RED = (248, 81, 73)           # #f85149
WHITE = (230, 237, 243)       # #e6edf3


def rounded_rect(draw, xy, radius, fill, outline=None, width=1):
    """Yuvarlak koseli dikdortgen ciz."""
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def draw_candlestick(draw, x, y_open, y_close, y_high, y_low, width=8):
    """Tek bir mum ciz."""
    is_bull = y_close < y_open  # yukariya kapandi (koordinat sistemi: ust = kucuk)
    color = GREEN if is_bull else RED
    body_top = min(y_open, y_close)
    body_bot = max(y_open, y_close)

    # Fitil (wick)
    cx = x + width // 2
    draw.line([(cx, y_high), (cx, y_low)], fill=color, width=2)

    # Govde (body)
    draw.rectangle([(x, body_top), (x + width, body_bot)], fill=color)


def create_icon():
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # ── Arka plan ─────────────────────────────────────────────
    # Gradyan efekti icin katmanlar
    for y in range(SIZE):
        ratio = y / SIZE
        r = int(BG_DARK[0] + (BG_LIGHT[0] - BG_DARK[0]) * ratio)
        g = int(BG_DARK[1] + (BG_LIGHT[1] - BG_DARK[1]) * ratio)
        b = int(BG_DARK[2] + (BG_LIGHT[2] - BG_DARK[2]) * ratio)
        draw.line([(0, y), (SIZE - 1, y)], fill=(r, g, b, 255))

    # Yuvarlak kose maskesi
    mask = Image.new("L", (SIZE, SIZE), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle([(0, 0), (SIZE - 1, SIZE - 1)], radius=44, fill=255)
    img.putalpha(mask)

    # Yeniden ciz (maske uzerine)
    draw = ImageDraw.Draw(img)

    # Gradyani tekrar ciz (maske uygulandiktan sonra)
    for y in range(SIZE):
        ratio = y / SIZE
        r = int(BG_DARK[0] + (BG_LIGHT[0] - BG_DARK[0]) * ratio)
        g = int(BG_DARK[1] + (BG_LIGHT[1] - BG_DARK[1]) * ratio)
        b = int(BG_DARK[2] + (BG_LIGHT[2] - BG_DARK[2]) * ratio)
        draw.line([(0, y), (SIZE - 1, y)], fill=(r, g, b))

    # Maske tekrar
    img.putalpha(mask)
    draw = ImageDraw.Draw(img)

    # Cerceve
    frame_mask = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    frame_draw = ImageDraw.Draw(frame_mask)
    frame_draw.rounded_rectangle(
        [(2, 2), (SIZE - 3, SIZE - 3)],
        radius=42, fill=None,
        outline=(*BORDER, 180), width=2
    )
    img = Image.alpha_composite(img, frame_mask)
    draw = ImageDraw.Draw(img)

    # ── Mumlar (arka plan, soluk) ─────────────────────────────
    candles = [
        # (x, open, close, high, low)
        (30,  175, 160, 155, 180),   # yesil
        (48,  160, 170, 155, 175),   # kirmizi
        (66,  170, 145, 140, 175),   # yesil
        (84,  145, 155, 138, 160),   # kirmizi
        (102, 155, 130, 125, 160),   # yesil
    ]

    # Soluk mumlar (opacity efekti icin renkleri azalt)
    for cx, o, c, h, l in candles:
        is_bull = c < o
        base_color = GREEN_DARK if is_bull else (150, 50, 45)
        body_top = min(o, c)
        body_bot = max(o, c)
        mid = cx + 4
        # Fitil
        draw.line([(mid, h), (mid, l)], fill=(*base_color, 100), width=1)
        # Govde
        body_overlay = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        body_draw = ImageDraw.Draw(body_overlay)
        body_draw.rectangle([(cx, body_top), (cx + 8, body_bot)],
                          fill=(*base_color, 80))
        img = Image.alpha_composite(img, body_overlay)
        draw = ImageDraw.Draw(img)

    # ── Yukselen grafik cizgisi ───────────────────────────────
    chart_points = [
        (25, 185), (55, 168), (85, 172), (115, 148),
        (145, 155), (175, 125), (200, 108), (230, 78)
    ]

    # Cizgi altini doldu (soluk yesil alan)
    fill_points = chart_points + [(230, 200), (25, 200)]
    fill_overlay = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    fill_draw = ImageDraw.Draw(fill_overlay)
    fill_draw.polygon(fill_points, fill=(63, 185, 80, 25))
    img = Image.alpha_composite(img, fill_overlay)
    draw = ImageDraw.Draw(img)

    # Cizgi kendisi
    for i in range(len(chart_points) - 1):
        draw.line([chart_points[i], chart_points[i + 1]],
                 fill=(*GREEN, 140), width=2)

    # Son nokta (parlak)
    draw.ellipse([(226, 74), (234, 82)], fill=GREEN)

    # ── "U" harfi (buyuk, altin) ──────────────────────────────
    # Font bul
    font = None
    font_paths = [
        "C:/Windows/Fonts/segoeuib.ttf",    # Segoe UI Bold
        "C:/Windows/Fonts/segoeui.ttf",      # Segoe UI
        "C:/Windows/Fonts/arialbd.ttf",      # Arial Bold
        "C:/Windows/Fonts/arial.ttf",        # Arial
    ]

    for fp in font_paths:
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, 140)
                break
            except Exception:
                continue

    if font is None:
        font = ImageFont.load_default()

    # "U" ciz - golge + ana metin
    text = "U"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = (SIZE - tw) // 2
    ty = (SIZE - th) // 2 - 8

    # Golge
    shadow_overlay = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_overlay)
    shadow_draw.text((tx + 3, ty + 3), text, font=font, fill=(0, 0, 0, 120))
    img = Image.alpha_composite(img, shadow_overlay)
    draw = ImageDraw.Draw(img)

    # Ana "U" (altin gradyan efekti)
    # Ust kisim parlak, alt kisim koyu
    u_layer = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    u_draw = ImageDraw.Draw(u_layer)
    u_draw.text((tx, ty), text, font=font, fill=GOLD)

    # Dogrudan altin renk
    draw.text((tx, ty), text, font=font, fill=GOLD)

    # ── Umlaut noktalari ──────────────────────────────────────
    dot_y = ty + 6
    dot_r = 8
    dot_gap = 28

    cx = SIZE // 2
    # Sol nokta
    draw.ellipse([(cx - dot_gap - dot_r, dot_y - dot_r),
                  (cx - dot_gap + dot_r, dot_y + dot_r)], fill=GOLD)
    # Sag nokta
    draw.ellipse([(cx + dot_gap - dot_r, dot_y - dot_r),
                  (cx + dot_gap + dot_r, dot_y + dot_r)], fill=GOLD)

    # ── Alt yazi: "STAT" (kucuk, beyaz) ───────────────────────
    small_font = None
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                small_font = ImageFont.truetype(fp, 28)
                break
            except Exception:
                continue

    if small_font:
        stat_text = "STAT"
        sbbox = draw.textbbox((0, 0), stat_text, font=small_font)
        stw = sbbox[2] - sbbox[0]
        stx = (SIZE - stw) // 2 + 36
        sty = ty + th - 18

        draw.text((stx, sty), stat_text, font=small_font, fill=(*WHITE, 200))

    # ── Alt cizgi (altin accent) ──────────────────────────────
    line_y = SIZE - 38
    draw.line([(50, line_y), (SIZE - 50, line_y)], fill=(*GOLD, 150), width=2)

    # ── Kucuk "v5" badge ──────────────────────────────────────
    badge_font = None
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                badge_font = ImageFont.truetype(fp, 16)
                break
            except Exception:
                continue

    if badge_font:
        badge_overlay = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
        badge_draw = ImageDraw.Draw(badge_overlay)
        badge_draw.rounded_rectangle(
            [(190, SIZE - 52), (240, SIZE - 30)],
            radius=8, fill=(*GOLD_DARK, 200)
        )
        badge_draw.text((198, SIZE - 51), "v5", font=badge_font, fill=(255, 255, 255, 230))
        img = Image.alpha_composite(img, badge_overlay)

    return img


def main():
    print("USTAT v5.0 ikon olusturuluyor...")

    icon_img = create_icon()
    out_dir = os.path.dirname(os.path.abspath(__file__))

    # PNG kaydet (256x256)
    png_path = os.path.join(out_dir, "icon.png")
    icon_img.save(png_path, "PNG")
    print(f"  PNG: {png_path}")

    # ICO kaydet (coklu boyut)
    ico_path = os.path.join(out_dir, "icon.ico")
    icon_sizes = []
    for s in [16, 32, 48, 64, 128, 256]:
        resized = icon_img.resize((s, s), Image.LANCZOS)
        icon_sizes.append(resized)

    icon_sizes[0].save(
        ico_path, format="ICO",
        sizes=[(s, s) for s in [16, 32, 48, 64, 128, 256]],
        append_images=icon_sizes[1:]
    )
    print(f"  ICO: {ico_path}")

    print("Tamamlandi!")


if __name__ == "__main__":
    main()
