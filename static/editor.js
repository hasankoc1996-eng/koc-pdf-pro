/* Koç PDF Pro — düzenleme araçları. Okuma ekranındaki (reader.js) sayfaların üstünde çalışan katman:
   "Düzenle"ye basınca açılan ikinci araç satırı, sayfaya eklenen öğeler, metin düzenleme, sayfa küçük resimleri
   ve sayfa düzeni. Belgenin kendisini ve sayfaların çizimini okuma ekranı yönetir. */
'use strict';
(function () {
  let host = null;       // okuma ekranı: belge bilgisi, ölçek, sayfa öğeleri (bkz. reader.js editHost)
  const ED = {
    editing: false,      // düzenleme araç satırı açık mı
    tool: 'select',
    selected: new Set(), // küçük resimlerde seçili sayfalar
    anchor: 0,
    grid: false,         // sayfa düzeni: tüm sayfalar ızgarada
    items: [],           // uygulanmamış eklemeler (her biri kendi sayfasında: it.page)
    edits: new Map(),    // "sayfa:satır" -> {page, i, text}: değiştirilen satırlar
    lines: new Map(),    // sayfa -> düzenlenebilir satırlar (Metni Düzenle aracı)
    linesLoading: new Set(),
    linesGen: 0,         // belge değişince eski satır istekleri yok sayılsın
    words: new Map(),    // sayfa -> satır satır kelimeler (Vurgula aracı metne yapışsın diye)
    wordsLoading: new Set(),
    selItem: null,
    opts: { font: 'sans', size: 12, color: '#000000', bold: false, hl: '#ffe14d', mark: 'highlight', markLine: '#d6453d',
            pen: '#1d4ed8', penW: 2, penMode: 'pen', marker: '#ffe14d', markerW: 11, box: '#d6453d' },
  };
  let seq = 0;
  let flushing = null;
  let target = null;     // sağ tık › "Buraya …": resim, imza ya da kaşe bu noktaya konur ({page, x, y})

  const TOOLS = [
    { id: 'select', icon: 'pointer', label: 'Seç', hint: '' },
    { id: 'text', icon: 'text', label: 'Metin Ekle', hint: 'Sayfada metin eklemek istediğiniz yere tıklayın.' },
    { id: 'textedit', icon: 'textedit', label: 'Metni Düzenle', hint: 'Değiştirmek istediğiniz paragrafa tıklayın; metin paragrafın içinde yeniden dizilir. Enter: onayla, Shift+Enter: alt satır, Esc: vazgeç.' },
    { id: 'whiteout', icon: 'eraser', label: 'Beyaz Kutu', hint: 'Silmek istediğiniz alanı sürükleyin; altındaki yazı silinir, üstüne yeni metin ekleyebilirsiniz.' },
    { id: 'redact', icon: 'redact', label: 'Karart', hint: 'Sürükleyerek alanı karartın. Altındaki metin kalıcı olarak silinir.' },
    { id: 'highlight', icon: 'highlight', label: 'Vurgula', hint: 'Metnin üzerinde sürükleyin: işaret kelimelere yapışır. Metin olmayan yerde (ya da ⌥ basılıyken) serbest alan vurgulanır.' },
    { id: 'box', icon: 'box', label: 'Çerçeve', hint: 'Sürükleyerek dikdörtgen çerçeve çizin.' },
    { id: 'pen', icon: 'pen', label: 'Kalem', hint: 'Serbest çizim yapın. Shift basılıyken düz çizgi çizer; Fosforlu ile satırları boyayabilirsiniz.' },
    { id: 'line', icon: 'line', label: 'Çizgi', hint: 'Sürükleyerek düz çizgi çizin. Shift: yatay, dikey ya da 45°.' },
    { id: 'image', icon: 'img', label: 'Resim', action: true },
    { id: 'signature', icon: 'signature', label: 'İmza', action: true },
    { id: 'stamp', icon: 'stamp', label: 'Kaşe', action: true },
  ];
  const RECT_TOOLS = new Set(['whiteout', 'redact', 'highlight', 'box']);
  const HL_COLORS = ['#ffe14d', '#8ef0a0', '#8fd3ff', '#ffa3d1'];
  const MARKER_OPACITY = 0.4;   // fosforlu kalem: yarı saydam, altındaki yazı okunur

  // Shift ile çizgi: başlangıçtan geçen yatay, dikey ya da 45° doğrultuya oturt (ekran pikselleriyle)
  function snapAngle([x0, y0], [x1, y1], W, H) {
    const dx = (x1 - x0) * W, dy = (y1 - y0) * H;
    const angle = Math.round(Math.atan2(dy, dx) / (Math.PI / 4)) * (Math.PI / 4);
    const len = Math.hypot(dx, dy) * Math.abs(Math.cos(Math.atan2(dy, dx) - angle));
    return [x0 + Math.cos(angle) * len / W, y0 + Math.sin(angle) * len / H];
  }
  const LINE_COLORS = ['#d6453d', '#1d4ed8', '#1f8a4c', '#111111'];
  const MARK_STYLES = [['highlight', 'highlight', 'Vurgu'], ['underline', 'underline', 'Altını çiz'], ['strikeout', 'strike', 'Üstünü çiz']];

  const info = () => host?.info();
  const sid = () => info().id;
  const scale = () => host.scale();
  const pageUrl = (i, w) => `/api/edit/${sid()}/page/${i}?w=${w}&k=${info().pages[i].k}`;
  const pendingCount = () => ED.items.length + ED.edits.size;
  const clamp = (v, a, b) => Math.min(Math.max(v, a), b);
  const pagesBox = () => host?.pagesBox();
  const wrapOf = i => host?.pageEl(i);

  // ================================================================ okuma ekranına bağlanma
  // Okuma ekranı her çizildiğinde (belge açıldı, sayfa sayısı ya da boyutu değişti) çağrılır
  function attach(h) {
    host = h;
    setupOverlay();
    const apply = $('#pending-apply'), cancel = $('#pending-cancel');
    if (apply) apply.onclick = () => flush().catch(() => { });
    if (cancel) cancel.onclick = discardPending;
    renderTools();
    applyToolClasses();
    renderItems();
    if (ED.grid) renderThumbs();
    loadForTool();
  }

  // Ekrandan çıkılırken (başka bir araca geçildi) uygulanmamış eklemeler belgeye işlenir
  function detach() {
    if (info() && pendingCount()) flush().catch(() => { });
  }

  // Başka bir belge açıldı ya da belge kapandı. editing: araç satırı açık kalsın mı
  function reset(editing = false) {
    resetPending();
    ED.selected = new Set();
    ED.grid = false;
    ED.tool = 'select';
    ED.editing = editing;
  }

  function resetPending() {
    ED.items = []; ED.edits = new Map(); ED.lines = new Map(); ED.words = new Map(); ED.linesGen++; ED.selItem = null;
  }

  // "Vazgeç": uygulanmamış eklemeleri at (yüklenmiş satırlar kalsın)
  function discardPending() {
    ED.items = []; ED.edits = new Map(); ED.selItem = null;
    renderItems();
    renderTools();
  }

  // Düzenleme araç satırını aç / kapat. Kapatınca uygulanmamış eklemeler belgeye işlenir.
  // tool: açılınca seçili gelecek araç. Dönen: değişti mi (eklemeler işlenemezse kapanmaz)
  async function setEditing(on, tool) {
    if (!on && ED.editing) {
      try { await flush(); } catch { return false; }
      ED.tool = 'select';
      ED.selItem = null;
      if (ED.grid) setGrid(false);
    }
    ED.editing = on;
    if (on && tool && TOOLS.some(t => t.id === tool && !t.action)) ED.tool = tool;
    host?.editingChanged(on);
    renderTools();
    applyToolClasses();
    renderItems();
    loadForTool();
    return true;
  }

  // Seçili araç sayfadaki metni gerektiriyorsa (Metni Düzenle, Vurgula) ekrandaki sayfalarınki yüklenir
  function loadForTool() {
    if (!ED.editing || !info()) return;
    host.near().forEach(i => pageNear(i));
  }

  // Okuma ekranı: bir sayfa ekrana yaklaştı
  function pageNear(i) {
    if (!ED.editing) return;
    if (ED.tool === 'textedit') loadLines(i, i === host.cur());
    if (ED.tool === 'highlight') loadWords(i);
  }

  // Belgenin yeni hâli okuma ekranına işlendi (araç, geri al, not…): satır ve kelime önbellekleri yenilenir
  function docChanged() {
    ED.lines = new Map();
    ED.words = new Map();
    ED.linesGen++;
    const n = info()?.pages.length || 0;
    ED.selected = new Set([...ED.selected].filter(i => i < n));
    renderItems();
    renderThumbs();
    loadForTool();
  }

  // ================================================================ araç satırı
  function renderTools() {
    const bar = $('#ed-bar');
    if (!bar) return;
    const t = TOOLS.find(t => t.id === ED.tool);
    const o = ED.opts;
    let opts = '';
    const sel = ED.selItem && ED.items.find(i => i.id === ED.selItem);
    const textCtx = ED.tool === 'text' || sel?.type === 'text';
    if (ED.grid) {
      opts = '';
    } else if (textCtx) {
      opts = `<div class="tool-opts">
        <select id="o-font" title="Yazı tipi"><option value="sans" ${o.font === 'sans' ? 'selected' : ''}>Arial</option>
          <option value="serif" ${o.font === 'serif' ? 'selected' : ''}>Times New Roman</option></select>
        <input type="number" id="o-size" min="4" max="144" value="${o.size}" title="Yazı boyutu (pt)">
        <button class="toggle ${o.bold ? 'on' : ''}" id="o-bold" title="Kalın">K</button>
        <input type="color" id="o-color" value="${o.color}" title="Renk"></div>`;
    } else if (ED.tool === 'highlight') {
      const line = o.mark !== 'highlight';
      const current = line ? o.markLine : o.hl;
      opts = `<div class="tool-opts">${MARK_STYLES.map(([id, ic, label]) =>
        `<button class="toggle icon ${o.mark === id ? 'on' : ''}" data-mark="${id}" title="${label}">${icon(ic)}</button>`).join('')}
        <span class="opt-sep"></span>${(line ? LINE_COLORS : HL_COLORS).map(c =>
        `<button class="toggle ${current === c ? 'on' : ''}" data-hl="${c}" style="background:${c};border-color:${current === c ? 'var(--text)' : 'var(--border-strong)'}" title="Renk"></button>`).join('')}</div>`;
    } else if (ED.tool === 'pen' || ED.tool === 'line') {
      const marker = ED.tool === 'pen' && o.penMode === 'marker';
      opts = `<div class="tool-opts">${ED.tool === 'pen' ? `
        <button class="toggle icon ${marker ? '' : 'on'}" data-penmode="pen" title="Kalem">${icon('pen')}</button>
        <button class="toggle icon ${marker ? 'on' : ''}" data-penmode="marker" title="Fosforlu kalem">${icon('highlight')}</button>
        <span class="opt-sep"></span>` : ''}${marker
        ? HL_COLORS.map(c => `<button class="toggle ${o.marker === c ? 'on' : ''}" data-marker="${c}" style="background:${c};border-color:${o.marker === c ? 'var(--text)' : 'var(--border-strong)'}" title="Renk"></button>`).join('')
          + `<select id="o-markerw" title="Kalınlık">${[8, 11, 14].map(w => `<option value="${w}" ${o.markerW == w ? 'selected' : ''}>${w} pt</option>`).join('')}</select>`
        : `<input type="color" id="o-pen" value="${o.pen}" title="Renk">
        <select id="o-penw" title="Kalınlık">${[1, 2, 3, 5, 8].map(w => `<option value="${w}" ${o.penW == w ? 'selected' : ''}>${w} pt</option>`).join('')}</select>`}</div>`;
    } else if (ED.tool === 'box') {
      opts = `<div class="tool-opts"><input type="color" id="o-box" value="${o.box}" title="Çerçeve rengi"></div>`;
    } else if (sel?.type === 'stamp') {
      opts = `<div class="tool-opts">${STAMP_COLORS.map(([c, name]) =>
        `<button class="toggle ${sel.color === c ? 'on' : ''}" data-stampcolor="${c}" style="background:${c};border-color:${sel.color === c ? 'var(--text)' : 'var(--border-strong)'}" title="${name}"></button>`).join('')}
        <span class="opt-sep"></span><label class="check small"><input type="checkbox" id="o-stampall" ${sel.all ? 'checked' : ''}>Tüm sayfalara bas</label></div>`;
    }
    const hint = ED.grid ? '<span class="tool-hint">Sayfaları sürükleyerek sıralayın. ⌘ veya ⇧ ile birden çok sayfa seçin. Çift tıklayınca sayfa açılır.</span>'
      : t?.hint ? `<span class="tool-hint" title="${esc(t.hint)}"><b>${esc(t.label)}:</b> ${esc(t.hint)}</span>` : '';
    bar.innerHTML = `<div class="tb-group" ${ED.grid ? 'hidden' : ''}>${TOOLS.map(t => `<button class="tb-btn ${ED.tool === t.id ? 'on' : ''}" data-tool="${t.id}"
        data-tip="${esc(t.label)}" aria-label="${esc(t.label)}">${icon(t.icon)}</button>`).join('')}${tbSep()}</div>
      ${tbBtn('ed-grid', 'grid', ED.grid ? 'Sayfa görünümüne dön' : 'Sayfa düzeni: sürükleyerek sırala, döndür, sil', ED.grid ? 'on' : '')}
      ${tbBtn('ed-insert', 'plus', 'Sayfa ekle: PDF, resim, Word, Excel ya da boş sayfa')}
      ${tbBtn('ed-find', 'search', 'Bul ve değiştir')}
      <div class="ed-opts" ${opts || hint ? '' : 'hidden'}>${opts}${hint}</div>`;
    $$('[data-tool]', bar).forEach(b => b.onclick = () => chooseTool(b.dataset.tool));
    $('#ed-grid').onclick = () => setGrid(!ED.grid);
    $('#ed-insert').onclick = insertDialog;
    $('#ed-find').onclick = () => host.openReplace();
    const bind = (id, ev, fn) => { const el = $(id); if (el) el[ev] = fn; };
    const applyText = () => {
      if (sel?.type === 'text') { Object.assign(sel, { font: o.font, size: o.size, bold: o.bold, color: o.color }); renderItems(); }
    };
    bind('#o-font', 'onchange', e => { o.font = e.target.value; applyText(); });
    bind('#o-size', 'oninput', e => { o.size = clamp(+e.target.value || 12, 4, 144); applyText(); });
    bind('#o-bold', 'onclick', () => { o.bold = !o.bold; applyText(); renderTools(); });
    bind('#o-color', 'oninput', e => { o.color = e.target.value; applyText(); });
    bind('#o-pen', 'oninput', e => o.pen = e.target.value);
    bind('#o-penw', 'onchange', e => o.penW = +e.target.value);
    bind('#o-markerw', 'onchange', e => o.markerW = +e.target.value);
    $$('[data-penmode]', bar).forEach(b => b.onclick = () => { o.penMode = b.dataset.penmode; renderTools(); });
    $$('[data-marker]', bar).forEach(b => b.onclick = () => { o.marker = b.dataset.marker; renderTools(); });
    bind('#o-box', 'oninput', e => o.box = e.target.value);
    bind('#o-stampall', 'onchange', e => { sel.all = e.target.checked; renderItems(); });
    $$('[data-stampcolor]', bar).forEach(b => b.onclick = () => { sel.color = b.dataset.stampcolor; renderItems(); renderTools(); });
    $$('[data-hl]', bar).forEach(b => b.onclick = () => { if (o.mark === 'highlight') o.hl = b.dataset.hl; else o.markLine = b.dataset.hl; renderTools(); });
    $$('[data-mark]', bar).forEach(b => b.onclick = () => { o.mark = b.dataset.mark; renderTools(); });
  }

  async function chooseTool(id) {
    if (TOOLS.find(t => t.id === id)?.action) target = null;   // araç satırından: görünen sayfanın ortasına
    if (id === 'image') return addImage();
    if (id === 'signature') return signatureDialog();
    if (id === 'stamp') return stampDialog();
    // E-imzalı belgede karartma belgeyi baştan yazar (imza geçersiz olur): araç seçilirken sorulur
    if (id === 'redact' && ED.tool !== 'redact' && !await confirmSignedRewrite(info(), 'Karartma')) return;
    ED.tool = id;
    if (id !== 'select') ED.selItem = null;
    window.getSelection()?.removeAllRanges();
    renderTools();
    renderItems();
    loadForTool();
    applyToolClasses();
  }

  // Sayfa katmanının fare davranışı: araç seçiliyken sayfa aracındır; "Seç"te ve okurken metin seçilir
  function applyToolClasses() {
    const box = pagesBox();
    if (!box) return;
    const t = ED.editing ? ED.tool : null;
    box.classList.toggle('editing', !!t);
    box.classList.toggle('crosshair', RECT_TOOLS.has(t) || t === 'pen' || t === 'line');
    box.classList.toggle('text-cursor', t === 'text');
    box.classList.toggle('select-mode', !t || t === 'select');
  }

  // ================================================================ sayfa küçük resimleri ve sayfa düzeni
  function setGrid(on) {
    ED.grid = on;
    if (on) { ED.selItem = null; if (!ED.selected.size) ED.selected = new Set([host.cur()]); }
    host.setGrid(on);
    renderTools();
    renderThumbs();
    if (!on) host.goPage(host.cur());
  }

  // Yan paneldeki liste ya da sayfa düzeni (ızgara). Sürükleyerek sıralanır; ⌘ / ⇧ ile birden çok sayfa seçilir.
  function renderThumbs() {
    const box = ED.grid ? $('#rd-grid') : host?.thumbsBox();
    if (!box || !info()) return;
    const scroll = box.scrollTop;
    const cur = host.cur();
    const selN = ED.selected.size;
    const bar = selN > 1 || (ED.grid && selN > 0) ? `<div class="sel-bar"><b>${selN} sayfa seçili</b>
        <button class="btn sm ghost icon-btn" data-sel="rotccw" title="Sola döndür">${icon('rotccw')}</button>
        <button class="btn sm ghost icon-btn" data-sel="rotcw" title="Sağa döndür">${icon('rotcw')}</button>
        <button class="btn sm ghost icon-btn" data-sel="dup" title="Çoğalt">${icon('copy')}</button>
        <button class="btn sm ghost icon-btn" data-sel="extract" title="Seçilenleri ayrı bir PDF olarak kaydet">${icon('extract')}</button>
        <button class="btn sm ghost icon-btn" data-sel="del" title="Sil">${icon('trash')}</button>
        <button class="btn sm ghost" data-sel="none">Seçimi kaldır</button></div>` : '';
    box.innerHTML = bar + info().pages.map((p, i) => `
      <div class="thumb ${i === cur && !ED.grid ? 'current' : ''} ${ED.selected.has(i) ? 'selected' : ''}" draggable="true" data-i="${i}" style="--ar:${p.w / p.h}">
        <div class="img-box"><img loading="lazy" src="${pageUrl(i, 320)}" alt="Sayfa ${i + 1}"></div>
        <div class="num">${i + 1}</div>
        <div class="t-actions">
          <button data-a="rotccw" title="Sola döndür">${icon('rotccw')}</button>
          <button data-a="rotcw" title="Sağa döndür">${icon('rotcw')}</button>
          <button data-a="dup" title="Çoğalt">${icon('copy')}</button>
          <button data-a="del" title="Sil">${icon('trash')}</button>
        </div></div>`).join('');
    box.scrollTop = scroll;

    $$('[data-sel]', box).forEach(b => b.onclick = () => pageAction(b.dataset.sel, [...ED.selected].sort((a, b) => a - b)));
    $$('.thumb', box).forEach(el => {
      const i = +el.dataset.i;
      el.onclick = e => {
        if (e.target.closest('.t-actions')) return;
        if (e.metaKey || e.ctrlKey) {
          if (!ED.selected.size) ED.selected.add(host.cur());   // listede: okunan sayfa da seçime girer
          ED.selected.has(i) ? ED.selected.delete(i) : ED.selected.add(i);
          ED.anchor = i;
        } else if (e.shiftKey) {
          const from = ED.selected.size ? ED.anchor : host.cur();
          const [a, b] = [Math.min(from, i), Math.max(from, i)];
          ED.selected = new Set(Array.from({ length: b - a + 1 }, (_, k) => a + k));
        } else if (ED.grid) {
          ED.selected = new Set([i]);
          ED.anchor = i;
        } else {
          ED.selected = new Set();
          ED.anchor = i;
          host.goPage(i);
        }
        renderThumbs();
      };
      el.ondblclick = () => { if (ED.grid) { ED.selected = new Set(); host.setCur(i); setGrid(false); } };
      el.oncontextmenu = e => {   // seçili sayfalardan birine: hepsine uygulanır
        e.preventDefault();
        const pages = ED.selected.has(i) && ED.selected.size > 1 ? [...ED.selected].sort((a, b) => a - b) : [i];
        contextMenu(e.clientX, e.clientY, [
          pages.length === 1 ? { label: ED.grid ? 'Sayfayı aç' : 'Sayfaya git', icon: 'right', run: () => (ED.grid ? el.ondblclick() : host.goPage(i)) } : null,
          'sep', ...pageMenuItems(pages)]);
      };
      $$('[data-a]', el).forEach(b => b.onclick = () => pageAction(b.dataset.a, [i]));
    });
    enableThumbDrag(box);
    if (!ED.grid) box.querySelector('.thumb.current')?.scrollIntoView({ block: 'nearest' });
  }

  function enableThumbDrag(box) {
    let from = null;
    const clear = () => $$('.drop-before,.drop-after', box).forEach(t => t.classList.remove('drop-before', 'drop-after'));
    const targetOf = (el, e) => {
      const r = el.getBoundingClientRect();
      const after = ED.grid ? e.clientX > r.left + r.width / 2 : e.clientY > r.top + r.height / 2;
      return { idx: +el.dataset.i + (after ? 1 : 0), after };
    };
    $$('.thumb', box).forEach(el => {
      el.addEventListener('dragstart', e => {
        from = +el.dataset.i; el.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', String(from));
      });
      el.addEventListener('dragend', () => { el.classList.remove('dragging'); clear(); from = null; });
      el.addEventListener('dragover', e => {
        if (from == null) return;
        e.preventDefault();
        clear();
        el.classList.add(targetOf(el, e).after ? 'drop-after' : 'drop-before');
      });
      el.addEventListener('drop', e => {
        if (from == null) return;
        e.preventDefault();
        const { idx } = targetOf(el, e);
        clear();
        movePages(ED.selected.has(from) ? [...ED.selected].sort((a, b) => a - b) : [from], idx);
      });
    });
  }

  async function movePages(moving, before) {
    const n = info().pages.length;
    const rest = [...Array(n).keys()].filter(i => !moving.includes(i));
    const pos = rest.filter(i => i < before).length;
    const order = [...rest.slice(0, pos), ...moving, ...rest.slice(pos)];
    if (order.every((v, i) => v === i)) return;
    const oldCur = host.cur();
    try { await op({ op: 'reorder', order }, 'Sıralanıyor…'); } catch { return; }
    ED.selected = ED.grid || moving.length > 1 ? new Set(moving.map(m => order.indexOf(m))) : new Set();
    if (ED.grid) host.setCur(order.indexOf(oldCur)); else host.goPage(order.indexOf(oldCur));
    renderThumbs();
  }

  async function pageAction(action, pages) {
    if (!pages.length) return;
    if (action === 'none') { ED.selected = new Set(); return renderThumbs(); }
    try {
      if (action === 'rotcw' || action === 'rotccw') return await op({ op: 'rotate', pages, angle: action === 'rotcw' ? 90 : -90 }, 'Döndürülüyor…');
      if (action === 'dup') return await op({ op: 'duplicate', pages }, 'Çoğaltılıyor…');
      if (action === 'extract') {
        await flush();
        const r = await withBusy('Sayfalar çıkarılıyor…', () => postJSON(`/api/edit/${sid()}/extract`, { pages }));
        const where = await saveOutput(r, dirOf(info().path));
        if (where) toast('Kaydedildi: ' + shortPath(where), 'ok');
        return;
      }
      if (action === 'del') {
        if (pages.length >= info().pages.length) return toast('Tüm sayfalar silinemez; en az bir sayfa kalmalı.', 'error');
        if (pages.length > 1 && !confirm(`${pages.length} sayfa silinsin mi?`)) return;
        await op({ op: 'delete', pages }, 'Siliniyor…');
        ED.selected = new Set();
        renderThumbs();
      }
    } catch { /* hata gösterildi */ }
  }

  // ================================================================ sunucu işlemleri
  async function op(body, text = 'Uygulanıyor…') {
    await flush();
    let r;
    if (body instanceof FormData) r = await withBusy(text, () => api(`/api/edit/${sid()}/op`, { method: 'POST', body }));
    else r = await withBusy(text, () => postJSON(`/api/edit/${sid()}/op`, body));
    await host.apply(r);
    return r;
  }

  // Sayfadaki uygulanmamış eklemeleri belgeye işler (aynı anda iki kez çağrılırsa tek istek gider)
  function flush() {
    if (flushing) return flushing;
    if (!info() || !pendingCount()) return Promise.resolve();
    // Odaktaki metin kutusunun son hâlini al
    document.activeElement?.blur?.();
    const byPage = new Map();
    const part = pg => byPage.get(pg) || byPage.set(pg, { page: pg, items: [], edits: [] }).get(pg);
    for (const it of ED.items) {
      const ser = serialize(it);
      if (!ser) continue;
      if (it.all) info().pages.forEach((_, pg) => part(pg).items.push({ ...ser, ...copyPlace(it, pg) }));
      else part(it.page).items.push(ser);
    }
    for (const e of ED.edits.values()) part(e.page).edits.push({ ...ED.lines.get(e.page)[e.i], text: e.text });
    if (!byPage.size) { discardPending(); return Promise.resolve(); }
    flushing = withBusy('Değişiklikler uygulanıyor…', () =>
      postJSON(`/api/edit/${sid()}/op`, { op: 'pages_edit', pages: [...byPage.values()] }))
      .then(r => { resetPending(); return host.apply(r); })
      .finally(() => { flushing = null; });
    return flushing;
  }

  function serialize(it) {
    const base = { x: it.x, y: it.y, w: it.w, h: it.h };
    switch (it.type) {
      case 'text': return it.text.trim() ? { ...base, type: 'text', text: it.text, size: it.size, color: it.color, font: it.font, bold: it.bold } : null;
      case 'whiteout': return { ...base, type: 'whiteout' };
      case 'box': return { ...base, type: 'rect', stroke: it.color, width: 2 };
      case 'redact': return { ...base, type: 'redact' };
      case 'highlight': return { ...base, type: 'highlight', color: it.color };
      case 'image': return { ...base, type: 'image', data: it.data };
      case 'stamp': return { ...base, type: 'stamp', lines: it.lines, color: it.color };
      case 'pen': return { type: 'pen', points: it.points, color: it.color, width: it.width, opacity: it.opacity ?? 1 };
    }
  }

  // Geri Al önce henüz uygulanmamış son eklemeyi geri alır. Dönen: geri alınacak ekleme var mıydı
  function undoPending() {
    if (!ED.items.length && !ED.edits.size) return false;
    if (ED.items.length) ED.items.pop(); else ED.edits.delete([...ED.edits.keys()].pop());
    ED.selItem = null;
    renderItems();
    renderTools();
    return true;
  }

  function updatePendingBar() {
    const n = pendingCount();
    const bar = $('#pending');
    if (bar) {
      bar.hidden = n === 0;
      $('#pending-text').textContent = `${n} değişiklik henüz uygulanmadı`;
    }
    host?.refreshButtons();
  }

  // ---------------------------------------------------------------- öğeler
  function wrapSize(i) { const w = wrapOf(i); return { W: w.clientWidth, H: w.clientHeight }; }

  function renderItems() {
    const box = pagesBox();
    if (!box) return updatePendingBar();
    // Yazılmakta olan metin kutusu yeniden çizildikten sonra da odakta kalsın
    const active = document.activeElement;
    const typing = active?.tagName === 'TEXTAREA' && box.contains(active) ? active.closest('.item')?.dataset.id : null;
    const caret = typing && [active.selectionStart, active.selectionEnd];
    $$('.item, .line-box, .line-input', box).forEach(e => e.remove());
    const penPages = new Set(ED.items.filter(it => it.type === 'pen').map(it => it.page));
    for (const svg of $$('.pen-layer', box)) {
      const i = +svg.closest('.rd-page').dataset.i;
      if (!penPages.has(i)) { if (svg.firstChild) svg.innerHTML = ''; continue; }
      const { W, H } = wrapSize(i);
      svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
      svg.innerHTML = ED.items.filter(it => it.type === 'pen' && it.page === i).map(it =>
        `<polyline points="${it.points.map(([x, y]) => `${x * W},${y * H}`).join(' ')}" fill="none" stroke="${it.color}" stroke-width="${it.width * scale()}" stroke-opacity="${it.opacity ?? 1}" stroke-linecap="round" stroke-linejoin="round"/>`).join('');
    }
    for (const it of ED.items) {
      if (it.type === 'pen') continue;
      $('.overlay', wrapOf(it.page))?.append(itemEl(it));
      if (it.all) info().pages.forEach((_, pg) => { if (pg !== it.page) $('.overlay', wrapOf(pg))?.append(ghostEl(it, pg)); });
    }
    if (ED.editing && ED.tool === 'textedit') {
      for (const [i, lines] of ED.lines) {
        const ov = $('.overlay', wrapOf(i));
        if (ov) lines.forEach((l, k) => ov.append(lineBox(l, i, k, ED.edits.get(`${i}:${k}`)?.text)));
      }
    } else {
      for (const e of ED.edits.values()) $('.overlay', wrapOf(e.page))?.append(lineBox(ED.lines.get(e.page)[e.i], e.page, e.i, e.text));
    }
    const ta = typing && $(`.item[data-id="${typing}"] textarea`, box);
    if (ta) { ta.focus({ preventScroll: true }); ta.setSelectionRange(...caret); }
    updatePendingBar();
  }

  function place(el, it) {
    el.style.left = it.x * 100 + '%';
    el.style.top = it.y * 100 + '%';
    el.style.width = it.w * 100 + '%';
    el.style.height = it.h * 100 + '%';
  }

  function itemEl(it) {
    const el = document.createElement('div');
    el.className = 'item ' + ({ text: 'text-item', image: 'image-item', stamp: 'stamp-item' }[it.type] || 'rect-item');
    el.dataset.id = it.id;
    if (ED.selItem === it.id) el.classList.add('sel');
    place(el, it);
    if (it.type === 'whiteout') Object.assign(el.style, { background: '#fff', outline: el.classList.contains('sel') ? '' : '1px dashed #9aa1aa' });
    if (it.type === 'redact') el.style.background = '#000';
    if (it.type === 'highlight') Object.assign(el.style, { background: it.color, opacity: .45, mixBlendMode: 'multiply' });
    if (it.type === 'box') el.style.border = `${2 * scale()}px solid ${it.color}`;
    if (it.type === 'image') el.innerHTML = `<img src="${it.data}" alt="">`;
    if (it.type === 'stamp') el.innerHTML = stampSvg(it.lines, it.color);
    if (it.type === 'text') {
      el.innerHTML = '<span class="drag-bar">taşı</span><textarea spellcheck="false" placeholder="Metin yazın"></textarea>';
      const ta = $('textarea', el);
      ta.value = it.text;
      Object.assign(ta.style, {
        fontFamily: it.font === 'serif' ? '"Times New Roman", Times, serif' : 'Arial, Helvetica, sans-serif',
        fontSize: it.size * scale() + 'px', fontWeight: it.bold ? '700' : '400', color: it.color,
      });
      const fit = () => {
        const { H } = wrapSize(it.page);
        if (!H) return;   // sayfa henüz boyutlanmadı
        ta.style.height = 'auto';
        const h = Math.max(ta.scrollHeight + 2, it.size * scale() * 1.25);
        ta.style.height = h + 'px';
        it.h = h / H;
        el.style.height = it.h * 100 + '%';
      };
      ta.oninput = () => { it.text = ta.value; fit(); };
      ta.onfocus = () => selectItem(it.id, false);
      ta.onblur = () => {
        setTimeout(() => {
          const still = document.activeElement?.closest?.('.item')?.dataset.id === String(it.id);   // yeniden çizilen kutu
          if (!it.text.trim() && ED.items.includes(it) && !still) {
            ED.items = ED.items.filter(x => x !== it);
            if (ED.selItem === it.id) ED.selItem = null;
            renderItems();
          }
        }, 150);
      };
      requestAnimationFrame(fit);
    }
    el.insertAdjacentHTML('beforeend', '<button class="del" title="Sil">×</button><span class="handle"></span>');
    $('.del', el).onpointerdown = e => { e.stopPropagation(); e.preventDefault(); removeItem(it.id); };
    return el;
  }

  // "Tüm sayfalara bas": öbür sayfalarda aynı yerde, aynı boyutta (pt) soluk kopyası görünür
  function copyPlace(it, pg) {
    const src = info().pages[it.page], dst = info().pages[pg];
    const w = Math.min(it.w * src.w / dst.w, 1), h = Math.min(it.h * src.h / dst.h, 1);
    return { x: clamp(it.x, 0, 1 - w), y: clamp(it.y, 0, 1 - h), w, h };
  }

  function ghostEl(it, pg) {
    const el = document.createElement('div');
    el.className = 'item stamp-item ghost';
    place(el, copyPlace(it, pg));
    el.innerHTML = stampSvg(it.lines, it.color);
    return el;
  }

  function selectItem(id, rerender = true) {
    ED.selItem = id;
    const it = ED.items.find(i => i.id === id);
    if (it?.type === 'text') Object.assign(ED.opts, { font: it.font, size: it.size, bold: it.bold, color: it.color });
    $$('.item', pagesBox()).forEach(e => e.classList.toggle('sel', e.dataset.id === String(id)));
    if (rerender) renderTools(); else renderToolsKeepFocus();
  }

  function renderToolsKeepFocus() {
    const a = document.activeElement;
    renderTools();
    a?.focus?.();
  }

  function removeItem(id) {
    ED.items = ED.items.filter(i => i.id !== id);
    if (ED.selItem === id) ED.selItem = null;
    renderItems();
    renderTools();
  }

  function addItem(it, select = true) {
    it.id = ++seq;
    ED.items.push(it);
    if (select) ED.selItem = it.id;
    renderItems();
    return it;
  }

  // ---------------------------------------------------------------- fare etkileşimleri
  // Tüm sayfalar için tek dinleyici: tıklanan sayfanın katmanı bulunur, öğe o sayfaya eklenir
  function setupOverlay() {
    const box = pagesBox();
    if (!box || box.dataset.overlay) return;
    box.dataset.overlay = '1';
    let drag = null;
    const rel = (ov, e) => {
      const r = ov.getBoundingClientRect();
      return { x: clamp((e.clientX - r.left) / r.width, 0, 1), y: clamp((e.clientY - r.top) / r.height, 0, 1) };
    };
    const deselect = () => {
      if (!ED.selItem) return;
      ED.selItem = null;
      $$('.item.sel', box).forEach(x => x.classList.remove('sel'));
      renderTools();
    };

    box.addEventListener('pointerdown', e => {
      if (e.button !== 0 || !ED.editing) return;
      const ov = e.target.closest('.overlay');
      if (!ov) return deselect();   // "Seç" aracında sayfanın boş yerine (metne) tıklandı: metin seçimi sürer
      if (e.target.closest('.line-box, .line-input')) return;
      const pg = +ov.parentElement.dataset.i;
      if (pg !== host.cur()) host.setCur(pg);
      const itemNode = e.target.closest('.item');
      const p = rel(ov, e);

      // Var olan öğe: taşı / boyutlandır
      if (itemNode && ED.tool !== 'pen') {
        const it = ED.items.find(i => String(i.id) === itemNode.dataset.id);
        if (!it) return;
        const isHandle = e.target.classList.contains('handle');
        if (e.target.tagName === 'TEXTAREA' && !isHandle) { selectItem(it.id, false); return; }
        e.preventDefault();
        selectItem(it.id);
        drag = { mode: isHandle ? 'resize' : 'move', it, start: p, orig: { ...it }, el: itemNode, ov, page: pg };
        ov.setPointerCapture(e.pointerId);
        return;
      }
      deselect();

      // Vurgula: metnin üzerinde başlarsa işaret kelimelere yapışır; ⌥ basılıysa ya da metin yoksa serbest alan
      if (ED.tool === 'highlight' && !e.altKey) {
        const hit = wordAt(pg, p, false);
        if (hit) {
          e.preventDefault();
          drag = { mode: 'mark', page: pg, ov, start: hit, end: hit };
          ov.setPointerCapture(e.pointerId);
          drawMarkPreview(drag);
          return;
        }
        if (ED.opts.mark !== 'highlight') {
          toast('Altını ya da üstünü çizmek için metnin üzerinde sürükleyin.');
          return;
        }
      }

      if (RECT_TOOLS.has(ED.tool)) {
        e.preventDefault();
        const tmp = document.createElement('div');
        tmp.className = 'item rect-item';
        tmp.style.outline = '1.5px dashed var(--accent)';
        ov.append(tmp);
        drag = { mode: 'draw', start: p, el: tmp, ov, page: pg };
        ov.setPointerCapture(e.pointerId);
      } else if (ED.tool === 'pen' || ED.tool === 'line') {
        e.preventDefault();
        const o = ED.opts, marker = ED.tool === 'pen' && o.penMode === 'marker';
        const it = { type: 'pen', page: pg, points: [[p.x, p.y]], color: marker ? o.marker : o.pen,
          width: marker ? o.markerW : o.penW, opacity: marker ? MARKER_OPACITY : 1 };
        const svg = $('.pen-layer', ov);
        const { W, H } = wrapSize(pg);
        svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
        Object.entries({ fill: 'none', stroke: it.color, 'stroke-width': it.width * scale(), 'stroke-opacity': it.opacity,
          'stroke-linecap': 'round', 'stroke-linejoin': 'round' }).forEach(([k, v]) => line.setAttribute(k, v));
        svg.append(line);
        drag = { mode: 'pen', it, line, ov, page: pg, straight: ED.tool === 'line' };
        ov.setPointerCapture(e.pointerId);
      } else if (ED.tool === 'text') {
        e.preventDefault();
        addTextAt({ page: pg, x: p.x, y: p.y });
      }
    });

    box.addEventListener('pointermove', e => {
      if (!drag) return;
      const p = rel(drag.ov, e);
      if (drag.mode === 'mark') {
        const hit = wordAt(drag.page, p, true);
        if (hit) { drag.end = hit; drawMarkPreview(drag); }
      } else if (drag.mode === 'draw') {
        const x = Math.min(p.x, drag.start.x), y = Math.min(p.y, drag.start.y);
        place(drag.el, { x, y, w: Math.abs(p.x - drag.start.x), h: Math.abs(p.y - drag.start.y) });
      } else if (drag.mode === 'pen') {
        const { W, H } = wrapSize(drag.page);
        if (drag.straight || e.shiftKey) {
          const start = drag.it.points[0];
          drag.it.points = [start, e.shiftKey ? snapAngle(start, [p.x, p.y], W, H) : [p.x, p.y]];
        } else drag.it.points.push([p.x, p.y]);
        drag.line.setAttribute('points', drag.it.points.map(([x, y]) => `${x * W},${y * H}`).join(' '));
      } else if (drag.mode === 'move') {
        const { it, orig } = drag;
        it.x = clamp(orig.x + p.x - drag.start.x, 0, 1 - it.w);
        it.y = clamp(orig.y + p.y - drag.start.y, 0, 1 - it.h);
        place(drag.el, it);
      } else if (drag.mode === 'resize') {
        const { it, orig } = drag;
        it.w = clamp(orig.w + p.x - drag.start.x, 0.01, 1 - it.x);
        if (it.aspect) {   // resim ve kaşe: en-boy oranı korunur
          const { W, H } = wrapSize(drag.page);
          it.h = Math.min(it.w * W / it.aspect / H, 1 - it.y);
          it.w = it.h * H * it.aspect / W;
        } else if (it.type !== 'text') it.h = clamp(orig.h + p.y - drag.start.y, 0.005, 1 - it.y);
        place(drag.el, it);
        if (it.type === 'text') $('textarea', drag.el).dispatchEvent(new Event('input'));
      }
    });

    const end = e => {
      if (!drag) return;
      const d = drag;
      drag = null;
      if (d.mode === 'mark') {
        $$('.mark-preview', d.ov).forEach(x => x.remove());
        applyMark(d.page, markRects(d));
      } else if (d.mode === 'draw') {
        d.el.remove();
        const p = rel(d.ov, e);
        const it = { page: d.page, x: Math.min(p.x, d.start.x), y: Math.min(p.y, d.start.y), w: Math.abs(p.x - d.start.x), h: Math.abs(p.y - d.start.y) };
        const { W, H } = wrapSize(d.page);
        if (it.w * W < 4 || it.h * H < 4) return;
        it.type = ED.tool;
        if (ED.tool === 'highlight') it.color = ED.opts.hl;
        if (ED.tool === 'box') it.color = ED.opts.box;
        addItem(it, false);
      } else if (d.mode === 'pen') {
        const { W, H } = wrapSize(d.page);
        const [[x0, y0], [x1, y1] = [x0, y0]] = [d.it.points[0], d.it.points[d.it.points.length - 1]];
        const long = d.it.points.length > 2 || Math.hypot((x1 - x0) * W, (y1 - y0) * H) > 3;   // tıklama değil
        if (d.it.points.length > 1 && long) addItem(d.it, false); else d.line.remove();
      } else if (d.it?.all) renderItems();   // öbür sayfalardaki kaşe kopyaları da yeni yere
    };
    box.addEventListener('pointerup', end);
    box.addEventListener('pointercancel', end);
  }

  // Noktaya metin kutusu: yazmaya hemen başlanır
  function addTextAt(at) {
    const { W, H } = wrapSize(at.page);
    const lh = (ED.opts.size * scale() * 1.25) / H;
    const it = addItem({
      type: 'text', page: at.page, text: '', x: at.x, y: clamp(at.y - lh / 2, 0, 1 - lh), w: Math.min(0.45, 1 - at.x), h: lh,
      size: ED.opts.size, color: ED.opts.color, font: ED.opts.font, bold: ED.opts.bold,
    });
    if (it.w * W < 40) { it.x = Math.max(0, 1 - 160 / W); it.w = 1 - it.x; }
    renderItems();
    renderTools();
    setTimeout(() => $(`.item[data-id="${it.id}"] textarea`)?.focus({ preventScroll: true }), 0);
  }

  // ---------------------------------------------------------------- sağ tık menüsü
  // Sayfada sağ tık › "Buraya …": düzenleme araçları açılır, öğe tıklanan yere konur
  async function placeAt(kind, at) {
    if (!ED.editing) await setEditing(true);
    if (kind === 'text') return addTextAt(at);
    target = at;
    if (kind === 'image') return addImage();
    if (kind === 'signature') return signatureDialog();
    if (kind === 'stamp') return stampDialog();
  }

  // Düzenlerken eklenen (henüz uygulanmamış) öğeye sağ tık. Öğe değilse null
  function itemMenu(el) {
    const node = ED.editing && el.closest?.('.overlay .item:not(.ghost)');
    const it = node && ED.items.find(i => String(i.id) === node.dataset.id);
    if (!it) return null;
    selectItem(it.id);
    return [
      it.type === 'text' ? { label: 'Yazıyı düzenle', icon: 'text', run: () => $(`.item[data-id="${it.id}"] textarea`)?.focus() } : null,
      it.type === 'stamp' && info().pages.length > 1
        ? { label: it.all ? 'Yalnızca bu sayfaya bas' : 'Tüm sayfalara bas', icon: 'stamp', run: () => { it.all = !it.all; renderItems(); renderTools(); } } : null,
      { label: 'Kopyasını ekle', icon: 'copy', run: () => duplicateItem(it) },
      'sep',
      { label: 'Uygula', icon: 'check', hint: `${pendingCount()} değişiklik`, run: () => flush().catch(() => { }) },
      { label: 'Sil', icon: 'trash', hint: '⌫', danger: true, run: () => removeItem(it.id) },
    ];
  }

  function duplicateItem(it) {
    const copy = { ...it, x: clamp(it.x + 0.02, 0, 1 - it.w), y: clamp(it.y + 0.02, 0, 1 - it.h) };
    delete copy.id;
    addItem(copy);
    renderTools();
  }

  // Sayfa işlemleri: sayfada ve küçük resimlerde sağ tık (pages: seçili sayfalar)
  function pageMenuItems(pages) {
    const what = pages.length === 1 ? 'Sayfayı' : `${pages.length} sayfayı`;
    const last = Math.max(...pages);
    return [
      { label: `${what} sağa döndür`, icon: 'rotcw', run: () => pageAction('rotcw', pages) },
      { label: `${what} sola döndür`, icon: 'rotccw', run: () => pageAction('rotccw', pages) },
      { label: `${what} çoğalt`, icon: 'copy', run: () => pageAction('dup', pages) },
      { label: `${what} ayrı PDF olarak kaydet…`, icon: 'extract', run: () => pageAction('extract', pages) },
      { label: 'Sonrasına boş sayfa ekle', icon: 'plus', run: () => op({ op: 'blank', after: last }, 'Sayfa ekleniyor…').then(() => host.goPage(last + 1), () => { }) },
      'sep',
      { label: `${what} sil`, icon: 'trash', danger: true, disabled: pages.length >= info().pages.length, run: () => pageAction('del', pages) },
    ];
  }

  // ---------------------------------------------------------------- metne yapışan işaretleme
  // Vurgula aracı açıkken sayfadaki kelimeler (satır satır) yüklenir; işaret bastığınız kelimeden bıraktığınız
  // kelimeye kadar, satır yüksekliğinde çizilir (okuyucudaki metin seçimi gibi).
  async function loadWords(i) {
    if (!info() || ED.words.has(i) || ED.wordsLoading.has(i)) return;
    const gen = ED.linesGen, id = sid();
    ED.wordsLoading.add(i);
    try {
      let r = await api(`/api/edit/${id}/words/${i}`);
      if (r.scan && state.engines.ocr) r = await api(`/api/edit/${id}/words/${i}?ocr=1`);   // taranmış sayfa
      if (gen === ED.linesGen && info() && sid() === id) ED.words.set(i, r.lines);
    } catch { /* metin yoksa serbest alan çizilir */ }
    finally { ED.wordsLoading.delete(i); }
  }

  // Noktadaki kelime ({li, wi}). loose: satır aralarında ve kenarlarda da en yakın satır/kelime (sürüklerken)
  function wordAt(page, p, loose) {
    const lines = ED.words.get(page);
    if (!lines?.length) return null;
    let best = -1, bestD = Infinity;
    lines.forEach((l, li) => {
      const ws = l.words, x0 = ws[0][0], x1 = ws[ws.length - 1][0] + ws[ws.length - 1][1];
      const pad = l.h * 0.2;
      const dy = p.y < l.y - pad ? l.y - pad - p.y : p.y > l.y + l.h + pad ? p.y - (l.y + l.h + pad) : 0;
      const dx = p.x < x0 ? x0 - p.x : p.x > x1 ? p.x - x1 : 0;
      if (!loose && (dy > 0 || dx > 0.01)) return;
      if (dy * 4 + dx < bestD) { bestD = dy * 4 + dx; best = li; }
    });
    if (best < 0) return null;
    const ws = lines[best].words;
    const wi = ws.findIndex(w => p.x < w[0] + w[1]);
    return { li: best, wi: wi < 0 ? ws.length - 1 : wi };
  }

  // Seçilen kelimeler: satır başına bir dikdörtgen [x, y, genişlik, yükseklik]
  function markRects(d) {
    const lines = ED.words.get(d.page) || [];
    let a = d.start, b = d.end;
    if (b.li < a.li || (b.li === a.li && b.wi < a.wi)) [a, b] = [b, a];
    const rects = [];
    for (let li = a.li; li <= b.li; li++) {
      const l = lines[li], ws = l.words;
      const first = li === a.li ? a.wi : 0, last = li === b.li ? b.wi : ws.length - 1;
      const x0 = ws[first][0], x1 = ws[last][0] + (ws[last][3] ?? ws[last][1]);
      rects.push([x0, l.y, x1 - x0, l.h]);
    }
    return rects;
  }

  function drawMarkPreview(d) {
    $$('.mark-preview', d.ov).forEach(x => x.remove());
    const o = ED.opts, color = o.mark === 'highlight' ? o.hl : o.markLine;
    for (const [x, y, w, h] of markRects(d)) {
      const el = document.createElement('div');
      el.className = `mark-preview ${o.mark}`;
      el.style.setProperty('--c', color);
      place(el, { x, y, w, h });
      d.ov.append(el);
    }
  }

  // İşaret hemen belgeye işlenir (metin seçip vurgulamadaki gibi; Geri Al ile geri alınır)
  async function applyMark(page, rects) {
    if (!rects.length) return;
    const o = ED.opts;
    try {
      await op({ op: 'highlight', page, rects, kind: o.mark, color: o.mark === 'highlight' ? o.hl : o.markLine }, 'İşaretleniyor…');
    } catch { /* hata gösterildi */ }
  }

  // ---------------------------------------------------------------- metin düzenleme
  // Satırlar sayfa ekrana yaklaştıkça yüklenir
  async function loadLines(i, announce = false) {
    if (!info() || ED.lines.has(i) || ED.linesLoading.has(i)) return;
    const gen = ED.linesGen, id = sid();
    ED.linesLoading.add(i);
    try {
      const r = await api(`/api/edit/${id}/lines/${i}`);
      if (gen !== ED.linesGen || !info() || sid() !== id) return;
      ED.lines.set(i, r.lines);
      if (!r.lines.length && announce) toast('Bu sayfada düzenlenebilir metin yok (taranmış sayfa olabilir). "Beyaz Kutu" + "Metin Ekle" kullanabilirsiniz.');
      renderItems();
    } catch (e) { toast(e.message, 'error'); }
    finally { ED.linesLoading.delete(i); }
  }

  function lineFont(l) {
    return `${l.italic ? 'italic ' : ''}${l.bold ? '700' : '400'} ${l.size * scale()}px ${l.serif ? '"Times New Roman", Times, serif' : 'Arial, Helvetica, sans-serif'}`;
  }

  // Paragraf (l.lines dolu): metin paragrafın genişliğinde, aynı girinti, satır aralığı ve hizalamayla dizilir
  function paraStyle(l) {
    return {
      font: lineFont(l), color: l.color, lineHeight: l.lh * scale() + 'px',
      textIndent: (l.indent || 0) * scale() + 'px', textAlign: l.align || 'left',
    };
  }

  function lineBox(l, page, k, edited) {
    const el = document.createElement('div');
    const para = !!l.lines;
    el.className = 'line-box' + (para ? ' para' : '') + (edited != null ? ' edited' : '');
    const pad = para ? 0.003 : 0.15 * l.h;
    place(el, { x: l.x, y: l.y - pad, w: l.w, h: l.h + 2 * pad });
    el.title = edited != null ? 'Düzenlendi — tekrar değiştirmek için tıklayın' : 'Düzenlemek için tıklayın';
    if (edited != null) {
      el.textContent = edited;
      if (para) {   // önizleme: paragrafın kenarları arasında yeniden dizilmiş hâli
        Object.assign(el.style, paraStyle(l), { left: l.fl * 100 + '%', width: (l.fr - l.fl) * 100 + '%', height: 'auto', minHeight: (l.h + 2 * pad) * 100 + '%' });
      } else {
        Object.assign(el.style, { font: lineFont(l), color: l.color });
      }
    }
    if (ED.tool === 'textedit') el.onclick = () => editLine(page, k);
    return el;
  }

  function editLine(page, k) {
    const l = ED.lines.get(page)[k];
    if (l.lines) return editPara(page, k);
    const key = `${page}:${k}`;
    const ov = $('.overlay', wrapOf(page));
    $$('.line-input', pagesBox()).forEach(x => x.remove());
    const input = document.createElement('input');
    input.className = 'line-input';
    input.value = ED.edits.get(key)?.text ?? l.text;
    const { W, H } = wrapSize(page);
    const ctx = document.createElement('canvas').getContext('2d');
    ctx.font = lineFont(l);
    const size = () => input.style.width = Math.max(l.w * W, ctx.measureText(input.value).width + 24) + 'px';
    Object.assign(input.style, {
      left: l.x * W - 3 + 'px', top: (l.y - 0.2 * l.h) * H + 'px', height: l.h * 1.4 * H + 'px',
      font: lineFont(l), color: l.color,
    });
    size();
    input.oninput = size;
    let done = false;
    const commit = keep => {
      if (done) return; done = true;
      if (keep) {
        const v = input.value;
        if (v === l.text) ED.edits.delete(key); else ED.edits.set(key, { page, i: k, text: v });
      }
      input.remove();
      renderItems();
    };
    input.onkeydown = e => {
      e.stopPropagation();
      if (e.key === 'Enter') commit(true);
      if (e.key === 'Escape') commit(false);
    };
    input.onblur = () => commit(true);
    ov.append(input);
    input.focus({ preventScroll: true });
    input.select();
  }

  // Paragraf düzenleme: yazdıkça satırlar paragrafın kenarları arasında kayar, kutu aşağı doğru uzar
  function editPara(page, k) {
    const l = ED.lines.get(page)[k];
    const key = `${page}:${k}`;
    const ov = $('.overlay', wrapOf(page));
    $$('.line-input', pagesBox()).forEach(x => x.remove());
    const box = document.createElement('textarea');
    box.className = 'line-input para-input';
    box.spellcheck = false;
    box.value = ED.edits.get(key)?.text ?? l.text;
    const { W, H } = wrapSize(page);
    const pad = 3;
    Object.assign(box.style, paraStyle(l), {
      left: l.fl * W - pad + 'px', top: l.y * H - pad + 'px', width: (l.fr - l.fl) * W + 2 * pad + 'px',
    });
    const grow = () => { box.style.height = 'auto'; box.style.height = Math.max(box.scrollHeight, l.h * H + 2 * pad) + 'px'; };
    box.oninput = grow;
    let done = false;
    const commit = keep => {
      if (done) return; done = true;
      if (keep) {
        const v = box.value.replace(/[ \t]+$/gm, '').trim();
        if (v === l.text) ED.edits.delete(key); else ED.edits.set(key, { page, i: k, text: v });
      }
      box.remove();
      renderItems();
    };
    box.onkeydown = e => {
      e.stopPropagation();
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); commit(true); }
      if (e.key === 'Escape') commit(false);
    };
    box.onblur = () => commit(true);
    ov.append(box);
    grow();
    box.focus({ preventScroll: true });
  }

  // ---------------------------------------------------------------- resim ve imza
  // Sayfanın ekranda görünen kısmının ortası (resim ve imza oraya konur)
  function visibleCenterY(i) {
    const r = wrapOf(i).getBoundingClientRect(), st = host.scroller().getBoundingClientRect();
    const top = Math.max(r.top, st.top), bottom = Math.min(r.bottom, st.bottom);
    return clamp(((top + bottom) / 2 - r.top) / r.height, 0.1, 0.9);
  }

  function placeImage(data, natW, natH, widthFrac) {
    const at = target;
    target = null;
    const pg = at ? at.page : host.cur();
    const { W, H } = wrapSize(pg);
    const aspect = natW / natH;
    let w = widthFrac, h = w * W / aspect / H;
    if (h > 0.8) { h = 0.8; w = h * H * aspect / W; }
    const cy = at ? at.y : visibleCenterY(pg);
    ED.tool = 'select';
    addItem({ type: 'image', page: pg, data, aspect, x: at ? clamp(at.x - w / 2, 0, 1 - w) : (1 - w) / 2, y: clamp(cy - h / 2, 0, 1 - h), w, h });
    chooseTool('select');
    toast('Resmi sürükleyerek taşıyın, sağ alt köşeden boyutlandırın, sonra "Uygula"ya basın.');
  }

  function loadImage(src) {
    return new Promise((res, rej) => { const im = new Image(); im.onload = () => res(im); im.onerror = rej; im.src = src; });
  }

  async function fileToData(file) {
    const url = URL.createObjectURL(file);
    try {
      const im = await loadImage(url);
      const max = 2000, k = Math.min(1, max / Math.max(im.naturalWidth, im.naturalHeight));
      const keepPng = file.type === 'image/png';
      if (k === 1 && (keepPng || file.type === 'image/jpeg')) {
        const data = await new Promise(r => { const fr = new FileReader(); fr.onload = () => r(fr.result); fr.readAsDataURL(file); });
        return { data, w: im.naturalWidth, h: im.naturalHeight };
      }
      const c = document.createElement('canvas');
      c.width = Math.round(im.naturalWidth * k); c.height = Math.round(im.naturalHeight * k);
      c.getContext('2d').drawImage(im, 0, 0, c.width, c.height);
      return { data: keepPng ? c.toDataURL('image/png') : c.toDataURL('image/jpeg', 0.9), w: c.width, h: c.height };
    } finally { URL.revokeObjectURL(url); }
  }

  async function addImage() {
    const [file] = await pickFiles({ accept: 'image/*' });
    if (!file) return;
    try {
      const { data, w, h } = await fileToData(file);
      placeImage(data, w, h, 0.35);
    } catch { toast('Resim açılamadı. JPG veya PNG deneyin.', 'error'); }
  }

  // saveOnly (Ayarlar): imza belgeye konmadan bu bilgisayara kaydedilir, sonra onSaved çağrılır
  function signatureDialog({ saveOnly = false, onSaved } = {}) {
    let saved = null;
    try { saved = localStorage.getItem('pdfstudyo.signature'); } catch { }
    const m = modal({
      title: saveOnly ? 'İmzanızı çizin' : 'İmza ekle', width: 560,
      body: `<canvas class="sig-canvas" id="sig"></canvas>
        <div class="actions" style="margin-top:10px;justify-content:space-between">
          <div style="display:flex;gap:6px;align-items:center">
            <span class="muted small">Renk:</span>
            <button class="toggle" data-c="#111111" style="width:26px;height:26px;border-radius:50%;background:#111;border:2px solid var(--accent);cursor:pointer"></button>
            <button class="toggle" data-c="#1d3fbf" style="width:26px;height:26px;border-radius:50%;background:#1d3fbf;border:2px solid transparent;cursor:pointer"></button>
            <button class="btn sm ghost" id="sig-clear">Temizle</button>
            <button class="btn sm ghost" id="sig-file">Resimden yükle</button>
          </div>
          ${saveOnly ? '' : '<label class="check small"><input type="checkbox" id="sig-save" checked>İmzayı bu bilgisayarda hatırla</label>'}
        </div>
        ${saved && !saveOnly ? `<div class="sig-saved"><span class="muted small">Kayıtlı imza:</span><img src="${saved}" alt="Kayıtlı imza">
          <button class="btn sm" id="sig-use-saved">Bunu kullan</button><button class="btn sm ghost" id="sig-forget">Unut</button></div>` : ''}`,
      foot: `<button class="btn" data-close2>Vazgeç</button><button class="btn primary" id="sig-ok">${icon('check')}${saveOnly ? 'İmzayı kaydet' : 'İmzayı yerleştir'}</button>`,
    });
    const remember = data => { try { localStorage.setItem('pdfstudyo.signature', data); } catch { } };
    const finish = (data, w, h) => {
      m.close();
      if (!saveOnly) return placeImage(data, w, h, 0.25);
      remember(data);
      toast('İmza kaydedildi.', 'ok');
      onSaved?.();
    };
    const c = $('#sig', m.el);
    const dpr = window.devicePixelRatio || 1;
    c.width = c.clientWidth * dpr; c.height = c.clientHeight * dpr;
    const ctx = c.getContext('2d');
    ctx.scale(dpr, dpr);
    ctx.lineCap = ctx.lineJoin = 'round';
    ctx.lineWidth = 2.6;
    let color = '#111111', drawing = false, last = null, empty = true;
    $$('[data-c]', m.el).forEach(b => b.onclick = () => {
      color = b.dataset.c;
      $$('[data-c]', m.el).forEach(x => x.style.borderColor = x === b ? 'var(--accent)' : 'transparent');
    });
    const pos = e => { const r = c.getBoundingClientRect(); return [e.clientX - r.left, e.clientY - r.top]; };
    c.onpointerdown = e => { drawing = true; last = pos(e); c.setPointerCapture(e.pointerId); ctx.beginPath(); ctx.arc(last[0], last[1], 1.2, 0, 7); ctx.fillStyle = color; ctx.fill(); empty = false; };
    c.onpointermove = e => {
      if (!drawing) return;
      const p = pos(e);
      ctx.strokeStyle = color; ctx.beginPath(); ctx.moveTo(...last); ctx.lineTo(...p); ctx.stroke();
      last = p; empty = false;
    };
    c.onpointerup = () => drawing = false;
    $('#sig-clear', m.el).onclick = () => { ctx.clearRect(0, 0, c.width, c.height); empty = true; };
    $('[data-close2]', m.el).onclick = m.close;
    $('#sig-file', m.el).onclick = async () => {
      const [f] = await pickFiles({ accept: 'image/*' });
      if (!f) return;
      const { data, w, h } = await fileToData(f);
      finish(data, w, h);
    };
    const useSaved = $('#sig-use-saved', m.el);
    if (useSaved) useSaved.onclick = async () => {
      const im = await loadImage(saved);
      m.close();
      placeImage(saved, im.naturalWidth, im.naturalHeight, 0.25);
    };
    const forget = $('#sig-forget', m.el);
    if (forget) forget.onclick = () => { try { localStorage.removeItem('pdfstudyo.signature'); } catch { } $('.sig-saved', m.el).remove(); };
    $('#sig-ok', m.el).onclick = () => {
      if (empty) return toast('Önce imzanızı çizin.', 'error');
      const trimmed = trimCanvas(c);
      if (!trimmed) return toast('Önce imzanızı çizin.', 'error');
      if (!saveOnly && $('#sig-save', m.el).checked) remember(trimmed.data);
      finish(trimmed.data, trimmed.w, trimmed.h);
    };
  }

  // ---------------------------------------------------------------- kaşe
  // Ölçüler editor.py STAMP ile aynı (pt): sayfaya basılan kaşe önizlemeyle aynı düzende çıkar
  const STAMP = { main: 18, sub: 9.5, pad: 7, border: 1.8, radius: 3 };
  const STAMP_PRESETS = ['ASLI GİBİDİR', 'ASLININ AYNIDIR', 'ONAYLI SURETTİR', 'ASLI GÖRÜLMÜŞTÜR', 'TEBELLÜĞ EDİLDİ',
    'TASLAK', 'GİZLİDİR', 'İPTAL'];
  const STAMP_COLORS = [['#c62828', 'Kırmızı'], ['#1d3fbf', 'Mavi'], ['#111111', 'Siyah']];
  let measureCtx = null;

  function stampLayout(lines) {
    measureCtx ||= document.createElement('canvas').getContext('2d');
    const edge = STAMP.pad + STAMP.border;
    let y = edge, w = 0;
    const rows = lines.map((text, k) => {
      const size = k ? STAMP.sub : STAMP.main;
      measureCtx.font = `${k ? 400 : 700} ${size}px Arial, Helvetica, sans-serif`;
      w = Math.max(w, measureCtx.measureText(text).width);
      const row = { text, size, bold: !k, top: y };
      y += k ? size * 1.35 : size * 1.15 + 3;
      return row;
    });
    return { rows, w: w + 2 * edge, h: y + edge };
  }

  function stampSvg(lines, color) {
    const { rows, w, h } = stampLayout(lines);
    const b = STAMP.border;
    return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
      <rect x="${b / 2}" y="${b / 2}" width="${w - b}" height="${h - b}" rx="${STAMP.radius}" fill="none" stroke="${color}" stroke-width="${b}"/>
      ${rows.map(r => `<text x="${w / 2}" y="${r.top + r.size * 0.93}" text-anchor="middle" font-family="Arial, Helvetica, sans-serif"
        font-size="${r.size}" font-weight="${r.bold ? 700 : 400}" fill="${color}">${esc(r.text)}</text>`).join('')}</svg>`;
  }

  const stampToday = () => new Date().toLocaleDateString('tr-TR', { day: '2-digit', month: '2-digit', year: 'numeric' });

  // Kayıtlı kaşenin (Ayarlar) önizlemesi; tarih bugünün tarihiyle
  function stampPreview(saved) {
    return stampSvg([saved.text, saved.date ? stampToday() : '', saved.name].filter(Boolean), saved.color || STAMP_COLORS[0][0]);
  }

  // saveOnly (Ayarlar): kaşe bilgileri belgeye basılmadan kaydedilir, sonra onSaved çağrılır
  function stampDialog({ saveOnly = false, onSaved } = {}) {
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem('pdfstudyo.stamp') || '{}'); } catch { }
    const today = stampToday();
    const st = { text: saved.text || STAMP_PRESETS[0], date: saved.date ?? true, name: saved.name || '',
                 color: saved.color || STAMP_COLORS[0][0] };
    const n = saveOnly ? 0 : info().pages.length;
    const m = modal({
      title: saveOnly ? 'Kaşe' : 'Kaşe bas', width: 560,
      body: `<div class="st-presets">${STAMP_PRESETS.map(t => `<button class="btn sm" data-preset="${esc(t)}">${esc(t)}</button>`).join('')}</div>
        <div class="field"><label for="st-text">Kaşe yazısı</label><input class="input" id="st-text" maxlength="40" value="${esc(st.text)}"></div>
        <div class="st-row"><label class="check"><input type="checkbox" id="st-date" ${st.date ? 'checked' : ''}>Tarih</label>
          <input class="input" id="st-dateval" value="${today}" maxlength="20"></div>
        <div class="field"><label for="st-name">Ad soyad / unvan (isteğe bağlı)</label><input class="input" id="st-name" maxlength="60"
          value="${esc(st.name)}" placeholder="Örn. Av. Ayşe Demir"></div>
        <div class="st-row"><span class="muted small">Renk:</span>${STAMP_COLORS.map(([c, name]) =>
          `<button class="swatch" data-color="${c}" style="background:${c}" title="${name}"></button>`).join('')}
          ${n > 1 ? `<label class="check" style="margin-left:auto"><input type="checkbox" id="st-all">Tüm sayfalara bas (${n})</label>` : ''}</div>
        <div class="st-preview" id="st-preview"></div>`,
      foot: `<button class="btn" data-x>Vazgeç</button><button class="btn primary" id="st-ok">${icon('check')}${saveOnly ? 'Kaşeyi kaydet' : 'Kaşeyi yerleştir'}</button>`,
    });
    const $m = q => $(q, m.el);
    const lines = () => [$m('#st-text').value.trim(), $m('#st-date').checked ? $m('#st-dateval').value.trim() : '',
      $m('#st-name').value.trim()].filter(Boolean);
    const update = () => {
      $$('[data-color]', m.el).forEach(b => b.classList.toggle('on', b.dataset.color === st.color));
      $$('[data-preset]', m.el).forEach(b => b.classList.toggle('primary', b.dataset.preset === $m('#st-text').value.trim()));
      $m('#st-dateval').disabled = !$m('#st-date').checked;
      $m('#st-preview').innerHTML = lines().length ? stampSvg(lines(), st.color) : '<span class="muted small">Kaşe yazısını girin.</span>';
    };
    $$('[data-preset]', m.el).forEach(b => b.onclick = () => { $m('#st-text').value = b.dataset.preset; update(); });
    $$('[data-color]', m.el).forEach(b => b.onclick = () => { st.color = b.dataset.color; update(); });
    ['#st-text', '#st-dateval', '#st-name'].forEach(q => $m(q).oninput = update);
    $m('#st-date').onchange = update;
    $('[data-x]', m.el).onclick = m.close;
    $m('#st-ok').onclick = () => {
      const ls = lines();
      if (!$m('#st-text').value.trim()) return toast('Kaşe yazısını girin.', 'error');
      try {
        localStorage.setItem('pdfstudyo.stamp', JSON.stringify({ text: $m('#st-text').value.trim(), date: $m('#st-date').checked,
          name: $m('#st-name').value.trim(), color: st.color }));
      } catch { }
      m.close();
      if (!saveOnly) return placeStamp(ls, st.color, !!$m('#st-all')?.checked);
      toast('Kaşe kaydedildi.', 'ok');
      onSaved?.();
    };
    update();
  }

  // Kaşe gerçek boyutunda (başlık 18 pt) görünen sayfanın sağına (sağ tıktan gelindiyse tıklanan yere) yerleşir;
  // sürükleyip büyütülebilir
  function placeStamp(lines, color, all) {
    const at = target;
    target = null;
    const pg = at ? at.page : host.cur();
    const { w: nw, h: nh } = stampLayout(lines);
    const page = info().pages[pg];
    const w = Math.min(nw / page.w, 0.9), h = w * page.w / (nw / nh) / page.h;
    const cy = at ? at.y : visibleCenterY(pg);
    addItem({ type: 'stamp', page: pg, lines, color, all, aspect: nw / nh,
              x: clamp(at ? at.x - w / 2 : 0.92 - w, 0, 1 - w), y: clamp(cy - h / 2, 0, 1 - h), w, h });
    chooseTool('select');
    toast(all ? 'Kaşe tüm sayfalarda aynı yere basılacak. Sürükleyerek taşıyın, sonra "Uygula"ya basın.'
      : 'Kaşeyi sürükleyerek taşıyın, sağ alt köşeden büyütün, sonra "Uygula"ya basın.');
  }

  function trimCanvas(c) {
    const ctx = c.getContext('2d');
    const { width, height } = c;
    const px = ctx.getImageData(0, 0, width, height).data;
    let x0 = width, y0 = height, x1 = -1, y1 = -1;
    for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
      if (px[(y * width + x) * 4 + 3] > 8) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
    }
    if (x1 < 0) return null;
    const pad = 6;
    x0 = Math.max(0, x0 - pad); y0 = Math.max(0, y0 - pad); x1 = Math.min(width - 1, x1 + pad); y1 = Math.min(height - 1, y1 + pad);
    const out = document.createElement('canvas');
    out.width = x1 - x0 + 1; out.height = y1 - y0 + 1;
    out.getContext('2d').drawImage(c, x0, y0, out.width, out.height, 0, 0, out.width, out.height);
    return { data: out.toDataURL('image/png'), w: out.width, h: out.height };
  }

  // ================================================================ iletişim kutuları
  function insertDialog() {
    const m = modal({
      title: 'Sayfa ekle',
      body: `<div class="field" style="margin-bottom:14px"><label>Nereye?</label>
          <select class="input" id="ins-pos">
            <option value="after">Geçerli sayfadan (${host.cur() + 1}) sonra</option>
            <option value="before">Geçerli sayfadan önce</option>
            <option value="end">En sona</option><option value="start">En başa</option></select></div>
        <div class="choice-grid">
          <button class="choice" data-k="pdf"><span class="tool-icon" style="--c:var(--c-pages)">${icon('file')}</span><b>PDF dosyası</b></button>
          <button class="choice" data-k="img"><span class="tool-icon" style="--c:var(--c-convert)">${icon('img')}</span><b>Resim / tarama</b></button>
          <button class="choice" data-k="blank"><span class="tool-icon" style="--c:var(--muted)">${icon('plus')}</span><b>Boş sayfa</b></button>
          <button class="choice" data-k="word"><span class="tool-icon" style="--c:var(--c-convert)">${icon('wordpdf')}</span><b>Word belgesi</b></button>
          <button class="choice" data-k="excel"><span class="tool-icon" style="--c:var(--c-convert)">${icon('excel')}</span><b>Excel tablosu</b></button>
        </div>`,
    });
    $$('.choice', m.el).forEach(b => b.onclick = async () => {
      const pos = $('#ins-pos', m.el).value;
      const n = info().pages.length, cur = host.cur();
      const at = { after: cur + 1, before: cur, end: n, start: 0 }[pos];
      m.close();
      const k = b.dataset.k;
      if (k === 'blank') return op({ op: 'blank', after: at - 1 }, 'Sayfa ekleniyor…').then(() => host.goPage(at)).catch(() => { });
      const files = await pickFiles({ accept: { pdf: '.pdf', img: 'image/*', word: WORD_ACCEPT, excel: EXCEL_ACCEPT }[k], multiple: true });
      if (!files.length) return;
      try {
        let uploads = files;
        if (k === 'word' || k === 'excel') {   // önce PDF'e çevrilir
          const fd = new FormData(); files.forEach(f => fd.append('files', f, f.name));
          const res = await withBusy(k === 'word' ? 'Word belgesi PDF\'e çevriliyor…' : 'Excel tablosu PDF\'e çevriliyor…',
            () => api(`/api/convert/${k}-to-pdf`, { method: 'POST', body: fd }));
          const bad = res.files.find(r => r.error);
          if (bad) throw new Error(bad.error);
          uploads = await Promise.all(res.files.map(async r => new File([await (await fetch(r.url)).blob()], r.name, { type: 'application/pdf' })));
        }
        const fd = new FormData();
        fd.append('op', k === 'img' ? 'insert_images' : 'insert_pdf');
        fd.append('at', at);
        uploads.forEach(f => fd.append('files', f, f.name));
        await op(fd, 'Sayfalar ekleniyor…');
        host.goPage(at);
      } catch (e) { toast(e.message, 'error'); }
    });
  }

  // ================================================================ klavye
  // Okuma ekranının klavye dinleyicisi önce buraya sorar. Dönen: tuş burada karşılandı mı
  function onKey(e) {
    if (!ED.editing || !info()) return false;
    const tag = document.activeElement?.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return false;
    const del = e.key === 'Delete' || e.key === 'Backspace';
    if (del && ED.selItem) { e.preventDefault(); removeItem(ED.selItem); return true; }
    if (del && ED.grid && ED.selected.size) { e.preventDefault(); pageAction('del', [...ED.selected]); return true; }
    if (e.key === 'Escape' && (ED.selItem || ED.tool !== 'select')) { ED.selItem = null; chooseTool('select'); return true; }
    if (ED.grid && /^(Arrow|Page|Home$|End$)/.test(e.key)) return true;   // ızgarada sayfa gezilmez
    return false;
  }

  window.addEventListener('beforeunload', e => {
    if (info() && pendingCount()) { e.preventDefault(); e.returnValue = ''; }
  });

  window.Editor = {
    attach, detach, reset, setEditing, pageNear, docChanged, flush, undoPending, pendingCount, renderThumbs, onKey,
    useTool: chooseTool, placeAt, itemMenu, pageMenuItems,
    signatureDialog, stampDialog, stampPreview,   // Ayarlar › İmza ve kaşe (saveOnly: belgeye koymadan kaydeder)
    relayout: renderItems,   // yakınlaştırma değişti: eklemeler yeni ölçekte
    isEditing: () => ED.editing,
    isGrid: () => ED.grid,
  };
})();
