// Verbaliox page script: one card everywhere («Пульт встреч», docs/pult-plan.md). The line icons of the
// kinds of cards, and the head of a card: the icon in a square, the name and a number on the right. The
// tasks, the people, the dictionary, the settings and the window after an update draw their cards with it.
// The parts are classic scripts sharing one global scope, loaded in order by index.html.

const PULT_IC = {
  meet: '<rect x="4" y="5.5" width="16" height="14.5" rx="2"/><path d="M4 10h16M8.5 3.5v4M15.5 3.5v4"/>',
  task: '<path d="M4.5 7.5l2 2 3-3.5M4.5 15.5l2 2 3-3.5M13 8h7M13 16h7"/>',
  dec: '<path d="M5 12.5l4 4L19 7"/>',
  people: '<circle cx="9" cy="9" r="3.2"/><path d="M3.5 19c.8-3 3-4.5 5.5-4.5s4.7 1.5 5.5 4.5M16 6.5a3 3 0 010 5.5M17.5 14.6c1.6.6 2.6 2 3 4.4"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  chart: '<path d="M4 20h16M7 17v-4M12 17V8M17 17v-6"/>',
  spark: '<path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z"/>',
  globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.3 2.4 3.4 5.2 3.4 8.5s-1.1 6.1-3.4 8.5c-2.3-2.4-3.4-5.2-3.4-8.5s1.1-6.1 3.4-8.5z"/>',
  tag: '<path d="M4 12V5a1 1 0 011-1h7l8 8-8 8z"/><circle cx="8.5" cy="8.5" r="1.3"/>',
  text: '<path d="M4 6h16M4 10h16M4 14h10"/>',
  rec: '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="3.5"/>',
  over: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5v5M12 16v.5"/>',
  set: '<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>',
  book: '<path d="M12 6.5C10.5 5.3 8.3 4.8 4 5v13c4.3-.2 6.5.3 8 1.5 1.5-1.2 3.7-1.7 8-1.5V5c-4.3-.2-6.5.3-8 1.5z"/><path d="M12 6.5v13"/>',
  note: '<path d="M5 4h10l4 4v12H5z"/><path d="M15 4v4h4M8.5 12h7M8.5 16h5"/>',
  mark: '<path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8L3.5 9.7l5.9-.9z"/>',
  wave: '<path d="M4 10v4M8 7v10M12 4v16M16 8v8M20 11v2"/>',
  link: '<path d="M14 4h6v6M20 4l-8.5 8.5M18 14v5a1 1 0 01-1 1H5a1 1 0 01-1-1V7a1 1 0 011-1h5"/>',
  lock: '<rect x="5" y="10.5" width="14" height="9.5" rx="2"/><path d="M8.5 10.5V7.5a3.5 3.5 0 017 0v3"/>',
  flask: '<path d="M9.5 3.5h5M10.5 3.5v6L5 18.5a1.3 1.3 0 001.1 2h11.8a1.3 1.3 0 001.1-2l-5.5-9v-6M7.5 15h9"/>',
  key: '<circle cx="8" cy="15" r="3.5"/><path d="M10.5 12.5L19 4M16 7l2.5 2.5M14 9l2 2"/>',
  mic: '<rect x="9" y="3.5" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0013 0M12 18v2.5"/>',
  send: '<path d="M12 19V5M6 11l6-6 6 6"/>',
  stop: '<rect x="7" y="7" width="10" height="10" rx="1.5"/>',
  play: '<path d="M8 5.5v13l10.5-6.5z"/>',
};

// The drawing of an icon (the stroke follows the colour of the text around it)
function pultIcon(k, cls = '') {
  return `<svg${cls ? ` class="${cls}"` : ''} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${PULT_IC[k] || PULT_IC.text}</svg>`;
}

// The head of a card: the icon of its kind in a square, the name, its number; `side` (a button, a link)
// stays on the right
function pultCardHead(title, n, ic, side = '') {
  return `<h3 class="pcd-h"><span class="pcd-ic">${pultIcon(ic)}</span><span class="pcd-t">${escapeHtml(title)}${n != null && n !== '' ? `<b class="pcd-n">${escapeHtml(String(n))}</b>` : ''}</span>${side ? `<span class="pcd-side">${side}</span>` : ''}</h3>`;
}

// A whole card: its head and what it holds (html); `cls` adds a tone («pcard-over» — red)
function pultCard(title, n, ic, inner, cls = '', side = '') {
  return `<section class="pcard${cls ? ` ${cls}` : ''}">${pultCardHead(title, n, ic, side)}${inner}</section>`;
}
