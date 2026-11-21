// Verbaliox page script: the import window (package B, docs/redesign-plan.md). Files, links and paths
// to add; the model, language and speakers; what is done to the sound before recognition and to the
// text after it (database.PROCESSING_KEYS, kept per recording). Filled from the settings; "Remember"
// writes them back, "Do not ask" makes "Import" start at once (setting ask_import_params).
// The parts are classic scripts sharing one global scope, loaded in order by index.html.

const IMP_SOUND = [
  // key, label, hint, the models it is for: 'onnx' (GigaAM, Parakeet), 'whisper', or both
  ['denoise', 'impDenoise', 'impDenoiseHint', ''],
  ['loudnorm', 'impLoudnorm', 'impLoudnormHint', ''],
  ['leveling', 'impLeveling', 'impLevelingHint', 'onnx'],
  ['vad', 'impVad', 'impVadHint', 'whisper'],
];
const IMP_AFTER = [['diarization', 'impDiarization', 'impDiarizationHint'], ['summary', 'impSummary', 'impSummaryHint']];
const IMP_ENSEMBLE = ['ensemble', 'impEnsemble', 'impEnsembleHint', ''];  // shown under the model, always

function impSettings() { return (state.system && state.system.settings) || {}; }

// Settings are "true"/"false" strings; a missing one is on (as on the server)
function impOn(key, s = impSettings()) { return String(s[key] ?? 'true') !== 'false'; }

function askImportParams() { return impOn('ask_import_params'); }

// What the settings choose for a new file (database.effective_processing on the server)
function impDefaults() {
  const s = impSettings();
  const sound = (key) => (s[key] != null && s[key] !== '' ? impOn(key, s) : impOn('audio_enhance', s));
  return {
    denoise: sound('proc_denoise'), loudnorm: sound('proc_loudnorm'), leveling: impOn('proc_leveling', s),
    vad: impOn('vad_filter', s), diarization: impOn('diarization_enabled', s), summary: impOn('auto_summary', s),
    ensemble: String(s.asr_ensemble) === 'true',  // off unless chosen (Settings → Recognition)
    transcribe: true,  // off: «Только добавить» — the files go to the library without recognition
  };
}

function impFresh() {
  return { items: [], proc: impDefaults(), seq: 0, mode: 'all' };
}

// Ctrl+O and «Файлы» of the ▾ menu: the window in its files mode, or the file picker at once when it should not ask
function openImport() {
  if (askImportParams()) openImportDialog({ mode: 'files' });
  else impPickFiles();
}

// «＋ Импорт» itself (the main part of the split button): the window with every way to add and every option
function openImportFull() {
  openImportDialog({ mode: 'all' });
}

// «Файлы…»: the Windows file picker gives the files' places, and they are added where they are (no
// copy in the program's folder). The page's own picker gives only their content, so it is used when
// the files are to be copied (Settings «Копировать импортированные файлы») or the Windows one is not there.
async function impPickFiles() {
  const s = (state.system && state.system.settings) || {};
  if (String(s.import_copy) === 'true') { clickElement('file-input'); return; }
  const res = await fetch('/api/import/pick-files', { method: 'POST' }).catch(() => null);
  const data = res && res.ok ? await readJson(res) : null;
  if (!data || !data.available) { clickElement('file-input'); return; }
  const paths = data.paths || [];
  if (!paths.length) return;
  await importPaths(paths);
}

// Files by their place on disk (the Windows picker, or dropped on the window): added where they are
async function importPaths(paths, mode = 'files') {
  if (impIsOpen()) { impAddPaths(paths); return; }
  if (askImportParams()) { openImportDialog({ mode }); impAddPaths(paths); return; }
  if (!requireRecognitionModel()) return;
  const created = [];
  for (const path of paths) {
    const r = await fetch('/api/meetings/local-path', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path }),
    });
    const out = await readJson(r);
    if (r.status === 409) { showToast(serverText(out.detail)); continue; }  // already in the library: the rest still go
    if (!r.ok) { showError(serverText(out.detail)); break; }
    created.push(...(out.created || []));
  }
  if (!created.length) return;
  switchAppView('library');
  await loadMeetingsList();
  await selectMeeting(created[0].id, true);
  showToast(t('impQueued').replace('{n}', () => plural(created.length, t('impItemsForms'))), null, 'success');
}

function impAddPaths(paths) {
  const imp = state.imp || (state.imp = impFresh());
  for (const path of paths) impPushPath(imp, path);
  renderImport();
}

// A path in the list; a folder's own audio and video files are listed under it once the server has looked
function impPushPath(imp, path) {
  if (imp.items.some(x => x.kind === 'path' && x.path === path)) return;
  const item = { id: ++imp.seq, kind: 'path', path, folder: null };
  imp.items.push(item);
  impProbeFolder(item);
}

async function impProbeFolder(item) {
  const res = await fetch('/api/import/folder-files', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ path: item.path }),
  }).catch(() => null);
  const data = res && res.ok ? await readJson(res) : null;
  if (!data || !data.is_dir) return;
  item.folder = data;
  if (impIsOpen()) renderImport();
}

// «Папка…»: the Windows folder picker, then every audio and video file in it is added where it is;
// without that picker, the window with its path field
// «Обзор…» beside the path in the window: the Windows folder picker; the folder goes into the window's list
// (the window keeps its parameters). Without the picker the field stays for a typed path
async function impBrowsePath() {
  const res = await fetch('/api/import/pick-folder', { method: 'POST' }).catch(() => null);
  const data = res && res.ok ? await readJson(res) : null;
  if (!data || !data.available) { document.getElementById('local-path-input')?.focus(); return; }
  if (data.path) impAddPaths([data.path]);
}

async function impPickFolder() {
  const res = await fetch('/api/import/pick-folder', { method: 'POST' }).catch(() => null);
  const data = res && res.ok ? await readJson(res) : null;
  if (!data || !data.available) { openImportDialog({ mode: 'folder' }); return; }
  if (data.path) await importPaths([data.path], 'folder');
}

// The window's modes (asked by the user: each item of the ▾ menu opened the same window): its icon and title
const IMP_ICONS = {
  files: '<path d="M7 3.5h7l4 4v13H7z"/><path d="M14 3.5v4h4M10 14.5l2-2 2 2M12 12.5v5"/>',
  folder: '<path d="M3.5 7.5a2 2 0 012-2h4l2 2h7a2 2 0 012 2v8a2 2 0 01-2 2h-13a2 2 0 01-2-2z"/>',
  link: '<path d="M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 00-5.7 0l-3 3a4 4 0 005.7 5.7l1-1"/>',
  all: '<path d="M12 4v11M7.5 10.5L12 15l4.5-4.5M5 19.5h14"/>',
};
const IMP_TITLES = { files: 'impTitleFiles', folder: 'impTitleFolder', link: 'impTitleLink', all: 'impTitle' };

// The ▾ of «＋ Импорт ▾» in the strip on top: what to import, with an icon each; each item opens the window in
// its mode (the files and the folder go at once when the window should not ask); files can also be dropped on the
// window on any screen
const IMP_MENU = [
  ['files', IMP_ICONS.files, 'impMenuFiles', 'impMenuFilesSub', 'Ctrl+O', () => openImport()],
  ['folder', IMP_ICONS.folder, 'impMenuFolder', 'impMenuFolderSub', '', () => (askImportParams() ? openImportDialog({ mode: 'folder' }) : impPickFolder())],
  ['link', IMP_ICONS.link, 'impMenuLink', 'impMenuLinkSub', '', () => openImportDialog({ mode: 'link' })],
  ['all', '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>', 'impMenuParams', 'impMenuParamsSub', '', () => openImportDialog({ mode: 'all' })],
];

function openImportMenu(e) {
  e.preventDefault();
  e.stopPropagation();
  const had = document.getElementById('imp-menu');
  closeImportMenu();
  if (had) return;
  const btn = e.currentTarget;
  const menu = document.createElement('div');
  menu.id = 'imp-menu';
  menu.className = 'imp-menu';
  menu.setAttribute('role', 'menu');
  menu.innerHTML = IMP_MENU.map(([k, icon, title, sub, key]) => `<button type="button" class="imp-menu-row" role="menuitem" data-imp="${k}">`
    + `<span class="imp-menu-ic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icon}</svg></span>`
    + `<span class="imp-menu-tx"><b>${escapeHtml(t(title))}</b><small>${escapeHtml(t(sub))}</small></span>`
    + `<span>${key ? `<kbd class="imp-kbd">${key}</kbd>` : ''}</span></button>`).join('')
    + `<div class="imp-menu-note">${escapeHtml(t('impMenuDrop'))}</div>`;
  menu.addEventListener('click', ev => {
    const row = ev.target.closest('[data-imp]');
    ev.stopPropagation();
    if (!row) return;
    closeImportMenu();
    IMP_MENU.find(x => x[0] === row.dataset.imp)[5]();
  });
  document.body.appendChild(menu);
  btn.setAttribute('aria-expanded', 'true');
  const r = (btn.closest('.imp-split') || btn).getBoundingClientRect();  // under the whole split button, its right edge
  menu.style.left = `${Math.max(4, Math.min(zpx(r.right) - menu.offsetWidth, viewW() - menu.offsetWidth - 4))}px`;
  menu.style.top = `${zpx(r.bottom) + 6}px`;
  nextFrame(() => menu.querySelector('button')?.focus());
}

function closeImportMenu() {
  if (!document.getElementById('imp-menu')) return;
  document.getElementById('imp-menu').remove();
  document.querySelectorAll('[data-click="openImportMenu"][aria-expanded="true"]').forEach(b => b.setAttribute('aria-expanded', 'false'));
}

document.addEventListener('click', closeImportMenu);
document.addEventListener('keydown', e => {
  const menu = document.getElementById('imp-menu');
  if (!menu) return;
  if (e.key === 'Escape') { e.preventDefault(); closeImportMenu(); return; }
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    const rows = [...menu.querySelectorAll('button')];
    const i = rows.indexOf(document.activeElement);
    rows[(i + (e.key === 'ArrowDown' ? 1 : rows.length - 1)) % rows.length].focus();
  }
});

// Opens the window in a mode (files, folder, link, all), with these files (dropped, chosen) in its list
function openImportDialog(opts = {}) {
  state.imp = impFresh();
  state.imp.mode = IMP_TITLES[opts.mode] ? opts.mode : opts.files ? 'files' : 'all';
  state.imp.moreOpen = state.imp.mode === 'all';  // «Все параметры»: the processing in sight too
  state.impPrepared = true;
  openModal('import');
  if (opts.files) impAddFiles(opts.files);
  if (state.imp.mode === 'link') impShowRow('link');
}

// The segmented control on top of the window: another mode, the list and the options kept
function impSetMode(mode) {
  if (!IMP_TITLES[mode] || !state.imp) return;
  state.imp.mode = mode;
  if (mode === 'all') state.imp.moreOpen = true;
  renderImport();
  if (mode === 'link') impShowRow('link');
}

// core.js openModal('import'): from any button that opens the window as it is
function onImportDialogOpen() {
  if (!state.impPrepared || !state.imp) state.imp = impFresh();
  state.impPrepared = false;
  const s = impSettings();
  const lang = document.getElementById('upload-language');
  lang.value = s.language || 'auto';
  if (!lang.value) lang.value = 'auto';
  const spk = document.getElementById('upload-speakers');
  spk.value = String(s.num_speakers || 0);
  if (!spk.value) spk.value = '0';
  document.getElementById('imp-remember').checked = false;
  document.getElementById('imp-noask').checked = !askImportParams();
  renderModelHints();
  renderImport();
}

function impIsOpen() {
  return !document.getElementById('modal-import').classList.contains('hidden');
}

function impModelIsWhisper(id = document.getElementById('upload-model').value) {
  const item = (state.whisperCatalog || []).find(i => i.id === id);
  return item ? item.engine !== 'onnx' : !/gigaam|parakeet/i.test(id || '');
}

// --- The list: files, links, paths ---
function impExt(name) {
  const m = /\.([a-z0-9]{1,5})$/i.exec(name || '');
  return m ? m[1].toUpperCase() : '';
}

function impAddFiles(fileList) {
  const imp = state.imp || (state.imp = impFresh());
  for (const file of Array.from(fileList || [])) {
    if (imp.items.some(x => x.kind === 'file' && x.file.name === file.name && x.file.size === file.size)) continue;
    const item = { id: ++imp.seq, kind: 'file', file, dur: null };
    imp.items.push(item);
    impProbeDuration(file).then(sec => { item.dur = sec; if (impIsOpen()) renderImport(); });
  }
  document.getElementById('file-input').value = '';
  renderImport();
}

// The length of a file: read from its header by the browser (a format it cannot play gives no length)
function impProbeDuration(file) {
  return new Promise(resolve => {
    const url = URL.createObjectURL(file);
    const el = document.createElement(/^video\//.test(file.type) ? 'video' : 'audio');
    const done = (v) => { URL.revokeObjectURL(url); el.removeAttribute('src'); resolve(v); };
    el.preload = 'metadata';
    el.addEventListener('loadedmetadata', () => done(Number.isFinite(el.duration) ? el.duration : null), { once: true });
    el.addEventListener('error', () => done(null), { once: true });
    setTimeout(() => done(null), 8000);
    el.src = url;
  });
}

async function impDropFiles(e) {
  e.preventDefault();
  e.stopPropagation();  // not the drop of the whole window under it
  hideDropOverlay();
  const files = Array.from((e.dataTransfer && e.dataTransfer.files) || []);
  const media = files.filter(isMediaFile);
  if (media.length < files.length) {
    const skipped = files.filter(f => !isMediaFile(f)).map(f => f.name).slice(0, 3).join(', ');
    showToast(t('dropSkipped').replace('{names}', () => skipped));
  }
  if (!media.length) return;
  const paths = await nativeDropPaths(media);
  if (paths) impAddPaths(paths);
  else impAddFiles(media);
}

// A drop on the app's window: the window (run.py) tells the dropped files' places on disk, so they are
// added where they are, as with «Файлы…» — without it a 4 GB video was copied to the system disk. In
// a browser, with copying turned on in Settings, or when the places do not come: the files' content
let _nativeDrop = null;
function nativeDropPaths(media) {
  const s = (state.system && state.system.settings) || {};
  if (!(window.pywebview && window.pywebview.api) || String(s.import_copy) === 'true') return Promise.resolve(null);
  return new Promise(resolve => {
    const names = media.map(f => f.name);
    const timer = setTimeout(() => { _nativeDrop = null; resolve(null); }, 1500);
    _nativeDrop = (paths) => {
      const byName = new Map(paths.map(p => [String(p).split(/[\\/]/).pop(), p]));
      const found = names.map(n => byName.get(n)).filter(Boolean);
      if (found.length !== names.length) return;  // another drop's places, or not all of them yet
      clearTimeout(timer);
      _nativeDrop = null;
      resolve(found);
    };
  });
}

// Called by the window (run.py) with the places of the files dropped on it
function onNativeDrop(paths) {
  if (_nativeDrop && Array.isArray(paths)) _nativeDrop(paths);
}

// The link and path fields are always shown: opened «with a link» or «with a path», the window puts the cursor there
function impShowRow(kind) {
  const row = document.getElementById(kind === 'link' ? 'imp-link-row' : 'imp-path-row');
  nextFrame(() => row.querySelector('input').focus());
}

function impAddLink() {
  const input = document.getElementById('url-import-input');
  const url = input.value.trim();
  if (!url) return;
  if (!/^https?:\/\/\S+$/i.test(url)) { showWarning(t('impBadLink')); return; }
  const imp = state.imp;
  if (!imp.items.some(x => x.kind === 'link' && x.url === url)) imp.items.push({ id: ++imp.seq, kind: 'link', url });
  input.value = '';
  renderImport();
}

function impAddPath() {
  const input = document.getElementById('local-path-input');
  const path = input.value.trim().replace(/^["']|["']$/g, '');
  if (!path) return;
  const imp = state.imp;
  impPushPath(imp, path);
  input.value = '';
  renderImport();
}

function impRemove(id) {
  state.imp.items = state.imp.items.filter(x => x.id !== Number(id));
  renderImport();
}

function impRowHtml(x) {
  let name, sub, ext, tone;
  if (x.kind === 'file') {
    name = x.file.name;
    ext = impExt(name) || '—';
    tone = /^video\//.test(x.file.type) ? 'imp-tile-video' : 'imp-tile-audio';
    sub = t(/^video\//.test(x.file.type) ? 'impKindVideo' : 'impKindAudio');
  } else if (x.kind === 'link') {
    let host = x.url;
    try { const u = new URL(x.url); host = u.host + (u.pathname.length > 1 ? u.pathname : ''); } catch (e) {}
    name = host;
    ext = '↗';
    tone = 'imp-tile-link';
    sub = t('impKindLink');
  } else {
    name = x.path;
    ext = '▤';
    tone = 'imp-tile-path';
    const f = x.folder;
    sub = !f ? t('impKindPath') : f.count ? `${t('impKindFolder')} · ${plural(f.count, t('impItemsForms'))}` : `${t('impKindFolder')} · ${t('impFolderNone')}`;
  }
  const dur = x.kind === 'file' ? (x.dur != null ? formatTime(x.dur) : '…') : '';
  const size = x.kind === 'file' ? impFormatBytes(x.file.size) : '';
  return `<div class="imp-row">
      <span class="imp-tile ${tone}" aria-hidden="true">${escapeHtml(ext)}</span>
      <span class="min-w-0 flex flex-col"><span class="imp-row-name" title="${escapeHtml(name)}">${escapeHtml(name)}</span><span class="imp-row-sub">${escapeHtml(sub)}</span></span>
      <span class="imp-row-dur">${escapeHtml(dur)}</span>
      <span class="imp-row-size">${escapeHtml(size)}</span>
      <button ${pageCall('click', 'impRemove', [x.id])} class="imp-x" title="${escapeHtml(t('impRemove'))}">✕</button>
    </div>${impFolderListHtml(x.folder)}`;
}

// The files of a folder under its row: the first few, then how many more
const IMP_FOLDER_SHOWN = 6;
function impFolderListHtml(f) {
  if (!f || !f.files || !f.files.length) return '';
  const rows = f.files.slice(0, IMP_FOLDER_SHOWN).map(file => `<div class="imp-sub-row">`
    + `<span class="imp-sub-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</span>`
    + `<span class="imp-sub-size">${escapeHtml(impFormatBytes(file.size))}</span></div>`).join('');
  const more = f.count > IMP_FOLDER_SHOWN ? `<div class="imp-sub-more">${escapeHtml(t('impFolderMore').replace('{n}', () => String(f.count - IMP_FOLDER_SHOWN)))}</div>` : '';
  return `<div class="imp-sub-list">${rows}${more}</div>`;
}

function impFormatBytes(n) {
  if (!n) return '';
  if (n >= 1 << 30) return `${(n / (1 << 30)).toFixed(1)} ${t('impGB')}`;
  return `${Math.max(1, Math.round(n / (1 << 20)))} ${t('impMB')}`;
}

// How many recordings the list makes: a folder counts its audio and video files once the server has listed them
function impCount(items) {
  return items.reduce((a, x) => a + (x.folder ? x.folder.count : 1), 0);
}

// "3 файла · 2 ч 14 мин"
function impSummaryText(items) {
  if (!items.length) return t('impNothing');
  const sec = items.reduce((a, x) => a + (x.dur || 0), 0);
  const h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60);
  const len = !sec ? '' : !h && !m ? ` · ${t('impUnderMinute')}` : ` · ${h ? `${h} ${t('impHours')} ` : ''}${m} ${t('impMinutes')}`;
  return plural(impCount(items), t('impItemsForms')) + len;
}

// --- How long it will take: by the length of the files and the speed of this computer ---
function impEta(items, whisper) {
  const sec = items.reduce((a, x) => a + (x.dur || 0), 0);
  if (!sec) return null;
  const hw = (state.system && state.system.hardware) || {};
  const gpu = !!hw.cuda_available;
  // times faster than real time, roughly: what the bench measures on common cards and processors
  const speed = gpu ? (whisper ? 25 : 60) : (whisper ? 3 : 15);
  const extra = (state.imp.proc.diarization ? 1.15 : 1) * (state.imp.proc.denoise || state.imp.proc.loudnorm ? 1.05 : 1);
  const min = Math.max(1, Math.round((sec / speed) * extra / 60));
  const device = gpu ? String(hw.device_name || '').replace(/^NVIDIA (GeForce )?/, '') : t('impCpu');
  return { min, device };
}

// The mode in the window: its title and icon, the chosen segment, the fields that belong to it
function impRenderMode(imp) {
  const mode = IMP_TITLES[imp.mode] ? imp.mode : 'all';
  document.querySelector('#modal-import .imp-card').dataset.mode = mode;
  document.getElementById('imp-title').textContent = t(IMP_TITLES[mode]);
  document.getElementById('imp-head-ic').innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${IMP_ICONS[mode]}</svg>`;
  document.querySelectorAll('#imp-modes [data-imp-mode]').forEach(b => b.setAttribute('aria-checked', String(b.dataset.impMode === mode)));
  document.querySelectorAll('#modal-import [data-imp-modes]').forEach(el => el.toggleAttribute('data-imp-off', !el.dataset.impModes.split(' ').includes(mode)));
  document.getElementById('imp-folder-empty').classList.toggle('hidden', imp.items.some(x => x.kind === 'path'));
}

function renderImport() {
  const imp = state.imp || (state.imp = impFresh());
  const items = imp.items;
  impRenderMode(imp);
  document.getElementById('imp-list').innerHTML = items.map(impRowHtml).join('');
  document.getElementById('imp-empty').classList.toggle('hidden', items.length > 0);
  document.getElementById('imp-summary').textContent = impSummaryText(items);
  const whisper = impModelIsWhisper();

  const eta = impEta(items, whisper);
  document.getElementById('imp-eta').classList.toggle('hidden', !eta);
  if (eta) {
    document.getElementById('imp-eta-text').innerHTML = escapeHtml(t('impEtaText')).replace('{min}', () => `<b>${eta.min} ${escapeHtml(t('impMinutes'))}</b>`)
      .replace('{device}', () => `<span class="imp-eta-dev">${escapeHtml(eta.device)}</span>`);
  }

  const card = ([key, label, hint, only]) => {
    const off = (only === 'onnx' && whisper) || (only === 'whisper' && !whisper);
    const on = !off && !!imp.proc[key];
    const tag = off ? `<span class="imp-tag">· ${escapeHtml(t(only === 'whisper' ? 'impOnlyWhisper' : 'impNotWhisper'))}</span>` : '';
    return `<label class="imp-opt${on ? ' imp-opt-on' : ''}${off ? ' imp-opt-off' : ''}">
        <span class="min-w-0 flex-1 flex flex-col gap-0.5"><span class="imp-opt-label">${escapeHtml(t(label))} ${tag}</span><span class="imp-opt-hint">${escapeHtml(t(hint))}</span></span>
        <input type="checkbox" role="switch" class="vs-switch" ${on ? 'checked' : ''} ${off ? 'disabled' : ''} ${pageCall('change', 'impToggle', [key, { $: 'checked' }])} />
      </label>`;
  };
  document.getElementById('imp-sound').innerHTML = IMP_SOUND.map(card).join('');
  document.getElementById('imp-after').innerHTML = IMP_AFTER.map(([k, l, h]) => card([k, l, h, ''])).join('');
  document.getElementById('imp-ensemble').innerHTML = card(IMP_ENSEMBLE) + impAddOnlyHtml(imp);
  // only added: the recognition's choices do not apply, the button says what it does
  document.querySelector('#modal-import .imp-card').classList.toggle('imp-add-only', !imp.proc.transcribe);
  const def = impDefaults();
  const asSettings = IMP_SOUND.every(([k]) => imp.proc[k] === def[k]) && IMP_AFTER.every(([k]) => imp.proc[k] === def[k]);
  document.getElementById('imp-reset').classList.toggle('hidden', IMP_SOUND.every(([k]) => imp.proc[k] === def[k]));
  // audit 8.3: one line says how the files will be processed; the switches open under «Изменить»
  document.querySelector('#modal-import .imp-card').classList.toggle('imp-more-open', !!imp.moreOpen);
  document.getElementById('imp-more-summary').textContent = t(asSettings ? 'impMoreAsSettings' : 'impMoreChanged');
  const moreBtn = document.getElementById('imp-more-btn');
  moreBtn.textContent = t(imp.moreOpen ? 'impMoreClose' : 'impMoreOpen');
  moreBtn.setAttribute('aria-expanded', String(!!imp.moreOpen));

  const go = document.getElementById('imp-go');
  const verb = t(imp.proc.transcribe ? 'impGo' : 'impAddOnlyGo');
  go.textContent = impCount(items) ? `${verb} ${plural(impCount(items), t('impItemsForms'))}` : verb;
  go.disabled = !items.length;
}

// «Только добавить, без распознавания»: a switch, on when the files only go to the library
function impAddOnlyHtml(imp) {
  const on = !imp.proc.transcribe;
  return `<label class="imp-opt${on ? ' imp-opt-on' : ''} mt-2">
      <span class="min-w-0 flex-1 flex flex-col gap-0.5"><span class="imp-opt-label">${escapeHtml(t('impAddOnly'))}</span><span class="imp-opt-hint">${escapeHtml(t('impAddOnlyHint'))}</span></span>
      <input type="checkbox" role="switch" class="vs-switch" ${on ? 'checked' : ''} ${pageCall('change', 'impToggleAddOnly', [{ $: 'checked' }])} />
    </label>`;
}

function impToggleAddOnly(on) {
  state.imp.proc.transcribe = !on;
  renderImport();
}

function impToggleMore() {
  state.imp.moreOpen = !state.imp.moreOpen;
  renderImport();
}

function impToggle(key, on) {
  state.imp.proc[key] = !!on;
  renderImport();
}

function impResetSound() {
  const def = impDefaults();
  for (const [k] of IMP_SOUND) state.imp.proc[k] = def[k];
  renderImport();
}

function impOnModel() {
  renderModelHints();
  renderImport();
}

// --- Start: each file with the chosen processing; the window stays open on an error ---
// A link to a playlist or a channel: all its videos (each a recording, in a folder of its own) or the
// first one. Asked only when the site says it is a list of several videos
async function impAskPlaylist(url) {
  const res = await fetch('/api/meetings/url/probe', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url }),
  }).catch(() => null);
  const info = res && res.ok ? await readJson(res) : null;
  if (!info || !info.playlist) return false;
  const name = info.title || url;
  return confirmDialog(t('impPlaylistTitle').replace('{name}', () => name),
    t('impPlaylistText').replace('{n}', () => plural(info.count, t('impVideoForms'))).replace('{name}', () => name),
    `${t('impPlaylistAll')} (${info.count})`, false, { cancel: t('impPlaylistFirst') });
}

// «Recognize»: the window closes at once. Links and paths are only a request each; files go to the
// library in the background with their progress in a notice (a large video takes a while to copy)
async function impSubmit() {
  const imp = state.imp;
  if (!imp.items.length || (imp.proc.transcribe && !requireRecognitionModel())) return;  // only added: no model needed
  const model = document.getElementById('upload-model').value;
  const language = document.getElementById('upload-language').value;
  const speakers = Number(document.getElementById('upload-speakers').value || 0);
  const whisper = impModelIsWhisper(model);
  // what does not apply to the chosen model is sent off, so the recording shows what was done
  const processing = { ...imp.proc, leveling: !whisper && imp.proc.leveling, vad: whisper && imp.proc.vad };
  const go = document.getElementById('imp-go');
  go.disabled = true;
  go.textContent = t('impSending');
  const created = [];
  // Links and paths first, while the window is open: each is one quick request, and a wrong one is
  // said here, where it can be fixed
  try {
    for (const x of imp.items.filter(i => i.kind !== 'file')) {
      const link = x.kind === 'link';
      const playlist = link ? await impAskPlaylist(x.url) : false;
      const res = await fetch(link ? '/api/meetings/url' : '/api/meetings/local-path', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...(link ? { url: x.url, playlist } : { path: x.path }), model_name: model, language, num_speakers: speakers, processing }),
      });
      const data = await readJson(res);
      if (res.status === 409 && !link) {  // already in the library: said, and the others go on
        showToast(serverText(data.detail));
        imp.items = imp.items.filter(i => i !== x);
        continue;
      }
      if (!res.ok) throw new Error(serverText(data.detail) || `HTTP ${res.status}`);
      created.push(...(data.created || []));
      imp.items = imp.items.filter(i => i !== x);  // what went is not sent twice if a later one fails
    }
  } catch (err) {
    showError(humanError(err.message || err).short);
    renderImport();
    if (created.length) await loadMeetingsList();
    return;
  }
  const files = imp.items.filter(x => x.kind === 'file').map(x => x.file);
  const remember = document.getElementById('imp-remember').checked;
  const noAsk = document.getElementById('imp-noask').checked;
  const values = {};
  if (remember) {
    Object.assign(values, {
      whisper_model: model, language, num_speakers: String(speakers),
      proc_denoise: String(imp.proc.denoise), proc_loudnorm: String(imp.proc.loudnorm), proc_leveling: String(imp.proc.leveling),
      audio_enhance: String(imp.proc.denoise || imp.proc.loudnorm), vad_filter: String(imp.proc.vad),
      diarization_enabled: String(imp.proc.diarization), auto_summary: String(imp.proc.summary),
      asr_ensemble: String(!!imp.proc.ensemble),
    });
  }
  if (noAsk === askImportParams()) values.ask_import_params = String(!noAsk);
  closeModal('import');
  state.imp = impFresh();
  if (Object.keys(values).length) await impSaveSettings(values);
  const view = state.appView;
  const show = async (made) => {
    if (!made.length) return;
    // the library opens on the first one, unless the user went elsewhere meanwhile
    if (state.appView === view || state.appView === 'library') {
      switchAppView('library');
      await loadMeetingsList();
      await selectMeeting(made[0].id, true);
    } else {
      await loadMeetingsList();
    }
    showToast(t(processing.transcribe === false ? 'impAddedOnly' : 'impQueued').replace('{n}', () => plural(made.length, t('impItemsForms'))), null, 'success');
  };
  if (created.length) await show(created);
  if (files.length) uploadInBackground(files, { source: 'import', model, language, speakers, processing }, show);
}

async function impSaveSettings(values) {
  const res = await fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ settings: values }) });
  if (!res.ok) { showError(serverText((await readJson(res)).detail)); return; }
  if (state.system) state.system.settings = { ...(state.system.settings || {}), ...values };
}
