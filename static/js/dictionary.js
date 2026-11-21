// Verbaliox page script: «Словарь», a section of its own at the bottom of the rail (docs/pult-plan.md, stage 6).
// The words come from /api/dictionary (state.dictionary, loaded by settings.js loadDictionary, which also adds
// a word, edits and deletes one); this page shows them by group, with how many recordings hold each
// (/api/dictionary/usage) and its own switch, and the words corrections by hand suggest
// (/api/dictionary/offers, made by the edits of the analysis that offerDictionaryWords offers at once).
// The parts are classic scripts sharing one global scope, loaded in order by index.html.

const DC = { group: '', q: '', usage: {}, offers: [] };

async function renderDictionaryPage() {
  const [usage, offers] = await Promise.all([
    fetch('/api/dictionary/usage').then(r => (r.ok ? r.json() : {})).catch(() => ({})),
    fetch('/api/dictionary/offers').then(r => (r.ok ? r.json() : [])).catch(() => []),
  ]);
  DC.usage = usage || {};
  DC.offers = Array.isArray(offers) ? offers : [];
  const s = (state.system && state.system.settings) || {};
  document.getElementById('set-dict-fuzzy').checked = s.dictionary_fuzzy !== 'false';
  document.getElementById('set-feature-suggest').checked = s.feature_suggest !== 'false';
  await loadDictionary();  // draws the page (renderDictPage)
  if (typeof renderDictFeatures === 'function') renderDictFeatures();
}

function dcGroups() {
  const groups = new Map();
  for (const d of state.dictionary || []) groups.set(d.category, (groups.get(d.category) || 0) + 1);
  return [...groups.entries()].sort((a, b) => _libCollator.compare(a[0], b[0]));
}

function renderDictPage() {
  if (state.appView !== 'dict') return;
  const terms = state.dictionary || [];
  const groups = dcGroups();
  if (DC.group && !groups.some(([g]) => g === DC.group)) DC.group = '';
  document.getElementById('dc-sub').textContent = terms.length
    ? `${plural(terms.length, t('dcWordsForms'))} · ${plural(groups.length, t('dcGroupsForms'))}` : t('rdSasDictEmpty');
  document.getElementById('dc-groups').innerHTML = groups.map(([g]) => `<option value="${escapeHtml(g)}"></option>`).join('');
  renderDictOffers();
  const q = DC.q.trim().toLocaleLowerCase();
  const shown = terms.filter(d => (!DC.group || d.category === DC.group)
    && (!q || `${d.term} ${d.variants || ''} ${d.category}`.toLocaleLowerCase().includes(q)));
  const chip = (key, label, n) => `<button class="tk-chip${DC.group === key ? ' tk-on' : ''}" aria-pressed="${DC.group === key}" ${pageCall('click', 'setDictGroup', [key])}>${escapeHtml(label)} <span class="tk-chip-n">${n}</span></button>`;
  const filters = `<div class="dc-filters">${chip('', t('tkFAll'), terms.length)}${groups.map(([g, n]) => chip(g, g, n)).join('')}</div>`;
  const row = d => {
    const n = Number(DC.usage[String(d.id)] || 0);
    const variants = String(d.variants || '').split(',').map(v => v.trim()).filter(Boolean);
    return `<div class="dc-row${d.active ? '' : ' dc-off'}">
      <span class="dc-word" title="${escapeHtml(d.term)}">${escapeHtml(d.term)}</span>
      <span class="dc-vars">${variants.length ? variants.map(v => `<span class="dc-var">${escapeHtml(v)}</span>`).join('') : '<span class="tk-dim">—</span>'}</span>
      <span class="dc-group">${escapeHtml(d.category)}</span>
      <span class="dc-used">${escapeHtml(n ? plural(n, t('dcRecForms')) : t('dcRecNone'))}</span>
      <input type="checkbox" role="switch" class="vs-switch vs-sm" ${d.active ? 'checked' : ''} ${pageCall('change', 'toggleDictItem', [d.id, { $: 'checked' }])}
        title="${escapeHtml(t(d.active ? 'dcOnTip' : 'dcOffTip'))}" aria-label="${escapeHtml(t('dcOnTip'))}">
      <button class="tk-more" ${pageCall('click', 'openDictRowMenu', [d.id, { $: 'event' }])} title="${escapeHtml(t('dcRowMenu'))}" aria-label="${escapeHtml(t('dcRowMenu'))}">⋯</button>
    </div>`;
  };
  const head = `<div class="dc-row dc-thead" aria-hidden="true"><span>${escapeHtml(t('dcColWord'))}</span><span>${escapeHtml(t('dcColVars'))}</span>`
    + `<span>${escapeHtml(t('dcColGroup'))}</span><span>${escapeHtml(t('dcColUsed'))}</span><span>${escapeHtml(t('dcColOn'))}</span><span></span></div>`;
  const body = !terms.length ? `<div class="dc-empty">${escapeHtml(t('rdSasDictEmpty'))}</div>`
    : shown.length ? head + shown.map(row).join('') : `<div class="dc-empty">${escapeHtml(t('tkNothing'))}</div>`;
  const clear = terms.length ? `<button id="settings-dict-clear" data-click="clearDictionary" class="tk-btn tk-btn-sm" data-i18n="cfDeleteWords">${escapeHtml(t('cfDeleteWords'))}</button>` : '';
  document.getElementById('dc-words').innerHTML = pultCardHead(t('dcWords'), terms.length, 'book', clear) + (terms.length ? filters : '') + body;
}

function renderDictOffers() {
  const box = document.getElementById('dc-offers');
  const list = DC.offers;
  box.classList.toggle('hidden', !list.length);
  if (!list.length) { box.innerHTML = ''; return; }
  box.innerHTML = pultCardHead(t('dcOffers'), list.length, 'spark')
    + `<p class="dc-note">${escapeHtml(t('dcOffersNote'))}</p>`
    + list.map((o, i) => `<div class="dc-offer">
        <span class="dc-offer-w"><b>${escapeHtml(o.right)}</b> <span class="tk-dim">${escapeHtml(t('dcInsteadOf').replace('{w}', () => o.wrong))}</span></span>
        <span class="dc-offer-rec" title="${escapeHtml(o.title)}">${escapeHtml(o.title)}</span>
        <button class="tk-btn tk-btn-sm tk-btn-primary" ${pageCall('click', 'acceptDictOffer', [i])}>${escapeHtml(t('rdSasDictAdd'))}</button>
        <button class="tk-btn tk-btn-sm" ${pageCall('click', 'hideDictOffer', [i])}>${escapeHtml(t('dcHide'))}</button>
      </div>`).join('');
}

function setDictGroup(g) { DC.group = g; renderDictPage(); }
function onDictSearch(value) { DC.q = value; renderDictPage(); }

async function acceptDictOffer(i) {
  const o = DC.offers[i];
  if (!o) return;
  const res = await fetch('/api/dictionary/learn', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pairs: [{ wrong: o.wrong, right: o.right }] }) }).catch(() => null);
  if (!res || !res.ok) { showError(res ? serverText((await readJson(res)).detail) : t('errNoNetwork')); return; }
  DC.offers.splice(i, 1);
  await loadDictionary();
}

async function hideDictOffer(i) {
  const o = DC.offers[i];
  if (!o) return;
  await fetch('/api/dictionary/offers/hide', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ wrong: o.wrong, right: o.right }) }).catch(() => null);
  DC.offers.splice(i, 1);
  renderDictPage();
}

function openDictRowMenu(id, e) {
  e.stopPropagation();
  const r = e.currentTarget.getBoundingClientRect();
  openTextMenuAt([
    { label: t('editBtn'), run: () => editDictItem(id) },
    { label: t('dcDelete'), run: () => deleteSettingsDictItem(id) },
  ], r.right, r.bottom + 4, { right: true });
}

// The two switches of the section are settings: saved at once
document.addEventListener('change', async e => {
  const key = DICT_SWITCHES[e.target?.id];
  if (!key || !e.target.closest('#dict-view')) return;
  const value = String(!!e.target.checked);
  const res = await fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ settings: { [key]: value } }) }).catch(() => null);
  if (!res || !res.ok) { showError(t('errorGeneric')); return; }
  if (state.system && state.system.settings) state.system.settings[key] = value;
  if (typeof _settingsBaseline === 'object' && _settingsBaseline) _settingsBaseline[key] = value;
});

registerView('dict', { show: renderDictionaryPage, refresh: (changed) => { if (changed) renderDictionaryPage(); } });
