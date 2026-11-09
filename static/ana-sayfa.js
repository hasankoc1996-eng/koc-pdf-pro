/* Koç PDF Pro — yönlendirme (#/adres → ekran), ana sayfa, kullanım kılavuzu ekranı ve açılış (init). */
'use strict';

// ------------------------------------------------------------------ kullanım kılavuzu
// Metin static/kilavuz/kilavuz.html'de: her bölüm <section class="g-part" id>, alt başlıkları <section class="g-sub" id>;
// içindekiler listesi başlıklardan çıkarılır. #/kilavuz?b=<kimlik> o başlığa gider. Mac işaretleriyle (⌘) yazılır,
// Windows'ta winify çevirir. PDF hâlini sunucu yazar (kilavuz.py).
let guideHtml = null;

async function openGuide(target) {
  try { await window.Reader?.flush?.(); } catch { }   // açık belgedeki uygulanmamış eklemeler belgeye işlensin
  location.hash = '#/kilavuz' + (target ? '?b=' + target : '');
}
window.PDFSTUDYO_guide = () => openGuide();   // Mac: Yardım › Kullanım Kılavuzu

async function renderGuide(main, target) {
  const back = window.Reader?.hasDoc?.() ? ['#/reader', 'Belgeye dön'] : ['#/', 'Ana sayfa'];
  // Kılavuz kendi içinde kayar (içindekiler listesi yanda sabit durur); olaylar bu kutuda, başka ekrana geçince kalmaz
  main.innerHTML = `<div class="guide-page"><div class="guide-bar"><a class="btn sm" href="${back[0]}">${icon('left')}${back[1]}</a>
      <b class="guide-title">${icon('help')}Kullanım Kılavuzu</b><span class="spacer"></span>
      <button class="btn sm" id="g-pdf">${icon('download')}PDF olarak kaydet…</button></div>
    <div class="guide-wrap"><nav class="guide-toc">
        <input class="input" id="g-q" type="search" placeholder="Kılavuzda ara (ör. karart, Word, şifre)" autocomplete="off" spellcheck="false">
        <div id="g-toc"></div><p class="muted small" id="g-none" hidden>Aradığınız kelime kılavuzda geçmiyor.</p></nav>
      <article class="guide" id="g-body"><p class="muted">Yükleniyor…</p></article></div></div>`;
  const page = $('.guide-page', main), body = $('#g-body', main), toc = $('#g-toc', main);
  try {
    if (!guideHtml) {
      const res = await fetch('/static/kilavuz/kilavuz.html');
      if (!res.ok) throw new Error();
      guideHtml = await res.text();
    }
  } catch { body.innerHTML = '<p>Kılavuz açılamadı.</p>'; return; }
  if (!body.isConnected) return;
  body.innerHTML = guideHtml;
  const parts = $$('.g-part', body);
  toc.innerHTML = parts.map(p => `<button class="g-toc-h2" data-to="${p.id}">${esc($('h2', p).textContent)}</button>`
    + $$('.g-sub', p).map(s => `<button class="g-toc-h3" data-to="${s.id}">${esc($('h3', s).textContent)}</button>`).join('')).join('');
  const go = id => { const el = id && body.querySelector('#' + CSS.escape(id)); if (el) el.scrollIntoView({ block: 'start' }); };
  page.onclick = e => {
    const link = e.target.closest('[data-to]');
    if (link) { e.preventDefault(); return go(link.dataset.to); }
    const img = e.target.closest('.guide figure img');
    if (img) {
      modal({ title: img.closest('figure').querySelector('figcaption')?.textContent || 'Görüntü', width: 1240,
        body: `<img class="g-zoom" src="${esc(img.getAttribute('src'))}" alt="">` });
    }
  };
  // Okunan bölüm içindekiler listesinde işaretlenir
  const heads = $$('.g-part, .g-sub', body);
  page.onscroll = () => {
    const top = page.getBoundingClientRect().top + 90;
    let cur = null;
    for (const h of heads) if (!h.hidden && h.getBoundingClientRect().top <= top) cur = h.id;
    $$('[data-to]', toc).forEach(b => b.classList.toggle('on', b.dataset.to === cur));
  };
  // Arama: başlığı tutan bölüm bütünüyle, öbürlerinde yalnızca kelimenin geçtiği alt başlıklar görünür
  const norm = s => s.toLocaleLowerCase('tr');
  $('#g-q', main).oninput = e => {
    const q = norm(e.target.value.trim());
    let found = 0;
    for (const p of parts) {
      const whole = !q || norm($('h2', p).textContent).includes(q);
      let any = whole || [...p.children].some(c => !c.classList.contains('g-sub') && norm(c.textContent).includes(q));
      for (const s of $$('.g-sub', p)) {
        s.hidden = !whole && !norm(s.textContent).includes(q);
        any ||= !s.hidden;
      }
      p.hidden = !any;
      found += any;
    }
    $$('[data-to]', toc).forEach(b => { b.hidden = body.querySelector('#' + CSS.escape(b.dataset.to)).closest('[hidden]') !== null; });
    $('#g-none', main).hidden = !!found;
    page.scrollTop = 0;
  };
  $('#g-pdf', main).onclick = async () => {
    let r;
    try { r = await withBusy('Kılavuz PDF olarak hazırlanıyor…', () => postJSON('/api/kilavuz/pdf')); } catch { return; }
    try {
      const where = await saveOutput(r);
      if (where) toast(`Kılavuz kaydedildi: ${shortPath(where)}`, 'ok');
    } catch { /* hata gösterildi */ }
  };
  go(target);
}

// ------------------------------------------------------------------ yönlendirme

let handoffFiles = null; // ana sayfadan araca aktarılan dosyalar
// settings: Ayarlar penceresinin uygulama genelindeki seçimleri (sunucudaki ayarlar.json; açılışta okunur)
const state = { engines: {}, desktop: '',
  settings: { backupKeep: 10, backupDays: 60, recoverDays: 7, autoUpdate: true, saveFolder: 'doc', resumePage: true, author: '' } };

function route() {
  const id = location.hash.replace(/^#\/?/, '').split('?')[0];
  const main = $('#main');
  main.scrollTop = 0;
  const file = handoffFiles?.[0];
  window.Reader?.unmount?.();
  if (id === 'editor' || id === 'reader') {
    state.docView = 'reader';   // Araçlar menüsündeki araçlar bu ekrandaki açık belgeye uygulanır
    handoffFiles = null;
    // Eski Düzenleyici adresi: belge ekranı düzenleme araçları açık gelir
    if (id === 'editor') history.replaceState(null, '', '#/reader');
    return window.Reader.mount(main, file, { edit: id === 'editor' });
  }
  if (id === 'kilavuz') {
    setTabTitle('Kullanım Kılavuzu');
    return renderGuide(main, new URLSearchParams(location.hash.split('?')[1] || '').get('b'));
  }
  setTabTitle(TOOL[id]?.title || 'Ana Sayfa');
  if (DIALOGS[id]) {   // pencereyle açılan araç: ana sayfa ve üstünde penceresi
    history.replaceState(null, '', '#/');
    renderHome(main);
    return DIALOGS[id]();
  }
  if (TOOL[id]) return renderTool(main, TOOL[id]);
  renderHome(main);
}

// ------------------------------------------------------------------ ana sayfa
function renderHome(main) {
  // Gruplar dört sütunluk tek bir ızgarada: kartları az olan gruplar yan yana durur (Oku & Düzenle ile Dönüştür
  // aynı satırda), kartlar yine aynı sütunlara oturur
  let cards = '<div class="card-groups">';
  for (const g of GROUPS) {
    const tools = listedTools(g), span = Math.min(tools.length, 4);
    cards += `<div class="card-group" style="grid-column: span ${span}"><div class="card-group-title">${esc(g)}</div>
      <div class="cards" style="grid-template-columns: repeat(${span}, minmax(0, 1fr))">`;
    for (const t of tools) {
      cards += `<a class="card" href="${toolHref(t)}" data-card="${t.id}" title="${esc(t.title)} — ${esc(t.short)}"><span class="tool-icon" style="--c:${t.color}">${icon(t.icon)}</span>
        <div><b>${esc(t.title)}</b><span>${esc(t.short)}</span></div></a>`;
    }
    cards += '</div></div>';
  }
  cards += '</div>';
  main.innerHTML = `${idleToolbar()}<div class="home-wrap"><div class="page home-page">
    <div class="drop drop-bar" id="home-drop">
      <span class="drop-bar-icon">${icon('upload')}</span>
      <span class="drop-bar-text"><b>Dosyayı buraya bırakın</b>
        <span class="muted small">PDF, Word, Excel, UDF ya da resim — ne yapmak istediğinizi soracağız</span></span>
      <button class="btn sm primary" type="button">Dosya seç</button>
    </div>
    ${cards}
    <div id="home-recent"></div></div>
    <footer class="home-foot"><img src="/static/logo.png" alt="" width="28" height="28">
      <span><span class="muted small">Koç PDF Pro${state.version ? ` · Sürüm ${esc(state.version)}` : ''}</span>
        <a href="#/kilavuz">Kullanım kılavuzu</a>
        <a href="${DEVELOPER.url}" data-ext title="${DEVELOPER.url}">Geliştirici: ${esc(DEVELOPER.label)} ↗</a></span></footer>
  </div>`;
  setupDrop($('#home-drop'), { accept: `.pdf,.udf,${WORD_ACCEPT},${EXCEL_ACCEPT},${IMG_ACCEPT}`, multiple: true }, handleHomeFiles);
  bindIdleToolbar(main);
  bindExternalLinks(main);
  for (const [id, open] of Object.entries(DIALOGS)) {
    const card = $(`[data-card="${id}"]`, main);
    if (card) card.onclick = e => { e.preventDefault(); open(); };
  }
  renderRecent($('#home-recent'));
}

// Son açılanlar: diskten açılan son 10 belge; tıklayınca okuyucuda, kalınan sayfadan açılır
function whenText(t) {
  const d = new Date(t * 1000), now = new Date();
  const hm = d.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
  const days = Math.round((new Date(now.toDateString()) - new Date(d.toDateString())) / 86400000);
  return days === 0 ? `Bugün ${hm}` : days === 1 ? `Dün ${hm}` : d.toLocaleDateString('tr-TR');
}

// Ana sayfa ve okuyucunun boş ekranı. open: belgeyi açan işlev (varsayılan: okuyucuda aç).
async function renderRecent(box, open = path => window.PDFSTUDYO_openPaths?.([path])) {
  await migrateRecent();
  let items;
  try { items = (await api('/api/recent')).items; } catch { return; }
  if (!box?.isConnected) return;
  if (!items.length) {   // boşken de bölüm görünür: listenin nerede olduğu ve neyin gireceği belli olsun
    box.innerHTML = `<div class="card-group-title recent-head">Son açılanlar</div>
      <div class="recent-empty muted small">Henüz bir dosya açmadınız; açtığınız PDF'ler burada listelenir.</div>`;
    return;
  }
  box.innerHTML = `<div class="card-group-title recent-head">Son açılanlar
      <button class="link-btn small" data-clear>Listeyi temizle</button></div>
    <div class="recent-list">${items.map((it, k) => `<div class="recent-row ${it.exists ? '' : 'missing'}" data-k="${k}" title="${esc(it.path)}">
        <span class="badge">${esc(ext(it.name).toUpperCase() || 'PDF')}</span><span class="fname">${esc(it.name)}</span>
        <span class="muted small rpath">${esc(shortPath(dirOf(it.path)))}</span>
        <span class="muted small recent-when">${it.exists ? whenText(it.time) : 'Bulunamadı'}</span>
        <button class="x" data-rm="${k}" title="Listeden çıkar (dosyaya dokunulmaz)">×</button></div>`).join('')}</div>`;
  const remove = async path => { try { await postJSON('/api/recent/remove', path ? { path } : {}); } catch { } renderRecent(box, open); };
  $('[data-clear]', box).onclick = () => remove(null);
  $$('.recent-row', box).forEach(row => row.onclick = e => {
    const it = items[+row.dataset.k];
    if (e.target.closest('[data-rm]')) return remove(it.path);
    if (!it.exists) return toast(`${it.name} bulunamadı; taşınmış, adı değiştirilmiş ya da silinmiş olabilir.`, 'error');
    open(it.path);
  });
}

// Eski sürüm son açılanları sayfanın kendi belleğinde tutuyordu (yalnız Mac): bir kez uygulamanın listesine aktarılır
async function migrateRecent() {
  let old;
  try { old = JSON.parse(localStorage.getItem('pdfstudyo.recent') || 'null'); } catch { return; }
  if (!Array.isArray(old)) return;
  try {
    await postJSON('/api/recent/import', { items: old.map(r => ({ path: r.path, time: (r.t || 0) / 1000 })) });
    localStorage.removeItem('pdfstudyo.recent');
  } catch { }
}

function handleHomeFiles(files) {
  if (!files.length) return;
  const kinds = files.map(f => {
    const e = ext(f.name);
    if (e === 'pdf') return 'pdf';
    if (e === 'udf') return 'udf';
    if (WORD_ACCEPT.includes('.' + e)) return 'word';
    if (EXCEL_ACCEPT.split(',').includes('.' + e)) return 'excel';
    if (f.type.startsWith('image/') || ['heic', 'webp'].includes(e)) return 'img';
    return 'other';
  });
  const all = k => kinds.every(x => x === k);
  const where = Promise.all(files.map(droppedPath));   // Mac: bırakılan dosyaların yolları, hemen sorulur
  const go = async id => {
    if (DIALOGS[id]) return DIALOGS[id]({ files, where });
    // Okuyucu: Mac'te bırakılan dosya diskteki yeriyle açılır (kopya gibi değil): son açılanlara girer, Kaydet asıl
    // dosyanın üzerine kaydeder
    const [path] = id === 'reader' ? await where : [];
    if (path) return window.PDFSTUDYO_openPaths([path]);
    handoffFiles = files; location.hash = '#/' + id;
  };
  const many = files.length > 1, pair = files.length === 2;
  let ids;
  if (all('img')) ids = ['images-to-pdf', 'convert', 'ocr'];
  else if (all('excel')) ids = ['convert', ...(many ? ['merge'] : []), ...(pair ? ['compare'] : [])];
  else if (all('udf')) ids = many ? ['convert', 'merge'] : ['reader', 'convert'];
  else if (all('word')) ids = ['convert', ...(many ? ['merge'] : []), ...(pair ? ['compare'] : [])];
  else if (all('pdf')) ids = !many ? ['reader', 'convert', 'ocr', 'split', 'compress', 'watermark', 'numbers', 'protect']
    : [...(pair ? ['compare'] : []), 'merge', 'convert', 'ocr', 'compress', 'watermark', 'numbers', 'protect'];
  else if (!kinds.includes('other')) ids = ['convert', 'merge'];   // karışık türler: ayrı ayrı dönüştür ya da tek PDF'te birleştir
  else return toast('Bu dosya türü desteklenmiyor. PDF, Word, Excel, UDF ya da resim seçin.', 'error');
  if (ids.length === 1) return go(ids[0]);
  const choices = ids.map(id => TOOL[id]);
  const m = modal({
    title: files.length === 1 ? `“${files[0].name}” ile ne yapalım?` : `${files.length} dosya ile ne yapalım?`,
    body: `<div class="choice-grid">${choices.map(t => `<button class="choice" data-id="${t.id}">
      <span class="tool-icon" style="--c:${t.color}">${icon(t.icon)}</span><span><b>${esc(t.id === 'convert' ? 'Format Değiştir' : t.title)}</b></span></button>`).join('')}</div>`,
  });
  $$('.choice', m.el).forEach(b => b.onclick = () => { m.close(); go(b.dataset.id); });
}

// ------------------------------------------------------------------ başlangıç
async function init() {
  if (IS_WIN) startWinTexts();
  // Mac: pencerenin içeriği başlık çubuğunun altına uzanır; başlık satırı (pencere düğmelerinin yanında ad) sayfada
  if (HOST === 'mac' && window.PDFSTUDYO_TITLEBAR) {
    const bar = $('#titlebar');
    bar.hidden = false;
    bar.style.height = window.PDFSTUDYO_TITLEBAR + 'px';
  }
  setupToolbarTips();
  renderTabStrip();
  applyTheme(getTheme());
  window.addEventListener('hashchange', route);
  // Pencereye bırakılan dosyalar tarayıcıda açılmasın
  window.addEventListener('dragover', e => e.preventDefault());
  window.addEventListener('drop', e => e.preventDefault());
  const settings = loadSettings();
  setTimeout(checkUpdate, 3000);
  setTimeout(checkRecovery, 1200);
  try {
    const s = await api('/api/status');
    state.engines = s.engines;  // Word bulunamazsa Word → PDF ekranında uyarı gösterilir
    state.version = s.version;
    state.packaged = s.packaged;   // kurulum paketi mi: güncelleme yalnızca onda denetlenir
    if (s.heartbeat) {
      // Windows: pencere kapanınca motor da kapansın diye sayfa ara ara "buradayım" der
      const beat = () => fetch('/api/ping', { method: 'POST' }).catch(() => { });
      beat();
      setInterval(beat, 20000);
    }
  } catch { }
  await settings;   // belge açılırken "kaldığım sayfadan aç" ayarı bilinsin
  route();
}
document.addEventListener('DOMContentLoaded', init);
