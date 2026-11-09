/* Koç PDF Pro — sekme çubuğu, araç çubuğu, sağ tık menüsü, Hakkında penceresi ve klavye kısayolları. */
'use strict';

// ------------------------------------------------------------------ sekme çubuğu
// Mac uygulamasında her sekme ayrı bir sayfadır; uygulama tüm sekmelerin listesini her sayfaya gönderir
// (PDFSTUDYO_tabs). Tarayıcıda / Windows'ta yalnızca bu pencerenin sekmesi gösterilir.
const strip = { tabs: null, local: { title: 'Koç PDF Pro', path: null }, unsaved: false,
  update: null,     // yeni sürüm bilgisi (varsa "Güncelleme hazır" rozeti)
  recover: 0 };     // kurtarılabilir belge sayısı
window.PDFSTUDYO_tabs = list => { strip.tabs = list; renderTabStrip(); };

// Açık sekmelerdeki belgelerin yolları (yerel uygulamada); bilinmiyorsa null
const openTabPaths = () => (strip.tabs ? strip.tabs.map(t => t.path).filter(Boolean) : null);

function renderTabStrip() {
  const el = $('#tabstrip');
  if (!el) return;
  const tabs = strip.tabs || [{
    id: 'self', title: strip.local.title, path: strip.local.path, active: true, local: true, unsaved: strip.unsaved,
    doc: !!window.Reader?.hasDoc?.(),
  }];
  const theme = THEMES[getTheme()];
  el.innerHTML = `<button class="strip-btn strip-home" id="strip-home" data-tip="Ana Sayfa" aria-label="Ana Sayfa">
      <img src="/static/logo.png" alt=""></button>`
    + tabs.map(t => `<div class="tab ${t.active ? 'active' : ''} ${t.unsaved ? 'unsaved' : ''}" data-id="${t.id}"
      data-tip="${esc(t.path ? shortPath(t.path) : t.title)}${t.unsaved ? ' — kaydedilmemiş değişiklikler var' : ''}">
      <span class="t-icon">${icon(t.doc ? 'file' : 'home')}</span><span class="t-title">${esc(t.title)}</span>
      ${t.local ? (t.unsaved ? '<span class="t-dot"></span>' : '')
        : `<button class="t-close" data-close="${t.id}" aria-label="Sekmeyi kapat">${icon('close')}</button>`}</div>`).join('')
    + (strip.tabs ? `<button class="tab-new" id="tab-new" data-tip="Yeni sekme (⌘T)" aria-label="Yeni sekme">${icon('plus')}</button>` : '')
    + `<span class="strip-spacer"></span>
       ${strip.recover ? `<button class="strip-badge warn" id="strip-recover" data-tip="Kaydedilmemiş değişiklikleri olan belgeler: açın ya da silin">${icon('history')}<span>Kurtarılabilir belge (${strip.recover})</span></button>` : ''}
       ${strip.update ? `<button class="strip-badge" id="strip-update" data-tip="Yeni sürüm ${esc(strip.update.surum)}: indirip kurmak için tıklayın">${icon('download')}<span>Güncelleme hazır</span></button>` : ''}
       <button class="strip-btn" id="strip-theme" data-tip="Görünüm: ${theme.label} — değiştirmek için tıklayın" aria-label="Görünüm: ${theme.label}">${icon(theme.icon)}</button>
       <button class="strip-btn" id="strip-settings" data-tip="Ayarlar (${esc(keyLabel('⌘,'))})" aria-label="Ayarlar">${icon('gear')}</button>
       <button class="strip-btn" id="strip-guide" data-tip="Kullanım kılavuzu" aria-label="Kullanım kılavuzu">${icon('help')}</button>
       <button class="strip-btn" id="strip-about" data-tip="Hakkında: sürüm, iletişim, sorun bildir" aria-label="Hakkında">${icon('info')}</button>`;
  $$('.tab', el).forEach(t => t.onclick = e => {
    const close = e.target.closest('[data-close]');
    if (close) { e.stopPropagation(); return native({ action: 'closeTab', id: +close.dataset.close }); }
    if (strip.tabs && !t.classList.contains('active')) native({ action: 'selectTab', id: +t.dataset.id });
  });
  $$('.tab', el).forEach(t => t.onauxclick = e => { if (e.button === 1 && strip.tabs) native({ action: 'closeTab', id: +t.dataset.id }); });
  const add = $('#tab-new', el);
  if (add) add.onclick = () => native({ action: 'newTab' });
  $('#strip-theme', el).onclick = () => setTheme(THEME_ORDER[(THEME_ORDER.indexOf(getTheme()) + 1) % THEME_ORDER.length]);
  $('#strip-home', el).onclick = () => { location.hash = '#/'; };
  $('#strip-settings', el).onclick = () => settingsDialog();
  $('#strip-about', el).onclick = aboutDialog;
  $('#strip-guide', el).onclick = () => openGuide();
  const rec = $('#strip-recover', el), upd = $('#strip-update', el);
  if (rec) rec.onclick = () => recoverDialog();
  if (upd) upd.onclick = () => updateDialog(strip.update);
}

// Tarayıcıda: kaydedilmemiş değişiklik işareti sekmede de görünsün
if (!NATIVE && !SHELL) setInterval(() => {
  const u = !!window.PDFSTUDYO_unsaved?.();
  if (u !== strip.unsaved && !strip.tabs) { strip.unsaved = u; renderTabStrip(); }
}, 700);

// ------------------------------------------------------------------ araç çubuğu
// Simge düğmesi: ipucu (data-tip) üzerine gelince hemen altında görünür
function tbBtn(id, iconName, tip, cls = '') {
  return `<button class="tb-btn ${cls}" id="${id}" data-tip="${esc(tip)}" aria-label="${esc(tip)}">${icon(iconName)}</button>`;
}
const tbSep = () => '<span class="tb-sep"></span>';

// Belge açık değilken (ana sayfa, boş okuyucu) de aynı araç çubuğu durur: belge açılınca pencere düzeni kaymaz.
// Belgeye bağlı düğmeler soluktur (üzerine gelince "önce bir PDF açın"); PDF aç ve Araçlar çalışır.
function idleToolbar() {
  const off = (iconName, tip) => `<button class="tb-btn off" aria-disabled="true" data-tip="${esc(tip)} · önce bir PDF açın"
    aria-label="${esc(tip)}">${icon(iconName)}</button>`;
  return `<div class="doc-toolbar idle-bar">
    ${off('sidebar', 'Yan panel: sayfalar, içindekiler, notlar')}${tbSep()}
    ${off('save', 'Kaydet')}${off('saveas', 'Farklı Kaydet')}${off('history', 'Önceki sürümler')}
    ${canShare() ? off('share', 'Paylaş') : ''}${NATIVE ? off('copy', 'Dosya olarak kopyala') : ''}${off('printer', 'Yazdır')}${tbSep()}
    ${off('undo', 'Geri al')}${off('redo', 'Yinele')}${tbSep()}
    <div class="tb-group">${off('left', 'Önceki sayfa')}<input class="tb-page" disabled aria-label="Sayfa"><span class="muted tb-total">/ –</span>
      ${off('right', 'Sonraki sayfa')}</div>${tbSep()}
    <div class="tb-group">${off('zoomout', 'Uzaklaştır')}<select class="tb-zoom" disabled aria-label="Yakınlaştırma"><option>Genişlik</option></select>
      ${off('zoomin', 'Yakınlaştır')}</div>${tbSep()}
    ${off('pages2', 'Görünüm: tek sayfa, iki sayfa, kaydırma')}${off('rotcw', 'Sayfayı döndür')}${off('search', 'Belgede ara')}${tbSep()}
    ${off('note', 'Not ekle')}${off('bookmark', 'Yer imi ekle')}${off('shield', 'Kişisel verileri karart (KVKK)')}${tbSep()}
    <button class="tb-text-btn" id="ib-tools" data-tip="Tüm araçlar">${icon('tools')}<span class="tb-lbl">Araçlar</span>${icon('chevdown')}</button>
    <span class="tb-spacer"></span>
    <button class="tb-text-btn" id="ib-open" data-tip="PDF ya da UDF aç${HOST === 'mac' ? ' (⌘O)' : ''}">${icon('folder')}<span class="tb-lbl">PDF aç</span></button>
    <button class="btn sm primary off" aria-disabled="true" data-tip="Düzenle · önce bir PDF açın">${icon('edit')}Düzenle</button>
  </div>`;
}

// open: PDF aç düğmesi (boş okuyucu kendi açma işlevini verir)
function bindIdleToolbar(root, open = openFromHome) {
  $$('.idle-bar .off', root).forEach(b => b.onclick = () => toast('Önce bir PDF açın: “PDF aç” düğmesine basın ya da dosyayı pencereye bırakın.'));
  $('#ib-tools', root).onclick = e => showAllToolsMenu(e.currentTarget);
  $('#ib-open', root).onclick = open;
}

async function openFromHome() {
  if (NATIVE) return native({ action: 'openPDF' });
  const d = await pickDocument();
  if (d?.file) { handoffFiles = [d.file]; location.hash = '#/reader'; }
}

function setupToolbarTips() {
  const tip = document.createElement('div');
  tip.className = 'tb-tip';
  tip.setAttribute('role', 'tooltip');
  document.body.append(tip);
  let timer = 0, current = null;
  const hide = () => { clearTimeout(timer); current = null; tip.classList.remove('show'); };
  document.addEventListener('mouseover', e => {
    const el = e.target.closest('.doc-toolbar [data-tip], .tabstrip [data-tip], .edit-bar [data-tip]');
    if (el === current) return;
    hide();
    if (!el) return;
    current = el;
    timer = setTimeout(() => {
      if (!el.isConnected || current !== el) return;
      const r = el.getBoundingClientRect();
      tip.textContent = el.dataset.tip;
      tip.style.left = Math.min(Math.max(r.left + r.width / 2, 90), innerWidth - 90) + 'px';
      tip.style.top = r.bottom + 8 + 'px';
      tip.classList.add('show');
    }, 280);
  });
  document.addEventListener('mousedown', hide, true);
  document.addEventListener('scroll', hide, true);
}

// Araç listesi açılır kutusu. groups: [[başlık, [araç kimlikleri]], …]
// doc: belge çubuğundaki menü (Dönüştür ve Sıkıştır açık belgeyle açılır)
function toolsMenu(anchor, groups, { doc = false } = {}) {
  const open = $('.tb-menu');
  open?.close();
  if (open?.anchor === anchor) return;   // aynı düğmeye yeniden basıldı: kapat
  const menu = document.createElement('div');
  menu.className = 'tb-menu';
  menu.anchor = anchor;
  menu.innerHTML = groups.map(([title, ids]) => `<div class="tb-menu-title">${esc(title)}</div>` + ids.filter(id => TOOL[id]).map(id => {
    const t = TOOL[id];
    return `<button class="tb-menu-item" data-id="${id}"><span class="tool-icon sm" style="--c:${t.color}">${icon(t.icon)}</span>
      <span><b>${esc(t.title)}</b><span class="muted small">${esc(id === 'convert' && doc ? 'Word, Excel, UDF ya da resim' : t.short)}</span></span></button>`;
  }).join('')).join('');
  document.body.append(menu);
  const r = anchor.getBoundingClientRect();
  menu.style.left = Math.max(8, Math.min(r.left, innerWidth - menu.offsetWidth - 12)) + 'px';
  menu.style.top = r.bottom + 6 + 'px';
  const close = e => {
    if (e && (e.type === 'keydown' ? e.key !== 'Escape' : menu.contains(e.target) || anchor.contains(e.target))) return;
    menu.remove();
    document.removeEventListener('mousedown', close, true);
    document.removeEventListener('keydown', close, true);
  };
  menu.close = close;
  document.addEventListener('mousedown', close, true);
  document.addEventListener('keydown', close, true);
  $$('.tb-menu-item', menu).forEach(b => b.onclick = () => {
    close();
    if (DIALOGS[b.dataset.id]) return DIALOGS[b.dataset.id]({ doc: doc ? openDocView()?.info : null });
    location.hash = toolHref(TOOL[b.dataset.id]);
  });
}

// Belge çubuğundaki "Araçlar ▾": açık belgeyle kullanılabilen araçlar
function showToolsMenu(anchor) {
  toolsMenu(anchor, [
    ['Belgeye uygula', ['numbers', 'watermark', 'compress', ...(state.engines.ocr ? ['ocr'] : []), 'merge']],   // metin tanıma yalnızca Mac'te
    ['Belgeden yeni dosya', ['convert', 'compare', 'split', 'protect', 'unlock']],
  ], { doc: true });
}

// Belgesiz araç çubuğundaki "Araçlar ▾" (ana sayfa, boş okuyucu): bütün araçlar, gruplarıyla
function showAllToolsMenu(anchor) {
  toolsMenu(anchor, GROUPS.map(g => [g, listedTools(g).map(t => t.id)]));
}

// ------------------------------------------------------------------ sağ tık menüsü
// items: {label, icon, run, hint, danger, disabled} | {label, colors: [...], run(renk)} | 'sep' | null (atlanır)
let closeCtxMenu = () => { };
function contextMenu(x, y, items) {
  closeCtxMenu();
  const list = items.filter(Boolean).filter((it, k, a) => it !== 'sep' || (k > 0 && a[k - 1] !== 'sep' && k < a.length - 1));
  if (!list.length) return;
  const menu = document.createElement('div');
  menu.className = 'ctx-menu';
  menu.setAttribute('role', 'menu');
  menu.innerHTML = list.map((it, k) => it === 'sep' ? '<div class="ctx-sep"></div>'
    : it.colors ? `<div class="ctx-colors"><span class="ctx-label">${esc(it.label)}</span>${it.colors.map(c =>
        `<button class="hl-dot" data-k="${k}" data-c="${c}" style="background:${c}" aria-label="${esc(it.label)}"></button>`).join('')}</div>`
    : `<button class="ctx-item ${it.danger ? 'danger' : ''}" role="menuitem" data-k="${k}" ${it.disabled ? 'disabled' : ''}>
        ${it.icon ? icon(it.icon) : '<span class="ctx-noicon"></span>'}<span class="ctx-label">${esc(it.label)}</span>
        ${it.hint ? `<span class="ctx-hint">${esc(it.hint)}</span>` : ''}</button>`).join('');
  document.body.append(menu);
  const w = menu.offsetWidth, h = menu.offsetHeight;   // ekrandan taşmasın
  menu.style.left = Math.max(6, Math.min(x, innerWidth - w - 6)) + 'px';
  menu.style.top = Math.max(6, y + h > innerHeight - 6 ? y - h : y) + 'px';
  const buttons = $$('.ctx-item:not(:disabled), .hl-dot', menu);
  const onKey = e => {
    if (e.key === 'Escape') close();
    else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      const n = buttons.length, k = buttons.indexOf(document.activeElement), down = e.key === 'ArrowDown';
      buttons[k < 0 ? (down ? 0 : n - 1) : (k + (down ? 1 : n - 1)) % n]?.focus();
    } else return;   // Enter ve boşluk: odaktaki düğme çalışır
    e.preventDefault();
    e.stopPropagation();
  };
  const outside = e => { if (!menu.contains(e.target)) close(); };
  const close = () => {
    menu.remove();
    document.removeEventListener('keydown', onKey, true);
    document.removeEventListener('mousedown', outside, true);
    document.removeEventListener('scroll', close, true);
    window.removeEventListener('blur', close);
    window.removeEventListener('resize', close);
    closeCtxMenu = () => { };
  };
  closeCtxMenu = close;
  document.addEventListener('keydown', onKey, true);
  document.addEventListener('mousedown', outside, true);
  document.addEventListener('scroll', close, true);
  window.addEventListener('blur', close);
  window.addEventListener('resize', close);
  menu.addEventListener('mousedown', e => e.preventDefault());   // seçili metin kaybolmasın
  menu.addEventListener('contextmenu', e => e.preventDefault());
  $$('.ctx-item', menu).forEach(b => b.onclick = () => { close(); list[+b.dataset.k].run(); });
  $$('.hl-dot', menu).forEach(b => b.onclick = () => { close(); list[+b.dataset.k].run(b.dataset.c); });
}

// Hakkında: sürüm, künye, iletişim, sorun bildirme
// Geliştiricinin sayfası: ana sayfanın künyesinde ve Hakkında penceresinde
const DEVELOPER = { label: '@murttkcc', url: 'https://x.com/murttkcc' };
// Kaynak kodu ve lisans (AGPL-3.0): Hakkında penceresinde
const SOURCE = { label: 'github.com/hasankoc1996-eng/koc-pdf-pro', url: 'https://github.com/hasankoc1996-eng/koc-pdf-pro' };

// Dış bağlantılar (data-ext) uygulamanın içinde değil, bilgisayarın varsayılan tarayıcısında açılır. Mac kabuğu http
// bağlantısını zaten tarayıcıya verir (sayfa yerinde kalır); Windows'ta pencere sahibi açar; tarayıcıda yeni sekmede.
function bindExternalLinks(root) {
  $$('a[data-ext]', root).forEach(a => a.onclick = e => {
    if (HOST === 'mac') return;
    e.preventDefault();
    if (SHELL) native({ action: 'openUrl', url: a.href });
    else window.open(a.href, '_blank', 'noopener');
  });
}

function aboutDialog() {
  const m = modal({
    title: 'Koç PDF Pro Hakkında',
    width: 420,
    body: `<div class="about">
      <img src="/static/logo.png" alt="" width="64" height="64">
      <h3>Koç PDF Pro</h3>
      <div class="muted small">Yerel PDF okuma, dönüştürme ve düzenleme</div>
      <div class="about-ver">${state.version ? `<span class="ver-badge">Sürüm ${esc(state.version)}</span>` : ''}
        <button class="link-btn small" data-update>Güncellemeleri denetle</button></div>
      <div class="credits">
        <div>© 2026 Hasan Koç · Açık kaynak, <a href="${SOURCE.url}/blob/main/LICENSE" data-ext>GNU AGPL-3.0</a> lisansıyla</div>
        <div>Kaynak kodu: <a href="${SOURCE.url}" data-ext>${esc(SOURCE.label)}</a></div>
        <div class="credits-gap">Görüş, öneri ve geliştirme fikirleriniz için e-posta gönderebilirsiniz:</div>
        <a href="mailto:hasankoc1996@icloud.com?subject=Ko%C3%A7%20PDF%20Pro%20-%20G%C3%B6r%C3%BC%C5%9F%20ve%20%C3%B6neri">hasankoc1996@icloud.com</a>
        <div class="credits-gap">Geliştirici: <a href="${DEVELOPER.url}" data-ext>${esc(DEVELOPER.label)}</a></div>
      </div>
      <button class="link-btn small kb-link" data-guide>Kullanım kılavuzu</button>
      <button class="link-btn small kb-link" data-keys>Klavye kısayolları (${esc(keyLabel('⌘/'))})</button></div>`,
    foot: `${NATIVE || SHELL ? '' : '<button class="btn" data-quit title="Sunucuyu durdurur">Uygulamayı kapat</button>'}
      <span class="spacer"></span><button class="btn" data-report>${icon('mail')}Sorun bildir…</button><button class="btn primary" data-ok>Tamam</button>`,
  });
  $('[data-ok]', m.el).onclick = m.close;
  bindExternalLinks(m.el);
  $('[data-report]', m.el).onclick = () => { m.close(); reportDialog(); };
  $('[data-keys]', m.el).onclick = () => { m.close(); shortcutsDialog(); };
  $('[data-guide]', m.el).onclick = () => { m.close(); openGuide(); };
  $('[data-update]', m.el).onclick = () => { m.close(); settingsDialog('update', true); };
  const quit = $('[data-quit]', m.el);
  if (quit) quit.onclick = async () => {
    if (!confirm('Koç PDF Pro kapatılsın mı? Tekrar açmak için uygulama simgesine tıklayın.')) return;
    m.close();
    try { await postJSON('/api/shutdown'); } catch { }
    document.body.innerHTML = '<div class="empty-editor"><h2>Koç PDF Pro kapatıldı</h2><p class="muted">Bu sekmeyi kapatabilirsiniz.</p></div>';
  };
}
// Mac uygulamasında Yardım › Sorun Bildir… bunu çağırır
window.PDFSTUDYO_report = () => reportDialog();

// ------------------------------------------------------------------ klavye kısayolları
// Tuşlar Mac işaretleriyle yazılır; Windows'ta adlarıyla gösterilir (⇧⌘S → Ctrl+Shift+S)
const KEY_WIN = { '⌘': 'Ctrl', '⌃': 'Ctrl', '⌥': 'Alt', '⇧': 'Shift', '↵': 'Enter', '⌫': 'Delete' };
function keyLabel(k) {
  if (!IS_WIN) return k;
  const mods = new Set();
  while (k.length > 1 && '⌘⌃⌥⇧'.includes(k[0])) { mods.add(KEY_WIN[k[0]]); k = k.slice(1); }
  return [...['Ctrl', 'Alt', 'Shift'].filter(m => mods.has(m)), KEY_WIN[k] || k].join('+');
}
const kbd = (...keys) => keys.map(k => `<kbd>${esc(keyLabel(k))}</kbd>`).join('<span class="kb-or">/</span>');

// Gruplar: [başlık, [[tuşlar (HTML), açıklama], …]]. Yalnızca bu pencerede (Mac uygulaması, Windows, tarayıcı) çalışanlar
function shortcutGroups() {
  const tabs = NATIVE || SHELL, mac = HOST === 'mac';
  return [
    ['Genel', [
      [kbd('⌘/'), 'Klavye kısayolları (bu pencere)'],
      [kbd('⌘,'), 'Ayarlar'],
      tabs && [kbd('⌘T'), 'Yeni sekme'],
      tabs && [kbd('⌘W'), 'Sekmeyi kapat'],
      tabs && [kbd('⌃Tab', '⌃⇧Tab'), 'Sonraki / önceki sekme'],
      mac && [kbd('⌘O'), 'PDF aç'],   // Mac uygulamasının menüsünde
      mac && [kbd('⌘1'), 'Ana sayfa'],
      mac && [kbd('⌘2'), 'PDF Okuyucu ve Düzenleyici'],
      [kbd('Esc'), 'Pencereyi ya da menüyü kapat'],
    ]],
    ['Belge', [
      [kbd('⌘S'), 'Kaydet'],
      [kbd('⇧⌘S'), 'Farklı kaydet'],
      [kbd('⌘P'), 'Yazdır'],
      [kbd('⌘Z'), 'Geri al'],
      [kbd('⇧⌘Z', '⌘Y'), 'Yinele'],
      [kbd('⌘C'), 'Seçili metni kopyala (satırlar birleşir)'],
    ]],
    ['Gezinme ve görünüm', [
      [kbd('←', '→'), 'Önceki / sonraki sayfa'],
      [kbd('Home', 'End'), 'İlk / son sayfa'],
      [kbd('⌘+', '⌘−'), 'Yakınlaştır / uzaklaştır'],
      [kbd('⌘0'), 'Genişliğe sığdır'],
      [IS_WIN ? `${kbd('⌃')} + tekerlek` : 'İki parmakla kıstır', 'Yakınlaştır / uzaklaştır'],
    ]],
    ['Arama', [
      [kbd('⌘F'), 'Belgede ara'],
      [kbd('↵', '⇧↵'), 'Sonraki / önceki eşleşme'],
      [kbd('Esc'), 'Aramayı kapat'],
    ]],
    ['Düzenleme', [
      [kbd('Esc'), 'Aracı bırak, "Seç"e dön'],
      [kbd('⌫'), 'Seçili eklemeyi sil (Sayfa düzeninde seçili sayfaları)'],
      [`${kbd('⇧')} + sürükle`, 'Kalem, Çizgi: yatay, dikey ya da 45° düz çizgi'],
      [`${kbd('⌥')} + sürükle`, 'Vurgula: metne yapışmadan serbest alan'],
      [kbd('↵', '⇧↵'), 'Metni Düzenle: onayla / alt satır'],
      [kbd('⌘↵'), 'Not penceresinde kaydet'],
    ]],
    ['Fare', [
      ['Sağ tık', 'Tıklanan yere göre menü: not, metin, imza, kaşe, sayfa işlemleri'],
      [`${kbd('⌘')} / ${kbd('⇧')} + tık`, 'Küçük resimlerde birden çok sayfa seç'],
      ['Sürükle', 'Küçük resimlerde sayfaları sırala'],
    ]],
  ].map(([title, rows]) => [title, rows.filter(Boolean)]);
}

// ⌘/ ile ya da Hakkında penceresinden açılır (Mac: Yardım › Klavye Kısayolları)
function shortcutsDialog() {
  if ($('.kb-help')) return;
  modal({
    title: 'Klavye kısayolları',
    width: 760,
    body: `<div class="kb-help">${shortcutGroups().map(([title, rows]) => `<section class="kb-group"><h4>${esc(title)}</h4>
      ${rows.map(([keys, label]) => `<div class="kb-row"><span class="kb-label">${esc(label)}</span><span class="kb-keys">${keys}</span></div>`).join('')}
      </section>`).join('')}</div>`,
  });
}
window.PDFSTUDYO_shortcuts = shortcutsDialog;

// ⌘/ (ya da yazı yazılmıyorken ?): klavye kısayolları · ⌘,: ayarlar (Mac uygulamasında menüden de gelir)
document.addEventListener('keydown', e => {
  const mod = e.metaKey || e.ctrlKey;
  const el = document.activeElement;
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(el?.tagName) || el?.isContentEditable;
  if ((mod && (e.key === '/' || e.key === '?')) || (!mod && !typing && e.key === '?')) {
    e.preventDefault();
    shortcutsDialog();
  } else if (mod && !e.shiftKey && !e.altKey && e.key === ',') {
    e.preventDefault();
    settingsDialog();
  }
});

