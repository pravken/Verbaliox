// Verbaliox page script: the shell. The top bar (record at once, the parts of the app, the open
// recording), the views of the main area, the status bar. docs/redesign-plan.md tells how a view plugs in.
// The parts are classic scripts sharing one global scope, loaded in order by index.html.

// --- Views of the main area ---
// "library" is the open recording (its transcript, analysis and speakers); its name stays for the
// many places that open a recording. Ctrl+1…5 follow the top bar (video.js).
const APP_VIEWS = ['home', 'library', 'tasks', 'studio', 'ask', 'settings', 'libtable', 'dashboard', 'dict', 'people'];
const VIEW_HOOKS = {};

// A view of a package: show() runs each time it comes on screen, hide() when another one does,
// refresh() when the list of recordings changed while it is on screen
function registerView(name, hooks) {
  VIEW_HOOKS[name] = hooks || {};
}

// What the views refresh for: a recording added, removed, renamed, finished or analysed — not the
// progress of one being processed, which the list is polled for every 2 s
function librarySignature() {
  return (state.meetings || []).map(m => `${m.id}:${m.status}:${m.title || ''}:${m.completed_at || ''}:${m.has_summary ? 1 : 0}`).join('|');
}

// The list of recordings was loaded again (loadMeetingsList): the bar and the view on screen follow;
// refresh(changed) says whether anything but the progress changed
function onLibraryChanged() {
  renderTopbar();
  refreshTasksCount();
  const sig = librarySignature(), changed = sig !== state.librarySig;
  state.librarySig = sig;
  VIEW_HOOKS[state.appView]?.refresh?.(changed);
}

function switchAppView(view) {
  if (!APP_VIEWS.includes(view)) view = 'library';
  const prev = state.appView;
  if (state.theatre && view !== 'library') exitTheatre();
  if (prev && prev !== view) {
    if (prev !== 'settings') state.prevView = prev;  // where the settings page goes back to
    if (prev === 'settings') leaveSettingsPage();
    VIEW_HOOKS[prev]?.hide?.();
  }
  state.appView = view;
  // the library marks what the main area shows (library.js libSelectionShown, the running recording)
  if (prev !== view && typeof renderMeetingsSidebar === 'function' && state.meetings) renderMeetingsSidebar();
  // audit 8.8: the open settings page is marked on its button, like the current tab
  document.getElementById('sb-settings-btn')?.classList.toggle('sb-on', view === 'settings');
  // The sidebar always shows the library; the main area shows the chosen part
  for (const v of APP_VIEWS) document.getElementById(`${v}-view`)?.classList.toggle('hidden', v !== view);
  if (prev && prev !== view) animateIn(document.getElementById(`${view}-view`));  // it fades in
  if (view === 'ask') loadPeople();
  hideContextMenu();
  hideFolderMenu();
  if (view === 'studio') {
    prepareStudio();
    syncStudioCaptions();
  } else if (studio.focus) {
    toggleStudioFocus(false);
  }
  if (view === 'ask') {
    renderAskScope();
    renderAskThread();
    nextFrame(() => document.getElementById('library-question').focus());
  }
  // Reached without openModal (another script switching to it): the page needs its content
  if (view === 'settings' && document.getElementById('modal-settings')?.classList.contains('hidden')) openModal('settings');
  VIEW_HOOKS[view]?.show?.();
  updateRecordButtonState();
  renderTopbar();
  navRecord();
}

// --- «Назад» / «Вперёд» of the mouse (and Alt+← / Alt+→) inside the app (reported by the user: the window
// went back to its loading page). The places visited: the page, the recording open and its tab ---
const NAV = { back: [], fwd: [], last: null, moving: false, at: 0 };

function navPlace() {
  return { view: state.appView || 'dashboard', meeting: state.activeMeeting ? state.activeMeeting.id : 0,
    tab: state.activeWorkspaceTab || 'transcript' };
}

function navSame(a, b) {
  if (!a || !b || a.view !== b.view) return false;
  return a.view !== 'library' || (a.meeting === b.meeting && a.tab === b.tab);
}

function navRecord() {
  if (NAV.moving) return;
  const p = navPlace();
  p.t = Date.now();
  if (navSame(NAV.last, p)) { NAV.last = p; return; }
  // a step on the way (the library shown, then the recording opened in it a moment later): one place
  if (NAV.last && NAV.last.view === p.view && p.t - NAV.last.t < 600) { NAV.last = p; return; }
  if (NAV.last) {
    NAV.back.push(NAV.last);
    if (NAV.back.length > 50) NAV.back.shift();
    NAV.fwd = [];
  }
  NAV.last = p;
}

async function navGo(dir) {
  const from = dir < 0 ? NAV.back : NAV.fwd, to = dir < 0 ? NAV.fwd : NAV.back;
  // an open menu or window goes first («Назад» closes it), the page after
  if (dir < 0 && document.getElementById('tk-pop')) { tkClosePop(); return; }
  const modal = document.querySelector('[id^="modal-"]:not(#modal-settings):not(.hidden)');
  if (dir < 0 && modal) { closeModal(modal.id.slice(6)); return; }
  const p = from.pop();
  if (!p) return;
  if (NAV.last) to.push(NAV.last);
  NAV.moving = true;
  try {
    if (p.view === 'library' && p.meeting && (!state.activeMeeting || state.activeMeeting.id !== p.meeting)
        && (state.meetings || []).some(m => m.id === p.meeting)) {
      await selectMeeting(p.meeting, true);
    }
    switchAppView(p.view);
    if (p.view === 'library' && p.tab && state.activeWorkspaceTab !== p.tab) switchWorkspaceTab(p.tab);
  } finally {
    NAV.moving = false;
    NAV.last = Object.assign(navPlace(), { t: 0 });
  }
}

// The mouse's side buttons: 3 back, 4 forward. Their default (the WebView's history) is stopped.
for (const type of ['mousedown', 'mouseup', 'auxclick']) {
  document.addEventListener(type, e => {
    if (e.button !== 3 && e.button !== 4) return;
    e.preventDefault();
    if (type === 'mouseup') { NAV.at = Date.now(); navGo(e.button === 3 ? -1 : 1); }
  });
}
document.addEventListener('keydown', e => {
  if (!e.altKey || (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight')) return;
  e.preventDefault();
  NAV.at = Date.now();
  navGo(e.key === 'ArrowLeft' ? -1 : 1);
});
// Should the WebView go back in its history all the same, it stays on this page: an entry of its own is
// kept on top, and a «back» to it is taken as the app's «Назад»
history.pushState({ vx: 1 }, '', location.href);
window.addEventListener('popstate', () => {
  history.pushState({ vx: 1 }, '', location.href);
  if (Date.now() - NAV.at > 400) navGo(-1);  // not when the mouse handler did it already
});

// The tabs of the open recording, in the top bar: transcript | summary (analysis) | speakers | info
function openRecordTab(tab) {
  if (!state.activeMeeting) { switchAppView('home'); return; }
  switchAppView('library');
  switchWorkspaceTab(tab);
}

// --- The top bar ---
function renderTopbar() {
  const view = state.appView || 'home';
  const tab = state.activeWorkspaceTab || 'transcript';
  const set = (id, on) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.toggle('tb-active', on);
    if (on) el.setAttribute('aria-current', 'page'); else el.removeAttribute('aria-current');
  };
  set('nav-tasks', view === 'dashboard' || view === 'tasks');  // the tasks' page opens from the dashboard
  set('nav-studio', view === 'studio');
  updateRecordButtonState();  // the recording's tab: shown while it records or its settings are open
  set('nav-ask', view === 'ask');
  const m = state.activeMeeting;
  // Audit 8.5: the tabs of a recording appear once you have opened one, not for the one picked at start
  if (view === 'library') state.recordSeen = true;
  document.getElementById('tb-record')?.classList.toggle('hidden', !m || !state.recordSeen);
  set('nav-transcript', view === 'library' && tab === 'transcript');
  set('nav-summary', view === 'library' && tab === 'summary');
  set('nav-speakers', view === 'library' && tab === 'speakers');
  set('nav-info', view === 'library' && tab === 'info');
  syncAnalysisMark();
  if (m) {
    // the sections made (summaries["error"] is the last failure, not a section)
    const ready = Object.entries(m.summaries || {}).filter(([k, v]) => k !== 'error' && typeof v === 'string' && v.trim()).length;
    badge('nav-summary-n', ready);
    badge('nav-speakers-n', Object.keys(m.speakers || {}).length);
  }
  scheduleFitTopbar();
  placeTabIndicators();
  renderRail();
  if (typeof renderStrip === 'function') renderStrip();  // the strip of the meeting (pult.js)
}

// --- The rail of the sections (parts/rail.html) ---
// The section on screen is marked, and the bar at the edge moves to it from the one left; an open recording
// belongs to «Записи», the settings page to «Настройки»
const RAIL_OF_VIEW = { home: 'rail-home', dashboard: 'rail-dashboard', libtable: 'rail-libtable', library: 'rail-libtable',
  tasks: 'rail-tasks', ask: 'rail-ask', settings: 'sb-settings-btn', dict: 'rail-dict', people: 'rail-people' };
let _railOn = '';
function renderRail() {
  const rail = document.getElementById('app-rail');
  if (!rail) return;
  const id = RAIL_OF_VIEW[state.appView] || '';
  if (id === _railOn) return;
  const was = _railOn;
  _railOn = id;
  for (const b of rail.querySelectorAll('.rail-btn')) {
    const on = b.id === id;
    b.classList.toggle('rail-on', on);
    if (on) b.setAttribute('aria-current', 'page'); else b.removeAttribute('aria-current');
  }
  const on = id && document.getElementById(id);
  if (!placeRailIndicator(!was)) return;
  if (was && was !== id) {  // the icon of the section chosen gives a small press
    on.classList.remove('rail-pick'); void on.offsetWidth; on.classList.add('rail-pick');
  }
}

// The bar at the rail's edge on the section's button; still: placed at once, not moved (the first one, a resize: the
// buttons change height at 1180 px, and the bar stayed where the button had been)
function placeRailIndicator(still) {
  const rail = document.getElementById('app-rail');
  const ind = rail && rail.querySelector('.rail-ind'), on = _railOn && document.getElementById(_railOn);
  if (!ind) return false;
  if (!on) { ind.style.opacity = '0'; return false; }
  ind.classList.toggle('rail-ind-still', !!still);
  Object.assign(ind.style, { top: `${on.offsetTop + 8}px`, height: `${on.offsetHeight - 16}px`, opacity: '1' });
  return true;
}
window.addEventListener('resize', () => placeRailIndicator(true));

// The highlight of the chosen tab in a group moves to it (chosen with the user): one element under the
// tabs, placed on the chosen one; none chosen in the group (a recording open, under the app's views), it fades
function placeTabIndicators() {
  requestAnimationFrame(() => {
    for (const g of document.querySelectorAll('#tb-main, #tb-record')) {
      let ind = g.querySelector(':scope > .tb-ind');
      if (!ind) { ind = document.createElement('i'); ind.className = 'tb-ind'; ind.setAttribute('aria-hidden', 'true'); g.prepend(ind); g.classList.add('has-ind'); }
      const on = g.querySelector(':scope > .tb-active');
      if (!on || !on.offsetWidth) { ind.style.opacity = '0'; continue; }
      const first = ind.style.opacity !== '1';  // appearing: in place at once, no ride from where it was
      if (first) ind.classList.add('tb-ind-still');
      Object.assign(ind.style, { left: `${on.offsetLeft}px`, top: `${on.offsetTop}px`, width: `${on.offsetWidth}px`, height: `${on.offsetHeight}px`, opacity: '1' });
      if (first) requestAnimationFrame(() => ind.classList.remove('tb-ind-still'));
    }
  });
}
window.addEventListener('resize', placeTabIndicators);

// While the analysis of the open recording runs (a section asked for here, or the analysis after the
// transcription), the mark of «Анализ» in the bar turns and a dot pulses beside it (asked by the user)
function analysisRunning(m) {
  if (!m) return false;
  if (m.status === 'summarizing') return true;
  const own = `${m.id}:`;
  return !!state.anBusy && [...state.anBusy].some(k => k.startsWith(own));
}
function syncAnalysisMark() {
  const el = document.getElementById('nav-summary');
  if (!el) return;
  const on = analysisRunning(state.activeMeeting);
  if (el.classList.contains('tb-analysing') === on) return;
  el.classList.toggle('tb-analysing', on);
  el.title = on ? t('tipAnalysisRunning') : t('tipTabSummary');
}

// The bar fits the window at any width and interface scale: the steps of styles.css (tb-c1…tb-c6) are
// tried in turn until nothing sticks out
const TOPBAR_STEPS = ['tb-c1', 'tb-c2', 'tb-c3', 'tb-c4', 'tb-c5', 'tb-c6'];
let _topbarFitFor = '';
function fitTopbar() {
  const bar = document.getElementById('app-bar');
  if (!bar || !bar.offsetParent) return;
  // the same text in the same width: already fitted (renderTopbar runs every 1.5 s, and each fit makes
  // the browser lay the page out several times)
  const sig = `${window.innerWidth}|${devicePixelRatio}|${document.documentElement.style.zoom}|${bar.textContent}|${bar.querySelectorAll('.hidden').length}`;
  if (sig === _topbarFitFor) return;
  _topbarFitFor = sig;
  bar.classList.remove(...TOPBAR_STEPS);
  for (const step of TOPBAR_STEPS) {
    if (bar.scrollWidth <= bar.clientWidth + 1) break;
    bar.classList.add(step);
  }
}
let _fitTopbarFrame = 0;
function scheduleFitTopbar() {
  cancelAnimationFrame(_fitTopbarFrame);
  _fitTopbarFrame = requestAnimationFrame(fitTopbar);
}
window.addEventListener('resize', scheduleFitTopbar);

function badge(id, n) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = n ? String(n) : '';
  el.classList.toggle('hidden', !n);
  if (el.closest('#app-bar')) scheduleFitTopbar();
}

// The open tasks of the whole library, on the "Tasks" tab (refreshed with the list, at most every 10 s)
let _tasksCountAt = 0;
async function refreshTasksCount(force) {
  if (!force && Date.now() - _tasksCountAt < 10000) return;
  _tasksCountAt = Date.now();
  const items = await fetch('/api/commitments').then(r => (r.ok ? r.json() : null)).catch(() => null);
  if (!Array.isArray(items)) return;
  // the user's own open tasks (the dashboard tracks only those); everyone's while «Это я» is not set
  const me = String(((state.system || {}).settings || {}).my_name || '').split(',').map(n => n.trim().toLocaleLowerCase()).filter(Boolean);
  const mine = me.length ? items.filter(x => me.includes(String(x.who || '').trim().toLocaleLowerCase())) : items;
  badge('nav-tasks-n', mine.length);
  // what needs the user today stands out (asked by the user: the count was barely seen): overdue or due
  // today, the badge turns orange and says how many
  const today = new Date().toLocaleDateString('sv');
  const hot = mine.filter(x => x.status !== 'done' && x.due_date && String(x.due_date) <= today).length;
  const el = document.getElementById('nav-tasks-n');
  if (el) {
    el.classList.toggle('tb-badge-hot', hot > 0);
    el.title = hot ? t('tbTasksHot').replace('{n}', () => hot) : t('tbTasksOpen').replace('{n}', () => mine.length);
  }
}

// The open recording changes in many places; the bar follows it without each of them calling it
setInterval(() => { if (!document.hidden) renderTopbar(); }, 1500);

// The ⋯ of the open recording: its details, rename, move, show the file, delete
// Audit 7.1. The ⋯ of the top bar opens the same full menu of the recording as the ⋯ at its title
function openRecordBarMenu(e) {
  e.stopPropagation();
  const m = state.activeMeeting;
  if (!m) return;
  const r = e.currentTarget.getBoundingClientRect();
  openRecordingContextMenu({ clientX: r.right, clientY: r.bottom + 4, preventDefault() {}, stopPropagation() {} }, m.id);
}

function openMoveRecordMenu(m, r) {
  const folders = [...(state.folders || [])].sort((a, b) => folderName(a).localeCompare(folderName(b), state.uiLang));
  openTextMenuAt(folders.map(f => ({
    label: folderName(f), on: (m.folder_id ?? null) === f.id,
    run: () => moveMeetingToFolder(m.id, f.id),
  })), r.right, r.bottom + 4, { right: true });
}

// --- Record at once: the red button of the top bar, with the last studio settings, in any view ---
let _quickRecResult = null;
let _quickRecHideTimer = null;

let _quickRecBusy = false;  // starting or saving: a second press waits for it

async function shellQuickRecord() {
  if (_quickRecBusy) return;
  _quickRecBusy = true;
  hideQuickRecDone();
  updateRecordButtonState();  // «Запуск…» at once: the microphone can take seconds to answer
  try {
    if (isRecording()) {
      const clock = document.getElementById('studio-timer').textContent;
      const first = await stopAndTranscribeRecording({ quiet: true });
      if (first !== undefined) showQuickRecDone(first, clock);
      return;
    }
    state.quickRecStay = true;  // startLiveRecording leaves the view as it is
    // In the open Studio it records what the Studio shows; from another view, with the chosen preset
    if (state.appView === 'studio') await prepareStudio();
    else await prepareStudio(state.recPresetId || defaultRecordPresetId());
    await startLiveRecording();
  } finally {
    state.quickRecStay = false;
    _quickRecBusy = false;
    updateRecordButtonState();
  }
}

function showQuickRecDone(first, clock) {
  _quickRecResult = first || null;
  document.getElementById('tb-rec-saved-time').textContent = clock || '';
  document.getElementById('tb-rec-open').classList.toggle('hidden', !first);
  document.getElementById('tb-rec-done').classList.remove('hidden');
  clearTimeout(_quickRecHideTimer);
  _quickRecHideTimer = setTimeout(hideQuickRecDone, 9000);
}

function hideQuickRecDone() {
  clearTimeout(_quickRecHideTimer);
  document.getElementById('tb-rec-done')?.classList.add('hidden');
}

function openQuickRecResult() {
  hideQuickRecDone();
  if (_quickRecResult) openMeeting(_quickRecResult.id);
}

// The red button and the studio tab while recording: the time on both (called every 400 ms)
function updateRecordButtonState() {
  const btn = document.getElementById('tb-rec');
  if (!btn) return;
  const recording = isRecording();
  const timer = document.getElementById('studio-timer').textContent;
  btn.classList.toggle('tb-rec-on', recording);
  const starting = _quickRecBusy && !recording;
  btn.classList.toggle('tb-rec-busy', starting);
  btn.setAttribute('aria-busy', String(starting));
  document.getElementById('tb-rec-label').textContent = recording ? t('tbRecStop') : starting ? t('tbRecStarting') : t('tbRecord');
  const clock = document.getElementById('tb-rec-clock');
  clock.textContent = recording ? timer : '';
  clock.classList.toggle('hidden', !recording);
  syncLibLiveRow();
  if (!recording && recSrc.mic.used + recSrc.sys.used) recSourcesStop();  // a recording that ended another way
  btn.title = recording ? t('tipTbRecordStop') : t('tipTbRecord');
  btn.setAttribute('aria-label', btn.title);  // in its idle state the button is a dot without words
  // The recording's screen opens from the strip of the meeting while it records (pult.js), its settings from ▾
  document.getElementById('tb-rec-more').classList.toggle('hidden', recording || starting);
  // While it records, its screen is the text, the notes and the people: the presets and the sources fold away
  document.getElementById('studio-view')?.classList.toggle('st-live', recording);
  if (recording && typeof hmAskExpire === 'function') hmAskExpire();  // «Через минуту: …» has no point now
}

// The red button's menu (asked by the user: one place for recording instead of a «Студия» tab, its card on
// the dashboard and the dictation card): record with a preset, with the captions, dictate, the settings
function openRecMenu(e) {
  e.stopPropagation();
  // a second click on ▾ closes the menu it opened (reported by the user: it stayed open)
  const open = document.getElementById('rec-menu');
  if (open) { open.remove(); return; }
  const menu = document.createElement('div');
  menu.id = 'rec-menu';
  menu.className = 'fixed w-80 macos-menu z-50';
  menu.setAttribute('role', 'menu');
  const def = defaultRecordPresetId();
  const key = state.system?.settings?.record_hotkey ?? 'Ctrl+Alt+R';  // empty: the hotkey is off
  const dkey = state.system?.settings?.dictation_hotkey ?? 'Ctrl+Alt+D';
  const item = (fn, args, label, mark = '', hint = '') => `<button class="macos-menu-item rec-mi" role="menuitem" data-fn="${fn}" data-args='${escapeHtml(JSON.stringify(args))}'>`
    + `<span class="rec-mi-mark" aria-hidden="true">${mark}</span><span class="flex-1 min-w-0 truncate">${escapeHtml(label)}</span>${hint ? `<kbd class="rec-mi-key">${escapeHtml(hint)}</kbd>` : ''}</button>`;
  menu.innerHTML = `<div class="rec-mh">${escapeHtml(t('recMenuHead'))}</div>`
    + recordPresets().map(p => item('recMenuPreset', [p.id], presetLabel(p), p.id === def ? '✓' : '', p.id === def ? key : '')).join('')
    + '<div class="my-1 h-px bg-white/10"></div>'
    + item('recMenuLive', [], t('recMenuLive'), '◉')
    + item('recMenuDictate', [], t('hmDict'), '🎙', dkey)
    + '<div class="my-1 h-px bg-white/10"></div>'
    + item('recMenuSettings', [], t('tbRecSettings') + '…', '⚙');
  menu.addEventListener('click', ev => {
    const b = ev.target.closest('button[data-fn]');
    if (!b) return;
    menu.remove();
    window[b.dataset.fn](...JSON.parse(b.dataset.args || '[]'));
  });
  document.body.appendChild(menu);
  const r = e.currentTarget.getBoundingClientRect();
  placeMenuAt(menu, { clientX: r.right, clientY: r.bottom + 6 });
  setTimeout(() => document.addEventListener('click', () => menu.remove(), { once: true }), 0);
}

// A preset of the menu: recorded at once, where the user is (as the red button)
async function recMenuPreset(id) {
  state.recPresetId = id;
  await shellQuickRecord();
}

// With the captions and the translation: the recording's screen opens
async function recMenuLive() {
  await quickRecord(state.recPresetId || defaultRecordPresetId());
}

async function recMenuDictate() {
  switchAppView('home');  // its text shows there
  await hmDictToggle();
}

async function recMenuSettings() {
  await openRecordModal(state.recPresetId || defaultRecordPresetId());
}

// --- The settings: a page of the main area. The settings window moves into it the first time ---
function mountSettingsPage() {
  const modal = document.getElementById('modal-settings');
  const view = document.getElementById('settings-view');
  if (!modal || !view || modal.parentElement === view) return;
  view.appendChild(modal);
  modal.classList.remove('fixed', 'inset-0', 'modal-backdrop', 'z-50', 'p-4', 'items-center', 'justify-center');
  modal.classList.add('settings-page');
  modal.removeAttribute('data-click');  // no backdrop to click: it is the page
}

function leaveSettingsPage() {
  const modal = document.getElementById('modal-settings');
  if (!modal || modal.classList.contains('hidden')) return;
  modal.classList.add('hidden');
  stopSettingsAudioTest();
}

// --- The status bar: the queue; the load of the computer and its window are in pult.js ---
// The economy mode (app/economy.py): recording only; set in Settings → Общие or the tray icon's menu
function economyOn() {
  const s = (state.system && state.system.settings) || {};
  const end = Number(s.economy_until || 0);
  return String(s.economy_mode) === 'true' && !(end && Date.now() / 1000 >= end);
}

async function economyOff() {
  const res = await fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ settings: { economy_mode: 'false' } }) }).catch(() => null);
  if (!res || !res.ok) { showError(t('errorGeneric')); return; }
  onEconomyEvent({ on: false });
}

function onEconomyEvent(ev) {
  if (state.system && state.system.settings) {
    state.system.settings.economy_mode = ev.on ? 'true' : 'false';
    state.system.settings.economy_until = ev.until ? String(ev.until) : '';
  }
  const box = document.getElementById('set-economy-mode');
  if (box) box.checked = !!ev.on;
  if (ev.on && typeof stopLiveCaptions === 'function' && liveCap.session) {
    stopLiveCaptions();  // the server ended its session: the recording goes on without them
    const capToggle = document.getElementById('live-captions-toggle');
    if (capToggle && capToggle.checked) { capToggle.checked = false; liveCap.autoOff = true; }  // back after it
    if (typeof renderLiveCaptionsError === 'function') renderLiveCaptionsError(t('economyNoCaptions'));
  }
  renderStatusbar();
}

function renderStatusbar() {
  const eco = document.getElementById('sb-economy');
  if (eco) {
    eco.classList.toggle('hidden', !economyOn());
    // for a time: when it ends (the server turns it off then)
    const end = Number(((state.system && state.system.settings) || {}).economy_until || 0);
    const label = t('sbEconomy') + (end ? ` · ${t('sbEconomyUntil').replace('{time}', () => new Date(end * 1000).toLocaleTimeString(state.uiLang === 'en' ? 'en-GB' : 'ru-RU', { hour: '2-digit', minute: '2-digit' }))}` : '');
    if (eco.textContent !== label) eco.textContent = label;
  }
  // Audit 6.4: a model downloading in the background is seen from every page
  const dl = document.getElementById('sb-dl');
  const downloads = typeof modelDownloadsNow === 'function' ? modelDownloadsNow() : [];
  if (dl) {
    dl.classList.toggle('hidden', !downloads.length);
    if (downloads.length) {
      const d = downloads[0];
      const label = `↓ ${d.name} · ${d.pct || 0}%${downloads.length > 1 ? ` · ${t('sbQueueMore').replace('{n}', () => downloads.length - 1)}` : ''}`;
      if (dl.textContent !== label) dl.textContent = label;
    }
  }
  const text = (id) => (document.getElementById(id)?.textContent || '').trim();
  const put = (id, v) => { const el = document.getElementById(id); if (el && el.textContent !== v) el.textContent = v || '—'; };
  const items = state.queue || [];
  if (typeof renderJobsIsland === 'function') { renderJobsIsland(); renderJobsPop(); }  // the strip's «Очередь» and its window
  const q = document.getElementById('sb-queue');
  if (!q) return;
  const run = items.find(x => x.state === 'running');
  if (!items.length) {
    q.textContent = t('sbQueueEmpty');
    q.classList.remove('sb-queue-busy');
    return;
  }
  const m = run ? (state.meetings.find(x => x.id === run.id) || {}) : {};
  const pct = run ? (m.progress ?? run.progress ?? 0) : 0;
  const more = items.length - (run ? 1 : 0);
  q.textContent = run
    ? `${queueKindLabel(run)} · ${pct}% — «${run.title}»${more ? ` · ${t('sbQueueMore').replace('{n}', () => more)}` : ''}`
    : state.queuePaused ? t('sbQueuePaused').replace('{n}', () => items.length)
    : state.queueMeeting ? t('sbQueueMeeting').replace('{n}', () => items.length) : t('sbQueueWaiting').replace('{n}', () => items.length);
  q.classList.add('sb-queue-busy');
}

function openStatusbarDownloads(e) {
  if (typeof toggleModelsPop === 'function') toggleModelsPop(e);
}

// The queue of the status bar opens the same window as the strip's «Очередь» (pult.js)
function openStatusbarQueue() {
  toggleJobsPop('status');
}
setInterval(() => { if (!document.hidden) renderStatusbar(); }, 2000);

// The first view: the home page
document.addEventListener('DOMContentLoaded', () => {
  if (!state.appView) switchAppView('home');
  refreshTasksCount(true);
  renderStatusbar();
});


// «Выйти» (asked by the user, like the power button of Windows): a menu with «Свернуть в трей» (the window hides, the
// program goes on) and «Выйти полностью» (the whole program closes, after a question). Only in the app's window
// (window.pywebview): a browser has no such button.
function quitApp() {
  const api = window.pywebview && window.pywebview.api;
  if (!api || !api.quit_app) return;
  const btn = document.getElementById('rail-quit');
  const r = btn.getBoundingClientRect();
  // after this click, which closes the menus
  setTimeout(() => openTextMenuAt([
    { label: t('quitToTray'), run: () => { try { api.hide_to_tray && api.hide_to_tray(); } catch (e) {} } },
    { label: t('quitFully'), key: 'Ctrl+Q', danger: true, run: () => quitFully() },
  ], r.right + 6, r.top, { owner: btn }), 0);
}
let quitAsking = false;  // one question at a time: Ctrl+Q pressed twice opened two
async function quitFully() {
  const api = window.pywebview && window.pywebview.api;
  if (!api || !api.quit_app || quitAsking) return;
  quitAsking = true;
  try {
    let st = 'idle';
    try { st = await api.app_state(); } catch (e) {}
    // always asked; while something runs it says what is lost
    const ok = await confirmDialog(t('quitBusyTitle'), t(st === 'recording' ? 'quitBusyRecording' : st === 'idle' ? 'quitIdle' : 'quitBusyWork'), t('quitOk'), true);
    if (!ok) return;
    try { await api.quit_app(); } catch (e) {}
  } finally { quitAsking = false; }
}
function showQuitButton() {
  const api = window.pywebview && window.pywebview.api;
  document.getElementById('rail-quit')?.classList.toggle('hidden', !(api && api.quit_app));
}
window.addEventListener('pywebviewready', showQuitButton);
showQuitButton();
document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && !e.shiftKey && !e.altKey && (e.code === 'KeyQ') && window.pywebview && window.pywebview.api) {
    e.preventDefault();
    if (!e.repeat) quitFully();
  }
});
