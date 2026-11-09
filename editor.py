"""PDF düzenleyici oturumları: her işlem yeni bir sürüm üretir, geri al/yinele desteklenir."""
import base64
import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path

import pymupdf

import fonts
import ocr
from formlar import form_fields
from kisisel_veri import find_personal_data, is_scan_page
from paragraflar import _paragraphs
from pdf_ortak import _dir_rotate, _disp_rect, _fname, _native
from tools import ToolError, disk_full, finalize, fix_spaces, hex_to_rgb

# Geri alma: her değişiklik belgenin tam bir kopyasıdır. Bir belgenin sürümleri en çok MAX_HISTORY adım ve
# HISTORY_BYTES yer, açık belgelerin hepsininki birlikte STORE_BYTES yer kaplar; aşılınca en eski adımlar silinir.
# Güncel sürüm (kaydedilmemiş iş, kurtarma) ve bir önceki (son işlemi geri alma) her zaman kalır.
MAX_HISTORY = 40
HISTORY_BYTES = 500 * 2**20
STORE_BYTES = 2 * 2**30
NO_SPACE = "Diskte yer kalmadı; değişiklik uygulanamadı. Belge olduğu gibi duruyor; biraz yer açıp yeniden deneyin."
SAFE_URI = re.compile(r"(?i)^(https?://|mailto:)\S+$")   # web/e-posta bağlantıları; javascript:, file: vb. açılmaz


class PasswordRequired(ToolError):
    """Şifreli PDF: arayüz şifre sorar."""


def file_stamp(path):
    """Dosyanın başka bir yerde değişip değişmediğini anlamak için damgası: [değiştirilme zamanı (ns), boyut]."""
    st = Path(path).stat()
    return [st.st_mtime_ns, st.st_size]


class EditSession:
    def __init__(self, sid, name, src: Path, root: Path, password=None, source=None):
        self.id = sid
        self.name = name
        self.source = source  # Finder'dan açıldıysa özgün dosyanın yolu
        self.encrypted = False
        self.source_stamp = file_stamp(source) if source else None
        self.dir = root / sid
        self.dir.mkdir(parents=True)
        self.rev = 0
        self.history = []  # sürüm dosyaları
        self.future = []
        self.redacted = set()  # karartma içeren sürümler (Kaydet özgün dosyanın üzerine yazmadan önce sorar)
        self.closed = False    # kullanıcı belgeyi kapattı: kaydedilmemiş değişiklikleri kurtarılmaz
        self.signed = False    # e-imzalı: değişiklikler dosyanın sonuna eklenir, imzalı bölüm aynen kalır (bkz. sig_intact)
        self._staged = None
        self.store = None      # açık belgelerin ortak yer sınırı için (SessionStore.trim)
        self.lock = threading.RLock()
        self.touched = time.time()
        self._renders = OrderedDict()
        self._textmaps = OrderedDict()   # (sürüm, sayfa) → arama için sayfa metni
        self.ocr_words = OrderedDict()   # (sürüm, sayfa) → taranmış sayfanın tanınan yazısı (belgeye yazılmaz)
        first = self._new_path()
        try:
            try:
                doc = pymupdf.open(src)
            except Exception:
                raise ToolError(f"{name} açılamadı; dosya bozuk ya da PDF değil.")
            if doc.needs_pass:
                self.encrypted = True
                if not password or not doc.authenticate(password):
                    doc.close()
                    raise PasswordRequired("Şifre yanlış." if password else "Bu PDF şifreli. Açmak için şifresini girin.")
                doc.save(first, encryption=pymupdf.PDF_ENCRYPT_NONE)  # şifresiz çalışma kopyası
            else:
                shutil.copy(src, first)
            if doc.page_count == 0:
                doc.close()
                raise ToolError("PDF'te sayfa yok.")
            self.signed = not self.encrypted and is_signed(doc)
            doc.close()
        except Exception:
            shutil.rmtree(self.dir, ignore_errors=True)
            raise
        self.history.append(first)
        self.saved = first   # en son kaydedilen (ya da açılan) sürüm
        self.persist()

    # Oturumun durumu diske yazılır: uygulama beklenmedik şekilde kapanırsa kaydedilmemiş değişiklikler bir
    # sonraki açılışta kurtarılabilir (SessionStore.scan). pid: oturumun hangi açık uygulamaya ait olduğu.
    def persist(self):
        meta = {"name": self.name, "source": self.source, "source_stamp": self.source_stamp, "encrypted": self.encrypted,
                "history": [p.name for p in self.history], "future": [p.name for p in self.future],
                "saved": self.saved.name, "redacted": [p.name for p in self.redacted], "closed": self.closed,
                "signed": self.signed, "pid": os.getpid(), "touched": time.time()}
        tmp = self.dir / (META + ".tmp")
        try:
            tmp.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.dir / META)
        except OSError:   # disk doldu: kurtarma bilgisi bir önceki hâlinde kalır, açık belge etkilenmez
            tmp.unlink(missing_ok=True)

    def source_changed(self, target):
        """Dosya açıldığından (ya da son kaydedildiğinden) beri başka bir yerde değiştirildi mi: değiştirilme zamanı
        nanosaniyesine kadar ve boyutu birlikte karşılaştırılır; saniyenin altındaki değişiklikler de yakalanır.
        Damgası bilinmeyen oturumda (eski sürümden kurtarılan) değişmiş sayılır: üzerine yazmadan önce sorulur."""
        return self.source_stamp is None or file_stamp(target) != self.source_stamp

    @classmethod
    def load(cls, folder: Path):
        """Önceki bir çalışmadan kalan oturum (otomatik kurtarma)."""
        meta = json.loads((folder / META).read_text(encoding="utf-8"))
        s = cls.__new__(cls)
        s.id, s.dir, s.name, s.source = folder.name, folder, meta["name"], meta.get("source")
        s.encrypted, s.source_stamp = meta.get("encrypted", False), meta.get("source_stamp")
        s.history = [folder / n for n in meta["history"] if (folder / n).exists()]
        s.future = [folder / n for n in meta.get("future", []) if (folder / n).exists()]
        if not s.history:
            raise ToolError("Kurtarılacak belgenin dosyaları bulunamadı.")
        s.saved, s.redacted = folder / meta["saved"], {folder / n for n in meta.get("redacted", [])}
        s.rev = max(int(p.stem[1:]) for p in [*s.history, *s.future])
        s.lock, s.touched, s._renders, s.closed = threading.RLock(), time.time(), OrderedDict(), False
        s.signed, s._staged, s._textmaps, s.ocr_words = meta.get("signed", False), None, OrderedDict(), OrderedDict()
        s.store = None
        return s

    @property
    def unsaved(self):
        return self.path != self.saved

    def _new_path(self):
        self.rev += 1
        return self.dir / f"v{self.rev:04d}.pdf"

    @property
    def path(self):
        return self.history[-1]

    @property
    def sig_intact(self):
        """E-imza geçerli mi? Karartılan sürüm baştan yazılır (silinen yazı dosyanın imzalı bölümünde kalmasın);
        onun ve ondan türeyen sürümlerin imzası geçersizdir, sonraki değişiklikler de artımlı yazılmaz."""
        return self.signed and self.path not in self.redacted

    def open(self):
        return pymupdf.open(self.path)

    def open_for_edit(self):
        """Değiştirilecek belge. E-imzalıysa güncel sürümün kopyası açılır: commit değişiklikleri o dosyanın sonuna
        ekler (artımlı kaydetme), imzalı bölümün baytları değişmez."""
        if not self.sig_intact:
            return self.open()
        staged = self._new_path()
        try:
            shutil.copy(self.path, staged)
        except Exception as e:
            self._write_failed(e, staged)
        self._staged = staged
        return pymupdf.open(staged)

    def abort_edit(self):
        """İşlem yarıda kaldı: hazırlanan kopya silinir."""
        if self._staged:
            self._staged.unlink(missing_ok=True)
            self._staged = None

    def commit(self, doc, redacted=False):
        if doc.page_count == 0:
            doc.close()
            self.abort_edit()
            raise ToolError("Belgede en az bir sayfa kalmalı.")
        fix_spaces(doc)
        staged, self._staged = self._staged, None
        signed = self.signed
        p = staged if staged and doc.name == str(staged) else self._new_path()
        tmp = p.with_suffix(".tam.pdf")
        try:
            if p != staged:
                doc.save(p, garbage=1, deflate=True)
            else:
                incremental = False
                if not redacted:
                    try:
                        doc.saveIncr()
                        incremental = True
                    except Exception:   # artımlı yazılamayan (onarılmış) dosya: baştan yazılır, imza korunamaz
                        self.signed = False
                if not incremental:
                    # Karartma artımlı eklenirse silinen yazı dosyanın imzalı bölümünde okunabilir kalır: belge baştan
                    # yazılır, eski bölüm ve artık kullanılmayan nesneler atılır (imza geçersiz olur; arayüz önceden sorar)
                    doc.save(tmp, garbage=1, deflate=True)
                    doc.close()
                    os.replace(tmp, p)
        except Exception as e:
            self.signed = signed
            if not doc.is_closed:
                doc.close()
            self._write_failed(e, p, tmp)
        if not doc.is_closed:
            doc.close()
        self._push(p, redacted)

    def commit_file(self, src):
        """Hazır bir PDF dosyasını (araç çıktısı) yeni sürüm olarak ekler."""
        doc = pymupdf.open(src)
        empty = doc.page_count == 0
        doc.close()
        if empty:
            raise ToolError("Belgede en az bir sayfa kalmalı.")
        p = self._new_path()
        try:
            shutil.copy(src, p)
        except Exception as e:
            self._write_failed(e, p)
        self._push(p)

    def _write_failed(self, e, *files):
        """Yeni sürüm yazılamadı: yarım kalan dosyalar silinir, belge son sürümünde kalır. Disk dolduysa
        anlaşılır mesajla bildirilir."""
        for f in files:
            f.unlink(missing_ok=True)
        if disk_full(e, self.dir):
            raise ToolError(NO_SPACE) from e
        raise e

    def _push(self, p, redacted=False):
        if redacted or self.path in self.redacted:   # karartılmış sürümden türeyen de karartılmıştır
            self.redacted.add(p)
        self.history.append(p)
        for f in self.future:
            f.unlink(missing_ok=True)
        self.future = []
        while len(self.history) > MAX_HISTORY:
            self.history.pop(0).unlink(missing_ok=True)
        self.trim(HISTORY_BYTES)
        self.persist()
        if self.store:
            self.store.trim()

    def versions_size(self):
        """Geri alma ve yineleme sürümlerinin diskte kapladığı yer (bayt)."""
        total = 0
        for p in [*self.history, *self.future]:
            try:
                total += p.stat().st_size
            except OSError:
                pass
        return total

    def trim(self, budget):
        """Sürümler sınırı aşıyorsa önce en eski geri alma adımları, sonra en uzak yineleme adımları silinir; güncel
        sürüm ve bir önceki kalır. Dönen: boşalan yer (bayt). Çağıran oturumun kilidini tutar."""
        size, freed = self.versions_size(), 0
        while size > budget:
            if len(self.history) > 2:
                p = self.history.pop(0)
            elif self.future:
                p = self.future.pop(0)
            else:
                break
            try:
                n = p.stat().st_size
            except OSError:
                n = 0
            p.unlink(missing_ok=True)
            size, freed = size - n, freed + n
        return freed

    def undo(self):
        if len(self.history) < 2:
            return False
        self.future.append(self.history.pop())
        self.persist()
        return True

    def redo(self):
        if not self.future:
            return False
        self.history.append(self.future.pop())
        self.persist()
        return True

    @staticmethod
    def page_key(doc, page):
        """Sayfa içeriği değişmedikçe aynı kalan anahtar (küçük resim önbelleği için)."""
        h = hashlib.md5(doc.xref_object(page.xref, compressed=True).encode())
        h.update(page.read_contents())
        for a in page.annots():
            h.update(doc.xref_object(a.xref, compressed=True).encode())
        for w in page.widgets():   # form alanının değeri değişince sayfa yeniden çizilsin
            h.update(doc.xref_object(w.xref, compressed=True).encode())
        return h.hexdigest()[:12]

    def info(self):
        doc = self.open()
        pages = [{"w": round(p.rect.width, 2), "h": round(p.rect.height, 2), "rot": p.rotation,
                  "k": self.page_key(doc, p)} for p in doc]
        # metin katmanı yoksa okuyucu "Metni tanı" önerir (resmi olmayan boş sayfa ya da yalnızca form alanı taranmış sayılmaz)
        scanned = ocr.needs_ocr(doc) and any(doc[i].get_images() for i in range(min(6, doc.page_count)))
        form = bool(doc.is_form_pdf)  # doldurulabilir alanlar
        doc.close()
        return {
            "id": self.id, "name": self.name, "rev": self.path.stem, "pages": pages, "path": self.source,
            "scanned": scanned, "form": form,
            # notlar/vurgular özgün dosyaya yazılabilir mi (Finder'dan açılmış, şifresiz PDF)
            "can_save_source": bool(self.source) and str(self.source).lower().endswith(".pdf") and not self.encrypted,
            "unsaved": self.unsaved, "encrypted": self.encrypted,
            # kaydedilen hâlden sonra karartma yapıldı: Kaydet özgün dosyayı korumayı önerir
            "redacted": self.path in self.redacted and self.saved not in self.redacted,
            "signed": self.sig_intact,
            "canUndo": len(self.history) > 1, "canRedo": bool(self.future),
            "size": self.path.stat().st_size,   # durum çubuğunda: belgenin şu anki hâlinin boyutu
        }

    def render(self, index, width):
        doc = self.open()
        if not 0 <= index < doc.page_count:
            doc.close()
            raise ToolError("Sayfa bulunamadı.")
        page = doc[index]
        key = (self.page_key(doc, page), width)
        if key in self._renders:
            doc.close()
            self._renders.move_to_end(key)
            return self._renders[key]
        zoom = width / page.rect.width
        png = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False).tobytes("png")
        doc.close()
        self._renders[key] = png
        while len(self._renders) > 400:
            self._renders.popitem(last=False)
        return png

    def search(self, query, limit=3000):
        """Metin arama: sayfa başına eşleşmeler (ekran koordinatlarında, 0–1 arası) ve ilk eşleşmenin çevresi.
        Türkçe büyük-küçük harf kurallarıyla (ŞAHİN = şahin, İ/i ve I/ı ayrı), şapkasız (hakim = hâkim);
        satır sonunda tireyle bölünmüş kelimeler de bulunur."""
        needle = fold_text(" ".join(query.split()))
        if not needle:
            return []
        doc = self.open()
        hits, total = [], 0
        try:
            for i, page in enumerate(doc):
                folded, chars, plain = self._text_map(doc, i)
                W, H, m = page.rect.width, page.rect.height, page.rotation_matrix
                boxes, first, k = [], None, folded.find(needle)
                while k >= 0:
                    first = k if first is None else first
                    lines = {}
                    for c in chars[k:k + len(needle)]:
                        if c:
                            r = lines.get(c[1])
                            lines[c[1]] = c[0] if r is None else r | c[0]
                    for r in lines.values():
                        d = (r * m).normalize()
                        boxes.append([d.x0 / W, d.y0 / H, d.width / W, d.height / H])
                    k = folded.find(needle, k + len(needle))
                if boxes:
                    a, b = max(0, first - 50), min(len(plain), first + len(needle) + 50)
                    while 0 < a < first and not plain[a - 1].isspace():   # alıntı kelime başından başlasın
                        a += 1
                    while first + len(needle) < b < len(plain) and not plain[b].isspace():
                        b -= 1
                    snippet = " ".join(plain[a:b].split())
                    hits.append({"page": i, "rects": boxes, "snippet": snippet})
                    total += len(boxes)
                    if total >= limit:
                        break
        finally:
            doc.close()
        return hits

    def _text_map(self, doc, index):
        """Sayfa metni arama için: (karşılaştırma biçimi, her harfin (kutusu, satırı) ya da None, düz metin).
        Satırlar boşlukla, bloklar satır sonuyla ayrılır; satır sonu hece tiresi atlanır (reddedil- + diğini)."""
        key = (self.path, index)
        if key in self._textmaps:
            self._textmaps.move_to_end(key)
            return self._textmaps[key]
        folded, chars, plain = [], [], []

        def put(ch, info):
            if ch.isspace():
                if not plain or plain[-1].isspace():
                    return
                ch, info = (ch if ch == "\n" else " "), None
            plain.append(ch)
            folded.append(fold_char(ch))
            chars.append(info)
        line_no = 0
        for block in doc[index].get_text("rawdict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]:
            for line in block.get("lines", []):
                line_no += 1
                text = [(ch["c"], (pymupdf.Rect(ch["bbox"]), line_no)) for span in line["spans"] for ch in span["chars"]]
                if not text:
                    continue
                if len(plain) >= 2 and plain[-1] in "-\u00ad" and plain[-2].isalpha():   # satır sonu tiresi: boşluksuz
                    if (len(plain) >= 3 and plain[-3].isalpha() and text[0][0].isalpha()
                            and text[0][0] == text[0][0].lower()):   # hece tiresi kalkar (reddedil- + diğini)
                        for lst in (plain, folded, chars):
                            lst.pop()
                    else:   # e- + posta → e-posta
                        plain[-1], folded[-1] = "-", "-"
                else:
                    put(" ", None)
                for ch, info in text:
                    put(ch, info)
            put("\n", None)
        result = ("".join(folded), chars, "".join(plain))
        self._textmaps[key] = result
        while len(self._textmaps) > 300:
            self._textmaps.popitem(last=False)
        return result

    def fields(self):
        doc = self.open()
        try:
            return form_fields(doc)
        finally:
            doc.close()

    def annotations(self):
        """Vurgular ve notlar (ekran koordinatlarında, 0–1 arası)"""
        doc = self.open()
        out = []
        for i, page in enumerate(doc):
            W, H, m = page.rect.width, page.rect.height, page.rotation_matrix
            for a in page.annots():
                kind = a.type[1]
                if kind not in ("Highlight", "Text", "FreeText", "Underline", "StrikeOut"):
                    continue
                r = (a.rect * m).normalize()
                stroke = (a.colors or {}).get("stroke") or (1, 0.85, 0.2)
                quoted = annot_quote(page, a)[:200]
                v = a.vertices or [] if kind in MARK_TYPES else []
                parts = [(pymupdf.Quad(v[k:k + 4]).rect * m).normalize() for k in range(0, len(v) - 3, 4)] or [r]
                out.append({"page": i, "xref": a.xref, "type": kind,
                            "x": r.x0 / W, "y": r.y0 / H, "w": r.width / W, "h": r.height / H,
                            "rects": [[q.x0 / W, q.y0 / H, q.width / W, q.height / H] for q in parts],
                            "content": a.info.get("content", ""), "quote": quoted, "author": a.info.get("title", ""),
                            "color": "#%02x%02x%02x" % tuple(int(c * 255) for c in stroke[:3])})
        toc = [{"level": lv, "title": t, "page": p - 1 if 0 < p <= doc.page_count else -1,
                 "y": dest_y(doc, p - 1, (dest or {}).get("to"))}
               for lv, t, p, *rest in doc.get_toc(simple=False) for dest in [rest[0] if rest else None]]
        doc.close()
        return {"annots": out, "outline": toc}

    def links(self, index):
        """Sayfadaki tıklanabilir bağlantılar (ekran koordinatlarında, 0–1 arası):
        belge içi (içindekiler satırları gibi: hedef sayfa ve konum) ya da web/e-posta adresi."""
        doc = self.open()
        try:
            if not 0 <= index < doc.page_count:
                raise ToolError("Sayfa bulunamadı.")
            page = doc[index]
            W, H, m = page.rect.width, page.rect.height, page.rotation_matrix
            out = []
            for ln in page.get_links():
                r = (pymupdf.Rect(ln["from"]) * m).normalize()
                item = {"x": r.x0 / W, "y": r.y0 / H, "w": r.width / W, "h": r.height / H}
                target = ln.get("page")
                if ln["kind"] in (pymupdf.LINK_GOTO, pymupdf.LINK_NAMED) and target is not None and 0 <= target < doc.page_count:
                    item.update(page=target, to=dest_y(doc, target, ln.get("to")))
                elif ln["kind"] == pymupdf.LINK_URI and SAFE_URI.match(ln.get("uri") or ""):
                    item["uri"] = ln["uri"]
                else:
                    continue
                out.append(item)
            return out
        finally:
            doc.close()

    def personal_data(self, terms=(), scans=None):
        """KVKK: belgedeki kişisel verileri bulur (T.C. kimlik no, vergi kimlik no, IBAN, kart, telefon, e-posta ve verilen
        kelimeler). Her bulgu: tür, değer, sayfa, çevresindeki metin ve ekran dikdörtgenleri (0–1 arası).
        scans: taranmış sayfaların tanınan yazısı {sayfa: satırlar} (bkz. scan_pages)."""
        scans = {i: lines for i, lines in (scans or {}).items() if lines}
        doc = self.open()
        try:
            has_text = bool(scans) or any(page.get_text("text").strip() for page in doc)
            return {"items": find_personal_data(doc, terms, scans=scans) if has_text else [], "has_text": has_text,
                    "scanned": sorted(scans)}
        finally:
            doc.close()

    def is_scan(self, index):
        doc = self.open()
        try:
            return is_scan_page(doc[index])
        finally:
            doc.close()

    def scan_pages(self):
        """Yazısı resmin içinde olan (taranmış) sayfalar."""
        doc = self.open()
        try:
            return [i for i, page in enumerate(doc) if is_scan_page(page)]
        finally:
            doc.close()

    def words(self, index):
        """Okuyucunun seçilebilir metin katmanı ve düzenleyicinin metne yapışan işaretlemesi: satır satır kelimeler
        (ekran koordinatlarında, 0–1 arası). Kelime: [x, sonraki kelimeye kadar genişlik, metin, kendi genişliği].
        Kelime kelime kurulduğu için bir satır, ya da bir satırın istenen kısmı seçilip vurgulanabilir.
        Her kelimenin genişliği bir sonrakinin başına kadar uzatılır: seçim satır boyunca kesintisiz görünür."""
        doc = self.open()
        try:
            page = doc[index]
            rot = page.rotation_matrix
            W, H = page.rect.width, page.rect.height
            tp = page.get_textpage(flags=pymupdf.TEXTFLAGS_TEXT)
            kinds = {}   # (blok, satır) → (ekranda yatay mı, tırnaklı yazı tipi mi)
            for b in page.get_text("dict", textpage=tp)["blocks"]:
                for n, line in enumerate(b.get("lines", [])):
                    d = pymupdf.Point(line["dir"]) * pymupdf.Matrix(rot.a, rot.b, rot.c, rot.d, 0, 0)
                    spans = [s for s in line["spans"] if s["text"].strip()]
                    serif = bool(spans) and bool(max(spans, key=lambda s: len(s["text"]))["flags"] & 4)
                    kinds[(b["number"], n)] = (abs(d.x - 1) <= 0.02 and abs(d.y) <= 0.02, serif)
            grouped = {}
            for x0, y0, x1, y1, text, block, line, _ in page.get_text("words", textpage=tp):
                horizontal, serif = kinds.get((block, line), (False, False))
                if horizontal:   # yalnızca ekranda yatay satırlar
                    grouped.setdefault((block, line), (serif, []))[1].append((pymupdf.Rect(x0, y0, x1, y1) * rot, text))
            out = []
            for serif, words in grouped.values():   # metnin okunma sırası
                words.sort(key=lambda w: w[0].x0)
                top, bottom = min(r.y0 for r, _ in words), max(r.y1 for r, _ in words)
                items = []
                for k, (r, text) in enumerate(words):
                    end = words[k + 1][0].x0 if k + 1 < len(words) else r.x1
                    items.append([round(r.x0 / W, 5), round(max(end - r.x0, r.width) / W, 5), text, round(r.width / W, 5)])
                out.append({"y": round(top / H, 5), "h": round((bottom - top) / H, 5), "serif": serif, "words": items})
            return out
        finally:
            doc.close()

    def lines(self, index):
        """Düzenlenebilir metin satırları (ekran koordinatlarında, 0–1 arası)."""
        doc = self.open()
        page = doc[index]
        rot = page.rotation_matrix
        W, H = page.rect.width, page.rect.height
        out = []
        for b in page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]:
            for line in b.get("lines", []):
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                d = pymupdf.Point(line["dir"]) * pymupdf.Matrix(rot.a, rot.b, rot.c, rot.d, 0, 0)
                if abs(d.x - 1) > 0.02 or abs(d.y) > 0.02:  # yalnızca ekranda yatay satırlar
                    continue
                bbox = pymupdf.Rect(line["bbox"])
                disp = bbox * rot
                first = max(spans, key=lambda s: len(s["text"]))
                text = "".join(s["text"] for s in line["spans"]).strip()
                out.append({
                    "text": text,
                    "bbox": [round(v, 3) for v in bbox],
                    "origin": [round(v, 3) for v in spans[0]["origin"]],
                    "x": disp.x0 / W, "y": disp.y0 / H, "w": disp.width / W, "h": disp.height / H,
                    "size": round(first["size"], 2),
                    "font": first["font"],
                    "color": "#%06x" % first["color"],
                    "bold": bool(first["flags"] & 16),
                    "italic": bool(first["flags"] & 2),
                    "serif": bool(first["flags"] & 4),
                    "rotate": _dir_rotate(line["dir"]),
                })
        # Döndürülmemiş sayfalarda satırlar paragraflara gruplanır: düzenlenen metin paragrafın
        # içinde yeniden dizilir (Word'deki gibi). Döndürülmüş sayfalarda her satır ayrı düzenlenir.
        if page.rotation == 0 and out:
            out = _paragraphs(out, W, H)
        doc.close()
        return out


_FOLD = {"I": "ı", "İ": "i", "â": "a", "Â": "a", "î": "i", "Î": "i", "û": "u", "Û": "u", "\u00ad": "-"}


def fold_char(ch):
    """Aramada karşılaştırma biçimi: Türkçe küçük harf (İ → i, I → ı), şapkasız; her zaman tek karakter."""
    f = _FOLD.get(ch) or ch.lower()
    return f if len(f) == 1 else ch


def fold_text(text):
    return "".join(fold_char(ch) for ch in text)


def ocr_word_lines(found, font):
    """Metin tanımanın satırlarını okuyucunun kelime biçimine çevirir (bkz. EditSession.words): tanıma yalnız satırın
    kutusunu verir; kelimelerin satırdaki yeri yazı tipi genişliklerine göre oranlanır."""
    out = []
    space = font.text_length(" ", fontsize=10)
    for line in found:
        words = line.get("text", "").split()
        if not words:
            continue
        widths = [font.text_length(w, fontsize=10) for w in words]
        k = line["w"] / ((sum(widths) + space * (len(words) - 1)) or 1)
        x, items = line["x"], []
        for n, (width, text) in enumerate(zip(widths, words)):
            last = n == len(words) - 1
            items.append([round(x, 5), round((width if last else width + space) * k, 5), text, round(width * k, 5)])
            x += (width + space) * k
        out.append({"y": round(line["y"], 5), "h": round(line["h"], 5), "serif": False, "words": items})
    return out


def annot_quote(page, annot):
    """Vurgu, altı ya da üstü çizili işaretin kapsadığı metin. Her işaret dörtgeninin ortasındaki şerit okunur:
    komşu satırlar ve harfler karışmaz."""
    if annot.type[1] not in ("Highlight", "Underline", "StrikeOut"):
        return ""
    v = annot.vertices or []
    parts = []
    for k in range(0, len(v) - 3, 4):
        q = pymupdf.Quad(v[k:k + 4]).rect
        h = q.height
        parts.append(page.get_textbox(pymupdf.Rect(q.x0 + 0.5, q.y0 + h * 0.3, q.x1 - 0.5, q.y1 - h * 0.3)))
    return " ".join(" ".join(parts).split())


def is_signed(doc):
    """Belgede e-imza var mı? İmza değeri (/V) taşıyan imza alanı aranır: imzalanmamış boş imza alanı (form
    şablonlarında olur) imza sayılmaz; yoksa belge gereksiz yere artımlı yazılır, Sıkıştır imza uyarısı verir."""
    try:
        if not doc.is_form_pdf:
            return False
        for page in doc:
            for w in page.widgets(types=[pymupdf.PDF_WIDGET_TYPE_SIGNATURE]):
                x = w.xref
                for _ in range(10):   # değer alanın kendisinde ya da üst alanında (Parent) durur
                    if doc.xref_get_key(x, "V")[0] != "null":
                        return True
                    kind, parent = doc.xref_get_key(x, "Parent")
                    if kind != "xref":
                        break
                    x = int(parent.split()[0])
        return False
    except Exception:
        return False


META = "oturum.json"
RECOVER_DAYS = 7   # kaydedilmemiş değişiklikler bu kadar gün kurtarılabilir (Ayarlar › Kaydetme ile değişir)
SESSION_ID = re.compile(r"^[0-9a-f]{12}$")


def _alive(pid):
    """Bu numaralı işlem (başka bir açık Koç PDF Pro) çalışıyor mu?"""
    if not pid:
        return False
    if os.name == "nt":   # Windows'ta os.kill(pid, 0) işlemi sonlandırır: soru Windows'a sorulur
        import ctypes
        k32 = ctypes.windll.kernel32
        handle = k32.OpenProcess(0x1000, False, int(pid))   # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        k32.GetExitCodeProcess(handle, ctypes.byref(code))
        k32.CloseHandle(handle)
        return code.value == 259   # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


class SessionStore:
    def __init__(self, root: Path):
        self.root = root
        self.sessions = {}
        self.lock = threading.Lock()
        self.recoverable = {}   # önceki çalışmalardan kalan, kaydedilmemiş değişikliği olan oturumlar
        self.scan_lock = threading.Lock()
        self.scanned = False

    def scan(self):
        """Önceki çalışmalardan kalan oturum klasörleri: kaydedilmemiş değişikliği olanlar kurtarılmak üzere
        listelenir (7 gün), ötekiler silinir. Açık başka bir Koç PDF Pro'nun oturumlarına dokunulmaz."""
        with self.scan_lock:
            now = time.time()
            for d in self.root.iterdir():
                if not d.is_dir() or d.name in self.sessions or d.name in self.recoverable:
                    continue
                try:
                    meta = json.loads((d / META).read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    meta = None
                if meta and (meta.get("pid") == os.getpid() or _alive(meta.get("pid"))):
                    continue
                age = now - (meta["touched"] if meta else d.stat().st_mtime)
                if meta is None and age < 6 * 3600:   # durumu yazılmayan eski sürümün açık oturumu olabilir
                    continue
                if (meta and meta["history"] and meta["history"][-1] != meta.get("saved") and not meta.get("closed")
                        and age < RECOVER_DAYS * 86400):
                    self.recoverable[d.name] = {"id": d.name, "name": meta["name"], "source": meta.get("source"),
                                                "ts": meta["touched"],
                                                "time": time.strftime("%d.%m.%Y %H:%M", time.localtime(meta["touched"]))}
                    continue
                shutil.rmtree(d, ignore_errors=True)
            self.scanned = True

    def restore(self, sid):
        """Kurtarılabilir oturumu yeniden açar."""
        if sid not in self.recoverable:
            raise ToolError("Kurtarılacak belge bulunamadı.")
        s = EditSession.load(self.root / sid)
        s.store = self
        s.persist()   # artık bu uygulamanın
        self.recoverable.pop(sid)
        with self.lock:
            self.sessions[sid] = s
        return s

    def discard(self, sid):
        """Oturumu siler (kurtarılabilir belgeyi sil, kapatılan belge)."""
        if not SESSION_ID.match(sid or ""):
            return
        self.recoverable.pop(sid, None)
        with self.lock:
            self.sessions.pop(sid, None)
        shutil.rmtree(self.root / sid, ignore_errors=True)

    def create(self, src: Path, name: str, password=None, source=None):
        sid = uuid.uuid4().hex[:12]
        s = EditSession(sid, name, src, self.root, password=password, source=source)
        s.store = self
        with self.lock:
            self.sessions[sid] = s
        return s

    def get(self, sid):
        s = self.sessions.get(sid)
        if not s:
            raise ToolError("Düzenleme oturumu bulunamadı; dosyayı yeniden açın.")
        s.touched = time.time()
        return s

    def touch_all(self):
        """Bilgisayar uykudan uyandı: açık pencereler uykuda "buradayım" diyemedi; boşta geçen süre şimdi başlar."""
        now = time.time()
        with self.lock:
            for s in self.sessions.values():
                s.touched = now

    def trim(self):
        """Açık belgelerin sürümleri birlikte STORE_BYTES'ı aşıyorsa eski adımlar silinir: önce kapatılmış belgelerden,
        sonra en çok yer kaplayandan başlayarak (her belgenin güncel sürümü ve son adımı kalır). O anda başka bir
        işlemin sürdüğü belgeye dokunulmaz."""
        with self.lock:
            sessions = list(self.sessions.values())
        sizes = {s.id: s.versions_size() for s in sessions}
        over = sum(sizes.values()) - STORE_BYTES
        for s in sorted(sessions, key=lambda s: (not s.closed, -sizes[s.id])):
            if over <= 0:
                break
            if not s.lock.acquire(blocking=False):
                continue
            try:
                freed = s.trim(sizes[s.id] - over)
                if freed:
                    s.persist()
                over -= freed
            finally:
                s.lock.release()

    def cleanup(self, max_age=6 * 3600):
        """Uzun süre kullanılmayan oturumlar silinir. Açık belge penceresi oturumunu ara ara yokladığından
        (/touch) belge ekranda durdukça silinmez; sekmesi kapatılan belgenin oturumu birkaç saat sonra gider."""
        now = time.time()
        with self.lock:
            for sid, s in list(self.sessions.items()):
                idle = now - s.touched
                if idle > max_age and (not s.unsaved or s.closed or idle > RECOVER_DAYS * 86400):   # kaydedilmemiş iş korunur
                    shutil.rmtree(s.dir, ignore_errors=True)
                    del self.sessions[sid]


def dest_y(doc, index, to):
    """Bir hedefin (başlık, bağlantı) sayfadaki dikey konumu: 0 = sayfanın üstü, 1 = altı."""
    if to is None or not 0 <= index < doc.page_count:
        return 0
    page = doc[index]
    y = (pymupdf.Point(to) * page.rotation_matrix).y / (page.rect.height or 1)
    return round(min(max(y, 0), 1), 4)


# ---------------------------------------------------------------- işlemler

def op_rotate(doc, pages, angle):
    for i in pages:
        p = doc[i]
        p.set_rotation((p.rotation + int(angle)) % 360)


def op_delete(doc, pages):
    if len(set(pages)) >= doc.page_count:
        raise ToolError("Tüm sayfalar silinemez; en az bir sayfa kalmalı.")
    doc.delete_pages(sorted(set(pages)))


def op_reorder(doc, order):
    if sorted(order) != list(range(doc.page_count)):
        raise ToolError("Geçersiz sayfa sırası.")
    doc.select(order)


def op_duplicate(doc, pages):
    # Bağımsız kopya (select() aynı sayfa nesnesini paylaştırır)
    for i in sorted(set(pages), reverse=True):
        doc.fullcopy_page(i, i + 1)


def op_blank(doc, after):
    ref = doc[min(max(after, 0), doc.page_count - 1)]
    doc.new_page(after + 1, width=ref.rect.width, height=ref.rect.height)


def op_insert_pdf(doc, src_path, at):
    other = pymupdf.open(src_path)
    if other.needs_pass:
        raise ToolError("Eklenen PDF şifreli.")
    doc.insert_pdf(other, start_at=at)
    other.close()


def op_insert_images(doc, img_paths, at):
    ref = doc[min(max(at - 1, 0), doc.page_count - 1)]
    W, H = ref.rect.width, ref.rect.height
    for k, path in enumerate(img_paths):
        page = doc.new_page(at + k, width=W, height=H)
        m = 24
        page.insert_image(pymupdf.Rect(m, m, W - m, H - m), filename=str(path), keep_proportion=True)


ERASE_TYPES = {"redact": (0, 0, 0), "whiteout": (1, 1, 1)}


def op_annotate(doc, index, items, cache_dir):
    page = doc[index]
    rot = page.rotation
    # 1) Önce silme alanları (karartma / beyaz kutu): altındaki metni ve resmi gerçekten kaldırır.
    #    Yeni eklenen metinler bunlardan sonra yazılır, böylece beyaz kutunun üstüne yazılabilir.
    erase = [it for it in items if it.get("type") in ERASE_TYPES]
    for it in erase:
        disp = _disp_rect(page, it)
        if not disp.is_empty:
            page.add_redact_annot(_native(page, disp), fill=ERASE_TYPES[it["type"]])
    if erase:
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_PIXELS,
                              graphics=pymupdf.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED)
    # 2) Sonra eklemeler, verilen sırayla
    for it in items:
        kind = it.get("type")
        if kind in ERASE_TYPES:
            continue
        if kind == "pen":
            pts = [pymupdf.Point(x * page.rect.width, y * page.rect.height) * page.derotation_matrix
                   for x, y in it["points"]]
            if len(pts) < 2:
                continue
            shape = page.new_shape()
            shape.draw_polyline(pts)
            shape.finish(color=hex_to_rgb(it.get("color")), width=float(it.get("width", 2)),
                         lineCap=1, lineJoin=1, closePath=False,
                         stroke_opacity=float(it.get("opacity", 1)))
            shape.commit()
            continue
        disp = _disp_rect(page, it)
        if disp.is_empty:
            continue
        nat = _native(page, disp)
        if kind == "text":
            text = it.get("text", "")
            if not text.strip():
                continue
            family = "serif" if it.get("font") == "serif" else "sans"
            path = fonts.resolve("Times New Roman" if family == "serif" else "Arial", text,
                                 bold=it.get("bold", False), italic=it.get("italic", False),
                                 serif=family == "serif", cache_dir=cache_dir)
            size = float(it.get("size", 12))
            # Kutu metne yetmezse aşağı doğru genişlet
            tall = pymupdf.Rect(disp.x0, disp.y0, max(disp.x1, disp.x0 + 10), page.rect.height)
            align = {"left": 0, "center": 1, "right": 2}.get(it.get("align"), 0)
            page.insert_textbox(_native(page, tall), text, fontsize=size, fontname=_fname(path),
                                fontfile=path, color=hex_to_rgb(it.get("color")), rotate=rot,
                                align=align, lineheight=1.18)
        elif kind == "rect":
            fill = hex_to_rgb(it["fill"]) if it.get("fill") else None
            stroke = hex_to_rgb(it["stroke"]) if it.get("stroke") else None
            page.draw_rect(nat, color=stroke, fill=fill, width=float(it.get("width", 1.5)) if stroke else 0,
                           fill_opacity=float(it.get("opacity", 1)), overlay=True)
        elif kind == "highlight":
            annot = page.add_highlight_annot(nat)
            annot.set_colors(stroke=hex_to_rgb(it.get("color"), (1, 0.9, 0.2)))
            _set_author(annot)
            annot.update()
        elif kind == "image":
            data = it["data"].split(",", 1)[-1]
            page.insert_image(nat, stream=base64.b64decode(data), keep_proportion=True,
                              rotate=rot, overlay=True)
        elif kind == "stamp":
            _draw_stamp(page, disp, it, cache_dir)


# Kaşe: ölçüler doğal boyutta (pt); kutuya sığacak kadar büyütülüp küçültülür.
# Düzenleyicideki önizleme (editor.js stampLayout) aynı ölçüleri kullanır.
STAMP = {"main": 18, "sub": 9.5, "pad": 7, "border": 1.8, "radius": 3}


def _stamp_layout(lines, width_of):
    """Satırlar [(metin, boyut, kalın, üst kenar)], doğal genişlik ve yükseklik. İlk satır kalın ve büyük."""
    edge = STAMP["pad"] + STAMP["border"]
    rows, y = [], edge
    for k, text in enumerate(lines):
        size = STAMP["main"] if k == 0 else STAMP["sub"]
        rows.append((text, size, k == 0, y))
        y += size * 1.15 + 3 if k == 0 else size * 1.35
    return rows, max(width_of(t, size, bold) for t, size, bold, _ in rows) + 2 * edge, y + edge


def _draw_stamp(page, disp, it, cache_dir):
    lines = [" ".join(str(line).split()) for line in it.get("lines") or []]
    lines = [line for line in lines if line][:4]
    if not lines:
        return
    color = hex_to_rgb(it.get("color"), (0.78, 0.16, 0.16))
    files = {bold: fonts.resolve("Arial", " ".join(lines), bold=bold, cache_dir=cache_dir) for bold in (True, False)}
    rows, nw, nh = _stamp_layout(lines, lambda t, size, bold: fonts.font_obj(files[bold]).text_length(t, fontsize=size))
    k = min(disp.width / nw, disp.height / nh)
    ox, oy = disp.x0 + (disp.width - nw * k) / 2, disp.y0 + (disp.height - nh * k) / 2
    bw = STAMP["border"] * k
    frame = pymupdf.Rect(ox + bw / 2, oy + bw / 2, ox + nw * k - bw / 2, oy + nh * k - bw / 2)
    page.draw_rect(_native(page, frame), color=color, width=bw, radius=STAMP["radius"] * k / min(frame.width, frame.height))
    for text, size, bold, top in rows:
        line = pymupdf.Rect(ox, oy + top * k, ox + nw * k, oy + (top + size * 1.6) * k)
        page.insert_textbox(_native(page, line), text, fontsize=size * k, fontname=_fname(files[bold]),
                            fontfile=files[bold], color=color, rotate=page.rotation, align=1)


# İşaret türleri: PDF'in standart metin işaretleri (başka PDF programlarında da aynı görünür)
AUTHOR = ""   # eklenen not ve işaretlerin yazarı (PDF'te T; Ayarlar › Belgeler › Adınız). Boşsa yazılmaz


def _set_author(annot):
    if AUTHOR:
        annot.set_info(title=AUTHOR)


MARK_KINDS = {"highlight": ("add_highlight_annot", (1, 0.9, 0.2)),
              "underline": ("add_underline_annot", (0.84, 0.27, 0.24)),
              "strikeout": ("add_strikeout_annot", (0.84, 0.27, 0.24))}


def op_highlight(doc, index, rects, color, note="", kind="highlight"):
    """Vurgu, altı çizili ya da üstü çizili metin işareti (rects: ekran koordinatlarında, satır başına bir)."""
    page = doc[index]
    W, H = page.rect.width, page.rect.height
    native = [(pymupdf.Rect(x * W, y * H, (x + w) * W, (y + h) * H) * page.derotation_matrix).normalize()
              for x, y, w, h in rects]
    native = [r for r in native if not r.is_empty]
    if not native:
        raise ToolError("İşaretlenecek metni seçin.")
    method, default = MARK_KINDS.get(kind, MARK_KINDS["highlight"])
    annot = getattr(page, method)(native)
    annot.set_colors(stroke=hex_to_rgb(color, default))
    if note:
        annot.set_info(content=note)
    _set_author(annot)
    annot.update()


def op_note(doc, index, x, y, text):
    page = doc[index]
    point = pymupdf.Point(x * page.rect.width, y * page.rect.height) * page.derotation_matrix
    annot = page.add_text_annot(point, text, icon="Note")
    annot.set_colors(stroke=(1, 0.8, 0.1))
    _set_author(annot)
    annot.update()


def _find_annot(page, xref):
    if xref not in {a.xref for a in page.annots()}:
        raise ToolError("Not bulunamadı; sayfa değişmiş olabilir.")
    return page.load_annot(xref)


def op_annot_delete(doc, index, xref):
    page = doc[index]
    page.delete_annot(_find_annot(page, xref))


MARK_TYPES = {"Highlight": "highlight", "Underline": "underline", "StrikeOut": "strikeout"}


def op_annot_style(doc, index, xref, color=None, kind=None):
    """İşaretin rengini ya da türünü (vurgu, altı çizili, üstü çizili) değiştirir. Tür değişince işaret aynı yerde
    yeni türüyle yeniden oluşturulur; notu korunur. Renk verilmezse: açık renkli vurgu çizgiye dönerken kırmızı,
    koyu renkli çizgi vurguya dönerken sarı olur (açık renk çizgi, koyu renk vurgu okunmaz)."""
    page = doc[index]
    annot = _find_annot(page, xref)
    current = MARK_TYPES.get(annot.type[1])
    if not current:
        raise ToolError("Bu işaretin rengi ya da türü değiştirilemez.")
    stroke = (annot.colors or {}).get("stroke") or MARK_KINDS[current][1]
    if kind and kind != current:
        if kind not in MARK_KINDS:
            raise ToolError("Bilinmeyen işaret türü.")
        method, default = MARK_KINDS[kind]
        light = 0.299 * stroke[0] + 0.587 * stroke[1] + 0.114 * stroke[2] > 0.6
        if not color and (kind == "highlight") != light:
            stroke = default
        v = annot.vertices or []
        quads = [pymupdf.Quad(v[k:k + 4]) for k in range(0, len(v) - 3, 4)]
        info = annot.info
        page.delete_annot(annot)
        annot = getattr(page, method)(quads)
        annot.set_info(content=info.get("content", ""), title=info.get("title", ""))
    if color:
        stroke = hex_to_rgb(color, stroke)
    annot.set_colors(stroke=stroke)
    annot.update()


def op_annot_edit(doc, index, xref, text):
    page = doc[index]                 # sayfa canlı kalmalı; yoksa not sayfadan kopar
    annot = _find_annot(page, xref)
    annot.set_info(content=text)
    annot.update()


def op_bookmark_add(doc, index, title):
    toc = doc.get_toc(simple=False)   # var olan başlıkların sayfa içindeki konumları korunsun
    toc.append([1, title.strip() or f"Sayfa {index + 1}", index + 1])
    doc.set_toc(toc)


def op_bookmark_delete(doc, position):
    toc = doc.get_toc(simple=False)
    if not 0 <= position < len(toc):
        raise ToolError("Yer imi bulunamadı.")
    level = toc[position][0]
    end = position + 1
    while end < len(toc) and toc[end][0] > level:    # alt yer imleriyle birlikte sil
        end += 1
    del toc[position:end]
    doc.set_toc(toc)
