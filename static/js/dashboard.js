// Verbaliox page script: «Дэшборд» (static/parts/dashboard.html), the first page of the app. Widgets the user
// arranges («Настроить»: dragged, sized S · M · L · W, removed, added from the list), kept on this computer.
// The data widgets read /api/dashboard (app/dashboard.py) for the period and the feature chosen; the week reads
// /api/calendar/range. The day of the former home page (its greeting, the meetings of today with their
// auto-recording, the latest recordings, what is being processed) lives here too: its blocks are moved in
// from static/parts/home.html and drawn by static/js/home.js as before.
// The parts are classic scripts sharing one global scope, loaded in order by index.html.

const DB_KEY = 'vx-dashboard';
// of 12 columns: two M, an S and an L, three S fill a row (reported by the user: M and M left a hole)
const DB_SIZES = { S: 4, M: 6, L: 8, W: 12 };
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
  // asked by the user («давай делать все»): the next meeting's prep, what is due today, the free time of
  // the day, the load of the week, the series giving nothing
  prep: { title: 'dbPrep', sizes: ['S', 'M', 'L', 'W'], icon: '◎' },
  due: { title: 'dbDue', sizes: ['S', 'M', 'L', 'W'], icon: '!' },
  free: { title: 'dbFree', sizes: ['S', 'M', 'L'], icon: '◌' },
  load: { title: 'dbLoad', sizes: ['S', 'M', 'L', 'W'], icon: '▥' },
  dull: { title: 'dbDull', sizes: ['S', 'M', 'L', 'W'], icon: '↻' },
  // asked by the user: how long the working day lasted (app/worktime.py), against the norm
  worked: { title: 'dbWorked', sizes: ['S', 'M', 'L', 'W'], icon: '⏱' },
};
// rows that add up to 12: W · M+M · M+M · M+M · S+L · L+S · S+S+S · M+M
const DB_DEFAULT = [['kpis', 'W'], ['today', 'M'], ['week', 'M'], ['prep', 'M'], ['due', 'M'], ['mytasks', 'M'], ['waiting', 'M'],
  ['free', 'S'], ['load', 'L'], ['features', 'L'], ['time', 'S'], ['people', 'S'], ['decisions', 'S'], ['dull', 'S'],
  ['summary', 'M'], ['recent', 'M']];
const DB_PERIODS = ['week', 'month', 'quarter'];
// added after the first dashboard: offered once to an existing layout, after the widget named (removed by
// the user, it stays out)
const DB_NEW_WIDGETS = [['waiting', 'mytasks'], ['prep', 'week'], ['due', 'prep'], ['free', 'waiting'], ['load', 'free'], ['dull', 'decisions'], ['worked', 'kpis']];

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
  const q = `period=${p.period}${p.feature ? `&feature=${p.feature}` : ''}&lang=${state.uiLang === 'en' ? 'en' : 'ru'}`;
  const [data, week, untx] = await Promise.all([
    fetch(`/api/dashboard?${q}`).then(r => (r.ok ? r.json() : null)).catch(() => null),
    dbLoadWeek(),
    fetch('/api/untranscribed').then(r => (r.ok ? r.json() : null)).catch(() => null),
    dbLoadWork(),
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

// The hours worked of this week (app/worktime.py): asked again at each tick, the minutes go on
async function dbLoadWork() {
  const a = dbMonday(), b = new Date(a);
  b.setDate(a.getDate() + 7);
  const w = await fetch(`/api/worktime?start=${calKey(a)}&end=${calKey(b)}`).then(r => (r.ok ? r.json() : null)).catch(() => null);
  if (w) DB.work = w;
}

// «7 ч 45» for a day's head: the hours worked, short
function dbWorkedShort(min) {
  return min ? `${Math.floor(min / 60)}:${String(min % 60).padStart(2, '0')}` : '';
}

async function dbLoadWeek() {
  const a = dbMonday(), b = new Date(a);
  b.setDate(a.getDate() + 7);
  return fetch(`/api/calendar/range?start=${encodeURIComponent(hmIso(a))}&end=${encodeURIComponent(hmIso(b))}&lang=${state.uiLang === 'en' ? 'en' : 'ru'}`)
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
  // How far the period is (asked by the user: «сколько дней прошло»): a bar and «Прошло 4 дня из 7»
  const prog = document.getElementById('db-progress');
  if (prog) {
    prog.classList.toggle('hidden', !d);
    if (d) {
      // calendar days, or working days (Monday to Friday) as the user chose with the gear (asked by the user);
      // a public holiday of the country chosen in the settings is no working day
      const work = dbPrefs().days === 'work', hol = d.holidays || {};
      const a = new Date(`${d.start}T00:00:00`), b = new Date(`${d.end}T00:00:00`), now = new Date();
      const days = [];
      for (let x = new Date(a); x < b; x.setDate(x.getDate() + 1)) if (!work || ((x.getDay() + 6) % 7 < 5 && !hol[calKey(x)])) days.push(new Date(x));
      const all = days.length;
      const done = days.filter(x => x.getTime() + 864e5 <= now.getTime()).length;  // the days over
      const today = days.find(x => x <= now && now < new Date(x.getTime() + 864e5));
      const pct = all ? Math.max(0, Math.min(100, (done + (today ? (now - today) / 864e5 : 0)) / all * 100)) : 0;
      const label = t(work ? 'dbPeriodProgressWork' : 'dbPeriodProgress').replace('{done}', () => plural(done, t(work ? 'dbWorkDayForms' : 'dbDayForms'))).replace('{all}', () => all);
      prog.innerHTML = `<i class="db-progress-bar"><i style="width:${pct.toFixed(1)}%"></i></i><span>${escapeHtml(label)}</span>`
        + `<button class="db-prog-cfg" data-click="dbProgressMenu" data-click-args='[{"$": "el"}]' title="${escapeHtml(t('dbDaysTip'))}" aria-label="${escapeHtml(t('dbDaysTip'))}">`
        + '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg></button>';
      prog.setAttribute('aria-label', label);
    }
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

// the gear of the period's progress: calendar or working days
function dbProgressMenu(el) {
  const r = el.getBoundingClientRect(), cur = dbPrefs().days === 'work' ? 'work' : 'cal';
  const pick = days => { dbSave({ days }); dbRenderHead(); };
  setTimeout(() => openTextMenuAt([
    { label: `${cur === 'cal' ? '✓ ' : '   '}${t('dbDaysCal')}`, run: () => pick('cal') },
    { label: `${cur === 'work' ? '✓ ' : '   '}${t('dbDaysWork')}`, run: () => pick('work') },
  ], r.left, r.bottom + 6), 0);
}

function dbNum(n) { return String(n); }  // a point for fractions in both languages (asked by the user)

// --- The day's time: the next meeting, the free windows, the load of the week (asked by the user) ---
// They read the calendar of today (home.events, static/js/home.js) and of the week (DB.week): no request
const DB_LOCAL_WIDGETS = ['week', 'prep', 'free', 'load', 'worked'];
const DB_TIME_WIDGETS = ['week', 'prep', 'free', 'load', 'worked'];  // redrawn as the time goes (dbTickNow)

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

// On the line of «now» of the week: « · через 12 мин» to the next meeting of today, « · идёт» during one
function dbNextIn() {
  const e = dbNextMeeting();
  if (!e) return '';
  const now = Date.now();
  // short: the pill stands on a narrow day column
  return `<span class="db-now-next"> → ${escapeHtml(e.s.getTime() <= now ? t('dbNowLive') : dbHm((e.s.getTime() - now) / 1000))}</span>`;
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

// «Горит сегодня»: the tasks due today or overdue, mine and those promised to me, overdue first
function dbDueHtml(d, size) {
  if (d.needs_me) return `<div class="db-note">${escapeHtml(t('dbNeedsMe'))} <button class="db-more" data-click="hmSetMyName">${escapeHtml(t('dbSetMe'))}</button></div>`;
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

// «Нагрузка недели»: the hours of meetings of each day of the week against the user's norm (a click on
// the norm changes it: 2–6 h, kept on this computer). The calendar's meetings, or the recordings without one
function dbLoadHtml() {
  const w = DB.week;
  if (!w) return `<div class="db-note">${escapeHtml(t(DB.loading ? 'dbLoading' : 'dbNoData'))}</div>`;
  const a = dbMonday(), lang = state.uiLang === 'en' ? 'en-US' : 'ru-RU', today = calKey(new Date());
  const norm = dbPrefs().norm;
  const days = [];
  for (let i = 0; i < 7; i++) {
    const x = new Date(a); x.setDate(a.getDate() + i);
    const k = calKey(x);
    const spans = [...(w.events || []).filter(e => !e.all_day && !hmIsIgnored(e)).map(e => [new Date(e.start).getTime(), new Date(e.end || e.start).getTime()])
        .filter(([a, b]) => b - a < DB_BLOCK_MS),  // a night or a day off is not hours of meetings
      ...(w.recordings || []).map(r => [new Date(r.at).getTime(), new Date(r.at).getTime() + (r.duration || 0) * 1000])]
      .filter(([s]) => calKey(new Date(s)) === k);
    const hours = dbMerge(spans).reduce((sum, [s, e]) => sum + (e - s), 0) / 3600e3;
    if (i < 5 || hours) days.push({ x, k, hours, hol: (w.holidays || {})[k] || '' });
  }
  const top = Math.max(norm * 1.5, ...days.map(d => d.hours));
  const sum = days.reduce((s, d) => s + d.hours, 0);
  return `<div class="db-load-head">${escapeHtml(t('dbLoadSum').replace('{h}', () => dbNum(Math.round(sum * 10) / 10)))}`
    + `<button class="db-more" data-click="dbCycleNorm" title="${escapeHtml(t('dbNormTip'))}">${escapeHtml(t('dbNorm').replace('{h}', () => norm))}</button></div>`
    + `<div class="db-load"><i class="db-load-norm" style="bottom:${Math.round(norm / top * 100)}%"></i>` + days.map(d => {
      const over = d.hours > norm;
      return `<div class="db-load-day${d.k === today ? ' today' : ''}${d.k < today ? ' past' : ''}${d.hol ? ' hol' : ''}" title="${escapeHtml(`${d.x.toLocaleDateString(lang, { weekday: 'long', day: 'numeric', month: 'short' })}: ${dbNum(Math.round(d.hours * 10) / 10)} ${t('dbHoursShort')}${d.hol ? ` · ${d.hol}` : ''}`)}">`
        + `<span class="db-load-v">${d.hours ? dbNum(Math.round(d.hours * 10) / 10) : ''}</span>`
        + `<i class="db-load-bar${over ? ' over' : ''}" style="height:${Math.round(d.hours / top * 100)}%"></i>`
        + `<span class="db-load-d">${escapeHtml(d.x.toLocaleDateString(lang, { weekday: 'short' }))}</span></div>`;
    }).join('') + '</div>';
}

// «Рабочий день»: the hours worked today against the norm (the reminder's hours), when it began, the breaks,
// and the days of the week (app/worktime.py: the minutes this computer was in use)
function dbWorkedHtml(size) {
  const w = DB.work;
  if (!w) return `<div class="db-note">${escapeHtml(t(DB.loading ? 'dbLoading' : 'dbNoData'))}</div>`;
  if (!w.supported) return `<div class="db-note">${escapeHtml(t('dbWorkedNoSupport'))}</div>`;
  if (!w.enabled) return `<div class="db-note">${escapeHtml(t('dbWorkedOff'))} <button class="db-more" data-click="openWorkSettings">${escapeHtml(t('newsOpenSettings'))}</button></div>`;
  const today = w.days[w.today] || { worked: 0, start: '', end: '', breaks: 0 };
  const norm = (w.norm || 8) * 60, pct = Math.min(100, today.worked / norm * 100);
  const over = today.worked >= norm;
  let html = `<div class="db-wk-head"><b class="db-wk-big${over ? ' over' : ''}">${escapeHtml(dbHm(today.worked * 60))}</b>`
    + `<span class="db-wk-of">${escapeHtml(t('dbWorkedOf').replace('{h}', () => dbNum(w.norm || 8)))}</span></div>`
    + `<div class="db-wk-bar${over ? ' over' : ''}"><i style="width:${pct.toFixed(1)}%"></i></div>`
    + `<div class="db-wk-sub">${escapeHtml(today.start ? [t('dbWorkedSince').replace('{t}', () => today.start), today.breaks >= 15 ? t('dbWorkedBreaks').replace('{t}', () => dbHm(today.breaks * 60)) : ''].filter(Boolean).join(' · ') : t('dbWorkedNone'))}</div>`;
  if (size !== 'S') {
    const a = dbMonday(), lang = state.uiLang === 'en' ? 'en-US' : 'ru-RU';
    const days = [];
    for (let i = 0; i < 7; i++) {
      const x = new Date(a); x.setDate(a.getDate() + i);
      const k = calKey(x), d = w.days[k];
      if (i < 5 || d) days.push({ x, k, min: d ? d.worked : 0, d });
    }
    const top = Math.max(norm * 1.25, ...days.map(d => d.min));
    const sum = days.reduce((s, d) => s + d.min, 0);
    html += `<div class="db-load-head">${escapeHtml(t('dbWorkedWeek').replace('{t}', () => dbHm(sum * 60)))}</div>`
      + `<div class="db-load db-wk-week"><i class="db-load-norm" style="bottom:${Math.round(norm / top * 100)}%"></i>` + days.map(d =>
        `<div class="db-load-day${d.k === w.today ? ' today' : ''}${d.k < w.today ? ' past' : ''}" title="${escapeHtml(`${d.x.toLocaleDateString(lang, { weekday: 'long', day: 'numeric', month: 'short' })}: ${dbHm(d.min * 60)}${d.d && d.d.start ? ` (${d.d.start}–${d.d.end})` : ''}`)}">`
        + `<span class="db-load-v">${escapeHtml(dbWorkedShort(d.min))}</span>`
        + `<i class="db-load-bar${d.min > norm ? ' over' : ''}" style="height:${Math.round(d.min / top * 100)}%"></i>`
        + `<span class="db-load-d">${escapeHtml(d.x.toLocaleDateString(lang, { weekday: 'short' }))}</span></div>`).join('') + '</div>';
  }
  return html;
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

// «Серии без отдачи»: series whose last meetings, three or more in a row, gave no decision and no task
// (app/dashboard._dull_series); a click opens the latest one
function dbDullHtml(d) {
  const list = d.dull_series || [];
  if (!list.length) return `<div class="db-note db-ok">${escapeHtml(t('dbDullNone'))}</div>`;
  return list.map(x => `<button class="db-dull" data-click="openMeeting" data-click-args='[${Number(x.last.id)}]' title="${escapeHtml(t('dbDullTip'))}">`
    + `<span class="db-dull-name">${escapeHtml(x.name)}</span>`
    + `<span class="db-dull-sub">${escapeHtml(t('dbDullStreak').replace('{n}', () => x.streak).replace('{h}', () => dbNum(x.hours)))}</span></button>`).join('');
}

function dbWidgetHtml(id, size) {
  const d = DB.data;
  if (!d && !DB_LOCAL_WIDGETS.includes(id)) return `<div class="db-note">${escapeHtml(t(DB.loading ? 'dbLoading' : 'dbNoData'))}</div>`;
  switch (id) {
    case 'kpis': return dbKpis(d);
    case 'week': return dbWeek();
    case 'prep': return dbPrepHtml(size);
    case 'due': return dbDueHtml(d, size);
    case 'free': return dbFreeHtml();
    case 'load': return dbLoadHtml();
    case 'worked': return dbWorkedHtml(size);
    case 'dull': return dbDullHtml(d);
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
      + `<span class="db-tm">${pad(it.at.getHours())}:${pad(it.at.getMinutes())}</span> <span class="db-ev-t">${escapeHtml(it.title)}</span>${live ? `<i class="db-ev-prog" style="width:${pct}%"></i>` : ''}</button>`;
  };
  const nowDate = new Date(now);
  return `<div class="db-cal" style="grid-template-columns:repeat(${shown.length}, minmax(0, 1fr))">` + shown.map(x => {
    const k = calKey(x), list = (items[k] || []).sort((p, q) => p.at - q.at);
    const hol = (w.holidays || {})[k];
    const wk = DB.work && DB.work.enabled && DB.work.days[k] ? DB.work.days[k].worked : 0;  // the hours worked that day (app/worktime.py)
    const head = `<div class="db-dn${hol ? ' hol' : ''}"${hol ? ` title="${escapeHtml(hol)}"` : ''}><b>${x.getDate()}</b>${escapeHtml(x.toLocaleDateString(lang, { weekday: 'short' }))}`
      + (wk ? `<span class="db-dn-wk" title="${escapeHtml(t('dbWorkedTip').replace('{t}', () => dbHm(wk * 60)))}">${escapeHtml(dbWorkedShort(wk))}</span>` : '') + '</div>'
      + (hol ? `<div class="db-hol">${escapeHtml(hol)}</div>` : '');
    // The time already past is filled (asked by the user): a day before today whole; today down to the
    // line of "now", which stands after the last thing already begun, never over a card
    if (k === today) {
      const begun = list.filter(it => it.at.getTime() <= now), ahead = list.filter(it => it.at.getTime() > now);
      return `<div class="db-day today${hol ? ' db-day-off' : ''}"><div class="db-past">${head}${begun.map(item).join('')}</div>`
        + `<div class="db-now"><b>${pad(nowDate.getHours())}:${pad(nowDate.getMinutes())}${dbNextIn()}</b></div>${ahead.map(item).join('')}</div>`;
    }
    return `<div class="db-day${k < today ? ' db-day-past' : ''}${hol ? ' db-day-off' : ''}">${head}${list.map(item).join('')}</div>`;
  }).join('') + '</div>';
}

function dbFeatures(d, size) {
  if (!d.features.length) return `<div class="db-note">${escapeHtml(t('dbNoFeatures'))}</div>`;
  const n = size === 'M' ? 2 : size === 'W' ? 6 : 4;
  return `<div class="db-feats">` + d.features.slice(0, n).map(f => {
    const c = /^#[0-9A-Fa-f]{6}$/.test(f.color || '') ? f.color : '#8E8E93';
    const max = Math.max(1, ...f.spark);
    // a click opens the feature's card (asked by the user); the filter of «Главная» is in «Все фичи ▾»
    return `<button class="db-feat" style="--ft:${c}" data-click="openFeaturePage" data-click-args='[${f.id}]' title="${escapeHtml(t('dbFeatureOpenTip').replace('{name}', () => f.name))}">`
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
  const cur = p.feature ? featureById(p.feature) : null;
  openTextMenuAt([...(cur ? [{ label: `↗  ${t('dbFeatureCard').replace('{name}', () => cur.name)}`, run: () => openFeaturePage(cur.id) }, { sep: true }] : []),
    { label: tick(!p.feature, t('dbAllFeatures')), run: () => setDashFeature(0) }, { sep: true },
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
      : `<div class="db-note">${escapeHtml(t(DB_DETAIL.filter === 'useless' ? 'dbUselessNone' : 'dbNoMeetingsYet'))}</div>`);
}

function dbDetailTasks(list, today, mine) {
  if (!list.length) return `<div class="db-note">${escapeHtml(t(mine ? 'dbNoMyTasks' : 'dbNoWaiting'))}</div>`;
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
    }).join('') : `<div class="db-note">${escapeHtml(t('dbNoDecisionsYet'))}</div>`;
  } else if (kind === 'tasks' || kind === 'waiting') {
    body = d.needs_me ? `<div class="db-note">${escapeHtml(t('dbNeedsMe'))}</div>` : dbDetailTasks(d.tasks, today, kind === 'tasks');
  } else {  // a person
    body = `<div class="db-dt-sec">${escapeHtml(t('dbDtOwesMe'))}</div>${dbDetailTasks(d.owes_me || [], today, false)}`
      + `<div class="db-dt-sec">${escapeHtml(t('dbDtIOwe'))}</div>${dbDetailTasks(d.i_owe || [], today, true)}`
      + `<div class="db-dt-sec">${escapeHtml(t('dbDtTheirMeetings').replace('{n}', () => d.meetings_total || 0))}</div>`
      + ((d.meetings || []).map(m => `<button class="db-dt-row db-dt-row2" data-click="dashOpenSummary" data-click-args='[${m.id}]'>`
        + `<span class="db-dt-main"><b class="db-dt-one">${escapeHtml(m.title || t('hmUntitled'))}</b><small><span>${escapeHtml(dbAgo(m.date, today))}</span></small></span><span class="db-dt-dur">${escapeHtml(dbHm(m.duration))}</span></button>`).join('')
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
  else if (dbPrefs().layout.some(w => w.id === 'worked')) dbLoadWork().then(() => {
    dbPrefs().layout.forEach((w, i) => {
      if (w.id !== 'worked' || DB.edit || DB.drag) return;
      const c = document.querySelector(`#db-grid .db-w[data-i="${i}"] .db-c`);
      if (c) c.innerHTML = dbWidgetHtml(w.id, dbSize(w));
    });
  });
  if (!DB.edit && !DB.drag) {
    dbPrefs().layout.forEach((w, i) => {
      if (!DB_TIME_WIDGETS.includes(w.id)) return;
      const c = document.querySelector(`#db-grid .db-w[data-i="${i}"] .db-c`);
      if (c) c.innerHTML = dbWidgetHtml(w.id, dbSize(w));
    });
  }
  dbRenderHead();
  if (typeof renderHomeNow === 'function') renderHomeNow();
}
setInterval(dbTickNow, 30000);
document.addEventListener('visibilitychange', dbTickNow);
window.addEventListener('focus', dbTickNow);

registerView('dashboard', {
  show: () => {
    // the greeting and the date of the former home page in the head of the dashboard
    const hello = document.querySelector('#home-view .hm-hello'), slot = document.getElementById('db-hello');
    if (hello && slot && !slot.contains(hello)) slot.appendChild(hello);
    const qa = document.querySelector('#home-view .hm-head > .flex'), qslot = document.getElementById('db-qa');
    if (qa && qslot && !qslot.contains(qa)) qslot.appendChild(qa);
    renderDashboard();
    // the widgets come in one after another as Главная opens (not on every redraw)
    const grid = document.getElementById('db-grid');
    if (grid) {
      grid.querySelectorAll(':scope > .db-w').forEach((w, i) => { w.style.animationDelay = `${Math.min(i, 12) * 40}ms`; });
      grid.classList.remove('db-wave'); void grid.offsetWidth; grid.classList.add('db-wave');
      clearTimeout(DB.waveTimer);
      DB.waveTimer = setTimeout(() => grid.classList.remove('db-wave'), 1000);
    }
    if (typeof renderHome === 'function') renderHome();
    loadDashboard();
  },
  hide: () => { DB.edit = false; },
  refresh: (changed) => { if (changed) loadDashboard(); if (typeof renderHome === 'function') renderHome(); },
});
