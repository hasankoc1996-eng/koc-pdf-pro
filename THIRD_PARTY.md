# Üçüncü taraf bileşenler

Koç PDF Pro aşağıdaki açık kaynak bileşenleri kullanır. Kurulum paketleri bunları içerir; her biri kendi lisansıyla
dağıtılır ve lisans metinleri paketteki kütüphane klasörlerinde (`*.dist-info`) ve proje sayfalarında bulunur.
Kesin sürümler ve dosyaların SHA-256 parmak izleri: `packaging/bagimliliklar/mac.txt` ve `windows.txt`.

## Uygulamanın kullandıkları (Mac ve Windows)

| Bileşen | Sürüm | Lisans | Ne için |
|---|---|---|---|
| [PyMuPDF](https://github.com/pymupdf/PyMuPDF) ve içindeki [MuPDF](https://mupdf.com) | 1.28.2 | AGPL-3.0 (Artifex; ticari lisans seçeneği de var) | PDF okuma, çizme, düzenleme |
| [pdf2docx](https://github.com/ArtifexSoftware/pdf2docx) | 0.5.13 | MIT | PDF → Word |
| [python-docx](https://github.com/python-openxml/python-docx) | 1.2.0 | MIT | Word belgeleri |
| [openpyxl](https://openpyxl.readthedocs.io) · et-xmlfile | 3.1.5 · 2.0.0 | MIT | Excel belgeleri |
| [Flask](https://github.com/pallets/flask) · Werkzeug · Jinja2 · MarkupSafe · itsdangerous · click | 3.1.3 · 3.1.9 · 3.1.6 · 3.0.4 · 2.2.0 · 8.5.0 | BSD-3-Clause | uygulamanın iç sunucusu |
| [blinker](https://github.com/pallets-eco/blinker) | 1.9.0 | MIT | Flask'ın bağımlılığı |
| [Pillow](https://python-pillow.github.io) | 12.3.0 | MIT-CMU (içindeki libjpeg, libpng, libtiff, libwebp, FreeType, zlib vb. kendi lisanslarıyla) | resimler |
| [pi-heif](https://github.com/bigcat88/pillow_heif) | 1.4.0 | LGPL-3.0 (içindeki libheif, libde265 de LGPL-3.0) | iPhone fotoğrafları (HEIC) |
| [fontTools](https://github.com/fonttools/fonttools) | 4.67.0 | MIT | yazı tipi küçültme |
| [lxml](https://lxml.de) | 6.1.3 | BSD-3-Clause (içindeki libxml2, libxslt MIT) | XML (Word, UDF) |
| [NumPy](https://numpy.org) | 2.5.4 | BSD-3-Clause ve diğerleri (0BSD, MIT, Zlib, CC0-1.0) | pdf2docx'in bağımlılığı |
| [opencv-python-headless](https://github.com/opencv/opencv-python) | 5.0.0.93 | Apache-2.0 (içindeki üçüncü taraf kitaplıklar kendi lisanslarıyla) | pdf2docx'in bağımlılığı |
| [python-fire](https://github.com/google/python-fire) · [termcolor](https://github.com/termcolor/termcolor) | 0.7.1 · 3.3.0 | Apache-2.0 · MIT | pdf2docx'in bağımlılıkları |
| [typing_extensions](https://github.com/python/typing_extensions) | 4.16.0 | PSF-2.0 | bağımlılık |
| [Python](https://www.python.org) ve standart kitaplığı | 3.13.16 | PSF-2.0 (içindeki OpenSSL, zlib, libffi, SQLite vb. kendi lisanslarıyla) | çalışma ortamı |

## Yalnızca Windows paketinde

| Bileşen | Sürüm | Lisans | Ne için |
|---|---|---|---|
| [pywebview](https://pywebview.flowrl.com) · proxy-tools · bottle | 6.2.1 · 0.1.0 · 0.13.4 | BSD-3-Clause · MIT · MIT | uygulama penceresi (Windows'un WebView2 bileşeniyle) |
| [pythonnet](https://pythonnet.github.io) · clr-loader | 3.2.1 · 0.3.1 | MIT | pywebview'in bağımlılıkları |
| [cffi](https://github.com/python-cffi/cffi) · pycparser | 2.1.1 · 3.11 | MIT-0 · BSD-3-Clause | bağımlılıklar |
| [comtypes](https://github.com/enthought/comtypes) | 1.4.17 | MIT | Word / Excel / Outlook otomasyonu |
| [colorama](https://github.com/tartley/colorama) | 0.4.6 | BSD-3-Clause | bağımlılık |
| [PyWinRT](https://github.com/pywinrt/pywinrt) (winrt-runtime, winrt-Windows.*) | 3.2.1 | MIT | Windows'un yerleşik metin tanıması |
| Microsoft Visual C++ çalışma zamanı (msvcp140*.dll, [msvc-runtime](https://pypi.org/project/msvc-runtime/) paketinden) | 14.44 | Microsoft Visual C++ Redistributable lisansı (uygulamayla dağıtılmasına izin verilir) | PDF kitaplığının gereksinimi |

Kurulum programı [NSIS](https://nsis.sourceforge.io) ile üretilir (zlib/libpng lisansı).

## Yalnızca Mac paketinde

| Bileşen | Sürüm | Lisans | Ne için |
|---|---|---|---|
| [PyInstaller](https://pyinstaller.org) · pyinstaller-hooks-contrib | 6.22.3 · 2026.8 | GPL-2.0, önyükleyici istisnasıyla (paketlenen uygulama kendi lisansıyla dağıtılabilir) · Apache-2.0 / GPL-2.0 | iç sunucuyu tek klasöre dönüştürme |
| altgraph · macholib · packaging · setuptools | 0.17.5 · 1.16.4 · 26.3 · 84.0.0 | MIT · MIT · Apache-2.0 veya BSD-2-Clause · MIT | PyInstaller'ın bağımlılıkları |

## Paketlenmeyenler

Uygulama işletim sisteminin bileşenlerini kullanır, bunları dağıtmaz: Mac'te WebKit ve Vision (metin tanıma),
Windows'ta WebView2 ve Windows.Media.Ocr; Word / Excel dönüştürmelerinde bilgisayarda kurulu Microsoft Word, Excel ya
da LibreOffice; PDF'e yazılan metinlerde sistemin yazı tipleri.
