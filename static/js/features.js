// --- Features (app/features.py): a tag across the library. A meeting may be about several (most
// often one); its tasks belong to its features. The analysis model may suggest some: greyed, with
// ✓ / ✕, nothing is put on a meeting until the user accepts it ---

async function loadFeatures() {
  try {
    const res = await fetch('/api/features');
    if (res.ok) state.features = await readJson(res);
  } catch (e) { /* the list stays as it was */ }
}

function featureById(id) { return (state.features || []).find(f => f.id === Number(id)); }

// A tag of a feature: its colour as a dot and a tint; `opts.suggested` greyed with a question mark
function featureChipHtml(f, opts = {}) {
  if (!f) return '';
  const c = /^#[0-9A-Fa-f]{6}$/.test(f.color || '') ? f.color : '#8E8E93';
  return `<span class="ft-chip${opts.suggested ? ' ft-chip-suggested' : ''}" style="--ft:${c}" title="${escapeHtml(opts.title || f.name)}">`
    + `<span class="ft-dot"></span><span class="ft-name">${escapeHtml(f.name)}${opts.suggested ? '?' : ''}</span></span>`;
}

// The features of the open recording next to its title: its own, the model's suggestions, «+ фича»
function renderMeetingFeatures() {
  const box = document.getElementById('meeting-features');
  const m = state.activeMeeting;
  if (!box) return;
  if (!m) { box.innerHTML = ''; return; }
  const own = (m.features || []).map(featureById).filter(Boolean);
  const guesses = (m.feature_suggestions || []).map(featureById).filter(Boolean);
  // two at most next to the title, «+N» for the rest (the header has no room for more)
  const shown = own.slice(0, 2), more = own.length - shown.length;
  // «Фича:» says what the chips are (a coloured chip alone read as any tag)
  box.innerHTML = `<span class="ft-label">${escapeHtml(t('ftLabel'))}</span>` + shown.map(f => `<button class="ft-chip-btn" data-ft="${f.id}" ${pageCall('click', 'openFeaturePicker', [{ $: 'event' }])} title="${escapeHtml(t('ftChangeTip'))}">${featureChipHtml(f)}</button>`).join('')
    + (more > 0 ? `<button class="ft-chip-btn ft-more" ${pageCall('click', 'openFeaturePicker', [{ $: 'event' }])} title="${escapeHtml(own.map(f => f.name).join(', '))}">+${more}</button>` : '')
    + guesses.map(f => `<span class="ft-suggest">${featureChipHtml(f, { suggested: true, title: t('ftSuggestedTip') })}
        <button class="ft-yes" ${pageCall('click', 'acceptFeatureSuggestion', [f.id])} title="${escapeHtml(t('ftAccept'))}" aria-label="${escapeHtml(t('ftAccept'))}">✓</button>
        <button class="ft-no" ${pageCall('click', 'declineFeatureSuggestion', [f.id])} title="${escapeHtml(t('ftDecline'))}" aria-label="${escapeHtml(t('ftDecline'))}">✕</button></span>`).join('')
    + (own.length ? '' : `<button class="ft-add" ${pageCall('click', 'openFeaturePicker', [{ $: 'event' }])} title="${escapeHtml(t('ftAddTip'))}">+ ${escapeHtml(t('ftAddShort'))}</button>`);
}

function applyMeetingFeatures(m, data) {
  m.features = data.features || [];
  m.feature_suggestions = data.feature_suggestions || [];
  const row = (state.meetings || []).find(x => x.id === m.id);
  if (row) { row.features = m.features; row.feature_suggestions = m.feature_suggestions; }
  renderMeetingFeatures();
  scheduleSidebarRender();
  if (state.activeSummaryTab === 'commitments' && typeof renderSummaryPanel === 'function') renderSummaryPanel();
}

async function saveMeetingFeatures(ids, forSeries = false) {
  const m = state.activeMeeting;
  if (!m) return;
  const res = await fetch(`/api/meetings/${m.id}/features`, { method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ids, for_series: forSeries }) });
  const data = await readJson(res);
  if (!res.ok) { showError(data.detail); return; }
  await loadFeatures();  // a feature just made is known before the header draws its chip
  applyMeetingFeatures(m, data);
  if (document.getElementById('tk-pop')) drawFeaturePicker();
}

async function acceptFeatureSuggestion(id) {
  const m = state.activeMeeting;
  const res = await fetch(`/api/meetings/${m.id}/feature-suggestions/${id}`, { method: 'POST' });
  if (res.ok) applyMeetingFeatures(m, await readJson(res));
}

async function declineFeatureSuggestion(id) {
  const m = state.activeMeeting;
  const res = await fetch(`/api/meetings/${m.id}/feature-suggestions/${id}`, { method: 'DELETE' });
  if (res.ok) applyMeetingFeatures(m, await readJson(res));
}

// The picker: every feature with a tick, a field for a new one, and «for the whole series»
let _ftAnchor = null;
function openFeaturePicker(e) {
  e.stopPropagation();
  _ftAnchor = e.currentTarget;
  loadFeatures().then(drawFeaturePicker);
}

function drawFeaturePicker() {
  const m = state.activeMeeting;
  if (!m || !_ftAnchor) return;
  // the header's chips were drawn anew (a feature added or taken off): the picker stays by them, not at
  // the top left corner where a button no longer on the page puts it
  if (!_ftAnchor.isConnected) {
    _ftAnchor = [...document.querySelectorAll('#meeting-features [data-click="openFeaturePicker"]')].find(b => b.offsetParent) || null;
    if (!_ftAnchor) { if (typeof tkClosePop === 'function') tkClosePop(); return; }
  }
  const on = new Set(m.features || []);
  // the page link is a button of its own beside the item, not inside it (a button in a button: no keyboard)
  // a feature of the recording is framed, with its box ticked on the left (a small tick on the right was not
  // seen: reported by the user)
  const list = (state.features || []).map(f => `<div class="ft-pick-row${on.has(f.id) ? ' ft-pick-on' : ''}"><button class="tk-pop-item" role="menuitemcheckbox" aria-checked="${on.has(f.id)}" ${pageCall('click', 'toggleMeetingFeature', [f.id])}>
      <span class="ft-pick-box" aria-hidden="true">${on.has(f.id) ? '✓' : ''}</span>${featureChipHtml(f)}<span class="tk-grow"></span><span class="tk-dim">${f.count || 0}</span></button>
      <button class="ft-open" ${pageCall('click', 'openFeaturePageFromPick', [f.id, { $: 'event' }])} title="${escapeHtml(t('fpOpenTip'))}" aria-label="${escapeHtml(t('fpOpenTip'))}">↗</button></div>`).join('');
  const series = m.series_id ? `<label class="ft-series"><input type="checkbox" id="ft-for-series" ${pageCall('change', 'saveFeaturesForSeries')}>
      <span>${escapeHtml(t('ftForSeries'))}</span></label>` : '';
  tkOpenPop(`<div class="tk-pop-cap">${escapeHtml(t('ftPickTitle'))}</div>${list || `<div class="tk-pop-quote">${escapeHtml(t('ftNone'))}</div>`}
    <div class="tk-pop-add"><div class="tk-row2">
      <input id="ft-new-name" class="tk-input" type="text" maxlength="60" placeholder="${escapeHtml(t('ftNewPh'))}" title="${escapeHtml(t('ftNewPh'))}" ${pageCall('keydown', 'onNewFeatureKey', [{ $: 'event' }])}>
      <button class="tk-btn tk-btn-primary tk-btn-sm" ${pageCall('click', 'createFeatureFromPicker')}>${escapeHtml(t('ftCreate'))}</button></div>${series}</div>`, _ftAnchor, 300);
}

// A click chooses and closes the list (asked by the user: after a click it was not clear the feature was
// chosen): the feature added lights up in the header; another one is added by opening the list again
async function toggleMeetingFeature(id) {
  const m = state.activeMeeting;
  const ids = new Set(m.features || []);
  const adding = !ids.has(id);
  if (adding) ids.add(id); else ids.delete(id);
  const series = !!document.getElementById('ft-for-series')?.checked;
  if (typeof tkClosePop === 'function') tkClosePop();
  _ftAnchor = null;
  await saveMeetingFeatures([...ids], series);
  if (adding) flashMeetingFeature(id);
}

function flashMeetingFeature(id) {
  const chip = document.querySelector(`#meeting-features [data-ft="${id}"]`) || document.querySelector('#meeting-features .ft-more');
  if (!chip) return;
  chip.classList.remove('ft-flash');
  void chip.offsetWidth;  // the animation starts again
  chip.classList.add('ft-flash');
}

function saveFeaturesForSeries() {
  const m = state.activeMeeting;
  if (document.getElementById('ft-for-series')?.checked) saveMeetingFeatures(m.features || [], true);
}

function onNewFeatureKey(e) {
  if (e.key === 'Enter') { e.preventDefault(); createFeatureFromPicker(); }
}

async function createFeatureFromPicker() {
  const input = document.getElementById('ft-new-name');
  const name = (input?.value || '').trim();
  if (!name) { input?.focus(); return; }
  const res = await fetch('/api/features', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
  const f = await readJson(res);
  if (!res.ok) { showError(f.detail); return; }
  const m = state.activeMeeting;
  const series = !!document.getElementById('ft-for-series')?.checked;
  if (typeof tkClosePop === 'function') tkClosePop();
  _ftAnchor = null;
  await saveMeetingFeatures([...new Set([...(m.features || []), f.id])], series);
  flashMeetingFeature(f.id);
}

// The tags of a task: the features of its meeting (tasks are not tagged one by one)
// One chip (the first feature) and «+N», the whole list in its tip: a task card keeps one line for it
function taskFeatureChipsHtml(meetingId, ids) {
  const list = (ids || ((state.meetings || []).find(x => x.id === meetingId) || {}).features || []).map(featureById).filter(Boolean);
  if (!list.length) return '';
  const all = list.map(f => f.name).join(', ');
  return `<button type="button" class="ft-compact" ${pageCall('click', 'openFeaturePage', [list[0].id])}>${featureChipHtml(list[0], { title: all })}${list.length > 1 ? `<span class="ft-more" title="${escapeHtml(all)}">+${list.length - 1}</span>` : ''}</button>`;
}

// --- Словарь → Фичи: what each feature is. Every field has a use: keywords find it in a meeting's
// title, the description tells the models what it is, the terms are written right by recognition
// and by the models; none is required ---
const FT_COLORS = ['#64B5FF', '#BF5AF2', '#30D158', '#FF9F0A', '#FF6482', '#5AC8FA', '#FFD60A', '#AC8E68'];

async function renderDictFeatures() {
  const box = document.getElementById('ft-dict-list');
  if (!box) return;
  await loadFeatures();
  const list = state.features || [];
  const sw = f => FT_COLORS.map(c => `<button class="ft-swatch${(f.color || '').toUpperCase() === c ? ' ft-swatch-on' : ''}" style="--ft:${c}"
      ${pageCall('click', 'saveDictFeature', [f.id, 'color', c])} aria-label="${escapeHtml(c)}" title="${escapeHtml(t('ftColor'))}"></button>`).join('');
  const field = (f, key, label, hint, rows) => `<label class="ft-field"><span class="ft-field-label">${escapeHtml(t(label))}</span>
      ${rows ? `<textarea rows="${rows}" maxlength="400"` : `<input type="text" maxlength="${key === 'terms' ? 1200 : 400}"`} class="ft-input" placeholder="${escapeHtml(t(hint))}" title="${escapeHtml(t(hint))}"
        ${pageCall('change', 'saveDictFeature', [f.id, key, { $: 'value' }])}${rows ? `>${escapeHtml(f[key] || '')}</textarea>` : ` value="${escapeHtml(f[key] || '')}">`}</label>`;
  box.innerHTML = list.length ? list.map(f => `<details class="ft-card">
      <summary class="ft-card-head">${featureChipHtml(f)}<span class="tk-grow"></span>
        <span class="text-[11.5px] text-apple-tertiary">${escapeHtml(t('ftRecordings').replace('{n}', () => f.count || 0))}</span></summary>
      <div class="ft-card-body">
        <label class="ft-field"><span class="ft-field-label">${escapeHtml(t('ftName'))}</span>
          <input type="text" maxlength="60" class="ft-input" value="${escapeHtml(f.name)}" title="${escapeHtml(t('ftName'))}" ${pageCall('change', 'saveDictFeature', [f.id, 'name', { $: 'value' }])}></label>
        <div class="ft-field"><span class="ft-field-label">${escapeHtml(t('ftColor'))}</span><span class="ft-swatches">${sw(f)}
          <input type="color" class="ft-color-any" value="${escapeHtml(/^#[0-9A-Fa-f]{6}$/.test(f.color || '') ? f.color : '#64B5FF')}" title="${escapeHtml(t('ftColorAny'))}" aria-label="${escapeHtml(t('ftColorAny'))}"
            ${pageCall('change', 'saveDictFeature', [f.id, 'color', { $: 'value' }])}></span></div>
        ${field(f, 'keywords', 'ftKeywords', 'ftKeywordsHint', 0)}
        ${field(f, 'description', 'ftDescription', 'ftDescriptionHint', 2)}
        ${field(f, 'terms', 'ftTerms', 'ftTermsHint', 0)}
        <div class="flex justify-between"><button class="ui-btn ui-btn-subtle h-7 px-3 text-[11.5px]" ${pageCall('click', 'openFeaturePage', [f.id])}>${escapeHtml(t('fpOpen'))} ↗</button>
          <button class="ui-btn ui-btn-subtle h-7 px-3 text-[11.5px] hover:text-apple-red" ${pageCall('click', 'deleteDictFeature', [f.id])}>${escapeHtml(t('ftDelete'))}</button></div>
      </div></details>`).join('')
    : `<div class="text-[11.5px] text-apple-tertiary">${escapeHtml(t('ftNone'))}</div>`;
}

async function saveDictFeature(id, key, value) {
  const res = await fetch(`/api/features/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ [key]: value }) });
  const data = await readJson(res);
  if (!res.ok) { showError(data.detail); renderDictFeatures(); return; }
  state.features = data;
  if (key === 'name' || key === 'color') {
    const open = [...document.querySelectorAll('#ft-dict-list details[open]')].map(d => [...d.parentNode.children].indexOf(d));
    await renderDictFeatures();
    const cards = document.querySelectorAll('#ft-dict-list details');
    open.forEach(i => cards[i]?.setAttribute('open', ''));
    renderMeetingFeatures();
    scheduleSidebarRender();
  }
}

async function addDictFeature() {
  const input = document.getElementById('ft-dict-new');
  const name = (input?.value || '').trim();
  if (!name) { input?.focus(); return; }
  const res = await fetch('/api/features', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
  const data = await readJson(res);
  if (!res.ok) { showError(data.detail); return; }
  input.value = '';
  await renderDictFeatures();
  const cards = [...document.querySelectorAll('#ft-dict-list details')];
  const i = (state.features || []).findIndex(f => f.id === data.id);
  if (cards[i]) cards[i].open = true;
}

async function deleteDictFeature(id) {
  const f = featureById(id);
  if (!f || !await askConfirm(t('ftDeleteConfirm').replace('{name}', () => f.name), true, t('ftDelete'))) return;
  const res = await fetch(`/api/features/${id}`, { method: 'DELETE' });
  if (!res.ok) { showError((await readJson(res)).detail); return; }
  state.features = await readJson(res);
  for (const m of [state.activeMeeting, ...(state.meetings || [])]) {
    if (!m) continue;
    m.features = (m.features || []).filter(x => x !== id);
    m.feature_suggestions = (m.feature_suggestions || []).filter(x => x !== id);
  }
  renderDictFeatures();
  renderMeetingFeatures();
  scheduleSidebarRender();
}

// --- The card of a feature (asked by the user; opened from the widget «Фичи» on «Главная», a feature's chip,
// the tasks, the dictionary): what is going on now (its next meeting from the calendar, what changed in a
// week, «Где мы» from the analysis model on a click), three numbers, its weeks and people, the last decisions,
// the open tasks as rows and the meetings by month. Sections with nothing in them are left out ---
const FP = { all: {} };  // the sections shown in full («Все решения», «Ещё», «Показать все»), per feature

async function openFeaturePage(id) {
  if (typeof tkClosePop === "function") tkClosePop();
  const res = await fetch(`/api/features/${id}`);
  const data = await readJson(res);
  if (!res.ok) { showError(data.detail); return; }
  const before = document.getElementById('feature-page');
  const scroll = before?.querySelector('.fp-body')?.scrollTop || 0;  // redrawn after a change: stays where it was
  before?.remove();
  const f = data.feature;
  const color = /^#[0-9A-Fa-f]{6}$/.test(f.color || '') ? f.color : '#8E8E93';
  const all = FP.all[f.id] || (FP.all[f.id] = {});
  const tasks = data.tasks || [];
  const open = tasks.filter(x => x.status !== 'done');
  const over = open.filter(x => tkIsOver(x)).length;
  const lang = state.uiLang === 'en' ? 'en-US' : 'ru-RU';
  const wrap = document.createElement('div');
  wrap.id = 'feature-page';
  wrap.dataset.fid = String(f.id);
  wrap.className = 'fixed inset-0 modal-backdrop z-[60] flex items-center justify-center p-4';
  wrap.setAttribute('role', 'dialog');
  wrap.setAttribute('aria-modal', 'true');
  wrap.setAttribute('aria-label', f.name);
  const more = (key, n, label) => n > 0 ? `<button class="fp-more" ${pageCall('click', 'fpShowAll', [f.id, key])}>${escapeHtml(label)}</button>` : '';
  // decisions: the latest first, each with its meeting's date
  const decisions = data.meetings.flatMap(m => m.decisions.map(d => ({ d, m })));
  const decShown = all.decisions ? decisions : decisions.slice(0, 3);
  // tasks: overdue first, then by due date, those without one last
  const sorted = open.slice().sort((x, y) => (tkIsOver(y) - tkIsOver(x)) || String(x.due_date || '9999').localeCompare(String(y.due_date || '9999')));
  const taskShown = all.tasks ? sorted : sorted.slice(0, 4);
  const today = new Date().toISOString().slice(0, 10);
  const meetShown = all.meetings ? data.meetings : data.meetings.slice(0, 5);
  let month = '';
  const meetings = meetShown.map(m => {
    const k = m.date.slice(0, 7);
    // «Ноябрь», with the year when it is not this one
    const d = new Date(`${k}-15T12:00:00`), name = d.toLocaleDateString(lang, { month: 'long' });
    const label = name.charAt(0).toUpperCase() + name.slice(1) + (d.getFullYear() !== new Date().getFullYear() ? ` ${d.getFullYear()}` : '');
    const head = k !== month ? `<div class="fp-month">${escapeHtml(label)}</div>` : '';
    month = k;
    return head + `<button class="fp-meet2" ${pageCall('click', 'openMeetingFromFeature', [m.id])}>
      <span class="fp-meet2-t">${escapeHtml(m.title || t('tkUntitled'))}</span><span class="fp-meet2-d">${escapeHtml(tkShortDate(m.date.slice(0, 10)))} · ${formatTime(m.duration)}</span>
      ${m.tldr ? `<span class="fp-meet2-l">${escapeHtml(m.tldr)}</span>` : ''}</button>`;
  }).join('');
  wrap.innerHTML = `<div class="fp-card modal-card" style="--ft:${color}">
      <div class="fp-head">
        <div class="fp-sw" aria-hidden="true">${escapeHtml((f.name || '?').slice(0, 1).toUpperCase())}</div>
        <div class="fp-ht"><h2 class="fp-title">${escapeHtml(f.name)}</h2>
          ${f.description ? `<p class="fp-desc">${escapeHtml(f.description)}</p>` : `<button class="fp-adddesc" ${pageCall('click', 'editFeatureFromPage')}>+ ${escapeHtml(t('fpAddDesc'))}</button>`}</div>
        <div class="fp-hb">
          <button class="an-btn an-btn-primary" ${pageCall('click', 'askAboutFeature', [f.id])}>✦ ${escapeHtml(t('fpAskShort'))}</button>
          <button class="an-btn" ${pageCall('click', 'editFeatureFromPage')}>${escapeHtml(t('fpEdit'))}</button>
          <button data-a="close" class="dlg-x" title="${escapeHtml(t('tipCloseModal'))}" aria-label="${escapeHtml(t('tipCloseModal'))}">✕</button>
        </div>
      </div>
      <div class="fp-body">
        ${fpNowHtml(data)}
        <div class="fp-stats3">
          <div class="fp-stat"><b>${data.meetings.length}</b><span>${escapeHtml(plural(data.meetings.length, t('dbMeetingForms')).replace(/^\d+\s/, ''))}</span></div>
          <div class="fp-stat"><b>${escapeHtml(dbNum(data.hours || 0))}</b><span>${escapeHtml(t('fpHours'))}</span></div>
          <div class="fp-stat"><b>${open.length}</b><span>${escapeHtml(t('fpOpenCount'))}</span>${over ? `<em class="fp-over">${escapeHtml(t('fpOverdueN').replace('{n}', () => over))}</em>` : ''}</div>
        </div>
        ${data.meetings.length ? fpActivityHtml(data) : ''}
        ${fpPeopleHtml(data)}
        ${decisions.length ? `<section><h4 class="fp-h">${escapeHtml(t('fpDecisions'))}</h4><div class="fp-decs">${decShown.map(x =>
          `<div class="fp-dec2"><span class="fp-dec2-d">${escapeHtml(tkShortDate(x.m.date.slice(0, 10)))}</span><span>${escapeHtml(x.d)}</span></div>`).join('')}</div>
          ${all.decisions ? '' : more('decisions', decisions.length - 3, t('fpAllDecisions').replace('{n}', () => decisions.length))}</section>` : ''}
        ${open.length ? `<section><h4 class="fp-h">${escapeHtml(t('fpOpenTasks'))}</h4><div class="fp-tasks">${taskShown.map(x =>
          `<div class="db-task"><button class="db-ck" ${pageCall('click', 'fpTaskDone', [x.id])} title="${escapeHtml(t('dbMarkDone'))}" aria-label="${escapeHtml(t('dbMarkDone'))}"></button>`
          + `<button class="db-task-t" ${pageCall('click', 'openMeetingFromFeature', [Number(x.meeting_id) || 0])} title="${escapeHtml(x.what)}">${escapeHtml(x.what)}</button>`
          + `<span class="fp-task-who">${escapeHtml(x.who || '')}</span>${dbDue(x, today)}</div>`).join('')}</div>
          ${all.tasks ? '' : more('tasks', open.length - 4, t('fpMoreN').replace('{n}', () => open.length - 4))}</section>` : ''}
        ${data.meetings.length ? `<section><h4 class="fp-h">${escapeHtml(t('fpMeetingsList'))}</h4>${meetings}
          ${all.meetings ? '' : more('meetings', data.meetings.length - 5, t('fpShowAllN').replace('{n}', () => data.meetings.length))}</section>`
          : `<p class="fp-empty">${escapeHtml(t('fpNoMeetings'))}</p>`}
      </div>
    </div>`;
  wrap.addEventListener('click', e => { if (e.target === wrap || e.target.closest('[data-a="close"]')) wrap.remove(); });
  document.body.appendChild(wrap);
  wrap.querySelector('.fp-card').style.maxHeight = `${Math.round(viewH() - 32)}px`;
  const body = wrap.querySelector('.fp-body');
  if (body) body.scrollTop = scroll;
}

// «Сейчас»: the next meeting of the feature (with «Подключиться» when the invitation has a call), what
// changed in 7 days, and «Где мы» (kept on this computer; the model is asked only on a click)
function fpNowHtml(data) {
  const f = data.feature, n = data.next, w = data.week || {};
  const lang = state.uiLang === 'en' ? 'en-US' : 'ru-RU';
  let next = `<div class="fp-box"><div class="fp-k">${escapeHtml(t('fpNext'))}</div><div class="fp-none">${escapeHtml(t(n === null && !(state.system?.settings?.calendar_ics) ? 'fpNoCalendar' : 'fpNoNext'))}</div></div>`;
  if (n) {
    const s = new Date(n.start), d0 = new Date(); d0.setHours(0, 0, 0, 0);
    const days = Math.round((new Date(s.getFullYear(), s.getMonth(), s.getDate()) - d0) / 864e5);
    const day = days === 0 ? t('tkTodayLow') : days === 1 ? t('tkTomorrowLow') : s.toLocaleDateString(lang, { weekday: 'short', day: 'numeric', month: 'short' });
    const who = (n.attendees || []).slice(0, 2).join(', ') + ((n.attendees || []).length > 2 ? ` ${t('fpAndMore').replace('{n}', () => n.attendees.length - 2)}` : '');
    next = `<div class="fp-box"><div class="fp-k">${escapeHtml(t('fpNext'))}</div><div class="fp-next">
      <div class="min-w-0"><div class="fp-when">${escapeHtml(day)} ${escapeHtml(s.toLocaleTimeString(lang, { hour: '2-digit', minute: '2-digit' }))}</div>
        <div class="fp-next-t">${escapeHtml(n.title)}</div>${who ? `<div class="fp-next-w">${escapeHtml(who)}</div>` : ''}</div>
      ${n.join ? `<button class="an-btn an-btn-primary" ${pageCall('click', 'joinMeetingCall', [n.join])}>${escapeHtml(t('hmJoin'))}</button>` : ''}</div></div>`;
  }
  const row = (v, label, sign) => `<div class="fp-chg-r"><b class="${v ? sign : ''}">${v ? (sign === 'plus' ? '+' : '−') + v : '0'}</b><span>${escapeHtml(label)}</span></div>`;
  const week = `<div class="fp-box"><div class="fp-k">${escapeHtml(t('fpWeek7'))}</div><div class="fp-chg">
    ${row(w.decisions || 0, t('fpChgDecisions'), 'plus')}${row(w.tasks_new || 0, t('fpChgNew'), 'plus')}${row(w.tasks_done || 0, t('fpChgDone'), 'minus')}</div></div>`;
  const kept = fpWhere(f.id);
  const busy = FP.whereBusy === f.id;
  const where = `<div class="fp-box fp-where"><div class="min-w-0 flex-1"><div class="fp-k"><span class="fp-ai">✦</span> ${escapeHtml(t('fpWhere'))}</div>
      <p class="fp-where-t">${busy ? escapeHtml(t('fpWhereBusy')) : kept ? escapeHtml(kept.text) : escapeHtml(t('fpWhereNone'))}</p>
      ${kept && !busy ? `<div class="fp-where-at">${escapeHtml(t('fpWhereAt').replace('{date}', () => new Date(kept.at).toLocaleDateString(lang, { day: 'numeric', month: 'short' })))}</div>` : ''}</div>
    ${data.meetings.length ? `<button class="an-btn" ${busy ? 'disabled' : ''} ${pageCall('click', 'fpAskWhere', [f.id])}>${escapeHtml(t(kept ? 'fpWhereRefresh' : 'fpWhereAsk'))}</button>` : ''}</div>`;
  return `<section><h4 class="fp-h">${escapeHtml(t('fpNow'))}</h4><div class="fp-now">${next}${week}${where}</div></section>`;
}

function fpWhere(id) {
  try { const v = JSON.parse(localStorage.getItem(`vx-feature-where-${id}`) || 'null'); return v && v.text ? v : null; } catch (e) { return null; }
}

// «Где мы»: two or three sentences from the transcripts of the feature's meetings (the assistant's answer)
async function fpAskWhere(id) {
  const f = featureById(id);
  const page = await fetch(`/api/features/${id}`).then(r => (r.ok ? r.json() : null)).catch(() => null);
  if (!page) return;
  FP.whereBusy = id;
  openFeaturePage(id);
  try {
    const res = await fetch('/api/library/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: t('fpWhereQuestion').replace('{name}', () => (f || page.feature).name), lang: state.uiLang === 'en' ? 'en' : 'ru',
        meeting_ids: page.meetings.slice(0, 30).map(m => m.id) }) });
    const data = await readJson(res);
    if (!res.ok) throw new Error(errorText(data, res));
    const text = String(data.answer || '').replace(/\s?\[\d+(?:\s*[,–-]\s*\d+)*\]/g, '').replace(/[#*_`>]/g, '').replace(/\s+/g, ' ').trim();
    try { localStorage.setItem(`vx-feature-where-${id}`, JSON.stringify({ text, at: Date.now() })); } catch (e) {}
  } catch (e) {
    showError(serverText(e.message));
  } finally {
    FP.whereBusy = 0;
    if (document.getElementById('feature-page')?.dataset.fid === String(id)) openFeaturePage(id);
  }
}

function fpShowAll(id, key) {
  (FP.all[id] = FP.all[id] || {})[key] = true;
  openFeaturePage(id);
}

async function fpTaskDone(id) {
  const res = await fetch(`/api/tasks/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'done' }) });
  if (!res.ok) { showToast(errorText(await readJson(res), res)); return; }
  refreshFeaturePage();
  showToast(t('dbTaskDone'), { label: t('spUndo'), onClick: async () => {
    await fetch(`/api/tasks/${id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status: 'open' }) });
    refreshFeaturePage();
  } }, 'success');
}

// The card's activity: the meetings of each of the last 12 weeks (the bar's height: their hours), and
// when the last one was
function fpActivityHtml(data) {
  const weeks = data.weeks || [];
  if (!weeks.length) return '';
  const lang = state.uiLang === 'en' ? 'en-US' : 'ru-RU';
  const top = Math.max(0.01, ...weeks.map(w => w.hours));  // the busiest week fills its column
  const label = s => new Date(`${s}T12:00:00`).toLocaleDateString(lang, { day: 'numeric', month: 'short' }).replace('.', '');
  const last = data.last ? t('fpLast').replace('{date}', () => tkShortDate(data.last)) : t('fpNoMeetings');
  return `<section><h4 class="fp-h">${escapeHtml(t('fpActivity'))}<span class="fp-h-sub">${escapeHtml(last)}</span></h4>
    <div class="fp-weeks" style="--ft:${/^#[0-9A-Fa-f]{6}$/.test(data.feature.color || '') ? data.feature.color : 'var(--accent)'}">${weeks.map((w, i) => `<div class="fp-week${i === weeks.length - 1 ? ' now' : ''}" title="${escapeHtml(`${t('fpWeekOf').replace('{date}', () => label(w.start))}: ${plural(w.meetings, t('dbMeetingForms'))} · ${dbNum(w.hours)} ${t('dbHoursShort')}`)}">`
      + `<i style="height:${w.meetings ? Math.max(8, Math.round(w.hours / top * 100)) : 0}%"></i><span>${w.meetings || ''}</span></div>`).join('')}</div>
    <div class="fp-weeks-axis"><span>${escapeHtml(label(weeks[0].start))}</span><span>${escapeHtml(t('fpThisWeek'))}</span></div></section>`;
}

// The people met in the feature's meetings, most first: a click opens the person's card
function fpPeopleHtml(data) {
  const people = data.people || [];
  if (!people.length) return '';
  return `<section><h4 class="fp-h">${escapeHtml(t('fpPeople'))}</h4><div class="fp-people">${people.map(p => {
    const c = /^#[0-9A-Fa-f]{6}$/.test(p.color || '') ? p.color : '#8E8E93';
    return `<button class="fp-person" style="--pc:${c}" ${pageCall('click', 'openPersonFromFeature', [p.name])} title="${escapeHtml(t('fpPersonTip').replace('{n}', () => p.meetings).replace('{date}', () => tkShortDate(p.last)))}">`
      + `<i></i><span>${escapeHtml(p.name)}</span><b>${p.meetings}</b></button>`;
  }).join('')}</div></section>`;
}

function openPersonFromFeature(name) {
  document.getElementById('feature-page')?.remove();
  openPersonCard(name);
}

// A task changed on the open page (its person, due date, done): the counts and the cards follow
function refreshFeaturePage() {
  const page = document.getElementById('feature-page');
  if (page) openFeaturePage(Number(page.dataset.fid));
}

document.addEventListener('keydown', e => {
  if (e.key !== 'Escape' || !document.getElementById('feature-page')) return;
  if (document.querySelector('.tk-pop')) return;  // a picker over the page closes first
  e.stopPropagation();
  document.getElementById('feature-page')?.remove();
});

function openMeetingFromFeature(id) {
  document.getElementById('feature-page')?.remove();
  if (!id) return;
  switchAppView('library');
  openMeeting(id);
}

function askAboutFeature(id) {
  document.getElementById('feature-page')?.remove();
  openLibraryAsk(t('fpAskQuestion'), { type: 'feature', id });
}

function editFeatureFromPage() {
  document.getElementById('feature-page')?.remove();
  openDictionary();
}

function openFeaturePageFromPick(id, e) {
  e.stopPropagation();
  openFeaturePage(id);
}
