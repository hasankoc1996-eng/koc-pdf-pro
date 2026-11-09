/* Koç PDF Pro — KVKK karartma, sorun bildirme, güncelleme ve Ayarlar pencereleri. */
'use strict';

// ------------------------------------------------------------------ KVKK: kişisel verileri karartma
// Okuyucu ve düzenleyici kullanır. Belgede kişisel veriler aranır, kullanıcı listeden seçer; seçilenler tek
// adımda kalıcı olarak karartılır (onApply: { op: 'redact_areas', areas, clean_meta } işlemini uygular).
const PD_HINT = 'Belgede ad soyad, T.C. kimlik no, vergi kimlik no, IBAN, kart numarası, telefon ve e-posta aranır. Ad soyadlar sık kullanılan '
  + 'adlardan tanınır, bu kişilerin tek başına geçen soyadları da listelenir; bulunamayan bir adı ya da başka kelimeleri aşağıya yazabilirsiniz. Karartma kalıcıdır: altındaki yazı '
  + 'belgeden silinir (Geri Al ile geri alınabilir).';
// Başka numaralarla karışabilen türler: grubun başında uyarı
const PD_NOTE = {
  vkn: 'Başka 10 haneli numaralar (dekont, abone, müşteri no…) da bu denetimden geçebilir; vergi numarası olmayanların işaretini kaldırın.',
};

function personalDataDialog({ sid, onApply, signed }) {
  const m = modal({
    title: 'Kişisel verileri karart (KVKK)', width: 640,
    body: `<p class="muted small" style="margin:0 0 12px">${esc(PD_HINT)}${signed
        ? ' <b>Belge e-imzalı:</b> karartılan yazı dosyada saklı kalmasın diye belge baştan yazılır; e-imza geçersiz olur. İmzalı hâli korumak için sonucu Farklı Kaydet ile ayrı bir dosyaya kaydedin.' : ''}</p>
      <div class="pd-terms"><input class="input" id="pd-terms" placeholder="Ek olarak aranacak adlar ya da kelimeler (virgülle ayırın)">
        <button class="btn" id="pd-search">${icon('search')}Ara</button></div>
      <div class="pd-list" id="pd-list"><p class="muted small">Aranıyor…</p></div>
      <label class="check pd-meta"><input type="checkbox" id="pd-meta">Belge bilgilerini de temizle (yazar, başlık, konu…)</label>`,
    foot: `<button class="btn" data-x>Vazgeç</button><button class="btn primary" id="pd-apply" disabled>Seçilenleri karart</button>`,
  });
  const $m = sel => $(sel, m.el);
  let items = [];
  $('[data-x]', m.el).onclick = m.close;

  const count = () => {
    const n = $$('.pd-item input:checked', m.el).length;
    const meta = $m('#pd-meta').checked;
    const btn = $m('#pd-apply');
    btn.disabled = !n && !meta;
    btn.textContent = n ? `Seçilenleri karart (${n})` : meta ? 'Belge bilgilerini temizle' : 'Seçilenleri karart';
  };

  const render = (res) => {
    items = res.items || [];
    const box = $m('#pd-list');
    if (!res.has_text) {
      box.innerHTML = `<p class="note warn">Belgede okunabilir metin bulunamadı. Kişisel verileri “Düzenle › Karart” aracıyla
        sayfada sürükleyerek kapatabilirsiniz.</p>`;
      return count();
    }
    // Taranmış sayfalar yazısı tanınarak arandı: tanıma hatalı okuyabilir
    const scanned = res.scanned || [];
    const scanNote = scanned.length ? `<p class="note pd-scan">${icon('scan')}<span><b>${scanned.length === 1
        ? `Sayfa ${scanned[0] + 1} taranmış` : `${scanned.length} sayfa taranmış`}:</b> yazısı tanınarak arandı. Tanıma bazı harf
        ve rakamları yanlış okuyabilir; sonuçları ve sayfaları gözle de kontrol edin. Kaçan bir yeri metni seçip sağ tık ›
        Karart ile ya da “Düzenle › Karart” aracıyla kapatabilirsiniz.</span></p>` : '';
    if (!items.length) {
      box.innerHTML = scanNote + '<p class="muted">Kişisel veri bulunamadı. Tanınmayan adları ya da başka kelimeleri yukarıdan arayabilirsiniz.</p>';
      return count();
    }
    const groups = new Map();
    items.forEach((it, i) => { if (!groups.has(it.label)) groups.set(it.label, []); groups.get(it.label).push(i); });
    box.innerHTML = scanNote + [...groups].map(([label, idx]) => `<div class="pd-group">
        <label class="check pd-group-head"><input type="checkbox" checked data-group="${esc(label)}"><b>${esc(label)}</b>
          <span class="muted small">${idx.length}</span></label>
        ${PD_NOTE[items[idx[0]].kind] ? `<p class="muted small pd-note">${esc(PD_NOTE[items[idx[0]].kind])}</p>` : ''}
        ${idx.map(i => {
          const it = items[i];
          const ctx = esc(it.context).replace(esc(it.text), `<mark>${esc(it.text)}</mark>`);
          return `<label class="pd-item" data-group="${esc(label)}"><input type="checkbox" checked data-i="${i}">
            <span><span class="pd-ctx">${ctx}</span><span class="muted small"> · Sayfa ${it.page + 1}${scanned.includes(it.page) ? ' (taranmış)' : ''}${it.places > 1 ? ` · ${it.places} yerde` : ''}</span></span></label>`;
        }).join('')}</div>`).join('');
    $$('[data-group]', box).forEach(g => {
      if (g.tagName !== 'INPUT') return;
      g.onchange = () => { $$(`.pd-item[data-group="${CSS.escape(g.dataset.group)}"] input`, box).forEach(c => c.checked = g.checked); count(); };
    });
    $$('.pd-item input', box).forEach(c => c.onchange = count);
    count();
  };

  const search = async () => {
    const terms = $m('#pd-terms').value.split(/[,\n]/).map(t => t.trim()).filter(t => t.length >= 2);
    const list = $m('#pd-list');
    list.innerHTML = '<p class="muted small">Aranıyor…</p>';
    // Taranmış sayfaların yazısı tanınırken (sayfa başına yaklaşık bir saniye) ne olduğunu söyle
    const slow = setTimeout(() => {
      if (list.querySelector('.muted')?.textContent === 'Aranıyor…') {
        list.innerHTML = '<p class="muted small">Aranıyor… Taranmış sayfaların yazısı tanınıyor; sayfa sayısına göre biraz sürebilir.</p>';
      }
    }, 1500);
    try { render(await postJSON(`/api/edit/${sid}/personal-data`, { terms })); }
    catch (e) { list.innerHTML = `<p class="note warn">${esc(e.message)}</p>`; }
    finally { clearTimeout(slow); }
  };
  $m('#pd-search').onclick = search;
  $m('#pd-terms').onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); search(); } };
  $m('#pd-meta').onchange = count;
  $m('#pd-apply').onclick = async () => {
    const chosen = $$('.pd-item input:checked', m.el).map(c => items[+c.dataset.i]);
    const areas = chosen.map(it => ({ page: it.page, rects: it.rects }));
    const ok = await onApply({ op: 'redact_areas', areas, clean_meta: $m('#pd-meta').checked });
    if (ok !== false) {
      m.close();
      toast(chosen.length ? `${chosen.length} kişisel veri karartıldı.` : 'Belge bilgileri temizlendi.', 'ok');
    }
  };
  search();
}

// ------------------------------------------------------------------ sorun bildir
// Kullanıcının notu, sürüm, sistem bilgisi ve uygulama kaydı bir rapor dosyasına yazılır. E-posta rapor ekli açılır
// (Mac: sistemin e-posta hizmeti; Windows: Outlook ya da Basit MAPI). Olmazsa e-posta mailto ile açılır, rapor
// dosyası klasöründe gösterilir (kullanıcı ekler).
function reportDialog() {
  const m = modal({
    title: 'Sorun bildir', width: 600,
    body: `<p class="muted small" style="margin:0 0 10px">Ne yaparken ne olduğunu kısaca yazın. Rapora uygulamanın sürümü,
        sistem bilgisi ve uygulama kaydının son satırları eklenir; belgelerinizin içeriği eklenmez. E-postayı göndermeden önce
        görebilirsiniz.</p>
      <textarea class="input" id="rp-msg" rows="5" placeholder="Örn. Word → PDF dönüştürürken uygulama yanıt vermedi."></textarea>
      <details class="rp-details"><summary class="small">Rapora eklenecek bilgiyi göster</summary><pre id="rp-text">Yükleniyor…</pre></details>`,
    foot: `<button class="btn" data-x>Vazgeç</button><button class="btn primary" id="rp-send">${icon('mail')}E-postayı hazırla</button>`,
  });
  $('[data-x]', m.el).onclick = m.close;
  api('/api/report').then(r => { $('#rp-text', m.el).textContent = r.text; }, () => { $('#rp-text', m.el).textContent = 'Bilgi alınamadı.'; });
  $('#rp-msg', m.el).focus();
  $('#rp-send', m.el).onclick = async () => {
    let r;
    try { r = await withBusy('Rapor hazırlanıyor…', () => postJSON('/api/report', { message: $('#rp-msg', m.el).value })); } catch { return; }
    m.close();
    const mailto = `mailto:${r.to}?subject=${encodeURIComponent(r.subject)}&body=${encodeURIComponent(r.body)}`;
    const mail = { to: r.to, subject: r.subject, body: r.body, path: r.path };
    const attached = HOST === 'mac'
      ? await Promise.race([nativeAsk('mail', mail), new Promise(res => setTimeout(() => res(null), 2000))])   // eski kabuk bu isteği tanımaz
      : HOST === 'win'   // Outlook ya da Basit MAPI; olmazsa kabuk e-postayı mailto ile açar
        ? await withBusy('E-posta programı açılıyor…', () => nativeAsk('mail', { ...mail, url: mailto })) === 'attached'
        : false;
    if (attached) return toast('E-posta rapor ekli olarak açıldı; göndermeniz yeterli.', 'ok');
    if (HOST !== 'win') { const a = document.createElement('a'); a.href = mailto; a.click(); }
    if (NATIVE) native({ action: 'reveal', path: r.path });
    toast(NATIVE ? `E-posta açıldı. Klasörde gösterilen ${baseName(r.path)} dosyasını e-postaya ekleyin.`
      : `E-posta açıldı. Rapor dosyası: ${shortPath(r.path)}`, 'ok');
  };
}

// ------------------------------------------------------------------ güncelleme
// Kurulum paketinde açılıştan biraz sonra yeni sürüm denetlenir; varsa sekme çubuğunda "Güncelleme hazır" rozeti çıkar.
async function checkUpdate() {
  if (!state.settings.autoUpdate) return;   // Ayarlar › Güncelleme
  let u;
  try { u = await api('/api/update'); } catch { return; }
  if (!u.available || strip.update) return;
  strip.update = u;
  renderTabStrip();
}

function updateDialog(u) {
  const mb = n => (n / 1048576).toLocaleString('tr-TR', { maximumFractionDigits: 0 }) + ' MB';
  const m = modal({
    title: 'Güncelleme', width: 520,
    body: `<p style="margin-top:0">Koç PDF Pro'nun yeni sürümü hazır. İndirilip doğrulandıktan sonra kurulum açılır;
        uygulama kapanır, kurulum bitince yeniden açabilirsiniz. Ayarlarınız ve imzanız korunur.</p>
      <p class="muted small">Yüklü sürüm: ${esc(u.current)} · Yeni sürüm: ${esc(u.surum)}${u.boyut ? ' · ' + mb(u.boyut) : ''}</p>
      ${u.notlar ? `<div class="up-notes"><b class="small">Yenilikler</b><p>${esc(u.notlar)}</p></div>` : ''}
      <div class="up-progress" id="up-progress" hidden><div class="up-bar"><span id="up-bar"></span></div>
        <span class="muted small" id="up-text"></span></div>`,
    foot: `<button class="btn" data-x>Sonra</button><button class="btn primary" id="up-go">${icon('download')}İndir ve kur</button>`,
  });
  const go = $('#up-go', m.el), text = $('#up-text', m.el);
  $('[data-x]', m.el).onclick = m.close;
  go.onclick = async () => {
    if (SHELL?.unsavedCount?.()) return toast('Önce açık belgelerdeki değişiklikleri kaydedin; kurulum uygulamayı kapatır.', 'error');
    go.disabled = true;
    $('#up-progress', m.el).hidden = false;
    let s;
    try { s = await postJSON('/api/update/download'); } catch { go.disabled = false; return; }
    while (s.status === 'downloading') {
      $('#up-bar', m.el).style.width = (s.total ? Math.min(100, 100 * s.received / s.total) : 5) + '%';
      text.textContent = `İndiriliyor… ${mb(s.received)}${s.total ? ' / ' + mb(s.total) : ''}`;
      await new Promise(r => setTimeout(r, 400));
      try { s = await api('/api/update/state'); } catch { s = { status: 'error', error: 'Uygulamayla bağlantı kesildi.' }; }
    }
    if (s.status !== 'ready') { text.textContent = s.error || 'Güncelleme indirilemedi.'; go.disabled = false; return; }
    $('#up-bar', m.el).style.width = '100%';
    text.textContent = 'Doğrulandı. Kurulum açılıyor; Koç PDF Pro kapanacak.';
    try { await postJSON('/api/update/install'); } catch { go.disabled = false; return; }
    if (NATIVE) setTimeout(() => native({ action: 'quit' }), 1500);
    else text.textContent = 'Kurulum açıldı. Bitince Koç PDF Pro\'yu yeniden başlatın.';
  };
}

// ------------------------------------------------------------------ ayarlar
// ⚙ düğmesi (sekme çubuğu) ve ⌘, (Mac: Koç PDF Pro › Ayarlar…). Seçimler hemen uygulanır. Uygulama genelindekiler
// sunucuda (ayarlar.json); gece / gündüz, sayfa görünümü, imza ve kaşe bu bilgisayarın sayfa belleğinde; arayüz
// büyüklüğü Mac / Windows kabuğunda.
async function loadSettings() {
  try {
    const r = await api('/api/settings');
    Object.assign(state, { settings: r.settings, desktop: r.desktop });
  } catch { }
}
async function saveSettings(change) {
  try { state.settings = (await postJSON('/api/settings', change)).settings; return true; }
  catch (e) { toast(e.message, 'error'); return false; }
}
const daysText = n => (n === 365 ? '1 yıl' : n === 180 ? '6 ay' : `${n} gün`);

// Arayüz büyüklüğü (menüler, düğmeler, yazılar): pencere sahibi uygular ve hatırlar. Tarayıcıda yok (tarayıcının kendi yakınlığı var).
async function getUiZoom() {
  if (HOST === 'mac') return window.PDFSTUDYO_UIZOOM || 1;
  if (HOST === 'win') return +(await nativeAsk('getUiZoom')) || 1;
  return null;
}

const SETTINGS_SECTIONS = [
  ['view', 'Görünüm', 'sun'], ['docs', 'Belgeler', 'file'], ['save', 'Kaydetme ve yedek', 'save'],
  ['sign', 'İmza ve kaşe', 'signature'], ['update', 'Güncelleme', 'download'], ['storage', 'Depolama', 'folder'],
];
let settingsSection = 'view';   // pencere yeniden açılınca son bakılan bölüm

// checkNow: bölüm açılınca yeni sürüme hemen bakılır (Hakkında › Güncellemeleri denetle, Mac menüsü)
function settingsDialog(section, checkNow = false) {
  if ($('.set-dialog')) return;
  if (section) settingsSection = section;
  const onDefault = e => paintDefault(e.detail.isDefault);
  document.addEventListener('pdfdefault', onDefault);
  const m = modal({
    title: 'Ayarlar', width: 840,
    body: `<div class="set-dialog"><nav class="set-nav">${SETTINGS_SECTIONS.map(([id, label, ic]) =>
      `<button type="button" data-sec="${id}">${icon(ic)}<span>${label}</span></button>`).join('')}</nav>
      <div class="set-body"></div></div>`,
    foot: '<button class="btn primary" data-ok>Tamam</button>',
    onClose: () => document.removeEventListener('pdfdefault', onDefault),
  });
  $('[data-ok]', m.el).onclick = m.close;
  const body = $('.set-body', m.el);
  const ls = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    json(k) { try { return JSON.parse(localStorage.getItem(k) || 'null'); } catch { return null; } },
    remove(k) { try { localStorage.removeItem(k); } catch { } },
  };
  let storage = null;

  // Satır: solda ad ve açıklama, sağda seçim
  const row = (title, hint, ctl) => `<div class="set-row"><div class="set-label"><b>${title}</b>${hint ? `<span class="muted small">${hint}</span>` : ''}</div>
    <div class="set-ctl">${ctl}</div></div>`;
  const seg = (name, items, cur) => `<div class="seg sm" data-seg="${name}">${items.map(([v, label]) =>
    `<button type="button" data-v="${v}" class="${String(v) === String(cur) ? 'on' : ''}">${esc(label)}</button>`).join('')}</div>`;
  const sel = (name, items, cur) => `<select class="input" data-sel="${name}">${items.map(([v, label]) =>
    `<option value="${v}" ${v === cur ? 'selected' : ''}>${esc(label)}</option>`).join('')}</select>`;
  const sw = (name, on, off = false) => `<label class="switch"><input type="checkbox" data-chk="${name}" ${on ? 'checked' : ''} ${off ? 'disabled' : ''}><span></span></label>`;
  const btn = (act, label, off = false) => `<button type="button" class="btn sm" data-act="${act}" ${off ? 'disabled' : ''}>${label}</button>`;
  const confirmDelete = (title, text) => askChoice({
    title, body: `<p style="margin:0">${text}</p>`, choices: [{ id: '', label: 'Vazgeç' }, { id: 'yes', label: 'Sil', primary: true }],
  });

  const sections = {
    async view() {
      const zoom = await getUiZoom(), v = window.Reader.view();
      const zooms = [...new Set([0.8, 0.9, 1, 1.1, 1.2, 1.3, 1.5, ...(zoom ? [zoom] : [])])].sort((a, b) => a - b);
      return row('Gece / gündüz', `Otomatik: ${IS_WIN ? 'Windows\'un' : 'Mac\'in'} ayarını izler.`,
        seg('theme', THEME_ORDER.map(t => [t, THEMES[t].label]), getTheme()))
        + (zoom ? row('Arayüz büyüklüğü', 'Menüler, düğmeler ve yazılar. Belgenin yakınlığı ayrıdır.',
          seg('zoom', zooms.map(z => [z, '%' + Math.round(z * 100)]), zoom)) : '')
        + row('Sayfa düzeni', 'Belgeler bu düzende açılır; okurken araç çubuğundaki Görünüm düğmesinden de değişir.',
          seg('spread', [[0, 'Tek sayfa'], [1, 'İki sayfa']], +v.spread))
        + row('Kaydırma', 'Kapalıyken sayfalar tek tek gösterilir; tekerlek ve ok tuşları sayfa çevirir.', sw('scroll', v.scroll))
        + row('Kapak sayfası ayrı', 'İki sayfa düzeninde ilk sayfa, kitap kapağı gibi tek başına durur.', sw('cover', v.cover, !v.spread));
    },
    async docs() {
      let recent = 0;
      try { recent = (await api('/api/recent')).items.length; } catch { }
      return row('Adınız', 'Eklediğiniz not ve vurgularda yazar olarak görünür; belgeyi açan başka PDF programlarında da. Önceden eklenenler değişmez.',
        `<input class="input set-name" data-text="author" maxlength="60" aria-label="Adınız" value="${esc(state.settings.author)}">`)
        + row('Kaldığım sayfadan aç', 'Bir belgeyi yeniden açınca en son baktığınız sayfaya gider.', sw('resumePage', state.settings.resumePage))
        + row('Son açılanlar', recent ? `Listede ${recent} belge var. Yalnız liste temizlenir, dosyalara dokunulmaz.` : 'Liste boş.',
          btn('clearRecent', 'Listeyi temizle', !recent))
        + (HOST === 'mac' ? row('Varsayılan PDF uygulaması', '<span id="set-default">Denetleniyor…</span>', '<span id="set-default-btn"></span>')
          : HOST === 'win' ? row('Varsayılan PDF uygulaması', 'PDF\'lere çift tıklayınca Koç PDF Pro\'nun açılması için Windows ayarlarında .pdf türüne Koç PDF Pro\'yu seçin.',
            btn('winDefault', 'Windows ayarlarını aç')) : '');
    },
    async save() {
      const s = state.settings;
      return row('Farklı Kaydet önce şu klasörü açsın', 'Araçların sonuçlarını kaydederken de geçerlidir.',
        seg('saveFolder', [['doc', 'Belgenin klasörü'], ['last', 'En son kullanılan'], ['desktop', 'Masaüstü']], s.saveFolder))
        + row('Önceki sürümler', 'Bir dosyanın üzerine kaydederken eski hâli yedeklenir; belgede Önceki sürümler düğmesiyle açılıp geri yüklenebilir.',
          sel('backupKeep', [3, 5, 10, 20, 50].map(n => [n, `Son ${n} sürüm`]), s.backupKeep)
          + sel('backupDays', [7, 30, 60, 180, 365].map(n => [n, `${daysText(n)} boyunca`]), s.backupDays))
        + row('Kurtarılabilir belgeler', 'Kaydetmeden kapatılan ya da uygulama beklenmedik kapanınca kalan değişiklikler bu kadar saklanır.',
          sel('recoverDays', [1, 3, 7, 14, 30].map(n => [n, daysText(n)]), s.recoverDays));
    },
    async sign() {
      const sig = ls.get('pdfstudyo.signature'), stamp = ls.json('pdfstudyo.stamp');
      return '<p class="muted small set-intro">Bu bilgisayarda saklanır; belgeye düzenleme araçlarındaki İmza ve Kaşe ile eklenir.</p>'
        + row('İmza', '', (sig ? `<img class="set-sig" src="${esc(sig)}" alt="Kayıtlı imza">` : '<span class="muted small">Kayıtlı imza yok</span>')
          + btn('sigDraw', sig ? 'Değiştir' : 'İmza çiz') + (sig ? btn('sigDelete', 'Sil') : ''))
        + row('Kaşe', '', (stamp?.text ? `<span class="set-stamp">${window.Editor.stampPreview(stamp)}</span>` : '<span class="muted small">Kayıtlı kaşe yok</span>')
          + btn('stampEdit', stamp?.text ? 'Değiştir' : 'Kaşe oluştur') + (stamp?.text ? btn('stampDelete', 'Sil') : ''));
    },
    async update() {
      // Proje klasöründen çalışan geliştirme kopyası güncellenmez: kurulum paketi onun yerine kurulmasın
      const live = state.packaged;
      return row('Yüklü sürüm', `<span class="ver-badge">${esc(state.version || '?')}</span>${live ? ''
        : ' Geliştirme kopyası (proje klasöründen çalışıyor); güncellemeler yalnızca kurulan uygulamada denetlenir.'}`, '')
        + row('Yeni sürümleri kendiliğinden denetle', 'Açılışta ve 6 saatte bir bakılır; yeni sürüm varsa sekme çubuğunda “Güncelleme hazır” çıkar. İndirip kurmadan önce her zaman sorulur.',
          sw('autoUpdate', state.settings.autoUpdate))
        + row('Şimdi denetle', '<span id="set-upd">Yeni sürüm olup olmadığına hemen bakar.</span>', btn('checkNow', 'Denetle', !live))
        + row('Sürüm notları', 'Yayımlanan bütün sürümler, yenilikleri ve kurulum dosyaları GitHub\'daki Sürümler sayfasında.',
          `<a class="btn sm" href="${SOURCE.url}/releases" data-ext>Sürümler sayfası ↗</a>`);
    },
    async storage() {
      try { storage = await api('/api/storage'); } catch { return '<p class="muted">Bilgi alınamadı.</p>'; }
      const st = storage;
      return row('Geçici dosyalar', `${fmtSize(st.temp)} · dönüştürme ve araç sonuçlarının kopyaları; 6 saatte bir kendiliğinden silinir.`,
        btn('cleanTemp', 'Temizle', !st.temp))
        + row('Önceki sürümler', st.backup_count ? `${st.backup_count} yedek dosya · ${fmtSize(st.backups)}` : 'Yedek yok.',
          btn('cleanBackups', 'Hepsini sil', !st.backup_count))
        + row('Kurtarılabilir belgeler', st.recover ? `Kaydedilmemiş değişiklikleri olan ${st.recover} belge` : 'Yok.',
          st.recover ? btn('showRecover', 'Göster') : '')
        + (NATIVE ? row('Veri klasörü', esc(shortPath(st.data)), btn('reveal', 'Klasörü göster')) : '');
    },
  };

  // Mac: varsayılan PDF uygulaması mı (yanıt reader.js'teki PDFSTUDYO_defaultStatus'tan olayla gelir)
  function paintDefault(isDefault) {
    const text = $('#set-default', m.el), slot = $('#set-default-btn', m.el);
    if (!text) return;
    text.textContent = isDefault ? 'Koç PDF Pro varsayılan PDF uygulamanız; Finder\'da PDF\'e çift tıklayınca burada açılır.'
      : 'PDF\'ler şu an başka bir uygulamayla açılıyor.';
    slot.innerHTML = isDefault ? '' : btn('setDefault', 'Varsayılan yap');
  }

  // Yedek sınırı düşerse dışında kalan eski sürümler hemen silinir: önce sorulur
  async function setBackups(change) {
    const next = { ...state.settings, ...change };
    let count = 0;
    try { count = (await api(`/api/backups/prune-preview?keep=${next.backupKeep}&days=${next.backupDays}`)).count; } catch { }
    if (count && !await confirmDelete('Eski sürümler silinecek',
      `Yeni sınırın dışında kalan <b>${count}</b> eski sürüm hemen silinecek. Bu geri alınamaz; asıl dosyalarınıza dokunulmaz.`)) return render();
    await saveSettings(change);
    render();
  }

  const on = {
    theme: v => setTheme(v, false),
    zoom: v => { window.PDFSTUDYO_UIZOOM = +v; native({ action: 'uiZoom', value: +v }); },
    spread: v => { window.Reader.setView({ spread: v === '1' }); render(); },
    scroll: checked => window.Reader.setView({ scroll: checked }),
    cover: checked => window.Reader.setView({ cover: checked }),
    resumePage: checked => saveSettings({ resumePage: checked }),
    async author(value, input) {
      const name = value.split(/\s+/).filter(Boolean).join(' ');
      input.value = name;
      if (name === state.settings.author || !await saveSettings({ author: name })) return;
      toast(state.settings.author ? `Notlarda yazar: ${state.settings.author}` : 'Notlara ad yazılmayacak.', 'ok');
    },
    autoUpdate: checked => saveSettings({ autoUpdate: checked }),
    saveFolder: v => saveSettings({ saveFolder: v }),
    recoverDays: n => saveSettings({ recoverDays: n }),
    backupKeep: n => setBackups({ backupKeep: n }),
    backupDays: n => setBackups({ backupDays: n }),
    async clearRecent() {
      try { await postJSON('/api/recent/remove', {}); } catch (e) { return toast(e.message, 'error'); }
      native({ action: 'clearRecent' });   // Mac: Dosya › Son Açılanlar menüsü de
      toast('Son açılanlar listesi temizlendi.', 'ok');
      for (const box of [$('#home-recent'), $('#rd-recent')]) if (box) renderRecent(box);
      render();
    },
    setDefault: () => native({ action: 'setDefaultPDF' }),
    winDefault: () => native({ action: 'defaultApps' }),
    sigDraw: () => window.Editor.signatureDialog({ saveOnly: true, onSaved: render }),
    stampEdit: () => window.Editor.stampDialog({ saveOnly: true, onSaved: render }),
    async sigDelete() {
      if (!await confirmDelete('İmzayı sil', 'Bu bilgisayarda kayıtlı imzanız silinsin mi? Belgelere eklediğiniz imzalara dokunulmaz.')) return;
      ls.remove('pdfstudyo.signature');
      render();
    },
    async stampDelete() {
      if (!await confirmDelete('Kaşeyi sil', 'Kayıtlı kaşe bilgileriniz silinsin mi? Belgelere bastığınız kaşelere dokunulmaz.')) return;
      ls.remove('pdfstudyo.stamp');
      render();
    },
    async checkNow(b) {
      const msg = $('#set-upd', m.el);
      b.disabled = true;
      msg.textContent = 'Denetleniyor…';
      let u = null;
      try { u = await api('/api/update?yeniden=1'); } catch { }
      b.disabled = false;
      if (!msg.isConnected) return;
      if (u?.available) {
        msg.textContent = `Yeni sürüm hazır: ${u.surum}`;
        strip.update = u;
        renderTabStrip();
        updateDialog(u);
      } else msg.textContent = u?.surum ? 'Koç PDF Pro güncel.' : 'Denetlenemedi; internet bağlantınızı kontrol edip yeniden deneyin.';
    },
    async cleanTemp() {
      try { await postJSON('/api/storage/clean', { what: 'temp' }); } catch (e) { return toast(e.message, 'error'); }
      toast('Geçici dosyalar temizlendi; son 15 dakikada kullanılanlar bırakıldı.', 'ok');
      render();
    },
    async cleanBackups() {
      if (!await confirmDelete('Önceki sürümleri sil', `Bütün dosyaların önceki sürümleri (${storage.backup_count} yedek, ${fmtSize(storage.backups)})
        silinsin mi? Bu geri alınamaz; asıl dosyalarınıza dokunulmaz.`)) return;
      try { await postJSON('/api/storage/clean', { what: 'backups' }); } catch (e) { return toast(e.message, 'error'); }
      toast('Önceki sürümler silindi.', 'ok');
      render();
    },
    showRecover: () => { m.close(); recoverDialog(); },
    reveal: () => native({ action: 'reveal', path: storage.data }),
  };

  body.addEventListener('click', e => {
    const b = e.target.closest('button');
    if (!b || b.disabled) return;
    const group = b.closest('[data-seg]');
    if (group) {
      if (b.classList.contains('on')) return;
      $$('button', group).forEach(x => x.classList.toggle('on', x === b));
      return on[group.dataset.seg](b.dataset.v);
    }
    if (b.dataset.act) on[b.dataset.act](b);
  });
  body.addEventListener('change', e => {
    const t = e.target;
    if (t.dataset.chk) on[t.dataset.chk](t.checked);
    else if (t.dataset.sel) on[t.dataset.sel](+t.value);
    else if (t.dataset.text) on[t.dataset.text](t.value, t);   // yazı kutusu: Enter'da ya da kutudan çıkınca
  });
  body.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.dataset.text) e.target.blur(); });

  let seq = 0;
  async function render() {
    const my = ++seq, sec = settingsSection, top = body.dataset.sec === sec ? body.scrollTop : 0;
    $$('[data-sec]', m.el).forEach(b => b.classList.toggle('on', b.dataset.sec === sec));
    const html = await sections[sec]();
    if (my !== seq || !m.el.isConnected) return;
    body.dataset.sec = sec;
    body.innerHTML = `<h3>${SETTINGS_SECTIONS.find(x => x[0] === sec)[1]}</h3>${html}`;
    body.scrollTop = top;
    bindExternalLinks(body);
    if (sec === 'docs' && HOST === 'mac') native({ action: 'defaultStatus' });
    if (sec === 'update' && checkNow) {
      checkNow = false;
      const b = $('[data-act="checkNow"]', body);
      if (b && !b.disabled) on.checkNow(b);
    }
  }
  $$('[data-sec]', m.el).forEach(b => b.onclick = () => { settingsSection = b.dataset.sec; render(); });
  render();
}
// Mac uygulamasında Koç PDF Pro › Ayarlar… (⌘,) ve › Güncellemeleri Denetle… bunları çağırır
window.PDFSTUDYO_settings = () => settingsDialog();
window.PDFSTUDYO_checkUpdates = () => settingsDialog('update', true);

