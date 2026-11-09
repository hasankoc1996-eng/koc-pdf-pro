# PyInstaller tarifi: Koç PDF Pro sunucusunu (app.py) Python kurulumu gerektirmeyen tek klasöre dönüştürür.
# Kullanım: .venv/bin/pyinstaller packaging/server.spec --distpath packaging/dist --workpath packaging/build
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

# make_dmg.sh, sürüm bilgisi eklenmiş bir kopyayı KOCPDF_SRC ile verir; yoksa proje klasörü kullanılır
ROOT = Path(os.environ.get("KOCPDF_SRC") or Path(SPECPATH).parent)

a = Analysis(
    [str(ROOT / "app.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "static"), "static"), (str(ROOT / "scripts"), "scripts")],
    # pdf2docx yalnızca PDF→Word sırasında içe aktarılıyor; PyMuPDF yazı tipi küçültme için fontTools'u kullanıyor
    hiddenimports=collect_submodules("pdf2docx") + collect_submodules("fontTools.subset") + ["fontTools.ttLib"],
    excludes=["tkinter", "matplotlib", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="kocpdf-server", console=True,
          target_arch="arm64", codesign_identity=None)
coll = COLLECT(exe, a.binaries, a.datas, name="server")
