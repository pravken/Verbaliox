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

// --- The page of a feature: what it is, its meetings with their decisions, its open tasks, and the
// assistant asked about it ---
async function openFeaturePage(id) {
  if (typeof tkClosePop === "function") tkClosePop();
  const res = await fetch(`/api/features/${id}`);
  const data = await readJson(res);
  if (!res.ok) { showError(data.detail); return; }
  const before = document.getElementById('feature-page');
  const scroll = before?.querySelector('.overflow-y-auto')?.scrollTop || 0;  // redrawn after a change: stays where it was
  before?.remove();
  const f = data.feature;
  const tasks = data.tasks || [];
  const open = tasks.filter(x => x.status !== 'done');
  const over = open.filter(x => tkIsOver(x)).length;
  const done = tasks.length - open.length;
  const stat = (n, label, tone = '') => `<div class="fp-stat"><b class="${tone}">${n}</b><span>${escapeHtml(label)}</span></div>`;
  const decisions = data.meetings.filter(m => m.decisions.length);
  const wrap = document.createElement('div');
  wrap.id = 'feature-page';
  wrap.dataset.fid = String(f.id);
  wrap.className = 'fixed inset-0 modal-backdrop z-[60] flex items-center justify-center p-4';
  wrap.setAttribute('role', 'dialog');
  wrap.setAttribute('aria-modal', 'true');
  wrap.innerHTML = `<div class="w-full max-w-3xl max-h-[88vh] flex flex-col bg-apple-card border apple-border rounded-2xl shadow-2xl modal-card">
      <div class="px-5 pt-5 pb-3 border-b apple-border flex items-start justify-between gap-3">
        <div class="min-w-0 space-y-1.5">${featureChipHtml(f)}
          ${f.description ? `<p class="text-[12.5px] text-apple-label leading-snug">${escapeHtml(f.description)}</p>` : ''}
          ${f.keywords ? `<p class="text-[11.5px] text-apple-tertiary">${escapeHtml(t('ftKeywords'))}: ${escapeHtml(f.keywords)}</p>` : ''}</div>
        <div class="flex items-center gap-2 shrink-0">
          <button class="an-btn an-btn-primary" ${pageCall('click', 'askAboutFeature', [f.id])}>✦ ${escapeHtml(t('fpAsk'))}</button>
          <button class="an-btn" ${pageCall('click', 'editFeatureFromPage')}>${escapeHtml(t('fpEdit'))}</button>
          <button data-a="close" class="dlg-x" title="${escapeHtml(t('tipCloseModal'))}" aria-label="${escapeHtml(t('tipCloseModal'))}">✕</button>
        </div>
      </div>
      <div class="flex-1 overflow-y-auto px-5 py-4 space-y-5">
        <div class="fp-stats">${stat(data.meetings.length, t('fpMeetings'))}${stat(dbNum(data.hours || 0), t('fpHours'))}${stat(open.length, t('fpOpenCount'))}${stat(over, t('fpOverdue'), over ? 'tk-red' : '')}${stat(done, t('fpDone'), done ? 'tk-green' : '')}</div>
        ${fpActivityHtml(data)}
        ${fpPeopleHtml(data)}
        <section><h4 class="fp-h">${escapeHtml(t('fpDecisions'))}</h4>
          ${decisions.length ? decisions.map(m => `<div class="fp-dec"><button class="fp-meet-link" ${pageCall('click', 'openMeetingFromFeature', [m.id])}>${escapeHtml(m.title || t('tkUntitled'))} · ${escapeHtml(tkShortDate(m.date.slice(0, 10)))}</button>
              <ul>${m.decisions.map(d => `<li>${escapeHtml(d)}</li>`).join('')}</ul></div>`).join('')
            : `<p class="fp-empty">${escapeHtml(t('fpNoDecisions'))}</p>`}</section>
        <section><h4 class="fp-h">${escapeHtml(t('fpOpenTasks'))}</h4>
          ${open.length ? `<div class="an-tasks">${open.map(c => commitmentRowHtml(c, true)).join('')}</div>` : `<p class="fp-empty">${escapeHtml(t('fpNoTasks'))}</p>`}</section>
        <section><h4 class="fp-h">${escapeHtml(t('fpMeetingsList'))}</h4>
          ${data.meetings.length ? data.meetings.map(m => `<button class="fp-meet" ${pageCall('click', 'openMeetingFromFeature', [m.id])}>
              <span class="fp-meet-title">${escapeHtml(m.title || t('tkUntitled'))}</span><span class="fp-meet-date">${escapeHtml(tkShortDate(m.date.slice(0, 10)))} · ${formatTime(m.duration)}</span>
              ${m.tldr ? `<span class="fp-meet-tldr">${escapeHtml(m.tldr)}</span>` : ''}</button>`).join('')
            : `<p class="fp-empty">${escapeHtml(t('fpNoMeetings'))}</p>`}</section>
      </div>
    </div>`;
  wrap.addEventListener('click', e => { if (e.target === wrap || e.target.closest('[data-a="close"]')) wrap.remove(); });
  document.body.appendChild(wrap);
  const body = wrap.querySelector('.overflow-y-auto');
  if (body) body.scrollTop = scroll;
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
