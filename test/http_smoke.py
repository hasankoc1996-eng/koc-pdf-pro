"""Çalışan bir Koç PDF Pro sunucusunu HTTP üzerinden dener (paketlenmiş sürümü test etmek için).
Kullanım: python3 test/http_smoke.py 5077"""
import json, subprocess, sys
from urllib.parse import quote
from pathlib import Path

PORT = sys.argv[1] if len(sys.argv) > 1 else "5055"
BASE = f"http://127.0.0.1:{PORT}"
T = Path(__file__).parent
ok = True

KEY_FILE = Path.home() / "Library/Caches/PDFStudyo/oturum"   # paketlenmiş motorun uygulama anahtarı

def curl(*args):
    # Kurulum paketindeki motor yalnızca anahtarı bilen pencereye cevap verir: anahtar çerezle iletilir
    cookie = ["-H", f"Cookie: kpa={KEY_FILE.read_text().strip()}"] if KEY_FILE.exists() else []
    out = subprocess.run(["curl", "-s", "-m", "120", *cookie, *args], capture_output=True)
    return out.stdout

def post_files(url, files, **form):
    args = []
    for f in files: args += ["-F", f"files=@{f}"]
    for k, v in form.items(): args += ["-F", f"{k}={v}"]
    return json.loads(curl(*args, BASE + url))

def post_json(url, body):
    return json.loads(curl("-H", "Content-Type: application/json", "-d", json.dumps(body), BASE + url))

def check(name, cond, extra=""):
    global ok
    ok &= bool(cond)
    print(("✅" if cond else "❌"), name, extra if not cond else "")

check("arayüz", b"Ko\xc3\xa7 PDF Pro" in curl(BASE + "/"))
check("logo", len(curl(BASE + "/static/logo.png")) > 10000)
r = post_files("/api/convert/word-to-pdf", [T / "deneme.docx"]); check("Word→PDF", "error" not in r["files"][0], r)
r = post_files("/api/convert/pdf-to-word", [T / "deneme.pdf"]); check("PDF→Word (pdf2docx)", "error" not in r["files"][0], r)
r = post_files("/api/convert/pdf-to-images", [T / "deneme.pdf"], format="png"); check("PDF→Resim", "error" not in r["files"][0], r)
r = post_files("/api/tool/merge", [T / "deneme.pdf", T / "deneme.pdf"]); check("Birleştir", "error" not in r["files"][0], r)
merged = r["files"][0]["url"]
r = post_files("/api/tool/compress", [T / "deneme.pdf"], level="yuksek"); check("Sıkıştır", "error" not in r["files"][0], r)
r = post_files("/api/tool/watermark", [T / "deneme.pdf"], text="GİZLİ"); check("Filigran (Türkçe font)", "error" not in r["files"][0], r)
r = post_files("/api/tool/protect", [T / "deneme.pdf"], password="1234"); check("Şifrele", "error" not in r["files"][0], r)
info = post_json("/api/edit/open", {"path": str(T / "deneme.pdf")}); check("Okuyucu: yoldan aç", len(info.get("pages", [])) == 2, info)
sid = info["id"]
check("Sayfa görüntüsü", curl(f"{BASE}/api/edit/{sid}/page/0?w=400")[:4] == b"\x89PNG")
lines = json.loads(curl(f"{BASE}/api/edit/{sid}/lines/0"))["lines"]; check("Metin satırları", len(lines) > 5)
hits = json.loads(curl(f"{BASE}/api/edit/{sid}/search?q={quote('satır')}"))["hits"]; check("Arama", len(hits) > 0)
r = post_json(f"/api/edit/{sid}/op", {"op": "page_edit", "page": 0, "items": [
    {"type": "text", "x": .1, "y": .05, "w": .5, "h": .04, "text": "Paket testi şğı", "size": 12, "color": "#000000"}],
    "edits": [dict(lines[3], text="Değiştirilmiş satır")]})
check("Düzenleme", "error" not in r, r)
pdf = curl(f"{BASE}/api/edit/{sid}/download"); check("İndir (font küçültme)", pdf[:4] == b"%PDF" and len(pdf) > 5000)
r = post_files("/api/convert/udf-to-pdf", [T / "deneme.udf"]); check("UDF→PDF", "error" not in r["files"][0], r)
r = post_files("/api/convert/to-udf", [T / "deneme.docx"]); check("Word→UDF", "error" not in r["files"][0], r)
print("\nSONUÇ:", "TÜMÜ GEÇTİ" if ok else "HATA VAR")
sys.exit(0 if ok else 1)   # betik ya da otomasyon başarısızlığı çıkış kodundan anlasın
