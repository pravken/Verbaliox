// Verbaliox page script, part 2 of 9: The export menu and the recording context menu.
// The parts are classic scripts sharing one global scope, loaded in order by index.html.

// --- Export: every format in one menu. What the recording does not have yet (a translation, a
// dub, even the transcript while it is being made) is made first, and the file is then saved into
// the export folder by itself (app/pending_exports.py). ---
function exportLangChoices() {
  const m = state.activeMeeting;
  const have = Object.keys(meetingTranslations(m));
  const src = (m && m.language) || '';
  const all = (_textLangs || TEXT_LANG_FALLBACK).filter(c => c !== src && !have.includes(c))
    .map(c => ({ c, n: langName(c) })).sort((a, b) => a.n.localeCompare(b.n));
  return { have, others: all };
}

function renderExportMenu() {
  const menu = document.getElementById('export-menu');
  const m = state.activeMeeting;
  if (!m) { menu.innerHTML = ''; return; }
  const isVideo = !!m.is_video;
  const busy = !DONE_STATUSES.includes(m.status);
  const { have, others } = exportLangChoices();
  const src = (m.language || '').toLowerCase();
  if (!state.exportLang || state.exportLang === src) {
    state.exportLang = have[0] || (src === 'en' ? 'ru' : 'en');
  }
  const trLang = state.exportLang;
  const trReady = have.includes(trLang);
  const dubs = availableDubs(m).map(d => d.lang);
  const dubLangs = Object.keys(I18N.ru.dubLangNames).filter(c => c !== src);
  if (!state.exportDubLang || !dubLangs.includes(state.exportDubLang)) state.exportDubLang = dubs[0] || (src === 'en' ? 'ru' : 'en');
  const dubLang = state.exportDubLang;
  const dubReady = dubs.includes(dubLang);

  const header = (label, extra = '') =>
    `<div class="px-2.5 pt-2 pb-1 flex items-center justify-between gap-2"><span class="text-[11px] font-semibold uppercase tracking-wider text-apple-secondary">${escapeHtml(label)}</span>${extra}</div>`;
  const item = (payload, label, tag, hint) =>
    `<button data-click="runExport" data-click-args='[${jsArg(payload)}]' class="macos-menu-item gap-3" ${hint ? `title="${escapeHtml(hint)}"` : ''}>`
    + `<span class="truncate">${escapeHtml(label)}</span><span class="text-[11px] opacity-80 shrink-0">${escapeHtml(tag)}</span></button>`;
  const note = (text, cls = 'text-apple-tertiary') => `<div class="px-2.5 pb-1 text-[11px] leading-snug ${cls}">${escapeHtml(text)}</div>`;
  const sep = '<div class="my-1 border-t border-white/10"></div>';
  const langSelect = (id, fn, options) =>
    `<select id="${id}" ${pageCall('change', fn, [{ $: 'value' }])} ${pageCall('click', 'stopEvent', [{ $: 'event' }])} class="h-6 max-w-[150px] bg-apple-sidebar border apple-border rounded-md px-1.5 text-[11.5px] text-white focus:outline-none">${options}</select>`;

  let html = '';
  if (busy) html += note(t('exportWhileProcessing'), 'text-apple-amber');
  html += header(t('exportGroupDoc'));
  html += rpExportOptionsHtml();  // time stamps, names, without fillers: the text files take them (redesign_player.js)
  html += item({ kind: 'doc', fmt: 'docx' }, 'Word', 'DOCX') + item({ kind: 'doc', fmt: 'md' }, 'Markdown', 'MD')
    + item({ kind: 'doc', fmt: 'txt' }, t('exportPlainText'), 'TXT') + item({ kind: 'doc', fmt: 'json' }, 'JSON', 'JSON');

  html += sep + header(t('exportGroupSubs'));
  html += item({ kind: 'doc', fmt: 'srt' }, t('exportSrtFile'), 'SRT') + item({ kind: 'doc', fmt: 'vtt' }, t('exportVttFile'), 'VTT');
  if (isVideo) {
    html += item({ kind: 'video_soft' }, t('exportVideoSoft'), t('exportTagVideo'), t('tipSubsSoft'))
      + item({ kind: 'video_burn' }, t('exportVideoBurn'), t('exportTagVideo'), t('tipSubsBurn'));
  }

  const trOptions = (have.length ? `<optgroup label="${escapeHtml(t('exportLangReady'))}">${have.map(c => `<option value="${escapeHtml(c)}" ${c === trLang ? 'selected' : ''}>✓ ${escapeHtml(langName(c))}</option>`).join('')}</optgroup>` : '')
    + `<optgroup label="${escapeHtml(t('exportLangNew'))}">${others.map(o => `<option value="${escapeHtml(o.c)}" ${o.c === trLang ? 'selected' : ''}>${escapeHtml(o.n)}</option>`).join('')}</optgroup>`;
  html += sep + header(t('exportGroupTr'), langSelect('export-tr-lang', 'setExportLang', trOptions));
  if (!trReady) html += note(t('exportTrWillRun').replace('{lang}', () => langName(trLang)));
  const tr = (fmt, variant, label, tag) => item({ kind: 'doc', fmt, lang: trLang, variant }, label, tag);
  html += tr('docx', 'translated', 'Word', 'DOCX') + tr('md', 'translated', 'Markdown', 'MD') + tr('txt', 'translated', t('exportPlainText'), 'TXT')
    + tr('srt', 'translated', t('exportSrtFile'), 'SRT') + tr('vtt', 'translated', t('exportVttFile'), 'VTT')
    + tr('docx', 'bilingual', `Word · ${t('exportBilingual')}`, 'DOCX') + tr('srt', 'bilingual', `${t('exportSrtFile')} · ${t('exportBilingual')}`, 'SRT')
    + tr('vtt', 'bilingual', `${t('exportVttFile')} · ${t('exportBilingual')}`, 'VTT');
  if (isVideo) {
    html += item({ kind: 'video_soft', lang: trLang, variant: 'translated' }, t('exportVideoSoftTr'), t('exportTagVideo'), t('tipSubsSoft'))
      + item({ kind: 'video_burn', lang: trLang, variant: 'translated' }, t('exportVideoBurnTr'), t('exportTagVideo'), t('tipSubsBurn'));
  }

  const dubOptions = dubLangs.map(c => `<option value="${escapeHtml(c)}" ${c === dubLang ? 'selected' : ''}>${dubs.includes(c) ? '✓ ' : ''}${escapeHtml(dubLangName(c))}</option>`).join('');
  html += sep + header(t('exportGroupDub'), langSelect('export-dub-lang', 'setExportDubLang', dubOptions));
  if (!dubReady) html += note(t('exportDubWillRun'));
  const dubExt = dubReady ? String((availableDubs(m).find(d => d.lang === dubLang) || {}).path || '').split('.').pop().toUpperCase() : (isVideo ? 'MP4' : 'M4A');
  html += item({ kind: 'dub_media', lang: dubLang }, isVideo ? t('exportDubVideo') : t('exportDubAudio'), dubExt)
    + item({ kind: 'dub_srt', lang: dubLang }, t('exportDubSrt'), 'SRT');

  // A shorter copy of the recording (app/media_cut.py)
  html += sep + header(t('exportGroupCut'));
  if (!(m.segments || []).length) html += note(t('exportCutNeedsText'));
  else html += item({ kind: 'cut_clean' }, t('exportCutClean'), isVideo ? 'MP4' : 'M4A', t('tipCutClean'))
    + item({ kind: 'cut_highlights' }, t('exportCutHighlights'), isVideo ? 'MP4' : 'M4A', t('tipCutHighlights'))
    + item({ kind: 'cut_denoise' }, t('exportCutDenoise'), isVideo ? 'MP4' : 'M4A', t('tipCutDenoise'));

  const settings = (state.system && state.system.settings) || {};
  html += sep + header('Obsidian');
  html += item({ kind: 'obsidian' }, t('exportObsidian'), 'MD', settings.obsidian_vault ? settings.obsidian_vault : t('exportObsidianNoVault'));
  if (m.obsidian_path) html += note(t('exportObsidianSaved').replace('{name}', () => String(m.obsidian_path).split(/[\\/]/).pop()));

  html += sep + `<button data-click="runAll" data-click-args='[["hideExportMenu"], ["openExportDir"]]' class="macos-menu-item"><span>${escapeHtml(t('exportOpenFolder'))}</span></button>`;
  menu.innerHTML = html;
}

function setExportLang(lang) {
  state.exportLang = lang;
  renderExportMenu();
}

function setExportDubLang(lang) {
  state.exportDubLang = lang;
  renderExportMenu();
}

async function ctxClearResults() {
  hideContextMenu();
  const id = state.contextMeetingId;
  const m = state.meetings.find(x => x.id === id);
  if (!m || !(await confirmDialog(t('clearResultsTitle'), t('clearResultsText').replace('{title}', () => m.title), t('ctxClearResults')))) return;
  const res = await fetch(`/api/meetings/${id}/clear-results`, { method: 'POST' });
  if (!res.ok) { showError((await readJson(res)).detail); return; }
  await loadMeetingsList();
  if (state.activeMeeting && state.activeMeeting.id === id && state.pendingMeetingId == null) await selectMeeting(id, true);
}

async function ctxRemoveMedia() {
  hideContextMenu();
  const id = state.contextMeetingId;
  const m = state.meetings.find(x => x.id === id);
  if (!m || !(await confirmDialog(t('removeMediaTitle'), t('removeMediaText').replace('{title}', () => m.title), t('ctxRemoveMedia')))) return;
  const res = await fetch(`/api/meetings/${id}/remove-media`, { method: 'POST' });
  if (!res.ok) { showError((await readJson(res)).detail); return; }
  await loadMeetingsList();
  if (state.activeMeeting && state.activeMeeting.id === id && state.pendingMeetingId == null) await selectMeeting(id, true);
}

async function ctxCut(kind) {
  hideContextMenu();
  const id = state.contextMeetingId;
  if (!id) return;
  if (!state.activeMeeting || state.activeMeeting.id !== id) await selectMeeting(id, true);
  requestCut(kind);
}

async function requestCut(kind) {
  const m = state.activeMeeting;
  if (!m) return;
  if (kind === 'highlights') showToast(t('cutPicking'));
  const res = await fetch(`/api/meetings/${m.id}/cut`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ kind, lang: state.uiLang === 'en' ? 'en' : 'ru' }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) { showError(data.detail); return; }
  if (data.cancelled) return;
  const saved = Math.max(0, Math.round((data.duration || 0) - (data.kept_seconds || 0)));
  showToast(t('cutQueued').replace('{name}', () => data.filename).replace('{kept}', () => formatTime(data.kept_seconds || 0))
    + (kind === 'clean' && saved ? ` · −${formatTime(saved)}` : ''));
  await loadMeetingsList();
}

async function runExport(item) {
  hideExportMenu();
  const m = state.activeMeeting;
  if (!m) return;
  if (item.kind === 'obsidian') { await exportToObsidian(m.id); return; }
  if (item.kind === 'cut_clean' || item.kind === 'cut_highlights' || item.kind === 'cut_denoise') {
    await requestCut({ cut_clean: 'clean', cut_highlights: 'highlights', cut_denoise: 'denoise' }[item.kind]);
    return;
  }
  let res, data;
  try {
    res = await fetch(`/api/meetings/${m.id}/export-request`, {
      // the menu's options (time stamps, names, without fillers) go with an export written later too
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...item, opts: rpExportOptions() }),
    });
    data = await res.json().catch(() => ({}));
  } catch (e) {
    showError(t('exportFailed'));
    return;
  }
  if (!res.ok) { showToast(data.detail || t('exportFailed')); return; }
  if (data.status === 'needs_dub') {
    state.pendingDubExport = { kind: item.kind, lang: item.lang };
    openDubModal(item.lang);
    return;
  }
  if (data.status === 'queued') {
    const what = t(`exportWaiting_${data.waiting_for}`) || '';
    showToast(t('exportQueued').replace('{what}', () => what).replace('{dir}', () => data.folder || ''), { label: t('showInFolder'), onClick: () => revealPath(data.folder) });
    await loadMeetingsList();
    return;
  }
  // Everything the export needs is there: save it now, asking where
  if (item.kind === 'doc') await exportMeetingById(m.id, item.fmt, item.lang ? { lang: item.lang, variant: item.variant, menu: true } : { menu: true });
  else if (item.kind === 'video_soft' || item.kind === 'video_burn') await requestVideoSubtitles(item.lang || '', item.variant || 'translated', item.kind === 'video_soft' ? 'soft' : 'burn', true);
  else if (item.kind === 'dub_media') await saveDubFile(item.lang, 'media');
  else if (item.kind === 'dub_srt') await saveDubFile(item.lang, 'srt');
}

async function exportToObsidian(id) {
  const settings = (state.system && state.system.settings) || {};
  if (!settings.obsidian_vault) {
    showWarning(t('exportObsidianNoVault'));
    openModal('settings', 'export');
    return;
  }
  showToast(t('obsidianSaving'));
  try {
    const res = await fetch(`/api/meetings/${id}/obsidian`, { method: 'POST' });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { showToast(data.detail || t('exportFailed')); return; }
    if (state.activeMeeting && state.activeMeeting.id === id) state.activeMeeting.obsidian_path = data.path;
    showToast(`${t('obsidianSaved')} ${data.filename}`, { label: t('showInFolder'), onClick: () => revealPath(data.path) });
  } catch (e) {
    showError(t('exportFailed'));
  }
}

// An export that waited for a job has been written (or could not be)
function onExportedEvent(ev) {
  const files = ev.files || [];
  if (files.length) {
    const name = String(files[0]).split(/[\\/]/).pop();
    showToast(`${t('exportSavedTo')} ${name}${files.length > 1 ? ` (+${files.length - 1})` : ''}`,
      { label: t('showInFolder'), onClick: () => revealPath(files[0]) });
  } else if ((ev.queued || []).length) {
    showToast(t('subsBurnQueued').replace('{name}', () => ''));
  }
  if ((ev.errors || []).length) setTimeout(() => showToast(ev.errors.join('; ')), files.length ? 3000 : 0);
}

// --- Right-Click Context Menu on Sidebar Recording Items ---
// The ••• button of the recording header: the menu of the recording that is open
// The transcript Teams saves after a meeting (.vtt): a version of its own, and its names for the voices
function ctxImportTeamsVtt() {
  const id = state.contextMeetingId;
  hideContextMenu();
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.vtt,text/vtt';
  input.addEventListener('change', async () => {
    const file = input.files && input.files[0];
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    const res = await fetch(`/api/meetings/${id}/teams-transcript`, { method: 'POST', body: fd });
    const data = await readJson(res);
    if (!res.ok) { showError(serverText(data.detail)); return; }
    await loadMeetingsList();
    if (state.activeMeeting && state.activeMeeting.id === id) await selectMeeting(id, false);
    showToast(t('teamsVttDone').replace('{lines}', () => data.lines).replace('{named}', () => data.named), null, 'success');
  });
  input.click();
}

function openActiveRecordingMenu(e) {
  if (state.activeMeeting) openRecordingContextMenu(e, state.activeMeeting.id);
}

// Opened from the keyboard (Enter on «⋯», the menu key in «Записи»): a click of the keyboard has no point (0, 0)
function vxFromKeys(e) {
  return !!e && (!!e.vxKeys || e.type === 'keydown' || (e.type === 'click' && e.detail === 0)
    || (e.type === 'contextmenu' && !e.clientX && !e.clientY));
}
const vxCtx = { opener: null };  // what opened the recording's menu from the keyboard: the focus goes back to it

function openRecordingContextMenu(e, meetingId) {
  e.preventDefault();
  e.stopPropagation();
  // a submenu of the menu opened before (for another recording) must not stay at its old place
  closeSubmenus(false);
  document.getElementById('export-menu')?.classList.add('hidden');

  // Right-click on one of several selected recordings: the actions for all of them
  if (state.multi && state.multi.size > 1 && state.multi.has(meetingId)) { openBulkMenu(e); return; }
  if (state.multi && state.multi.size) clearLibSelection();
  state.contextMeetingId = meetingId;
  const m = state.meetings.find(x => x.id === meetingId);
  if (!m) return;

  document.getElementById('ctx-title-header').textContent = m.title;
  document.getElementById('ctx-cancel-item').classList.toggle('hidden', DONE_STATUSES.includes(m.status));
  const hasBackup = state.activeMeeting && state.activeMeeting.id === m.id && state.activeMeeting.has_segments_backup;
  document.getElementById('ctx-restore-item').classList.toggle('hidden', !hasBackup);
  document.getElementById('ctx-series-name').textContent = ((state.series || []).find(s => s.id === m.series_id) || {}).name || '';
  const menu = document.getElementById('recording-context-menu');
  menu.classList.remove('hidden');

  if (!vxFromKeys(e)) { vxCtx.opener = null; placeMenuAt(menu, e); return; }
  // from the keyboard: under the button (or the row) that opened it, above it where it does not fit below; the
  // focus on its first item, so ↑ ↓ → ← Esc work at once
  const t0 = e.target instanceof Element ? e.target : null;
  const opener = e.vxOpener || (t0 && t0.closest('button, [tabindex]')) || document.activeElement;
  const anchor = e.vxAnchor || (opener instanceof Element && opener !== document.body ? opener : null);
  if (anchor) {
    const r = anchor.getBoundingClientRect(), h = menu.offsetHeight * uiZoom();
    placeMenuAt(menu, { clientX: r.left, clientY: r.bottom + 4 + h <= window.innerHeight - 8 ? r.bottom + 4 : r.top - 4 });
  } else placeMenuAt(menu, e);
  vxCtx.opener = opener instanceof HTMLElement && opener !== document.body ? opener : null;
  vxSubItems(menu)[0]?.focus({ preventScroll: true });
}

function openBulkMenu(e) {
  document.getElementById('bulk-menu')?.remove();
  const menu = document.createElement('div');
  menu.id = 'bulk-menu';
  menu.className = 'fixed w-56 macos-menu z-50';
  const item = (fn, label, cls = '') => `<button class="macos-menu-item ${cls}" data-fn="${fn}"><span>${escapeHtml(label)}</span></button>`;
  menu.innerHTML = `<div class="px-2.5 py-1 text-[11.5px] font-semibold text-apple-secondary border-b border-white/10 mb-1">${escapeHtml(t('libSelected').replace('{n}', () => state.multi.size))}</div>`
    + item('bulkRename', t('bulkRename') + '…') + item('bulkAutoTitles', t('bulkAutoTitle'))
    + '<div class="my-1 h-px bg-white/10"></div>' + item('bulkDelete', t('ctxDelete'), 'text-apple-red');
  menu.addEventListener('click', ev => {
    const b = ev.target.closest('button[data-fn]');
    if (!b) return;
    menu.remove();
    callPage(b.dataset.fn);
  });
  document.body.appendChild(menu);
  placeMenuAt(menu, e);
  setTimeout(() => document.addEventListener('click', () => menu.remove(), { once: true }), 0);
}

// --- Series menu of a recording ---
state.series = [];

async function loadSeries() {
  state.series = await fetch('/api/series').then(r => r.ok ? r.json() : []).catch(() => []);
}

async function openSeriesMenu(e) {
  e.stopPropagation();
  const m = state.meetings.find(x => x.id === state.contextMeetingId);
  hideContextMenu();
  if (!m) return;
  await loadSeries();
  document.getElementById('series-menu')?.remove();
  const menu = document.createElement('div');
  menu.id = 'series-menu';
  menu.className = 'fixed w-60 max-h-80 overflow-y-auto macos-menu z-50';
  menu.innerHTML = `<div class="px-2.5 py-1 text-[11px] text-apple-tertiary">${escapeHtml(t('ctxSeries'))}</div>`
    + state.series.map(s => `<button class="macos-menu-item" data-sid="${s.id}"><span class="truncate">${escapeHtml(s.name)}</span><span class="text-[11px] opacity-70">${m.series_id === s.id ? '✓' : s.count}</span></button>`).join('')
    + `<button class="macos-menu-item" data-sid="new"><span>${escapeHtml(t('seriesNew'))}</span></button>`
    + (m.series_id ? `<button class="macos-menu-item" data-sid="rename"><span>${escapeHtml(t('seriesRename'))}</span></button>`
      + `<button class="macos-menu-item" data-sid="none"><span>${escapeHtml(t('seriesRemove'))}</span></button>` : '');
  menu.addEventListener('click', async (ev) => {
    const b = ev.target.closest('button[data-sid]');
    ev.stopPropagation();
    if (!b) return;
    menu.remove();
    let body = { series_id: null };
    if (b.dataset.sid === 'rename') {
      const cur = state.series.find(s => s.id === m.series_id);
      const name = (await askText(t('seriesNamePrompt'), cur ? cur.name : '') || '').trim();
      if (!name) return;
      const r = await fetch(`/api/series/${m.series_id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
      if (!r.ok) { showToast(errorText(await readJson(r), r)); return; }
      await loadSeries();
      if (state.activeMeeting && state.activeMeeting.series_id === m.series_id) renderSeriesUi();
      return;
    }
    if (b.dataset.sid === 'new') {
      const name = (await askText(t('seriesNamePrompt'), m.title) || '').trim();
      if (!name) return;
      body = { new_name: name };
    } else if (b.dataset.sid !== 'none') body = { series_id: Number(b.dataset.sid) };
    const res = await fetch(`/api/meetings/${m.id}/series`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!res.ok) return;
    const data = await readJson(res);
    if (state.activeMeeting && state.activeMeeting.id === m.id) { state.activeMeeting.series_id = data.series_id; renderSeriesUi(); }
    await loadMeetingsList();
    loadSeries();
  });
  document.body.appendChild(menu);
  placeMenuAt(menu, e);
}

document.addEventListener('click', () => document.getElementById('series-menu')?.remove());

// «Сведения» and «Переместить в папку» of the recording menu (they were only in the top bar's own menu)
async function ctxOpenInfo() {
  const id = state.contextMeetingId;
  hideContextMenu();
  if (!state.activeMeeting || state.activeMeeting.id !== id) await openMeeting(id);
  rpOpenInfo();
}
function ctxMoveToFolder(e) {
  const m = state.meetings.find(x => x.id === state.contextMeetingId);
  const r = document.getElementById('recording-context-menu').getBoundingClientRect();
  hideContextMenu();
  if (m) openMoveRecordMenu(m, { right: r.right, bottom: r.top - 4 + Math.min(r.height, 60) });
}

// The submenu closes without taking the focus to its row (the menu is going); the focus in the menu goes back to
// what opened it from the keyboard (it fell to the page)
function hideContextMenu() {
  const menu = document.getElementById('recording-context-menu');
  const f = document.activeElement;
  const inside = !!f && f !== document.body && (!!menu?.contains(f) || !!vxSub.menu?.contains(f));
  closeSubmenus(false);
  if (menu) hideWithExit(menu);
  const back = vxCtx.opener;
  vxCtx.opener = null;
  if (inside && back && back.isConnected) back.focus({ preventScroll: true });
}

// --- Submenus: a row of a menu with data-submenu="<id>" (and a «›» in the place of the shortcut) opens the menu
// of that id beside it — the recording's «Экспорт ›», «Нарезка ›», «Ещё ›». It opens on a short hover, a click,
// Enter, Space or →, which also moves the focus into it; ←, Esc (the layer «vx-submenu» in static/js/core.js) and
// leaving it close it. It stands to the right of its menu, or to the left where there is no room, and inside the
// window. The submenu is a separate element after its menu (not inside it: the menu scrolls in a low window and
// would cut it off). One submenu is open at a time
// While a submenu is open, a move over another row switches only after a pause, and not while the pointer heads for
// the open submenu (inside the triangle from where it was to the submenu's near edge): the way from «Экспорт ›» to
// its items crosses «Нарезка ›»
const VX_SUB_OPEN_MS = 180, VX_SUB_CLOSE_MS = 300, VX_SUB_AIM_MS = 400;
const vxSub = { trigger: null, menu: null, openT: 0, closeT: 0, want: null, pts: [] };

function vxSubItems(menu) {
  return [...menu.querySelectorAll('button.macos-menu-item')].filter(b => !b.classList.contains('hidden') && !b.disabled);
}

function openSubmenu(trigger, focusFirst) {
  clearTimeout(vxSub.openT);
  clearTimeout(vxSub.closeT);
  vxSub.want = null;
  const sub = document.getElementById(trigger.dataset.submenu);
  const parent = trigger.closest('.macos-menu');
  if (!sub || !parent || parent.classList.contains('hidden')) return;
  if (vxSub.trigger !== trigger) closeSubmenus();
  sub.classList.remove('hidden');
  trigger.setAttribute('aria-expanded', 'true');
  vxSub.trigger = trigger;
  vxSub.menu = sub;
  placeSubmenu(sub, trigger, parent);
  if (focusFirst) vxSubItems(sub)[0]?.focus();
}

// Beside the row: its first item level with the row, to the right of the menu or, where it does not fit, to the left
function placeSubmenu(sub, trigger, parent) {
  sub.style.maxHeight = '';
  sub.style.overflowY = '';
  const W = window.innerWidth, H = window.innerHeight, m = 8;
  const p = parent.getBoundingClientRect(), t = trigger.getBoundingClientRect();
  // the sizes of the layout, not of the box on screen: the submenu is drawn scaled down as it appears (vx-pop)
  const z = uiZoom();
  const size = () => ({ width: sub.offsetWidth * z, height: sub.offsetHeight * z });
  let r = size();
  if (r.height > H - 2 * m) {
    sub.style.maxHeight = `${zpx(H - 2 * m)}px`;
    sub.style.overflowY = 'auto';
    r = size();
  }
  const first = sub.querySelector('.macos-menu-item');
  const inset = first ? first.offsetTop * z : 0;
  let left = p.right - 2, toLeft = false;
  if (left + r.width > W - m) {
    toLeft = p.left - r.width + 2 >= m;
    left = toLeft ? p.left - r.width + 2 : Math.max(m, W - m - r.width);
  }
  const top = Math.max(m, Math.min(t.top - inset, H - m - r.height));
  sub.style.left = `${zpx(left)}px`;
  sub.style.top = `${zpx(top)}px`;
  sub.style.transformOrigin = `${toLeft ? 'right' : 'left'} top`;
}

// back: the focus that was in the submenu goes to its row (not when the menu itself is closing: hideContextMenu)
function closeSubmenus(back = true) {
  clearTimeout(vxSub.openT);
  clearTimeout(vxSub.closeT);
  vxSub.want = null;
  const { trigger, menu } = vxSub;
  vxSub.trigger = vxSub.menu = null;
  if (!menu) return;
  const hadFocus = menu.contains(document.activeElement);
  menu.classList.add('hidden');
  if (!trigger) return;
  trigger.setAttribute('aria-expanded', 'false');
  if (back !== false && hadFocus && trigger.isConnected && !trigger.closest('.hidden, .is-leaving')) trigger.focus();
}

function vxSubCloseSoon() {
  clearTimeout(vxSub.closeT);
  vxSub.closeT = setTimeout(closeSubmenus, VX_SUB_CLOSE_MS);
}

// The row the pointer is over while another row's submenu is open: its submenu (or none) after `ms`
function vxSubSwitchSoon(row, ms) {
  clearTimeout(vxSub.openT);
  clearTimeout(vxSub.closeT);
  vxSub.want = row;
  vxSub.openT = setTimeout(() => {
    vxSub.want = null;
    if (row.dataset.submenu && row.isConnected) openSubmenu(row, false); else closeSubmenus();
  }, ms);
}

// Is the pointer at (x, y) heading for the open submenu: inside the triangle from where it was a moment ago to the
// submenu's near edge (a little taller than the submenu, for a hand that is not exact)
function vxSubAiming(x, y) {
  const sub = vxSub.menu, parent = vxSub.trigger?.closest('.macos-menu');
  if (!sub || !parent) return false;
  const now = performance.now();
  const from = vxSub.pts.find(p => now - p.t < 200 && (p.x !== x || p.y !== y));
  if (!from) return false;
  const s = sub.getBoundingClientRect(), p = parent.getBoundingClientRect();
  const right = s.left >= p.left + p.width / 2;
  if (right ? x <= from.x : x >= from.x) return false;
  const ex = right ? s.left : s.right;
  const A = from, B = { x: ex, y: s.top - 8 }, C = { x: ex, y: s.bottom + 8 };
  const cross = (a, b) => (b.x - a.x) * (y - a.y) - (b.y - a.y) * (x - a.x);
  const d = [cross(A, B), cross(B, C), cross(C, A)];
  return !(d.some(v => v < 0) && d.some(v => v > 0));
}

// ↑ ↓ move along the items (of a menu or a submenu), → Enter Space on a row with a submenu open it, ← in a submenu
// goes back to its row
function vxMenuKeys(e, menu, trigger) {
  const at = document.activeElement;
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    const items = vxSubItems(menu);
    if (!items.length) return;
    e.preventDefault();
    e.stopPropagation();
    const i = items.indexOf(at), n = items.length, down = e.key === 'ArrowDown';
    items[i < 0 ? (down ? 0 : n - 1) : (i + (down ? 1 : n - 1)) % n].focus();
  } else if (at && at.dataset && at.dataset.submenu && menu.contains(at) && ['ArrowRight', 'Enter', ' '].includes(e.key)) {
    e.preventDefault();
    e.stopPropagation();
    openSubmenu(at, true);
  } else if (trigger && e.key === 'ArrowLeft') {
    e.preventDefault();
    e.stopPropagation();
    closeSubmenus();
  }
}

function vxSubmenus(menu) {
  if (!menu || menu._vxSubmenus) return;
  menu._vxSubmenus = true;
  menu.addEventListener('pointermove', (e) => {
    vxSub.pts.push({ x: e.clientX, y: e.clientY, t: performance.now() });
    if (vxSub.pts.length > 8) vxSub.pts.shift();
    // still heading for the open submenu over another row: the switch waits on
    if (vxSub.want && vxSub.menu && vxSubAiming(e.clientX, e.clientY)) vxSubSwitchSoon(vxSub.want, VX_SUB_AIM_MS);
  });
  menu.addEventListener('pointerover', (e) => {
    const row = e.target.closest('.macos-menu-item');
    if (!row || !menu.contains(row)) return;
    if (vxSub.menu) {
      if (vxSub.trigger === row) { clearTimeout(vxSub.openT); clearTimeout(vxSub.closeT); vxSub.want = null; return; }
      if (vxSub.want === row) return;  // a part of the same row: its pause runs on
      vxSubSwitchSoon(row, vxSubAiming(e.clientX, e.clientY) ? VX_SUB_AIM_MS : row.dataset.submenu ? VX_SUB_OPEN_MS : VX_SUB_CLOSE_MS);
      return;
    }
    clearTimeout(vxSub.openT);
    if (row.dataset.submenu) vxSub.openT = setTimeout(() => openSubmenu(row, false), VX_SUB_OPEN_MS);
  });
  menu.addEventListener('pointerleave', (e) => {
    clearTimeout(vxSub.openT);
    vxSub.want = null;
    if (vxSub.menu && !vxSub.menu.contains(e.relatedTarget)) vxSubCloseSoon();
  });
  // the menu scrolling in a low window (vxFitInView): the submenu follows its row, or closes once the row is out of sight
  // (once a frame, and again at the end of a smooth scroll)
  let follow = 0;
  const followRow = () => {
    follow = 0;
    const { trigger, menu: sub } = vxSub;
    if (!sub || !trigger || !menu.contains(trigger)) return;
    const m = menu.getBoundingClientRect(), r = trigger.getBoundingClientRect();
    if (r.bottom <= m.top || r.top >= m.bottom) closeSubmenus(); else placeSubmenu(sub, trigger, menu);
  };
  menu.addEventListener('scroll', () => { if (!follow) follow = requestAnimationFrame(followRow); }, { passive: true });
  menu.addEventListener('scrollend', followRow, { passive: true });
  menu.addEventListener('click', (e) => {
    const row = e.target.closest('[data-submenu]');
    if (row && menu.contains(row)) openSubmenu(row, e.detail === 0);
  });
  menu.addEventListener('keydown', (e) => vxMenuKeys(e, menu, null));
  for (const trigger of menu.querySelectorAll('[data-submenu]')) {
    const sub = document.getElementById(trigger.dataset.submenu);
    if (!sub || sub._vxSubmenu) continue;
    sub._vxSubmenu = true;
    sub.addEventListener('pointerenter', () => { clearTimeout(vxSub.closeT); clearTimeout(vxSub.openT); vxSub.want = null; });
    sub.addEventListener('pointerleave', (e) => { if (vxSub.menu === sub && !trigger.contains(e.relatedTarget)) vxSubCloseSoon(); });
    sub.addEventListener('keydown', (e) => vxMenuKeys(e, sub, trigger));
  }
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => vxSubmenus(document.getElementById('recording-context-menu')));
else vxSubmenus(document.getElementById('recording-context-menu'));

document.addEventListener('click', () => {
  hideContextMenu();
  hideFolderMenu();
  document.getElementById('export-menu')?.classList.add('hidden');
  hideTranslateMenu();
  hideTxViewMenu();
  hideRecordPresetMenu();
});

function toggleTranslateMenu(e) {
  e.stopPropagation();
  hideContextMenu();
  document.getElementById('export-menu')?.classList.add('hidden');
  document.getElementById('translate-menu').classList.toggle('hidden');
}

// One click (the chips in the transcript toolbar): shows the translation, or makes it
async function quickTranslate(lang) {
  hideTranslateMenu();
  const m = state.activeMeeting;
  if (!m) return;
  if (meetingTranslations(m)[lang]) {
    state.txLang = lang;
    setTranscriptView(state.txView === 'orig' || !state.txView ? 'both' : state.txView);
    return;
  }
  await startTranslation(false, lang);
}

function hideTranslateMenu() {
  document.getElementById('translate-menu')?.classList.add('hidden');
}

async function ctxRenameRecording() {
  hideContextMenu();
  const m = state.meetings.find(x => x.id === state.contextMeetingId);
  if (!m) return;
  const newTitle = await askText(t('uiNewRecordingTitle'), m.title);
  if (!newTitle || !newTitle.trim() || newTitle.trim() === m.title) return;

  const res = await fetch(`/api/meetings/${m.id}/title`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title: newTitle.trim() })
  });
  if (!res.ok) { showError((await readJson(res)).detail); return; }
  await loadMeetingsList();
  if (state.activeMeeting && state.activeMeeting.id === m.id) {
    state.activeMeeting.title = newTitle.trim();
    document.getElementById('meeting-title-input').value = newTitle.trim();
  }
}

function ctxOpenReconfigureModal() {
  hideContextMenu();
  const m = state.meetings.find(x => x.id === state.contextMeetingId);
  if (!m) return;

  document.getElementById('reconfig-recording-name').textContent = m.title;
  const modelSel = document.getElementById('reconfig-model');
  modelSel.value = m.model_name || 'large-v3-turbo';
  if (!modelSel.value && modelSel.options.length) modelSel.selectedIndex = 0;  // a removed model
  renderModelHints();
  document.getElementById('reconfig-language').value = m.language || 'auto';
  document.getElementById('reconfig-speakers').value = String(m.num_speakers_hint || 0);
  openModal('reconfigure');
}

async function submitReconfigure() {
  const id = state.contextMeetingId;
  if (!id) return;
  const res = await fetch(`/api/meetings/${id}/reconfigure`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model_name: document.getElementById('reconfig-model').value,
      language: document.getElementById('reconfig-language').value,
      num_speakers_hint: Number(document.getElementById('reconfig-speakers').value || 0),
    })
  }).catch(() => null);
  // refused (the recording is busy, no model): said, and the window stays with its choices (it said «Запущена
  // повторная обработка» whatever the answer: audit)
  if (!res || !res.ok) { showError(res ? errorText(await readJson(res), res) : t('errorGeneric')); return; }
  closeModal('reconfigure');
  await loadMeetingsList();
  await selectMeeting(id, false);
  showToast(t('uiReProcessingStarted'));
}

async function ctxCancelProcessing() {
  hideContextMenu();
  if (state.contextMeetingId) await cancelProcessing(state.contextMeetingId);
}

async function ctxRestoreSegments() {
  hideContextMenu();
  if (state.contextMeetingId) await restoreSegments(state.contextMeetingId);
}

async function restoreSegments(id) {
  const res = await fetch(`/api/meetings/${id}/restore-segments`, { method: 'POST' });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showError(data.detail);
    return;
  }
  if (state.activeMeeting && state.activeMeeting.id === id) {
    state.activeMeeting = data;
    renderTranscript();
    renderSpeakersPanel();
  }
  showToast(t('uiOriginalTextRestored'));
}

async function ctxRevealInExplorer() {
  hideContextMenu();
  if (!state.contextMeetingId) return;
  await fetch(`/api/meetings/${state.contextMeetingId}/reveal`, { method: 'POST' });
}

async function ctxExport(fmt) {
  hideContextMenu();
  if (!state.contextMeetingId) return;
  await exportMeetingById(state.contextMeetingId, fmt);
}

// Delete confirmation for one or several recordings: what is always deleted, and the files on the
// disk that can go too (the source used in place, saved exports, the Obsidian note)
function confirmDeleteDialog(list) {
  if (!Array.isArray(list)) list = [list];
  return new Promise(resolve => {
    const sources = list.filter(m => m.source === 'local');
    const exportsN = list.reduce((n, m) => n + (m.exports || []).length, 0);
    const notes = list.filter(m => m.obsidian_path);
    const opt = (id, label, detail) => `<label class="flex items-start gap-2.5 cursor-pointer text-xs text-apple-label">
        <input type="checkbox" id="${id}" class="del-opt mt-0.5 rounded bg-apple-sidebar border-white/20 text-apple-red" />
        <span>${escapeHtml(label)}${detail ? `<span class="block text-[11.5px] text-apple-tertiary mt-0.5 break-all line-clamp-2">${escapeHtml(detail)}</span>` : ''}</span></label>`;
    const options = [
      sources.length ? opt('del-with-source', t('deleteWithSource'), sources.map(m => m.filename).join(', ')) : '',
      exportsN ? opt('del-with-exports', t('deleteWithExports').replace('{n}', () => exportsN), list.flatMap(m => m.exports || []).slice(0, 3).join(', ')) : '',
      notes.length ? opt('del-with-note', t('deleteWithNote').replace('{n}', () => notes.length), notes.map(m => m.obsidian_path).slice(0, 2).join(', ')) : '',
    ].filter(Boolean);
    const what = list.length === 1 ? t('confirmDeleteOne').replace('{title}', () => list[0].title) : t('confirmDeleteMany').replace('{n}', () => list.length);
    const wrap = document.createElement('div');
    wrap.className = 'fixed inset-0 modal-backdrop z-[70] flex items-center justify-center p-4';
    // a dialog for screen readers and the focus trap of the page (it was a plain block: audit)
    wrap.setAttribute('role', 'dialog');
    wrap.setAttribute('aria-modal', 'true');
    wrap.setAttribute('aria-labelledby', 'del-dlg-title');
    wrap.innerHTML = `<div class="w-full max-w-md bg-apple-card border apple-border rounded-2xl shadow-2xl p-5 space-y-4 modal-card">
      <div id="del-dlg-title" class="text-sm font-semibold text-white">${escapeHtml(t('deleteTitle'))}</div>
      <p class="text-xs text-apple-secondary leading-relaxed">${escapeHtml(what)}</p>
      <p class="text-[11.5px] text-apple-tertiary leading-relaxed">${escapeHtml(t('deleteAlways'))}</p>
      ${options.length ? `<div class="space-y-2.5"><div class="text-[11.5px] text-apple-secondary">${escapeHtml(t('deleteAlsoFiles'))}</div>${options.join('')}</div>` : ''}
      <div class="flex justify-end gap-2">
        ${options.length > 1 ? `<button data-a="all" class="ui-btn ui-btn-subtle mr-auto">${escapeHtml(t('deleteSelectAll'))}</button>` : ''}
        <button data-a="no" class="ui-btn ui-btn-subtle">${escapeHtml(t('cancel'))}</button>
        <button data-a="yes" class="ui-btn bg-apple-red text-white hover:opacity-90">${escapeHtml(t('ctxDelete'))}</button>
      </div></div>`;
    const done = (v) => { wrap.remove(); document.removeEventListener('keydown', onKey, true); resolve(v); };
    const onKey = (e) => { if (e.key === 'Escape') { e.stopPropagation(); done(null); } };
    const checked = id => !!wrap.querySelector('#' + id)?.checked;
    wrap.addEventListener('click', (e) => {
      const a = e.target.closest('button[data-a]');
      if (e.target === wrap || (a && a.dataset.a === 'no')) done(null);
      else if (a && a.dataset.a === 'all') wrap.querySelectorAll('.del-opt').forEach(c => { c.checked = true; });
      else if (a) done({ withSource: checked('del-with-source'), withExports: checked('del-with-exports'), withNote: checked('del-with-note') });
    });
    document.addEventListener('keydown', onKey, true);
    document.body.appendChild(wrap);
    wrap.querySelector('button[data-a="no"]').focus();  // Enter after Delete must not remove recordings
  });
}

// The query of DELETE /api/meetings/{id} for the options chosen in the dialog
function deleteQuery(choice, m) {
  const q = new URLSearchParams();
  if (choice.withSource && m.source === 'local') q.set('with_source', 'true');
  if (choice.withExports) q.set('with_exports', 'true');
  if (choice.withNote) q.set('with_note', 'true');
  const s = q.toString();
  return s ? `?${s}` : '';
}

async function ctxDeleteRecording() {
  hideContextMenu();
  const m = state.meetings.find(x => x.id === state.contextMeetingId);
  if (!m) return;
  const choice = await confirmDeleteDialog(m);
  if (!choice) return;

  const delRes = await fetch(`/api/meetings/${m.id}${deleteQuery(choice, m)}`, { method: 'DELETE' });
  if (!delRes.ok) {
    const data = await delRes.json().catch(() => ({}));
    showError(data.detail);
    await loadMeetingsList();
    return;
  }
  if (state.activeMeeting && state.activeMeeting.id === m.id) {
    state.activeMeeting = null;
    document.getElementById('workspace-content').classList.add('hidden');
    document.getElementById('workspace-empty').classList.remove('hidden');
    leaveDeletedRecording();
  }
  await loadMeetingsList();
  // its tracks are being mixed: it goes as soon as the mix is over (the server says so)
  const done = await delRes.json().catch(() => ({}));
  if (done.later) showToast(serverText(done.detail) || t('mixDeleting'));
  else showToast(t('uiRecordingDeleted'), null, 'success');
}
