// Verbaliox page script: «Дэшборд» (static/parts/dashboard.html), the first page of the app. Widgets the user
// arranges («Настроить»: dragged, sized S · M · L · W, removed, added from the list), kept on this computer.
// The data widgets read /api/dashboard (app/dashboard.py) for the period and the feature chosen; the week reads
// /api/calendar/range. The day of the former home page (its greeting, the meetings of today with their
// auto-recording, the latest recordings, what is being processed) lives here too: its blocks are moved in
// from static/parts/home.html and drawn by static/js/home.js as before.
// The parts are classic scripts sharing one global scope, loaded in order by index.html.

const DB_KEY = 'vx-dashboard';
const DB_SIZES = { S: 4, M: 5, L: 7, W: 12 };
// Every widget: its title key, the sizes it takes, and the block of the home page it shows (host)
const DB_WIDGETS = {
  kpis: { title: 'dbKpis', sizes: ['L', 'W'], icon: '▦' },
  today: { title: 'hmMeetings', sizes: ['S', 'M', 'L', 'W'], host: 'hm-timeline', icon: '◷' },
  week: { title: 'dbWeek', sizes: ['M', 'L', 'W'], icon: '▤' },
  mytasks: { title: 'hmMyTasks', sizes: ['S', 'M', 'L', 'W'], icon: '☑' },
  waiting: { title: 'dbWaiting', sizes: ['S', 'M', 'L', 'W'], icon: '⧗' },
  features: { title: 'dbFeatures', sizes: ['M', 'L', 'W'], icon: '◆' },
  time: { title: 'dbTime', sizes: ['S', 'M', 'L', 'W'], icon: '▮' },
  people: { title: 'dbPeople', sizes: ['S', 'M', 'L'], icon: '☺' },
  decisions: { title: 'dbDecisions', sizes: ['S', 'M', 'L', 'W'], icon: '✓' },
  summary: { title: 'dbSummary', sizes: ['S', 'M', 'L', 'W'], icon: '✦' },
  recent: { title: 'homeRecent', sizes: ['S', 'M', 'L', 'W'], host: 'hm-recent', icon: '☰' },
  work: { title: 'hmInWork', sizes: ['S', 'M', 'L'], host: 'hm-queue', icon: '⟳' },
};
const DB_DEFAULT = [['kpis', 'W'], ['today', 'M'], ['week', 'L'], ['mytasks', 'M'], ['waiting', 'M'], ['features', 'L'],
  ['time', 'S'], ['people', 'S'], ['decisions', 'S'], ['summary', 'M'], ['recent', 'L']];
const DB_PERIODS = ['week', 'month', 'quarter'];
const DB_NEW_WIDGETS = ['waiting'];  // added after the first dashboard: offered once to an existing layout

const DB = { data: null, week: null, edit: false, loading: false, prefs: null, drag: null, summaryBusy: false };

function dbPrefs() {
  if (DB.prefs) return DB.prefs;
  let p = {};
  try { p = JSON.parse(localStorage.getItem(DB_KEY) || '{}') || {}; } catch (e) {}
  const layout = Array.isArray(p.layout) ? p.layout.filter(w => w && DB_WIDGETS[w.id]) : null;
  // a widget added in a later version comes once into a layout made before it (after «Мои задачи»);
  // removed by the user, it stays out
  const offered = Array.isArray(p.offered) ? p.offered : [];
  if (layout && layout.length) {
    for (const id of DB_NEW_WIDGETS) {
      if (offered.includes(id) || layout.some(w => w.id === id)) continue;
      const at = layout.findIndex(w => w.id === 'mytasks');
      layout.splice(at < 0 ? layout.length : at + 1, 0, { id, size: 'M' });
    }
  }
  return DB.prefs = {
    offered: [...new Set([...offered, ...DB_NEW_WIDGETS])],
    layout: layout && layout.length ? layout : DB_DEFAULT.map(([id, size]) => ({ id, size })),
    period: DB_PERIODS.includes(p.period) ? p.period : 'week',
    feature: Number(p.feature) || 0,
    summary: p.summary && typeof p.summary === 'object' ? p.summary : null,
  };
}

function dbSave(changes) {
  DB.prefs = { ...dbPrefs(), ...changes };
  try { localStorage.setItem(DB_KEY, JSON.stringify(DB.prefs)); } catch (e) {}
}

function dbSize(w) {
  const sizes = DB_WIDGETS[w.id].sizes;
  return sizes.includes(w.size) ? w.size : sizes[Math.min(1, sizes.length - 1)];
}

// --- Data ---
async function loadDashboard() {
  const p = dbPrefs();
  DB.loading = true;
  const q = `period=${p.period}${p.feature ? `&feature=${p.feature}` : ''}`;
  const [data, week, untx] = await Promise.all([
    fetch(`/api/dashboard?${q}`).then(r => (r.ok ? r.json() : null)).catch(() => null),
    dbLoadWeek(),
    fetch('/api/untranscribed').then(r => (r.ok ? r.json() : null)).catch(() => null),
  ]);
  DB.loading = false;
  DB.data = data;
  DB.week = week;
  DB.untx = (untx && untx.items) || [];
  if (state.appView === 'dashboard') renderDashboard();
}

function dbMonday(d = new Date()) {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  x.setDate(x.getDate() - ((x.getDay() + 6) % 7));
  return x;
}

async function dbLoadWeek() {
  const a = dbMonday(), b = new Date(a);
  b.setDate(a.getDate() + 7);
  return fetch(`/api/calendar/range?start=${encodeURIComponent(hmIso(a))}&end=${encodeURIComponent(hmIso(b))}`)
    .then(r => (r.ok ? r.json() : null)).catch(() => null);
}

// --- Drawing ---
function renderDashboard() {
  const grid = document.getElementById('db-grid');
  if (!grid) return;
  const p = dbPrefs();
  dbRenderHead();
  dbParkHosts();  // the home page's blocks go back before the grid is redrawn, so they are not lost
  grid.classList.toggle('db-editing', DB.edit);
  grid.innerHTML = p.layout.map((w, i) => {
    const def = DB_WIDGETS[w.id], size = dbSize(w);
    const sizes = DB.edit ? `<span class="db-sizes">${def.sizes.map(s => `<button data-click="setDashSize" data-click-args='[${i}, "${s}"]' class="${s === size ? 'on' : ''}" title="${escapeHtml(t(`dbSize_${s}`))}">${s}</button>`).join('')}</span>` : '';
    const tools = DB.edit ? `<span class="db-tools"><span class="db-grip" title="${escapeHtml(t('dbDragTip'))}">⋮⋮</span>`
      + `<button data-click="removeDashWidget" data-click-args='[${i}]' class="db-x" title="${escapeHtml(t('dbRemove'))}" aria-label="${escapeHtml(t('dbRemove'))}">✕</button></span>` : '';
    return `<section class="db-w db-w-${w.id}${w.id === 'summary' ? ' db-summary' : ''}" style="grid-column:span ${DB_SIZES[size]}" data-i="${i}" ${DB.edit ? 'draggable="true"' : ''}>`
      + (def.host ? '' : `<h3 class="db-h">${escapeHtml(t(def.title))}${dbLink(w.id)}</h3>`)
      + `<div class="db-c">${def.host ? '' : dbWidgetHtml(w.id, size)}</div>${tools}${sizes}</section>`;
  }).join('') || `<div class="db-empty">${escapeHtml(t('dbEmpty'))}</div>`;
  if (!DB.edit && (DB.untx || []).length) grid.insertAdjacentHTML('afterbegin', dbUntxHtml());
  // the home page's blocks in their widgets (home.js keeps drawing them where they are)
  p.layout.forEach((w, i) => {
    const def = DB_WIDGETS[w.id];
    if (!def.host) return;
    const block = document.getElementById(def.host)?.closest('section');
    if (block) grid.querySelector(`.db-w[data-i="${i}"] .db-c`).appendChild(block);
  });
  renderDashDrawer();
}

// Recordings whose transcription was cancelled and never done (app/untranscribed.py): asked by the user,
// a reminder with «Расшифровать», above the widgets
function dbUntxHtml() {
  const items = DB.untx || [];
  const names = items.slice(0, 3).map(m => `<button class="db-untx-name" data-click="openMeeting" data-click-args='[${m.id}]'>${escapeHtml(m.title || t('hmUntitled'))}</button>`).join(', ');
  const more = items.length > 3 ? ` ${escapeHtml(t('dbUntxMore').replace('{n}', () => items.length - 3))}` : '';
  return `<div class="db-untx" role="status">
    <span class="db-untx-text">${escapeHtml(t(items.length > 1 ? 'dbUntxMany' : 'dbUntxOne').replace('{n}', () => items.length))} ${names}${more}</span>
    <button class="tk-btn db-untx-go" data-click="dashTranscribeUntx">${escapeHtml(t(items.length > 1 ? 'dbUntxGoAll' : 'dbUntxGo'))}</button>
    <button class="tk-btn" data-click="dashDismissUntx">${escapeHtml(t('dbUntxDismiss'))}</button>
  </div>`;
}

async function dashTranscribeUntx() {
  const ids = (DB.untx || []).map(m => m.id);
  const res = await fetch('/api/untranscribed/transcribe', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids }) }).catch(() => null);
  if (!res || !res.ok) { showError(t('errorGeneric')); return; }
  const out = await res.json();
  showToast(t('dbUntxQueued').replace('{n}', () => out.queued), null, 'success');
  DB.untx = [];
  renderDashboard();
  loadMeetingsList().catch(() => {});
}

async function dashDismissUntx() {
  const ids = (DB.untx || []).map(m => m.id);
  await fetch('/api/untranscribed/dismiss', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids }) }).catch(() => null);
  DB.untx = [];
  renderDashboard();
}

// The blocks borrowed from the home page go back to it, out of the grid
function dbParkHosts() {
  const park = document.getElementById('db-park');
  if (!park) return;
  for (const def of Object.values(DB_WIDGETS)) {
    const block = def.host && document.getElementById(def.host)?.closest('section');
    if (block && !park.contains(block)) park.appendChild(block);
  }
}

function dbLink(id) {
  const link = (fn, args, key) => `<button class="db-more" data-click="${fn}" data-click-args='${JSON.stringify(args)}'>${escapeHtml(t(key))}</button>`;
  if (id === 'mytasks') return link('dbOpenDetail', ['tasks'], 'dbAllLink');
  if (id === 'waiting') return link('dbOpenDetail', ['waiting'], 'dbAllLink');
  if (id === 'decisions') return link('dbOpenDetail', ['decisions'], 'dbAllLink');
  if (id === 'time') return link('dbOpenDetail', ['meetings'], 'dbAllLink');
  if (id === 'week') return link('openCalendarView', [], 'dbCalendarLink');
  if (id === 'summary') return DB.summaryBusy ? '' : link('makeDashSummary', [], dbPrefs().summary ? 'dbSummaryRedo' : 'dbSummaryMake');
  return '';
}

function dbRenderHead() {
  const p = dbPrefs(), d = DB.data;
  const fmt = s => new Date(`${s}T12:00:00`).toLocaleDateString(state.uiLang === 'en' ? 'en-US' : 'ru-RU', { day: 'numeric', month: 'long' });
  const sub = document.getElementById('db-sub');
  if (sub) {
    const last = d ? new Date(`${d.end}T12:00:00`) : null;
    if (last) last.setDate(last.getDate() - 1);
    sub.textContent = d ? `${t(`dbPeriodName_${p.period}`)}: ${fmt(d.start)} – ${fmt(last.toISOString().slice(0, 10))}` : '';
  }
  document.getElementById('db-periods').innerHTML = DB_PERIODS.map(k =>
    `<button role="radio" aria-checked="${p.period === k}" class="tk-seg-btn${p.period === k ? ' tk-on' : ''}" data-click="setDashPeriod" data-click-args='["${k}"]'>${escapeHtml(t(`dbPeriod_${k}`))}</button>`).join('');
  const f = p.feature ? featureById(p.feature) : null;
  const fb = document.getElementById('db-feature-btn');
  fb.textContent = `${f ? f.name : t('dbAllFeatures')} ▾`;
  fb.classList.toggle('lt-btn-on', !!f);
  document.getElementById('db-edit-label').textContent = t(DB.edit ? 'dbDone' : 'dbEdit');
  document.getElementById('db-edit-btn').setAttribute('aria-pressed', DB.edit ? 'true' : 'false');
}

function dbNum(n) { return String(n).replace('.', state.uiLang === 'en' ? '.' : ','); }

function dbWidgetHtml(id, size) {
  const d = DB.data;
  if (!d && id !== 'week') return `<div class="db-note">${escapeHtml(t(DB.loading ? 'dbLoading' : 'dbNoData'))}</div>`;
  switch (id) {
    case 'kpis': return dbKpis(d);
    case 'week': return dbWeek();
    case 'mytasks': return dbTasks(d, size);
    case 'waiting': return dbWaitingHtml(d, size);
    case 'features': return dbFeatures(d, size);
    case 'time': return dbTime(d);
    case 'people': return dbPeople(d);
    case 'decisions': return dbDecisions(d, size);
    case 'summary': return dbSummaryHtml();
  }
  return '';
}

function dbKpis(d) {
  const k = d.kpi;
  const delta = (now, before, unit = '') => {
    const x = Math.round((now - before) * 10) / 10;
    if (!before && !now) return `<span>${escapeHtml(t('dbNothingYet'))}</span>`;
    return `<b class="${x < 0 ? 'neg' : ''}">${x > 0 ? '+' : ''}${dbNum(x)}${unit}</b> ${escapeHtml(t(`dbVsBefore_${d.period}`))}`;
  };
  // every tile opens its details (asked by the user: a number could not be looked into)
  const tile = (key, value, line, kind, extra = '') => `<div class="db-kpi"><button class="db-kpi-open" data-click="dbOpenDetail" data-click-args='["${kind}"]' title="${escapeHtml(t('dbOpenDetailTip'))}">`
    + `<div class="db-kpi-k">${escapeHtml(t(key))}<span class="db-kpi-go" aria-hidden="true">→</span></div><div class="db-kpi-v">${value}</div><div class="db-kpi-d">${line}</div></button>${extra}</div>`;
  // the meetings without an outcome (no decision, no task; the user silent; a series giving nothing)
  const useless = `<button class="db-kpi-x${k.useless ? '' : ' db-kpi-x-none'}" data-click="dbOpenDetail" data-click-args='["useless"]'>${escapeHtml(k.useless
    ? t('dbUselessN').replace('{n}', () => k.useless).replace('{h}', () => dbNum(k.useless_hours)) : t('dbUselessNone'))}</button>`;
  return `<div class="db-kpis">`
    + tile('dbKpiMeetings', k.meetings, delta(k.meetings, k.meetings_before), 'meetings', useless)
    + tile('dbKpiHours', `${dbNum(k.hours)} ${escapeHtml(t('dbHoursShort'))}`, delta(k.hours, k.hours_before, ` ${t('dbHoursShort')}`), 'meetings')
    + (d.needs_me
      ? `<div class="db-kpi"><div class="db-kpi-k">${escapeHtml(t('dbKpiMyTasks'))}</div><div class="db-kpi-v">—</div><div class="db-kpi-d"><button class="db-more" data-click="hmSetMyName">${escapeHtml(t('dbSetMe'))}</button></div></div>`
      : tile('dbKpiMyTasks', k.open, k.overdue ? `<b class="neg">${escapeHtml(t('dbOverdueN').replace('{n}', () => k.overdue))}</b>` : `<span>${escapeHtml(t('dbNoneOverdue'))}</span>`, 'tasks'))
    + tile('dbKpiDecisions', k.decisions, k.decisions ? escapeHtml(t('dbInMeetings').replace('{n}', () => k.decision_meetings)) : `<span>${escapeHtml(t('dbNoDecisions'))}</span>`, 'decisions')
    + '</div>';
}

function dbDue(task, today) {
  if (!task.due_date) return `<span class="db-due">${escapeHtml(t('tkNoDue'))}</span>`;
  const days = Math.round((new Date(`${task.due_date}T12:00:00`) - new Date(`${today}T12:00:00`)) / 864e5);
  const cls = days < 0 ? 'over' : days === 0 ? 'today' : '';
  const text = days < 0 ? t('dbDaysAgo').replace('{n}', () => -days) : days === 0 ? t('tkTodayLow') : days === 1 ? t('tkTomorrowLow')
    : new Date(`${task.due_date}T12:00:00`).toLocaleDateString(state.uiLang === 'en' ? 'en-US' : 'ru-RU', { weekday: 'short', day: 'numeric', month: 'short' });
  return `<span class="db-due ${cls}">${escapeHtml(text)}</span>`;
}

function dbTasks(d, size) {
  if (d.needs_me) {
    return `<div class="db-note">${escapeHtml(t('dbNeedsMe'))}</div><button class="tk-btn tk-btn-sm" data-click="hmSetMyName">${escapeHtml(t('dbSetMe'))}</button>`;
  }
  if (!d.tasks.length) return `<div class="db-note">${escapeHtml(t('dbNoMyTasks'))}</div>`;
  const n = size === 'S' ? 4 : size === 'W' ? 10 : 6;
  return d.tasks.slice(0, n).map(x => {
    const f = (x.features || []).map(featureById).filter(Boolean)[0];
    return `<div class="db-task"><button class="db-ck" data-click="dashTaskDone" data-click-args='[${x.id}]' title="${escapeHtml(t('dbMarkDone'))}" aria-label="${escapeHtml(t('dbMarkDone'))}"></button>`
      + `<button class="db-task-t" data-click="dashOpenTask" data-click-args='[${x.id}, ${Number(x.meeting_id) || 0}]' title="${escapeHtml(x.meeting_title ? `${x.what} — ${x.meeting_title}` : x.what)}">${escapeHtml(x.what)}</button>`
      // the chip with its name where there is room, its colour alone in a narrow card (the name in its tooltip)
      + (!f ? '<span class="db-task-ft"></span>' : size === 'L' || size === 'W' ? `<span class="db-task-ft">${featureChipHtml(f)}</span>`
        : `<span class="db-task-ft"><span class="db-ft-dot" style="--ft:${/^#[0-9A-Fa-f]{6}$/.test(f.color || '') ? f.color : '#8E8E93'}" title="${escapeHtml(f.name)}"></span></span>`)
      + dbDue(x, d.today) + '</div>';
  }).join('');
}

function dbWeek() {
  const w = DB.week;
  if (!w) return `<div class="db-note">${escapeHtml(t(DB.loading ? 'dbLoading' : 'dbNoData'))}</div>`;
  const a = dbMonday(), today = calKey ? calKey(new Date()) : '';
  const lang = state.uiLang === 'en' ? 'en-US' : 'ru-RU';
  const days = [];
  for (let i = 0; i < 7; i++) { const x = new Date(a); x.setDate(a.getDate() + i); days.push(x); }
  const items = {};
  const put = (dt, item) => { const k = calKey(dt); (items[k] = items[k] || []).push(item); };
  for (const e of w.events || []) put(new Date(e.start), { at: new Date(e.start), end: new Date(e.end || e.start), title: e.title || t('hmUntitled'), rec: e.recording ? e.recording.id : 0 });
  // a recording without a meeting: over by the time it is in the library (its length when it is known)
  for (const r of w.recordings || []) put(new Date(r.at), { at: new Date(r.at), end: new Date(new Date(r.at).getTime() + (r.duration || 0) * 1000), title: r.title, rec: r.id, own: true });
  const shown = days.filter((x, i) => i < 5 || (items[calKey(x)] || []).length);
  const now = Date.now();
  const pad = n => String(n).padStart(2, '0');
  const item = it => {
    // over (a tick), going on (red, with how far it is), or ahead
    const done = it.end.getTime() <= now || (it.own && it.at.getTime() <= now);
    const live = !done && it.at.getTime() <= now;
    const pct = live ? Math.round((now - it.at) / Math.max(1, it.end - it.at) * 100) : 0;
    return `<button class="db-ev${done ? ' done' : ''}${live ? ' live' : ''}${it.own ? ' own' : ''}" ${it.rec ? `data-click="openMeeting" data-click-args='[${it.rec}]'` : 'disabled'} title="${escapeHtml(it.title)}">`
      + `<span class="db-tm">${pad(it.at.getHours())}:${pad(it.at.getMinutes())}</span>${escapeHtml(it.title)}${live ? `<i class="db-ev-prog" style="width:${pct}%"></i>` : ''}</button>`;
  };
  const nowDate = new Date(now);
  return `<div class="db-cal" style="grid-template-columns:repeat(${shown.length}, minmax(0, 1fr))">` + shown.map(x => {
    const k = calKey(x), list = (items[k] || []).sort((p, q) => p.at - q.at);
    const head = `<div class="db-dn"><b>${x.getDate()}</b>${escapeHtml(x.toLocaleDateString(lang, { weekday: 'short' }))}</div>`;
    // The time already past is filled (asked by the user): a day before today whole; today down to the
    // line of "now", which stands after the last thing already begun, never over a card
    if (k === today) {
      const begun = list.filter(it => it.at.getTime() <= now), ahead = list.filter(it => it.at.getTime() > now);
      return `<div class="db-day today"><div class="db-past">${head}${begun.map(item).join('')}</div>`
        + `<div class="db-now"><b>${pad(nowDate.getHours())}:${pad(nowDate.getMinutes())}</b></div>${ahead.map(item).join('')}</div>`;
    }
    return `<div class="db-day${k < today ? ' db-day-past' : ''}">${head}${list.map(item).join('')}</div>`;
  }).join('') + '</div>';
}

function dbFeatures(d, size) {
  if (!d.features.length) return `<div class="db-note">${escapeHtml(t('dbNoFeatures'))}</div>`;
  const n = size === 'M' ? 2 : size === 'W' ? 6 : 4;
  return `<div class="db-feats">` + d.features.slice(0, n).map(f => {
    const c = /^#[0-9A-Fa-f]{6}$/.test(f.color || '') ? f.color : '#8E8E93';
    const max = Math.max(1, ...f.spark);
    return `<button class="db-feat" style="--ft:${c}" data-click="setDashFeature" data-click-args='[${f.id}]' title="${escapeHtml(t('dbFeatureOnly').replace('{name}', () => f.name))}">`
      + `<span class="db-feat-n"><i></i>${escapeHtml(f.name)}</span>`
      + `<span class="db-feat-row"><span><b>${f.meetings}</b> ${escapeHtml(plural(f.meetings, t('dbMeetingForms')).replace(/^\d+\s/, ''))}</span>`
      + (d.needs_me ? '' : `<span><b>${f.open}</b> ${escapeHtml(t('dbMyTasksShort'))}</span>`)
      + (f.overdue ? `<span class="neg"><b>${f.overdue}</b> ${escapeHtml(t('dbOverdueShort'))}</span>` : '') + '</span>'
      + `<span class="db-spark" title="${escapeHtml(t('dbSparkTip'))}">${f.spark.map(v => `<i style="height:${Math.round(8 + 92 * v / max)}%;opacity:${v ? 1 : 0.25}"></i>`).join('')}</span>`
      + `<span class="db-feat-last">${escapeHtml(t('dbLast'))}: «${escapeHtml(f.last.title)}», ${escapeHtml(dbAgo(f.last.date, d.today))}</span></button>`;
  }).join('') + '</div>';
}

function dbAgo(day, today) {
  const n = Math.round((new Date(`${today}T12:00:00`) - new Date(`${day}T12:00:00`)) / 864e5);
  if (n === 0) return t('libToday').toLowerCase();
  if (n === 1) return t('libYesterday').toLowerCase();
  return new Date(`${day}T12:00:00`).toLocaleDateString(state.uiLang === 'en' ? 'en-US' : 'ru-RU', { day: 'numeric', month: 'short' });
}

function dbTime(d) {
  const b = d.buckets;
  if (!b.some(x => x.hours)) return `<div class="db-note">${escapeHtml(t('dbNoMeetingsYet'))}</div>`;
  const max = Math.max(...b.map(x => x.hours));
  const lang = state.uiLang === 'en' ? 'en-US' : 'ru-RU';
  const label = x => {
    const dt = new Date(`${x.key}T12:00:00`);
    return x.kind === 'day' ? dt.toLocaleDateString(lang, { weekday: 'short' }) : dt.toLocaleDateString(lang, { day: 'numeric', month: 'short' });
  };
  const top = b.reduce((m, x) => (x.hours > m.hours ? x : m), b[0]);
  return `<div class="db-bars">` + b.map(x => {
    const tip = `${label(x)}: ${dbNum(x.hours)} ${t('dbHoursShort')}${x.meetings.length ? '\n' + x.meetings.map(m => `· ${m.title}`).join('\n') : ''}`;
    return `<div class="db-col" title="${escapeHtml(tip)}"><span class="db-col-v">${x.hours ? `${dbNum(x.hours)}` : ''}</span><i style="height:${x.hours ? Math.max(3, Math.round(100 * x.hours / max)) : 0}%"></i></div>`;
  }).join('') + `</div><div class="db-axis">${b.map(x => `<span>${escapeHtml(label(x))}</span>`).join('')}</div>`
    + `<div class="db-note">${escapeHtml(t('dbTimeTop').replace('{when}', () => label(top)).replace('{h}', () => dbNum(top.hours)).replace('{n}', () => top.meetings.length))}</div>`;
}

function dbPeople(d) {
  if (!d.people.length) return `<div class="db-note">${escapeHtml(t('dbNoPeople'))}</div>`;
  const max = Math.max(...d.people.map(p => p.meetings));
  return d.people.slice(0, 5).map((p, i) => {
    const c = /^#[0-9A-Fa-f]{6}$/.test(p.color || '') ? p.color : TK_COLORS[i % TK_COLORS.length];
    return `<button class="db-person" data-click="dbOpenDetail" data-click-args='["person", ${JSON.stringify(p.name)}]'>`
      + `<span class="db-av" style="--av:${c}">${escapeHtml(p.name.charAt(0).toUpperCase())}</span>`
      + `<span class="db-person-n">${escapeHtml(p.name)}<small>${escapeHtml(plural(p.meetings, t('dbMeetingForms')))}</small></span>`
      + `<span class="db-meter"><i style="width:${Math.round(100 * p.meetings / max)}%"></i></span></button>`;
  }).join('');
}

function dbDecisions(d, size) {
  if (!d.decisions.length) return `<div class="db-note">${escapeHtml(t('dbNoDecisionsYet'))}</div>`;
  const n = size === 'S' ? 3 : size === 'W' ? 8 : 5;
  return d.decisions.slice(0, n).map(x => `<button class="db-dec" data-click="dashOpenSummary" data-click-args='[${x.meeting_id}]'>`
    + `${escapeHtml(x.text)}<small>«${escapeHtml(x.title)}» · ${escapeHtml(dbAgo(x.date, d.today))}</small></button>`).join('');
}

// «Сводка недели»: the digest of the library (app/digest.py) for the period, made on request, kept here
function dbSummaryHtml() {
  const s = dbPrefs().summary;
  if (DB.summaryBusy) return `<div class="db-note db-busy">${escapeHtml(t('dbSummaryBusy'))}</div>`;
  if (!s || !s.html) return `<div class="db-note">${escapeHtml(t('dbSummaryNone'))}</div>`;
  const when = new Date(s.at).toLocaleString(state.uiLang === 'en' ? 'en-US' : 'ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  return `<div class="db-md">${s.html}</div><div class="db-note">${escapeHtml(t(`dbPeriod_${s.period}`))} · ${escapeHtml(when)}${s.model ? ` · ${escapeHtml(s.model)}` : ''}</div>`;
}

async function makeDashSummary() {
  if (DB.summaryBusy) return;
  const period = dbPrefs().period;
  DB.summaryBusy = true;
  renderDashboard();
  try {
    const res = await fetch('/api/library/digest', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ days: { week: 7, month: 31, quarter: 92 }[period], lang: state.uiLang === 'en' ? 'en' : 'ru' }),
    });
    const data = await readJson(res);
    if (!res.ok) throw new Error(errorText(data, res));
    // the citations [1] of the digest point to its sources, which this card does not show
    const md = String(data.answer || '').replace(/\s?\[\d+(?:\s*[,–-]\s*\d+)*\]/g, '');
    dbSave({ summary: { period, at: Date.now(), html: sanitizedMarkdown(md), model: data.model || '' } });
  } catch (e) {
    showError(serverText(e.message));
  } finally {
    DB.summaryBusy = false;
    if (state.appView === 'dashboard') renderDashboard();
  }
}

// --- Actions ---
function dbRefreshDetail() {
  if (DB_DETAIL.kind) dbOpenDetail(DB_DETAIL.kind, DB_DETAIL.person);
}

function setDashPeriod(period) {
  dbSave({ period });
  loadDashboard();
  renderDashboard();
  dbRefreshDetail();
}

function setDashFeature(id) {
  dbSave({ feature: Number(id) || 0 });
  loadDashboard();
  renderDashboard();
  dbRefreshDetail();
}

function openDashFeatureMenu(e) {
  const p = dbPrefs();
  const used = new Set((state.meetings || []).flatMap(m => m.features || []));
  const feats = (state.features || []).filter(f => used.has(f.id)).sort((a, b) => _libCollator.compare(a.name, b.name));
  const tick = (on, label) => `${on ? '✓' : ' '}  ${label}`;
  e.stopPropagation();
  const r = e.currentTarget.getBoundingClientRect();
  openTextMenuAt([{ label: tick(!p.feature, t('dbAllFeatures')), run: () => setDashFeature(0) }, { sep: true },
    ...feats.map(f => ({ label: tick(p.feature === f.id, f.name), run: () => setDashFeature(f.id) }))], r.left, r.bottom + 4);
}

async function dashTaskDone(id) {
  const res = await fetch(`/api/tasks/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'done' }) });
  if (!res.ok) { showToast(errorText(await readJson(res), res)); return; }
  if (DB.data) DB.data.tasks = DB.data.tasks.filter(x => x.id !== id);
  renderDashboard();
  showToast(t('dbTaskDone'), { label: t('spUndo'), onClick: async () => {
    await fetch(`/api/tasks/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'open' }) });
    loadDashboard();
  } }, 'success');
  loadDashboard();
  if (typeof loadTasks === 'function') loadTasks();
}

function dashOpenTask(id, meetingId) {
  if (meetingId) { openMeeting(meetingId); setTimeout(() => openRecordTab('summary'), 300); }
  else switchAppView('tasks');
}

function dashOpenSummary(meetingId) {
  openMeeting(meetingId);
  setTimeout(() => openRecordTab('summary'), 300);
}

// --- «Жду от других»: what others promised the user (asked by the user) ---
function dbWaitingHtml(d, size) {
  if (d.needs_me) return `<div class="db-note">${escapeHtml(t('dbNeedsMe'))}</div><button class="tk-btn tk-btn-sm" data-click="hmSetMyName">${escapeHtml(t('dbSetMe'))}</button>`;
  const list = d.waiting || [];
  if (!list.length) return `<div class="db-note">${escapeHtml(t('dbNoWaiting'))}</div>`;
  const n = size === 'S' ? 4 : size === 'W' ? 10 : 6;
  return list.slice(0, n).map(x => `<div class="db-task db-task-wait">`
    + `<span class="db-who" title="${escapeHtml(x.who)}">${escapeHtml(x.who || '—')}</span>`
    + `<button class="db-task-t" data-click="dashOpenTask" data-click-args='[${x.id}, ${Number(x.meeting_id) || 0}]' title="${escapeHtml(x.meeting_title ? `${x.what} — ${x.meeting_title}` : x.what)}">${escapeHtml(x.what)}</button>`
    + (x.due_date ? dbDue(x, d.today) : `<span class="db-due">${escapeHtml(t('dbDaysWaiting').replace('{n}', () => x.days || 0))}</span>`) + '</div>').join('');
}

// --- The details of a number or a widget (asked by the user: hours, tasks, decisions could not be opened):
// a panel on the right with what it is made of, by /api/dashboard/detail (app/dashboard.detail) ---
const DB_DETAIL = { kind: '', person: '', data: null, filter: 'all' };

async function dbOpenDetail(kind, person = '') {
  const p = dbPrefs();
  Object.assign(DB_DETAIL, { kind, person, data: null, filter: kind === 'useless' ? 'useless' : 'all' });
  dbRenderDetail();
  const q = new URLSearchParams({ kind, period: p.period, feature: p.feature || 0, person });
  const data = await fetch(`/api/dashboard/detail?${q}`).then(r => (r.ok ? r.json() : null)).catch(() => null);
  if (DB_DETAIL.kind !== kind || DB_DETAIL.person !== person) return;  // another one opened meanwhile
  DB_DETAIL.data = data || { error: true };
  dbRenderDetail();
}

function dbCloseDetail() {
  DB_DETAIL.kind = '';
  document.getElementById('db-detail')?.classList.add('hidden');
}

function dbDetailFilter(f) {
  DB_DETAIL.filter = f;
  dbRenderDetail();
}

function dbHm(sec) {
  const m = Math.round((sec || 0) / 60);
  return m >= 60 ? `${Math.floor(m / 60)} ${t('dbHoursShort')} ${String(m % 60).padStart(2, '0')} ${t('dbMinShort')}` : `${m} ${t('dbMinShort')}`;
}

function dbDetailMeetings(d) {
  const rows = DB_DETAIL.filter === 'useless' ? d.meetings.filter(r => r.reasons.length) : d.meetings;
  const total = rows.reduce((s, r) => s + r.duration, 0);
  const chips = (d.by_feature || []).slice(0, 6).map(x => {
    const f = x.feature ? featureById(x.feature) : null;
    return `<span class="db-dt-chip">${f ? featureChipHtml(f) : escapeHtml(t('dbNoFeature'))} ${dbNum(x.hours)} ${escapeHtml(t('dbHoursShort'))}</span>`;
  }).join('');
  const seg = `<div class="tk-seg db-dt-seg" role="radiogroup">${['all', 'useless'].map(k => `<button role="radio" aria-checked="${DB_DETAIL.filter === k}" class="tk-seg-btn${DB_DETAIL.filter === k ? ' tk-on' : ''}" data-click="dbDetailFilter" data-click-args='["${k}"]'>${escapeHtml(t(k === 'all' ? 'dbDtAll' : 'dbDtUseless'))}${k === 'useless' ? ` · ${d.meetings.filter(r => r.reasons.length).length}` : ''}</button>`).join('')}</div>`;
  const reason = r => r.reasons.map(x => `<span class="db-dt-why" title="${escapeHtml(t(`dbWhy_${x}_tip`))}">${escapeHtml(t(`dbWhy_${x}`))}</span>`).join('');
  const list = rows.map(r => {
    const f = (r.features || []).map(featureById).filter(Boolean)[0];
    return `<button class="db-dt-row" data-click="dashOpenSummary" data-click-args='[${r.id}]'>`
      + `<span class="db-dt-when">${escapeHtml(dbAgo(r.date, DB.data ? DB.data.today : r.date))}${r.time ? ` ${escapeHtml(r.time)}` : ''}</span>`
      + `<span class="db-dt-main"><b>${escapeHtml(r.title || t('hmUntitled'))}</b><small>${f ? featureChipHtml(f) : ''}${reason(r)}</small></span>`
      + `<span class="db-dt-num" title="${escapeHtml(t('dbDtDecTip'))}">${r.decisions}</span>`
      + `<span class="db-dt-num" title="${escapeHtml(t('dbDtTaskTip'))}">${r.tasks}</span>`
      + `<span class="db-dt-num" title="${escapeHtml(t('dbDtShareTip'))}">${r.my_share == null ? '—' : `${Math.round(r.my_share)}%`}</span>`
      + `<span class="db-dt-dur">${escapeHtml(dbHm(r.duration))}</span></button>`;
  }).join('');
  return `<div class="db-dt-sum">${escapeHtml(t('dbDtMeetingsSum').replace('{n}', () => rows.length).replace('{h}', () => dbHm(total)))}</div>`
    + (chips ? `<div class="db-dt-chips">${chips}</div>` : '') + seg
    + (rows.length ? `<div class="db-dt-head"><span></span><span></span><span>${escapeHtml(t('dbDtDec'))}</span><span>${escapeHtml(t('dbDtTasks'))}</span><span>${escapeHtml(t('dbDtShare'))}</span><span></span></div>${list}`
      : `<div class="db-note">${escapeHtml(t(DB_DETAIL.filter === 'useless' ? 'dbUselessNone' : 'dbNoMeetingsYet'))}</div>`);
}

function dbDetailTasks(list, today, mine) {
  if (!list.length) return `<div class="db-note">${escapeHtml(t(mine ? 'dbNoMyTasks' : 'dbNoWaiting'))}</div>`;
  return list.map(x => `<div class="db-dt-task${x.status === 'done' ? ' done' : ''}">`
    + (mine && x.status !== 'done' ? `<button class="db-ck" data-click="dbDetailDone" data-click-args='[${x.id}]' title="${escapeHtml(t('dbMarkDone'))}" aria-label="${escapeHtml(t('dbMarkDone'))}"></button>` : '<span class="db-ck-gap"></span>')
    + `<button class="db-dt-main" data-click="dashOpenTask" data-click-args='[${x.id}, ${Number(x.meeting_id) || 0}]'><b>${escapeHtml(x.what)}</b>`
    + `<small>${escapeHtml([mine ? (x.to ? `→ ${x.to}` : '') : x.who, x.meeting_title ? `«${x.meeting_title}»` : '', x.meeting_date ? dbAgo(x.meeting_date, today) : ''].filter(Boolean).join(' · '))}</small></button>`
    + (x.due_date ? dbDue(x, today) : `<span class="db-due">${escapeHtml(mine ? t('tkNoDue') : t('dbDaysWaiting').replace('{n}', () => x.days || 0))}</span>`) + '</div>').join('');
}

async function dbDetailDone(id) {
  await dashTaskDone(id);
  dbOpenDetail(DB_DETAIL.kind, DB_DETAIL.person);
}

function dbRenderDetail() {
  const box = document.getElementById('db-detail');
  if (!box) return;
  const { kind, person, data: d } = DB_DETAIL;
  box.classList.toggle('hidden', !kind);
  if (!kind) return;
  const today = DB.data ? DB.data.today : new Date().toISOString().slice(0, 10);
  const title = kind === 'person' ? person : t(`dbDt_${kind}`);
  const period = DB.data && kind !== 'person' ? `<div class="db-dt-period">${escapeHtml(document.getElementById('db-sub')?.textContent || '')}</div>` : '';
  let body;
  if (!d) body = `<div class="db-note">${escapeHtml(t('dbLoading'))}</div>`;
  else if (d.error) body = `<div class="db-note">${escapeHtml(t('dbNoData'))}</div>`;
  else if (kind === 'meetings' || kind === 'useless') body = dbDetailMeetings(d);
  else if (kind === 'decisions') {
    body = d.decisions.length ? d.decisions.map(x => {
      const f = (x.features || []).map(featureById).filter(Boolean)[0];
      return `<button class="db-dt-row db-dt-dec" data-click="dashOpenSummary" data-click-args='[${x.meeting_id}]'><span class="db-dt-main"><b>${escapeHtml(x.text)}</b>`
        + `<small>${f ? featureChipHtml(f) : ''}«${escapeHtml(x.title)}» · ${escapeHtml(dbAgo(x.date, today))}</small></span></button>`;
    }).join('') : `<div class="db-note">${escapeHtml(t('dbNoDecisionsYet'))}</div>`;
  } else if (kind === 'tasks' || kind === 'waiting') {
    body = d.needs_me ? `<div class="db-note">${escapeHtml(t('dbNeedsMe'))}</div>` : dbDetailTasks(d.tasks, today, kind === 'tasks');
  } else {  // a person
    body = `<div class="db-dt-sec">${escapeHtml(t('dbDtOwesMe'))}</div>${dbDetailTasks(d.owes_me || [], today, false)}`
      + `<div class="db-dt-sec">${escapeHtml(t('dbDtIOwe'))}</div>${dbDetailTasks(d.i_owe || [], today, true)}`
      + `<div class="db-dt-sec">${escapeHtml(t('dbDtTheirMeetings').replace('{n}', () => d.meetings_total || 0))}</div>`
      + ((d.meetings || []).map(m => `<button class="db-dt-row" data-click="dashOpenSummary" data-click-args='[${m.id}]'><span class="db-dt-when">${escapeHtml(dbAgo(m.date, today))}</span>`
        + `<span class="db-dt-main"><b>${escapeHtml(m.title || t('hmUntitled'))}</b></span><span class="db-dt-dur">${escapeHtml(dbHm(m.duration))}</span></button>`).join('')
        || `<div class="db-note">${escapeHtml(t('dbNoMeetingsYet'))}</div>`)
      + `<button class="tk-btn tk-btn-sm db-dt-card" data-click="openPersonCard" data-click-args='[${JSON.stringify(person)}]'>${escapeHtml(t('dbDtCard'))}</button>`;
  }
  box.innerHTML = `<div class="db-dt-top"><h2>${escapeHtml(title)}</h2><button class="hm-x" data-click="dbCloseDetail" title="${escapeHtml(t('close'))}" aria-label="${escapeHtml(t('close'))}">✕</button></div>${period}<div class="db-dt-body">${body}</div>`;
}

document.addEventListener('keydown', e => { if (e.key === 'Escape' && DB_DETAIL.kind) dbCloseDetail(); });

// --- «Настроить»: drag, sizes, remove, add ---
function toggleDashEdit() {
  DB.edit = !DB.edit;
  renderDashboard();
}

function setDashSize(i, size) {
  const layout = dbPrefs().layout.slice();
  layout[i] = { ...layout[i], size };
  dbSave({ layout });
  renderDashboard();
}

function removeDashWidget(i) {
  const layout = dbPrefs().layout.slice();
  layout.splice(i, 1);
  dbSave({ layout });
  renderDashboard();
}

function addDashWidget(id) {
  const def = DB_WIDGETS[id];
  if (!def) return;
  dbSave({ layout: [...dbPrefs().layout, { id, size: def.sizes[Math.min(1, def.sizes.length - 1)] }] });
  renderDashboard();
  document.querySelector('#db-grid .db-w:last-child')?.scrollIntoView({ block: 'nearest', behavior: scrollMotion() });
}

function resetDashboard() {
  dbSave({ layout: DB_DEFAULT.map(([id, size]) => ({ id, size })) });
  renderDashboard();
}

function renderDashDrawer() {
  const box = document.getElementById('db-drawer');
  if (!box) return;
  box.classList.toggle('hidden', !DB.edit);
  if (!DB.edit) { box.innerHTML = ''; return; }
  const on = new Set(dbPrefs().layout.map(w => w.id));
  const item = (id, add) => `<div class="db-lib${add ? '' : ' on'}"><span class="db-lib-ic">${DB_WIDGETS[id].icon}</span>`
    + `<span class="db-lib-tx"><b>${escapeHtml(t(DB_WIDGETS[id].title))}</b><span>${escapeHtml(t(`dbAbout_${id}`))}</span></span>`
    + (add ? `<button class="db-lib-add" data-click="addDashWidget" data-click-args='["${id}"]'>${escapeHtml(t('dbAdd'))}</button>` : '') + '</div>';
  const ids = Object.keys(DB_WIDGETS);
  box.innerHTML = `<h2>${escapeHtml(t('dbWidgets'))}</h2><p class="db-note">${escapeHtml(t('dbEditHint'))}</p>`
    + (ids.some(id => !on.has(id)) ? `<div class="db-cap">${escapeHtml(t('dbAddCap'))}</div>${ids.filter(id => !on.has(id)).map(id => item(id, true)).join('')}` : '')
    + `<div class="db-cap">${escapeHtml(t('dbOnCap'))}</div>${ids.filter(id => on.has(id)).map(id => item(id, false)).join('')}`
    + `<div class="db-drawer-foot"><button class="tk-btn tk-btn-sm" data-click="resetDashboard">${escapeHtml(t('dbReset'))}</button>`
    + `<button class="tk-btn tk-btn-primary tk-btn-sm" data-click="toggleDashEdit">${escapeHtml(t('dbDone'))}</button></div>`;
}

(function wireDashboard() {
  const grid = document.getElementById('db-grid');
  if (!grid) return;
  grid.addEventListener('dragstart', (e) => {
    const w = DB.edit && e.target.closest && e.target.closest('.db-w');
    if (!w) return;
    DB.drag = Number(w.dataset.i);
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', `db:${DB.drag}`);
    requestAnimationFrame(() => w.classList.add('db-dragging'));
  });
  grid.addEventListener('dragover', (e) => {
    if (DB.drag == null) return;
    const w = e.target.closest && e.target.closest('.db-w');
    e.preventDefault();
    grid.querySelectorAll('.db-drop').forEach(x => x.classList.remove('db-drop'));
    if (w && Number(w.dataset.i) !== DB.drag) w.classList.add('db-drop');
  });
  grid.addEventListener('drop', (e) => {
    if (DB.drag == null) return;
    e.preventDefault();
    const w = e.target.closest && e.target.closest('.db-w');
    const from = DB.drag, to = w ? Number(w.dataset.i) : dbPrefs().layout.length - 1;
    DB.drag = null;
    if (from === to) { renderDashboard(); return; }
    const layout = dbPrefs().layout.slice();
    const [moved] = layout.splice(from, 1);
    layout.splice(to, 0, moved);
    dbSave({ layout });
    renderDashboard();
  });
  grid.addEventListener('dragend', () => { DB.drag = null; grid.querySelectorAll('.db-dragging, .db-drop').forEach(x => x.classList.remove('db-dragging', 'db-drop')); });
})();

registerView('dashboard', {
  show: () => {
    // the greeting and the date of the former home page in the head of the dashboard
    const hello = document.querySelector('#home-view .hm-hello'), slot = document.getElementById('db-hello');
    if (hello && slot && !slot.contains(hello)) slot.appendChild(hello);
    const qa = document.querySelector('#home-view .hm-head > .flex'), qslot = document.getElementById('db-qa');
    if (qa && qslot && !qslot.contains(qa)) qslot.appendChild(qa);
    renderDashboard();
    if (typeof renderHome === 'function') renderHome();
    loadDashboard();
  },
  hide: () => { DB.edit = false; },
  refresh: (changed) => { if (changed) loadDashboard(); if (typeof renderHome === 'function') renderHome(); },
});
