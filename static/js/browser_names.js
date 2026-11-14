// Loaded before the page's own scripts: every name the browser (and the vendored Markdown libraries)
// put on window. A data-* handler (core.js runPageHandler) may only name a function of the page's own
// scripts; a browser function wrapped by the page (window.fetch, see core.js) still is the browser's.
window.BROWSER_NAMES = new Set(Object.getOwnPropertyNames(window));
