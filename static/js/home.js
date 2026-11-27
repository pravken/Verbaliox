// Verbaliox page script: the home page (package B, docs/redesign-plan.md). Today as a calendar page, the
// greeting and the line of the day; the latest recordings with a line of their overview; the meetings of
// the working day from the calendar (hours chosen by the user, past midnight for a night shift) — they can
// be recorded by themselves; what is being processed; the user's open tasks. Also the dictation button,
// and the details of the status bar (the hardware block).
// The parts are classic scripts sharing one global scope, loaded in order by index.html.

const HM_PX = 44;  // pixels of an hour on the timeline
const HM_PRESETS = [[9, 18, 'hmPreset918'], [8, 20, 'hmPreset820'], [20, 8, 'hmPresetNight'], [0, 0, 'hmPresetDay']];

const home = { recent: [], recentAt: 0, events: [], eventsAt: 0, days: {}, calConfigured: true, tasks: [], tasksAt: 0, asked: new Set(), started: new Set(), warned: new Set() };

function hmSettings() { return (state.system && state.system.settings) || {}; }
function hmNum(key, def) { const n = Number(hmSettings()[key]); return Number.isFinite(n) && hmSettings()[key] !== '' && hmSettings()[key] != null ? n : def; }
function hmOn(key, def) { const v = hmSettings()[key]; return v == null || v === '' ? def : String(v) === 'true'; }
// «Никогда»: a series (or one meeting) of the calendar never recorded nor asked about. The series is
// the event's id in the calendar (the key without its start), or its title when the id changes
function hmNeverList() { try { const v = JSON.parse(hmSettings().meet_never || '[]'); return Array.isArray(v) ? v : []; } catch (e) { return []; } }
function hmSeries(e) { return String(e.key || '').replace(/\|[^|]*$/, ''); }
function hmIsNever(e) {
  const id = hmSeries(e), title = (e.title || '').trim().toLowerCase();
  return hmNeverList().some(x => (x.id && x.id === id) || (title && (x.title || '').trim().toLowerCase() === title));
}
// Calendar events that are no meeting (asked by the user): one, or a whole series (meet_ignore; the server's
// app/calendar_ics.is_meeting): not counted, not recorded, not a countdown, no pause of the analysis
function hmIgnoreList() { try { const v = JSON.parse(hmSettings().meet_ignore || '[]'); return Array.isArray(v) ? v : []; } catch (e) { return []; } }
function hmIsIgnored(e) {
  const id = hmSeries(e);
  return hmIgnoreList().some(x => (x.key ? x.key === e.key : x.id && x.id === id));
}
function hmOverrides() { try { return JSON.parse(hmSettings().meet_overrides || '{}') || {}; } catch (e) { return {}; } }
function hmLocale() { return state.uiLang === 'en' ? 'en-GB' : 'ru-RU'; }
function hmPad(n) { return String(n).padStart(2, '0'); }

async function hmSave(values) {
  const res = await fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ settings: values }) });
  if (!res.ok) { showError(serverText((await readJson(res)).detail)); return false; }
  if (state.system) state.system.settings = { ...(state.system.settings || {}), ...values };
  return true;
}

// --- The working day: start and end hours; an end not after the start runs past midnight ---
// date: the working day of that date (the day view of «Сегодня» opened on another day); without it, or when it is
// the date the working day going on began, the working day of now
function hmDay(date) {
  const start = hmNum('work_day_start', 9), end = hmNum('work_day_end', 18);
  const len = end > start ? end - start : end + 24 - start;  // 0 → 24: the whole day
  const now = new Date();
  const from = new Date(now.getFullYear(), now.getMonth(), now.getDate(), start);
  // a shift that began yesterday and has not ended yet is still today's working day
  if (now < from) {
    const prev = new Date(from);
    prev.setDate(prev.getDate() - 1);
    if (now.getTime() < prev.getTime() + len * 3600e3) from.setTime(prev.getTime());
  }
  if (date && calKey(date) !== calKey(from)) from.setTime(new Date(date.getFullYear(), date.getMonth(), date.getDate(), start).getTime());
  const to = new Date(from.getTime() + len * 3600e3);
  return { start, end, len, from, to, fit: hmOn('work_day_fit', true) };
}

// The date the day view of «Сегодня» shows when it is not today (TD.cal.anchor, static/js/today.js), or null
function hmViewDate() {
  const a = typeof TD !== 'undefined' && typeof tdSpan === 'function' && tdSpan() === 'day' ? TD.cal.anchor : null;
  return a && calKey(a) !== calKey(hmDay().from) ? a : null;
}

function hmIso(d) {
  return `${d.getFullYear()}-${hmPad(d.getMonth() + 1)}-${hmPad(d.getDate())}T${hmPad(d.getHours())}:${hmPad(d.getMinutes())}`;
}

// --- Data: refreshed when the page is shown, at most every half minute (events: 5 minutes) ---
async function hmLoad(force) {
  // the latest recordings live in «Записи», the tasks in the cards of «Сегодня» (static/js/today.js)
  const jobs = [];
  jobs.push(hmLoadEvents(force));
  const view = hmViewDate();  // another day shown: its meetings too (today's stay loaded: they are recorded by themselves)
  if (view) jobs.push(hmLoadEvents(force, view));
  await Promise.all(jobs);
}

// The meetings of a working day (date: that of another day; none: today's, kept in home.events for the recording by
// themselves, the dashboard and the pills). Kept by the date of the working day (home.days) for five minutes; another
// day also brings its recordings outside any meeting and its hours worked
const hmEventsLoading = {};  // one request at a time for a day; a failed one is tried again at the next tick
// Today's while a meeting starts within the hour: every minute (a meeting moved or cancelled in the calendar is not
// recorded at its old time; the server reads the calendar more often then, app/brief_notice.py keep_fresh)
const HM_EVENTS_SOON_MS = 60000;
function hmSoonMeeting(events) {
  const now = Date.now();
  return (events || []).some(e => e.e > now && e.s - now < 3600e3);
}
async function hmLoadEvents(force, date) {
  const d = hmDay(date), key = calKey(d.from), today = key === calKey(hmDay().from);
  const at = today ? home.eventsAt : (home.days[key] || {}).at || 0;
  if (!force && Date.now() - at < (today && hmSoonMeeting(home.events) ? HM_EVENTS_SOON_MS : 300000)) return;
  if (hmEventsLoading[key]) return hmEventsLoading[key];
  hmEventsLoading[key] = (async () => {
    // three hours on each side: meetings a little past the edges stretch the day ("fit")
    // and the whole calendar day: a meeting late in the evening is in the head's count and stretches the day
    const day0 = calDayStart(d.from).getTime();
    const a = new Date(Math.min(d.from.getTime() - 3 * 3600e3, day0)), b = new Date(Math.max(d.to.getTime() + 3 * 3600e3, day0 + 86400e3));
    const next = calAddDays(calDayStart(d.from), 1);
    const [data, work] = await Promise.all([
      fetch(`/api/calendar/day?start=${encodeURIComponent(hmIso(a))}&end=${encodeURIComponent(hmIso(b))}`)
        .then(r => (r.ok ? r.json() : null)).catch(() => null),
      today ? null : fetch(`/api/worktime?start=${key}&end=${calKey(next)}`).then(r => (r.ok ? r.json() : null)).catch(() => null),
    ]);
    if (!data) return;
    const events = (data.events || []).map(e => ({ ...e, s: new Date(e.start), e: new Date(e.end) }));
    home.calConfigured = !!data.configured;
    const worked = work && work.enabled && work.days[key] ? work.days[key].worked || 0 : 0;
    home.days[key] = { at: Date.now(), events, recordings: data.recordings || [], worked };
    // a few weeks of days at most: the ones loaded longest ago leave, never the day just loaded nor today (sorted by
    // date, a step back of 30 days dropped the day just loaded: «Загрузка…» for good)
    const todayKey = calKey(hmDay().from);
    const old = Object.keys(home.days).filter(k => k !== key && k !== todayKey).sort((x, y) => home.days[x].at - home.days[y].at);
    for (const k of old.slice(0, Math.max(0, Object.keys(home.days).length - 30))) delete home.days[k];
    if (today) { home.eventsAt = Date.now(); home.events = events; }
  })().finally(() => { delete hmEventsLoading[key]; });
  return hmEventsLoading[key];
}

// A meeting by its key: of today, or of another day shown
function hmEvent(key) {
  return home.events.find(e => e.key === key) || Object.values(home.days).flatMap(x => x.events).find(e => e.key === key);
}

// The day of the home page is drawn on «Дэшборд» (its blocks are there: static/js/dashboard.js)
function hmShown() { return state.appView === 'home' || state.appView === 'dashboard'; }

function renderHome() {
  hmLoad().then(() => { if (hmShown()) renderHomeNow(); });
  renderHomeNow();
}

// «Сегодня» (static/js/today.js) draws its head, its calendar and its cards around the day's meetings
function renderHomeNow() {
  renderHomeMeetings();
  renderHomeQueue();
  if (typeof tdRender === 'function') tdRender();
}

// --- The latest recordings ---
function hmWhen(iso) {
  const d = new Date(String(iso || '').replace(' ', 'T'));
  if (Number.isNaN(d.getTime())) return '';
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const day = new Date(d); day.setHours(0, 0, 0, 0);
  const diff = Math.round((today - day) / 86400e3);
  const time = `${hmPad(d.getHours())}:${hmPad(d.getMinutes())}`;
  if (diff === 0) return `${t('hmToday')} ${time}`;
  if (diff === 1) return `${t('hmYesterday')} ${time}`;
  return d.toLocaleDateString(hmLocale(), { day: 'numeric', month: 'short' });
}

function hmDuration(sec) {
  const m = Math.round((sec || 0) / 60);
  if (!m) return '';
  return m >= 60 ? `${Math.floor(m / 60)} ${t('impHours')} ${m % 60} ${t('impMinutes')}` : `${m} ${t('impMinutes')}`;
}

// A recording not done yet: «в очереди» while it waits (for a meeting, the captions or its turn), else the progress
function hmBusyLabel(m) {
  return m.status === 'queued' ? t('hmQueued') : t('hmProcessing').replace('{pct}', () => m.progress || 0);
}

function renderHomeRecent() {
  const box = document.getElementById('hm-recent');
  if (!box) return;
  // what is being processed now shows its progress (the list of the library is fresher than the page's own copy)
  const live = new Map((state.meetings || []).map(m => [m.id, m]));
  const rows = home.recent.filter(r => live.has(r.id) || !state.meetings.length);
  if (!rows.length) {
    box.innerHTML = `<p class="hm-empty">${escapeHtml(t('homeRecentEmpty'))}</p>`;
    return;
  }
  box.innerHTML = rows.map(r => {
    const m = live.get(r.id) || r;
    const busy = !DONE_STATUSES.includes(m.status);
    const meta = [hmWhen(r.recorded_at), hmDuration(m.duration)].filter(Boolean).join(' · ');
    const icon = r.is_video
      ? '<svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="6" width="13" height="12" rx="2"/><path d="M16 10l5-3v10l-5-3"/></svg>'
      : '<svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 10v4M8 7v10M12 4v16M16 8v8M20 11v2"/></svg>';
    const line = busy
      ? `<span class="hm-busy"><span class="hm-bar"><span style="--fill: ${Math.max(2, m.progress || 0) / 100}"></span></span>${escapeHtml(hmBusyLabel(m))}</span>`
      : r.summary ? `<span class="hm-sum"><svg class="hm-ai" viewBox="0 0 24 24" aria-hidden="true"><path d="M10 2l1.9 5.6 5.6 1.9-5.6 1.9L10 17l-1.9-5.6-5.6-1.9 5.6-1.9z"/><path d="M18.5 13l.9 2.6 2.6.9-2.6.9-.9 2.6-.9-2.6-2.6-.9 2.6-.9z"/></svg><span class="truncate">${escapeHtml(r.summary)}</span></span>` : '';
    const tag = r.tasks ? `<span class="hm-tag">${escapeHtml(plural(r.tasks, t('hmTaskForms')))}</span>` : '';
    return `<button ${pageCall('click', 'openMeeting', [r.id])} class="hm-rec">
        <span class="hm-rec-tile ${r.is_video ? 'hm-rec-video' : ''}" aria-hidden="true">${icon}</span>
        <span class="min-w-0 flex flex-col gap-1">
          <span class="flex items-center gap-2 min-w-0"><b class="hm-rec-title">${escapeHtml(m.title || r.title)}</b><span class="hm-rec-meta">${escapeHtml(meta)}</span></span>
          ${line}
        </span>
        <span class="flex items-center gap-1.5">${tag}</span>
      </button>`;
  }).join('');
}

// --- The meetings of the working day ---
// on: it will be recorded; ask: it will be asked about first (an in-person meeting); off: not recorded
function hmMeetingState(ev) {
  if (hmIsIgnored(ev)) return 'ignored';
  const all = hmOn('meet_auto_all', false), askIn = hmOn('meet_ask_inperson', true);
  const ov = hmOverrides()[ev.key];
  if (ov === 'rec') return 'on';
  if (hmIsNever(ev)) return 'never';
  if (ov === 'skip') return all ? 'skipped' : 'off';
  if (!all) return 'off';
  return askIn && !ev.online ? 'ask' : 'on';
}

// What the day view shows (and what the head of «Сегодня» counts, so both agree): the working day, stretched for
// the meetings past its edges as far as the calendar day when «Расширять» is on; a meeting going on now is always in
// sight. Without a calendar: the day's recordings, the hours stretched for them (the working hours are not offered
// then). A day gone by: also the recordings made outside its meetings
function hmDayShown(view) {
  const d = hmDay(view || undefined), other = view ? home.days[calKey(d.from)] : null;
  const cal = home.calConfigured;
  const events = !cal ? [] : view ? (other ? other.events : []) : home.events;
  const now = Date.now();
  let a = d.from.getTime(), b = d.to.getTime();
  const dayA = calDayStart(d.from).getTime(), lo = Math.min(a, dayA), hi = Math.max(b, dayA + 86400e3);
  const inDay = events.filter(e => e.e.getTime() > lo && e.s.getTime() < hi);
  const asRec = r => {
    const s0 = new Date(r.at);
    return { rec: r, key: `rec|${r.id}`, title: r.title, s: s0, e: new Date(s0.getTime() + Math.max(15 * 60, r.duration || 0) * 1000) };
  };
  let recs = [];
  if (!cal) {
    const key = calKey(d.from);
    recs = (state.meetings || []).map(m => ({ m, at: String(m.recorded_at || m.created_at || '') }))
      .filter(x => x.at.slice(0, 10) === key && !Number.isNaN(Date.parse(x.at.replace(' ', 'T'))))
      .map(({ m, at }) => asRec({ id: m.id, at: at.replace(' ', 'T'), title: m.title, duration: m.duration, status: m.status, progress: m.progress }));
  } else if (view && other) recs = (other.recordings || []).map(asRec);
  const short = e => !e.all_day && e.e.getTime() - e.s.getTime() < 6 * 3600e3;
  const live = e => e.s.getTime() <= now && now < e.e.getTime();
  for (const e of [...inDay, ...recs]) {
    if (!short(e) || !(d.fit || live(e) || e.rec && !cal)) continue;
    a = Math.max(lo, Math.min(a, Math.floor(e.s.getTime() / 3600e3) * 3600e3));
    b = Math.min(hi, Math.max(b, Math.ceil(e.e.getTime() / 3600e3) * 3600e3));
  }
  const meetings = inDay.filter(e => e.e.getTime() > a && e.s.getTime() < b);
  const real = meetings.filter(e => !hmIsIgnored(e) && e.e - e.s < 6 * 3600e3);  // what counts as meetings
  return { d, other, a, b, meetings, real, recs: recs.filter(e => e.e.getTime() > a && e.s.getTime() < b) };
}

function renderHomeMeetings() {
  // another day opened from the calendar (hmViewDate): its working day, its meetings, its recordings
  const view = hmViewDate();
  const { d, other, a, b, meetings: shownMeetings, real, recs } = hmDayShown(view);
  const pastDay = !!view && d.to.getTime() <= Date.now();
  const mtTitle = document.getElementById('hm-mt-title');
  if (mtTitle) mtTitle.textContent = view ? t('hmMeetingsOn').replace('{date}', () => d.from.toLocaleDateString(hmLocale(), { day: 'numeric', month: 'long' })) : t('hmMeetings');
  document.getElementById('hm-day-range').textContent = d.len === 24 ? t('hmAllDay') : `${hmPad(d.start)}–${hmPad(d.end)}`;
  document.getElementById('hm-cal-off').classList.toggle('hidden', home.calConfigured);
  // without a calendar the day still shows its recordings (the week did, the day said only «Подключите календарь»)
  document.getElementById('hm-cal-on').classList.remove('hidden');
  // audit 8.7: the working hours only matter for the meetings of a calendar
  document.getElementById('hm-day-btn').closest('.hm-day-wrap')?.classList.toggle('hidden', !home.calConfigured);
  const now = new Date();
  const meetings = [...shownMeetings];
  const count = document.getElementById('hm-mt-count');
  count.textContent = String(real.length);
  count.classList.toggle('hidden', !real.length || !home.calConfigured);
  meetings.push(...recs);

  // the switch "record every meeting" and what it means today (it is about the meetings ahead: not on a day gone by)
  document.getElementById('hm-auto').classList.toggle('hidden', pastDay || !home.calConfigured);
  const all = hmOn('meet_auto_all', false);
  const sw = document.getElementById('hm-auto-sw');
  sw.setAttribute('aria-checked', String(all));
  document.getElementById('hm-auto').classList.toggle('hm-auto-on', all);
  document.getElementById('hm-ask-wrap').classList.toggle('hidden', !all);
  document.getElementById('hm-ask-inperson').checked = hmOn('meet_ask_inperson', true);
  const up = real.filter(e => e.e > now);
  const states = up.map(hmMeetingState);
  const rec = states.filter(s => s === 'on').length, ask = states.filter(s => s === 'ask').length;
  document.getElementById('hm-auto-sub').textContent = !all
    ? t('hmAutoOffSub')
    : [t('hmAutoOnSub').replace('{n}', () => rec).replace('{of}', () => up.length), ask ? t('hmAutoAskSub').replace('{n}', () => ask) : ''].filter(Boolean).join(' · ');

  // hours, the meetings on them, the line of "now"
  const hours = [];
  for (let x = a; x <= b; x += 3600e3) hours.push(x);
  const top = (ms) => ((ms - a) / 3600e3) * HM_PX;
  const box = document.getElementById('hm-timeline');
  box.style.height = `${top(b)}px`;
  // The time already past is filled, up to the line of "now" (asked by the user: where the border is and
  // which meetings are over was not clear); the whole scale once the day is over
  const nowMs = now.getTime();
  // the working time gone by is tinted from the start of the working day (work_day_start), not from the first hour
  // shown; a plain tint: hatching means a day off
  const pastTo = nowMs <= a ? 0 : Math.min(nowMs, b), pastFrom = Math.max(a, d.from.getTime());
  const html = pastTo > pastFrom ? [`<div class="hm-pastfill" style="top: ${top(pastFrom)}px; height: ${top(pastTo) - top(pastFrom)}px" aria-hidden="true"></div>`] : [];
  const workGone = Math.max(0, Math.min(nowMs, d.to.getTime()) - d.from.getTime());
  html.push(...hours.map(x => `<div class="hm-hour" style="top: ${top(x)}px"><span>${hmPad(new Date(x).getHours())}:00</span><i></i></div>`));
  // Meetings at the same time stand side by side, not on top of each other (reported by the user): a
  // group of meetings that overlap shares the width, each in the first column free at its start
  const lane = new Map();
  const order = [...meetings].sort((x, y) => x.s - y.s || y.e - x.e);
  let group = [], ends = [], groupEnd = 0;
  const closeGroup = () => { group.forEach(g => { lane.get(g).cols = ends.length; }); group = []; ends = []; };
  for (const e of order) {
    const s0 = e.s.getTime(), e0 = Math.max(e.e.getTime(), s0 + 26 / HM_PX * 3600e3);  // as tall as it is drawn
    if (group.length && s0 >= groupEnd) closeGroup();
    let col = ends.findIndex(end => end <= s0);
    if (col < 0) { col = ends.length; ends.push(e0); } else ends[col] = e0;
    lane.set(e, { col, cols: 1 });
    group.push(e);
    groupEnd = group.length === 1 ? e0 : Math.max(groupEnd, e0);
  }
  closeGroup();
  for (const e of meetings) {
    const s = Math.max(e.s.getTime(), a), en = Math.min(e.e.getTime(), b);
    const hpx = Math.max(26, top(en) - top(s) - 3);
    const { col, cols } = lane.get(e) || { col: 0, cols: 1 };
    const narrow = cols > 1;
    const place = narrow ? `left: calc(46px + (100% - 46px) * ${col} / ${cols}); right: auto; width: calc((100% - 46px) / ${cols} - 3px);` : '';
    const lines = Math.max(1, Math.floor((hpx - (narrow && hpx < 40 ? 6 : 23)) / 17));  // the title wraps as far as the height lets it
    if (e.rec) {  // a recording of a day gone by, made outside any meeting: the whole card opens it
      const r = e.rec, at = `${hmPad(e.s.getHours())}:${hmPad(e.s.getMinutes())}`;
      const label = DONE_STATUSES.includes(r.status) ? t('hmRecordingLink') : hmBusyLabel(r);
      html.push(`<button ${pageCall('click', 'openMeeting', [r.id])} class="hm-mt hm-mt-k-recording${narrow ? ' hm-mt-narrow' : ''}" style="top: ${top(s)}px; height: ${hpx}px; ${place}" title="${escapeHtml(`${at} · ${e.title || t('hmUntitled')}\n${t('hmRecOutside')}`)}">
          <span class="flex-1 min-w-0 flex flex-col gap-px text-left"><span class="hm-mt-title">${escapeHtml(e.title || t('hmUntitled'))}</span>
          ${hpx >= 34 && !narrow ? `<span class="hm-mt-sub"><span class="hm-mono">${escapeHtml(at)}</span> · ${escapeHtml(t('hmRecOutside'))}</span>` : ''}</span>
          <span class="hm-mt-link">${escapeHtml(label)}</span>${narrow ? '' : '<span class="hm-mt-more hm-mt-slot" aria-hidden="true"></span>'}</button>`);
      continue;
    }
    // How much it overlaps the others (asked by the user: side by side, it was not clear): the time they
    // share is hatched in the card, and its tooltip says with which meeting and for how long
    const clock = ms => { const d = new Date(ms); return `${hmPad(d.getHours())}:${hmPad(d.getMinutes())}`; };
    const overlaps = narrow ? meetings.filter(o => o !== e && o.s < e.e && e.s < o.e).map(o => {
      const from = Math.max(o.s.getTime(), e.s.getTime()), to = Math.min(o.e.getTime(), e.e.getTime());
      return { o, from, to };
    }) : [];
    const hatch = overlaps.map(({ from, to }) => {
      const y = Math.max(0, top(Math.max(from, a)) - top(s)), h = Math.min(hpx, top(Math.min(to, b)) - top(s)) - y;
      return h > 0 ? `<i class="hm-ovl" style="top: ${y}px; height: ${h}px"></i>` : '';
    }).join('');
    const overlapTip = overlaps.map(({ o, from, to }) => t('hmOverlapTip').replace('{title}', () => o.title || t('hmUntitled'))
      .replace('{from}', () => clock(from)).replace('{to}', () => clock(to)).replace('{min}', () => Math.round((to - from) / 60e3))).join('\n');
    const past = e.e <= now, live = e.s <= now && now < e.e;
    const st = past ? 'past' : hmMeetingState(e);
    const time = `${hmPad(e.s.getHours())}:${hmPad(e.s.getMinutes())}–${hmPad(e.e.getHours())}:${hmPad(e.e.getMinutes())}`;
    const where = e.online ? t('hmOnline') : (e.location || t('hmInPerson'));
    const who = [where, e.attendees.length ? plural(e.attendees.length, t('hmPeopleForms')) : ''].filter(Boolean).join(' · ');
    let action;
    if (past) {
      const r = e.recording;
      action = r
        ? `<button ${pageCall('click', 'openMeeting', [r.id])} class="hm-mt-link">${escapeHtml(DONE_STATUSES.includes(r.status) ? t('hmRecordingLink') : hmBusyLabel(r))}</button>`
        : `<span class="hm-mt-none">${escapeHtml(t('hmNoRecording'))}</span>`;
    } else if (hmAutoRec && hmAutoRec.key === e.key && isRecording()) {
      action = `<span class="hm-mt-btn hm-mt-rec" title="${escapeHtml(t('hmRecordingNow'))}"><i></i><span class="hm-mt-btn-t">${escapeHtml(t('hmRecordingNow'))}</span></span>`;
    } else if (live && now - e.s > 5 * 60e3 && !isRecording()
      && !(e.online && st === 'on' && hmCallWatch !== false && !home.started.has(e.key) && !hmUserStopped().has(e.key))) {
      // half-way through: not started by itself any more (hmAutoTick), but one click records the rest; an online
      // meeting still waiting for its call keeps its state: the call starts it (hmJoinTick)
      action = `<button ${pageCall('click', 'hmRecordNow', [e.key])} class="hm-mt-btn" title="${escapeHtml(t('hmRecordNow'))}"><i></i><span class="hm-mt-btn-t">${escapeHtml(t('hmRecordNow'))}</span></button>`;
    } else {
      const label = { on: 'hmStateOn', ask: 'hmStateAsk', skipped: 'hmStateSkipped', off: 'hmStateOff', never: 'hmStateNever', ignored: 'hmStateIgnored' }[st];
      action = `<button ${pageCall('click', 'hmToggleMeeting', [e.key])} class="hm-mt-btn hm-mt-${st}" aria-pressed="${st === 'on'}" aria-label="${escapeHtml(t(label))}" title="${escapeHtml(`${t(label)}. ${t('hmMeetingTip')}`)}"><i></i><span class="hm-mt-btn-t">${escapeHtml(t(label))}</span></button>`;
    }
    // A meeting ahead that continues a series: what is open from last time, and the brief on a click
    const bf = !past && e.before;
    const brief = bf
      ? `<button ${pageCall('click', 'openBriefFor', bf.series_id ? ['series', bf.series_id] : ['person', bf.person])} class="hm-mt-link"
          title="${escapeHtml(t('hmBriefTip').replace('{n}', () => bf.open_tasks).replace('{title}', () => bf.last.title).replace('{date}', () => bf.last.date))}">${escapeHtml(
          bf.open_tasks ? t('hmBriefTasks').replace('{n}', () => bf.open_tasks) : t('hmBrief'))}</button>`
      : '';
    // the call of the meeting, from its invitation (Teams, Zoom, Meet, Webex): one click joins, from now to its end
    const join = !past && e.join && e.s - now < 15 * 60e3
      ? `<button ${pageCall('click', 'joinMeetingCall', [e.join])} class="hm-mt-link hm-mt-join" title="${escapeHtml(t('hmJoinTip'))}">${escapeHtml(t('hmJoin'))}</button>`
      : '';
    const title = e.title || t('hmUntitled');
    // a meeting going on: how far it is, filled in its card, and the minutes left
    const done = live ? Math.round((nowMs - e.s.getTime()) / (e.e.getTime() - e.s.getTime()) * 100) : 0;
    const left = live ? Math.max(1, Math.round((e.e.getTime() - nowMs) / 60e3)) : 0;
    const liveFill = live ? `<i class="hm-mt-prog" style="width: ${done}%"></i>` : '';
    const liveSub = live ? ` · <b class="hm-mt-left">${escapeHtml(t('hmLiveLeft').replace('{n}', () => left))}</b>` : '';
    html.push(`<div class="hm-mt hm-mt-k-${past ? 'past' : st}${live ? ' hm-mt-live' : ''}${narrow ? ' hm-mt-narrow' : ''}" style="top: ${top(s)}px; height: ${hpx}px; ${place}">${liveFill}${hatch}
        <span class="flex-1 min-w-0 flex flex-col gap-px" title="${escapeHtml([`${title}`, `${time} · ${who}`, overlapTip].filter(Boolean).join('\n'))}">
          <span class="flex items-baseline gap-1.5 min-w-0">${narrow && hpx < 40 ? `<span class="hm-mt-time">${escapeHtml(clock(e.s.getTime()))}</span>` : ''}<span class="hm-mt-title${lines > 1 ? ' hm-mt-wrap' : ''}" style="-webkit-line-clamp: ${lines}">${escapeHtml(title)}</span>${hpx < 34 && !narrow ? `<span class="hm-mt-time">${escapeHtml(time)}</span>` : ''}</span>
          ${hpx >= 34 && !narrow ? `<span class="hm-mt-sub"><span class="hm-mono">${escapeHtml(time)}</span>${live ? liveSub : ` · ${escapeHtml(who)}`}</span>` : ''}
          ${narrow && hpx >= 40 ? `<span class="hm-mt-sub hm-mono">${escapeHtml(time)}</span>` : ''}
        </span>${join}${narrow ? '' : brief}${action}${narrow ? '' : `<button ${pageCall('click', 'hmMeetingMenu', [e.key, { $: 'el' }])} class="hm-mt-more" title="${escapeHtml(t('hmMeetingMenuTip'))}" aria-label="${escapeHtml(t('hmMeetingMenuTip'))}">⋯</button>`}
      </div>`);
  }
  if (!meetings.length) html.push(`<div class="hm-mt-empty">${escapeHtml(t(!home.calConfigured ? 'hmNoRecordingsDay' : view && !other ? 'dbLoading' : 'hmNoMeetings'))}</div>`);
  // how much of the working day is over: the shaded part says it, the figure is in the hint of the time (a caption
  // on the line itself crossed it — reported by the user)
  const gone = workGone && nowMs < d.to.getTime() ? ` title="${escapeHtml(t('hmDayGone').replace('{t}', () => dbHm(workGone / 1000)))}"` : '';
  if (!view && nowMs >= a && nowMs <= b) html.push(`<div class="hm-now" style="top: ${top(nowMs)}px"><b class="hm-now-t"${gone}>${hmPad(now.getHours())}:${hmPad(now.getMinutes())}</b></div>`);
  box.innerHTML = html.join('');
  return real;  // the header counts the meetings, not the blocks and the events that are none
}

// «⋯» on a meeting of the day: no meeting (this one or its whole series), or a meeting again
async function hmSetIgnored(key, scope) {
  const ev = hmEvent(key);
  if (!ev) return;
  const id = hmSeries(ev);
  const list = hmIgnoreList().filter(x => !(x.key === ev.key || (!x.key && x.id === id)));
  if (scope === 'one') list.push({ id: '', key: ev.key, title: ev.title || '' });
  if (scope === 'series') list.push({ id, key: '', title: ev.title || '' });
  if (!await hmSave({ meet_ignore: JSON.stringify(list.slice(-300)) })) return;
  renderHomeNow();
  if (state.appView === 'dashboard' && typeof renderDashboard === 'function') renderDashboard();
}

function hmMeetingMenu(key, el) {
  const ev = hmEvent(key);
  if (!ev) return;
  const r = el.getBoundingClientRect();
  const items = hmIsIgnored(ev)
    ? [{ label: t('hmMeetingAgain'), run: () => hmSetIgnored(key, null) }]
    : [{ label: t('hmIgnoreOne'), run: () => hmSetIgnored(key, 'one') }, { label: t('hmIgnoreSeries'), run: () => hmSetIgnored(key, 'series') }];
  setTimeout(() => openTextMenuAt(items, r.right, r.bottom + 4, { right: true }), 0);
}

// A meeting going on: record the rest of it, stopped with the meeting like an automatic one
async function hmRecordNow(key) {
  // the strip shows the meetings of the week (strip.events), «Сегодня» those of the working day ±3 h
  const ev = home.events.find(e => e.key === key) || (typeof strip !== 'undefined' ? (strip.events || []).find(e => e.key === key) : null);
  if (!ev || isRecording() || hmAutoRec) return;
  home.started.add(key);
  hmAutoRec = { key, end: ev.e.getTime(), title: ev.title || '' };
  await shellQuickRecord();
  renderHomeNow();
}

async function hmToggleMeeting(key) {
  const ev = hmEvent(key);
  if (!ev) return;
  const ov = hmOverrides();
  const st = hmMeetingState(ev);
  if (st === 'ignored') { await hmSetIgnored(key, null); return; }  // «Не встреча» taken back
  if (st === 'never') { await hmSetNever(ev, false); return; }  // «Никогда» taken back: as the others again
  // asking → recorded → left out → recorded …; without "all": recorded ↔ not
  if (st === 'on') { if (hmOn('meet_auto_all', false)) ov[key] = 'skip'; else delete ov[key]; }
  else ov[key] = 'rec';
  if (await hmSave({ meet_overrides: JSON.stringify(hmPruneOverrides(ov)) })) renderHomeNow();
}

// Choices of meetings two days past are of no use any more
function hmPruneOverrides(ov) {
  const old = Date.now() - 2 * 86400e3;
  return Object.fromEntries(Object.entries(ov).filter(([k]) => { const t0 = Date.parse(k.split('|').pop()); return !t0 || t0 > old; }));
}

async function hmToggleAutoAll() {
  if (await hmSave({ meet_auto_all: String(!hmOn('meet_auto_all', false)), meet_overrides: '{}' })) renderHomeNow();
}

async function hmSetAskInPerson(on) {
  if (await hmSave({ meet_ask_inperson: String(!!on) })) renderHomeNow();
}

// --- The working day popover ---
function hmToggleDay(e) {
  e.stopPropagation();
  const pop = document.getElementById('hm-day-pop');
  const open = pop.classList.contains('hidden');
  pop.classList.toggle('hidden', !open);
  document.getElementById('hm-day-btn').setAttribute('aria-expanded', String(open));
  if (open) renderHomeDayPop();
}

function renderHomeDayPop() {
  const d = hmDay();
  const opts = (sel, v) => {
    sel.innerHTML = Array.from({ length: 24 }, (_, h) => `<option value="${h}">${hmPad(h)}:00</option>`).join('');
    sel.value = String(v % 24);
  };
  opts(document.getElementById('hm-day-start'), d.start);
  opts(document.getElementById('hm-day-end'), d.end);
  const night = document.getElementById('hm-overnight');
  night.classList.toggle('hidden', d.end > d.start);
  night.textContent = d.len === 24 ? t('hmAllDayNote') : t('hmOvernight');
  document.getElementById('hm-presets').innerHTML = HM_PRESETS.map(([a, b, label]) => {
    const on = d.start === a && d.end % 24 === b;
    return `<button ${pageCall('click', 'hmPickPreset', [a, b])} class="hm-preset${on ? ' hm-preset-on' : ''}" aria-pressed="${on}">${escapeHtml(t(label))}</button>`;
  }).join('');
  document.getElementById('hm-fit').checked = d.fit;
}

async function hmSetDay() {
  const start = Number(document.getElementById('hm-day-start').value), end = Number(document.getElementById('hm-day-end').value);
  await hmApplyDay(start, end);
}

async function hmPickPreset(start, end) { await hmApplyDay(start, end); }

async function hmApplyDay(start, end) {
  if (!await hmSave({ work_day_start: String(start), work_day_end: String(end) })) return;
  home.eventsAt = 0;
  home.days = {};  // the other days have other hours now
  await hmLoad(true);
  renderHomeDayPop();
  renderHomeNow();
}

async function hmSetFit(on) {
  if (await hmSave({ work_day_fit: String(!!on) })) renderHomeNow();
}

document.addEventListener('click', (e) => {
  const pop = document.getElementById('hm-day-pop');
  if (pop && !pop.classList.contains('hidden') && !e.target.closest('#hm-day-btn')) {
    pop.classList.add('hidden');
    document.getElementById('hm-day-btn').setAttribute('aria-expanded', 'false');
  }
});

// --- In work: the queue of the library ---
function renderHomeQueue() {
  const items = state.queue || [];
  document.getElementById('hm-work-card').classList.toggle('hidden', !items.length);
  document.getElementById('hm-queue').innerHTML = items.slice(0, 4).map(q => {
    const m = (state.meetings || []).find(x => x.id === q.id) || {};
    const run = q.state === 'running';
    const pct = run ? (m.progress ?? q.progress ?? 0) : 0;
    return `<button ${pageCall('click', 'openMeeting', [q.id])} class="hm-q">
        <span class="flex items-center gap-2 min-w-0"><b class="hm-q-title">${escapeHtml(q.title || m.title || '')}</b><span class="${run ? 'hm-q-run' : 'hm-q-wait'}">${escapeHtml(run ? `${queueKindLabel(q)} · ${pct}%` : t('hmWaiting'))}</span></span>
        <span class="hm-bar hm-bar-wide"><span style="--fill: ${run ? Math.max(2, pct) / 100 : 0}"></span></span>
      </button>`;
  }).join('');
  return items.length;
}

// --- The user's open tasks: who is the user — names in the setting my_name (comma separated) ---
function hmMyNames() {
  return String(hmSettings().my_name || '').split(',').map(s => s.trim().toLowerCase()).filter(Boolean);
}

function renderHomeTasks() {
  const names = hmMyNames();
  // the whole name, as on the Tasks page (tkIsMe): «Ан» is not «Анна»
  const mine = names.length ? home.tasks.filter(c => names.includes(String(c.who || '').trim().toLowerCase())) : home.tasks;
  if (!document.getElementById('hm-tasks')) return mine.length;
  document.getElementById('hm-tasks-title').textContent = t(names.length ? 'hmMyTasks' : 'hmOpenTasks');
  document.getElementById('hm-my-name').classList.toggle('hidden', !!names.length);
  const count = document.getElementById('hm-tasks-count');
  count.textContent = String(mine.length);
  count.classList.toggle('hidden', !mine.length);
  // by the due date (the one set by hand too), as on the Tasks page; the nearest first, then the ones without one
  const list = [...mine].sort((x, y) => (x.due_date ? 0 : 1) - (y.due_date ? 0 : 1)
    || String(x.due_date || '').localeCompare(String(y.due_date || ''))
    || String(y.meeting_date).localeCompare(String(x.meeting_date))).slice(0, 5);
  document.getElementById('hm-tasks').innerHTML = list.length ? list.map(c => `
      <label class="hm-task">
        <input type="checkbox" ${pageCall('change', 'hmTaskDone', [c.id])} />
        <span class="flex-1 min-w-0 flex flex-col gap-0.5"><span class="hm-task-text">${escapeHtml(c.what)}</span>
          <span class="hm-task-sub">${escapeHtml([names.length ? '' : c.who, c.meeting_title].filter(Boolean).join(' · '))}</span></span>
        ${c.due_date ? `<span class="hm-due ${tkDueTone(c)}">${escapeHtml(tkDueText(c))}</span>` : ''}
      </label>`).join('')
    : `<p class="hm-empty">${escapeHtml(t('tasksEmpty'))}</p>`;
  return mine.length;
}

async function hmTaskDone(id) {
  const res = await fetch(`/api/commitments/${Number(id)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'done' }) });
  if (!res.ok) { showError(serverText((await readJson(res)).detail)); return; }
  home.tasks = home.tasks.filter(c => c.id !== Number(id));
  refreshTasksCount(true);
  renderHomeNow();
  showToast(t('hmTaskDoneToast'), { label: t('hmUndo'), onClick: () => hmTaskUndo(id) });
}

async function hmTaskUndo(id) {
  await fetch(`/api/commitments/${Number(id)}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'open' }) });
  home.tasksAt = 0;
  refreshTasksCount(true);
  await hmLoad(true);
  renderHomeNow();
}

async function hmSetMyName() {
  const v = await askText(t('hmMyNamePrompt'), hmSettings().my_name || '');
  if (v == null) return;
  if (await hmSave({ my_name: v.trim().slice(0, 200) })) renderHomeNow();
}

// --- Recording the meetings of the calendar by themselves (the page is open: it records) ---
// Every 20 s: a meeting that began and is to be recorded starts the recording (once; a recording the user
// stopped is not started again); the recording it started stops a minute after the meeting ends. An
// in-person meeting to be asked about shows the question a minute before it. The window hidden in the
// tray or minimized keeps the page running (as the calls recorded by themselves do, studio.js), so the
// tick runs then too; the browser may slow it to once a minute, which the 5-minute start window allows.
// The question brings the window back (window.pywebview.api.show_window).
let hmAutoRec = null;  // {key, end}: the recording started for a meeting
const HM_OVERRUN_MS = 4 * 3600e3;  // a call held past this after its meeting ends no longer keeps the recording

async function hmAutoTick() {
  await hmLoadEvents(false);
  // a meeting about to be recorded or asked about: by the calendar read for its start (the server reads it two
  // minutes before), not by the one of a few minutes ago — the meeting may have moved
  const t0 = Date.now();
  if (home.events.some(e => !home.started.has(e.key) && t0 >= e.s.getTime() - 75e3 && t0 < e.s.getTime() + 5 * 60e3
    && home.eventsAt < e.s.getTime() - 60e3)) await hmLoadEvents(true);
  const now = Date.now();
  if (hmAutoRec && !isRecording() && !_quickRecBusy) {  // the user stopped it: it stays stopped
    hmUserStopped().add(hmAutoRec.key);
    hmAutoRec = null;
  }
  hmAskExpire();
  // The meeting runs over its time in the calendar while its call still holds the microphone: the recording goes on
  // until the call lets go of it (hmCallEndTick), and the next meeting does not take its place (reported by the
  // user: an hour and a half on one call was cut at its calendar end, and a recording of the next meeting began).
  // Only for an online meeting whose call was seen holding it lately (an in-person meeting ends by the clock; the
  // status unanswered is no call: found in review, a failing status kept it 4 hours), at most HM_OVERRUN_MS past its end
  if (hmAutoRec && now > hmAutoRec.end + 60e3 && hmAutoRec.online && hmAutoRec.seenAt && now - hmAutoRec.seenAt < HM_CALL_GONE_MS + 10e3
      && isRecording() && now < hmAutoRec.end + HM_OVERRUN_MS) {
    if (!hmAutoRec.overrun) {
      hmAutoRec.overrun = true;
      showToast(t('hmCallOverrun').replace('{title}', () => hmAutoRec.title || t('hmUntitled')));
    }
    return;
  }
  if (hmAutoRec && now > hmAutoRec.end + 60e3) {
    const rec = hmAutoRec;
    hmAutoRec = null;
    if (isRecording()) {
      await shellQuickRecord();
      autoRecordNotice(false, 'calendar', rec.title);
    }
    home.started.add(rec.key);
    return;
  }
  for (const e of home.events) {
    const s = e.s.getTime(), en = e.e.getTime();
    if (en <= now || home.started.has(e.key)) continue;
    const st = hmMeetingState(e);
    if (st === 'ask' && now >= s - 60e3 && now < s + 5 * 60e3 && !home.asked.has(e.key)) {
      home.asked.add(e.key);
      hmShowAsk(e);
      continue;
    }
    // a minute before a meeting recorded by itself: a chime and a word (asked by the user)
    if (st === 'on' && now >= s - 75e3 && now < s - 15e3 && !home.warned.has(e.key) && !isRecording()) {
      home.warned.add(e.key);
      recordSound('soon');
      showToast(t(e.online && hmCallWatch !== false ? 'hmAutoSoonCall' : 'hmAutoSoon').replace('{title}', () => e.title || t('hmUntitled')));
    }
    // an online meeting waits for its call (hmJoinTick); an in-person one starts by the clock, only near the
    // start: a meeting half over is not recorded by surprise
    if (e.online && hmCallWatch !== false) continue;
    if (st === 'on' && now >= s - 15e3 && now < s + 5 * 60e3 && !isRecording() && !hmAutoRec) await hmStartAuto(e, '');
  }
}

// The meetings whose recording the user stopped (by «Стоп» or the red button): not recorded again by themselves, and
// the strip offers no «Записать» for them. A recording stopped by the end of its call is not one of them
function hmUserStopped() { return home.userStopped || (home.userStopped = new Set()); }

// A browser holds the microphone for many things: only an online meeting takes it for its call (found in review)
function hmIsBrowser(app) { return /\.exe$/i.test(app || ''); }

async function hmStartAuto(e, app) {
  home.started.add(e.key);
  hmAutoRec = { key: e.key, end: e.e.getTime(), title: e.title || '', app, online: !!e.online, seenAt: app ? Date.now() : 0 };
  await shellQuickRecord();
  showToast(t('hmAutoStarted').replace('{title}', () => e.title || t('hmUntitled')));
  if (isRecording()) autoRecordNotice(true, 'calendar', e.title || t('hmUntitled'));
}

// An online meeting is recorded only once its call is joined: a call app or a browser holds the microphone for
// HM_CALL_JOIN_MS, from two minutes before the meeting to its end (reported by the user: the computer woke from
// sleep at the time of a meeting nobody joined, and the recording started by the clock). Where the microphone
// cannot be read (not Windows), the clock starts it as before. hmCallWatch: null until the first status read
const HM_CALL_JOIN_MS = 8e3;
let hmCallWatch = null;
let hmJoin = null;  // {key, since}: the call of this meeting holds the microphone since
async function hmJoinTick() {
  const now = Date.now();
  const due = x => x.online && hmMeetingState(x) === 'on' && now >= x.s.getTime() - 2 * 60e3 && now < x.e.getTime();
  // a recording made by hand during the meeting: its meeting is not recorded again by itself once it stops (found in
  // review: a stop by hand mid-call was followed by a new recording seconds later)
  if (isRecording() && !hmAutoRec) for (const x of home.events) if (due(x)) hmUserStopped().add(x.key);
  if (hmAutoRec || isRecording() || _quickRecBusy || hmCallWatch === false) { hmJoin = null; return; }
  const e = home.events.find(x => due(x) && !home.started.has(x.key) && !hmUserStopped().has(x.key) && !x.recording);
  if (!e) { hmJoin = null; return; }
  const st = await fetch('/api/calls/status').then(r => (r.ok ? r.json() : null)).catch(() => null);
  if (!st) return;
  hmCallWatch = !!st.supported;
  if (!hmCallWatch) return;  // the next hmAutoTick starts it by the clock
  if (!st.meeting_app) { hmJoin = null; return; }
  if (!hmJoin || hmJoin.key !== e.key) hmJoin = { key: e.key, since: now };
  if (now - hmJoin.since < HM_CALL_JOIN_MS || hmAutoRec || isRecording() || _quickRecBusy) return;
  hmJoin = null;
  await hmStartAuto(e, st.meeting_app);
}

// A meeting over before its time in the calendar: the recording the calendar started stops when the app
// of the call lets go of the microphone (reported by the user: it ran on after the call). Only once an app
// was seen holding it during this recording: an in-person meeting has none and runs to its end
const HM_CALL_GONE_MS = 20e3;
async function hmCallEndTick() {
  if (!hmAutoRec || !isRecording() || _quickRecBusy) return;
  const st = await fetch('/api/calls/status').then(r => (r.ok ? r.json() : null)).catch(() => null);
  if (!st || !st.supported || !hmAutoRec) return;
  // an in-person meeting: a browser holding the microphone is not its call
  const app = st.meeting_app && (hmAutoRec.online || !hmIsBrowser(st.meeting_app)) ? st.meeting_app : '';
  if (app) { hmAutoRec.app = app; hmAutoRec.freeSince = 0; hmAutoRec.seenAt = Date.now(); return; }
  if (!hmAutoRec.app) return;
  hmAutoRec.freeSince = hmAutoRec.freeSince || Date.now();
  if (Date.now() - hmAutoRec.freeSince < HM_CALL_GONE_MS) return;
  const rec = hmAutoRec;
  hmAutoRec = null;
  // not marked as done: the call joined again records again (found in review: a dropped call was not recorded after)
  if (rec.online) home.started.delete(rec.key); else home.started.add(rec.key);  // in person: by the clock, once
  hmJoin = null;
  if (isRecording()) {
    await shellQuickRecord();
    autoRecordNotice(false, 'calendar', rec.title);
    showToast(t('hmCallEnded').replace('{title}', () => rec.title || t('hmUntitled')));
  }
}

let hmAskEvent = null;
function hmShowAsk(e) {
  hmAskEvent = e;
  document.getElementById('hm-ask-title').textContent = t('hmAskTitle').replace('{title}', () => e.title || t('hmUntitled'));
  document.getElementById('hm-ask-text').textContent = t('hmAskText').replace('{where}', () => e.location || t('hmInPerson'));
  document.getElementById('hm-ask').classList.remove('hidden');
  const api = window.pywebview && window.pywebview.api;
  if (document.hidden && api && api.show_window) api.show_window().catch(() => {});
}

// «Никогда» before a meeting: neither this one nor the next of its series is recorded or asked about;
// the home page shows it as «Никогда», a click there takes it back
async function hmSetNever(e, on) {
  const id = hmSeries(e), title = (e.title || '').trim();
  const low = title.toLowerCase();
  const rest = hmNeverList().filter(x => !((x.id && x.id === id) || (low && (x.title || '').trim().toLowerCase() === low)));
  const list = on ? [...rest, { id, title }].slice(-300) : rest;
  const ov = hmOverrides();
  delete ov[e.key];
  if (!await hmSave({ meet_never: JSON.stringify(list), meet_overrides: JSON.stringify(hmPruneOverrides(ov)) })) return false;
  if (hmShown()) renderHomeNow();
  return true;
}

// The question goes by itself once it has no point (reported by the user: «Через минуту: …» stayed while the
// meeting was recorded): a recording going on (started by any way), or the start window over (the tick
// records nothing later than 5 minutes in). Unanswered: nothing is saved for the meeting
function hmAskExpire() {
  const e = hmAskEvent;
  if (!e) return;
  const now = Date.now();
  if (!isRecording() && now < e.s.getTime() + 5 * 60e3 && now < e.e.getTime()) return;
  hmAskEvent = null;
  document.getElementById('hm-ask')?.classList.add('hidden');
}

async function hmAskNever() {
  document.getElementById('hm-ask').classList.add('hidden');
  const e = hmAskEvent;
  hmAskEvent = null;
  if (!e || !await hmSetNever(e, true)) return;
  showToast(t('hmNeverToast').replace('{title}', () => e.title || t('hmUntitled')),
    { label: t('hmUndo'), onClick: () => hmSetNever(e, false) });
}

async function hmAskAnswer(yes) {
  document.getElementById('hm-ask').classList.add('hidden');
  const e = hmAskEvent;
  hmAskEvent = null;
  if (!e || yes == null) return;
  const ov = hmOverrides();
  ov[e.key] = yes ? 'rec' : 'skip';
  await hmSave({ meet_overrides: JSON.stringify(hmPruneOverrides(ov)) });
  if (yes && !isRecording() && !hmAutoRec) {
    home.started.add(e.key);
    hmAutoRec = { key: e.key, end: e.e.getTime(), title: e.title || '' };
    await shellQuickRecord();
  }
  if (hmShown()) renderHomeNow();
}

// --- Dictation from the home page (app/dictation.py, the text is shown here, not typed) ---
let hmDictTimer = null;

async function hmDictToggle() {
  const res = await fetch('/api/dictation/toggle', { method: 'POST' });
  const data = await readJson(res);
  if (!res.ok) { showError(serverText(data.detail)); return; }
  hmDictShow(data.state === 'started' ? 'listen' : 'busy');
  clearInterval(hmDictTimer);
  hmDictTimer = setInterval(hmDictPoll, 500);
}

async function hmDictPoll() {
  const st = await fetch('/api/dictation').then(r => (r.ok ? r.json() : null)).catch(() => null);
  if (!st) return;
  if (st.active) { hmDictShow('listen'); return; }
  if (st.busy) { hmDictShow('busy'); return; }
  clearInterval(hmDictTimer);
  if (st.error && !st.last_text) {
    hmDictHide();
    showToast(serverText(st.error));
    return;
  }
  hmDictShow('done', st.last_text);
  loadMeetingsList();  // the dictation is kept in the library, folder "Dictations"
}

function hmDictShow(mode, text) {
  const bar = document.getElementById('hm-dict');
  bar.classList.remove('hidden');
  bar.dataset.mode = mode;
  document.getElementById('hm-dict-title').textContent = t({ listen: 'hmDictListen', busy: 'hmDictBusy', done: 'hmDictHeard' }[mode]);
  document.getElementById('hm-dict-text').textContent = mode === 'done' ? text : t(mode === 'listen' ? 'hmDictListenSub' : 'hmDictBusySub');
  document.getElementById('hm-dict-lvl').classList.toggle('hidden', mode !== 'listen');
  document.getElementById('hm-dict-done').classList.toggle('hidden', mode !== 'listen');
  document.getElementById('hm-dict-copy').classList.toggle('hidden', mode !== 'done');
  document.getElementById('hm-dict-cancel').textContent = t(mode === 'done' ? 'close' : 'cancel');
  document.getElementById('hm-dict-btn')?.classList.toggle('hm-qa-on', mode === 'listen');
}

function hmDictHide() {
  document.getElementById('hm-dict').classList.add('hidden');
  document.getElementById('hm-dict-btn')?.classList.remove('hm-qa-on');
}

async function hmDictCancel() {
  clearInterval(hmDictTimer);
  if (document.getElementById('hm-dict').dataset.mode !== 'done') await fetch('/api/dictation/cancel', { method: 'POST' });
  hmDictHide();
}

async function hmDictCopy() {
  try { await navigator.clipboard.writeText(document.getElementById('hm-dict-text').textContent); showToast(t('copied'), null, 'success'); }
  catch (e) { showError(String(e.message || e)); }
}

// The tray's "Open the last recording" (run.py): the newest one of the library (read first when the
// window was just opened and the list has not come yet)
async function openLastRecording() {
  if (!(state.meetings || []).length) await loadMeetingsList().catch(() => {});
  const last = [...(state.meetings || [])].sort((x, y) =>
    String(y.recorded_at || y.created_at || '').localeCompare(String(x.recorded_at || x.created_at || '')))[0];
  if (last) openMeeting(last.id);
  else switchAppView('home');
}

// A click on a Windows notification (run.py App.open_target): the place it was about. "meeting:ID:KIND"
// opens the recording (a finished transcription on its text), "studio" the recording running, "last"
// the newest recording, "settings:TAB" that part of the settings
// The call of a calendar meeting: the server opens it (Teams in its app), only a link of a call service
async function joinMeetingCall(url) {
  const r = await fetch('/api/meeting/join', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url }) }).catch(() => null);
  if (r && r.ok) showToast(t('hmJoining')); else showError(t('hmJoinFailed'));
}

async function openFromNotice(target) {
  if (String(target || '').startsWith('join:')) { joinMeetingCall(String(target).slice(5)); return; }
  const [kind, a, b] = String(target || '').split(':');
  if (kind === 'meeting' && Number(a)) {
    if (!(state.meetings || []).length) await loadMeetingsList().catch(() => {});
    if (!(state.meetings || []).some(m => m.id === Number(a))) { openLastRecording(); return; }  // deleted since
    await openMeeting(Number(a));
    if (b === 'transcribe' || b === 'translate') openRecordTab('transcript');
  } else if (kind === 'studio') {
    switchAppView('studio');
    studioTab('text');
  } else if (kind === 'dashboard') {  // recordings whose transcription was cancelled (app/untranscribed.py)
    switchAppView('home');  // the reminder stands on «Сегодня»
  } else if (kind === 'last') {
    openLastRecording();
  } else if (kind === 'settings') {
    openModal('settings', a || undefined);
  } else if (kind === 'update') {  // a new version (app/updater.py notice_tick)
    openUpdateDialog();
  } else if (kind === 'brief') {  // «brief:series:ID» or «brief:person:NAME» (app/brief_notice.py)
    openBriefFor(a, String(target).split(':').slice(2).join(':'));
  }
}

// The brief before a meeting: what is open from the last meetings of its series (or with that person)
function openBriefFor(kind, value) {
  if (kind === 'series' && Number(value)) state.askScope = { type: 'series', id: Number(value) };
  else if (kind === 'person' && value) state.askScope = { type: 'person', name: value };
  else return;
  switchAppView('ask');
  if (typeof renderAskScope === 'function') renderAskScope();
  makeBrief();
}

// the view «home» is «Сегодня»: registered by static/js/today.js

document.addEventListener('DOMContentLoaded', () => {
  setInterval(hmAutoTick, 20000);
  setInterval(hmCallEndTick, 5000);
  setInterval(hmJoinTick, 4000);
  // the clock line and the processing on the page follow by themselves
  setInterval(() => { if (state.appView === 'home' && !document.hidden) renderHomeNow(); }, 30000);  // the dashboard: dbTickNow
});


// --- The calendar of a week or a month: the calendar's meetings and the recordings, side by side.
// A meeting recorded carries its recording (a click opens it); a recording outside any meeting comes
// on its own. Week or month is remembered on this computer ---
const calView = { mode: 'week', anchor: null, data: null, loading: false };
try { if (localStorage.getItem('verbaliox_cal_mode') === 'month') calView.mode = 'month'; } catch (e) {}

function calDayStart(d) { const x = new Date(d); x.setHours(0, 0, 0, 0); return x; }
function calAddDays(d, n) { const x = new Date(d); x.setDate(x.getDate() + n); return x; }
function calMonday(d) { const x = calDayStart(d); return calAddDays(x, -((x.getDay() + 6) % 7)); }
function calKey(d) { return `${d.getFullYear()}-${hmPad(d.getMonth() + 1)}-${hmPad(d.getDate())}`; }
function calTime(d) { return `${hmPad(d.getHours())}:${hmPad(d.getMinutes())}`; }

// The days shown: a week from Monday, or the weeks that hold the month (six at most)
// cv: the state of the calendar window, or that of «Сегодня» (static/js/today.js), which shows the same week and month
function calRange(cv = calView) {
  const anchor = cv.anchor || new Date();
  if (cv.mode === 'week') { const a = calMonday(anchor); return { a, b: calAddDays(a, 7), month: -1 }; }
  const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
  const a = calMonday(first);
  const last = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0);
  const b = calAddDays(calMonday(last), 7);
  return { a, b, month: anchor.getMonth() };
}

// The date tile of the dashboard: the calendar on this week (the user's week or month choice stays theirs)
function hmOpenWeek() {
  calView.mode = 'week';
  openCalendarView();
}

function openCalendarView() {
  calView.anchor = new Date();
  document.getElementById('cal-view')?.remove();
  const wrap = document.createElement('div');
  wrap.id = 'cal-view';
  wrap.className = 'fixed inset-0 modal-backdrop z-[60] flex items-center justify-center p-4';
  wrap.setAttribute('role', 'dialog');
  wrap.setAttribute('aria-modal', 'true');
  wrap.setAttribute('aria-label', t('calTitle'));
  wrap.addEventListener('click', e => {
    if (e.target === wrap) { closeCalendarView(); return; }
    const b = e.target.closest('[data-cal]');
    if (!b) return;
    const act = b.dataset.cal;
    if (act === 'close') closeCalendarView();
    else if (act === 'prev' || act === 'next') {
      const k = act === 'prev' ? -1 : 1;
      const x = new Date(calView.anchor);
      if (calView.mode === 'week') x.setDate(x.getDate() + 7 * k); else { x.setDate(1); x.setMonth(x.getMonth() + k); }
      calView.anchor = x; calLoad();
    } else if (act === 'today') { calView.anchor = new Date(); calLoad(); }
    else if (act === 'week' || act === 'month') {
      calView.mode = act;
      try { localStorage.setItem('verbaliox_cal_mode', act); } catch (err) {}
      calLoad();
    } else if (act === 'day') { calView.mode = 'week'; calView.anchor = new Date(b.dataset.day); calLoad(); }
    else if (act === 'dayoff') { const r = b.getBoundingClientRect(); calDayMenu(b.dataset.day, r.left, r.bottom + 4); }
    else if (act === 'rec') { closeCalendarView(); openMeeting(Number(b.dataset.id)); }
  });
  // a right click on a day: mark it a day off, or not (asked by the user)
  wrap.addEventListener('contextmenu', e => {
    const cell = e.target.closest('[data-daykey]');
    if (!cell) return;
    e.preventDefault();
    calDayMenu(cell.dataset.daykey, e.clientX, e.clientY);
  });
  document.addEventListener('keydown', calKeydown, true);
  document.body.appendChild(wrap);
  calLoad();
}

// A day of the calendar: a day off of one's own, marked or taken back here (days_off, as in Settings → Календарь)
function calDayMenu(day, x, y, reload = calLoad) {
  let list = [];
  try { list = JSON.parse(((state.system && state.system.settings) || {}).days_off || '[]'); } catch (e) {}
  if (!Array.isArray(list)) list = [];
  const hit = list.find(p => p.from <= day && day <= (p.to || p.from));
  const save = async next => {
    if (typeof saveDaysOff === 'function' && await saveDaysOff(next)) reload();
  };
  const shift = (k, n) => { const d = new Date(`${k}T12:00:00`); d.setDate(d.getDate() + n); return calKey(d); };
  const items = [];
  if (hit) {
    items.push({ info: true, label: hit.title || t('dayOffDefault') });
    // one day out of a period: the period is split around it
    items.push({ label: t('calDayOffRemove'), run: () => save(list.flatMap(p => p !== hit ? [p] : [
      ...(p.from < day ? [{ ...p, to: shift(day, -1) }] : []), ...((p.to || p.from) > day ? [{ ...p, from: shift(day, 1) }] : [])])) });
    if (hit.from !== (hit.to || hit.from)) items.push({ label: t('calDayOffRemoveAll'), run: () => save(list.filter(p => p !== hit)) });
  } else {
    items.push({ label: t('calDayOffMark'), run: () => save([...list, { from: day, to: day, title: t('dayOffDefault') }]) });
    items.push({ label: t('calVacationFrom'), run: () => {
      closeCalendarView();
      openModal('settings', 'general');
      selectSettingsTab('calendar');
      setTimeout(() => {
        const a = document.getElementById('dayoff-from'), b = document.getElementById('dayoff-to'), n = document.getElementById('dayoff-title');
        if (!a) return;
        a.value = day; b.value = shift(day, 6); n.value = t('dayOffNamePh');
        syncDateField(a); syncDateField(b);
        a.scrollIntoView({ block: 'center' });
      }, 300);
    } });
  }
  setTimeout(() => openTextMenuAt(items, x, y), 0);
}

function calKeydown(e) {
  if (e.key === 'Escape' && document.getElementById('cal-view')) { e.stopPropagation(); closeCalendarView(); }
}

function closeCalendarView() {
  document.getElementById('cal-view')?.remove();
  document.removeEventListener('keydown', calKeydown, true);
}

async function calLoad() {
  const { a, b } = calRange();
  const seq = (calView.seq = (calView.seq || 0) + 1);  // a quick ‹ › : only the last answer is shown (found in the audit)
  calView.loading = true;
  renderCalendarView();
  const [data, work] = await Promise.all([
    fetch(`/api/calendar/range?start=${encodeURIComponent(hmIso(a))}&end=${encodeURIComponent(hmIso(b))}&lang=${state.uiLang === 'en' ? 'en' : 'ru'}`)
      .then(r => (r.ok ? r.json() : null)).catch(() => null),
    fetch(`/api/worktime?start=${calKey(a)}&end=${calKey(b)}`).then(r => (r.ok ? r.json() : null)).catch(() => null),
  ]);
  if (seq !== calView.seq) return;
  calView.work = work && work.enabled ? work.days : {};
  calView.loading = false;
  calView.data = data;
  renderCalendarView();
}

// What a day holds, by time: meetings (with their recording) and recordings of their own
function calItems(cv = calView) {
  const byDay = {};
  const put = (d, item) => { (byDay[calKey(d)] = byDay[calKey(d)] || []).push(item); };
  const data = cv.data || {};
  for (const e of data.events || []) {
    const s = new Date(e.start), en = new Date(e.end);
    put(s, { kind: 'event', s, en, title: e.title || t('hmUntitled'), rec: e.recording, attendees: (e.attendees || []).length, location: e.location || '' });
  }
  for (const r of data.recordings || []) {
    const s = new Date(r.at);
    put(s, { kind: 'rec', s, title: r.title || t('hmUntitled'), id: r.id, duration: r.duration });
  }
  for (const k of Object.keys(byDay)) byDay[k].sort((x, y) => x.s - y.s);
  return byDay;
}

function calItemHtml(it, compact) {
  const time = calTime(it.s);
  if (it.kind === 'rec' || it.rec) {
    const id = it.kind === 'rec' ? it.id : it.rec.id;
    const tip = it.kind === 'rec' ? t('calRecTip') : t('calMeetingRecTip').replace('{title}', () => it.title);
    return `<button data-cal="rec" data-id="${Number(id) || 0}" class="cal-item ${it.kind === 'rec' ? 'cal-rec' : 'cal-ev cal-ev-rec'}" title="${escapeHtml(`${time} · ${it.title}\n${tip}`)}">
      <i class="cal-dot"></i><span class="cal-time">${time}</span><span class="cal-name">${escapeHtml(it.title)}</span></button>`;
  }
  const tip = [`${time}–${calTime(it.en)} · ${it.title}`, it.location, it.attendees ? t('calPeople').replace('{n}', () => it.attendees) : ''].filter(Boolean).join('\n');
  return `<div class="cal-item cal-ev${it.en < new Date() ? ' cal-past' : ''}" title="${escapeHtml(tip)}">
    <i class="cal-dot"></i><span class="cal-time">${time}</span><span class="cal-name">${escapeHtml(it.title)}</span></div>`;
}

// «16 нояб. – 22 нояб. 2026» or «ноябрь 2026 г.»: what a calendar state shows
function calLabel(cv = calView) {
  const { a, b } = calRange(cv), loc = hmLocale();
  return cv.mode === 'week'
    ? `${a.toLocaleDateString(loc, { day: 'numeric', month: 'short' })} – ${calAddDays(b, -1).toLocaleDateString(loc, { day: 'numeric', month: 'short', year: 'numeric' })}`
    : new Date(cv.anchor || new Date()).toLocaleDateString(loc, { month: 'long', year: 'numeric' });
}

function renderCalendarView() {
  const wrap = document.getElementById('cal-view');
  if (!wrap) return;
  const body = calBodyHtml(calView), label = calLabel(calView);
  const data = calView.data || {};
  const note = !calView.loading && !data.configured ? `<p class="cal-note">${escapeHtml(t('calNoCalendar'))}</p>`
    : data.error ? `<p class="cal-note">${escapeHtml(t('calError'))}: ${escapeHtml(serverText(data.error))}</p>` : '';
  const seg = m => `<button data-cal="${m}" class="cal-seg${calView.mode === m ? ' cal-seg-on' : ''}" aria-pressed="${calView.mode === m}">${escapeHtml(t(m === 'week' ? 'calWeek' : 'calMonth'))}</button>`;
  vxRedraw(wrap);
  wrap.innerHTML = `<div class="cal-dialog modal-card">
    <div class="cal-head">
      <span class="vx-head-ic" aria-hidden="true">${pultIcon('cal')}</span><h2 class="cal-title">${escapeHtml(t('calTitle'))}</h2>
      <div class="cal-segs" role="group">${seg('week')}${seg('month')}</div>
      <div class="cal-navs">
        <button data-cal="prev" class="cal-nav" aria-label="${escapeHtml(t('calPrev'))}" title="${escapeHtml(t('calPrev'))}">‹</button>
        <button data-cal="today" class="cal-today-btn">${escapeHtml(t('calToday'))}</button>
        <button data-cal="next" class="cal-nav" aria-label="${escapeHtml(t('calNext'))}" title="${escapeHtml(t('calNext'))}">›</button>
        <span class="cal-label">${escapeHtml(label)}</span>
      </div>
      <button data-cal="close" class="vx-x cal-close" aria-label="${escapeHtml(t('close'))}" title="${escapeHtml(t('close'))}">✕</button>
    </div>
    ${note}
    <div class="cal-body${calView.loading ? ' cal-loading' : ''}">${body}</div>
    <div class="cal-legend"><span><i class="cal-dot cal-lg-ev"></i>${escapeHtml(t('calLgMeeting'))}</span>
      <span><i class="cal-dot cal-lg-evrec"></i>${escapeHtml(t('calLgMeetingRec'))}</span>
      <span><i class="cal-dot cal-lg-rec"></i>${escapeHtml(t('calLgRec'))}</span></div>
  </div>`;
  wrap.querySelector('.cal-dialog').style.maxHeight = `${Math.round(viewH() - 32)}px`;
}

// The days of a calendar state (the window's, or that of «Сегодня»), a week or a month, with what they hold
function calBodyHtml(cv) {
  const { a, b, month } = calRange(cv);
  const loc = hmLocale();
  const today = calKey(new Date());
  const items = calItems(cv);
  const days = [];
  for (let d = new Date(a); d < b; d = calAddDays(d, 1)) days.push(d);
  const weekday = d => d.toLocaleDateString(loc, { weekday: 'short' }).replace('.', '');
  let body;
  const hols = (cv.data && cv.data.holidays) || {};  // public holidays (Settings → Календарь → Праздники)
  // «⋯» of a day: mark it a day off (shown on hover; a right click does the same)
  const dayBtn = d => `<button data-cal="dayoff" data-day="${calKey(d)}" class="cal-day-more" title="${escapeHtml(t('calDayMenuTip'))}" aria-label="${escapeHtml(t('calDayMenuTip'))}">⋯</button>`;
  // the hours worked of a day, by fact (app/worktime.py)
  const wkTag = d => { const w = (cv.work || {})[calKey(d)]; return w && w.worked ? `<span class="cal-wk" title="${escapeHtml(`${t('dbWorkedTip').replace('{t}', () => dbHm(w.worked * 60))} · ${w.start}–${w.end}`)}">${escapeHtml(dbWorkedShort(w.worked))}</span>` : ''; };
  // a day off (a weekend, a holiday or one's own) is hatched; a working day gone by is a step dimmer
  const dayKind = d => ((d.getDay() + 6) % 7 >= 5 || hols[calKey(d)] ? ' cal-offday' : calKey(d) < today ? ' cal-pastday' : '');
  const holTag = d => hols[calKey(d)] ? `<span class="cal-hol" title="${escapeHtml(hols[calKey(d)])}">${escapeHtml(hols[calKey(d)])}</span>` : '';
  // cv.dayTip («Сегодня»): a click on a day (not on what it holds) opens that day; the window opens its week
  const dayTip = t(cv.dayTip || 'calOpenWeek');
  const open = cv.dayTip ? ` cal-open" title="${escapeHtml(dayTip)}` : '';
  if (cv.mode === 'week') {
    body = `<div class="cal-week">${days.map(d => {
      const list = items[calKey(d)] || [];
      return `<div class="cal-col${calKey(d) === today ? ' cal-today' : ''}${hols[calKey(d)] ? ' cal-holday' : ''}${dayKind(d)}${open}" data-daykey="${calKey(d)}">
        <div class="cal-col-head"><span>${escapeHtml(weekday(d))}</span><b>${d.getDate()}</b>${wkTag(d)}${dayBtn(d)}</div>${holTag(d)}
        <div class="cal-col-list">${list.length ? list.map(it => calItemHtml(it, false)).join('') : `<span class="cal-none">—</span>`}</div></div>`;
    }).join('')}</div>`;
  } else {
    const heads = days.slice(0, 7).map(d => `<div class="cal-mhead">${escapeHtml(weekday(d))}</div>`).join('');
    body = `<div class="cal-month">${heads}${days.map(d => {
      const list = items[calKey(d)] || [];
      const more = list.length - 3;
      return `<div class="cal-cell${d.getMonth() !== month ? ' cal-out' : ''}${calKey(d) === today ? ' cal-today' : ''}${hols[calKey(d)] ? ' cal-holday' : ''}${dayKind(d)}${open}" data-daykey="${calKey(d)}">
        <div class="cal-cell-head"><button data-cal="day" data-day="${calKey(d)}T12:00" class="cal-num" title="${escapeHtml(dayTip)}">${d.getDate()}</button>${wkTag(d)}${dayBtn(d)}</div>${holTag(d)}
        ${list.slice(0, 3).map(it => calItemHtml(it, true)).join('')}
        ${more > 0 ? `<button data-cal="day" data-day="${calKey(d)}T12:00" class="cal-more" title="${escapeHtml(dayTip)}">${escapeHtml(t('calMore').replace('{n}', () => more))}</button>` : ''}</div>`;
    }).join('')}</div>`;
  }
  return body;
}
