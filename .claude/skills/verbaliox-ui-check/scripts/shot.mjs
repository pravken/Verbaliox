// A screenshot of one state of the page, to look at a design (run through serve.sh, which sets BASE).
//   node shot.mjs <out.png> [--view dashboard|home|assistant] [--js "<code run in the page>"]
//        [--width 1400] [--height 900] [--clip x,y,w,h] [--wait 1500] [--scale 2]
// The first-run wizard is closed; page errors are printed. Run from the repository root (Playwright is found
// there), e.g.: serve.sh -- node .claude/skills/verbaliox-ui-check/scripts/shot.mjs /tmp/a.png --view dashboard
import { chromium } from 'playwright';

const args = process.argv.slice(2);
const out = args.shift();
const opt = (name, dflt) => { const i = args.indexOf(`--${name}`); return i >= 0 ? args[i + 1] : dflt; };
if (!out || out.startsWith('--')) { console.error('shot.mjs <out.png> [--view …] [--js …] [--clip x,y,w,h]'); process.exit(2); }
const base = process.env.BASE || 'http://127.0.0.1:8797';
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: +opt('width', 1400), height: +opt('height', 900) }, deviceScaleFactor: +opt('scale', 2) });
page.on('pageerror', e => console.log('page error:', e.message));
await page.goto(`${base}/?token=${process.env.TOKEN || 'smoke'}`);
await page.waitForTimeout(2500);
await page.evaluate(() => document.getElementById('first-run-wizard')?.remove());
const view = opt('view');
if (view) await page.evaluate(v => switchAppView(v), view);
const js = opt('js');
if (js) await page.evaluate(js);
await page.waitForTimeout(+opt('wait', 1500));
const clip = opt('clip');
const [x, y, w, h] = clip ? clip.split(',').map(Number) : [];
await page.screenshot({ path: out, ...(clip ? { clip: { x, y, width: w, height: h } } : {}) });
await browser.close();
console.log(out);
