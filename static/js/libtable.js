// Verbaliox page script: the section «Записи» (static/parts/libtable.html, docs/pult-plan.md, stage 4).
// Four views of the library: «Таблица» (the columns chosen in «Колонки», sorted by a click on a header,
// widths dragged at its edge), «Компактно», «Карточки» and «Папки» (the folder tree beside the list).
// The recordings are grouped by day in cards; the search finds titles, people and features here and the
// words of the transcripts on the server (/api/meetings/search), whose places are shown under the title.
// A click opens a recording; the box at its left, Ctrl and Shift select, and the bar of the selection
// takes the place of the filters. Kept per computer in localStorage.
// The parts are classic scripts sharing one global scope, loaded in order by index.html.

// Every column: its default width (the name takes what is left) and the value it is sorted by
const LT_COLS = {
  name: { w: 0, key: m => libTitle(m) || m.filename || '' },
  feature: { w: 150, key: m => { const f = featureById((m.features || [])[0]); return f ? f.name : ''; } },
  date: { w: 96, key: m => m.recorded_at || m.created_at || '' },
  duration: { w: 92, key: m => Number(m.duration) || 0 },
  people: { w: 170, key: m => ltPeople(m).length },
  lang: { w: 48, key: m => ltLang(m) },
  status: { w: 140, key: m => ltStatus(m)[2] },
  added: { w: 116, key: m => m.created_at || '' },
  size: { w: 86, key: m => Number(m.size_bytes) || 0 },
  model: { w: 150, key: m => m.transcript_model || m.model_name || '' },
  tasks: { w: 72, key: m => ltTaskCount(m.id) },
  folder: { w: 150, key: m => ltFolder(m) },
};
const LT_DEFAULT_COLS = ['name', 'feature', 'date', 'duration', 'people', 'lang', 'status'];
const LT_MORE_COLS = ['added', 'size', 'model', 'tasks', 'folder'];
const LT_ORDER = [...LT_DEFAULT_COLS.slice(1), ...LT_MORE_COLS];  // the columns of «Колонки», the name always stays
const LT_GROUPS = ['day', 'feature', 'folder', 'none'];
const LT_VIEWS = ['table', 'cards', 'folders'];
const LT_CHIPS = ['all', 'summary', 'untranscribed', 'video'];
const LT_KEY = 'verbaliox_library_table';
// The box and the kind of file before the name, in every view
const LT_LEAD = '22px 18px';

const LT = { prefs: null, cur: null, anchor: null, q: '', ids: [], taskCounts: null, hits: null, hitsQ: '', chip: 'all', colsOpen: false,
  pressed: false, later: false };  // a press in the table (a click, a column dragged): the progress waits for its end

const LT_SVG = (d, w = 14) => `<svg width="${w}" height="${w}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const LT_ICON = {
  day: '<rect x="4" y="5.5" width="16" height="14.5" rx="2"/><path d="M4 10h16M8.5 3.5v4M15.5 3.5v4"/>',
  feature: '<path d="M4 12V5a1 1 0 011-1h7l8 8-8 8z"/><circle cx="8.5" cy="8.5" r="1.3"/>',
  folder: '<path d="M3.5 7.5a2 2 0 012-2h4l2 2h7a2 2 0 012 2v8a2 2 0 01-2 2h-13a2 2 0 01-2-2z"/>',
  none: '<rect x="4" y="5" width="16" height="14" rx="2"/><path d="M8 10h8M8 14h5"/>',
  gear: '<path d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z"/><path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>',
  reset: '<path d="M4 12a8 8 0 108-8 8.3 8.3 0 00-6 2.6L4 9"/><path d="M4 4v5h5"/>',
};

function ltPrefs() {
  if (LT.prefs) return LT.prefs;
  let p = {};
  try { p = JSON.parse(localStorage.getItem(LT_KEY) || '{}') || {}; } catch (e) {}
  const cols = Array.isArray(p.cols) ? p.cols.filter(c => LT_COLS[c]) : [];
  const order = Array.isArray(p.order) ? p.order.filter(c => LT_ORDER.includes(c)) : [];
  return LT.prefs = {
    cols: cols.includes('name') ? cols : [...LT_DEFAULT_COLS],
    order: [...order, ...LT_ORDER.filter(c => !order.includes(c))],
    widths: p.widths && typeof p.widths === 'object' ? p.widths : {},
    sort: LT_COLS[p.sort] ? p.sort : 'date',
    dir: p.dir === 'asc' ? 'asc' : 'desc',
    group: LT_GROUPS.includes(p.group) ? p.group : 'day',
    feature: typeof p.feature === 'string' ? p.feature : '',
    folderFilter: typeof p.folderFilter === 'string' ? p.folderFilter : '',
    view: LT_VIEWS.includes(p.view) ? p.view : 'table',
    dense: p.dense === true || p.view === 'compact',  // «Строки: Компактные» (the former view «Компактно»)
    folder: typeof p.folder === 'string' ? p.folder : '',  // the folder open in «Папки»: its id, or 'none'
  };
}

function ltSave(changes) {
  LT.prefs = { ...ltPrefs(), ...changes };
  try { localStorage.setItem(LT_KEY, JSON.stringify(LT.prefs)); } catch (e) {}
}

// The columns shown, in the order of «Колонки»: the name first
function ltShownCols() {
  const p = ltPrefs();
  return ['name', ...p.order.filter(c => p.cols.includes(c))];
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

// Without a text that can be made again: the bar's «Расшифровать» and the chip «Не расшифрованы»
const LT_UNTRANSCRIBED = ['failed', 'cancelled', 'cleared', 'added'];

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

function ltParseDate(s) {
  const d = new Date(String(s || '').replace(' ', 'T'));
  return isNaN(d) ? null : d;
}

const ltPad = n => String(n).padStart(2, '0');

// «Дата» in one form down the column: the time under a day's heading, the day and the time without one
function ltDate(s, timeOnly = false) {
  const d = ltParseDate(s);
  if (!d) return '';
  const time = `${ltPad(d.getHours())}:${ltPad(d.getMinutes())}`;
  if (timeOnly) return time;
  const year = d.getFullYear() === new Date().getFullYear() ? '' : `.${String(d.getFullYear()).slice(2)}`;
  return `${ltPad(d.getDate())}.${ltPad(d.getMonth() + 1)}${year} ${time}`;
}

function ltByDay() {
  return ltPrefs().group === 'day' && ltPrefs().view !== 'cards' && ltPrefs().view !== 'folders';
}

// --- The cells ---
const LT_DASH = '<span class="lt-dim">—</span>';

function ltKind(m) {
  return `<span class="lt-kind" title="${escapeHtml(t(m.is_video ? 'ltKindVideo' : 'ltKindAudio'))}">${m.is_video ? ICON_FILE_VIDEO : ICON_FILE_AUDIO}</span>`;
}

function ltBox(m) {
  return `<span class="lt-cbx${state.multi.has(m.id) ? ' on' : ''}" data-cbx="${m.id}" role="checkbox" aria-checked="${state.multi.has(m.id)}" title="${escapeHtml(t('ltSelectTip'))}"></span>`;
}

function ltFaces(m, max = 3) {
  const ps = ltPeople(m);
  if (!ps.length) return '';
  return `<span class="lt-avs" title="${escapeHtml(ps.map(s => s.name.trim()).join(', '))}">`
    + ps.slice(0, max).map((s, i) => `<span class="lt-av" style="--av:${/^#[0-9A-Fa-f]{6}$/.test(s.color || '') ? s.color : TK_COLORS[i % TK_COLORS.length]}">${escapeHtml(s.name.trim().charAt(0).toUpperCase())}</span>`).join('')
    + (ps.length > max ? `<span class="lt-av lt-av-more">+${ps.length - max}</span>` : '') + '</span>';
}

function ltStatusChip(m) {
  const [label, color] = ltStatus(m);
  const tip = m.status === 'failed' && m.error_message ? humanError(m.error_message).short : label;
  return `<span class="lt-st" style="--st:${color}" title="${escapeHtml(tip)}"><i></i><span class="lt-ell">${escapeHtml(label)}</span></span>`;
}

// The name, with the places the search found in the text under it
function ltNameCell(m) {
  const title = libTitle(m) || m.filename || '';
  const q = LT.q.trim();
  return `<span class="lt-name"><span class="lt-ell" title="${escapeHtml(title)}">${q ? highlightSearch(escapeHtml(title), q) : escapeHtml(title)}</span>${ltSnips(m)}</span>`;
}

function ltSnips(m) {
  const hits = LT.q.trim() && LT.hits ? LT.hits.get(m.id) : null;
  if (!hits || !hits.length) return '';
  return hits.slice(0, 3).map(h => `<button type="button" class="lt-snip" data-hit="${m.id}" data-at="${Number(h.start) || 0}" title="${escapeHtml(t('tipSeekTimestamp'))}">`
    + `<span class="lt-snip-t">${escapeHtml(formatTime(h.start))}</span><span class="lt-ell">${h.speaker ? `${escapeHtml(h.speaker)}: ` : ''}${highlightSearch(escapeHtml(h.text || ''), LT.q)}</span></button>`).join('');
}

function ltCell(col, m) {
  switch (col) {
    case 'name': return ltNameCell(m);
    case 'feature': {
      const chip = libFeatureChip(m);
      return chip ? `<span class="lt-ft">${chip}</span>` : LT_DASH;
    }
    case 'date': return `<span class="lt-mono">${escapeHtml(ltDate(m.recorded_at || m.created_at, ltByDay()))}</span>`;
    case 'added': return `<span class="lt-mono">${escapeHtml(ltDate(m.created_at))}</span>`;
    case 'duration': return m.duration ? `<span class="lt-mono">${escapeHtml(formatTime(m.duration))}</span>` : LT_DASH;
    case 'size': return m.size_bytes ? `<span class="lt-mono">${escapeHtml(formatSize(m.size_bytes))}</span>` : LT_DASH;
    case 'people': {
      const ps = ltPeople(m);
      if (!ps.length) return LT_DASH;
      const names = ps.map(s => s.name.trim());
      const shown = names.length > 3 ? `${names.slice(0, 2).join(', ')} +${names.length - 2}` : names.join(', ');
      return `<span class="lt-people">${ltFaces(m)}<span class="lt-ell">${escapeHtml(shown)}</span></span>`;
    }
    case 'lang': return ltLang(m) ? `<span class="lt-dim">${escapeHtml(ltLang(m))}</span>` : LT_DASH;
    case 'status': return ltStatusChip(m);
    case 'model': return (m.transcript_model || m.model_name) ? `<span class="lt-ell lt-dim">${escapeHtml(m.transcript_model || m.model_name)}</span>` : LT_DASH;
    case 'tasks': { const n = ltTaskCount(m.id); return n ? `<span class="lt-mono">${n}</span>` : LT_DASH; }
    case 'folder': return ltFolder(m) ? `<span class="lt-ell">${escapeHtml(ltFolder(m))}</span>` : LT_DASH;
  }
  return '';
}

// --- What is shown: the chips, the feature, the folder, the search, the sort and the groups ---
function ltChipMatch(m, chip = LT.chip) {
  if (chip === 'summary') return !!m.has_summary;
  if (chip === 'untranscribed') return LT_UNTRANSCRIBED.includes(m.status);
  if (chip === 'video') return !!m.is_video;
  return true;
}

function ltTextMatch(m) {
  const q = LT.q.trim().toLocaleLowerCase();
  if (!q) return true;
  if (LT.hits && LT.hitsQ === LT.q.trim() && LT.hits.has(m.id)) return true;
  const hay = [libTitle(m), m.title, m.filename, ...ltPeople(m).map(s => s.name),
    ...(m.features || []).map(id => (featureById(id) || {}).name || ''), ltFolder(m)].join('\n').toLocaleLowerCase();
  return q.split(/\s+/).every(w => hay.includes(w));
}

function ltFolderMatch(m) {
  const p = ltPrefs();
  if (p.view === 'folders') {
    const fid = ltOpenFolder();
    return fid === 'none' ? !(m.folder_id != null && folderById(m.folder_id)) : m.folder_id === fid;
  }
  if (!p.folderFilter) return true;
  if (p.folderFilter === 'none') return !(m.folder_id != null && folderById(m.folder_id));
  const id = Number(p.folderFilter);
  return folderById(id) ? folderSubtreeIds(id).has(m.folder_id) : true;
}

function ltMatches(m, opts = {}) {
  const p = ltPrefs();
  if (p.feature === 'none' ? (m.features || []).length : p.feature && !(m.features || []).includes(Number(p.feature))) return false;
  if (!opts.anyChip && !ltChipMatch(m)) return false;
  return ltFolderMatch(m) && ltTextMatch(m);
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

// [[kind, label, recordings]] in the order of the groups: days newest first (oldest first when the dates
// are sorted up), features and folders by name, the recordings without one last
function ltGroups(list) {
  const p = ltPrefs();
  if (p.group === 'none') return [['none', t('ltAllRecordings'), list]];
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
  return keys.map(k => [p.group, label(k), buckets.get(k)]);
}

// One card per group: the icon of its kind, its name and how many recordings it holds
function ltCard(kind, label, n, inner) {
  return `<section class="lt-card"><h3 class="lt-card-h"><span class="lt-card-ic">${LT_SVG(LT_ICON[kind] || LT_ICON.none)}</span>`
    + `<span class="lt-ell">${escapeHtml(label)}</span><b class="lt-card-n">${n}</b></h3>${inner}</section>`;
}

// --- Drawing ---
function ltWidth(col) {
  const w = Number(ltPrefs().widths[col]);
  return w >= 40 ? Math.min(w, 900) : LT_COLS[col].w;
}

function ltTableTpl(cols) {
  return `${LT_LEAD} minmax(180px, 1fr) ${cols.filter(c => c !== 'name').map(c => `${ltWidth(c)}px`).join(' ')}`.trim();
}

function ltRowAttrs(m, extra = '') {
  const on = state.multi.has(m.id);
  const open = state.activeMeeting && state.activeMeeting.id === m.id;
  return `class="lt-row${extra}${on ? ' lt-on' : ''}${LT.cur === m.id ? ' lt-cur' : ''}${open ? ' lt-open' : ''}" data-mid="${m.id}" draggable="true"`;
}

// «Таблица» and «Папки» are one table: the columns of «Колонки» in their order. In «Папки» the folder
// column is left out (the tree says it) and the date is shown in full (no day's heading above it)
function ltTableHtml(groups, inFolders = false) {
  const p = ltPrefs();
  const cols = ltShownCols().filter(c => !(inFolders && c === 'folder'));
  const arrow = p.dir === 'asc' ? '▴' : '▾';
  const head = '<span></span><span></span>' + cols.map(c => `<span data-col="${c}" class="lt-hc${p.sort === c ? ' lt-sorted' : ''}" title="${escapeHtml(t('ltSortTip'))}">`
    + `<span class="lt-th">${escapeHtml(t(`ltCol_${c}`))}${p.sort === c ? `<span class="lt-arrow">${arrow}</span>` : ''}</span>`
    + (c === 'name' ? '' : `<span class="lt-rs" data-rs="${c}" title="${escapeHtml(t('ltResizeTip'))}"></span>`) + '</span>').join('');
  const body = groups.map(([kind, label, ms]) => ltCard(kind, label, ms.length, ms.map(m => {
    LT.ids.push(m.id);
    return `<div ${ltRowAttrs(m)}>${ltBox(m)}${ltKind(m)}` + cols.map(c => `<span class="lt-c lt-c-${c}">${ltCell(c, m)}</span>`).join('') + '</div>';
  }).join('') || `<div class="lt-none">${escapeHtml(t('ltFolderEmpty'))}</div>`)).join('');
  const minW = 40 + 180 + cols.filter(c => c !== 'name').reduce((s, c) => s + ltWidth(c) + 12, 0) + 40;
  return { html: `<div class="lt-hrow">${head}</div>${body}`, tpl: ltTableTpl(cols), minW };
}

// A card of «Карточки»: a frame of the video or the bars of the voices, the title, and the details ticked
// in «Колонки» (one setting for every view). A detail a recording lacks keeps its place on its card
function ltTile(m) {
  LT.ids.push(m.id);
  const on = c => ltPrefs().cols.includes(c);
  const ps = ltPeople(m);
  const colors = ps.length ? ps.map((s, i) => (/^#[0-9A-Fa-f]{6}$/.test(s.color || '') ? s.color : TK_COLORS[i % TK_COLORS.length])) : ['#8E8E93'];
  const pre = m.is_video
    ? `<div class="lt-tile-pre lt-vid"><img src="/api/meetings/${m.id}/thumb" loading="lazy" alt="" draggable="false" data-error="removeElement" data-error-args='[{"$": "el"}]'><span class="lt-play">▶</span></div>`
    : `<div class="lt-tile-pre">${Array.from({ length: 34 }, (_, k) => `<i style="height:${18 + Math.round(70 * Math.abs(Math.sin(k * 0.6 + m.id) * Math.cos(k * 0.2)))}%;background:${colors[k % colors.length]}"></i>`).join('')}</div>`;
  const when = [on('date') ? ltDate(m.recorded_at || m.created_at) : '', on('duration') && m.duration ? formatTime(m.duration) : ''].filter(Boolean).join(' · ');
  const chip = libFeatureChip(m);
  const more = [['added', () => ltDate(m.created_at)], ['folder', () => ltFolder(m)], ['tasks', () => { const n = ltTaskCount(m.id); return n ? `${t('ltCol_tasks')}: ${n}` : ''; }],
    ['lang', () => ltLang(m)], ['model', () => m.transcript_model || m.model_name || ''], ['size', () => (m.size_bytes ? formatSize(m.size_bytes) : '')]]
    .filter(([c]) => on(c));
  const moreText = more.map(([, f]) => f()).filter(Boolean).join(' · ');
  return `<div ${ltRowAttrs(m, ' lt-tile')}>${pre}<div class="lt-tile-b">`
    + `<div class="lt-tile-t">${ltKind(m)}${ltNameCell(m)}</div>`
    + (on('date') || on('duration') ? `<div class="lt-tile-m">${escapeHtml(when) || '&nbsp;'}</div>` : '')
    + (on('people') || on('status') ? `<div class="lt-tile-f">${on('people') ? ltFaces(m, 4) || `<span class="lt-dim">${escapeHtml(t('ltNoPeople'))}</span>` : '<span></span>'}${on('status') ? ltStatusChip(m) : ''}</div>` : '')
    + (on('feature') ? `<div class="lt-tile-ft">${chip ? `<span class="lt-ft">${chip}</span>` : `<span class="lt-dim">${escapeHtml(t('ftNoFeature'))}</span>`}</div>` : '')
    + (more.length ? `<div class="lt-tile-m lt-tile-more">${escapeHtml(moreText) || '&nbsp;'}</div>` : '')
    + `</div>${ltBox(m)}</div>`;
}

// «Папки»: the folder open, or the first one; 'none' is the recordings without a folder
function ltOpenFolder() {
  const v = ltPrefs().folder;
  if (v === 'none') return 'none';
  const id = Number(v);
  if (v && folderById(id)) return id;
  const first = ltFolderList().map(([f]) => f).find(f => (state.meetings || []).some(m => m.folder_id === f.id)) || sortedFolders(null)[0];
  return first ? first.id : 'none';
}

function ltFolderTree() {
  const open = ltOpenFolder();
  const count = new Map();
  let loose = 0;
  for (const m of state.meetings || []) {
    if (!ltChipMatch(m)) continue;
    if (m.folder_id != null && folderById(m.folder_id)) count.set(m.folder_id, (count.get(m.folder_id) || 0) + 1);
    else loose++;
  }
  // a folder of the user's is dragged onto another folder, or onto «Без папки» for the top level (libraryDrop)
  const row = (f, depth) => `<button type="button" class="lt-frow${open === f.id ? ' on' : ''}" data-folder="${f.id}" style="--d:${depth}"`
    + (f.system_key ? '' : ` draggable="true" data-dragstart="libraryDragStart" data-dragstart-args='[{"$": "event"}, "f", ${f.id}]'`)
    + ` data-dragover="libraryDragOver" data-dragover-args='[{"$": "event"}, ${f.id}]' data-dragleave="libraryDragLeave" data-dragleave-args='[{"$": "event"}]' data-drop="ltDropOnFolder" data-drop-args='[{"$": "event"}, ${f.id}]'>`
    + `<span class="lt-fname">${folderIcon(f)}<span class="lt-ell">${escapeHtml(folderName(f))}</span></span><span class="lt-dim">${count.get(f.id) || 0}</span></button>`
    + sortedFolders(f.id).map(c => row(c, depth + 1)).join('');
  return `<nav class="lt-ftree" aria-label="${escapeHtml(t('ltView_folders'))}">${sortedFolders(null).map(f => row(f, 0)).join('')}`
    + `<button type="button" class="lt-frow${open === 'none' ? ' on' : ''}" data-folder="none" style="--d:0"`
    + ` data-dragover="libraryDragOver" data-dragover-args='[{"$": "event"}, null]' data-dragleave="libraryDragLeave" data-dragleave-args='[{"$": "event"}]' data-drop="ltDropOnFolder" data-drop-args='[{"$": "event"}, null]'>`
    + `<span class="lt-fname">${ICON_FILE}<span class="lt-ell">${escapeHtml(t('ltNoFolder'))}</span></span><span class="lt-dim">${loose}</span></button>`
    + `<button type="button" class="lt-frow lt-fadd" data-click="createFolderPrompt" data-click-args='[null]'>＋ ${escapeHtml(t('ltNewFolder'))}</button></nav>`;
}

async function ltDropOnFolder(e, folderId) {
  e.currentTarget.classList.remove('drop-target');
  await libraryDrop(e, folderId);
  renderLibTable();
}

// The progress of the recordings being processed (live events, library.js): only the state of a row
// changes, so only that is drawn again; the whole table waits for a press to end (a click between the down
// and the up of a row, or a column being dragged, would lose its element), and the open «Колонки» panel is
// not made again under the pointer
function renderLibTableLive(rows) {
  if (state.appView !== 'libtable') return;
  if (LT.pressed) { LT.later = true; return; }
  if (rows && [...rows].every(ltRenderRowState)) return;
  renderLibTable({ live: true });
}

function ltRenderRowState(id) {
  const m = (state.meetings || []).find(x => x.id === id);
  if (!m) return false;
  const row = document.querySelector(`#lt-body [data-mid="${id}"]`);
  if (row) row.querySelectorAll('.lt-st').forEach(el => { el.outerHTML = ltStatusChip(m); });
  return true;  // a row not shown: its progress does not change what is shown
}

window.addEventListener('pointerup', () => {
  if (!LT.pressed) return;
  LT.pressed = false;
  // after the click that follows this up: the row clicked is still the one under it
  if (LT.later) setTimeout(() => { if (LT.later && !LT.pressed) { LT.later = false; renderLibTable({ live: true }); } }, 0);
}, true);

function renderLibTable(opts = {}) {
  if (state.appView !== 'libtable') return;
  const p = ltPrefs();
  const box = document.getElementById('lt-body');
  if (!box) return;
  const all = state.meetings || [];
  const shown = ltSorted(all.filter(m => ltMatches(m)));
  // once per showing: a failed load must not ask again at every drawing
  if (ltShownCols().includes('tasks') && typeof TK !== 'undefined' && !TK.loaded && !LT.tasksAsked) {
    LT.tasksAsked = true;
    loadTasks().catch(() => {}).finally(() => { if (TK.loaded) renderLibTable(); });
  }
  LT.taskCounts = null;
  LT.ids = [];
  renderLibTableCount(all, shown);
  if (!(opts.live && LT.colsOpen)) renderLibTableBar();
  let html = '', tpl = '', minW = 0;
  if (p.view === 'table') {
    ({ html, tpl, minW } = ltTableHtml(ltGroups(shown)));
  } else if (p.view === 'cards') {
    // one grid, the newest first: a day's group would leave a hole at the end of its row (the date is on each card)
    html = `<div class="lt-tiles">${shown.map(ltTile).join('')}</div>`;
  } else {
    const fid = ltOpenFolder();
    const f = fid === 'none' ? null : folderById(fid);
    const table = ltTableHtml([['folder', f ? folderName(f) : t('ltNoFolder'), shown]], true);
    html = `<div class="lt-fview">${ltFolderTree()}<div class="lt-fmain" style="min-width:${table.minW}px">${table.html}</div></div>`;
    tpl = table.tpl;
  }
  // the selection is of the rows on screen: a search or a filter that hides a selected one takes it out, so
  // «Выбрано» and the actions of the selection never count or touch a recording that is not seen
  if (state.multi.size) {
    const seen = new Set(LT.ids);
    const kept = [...state.multi].filter(id => seen.has(id));
    if (kept.length !== state.multi.size) {
      state.multi = new Set(kept);
      if (!(opts.live && LT.colsOpen)) renderLibTableBar();
      renderMeetingsSidebar();
    }
  }
  box.className = `lt-body lt-v-${p.view}${p.dense ? ' lt-dense' : ''}`;
  box.style.setProperty('--lt-tpl', tpl || 'none');
  box.style.minWidth = minW ? `${minW}px` : '';
  box.innerHTML = html;
  const empty = document.getElementById('lt-empty');
  const none = !shown.length && p.view !== 'folders';
  empty.classList.toggle('hidden', !none);
  if (none) {
    empty.innerHTML = all.length
      ? `<div>${escapeHtml(t(LT.q.trim() ? 'noMatches' : 'libFilterNone'))}</div><button class="tk-btn tk-btn-sm" data-click="resetLibTableFilters">${escapeHtml(t('libFilterResetAll'))}</button>`
      : `<div>${escapeHtml(t('noRecordings'))}</div>`;
  }
}

// Beside the title: how many recordings, or what the search found in the texts
function renderLibTableCount(all, shown) {
  const el = document.getElementById('lt-count');
  if (!el) return;
  const q = LT.q.trim();
  if (q && LT.hits && LT.hitsQ === q) {
    const ids = new Set(shown.map(m => m.id));
    let places = 0, recs = 0;
    for (const [id, hits] of LT.hits) if (ids.has(id) && hits.length) { places += hits.length; recs++; }
    if (places) {
      el.textContent = t('ltFound').replace('{places}', () => plural(places, t('ltPlacesForms'))).replace('{recs}', () => plural(recs, t('ltInRecForms')));
      return;
    }
  }
  el.textContent = shown.length === all.length
    ? plural(all.length, t('ltCountForms'))
    : t('ltCountOf').replace('{n}', () => shown.length).replace('{all}', () => all.length);
}

// --- The bar under the title: the filters and the views, or the selection in their place (one height:
// the list does not move when a recording is selected) ---
function ltChipCount(chip) {
  return (state.meetings || []).filter(m => ltMatches(m, { anyChip: true }) && ltChipMatch(m, chip)).length;
}

function renderLibTableBar() {
  const bar = document.getElementById('lt-bar');
  if (!bar) return;
  const p = ltPrefs();
  const n = state.multi.size;
  bar.classList.toggle('lt-selbar', n > 0);
  if (n) {
    bar.innerHTML = `<span class="lt-sel-n">${escapeHtml(t('libSelected').replace('{n}', () => n))}</span><span class="tk-grow"></span>`
      + `<button type="button" class="lt-btn" data-click="ltBulkFolder" data-click-args='[{"$": "event"}]'>${escapeHtml(t('ltToFolder'))}</button>`
      + `<button type="button" class="lt-btn" data-click="ltBulkFeature" data-click-args='[{"$": "event"}]'>${escapeHtml(t('ltToFeature'))}</button>`
      + `<button type="button" class="lt-btn" data-click="ltBulkExport" data-click-args='[{"$": "event"}]'>${escapeHtml(t('export'))}</button>`
      + `<button type="button" class="lt-btn" data-click="ltBulkTranscribe" title="${escapeHtml(t('ltTranscribeTip'))}">${escapeHtml(t('ltTranscribe'))}</button>`
      + `<button type="button" class="lt-btn" data-click="ltBulkMore" data-click-args='[{"$": "event"}]' title="${escapeHtml(t('ltMoreTip'))}" aria-haspopup="menu">⋯</button>`
      + `<button type="button" class="lt-btn lt-ghost" data-click="clearLibSelection" title="Esc">${escapeHtml(t('ltClearSel'))}</button>`;
    return;
  }
  const chip = c => `<button type="button" class="lt-chip${LT.chip === c ? ' on' : ''}" data-click="ltSetChip" data-click-args='["${c}"]'>${escapeHtml(t(`ltChip_${c}`))}`
    + (c === 'all' ? '' : `<b>${ltChipCount(c)}</b>`) + '</button>';
  const fName = p.feature === 'none' ? t('ftNoFeature') : p.feature ? (featureById(p.feature) || {}).name : '';
  const folderOff = p.view === 'folders';
  const ff = p.folderFilter === 'none' ? t('ltNoFolder') : p.folderFilter && folderById(Number(p.folderFilter)) ? folderName(folderById(Number(p.folderFilter))) : '';
  const groupOff = p.view === 'cards' || p.view === 'folders';
  const views = LT_VIEWS.map(v => `<button type="button" class="lt-seg-b${p.view === v ? ' on' : ''}" data-click="ltSetView" data-click-args='["${v}"]' aria-pressed="${p.view === v}">${escapeHtml(t(`ltView_${v}`))}</button>`).join('');
  bar.innerHTML = `<span class="lt-fl">${LT_CHIPS.map(chip).join('')}`
    + `<button type="button" id="lt-feature-btn" class="lt-chip${fName ? ' on' : ''}" data-click="openLibTableFeatureMenu" data-click-args='[{"$": "event"}]' aria-haspopup="menu"><span class="lt-ell">${escapeHtml(fName ? `${t('ltFeature')}: ${fName}` : t('ltFeature'))}</span> ▾</button>`
    + `<button type="button" id="lt-folder-btn" class="lt-chip${ff && !folderOff ? ' on' : ''}" data-click="openLibTableFolderMenu" data-click-args='[{"$": "event"}]' aria-haspopup="menu" ${folderOff ? `disabled title="${escapeHtml(t('ltFolderOffTip'))}"` : ''}><span class="lt-ell">${escapeHtml(ff && !folderOff ? `${t('ltCol_folder')}: ${ff}` : t('ltCol_folder'))}</span> ▾</button>`
    + `<button type="button" id="lt-group-btn" class="lt-chip" data-click="openLibTableGroupMenu" data-click-args='[{"$": "event"}]' aria-haspopup="menu" ${groupOff ? `disabled title="${escapeHtml(t('ltGroupOffTip'))}"` : ''}><span class="lt-ell">${escapeHtml(t(`ltGroupChip_${p.group}`))}</span> ▾</button></span>`
    + `<span class="lt-fr"><span class="lt-seg" role="group" title="${escapeHtml(t('ltViewTip'))}">${views}</span>`
    + `<span class="lt-cols-wrap"><button type="button" class="lt-btn" data-lt-cols data-click="toggleLibTableColumns" aria-haspopup="dialog" aria-expanded="${LT.colsOpen}" title="${escapeHtml(t(p.view === 'cards' ? 'ltColumnsCardsTip' : 'ltColumnsTip'))}">${LT_SVG(LT_ICON.gear, 14)}<span>${escapeHtml(t('ltColumns'))}</span></button>`
    + (LT.colsOpen ? ltColumnsPopHtml() : '') + '</span></span>';
}

function ltSetChip(c) {
  LT.chip = LT_CHIPS.includes(c) ? c : 'all';
  renderLibTable();
}

function ltSetView(v) {
  LT.colsOpen = false;
  ltSave({ view: LT_VIEWS.includes(v) ? v : 'table' });
  renderLibTable();
}

// --- The search: here by title, people and features at once, on the server by the words of the texts ---
function onLibTableSearch(value) {
  LT.q = value || '';
  const q = LT.q.trim();
  clearTimeout(LT.searchTimer);
  if (!q) { LT.hits = null; LT.hitsQ = ''; renderLibTable(); return; }
  renderLibTable();
  LT.searchTimer = setTimeout(() => runLibTableSearch(q), 220);
}

async function runLibTableSearch(q) {
  const res = await fetch(`/api/meetings/search?q=${encodeURIComponent(q)}`).catch(() => null);
  const data = res && res.ok ? await readJson(res) : [];
  if (q !== LT.q.trim()) return;  // an older search answered late
  LT.hits = new Map((Array.isArray(data) ? data : []).map(r => [Number(r.meeting_id), r.hits || []]));
  LT.hitsQ = q;
  renderLibTable();
}

function resetLibTableFilters() {
  LT.q = '';
  LT.hits = null;
  LT.chip = 'all';
  const q = document.getElementById('lt-q');
  if (q) q.value = '';
  ltSave({ feature: '', folderFilter: '' });
  renderLibTable();
}

// The table button in the library header of the sidebar: the section, or back to what the main area showed
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

// --- Menus: the feature, the folder, the groups ---
function ltMenuUnder(e, items) {
  e.preventDefault();
  e.stopPropagation();
  const r = e.currentTarget.getBoundingClientRect();
  openTextMenuAt(items, r.left, r.bottom + 4);
}

const ltTick = (on, label) => `${on ? '✓' : ' '}  ${label}`;

function openLibTableFeatureMenu(e) {
  const p = ltPrefs();
  const used = new Set((state.meetings || []).flatMap(m => m.features || []));
  const feats = (state.features || []).filter(f => used.has(f.id)).sort((a, b) => _libCollator.compare(a.name, b.name));
  const pick = id => () => { ltSave({ feature: id }); renderLibTable(); };
  ltMenuUnder(e, [
    { label: ltTick(!p.feature, t('ltFeatureAll')), run: pick('') },
    { sep: true },
    ...feats.map(f => ({ label: ltTick(p.feature === String(f.id), f.name), run: pick(String(f.id)) })),
    ...(feats.length ? [{ sep: true }] : []),
    { label: ltTick(p.feature === 'none', t('ftNoFeature')), run: pick('none') },
  ]);
}

// The folders with their depth, as in the tree of «Папки»
function ltFolderList(parentId = null, depth = 0) {
  return sortedFolders(parentId).flatMap(f => [[f, depth], ...ltFolderList(f.id, depth + 1)]);
}

function openLibTableFolderMenu(e) {
  const p = ltPrefs();
  const pick = id => () => { ltSave({ folderFilter: id }); renderLibTable(); };
  ltMenuUnder(e, [
    { label: ltTick(!p.folderFilter, t('ltFolderAll')), run: pick('') },
    { sep: true },
    ...ltFolderList().map(([f, d]) => ({ label: ltTick(p.folderFilter === String(f.id), `${'   '.repeat(d)}${folderName(f)}`), run: pick(String(f.id)) })),
    { sep: true },
    { label: ltTick(p.folderFilter === 'none', t('ltNoFolder')), run: pick('none') },
  ]);
}

function openLibTableGroupMenu(e) {
  const p = ltPrefs();
  ltMenuUnder(e, LT_GROUPS.map(g => ({ label: ltTick(p.group === g, t(`ltGroup_${g}`)), run: () => { ltSave({ group: g }); renderLibTable(); } })));
}

// --- «Колонки»: a panel under its button; a box shows a column, a drag changes the order ---
function ltColumnsPopHtml() {
  const p = ltPrefs();
  return `<div id="lt-cols-pop" class="lt-colpop" role="dialog" aria-label="${escapeHtml(t('ltColumns'))}">`
    + `<div class="lt-colpop-t">${escapeHtml(t('ltColumns'))}</div>`
    // the cards show the details ticked here; the table and the folders their columns, in rows of one density
    + (p.view === 'cards' ? `<div class="lt-colpop-s">${escapeHtml(t('ltColumnsCards'))}</div>`
      : `<div class="lt-colpop-dn"><span>${escapeHtml(t('ltRows'))}</span><span class="lt-seg">${[[false, 'ltRowsNormal'], [true, 'ltRowsDense']]
        .map(([d, k]) => `<button type="button" class="lt-seg-b${!!p.dense === d ? ' on' : ''}" data-dense="${d ? 1 : 0}" aria-pressed="${!!p.dense === d}">${escapeHtml(t(k))}</button>`).join('')}</span></div>`)
    + `<div class="lt-colpop-s">${escapeHtml(t('ltColumnsDrag'))}</div>`
    + p.order.map(c => `<label class="lt-colrow" draggable="true" data-colrow="${c}"><span class="lt-grip" aria-hidden="true">⋮⋮</span>`
      + `<input type="checkbox" data-col="${c}"${p.cols.includes(c) ? ' checked' : ''}><span>${escapeHtml(t(`ltColFull_${c}`))}</span></label>`).join('')
    + `<div class="lt-colpop-f"><button type="button" class="lt-btn lt-ghost" data-col-reset title="${escapeHtml(t('ltColumnsResetTip'))}">${LT_SVG(LT_ICON.reset, 13)}${escapeHtml(t('ltColumnsReset'))}</button>`
    + `<button type="button" class="lt-btn lt-go" data-cols-close>${escapeHtml(t('ltDone'))}</button></div></div>`;
}

function toggleLibTableColumns() {
  LT.colsOpen = !LT.colsOpen;
  renderLibTableBar();
  // the motion only on opening: the panel redrawn by a tick inside it comes without it
  if (LT.colsOpen) document.getElementById('lt-cols-pop')?.classList.add('vx-pop-in');
}

function closeLibTableColumnsMenu() {
  if (!LT.colsOpen) return;
  LT.colsOpen = false;
  renderLibTableBar();
}

document.addEventListener('click', (e) => {
  if (LT.colsOpen && e.target.isConnected && !e.target.closest?.('#lt-cols-pop, [data-lt-cols]')) closeLibTableColumnsMenu();  // a click that redrew the panel is inside it
});
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeLibTableColumnsMenu(); });

(function wireLibTableBar() {
  const bar = document.getElementById('lt-bar');
  if (!bar) return;
  bar.addEventListener('change', (e) => {
    const box = e.target.closest('input[data-col]');
    if (!box) return;
    const c = box.dataset.col, cols = ltPrefs().cols;
    ltSave({ cols: box.checked ? [...cols.filter(x => x !== c), c] : cols.filter(x => x !== c) });
    renderLibTable();
  });
  bar.addEventListener('click', (e) => {
    const dense = e.target.closest('[data-dense]');
    if (dense) { ltSave({ dense: dense.dataset.dense === '1' }); renderLibTable(); }
    else if (e.target.closest('[data-col-reset]')) { ltSave({ cols: [...LT_DEFAULT_COLS], order: [...LT_ORDER], widths: {}, dense: false }); renderLibTable(); }
    else if (e.target.closest('[data-cols-close]')) closeLibTableColumnsMenu();
  });
  let dragCol = null;
  bar.addEventListener('dragstart', (e) => {
    const row = e.target.closest?.('[data-colrow]');
    if (!row) return;
    dragCol = row.dataset.colrow;
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', dragCol);
    e.stopPropagation();
  });
  bar.addEventListener('dragover', (e) => {
    const row = e.target.closest?.('[data-colrow]');
    if (!dragCol || !row) return;
    e.preventDefault();
    e.stopPropagation();
    bar.querySelectorAll('.lt-colrow-over').forEach(x => x.classList.remove('lt-colrow-over'));
    row.classList.add('lt-colrow-over');
  });
  bar.addEventListener('drop', (e) => {
    const row = e.target.closest?.('[data-colrow]');
    if (!dragCol || !row) return;
    e.preventDefault();
    e.stopPropagation();
    const to = row.dataset.colrow;
    const order = ltPrefs().order.filter(c => c !== dragCol);
    order.splice(order.indexOf(to) + (ltPrefs().order.indexOf(dragCol) < ltPrefs().order.indexOf(to) ? 1 : 0), 0, dragCol);
    dragCol = null;
    ltSave({ order });
    renderLibTable();
  });
  bar.addEventListener('dragend', () => { dragCol = null; });
})();

// --- The selection: the box, Ctrl and Shift; a plain click opens the recording ---
function ltToggle(id) {
  if (state.multi.has(id)) state.multi.delete(id); else state.multi.add(id);
  LT.anchor = id;
  LT.cur = id;
}

function ltPick(e, id) {
  if (e.shiftKey) {
    const from = LT.ids.indexOf(LT.anchor ?? LT.cur);
    const to = LT.ids.indexOf(id);
    state.multi = new Set(from < 0 ? [id] : LT.ids.slice(Math.min(from, to), Math.max(from, to) + 1));
    LT.cur = id;
    document.getSelection()?.removeAllRanges();
  } else {
    ltToggle(id);
  }
  ltPaintPick();
}

// The pick is repainted on the rows in place, and the bar follows
function ltPaintPick() {
  for (const el of document.querySelectorAll('#lt-body [data-mid]')) {
    const id = Number(el.dataset.mid), on = state.multi.has(id);
    el.classList.toggle('lt-on', on);
    el.classList.toggle('lt-cur', LT.cur === id);
    const box = el.querySelector('.lt-cbx');
    if (box) { box.classList.toggle('on', on); box.setAttribute('aria-checked', String(on)); }
  }
  renderMeetingsSidebar();
  renderLibTableBar();
}

function ltMove(step) {
  if (!LT.ids.length) return;
  const i = LT.ids.indexOf(LT.cur);
  LT.cur = LT.ids[Math.max(0, Math.min(LT.ids.length - 1, i < 0 ? 0 : i + step))];
  ltPaintPick();
  document.querySelector(`#lt-body [data-mid="${LT.cur}"]`)?.scrollIntoView({ block: 'nearest' });
}

function ltOpen(id) {
  state.multi.clear();
  LT.cur = id;
  renderLibSelectionBar();
  openMeeting(id);
}

(function wireLibTable() {
  const body = document.getElementById('lt-body');
  const scroll = document.getElementById('lt-scroll');
  if (!body || !scroll) return;
  const rowOf = e => e.target.closest && e.target.closest('[data-mid]');
  body.addEventListener('click', (e) => {
    if (e.target.closest('.lt-rs')) return;
    const folder = e.target.closest('[data-folder]');
    if (folder) { ltSave({ folder: folder.dataset.folder }); renderLibTable(); return; }
    const hc = e.target.closest('.lt-hc[data-col]');
    if (hc) {
      const c = hc.dataset.col, p = ltPrefs();
      ltSave(p.sort === c ? { dir: p.dir === 'asc' ? 'desc' : 'asc' } : { sort: c, dir: ['name', 'feature', 'people', 'lang', 'model', 'folder'].includes(c) ? 'asc' : 'desc' });
      renderLibTable();
      return;
    }
    const hit = e.target.closest('.lt-snip');
    if (hit) { e.stopPropagation(); openLibraryHit(Number(hit.dataset.hit), Number(hit.dataset.at) || 0); return; }
    const row = rowOf(e);
    if (!row) return;
    const id = Number(row.dataset.mid);
    if (e.target.closest('.lt-cbx') || e.ctrlKey || e.metaKey || e.shiftKey) ltPick(e, id);
    else if (state.multi.size) ltPick(e, id);  // while recordings are selected a click adds or takes away
    else ltOpen(id);
  });
  body.addEventListener('contextmenu', (e) => {
    const folder = e.target.closest('[data-folder]');
    if (folder && folder.dataset.folder !== 'none' && !folder.classList.contains('lt-fadd')) { openFolderMenu(e, Number(folder.dataset.folder)); return; }
    const row = rowOf(e);
    if (!row) return;
    const id = Number(row.dataset.mid);
    if (!state.multi.has(id)) { state.multi.clear(); LT.cur = id; ltPaintPick(); }
    openRecordingContextMenu(e, id);
  });
  body.addEventListener('dragstart', (e) => {
    const row = rowOf(e);
    if (row) libraryDragStart(e, 'm', Number(row.dataset.mid));
  });
  body.addEventListener('dragend', () => {
    clearLibraryDrag();
    body.querySelectorAll('.drop-target').forEach(x => x.classList.remove('drop-target'));
  });
  scroll.addEventListener('keydown', (e) => {
    if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || '')) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); ltMove(e.key === 'ArrowDown' ? 1 : -1); }
    else if (e.key === 'Enter' && LT.cur != null) { e.preventDefault(); ltOpen(LT.cur); }
    else if (e.key === ' ' && LT.cur != null) { e.preventDefault(); ltToggle(LT.cur); ltPaintPick(); }
    else if (e.key === 'Escape' && state.multi.size) { e.preventDefault(); clearLibSelection(); }
    else if ((e.ctrlKey || e.metaKey) && e.code === 'KeyA') {
      e.preventDefault();
      state.multi = new Set(LT.ids);
      ltPaintPick();
    }
  });
  // The width of a column: dragged at the right edge of its header
  body.addEventListener('pointerdown', () => { LT.pressed = true; }, true);  // ends on the window (above)
  body.addEventListener('pointerdown', (e) => {
    const rs = e.target.closest && e.target.closest('.lt-rs');
    if (!rs) return;
    e.preventDefault();
    e.stopPropagation();
    const c = rs.dataset.rs;
    const start = ltWidth(c), x0 = e.clientX;
    try { rs.setPointerCapture(e.pointerId); } catch (err) { /* the pointer is already gone */ }
    document.body.classList.add('lt-resizing');
    let w = start, done = false;
    const move = (ev) => {
      w = Math.max(40, Math.min(900, Math.round(start + zpx(ev.clientX - x0))));
      const widths = { ...ltPrefs().widths, [c]: w };
      body.style.setProperty('--lt-tpl', `${LT_LEAD} minmax(180px, 1fr) ${ltShownCols().filter(x => x !== 'name').map(x => `${x === c ? w : (Number(widths[x]) >= 40 ? Math.min(widths[x], 900) : LT_COLS[x].w)}px`).join(' ')}`);
    };
    // the end is heard on the window and when the capture is lost (the handle redrawn, the window left):
    // the cursor «col-resize» and the selection off must never stay behind
    const up = () => {
      if (done) return;
      done = true;
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('pointercancel', up);
      rs.removeEventListener('lostpointercapture', up);
      document.body.classList.remove('lt-resizing');
      LT.pressed = false;
      LT.later = false;
      ltSave({ widths: { ...ltPrefs().widths, [c]: w } });
      renderLibTable();
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    window.addEventListener('pointercancel', up);
    rs.addEventListener('lostpointercapture', up);
  });
})();

// --- The actions of the selection bar ---
function ltSelected() {
  return libSelectedInOrder();
}

function ltBulkFolder(e) {
  const list = ltSelected();
  const move = id => async () => {
    for (const m of list) await moveMeetingToFolder(m.id, id);
    renderLibTable();
  };
  ltMenuUnder(e, [
    ...ltFolderList().map(([f, d]) => ({ label: `${'   '.repeat(d)}${folderName(f)}`, key: list.every(m => m.folder_id === f.id) ? '✓' : '', run: move(f.id) })),
    { sep: true },
    { label: t('ltNoFolder'), run: move(null) },
    { label: `${t('ltNewFolder')}…`, run: async () => {
      const name = (await askText(t('folderNamePrompt'), '') || '').trim();
      if (!name) return;
      const res = await fetch('/api/folders', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, parent_id: null }) });
      const data = await readJson(res);
      if (!res.ok) { showError(data.detail); return; }
      await loadFolders();
      await move(data.id)();
    } },
  ]);
}

// mode: "add" or "remove" the feature fid, or "clear" all of them
async function ltSetFeatures(list, mode, fid) {
  let failed = 0;
  for (const m of list) {
    const had = m.features || [];
    const ids = mode === 'clear' ? [] : mode === 'remove' ? had.filter(x => x !== fid) : [...new Set([...had, fid])];
    const res = await fetch(`/api/meetings/${m.id}/features`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids, for_series: false }) }).catch(() => null);
    const data = res ? await readJson(res) : {};
    if (!res || !res.ok) { failed++; continue; }
    m.features = data.features || [];
    m.feature_suggestions = data.feature_suggestions || [];
    if (state.activeMeeting && state.activeMeeting.id === m.id) applyMeetingFeatures(state.activeMeeting, data);
  }
  scheduleSidebarRender();
  renderLibTable();
  if (failed) showError(t('bulkSomeFailed').replace('{n}', () => failed));
}

// A feature on all of them, or off all of them when they all have it already
function ltBulkFeature(e) {
  const list = ltSelected();
  const feats = (state.features || []).slice().sort((a, b) => _libCollator.compare(a.name, b.name));
  ltMenuUnder(e, [
    ...feats.map(f => {
      const all = list.every(m => (m.features || []).includes(f.id));
      return { label: f.name, key: all ? '✓' : '', run: () => ltSetFeatures(list, all ? 'remove' : 'add', f.id) };
    }),
    ...(feats.length ? [{ sep: true }] : []),
    { label: `${t('ltNewFeature')}…`, run: async () => {
      const name = (await askText(t('ltNewFeature'), '') || '').trim();
      if (!name) return;
      const res = await fetch('/api/features', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
      const data = await readJson(res);
      if (!res.ok) { showError(data.detail); return; }
      await loadFeatures();
      await ltSetFeatures(list, 'add', data.id);
    } },
    { label: t('ltFeatureClear'), disabled: !list.some(m => (m.features || []).length), run: () => ltSetFeatures(list, 'clear') },
  ]);
}

function ltBulkExport(e) {
  ltMenuUnder(e, [['docx', 'Word (.docx)'], ['md', 'Markdown (.md)'], ['txt', t('ltExportTxt')], ['srt', t('ltExportSrt')]]
    .map(([fmt, label]) => ({ label, run: () => ltExportMany(fmt) })));
}

function ltExportName(res, m, fmt) {
  const disp = res.headers.get('content-disposition') || '';
  const utf = disp.match(/filename\*=UTF-8''([^;]+)/i), plain = disp.match(/filename="?([^";]+)"?/i);
  if (utf) { try { return decodeURIComponent(utf[1]); } catch (e) { return utf[1]; } }
  if (plain) return plain[1];
  return `${(m.title || 'meeting').replace(/[^a-zA-Z0-9а-яА-ЯёЁ _-]/g, '_').trim() || 'meeting'}.${fmt}`;
}

// The texts of the selected recordings: into one folder chosen once (the page's folder picker), or each
// with its own «Сохранить как» where that picker is not there
async function ltExportMany(fmt) {
  const list = ltSelected().filter(m => m.status === 'completed');
  if (!list.length) { showWarning(t('bulkNoTranscripts')); return; }
  if (typeof window.showDirectoryPicker !== 'function') {
    for (const m of list) await exportMeetingById(m.id, fmt);
    return;
  }
  let dir;
  try { dir = await window.showDirectoryPicker({ mode: 'readwrite' }); } catch (err) { return; }  // cancelled
  let saved = 0, failed = 0;
  for (const m of list) {
    try {
      const res = await fetch(`/api/meetings/${m.id}/export/${fmt}`);
      if (!res.ok) { failed++; continue; }
      const blob = await res.blob();
      const file = await dir.getFileHandle(ltExportName(res, m, fmt), { create: true });
      const w = await file.createWritable();
      await w.write(blob);
      await w.close();
      saved++;
    } catch (err) {
      failed++;
    }
  }
  showToast(failed ? t('bulkSomeFailed').replace('{n}', () => failed) : t('ltExported').replace('{n}', () => saved).replace('{dir}', () => dir.name), null, failed ? 'warning' : 'success');
}

// Recognition again for the selected ones that have no text (added only, failed, cancelled, cleared)
async function ltBulkTranscribe() {
  const list = ltSelected().filter(m => LT_UNTRANSCRIBED.includes(m.status));
  if (!list.length) { showWarning(t('ltNothingToTranscribe')); return; }
  if (!requireRecognitionModel()) return;
  let queued = 0, failed = 0;
  for (const m of list) {
    const res = await fetch(`/api/meetings/${m.id}/retry`, { method: 'POST' }).catch(() => null);
    if (res && res.ok) queued++; else failed++;
  }
  await loadMeetingsList();
  showToast(failed ? t('bulkSomeFailed').replace('{n}', () => failed) : t('ltQueuedN').replace('{n}', () => plural(queued, t('ltCountForms'))), null, failed ? 'warning' : 'success');
}

// The rest of what the old bar of the selection did: one name for all, titles from the texts, delete
function ltBulkMore(e) {
  ltMenuUnder(e, [
    { label: `${t('bulkRename')}…`, run: () => bulkRename() },
    { label: t('bulkAutoTitle'), run: () => bulkAutoTitles() },
    { sep: true },
    { label: t('ctxDelete'), danger: true, run: () => bulkDelete() },
  ]);
}

registerView('libtable', {
  show: () => {
    if (LT.cur == null && state.activeMeeting) LT.cur = state.activeMeeting.id;
    LT.tasksAsked = false;
    syncLibTableButton();
    renderLibTable();
    renderLibSelectionBar();
    nextFrame(() => document.getElementById('lt-scroll')?.focus({ preventScroll: true }));
  },
  // the selection belongs to the table on screen: it does not stay behind, unseen, for Delete in another section
  hide: () => { syncLibTableButton(); LT.colsOpen = false; state.multi.clear(); nextFrame(renderLibSelectionBar); },
  refresh: renderLibTable,
});
