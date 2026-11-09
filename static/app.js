/* Koç PDF Pro — arayüzün ortak temeli: simgeler, yardımcılar (api, toast, modal), yerel uygulama köprüsü,
   yakınlaştırma, Windows uyumu, gece / gündüz modu. Öbür dosyalar bunun üstüne kurulur ve aynı genel alanı paylaşır;
   index.html'deki yükleme sırası önemlidir (yüklenirken çalışan satırlar yalnızca önceki dosyaları kullanabilir):
     app.js → kaydet.js (açma, kaydetme, kurtarma) → cubuklar.js (sekme/araç çubuğu, sağ tık, kısayollar)
     → pencereler.js (KVKK, sorun bildir, güncelleme, Ayarlar) → araclar.js (araç tanımları, araç sayfası, sonuçlar)
     → dosya-pencereleri.js (Format Değiştir) → sikistir-bol.js (Sıkıştır, Böl) → ana-sayfa.js (yönlendirme,
     ana sayfa, kılavuz, açılış) → editor.js, reader.js (belge ekranı) */
'use strict';

// ------------------------------------------------------------------ simgeler
const ICONS = {
  tools: '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M3 13h18M12 12v3"/>',
  chevdown: '<path d="m6 9 6 6 6-6"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  share: '<path d="M12 15V3"/><path d="m8 7 4-4 4 4"/><path d="M7 10H5a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-9a1 1 0 0 0-1-1h-2"/>',
  home: '<path d="M3 10.5 12 3l9 7.5"/><path d="M5 9.5V21h14V9.5"/>',
  wordpdf: '<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5"/><path d="m8 13 1.2 4 1.3-3 1.3 3 1.2-4"/><path d="M15 14h2.5M16 12.5l1.5 1.5-1.5 1.5"/>',
  pdfword: '<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5"/><path d="M8 12h3a1.5 1.5 0 0 1 0 3H8v-3zm0 3v3"/><path d="M14 16h2.5M15.5 14.5 17 16l-1.5 1.5"/>',
  img: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="m21 16-5-5-9 9"/>',
  toimg: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m3 17 5-5 4 4 3-3 6 6"/><circle cx="15.5" cy="9" r="1.5"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
  docs: '<path d="M8 3h8l4 4v11a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"/><path d="M16 3v4h4"/><path d="M4 7v13a1 1 0 0 0 1 1h10"/>',
  merge: '<rect x="3" y="3" width="8" height="11" rx="1"/><rect x="13" y="3" width="8" height="11" rx="1"/><path d="M7 17v2h10v-2M12 19v2"/>',
  split: '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M20 4 8.1 15.9M14.5 14.5 20 20M8.1 8.1 12 12"/>',
  compress: '<path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7"/>',
  watermark: '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/>',
  numbers: '<path d="M4 9h16M4 15h16M10 3 8 21M16 3l-2 18"/>',
  lock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
  unlock: '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 7.5-2"/>',
  upload: '<path d="M12 15V3M7 8l5-5 5 5"/><path d="M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4"/>',
  download: '<path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/>',
  rotcw: '<path d="M20 12a8 8 0 1 1-2.3-5.6L20 8.7"/><path d="M20 3v5.7h-5.7"/>',
  rotccw: '<path d="M4 12a8 8 0 1 0 2.3-5.6L4 8.7"/><path d="M4 3v5.7h5.7"/>',
  copy: '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>',
  trash: '<path d="M3 6h18M8 6V4h8v2M6 6l1 15h10l1-15"/>',
  undo: '<path d="M9 14 4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>',
  redo: '<path d="m15 14 5-5-5-5"/><path d="M20 9H9a5 5 0 0 0 0 10h3"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  text: '<path d="M5 6V4h14v2M12 4v16M9 20h6"/>',
  textedit: '<path d="M4 7V5h11v2M9.5 5v14M7 19h5"/><path d="m14 17 5.5-5.5 2 2L16 19h-2z"/>',
  eraser: '<path d="m7 21-4-4L14 6l7 7-8 8z"/><path d="M7 21h14M9 11l7 7"/>',
  redact: '<rect x="3" y="7" width="18" height="10" rx="1" fill="currentColor"/>',
  box: '<rect x="4" y="5" width="16" height="14" rx="1"/>',
  highlight: '<path d="m9 11-6 6v4h4l6-6"/><path d="m22 12-4.6 4.6a2 2 0 0 1-2.8 0l-5.2-5.2a2 2 0 0 1 0-2.8L14 4"/>',
  underline: '<path d="M7 4v7a5 5 0 0 0 10 0V4"/><path d="M5 20h14"/>',
  strike: '<path d="M4 12h16"/><path d="M16 6.5C15.3 5.6 13.9 5 12 5 9.5 5 8 6.3 8 8c0 1.5 1 2.4 3 3"/><path d="M8 17.5c.8 1 2.2 1.5 4 1.5 2.5 0 4-1.3 4-3 0-.8-.3-1.5-.9-2"/>',
  line: '<path d="M5 19 19 5"/>',
  signed: '<path d="M12 3 4.5 6v5.5c0 4.6 3.2 8.4 7.5 9.5 4.3-1.1 7.5-4.9 7.5-9.5V6z"/><path d="m8.8 12 2.3 2.3 4.3-4.6"/>',
  shield: '<path d="M12 3 4.5 6v5.5c0 4.6 3.2 8.4 7.5 9.5 4.3-1.1 7.5-4.9 7.5-9.5V6z"/><path d="M8.5 11.5h7" stroke-width="3"/>',
  pen: '<path d="M3 21c3-1 4.5-4 7-6.5S16 9 19 6a2 2 0 0 0-3-3c-3 3-5 6-7.5 8.5S4 18 3 21z"/>',
  signature: '<path d="M3 17c3-6 5-9 6-8s-2 7 0 8 3-5 5-5 1 5 3 5 2-2 4-2"/><path d="M3 21h18"/>',
  history: '<path d="M3 12a9 9 0 1 0 2.6-6.4L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l3 2"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 7 9 6 9-6"/>',
  stamp: '<path d="M5 21h14"/><path d="M4 17h16v-2.5A2.5 2.5 0 0 0 17.5 12h-11A2.5 2.5 0 0 0 4 14.5z"/><path d="M14 12V9c0-1.5 1.5-2 1.5-4a3.5 3.5 0 0 0-7 0c0 2 1.5 2.5 1.5 4v3"/>',
  pointer: '<path d="m4 3 7 18 2.5-7.5L21 11z"/>',
  zoomin: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5M11 8v6M8 11h6"/>',
  zoomout: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5M8 11h6"/>',
  left: '<path d="m15 18-6-6 6-6"/>',
  right: '<path d="m9 18 6-6-6-6"/>',
  check: '<path d="m5 12 5 5L20 7"/>',
  pages2: '<rect x="3" y="4" width="8" height="16" rx="1.5"/><rect x="13" y="4" width="8" height="16" rx="1.5"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  folder: '<path d="M3 6a1 1 0 0 1 1-1h5l2 2h9a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/>',
  grip: '<circle cx="9" cy="6" r="1"/><circle cx="15" cy="6" r="1"/><circle cx="9" cy="12" r="1"/><circle cx="15" cy="12" r="1"/><circle cx="9" cy="18" r="1"/><circle cx="15" cy="18" r="1"/>',
  extract: '<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h5"/><path d="M14 3v5h5v4"/><path d="M15 19h6M18 16l3 3-3 3"/>',
  file: '<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5"/>',
  fit: '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
  note: '<path d="M5 4h14v11l-5 5H5z"/><path d="M14 20v-5h5"/>',
  bookmark: '<path d="M7 3h10v18l-5-4-5 4z"/>',
  sidebar: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
  save: '<path d="M5 3h11l3 3v15H5z"/><path d="M8 3v5h7V3M8 21v-7h8v7"/>',
  saveas: '<path d="M11 21H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9.2a2 2 0 0 1 1.4.6l2.8 2.8a2 2 0 0 1 .6 1.4V10"/><path d="M8 3v4h7V3"/><path d="M8 21v-6h4"/><path d="M14 21v-2.6l5.6-5.6 2.6 2.6-5.6 5.6z"/>',
  scan: '<path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3"/><path d="M8 10h8M8 14h5"/>',
  udf: '<path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z"/><path d="M14 3v5h5"/><path d="M9 11v4a3 3 0 0 0 6 0v-4"/>',
  book: '<path d="M3 5h6a3 3 0 0 1 3 3v12a2.5 2.5 0 0 0-2.5-2.5H3z"/><path d="M21 5h-6a3 3 0 0 0-3 3v12a2.5 2.5 0 0 1 2.5-2.5H21z"/>',
  printer: '<path d="M7 9V3h10v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M7 14h10v7H7z"/>',
  sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
  autotheme: '<circle cx="12" cy="12" r="8"/><path d="M12 4v16a8 8 0 0 0 0-16z" fill="currentColor"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.5v.5"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.6 9.3a2.5 2.5 0 0 1 4.9.7c0 1.7-2.5 2.2-2.5 3.8M12 17v.5"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
  excel: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M3 15h18M9 3v18"/>',
  convert: '<path d="M4 8h14l-4-4"/><path d="M20 16H6l4 4"/>',
  compare: '<circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><path d="M13 6h3a2 2 0 0 1 2 2v7"/><path d="M11 18H8a2 2 0 0 1-2-2V9"/>',
};
function icon(name, extra = '') {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" ${extra}>${ICONS[name] || ''}</svg>`;
}

// ------------------------------------------------------------------ yardımcılar
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
function fmtSize(n) {
  if (n < 1024) return n + ' B';
  if (n < 1024 * 1024) return (n / 1024).toFixed(0) + ' KB';
  return (n / 1024 / 1024).toFixed(n < 10 * 1024 * 1024 ? 2 : 1).replace('.', ',') + ' MB';
}
function ext(name) { return (name.split('.').pop() || '').toLowerCase(); }

function toast(msg, kind = '') {
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  el.textContent = msg;
  $('#toasts').append(el);
  setTimeout(() => el.remove(), kind === 'error' ? 7000 : 3500);
}

let busyCount = 0;
function busy(on, text = 'İşleniyor…') {
  busyCount = Math.max(0, busyCount + (on ? 1 : -1));
  $('#busy-text').textContent = text;
  $('#busy').hidden = busyCount === 0;
}

async function api(url, opts = {}) {
  const res = await fetch(url, opts);
  let data = null;
  const type = res.headers.get('content-type') || '';
  if (type.includes('application/json')) data = await res.json();
  if (!res.ok) {
    const err = new Error((data && data.error) || `Sunucu hatası (${res.status})`);
    err.data = data;
    throw err;
  }
  return data;
}
const postJSON = (url, body) => api(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });

async function withBusy(text, fn) {
  busy(true, text);
  try { return await fn(); }
  catch (e) { toast(e.message, 'error'); throw e; }
  finally { busy(false); }
}

function downloadUrl(url, name) {
  const a = document.createElement('a');
  a.href = url; if (name) a.download = name;
  document.body.append(a); a.click(); a.remove();
}

// Yerel uygulama içinde mi çalışıyoruz?
//  HOST 'mac': Mac uygulaması (Swift kabuk) · 'win': Windows uygulama penceresi (sekme kabuğu + pencere sahibi)
//  SHELL: Windows'ta bu sayfayı bir sekme olarak taşıyan kabuk (static/shell.js)
const SHELL = (() => { try { return (window.parent !== window && window.parent.PDFSTUDYO_SHELL) || null; } catch { return null; } })();
const TAB_ID = SHELL ? +(window.frameElement?.dataset.tab || 0) : 0;
const HOST = window.PDFSTUDYO_NATIVE && window.webkit?.messageHandlers?.pdfstudyo ? 'mac' : SHELL?.hasHost() ? 'win' : null;
const NATIVE = !!HOST;
const native = msg => {
  try {
    if (HOST === 'mac') window.webkit.messageHandlers.pdfstudyo.postMessage(msg);
    else if (SHELL) SHELL.message(TAB_ID, msg);
  } catch { }
};

function pickFiles({ accept = '', multiple = false } = {}) {
  return new Promise(resolve => {
    const input = document.createElement('input');
    input.type = 'file'; input.accept = accept; input.multiple = multiple;
    input.hidden = true;
    document.body.append(input);  // WebKit, belgeye eklenmemiş dosya kutusunu açmayabilir
    input.onchange = () => { resolve([...input.files]); input.remove(); };
    if (NATIVE) native({ action: 'accept', value: accept });  // seçim penceresinde dosya türü filtresi
    input.click();
  });
}

// ------------------------------------------------------------------ sayfa içi bağlantılar
// PDF'teki tıklanabilir alan (içindekiler satırı, web adresi). onGo(sayfa, konum): belge içi bağlantıya tıklanınca.
function pdfLinkEl(l, onGo) {
  const internal = l.uri == null;
  const el = document.createElement(internal ? 'span' : 'a');
  el.className = 'pdf-link';
  Object.assign(el.style, { left: l.x * 100 + '%', top: l.y * 100 + '%', width: l.w * 100 + '%', height: l.h * 100 + '%' });
  if (internal) {
    el.title = `Git: sayfa ${l.page + 1}`;
    el.setAttribute('role', 'link');
    el.onclick = e => { e.preventDefault(); e.stopPropagation(); onGo(l.page, l.to); };
  } else {
    el.href = l.uri;   // sunucu yalnızca http(s) ve e-posta adreslerini gönderir
    el.title = l.uri.replace(/^mailto:/i, '');
    if (HOST !== 'mac' && /^https?:/i.test(l.uri)) { el.target = '_blank'; el.rel = 'noopener noreferrer'; }
  }
  return el;
}

// ------------------------------------------------------------------ yakınlaştırma (iki parmakla kıstırma)
// Yakınlaştırırken parmakların (ya da imlecin) altındaki nokta yerinde kalsın: önce yeri ölç, sonra geri koy.
function zoomAnchor(scroller, pageEls, pt) {
  if (!scroller || !pageEls.length) return null;
  const s = scroller.getBoundingClientRect();
  const x = pt ? pt.x : s.left + s.width / 2, y = pt ? pt.y : s.top + s.height * 0.35;
  let lo = 0, hi = pageEls.length - 1;   // sayfalar alt alta: imlecin hizasındaki sayfayı ikili aramayla bul
  while (lo < hi) { const mid = (lo + hi) >> 1; if (pageEls[mid].getBoundingClientRect().bottom < y) lo = mid + 1; else hi = mid; }
  const el = pageEls[lo], r = el.getBoundingClientRect();
  if (!r.width || !r.height) return null;
  return { el, fx: (x - r.left) / r.width, fy: (y - r.top) / r.height, dx: x - s.left, dy: y - s.top };
}

function restoreZoomAnchor(scroller, a) {
  if (!scroller || !a?.el?.isConnected) return;
  scroller.scrollLeft = a.el.offsetLeft + a.fx * a.el.offsetWidth - a.dx;
  scroller.scrollTop = a.el.offsetTop + a.fy * a.el.offsetHeight - a.dy;
}

// Mac: trackpad'de iki parmakla kıstırma (Safari/WebKit "gesture" olayları); Windows/Edge: kıstırma ya da Ctrl + tekerlek.
// set(yeniÖlçek, {x, y}) ekran karesi başına en fazla bir kez çağrılır.
function setupPinchZoom(el, { get, set }) {
  let gesture = null, pending = null;
  const apply = (scale, pt) => {
    const first = !pending;
    pending = { scale, pt };
    if (first) requestAnimationFrame(() => { const p = pending; pending = null; set(p.scale, p.pt); });
  };
  el.addEventListener('wheel', e => {
    if (!e.ctrlKey || gesture) return;
    e.preventDefault();
    const step = Math.abs(e.deltaY) >= 50 ? (e.deltaY > 0 ? 1 / 1.15 : 1.15) : Math.exp(-e.deltaY * 0.01);   // fare tekerleği: tık başına %15
    apply((pending ? pending.scale : get()) * step, { x: e.clientX, y: e.clientY });
  }, { passive: false });
  el.addEventListener('gesturestart', e => { e.preventDefault(); gesture = { start: get() }; });
  el.addEventListener('gesturechange', e => { e.preventDefault(); if (gesture) apply(gesture.start * e.scale, { x: e.clientX, y: e.clientY }); });
  el.addEventListener('gestureend', e => { e.preventDefault(); gesture = null; });
}

// Açık belgenin bulunduğu görünüm (belge ekranı)
function openDocView(onlyIfShown = false) {
  const route = location.hash.replace(/^#\/?/, '').split('?')[0];
  const view = onlyIfShown ? route : state.docView;
  const mod = view === 'editor' || view === 'reader' ? window.Reader : null;
  const info = mod?.docInfo?.();
  return info ? { view, mod, info } : null;
}

// Windows uygulama penceresi: Ctrl+T yeni sekme, Ctrl+W sekmeyi kapat, Ctrl+Tab / Ctrl+Shift+Tab sekmeler arası
if (SHELL) document.addEventListener('keydown', e => {
  if (!e.ctrlKey || e.altKey || e.metaKey) return;
  const k = e.key.toLowerCase();
  if (k === 't' && !e.shiftKey) { e.preventDefault(); native({ action: 'newTab' }); }
  else if (k === 'w' && !e.shiftKey) { e.preventDefault(); native({ action: 'closeTab', id: TAB_ID }); }
  else if (e.key === 'Tab' || e.key === 'PageDown' || e.key === 'PageUp') {
    e.preventDefault();
    native({ action: 'stepTab', delta: e.shiftKey || e.key === 'PageUp' ? -1 : 1 });
  }
}, true);

// ⌘S / ⇧⌘S ve Dosya › Paylaş… (menüden gelir)
window.PDFSTUDYO_save = asNew => openDocView(true)?.mod.save(asNew);
window.PDFSTUDYO_share = () => {
  const v = openDocView(true);
  if (v) v.mod.share();
  else toast('Paylaşmak için önce bir PDF açın.');
};
document.addEventListener('keydown', e => {
  if (!(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== 's' || $('.modal-back')) return;
  const v = openDocView(true);
  if (!v) return;
  e.preventDefault();
  v.mod.save(e.shiftKey);
});

// ------------------------------------------------------------------ Windows uyumu
// Arayüzdeki Mac kısayol işaretlerini (⌘, ⇧) ve "Finder" ifadelerini Windows karşılıklarına çevirir.
const IS_WIN = /Win/i.test(navigator.platform || navigator.userAgent);
const WIN_TEXT = [
  [/⇧⌘/g, 'Ctrl+Shift+'], [/⌘ veya ⇧/g, 'Ctrl veya Shift'], [/⌘/g, 'Ctrl+'], [/⌃/g, 'Ctrl+'], [/⇧/g, 'Shift+'], [/↵/g, 'Enter'],
  [/⌫/g, 'Delete'], [/⌥/g, 'Alt'],
  [/ve Finder'da göster/g, 've klasörünü aç'], [/Finder'da göster/g, 'Klasörde göster'], [/Finder'da/g, 'Dosya Gezgini\'nde'],
];
function toWinText(s) { return WIN_TEXT.reduce((t, [re, to]) => t.replace(re, to), s); }
function winify(root) {
  if (root.nodeType === Node.TEXT_NODE) {
    const t = toWinText(root.nodeValue);
    if (t !== root.nodeValue) root.nodeValue = t;
    return;
  }
  if (root.nodeType !== Node.ELEMENT_NODE) return;
  for (const el of [root, ...root.querySelectorAll('[title], [placeholder], [data-tip]')]) {
    for (const attr of ['title', 'placeholder', 'data-tip']) {
      const v = el.getAttribute?.(attr);
      if (v) { const t = toWinText(v); if (t !== v) el.setAttribute(attr, t); }
    }
  }
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) winify(n);
}
function startWinTexts() {
  winify(document.body);
  new MutationObserver(muts => {
    for (const m of muts) {
      if (m.type === 'attributes') winify(m.target);
      else m.addedNodes.forEach(winify);
    }
  }).observe(document.body, { childList: true, subtree: true, characterData: false, attributes: true, attributeFilter: ['title', 'placeholder', 'data-tip'] });
}

// Kaydedilmemiş değişiklik durumunu yerel uygulamaya bildir (kapatırken sorması için)
// Sekme durumunu yerel uygulamaya bildir: kaydedilmemiş değişiklik (kapatırken sorması için),
// açık belge ve ekran (yeni PDF'in bu sekmede mi yoksa yeni sekmede mi açılacağı için)
if (NATIVE || SHELL) {
  let last = '';
  setInterval(() => {
    const state = {
      unsaved: !!window.PDFSTUDYO_unsaved?.(),
      hasDoc: !!window.Reader?.hasDoc?.(),
      route: location.hash.replace(/^#\/?/, '').split('?')[0],
    };
    const key = JSON.stringify(state);
    if (key !== last) { last = key; native({ action: 'state', ...state }); }
  }, 300);
}
// Sekme başlığı (yerel uygulamada)
function setTabTitle(name, path) {
  if (NATIVE || SHELL) native({ action: 'document', name, path });
  strip.local = { title: name || 'Koç PDF Pro', path: path || null };
  if (!strip.tabs) renderTabStrip();
}

// ------------------------------------------------------------------ gece / gündüz modu
const THEMES = {
  auto: { label: 'Otomatik', icon: 'autotheme', hint: 'Mac\'in ayarını izler' },
  dark: { label: 'Gece', icon: 'moon', hint: 'Koyu renkler' },
  light: { label: 'Gündüz', icon: 'sun', hint: 'Açık renkler' },
};
const THEME_ORDER = ['auto', 'dark', 'light'];
const darkQuery = window.matchMedia('(prefers-color-scheme: dark)');

function getTheme() {
  try { return THEMES[localStorage.getItem('pdfstudyo.theme')] ? localStorage.getItem('pdfstudyo.theme') : 'auto'; }
  catch { return 'auto'; }
}
function isDarkTheme() {
  const t = getTheme();
  return t === 'dark' || (t === 'auto' && darkQuery.matches);
}
function applyTheme(theme, notifyNative = true) {
  document.documentElement.dataset.theme = theme;
  if ((NATIVE || SHELL) && notifyNative) native({ action: 'theme', value: theme });
  renderTabStrip();
  document.dispatchEvent(new Event('themechange'));
}
function setTheme(theme, announce = true) {
  try { localStorage.setItem('pdfstudyo.theme', theme); } catch { }
  applyTheme(theme);
  if (announce) toast(`Görünüm: ${THEMES[theme].label}`);
}
// Yerel uygulama: menüden seçilince ya da başka sekmede değişince
window.PDFSTUDYO_applyTheme = theme => {
  if (!THEMES[theme]) return;
  try { localStorage.setItem('pdfstudyo.theme', theme); } catch { }
  applyTheme(theme, false);
};
window.addEventListener('storage', e => { if (e.key === 'pdfstudyo.theme') applyTheme(getTheme(), false); });
darkQuery.addEventListener?.('change', () => document.dispatchEvent(new Event('themechange')));

// Yerel uygulama, kaydetme penceresinde dosya kaydedilince bunu çağırır
window.PDFSTUDYO_saved = path => toast('Kaydedildi: ' + path.replace(/^\/Users\/[^/]+/, '~'), 'ok');

function modal({ title, body, foot, width, onClose }) {
  const back = document.createElement('div');
  back.className = 'modal-back';
  back.innerHTML = `<div class="modal" style="${width ? `width:min(${width}px,100%)` : ''}">
    <div class="modal-head"><h2>${esc(title)}</h2><button class="btn ghost icon-btn" data-close aria-label="Kapat">✕</button></div>
    <div class="modal-body"></div><div class="modal-foot"></div></div>`;
  const close = () => { back.remove(); document.removeEventListener('keydown', onKey); onClose?.(); };
  const onKey = e => { if (e.key === 'Escape' && back === $('#modal-root').lastElementChild) close(); };   // üst üste pencerede yalnız üstteki
  document.addEventListener('keydown', onKey);
  back.addEventListener('mousedown', e => { if (e.target === back) close(); });
  $('[data-close]', back).onclick = close;
  if (typeof body === 'string') $('.modal-body', back).innerHTML = body; else if (body) $('.modal-body', back).append(body);
  if (foot) $('.modal-foot', back).innerHTML = foot; else $('.modal-foot', back).remove();
  $('#modal-root').append(back);
  return { el: back, close };
}

// E-imzalı belge rozeti (okuyucu ve düzenleyici araç çubuğu). Karartılınca imza geçersiz olur, Geri Al ile
// döner: rozet hep yerinde durur, imzasızken gizlenir
const SIGNED_TIP = 'Bu belge e-imzalı. Not, vurgu ve yer imleri imzayı bozmadan eklenir; metin ve sayfa değişiklikleri imzada «belge değiştirildi» olarak görünür. Karartmada belge baştan yazılır, e-imza geçersiz olur.';
const signedBadge = info =>
  `<span class="sig-badge" data-tip="${esc(SIGNED_TIP)}" ${info?.signed ? '' : 'hidden'}>${icon('signed')}<span class="tb-lbl">e-imzalı</span></span>`;

// E-imzalı belgede belgeyi baştan yazan işlemden önce sorulur. Dönen: devam edilsin mi?
async function confirmSignedRewrite(info, what) {
  if (!info?.signed) return true;
  return !!await askChoice({
    title: 'E-imza geçersiz olur',
    body: `<p style="margin-top:0">Bu belge e-imzalı. ${esc(what)} belgeyi baştan yazar; sonuçtaki dosyada e-imza geçersiz olur.</p>
      <p class="muted small" style="margin-bottom:0">Not, vurgu ve yer imleri imzayı bozmaz. İmzalı hâli korumak için işlemden önce
      belgeyi kaydedebilir ya da sonucu Farklı Kaydet ile ayrı bir dosyaya kaydedebilirsiniz.</p>`,
    choices: [{ id: '', label: 'Vazgeç' }, { id: 'yes', label: 'Yine de devam et', primary: true }],
  });
}

// Birkaç seçenekli soru: seçilen düğmenin kimliği; Vazgeç ya da pencere kapatılırsa boş
function askChoice({ title, body, choices, width = 520 }) {
  return new Promise(resolve => {
    let picked = '';
    const m = modal({
      title, body, width, onClose: () => resolve(picked),
      foot: choices.map(c => `<button class="btn ${c.primary ? 'primary' : ''}" data-choice="${c.id}">${c.icon ? icon(c.icon) : ''}${esc(c.label)}</button>`).join(''),
    });
    $$('[data-choice]', m.el).forEach(b => b.onclick = () => { picked = b.dataset.choice; m.close(); });
  });
}

