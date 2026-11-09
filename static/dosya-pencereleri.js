/* Koç PDF Pro — Format Değiştir penceresi ve onun Sıkıştır'la ortak dosya penceresi (fileWindow). */
'use strict';

// ------------------------------------------------------------------ format değiştir
// Dönüştürmeler tek pencerede: dosyalar eklenir (türleri karışık olabilir), her dosyanın hedef biçimi kendi satırında
// seçilir, sonuçlar birlikte bir klasöre kaydedilir. Ayrıntılı dönüştürme sayfaları (#/pdf-to-word …) adresle açılır,
// menülerde yer almaz.
const CONVERT_IDS = new Set(['pdf-to-word', 'pdf-to-excel', 'to-udf', 'pdf-to-images', 'word-to-pdf', 'excel-to-pdf',
  'udf-to-pdf', 'udf-to-word', 'images-to-pdf']);
const listedTools = g => TOOLS.filter(t => t.group === g && !CONVERT_IDS.has(t.id));   // ana sayfa ve menülerdeki araçlar

const FX_ACCEPT = `.pdf,.udf,${WORD_ACCEPT},${EXCEL_ACCEPT},.jpg,.jpeg,.png,.heic,.webp,.bmp,.gif,.tif,.tiff`;
const FX_KIND = { pdf: 'PDF', word: 'Word', excel: 'Excel', udf: 'UDF', image: 'Resim' };
const FX_DPI = { name: 'dpi', value: '150', choices: [['96', '96 dpi'], ['150', '150 dpi'], ['300', '300 dpi']] };
const FX_IMAGES = 'Her sayfa ayrı bir resim; çok sayfalı belgede resimler bir klasörde toplanır.';
// Her kaynak türünün gidebileceği biçimler. form: sabit alanlar; opts: satırdaki küçük seçenekler (value yoksa ilki varsayılan);
// app: gereken program (Word / Excel; yoksa LibreOffice); pages: çok sayfalı belgede sonuç bir klasör olur
const FX_TARGETS = {
  pdf: [
    { id: 'word', label: 'Word', ext: 'docx', endpoint: '/api/convert/pdf-to-word',
      note: 'Düzenlenebilir Word belgesi; sayfa düzeni, tablolar ve resimler korunur.',
      opts: () => (state.engines.word ? [{ name: 'engine', choices: [['standart', 'Standart'], ['word', 'Microsoft Word ile']] }] : []) },
    { id: 'excel', label: 'Excel', ext: 'xlsx', endpoint: '/api/convert/pdf-to-excel',
      note: 'Tablolar Excel\'e aktarılır; tutarlar sayı, tarihler tarih olur.',
      opts: () => [{ name: 'content', choices: [['tables', 'Yalnızca tablolar'], ['all', 'Bütün sayfa']] }] },
    { id: 'udf', label: 'UDF', ext: 'udf', endpoint: '/api/convert/to-udf', note: UDF_NOTE },
    { id: 'jpg', label: 'JPG', ext: 'jpg', pages: true, endpoint: '/api/convert/pdf-to-images', form: { format: 'jpg' }, note: FX_IMAGES,
      opts: () => [FX_DPI] },
    { id: 'png', label: 'PNG', ext: 'png', pages: true, endpoint: '/api/convert/pdf-to-images', form: { format: 'png' }, note: FX_IMAGES,
      opts: () => [FX_DPI] },
    { id: 'tiff', label: 'TIFF', ext: 'tif', endpoint: '/api/convert/pdf-to-images', form: { format: 'tiff' },
      note: 'Bütün sayfalar tek bir TIFF dosyasında.',
      opts: () => [FX_DPI, { name: 'color', choices: [['gri', 'Gri'], ['renkli', 'Renkli'], ['sb', 'Siyah-beyaz']] }] },
  ],
  word: [
    { id: 'pdf', label: 'PDF', ext: 'pdf', endpoint: '/api/convert/word-to-pdf', app: 'word', note: 'Word\'deki görünümüyle birebir PDF.' },
    { id: 'udf', label: 'UDF', ext: 'udf', endpoint: '/api/convert/to-udf', note: UDF_NOTE },
  ],
  excel: [
    { id: 'pdf', label: 'PDF', ext: 'pdf', endpoint: '/api/convert/excel-to-pdf', app: 'excel',
      note: 'Bütün çalışma sayfaları Excel\'in sayfa düzeniyle tek PDF\'te.' },
  ],
  udf: [
    { id: 'pdf', label: 'PDF', ext: 'pdf', endpoint: '/api/convert/udf-to-pdf', note: 'Biçimi korunarak PDF\'e; Word gerekmez.' },
    { id: 'word', label: 'Word', ext: 'docx', endpoint: '/api/convert/udf-to-word', note: 'Düzenlenebilir Word belgesi.' },
  ],
  image: [
    { id: 'pdf', label: 'PDF', ext: 'pdf', endpoint: '/api/convert/images-to-pdf',
      note: 'Çok sayfalı TIFF\'in her sayfası ayrı sayfa olur. Birkaç resmi tek PDF yapmak için Birleştir\'i kullanın.',
      opts: () => [{ name: 'page_size', choices: [['a4', 'A4'], ['a4-yatay', 'A4 yatay'], ['orijinal', 'Resim boyutu']] }] },
  ],
};
const FX_APP = { word: 'Microsoft Word', excel: 'Microsoft Excel' };

// ------------------------------------------------------------------ dosya pencereleri
// Format Değiştir ve Sıkıştır'ın ortak penceresi: dosyalar eklenir ya da bırakılır (bir kez sunucuya alınır: küçük resim,
// sayfa sayısı), şifreli PDF'in şifresi satırında sorulur, dosyalar satır satır işlenir, sonuçlar birlikte bir klasöre
// kaydedilir. spec:
//   title, kinds (kabul edilen türler), wrongKind, accept, emptyHint, folderName (birden çok dosyanın klasörü), progress,
//   runIcon, runLabel(rows): ana düğme · newRow(f): sunucudan gelen dosyaya pencerenin alanları eklenir
//   rowBody(r): satırın ayar kısmı (html) · bindRow(el, r) · renderTop(kutu) / renderSettings(kutu): ek düğmeler, ayarlar
//   outName(r): tek dosyada kaydedilecek ad {name, ext, folder} · process(r): satırın sonucu (araç çıktısı)
//   noteInBody: sonuç notu satırın ayar kısmında gösteriliyor · changed(): satırlar değişti (eklendi, çıkarıldı, şifre)
//   single: tek dosya (yenisi eskisinin yerine geçer) · settingsBelow: ayarlar listenin altında · blocked(): ana düğme
//   kapalı · outputs(r): bir satırın birden çok sonucu · saveAs(rows): Kaydet bölümünün adı {name, ext, folder, note}
//   doneHtml(r): işlenen satırın son satırı
//   docOnly: yalnızca açık belge (dosya eklenmez) · applyLabel, applyHint, finish(done): Kaydet bölümünde "Yeni dosya
//   olarak kaydet" ile "belgeye uygula" arasında seçim; uygulama seçiliyse sonuç finish ile belgeye uygulanır
function fileWindow(spec) {
  const w = { rows: [], loading: 0, running: false, closed: false, desktop: '', dir: '', dirTouched: false, apply: false };
  let name = '', nameKey = '', nameTouched = false;
  const m = modal({
    title: spec.title, width: 780,
    body: `<div class="fx-top" ${spec.docOnly ? 'hidden' : ''}><button class="btn sm" id="fx-add">${icon('plus')}${spec.single ? 'Dosya seç' : 'Dosya ekle'}</button>
        <button class="link-btn small" id="fx-clear">Listeyi temizle</button><span class="spacer"></span>
        <span class="fx-all" id="fx-all"></span><span class="muted small" id="fx-count"></span></div>
      <div class="fx-settings" id="fx-settings" hidden></div>
      <div class="fx-list" id="fx-list"></div><div class="fx-save" id="fx-save" hidden></div>`,
    foot: `<span class="fx-status" id="fx-status"></span><span class="spacer"></span>
      <button class="btn" data-x>Kapat</button><button class="btn primary" id="fx-run"></button>`,
    onClose: () => { w.closed = true; },
  });
  m.el.classList.add('fx-dialog');
  w.m = m;
  const el = w.el = id => $('#' + id, m.el);
  if (spec.settingsBelow) el('fx-list').after(el('fx-settings'));
  w.status = html => { el('fx-status').innerHTML = html; };
  // Kutunun içeriği yalnızca değiştiyse yeniden çizilir: ilgisiz güncellemelerde yazı kutusu ve odak bozulmaz
  w.patch = (box, html, bind) => {
    if (box._html === html) return;
    box._html = html;
    box.innerHTML = html;
    bind?.(box);
  };
  const stemOf = w.stemOf = n => n.replace(/\.[^.]*$/, '');
  // Pencerenin içinde geçici bir bölüm (Sıkıştır'ın önizlemesi): liste ve Kaydet gizlenir, ayarlar kalır. Dönen: kapatan işlev
  w.showPanel = panel => {
    const body = $('.modal-body', m.el);
    panel.classList.add('fx-panel');
    body.classList.add('fx-paneled');
    body.append(panel);
    return () => { panel.remove(); body.classList.remove('fx-paneled'); w.render(); };
  };

  async function stage(body, extra = {}) {
    w.loading++;
    w.render();
    try {
      const res = body instanceof FormData ? await api('/api/stage', { method: 'POST', body }) : await postJSON('/api/stage', body);
      w.desktop = res.desktop;
      const bad = res.files.filter(f => f.error || !spec.kinds.includes(f.kind));
      if (bad.length) toast(bad.map(f => `${f.name}: ${f.error || spec.wrongKind}`).join(' · '), 'error');
      const fresh = res.files.filter(f => !bad.includes(f)).map(f => spec.newRow({ ...f, ...extra, state: '' }));
      if (spec.single) { if (fresh.length) w.rows = [fresh[0]]; }   // yeni dosya eskisinin yerine
      else w.rows.push(...fresh);
    } catch (e) { toast(e.message, 'error'); }
    w.loading--;
    w.render();
    spec.changed?.();
  }

  async function addFiles(list, known = null) {
    if (!list.length) return;
    // Mac uygulamasına bırakılan dosyalar diskteki yollarıyla alınır (kaydetme yeri kaynağın klasörü olabilsin)
    const found = await (known || Promise.all(list.map(droppedPath)));
    const paths = found.filter(Boolean), uploads = list.filter((f, k) => !found[k]);
    if (paths.length) await stage({ paths });
    if (uploads.length) {
      const fd = new FormData();
      uploads.forEach(f => fd.append('files', f, f.name));
      await stage(fd);
    }
  }

  async function pick() {
    if (w.running) return;
    if (!NATIVE) return addFiles(await pickFiles({ accept: spec.accept, multiple: !spec.single }));
    const paths = await nativeAsk('openPanel', { accept: spec.accept, multiple: !spec.single, directory: w.dir });
    if (paths?.length) stage({ paths });
  }

  async function unlock(r, password) {
    let res;
    try { res = await postJSON(`/api/stage/${r.id}/unlock`, { password }); } catch (e) { return toast(e.message, 'error'); }
    if (!res.ok) return toast('Şifre yanlış.', 'error');
    const { ok, ...more } = res;
    Object.assign(r, more, { encrypted: false });
    w.render();
    spec.changed?.();
  }

  function rowHtml(r) {
    const kind = r.kind === 'image' ? ext(r.name).toUpperCase() : FX_KIND[r.kind];
    const meta = [kind, r.pages ? `${r.pages} sayfa` : '', fmtSize(r.size), r.doc ? 'açık belge' : ''].filter(Boolean).join(' · ');
    const res = r.result;
    const state = r.state === 'wait' ? '<div class="fx-state muted">Sırada</div>'
      : r.state === 'run' ? `<div class="fx-state"><span class="spinner sm"></span>${esc(spec.progress)}</div>`
      : r.state === 'err' ? `<div class="fx-state err">${esc(r.error)}</div>`
      : r.state === 'done' && spec.doneHtml ? spec.doneHtml(r)
      : r.state === 'done' ? `<div class="fx-state ok">${icon('check')}<span class="fx-out" title="${esc(r.savedPath || '')}">${esc(r.savedPath
        ? baseName(r.savedPath) : res.name)}</span>${res.note && !spec.noteInBody ? `<span class="muted">· ${esc(res.note)}</span>` : ''}
        ${res.pdf ? '<button class="link-btn small" data-open>Aç</button>' : ''}</div>` : '';
    return `<div class="fx-row ${r.state}" data-id="${r.id}">
      <div class="fx-thumb fx-${r.kind}">${r.thumb ? `<img src="${r.thumb}" alt="">` : `<span class="fx-ext">${esc(ext(r.name).toUpperCase())}</span>`}</div>
      <div class="fx-main">
        <div class="fx-name" title="${esc(r.name)}">${esc(r.name)}</div>
        <div class="muted small">${esc(meta)}</div>
        ${r.encrypted ? `<div class="fx-lock">${icon('lock')}<span>Şifreli PDF</span>
            <input class="input sm" type="password" placeholder="Şifre" autocomplete="off"><button class="btn sm" data-unlock>Aç</button></div>`
          : spec.rowBody(r)}
        ${state}
      </div>
      ${spec.docOnly ? '' : '<button class="x" data-del title="Listeden çıkar">×</button>'}</div>`;
  }

  function bindRow(row, r) {
    const del = $('[data-del]', row);
    if (del) del.onclick = () => {
      if (w.running) return;
      w.rows.splice(w.rows.indexOf(r), 1);
      w.render();
      spec.changed?.();
    };
    const pw = $('.fx-lock input', row);
    if (pw) {
      pw.onkeydown = e => { if (e.key === 'Enter') unlock(r, pw.value); };
      $('[data-unlock]', row).onclick = () => unlock(r, pw.value);
    }
    const open = $('[data-open]', row);
    if (open) open.onclick = () => {
      m.close();
      if (NATIVE && r.savedPath) native({ action: 'openPaths', paths: [r.savedPath] });   // yeni sekmede
      else openOutputInEditor(r.result.id, false);
    };
    if (!r.encrypted) spec.bindRow?.(row, r);
  }

  function renderList() {
    const list = el('fx-list');
    if (!w.rows.length && !w.loading) {
      return w.patch(list, `<div class="drop fx-drop"><div class="drop-icon">${icon('upload')}</div>
        <b>Dosyaları buraya bırakın ya da tıklayıp seçin</b><span class="muted">${esc(spec.emptyHint)}</span></div>`,
      box => { $('.fx-drop', box).onclick = pick; });
    }
    list._html = null;
    const old = new Map($$(':scope > .fx-row[data-id]', list).map(e => [e.dataset.id, e]));
    const nodes = w.rows.map(r => {
      const html = rowHtml(r);
      let row = old.get(r.id);
      if (!row || row._html !== html) {
        const t = document.createElement('template');
        t.innerHTML = html.trim();
        row = t.content.firstElementChild;
        row._html = html;
        bindRow(row, r);
      }
      return row;
    });
    if (w.loading) {
      w.loadingRow ||= Object.assign(document.createElement('div'), { className: 'fx-row fx-loading',
        innerHTML: '<span class="spinner sm"></span><span class="muted">Ekleniyor…</span>' });
      nodes.push(w.loadingRow);
    }
    // Yerinde kalan satırlar taşınmaz: içindeki şifre kutusu yazılırken odağını kaybetmez
    nodes.forEach((n, i) => { if (list.children[i] !== n) list.insertBefore(n, list.children[i] || null); });
    while (list.children.length > nodes.length) list.lastElementChild.remove();
  }

  w.render = () => {
    if (w.closed) return;
    renderList();
    spec.renderTop?.(el('fx-all'));
    const settings = el('fx-settings');
    settings.hidden = !spec.renderSettings || !w.rows.length;
    if (!settings.hidden) spec.renderSettings(settings);
    el('fx-count').textContent = w.rows.length && !spec.single ? `${w.rows.length} dosya` : '';
    el('fx-clear').hidden = !w.rows.length;
    renderSave();
    const run = el('fx-run');
    run.disabled = w.running || w.loading > 0 || !w.rows.some(r => !r.encrypted) || !!spec.blocked?.();
    w.patch(run, `${icon(spec.runIcon)}${esc(spec.runLabel(w.rows))}`);
  };

  function renderSave() {
    const box = el('fx-save');
    box.hidden = !w.rows.length;
    if (box.hidden) return;
    // Açık belge: yeni dosya mı, belgenin kendisi mi
    const how = spec.applyLabel ? `<div class="seg sm fx-how">
        <button type="button" data-how="" class="${w.apply ? '' : 'on'}">Yeni dosya olarak kaydet</button>
        <button type="button" data-how="1" class="${w.apply ? 'on' : ''}">${esc(spec.applyLabel)}</button></div>` : '';
    const bindHow = b => $$('[data-how]', b).forEach(btn => btn.onclick = () => {
      if (w.running || w.apply === !!btn.dataset.how) return;
      w.apply = !!btn.dataset.how;
      w.status('');
      w.render();
    });
    if (w.apply) {
      return w.patch(box, `<div class="fx-save-title">Kaydet</div>${how}<div class="muted small fx-save-hint">${esc(spec.applyHint)}</div>`, bindHow);
    }
    const single = w.rows.length === 1;
    const out = saveName();
    const key = spec.saveAs ? `${w.rows[0].id}:${out.folder}` : single ? 'dosya:' + w.rows[0].id : 'klasör';
    if (key !== nameKey) { nameKey = key; nameTouched = false; }
    if (!nameTouched) name = out.name;
    if (!w.dirTouched) w.dir = w.rows.find(r => r.dir)?.dir || w.desktop;
    w.patch(box, `<div class="fx-save-title">Kaydet</div>${how}
      <div class="fx-save-grid" data-name="${esc(nameTouched ? '' : name)}">
        <label for="fx-name">${out.folder ? 'Klasör adı' : 'Dosya adı'}</label>
        <div class="fx-name-row"><input class="input" id="fx-name" spellcheck="false" autocomplete="off">
          ${out.folder ? '' : `<span class="fx-suffix">.${esc(out.ext)}</span>`}</div>
        <label>Konum</label>
        <div class="fx-dir-row">${NATIVE ? `${icon('folder')}<span class="fx-dir" title="${esc(w.dir)}">${esc(shortPath(w.dir))}</span>
          <button class="btn sm" id="fx-dir">Değiştir…</button>`
          : `<span class="muted small">Dosyalar tarayıcının İndirilenler klasörüne iner${single && !out.folder ? '' : ' (tek ZIP olarak)'}.</span>`}</div>
      </div>
      <div class="fx-keep">${icon('check')}${out.note ? `Asıl dosyanıza dokunulmaz; ${esc(out.note)}.`
        : single ? 'Asıl dosyanıza dokunulmaz; sonuç ayrı bir dosya olarak kaydedilir.'
        : `Asıl dosyalarınıza dokunulmaz; ${w.rows.length} dosyanın sonuçları bu klasörde toplanır.`}</div>
      <div class="muted small fx-save-hint">Aynı adlı dosyanın üzerine yazılmaz; adın sonuna (1), (2) eklenir.</div>`, b => {
      bindHow(b);
      const input = $('#fx-name', b);
      input.value = name;
      input.oninput = () => { name = input.value; nameTouched = true; };
      const change = $('#fx-dir', b);
      if (change) change.onclick = async () => {
        const folder = await nativeAsk('folderPanel', { directory: saveDir(w.dir), message: 'Sonuçların kaydedileceği klasörü seçin' });
        if (folder) { w.dir = folder; w.dirTouched = true; renderSave(); }
      };
    });
  }

  async function run() {
    if (w.running) return;
    const ready = w.rows.filter(r => !r.encrypted);
    let todo = ready.filter(r => r.state !== 'done');
    if (!todo.length) todo = ready;   // hepsi işlenmişti: yeniden
    if (NATIVE && !w.apply && !w.dir) return toast('Kaydedilecek klasörü seçin.', 'error');
    w.running = true;
    todo.forEach(r => { r.state = 'wait'; r.result = null; r.savedPath = ''; });
    for (const [k, r] of todo.entries()) {
      if (w.closed) return;
      r.state = 'run';
      w.render();
      w.status(`<span class="muted">${k + 1} / ${todo.length} · ${esc(spec.progress)}</span>`);
      try {
        r.result = await spec.process(r);
        r.state = 'done';
      } catch (e) { r.error = e.message; r.state = 'err'; }
    }
    if (w.closed) return;
    const done = todo.filter(r => r.state === 'done'), failed = todo.length - done.length;
    if (w.apply) {
      w.running = false;
      done.forEach(r => { r.state = ''; });
      w.render();
      w.status(failed ? `<span class="err">${esc(todo[0].error)}</span>` : '');
      return done.length && spec.finish(done);
    }
    w.status('<span class="muted">Kaydediliyor…</span>');
    let saved = null;
    if (done.length) {
      try { saved = await saveAll(done); } catch (e) { toast(e.message, 'error'); }
    }
    w.running = false;
    w.render();
    const fail = failed ? `<span class="err">${failed} dosya işlenemedi</span>` : '';
    if (!saved) return w.status(fail || '<span class="err">Kaydedilemedi</span>');
    const count = done.reduce((n, r) => n + (spec.outputs ? spec.outputs(r).length : 1), 0);
    w.status(`<span class="ok">${icon('check')}${count} dosya ${NATIVE ? 'kaydedildi' : 'indirildi'}</span>${fail ? ' · ' + fail : ''}
      ${NATIVE && saved.paths.length ? `<button class="btn sm ghost" id="fx-reveal">${icon('folder')}Klasörde göster</button>` : ''}`);
    const reveal = el('fx-reveal');
    if (reveal) reveal.onclick = () => native({ action: 'reveal', path: saved.paths[0] });
  }

  // Tek dosya: verilen adla; birden çok dosya: verilen adlı klasörde. Sayfa resimleri (ZIP) bir klasöre açılır.
  // Kaydet bölümünün adı: tek dosyada dosya adı, birden çok dosyada (ya da çok parçalı sonuçta) klasör adı
  function saveName() {
    if (spec.saveAs) return spec.saveAs(w.rows);
    return w.rows.length === 1 ? spec.outName(w.rows[0]) : { name: spec.folderName, folder: true };
  }

  async function saveAll(done) {
    const out = saveName();
    const intoFolder = spec.saveAs ? out.folder : w.rows.length > 1;
    const given = name.trim() || out.name;
    const outputs = done.flatMap(r => (spec.outputs ? spec.outputs(r) : [r.result]).map(o => [r, o]));
    if (NATIVE) {
      const res = await postJSON('/api/out/save-to', { dir: w.dir, folder: intoFolder ? given : '',
        items: outputs.map(([, o]) => ({ id: o.id, name: intoFolder ? '' : given, unzip: true })) });
      outputs.forEach(([r], k) => { r.savedPath ||= res.paths[k]; });   // satırın ilk sonucu
      return res;
    }
    if (outputs.length === 1) {
      const o = outputs[0][1];
      downloadUrl(o.url, intoFolder ? o.name : `${given}.${ext(o.name)}`);
    } else {
      const zip = await postJSON('/api/out/zip', { ids: outputs.map(([, o]) => o.id) });
      downloadUrl(zip.url, `${given}.zip`);
    }
    return { dir: 'İndirilenler', paths: [] };
  }

  el('fx-add').onclick = pick;
  el('fx-clear').onclick = () => {
    if (w.running) return;
    w.rows = [];
    w.render();
    w.status('');
    spec.changed?.();
  };
  el('fx-run').onclick = run;
  $('[data-x]', m.el).onclick = () => m.close();
  if (!spec.docOnly) {
    const box = $('.modal', m.el);
    box.addEventListener('dragover', e => { e.preventDefault(); box.classList.add('over'); });
    box.addEventListener('dragleave', e => { if (!box.contains(e.relatedTarget)) box.classList.remove('over'); });
    box.addEventListener('drop', e => {
      e.preventDefault(); e.stopPropagation();
      box.classList.remove('over');
      if (!w.running && e.dataTransfer.files.length) addFiles([...e.dataTransfer.files]);
    });
  }
  // doc: açık belge listeye eklenir (uygulanmamış eklemeler önce uygulanır); files: ana sayfaya bırakılanlar
  // where: bırakılan dosyaların diskteki yolları (Mac; bırakıldığı anda istenir, söz olarak)
  w.open = async ({ doc = null, files = [], where = null } = {}) => {
    w.render();
    if (doc) {
      try { await window.Reader?.flush?.(); } catch { }
      await stage({ sid: doc.id }, { doc: true });
    }
    await addFiles(files, where);
  };
  return w;
}

// Format Değiştir: her dosyanın hedef biçimi kendi satırında seçilir; türler karışık olabilir
function convertDialog(opts = {}) {
  let last = {};   // her türde en son seçilen hedef
  try { last = JSON.parse(localStorage.getItem('pdfstudyo.format') || '{}') || {}; } catch { }
  const remember = (kind, id) => {
    last[kind] = id;
    try { localStorage.setItem('pdfstudyo.format', JSON.stringify(last)); } catch { }
  };
  const targetOf = r => FX_TARGETS[r.kind].find(t => t.id === r.target) || FX_TARGETS[r.kind][0];
  const optValue = (r, o) => r.opts[o.name] ?? o.value ?? o.choices[0][0];
  const choose = (r, id) => { if (r.target !== id) { r.target = id; r.state = ''; } };

  const w = fileWindow({
    title: 'Format Değiştir', kinds: Object.keys(FX_TARGETS), accept: FX_ACCEPT, wrongKind: 'bu dosya türü dönüştürülemez',
    emptyHint: 'PDF, Word, Excel, UDF, resim ve TIFF; türleri karışık olabilir', folderName: 'Dönüştürülmüş',
    progress: 'Dönüştürülüyor…', runIcon: 'convert',
    runLabel: rows => (rows.length && rows.every(r => r.state === 'done' || r.encrypted) ? 'Yeniden dönüştür' : 'Dönüştür'),
    newRow: f => ({ ...f, opts: {},
      target: FX_TARGETS[f.kind].some(t => t.id === last[f.kind]) ? last[f.kind] : FX_TARGETS[f.kind][0].id }),
    rowBody: r => {
      const t = targetOf(r);
      const opts = (t.opts?.() || []).map(o => `<div class="seg sm" data-o="${o.name}">${o.choices.map(([v, label]) =>
        `<button type="button" data-v="${esc(v)}" class="${optValue(r, o) === v ? 'on' : ''}">${esc(label)}</button>`).join('')}</div>`).join('');
      const missing = t.app && !state.engines[t.app];
      const note = missing ? (state.engines.libreoffice ? `${FX_APP[t.app]} bulunamadı; LibreOffice kullanılacak.`
        : `Bu dönüştürme için ${FX_APP[t.app]} ya da LibreOffice kurulu olmalı.`) : t.note;
      return `<div class="fx-target"><span class="fx-arrow">→</span><div class="seg sm fx-seg">${FX_TARGETS[r.kind].map(x =>
        `<button type="button" data-t="${x.id}" class="${x.id === t.id ? 'on' : ''}">${esc(x.label)}</button>`).join('')}</div>${opts}</div>
        <div class="fx-note ${missing && !state.engines.libreoffice ? 'warn' : ''}">${esc(note)}</div>`;
    },
    bindRow: (row, r) => {
      $$('[data-t]', row).forEach(b => b.onclick = () => {
        if (w.running) return;
        choose(r, b.dataset.t);
        remember(r.kind, r.target);
        w.render();
      });
      $$('[data-o]', row).forEach(seg => $$('button', seg).forEach(b => b.onclick = () => {
        if (w.running) return;
        r.opts[seg.dataset.o] = b.dataset.v;
        r.state = '';
        w.render();
      }));
    },
    // Hepsi aynı türdeyse hedef tek seferde seçilebilir
    renderTop: box => {
      const kinds = new Set(w.rows.map(r => r.kind));
      const kind = kinds.size === 1 && w.rows.length > 1 ? w.rows[0].kind : null;
      w.patch(box, kind && FX_TARGETS[kind].length > 1 ? `<span class="muted small">Hepsini:</span><div class="seg sm">${FX_TARGETS[kind].map(x =>
        `<button type="button" data-t="${x.id}" class="${w.rows.every(r => r.target === x.id) ? 'on' : ''}">${esc(x.label)}</button>`).join('')}</div>` : '',
      b => $$('[data-t]', b).forEach(btn => btn.onclick = () => {
        if (w.running) return;
        w.rows.forEach(r => choose(r, btn.dataset.t));
        remember(kind, btn.dataset.t);
        w.render();
      }));
    },
    outName: r => {
      const t = targetOf(r);
      return { name: w.stemOf(r.name), ext: t.ext, folder: !!(t.pages && r.pages > 1) };   // çok sayfalı belgenin resimleri bir klasörde
    },
    process: async r => {
      const t = targetOf(r);
      const fd = new FormData();
      fd.append('staged', r.id);
      for (const [key, v] of Object.entries(t.form || {})) fd.append(key, v);
      for (const o of t.opts?.() || []) fd.append(o.name, optValue(r, o));
      const res = (await api(t.endpoint, { method: 'POST', body: fd })).files[0];
      if (res.error) throw new Error(res.error);
      return res;
    },
  });
  w.open(opts);
}

