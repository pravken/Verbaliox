// Verbaliox page script, part 1 of 9: State, small helpers, dialogs and voice profiles.
// The parts are classic scripts sharing one global scope, loaded in order by index.html.

// Verbaliox UI logic. Depends on vendor/marked.min.js, vendor/purify.min.js and i18n.js.
const DONE_STATUSES = ['completed', 'failed', 'cancelled', 'cleared', 'added'];  // added: imported without recognition
// The page opened, so the locked page (app/main.py) may again try one fresh address next time
try { sessionStorage.removeItem('vs_relocked'); } catch (e) { /* storage off */ }

// --- Interface scale (Settings → Interface, ui_scale): CSS zoom on the page, 100 % by default ---
// The zoom is on <html>, so the page lays itself out in its own pixels: a point of the window
// (event.clientX/Y, getBoundingClientRect) is divided by the zoom before it becomes style.left/top.
const UI_SCALES = ['75', '90', '100', '115', '130', '150'];
function uiZoom() { return Number(document.documentElement.dataset.zoom) || 1; }
function zpx(v) { return v / uiZoom(); }
function viewW() { return window.innerWidth / uiZoom(); }
function viewH() { return window.innerHeight / uiZoom(); }
// Audit 3.15. After the page has drawn what was just shown (two frames), not after a guessed delay
function nextFrame(fn) { requestAnimationFrame(() => requestAnimationFrame(fn)); }
// «Show less motion» in Windows: scrolls jump instead of gliding (CSS covers the rest)
function scrollMotion() {
  return window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
}
// Audit 3.6. Menus and dialogs leave the way they came, in 120 ms, instead of vanishing in one
// frame; the pointer goes through them meanwhile, so nothing waits for the animation. Showing the
// element again cancels its exit (cancelLeave)
function leaveThen(el, done) {
  if (!el || scrollMotion() === 'auto' || el.classList.contains('hidden')) { done(); return; }
  const token = el._leave = (el._leave || 0) + 1;
  el.classList.add('is-leaving');
  const end = () => {
    if (el._leave !== token) return;
    el._leave++;
    el.classList.remove('is-leaving');
    done();
  };
  el.addEventListener('animationend', (e) => { if (e.target === el) end(); }, { once: true });
  setTimeout(end, 140);
}
// A side panel (the details and the widgets of «Обзор»): slides in from the right when it is shown, and out
// before it is hidden; a redraw of a shown one does not move it. after() runs once it is hidden
function drawerShow(el) {
  if (!el) return;
  const was = el.classList.contains('hidden') || el.classList.contains('vx-drawer-out');
  el._drawer = (el._drawer || 0) + 1;
  el.classList.remove('hidden', 'vx-drawer-out');
  if (was) { el.classList.remove('vx-drawer-in'); void el.offsetWidth; el.classList.add('vx-drawer-in'); }
}
function drawerHide(el, after) {
  if (!el) return;
  if (el.classList.contains('hidden') || scrollMotion() === 'auto') { el.classList.add('hidden'); el.classList.remove('vx-drawer-in', 'vx-drawer-out'); if (after) after(); return; }
  if (el.classList.contains('vx-drawer-out')) return;
  const token = el._drawer = (el._drawer || 0) + 1;
  el.classList.remove('vx-drawer-in');
  el.classList.add('vx-drawer-out');
  const end = () => {
    el.removeEventListener('animationend', onEnd);
    if (el._drawer !== token) return;
    el._drawer++;
    el.classList.remove('vx-drawer-out');
    el.classList.add('hidden');
    if (after) after();
  };
  const onEnd = (e) => { if (e.target === el) end(); };
  el.addEventListener('animationend', onEnd);
  setTimeout(end, 220);
}
// A window drawn again in place (its next step, a filter): the opening motion plays on the first draw only
function vxRedraw(wrap) {
  if (wrap.dataset.drawn) wrap.classList.add('vx-drawn');
  wrap.dataset.drawn = '1';
}
function hideWithExit(el) { leaveThen(el, () => el.classList.add('hidden')); }
function removeWithExit(el) { leaveThen(el, () => el.remove()); }
function cancelLeave(el) {
  if (!el || !el.classList.contains('is-leaving')) return;
  el._leave = (el._leave || 0) + 1;
  el.classList.remove('is-leaving');
}

// Puts a shown menu at the pointer by its real size: where it does not fit below, it opens upward
// from the pointer, and where it does not fit to the right, leftward; it never leaves the window
function placeMenuAt(menu, e) {
  cancelLeave(menu);
  const x = zpx(e.clientX), y = zpx(e.clientY);
  const w = menu.offsetWidth, h = menu.offsetHeight;
  const left = x + w <= viewW() - 8 ? x : Math.max(8, x - w);
  const top = y + h <= viewH() - 8 ? y : Math.max(8, Math.min(y - h, viewH() - h - 8));
  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;
  menu.style.transformOrigin = `${left < x ? 'right' : 'left'} ${top < y ? 'bottom' : 'top'}`;
}
function applyUiScale(pct) {
  const z = (UI_SCALES.includes(String(pct)) ? Number(pct) : 100) / 100;
  const root = document.documentElement;
  root.style.zoom = String(z);
  root.dataset.zoom = String(z);
  root.style.setProperty('--ui-zoom', String(z));  // body height: 100vh is not zoomed (styles.css)
  try { localStorage.setItem('verbaliox_ui_scale', String(Math.round(z * 100))); } catch (e) {}
  if (typeof scheduleFitTopbar === 'function') scheduleFitTopbar();
}
// Before anything is drawn: the last scale, so the window does not jump when the settings arrive
(() => { let v = null; try { v = localStorage.getItem('verbaliox_ui_scale'); } catch (e) {} applyUiScale(v || '100'); })();

// --- The look: the accent colour and the background. Every colour of the page reads the variables of
// static/styles.css :root, set here ---
// One background, chosen with the user on the try-on page: the cold slate with the soft fill (asked by the user: the
// paler accent, as on the icon squares, for the buttons and switches too). The accent is
// chosen in Settings → Общие from the presets approved then (ui_accent); the fill under white text is the accent darkened until white reads on it (4.8:1 and more)
const THEME_ACCENTS = {
  steel: '#4C7FD9', lavender: '#8C7FD0', slate: '#7D8A9C', turquoise: '#43A6B4',
  emerald: '#3F9E78', sage: '#6F9C80', ochre: '#C09A4D', cherry: '#A8324A',
};
const THEME_BGS = {
  slate: '#121418', deepblue: '#10141C', petrol: '#0E1617', moss: '#121411',
  pine: '#0F1513', steel: '#111518', coal: '#0B0C0E', black: '#000000',
};
const THEME_FILLS = ['solid', 'soft', 'outline'];
// the presets of 0.8.24, for a theme chosen then
const THEME_FORMER = { blue: 'steel', indigo: 'lavender', purple: 'lavender', pink: 'cherry', teal: 'turquoise', mint: 'emerald', graphite: 'slate',
  midnight: 'deepblue', forest: 'pine', warm: 'coal' };
function hexChannels(h) { return [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16)).join(' '); }
// a colour mixed with white (k > 0) or black (k < 0), as #RRGGBB
function hexMix(h, k) {
  const to = k > 0 ? 255 : 0, f = Math.abs(k);
  return '#' + [1, 3, 5].map(i => Math.round(parseInt(h.slice(i, i + 2), 16) * (1 - f) + to * f).toString(16).padStart(2, '0')).join('');
}
// two colours mixed: k of b into a
function hexBlend(a, b, k) {
  return '#' + [1, 3, 5].map(i => Math.round(parseInt(a.slice(i, i + 2), 16) * (1 - k) + parseInt(b.slice(i, i + 2), 16) * k).toString(16).padStart(2, '0')).join('');
}
function hexContrast(x, y) {
  const lum = h => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16) / 255)
    .map(c => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)).reduce((s, c, i) => s + c * [0.2126, 0.7152, 0.0722][i], 0);
  const a = lum(x), b = lum(y);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}
// the fill under a white text: the accent darkened step by step until white reads on it
function readableFill(c) {
  let k = 0.1, d = hexMix(c, -k);
  while (hexContrast('#ffffff', d) < 4.8 && k < 0.8) { k += 0.04; d = hexMix(c, -k); }
  return d;
}
function themeKey(v, list, def) { v = THEME_FORMER[v] || v; return list[v] ? v : def; }
function applyTheme(accent, bg, fill) {
  accent = themeKey(accent, THEME_ACCENTS, 'steel');
  bg = themeKey(bg, THEME_BGS, 'slate');
  fill = THEME_FILLS.includes(fill) ? fill : 'solid';
  const a = THEME_ACCENTS[accent], page = THEME_BGS[bg], lo = readableFill(a);
  const st = document.documentElement.style;
  // the accent and its shades: light (marks, links), the fill under white text, pressed; the page and four
  // steps lighter keeping its tint (sidebar, panel, card, raised)
  [['accent', a], ['accent-hi', hexMix(a, 0.36)], ['accent-lo', lo],
    ['bg', page], ['sidebar', hexMix(page, 0.035)], ['panel', hexMix(page, 0.045)], ['card', hexMix(page, 0.075)], ['elevated', hexMix(page, 0.11)]]
    .forEach(([k, v]) => { st.setProperty(`--${k}`, v); st.setProperty(`--${k}-rgb`, hexChannels(v)); });
  st.setProperty('--accent-deep', hexMix(lo, -0.14));
  st.setProperty('--bg-deep', hexMix(page, -0.22));  // a page under cards, a step darker
  st.setProperty('--accent-text', hexMix(a, 0.45));
  st.setProperty('--accent-pale', hexMix(a, 0.78));
  // the muted accent of the switches and the check boxes, the same as the soft fill (asked by the user: one, paler accent)
  st.setProperty('--accent-soft', hexBlend(page, a, 0.5));
  // «Заливка выделенного»: solid (white text on the darkened accent), soft (a tint of it, its light text),
  // outline (a frame and the light text)
  const fills = {
    solid: [lo, hexMix(lo, -0.14), '#FFFFFF', 'transparent'],
    soft: [hexBlend(page, a, 0.38), hexBlend(page, a, 0.46), hexMix(a, 0.6), hexBlend(page, a, 0.7)],
    outline: ['transparent', hexBlend(page, a, 0.14), hexMix(a, 0.45), a],
  }[fill];
  ['fill-bg', 'fill-bg-hover', 'fill-fg', 'fill-ring'].forEach((k, i) => st.setProperty(`--${k}`, fills[i]));
  Object.assign(document.documentElement.dataset, { accent, bg, fill });
  try { localStorage.setItem('verbaliox_ui_accent', accent); } catch (e) {}
}
// the accent as a colour for a canvas (it cannot read a CSS variable)
function accentColor() { return getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#0A84FF'; }
// Before anything is drawn: the last theme, so the window does not flash the default one
// the accent chosen in Settings → Общие (ui_accent), remembered here so the window does not flash the default one;
// the background and the fill stay one (asked by the user: accents to choose, not backgrounds)
(() => { let v = null; try { v = localStorage.getItem('verbaliox_ui_accent'); } catch (e) {} applyTheme(v || 'steel', 'slate', 'soft'); })();

// --- Events without inline handlers ---
// The page's Content-Security-Policy runs no inline script, so markup does not say onclick="…".
// An element names a page function in data-<event> and its arguments, as a JSON list, in
// data-<event>-args: <button data-click="openModal" data-click-args='["settings"]'>. In templates the
// values go in with jsArg() (or Number()), as before. Placeholders in the list: {"$":"event"},
// {"$":"el"} (the element), {"$":"value"}, {"$":"checked"}, {"$":"files"} and {"$":"data","k":"x"}
// (el.dataset.x). A text from a recording can never become a placeholder: jsArg makes it a string.
const PAGE_EVENTS = ['click', 'dblclick', 'change', 'input', 'keydown', 'contextmenu', 'dragstart', 'dragover', 'dragleave', 'drop'];
const PAGE_OWN_EVENTS = { focusin: 'focus', focusout: 'blur', error: 'error' };  // of the element itself

// The event as an inline handler saw it: its currentTarget is the element that has the handler
// (the listener is on the document, so the real one is the document). Methods act on the real event.
function pageEvent(ev, el) {
  return new Proxy(ev, {
    get(target, key) {
      if (key === 'currentTarget') return el;
      const value = Reflect.get(target, key, target);
      return typeof value === 'function' ? value.bind(target) : value;
    },
    set(target, key, value) { target[key] = value; return true; },
  });
}

function pageArg(a, el, ev) {
  if (!a || typeof a !== 'object' || Array.isArray(a) || typeof a.$ !== 'string') return a;
  switch (a.$) {
    case 'event': return pageEvent(ev, el);
    case 'el': return el;
    case 'value': return el.value;
    case 'checked': return el.checked;
    case 'files': return el.files;
    case 'data': return el.dataset[a.k];
    default: return a;
  }
}

// Only a function of the page's own scripts: never one of the browser's (fetch, open, …), even wrapped by
// the page, so markup that should not be there (a hostile backup, say) cannot call them with its own arguments
const PAGE_WRAPS_BROWSER = new Set(['fetch']);  // the page's wrappers of a browser function: still the browser's
function pageFunction(name) {
  if (!/^[A-Za-z_$][\w$]*$/.test(name || '') || PAGE_WRAPS_BROWSER.has(name)) return null;
  const fn = window[name];
  if (window.BROWSER_VALUES && window.BROWSER_VALUES.has(name) && window.BROWSER_VALUES.get(name) === fn) return null;
  if (typeof fn !== 'function' || /\[native code\]\s*\}$/.test(Function.prototype.toString.call(fn))) return null;
  return fn;
}

function callPage(name, ...args) {
  const fn = pageFunction(name);
  if (!fn) { console.error(`no page function "${name}"`); return undefined; }
  return fn(...args);
}

function runPageHandler(el, type, ev) {
  const name = el.getAttribute('data-' + type);
  const fn = pageFunction(name);
  if (!fn) {
    console.error(`data-${type}: no page function "${name}"`);
    return;
  }
  let args = [];
  const raw = el.getAttribute(`data-${type}-args`);
  if (raw) {
    try { args = JSON.parse(raw); } catch (e) { console.error(`data-${type}-args: not JSON`, raw); return; }
  }
  fn.apply(el, args.map(a => pageArg(a, el, ev)));
}

for (const type of PAGE_EVENTS) {
  // Registered before every other listener of the page: the handlers run first, as inline ones did
  document.addEventListener(type, ev => {
    // From the element up, like bubbling; stopPropagation() in a handler ends it, and also keeps
    // the page's own document listeners (closing menus) from seeing the event, as before
    for (const el of ev.composedPath()) {
      if (el === document || !(el instanceof Element)) break;
      if (el.hasAttribute('data-' + type)) {
        runPageHandler(el, type, ev);
        if (ev.cancelBubble) { ev.stopImmediatePropagation(); break; }
      }
    }
  });
}
for (const [native, type] of Object.entries(PAGE_OWN_EVENTS)) {
  document.addEventListener(native, ev => {
    const el = ev.target;
    if (el instanceof Element && el.hasAttribute('data-' + type)) runPageHandler(el, type, ev);
  }, true);  // focus and a failed image do not bubble: seen on the way down
}

// Both attributes for a template: pageCall('click', 'quickTranslate', [lang]) gives
// data-click="quickTranslate" data-click-args='["en"]'. Any value is safe in the list.
function pageCall(type, fn, args = []) {
  return `data-${type}="${fn}"` + (args.length ? ` data-${type}-args='${escapeHtml(JSON.stringify(args))}'` : '');
}

// Small steps the markup used to write inline. `name`: a page function, called with the rest
function stopEvent(ev) { ev.stopPropagation(); }
function preventEvent(ev) { ev.preventDefault(); }
function stopThen(ev, name, ...args) { ev.stopPropagation(); callPage(name, ...args); }
function preventThen(ev, name, ...args) { ev.preventDefault(); callPage(name, ...args); }
function onEnter(ev, name, ...args) { if (ev.key === 'Enter') callPage(name, ...args); }
function blurOnEnter(ev, el) { if (ev.key === 'Enter') el.blur(); }
function selectOnFocus(el) { el.select(); }
function clickElement(id) { document.getElementById(id).click(); }
function showFixed2(el, id) { document.getElementById(id).textContent = Number(el.value).toFixed(2); }
function removeElement(el) { el.remove(); }
function openSupport() { openExternal(SUPPORT_URL); }
// Several calls in turn: runAll(["hideTranslateMenu"], ["openTranslateModal"])
function runAll(...calls) { for (const [name, ...args] of calls) callPage(name, ...args); }

let state = {
  uiLang: (() => { try { return localStorage.getItem('whisper_ui_lang') || 'ru'; } catch (e) { return 'ru'; } })(),
  meetings: [],
  activeMeeting: null,
  contextMeetingId: null,
  activeWorkspaceTab: 'transcript',
  activeSummaryTab: 'protocol',
  speakerFilter: null,
  videoMode: (() => { try { return localStorage.getItem('verbaliox_video_mode') === 'mini' ? 'mini' : 'expanded'; } catch (e) { return 'expanded'; } })(),
  hasVideo: false,
  audioTrack: 'orig',
  studioVoiceActive: false,
  globalSearchQuery: '',
  globalSearchResults: null,
  playbackSpeeds: [1.0, 1.25, 1.5, 1.75, 2.0],
  speedIndex: 0,
  system: null,
  dictionary: [],
  voicePreviewTimer: null,
  playerPeaks: [],
  playerHoverRatio: -1,
  volume: (() => { try { return Number(localStorage.getItem('verbaliox_volume') ?? 100); } catch (e) { return 100; } })(),
  muted: false,
  txView: (() => { try { return localStorage.getItem('verbaliox_tx_view') || 'orig'; } catch (e) { return 'orig'; } })(),
  txLang: null,
};

// Minimalist SVG Icon Helpers (uniform stroke style)
const ICON_SPEAKERS = '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z"/></svg>';

const SVG_ICONS = {
  pencil: `<svg class="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16v4z"/><path d="M13.5 6.5l4 4"/></svg>`,
  download: `<svg class="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3"/></svg>`,
  check: `<svg class="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5"/></svg>`,
  trash: `<svg class="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" stroke-width="1.75" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0"/></svg>`,
  playMini: `<svg class="w-3 h-3 shrink-0" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>`,
  mergeUp: `<svg class="w-3 h-3 shrink-0" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M4.5 10.5L12 3m0 0l7.5 7.5M12 3v18"/></svg>`,
  closeX: `<svg class="w-3.5 h-3.5 shrink-0" fill="none" stroke="currentColor" stroke-width="1.8" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"/></svg>`,
};

function t(key) {
  return (I18N[state.uiLang] && I18N[state.uiLang][key]) || I18N.ru[key] || key;
}

// A text that may not exist (a status or summary kind made up from data): undefined, not the key
function tMaybe(key) {
  return (I18N[state.uiLang] && I18N[state.uiLang][key]) || I18N.ru[key] || undefined;
}

// --- Dates in the interface language: a native date field writes its date the way the browser's own
// locale does (10/25/2026 in a Russian interface). Each one gets a button over it with the date as the
// interface writes it (25.10.2026); the button opens the field's own calendar. ---
function uiDateText(iso) {
  if (!iso) return t('pickDate');
  const d = new Date(`${iso}T00:00`);
  return isNaN(d) ? iso : d.toLocaleDateString(state.uiLang === 'en' ? 'en-US' : 'ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' });
}
function syncDateField(input) {
  const btn = input && input.parentElement && input.parentElement.querySelector(':scope > .vs-date-btn');
  if (btn) btn.textContent = uiDateText(input.value);
}
function enhanceDateInput(input) {
  if (input.dataset.vsDate) return;
  input.dataset.vsDate = '1';
  const wrap = document.createElement('span');
  wrap.className = 'vs-date';
  input.replaceWith(wrap);
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = `${input.className} vs-date-btn`;
  btn.title = input.title;
  // the button is what the keyboard and a screen reader reach: it takes the field's name, and its keys for a
  // change of the language
  const label = input.getAttribute('aria-label') || input.title;
  if (label) btn.setAttribute('aria-label', label);
  const tKey = input.getAttribute('data-i18n-title'), aKey = input.getAttribute('data-i18n-aria') || tKey;
  if (tKey) btn.setAttribute('data-i18n-title', tKey);
  if (aKey) btn.setAttribute('data-i18n-aria', aKey);
  btn.addEventListener('click', () => { try { input.showPicker(); } catch (e) { input.focus(); } });
  input.tabIndex = -1;
  input.setAttribute('aria-hidden', 'true');
  input.addEventListener('change', () => syncDateField(input));
  wrap.append(input, btn);
  syncDateField(input);
}
function enhanceDateInputs(root) {
  if (root.matches && root.matches('input[type="date"]')) enhanceDateInput(root);
  if (root.querySelectorAll) root.querySelectorAll('input[type="date"]').forEach(enhanceDateInput);
}
(function watchDateInputs() {
  const start = () => {
    enhanceDateInputs(document.body);
    new MutationObserver(list => list.forEach(m => m.addedNodes.forEach(n => { if (n.nodeType === 1) enhanceDateInputs(n); })))
      .observe(document.body, { childList: true, subtree: true });
  };
  if (document.body) start(); else document.addEventListener('DOMContentLoaded', start);
})();

// localStorage belongs to the page's origin, and the origin has the port: when 8765 is busy the app
// starts on the next port, and that launch had no language (an English user got Russian). The server
// keeps the choice too (setting ui_lang); localStorage is only its cache for the first paint.
const UI_PREFS_STORED = (() => { try { return { lang: !!localStorage.getItem('whisper_ui_lang') }; } catch (e) { return {}; } })();
let _uiPrefsSynced = false;

// Once per page, with the first settings from the server (loadSystemInfo)
function syncUiPrefsFromServer(settings) {
  if (_uiPrefsSynced || !settings) return;
  _uiPrefsSynced = true;
  const lang = settings.ui_lang;
  if (lang === 'ru' || lang === 'en') {
    if (lang !== state.uiLang) setUILanguage(lang);
  } else if (UI_PREFS_STORED.lang) {
    saveUiSetting('ui_lang', state.uiLang);  // chosen before the server kept it: it does from now on
  }
  if (typeof dbPrefsFromServer === 'function') dbPrefsFromServer(settings);
}

// A preference of the page kept on the server (and in state.system.settings, so it is not sent twice)
function saveUiSetting(key, value) {
  const set = (state.system && state.system.settings) || null;
  if (set) { if (set[key] === value) return; set[key] = value; }
  fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ settings: { [key]: value } }) }).catch(() => {});
}

function setUILanguage(lang) {
  state.uiLang = lang;
  document.documentElement.lang = lang;
  try { localStorage.setItem('whisper_ui_lang', lang); } catch (e) { /* the server keeps it too */ }
  // the first call (at load) is before the server's settings: it does not overwrite them
  if (_uiPrefsSynced) saveUiSetting('ui_lang', lang);
  // The launcher's splash screen speaks the same language (see /api/ui/lang)
  fetch('/api/ui/lang', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ lang }) }).catch(() => {});

  // Settings -> General -> Interface language
  for (const code of ['ru', 'en']) {
    document.getElementById(`lang-btn-${code}`).className = `apple-segment-btn ${lang === code ? 'apple-segment-active' : 'text-apple-secondary hover:text-white'}`;
  }

  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    el.textContent = t(key);
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    const key = el.getAttribute('data-i18n-placeholder');
    el.setAttribute('placeholder', t(key));
  });
  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    const key = el.getAttribute('data-i18n-title');
    el.setAttribute('title', t(key));
  });
  document.querySelectorAll('[data-i18n-aria]').forEach(el => {
    el.setAttribute('aria-label', t(el.getAttribute('data-i18n-aria')));
  });

  renderMeetingsSidebar();
  loadDictionary();
  // drawn by script, not by data-i18n: drawn again in the new language (found in the audit)
  if (typeof renderMeetingFeatures === 'function') renderMeetingFeatures();
  if (typeof refreshTasksCount === 'function') refreshTasksCount(true);
  if (typeof scheduleFitTopbar === 'function') scheduleFitTopbar();
  if (typeof rpApplyMini === 'function') rpApplyMini();  // the minimize button's title and label
  if (state.system) {
    const p = state.system.paths;
    const dirEl = document.getElementById('settings-data-dir');
    if (p && dirEl) {
      dirEl.textContent = `${t('dataFolder')}: ${p.data}`;
      dirEl.title = `${t('dataFolder')}: ${p.data}\n${t('modelsFolder')}: ${p.models}`;
    }
    updateOllamaUI(state.system.ollama);
    if (state.system.models) updateWhisperModelsUI(state.system.models);
  }
  if (state.activeMeeting) {
    renderSpeakerPillsBar();
    renderSpeakersPanel();
    renderTranscript();
    renderSummaryPanel();
  }
  // Texts the scripts wrote (not data-i18n): drawn again in the new language
  document.querySelectorAll('.vs-date > input').forEach(syncDateField);
  if (typeof renderStatusbar === 'function') renderStatusbar();
  loadSystemInfo().then(() => { if (typeof renderStatusbar === 'function') renderStatusbar(); }).catch(() => {});
  if (typeof scheduleVramRefresh === 'function') scheduleVramRefresh(50);  // the memory badges
  if (typeof renderUpdateStatus === 'function') renderUpdateStatus();
  renderQueuePanel();
  if (typeof renderDictPage === 'function') renderDictPage();  // «Словарь», drawn by its script
  if (typeof renderLoadIndicator === 'function') renderLoadIndicator();  // «Модели не в памяти» of the status bar
  if (state.activeMeeting) { renderTranslationControls(); updateProcessingBanner(state.activeMeeting); }
  if (typeof renderRecordSaveHint === 'function') renderRecordSaveHint();
  applyVideoLayout();
  if (typeof relabelStudioLanguages === 'function') relabelStudioLanguages();
  if (state.appView === 'studio') { renderStudioState(); syncStudioCaptions(); }
  if (state.appView === 'ask') { renderAskScope(); renderAskThread(); }
  if (state.activeWorkspaceTab === 'info' && state.activeMeeting) loadMeetingInfo();
}

// A styled yes/no question (instead of the browser's confirm): resolves true or false.
// Cancel is focused, so Enter does not confirm by accident.
// opts.cancel: the label of the other button; opts.single: one button only (a message, not a question)
// One caret for every menu button and one «+» for every add button (the same line icons, never ▾ or a text plus)
const VX_CARET = '<svg class="vx-caret" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>';
const VX_PLUS = '<svg class="vx-plus" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>';

function confirmDialog(title, text, okLabel, danger = true, opts = {}) {
  return new Promise(resolve => {
    const wrap = document.createElement('div');
    wrap.className = 'fixed inset-0 modal-backdrop z-[70] flex items-center justify-center p-4';
    wrap.setAttribute('role', 'dialog');
    wrap.setAttribute('aria-modal', 'true');
    // the head: a warning in red for what cannot be undone, a question mark for a question, «i» for a message
    const ic = opts.single ? 'info' : danger ? 'over' : 'help';
    wrap.innerHTML = `<div class="vx-dlg vx-dlg-sm modal-card">
      ${vxHead(ic, title, { close: 'data-a="no"', tone: danger && !opts.single ? 'danger' : '' })}
      ${text ? `<p class="vx-dlg-text whitespace-pre-line break-words">${escapeHtml(text)}</p>` : ''}
      <div class="vx-dlg-foot">
        ${opts.single ? '' : `<button data-a="no" class="tk-btn">${escapeHtml(opts.cancel || t('cancel'))}</button>`}
        <button data-a="yes" class="tk-btn ${danger ? 'tk-btn-danger' : 'tk-btn-primary'}">${escapeHtml(okLabel)}</button>
      </div></div>`;
    const done = v => { removeWithExit(wrap); document.removeEventListener('keydown', onKey, true); resolve(v); };
    const onKey = e => { if (e.key === 'Escape') { e.stopPropagation(); done(false); } };
    wrap.addEventListener('click', e => {
      const a = e.target.closest('button[data-a]');
      if (e.target === wrap || (a && a.dataset.a === 'no')) done(false);
      else if (a) done(true);
    });
    document.addEventListener('keydown', onKey, true);
    document.body.appendChild(wrap);
    (wrap.querySelector('.vx-dlg-foot button[data-a="no"]') || wrap.querySelector('button[data-a="yes"]')).focus();
  });
}

// Short forms for the old browser dialogs (window.confirm / prompt / alert), in the app's style.
// danger: the button is red (deleting, discarding); said by the caller, not guessed from the words
// The question is the title and the button names the action («Удалить папку», not «OK»).
// text: the question with its explanation, in either order ("Удалить X? Записи останутся." or
// "Места мало. Начать запись?"); okLabel: the verb of the action
function askConfirm(text, danger = false, okLabel = '') {
  const [title, body] = splitQuestion(text);
  return confirmDialog(title, body, okLabel || t('ok'), danger);
}
function splitQuestion(text) {
  const s = String(text);
  const i = s.indexOf('?');
  if (i < 0) return [t('confirmTitle'), s];
  const rest = s.slice(i + 1).trim();
  if (rest) return [s.slice(0, i + 1).trim(), rest];
  const m = s.match(/^([\s\S]*[.!])\s+([^.!?]+\?)$/);
  return m ? [m[2].trim(), m[1].trim()] : [s.trim(), ''];
}

function askText(label, value = '', opts = {}) {
  return new Promise(resolve => {
    const wrap = document.createElement('div');
    wrap.className = 'fixed inset-0 modal-backdrop z-[70] flex items-center justify-center p-4';
    wrap.setAttribute('role', 'dialog');
    wrap.setAttribute('aria-modal', 'true');
    // the head names what is typed (the title, or the question itself when there is no title)
    wrap.innerHTML = `<form class="vx-dlg vx-dlg-sm modal-card">
      ${vxHead(opts.ic || 'pen', opts.title || label, { close: 'data-a="no"' })}
      ${opts.title ? `<label class="vx-dlg-text whitespace-pre-line">${escapeHtml(label)}</label>` : ''}
      <input type="text" class="vx-field" aria-label="${escapeHtml(label)}" />
      <div class="vx-dlg-foot">
        <button type="button" data-a="no" class="tk-btn">${escapeHtml(t('cancel'))}</button>
        <button type="submit" class="tk-btn tk-btn-primary">${escapeHtml(opts.ok || t('ok'))}</button>
      </div></form>`;
    const input = wrap.querySelector('input');
    input.value = value || '';
    const done = v => { removeWithExit(wrap); document.removeEventListener('keydown', onKey, true); resolve(v); };
    const onKey = e => { if (e.key === 'Escape') { e.stopPropagation(); done(null); } };
    wrap.querySelector('form').addEventListener('submit', e => { e.preventDefault(); done(input.value); });
    wrap.addEventListener('click', e => { if (e.target === wrap || e.target.closest('[data-a="no"]')) done(null); });
    document.addEventListener('keydown', onKey, true);
    document.body.appendChild(wrap);
    input.focus();
    input.select();
  });
}

function showAlert(text) {
  return confirmDialog(t('attentionTitle'), String(text), t('gotIt'), false, { single: true }).then(() => {});
}

// The browser's reasons for not giving a microphone or the screen (DOMException names), in words a user
// can act on; what: 'mic' or 'screen'. Our own messages (a plain Error) are shown as they are.
function mediaErrorText(err, what = 'mic') {
  const name = err && err.name;
  if (what === 'screen') {
    if (name === 'NotAllowedError' || name === 'SecurityError') return t('recErrScreenDenied');
    if (name === 'NotFoundError' || name === 'NotReadableError' || name === 'AbortError' || name === 'NotSupportedError') return t('recErrScreenFailed');
  }
  if (name === 'NotFoundError' || name === 'OverconstrainedError') return t('recErrMicMissing');
  if (name === 'NotAllowedError' || name === 'SecurityError') return t('recErrMicDenied');
  if (name === 'NotReadableError' || name === 'AbortError' || name === 'TrackStartError') return t('recErrMicBusy');
  if (err && typeof DOMException !== 'undefined' && err instanceof DOMException) return t('recErrUnknown');
  return serverText((err && err.message) || String(err || '')) || t('recErrUnknown');
}

// A recording that could not start: the reason and a way to the recording settings (one place for the
// studio, the red button of the top bar and the microphone tests)
async function showMediaError(err, what = 'mic') {
  console.warn('media:', err);
  const go = await confirmDialog(t('recErrTitle'), mediaErrorText(err, what), t('recErrOpenSettings'), false, { cancel: t('close') });
  if (go) openModal('settings', 'record');
}

// A failure as a person reads it: {short} — the cause in words (a lost network, a link that cannot be
// downloaded, or the server's message without the program's paths and exception names), {tech} — the
// whole technical text for «Подробнее» ('' when there is nothing more than the short one)
const NET_ERROR = /403 Forbidden|401 Unauthorized|407 Proxy|ConnectError|ConnectTimeout|ReadTimeout|timed? ?out|Name or service not known|getaddrinfo|Network is unreachable|Connection (refused|reset|aborted)|SSLError|CERTIFICATE_VERIFY|ProxyError|Max retries exceeded|Temporary failure in name resolution/i;
const LINK_ERROR = /^ERROR: \[|Unable to download webpage|Unsupported URL|Video unavailable|Private video|This video is not available|HTTP Error \d{3}/im;
function humanError(raw) {
  const text = String(raw || '').trim();
  if (!text) return { short: '', tech: '' };
  const first = text.split(/\n/)[0].trim();
  let short;
  const model = first.match(/^Не удалось скачать модель (.+?):/);
  if (model && NET_ERROR.test(text)) short = t('errModelNoNet').replace('{model}', () => model[1]);
  else if (LINK_ERROR.test(text)) short = t('errLinkDownload');
  else if (NET_ERROR.test(text)) short = t('errNoNetwork');
  else {
    short = first.replace(/\s*(?:[A-Za-z]:\\|\/)[^\s]*(?:\.py|-packages)[^\s]*/g, '')
      .replace(/^(?:[A-Za-z_][\w.]*(?:Error|Exception)):\s*/, '').replace(/[:;,]\s*$/, '').trim();
    short = serverText(short);
    if (short.length > 180) short = `${short.slice(0, 177)}…`;
  }
  return { short: short || t('errUnknown'), tech: text === short ? '' : text };
}

// A message of the server (always Russian) in the interface language (static/server_text.js)
function serverText(text) {
  if (state.uiLang !== 'en' || typeof text !== 'string' || !text || typeof SERVER_TEXT_EN === 'undefined') return text;
  if (SERVER_TEXT_EN[text]) return SERVER_TEXT_EN[text];
  for (const [ru, en] of SERVER_PATTERNS_EN) {
    const parts = ru.split('{}');
    const re = new RegExp('^' + parts.map(p => p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('([\\s\\S]*?)') + '$');
    const m = text.match(re);
    if (m) return en.replace(/\{(\d)\}/g, (_, i) => serverText(m[Number(i) + 1]));
  }
  return text;
}

// A count with its word, shared by the pages: "1 файл / 2 файла / 5 файлов": the forms are given as "one|few|many" (English: "one|many|many")
function plural(n, forms) {
  const [one, few, many] = forms.split('|');
  const m10 = n % 10, m100 = n % 100;
  const form = state.uiLang === 'en' ? (n === 1 ? one : many)
    : m10 === 1 && m100 !== 11 ? one : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? few : many;
  return `${n} ${form}`;
}

// What a failed answer says, for a toast: FastAPI's "detail" is a text, or a list of invalid fields
function errorText(data, res) {
  const d = data && data.detail;
  if (Array.isArray(d)) return d.map(x => (x && (x.msg || x.message)) || String(x)).join('; ');
  return (typeof d === 'string' && serverText(d)) || `${t('serverError')} (HTTP ${res ? res.status : '?'})`;
}

// A lost session (the server started again with a new token, the cookie is gone): every request then
// answers 401. Instead of a page that silently stops working, the window reloads itself with a fresh
// address (in a browser the user is told to open the app again).
const _nativeFetch = window.fetch.bind(window);
let _sessionLost = false;
window.fetch = async (...args) => {
  const res = await _nativeFetch(...args);
  if (res.status === 401 && !_sessionLost && /^\/api\//.test(String(args[0]))) {
    _sessionLost = true;
    onSessionLost();
  }
  return res;
};

async function onSessionLost() {
  showWarning(t('sessionLost'));
  // In the app window the page reloads and signs in again (app/main.py _LOCKED_PAGE)
  if (window.pywebview && window.pywebview.api) setTimeout(() => location.replace('/'), 1500);
  /* in a browser: the toast says what to do */
}

// The JSON of a response; a non-JSON answer (a server error page) becomes {detail: "..."} instead of
// "Unexpected token ... is not valid JSON" shown to the user
async function readJson(res) {
  const text = await res.text().catch(() => '');
  try {
    const data = text ? JSON.parse(text) : {};
    if (data && typeof data.detail === 'string') data.detail = serverText(data.detail);
    return data;
  } catch (e) {
    return { detail: `${t('serverError')} (HTTP ${res.status})` };
  }
}

// Audit 6.3, 3.11. Four kinds of notices: a status, done (with «Отменить» when it can be undone),
// a warning and an error. An error stays until it is closed and is read out by the screen reader at
// once; the others leave by themselves, but not while the pointer is on them. A new status or done
// notice replaces the previous one; errors and warnings stack, three at most, the newest below
// an error goes away by itself too (reported by the user: it stayed until closed); one with a button stays
const TOAST_LIFE = { status: 3000, success: 3000, warning: 8000, error: 10000 };
const TOAST_ICONS = {
  status: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="8" cy="8" r="6.2"/><path d="M8 7.2v3.6M8 5.1v.1" stroke-linecap="round"/></svg>',
  success: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 8.4l3 3 6-6.4"/></svg>',
  warning: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M8 2.2l6.2 11H1.8z"/><path d="M8 6.6v3M8 11.4v.1"/></svg>',
  error: '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="8" cy="8" r="6.2"/><path d="M5.8 5.8l4.4 4.4M10.2 5.8l-4.4 4.4"/></svg>',
};
function showToast(msg, action, kind) {
  kind = TOAST_LIFE[kind] !== undefined ? kind : (action ? 'success' : 'status');
  const stack = document.getElementById('toast');
  // a notice that is replaced leaves its place at once and fades where it was, so the new one takes the place
  // (asked by the user: the new one showed under the old for a moment and then jumped up)
  const leaveInPlace = (old) => {
    const r = old.getBoundingClientRect();
    Object.assign(old.style, { position: 'absolute', width: `${r.width}px`, pointerEvents: 'none', margin: '0' });
    // the stack is centred on its own width, which changes when the notice leaves the flow: placed after that
    const box = stack.getBoundingClientRect();
    Object.assign(old.style, { top: `${r.top - box.top}px`, left: `${r.left - box.left}px` });
    removeWithExit(old);
  };
  if (kind === 'status' || kind === 'success') {
    stack.querySelectorAll('.toast-status:not(.toast-progress), .toast-success').forEach(old => { if (!old.classList.contains('is-leaving')) leaveInPlace(old); });
  }
  const el = document.createElement('div');
  el.className = `toast toast-${kind}`;
  el.setAttribute('role', kind === 'error' ? 'alert' : 'status');
  el.innerHTML = `<span class="toast-icon" aria-hidden="true">${TOAST_ICONS[kind]}</span><span class="toast-text"></span><span class="toast-life" aria-hidden="true"></span>`;
  el.querySelector('.toast-text').textContent = msg;
  const dismiss = () => { clearTimeout(el._timer); removeWithExit(el); };
  if (action && action.label && typeof action.onClick === 'function') {
    const btn = document.createElement('button');
    btn.className = 'tk-btn tk-btn-sm toast-action';
    btn.textContent = action.label;
    if (action.title) btn.title = action.title;
    btn.onclick = () => { dismiss(); action.onClick(); };
    el.appendChild(btn);
  }
  if (kind === 'warning' || kind === 'error') {
    const x = document.createElement('button');
    x.className = 'vx-x toast-close';
    x.setAttribute('aria-label', t('close'));
    x.textContent = '✕';
    x.onclick = dismiss;
    el.appendChild(x);
  }
  const life = action && kind === 'success' ? 7000 : action && kind === 'error' ? 0 : TOAST_LIFE[kind];
  // the thin line at the bottom shows the life left; it stops while the pointer is on the notice and starts
  // again, over the shorter time, when it leaves
  const line = el.querySelector('.toast-life');
  const arm = (ms) => {
    clearTimeout(el._timer);
    if (ms) el._timer = setTimeout(dismiss, ms);
    line.classList.toggle('hidden', !ms);
    if (ms) { line.style.animationDuration = `${ms}ms`; line.classList.remove('is-on'); void line.offsetWidth; line.classList.add('is-on'); }
  };
  el.addEventListener('mouseenter', () => clearTimeout(el._timer));
  el.addEventListener('mouseleave', () => arm(life && Math.max(1500, life / 2)));
  el.appendChild(line);
  stack.appendChild(el);
  const live = [...stack.children].filter(c => !c.classList.contains('is-leaving'));
  live.slice(0, Math.max(0, live.length - 3)).forEach(leaveInPlace);
  arm(life);
  return dismiss;
}
// A notice that stays while something runs in the background (a file sent to the library) and shows how
// far it is: updated in place, not replaced by other notices; done() takes it away
function progressToast(text) {
  const stack = document.getElementById('toast');
  const el = document.createElement('div');
  el.className = 'toast toast-status toast-progress';
  el.setAttribute('role', 'status');
  el.innerHTML = `<span class="toast-icon" aria-hidden="true">${TOAST_ICONS.status}</span><span class="toast-text"></span>`;
  const label = el.querySelector('.toast-text');
  label.textContent = text;
  stack.appendChild(el);
  return { set: (s) => { label.textContent = s; }, done: () => removeWithExit(el) };
}

// Audit 6.1. A reversible removal happens at once and the notice offers «Отменить» for 7 s; the
// server is told only then (or when the window closes), so undoing needs nothing from it.
// hide() and restore() change the page; commit(keepalive) sends the removal and resolves true
// when it went through (on false the item comes back with an error)
function deleteWithUndo({ message, hide, restore, commit }) {
  hide();
  let settled = false;
  const onLeave = () => { if (!settled) { settled = true; commit(true); } };
  const finish = async () => {
    if (settled) return;
    settled = true;
    window.removeEventListener('pagehide', onLeave);
    const ok = await Promise.resolve(commit(false)).catch(() => false);
    if (ok === false) { restore(); showError(t('errorGeneric')); }
  };
  window.addEventListener('pagehide', onLeave);
  const timer = setTimeout(finish, 7000);
  showToast(message, { label: t('rdSasUndo'), onClick: () => {
    if (settled) return;
    settled = true;
    clearTimeout(timer);
    window.removeEventListener('pagehide', onLeave);
    restore();
  } });
}
function showError(msg, action) { return showToast(msg || t('errorGeneric'), action, 'error'); }
function showWarning(msg, action) { return showToast(msg, action, 'warning'); }

function formatTime(sec) {
  sec = Math.max(0, Number(sec) || 0);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = Math.floor(sec % 60);
  if (h > 0) {
    return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
  }
  return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}

// --- Modals & Menus ---
// Settings are split into tabs; the last one is remembered. A tab holds one or more sections
// ([data-stab]): the sections of the former tabs are listed in SETTINGS_SECTION_TAB, and their old
// names (openModal('settings', 'hotkeys'), "settings:hotkeys" of a notification, #settings/models)
// open the tab and scroll to the section
const SETTINGS_TABS = ['general', 'record', 'recognition', 'analysis', 'calendar', 'export', 'privacy', 'advanced'];
const SETTINGS_SECTION_TAB = {
  updates: 'general', about: 'general',
  hotkeys: 'record',
  models: 'recognition', dictionary: 'recognition',
  bench: 'advanced', dub: 'advanced',
};
const SETTINGS_TAB_ALIASES = { integrations: 'export', interface: 'general', ui: 'general', ai: 'analysis', dict: 'dictionary', recog: 'recognition' };
function settingsTabOf(section) {
  return SETTINGS_SECTION_TAB[section] || section;
}
function selectSettingsTab(name) {
  name = SETTINGS_TAB_ALIASES[name] || name;
  const section = SETTINGS_SECTION_TAB[name] ? name : null;  // a section inside a tab: scrolled to
  name = settingsTabOf(name);
  if (!SETTINGS_TABS.includes(name)) name = 'general';
  const changed = document.getElementById('modal-settings').dataset.tab !== name;
  document.querySelectorAll('#modal-settings [data-stab]').forEach(el => {
    const on = settingsTabOf(el.dataset.stab) === name;
    el.classList.toggle('hidden', !on);
    // another tab fades in, like the views of the program (asked by the user: Settings changed abruptly)
    if (on && changed) animateIn(el);
  });
  SETTINGS_TABS.forEach(k => {
    const btn = document.getElementById(`stab-${k}`);
    if (!btn) return;
    btn.classList.toggle('is-active', k === name);
    if (k === name) btn.setAttribute('aria-current', 'page'); else btn.removeAttribute('aria-current');
  });
  document.getElementById('modal-settings').dataset.tab = name;
  try { localStorage.setItem('verbaliox_settings_tab', name); } catch (e) {}
  if (name === 'advanced' && typeof loadBench === 'function') loadBench();
  if (typeof onSettingsTabShown === 'function') onSettingsTabShown(name);  // static/js/settings.js
  if (section) scrollToSettingsSection(section);
}

function scrollToSettingsSection(section) {
  const el = document.querySelector(`#modal-settings [data-stab="${section}"]`);
  if (!el) return;
  el.scrollIntoView({ block: 'start' });
  // once more after the layout: the page may have just been mounted or shown
  requestAnimationFrame(() => el.scrollIntoView({ block: 'start' }));
}

// Keyboard: an opened window takes the focus, Tab stays inside the top one, and the focus goes back
// to where it was when the window closes
const _modalReturnFocus = {};

function focusablesIn(root) {
  return [...root.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')]
    .filter(el => !el.disabled && el.tabIndex >= 0 && el.getClientRects().length);  // shown (offsetParent is null for fixed ones), in the tab order
}

document.addEventListener('keydown', e => {
  if (e.key !== 'Tab') return;
  const open = [...document.querySelectorAll('[aria-modal="true"]')].filter(el => !el.classList.contains('hidden') && el.getClientRects().length).pop();
  if (!open) return;
  const items = focusablesIn(open);
  if (!items.length) return;
  const first = items[0], last = items[items.length - 1];
  if (!open.contains(document.activeElement)) { e.preventDefault(); first.focus(); }
  else if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
});

// Rows and items made of <div role="button" tabindex="0">: Enter and Space click them, as a button
document.addEventListener('keydown', e => {
  if ((e.key !== 'Enter' && e.key !== ' ') || e.target.tagName === 'BUTTON' || !e.target.matches?.('[role="button"][tabindex="0"]')) return;
  e.preventDefault();
  e.target.click();
});

function openModal(name, tab) {
  if (name === 'settings') mountSettingsPage();  // the settings are a page of the main area (shell.js)
  // «Очередь» and «Нагрузка» stand above the windows (z 60): they close when a window opens
  if (typeof closeJobsPop === 'function') closeJobsPop();
  if (typeof closeLoadPop === 'function') closeLoadPop();
  const modal = document.getElementById(`modal-${name}`);
  _modalReturnFocus[name] = document.activeElement;
  if (name !== 'settings') {
    modal.setAttribute('role', 'dialog');
    modal.setAttribute('aria-modal', 'true');
  }
  cancelLeave(modal);
  modal.classList.remove('hidden');
  if (name === 'settings' && state.appView !== 'settings') switchAppView('settings');
  setTimeout(() => {
    if (modal.contains(document.activeElement)) return;
    // the search of Settings, not «Закрыть»; a window with nothing to fill marks its own start (data-autofocus)
    const first = name === 'settings' ? document.getElementById('settings-search') : modal.querySelector('[data-autofocus]');
    // Audit 7.2: the first field or action, not the ✕ of the window (Enter must not close it)
    const items = focusablesIn(modal);
    (first || items.find(el => !el.matches('.dlg-x, .imp-x, .vx-x')) || items[0] || modal).focus();
  }, 60);
  if (name === 'import') onImportDialogOpen();  // importdlg.js: the list, the processing from the settings
  if (name === 'settings') {
    let last = null;
    try { last = localStorage.getItem('verbaliox_settings_tab'); } catch (e) {}
    selectSettingsTab(tab || last || 'general');
    syncSettingsFormFromState();  // settings.js: what the import window and the home page changed since
    loadVoiceProfiles();
    loadDubInfo();
    populateAudioInputDevices();
    refreshExportDirLabel();
    refreshRecordingsDirLabel();
    refreshObsidianStatus();
    nextFrame(() => drawIdleSoundCloudBars('settings-waveform-canvas'));
  }
}
// Voice profiles only work with speaker separation: dimmed while it is off
function syncVoiceProfilesToggle() {
  const on = document.getElementById('set-diarization')?.checked !== false;
  const box = document.getElementById('voice-profiles-box');
  if (!box) return;
  box.style.opacity = on ? '' : '0.45';
  document.getElementById('set-voice-profiles').disabled = !on;
}

// --- Voice profiles (Settings): names remembered from earlier recordings ---
async function loadVoiceProfiles() {
  const box = document.getElementById('voice-profiles-list');
  if (!box) return;
  try {
    const res = await fetch('/api/voice-profiles');
    renderVoiceProfiles(await readJson(res));
  } catch (e) {
    box.innerHTML = '';
  }
}

function renderVoiceProfiles(data) {
  const box = document.getElementById('voice-profiles-list');
  const list = (data && data.profiles) || [];
  if (!list.length) {
    box.innerHTML = `<div class="text-[11.5px] text-apple-tertiary">${escapeHtml(t('voiceProfilesNone'))}</div>`;
    return;
  }
  box.innerHTML = list.map(p => `
    <div class="flex items-center justify-between gap-2 text-xs">
      <span class="text-apple-label truncate">${escapeHtml(p.name)}
        <span class="text-apple-tertiary">· ${escapeHtml(t('voiceProfileSamples').replace('{n}', () => p.samples))}</span></span>
      <button data-click="deleteVoiceProfile" data-click-args='[${Number(p.id)}, {"$": "data", "k": "name"}]' data-name="${escapeHtml(p.name)}"
        class="ui-btn ui-btn-subtle h-6 px-2 text-[11.5px] text-apple-red" title="${escapeHtml(t('tipVoiceProfileDelete'))}">${escapeHtml(t('voiceProfileDelete'))}</button>
    </div>`).join('');
}

async function applyVoiceProfilesToLibrary() {
  const res = await fetch('/api/voice-profiles/apply-all', { method: 'POST' });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) { showError(data.detail); return; }
  showToast(data.speakers ? t('voiceApplyAllDone').replace('{n}', () => data.speakers).replace('{m}', () => data.meetings) : t('voiceApplyAllNone'));
  if (data.speakers) {
    await loadMeetingsList();
    if (state.activeMeeting) selectMeeting(state.activeMeeting.id, false);
  }
}

async function deleteVoiceProfile(id, name) {
  if (!await askConfirm(t('voiceProfileDeleteConfirm').replace('{name}', () => name || ''), true, t('cfDeleteProfile'))) return;
  const res = await fetch(`/api/voice-profiles/${id}`, { method: 'DELETE' });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    showError(data.detail);
    return;
  }
  renderVoiceProfiles(data);
}

function closeModal(name) {
  if (name === 'settings') {
    stopSettingsAudioTest();
  }
  if (name === 'about') endAboutEgg();  // the transcript of the room does not go on unseen
  const modal = document.getElementById(`modal-${name}`);
  if (name === 'settings') modal.classList.add('hidden');
  else hideWithExit(modal);
  // The settings page: back to the view it was opened from
  if (name === 'settings' && state.appView === 'settings') switchAppView(state.prevView || 'home');
  const back = _modalReturnFocus[name];
  if (back && document.contains(back)) back.focus();
}
function closeModalOnBackdrop(e, name) {
  if (e.target === e.currentTarget) closeModal(name);
}

// Audit 4.5. Scrolled lists fade into their edges instead of being cut by a line: the top edge
// fades only once the list is scrolled, the bottom one while there is more below
function softEdges(el) {
  if (!el || el._softEdges) return;
  el._softEdges = true;
  el.classList.add('soft-edges');
  const update = () => {
    el.classList.toggle('se-top', el.scrollTop > 2);
    el.classList.toggle('se-bottom', el.scrollTop + el.clientHeight < el.scrollHeight - 2);
  };
  el.addEventListener('scroll', update, { passive: true });
  if (window.ResizeObserver) new ResizeObserver(update).observe(el);
  if (window.MutationObserver) new MutationObserver(update).observe(el, { childList: true, subtree: true });
  update();
}
document.addEventListener('DOMContentLoaded', () => {
  ['transcript-container', 'an-main', 'library-answer', 'wview-speakers', 'wview-info'].forEach(id => softEdges(document.getElementById(id)));
});

// A press inside a dialog released over its backdrop (a text selection dragged out of a field)
// reaches the backdrop as a click: that is not a click on the backdrop, so no dialog closes on it
let _pressTarget = null;
document.addEventListener('pointerdown', e => { _pressTarget = e.target; }, true);
window.addEventListener('click', e => {
  const t = e.target;
  if (t === _pressTarget || !(t instanceof Element)) return;
  if (t.classList.contains('modal-backdrop') || t.classList.contains('tk-veil')) e.stopPropagation();
}, true);

// The motion chosen with the user on the try-on page: the new view fades in, the highlight of the tab
// moves to it (static/js/shell.js placeTabIndicators), the widgets of Главная come in one after another
function animateIn(el) {
  if (!el) return;
  el.classList.remove('vx-in');
  void el.offsetWidth;  // restarts the animation
  el.classList.add('vx-in');
}

function switchWorkspaceTab(tab) {
  const prevTab = state.activeWorkspaceTab;
  state.activeWorkspaceTab = tab;
  if (typeof navRecord === 'function') navRecord();
  if (typeof renderTopbar === 'function') renderTopbar();
  if (tab === 'info') loadMeetingInfo();
  ['transcript', 'summary', 'speakers', 'info'].forEach(k => {
    document.getElementById(`wview-${k}`).classList.toggle('hidden', k !== tab);
    const btn = document.getElementById(`wtab-${k}`);
    btn.className = (k === tab)
      ? 'apple-segment-btn apple-segment-active'
      : 'apple-segment-btn text-apple-secondary hover:text-white';
  });
  if (prevTab && prevTab !== tab) animateIn(document.getElementById(`wview-${tab}`));
}

function toggleExportMenu(e) {
  e.stopPropagation();
  hideContextMenu();
  hideTranslateMenu();
  const menu = document.getElementById('export-menu');
  if (menu.classList.contains('hidden')) renderExportMenu();
  menu.classList.toggle('hidden');
}

function hideExportMenu() {
  document.getElementById('export-menu')?.classList.add('hidden');
}

// Esc closes the dialogs made on the fly that have no keyboard handling of their own (found in the audit:
// Esc closed Settings under a dialog and left the dialog open). Their own ✕ is pressed, so a dialog
// that asks before closing still asks; the event goes no further, the window below stays
const ESC_DIALOGS = ['templates-editor', 'an-tpl-dlg', 'open-commitments'];
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape' || e.defaultPrevented) return;
  const open = ESC_DIALOGS.map(id => document.getElementById(id)).filter(Boolean);
  if (!open.length) return;
  const top = open.reduce((a, b) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? b : a));
  // A question opened over it (askConfirm, askText) answers its own Esc: the window under it stays
  const over = [...document.querySelectorAll('.modal-backdrop')].pop();
  if (over && over !== top && !top.contains(over) && (top.compareDocumentPosition(over) & Node.DOCUMENT_POSITION_FOLLOWING)) return;
  const x = top.querySelector('[data-a="close"], [data-a="no"]');
  e.preventDefault();
  e.stopPropagation();
  if (x) x.click(); else top.remove();
}, true);

// --- Menus and popovers: one at a time, Esc closes the one on top, a second press of its button closes it ---
// (reviews: «● Запись ▾» and «Импорт ▾» stayed open together; one Esc closed «Нагрузка» and left the settings, or
// closed «Показатели» and the drawer under it; several menus did not close on Esc or on a second click.) Each
// menu is listed here with how to tell it is open and how to close it; the order of opening is seen in the page
// itself (a MutationObserver), so the menus need not report it. kind 'menu': one at a time; 'mode' (the drawer of
// «Обзор», its «Настроить»): closed by Esc in its turn, but opening a menu leaves it; 'modal': a window above,
// whose Esc is its own
const vxShown = (id) => { const el = document.getElementById(id); return !!el && !el.classList.contains('hidden') && !el.classList.contains('is-leaving'); };
const vxThere = (id) => { const el = document.getElementById(id); return !!el && !el.classList.contains('is-leaving'); };
const vxHide = (id) => () => document.getElementById(id)?.classList.add('hidden');
const vxRemove = (id) => () => document.getElementById(id)?.remove();
const vxCall = (fn) => () => { if (typeof window[fn] === 'function') window[fn](); };
const vxTry = (f) => () => { try { return f(); } catch (e) { return false; } };
const VX_LAYERS = [
  ['text-menu', () => vxThere('text-menu'), vxCall('closeTextMenu'), '#text-menu'],
  ['rec-menu', () => vxThere('rec-menu'), vxRemove('rec-menu'), '#rec-menu'],
  ['imp-menu', () => vxThere('imp-menu'), vxCall('closeImportMenu'), '#imp-menu'],
  ['translate-menu', () => vxShown('translate-menu'), vxCall('hideTranslateMenu'), '#translate-menu'],
  ['export-menu', () => vxShown('export-menu'), vxCall('hideExportMenu'), '#export-menu'],
  ['recording-context-menu', () => vxShown('recording-context-menu'), vxCall('hideContextMenu'), '#recording-context-menu'],
  ['folder-context-menu', () => vxShown('folder-context-menu'), vxCall('hideFolderMenu'), '#folder-context-menu'],
  ['tx-view-menu', () => vxShown('tx-view-menu'), vxHide('tx-view-menu'), '#tx-view-menu'],
  ['tx-proc-menu', () => vxShown('tx-proc-menu'), vxHide('tx-proc-menu'), '#tx-proc-menu'],
  ['record-preset-menu', () => vxShown('record-preset-menu'), vxHide('record-preset-menu'), '#record-preset-menu'],
  ...['bulk-menu', 'series-menu', 'digest-menu', 'lib-view-menu', 'lib-filter-menu', 'as-menu', 'an-cfg-pop']
    .map(id => [id, () => vxThere(id), vxRemove(id), `#${id}`]),
  ['quick-lang-menu', () => vxThere('quick-lang-menu'), vxCall('closeQuickLangMenu'), '#quick-lang-menu'],
  ['tk-pop', () => vxThere('tk-pop'), vxCall('tkClosePop'), '#tk-pop'],
  ['hm-day-pop', () => vxShown('hm-day-pop'), () => {
    document.getElementById('hm-day-pop')?.classList.add('hidden');
    document.getElementById('hm-day-btn')?.setAttribute('aria-expanded', 'false');
  }, '#hm-day-pop'],
  ['lt-cols', vxTry(() => LT.colsOpen), vxCall('closeLibTableColumnsMenu'), '#lt-cols-pop'],
  ['jobs-pop', vxTry(() => jobs.open), vxCall('closeJobsPop'), '#jobs-pop'],
  ['load-pop', vxTry(() => load.open), vxCall('closeLoadPop'), '#load-pop'],
  ['models-pop', vxTry(() => modelsPop.open), vxCall('closeModelsPop'), '#models-pop'],
  ['rp-pop', vxTry(() => !!rp.open), vxCall('rpClosePop'), '.rp-pop:not(.hidden)'],
  ['kpi-cfg', vxTry(() => DB.kpiCfg && state.appView === 'dashboard'), () => { DB.kpiCfg = false; dbKpiRedraw(); }, '.db-kc'],
  ['db-detail', vxTry(() => !!DB_DETAIL.kind && state.appView === 'dashboard'), vxCall('dbCloseDetail'), '#db-detail', 'mode'],
  ['db-edit', vxTry(() => DB.edit && state.appView === 'dashboard'), vxCall('toggleDashEdit'), '#db-grid', 'mode'],
  ['modal', () => !!document.querySelector('.modal-backdrop:not(.hidden), #upd-after')
    || [...document.querySelectorAll('[id^="modal-"]:not(.hidden)')].some(m => !m.closest('#settings-view')), () => {}, '', 'modal'],
].map(([name, isOpen, close, sel, kind]) => ({ name, isOpen, close, sel, kind: kind || 'menu', open: false, at: 0, owner: null, ownerEl: null }));

// The button a menu belongs to, by a key that survives a redraw of the bar it is in (the filter bar of «Записи»,
// the overview's head): its id, a data-menu-key, or what it calls
function vxOwnerKey(el) {
  if (!el) return '';
  return el.id || el.dataset.menuKey || (el.dataset.click ? `${el.dataset.click}|${el.dataset.clickArgs || ''}` : '');
}
const vxOwnerOf = (t) => (t instanceof Element ? t.closest('button, [role="button"], [aria-haspopup], [data-click]') : null);
let vxPress = { key: '', el: null, at: 0 }, vxSwallow = { key: '', until: 0 }, vxSeq = 0;

function vxLayerEl(l) { return l.sel ? document.querySelector(l.sel) : null; }

function vxSyncLayers() {
  for (const l of VX_LAYERS) {
    const open = !!l.isOpen();
    if (open && !l.open) {
      l.at = ++vxSeq;
      const recent = performance.now() - vxPress.at < 800;
      l.owner = recent ? vxPress.key : null;
      l.ownerEl = recent ? vxPress.el : null;
      if (l.kind === 'menu') closeAllMenus(l, vxPress.el);
    }
    // the button that opened a menu says whether it is open (screen readers), whichever menu it is
    if (open !== l.open && l.ownerEl && l.ownerEl.hasAttribute('aria-haspopup')) l.ownerEl.setAttribute('aria-expanded', String(open));
    l.open = open;
  }
}

// Closes every open menu but one (the one just opened); a menu holding the button that opened it stays (a menu
// opened from another one)
function closeAllMenus(keep, from) {
  for (const l of VX_LAYERS) {
    if (l === keep || l.kind !== 'menu' || !l.isOpen()) continue;
    const el = vxLayerEl(l);
    if (from && el && el.contains(from)) continue;
    l.close();
  }
}

new MutationObserver(vxSyncLayers).observe(document.documentElement, { subtree: true, childList: true, attributes: true, attributeFilter: ['class', 'id'] });

// A press of a menu's own button while it is open: the menu closes, and the click that follows does not open it again
function vxPressOwner(e, el) {
  const key = vxOwnerKey(el);
  vxPress = { key, el, at: performance.now() };
  if (!key) return false;
  // a button inside the menu calling the same (its «Готово») is the menu's own, not its owner
  const l = VX_LAYERS.find(x => x.kind === 'menu' && x.owner === key && x.isOpen() && !vxLayerEl(x)?.contains(el));
  if (!l) return false;
  l.close();
  vxSwallow = { key, until: performance.now() + 1000 };
  return true;
}
window.addEventListener('pointerdown', (e) => {
  if (e.button !== 0) { vxPress = { key: '', el: null, at: 0 }; return; }
  vxPressOwner(e, vxOwnerOf(e.target));
}, true);
window.addEventListener('click', (e) => {
  if (!vxSwallow.key || performance.now() > vxSwallow.until) return;
  const key = vxOwnerKey(vxOwnerOf(e.target)), want = vxSwallow.key;
  vxSwallow = { key: '', until: 0 };
  if (key && key === want) { e.preventDefault(); e.stopImmediatePropagation(); }
}, true);

window.addEventListener('keydown', (e) => {
  if ((e.key === 'Enter' || e.key === ' ') && !e.repeat) {
    // the keyboard's press of a button: the same as a click for the owner of a menu
    const el = vxOwnerOf(document.activeElement);
    if (el && !(el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') && vxPressOwner(e, el)) { e.preventDefault(); e.stopImmediatePropagation(); }
    return;
  }
  if (e.key !== 'Escape' || e.isComposing) return;
  if (typeof DB !== 'undefined' && DB.drag) return;  // a widget being dragged: its own Esc puts it back
  const open = VX_LAYERS.filter(l => l.isOpen());
  if (!open.length) return;
  const top = open.reduce((a, b) => (b.at > a.at ? b : a));
  if (top.kind === 'modal') return;  // a window above the menus answers its own Esc
  e.preventDefault();
  e.stopImmediatePropagation();
  const back = top.ownerEl && top.ownerEl.isConnected ? top.ownerEl : null;
  top.close();
  const f = document.activeElement;
  if (back && (!f || f === document.body || !f.isConnected || vxLayerEl(top)?.contains(f))) back.focus();
}, true);
