/* Koç PDF Pro — Sıkıştır ve Böl pencereleri; pencereyle açılan araçlar (DIALOGS). */
'use strict';

// ------------------------------------------------------------------ sıkıştır
// Her düzeyin gerçek sonucu arka planda hesaplanır ve düğmelerinde yazar; hedef boyut seçilirse o boyuta inen en
// kaliteli düzey kullanılır. Açık belgede sonuç belgeye uygulanır (Geri Al ile geri alınır).
const SIK_LEVELS = [['dusuk', 'Hafif'], ['orta', 'Önerilen'], ['yuksek', 'Güçlü']];
const SIK_HINT = {
  dusuk: 'Görünüm hiç değişmez: gereksiz veriler temizlenir, yazı tipleri küçültülür.',
  orta: 'Resimler 150 dpi\'ye iner; ekranda ve baskıda fark edilmez.',
  yuksek: 'Resimler 96 dpi\'ye iner; ekranda rahat okunur, baskıda resimler biraz bulanıklaşabilir.',
  hedef: 'Seçtiğiniz boyuta inen en kaliteli düzey kullanılır; gerekirse resimler 72 dpi\'ye kadar iner.',
};
const SIK_HINT_SB = {   // siyah-beyaz seçiliyken taranmış sayfaların çözünürlüğü
  dusuk: 'Taranmış sayfalar 300 dpi siyah-beyaz; diğer her şey aynı kalır.',
  orta: 'Taranmış sayfalar 200 dpi siyah-beyaz; yazılar net kalır.',
  yuksek: 'Taranmış sayfalar 150 dpi siyah-beyaz; çok küçük yazılar biraz bozulabilir.',
};
const SIK_COLORS = [['renkli', 'Olduğu gibi'], ['gri', 'Gri'], ['sb', 'Siyah-beyaz']];
const SIK_COLOR_HINT = {
  renkli: '',
  gri: 'Bütün belge gri olur; renkli taramalarda dosya küçülür.',
  sb: 'Taranmış sayfalar siyah-beyaz olur; yazılı belgelerde dosya çok küçülür. Renkli kaşe, imza ve fotoğraflar da siyah-beyaz görünür.',
};
const SIK_TARGETS = [2, 5, 10, 20];   // MB (1 MB = 1.000.000 bayt: e-posta ve yükleme sınırlarının altında kalsın)
const MB = 1e6;

function compressDialog({ doc = null, ...opts } = {}) {
  // target: bayt (0 ise düzey seçili); drop: kaldırılacaklar (gömülü ek dosyalar, belge bilgileri)
  const cfg = { level: 'orta', target: 0, targetPick: 10 * MB, color: 'renkli', drop: { attachments: false, meta: false } };
  // Sonuç anahtarı: "düzey|renk|kaldırılanlar" ya da "t<bayt>|renk|kaldırılanlar"
  const keyOf = mode => `${mode}|${cfg.color}|${Object.keys(cfg.drop).filter(k => cfg.drop[k]).join(',')}`;
  const current = () => keyOf(cfg.target ? 't' + cfg.target : cfg.level);
  const params = key => {
    const [mode, color, drop] = key.split('|');
    return { color, drop: drop ? drop.split(',') : [], ...(mode[0] === 't' ? { target: +mode.slice(1) } : { level: mode }) };
  };
  const pct = res => Math.round((1 - res.after / res.before) * 100);
  // Sonuç bir kez istenir; aynı anda gelen istekler (arka plan hesabı, Sıkıştır düğmesi) aynı yanıtı bekler
  const get = (r, key) => r.res[key] ? Promise.resolve(r.res[key])
    : r.pending[key] ||= postJSON('/api/compress', { id: r.id, ...params(key) })
      .catch(e => ({ error: e.message }))
      .then(res => { r.res[key] = res; delete r.pending[key]; w.render(); return res; });

  let working = false;
  async function compute() {   // önce seçili ayar, sonra düğmelerdeki düzeyler; satırlar sırayla
    if (working) return;
    working = true;
    try {
      for (;;) {
        if (w.closed) return;
        const live = w.rows.filter(r => !r.encrypted);
        let task = null;
        for (const key of [current(), ...SIK_LEVELS.map(([l]) => keyOf(l))]) {
          const r = live.find(x => !x.res[key]);
          if (r) { task = [r, key]; break; }
        }
        if (!task) return;
        await get(...task);
      }
    } finally { working = false; }
  }

  function settingsChanged() {
    w.rows.forEach(r => { if (r.state !== 'run') r.state = ''; });
    w.status('');
    w.render();
    compute();
    shown?.update();
  }

  // Önce / sonra: bir sayfa yan yana, iki taraf birlikte kayar. Ayarlar açık kalır; düzey ya da renk değişince
  // "sonra" tarafı yeni sonuçla çizilir.
  let shown = null;
  function preview(r) {
    const panel = document.createElement('div');
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    let page = r.image_page || 0, zoom = 1;
    panel.innerHTML = `<div class="fx-pv-head"><button class="btn sm" data-back>${icon('left')}Listeye dön</button>
        <b class="fx-pv-name" title="${esc(r.name)}">${esc(r.name)}</b><span class="spacer"></span>
        <span class="fx-pv-pages"><button class="btn sm ghost icon-btn" data-step="-1" aria-label="Önceki sayfa">${icon('left')}</button>
          <span class="muted small" data-page></span>
          <button class="btn sm ghost icon-btn" data-step="1" aria-label="Sonraki sayfa">${icon('right')}</button></span>
        <div class="seg sm" data-zoom>${[1, 2, 3].map(z => `<button type="button" data-z="${z}" class="${z === zoom ? 'on' : ''}">%${z * 100}</button>`).join('')}</div></div>
      <div class="fx-pv-grid">
        <div class="fx-pv-col"><div class="fx-pv-label" data-label="0"></div><div class="fx-pv-scroll"><img alt=""></div></div>
        <div class="fx-pv-col"><div class="fx-pv-label" data-label="1"></div><div class="fx-pv-scroll"><img alt=""></div></div>
      </div>
      <div class="muted small">İki taraf birlikte kayar; yazıların ve resimlerin okunaklığını karşılaştırın.</div>`;
    const panes = $$('.fx-pv-scroll', panel), imgs = $$('.fx-pv-scroll img', panel);
    let syncing = false;
    panes.forEach((p, i) => p.addEventListener('scroll', () => {
      if (syncing) return;
      syncing = true;
      panes[1 - i].scrollTop = p.scrollTop;
      panes[1 - i].scrollLeft = p.scrollLeft;
      requestAnimationFrame(() => { syncing = false; });
    }));
    imgs.forEach(img => img.onload = () => { img.style.width = img.naturalWidth / dpr + 'px'; });
    const draw = async () => {
      if (w.closed || closePanel === null) return;
      const ratio = [panes[0].scrollLeft / (panes[0].scrollWidth || 1), panes[0].scrollTop / (panes[0].scrollHeight || 1)];
      $('[data-page]', panel).textContent = `Sayfa ${page + 1} / ${r.pages}`;
      $$('[data-z]', panel).forEach(b => b.classList.toggle('on', +b.dataset.z === zoom));
      const q = `page=${page}&zoom=${zoom * dpr}`;
      $('[data-label="0"]', panel).textContent = `Önce · ${fmtSize(r.size)}`;
      imgs[0].src = `/api/compress/page?src=${r.id}&${q}`;
      $('[data-label="1"]', panel).textContent = 'Sonra · hesaplanıyor…';
      const res = await get(r, current());
      if (closePanel === null) return;
      if (res.error) { $('[data-label="1"]', panel).textContent = 'Sonra · ' + res.error; return; }
      $('[data-label="1"]', panel).textContent = `Sonra · ${res.level_name}${cfg.color !== 'renkli' ? ' · ' + SIK_COLORS.find(([c]) => c === cfg.color)[1].toLowerCase() : ''} · ${fmtSize(res.after)}`;
      imgs[1].src = `/api/compress/page?out=${res.id}&${q}`;
      await Promise.all(imgs.map(img => (img.complete ? null : new Promise(ok => img.addEventListener('load', ok, { once: true })))));
      panes.forEach(p => { p.scrollLeft = ratio[0] * p.scrollWidth; p.scrollTop = ratio[1] * p.scrollHeight; });
    };
    $$('[data-step]', panel).forEach(b => b.onclick = () => {
      page = Math.min(Math.max(page + +b.dataset.step, 0), r.pages - 1);
      draw();
    });
    $$('[data-z]', panel).forEach(b => b.onclick = () => { zoom = +b.dataset.z; draw(); });
    let closePanel = w.showPanel(panel);
    $('[data-back]', panel).onclick = () => { closePanel(); closePanel = null; shown = null; };
    shown = { update: draw };
    draw();
  }

  const total = level => {
    const key = keyOf(level), live = w.rows.filter(r => !r.encrypted);
    if (!live.length || live.some(r => !r.res[key] || r.res[key].error)) return '…';
    return fmtSize(live.reduce((n, r) => n + r.res[key].after, 0));
  };

  const w = fileWindow({
    title: 'Sıkıştır', kinds: ['pdf'], accept: '.pdf', wrongKind: 'yalnızca PDF dosyaları sıkıştırılır',
    emptyHint: 'PDF dosyaları; birden çok dosya eklenebilir', folderName: 'Sıkıştırılmış', progress: 'Hazırlanıyor…',
    runIcon: 'compress', noteInBody: true, docOnly: !!doc,
    applyLabel: doc && 'Açık belgeye uygula',
    applyHint: 'Belge ekranda küçülür; dosyanız siz Kaydet\'e basana kadar değişmez. Kaydet\'e basınca dosyanızın üzerine '
      + 'yazılır, eski hâli Önceki sürümler\'de saklanır. Ayrı bir küçük kopya için "Yeni dosya olarak kaydet"i seçin.',
    runLabel: rows => (w.apply ? 'Belgeye uygula' : rows.length && rows.every(r => r.state === 'done' || r.encrypted) ? 'Yeniden kaydet' : 'Sıkıştır'),
    newRow: f => ({ ...f, res: {}, pending: {} }),
    rowBody: r => {
      const res = r.res[current()];
      const size = !res ? '<span class="spinner sm"></span><span class="muted">Hesaplanıyor…</span>'
        : res.error ? `<span class="err">${esc(res.error)}</span>`
        : `<b>${fmtSize(res.before)} → ${fmtSize(res.after)}</b>${pct(res) >= 1 ? `<span class="fx-pct">−%${pct(res)}</span>` : ''}
          ${cfg.target ? (res.reached ? `<span class="muted">· ${esc(res.level_name)} düzeyde</span>`
            : '<span class="err">· hedefe inilemedi; en küçük sonuç bu</span>') : ''}`;
      return `<div class="fx-size">${size}${res && !res.error ? '<button class="link-btn small" data-preview>Önizle</button>' : ''}</div>
        ${res?.note ? `<div class="fx-note">${esc(res.note)}</div>` : ''}
        ${r.signed ? '<div class="fx-note warn">E-imzalı belge: sıkıştırılınca e-imza geçersiz olur. İmzalı hâlini ayrıca saklayın.</div>' : ''}`;
    },
    bindRow: (row, r) => {
      const b = $('[data-preview]', row);
      if (b) b.onclick = () => preview(r);
    },
    renderSettings: box => {
      if (!box.firstChild) box.innerHTML = '<div class="fx-levels"></div><div class="fx-goal"></div><div class="fx-colors"></div><div class="fx-extras"></div>';
      const mode = cfg.target ? 'hedef' : cfg.level;
      w.patch($('.fx-levels', box), `<div class="seg fx-level-seg">${SIK_LEVELS.map(([l, label]) =>
        `<button type="button" data-l="${l}" class="${mode === l ? 'on' : ''}"><b>${label}</b><span>${total(l)}</span></button>`).join('')}
        <button type="button" data-l="hedef" class="${cfg.target ? 'on' : ''}"><b>Hedef boyut</b>
          <span>${cfg.target ? `en fazla ${String(cfg.target / MB).replace('.', ',')} MB` : 'boyutu siz seçin'}</span></button></div>
        <div class="fx-note">${esc((cfg.color === 'sb' && SIK_HINT_SB[mode]) || SIK_HINT[mode])}</div>`,
      b => $$('[data-l]', b).forEach(btn => btn.onclick = () => {
        if (w.running) return;
        if (btn.dataset.l === 'hedef') cfg.target = cfg.targetPick;
        else { cfg.level = btn.dataset.l; cfg.target = 0; }
        settingsChanged();
      }));
      const custom = cfg.target && !SIK_TARGETS.includes(cfg.target / MB);
      w.patch($('.fx-goal', box), cfg.target ? `<span class="muted small">${w.rows.length > 1 ? 'Her dosya en fazla' : 'En fazla'}</span>
        <div class="seg sm">${SIK_TARGETS.map(n => `<button type="button" data-mb="${n}" class="${cfg.target === n * MB ? 'on' : ''}">${n} MB</button>`).join('')}</div>
        <input class="input sm fx-mb ${custom ? 'on' : ''}" inputmode="decimal" placeholder="Başka" value="${custom ? String(cfg.target / MB).replace('.', ',') : ''}">
        <span class="muted small">MB</span>` : '',
      b => {
        const set = mb => {
          if (!(mb > 0) || w.running) return;
          cfg.target = cfg.targetPick = Math.round(mb * MB);
          settingsChanged();
        };
        $$('[data-mb]', b).forEach(btn => btn.onclick = () => set(+btn.dataset.mb));
        const input = $('.fx-mb', b);
        if (input) {
          input.onchange = () => set(parseFloat(input.value.replace(',', '.')));
          input.onkeydown = e => { if (e.key === 'Enter') input.onchange(); };
        }
      });
      w.patch($('.fx-colors', box), `<span class="muted small">Renk</span><div class="seg sm">${SIK_COLORS.map(([c, label]) =>
        `<button type="button" data-c="${c}" class="${cfg.color === c ? 'on' : ''}">${label}</button>`).join('')}</div>
        <span class="fx-note">${esc(SIK_COLOR_HINT[cfg.color])}</span>`,
      b => $$('[data-c]', b).forEach(btn => btn.onclick = () => {
        if (w.running || cfg.color === btn.dataset.c) return;
        cfg.color = btn.dataset.c;
        settingsChanged();
      }));
      // Kayıpsız ek temizlik: gömülü ek dosyalar (yalnız varsa gösterilir) ve belge bilgileri
      const [count, bytes] = w.rows.reduce(([n, b], r) => [n + (r.attachments?.[0] || 0), b + (r.attachments?.[1] || 0)], [0, 0]);
      if (!count && cfg.drop.attachments) { cfg.drop.attachments = false; compute(); }
      w.patch($('.fx-extras', box), `<span class="muted small">Ayrıca</span>
        ${count ? `<label class="check small"><input type="checkbox" data-d="attachments" ${cfg.drop.attachments ? 'checked' : ''}>
          Gömülü ek dosyaları kaldır (${count} dosya · ${fmtSize(bytes)})</label>` : ''}
        <label class="check small"><input type="checkbox" data-d="meta" ${cfg.drop.meta ? 'checked' : ''}>
          Belge bilgilerini temizle (yazar, program, tarihler)</label>`,
      b => $$('[data-d]', b).forEach(input => input.onchange = () => {
        if (w.running) { input.checked = cfg.drop[input.dataset.d]; return; }
        cfg.drop[input.dataset.d] = input.checked;
        settingsChanged();
      }));
    },
    outName: r => ({ name: w.stemOf(r.name) + '_sikistirilmis', ext: 'pdf' }),
    process: async r => {
      const res = await get(r, current());
      if (res.error) throw new Error(res.error);
      return res;
    },
    changed: () => compute(),
    // Açık belgeye uygula: sonuç belgenin yeni hâli olur
    finish: doc && (async ([r]) => {
      const res = r.result;
      if (!res.changed) { w.m.close(); return toast('Belge zaten küçük; değişiklik gerekmedi.'); }
      const ctx = openDocView();
      if (ctx?.info.id !== doc.id) return toast('Belge kapatılmış; dosya seçerek devam edin.', 'error');
      if (!await confirmSignedRewrite(ctx.info, '“Sıkıştır”')) return;
      try {
        const info = await withBusy('Uygulanıyor…', () => postJSON(`/api/edit/${doc.id}/apply-output`, { out: res.id, rev: r.rev }));
        window.Reader.refresh(info);
        w.m.close();
        toast(`Sıkıştırıldı (${fmtSize(res.before)} → ${fmtSize(res.after)}). Kalıcı olması için Kaydet'e basın.`, 'ok');
      } catch { /* toast gösterildi */ }
    }),
  });
  w.open({ doc, ...opts });
}

// ------------------------------------------------------------------ böl
// Sayfalar küçük resimleriyle görünür: iki sayfanın arasına tıklayınca orası kesilir, sayfaya tıklayınca o sayfa hiçbir
// parçaya girmez. Yöntemler (her sayfa, her N sayfa, aralıklar…) kesimleri kendiliğinden yerleştirir; sonra elle
// düzeltilebilir. Parçalar ayrı PDF'ler olarak bir klasöre (tek parçaysa verilen adla) kaydedilir.
const SPLIT_COLORS = ['#2f6fec', '#1f8a4c', '#b4530a', '#7b4bd6', '#0f8f7e', '#d6453d'];
const SPLIT_MODES = [['each', 'Her sayfa'], ['every', 'Her N sayfada'], ['ranges', 'Aralıklar'], ['toc', 'Yer imleri'], ['size', 'Boyut'],
  ['blank', 'Boş sayfalar']];
const SPLIT_PLANNED = new Set(['toc', 'size', 'blank']);   // sunucuda hesaplanan yöntemler

// "1-3, 5, 8-" → [[0,1,2],[4],[7..n-1]] (sunucudaki parse_ranges'in kuralları); hatalıysa ileti fırlatır
function parseRanges(spec, n) {
  const groups = [];
  for (const raw of spec.split(/[,;]/)) {
    const part = raw.replace(/\s+/g, '');
    if (!part) continue;
    const m = part.match(/^(\d*)-(\d*)$/);
    let a, b;
    if (m) { a = m[1] ? +m[1] : 1; b = m[2] ? +m[2] : n; }
    else if (/^\d+$/.test(part)) a = b = +part;
    else throw new Error(`Geçersiz sayfa aralığı: “${part}”`);
    if (a < 1 || b > n || a > b) throw new Error(`“${part}” aralığı geçersiz (belge ${n} sayfa).`);
    groups.push(Array.from({ length: b - a + 1 }, (_, k) => a - 1 + k));
  }
  if (!groups.length) throw new Error('Sayfa aralığı yazın, örneğin: 1-3, 5, 8-10');
  return groups;
}

// [0, 1, 2, 4] → "1-3, 5"
function pagesLabel(pages) {
  const runs = [];
  for (const p of pages) {
    const last = runs[runs.length - 1];
    if (last && p === last[1] + 1) last[1] = p;
    else runs.push([p, p]);
  }
  return runs.map(([a, b]) => (a === b ? `${a + 1}` : `${a + 1}-${b + 1}`)).join(', ');
}

function splitDialog({ doc = null, ...opts } = {}) {
  // Seçili dosyanın bölünüşü: cuts (bu sayfadan sonra kesilir), skip (alınmayan sayfalar), names (elle verilen parça
  // adları; parçanın ilk sayfasıyla), auto (yöntemin verdiği adlar), mode (son uygulanan yöntem; elle değişince boş)
  let sp = null;
  const current = () => {
    const r = w.rows[0];
    if (!r || r.encrypted || !r.pages) return (sp = null);
    if (sp?.id !== r.id || sp.n !== r.pages) {
      sp = { id: r.id, n: r.pages, cuts: new Set(), skip: new Set(), names: new Map(), auto: new Map(), sizes: new Map(),
        mode: '', every: 2, ranges: '', together: false, limit: 10 * MB, error: '' };
    }
    return sp;
  };
  const parts = () => {
    const out = [];
    let cur = [];
    for (let i = 0; i < sp.n; i++) {
      if (!sp.skip.has(i)) cur.push(i);
      if (sp.cuts.has(i) || i === sp.n - 1) {
        if (cur.length) out.push(cur);
        cur = [];
      }
    }
    return out;
  };
  const stem = () => w.stemOf(w.rows[0].name);
  const color = k => SPLIT_COLORS[k % SPLIT_COLORS.length];
  const defaultName = (pages, k, count) => sp.auto.get(pages[0])
    ?? (count > 1 ? `${stem()} - ${k + 1} (s. ${pagesLabel(pages)})` : pages.length === sp.n ? stem() : `${stem()} (s. ${pagesLabel(pages)})`);
  const nameOf = (pages, k, count) => sp.names.get(pages[0])?.trim() || defaultName(pages, k, count);

  function changed() {
    if (w.rows[0]) w.rows[0].state = '';
    w.status('');
    w.render();
  }

  // Yöntem: kesimleri ve alınmayan sayfaları baştan yerleştirir
  function apply(mode) {
    if (SPLIT_PLANNED.has(mode)) return plan(mode, mode === 'size' ? { limit: sp.limit } : {});
    Object.assign(sp, { mode, error: '', note: '', cuts: new Set(), skip: new Set(), auto: new Map(), sizes: new Map() });
    const n = sp.n;
    if (mode === 'each') for (let i = 0; i < n - 1; i++) sp.cuts.add(i);
    else if (mode === 'every') {
      const k = Math.max(1, parseInt(sp.every, 10) || 1);
      for (let i = k - 1; i < n - 1; i += k) sp.cuts.add(i);
    } else if (mode === 'ranges' && sp.ranges.trim()) {
      let groups;
      try { groups = parseRanges(sp.ranges, n); } catch (e) { sp.error = e.message; return changed(); }
      const flat = groups.flat();
      if (flat.some((p, k) => k && p <= flat[k - 1])) {
        sp.error = 'Aralıkları sırayla ve birbirine karışmadan yazın (örneğin 1-3, 5, 8-10).';
        return changed();
      }
      const keep = new Set(flat);
      for (let i = 0; i < n; i++) if (!keep.has(i)) sp.skip.add(i);
      if (!sp.together) groups.forEach(g => { if (g[g.length - 1] < n - 1) sp.cuts.add(g[g.length - 1]); });
    }
    changed();
  }

  // Sunucuda hesaplanan yöntem (içindekiler…): sonuç gelene kadar "hesaplanıyor"
  async function plan(mode, extra = {}) {
    const s = sp;
    Object.assign(s, { mode, error: '', note: '', cuts: new Set(), skip: new Set(), auto: new Map(), sizes: new Map(), busy: true });
    changed();
    try {
      const res = await postJSON('/api/split/plan', { id: s.id, mode, ...extra });
      if (sp !== s || s.mode !== mode) return;   // bu arada başka dosya ya da yöntem seçildi
      const byStart = o => new Map(Object.entries(o || {}).map(([k, v]) => [+k, v]));
      Object.assign(s, { cuts: new Set(res.cuts || []), skip: new Set(res.skip || []), note: res.note || '',
        auto: byStart(res.names), sizes: byStart(res.sizes) });
    } catch (e) { s.error = e.message; }
    s.busy = false;
    if (sp === s) changed();
  }

  function buildGrid(grid) {
    const r = w.rows[0], dpr = Math.min(window.devicePixelRatio || 1, 2);
    grid.innerHTML = Array.from({ length: sp.n }, (_, i) => `<div class="sp-tile" data-i="${i}" title="Sayfa ${i + 1} · tıklayınca bu sayfa alınmaz ya da yeniden alınır">
        <div class="sp-thumb"><img loading="lazy" alt="" src="/api/stage/${r.id}/page/${i}?w=${Math.round(92 * dpr)}"></div>
        <span class="sp-no">${i + 1}</span><span class="sp-badge"></span></div>`
      + (i < sp.n - 1 ? `<button type="button" class="sp-gap" data-g="${i}" title="${i + 1}. sayfadan sonra kes">${icon('split')}</button>` : '')).join('');
    grid.onclick = e => {
      if (w.running) return;
      const gap = e.target.closest('.sp-gap'), tile = e.target.closest('.sp-tile');
      const toggle = (set, i) => (set.has(i) ? set.delete(i) : set.add(i));
      if (gap) toggle(sp.cuts, +gap.dataset.g);
      else if (tile) toggle(sp.skip, +tile.dataset.i);
      else return;
      Object.assign(sp, { mode: '', error: '', note: '', sizes: new Map() });   // elle düzenlendi: hesaplanan boyutlar geçersiz
      changed();
    };
  }

  function paintGrid(grid, ps) {
    const partOf = new Map();
    ps.forEach((pages, k) => pages.forEach(p => partOf.set(p, k)));
    $$('.sp-tile', grid).forEach(tile => {
      const i = +tile.dataset.i, k = partOf.get(i);
      tile.classList.toggle('skip', k == null);
      tile.style.setProperty('--pc', k == null ? 'transparent' : color(k));
      $('.sp-badge', tile).textContent = k != null && ps[k][0] === i && ps.length > 1 ? k + 1 : '';
    });
    $$('.sp-gap', grid).forEach(g => g.classList.toggle('on', sp.cuts.has(+g.dataset.g)));
  }

  const w = fileWindow({
    title: 'Böl / Sayfa Ayır', kinds: ['pdf'], accept: '.pdf', wrongKind: 'yalnızca PDF dosyaları bölünür',
    emptyHint: 'Bir PDF seçin; sayfalarını burada görüp istediğiniz yerlerden bölersiniz', progress: 'Bölünüyor…',
    runIcon: 'split', single: true, settingsBelow: true, docOnly: !!doc,
    runLabel: rows => (rows[0]?.state === 'done' ? 'Yeniden böl' : 'Böl'),
    newRow: f => f,
    rowBody: () => '',
    renderSettings: box => {
      if (!current()) { box.innerHTML = ''; box._doc = null; return; }
      if (box._doc !== sp.id) {   // yeni dosya: sayfalar bir kez dizilir, sonra yalnız boyanır
        box._doc = sp.id;
        box.innerHTML = '<div class="sp-modes"></div><div class="sp-hint"></div><div class="sp-grid"></div><div class="sp-parts"></div>';
        buildGrid($('.sp-grid', box));
      }
      const ps = parts();
      w.patch($('.sp-modes', box), `<span class="muted small">Nasıl bölünsün?</span>
        <div class="seg sm">${SPLIT_MODES.map(([m, label]) => (m === 'toc' && !w.rows[0].bookmarks
          ? `<button type="button" disabled title="Bu belgede içindekiler (yer imi) yok">${label}</button>`
          : `<button type="button" data-m="${m}" class="${sp.mode === m ? 'on' : ''}">${label}</button>`)).join('')}</div>
        ${sp.mode === 'every' ? '<input class="input sm sp-every" inputmode="numeric" aria-label="Kaç sayfada bir"><span class="muted small">sayfada bir</span>' : ''}
        ${sp.mode === 'ranges' ? `<input class="input sm sp-ranges" placeholder="örn. 1-3, 5, 8-10" spellcheck="false" aria-label="Sayfa aralıkları">
          <div class="seg sm" data-together>${[['', 'Her aralık ayrı'], ['1', 'Hepsi tek dosyada']].map(([v, label]) =>
            `<button type="button" data-t="${v}" class="${sp.together === !!v ? 'on' : ''}">${label}</button>`).join('')}</div>` : ''}
        ${sp.mode === 'size' ? `<span class="muted small">Her parça en fazla</span><div class="seg sm">${SIK_TARGETS.map(n =>
            `<button type="button" data-mb="${n}" class="${sp.limit === n * MB ? 'on' : ''}">${n} MB</button>`).join('')}</div>
          <input class="input sm fx-mb ${SIK_TARGETS.includes(sp.limit / MB) ? '' : 'on'}" inputmode="decimal" placeholder="Başka" aria-label="En fazla MB">
          <span class="muted small">MB</span>` : ''}
        <span class="spacer"></span><button class="link-btn small" data-reset>Kesimleri temizle</button>`, b => {
        $$('[data-m]', b).forEach(btn => btn.onclick = () => { if (!w.running) apply(btn.dataset.m); });
        $$('[data-t]', b).forEach(btn => btn.onclick = () => { sp.together = !!btn.dataset.t; apply('ranges'); });
        $('[data-reset]', b).onclick = () => { if (!w.running) apply(''); };
        const limit = mb => { if (mb > 0 && !w.running) { sp.limit = Math.round(mb * MB); apply('size'); } };
        $$('[data-mb]', b).forEach(btn => btn.onclick = () => limit(+btn.dataset.mb));
        const custom = $('.fx-mb', b);
        if (custom) {
          if (!SIK_TARGETS.includes(sp.limit / MB)) custom.value = String(sp.limit / MB).replace('.', ',');
          custom.onchange = () => limit(parseFloat(custom.value.replace(',', '.')));
          custom.onkeydown = e => { if (e.key === 'Enter') custom.onchange(); };
        }
        const every = $('.sp-every', b), ranges = $('.sp-ranges', b);
        let timer = 0;
        const later = fn => { clearTimeout(timer); timer = setTimeout(fn, 350); };   // yazarken çizgiler kendiliğinden yerleşsin
        if (every) {
          every.value = sp.every;
          every.oninput = () => { sp.every = every.value; later(() => apply('every')); };
        }
        if (ranges) {
          ranges.value = sp.ranges;
          ranges.oninput = () => { sp.ranges = ranges.value; later(() => apply('ranges')); };
          ranges.focus();
        }
      });
      const skipped = sp.skip.size, alone = ps.length < 2 && !skipped;
      $('.sp-hint', box).innerHTML = sp.error ? `<span class="err">${esc(sp.error)}</span>`
        : sp.busy ? '<span class="spinner sm"></span> Hesaplanıyor…'
        : `<b>${ps.length} parça</b>${sp.note ? ` · ${esc(sp.note)}` : ''}${skipped ? ` · ${skipped} sayfa alınmayacak` : ''} · ${alone
          ? 'Bölmek için iki sayfanın arasına tıklayın ya da yukarıdan bir yöntem seçin.'
          : 'Aralara tıklayarak kesimleri değiştirin; bir sayfaya tıklayınca o sayfa alınmaz.'}`;
      paintGrid($('.sp-grid', box), ps);
      // Parça adları: yazılan ad korunur (sayfadaki işaret yerinde kaldıkça); tek parçada ad Kaydet bölümünde
      w.patch($('.sp-parts', box), ps.length > 1 ? `<div class="muted small sp-parts-head">Parça adları</div>${ps.map((pages, k) =>
        `<div class="sp-part" data-s="${pages[0]}" data-d="${esc(defaultName(pages, k, ps.length))}">
          <span class="sp-dot" style="--pc:${color(k)}">${k + 1}</span>
          <span class="muted small sp-range" title="s. ${pagesLabel(pages)}">s. ${pagesLabel(pages)} · ${pages.length} sayfa${sp.sizes.has(pages[0])
            ? ` · ${fmtSize(sp.sizes.get(pages[0]))}` : ''}</span>
          <input class="input sm sp-name" spellcheck="false" aria-label="${k + 1}. parçanın adı"><span class="muted small">.pdf</span></div>`).join('')}` : '',
      b => $$('.sp-part', b).forEach((row, k) => {
        const input = $('input', row);
        input.value = nameOf(ps[k], k, ps.length);
        input.oninput = () => { sp.names.set(+row.dataset.s, input.value); w.rows[0].state = ''; };
      }));
    },
    blocked: () => !current() || sp.busy || !!sp.error || !parts().length || (parts().length < 2 && !sp.skip.size),
    saveAs: () => {
      const ps = current() ? parts() : [];
      if (ps.length <= 1) return { name: ps.length ? nameOf(ps[0], 0, 1) : stem(), ext: 'pdf', folder: false };
      return { name: `${stem()}_parcalar`, folder: true, note: `${ps.length} parça bu klasörde toplanır` };
    },
    process: async r => {
      const ps = parts();
      const res = await postJSON('/api/split', { id: r.id, parts: ps.map((pages, k) => ({ pages, name: nameOf(pages, k, ps.length) })) });
      return { files: res.files };
    },
    outputs: r => r.result.files,
    doneHtml: r => {
      const files = r.result.files, one = files.length === 1;
      return `<div class="fx-state ok">${icon('check')}<span class="fx-out">${one ? esc(r.savedPath ? baseName(r.savedPath) : files[0].name)
        : `${files.length} parça ${NATIVE ? 'kaydedildi' : 'hazır'}`}</span></div>`;
    },
  });
  w.open({ doc, ...opts });
}

// Pencereyle açılan araçlar (ana sayfa kartı, Araçlar menüleri, ana sayfaya bırakılan dosyalar, eski adresleri)
const DIALOGS = { convert: convertDialog, compress: compressDialog, split: splitDialog };

