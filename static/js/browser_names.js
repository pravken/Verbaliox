// Loaded before the page's own scripts: what the browser (and the vendored Markdown libraries) put on
// window, by name. A data-* handler (core.js pageFunction) may only call a function of the page's own
// scripts: a name whose value is still the browser's is refused. A page function that took a browser's
// name (a newer WebView2 adding a global) is the page's and still works.
window.BROWSER_VALUES = new Map(Object.getOwnPropertyNames(window).map(n => {
  try { return [n, window[n]]; } catch (e) { return [n, undefined]; }
}));
