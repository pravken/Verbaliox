// Verbaliox page script: «Обзор» (static/parts/dashboard.html; docs/pult-plan.md, stage 3), the analytics of a
// period: widgets the user arranges («Настроить»: dragged, sized S · M · L · W, removed, added from the list), kept
// with the settings. The data widgets read /api/dashboard (app/dashboard.py) for the period and the feature chosen;
// «Частые участники» and «Мои программы» have a period of their own. ‹ › go back to any past period (DB.at, not
// kept with the settings: the app opens on the current one), its figures compared with the period before or the
// same days a year earlier (dbPrefs().compare). The day (its meetings and its cards) is «Сегодня»
// (static/js/today.js), which draws its cards with the functions of this file.
// The parts are classic scripts sharing one global scope, loaded in order by index.html.

const DB_KEY = 'vx-dashboard';
// of 12 columns: two M, an S and an L, three S fill a row (reported by the user: M and M left a hole)
const DB_SIZES = { S: 4, M: 6, L: 8, W: 12 };
// Every widget: its title key and the sizes it takes
const DB_WIDGETS = {
  kpis: { title: 'dbStats', sizes: ['L', 'W'], icon: '▦' },
  mytasks: { title: 'hmMyTasks', sizes: ['S', 'M', 'L', 'W'], icon: '☑' },
  waiting: { title: 'dbWaiting', sizes: ['S', 'M', 'L', 'W'], icon: '⧗' },
  features: { title: 'dbFeatures', sizes: ['M', 'L', 'W'], icon: '◆' },
  time: { title: 'dbTime', sizes: ['S', 'M', 'L', 'W'], icon: '▮' },
  people: { title: 'dbPeople', sizes: ['S', 'M', 'L'], icon: '☺' },
  decisions: { title: 'dbDecisions', sizes: ['S', 'M', 'L', 'W'], icon: '✓' },
  summary: { title: 'dbSummary', sizes: ['S', 'M', 'L', 'W'], icon: '✦' },
  load: { title: 'dbLoad', sizes: ['S', 'M', 'L', 'W'], icon: '▥' },
  dull: { title: 'dbDull', sizes: ['S', 'M', 'L', 'W'], icon: '↻' },
  // asked by the user: how long the working day lasted (app/worktime.py), against the norm
  worked: { title: 'dbWorked', sizes: ['S', 'M', 'L', 'W'], icon: '⏱' },
  // asked by the user: where the working time goes, by the program in front (app/worktime.py); off until turned on
  apps: { title: 'dbApps', sizes: ['M', 'L', 'W'], icon: '▤' },
  // asked by the user: the load of the computer and the models in memory, as the «Нагрузка» window of the status bar
  sysload: { title: 'dbSysload', sizes: ['S', 'M', 'L'], icon: '◫' },
};
// rows that add up to 12: W · M+M · L+S · M+M · W
const DB_DEFAULT = [['kpis', 'W'], ['time', 'M'], ['load', 'M'], ['features', 'L'], ['people', 'S'], ['decisions', 'M'], ['dull', 'M'], ['summary', 'W']];
const DB_PERIODS = ['week', 'month', 'quarter', 'year'];
// what the figures of «Статистика» are compared with: the period before, or the same days a year earlier
const DB_COMPARE = ['prev', 'year'];
// added after the first dashboard: offered once to an existing layout, after the widget named (removed by
// the user, it stays out)
const DB_NEW_WIDGETS = [['waiting', 'mytasks'], ['load', 'time'], ['dull', 'decisions'], ['worked', 'kpis']];
// «Статистика»: the figures shown, in their order (2 to 8), and those of a new layout
const DB_KPI_DEFAULT = ['meetings', 'hours', 'focus', 'mine', 'decisions', 'useless'];
const DB_KPI_MAX = 8, DB_KPI_MIN = 2;
// the period of one widget («Частые участники», «Мои программы»), apart from the page's own
const DB_WPERIODS = ['day', 'week', 'month', 'year'];

// at: the first day of the past period shown (YYYY-MM-DD), '' for the current one
const DB = { data: null, week: null, prevWeek: null, edit: false, loading: false, prefs: null, drag: null, summaryBusy: false, kpiCfg: false, people: null, at: '' };

function dbPrefs() {
  if (DB.prefs) return DB.prefs;
  let p = {};
  try { p = JSON.parse(localStorage.getItem(DB_KEY) || '{}') || {}; } catch (e) {}
  const layout = Array.isArray(p.layout) ? p.layout.filter(w => w && DB_WIDGETS[w.id]) : null;
  // a widget added in a later version comes once into a layout made before it (after «Мои задачи»);
  // removed by the user, it stays out
  const offered = Array.isArray(p.offered) ? p.offered : [];
  if (layout && layout.length) {
    for (const [id, after] of DB_NEW_WIDGETS) {
      if (offered.includes(id) || layout.some(w => w.id === id)) continue;
      const at = layout.findIndex(w => w.id === after);
      layout.splice(at < 0 ? layout.length : at + 1, 0, { id, size: DB_WIDGETS[id].sizes.includes('M') ? 'M' : DB_WIDGETS[id].sizes[0] });
    }
  }
  return DB.prefs = {
    offered: [...new Set([...offered, ...DB_NEW_WIDGETS.map(([id]) => id)])],
    norm: [2, 3, 4, 5, 6].includes(Number(p.norm)) ? Number(p.norm) : 4,
    days: p.days === 'work' ? 'work' : 'cal',
    layout: layout && layout.length ? layout : DB_DEFAULT.map(([id, size]) => ({ id, size })),
    period: DB_PERIODS.includes(p.period) ? p.period : 'week',
    compare: DB_COMPARE.includes(p.compare) ? p.compare : 'prev',
    feature: Number(p.feature) || 0,
    summary: p.summary && typeof p.summary === 'object' ? p.summary : null,
    // «Сегодня»: the day, the week or the month of its calendar (static/js/today.js)
    span: ['day', 'week', 'month'].includes(p.span) ? p.span : 'day',
    kpis: dbKpiList(p.kpis),
    // the look of each chart widget («col», «bar», «ring», «line»; «Мои программы»: «list», «ring», «col»)
    charts: p.charts && typeof p.charts === 'object' ? p.charts : {},
    wperiod: p.wperiod && typeof p.wperiod === 'object' ? p.wperiod : {},
  };
}

function dbSave(changes) {
  DB.prefs = { ...dbPrefs(), ...changes };
  const text = JSON.stringify(DB.prefs);
  try { localStorage.setItem(DB_KEY, text); } catch (e) {}
  // the server keeps the layout too (ui_dashboard): localStorage is per port, see syncUiPrefsFromServer
  clearTimeout(DB.saveTimer);
  DB.saveTimer = setTimeout(() => saveUiSetting('ui_dashboard', text), 800);
}

// The layout kept on the server wins over this origin's copy (another port had none, or an older one)
function dbPrefsFromServer(settings) {
  let local = null;
  try { local = localStorage.getItem(DB_KEY); } catch (e) {}
  const server = settings.ui_dashboard;
  if (!server) {
    if (local) saveUiSetting('ui_dashboard', local);  // made before the server kept it
    return;
  }
  if (server === local) return;
  try { const v = JSON.parse(server); if (!v || typeof v !== 'object') return; } catch (e) { return; }
  try { localStorage.setItem(DB_KEY, server); } catch (e) {}
  DB.prefs = null;
  if (state.appView === 'dashboard') { renderDashboard(); loadDashboard(); }
  else if (state.appView === 'home' && typeof tdRender === 'function') tdRender();
}

function dbSize(w) {
  const sizes = DB_WIDGETS[w.id].sizes;
  return sizes.includes(w.size) ? w.size : sizes[Math.min(1, sizes.length - 1)];
}

// --- Data ---
// keepWeek: the period only moved (‹ ›, «Текущий период», another period or comparison): the week of «Нагрузка
// недели» and «Рабочий день» is asked again only when it is another week
async function loadDashboard({ keepWeek = false } = {}) {
  const p = dbPrefs();
  const seq = (DB.seq = (DB.seq || 0) + 1);  // a period switched quickly: only the last answer is shown
  DB.loading = true;
  const q = `period=${p.period}${p.feature ? `&feature=${p.feature}` : ''}${DB.at ? `&at=${DB.at}` : ''}&compare=${p.compare}`
    + `&lang=${state.uiLang === 'en' ? 'en' : 'ru'}`;
  // every request on its own, each widget drawn in place as its data comes (the grid is shown at once with what
  // is known; the widgets are not drawn anew, so they do not rise a second time)
  const fresh = ids => { if (seq === DB.seq && state.appView === 'dashboard' && !DB.edit && !(DB.drag && DB.drag.on)) ids.forEach(dbRedrawWidget); };
  const side = [
    ...dbLoadWeekWidgets(keepWeek),
    dbLoadApps().then(() => fresh(['apps'])),
    dbLoadPeople().then(() => fresh(['people'])),
  ];
  const data = await fetch(`/api/dashboard?${q}`).then(r => (r.ok ? r.json() : null)).catch(() => null);
  if (seq !== DB.seq) return;
  DB.loading = false;
  // a failed request keeps what was shown rather than an empty «Обзор»
  DB.data = data || (DB.data && DB.data.period === p.period && DB.data.start === dbSpan()[0] ? DB.data : null);
  if (state.appView === 'dashboard') {
    dbRenderHead();
    fresh(dbPrefs().layout.map(w => w.id).filter(id => !DB_LOCAL_WIDGETS.includes(id) || id === 'people'));
  }
  await Promise.all(side);
}

// The week of «Нагрузка недели» and «Рабочий день»: the current one, or for a past period (DB.at) the week of its
// last day (a past week: that week; a month, a quarter, a year: its last week). Found in review: a past period
// showed the current week in both
function dbWeekMonday() {
  if (!DB.at) return dbMonday();
  const last = new Date(`${dbSpan()[1]}T12:00:00`);
  last.setDate(last.getDate() - 1);
  return dbMonday(last);
}

// What the two widgets draw: the current week (DB.week, DB.prevWeek, DB.work — «Главная» reads them too), or the
// past one of DB.past, loaded for its Monday
function dbWeekData() {
  const monday = dbWeekMonday();
  if (!DB.at) return { week: DB.week, prev: DB.prevWeek, work: DB.work, monday, past: false };
  const P = DB.past && DB.past.monday === calKey(monday) ? DB.past : {};
  return { week: P.week, prev: P.prev, work: P.work, monday, past: true };
}

// The requests of the week's widgets; none for a week already loaded when the period only moved (keep)
function dbLoadWeekWidgets(keep) {
  const monday = dbWeekMonday(), key = calKey(monday), before = new Date(monday);
  before.setDate(monday.getDate() - 7);
  const draw = (ids, ok) => { if (ok() && state.appView === 'dashboard' && !DB.edit && !(DB.drag && DB.drag.on)) ids.forEach(dbRedrawWidget); };
  if (DB.at) {
    if (keep && DB.past && DB.past.monday === key) return [];
    const P = (DB.past = { monday: key }), mine = () => DB.past === P;  // a later week does not take this one's answers
    return [
      dbLoadWeek(monday).then(w => { if (w) P.week = w; draw(['load'], mine); }),
      dbLoadPrevWeek(monday).then(w => { if (w) P.prev = w; draw(['load'], mine); }),
      dbLoadWork(monday, P).then(() => draw(['worked'], mine)),
    ];
  }
  const cur = () => !DB.at && calKey(dbMonday()) === key;
  return [
    keep && DB.week && DB.week.monday === key ? null : dbLoadWeek(monday).then(w => { if (w && cur()) DB.week = w; draw(['load'], cur); }),
    keep && DB.prevWeek && DB.prevWeek.monday === calKey(before) ? null
      : dbLoadPrevWeek(monday).then(w => { if (w && cur()) DB.prevWeek = w; draw(['load'], cur); }),
    keep && DB.work && DB.work.monday === key ? null : dbLoadWork(monday).then(() => draw(['worked'], cur)),
  ].filter(Boolean);
}

// The period around a day, as app/dashboard._bounds: [first day, the day after the last] as YYYY-MM-DD
function dbBounds(period, day) {
  const y = day.getFullYear(), m = day.getMonth();
  let a, b;
  if (period === 'year') { a = new Date(y, 0, 1); b = new Date(y + 1, 0, 1); }
  else if (period === 'quarter') { a = new Date(y, m - m % 3, 1); b = new Date(y, m - m % 3 + 3, 1); }
  else if (period === 'month') { a = new Date(y, m, 1); b = new Date(y, m + 1, 1); }
  else { a = dbMonday(day); b = new Date(a); b.setDate(a.getDate() + 7); }
  return [calKey(a), calKey(b)];
}

// The period shown: the current one, or the past one DB.at is in
function dbSpan() {
  return dbBounds(dbPrefs().period, DB.at ? new Date(`${DB.at}T12:00:00`) : new Date());
}

// A past period stays one only when it is not the current one (a period switched from a past week may hold today)
function dbSetAt(day) {
  const period = dbPrefs().period, cur = dbBounds(period, new Date())[0];
  const start = day ? dbBounds(period, new Date(`${day}T12:00:00`))[0] : '';
  DB.at = start && start < cur ? start : '';
}

// The name of the period shown: «17–23 ноября», «Октябрь 2026», «III квартал 2026», «2025»
function dbSpanName() {
  const p = dbPrefs().period, [a] = dbSpan(), lang = state.uiLang === 'en' ? 'en-US' : 'ru-RU';
  const first = new Date(`${a}T12:00:00`);
  const y = first.getFullYear();
  if (p === 'year') return String(y);
  if (p === 'quarter') {
    const q = Math.floor(first.getMonth() / 3);
    return t('dbQuarterName').replace('{q}', () => ['I', 'II', 'III', 'IV'][q]).replace('{n}', () => q + 1).replace('{y}', () => y);
  }
  if (p === 'month') {
    const name = first.toLocaleDateString(lang, { month: 'long' });
    return `${name.charAt(0).toUpperCase()}${name.slice(1)} ${y}`;
  }
  return dbWeekName(first);
}

// A week by its days: «17–23 ноября», «27 октября – 2 ноября», with the year when it is not the current one
function dbWeekName(first) {
  const lang = state.uiLang === 'en' ? 'en-US' : 'ru-RU', last = new Date(first);
  last.setDate(first.getDate() + 6);
  const other = last.getFullYear() !== new Date().getFullYear() ? ` ${last.getFullYear()}` : '';
  const day = x => x.toLocaleDateString(lang, { day: 'numeric' });
  if (first.getMonth() === last.getMonth()) {
    const month = last.toLocaleDateString(lang, { day: 'numeric', month: 'long' }).replace(/\d+/, '').trim();
    return lang === 'en-US' ? `${month} ${day(first)}–${day(last)}${other}` : `${day(first)}–${day(last)} ${month}${other}`;
  }
  const dm = x => x.toLocaleDateString(lang, { day: 'numeric', month: 'long' });
  return `${dm(first)} – ${dm(last)}${other}`;
}

// ‹ the period before · its name · the next one › (none after the current one), «Текущий период» back to it
function dbRenderNav() {
  const el = document.getElementById('db-nav');
  if (!el) return;
  const now = !DB.at;
  const arrow = d => `<svg aria-hidden="true" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`;
  el.innerHTML = (now ? '' : `<button class="tk-btn" data-click="dbToCurrent" title="${escapeHtml(t('dbNavNowTip'))}">${escapeHtml(t('dbNavNow'))}</button>`)
    + `<button class="tk-btn tk-btn-sq" data-click="dbShiftPeriod" data-click-args="[-1]" title="${escapeHtml(t('dbNavPrev'))}" aria-label="${escapeHtml(t('dbNavPrev'))}">${arrow('M15 6l-6 6 6 6')}</button>`
    + `<span class="db-nav-name" aria-live="polite">${escapeHtml(dbSpanName())}</span>`
    + `<button class="tk-btn tk-btn-sq" data-click="dbShiftPeriod" data-click-args="[1]" ${now ? 'disabled' : ''} title="${escapeHtml(t('dbNavNext'))}" aria-label="${escapeHtml(t('dbNavNext'))}">${arrow('M9 6l6 6-6 6')}</button>`;
}

function dbShiftPeriod(step) {
  const [a, b] = dbSpan();
  if (step > 0 && !DB.at) return;
  const day = new Date(`${step < 0 ? a : b}T12:00:00`);
  if (step < 0) day.setDate(day.getDate() - 1);
  dbSetAt(calKey(day));
  dbReload();
}

function dbToCurrent() {
  DB.at = '';
  dbReload();
}

function dbReload() {
  loadDashboard({ keepWeek: true });
  renderDashboard();
  dbRefreshDetail();
}

function dbMonday(d = new Date()) {
  const x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  x.setDate(x.getDate() - ((x.getDay() + 6) % 7));
  return x;
}

// The days of a widget's own period: today, this week, this month, this year ([start, end) as YYYY-MM-DD)
function dbWPeriod(id) {
  const p = (dbPrefs().wperiod || {})[id];
  return DB_WPERIODS.includes(p) ? p : 'week';
}

function dbWRange(id) {
  // «Мои программы» follow the working day of app/worktime.py: before 4 in the morning it is still the day before
  // (a night's work counted «сегодня» showed nothing — found in review)
  const now = new Date(Date.now() - (id === 'apps' ? 4 * 3600 * 1000 : 0)), p = dbWPeriod(id);
  let a, b;
  if (p === 'day') { a = new Date(now.getFullYear(), now.getMonth(), now.getDate()); b = new Date(a); b.setDate(a.getDate() + 1); }
  else if (p === 'month') { a = new Date(now.getFullYear(), now.getMonth(), 1); b = new Date(now.getFullYear(), now.getMonth() + 1, 1); }
  else if (p === 'year') { a = new Date(now.getFullYear(), 0, 1); b = new Date(now.getFullYear() + 1, 0, 1); }
  else { a = dbMonday(now); b = new Date(a); b.setDate(a.getDate() + 7); }
  return [calKey(a), calKey(b)];
}

// What a widget's period holds, in words: «сегодня», «с 16 ноября», «с 1 января»; «с 3 ноября, когда включён
// учёт» when what is counted began later than the period (since: its first day)
function dbWSince(id, since = '') {
  const [a] = dbWRange(id);
  const fmt = k => new Date(`${k}T12:00:00`).toLocaleDateString(state.uiLang === 'en' ? 'en-GB' : 'ru-RU', { day: 'numeric', month: 'long' });
  if (since && since > a) return t('dbSinceOn').replace('{d}', () => fmt(since));
  return dbWPeriod(id) === 'day' ? t('dbWpCap_day') : t('dbSince').replace('{d}', () => fmt(a));
}

// «Частые участники» of its own period (app/dashboard.people), only while the widget is on «Обзор»
async function dbLoadPeople() {
  if (!dbPrefs().layout.some(w => w.id === 'people')) return;
  const [a, b] = dbWRange('people'), f = dbPrefs().feature;
  const asked = `${a}|${b}|${f}`;
  const r = await fetch(`/api/dashboard/people?start=${a}&end=${b}${f ? `&feature=${f}` : ''}`).then(x => (x.ok ? x.json() : null)).catch(() => null);
  // the period or the feature changed meanwhile: a late answer does not replace the newer one
  const [a2, b2] = dbWRange('people');
  if (r && asked === `${a2}|${b2}|${dbPrefs().feature}`) DB.people = { period: dbWPeriod('people'), list: r.people || [] };
}

// The hours worked of this week (app/worktime.py): asked again at each tick, the minutes go on
// (or of the week from Monday `a`, into `into`: a past week of «Обзор» goes to DB.past)
async function dbLoadWork(a = dbMonday(), into = DB) {
  const b = new Date(a);
  b.setDate(a.getDate() + 7);
  const w = await fetch(`/api/worktime?start=${calKey(a)}&end=${calKey(b)}`).then(r => (r.ok ? r.json() : null)).catch(() => null);
  if (w) into.work = { ...w, monday: calKey(a) };
}

// «Мои программы» of this week and the one before (app/worktime.py), only while the widget is on «Главная»
async function dbLoadApps() {
  if (!dbPrefs().layout.some(w => w.id === 'apps')) return;
  const [a, b] = dbWRange('apps');
  const r = await fetch(`/api/worktime/apps?start=${a}&end=${b}`).then(x => (x.ok ? x.json() : null)).catch(() => null);
  const [a2, b2] = dbWRange('apps');
  if (r && a === a2 && b === b2) DB.apps = { ...r, period: dbWPeriod('apps') };  // not a late answer of another period
}

// «7 ч 45» for a day's head: the hours worked, short
function dbWorkedShort(min) {
  return min ? `${Math.floor(min / 60)}:${String(min % 60).padStart(2, '0')}` : '';
}

// The calendar and the recordings of the week from Monday `a` (this week by default), with that Monday
async function dbLoadWeek(a = dbMonday()) {
  const b = new Date(a);
  b.setDate(a.getDate() + 7);
  const w = await fetch(`/api/calendar/range?start=${encodeURIComponent(hmIso(a))}&end=${encodeURIComponent(hmIso(b))}&lang=${state.uiLang === 'en' ? 'en' : 'ru'}`)
    .then(r => (r.ok ? r.json() : null)).catch(() => null);
  return w && { ...w, monday: calKey(a) };
}

// The week before the one of «Нагрузка недели», for its comparison: the same request one week back. The answer
// keeps the Monday it was asked for, so a week moved meanwhile is not compared with the wrong one
async function dbLoadPrevWeek(b = dbMonday()) {
  const a = new Date(b);
  a.setDate(b.getDate() - 7);
  const w = await fetch(`/api/calendar/range?start=${encodeURIComponent(hmIso(a))}&end=${encodeURIComponent(hmIso(b))}&lang=${state.uiLang === 'en' ? 'en' : 'ru'}`)
    .then(r => (r.ok ? r.json() : null)).catch(() => null);
  return w && { ...w, monday: calKey(a) };
}

// --- Drawing ---
// The widgets rise one after another as Главная opens. The fresh numbers come a moment later and draw the
// widgets again: each new one goes on from where its former one was in the rise, it does not start it over
// (reported by the user: every card jerked twice, a strobe)
// The whole rise takes the same time on every section (asked by the user: «Обзор» felt slow): a step of
// min(35 ms, 180 ms / the widgets in view); those out of view are there at once
function dbWaveDelays(grid) {
  const gone = performance.now() - (DB.waveAt || 0);
  dbWave(grid.querySelectorAll(':scope > .db-w'), gone);
}

function dbWave(els, gone) {
  const h = window.innerHeight;
  const seen = [...els].filter(el => { const r = el.getBoundingClientRect(); return r.bottom > 0 && r.top < h; });
  const step = Math.min(35, 180 / Math.max(1, seen.length));
  els.forEach(el => {
    const k = seen.indexOf(el);
    el.style.animationDelay = k < 0 ? '-1000ms' : `${Math.round(k * step - gone)}ms`;
  });
}

function renderDashboard() {
  const grid = document.getElementById('db-grid');
  if (!grid) return;
  if (DB.drag && DB.drag.on) return;  // a widget is being dragged: the drop draws the grid (with what came meanwhile)
  const p = dbPrefs();
  dbRenderHead();
  grid.classList.toggle('db-editing', DB.edit);
  grid.innerHTML = p.layout.map((w, i) => {
    const def = DB_WIDGETS[w.id], size = dbSize(w);
    const sizes = DB.edit ? `<span class="db-sizes">${def.sizes.map(s => `<button data-click="setDashSize" data-click-args='[${i}, "${s}"]' class="${s === size ? 'on' : ''}" title="${escapeHtml(t(`dbSize_${s}`))}">${s}</button>`).join('')}</span>` : '';
    const tools = DB.edit ? `<span class="db-tools"><span class="db-grip" title="${escapeHtml(t('dbDragTip'))}">⋮⋮</span>`
      + `<button data-click="removeDashWidget" data-click-args='[${i}]' class="db-x" title="${escapeHtml(t('dbRemove'))}" aria-label="${escapeHtml(t('dbRemove'))}">✕</button></span>` : '';
    return `<section class="db-w db-w-${w.id}${w.id === 'summary' ? ' db-summary' : ''}" style="grid-column:span ${DB_SIZES[size]}" data-i="${i}" data-wid="${w.id}">`
      + `<h3 class="db-h">${dbHeadHtml(w.id, size)}</h3>`
      + `<div class="db-c">${dbWidgetHtml(w.id, size)}</div>${tools}${sizes}</section>`;
  }).join('') || `<div class="db-empty">${escapeHtml(t('dbEmpty'))}</div>`;
  if (grid.classList.contains('db-wave')) dbWaveDelays(grid);
  renderDashDrawer();
}

// The head of a widget: its title, then its tools (the look of a chart, its own period, «Показатели»), then its link
function dbHeadHtml(id, size) {
  const tools = [];
  if (!DB.edit) {
    if (['time', 'load'].includes(id) || (id === 'worked' && size !== 'S')) tools.push(dbChartSwitch(id, DB_CHART_KINDS, 'col'));
    if (id === 'apps' && DB.apps && DB.apps.enabled) tools.push(dbChartSwitch('apps', DB_APPS_KINDS, 'list'));
    if (id === 'apps') tools.push(dbWPeriodSwitch('apps'));
    if (id === 'kpis') {
      tools.push(dbCompareSwitch());
      tools.push(`<button class="tk-btn tk-btn-sm db-kc-btn${DB.kpiCfg ? ' on' : ''}" data-click="dbKpiPanel" aria-expanded="${DB.kpiCfg}" title="${escapeHtml(t('kpiCfgTip'))}">`
        + '<svg aria-hidden="true" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/></svg>'
        + `<span>${escapeHtml(t('kpiCfg'))}</span></button>`);
    }
  }
  return `<span class="db-h-t">${escapeHtml(t(DB_WIDGETS[id].title))}</span>`
    + (tools.length ? `<span class="db-h-tools">${tools.join('')}</span>` : '') + dbLink(id);
}

// One widget drawn again where it is (a look or a period changed): the page does not move
function dbRedrawWidget(id) {
  dbPrefs().layout.forEach((w, i) => {
    if (w.id !== id) return;
    const el = document.querySelector(`#db-grid .db-w[data-i="${i}"]`);
    if (!el) return;
    el.querySelector('.db-h').innerHTML = dbHeadHtml(id, dbSize(w));
    el.querySelector('.db-c').innerHTML = dbWidgetHtml(id, dbSize(w));
  });
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
  if (typeof tdRender === 'function') tdRender();
  loadMeetingsList().catch(() => {});
}

async function dashDismissUntx() {
  const ids = (DB.untx || []).map(m => m.id);
  await fetch('/api/untranscribed/dismiss', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids }) }).catch(() => null);
  DB.untx = [];
  if (typeof tdRender === 'function') tdRender();
}

function dbLink(id) {
  const link = (fn, args, key) => `<button class="db-more" data-click="${fn}" data-click-args='${JSON.stringify(args)}'>${escapeHtml(t(key))}</button>`;
  if (id === 'mytasks') return link('dbOpenDetail', ['tasks'], 'dbAllLink');
  if (id === 'waiting') return link('dbOpenDetail', ['waiting'], 'dbAllLink');
  if (id === 'decisions') return link('dbOpenDetail', ['decisions'], 'dbAllLink');
  if (id === 'time') return link('dbOpenDetail', ['meetings'], 'dbAllLink');
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
    // the dates of the period under the name (the switch beside says which period); «Аналитика периода» until they come
    sub.textContent = d ? `${fmt(d.start)} – ${fmt(calKey(last))}` : t('dbOverviewSub');
    sub.title = d ? t(`dbPeriodName_${p.period}`) : '';
  }
  // How far the period is (asked by the user: «сколько дней прошло»): a pill of the head that fills as the period
  // goes, as the pills of «Сегодня»; calendar or working days as chosen in «Настроить»
  const prog = document.getElementById('db-progress');
  if (prog) prog.innerHTML = d ? dbProgressPill(d) : '';
  dbRenderNav();
  document.getElementById('db-periods').innerHTML = DB_PERIODS.map(k =>
    `<button role="radio" aria-checked="${p.period === k}" class="tk-seg-btn${p.period === k ? ' tk-on' : ''}" data-click="setDashPeriod" data-click-args='["${k}"]'>${escapeHtml(t(`dbPeriod_${k}`))}</button>`).join('');
  const f = p.feature ? featureById(p.feature) : null;
  const fb = document.getElementById('db-feature-btn');
  // a filter by a feature says so in its button and gets its own ✕ (asked by the user: the filter went unnoticed)
  fb.innerHTML = `<span class="lt-ell">${escapeHtml(f ? t('dbFeatureOn').replace('{name}', () => f.name) : t('dbAllFeatures'))}</span>${VX_CARET}`;
  if (f) fb.title = t('dbFeatureOn').replace('{name}', () => f.name); else fb.removeAttribute('title');  // its name when cut
  fb.classList.toggle('lt-btn-on', !!f);
  fb.classList.toggle('db-feature-on', !!f);
  document.getElementById('db-feature-clear').classList.toggle('hidden', !f);
  document.getElementById('db-edit-label').textContent = t(DB.edit ? 'dbDone' : 'dbEdit');
  document.getElementById('db-edit-btn').setAttribute('aria-pressed', DB.edit ? 'true' : 'false');
}

// The pill «Прошло 4 дня из 7»: calendar days, or working days (Monday to Friday) as the user chose in «Настроить»
// (asked by the user); a public holiday of the country chosen in the settings is no working day
function dbProgressPill(d) {
  const work = dbPrefs().days === 'work', hol = d.holidays || {};
  const a = new Date(`${d.start}T00:00:00`), b = new Date(`${d.end}T00:00:00`), now = new Date();
  const days = [];
  for (let x = new Date(a); x < b; x.setDate(x.getDate() + 1)) if (!work || ((x.getDay() + 6) % 7 < 5 && !hol[calKey(x)])) days.push(new Date(x));
  const all = days.length;
  const done = days.filter(x => x.getTime() + 864e5 <= now.getTime()).length;  // the days over
  const today = days.find(x => x <= now && now < new Date(x.getTime() + 864e5));
  const part = all ? Math.max(0, Math.min(1, (done + (today ? (now - today) / 864e5 : 0)) / all)) : 0;
  const label = t(work ? 'dbPeriodProgressWork' : 'dbPeriodProgress').replace('{done}', () => plural(done, t(work ? 'dbWorkDayForms' : 'dbDayForms'))).replace('{all}', () => all);
  return tdPill(label, part, `${label} · ${t(work ? 'dbDaysWork' : 'dbDaysCal')}`);
}

// «Настроить»: which days the pill of the period counts
function setDashDays(days) {
  dbSave({ days: days === 'work' ? 'work' : 'cal' });
  dbRenderHead();
  renderDashDrawer();
}

// One way to write hours (and other numbers) in all the widgets: one decimal place at most, the decimal comma in
// Russian and the point in English (asked by the user: «0.1 ч» beside «0 ч» and «0.05 ч» for one week)
function dbNum(n) {
  const v = Math.round((Number(n) || 0) * 10) / 10 || 0;  // «|| 0»: no «-0»
  return v.toLocaleString(state.uiLang === 'en' ? 'en-US' : 'ru-RU', { maximumFractionDigits: 1, useGrouping: false });
}

// Hours as every widget writes them: «1,5 ч»; less than 0,1 h in minutes («6 мин»), not «0,1 ч» beside «0 ч»
// (found in the audit). unit false: the number alone, as a chart's label («1,5»; minutes keep «мин»)
function dbHours(h, unit = true) {
  const v = Number(h) || 0;
  if (v > 0 && v < 0.1) return `${Math.max(1, Math.round(v * 60))} ${t('dbMinShort')}`;
  return unit ? `${dbNum(v)} ${t('dbHoursShort')}` : dbNum(v);
}

// --- The day's time: the next meeting, the free windows, the load of the week (asked by the user) ---
// They read the calendar of today (home.events, static/js/home.js) and of the week (DB.week): no request
const DB_LOCAL_WIDGETS = ['load', 'worked', 'apps', 'people', 'sysload'];
const DB_TIME_WIDGETS = ['load'];  // redrawn as the time goes (dbTickNow); «Рабочий день» after its numbers come

// The meeting going on or the next one of today (not an all-day one); null when there is none left
// A meeting begun counts as going on only while a recording runs (asked by the user: a block over the whole
// night in the calendar showed «идёт встреча» on the dashboard): otherwise the next one ahead is shown. A block
// of six hours or more (a night, a day off, a reminder) is never a meeting to count down to
const DB_BLOCK_MS = 6 * 3600e3;  // a calendar block this long or longer is no meeting

function dbNextMeeting() {
  const now = Date.now(), rec = typeof isRecording === 'function' && isRecording();
  const list = (typeof home !== 'undefined' ? home.events : [])
    .filter(e => !e.all_day && e.e.getTime() > now && e.e - e.s < DB_BLOCK_MS && !hmIsIgnored(e) && (e.s.getTime() > now || rec))
    .sort((x, y) => x.s - y.s);
  return list[0] || null;
}

// «через 12 мин», «через 1 ч 05 мин»
function dbIn(ms) {
  const m = Math.max(1, Math.round(ms / 60e3));
  return t('dbInMin').replace('{t}', () => dbHm(m * 60));
}

// «Перед встречей»: the next meeting, when, who, and what is open from the last time (series.before_meeting)
function dbPrepHtml(size) {
  if (typeof home === 'undefined' || !home.calConfigured) return `<div class="db-note">${escapeHtml(t('hmCalOff'))}</div>`;
  const e = dbNextMeeting();
  if (!e) return `<div class="db-note">${escapeHtml(t('dbNoMoreMeetings'))}</div>`;
  const now = Date.now(), pad = n => String(n).padStart(2, '0');
  const live = e.s.getTime() <= now;
  const when = live ? t('dbLiveLeft').replace('{t}', () => dbHm((e.e.getTime() - now) / 1000)) : dbIn(e.s.getTime() - now);
  const soon = !live && e.s.getTime() - now <= 5 * 60e3;
  const people = (e.attendees || []).map(a => String(a).replace(/@.*$/, '')).filter(Boolean);
  const bf = e.before;
  const tasks = bf && (bf.tasks || []).length
    ? `<div class="db-prep-sec">${escapeHtml(t('dbPrepOpen').replace('{n}', () => bf.open_tasks))}</div>`
      + bf.tasks.slice(0, size === 'S' ? 2 : 5).map(x => `<div class="db-prep-task"><span class="db-prep-what">${escapeHtml(x.what)}</span>`
        + `<span class="db-prep-who">${escapeHtml([x.who, x.to_whom ? `→ ${x.to_whom}` : ''].filter(Boolean).join(' '))}</span></div>`).join('')
    : '';
  const last = bf
    ? `<button class="db-more" data-click="openMeeting" data-click-args='[${Number(bf.last.id)}]'>${escapeHtml(t('dbPrepLast').replace('{title}', () => bf.last.title).replace('{date}', () => dbAgo(bf.last.date, DB.data ? DB.data.today : bf.last.date)))}</button>`
    : `<span class="db-note">${escapeHtml(t('dbPrepFirst'))}</span>`;
  const brief = bf
    ? `<button class="tk-btn tk-btn-sm" data-click="openBriefFor" data-click-args='${escapeHtml(JSON.stringify(bf.series_id ? ['series', bf.series_id] : ['person', bf.person]))}'>${escapeHtml(t('dbPrepBrief'))}</button>` : '';
  return `<div class="db-prep${soon ? ' soon' : ''}${live ? ' live' : ''}">`
    + `<div class="db-prep-when"><b>${escapeHtml(when)}</b><span>${pad(e.s.getHours())}:${pad(e.s.getMinutes())}–${pad(e.e.getHours())}:${pad(e.e.getMinutes())}</span></div>`
    + `<div class="db-prep-title">${escapeHtml(e.title || t('hmUntitled'))}</div>`
    + `<div class="db-prep-people">${escapeHtml(people.length ? people.slice(0, 6).join(', ') + (people.length > 6 ? ` +${people.length - 6}` : '') : (e.online ? t('hmOnline') : (e.location || t('hmInPerson'))))}</div>`
    + tasks + `<div class="db-prep-foot">${last}<span class="flex-1"></span>${brief}</div></div>`;
}

// «Срочные задачи»: the tasks due today or overdue, mine and those promised to me, overdue first
function dbDueHtml(d, size) {
  // the same note and button as «Ожидаю от других» and «Мои задачи» (here it was a link in the text: audit)
  if (d.needs_me) return `<div class="db-note">${escapeHtml(t('dbNeedsMe'))}</div><button class="tk-btn tk-btn-sm" data-click="hmSetMyName">${escapeHtml(t('dbSetMe'))}</button>`;
  const today = d.today;
  const hot = x => x.due_date && x.due_date <= today;
  const list = [...(d.tasks || []).filter(hot).map(x => ({ ...x, mine: true })), ...(d.waiting || []).filter(hot).map(x => ({ ...x, mine: false }))]
    .sort((x, y) => (x.due_date < y.due_date ? -1 : x.due_date > y.due_date ? 1 : 0));
  if (!list.length) return `<div class="db-note db-ok">${escapeHtml(t('dbDueNone'))}</div>`;
  const n = size === 'S' ? 3 : size === 'W' ? 10 : 6;
  return list.slice(0, n).map(x => `<div class="db-task db-task-due">`
    + (x.mine ? `<button class="db-ck" data-click="dashTaskDone" data-click-args='[${x.id}]' title="${escapeHtml(t('dbMarkDone'))}" aria-label="${escapeHtml(t('dbMarkDone'))}"></button>` : '<span class="db-ck-gap"></span>')
    + `<button class="db-tt" data-click="dashOpenTask" data-click-args='[${x.id}, ${Number(x.meeting_id) || 0}]'>${escapeHtml(x.what)}`
    + `<small>${escapeHtml(x.mine ? t('dbDueMine') : t('dbDueFrom').replace('{who}', () => x.who || '—'))}</small></button>`
    + `${dbDue(x, today)}</div>`).join('') + (list.length > n ? `<div class="db-note">${escapeHtml(t('dbMoreN').replace('{n}', () => list.length - n))}</div>` : '');
}

// The busy times of a list of [start, end] (ms), merged
function dbMerge(spans) {
  const out = [];
  for (const [a, b] of spans.filter(([a, b]) => b > a).sort((x, y) => x[0] - y[0])) {
    const last = out[out.length - 1];
    if (last && a <= last[1]) last[1] = Math.max(last[1], b); else out.push([a, b]);
  }
  return out;
}

// «Свободное время»: the windows of 30 minutes or more left in the working day between the meetings
function dbFreeHtml() {
  if (typeof home === 'undefined' || !home.calConfigured) return `<div class="db-note">${escapeHtml(t('hmCalOff'))}</div>`;
  // a public holiday (Settings → Календарь → Праздники) is no working day
  const hol = ((DB.week && DB.week.holidays) || {})[calKey(new Date())];
  if (hol) return `<div class="db-note">${escapeHtml(t('dbHolidayToday').replace('{name}', () => hol))}</div>`;
  const d = hmDay(), now = Date.now();
  const from = Math.max(now, d.from.getTime()), to = d.to.getTime();
  if (from >= to) return `<div class="db-note">${escapeHtml(t('dbDayOver'))}</div>`;
  // a block of six hours or more (a night, a day off) is no meeting (reported by the user: «The End» 17:00–08:30)
  const busy = dbMerge(home.events.filter(e => !e.all_day && e.e - e.s < DB_BLOCK_MS && !hmIsIgnored(e)).map(e => [Math.max(e.s.getTime(), from), Math.min(e.e.getTime(), to)]));
  const gaps = [];
  let at = from;
  for (const [a, b] of busy) { if (a - at >= 30 * 60e3) gaps.push([at, a]); at = Math.max(at, b); }
  if (to - at >= 30 * 60e3) gaps.push([at, to]);
  if (!gaps.length) return `<div class="db-note">${escapeHtml(t('dbNoFree'))}</div>`;
  const pad = n => String(n).padStart(2, '0'), clock = ms => { const x = new Date(ms); return `${pad(x.getHours())}:${pad(x.getMinutes())}`; };
  const total = gaps.reduce((sum, [a, b]) => sum + (b - a), 0);
  return `<div class="db-free-sum">${escapeHtml(t('dbFreeSum').replace('{t}', () => dbHm(total / 1000)))}</div>`
    + gaps.map(([a, b]) => `<div class="db-free-row${a <= now + 60e3 ? ' now' : ''}"><span class="db-free-t">${clock(a)}–${clock(b)}</span>`
      + `<span class="db-free-len">${escapeHtml(dbHm((b - a) / 1000))}</span></div>`).join('');
}
// --- Charts: the same figures as columns, bars with the norm, a ring or a line; the look is chosen in the widget's
// head and kept per widget (asked by the user) ---
const DB_ICON = p => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${p}</svg>`;
const DB_CHART_KINDS = [
  ['col', 'dbChCol', '<path d="M5 20V11M10 20V5M15 20v-7M20 20v-4"/>'],
  ['bar', 'dbChBar', '<path d="M4 5h9M4 10h15M4 15h6M4 20h12"/>'],
  ['ring', 'dbChRing', '<path d="M12 3.5a8.5 8.5 0 108.5 8.5H12z"/><path d="M15 3.8A8.5 8.5 0 0120.2 9H15z"/>'],
  ['line', 'dbChLine', '<path d="M4 17l5-6 4 3 7-8"/>'],
];
const DB_APPS_KINDS = [
  ['list', 'dbChList', '<path d="M4 6h3M10 6h10M4 12h3M10 12h10M4 18h3M10 18h10"/>'],
  ['ring', 'dbChRing', '<path d="M12 3.5a8.5 8.5 0 108.5 8.5H12z"/><path d="M15 3.8A8.5 8.5 0 0120.2 9H15z"/>'],
  ['col', 'dbChCol', '<path d="M5 20V11M10 20V5M15 20v-7M20 20v-4"/>'],
];
// One hue per part, told apart at a glance, and none of the colours of a state (CLAUDE.md): blue, teal, violet,
// pink-lilac, brown, blue-grey; grey is «Другие». A part above the norm keeps its hue and gets a mark of its own
const DB_SLICE = ['#4C7FD9', '#2EB6A6', '#9B6BDF', '#D46FC4', '#A0785A', '#6B7FA8'];
const DB_OTHER = '#8A94A6';

function dbChartKind(id, kinds = DB_CHART_KINDS, def = 'col') {
  const k = (dbPrefs().charts || {})[id];
  return kinds.some(x => x[0] === k) ? k : def;
}

function dbChartSwitch(id, kinds, def) {
  const cur = dbChartKind(id, kinds, def);
  return `<span class="db-chsw" role="radiogroup" aria-label="${escapeHtml(t('dbChartKind'))}">${kinds.map(([k, key, p]) =>
    `<button role="radio" aria-checked="${cur === k}" class="${cur === k ? 'on' : ''}" data-click="setDashChart" data-click-args='["${id}", "${k}"]' title="${escapeHtml(t(key))}" aria-label="${escapeHtml(t(key))}">${DB_ICON(p)}</button>`).join('')}</span>`;
}

function setDashChart(id, kind) {
  dbSave({ charts: { ...(dbPrefs().charts || {}), [id]: kind } });
  dbRedrawWidget(id);
}

// «Статистика»: compared with the period before or with the same days a year earlier
function dbCompareSwitch() {
  const cur = dbPrefs().compare;
  return `<span class="db-wp" role="radiogroup" aria-label="${escapeHtml(t('dbCompare'))}" title="${escapeHtml(t('dbCompare'))}">${DB_COMPARE.map(k =>
    `<button role="radio" aria-checked="${cur === k}" class="${cur === k ? 'on' : ''}" data-click="setDashCompare" data-click-args='["${k}"]' title="${escapeHtml(t(`dbCmpTip_${k}`))}">${escapeHtml(t(`dbCmp_${k}`))}</button>`).join('')}</span>`;
}

function setDashCompare(k) {
  if (!DB_COMPARE.includes(k) || dbPrefs().compare === k) return;
  dbSave({ compare: k });
  dbRedrawWidget('kpis');
  loadDashboard({ keepWeek: true });
}

// День · Неделя · Месяц · Год of a widget
function dbWPeriodSwitch(id) {
  const cur = dbWPeriod(id);
  return `<span class="db-wp" role="radiogroup" aria-label="${escapeHtml(t('dbPeriod'))}">${DB_WPERIODS.map(k =>
    `<button role="radio" aria-checked="${cur === k}" class="${cur === k ? 'on' : ''}" data-click="setDashWPeriod" data-click-args='["${id}", "${k}"]'>${escapeHtml(t(`dbWp_${k}`))}</button>`).join('')}</span>`;
}

async function setDashWPeriod(id, p) {
  dbSave({ wperiod: { ...(dbPrefs().wperiod || {}), [id]: p } });
  dbRedrawWidget(id);
  await (id === 'apps' ? dbLoadApps() : dbLoadPeople());
  if (state.appView === 'dashboard') dbRedrawWidget(id);
}

// rows: [{ label, value (hours), plan (the hours of it still ahead), prev (the hours of the same day a week before,
// or null), dx (the difference to it, «+1,5», or ''), tip, cls }]; norm: hours of a day, or 0.
// The hours ahead are a plan: a neutral grey part that continues the day's mark (the hours passed keep the day's
// colour), the figure of a day all ahead grey. A plan above the norm stays grey and gets an orange frame over the
// part above the norm (CLAUDE.md: a part above the norm keeps its hue and gets a mark of its own). The week before:
// a thin light tick at its hours of the same day, over the mark, and the difference in a column of its own.
// The line: its fill and the line in an SVG that stretches with the card, the dots, figures and days in HTML at
// percent places, so the text never stretches
function dbChartHtml(id, rows, norm) {
  const kind = dbChartKind(id);
  const max = Math.max(norm || 0, ...rows.map(r => Math.max(r.value, r.prev || 0))) || 1;
  const h1 = v => dbHours(v, false), hs = t('dbHoursShort');
  const hu = v => dbHours(v);
  const pl = r => (r.plan || 0) > 1e-4, done = r => Math.max(0, r.value - (r.plan || 0));
  const allPl = r => pl(r) && done(r) < 1e-4;
  const overFact = r => norm && done(r) > norm, over = r => norm && r.value > norm;
  const hasPrev = rows.some(r => r.prev != null);
  // the classes of a mark: «over» above the norm, «plan» with hours ahead
  const mk = r => [over(r) ? 'over' : '', pl(r) ? 'plan' : ''].filter(Boolean).join(' ');
  // a mark with hours ahead is grey as a whole; the hours already passed are in the day's colour at its start,
  // and the planned part above the norm is framed orange
  const doneIn = (r, dim, extra = '') => {
    if (!pl(r)) return '';
    const from = (dim === 'width' ? 'left' : 'bottom'), pc = v => (v / r.value * 100).toFixed(1);
    const top = Math.max(norm || 0, done(r));
    return (allPl(r) ? '' : `<s class="dbc-done${overFact(r) ? ' over' : ''}" style="${dim}:${pc(done(r))}%${extra}"></s>`)
      + (over(r) && r.value - top > 1e-4 ? `<s class="dbc-ovp" style="${from}:${pc(top)}%;${dim}:${pc(r.value - top)}%"></s>` : '');
  };
  const prevAt = r => (r.prev ? (r.prev / max * 100).toFixed(1) : '');
  const dx = (r, tag = 'span', style = '') => (hasPrev ? `<${tag} class="dbc-dx"${style}>${escapeHtml(r.dx || '')}</${tag}>` : '');
  if (kind === 'bar') {
    return `<div class="dbc-bars${hasPrev ? ' dx' : ''}">${rows.map(r => `<div class="dbc-hb ${r.cls || ''}" title="${escapeHtml(r.tip)}"><span class="dbc-hb-d">${escapeHtml(r.label)}</span>`
      + `<span class="dbc-hb-t"><b class="${mk(r)}" style="width:${(r.value / max * 100).toFixed(1)}%">${doneIn(r, 'width')}</b>${norm ? `<i style="left:${(norm / max * 100).toFixed(1)}%"></i>` : ''}`
      + `${r.prev ? `<s class="dbc-prev" style="left:${prevAt(r)}%"></s>` : ''}</span>`
      + `<span class="dbc-hb-v${allPl(r) ? ' pl' : ''}">${r.value ? hu(r.value) : '—'}</span>${dx(r)}</div>`).join('')}</div>`;
  }
  if (kind === 'ring') {
    const xs = rows.filter(r => r.value).map((r, i) => ({ ...r, c: DB_SLICE[i % DB_SLICE.length] }));
    if (!xs.length) return `<div class="db-note">${escapeHtml(t('dbNoMeetingsYet'))}</div>`;
    const sum = xs.reduce((s, r) => s + r.value, 0), top = Math.max(norm || 0, ...xs.map(r => Math.max(r.value, r.prev || 0)));
    const dash = (from, len) => `stroke-dasharray="${Math.max(0.1, len).toFixed(2)} ${(100 - Math.max(0.1, len)).toFixed(2)}" stroke-dashoffset="${(25 - from).toFixed(2)}"`;
    let at = 0;
    const segs = xs.map(r => {
      const len = r.value / sum * 100, d = done(r) / sum * 100, gap = 0.8;
      // the hours passed in the day's hue, those ahead grey
      const seg = (from, l, cls) => (l > 0.05 ? `<circle r="15.9155" cx="18" cy="18" fill="none" stroke="${r.c}" stroke-width="4.2"${cls ? ` class="${cls}"` : ''} ${dash(from, l)}/>` : '');
      const out = (pl(r) ? seg(at, d, '') + seg(at + d, len - d - gap, 'dbc-ring-plan') : seg(at, len - gap, ''))
        // above the norm: the day keeps its hue, a thin amber arc outside marks it (as planned when only the plan is over)
        + (over(r) ? `<circle r="19.1" cx="18" cy="18" fill="none" class="dbc-ring-over${overFact(r) ? '' : ' plan'}" stroke-width="1.2" pathLength="100" ${dash(at, len - gap)}/>` : '');
      at += len;
      return out;
    }).join('');
    return `<div class="dbc-ring"><svg viewBox="${norm ? '-1.6 -1.6 39.2 39.2' : '0 0 36 36'}" class="dbc-ring-svg" role="img" aria-label="${escapeHtml(hu(sum))}">${segs}`
      // less than 0,1 h: the minutes and «мин» under them
      + `<text x="18" y="18" text-anchor="middle" class="dbc-ring-n">${sum < 0.1 ? Math.max(1, Math.round(sum * 60)) : h1(sum)}</text><text x="18" y="22.6" text-anchor="middle" class="dbc-ring-l">${escapeHtml(sum < 0.1 ? t('dbMinShort') : hs)}</text></svg>`
      + `<div class="dbc-lg${hasPrev ? ' dx' : ''}">${xs.map(r => `<div title="${escapeHtml(r.tip)}"><i class="${allPl(r) ? 'plan' : ''}" style="${allPl(r) ? '' : `background:${r.c}`}"></i><span class="dbc-lg-d">${escapeHtml(r.label)}</span>`
        + `<b class="dbc-lg-bar"><u class="${mk(r)}" style="width:${(r.value / top * 100).toFixed(1)}%${pl(r) ? '' : `;background:${r.c}`}">${doneIn(r, 'width', `;background:${r.c}`)}</u>${norm ? `<em style="left:${(norm / top * 100).toFixed(1)}%"></em>` : ''}`
        + `${r.prev ? `<s class="dbc-prev" style="left:${(r.prev / top * 100).toFixed(1)}%"></s>` : ''}</b>`
        + `<span class="dbc-lg-h${over(r) ? ' over' : ''}${allPl(r) ? ' pl' : ''}"${over(r) ? ` title="${escapeHtml(t('dbOverNorm'))}"` : ''}>${escapeHtml(hu(r.value))}</span>`
        + `${dx(r)}<span class="dbc-lg-p">${Math.round(r.value / sum * 100)}%</span></div>`).join('')}</div></div>`;
  }
  if (kind === 'line') {
    const n = rows.length, px = i => (n > 1 ? 3 + i * 94 / (n - 1) : 50);
    const py = v => 100 - v / max * 82;
    const pt = i => `${px(i).toFixed(2)},${py(rows[i].value).toFixed(2)}`;
    // solid up to the last day with nothing ahead, dashed grey from there on through the days of the plan
    const f = rows.findIndex(pl), cut = f < 0 ? n - 1 : Math.max(0, f - 1);
    const run = (a, b) => rows.slice(a, b + 1).map((r, k) => pt(a + k)).join(' ');
    const part = (a, b, cls) => `<polygon points="${px(a).toFixed(2)},100 ${run(a, b)} ${px(b).toFixed(2)},100" class="dbc-l-area${cls}"/><polyline points="${run(a, b)}" class="dbc-l-line${cls}"/>`;
    // the week before: a faint grey line under the week's own
    const prevPts = rows.map((r, i) => [px(i), py(r.prev || 0)].map(v => v.toFixed(2)).join(',')).join(' ');
    const prev = hasPrev ? `<polyline points="${prevPts}" class="dbc-l-prev"/>` : '';
    return `<div class="dbc-line"><div class="dbc-plot"><svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">`
      + (norm ? `<line x1="0" x2="100" y1="${py(norm).toFixed(2)}" y2="${py(norm).toFixed(2)}" class="dbc-l-norm"/>` : '')
      + prev + (f === 0 ? '' : part(0, cut, '')) + (f < 0 ? '' : part(cut, n - 1, ' plan')) + '</svg>'
      + rows.map((r, i) => `<i class="${mk(r)}" style="left:${px(i).toFixed(2)}%;top:${py(r.value).toFixed(2)}%" title="${escapeHtml(r.tip)}"></i>`
        + (r.value ? `<span class="dbc-l-v${allPl(r) ? ' pl' : ''}" style="left:${px(i).toFixed(2)}%;top:${py(r.value).toFixed(2)}%">${h1(r.value)}</span>` : '')).join('')
      + `</div><div class="dbc-days">${rows.map((r, i) => `<span class="${r.cls || ''}" style="left:${px(i).toFixed(2)}%">${escapeHtml(r.label)}</span>`).join('')}</div>`
      + (hasPrev ? `<div class="dbc-days dbc-dxs">${rows.map((r, i) => dx(r, 'span', ` style="left:${px(i).toFixed(2)}%"`)).join('')}</div>` : '') + '</div>';
  }
  return `<div class="dbc-cols">${norm ? `<i class="dbc-norm" style="bottom:${(norm / max * 100).toFixed(1)}%"></i>` : ''}${rows.map(r => {
    const pct = r.value / max * 100;
    return `<div class="dbc-col ${r.cls || ''}" title="${escapeHtml(r.tip)}"><i class="${mk(r)}" style="height:${r.value ? Math.max(2, pct).toFixed(1) : 0}%">${doneIn(r, 'height')}</i>`
      + (r.prev ? `<s class="dbc-prev" style="bottom:${prevAt(r)}%"></s>` : '')
      + (r.value ? `<span class="${allPl(r) ? 'pl' : ''}" style="bottom:calc(${pct.toFixed(1)}% + 3px)">${h1(r.value)}</span>` : '') + '</div>';
  }).join('')}</div><div class="dbc-axis">${rows.map(r => `<span class="${r.cls || ''}">${escapeHtml(r.label)}</span>`).join('')}</div>`
    + (hasPrev ? `<div class="dbc-axis dbc-dxs">${rows.map(r => dx(r)).join('')}</div>` : '');
}

// The hours of meetings of a day (YYYY-MM-DD) in a week's answer of /api/calendar/range, and of them those passed
// by `now`: the calendar's meetings (not those of a whole day, not those ignored, not a block of DB_BLOCK_MS or
// longer — a night or a day off is not hours of meetings) and the recordings (those made during a meeting too),
// overlaps counted once. The same rule as «Статистика» (app/dashboard.busy_days)
function dbDayHours(w, k, now) {
  const rec = r => [new Date(r.at).getTime(), new Date(r.at).getTime() + (r.duration || 0) * 1000];
  const spans = [...(w.events || []).filter(e => !e.all_day && !hmIsIgnored(e)).map(e => [new Date(e.start).getTime(), new Date(e.end || e.start).getTime()])
      .filter(([s, e]) => e - s < DB_BLOCK_MS),
    ...(w.events || []).filter(e => e.recording && e.recording.at).map(e => rec(e.recording)),
    ...(w.recordings || []).map(rec)]
    .filter(([s]) => calKey(new Date(s)) === k);
  const busy = dbMerge(spans);
  return { hours: busy.reduce((sum, [s, e]) => sum + (e - s), 0) / 3600e3,
    // what of each meeting lies before now has passed; the rest is the plan
    done: busy.reduce((sum, [s, e]) => sum + Math.max(0, Math.min(e, now) - s), 0) / 3600e3 };
}

// «Нагрузка недели»: the hours of meetings of each day of the week against the user's norm (a click on
// the norm changes it: 2–6 h). The calendar's meetings, or the recordings without one. The meetings still ahead
// (the days to come, the rest of today) are a plan, drawn grey and counted apart in the head (reported by
// the user: the meetings ahead read as hours already spent). The week before is a tick at each day and the
// difference beside its hours (the whole day, the plan too); grey, as more meetings are neither better nor worse
function dbLoadHtml() {
  const { week: w, prev: pw0, monday: a, past } = dbWeekData();
  if (!w) return `<div class="db-note">${escapeHtml(t(DB.loading || past ? 'dbLoading' : 'dbNoData'))}</div>`;
  const lang = state.uiLang === 'en' ? 'en-US' : 'ru-RU', now = Date.now(), today = calKey(new Date(now));
  const norm = dbPrefs().norm;
  const hu = v => dbHours(v);
  const ahead = h => t('dbLoadAhead').replace('{h}', () => hu(h));
  const a0 = new Date(a); a0.setDate(a.getDate() - 7);
  const pw = pw0 && pw0.monday === calKey(a0) ? pw0 : null;
  const rows = [];
  for (let i = 0; i < 7; i++) {
    const x = new Date(a); x.setDate(a.getDate() + i);
    const x0 = new Date(a0); x0.setDate(a0.getDate() + i);
    const k = calKey(x), { hours, done } = dbDayHours(w, k, now);
    const plan = Math.max(0, hours - done);
    const prev = pw ? dbDayHours(pw, calKey(x0), now).hours : null;
    const hol = (w.holidays || {})[k] || '';
    if (i < 5 || hours || prev) {
      const d = prev == null ? 0 : Math.round(hours * 10) / 10 - Math.round(prev * 10) / 10;
      const dx = Math.abs(d) < 0.05 ? '' : `${d > 0 ? '+' : '−'}${dbNum(Math.abs(d))}`;
      const tip = (plan && !done ? `${hu(hours)} ${t('dbLoadPlanned')}` : `${hu(done)}${plan ? ` · ${ahead(plan)}` : ''}`)
        + (prev == null ? '' : ` · ${t('dbLoadPrevTip').replace('{h}', () => hu(prev))}${dx ? ` (${dx})` : ''}`);
      rows.push({ label: x.toLocaleDateString(lang, { weekday: 'short' }), value: hours, plan, prev, dx,
        cls: `${k === today ? 'today' : ''}${k < today ? ' past' : ''}${k > today ? ' ahead' : ''}${hol ? ' hol' : ''}`,
        tip: `${x.toLocaleDateString(lang, { weekday: 'short', day: 'numeric', month: 'short' })}: ${tip}${hol ? ` · ${hol}` : ''}` });
    }
  }
  const sum = rows.reduce((s, d) => s + d.value - d.plan, 0), left = rows.reduce((s, d) => s + d.plan, 0);
  // above the norm by the hours passed, or only by the plan
  const byFact = rows.filter(d => d.value - d.plan > norm), byPlan = rows.filter(d => d.value > norm && d.value - d.plan <= norm);
  const days = l => l.map(d => d.label).join(', ');
  const note = byFact.length
    ? t('dbLoadOver').replace('{days}', () => days(byFact)) + (byPlan.length ? `; ${t('dbLoadOverPlan').replace('{days}', () => days(byPlan))}` : '')
    : (byPlan.length ? t('dbLoadOverPlanOnly').replace('{days}', () => days(byPlan)) : '');
  const head = t('dbLoadSum').replace('{h}', () => hu(sum)) + (left >= 0.05 ? ` · ${ahead(left)}` : '');
  // the key under the chart: its marks drawn as in the look chosen
  // a past week has nothing ahead: no «план» in its key
  const key = [['done', 'dbLoadKeyDone'], ...(past ? [] : [['plan', 'dbLoadKeyPlan']]), ...(pw ? [['prev', 'dbLoadKeyPrev']] : [])]
    .map(([c, k]) => `<span><i class="k-${c}"></i>${escapeHtml(t(k))}</span>`).join('');
  return (past ? `<div class="db-wk-sub db-week-name">${escapeHtml(dbWeekName(a))}</div>` : '') + `<div class="db-load-head"><span class="db-load-sum">${escapeHtml(head)}</span>`
    + `<button class="db-more" data-click="dbCycleNorm" title="${escapeHtml(t('dbNormTip'))}">${escapeHtml(t('dbNorm').replace('{h}', () => norm))}</button></div>`
    + dbChartHtml('load', rows, norm)
    + `<div class="dbc-key dbc-key-${dbChartKind('load')}">${key}</div>`
    + (note ? `<div class="db-note db-load-over">${escapeHtml(note)}</div>` : '');
}

// «Рабочий день»: the hours worked today against the norm (the reminder's hours), when it began, the breaks,
// and the days of the week (app/worktime.py: the minutes this computer was in use)
function dbWorkedHtml(size) {
  const { work: w, monday: a, past } = dbWeekData();
  if (!w) return `<div class="db-note">${escapeHtml(t(DB.loading || past ? 'dbLoading' : 'dbNoData'))}</div>`;
  if (!w.supported) return `<div class="db-note">${escapeHtml(t('dbWorkedNoSupport'))}</div>`;
  if (!w.enabled) return `<div class="db-note">${escapeHtml(t('dbWorkedOff'))} <button class="db-more" data-click="openWorkSettings">${escapeHtml(t('newsOpenSettings'))}</button></div>`;
  const today = w.days[w.today] || { worked: 0, start: '', end: '', breaks: 0 };
  const norm = (w.norm || 8) * 60, pct = Math.min(100, today.worked / norm * 100);
  const over = today.worked >= norm;
  // a past week: its name and its days, no «today»
  let html = past ? `<div class="db-wk-sub db-week-name">${escapeHtml(dbWeekName(a))}</div>` : `<div class="db-wk-head"><b class="db-wk-big${over ? ' over' : ''}">${escapeHtml(dbHm(today.worked * 60))}</b>`
    + `<span class="db-wk-of">${escapeHtml(t('dbWorkedOf').replace('{h}', () => dbNum(w.norm || 8)))}</span></div>`
    + `<div class="db-wk-bar${over ? ' over' : ''}"><i style="width:${pct.toFixed(1)}%"></i></div>`
    + `<div class="db-wk-sub">${escapeHtml(today.start ? [t('dbWorkedSince').replace('{t}', () => today.start), today.breaks >= 15 ? t('dbWorkedBreaks').replace('{t}', () => dbHm(today.breaks * 60)) : ''].filter(Boolean).join(' · ') : t('dbWorkedNone'))}</div>`;
  if (size !== 'S' || past) {
    const lang = state.uiLang === 'en' ? 'en-US' : 'ru-RU';
    const rows = [];
    for (let i = 0; i < 7; i++) {
      const x = new Date(a); x.setDate(a.getDate() + i);
      const k = calKey(x), d = w.days[k];
      if (i < 5 || d) {
        rows.push({ label: x.toLocaleDateString(lang, { weekday: 'short' }), value: (d ? d.worked : 0) / 60,
          cls: `${k === w.today ? 'today' : ''}${k < w.today ? ' past' : ''}`,
          tip: `${x.toLocaleDateString(lang, { weekday: 'long', day: 'numeric', month: 'short' })}: ${dbHm((d ? d.worked : 0) * 60)}${d && d.start ? ` (${d.start}–${d.end})` : ''}` });
      }
    }
    const sum = rows.reduce((s, d) => s + d.value, 0);
    html += `<div class="db-load-head">${escapeHtml(t('dbWorkedWeek').replace('{t}', () => dbHm(sum * 3600)))}</div>` + (size !== 'S' ? dbChartHtml('worked', rows, w.norm || 8) : '');
  }
  return html;
}

// «Мои программы»: the time by program of the widget's period, with the share and the change to the same span
// before. A list, a ring or columns. Off: what it counts and what it does not, and «Включить»
function dbAppsHtml(size) {
  const r = DB.apps;
  if (!r) return `<div class="db-note">${escapeHtml(t(DB.loading ? 'dbLoading' : 'dbNoData'))}</div>`;
  if (!r.supported) return `<div class="db-note">${escapeHtml(t('dbWorkedNoSupport'))}</div>`;
  if (!r.enabled) return `<div class="db-apps-off"><div class="db-note">${escapeHtml(t('dbAppsOff'))}</div><button class="tk-btn" data-click="dbAppsTurnOn">${escapeHtml(t('dbAppsOn'))}</button></div>`;
  const list = r.apps || [];
  if (!list.length) return `<div class="db-note">${escapeHtml(t('dbAppsNone'))}</div>`;
  const total = list.reduce((s, x) => s + x.minutes, 0), top = list[0].minutes;
  const shown = list.slice(0, size === 'M' ? 5 : 6), rest = list.slice(shown.length);
  // the names the server gives in Russian («Проводник», «Блокнот»…) are said in the language of the page by the
  // program's key (app/worktime.py APP_NAMES)
  const rows = shown.map((x, i) => ({ ...x, name: x.app === 'meeting' ? t('dbAppsMeetings') : tMaybe(`appName_${x.app}`) || x.name, color: DB_SLICE[i % DB_SLICE.length] }));
  if (rest.length) rows.push({ app: '', name: t('dbAppsOther').replace('{n}', () => rest.length), minutes: rest.reduce((s, x) => s + x.minutes, 0), before: rest.reduce((s, x) => s + x.before, 0), color: DB_OTHER, rest: true });
  // «5 ч 50», «10 ч», «40 мин»: short enough for a row
  const hm = m => m < 60 ? `${m} ${t('dbMinShort')}` : `${Math.floor(m / 60)} ${t('dbHoursShort')}${m % 60 ? ` ${String(m % 60).padStart(2, '0')}` : ''}`;
  const delta = x => {
    const d = x.minutes - x.before;
    if (!x.before || Math.abs(d) < 6) return '';
    return `${d > 0 ? '+' : '−'}${hm(Math.abs(d))}`;
  };
  const pct = x => Math.round(x.minutes / total * 100);
  const icon = x => `<span class="db-app-ic" style="background:${x.color}">${x.app === 'meeting' ? DB_ICON('<rect x="3.5" y="5" width="17" height="15" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/>') : escapeHtml(x.rest ? '…' : (x.name || '?').charAt(0).toUpperCase())}</span>`;
  const head = `<div class="db-apps-head"><b>${escapeHtml(dbHm(total * 60))}</b> <span>${escapeHtml(`${t('dbAppsAt')} ${dbWSince('apps', r.since)}`)}</span><span class="db-apps-local">${escapeHtml(t('dbAppsLocal'))}</span></div>`;
  const view = dbChartKind('apps', DB_APPS_KINDS, 'list');
  if (view === 'ring') {
    let at = 0;
    const segs = rows.map(x => {
      const len = x.minutes / total * 100;
      const seg = `<circle r="15.9155" cx="18" cy="18" fill="none" stroke="${x.color}" stroke-width="4.2" stroke-dasharray="${Math.max(0.1, len - 0.6).toFixed(2)} ${(100 - len + 0.6).toFixed(2)}" stroke-dashoffset="${(25 - at).toFixed(2)}"/>`;
      at += len;
      return seg;
    }).join('');
    return head + `<div class="dbc-ring db-apps-ring"><svg viewBox="0 0 36 36" class="dbc-ring-svg" role="img" aria-label="${escapeHtml(dbHm(total * 60))}">${segs}`
      + `<text x="18" y="18" text-anchor="middle" class="dbc-ring-n">${dbNum(Math.round(total / 6) / 10)}</text><text x="18" y="22.6" text-anchor="middle" class="dbc-ring-l">${escapeHtml(t('dbHoursShort'))}</text></svg>`
      + `<div class="dbc-lg db-apps-lg">${rows.map(x => `<div title="${escapeHtml(x.app || x.name)}"><i style="background:${x.color}"></i><span class="dbc-lg-d">${escapeHtml(x.name)}</span>`
        + `<b class="dbc-lg-bar"><u style="width:${(x.minutes / top * 100).toFixed(1)}%;background:${x.color}"></u></b>`
        + `<span class="dbc-lg-h">${escapeHtml(hm(x.minutes))}</span><span class="dbc-lg-p">${pct(x)}%</span></div>`).join('')}</div></div>`;
  }
  if (view === 'col') {
    return head + `<div class="db-apps-cols">${rows.map(x => `<div title="${escapeHtml(`${x.name}: ${hm(x.minutes)}${delta(x) ? ` · ${delta(x)}` : ''}`)}">`
      + `<span class="db-ac-area"><span class="db-ac-v" style="bottom:${(x.minutes / top * 100).toFixed(1)}%">${escapeHtml(hm(x.minutes))}</span>`
      + `<b style="height:${Math.max(2, x.minutes / top * 100).toFixed(1)}%;background:${x.color}"></b></span>${icon(x)}<span class="db-ac-n">${escapeHtml(x.name)}</span></div>`).join('')}</div>`;
  }
  return head + `<div class="db-apps-strip">${rows.map(x => `<i style="flex:${x.minutes};background:${x.color}" title="${escapeHtml(`${x.name}: ${hm(x.minutes)}`)}"></i>`).join('')}</div>`
    + `<div class="db-apps-list${size === 'W' ? ' two' : ''}">` + rows.map(x => `<div class="db-app">`
      + `${icon(x)}<span class="db-app-n" title="${escapeHtml(x.app || '')}">${escapeHtml(x.name)}</span>`
      + `<span class="db-app-bar"><i style="width:${(x.minutes / top * 100).toFixed(1)}%;background:${x.color}"></i></span>`
      + `<span class="db-app-h">${escapeHtml(hm(x.minutes))}</span><span class="db-app-p">${pct(x)}%</span>`
      + `<span class="db-app-d">${escapeHtml(delta(x))}</span></div>`).join('') + '</div>';
}

async function dbAppsTurnOn() {
  if (!(await askConfirm(`${t('dbAppsAskQ')}\n${t('rdSasAppsHint')}`, false, t('dbAppsOn')))) return;
  saveUiSetting('apps_track', 'true');
  const sw = document.getElementById('set-apps-track');
  if (sw) sw.checked = true;  // the settings' switch says the same
  DB.apps = { ...(DB.apps || {}), enabled: true, apps: [] };
  renderDashboard();
}

async function clearAppsHistory() {
  if (!(await askConfirm(t('rdSasAppsClearQ'), true, t('rdSasAppsClear')))) return;
  const r = await fetch('/api/worktime/apps', { method: 'DELETE' }).catch(() => null);
  if (!r || !r.ok) { showError(t('errorGeneric')); return; }
  DB.apps = DB.apps ? { ...DB.apps, apps: [] } : null;
  showToast(t('rdSasAppsCleared'), null, 'status');
}

function openWorkSettings() {
  openModal('settings', 'general');
  selectSettingsTab('calendar');
}

function dbCycleNorm() {
  const norms = [2, 3, 4, 5, 6];
  dbSave({ norm: norms[(norms.indexOf(dbPrefs().norm) + 1) % norms.length] });
  renderDashboard();
}

// «Серии без результатов»: series whose last meetings, three or more in a row, gave no decision and no task
// (app/dashboard._dull_series); a click opens the latest one
function dbDullHtml(d) {
  const list = d.dull_series || [];
  if (!list.length) return `<div class="db-note db-ok">${escapeHtml(t('dbDullNone'))}</div>`;
  return list.map(x => `<button class="db-dull" data-click="openMeeting" data-click-args='[${Number(x.last.id)}]' title="${escapeHtml(t('dbDullTip'))}">`
    + `<span class="db-dull-name">${escapeHtml(x.name)}</span>`
    + `<span class="db-dull-sub">${escapeHtml(t('dbDullStreak').replace('{n}', () => x.streak).replace('{h}', () => dbNum(x.hours)))}</span></button>`).join('');
}

// --- «Нагрузка системы и моделей» (asked by the user): the figures of the «Нагрузка» window of the status bar
// (static/js/pult.js renderLoadPop) in a widget. It reads vram.data, which the status bar's poll of /api/vram keeps
// fresh (static/js/settings.js loadVram): no request of its own. Each new picture redraws the widget while «Обзор» is
// shown (dbOnVramData from renderVram); hidden, nothing is drawn. S: the three bars; M and L: the models in memory too.
// Verbaliox's share in the accent over the grey of the whole, the value orange above 85 % (loadLevel)
function dbSysloadHtml(size) {
  const data = vram.data;
  if (!data) return `<div class="db-note">${escapeHtml(t('dbLoading'))}</div>`;
  const sys = data.system || {}, own = data.own || {}, gpu = data.gpu, ram = sys.ram;
  // the same columns as the «Нагрузка» window (static/js/pult.js ldRowsHtml); without a video card that reports its
  // memory the GPU row keeps its place, said in words
  let html = ldHeadHtml() + ldRowsHtml(sys, own, gpu, ram, null, [t('dbSlNoGpu'), t('mpNoGpu')]);
  if (size === 'S') return html;
  const models = loadModels();
  html += `<div class="db-sl-cap">${escapeHtml(t('ldInMemory'))}</div>`;
  if (!models.length) return `${html}<div class="db-sl-empty">${escapeHtml(t('dbSlEmpty'))}</div>`;
  return html + models.map(({ c, i }) => {
    const u = loadModelUse(c, own);
    const can = !vram.busy && !c.loading && c.kind !== 'dub' && (c.can_unload || c.in_use);
    const tip = c.kind === 'dub' ? t('tipVramDub') : vramChipTitle(c);
    return `<div class="db-sl-model"><span class="db-sl-name"><b>${escapeHtml(loadModelName(c))}</b><small>${escapeHtml(loadModelPurpose(c))}</small></span>`
      + `<span class="db-sl-use"><b>${escapeHtml(u.mem)}</b><small>${escapeHtml(u.more)}</small></span>`
      + `<button data-click="vramChipClick" data-click-args='[${i}]' class="tk-btn tk-btn-sm" title="${escapeHtml(tip)}" ${can ? '' : 'disabled'}>${escapeHtml(t('mpActUnload'))}</button></div>`;
  }).join('');
}

// A new picture of the load (renderVram in static/js/settings.js): the widget follows while «Обзор» is shown
// (drawn only when it changed, so a refresh never swallows a click on «Выгрузить»); hidden, nothing is drawn
function dbOnVramData() {
  if (state.appView !== 'dashboard' || document.hidden || DB.edit || (DB.drag && DB.drag.on)) return;
  dbPrefs().layout.forEach((w, i) => {
    if (w.id !== 'sysload') return;
    const c = document.querySelector(`#db-grid .db-w[data-i="${i}"] .db-c`);
    const html = c && dbWidgetHtml('sysload', dbSize(w));
    if (c && c._vxHtml !== html) { c._vxHtml = html; c.innerHTML = html; }
  });
}

// While the widget is shown, the poll of the load keeps its pace even without a video card (static/js/settings.js)
function dbSysloadLive() {
  return state.appView === 'dashboard' && !document.hidden && dbPrefs().layout.some(w => w.id === 'sysload');
}

function dbWidgetHtml(id, size) {
  const d = DB.data;
  if (!d && !DB_LOCAL_WIDGETS.includes(id)) return `<div class="db-note">${escapeHtml(t(DB.loading ? 'dbLoading' : 'dbNoData'))}</div>`;
  switch (id) {
    case 'kpis': return dbKpis(d, size);
    case 'load': return dbLoadHtml();
    case 'worked': return dbWorkedHtml(size);
    case 'apps': return dbAppsHtml(size);
    case 'sysload': return dbSysloadHtml(size);
    case 'dull': return dbDullHtml(d);
    case 'mytasks': return dbTasks(d, size);
    case 'waiting': return dbWaitingHtml(d, size);
    case 'features': return dbFeatures(d, size);
    case 'time': return dbTime(d);
    case 'people': return dbPeople();
    case 'decisions': return dbDecisions(d, size);
    case 'summary': return dbSummaryHtml();
  }
  return '';
}

// --- «Статистика»: compact tiles, each with its figure, a small trend of six periods, what it counts (under it,
// wrapped, never cut) and the change to the period before, coloured by what it means: green better, amber to
// watch, red bad. Which figures and in what order is chosen in «Показатели» (2 to 8, kept with the dashboard) ---
// better: which way is good (1 up, -1 down, 0 neither); worse: the tone of the other way; detail: what a click opens
const DB_KPI = {
  meetings: { better: 0, detail: 'meetings', fmt: v => String(v) },
  hours: { better: -1, worse: 'warn', detail: 'meetings', fmt: v => dbHours(v), unit: 'h' },
  share: { better: -1, worse: 'warn', detail: 'meetings', fmt: v => `${v}%`, hint: true },
  focus: { better: 1, worse: 'bad', detail: 'meetings', fmt: v => dbHours(v), unit: 'h', hint: true },
  mine: { better: -1, worse: 'warn', detail: 'tasks', fmt: v => String(v), me: true },
  closed: { better: 1, worse: 'warn', detail: 'tasks', fmt: v => String(v), me: true, hint: true },
  waiting: { better: -1, worse: 'warn', detail: 'waiting', fmt: v => String(v), me: true, hint: true },
  decisions: { better: 1, worse: 'warn', detail: 'decisions', fmt: v => String(v) },
  useless: { better: -1, worse: 'warn', detail: 'useless', fmt: v => String(v), hint: true },
  avg: { better: -1, worse: 'warn', detail: 'meetings', fmt: v => `${v} ${t('dbMinShort')}`, unit: 'min' },
  people: { better: 0, fmt: v => String(v) },
};

function dbKpiList(v) {
  const list = Array.isArray(v) ? [...new Set(v.filter(k => DB_KPI[k]))].slice(0, DB_KPI_MAX) : [];
  return list.length >= DB_KPI_MIN ? list : [...DB_KPI_DEFAULT];
}

function dbSpark(v) {
  v = (v || []).filter(x => x != null);  // the periods before the first data have no value
  if (v.length < 2) return '';
  const lo = Math.min(...v), hi = Math.max(...v), k = hi - lo || 1;
  const pts = v.map((x, i) => `${(i * 56 / (v.length - 1)).toFixed(1)},${(hi === lo ? 12 : 20 - (x - lo) / k * 16).toFixed(1)}`);
  const [cx, cy] = pts[pts.length - 1].split(',');
  return `<svg class="db-spark-l" viewBox="-2 0 60 24" width="60" height="24" aria-hidden="true"><polyline points="${pts.join(' ')}" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/><circle cx="${cx}" cy="${cy}" r="2.2" fill="currentColor"/></svg>`;
}

// The figure of a metric now, its six periods, and the line under it with its tone
function dbKpiFigure(key, d) {
  const def = DB_KPI[key], h = (d.history && d.history.values && d.history.values[key]) || null;
  const k = d.kpi;
  const now = h ? h[h.length - 1] : ({ meetings: k.meetings, hours: k.hours, mine: k.open, waiting: k.waiting, decisions: k.decisions, useless: k.useless })[key] ?? 0;
  // compared with what the server says (the period before, or the same days a year earlier); the trend's one before
  const cmp = d.history && d.history.before;
  const before = cmp && key in cmp ? cmp[key] : h && h.length > 1 ? h[h.length - 2] : null;
  let line = '', tone = 'flat';
  if (def.me && d.needs_me) return { value: '—', spark: '', line: '', tone, needsMe: true };
  // no data up to this period (the share, the time without meetings before the first recording): unknown, not zero
  if (now == null) return { value: '—', now: null, spark: '', line: '', tone };
  if (key === 'mine' && k.overdue) { line = t('dbOverdueN').replace('{n}', () => k.overdue); tone = 'bad'; }
  else if (key === 'waiting' && k.waiting_overdue) { line = t('kpiWaitOverdue').replace('{n}', () => k.waiting_overdue); tone = 'warn'; }
  else if (before != null) {
    // hours to the minute (less than 0,1 h is written in minutes), the other figures to a tenth
    const x = def.unit === 'h' ? Math.round((now - before) * 60) / 60 : Math.round((now - before) * 10) / 10;
    const ago = d.compare === 'year';
    if (!x) line = t(ago ? 'kpiSameYear' : 'kpiSame');
    else if (key === 'share') line = t(ago ? 'kpiWasYear' : 'kpiWas').replace('{v}', () => `${before}%`);
    else {
      const abs = def.unit === 'h' ? dbHours(Math.abs(x)) : `${dbNum(Math.abs(x))}${def.unit === 'min' ? ` ${t('dbMinShort')}` : ''}`;
      line = `${x > 0 ? '+' : '−'}${abs} ${t(`${ago ? 'dbVsYear' : 'dbVsBefore'}_${d.period}`)}`;
    }
    if (x && def.better) tone = (x > 0) === (def.better > 0) ? 'up' : def.worse;
  }
  return { value: def.fmt(now), now, spark: dbSpark(h), line, tone };
}

// what the figure counts, under it: «встречи», «решений», as the number asks
function dbKpiCaption(key, n) {
  const forms = t(`kpiCap_${key}`);
  return forms.includes('|') ? plural(Math.round(Number(n) || 0), forms).replace(/^\S+\s/, '') : forms;
}

function dbKpis(d, size) {
  const sel = dbPrefs().kpis;
  // the tiles fill the rows whatever their number, the rows balanced: up to 6 in a row, 4 in a narrow card
  const narrow = size !== 'W' || (document.getElementById('db-grid')?.clientWidth || 1200) < 900;
  const per = narrow ? 4 : 6, rows = Math.ceil(sel.length / per), spans = [];
  for (let r = 0, left = sel.length; r < rows; r++) { const n = Math.ceil(left / (rows - r)); for (let i = 0; i < n; i++) spans.push(60 / n); left -= n; }
  const tiles = sel.map((key, i) => {
    const def = DB_KPI[key], f = dbKpiFigure(key, d);
    const name = t(`kpiN_${key}`), hint = def.hint ? t(`kpiHint_${key}`) : '';
    const inner = `<span class="db-kt-top"><span class="db-kt-n">${escapeHtml(f.value)}</span><span class="db-kt-spark t-${f.tone}">${f.spark}</span></span>`
      + `<span class="db-kt-l">${escapeHtml(f.needsMe ? name : dbKpiCaption(key, f.now))}</span>`
      + (f.needsMe ? '' : `<span class="db-kt-d t-${f.tone}">${escapeHtml(f.line)}</span>`);
    const tip = [name, hint, def.detail && !f.needsMe ? t('dbOpenDetailTip') : ''].filter(Boolean).join('\n');
    const style = `grid-column:span ${spans[i]}`;
    if (f.needsMe) return `<div class="db-kt" style="${style}" title="${escapeHtml(tip)}">${inner}<button class="db-more db-kt-me" data-click="hmSetMyName">${escapeHtml(t('dbSetMe'))}</button></div>`;
    return def.detail
      ? `<button class="db-kt db-kt-open" style="${style}" data-click="dbOpenDetail" data-click-args='["${def.detail}"]' title="${escapeHtml(tip)}">${inner}</button>`
      : `<div class="db-kt" style="${style}" title="${escapeHtml(tip)}">${inner}</div>`;
  }).join('');
  // the recordings of the period the feature filter leaves out, with the way back to all of them
  const f = d.feature ? featureById(d.feature) : null;
  const note = f && d.outside
    ? `<div class="db-note db-kts-note">${escapeHtml(t('dbFeatureOutside').replace('{name}', () => f.name).replace('{n}', () => d.outside))}`
      + ` <button class="db-more" data-click="setDashFeature" data-click-args="[0]">${escapeHtml(t('dbFeatureClear'))}</button></div>`
    : '';
  return `<div class="db-kts">${tiles}</div>${note}${DB.kpiCfg ? dbKpiPanelHtml(d) : ''}`;
}

// «Показатели»: every metric by its own name, on or off (2 to 8), ↑↓ for the order, «По умолчанию»
function dbKpiPanelHtml(d) {
  const sel = dbPrefs().kpis, full = sel.length >= DB_KPI_MAX;
  const all = [...sel, ...Object.keys(DB_KPI).filter(k => !sel.includes(k))];
  const rows = all.map(k => {
    const on = sel.includes(k), at = sel.indexOf(k), f = d ? dbKpiFigure(k, d) : { value: '' };
    const lock = on && sel.length <= DB_KPI_MIN;
    return `<div class="kc-row${on ? ' on' : ''}${!on && full ? ' full' : ''}">`
      + `<button class="kc-cb${on ? ' on' : ''}" role="checkbox" aria-checked="${on}" aria-disabled="${lock || (!on && full)}" data-click="dbKpiToggle" data-click-args='["${k}"]' aria-label="${escapeHtml(t(`kpiN_${k}`))}"${lock ? ` title="${escapeHtml(t('kpiMin'))}"` : ''}>${on ? '✓' : ''}</button>`
      + `<span class="kc-n">${escapeHtml(t(`kpiN_${k}`))}</span><span class="kc-v">${escapeHtml(f.value)}</span>`
      + `<span class="kc-ar">${on ? `<button class="kc-mv" data-click="dbKpiMove" data-click-args='["${k}", -1]' ${at === 0 ? 'disabled' : ''} title="${escapeHtml(t('kpiUp'))}" aria-label="${escapeHtml(t('kpiUp'))}">↑</button>`
        + `<button class="kc-mv" data-click="dbKpiMove" data-click-args='["${k}", 1]' ${at === sel.length - 1 ? 'disabled' : ''} title="${escapeHtml(t('kpiDown'))}" aria-label="${escapeHtml(t('kpiDown'))}">↓</button>` : ''}</span></div>`;
  }).join('');
  return `<div class="db-kc" role="dialog" aria-label="${escapeHtml(t('kpiCfg'))}">`
    + `<div class="kc-h"><b>${escapeHtml(t('kpiCfg'))}</b><span>${escapeHtml(t('kpiCount').replace('{n}', () => sel.length).replace('{max}', () => DB_KPI_MAX))}</span></div>`
    + (full ? `<div class="kc-lim">${escapeHtml(t('kpiLimit').replace('{max}', () => DB_KPI_MAX))}</div>` : '')
    + `<div class="kc-list">${rows}</div>`
    + `<div class="kc-f"><button class="tk-btn tk-btn-sm" data-click="dbKpiReset">${escapeHtml(t('kpiDefault'))}</button><span class="flex-1"></span>`
    + `<button class="tk-btn tk-btn-primary tk-btn-sm" data-click="dbKpiPanel">${escapeHtml(t('dbDone'))}</button></div></div>`;
}

// The widget drawn again in place, the list of «Показатели» kept where it was scrolled to
function dbKpiRedraw() {
  const list = document.querySelector('#db-grid .db-w-kpis .kc-list'), top = list ? list.scrollTop : 0;
  dbRedrawWidget('kpis');
  const again = document.querySelector('#db-grid .db-w-kpis .kc-list');
  if (again) again.scrollTop = top;
}

function dbKpiPanel() {
  DB.kpiCfg = !DB.kpiCfg;
  dbKpiRedraw();
  if (DB.kpiCfg) document.querySelector('.db-kc')?.classList.add('vx-pop-in');  // the motion only on opening
}

function dbKpiToggle(k) {
  const sel = [...dbPrefs().kpis];
  if (sel.includes(k)) {
    if (sel.length <= DB_KPI_MIN) return;
    sel.splice(sel.indexOf(k), 1);
  } else if (sel.length >= DB_KPI_MAX) {
    // the note says why: it flashes
    const lim = document.querySelector('#db-grid .db-w-kpis .kc-lim');
    if (lim) { lim.classList.remove('hit'); void lim.offsetWidth; lim.classList.add('hit'); }
    return;
  } else sel.push(k);
  dbSave({ kpis: sel });
  dbKpiRedraw();
}

function dbKpiMove(k, step) {
  const sel = [...dbPrefs().kpis], i = sel.indexOf(k), j = i + step;
  if (i < 0 || j < 0 || j >= sel.length) return;
  [sel[i], sel[j]] = [sel[j], sel[i]];
  dbSave({ kpis: sel });
  dbKpiRedraw();
}

function dbKpiReset() {
  dbSave({ kpis: [...DB_KPI_DEFAULT] });
  dbKpiRedraw();
}

document.addEventListener('keydown', e => { if (e.key === 'Escape' && DB.kpiCfg && state.appView === 'dashboard') { DB.kpiCfg = false; dbKpiRedraw(); } });

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

// «Фичи»: each feature with its colour (the same as on its card and its chips; one of the palette by its order when
// it has none), the meetings of its last eight weeks in that colour, its meetings and tasks, its last meeting
function dbFeatures(d, size) {
  if (!d.features.length) return `<div class="db-note">${escapeHtml(t('dbNoFeatures'))}</div>`;
  const n = size === 'M' ? 3 : size === 'W' ? 8 : 5;
  const head = `<div class="db-ft-head"><span></span><span>${escapeHtml(t('dbFtWeeks'))}</span><span>${escapeHtml(t('dbFtMeetings'))}</span>`
    + `${d.needs_me ? '<span></span>' : `<span>${escapeHtml(t('dbFtTasks'))}</span>`}<span>${escapeHtml(t('dbFtLast'))}</span></div>`;
  return head + d.features.slice(0, n).map((f, i) => {
    const c = /^#[0-9A-Fa-f]{6}$/.test(f.color || '') ? f.color : DB_SLICE[i % DB_SLICE.length];
    const max = Math.max(1, ...f.spark);
    const tasks = d.needs_me ? '' : f.open ? `${plural(f.open, t('dbTaskForms'))}${f.overdue ? ` <b class="neg" title="${escapeHtml(t('dbOverdueN').replace('{n}', () => f.overdue))}">!</b>` : ''}` : `<span class="db-dim">${escapeHtml(t('dbNoTasks'))}</span>`;
    // a click opens the feature's card (asked by the user); the filter of «Обзор» is in «Все фичи ▾»
    return `<button class="db-ft-row" style="--ft:${c}" data-click="openFeaturePage" data-click-args='[${f.id}]' title="${escapeHtml(t('dbFeatureOpenTip').replace('{name}', () => f.name))}">`
      + `<span class="db-ft-n"><i></i><span>${escapeHtml(f.name)}</span></span>`
      + `<span class="db-spark" title="${escapeHtml(t('dbSparkTip'))}">${f.spark.map(v => `<i style="height:${Math.round(8 + 92 * v / max)}%;opacity:${v ? 1 : 0.25}"></i>`).join('')}</span>`
      + `<span class="db-ft-c">${f.meetings ? escapeHtml(plural(f.meetings, t('dbMeetingForms'))) : `<span class="db-dim">${escapeHtml(t('dbNoMeetingsShort'))}</span>`}</span>`
      + `<span class="db-ft-c">${tasks}</span>`
      + `<span class="db-ft-c db-dim" title="«${escapeHtml(f.last.title)}»">${escapeHtml(dbAgo(f.last.date, d.today))}</span></button>`;
  }).join('');
}

function dbAgo(day, today) {
  const n = Math.round((new Date(`${today}T12:00:00`) - new Date(`${day}T12:00:00`)) / 864e5);
  if (n === 0) return t('libToday').toLowerCase();
  if (n === 1) return t('libYesterday').toLowerCase();
  return new Date(`${day}T12:00:00`).toLocaleDateString(state.uiLang === 'en' ? 'en-US' : 'ru-RU', { day: 'numeric', month: 'short' });
}

// «Время во встречах»: the hours of each day (a week) or each week (a month, a quarter), in the look chosen
function dbTime(d) {
  const b = d.buckets;
  if (!b.some(x => x.hours)) return `<div class="db-note">${escapeHtml(t('dbNoMeetingsYet'))}</div>`;
  const lang = state.uiLang === 'en' ? 'en-US' : 'ru-RU', today = d.today;
  const label = x => {
    const dt = new Date(`${x.key}T12:00:00`);
    if (x.kind === 'month') return dt.toLocaleDateString(lang, { month: 'short' }).replace('.', '');
    return x.kind === 'day' ? dt.toLocaleDateString(lang, { weekday: 'short' }) : dt.toLocaleDateString(lang, { day: 'numeric', month: 'short' });
  };
  const top = b.reduce((m, x) => (x.hours > m.hours ? x : m), b[0]);
  const rows = b.map(x => ({ label: label(x), value: x.hours, cls: x.kind === 'day' && x.key === today ? 'today' : '',
    tip: `${label(x)}: ${dbHours(x.hours)}${x.meetings.length ? '\n' + x.meetings.map(m => `· ${m.title}`).join('\n') : ''}` }));
  return dbChartHtml('time', rows, 0)
    // the summary and the hint on lines of their own (asked by the user: one long line read oddly)
    + `<div class="db-time-foot"><span class="db-time-top">${escapeHtml(t('dbTimeTop').replace('{when}', () => label(top)).replace('{h}', () => dbHours(top.hours)).replace('{n}', () => top.meetings.length))}</span>`
    + `<span class="db-time-hint">${escapeHtml(t('dbTimeHover'))}</span></div>`;
}

// «Частые участники»: the meetings together in the widget's own period, a bar to the first one, the hours together
function dbPeople() {
  const cap = `<div class="db-pp-cap"><span title="${escapeHtml(dbWSince('people'))}">${escapeHtml(t('dbPpCap'))}</span>${DB.edit ? '' : dbWPeriodSwitch('people')}</div>`;
  const got = DB.people;
  if (!got) return cap + `<div class="db-note">${escapeHtml(t(DB.loading ? 'dbLoading' : 'dbNoData'))}</div>`;
  if (!got.list.length) return cap + `<div class="db-note">${escapeHtml(t('dbNoPeople'))}</div>`;
  const max = Math.max(...got.list.map(p => p.meetings));
  return cap + got.list.slice(0, 5).map((p, i) => {
    const c = /^#[0-9A-Fa-f]{6}$/.test(p.color || '') ? p.color : TK_COLORS[i % TK_COLORS.length];
    return `<button class="db-pp" data-click="dbOpenDetail" data-click-args='["person", ${escapeHtml(JSON.stringify(p.name))}]'>`
      + `<span class="db-av" style="--av:${c}">${escapeHtml(p.name.charAt(0).toUpperCase())}</span>`
      + `<span class="db-pp-n">${escapeHtml(p.name)}</span>`
      + `<span class="db-pp-bar"><i style="width:${Math.round(100 * p.meetings / max)}%"></i></span>`
      + `<span class="db-pp-m">${escapeHtml(plural(p.meetings, t('dbMeetingForms')))}</span>`
      + `<span class="db-pp-h">${p.hours ? escapeHtml(dbHours(p.hours)) : ''}</span></button>`;
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
  return `<div class="db-md">${sanitizedHtml(s.html)}</div><div class="db-note">${escapeHtml(t(`dbPeriod_${s.period}`))} · ${escapeHtml(when)}${s.model ? ` · ${escapeHtml(s.model)}` : ''}</div>`;
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
  dbSetAt(DB.at);  // a past day stays: from a past month to its year
  dbReload();
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
  const cur = p.feature ? featureById(p.feature) : null;
  openTextMenuAt([...(cur ? [{ label: `↗  ${t('dbFeatureCard').replace('{name}', () => cur.name)}`, run: () => openFeaturePage(cur.id) }, { sep: true }] : []),
    { label: tick(!p.feature, t('dbAllFeatures')), run: () => setDashFeature(0) }, { sep: true },
    ...feats.map(f => ({ label: tick(p.feature === f.id, f.name), run: () => setDashFeature(f.id) })),
    { sep: true }, { label: t('ftManage'), run: () => openFeatureDrawer(p.feature) }], r.left, r.bottom + 4);
}

async function dashTaskDone(id) {
  const res = await fetch(`/api/tasks/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'done' }) });
  if (!res.ok) { showToast(errorText(await readJson(res), res)); return; }
  if (DB.data) DB.data.tasks = DB.data.tasks.filter(x => x.id !== id);
  if (typeof TD !== 'undefined' && TD.data) TD.data.tasks = TD.data.tasks.filter(x => x.id !== id);
  // the page on screen follows: «Обзор» or «Сегодня» (its cards are drawn by this file)
  const reload = () => (state.appView === 'home' && typeof tdLoad === 'function' ? tdLoad() : loadDashboard());
  if (state.appView === 'home') tdRender(); else renderDashboard();
  showToast(t('dbTaskDone'), { label: t('spUndo'), onClick: async () => {
    await fetch(`/api/tasks/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'open' }) });
    reload();
  } }, 'success');
  reload();
  if (typeof loadTasks === 'function') loadTasks();
}

function dashOpenTask(id, meetingId) {
  if (meetingId) dashOpenSummary(meetingId);
  else switchAppView('tasks');
}

// the analysis once the recording is open (a fixed pause showed the transcript of a slow one: audit)
async function dashOpenSummary(meetingId) {
  await openMeeting(meetingId);
  if (state.activeMeeting && state.activeMeeting.id === meetingId) openRecordTab('summary');
}

// --- «Ожидаю от других»: what others promised the user (asked by the user) ---
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
  const q = new URLSearchParams({ kind, period: p.period, feature: p.feature || 0, person, at: DB.at });
  const data = await fetch(`/api/dashboard/detail?${q}`).then(r => (r.ok ? r.json() : null)).catch(() => null);
  if (DB_DETAIL.kind !== kind || DB_DETAIL.person !== person) return;  // another one opened meanwhile
  DB_DETAIL.data = data || { error: true };
  dbRenderDetail();
}

function dbCloseDetail() {
  DB_DETAIL.kind = '';
  drawerHide(document.getElementById('db-detail'));
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
    return `<span class="db-dt-chip">${f ? featureChipHtml(f) : escapeHtml(t('dbNoFeature'))} ${escapeHtml(dbHours(x.hours))}</span>`;
  }).join('');
  const seg = `<div class="tk-seg db-dt-seg" role="radiogroup">${['all', 'useless'].map(k => `<button role="radio" aria-checked="${DB_DETAIL.filter === k}" class="tk-seg-btn${DB_DETAIL.filter === k ? ' tk-on' : ''}" data-click="dbDetailFilter" data-click-args='["${k}"]'>${escapeHtml(t(k === 'all' ? 'dbDtAll' : 'dbDtUseless'))}${k === 'useless' ? ` · ${d.meetings.filter(r => r.reasons.length).length}` : ''}</button>`).join('')}</div>`;
  const reason = r => r.reasons.map(x => `<span class="db-dt-why" title="${escapeHtml(t(`dbWhy_${x}_tip`))}">${escapeHtml(t(`dbWhy_${x}`))}</span>`).join('');
  const list = rows.map(r => {
    const f = (r.features || []).map(featureById).filter(Boolean)[0];
    const when = `${dbAgo(r.date, DB.data ? DB.data.today : r.date)}${r.time ? ` ${r.time}` : ''}`;
    return `<button class="db-dt-row" data-click="dashOpenSummary" data-click-args='[${r.id}]'>`
      + `<span class="db-dt-main"><b class="db-dt-one">${escapeHtml(r.title || t('hmUntitled'))}</b><small>${f ? featureChipHtml(f) : ''}<span>${escapeHtml(when)}</span>${reason(r)}</small></span>`
      + `<span class="db-dt-num${r.decisions ? '' : ' db-dt-zero'}" title="${escapeHtml(t('dbDtDecTip'))}">${r.decisions}</span>`
      + `<span class="db-dt-num${r.tasks ? '' : ' db-dt-zero'}" title="${escapeHtml(t('dbDtTaskTip'))}">${r.tasks}</span>`
      + `<span class="db-dt-num" title="${escapeHtml(t('dbDtShareTip'))}">${r.my_share == null ? '—' : `${Math.round(r.my_share)}%`}</span>`
      + `<span class="db-dt-dur">${escapeHtml(dbHm(r.duration))}</span></button>`;
  }).join('');
  return `<div class="db-dt-sum">${escapeHtml(t('dbDtMeetingsSum').replace('{n}', () => rows.length).replace('{h}', () => dbHm(total)))}</div>`
    + (chips ? `<div class="db-dt-chips">${chips}</div>` : '') + seg
    + (rows.length ? `<div class="db-dt-head"><span></span><span>${escapeHtml(t('dbDtDec'))}</span><span>${escapeHtml(t('dbDtTasks'))}</span><span>${escapeHtml(t('dbDtShare'))}</span><span></span></div>${list}`
      : vxEmpty('meet', t(DB_DETAIL.filter === 'useless' ? 'dbUselessNone' : 'dbNoMeetingsYet')));
}

function dbDetailTasks(list, today, mine) {
  if (!list.length) return vxEmpty(mine ? 'task' : 'wait', t(mine ? 'dbNoMyTasks' : 'dbNoWaiting'));
  return list.map(x => `<div class="db-dt-task${x.status === 'done' ? ' done' : ''}">`
    + (mine && x.status !== 'done' ? `<button class="db-ck" data-click="dbDetailDone" data-click-args='[${x.id}]' title="${escapeHtml(t('dbMarkDone'))}" aria-label="${escapeHtml(t('dbMarkDone'))}"></button>` : '<span class="db-ck-gap"></span>')
    + `<button class="db-dt-main" data-click="dashOpenTask" data-click-args='[${x.id}, ${Number(x.meeting_id) || 0}]'><span class="db-dt-text">${escapeHtml(x.what)}</span>`
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
  if (!kind) { drawerHide(box); return; }
  drawerShow(box);
  const today = DB.data ? DB.data.today : calKey(new Date());
  const title = kind === 'person' ? person : t(`dbDt_${kind}`);
  const period = DB.data && kind !== 'person' ? document.getElementById('db-sub')?.textContent || '' : '';
  let body;
  if (!d) body = `<div class="db-note">${escapeHtml(t('dbLoading'))}</div>`;
  else if (d.error) body = vxEmpty('over', t('dbNoData'));
  else if (kind === 'meetings' || kind === 'useless') body = dbDetailMeetings(d);
  else if (kind === 'decisions') {
    // grouped by their meeting (asked by the user: the same title and chip under every decision made the list
    // a wall of equal lines): the meeting once as the card's head, its decisions as plain points under it
    const groups = [];
    for (const x of d.decisions) {
      const last = groups[groups.length - 1];
      if (last && last.meeting_id === x.meeting_id) last.items.push(x.text);
      else groups.push({ ...x, items: [x.text] });
    }
    body = groups.length ? groups.map(g => {
      const f = (g.features || []).map(featureById).filter(Boolean)[0];
      return `<div class="db-dt-group"><button class="db-dt-ghead" data-click="dashOpenSummary" data-click-args='[${g.meeting_id}]'>`
        + `<span class="db-dt-gtitle">${escapeHtml(g.title || t('hmUntitled'))}</span><small>${f ? featureChipHtml(f) : ''}<span>${escapeHtml(dbAgo(g.date, today))}</span></small></button>`
        + `<ul class="db-dt-points">${g.items.map(x => `<li>${escapeHtml(x)}</li>`).join('')}</ul></div>`;
    }).join('') : vxEmpty('dec', t('dbNoDecisionsYet'));
  } else if (kind === 'tasks' || kind === 'waiting') {
    body = d.needs_me ? `<div class="db-note">${escapeHtml(t('dbNeedsMe'))}</div>` : dbDetailTasks(d.tasks, today, kind === 'tasks');
  } else {  // a person
    body = `<div class="db-dt-sec">${escapeHtml(t('dbDtOwesMe'))}</div>${dbDetailTasks(d.owes_me || [], today, false)}`
      + `<div class="db-dt-sec">${escapeHtml(t('dbDtIOwe'))}</div>${dbDetailTasks(d.i_owe || [], today, true)}`
      + `<div class="db-dt-sec">${escapeHtml(t('dbDtTheirMeetings').replace('{n}', () => d.meetings_total || 0))}</div>`
      + ((d.meetings || []).map(m => `<button class="db-dt-row db-dt-row2" data-click="dashOpenSummary" data-click-args='[${m.id}]'>`
        + `<span class="db-dt-main"><b class="db-dt-one">${escapeHtml(m.title || t('hmUntitled'))}</b><small><span>${escapeHtml(dbAgo(m.date, today))}</span></small></span><span class="db-dt-dur">${escapeHtml(dbHm(m.duration))}</span></button>`).join('')
        || vxEmpty('meet', t('dbNoMeetingsYet')))
      + `<button class="tk-btn tk-btn-sm db-dt-card" data-click="openPersonCard" data-click-args='[${jsArg(person)}]'>${escapeHtml(t('dbDtCard'))}</button>`;
  }
  const ic = { meetings: 'meet', useless: 'over', decisions: 'dec', tasks: 'task', waiting: 'wait' }[kind] || 'people';
  box.innerHTML = vxHead(ic, title, { sub: period, close: 'data-click="dbCloseDetail"' }) + `<div class="db-dt-body">${body}</div>`;
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
  if (id === 'sysload' && typeof scheduleVramRefresh === 'function') scheduleVramRefresh(50);
  if (id === 'apps' && !DB.apps) dbLoadApps().then(() => { if (state.appView === 'dashboard') renderDashboard(); });
  document.querySelector('#db-grid .db-w:last-child')?.scrollIntoView({ block: 'nearest', behavior: scrollMotion() });
}

function resetDashboard() {
  dbSave({ layout: DB_DEFAULT.map(([id, size]) => ({ id, size })) });
  renderDashboard();
}

// the line icons of the widgets in the panel «Виджеты» (the icon language of the rail and the cards)
const DB_LIB_IC = { kpis: 'grid', mytasks: 'task', waiting: 'wait', features: 'tag', time: 'chart', people: 'people', decisions: 'dec',
  summary: 'spark', load: 'chart', dull: 'redo', worked: 'clock', apps: 'grid', sysload: 'chart' };

function renderDashDrawer() {
  const box = document.getElementById('db-drawer');
  if (!box) return;
  if (!DB.edit) { drawerHide(box, () => { box.innerHTML = ''; }); return; }
  drawerShow(box);
  const on = new Set(dbPrefs().layout.map(w => w.id));
  // one row for both lists; the right slot holds «Добавить» or the chip «Показан», so the slot never moves
  const item = (id, add) => `<div class="db-lib${add ? '' : ' on'}"><span class="db-lib-ic">${pultIcon(DB_LIB_IC[id] || 'grid')}</span>`
    + `<span class="db-lib-tx"><b>${escapeHtml(t(DB_WIDGETS[id].title))}</b><span>${escapeHtml(t(`dbAbout_${id}`))}</span></span>`
    + (add ? `<button class="tk-btn tk-btn-sm db-lib-add" data-click="addDashWidget" data-click-args='["${id}"]'>${VX_PLUS}<span>${escapeHtml(t('dbAdd'))}</span></button>`
      : `<span class="db-lib-shown">${escapeHtml(t('dbShown'))}</span>`) + '</div>';
  const ids = Object.keys(DB_WIDGETS);
  box.innerHTML = vxHead('grid', t('dbWidgets'), { close: 'data-click="toggleDashEdit"' }) + `<p class="db-drawer-hint">${escapeHtml(t('dbEditHint'))}</p>`
    + (ids.some(id => !on.has(id)) ? `<div class="db-cap">${escapeHtml(t('dbAddCap'))}</div>${ids.filter(id => !on.has(id)).map(id => item(id, true)).join('')}` : '')
    + `<div class="db-cap">${escapeHtml(t('dbOnCap'))}</div>${ids.filter(id => on.has(id)).map(id => item(id, false)).join('')}`
    + dbDaysOptionHtml()
    + `<div class="db-drawer-foot"><button class="tk-btn tk-btn-sm" data-click="resetDashboard">${escapeHtml(t('dbReset'))}</button>`
    + `<button class="tk-btn tk-btn-primary tk-btn-sm" data-click="toggleDashEdit">${escapeHtml(t('dbDone'))}</button></div>`;
}

// «Настроить»: the days the pill of the period counts (it was a gear beside the pill under the head)
function dbDaysOptionHtml() {
  const cur = dbPrefs().days === 'work' ? 'work' : 'cal';
  return `<div class="db-cap">${escapeHtml(t('dbDaysCap'))}</div><div class="db-days"><div class="tk-seg" role="radiogroup" aria-label="${escapeHtml(t('dbDaysTip'))}">`
    + ['cal', 'work'].map(k => `<button role="radio" aria-checked="${cur === k}" class="tk-seg-btn${cur === k ? ' tk-on' : ''}" data-click="setDashDays" data-click-args='["${k}"]'>${escapeHtml(t(k === 'work' ? 'dbDaysWork' : 'dbDaysCal'))}</button>`).join('')
    + '</div></div>';
}

// --- Arranging the widgets («Настроить»), asked by the user: the browser's own drag showed nothing until
// the drop, and the grid packed itself another way once «Готово» was pressed. Now the widget lifts and
// follows the pointer, a slot of its size stands where it will land and moves among the others as they
// make room; the grid packs the same way while arranging, so the slot's place is the widget's place ---
const DB_DRAG_PX = 5;      // a press that moves less is a click
const DB_EDGE_PX = 48;     // the grid scrolls by itself this close to its top or bottom

function dbTiles(grid) { return [...grid.querySelectorAll(':scope > .db-w:not(.db-lifted), :scope > .db-slot')]; }

// The others glide to their new places (first, last, invert, play)
function dbFlip(grid, change) {
  const els = dbTiles(grid);
  const before = new Map(els.map(el => [el, el.getBoundingClientRect()]));
  change();
  if (scrollMotion() === 'auto') return;
  const moved = [];
  dbTiles(grid).forEach(el => {
    const a = before.get(el);
    if (!a || el.classList.contains('db-slot')) return;
    const b = el.getBoundingClientRect();
    const dx = zpx(a.left - b.left), dy = zpx(a.top - b.top);
    if (Math.abs(dx) < 1 && Math.abs(dy) < 1) return;
    el.style.transition = 'none';
    el.style.transform = `translate(${dx}px, ${dy}px)`;
    moved.push(el);
  });
  if (!moved.length) return;
  void grid.offsetWidth;
  moved.forEach(el => { el.style.transition = 'transform 180ms cubic-bezier(0.2, 0.7, 0.2, 1)'; el.style.transform = ''; });
}

// The widget under the pointer, by the grid's own layout (not the boxes moved by the animation). The pointer and the
// box are in the window's pixels, the offsets in the page's own (the interface scale): divided by the zoom first
function dbHit(grid, x, y) {
  const g = grid.getBoundingClientRect();
  const px = zpx(x - g.left) - grid.clientLeft + grid.scrollLeft, py = zpx(y - g.top) - grid.clientTop + grid.scrollTop;
  let last = null;
  for (const el of dbTiles(grid)) {
    const r = { x: el.offsetLeft, y: el.offsetTop, w: el.offsetWidth, h: el.offsetHeight };
    if (px >= r.x && px < r.x + r.w && py >= r.y && py < r.y + r.h) return { el };
    if (!last || r.y + r.h > last) last = r.y + r.h;
  }
  return { el: null, below: last != null && py > last };
}

function dbDragMove(e) {
  const d = DB.drag;
  if (!d) return;
  d.x = e.clientX; d.y = e.clientY;
  if (!d.on) {
    if (Math.hypot(d.x - d.x0, d.y - d.y0) < DB_DRAG_PX) return;
    dbDragLift(d);
  }
  e.preventDefault();
  d.el.style.transform = `translate(${zpx(d.x - d.x0)}px, ${zpx(d.y - d.y0)}px) scale(1.02)`;
  if (!d.raf) d.raf = requestAnimationFrame(dbDragFrame);
}

function dbDragLift(d) {
  const grid = d.grid, el = d.el, r = el.getBoundingClientRect();
  d.on = true;
  const slot = document.createElement('div');
  slot.className = 'db-slot';
  slot.style.gridColumn = el.style.gridColumn;
  slot.style.height = `${zpx(r.height)}px`;
  el.after(slot);
  d.slot = slot;
  Object.assign(el.style, { left: `${zpx(r.left)}px`, top: `${zpx(r.top)}px`, width: `${zpx(r.width)}px`, height: `${zpx(r.height)}px` });
  el.classList.add('db-lifted');
  document.body.classList.add('db-dragging-now');
  try { grid.setPointerCapture(d.pid); } catch (err) {}
}

// One step a frame: the slot follows the pointer, the grid scrolls at its edges
function dbDragFrame() {
  const d = DB.drag;
  if (!d || !d.on) return;
  d.raf = 0;
  const grid = d.grid, g = grid.getBoundingClientRect();
  const step = d.y < g.top + DB_EDGE_PX ? -12 : d.y > g.bottom - DB_EDGE_PX ? 12 : 0;
  if (step && grid.scrollTop + step >= 0 && grid.scrollTop + step <= grid.scrollHeight - grid.clientHeight) {
    grid.scrollTop += step;
    d.raf = requestAnimationFrame(dbDragFrame);  // goes on while the pointer stays at the edge
  }
  const hit = dbHit(grid, d.x, d.y);
  const tiles = dbTiles(grid);
  if (hit.el && hit.el !== d.slot && hit.el !== d.over) {
    // over another widget: the slot takes its place, the widget steps aside (forward: after it, back: before)
    const forward = tiles.indexOf(hit.el) > tiles.indexOf(d.slot);
    dbFlip(grid, () => (forward ? hit.el.after(d.slot) : hit.el.before(d.slot)));
  } else if (!hit.el && hit.below && tiles[tiles.length - 1] !== d.slot) {
    dbFlip(grid, () => tiles[tiles.length - 1].after(d.slot));
  }
  // the same widget is not taken twice in a row: it moved, and would hand the slot back and forth
  d.over = hit.el === d.slot ? d.over : hit.el;
}

function dbDragEnd(e, cancel) {
  const d = DB.drag;
  if (!d) return;
  DB.drag = null;
  cancelAnimationFrame(d.raf);
  document.removeEventListener('pointermove', dbDragMove, true);
  document.removeEventListener('pointerup', dbDragUp, true);
  document.removeEventListener('pointercancel', dbDragCancel, true);
  document.removeEventListener('keydown', dbDragKey, true);
  if (!d.on) return;
  document.body.classList.remove('db-dragging-now');
  const order = cancel ? null : dbTiles(d.grid).map(x => (x === d.slot ? d.from : Number(x.dataset.i)));
  const done = () => {
    if (order && order.some((v, k) => v !== k)) {
      const layout = dbPrefs().layout;
      dbSave({ layout: order.map(k => layout[k]) });
    }
    renderDashboard();
  };
  if (cancel || scrollMotion() === 'auto') { done(); return; }
  // the widget settles into its slot, then the grid is drawn in the new order
  const to = d.slot.getBoundingClientRect(), from = d.el.getBoundingClientRect();
  d.el.style.transition = 'transform 140ms cubic-bezier(0.2, 0.7, 0.2, 1)';
  d.el.style.transform = `translate(${zpx(d.x - d.x0 + to.left - from.left)}px, ${zpx(d.y - d.y0 + to.top - from.top)}px)`;
  setTimeout(done, 140);
}
function dbDragUp(e) { dbDragEnd(e, false); }
function dbDragCancel(e) { dbDragEnd(e, true); }
function dbDragKey(e) { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); dbDragEnd(e, true); } }

(function wireDashboard() {
  const grid = document.getElementById('db-grid');
  if (!grid) return;
  grid.addEventListener('pointerdown', (e) => {
    if (!DB.edit || DB.drag || e.button !== 0) return;
    const w = e.target.closest && e.target.closest('.db-w');
    if (!w || w.parentElement !== grid || e.target.closest('button, a, input, select, textarea, label')) return;
    e.preventDefault();  // no text selected on the way
    DB.drag = { grid, el: w, from: Number(w.dataset.i), pid: e.pointerId, x0: e.clientX, y0: e.clientY, x: e.clientX, y: e.clientY, on: false, raf: 0 };
    document.addEventListener('pointermove', dbDragMove, true);
    document.addEventListener('pointerup', dbDragUp, true);
    document.addEventListener('pointercancel', dbDragCancel, true);
    document.addEventListener('keydown', dbDragKey, true);
  });
})();

// The time on the dashboard follows by itself (reported by the user: the «now» of the week and of the
// day froze, above all after the window was restored from the tray or the taskbar). Every 30 s while it is
// seen, and at once when the window comes back: the week's widget is redrawn from what is loaded (no
// request), the day's meetings by home.js; a new day loads its week and numbers again. The open calendar
// window follows too (its past meetings and today)
let _dbDay = new Date().toDateString();
function dbTickNow() {
  if (document.hidden) return;
  if (document.getElementById('cal-view') && typeof renderCalendarView === 'function') renderCalendarView();
  if (state.appView !== 'dashboard') return;
  const day = new Date().toDateString();
  if (day !== _dbDay) { _dbDay = day; loadDashboard(); }
  else if (!DB.at && dbPrefs().layout.some(w => w.id === 'worked')) dbLoadWork().then(() => { if (!DB.edit && !DB.drag && state.appView === 'dashboard') dbRedrawWidget('worked'); });
  if (!DB.edit && !DB.drag) {
    dbPrefs().layout.forEach((w, i) => {
      if (!DB_TIME_WIDGETS.includes(w.id)) return;
      const c = document.querySelector(`#db-grid .db-w[data-i="${i}"] .db-c`);
      if (c) c.innerHTML = dbWidgetHtml(w.id, dbSize(w));
    });
  }
  dbRenderHead();
}
setInterval(dbTickNow, 30000);
document.addEventListener('visibilitychange', dbTickNow);
window.addEventListener('focus', dbTickNow);

registerView('dashboard', {
  show: () => {
    renderDashboard();
    // the widgets come in one after another as «Обзор» opens (not on every redraw)
    const grid = document.getElementById('db-grid');
    if (grid) {
      DB.waveAt = performance.now();
      dbWaveDelays(grid);
      grid.classList.remove('db-wave'); void grid.offsetWidth; grid.classList.add('db-wave');
      clearTimeout(DB.waveTimer);
      DB.waveTimer = setTimeout(() => grid.classList.remove('db-wave'), 1000);
    }
    loadDashboard();
    if (dbPrefs().layout.some(w => w.id === 'sysload') && typeof scheduleVramRefresh === 'function') scheduleVramRefresh(50);
  },
  hide: () => { DB.edit = false; DB.kpiCfg = false; },
  refresh: (changed) => { if (changed) loadDashboard(); },
});
