/* Koç PDF Pro — belge ekranı: PDF'i açın, okuyun, not alın; "Düzenle" ile düzenleme araçları (editor.js) açılır. */
'use strict';
(function () {
  const RD = {
    info: null,          // {id, name, path, pages:[{w,h,rot,k}]}
    path: null,          // Finder'dan açıldıysa özgün dosya yolu
    root: null,
    zoom: 'width',       // 'width' | 'page' | yüzde (sayı)
    scale: 1,
    cur: 0,
    tops: [],
    near: new Set(),     // görünür alana yakın sayfalar
    side: null,          // yan panel: null | 'pages' | 'marks' | 'notes'
    marks: { annots: [], outline: [] },
    dirty: false,        // özgün dosyaya kaydedilmemiş not/vurgu/yer imi var mı
    noteMode: false,
    search: { q: '', flat: [], idx: -1 },
    queue: [],
    opening: false,
    isDefault: null,
    onKey: null,
    io: null,
    ro: null,
    saveTimer: null,
    wantEdit: false,     // ekran çizilince düzenleme araçları açılsın (Düzenleyici girişinden gelindi)
    fields: [],          // doldurulabilir form alanları
    fieldSaving: null,   // belgeye işlenmekte olan alan değeri (sırayla)
    formBar: true,       // form bilgi şeridi (kapatılınca bu belgede yeniden çıkmaz)
  };
  const VIEW_KEY = 'pdfstudyo.view';
  RD.view = { spread: false, scroll: true, cover: true };   // görünüm (aşağıda: tek / iki sayfa, kaydırma)
  try { Object.assign(RD.view, JSON.parse(localStorage.getItem(VIEW_KEY) || '{}')); } catch { }
  RD.rows = [];
  const ROW_GAP = 14;   // iki sayfa arasındaki boşluk (CSS'teki .rd-row gap)
  const ZOOMS = [['width', 'Genişlik'], ['page', 'Tam sayfa'], ['50', '%50'], ['75', '%75'], ['100', '%100'],
    ['125', '%125'], ['150', '%150'], ['200', '%200'], ['300', '%300']];
  const PX_PER_PT = 96 / 72;
  const clamp = (v, a, b) => Math.min(Math.max(v, a), b);
  const sid = () => RD.info.id;
  const SID_KEY = 'pdfstudyo.sid' + (TAB_ID ? ':' + TAB_ID : '');   // sayfa yenilenince bu sekmenin belgesi geri gelsin
  const pages = () => RD.info.pages;
  const pageUrl = (i, w) => `/api/edit/${sid()}/page/${i}?w=${w}&k=${pages()[i].k}`;
  const lastPageKey = () => 'pdfstudyo.lastpage:' + (RD.path || `${RD.info.name}:${pages().length}`);
  const store = {
    get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { } },
  };

  // ================================================================ açma
  function queuePaths(paths) {
    if (!paths?.length) return;
    RD.queue = [paths[0]];
    if (paths.length > 1) toast('Birden fazla dosya seçildi; ilki açıldı.');
    if (RD.root) flushQueue();
  }

  async function flushQueue() {
    if (RD.opening || !RD.queue.length) return;
    openPath(RD.queue.shift());
  }

  // doc: {path} (diskteki dosya), {file, handle} (Windows) ya da {file}; şifre gerekirse sorulur
  async function openDoc(doc) {
    if (!doc) return;
    RD.opening = true;
    let info;
    try { info = await openDocument(doc); } finally { RD.opening = false; }
    if (info) setDoc(info, doc.path || null);
    else if (!RD.info && RD.root) renderEmpty();
  }

  const openPath = path => openDoc({ path });

  async function openUpload(file) {
    if (file) openDoc({ file, path: await droppedPath(file) });
  }

  function setDoc(info, path) {
    window.Editor.reset(window.Editor.isEditing());
    try { sessionStorage.setItem(SID_KEY, info.id); } catch { }
    RD.info = info;
    RD.path = path || info.path || null;
    RD.search = { q: '', flat: [], idx: -1 };
    RD.fields = [];
    RD.formBar = true;
    RD.dirty = !!info.unsaved;
    RD.noteMode = false;
    RD.marks = { annots: [], outline: [] };
    const saved = state.settings.resumePage ? store.get(lastPageKey(), 0) : 0;   // Ayarlar › Belgeler
    RD.cur = clamp(saved, 0, info.pages.length - 1);
    if (RD.root) renderShell();
    const jump = pendingJump();
    if (jump?.path && jump.path === RD.path) applyJump(jump);   // tüm belgelerde aramadan gelindi
    else if (RD.cur > 0) toast(`Kaldığınız yerden devam: sayfa ${RD.cur + 1}`);
  }

  async function closeDoc() {
    if (window.PDFSTUDYO_unsaved() && !confirm('Kaydedilmemiş değişiklikler var. Belge yine de kapatılsın mı?')) return;
    if (RD.info) postJSON(`/api/edit/${RD.info.id}/close`).catch(() => { });   // kurtarma listesine düşmesin
    window.Editor.reset();
    try { sessionStorage.removeItem(SID_KEY); } catch { }
    RD.dirty = false;
    RD.info = null;
    RD.path = null;
    renderEmpty();
  }

  // ================================================================ görünüm yaşam döngüsü
  // edit: düzenleme araçları açık gelsin
  async function mount(main, file, { edit = false } = {}) {
    RD.root = main;
    RD.wantEdit = edit;
    RD.onKey = onKey;
    document.addEventListener('keydown', RD.onKey);
    if (file) {
      renderEmpty();
      return openUpload(file);
    }
    if (RD.info) {
      // Bir araç sayfasında değişmiş olabilir: güncel hâlini al
      try { RD.info = await api(`/api/edit/${sid()}`); RD.dirty = !!RD.info.unsaved; } catch { RD.info = null; }
    } else if (!RD.queue.length) {
      // Sayfa yenilendi: bu sekmede açık olan belge geri gelsin
      let saved = null;
      try { saved = sessionStorage.getItem(SID_KEY); } catch { }
      if (saved) {
        try {
          const info = await api(`/api/edit/${saved}`);
          if (RD.root && !RD.info) return setDoc(info, info.path);
        } catch { try { sessionStorage.removeItem(SID_KEY); } catch { } }
      }
    }
    if (!RD.queue.length) RD.info ? renderShell() : renderEmpty();
    else renderEmpty();
    flushQueue();
  }

  function unmount() {
    if (!RD.root) return;
    window.Editor.detach();
    hideSelectionTools();
    closeMarkBar();
    $$('.rd-pop, .rd-allpanel').forEach(p => p.remove());
    document.removeEventListener('keydown', RD.onKey);
    RD.io?.disconnect();
    RD.ro?.disconnect();
    RD.root = null;
  }

  // ================================================================ boş ekran
  function renderEmpty() {
    if (!RD.root) return;
    RD.io?.disconnect();
    setTabTitle('PDF Okuyucu ve Düzenleyici');
    RD.root.innerHTML = `${idleToolbar()}<div class="page">
      <div class="page-head"><span class="tool-icon" style="--c:var(--c-read)">${icon('book')}</span>
        <div><h1>PDF Okuyucu ve Düzenleyici</h1><p>PDF'lerinizi açıp okuyun, not alın; "Düzenle" ile metin ekleyin ya da değiştirin, imza ve kaşe koyun, sayfaları düzenleyin.</p></div></div>
      <div class="drop" id="rd-drop"><div class="drop-icon">${icon('book')}</div>
        <b>PDF'i buraya bırakın ya da tıklayıp seçin</b><span class="muted">.pdf · .udf (UYAP)</span></div>
      <div id="rd-recent"></div>
      ${HOST === 'mac' ? `<div class="panel" id="rd-default"></div>` : ''}
    </div>`;
    const drop = $('#rd-drop');
    if (NATIVE) {
      drop.onclick = () => native({ action: 'openPDF' });
      drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
      drop.addEventListener('dragleave', () => drop.classList.remove('over'));
      drop.addEventListener('drop', async e => {
        e.preventDefault(); drop.classList.remove('over');
        if (e.dataTransfer.files.length) openDoc(await droppedDocument(e));
      });
    } else {
      setupDocDrop(drop, openDoc);
    }
    bindIdleToolbar(RD.root, async () => {
      if (NATIVE) return native({ action: 'openPDF' });
      const d = await pickDocument();
      if (d) openDoc(d);
    });
    renderRecent($('#rd-recent'), openPath);
    if (HOST === 'mac') { renderDefaultPanel(); native({ action: 'defaultStatus' }); }
  }

  function renderDefaultPanel() {
    const box = $('#rd-default');
    if (!box) return;
    if (RD.isDefault) {
      box.innerHTML = `<h3>${icon('check', 'width="15" height="15" style="vertical-align:-2px;color:var(--ok)"')} Koç PDF Pro varsayılan PDF uygulamanız</h3>
        <span class="muted">Finder'da bir PDF'e çift tıkladığınızda burada açılır.</span>`;
      return;
    }
    box.innerHTML = `<h3>PDF'lere çift tıklayınca burada açılsın mı?</h3>
      <p class="muted" style="margin:0 0 12px">Şu an PDF'ler başka bir uygulamayla açılıyor. İsterseniz Koç PDF Pro'yu varsayılan yapabilirsiniz.
        Varsayılan yapmadan da Finder'da PDF'e sağ tıklayıp <b>Birlikte Aç › Koç PDF Pro</b> diyebilirsiniz.</p>
      <button class="btn" id="rd-make-default">${icon('book')}Varsayılan PDF uygulaması yap</button>`;
    $('#rd-make-default').onclick = () => native({ action: 'setDefaultPDF' });
  }

  // ================================================================ okuma ekranı
  function renderShell() {
    if (!RD.root) return;
    const n = pages().length;
    const grid = window.Editor.isGrid();
    RD.root.innerHTML = `<div class="reader">
      <div class="doc-toolbar">
        ${tbBtn('rd-side-btn', 'sidebar', 'Yan panel: sayfalar, içindekiler, notlar', RD.side ? 'on' : '')}
        ${tbSep()}
        ${tbBtn('rd-save', 'save', 'Kaydet (⌘S)')}
        ${tbBtn('rd-saveas', 'saveas', 'Farklı Kaydet… (⇧⌘S)')}
        ${tbBtn('rd-history', 'history', 'Önceki sürümler: kaydedilmiş eski hâller')}
        ${canShare() ? tbBtn('rd-share', 'share', SHARE_HINT) : ''}
        ${NATIVE ? tbBtn('rd-copyfile', 'copy', COPY_FILE_HINT) : ''}
        ${tbBtn('rd-print', 'printer', 'Yazdır (⌘P)')}
        ${tbSep()}
        ${tbBtn('rd-undo', 'undo', 'Geri al (⌘Z)')}
        ${tbBtn('rd-redo', 'redo', 'Yinele (⇧⌘Z)')}
        ${tbSep()}
        <div class="tb-group">
          ${tbBtn('rd-prev', 'left', 'Önceki sayfa (←)')}
          <input class="tb-page" id="rd-page" value="${RD.cur + 1}" aria-label="Sayfa"><span class="muted tb-total">/ ${n}</span>
          ${tbBtn('rd-next', 'right', 'Sonraki sayfa (→)')}
        </div>
        ${tbSep()}
        <div class="tb-group">
          ${tbBtn('rd-zout', 'zoomout', 'Uzaklaştır (⌘−)')}
          <select class="tb-zoom" id="rd-zoom" data-tip="Yakınlaştırma (iki parmakla da ayarlanır)">${ZOOMS.map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}<option value="custom" hidden></option></select>
          ${tbBtn('rd-zin', 'zoomin', 'Yakınlaştır (⌘+)')}
        </div>
        ${tbSep()}
        ${tbBtn('rd-view', 'pages2', 'Görünüm: tek sayfa, iki sayfa, kaydırma')}
        ${tbBtn('rd-rotate', 'rotcw', 'Bu sayfayı sağa döndür')}
        ${tbBtn('rd-search-btn', 'search', 'Belgede ara (⌘F)')}
        <div class="tb-search" id="rd-searchbox" hidden>
          <input id="rd-q" placeholder="Belgede ara" autocomplete="off" spellcheck="false">
          <span class="muted small" id="rd-count"></span>
          ${tbBtn('rd-sprev', 'left', 'Önceki eşleşme (⇧↵)')}
          ${tbBtn('rd-snext', 'right', 'Sonraki eşleşme (↵)')}
          ${tbBtn('rd-sall', 'docs', 'Tüm açık belgelerde ara')}
          ${tbBtn('rd-rep-btn', 'textedit', 'Değiştir: bulunan metni başka bir metinle değiştirin')}
        </div>
        <div class="tb-search tb-replace" id="rd-repbox" hidden>
          <input id="rd-rep" placeholder="Yeni metin (boş bırakılırsa silinir)" autocomplete="off" spellcheck="false">
          <label class="tb-case" data-tip="Büyük/küçük harfe duyarlı"><input type="checkbox" id="rd-case" checked>Aa</label>
          <button class="btn sm primary" id="rd-rep-go">Tümünü değiştir</button>
        </div>
        ${tbSep()}
        ${tbBtn('rd-note', 'note', 'Not ekle: sayfada notun duracağı yere tıklayın')}
        ${tbBtn('rd-mark', 'bookmark', 'Bu sayfaya yer imi ekle')}
        ${tbBtn('rd-kvkk', 'shield', 'Kişisel verileri karart (KVKK)')}
        ${signedBadge(RD.info)}
        ${tbSep()}
        <button class="tb-text-btn" id="rd-tools" data-tip="Bu belgeye uygulanacak araçlar">${icon('tools')}<span class="tb-lbl">Araçlar</span>${icon('chevdown')}</button>
        <span class="tb-spacer"></span>
        ${NATIVE && RD.path ? tbBtn('rd-reveal', 'folder', "Finder'da göster") : ''}
        <button class="btn sm primary" id="rd-edit"></button>
        ${tbBtn('rd-close', 'close', 'Belgeyi kapat')}
      </div>
      <div class="edit-bar" id="ed-bar" hidden></div>
      ${RD.info.form && RD.formBar ? `<div class="rd-banner" id="rd-formbar">${icon('textedit')}
        <span>Bu belgede doldurulabilir form alanları var. Alanlara tıklayıp yazın (Tab ile sonrakine geçilir); Kaydet ile dosyaya işlenir.</span>
        <button class="btn sm" id="rd-form-clear">Formu temizle</button>${tbBtn('rd-form-x', 'close', 'Bu şeridi kapat')}</div>` : ''}
      ${RD.info.scanned && state.engines.ocr ? `<div class="rd-banner" id="rd-ocr">${icon('scan')}
        <span>Bu belge taranmış: yazıları otomatik tanınır, fareyle seçip kopyalayabilirsiniz. Belgede arama yapmak ve aranabilir
          hâlini kaydetmek için metni tanıtın.</span>
        <button class="btn sm primary" id="rd-ocr-go">Metni tanı</button></div>` : ''}
      <div class="rd-body">
        <div class="rd-side" id="rd-side" ${RD.side && !grid ? '' : 'hidden'}>
          <div class="seg rd-tabs">
            <button data-side="pages">Sayfalar</button><button data-side="marks">İçindekiler</button><button data-side="notes">Notlar</button>
          </div>
          <div class="rd-side-body" id="rd-side-body"></div>
        </div>
        <div class="rd-stage" ${grid ? 'hidden' : ''}>
          <div class="rd-scroll" id="rd-scroll" tabindex="-1"><div class="rd-pages" id="rd-pages"></div></div>
          <div class="pending-bar" id="pending" hidden><span id="pending-text"></span>
            <button class="btn ghost sm" id="pending-cancel">Vazgeç</button>
            <button class="btn primary sm" id="pending-apply">${icon('check')}Uygula</button></div>
        </div>
        <div class="thumbs grid" id="rd-grid" ${grid ? '' : 'hidden'}></div>
      </div>
      <div class="rd-status" id="rd-status"><span>Sayfa <b id="st-page"></b> / <span id="st-total"></span></span>
        <span class="st-sep"></span><span id="st-zoom"></span><span class="st-sep"></span><span id="st-size"></span></div></div>`;
    setTabTitle(RD.info.name, RD.path);

    $('#rd-side-btn').onclick = () => openSide(RD.side ? null : 'pages');
    $$('[data-side]').forEach(b => b.onclick = () => openSide(b.dataset.side));
    $('#rd-note').onclick = () => setNoteMode(!RD.noteMode);
    $('#rd-mark').onclick = addBookmark;
    // KVKK: önce bekleyen eklemeler belgeye işlenir, sonra kişisel veriler bulunup seçilenler karartılır
    $('#rd-kvkk').onclick = async () => {
      if (!RD.info || !await applyPending()) return;
      personalDataDialog({ sid: sid(), signed: RD.info.signed, onApply: body => annotOp(body, 'Karartılıyor…') });
    };
    $('#rd-save').onclick = () => save(false);
    $('#rd-saveas').onclick = () => save(true);
    $('#rd-history').onclick = () => versionsDialog({ info: RD.info, unsaved: RD.dirty || window.Editor.pendingCount() > 0,
      onRestored: () => openPath(RD.info.path) });
    $('#rd-undo').onclick = () => historyStep('undo');
    $('#rd-redo').onclick = () => historyStep('redo');
    $('#rd-rotate').onclick = () => annotOp({ op: 'rotate', pages: [RD.cur], angle: 90 }, 'Döndürülüyor…');
    $('#rd-search-btn').onclick = () => toggleSearch();
    $('#rd-tools').onclick = e => showToolsMenu(e.currentTarget);
    updateDocButtons();
    if ($('#rd-share')) $('#rd-share').onclick = () => share();
    if ($('#rd-copyfile')) $('#rd-copyfile').onclick = async () => { if (RD.info && await applyPending()) copyDocumentFile(sid()); };
    $('#rd-prev').onclick = () => step(-1);
    $('#rd-next').onclick = () => step(1);
    $('#rd-view').onclick = e => viewMenu(e.currentTarget);
    const pn = $('#rd-page');
    pn.onkeydown = e => { if (e.key === 'Enter') { goPage((parseInt(pn.value, 10) || 1) - 1); $('#rd-scroll').focus(); } };
    pn.onfocus = () => pn.select();
    pn.onblur = () => pn.value = RD.cur + 1;
    $('#rd-zoom').onchange = e => setZoom(e.target.value);
    $('#rd-zin').onclick = () => stepZoom(1);
    $('#rd-zout').onclick = () => stepZoom(-1);
    const q = $('#rd-q');
    q.onkeydown = e => {
      e.stopPropagation();
      if (e.key === 'Enter') { q.value.trim() === RD.search.q ? stepHit(e.shiftKey ? -1 : 1) : runSearch(q.value.trim()); }
      if (e.key === 'Escape') { q.value = ''; runSearch(''); toggleSearch(false); $('#rd-scroll').focus(); }
    };
    $('#rd-sprev').onclick = () => stepHit(-1);
    $('#rd-sall').onclick = () => searchAll(q.value.trim());
    $('#rd-snext').onclick = () => q.value.trim() === RD.search.q ? stepHit(1) : runSearch(q.value.trim());
    $('#rd-rep-btn').onclick = () => toggleReplace();
    const rq = $('#rd-rep');
    rq.onkeydown = e => {
      e.stopPropagation();
      if (e.key === 'Enter') replaceAll();
      if (e.key === 'Escape') toggleReplace(false);
    };
    $('#rd-rep-go').onclick = replaceAll;
    $('#rd-print').onclick = print;
    if ($('#rd-formbar')) {
      $('#rd-form-clear').onclick = clearForm;
      $('#rd-form-x').onclick = () => { RD.formBar = false; $('#rd-formbar').remove(); };
    }
    const ocrBtn = $('#rd-ocr-go');
    if (ocrBtn) ocrBtn.onclick = runOcr;
    $('#rd-edit').onclick = () => window.Editor.setEditing(!window.Editor.isEditing());
    $('#rd-close').onclick = closeDoc;
    const rv = $('#rd-reveal');
    if (rv) rv.onclick = () => native({ action: 'reveal', path: RD.path });

    buildPages();
    layoutRows();
    window.Editor.attach(editHost);
    renderEditButton();
    loadFields(true);
    setupSelectionTools();
    setupContextMenu();
    setupMarkClicks();
    openSide(RD.side);
    loadMarks();
    const scroller = $('#rd-scroll');
    let lastW = 0, lastH = 0;
    RD.ro?.disconnect();
    RD.ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (!width) return;   // sayfa düzeni açıkken sayfalar gizli
      if ((Math.round(width) !== lastW || (RD.zoom === 'page' && Math.round(height) !== lastH)) && typeof RD.zoom === 'string') {
        lastW = Math.round(width); lastH = Math.round(height);
        applyScale(true);
      }
    });
    RD.ro.observe(scroller);
    scroller.addEventListener('scroll', onScroll, { passive: true });
    // Kaydırma kapalı (sayfa sayfa): sayfanın sonuna gelince tekerlek / iki parmak bir sonraki sayfaya geçer
    let wheelSum = 0, wheelAt = 0;
    scroller.addEventListener('wheel', e => {
      if (RD.view.scroll || e.ctrlKey || e.metaKey) return;
      const atTop = scroller.scrollTop <= 0, atEnd = scroller.scrollTop + scroller.clientHeight >= scroller.scrollHeight - 2;
      if ((e.deltaY > 0 && !atEnd) || (e.deltaY < 0 && !atTop)) { wheelSum = 0; return; }
      wheelSum += e.deltaY;
      if (Math.abs(wheelSum) < 80 || Date.now() - wheelAt < 450) return;
      wheelAt = Date.now();
      step(Math.sign(wheelSum));
      wheelSum = 0;
    }, { passive: true });
    setupPinchZoom(scroller, { get: () => RD.scale, set: zoomTo });   // iki parmakla kıstırma
    applyScale(false);
    window.Editor.relayout();   // sayfalar boyutlandı: uygulanmamış eklemeler yerlerine
    goPage(RD.cur, false);
    scroller.focus({ preventScroll: true });
    if (RD.wantEdit) {   // Düzenleyici girişinden gelindi
      RD.wantEdit = false;
      if (!window.Editor.isEditing()) window.Editor.setEditing(true);
    }
  }

  // "Düzenle" düğmesi ve düzenleme araç satırı (editor.js)
  function renderEditButton() {
    const b = $('#rd-edit');
    if (!b) return;
    const on = window.Editor.isEditing();
    b.innerHTML = on ? `${icon('check')}<span class="tb-lbl">Bitti</span>` : `${icon('edit')}<span class="tb-lbl">Düzenle</span>`;
    b.dataset.tip = on ? 'Düzenlemeyi bitir: eklemeler belgeye işlenir, araç satırı kapanır'
      : 'Düzenle: metin ekleme ve değiştirme, imza, kaşe, karartma, sayfa düzeni';
    $('#ed-bar').hidden = !on;
  }

  // Sayfa düzeni (editor.js): sayfaların yerine tüm sayfaların küçük resimleri ızgarada
  function showGrid(on) {
    const grid = $('#rd-grid');
    if (!grid) return;
    grid.hidden = !on;
    $('.rd-stage').hidden = on;
    $('#rd-side').hidden = on || !RD.side;
    if (!on) applyScale(false);
  }

  // Düzenleme katmanının (editor.js) okuma ekranından kullandıkları
  const editHost = {
    info: () => RD.info,
    apply: info => applyDocInfo(info),
    scale: () => RD.scale,
    cur: () => RD.cur,
    setCur: i => setCurrent(i),
    goPage: (i, y = 0) => goPage(i, false, y),
    pagesBox: () => $('#rd-pages'),
    openReplace: () => toggleReplace(true),
    pageEl: i => $(`.rd-page[data-i="${i}"]`),
    scroller: () => $('#rd-scroll'),
    near: () => RD.near,
    thumbsBox: () => (RD.side === 'pages' ? $('#rd-side-body') : null),
    setGrid: showGrid,
    editingChanged: renderEditButton,
    refreshButtons: () => updateDocButtons(),
  };

  // Yazılmakta olan form alanı ve uygulanmamış eklemeler (düzenleme araçları) önce belgeye işlenir. Dönen: işlendi mi
  async function applyPending() {
    if (document.activeElement?.closest?.('.rd-form')) document.activeElement.blur();   // değeri işlensin
    try { await RD.fieldSaving; } catch { return false; }
    return window.Editor.flush().then(() => true, () => false);
  }

  function buildPages() {
    const box = $('#rd-pages');
    box.innerHTML = pages().map((p, i) => `<div class="rd-page" data-i="${i}">
        <img alt="" draggable="false"><div class="rd-hls"></div><div class="rd-text"></div><div class="rd-annots"></div><div class="rd-links"></div><div class="rd-form"></div>
        <div class="overlay"><svg class="pen-layer"></svg></div></div>`).join('');
    RD.near = new Set();
    RD.io?.disconnect();
    RD.io = new IntersectionObserver(entries => {
      for (const en of entries) {
        const i = +en.target.dataset.i;
        if (en.isIntersecting) { RD.near.add(i); loadPage(i); window.Editor.pageNear(i); } else RD.near.delete(i);
      }
    }, { root: $('#rd-scroll'), rootMargin: '1500px 0px' });
    $$('.rd-page', box).forEach(el => RD.io.observe(el));
  }

  function targetWidth(p) {
    return clamp(Math.ceil(p.w * RD.scale * (window.devicePixelRatio || 1) / 200) * 200, 400, 3000);
  }

  function loadPage(i) {
    const el = $(`.rd-page[data-i="${i}"]`);
    if (!el) return;
    const p = pages()[i];
    const want = targetWidth(p);
    const img = $('img', el);
    if (+img.dataset.w !== want) { img.src = pageUrl(i, want); img.dataset.w = want; }
    if (!el.dataset.text) { el.dataset.text = '1'; loadText(i, el); loadLinks(i, el); }
  }

  // Sayfadaki bağlantılar: içindekiler satırına tıklayınca ilgili yere gidilir, web adresleri tarayıcıda açılır
  async function loadLinks(i, el) {
    let links;
    try { links = (await api(`/api/edit/${sid()}/links/${i}`)).links; } catch { return; }
    const layer = $('.rd-links', el);
    if (layer) layer.replaceChildren(...links.map(l => pdfLinkEl(l, (page, to) => goPage(page, false, to))));
  }

  const measureCtx = document.createElement('canvas').getContext('2d');

  // Seçilebilir metin katmanı: her kelime ayrı, görünmez bir yazı; seçim ve vurgu kelime kelime yapılır.
  // Kelime sonraki kelimenin başına kadar uzatılır (boşluk dahil): satır boyunca seçim kesintisiz görünür.
  async function loadText(i, el) {
    let lines, scan;
    try { ({ lines, scan } = await api(`/api/edit/${sid()}/words/${i}`)); } catch { el.dataset.text = ''; return; }
    if (scan && state.engines.ocr) {   // taranmış sayfa: yazısı tanınır, seçilip kopyalanabilir (belge değişmez)
      el.classList.add('ocr-busy');
      try { lines = (await api(`/api/edit/${sid()}/words/${i}?ocr=1`)).lines; } catch { /* tanınamadı: sayfanın kendi metni kalır */ }
      finally { el.classList.remove('ocr-busy'); }
    }
    const p = pages()[i];
    const layer = $('.rd-text', el);
    if (!layer) return;
    const frag = document.createDocumentFragment();
    const ends = paragraphEnds(lines, p);
    for (const [n, l] of lines.entries()) {
      const fs = l.h * p.h * 0.86;
      const family = l.serif ? '"Times New Roman", Times, serif' : 'Arial, Helvetica, sans-serif';
      measureCtx.font = `${fs}px ${family}`;
      l.words.forEach(([x, w, text], k) => {
        const span = document.createElement('span');
        span.textContent = k < l.words.length - 1 ? text + ' ' : text;   // kopyalanan metinde kelimeler arası boşluk
        const natural = measureCtx.measureText(span.textContent).width || 1;
        Object.assign(span.style, {
          left: x * p.w + 'pt', top: l.y * p.h + 'pt', fontSize: fs + 'pt', fontFamily: family,
          transform: `scaleX(${(w * p.w) / natural})`,
        });
        frag.append(span);
      });
      const br = document.createElement('br');
      if (ends[n]) br.dataset.p = '1';   // paragraf sonu: kopyalanan metinde satır sonu kalır
      frag.append(br);
    }
    const guard = document.createElement('div');   // seçim zemini (bkz. setupSelectionGuard)
    guard.className = 'rd-eoc';
    frag.append(guard);
    layer.replaceChildren(frag);
  }

  // ---------------------------------------------------------------- temiz kopyalama
  // PDF'te her satır ayrı biter; kopyalanan metinde paragrafın satırları birleşir, satır sonu tireleri kalkar
  // ("hâ- / kim" → "hâkim"), paragraflar ayrı satırda kalır: UYAP Doküman Editörü'ne ve Word'e düzgün yapışır.
  // Bir satır sonu paragraf sonudur: sonraki satırın ilk kelimesi bu satıra sığacakken satır bitmişse, satırlar
  // arasında paragraf aralığı varsa, sonraki satır girintiliyse ya da madde işaretiyle başlıyorsa, satır ":" ile
  // bitiyorsa.
  const LIST_START = /^(\d{1,3}[.)-]|[a-zçğıöşü][.)]|[-–•·▪*]|\(\d{1,3}\)|[IVXLC]{1,5}[.-])$/iu;

  function paragraphEnds(lines, p) {
    const right = l => { const w = l.words[l.words.length - 1]; return (w[0] + w[3]) * p.w; };
    const rights = lines.map(right).sort((a, b) => a - b);
    const margin = rights[Math.floor((rights.length - 1) * 0.9)] || 0;   // metnin sağ kenarı (çoğu satırın bittiği yer)
    return lines.map((l, k) => {
      const n = lines[k + 1], h = l.h * p.h, space = h * 0.3;
      if (/:$/.test(l.words[l.words.length - 1][2])) return true;
      if (!n) return right(l) + space * 4 < margin;   // sayfanın son satırı: kısaysa paragraf biter
      const first = n.words[0];
      if (n.y < l.y || (n.y - l.y - l.h) * p.h > h * 0.7) return true;   // sütun değişti ya da paragraf aralığı
      const hanging = LIST_START.test(l.words[0][2]) && l.words[1] && Math.abs(first[0] - l.words[1][0]) * p.w < space * 2;
      if (!hanging && (first[0] - l.words[0][0]) * p.w > space * 2) return true;   // sonraki satır girintili
      if (LIST_START.test(first[2])) return true;
      return right(l) + space + first[3] * p.w < margin - space;   // sonraki satırın ilk kelimesi bu satıra sığardı
    });
  }

  function cleanText(range) {
    const box = $('#rd-pages');
    if (!box?.contains(range.commonAncestorContainer)) return null;
    let out = '', join = '';   // satır sonu tiresi: 'drop' (hece tiresi, kalkar) ya da 'keep' (e-posta, Türk-Alman)
    const part = (node, c, o) => (c.nodeType === Node.TEXT_NODE ? o : o ? node.textContent.length : 0);
    for (const node of box.querySelectorAll('.rd-text span, .rd-text br')) {
      if (!range.intersectsNode(node)) continue;
      if (node.tagName === 'BR') {
        out = out.replace(/[ \t]+$/, '');
        if (node.dataset.p) { if (out && !out.endsWith('\n')) out += '\n'; join = ''; }
        else if (/\p{L}[-\u00ad]$/u.test(out)) {   // satır sonu tiresi (bazı yazı tiplerinde yumuşak tire): boşluksuz birleşir
          out = out.slice(0, -1) + '-';
          join = /\p{L}\p{Ll}-$/u.test(out) ? 'drop' : 'keep';
        }
        else if (out && !out.endsWith('\n')) out += ' ';
        continue;
      }
      let t = node.textContent;
      const s = node.contains(range.startContainer) ? part(node, range.startContainer, range.startOffset) : 0;
      const e = node.contains(range.endContainer) ? part(node, range.endContainer, range.endOffset) : t.length;
      t = t.slice(s, e);
      if (!t) continue;
      if (join === 'drop' && /^\p{Ll}/u.test(t)) out = out.slice(0, -1);   // "hâ-" + "kim" → "hâkim"
      join = '';
      out += t;
    }
    return out.replace(/ {2,}/g, ' ').replace(/ +\n/g, '\n').trim();
  }

  function onCopy(e) {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return;
    const text = cleanText(sel.getRangeAt(0));
    if (!text) return;
    e.clipboardData.setData('text/plain', text);
    e.preventDefault();
  }

  // ---------------------------------------------------------------- yakınlaştırma
  function fitScale() {
    const sc = $('#rd-scroll');
    const availW = sc.clientWidth - 48, availH = sc.clientHeight - 32;
    // Satırın genişliği (iki sayfalı görünümde iki sayfa ve aradaki boşluk) ekrana sığsın
    const fitW = row => (availW - ROW_GAP * (row.length - 1)) / row.reduce((w, i) => w + pages()[i].w, 0);
    if (RD.zoom === 'width') return clamp(Math.min(...RD.rows.map(fitW)), 0.2, 2.2);
    const row = RD.rows.find(r => r.includes(RD.cur)) || [RD.cur];
    return clamp(Math.min(fitW(row), availH / Math.max(...row.map(i => pages()[i].h))), 0.1, 4);
  }

  function setZoom(z) {
    RD.zoom = (z === 'width' || z === 'page') ? z : clamp(+z, 10, 500) / 100 * PX_PER_PT;
    applyScale(true);
  }

  // İki parmakla yakınlaştırma: parmakların altındaki nokta yerinde kalır; netlik hareket bitince artar
  function zoomTo(scale, pt) {
    const scroller = $('#rd-scroll');
    const a = zoomAnchor(scroller, $$('.rd-page'), pt);
    RD.zoom = clamp(scale, 0.1 * PX_PER_PT, 5 * PX_PER_PT);
    RD.pinching = true;
    applyScale(false);
    restoreZoomAnchor(scroller, a);
    clearTimeout(RD.pinchTimer);
    RD.pinchTimer = setTimeout(() => { RD.pinching = false; RD.near.forEach(loadPage); window.Editor.relayout(); }, 180);
  }

  function stepZoom(dir) {
    const steps = [25, 33, 50, 67, 75, 90, 100, 110, 125, 150, 175, 200, 250, 300, 400];
    const pct = RD.scale / PX_PER_PT * 100;
    const next = dir > 0 ? steps.find(s => s > pct + 1) : [...steps].reverse().find(s => s < pct - 1);
    if (next) setZoom(next);
  }

  function applyScale(keepPosition) {
    const scroller = $('#rd-scroll');
    if (!scroller) return;
    // Yakınlaştırırken okunan yeri koru
    let anchor = null;
    if (keepPosition && RD.tops.length) {
      const i = RD.cur, top = RD.tops[i], h = pages()[i].h * RD.scale;
      anchor = { i, frac: (scroller.scrollTop - top) / h };
    }
    const before = RD.scale;
    RD.scale = typeof RD.zoom === 'number' ? RD.zoom : fitScale();
    const sel = $('#rd-zoom');
    const pct = Math.round(RD.scale / PX_PER_PT * 100);
    if (typeof RD.zoom === 'string') sel.value = RD.zoom;
    else {
      const match = ZOOMS.find(([v]) => +v === pct);
      if (match) sel.value = match[0];
      else { const c = sel.querySelector('option[value=custom]'); c.textContent = '%' + pct; sel.value = 'custom'; }
    }
    $$('.rd-page').forEach(el => {
      const p = pages()[+el.dataset.i];
      el.style.width = Math.round(p.w * RD.scale) + 'px';
      el.style.height = Math.round(p.h * RD.scale) + 'px';
      for (const layer of $$('.rd-text, .rd-form', el)) {   // pt ölçüsünde çizilir, sayfayla birlikte ölçeklenir
        layer.style.width = p.w + 'pt';
        layer.style.height = p.h + 'pt';
        layer.style.transform = `scale(${RD.scale / PX_PER_PT})`;
      }
    });
    measureTops();
    if (!RD.pinching) {
      RD.near.forEach(loadPage);
      if (RD.scale !== before) window.Editor.relayout();   // eklemeler yeni ölçekte
    }
    if (anchor) scroller.scrollTop = RD.tops[anchor.i] + anchor.frac * pages()[anchor.i].h * RD.scale;
    updateStatus();
  }

  function measureTops() {
    RD.tops = $$('.rd-page').map(el => el.offsetTop);
  }

  // ---------------------------------------------------------------- gezinme
  // y: sayfadaki hedef konum (0 = üst, 1 = alt) — içindekilerdeki başlığın tam yeri
  function goPage(i, smooth = false, y = 0) {
    if (!RD.info) return;
    i = clamp(i, 0, pages().length - 1);
    const scroller = $('#rd-scroll');
    const top = pageTop(i);
    const into = y > 0.03 ? y * pages()[i].h * RD.scale - 24 : 0;
    scroller.scrollTo({ top: top + into - 12, behavior: smooth && RD.view.scroll ? 'smooth' : 'auto' });
    setCurrent(i);
  }

  // Sayfanın kaydırma kutusundaki yeri; kaydırma kapalıyken önce o sayfanın satırı gösterilir
  function pageTop(i) {
    if (!RD.view.scroll) { RD.cur = i; showRow(); }
    return $(`.rd-page[data-i="${i}"]`)?.offsetTop ?? 0;
  }

  // Önceki / sonraki: iki sayfalı görünümde bir çift, yoksa bir sayfa
  function step(dir) {
    if (!RD.info) return;
    const r = RD.rows.findIndex(row => row.includes(RD.cur));
    goPage(RD.rows[clamp(r + dir, 0, RD.rows.length - 1)][0]);
  }

  function onScroll() {
    const scroller = $('#rd-scroll');
    if (!scroller || !RD.view.scroll) return;   // sayfa sayfa görünümde o anki sayfayı gezinme belirler
    const y = scroller.scrollTop + scroller.clientHeight * 0.35;
    let lo = 0, hi = RD.tops.length - 1;
    while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (RD.tops[mid] <= y) lo = mid; else hi = mid - 1; }
    while (lo > 0 && RD.tops[lo - 1] === RD.tops[lo]) lo--;   // iki sayfalı satırda soldaki sayfa
    if (lo !== RD.cur) setCurrent(lo);
  }

  // ---------------------------------------------------------------- görünüm: tek / iki sayfa, kaydırma
  // spread: sayfalar ikişer yan yana (cover: ilk sayfa kitap kapağı gibi tek başına); scroll kapalıysa yalnız o anki
  // sayfa (ya da çift) görünür, sayfa sayfa geçilir. Seçim bu bilgisayarda hatırlanır.
  function rowsOf(n) {
    const out = [];
    let i = 0;
    if (RD.view.spread && RD.view.cover && n) out.push([i++]);
    for (; i < n; i += RD.view.spread ? 2 : 1) out.push(RD.view.spread && i + 1 < n ? [i, i + 1] : [i]);
    return out;
  }

  // Sayfalar satırlara dizilir; sayfa öğeleri yerinden taşınır (yüklü resimleri, metin ve düzenleme katmanları kalır)
  function layoutRows() {
    const box = $('#rd-pages');
    if (!box || !RD.info) return;
    const els = new Map($$('.rd-page', box).map(el => [+el.dataset.i, el]));
    RD.rows = rowsOf(pages().length);
    box.replaceChildren(...RD.rows.map(row => {
      const div = document.createElement('div');
      div.className = 'rd-row';
      div.append(...row.map(i => els.get(i)));
      return div;
    }));
    box.classList.toggle('paged', !RD.view.scroll);
    showRow();
  }

  function showRow() {
    const cur = RD.rows.findIndex(row => row.includes(RD.cur));
    $$('#rd-pages > .rd-row').forEach((div, k) => { div.hidden = !RD.view.scroll && k !== cur; });
  }

  // Görünüm menüsünden ya da Ayarlar penceresinden: kaydedilir, açık belge hemen yeniden dizilir
  function setView(change) {
    Object.assign(RD.view, change);
    try { localStorage.setItem(VIEW_KEY, JSON.stringify(RD.view)); } catch { }
    if (!RD.info || !$('#rd-pages')) return;
    const keep = RD.cur;
    layoutRows();
    applyScale(false);
    goPage(keep);
    window.Editor.relayout();
  }

  function viewMenu(anchor) {
    const v = RD.view, r = anchor.getBoundingClientRect(), set = setView;
    contextMenu(r.left, r.bottom + 4, [
      { label: 'Tek sayfa', icon: v.spread ? null : 'check', run: () => set({ spread: false }) },
      { label: 'İki sayfa', icon: v.spread ? 'check' : null, run: () => set({ spread: true }) },
      'sep',
      { label: 'Kaydırmayı etkinleştir', icon: v.scroll ? 'check' : null, run: () => set({ scroll: !v.scroll }) },
      'sep',
      { label: 'İki sayfalı görünümde kapak sayfasını ayrı göster', icon: v.cover ? 'check' : null, disabled: !v.spread,
        run: () => set({ cover: !v.cover }) },
    ]);
  }

  // Durum çubuğu (en altta): o anki sayfa (iki sayfalı görünümde çift) / sayfa sayısı · yakınlık · dosya boyutu
  function updateStatus() {
    if (!RD.info || !$('#rd-status')) return;
    const row = RD.rows.find(r => r.includes(RD.cur)) || [RD.cur];
    $('#st-page').textContent = row.length > 1 ? `${row[0] + 1}–${row[row.length - 1] + 1}` : RD.cur + 1;
    $('#st-total').textContent = pages().length;
    $('#st-zoom').textContent = '%' + Math.round(RD.scale / PX_PER_PT * 100);
    $('#st-size').textContent = RD.info.size ? fmtSize(RD.info.size) : '';
  }

  function setCurrent(i) {
    RD.cur = i;
    updateStatus();
    const pn = $('#rd-page');
    if (pn && document.activeElement !== pn) pn.value = i + 1;
    $$('#rd-side-body .thumb').forEach(t => t.classList.toggle('current', +t.dataset.i === i));
    $(`#rd-side-body .thumb[data-i="${i}"]`)?.scrollIntoView({ block: 'nearest' });
    clearTimeout(RD.saveTimer);
    RD.saveTimer = setTimeout(() => RD.info && store.set(lastPageKey(), RD.cur), 400);
  }

  // ---------------------------------------------------------------- yan panel
  function openSide(which) {
    RD.side = which;
    const side = $('#rd-side');
    if (!side) return;
    side.hidden = !which || window.Editor.isGrid();
    $('#rd-side-btn').classList.toggle('on', !!which);
    $$('[data-side]').forEach(b => b.classList.toggle('on', b.dataset.side === which));
    if (which === 'pages') window.Editor.renderThumbs();
    else if (which === 'marks') buildMarksList();
    else if (which === 'notes') buildNotesList();
  }

  // ---------------------------------------------------------------- arama
  async function runSearch(q) {
    RD.search = { q, flat: [], idx: -1 };
    $$('.rd-hls').forEach(h => h.innerHTML = '');
    $('#rd-count').textContent = '';
    if (!q) return;
    let hits;
    try { hits = (await api(`/api/edit/${sid()}/search?q=${encodeURIComponent(q)}`)).hits; }
    catch (e) { return toast(e.message, 'error'); }
    if (RD.search.q !== q) return;
    for (const h of hits) {
      const layer = $(`.rd-page[data-i="${h.page}"] .rd-hls`);
      h.rects.forEach(([x, y, w, hh]) => {
        const box = document.createElement('div');
        box.className = 'rd-hl';
        Object.assign(box.style, { left: x * 100 + '%', top: y * 100 + '%', width: w * 100 + '%', height: hh * 100 + '%' });
        layer.append(box);
        RD.search.flat.push({ page: h.page, y, el: box });
      });
    }
    if (!RD.search.flat.length) { $('#rd-count').textContent = 'Bulunamadı'; return; }
    // Okunan sayfadan sonraki ilk eşleşmeden başla
    const start = RD.search.flat.findIndex(f => f.page >= RD.cur);
    showHit(start < 0 ? 0 : start);
  }

  // ---------------------------------------------------------------- tüm açık belgelerde arama
  // Sonuçlar belgelere göre listelenir; başka bir belgeye tıklanınca o sekmeye geçilir ve arama orada açılır
  // (istek sekmeler arasında localStorage ile iletilir: 'storage' olayı, yeni açılan sekmede setDoc).
  async function searchAll(q) {
    $$('.rd-allpanel').forEach(p => p.remove());
    if (!q) { toggleSearch(true); return toast('Önce aranacak kelimeyi yazın.'); }
    const params = new URLSearchParams({ q, current: sid() });
    (openTabPaths() || []).forEach(p => params.append('path', p));
    let docs;
    try { docs = (await withBusy('Açık belgelerde aranıyor…', () => api(`/api/search-all?${params}`))).docs; } catch { return; }
    const total = docs.reduce((n, d) => n + d.count, 0);
    const panel = document.createElement('div');
    panel.className = 'rd-allpanel';
    panel.innerHTML = `<div class="rd-allhead"><b>“${esc(q)}”</b><span class="muted small">${docs.length
        ? `${docs.length} belgede ${total} sonuç` : 'Açık belgelerde bulunamadı'}</span></div>
      ${docs.map((d, k) => `<div class="rd-alldoc">
        <div class="rd-alltitle"><b>${esc(d.name)}</b>${d.current ? '<span class="muted small">bu belge</span>' : ''}
          <span class="count">${d.count}</span></div>
        ${d.pages.map(p => `<button class="rd-allhit" data-k="${k}" data-page="${p.page}"><span class="muted small">s. ${p.page + 1}</span>
          <span>${markQuery(p.snippet, q)}</span></button>`).join('')}</div>`).join('')}`;
    const at = $('#rd-searchbox').getBoundingClientRect();
    Object.assign(panel.style, { top: at.bottom + 6 + 'px', left: Math.max(16, Math.min(at.left, innerWidth - 476)) + 'px' });
    document.body.append(panel);
    const close = e => { if (!panel.contains(e.target) && e.target.id !== 'rd-sall') { panel.remove(); document.removeEventListener('mousedown', close); } };
    setTimeout(() => document.addEventListener('mousedown', close));
    $$('.rd-allhit', panel).forEach(b => b.onclick = () => {
      const d = docs[+b.dataset.k], jump = { path: d.path, q, page: +b.dataset.page, t: Date.now() };
      panel.remove();
      if (d.current) return applyJump(jump);
      try { localStorage.setItem('pdfstudyo.jump', JSON.stringify(jump)); } catch { }
      if (NATIVE) native({ action: 'openPaths', paths: [d.path] });   // o belgenin sekmesine geç (yoksa açılır)
      else openPath(d.path);
    });
  }

  const markQuery = (text, q) => {
    const k = text.toLocaleLowerCase('tr-TR').indexOf(q.toLocaleLowerCase('tr-TR'));
    return k < 0 ? esc(text) : esc(text.slice(0, k)) + `<mark>${esc(text.slice(k, k + q.length))}</mark>` + esc(text.slice(k + q.length));
  };

  // Başka sekmeden gelen "bu belgede şunu ara, şu sayfaya git" isteği
  async function applyJump(jump) {
    if (!jump || !RD.info || (jump.path && jump.path !== RD.path)) return;
    try { if (localStorage.getItem('pdfstudyo.jump')) localStorage.removeItem('pdfstudyo.jump'); } catch { }
    toggleSearch(true);
    $('#rd-q').value = jump.q;
    await runSearch(jump.q);
    const k = RD.search.flat.findIndex(f => f.page >= jump.page);
    if (k >= 0) showHit(k);
  }

  function pendingJump() {
    try {
      const jump = JSON.parse(localStorage.getItem('pdfstudyo.jump') || 'null');
      return jump && Date.now() - jump.t < 20000 ? jump : null;
    } catch { return null; }
  }

  window.addEventListener('storage', e => {
    if (e.key === 'pdfstudyo.jump' && e.newValue) { try { applyJump(JSON.parse(e.newValue)); } catch { } }
  });

  function stepHit(dir) {
    const n = RD.search.flat.length;
    if (!n) return;
    showHit((RD.search.idx + dir + n) % n);
  }

  function showHit(k) {
    const s = RD.search;
    s.flat[s.idx]?.el.classList.remove('cur');
    s.idx = k;
    const hit = s.flat[k];
    hit.el.classList.add('cur');
    $('#rd-count').textContent = `${k + 1}/${s.flat.length}`;
    const scroller = $('#rd-scroll');
    const y = pageTop(hit.page) + hit.y * pages()[hit.page].h * RD.scale;
    scroller.scrollTo({ top: y - scroller.clientHeight / 3 });
    setCurrent(hit.page);
  }

  // ---------------------------------------------------------------- form doldurma
  // Doldurulabilir alanların üstüne giriş kutuları konur; değer alandan çıkınca (onay kutusu ve listede hemen)
  // belgeye işlenir. rebuild: kutular baştan kurulsun (belge yeniden çizildi); yoksa yalnızca değerler güncellenir.
  async function loadFields(rebuild = false) {
    if (!RD.info?.form) { RD.fields = []; return; }
    const id = sid();
    let fields;
    try { fields = (await api(`/api/edit/${id}/fields`)).fields; } catch { return; }
    if (!RD.info || sid() !== id) return;
    const same = !rebuild && fields.length === RD.fields.length && fields.every((f, k) => f.xref === RD.fields[k].xref);
    RD.fields = fields;
    same ? updateFieldValues() : renderFields();
  }

  function renderFields() {
    $$('.rd-form').forEach(l => l.replaceChildren());
    RD.fields.forEach((f, k) => {
      const layer = $(`.rd-page[data-i="${f.page}"] .rd-form`);
      if (!layer) return;
      const p = pages()[f.page];
      let el;
      if (f.type === 'text') {
        el = document.createElement(f.multiline ? 'textarea' : 'input');
        if (f.maxlen) el.maxLength = f.maxlen;
        el.spellcheck = false;
      } else if (f.type === 'choice') {
        el = document.createElement('select');
        el.innerHTML = f.options.map(([v, label]) => `<option value="${esc(v)}">${esc(label)}</option>`).join('');
      } else {
        el = document.createElement('input');
        el.type = f.type === 'radio' ? 'radio' : 'checkbox';
        if (f.type === 'radio') el.name = `rf-${f.name}`;
      }
      el.className = `ff ff-${f.type}`;
      el.dataset.k = k;
      el.disabled = f.readonly;
      el.title = f.label || f.name;
      // Yazı boyutu "otomatik" ise belgeye işlenirken verilen boyut (bkz. editor.op_fill_form)
      const size = f.size || (f.multiline ? 10 : Math.round(Math.min(12, Math.max(6, f.h * p.h * 0.6)) * 10) / 10);
      Object.assign(el.style, { left: f.x * 100 + '%', top: f.y * 100 + '%', width: f.w * 100 + '%', height: f.h * 100 + '%',
        fontSize: size + 'pt' });
      el.onchange = () => fillField(RD.fields[+el.dataset.k], el);
      layer.append(el);
    });
    updateFieldValues();
  }

  function updateFieldValues() {
    for (const el of $$('.rd-form .ff')) {
      const f = RD.fields[+el.dataset.k];
      if (!f || el === document.activeElement) continue;   // yazılmakta olana dokunma
      if (f.type === 'check' || f.type === 'radio') el.checked = f.checked;
      else el.value = f.value;
    }
  }

  // Yazılmakta olan form alanı: değeri alandan çıkınca belgeye işlenir; o ana kadar kapatırken sorulsun
  function fieldTyping() {
    const el = document.activeElement;
    const f = el?.closest?.('.rd-form') && RD.fields[+el.dataset.k];
    return !!f && (f.type === 'check' || f.type === 'radio' ? el.checked !== f.checked : el.value !== f.value);
  }

  function fillField(f, el) {
    const value = f.type === 'check' || f.type === 'radio' ? el.checked : el.value;
    const fields = [{ page: f.page, xref: f.xref, value }];
    if (f.type === 'radio' && !value) return;
    RD.fieldSaving = (RD.fieldSaving || Promise.resolve()).catch(() => { }).then(async () => {
      let info;
      try { info = await postJSON(`/api/edit/${sid()}/op`, { op: 'fill_form', fields }); }
      catch { updateFieldValues(); throw new Error('Form alanı kaydedilemedi'); }
      await applyDocInfo(info);
    });
  }

  async function clearForm() {
    const fields = RD.fields.filter(f => !f.readonly && (f.type === 'check' || f.type === 'radio' ? f.checked : f.value))
      .map(f => ({ page: f.page, xref: f.xref, value: f.type === 'check' || f.type === 'radio' ? false : '' }));
    if (!fields.length) return toast('Form zaten boş.');
    if (!confirm(`${fields.length} alanın değeri silinsin mi? (Geri Al ile geri alınabilir)`)) return;
    await annotOp({ op: 'fill_form', fields }, 'Form temizleniyor…');
  }

  // ---------------------------------------------------------------- notlar, vurgular, yer imleri
  const HL_COLORS = ['#ffe14d', '#8ef0a0', '#8fd3ff', '#ffa3d1'];
  const LINE_COLOR = '#d6453d';   // altını / üstünü çizme rengi
  const LINE_COLORS = [LINE_COLOR, '#1d4ed8', '#1f8a4c', '#111111'];
  const MARK_KIND = { Highlight: 'highlight', Underline: 'underline', StrikeOut: 'strikeout' };

  async function annotOp(body, text = 'Kaydediliyor…') {
    if (!await applyPending()) return false;
    let info;
    try { info = await withBusy(text, () => postJSON(`/api/edit/${sid()}/op`, body)); } catch { return false; }
    await applyDocInfo(info);
    return true;
  }

  async function historyStep(dir) {
    if (!RD.info) return;
    if (dir === 'undo' && window.Editor.undoPending()) return;   // önce uygulanmamış son ekleme
    if (!RD.info[dir === 'undo' ? 'canUndo' : 'canRedo']) return;
    let info;
    try { info = await withBusy(dir === 'undo' ? 'Geri alınıyor…' : 'Yineleniyor…', () => postJSON(`/api/edit/${sid()}/${dir}`)); } catch { return; }
    await applyDocInfo(info);
  }

  // Belgenin yeni hâli: sayfa boyutları değiştiyse (döndürme, sayfa ekleme) yeniden çiz, yoksa yalnızca değişen sayfaları yenile
  async function applyDocInfo(info) {
    const before = pages();
    RD.info = info;
    RD.dirty = !!info.unsaved;
    const sameLayout = before.length === info.pages.length && before.every((p, i) => p.w === info.pages[i].w && p.h === info.pages[i].h);
    if (!sameLayout) {
      RD.cur = Math.min(RD.cur, info.pages.length - 1);
      renderShell();
      goPage(RD.cur);
      window.Editor.docChanged();
      await loadMarks();
      return;
    }
    pages().forEach((p, i) => {
      if (p.k !== before[i].k) {
        const el = $(`.rd-page[data-i="${i}"]`);
        if (el) { $('img', el).dataset.w = ''; el.dataset.text = ''; if (RD.near.has(i)) loadPage(i); }
      }
    });
    setDirty(RD.dirty);
    const badge = $('.sig-badge');
    if (badge) badge.hidden = !info.signed;
    updateStatus();   // dosya boyutu değişmiş olabilir
    window.Editor.docChanged();   // küçük resimler, düzenlenebilir satırlar
    loadFields();
    await loadMarks();
  }

  function setDirty(on) {
    RD.dirty = on;
    updateDocButtons();
  }

  function updateDocButtons() {
    const set = (id, off) => { const b = $(id); if (b) b.disabled = off; };
    const pending = window.Editor.pendingCount() > 0;
    set('#rd-save', !RD.dirty && !pending);
    set('#rd-undo', !RD.info?.canUndo && !pending);
    set('#rd-redo', !RD.info?.canRedo);
  }

  function toggleSearch(show) {
    const box = $('#rd-searchbox');
    if (!box) return;
    show = show ?? box.hidden;
    box.hidden = !show;
    $('#rd-search-btn').classList.toggle('on', show);
    if (show) { const q = $('#rd-q'); q.focus(); q.select(); } else toggleReplace(false);
  }

  // Bul ve değiştir: arama kutusunun yanında yeni metin kutusu açılır
  function toggleReplace(show) {
    const box = $('#rd-repbox');
    if (!box) return;
    show = show ?? box.hidden;
    if (show) toggleSearch(true);
    box.hidden = !show;
    $('#rd-rep-btn').classList.toggle('on', show);
    if (show) $($('#rd-q').value.trim() ? '#rd-rep' : '#rd-q').focus();
  }

  // Aranan metin tüm sayfalarda yeni metinle değiştirilir: yazı tipi (en yakın sistem fontu), boyut ve renk korunur
  async function replaceAll() {
    const find = $('#rd-q').value;
    if (!find.trim()) { toast('Önce aranacak metni yazın.', 'error'); return $('#rd-q').focus(); }
    if (!await applyPending()) return;
    let info;
    try {
      info = await withBusy('Değiştiriliyor…', () => postJSON(`/api/edit/${sid()}/op`,
        { op: 'replace_all', find, replace: $('#rd-rep').value, match_case: $('#rd-case').checked }));
    } catch { return; }
    if (!info.count) return toast('Metin bulunamadı. Büyük/küçük harf farkı varsa "Aa" seçimini kaldırıp deneyin.', 'error');
    await applyDocInfo(info);
    toast(`${info.count} yerde değiştirildi.`, 'ok');
    runSearch(find.trim());   // kalan eşleşmeler (varsa) görünsün
  }

  async function loadMarks() {
    if (!RD.info) return;
    try { RD.marks = await api(`/api/edit/${sid()}/annotations`); } catch { return; }
    // Belgenin içindekiler listesi varsa, açılışta yan panelde göster (kapatılırsa bu belgede yeniden açılmaz)
    if (RD.marks.outline.length && RD.autoTocFor !== RD.info.id) {
      RD.autoTocFor = RD.info.id;
      if (!RD.side) openSide('marks');
    }
    renderAnnotMarkers();
    if (RD.side === 'marks') buildMarksList();
    if (RD.side === 'notes') buildNotesList();
  }

  // Yapışkan notların sayfa üzerindeki tıklanabilir işaretleri (vurgular sayfa görüntüsünde zaten çizili)
  function renderAnnotMarkers() {
    $$('.rd-annots').forEach(l => l.innerHTML = '');
    for (const a of RD.marks.annots) {
      if (a.type !== 'Text') continue;
      const layer = $(`.rd-page[data-i="${a.page}"] .rd-annots`);
      if (!layer) continue;
      const m = document.createElement('button');
      m.className = 'rd-note-marker';
      m.title = a.content || 'Not';
      Object.assign(m.style, { left: a.x * 100 + '%', top: a.y * 100 + '%', width: Math.max(a.w * 100, 2) + '%', height: Math.max(a.h * 100, 1.5) + '%' });
      m.onclick = e => { e.stopPropagation(); notePopover(a, m); };
      layer.append(m);
    }
  }

  function notePopover(a, anchor) {
    $$('.rd-pop').forEach(p => p.remove());
    const pop = document.createElement('div');
    pop.className = 'rd-pop';
    pop.innerHTML = `<div class="rd-pop-text">${esc(a.content || '(boş not)')}</div>
      ${a.author ? `<div class="muted small rd-pop-author">${esc(a.author)}</div>` : ''}
      <div class="rd-pop-actions"><button class="btn sm ghost" data-edit>${icon('edit')}Düzenle</button>
      <button class="btn sm ghost" data-del>${icon('trash')}Sil</button></div>`;
    const r = anchor.getBoundingClientRect();
    Object.assign(pop.style, { left: Math.min(r.left, innerWidth - 300) + 'px', top: r.bottom + 6 + 'px' });
    document.body.append(pop);
    const close = e => { if (!pop.contains(e.target)) { pop.remove(); document.removeEventListener('mousedown', close); } };
    setTimeout(() => document.addEventListener('mousedown', close));
    $('[data-edit]', pop).onclick = async () => { pop.remove(); await editAnnot(a); };
    $('[data-del]', pop).onclick = async () => { pop.remove(); await deleteAnnot(a); };
  }

  async function editAnnot(a) {
    const text = await askText(a.type === 'Text' ? 'Notu düzenle' : 'İşarete not', a.content || '');
    if (text != null) annotOp({ op: 'annot_edit', page: a.page, xref: a.xref, text });
  }

  async function deleteAnnot(a) {
    if (!confirm(a.type === 'Text' ? 'Bu not silinsin mi?' : a.type === 'Highlight' ? 'Bu vurgu silinsin mi?' : 'Bu işaret silinsin mi?')) return;
    annotOp({ op: 'annot_delete', page: a.page, xref: a.xref }, 'Siliniyor…');
  }

  function askText(title, value = '', placeholder = '') {
    return new Promise(resolve => {
      let done = false;
      const m = modal({
        title,
        body: `<textarea class="input" id="rd-ask" rows="5" style="height:auto;padding:8px;resize:vertical" placeholder="${esc(placeholder)}">${esc(value)}</textarea>`,
        foot: `<button class="btn" data-x>Vazgeç</button><button class="btn primary" id="rd-ask-ok">Kaydet</button>`,
      });
      const finish = v => { if (done) return; done = true; m.close(); resolve(v); };
      const ta = $('#rd-ask', m.el);
      ta.focus(); ta.select();
      ta.onkeydown = e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) finish(ta.value); };
      $('#rd-ask-ok', m.el).onclick = () => finish(ta.value);
      $('[data-x]', m.el).onclick = () => finish(null);
      new MutationObserver((_, obs) => { if (!m.el.isConnected) { obs.disconnect(); finish(null); } })
        .observe($('#modal-root'), { childList: true });
    });
  }

  // Not koyma modu: sayfada tıklanan yere yapışkan not
  function setNoteMode(on) {
    if (on && window.Editor.isEditing()) window.Editor.useTool('select');   // tıklama notu koysun, araç değil
    RD.noteMode = on;
    $('.reader')?.classList.toggle('note-mode', on);
    $('#rd-note')?.classList.toggle('on', on);
    if (on) toast('Notun duracağı yere tıklayın. Vazgeçmek için Esc.');
  }

  async function placeNote(e) {
    if (!RD.noteMode) return;
    const pageEl = e.target.closest('.rd-page');
    if (!pageEl) return;
    e.preventDefault();
    setNoteMode(false);
    addNoteAt(pointOnPage(pageEl, e));
  }

  // Tıklanan nokta: {page, x, y} (sayfaya göre 0–1)
  function pointOnPage(pageEl, e) {
    const r = pageEl.getBoundingClientRect();
    return { page: +pageEl.dataset.i, x: clamp((e.clientX - r.left) / r.width, 0, 1), y: clamp((e.clientY - r.top) / r.height, 0, 1) };
  }

  async function addNoteAt(at) {
    const text = await askText('Not ekle', '', 'Notunuzu yazın…');
    if (text && text.trim()) annotOp({ op: 'note', page: at.page, x: at.x, y: at.y, text });
  }

  // Metin seçilince çıkan vurgulama çubuğu
  function setupSelectionTools() {
    const box = $('#rd-pages');
    box.addEventListener('mousedown', e => e.target.closest('.rd-text')?.classList.add('selecting'));
    box.addEventListener('mouseup', e => {   // sağ tıkta (Mac: ⌃ tık) seçim çubuğu değil sağ tık menüsü açılır
      if (e.button === 0 && !e.ctrlKey) setTimeout(showSelectionTools, 0);
    });
    setupSelectionGuard();
    box.addEventListener('copy', onCopy);
    box.addEventListener('click', placeNote);
    $('#rd-scroll').addEventListener('scroll', hideSelectionTools, { passive: true });
  }

  function hideSelectionTools() { $$('.rd-seltools').forEach(t => t.remove()); }

  // Fare satır aralarına ya da kenar boşluğuna gelince seçim sayfanın sonuna atlamasın (pdf.js'teki yöntem):
  // seçim sürerken metin katmanının arkasına görünmez bir zemin (.rd-eoc) açılır ve seçimin hareket eden
  // ucunun hemen yanına taşınır; boşluğa gelen fare böylece seçimi olduğu yerde tutar.
  let selectionGuard = false;
  function setupSelectionGuard() {
    if (selectionGuard) return;
    selectionGuard = true;
    const stop = () => $$('.rd-text.selecting').forEach(l => l.classList.remove('selecting'));
    document.addEventListener('mouseup', stop);
    window.addEventListener('blur', stop);
    document.addEventListener('selectionchange', () => {
      const sel = window.getSelection();
      if (!sel.rangeCount || sel.isCollapsed || !sel.focusNode) return;
      const focus = sel.focusNode.nodeType === Node.TEXT_NODE ? sel.focusNode.parentElement : sel.focusNode;
      const layer = focus?.closest?.('.rd-text');
      const guard = layer && $('.rd-eoc', layer);
      if (!guard || focus === guard || focus === layer || focus.parentNode !== layer) return;
      const forward = sel.anchorNode === sel.focusNode ? sel.anchorOffset <= sel.focusOffset
        : !!(sel.anchorNode.compareDocumentPosition(sel.focusNode) & Node.DOCUMENT_POSITION_FOLLOWING);
      layer.insertBefore(guard, forward ? focus.nextSibling : focus);
    });
  }

  function selectionRects() {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return null;
    const range = sel.getRangeAt(0);
    if (!$('#rd-pages')?.contains(range.commonAncestorContainer)) return null;
    // Seçilen her kelimenin yalnızca yazısının kutusu alınır (kelime kutusu ayrıca sayılmaz) ve aynı satırdakiler
    // birleştirilir: vurgu satır başına tek parça olur, üst üste binip koyulaşmaz, alıntıda kelimeler tekrarlanmaz.
    const root = range.commonAncestorContainer.nodeType === Node.TEXT_NODE ? range.commonAncestorContainer.parentNode : range.commonAncestorContainer;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const boxes = [];
    for (let n = walker.currentNode; n; n = walker.nextNode()) {
      if (n.nodeType !== Node.TEXT_NODE || !range.intersectsNode(n) || !n.parentElement?.closest('.rd-text')) continue;
      const part = document.createRange();
      part.selectNodeContents(n);
      if (n === range.startContainer) part.setStart(n, range.startOffset);
      if (n === range.endContainer) part.setEnd(n, range.endOffset);
      const r = part.getBoundingClientRect();
      if (r.width >= 1 && r.height >= 1) boxes.push(r);
    }
    const byPage = new Map();
    const pagesEls = $$('.rd-page');
    for (const cr of boxes) {
      const cx = cr.left + cr.width / 2, cy = cr.top + cr.height / 2;
      const el = pagesEls.find(p => { const b = p.getBoundingClientRect(); return cx >= b.left && cx <= b.right && cy >= b.top && cy <= b.bottom; });
      if (!el) continue;
      const b = el.getBoundingClientRect();
      const i = +el.dataset.i;
      if (!byPage.has(i)) byPage.set(i, []);
      const rows = byPage.get(i);
      const x0 = (cr.left - b.left) / b.width, y0 = (cr.top - b.top) / b.height;
      const x1 = x0 + cr.width / b.width, y1 = y0 + cr.height / b.height;
      const row = rows.find(r => Math.abs((r[1] + r[3]) / 2 - (y0 + y1) / 2) < (y1 - y0) / 2);   // aynı satır
      if (row) { row[0] = Math.min(row[0], x0); row[2] = Math.max(row[2], x1); row[1] = Math.min(row[1], y0); row[3] = Math.max(row[3], y1); }
      else rows.push([x0, y0, x1, y1]);
    }
    for (const rows of byPage.values()) rows.forEach(r => { r[2] -= r[0]; r[3] -= r[1]; });   // [x, y, genişlik, yükseklik]
    return byPage.size ? { byPage, text: cleanText(range) || sel.toString(), last: boxes[boxes.length - 1] } : null;
  }

  function showSelectionTools() {
    hideSelectionTools();
    if (RD.noteMode || $('.ctx-menu')) return;   // sağ tık menüsü açıkken çıkmasın
    const s = selectionRects();
    if (!s || !s.last) return;
    const bar = document.createElement('div');
    bar.className = 'rd-seltools';
    bar.innerHTML = HL_COLORS.map(c => `<button class="hl-dot" data-c="${c}" style="background:${c}" title="Vurgula"></button>`).join('')
      + `<span class="sep"></span><button class="btn sm ghost icon-only" data-kind="underline" title="Altını çiz" aria-label="Altını çiz">${icon('underline')}</button>
         <button class="btn sm ghost icon-only" data-kind="strikeout" title="Üstünü çiz" aria-label="Üstünü çiz">${icon('strike')}</button>
         <span class="sep"></span><button class="btn sm ghost" data-note>${icon('note')}Notlu vurgu</button>
         <button class="btn sm ghost" data-copy>${icon('copy')}Kopyala</button>`;
    Object.assign(bar.style, { left: Math.min(s.last.right - 40, innerWidth - 420) + 'px', top: s.last.bottom + 8 + 'px' });
    document.body.append(bar);
    bar.addEventListener('mousedown', e => e.preventDefault());   // seçim kaybolmasın
    const apply = async (color, note = '', kind = 'highlight') => {
      hideSelectionTools();
      window.getSelection().removeAllRanges();
      for (const [page, rects] of s.byPage) await annotOp({ op: 'highlight', page, rects, color, note, kind }, 'İşaretleniyor…');
    };
    $$('[data-c]', bar).forEach(b => b.onclick = () => apply(b.dataset.c));
    $$('[data-kind]', bar).forEach(b => b.onclick = () => apply(LINE_COLOR, '', b.dataset.kind));
    $('[data-note]', bar).onclick = async () => {
      hideSelectionTools();
      const note = await askText('Vurguya not', '', 'Bu bölümle ilgili notunuz…');
      if (note != null) apply(HL_COLORS[0], note);
    };
    $('[data-copy]', bar).onclick = () => { copyText(s.text); hideSelectionTools(); };
  }

  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); toast('Kopyalandı.', 'ok'); }
    catch { document.execCommand('copy'); }   // seçim hâlâ duruyor: temiz kopyalama (onCopy) çalışır
  }

  // ---------------------------------------------------------------- tıklanabilir işaretler
  // Vurgu ve çizgiler sayfa görüntüsüne çizilidir. Fare üzerine gelince işaret çerçevelenir (notu varsa ipucunda
  // görünür); tıklayınca rengini ya da türünü değiştirme, not ve silme çubuğu açılır.
  let hovered = null;
  function setupMarkClicks() {
    const box = $('#rd-pages');
    let raf = 0, last = null;
    box.addEventListener('mousemove', e => {
      last = e;
      if (raf) return;
      raf = requestAnimationFrame(() => { raf = 0; hoverMark(last.buttons ? null : markAt(last)); });
    });
    box.addEventListener('mouseleave', () => hoverMark(null));
    box.addEventListener('click', e => {
      if (RD.noteMode || e.button !== 0 || !window.getSelection().isCollapsed) return;   // not koyma ya da metin seçimi
      if (e.target.closest('.pdf-link, .rd-note-marker, .rd-form, .item, .line-box, .line-input')) return;
      const hit = markAt(e);
      if (hit) markBar(hit, e.clientX, e.clientY);
    });
    $('#rd-scroll').addEventListener('scroll', closeMarkBar, { passive: true });
  }

  // Noktadaki vurgu ya da çizgi (düzenleme aracı seçiliyken yok: tıklama aracındır)
  function markAt(e) {
    const box = $('#rd-pages');
    if (box?.classList.contains('editing') && !box.classList.contains('select-mode')) return null;
    const pageEl = e.target.closest?.('.rd-page');
    if (!pageEl) return null;
    const at = pointOnPage(pageEl, e);
    return RD.marks.annots.find(a => a.page === at.page && MARK_KIND[a.type] && (a.rects || []).some(([x, y, w, h]) =>
      at.x >= x - 0.002 && at.x <= x + w + 0.002 && at.y >= y - 0.003 && at.y <= y + h + 0.003)) || null;
  }

  function hoverMark(a) {
    if (a === hovered) return;
    $$('.rd-markhover').forEach(el => el.remove());
    $$('.rd-page.over-mark').forEach(el => { el.classList.remove('over-mark'); el.removeAttribute('title'); });
    hovered = a;
    if (!a) return;
    const pageEl = $(`.rd-page[data-i="${a.page}"]`);
    if (!pageEl) return;
    pageEl.classList.add('over-mark');
    pageEl.title = a.content ? `Not: ${a.content}` : 'Tıklayın: rengini ya da türünü değiştirin, not ekleyin, silin';
    const layer = $('.rd-annots', pageEl);
    for (const [x, y, w, h] of a.rects) {
      const el = document.createElement('div');
      el.className = 'rd-markhover';
      Object.assign(el.style, { left: x * 100 + '%', top: y * 100 + '%', width: w * 100 + '%', height: h * 100 + '%' });
      layer.append(el);
    }
  }

  // Renkler sunucuda 0–1 arası sayılardan gelir: küçük yuvarlama farkları aynı renk sayılır
  const sameColor = (a, b) => [1, 3, 5].every(k => Math.abs(parseInt(a.substr(k, 2), 16) - parseInt(b.substr(k, 2), 16)) < 8);

  let markBarClose = () => { };
  function closeMarkBar() { markBarClose(); }

  function markBar(a, x, y) {
    closeMarkBar();
    hideSelectionTools();
    const kind = MARK_KIND[a.type];
    const kinds = [['highlight', 'highlight', 'Vurgu'], ['underline', 'underline', 'Altını çiz'], ['strikeout', 'strike', 'Üstünü çiz']];
    const bar = document.createElement('div');
    bar.className = 'rd-markbar';
    bar.innerHTML = `<div class="mb-row">
        ${(kind === 'highlight' ? HL_COLORS : LINE_COLORS).map(c => `<button class="hl-dot ${sameColor(c, a.color) ? 'on' : ''}" data-c="${c}"
          style="background:${c}" title="Bu renge çevir" aria-label="Renk"></button>`).join('')}
        <span class="sep"></span>
        ${kinds.map(([k, ic, label]) => `<button class="btn sm ghost icon-only ${k === kind ? 'on' : ''}" data-kind="${k}" title="${label}"
          aria-label="${label}">${icon(ic)}</button>`).join('')}
        <span class="sep"></span>
        <button class="btn sm ghost" data-note>${icon('note')}${a.content ? 'Notu düzenle' : 'Not ekle'}</button>
        <button class="btn sm ghost icon-only" data-del title="Sil (Geri Al ile geri alınır)" aria-label="Sil">${icon('trash')}</button>
      </div>${a.content ? `<div class="mb-note">${esc(a.content)}</div>` : ''}`;
    document.body.append(bar);
    const w = bar.offsetWidth, h = bar.offsetHeight;
    Object.assign(bar.style, { left: clamp(x - 24, 8, innerWidth - w - 8) + 'px', top: (y + 14 + h > innerHeight - 8 ? y - h - 14 : y + 14) + 'px' });
    const outside = e => { if (!bar.contains(e.target)) close(); };
    const onKey = e => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
    const close = () => {
      bar.remove();
      document.removeEventListener('mousedown', outside, true);
      document.removeEventListener('keydown', onKey, true);
      markBarClose = () => { };
    };
    markBarClose = close;
    setTimeout(() => document.addEventListener('mousedown', outside, true));
    document.addEventListener('keydown', onKey, true);
    bar.addEventListener('mousedown', e => e.preventDefault());
    const restyle = async change => {
      const first = a.rects[0];
      if (!await annotOp({ op: 'annot_style', page: a.page, xref: a.xref, ...change }, 'Değiştiriliyor…')) return;
      // Yeni hâliyle çubuk açık kalsın (tür değişince işaret yeniden oluşturulur, kimliği değişir)
      const again = RD.marks.annots.find(b => b.page === a.page && MARK_KIND[b.type]
        && b.rects.some(([bx, by, bw, bh]) => Math.abs(bx - first[0]) < 0.01 && Math.abs(by - first[1]) < 0.01));
      if (again) markBar(again, x, y);
    };
    $$('[data-c]', bar).forEach(b => b.onclick = () => { if (!b.classList.contains('on')) restyle({ color: b.dataset.c }); });
    $$('[data-kind]', bar).forEach(b => b.onclick = () => { if (b.dataset.kind !== kind) restyle({ kind: b.dataset.kind }); });
    $('[data-note]', bar).onclick = () => { close(); editAnnot(a); };
    $('[data-del]', bar).onclick = async () => {
      close();
      if (await annotOp({ op: 'annot_delete', page: a.page, xref: a.xref }, 'Siliniyor…')) toast('İşaret silindi. Geri almak için ⌘Z.', 'ok');
    };
  }

  // ---------------------------------------------------------------- sağ tık menüsü
  // Tıklanan yere göre: seçili metin, eklenen öğe (düzenlerken), var olan not ya da vurgu, sayfanın kendisi.
  // Mac'te sağ tık, seçim dışındaki kelimeyi kendiliğinden seçer; bu yüzden sağ tıktan hemen önceki seçime bakılır.
  let selBeforeMenu = null;
  function setupContextMenu() {
    const box = $('#rd-pages');
    box.addEventListener('mousedown', e => {
      if (e.button === 2 || (e.button === 0 && e.ctrlKey && HOST === 'mac')) selBeforeMenu = selectionRects();
    }, true);
    box.addEventListener('contextmenu', onPageMenu);
  }

  function onPageMenu(e) {
    const pageEl = e.target.closest('.rd-page');
    if (!pageEl || e.target.closest('textarea, input')) return;   // metin kutusunda tarayıcının menüsü (yapıştır, yazım)
    e.preventDefault();
    $$('.rd-pop').forEach(p => p.remove());
    const at = pointOnPage(pageEl, e);
    const sel = selBeforeMenu;
    selBeforeMenu = null;
    const onSel = sel?.byPage.get(at.page)?.some(([x, y, w, h]) => at.x >= x - 0.01 && at.x <= x + w + 0.01 && at.y >= y - 0.01 && at.y <= y + h + 0.01);
    if (!onSel) window.getSelection().removeAllRanges();   // sağ tıkla kendiliğinden seçilen kelime
    const items = onSel ? selectionMenu(sel) : window.Editor.itemMenu(e.target) || [...annotMenu(at), ...pageMenu(at)];
    contextMenu(e.clientX, e.clientY, items);
    hideSelectionTools();
  }

  function selectionMenu(s) {
    const mark = (color, kind = 'highlight', note = '') => async () => {
      window.getSelection().removeAllRanges();
      for (const [page, rects] of s.byPage) await annotOp({ op: 'highlight', page, rects, color, note, kind }, 'İşaretleniyor…');
    };
    const q = s.text.replace(/\s+/g, ' ').trim();
    return [
      { label: 'Kopyala', icon: 'copy', hint: '⌘C', run: () => copyText(s.text) },
      { label: 'Vurgula', colors: HL_COLORS, run: color => mark(color)() },
      { label: 'Altını çiz', icon: 'underline', run: mark(LINE_COLOR, 'underline') },
      { label: 'Üstünü çiz', icon: 'strike', run: mark(LINE_COLOR, 'strikeout') },
      { label: 'Notlu vurgu…', icon: 'note', run: async () => {
        const note = await askText('Vurguya not', '', 'Bu bölümle ilgili notunuz…');
        if (note != null) mark(HL_COLORS[0], 'highlight', note)();
      } },
      'sep',
      q && q.length <= 100 ? { label: `“${q.length > 30 ? q.slice(0, 29) + '…' : q}” belgede ara`, icon: 'search', run: () => {
        window.getSelection().removeAllRanges();
        toggleSearch(true);
        $('#rd-q').value = q;
        runSearch(q);
      } } : null,
      'sep',
      { label: 'Karart: seçili metni kalıcı olarak sil', icon: 'redact', danger: true, run: () => redactSelection(s) },
    ];
  }

  // Seçili metin belgeden silinir, yerine siyah kutu konur (Geri Al ile geri alınır). Kutu komşu satırlara
  // değmeyecek kadar sunucuda daraltılır (fit).
  async function redactSelection(s) {
    if (!await confirmSignedRewrite(RD.info, 'Karartma')) return;
    window.getSelection().removeAllRanges();
    const areas = [...s.byPage].map(([page, rects]) => ({ page, rects }));
    if (await annotOp({ op: 'redact_areas', fit: true, areas }, 'Karartılıyor…')) toast('Seçili metin karartıldı. Geri almak için ⌘Z.', 'ok');
  }

  // Tıklanan yerdeki not ya da işaret (birden çoksa en küçüğü)
  function annotAt(at) {
    const pad = 0.004;
    return RD.marks.annots.filter(a => a.page === at.page && at.x >= a.x - pad && at.x <= a.x + Math.max(a.w, 0.02) + pad
      && at.y >= a.y - pad && at.y <= a.y + Math.max(a.h, 0.015) + pad).sort((a, b) => a.w * a.h - b.w * b.h)[0];
  }

  function annotMenu(at) {
    const a = annotAt(at);
    if (!a) return [];
    const note = a.type === 'Text';
    return [
      { label: note ? 'Notu düzenle…' : a.content ? 'İşaretin notunu düzenle…' : 'İşarete not ekle…', icon: 'edit', run: () => editAnnot(a) },
      { label: note ? 'Notu sil' : a.type === 'Highlight' ? 'Vurguyu sil' : 'İşareti sil', icon: 'trash', danger: true, run: () => deleteAnnot(a) },
      'sep',
    ];
  }

  function pageMenu(at) {
    const ed = window.Editor;
    return [
      { label: 'Buraya not ekle…', icon: 'note', run: () => addNoteAt(at) },
      { label: 'Buraya metin ekle', icon: 'text', run: () => ed.placeAt('text', at) },
      { label: 'Buraya imza koy…', icon: 'signature', run: () => ed.placeAt('signature', at) },
      { label: 'Buraya kaşe bas…', icon: 'stamp', run: () => ed.placeAt('stamp', at) },
      { label: 'Buraya resim koy…', icon: 'img', run: () => ed.placeAt('image', at) },
      'sep',
      { label: 'Bu sayfaya yer imi ekle…', icon: 'bookmark', run: () => { setCurrent(at.page); addBookmark(); } },
      ...ed.pageMenuItems([at.page]),
    ];
  }

  async function addBookmark() {
    const title = await askText(`Yer imi — sayfa ${RD.cur + 1}`, `Sayfa ${RD.cur + 1}`);
    if (title == null) return;
    if (await annotOp({ op: 'bookmark_add', page: RD.cur, title: title.trim() || `Sayfa ${RD.cur + 1}` })) {
      toast('Yer imi eklendi.', 'ok');
      if (RD.side !== 'marks') openSide('marks');
    }
  }

  function buildMarksList() {
    const box = $('#rd-side-body');
    if (!box) return;
    const list = RD.marks.outline;
    box.innerHTML = `<button class="btn sm" id="rd-mark-add" style="width:100%;margin-bottom:8px">${icon('bookmark')}Bu sayfaya yer imi ekle</button>`
      + (list.length ? list.map((m, i) => `<div class="rd-item" data-i="${i}" style="padding-left:${8 + (m.level - 1) * 14}px">
          <span class="rd-item-title">${esc(m.title)}</span><span class="muted small">${m.page >= 0 ? 's. ' + (m.page + 1) : ''}</span>
          <button class="x" data-del="${i}" title="İçindekilerden sil">×</button></div>`).join('')
        : '<p class="muted small">Bu belgede içindekiler (bölüm listesi) yok. Okuduğunuz sayfayı listeye eklemek için yukarıdaki düğmeyi kullanın.</p>');
    $('#rd-mark-add').onclick = addBookmark;
    $$('.rd-item', box).forEach(el => el.onclick = async e => {
      const i = +el.dataset.i;
      if (e.target.dataset.del != null) {
        if (confirm(`“${list[i].title}” içindekilerden silinsin mi?`)) annotOp({ op: 'bookmark_delete', index: i }, 'Siliniyor…');
        return;
      }
      if (list[i].page >= 0) goPage(list[i].page, false, list[i].y);
    });
  }

  const MARK_SWATCH = { Underline: 'is-under', StrikeOut: 'is-strike' };   // listede çizgi işaretlerinin görünümü

  function buildNotesList() {
    const box = $('#rd-side-body');
    if (!box) return;
    const items = [...RD.marks.annots].sort((a, b) => a.page - b.page || a.y - b.y);
    box.innerHTML = (items.length ? `<button class="btn sm" id="rd-notes-report" style="width:100%;margin-bottom:8px"
        title="Vurgular ve notlar sayfa numaralarıyla tek bir Word ya da PDF belgesine dökülür">${icon('docs')}Rapora dök…</button>` : '')
      + (items.length ? items.map((a, i) => `<div class="rd-item rd-noteitem" data-i="${i}">
        <span class="rd-swatch ${MARK_SWATCH[a.type] || ''}" style="--c:${a.color};background:${a.type === 'Text' ? '#ffd23f' : a.color}">${a.type === 'Text' ? icon('note') : ''}</span>
        <div class="rd-item-body">
          ${a.quote ? `<div class="rd-quote">“${esc(a.quote)}”</div>` : ''}
          ${a.content ? `<div>${esc(a.content)}</div>` : ''}
          <div class="muted small">Sayfa ${a.page + 1}${a.author ? ` · ${esc(a.author)}` : ''}</div>
        </div>
        <div class="rd-item-actions"><button class="x" data-edit title="Notu düzenle">${icon('edit')}</button>
          <button class="x" data-del title="Sil">×</button></div></div>`).join('')
      : '<p class="muted small">Henüz not ya da vurgu yok. Metni seçip renk düğmesine basarak vurgulayabilir, araç çubuğundaki not düğmesiyle sayfaya not koyabilirsiniz.</p>');
    const report = $('#rd-notes-report', box);
    if (report) report.onclick = notesReportDialog;
    $$('.rd-noteitem', box).forEach(el => el.onclick = e => {
      const a = items[+el.dataset.i];
      if (e.target.closest('[data-del]')) return deleteAnnot(a);
      if (e.target.closest('[data-edit]')) return editAnnot(a);
      const scroller = $('#rd-scroll');
      scroller.scrollTo({ top: pageTop(a.page) + a.y * pages()[a.page].h * RD.scale - scroller.clientHeight / 3 });
      setCurrent(a.page);
      if (MARK_KIND[a.type]) {   // işaret: rengi, türü, notu, silme (kaydırma bitince: kaydırma çubuğu kapatır)
        setTimeout(() => {
          const r = $(`.rd-page[data-i="${a.page}"]`)?.getBoundingClientRect();
          if (r) markBar(a, r.left + a.x * r.width, r.top + (a.y + a.h) * r.height);
        }, 150);
      }
    });
  }

  // Notlar ve vurgular raporu: işaretler sayfa numaralarıyla Word ya da PDF olarak kaydedilir
  function notesReportDialog() {
    const opt = { format: 'docx', by: 'page' };
    const m = modal({
      title: 'Notlar ve vurgular raporu', width: 500,
      body: `<p class="muted small" style="margin:0 0 14px">Vurgular, altı ve üstü çizili yerler ve notlar sayfa numaralarıyla tek bir
          belgeye dökülür: işaretlediğiniz metin alıntı olarak, notunuz altında yer alır. Taranmış sayfalardaki işaretlerin
          görüntüsü konur.</p>
        <div class="field"><label>Biçim</label><div class="seg" data-opt="format">
          <button type="button" data-v="docx" class="on">Word (.docx)</button><button type="button" data-v="pdf">PDF</button></div></div>
        <div class="field" style="margin-top:12px"><label>Sıralama</label><div class="seg" data-opt="by">
          <button type="button" data-v="page" class="on">Sayfa sırasıyla</button><button type="button" data-v="color">Renge göre</button></div></div>
        <div style="margin-top:14px;display:flex;gap:18px">
          <label class="check"><input type="checkbox" id="nr-marks" checked>Vurgular ve çizgiler</label>
          <label class="check"><input type="checkbox" id="nr-notes" checked>Notlar</label></div>`,
      foot: `<button class="btn" data-x>Vazgeç</button><button class="btn primary" id="nr-go">${icon('download')}Raporu kaydet…</button>`,
    });
    $$('[data-opt]', m.el).forEach(seg => $$('button', seg).forEach(b => b.onclick = () => {
      opt[seg.dataset.opt] = b.dataset.v;
      $$('button', seg).forEach(x => x.classList.toggle('on', x === b));
    }));
    $('[data-x]', m.el).onclick = m.close;
    $('#nr-go', m.el).onclick = async () => {
      const marks = $('#nr-marks', m.el).checked, notes = $('#nr-notes', m.el).checked;
      if (!marks && !notes) return toast('Rapora girecek en az bir tür seçin.', 'error');
      let r;
      try {
        r = await withBusy('Rapor hazırlanıyor…', () => postJSON(`/api/edit/${sid()}/annot-report`, { ...opt, marks, notes }));
      } catch { return; }
      m.close();
      try {
        const where = await saveOutput(r, dirOf(RD.path));
        if (where) toast(`Rapor kaydedildi (${r.count} işaret): ${shortPath(where)}`, 'ok');
      } catch { /* hata gösterildi */ }
    };
  }

  // Kaydet: açılan dosyanın üzerine (eski hâli yedeklenir); bilinmiyorsa ya da Farklı Kaydet'te yer sorulur
  // Dönen: kaydedildi mi (vazgeçilir ya da kaydedilemezse false)
  async function save(asNew = false) {
    if (!RD.info || !await applyPending()) return false;
    try {
      const info = asNew ? await saveAs(RD.info) : await saveDocument(RD.info);
      if (!info) return false;
      RD.info = { ...RD.info, ...info };
      if (info.path) RD.path = info.path;
      setDirty(!!info.unsaved);
      setTabTitle(RD.info.name, RD.path);
      return !info.unsaved;
    } catch { return false; /* hata mesajı gösterildi */ }
  }

  async function share() {
    if (RD.info && await applyPending()) shareFile({ sid: sid(), name: docFileName(RD.info), anchor: $('#rd-share') });
  }

  // Kurtarılan ya da bir aracın oluşturduğu belgeyi bu sekmede aç (ekran açılınca çizilir). edit: araçlar açık gelsin
  function useSession(info, page = 0, edit = false) {
    if (RD.info && RD.info.id !== info.id) postJSON(`/api/edit/${RD.info.id}/close`).catch(() => { });
    window.Editor.reset(edit || window.Editor.isEditing());
    try { sessionStorage.setItem(SID_KEY, info.id); } catch { }
    RD.info = info;
    RD.path = info.path || null;
    RD.dirty = !!info.unsaved;
    RD.search = { q: '', flat: [], idx: -1 };
    RD.noteMode = false;
    RD.marks = { annots: [], outline: [] };
    RD.cur = clamp(page, 0, info.pages.length - 1);
  }

  // Bir araç belgeye uygulandı (görünüm açılınca yeni hâli çizilir)
  function update(info) {
    RD.info = info;
    RD.dirty = !!info.unsaved;
    window.Editor.docChanged();
  }

  // Yerel uygulama kapanırken kaydedilmemiş değişiklik varsa sorsun
  window.PDFSTUDYO_unsaved = () => !!RD.info && (RD.dirty || window.Editor.pendingCount() > 0 || fieldTyping());

  // ---------------------------------------------------------------- metin tanıma
  async function runOcr() {
    if (!await applyPending()) return;
    const n = pages().length;
    let res;
    try {
      res = await withBusy(`Metin tanınıyor… (${n} sayfa, yaklaşık ${Math.max(1, Math.round(n * 1.2))} saniye)`,
        () => postJSON(`/api/edit/${sid()}/op`, { op: 'ocr' }));
    } catch { return; }
    const keep = RD.cur;
    RD.info = res;
    RD.dirty = !!res.unsaved;
    renderShell();
    goPage(keep);
    const banner = $('#rd-ocr');
    const msg = res.count ? `${res.count} sayfada metin tanındı. Artık arayıp kopyalayabilirsiniz.${res.notice ? ' ' + res.notice : ''}` : 'Tanınacak metin bulunamadı.';
    toast(msg, res.count ? 'ok' : '');
    if (res.count) {
      // Aranabilir hâlini kaydetme imkânı (özgün dosya değişmez)
      const bar = document.createElement('div');
      bar.className = 'rd-banner ok';
      bar.innerHTML = `${icon('check')}<span>Metin tanındı. Dosyanız henüz değişmedi: Kaydet ile dosyanıza işleyebilir, Farklı Kaydet ile ayrı bir kopya oluşturabilirsiniz.</span>
        <button class="btn sm" id="rd-ocr-save">${icon('saveas')}Farklı Kaydet…</button>`;
      (banner || $('.reader .doc-toolbar')).after(bar);
      banner?.remove();
      $('#rd-ocr-save').onclick = () => save(true);
    }
  }

  // ---------------------------------------------------------------- yazdırma
  async function print() {
    if (!await applyPending()) return;
    const url = `${location.origin}/api/edit/${sid()}/download?inline=1`;
    if (NATIVE) native({ action: 'print', url, path: RD.path, name: RD.info.name });
    else window.open(url, '_blank');
  }

  // ---------------------------------------------------------------- klavye
  function onKey(e) {
    if (!RD.info || !$('#rd-scroll') || $('.modal-back')) return;
    if (window.Editor.onKey(e)) return;   // düzenleme araçları: seçili öğeyi silme, aracı bırakma
    const mod = e.metaKey || e.ctrlKey;
    const k = e.key.toLowerCase();
    const typing = ['INPUT', 'TEXTAREA'].includes(document.activeElement?.tagName);
    if (mod && k === 'f') { e.preventDefault(); return toggleSearch(true); }
    if (mod && k === 'z' && !typing) { e.preventDefault(); return historyStep(e.shiftKey ? 'redo' : 'undo'); }
    if (mod && k === 'y' && !typing) { e.preventDefault(); return historyStep('redo'); }
    if (mod && k === 'p') { e.preventDefault(); return print(); }
    if (mod && (k === '+' || k === '=')) { e.preventDefault(); return stepZoom(1); }
    if (mod && k === '-') { e.preventDefault(); return stepZoom(-1); }
    if (mod && k === '0') { e.preventDefault(); return setZoom('width'); }
    if (e.key === 'Escape') { hideSelectionTools(); $$('.rd-pop').forEach(p => p.remove()); if (RD.noteMode) setNoteMode(false); }
    const tag = document.activeElement?.tagName;
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return;
    if (e.key === 'ArrowRight') { e.preventDefault(); step(1); }
    if (e.key === 'ArrowLeft') { e.preventDefault(); step(-1); }
    if (!RD.view.scroll && (e.key === 'PageDown' || e.key === 'PageUp' || e.key === ' ')) {   // sayfa sayfa görünüm
      e.preventDefault();
      step(e.key === 'PageUp' || (e.key === ' ' && e.shiftKey) ? -1 : 1);
    }
    if (e.key === 'Home' && !mod) { e.preventDefault(); goPage(0); }
    if (e.key === 'End' && !mod) { e.preventDefault(); goPage(pages().length - 1); }
  }

  // ---------------------------------------------------------------- yerel uygulama köprüsü
  // Kaydedilmemiş belgenin sekmesi (ya da pencere) kapatılırken "Kaydet" / "Farklı Kaydet…" seçildi: ⌘S ile aynı
  // kaydetme (karartma ve e-imza soruları dahil). Dönen: kaydedildi mi; değilse sekme açık kalır.
  window.PDFSTUDYO_saveForClose = async asNew => (RD.info ? save(!!asNew) : true);

  // Windows: kapatma sorusunu sayfa sorar (Mac'te uygulamanın kendi uyarısı). Dönen: sekme kapatılabilir mi
  window.PDFSTUDYO_confirmClose = async () => {
    if (!window.PDFSTUDYO_unsaved()) return true;
    const how = await askChoice({
      title: 'Kaydedilmemiş değişiklikler var', width: 620,
      body: `<p style="margin:0">“${esc(RD.info?.name || 'Belge')}” belgesindeki değişiklikleri henüz kaydetmediniz. Kapatmadan önce
        kaydetmek ister misiniz? Kaydetmezseniz değişiklikler kaybolur.</p>`,
      choices: [{ id: '', label: 'Vazgeç' }, { id: 'discard', label: 'Kaydetmeden kapat' },
        { id: 'saveas', label: 'Farklı Kaydet…', icon: 'saveas' }, { id: 'save', label: 'Kaydet', primary: true, icon: 'save' }],
    });
    if (how === 'discard') return true;
    if (how === 'save' || how === 'saveas') return save(how === 'saveas');
    return false;
  };

  window.PDFSTUDYO_openPaths = paths => {
    queuePaths(paths);
    if (location.hash !== '#/reader') location.hash = '#/reader';
  };
  window.PDFSTUDYO_defaultStatus = (isDefault, message) => {
    RD.isDefault = !!isDefault;
    renderDefaultPanel();
    document.dispatchEvent(new CustomEvent('pdfdefault', { detail: { isDefault: RD.isDefault } }));   // Ayarlar penceresi
    if (message) toast(message, isDefault ? 'ok' : 'error');
  };

  // Belge ekranda durdukça sunucu oturumu silmesin (saatlerce dokunulmadan açık kalsa da): ara ara ve pencere
  // yeniden öne gelince bildirilir
  const touchDoc = () => { if (RD.info) fetch(`/api/edit/${sid()}/touch`, { method: 'POST' }).catch(() => { }); };
  setInterval(touchDoc, 20 * 60000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) touchDoc(); });

  // Açık (ya da açılmakta olan) belge var mı — yerel uygulama yeni PDF'i hangi sekmeye koyacağına bakar
  const hasDoc = () => !!RD.info || RD.opening || RD.queue.length > 0;

  // Belge bir araç penceresinde değişti (Sıkıştır): yeniden çizilir, aynı sayfada kalınır
  function refresh(info) {
    const keep = RD.cur;
    RD.info = info;
    RD.dirty = !!info.unsaved;
    renderShell();
    goPage(keep);
  }

  window.Reader = { mount, unmount, hasDoc, update, refresh, save, share, useSession, docInfo: () => RD.info, flush: () => window.Editor.flush(),
    view: () => ({ ...RD.view }), setView };
})();
