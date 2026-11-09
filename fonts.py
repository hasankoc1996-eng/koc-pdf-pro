"""PDF'teki font adını (ör. 'TimesNewRomanPS-BoldMT') sistemdeki bir TTF dosyasıyla eşleştirir."""
import glob
import json
import os
import re
import sys
import threading
from pathlib import Path

import pymupdf

if sys.platform == "win32":
    WINFONTS = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    FONT_GLOBS = [str(WINFONTS / "*.tt[fc]"),
                  str(Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Microsoft/Windows/Fonts/*.tt[fc]")]
    FALLBACK = {
        (False, False, False): WINFONTS / "arial.ttf",
        (False, True, False): WINFONTS / "arialbd.ttf",
        (False, False, True): WINFONTS / "ariali.ttf",
        (False, True, True): WINFONTS / "arialbi.ttf",
        (True, False, False): WINFONTS / "times.ttf",
        (True, True, False): WINFONTS / "timesbd.ttf",
        (True, False, True): WINFONTS / "timesi.ttf",
        (True, True, True): WINFONTS / "timesbi.ttf",
    }

MAC_FONT_GLOBS = [
    "/System/Library/Fonts/Supplemental/*.tt[fc]",
    "/System/Library/Fonts/*.tt[fc]",
    "/Library/Fonts/*.tt[fc]",
    str(Path.home() / "Library/Fonts/*.tt[fc]"),
    "/Applications/Microsoft Word.app/Contents/Resources/DFonts/*.tt[fc]",
]
SUPPLEMENTAL = Path("/System/Library/Fonts/Supplemental")
MAC_FALLBACK = {
    (False, False, False): SUPPLEMENTAL / "Arial.ttf",
    (False, True, False): SUPPLEMENTAL / "Arial Bold.ttf",
    (False, False, True): SUPPLEMENTAL / "Arial Italic.ttf",
    (False, True, True): SUPPLEMENTAL / "Arial Bold Italic.ttf",
    (True, False, False): SUPPLEMENTAL / "Times New Roman.ttf",
    (True, True, False): SUPPLEMENTAL / "Times New Roman Bold.ttf",
    (True, False, True): SUPPLEMENTAL / "Times New Roman Italic.ttf",
    (True, True, True): SUPPLEMENTAL / "Times New Roman Bold Italic.ttf",
}

if sys.platform != "win32":
    FONT_GLOBS, FALLBACK = MAC_FONT_GLOBS, MAC_FALLBACK

_index = None
_lock = threading.Lock()
_font_cache = {}


def normalize(name: str) -> str:
    name = name.split("+", 1)[-1].lower()  # alt küme önekini at: ABCDEF+Calibri
    name = re.sub(r"[^a-z0-9]", "", name)
    for token in ("regular", "psmt", "ps", "mt"):
        name = name.replace(token, "")
    return name


def _build(cache_file: Path):
    index = {}
    for pattern in FONT_GLOBS:
        for f in glob.glob(pattern):
            try:
                key = normalize(pymupdf.Font(fontfile=f).name)
            except Exception:
                continue
            index.setdefault(key, f)
    try:
        cache_file.write_text(json.dumps(index))
    except OSError:
        pass
    return index


def load_index(cache_dir: Path):
    global _index
    with _lock:
        if _index is None:
            cache_file = cache_dir / "font_index.json"
            if cache_file.exists():
                try:
                    _index = json.loads(cache_file.read_text())
                except ValueError:
                    _index = None
            if _index is None:
                _index = _build(cache_file)
    return _index


def font_obj(path):
    if path not in _font_cache:
        _font_cache[path] = pymupdf.Font(fontfile=path)
    return _font_cache[path]


def resolve(pdf_font_name, text, bold=False, italic=False, serif=False, cache_dir=Path(".")):
    """Metindeki tüm karakterleri içeren en uygun font dosyasını döndürür."""
    index = load_index(cache_dir)
    candidates = []
    key = normalize(pdf_font_name or "")
    style = ("bold" if bold else "") + ("italic" if italic else "")
    for k in (key + style, key + style.replace("italic", "oblique")) if style else ():   # Arial + kalın → Arial Bold
        if k in index:
            candidates.append(index[k])
    if key in index:
        candidates.append(index[key])
    lowered = (pdf_font_name or "").lower()
    serif = serif or any(s in lowered for s in ("times", "serif", "georgia", "cambria", "garamond", "book"))
    bold = bold or "bold" in lowered or "black" in lowered
    italic = italic or "italic" in lowered or "oblique" in lowered
    candidates.append(str(FALLBACK[(serif, bold, italic)]))
    candidates.append(str(FALLBACK[(False, False, False)]))
    for path in candidates:
        try:
            font = font_obj(path)
        except Exception:
            continue
        if all(font.has_glyph(ord(ch)) or ch.isspace() for ch in text):
            return path
    return candidates[-1]


def face_file(family, bold=False, italic=False, cache_dir=Path(".")):
    """Bir yazı tipi ailesinin istenen kalın/italik dosyası; yoksa en yakın sistem fontu."""
    index = load_index(cache_dir)
    base = normalize(family or "")
    style = ("bold" if bold else "") + ("italic" if italic else "")
    for key in (base + style, base + style.replace("italic", "oblique"), base if not style else None):
        if key and key in index:
            return index[key]
    lowered = (family or "").lower()
    serif = any(s in lowered for s in ("times", "serif", "georgia", "cambria", "garamond", "book"))
    path = FALLBACK.get((serif, bold, italic))
    return str(path) if path and Path(path).exists() else None


def story_faces(families, cache_dir=Path(".")):
    """HTML'den PDF çizerken (pymupdf.Story) kullanılacak sistem yazı tipleri: Türkçe harfler için gömülür.
    Dönen: (arşiv, @font-face CSS). families: CSS'te geçen aile adları (ör. "Arial", "Times New Roman")."""
    archive = pymupdf.Archive()
    faces = []
    for i, family in enumerate(sorted(families)):
        for bold in (False, True):
            for italic in (False, True):
                path = face_file(family, bold, italic, cache_dir)
                if not path:
                    continue
                name = f"f{i}{int(bold)}{int(italic)}{Path(path).suffix}"
                archive.add((Path(path).read_bytes(), name))
                faces.append(f"@font-face {{font-family:'{family}'; src:url({name});"
                             f" font-weight:{'bold' if bold else 'normal'}; font-style:{'italic' if italic else 'normal'};}}")
    return archive, "\n".join(faces)
