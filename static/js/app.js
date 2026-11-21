// Verbaliox page script, part 9 of 9: Updates, start-up, analysis and chapters, export, folders, Obsidian, details, the text menu.
// The parts are classic scripts sharing one global scope, loaded in order by index.html.

// --- Updates (app/updater.py): check GitHub Releases, download, verify, install on request ---
const updateState = { info: null, notified: false, polling: false };

function renderUpdateStatus() {
  renderUpdatePill();  // the mark in the sidebar, whatever page is open
  const info = updateState.info;
  const text = document.getElementById('update-status-text');
  const btn = document.getElementById('update-install-btn');
  if (!text || !info) return;
  const dl = info.download || {};
  const ver = () => (info.latest || {}).version || '';
  let msg = t('updInstalled').replace('{v}', () => info.current);
  if (dl.active) msg += ' ' + t('updDownloading').replace('{v}', () => ver()).replace('{pct}', () => dl.progress);
  else if (dl.error) msg += ' ' + dl.error;
  else if (info.available && info.git_checkout) msg += ' ' + t('updGitClone').replace('{v}', () => ver());
  else if (info.available && dl.done) msg += ' ' + t(info.auto ? 'updDownloadedOnExit' : 'updDownloaded').replace('{v}', () => ver());
  else if (info.available) msg += ' ' + t('updAvailable').replace('{v}', () => ver());
  else if (info.error) msg += ' ' + t('updCheckFailed').replace('{why}', () => info.error);
  else if (info.checked_at) msg += ' ' + t('updLatest');
  text.textContent = msg;
  // a git clone: «Обновить через git» runs update.bat (git pull and the packages), the app restarts
  const viaGit = !!(info.available && info.git_checkout);
  btn.classList.toggle('hidden', !(info.can_install || viaGit) || !!dl.active);
  btn.textContent = viaGit ? t('updateGitBtn') : dl.done ? t('updateRestartBtn') : t('updateInstallBtn');
}

// The mark of a new version under the library (asked by the user: a toast in a hidden window went unseen)
function renderUpdatePill() {
  const info = updateState.info;
  const pill = document.getElementById('upd-pill');
  if (!pill) return;
  const on = !!(info && info.available && info.latest);
  pill.classList.toggle('hidden', !on);
  if (!on) return;
  const dl = info.download || {};
  document.getElementById('upd-pill-text').textContent = (dl.done && !dl.stale ? t('updPillReady') : t('updPill'))
    .replace('{v}', () => info.latest.version);
}

// The release's text for the language of the page: its section «X.Y.Z — English» or «X.Y.Z» (CHANGELOG.md)
function releaseNotesFor(notes) {
  const parts = String(notes || '').split(/^## /m).filter(x => x.trim());
  const en = state.uiLang === 'en';
  const hit = parts.find(p => /english/i.test(p.split('\n')[0]) === en) || parts[0] || '';
  return hit.split('\n').slice(1).join('\n').trim();
}

// What is new in a version, with «Установить» (a new one) or alone (after an update, once)
async function openUpdateDialog(after = false) {
  if (!updateState.info) {
    try { updateState.info = await (await fetch('/api/update')).json(); } catch (e) { return; }
  }
  const info = updateState.info || {};
  const latest = info.latest || {};
  document.getElementById('upd-dlg')?.remove();
  const wrap = document.createElement('div');
  wrap.id = 'upd-dlg';
  wrap.className = 'fixed inset-0 modal-backdrop z-[60] flex items-center justify-center p-4';
  wrap.setAttribute('role', 'dialog');
  wrap.setAttribute('aria-modal', 'true');
  const notes = releaseNotesFor(latest.notes);
  const dl = info.download || {};
  const canGo = !after && info.available && (info.can_install || info.git_checkout);
  const goLabel = info.git_checkout ? t('updateGitBtn') : dl.done && !dl.stale ? t('updateRestartBtn') : t('updateInstallBtn');
  wrap.innerHTML = `<div class="an-dlg upd-dlg modal-card">
      <div class="an-dlg-head"><h2>${escapeHtml((after ? t('updWhatsNew') : t('updNewTitle')).replace('{v}', () => latest.version || info.current))}</h2>
        <button data-a="close" class="an-dlg-x" aria-label="${escapeHtml(t('close'))}">✕</button></div>
      ${after ? '' : `<p class="an-dlg-text">${escapeHtml(t('updNewText').replace('{cur}', () => info.current))}</p>`}
      <div class="upd-notes an-md">${notes ? sanitizedMarkdown(notes) : `<p>${escapeHtml(t('updNoNotes'))}</p>`}</div>
      <div class="an-dlg-foot">
        ${latest.url ? `<button data-a="page" class="an-btn">${escapeHtml(t('updOnGithub'))}</button>` : ''}
        <span class="flex-1"></span>
        <button data-a="close" class="an-btn">${escapeHtml(t(canGo ? 'updLater' : 'close'))}</button>
        ${canGo ? `<button data-a="go" class="an-btn an-btn-primary">${escapeHtml(goLabel)}</button>` : ''}
      </div></div>`;
  document.body.appendChild(wrap);
  wrap.addEventListener('keydown', e => { if (e.key === 'Escape') wrap.remove(); });
  wrap.addEventListener('click', e => {
    const b = e.target.closest('button');
    if (e.target === wrap || (b && b.dataset.a === 'close')) { wrap.remove(); return; }
    if (!b) return;
    if (b.dataset.a === 'page') { openExternal(latest.url); return; }
    if (b.dataset.a === 'go') { wrap.remove(); installUpdate(); }
  });
}

// The first start of a new version: what changed in it, once (not on a fresh install)
function maybeShowWhatsNew() {
  const info = updateState.info;
  if (!info || !info.current) return;
  let seen = null;
  try { seen = localStorage.getItem('vx-seen-version'); localStorage.setItem('vx-seen-version', info.current); } catch (e) { return; }
  // the window after an update (settings.js openAfterUpdate): the notes of this version join the steps it asks
  if (seen && seen !== info.current && info.latest && info.latest.version === info.current && info.latest.notes) {
    openAfterUpdateNotes(releaseNotesFor(info.latest.notes), info.current, info.latest.url || '');
  }
}

async function updateViaGit() {
  if (!(await askConfirm(t('updGitConfirm'), false, t('updateGitBtn')))) return;
  const r = await fetch('/api/update/git', { method: 'POST' });
  if (!r.ok) { showError(serverText((await readJson(r)).detail)); return; }
  showToast(t('updGitStarted'), null, 'status');
}

async function checkForUpdates(force) {
  try {
    const r = force ? await fetch('/api/update/check', { method: 'POST' }) : await fetch('/api/update?check=true');
    updateState.info = await r.json();
  } catch (e) { return; }
  renderUpdateStatus();
  const info = updateState.info;
  if (!force) maybeShowWhatsNew();
  if (info.available && info.auto && (info.download || {}).active) {
    followUpdateDownload();  // started by the server (automatic updates): tell when it is ready
  } else if (!force && info.available && !updateState.notified) {
    updateState.notified = true;
    showToast(t('updToastAvailable').replace('{v}', () => info.latest.version),
      { label: t('updDetails'), onClick: () => openModal('settings', 'updates') });
  } else if (force && !info.available && !info.error) {
    showToast(t('updToastLatest'));
  }
}

// Automatic updates: the download runs on the server; when it is ready the user may restart now
// (otherwise it is installed when the app closes)
async function followUpdateDownload() {
  if (updateState.polling) return;
  updateState.polling = true;
  while (true) {
    await new Promise(res => setTimeout(res, 1500));
    try { updateState.info = await (await fetch('/api/update')).json(); } catch (e) { continue; }
    renderUpdateStatus();
    if (!updateState.info.download.active) break;
  }
  updateState.polling = false;
  const info = updateState.info;
  if (info.download.done && !updateState.notified) {
    updateState.notified = true;
    showToast(t('updToastReady').replace('{v}', () => info.latest.version),
      { label: t('updRestartNow'), onClick: () => installUpdate() });
  }
}

async function installUpdate() {
  const info = updateState.info;
  if (info && info.available && info.git_checkout) { await updateViaGit(); return; }
  if (!info || !info.can_install) return;
  if (!(info.download || {}).done) {
    if (updateState.polling) return;
    const r = await fetch('/api/update/download', { method: 'POST' });
    if (!r.ok) { showError((await r.json()).detail); return; }
    updateState.info = await r.json();
    renderUpdateStatus();
    updateState.polling = true;
    while (true) {
      await new Promise(res => setTimeout(res, 700));
      try { updateState.info = await (await fetch('/api/update')).json(); } catch (e) { continue; }
      renderUpdateStatus();
      if (!updateState.info.download.active) break;
    }
    updateState.polling = false;
    if (!updateState.info.download.done) return;
  }
  const ok = await askConfirm(t('updInstallConfirm').replace('{v}', () => info.latest.version), false, t('cfInstall'));
  if (!ok) return;
  const r = await fetch('/api/update/install', { method: 'POST' });
  if (!r.ok) { showToast(errorText(await readJson(r), r)); return; }
  showToast(t('updInstalling'));
}

// A recording the page before this one did not finish (reloaded mid-recording): saved now, with its notes,
// and said; once more a little later, when its last «still recording» is old enough to be sure
async function saveOrphanRecordings() {
  const res = await fetch('/api/record/orphans/save', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ older_than: 30 }),
  }).catch(() => null);
  const data = res && res.ok ? await res.json().catch(() => null) : null;
  if (data && data.saved) {
    showToast(t('recOrphanSaved'), null, 'success');
    if (typeof loadMeetingsList === 'function') loadMeetingsList();
  }
}

document.addEventListener('DOMContentLoaded', () => {
  setTimeout(saveOrphanRecordings, 2000);
  setTimeout(saveOrphanRecordings, 35000);  // past the 30 s of silence the server waits for
  state.autoScroll = true;
  loadSummaryTemplates();
  setUILanguage(state.uiLang);
  updateVolumeUI();

  const player = document.getElementById('media-player');
  player.volume = state.volume / 100;
  // The wave (click, drag, double click, keys) is wired by redesign_player.js (rpInitWave)

  player.addEventListener('play', () => {
    document.getElementById('icon-play').classList.add('hidden');
    document.getElementById('icon-pause').classList.remove('hidden');
  });
  player.addEventListener('pause', () => {
    document.getElementById('icon-play').classList.remove('hidden');
    document.getElementById('icon-pause').classList.add('hidden');
  });
  player.addEventListener('loadedmetadata', () => {
    if (player.duration && isFinite(player.duration)) {
      document.getElementById('player-total-time').textContent = formatTime(player.duration);
    }
    state.hasVideo = player.videoWidth > 0;
    if (state.theatre && !state.hasVideo) exitTheatre();  // another recording without a picture
    applyVideoLayout();
  });
  player.addEventListener('loadstart', () => {
    // A new recording: hide video controls until we know it has a video track
    state.hasVideo = false;
    if (document.pictureInPictureElement === player) document.exitPictureInPicture().catch(() => {});
    applyVideoLayout();
  });
  player.addEventListener('enterpictureinpicture', applyVideoLayout);
  player.addEventListener('leavepictureinpicture', applyVideoLayout);
  const txBox = document.getElementById('transcript-container');
  const userMoved = () => { state.userScrollAt = Date.now(); };
  ['wheel', 'pointerdown', 'keydown', 'touchmove'].forEach(ev => txBox.addEventListener(ev, userMoved, { passive: true }));
  player.addEventListener('timeupdate', () => {
    const cur = player.currentTime;
    const dur = player.duration || (state.activeMeeting && state.activeMeeting.duration) || 1;
    document.getElementById('player-current-time').textContent = formatTime(cur);
    if (player.paused) renderPlayerWaveform(Math.min(1, cur / dur));  // while playing: redesign_player.js rpTick

    // Following waits while you scroll or click in the text yourself, then picks the current line up again
    const follow = state.autoScroll !== false && !player.paused && Date.now() - (state.userScrollAt || 0) > 4000;
    const activeSegEl = updatePlaybackHighlight(cur, follow);
    updateTheatreCaption(cur);
    updateActiveChapter(cur);

    if (activeSegEl && follow) {
      const container = document.getElementById('transcript-container');
      const rect = activeSegEl.getBoundingClientRect();
      const cRect = container.getBoundingClientRect();
      if (rect.top < cRect.top + 50 || rect.bottom > cRect.bottom - 50) {
        activeSegEl.scrollIntoView({ behavior: scrollMotion(), block: 'center' });
      }
    }
  });

  loadSystemInfo();
  loadSeries();  // the series name in the context menu of a recording
  loadLlmStatus();
  setTimeout(() => checkForUpdates(false), 4000);  // after the page has settled; only if enabled in settings
  setInterval(() => checkForUpdates(false), 3600e3);  // the window may stay open for days (the server asks GitHub every 6 h)
  loadDictionary();
  loadVram();
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) return;
    scheduleVramRefresh(100);
    loadMeetingsList({ poll: true }).then(loadQueue).catch(console.error);  // what changed while the window was in the tray
  });
  startLiveUpdates();
  loadQueue().catch(console.error);
  pollMeetingsLoop();
});

// --- Analysis: sections on the left, the open one on the right ---
// "protocol" is the overview: the summary itself and, around it, cards of the other sections
// (which ones: «Настроить»). A section with a dot is made; one without can be made in one click.
function selectSummaryTab(tab) {
  state.activeSummaryTab = tab;
  renderSummaryPanel();
  document.getElementById('an-main')?.scrollTo({ top: 0 });
}

// --- The user's summary templates: a group of sections of their own ---
async function loadSummaryTemplates() {
  state.summaryTemplates = await fetch('/api/summary-templates').then(r => r.json()).catch(() => []);
  renderTemplateTabs();
}

function renderTemplateTabs() {
  if (String(state.activeSummaryTab || '').startsWith('tpl:') && !anTemplate(state.activeSummaryTab)) state.activeSummaryTab = 'protocol';
  renderSummaryPanel();
}

function anTemplate(key) {
  const id = String(key || '').startsWith('tpl:') ? key.slice(4) : '';
  return id ? (state.summaryTemplates || []).find(x => x.id === id) || null : null;
}

// The sections, by group: {key, label, about, page (has a page of its own), make (a model makes it)}
function analysisSections() {
  const m = state.activeMeeting || {};
  const sums = m.summaries || {};
  const tpls = (state.summaryTemplates || []).map(x => ({ key: `tpl:${x.id}`, label: x.name, about: x.prompt, page: true, make: true, mine: true }));
  return [
    { label: t('anGrpResults'), items: [
      { key: 'protocol', label: t('sumProtocol'), about: t('anAboutProtocol'), page: true, make: true },
      ...((sums.custom || '').trim() || anIsBusy('custom') ? [{ key: 'custom', label: t('anAnswer'), about: '', page: true, make: false }] : []),
    ] },
    { label: t('anGrpWork'), items: [
      // «Следующие шаги» repeated the tasks: only a recording that has one made keeps it
      ...((sums.tasks || '').trim() || anIsBusy('tasks') ? [{ key: 'tasks', label: t('sumTasks'), about: t('tipSumTasks'), page: true, make: true }] : []),
      { key: 'commitments', label: t('sumCommitments'), about: t('tipSumCommitments'), page: true, make: true },
      { key: 'followup', label: t('anLetter'), about: t('tipSumFollowup'), page: true, make: true },
      ...(m.series_id ? [{ key: 'since_last', label: t('sumSinceLast'), about: t('tipSumSinceLast'), page: true, make: true }] : []),
    ] },
    ...(tpls.length ? [{ label: t('anGrpTemplates'), items: tpls }] : []),
    { label: t('anGrpMine'), items: [
      { key: 'mynotes', label: t('notesTitle'), about: t('tipSumMyNotes'), page: true, make: false, mine: true },
      { key: 'mfu', label: t('mfuTitle'), about: t('tipSumMfu'), page: true, make: false, mine: true },
      { key: 'notes', label: t('sumNotes'), about: t('tipSumNotes'), page: true, make: true },
    ] },
  ];
}

// Made only in the overview, without a page of their own
const AN_CARD_ONLY = { tldr: 'anShort', chapters: 'sumChapters' };

function anSectionInfo(key) {
  for (const g of analysisSections()) {
    const it = g.items.find(x => x.key === key);
    if (it) return it;
  }
  if (AN_CARD_ONLY[key]) return { key, label: t(AN_CARD_ONLY[key]), about: t(key === 'tldr' ? 'tipSumTldr' : 'tipSumChapters'), page: false, make: true };
  return { key, label: key, about: '', page: true, make: false };
}

function anHasContent(key) {
  const m = state.activeMeeting;
  if (!m) return false;
  if (key === 'mynotes') return !!(m.user_notes || '').trim();
  if (key === 'mfu') return !!(m.mfu || '').trim();
  if (key === 'commitments') return !!(state.anCommit && state.anCommit.id === m.id && state.anCommit.n > 0);
  return !!((m.summaries || {})[key] || '').trim();
}

// Points of a list in a section's Markdown ("- …", "1. …"): the count next to its name
function anListCount(key) {
  if (key === 'commitments') return state.anCommit && state.activeMeeting && state.anCommit.id === state.activeMeeting.id ? state.anCommit.n : 0;
  const md = ((state.activeMeeting && state.activeMeeting.summaries) || {})[key] || '';
  return (md.match(/^\s*(?:[-*+]|\d+[.)])\s+\S/gm) || []).length;
}

function anBusyKey(key) { return `${state.activeMeeting ? state.activeMeeting.id : 0}:${key}`; }
function anIsBusy(key) { return !!(state.anBusy && state.anBusy.has(anBusyKey(key))); }

// The cards of the overview that are off («Настроить»); kept in this browser only
const AN_OFF_DEFAULT = ['followup', 'notes', 'since_last', 'commitments'];
function anOverviewOff() {
  try {
    const v = JSON.parse(localStorage.getItem('vs.analysisOverviewOff') || 'null');
    return Array.isArray(v) ? v : AN_OFF_DEFAULT.slice();
  } catch (e) { return AN_OFF_DEFAULT.slice(); }
}
function setOverviewOff(list) {
  try { localStorage.setItem('vs.analysisOverviewOff', JSON.stringify(list)); } catch (e) { /* the default stays */ }
}
function toggleOverviewCard(key) {
  const off = anOverviewOff();
  setOverviewOff(off.includes(key) ? off.filter(k => k !== key) : off.concat(key));
  renderSummaryPanel();
}

// How many promises the open recording has (the count of its section)
async function refreshCommitmentCount() {
  const m = state.activeMeeting;
  if (!m) return;
  const items = await fetch(`/api/meetings/${m.id}/commitments`).then(r => r.ok ? r.json() : []).catch(() => []);
  if (state.activeMeeting !== m) return;
  const n = Array.isArray(items) ? items.length : 0;
  const changed = !state.anCommit || state.anCommit.id !== m.id || state.anCommit.n !== n;
  state.anCommit = { id: m.id, n };
  if (changed) renderAnalysisNav();
}

function renderAnalysisNav() {
  const nav = document.getElementById('an-nav');
  if (!nav || !state.activeMeeting) return;
  const cur = state.activeSummaryTab;
  const ai = aiAvailable();
  nav.innerHTML = analysisSections().map(g => `<div class="an-grp">${escapeHtml(g.label)}</div>` + g.items.map(it => {
    const done = anHasContent(it.key), busy = anIsBusy(it.key), n = done && it.key !== 'protocol' ? anListCount(it.key) : 0;
    const dot = done ? (it.mine ? 'an-dot-mine' : 'an-dot-done') : 'an-dot-empty';
    const make = !done && !busy && it.make && ai
      ? `<span class="an-mk" ${pageCall('click', 'createAnalysisSection', [it.key, { $: 'event' }])}>✦ ${escapeHtml(t('anCreate'))}</span>` : '';
    return `<button class="an-navi${it.key === cur ? ' an-navi-on' : ''}" ${pageCall('click', 'selectSummaryTab', [it.key])}
        ${it.key === cur ? 'aria-current="true"' : ''} title="${escapeHtml(it.about || it.label)}">
      <span class="an-dot ${dot}"></span><span class="an-navi-label">${escapeHtml(it.label)}</span>
      ${n > 0 ? `<span class="an-cnt">${n}</span>` : ''}${busy ? `<span class="an-busy">${escapeHtml(t('anMaking'))}</span>` : make}
    </button>`;
  }).join('')).join('')
    + `<button class="an-newtpl" data-click="openTemplateDialog">+ ${escapeHtml(t('anNewTemplate'))}</button>`;
}

// Ready-made starting points for the user's own templates
const TEMPLATE_PRESETS = {
  ru: [
    { name: '1:1', prompt: 'Это встреча один на один руководителя и сотрудника. Выдели: как дела у сотрудника и что его беспокоит, обратную связь в обе стороны, договорённости и следующие шаги (кто — что — когда), темы на следующую встречу.' },
    { name: 'Интервью', prompt: 'Это интервью. Составь портрет собеседника, выпиши ключевые ответы на каждый вопрос с цитатами, сильные стороны и сомнения, и вывод: что важно запомнить.' },
    { name: 'Планёрка', prompt: 'Это планёрка команды. По каждому участнику: что сделано, что в работе, какие блокеры. Отдельно — решения и новые задачи с ответственными и сроками.' },
    { name: 'Лекция', prompt: 'Это лекция или занятие. Выдели основные темы по порядку, определения и примеры, вопросы слушателей с ответами и что стоит повторить или изучить дальше.' },
  ],
  en: [
    { name: '1:1', prompt: 'This is a one-on-one between a manager and a report. Cover: how the person is doing and what worries them, feedback both ways, agreements and next steps (who — what — when), topics for next time.' },
    { name: 'Interview', prompt: 'This is an interview. Profile the person, list the key answers to each question with quotes, strengths and doubts, and a conclusion: what to remember.' },
    { name: 'Stand-up', prompt: 'This is a team stand-up. For each person: done, in progress, blockers. Then the decisions and new tasks with owners and deadlines.' },
    { name: 'Lecture', prompt: 'This is a lecture or a class. Cover the main topics in order, the definitions and examples, the questions from the audience with their answers, and what is worth reviewing or studying next.' },
  ],
};

// --- Chapters: "- [MM:SS] Title — description" lines of the "chapters" analysis ---
function parseChapters(md) {
  const out = [];
  for (const raw of String(md || '').split('\n')) {
    const line = raw.replace(/\*\*|__/g, '');  // models sometimes bold the time stamp
    const m = line.match(/^\s*(?:[-*\d.]+\s*)?\[?(\d{1,2}):(\d{2})(?::(\d{2}))?\]?\s*[-–—:]?\s*(.+?)\s*$/);
    if (!m) continue;
    const secs = m[3] !== undefined ? Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3]) : Number(m[1]) * 60 + Number(m[2]);
    const [title, ...rest] = m[4].split(/\s+[—–-]\s+/);
    out.push({ start: secs, title: title.trim(), desc: rest.join(' — ').trim() });
  }
  return out.sort((a, b) => a.start - b.start);
}

let _chapters = [];
let _activeChapter = -1;

function renderChaptersBar() {
  const m = state.activeMeeting;
  _chapters = parseChapters(m && m.summaries && m.summaries.chapters);
  _activeChapter = -1;
  const bar = document.getElementById('chapters-bar');
  bar.classList.add('hidden');  // the chapters are the bands of the player's wave (asked by the user: not twice)
  document.getElementById('chapters-list').innerHTML = _chapters.map((c, i) =>
    `<button data-click="seekPlayer" data-click-args='[${Number(c.start) || 0}]' id="chapter-${i}" title="${escapeHtml(c.desc || c.title)}"
      class="chapter-chip"><span class="font-mono text-apple-tertiary">${formatTime(c.start)}</span> ${escapeHtml(c.title)}</button>`
  ).join('');
  document.getElementById('chapters-all').textContent = t('chaptersAll').replace('{n}', () => _chapters.length);
  rpRenderChapters();  // the same chapters as bands of the player's wave
  updateActiveChapter(document.getElementById('media-player')?.currentTime || 0);
}

function updateActiveChapter(cur) {
  if (!_chapters.length) return;
  let idx = 0;  // before the first one starts, the first is the current one
  for (let i = 0; i < _chapters.length; i++) if (_chapters[i].start <= cur + 0.25) idx = i;
  if (idx === _activeChapter) return;
  document.getElementById(`chapter-${_activeChapter}`)?.classList.remove('chapter-chip-active');
  const el = document.getElementById(`chapter-${idx}`);
  el?.classList.add('chapter-chip-active');
  _activeChapter = idx;
  centerActiveChapter(true);
}

// The current chapter in the middle of the row: the room before the first and after the last chip
// lets those be centred too
function centerActiveChapter(smooth) {
  const list = document.getElementById('chapters-list');
  const el = document.getElementById(`chapter-${_activeChapter}`);
  if (!list || !el || !list.clientWidth) return;
  const pad = Math.max(0, (list.clientWidth - el.offsetWidth) / 2);
  list.style.paddingLeft = list.style.paddingRight = `${pad}px`;
  const left = el.getBoundingClientRect().left - list.getBoundingClientRect().left + list.scrollLeft;
  list.scrollTo({ left: left - pad, behavior: smooth ? scrollMotion() : 'auto' });
}

// The row shows only the chips that fit: "All chapters" lists them all, the current one ticked
function openChaptersMenu(e) {
  e.stopPropagation();
  const r = e.currentTarget.getBoundingClientRect();
  openTextMenuAt(_chapters.map((c, i) => ({
    label: (i === _activeChapter ? '✓ ' : '') + c.title, key: formatTime(c.start), run: () => seekPlayer(c.start),
  })), r.right, r.bottom + 4, { right: true, maxWidth: 460 });
}

// The mouse wheel scrolls the row of chapters sideways (its scrollbar is hidden)
document.getElementById('chapters-list')?.addEventListener('wheel', (e) => {
  const el = e.currentTarget;
  if (el.scrollWidth <= el.clientWidth || Math.abs(e.deltaX) > Math.abs(e.deltaY)) return;
  e.preventDefault();
  el.scrollLeft += e.deltaY;
}, { passive: false });
// again when the row changes width or comes into view (another tab, the window, the sidebar)
if (window.ResizeObserver && document.getElementById('chapters-list')) {
  // Only a real change of width counts: the row's own side padding (set by the centring) changes its
  // content box, and reacting to that turned the smooth move to the middle into a jump
  let chaptersWidth = 0;
  new ResizeObserver((entries) => {
    const w = Math.round(entries[0].borderBoxSize?.[0]?.inlineSize ?? entries[0].target.offsetWidth);
    if (w === chaptersWidth) return;
    chaptersWidth = w;
    centerActiveChapter(false);
  }).observe(document.getElementById('chapters-list'), { box: 'border-box' });
}

// "Clear" (the section's ⋯): what the open section holds (an analysis, my notes, the promises)
function setClearSummaryVisible(on) {
  state.anCanClear = !!on;
}

async function clearSummaryTab(key) {
  const m = state.activeMeeting;
  if (!m) return;
  const tab = typeof key === 'string' ? key : state.activeSummaryTab;
  const label = anSectionInfo(tab).label || t('tabSummary');
  // Audit 6.1: an analysis section or my notes are cleared at once, «Отменить» brings them back for
  // 7 s and the server forgets them only after that; the promises (tasks of other pages) still ask
  if (tab !== 'commitments') {
    const redraw = () => {
      if (!state.activeMeeting || state.activeMeeting.id !== m.id) return;
      if (tab === 'chapters') renderChaptersBar();
      renderSummaryPanel();
    };
    const notes = m.user_notes, mfu = m.mfu;
    const section = (m.summaries || {})[tab];
    deleteWithUndo({
      message: t('clearTabDoneToast').replace('{tab}', () => label),
      hide: () => {
        if (tab === 'mynotes') m.user_notes = '';
        else if (tab === 'mfu') m.mfu = '';
        else { const rest = { ...(m.summaries || {}) }; delete rest[tab]; m.summaries = rest; }
        redraw();
      },
      restore: () => {
        if (tab === 'mynotes') m.user_notes = notes;
        else if (tab === 'mfu') m.mfu = mfu;
        else m.summaries = { ...(m.summaries || {}), [tab]: section };
        redraw();
      },
      commit: async (keepalive) => {
        const res = tab === 'mynotes'
          ? await fetch(`/api/meetings/${m.id}/notes`, { method: 'PATCH', keepalive, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ notes: '' }) })
          : tab === 'mfu'
          ? await fetch(`/api/meetings/${m.id}/mfu`, { method: 'PUT', keepalive, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text: '' }) })
          : await fetch(`/api/meetings/${m.id}/summaries?key=${encodeURIComponent(tab)}`, { method: 'DELETE', keepalive });
        if (res.ok && !keepalive && tab === 'mfu') refreshTasksAfterMfu(m);
        if (res.ok && !keepalive && tab !== 'mynotes' && tab !== 'mfu' && state.activeMeeting && state.activeMeeting.id === m.id) {
          state.activeMeeting.summaries = (await readJson(res)).summaries || {};
          redraw();
        }
        return res.ok;
      },
    });
    return;
  }
  if (!(await confirmDialog(t('clearTabTitle').replace('{tab}', () => label), t('clearTabText'), t('clearBtn')))) return;
  let res;
  if (tab === 'commitments') {
    res = await fetch(`/api/meetings/${m.id}/commitments`, { method: 'DELETE' });
    if (res.ok) state.anCommit = { id: m.id, n: 0 };
  } else {
    res = await fetch(`/api/meetings/${m.id}/summaries?key=${encodeURIComponent(tab)}`, { method: 'DELETE' });
    if (res.ok) state.activeMeeting.summaries = (await readJson(res)).summaries || {};
  }
  if (!res.ok) { showError((await readJson(res)).detail); return; }
  if (tab === 'chapters') renderChaptersBar();
  renderSummaryPanel();
}

function renderSummaryPanel() {
  const box = document.getElementById('summary-content');
  const m = state.activeMeeting;
  if (!m || !box) return;
  let tab = state.activeSummaryTab;
  const known = analysisSections().some(g => g.items.some(x => x.key === tab));
  if (!known) tab = state.activeSummaryTab = 'protocol';  // a template that is gone, "since last time" off a series
  if (!state.anCommit || state.anCommit.id !== m.id) { state.anCommit = { id: m.id, n: 0 }; refreshCommitmentCount(); }
  setClearSummaryVisible(tab !== 'protocol' && anHasContent(tab));
  if (state.anEdit && (state.anEdit.id !== m.id || state.anEdit.tab !== tab)) state.anEdit = null;  // another section opened
  renderAnalysisNav();
  renderAnalysisHead();
  if (state.anEdit && box.querySelector('.an-edit')) return;  // a section finished in the background keeps the text being edited
  state.anEdit = null;
  if (tab === 'protocol') { renderAnalysisOverview(box); markSuspects(box); return; }
  if (tab === 'mynotes') {
    // a section finished in the background re-renders the panel: the notes being typed keep their caret
    const ed = document.getElementById('my-notes-input');
    if (!(ed && box.contains(ed) && document.activeElement === ed)) renderMyNotesEditor(box);
    return;
  }
  if (tab === 'mfu') {
    // the editor of the same recording keeps its caret; another recording's is drawn again (a text typed
    // for one recording was saved into the next one: found by an audit)
    const ed = document.getElementById('mfu-input');
    if (!(ed && box.contains(ed) && document.activeElement === ed && ed.dataset.mid === String(m.id))) renderMfuEditor(box);
    return;
  }
  if (tab === 'commitments') { renderCommitments(box); return; }
  const summaries = m.summaries || {};
  const md = summaries[tab] || '';
  if (anIsBusy(tab)) { box.innerHTML = anMakingHtml(); return; }
  if (!md) { box.innerHTML = anEmptyHtml(tab, summaries.error); return; }
  if (tab === 'custom' && state.anQuestion && state.anQuestion.id === m.id) {
    box.innerHTML = `<div class="an-question">${escapeHtml(state.anQuestion.text)}</div><div class="markdown-body an-md"></div>`;
    renderMarkdownWithTimestamps(box.querySelector('.an-md'), md, m.duration);
    markSuspects(box);
    return;
  }
  box.innerHTML = '<div class="markdown-body an-md"></div>';
  renderMarkdownWithTimestamps(box.firstElementChild, md, m.duration);
  markSuspects(box);
  if (tab === 'followup') {
    const bar = document.createElement('div');
    bar.className = 'an-bar';
    bar.innerHTML = `<button class="an-btn an-btn-primary">${escapeHtml(t('followupOpenMail'))}</button>`;
    bar.querySelector('button').onclick = () => openFollowupMail(md);
    box.appendChild(bar);
  }
}

function anMakingHtml() {
  return `<div class="an-empty an-making"><span>${escapeHtml(t('uiGeneratingAnalysis'))}</span>
    <span class="an-chip-sm">${escapeHtml(summaryModelChoice().prettyModel)}</span></div>`;
}

// A section not made yet: what it will hold, and the button that makes it
function anEmptyHtml(key, error) {
  const it = anSectionInfo(key);
  const ai = aiAvailable();
  return `<div class="an-empty">
      <div class="an-empty-title">${escapeHtml(t('anNotMade'))}</div>
      ${it.about ? `<p class="an-empty-about">${escapeHtml(it.about)}</p>` : ''}
      ${it.make ? `<button class="an-btn an-btn-primary" ${ai ? '' : `aria-disabled="true" title="${escapeHtml(t('anNeedModel'))}"`} ${pageCall('click', 'createAnalysisSection', [key])}>
        <svg class="tb-ai" viewBox="0 0 24 24" aria-hidden="true"><path d="M10 2l1.9 5.6 5.6 1.9-5.6 1.9L10 17l-1.9-5.6-5.6-1.9 5.6-1.9z"/><path d="M18.5 13l.9 2.6 2.6.9-2.6.9-.9 2.6-.9-2.6-2.6-.9 2.6-.9z"/></svg>
        ${escapeHtml(t('anCreateWithModel'))}</button>` : ''}
      ${error ? `<div class="an-error">${escapeHtml(error)}</div>` : ''}
    </div>`;
}

// The head of the open section: its name, the model, what can be done with it
function renderAnalysisHead() {
  const tab = state.activeSummaryTab;
  const it = anSectionInfo(tab);
  const has = anHasContent(tab), busy = anIsBusy(tab), ai = aiAvailable();
  const overview = tab === 'protocol';
  document.getElementById('an-noai')?.classList.toggle('hidden', ai);
  const title = document.getElementById('an-title');
  if (title) title.textContent = it.label;
  const sub = document.getElementById('an-sub');
  if (sub) sub.textContent = tab === 'mynotes' ? t('anNotesSub') : tab === 'mfu' ? t('mfuSub') : busy ? t('anMaking') : '';
  const sel = document.getElementById('summary-llm-select');
  const name = document.getElementById('an-model-name');
  const opt = sel && sel.selectedIndex >= 0 ? sel.options[sel.selectedIndex] : null;
  if (name) {
    name.textContent = opt ? opt.textContent : '—';
    name.closest('button')?.classList.toggle('an-model-off', !!opt && opt.dataset.off === '1');
  }
  // the overview has its bar above the cards (renderAnalysisOverview): the model, «Настроить», «Пересоздать анализ»
  document.getElementById('an-model-btn')?.parentElement.classList.toggle('hidden', !it.make || overview);
  document.getElementById('an-cfg-btn')?.classList.toggle('hidden', true);
  const gen = document.getElementById('generate-summary-btn');
  if (gen) {
    gen.classList.toggle('hidden', !it.make || overview);
    gen.disabled = busy;
    gen.setAttribute('aria-disabled', String(!ai));
    gen.title = ai ? t('tipGenerateSummary') : t('anNeedModel');
    const label = document.getElementById('an-gen-label');
    if (label) label.textContent = busy ? t('anMaking') : t(has ? 'anRegen' : 'anCreate');
  }
  const shown = overview ? anHasContent('protocol') : has;
  document.getElementById('an-copy-btn')?.classList.toggle('hidden', !shown || tab === 'commitments');
  document.getElementById('an-exp-btn')?.classList.toggle('hidden', !shown && tab !== 'commitments');
  const edit = document.getElementById('an-edit-btn');
  if (edit) {
    const key = overview ? 'protocol' : tab;
    edit.classList.toggle('hidden', !anEditable(key) || busy || anIsBusy(key) || !!state.anEdit);
  }
}

// Overview: «Итоги» in cards (docs/pult-plan.md, stage 5). «Коротко», «Решения», «Задачи», «Отмечено» and
// «Мои заметки» on the left, «Темы» on the right; each card's head has the icon of its kind, the name and the
// count at the right end; the moments are quiet links «▶ 06:12» that play from there. The rest of the protocol
// and the other sections chosen in «Настроить» follow; what is not made yet is offered below
function renderAnalysisOverview(box) {
  const m = state.activeMeeting;
  const sums = m.summaries || {};
  const off = anOverviewOff();
  const ai = aiAvailable();
  const icon = (kind) => `<span class="sc-ic" aria-hidden="true">${recCardIcon(kind)}</span>`;
  const act = (fn, args, label, mark) => `<button class="sc-act" ${pageCall('click', fn, args)} title="${escapeHtml(label)}" aria-label="${escapeHtml(label)}">${mark}</button>`;
  // one card: the head (icon, name, the actions on hover, the count at the right end), its body
  const card = (key, title, body, opts = {}) => `<section class="scard${opts.cls ? ` ${opts.cls}` : ''}" data-card="${escapeHtml(key)}">
      <h3 class="sc-h">${icon(opts.icon || 'doc')}<span class="sc-name">${escapeHtml(title)}</span>
        ${opts.tag ? `<span class="an-tag">${escapeHtml(opts.tag)}</span>` : ''}<span class="flex-1"></span>
        ${opts.edit ? act(opts.editFn || 'editAnalysisSection', [opts.edit], t('anEditTip'), '✎') : ''}
        ${opts.regen && ai ? act('createAnalysisSection', [key], t('anRegen'), AI_MARK) : ''}
        ${opts.open ? `<button class="sc-open" ${pageCall('click', 'selectSummaryTab', [opts.open])}>${escapeHtml(t('anOpen'))} →</button>` : ''}
        <b class="sc-n">${opts.count != null ? opts.count : ''}</b></h3>
      <div class="an-cardb${opts.clamp ? ' an-clamp' : ''}">${body}</div>
    </section>`;
  const md = (key) => `<div class="markdown-body an-md" data-md="${escapeHtml(key)}"></div>`;
  const making = `<div class="sc-quiet">${escapeHtml(t('anMaking'))}</div>`;
  const quiet = (text) => `<div class="sc-quiet">${escapeHtml(text)}</div>`;
  const make = (key) => (ai ? `<button class="sc-make" ${pageCall('click', 'createAnalysisSection', [key])}>✦ ${escapeHtml(t('anCreate'))}</button>` : '');
  const at = (sec) => (sec != null ? `<button class="sc-at" ${pageCall('click', 'seekPlayer', [Number(sec) || 0])} title="${escapeHtml(t('recListenFrom'))}">▶ ${formatTime(sec)}</button>` : '<span class="sc-at" aria-hidden="true"></span>');
  const row = (text, sec, lead = '') => `<div class="sc-row">${lead}<span class="sc-t">${escapeHtml(text)}</span>${at(sec)}</div>`;

  const protocol = String(sums.protocol || '');
  const dec = recMdSection(protocol, REC_DECISION_HEADS);
  const next = recMdSection(dec.rest, REC_NEXT_HEADS);
  const rest = /[^\s#*_-]/.test(next.rest.replace(/^\s*#{1,6}\s.*$/gm, '')) ? next.rest.trim() : '';  // more than headings
  const notes = recNotes(m.user_notes);

  // «Коротко»
  const tldr = anIsBusy('tldr') ? making : anHasContent('tldr') ? md('tldr') : `${quiet(t('anNotMade'))}${make('tldr')}`;
  const lead = off.includes('tldr') ? '' : card('tldr', t('anShort'), tldr, { icon: 'sum', cls: 'lead', edit: anHasContent('tldr') ? 'tldr' : '', regen: anHasContent('tldr') });
  // «Решения»: the points of the protocol's «Решения»
  const decBody = anIsBusy('protocol') ? making
    : dec.items.length ? dec.items.map(x => row(x.text, x.at, '<span class="sc-dot"></span>')).join('')
    : quiet(dec.found ? t('recNoDecisions') : anHasContent('protocol') ? t('recNoDecisions') : t('recAfterAnalysis'));
  const decisions = card('decisions', t('recDecisions'), decBody, { icon: 'dec', count: dec.items.length || '', edit: anEditable('protocol') ? 'protocol' : '' });
  // «Задачи»: the tasks of the recording (filled by recFillTasks); the protocol's «Следующие шаги» until then
  const tasks = card('rec-tasks', t('recTasks'), recTasksBody(next.items), { icon: 'task', count: '', open: 'commitments' });
  // «Отмечено» and «Мои заметки»: the lines of the notes, the marks (⚑) apart
  const marksBody = notes.marks.length ? notes.marks.map(x => row(x.text || t('recMark'), x.at)).join('') : quiet(t('recNoMarks'));
  const notesBody = notes.lines.length ? notes.lines.map(x => row(x.text, x.at)).join('') : quiet(t('anNoNotes'));
  const mine = `<div class="sum-two">${card('rec-marks', t('recMarked'), marksBody, { icon: 'mark', count: notes.marks.length || '', edit: 'mynotes', editFn: 'selectSummaryTab' })}
    ${off.includes('mynotes') ? '' : card('mynotes', t('notesTitle'), notesBody, { icon: 'note', count: notes.lines.length || '', edit: 'mynotes', editFn: 'selectSummaryTab' })}</div>`;
  // «Темы»: the chapters, each a link to its moment
  const chs = parseChapters(sums.chapters);
  const topicsBody = anIsBusy('chapters') ? making
    : chs.length ? chs.map(c => `<button class="sc-row link" ${pageCall('click', 'seekPlayer', [Number(c.start) || 0])} title="${escapeHtml(c.desc || t('anListenChapter'))}"><span class="sc-t">${escapeHtml(c.title)}</span><span class="sc-at">${formatTime(c.start)}</span></button>`).join('')
    : anHasContent('chapters') ? md('chapters') : `${quiet(t('anNotMade'))}${make('chapters')}`;
  const topics = off.includes('chapters') ? '' : card('chapters', t('recTopics'), topicsBody, { icon: 'topic', count: chs.length || '', regen: anHasContent('chapters') });

  // the rest of the protocol, and the other sections as before
  const cards = [];
  const missing = [];
  const consider = (key, title, render, opts) => {
    if (anIsBusy(key)) { cards.push(card(key, title, making)); return; }
    if (!anHasContent(key)) { if (opts.make !== false) missing.push({ key, title, about: anSectionInfo(key).about }); return; }
    if (off.includes(key)) return;
    cards.push(render());
  };
  if (anHasContent('protocol') && !anIsBusy('protocol')) {
    cards.push(`<div class="${rest ? '' : 'hidden'}">${card('protocol', t('anResults'), `<div class="markdown-body an-md" data-md-rest="1"></div>`, { icon: 'doc', edit: anEditable('protocol') ? 'protocol' : '' })}</div>`);
  } else if (!anIsBusy('protocol')) missing.unshift({ key: 'protocol', title: t('anResults'), about: t('anAboutProtocol') });
  consider('tasks', t('sumTasks'), () => card('tasks', t('sumTasks'), md('tasks'), { icon: 'task', count: anListCount('tasks'), open: 'tasks', clamp: true }), { make: false });
  (state.summaryTemplates || []).forEach(x => {
    const key = `tpl:${x.id}`;
    consider(key, x.name, () => card(key, x.name, md(key), { count: anListCount(key), tag: t('anMyTemplate'), open: key, clamp: true }), {});
  });
  consider('followup', t('anLetter'), () => card('followup', t('anLetter'), md('followup'), { icon: 'mail', open: 'followup', clamp: true }), {});
  if (m.series_id) consider('since_last', t('sumSinceLast'), () => card('since_last', t('sumSinceLast'), md('since_last'), { open: 'since_last', clamp: true }), {});
  consider('notes', t('sumNotes'), () => card('notes', t('sumNotes'), md('notes'), { icon: 'note', open: 'notes', clamp: true }), {});
  if ((m.mfu || '').trim()) {
    const lines = String(m.mfu).split('\n').map(s => s.trim()).filter(Boolean).slice(0, 6);
    cards.push(card('mfu', t('mfuTitle'), lines.map(s => `<div class="an-row-text">${escapeHtml(s)}</div>`).join(''), { icon: 'note', open: 'mfu' }));
  }
  const ask = `<button class="sum-ask" data-click="runCustomQuestion" ${ai ? '' : `aria-disabled="true" title="${escapeHtml(t('anNeedModel'))}"`}>${recCardIcon('ask')}<span>${escapeHtml(t('recAskPh'))}</span></button>`;
  box.innerHTML = `${recAnalysisBar()}<div class="sum-grid">
      <div class="sum-main">${lead}${decisions}${tasks}${mine}${cards.join('')}</div>
      <div class="sum-side">${topics}${ask}</div>
    </div>`
    + (missing.length ? `<section class="an-missing"><div class="an-grp an-grp-flat">${escapeHtml(t('anCanMake'))}</div>
      <div class="an-missing-grid">${missing.map(x => `<div class="an-tile">
          <span class="an-tile-text"><b>${escapeHtml(x.title)}</b><span>${escapeHtml(x.about || '')}</span></span>
          <button class="an-tile-btn" ${ai ? '' : `aria-disabled="true" title="${escapeHtml(t('anNeedModel'))}"`} ${pageCall('click', 'createAnalysisSection', [x.key])}>✦ ${escapeHtml(t('anCreate'))}</button>
        </div>`).join('')}</div></section>` : '');
  box.querySelectorAll('[data-md]').forEach(el => renderMarkdownWithTimestamps(el, sums[el.dataset.md] || '', m.duration));
  const restEl = box.querySelector('[data-md-rest]');
  if (restEl) renderMarkdownWithTimestamps(restEl, rest, m.duration);
  markUnverified(box.querySelector('.sum-main'));
  recFillTasks(box, next.items);
}

// The menus of the section's head: the model, «Настроить» (the overview's cards), «Экспорт», ⋯
function openAnalysisMenu(kind, el) {
  const r = el.getBoundingClientRect();
  // after this click closes menus; the «⋯» at the right end opens leftwards from its right edge
  const at = (items) => setTimeout(() => (kind === 'dots' ? openTextMenuAt(items, r.right, r.bottom + 6, { right: true }) : openTextMenuAt(items, r.left, r.bottom + 6)), 0);
  const tab = state.activeSummaryTab;
  const m = state.activeMeeting;
  if (!m) return;
  if (kind === 'model') {
    const sel = document.getElementById('summary-llm-select');
    const opts = sel ? [...sel.options].filter(o => o.value) : [];
    at([...opts.map(o => ({ label: `${o.value === sel.value ? '✓ ' : '   '}${o.textContent}`, run: () => {
        sel.value = o.value;
        sel.dispatchEvent(new Event('change', { bubbles: true }));
        renderAnalysisHead();
      } })),
      { sep: true }, { label: t('anModelsSettings'), run: () => openModal('settings', 'analysis') }]);
  } else if (kind === 'cfg') {
    openOverviewConfig(el);
  } else if (kind === 'exp') {
    const items = [];
    if (anSectionText(tab).trim()) items.push({ label: t('anExportMd'), key: '.md', run: () => saveSectionMarkdown(tab) });
    if (tab === 'commitments') {
      items.push({ label: `${t('sumCommitments')}: Markdown`, run: () => exportCommitments('md', m.id) },
        { label: `${t('sumCommitments')}: Todoist`, key: 'CSV', run: () => exportCommitments('todoist', m.id) },
        { label: `${t('sumCommitments')}: ${t('commitmentsTable')}`, run: () => exportCommitments('csv', m.id) });
    }
    items.push({ sep: true }, { label: t('anExportWord'), key: '.docx', run: () => exportMeetingById(m.id, 'docx') },
      { label: t('anExportObsidian'), run: () => exportToObsidian(m.id) });
    at(items);
  } else if (kind === 'dots') {
    const tpl = anTemplate(tab);
    const items = [];
    // what the head showed as buttons (asked by the user: eight of them over a section): «Настроить»,
    // the export, the doubtful words; the buttons still say when each applies (renderAnalysisHead)
    const applies = id => { const b = document.getElementById(id); return !!b && !b.classList.contains('hidden'); };
    if (tab === 'protocol') items.push({ label: `${t('anCfgTitle')}…`, run: () => openOverviewConfig(el) });
    items.push({ label: `${t('anAskMenu')}…`, disabled: !aiAvailable(), run: () => runCustomQuestion() });
    if (applies('an-exp-btn')) {
      items.push({ sep: true });
      if (anSectionText(tab).trim()) items.push({ label: `${t('anExport')}: ${t('anExportMd')}`, key: '.md', run: () => saveSectionMarkdown(tab) });
      if (tab === 'commitments') {
        items.push({ label: `${t('anExport')}: ${t('sumCommitments')} Markdown`, run: () => exportCommitments('md', m.id) },
          { label: `${t('anExport')}: Todoist`, key: 'CSV', run: () => exportCommitments('todoist', m.id) });
      }
      items.push({ label: `${t('anExport')}: ${t('anExportWord')}`, key: '.docx', run: () => exportMeetingById(m.id, 'docx') },
        { label: `${t('anExport')}: ${t('anExportObsidian')}`, run: () => exportToObsidian(m.id) });
    }
    if (applies('an-wavy-btn')) items.push({ sep: true }, { label: t(suspectsHidden() ? 'anSuspectsShow' : 'anSuspectsHide'), run: () => toggleSuspects() });
    items.push({ sep: true });
    if (tpl) items.push({ label: t('anEditTemplate'), run: () => openTemplateDialog(tpl) });
    items.push({ label: t('anAllTemplates'), run: () => openTemplatesEditor() });
    if (analysisTextShown()) items.push({ label: t('anCheckWords'), disabled: !aiAvailable() || !!state.anChecking, run: () => checkAnalysisWords() });
    if (tab !== 'protocol' && anEditable(tab)) items.push({ sep: true }, { label: t('anEdit'), run: () => editAnalysisSection(tab) });
    if (tab === 'protocol') {
      const keys = ['protocol', 'tldr'].filter(anEditable);
      if (keys.length) items.push({ sep: true }, ...keys.map(key => ({ label: `${t('anEdit')}: ${key === 'protocol' ? t('anResults') : t('anShort')}`, run: () => editAnalysisSection(key) })));
    }
    if (tab !== 'protocol' && state.anCanClear) items.push({ sep: true }, { label: t('anClearSection'), run: () => clearSummaryTab(tab) });
    if (tab === 'protocol') {
      for (const key of ['protocol', 'tldr', 'chapters']) if (anHasContent(key)) items.push({ label: `${t('anClearSection')}: ${anSectionInfo(key).label}`, run: () => clearSummaryTab(key) });
    }
    at(items);
  }
}

// «Настроить»: which cards the overview shows (made ones; the others are offered below it)
function openOverviewConfig(el) {
  document.getElementById('an-cfg-pop')?.remove();
  const keys = [['tldr', t('anShort')], ['chapters', t('sumChapters')], ...(anHasContent('tasks') ? [['tasks', t('sumTasks')]] : []),
    ['followup', t('anLetter')], ...(state.activeMeeting && state.activeMeeting.series_id ? [['since_last', t('sumSinceLast')]] : []),
    ['notes', t('sumNotes')], ['mynotes', t('notesTitle')],
    ...(state.summaryTemplates || []).map(x => [`tpl:${x.id}`, x.name])];
  const off = anOverviewOff();
  const pop = document.createElement('div');
  pop.id = 'an-cfg-pop';
  pop.className = 'an-pop';
  pop.setAttribute('role', 'dialog');
  pop.innerHTML = `<div class="an-pop-title">${escapeHtml(t('anCfgTitle'))}</div>`
    + keys.map(([k, label]) => `<label class="an-pop-row"><input type="checkbox" data-k="${escapeHtml(k)}" ${off.includes(k) ? '' : 'checked'}>
        <span class="flex-1">${escapeHtml(label)}</span><span class="an-pop-tag">${escapeHtml(anHasContent(k) ? '' : t('anNotMadeShort'))}</span></label>`).join('')
    + `<div class="an-pop-foot"><button class="an-pop-link" data-a="new">+ ${escapeHtml(t('anNewTemplate'))}</button></div>`;
  pop.addEventListener('change', e => {
    const k = e.target.dataset && e.target.dataset.k;
    if (k) toggleOverviewCard(k);
  });
  pop.addEventListener('click', e => {
    if (e.target.closest('[data-a="new"]')) { pop.remove(); openTemplateDialog(null); }
  });
  document.body.appendChild(pop);
  const r = el.getBoundingClientRect();
  const w = pop.getBoundingClientRect();
  pop.style.left = `${Math.max(8, Math.min(zpx(r.right - w.width), viewW() - zpx(w.width) - 8))}px`;
  pop.style.top = `${Math.max(8, Math.min(zpx(r.bottom + 6), viewH() - zpx(w.height) - 8))}px`;
  const away = (e) => {
    if (e.type === 'keydown' && e.key !== 'Escape') return;
    if (e.type === 'mousedown' && (pop.contains(e.target) || el.contains(e.target))) return;
    pop.remove();
    document.removeEventListener('mousedown', away, true);
    document.removeEventListener('keydown', away, true);
  };
  setTimeout(() => { document.addEventListener('mousedown', away, true); document.addEventListener('keydown', away, true); }, 0);
}

// The section as a Markdown file (the overview: the short summary, the summary and the chapters)
async function saveSectionMarkdown(key) {
  const m = state.activeMeeting;
  const text = anSectionText(key).replaceAll('[?]', `(${t('unverifiedBadge')})`).trim();
  if (!m || !text) return;
  const label = anSectionInfo(key).label;
  const name = `${(m.title || 'meeting').replace(/[\\/:*?"<>|]+/g, '_').trim()} — ${label}.md`;
  const blob = new Blob([`# ${m.title || ''} — ${label}\n\n${text}\n`], { type: 'text/markdown' });
  if (typeof window.showSaveFilePicker === 'function') {
    try {
      const handle = await window.showSaveFilePicker({ suggestedName: name, types: [{ description: 'Markdown (*.md)', accept: { 'text/markdown': ['.md'] } }] });
      const w = await handle.createWritable();
      await w.write(blob);
      await w.close();
      showToast(`${t('exportSavedTo')} ${handle.name}`);
      return;
    } catch (err) {
      if (err && (err.name === 'AbortError' || err.code === 20)) return;
    }
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { a.remove(); URL.revokeObjectURL(url); }, 4000);
  showToast(`${t('exportSavedTo')} ${name}`);
}

// A template of one's own: a name and what to find in the recording; shown in the overview or not
function openTemplateDialog(tpl) {
  document.getElementById('an-tpl-dlg')?.remove();
  const editing = !!(tpl && tpl.id);
  const key = editing ? `tpl:${tpl.id}` : '';
  const wrap = document.createElement('div');
  wrap.id = 'an-tpl-dlg';
  wrap.className = 'fixed inset-0 modal-backdrop z-[60] flex items-center justify-center p-4';
  wrap.setAttribute('role', 'dialog');
  wrap.setAttribute('aria-modal', 'true');
  wrap.innerHTML = `<div class="an-dlg modal-card">
      <div class="an-dlg-head"><h2>${escapeHtml(t(editing ? 'anTplEditTitle' : 'anTplNewTitle'))}</h2>
        <button data-a="no" class="an-dlg-x" aria-label="${escapeHtml(t('close'))}">✕</button></div>
      <label class="an-fld-label">${escapeHtml(t('anTplName'))}
        <input data-f="name" maxlength="60" class="an-fld" value="${escapeHtml(editing ? tpl.name : '')}"></label>
      <label class="an-fld-label">${escapeHtml(t('anTplPrompt'))}
        <textarea data-f="prompt" rows="5" maxlength="4000" class="an-fld" placeholder="${escapeHtml(t('anTplPromptPh'))}">${escapeHtml(editing ? tpl.prompt : '')}</textarea></label>
      <label class="an-pop-row"><input type="checkbox" data-f="show" ${editing && anOverviewOff().includes(key) ? '' : 'checked'}>
        <span>${escapeHtml(t('anTplShow'))}</span></label>
      ${editing ? '' : `<label class="an-pop-row"><input type="checkbox" data-f="make" ${aiAvailable() && state.activeMeeting ? 'checked' : 'disabled'}>
        <span>${escapeHtml(t('anTplMakeNow'))}</span></label>`}
      <div class="an-dlg-foot">
        ${editing ? `<button data-a="del" class="an-btn an-btn-danger">${escapeHtml(t('ctxDelete'))}</button>` : ''}
        <span class="flex-1"></span>
        <button data-a="no" class="an-btn">${escapeHtml(t('cancel'))}</button>
        <button data-a="save" class="an-btn an-btn-primary">${escapeHtml(t('save'))}</button>
      </div></div>`;
  const val = (f) => wrap.querySelector(`[data-f="${f}"]`);
  const save = async (list) => {
    const res = await fetch('/api/summary-templates', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ templates: list }) });
    const data = await readJson(res);
    if (!res.ok) { showError(serverText(data.detail)); return null; }
    state.summaryTemplates = data;
    return data;
  };
  wrap.addEventListener('click', async e => {
    const b = e.target.closest('button');
    if (e.target === wrap || (b && b.dataset.a === 'no')) { wrap.remove(); return; }
    if (!b) return;
    const all = (state.summaryTemplates || []).map(x => ({ ...x }));
    if (b.dataset.a === 'del') {
      // Audit 6.1: removed at once, «Отменить» saves the list as it was
      if (await save(all.filter(x => x.id !== tpl.id))) {
        removeWithExit(wrap);
        renderTemplateTabs();
        showToast(t('anTplDeletedToast').replace('{name}', () => tpl.name), { label: t('rdSasUndo'), onClick: async () => { if (await save(all)) renderTemplateTabs(); } });
      }
      return;
    }
    if (b.dataset.a !== 'save') return;
    const name = val('name').value.trim(), prompt = val('prompt').value.trim();
    if (!name || !prompt) { (name ? val('prompt') : val('name')).focus(); return; }
    const before = new Set(all.map(x => x.id));
    const list = editing ? all.map(x => x.id === tpl.id ? { ...x, name, prompt } : x) : all.concat({ id: '', name, prompt });
    const saved = await save(list);
    if (!saved) return;
    const made = editing ? saved.find(x => x.id === tpl.id) : saved.find(x => !before.has(x.id));
    wrap.remove();
    if (made) {
      const k = `tpl:${made.id}`;
      const off = anOverviewOff().filter(x => x !== k);
      setOverviewOff(val('show').checked ? off : off.concat(k));
      state.activeSummaryTab = k;
      if (!editing && val('make') && val('make').checked) { createAnalysisSection(k); return; }
    }
    renderTemplateTabs();
  });
  document.body.appendChild(wrap);
  val('name').focus();
}

// A section made (or made again) by the model chosen above; several can be made at once
async function createAnalysisSection(key, ev) {
  if (ev && ev.stopPropagation) ev.stopPropagation();
  const m = state.activeMeeting;
  if (!m) return;
  if (!aiAvailable()) { flashNoAiBanner(); return; }
  state.anBusy = state.anBusy || new Set();
  const busy = `${m.id}:${key}`;
  if (state.anBusy.has(busy)) return;
  state.anBusy.add(busy);
  syncAnalysisMark();
  if (state.activeMeeting === m) renderSummaryPanel();
  const { chosenModel } = summaryModelChoice();
  try {
    let res;
    if (key === 'commitments') {
      res = await fetch(`/api/meetings/${m.id}/commitments`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: chosenModel }) });
    } else if (key === 'since_last') {
      res = await fetch(`/api/meetings/${m.id}/since-last`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: chosenModel, lang: state.uiLang }) });
    } else {
      res = await fetch(`/api/meetings/${m.id}/summary`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ template: key, model: chosenModel, lang: state.uiLang }) });
    }
    const data = await readJson(res);
    if (!res.ok) throw new Error(data.detail || t('errorGeneric'));
    if (data.summaries) m.summaries = data.summaries;
    if (key === 'commitments') {
      state.anCommit = { id: m.id, n: Array.isArray(data) ? data.length : (data.items || []).length || 0 };
      // a task found now was added to the overview's «Следующие шаги» (app/analysis_chain.sync_next_steps)
      const fresh = await fetch(`/api/meetings/${m.id}`).then(r => (r.ok ? r.json() : null)).catch(() => null);
      if (fresh && fresh.summaries) m.summaries = fresh.summaries;
    }
    if (key === 'chapters' && state.activeMeeting === m) renderChaptersBar();
  } catch (e) {
    showToast(`${anSectionInfo(key).label}: ${serverText(e.message)}`);
  } finally {
    state.anBusy.delete(busy);
    syncAnalysisMark();
    if (state.activeMeeting === m) {
      if (key === 'commitments' || key === 'protocol') await refreshCommitmentCount();  // the analysis in steps finds the tasks too
      renderSummaryPanel();
    }
  }
}

// The follow-up draft in the mail app: "Тема: …" becomes the subject, the rest the body
function openFollowupMail(md) {
  const text = String(md || '').replace(/\*\*|__|^#+\s*/gm, '').trim();
  const m = text.match(/^(?:Тема|Subject)\s*:\s*(.+)$/im);
  const subject = m ? m[1].trim() : (state.activeMeeting && state.activeMeeting.title) || '';
  const body = (m ? text.replace(m[0], '') : text).trim();
  openExternalMail(`mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body.slice(0, 1800))}`);
}

// The editor of the user's templates: name + what the summary should contain
function openTemplatesEditor() {
  document.getElementById('templates-editor')?.remove();
  let items = (state.summaryTemplates || []).map(x => ({ ...x }));
  const initial = JSON.stringify(items);
  const wrap = document.createElement('div');
  wrap.id = 'templates-editor';
  wrap.className = 'fixed inset-0 modal-backdrop z-[60] flex items-center justify-center p-4';
  wrap.setAttribute('role', 'dialog');
  wrap.setAttribute('aria-modal', 'true');
  const presets = TEMPLATE_PRESETS[state.uiLang === 'en' ? 'en' : 'ru'];
  const draw = () => {
    wrap.innerHTML = `<div class="w-full max-w-2xl max-h-[85vh] flex flex-col bg-apple-card border apple-border rounded-2xl shadow-2xl modal-card">
      <div class="px-5 pt-5 pb-3 border-b apple-border">
        <div class="text-sm font-semibold text-white">${escapeHtml(t('templatesTitle'))}</div>
        <p class="text-[11.5px] text-apple-secondary mt-1">${escapeHtml(t('templatesDesc'))}</p>
      </div>
      <div class="flex-1 overflow-y-auto px-5 py-3 space-y-3">
        ${items.map((x, i) => `<div class="p-3 rounded-xl bg-apple-sidebar border border-white/10 space-y-2">
          <div class="flex items-center gap-2">
            <input data-i="${i}" data-f="name" value="${escapeHtml(x.name)}" maxlength="60" placeholder="${escapeHtml(t('templateName'))}"
              class="flex-1 h-8 bg-apple-card border apple-border rounded-lg px-2.5 text-xs text-white focus:outline-none focus:border-apple-blue" />
            <button data-del="${i}" class="ui-btn ui-btn-subtle px-2 hover:text-apple-red" title="${escapeHtml(t('ctxDelete'))}">${SVG_ICONS.trash}</button>
          </div>
          <textarea data-i="${i}" data-f="prompt" rows="3" maxlength="4000" placeholder="${escapeHtml(t('templatePrompt'))}"
            class="w-full bg-apple-card border apple-border rounded-lg px-2.5 py-2 text-xs text-white focus:outline-none focus:border-apple-blue resize-y">${escapeHtml(x.prompt)}</textarea>
        </div>`).join('') || `<div class="py-6 text-center text-xs text-apple-tertiary">${escapeHtml(t('templatesEmpty'))}</div>`}
        <div class="flex flex-wrap items-center gap-1.5 pt-1">
          <span class="text-[11.5px] text-apple-secondary">${escapeHtml(t('templatesAddFrom'))}</span>
          ${presets.map((p, i) => `<button data-preset="${i}" class="ui-btn ui-btn-subtle h-7 text-[11.5px]">${escapeHtml(p.name)}</button>`).join('')}
          <button data-add="1" class="ui-btn ui-btn-subtle h-7 text-[11.5px]">+ ${escapeHtml(t('templateBlank'))}</button>
        </div>
      </div>
      <div class="px-5 py-3 border-t apple-border flex justify-end gap-2">
        <button data-a="no" class="ui-btn ui-btn-subtle">${escapeHtml(t('cancel'))}</button>
        <button data-a="save" class="ui-btn ui-btn-primary">${escapeHtml(t('save'))}</button>
      </div></div>`;
  };
  draw();
  wrap.addEventListener('input', e => {
    const el = e.target.closest('[data-f]');
    if (el) items[Number(el.dataset.i)][el.dataset.f] = el.value;
  });
  wrap.addEventListener('click', async e => {
    const b = e.target.closest('button');
    if (b && b.dataset.a === 'no') { wrap.remove(); return; }
    // A click beside the window is easy to make by accident: unsaved edits are not dropped without asking
    if (e.target === wrap) {
      if (JSON.stringify(items) === initial || await askConfirm(t('templatesDiscardConfirm'), true, t('templatesDiscard'))) wrap.remove();
      return;
    }
    if (!b) return;
    if (b.dataset.del !== undefined) { items.splice(Number(b.dataset.del), 1); draw(); }
    else if (b.dataset.preset !== undefined) { items.push({ ...presets[Number(b.dataset.preset)], id: '' }); draw(); }
    else if (b.dataset.add) { items.push({ id: '', name: '', prompt: '' }); draw(); }
    else if (b.dataset.a === 'save') {
      const res = await fetch('/api/summary-templates', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ templates: items }) });
      if (!res.ok) { showError((await readJson(res)).detail); return; }
      state.summaryTemplates = await readJson(res);
      renderTemplateTabs();
      wrap.remove();
    }
  });
  document.body.appendChild(wrap);
}

// --- Commitments (app/commitments.py): who promised what to whom, by when ---
// A task of a recording as a card: what to do first, then who (an avatar, as on the Tasks page), the
// due date as a chip coloured by how near it is, the moment in the recording and where the task came from
function commitmentRowHtml(c, withMeeting, hasMfu = false) {
  const done = c.status === 'done';
  // Where the task came from, as a tag at the same place on every card: MFU lit (the organizer's
  // follow-up), LLM outlined (the model found it in the talk), ✎ (added by hand)
  const srcKind = c.source === 'mfu' ? 'mfu' : c.source === 'manual' ? 'manual' : 'llm';
  const srcLabel = { mfu: 'MFU', llm: 'LLM', manual: '✎' }[srcKind];
  const srcTip = { mfu: 'mfuTaskTip', llm: 'srcLlmTip', manual: 'srcManualTip' }[srcKind];
  const src = `<span class="an-task-tag an-task-src-${srcKind}${srcKind === 'mfu' ? ' an-task-tag-on' : ''}" title="${escapeHtml(t(srcTip))}">${srcLabel}</span>`;
  const at = c.at != null ? `<button data-mid="${c.meeting_id}" data-at="${c.at}" data-click="openCommitmentPlace" data-click-args='[{"$": "el"}]' class="an-task-at" title="${escapeHtml(t('tkOpenAt'))}">▶ ${formatTime(c.at)}</button>` : '';
  // who and the due date open the same pickers as on the Tasks page: the people, the calendar
  const dueText = c.due_date ? tkDueText(c) : c.due || t('tkNoDue');
  const due = `<button class="tk-due ${c.due_date ? tkDueTone(c) : c.due ? '' : 'an-task-nodue'}" ${pageCall('click', 'openCardDue', [c.id, { $: 'event' }])} title="${escapeHtml(t('tkDueTitle'))}">${escapeHtml(dueText)}</button>`;
  const to = c.to_whom ? `<span class="an-task-to" title="${escapeHtml(t('anToTip'))}">${escapeHtml(t('anToCap'))} ${escapeHtml(c.to_whom)}</span>` : '';
  const where = withMeeting ? `<span class="an-task-where">${escapeHtml(c.meeting_title || '')} · ${escapeHtml(c.meeting_date || '')}</span>` : '';
  return `<div class="an-task${done ? ' an-task-done' : ''}">
      <input type="checkbox" ${done ? 'checked' : ''} data-cid="${c.id}" data-change="toggleCommitment" data-change-args='[{"$": "el"}]' class="tk-check" aria-label="${escapeHtml(t('tkDone'))}" />
      <div class="an-task-main">
        <div class="an-task-what">${escapeHtml(c.what)}</div>
        <div class="an-task-meta">
          <button class="an-task-who" ${pageCall('click', 'openCardAssign', [c.id, { $: 'event' }])} title="${escapeHtml(t('tkAssignTitle'))}" aria-haspopup="true"><span class="an-task-who-cap">${escapeHtml(t('anWhoCap'))}</span>${tkAvatar(c.who, c.who_kind, 20)}<span>${escapeHtml(tkWhoName(c))}</span></button>${to}${at}${where}
        </div>
      </div>
      <div class="an-task-side">${due}<div class="an-task-tags">${taskFeatureChipsHtml(c.meeting_id, withMeeting ? null : (state.activeMeeting || {}).features)}${src}</div></div>
    </div>`;
}

// The pickers of the Tasks page (tasks.js) over a recording's task card: the task list is loaded first
async function tkPickerFor(id, e, open) {
  e.stopPropagation();
  const anchor = e.currentTarget;
  if (!tkTask(id)) await loadTasks();
  if (tkTask(id)) open(id, { stopPropagation() {}, currentTarget: anchor });
}
function openCardAssign(id, e) { return tkPickerFor(id, e, openTaskAssign); }
function openCardDue(id, e) { return tkPickerFor(id, e, openTaskDue); }

async function renderCommitments(box) {
  const m = state.activeMeeting;
  box.innerHTML = `<div class="py-6 text-center text-xs text-apple-secondary animate-pulse">…</div>`;
  const items = await fetch(`/api/meetings/${m.id}/commitments`).then(r => r.json()).catch(() => []);
  if (state.activeMeeting !== m || state.activeSummaryTab !== 'commitments') return;
  setClearSummaryVisible(items.length > 0);
  if (!state.anCommit || state.anCommit.id !== m.id || state.anCommit.n !== items.length) {
    state.anCommit = { id: m.id, n: items.length };
    renderAnalysisNav();
    renderAnalysisHead();
  }
  box.innerHTML = anIsBusy('commitments') ? anMakingHtml()
    : items.length ? `<div class="an-tasks">${items.map(c => commitmentRowHtml(c, false, !!(m.mfu || '').trim())).join('')}</div>${commitmentExportBar(m.id)}`
    : anEmptyHtml('commitments');
  linkPeople(box, '.an-task-what');  // a person the task names opens their card
}

// Promises as tasks for another app: Markdown (Obsidian, Notion), Todoist's CSV, a table
function commitmentExportBar(meetingId) {
  const b = (fmt, label) => `<button data-click="exportCommitments" data-click-args='[${jsArg(fmt)}, ${jsArg(meetingId)}]' class="ui-btn ui-btn-subtle h-7 text-[11.5px]">${escapeHtml(label)}</button>`;
  return `<div class="flex flex-wrap items-center gap-1.5 pt-3">
      <span class="text-[11.5px] text-apple-tertiary mr-1">${escapeHtml(t('commitmentsExport'))}</span>
      ${b('md', 'Markdown')}${b('todoist', 'Todoist')}${b('csv', t('commitmentsTable'))}
    </div>`;
}

async function exportCommitments(fmt, meetingId) {
  const res = await fetch('/api/commitments/export', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fmt, meeting_id: meetingId, lang: state.uiLang === 'en' ? 'en' : 'ru' }),
  });
  const data = await readJson(res);
  if (!res.ok) { showError(data.detail); return; }
  if (data.ok) showToast(t('commitmentsSaved'), { label: t('modelReveal'), onClick: () => revealPath(data.path) });
}

async function toggleCommitment(input) {
  const res = await fetch(`/api/commitments/${input.dataset.cid}`, {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: input.checked ? 'done' : 'open' }),
  });
  if (!res.ok) { input.checked = !input.checked; showError((await readJson(res)).detail); return; }
  input.closest('.an-task')?.classList.toggle('an-task-done', input.checked);
  if (typeof refreshFeaturePage === 'function') refreshFeaturePage();
}

async function openCommitmentPlace(btn) {
  document.getElementById('open-commitments')?.remove();
  switchAppView('library');
  await selectMeetingAndSeek(Number(btn.dataset.mid), Number(btn.dataset.at));
}

// All open promises of the library, from the assistant's side panel
async function openOpenCommitments() {
  const items = await fetch('/api/commitments').then(r => r.json()).catch(() => []);
  document.getElementById('open-commitments')?.remove();
  const wrap = document.createElement('div');
  wrap.id = 'open-commitments';
  wrap.className = 'fixed inset-0 modal-backdrop z-[60] flex items-center justify-center p-4';
  wrap.setAttribute('role', 'dialog');
  wrap.setAttribute('aria-modal', 'true');
  wrap.innerHTML = `<div class="w-full max-w-2xl max-h-[85vh] flex flex-col bg-apple-card border apple-border rounded-2xl shadow-2xl modal-card">
      <div class="px-5 pt-5 pb-3 border-b apple-border flex items-center justify-between gap-3">
        <div><div class="text-sm font-semibold text-white">${escapeHtml(t('openCommitmentsBtn'))}</div>
          <p class="text-[11.5px] text-apple-secondary mt-1">${escapeHtml(t('openCommitmentsDesc'))}</p></div>
        <button data-a="close" class="dlg-x" title="${escapeHtml(t('tipCloseModal'))}" aria-label="${escapeHtml(t('tipCloseModal'))}">✕</button>
      </div>
      <div class="flex-1 overflow-y-auto px-5 py-2">${items.length ? `<div class="an-tasks">${items.map(c => commitmentRowHtml(c, true)).join('')}</div>` + commitmentExportBar(null)
        : `<div class="py-10 text-center text-xs text-apple-tertiary">${escapeHtml(t('commitmentsNoneOpen'))}</div>`}</div>
    </div>`;
  wrap.addEventListener('click', e => { if (e.target === wrap || e.target.closest('[data-a="close"]')) wrap.remove(); });
  document.body.appendChild(wrap);
}

// An analysis model is there: a local one downloaded in Ollama, or a cloud one with its key
// A press that needs the analysis model while there is none: the banner with its two ways is shown,
// scrolled to and lit for a moment instead of doing nothing
function flashNoAiBanner(id = 'an-noai') {
  const b = document.getElementById(id);
  if (!b) { showWarning(t('anNeedModel')); return; }
  b.classList.remove('hidden', 'an-noai-flash');
  void b.offsetWidth;
  b.classList.add('an-noai-flash');
  b.scrollIntoView({ block: 'nearest', behavior: scrollMotion() });
}

function aiAvailable() {
  const ollamaModels = ((state.lastOllama && state.lastOllama.models) || []).length;
  const st = state.llm;
  const cloud = st && st.consent && st.providers && st.providers[st.provider] && st.providers[st.provider].key && st.providers[st.provider].key.saved;
  return state.lastOllama === undefined || ollamaModels > 0 || !!cloud;  // not loaded yet: assume yes
}

// --- The organizer's meeting follow-up (MFU), pasted by hand: saved by its button, which also makes the
// tasks again (once per change, not per keystroke); every summary takes it in as the agreed text ---
function renderMfuEditor(box) {
  const m = state.activeMeeting;
  box.innerHTML = `<div class="space-y-2">
      <p class="text-[11.5px] text-apple-tertiary">${escapeHtml(t('mfuHint'))}</p>
      <textarea id="mfu-input" rows="9" placeholder="${escapeHtml(t('mfuPh'))}"
        class="w-full bg-apple-sidebar border apple-border rounded-xl px-4 py-3 text-[13px] leading-relaxed text-white placeholder-apple-tertiary focus:outline-none focus:border-apple-blue resize-y"></textarea>
      <div class="flex items-center gap-3">
        <button id="mfu-save" data-click="saveMfu" class="an-btn an-btn-primary">${escapeHtml(t('mfuSave'))}</button>
        <span id="mfu-status" class="text-[11px] text-apple-tertiary"></span>
      </div>
    </div>`;
  const ta = document.getElementById('mfu-input');
  ta.dataset.mid = String(m.id);
  // a text not saved yet stays with its recording while the page is open (leaving the tab lost it)
  state.mfuDrafts = state.mfuDrafts || {};
  ta.value = state.mfuDrafts[m.id] ?? (m.mfu || '');
  const status = () => {
    const changed = ta.value.trim() !== (m.mfu || '').trim();
    const long = ta.value.length > MFU_READ_CHARS;
    const st = document.getElementById('mfu-status');
    st.className = 'text-[11px] ' + (long ? 'text-apple-amber' : 'text-apple-tertiary');
    st.textContent = [changed ? t('mfuUnsaved') : '', long ? t('mfuTooLong').replace('{n}', () => MFU_READ_CHARS) : ''].filter(Boolean).join(' · ');
  };
  ta.oninput = () => {
    if (ta.value.trim() !== (m.mfu || '').trim()) state.mfuDrafts[m.id] = ta.value; else delete state.mfuDrafts[m.id];
    status();
  };
  status();
}

const MFU_READ_CHARS = 6000;  // what every summary reads of it (app/ollama_client.MFU_SUMMARY_CHARS)

async function saveMfu() {
  const ta = document.getElementById('mfu-input');
  const m = state.activeMeeting;
  if (!m || !ta || ta.dataset.mid !== String(m.id)) return;  // the editor of another recording
  const text = ta.value.trim();
  const st = document.getElementById('mfu-status');
  const res = await fetch(`/api/meetings/${m.id}/mfu`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) });
  if (!res.ok) { if (st) st.textContent = serverText((await readJson(res)).detail || t('errorGeneric')); return; }
  const changed = text !== (m.mfu || '').trim();
  m.mfu = text;
  if (state.mfuDrafts) delete state.mfuDrafts[m.id];
  setClearSummaryVisible(!!text);
  renderAnalysisNav();
  if (st) st.textContent = t('notesSaved');
  if (changed) refreshTasksAfterMfu(m);
}

// The tasks made again with the MFU (or without it, once cleared): the summaries use it the next time they are made
function refreshTasksAfterMfu(m) {
  if (!aiAvailable()) { showToast(t('mfuNoModel')); return; }
  showToast(t('mfuTasksUpdating'));
  createAnalysisSection('commitments');
}

// --- My notes of a recording: plain text, saved as it is typed; every summary takes it in ---
function renderMyNotesEditor(box) {
  const m = state.activeMeeting;
  box.innerHTML = `<div class="space-y-2">
      <p class="text-[11.5px] text-apple-tertiary">${escapeHtml(t('notesHint'))}</p>
      <textarea id="my-notes-input" rows="14" placeholder="${escapeHtml(t('notesPh'))}"
        class="w-full bg-apple-sidebar border apple-border rounded-xl px-4 py-3 text-[13px] leading-relaxed text-white placeholder-apple-tertiary focus:outline-none focus:border-apple-blue resize-y"></textarea>
      <div id="my-notes-status" class="text-[11px] text-apple-tertiary h-4"></div>
    </div>`;
  const ta = document.getElementById('my-notes-input');
  ta.value = m.user_notes || '';
  ta.oninput = () => {
    const id = m.id, text = ta.value;
    m.user_notes = text;
    setClearSummaryVisible(!!text.trim());
    clearTimeout(window._notesSaveTimer);
    document.getElementById('my-notes-status').textContent = '…';
    window._notesSaveTimer = setTimeout(async () => {
      const res = await fetch(`/api/meetings/${id}/notes`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ notes: text }) });
      const st = document.getElementById('my-notes-status');
      if (st) st.textContent = res.ok ? t('notesSaved') : ((await readJson(res)).detail || t('errorGeneric'));
    }, 600);
  };
}

// LLM output is derived from the recording's speech, so it is treated as untrusted HTML. No data-*
// attributes either: the page's event dispatcher (core.js) calls the function a data-click / data-error
// names — an image that fails to load would have run one without a click
// Only what Markdown makes: no class or id (a block styled to cover the window or look like the app's own
// button), no media, and links only to the web (a relative one or "//host" would take the window itself away)
const MARKDOWN_TAGS = ['p', 'br', 'hr', 'strong', 'b', 'em', 'i', 'del', 's', 'code', 'pre', 'blockquote', 'ul', 'ol', 'li',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'sup', 'sub'];
function sanitizedMarkdown(md) {
  const html = DOMPurify.sanitize(marked.parse(md || ''), {
    ALLOWED_TAGS: MARKDOWN_TAGS, ALLOWED_ATTR: ['href', 'title', 'start', 'align', 'colspan', 'rowspan'],
    ALLOWED_URI_REGEXP: /^https?:\/\//i, ALLOW_DATA_ATTR: false,
    // not addresses: DOMPurify would hold them to the URI rule above and drop them («3.» shown as «1.»)
    ADD_URI_SAFE_ATTR: ['start', 'align', 'colspan', 'rowspan'],
  });
  return html;
}

function renderMarkdownWithTimestamps(box, md, durationSec) {
  box.innerHTML = sanitizedMarkdown(md);
  linkifyTimestamps(box, Number(durationSec) || 0, (sec) => seekPlayer(sec));
  markUnverified(box);
}

// "[?]" (app/grounding.py): a point of a summary the transcript does not support
function markUnverified(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) if (walker.currentNode.nodeValue.includes('[?]')) nodes.push(walker.currentNode);
  for (const node of nodes) {
    const parts = node.nodeValue.split('[?]');
    const frag = document.createDocumentFragment();
    parts.forEach((p, i) => {
      if (p) frag.appendChild(document.createTextNode(p));
      if (i < parts.length - 1) {
        const b = document.createElement('span');
        b.className = 'ml-1 px-1.5 py-px rounded bg-apple-amber/15 text-apple-amber text-[11px] font-medium whitespace-nowrap align-middle';
        b.textContent = t('unverifiedBadge');
        b.title = t('tipUnverified');
        frag.appendChild(b);
        b.closest('li, p')?.classList.add('opacity-80');
      }
    });
    node.replaceWith(frag);
  }
}

// Time stamps in model answers come in many shapes: [03:14], [03:14-05:06], (1:02:03), "03:14 — …"
// at the start of a line, inside `code`. Each one becomes a button that seeks there. Text nodes are
// rewritten (never the HTML string), so attributes and entities are left alone. A bare "10:30" in
// the middle of a sentence is more likely a clock time and stays text, as does anything past the end
// of the recording.
const TS_RE = /([\[(])?(\d{1,2}):([0-5]\d)(?::([0-5]\d))?(?:(\s*[-–—]\s*)(\d{1,2}):([0-5]\d)(?::([0-5]\d))?)?([\])])?/g;

function tsSeconds(a, b, c) {
  return c !== undefined ? Number(a) * 3600 + Number(b) * 60 + Number(c) : Number(a) * 60 + Number(b);
}

function linkifyTimestamps(root, maxSec, onSeek) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) {
    const n = walker.currentNode;
    if (/\d:[0-5]\d/.test(n.nodeValue) && !n.parentElement.closest('button, a')) nodes.push(n);
  }
  const fits = (sec) => !maxSec || sec <= maxSec + 2;
  const makeBtn = (label, sec) => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = 'ts-link';
    b.textContent = label;
    b.title = t('tipSeekTimestamp');
    b.dataset.ts = String(sec);
    b.addEventListener('click', (e) => { e.preventDefault(); onSeek(sec); });
    return b;
  };
  for (const node of nodes) {
    const text = node.nodeValue;
    const frag = document.createDocumentFragment();
    let last = 0;
    let changed = false;
    TS_RE.lastIndex = 0;
    let m;
    while ((m = TS_RE.exec(text))) {
      const before = text[m.index - 1] || '';
      const after = text[m.index + m[0].length] || '';
      if (/[\d:.]/.test(before) || /\d/.test(after)) continue;  // part of a longer number or a date
      const range = m[6] !== undefined;
      const bracketed = !!(m[1] && m[9]);
      const atLineStart = !text.slice(0, m.index).trim() && !node.previousSibling;
      if (!(bracketed || range || atLineStart || m[4] !== undefined)) continue;
      const s1 = tsSeconds(m[2], m[3], m[4]);
      if (!fits(s1)) continue;
      const label1 = `${m[2]}:${m[3]}${m[4] !== undefined ? ':' + m[4] : ''}`;
      frag.append(text.slice(last, m.index), m[1] || '', makeBtn(label1, s1));
      if (range) {
        const label2 = `${m[6]}:${m[7]}${m[8] !== undefined ? ':' + m[8] : ''}`;
        const s2 = tsSeconds(m[6], m[7], m[8]);
        frag.append(m[5], fits(s2) ? makeBtn(label2, s2) : label2);
      }
      frag.append(m[9] || '');
      last = m.index + m[0].length;
      changed = true;
    }
    if (!changed) continue;
    frag.append(text.slice(last));
    node.replaceWith(frag);
  }
}

// The model for this request: "cloud" for the cloud model, otherwise an Ollama tag
function summaryModelChoice() {
  const value = document.getElementById('summary-llm-select')?.value || '';
  if (value === '__cloud') {
    const c = cloudLlmChoice();
    return { chosenModel: 'cloud', prettyModel: c ? c.label : 'Cloud' };
  }
  return { chosenModel: value || undefined, prettyModel: formatModelName(value || 'Ollama') };
}

function renderSeriesUi() {
  // "Since last time" is a section only for a recording of a series
  if (state.activeSummaryTab === 'since_last' && !(state.activeMeeting && state.activeMeeting.series_id)) state.activeSummaryTab = 'protocol';
  if (document.getElementById('an-nav')) renderSummaryPanel();
}

async function generateSummaryForActiveTab() {
  const key = state.activeSummaryTab === 'protocol' && anHasContent('protocol') ? 'protocol' : state.activeSummaryTab;
  await createAnalysisSection(key);
}

// A question about this recording: the answer is a section of its own («Ответ на вопрос»)
// (asked by the user: the field under every section took room; it is in the «⋯» menu)
async function runCustomQuestion() {
  const m = state.activeMeeting;
  if (!m) return;
  if (!aiAvailable()) { flashNoAiBanner(); return; }
  const prompt = ((await askText(t('anAskPh'), '')) || '').trim();
  if (!prompt) return;
  const { chosenModel } = summaryModelChoice();
  state.anQuestion = { id: m.id, text: prompt };
  state.anBusy = state.anBusy || new Set();
  state.anBusy.add(`${m.id}:custom`);
  syncAnalysisMark();
  state.activeSummaryTab = 'custom';  // the section shows while it is made
  renderSummaryPanel();
  try {
    const res = await fetch(`/api/meetings/${m.id}/summary`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ template: 'custom', custom_prompt: prompt, model: chosenModel, lang: state.uiLang }),
    });
    const data = await readJson(res);
    if (!res.ok) throw new Error(data.detail || t('errorGeneric'));
    m.summaries = data.summaries;
  } catch (e) {
    showError(serverText(e.message));
  } finally {
    state.anBusy.delete(`${m.id}:custom`);
    syncAnalysisMark();
    if (state.activeMeeting === m) { renderChaptersBar(); renderSummaryPanel(); }
  }
}

// The text of the open section (the overview: its summary and short summary)
function anSectionText(key) {
  const m = state.activeMeeting;
  if (!m) return '';
  const sums = m.summaries || {};
  if (key === 'mynotes') return m.user_notes || '';
  if (key === 'mfu') return m.mfu || '';
  if (key === 'protocol') return [sums.tldr, sums.protocol, sums.chapters].filter(x => (x || '').trim()).join('\n\n');
  return sums[key] || '';
}

function copySummaryText() {
  const text = anSectionText(state.activeSummaryTab).replaceAll('[?]', `(${t('unverifiedBadge')})`).trim();
  if (!text) return;
  navigator.clipboard.writeText(text);
  showToast(t('uiCopied'), null, 'success');
}

// --- Export ---
async function exportMeetingById(id, fmt, opts) {
  fmt = (fmt || 'txt').toLowerCase();
  try {
    const params = new URLSearchParams(opts && opts.lang ? { lang: opts.lang, variant: opts.variant || 'translated' } : {});
    // the options of the export menu (time stamps, names, without fillers) go with the files of that
    // menu; the other exports (another recording's context menu, a section of the analysis) take the defaults
    const xo = opts && opts.menu ? rpExportOptions() : { times: true, names: true, nofill: false };
    if (!xo.times) params.set('times', 'false');
    if (!xo.names) params.set('names', 'false');
    if (xo.nofill) params.set('nofill', 'true');
    const qs = params.toString() ? `?${params}` : '';
    const res = await fetch(`/api/meetings/${id}/export/${fmt}${qs}`);
    if (!res.ok) {
      showError(t('exportFailed'));
      return;
    }
    const blob = await res.blob();

    // Extract filename from Content-Disposition header with fallback
    const disp = res.headers.get('content-disposition') || '';
    let filename = '';
    const matchUtf8 = disp.match(/filename\*=UTF-8''([^;]+)/i);
    const matchPlain = disp.match(/filename="?([^";]+)"?/i);
    if (matchUtf8 && matchUtf8[1]) {
      try { filename = decodeURIComponent(matchUtf8[1]); } catch (e) { filename = matchUtf8[1]; }
    } else if (matchPlain && matchPlain[1]) {
      filename = matchPlain[1];
    }
    if (!filename) {
      const m = state.meetings.find(x => x.id === id) || state.activeMeeting;
      const title = (m && m.title) || 'meeting';
      const safeTitle = title.replace(/[^a-zA-Z0-9а-яА-ЯёЁ _-]/g, '_').trim() || 'meeting';
      filename = `${safeTitle}.${fmt}`;
    }

    // Method 1: File System Access API (Native Windows "Save As" file dialog in WebView2 / Chromium)
    if (typeof window.showSaveFilePicker === 'function') {
      const typeMap = {
        docx: { description: 'Word Document (*.docx)', accept: { 'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'] } },
        md:   { description: 'Markdown (*.md)', accept: { 'text/markdown': ['.md'] } },
        txt:  { description: 'Text File (*.txt)', accept: { 'text/plain': ['.txt'] } },
        srt:  { description: 'Subtitles (*.srt)', accept: { 'text/plain': ['.srt'] } },
        json: { description: 'JSON File (*.json)', accept: { 'application/json': ['.json'] } },
      };
      try {
        const handle = await window.showSaveFilePicker({
          suggestedName: filename,
          types: typeMap[fmt] ? [typeMap[fmt]] : undefined,
        });
        const writable = await handle.createWritable();
        await writable.write(blob);
        await writable.close();
        showToast(`${t('exportSavedTo')} ${handle.name}`);
        return;
      } catch (err) {
        // User cancelled the file picker dialog
        if (err && (err.name === 'AbortError' || err.code === 20)) {
          return;
        }
        console.warn('showSaveFilePicker fallback:', err);
      }
    }

    // Method 2: Native download trigger via Blob URL
    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = blobUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      document.body.removeChild(a);
      URL.revokeObjectURL(blobUrl);
    }, 4000);
    showToast(`${t('exportSavedTo')} ${filename}`);
  } catch (e) {
    console.error('Export error:', e);
    showError(t('exportFailed'));
  }
}

async function revealPath(path) {
  try {
    await fetch('/api/reveal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    });
  } catch (e) {}
}

async function refreshExportDirLabel() {
  const el = document.getElementById('set-export-dir');
  if (!el) return;
  try {
    const res = await fetch('/api/export-dir');
    const data = await readJson(res);
    el.textContent = data.folder || '';
    el.title = data.folder || '';
  } catch (e) {}
}

async function pickExportDir() {
  try {
    const res = await fetch('/api/export-dir/pick', { method: 'POST' });
    const data = await readJson(res);
    if (data && data.ok) refreshExportDirLabel();
  } catch (e) {}
}

// --- Folder for recordings made in the app ---
async function refreshRecordingsDirLabel() {
  try {
    const data = await (await fetch('/api/recordings-dir')).json();
    const el = document.getElementById('set-recordings-dir');
    el.textContent = data.folder || '';
    el.title = data.folder || '';
    document.getElementById('recdir-reset-btn').classList.toggle('hidden', !data.folder || data.folder === data.default);
    const uploads = state.system && state.system.paths && state.system.paths.uploads;
    document.getElementById('set-imports-dir').textContent = uploads ? t('recDirImports').replace('{dir}', () => uploads) : '';
  } catch (e) {}
}

async function pickRecordingsDir() {
  const res = await fetch('/api/recordings-dir/pick', { method: 'POST' });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) { showError(data.detail); return; }
  if (data.ok) await afterRecordingsDirChange();
}

async function resetRecordingsDir() {
  await fetch('/api/recordings-dir/reset', { method: 'POST' });
  await afterRecordingsDirChange();
}

async function afterRecordingsDirChange() {
  await loadSystemInfo();
  refreshRecordingsDirLabel();
  renderRecordSaveHint();
  showToast(t('recDirChanged'));
}

function openRecordingsDir() {
  const el = document.getElementById('set-recordings-dir');
  if (el && el.textContent) revealPath(el.textContent);
}

// --- Obsidian settings ---
const OBSIDIAN_TOGGLES = ['auto', 'generate', 'summary', 'tasks', 'chapters', 'transcript', 'feature_folders', 'more', 'stats'];

function fillObsidianSettings(s) {
  for (const k of OBSIDIAN_TOGGLES) {
    document.getElementById(`set-obsidian-${k}`).checked = (s[`obsidian_${k}`] || (k === 'auto' ? 'false' : 'true')) === 'true';
  }
  document.getElementById('set-obsidian-subfolder').value = s.obsidian_subfolder ?? 'Verbaliox';
  document.getElementById('set-obsidian-filename').value = s.obsidian_filename || '{date} {title}';
  document.getElementById('set-file-name-template').value = s.file_name_template || '{date} {title}';
  state.fileNameTemplate = s.file_name_template || '{date} {title}';
  if (libPrefs().names === 'file' && state.meetings) renderMeetingsSidebar();
  document.getElementById('set-date-folders').value = s.date_folders || 'off';
  updateFileNamePreview();
  const vault = document.getElementById('set-obsidian-vault');
  vault.textContent = s.obsidian_vault || t('obsVaultNone');
  vault.title = s.obsidian_vault || '';
  vault.dataset.path = s.obsidian_vault || '';
  updateObsidianPreview();
}

function obsidianSettingsPayload() {
  const out = {
    obsidian_subfolder: document.getElementById('set-obsidian-subfolder').value.trim(),
    obsidian_filename: document.getElementById('set-obsidian-filename').value.trim() || '{date} {title}',
    file_name_template: document.getElementById('set-file-name-template').value.trim() || '{date} {title}',
    date_folders: document.getElementById('set-date-folders').value || 'off',
  };
  for (const k of OBSIDIAN_TOGGLES) out[`obsidian_${k}`] = String(document.getElementById(`set-obsidian-${k}`).checked);
  return out;
}

function meetingDate(m) {
  const d = m ? new Date(String(m.recorded_at || m.created_at || '').replace(' ', 'T')) : new Date();
  return isNaN(d) ? new Date() : d;
}

// A recording's name by the file name template (as its files are named), without the extension
function formatFileName(m, tpl) {
  const dt = meetingDate(m);
  const p2 = n => String(n).padStart(2, '0');
  const ymd = `${dt.getFullYear()}-${p2(dt.getMonth() + 1)}-${p2(dt.getDate())}`;
  return (tpl || state.fileNameTemplate || '{date} {title}')
    .replaceAll('{date}', ymd).replaceAll('{time}', `${p2(dt.getHours())}-${p2(dt.getMinutes())}`)
    .replaceAll('{title}', (m && m.title) || t('fileNameExampleTitle')).replaceAll('{lang}', ((m && m.language) || 'ru').toUpperCase())
    .replace(/[<>:"/\\|?*]/g, '').replace(/\s+/g, ' ').trim();
}

// Settings -> Export: tokens to insert and an example of the folder and file name
const FILE_NAME_TOKENS = ['{date}', '{time}', '{title}', '{lang}'];

function updateFileNamePreview() {
  const input = document.getElementById('set-file-name-template');
  const tokens = document.getElementById('file-name-tokens');
  if (tokens && !tokens.childElementCount) {
    tokens.innerHTML = FILE_NAME_TOKENS.map(tk => `<button type="button" data-tk="${tk}" class="ui-btn ui-btn-subtle h-6 !px-2 text-[11px] font-mono">${tk}</button>`).join('');
    tokens.onclick = e => {
      const b = e.target.closest('[data-tk]');
      if (!b) return;
      const pos = input.selectionStart ?? input.value.length;
      input.value = input.value.slice(0, pos) + b.dataset.tk + input.value.slice(input.selectionEnd ?? pos);
      input.focus();
      updateFileNamePreview();
    };
  }
  const m = state.activeMeeting;
  const name = formatFileName(m, input.value.trim());
  const dt = meetingDate(m);
  const p2 = n => String(n).padStart(2, '0');
  const ymd = `${dt.getFullYear()}-${p2(dt.getMonth() + 1)}-${p2(dt.getDate())}`;
  const mode = document.getElementById('set-date-folders').value;
  const folder = { off: '', day: ymd, month: ymd.slice(0, 7), year_month: `${ymd.slice(0, 4)}\\${ymd.slice(0, 7)}` }[mode] || '';
  document.getElementById('file-name-preview').textContent = `${t('fileNameExample')}: ${folder ? folder + '\\' : ''}${name}.md`;
}

function updateObsidianPreview() {
  const vault = document.getElementById('set-obsidian-vault').dataset.path || '';
  const sub = document.getElementById('set-obsidian-subfolder').value.trim();
  const tpl = document.getElementById('set-obsidian-filename').value.trim() || '{date} {title}';
  const m = state.activeMeeting;
  const d = new Date();
  const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  // the feature of the open recording, or an example one: the folder and {feature} show what they do
  const f = m && (m.features || []).length && typeof featureById === 'function' ? featureById(m.features[0]) : null;
  const feature = f ? f.name : t('obsExampleFeature');
  const name = tpl.replace('{date}', () => date).replace('{time}', () => `${String(d.getHours()).padStart(2, '0')}-${String(d.getMinutes()).padStart(2, '0')}`)
    .replace('{title}', () => (m && m.title) || t('obsExampleTitle')).replace('{lang}', () => ((m && m.language) || 'ru').toUpperCase())
    .replace('{feature}', () => feature);
  const byFeature = document.getElementById('set-obsidian-feature_folders')?.checked;
  const sep = vault.includes('/') && !vault.includes('\\') ? '/' : '\\';
  document.getElementById('obs-preview').textContent = vault
    ? `${t('obsPreview')}: ${[vault, sub, byFeature ? feature : '', name + '.md'].filter(Boolean).join(sep)}`
    : t('obsPreviewNoVault');
}

// «Реэкспорт всех расшифровок»: every transcribed recording's note, or only those without one, in the
// background; «Дополнить» first has the analysis model make what a note shows and its analysis lacks
// (the overview, tasks, chapters), in the queue. The count follows
function obsidianExportAll(e) {
  e?.stopPropagation?.();
  tkOpenPop(`<div class="tk-pop-cap">${escapeHtml(t('obsReexportTitle'))}</div>
    <label class="obs-rx-row"><input type="radio" name="obs-rx-scope" value="all" checked><span>${escapeHtml(t('obsReexportAll'))}</span></label>
    <label class="obs-rx-row"><input type="radio" name="obs-rx-scope" value="missing"><span>${escapeHtml(t('obsReexportMissing'))}</span></label>
    <label class="obs-rx-row obs-rx-sep"><input type="checkbox" id="obs-rx-complete" checked><span>${escapeHtml(t('obsReexportComplete'))}
      <span class="obs-rx-hint">${escapeHtml(t('obsReexportCompleteHint'))}</span></span></label>
    <div class="obs-rx-go"><button class="tk-btn tk-btn-primary tk-btn-sm" ${pageCall('click', 'obsidianExportAllStart')}>${escapeHtml(t('obsReexportStart'))}</button></div>`,
  document.getElementById('obs-export-all'), 330);
}

async function obsidianExportAllStart() {
  const missing = document.querySelector('input[name="obs-rx-scope"]:checked')?.value === 'missing';
  const complete = !!document.getElementById('obs-rx-complete')?.checked;
  tkClosePop();
  const res = await fetch(`/api/obsidian/export-all?missing_only=${missing}&complete=${complete}`, { method: 'POST' }).catch(() => null);
  const data = res ? await readJson(res) : null;
  if (!res || !res.ok) { showError(res ? errorText(data, res) : t('errorGeneric')); return; }
  obsidianExportAllWatch(data);
}

async function obsidianExportAllWatch(st) {
  const box = document.getElementById('obs-export-all-status');
  const btn = document.getElementById('obs-export-all');
  st = st || await fetch('/api/obsidian/export-all').then(r => (r.ok ? r.json() : null)).catch(() => null);
  if (!box || !st) return;
  if (btn) btn.disabled = !!st.active;
  box.textContent = st.active ? t('obsExportAllRunning').replace('{done}', () => st.done).replace('{total}', () => st.total)
    : st.total ? t('obsExportAllDone').replace('{n}', () => st.total - st.failed - (st.kept || 0) - (st.queued || 0))
      + (st.queued ? ` · ${t('obsExportAllQueued').replace('{n}', () => st.queued)}` : '')
      + (st.kept ? ` · ${t('obsExportAllKept').replace('{n}', () => st.kept)}` : '')
      + (st.failed ? ` · ${t('obsExportAllFailed').replace('{n}', () => st.failed)}` : '') : '';
  if (st.active) setTimeout(() => obsidianExportAllWatch(), 1500);
}

async function refreshObsidianStatus() {
  try {
    const st = await (await fetch('/api/obsidian/status')).json();
    const pill = document.getElementById('obs-pill');
    const [text, cls] = !st.vault ? [t('obsPillNone'), 'bg-white/5 text-apple-secondary']
      : !st.exists ? [t('obsPillMissing'), 'bg-apple-red/15 text-apple-red']
      : st.is_vault ? [t('obsPillVault'), 'bg-apple-green/15 text-apple-green']
      : [t('obsPillFolder'), 'bg-apple-amber/15 text-apple-amber'];
    pill.textContent = text;
    pill.className = `text-[11px] font-mono px-2.5 py-0.5 rounded-full shrink-0 ${cls}`;
    pill.title = st.is_vault || !st.vault ? '' : t('tipObsNotVault');
  } catch (e) {}
}

async function pickObsidianVault() {
  const res = await fetch('/api/obsidian/pick-vault', { method: 'POST' });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || !data.ok) return;
  if (state.system && state.system.settings) state.system.settings.obsidian_vault = data.folder;
  const vault = document.getElementById('set-obsidian-vault');
  vault.textContent = data.folder;
  vault.title = data.folder;
  vault.dataset.path = data.folder;
  updateObsidianPreview();
  refreshObsidianStatus();
  if (!data.is_vault) showWarning(t('tipObsNotVault'));
}

async function openObsidianFolder() {
  try {
    const st = await (await fetch('/api/obsidian/status')).json();
    if (st.folder || st.vault) revealPath(st.exists ? st.vault : '');
  } catch (e) {}
}

// Every model out of memory: the app's and every model Ollama holds, also one loaded before this start;
// the server waits until Ollama has really let them go and stops its runner if it does not
// A switch: while a recording is processed or captions run, it asks and then stops them first
async function unloadAllModelsNow(stop = false) {
  stop = stop === true;  // a click passes its event: only an explicit true stops the work
  if (vram.busy) return;
  vram.busy = true;
  if (vram.data) renderVram(vram.data);
  showToast(t('idleUnloading'));
  let again = false;
  try {
    const res = await fetch(`/api/vram/unload-all${stop ? '?stop=true' : ''}`, { method: 'POST' });
    const data = await res.json().catch(() => ({}));
    if (res.status === 409 && !stop) again = true;  // asked below, once the button is free again
    else if (!res.ok) showError(data.detail);
    else {
      renderVram(data);
      if ((data.left || []).length) showError(t('idleUnloadLeft').replace('{names}', () => data.left.map(formatModelName).join(', ')));
      else showToast((data.released || []).length ? t('idleUnloadedNow') : t('idleNothingLoaded'), null, 'success');
    }
  } catch (e) {
    showError('');
  } finally {
    vram.busy = false;
    scheduleVramRefresh(300);
  }
  if (again && await askConfirm(t('unloadStopAsk'), true, t('unloadStopOk'))) unloadAllModelsNow(true);
}

function openExportDir() {
  const el = document.getElementById('set-export-dir');
  if (el && el.textContent) revealPath(el.textContent);
}

// The language model the first-run wizard picks, downloaded from its card
function pullFirstRunLlm() {
  pullOllamaModel(firstRunPicks(state.system || {}, state.uiLang).llm, true);
}

function escapeHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// A value as JSON for the arguments of an event (core.js PAGE_EVENTS): data-click="f" data-click-args='[${jsArg(name)}]'.
// Any text is safe there (quotes included); a value never goes in without it, or Number() for numbers.
function jsArg(value) {
  return escapeHtml(JSON.stringify(value ?? null));
}

// --- "Details" tab: where the file is, what it is, and what was done with it ---
async function loadMeetingInfo() {
  const box = document.getElementById('info-content');
  const m = state.activeMeeting;
  if (!m) return;
  const id = m.id;
  box.innerHTML = `<div class="py-10 text-center text-xs text-apple-secondary animate-pulse">…</div>`;
  try {
    const res = await fetch(`/api/meetings/${id}/info`);
    const info = await readJson(res);
    if (!res.ok) throw new Error(info.detail || t('errorGeneric'));
    if (!state.activeMeeting || state.activeMeeting.id !== id) return;
    renderMeetingInfo(info);
  } catch (e) {
    // Same check as on success: the user may have opened another recording meanwhile
    if (!state.activeMeeting || state.activeMeeting.id !== id) return;
    box.innerHTML = `<div class="py-6 text-xs text-apple-red">${escapeHtml(e.message)}</div>`;
  }
}

function formatDateTime(s) {
  const m = String(s || '').match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/);
  if (!m) return s ? String(s) : '—';
  try {
    return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]))
      .toLocaleString(state.uiLang === 'en' ? 'en-GB' : 'ru-RU', { day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch (e) {
    return String(s);
  }
}

function copyText(text) {
  navigator.clipboard.writeText(text).then(() => showToast(t('copied'), null, 'success'), () => {});
}

// «Сведения» (stage 5): cards «Файл», «Расшифровка», «Анализ», «Хранение» as rows «key — value», each with its
// actions under a line. Only what the program already does: reveal and copy the path, transcribe again (the dialog
// with the model, the language and the speakers), split by speakers again, make the analysis again, move to a folder
function renderMeetingInfo(info) {
  const box = document.getElementById('info-content');
  const m = state.activeMeeting || {};
  const row = (label, value, opts = {}) => value == null || value === '' ? '' : `
    <div class="kv"><span class="kv-k">${escapeHtml(label)}</span>
      <span class="kv-v${opts.mono ? ' kv-mono' : ''}">${opts.html ? value : escapeHtml(String(value))}</span></div>`;
  const btn = (fn, args, label, title = '') => `<button class="ui-btn ui-btn-subtle h-7 text-[12px]" data-click="${fn}" data-click-args='${jsArg(args)}'${title ? ` title="${escapeHtml(title)}"` : ''}>${fn === 'recRegenFromInfo' ? AI_MARK + ' ' : ''}${escapeHtml(label)}</button>`;
  const card = (key, icon, title, rows, actions = '') => `<section class="scard" data-info="${key}">
      <h3 class="sc-h"><span class="sc-ic" aria-hidden="true">${recCardIcon(icon)}</span><span class="sc-name">${escapeHtml(title)}</span></h3>
      <div class="kv-rows">${rows || `<div class="sc-quiet">—</div>`}</div>
      ${actions ? `<div class="kv-acts">${actions}</div>` : ''}
    </section>`;
  const media = info.media || {};
  const probe = info.probe || {};
  const v = probe.video;
  const a = probe.audio;
  const folderPath = (info.folders || []).map(f => f.system_key ? t(`folderSystem_${f.system_key}`) : f.name).join(' / ');
  const done = (info.segments || 0) > 0;

  const file = card('file', 'note', t('infoFile'),
    row(t('infoName'), media.name || info.filename)
    + row(t('infoLocation'), media.path, { mono: true })
    + (media.exists === false ? row(t('infoState'), `<span class="text-apple-red">${escapeHtml(t('infoMissing'))}</span>`, { html: true }) : '')
    + row(t('infoSize'), media.size != null ? formatBytes(media.size) : '')
    + row(t('infoDuration'), formatTime(probe.duration || info.duration))
    + row(t('infoContainer'), probe.container)
    + (v ? row(t('infoVideo'), [v.codec && v.codec.toUpperCase(), v.width && v.height ? `${v.width}×${v.height}` : '', v.fps ? `${v.fps} fps` : ''].filter(Boolean).join(' · ')) : '')
    + (a ? row(t('infoAudio'), [a.codec && a.codec.toUpperCase(), a.sample_rate ? `${(a.sample_rate / 1000).toFixed(1)} kHz` : '', a.layout || (a.channels ? `${a.channels} ch` : ''), a.bitrate_kbps ? `${a.bitrate_kbps} kbps` : ''].filter(Boolean).join(' · ')) : '')
    + row(t('infoBitrate'), probe.bitrate_kbps ? `${probe.bitrate_kbps} kbps` : '')
    + row(t('infoSourceLabel'), t(`infoSource_${info.source || 'import'}`) + (info.owns_media ? '' : ` · ${t('infoInPlace')}`)),
    media.exists && media.path ? btn('revealPath', [media.path], t('showInFolder')) + btn('copyText', [media.path], t('copyPath')) : '');

  const transcript = card('transcript', 'doc', t('infoTranscriptCard'),
    row(t('infoStatus'), tMaybe(`status_${info.status}`) || info.status)
    + row(t('infoModel'), formatModelName(info.transcript_model || info.model_name))
    + row(t('infoLanguage'), !info.language ? '' : info.language === 'auto' ? t('studioSpeechAuto')
      : `${langName(info.language)} (${String(info.language).toUpperCase()})`)
    + row(t('infoCounts'), t('infoCountsValue').replace('{spk}', () => info.speakers).replace('{seg}', () => info.segments).replace('{words}', () => info.words))
    + row(t('infoTranslations'), (info.translations || []).map(c => langName(c)).join(', '))
    + row(t('infoProcessedAt'), info.completed_at ? formatDateTime(info.completed_at) : '')
    + row(t('infoWorkAudio'), info.audio && info.audio.exists ? `${info.audio.path} · ${formatBytes(info.audio.size)}` : '', { mono: true }),
    btn('recReconfigure', [], `↻ ${t('recRedo')}`, t('recRedoTip'))
    + (done ? btn('openResplitDialog', [], t('infoResplit'), t('spResplitTip')) : ''));

  const analyses = (info.summaries || []).filter(k => k !== 'error')
    .map(k => tMaybe(`summaryName_${k}`) || ((state.summaryTemplates || []).find(x => `tpl:${x.id}` === k || x.id === k) || {}).name || k);
  const analysis = card('analysis', 'sum', t('infoAnalysisCard'),
    row(t('infoAnalyses'), analyses.join(', ') || t('infoNoAnalysis'))
    + row(t('recModel'), summaryModelChoice().prettyModel),
    done ? btn('recRegenFromInfo', [], t('recRegenAnalysisDlg'), t('tipGenerateSummary')) : '');

  const dubs = (info.dubs || []).filter(Boolean);
  const storage = card('storage', 'folder', t('infoStorageCard'),
    row(t('infoFolder'), folderPath || t('infoNoFolder'))
    + row(t('infoRecordedAt'), formatDateTime(info.recorded_at))
    + row(t('infoAddedAt'), formatDateTime(info.created_at))
    + row(t('infoFileModified'), media.modified ? formatDateTime(media.modified) : '')
    + dubs.map(d => row(t('infoDubFile'), `${d.path}${d.size != null ? ' · ' + formatBytes(d.size) : ''}`, { mono: true })).join('')
    + (info.obsidian ? row('Obsidian', info.obsidian.path + (info.obsidian.exists ? '' : ` (${t('infoMissing')})`), { mono: true }) : ''),
    (m.id === info.id ? `<button class="ui-btn ui-btn-subtle h-7 text-[12px]" data-click="recMoveFromInfo" data-click-args='[{"$": "el"}]'>${escapeHtml(t('infoMoveFolder'))}</button>` : '')
    + (info.obsidian && info.obsidian.exists ? btn('revealPath', [info.obsidian.path], `Obsidian: ${t('showInFolder')}`) : ''));

  let html = `<div class="info-grid">${file}${transcript}${analysis}${storage}</div>`;
  if ((info.pending_exports || []).length) {
    html += `<div class="rounded-xl border border-apple-amber/40 bg-apple-amber/10 px-4 py-3 mt-3 text-xs text-apple-amber flex items-center justify-between gap-3">
      <span>${escapeHtml(t('infoPendingExports').replace('{n}', () => info.pending_exports.length))}</span>
      <button data-click="cancelPendingExports" data-click-args='[${info.id}]' class="ui-btn ui-btn-subtle h-6 px-2 text-[11.5px]">${escapeHtml(t('cancel'))}</button>
    </div>`;
  }
  box.innerHTML = html;
}

async function cancelPendingExports(id) {
  const res = await fetch(`/api/meetings/${id}/pending-exports`, { method: 'DELETE' }).catch(() => null);
  if (!res || !res.ok) { showError(errorText(res ? await readJson(res) : null, res)); return; }
  loadMeetingInfo();
}

// --- Text context menu ---
// The app window has no browser menu of its own, so right-click on text opens this one: in a text
// field it edits (cut, copy, paste, select all); on selected text it copies the text and offers what
// the app can do with it (play from there, search, ask the assistant, add to the dictionary).
const TEXT_AREAS = '#studio-captions, #transcript-container, #summary-content, #ask-thread, #info-content, .markdown-body';

function closeTextMenu() {
  const menu = document.getElementById('text-menu');
  if (menu && !menu.classList.contains('is-leaving')) { menu.id = ''; removeWithExit(menu); }
}

function textMenuItems(e) {
  const el = e.target;
  if (isTypingTarget(el) && el.tagName !== 'SELECT') {
    const field = el;
    const ro = field.readOnly || field.disabled;
    const sel = field.isContentEditable ? String(window.getSelection()) : field.value.slice(field.selectionStart ?? 0, field.selectionEnd ?? 0);
    return [
      { label: t('ctxCut'), key: 'Ctrl+X', disabled: ro || !sel, run: () => { field.focus(); document.execCommand('cut'); } },
      { label: t('ctxCopy'), key: 'Ctrl+C', disabled: !sel, run: () => copyPlain(sel) },
      { label: t('ctxPaste'), key: 'Ctrl+V', disabled: ro, run: () => pasteInto(field) },
      { sep: true },
      { label: t('ctxSelectAll'), key: 'Ctrl+A', run: () => { field.focus(); field.select ? field.select() : document.execCommand('selectAll'); } },
    ];
  }
  const area = el.closest && el.closest(TEXT_AREAS);
  const selection = window.getSelection();
  const text = String(selection || '').replace(/\s+/g, ' ').trim();
  const inSel = text && selection.rangeCount && area && area.contains(selection.getRangeAt(0).commonAncestorContainer);
  if (!area && !text) return null;
  const items = [];
  const segRow = (inSel ? nodeEl(selection.anchorNode) : el)?.closest?.('.segment-row');
  const inStudio = area && area.id === 'studio-captions';
  if (text && (inSel || !area)) {
    items.push({ label: t('ctxCopy'), key: 'Ctrl+C', run: () => copyPlain(String(selection)) });
    if (segRow) {
      const start = selectionStartTime(selection) ?? Number(segRow.dataset.start);
      items.push({ label: t('ctxCopyWithTime'), run: () => copyPlain(`[${formatTime(start)}] ${text}`) });
      items.push({ sep: true });
      items.push({ label: t('ctxPlayFromHere'), key: formatTime(start), run: () => seekPlayer(start) });
    }
    items.push({ sep: true });
    const short = text.length <= 80;
    if (state.activeMeeting && short && document.getElementById('library-view') && !document.getElementById('library-view').classList.contains('hidden')) {
      items.push({ label: t('ctxFindHere'), run: () => findInTranscript(text) });
    }
    if (short) items.push({ label: t('ctxFindAll'), run: () => findEverywhere(text) });
    items.push({ label: t('ctxAskAssistant'), run: () => askAbout(text) });
    if (text.length <= 60 && text.split(' ').length <= 5) {
      // a word of the analysis written wrong: put right in the analysis, and the dictionary learns it
      if (area && area.closest('#summary-content') && state.activeMeeting && !nodeEl(selection.anchorNode)?.closest?.('.an-edit, textarea, input')) {
        const card = nodeEl(selection.anchorNode)?.closest?.('[data-md]');
        items.push({ label: t('ctxFixInAnalysis').replace('{word}', () => text), run: () => openWordFixDialog(text, card ? card.dataset.md : null) });
      }
      items.push({ label: t('ctxAddToDictionary'), run: () => addToDictionary(text) });
    }
  } else if (segRow) {
    // A word under the cursor: it can go to the dictionary as it is
    const wordEl = el.closest && el.closest('.word-token');
    const word = wordEl ? wordEl.textContent.replace(/^[\s.,!?;:«»"'()]+|[\s.,!?;:«»"'()]+$/g, '') : '';
    if (word) {
      items.push({ label: t('ctxAddWordToDictionary').replace('{word}', () => word), run: () => addToDictionary(word) });
      items.push({ label: t('ctxPlayFromHere'), key: formatTime(Number(wordEl.dataset.start)), run: () => seekPlayer(Number(wordEl.dataset.start)) });
      items.push({ sep: true });
    }
    const segText = segRow.querySelector('[id^="seg-text-"]')?.innerText.replace(/\s+/g, ' ').trim() || '';
    const start = Number(segRow.dataset.start);
    items.push({ label: t('ctxCopyLine'), run: () => copyPlain(segText) });
    items.push({ label: t('ctxCopyWithTime'), run: () => copyPlain(`[${formatTime(start)}] ${segText}`) });
    items.push({ label: t('ctxPlayFromHere'), key: formatTime(start), run: () => seekPlayer(start) });
    // a phrase of a block: its own text, its person, joined to the one before
    const segId = Number(String(segRow.id || '').replace(/^seg-/, ''));
    const m = state.activeMeeting;
    const segs = (m && m.segments) || [];
    const at = segs.findIndex(x => x.id === segId);
    if (at >= 0) {
      items.push({ sep: true });
      items.push({ label: t('ctxEditPhrase'), run: () => openInlineSegmentEditor(segId) });
      const others = Object.entries(m.speakers || {}).filter(([k]) => k !== segs[at].speaker);
      if (others.length) {
        items.push({ label: t('ctxPhraseSpeaker'), run: () => openTextMenuAt(others.map(([k, sp]) => ({ label: sp.name || k, run: () => changeSegmentSpeaker(segId, k) })), e.clientX, e.clientY) });
      }
      if (at > 0) items.push({ label: t('ctxMergePhrase'), run: () => mergeSegmentWithPrevious(segId) });
    }
  } else if (inStudio) {
    const row = el.closest('.cap-row');
    const line = row ? capRowText(row) : '';
    if (line) items.push({ label: t('ctxCopyLine'), run: () => copyPlain(line) });
  }
  if (area) {
    items.push({ sep: true });
    if (inStudio) items.push({ label: t('ctxCopyAllCaptions'), disabled: !capView.rows.size, run: () => copyPlain(studioCaptionsText()) });
    items.push({ label: t('ctxSelectAll'), key: 'Ctrl+A', run: () => selectAllIn(inStudio ? document.getElementById('studio-cap-rows') : area) });
  }
  return items;
}

function nodeEl(node) {
  return node && (node.nodeType === 1 ? node : node.parentElement);
}

// The time of the first selected word, when the words carry their timings
function selectionStartTime(selection) {
  const range = selection.getRangeAt(0);
  const startEl = nodeEl(range.startContainer);
  const word = startEl?.closest('.word-token');
  if (word) return Number(word.dataset.start);
  const row = startEl?.closest('.segment-row');
  const first = row && [...row.querySelectorAll('.word-token')].find(w => range.intersectsNode(w));
  return first ? Number(first.dataset.start) : null;
}

function capRowText(row) {
  const o = row.querySelector('.cap-orig')?.textContent.trim() || '';
  const tr = row.querySelector('.cap-tr')?.textContent.trim() || '';
  return tr && tr !== o ? `${o}\n${tr}` : o;
}

function studioCaptionsText() {
  return [...capView.rows.values()].filter(r => r.key !== capView.draftKey).map(r => capRowText(r.el)).filter(Boolean).join('\n\n');
}

function selectAllIn(el) {
  const range = document.createRange();
  range.selectNodeContents(el);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
}

function copyPlain(text) {
  if (text) copyText(text);
}

async function pasteInto(field) {
  field.focus();
  try {
    const text = await navigator.clipboard.readText();
    if (field.isContentEditable) {
      document.execCommand('insertText', false, text);
    } else {
      field.setRangeText(text, field.selectionStart, field.selectionEnd, 'end');
      field.dispatchEvent(new Event('input', { bubbles: true }));
    }
  } catch (e) {
    showWarning(t('ctxPasteBlocked'));
  }
}

function findInTranscript(text) {
  focusTranscriptSearch();
  const input = document.getElementById('transcript-search');
  input.value = text;
  renderTranscript();
}

function findEverywhere(text) {
  switchAppView('library');
  const input = document.getElementById('global-search-input');
  input.value = text;
  input.focus();
  handleGlobalSidebarSearch(text);
}

function askAbout(text) {
  const inLibrary = !document.getElementById('library-view')?.classList.contains('hidden');
  const scope = inLibrary && state.activeMeeting ? { type: 'meeting', id: state.activeMeeting.id } : null;
  openLibraryAsk(t('ctxAskTemplate').replace('{text}', () => text.length > 300 ? text.slice(0, 300) + '…' : text), scope);
}

async function addToDictionary(text) {
  const term = text.replace(/^[\s.,!?;:«»"'()]+|[\s.,!?;:«»"'()]+$/g, '');
  if (!term) return;
  const res = await fetch('/api/dictionary', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ term, category: 'Термин' }),
  });
  if (res.ok) {
    showToast(t('ctxAddedToDictionary').replace('{term}', () => term));
    loadDictionary();
  }
}

// --- Hand corrections of the analysis (app/analysis_edits.py) ---
// A section a person may edit: Markdown made by the model (the chapters are a list with times, the notes,
// MFU and tasks have editors of their own)
const AN_NOT_EDITABLE = new Set(['chapters', 'mynotes', 'mfu', 'commitments', 'error']);
function anEditable(key) {
  const m = state.activeMeeting;
  const v = m && (m.summaries || {})[key];
  return !AN_NOT_EDITABLE.has(key) && typeof v === 'string' && !!v.trim();
}

function anTrimWord(text) {
  return String(text || '').replace(/\s+/g, ' ').replace(/^[\s.,!?;:«»"'()*_#\-]+|[\s.,!?;:«»"'()*_#\-]+$/g, '');
}

// «Исправить …»: the right spelling for every section of this recording; the dictionary remembers it
function openWordFixDialog(selected, section) {
  const wrong = anTrimWord(selected);
  const m = state.activeMeeting;
  if (!wrong || !m) return;
  const wrap = document.createElement('div');
  wrap.className = 'fixed inset-0 modal-backdrop z-[70] flex items-center justify-center p-4';
  wrap.setAttribute('role', 'dialog');
  wrap.setAttribute('aria-modal', 'true');
  wrap.innerHTML = `<form class="w-full max-w-md bg-apple-card border apple-border rounded-2xl shadow-2xl p-5 space-y-4 modal-card">
      <div class="text-sm font-semibold text-white">${escapeHtml(t('fixWordTitle'))}</div>
      <div class="space-y-1">
        <div class="text-xs text-apple-secondary">${escapeHtml(t('fixWordWas'))}</div>
        <div class="text-sm text-white break-words"><s class="opacity-70">${escapeHtml(wrong)}</s></div>
      </div>
      <label class="block space-y-1">
        <span class="block text-xs text-apple-secondary">${escapeHtml(t('fixWordRight'))}</span>
        <input type="text" name="right" class="w-full h-9 bg-apple-sidebar border apple-border rounded-lg px-3 text-sm text-white focus:outline-none focus:border-apple-blue" />
      </label>
      <label class="flex items-start gap-2 text-xs text-apple-label"><input type="checkbox" name="all" checked class="mt-0.5">
        <span>${escapeHtml(t('fixWordAll'))}</span></label>
      <label class="flex items-start gap-2 text-xs text-apple-label"><input type="checkbox" name="learn" checked class="mt-0.5">
        <span><span>${escapeHtml(t('fixWordLearn'))}</span><span class="block text-apple-secondary mt-0.5" data-hint></span></span></label>
      <div class="flex justify-end gap-2">
        <button type="button" data-a="no" class="ui-btn ui-btn-subtle">${escapeHtml(t('cancel'))}</button>
        <button type="submit" class="ui-btn ui-btn-primary">${escapeHtml(t('fixWordOk'))}</button>
      </div></form>`;
  const form = wrap.querySelector('form');
  const input = form.elements.right;
  const hint = wrap.querySelector('[data-hint]');
  const learnBox = form.elements.learn;
  const tooLong = wrong.split(' ').length > 4;
  if (tooLong) { learnBox.checked = false; learnBox.disabled = true; }
  const sayHint = () => {
    const right = anTrimWord(input.value);
    hint.textContent = tooLong ? t('fixWordLong') : right && right !== wrong
      ? t('fixWordHint').replace('{wrong}', () => wrong).replace('{right}', () => right) : '';
  };
  input.value = wrong;
  input.addEventListener('input', sayHint);
  const done = () => { removeWithExit(wrap); document.removeEventListener('keydown', onKey, true); };
  const onKey = e => { if (e.key === 'Escape') { e.stopPropagation(); done(); } };
  wrap.addEventListener('click', e => { if (e.target === wrap || e.target.closest('[data-a="no"]')) done(); });
  form.addEventListener('submit', async e => {
    e.preventDefault();
    const right = anTrimWord(input.value);
    if (!right || right === wrong) { input.focus(); return; }
    const tab = state.activeSummaryTab;
    // one section: the one the word was selected in (a card of the overview has its own)
    const key = form.elements.all.checked ? null : (section || (tab === 'protocol' ? 'protocol' : tab));
    const res = await fetch(`/api/meetings/${m.id}/summaries/fix`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ wrong, right, key, learn: learnBox.checked }),
    }).catch(() => null);
    if (!res || !res.ok) { showError(res ? serverText((await readJson(res)).detail) : t('errNoNetwork')); return; }
    const data = await res.json();
    done();
    if (state.activeMeeting && state.activeMeeting.id === m.id) {
      state.activeMeeting.summaries = data.summaries || state.activeMeeting.summaries;
      renderSummaryPanel();
    }
    if (data.learned && data.learned.length) loadDictionary();
    showToast((data.replaced ? t('fixWordDone').replace('{n}', () => String(data.replaced)) : t('fixWordNone'))
      + (data.learned && data.learned.length ? ` · ${t('fixWordLearned')}` : ''));
  });
  document.addEventListener('keydown', onKey, true);
  document.body.appendChild(wrap);
  sayHint();
  input.focus();
  input.select();
}

// «Править»: the section's Markdown in a field; after saving, the words replaced are offered to the dictionary
function editAnalysisSection(key) {
  const m = state.activeMeeting;
  const tab = state.activeSummaryTab;
  if (!m) return;
  key = typeof key === 'string' ? key : (tab === 'protocol' ? 'protocol' : tab);
  if (!anEditable(key) || anIsBusy(key)) return;
  const box = document.getElementById('summary-content');
  const host = tab === 'protocol' ? box?.querySelector(`[data-card="${CSS.escape(key)}"] .an-cardb`) : box;
  if (!host) return;
  host.closest('.hidden')?.classList.remove('hidden');  // the protocol's card is hidden while all of it is in the cards above
  const old = m.summaries[key];
  state.anEdit = { id: m.id, tab, key };
  host.classList.remove('an-clamp');
  host.innerHTML = `<div class="an-edit">
      <textarea class="an-edit-input w-full bg-apple-sidebar border apple-border rounded-xl px-4 py-3 text-[13px] leading-relaxed text-white focus:outline-none focus:border-apple-blue resize-y" spellcheck="true" aria-label="${escapeHtml(t('anEdit'))}"></textarea>
      <div class="an-edit-bar">
        <span class="an-edit-hint">${escapeHtml(t('anEditHint'))}</span>
        <button type="button" class="an-btn" data-a="cancel">${escapeHtml(t('cancel'))}</button>
        <button type="button" class="an-btn an-btn-primary" data-a="save">${escapeHtml(t('save'))}</button>
      </div></div>`;
  const ta = host.querySelector('textarea');
  ta.value = old;
  const fit = () => { ta.style.height = 'auto'; ta.style.height = `${Math.min(ta.scrollHeight + 4, Math.max(160, window.innerHeight * 0.7))}px`; };
  ta.addEventListener('input', fit);
  const scroller = document.getElementById('an-main');
  const scrolled = scroller ? scroller.scrollTop : 0;
  const close = () => {
    state.anEdit = null;
    renderSummaryPanel();
    if (scroller) scroller.scrollTop = scrolled;  // back where the section was read
  };
  const save = async () => {
    const text = ta.value.trim();
    if (text === old.trim()) { close(); return; }
    if (!text) { showError(t('anEditEmpty')); return; }
    const res = await fetch(`/api/meetings/${m.id}/summaries/${encodeURIComponent(key)}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text, base: old }),
    }).catch(() => null);
    if (!res || !res.ok) { showError(res ? serverText((await readJson(res)).detail) : t('errNoNetwork')); return; }
    const data = await res.json();
    if (state.activeMeeting && state.activeMeeting.id === m.id) state.activeMeeting.summaries = data.summaries || state.activeMeeting.summaries;
    close();
    showToast(t('anEditSaved'));
    if ((data.suggest || []).length) offerDictionaryWords(data.suggest);
  };
  host.querySelector('[data-a="cancel"]').addEventListener('click', close);
  host.querySelector('[data-a="save"]').addEventListener('click', save);
  ta.addEventListener('keydown', e => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); save(); }
    else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
  });
  renderAnalysisHead();
  fit();
  ta.focus();
}

// The words a hand edit replaced: which of them the dictionary should learn (all ticked)
function offerDictionaryWords(pairs) {
  const wrap = document.createElement('div');
  wrap.className = 'fixed inset-0 modal-backdrop z-[70] flex items-center justify-center p-4';
  wrap.setAttribute('role', 'dialog');
  wrap.setAttribute('aria-modal', 'true');
  wrap.innerHTML = `<form class="w-full max-w-md bg-apple-card border apple-border rounded-2xl shadow-2xl p-5 space-y-4 modal-card">
      <div class="text-sm font-semibold text-white">${escapeHtml(t('learnTitle'))}</div>
      <p class="text-xs text-apple-secondary leading-relaxed">${escapeHtml(t('learnText'))}</p>
      <div class="space-y-1.5 max-h-[50vh] overflow-y-auto">${pairs.map((p, i) => `<label class="flex items-center gap-2 text-sm text-white">
          <input type="checkbox" data-i="${i}" ${p.sure === false ? '' : 'checked'}>
          <span class="break-words"><s class="opacity-60">${escapeHtml(p.wrong)}</s> → <b>${escapeHtml(p.right)}</b></span></label>`).join('')}</div>
      <div class="flex justify-end gap-2">
        <button type="button" data-a="no" class="ui-btn ui-btn-subtle">${escapeHtml(t('learnSkip'))}</button>
        <button type="submit" class="ui-btn ui-btn-primary">${escapeHtml(t('learnOk'))}</button>
      </div></form>`;
  const done = () => { removeWithExit(wrap); document.removeEventListener('keydown', onKey, true); };
  const onKey = e => { if (e.key === 'Escape') { e.stopPropagation(); done(); } };
  wrap.addEventListener('click', e => { if (e.target === wrap || e.target.closest('[data-a="no"]')) done(); });
  wrap.querySelector('form').addEventListener('submit', async e => {
    e.preventDefault();
    const chosen = [...wrap.querySelectorAll('input[data-i]:checked')].map(x => pairs[Number(x.dataset.i)]);
    done();
    if (!chosen.length) return;
    const res = await fetch('/api/dictionary/learn', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pairs: chosen }),
    }).catch(() => null);
    if (!res || !res.ok) { showError(res ? serverText((await readJson(res)).detail) : t('errNoNetwork')); return; }
    const data = await res.json();
    loadDictionary();
    showToast(t('learnDone').replace('{n}', () => String((data.learned || []).length)));
  });
  document.addEventListener('keydown', onKey, true);
  document.body.appendChild(wrap);
  wrap.querySelector('button[type="submit"]').focus();
}

// --- Doubtful words of the analysis (app/analysis_edits.py: suspects, check_with_model) ---
// Underlined: where the models of a merged transcript heard differently, a word Whisper was unsure of,
// and what the check by a model found. A click offers the other spellings, the correction dialog,
// listening to the place, or «Верно» (not underlined again in this recording).
function anSumsSig(m) {
  // the text itself, hashed: a same-length correction kept the old underlines (an audit)
  let h = 0;
  for (const [k, v] of Object.entries(m.summaries || {})) {
    const s = `${k}:${typeof v === 'string' ? v : JSON.stringify(v)}|`;
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  }
  return String(h);
}

function analysisTextShown() {
  const m = state.activeMeeting;
  return !!m && Object.entries(m.summaries || {}).some(([k, v]) => !AN_NOT_EDITABLE.has(k) && typeof v === 'string' && v.trim());
}

function anIgnored(mid) {
  try { return new Set(JSON.parse(localStorage.getItem(`vx-an-ok-${mid}`) || '[]')); } catch { return new Set(); }
}
function anIgnore(mid, word) {
  const set = anIgnored(mid);
  set.add(word.toLowerCase());
  try { localStorage.setItem(`vx-an-ok-${mid}`, JSON.stringify([...set].slice(-300))); } catch { /* per viewer only */ }
}

async function loadSuspects(m) {
  const sig = anSumsSig(m);
  const cur = state.anSuspects;
  if (cur && cur.id === m.id && (cur.sig === sig || cur.loading)) return;
  state.anSuspects = { id: m.id, sig, words: cur && cur.id === m.id ? cur.words : [], loading: true };
  const data = await fetch(`/api/meetings/${m.id}/analysis/suspects`).then(r => (r.ok ? r.json() : { words: [] })).catch(() => ({ words: [] }));
  if (!state.anSuspects || state.anSuspects.id !== m.id) return;
  state.anSuspects = { id: m.id, sig, words: data.words || [], loading: false };
  if (state.activeMeeting && state.activeMeeting.id === m.id) markSuspects(document.getElementById('summary-content'));
}

function anSuspectList(m) {
  const list = [];
  if (state.anSuspects && state.anSuspects.id === m.id) list.push(...state.anSuspects.words);
  if (state.anCheck && state.anCheck.id === m.id) {
    for (const x of state.anCheck.items) list.push({ word: x.wrong, options: [x.right], source: 'model', reason: x.reason, start: 0 });
  }
  const ok = anIgnored(m.id);
  const seen = new Set();
  return list.filter(x => {
    const k = String(x.word || '').toLowerCase();
    if (!k || ok.has(k) || seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

// The doubtful words can be hidden (asked by the user: many wavy lines make the text hard to read); the
// choice is this viewer's and stays for every recording
function suspectsHidden() {
  try { return localStorage.getItem('vx-an-suspects-off') === '1'; } catch { return false; }
}

function syncSuspectsButton(count) {
  const btn = document.getElementById('an-wavy-btn');
  const box = document.getElementById('summary-content');
  const off = suspectsHidden();
  box?.classList.toggle('an-suspects-off', off);
  if (!btn) return;
  if (typeof count === 'number') btn.classList.toggle('hidden', count === 0);
  const tip = t(off ? 'anSuspectsShow' : 'anSuspectsHide');
  btn.title = tip;
  btn.setAttribute('aria-label', tip);
  btn.setAttribute('aria-pressed', String(off));
  btn.classList.toggle('is-off', off);
}

function toggleSuspects() {
  const off = !suspectsHidden();
  try { localStorage.setItem('vx-an-suspects-off', off ? '1' : '0'); } catch { /* the choice lives for this page only */ }
  syncSuspectsButton();
}

function markSuspects(box) {
  const m = state.activeMeeting;
  if (!m || !box) return;
  loadSuspects(m);
  const list = anSuspectList(m);
  syncSuspectsButton(list.length);
  box.querySelectorAll('.an-guess').forEach(el => el.remove());
  box.querySelectorAll('.an-person').forEach(el => el.replaceWith(...el.childNodes));
  box.querySelectorAll('.an-suspect').forEach(el => el.replaceWith(document.createTextNode(el.textContent)));
  box.querySelectorAll('.an-md').forEach(el => el.normalize());
  if (!list.length) { markPeople(box); return; }
  const esc = w => w.split(/\s+/).map(p => p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s+');
  // the longest first: «Claude Code» before «Claude»
  const order = list.map((x, i) => [x, i]).sort((a, b) => b[0].word.length - a[0].word.length);
  const rx = new RegExp(`(?<![\\p{L}\\p{N}_-])(${order.map(([x]) => esc(x.word)).join('|')})(?![\\p{L}\\p{N}_-])`, 'giu');
  const byWord = new Map(list.map((x, i) => [x.word.toLowerCase().replace(/\s+/g, ' '), i]));
  box.querySelectorAll('.an-md').forEach(md => {
    if (md.closest('.an-edit')) return;
    const walker = document.createTreeWalker(md, NodeFilter.SHOW_TEXT, {
      acceptNode: n => (n.parentElement.closest('code, pre, a, button, .an-suspect, .an-guess') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const text = node.nodeValue;
      rx.lastIndex = 0;
      if (!rx.test(text)) continue;
      rx.lastIndex = 0;
      const frag = document.createDocumentFragment();
      let last = 0;
      for (const hit of text.matchAll(rx)) {
        const i = byWord.get(hit[0].toLowerCase().replace(/\s+/g, ' '));
        if (i === undefined) continue;
        frag.append(text.slice(last, hit.index));
        const span = document.createElement('span');
        span.className = `an-suspect an-suspect-${list[i].source}`;
        span.dataset.i = String(i);
        span.tabIndex = 0;
        span.title = t('anSuspectTip');
        span.textContent = hit[0];
        frag.append(span);
        last = hit.index + hit[0].length;
      }
      frag.append(text.slice(last));
      node.replaceWith(frag);
    }
  });
  state.anSuspectShown = list;
  markPeople(box);
}

// The people of «Контакты» named in the analysis are links to their card (asked by the user). A doubtful
// word stays a doubtful word: the correction comes first. Names and their variants, Russian endings allowed
function markPeople(box) {
  if (!box) return;
  if (!contacts.list) { loadContacts().then(() => { if (contacts.list && contacts.list.length) markSuspects(box); }); return; }
  linkPeople(box, '.an-md');
}

// The same links in other texts: a task's words (the Tasks page, a recording's tasks). Elements of `selector`
// inside `root`; their earlier links are made again
function linkPeople(root, selector) {
  if (!root) return;
  if (!contacts.list) { loadContacts().then(list => { if (list && list.length) linkPeople(root, selector); }); return; }
  root.querySelectorAll(`${selector} .an-guess`).forEach(el => el.remove());
  root.querySelectorAll(`${selector} .an-person`).forEach(el => el.replaceWith(...el.childNodes));
  const spell = [];
  for (const p of contacts.list) {
    if (p.kind !== 'person') continue;
    for (const s of [p.name, ...(p.aliases || [])]) if (String(s || '').trim().length >= 3) spell.push([s.trim(), p.name]);
  }
  if (!spell.length) { markUnknownPeople(root, selector); return; }
  spell.sort((a, b) => b[0].length - a[0].length);  // «Анна Петрова» before «Анна»
  // any case form: «Олега»; a name ending in а/я/й/ь changes it: «Ксении», «Игоря» (app/people.py name_regex)
  const esc = w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const form = s => {
    const body = s.split(/\s+/).map(esc).join('\\s+');
    return s.length >= 4 && /[аяйь]$/i.test(s) ? `${body.slice(0, -1)}(?:а|я|у|ю|ой|ей|ою|ею|ы|и|е|й|ь|ем|ём|ом)`
      : `${body}(?:а|у|ой|ом|е|ы|ю|ем|и|я|ей|ов|ым)?`;
  };
  const rx = new RegExp(`(?<![\\p{L}\\p{N}_-])(?:${spell.map(([s]) => `(${form(s)})`).join('|')})(?![\\p{L}\\p{N}_-])`, 'giu');
  root.querySelectorAll(selector).forEach(md => {
    if (md.closest('.an-edit')) return;
    md.normalize();
    const walker = document.createTreeWalker(md, NodeFilter.SHOW_TEXT, {
      acceptNode: n => (n.parentElement.closest('code, pre, a, button, .an-suspect, .an-person, .an-guess') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const text = node.nodeValue;
      rx.lastIndex = 0;
      if (!rx.test(text)) continue;
      rx.lastIndex = 0;
      const frag = document.createDocumentFragment();
      let last = 0;
      for (const hit of text.matchAll(rx)) {
        const at = hit.slice(1).findIndex(x => x !== undefined);
        const name = at >= 0 ? spell[at][1] : '';
        if (!name) continue;
        frag.append(text.slice(last, hit.index));
        const span = document.createElement('span');
        span.className = 'an-person';
        span.dataset.person = name;
        span.tabIndex = 0;
        span.setAttribute('role', 'link');
        span.title = t('anPersonTip').replace('{name}', () => name);
        span.textContent = hit[0];
        frag.append(span);
        last = hit.index + hit[0].length;
      }
      frag.append(text.slice(last));
      node.replaceWith(frag);
    }
  });
  markUnknownPeople(root, selector);
}

// A name that is not in the contacts (asked by the user: every person named is a link, so that no one is
// made up). A capitalised word that is a given name (given_names.js), with the surname beside it: dashed
// amber, a click adds the person to the contacts or says which contact it is. In the analysis of a recording
// a name its transcript does not have at all is red: the model may have made the person up
function givenName(word) {
  const w = String(word || '').toLowerCase();
  if (w.length < 3) return '';
  const tries = [w];
  for (const end of ['ами', 'ями', 'ого', 'ому', 'ой', 'ей', 'ом', 'ем', 'ою', 'ею', 'ам', 'ям', 'ах', 'ях', 'а', 'я', 'у', 'ю', 'е', 'ы', 'и']) {
    if (w.endsWith(end) && w.length - end.length >= 2) {
      const stem = w.slice(0, -end.length);
      tries.push(stem, stem + 'а', stem + 'я', stem + 'й', stem + 'ь', stem + 'ия');
    }
  }
  const hit = tries.find(x => GIVEN_NAMES.has(x));
  return hit ? hit[0].toUpperCase() + hit.slice(1) : '';
}

// Latin letters as Russian (Boris → борис, Dmitry → дмитрий), to match a name with a contact spelled in the
// other alphabet. Rough on purpose: only the first letters of the two are compared after it
function toCyrillic(word) {
  let w = String(word || '').toLowerCase();
  if (!/[a-z]/.test(w)) return w;
  const pairs = [['shch', 'щ'], ['sch', 'щ'], ['yo', 'ё'], ['yu', 'ю'], ['ya', 'я'], ['zh', 'ж'], ['kh', 'х'], ['ts', 'ц'], ['ch', 'ч'], ['sh', 'ш'],
    ['iy', 'ий'], ['yi', 'ий'], ['ey', 'ей'], ['ay', 'ай'], ['oy', 'ой'], ['x', 'кс'], ['a', 'а'], ['b', 'б'], ['c', 'к'], ['d', 'д'],
    ['e', 'е'], ['f', 'ф'], ['g', 'г'], ['h', 'х'], ['i', 'и'], ['j', 'дж'], ['k', 'к'], ['l', 'л'], ['m', 'м'], ['n', 'н'], ['o', 'о'],
    ['p', 'п'], ['q', 'к'], ['r', 'р'], ['s', 'с'], ['t', 'т'], ['u', 'у'], ['v', 'в'], ['w', 'в'], ['y', 'ы'], ['z', 'з']];
  let out = '';
  while (w) {
    const hit = pairs.find(([a]) => w.startsWith(a));
    if (hit) { out += hit[1]; w = w.slice(hit[0].length); } else { out += w[0]; w = w.slice(1); }
  }
  return out.replace(/ы$/, 'и').replace(/ий$/, 'ий');
}

function nameGroupOf(word) {
  const w = toCyrillic(givenName(word) || word).toLowerCase();
  const g = typeof NAME_GROUPS !== 'undefined' && NAME_GROUPS.find(x => x.includes(w));
  return g ? g[0] : w;
}

function sameStem(a, b) {
  const x = toCyrillic(a).toLowerCase(), y = toCyrillic(b).toLowerCase();
  const n = Math.min(x.length, y.length);
  if (n < 4) return x === y;
  let i = 0;
  while (i < n && x[i] === y[i]) i++;
  return i >= Math.max(4, n - 2);
}

// Who of the contacts a name of the analysis most likely is (asked by the user: an unclear person is offered,
// as a feature is): the surname first, then the name in any of its forms («Дима» — Дмитрий, Boris — Борис).
// One contact clearly ahead, or nobody
function guessContact(first, surname) {
  const people = (contacts.list || []).filter(p => p.kind === 'person');
  const key = first ? nameGroupOf(first) : '';
  const scored = people.map(p => {
    let score = 0;
    for (const spelling of [p.name, ...(p.aliases || [])]) {
      const words = spelling.split(/\s+/);
      let sc = 0;
      if (surname && words.some(w => sameStem(w, surname))) sc += 3;
      if (key && words.some(w => nameGroupOf(w) === key)) sc += 2;
      score = Math.max(score, sc);
    }
    return { p, score };
  }).filter(x => x.score >= 2).sort((a, b) => b.score - a.score || (b.p.recordings || 0) - (a.p.recordings || 0));
  if (!scored.length || (scored[1] && scored[1].score === scored[0].score)) return '';
  return scored[0].p.name;
}

function guessDismissed(said, name) {
  try { return (JSON.parse(localStorage.getItem('vx-guess-no') || '[]')).includes(`${said}|${name}`.toLowerCase()); } catch { return false; }
}

function dismissGuess(said, name) {
  try {
    const list = JSON.parse(localStorage.getItem('vx-guess-no') || '[]');
    list.push(`${said}|${name}`.toLowerCase());
    localStorage.setItem('vx-guess-no', JSON.stringify(list.slice(-500)));
  } catch { /* this page only */ }
}

async function acceptGuess(said, name) {
  const res = await fetch('/api/people/merge', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ names: [name, said] }) });
  if (!res.ok) { showError(serverText((await readJson(res)).detail)); return; }
  showToast(t('pnMerged').replace('{name}', () => said).replace('{contact}', () => name), null, 'success');
  await relinkPeople();
}

async function relinkPeople() {
  await loadContacts(true);
  // the confirmed spelling is written out as the full name in this recording's analysis (app/people.expand_names)
  const m = state.activeMeeting;
  if (m) {
    const data = await fetch(`/api/meetings/${m.id}/analysis/expand-names`, { method: 'POST' }).then(r => (r.ok ? r.json() : null)).catch(() => null);
    if (data && data.changed && data.changed.length && state.activeMeeting === m) { m.summaries = data.summaries; renderSummaryPanel(); return; }
  }
  markSuspects(document.getElementById('summary-content'));
  if (state.appView === 'tasks' && typeof renderTasks === 'function') renderTasks();
  if (state.activeSummaryTab === 'commitments') renderSummaryPanel();
}

function transcriptHas(word) {
  const m = state.activeMeeting;
  if (!m || !Array.isArray(m.segments)) return true;
  if (!m._lowText) Object.defineProperty(m, '_lowText', { value: m.segments.map(x => x.text || '').join(' ').toLowerCase(), enumerable: false });
  const w = String(word || '').toLowerCase();
  // a name in the other alphabet («Boris» for «Борис» said in a Russian talk) is not checked: it is not an invention
  const latin = /[a-z]/.test(w), cyr = /[а-яё]/.test(m._lowText.slice(0, 2000));
  if (latin === cyr) return true;
  return m._lowText.includes(w.length > 5 ? w.slice(0, w.length - 2) : w.slice(0, 4));
}

function markUnknownPeople(root, selector) {
  if (typeof GIVEN_NAMES === 'undefined') return;
  const inMeeting = !!root.closest?.('#summary-content') || root.id === 'summary-content';
  const offeredHere = new Set();
  root.querySelectorAll(`${selector} .an-guess`).forEach(el => el.remove());
  const rx = /(?<![\p{L}\p{N}_-])(\p{Lu}[\p{Ll}'’-]+)(?:\s+(\p{Lu}[\p{Ll}'’-]+))?(?![\p{L}\p{N}_-])/gu;
  root.querySelectorAll(selector).forEach(md => {
    if (md.closest('.an-edit')) return;
    const walker = document.createTreeWalker(md, NodeFilter.SHOW_TEXT, {
      acceptNode: n => (n.parentElement.closest('code, pre, a, button, .an-suspect, .an-person, .an-guess') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
    });
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      const text = node.nodeValue;
      const frag = document.createDocumentFragment();
      let last = 0, any = false;
      for (const hit of text.matchAll(rx)) {
        const first = givenName(hit[1]), second = hit[2] ? givenName(hit[2]) : '';
        if (!first && !second) continue;
        // «Захар Петров», «Kotov Boris»: the name and the surname; the name as said otherwise
        const guess = first ? [first, hit[2] || ''].join(' ').trim() : [hit[1], second].join(' ');
        const name = first || second, surname = first ? hit[2] : hit[1];
        const maybe = guessContact(name, surname || '');
        const offered = maybe && !guessDismissed(guess, maybe) ? maybe : '';
        const invented = !offered && inMeeting && !transcriptHas(first ? hit[1] : hit[2]);
        frag.append(text.slice(last, hit.index));
        const span = document.createElement('span');
        span.className = `an-person ${offered ? 'an-person-maybe' : 'an-person-new'}${invented ? ' an-person-invented' : ''}`;
        span.dataset.new = guess;
        if (offered) span.dataset.guess = offered;
        span.tabIndex = 0;
        span.setAttribute('role', 'button');
        span.title = offered ? t('anPersonMaybe').replace('{name}', () => guess).replace('{contact}', () => offered)
          : t(invented ? 'anPersonInvented' : 'anPersonNew').replace('{name}', () => guess);
        span.textContent = hit[0];
        frag.append(span);
        // the offer once per name in a text, as a feature is offered: «Дмитрий Орлов?» ✓ ✕
        const shownKey = `${guess}|${offered}`.toLowerCase();
        if (offered && !offeredHere.has(shownKey)) {
          offeredHere.add(shownKey);
          const chip = document.createElement('span');
          chip.className = 'ft-suggest an-guess';
          chip.innerHTML = `<span class="ft-chip ft-chip-suggested" style="--ft:#64D2FF"><span class="ft-name">${escapeHtml(offered)}?</span></span>`
            + `<button class="ft-yes" data-guess-ok data-said="${escapeHtml(guess)}" data-contact="${escapeHtml(offered)}" title="${escapeHtml(t('anGuessYes').replace('{contact}', () => offered))}" aria-label="${escapeHtml(t('anGuessYes').replace('{contact}', () => offered))}">✓</button>`
            + `<button class="ft-no" data-guess-no data-said="${escapeHtml(guess)}" data-contact="${escapeHtml(offered)}" title="${escapeHtml(t('anGuessNo'))}" aria-label="${escapeHtml(t('anGuessNo'))}">✕</button>`;
          frag.append(chip);
        }
        last = hit.index + hit[0].length;
        any = true;
      }
      if (!any) continue;
      frag.append(text.slice(last));
      node.replaceWith(frag);
    }
  });
}

// A click on a name not in the contacts: add it, or say which contact it is (the name becomes their variant)
function openUnknownPersonMenu(el) {
  const said = el.dataset.new, shown = el.textContent, offered = el.dataset.guess;
  const r = el.getBoundingClientRect();
  const relink = relinkPeople;
  const items = [...(offered ? [{ label: t('anGuessYes').replace('{contact}', () => offered), run: () => acceptGuess(said, offered) },
    { label: t('anGuessNo'), run: () => { dismissGuess(said, offered); relinkPeople(); } }, { sep: true }] : []), { label: t('pnAdd').replace('{name}', () => said), run: async () => {
    const name = await askText(t('pnAddAsk'), said);
    if (!name || !name.trim()) return;
    const res = await fetch('/api/people/directory', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name.trim(), kind: 'person' }) });
    if (!res.ok) { showError(serverText((await readJson(res)).detail)); return; }
    showToast(t('pnAdded').replace('{name}', () => name.trim()), null, 'success');
    await relink();
  } }, { label: t('pnIsContact'), run: () => {
    const people = (contacts.list || []).filter(p => p.kind === 'person').slice(0, 14);
    if (!people.length) { showToast(t('pnNoContacts')); return; }
    setTimeout(() => openTextMenuAt(people.map(p => ({ label: p.name, run: async () => {
      const res = await fetch('/api/people/merge', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ names: [p.name, said] }) });
      if (!res.ok) { showError(serverText((await readJson(res)).detail)); return; }
      showToast(t('pnMerged').replace('{name}', () => said).replace('{contact}', () => p.name), null, 'success');
      await relink();
    } })), r.left, r.bottom + 4), 0);
  } }];
  if (el.classList.contains('an-person-invented') && el.closest('#summary-content')) {
    items.push({ sep: true }, { label: t('pnFixWord'), run: () => openWordFixDialog(shown, el.closest('[data-md]')?.dataset.md || null) });
  }
  setTimeout(() => openTextMenuAt(items, r.left, r.bottom + 4), 0);
}

// A contact named in the analysis: their card, or «someone else» (asked by the user: a contribution was put
// under a wrong surname) — every mention of them in this recording's analysis and its tasks take the other one
function openKnownPersonMenu(el) {
  const name = el.dataset.person;
  const m = state.activeMeeting;
  const r = el.getBoundingClientRect();
  const items = [{ label: t('pnOpenCard').replace('{name}', () => name), run: () => openPersonCard(name) }];
  if (m && el.closest('#summary-content')) {
    items.push({ sep: true }, { label: t('pnIsSomeoneElse'), run: () => setTimeout(() => openReplacePersonMenu(name, r), 0) });
  }
  setTimeout(() => openTextMenuAt(items, r.left, r.bottom + 4), 0);
}

async function openReplacePersonMenu(name, r) {
  const m = state.activeMeeting;
  if (!m) return;
  if (typeof loadContacts === 'function') await loadContacts(true);  // the contacts as they are now
  const low = name.toLowerCase();
  // the participants of the recording first, then the other contacts
  const here = Object.values(m.speakers || {}).map(sp => sp && sp.name).filter(Boolean);
  const people = (contacts.list || []).filter(p => p.kind === 'person').map(p => p.name);
  const names = [...new Set([...here, ...people])].filter(n => n.toLowerCase() !== low && !/^(SPEAKER_|Спикер |Speaker )/i.test(n)).slice(0, 16);
  const items = [{ info: true, label: t('pnReplaceWho').replace('{name}', () => name) }, { sep: true },
    ...names.map(n => ({ label: n, run: () => replacePersonInAnalysis(name, n) })),
    { sep: true }, { label: t('pnReplaceOther'), run: async () => {
      const typed = await askText(t('pnReplaceAsk').replace('{name}', () => name), '');
      if (typed && typed.trim()) replacePersonInAnalysis(name, typed.trim());
    } }];
  openTextMenuAt(items, r.left, r.bottom + 4);
}

async function replacePersonInAnalysis(oldName, newName, undo = false) {
  const m = state.activeMeeting;
  if (!m) return;
  const res = await fetch(`/api/meetings/${m.id}/analysis/rename-person`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ old: oldName, new: newName }),
  });
  const data = await readJson(res);
  if (!res.ok) { showError(errorText(data, res)); return; }
  if (state.activeMeeting !== m) return;
  m.summaries = data.summaries;
  renderSummaryPanel();
  if (data.tasks && typeof loadTasks === 'function') loadTasks().then(() => { if (state.appView === 'tasks') renderTasks(); });
  if (undo) return;
  if (!data.changed.length && !data.tasks) { showToast(t('pnReplaceNone').replace('{name}', () => oldName)); return; }
  showToast(t('pnReplaced').replace('{name}', () => oldName).replace('{other}', () => newName),
    { label: t('spUndo'), onClick: () => replacePersonInAnalysis(newName, oldName, true) });
}

function openSuspectMenu(el) {
  const m = state.activeMeeting;
  const x = (state.anSuspectShown || [])[Number(el.dataset.i)];
  if (!m || !x) return;
  const shown = el.textContent;
  const why = x.source === 'dispute' ? t('anSuspectDispute') : x.source === 'unsure' ? t('anSuspectUnsure')
    : `${t('anSuspectModel')}${x.reason ? `: ${x.reason}` : ''}`;
  const items = [{ info: true, label: why }, { sep: true }];
  for (const o of x.options || []) {
    items.push({ label: t('anSuspectUse').replace('{word}', () => o), run: () => fixWordAt(shown, o) });
  }
  items.push({ label: t('anSuspectOther'), run: () => openWordFixDialog(shown, el.closest('[data-md]')?.dataset.md || null) });
  if (x.start) items.push({ label: t('ctxPlayFromHere'), key: formatTime(x.start), run: () => seekPlayer(x.start) });
  items.push({ sep: true }, {
    label: t('anSuspectOk'), run: () => { anIgnore(m.id, x.word); markSuspects(document.getElementById('summary-content')); },
  });
  const r = el.getBoundingClientRect();
  openTextMenuAt(items, r.left, r.bottom + 4, { maxWidth: 380 });
}

// One click: the other spelling in every section, and the dictionary learns it
async function fixWordAt(wrong, right) {
  const m = state.activeMeeting;
  if (!m) return;
  // the dictionary is not taught by one click: «мы» → «вы» would change every «мы» after it (an audit);
  // the toast offers it
  const res = await fetch(`/api/meetings/${m.id}/summaries/fix`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ wrong, right, learn: false }),
  }).catch(() => null);
  if (!res || !res.ok) { showError(res ? serverText((await readJson(res)).detail) : t('errNoNetwork')); return; }
  const data = await res.json();
  if (state.activeMeeting && state.activeMeeting.id === m.id) {
    state.activeMeeting.summaries = data.summaries || state.activeMeeting.summaries;
    renderSummaryPanel();
  }
  showToast(t('fixWordDone').replace('{n}', () => String(data.replaced || 0)), {
    label: t('fixWordRemember'),
    onClick: async () => {
      const r = await fetch('/api/dictionary/learn', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pairs: [{ wrong, right }] }),
      }).catch(() => null);
      const learned = r && r.ok ? (await r.json()).learned || [] : [];
      if (learned.length) { loadDictionary(); showToast(t('fixWordLearned')); }
    },
  });
}

// «Проверить слова»: a small model reads the analysis; what it finds is underlined like the rest
async function checkAnalysisWords() {
  const m = state.activeMeeting;
  if (!m || state.anChecking) return;
  if (!aiAvailable()) { showToast(t('anNeedModel')); return; }
  state.anChecking = true;
  showToast(t('anCheckRunning'));
  try {
    const res = await fetch(`/api/meetings/${m.id}/analysis/check`, { method: 'POST' }).catch(() => null);
    if (!res || !res.ok) { showError(res ? serverText((await readJson(res)).detail) : t('errNoNetwork')); return; }
    const items = (await res.json()).suggestions || [];
    state.anCheck = { id: m.id, items };
    if (state.activeMeeting && state.activeMeeting.id === m.id) markSuspects(document.getElementById('summary-content'));
    showToast(items.length ? t('anCheckFound').replace('{n}', () => String(items.length)) : t('anCheckNone'));
  } finally {
    state.anChecking = false;
  }
}

// The offer of a contact for a name: ✓ makes the name their variant, ✕ stops offering them for it
document.addEventListener('click', (e) => {
  const b = e.target.closest && e.target.closest('[data-guess-ok], [data-guess-no]');
  if (!b) return;
  e.stopPropagation();
  if (b.hasAttribute('data-guess-ok')) acceptGuess(b.dataset.said, b.dataset.contact);
  else { dismissGuess(b.dataset.said, b.dataset.contact); relinkPeople(); }
}, true);
// A name of a contact anywhere else (a task's words): its card
document.addEventListener('click', (e) => {
  const who = e.target.closest && e.target.closest('.an-person');
  if (!who || who.closest('#summary-content')) return;
  e.stopPropagation();
  if (who.dataset.new) openUnknownPersonMenu(who); else openPersonCard(who.dataset.person);
});
document.getElementById('summary-content')?.addEventListener('click', (e) => {
  const who = e.target.closest && e.target.closest('.an-person');
  if (who) { e.stopPropagation(); if (who.dataset.new) openUnknownPersonMenu(who); else openKnownPersonMenu(who); return; }
  const el = e.target.closest && e.target.closest('.an-suspect');
  if (!el) return;
  e.stopPropagation();  // the click would close the menu it opens
  openSuspectMenu(el);
});
document.getElementById('summary-content')?.addEventListener('keydown', (e) => {
  const who = e.target.closest && e.target.closest('.an-person');
  if (who && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); if (who.dataset.new) openUnknownPersonMenu(who); else openKnownPersonMenu(who); return; }
  const el = e.target.closest && e.target.closest('.an-suspect');
  if (el && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); openSuspectMenu(el); }
});

document.addEventListener('contextmenu', (e) => {
  closeTextMenu();
  if (e.defaultPrevented) return;
  const items = textMenuItems(e);
  if (!items || !items.some(i => !i.sep)) return;
  e.preventDefault();
  openTextMenuAt(items, e.clientX, e.clientY);
});

// A small menu of items ({label, key, run, disabled} or {sep}) at a point of the window
function openTextMenuAt(items, x, y, opts) {
  closeTextMenu();
  closeQuickLangMenu();
  const menu = document.createElement('div');
  menu.id = 'text-menu';
  menu.className = 'fixed min-w-[220px] macos-menu z-[60]';
  const clean = items.filter((it, i, a) => !it.sep || (i > 0 && !a[i - 1].sep && i < a.length - 1));
  menu.innerHTML = clean.map((it, i) => it.sep
    ? '<div class="my-1 h-px bg-white/10"></div>'
    : it.info  // a line that only says something (who chose a disputed word), not an action
    ? `<div class="tm-info">${escapeHtml(it.label)}</div>`
    : `<button class="macos-menu-item gap-6${it.danger ? ' tm-danger' : ''}" data-i="${i}" ${it.disabled ? 'disabled style="opacity:.4"' : ''}><span class="min-w-0 truncate">${escapeHtml(it.label)}</span>`
      + `<span class="tm-key">${escapeHtml(it.key || '')}</span></button>`).join('');
  // Keeps the selection: a click in the menu must not clear it before the action reads it
  menu.addEventListener('mousedown', ev => ev.preventDefault());
  menu.addEventListener('click', (ev) => {
    const b = ev.target.closest('button[data-i]');
    ev.stopPropagation();
    if (!b || b.disabled) return;
    closeTextMenu();
    clean[Number(b.dataset.i)].run();
  });
  if (opts && opts.maxWidth) menu.style.maxWidth = `${opts.maxWidth}px`;
  menu.style.maxHeight = `${viewH() - 8}px`;  // a long list scrolls instead of leaving the window
  menu.style.overflowY = 'auto';
  document.body.appendChild(menu);
  // x, y are a point of the window (clientX/Y); the menu is placed in the page's own pixels.
  // opts.right: x is the menu's right edge (a menu under a button at the right)
  const r = menu.getBoundingClientRect();
  const left = opts && opts.right ? zpx(x) - zpx(r.width) : zpx(x);
  menu.style.left = `${Math.max(4, Math.min(left, viewW() - zpx(r.width) - 4))}px`;
  menu.style.top = `${Math.max(4, Math.min(zpx(y), viewH() - zpx(r.height) - 4))}px`;
}
document.addEventListener('click', closeTextMenu);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeTextMenu(); });
window.addEventListener('blur', closeTextMenu);
// The page scrolling under the menu closes it; a long menu scrolling its own list does not
document.addEventListener('scroll', (e) => { if (!(e.target instanceof Element && e.target.closest('#text-menu'))) closeTextMenu(); }, true);

// --- About (GET /api/about) and its easter eggs: the willow hears everything ---
const ABOUT_LINES = {
  ru: [
    'Участник 3 просил не записывать. Записано.',
    '[неразборчиво] — но мы поняли.',
    'Ваша последняя фраза уже в протоколе. [00:00]',
    'Пункт помечен [?]: доказательств нет. Пока.',
    'Слова-паразиты удалены. Паразиты — нет.',
    'Обещание найдено: «сделаю к пятнице». Пятница не найдена.',
    'Верба не спит. Верба транскрибирует.',
    'Тишина длилась 3 секунды. Расшифровано: «…».',
    'Голос узнан: это вы. Опять.',
  ],
  en: [
    'Participant 3 asked not to be recorded. Recorded.',
    '[inaudible], but we got it.',
    'Your last sentence is already in the minutes. [00:00]',
    'Point marked [?]: no evidence. Yet.',
    'Filler words removed. The fillers themselves are still here.',
    'Promise found: "done by Friday". Friday not found.',
    'The willow does not sleep. The willow transcribes.',
    'Silence lasted 3 seconds. Transcribed: "…".',
    'Voice recognized: it is you. Again.',
  ],
};
const ABOUT_EGG = {
  ru: [
    ['00:00', 'Участник 1', '#64D2FF', '…он опять кликает по вербе.'],
    ['00:02', 'Участник 2', '#BF5AF2', 'Пусть. Мы всё равно всё записываем.'],
    ['00:04', 'Участник ?', '#FF453A', 'Тише. Он читает субтитры.'],
    ['00:07', null, null, 'Разделение по голосам: найдено 4 участника. В комнате — 1 человек. [?]'],
    ['00:09', null, null, 'Обещание: «больше не кликать по логотипу». Срок: никогда.'],
    ['00:11', 'Участник 4', '#FF9F0A', 'Не оборачивайся.'],
  ],
  en: [
    ['00:00', 'Participant 1', '#64D2FF', '…he is clicking the willow again.'],
    ['00:02', 'Participant 2', '#BF5AF2', 'Let him. We are recording everything anyway.'],
    ['00:04', 'Participant ?', '#FF453A', 'Quiet. He is reading the captions.'],
    ['00:07', null, null, 'Speaker separation: 4 participants found. People in the room: 1. [?]'],
    ['00:09', null, null, 'Promise: "no more clicking the logo". Due: never.'],
    ['00:11', 'Participant 4', '#FF9F0A', 'Do not turn around.'],
  ],
};
const about = { clicks: [], line: -1, typing: null, egg: [], eggOn: false };

async function openAbout() {
  hideContextMenu();
  const d = await fetch('/api/about').then(r => r.json()).catch(() => null);
  const en = state.uiLang === 'en';
  if (d) {
    document.getElementById('about-version').textContent = d.version;
    const since = d.since ? d.since.split('-').reverse().join('.') : '';
    const n = d.recordings;
    const amount = d.hours >= 1 ? `${d.hours} ${en ? 'h' : 'ч'}` : `${Math.max(1, Math.round(d.hours * 60))} ${en ? 'min' : 'мин'}`;
    const recs = en ? (n === 1 ? 'recording' : 'recordings') : (n % 10 === 1 && n % 100 !== 11 ? 'записи' : 'записях');
    document.getElementById('about-stats').textContent = n
      ? (en ? `Transcribed ${amount} of speech in ${n} ${recs} since ${since}` : `Расшифровано ${amount} речи в ${n} ${recs} с ${since}`)
      : (en ? 'Nothing transcribed yet' : 'Расшифрованных записей пока нет');
  }
  document.getElementById('about-caption').textContent = '';
  endAboutEgg();
  openModal('about');
}

function aboutTypeLine(text) {
  const box = document.getElementById('about-caption');
  clearInterval(about.typing);
  let i = 0;
  box.innerHTML = '<span></span><span class="caret"></span>';
  const span = box.firstChild;
  about.typing = setInterval(() => {
    span.textContent = text.slice(0, ++i);
    if (i >= text.length) clearInterval(about.typing);
  }, 28);
}

function aboutLogoClick() {
  if (about.eggOn) return;
  const logo = document.getElementById('about-logo');
  logo.classList.remove('about-shake');
  void logo.offsetWidth;  // restart the animation
  logo.classList.add('about-shake');
  releaseWillowFluff(10, 1.3, logo);
  const now = Date.now();
  about.clicks = about.clicks.filter(t => now - t < 2000).concat(now);
  if (about.clicks.length >= 5) { about.clicks = []; startAboutEgg(); return; }
  const lines = ABOUT_LINES[state.uiLang === 'en' ? 'en' : 'ru'];
  about.line = (about.line + 1) % lines.length;
  aboutTypeLine(lines[about.line]);
}

function startAboutEgg() {
  const en = state.uiLang === 'en';
  const box = document.getElementById('about-egg');
  const list = document.getElementById('about-egg-lines');
  const timer = document.getElementById('about-egg-timer');
  list.innerHTML = '';
  box.classList.remove('hidden');
  box.parentElement.classList.add('about-egg-on');  // room for the whole transcript
  about.eggOn = true;
  const started = Date.now();
  const tick = setInterval(() => {
    const s = Math.floor((Date.now() - started) / 1000);
    timer.textContent = `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
  }, 250);
  about.egg.push(tick);
  // Now and then the whole window glitches, every 2.5-5 s (its last line glitches too)
  const glitch = () => {
    box.classList.remove('egg-glitch');
    void box.offsetWidth;  // restart the animation
    box.classList.add('egg-glitch');
    about.egg.push(setTimeout(glitch, 2500 + Math.random() * 2500));
  };
  about.egg.push(setTimeout(glitch, 1800));
  const lines = ABOUT_EGG[en ? 'en' : 'ru'];
  lines.forEach(([ts, who, color, text], i) => {
    about.egg.push(setTimeout(() => {
      const row = document.createElement('div');
      row.innerHTML = `<span class="ts">[${ts}]</span>` + (who
        ? `<span class="who" style="color:${color}">${escapeHtml(who)}:</span><span class="text-white">${escapeHtml(text)}</span>`
        : `<span class="sys">${escapeHtml(text)}</span>`);
      list.appendChild(row);
    }, 900 + i * 1700));
  });
  about.egg.push(setTimeout(() => {
    const row = document.createElement('div');
    row.className = 'glitch pt-3';
    row.textContent = en ? 'Kidding. Everything runs locally, the microphone is off. Probably.'
      : 'Шутка. Всё работает локально, микрофон выключен. Наверное.';
    list.appendChild(row);
    releaseWillowFluff(60, 3.4, document.getElementById('about-logo'));
  }, 900 + lines.length * 1700 + 600));
  about.egg.push(setTimeout(endAboutEgg, 900 + lines.length * 1700 + 6000));
}

function endAboutEgg() {
  about.egg.forEach(id => { clearTimeout(id); clearInterval(id); });
  about.egg = [];
  about.eggOn = false;
  const box = document.getElementById('about-egg');
  box?.classList.add('hidden');
  box?.classList.remove('egg-glitch');
  box?.parentElement.classList.remove('about-egg-on');
}
