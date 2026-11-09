/* Koç PDF Pro — araç tanımları, araç sayfası (dosya seçme, seçenekler, çalıştırma) ve sonuçlar. */
'use strict';

// ------------------------------------------------------------------ araç tanımları
const WORD_ACCEPT = '.doc,.docx,.rtf,.odt,.txt,.docm,.dotx';
const EXCEL_ACCEPT = '.xlsx,.xls,.xlsm,.csv,.ods';
const IMG_ACCEPT = 'image/*,.heic,.webp,.tif,.tiff';
const UDF_NOTE = 'Üretilen UDF dosyasını UYAP\'a göndermeden önce UYAP Doküman Editörü\'nde bir kez açıp kontrol edin. '
  + 'Resimler UDF\'ye aktarılmaz.';
const isEkFormat = v => v.format === 'ek' || v.format === 'ek-sayfa' || v.format === 'custom';

const TOOLS = [
  {
    id: 'udf-to-pdf', group: 'Dönüştür', color: 'var(--c-uyap)', icon: 'udf', title: 'UDF → PDF',
    short: 'UYAP belgesini PDF yap', desc: 'UYAP Doküman Editörü belgelerini (.udf) biçimini koruyarak PDF\'e çevirin. Word gerekmez.',
    accept: '.udf', multiple: true, endpoint: '/api/convert/udf-to-pdf', button: 'PDF\'e Dönüştür', options: [],
  },
  {
    id: 'udf-to-word', group: 'Dönüştür', color: 'var(--c-uyap)', icon: 'udf', title: 'UDF → Word',
    short: 'UYAP belgesini Word yap', desc: 'UDF belgelerini düzenlenebilir Word (.docx) dosyasına çevirin.',
    accept: '.udf', multiple: true, endpoint: '/api/convert/udf-to-word', button: 'Word\'e Dönüştür', options: [],
  },
  {
    id: 'to-udf', group: 'Dönüştür', color: 'var(--c-uyap)', icon: 'udf', title: 'Word / PDF → UDF',
    short: 'UYAP\'a yüklenecek UDF hazırla', desc: 'Word (.docx, .doc, .rtf) ya da PDF dosyasını UYAP Doküman Editörü biçimine (.udf) çevirin.',
    accept: '.docx,.doc,.rtf,.odt,.pdf', multiple: true, endpoint: '/api/convert/to-udf', button: 'UDF\'ye Dönüştür',
    busy: 'UDF hazırlanıyor…', options: [], note: UDF_NOTE,
  },
  {
    id: 'ocr', group: 'Sayfa Araçları', color: 'var(--c-convert)', icon: 'scan', title: 'Metin Tanıma (OCR)',
    short: 'Taranmış belgeyi aranabilir yap', desc: 'Taranmış PDF\'lerdeki ve fotoğraflardaki yazıları tanır; belge aranabilir ve kopyalanabilir olur.',
    accept: '.pdf,' + IMG_ACCEPT, multiple: true, endpoint: '/api/tool/ocr', button: 'Metni Tanı',
    busy: 'Metin tanınıyor… (sayfa başına yaklaşık 1 saniye)',
    options: [
      { name: 'mode', type: 'seg', label: 'Hangi sayfalar?', value: 'missing', choices: [['missing', 'Yalnızca metni olmayanlar'], ['all', 'Tüm sayfalar']],
        hint: 'Sayfanın görünümü değişmez; yazıların üzerine görünmez, seçilebilir bir metin katmanı eklenir.' },
    ],
    note: 'Tanıma bilgisayarınızda yapılır; internet ve yapay zekâ servisi kullanılmaz. Türkçe karakterler desteklenir.',
  },
  {
    id: 'word-to-pdf', group: 'Dönüştür', color: 'var(--c-convert)', icon: 'wordpdf', title: 'Word → PDF',
    short: 'Word belgelerini PDF yap', desc: 'Word belgelerini (.docx, .doc, .rtf, .odt) birebir görünümle PDF\'e çevirin.',
    accept: WORD_ACCEPT, multiple: true, endpoint: '/api/convert/word-to-pdf', button: 'PDF\'e Dönüştür',
    busy: 'Microsoft Word ile dönüştürülüyor…', options: [],
  },
  {
    id: 'excel-to-pdf', group: 'Dönüştür', color: 'var(--c-convert)', icon: 'excel', title: 'Excel → PDF',
    short: 'Excel tablolarını PDF yap',
    desc: 'Excel dosyalarını (.xlsx, .xls, .csv, .ods) Excel\'in sayfa düzeniyle PDF\'e çevirin; bütün çalışma sayfaları tek PDF\'te.',
    accept: EXCEL_ACCEPT, multiple: true, endpoint: '/api/convert/excel-to-pdf', button: 'PDF\'e Dönüştür',
    busy: 'Microsoft Excel ile dönüştürülüyor…', options: [],
    note: 'Sayfa yönü, kenar boşluğu ve yazdırma alanı Excel\'deki “Sayfa Düzeni” ayarlarından gelir.',
  },
  {
    id: 'pdf-to-word', group: 'Dönüştür', color: 'var(--c-convert)', icon: 'pdfword', title: 'PDF → Word',
    short: 'PDF\'i düzenlenebilir Word yap', desc: 'PDF dosyalarını düzenlenebilir Word (.docx) belgesine çevirin.',
    accept: '.pdf', multiple: true, endpoint: '/api/convert/pdf-to-word', button: 'Word\'e Dönüştür', busy: 'Word belgesi oluşturuluyor…',
    options: [
      { name: 'engine', type: 'seg', label: 'Dönüştürme motoru', value: 'standart', choices: [['standart', 'Standart'], ['word', 'Microsoft Word']],
        hint: 'Standart: sayfa düzenini, tabloları ve resimleri korur. Microsoft Word: Word\'ün kendi PDF okuyucusunu kullanır.' },
      { name: 'password', type: 'password', label: 'PDF şifresi (varsa)', placeholder: 'Şifresizse boş bırakın', showIf: v => !v.__doc },
    ],
    note: 'Taranmış (resim) PDF\'lerde metin seçilebilir olmadığı için Word\'de de resim olarak görünür.',
  },
  {
    id: 'pdf-to-excel', group: 'Dönüştür', color: 'var(--c-convert)', icon: 'excel', title: 'PDF → Excel',
    short: 'Tabloları Excel\'e aktar',
    desc: 'PDF\'teki tabloları Excel\'e aktarın: çizgili tablolar hücreleriyle, çizgisiz hizalı tablolar (hesap dökümü, ödeme planı) '
      + 'sütunlarına ayrılarak gelir. Tutarlar (12.500,00) sayı, tarihler (01.02.2026) tarih olur; Excel\'de toplanıp sıralanabilir.',
    accept: '.pdf', multiple: true, endpoint: '/api/convert/pdf-to-excel', button: 'Excel\'e Dönüştür', busy: 'Tablolar aktarılıyor…',
    options: [
      { name: 'content', type: 'seg', label: 'Ne aktarılsın?', value: 'tables', choices: [['tables', 'Yalnızca tablolar'], ['all', 'Bütün sayfa']],
        hint: 'Bütün sayfa: tablo dışındaki satırlar da sırasıyla (her satır bir hücre) aktarılır.' },
      { name: 'layout', type: 'seg', label: 'Excel sayfaları', value: 'pages', choices: [['pages', 'Her PDF sayfası ayrı'], ['single', 'Hepsi tek sayfada']] },
    ],
    note: 'Taranmış PDF\'lerde önce “Metin Tanıma (OCR)” uygulayın.',
  },
  {
    id: 'images-to-pdf', group: 'Dönüştür', color: 'var(--c-convert)', icon: 'img', title: 'Resim → PDF',
    short: 'JPG, PNG, HEIC, TIFF\'ten PDF',
    desc: 'Fotoğraf ve taramaları tek bir PDF\'te toplayın; çok sayfalı TIFF\'in her sayfası ayrı sayfa olur. Sırayı sürükleyerek değiştirin.',
    accept: IMG_ACCEPT, multiple: true, reorder: true, endpoint: '/api/convert/images-to-pdf', button: 'PDF Oluştur',
    options: [
      { name: 'page_size', type: 'seg', label: 'Sayfa boyutu', value: 'a4', choices: [['a4', 'A4 dikey'], ['a4-yatay', 'A4 yatay'], ['orijinal', 'Resim boyutu']] },
      { name: 'name', type: 'text', label: 'Dosya adı', placeholder: 'resimler', showIf: v => !v.separate },
      { name: 'separate', type: 'check', label: 'Her resmi ayrı PDF yap', value: false },
    ],
  },
  {
    id: 'pdf-to-images', group: 'Dönüştür', color: 'var(--c-convert)', icon: 'toimg', title: 'PDF → Resim',
    short: 'Sayfaları JPG, PNG ya da TIFF yap',
    desc: 'Her sayfayı ayrı bir resim olarak (çok sayfa ZIP) ya da bütün sayfaları tek bir TIFF dosyası olarak kaydedin.',
    accept: '.pdf', multiple: true, endpoint: '/api/convert/pdf-to-images', button: 'Resimlere Dönüştür',
    options: [
      { name: 'format', type: 'seg', label: 'Biçim', value: 'jpg', choices: [['jpg', 'JPG'], ['png', 'PNG'], ['tiff', 'TIFF (tek dosya)']] },
      { name: 'dpi', type: 'seg', label: 'Çözünürlük', value: '150',
        choices: [['96', 'Ekran (96 dpi)'], ['150', 'Normal (150 dpi)'], ['200', 'Tarama (200 dpi)'], ['300', 'Baskı (300 dpi)']] },
      { name: 'color', type: 'seg', label: 'Renk', value: 'gri', showIf: v => v.format === 'tiff',
        choices: [['renkli', 'Renkli'], ['gri', 'Gri'], ['sb', 'Siyah-beyaz (en küçük)']] },
    ],
  },
  {
    id: 'reader', group: 'Oku & Düzenle', color: 'var(--c-read)', icon: 'book', title: 'PDF Okuyucu ve Düzenleyici',
    short: 'Okuyun, not alın, düzenleyin, imzalayın', desc: '', route: '#/reader',
  },
  {
    id: 'convert', group: 'Dönüştür', color: 'var(--c-convert)', icon: 'convert', title: 'Dönüştür',
    short: 'PDF, Word, Excel, UDF ve resim arasında', desc: '', route: '#/convert',
  },
  {
    id: 'compare', group: 'Oku & Düzenle', color: 'var(--c-read)', icon: 'compare', title: 'Karşılaştır',
    short: 'İki sürüm arasındaki farklar',
    desc: 'Bir dilekçenin, sözleşmenin ya da kararın iki sürümünü (PDF, Word, Excel ya da UDF) karşılaştırın: eski sürümden silinen '
      + 'yerler kırmızı, yenide eklenen yerler yeşil boyanır. İlk sayfada değişiklik listesi, ardından eski ve yeni sayfalar yan yana.',
    accept: `.pdf,.udf,${WORD_ACCEPT},${EXCEL_ACCEPT}`, multiple: true, reorder: true, minFiles: 2, maxFiles: 2, withDoc: true,
    roles: ['ESKİ', 'YENİ'], docLast: true, readResult: true, pickHint: 'Karşılaştırılacak eski sürümü seçin',
    endpoint: '/api/tool/compare', button: 'Karşılaştır', busy: 'Karşılaştırılıyor…', options: [],
  },
  {
    id: 'merge', group: 'Sayfa Araçları', color: 'var(--c-pages)', icon: 'merge', title: 'Birleştir',
    short: 'PDF, Word, Excel, UDF ve resimleri tek PDF yap',
    desc: 'PDF, Word, Excel, UDF, resim ve TIFF dosyalarını istediğiniz sırayla tek bir PDF\'te birleştirin. Resim ve TIFF sayfaları '
      + 'A4\'e sığan en büyük ölçüde konur; her dosya içindekilerde ayrı bir başlık olur.',
    accept: `.pdf,.udf,${WORD_ACCEPT},${EXCEL_ACCEPT},${IMG_ACCEPT}`, multiple: true, reorder: true, minFiles: 2, withDoc: true,
    pickHint: 'Açık belgeye eklenecek dosyaları seçin',
    endpoint: '/api/tool/merge', button: 'Birleştir',
    options: [{ name: 'name', type: 'text', label: 'Yeni dosya adı', placeholder: 'birlestirilmis' }],
  },
  {
    id: 'split', group: 'Sayfa Araçları', color: 'var(--c-pages)', icon: 'split', title: 'Böl / Sayfa Ayır',
    short: 'Sayfaları ayrı dosyalara böl', desc: 'PDF\'i sayfalara ya da aralıklara bölün veya seçtiğiniz sayfaları çıkarın.',
    accept: '.pdf', multiple: false, endpoint: '/api/tool/split', button: 'Böl',
    options: [
      { name: 'mode', type: 'seg', label: 'Nasıl bölünsün?', value: 'each', choices: [['each', 'Her sayfa ayrı'], ['ranges', 'Aralıklara göre'], ['every', 'Her N sayfada'], ['extract', 'Sayfaları çıkar']] },
      { name: 'spec', type: 'text', label: 'Sayfa aralıkları', placeholder: 'örn: 1-3, 5, 8-10', showIf: v => v.mode === 'ranges' || v.mode === 'extract',
        hint: 'Aralıklara göre: her virgül ayrı dosya. Sayfaları çıkar: hepsi tek dosya.' },
      { name: 'every', type: 'number', label: 'Kaç sayfada bir?', value: 2, min: 1, showIf: v => v.mode === 'every' },
    ],
  },
  {
    id: 'compress', group: 'Sayfa Araçları', color: 'var(--c-pages)', icon: 'compress', title: 'Sıkıştır',
    short: 'Dosya boyutunu küçült', desc: 'Resimleri optimize ederek PDF boyutunu küçültün (e-posta, UYAP vb. için).',
    accept: '.pdf', multiple: true, endpoint: '/api/tool/compress', button: 'Sıkıştır', busy: 'Sıkıştırılıyor…',
    options: [
      { name: 'level', type: 'seg', label: 'Sıkıştırma düzeyi', value: 'orta', choices: [['dusuk', 'Hafif (kayıpsız)'], ['orta', 'Önerilen'], ['yuksek', 'Güçlü']],
        hint: 'Güçlü sıkıştırma resim kalitesini düşürür; metinler etkilenmez.' },
    ],
  },
  {
    id: 'watermark', group: 'İşaretle & Koru', color: 'var(--c-secure)', icon: 'watermark', title: 'Filigran',
    short: 'Sayfalara yazı damgası', desc: 'Tüm sayfalara çapraz bir filigran yazısı ekleyin (ör. "ASLI GİBİDİR", "TASLAK").',
    accept: '.pdf', multiple: true, endpoint: '/api/tool/watermark', button: 'Filigran Ekle',
    options: [
      { name: 'text', type: 'text', label: 'Filigran metni', value: 'TASLAK', wide: true },
      { name: 'size', type: 'number', label: 'Yazı boyutu', value: 64, min: 8, max: 200 },
      { name: 'opacity', type: 'range', label: 'Saydamlık', value: 0.18, min: 0.05, max: 1, step: 0.01, fmt: v => '%' + Math.round(v * 100) },
      { name: 'angle', type: 'number', label: 'Açı (derece)', value: 45, min: -90, max: 90 },
      { name: 'color', type: 'color', label: 'Renk', value: '#c0392b' },
      { name: 'pages', type: 'text', label: 'Sayfalar', placeholder: 'Boş = tümü, örn: 1-3' },
    ],
  },
  {
    id: 'numbers', group: 'İşaretle & Koru', color: 'var(--c-secure)', icon: 'numbers', title: 'Sayfa No / Ek No',
    short: 'Sayfa ya da ek numarası ekle', desc: 'Sayfalara sayfa numarası ya da "Ek:1/1, Ek:1/2…" gibi ek numarası ekleyin.',
    accept: '.pdf', multiple: true, reorder: true, endpoint: '/api/tool/numbers', button: 'Numara Ekle',
    options: [
      { name: 'format', type: 'select', label: 'Biçim', value: 'n', choices: [['n', '1'], ['n/t', '1 / 10'], ['sayfa n', 'Sayfa 1'],
        ['sayfa n/t', 'Sayfa 1 / 10'], ['-n-', '- 1 -'], ['ek', 'Ek:1/1  (ek no / ekin sayfası)'], ['ek-sayfa', 'EK-1 / Sayfa 1'], ['custom', 'Özel (kendim yazacağım)…']] },
      { name: 'template', type: 'text', label: 'Özel biçim', value: 'EK-{n} Sayfa {t}', placeholder: 'örn: EK-{n} Sayfa {t}',
        showIf: v => v.format === 'custom', hint: '{n} yerine ek numarası, {t} yerine ekin kaçıncı sayfası olduğu yazılır. {toplam} ekin son sayfa numarasıdır.' },
      { name: 'ek_no', type: 'number', label: 'Ek numarası', value: 1, min: 1, showIf: v => isEkFormat(v) },
      { name: 'position', type: 'select', label: 'Konum', value: 'alt-orta', choices: [['alt-orta', 'Alt orta'], ['alt-sag', 'Alt sağ'], ['alt-sol', 'Alt sol'], ['ust-orta', 'Üst orta'], ['ust-sag', 'Üst sağ'], ['ust-sol', 'Üst sol']] },
      { name: 'start', type: 'number', label: 'Başlangıç numarası', value: 1, min: 0 },
      { name: 'font', type: 'select', label: 'Yazı tipi', value: 'serif', choices: [['serif', 'Times New Roman'], ['sans', 'Arial']] },
      { name: 'size', type: 'number', label: 'Yazı boyutu', value: 11, min: 6, max: 40 },
      { name: 'color', type: 'palette', label: 'Renk', value: '#000000', wide: true, choices: [['#000000', 'Siyah'], ['#1f3a93', 'Lacivert'],
        ['#c62828', 'Kırmızı'], ['#7b1e1e', 'Bordo'], ['#1565c0', 'Mavi'], ['#2e7d32', 'Yeşil'], ['#6b7280', 'Gri']] },
      { name: 'bold', type: 'check', label: 'Kalın yazı', value: false },
      { name: 'skip_first', type: 'check', label: 'İlk sayfayı numaralandırma (kapak)', value: false },
      { name: 'ek_artir', type: 'check', label: 'Birden çok dosyada ek numarasını artır', value: true, wide: true, showIf: v => isEkFormat(v) && !v.__doc,
        hint: 'Seçilen dosyalar listedeki sırayla Ek 1, Ek 2, Ek 3… olur. Sırayı dosyaları sürükleyerek değiştirebilirsiniz.' },
    ],
    preview: v => {
      const ekMode = isEkFormat(v);
      const n = Number.isNaN(parseInt(v.start, 10)) ? 1 : parseInt(v.start, 10);
      const pages = v.__pages || 10;   // açık belgenin sayfa sayısı; dosya seçilince 10 sayfalık bir örnek
      const toplam = n + Math.max(pages - (v.skip_first ? 2 : 1), 0);
      const ek = parseInt(v.ek_no, 10) || 1;
      const tpl = { n: '{sayfa}', 'n/t': '{sayfa} / {toplam}', 'sayfa n': 'Sayfa {sayfa}', 'sayfa n/t': 'Sayfa {sayfa} / {toplam}',
        '-n-': '- {sayfa} -', ek: 'Ek:{ek}/{sayfa}', 'ek-sayfa': 'EK-{ek} / Sayfa {sayfa}', custom: v.template || '' }[v.format] ?? '{sayfa}';
      const vals = { sayfa: n, toplam, ek, n: ek, t: n };
      const label = tpl.replace(/\{(\w+)\}/g, (m, k) => k in vals ? vals[k] : m);
      const size = Math.min(Math.max((+v.size || 11) * 0.95, 9), 18);
      const family = v.font === 'sans' ? 'Arial, Helvetica, sans-serif' : "'Times New Roman', Times, serif";
      const which = v.skip_first ? '2. sayfası (kapak numarasız)' : 'ilk sayfası';
      return `<div class="num-page"><span class="num-label pos-${esc(v.position)}" style="color:${esc(v.color)};font-weight:${v.bold ? 700 : 400};font-size:${size}px;font-family:${family}">${esc(label)}</span></div>
        <span class="muted small">${v.__pages ? '' : 'Örnek: '}${pages} sayfalık ${ekMode ? `Ek ${ek} dosyasının` : 'belgenin'} ${which}</span>`;
    },
  },
  {
    id: 'protect', group: 'İşaretle & Koru', color: 'var(--c-secure)', icon: 'lock', title: 'Şifrele',
    short: 'PDF\'e açılış şifresi koy', desc: 'PDF\'i AES-256 ile şifreleyin; açmak için şifre gerekir.',
    accept: '.pdf', multiple: true, endpoint: '/api/tool/protect', button: 'Şifrele',
    options: [
      { name: 'password', type: 'password', label: 'Şifre' },
      { name: 'password2', type: 'password', label: 'Şifre (tekrar)', noSend: true },
      { name: 'allow_print', type: 'check', label: 'Yazdırmaya izin ver', value: true },
      { name: 'allow_copy', type: 'check', label: 'Metin kopyalamaya izin ver', value: false },
    ],
    validate: v => !v.password ? 'Şifre girin.' : v.password !== v.password2 ? 'Şifreler eşleşmiyor.' : null,
  },
  {
    id: 'unlock', group: 'İşaretle & Koru', color: 'var(--c-secure)', icon: 'unlock', title: 'Şifre Kaldır',
    short: 'Şifreli PDF\'i aç', desc: 'Şifresini bildiğiniz bir PDF\'ten şifre korumasını kaldırın.',
    accept: '.pdf', multiple: true, endpoint: '/api/tool/unlock', button: 'Şifreyi Kaldır',
    options: [{ name: 'password', type: 'password', label: 'Mevcut şifre', showIf: v => !v.__doc }],
    docNote: info => info.encrypted ? 'Belge açılırken şifresi girildi; şifresiz bir kopyası oluşturulacak.'
      : 'Açık belge zaten şifresiz. Yine de bir kopyasını oluşturabilirsiniz.',
  },
];
const TOOL = Object.fromEntries(TOOLS.map(t => [t.id, t]));
const GROUPS = ['Oku & Düzenle', 'Dönüştür', 'Sayfa Araçları', 'İşaretle & Koru'];
const toolHref = t => t.route || `#/${t.id}`;

// ------------------------------------------------------------------ dosya bırakma alanı
function setupDrop(el, { accept, multiple }, onFiles) {
  el.addEventListener('click', async () => onFiles(await pickFiles({ accept, multiple })));
  el.addEventListener('dragover', e => { e.preventDefault(); el.classList.add('over'); });
  el.addEventListener('dragleave', () => el.classList.remove('over'));
  el.addEventListener('drop', e => {
    e.preventDefault(); el.classList.remove('over');
    const files = [...e.dataTransfer.files];
    onFiles(multiple ? files : files.slice(0, 1));
  });
}

function acceptsFile(tool, f) {
  const e = '.' + ext(f.name);
  return tool.accept.split(',').some(a => a === e || (a === 'image/*' && f.type.startsWith('image/')));
}

// ------------------------------------------------------------------ araç sayfası
// Düzenleyicide/okuyucuda bir belge açıkken bu araçlar o belgeyle çalışır.
// apply: sonuç belgenin yeni hâli olur (hemen görünür, Geri Al ile geri alınır); export: ayrı dosya üretir.
const DOC_TOOL_MODE = {
  watermark: 'apply', numbers: 'apply', compress: 'apply', ocr: 'apply', merge: 'apply', compare: 'export',
  'pdf-to-word': 'export', 'pdf-to-excel': 'export', 'pdf-to-images': 'export', split: 'export', 'to-udf': 'export', protect: 'export', unlock: 'export',
};

function renderTool(main, tool, { useDoc = true } = {}) {
  const values = {};
  for (const o of tool.options) values[o.name] = o.value ?? '';
  let files = [];
  const ctx = useDoc && !handoffFiles && DOC_TOOL_MODE[tool.id] ? openDocView() : null;
  const apply = DOC_TOOL_MODE[tool.id] === 'apply';
  values.__doc = !!ctx;
  values.__pages = ctx ? ctx.info.pages.length : 0;   // önizleme açık belgenin sayfa sayısıyla
  if (handoffFiles) { files = handoffFiles.filter(f => acceptsFile(tool, f)); handoffFiles = null; }
  if (ctx && tool.withDoc) files = [{ doc: true }];   // açık belge listede; yanına başka dosyalar eklenir
  if (!tool.multiple) files = files.slice(0, 1);
  const docName = () => ctx.mod.docInfo()?.name || ctx.info.name;

  main.innerHTML = `<div class="page">
    <div class="page-head"><span class="tool-icon" style="--c:${tool.color}">${icon(tool.icon)}</span>
      <div><h1>${esc(tool.title)}</h1><p>${esc(tool.desc)}</p></div></div>
    ${ctx ? `<div class="doc-ctx"><span class="tool-icon" style="--c:var(--c-edit)">${icon('file')}</span>
      <div class="doc-ctx-text"><b>${esc(docName())}</b><span class="muted small">${apply
        ? 'Açık belgeye uygulanacak; sonucu hemen ekranda görürsünüz' : 'Açık belgeden yeni bir dosya oluşturulacak'} · ${ctx.info.pages.length} sayfa</span></div>
      <span class="spacer"></span>
      <button class="btn sm ghost" id="ctx-back">${icon('left')}Belgeye dön</button>
      <button class="btn sm ghost" id="ctx-other" title="Açık belge yerine bilgisayardan dosya seçin">Başka dosya seç</button></div>
      ${tool.docNote ? `<div class="note">${esc(tool.docNote(ctx.info))}</div>` : ''}` : ''}
    <div class="drop" id="tool-drop" ${ctx && !tool.withDoc ? 'hidden' : ''}><div class="drop-icon">${icon('upload')}</div>
      <b>${tool.multiple ? 'Dosyaları' : 'Dosyayı'} buraya bırakın ya da tıklayıp seçin</b>
      <span class="muted">${esc(tool.accept.replace('image/*', 'resimler').replaceAll(',', ' '))}</span></div>
    <div class="file-list" id="file-list"></div>
    ${tool.id === 'word-to-pdf' && !state.engines.word ? `<div class="note ${state.engines.libreoffice ? '' : 'warn'}">${state.engines.libreoffice
      ? 'Microsoft Word bulunamadı; LibreOffice kullanılacak.' : 'Word→PDF için Microsoft Word veya LibreOffice kurulu olmalı.'}</div>` : ''}
    ${tool.id === 'excel-to-pdf' && !state.engines.excel ? `<div class="note ${state.engines.libreoffice ? '' : 'warn'}">${state.engines.libreoffice
      ? 'Microsoft Excel bulunamadı; LibreOffice kullanılacak.' : 'Excel→PDF için Microsoft Excel veya LibreOffice kurulu olmalı.'}</div>` : ''}
    ${tool.id === 'ocr' && !state.engines.ocr ? `<div class="note warn">Bu bilgisayarda metin tanıma bulunamadı.${IS_WIN ? ' Windows Ayarlar › Saat ve dil › Dil ve bölge › Türkçe › Dil seçenekleri bölümünden “Optik karakter tanıma” bileşenini yükleyip uygulamayı yeniden açın.' : ''}</div>` : ''}
    ${tool.options.length ? '<div class="panel"><h3>Ayarlar</h3><div class="options" id="opts"></div></div>' : ''}
    ${tool.note ? `<div class="note">${esc(tool.note)}</div>` : ''}
    ${ctx && apply ? `<div class="note">Sonuç belgede hemen görünür. Beğenmezseniz Geri Al (⌘Z) ile geri alabilirsiniz; dosyanız siz Kaydet'e basana kadar değişmez.</div>` : ''}
    <div class="actions"><button class="btn primary big" id="run">${icon('check')}${esc(ctx && apply && !tool.withDoc ? 'Belgeye Uygula' : tool.button)}</button>
      <span class="muted" id="run-hint"></span></div>
    <div class="results" id="results"></div>
  </div>`;

  if (ctx) {
    $('#ctx-back').onclick = () => { location.hash = '#/' + ctx.view; };
    $('#ctx-other').onclick = () => renderTool(main, tool, { useDoc: false });
  }
  const drop = $('#tool-drop');
  setupDrop(drop, tool, picked => {
    const ok = picked.filter(f => acceptsFile(tool, f));
    if (ok.length < picked.length) toast('Bazı dosyalar bu araç için uygun değil, atlandı.', 'error');
    // docLast: açık belge sonda kalır (Karşılaştır'da açık belge yeni sürüm sayılır)
    const docLast = tool.docLast && files.some(f => f.doc);
    files = !tool.multiple ? ok.slice(0, 1) : docLast ? [...ok, ...files] : files.concat(ok);
    if (tool.maxFiles && files.length > tool.maxFiles) {   // açık belge her zaman listede kalır
      toast(`En çok ${tool.maxFiles} dosya seçilebilir; fazlası alınmadı.`, 'error');
      const doc = files.filter(f => f.doc), rest = files.filter(f => !f.doc).slice(0, tool.maxFiles - doc.length);
      files = docLast ? [...rest, ...doc] : [...doc, ...rest];
    }
    renderFiles();
  });

  function renderFiles() {
    const list = $('#file-list');
    // Sırası anlamlı araçlarda (Karşılaştır: eski, yeni) her satırın görevi yazılır; açık belge sonda duracağı için
    // liste eksikken görevler sondan sayılır (tek başına açık belge: YENİ)
    const shift = tool.docLast && files.some(f => f.doc) ? Math.max(0, (tool.roles?.length || 0) - files.length) : 0;
    const role = i => (tool.roles?.[i + shift] ? `<span class="role">${esc(tool.roles[i + shift])}</span>` : '');
    list.innerHTML = files.map((f, i) => f.doc ? `<div class="file-row doc-row" draggable="${!!tool.reorder}" data-i="${i}">
      ${tool.reorder ? `<span class="grip" title="Sürükleyerek sırala">${icon('grip')}</span>` : ''}
      ${role(i)}<span class="badge">AÇIK</span><span class="fname">${esc(docName())}</span>
      <span class="muted small">${ctx.info.pages.length} sayfa · açık belge</span></div>`
      : `<div class="file-row" draggable="${!!tool.reorder}" data-i="${i}">
      ${tool.reorder ? `<span class="grip" title="Sürükleyerek sırala">${icon('grip')}</span>` : ''}
      ${role(i)}<span class="badge">${esc(ext(f.name).toUpperCase())}</span>
      <span class="fname" title="${esc(f.name)}">${esc(f.name)}</span>
      <span class="muted small">${fmtSize(f.size)}</span>
      <button class="x" data-del="${i}" title="Kaldır">×</button></div>`).join('');
    drop.classList.toggle('compact', files.length > 0);
    $$('[data-del]', list).forEach(b => b.onclick = () => { files.splice(+b.dataset.del, 1); renderFiles(); });
    if (tool.reorder) enableRowDrag(list, (from, to) => {
      const [f] = files.splice(from, 1); files.splice(to > from ? to - 1 : to, 0, f); renderFiles();
    });
    const need = tool.minFiles || 1;
    const count = files.length + (ctx && !tool.withDoc ? 1 : 0);
    const unavailable = tool.id === 'ocr' && !state.engines.ocr;   // Windows'ta metin tanıma motoru yok
    $('#run').disabled = count < need || unavailable;
    $('#run-hint').textContent = count < need ? (ctx && tool.pickHint ? tool.pickHint : need > 1 ? `En az ${need} dosya seçin` : 'Önce dosya seçin')
      : ctx && count === 1 ? `“${docName()}” hazır` : `${count} dosya hazır`;
  }

  function renderOptions() {
    const box = $('#opts');
    if (!box) return;
    box.innerHTML = '';
    for (const o of tool.options) {
      if (o.showIf && !o.showIf(values)) continue;
      const f = document.createElement('div');
      // Çok ya da uzun seçenekli düğme grubu tam satıra yayılır (yarım sütunda düğmeler alt alta kırılıyor)
      const longSeg = o.type === 'seg' && (o.choices.length > 3 || o.choices.reduce((n, [, lab]) => n + lab.length, 0) > 30);
      f.className = 'field' + (o.wide || longSeg ? ' wide' : '');
      const id = 'opt-' + o.name;
      const v = values[o.name];
      if (o.type === 'check') {
        f.innerHTML = `<label class="check" style="margin-top:22px;color:var(--text);font-size:14px"><input type="checkbox" id="${id}" ${v ? 'checked' : ''}>${esc(o.label)}</label>`;
        $('input', f).onchange = e => { values[o.name] = e.target.checked; renderOptions(); };
      } else if (o.type === 'seg') {
        f.innerHTML = `<label>${esc(o.label)}</label><div class="seg">${o.choices.map(([val, lab]) =>
          `<button type="button" data-v="${esc(val)}" class="${String(v) === String(val) ? 'on' : ''}">${esc(lab)}</button>`).join('')}</div>`;
        $$('button', f).forEach(b => b.onclick = () => { values[o.name] = b.dataset.v; renderOptions(); });
      } else if (o.type === 'select') {
        f.innerHTML = `<label for="${id}">${esc(o.label)}</label><select class="input" id="${id}">${o.choices.map(([val, lab]) =>
          `<option value="${esc(val)}" ${String(v) === String(val) ? 'selected' : ''}>${esc(lab)}</option>`).join('')}</select>`;
        $('select', f).onchange = e => { values[o.name] = e.target.value; renderOptions(); };
      } else if (o.type === 'palette') {
        const known = o.choices.some(([c]) => c.toLowerCase() === String(v).toLowerCase());
        f.innerHTML = `<label>${esc(o.label)}</label><div class="palette">${o.choices.map(([c, n]) =>
          `<button type="button" class="swatch ${String(v).toLowerCase() === c ? 'on' : ''}" data-c="${c}" title="${esc(n)}" aria-label="${esc(n)}" style="background:${c}"></button>`).join('')}
          <label class="swatch custom ${known ? '' : 'on'}" title="Başka bir renk seç"><input type="color" value="${esc(v)}"></label>
          <span class="muted small palette-name">${esc((o.choices.find(([c]) => c.toLowerCase() === String(v).toLowerCase()) || [, 'Özel renk'])[1])}</span></div>`;
        $$('[data-c]', f).forEach(b => b.onclick = () => { values[o.name] = b.dataset.c; renderOptions(); });
        $('input[type=color]', f).oninput = e => {
          values[o.name] = e.target.value;
          $$('.swatch', f).forEach(s => s.classList.toggle('on', s.classList.contains('custom')));
          $('.palette-name', f).textContent = 'Özel renk';
          updatePreview();
        };
      } else if (o.type === 'range') {
        f.innerHTML = `<label for="${id}">${esc(o.label)}: <span>${o.fmt ? o.fmt(v) : v}</span></label>
          <input type="range" id="${id}" min="${o.min}" max="${o.max}" step="${o.step}" value="${v}">`;
        $('input', f).oninput = e => { values[o.name] = +e.target.value; $('span', f).textContent = o.fmt ? o.fmt(+e.target.value) : e.target.value; };
      } else {
        const type = o.type === 'number' ? 'number' : o.type === 'password' ? 'password' : o.type === 'color' ? 'color' : 'text';
        f.innerHTML = `<label for="${id}">${esc(o.label)}</label><input class="input" id="${id}" type="${type}" value="${esc(v)}"
          ${o.placeholder ? `placeholder="${esc(o.placeholder)}"` : ''} ${o.min != null ? `min="${o.min}"` : ''} ${o.max != null ? `max="${o.max}"` : ''}>`;
        $('input', f).oninput = e => { values[o.name] = e.target.value; updatePreview(); };
      }
      if (o.hint) f.insertAdjacentHTML('beforeend', `<span class="hint">${esc(o.hint)}</span>`);
      box.append(f);
    }
    if (tool.preview) {
      box.insertAdjacentHTML('beforeend', '<div class="field wide"><label>Önizleme</label><div class="opt-preview" id="opt-preview"></div></div>');
      updatePreview();
    }
  }

  function updatePreview() {
    const el = $('#opt-preview');
    if (el && tool.preview) el.innerHTML = tool.preview(values);
  }

  $('#run').onclick = async () => {
    const problem = tool.validate?.(values);
    if (problem) return toast(problem, 'error');
    const fd = new FormData();
    files.forEach((f, i) => {
      if (f.doc) fd.append('doc_pos', files.slice(0, i).filter(x => !x.doc).length);
      else fd.append('files', f, f.name);
    });
    for (const o of tool.options) {
      if (o.noSend || (o.showIf && !o.showIf(values))) continue;
      const v = values[o.name];
      fd.append(o.name, typeof v === 'boolean' ? (v ? '1' : '0') : v);
    }
    if (ctx) return runOnDocument(fd);
    try {
      const data = await withBusy(tool.busy || 'İşleniyor…', () => api(tool.endpoint, { method: 'POST', body: fd }));
      renderResults($('#results'), data.files, { read: tool.readResult });
    } catch { /* toast gösterildi */ }
  };

  async function runOnDocument(fd) {
    const info = ctx.mod.docInfo();
    if (!info) { toast('Belge kapatılmış; dosya seçerek devam edin.', 'error'); return renderTool(main, tool, { useDoc: false }); }
    try {
      if (apply && !await confirmSignedRewrite(info, `“${tool.title}”`)) return;
      await window.Reader.flush?.();   // uygulanmamış eklemeler (düzenleme araçları) varsa önce onlar
      const data = await withBusy(tool.busy || 'İşleniyor…', () => api(`/api/edit/${info.id}/tool/${tool.id}`, { method: 'POST', body: fd }));
      if (!apply) return renderResults($('#results'), data.files, { dir: dirOf(info.path), read: tool.readResult });
      ctx.mod.update(data);
      if (data.changed === false) toast(data.note || 'Belgede değişiklik gerekmedi.');
      else toast(`${tool.title} uygulandı${data.before ? ` (${fmtSize(data.before)} → ${fmtSize(data.after)})` : ''}. Kalıcı olması için Kaydet'e basın.`, 'ok');
      if (tool.id === 'ocr' && data.changed !== false && /Türkçe tanıma paketi/.test(data.note || '')) toast(data.note);
      location.hash = '#/' + ctx.view;
    } catch { /* toast gösterildi */ }
  }

  renderFiles();
  renderOptions();
}

function enableRowDrag(list, onMove) {
  let from = null;
  $$('.file-row', list).forEach(row => {
    row.addEventListener('dragstart', e => { from = +row.dataset.i; row.classList.add('dragging'); e.dataTransfer.effectAllowed = 'move'; });
    row.addEventListener('dragend', () => { row.classList.remove('dragging'); $$('.drop-before', list).forEach(r => r.classList.remove('drop-before')); });
    row.addEventListener('dragover', e => {
      e.preventDefault();
      $$('.drop-before', list).forEach(r => r.classList.remove('drop-before'));
      row.classList.add('drop-before');
    });
    row.addEventListener('drop', e => {
      e.preventDefault(); e.stopPropagation();
      if (from != null && from !== +row.dataset.i) onMove(from, +row.dataset.i);
    });
  });
  list.addEventListener('dragover', e => e.preventDefault());
  list.ondrop = e => {
    if (e.target === list && from != null) onMove(from, list.children.length);
  };
}

// ------------------------------------------------------------------ sonuçlar
// read: çıktı okunmak için açılır (Karşılaştır raporu); yoksa düzenleme araçları açık gelir
function renderResults(box, results, { dir = '', read = false } = {}) {
  const ok = results.filter(r => !r.error);
  box.innerHTML = `<h3>${ok.length ? `<span class="ok-dot" style="width:22px;height:22px;border-radius:50%;background:var(--ok);color:#fff;display:inline-grid;place-items:center">${icon('check', 'width="14" height="14"')}</span>` : ''}
    ${ok.length ? `${ok.length} dosya hazır` : 'İşlem başarısız'}</h3>`;
  for (const r of results) {
    const row = document.createElement('div');
    if (r.error) {
      row.className = 'result-row error';
      row.innerHTML = `<span class="fname">${esc(r.name)}</span><span>${esc(r.error)}</span>`;
    } else {
      row.className = 'result-row';
      const saved = r.before ? ` · ${fmtSize(r.before)} → ${fmtSize(r.after)} (${r.after < r.before ? '−%' + Math.round((1 - r.after / r.before) * 100) : 'zaten optimize'})` : '';
      row.innerHTML = `<span class="fname" title="${esc(r.name)}">${esc(r.name)}</span>
        <span class="meta">${fmtSize(r.size)}${saved}${r.note ? ` · ${esc(r.note)}` : ''}</span>
        ${r.pdf ? `<button class="btn sm" data-edit>${read ? `${icon('book')}Aç` : `${icon('edit')}Düzenle`}</button>` : ''}
        ${canShare() ? `<button class="btn sm" data-share title="${SHARE_HINT}">${icon('share')}Paylaş</button>` : ''}
        <button class="btn sm primary" data-save title="Kaydedilecek yeri seçin">${icon('save')}Kaydet…</button>`;
      const sh = $('[data-share]', row);
      if (sh) sh.onclick = () => shareFile({ outId: r.id, name: r.name, anchor: sh });
      $('[data-save]', row).onclick = async () => {
        try {
          const where = await saveOutput(r, dir);
          if (where) showSaved(row, where);
        } catch { /* toast gösterildi */ }
      };
      const ed = $('[data-edit]', row);
      if (ed) ed.onclick = () => openOutputInEditor(r.id, !read);
    }
    box.append(row);
  }
  if (ok.length > 1) {
    const all = document.createElement('div');
    all.className = 'actions';
    all.innerHTML = `<button class="btn">${icon('folder')}Tümünü bir klasöre kaydet…</button><span class="muted small" id="save-all-info"></span>`;
    $('button', all).onclick = async () => {
      try {
        const res = await saveOutputs(ok, dir);
        if (!res) return;
        toast(`${res.paths.length} dosya kaydedildi: ${shortPath(res.dir)}`, 'ok');
        const info = $('#save-all-info', all);
        info.textContent = `✓ ${shortPath(res.dir)}`;
        if (NATIVE) {
          info.insertAdjacentHTML('afterend', `<button class="btn sm ghost">${icon('folder')}Finder'da göster</button>`);
          info.nextElementSibling.onclick = () => native({ action: 'reveal', path: res.paths[0] });
        }
      } catch { /* toast gösterildi */ }
    };
    box.append(all);
  }
  box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// Kaydedilen yeri sonuç satırında göster (Mac'te Finder'da gösterme düğmesiyle)
function showSaved(row, where) {
  $('.saved-to', row)?.remove();
  const el = document.createElement('span');
  el.className = 'saved-to';
  el.title = where;
  el.innerHTML = `${icon('check')}${esc(shortPath(where))}`;
  if (NATIVE && /^([a-z]:[\\/]|\/)/i.test(where)) {
    el.classList.add('link');
    el.title = 'Finder\'da göster';
    el.onclick = () => native({ action: 'reveal', path: where });
  }
  $('.meta', row).after(el);
}

// Aracın oluşturduğu PDF'i bu sekmede aç (açık belge varsa onun yerine); edit: düzenleme araçları açık gelsin
async function openOutputInEditor(outId, edit = true) {
  if (window.PDFSTUDYO_unsaved?.() && !confirm('Açık belgede kaydedilmemiş değişiklikler var. Belge kapatılıp yeni dosya açılsın mı?')) return;
  try {
    const info = await withBusy('Belge açılıyor…', () => postJSON('/api/edit/open', { out_id: outId }));
    window.Reader.useSession(info, 0, edit);
    location.hash = '#/reader';
  } catch { /* toast */ }
}

