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
  box.innerHTML = shown.map(f => `<button class="ft-chip-btn" ${pageCall('click', 'openFeaturePicker', [{ $: 'event' }])} title="${escapeHtml(t('ftChangeTip'))}">${featureChipHtml(f)}</button>`).join('')
    + (more > 0 ? `<button class="ft-chip-btn ft-more" ${pageCall('click', 'openFeaturePicker', [{ $: 'event' }])} title="${escapeHtml(own.map(f => f.name).join(', '))}">+${more}</button>` : '')
    + guesses.map(f => `<span class="ft-suggest">${featureChipHtml(f, { suggested: true, title: t('ftSuggestedTip') })}
        <button class="ft-yes" ${pageCall('click', 'acceptFeatureSuggestion', [f.id])} title="${escapeHtml(t('ftAccept'))}" aria-label="${escapeHtml(t('ftAccept'))}">✓</button>
        <button class="ft-no" ${pageCall('click', 'declineFeatureSuggestion', [f.id])} title="${escapeHtml(t('ftDecline'))}" aria-label="${escapeHtml(t('ftDecline'))}">✕</button></span>`).join('')
    + (own.length ? '' : `<button class="ft-add" ${pageCall('click', 'openFeaturePicker', [{ $: 'event' }])} title="${escapeHtml(t('ftAddTip'))}">+ ${escapeHtml(t('ftFeature'))}</button>`);
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
  applyMeetingFeatures(m, data);
  loadFeatures().then(() => { if (document.getElementById('tk-pop')) drawFeaturePicker(); });
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
  const on = new Set(m.features || []);
  const list = (state.features || []).map(f => `<button class="tk-pop-item" role="menuitemcheckbox" aria-checked="${on.has(f.id)}" ${pageCall('click', 'toggleMeetingFeature', [f.id])}>
      ${featureChipHtml(f)}<span class="tk-grow"></span><span class="tk-dim">${f.count || 0}</span>${on.has(f.id) ? '<span class="tk-tick">✓</span>' : '<span class="tk-tick"></span>'}</button>`).join('');
  const series = m.series_id ? `<label class="ft-series"><input type="checkbox" id="ft-for-series" ${pageCall('change', 'saveFeaturesForSeries')}>
      <span>${escapeHtml(t('ftForSeries'))}</span></label>` : '';
  tkOpenPop(`<div class="tk-pop-cap">${escapeHtml(t('ftPickTitle'))}</div>${list || `<div class="tk-pop-quote">${escapeHtml(t('ftNone'))}</div>`}
    <div class="tk-pop-add"><div class="tk-row2">
      <input id="ft-new-name" class="tk-input" type="text" maxlength="60" placeholder="${escapeHtml(t('ftNewPh'))}" title="${escapeHtml(t('ftNewPh'))}" ${pageCall('keydown', 'onNewFeatureKey', [{ $: 'event' }])}>
      <button class="tk-btn tk-btn-primary tk-btn-sm" ${pageCall('click', 'createFeatureFromPicker')}>${escapeHtml(t('ftCreate'))}</button></div>${series}</div>`, _ftAnchor, 300);
}

function toggleMeetingFeature(id) {
  const m = state.activeMeeting;
  const ids = new Set(m.features || []);
  if (ids.has(id)) ids.delete(id); else ids.add(id);
  saveMeetingFeatures([...ids], !!document.getElementById('ft-for-series')?.checked);
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
  await saveMeetingFeatures([...new Set([...(m.features || []), f.id])], !!document.getElementById('ft-for-series')?.checked);
}

// The tags of a task: the features of its meeting (tasks are not tagged one by one)
// One chip (the first feature) and «+N», the whole list in its tip: a task card keeps one line for it
function taskFeatureChipsHtml(meetingId, ids) {
  const list = (ids || ((state.meetings || []).find(x => x.id === meetingId) || {}).features || []).map(featureById).filter(Boolean);
  if (!list.length) return '';
  const all = list.map(f => f.name).join(', ');
  return `<span class="ft-compact">${featureChipHtml(list[0], { title: all })}${list.length > 1 ? `<span class="ft-more" title="${escapeHtml(all)}">+${list.length - 1}</span>` : ''}</span>`;
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
      ${rows ? `<textarea rows="${rows}" maxlength="400"` : '<input type="text" maxlength="400"'} class="ft-input" placeholder="${escapeHtml(t(hint))}" title="${escapeHtml(t(hint))}"
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
        <div class="flex justify-end"><button class="ui-btn ui-btn-subtle h-7 px-3 text-[11.5px] hover:text-apple-red" ${pageCall('click', 'deleteDictFeature', [f.id])}>${escapeHtml(t('ftDelete'))}</button></div>
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
