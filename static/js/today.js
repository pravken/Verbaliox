// Verbaliox page script: «Сегодня» (static/parts/home.html; docs/pult-plan.md, stage 3), the first page of the app.
// The head: the date as a calendar sheet, the period shown and its figures in pills that fill as it goes, and
// «Календарь» День · Неделя · Месяц (kept with the dashboard's settings, dbPrefs().span). The day shows the
// meetings of the working day (drawn by static/js/home.js) with the cards of the day on the right: «Перед
// встречей», «Срочные задачи», «Рабочий день», «Свободное время», «Ожидаю от других»; a week or a month shows
// the calendar over the width (calBodyHtml, the same as the calendar window) and the cards in a row under it.
// The cards are drawn by the functions of static/js/dashboard.js, from /api/dashboard of this week (no feature
// filter: the filter belongs to «Обзор»). The parts are classic scripts sharing one global scope.

// cal.anchor: the day shown (null: today), kept across День · Неделя · Месяц; dayTip: a click on a day opens it
const TD = { data: null, seq: 0, shownAt: 0, cal: { mode: 'week', anchor: null, data: null, work: {}, loading: false, seq: 0, dayTip: 'calOpenDay' } };
const TD_SPANS = ['day', 'week', 'month'];
const TD_GROW_MS = 1200;  // «Рабочий день»: the bar fills from zero this long, once, as the page opens

function tdSpan() { return TD_SPANS.includes(dbPrefs().span) ? dbPrefs().span : 'day'; }

// the span changes, the day shown stays: a week or a month shows the week or the month of that day
function tdSetSpan(span) {
  if (!TD_SPANS.includes(span)) return;
  dbSave({ span });
  if (span !== 'day') tdCalLoad(); else renderHome();
}

// A day of the week or the month opens in «День» (YYYY-MM-DDTHH:MM); today's date is today's working day
function tdOpenDay(day) {
  const x = new Date(day);
  if (Number.isNaN(x.getTime())) return;
  TD.cal.anchor = calKey(x) === calKey(new Date()) ? null : x;
  dbSave({ span: 'day' });
  renderHome();
}

// ‹ Сегодня ›: the day, the week or the month before, this one, the one after
function tdNav(k) {
  const cv = TD.cal;
  if (!k) cv.anchor = null;
  else if (tdSpan() === 'day') {
    const x = calDayStart(hmViewDate() || hmDay().from);  // today: from the date its working day began (a night shift)
    x.setDate(x.getDate() + k);
    x.setHours(12);
    cv.anchor = calKey(x) === calKey(hmDay().from) ? null : x;
  } else {
    const x = new Date(cv.anchor || new Date());
    if (cv.mode === 'week') x.setDate(x.getDate() + 7 * k); else { x.setDate(1); x.setMonth(x.getMonth() + k); }
    cv.anchor = x;
  }
  if (tdSpan() === 'day') { renderHome(); return; }
  tdCalLoad();
}

// --- Data ---
async function tdLoad() {
  const seq = ++TD.seq;
  const lang = state.uiLang === 'en' ? 'en' : 'ru';
  const [data, week, untx] = await Promise.all([
    fetch(`/api/dashboard?period=week&lang=${lang}`).then(r => (r.ok ? r.json() : null)).catch(() => null),
    dbLoadWeek(),
    fetch('/api/untranscribed').then(r => (r.ok ? r.json() : null)).catch(() => null),
    dbLoadWork(),
  ]);
  if (seq !== TD.seq) return;
  if (data) TD.data = data;
  if (week) DB.week = week;
  if (untx) DB.untx = untx.items || [];
  if (state.appView === 'home') tdRender();
}

// The week or the month shown: the calendar's meetings, the recordings and the hours worked
async function tdCalLoad() {
  const cv = TD.cal;
  cv.mode = tdSpan();
  if (cv.mode === 'day') { tdRender(); return; }
  const { a, b } = calRange(cv);
  const seq = ++cv.seq;
  cv.loading = true;
  tdRender();
  const [data, work] = await Promise.all([
    fetch(`/api/calendar/range?start=${encodeURIComponent(hmIso(a))}&end=${encodeURIComponent(hmIso(b))}&lang=${state.uiLang === 'en' ? 'en' : 'ru'}`)
      .then(r => (r.ok ? r.json() : null)).catch(() => null),
    fetch(`/api/worktime?start=${calKey(a)}&end=${calKey(b)}`).then(r => (r.ok ? r.json() : null)).catch(() => null),
  ]);
  if (seq !== cv.seq) return;
  cv.loading = false;
  cv.data = data;
  cv.work = work && work.enabled ? work.days : {};
  tdRender();
}

// --- The head ---
function tdIsoWeek(d) {
  const x = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  x.setUTCDate(x.getUTCDate() + 4 - (x.getUTCDay() || 7));
  return Math.ceil(((x - Date.UTC(x.getUTCFullYear(), 0, 1)) / 864e5 + 1) / 7);
}

// The meetings of a list of calendar events that count (not all day, not a block of six hours, not marked
// «не встреча»), and the recordings made outside any meeting
function tdMeetings(events, recordings) {
  const ms = (events || []).filter(e => !e.all_day && !hmIsIgnored(e)).map(e => ({ s: new Date(e.start || e.s), e: new Date(e.end || e.e || e.start) }))
    .filter(x => x.e - x.s < DB_BLOCK_MS && x.e > x.s);
  for (const r of recordings || []) ms.push({ s: new Date(r.at), e: new Date(new Date(r.at).getTime() + (r.duration || 0) * 1000) });
  return ms;
}

// A pill: its text, and when given how much of it has passed (it fills) with what the fill means
function tdPill(text, part, tip) {
  const fill = part == null ? '' : ` td-pill-fill" style="--p:${Math.round(Math.max(0, Math.min(1, part)) * 100)}%`;
  return `<span class="td-pill${fill}"${tip ? ` title="${escapeHtml(tip)}"` : ''}>${escapeHtml(text)}</span>`;
}

function tdPillsHtml(span) {
  const now = Date.now();
  const h1 = x => dbNum(Math.round(x * 10) / 10);
  const meetPills = list => {
    if (!list.length) return [tdPill(t('tdNoMeetings'))];
    const total = list.reduce((s, m) => s + (m.e - m.s), 0) / 3600e3;
    const part = m => Math.max(0, Math.min(1, (now - m.s) / (m.e - m.s)));
    const done = list.reduce((s, m) => s + part(m), 0), ended = list.filter(m => m.e <= now).length;
    const spent = list.reduce((s, m) => s + part(m) * (m.e - m.s), 0) / 3600e3;
    return [tdPill(plural(list.length, t('dbMeetingForms')), done / list.length, t('tdPillPassed').replace('{a}', () => ended).replace('{n}', () => list.length)),
      tdPill(t('tdPillHours').replace('{h}', () => h1(total)), total ? spent / total : 0, t('tdPillHoursTip').replace('{a}', () => h1(spent)).replace('{b}', () => h1(total)))];
  };
  const pills = [];
  let worked = 0;
  const view = span === 'day' ? hmViewDate() : null;
  // the day: what its view shows (hmDayShown, static/js/home.js), so the head and the day agree
  const dayPills = () => {
    const shown = hmDayShown(view);
    if (home.calConfigured) pills.push(...meetPills(shown.real));
    else pills.push(tdPill(shown.recs.length ? plural(shown.recs.length, t('tdRecForms')) : t('tdNoRecordings')));
  };
  if (view) {  // another day: its meetings and its hours worked (home.days, static/js/home.js)
    const other = home.days[calKey(hmDay(view).from)];
    if (!other) return '';
    dayPills();
    worked = other.worked || 0;
  } else if (span === 'day') {
    dayPills();
    const w = DB.work;
    worked = w && w.enabled && w.days[w.today] ? w.days[w.today].worked : 0;
  } else {
    const d = TD.cal.data;
    if (!d) return '';
    pills.push(...meetPills(tdMeetings(d.events, (d.recordings || []))));
    worked = Object.values(TD.cal.work || {}).reduce((s, x) => s + (x.worked || 0), 0);
  }
  if (worked) pills.push(tdPill(t('tdPillWorked').replace('{t}', () => dbHm(worked * 60))));
  return pills.join('');
}

function tdRenderHead(span) {
  const now = new Date(), loc = hmLocale(), cv = TD.cal;
  const at = span === 'day' ? now : new Date(cv.anchor || now);
  const set = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };
  const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
  const view = span === 'day' ? hmViewDate() : null;
  if (view) {  // another day: «Вт, 24 ноября» and its year
    const day = hmDay(view).from, wd = day.toLocaleDateString(loc, { weekday: 'short' }).replace('.', '');
    set('td-tile-k', wd);
    set('td-tile-n', String(day.getDate()));
    set('td-title', `${cap(wd)}, ${day.toLocaleDateString(loc, { day: 'numeric', month: 'long' })}`);
    set('td-sub', String(day.getFullYear()));
  } else if (span === 'day') {
    set('td-tile-k', now.toLocaleDateString(loc, { weekday: 'short' }).replace('.', ''));
    set('td-tile-n', String(now.getDate()));
    set('td-title', t('tdToday'));
    set('td-sub', now.toLocaleDateString(loc, { weekday: 'long', day: 'numeric', month: 'long' }));
  } else if (span === 'week') {
    set('td-tile-k', t('tdWeekShort'));
    set('td-tile-n', String(tdIsoWeek(calRange(cv).a)));
    set('td-title', t('tdSpan_week'));
    set('td-sub', calLabel(cv));
  } else {
    set('td-tile-k', t('tdMonthShort'));
    set('td-tile-n', String(at.getMonth() + 1));
    set('td-title', cap(at.toLocaleDateString(loc, { month: 'long' })));
    set('td-sub', String(at.getFullYear()));
  }
  document.getElementById('td-tile')?.classList.toggle('td-tile-word', span !== 'day');
  // today has a green frame: while stepping through the days, today is seen at once (asked by the user)
  document.getElementById('td-tile')?.classList.toggle('td-tile-today', span === 'day' && !view);
  const pills = document.getElementById('td-pills');
  if (pills) pills.innerHTML = tdPillsHtml(span);
  document.getElementById('td-nav')?.classList.remove('hidden');  // the day steps by a day, the week and the month by theirs
  const seg = document.getElementById('td-spans');
  if (seg) seg.innerHTML = TD_SPANS.map(k => `<button role="radio" aria-checked="${span === k}" class="tk-seg-btn${span === k ? ' tk-on' : ''}" data-click="tdSetSpan" data-click-args='["${k}"]'>${escapeHtml(t(`tdSpan_${k}`))}</button>`).join('');
}

// --- The cards of the day ---
function tdCard(id, title, body, extra = '') {
  return `<section class="hm-card td-card td-card-${id}"><div class="hm-card-head"><h2>${escapeHtml(title)}</h2><span class="flex-1"></span>${extra}</div><div class="td-card-body">${body}</div></section>`;
}

// «Рабочий день»: the hours worked today against the norm. The bar fills from zero once as the page opens (each
// redraw goes on from where the fill is), a soft light runs along it and its end glows while the day is counted
function tdWorkedHtml() {
  const w = DB.work;
  if (!w) return `<div class="db-note">${escapeHtml(t('dbLoading'))}</div>`;
  if (!w.supported) return `<div class="db-note">${escapeHtml(t('dbWorkedNoSupport'))}</div>`;
  if (!w.enabled) return `<div class="db-note">${escapeHtml(t('dbWorkedOff'))} <button class="db-more" data-click="openWorkSettings">${escapeHtml(t('newsOpenSettings'))}</button></div>`;
  const day = w.days[w.today] || { worked: 0, start: '', breaks: 0 };
  const norm = (w.norm || 8) * 60, pct = Math.min(100, day.worked / norm * 100), over = day.worked >= norm;
  const gone = performance.now() - TD.shownAt, grow = gone < TD_GROW_MS && scrollMotion() !== 'auto';
  // the animations go on from where they are: the fill (once) and the light (from 1.2 s on, again and again)
  const delays = grow ? `animation-delay:${Math.round(-gone)}ms, ${Math.round(TD_GROW_MS - gone)}ms;` : '';
  const sub = day.start ? [t('dbWorkedSince').replace('{t}', () => day.start), day.breaks >= 15 ? t('dbWorkedBreaks').replace('{t}', () => dbHm(day.breaks * 60)) : ''].filter(Boolean).join(' · ') : t('dbWorkedNone');
  let remind = '';
  if (w.norm > 0 && !over && day.worked > 0) {
    const at = new Date(Date.now() + (norm - day.worked) * 60e3);
    remind = `<div class="td-wd-note">${escapeHtml(t('tdNormAt').replace('{t}', () => `${hmPad(at.getHours())}:${hmPad(at.getMinutes())}`))}</div>`;
  }
  return `<div class="td-wd-head"><b class="td-wd-big${over ? ' over' : ''}">${escapeHtml(dbHm(day.worked * 60))}</b><span class="td-wd-sub">${escapeHtml(sub)}</span></div>`
    + `<div class="td-wd${day.worked ? ' live' : ''}${over ? ' over' : ''}" role="img" aria-label="${escapeHtml(`${dbHm(day.worked * 60)} ${t('dbWorkedOf').replace('{h}', () => dbNum(w.norm || 8))}`)}">`
    + `<i class="${grow ? 'grow' : ''}" style="width:${pct.toFixed(1)}%;${delays}"></i></div>`
    + remind;
}

function tdCardsHtml() {
  const d = TD.data, cards = [];
  const note = key => `<div class="db-note">${escapeHtml(t(key))}</div>`;
  const allTasks = `<button class="hm-link" data-click="switchAppView" data-click-args='["tasks"]'>${escapeHtml(t('hmAllTasks'))}</button>`;
  if (home.calConfigured && dbNextMeeting()) {
    const e = dbNextMeeting();
    cards.push(tdCard('prep', t('tdPrepFor').replace('{title}', () => e.title || t('hmUntitled')), dbPrepHtml('M')));
  }
  cards.push(tdCard('due', t('dbDue'), d ? dbDueHtml(d, 'M') : note('dbLoading'), allTasks));
  cards.push(tdCard('worked', t('dbWorked'), tdWorkedHtml(),
    DB.work && DB.work.enabled && DB.work.supported ? `<span class="hm-note">${escapeHtml(t('tdNorm').replace('{h}', () => dbNum(DB.work.norm || 8)))}</span>` : ''));
  if (home.calConfigured) cards.push(tdCard('free', t('dbFree'), dbFreeHtml()));
  const waitN = d && !d.needs_me ? (d.kpi.waiting || 0) : 0;
  cards.push(tdCard('waiting', t('dbWaiting'), d ? dbWaitingHtml(d, 'S') : note('dbLoading'), waitN ? `<span class="hm-cnt">${waitN}</span>` : ''));
  return cards.join('');
}

// --- Drawing ---
function tdRender() {
  if (!document.getElementById('home-view')) return;
  const span = tdSpan(), cv = TD.cal;
  tdRenderHead(span);
  const body = document.getElementById('td-body');
  body.classList.toggle('td-row', span !== 'day');
  document.getElementById('td-day').classList.toggle('hidden', span !== 'day');
  const cal = document.getElementById('td-cal');
  cal.classList.toggle('hidden', span === 'day');
  if (span !== 'day') {
    const data = cv.data || {};
    const off = cv.data && !data.configured ? `<p class="cal-note">${escapeHtml(t('calNoCalendar'))}</p>` : '';
    cal.innerHTML = `${off}<div class="cal-body${cv.loading ? ' cal-loading' : ''}">${cv.data || !cv.loading ? calBodyHtml(cv) : ''}</div>`;
  }
  const cards = document.getElementById('td-cards');
  if (cards) cards.innerHTML = tdCardsHtml();
  const untx = document.getElementById('td-untx');
  if (untx) untx.innerHTML = (DB.untx || []).length ? dbUntxHtml() : '';
  // the cards rise one after another as «Сегодня» opens (not at a redraw): a card drawn again while they rise goes
  // on from where its former one was
  const gone = performance.now() - TD.shownAt, wave = gone < TD_WAVE_MS && scrollMotion() !== 'auto';
  body.classList.toggle('td-wave', wave);
  if (wave) dbWave(body.querySelectorAll('.hm-card:not(.hidden)'), gone);
}
const TD_WAVE_MS = 1000;

// The calendar of the week or the month: a day (its number, its head, «ещё N», an empty part of it — not a meeting
// or a recording) opens in «День», «⋯» or a right click marks a day off, a recording opens
(function wireToday() {
  const cal = document.getElementById('td-cal');
  if (!cal) return;
  cal.addEventListener('click', e => {
    const b = e.target.closest('[data-cal]');
    if (!b) {
      const cell = !e.target.closest('.cal-item') && e.target.closest('[data-daykey]');
      if (cell) tdOpenDay(`${cell.dataset.daykey}T12:00`);
      return;
    }
    const act = b.dataset.cal;
    if (act === 'day') tdOpenDay(b.dataset.day);
    else if (act === 'dayoff') { const r = b.getBoundingClientRect(); calDayMenu(b.dataset.day, r.left, r.bottom + 4, tdCalLoad); }
    else if (act === 'rec') openMeeting(Number(b.dataset.id));
  });
  cal.addEventListener('contextmenu', e => {
    const cell = e.target.closest('[data-daykey]');
    if (!cell) return;
    e.preventDefault();
    calDayMenu(cell.dataset.daykey, e.clientX, e.clientY, tdCalLoad);
  });
})();

// the hours worked go on: asked again every minute while «Сегодня» is seen; a new day loads its week again
let _tdDay = new Date().toDateString();
setInterval(() => {
  if (state.appView !== 'home' || document.hidden) return;
  const day = new Date().toDateString();
  if (day !== _tdDay) { _tdDay = day; tdLoad(); return; }
  dbLoadWork().then(() => { if (state.appView === 'home') tdRender(); });
}, 60000);

registerView('home', {
  show: () => {
    TD.shownAt = performance.now();
    renderHome();
    clearTimeout(TD.waveTimer);
    TD.waveTimer = setTimeout(() => document.getElementById('td-body')?.classList.remove('td-wave'), TD_WAVE_MS);
    tdLoad();
    if (tdSpan() !== 'day') tdCalLoad();
  },
  refresh: (changed) => { renderHome(); if (changed) tdLoad(); },
});
