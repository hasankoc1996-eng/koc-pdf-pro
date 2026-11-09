import atexit, io, json, os, sys, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Testler kendi veri klasörünü kullanır: uygulamanın oturumlarına, yedeklerine, son açılanlarına karışmaz
os.environ["PDFSTUDYO_DATA"] = str(Path(__file__).resolve().parent / ".veri")
import pymupdf
import app as A

c = A.app.test_client()


@atexit.register
def _cleanup_sessions():
    """Testlerin açtığı oturumlar silinir (test yarıda kesilse de): uygulamada "kurtarılabilir belge" görünmesinler."""
    for sid in list(A.store.sessions):
        A.store.discard(sid)


H = {"Host": f"127.0.0.1:{A.PORT}"}
T = Path(__file__).parent
ok = True
def check(name, cond, extra=""):
    global ok
    ok &= bool(cond)
    print(("✅" if cond else "❌"), name, extra)

def post(url, files=(), **form):
    data = {k: str(v) for k, v in form.items()}
    data["files"] = [(open(f, "rb"), Path(f).name) for f in files]
    r = c.post(url, data=data, headers=H, content_type="multipart/form-data")
    return r, r.get_json()

def fetch(item):
    r = c.get(item["url"], headers=H); return r.data

check("host guard", c.get("/", headers={"Host": "evil.com:5055"}).status_code == 403)
check("index", c.get("/", headers=H).status_code == 200)
check("Windows sekme kabuğu", b"shell.js" in c.get("/shell", headers=H).data)
check("İkinci açılış: pencere yokken reddedilir", c.post("/api/host/open", json={"paths": []}, headers=H).status_code == 404)
_got = []
A.HOST_OPEN = lambda paths: _got.append(paths) or True
r = c.post("/api/host/open", json={"paths": ["C:\\Belgeler\\dilekce.pdf", 5]}, headers=H)
check("İkinci açılış: açık pencereye iletilir", r.get_json() == {"ok": True} and _got == [["C:\\Belgeler\\dilekce.pdf"]], _got)
r = c.post("/api/host/open", json={"paths": []}, headers=H | {"Origin": "https://kotu-site.com"})
check("İkinci açılış: başka siteden reddedilir", r.status_code == 403)
A.HOST_OPEN = None

r, j = post("/api/convert/word-to-pdf", [T/"deneme.docx"])
check("word→pdf", r.status_code == 200 and "error" not in j["files"][0], j)
pdf_bytes = fetch(j["files"][0]); d = pymupdf.open(stream=pdf_bytes)
check("word→pdf içerik", "İğne ipliği" in d[0].get_text(), j["files"][0]["name"])

r, j = post("/api/convert/pdf-to-word", [T/"deneme.pdf"])
check("pdf→word standart", r.status_code == 200 and j["files"][0]["name"].endswith(".docx"), j)
r, j = post("/api/convert/pdf-to-word", [T/"deneme.pdf"], engine="word")
check("pdf→word word", r.status_code == 200 and "error" not in j["files"][0], j)

# test image
pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 300), 0); pix.set_rect(pix.irect, (30, 120, 200)); pix.save(T/"resim.png")
r, j = post("/api/convert/images-to-pdf", [T/"resim.png", T/"resim.png"], page_size="a4")
d = pymupdf.open(stream=fetch(j["files"][0]))
check("resim→pdf", d.page_count == 2, j)
# iPhone fotoğrafı (HEIC): deneme dosyası macOS'un sips aracıyla üretilir
import shutil as _shh, subprocess as _sp
if _shh.which("sips"):
    _sp.run(["sips", "-s", "format", "heic", str(T / "resim.png"), "--out", str(T / "foto.heic")], capture_output=True)
    r, j = post("/api/convert/images-to-pdf", [T / "foto.heic"], page_size="a4")
    hd = pymupdf.open(stream=fetch(j["files"][0])) if "error" not in j["files"][0] else None
    check("HEIC (iPhone fotoğrafı) → PDF", hd is not None and hd.page_count == 1 and len(hd[0].get_images()) == 1, j["files"][0])
    (T / "foto.heic").unlink(missing_ok=True)
else:
    print("(HEIC testi atlandı: sips yok)")
r, j = post("/api/convert/pdf-to-images", [T/"deneme.pdf"], format="jpg", dpi=100)
z = zipfile.ZipFile(io.BytesIO(fetch(j["files"][0])))
check("pdf→resim", len(z.namelist()) == 2, z.namelist())

r, j = post("/api/tool/merge", [T/"deneme.pdf", T/"deneme.pdf"])
check("birleştir", pymupdf.open(stream=fetch(j["files"][0])).page_count == 4, j)
merged = T/"birlesik.pdf"; merged.write_bytes(fetch(j["files"][0]))
r, j = post("/api/tool/split", [merged], mode="ranges", spec="1-2, 4")
check("böl aralık", [f["name"] for f in j["files"]] == ["birlesik_sayfa_1-2.pdf", "birlesik_sayfa_4.pdf"], j)
r, j = post("/api/tool/split", [merged], mode="each")
check("böl her sayfa", len(j["files"]) == 4)
each_ids = [f["id"] for f in j["files"]]
r, j = post("/api/tool/split", [merged], mode="extract", spec="9")
check("böl hata mesajı", r.status_code == 400 and "geçersiz" in j["error"], j)
zj = c.post("/api/out/zip", json={"ids": each_ids}, headers=H).get_json()
zz = zipfile.ZipFile(io.BytesIO(fetch(zj)))
check("zip çıktısı", zj["name"] == "PDF_Studyo.zip" and len(zz.namelist()) == 4, zz.namelist())
r, j = post("/api/tool/compress", [merged], level="yuksek")
check("sıkıştır", "after" in j["files"][0], j["files"][0])
r, j = post("/api/tool/protect", [merged], password="1234", allow_print="1")
enc = fetch(j["files"][0]); d = pymupdf.open(stream=enc)
check("şifrele", d.needs_pass and d.authenticate("1234"))
(T/"sifreli.pdf").write_bytes(enc)
r, j = post("/api/tool/unlock", [T/"sifreli.pdf"], password="yanlis")
check("şifre kaldır yanlış", "error" in j["files"][0], j)
r, j = post("/api/tool/unlock", [T/"sifreli.pdf"], password="1234")
check("şifre kaldır", not pymupdf.open(stream=fetch(j["files"][0])).needs_pass)
r, j = post("/api/tool/watermark", [merged], text="GİZLİ ŞİRKET", opacity=0.2)
wm = fetch(j["files"][0]); (T/"filigran.pdf").write_bytes(wm)
check("filigran", "GİZLİ ŞİRKET" in pymupdf.open(stream=wm)[0].get_text(), j)
r, j = post("/api/tool/numbers", [merged], format="sayfa n/t", position="alt-sag")
nm = fetch(j["files"][0]); (T/"numarali.pdf").write_bytes(nm)
check("sayfa no", "Sayfa 3 / 4" in pymupdf.open(stream=nm)[2].get_text(), j)
def span_of(pdf, page, needle):
    for b in pymupdf.open(stream=pdf)[page].get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            for sp in l["spans"]:
                if needle in sp["text"]:
                    return sp
check("sayfa no Times New Roman", span_of(nm, 2, "Sayfa 3 / 4")["font"].startswith("Times New Roman"), span_of(nm, 2, "Sayfa 3 / 4")["font"])
r, j = post("/api/tool/numbers", [merged], format="ek", ek_no=3, color="#c62828", bold="1", skip_first="1")
ek = fetch(j["files"][0]); sp = span_of(ek, 2, "Ek:3/2")
check("ek no (Ek:3/1, Ek:3/2 …)", sp is not None and "Ek:" not in pymupdf.open(stream=ek)[0].get_text()
      and "Ek:3/1" in pymupdf.open(stream=ek)[1].get_text() and j["files"][0]["name"].endswith("_ek3.pdf"), j)
check("ek no renk", sp and sp["color"] == 0xc62828, sp and hex(sp["color"]))
check("ek no kalın Times", sp and sp["font"].startswith("Times New Roman") and "Bold" in sp["font"], sp and sp["font"])
r, j = post("/api/tool/numbers", [merged, merged], format="ek", ek_artir="1", font="sans")
e1, e2 = fetch(j["files"][0]), fetch(j["files"][1])
check("çok dosya: Ek 1, Ek 2", "Ek:1/4" in pymupdf.open(stream=e1)[3].get_text() and "Ek:2/1" in pymupdf.open(stream=e2)[0].get_text()
      and span_of(e2, 0, "Ek:2/1")["font"].startswith("Arial"), j)
r, j = post("/api/tool/numbers", [merged], format="custom", template="EK-{n} Sayfa {t}/{toplam}", ek_no=2, start=5)
cu = fetch(j["files"][0])
check("özel biçim", "EK-2 Sayfa 6/8" in pymupdf.open(stream=cu)[1].get_text(), pymupdf.open(stream=cu)[1].get_text()[-40:])
r, j = post("/api/tool/numbers", [merged], format="custom", template="  ")
check("özel biçim boş", "error" in j["files"][0], j)

# --- editor
r = c.post("/api/edit/open", data={"files": [(open(merged, "rb"), "birlesik.pdf")]}, headers=H, content_type="multipart/form-data")
info = r.get_json(); sid = info["id"]
check("editör aç", len(info["pages"]) == 4, info["rev"])
def op(**kw):
    r = c.post(f"/api/edit/{sid}/op", json=kw, headers=H); return r.get_json()
info = op(op="rotate", pages=[0], angle=90); check("döndür", info["pages"][0]["rot"] == 90)
info = op(op="delete", pages=[3]); check("sil", len(info["pages"]) == 3)
info = op(op="reorder", order=[2, 0, 1]); check("sırala", info["pages"][1]["rot"] == 90)
info = op(op="duplicate", pages=[0]); check("çoğalt", len(info["pages"]) == 4)
info = op(op="blank", after=3); check("boş sayfa", len(info["pages"]) == 5)
r = c.post(f"/api/edit/{sid}/undo", headers=H).get_json(); check("geri al", len(r["pages"]) == 4 and r["canRedo"])
r = c.post(f"/api/edit/{sid}/redo", headers=H).get_json(); check("yinele", len(r["pages"]) == 5)
r = c.get(f"/api/edit/{sid}/page/1?w=400", headers=H); check("sayfa görüntüsü", r.status_code == 200 and r.mimetype == "image/png")
lines = c.get(f"/api/edit/{sid}/lines/0", headers=H).get_json()["lines"]
check("metin satırları", any("satır" in l["text"] for l in lines), lines[0])
# annotate on rotated page 1 and normal page 0
import base64
sig = "data:image/png;base64," + base64.b64encode((T/"resim.png").read_bytes()).decode()
info = op(op="annotate", page=2, items=[
    {"type": "text", "x": .1, "y": .1, "w": .5, "h": .05, "text": "Eklenen METİN şğı", "size": 14, "color": "#d00000"},
    {"type": "rect", "x": .6, "y": .6, "w": .2, "h": .1, "fill": "#ffffff"},
    {"type": "highlight", "x": .1, "y": .3, "w": .3, "h": .03},
    {"type": "image", "x": .5, "y": .8, "w": .2, "h": .1, "data": sig},
    {"type": "pen", "points": [[.1, .9], [.2, .95], [.3, .9]], "color": "#0000ff", "width": 2},
])
check("açıklama ekle (döndürülmüş sayfa)", "error" not in info, info.get("error"))
l0 = [l for l in lines if "satır" in l["text"]][0]
info = op(op="text_edit", page=0, edits=[dict(l0, text="DEĞİŞTİRİLDİ: yeni satır içeriği")])
check("metin düzenle", "error" not in info, info.get("error"))
info = op(op="replace_all", find="Lorem ipsum", replace="Yeni İçerik", match_case=True)
check("bul-değiştir", info.get("count", 0) > 10, info.get("count"))
info = op(op="annotate", page=0, items=[{"type": "redact", "x": 0, "y": 0, "w": 1, "h": .16}])
check("karart", "error" not in info, info.get("error"))
info = op(op="annotate", page=3, items=[
    {"type": "whiteout", "x": 0, "y": 0.2, "w": 1, "h": 0.1},
    {"type": "text", "x": .1, "y": .22, "w": .6, "h": .04, "text": "BEYAZ KUTU ÜSTÜ", "size": 12, "color": "#000000"}])
wtxt = pymupdf.open(stream=c.get(f"/api/edit/{sid}/download", headers=H).data)[3].get_text()
check("beyaz kutu altını siler, üstüne yazılır", "BEYAZ KUTU ÜSTÜ" in wtxt and "Hücre 2-2" not in wtxt, wtxt[:160].replace("\n", " | "))
r = c.get(f"/api/edit/{sid}/download", headers=H)
out = pymupdf.open(stream=r.data); (T/"duzenlenmis.pdf").write_bytes(r.data)
t0 = out[0].get_text(); t1 = out[2].get_text()
check("indirilen: çoğaltılan sayfa bağımsız", "DEĞİŞTİRİLDİ" not in out[1].get_text() and "Deneme Belgesi" in out[1].get_text())
check("indirilen: döndürülmüş sayfa", out[2].rotation == 90)
check("indirilen: boyut makul", len(r.data) < 400_000, len(r.data))
check("indirilen: düzenleme metni", "DEĞİŞTİRİLDİ" in t0, t0[:200].replace("\n", " | "))
check("indirilen: değiştir", "Yeni İçerik" in t0 and "Lorem ipsum" not in t0)
check("indirilen: eklenen metin", "Eklenen METİN şğı" in t1, t1[:120].replace("\n", " | "))
check("indirilen: karartma metni sildi", "Deneme Belgesi" not in t0)
# --- okuyucu: yoldan açma, şifre, arama, satır içi gösterim
r = c.post("/api/edit/open", json={"path": str(merged)}, headers=H); ri = r.get_json()
check("okuyucu: yoldan aç", r.status_code == 200 and ri["path"] == str(merged) and len(ri["pages"]) == 4, ri.get("error"))
r = c.post("/api/edit/open", json={"path": "/yok/boyle.pdf"}, headers=H)
check("okuyucu: olmayan dosya", r.status_code == 400 and "bulunamadı" in r.get_json()["error"])
r = c.post("/api/edit/open", json={"path": str(T / "sifreli.pdf")}, headers=H); rj = r.get_json()
check("okuyucu: şifre istenir", r.status_code == 400 and rj["needs_password"], rj)
r = c.post("/api/edit/open", json={"path": str(T / "sifreli.pdf"), "password": "yanlis"}, headers=H)
check("okuyucu: yanlış şifre", r.get_json()["error"] == "Şifre yanlış.")
r = c.post("/api/edit/open", json={"path": str(T / "sifreli.pdf"), "password": "1234"}, headers=H)
check("okuyucu: doğru şifre", r.status_code == 200 and len(r.get_json()["pages"]) == 4)
hits = c.get(f"/api/edit/{ri['id']}/search?q=İğne", headers=H).get_json()["hits"]
check("okuyucu: arama", [h["page"] for h in hits] == [0, 2] and all(0 <= v <= 1 for h in hits for b in h["rects"] for v in b), hits[:1])
r = c.get(f"/api/edit/{ri['id']}/download?inline=1", headers=H)
check("okuyucu: satır içi PDF", r.status_code == 200 and "attachment" not in r.headers.get("Content-Disposition", "") and r.data[:4] == b"%PDF")

# --- UYAP UDF
r, j = post("/api/convert/udf-to-pdf", [T/"deneme.udf"])
up = pymupdf.open(stream=fetch(j["files"][0]))
check("UDF→PDF", "İğne ipliği" in "".join(pg.get_text() for pg in up), j)
r, j = post("/api/convert/udf-to-word", [T/"deneme.udf"])
from docx import Document as _D
check("UDF→Word", j["files"][0]["name"].endswith(".docx") and "İğne" in "".join(pp.text for pp in _D(io.BytesIO(fetch(j["files"][0]))).paragraphs), j)
r, j = post("/api/convert/to-udf", [T/"deneme.docx"])
import udf as _udf
check("Word→UDF", "İğne ipliği" in _udf.plain_text(_udf.read(fetch(j["files"][0]))), j)
r, j = post("/api/convert/to-udf", [T/"deneme.pdf"])
check("PDF→UDF", "error" not in j["files"][0] and "satır" in _udf.plain_text(_udf.read(fetch(j["files"][0]))), j)
r, j = post("/api/convert/udf-to-pdf", [T/"deneme.docx"])
check("UDF olmayan dosya reddedilir", "error" in j["files"][0], j)
r = c.post("/api/edit/open", json={"path": str(T / "deneme.udf")}, headers=H); ui = r.get_json()
check("Okuyucu: UDF aç", r.status_code == 200 and ui["name"] == "deneme.udf" and len(ui["pages"]) >= 1, ui.get("error"))

# --- KVKK: kişisel verileri bulma ve karartma
kd = pymupdf.open(); kp = kd.new_page()
kp.insert_htmlbox(pymupdf.Rect(50, 50, 545, 700), "<p>Basvuru sahibi Ayse Demir (T.C. Kimlik No: 10000000146) iadenin "
    "TR33 0006 1005 1978 6457 8413 26 numarali IBAN hesabina odenmesini istemistir. Telefon 0532 123 45 67, e-posta "
    "ayse.demir@ornek.com.tr, kart 4111 1111 1111 1111. Dosya no 12345678901, birim telefonu (0312) 415 20 30. "
    "Firma vergi kimlik no 4540536920; dekont no 4540536921; abone no 1234567890; belge kodu ABC1234567890.</p>")
kd.set_metadata({"author": "Ayse Demir", "title": "Rapor"}); kd.save(T / "kvkk.pdf")
ks = c.post("/api/edit/open", json={"path": str(T / "kvkk.pdf")}, headers=H).get_json()
pd = c.post(f"/api/edit/{ks['id']}/personal-data", json={}, headers=H).get_json()
kinds = sorted({it["kind"] for it in pd["items"]})
check("KVKK: kişisel veriler doğrulanarak bulunur",
      pd["has_text"] and kinds == ["ad", "eposta", "iban", "kart", "tckn", "telefon", "vkn"]
      and sum(it["kind"] == "telefon" for it in pd["items"]) == 2 and not any("12345678901" in it["text"] for it in pd["items"])
      # Vergi kimlik no: son hanesi tutmayan alınmaz (abone no denetimden geçer: kullanıcı listeden çıkarır);
      # harfe bitişik kodun içindeki aynı rakamlar karartılacak yerlere girmez
      and [(it["text"], len(it["rects"])) for it in pd["items"] if it["kind"] == "vkn"] == [("4540536920", 1), ("1234567890", 1)],
      [(it["kind"], it["text"]) for it in pd["items"]])
r = c.post(f"/api/edit/{ks['id']}/op", json={"op": "redact_areas", "clean_meta": True,
           "areas": [{"page": it["page"], "rects": it["rects"]} for it in pd["items"]]}, headers=H).get_json()
kout = pymupdf.open(stream=c.get(f"/api/edit/{ks['id']}/download", headers=H).data)
kt = kout[0].get_text().replace("\n", " ")
check("KVKK: karartılan yazı belgeden silinir, gerisi kalır, belge bilgileri temizlenir",
      "error" not in r and not any(v in kt for v in ("10000000146", "ayse.demir@", "4111", "0532", "Ayse Demir", "4540536920"))
      and all(w in kt for w in ("12345678901", "Basvuru sahibi", "numarali IBAN hesabina odenmesini", "birim telefonu",
                                "4540536921", "ABC1234567890"))
      and not kout.metadata.get("author"), (r.get("error"), kt[:200]))
nd = pymupdf.open(); nd.new_page().insert_htmlbox(pymupdf.Rect(50, 50, 545, 700),
    "<p>DAVACI : MEHMET ALİ YILMAZ<br>VEKİLİ : Av. Zehra Kılıçarslan<br>DAVALI : ABC ELEKTRONİK TİCARET A.Ş.<br>"
    "Adı Soyadı: Rüzgar Tanyeri</p><p>Deniz Kuvvetleri Komutanlığı, Mustafa Kemal Bulvarı ve Ankara Barosu yazıları "
    "geldi. Ali Bey ile Ali Can görüştü; Vali Cantürk ve Halil kalite raporunu imzaladı. Ali yarın gelecek.</p>"
    "<p>Sayın Kılıçarslan, YILMAZ ve Tanyeri'nin beyanları alındı; can sıkıntısı yoktu. Tebligat Tanyeri Sokak "
    "adresine yapıldı.</p>")
nd.save(T / "adlar.pdf")
ns = c.post("/api/edit/open", json={"path": str(T / "adlar.pdf")}, headers=H).get_json()
pd = c.post(f"/api/edit/{ns['id']}/personal-data", json={"terms": ["Ali"]}, headers=H).get_json()
names = {it["text"] for it in pd["items"] if it["kind"] == "ad"}
ali = [it for it in pd["items"] if it["kind"] == "ozel"]
check("KVKK: ad soyadlar bulunur; kurum, yer ve sokak adları alınmaz",
      names == {"MEHMET ALİ YILMAZ", "Zehra Kılıçarslan", "Rüzgar Tanyeri", "Ali Can"}, names)
alone = sorted(it["text"] for it in pd["items"] if it["kind"] == "soyad")
check("KVKK: bulunan kişilerin tek geçen soyadları da listelenir (küçük harfli \"can\", \"Tanyeri Sokak\" değil)",
      alone == ["Kılıçarslan", "Tanyeri", "YILMAZ"] and all(len(it["rects"]) == 1 for it in pd["items"] if it["kind"] == "soyad"),
      alone)
check("KVKK: aranan kelime başka kelimelerin içinden (Vali, Halil, kalite) karartılmaz",
      len(ali) == 1 and len(ali[0]["rects"]) == 2, ali)
# satırında tek başına duran ad (imza, tablo hücresi) alttaki satırın ilk kelimesini soyad sanmaz;
# satır ortasında başlayıp alt satıra kayan ad bütün kalır
sd = pymupdf.open(); sd.new_page().insert_htmlbox(pymupdf.Rect(50, 50, 545, 700),
    "<p>Saygılarımla,<br>Ayşe Yılmaz<br>Veri sorumlusuna başvurulmuştur.</p><p>Veri envanteri ektedir.</p>"
    "<p>Bu dava davacı Mehmet Ali<br>Yılmaz tarafından açıldı.</p><p>Başvuru sahibi<br>Adı Soyadı<br>Zeynep Aksoy</p>"
    "<p style=\"text-align:justify\">Kurula yapılan başvuruda başvuru sahibi olarak eşi Murat Gündoğdu adına işlem yapılmıştır. "
    "Ayrıca Murat Gündoğdu ile görüşülmüş ve tutanak düzenlenmiştir; bu tutanak dosyaya eklenmiştir.</p>")
sd.save(T / "adlar2.pdf")
ss = c.post("/api/edit/open", json={"path": str(T / "adlar2.pdf")}, headers=H).get_json()
spd = c.post(f"/api/edit/{ss['id']}/personal-data", json={}, headers=H).get_json()
sfound = sorted(" ".join(it["text"].split()) for it in spd["items"] if it["kind"] in ("ad", "soyad"))
check("KVKK: satırında tek duran ad alt satıra taşmaz (\"Veri\" soyad sayılmaz); satır ortasındaki ad alt satıra kayabilir",
      [v for v in sfound if "Yılmaz" in v] == ["Ayşe Yılmaz", "Mehmet Ali Yılmaz"] and not any("Veri" in v for v in sfound), sfound)
check("KVKK: \"Başvuru sahibi\" altındaki \"Adı Soyadı\" başlığı ad sayılmaz, altındaki ad bulunur",
      "Zeynep Aksoy" in sfound and not any("Adı" in v or "Soyadı" in v for v in sfound), sfound)
splaces = {" ".join(it["text"].split()): (it["places"], len(it["rects"])) for it in spd["items"]}
check("KVKK penceresi: \"N yerde\" geçiş sayısıdır (satırda bölünen ad bir yer; iki yana yaslı yazıda kutu sayısı değil)",
      splaces.get("Mehmet Ali Yılmaz") == (1, 2) and splaces.get("Murat Gündoğdu", (0,))[0] == 2, splaces)
c.post(f"/api/edit/{ss['id']}/close", headers=H); (T / "adlar2.pdf").unlink()
c.post(f"/api/edit/{ns['id']}/op", json={"op": "redact_areas",
       "areas": [{"page": it["page"], "rects": it["rects"]} for it in pd["items"]]}, headers=H)
nt = pymupdf.open(stream=c.get(f"/api/edit/{ns['id']}/download", headers=H).data)[0].get_text().replace("\n", " ")
check("KVKK: ad soyad karartması yalnızca kişileri siler",
      not any(v in nt for v in ("YILMAZ", "Kılıçarslan", "Rüzgar", "Tanyeri'", "Ali Can", "Ali Bey", "Ali yarın"))
      and "can sıkıntısı" in nt and "Tanyeri Sokak" in nt
      and all(v in nt for v in ("Vali Cantürk", "Halil kalite", "Deniz Kuvvetleri", "Mustafa Kemal Bulvarı",
                                "Ankara Barosu", "ABC ELEKTRONİK")), nt)
# Sağ tık › Karart: elle seçilen metnin kutusu (satır yüksekliğinden taşan) komşu satırlara dokunmaz
sd = pymupdf.open(); sp = sd.new_page()
for k, line in enumerate(["Birinci satir burada duruyor", "Gizli Kelime ortada yaziyor", "Ucuncu satir da burada"]):
    sp.insert_text((72, 100 + k * 11), line, fontsize=11)
sd.save(T / "secim.pdf")
ss = c.post("/api/edit/open", json={"path": str(T / "secim.pdf")}, headers=H).get_json()
gw = [w for w in sp.get_text("words") if w[4] in ("Gizli", "Kelime")]
x0, y0, x1, y1 = gw[0][0], min(w[1] for w in gw), gw[-1][2], max(w[3] for w in gw)
W, Hh = sp.rect.width, sp.rect.height
box = [x0 / W, (y0 - 3) / Hh, (x1 - x0) / W, (y1 - y0 + 6) / Hh]   # seçim kutusu üst ve alt satıra taşıyor
r = c.post(f"/api/edit/{ss['id']}/op", json={"op": "redact_areas", "fit": True, "areas": [{"page": 0, "rects": [box]}]},
           headers=H).get_json()
st = pymupdf.open(stream=c.get(f"/api/edit/{ss['id']}/download", headers=H).data)[0].get_text()
check("Sağ tık › Karart: seçilen metin silinir, üst ve alt satırlar kalır",
      "error" not in r and "Gizli" not in st and "Kelime" not in st and "ortada" in st
      and "Birinci satir burada duruyor" in st and "Ucuncu satir da burada" in st, st)
(T / "secim.pdf").unlink()

# Karartmadan sonra Kaydet özgün dosyayı korumayı önerir (arayüz "redacted" bilgisine bakar)
rs = c.post("/api/edit/open", json={"path": str(T / "kvkk.pdf")}, headers=H).get_json()
r1 = c.post(f"/api/edit/{rs['id']}/op", json={"op": "pages_edit", "pages": [{"page": 0, "edits": [],
            "items": [{"type": "redact", "x": .1, "y": .05, "w": .2, "h": .03}]}]}, headers=H).get_json()
r2 = c.post(f"/api/edit/{rs['id']}/op", json={"op": "rotate", "pages": [0], "angle": 90}, headers=H).get_json()
r3 = c.post(f"/api/edit/{rs['id']}/undo", headers=H).get_json(); c.post(f"/api/edit/{rs['id']}/undo", headers=H)
r4 = c.get(f"/api/edit/{rs['id']}", headers=H).get_json()
c.post(f"/api/edit/{rs['id']}/redo", headers=H)
r5 = c.post(f"/api/edit/{rs['id']}/save", json={"path": str(T / "kvkk_KVKK.pdf")}, headers=H).get_json()
check("Kaydet: karartılmış sürüm bilinir; geri alınınca ya da ayrı kaydedilince uyarı kalkar",
      r1["redacted"] and r2["redacted"] and r3["redacted"] and not r4["redacted"] and not r5["redacted"]
      and r5["path"].endswith("kvkk_KVKK.pdf"), [r.get("redacted") for r in (r1, r2, r3, r4, r5)])
(T / "kvkk_KVKK.pdf").unlink()
blank = pymupdf.open(); blank.new_page(); blank.save(T / "bos.pdf")
bs = c.post("/api/edit/open", json={"path": str(T / "bos.pdf")}, headers=H).get_json()
check("KVKK: metni olmayan belge bildirilir",
      c.post(f"/api/edit/{bs['id']}/personal-data", json={}, headers=H).get_json() == {"has_text": False, "items": [], "scanned": []})
(T / "kvkk.pdf").unlink(); (T / "adlar.pdf").unlink(); (T / "bos.pdf").unlink()

# --- form doldurma
fd_ = pymupdf.open(); fp_ = fd_.new_page()
def _widget(kind, name, rect, **kw):
    w = pymupdf.Widget(); w.field_type = kind; w.field_name = name; w.rect = pymupdf.Rect(rect)
    for k, v in kw.items(): setattr(w, k, v)
    fp_.add_widget(w)
_widget(pymupdf.PDF_WIDGET_TYPE_TEXT, "ad", (100, 100, 300, 120))
_widget(pymupdf.PDF_WIDGET_TYPE_TEXT, "aciklama", (100, 130, 400, 200), field_flags=pymupdf.PDF_TX_FIELD_IS_MULTILINE)
_widget(pymupdf.PDF_WIDGET_TYPE_CHECKBOX, "onay", (100, 210, 114, 224), field_value=False)
_widget(pymupdf.PDF_WIDGET_TYPE_COMBOBOX, "il", (100, 240, 250, 260), choice_values=["Ankara", "İstanbul", "İzmir"], field_value="Ankara")
_widget(pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON, "secim", (100, 270, 112, 282), field_value=False)
_widget(pymupdf.PDF_WIDGET_TYPE_RADIOBUTTON, "secim", (150, 270, 162, 282), field_value=False)
_widget(pymupdf.PDF_WIDGET_TYPE_TEXT, "dosya_no", (100, 300, 300, 320), field_value="2026/1", field_flags=pymupdf.PDF_FIELD_IS_READ_ONLY)
fd_.save(T / "form.pdf")
fs_ = c.post("/api/edit/open", json={"path": str(T / "form.pdf")}, headers=H).get_json()
ff = c.get(f"/api/edit/{fs_['id']}/fields", headers=H).get_json()["fields"]
fby = {f["name"]: f for f in ff}
fr = [f for f in ff if f["name"] == "secim"]
check("Form: doldurulabilir alanlar listelenir (tür, değer, seçenekler, salt okunur)",
      fs_["form"] is True and [f["type"] for f in ff] == ["text", "text", "check", "choice", "radio", "radio", "text"]
      and fby["aciklama"]["multiline"] and fby["il"]["value"] == "Ankara" and fby["il"]["options"][1] == ["İstanbul", "İstanbul"]
      and fby["dosya_no"]["readonly"] and not fby["onay"]["checked"], [(f["name"], f["type"]) for f in ff])
fill = lambda fields: c.post(f"/api/edit/{fs_['id']}/op", json={"op": "fill_form", "fields": fields}, headers=H).get_json()
v = lambda name, value, k=0: {"page": 0, "xref": [f for f in ff if f["name"] == name][k]["xref"], "value": value}
f1 = fill([v("ad", "Ayşe Yılmaz Çağrı"), v("aciklama", "Şikâyet\nikinci satır"), v("onay", True), v("il", "İzmir"),
           v("secim", True, 1), v("dosya_no", "değişmemeli")])
f2 = fill([v("secim", True, 0)])
fdoc = pymupdf.open(stream=c.get(f"/api/edit/{fs_['id']}/download", headers=H).data); fpage = fdoc[0]
vals = [(w.field_name, w.field_value) for w in fpage.widgets()]
def _baseline(name):   # tek satırlı alanda yazının taban çizgisi kutunun içinde mi (MuPDF hatası düzeltildi mi)
    import re as _re
    w = next(w for w in fpage.widgets() if w.field_name == name)
    n = int(_re.findall(r"(\d+) 0 R", fdoc.xref_get_key(w.xref, "AP/N")[1])[0])
    y = float(_re.findall(r"1 0 0 -1 [-\d.]+ ([-\d.]+) Tm", fdoc.xref_stream(n).decode("latin-1"))[0])
    return 0 < y < w.rect.height
check("Form: metin (Türkçe, çok satır), onay kutusu, liste ve seçenek grubu doldurulur; salt okunur alan değişmez",
      "error" not in f1 and f1["unsaved"] and f1["pages"][0]["k"] != fs_["pages"][0]["k"]
      and vals == [("ad", "Ayşe Yılmaz Çağrı"), ("aciklama", "Şikâyet\nikinci satır"), ("onay", "Yes"), ("il", "İzmir"),
                   ("secim", "Yes"), ("secim", "Off"), ("dosya_no", "2026/1")]
      and _baseline("ad") and _baseline("il"), (f1.get("error"), vals))
fill([v("ad", ""), v("il", "")])
cleared = {f["name"]: f.get("value") for f in c.get(f"/api/edit/{fs_['id']}/fields", headers=H).get_json()["fields"]}
check("Form: alan boşaltılabilir (Formu temizle)", cleared["ad"] == "" and cleared["il"] == "", cleared)
(T / "form.pdf").unlink()

# --- Excel → PDF (Microsoft Excel ya da LibreOffice gerekir)
import converters as _cv
if _cv.excel_installed() or _cv.soffice_path():
    from openpyxl import Workbook as _Wb
    xb = _Wb(); xs1 = xb.active; xs1.title = "Hesap"
    xs1.append(["Kalem", "Tutar"]); xs1.append(["Şikâyet konusu cihaz", 12500])
    xs2 = xb.create_sheet("Ödeme planı"); xs2.append(["Tarih", "Tutar"]); xs2.append(["15.03.2026", 1500])
    xb.save(T / "hesap.xlsx")
    r, j = post("/api/convert/excel-to-pdf", [T / "hesap.xlsx"])
    xpdf = pymupdf.open(stream=fetch(j["files"][0])) if "error" not in j["files"][0] else None
    xtext = "".join(pg.get_text() for pg in xpdf) if xpdf else ""
    check("Excel → PDF: bütün çalışma sayfaları, Türkçe harfler", xpdf and xpdf.page_count == 2 and "Şikâyet" in xtext
          and "15.03.2026" in xtext and j["files"][0]["name"] == "hesap.pdf", j)
    r, j = post("/api/tool/merge", [T / "deneme.pdf", T / "hesap.xlsx"], name="excelli")
    mx = pymupdf.open(stream=fetch(j["files"][0])) if "error" not in j["files"][0] else None
    check("Birleştir: Excel dosyası da PDF olarak eklenir", mx and mx.page_count == 4
          and [t[1] for t in mx.get_toc()] == ["deneme", "hesap"], j)
    (T / "hesap.xlsx").unlink()
else:
    print("(Excel → PDF testi atlandı: Microsoft Excel ya da LibreOffice yok)")

# --- PDF → Excel
from openpyxl import load_workbook as _wb
xd = pymupdf.open(); xp = xd.new_page()
xp.insert_htmlbox(pymupdf.Rect(50, 50, 545, 300), "<table><tr><th>Gider kalemi</th><th>Tutar TL</th></tr><tr><td>Ürün bedeli</td>"
    "<td>12.500,00</td></tr><tr><td>Servis</td><td>850,00</td></tr></table>",
    css="td, th { border: 1px solid black; padding: 3px; } th { background-color: #e0e0e0; }")   # renkli başlık ayrı tablo sayılmaz
for k, row in enumerate([("Tarih", "Borc", "Alacak"), ("01.02.2026", "0,00", "2.000,00"), ("15.03.2026", "1.500,00", "0,00")]):
    for x, t in zip((60, 200, 330), row):
        xp.insert_text((x, 360 + k * 16), t, fontsize=10)
xp.insert_text((60, 420), "Dosya 2026 yili, T.C. 10000000146", fontsize=10)
xp.insert_text((60, 440), '=HYPERLINK("http://ornek.test","tikla")', fontsize=10)
xd.save(T / "tablo.pdf")
r, j = post("/api/convert/pdf-to-excel", [T / "tablo.pdf"])
xs = _wb(io.BytesIO(fetch(j["files"][0]))).active
rows = [list(r_) for r_ in xs.iter_rows(values_only=True)]
check("PDF → Excel: çizgili ve çizgisiz tablolar; tutar sayı, tarih tarih olur",
      j["files"][0]["name"] == "tablo.xlsx" and j["files"][0]["note"] == "2 tablo" and rows[0][:2] == ["Gider kalemi", "Tutar TL"]
      and rows[1][:2] == ["Ürün bedeli", 12500] and xs.cell(2, 2).number_format == "#,##0.00"
      and rows[4][:3] == ["Tarih", "Borc", "Alacak"] and rows[5][0].year == 2026 and rows[5][2] == 2000
      and not any("10000000146" in str(v) for r_ in rows for v in r_), rows)
r, j = post("/api/convert/pdf-to-excel", [T / "tablo.pdf"], content="all", layout="single")
xa = _wb(io.BytesIO(fetch(j["files"][0])))
alltext = [v for r_ in xa.active.iter_rows(values_only=True) for v in r_ if v is not None]
nt = pymupdf.open(); nt.new_page().insert_text((72, 100), "Bu belgede tablo yok, yalnizca duz bir satir var.", fontsize=11)
nt.save(T / "tablosuz.pdf")
r2, j2 = post("/api/convert/pdf-to-excel", [T / "tablosuz.pdf"])
check("PDF → Excel: bütün sayfa tek çalışma sayfasında; tablo yoksa uyarı",
      xa.sheetnames == ["Tablolar"] and "Sayfa 1" in alltext and "Dosya 2026 yili, T.C. 10000000146" in alltext
      and "tablo bulunamadı" in j2["files"][0].get("error", ""), (xa.sheetnames, alltext[-3:], j2))
_eq = [(c_.value, c_.data_type) for r_ in xa.active.iter_rows() for c_ in r_ if str(c_.value).startswith("=")]
check("PDF → Excel: PDF'te \"=\" ile başlayan yazı formül olmaz, yazı kalır",
      _eq == [('=HYPERLINK("http://ornek.test","tikla")', "s")], _eq)
(T / "tablo.pdf").unlink(); (T / "tablosuz.pdf").unlink()

# --- işaretin rengini ve türünü değiştirme (tıklayınca açılan çubuk)
md_ = pymupdf.open(); mp_ = md_.new_page()
mp_.insert_text((72, 100), "Davaci telefonun ayipli oldugunu ileri surmustur.", fontsize=12)
mp_.insert_text((72, 116), "Ikinci satir burada devam ediyor.", fontsize=12)
md_.save(T / "isaret.pdf")
ms_ = c.post("/api/edit/open", json={"path": str(T / "isaret.pdf")}, headers=H).get_json()
b1, b2 = mp_.search_for("telefonun ayipli")[0], mp_.search_for("Ikinci satir")[0]
fr = lambda r: [r.x0 / 595, r.y0 / 842, r.width / 595, r.height / 842]
c.post(f"/api/edit/{ms_['id']}/op", json={"op": "highlight", "page": 0, "rects": [fr(b1), fr(b2)], "color": "#ffe14d",
       "note": "Onemli"}, headers=H)
an = lambda: c.get(f"/api/edit/{ms_['id']}/annotations", headers=H).get_json()["annots"][0]
a0 = an()
c.post(f"/api/edit/{ms_['id']}/op", json={"op": "annot_style", "page": 0, "xref": a0["xref"], "color": "#8ef0a0"}, headers=H)
a1 = an()
c.post(f"/api/edit/{ms_['id']}/op", json={"op": "annot_style", "page": 0, "xref": a1["xref"], "kind": "underline"}, headers=H)
a2 = an()
und = c.post(f"/api/edit/{ms_['id']}/undo", headers=H).get_json()
a3 = an()
check("İşaret: satır kutuları; rengi ve türü değişir, not ve alıntı korunur, Geri Al eski hâline döndürür",
      len(a0["rects"]) == 2 and a1["color"] == "#8ef0a0" and a1["type"] == "Highlight"
      and a2["type"] == "Underline" and a2["content"] == "Onemli" and a2["quote"] == a0["quote"] and a2["color"].startswith("#d64")
      and len(a2["rects"]) == 2 and und["canRedo"] and a3["type"] == "Highlight" and a3["color"] == "#8ef0a0",
      (a0.get("rects"), a1["color"], a2["type"], a2["color"], a3["type"]))
(T / "isaret.pdf").unlink()

# --- iki sürümü karşılaştırma
def _surum(path, lines):
    d = pymupdf.open(); pg = d.new_page()
    for k, line in enumerate(lines):
        pg.insert_text((72, 90 + k * 16), line, fontsize=11)
    d.save(path)
_surum(T / "eski.pdf", ["Davaci 12.03.2026 tarihinde telefon satin almistir.", "Cihaz ayiplidir.", "Tanik Ahmet dinlenmistir.",
                        "Hukum fikrasi asagidadir."])
_surum(T / "yeni.pdf", ["Davaci 15.03.2026 tarihinde telefon satin almistir.", "Cihaz ayiplidir.", "Hukum fikrasi asagidadir.",
                        "Yargilama giderleri davaliya yukletilmistir."])
r, j = post("/api/tool/compare", [T / "eski.pdf", T / "yeni.pdf"])
cmp_ = pymupdf.open(stream=fetch(j["files"][0]))
first = cmp_[0].get_text()
check("Karşılaştır: eskiden silinen ve yenide eklenen yerler listelenir, sayfalar yan yana",
      j["files"][0]["note"] == "3 değişiklik: 5 kelime eklendi, 4 kelime silindi" and cmp_.page_count == 2
      and "12.03.2026" in first and "15.03.2026" in first and "Tanik Ahmet dinlenmistir." in first
      and cmp_[1].rect.width > 2 * 595 and [t[1] for t in cmp_.get_toc()] == ["Değişiklik listesi", "Sayfa 1"], (j, first[:300]))
es_ = c.post("/api/edit/open", json={"path": str(T / "yeni.pdf")}, headers=H).get_json()
r = c.post(f"/api/edit/{es_['id']}/tool/compare", data={"files": [(open(T / "eski.pdf", "rb"), "eski.pdf")], "doc_pos": "1"},
           headers=H, content_type="multipart/form-data").get_json()
r1 = post("/api/tool/compare", [T / "eski.pdf"])[1]
check("Karşılaştır: açık belgeyle (sıra: eski dosya, açık belge yeni) ve tek dosyada uyarı",
      r["files"][0]["note"].startswith("3 değişiklik") and "error" in r1, (r, r1))
(T / "eski.pdf").unlink(); (T / "yeni.pdf").unlink()

# --- notlar ve vurgular raporu (Word / PDF)
rd_ = pymupdf.open(); rp_ = rd_.new_page()
rp_.insert_text((72, 100), "Davaci telefonun ayipli oldugunu ileri surmustur.", fontsize=12)
rp_.insert_text((72, 200), "Bilirkisi raporu dosyaya sunulmustur.", fontsize=12)
rd_.new_page().insert_text((72, 100), "Ikinci sayfa metni.", fontsize=12)
rd_.save(T / "notlu_rapor.pdf")
rd_ = pymupdf.open(T / "notlu_rapor.pdf"); rp_ = rd_[0]   # sayfa eklenince eski sayfa nesnesi geçersiz olur
rs_ = c.post("/api/edit/open", json={"path": str(T / "notlu_rapor.pdf")}, headers=H).get_json()
empty = c.post(f"/api/edit/{rs_['id']}/annot-report", json={}, headers=H)
def _box(text):
    r = rp_.search_for(text)[0]
    return [r.x0 / rp_.rect.width, r.y0 / rp_.rect.height, r.width / rp_.rect.width, r.height / rp_.rect.height]
c.post(f"/api/edit/{rs_['id']}/op", json={"op": "highlight", "page": 0, "rects": [_box("telefonun ayipli")],
       "color": "#ffe14d", "note": "Ayip ihbari tarihi"}, headers=H)
c.post(f"/api/edit/{rs_['id']}/op", json={"op": "highlight", "kind": "underline", "page": 0, "rects": [_box("Bilirkisi raporu")],
       "color": "#d6453d"}, headers=H)
c.post(f"/api/edit/{rs_['id']}/op", json={"op": "note", "page": 1, "x": .5, "y": .5, "text": "Ikinci sayfaya not"}, headers=H)
r1 = c.post(f"/api/edit/{rs_['id']}/annot-report", json={"format": "docx"}, headers=H).get_json()
import zipfile as _zf
raw = fetch(r1)
paras = [pp.text for pp in _D(io.BytesIO(raw)).paragraphs]
body = "\n".join(paras)
check("Notlar raporu (Word): sayfa sırasıyla alıntılar, notlar ve renkli vurgu",
      r1["name"] == "notlu_rapor_notlar.docx" and r1["count"] == 3 and "“telefonun ayipli”" in body
      and "Not: Ayip ihbari tarihi" in body and "“Bilirkisi raporu”" in body and "Ikinci sayfaya not" in body
      and body.index("Sayfa 1") < body.index("telefonun") < body.index("Sayfa 2") < body.index("Ikinci sayfaya")
      and 'w:fill="ffe14d"' in _zf.ZipFile(io.BytesIO(raw)).read("word/document.xml").decode()
      and empty.status_code == 400, (r1.get("error"), paras[:8]))
r2 = c.post(f"/api/edit/{rs_['id']}/annot-report", json={"format": "pdf", "by": "color"}, headers=H).get_json()
pt = pymupdf.open(stream=fetch(r2))[0].get_text()
r3 = c.post(f"/api/edit/{rs_['id']}/annot-report", json={"notes": False}, headers=H).get_json()
check("Notlar raporu (PDF): renge göre gruplar, Türkçe harfler; yalnızca işaretler seçilebilir",
      r2["name"].endswith(".pdf") and "Sarı" in pt and "Kırmızı" in pt and "s. 2 · Not" in pt and "Altı çizili" in pt
      and r3["count"] == 2, (pt[:200], r3.get("count")))
# taranmış sayfadaki işaretin görüntüsü sayfa sonuna sığmazsa küçülmez, sonraki sayfaya geçer
import notlar as _nl
_px = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 600, 160), 0); _px.set_rect(_px.irect, (200, 220, 240))
_its = [{"page": k // 6, "kind": "Highlight", "label": "Vurgu", "color": "#ffd500", "color_name": "Sarı",
         "quote": "" if k % 5 == 2 else "Kişisel verilerin işlenmesinde özel hayatın gizliliği korunur. " * (1 + k % 4),
         "note": "Not metni" if k % 2 else "", "image": (_px.tobytes("png"), 430, 115) if k % 5 == 2 else None} for k in range(70)]
_nl.to_pdf(_its, "Deneme.pdf", 12, T / "taranmis_notlar.pdf", A.DATA)
_iw = [round(pymupdf.Rect(i["bbox"]).width) for pg in pymupdf.open(T / "taranmis_notlar.pdf") for i in pg.get_image_info()]
check("Notlar raporu (PDF): taranmış sayfa görüntüleri sayfa sonunda küçülmez", _iw == [430] * 14, _iw)
(T / "taranmis_notlar.pdf").unlink()
(T / "notlu_rapor.pdf").unlink()

# --- okuyucu: altını çiz / üstünü çiz (PDF'in standart metin işaretleri)
ui2 = c.post("/api/edit/open", json={"path": str(T / "deneme.pdf")}, headers=H).get_json()
def mop(**kw): return c.post(f"/api/edit/{ui2['id']}/op", json=kw, headers=H).get_json()
r1 = c.get(f"/api/edit/{ui2['id']}/search?q=İğne", headers=H).get_json()["hits"][0]["rects"][0]
r2 = c.get(f"/api/edit/{ui2['id']}/search?q=ılık", headers=H).get_json()["hits"][0]["rects"][0]
mop(op="highlight", kind="underline", page=0, rects=[r1], color="#d6453d")
mop(op="highlight", kind="strikeout", page=0, rects=[r2], color="#d6453d")
marks = c.get(f"/api/edit/{ui2['id']}/annotations", headers=H).get_json()["annots"]
check("Altını çiz / üstünü çiz eklendi, alıntıları okunuyor",
      sorted((a["type"], a["quote"]) for a in marks) == [("StrikeOut", "ılık"), ("Underline", "İğne")], marks)

# --- okuyucu: vurgu, not, yer imi, özgün dosyaya kaydetme
import shutil as _sh, time as _t
_sh.copy(T / "deneme.pdf", T / "notlu.pdf")
r = c.post("/api/edit/open", json={"path": str(T / "notlu.pdf")}, headers=H); ni = r.get_json(); nid = ni["id"]
check("Okuyucu: özgün dosyaya kaydedilebilir", ni["can_save_source"] is True)
def nop(**kw): return c.post(f"/api/edit/{nid}/op", json=kw, headers=H).get_json()
hl = c.get(f"/api/edit/{nid}/search?q=İğne", headers=H).get_json()["hits"][0]["rects"][0]
nop(op="highlight", page=0, rects=[hl], color="#8ef0a0", note="önemli kısım")
nop(op="note", page=0, x=0.8, y=0.1, text="Duruşmada sor")
nop(op="bookmark_add", page=1, title="İkinci sayfa")
an = c.get(f"/api/edit/{nid}/annotations", headers=H).get_json()
types = sorted(a["type"] for a in an["annots"])
check("Vurgu ve not eklendi", types == ["Highlight", "Text"], types)
check("Vurgulanan metin okunuyor", any("İğne" in a["quote"] for a in an["annots"]), an["annots"])
check("Yer imi eklendi", [{k: o[k] for k in ("level", "title", "page")} for o in an["outline"]] == [{"level": 1, "title": "İkinci sayfa", "page": 1}], an["outline"])
note = [a for a in an["annots"] if a["type"] == "Text"][0]
nop(op="annot_edit", page=0, xref=note["xref"], text="Duruşmada mutlaka sor")
an = c.get(f"/api/edit/{nid}/annotations", headers=H).get_json()
check("Not düzenlendi", any(a["content"] == "Duruşmada mutlaka sor" for a in an["annots"]))
check("Kaydedilmemiş değişiklik var", c.get(f"/api/edit/{nid}", headers=H).get_json()["unsaved"] is True)
r = c.post(f"/api/edit/{nid}/save", json={}, headers=H); sv = r.get_json()
saved = pymupdf.open(T / "notlu.pdf")
check("Kaydet: açılan dosyanın üzerine (+ yedek)", r.status_code == 200 and Path(sv["backup"]).exists() and sv["unsaved"] is False
      and len(list(saved[0].annots())) == 2 and saved.get_toc() == [[1, "İkinci sayfa", 2]], sv)
saved.close()
nop(op="bookmark_delete", index=0)
nop(op="annot_delete", page=0, xref=note["xref"])
an = c.get(f"/api/edit/{nid}/annotations", headers=H).get_json()
check("Not ve yer imi silindi", len(an["annots"]) == 1 and an["outline"] == [], an)
_t.sleep(1.1); (T / "notlu.pdf").touch()
r = c.post(f"/api/edit/{nid}/save", json={}, headers=H)
check("Dışarıda değişen dosyanın üzerine sormadan yazılmaz", r.status_code == 409 and r.get_json()["conflict"] == "modified")
# Farklı Kaydet: seçilen yere yazar; sonraki "Kaydet" o dosyaya yazar
r = c.post(f"/api/edit/{nid}/save", json={"path": str(T / "farkli")}, headers=H); fa = r.get_json()
check("Farklı Kaydet", r.status_code == 200 and fa["name"] == "farkli.pdf" and fa["path"] == str(T / "farkli.pdf")
      and (T / "farkli.pdf").exists() and fa["can_save_source"] and not fa["unsaved"], fa)
nop(op="note", page=1, x=0.5, y=0.5, text="ikinci not")
r = c.post(f"/api/edit/{nid}/save", json={}, headers=H)
check("Farklı Kaydet sonrası Kaydet yeni dosyaya yazar", r.status_code == 200
      and len(list(pymupdf.open(T / "farkli.pdf")[1].annots())) == 1 and len(list(pymupdf.open(T / "notlu.pdf")[1].annots())) == 0)
r = c.post(f"/api/edit/{nid}/save", json={"path": "/olmayan/klasor/x.pdf"}, headers=H)
check("Olmayan klasöre kaydedilmez", r.status_code == 400, r.get_json())
r = c.post(f"/api/edit/{nid}/save", json={"path": str(T / "x.pdf")}, headers=H | {"Origin": "https://kotu-site.com"})
check("Başka siteden gelen istek reddedilir", r.status_code == 403 and not (T / "x.pdf").exists())
r = c.post(f"/api/edit/{nid}/mark-saved", json={}, headers=H | {"Origin": f"http://127.0.0.1:{A.PORT}"})
check("Uygulamanın kendi isteği kabul edilir", r.status_code == 200)
(T / "farkli.pdf").unlink()
r = c.post("/api/edit/open", json={"path": str(T / "deneme.udf")}, headers=H)
check("UDF özgün dosyaya kaydedilmez", r.get_json()["can_save_source"] is False)
for b in A.yedekler.BACKUPS.glob("notlu_*"): b.unlink()
for b in A.yedekler.BACKUPS.glob("farkli_*"): b.unlink()
(T / "notlu.pdf").unlink()

# --- sol menüdeki araçlar açık belgeye uygulanır
r = c.post("/api/edit/open", json={"path": str(merged)}, headers=H); di = r.get_json(); did = di["id"]
def dtool(name, files=(), **form):
    data = {k: str(v) for k, v in form.items()}
    data["files"] = [(open(f, "rb"), Path(f).name) for f in files]
    r = c.post(f"/api/edit/{did}/tool/{name}", data=data, headers=H, content_type="multipart/form-data")
    return r.get_json()
def dtext(i):
    return pymupdf.open(stream=c.get(f"/api/edit/{did}/download?inline=1", headers=H).data)[i].get_text()
j = dtool("numbers", format="ek", ek_no=2, position="ust-sag")
check("Açık belgeye Ek No (hemen görünür)", "Ek:2/3" in dtext(2) and j["canUndo"] and j["unsaved"] and len(j["pages"]) == 4, j.get("error"))
j = c.post(f"/api/edit/{did}/undo", headers=H).get_json()
check("Ek No geri alınır", "Ek:" not in dtext(2) and not j["unsaved"])
j = dtool("watermark", text="ÖRNEK")
check("Açık belgeye filigran", "ÖRNEK" in dtext(0), j.get("error"))
rev = j["rev"]
j = dtool("compress", level="dusuk")
check("Sıkıştırma küçültmezse yeni sürüm oluşmaz", j["rev"] == rev or j.get("changed"), (j.get("rev"), rev, j.get("changed")))
j = dtool("merge", [T / "deneme.pdf"], doc_pos=1)
check("Birleştir: açık belge + seçilen dosya", len(j["pages"]) == 6 and "Lorem" in dtext(0), len(j.get("pages", [])))
j = dtool("pdf-to-word")
check("Açık belgeden Word (ayrı dosya)", j["files"][0]["name"] == "birlesik.docx" and len(c.get(f"/api/edit/{did}", headers=H).get_json()["pages"]) == 6, j)
out = j["files"][0]
r = c.post(f"/api/out/{out['id']}/save", json={"path": str(T / "kayit.docx")}, headers=H)
check("Çıktı seçilen yere kaydedilir", r.status_code == 200 and (T / "kayit.docx").stat().st_size == out["size"], r.get_json())
j = dtool("split", mode="each")
(T / "parcalar").mkdir(exist_ok=True)
r = c.post("/api/out/save-all", json={"ids": [f["id"] for f in j["files"]] + [j["files"][0]["id"]], "dir": str(T / "parcalar")}, headers=H)
sa = r.get_json()
check("Tüm çıktılar klasöre (aynı ad korunur)", r.status_code == 200 and len(sa["paths"]) == 7 and len(set(sa["paths"])) == 7
      and all(Path(p).exists() for p in sa["paths"]), sa)
_sh.rmtree(T / "parcalar"); (T / "kayit.docx").unlink()
r = c.post(f"/api/edit/{did}/tool/editor", data={}, headers=H, content_type="multipart/form-data")
check("Uygun olmayan araç reddedilir", r.status_code == 400)

# --- sürekli kaydırmalı düzenleyici: birden çok sayfadaki eklemeler tek adımda
before_rev = c.get(f"/api/edit/{did}", headers=H).get_json()["rev"]
j = c.post(f"/api/edit/{did}/op", json={"op": "pages_edit", "pages": [
    {"page": 0, "items": [{"type": "text", "x": .1, "y": .02, "w": .5, "h": .03, "text": "BİRİNCİ SAYFA NOTU", "size": 11, "color": "#000000", "font": "sans", "bold": False}], "edits": []},
    {"page": 3, "items": [{"type": "text", "x": .1, "y": .02, "w": .5, "h": .03, "text": "DÖRDÜNCÜ SAYFA NOTU", "size": 11, "color": "#000000", "font": "serif", "bold": True}], "edits": []},
]}, headers=H).get_json()
check("Birden çok sayfaya tek adımda ekleme", "BİRİNCİ SAYFA NOTU" in dtext(0) and "DÖRDÜNCÜ SAYFA NOTU" in dtext(3), j.get("error"))
dd = pymupdf.open(stream=c.get(f"/api/edit/{did}/download", headers=H).data)
faces = {(sp["font"], bool(sp["flags"] & 16)) for b in dd[3].get_text("dict")["blocks"] for l in b.get("lines", [])
         for sp in l["spans"] if "DÖRDÜNCÜ" in sp["text"]}
check("Kalın seçilen metin kalın yazı tipiyle yazılır", faces and all("Bold" in f for f, _ in faces), faces)
stamp = {"type": "stamp", "x": .55, "y": .05, "w": .38, "h": .12, "lines": ["ASLI GİBİDİR", "25.10.2026"], "color": "#c62828"}
c.post(f"/api/edit/{did}/op", json={"op": "pages_edit", "pages": [{"page": 0, "items": [stamp], "edits": []},
                                                                 {"page": 2, "items": [stamp], "edits": []}]}, headers=H)
dd = pymupdf.open(stream=c.get(f"/api/edit/{did}/download", headers=H).data)
red = [sp for b in dd[2].get_text("dict")["blocks"] for l in b.get("lines", []) for sp in l["spans"] if "ASLI" in sp["text"]]
frame = [d for d in dd[2].get_drawings() if d.get("color") and abs(d["color"][0] - 0.776) < 0.01 and d["rect"].width > 100]
check("Kaşe: yazısı kalın ve kırmızı, çerçevesiyle birden çok sayfaya basılır",
      "ASLI GİBİDİR" in dtext(0) and "25.10.2026" in dtext(2) and red and "Bold" in red[0]["font"]
      and red[0]["color"] == 0xC62828 and frame, (red[:1], len(frame)))
c.post(f"/api/edit/{did}/undo", headers=H)
j = c.post(f"/api/edit/{did}/undo", headers=H).get_json()
check("Tek Geri Al ile ikisi birden geri alınır", j["rev"] == before_rev and "BİRİNCİ" not in dtext(0) and "DÖRDÜNCÜ" not in dtext(3), j["rev"])

# --- içindekiler: bölüm listesi başlığın konumunu verir, sayfa içi bağlantılar tıklanabilir
ic = pymupdf.open(); [ic.new_page() for _ in range(3)]
ic[0].insert_text((72, 60), "İÇİNDEKİLER", fontname="helv")
ic[0].insert_link({"kind": pymupdf.LINK_GOTO, "from": pymupdf.Rect(72, 80, 300, 96), "page": 2, "to": pymupdf.Point(72, 300)})
ic[0].insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(72, 100, 300, 116), "uri": "https://www.example.com/karar"})
ic[0].insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(72, 120, 300, 136), "uri": "javascript:alert(1)"})
ic.set_toc([[1, "Giriş", 2, {"kind": pymupdf.LINK_GOTO, "page": 1, "to": pymupdf.Point(0, 396)}], [2, "Değerlendirme", 3]])
ic.save(T / "icindekiler.pdf"); ic.close()
ii = c.post("/api/edit/open", json={"path": str(T / "icindekiler.pdf")}, headers=H).get_json()
ol = c.get(f"/api/edit/{ii['id']}/annotations", headers=H).get_json()["outline"]
check("İçindekiler: başlığın sayfadaki yeri", ol[0]["page"] == 1 and abs(ol[0]["y"] - 396 / 842) < 0.01 and ol[1]["level"] == 2 and ol[1]["page"] == 2, ol)
lk = c.get(f"/api/edit/{ii['id']}/links/0", headers=H).get_json()["links"]
check("Sayfa içi bağlantı → hedef sayfa ve konum", any(l.get("page") == 2 and abs(l["to"] - 300 / 842) < 0.01 and l["y"] < 0.2 for l in lk), lk)
check("Web bağlantısı var, javascript: bağlantısı elendi", [l.get("uri") for l in lk if "uri" in l] == ["https://www.example.com/karar"], lk)
c.post(f"/api/edit/{ii['id']}/op", json={"op": "bookmark_add", "page": 0, "title": "Kapak"}, headers=H)
ol2 = c.get(f"/api/edit/{ii['id']}/annotations", headers=H).get_json()["outline"]
check("Yer imi eklenince eski başlıkların konumu korunur", len(ol2) == 3 and abs(ol2[0]["y"] - 396 / 842) < 0.01, ol2)
(T / "icindekiler.pdf").unlink()

# --- paylaşım (Mail, AirDrop…): paylaşılacak dosyanın yeri
sh = c.post("/api/share", json={"out_id": out["id"]}, headers=H).get_json()
check("Paylaş: araç çıktısı", Path(sh["path"]).name == "birlesik.docx" and Path(sh["path"]).exists(), sh)
_sh.copy(T / "deneme.pdf", T / "paylas.pdf")
pi = c.post("/api/edit/open", json={"path": str(T / "paylas.pdf")}, headers=H).get_json()
sh = c.post("/api/share", json={"sid": pi["id"]}, headers=H).get_json()
check("Paylaş: değişmemiş belge → dosyanın kendisi", sh["path"] == str(T / "paylas.pdf"), sh)
c.post(f"/api/edit/{pi['id']}/op", json={"op": "rotate", "pages": [0], "angle": 90}, headers=H)
sh = c.post("/api/share", json={"sid": pi["id"]}, headers=H).get_json()
shared = pymupdf.open(sh["path"])
check("Paylaş: değişmiş belge → ekrandaki hâlinin kopyası", Path(sh["path"]).name == "paylas.pdf" and sh["path"] != str(T / "paylas.pdf")
      and shared[0].rotation == 90 and pymupdf.open(T / "paylas.pdf")[0].rotation == 0, sh)
shared.close(); (T / "paylas.pdf").unlink()

import shutil
import re as _re
_ver = (A.BASE / "surum.txt").read_text(encoding="utf-8").strip()
check("Sürüm: surum.txt'te üç parçalı numara (ör. 1.0.0)", bool(_re.fullmatch(r"\d+\.\d+\.\d+", _ver)), _ver)
check("Paket: proje klasöründen çalışan geliştirme sürümü paket sayılmaz; sürümü surum.txt'ten",
      A.PACKAGED is False and A.SURUM == _ver and A.KAYNAK is None and A.UPDATER.current is None)
_st = A.app.test_client().get("/api/status", headers=H).get_json()
check("Sürüm: /api/status numarayı ve paket olup olmadığını bildirir", _st["version"] == _ver and _st["packaged"] is False, _st)

# --- araç bilgisi (Word, LibreOffice, metin tanıma): bir kez hesaplanır, başlatıcının yoklaması beklemez
import threading as _thr, time as _tim
_calls, _real_engines = [], A.converters.engines
def _slow_engines():
    _calls.append(1); _tim.sleep(0.3)   # Windows'ta ilk yoklama yavaş olabilir
    return {"word": False, "excel": False, "libreoffice": False}
A.converters.engines, A.ENGINES["value"] = _slow_engines, None
_res = []
_ths = [_thr.Thread(target=lambda: _res.append(A.app.test_client().get("/api/status", headers=H).get_json()["engines"]))
        for _ in range(4)]
[t.start() for t in _ths]; _tim.sleep(0.05)
_t0 = _tim.time(); _light = A.app.test_client().get("/api/status?yoklama=1", headers=H).get_json(); _light_s = _tim.time() - _t0
[t.join() for t in _ths]
check("Durum: aynı anda gelen istekler araç bilgisini bir kez hesaplatır", len(_calls) == 1 and len(_res) == 4
      and all(r == _res[0] and "ocr" in r for r in _res), _calls)
check("Durum: başlatıcının yoklaması (?yoklama=1) araç bilgisini beklemez", "engines" not in _light
      and _light["version"] == A.SURUM and _light_s < 0.2, f"{_light_s:.2f} sn")
A.app.test_client().get("/api/status", headers=H)
check("Durum: araç bilgisi bir dakika saklanır", len(_calls) == 1, _calls)
A.converters.engines, A.ENGINES["value"] = _real_engines, None

# --- uygulama anahtarı (kurulum paketleri): motor yalnızca kendi penceresine cevap verir
check("Anahtar: geliştirme sürümünde kapalı", A.APP_KEY is None and not A.KEY_FILE.exists())
A.APP_KEY = "deneme-anahtari"
k = A.app.test_client()   # ayrı bir "tarayıcı": kendi çerezleriyle
no_key = k.get("/", headers=H)
status = k.get("/api/status", headers=H)
wrong = k.get("/?anahtar=yanlis", headers=H)
first = k.get("/shell?anahtar=deneme-anahtari&open=/Belgeler/dilekce.pdf", headers=H)
after = k.get("/", headers=H)
api = k.post("/api/edit/open", json={}, headers=H)
A.APP_KEY = None
check("Anahtar: tarayıcıdan açılınca engellenir, durum sorgusu çalışır",
      no_key.status_code == 403 and "kendi penceresinde" in no_key.get_data(as_text=True)
      and status.status_code == 200 and wrong.status_code == 403)
check("Anahtar: pencere anahtarla açılınca çereze yazılır, adresten silinir",
      first.status_code == 302 and first.headers["Location"] == "/shell?open=%2FBelgeler%2Fdilekce.pdf"
      and "kpa=deneme-anahtari" in first.headers.get("Set-Cookie", "") and "HttpOnly" in first.headers["Set-Cookie"]
      and after.status_code == 200 and api.status_code != 403, (first.status_code, first.headers.get("Location")))

# --- paragraf düzenleme: metin paragrafın içinde yeniden dizilir, alttaki metin kayar
pd = pymupdf.open(); pg = pd.new_page()
para = ("Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore "
        "magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.")
pg.insert_htmlbox(pymupdf.Rect(72, 72, 523, 600), f"<p>{para}</p><p>Duis aute irure dolor in reprehenderit. {para}</p>",
                  css="p {font-family: serif; font-size: 12pt; line-height: 15pt; text-align: justify; text-indent: 24pt; margin: 0 0 15pt 0;}")
pd.save(T / "paragraf.pdf")
ps = c.post("/api/edit/open", json={"path": str(T / "paragraf.pdf")}, headers=H).get_json()
paras = c.get(f"/api/edit/{ps['id']}/lines/0", headers=H).get_json()["lines"]
check("Paragraflar: satırlar paragraflara gruplanır", len(paras) == 2 and all(len(p["lines"]) >= 3 for p in paras)
      and paras[0]["align"] == "justify" and paras[0]["indent"] > 20, [(len(p.get("lines", [])), p.get("align")) for p in paras])
# Okuyucunun seçilebilir metni paragraf değil satır satır, kelime kelime gelmeli (tek satır seçilip vurgulanabilsin)
wl = c.get(f"/api/edit/{ps['id']}/words/0", headers=H).get_json()["lines"]
ws = wl[1]["words"]
check("Okuyucu metin katmanı: her satır ayrı, kelime kelime ve kesintisiz",
      len(wl) == sum(len(p["lines"]) for p in paras) and all(len(l["words"]) > 3 for l in wl)
      and all(abs(a[0] + a[1] - b[0]) < 1e-4 for a, b in zip(ws, ws[1:])) and wl[1]["h"] < 0.03,
      (len(wl), [len(l["words"]) for l in wl]))
p0, p1 = paras
ek = " Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum."
r = c.post(f"/api/edit/{ps['id']}/op", json={"op": "text_edit", "page": 0, "edits": [dict(p0, text=p0["text"] + ek)]}, headers=H).get_json()
after = c.get(f"/api/edit/{ps['id']}/lines/0", headers=H).get_json()["lines"]
outp = pymupdf.open(stream=c.get(f"/api/edit/{ps['id']}/download", headers=H).data)[0]
check("Paragraf düzenle: metin kenarlar arasında yeniden dizilir, ilk satır yerinde kalır",
      "error" not in r and len(after) == 2 and len(after[0]["lines"]) > len(p0["lines"])
      and max(b[2] for b in after[0]["lines"]) <= p0["right"] + 1 and abs(after[0]["origin"][1] - p0["origin"][1]) < 0.5, r.get("error"))
check("Paragraf düzenle: alttaki paragraf kayar, metin tekrarlanmaz, aranabilir",
      after[1]["origin"][1] > p1["origin"][1] + 10 and outp.get_text().count("Duis aute") == 1
      and len(outp.search_for("officia deserunt")) == 1, (p1["origin"][1], after[1]["origin"][1]))
(T / "paragraf.pdf").unlink()
ts = c.post("/api/edit/open", json={"path": str(T / "deneme.pdf")}, headers=H).get_json()
tl = c.get(f"/api/edit/{ts['id']}/lines/0", headers=H).get_json()["lines"]
cells = [l["text"] for l in tl if l["text"].startswith("Hücre")]
check("Paragraflar: tablo hücreleri birbirine karışmaz", cells == [f"Hücre {r}-{k}" for r in (1, 2, 3) for k in (1, 2, 3)], cells)
cell = next(l for l in tl if l["text"] == "Hücre 1-2")
r = c.post(f"/api/edit/{ts['id']}/op", json={"op": "text_edit", "page": 0, "edits": [dict(cell, text="Değişti")]}, headers=H).get_json()
check("Paragraflar: sıkışık tablo hücresi düzenlenebilir, yandaki hücreye taşmaz",
      "error" not in r and cell["right"] < 378, (r.get("error"), cell["right"]))

# --- metin tanıma (OCR)
import ocr as _ocr
if _ocr.available():
    src = pymupdf.open(T / "deneme.pdf"); scan = pymupdf.open()
    for pg in src:
        np_ = scan.new_page(width=pg.rect.width, height=pg.rect.height); np_.insert_image(np_.rect, pixmap=pg.get_pixmap(dpi=150))
    scan.save(T / "taranmis.pdf"); src[0].get_pixmap(dpi=150).save(T / "foto.png")
    r, j = post("/api/tool/ocr", [T / "taranmis.pdf", T / "foto.png"])
    texts = [pymupdf.open(stream=fetch(f))[0].get_text() for f in j["files"] if "error" not in f]
    check("OCR aracı (PDF + fotoğraf)", len(texts) == 2 and all("İğne" in t and "\xa0" not in t for t in texts), j)
    r = c.post("/api/edit/open", json={"path": str(T / "taranmis.pdf")}, headers=H); si = r.get_json()
    check("Okuyucu: taranmış belge algılanır", si.get("scanned") is True, si.get("scanned"))
    w0 = c.get(f"/api/edit/{si['id']}/words/0", headers=H).get_json()
    w1 = c.get(f"/api/edit/{si['id']}/words/0?ocr=1", headers=H).get_json()
    seen = " ".join(w[2] for l in w1["lines"] for w in l["words"])
    xs = [w[0] for l in w1["lines"] for w in l["words"]]
    check("Okuyucu: taranmış sayfanın yazısı belgeye yazılmadan tanınır (kelime kelime, seçilebilir)",
          w0["lines"] == [] and w1.get("ocr") and "Lorem" in seen and len(set(xs)) > 3
          and not c.get(f"/api/edit/{si['id']}", headers=H).get_json()["unsaved"], seen[:120])
    si2 = c.post(f"/api/edit/{si['id']}/op", json={"op": "ocr"}, headers=H).get_json()
    hits = c.get(f"/api/edit/{si['id']}/search?q=Lorem", headers=H).get_json()["hits"]
    check("Okuyucu: metni tanı → arama", si2.get("count") == 2 and not si2.get("scanned") and len(hits) == 2, si2.get("count"))
    (T / "taranmis.pdf").unlink(); (T / "foto.png").unlink()

    # KVKK taranmış sayfada: yazı tanınarak aranır, karartma resmin o kısmını siler. Sayfanın altında UYAP'taki gibi
    # kısa bir doğrulama yazısı var (metin katmanı boş değil, ama sayfanın çoğu resim)
    kv = pymupdf.open(); kvp = kv.new_page()
    kvp.insert_htmlbox(pymupdf.Rect(50, 50, 545, 400), "<p style='font-size:14px'>Basvuru sahibi Ayse Demir (T.C. Kimlik No: "
        "10000000146) iadenin yapilmasini istemistir. E-posta: ayse.demir@ornek.com.tr</p>"
        "<p style='font-size:14px;line-height:1'>HAKIM : Elif Karaca 123456<br>KATIP : Burak Ozdemir 654321</p>")
    ks_ = pymupdf.open(); ksp = ks_.new_page(width=kvp.rect.width, height=kvp.rect.height)
    ksp.insert_image(ksp.rect, pixmap=kvp.get_pixmap(dpi=150))
    ksp.insert_text((50, 820), "Bu belge 5070 sayili kanuna gore elektronik imza ile imzalanmistir.", fontsize=7)
    ks_.save(T / "kvkk_tarama.pdf")
    kss = c.post("/api/edit/open", json={"path": str(T / "kvkk_tarama.pdf")}, headers=H).get_json()
    pd = c.post(f"/api/edit/{kss['id']}/personal-data", json={}, headers=H).get_json()
    got = {it["kind"]: it for it in pd["items"]}
    names = {it["text"] for it in pd["items"] if it["kind"] == "ad"}
    check("KVKK taranmış sayfa: yazı tanınarak kişisel veriler bulunur (sık satırlardaki adlar da)",
          pd["scanned"] == [0] and {"tckn", "eposta", "ad"} <= set(got) and got["tckn"]["text"] == "10000000146"
          and {"Elif Karaca", "Burak Ozdemir"} <= names
          and all(0 < r[2] < 1 and 0 < r[3] < 0.1 for it in pd["items"] for r in it["rects"]),
          [(it["kind"], it["text"], it["rects"]) for it in pd["items"]])
    c.post(f"/api/edit/{kss['id']}/op", json={"op": "redact_areas",
           "areas": [{"page": it["page"], "rects": it["rects"]} for it in pd["items"]]}, headers=H)
    pd2 = c.post(f"/api/edit/{kss['id']}/personal-data", json={}, headers=H).get_json()
    left = c.get(f"/api/edit/{kss['id']}/words/0?ocr=1", headers=H).get_json()
    seen = " ".join(w[2] for l in left["lines"] for w in l["words"])
    check("KVKK taranmış sayfa: karartılan yerler resimden silinir, gerisi okunur",
          not any(it["kind"] in ("tckn", "eposta", "ad") for it in pd2["items"]) and "iadenin" in seen and "10000000146" not in seen,
          ([(it["kind"], it["text"]) for it in pd2["items"]], seen[:160]))
    (T / "kvkk_tarama.pdf").unlink()
else:
    print("(OCR testleri atlandı: metin tanıma yardımcısı yok)")

# --- önceki sürümler: her kaydedişte eski hâl yedeklenir, listelenir, geri yüklenir; son 10 yedek tutulur
import time as _tm2
_real_backups, A.yedekler.BACKUPS = A.yedekler.BACKUPS, T / "yedek-deneme"
vd = T / "surumler"; vd.mkdir(exist_ok=True)
other = T / "surumler2"; other.mkdir(exist_ok=True)
def _pdf(path, text):
    d = pymupdf.open(); d.new_page().insert_text((72, 72), text); d.save(path)
_pdf(vd / "dilekce.pdf", "BIRINCI HAL"); _pdf(other / "dilekce.pdf", "BASKA KLASOR")
vs = c.post("/api/edit/open", json={"path": str(vd / "dilekce.pdf")}, headers=H).get_json()
c.post(f"/api/edit/{vs['id']}/op", json={"op": "rotate", "pages": [0], "angle": 90}, headers=H)
c.post(f"/api/edit/{vs['id']}/save", json={}, headers=H)
_tm2.sleep(1.1)
c.post(f"/api/edit/{vs['id']}/op", json={"op": "rotate", "pages": [0], "angle": 90}, headers=H)
c.post(f"/api/edit/{vs['id']}/save", json={}, headers=H)
os_ = c.post("/api/edit/open", json={"path": str(other / "dilekce.pdf")}, headers=H).get_json()
c.post(f"/api/edit/{os_['id']}/op", json={"op": "rotate", "pages": [0], "angle": 90}, headers=H)
c.post(f"/api/edit/{os_['id']}/save", json={}, headers=H)
items = c.get("/api/backups", query_string={"path": str(vd / "dilekce.pdf")}, headers=H).get_json()["items"]
check("Önceki sürümler: dosyanın yedekleri yeniden eskiye; aynı adlı başka klasördeki dosyanınkiler karışmaz",
      len(items) == 2 and items[0]["id"] > items[1]["id"]
      and all("BASKA" not in pymupdf.open(it["path"])[0].get_text() for it in items), items)
r = c.post("/api/backups/restore", json={"path": str(vd / "dilekce.pdf"), "id": items[1]["id"]}, headers=H).get_json()
restored = pymupdf.open(vd / "dilekce.pdf")
items2 = c.get("/api/backups", query_string={"path": str(vd / "dilekce.pdf")}, headers=H).get_json()["items"]
check("Önceki sürümler: geri yükleme dosyayı o hâline döndürür, şimdiki hâli de yedeklenir",
      r.get("ok") and restored[0].rotation == 0 and len(items2) == 3, (r, restored[0].rotation, len(items2)))
bo = c.post("/api/edit/open", json={"path": items2[0]["path"]}, headers=H).get_json()
check("Önceki sürümler: yedek kopya olarak açılır (Kaydet yedeğin üzerine yazmaz)",
      not bo["can_save_source"] and bo["name"].startswith("dilekce (yedek "), bo["name"])
# Kaydet: dosya başka bir uygulamada değiştirildiyse ya da taşındıysa 409 (arayüz sorar); force ile yine yazılır
cs = c.post("/api/edit/open", json={"path": str(vd / "dilekce.pdf")}, headers=H).get_json()
c.post(f"/api/edit/{cs['id']}/op", json={"op": "rotate", "pages": [0], "angle": 180}, headers=H)
_tm2.sleep(1.2); _pdf(vd / "dilekce.pdf", "BASKA UYGULAMA")
r1 = c.post(f"/api/edit/{cs['id']}/save", json={}, headers=H)
r2 = c.post(f"/api/edit/{cs['id']}/save", json={"force": True}, headers=H)
kept = [it for it in c.get("/api/backups", query_string={"path": str(vd / "dilekce.pdf")}, headers=H).get_json()["items"]
        if "BASKA UYGULAMA" in pymupdf.open(it["path"])[0].get_text()]
(vd / "dilekce.pdf").unlink()
r3 = c.post(f"/api/edit/{cs['id']}/save", json={}, headers=H)
r4 = c.post(f"/api/edit/{cs['id']}/save", json={"force": True}, headers=H)
check("Kaydet: değiştirilmiş / taşınmış dosya sorulur; onaylanınca yazılır, öbür uygulamadaki hâli yedeklenir",
      r1.status_code == 409 and r1.get_json()["conflict"] == "modified" and r2.status_code == 200 and kept
      and r3.status_code == 409 and r3.get_json()["conflict"] == "missing" and r4.status_code == 200
      and pymupdf.open(vd / "dilekce.pdf")[0].rotation == 180, (r1.status_code, r2.status_code, len(kept), r3.status_code, r4.status_code))
check("Önceki sürümler: başka bir dosyanın yedeği geri yüklenemez",
      c.post("/api/backups/restore", json={"path": str(vd / "dilekce.pdf"), "id": "baska.pdf"}, headers=H).status_code == 400)
# Saniyeden kısa dış değişiklik (yalnız değiştirilme zamanı 0,5 sn ileri) ve aynı dosyayı açmış iki oturum
_pdf(vd / "cakisma.pdf", "ILK HAL")
ca = c.post("/api/edit/open", json={"path": str(vd / "cakisma.pdf")}, headers=H).get_json()
cb = c.post("/api/edit/open", json={"path": str(vd / "cakisma.pdf")}, headers=H).get_json()
for _sid in (ca["id"], cb["id"]):
    c.post(f"/api/edit/{_sid}/op", json={"op": "rotate", "pages": [0], "angle": 90}, headers=H)
_ns = (vd / "cakisma.pdf").stat().st_mtime_ns + 500_000_000
os.utime(vd / "cakisma.pdf", ns=(_ns, _ns))
ra1 = c.post(f"/api/edit/{ca['id']}/save", json={}, headers=H)
ra2 = c.post(f"/api/edit/{ca['id']}/save", json={"force": True}, headers=H)
rb = c.post(f"/api/edit/{cb['id']}/save", json={}, headers=H)   # A az önce yazdı: B'nin açtığı hâl değişti
c.post(f"/api/edit/{ca['id']}/op", json={"op": "rotate", "pages": [0], "angle": 90}, headers=H)
ra3 = c.post(f"/api/edit/{ca['id']}/save", json={}, headers=H)   # kendi kaydından sonra sorulmaz
check("Kaydet: saniyeden kısa dış değişiklik ve aynı dosyayı açmış ikinci oturum sorulur; kendi kaydından sonra sorulmaz",
      ra1.status_code == 409 and ra1.get_json()["conflict"] == "modified" and ra2.status_code == 200
      and rb.status_code == 409 and rb.get_json()["conflict"] == "modified" and ra3.status_code == 200,
      (ra1.status_code, ra2.status_code, rb.status_code, ra3.status_code))
tag = A.yedekler.file_tag(vd / "dilekce.pdf")
for k in range(12):
    (A.yedekler.BACKUPS / f"dilekce_{tag}_202610{k + 10:02d}-120000.pdf").write_bytes(b"x")
(A.yedekler.BACKUPS / "eski_20200101-120000.pdf").write_bytes(b"x")
A.yedekler.prune_backups()
check("Önceki sürümler: dosya başına son 10 yedek kalır, 60 günden eskiler silinir",
      len(A.yedekler.backups_of(vd / "dilekce.pdf")) == 10 and not (A.yedekler.BACKUPS / "eski_20200101-120000.pdf").exists(),
      len(A.yedekler.backups_of(vd / "dilekce.pdf")))
# --- Geri alma sürümleri yer sınırını aşmaz (belge başına ve açık belgelerin hepsi birlikte); güncel sürüm ve son adım kalır
_pdf(vd / "butce.pdf", "BUTCE"); _pdf(vd / "butce2.pdf", "BUTCE IKI")
bs = c.post("/api/edit/open", json={"path": str(vd / "butce.pdf")}, headers=H).get_json()
_real_hb, A.editor.HISTORY_BYTES = A.editor.HISTORY_BYTES, 1
for _ in range(4):
    c.post(f"/api/edit/{bs['id']}/op", json={"op": "rotate", "pages": [0], "angle": 90}, headers=H)
A.editor.HISTORY_BYTES = _real_hb
_bs = A.store.get(bs["id"])
_vfiles = sorted(p.name for p in _bs.dir.glob("v*.pdf"))
_u1 = c.post(f"/api/edit/{bs['id']}/undo", headers=H).get_json()
_u2 = c.post(f"/api/edit/{bs['id']}/undo", headers=H).get_json()
c.post(f"/api/edit/{bs['id']}/redo", headers=H)
check("Geri alma: belge başına yer sınırı aşılınca eski adımlar silinir; güncel sürüm ve son adım kalır",
      len(_bs.history) == 2 and _vfiles == sorted(p.name for p in _bs.history) and _u1["canUndo"] is False
      and _u2["canUndo"] is False and pymupdf.open(_bs.path)[0].rotation == 0, (_vfiles, _u1["canUndo"]))
b2 = c.post("/api/edit/open", json={"path": str(vd / "butce2.pdf")}, headers=H).get_json()
for _ in range(3):
    c.post(f"/api/edit/{b2['id']}/op", json={"op": "rotate", "pages": [0], "angle": 90}, headers=H)
_b2 = A.store.get(b2["id"])
_n_before = len(_b2.history)
_real_sb, A.editor.STORE_BYTES = A.editor.STORE_BYTES, 1
c.post(f"/api/edit/{bs['id']}/op", json={"op": "rotate", "pages": [0], "angle": 90}, headers=H)
A.editor.STORE_BYTES = _real_sb
_meta = json.loads((_b2.dir / A.editor.META).read_text(encoding="utf-8"))
check("Geri alma: açık belgelerin hepsi birlikte sınırı aşınca öbür belgenin eski adımları da silinir (kurtarma bilgisi güncel)",
      _n_before == 4 and len(_b2.history) == 2 and pymupdf.open(_b2.path)[0].rotation == 270
      and _meta["history"] == [p.name for p in _b2.history] and sorted(p.name for p in _b2.dir.glob("v*.pdf")) == _meta["history"],
      (_n_before, len(_b2.history)))
# Disk doldu: değişiklik uygulanmaz, oturum ve kaydedilecek dosya bozulmaz, yarım dosya kalmaz
import errno as _errno
_real_save, _real_copy2 = pymupdf.Document.save, A.yedekler.shutil.copy2
def _no_space(doc, filename=None, *a, **k):   # yarısını yazıp kalır (PyMuPDF'in mesajıyla)
    if isinstance(filename, (str, Path)):
        Path(filename).write_bytes(b"%PDF-yarim")
    raise RuntimeError("code=2: cannot write to file: No space left on device")
def _half_copy(src, dst, *a, **k):
    Path(dst).write_bytes(b"%PDF-yarim"); raise OSError(_errno.ENOSPC, "No space left on device")
_hist, _files = list(_b2.history), sorted(p.name for p in _b2.dir.iterdir())
_orig = (vd / "butce2.pdf").read_bytes()
_nbk = len(A.yedekler.backups_of(vd / "butce2.pdf"))
pymupdf.Document.save = _no_space
try:
    _d1 = c.post(f"/api/edit/{b2['id']}/op", json={"op": "rotate", "pages": [0], "angle": 90}, headers=H)
    _d2 = c.post(f"/api/edit/{b2['id']}/save", json={}, headers=H)
    pymupdf.Document.save = _real_save
    A.yedekler.shutil.copy2 = _half_copy
    _d3 = c.post(f"/api/edit/{b2['id']}/save", json={}, headers=H)
finally:
    pymupdf.Document.save, A.yedekler.shutil.copy2 = _real_save, _real_copy2
_left = [p.name for p in vd.iterdir() if "kocpdf-tmp" in p.name]
check("Disk doldu: değişiklik uygulanmaz, belge son hâlinde kalır, yarım sürüm dosyası bırakılmaz",
      _d1.status_code == 400 and "Diskte yer kalmadı" in _d1.get_json()["error"] and _b2.history == _hist
      and sorted(p.name for p in _b2.dir.iterdir()) == _files and pymupdf.open(_b2.path)[0].rotation == 270,
      (_d1.status_code, _d1.get_json()))
check("Disk doldu: kaydedilemez, açılan dosya ve yedekler bozulmaz, yarım geçici dosya ya da yedek kalmaz",
      _d2.status_code == 400 and "Diskte yer kalmadı" in _d2.get_json()["error"] and _d3.status_code == 400
      and "Diskte yer kalmadı" in _d3.get_json()["error"] and (vd / "butce2.pdf").read_bytes() == _orig and not _left
      and len(A.yedekler.backups_of(vd / "butce2.pdf")) == _nbk + 1 and _b2.unsaved
      and all(f.read_bytes()[:5] == b"%PDF-" and f.stat().st_size > 20 for f, _ in A.yedekler.backups_of(vd / "butce2.pdf")),
      (_d2.status_code, _d3.status_code, _left))
_d4 = c.post(f"/api/edit/{b2['id']}/op", json={"op": "rotate", "pages": [0], "angle": 90}, headers=H)
_d5 = c.post(f"/api/edit/{b2['id']}/save", json={}, headers=H)
check("Disk doldu: yer açılınca değişiklik de kaydetme de olağan çalışır",
      _d4.status_code == 200 and _d5.status_code == 200 and pymupdf.open(vd / "butce2.pdf")[0].rotation == 0 and not _b2.unsaved,
      (_d4.status_code, _d5.status_code))
A.yedekler.BACKUPS = _real_backups
shutil.rmtree(T / "yedek-deneme"); shutil.rmtree(vd); shutil.rmtree(other)

# --- Türkçe arama: büyük-küçük harf Türkçe kurallarla, şapkasız, satır sonunda bölünmüş kelimeler de
ta = pymupdf.open(); tpg = ta.new_page()
tpg.insert_htmlbox(pymupdf.Rect(50, 50, 545, 200), "<p>İSTANBUL ŞAHİN ılık İLİK HÂKİM</p>")
for k, t in enumerate(["bedelin iadesine karar veril-", "mesine, sonucun bir e-", "posta ile bildirilmesine"]):
    tpg.insert_text((50, 250 + k * 15), t, fontname="helv", fontsize=11)
ta.save(T / "arama.pdf"); ta.close()
ts_ = c.post("/api/edit/open", json={"path": str(T / "arama.pdf")}, headers=H).get_json()
def _n(q):
    return sum(len(h["rects"]) for h in c.get(f"/api/edit/{ts_['id']}/search", query_string={"q": q}, headers=H).get_json()["hits"])
found = {q: _n(q) for q in ("istanbul", "şahin", "ılık", "ilik", "hakim", "verilmesine", "e-posta", "ıstanbul")}
check("Arama: Türkçe büyük-küçük harf (İ/i, I/ı ayrı), şapkasız, satır sonunda bölünmüş kelime",
      found == {"istanbul": 1, "şahin": 1, "ılık": 1, "ilik": 1, "hakim": 1, "verilmesine": 2, "e-posta": 2, "ıstanbul": 0}, found)
_pdf(T / "ara1.pdf", "ISTINAF yolu acik; istinaf suresi"); _pdf(T / "ara2.pdf", "istinaf"); _pdf(T / "ara3.pdf", "baska")
a1 = c.post("/api/edit/open", json={"path": str(T / "ara1.pdf")}, headers=H).get_json()
c.post("/api/edit/open", json={"path": str(T / "ara2.pdf")}, headers=H)
a2 = c.post("/api/edit/open", json={"path": str(T / "ara2.pdf")}, headers=H).get_json()   # aynı dosya ikinci kez
c.post("/api/edit/open", json={"path": str(T / "ara3.pdf")}, headers=H)
sa = c.get("/api/search-all", query_string={"q": "istinaf", "current": a2["id"]}, headers=H).get_json()["docs"]
sa_tabs = c.get("/api/search-all", query_string=[("q", "istinaf"), ("current", a2["id"]), ("path", str(T / "ara2.pdf"))],
                headers=H).get_json()["docs"]
check("Tüm belgelerde arama: belge başına sayı, bu belge başta, aynı dosya bir kez; sekme süzgeci",
      [(d["name"], d["count"], d["current"]) for d in sa] == [("ara2.pdf", 1, True), ("ara1.pdf", 1, False)]   # ISTINAF = ıstınaf
      and sa[1]["pages"][0]["snippet"].startswith("ISTINAF") and [d["name"] for d in sa_tabs] == ["ara2.pdf"], (sa, sa_tabs))
for f in ("arama", "ara1", "ara2", "ara3"):
    (T / f"{f}.pdf").unlink()

# --- son açılanlar: diskten açılanlar en yeni başta; çıkarılır, temizlenir; bulunamayan işaretlenir
c.post("/api/recent/remove", json={}, headers=H)
_pdf(T / "son1.pdf", "BIR"); _pdf(T / "son2.pdf", "IKI")
for f in ("son1.pdf", "son2.pdf", "son1.pdf"):
    c.post("/api/edit/open", json={"path": str(T / f)}, headers=H)
c.post("/api/edit/open", data={"files": [(open(T / "son2.pdf", "rb"), "yuklenen.pdf")]}, headers=H, content_type="multipart/form-data")
r1 = [it["name"] for it in c.get("/api/recent", headers=H).get_json()["items"]]
(T / "son2.pdf").unlink()
r2 = {it["name"]: it["exists"] for it in c.get("/api/recent", headers=H).get_json()["items"]}
c.post("/api/recent/remove", json={"path": str(T / "son2.pdf")}, headers=H)
r3 = [it["name"] for it in c.get("/api/recent", headers=H).get_json()["items"]]
c.post("/api/recent/remove", json={}, headers=H)
r4 = c.get("/api/recent", headers=H).get_json()["items"]
c.post("/api/recent/import", json={"items": [{"path": str(T / "son1.pdf"), "time": 100}, {"path": str(T / "yok.pdf"), "time": 200},
                                             {"path": str(T / "deneme.pdf"), "time": 300}]}, headers=H)
r5 = [it["name"] for it in c.get("/api/recent", headers=H).get_json()["items"]]
c.post("/api/recent/remove", json={}, headers=H)
check("Son açılanlar: en yeni başta, tekrar etmez, yüklenen girmez; bulunamayan işaretlenir, çıkarılır, temizlenir",
      r1 == ["son1.pdf", "son2.pdf"] and r2 == {"son1.pdf": True, "son2.pdf": False} and r3 == ["son1.pdf"] and r4 == []
      and r5 == ["deneme.pdf", "son1.pdf"], (r1, r2, r3, r4, r5))
(T / "son1.pdf").unlink()

# --- karışık birleştirme: PDF, Word, UDF, resim ve TIFF sırayla tek PDF; resimler A4'e; her dosya bir başlık
from PIL import Image as _Img
_Img.new("RGB", (1600, 900), (40, 120, 200)).save(T / "yatay.png")
_Img.new("L", (1654, 2339), 255).save(T / "tarama.tif", save_all=True, append_images=[_Img.new("L", (1654, 2339), 200)],
                                       dpi=(200, 200))
r, j = post("/api/tool/merge", [T / "deneme.pdf", T / "yatay.png", T / "tarama.tif", T / "deneme.udf", T / "deneme.docx"],
            name="dava dosyasi")
mm = pymupdf.open(stream=fetch(j["files"][0])) if "files" in j else None
toc = mm.get_toc() if mm else []
pdf_n, udf_n = pymupdf.open(T / "deneme.pdf").page_count, None
check("Birleştir: PDF, resim, çok sayfalı TIFF, UDF ve Word sırayla birleşir; her dosya içindekilerde başlık",
      mm and [t[1] for t in toc if t[0] == 1] == ["deneme", "yatay", "tarama", "deneme", "deneme"]
      and mm[pdf_n].rect.width > mm[pdf_n].rect.height            # yatay resim yatay A4'te
      and abs(mm[pdf_n].rect.width - 842) < 1
      and abs(mm[pdf_n + 1].rect.height - 842) < 1 and abs(mm[pdf_n + 2].rect.height - 842) < 1   # TIFF'in iki sayfası A4
      and toc[[t[1] for t in toc].index("tarama")][2] == pdf_n + 2, (j, toc))
r, j = post("/api/convert/images-to-pdf", [T / "tarama.tif"], page_size="orijinal")
tp_ = pymupdf.open(stream=fetch(j["files"][0]))
check("TIFF → PDF: çok sayfalı TIFF'in her sayfası ayrı sayfa, 200 dpi tarama A4 boyutunda",
      tp_.page_count == 2 and abs(tp_[0].rect.width - 595.4) < 2, (tp_.page_count, tp_[0].rect))
tiffs = {}
for mode in ("gri", "sb"):
    r, j = post("/api/convert/pdf-to-images", [T / "deneme.pdf"], format="tiff", dpi="200", color=mode)
    im = _Img.open(io.BytesIO(fetch(j["files"][0])))
    tiffs[mode] = (j["files"][0]["name"], im.n_frames, im.mode, im.info.get("compression"), j["files"][0]["size"])
check("PDF → TIFF: bütün sayfalar tek dosyada; siyah-beyaz G4 ile en küçük",
      tiffs["gri"][0] == "deneme.tif" and tiffs["gri"][1] == pymupdf.open(T / "deneme.pdf").page_count
      and tiffs["gri"][2] == "L" and tiffs["sb"][2] == "1" and tiffs["sb"][3] == "group4" and tiffs["sb"][4] < tiffs["gri"][4], tiffs)
(T / "yatay.png").unlink(); (T / "tarama.tif").unlink()

# --- e-imzalı PDF: değişiklikler dosyanın sonuna eklenir (artımlı); imzalı baytlar aynen kalır
def imzala(path):
    """Deneme e-imzası: imza alanına imza değeri (/V) dosyanın sonuna eklenir. Şifreli imza yok; uygulama
    yalnızca imzanın varlığına bakar."""
    d = pymupdf.open(path); sig = d.get_new_xref()
    d.update_object(sig, "<< /Type /Sig /Filter /Adobe.PPKLite /SubFilter /adbe.pkcs7.detached /ByteRange [0 0 0 0] /Contents <00> >>")
    d.xref_set_key(next(d[0].widgets()).xref, "V", f"{sig} 0 R"); d.saveIncr(); d.close()

sd = pymupdf.open(); sp_ = sd.new_page(); sp_.insert_text((72, 72), "IMZALI KARAR")
sw = pymupdf.Widget(); sw.field_type = pymupdf.PDF_WIDGET_TYPE_SIGNATURE; sw.field_name = "Imza"
sw.rect = pymupdf.Rect(60, 700, 260, 740); sp_.add_widget(sw)
sd.save(T / "imzali.pdf"); sd.close()
bos_ = c.post("/api/edit/open", json={"path": str(T / "imzali.pdf")}, headers=H).get_json()
c.post(f"/api/edit/{bos_['id']}/close", headers=H)
check("E-imza: imzalanmamış boş imza alanı imza sayılmaz", not bos_["signed"], bos_.get("signed"))
imzala(T / "imzali.pdf")
orig = (T / "imzali.pdf").read_bytes()
si_ = c.post("/api/edit/open", json={"path": str(T / "imzali.pdf")}, headers=H).get_json()
c.post(f"/api/edit/{si_['id']}/op", json={"op": "highlight", "page": 0, "rects": [[.1, .07, .3, .03]], "color": "#ffe14d"}, headers=H)
c.post(f"/api/edit/{si_['id']}/op", json={"op": "note", "page": 0, "x": .5, "y": .3, "text": "inceleme"}, headers=H)
files_before = sorted(p.name for p in (A.store.root / si_["id"]).glob("v*.pdf"))
bad = c.post(f"/api/edit/{si_['id']}/op", json={"op": "annot_delete", "page": 0, "xref": 999999}, headers=H)
files_after = sorted(p.name for p in (A.store.root / si_["id"]).glob("v*.pdf"))
c.post(f"/api/edit/{si_['id']}/save", json={"path": str(T / "imzali_notlu.pdf")}, headers=H)
saved_ = (T / "imzali_notlu.pdf").read_bytes()
dl = c.get(f"/api/edit/{si_['id']}/download", headers=H).data
check("E-imza: imzalı belge tanınır; not ve vurgu dosyanın sonuna eklenir, imzalı baytlar aynen kalır",
      si_["signed"] and saved_.startswith(orig) and len(saved_) > len(orig) and dl.startswith(orig)
      and len(list(pymupdf.open(T / "imzali_notlu.pdf")[0].annots())) == 2, (si_["signed"], saved_[:len(orig)] == orig))
check("E-imza: yarıda kalan işlem artık dosya bırakmaz", bad.status_code >= 400 and files_before == files_after,
      (files_before, files_after))
# Karartma artımlı eklenseydi dosyanın ilk (imzalı) bölümü ayrıca açılınca karartılan yazı okunurdu: belge baştan yazılır
_ip = pymupdf.open(T / "imzali.pdf"); _pw, _ph = _ip[0].rect.width, _ip[0].rect.height
_r = _ip[0].search_for("IMZALI")[0]; _ip.close()
rd_ = c.post(f"/api/edit/{si_['id']}/op", json={"op": "redact_areas", "areas": [
    {"page": 0, "rects": [[_r.x0 / _pw, _r.y0 / _ph, _r.width / _pw, _r.height / _ph]]}]}, headers=H).get_json()
_after = c.post(f"/api/edit/{si_['id']}/op", json={"op": "note", "page": 0, "x": .5, "y": .5, "text": "sonra"}, headers=H).get_json()
_dl = c.get(f"/api/edit/{si_['id']}/download", headers=H).data
_sh = Path(c.post("/api/share", json={"sid": si_["id"]}, headers=H).get_json()["path"]).read_bytes()
c.post(f"/api/edit/{si_['id']}/save", json={"path": str(T / "imzali_kvkk.pdf")}, headers=H)
_first = lambda b: b[:b.index(b"%%EOF") + 5]   # dosyanın ilk bölümü (artımlı eklemelerden önceki hâli)
_leak = ["IMZALI" in pymupdf.open(stream=_first(b))[0].get_text()
         for b in (_dl, _sh, (T / "imzali_kvkk.pdf").read_bytes(), A.store.get(si_["id"]).path.read_bytes())]
c.post(f"/api/edit/{si_['id']}/undo", headers=H)
_undo = c.post(f"/api/edit/{si_['id']}/undo", headers=H).get_json()
check("E-imza: karartılınca belge baştan yazılır; imzalı bölümde de yazı kalmaz, sonraki değişiklik artımlı olmaz",
      not rd_["signed"] and not _after["signed"] and _leak == [False] * 4,
      (rd_["signed"], _after["signed"], _leak))
check("E-imza: Geri Al ile imzalı hâle dönülünce imza yine korunur", _undo["signed"], _undo.get("signed"))
(T / "imzali.pdf").unlink(); (T / "imzali_notlu.pdf").unlink(); (T / "imzali_kvkk.pdf").unlink()

# --- Farklı Kaydet: açık belge Word, UDF ya da resim olarak kopya kaydedilir; tek sayfa doğrudan resim olur
_pdf(T / "tek.pdf", "TEK SAYFA")
ts = c.post("/api/edit/open", json={"path": str(T / "tek.pdf")}, headers=H).get_json()
def _export(tool, **form):
    return c.post(f"/api/edit/{ts['id']}/tool/{tool}", data=form, headers=H, content_type="multipart/form-data").get_json()["files"][0]
png, docx, udf_ = _export("pdf-to-images", format="png", dpi="100"), _export("pdf-to-word"), _export("to-udf")
check("Farklı Kaydet: tek sayfa doğrudan PNG; Word ve UDF kopyası üretilir",
      png["name"].endswith(".png") and fetch(png)[:8] == b"\x89PNG\r\n\x1a\n" and docx["name"].endswith(".docx")
      and udf_["name"].endswith(".udf") and not c.get(f"/api/edit/{ts['id']}", headers=H).get_json()["unsaved"],
      [png.get("name"), docx.get("name"), udf_.get("name"), udf_.get("error")])
c.post(f"/api/edit/{ts['id']}/op", json={"op": "highlight", "page": 0, "rects": [[.1, .05, .3, .03]], "color": "#ffe14d"}, headers=H)
c.post(f"/api/edit/{ts['id']}/op", json={"op": "note", "page": 0, "x": .5, "y": .5, "text": "gizli not"}, headers=H)
ex = c.post(f"/api/edit/{ts['id']}/export", json={"flatten": True, "clean_meta": True, "password": "1234",
            "name": "tek (düzleştirilmiş, şifreli).pdf"}, headers=H).get_json()
xd = pymupdf.open(stream=fetch(ex))
locked = xd.needs_pass
xd.authenticate("1234")
check("Kaydetme seçenekleri: düzleştirilir (not ve vurgu silinemez), şifrelenir, bilgileri temizlenir",
      ex["name"] == "tek (düzleştirilmiş, şifreli).pdf" and locked and not list(xd[0].annots())
      and not xd.metadata.get("producer") and not xd.metadata.get("author")
      and len(c.get(f"/api/edit/{ts['id']}/annotations", headers=H).get_json()["annots"]) == 2, (ex.get("name"), locked, xd.metadata))
img = pymupdf.open(); ip = img.new_page()
ip.insert_image(ip.rect, pixmap=pymupdf.Pixmap(pymupdf.open(T / "deneme.pdf")[0].get_pixmap(dpi=200), 0))
img.save(T / "resimli.pdf"); img.close()
rs_ = c.post("/api/edit/open", json={"path": str(T / "resimli.pdf")}, headers=H).get_json()
small = c.post(f"/api/edit/{rs_['id']}/export", json={"shrink": True, "name": "resimli (küçültülmüş).pdf"}, headers=H).get_json()
check("Kaydetme seçenekleri: Küçült dosyayı küçültür", small["size"] < (T / "resimli.pdf").stat().st_size * 0.8,
      (small["size"], (T / "resimli.pdf").stat().st_size))
(T / "tek.pdf").unlink(); (T / "resimli.pdf").unlink()

# --- otomatik kurtarma: önceki çalışmadan kalan kaydedilmemiş belge listelenir, açılır ya da silinir
import editor as _ed, os as _os
_real_store, A.store = A.store, _ed.SessionStore(T / "oturum-deneme")
(T / "oturum-deneme").mkdir(exist_ok=True)
_pdf(T / "kurtar.pdf", "KURTARMA")
def _sess(change=True, close=False):
    j = c.post("/api/edit/open", json={"path": str(T / "kurtar.pdf")}, headers=H).get_json()
    if change:
        c.post(f"/api/edit/{j['id']}/op", json={"op": "rotate", "pages": [0], "angle": 90}, headers=H)
    if close:
        c.post(f"/api/edit/{j['id']}/close", headers=H)
    return j["id"]
unsaved, clean, closed, alive = _sess(), _sess(change=False), _sess(close=True), _sess()
def _previous_run(sid, pid=4194301):   # uygulama kapandı: oturum bellekten gider, işlem artık yok
    meta = json.loads((A.store.root / sid / "oturum.json").read_text()); meta["pid"] = pid
    (A.store.root / sid / "oturum.json").write_text(json.dumps(meta)); A.store.sessions.pop(sid)
for sid in (unsaved, clean, closed):
    _previous_run(sid)
_previous_run(alive, _os.getppid())   # başka bir açık uygulamanın oturumu
legacy = A.store.root / "eskioturum01"; legacy.mkdir(); _os.utime(legacy, (0, 0))
A.RECOVER_OFFERED = False
r1 = c.get("/api/recover?ilk=1", headers=H).get_json()
r2 = c.get("/api/recover?ilk=1", headers=H).get_json()
check("Kurtarma: yalnızca kaydedilmemiş ve kapatılmamış belge listelenir; pencere bir kez kendiliğinden açılır",
      [it["id"] for it in r1["items"]] == [unsaved] and r1["first"] and not r2["first"]
      and not (A.store.root / clean).exists() and not (A.store.root / closed).exists() and not legacy.exists()
      and (A.store.root / alive).exists(), r1)
ri = c.post(f"/api/recover/{unsaved}", headers=H).get_json()
check("Kurtarma: belge değişiklikleriyle açılır (kaydedilmemiş, Geri Al çalışır)",
      ri["unsaved"] and ri["canUndo"] and ri["pages"][0]["rot"] == 90
      and c.get("/api/recover", headers=H).get_json()["items"] == [], ri.get("pages"))
other = _sess(); _previous_run(other); A.store.scan()
c.post(f"/api/recover/{other}/discard", headers=H)
check("Kurtarma: silinen belgenin dosyaları gider", not (A.store.root / other).exists()
      and c.post("/api/recover/../../x/discard", headers=H).status_code in (400, 404))
A.store = _real_store
shutil.rmtree(T / "oturum-deneme"); (T / "kurtar.pdf").unlink()

# --- sorun bildir: rapor dosyası (not, sürüm, sistem, kayıt) ve e-posta bilgileri
rp = c.post("/api/report", json={"message": "Deneme notu: dönüştürme takıldı"}, headers=H).get_json()
rtext = Path(rp["path"]).read_text(encoding="utf-8")
check("Sorun bildir: rapor not, sürüm ve sistem bilgisiyle yazılır; ev klasörü yolu gizlenir",
      rp["to"] == "hasankoc1996@icloud.com" and "Deneme notu" in rp["body"] and "Deneme notu" in rtext
      and f"Sürüm: {A.SURUM} (geliştirme)" in rtext and "PyMuPDF" in rtext and str(Path.home()) not in rtext, rtext[:300])
Path(rp["path"]).unlink()

# --- otomatik güncelleme: surum.json okunur, kurulum dosyası indirilip parmak iziyle doğrulanır
import hashlib as _hl, time as _tm
import updater as _up
UPD = T / "guncelleme"; UPD.mkdir(exist_ok=True)
(UPD / "KocPDFPro.pkg").write_bytes(b"kurulum" * 5000)
_good = _hl.sha256((UPD / "KocPDFPro.pkg").read_bytes()).hexdigest()

def _manifest(version, sha):
    e = {"surum": version, "dosya": "KocPDFPro.pkg", "boyut": 35000, "sha256": sha}
    (UPD / "surum.json").write_text(json.dumps({"notlar": "Kaşe aracı", "mac": e, "windows": e}), encoding="utf-8")

def _wait(u):
    for _ in range(50):
        if u.state["status"] != "downloading":
            break
        _tm.sleep(0.1)
    return u.state

_old_base, _old_up = _up.BASE_URL, A.UPDATER
_up.BASE_URL = UPD.as_uri() + "/"
_manifest("1.0.202612010000", _good)
A.UPDATER = _up.Updater("1.0.202601010000", T / "indirilen")
r = c.get("/api/update", headers=H).get_json()
check("Güncelleme: daha yeni sürüm bildirilir", r["available"] and r["surum"] == "1.0.202612010000" and r["notlar"] == "Kaşe aracı", r)
c.post("/api/update/download", headers=H)
st = _wait(A.UPDATER)
check("Güncelleme: kurulum dosyası indirilip doğrulanır", st["status"] == "ready"
      and Path(st["path"]).read_bytes() == (UPD / "KocPDFPro.pkg").read_bytes(), st)
_manifest("1.0.202612020000", "0" * 64)
bad = _up.Updater("1.0.202601010000", T / "indirilen2"); bad.check(force=True); bad.download()
check("Güncelleme: parmak izi tutmayan dosya reddedilir", _wait(bad)["status"] == "error"
      and not any((T / "indirilen2").iterdir()), bad.state)
_manifest("1.0.202512010000", _good)
check("Güncelleme: eski ya da aynı sürüm bildirilmez", not _up.Updater("1.0.202601010000", T / "x").check()["available"])
check("Güncelleme: geliştirme sürümü denetlenmez", _up.Updater(None, T / "x").check() == {"available": False, "current": None})
A.UPDATER = _up.Updater("1.0.202601010000", T / "x")
r2 = c.post("/api/update/install", headers=H)
check("Güncelleme: indirilmeden kurulum başlatılmaz", r2.status_code == 400 and "indirin" in r2.get_json()["error"], r2.get_json())
_up.BASE_URL, A.UPDATER = _old_base, _old_up
shutil.rmtree(UPD); shutil.rmtree(T / "indirilen"); shutil.rmtree(T / "indirilen2", ignore_errors=True)

# ---- Format Değiştir: dosyalar bir kez alınır, kimlikleriyle dönüştürülür, seçilen klasöre birlikte kaydedilir
(T / "notlar.xyz").write_text("x")
r = c.post("/api/stage", data={"files": [(open(T / n, "rb"), n) for n in ("deneme.pdf", "deneme.docx", "resim.png", "notlar.xyz")]},
           headers=H, content_type="multipart/form-data"); st = r.get_json()
(T / "notlar.xyz").unlink()
sf = st["files"]
check("Format: yüklenen dosyalar türleriyle alınır", [f.get("kind") for f in sf[:3]] == ["pdf", "word", "image"]
      and sf[0]["pages"] >= 1 and sf[0]["thumb"].startswith("data:image/jpeg") and sf[2]["thumb"] and "thumb" not in sf[1], [f.get("kind") for f in sf])
check("Format: desteklenmeyen dosya bildirilir", "error" in sf[3] and st["desktop"], sf[3])
r = c.post("/api/stage", data={"files": [(io.BytesIO(b"%PDF-1.4 bozuk"), "bozuk.pdf")]}, headers=H, content_type="multipart/form-data")
check("Format: bozuk PDF eklenirken bildirilir", "bozuk" in r.get_json()["files"][0].get("error", ""), r.get_json())
r = c.post("/api/stage", json={"paths": [str(T / "deneme.udf")]}, headers=H).get_json()["files"][0]
check("Format: diskteki dosya klasörüyle alınır", r["kind"] == "udf" and r["dir"] == str(T) and r["name"] == "deneme.udf", r)
r = c.post("/api/stage", json={"paths": [str(T / "sifreli.pdf")]}, headers=H).get_json()["files"][0]
bad = c.post(f"/api/stage/{r['id']}/unlock", json={"password": "yanlis"}, headers=H).get_json()
good = c.post(f"/api/stage/{r['id']}/unlock", json={"password": "1234"}, headers=H).get_json()
check("Format: şifreli PDF şifresiyle açılır", r.get("encrypted") and bad == {"ok": False} and good["ok"] and good["pages"] >= 1
      and not pymupdf.open(A.staged_path(r["id"])).needs_pass, (r.get("encrypted"), bad, good.get("ok")))
oi = c.post("/api/edit/open", json={"path": str(T / "deneme.pdf")}, headers=H).get_json()
r = c.post("/api/stage", json={"sid": oi["id"]}, headers=H).get_json()["files"][0]
check("Format: açık belge eklenir", r["kind"] == "pdf" and r["name"] == "deneme.pdf" and r["dir"] == str(T), r["name"])
c.post(f"/api/edit/{oi['id']}/close", headers=H)
r, j = post("/api/convert/pdf-to-word", staged=sf[0]["id"])
docx = j["files"][0]
check("Format: alınan dosya kimliğiyle dönüştürülür", r.status_code == 200 and docx["name"] == "deneme.docx", j)
r, j = post("/api/convert/pdf-to-images", staged=sf[0]["id"], format="jpg")
imgs = j["files"][0]
names = zipfile.ZipFile(io.BytesIO(fetch(imgs))).namelist() if imgs["name"].endswith(".zip") else []
check("Format: sayfa resimlerinin adında iç önek yok", all(n.startswith("deneme_sayfa_") for n in names), names[:2])
check("Format: kaynak kopyası değişmeden kalır", len(list(A.staged_path(sf[0]["id"]).parent.iterdir())) == 1)
OUTD = T / "kayit"; shutil.rmtree(OUTD, ignore_errors=True); OUTD.mkdir()
a = c.post("/api/out/save-to", json={"dir": str(OUTD), "items": [{"id": docx["id"], "name": "Yeni ad"}]}, headers=H).get_json()
b = c.post("/api/out/save-to", json={"dir": str(OUTD), "items": [{"id": docx["id"], "name": "Yeni ad.docx"}]}, headers=H).get_json()
check("Format: tek dosya verilen adla, üzerine yazmadan", a["paths"] == [str(OUTD / "Yeni ad.docx")]
      and b["paths"] == [str(OUTD / "Yeni ad (1).docx")], (a, b))
m = c.post("/api/out/save-to", json={"dir": str(OUTD), "folder": "Dönüştürülmüş",
           "items": [{"id": docx["id"]}, {"id": imgs["id"], "unzip": True}]}, headers=H).get_json()
fold = OUTD / "Dönüştürülmüş"
check("Format: birden çok dosya klasörde, resimler alt klasörde", m["dir"] == str(fold) and (fold / "deneme.docx").is_file()
      and (not names or sorted(f.name for f in Path(m["paths"][1]).iterdir()) == sorted(names)), m)
r = c.post("/api/out/save-to", json={"dir": str(T / "yok"), "items": []}, headers=H)
check("Format: olmayan klasör reddedilir", r.status_code == 400)
shutil.rmtree(OUTD)

# ---- Sıkıştır penceresi: her düzeyin gerçek sonucu, hedef boyut, açık belgeye uygulama
_src = pymupdf.open(T / "deneme.pdf"); _scan = pymupdf.open()
for _p in _src:   # renkli, 300 dpi taranmış belge
    _pg = _scan.new_page(width=_p.rect.width, height=_p.rect.height)
    _pg.insert_image(_pg.rect, stream=_p.get_pixmap(dpi=300).tobytes("jpeg", jpg_quality=90))
    _pg.insert_text((72, 90), "Gizli metin katmani", render_mode=3)   # metin tanıma katmanı gibi
_scan.save(T / "tarama.pdf"); _scan.close()
sk = c.post("/api/stage", json={"paths": [str(T / "tarama.pdf")]}, headers=H).get_json()["files"][0]
lv = {l: c.post("/api/compress", json={"id": sk["id"], "level": l}, headers=H).get_json() for l in ("dusuk", "orta", "yuksek")}
check("Sıkıştır: düzeyler küçükten büyüğe", lv["orta"]["after"] < lv["dusuk"]["after"] <= lv["dusuk"]["before"]
      and lv["yuksek"]["after"] < lv["orta"]["after"] and lv["orta"]["note"] == "2 resim küçültüldü"
      and lv["orta"]["level_name"] == "Önerilen", {k: (v["after"], v["note"]) for k, v in lv.items()})
again = c.post("/api/compress", json={"id": sk["id"], "level": "orta"}, headers=H).get_json()
check("Sıkıştır: aynı düzey yeniden sıkıştırılmaz", again["id"] == lv["orta"]["id"])
big = c.post("/api/compress", json={"id": sk["id"], "target": lv["dusuk"]["after"] + 10}, headers=H).get_json()
mid = c.post("/api/compress", json={"id": sk["id"], "target": lv["orta"]["after"] - 1}, headers=H).get_json()
tiny = c.post("/api/compress", json={"id": sk["id"], "target": 1000}, headers=H).get_json()
check("Sıkıştır: hedef boyuta inen en kaliteli düzey", big["level"] == "dusuk" and big["reached"]
      and mid["level"] in ("ara", "yuksek") and mid["reached"] and mid["after"] < lv["orta"]["after"], (big["level"], mid["level"]))
check("Sıkıştır: hedefe inilemezse en küçük sonuç", not tiny["reached"] and tiny["level"] == "en-yuksek", (tiny["level"], tiny["after"]))
sb = c.post("/api/compress", json={"id": sk["id"], "level": "orta", "color": "sb"}, headers=H).get_json()
gr = c.post("/api/compress", json={"id": sk["id"], "level": "orta", "color": "gri"}, headers=H).get_json()
_sbd, _grd = pymupdf.open(stream=fetch(sb)), pymupdf.open(stream=fetch(gr))
_info = _sbd[0].get_images(full=True)[0]
check("Sıkıştır: siyah-beyaz taranmış sayfa", sb["after"] < lv["orta"]["after"] / 3 and _info[4] == 1 and _info[2] < 2000
      and "2 taranmış sayfa siyah-beyaz" in sb["note"] and "Gizli metin" in _sbd[0].get_text(), (sb["after"], _info[2:5], sb["note"]))
check("Sıkıştır: gri", gr["note"].startswith("Belge gri yapıldı") and pymupdf.Pixmap(_grd, _grd[0].get_images()[0][0]).n == 1
      and gr["id"] != lv["orta"]["id"], gr["note"])
_a = c.get(f"/api/compress/page?src={sk['id']}&page=1&zoom=1", headers=H)
_b = c.get(f"/api/compress/page?out={lv['yuksek']['id']}&page=1&zoom=1", headers=H)
_pa, _pb = pymupdf.Pixmap(_a.data), pymupdf.Pixmap(_b.data)
check("Sıkıştır: önce / sonra sayfası aynı boyutta", _a.mimetype == "image/png" and (_pa.width, _pa.height) == (_pb.width, _pb.height)
      and _pa.width == 612 and sk["image_page"] == 0, (_pa.width, _pb.width))
# ek dosya, belge bilgisi, sayfa küçük resmi ve e-imza
_ek = pymupdf.open(); _ep = _ek.new_page(); _ep.insert_text((72, 72), "Ekli belge")
_ek.embfile_add("dekont.bin", os.urandom(300_000), filename="dekont.bin")
_ek.set_metadata({"author": "Av. Deneme", "producer": "Tarayici 3000"})
_tx = _ek.get_new_xref()
_ek.update_object(_tx, "<< /Type /XObject /Subtype /Image /Width 2 /Height 2 /BitsPerComponent 8 /ColorSpace /DeviceGray >>")
_ek.update_stream(_tx, b"\x00\xff\xff\x00"); _ek.xref_set_key(_ep.xref, "Thumb", f"{_tx} 0 R")
_sw = pymupdf.Widget(); _sw.field_type = pymupdf.PDF_WIDGET_TYPE_SIGNATURE; _sw.field_name = "Imza"
_sw.rect = pymupdf.Rect(60, 700, 260, 740); _ep.add_widget(_sw)
_ek.save(T / "ekli.pdf"); _ek.close(); imzala(T / "ekli.pdf")
ek = c.post("/api/stage", json={"paths": [str(T / "ekli.pdf")]}, headers=H).get_json()["files"][0]
keep = c.post("/api/compress", json={"id": ek["id"], "level": "dusuk"}, headers=H).get_json()
gone = c.post("/api/compress", json={"id": ek["id"], "level": "dusuk", "drop": ["attachments", "meta", "kotu"]}, headers=H).get_json()
_kd, _gd = pymupdf.open(stream=fetch(keep)), pymupdf.open(stream=fetch(gone))
check("Sıkıştır: e-imza ve ek dosyalar bildirilir", ek["signed"] and ek["attachments"][0] == 1 and ek["attachments"][1] > 290_000, ek.get("attachments"))
check("Sıkıştır: sayfa küçük resmi her zaman, ek dosya ve bilgiler isteyince kaldırılır",
      _kd.embfile_count() == 1 and _kd.metadata["author"] == "Av. Deneme" and _kd.xref_get_key(_kd[0].xref, "Thumb")[0] == "null"
      and _gd.embfile_count() == 0 and not _gd.metadata["author"] and gone["after"] < 50_000
      and gone["note"] == "1 ek dosya kaldırıldı · belge bilgileri temizlendi · 1 sayfa küçük resmi kaldırıldı", (keep["note"], gone["note"]))
(T / "ekli.pdf").unlink()
oi = c.post("/api/edit/open", json={"path": str(T / "tarama.pdf")}, headers=H).get_json()
st = c.post("/api/stage", json={"sid": oi["id"]}, headers=H).get_json()["files"][0]
res = c.post("/api/compress", json={"id": st["id"], "level": "yuksek"}, headers=H).get_json()
bad = c.post(f"/api/edit/{oi['id']}/apply-output", json={"out": res["id"], "rev": "baska"}, headers=H)
info = c.post(f"/api/edit/{oi['id']}/apply-output", json={"out": res["id"], "rev": st["rev"]}, headers=H).get_json()
check("Sıkıştır: sonuç açık belgeye uygulanır", bad.status_code == 400 and info["unsaved"] and info["canUndo"]
      and len(info["pages"]) == 2, (bad.status_code, info.get("unsaved"), info.get("canUndo")))
c.post(f"/api/edit/{oi['id']}/close", headers=H)
(T / "tarama.pdf").unlink()

# ---- Böl: 10'dan çok parça sayfa sırasıyla; parçalar kendi yer imlerini korur
_bd = pymupdf.open()
for _i in range(12):
    _bd.new_page().insert_text((72, 72), f"Sayfa {_i + 1}")
_bd.set_toc([[1, "Dilekçe", 1], [2, "Olaylar", 2], [1, "Ek-1 Vekaletname", 5], [1, "Ek-2 Rapor", 9], [2, "Sonuç", 11]])
_bd.save(T / "bolunecek.pdf"); _bd.close()
r, j = post("/api/tool/split", [T / "bolunecek.pdf"], mode="each")
check("Böl: 12 parça sayfa sırasıyla", [f["name"] for f in j["files"]] == [f"bolunecek_sayfa_{i}.pdf" for i in range(1, 13)],
      [f["name"] for f in j["files"]][:4])
r, j = post("/api/tool/split", [T / "bolunecek.pdf"], mode="ranges", spec="1-4, 9-12")
_t1, _t2 = (pymupdf.open(stream=fetch(f)).get_toc() for f in j["files"])
check("Böl: parçalar kendi yer imlerini korur", _t1 == [[1, "Dilekçe", 1], [2, "Olaylar", 2]]
      and _t2 == [[1, "Ek-2 Rapor", 1], [2, "Sonuç", 3]], (_t1, _t2))
bs = c.post("/api/stage", json={"paths": [str(T / "bolunecek.pdf")]}, headers=H).get_json()["files"][0]
_th = c.get(f"/api/stage/{bs['id']}/page/3?w=120", headers=H)
check("Böl: sayfa küçük resmi", _th.mimetype == "image/jpeg" and pymupdf.Pixmap(_th.data).width == 120 and bs["pages"] == 12)
j = c.post("/api/split", json={"id": bs["id"], "parts": [{"pages": [0, 1, 2, 3], "name": "Dilekçe"},
                                                      {"pages": [8, 10, 11], "name": "Ek: 2.pdf"}]}, headers=H).get_json()
_p2 = pymupdf.open(stream=fetch(j["files"][1]))
check("Böl: parçalar verilen adlarla, kendi yer imleriyle", [f["name"] for f in j["files"]] == ["Dilekçe.pdf", "Ek_ 2.pdf"]
      and _p2.page_count == 3 and _p2.get_toc() == [[1, "Ek-2 Rapor", 1], [2, "Sonuç", 2]] and "Sayfa 12" in _p2[2].get_text(),
      ([f["name"] for f in j["files"]], _p2.get_toc()))
r = c.post("/api/split", json={"id": bs["id"], "parts": [{"pages": [12]}]}, headers=H)
check("Böl: olmayan sayfa reddedilir", r.status_code == 400 and "1. parçanın" in r.get_json()["error"])
pl = c.post("/api/split/plan", json={"id": bs["id"], "mode": "toc"}, headers=H).get_json()
check("Böl: yer imlerine göre en üst başlıklar", bs["bookmarks"] == 5 and pl["cuts"] == [3, 7]
      and pl["names"] == {"0": "Dilekçe", "4": "Ek-1 Vekaletname", "8": "Ek-2 Rapor"} and "3 başlık" in pl["note"], pl)
_nb = c.post("/api/stage", json={"paths": [str(T / "deneme.pdf")]}, headers=H).get_json()["files"][0]
r = c.post("/api/split/plan", json={"id": _nb["id"], "mode": "toc"}, headers=H)
check("Böl: içindekiler yoksa söylenir", r.status_code == 400 and "içindekiler" in r.get_json()["error"] and _nb["bookmarks"] == 0)
_bt = pymupdf.open()
for _i in range(12):   # her sayfada farklı, sıkışmayan bir resim (~250 KB)
    _pix = pymupdf.Pixmap(pymupdf.csRGB, 300, 280, os.urandom(300 * 280 * 3), 0)
    _bt.new_page().insert_image(pymupdf.Rect(0, 0, 595, 842), stream=_pix.tobytes("png"))
_bt.save(T / "boyut.pdf", deflate=True); _bt.close()
bz = c.post("/api/stage", json={"paths": [str(T / "boyut.pdf")]}, headers=H).get_json()["files"][0]
_whole = (T / "boyut.pdf").stat().st_size
_lim = _whole // 3
pz = c.post("/api/split/plan", json={"id": bz["id"], "mode": "size", "limit": _lim}, headers=H).get_json()
_starts = [0] + [x + 1 for x in pz["cuts"]]
_parts = [list(range(a, b)) for a, b in zip(_starts, _starts[1:] + [12])]
jz = c.post("/api/split", json={"id": bz["id"], "parts": [{"pages": pg, "name": f"p{k}"} for k, pg in enumerate(_parts)]}, headers=H).get_json()
check("Böl: boyuta göre her parça sınırın altında, sayfa sırası bozulmadan", 3 <= len(_parts) <= 5 and sum(map(len, _parts)) == 12
      and all(f["size"] <= _lim for f in jz["files"]) and all(pz["sizes"][str(pg[0])] <= _lim for pg in _parts),
      (_lim, pz["cuts"], [f["size"] for f in jz["files"]]))
(T / "boyut.pdf").unlink()
_bb = pymupdf.open()
for _i in range(9):
    _pg = _bb.new_page()
    if _i == 3:
        continue   # tamamen boş
    if _i == 6:   # taranmış boş kâğıt: açık gri, kenarında tarayıcı gölgesi
        _pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 620, 877), 0)
        _pix.set_rect(_pix.irect, (236,)); _pix.set_rect(pymupdf.IRect(0, 0, 18, 877), (40,))
        _pg.insert_image(_pg.rect, pixmap=_pix)
        continue
    _pg.insert_text((72, 72), f"Belge sayfasi {_i + 1}")
_bb.save(T / "bosluklu.pdf"); _bb.close()
bb = c.post("/api/stage", json={"paths": [str(T / "bosluklu.pdf")]}, headers=H).get_json()["files"][0]
pb = c.post("/api/split/plan", json={"id": bb["id"], "mode": "blank"}, headers=H).get_json()
check("Böl: boş sayfalara göre (taranmış boş kâğıt da)", pb.get("skip") == [3, 6] and pb["cuts"] == [2, 3, 5, 6]
      and "2 boş sayfa" in pb["note"], pb)
r = c.post("/api/split/plan", json={"id": bs["id"], "mode": "blank"}, headers=H)
check("Böl: boş sayfa yoksa söylenir", r.status_code == 400 and "Boş sayfa bulunamadı" in r.get_json()["error"])
(T / "bosluklu.pdf").unlink()
(T / "bolunecek.pdf").unlink()   # Böl testleri sonu

_si = c.post("/api/edit/open", json={"path": str(T / "deneme.pdf")}, headers=H).get_json()
check("Durum çubuğu: belge bilgisinde boyut", _si["size"] == (A.store.get(_si["id"]).path).stat().st_size > 1000, _si.get("size"))
c.post(f"/api/edit/{_si['id']}/close", headers=H)

# ---- Ayarlar: seçimler ayarlar.json'a yazılır, geçersizi reddedilir; yedek ve kurtarma süreleri hemen uygulanır
_real_settings, A.ayarlar.SETTINGS_FILE = A.ayarlar.SETTINGS_FILE, T / "ayarlar-deneme.json"
g = c.get("/api/settings", headers=H).get_json()
check("Ayarlar: varsayılanlar ve Masaüstü yolu", g["settings"] == A.ayarlar.SETTINGS_DEFAULTS and g["desktop"], g)
r = c.post("/api/settings", json={"saveFolder": "desktop", "recoverDays": 14, "resumePage": False}, headers=H)
check("Ayarlar: kaydedilir ve uygulanır", r.status_code == 200 and A.ayarlar.read_settings()["saveFolder"] == "desktop"
      and A.editor.RECOVER_DAYS == 14 and r.get_json()["settings"]["resumePage"] is False, r.get_json())
bad = [c.post("/api/settings", json=b, headers=H).status_code
       for b in ({"recoverDays": True}, {"backupKeep": 4}, {"bilinmeyen": 1}, {"saveFolder": "/etc"})]
check("Ayarlar: geçersiz değer ve bilinmeyen ad reddedilir", bad == [400] * 4 and A.ayarlar.read_settings()["recoverDays"] == 14, bad)
A.ayarlar.SETTINGS_FILE.write_text("bozuk", encoding="utf-8")
check("Ayarlar: bozuk dosyada varsayılanlar", A.ayarlar.read_settings() == A.ayarlar.SETTINGS_DEFAULTS)
_real_backups, A.yedekler.BACKUPS = A.yedekler.BACKUPS, T / "yedek-ayar"
A.yedekler.BACKUPS.mkdir(exist_ok=True)
for k in range(6):
    day = _tm2.strftime("%Y%m%d", _tm2.localtime(_tm2.time() - (k + 1) * 86400))
    (A.yedekler.BACKUPS / f"ayar_abcdef12_{day}-120000.pdf").write_bytes(b"x")
n = c.get("/api/backups/prune-preview", query_string={"keep": 3, "days": 60}, headers=H).get_json()["count"]
check("Ayarlar: yedek sınırı düşerken silinecekler önceden sayılır (silinmez)", n == 3 and len(list(A.yedekler.BACKUPS.glob("*"))) == 6, n)
c.post("/api/settings", json={"backupKeep": 3}, headers=H)
check("Ayarlar: yedek sınırı kaydedilince fazlası silinir", len(list(A.yedekler.BACKUPS.glob("*"))) == 3 and A.yedekler.BACKUP_KEEP == 3)
st = c.get("/api/storage", headers=H).get_json()
check("Depolama: önceki sürümlerin sayısı ve boyutu", st["backup_count"] == 3 and st["backups"] == 3, st)
old_dir, new_dir = A.UPLOADS / "ayar_eski", A.OUTPUTS / "ayar_yeni"
old_dir.mkdir(exist_ok=True); (old_dir / "a").write_bytes(b"x" * 100)
new_dir.mkdir(exist_ok=True); (new_dir / "b").write_bytes(b"x" * 100)
os.utime(old_dir, (_tm2.time() - 3600, _tm2.time() - 3600))
st = c.post("/api/storage/clean", json={"what": "temp"}, headers=H).get_json()
check("Depolama: geçici dosyalar temizlenir, son 15 dakikada kullanılanlar kalır",
      not old_dir.exists() and new_dir.exists() and st["temp"] >= 100, st)
st = c.post("/api/storage/clean", json={"what": "backups"}, headers=H).get_json()
check("Depolama: önceki sürümlerin hepsi silinir", st["backup_count"] == 0 and not list(A.yedekler.BACKUPS.glob("*")), st)
check("Depolama: ne silineceği belirtilmezse reddedilir", c.post("/api/storage/clean", json={}, headers=H).status_code == 400)
shutil.rmtree(new_dir); A.yedekler.BACKUPS.rmdir(); A.yedekler.BACKUPS = _real_backups
# notlarda yazar adı: kaydedilir (boşluklar toparlanır), yeni not ve işaretlere PDF'in yazar alanı (T) olarak yazılır
r = c.post("/api/settings", json={"author": "  Av.  Ayşe\nDemir "}, headers=H)
too_long = c.post("/api/settings", json={"author": "x" * 61}, headers=H).status_code
check("Ayarlar: ad tek satıra toparlanır, 60 harften uzunu reddedilir",
      r.get_json()["settings"]["author"] == "Av. Ayşe Demir" and A.editor.AUTHOR == "Av. Ayşe Demir" and too_long == 400, r.get_json())
_as = c.post("/api/edit/open", json={"path": str(T / "deneme.pdf")}, headers=H).get_json()
c.post(f"/api/edit/{_as['id']}/op", json={"op": "note", "page": 0, "x": 0.5, "y": 0.5, "text": "Yazarlı"}, headers=H)
c.post(f"/api/edit/{_as['id']}/op", json={"op": "highlight", "page": 0, "rects": [[0.1, 0.1, 0.3, 0.03]], "note": "İşaret"}, headers=H)
c.post(f"/api/edit/{_as['id']}/op", json={"op": "annotate", "page": 0, "items": [{"type": "highlight", "x": 0.1, "y": 0.4, "w": 0.2, "h": 0.03}]}, headers=H)
c.post("/api/settings", json={"author": ""}, headers=H)
c.post(f"/api/edit/{_as['id']}/op", json={"op": "note", "page": 0, "x": 0.6, "y": 0.6, "text": "Adsız"}, headers=H)
_an = c.get(f"/api/edit/{_as['id']}/annotations", headers=H).get_json()["annots"]
_saved = pymupdf.open(A.store.get(_as["id"]).path)
check("Notlar: yazar adı yeni not ve işaretlere yazılır; ad boşsa yazılmaz, notun metni korunur",
      [(a["content"], a["author"]) for a in _an] == [("Yazarlı", "Av. Ayşe Demir"), ("İşaret", "Av. Ayşe Demir"),
                                                       ("", "Av. Ayşe Demir"), ("Adsız", "")]
      and {a.info["title"] for a in _saved[0].annots()} == {"Av. Ayşe Demir", ""}, _an)
c.post(f"/api/edit/{_as['id']}/close", headers=H)
A.ayarlar.SETTINGS_FILE.unlink(); A.ayarlar.SETTINGS_FILE = _real_settings
A.ayarlar.apply_settings(A.ayarlar.read_settings())

# --- açık belge: sayfa yokladıkça oturum silinmez; yoklanmayan (sekmesi kapatılmış) oturum saatler sonra silinir
_oa = c.post("/api/edit/open", json={"path": str(T / "deneme.pdf")}, headers=H).get_json()["id"]
_ob = c.post("/api/edit/open", json={"path": str(T / "deneme.pdf")}, headers=H).get_json()["id"]
for _o in (_oa, _ob):
    A.store.sessions[_o].touched -= 7 * 3600
_touch = c.post(f"/api/edit/{_oa}/touch", headers=H).status_code
A.store.cleanup()
check("Oturum: yoklanan açık belge kalır, 6 saattir yoklanmayan silinir",
      _touch == 200 and _oa in A.store.sessions and _ob not in A.store.sessions, (_touch, _oa in A.store.sessions, _ob in A.store.sessions))
A.store.sessions[_oa].touched -= 7 * 3600
A.store.touch_all(); A.store.cleanup()
check("Oturum: bilgisayar uykudan uyanınca açık belgeler hemen silinmez", _oa in A.store.sessions)

# --- kullanım kılavuzu PDF: başlıklar yer imi, iç bağlantılar sayfaya gider, resimler sayfa sonunda küçülmez,
# renkli kutular sonraki sayfalara şerit bırakmaz; Windows'ta kısayollar Ctrl / Shift
import kilavuz as _kv
_kdir = A.BASE / "static" / "kilavuz"
_ksrc = (_kdir / "kilavuz.html").read_text(encoding="utf-8")
r = c.post("/api/kilavuz/pdf", headers=H)
_kj = r.get_json()
_kd = pymupdf.open(stream=fetch(_kj))
_klinks = [l for pg in _kd for l in pg.get_links()]
_kwidths = _kv._prepare(_ksrc, _kdir, pymupdf.Archive())[1]
check("Kılavuz: PDF'te bütün başlıklar yer imi, iç bağlantılar sayfaya gider, ekran görüntüleri tam boy",
      r.status_code == 200 and _kj["name"] == "Koç PDF Pro Kullanım Kılavuzu.pdf"
      and [t[1] for t in _kd.get_toc()] == [h[2] for h in _kv.headings(_ksrc)]
      and _klinks and all(l["kind"] == pymupdf.LINK_GOTO and 0 <= l["page"] < _kd.page_count for l in _klinks)
      and len(_kwidths) == _ksrc.count("<figure") and not _kv._shrunk(_kd, _kwidths)
      and all(d["rect"].y0 >= _kv.BODY.y0 - 1 for pg in _kd for d in pg.get_drawings()), (_kj, _kd.page_count))
_kw = A.new_output("kilavuz-windows.pdf")
_kv.build_pdf(_ksrc, _kdir, _kw, None, windows=True)
_kmac = "".join(pg.get_text() for pg in _kd)
_kwin = "".join(pg.get_text() for pg in pymupdf.open(_kw))
check("Kılavuz: Windows'ta ⌘ ⇧ ⌃ yerine Ctrl / Shift, Finder yerine Dosya Gezgini",
      "⌘S" in _kmac and not any(k in _kwin for k in "⌘⇧⌃⌥") and "Ctrl+Shift+S" in _kwin and "Ctrl+Tab" in _kwin
      and "Dosya Gezgini'nde" in _kwin, [k for k in "⌘⇧⌃⌥" if k in _kwin])

print("\nSONUÇ:", "TÜMÜ GEÇTİ" if ok else "HATA VAR")
sys.exit(0 if ok else 1)   # betik ya da otomasyon başarısızlığı çıkış kodundan anlasın
