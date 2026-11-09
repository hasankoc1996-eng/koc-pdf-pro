"""Koç PDF Pro simgesini üretir.

Kaynak: native/logo_source.png (Figma yapay zekâ ile üretilmiş, kırmızı zeminli koç başı).
Çıktılar:
  native/AppIcon.iconset/   macOS simge boyutları (build.sh bunu AppIcon.icns yapar)
  static/logo.png           arayüzdeki logo ve sekme simgesi

Çalıştırma:  .venv/bin/python native/make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).parent
SOURCE = HERE / "logo_source.png"
FONT = "/System/Library/Fonts/Supplemental/Arial Black.ttf"
CANVAS = 1024
TILE = 824                 # macOS simge ızgarası: yuvarlatılmış kare tuvalin ~%80'i
RADIUS = 0.224             # köşe yarıçapı / kenar


def rounded_mask(size, scale=4):
    big = Image.new("L", (size * scale, size * scale), 0)
    ImageDraw.Draw(big).rounded_rectangle((0, 0, size * scale - 1, size * scale - 1),
                                          radius=int(size * scale * RADIUS), fill=255)
    return big.resize((size, size), Image.LANCZOS)


def badge(tile):
    """Sağ alt köşeye "PDF PRO" etiketi: koyu hap içinde beyaz yazı."""
    s = tile.size[0]
    font = ImageFont.truetype(FONT, int(s * 0.072))
    text = "PDF PRO"
    box = font.getbbox(text)
    tw, th = box[2] - box[0], box[3] - box[1]
    pad_x, pad_y = int(s * 0.034), int(s * 0.022)
    w, h = tw + 2 * pad_x, th + 2 * pad_y
    x1, y1 = int(s * 0.925), int(s * 0.915)
    x0, y0 = x1 - w, y1 - h
    shadow = Image.new("RGBA", tile.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((x0, y0 + s // 140, x1, y1 + s // 140), radius=h // 2, fill=(0, 0, 0, 110))
    layer = shadow.filter(ImageFilter.GaussianBlur(max(1, s // 100)))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle((x0, y0, x1, y1), radius=h // 2, fill=(17, 17, 20, 255), outline=(255, 255, 255, 255),
                        width=max(2, s // 220))
    d.text((x0 + pad_x - box[0], y0 + pad_y - box[1]), text, font=font, fill=(255, 255, 255, 255))
    return Image.alpha_composite(tile, layer)


def make_tile(size=TILE):
    src = Image.open(SOURCE).convert("RGBA")
    # Kaynağın köşelerindeki beyaz alanı kırp: kendi yuvarlatılmış karemizle maskeleyeceğiz
    inset = int(src.size[0] * 0.012)
    src = src.crop((inset, inset, src.size[0] - inset, src.size[1] - inset)).resize((size, size), Image.LANCZOS)
    tile = badge(src)
    tile.putalpha(ImageChops.multiply(tile.getchannel("A"), rounded_mask(size)))
    return tile


def main():
    tile = make_tile()
    icon = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    # macOS simgeleri gibi hafif alt gölge
    off = (CANVAS - TILE) // 2
    shadow = Image.new("RGBA", (CANVAS, CANVAS), (0, 0, 0, 0))
    shadow.paste((0, 0, 0, 90), (off, off + 12), rounded_mask(TILE))
    icon = Image.alpha_composite(icon, shadow.filter(ImageFilter.GaussianBlur(14)))
    icon.alpha_composite(tile, (off, off))

    iconset = HERE / "AppIcon.iconset"
    iconset.mkdir(exist_ok=True)
    for s in (16, 32, 128, 256, 512):
        icon.resize((s, s), Image.LANCZOS).save(iconset / f"icon_{s}x{s}.png")
        icon.resize((s * 2, s * 2), Image.LANCZOS).save(iconset / f"icon_{s}x{s}@2x.png")
    make_tile(256).save(HERE.parent / "static" / "logo.png")
    print("native/AppIcon.iconset, static/logo.png")


if __name__ == "__main__":
    main()
