// Verbaliox page script: the library as a table on the whole window (static/parts/libtable.html), like the
// columns of Windows Explorer: a column per property, sorted by a click on its header, widths dragged
// at the header's edge, the columns chosen in «Столбцы». Kept per computer in localStorage.
// The parts are classic scripts sharing one global scope, loaded in order by index.html.

// Every column: its default width (the name takes what is left) and the value it is sorted by
const LT_COLS = {
  name: { w: 0, key: m => libTitle(m) || m.filename || '' },
  feature: { w: 170, key: m => { const f = featureById((m.features || [])[0]); return f ? f.name : ''; } },
  date: { w: 116, key: m => m.recorded_at || m.created_at || '' },
  duration: { w: 76, key: m => Number(m.duration) || 0 },
  people: { w: 210, key: m => ltPeople(m).length },
  lang: { w: 62, key: m => ltLang(m) },
  status: { w: 150, key: m => ltStatus(m)[2] },
  added: { w: 116, key: m => m.created_at || '' },
  size: { w: 86, key: m => Number(m.size_bytes) || 0 },
  model: { w: 150, key: m => m.transcript_model || m.model_name || '' },
  tasks: { w: 72, key: m => ltTaskCount(m.id) },
  folder: { w: 150, key: m => ltFolder(m) },
};
const LT_DEFAULT_COLS = ['name', 'feature', 'date', 'duration', 'people', 'lang', 'status'];
const LT_MORE_COLS = ['added', 'size', 'model', 'tasks', 'folder'];
const LT_GROUPS = ['day', 'feature', 'folder', 'none'];
const LT_KEY = 'verbaliox_library_table';

const LT = { prefs: null, cur: null, anchor: null, q: '', ids: [], taskCounts: null };

function ltPrefs() {
  if (LT.prefs) return LT.prefs;
  let p = {};
  try { p = JSON.parse(localStorage.getItem(LT_KEY) || '{}') || {}; } catch (e) {}
  const cols = Array.isArray(p.cols) ? p.cols.filter(c => LT_COLS[c]) : [];
  return LT.prefs = {
    cols: cols.includes('name') ? cols : [...LT_DEFAULT_COLS],
    widths: p.widths && typeof p.widths === 'object' ? p.widths : {},
    sort: LT_COLS[p.sort] ? p.sort : 'date',
    dir: p.dir === 'asc' ? 'asc' : 'desc',
    group: LT_GROUPS.includes(p.group) ? p.group : 'day',
    feature: typeof p.feature === 'string' ? p.feature : '',
  };
}

function ltSave(changes) {
  LT.prefs = { ...ltPrefs(), ...changes };
  try { localStorage.setItem(LT_KEY, JSON.stringify(LT.prefs)); } catch (e) {}
}

// --- The values of a recording ---
function ltPeople(m) {
  return Object.values(m.speakers || {}).filter(s => s && typeof s === 'object' && String(s.name || '').trim());
}

function ltLang(m) {
  return m.language && m.language !== 'auto' ? String(m.language).toUpperCase() : '';
}

function ltFolder(m) {
  const f = m.folder_id != null ? folderById(m.folder_id) : null;
  return f ? folderName(f) : '';
}

// [label, colour, order]: what is wrong first, then what is running, then the finished ones
function ltStatus(m) {
  if (m.status === 'failed') return [t('statusFailed'), '#FF453A', 0];
  if (m.status === 'queued') return [t('ltQueued'), '#FF9F0A', 1];
  if (!DONE_STATUSES.includes(m.status)) return [`${t('ltBusy')} ${Number(m.progress) || 0}%`, '#FF9F0A', 2];
  if (m.status === 'cancelled') return [t('statusCancelled'), '#8E8E93', 3];
  if (m.status === 'cleared') return [t('statusClearedShort'), '#8E8E93', 4];
  if (m.status === 'added') return [t('statusAddedShort'), '#8E8E93', 5];
  if (m.has_summary) return [t('ltAnalysed'), '#30D158', 7];
  return [t('ltTranscribed'), 'var(--accent)', 6];  // the theme's accent
}

// Open tasks of each recording (the tasks page's list, loaded when the column is shown)
function ltTaskCount(id) {
  if (!LT.taskCounts) {
    if (!(typeof TK !== 'undefined' && TK.loaded)) return 0;
    LT.taskCounts = new Map();
    for (const x of TK.data.tasks || []) {
      if (x.meeting_id == null || (typeof tkIsDone === 'function' && tkIsDone(x))) continue;
      LT.taskCounts.set(x.meeting_id, (LT.taskCounts.get(x.meeting_id) || 0) + 1);
    }
  }
  return LT.taskCounts.get(id) || 0;
}

function ltDate(s) {
  const d = new Date(String(s || '').replace(' ', 'T'));
  if (isNaN(d)) return '';
  const p = n => String(n).padStart(2, '0');
  const year = d.getFullYear() === new Date().getFullYear() ? '' : `.${String(d.getFullYear()).slice(2)}`;
  return `${p(d.getDate())}.${p(d.getMonth() + 1)}${year} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

// --- The cells ---
const LT_DASH = '<span class="lt-dim">—</span>';

function ltCell(col, m) {
  switch (col) {
    case 'name':
      return `<span class="lt-name"><span class="lt-ico">${m.is_video ? ICON_FILE_VIDEO : ICON_FILE_AUDIO}</span>`
        + `<span class="lt-ell" title="${escapeHtml(libTitle(m))}">${escapeHtml(libTitle(m) || m.filename || '')}</span></span>`;
    case 'feature': {
      const chip = libFeatureChip(m);
      return chip ? `<span class="lt-ft">${chip}</span>` : LT_DASH;
    }
    case 'date': return `<span class="lt-mono">${escapeHtml(ltDate(m.recorded_at || m.created_at))}</span>`;
    case 'added': return `<span class="lt-mono">${escapeHtml(ltDate(m.created_at))}</span>`;
    case 'duration': return m.duration ? `<span class="lt-mono">${escapeHtml(formatTime(m.duration))}</span>` : LT_DASH;
    case 'size': return m.size_bytes ? `<span class="lt-mono">${escapeHtml(formatSize(m.size_bytes))}</span>` : LT_DASH;
    case 'people': {
      const ps = ltPeople(m);
      if (!ps.length) return LT_DASH;
      const names = ps.map(s => s.name.trim());
      const shown = names.length > 3 ? `${names.slice(0, 2).join(', ')} +${names.length - 2}` : names.join(', ');
      return `<span class="lt-people" title="${escapeHtml(names.join(', '))}"><span class="lt-avs">`
        + ps.slice(0, 3).map((s, i) => `<span class="lt-av" style="--av:${/^#[0-9A-Fa-f]{6}$/.test(s.color || '') ? s.color : TK_COLORS[i % TK_COLORS.length]}">${escapeHtml(s.name.trim().charAt(0).toUpperCase())}</span>`).join('')
        + `</span><span class="lt-ell">${escapeHtml(shown)}</span></span>`;
    }
    case 'lang': return ltLang(m) ? `<span class="lt-dim">${escapeHtml(ltLang(m))}</span>` : LT_DASH;
    case 'status': {
      const [label, color] = ltStatus(m);
      const tip = m.status === 'failed' && m.error_message ? humanError(m.error_message).short : label;
      return `<span class="lt-st" title="${escapeHtml(tip)}"><i style="background:${color}"></i><span class="lt-ell">${escapeHtml(label)}</span></span>`;
    }
    case 'model': return (m.transcript_model || m.model_name) ? `<span class="lt-ell lt-dim">${escapeHtml(m.transcript_model || m.model_name)}</span>` : LT_DASH;
    case 'tasks': { const n = ltTaskCount(m.id); return n ? `<span class="lt-mono">${n}</span>` : LT_DASH; }
    case 'folder': return ltFolder(m) ? `<span class="lt-ell">${escapeHtml(ltFolder(m))}</span>` : LT_DASH;
  }
  return '';
}

// --- What is shown: the search, the feature, the sort and the groups ---
function ltMatches(m) {
  const p = ltPrefs();
  if (p.feature === 'none' ? (m.features || []).length : p.feature && !(m.features || []).includes(p.feature)) return false;
  const q = LT.q.trim().toLocaleLowerCase();
  if (!q) return true;
  const hay = [libTitle(m), m.title, m.filename, ...ltPeople(m).map(s => s.name),
    ...(m.features || []).map(id => (featureById(id) || {}).name || ''), ltFolder(m)].join('\n').toLocaleLowerCase();
  return q.split(/\s+/).every(w => hay.includes(w));
}

function ltSorted(list) {
  const p = ltPrefs();
  const key = LT_COLS[p.sort].key;
  const sign = p.dir === 'asc' ? 1 : -1;
  const vals = new Map(list.map(m => [m.id, key(m)]));
  return list.slice().sort((a, b) => {
    const x = vals.get(a.id), y = vals.get(b.id);
    const c = typeof x === 'string' ? (p.sort === 'date' || p.sort === 'added' ? (x < y ? -1 : x > y ? 1 : 0) : _libCollator.compare(x, y)) : x - y;
    return (c || b.id - a.id) * sign;
  });
}

// [[label, recordings]] in the order of the groups: days newest first (oldest first when the dates
// are sorted up), features and folders by name, the recordings without one last
function ltGroups(list) {
  const p = ltPrefs();
  if (p.group === 'none') return [['', list]];
  const keyOf = {
    day: m => String(m.recorded_at || m.created_at || '').slice(0, 10),
    feature: m => String((m.features || [])[0] || ''),
    folder: m => (m.folder_id != null && folderById(m.folder_id) ? String(m.folder_id) : ''),
  }[p.group];
  const label = {
    day: k => libDateLabel(k, 'day'),
    feature: k => libDateLabel(k, 'feature'),
    folder: k => (k ? ltFolder({ folder_id: Number(k) }) : t('ltNoFolder')),
  }[p.group];
  const buckets = new Map();
  for (const m of list) {
    const k = keyOf(m);
    if (!buckets.has(k)) buckets.set(k, []);
    buckets.get(k).push(m);
  }
  const keys = [...buckets.keys()];
  if (p.group === 'day') keys.sort((a, b) => (a < b ? 1 : a > b ? -1 : 0) * (p.sort === 'date' && p.dir === 'asc' ? -1 : 1));
  else keys.sort((a, b) => (!a) - (!b) || _libCollator.compare(label(a), label(b)));
  return keys.map(k => [label(k), buckets.get(k)]);
}

// --- Drawing ---
function ltWidth(col) {
  const w = Number(ltPrefs().widths[col]);
  return w >= 40 ? Math.min(w, 900) : LT_COLS[col].w;
}

function ltIsPicked(id) {
  return state.multi.size ? state.multi.has(id) : LT.cur === id;
}

function renderLibTable() {
  if (state.appView !== 'libtable') return;
  const p = ltPrefs();
  const table = document.getElementById('lt-table');
  if (!table) return;
  const all = state.meetings || [];
  const shown = all.filter(ltMatches);
  const groups = ltGroups(ltSorted(shown));
  const cols = p.cols;
  // once per showing: a failed load must not ask again at every drawing
  if (cols.includes('tasks') && typeof TK !== 'undefined' && !TK.loaded && !LT.tasksAsked) {
    LT.tasksAsked = true;
    loadTasks().catch(() => {}).finally(() => { if (TK.loaded) renderLibTable(); });
  }
  LT.taskCounts = null;
  document.getElementById('lt-count').textContent = shown.length === all.length
    ? plural(all.length, t('ltCountForms'))
    : t('ltCountOf').replace('{n}', () => shown.length).replace('{all}', () => all.length);
  const fBtn = document.getElementById('lt-feature-btn');
  const fName = p.feature === 'none' ? t('ftNoFeature') : p.feature ? (featureById(p.feature) || {}).name : '';
  fBtn.textContent = `${t('ltFeature')}${fName ? `: ${fName}` : ''} ▾`;
  fBtn.classList.toggle('lt-btn-on', !!fName);
  document.getElementById('lt-group-btn').textContent = `${t('ltGroup')}: ${t(`ltGroup_${p.group}`)} ▾`;

  const arrow = p.dir === 'asc' ? '▴' : '▾';
  const head = cols.map(c => `<th data-col="${c}" class="${p.sort === c ? 'lt-sorted' : ''}" title="${escapeHtml(t('ltSortTip'))}">`
    + `<span class="lt-th">${escapeHtml(t(`ltCol_${c}`))}${p.sort === c ? `<span class="lt-arrow">${arrow}</span>` : ''}</span>`
    + (c === 'name' ? '' : `<span class="lt-rs" data-rs="${c}" title="${escapeHtml(t('ltResizeTip'))}"></span>`) + '</th>').join('');
  const minW = cols.reduce((s, c) => s + (c === 'name' ? 260 : ltWidth(c)), 0);
  LT.ids = [];
  const body = groups.map(([label, ms]) => (label
    ? `<tr class="lt-grp"><td colspan="${cols.length}"><span>${escapeHtml(label)}</span><span class="lt-grp-n">${ms.length}</span></td></tr>` : '')
    + ms.map(m => {
      LT.ids.push(m.id);
      const on = ltIsPicked(m.id);
      const open = state.activeMeeting && state.activeMeeting.id === m.id;
      return `<tr class="lt-row${on ? ' lt-on' : ''}${open ? ' lt-open' : ''}" data-mid="${m.id}" draggable="true">`
        + cols.map(c => `<td class="lt-c-${c}">${ltCell(c, m)}</td>`).join('') + '</tr>';
    }).join('')).join('');
  table.style.minWidth = `${minW}px`;
  table.innerHTML = `<colgroup>${cols.map(c => `<col data-col="${c}"${c === 'name' ? '' : ` style="width:${ltWidth(c)}px"`}>`).join('')}</colgroup>`
    + `<thead><tr>${head}</tr></thead><tbody>${body}</tbody>`;
  const empty = document.getElementById('lt-empty');
  empty.classList.toggle('hidden', shown.length > 0);
  if (!shown.length) {
    empty.innerHTML = all.length
      ? `<div>${escapeHtml(t('libFilterNone'))}</div><button class="tk-btn tk-btn-sm" data-click="resetLibTableFilters">${escapeHtml(t('libFilterResetAll'))}</button>`
      : `<div>${escapeHtml(t('noRecordings'))}</div>`;
  }
}

function onLibTableSearch(value) {
  LT.q = value || '';
  renderLibTable();
}

function resetLibTableFilters() {
  LT.q = '';
  const q = document.getElementById('lt-q');
  if (q) q.value = '';
  ltSave({ feature: '' });
  renderLibTable();
}

// The table button in the library header: the table, or back to what the main area showed
function toggleLibTable() {
  if (state.appView === 'libtable') switchAppView(state.prevView && state.prevView !== 'libtable' ? state.prevView : state.activeMeeting ? 'library' : 'home');
  else switchAppView('libtable');
}

function syncLibTableButton() {
  const on = state.appView === 'libtable';
  const btn = document.getElementById('lib-table-btn');
  if (!btn) return;
  btn.classList.toggle('lib-table-on', on);
  btn.setAttribute('aria-pressed', on ? 'true' : 'false');
}

// --- Menus: the feature, the groups, the columns ---
function ltMenuUnder(e, items) {
  e.preventDefault();
  e.stopPropagation();
  const r = e.currentTarget.getBoundingClientRect();
  openTextMenuAt(items, r.left, r.bottom + 4);
}

const ltTick = (on, label) => `${on ? '✓' : ' '}  ${label}`;

function openLibTableFeatureMenu(e) {
  const p = ltPrefs();
  const used = new Set((state.meetings || []).flatMap(m => m.features || []));
  const feats = (state.features || []).filter(f => used.has(f.id)).sort((a, b) => _libCollator.compare(a.name, b.name));
  const pick = id => () => { ltSave({ feature: id }); renderLibTable(); };
  ltMenuUnder(e, [
    { label: ltTick(!p.feature, t('ltFeatureAll')), run: pick('') },
    { sep: true },
    ...feats.map(f => ({ label: ltTick(p.feature === f.id, f.name), run: pick(f.id) })),
    ...(feats.length ? [{ sep: true }] : []),
    { label: ltTick(p.feature === 'none', t('ftNoFeature')), run: pick('none') },
  ]);
}

function openLibTableGroupMenu(e) {
  const p = ltPrefs();
  ltMenuUnder(e, LT_GROUPS.map(g => ({ label: ltTick(p.group === g, t(`ltGroup_${g}`)), run: () => { ltSave({ group: g }); renderLibTable(); } })));
}

// The columns menu stays open while columns are ticked (several at a time), like the view menu of the list
function ltColumnsMenuHtml() {
  const p = ltPrefs();
  const item = (c) => `<button class="macos-menu-item" data-col="${c}" ${c === 'name' ? 'disabled' : ''}>`
    + `<span class="lt-ck">${p.cols.includes(c) ? '✓' : ''}</span><span class="flex-1">${escapeHtml(t(`ltColFull_${c}`))}</span></button>`;
  return `<div class="px-2.5 py-1 text-[11px] text-apple-tertiary">${escapeHtml(t('ltColumns'))}</div>`
    + LT_DEFAULT_COLS.map(item).join('')
    + '<div class="my-1 h-px bg-white/10"></div>'
    + LT_MORE_COLS.map(item).join('')
    + '<div class="my-1 h-px bg-white/10"></div>'
    + `<button class="macos-menu-item" data-col="reset"><span class="lt-ck"></span><span class="flex-1">${escapeHtml(t('ltColumnsReset'))}</span></button>`;
}

function openLibTableColumnsMenu(e) {
  e.preventDefault();
  e.stopPropagation();
  const had = document.getElementById('lt-cols-menu');
  closeLibTableColumnsMenu();
  if (had) return;
  const menu = document.createElement('div');
  menu.id = 'lt-cols-menu';
  menu.className = 'fixed w-60 macos-menu z-50';
  menu.innerHTML = ltColumnsMenuHtml();
  menu.addEventListener('click', (ev) => {
    const b = ev.target.closest('button[data-col]');
    ev.stopPropagation();
    if (!b || b.disabled) return;
    const c = b.dataset.col;
    if (c === 'reset') ltSave({ cols: [...LT_DEFAULT_COLS], widths: {} });
    else {
      const cols = ltPrefs().cols;
      // a column added goes where it stands in the menu, among the ones shown
      const order = [...LT_DEFAULT_COLS, ...LT_MORE_COLS];
      ltSave({ cols: cols.includes(c) ? cols.filter(x => x !== c) : order.filter(x => x === c || cols.includes(x)) });
    }
    menu.innerHTML = ltColumnsMenuHtml();
    renderLibTable();
  });
  document.body.appendChild(menu);
  const r = e.currentTarget.getBoundingClientRect();
  menu.style.left = `${Math.max(4, Math.min(zpx(r.right) - 240, viewW() - 244))}px`;
  menu.style.top = `${zpx(r.bottom) + 4}px`;
}

function closeLibTableColumnsMenu() {
  document.getElementById('lt-cols-menu')?.remove();
}

document.addEventListener('click', closeLibTableColumnsMenu);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeLibTableColumnsMenu(); });

// --- The rows: a click picks one (Ctrl adds, Shift takes a range), a double click or Enter opens it,
// a right click is the recording's menu, a drag puts it into a folder of the sidebar ---
function ltPick(e, id) {
  if (e.ctrlKey || e.metaKey) {
    if (!state.multi.size && LT.cur != null) state.multi.add(LT.cur);
    if (state.multi.has(id)) state.multi.delete(id); else state.multi.add(id);
    LT.anchor = id;
  } else if (e.shiftKey) {
    const from = LT.ids.indexOf(LT.anchor ?? LT.cur);
    const to = LT.ids.indexOf(id);
    state.multi = new Set(from < 0 ? [id] : LT.ids.slice(Math.min(from, to), Math.max(from, to) + 1));
    document.getSelection()?.removeAllRanges();
  } else {
    state.multi.clear();
    LT.anchor = id;
  }
  if (state.multi.size === 1) { LT.cur = [...state.multi][0]; state.multi.clear(); } else LT.cur = id;
  ltPaintPick();
  renderMeetingsSidebar();
  renderLibSelectionBar();
}

// The pick is repainted on the rows in place: the table redrawn would lose the second click of a double click
function ltPaintPick() {
  for (const tr of document.querySelectorAll('#lt-table tr[data-mid]')) tr.classList.toggle('lt-on', ltIsPicked(Number(tr.dataset.mid)));
}

function ltMove(step) {
  if (!LT.ids.length) return;
  const i = LT.ids.indexOf(LT.cur);
  LT.cur = LT.ids[Math.max(0, Math.min(LT.ids.length - 1, i < 0 ? 0 : i + step))];
  state.multi.clear();
  LT.anchor = LT.cur;
  ltPaintPick();
  renderLibSelectionBar();
  document.querySelector(`#lt-table tr[data-mid="${LT.cur}"]`)?.scrollIntoView({ block: 'nearest' });
}

(function wireLibTable() {
  const table = document.getElementById('lt-table');
  const scroll = document.getElementById('lt-scroll');
  if (!table || !scroll) return;
  const rowOf = e => e.target.closest && e.target.closest('tr[data-mid]');
  table.addEventListener('click', (e) => {
    if (e.target.closest('.lt-rs')) return;
    const th = e.target.closest('th[data-col]');
    if (th) {
      const c = th.dataset.col, p = ltPrefs();
      ltSave(p.sort === c ? { dir: p.dir === 'asc' ? 'desc' : 'asc' } : { sort: c, dir: ['name', 'feature', 'people', 'lang', 'model', 'folder'].includes(c) ? 'asc' : 'desc' });
      renderLibTable();
      return;
    }
    const row = rowOf(e);
    if (row) ltPick(e, Number(row.dataset.mid));
  });
  table.addEventListener('dblclick', (e) => {
    const row = rowOf(e);
    if (!row) return;
    state.multi.clear();
    renderLibSelectionBar();
    openMeeting(Number(row.dataset.mid));
  });
  table.addEventListener('contextmenu', (e) => {
    const row = rowOf(e);
    if (!row) return;
    const id = Number(row.dataset.mid);
    if (!state.multi.has(id)) { state.multi.clear(); LT.cur = id; ltPaintPick(); renderLibSelectionBar(); }
    openRecordingContextMenu(e, id);
  });
  table.addEventListener('dragstart', (e) => {
    const row = rowOf(e);
    if (row) libraryDragStart(e, 'm', Number(row.dataset.mid));
  });
  table.addEventListener('dragend', () => clearLibraryDrag());
  scroll.addEventListener('keydown', (e) => {
    if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || '')) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); ltMove(e.key === 'ArrowDown' ? 1 : -1); }
    else if (e.key === 'Enter' && LT.cur != null) { e.preventDefault(); openMeeting(LT.cur); }
    else if ((e.ctrlKey || e.metaKey) && e.code === 'KeyA') {
      e.preventDefault();
      state.multi = new Set(LT.ids);
      ltPaintPick();
      renderMeetingsSidebar();
      renderLibSelectionBar();
    }
  });
  // The width of a column: dragged at the right edge of its header
  table.addEventListener('pointerdown', (e) => {
    const rs = e.target.closest && e.target.closest('.lt-rs');
    if (!rs) return;
    e.preventDefault();
    e.stopPropagation();
    const c = rs.dataset.rs;
    const col = table.querySelector(`col[data-col="${c}"]`);
    const start = ltWidth(c), x0 = e.clientX;
    rs.setPointerCapture(e.pointerId);
    document.body.classList.add('lt-resizing');
    let w = start;
    const move = (ev) => {
      w = Math.max(40, Math.min(900, Math.round(start + zpx(ev.clientX - x0))));
      col.style.width = `${w}px`;
    };
    const up = () => {
      rs.removeEventListener('pointermove', move);
      rs.removeEventListener('pointerup', up);
      rs.removeEventListener('pointercancel', up);
      document.body.classList.remove('lt-resizing');
      ltSave({ widths: { ...ltPrefs().widths, [c]: w } });
      renderLibTable();
    };
    rs.addEventListener('pointermove', move);
    rs.addEventListener('pointerup', up);
    rs.addEventListener('pointercancel', up);
  });
})();

registerView('libtable', {
  show: () => {
    if (LT.cur == null && state.activeMeeting) LT.cur = state.activeMeeting.id;
    LT.tasksAsked = false;
    syncLibTableButton();
    renderLibTable();
    renderLibSelectionBar();
     nextFrame(() => document.getElementById('lt-scroll')?.focus({ preventScroll: true }));
  },
  hide: () => { syncLibTableButton(); closeLibTableColumnsMenu(); nextFrame(renderLibSelectionBar); },
  refresh: renderLibTable,
});
