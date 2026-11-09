"""KVKK: belgedeki kişisel verilerin (ad soyad, T.C. kimlik no, vergi kimlik no, IBAN, kart numarası, telefon,
e-posta) bulunması ve karartılması. Taranmış sayfalarda tanınan yazıda aranır."""
import re

import pymupdf

import person_names
from pdf_ortak import _disp_rect, _native
from tools import ToolError


# ---------------------------------------------------------------- KVKK: kişisel verileri bulma ve karartma
# Rastgele sayılar kişisel veri sanılmasın diye her türün kendi doğrulaması var
# (T.C. kimlik no ve vergi kimlik no algoritmaları, IBAN mod-97, kart numarası Luhn).

def _valid_tckn(text):
    d = [int(c) for c in re.sub(r"\D", "", text)]
    if len(d) != 11 or d[0] == 0:
        return False
    return (sum(d[0:9:2]) * 7 - sum(d[1:8:2])) % 10 == d[9] and sum(d[:10]) % 10 == d[10]


def _valid_vkn(text):
    """Vergi kimlik numarası (10 hane): son hane ilk dokuzundan hesaplanır. Rastgele 10 haneli sayıların
    yaklaşık onda biri de bu denetimden geçer; bu yüzden liste kullanıcıya gösterilip seçtirilir."""
    d = [int(c) for c in re.sub(r"\D", "", text)]
    if len(d) != 10 or len(set(d)) == 1:
        return False
    total = 0
    for i, n in enumerate(d[:9]):
        t = (n + 9 - i) % 10
        total += 9 if t == 9 else t * 2 ** (9 - i) % 9
    return (10 - total % 10) % 10 == d[9]


def _valid_iban(text):
    s = re.sub(r"\s", "", text).upper()
    if len(s) != 26:
        return False
    digits = "".join(str(int(c, 36)) for c in s[4:] + s[:4])
    return int(digits) % 97 == 1


def _valid_card(text):
    d = [int(c) for c in re.sub(r"\D", "", text)]
    if len(d) != 16 or len(set(d)) == 1:
        return False
    total = 0
    for i, n in enumerate(reversed(d)):
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def _valid_phone(text):
    d = re.sub(r"\D", "", text)
    if d.startswith("90") and len(d) == 12:
        d = d[2:]
    elif d.startswith("0") and len(d) == 11:
        d = d[1:]
    elif not re.search(r"[\s().-]", text):   # önek ve ayraç yoksa telefon sayma (başka bir numara olabilir)
        return False
    return len(d) == 10 and d[0] in "2345" and len(set(d)) > 2


PERSONAL_DATA = [   # (tür, etiket, desen, doğrulama) — sıra önemli: aynı yeri ilk bulan tür alır
    ("iban", "IBAN", re.compile(r"\bTR\s?\d{2}(?:\s?\d{4}){5}\s?\d{2}(?!\d)", re.I), _valid_iban),
    ("kart", "Kart numarası", re.compile(r"(?<!\d)\d{4}(?:[ -]?\d{4}){3}(?!\d)"), _valid_card),
    ("tckn", "T.C. kimlik no", re.compile(r"(?<!\d)[1-9]\d{10}(?!\d)"), _valid_tckn),
    # Harfe bitişik 10 hane (belge ya da fatura kodlarının parçası) vergi numarası sayılmaz
    ("vkn", "Vergi kimlik no", re.compile(r"(?<!\w)\d{10}(?!\w)"), _valid_vkn),
    ("telefon", "Telefon", re.compile(r"(?<![\w+(])(?:\+90[\s-]?)?\(?0?\s?[2-5]\d{2}\)?[\s.-]?\d{3}[\s.-]?\d{2}[\s.-]?\d{2}(?!\d)"),
     _valid_phone),
    ("eposta", "E-posta", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), None),
]


def _page_chars(page):
    """Sayfanın harfleri satır satır: [(harf, kutu, satır no)]."""
    chars, n = [], 0
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            n += 1
            chars.extend((ch["c"], pymupdf.Rect(ch["bbox"]), n) for span in line["spans"] for ch in span["chars"])
    return chars


def _chars_in(r, chars):
    """Kutunun içindeki harflerin sıra numaraları."""
    return [k for k, (_, b, _) in enumerate(chars) if r.x0 <= (b.x0 + b.x1) / 2 <= r.x1 and r.y0 <= (b.y0 + b.y1) / 2 <= r.y1]


def _cuts_word(r, chars, glued=False):
    """Bulunan yer bir kelimenin ortasından mı başlıyor ya da bitiyor? (Ali → Halil, kalite; Can → Canlı)
    glued: harfe bitişik rakam da kelimenin parçası sayılır (ABC1234567890 içindeki 1234567890)."""
    inside = _chars_in(r, chars)
    if not inside:
        return False

    def joined(a, b):   # aynı satırda yan yana iki harf ya da iki rakam (glued: harf ve rakam da)
        x, y = chars[a][0], chars[b][0]
        return chars[a][2] == chars[b][2] and ((x.isalnum() and y.isalnum()) if glued
                                               else (x.isalpha() and y.isalpha()) or (x.isdigit() and y.isdigit()))
    first, last = inside[0], inside[-1]
    return (first > 0 and joined(first - 1, first)) or (last + 1 < len(chars) and joined(last, last + 1))


def _redact_rect(r, words):
    """Arama kutusu yazı tipinin tam yüksekliğindedir; sık satırlarda üst/alt satıra taşar ve karartma
    oradaki harfleri de siler (harfe azıcık değen kutu onu siler). Kutu komşu satırlara ve yandaki harflere
    değmeyecek kadar daraltılır; içindeki harflerin hepsine yine değer."""
    top, bottom = r.y0, r.y1
    for x0, y0, x1, y1, *_ in words:
        if x1 <= r.x0 or x0 >= r.x1:
            continue
        c = (y0 + y1) / 2
        if c < r.y0:
            top = max(top, y1 + 0.25)
        elif c > r.y1:
            bottom = min(bottom, y0 - 0.25)
    if bottom - top < r.height * 0.25:   # satırlar üst üste binmişse ortadaki şerit
        mid = (r.y0 + r.y1) / 2
        top, bottom = mid - r.height * 0.125, mid + r.height * 0.125
    return pymupdf.Rect(r.x0 + 0.25, top, r.x1 - 0.25, bottom)


def _context(text, start, end, pad=40):
    """Listede gösterilen çevre yazı: kelime ortasından başlayıp bitmesin diye kelime sınırına uzatılır."""
    a, b = max(0, start - pad), min(len(text), end + pad)
    while a > 0 and not text[a - 1].isspace() and start - a < pad + 20:
        a -= 1
    while b < len(text) and not text[b].isspace() and b - end < pad + 20:
        b += 1
    return ("…" if a > 0 else "") + " ".join(text[a:b].split()) + ("…" if b < len(text.rstrip()) else "")


def is_scan_page(page):
    """Sayfa taranmış mı: metni yok ya da sayfanın yarısından çoğunu bir resim kaplıyor ve metni az (UYAP'tan inen
    taranmış evrakta yalnızca altta bir doğrulama yazısı olur). Böyle sayfalarda kişisel veriler resmin içindedir.
    Resmi olmayan sayfada tanınacak bir şey yoktur."""
    if not page.get_images():
        return False
    text = page.get_text("text").strip()
    if len(text) <= 20:
        return True
    if len(text) > 400:
        return False
    area = abs(page.rect)
    return any(abs(r & page.rect) >= area * 0.5 for img in page.get_images(full=True) for r in page.get_image_rects(img[0]))


class ScanText:
    """Taranmış sayfanın tanınan yazısı (ocr_word_lines biçiminde satırlar): kelimeler satır satır tek metinde
    birleşir; metnin bir parçasının sayfadaki yeri kelime kutularından bulunur (kelime içindeki harfler eşit sayılır)."""

    def __init__(self, lines):
        parts, self.spans, pos = [], [], 0   # spans: (başlangıç, bitiş, x, genişlik, y, yükseklik, satır)
        for n, line in enumerate(lines):
            for k, (x, _, word, width) in enumerate(line["words"]):
                if parts:
                    parts.append(" " if k else "\n")
                    pos += 1
                parts.append(word)
                self.spans.append((pos, pos + len(word), x, width, line["y"], line["h"], n))
                pos += len(word)
        self.text = "".join(parts)

    def boxes(self, a, b):
        """Metnin [a, b) aralığı: satır başına bir dikdörtgen (ekranda, 0–1 arası)."""
        rows = {}
        for s0, s1, x, w, y, h, n in self.spans:
            lo, hi = max(a, s0), min(b, s1)
            if lo >= hi:
                continue
            x0, x1 = x + w * (lo - s0) / (s1 - s0), x + w * (hi - s0) / (s1 - s0)
            r = rows.get(n)
            rows[n] = [min(r[0], x0), y, max(r[2], x1), y + h] if r else [x0, y, x1, y + h]
        return [pymupdf.Rect(r) for r in rows.values()]

    @staticmethod
    def pad(r):
        """Karartılacak kutu: harflerin yeri kelime içinde oranlandığı için kenardaki harf açıkta kalmasın diye yanlara
        genişletilir; satır kutusu harflerin tam yüksekliğinde olduğundan üst/alt satıra pek taşmaz."""
        px, py = r.height * 0.35, r.height * 0.05
        return pymupdf.Rect(max(0, r.x0 - px), max(0, r.y0 - py), min(1, r.x1 + px), min(1, r.y1 + py))

    def find(self, value, exact=False, pick=None):
        """Değerin geçtiği yerler (her biri satır dikdörtgenlerinin listesi). exact ve pick: bkz. find_personal_data."""
        pattern = r"\s+".join(re.escape(part) for part in value.split())
        hits = [m.span() for m in re.finditer(rf"(?<!\w){pattern}(?!\w)", self.text, 0 if exact else re.I)]
        if pick and len(hits) == pick[1]:
            hits = [h for k, h in enumerate(hits) if k in pick[0]]
        return [self.boxes(a, b) for a, b in hits]


def _same_place(a, b):
    """İki kutu aynı yeri mi gösteriyor: kesişim küçüğünün üçte birinden büyükse. Komşu satırların kutuları
    (özellikle metin tanımada) kenarlarından biraz değebilir; bu, aynı yer sayılmaz."""
    cut = a & b
    return not cut.is_empty and abs(cut) > min(abs(a), abs(b)) / 3


def find_personal_data(doc, terms=(), limit=2000, scans=None):
    """scans: {sayfa: tanınan satırlar} — taranmış sayfalarda metin yerine tanınan yazıda aranır."""
    scans = {i: ScanText(lines) for i, lines in (scans or {}).items()}
    texts = [scans[i].text if i in scans else page.get_text("text") for i, page in enumerate(doc)]
    names = [person_names.find_names(text) for text in texts]
    # Bulunan kişilerin soyadları (belgenin tamamından): başka yerde tek başına geçtiklerinde de listelenir (Sayın Şahin)
    family = set().union(*(person_names.surnames(t[a:b]) for t, spans in zip(texts, names) for a, b in spans))
    found = []
    for i, page in enumerate(doc):
        W, H, rot = page.rect.width, page.rect.height, page.rotation_matrix
        text, scan = texts[i], scans.get(i)
        words, chars = (None, None) if scan else (page.get_text("words"), _page_chars(page))
        taken = []   # bu sayfada bulunan dikdörtgenler (ekranda, 0–1): aynı yer iki türe girmesin

        def add(kind, label, value, context, exact=False, pick=None, glued=False):
            """exact: yalnızca büyük/küçük harfiyle aynı yazılanlar (Demir; "demir kapı" değil).
            pick: (alınacak sıra numaraları, metindeki geçiş sayısı) — kelimenin yalnızca bazı geçişleri karartılır.
            glued: harfe bitişik geçişler alınmaz (bkz. _cuts_word)."""
            if scan:
                spots = scan.find(value, exact, pick)
                places = len(spots)
                rects = [r for boxes in spots for r in boxes]
            else:
                hits = [r for r in page.search_for(value) if not _cuts_word(r, chars, glued)
                        and (not exact or "".join(chars[k][0] for k in _chars_in(r, chars)) == value)]
                if pick and len(hits) == pick[1]:   # bulunan yerler metindeki sırayla eşleşir
                    hits = [r for k, r in enumerate(hits) if k in pick[0]]
                rects = [(_redact_rect(r, words) * rot).normalize() for r in hits]
                rects = [pymupdf.Rect(r.x0 / W, r.y0 / H, r.x1 / W, r.y1 / H) for r in rects]
                # Satır sonunda bölünen geçiş iki dikdörtgendir: kaç yerde geçtiği metinden sayılır
                pattern = r"\s+".join(re.escape(part) for part in value.split())
                places = len(pick[0]) if pick else len(re.findall(rf"(?<!\w){pattern}(?!\w)", text, 0 if exact else re.I))
            rects = [r for r in rects if not any(_same_place(r, o) for o in taken)]
            if not rects:
                return
            taken.extend(rects)
            if scan:
                rects = [scan.pad(r) for r in rects]
            found.append({"kind": kind, "label": label, "text": value, "page": i, "context": context,
                          "places": min(places, len(rects)) or len(rects),
                          "rects": [[round(r.x0, 5), round(r.y0, 5), round(r.width, 5), round(r.height, 5)] for r in rects]})

        seen = set()
        for a, b in names[i]:
            value = " ".join(text[a:b].split())
            if value not in seen:
                seen.add(value)
                add("ad", "Ad soyad", value, _context(text, a, b))
        alone = person_names.find_words(text, family, names[i])
        for value in dict.fromkeys(text[a:b] for a, b in alone):
            # Aynı kelime başka yerde bir özel adın parçası olabilir (Tanyeri Sokak): yalnızca kabul edilen geçişler
            starts = [m.start() for m in re.finditer(rf"(?<!\w){re.escape(value)}(?!\w)", text)]
            mine = [a for a, b in alone if text[a:b] == value]
            add("soyad", "Tek geçen soyad", value, _context(text, mine[0], mine[0] + len(value)), exact=True,
                pick=({starts.index(a) for a in mine if a in starts}, len(starts)))
        for kind, label, pattern, valid in PERSONAL_DATA:
            seen = set()
            for m in pattern.finditer(text):
                value = " ".join(m.group().split())
                if value in seen or (valid and not valid(value)):
                    continue
                seen.add(value)
                # Vergi no metinde harfe bitişikken alınmadığı gibi sayfada da bir kodun içinden karartılmaz
                add(kind, label, value, _context(text, m.start(), m.end()), glued=kind == "vkn")
        for term in terms:
            term = " ".join(str(term).split())
            if len(term) >= 2:
                k = text.lower().find(term.lower())
                add("ozel", "Aranan", term, _context(text, k, k + len(term)) if k >= 0 else term)
        if len(found) >= limit:
            break
    return found


def op_redact_areas(doc, areas, clean_meta=False, fit=False):
    """KVKK karartması: verilen alanlardaki yazı ve resim kalıcı olarak silinir, yerine siyah kutu konur
    (çizgilere dokunulmaz: tablo kenarları kalır). İstenirse belge bilgileri (yazar, başlık…) de temizlenir.
    fit: kutular elle seçilen metinden gelir; komşu satırlara ve yandaki harflere değmeyecek kadar daraltılır
    (bulunan kişisel verilerin kutuları bulunurken zaten daraltılmıştır)."""
    by_page = {}
    for a in areas or []:
        by_page.setdefault(int(a["page"]), []).extend(a.get("rects") or [])
    if not any(by_page.values()) and not clean_meta:
        raise ToolError("Karartılacak bir şey seçilmedi.")
    for index, rects in by_page.items():
        page = doc[index]
        words = page.get_text("words") if fit else None
        for x, y, w, h in rects:
            rect = _native(page, _disp_rect(page, {"x": x, "y": y, "w": w, "h": h}))
            if fit:
                rect = _redact_rect(rect, words)
            page.add_redact_annot(rect, fill=(0, 0, 0))
        if rects:
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
    if clean_meta:
        doc.set_metadata({})
        doc.del_xml_metadata()
