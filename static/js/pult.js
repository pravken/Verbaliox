// Verbaliox page script: «Пульт встреч» (docs/pult-plan.md, stages 1–2). The strip of the meeting at the top,
// the «Очередь» island of the strip and its window, the load indicator of the status bar and its window.
// The parts are classic scripts sharing one global scope, loaded in order by index.html.

// --- The strip of the meeting ---
// One state at a time, the most pressing first: recording, a meeting going on without a recording, a meeting
// within 15 minutes, the recording just made (waiting for its transcription, then its summary ready), a free
// day or a day off. Order everywhere: the pill, the meeting, its details, the buttons of the state.
const STRIP_SOON_MS = 15 * 60e3;
const STRIP_RECENT_MS = 3 * 3600e3;  // the recording just made stays on the strip this long
const STRIP_RETRY_MS = 45000;  // after a failed load: the next try this much later, not on the next redraw
const strip = { events: [], holidays: {}, configured: false, at: 0, failAt: 0, loading: null, call: null, callAt: 0, callOff: false,
  skip: new Set(), html: '', click: null };
let stripSeen = new Set();  // recordings whose «Итоги готовы» were opened or hidden
try { stripSeen = new Set(JSON.parse(localStorage.getItem('verbaliox_strip_seen') || '[]')); } catch (e) { /* storage off */ }

function stripRemember() {
  try { localStorage.setItem('verbaliox_strip_seen', JSON.stringify([...stripSeen].slice(-50))); } catch (e) { /* storage off */ }
}

function stripClock(d) { return `${hmPad(d.getHours())}:${hmPad(d.getMinutes())}`; }
function stripDayStart(d) { const x = new Date(d); x.setHours(0, 0, 0, 0); return x; }

// The meetings of today and of the week ahead (the next one after a free day), and the public holidays
// (every 5 minutes; every minute while a meeting starts within the hour: a meeting moved or cancelled in the calendar
// leaves the strip sooner, the server reads the calendar more often then, app/brief_notice.py keep_fresh)
async function stripLoad(force) {
  if (!force && Date.now() - strip.at < (hmSoonMeeting(strip.events) ? HM_EVENTS_SOON_MS : 300000)) return;
  // a failed answer redraws the strip, which asks again: without this pause, a request loop
  if (!force && Date.now() - strip.failAt < STRIP_RETRY_MS) return;
  if (strip.loading) return strip.loading;
  strip.loading = (async () => {
    const a = stripDayStart(new Date()), b = new Date(a.getTime() + 8 * 86400e3);
    const data = await fetch(`/api/calendar/range?start=${encodeURIComponent(hmIso(a))}&end=${encodeURIComponent(hmIso(b))}&lang=${state.uiLang === 'en' ? 'en' : 'ru'}`)
      .then(r => (r.ok ? r.json() : null)).catch(() => null);
    if (!data) { strip.failAt = Date.now(); return; }
    strip.failAt = 0;
    strip.at = Date.now();
    strip.configured = !!data.configured;
    strip.holidays = data.holidays || {};
    strip.events = (data.events || []).map(e => ({ ...e, s: new Date(e.start), e: new Date(e.end) }))
      .filter(e => !e.all_day && e.e - e.s < DB_BLOCK_MS && !hmIsIgnored(e))
      .sort((x, y) => x.s - y.s);
  })().finally(() => { strip.loading = null; renderStrip(); });
  return strip.loading;
}

// A call app holding the microphone (app/call_watch.py), looked at every 15 s while nothing records
async function stripCallTick() {
  if (strip.callOff || document.hidden || isRecording() || Date.now() - strip.callAt < 15000) return;
  strip.callAt = Date.now();
  const st = await fetch('/api/calls/status').then(r => (r.ok ? r.json() : null)).catch(() => null);
  if (!st) return;
  if (!st.supported) { strip.callOff = true; strip.call = null; return; }
  const app = (st.apps || []).find(a => a.id === st.meeting_app);  // a browser alone is no call
  const prev = strip.call;
  strip.call = app ? app.name : null;
  // «Не записывать» was for that call: once it is over, the next call of the same app is shown again
  if (prev && prev !== strip.call) strip.skip.delete(`call:${prev}`);
}

// The service of a meeting's call, from its link
function stripService(e) {
  const url = String((e && e.join) || '');
  if (/teams\.(microsoft|live)\.com/i.test(url)) return 'Teams';
  if (/zoom\.(us|com)/i.test(url)) return 'Zoom';
  if (/meet\.google\.com/i.test(url)) return 'Google Meet';
  if (/webex\.com/i.test(url)) return 'Webex';
  return e && e.online ? t('hmOnline') : (e && e.location) || '';
}

function stripWhenNext(e) {
  const now = new Date(), d0 = stripDayStart(now).getTime(), d = stripDayStart(e.s).getTime();
  const day = d === d0 ? '' : d === d0 + 86400e3 ? t('stripTomorrow')
    : e.s.toLocaleDateString(hmLocale(), { weekday: 'short', day: 'numeric', month: 'short' }).replace('.', '');
  return `${day ? `${day}, ` : ''}${stripClock(e.s)}`;
}

// Today is a day off: one marked in Settings → Календарь, a public holiday, or Saturday and Sunday
function stripDayOff() {
  const key = calKey(new Date());
  let list = [];
  try { list = JSON.parse(hmSettings().days_off || '[]'); } catch (e) { list = []; }
  const own = (Array.isArray(list) ? list : []).find(p => p.from <= key && key <= (p.to || p.from));
  if (own) return own.title || t('dayOffDefault');
  if (strip.holidays[key]) return strip.holidays[key];
  const wd = new Date().getDay();
  return wd === 0 || wd === 6 ? ' ' : '';
}

// The recording made last, from this program, within the last three hours
function stripRecent() {
  const now = Date.now();
  const recs = (state.meetings || []).filter(m => m.source === 'recording')
    .map(m => ({ m, at: Date.parse(String(m.completed_at || m.created_at || '').replace(' ', 'T')) }))
    .filter(x => x.at && now - x.at < STRIP_RECENT_MS)
    .sort((x, y) => y.m.id - x.m.id);
  return recs.length ? recs[0].m : null;
}

function stripState() {
  const now = Date.now(), recording = isRecording();
  const live = strip.events.find(e => e.s.getTime() <= now && now < e.e.getTime());
  const next = strip.events.find(e => e.s.getTime() > now);
  const act = (fn, args, label, cls = '', title = '') => ({ fn, args, label, cls, title });
  const joinAct = e => (e && e.join ? act('joinMeetingCall', [e.join], t('hmJoin'), 'go', t('hmJoinTip')) : null);
  if (recording) {
    const title = document.getElementById('record-title-input')?.value.trim() || (hmAutoRec && hmAutoRec.title) || (live && live.title) || t('stripRecUntitled');
    const lines = typeof liveCap !== 'undefined' && liveCap.session ? [...liveCap.lines.values()] : [];
    const last = lines.length ? lines[lines.length - 1] : null;
    const notes = document.getElementById('studio-notes-input')?.value || '';
    const marks = (notes.match(/⚑/g) || []).length;
    return { kind: 'rec', pill: t('stripRecording'), cls: 'red live', lead: title,
      meta: state.callRecording ? (strip.call || '') : live ? stripService(live) : '',
      grow: last && last.text ? `${last.speaker ? `${last.speaker}: ` : ''}«${last.text}»` : marks ? plural(marks, t('stripMarkForms')) : '',
      growCls: last ? 'live' : '', click: 'studio', tip: t('stripOpenLive'),
      // the way to the studio is the «Студия» chip of the recording button (asked by the user: the button here repeated it)
      acts: [act('studioMark', [], `★ ${t('stripMark')}`, '', t('stripMarkTip'))] };
  }
  const liveMeeting = live && !strip.skip.has(live.key) ? live : null;
  if (liveMeeting || (strip.call && !strip.skip.has(`call:${strip.call}`))) {
    const e = liveMeeting;
    const st = e ? hmMeetingState(e) : '';
    // its recording was made and stopped before the meeting's end: said so, not «Автозапись не началась»
    const stopped = !!e && (home.started.has(e.key) || !!e.recording);
    const why = stopped ? 'stripWhyStopped'
      : { off: 'stripWhyOff', never: 'stripWhyNever', skipped: 'stripWhySkipped', on: 'stripWhyLate', ask: 'stripWhyLate' }[st] || 'stripWhyCall';
    // Only what is needed (asked by the user: the strip held too much): the state, the meeting, one action. «Подключиться»
    // only while no call holds the microphone (in the call already, it has no use); «Не записывать» is the ✕ at the end;
    // the service and the minutes went (the title says the meeting), the reason is the pill's tooltip
    return { kind: 'unrec', pill: t(stopped ? 'stripRecStopped' : 'stripUnrec'), cls: 'amber', lead: e ? e.title || t('hmUntitled') : strip.call,
      meta: e ? '' : t('stripCall'),
      grow: '', pillTip: t(why),  // the reason was cut to «Автозапись для…»: it is the pill's tooltip now
      acts: [strip.call ? null : joinAct(e),
        // stopped by the user: no «Записать снова» (asked by the user: the red «Запись» is there for it)
        stopped ? null : act(e ? 'hmRecordNow' : 'shellQuickRecord', e ? [e.key] : [], `● ${t('stripRecordRest')}`, 'warn', t('stripRecordRestTip')),
        { ...act('stripSkip', [e ? e.key : `call:${strip.call}`], '✕', 'x', t('stripDontRecordTip')), icon: true }].filter(Boolean) };
  }
  if (next && next.s.getTime() - now <= STRIP_SOON_MS) {
    const min = Math.max(1, Math.ceil((next.s.getTime() - now) / 60e3));
    const known = home.events.find(x => x.key === next.key);
    const bf = known && known.before;
    const people = (next.attendees || []).map(a => String(a).replace(/@.*$/, '')).filter(Boolean).slice(0, 4).join(', ');
    return { kind: 'soon', pill: t('stripSoon').replace('{n}', () => min), cls: 'blue', lead: next.title || t('hmUntitled'),
      meta: [`${stripClock(next.s)}–${stripClock(next.e)}`, stripService(next)].filter(Boolean).join(' · '),
      grow: people,
      // the open tasks of last time open the brief with them (asked by the user), as on the meeting's card in «Сегодня»
      growLink: bf && bf.open_tasks ? { fn: 'openBriefFor', args: bf.series_id ? ['series', bf.series_id] : ['person', bf.person],
        label: t('stripOpenTasks').replace('{n}', () => bf.open_tasks),
        tip: t('hmBriefTip').replace('{n}', () => bf.open_tasks).replace('{title}', () => bf.last.title).replace('{date}', () => bf.last.date) } : null,
      acts: [joinAct(next)].filter(Boolean) };
  }
  const m = stripRecent();
  if (m && !DONE_STATUSES.includes(m.status)) {
    const q = (state.queue || []).find(x => x.id === m.id);
    const running = q && q.state === 'running';
    const mins = Math.max(1, Math.round((m.duration || 0) / 60));
    // the tracks of a stopped recording being mixed: not a wait for the transcription (reported by the user)
    const mixing = m.status === 'mixing';
    const open = state.appView === 'library' && state.activeMeeting && state.activeMeeting.id === m.id;
    const grow = mixing ? txStageParts(m).detail : running ? serverText(m.stage_text || q.stage_text || '')
      : holdPause() ? t('stripWaitPause').replace('{time}', () => holdClock())
      : state.queueMeeting && !(q && q.forced) ? t('stripWaitMeeting') : state.queuePaused ? t('stripWaitPaused')
      : q && q.hold === 'captions' ? t('stripWaitCaptions')
      : typeof economyOn === 'function' && economyOn() ? t('stripWaitEconomy') : q ? t('queueWaiting').replace('{n}', () => q.position) : '';
    return { kind: 'after', pill: mixWaiting(m) ? mixWaitPill(m) : mixing ? t('stripMixing').replace('{pct}', () => m.progress || 0)
      : running ? t('stripProcessing').replace('{pct}', () => m.progress || 0) : t('stripWaiting'), cls: running || mixing ? 'blue' : 'grey',
      lead: m.title || t('hmUntitled'), meta: m.duration ? t('stripRecorded').replace('{n}', () => mins) : '', grow, click: m.id, tip: t('tbRecOpen'),
      // the recording already open: no «Открыть запись» that does nothing
      acts: open ? [] : [act('openMeeting', [m.id], t('tbRecOpen'), 'ghost')] };
  }
  if (m && m.status === 'completed' && !stripSeen.has(m.id)) {
    const mins = Math.max(1, Math.round((m.duration || 0) / 60));
    return { kind: 'ready', pill: t(m.has_summary ? 'stripReady' : 'stripTextReady'), cls: 'green', lead: m.title || t('hmUntitled'),
      meta: m.duration ? t('stripRecorded').replace('{n}', () => mins) : '', grow: '', click: m.id, tip: t('stripOpenSummary'),
      acts: [act('stripOpenSummary', [m.id], t(m.has_summary ? 'stripOpenSummary' : 'tbRecOpen'), 'go'), act('stripHide', [m.id], t('stripHide'), 'ghost')] };
  }
  const nextText = next ? t('stripNext').replace('{when}', () => stripWhenNext(next)).replace('{title}', () => next.title || t('hmUntitled')) : '';
  if (!strip.configured) {
    // the hint in the part that gives way with «…» (as a fixed part it was cut off mid-word at 1100 px: audit)
    return { kind: 'free', pill: t('stripNoCalendar'), cls: 'grey', lead: '', meta: '', grow: t('stripNoCalendarSub'),
      acts: [act('stripOpenCalendarSettings', [], t('stripConnect'), 'ghost')] };
  }
  const today = next && stripDayStart(next.s).getTime() === stripDayStart(new Date()).getTime();
  const off = !today && stripDayOff();
  if (off) {
    return { kind: 'off', pill: t('stripDayOff'), cls: 'grey', lead: off.trim(), meta: nextText || t('stripNoWeek'), grow: '', acts: [] };
  }
  return { kind: 'free', pill: today ? t('stripFreeUntil').replace('{time}', () => stripClock(next.s)) : t('stripFreeDay'), cls: 'green',
    lead: '', meta: nextText || t('stripNoWeek'), grow: '', acts: [] };
}

function renderStrip() {
  const bar = document.getElementById('app-strip');
  if (!bar) return;
  stripLoad(false);
  stripCallTick();
  const s = stripState();
  strip.click = s.click || null;
  strip.kind = s.kind;
  const acts = s.acts.map(a => `<button ${pageCall('click', a.fn, a.args)} class="st-btn${a.cls ? ` st-btn-${a.cls}` : ''}"${a.title ? ` title="${escapeHtml(a.title)}"` : ''}${a.icon ? ` aria-label="${escapeHtml(a.title)}"` : ''}>${a.icon ? `<span aria-hidden="true">${escapeHtml(a.label)}</span>` : escapeHtml(a.label)}</button>`).join('');
  const sig = JSON.stringify([s.kind, s.pill, s.pillTip, s.cls, s.lead, s.meta, s.grow, s.growLink, acts, s.tip]);
  if (sig === strip.html) return;
  strip.html = sig;
  bar.className = `strip strip-${s.kind}`;
  const pill = document.getElementById('strip-pill');
  pill.className = `st-pill ${s.cls.split(' ').map(c => `stp-${c}`).join(' ')}`;
  document.getElementById('strip-pill-t').textContent = s.pill;
  if (s.pillTip) pill.title = s.pillTip; else pill.removeAttribute('title');
  const put = (id, v) => { const el = document.getElementById(id); el.textContent = v || ''; el.classList.toggle('hidden', !v); };
  // the title: when it is cut, a hover scrolls it to its end and back (asked by the user, instead of a running line)
  const lead = document.getElementById('strip-lead');
  lead.innerHTML = s.lead ? `<span class="strip-lead-t">${escapeHtml(s.lead)}</span>` : '';
  lead.classList.toggle('hidden', !s.lead);
  lead.title = s.lead || '';
  requestAnimationFrame(() => {
    const over = lead.scrollWidth - lead.clientWidth;
    lead.classList.toggle('strip-lead-over', over > 4);
    lead.style.setProperty('--lead-shift', `${-over}px`);
    lead.style.setProperty('--lead-time', `${Math.min(6, Math.max(1.2, over / 40))}s`);
  });
  put('strip-meta', s.meta);
  const g = s.growLink;
  document.getElementById('strip-grow').innerHTML = (g
    ? `<button type="button" class="strip-link-b" ${pageCall('click', 'stopThen', [{ $: 'event' }, g.fn, ...g.args])} title="${escapeHtml(g.tip || '')}">${escapeHtml(g.label)}</button>${s.grow ? ' · ' : ''}`
    : '') + escapeHtml(s.grow || '');
  document.getElementById('strip-grow').className = `strip-grow${s.growCls ? ` strip-grow-${s.growCls}` : ''}`;
  const main = document.getElementById('strip-main');
  main.classList.toggle('strip-link', !!s.click);
  // no tooltip: in the window of the app it was drawn over the strip's own text at the pointer (reported by the user);
  // the strip says what it opens with its button, and a screen reader hears it
  main.removeAttribute('title');
  if (s.click && s.tip) main.setAttribute('aria-label', [s.pill, s.lead, s.tip].filter(Boolean).join(' · ')); else main.removeAttribute('aria-label');
  // reached by the keyboard too while it opens something (Enter and Space: core.js)
  if (s.click) { main.setAttribute('role', 'button'); main.tabIndex = 0; } else { main.removeAttribute('role'); main.removeAttribute('tabindex'); }
  document.getElementById('strip-acts').innerHTML = acts;
}

// A click on the meeting: the recording's screen while it records, the recording (its summary) after
function stripOpen() {
  const c = strip.click;
  if (!c) return;
  if (c === 'studio') switchAppView('studio');
  else if (strip.kind === 'ready') stripOpenSummary(c);
  else openMeeting(c);
}

// «Открыть итоги»: the recording on «Анализ» once it is loaded (a slow answer opened «Расшифровка»)
async function stripOpenSummary(id) {
  stripSeen.add(id);
  stripRemember();
  renderStrip();
  await openMeeting(id);
  if (state.activeMeeting && state.activeMeeting.id === id && typeof openRecordTab === 'function') openRecordTab('summary');
}

function stripHide(id) {
  stripSeen.add(id);
  stripRemember();
  renderStrip();
}

// «Не записывать»: the strip leaves this meeting (or this call) alone until it is over. A meeting during a call
// leaves the call too: else the strip came back at once with the call, and one press was not enough
function stripSkip(key) {
  strip.skip.add(key);
  if (strip.call) strip.skip.add(`call:${strip.call}`);
  renderStrip();
}

function stripOpenCalendarSettings() {
  openModal('settings', 'general');
  selectSettingsTab('calendar');
}

// --- «Очередь»: the window of the strip's island (and of the status bar) ---
const jobs = { open: false, at: 'island', html: '' };
const PANEL_ICON = {
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  chart: '<path d="M4 19h16"/><path d="M7 16v-5M12 16V7M17 16v-8"/>',
};
const panelHead = (id, icon, title) => `<div class="vx-panel-h"><span class="vx-panel-ic" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${PANEL_ICON[icon]}</svg></span><h4 id="${id}">${escapeHtml(title)}</h4></div>`;

// Why the queue waits, or nothing
// The same reasons in a few words, for the island (the sentence of jobsHold took the whole strip: reported by the
// user, its text slid under the buttons); the sentence stays in the island's tooltip and the queue window
function jobsHoldShort() {
  if (typeof economyOn === 'function' && economyOn()) return t('islandHoldEconomy');
  if (state.queuePaused) return t('islandHoldPaused');
  if (holdPause()) return t('islandHoldPause').replace('{time}', () => holdClock());
  if (state.queueMeeting) return t('islandHoldMeeting');
  if (captionsHeld()) return t('islandHoldCaptions');
  return '';
}

function jobsHold() {
  if (typeof economyOn === 'function' && economyOn()) return t('jobsHoldEconomy');
  if (state.queuePaused) return t('jobsHoldPaused');
  if (holdPause()) return t('jobsHoldPause').replace('{time}', () => holdClock());
  if (state.queueMeeting) return t('jobsHoldMeeting');
  if (captionsHeld()) return t('jobsHoldCaptions');
  return '';
}

// A transcription waits for the end of the live captions (the server's queue: hold "captions"): it would load a
// second copy of the model the captions use (app/transcriber.waits_for_captions)
function captionsHeld() {
  return (state.queue || []).some(q => q.hold === 'captions' && q.state !== 'running');
}

// «Не мешать на встречах» holds the transcriptions: while a meeting goes on, or during the pause of 2 minutes after
// it (asked by the user: the window said «ждёт конца встречи» with no meeting going on). The pause counts down
function holdPause() {
  return !!(state.queueMeeting && state.queueHold && state.queueHold.kind === 'pause');
}
function holdLeft() {
  return holdPause() ? Math.max(0, Math.ceil((state.queueHold.end - Date.now()) / 1000)) : 0;
}
function holdClock() {
  const s = holdLeft();
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}
// The waiting text of a transcription held by a meeting (not one the user let go during it) or by the live
// captions, or '' (the item waits for something else)
function holdItemText(q, meetingKey) {
  if (q.kind !== 'transcribe' || q.state === 'running') return '';
  if (state.queueMeeting && !q.forced) return holdPause() ? t('jobsWaitPause').replace('{time}', () => holdClock()) : t(meetingKey);
  return q.hold === 'captions' ? t('jobsWaitCaptions') : '';
}
// Each second of the pause: the island, the queue's window, the strip and the status bar show the time left; at
// its end the queue is asked again (the transcriptions start), and every 5 s while the server still holds them
// (found in review: «0:00» stayed until the next poll). asked: when it was last asked, 0 during the pause
const holdTimer = { id: null, asked: 0 };
function holdTick() {
  if (!holdPause()) { clearInterval(holdTimer.id); holdTimer.id = null; holdTimer.asked = 0; return; }
  if (!holdTimer.id) holdTimer.id = setInterval(holdTick, 1000);
  renderJobsIsland();
  renderJobsPop();
  if (typeof renderQueuePanel === 'function') renderQueuePanel();
  if (typeof renderStatusbar === 'function') renderStatusbar();
  if (typeof strip !== 'undefined' && strip.kind === 'after' && typeof renderStrip === 'function') renderStrip();
  if (holdLeft()) holdTimer.asked = 0;  // a new pause: asked again at its end
  else if (Date.now() - holdTimer.asked >= 5000 && typeof loadQueue === 'function') {
    const first = !holdTimer.asked;
    holdTimer.asked = Date.now();
    setTimeout(() => loadQueue().catch(() => {}), first ? 1500 : 0);
  }
}

// «Начать сейчас» of a transcription waiting for the end of a meeting: asked as «Расшифровать» asks during a meeting
// (static/js/workspace.js transcribeWithPickedModel)
async function jobsRunNow(id) {
  const q = (state.queue || []).find(x => x.id === id) || {};
  const pause = holdPause();
  // what the item says it waits for: the meeting (or the pause after it), else the live captions
  const captions = (!state.queueMeeting || q.forced) && q.hold === 'captions';
  const [title, text] = captions ? ['txCaptionsNowTitle', 'txCaptionsNowText']
    : pause ? ['txPauseNowTitle', 'txPauseNowText'] : ['txMeetingNowTitle', 'txMeetingNowText'];
  if (!await confirmDialog(t(title), t(text), t('txMeetingNowYes'), false)) return;
  const res = await fetch(`/api/queue/${Number(id) || 0}/run-now`, { method: 'POST' }).catch(() => null);
  if (!res || !res.ok) { showToast(res ? errorText(await readJson(res), res) : t('errorGeneric')); return; }
  showToast(t('txMeetingNowStarted'));
  if (typeof loadQueue === 'function') loadQueue().catch(() => {});
}

// «Очередь» as an island in the top strip (asked by the user: the rail's button said «Очередь пуста» most of the
// time): nothing while nothing runs; a capsule before «＋ Импорт» with a progress ring and the job, «+N в очереди»;
// «Готово» for a moment when the last job ends. The strip itself already tells about its recording: then the capsule
// keeps only the count of the others, or only its ring (the queue window, with «Пауза» and «Отменить всё», is opened
// from here alone). A click opens the queue's window under it.
const island = { doneTimer: null, html: '', cancelAt: 0 };
function islandRing(pct) {
  const c = 56.5, d = Math.max(2, Math.min(100, pct || 0)) / 100 * c;
  return `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="rgba(255,255,255,.12)" stroke-width="3"/>`
    + `<circle cx="12" cy="12" r="9" fill="none" stroke="var(--accent)" stroke-width="3" stroke-linecap="round" stroke-dasharray="${d.toFixed(1)} ${c}" transform="rotate(-90 12 12)"/></svg>`;
}
// The queue cancelled (all of it, or its last job): it ends without «Готово» (the jobs may still be listed a moment
// while they stop, so a time, not a flag the next drawing would clear)
function islandCancelled() { island.cancelAt = Date.now(); }
function islandHide(el) {
  island.html = '';
  el.classList.add('hidden');
  el.innerHTML = '';
  if (jobs.open && jobs.at === 'island') closeJobsPop();
}
function renderJobsIsland() {
  let el = document.getElementById('strip-island');
  if (!el) {
    const acts = document.getElementById('strip-acts');
    if (!acts) return;
    el = document.createElement('button');
    el.id = 'strip-island';
    el.type = 'button';
    el.className = 'st-island hidden';
    el.setAttribute('aria-haspopup', 'dialog');
    el.setAttribute('aria-expanded', 'false');
    el.dataset.click = 'toggleJobsPop';
    el.dataset.clickArgs = '["island"]';
    acts.after(el);
  }
  const items = state.queue || [];
  const q = items.find(x => x.state === 'running');
  let html = '', cls = '', label = '', tipMore = '';
  if (items.length) {
    clearTimeout(island.doneTimer);
    island.doneTimer = null;
    const others = items.filter(x => x !== q).length;
    tipMore = others ? t('islandMoreSolo').replace('{n}', () => others) : '';  // the island shows «+N» only
    const moreText = others ? t('islandMore').replace('{n}', () => others) : '';
    const more = others ? `<span class="st-island-n">${escapeHtml(moreText)}</span>` : '';
    // the strip already says how its own recording goes: only the others then, or the ring alone
    const told = q && strip.kind === 'after' && strip.click === q.id;
    const m = q ? (state.meetings || []).find(x => x.id === q.id) || {} : {};
    const pct = q ? m.progress ?? q.progress ?? 0 : 0;
    if (q && !told) {
      label = `${queueKindLabel(q)} · ${pct}%`;
      html = `${islandRing(pct)}<span class="st-island-t">${escapeHtml(label)}</span>${more}`;
    } else if (!q) {
      label = jobsHold() || t('islandWaiting');
      const short = jobsHoldShort() || t('islandWaiting');
      html = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9" opacity=".45"/><path d="M10 9v6M14 9v6"/></svg>`
        + `<span class="st-island-t">${escapeHtml(short)}</span>${more}`;
      cls = 'st-island-wait';
    } else if (others) {
      label = t('islandMoreSolo').replace('{n}', () => others);  // alone, «+1» would say nothing
      html = `<span class="st-island-n st-island-solo">${escapeHtml(label)}</span>`;
    } else {
      label = `${queueKindLabel(q)} · ${pct}%`;
      html = islandRing(pct);
      cls = 'st-island-ring';
    }
  } else if (island.html && !island.doneTimer && Date.now() - island.cancelAt > 20000) {
    // the last job ended while the island was in sight: «Готово» for a moment
    label = t('islandDone');
    html = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.6 2.6L16 9.8"/></svg><span class="st-island-t">${escapeHtml(label)}</span>`;
    cls = 'st-island-done';
    island.doneTimer = setTimeout(() => { island.doneTimer = null; islandHide(el); }, 2600);
  } else if (island.doneTimer) {
    return;  // «Готово» is shown
  }
  const sig = cls + html;
  if (sig === island.html) return;
  if (!html) { islandHide(el); return; }
  const appear = el.classList.contains('hidden');
  island.html = sig;
  el.innerHTML = html;
  el.className = `st-island ${cls}`;
  el.title = [t('rlTipQueue'), label, label !== tipMore ? tipMore : ''].filter(Boolean).join(' · ');
  el.setAttribute('aria-label', el.title);
  if (appear) animateIn(el);
}

function renderJobsPop() {
  const pop = document.getElementById('jobs-pop');
  if (!pop || !jobs.open) return;
  const items = state.queue || [];
  const hold = jobsHold();
  const sub = hold || (items.length ? t('jobsSubBusy') : t('jobsSubEmpty'));
  const rows = items.map(q => {
    const m = (state.meetings || []).find(x => x.id === q.id) || {};
    const running = q.state === 'running';
    const pct = running ? (m.progress ?? q.progress ?? 0) : 0;
    const val = q.cancelling ? t('queueCancelling')
      : running ? `${pct}%`
      : state.queuePaused ? t('queuePausedItem')
      : holdItemText(q, 'jobsWaitMeeting') || t('queueWaiting').replace('{n}', () => q.position);
    // held by the meeting: «Начать сейчас» under it, after the user's «Да»
    const held = !q.cancelling && !state.queuePaused && !(typeof economyOn === 'function' && economyOn()) && !!holdItemText(q, 'jobsWaitMeeting');
    const tip = t('jobsOpenTip').replace('{title}', () => q.title || '');
    return `<div class="vx-prow vx-link" ${pageCall('click', 'jobsOpen', [q.id])} role="button" tabindex="0" title="${escapeHtml(tip)}">`
      + `<span class="vx-prow-t"><b>${escapeHtml(queueKindLabel(q))}</b><small>${escapeHtml(q.title || '')}</small></span>`
      + `<span class="vx-val ${running ? 'vx-run' : 'vx-wait'}">${escapeHtml(val)}</span>`
      + `<button ${pageCall('click', 'stopThen', [{ $: 'event' }, 'cancelProcessing', Number(q.id) || 0])} class="vx-x${q.cancelling ? ' invisible' : ''}" title="${escapeHtml(t('tipQueueCancel'))}" aria-label="${escapeHtml(t('tipQueueCancel'))}">✕</button>`
      + (running ? `<span class="vx-pbar"><b style="width:${Math.max(3, pct)}%"></b></span>` : '')
      + (held ? `<span class="vx-prow-go"><button ${pageCall('click', 'stopThen', [{ $: 'event' }, 'jobsRunNow', Number(q.id) || 0])} class="st-btn st-btn-sm" title="${escapeHtml(t(state.queueMeeting && !q.forced ? 'jobsRunNowTip' : 'jobsRunNowCaptionsTip'))}">${escapeHtml(t('jobsRunNow'))}</button></span>` : '')
      + '</div>';
  }).join('');
  const foot = items.length
    ? `<div class="vx-foot"><button data-click="toggleQueuePause" class="st-btn">${escapeHtml(t(state.queuePaused ? 'queueResume' : 'queuePause'))}</button>`
      + `<button data-click="cancelWholeQueue" class="st-btn st-btn-ghost">${escapeHtml(t('queueCancelAllOk'))}</button></div>` : '';
  const html = panelHead('jobs-pop-title', 'clock', t('rlQueue')) + `<div class="vx-sub${hold ? ' vx-hold' : ''}">${escapeHtml(sub)}</div>` + rows + foot;
  if (html !== jobs.html) { jobs.html = html; pop.innerHTML = html; }
}

function toggleJobsPop(at) {
  const where = at === 'status' ? 'status' : 'island';
  if (jobs.open && jobs.at === where) { closeJobsPop(); return; }
  closeLoadPop();
  jobs.open = true;
  jobs.at = where;
  jobs.html = '';
  const pop = document.getElementById('jobs-pop');
  pop.classList.remove('hidden');
  document.getElementById('strip-island')?.setAttribute('aria-expanded', String(where === 'island'));
  renderJobsPop();
  placePanel(pop, jobsAnchor(where), where);
  animateIn(pop);
  if (typeof loadQueue === 'function') loadQueue().catch(() => {});
}

function jobsAnchor(where) {
  return document.getElementById(where === 'island' ? 'strip-island' : 'sb-queue');
}

function closeJobsPop() {
  if (!jobs.open) return;
  jobs.open = false;
  document.getElementById('jobs-pop')?.classList.add('hidden');
  document.getElementById('strip-island')?.setAttribute('aria-expanded', 'false');
}

function jobsOpen(id) {
  closeJobsPop();
  openMeeting(id);
}

// A window opens next to what opened it: under the strip's island; above the status bar at its left or right end
function placePanel(pop, anchor, where) {
  if (!pop || !anchor) return;
  const r = anchor.getBoundingClientRect();
  Object.assign(pop.style, { left: '', right: '', top: '', bottom: '' });
  pop.style.maxHeight = `${viewH() - 60}px`;
  if (where === 'island') {  // under the strip's island, its right edge with the island's
    pop.style.top = `${zpx(r.bottom) + 8}px`;
    pop.style.right = `${Math.max(8, viewW() - zpx(r.right))}px`;
  } else {
    pop.style.bottom = '36px';
    if (where === 'status-left') pop.style.left = `${Math.max(8, zpx(r.left))}px`;
    else pop.style.right = `${Math.max(8, viewW() - zpx(r.right))}px`;
  }
}

// --- The load: the indicator of the status bar and its window ---
const load = { open: false, html: '' };
const GB_ = () => t('unitGB');
const gbNum = x => (Math.round(Number(x || 0) * 10) / 10).toLocaleString(state.uiLang === 'en' ? 'en-GB' : 'ru-RU');
const gbText = x => `${gbNum(x)} ${GB_()}`;
const gbPair = (used, total) => `${gbNum(used)} / ${gbNum(total)} ${GB_()}`;  // the unit once: «12,8 / 31,2 ГБ»
const loadLevel = p => (p >= 85 ? ' ld-high' : '');  // amber only above the norm

function loadModels() {
  const chips = (vram.data && vram.data.chips) || [];
  return chips.map((c, i) => ({ c, i })).filter(({ c }) => c.loaded || c.loading);
}

function loadModelName(c) {
  if (c.kind === 'dub') return 'VoxCPM2 · Demucs';
  if (c.kind === 'speakers') return 'ECAPA';
  return c.label || c.name;
}

function loadModelPurpose(c) {
  if (c.kind === 'ollama') return t(c.embedding ? 'ldForSearch' : 'ldForAnalysis');
  if (c.kind === 'live') return t('ldForCaptions');
  if (c.kind === 'dub') return t('ldForDub');
  if (c.kind === 'speakers') return t('ldForSpeakers');
  return t(c.live ? 'ldForCaptionsHere' : 'ldForSpeech');
}

// What a model holds and does: the figures the server knows (Ollama's size, a worker process's memory and
// processor); for the models inside the program, where it runs and its state (Windows does not split the
// memory of one process by models)
function loadModelUse(c, own) {
  const app = own && own.parts && own.parts.app;
  let mem, more;
  if (c.kind === 'ollama') mem = c.size_gb ? t(c.where === 'gpu' ? 'ldVram' : 'ldRam').replace('{gb}', () => gbText(c.size_gb)) : t('ldOllama');
  else if (c.ram_gb != null) mem = t('ldRam').replace('{gb}', () => gbText(c.ram_gb));
  else mem = t(c.where === 'gpu' ? 'ldOnGpu' : 'ldOnCpu');
  if (c.loading) more = t('ldLoading');
  else if (c.kind === 'live' || c.kind === 'dub') more = c.cpu_percent != null ? `CPU ${Math.round(c.cpu_percent)}%` : t('ldOwnProcess');
  else if (c.in_use) more = `${t('ldInUse')}${app && ['whisper', 'onnx', 'speakers'].includes(c.kind) ? ` · CPU ${Math.round(app.cpu_percent)}%` : ''}`;
  else {
    const idle = (vram.data && vram.data.idle) || {};
    more = idle.minutes && idle.unload_in_sec != null ? t('ldUnloadsIn').replace('{min}', () => Math.max(1, Math.ceil(idle.unload_in_sec / 60))) : t('ldIdle');
  }
  return { mem, more };
}

function renderLoadIndicator() {
  const data = vram.data;
  const btn = document.getElementById('sb-load');
  if (!btn || !data) return;
  const sys = data.system || {}, own = data.own || {};
  const models = loadModels();
  const loading = models.find(({ c }) => c.loading);
  const dot = document.getElementById('sb-load-dot');
  dot.className = `sb-dot${loading ? ' sb-dot-busy' : models.length ? ' sb-dot-on' : ''}`;
  const lead = loading ? t('ldLeadLoading').replace('{name}', () => loadModelName(loading.c))
    : models.length ? t('ldLeadLoaded').replace('{n}', () => plural(models.length, t('ldModelForms'))) : t('ldLeadNone');
  document.getElementById('sb-load-lead').textContent = lead;
  const cpu = sys.cpu_percent, ram = sys.ram;
  const set = (id, w) => { const el = document.getElementById(id); if (el) el.style.width = `${Math.max(0, Math.min(100, w || 0))}%`; };
  set('sb-cpu-all', cpu);
  set('sb-cpu-own', own.cpu_percent);
  const cpuEl = document.getElementById('sb-cpu');
  cpuEl.textContent = cpu == null ? '—' : `${Math.round(cpu)}%`;
  cpuEl.className = `sb-num${loadLevel(cpu || 0)}`;
  const rp = ram ? (100 * ram.used_gb) / Math.max(0.1, ram.total_gb) : 0;
  set('sb-ram-all', rp);
  set('sb-ram-own', ram && own.ram_gb != null ? (100 * own.ram_gb) / Math.max(0.1, ram.total_gb) : 0);
  const ramEl = document.getElementById('sb-ram');
  ramEl.textContent = ram ? gbText(ram.used_gb) : '—';
  ramEl.className = `sb-num${loadLevel(rp)}`;
  // the video memory next to them, as before the redesign (asked by the user); only with a card that reports it
  const gpu = data.gpu, gG = document.getElementById('sb-gpu-g');
  if (gG) {
    gG.classList.toggle('hidden', !gpu);
    if (gpu) {
      const vp = (100 * gpu.used_gb) / Math.max(0.1, gpu.total_gb);
      set('sb-gpu-all', vp);
      set('sb-gpu-own', own.gpu_gb != null ? (100 * own.gpu_gb) / Math.max(0.1, gpu.total_gb) : 0);
      const gEl = document.getElementById('sb-gpu');
      gEl.textContent = gbText(gpu.used_gb);
      gEl.className = `sb-num${loadLevel(vp)}`;
    }
  }
  btn.title = `${t('sbLoadTip')}${own.ram_gb != null ? `\nVerbaliox: CPU ${Math.round(own.cpu_percent || 0)}%, RAM ${gbText(own.ram_gb)}` : ''}`;
}

// The marks of the processor, the memory and the video card (asked by the user: the icons of the former sidebar
// back), before CPU, RAM and GPU in the status bar, the load window and the widget of «Обзор»
const HW_IC = {
  CPU: '<svg class="hw-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8.25 3v1.5M4.5 8.25H3m18 0h-1.5M4.5 12H3m18 0h-1.5m-15 3.75H3m18 0h-1.5M8.25 19.5V21M12 3v1.5m0 15V21m3.75-18v1.5m0 15V21m-9-1.5h10.5a2.25 2.25 0 002.25-2.25V6.75a2.25 2.25 0 00-2.25-2.25H6.75A2.25 2.25 0 004.5 6.75v10.5a2.25 2.25 0 002.25 2.25zm.75-12h9v9h-9v-9z"/></svg>',
  RAM: '<svg class="hw-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7.5h18v8.25H3V7.5zM6.75 10.5v2.25m3.75-2.25v2.25m3.75-2.25v2.25m3.75-2.25v2.25M6 15.75v2.25m4-2.25v2.25m4-2.25v2.25m4-2.25v2.25"/></svg>',
  GPU: '<svg class="hw-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.25 6.75h19.5v10.5H2.25V6.75zM4.5 17.25v2.25M9 13.875a1.875 1.875 0 100-3.75 1.875 1.875 0 000 3.75zM14.25 9.75h4.5m-4.5 2.25h4.5m-4.5 2.25h4.5"/></svg>',
};

// The column titles over the values of the load: «Всего занято» and «Verbaliox» (the load window and the widget)
function ldHeadHtml() {
  return `<div class="ld-row ld-head" aria-hidden="true"><span></span><span></span><span class="ld-v">${escapeHtml(t('ldColAll'))}</span>`
    + `<span class="ld-v ld-mine">Verbaliox</span></div>`;
}

// The rows CPU, RAM, GPU: the bar (the whole in grey, Verbaliox's part in the accent), the whole computer and
// Verbaliox's share in their columns; `notes` puts a grey line under the bar (the load window); `noGpu` (the widget)
// keeps the RAM and GPU rows in place when they are not reported, the GPU with a word and its tooltip
function ldRowsHtml(sys, own, gpu, ram, notes, noGpu) {
  const pct = (a, b) => (a != null && b ? (100 * a) / Math.max(0.1, b) : 0);
  const w = x => Math.max(0, Math.min(100, x || 0));
  const row = (k, all, mine, value, ownText, tip) => `<div class="ld-row" title="${escapeHtml(tip)}"><span class="ld-k">${HW_IC[k] || ''}${k}</span>`
    + `<span class="ld-bar ld-bar-lg"><b style="width:${w(all)}%"></b><i style="width:${w(mine)}%"></i></span>`
    + `<span class="ld-v${loadLevel(all || 0)}">${escapeHtml(value)}</span><span class="ld-v ld-mine">${escapeHtml(ownText || '—')}</span></div>`
    + (notes && notes[k] ? `<div class="ld-note">${escapeHtml(notes[k])}</div>` : '');
  const cpu = sys.cpu_percent;
  let html = row('CPU', cpu, own.cpu_percent, cpu == null ? '—' : `${Math.round(cpu)}%`,
    own.cpu_percent != null ? `${Math.round(own.cpu_percent)}%` : '', `Verbaliox: ${Math.round(own.cpu_percent || 0)}%`);
  if (ram) {
    html += row('RAM', pct(ram.used_gb, ram.total_gb), pct(own.ram_gb, ram.total_gb), gbPair(ram.used_gb, ram.total_gb),
      own.ram_gb != null ? gbText(own.ram_gb) : '', own.ram_gb != null ? `Verbaliox: ${gbText(own.ram_gb)}` : '');
  } else if (noGpu) html += row('RAM', 0, 0, '—', '', '');
  if (gpu) {
    const approx = own.gpu_exact ? '' : '≈';
    html += row('GPU', pct(gpu.used_gb, gpu.total_gb), pct(own.gpu_gb, gpu.total_gb), gbPair(gpu.used_gb, gpu.total_gb),
      own.gpu_gb != null ? `${approx}${gbText(own.gpu_gb)}` : '',
      own.gpu_gb != null ? `Verbaliox: ${approx}${gbText(own.gpu_gb)}${own.gpu_exact ? '' : `\n${t('ldGpuApprox')}`}` : '');
  } else if (noGpu) html += row('GPU', 0, 0, noGpu[0], '', noGpu[1]);
  return html;
}

function renderLoadPop() {
  const pop = document.getElementById('load-pop');
  const data = vram.data;
  if (!pop || !load.open || !data) return;
  const sys = data.system || {}, own = data.own || {}, gpu = data.gpu, ram = sys.ram;
  const hw = (state.system && state.system.hardware) || {};
  // one line per resource (asked by the user, «вариант A»): the label, the bar, the whole computer and Verbaliox's own
  // share in the accent (the colour of its part of the bar) under the column titles; the hardware under the bar
  let html = panelHead('load-pop-title', 'chart', t('ldTitle')) + `<div class="vx-sub">${escapeHtml(t('ldSub'))}</div>` + ldHeadHtml();
  html += ldRowsHtml(sys, own, gpu, ram, {
    CPU: [sys.cpu_name, sys.cores ? t('hwThreads').replace('{n}', () => sys.cores) : ''].filter(Boolean).join(' · '),
    RAM: ram ? t('ldRamNote').replace('{gb}', () => Math.round(ram.total_gb)) : '',
    GPU: hw.cuda_available && hw.device_name ? `${hw.device_name}${hw.vram_total_gb ? ` · ${t('ldVramNote').replace('{gb}', () => hw.vram_total_gb)}` : ''}` : '',
  });
  const models = loadModels();
  const vramSum = models.reduce((s, { c }) => s + (c.kind === 'ollama' && c.where === 'gpu' ? Number(c.size_gb || 0) : 0), 0);
  const ramSum = models.reduce((s, { c }) => s + (c.ram_gb != null ? Number(c.ram_gb) : c.kind === 'ollama' && c.where !== 'gpu' ? Number(c.size_gb || 0) : 0), 0);
  const sums = [ramSum ? `RAM ${gbText(ramSum)}` : '', vramSum ? `${t('ldVramShort')} ${gbText(vramSum)}` : ''].filter(Boolean).join(', ');
  html += `<div class="vx-sec">${escapeHtml(t('ldInMemory'))}${sums ? ` · ${escapeHtml(sums)}` : ''}</div>`;
  if (models.length) {
    html += models.map(({ c, i }) => {
      const u = loadModelUse(c, own);
      const can = !vram.busy && !c.loading && c.kind !== 'dub' && (c.can_unload || c.in_use);
      const tip = c.kind === 'dub' ? t('tipVramDub') : vramChipTitle(c);
      return `<div class="vx-prow ld-model"><span class="vx-prow-t"><b>${escapeHtml(loadModelName(c))}</b><small>${escapeHtml(loadModelPurpose(c))}</small></span>`
        + `<span class="ld-use"><b>${escapeHtml(u.mem)}</b><span>${escapeHtml(u.more)}</span></span>`
        + `<button ${pageCall('click', 'vramChipClick', [i])} class="st-btn st-btn-ghost st-btn-sm" title="${escapeHtml(tip)}" ${can ? '' : 'disabled'}>${escapeHtml(t('mpActUnload'))}</button></div>`;
    }).join('');
  } else {
    const idle = (data.idle || {}).minutes;
    html += `<div class="ld-empty">${escapeHtml(idle ? t('ldEmptyIdle').replace('{n}', () => idle) : t('ldEmpty'))}</div>`;
  }
  const anyUnload = models.some(({ c }) => c.kind !== 'dub');
  html += `<div class="vx-foot">${anyUnload ? `<button data-click="unloadAllModelsNow" class="st-btn" ${vram.busy ? 'disabled' : ''} title="${escapeHtml(t('tipUnloadAll'))}">${escapeHtml(t('mpUnloadAll'))}</button>` : ''}`
    + `<button data-click="loadOpenSettings" class="st-btn st-btn-ghost">${escapeHtml(t('ldModelSettings'))}</button></div>`;
  if (html !== load.html) { load.html = html; pop.innerHTML = html; }
}

function toggleLoadPop() {
  if (load.open) { closeLoadPop(); return; }
  closeJobsPop();
  load.open = true;
  load.html = '';
  const pop = document.getElementById('load-pop');
  pop.classList.remove('hidden');
  document.getElementById('sb-load').setAttribute('aria-expanded', 'true');
  renderLoadPop();
  placePanel(pop, document.getElementById('sb-load'), 'status-left');
  animateIn(pop);
  if (typeof scheduleVramRefresh === 'function') scheduleVramRefresh(50);
}

function closeLoadPop() {
  if (!load.open) return;
  load.open = false;
  document.getElementById('load-pop')?.classList.add('hidden');
  document.getElementById('sb-load')?.setAttribute('aria-expanded', 'false');
}

function loadOpenSettings() {
  closeLoadPop();
  openModal('settings', 'recognition');
}

// Each new picture of the memory (settings.js renderVram calls it) redraws the indicator and the open window
function onVramData() {
  renderLoadIndicator();
  renderLoadPop();
}

// Outside click and Escape close the windows; the strip's island follows the queue
document.addEventListener('pointerdown', e => {
  if (jobs.open && !e.target.closest('#jobs-pop, #sb-queue, #strip-island, .macos-menu')) closeJobsPop();
  if (load.open && !e.target.closest('#load-pop, #sb-load')) closeLoadPop();
});
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  if (jobs.open) { const at = jobs.at; closeJobsPop(); jobsAnchor(at)?.focus(); }
  if (load.open) { closeLoadPop(); document.getElementById('sb-load')?.focus(); }
});
window.addEventListener('resize', () => {
  if (jobs.open) placePanel(document.getElementById('jobs-pop'), jobsAnchor(jobs.at), jobs.at);
  if (load.open) placePanel(document.getElementById('load-pop'), document.getElementById('sb-load'), 'status-left');
});
