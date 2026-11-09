/* Koç PDF Pro — belgeyi açma, kaydetme, paylaşma; önceki sürümler ve otomatik kurtarma. */
'use strict';

// ------------------------------------------------------------------ açma ve kaydetme
// Mac uygulamasında macOS'un kendi pencereleri kullanılır (sonuç PDFSTUDYO_reply ile döner);
// Windows'ta (Edge) tarayıcının dosya sistemi erişimi; ikisi de yoksa klasik indirme.
const nativeReplies = new Map();
let nativeSeq = 0;
function nativeAsk(action, args = {}) {
  if (SHELL) return Promise.resolve(SHELL.ask(TAB_ID, { action, ...args })).then(v => v ?? null, () => null);
  return new Promise(resolve => {
    const id = ++nativeSeq;
    nativeReplies.set(id, resolve);
    native({ action, id, ...args });
  });
}
window.PDFSTUDYO_reply = (id, value) => {
  const done = nativeReplies.get(id);
  nativeReplies.delete(id);
  done?.(value);
};

const FS_API = !NATIVE && 'showSaveFilePicker' in window;
const docHandles = new Map();   // Windows: oturum → açılan/kaydedilen dosya (Kaydet onun üzerine yazar)
const dirOf = p => (p ? p.replace(/[\\/][^\\/]*$/, '') : '');
// Kaydetme penceresinin önce açacağı klasör (Ayarlar › Kaydetme): belgenin klasörü, en son kullanılan ya da Masaüstü.
// Boş verilince pencere sahibi en son kullanılan klasörü açar (o da yoksa Masaüstü).
function saveDir(docDir) {
  const how = state.settings.saveFolder;
  return how === 'desktop' ? state.desktop : how === 'last' ? '' : docDir || '';
}
const baseName = p => p.split(/[\\/]/).pop();
const shortPath = p => p.replace(/^\/Users\/[^/]+/, '~');
const MIME = { pdf: 'application/pdf', docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', zip: 'application/zip',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  png: 'image/png', jpg: 'image/jpeg', tif: 'image/tiff' };
const pickerTypes = name => {
  const e = ext(name);
  return [{ description: e.toUpperCase() + ' dosyası', accept: { [MIME[e] || 'application/octet-stream']: ['.' + e] } }];
};

async function writeToHandle(handle, url) {
  const opts = { mode: 'readwrite' };
  if ((await handle.queryPermission?.(opts)) !== 'granted' && (await handle.requestPermission?.(opts)) !== 'granted') {
    throw new Error('Dosyaya yazma izni verilmedi.');
  }
  const res = await fetch(url);
  if (!res.ok) {   // sunucu hata verdiyse dosyaya hiçbir şey yazılmaz, önceki hâli kalır
    const data = (res.headers.get('content-type') || '').includes('application/json') ? await res.json() : null;
    throw new Error(data?.error || `Sunucu hatası (${res.status})`);
  }
  const blob = await res.blob();
  const w = await handle.createWritable();
  await w.write(blob);
  await w.close();
}

// Pencereye bırakılan ya da sayfanın dosya seçme penceresinde seçilen dosyanın diskteki yolu (Mac uygulaması bildirir)
async function droppedPath(file) {
  if (HOST !== 'mac' || !file) return null;
  for (let i = 0; i < 6; i++) {
    const d = window.PDFSTUDYO_dropPaths;
    const p = d && Date.now() - d.t < 3000 && d.paths.find(x => baseName(x) === file.name);
    if (p) return p;
    await new Promise(r => setTimeout(r, 30));
  }
  return null;
}

// Düzenleyici/okuyucu için belge seçme: {path} (Mac), {file, handle} (Windows) ya da {file}
async function pickDocument() {
  if (NATIVE) {
    const paths = await nativeAsk('openPanel', { accept: '.pdf,.udf' });
    return paths?.[0] ? { path: paths[0] } : null;
  }
  if ('showOpenFilePicker' in window) {
    try {
      const [handle] = await showOpenFilePicker({ types: [{ description: 'PDF ya da UDF', accept: { 'application/pdf': ['.pdf'], 'application/octet-stream': ['.udf'] } }] });
      return { file: await handle.getFile(), handle };
    } catch { return null; }
  }
  const [file] = await pickFiles({ accept: '.pdf,.udf' });
  return file ? { file } : null;
}

// Bırakılan belge: dosya + (varsa) diskteki yolu ya da dosya tutamağı
function droppedDocument(e) {
  const file = e.dataTransfer.files[0];
  const item = e.dataTransfer.items?.[0];
  const handle = item?.kind === 'file' && item.getAsFileSystemHandle ? item.getAsFileSystemHandle().catch(() => null) : null;
  return (async () => ({ file, path: await droppedPath(file), handle: (await handle)?.kind === 'file' ? await handle : null }))();
}

function setupDocDrop(el, onDoc) {
  el.addEventListener('click', async () => { const d = await pickDocument(); if (d) onDoc(d); });
  el.addEventListener('dragover', e => { e.preventDefault(); el.classList.add('over'); });
  el.addEventListener('dragleave', () => el.classList.remove('over'));
  el.addEventListener('drop', async e => {
    e.preventDefault(); el.classList.remove('over');
    if (e.dataTransfer.files.length) onDoc(await droppedDocument(e));
  });
}

function askPassword(name, wrong) {
  return new Promise(resolve => {
    let done = false;
    const m = modal({
      title: 'Şifreli PDF',
      body: `<p style="margin:0 0 12px">“${esc(name)}” şifreyle korunuyor.</p>
        ${wrong ? '<div class="note warn" style="margin:0 0 12px">Şifre yanlış, tekrar deneyin.</div>' : ''}
        <input class="input" type="password" id="pw-ask" placeholder="Şifre" autocomplete="off">`,
      foot: `<button class="btn" data-x>Vazgeç</button><button class="btn primary" id="pw-ok">Aç</button>`,
    });
    const finish = v => { if (done) return; done = true; m.close(); resolve(v); };
    const input = $('#pw-ask', m.el);
    input.focus();
    input.onkeydown = e => { if (e.key === 'Enter') finish(input.value); };
    $('#pw-ok', m.el).onclick = () => finish(input.value);
    $('[data-x]', m.el).onclick = () => finish(null);
    // Esc / arka plana tıklama ile kapanırsa
    new MutationObserver((_, obs) => { if (!m.el.isConnected) { obs.disconnect(); finish(null); } })
      .observe($('#modal-root'), { childList: true });
  });
}

// Belgeyi sunucuda açar; şifre gerekirse sorup yeniden dener. Vazgeçilirse ya da hata olursa null.
async function openDocument({ file, path, handle }) {
  const name = path ? baseName(path) : file.name;
  if (!['pdf', 'udf'].includes(ext(name))) { toast('Yalnızca PDF ve UDF dosyaları açılır. Word belgelerini önce PDF\'e dönüştürün.', 'error'); return null; }
  let password;
  for (;;) {
    busy(true, 'PDF açılıyor…');
    try {
      let info;
      if (path) info = await postJSON('/api/edit/open', { path, password });
      else {
        const fd = new FormData();
        fd.append('files', file, file.name);
        if (password) fd.append('password', password);
        info = await api('/api/edit/open', { method: 'POST', body: fd });
      }
      if (handle) docHandles.set(info.id, handle);
      return info;
    } catch (e) {
      if (!e.data?.needs_password) { toast(e.message, 'error'); return null; }
    } finally { busy(false); }
    const wrong = password != null;
    password = await askPassword(name, wrong);
    if (password == null) return null;
  }
}

const docFileName = info => (ext(info.name) === 'pdf' ? info.name : info.name.replace(/\.[^.]*$/, '') + '.pdf');

// Kaydet (asNew=false): açılan dosyanın üzerine; dosya bilinmiyorsa Farklı Kaydet'e döner.
// Farklı Kaydet: yer ve ad seçilir. Dönen değer güncel oturum bilgisi; vazgeçilirse null.
async function saveDocument(info, asNew = false) {
  const sid = info.id;
  const handle = docHandles.get(sid);
  let name = docFileName(info);
  if (info.redacted) {
    // Karartılmış belge özgün dosyanın üzerine yazılırsa karartılmamış hâli yalnızca yedekte kalır: ayrı dosya önerilir
    name = name.replace(/(_KVKK)?\.pdf$/i, '_KVKK.pdf');
    if (!asNew && (handle || info.can_save_source)) {
      const how = await askChoice({
        title: 'Karartılmış belgeyi kaydet',
        body: `<p style="margin-top:0">Bu belgede karartma yaptınız. <b>${esc(info.name)}</b> dosyasının üzerine kaydederseniz
          karartılmamış hâli kaybolur; yalnızca uygulamanın yedeklerinde kalır.</p>
          <p class="muted small" style="margin-bottom:0">Önerilen: karartılmış hâli <b>${esc(name)}</b> adıyla ayrı bir dosya olarak
          kaydedin; özgün dosya olduğu gibi kalır.</p>`,
        choices: [{ id: '', label: 'Vazgeç' }, { id: 'overwrite', label: 'Üzerine yaz' },
          { id: 'copy', label: 'Ayrı dosya olarak kaydet', primary: true, icon: 'save' }],
      });
      if (!how) return null;
      asNew = how === 'copy';
    }
  }
  if (!asNew && handle) {
    await withBusy('Kaydediliyor…', () => writeToHandle(handle, `/api/edit/${sid}/download`));
    toast('Kaydedildi: ' + handle.name, 'ok');
    return postJSON(`/api/edit/${sid}/mark-saved`, { name: handle.name });
  }
  if (!asNew && info.can_save_source) {
    const r = await saveOverSource(info);
    if (r !== 'saveas') return r;   // kaydedildi ya da vazgeçildi
    asNew = true;
  }
  if (NATIVE) {
    const path = await nativeAsk('savePanel', { name, directory: saveDir(dirOf(info.path)), types: ['pdf'] });
    if (!path) return null;
    const r = await withBusy('Kaydediliyor…', () => postJSON(`/api/edit/${sid}/save`, { path }));
    toast('Kaydedildi: ' + shortPath(r.path), 'ok');
    return r;
  }
  if (FS_API) {
    let h;
    try { h = await showSaveFilePicker({ suggestedName: name, types: pickerTypes(name) }); } catch { return null; }
    await withBusy('Kaydediliyor…', () => writeToHandle(h, `/api/edit/${sid}/download`));
    docHandles.set(sid, h);
    toast('Kaydedildi: ' + h.name, 'ok');
    return postJSON(`/api/edit/${sid}/mark-saved`, { name: h.name });
  }
  // Yalnızca tarayıcı (yer seçilemiyor): belge indirilir. İndirmenin bitip bitmediği sayfadan anlaşılamaz; kullanıcı
  // onaylamadan kaydedilmiş sayılmaz (iptal ya da hata olursa "kaydedilmedi" uyarısı ve kurtarma korunur)
  downloadUrl(`/api/edit/${sid}/download`);
  const done = await askChoice({
    title: 'İndirme tamamlandı mı?',
    body: `<p style="margin-top:0">Belge tarayıcınızın indirilenler klasörüne indiriliyor. İndirilenler listesinde dosyanın
      tamamlandığını görünce <b>İndirildi</b> deyin.</p>
      <p class="muted small" style="margin-bottom:0">İndirme iptal edildiyse ya da başarısız olduysa <b>İndirilmedi</b> deyin:
      belge kaydedilmemiş sayılır, değişiklikleriniz kaybolmaz.</p>`,
    choices: [{ id: '', label: 'İndirilmedi' }, { id: 'ok', label: 'İndirildi', primary: true, icon: 'save' }],
  });
  if (!done) return null;
  return postJSON(`/api/edit/${sid}/mark-saved`, {});
}

// Farklı Kaydet: önce biçim seçilir. PDF: belge seçilen dosyaya kaydedilir (bundan sonra Kaydet oraya yazar).
// Word, UDF ve resim: kopya olarak kaydedilir, açık belge değişmez. Dönen: oturum bilgisi (PDF) ya da null.
const SAVE_FORMATS = [
  { id: 'pdf', icon: 'file', label: 'PDF', hint: 'Belge seçtiğiniz yere kaydedilir' },
  { id: 'docx', icon: 'pdfword', label: 'Word (.docx)', hint: 'Düzenlenebilir Word belgesi', tool: 'pdf-to-word' },
  { id: 'xlsx', icon: 'excel', label: 'Excel (.xlsx)', hint: 'Tablolar sütunlarıyla, öbür satırlar sırasıyla', tool: 'pdf-to-excel',
    form: { content: 'all' } },
  { id: 'udf', icon: 'udf', label: 'UDF (UYAP)', hint: 'UYAP Doküman Editörü belgesi', tool: 'to-udf' },
  { id: 'png', icon: 'toimg', label: 'Resim (PNG)', hint: 'Keskin; çok sayfa ZIP olarak', tool: 'pdf-to-images', form: { format: 'png', dpi: 200 } },
  { id: 'jpg', icon: 'toimg', label: 'Resim (JPG)', hint: 'Küçük dosya; çok sayfa ZIP olarak', tool: 'pdf-to-images', form: { format: 'jpg', dpi: 200 } },
  { id: 'tiff', icon: 'toimg', label: 'TIFF', hint: 'Bütün sayfalar tek dosyada (gri, 200 dpi)', tool: 'pdf-to-images', form: { format: 'tiff', dpi: 200, color: 'gri' } },
];
let lastSaveFormat = 'pdf';

function pickSaveFormat(info) {
  return new Promise(resolve => {
    let chosen = null, current = lastSaveFormat;
    const m = modal({
      title: 'Farklı Kaydet', width: 560, onClose: () => resolve(chosen),
      body: `<p class="muted small" style="margin:0 0 12px">${esc(docFileName(info))} hangi biçimde kaydedilsin? Word, UDF ve resim
          kopya olarak kaydedilir; açık belge değişmez.</p>
        <div class="choice-grid sa-formats">${SAVE_FORMATS.map(f => `<button class="choice" data-fmt="${f.id}">
          <span class="tool-icon" style="--c:var(--c-convert)">${icon(f.icon)}</span><span><b>${esc(f.label)}</b><br>
          <span class="muted small">${esc(f.hint)}</span></span></button>`).join('')}</div>
        <div class="sa-opts" id="sa-opts">
          <b class="small">PDF seçenekleri</b>
          ${[['flatten', 'Notları ve işaretleri düzleştir', 'vurgular, notlar ve form alanları sayfaya işlenir; karşı taraf silemez (notların açıklama metni kalmaz)'],
             ['shrink', 'Küçült', 'e-posta ve UYAP için daha küçük dosya (resimler sıkıştırılır)'],
             ['clean_meta', 'Belge bilgilerini temizle', 'yazar, başlık, konu, oluşturan program'],
             ['encrypt', 'Şifrele', 'açmak için şifre sorulur; yazdırılabilir, metni kopyalanamaz']].map(([id, label, hint]) =>
            `<label class="check"><input type="checkbox" data-opt="${id}"><span>${label} <span class="muted small">— ${hint}</span></span></label>`).join('')}
          <div class="sa-pw" id="sa-pw" hidden><input class="input" type="password" id="sa-pw1" placeholder="Şifre" autocomplete="new-password">
            <input class="input" type="password" id="sa-pw2" placeholder="Şifre (tekrar)" autocomplete="new-password"></div>
          <p class="muted small" id="sa-copy" hidden>Seçenekli PDF kopya olarak kaydedilir; açık belge değişmez.${info.signed
            ? ' Kopyada e-imza geçersiz olur.' : ''}</p>
        </div>`,
      foot: `<button class="btn" data-x>Vazgeç</button><button class="btn primary" id="sa-go">${icon('download')}Kaydet…</button>`,
    });
    const opt = id => $(`[data-opt="${id}"]`, m.el).checked;
    const mark = () => {
      $$('[data-fmt]', m.el).forEach(b => b.classList.toggle('on', b.dataset.fmt === current));
      $('#sa-opts', m.el).hidden = current !== 'pdf';
      $('#sa-pw', m.el).hidden = !opt('encrypt');
      $('#sa-copy', m.el).hidden = !$$('[data-opt]', m.el).some(c => c.checked);
    };
    const go = () => {
      let opts = null;
      if (current === 'pdf' && $$('[data-opt]', m.el).some(c => c.checked)) {
        const pw = $('#sa-pw1', m.el).value;
        if (opt('encrypt') && !pw) return toast('Şifreyi girin.', 'error');
        if (opt('encrypt') && pw !== $('#sa-pw2', m.el).value) return toast('İki şifre aynı değil.', 'error');
        opts = { flatten: opt('flatten'), shrink: opt('shrink'), clean_meta: opt('clean_meta'), password: opt('encrypt') ? pw : '' };
      }
      chosen = { fmt: SAVE_FORMATS.find(f => f.id === current), opts };
      lastSaveFormat = current;
      m.close();
    };
    $$('[data-fmt]', m.el).forEach(b => { b.onclick = () => { current = b.dataset.fmt; mark(); }; b.ondblclick = go; });
    $$('[data-opt]', m.el).forEach(c => c.onchange = () => { mark(); if (c.dataset.opt === 'encrypt' && c.checked) $('#sa-pw1', m.el).focus(); });
    $('[data-x]', m.el).onclick = m.close;
    $('#sa-go', m.el).onclick = go;
    m.el.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); go(); } });
    mark();
    $(`[data-fmt="${current}"]`, m.el).focus();
  });
}

async function saveAs(info) {
  const pick = await pickSaveFormat(info);
  if (!pick) return null;
  const { fmt, opts } = pick;
  if (fmt.id === 'pdf' && !opts) return saveDocument(info, true);
  let out;
  try {
    if (opts) {   // seçenekli PDF kopyası: adı ne yapıldığını söyler
      const tags = [opts.flatten && 'düzleştirilmiş', opts.shrink && 'küçültülmüş', opts.password && 'şifreli'].filter(Boolean);
      let name = docFileName(info);
      if (info.redacted) name = name.replace(/(_KVKK)?\.pdf$/i, '_KVKK.pdf');
      name = name.replace(/\.pdf$/i, ` (${tags.join(', ') || 'bilgileri temizlenmiş'}).pdf`);
      out = await withBusy('Hazırlanıyor…', () => postJSON(`/api/edit/${info.id}/export`, { ...opts, name }));
    } else {
      const fd = new FormData();
      Object.entries(fmt.form || {}).forEach(([k, v]) => fd.append(k, v));
      const data = await withBusy('Dönüştürülüyor…', () => api(`/api/edit/${info.id}/tool/${fmt.tool}`, { method: 'POST', body: fd }));
      out = data.files?.[0];
    }
  } catch { return null; }
  if (!out || out.error) { toast(out?.error || 'Dönüştürülemedi.', 'error'); return null; }
  const where = await saveOutput(out, dirOf(info.path));
  if (where) toast(`Kopya kaydedildi: ${shortPath(where)}${out.note ? ' · ' + out.note : ''}`, 'ok');
  return null;
}

// Kaydet: açılan dosyanın üzerine. Dosya bu arada başka bir uygulamada değiştirilmiş ya da taşınmışsa sorulur:
// üzerine yaz / Farklı Kaydet / vazgeç. Dönen: güncel oturum bilgisi, 'saveas' ya da null.
async function saveOverSource(info, force = false) {
  let r;
  busy(true, 'Kaydediliyor…');
  try { r = await postJSON(`/api/edit/${info.id}/save`, force ? { force: true } : {}); }
  catch (e) {
    busy(false);
    const conflict = e.data?.conflict;
    if (!conflict) { toast(e.message, 'error'); throw e; }
    const missing = conflict === 'missing';
    const how = await askChoice({
      title: missing ? 'Dosya bulunamadı' : 'Dosya başka bir yerde değiştirilmiş',
      body: missing
        ? `<p style="margin-top:0"><b>${esc(info.name)}</b> açtığınız yerde artık yok; taşınmış, adı değiştirilmiş ya da silinmiş
            olabilir.</p><p class="muted small" style="margin-bottom:0">Farklı Kaydet ile yeni bir yer seçebilir ya da dosyayı
            eski yerinde yeniden oluşturabilirsiniz.</p>`
        : `<p style="margin-top:0"><b>${esc(info.name)}</b>, siz çalışırken başka bir uygulamada değiştirilmiş. Üzerine yazarsanız
            o değişiklikler bu dosyada kalmaz.</p><p class="muted small" style="margin-bottom:0">Dosyanın o hâli yedeklenir;
            gerekirse Önceki sürümler'den dönebilirsiniz.</p>`,
      choices: [{ id: '', label: 'Vazgeç' }, { id: 'force', label: missing ? 'Eski yerine kaydet' : 'Üzerine yaz' },
        { id: 'saveas', label: 'Farklı Kaydet…', primary: true, icon: 'saveas' }],
    });
    return how === 'force' ? saveOverSource(info, true) : how || null;
  } finally { busy(false); }
  toast('Kaydedildi: ' + r.name, 'ok');
  return r;
}

// Bir araç çıktısını kaydeder: kaydetme penceresinde seçilen yere. Dönen: kaydedilen yol/ad ya da null.
async function saveOutput(r, dir = '') {
  if (NATIVE) {
    const path = await nativeAsk('savePanel', { name: r.name, directory: saveDir(dir), types: [ext(r.name)] });
    if (!path) return null;
    return (await withBusy('Kaydediliyor…', () => postJSON(`/api/out/${r.id}/save`, { path }))).path;
  }
  if (FS_API) {
    let h;
    try { h = await showSaveFilePicker({ suggestedName: r.name, types: pickerTypes(r.name) }); } catch { return null; }
    await withBusy('Kaydediliyor…', () => writeToHandle(h, r.url));
    return h.name;
  }
  downloadUrl(r.url, r.name);
  return r.name;
}

// Birden çok çıktı: bir klasör seçilir, hepsi oraya kaydedilir. Dönen: {dir, paths} ya da null.
async function saveOutputs(list, dir = '') {
  if (NATIVE) {
    const folder = await nativeAsk('folderPanel', { directory: saveDir(dir) });
    if (!folder) return null;
    return withBusy('Kaydediliyor…', () => postJSON('/api/out/save-all', { ids: list.map(r => r.id), dir: folder }));
  }
  if ('showDirectoryPicker' in window) {
    let d;
    try { d = await showDirectoryPicker({ mode: 'readwrite' }); } catch { return null; }
    const paths = [];
    await withBusy('Kaydediliyor…', async () => {
      for (const r of list) {
        let name = r.name;
        for (let k = 1; await d.getFileHandle(name).then(() => true, () => false); k++) name = r.name.replace(/(\.[^.]*)?$/, ` (${k})$1`);
        await writeToHandle(await d.getFileHandle(name, { create: true }), r.url);
        paths.push(name);
      }
    });
    return { dir: d.name, paths };
  }
  const zip = await withBusy('ZIP hazırlanıyor…', () => postJSON('/api/out/zip', { ids: list.map(r => r.id) }));
  downloadUrl(zip.url, zip.name);
  return { dir: 'İndirilenler', paths: [zip.name] };
}

// Paylaş: Mac'te macOS'un paylaşım menüsü (Mail, Mesajlar, AirDrop…), Windows'ta Edge'in paylaşım penceresi.
// Belgede kaydedilmemiş değişiklik varsa ekrandaki hâli paylaşılır.
const canShare = () => HOST === 'mac' || !!navigator.canShare;
const SHARE_HINT = HOST === 'mac' ? 'Paylaş: Mail, Mesajlar, AirDrop…' : 'Paylaş: e-posta ve diğer uygulamalar';
// PDF'i dosya olarak panoya kopyalar: Finder'a, e-postaya ya da UYAP'ın yükleme alanına ⌘V ile yapıştırılır.
// Belgenin ekrandaki hâli kopyalanır (değişiklik yoksa dosyanın kendisi). Yalnız yerel uygulamada.
const COPY_FILE_HINT = "PDF'i dosya olarak kopyala: Finder'a, e-postaya ya da UYAP'a ⌘V ile yapıştırın";

async function copyDocumentFile(sid) {
  let path;
  try { path = (await withBusy('Hazırlanıyor…', () => postJSON('/api/share', { sid }))).path; } catch { return; }
  const ok = await Promise.race([nativeAsk('copyFile', { path }), new Promise(res => setTimeout(() => res(null), 2000))]);
  if (ok) toast(`${baseName(path)} panoya kopyalandı. Finder'a, e-postaya ya da UYAP'a ⌘V ile yapıştırabilirsiniz.`, 'ok');
  else toast('PDF panoya kopyalanamadı.', 'error');
}

async function shareFile({ sid, outId, name, anchor }) {
  let prepared;
  try {
    prepared = await withBusy('Paylaşım hazırlanıyor…', async () => HOST === 'mac'
      ? (await postJSON('/api/share', sid ? { sid } : { out_id: outId })).path
      : (await fetch(sid ? `/api/edit/${sid}/download` : `/api/out/${outId}`)).blob());
  } catch { return; /* hata mesajı gösterildi */ }
  if (HOST === 'mac') {
    const r = anchor?.isConnected ? anchor.getBoundingClientRect() : null;
    return native({ action: 'share', path: prepared, rect: r ? { x: r.left, y: r.top, w: r.width, h: r.height } : null });
  }
  const file = new File([prepared], name, { type: prepared.type || 'application/pdf' });
  if (!navigator.canShare?.({ files: [file] })) return toast('Bu bilgisayarda paylaşım desteklenmiyor; dosyayı kaydedip e-postaya ekleyebilirsiniz.', 'error');
  try { await navigator.share({ files: [file], title: name }); }
  catch (e) { if (e?.name !== 'AbortError') toast('Paylaşılamadı: ' + e.message, 'error'); }
}

// ------------------------------------------------------------------ önceki sürümler
// Uygulama bir dosyanın üzerine kaydederken eski hâlini yedekler (son 10 yedek, 60 gün; Ayarlar › Kaydetme). Bu pencere açık dosyanın
// yedeklerini listeler: "Aç" yedeği ayrı bir sekmede kopya olarak açar, "Geri yükle" dosyayı o hâline döndürür.
// onRestored: geri yüklenen dosya yeniden açılsın diye (düzenleyici / okuyucu).
async function versionsDialog({ info, unsaved, onRestored }) {
  if (!info?.path) return toast('Önceki sürümler yalnızca diskteki bir dosyadan açılan belgelerde var.', 'error');
  let items;
  try { items = (await api(`/api/backups?path=${encodeURIComponent(info.path)}`)).items; } catch { return; }
  const kb = n => (n / 1024 > 1024 ? (n / 1048576).toLocaleString('tr-TR', { maximumFractionDigits: 1 }) + ' MB'
    : Math.ceil(n / 1024) + ' KB');
  const m = modal({
    title: 'Önceki sürümler', width: 560,
    body: `<p class="muted small" style="margin:0 0 12px">${esc(baseName(info.path))} dosyasının üzerine her kaydedişte eski hâli
        yedeklenir; son ${state.settings.backupKeep} yedek ${daysText(state.settings.backupDays)} saklanır.</p>
      ${items.length ? `<div class="vr-list">${items.map((it, k) => `<div class="vr-row">
          <span class="vr-time">${icon('history')}<b>${esc(it.time)}</b><span class="muted small">${kb(it.size)}</span></span>
          <button class="btn sm" data-open="${k}">Aç</button><button class="btn sm" data-restore="${k}">Geri yükle</button></div>`).join('')}</div>`
        : '<p class="muted">Bu dosyanın henüz yedeği yok. Dosyanın üzerine kaydettiğinizde eski hâli burada görünür.</p>'}`,
    foot: '<button class="btn" data-x>Kapat</button>',
  });
  $('[data-x]', m.el).onclick = m.close;
  $$('[data-open]', m.el).forEach(b => b.onclick = () => {
    const it = items[+b.dataset.open];
    m.close();
    if (NATIVE) native({ action: 'openPaths', paths: [it.path] });   // yeni sekmede, kopya olarak
    else window.PDFSTUDYO_openPaths?.([it.path]);
  });
  $$('[data-restore]', m.el).forEach(b => b.onclick = async () => {
    const it = items[+b.dataset.restore];
    const ok = await askChoice({
      title: 'Yedeği geri yükle',
      body: `<p style="margin-top:0"><b>${esc(baseName(info.path))}</b> dosyası <b>${esc(it.time)}</b> hâline döndürülsün mü?</p>
        <p class="muted small" style="margin-bottom:0">Dosyanın şimdiki hâli de yedeklenir; fikrinizi değiştirirseniz buradan geri
        dönebilirsiniz.${unsaved ? ' <b>Kaydedilmemiş değişiklikleriniz kaybolur.</b>' : ''}</p>`,
      choices: [{ id: '', label: 'Vazgeç' }, { id: 'yes', label: 'Geri yükle', primary: true, icon: 'history' }],
    });
    if (!ok) return;
    try { await withBusy('Geri yükleniyor…', () => postJSON('/api/backups/restore', { path: info.path, id: it.id })); } catch { return; }
    m.close();
    toast(`${baseName(info.path)}, ${it.time} hâline döndürüldü.`, 'ok');
    onRestored?.();
  });
}

// ------------------------------------------------------------------ otomatik kurtarma
// Uygulama beklenmedik şekilde kapandıysa kaydedilmemiş değişikliği olan belgeler kenar çubuğunda listelenir;
// açılışta ilk sekmede pencere kendiliğinden açılır.
async function checkRecovery(first = true) {
  let r;
  try { r = await api(`/api/recover${first ? '?ilk=1' : ''}`); } catch { return; }
  if (strip.recover !== r.items.length) { strip.recover = r.items.length; renderTabStrip(); }
  if (r.items.length && r.first) recoverDialog(r.items);
}

async function recoverDialog(items) {
  if (!items) { try { items = (await api('/api/recover')).items; } catch { return; } }
  if (!items.length) return checkRecovery(false);
  const m = modal({
    title: 'Kaydedilmemiş değişiklikler', width: 580,
    body: `<p style="margin-top:0">Koç PDF Pro geçen sefer beklenmedik şekilde kapandı ya da bu belgeler kaydedilmeden
        kapatıldı. Kaydedilmemiş değişiklikleri açıp kaydedebilirsiniz.</p>
      <div class="vr-list">${items.map((it, k) => `<div class="vr-row">
          <span class="vr-time">${icon('file')}<span><b>${esc(it.name)}</b><br><span class="muted small">Son değişiklik: ${esc(it.time)}${it.source
            ? ` · ${esc(shortPath(dirOf(it.source)))}` : ''}</span></span></span>
          <button class="btn sm primary" data-open="${k}">Aç</button><button class="btn sm" data-del="${k}">Sil</button></div>`).join('')}</div>
      <p class="muted small" style="margin-bottom:0">Açmadığınız belgeler ${daysText(state.settings.recoverDays)} saklanır, sonra silinir.</p>`,
    foot: `<button class="btn" data-delall>Hepsini sil</button><button class="btn" data-x>Sonra</button>`,
    onClose: () => checkRecovery(false),
  });
  $('[data-x]', m.el).onclick = m.close;
  const discard = async list => {
    const ok = await askChoice({
      title: 'Değişiklikleri sil',
      body: `<p style="margin:0">${list.length > 1 ? `${list.length} belgedeki` : `<b>${esc(list[0].name)}</b> belgesindeki`}
        kaydedilmemiş değişiklikler silinsin mi? Bu geri alınamaz; diskteki dosyalara dokunulmaz.</p>`,
      choices: [{ id: '', label: 'Vazgeç' }, { id: 'yes', label: 'Sil', primary: true }],
    });
    if (!ok) return;
    for (const it of list) { try { await postJSON(`/api/recover/${it.id}/discard`); } catch { } }
    m.close();
  };
  $$('[data-del]', m.el).forEach(b => b.onclick = () => discard([items[+b.dataset.del]]));
  $('[data-delall]', m.el).onclick = () => discard(items);
  $$('[data-open]', m.el).forEach(b => b.onclick = async () => {
    if (window.Reader?.hasDoc?.()) {
      return toast('Bu sekmede açık bir belge var. Kurtarılan belgeyi açmak için yeni bir sekme açın (⌘T).', 'error');
    }
    let info;
    try { info = await withBusy('Belge açılıyor…', () => postJSON(`/api/recover/${items[+b.dataset.open].id}`)); } catch { return; }
    m.close();
    window.Reader.unmount?.();
    window.Reader.useSession(info);
    if (location.hash === '#/reader') route(); else location.hash = '#/reader';
    toast('Belge kurtarıldı. Değişiklikleri korumak için kaydetmeyi unutmayın.', 'ok');
  });
}

