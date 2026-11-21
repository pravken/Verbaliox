// Verbaliox page script: «Пульт встреч» (docs/pult-plan.md, stages 1–2). The strip of the meeting at the top,
// the «Очередь» window of the rail and of the status bar, the load indicator of the status bar and its window.
// The parts are classic scripts sharing one global scope, loaded in order by index.html.

// --- The strip of the meeting ---
// One state at a time, the most pressing first: recording, a meeting going on without a recording, a meeting
// within 15 minutes, the recording just made (waiting for its transcription, then its summary ready), a free
// day or a day off. Order everywhere: the pill, the meeting, its details, the buttons of the state.
const STRIP_SOON_MS = 15 * 60e3;
const STRIP_RECENT_MS = 3 * 3600e3;  // the recording just made stays on the strip this long
const strip = { events: [], holidays: {}, configured: false, at: 0, loading: null, call: null, callAt: 0, callOff: false,
  skip: new Set(), html: '', click: null };
let stripSeen = new Set();  // recordings whose «Итоги готовы» were opened or hidden
try { stripSeen = new Set(JSON.parse(localStorage.getItem('verbaliox_strip_seen') || '[]')); } catch (e) { /* storage off */ }

function stripRemember() {
  try { localStorage.setItem('verbaliox_strip_seen', JSON.stringify([...stripSeen].slice(-50))); } catch (e) { /* storage off */ }
}

function stripClock(d) { return `${hmPad(d.getHours())}:${hmPad(d.getMinutes())}`; }
function stripDayStart(d) { const x = new Date(d); x.setHours(0, 0, 0, 0); return x; }

// The meetings of today and of the week ahead (the next one after a free day), and the public holidays
async function stripLoad(force) {
  if (!force && Date.now() - strip.at < 300000) return;
  if (strip.loading) return strip.loading;
  strip.loading = (async () => {
    const a = stripDayStart(new Date()), b = new Date(a.getTime() + 8 * 86400e3);
    const data = await fetch(`/api/calendar/range?start=${encodeURIComponent(hmIso(a))}&end=${encodeURIComponent(hmIso(b))}&lang=${state.uiLang === 'en' ? 'en' : 'ru'}`)
      .then(r => (r.ok ? r.json() : null)).catch(() => null);
    if (!data) return;
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
      acts: [act('studioMark', [], `★ ${t('stripMark')}`, '', t('stripMarkTip'))] };
  }
  const liveMeeting = live && !strip.skip.has(live.key) ? live : null;
  if (liveMeeting || (strip.call && !strip.skip.has(`call:${strip.call}`))) {
    const e = liveMeeting;
    const min = e ? Math.max(1, Math.round((now - e.s.getTime()) / 60e3)) : 0;
    const st = e ? hmMeetingState(e) : '';
    // its recording was made and stopped before the meeting's end: said so, not «Автозапись не началась»
    const stopped = !!e && (home.started.has(e.key) || !!e.recording);
    const why = stopped ? 'stripWhyStopped'
      : { off: 'stripWhyOff', never: 'stripWhyNever', skipped: 'stripWhySkipped', on: 'stripWhyLate', ask: 'stripWhyLate' }[st] || 'stripWhyCall';
    return { kind: 'unrec', pill: t(stopped ? 'stripRecStopped' : 'stripUnrec'), cls: 'amber', lead: e ? e.title || t('hmUntitled') : strip.call,
      meta: e ? [stripService(e) || strip.call, t('stripMinGoing').replace('{n}', () => min)].filter(Boolean).join(' · ') : t('stripCall'),
      grow: t(why),
      acts: [joinAct(e), act(e ? 'hmRecordNow' : 'shellQuickRecord', e ? [e.key] : [], `● ${t(stopped ? 'stripRecordAgain' : 'stripRecordRest')}`, 'warn', t('stripRecordRestTip')),
        act('stripSkip', [e ? e.key : `call:${strip.call}`], t('stripDontRecord'), 'ghost')].filter(Boolean) };
  }
  if (next && next.s.getTime() - now <= STRIP_SOON_MS) {
    const min = Math.max(1, Math.ceil((next.s.getTime() - now) / 60e3));
    const known = home.events.find(x => x.key === next.key);
    const bf = known && known.before;
    const people = (next.attendees || []).map(a => String(a).replace(/@.*$/, '')).filter(Boolean).slice(0, 4).join(', ');
    return { kind: 'soon', pill: t('stripSoon').replace('{n}', () => min), cls: 'blue', lead: next.title || t('hmUntitled'),
      meta: [`${stripClock(next.s)}–${stripClock(next.e)}`, stripService(next)].filter(Boolean).join(' · '),
      grow: [bf && bf.open_tasks ? t('stripOpenTasks').replace('{n}', () => bf.open_tasks) : '', people].filter(Boolean).join(' · '),
      acts: [joinAct(next)].filter(Boolean) };
  }
  const m = stripRecent();
  if (m && !DONE_STATUSES.includes(m.status)) {
    const q = (state.queue || []).find(x => x.id === m.id);
    const running = q && q.state === 'running';
    const mins = Math.max(1, Math.round((m.duration || 0) / 60));
    const grow = running ? serverText(m.stage_text || q.stage_text || '')
      : state.queueMeeting ? t('stripWaitMeeting') : state.queuePaused ? t('stripWaitPaused')
      : typeof economyOn === 'function' && economyOn() ? t('stripWaitEconomy') : q ? t('queueWaiting').replace('{n}', () => q.position) : '';
    return { kind: 'after', pill: running ? t('stripProcessing').replace('{pct}', () => m.progress || 0) : t('stripWaiting'), cls: running ? 'blue' : 'grey',
      lead: m.title || t('hmUntitled'), meta: m.duration ? t('stripRecorded').replace('{n}', () => mins) : '', grow, click: m.id, tip: t('tbRecOpen'),
      acts: [act('openMeeting', [m.id], t('tbRecOpen'), 'ghost')] };
  }
  if (m && m.status === 'completed' && !stripSeen.has(m.id)) {
    const mins = Math.max(1, Math.round((m.duration || 0) / 60));
    return { kind: 'ready', pill: t(m.has_summary ? 'stripReady' : 'stripTextReady'), cls: 'green', lead: m.title || t('hmUntitled'),
      meta: m.duration ? t('stripRecorded').replace('{n}', () => mins) : '', grow: '', click: m.id, tip: t('stripOpenSummary'),
      acts: [act('stripOpenSummary', [m.id], t(m.has_summary ? 'stripOpenSummary' : 'tbRecOpen'), 'go'), act('stripHide', [m.id], t('stripHide'), 'ghost')] };
  }
  const nextText = next ? t('stripNext').replace('{when}', () => stripWhenNext(next)).replace('{title}', () => next.title || t('hmUntitled')) : '';
  if (!strip.configured) {
    return { kind: 'free', pill: t('stripNoCalendar'), cls: 'grey', lead: '', meta: t('stripNoCalendarSub'), grow: '',
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
  const acts = s.acts.map(a => `<button ${pageCall('click', a.fn, a.args)} class="st-btn${a.cls ? ` st-btn-${a.cls}` : ''}"${a.title ? ` title="${escapeHtml(a.title)}"` : ''}>${escapeHtml(a.label)}</button>`).join('');
  const sig = JSON.stringify([s.kind, s.pill, s.cls, s.lead, s.meta, s.grow, acts, s.tip]);
  if (sig === strip.html) return;
  strip.html = sig;
  bar.className = `strip strip-${s.kind}`;
  const pill = document.getElementById('strip-pill');
  pill.className = `st-pill ${s.cls.split(' ').map(c => `stp-${c}`).join(' ')}`;
  document.getElementById('strip-pill-t').textContent = s.pill;
  const put = (id, v) => { const el = document.getElementById(id); el.textContent = v || ''; el.classList.toggle('hidden', !v); };
  put('strip-lead', s.lead);
  put('strip-meta', s.meta);
  document.getElementById('strip-grow').textContent = s.grow || '';
  document.getElementById('strip-grow').className = `strip-grow${s.growCls ? ` strip-grow-${s.growCls}` : ''}`;
  const main = document.getElementById('strip-main');
  main.classList.toggle('strip-link', !!s.click);
  main.title = s.click ? s.tip || '' : '';
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

// «Не записывать»: the strip leaves this meeting (or this call) alone until it is over
function stripSkip(key) {
  strip.skip.add(key);
  renderStrip();
}

function stripOpenCalendarSettings() {
  openModal('settings', 'general');
  selectSettingsTab('calendar');
}

// --- «Очередь»: the window of the rail button and of the status bar ---
const jobs = { open: false, at: 'rail', html: '' };

const JOBS_ICON = {
  run: '<circle cx="12" cy="12" r="8" opacity=".3"/><path class="ri-arc" d="M12 4a8 8 0 018 8"/>',
  wait: '<circle cx="12" cy="12" r="8"/><path class="ri-pz1" d="M10 9v6"/><path class="ri-pz2" d="M14 9v6"/>',
  ok: '<circle class="ri-ring" cx="12" cy="12" r="8"/><path class="ri-ok" pathLength="1" d="M8.5 12.5l2.3 2.2 4.7-5"/>',
};
const PANEL_ICON = {
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  chart: '<path d="M4 19h16"/><path d="M7 16v-5M12 16V7M17 16v-8"/>',
};
const panelHead = (id, icon, title) => `<div class="vx-panel-h"><span class="vx-panel-ic" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${PANEL_ICON[icon]}</svg></span><h4 id="${id}">${escapeHtml(title)}</h4></div>`;

// Why the queue waits, or nothing
function jobsHold() {
  if (typeof economyOn === 'function' && economyOn()) return t('jobsHoldEconomy');
  if (state.queuePaused) return t('jobsHoldPaused');
  if (state.queueMeeting) return t('jobsHoldMeeting');
  return '';
}

// The rail button: a turning arc while a job runs, a pause while all wait, a check when nothing is left; the count
function renderJobsRail() {
  const btn = document.getElementById('rail-jobs');
  if (!btn) return;
  const items = state.queue || [];
  const run = items.some(q => q.state === 'running'), wait = !run && items.length > 0;
  const mode = run ? 'run' : wait ? 'wait' : 'ok';
  if (btn.dataset.mode !== mode) {
    btn.dataset.mode = mode;
    btn.classList.toggle('rail-jobs-run', run);
    btn.classList.toggle('rail-jobs-wait', wait);
    document.getElementById('rail-jobs-ic').innerHTML = JOBS_ICON[mode];
  }
  const n = document.getElementById('rail-jobs-n');
  n.textContent = items.length ? String(items.length) : '';
  n.classList.toggle('hidden', !items.length);
  n.classList.toggle('rail-badge-wait', wait);
  btn.title = items.length ? `${t('rlTipQueue')} · ${run ? t('jobsRunning') : jobsHold() || t('jobsWaitingShort')}` : t('rlTipQueue');
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
      : state.queueMeeting && q.kind === 'transcribe' ? t('jobsWaitMeeting') : t('queueWaiting').replace('{n}', () => q.position);
    const tip = t('jobsOpenTip').replace('{title}', () => q.title || '');
    return `<div class="vx-prow vx-link" ${pageCall('click', 'jobsOpen', [q.id])} role="button" tabindex="0" title="${escapeHtml(tip)}">`
      + `<span class="vx-prow-t"><b>${escapeHtml(queueKindLabel(q))}</b><small>${escapeHtml(q.title || '')}</small></span>`
      + `<span class="vx-val ${running ? 'vx-run' : 'vx-wait'}">${escapeHtml(val)}</span>`
      + `<button ${pageCall('click', 'stopThen', [{ $: 'event' }, 'cancelProcessing', Number(q.id) || 0])} class="vx-x${q.cancelling ? ' invisible' : ''}" title="${escapeHtml(t('tipQueueCancel'))}" aria-label="${escapeHtml(t('tipQueueCancel'))}">✕</button>`
      + (running ? `<span class="vx-pbar"><b style="width:${Math.max(3, pct)}%"></b></span>` : '')
      + '</div>';
  }).join('');
  const foot = items.length
    ? `<div class="vx-foot"><button data-click="toggleQueuePause" class="st-btn">${escapeHtml(t(state.queuePaused ? 'queueResume' : 'queuePause'))}</button>`
      + `<button data-click="cancelWholeQueue" class="st-btn st-btn-ghost">${escapeHtml(t('queueCancelAllOk'))}</button></div>` : '';
  const html = panelHead('jobs-pop-title', 'clock', t('rlQueue')) + `<div class="vx-sub${hold ? ' vx-hold' : ''}">${escapeHtml(sub)}</div>` + rows + foot;
  if (html !== jobs.html) { jobs.html = html; pop.innerHTML = html; }
}

function toggleJobsPop(at) {
  const where = at === 'status' ? 'status' : 'rail';
  if (jobs.open && jobs.at === where) { closeJobsPop(); return; }
  closeLoadPop();
  jobs.open = true;
  jobs.at = where;
  jobs.html = '';
  const pop = document.getElementById('jobs-pop');
  pop.classList.remove('hidden');
  document.getElementById('rail-jobs')?.setAttribute('aria-expanded', String(where === 'rail'));
  renderJobsPop();
  placePanel(pop, where === 'rail' ? document.getElementById('rail-jobs') : document.getElementById('sb-queue'), where);
  animateIn(pop);
  if (typeof loadQueue === 'function') loadQueue().catch(() => {});
}

function closeJobsPop() {
  if (!jobs.open) return;
  jobs.open = false;
  document.getElementById('jobs-pop')?.classList.add('hidden');
  document.getElementById('rail-jobs')?.setAttribute('aria-expanded', 'false');
}

function jobsOpen(id) {
  closeJobsPop();
  openMeeting(id);
}

// A window opens next to what opened it: right of the rail, its bottom level with the button; above the status
// bar at its left or right end
function placePanel(pop, anchor, where) {
  if (!pop || !anchor) return;
  const r = anchor.getBoundingClientRect();
  Object.assign(pop.style, { left: '', right: '', top: '', bottom: '' });
  pop.style.maxHeight = `${viewH() - 60}px`;
  if (where === 'rail') {
    pop.style.left = `${zpx(r.right) + 8}px`;
    pop.style.top = `${Math.max(8, Math.min(zpx(r.bottom) - pop.offsetHeight, viewH() - pop.offsetHeight - 38))}px`;
  } else {
    pop.style.bottom = '36px';
    if (where === 'status-left') pop.style.left = `${Math.max(8, zpx(r.left))}px`;
    else pop.style.right = `${Math.max(8, viewW() - zpx(r.right))}px`;
  }
}

// --- The load: the indicator of the status bar and its window ---
const load = { open: false, html: '' };
const GB_ = () => t('unitGB');
const gbText = x => `${(Math.round(Number(x || 0) * 10) / 10).toLocaleString(state.uiLang === 'en' ? 'en-GB' : 'ru-RU')} ${GB_()}`;
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

function renderLoadPop() {
  const pop = document.getElementById('load-pop');
  const data = vram.data;
  if (!pop || !load.open || !data) return;
  const sys = data.system || {}, own = data.own || {}, gpu = data.gpu, ram = sys.ram;
  const hw = (state.system && state.system.hardware) || {};
  const bar = (all, mine) => `<span class="ld-bar ld-bar-lg"><b style="width:${Math.max(0, Math.min(100, all || 0))}%"></b><i style="width:${Math.max(0, Math.min(100, mine || 0))}%"></i></span>`;
  // each resource: its bar and value, under them the hardware on the left and Verbaliox's own share on the right
  // (asked by the user: the shares of the program in one line under the GPU read as a part of the GPU)
  const row = (k, all, mine, value, tip, note, own) => `<div class="ld-row" title="${escapeHtml(tip)}"><span class="ld-k">${k}</span>${bar(all, mine)}<span class="ld-v${loadLevel(all || 0)}">${escapeHtml(value)}</span></div>`
    + (note || own ? `<div class="ld-sub"><span class="ld-note">${escapeHtml(note || '')}</span>${own ? `<span class="ld-own"><i class="ld-me"></i>${escapeHtml(own)}</span>` : ''}</div>` : '');
  const cpu = sys.cpu_percent;
  let html = panelHead('load-pop-title', 'chart', t('ldTitle')) + `<div class="vx-sub">${escapeHtml(t('ldSub'))}</div>`
    + `<div class="ld-legend"><span><i class="ld-me"></i>Verbaliox</span><span><i></i>${escapeHtml(t('ldOthers'))}</span></div>`;
  html += row('CPU', cpu, own.cpu_percent, cpu == null ? '—' : `${Math.round(cpu)}%`,
    `Verbaliox: ${Math.round(own.cpu_percent || 0)}%`, [sys.cpu_name, sys.cores ? t('hwThreads').replace('{n}', () => sys.cores) : ''].filter(Boolean).join(' · '),
    own.cpu_percent != null ? `${Math.round(own.cpu_percent || 0)}%` : '');
  if (ram) {
    const rp = (100 * ram.used_gb) / Math.max(0.1, ram.total_gb);
    html += row('RAM', rp, own.ram_gb != null ? (100 * own.ram_gb) / Math.max(0.1, ram.total_gb) : 0, `${gbText(ram.used_gb)} / ${gbText(ram.total_gb)}`,
      own.ram_gb != null ? `Verbaliox: ${gbText(own.ram_gb)}` : '', t('ldRamNote').replace('{gb}', () => Math.round(ram.total_gb)),
      own.ram_gb != null ? gbText(own.ram_gb) : '');
  }
  if (gpu) {
    const vp = (100 * gpu.used_gb) / Math.max(0.1, gpu.total_gb);
    const mine = own.gpu_gb != null ? (100 * own.gpu_gb) / Math.max(0.1, gpu.total_gb) : 0;
    html += row('GPU', vp, mine, `${gbText(gpu.used_gb)} / ${gbText(gpu.total_gb)}`,
      own.gpu_gb != null ? `Verbaliox: ${own.gpu_exact ? '' : '≈'}${gbText(own.gpu_gb)}${own.gpu_exact ? '' : `\n${t('ldGpuApprox')}`}` : '',
      hw.cuda_available && hw.device_name ? `${hw.device_name}${hw.vram_total_gb ? ` · ${t('ldVramNote').replace('{gb}', () => hw.vram_total_gb)}` : ''}` : '',
      own.gpu_gb != null ? `${own.gpu_exact ? '' : '≈'}${gbText(own.gpu_gb)}` : '');
  }
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

// Outside click and Escape close the windows; the status bar and the rail follow the queue
document.addEventListener('pointerdown', e => {
  if (jobs.open && !e.target.closest('#jobs-pop, #rail-jobs, #sb-queue, .macos-menu')) closeJobsPop();
  if (load.open && !e.target.closest('#load-pop, #sb-load')) closeLoadPop();
});
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  if (jobs.open) { const at = jobs.at; closeJobsPop(); document.getElementById(at === 'rail' ? 'rail-jobs' : 'sb-queue')?.focus(); }
  if (load.open) { closeLoadPop(); document.getElementById('sb-load')?.focus(); }
});
window.addEventListener('resize', () => {
  if (jobs.open) placePanel(document.getElementById('jobs-pop'), document.getElementById(jobs.at === 'rail' ? 'rail-jobs' : 'sb-queue'), jobs.at);
  if (load.open) placePanel(document.getElementById('load-pop'), document.getElementById('sb-load'), 'status-left');
});
