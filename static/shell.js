/* Koç PDF Pro — Windows uygulama penceresinin sekme kabuğu.
   Her sekme, bir bölmede (iframe) açılan uygulamanın kendisidir; sekme çubuğunu o sayfa çizer (PDFSTUDYO_tabs).
   Sekmeleri bu kabuk yönetir; Kaydet / Aç pencereleri gibi Windows'a özgü işleri pencerenin sahibine
   (başlatıcıdaki Python, window.pywebview.api) iletir. Mac uygulamasındaki Swift kabuğun karşılığıdır. */
'use strict';
(function () {
  const frames = document.getElementById('frames');
  const tabs = [];          // {id, frame, title, path, unsaved, doc, route, ready, pending}
  let selected = null;
  let seq = 0;
  let lastUnsaved = -1;

  // Pencere sahibi hazır mı? (pywebview, sayfa yüklenince "pywebviewready" olayını gönderir)
  const hostReady = new Promise(resolve => {
    if (window.pywebview?.api) return resolve(true);
    window.addEventListener('pywebviewready', () => resolve(true), { once: true });
    setTimeout(() => resolve(!!window.pywebview?.api), 6000);
  });
  const host = msg => window.pywebview?.api ? window.pywebview.api.message(msg) : Promise.resolve(null);

  const byId = id => tabs.find(t => t.id === +id);
  const isFresh = t => !t.doc && !t.unsaved && !t.pending.length && (t.route === '' || t.route === 'reader');

  function newTab(paths = []) {
    const id = ++seq;
    const frame = document.createElement('iframe');
    frame.dataset.tab = id;
    frame.setAttribute('allow', 'clipboard-read; clipboard-write; web-share; fullscreen');
    frame.src = paths.length ? `/?tab=${id}#/reader` : `/?tab=${id}#/`;
    const tab = { id, frame, title: 'Koç PDF Pro', path: null, unsaved: false, doc: false, route: '', ready: false, pending: [...paths] };
    frame.addEventListener('load', () => { tab.ready = true; sendTabs(tab); deliver(tab); });
    tabs.push(tab);
    frames.append(frame);
    select(tab);
    return tab;
  }

  function deliver(tab) {
    if (!tab.ready || !tab.pending.length) return;
    const paths = tab.pending;
    tab.pending = [];
    tab.frame.contentWindow.PDFSTUDYO_openPaths?.(paths);
  }

  function select(tab) {
    selected = tab;
    for (const t of tabs) t.frame.hidden = t !== tab;
    try { tab.frame.contentWindow.focus(); } catch { }
    changed();
  }

  // Kaydedilmemiş sekme: sayfa sorar (Kaydet / Farklı Kaydet… / Kaydetmeden kapat / Vazgeç) ve kaydeder.
  // Dönen: kapatılabilir mi
  async function askClose(tab) {
    if (!tab.unsaved) return true;
    select(tab);
    try {
      const ask = tab.frame.contentWindow.PDFSTUDYO_confirmClose;
      if (ask) return !!await ask();
    } catch { }
    const ok = await host({ action: 'confirm', title: 'Kaydedilmemiş değişiklikler var',
      message: `“${tab.title}” sekmesindeki değişiklikleri henüz kaydetmediniz. Kapatırsanız değişiklikler kaybolur.` });
    return ok !== false && (ok != null || confirm(`“${tab.title}” sekmesinde kaydedilmemiş değişiklikler var. Yine de kapatılsın mı?`));
  }

  // Pencere kapatılırken: kaydedilmemiş sekmeler sırayla öne getirilip sorulur; biri "Vazgeç" derse pencere açık kalır
  async function closeAll() {
    for (const tab of tabs.filter(t => t.unsaved)) {
      if (!await askClose(tab)) return false;
    }
    host({ action: 'quit' });
    return true;
  }

  async function close(tab) {
    if (!await askClose(tab)) return;
    const i = tabs.indexOf(tab);
    if (i < 0) return;
    tabs.splice(i, 1);
    tab.frame.remove();
    if (!tabs.length) { host({ action: 'quit' }); return; }
    if (selected === tab) select(tabs[Math.min(i, tabs.length - 1)]); else changed();
  }

  function step(delta) {
    const i = tabs.indexOf(selected);
    if (tabs.length > 1 && i >= 0) select(tabs[(i + delta + tabs.length) % tabs.length]);
  }

  // Sekmeler değişti: her sayfanın sekme çubuğu güncellensin; pencere başlığı ve kapatma uyarısı için sahibine bildir
  let queued = false;
  function changed() {
    if (queued) return;
    queued = true;
    queueMicrotask(() => {
      queued = false;
      tabs.forEach(sendTabs);
      if (selected) { document.title = selected.title; host({ action: 'title', title: `${selected.title} — Koç PDF Pro` }); }
      const unsaved = tabs.filter(t => t.unsaved).length;
      if (unsaved !== lastUnsaved) { lastUnsaved = unsaved; host({ action: 'unsaved', count: unsaved }); }
    });
  }

  function sendTabs(tab) {
    if (!tab.ready) return;
    const list = tabs.map(t => ({ id: t.id, title: t.title, path: t.path, active: t === selected, unsaved: t.unsaved, doc: t.doc }));
    try { tab.frame.contentWindow.PDFSTUDYO_tabs?.(list); } catch { }
  }

  // Bir sekmeden gelen PDF'ler: zaten açıksa o sekmeye geç, boş sekmedeyse orada, değilse yeni sekmede aç
  function openPaths(paths, from) {
    for (const p of paths) {
      const open = tabs.find(t => t.path && t.path.toLowerCase() === p.toLowerCase());
      if (open) { select(open); continue; }
      const target = from && isFresh(from) ? from : null;
      if (target) { target.pending.push(p); target.path = p; deliver(target); select(target); from = null; }
      else newTab([p]);
    }
  }

  // Sayfadaki uygulamanın sahibe gönderdiği mesajlar (Mac'teki webkit.messageHandlers karşılığı)
  function message(id, msg) {
    const tab = byId(id);
    if (!tab || !msg) return;
    switch (msg.action) {
      case 'state':
        Object.assign(tab, { unsaved: !!msg.unsaved, doc: !!msg.hasDoc, route: msg.route || '' });
        if (!tab.doc && !tab.pending.length) tab.path = null;
        return changed();
      case 'document':
        tab.title = msg.name || 'Koç PDF Pro';
        if (msg.path) tab.path = msg.path;
        return changed();
      case 'selectTab': { const t = byId(msg.id); if (t) select(t); return; }
      case 'closeTab': { const t = byId(msg.id); if (t) close(t); return; }
      case 'newTab': newTab(); return;
      case 'openPaths': openPaths(msg.paths || [], null); return;   // Önceki sürümler: yedeği yeni sekmede aç
      case 'stepTab': step(msg.delta || 1); return;
      case 'openPDF':
        host({ action: 'openPanel', accept: '.pdf,.udf', multiple: true }).then(paths => { if (paths?.length) openPaths(paths, tab); });
        return;
      case 'theme':
        for (const t of tabs) if (t !== tab) { try { t.frame.contentWindow.PDFSTUDYO_applyTheme?.(msg.value); } catch { } }
        host({ action: 'theme', value: msg.value });   // açılış ekranı bir sonraki açılışta bu görünümle gelsin
        return;
      case 'accept': case 'defaultStatus': case 'setDefaultPDF': return;   // Windows'ta karşılığı yok
      default:
        host(msg);   // reveal, print, quit…
    }
  }

  window.PDFSTUDYO_SHELL = {
    hasHost: () => !!window.pywebview?.api,
    message,
    ask: (id, msg) => host(msg),                  // kaydetme / açma pencereleri: sonuç sayfaya döner
    unsavedCount: () => tabs.filter(t => t.unsaved).length,
    closeAll,   // pencerenin kapatma düğmesi (pencere sahibi çağırır)
    // Uygulama yeniden başlatıldı ya da kısayola PDF sürüklendi: mevcut pencerede aç
    openExternal: paths => started.then(() => { if (paths?.length) openPaths(paths, selected && isFresh(selected) ? selected : null); }),
  };

  // Başlatıcı ilk açılışta bir PDF ile çağrıldıysa (?open=yol) onu aç
  const started = hostReady.then(() => {
    const open = new URLSearchParams(location.search).getAll('open');
    newTab(open);
  });
})();
