// Browser scenarios (audit 8.12): the smoke test only catches script errors, these walk the usual paths
// and check what the user would see at each step: first run, import, reading, export, undo, the Studio.
// Needs a running server over the demo data of tests/ui/seed.py (CI: .github/workflows/ci.yml):
//   node tests/ui/scenarios.mjs        (BASE=http://127.0.0.1:8799 TOKEN=smoke; SHOTS=<folder> saves a
//                                       screenshot after each step)
import { mkdirSync } from 'node:fs';

const pw = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.BASE || 'http://127.0.0.1:8799';
const token = process.env.TOKEN || 'smoke';
const shots = process.env.SHOTS || '';
if (shots) mkdirSync(shots, { recursive: true });

const browser = await pw.chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
const page = await browser.newPage({ viewport: { width: 1300, height: 860 } });
page.setDefaultTimeout(8000);
// FAKE_NOW=2026-11-22T21:30:00Z: the page lives at that moment (a weekend evening, the last day of a month…)
if (process.env.FAKE_NOW) await page.clock.install({ time: new Date(process.env.FAKE_NOW) });
// CPU_SLOW=6: the page runs as on a slow computer (CI), to bring out what only fails there
if (process.env.CPU_SLOW) await (await page.context().newCDPSession(page)).send('Emulation.setCPUThrottlingRate', { rate: Number(process.env.CPU_SLOW) });
const errors = [];
page.on('pageerror', e => errors.push(`page: ${e.message}`));
page.on('response', r => { if (r.status() >= 500) errors.push(`HTTP ${r.status()} ${r.url().replace(/\?.*/, '')}`); });

let n = 0;
// the window after an update opens by itself once the page has read the settings (after a reload of an earlier
// step) and stood over the next steps (CI: «#upd-after intercepts pointer events»): closed before and after each
// step but its own, with a note naming where it was found
const closeUpdAfter = async (name, when) => {
  if (name === 'window after an update') return;
  const upd = await page.evaluate(() => { const w = document.getElementById('upd-after'); if (!w) return false;
    if (typeof closeAfterUpdate === 'function') closeAfterUpdate(); else w.remove(); return true; }).catch(() => false);
  if (upd) console.log(`note: the window after an update was open ${when} «${name}»`);
};
const step = async (name, fn) => {
  await closeUpdAfter(name, 'before');
  try { await fn(); } catch (e) {
    // the first line, and for a click that timed out what stood in its way (CI shows nothing else)
    const why = e.message.split('\n').filter(l => /intercepts pointer|not visible|not stable|not enabled|outside of the viewport|waiting for/.test(l)).slice(-3).map(l => l.trim());
    errors.push(`${name}: ${e.message.split('\n')[0]}${why.length ? ` [${why.join(' | ')}]` : ''}`);
  }
  if (shots) await page.screenshot({ path: `${shots}/${String(++n).padStart(2, '0')}-${name.replace(/\W+/g, '-')}.png` });
  // a question window a step left open (a confirmation, a dialog drawn by a script) would stand over the next steps:
  // it is closed, and its title is printed with the step's name so the step can be fixed
  await closeUpdAfter(name, 'after');
  const left = await page.evaluate(() => [...document.querySelectorAll('div.modal-backdrop[role="dialog"]:not([id])')]
    .filter(d => !d.classList.contains('hidden')).map(d => { const h = (d.querySelector('h2, h3, .font-semibold') || d).textContent.trim().slice(0, 60); d.remove(); return h; }))
    .catch(() => []);
  if (left.length) console.log(`note: «${name}» left a window open: ${left.join(' | ')}`);
};
const expect = (ok, what) => { if (!ok) throw new Error(what); };
const sleep = (ms) => page.waitForTimeout(ms);
// waits until fn (run in the page, with arg) is true: a condition, not a fixed pause that a slow runner outlasts
const until = async (fn, what, ms = 5000, arg) => {
  const end = Date.now() + ms;
  for (;;) {
    if (await page.evaluate(fn, arg).catch(() => false)) return;
    if (Date.now() > end) throw new Error(what);
    await sleep(100);
  }
};

await page.goto(`${base}/?token=${token}`);
await sleep(2000);
await page.evaluate(() => document.getElementById('first-run-wizard')?.remove());

// First run: the banner of the settings leads to the models, not «below» (1.6)
await step('first run banner', async () => {
  await page.evaluate(() => { openModal('settings', 'recognition'); document.getElementById('first-run-banner').classList.remove('hidden'); });
  await sleep(400);
  await page.click('#first-run-banner button');
  await sleep(300);
  expect(await page.evaluate(() => !document.querySelector('[data-stab="models"]').classList.contains('hidden')), 'the models tab did not open');
  await page.evaluate(() => closeModal('settings'));
});

// Import: the model, the language and the speakers in sight, the processing behind «Изменить» (8.3) in a mode of
// its own (files, folder, link); «Все параметры» opens with it
await step('import window', async () => {
  await page.evaluate(() => openImportDialog({ mode: 'files' }));
  await sleep(400);
  expect(await page.isVisible('#upload-model') && await page.isVisible('#upload-language') && await page.isVisible('#upload-speakers'), 'model, language or speakers not shown');
  expect(!(await page.isVisible('#imp-sound')), 'the rare options are open');
  await page.click('#imp-more-btn');
  await sleep(200);
  expect(await page.isVisible('#imp-sound'), '«Изменить» did not open the options');
  await page.evaluate(() => closeModal('import'));
  await sleep(250);
});

// Reading: a recording opens with its text; the recognition is one button that says it opens («версии и
// действия ▾», asked by the user: two rows always in sight for what is done once); it opens the row, with
// the precise mode among its choices. «Без запинок» and «Автопрокрутка» are in the view menu
await step('read a recording', async () => {
  await page.evaluate(() => openMeeting(1));
  await until(() => document.querySelectorAll('#transcript-container .segment-row').length > 0, 'no transcript lines', 8000);
  expect(!(await page.isVisible('#tx-model-bar')), 'the recognition row is not folded');
  // one short row (variant B): «Модель: … ▾», «Расшифровать заново», «⋯» and when the text was made
  expect(/Модель:/.test(await page.textContent('#tx-model-chip')), 'no model button');
  expect(await page.isVisible('#tx-redo-btn') && await page.isVisible('#tx-more-btn'), 'the row lacks its buttons');
  await page.click('#tx-model-chip');
  await sleep(200);
  const versions = await page.$$eval('#text-menu button', els => els.map(e => e.textContent));
  // the version shown is told by the accent (aria-current), not by a «✓»
  expect(await page.locator('#text-menu button.tm-on[aria-current="true"]').count() === 1, `the version shown is not marked: ${versions.join(' | ')}`);
  expect(!versions.some(x => x.includes('✓')), `a tick is left in the menu: ${versions.join(' | ')}`);
  await page.keyboard.press('Escape');
  await page.click('#tx-more-btn');
  await sleep(200);
  const more = await page.$$eval('#text-menu button', els => els.map(e => e.textContent));
  expect(more.some(x => /Удалить эту версию/.test(x)) && more.some(x => /Все модели и параметры/.test(x)), `the «⋯» menu: ${more.join(' | ')}`);
  await page.click('#text-menu button:has-text("Все модели и параметры")');
  expect(await page.isVisible('#tx-model-bar'), '«Все модели и параметры» does not open the row');
  expect(await page.locator('#tx-model-select option[value="precise"]').count() === 1, 'no precise mode in the list');
  await page.click('#tx-more-btn');
  await sleep(200);
  await page.click('#text-menu button:has-text("Свернуть панель моделей")');
  expect(!(await page.isVisible('#tx-model-bar')), 'the row does not fold back');
  expect(!(await page.isVisible('#chapters-bar')), 'the chapters are shown twice');
  await page.click('#tx-view-btn');
  const items = await page.$$eval('#tx-view-menu button', els => els.map(e => e.textContent.trim()));
  expect(items.some(x => /Без запинок/.test(x)) && items.some(x => /Автопрокрутка/.test(x)), 'the display toggles are not in the view menu');
  const before = await page.evaluate(() => !!state.noFillers);
  await page.click('#tx-view-menu button:has-text("Без запинок")');
  expect(await page.evaluate(() => !!state.noFillers) !== before, '«Без запинок» did not switch');
  await page.evaluate(() => txViewToggle('fillers'));
});

// A recording without a text (reported by the user: the old «РАСПОЗНАВАНИЕ» panel and a band with two percents):
// one card in the content column; while the tracks are mixed it shows the stage and one labelled percent, never
// «Идёт расшифровка»; the tools of a text are not shown; idle, it offers the model and «Расшифровать» (32px)
await step('recording without a text', async () => {
  await page.evaluate(() => {
    const m = state.activeMeeting;
    Object.assign(m, { segments: [], status: 'mixing', progress: 28, stage_text: 'Сведение дорожек: удаление эха колонок… 36%' });
    renderTxModelBar(); updateProcessingBanner(m); renderTranscript();
  });
  expect(await page.isVisible('#tx-model-bar') && await page.isVisible('#tx-rc-prog'), 'no progress card');
  expect(!(await page.isVisible('#tx-subbar')) && !(await page.isVisible('#workspace-processing-banner')), 'the toolbar or the old band is shown');
  const card = await page.textContent('#tx-model-bar');
  expect(/Сведение дорожек/.test(card) && !/Идёт расшифровка/.test(card), `the card while mixing: ${card.replace(/\s+/g, ' ')}`);
  expect((await page.textContent('#tx-rc-pct')).trim() === 'Этап 36% · Всего 28%', 'the percents are not labelled');
  await page.evaluate(() => { Object.assign(state.activeMeeting, { status: 'added', progress: 0, stage_text: '' }); renderTxModelBar(); updateProcessingBanner(state.activeMeeting); });
  expect(await page.isVisible('#tx-rc-pick') && await page.isVisible('#tx-transcribe-btn'), 'no model choice or «Расшифровать»');
  const geo = await page.evaluate(() => {
    const r = id => document.getElementById(id).getBoundingClientRect();
    return { card: [r('tx-model-bar').left, r('tx-model-bar').right], col: [r('transcript-inner').left, r('transcript-inner').right],
      btns: ['tx-transcribe-btn', 'tx-proc-btn'].map(id => r(id).height), seg: r('tx-model-chips').height };
  });
  expect(geo.card.every((x, i) => Math.abs(x - geo.col[i]) < 1), `the card is off the content column: ${JSON.stringify(geo)}`);
  expect(geo.btns.every(h => h === 32) && geo.seg === 32, `not 32px: ${JSON.stringify(geo)}`);
  await page.evaluate(() => selectMeeting(state.activeMeeting.id, false));
  await sleep(500);
  expect(await page.isVisible('#tx-subbar') && !(await page.isVisible('#tx-model-bar')), 'the text does not come back');
});

// A speaker filter left from before «Разделить по голосам» (its speakers named anew) does not hide the whole text;
// a filter or a search that hides every line offers «Показать все реплики», which clears both
await step('stale speaker filter', async () => {
  await page.evaluate(() => { state.speakerFilter = 'SPEAKER_99'; renderTranscript(); });
  expect(await page.locator('#transcript-container .segment-row').count() > 0, 'a stale speaker filter hides the text');
  expect(await page.evaluate(() => state.speakerFilter) === null, 'the stale filter is kept');
  await page.fill('#transcript-search', 'нет-такого-слова');
  await sleep(300);
  expect(await page.isVisible('#tx-show-all'), 'no «Показать все реплики»');
  await page.evaluate(() => { state.speakerFilter = 'SPEAKER_00'; });
  await page.click('#tx-show-all');
  await sleep(200);
  expect(await page.locator('#transcript-container .segment-row').count() > 0 && await page.inputValue('#transcript-search') === ''
    && await page.evaluate(() => state.speakerFilter) === null, '«Показать все реплики» did not clear the filter and the search');
});

// The transcript as a chat (docs/pult-plan.md, stage 5): each phrase a bubble with its time, the face and the
// name once for a run of one speaker; the phrase playing is lit; «Текст» brings the running text back, kept
await step('transcript as a chat', async () => {
  // the tabs in the order the user chose; another recording opens on «Расшифровка»
  const order = await page.$$eval('#tb-record > button', els => els.map(e => e.id));
  expect(order.join() === 'nav-transcript,nav-summary,nav-speakers,nav-info', `the tabs: ${order}`);
  await page.evaluate(() => openRecordTab('summary'));
  await page.evaluate(() => openMeeting(2));
  await sleep(800);
  expect(await page.evaluate(() => state.activeWorkspaceTab) === 'transcript', 'another recording did not open on «Расшифровка»');
  await page.evaluate(() => openMeeting(1));
  await until(() => state.activeMeeting?.id === 1 && document.querySelectorAll('#transcript-container .segment-row').length > 0,
    'the recording did not open again', 8000);
  await page.evaluate(() => { openRecordTab('transcript'); setTxLayout('chat'); });
  await until(() => document.querySelectorAll('#transcript-inner .ch-bub.segment-row').length > 0, 'no bubbles in «Чат»');
  const bubbles = await page.locator('#transcript-inner .ch-bub.segment-row').count();
  expect(bubbles > 0, 'no bubbles in «Чат»');
  expect(await page.locator('#transcript-inner .ch-bub .ch-tm').count() === bubbles, 'a bubble without its time');
  const runs = await page.locator('#transcript-inner .ch-group').count();
  expect(await page.locator('#transcript-inner .ch-group > .ch-av').count() === runs, 'the face is not once per run');
  await page.evaluate(() => updatePlaybackHighlight(1, true));
  // the bubbles may be drawn again by the recording's refresh a moment later: lit again, waited for
  await until(() => { updatePlaybackHighlight(1, true); return document.querySelectorAll('#transcript-inner .ch-bub.segment-active').length === 1; },
    'the phrase playing is not lit', 3000);
  await page.click('#tx-layout-text');
  await sleep(200);
  expect(await page.locator('#transcript-inner .ch-bub').count() === 0 && await page.locator('#transcript-inner .segment-row').count() > 0, '«Текст» did not bring the text back');
  expect(await page.evaluate(() => localStorage.getItem('verbaliox_tx_layout')) === 'text', 'the choice is not kept');
  await page.click('#tx-layout-chat');
});

// The unloaded player (stage 5): three buttons in the middle, the phrase's repeat and loop in «⋯»; J goes back
// 10 s; the play button is the same element while it plays (a hover on it is not restarted)
await step('unloaded player', async () => {
  expect(await page.locator('.rp-center button').count() === 3, 'more than three buttons in the middle of the player');
  expect(await page.locator('#rp-chapters .rp-chapter').count() === 0, 'chapter titles over the wave');
  const tall = await page.evaluate(() => document.getElementById('player-footer').getBoundingClientRect().height);
  expect(tall <= 135, `the player is ${tall}px tall`);
  const items = await page.evaluate(() => { rpTogglePop('more'); const x = [...document.querySelectorAll('#rp-pop-more .rp-item')].map(b => b.textContent.trim()); rpClosePop(); return x; });
  expect(items.some(x => /Повторить реплику/.test(x)) && items.some(x => /по кругу/.test(x)), `«⋯» lacks the phrase's repeat: ${items.join(' | ')}`);
  const res = await page.evaluate(async () => {
    const p = document.getElementById('media-player');
    p.muted = true;
    const btn = document.getElementById('play-pause-btn');
    p.currentTime = 30;
    await new Promise(r => setTimeout(r, 200));
    document.body.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyJ', key: 'j', bubbles: true }));
    await new Promise(r => setTimeout(r, 200));
    return { at: p.currentTime, same: document.getElementById('play-pause-btn') === btn };
  });
  expect(res.at > 15 && res.at < 25, `J did not go back 10 s: ${res.at}`);
  expect(res.same, 'the play button was drawn again');
});

// Scrubbing (asked by the user): hold the button on the wave and move — the time follows, the bubble over the
// playhead shows it and grows while dragging; a click without moving seeks too
await step('scrub the wave', async () => {
  await page.evaluate(() => { const p = document.getElementById('media-player'); p.muted = true; p.pause(); });
  const box = await page.locator('#player-waveform-wrapper').boundingBox();
  const y = box.y + box.height / 2;
  await page.mouse.move(box.x + box.width * 0.1, y);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * 0.5, y, { steps: 8 });
  const during = await page.evaluate(() => ({
    on: document.getElementById('player-waveform-wrapper').classList.contains('rp-scrubbing'),
    bubble: document.getElementById('rp-head-bubble').textContent,
  }));
  await page.mouse.up();
  await sleep(200);
  const at = await page.evaluate(() => document.getElementById('media-player').currentTime);
  expect(during.on, 'no dragging state while the button is held');
  expect(/^00:(2[7-9]|3[0-3])\b/.test(during.bubble), `the bubble shows ${during.bubble} in the middle of a minute`);
  expect(at > 27 && at < 33, `the drag left the time at ${at}`);
  expect(!(await page.evaluate(() => document.getElementById('player-waveform-wrapper').classList.contains('rp-scrubbing'))), 'the dragging state stays');
  await page.mouse.click(box.x + box.width * 0.25, y);
  await sleep(200);
  const click = await page.evaluate(() => document.getElementById('media-player').currentTime);
  expect(click > 12 && click < 18, `a click left the time at ${click}`);
  await page.evaluate(() => document.getElementById('media-player').pause());
});

// While the recording plays a frame copies the bars and the ribbon drawn once and asks no layout of the page (audit
// K20: every frame drew every phrase and read the canvas's box); a change of the speakers' filter draws them again
await step('player frames reuse their layers', async () => {
  const r = await page.evaluate(() => {
    rpRender();
    const drawn = rp.layersDrawn;
    let rects = 0;
    const orig = Element.prototype.getBoundingClientRect;
    Element.prototype.getBoundingClientRect = function () { rects++; return orig.call(this); };
    rp.drag = true;
    try { for (let i = 0; i < 30; i++) { rp.dragTime = i; rpRender(); } } finally { rp.drag = false; rp.dragTime = null; Element.prototype.getBoundingClientRect = orig; }
    const same = rp.layersDrawn - drawn;
    const spk = Object.keys(state.activeMeeting.speakers || {})[0];
    state.speakerFilter = spk;
    rpRender();
    const filtered = rp.layersDrawn - drawn - same;
    state.speakerFilter = null;
    rpRender();
    return { same, rects, filtered };
  });
  expect(r.same === 0, `the layers were drawn again ${r.same} times in 30 frames`);
  expect(r.rects === 0, `the frames read the layout ${r.rects} times`);
  expect(r.filtered === 1, `the speakers' filter did not draw the layers again: ${r.filtered}`);
});

// «Как прошёл разговор» (a bar per phrase) is drawn when the speakers' tab is shown, not into the hidden tab at
// each opening of a recording (audit В22)
await step('talk analytics wait for their tab', async () => {
  await page.evaluate(() => openRecordTab('transcript'));
  const asked = [];
  const seen = r => { if (/\/analytics$/.test(r.url())) asked.push(r.url()); };
  page.on('request', seen);
  await page.evaluate(() => renderSpeakersPanel());
  await sleep(300);
  const hidden = await page.evaluate(() => document.querySelectorAll('#talk-analytics .sp-lane').length);
  await page.evaluate(() => openRecordTab('speakers'));
  await until(() => document.querySelectorAll('#talk-analytics .sp-lane').length > 0, 'the speakers tab has no lanes');
  page.off('request', seen);
  await page.evaluate(() => openRecordTab('transcript'));
  expect(hidden === 0, `the hidden tab was drawn: ${hidden} lanes`);
  expect(asked.length === 1, `the analytics were asked ${asked.length} times`);
});

// «Сведения»: four cards of «key — value» rows, the actions of each under a line (only the program's own)
await step('recording details', async () => {
  await page.evaluate(() => openRecordTab('info'));
  await sleep(1200);
  const cards = await page.$$eval('#info-content [data-info]', els => els.map(e => e.dataset.info));
  expect(cards.join() === 'file,transcript,analysis,storage', `the cards: ${cards}`);
  const acts = await page.$$eval('#info-content .kv-acts button', els => els.map(e => e.dataset.click));
  for (const fn of ['recReconfigure', 'openResplitDialog', 'recRegenFromInfo', 'recMoveFromInfo']) expect(acts.includes(fn), `no ${fn} in «Сведения»`);
  await page.evaluate(() => openRecordTab('transcript'));
});

// The player minimized to one line and back; the choice is kept; the thin track still seeks
await step('minimized player', async () => {
  await page.click('#rp-min-btn');
  await sleep(300);
  const h = await page.evaluate(() => document.getElementById('player-footer').getBoundingClientRect().height);
  expect(h < 60, `the minimized player is ${h}px tall`);
  expect(await page.evaluate(() => localStorage.getItem('verbaliox_player_mini')) === '1', 'the choice is not kept');
  const box = await page.locator('#player-waveform-wrapper').boundingBox();
  await page.mouse.click(box.x + box.width * 0.75, box.y + box.height / 2);
  await sleep(200);
  const at = await page.evaluate(() => { const p = document.getElementById('media-player'); p.pause(); return p.currentTime; });
  expect(at > 42 && at < 48, `a click on the thin track left the time at ${at}`);
  await page.click('#rp-min-btn');
  await sleep(300);
  expect(await page.evaluate(() => document.getElementById('player-footer').getBoundingClientRect().height) > 100, 'the player did not expand');
});

// The menu of a recording at the bottom of the window stays inside it, «Удалить» reachable (1.2)
await step('menu at the bottom', async () => {
  const box = await page.evaluate(() => {
    openRecordingContextMenu({ clientX: 300, clientY: innerHeight - 10, preventDefault() {}, stopPropagation() {} }, 1);
    const r = document.getElementById('recording-context-menu').getBoundingClientRect();
    return { bottom: r.bottom, vh: innerHeight };
  });
  expect(box.bottom <= box.vh, 'the menu leaves the window');
  expect(await page.isVisible('#recording-context-menu [data-submenu="ctx-sub-export"]'), 'no export in the menu');
  await page.evaluate(() => hideContextMenu());
  await sleep(250);
  // the same menu in a low window scrolls inside it; opened again in a tall one it has its whole height back
  const ctxAt = () => page.evaluate(() => {
    openRecordingContextMenu({ clientX: 300, clientY: 40, preventDefault() {}, stopPropagation() {} }, 1);
    return new Promise(ok => setTimeout(() => { const e = document.getElementById('recording-context-menu'), r = e.getBoundingClientRect();
      ok({ bottom: r.bottom, vh: innerHeight, max: e.style.maxHeight }); }, 250));
  });
  await page.setViewportSize({ width: 1300, height: 280 });
  const low = await ctxAt();
  expect(low.bottom <= low.vh && !!low.max, `the menu in a low window: ${JSON.stringify(low)}`);
  await page.evaluate(() => hideContextMenu());
  await sleep(250);
  await page.setViewportSize({ width: 1300, height: 860 });
  const tall = await ctxAt();
  expect(!tall.max, `the menu kept the limit of the low window: ${JSON.stringify(tall)}`);
  await page.evaluate(() => hideContextMenu());
  await sleep(250);
});

// The menus are looked for after a change that can open one, not after the level meter and the timer of a recording
// (20 times a second for a whole meeting, each look going over the whole page)
// The recording's menu in four groups with submenus «Экспорт ›», «Нарезка ›», «Ещё ›» (asked by the user: the menu held
// too much): a hover opens a submenu, → ← Esc work from the keyboard, the menu fits a 1100×700 window opened at its bottom
await step('recording menu submenus', async () => {
  await page.setViewportSize({ width: 1100, height: 700 });
  const open = (x, y) => page.evaluate(([cx, cy]) => {
    hideContextMenu();
    openRecordingContextMenu({ clientX: cx, clientY: cy, preventDefault() {}, stopPropagation() {} }, 1);
  }, [x, y]);
  await open(300, 120); await sleep(300);
  const rows = await page.evaluate(() => [...document.querySelectorAll('#recording-context-menu > button')]
    .filter(b => !b.classList.contains('hidden')).map(b => b.dataset.click || b.dataset.submenu));
  expect(JSON.stringify(rows) === JSON.stringify(['ctxOpenInfo', 'ctxRenameRecording', 'ctxMoveToFolder', 'openSeriesMenu',
    'ctxOpenReconfigureModal', 'ctx-sub-export', 'ctx-sub-cut', 'ctx-sub-more', 'ctxDeleteRecording']), `the rows: ${rows}`);
  // the «›» of the submenu rows and the shortcuts at the same right edge
  const edges = await page.evaluate(() => [...document.querySelectorAll('#recording-context-menu .tm-key, #recording-context-menu .vx-sub-chev')]
    .map(e => Math.round(e.getBoundingClientRect().right)));
  expect(new Set(edges).size === 1, `the right edges of the keys and «›»: ${edges}`);
  // a hover on «Экспорт ›»: DOCX beside the menu, to its right
  await page.hover('#ctx-sub-export-btn');
  await until(() => !document.getElementById('ctx-sub-export').classList.contains('hidden'), 'hover did not open «Экспорт ›»', 2000);
  expect(await page.isVisible('#ctx-sub-export button:has-text("DOCX")'), 'no DOCX');
  const side = await page.evaluate(() => [document.getElementById('recording-context-menu').getBoundingClientRect().right,
    document.getElementById('ctx-sub-export').getBoundingClientRect().left, document.getElementById('ctx-sub-export-btn').getAttribute('aria-expanded')]);
  expect(side[1] >= side[0] - 4 && side[2] === 'true', `«Экспорт ›» not beside the menu: ${side}`);
  // over another row the submenu closes; over «Ещё ›» its four items
  await page.hover('#recording-context-menu button[data-click="ctxRenameRecording"]');
  await until(() => document.getElementById('ctx-sub-export').classList.contains('hidden'), '«Экспорт ›» stayed open over another row', 2000);
  await page.hover('#ctx-sub-more-btn');
  await until(() => !document.getElementById('ctx-sub-more').classList.contains('hidden'), 'hover did not open «Ещё ›»', 2000);
  const more = await page.evaluate(() => [...document.querySelectorAll('#ctx-sub-more button')].filter(b => b.offsetParent).map(b => b.dataset.click));
  expect(JSON.stringify(more) === JSON.stringify(['ctxImportTeamsVtt', 'ctxRevealInExplorer', 'ctxClearResults', 'ctxRemoveMedia']), `«Ещё ›»: ${more}`);
  // the keyboard: → opens «Нарезка ›» with the focus in it, ← goes back, Esc closes the submenu and then the menu
  await page.mouse.move(5, 5);
  await page.evaluate(() => { closeSubmenus(); document.getElementById('ctx-sub-cut-btn').focus(); });
  await page.keyboard.press('ArrowRight');
  await until(() => document.getElementById('ctx-sub-cut').contains(document.activeElement), '→ did not move the focus into «Нарезка ›»', 2000);
  expect(await page.evaluate(() => document.activeElement.dataset.clickArgs) === '["clean"]', 'the first item of «Нарезка ›» is not «Без пауз»');
  await page.keyboard.press('ArrowDown');
  expect(await page.evaluate(() => document.activeElement.dataset.clickArgs) === '["highlights"]', '↓ did not move to «Ключевые моменты»');
  await page.keyboard.press('ArrowLeft');
  await until(() => document.getElementById('ctx-sub-cut').classList.contains('hidden') && document.activeElement.id === 'ctx-sub-cut-btn', '← did not go back to the row', 2000);
  await page.keyboard.press('Enter');
  await until(() => document.getElementById('ctx-sub-cut').contains(document.activeElement), 'Enter did not open «Нарезка ›»', 2000);
  await page.keyboard.press('Escape'); await sleep(300);
  expect(await page.evaluate(() => document.getElementById('ctx-sub-cut').classList.contains('hidden') && vxShown('recording-context-menu')),
    'Esc did not close only the submenu');
  await page.keyboard.press('Escape'); await sleep(350);
  expect(!(await page.isVisible('#recording-context-menu')), 'the second Esc did not close the menu');
  // at the bottom right of a 1100×700 window: the menu and its submenu inside the window, the submenu to the left
  await open(1090, 690); await sleep(300);
  await page.hover('#ctx-sub-more-btn');
  await until(() => !document.getElementById('ctx-sub-more').classList.contains('hidden'), 'hover did not open «Ещё ›» at the bottom', 2000);
  const fit = await page.evaluate(() => {
    const a = document.getElementById('recording-context-menu').getBoundingClientRect(), b = document.getElementById('ctx-sub-more').getBoundingClientRect();
    return { a: [a.left, a.top, a.right, a.bottom], b: [b.left, b.top, b.right, b.bottom], scroll: document.getElementById('recording-context-menu').style.maxHeight };
  });
  expect(fit.a[1] >= 0 && fit.a[3] <= 700 && fit.a[2] <= 1100 && !fit.scroll, `the menu at the bottom: ${JSON.stringify(fit)}`);
  expect(fit.b[1] >= 0 && fit.b[3] <= 700 && fit.b[2] <= fit.a[0] + 4 && fit.b[0] >= 0, `«Ещё ›» at the bottom: ${JSON.stringify(fit)}`);
  await page.evaluate(() => hideContextMenu()); await sleep(250);
  await page.setViewportSize({ width: 1300, height: 860 });
});

await step('menus not looked for on a meter tick', async () => {
  const r = await page.evaluate(async () => {
    const real = window.vxSyncLayers;
    let looks = 0;
    window.vxSyncLayers = () => { looks++; real(); };
    const wait = () => new Promise(res => setTimeout(res, 50));
    try {
      // the records of the tick alone, judged by the page's own rule: other changes of the page meanwhile (a poll
      // redrawing a list) made the count of looks flaky
      const seen = [];
      const mo = new MutationObserver(rs => seen.push(...rs));
      mo.observe(document.documentElement, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['class', 'id'] });
      document.getElementById('studio-db').textContent = '-12 dB';
      document.getElementById('studio-level').className = 'h-full bg-apple-red transition-all duration-75';
      await wait();
      mo.disconnect();
      const mine = seen.filter(r => ['studio-db', 'studio-level'].includes((r.target.nodeType === 1 ? r.target : r.target.parentElement)?.id));
      const tick = mine.length && vxMattersFor(mine) ? 1 : 0;
      openRecordingContextMenu({ clientX: 300, clientY: 300, preventDefault() {}, stopPropagation() {} }, 1);
      await wait();
      const menu = looks;
      hideContextMenu();
      return { tick, menu };
    } finally {
      window.vxSyncLayers = real;
    }
  });
  expect(r.tick === 0, `a meter tick made ${r.tick} looks`);
  expect(r.menu > 0, 'an opened menu was not seen');
  await sleep(250);
});

// Undo instead of a question: a task goes at once and comes back with «Отменить» (6.1)
await step('undo a removal', async () => {
  await page.evaluate(() => switchAppView('tasks'));
  await until(() => typeof TK !== 'undefined' && TK.data && TK.data.tasks.length > 0, 'the tasks did not load', 8000);
  const before = await page.evaluate(() => TK.data.tasks.length);
  await page.evaluate(() => deleteTask(TK.data.tasks[0].id));
  await until(n => TK.data.tasks.length === n - 1, 'the task did not go', 5000, before);
  await page.click('#toast .toast-action');
  await until(n => TK.data.tasks.length === n, '«Отменить» did not bring it back', 5000, before);
});

// The tasks as a calendar of due dates: the grouping greys (its place kept), today framed, a task with its
// whole text, «Без срока» with its empty slot; the week view has seven tall days
await step('task calendar', async () => {
  await page.evaluate(() => { switchAppView('tasks'); setTasksView('cal'); setTasksCalMode('month'); });
  await sleep(500);
  const r = await page.evaluate(() => ({
    off: document.getElementById('tk-groups-box').classList.contains('tk-tbg-off'),
    today: document.querySelectorAll('#tk-cal .tk-day.tk-today').length,
    chips: [...document.querySelectorAll('#tk-cal .tk-grid .tk-cchip .tk-ctext')].map(e => e.scrollWidth <= e.clientWidth + 1),
    weekdays: document.querySelectorAll('#tk-cal .tk-week span').length,
    none: !!document.querySelector('#tk-cal .tk-nodue .pcd-h'),
  }));
  expect(r.off, 'the grouping is not greyed in the calendar');
  expect(r.today === 1, 'today is not framed');
  expect(r.chips.length > 0 && r.chips.every(Boolean), 'a task of the calendar is cut');
  expect(r.weekdays === 7 && r.none, 'no weekdays or no «Без срока»');
  await page.evaluate(() => setTasksCalMode('week'));
  await sleep(300);
  expect(await page.evaluate(() => document.querySelectorAll('#tk-cal .tk-day.tk-tall').length) === 7, 'the week has not seven days');
  await page.evaluate(() => { setTasksCalMode('month'); setTasksView('list'); });
  await sleep(300);
  expect(await page.evaluate(() => !document.getElementById('tk-groups-box').classList.contains('tk-tbg-off')
    && !!document.querySelector('#tk-list .tk-group.pcard .pcd-ic, #tk-list .tk-group.pcard .tk-ava')), 'the list has no group cards');
  // the names of the columns: one bar above all the cards, each name over its column (the summary folded:
  // room for the grid); «Колонки» adds a column to the bar and the rows alike; the cards have no bar
  const cols = await page.evaluate(() => {
    TK.rep = false; TK.cols = ['who', 'due', 'src']; renderTasks();
    const bar = document.querySelectorAll('#tk-list > .tk-colbar > span');
    const x = el => Math.round(el.getBoundingClientRect().left);
    return [bar.length === 7, ...[...document.querySelectorAll('#tk-list .tk-group .tk-row')].map(row => {
      const c = row.children;
      return [x(bar[2]) === x(c[2]), x(bar[3]) === x(c[3]), x(bar[4]) === x(c[4]), x(bar[5]) === x(c[5])];
    }).flat()];
  });
  expect(cols.length > 1 && cols.every(Boolean), `the column names are off their columns: ${cols}`);
  await page.evaluate(() => setTasksView('cards'));
  await sleep(300);
  expect(await page.evaluate(() => !document.querySelector('#tk-list .tk-colbar') && document.querySelectorAll('#tk-list .tk-tcard').length > 0), 'the cards view is not cards');
  await page.evaluate(() => { setTasksView('list'); TK.rep = true; resetTasksCols(); });
});

// «Словарь» is a section of the rail: a word added with its variants and group shows in its group with the
// number of recordings that hold it; the old entry in the settings leads here
await step('dictionary section', async () => {
  await page.click('#rail-dict');
  await sleep(600);
  expect(await page.isVisible('#dict-view') && await page.evaluate(() => document.getElementById('rail-dict').classList.contains('rail-on')), 'the section did not open');
  await page.fill('#settings-dict-term', 'Пиксель-Студио');
  await page.fill('#settings-dict-variants', 'пиксель студия');
  await page.fill('#settings-dict-cat', 'Компании');
  await page.click('#settings-dict-add');
  await sleep(600);
  const r = await page.evaluate(() => ({
    row: [...document.querySelectorAll('#dc-words .dc-row:not(.dc-thead)')].some(x => x.textContent.includes('Пиксель-Студио') && x.textContent.includes('пиксель студия')),
    group: [...document.querySelectorAll('#dc-words .dc-filters button')].some(b => b.textContent.includes('Компании')),
    used: document.querySelectorAll('#dc-words .dc-row:not(.dc-thead) .dc-used').length > 0,
  }));
  expect(r.row && r.group && r.used, `the word is not in its group: ${JSON.stringify(r)}`);
  await page.evaluate(() => { const d = state.dictionary.find(x => x.term === 'Пиксель-Студио'); return deleteDictItem(d.id); });
  await page.evaluate(() => { openModal('settings', 'dictionary'); });
  await sleep(500);
  await page.click('#modal-settings [data-stab="dictionary"] button[data-click="openDictionary"]');
  await sleep(500);
  expect(await page.isVisible('#dict-view'), 'the settings entry does not lead to the section');
});

// «Люди» is a section of the rail: the people on the left, the card of the one chosen on the right in cards
await step('people section', async () => {
  await page.click('#rail-people');
  await sleep(800);
  const r = await page.evaluate(() => ({
    view: !document.getElementById('people-view').classList.contains('hidden'),
    rows: document.querySelectorAll('#pv-list .pv-row').length,
    cards: document.querySelectorAll('#pv-card .pcard .pcd-ic').length,
    on: document.getElementById('rail-people').classList.contains('rail-on'),
  }));
  expect(r.view && r.rows >= 3 && r.cards >= 2 && r.on, `people: ${JSON.stringify(r)}`);
});

// Ассистент: the field has a send button; an answer's sources are moments «▶ 00:24» in the text, and under it
// each recording by its full name with its moments
await step('assistant sources', async () => {
  await page.evaluate(() => switchAppView('ask'));
  await sleep(500);
  const r = await page.evaluate(async () => {
    for (let i = 0; i < 30 && !ASSIST.loaded; i++) await new Promise(res => setTimeout(res, 100));
    assistantNewChat();
    currentChat().items.push({ id: 991, question: 'Что решили по срокам?', scope: state.askScope, scopeLabel: '', status: 'done', at: new Date().toISOString(),
      data: { found: true, answer: 'Сроки уточнят до среды [1], список будет к пятнице [2].', sources: [
        { n: 1, meeting_id: 1, title: 'Планёрка отдела', date: '21 ноября', start: 24, text: 'По срокам нужно уточнить.' },
        { n: 2, meeting_id: 1, title: 'Планёрка отдела', date: '21 ноября', start: 12, text: 'Я подготовлю список к пятнице.' }] } });
    renderAssistant();
    return { refs: [...document.querySelectorAll('#ask-thread .markdown-body .as-ref')].map(b => b.textContent),
      rows: document.querySelectorAll('#ask-thread .as-srcrow').length, send: !!document.querySelector('#library-ask-btn svg') };
  });
  expect(r.refs.join() === '▶ 00:24,▶ 00:12' && r.rows === 1 && r.send, `assistant: ${JSON.stringify(r)}`);
});

// Настройки: eight sections with their line icons, «Календарь» one of them; the cards with the icon of their section
await step('settings sections', async () => {
  await page.evaluate(() => openModal('settings', 'calendar'));
  await sleep(500);
  const r = await page.evaluate(() => ({
    nav: document.querySelectorAll('#settings-nav .sx-nav-btn svg').length,
    on: document.getElementById('stab-calendar').classList.contains('is-active'),
    icons: [...document.querySelectorAll('#modal-settings [data-stab="calendar"] .settings-card')].every(c => !c.querySelector('h4') || c.querySelector('.sx-card-hd > .pcd-ic')),
  }));
  expect(r.nav === 8 && r.on && r.icons, `settings sections: ${JSON.stringify(r)}`);
  await page.evaluate(() => closeModal('settings'));
  await sleep(300);
});

// Settings, one row in every section (asked by the user: the settings were overloaded): nothing folded away, the
// name of every option at one left edge and its control at one right edge, measured in every section
await step('settings rows line up', async () => {
  await page.evaluate(() => openModal('settings', 'general'));
  const tabs = ['general', 'record', 'recognition', 'analysis', 'calendar', 'export', 'privacy', 'advanced'];
  const lefts = new Set(), rights = new Set(), bad = [];
  let folded = 0, rows = 0;
  for (const tab of tabs) {
    await page.evaluate(t => selectSettingsTab(t), tab);
    await sleep(500);
    const r = await page.evaluate(() => {
      const out = { lefts: [], rights: [], folded: document.querySelectorAll('#modal-settings .sx-more, #modal-settings details > summary[data-i18n]').length };
      document.querySelectorAll('#modal-settings [data-stab]:not(.hidden) .sx-row:not(.sx-dep)').forEach(row => {
        if (!row.offsetParent) return;
        const label = row.querySelector('.sx-row-label');
        const ctl = row.querySelector(':scope > .sx-row-ctl, :scope > .vs-switch');
        const card = row.closest('.settings-card').getBoundingClientRect();
        if (label) out.lefts.push(Math.round(label.getBoundingClientRect().left - card.left));
        if (ctl) out.rights.push(Math.round(card.right - ctl.getBoundingClientRect().right));
      });
      return out;
    });
    folded += r.folded;
    rows += r.lefts.length;
    r.lefts.forEach(x => lefts.add(x));
    r.rights.forEach(x => rights.add(x));
    if (r.lefts.some(x => x !== r.lefts[0])) bad.push(tab);
  }
  await page.evaluate(() => closeModal('settings'));
  expect(!folded && rows > 40 && lefts.size === 1 && rights.size === 1,
    `settings rows: folded ${folded}, rows ${rows}, label edges ${[...lefts]}, control edges ${[...rights]} (${bad})`);
});

// The settings search finds an option by its new name and by its former one (the options were renamed)
await step('settings search finds renamed options', async () => {
  await page.evaluate(() => openModal('settings', 'general'));
  const found = await page.evaluate(() => Object.fromEntries([['эхо', 'set-echo-cancel'], ['шум', 'set-voice-filter'],
    ['MCP', 'set-mcp-local-only'], ['Obsidian', 'set-obsidian-auto'], ['CFG', 'set-dub-cfg'], ['vault', 'set-obsidian-auto'],
    ['потоки', 'set-cpu-threads'], ['Резерв памяти', 'set-mem-reserve-ram'], ['Подготовка звука', 'set-proc-denoise'],
    ['Эксперименты', 'set-dub-workers']].map(([q, id]) => {
    settingsSearch(q);
    const card = document.getElementById(id).closest('.settings-card');
    return [q, !card.classList.contains('hidden') && !card.closest('[data-stab]').classList.contains('hidden')];
  })));
  await page.evaluate(() => { clearSettingsSearch(); closeModal('settings'); });
  expect(Object.values(found).every(Boolean), `settings search: ${JSON.stringify(found)}`);
});

// A press in a dialog's field released over the backdrop keeps the dialog (1.1)
await step('dialog keeps a selection', async () => {
  await page.evaluate(() => { askText('Название', 'текст'); });
  await sleep(300);
  const input = await page.$('div.modal-backdrop:not(.hidden) form input');
  const b = await input.boundingBox();
  await page.mouse.move(b.x + 5, b.y + b.height / 2);
  await page.mouse.down();
  await page.mouse.move(4, 4, { steps: 4 });
  await page.mouse.up();
  await sleep(200);
  expect(!!(await page.$('div.modal-backdrop:not(.hidden) form input')), 'the dialog closed');
  await page.keyboard.press('Escape');
  await sleep(250);
});

// The Studio: what it shows is what the red button records with (1.5)
await step('studio source', async () => {
  await page.evaluate(() => switchAppView('studio'));
  await sleep(800);
  await page.evaluate(() => { document.getElementById('record-source-select').value = 'mic'; });
  await page.evaluate(() => prepareStudio());
  await sleep(300);
  expect(await page.evaluate(() => document.getElementById('record-source-select').value) === 'mic', 'the Studio source was reset');
});

// The studio's options as a rail of four buttons (asked by the user: the column of cards was hardly used and scrolled):
// the buttons of one size in one column, each opens its panel beside it with the focus inside, Esc closes it and gives
// the focus back, a second click closes it, the choice of the source shows under its button; nothing scrolls at 1280×800
await step('studio options rail', async () => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.evaluate(() => { document.getElementById('first-run-wizard')?.remove(); switchAppView('studio'); });
  await sleep(600);
  const keys = ['source', 'video', 'meet', 'after'];
  const boxes = await page.evaluate(ks => ks.map(k => { const r = document.getElementById(`st-rail-${k}`).getBoundingClientRect(); return [r.left, r.top, r.width, r.height]; }), keys);
  expect(boxes.every(b => Math.abs(b[0] - boxes[0][0]) < 0.5 && Math.abs(b[2] - boxes[0][2]) < 0.5 && Math.abs(b[3] - boxes[0][3]) < 0.5 && b[2] > 0),
    `the rail's buttons are not of one size in one column: ${JSON.stringify(boxes)}`);
  expect(boxes.every((b, i) => !i || Math.abs((b[1] - boxes[i - 1][1]) - (boxes[1][1] - boxes[0][1])) < 0.5), `the rail's buttons are not evenly spaced: ${JSON.stringify(boxes)}`);
  const noScroll = (id) => page.evaluate(i => { const e = document.getElementById(i); return e.scrollHeight <= e.clientHeight + 1; }, id);
  expect(await noScroll('side-studio'), 'the rail scrolls');
  for (const k of keys) {
    await page.click(`#st-rail-${k}`);
    await sleep(150);
    const s = await page.evaluate(key => {
      const fly = document.getElementById(`st-fly-${key}`), btn = document.getElementById(`st-rail-${key}`);
      const f = fly.getBoundingClientRect(), b = btn.getBoundingClientRect();
      return { shown: !fly.classList.contains('hidden'), exp: btn.getAttribute('aria-expanded'), focus: fly.contains(document.activeElement),
        beside: f.left >= b.right, inView: f.bottom <= innerHeight, others: document.querySelectorAll('.st-fly:not(.hidden)').length };
    }, k);
    expect(s.shown && s.exp === 'true' && s.focus && s.beside && s.inView && s.others === 1, `the panel «${k}» did not open beside its button: ${JSON.stringify(s)}`);
    expect(await noScroll(`st-fly-${k}`), `the panel «${k}» scrolls`);
    await page.keyboard.press('Escape');
    await sleep(150);
    const c = await page.evaluate(key => [document.getElementById(`st-fly-${key}`).classList.contains('hidden'),
      document.getElementById(`st-rail-${key}`).getAttribute('aria-expanded'), document.activeElement?.id], k);
    expect(c[0] && c[1] === 'false' && c[2] === `st-rail-${k}`, `Esc did not close the panel «${k}» or the focus did not come back: ${c}`);
  }
  // a second click closes; a click elsewhere closes
  await page.click('#st-rail-source');
  await sleep(150);
  await page.click('#st-rail-source');
  await sleep(150);
  expect(await page.evaluate(() => document.getElementById('st-fly-source').classList.contains('hidden')), 'a second click did not close the panel');
  await page.click('#st-rail-source');
  await sleep(150);
  await page.mouse.click(1200, 700);  // the empty captions' pane, away from the panel
  await sleep(150);
  expect(await page.evaluate(() => document.getElementById('st-fly-source').classList.contains('hidden')), 'a click elsewhere did not close the panel');
  // the source chosen in the panel: under the rail's button, and the recording reads it with the panel closed
  const before = await page.evaluate(() => document.getElementById('record-source-select').value);
  await page.click('#st-rail-source');
  await sleep(150);
  await page.click('#st-src-system');
  await sleep(150);
  const label = await page.evaluate(() => [document.getElementById('st-rail-source-state').textContent, t('rdSasSrcSystem')]);
  expect(label[0] === label[1], `the rail did not show the source: ${label}`);
  await page.keyboard.press('Escape');
  await sleep(150);
  expect(await page.evaluate(() => document.getElementById('record-source-select').value) === 'system', 'the source was lost as the panel closed');
  await page.click('#st-rail-source');
  await sleep(150);
  await page.click(`#st-src-${before}`);
  await page.keyboard.press('Escape');
  await page.setViewportSize({ width: 1300, height: 860 });
  await sleep(150);
});

// First-run wizard: a set is chosen and its settings are written; nothing is really downloaded here
await step('first run wizard', async () => {
  const sent = [];
  const stub = r => r.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
  await page.route('**/api/settings', r => {
    if (r.request().method() !== 'POST') return r.continue();
    sent.push(r.request().postDataJSON().settings);
    return stub(r);
  });
  for (const url of ['**/api/models/setup', '**/api/onnx-models/**', '**/api/ffmpeg/install', '**/api/ollama/**']) await page.route(url, stub);
  await page.evaluate(() => { document.querySelectorAll('.modal-backdrop').forEach(m => m.id === 'first-run-wizard' && m.remove()); openFirstRunWizard(state.system); });
  await sleep(300);
  // One topic a step: the AI analysis, the sound, (calls: Windows only), the calendar, then what downloads (the language is not asked:
  // the recommended set). The head says which step of how many (found in the audit: the dots alone did not)
  const stepOf = () => page.evaluate(() => {
    const m = document.querySelector('#first-run-wizard .frw-step')?.textContent.match(/(\d+)\D+(\d+)/);
    return m ? [+m[1], +m[2], document.querySelectorAll('#first-run-wizard .frw-dot').length] : null;
  });
  const s1 = await stepOf();
  await page.click('#first-run-wizard button[data-pick="ai:none"]');
  await page.click('#first-run-wizard button[data-a="next"]');
  const s2 = await stepOf();
  expect(s1 && s2 && s1[0] === 1 && s2[0] === 2 && s1[1] === s1[2] && s2[1] === s1[1], `the step in the head: ${JSON.stringify([s1, s2])}`);
  // Where the sound comes from: the microphone only
  await page.click('#first-run-wizard button[data-src="mic"]');
  await page.click('#first-run-wizard button[data-a="next"]');
  // The calendar with every meeting recorded: that turns the start with Windows on as well
  await page.click('#first-run-wizard label:has(input[data-auto="cal"])');
  await page.fill('#first-run-wizard input[data-cal-src]', 'https://example.com/basic.ics');
  await page.click('#first-run-wizard label:has(input[data-auto="allMeet"])');
  expect(await page.inputValue('#first-run-wizard input[data-cal-src]') === 'https://example.com/basic.ics', 'the calendar address was lost on a redraw');
  // The country of the public holidays on the same step (asked by the user: chosen at the first start); a region where it has them
  await page.waitForSelector('#first-run-wizard select[data-hol-country] option[value="DE"]', { state: 'attached' });
  await page.selectOption('#first-run-wizard select[data-hol-country]', 'DE');
  await page.selectOption('#first-run-wizard select[data-hol-subdiv]', 'BY');
  expect(await page.inputValue('#first-run-wizard input[data-cal-src]') === 'https://example.com/basic.ics', 'the calendar address was lost when the country changed');
  await page.click('#first-run-wizard button[data-a="next"]');
  expect(await page.isChecked('#first-run-wizard input[data-auto="startup"]'), 'the start with Windows did not follow the recording of meetings');
  expect((await page.textContent('#first-run-dialog')).includes(await page.evaluate(() => t('frwShortAll'))), 'the summary does not list the automation');
  // The precise mode on the last step: every speech model joins the models to download
  await page.click('#first-run-wizard label:has(input[data-ens])');
  await sleep(200);
  const listed = await page.textContent('#first-run-dialog');
  expect(listed.includes('Whisper Pro') && listed.includes('Parakeet'), 'not every speech model among the downloads');
  await page.click('#first-run-wizard button[data-a="next"]');
  await sleep(600);
  await page.unrouteAll({ behavior: 'ignoreErrors' });
  const first = sent[0] || {};
  expect(first.asr_ensemble === 'true', `precise mode not saved: ${JSON.stringify(first)}`);
  expect((first.asr_ensemble_models || '').split(',').length === 4, `not every model in the precise mode: ${JSON.stringify(first)}`);
  expect(!(await page.$('#first-run-wizard')), 'the wizard stayed open');
  expect(first.speech_model_ru === 'gigaam-v3', `Russian model not set: ${JSON.stringify(first)}`);
  expect(['parakeet-v3', 'large-v3-turbo'].includes(first.whisper_model), `main model not set: ${JSON.stringify(first)}`);
  expect(first.language === 'auto', `language not left to detection: ${JSON.stringify(first)}`);
  expect(first.record_source_mode === 'mic', `the sound source not saved: ${JSON.stringify(first)}`);
  expect(first.start_with_windows === 'true' && first.close_to_tray === 'true', `the start with Windows not saved: ${JSON.stringify(first)}`);
  expect(first.holiday_country === 'DE' && first.holiday_subdiv === 'BY', `the country of the holidays not saved: ${JSON.stringify(first)}`);
  expect(JSON.parse(first.setup_done || '[]').includes('holidays'), `the steps after an update would ask again: ${JSON.stringify(first)}`);
  expect(!('calendar_ics' in first), 'the calendar went with the other settings: a refused address would lose them all');
  const cal = sent.find(x => 'calendar_ics' in x) || {};
  expect(cal.calendar_ics === 'https://example.com/basic.ics' && cal.meet_auto_all === 'true', `the calendar not saved: ${JSON.stringify(sent)}`);
});

// After an update: ONE window — the settings a new version asks answered in place (amber «Нужен ответ», then
// green «Сохранено»), the new features as cards, all the changes folded as «Новое» and «Исправлено»; «Готово»
// marks every step answered, and they are not asked again
await step('window after an update', async () => {
  // what the step changes is put back as it was: leaving the steps unanswered opened this window again over the
  // later steps after a reload (CI: «#upd-after intercepts pointer events» in the calendar steps)
  const before = await page.evaluate(() => fetch('/api/system').then(r => r.json())
    .then(d => ({ holiday_country: d.settings.holiday_country || '', holiday_subdiv: d.settings.holiday_subdiv || '', setup_done: d.settings.setup_done || '[]' })));
  await page.evaluate(() => document.querySelectorAll('.modal-backdrop').forEach(m => m.id === 'first-run-wizard' && m.remove()));
  await page.evaluate(() => openSetupSteps({ holiday_country: '', setup_done: '[]' }));
  await page.waitForSelector('#upd-after select[data-hol-country] option[value="RS"]', { state: 'attached' });
  await page.selectOption('#upd-after select[data-hol-country]', 'RS');
  expect(!(await page.$('#upd-after select[data-hol-subdiv]')), 'a region offered for a country without them');
  expect(await page.$('#upd-after .upd-chip-warn'), 'the step does not say it needs an answer');
  await page.click('#upd-after button[data-a="save"]');
  for (let i = 0; i < 50 && !(await page.$('#upd-after .upd-chip-ok')); i++) await sleep(100);
  expect(await page.$('#upd-after .upd-chip-ok'), 'the step is not marked saved');
  expect(await page.evaluate(() => document.querySelectorAll('#upd-after .upd-card').length) >= 1, 'no new features');
  // the notes of the version join the same window: «Новое» and «Исправлено» as lists
  await page.evaluate(() => openAfterUpdateNotes('- **Подключение к звонку**: кнопка в карточке встречи.\n- Субтитры больше не пропадают после переключения окна.\n', '0.8.27', ''));
  expect(await page.evaluate(() => document.querySelectorAll('#upd-after').length) === 1, 'two windows after an update');
  await page.click('#upd-after button[data-a="all"]');
  const notes = await page.evaluate(() => ({ heads: [...document.querySelectorAll('#upd-after .upd-all-h')].map(h => h.textContent),
    items: document.querySelectorAll('#upd-after .upd-all li').length, bold: !!document.querySelector('#upd-after .upd-all li strong') }));
  expect(notes.heads.join() === 'Новое,Исправлено' && notes.items === 2 && notes.bold, `the changes are not lists: ${JSON.stringify(notes)}`);
  await page.click('#upd-after button[data-a="done"]');
  for (let i = 0; i < 50 && await page.$('#upd-after'); i++) await sleep(100);
  expect(!(await page.$('#upd-after')), 'the window stayed open');
  const set = await page.evaluate(() => fetch('/api/system').then(r => r.json()).then(d => d.settings));
  expect(set.holiday_country === 'RS', `the country not saved: ${set.holiday_country}`);
  // answered: not asked again
  await page.evaluate(sv => openSetupSteps(sv), set);
  await sleep(400);
  expect(!(await page.$('#upd-after')), 'asked again after it was answered');
  await page.evaluate(b => fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ settings: b }) }), before);
});

// A calendar meeting about to start with a Teams link: «Подключиться» on its card joins the call (asked by the user)
await step('join a meeting call', async () => {
  const sent = [];
  await page.route('**/api/meeting/join', r => { sent.push(r.request().postDataJSON()); r.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' }); });
  await page.evaluate(() => {
    switchAppView('home');
    Object.assign(state.system.settings, { work_day_start: '0', work_day_end: '24' });  // the meeting is in the day shown, whatever the time
    const s = new Date(Date.now() + 5 * 60e3), e = new Date(s.getTime() + 30 * 60e3);
    home.calConfigured = true;
    home.events = [{ key: 'j|1', title: 'Синк с командой', start: s.toISOString(), end: e.toISOString(), s, e, attendees: [], online: true,
      join: 'https://teams.microsoft.com/l/meetup-join/19%3ameeting_x%40thread.v2/0' }];
    home.eventsAt = Date.now();
    renderHomeNow();
  });
  await sleep(300);
  await page.click('.hm-mt-join');
  await sleep(300);
  await page.unroute('**/api/meeting/join');
  expect(sent.length === 1 && sent[0].url.startsWith('https://teams.microsoft.com/'), `the call was not opened: ${JSON.stringify(sent)}`);
});

// The card of a feature: its weeks, its people (asked by the user)
await step('feature card', async () => {
  const fid = await page.evaluate(async () => {
    const f = await fetch('/api/features', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: 'Карточка' }) }).then(r => r.json());
    await fetch('/api/meetings/1/features', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids: [f.id] }) });
    return f.id;
  });
  await page.evaluate(id => openFeaturePage(id), fid);
  await sleep(800);
  expect(await page.locator('#feature-page .fp-week').count() === 12, 'no 12 weeks on the card');
  expect(await page.locator('#feature-page .fp-now .fp-box').count() === 3, 'no «Сейчас» on the card');
  expect(await page.locator('#feature-page .fp-stats3 .fp-stat').count() === 3, 'not three numbers');
  expect(await page.locator('#feature-page .fp-person').count() > 0, 'no people on the card');
  // «Главная»'s widget «Фичи» opens the card (asked by the user)
  await page.evaluate(() => { document.getElementById('feature-page')?.remove(); switchAppView('dashboard'); });
  await page.evaluate(() => { const l = dbPrefs().layout.filter(w => w.id !== 'features'); dbSave({ layout: [{ id: 'features', size: 'L' }, ...l] }); return loadDashboard(); });
  await sleep(800);
  await page.click(`#db-grid .db-ft-row[data-click-args='[${fid}]']`);
  await sleep(800);
  expect(await page.$('#feature-page'), 'the widget does not open the card');
  await page.evaluate(id => { document.getElementById('feature-page')?.remove(); return fetch('/api/features/' + id, { method: 'DELETE' }); }, fid);
});

// The calendar window: a day marked a day off from its «⋯», then taken back (asked by the user)
await step('day off from the calendar', async () => {
  await page.evaluate(() => { calView.mode = 'month'; openCalendarView(); });
  await sleep(800);
  const day = await page.evaluate(() => calKey(new Date()));
  await page.hover(`#cal-view [data-daykey="${day}"]`);
  await page.click(`#cal-view [data-daykey="${day}"] .cal-day-more`);
  await sleep(200);
  await page.click('#text-menu button:has-text("Отметить выходным")');
  await until(d => !!document.querySelector(`#cal-view [data-daykey="${d}"].cal-holday`), 'the day is not marked', 5000, day);
  await page.click(`#cal-view [data-daykey="${day}"]`, { button: 'right' });
  await sleep(200);
  await page.click('#text-menu button:has-text("Убрать выходной")');
  await until(d => !document.querySelector(`#cal-view [data-daykey="${d}"].cal-holday`), 'the day off is not taken back', 5000, day);
  await page.evaluate(() => closeCalendarView());
});

// Settings → Календарь: a vacation marked by hand is saved at once and listed (asked by the user)
await step('own days off', async () => {
  await page.evaluate(() => { openModal('settings', 'general'); selectSettingsTab('calendar'); });
  // another tab of Settings fades in, like the views (asked by the user: it changed abruptly)
  expect(await page.evaluate(() => [...document.querySelectorAll('#modal-settings [data-stab]:not(.hidden)')].some(el => el.classList.contains('vx-in'))),
    'the settings tab did not fade in');
  await sleep(400);
  await page.evaluate(() => {
    document.getElementById('dayoff-from').value = '2026-03-02';
    document.getElementById('dayoff-to').value = '2026-03-04';
    document.getElementById('dayoff-title').value = 'Отпуск';
  });
  // waited for, not timed: a slow computer (CI) saves later
  const listed = async want => {
    for (let i = 0; i < 50; i++) {
      if ((await page.textContent('#dayoff-list')).includes('Отпуск') === want) return true;
      await sleep(100);
    }
    return false;
  };
  await page.click('button[data-click="addDayOff"]');
  expect(await listed(true), 'the vacation is not listed');
  const set = await page.evaluate(() => fetch('/api/system').then(r => r.json()).then(d => d.settings));
  expect(JSON.parse(set.days_off)[0].to === '2026-03-04', `not saved: ${set.days_off}`);
  await page.click('#dayoff-list button[data-click="removeDayOff"]');
  expect(await listed(false), 'the vacation was not removed');
  await sleep(1500);  // a fill of the settings asked for before must not bring it back
  expect(!(await page.textContent('#dayoff-list')).includes('Отпуск'), 'the vacation came back');
  await page.evaluate(() => closeModal('settings'));
});

// The choice without analysis keeps the speech settings (no stub here: the real server must accept the
// request); there is no cloud choice any more
await step('first run wizard, no analysis', async () => {
  for (const url of ['**/api/models/setup', '**/api/onnx-models/**', '**/api/ffmpeg/install', '**/api/ollama/**']) {
    await page.route(url, r => r.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
  }
  let status = 0;
  const watch = r => { if (r.url().endsWith('/api/settings') && r.request().method() === 'POST' && !status) status = r.status(); };
  page.on('response', watch);
  await page.evaluate(() => openFirstRunWizard(state.system));
  await sleep(300);
  expect(!(await page.$('#first-run-wizard button[data-pick="ai:cloud"]')), 'the cloud choice is still offered');
  await page.click('#first-run-wizard button[data-pick="ai:none"]');
  await page.click('#first-run-wizard button[data-a="next"]');
  await page.click('#first-run-wizard button[data-a="next"]');
  await page.click('#first-run-wizard button[data-a="next"]');
  await page.click('#first-run-wizard button[data-a="next"]');
  await sleep(800);
  page.off('response', watch);
  await page.unrouteAll({ behavior: 'ignoreErrors' });
  expect(status === 200, `the settings were refused (HTTP ${status})`);
  const v = await page.evaluate(() => fetch('/api/system').then(r => r.json()).then(d => d.settings));
  expect(v.speech_model_ru === 'gigaam-v3', `Russian model not saved: ${v.speech_model_ru}`);
  expect(!('llm_provider' in v), 'a cloud setting is stored');
  await page.evaluate(() => closeModal('settings'));
});

// «Сегодня»: «Календарь» День · Неделя · Месяц — the week and the month over the width, the cards under them,
// ‹ › move by a week, the day comes back with its meetings (docs/pult-plan.md, stage 3)
await step('today calendar', async () => {
  await page.evaluate(() => { dbSave({ span: 'day' }); switchAppView('home'); });
  await sleep(500);
  expect(await page.isVisible('#rail-home.rail-on'), '«Сегодня» is not marked on the rail');
  expect(await page.isVisible('#td-day') && await page.locator('#td-cards .td-card').count() >= 3, 'the day or its cards are missing');
  await page.click('#td-spans button >> nth=1');
  await sleep(700);
  expect(await page.isVisible('#td-cal .cal-week') && !(await page.isVisible('#td-day')), 'the week did not show');
  expect(await page.evaluate(() => document.getElementById('td-body').classList.contains('td-row')), 'the cards are not under the week');
  const label = await page.textContent('#td-sub');
  await page.click('#td-nav button >> nth=2');
  await sleep(500);
  expect((await page.textContent('#td-sub')) !== label, '› did not move to the next week');
  await page.click('#td-nav button >> nth=1');
  await page.click('#td-spans button >> nth=2');
  await sleep(700);
  expect(await page.isVisible('#td-cal .cal-month .cal-cell.cal-today'), 'the month or its today did not show');
  if (process.env.SHOTS) await page.screenshot({ path: `${process.env.SHOTS}/today-month.png` });
  await page.click('#td-spans button >> nth=0');
  await sleep(300);
  expect(await page.isVisible('#td-day') && !(await page.isVisible('#td-cal')), 'the day did not come back');
  // Ctrl+2 opens «Обзор», Ctrl+1 «Сегодня»
  await page.keyboard.press('Control+2');
  await sleep(300);
  expect(await page.evaluate(() => state.appView) === 'dashboard', 'Ctrl+2 did not open «Обзор»');
  await page.keyboard.press('Control+1');
  await sleep(300);
  expect(await page.evaluate(() => state.appView) === 'home', 'Ctrl+1 did not open «Сегодня»');
});

// «Сегодня»: a day of the week opens in «День» with its date and its meetings; ‹ steps back a day, «Сегодня» returns
// (asked by the user). The calendar of tests/ui/seed.py has a meeting every day around today
await step('today open a day', async () => {
  await page.evaluate(async () => {
    await hmSave({ calendar_ics: `${state.system.paths.data}/demo-calendar.ics`, work_day_start: '9', work_day_end: '18' });
    home.eventsAt = 0; home.days = {};
    TD.cal.anchor = null; dbSave({ span: 'day' }); switchAppView('home');
  });
  await sleep(600);
  await page.click('#td-spans button >> nth=1');
  await page.waitForSelector('#td-cal .cal-week .cal-col.cal-open');
  // a day of this week other than today, by a click on an empty part of its column
  const key = await page.evaluate(() => [...document.querySelectorAll('#td-cal .cal-col')].map(c => c.dataset.daykey).find(k => k !== calKey(new Date())));
  const col = page.locator(`#td-cal .cal-col[data-daykey="${key}"]`);
  expect(await col.getAttribute('title') === await page.evaluate(() => t('calOpenDay')), 'the day has no «Открыть день» hint');
  // the week is drawn again once the calendar just saved is read: the column of that drawing is waited for
  await until(k => { const el = document.querySelector(`#td-cal .cal-col[data-daykey="${k}"]`);
    return !!el && getComputedStyle(el).cursor === 'pointer'; }, 'no hand over the day', 5000, key);
  // the week may be drawn once more meanwhile: the column of that drawing is measured
  let box = null;
  for (let i = 0; i < 30 && !box; i++) { box = await col.boundingBox().catch(() => null); if (!box) await sleep(100); }
  expect(!!box, 'the column of the day is gone');
  await page.mouse.click(box.x + box.width / 2, box.y + box.height - 12);
  await sleep(900);
  expect(await page.isVisible('#td-day') && !(await page.isVisible('#td-cal')), 'the click on a day did not open «День»');
  const shown = await page.evaluate(() => ({ title: document.getElementById('td-title').textContent, card: document.getElementById('hm-mt-title').textContent,
    view: hmViewDate() && calKey(hmViewDate()), meetings: [...document.querySelectorAll('#hm-timeline .hm-mt')].map(x => x.textContent),
    now: !!document.querySelector('#hm-timeline .hm-now'), nav: !document.getElementById('td-nav').classList.contains('hidden') }));
  const date = await page.evaluate(k => new Date(`${k}T12:00`).toLocaleDateString(hmLocale(), { day: 'numeric', month: 'long' }), key);
  expect(shown.view === key, `«День» shows ${shown.view}, not ${key}`);
  expect(shown.title.includes(date) && shown.card.includes(date), `the head or the card does not name the day: ${shown.title} / ${shown.card}`);
  expect(shown.meetings.some(x => x.includes('Ежедневная встреча')), `the meetings of the day are missing: ${shown.meetings}`);
  expect(!shown.now && shown.nav, 'the line of now on another day, or no ‹ Сегодня ›');
  // ‹: the day before
  await page.click('#td-nav button >> nth=0');
  await sleep(900);
  const prev = await page.evaluate(k => { const d = new Date(`${k}T12:00`); d.setDate(d.getDate() - 1); return calKey(d); }, key);
  const back = await page.evaluate(() => hmViewDate() ? calKey(hmViewDate()) : calKey(hmDay().from));
  expect(back === prev, `‹ went to ${back}, not ${prev}`);
  // Неделя keeps the day: the week of the day shown
  await page.click('#td-spans button >> nth=1');
  await sleep(700);
  expect(await page.locator(`#td-cal .cal-col[data-daykey="${prev}"]`).count() === 1, 'the week is not the one of the day shown');
  await page.click('#td-spans button >> nth=0');
  await sleep(500);
  // «Сегодня»: today again, its line of now (the working day of the whole day, whatever the time)
  await page.evaluate(() => hmSave({ work_day_start: '0', work_day_end: '0' }));
  await page.click('#td-nav button >> nth=1');
  await sleep(900);
  const today = await page.evaluate(() => ({ view: hmViewDate(), title: document.getElementById('td-title').textContent, card: document.getElementById('hm-mt-title').textContent,
    now: !!document.querySelector('#hm-timeline .hm-now') }));
  expect(!today.view && today.title === await page.evaluate(() => t('tdToday')) && today.card === await page.evaluate(() => t('hmMeetings')), `«Сегодня» did not return: ${JSON.stringify(today)}`);
  expect(today.now, 'no line of now on today');
  await page.evaluate(async () => {
    await hmSave({ calendar_ics: '', work_day_start: '9', work_day_end: '18' });
    home.eventsAt = 0; home.days = {}; home.events = [];
    await hmLoad(true);
  });
});

// The calendar window of a week or a month opens and closes with Esc
await step('calendar view', async () => {
  await page.evaluate(() => switchAppView('home'));
  await sleep(500);
  await page.evaluate(() => openCalendarView());
  await sleep(600);
  expect(await page.isVisible('#cal-view .cal-week, #cal-view .cal-month'), 'the calendar did not open');
  await page.click('#cal-view button[data-cal="month"]');
  await sleep(500);
  expect(await page.isVisible('#cal-view .cal-month'), 'the month did not show');
  // today stands out in the month too (its cell rule once hid the mark)
  const marked = await page.evaluate(() => {
    const today = document.querySelector('#cal-view .cal-cell.cal-today');
    const other = [...document.querySelectorAll('#cal-view .cal-cell:not(.cal-today):not(.cal-out)')][0];
    return !!today && !!other && getComputedStyle(today).borderTopColor !== getComputedStyle(other).borderTopColor;
  });
  expect(marked, 'today is not marked in the month');
  if (process.env.SHOTS) await page.screenshot({ path: `${process.env.SHOTS}/cal-month.png` });
  await page.click('#cal-view button[data-cal="week"]');
  await sleep(400);
  await page.keyboard.press('Escape');
  await sleep(200);
  expect(!(await page.$('#cal-view')), 'Esc did not close the calendar');
});

// «Записи»: the table by day in cards, sorted by a header, a column added in «Колонки» (the view switch stays
// where it was), the other views, the box selects and the bar of the selection takes the filters' place at
// their height, the search shows the places found in the texts, a click opens the recording
await step('records section', async () => {
  await page.click('#rail-libtable');  // the rail's «Записи» (the old sidebar's button is gone)
  await sleep(500);
  expect(await page.isVisible('#libtable-view'), 'the section did not open');
  const rows = await page.$$eval('#lt-body .lt-card [data-mid]', els => els.length);
  expect(rows > 0, 'the table has no rows');
  expect(await page.$eval('#lt-body .lt-card-h', h => !!h.querySelector('.lt-card-ic') && !!h.querySelector('.lt-card-n')), 'a day card has no icon or count');
  expect(await page.$eval('#lt-body .lt-row', r => getComputedStyle(r).cursor) === 'pointer', 'a row has no hand cursor');
  await page.click('#lt-body .lt-hc[data-col="name"]');
  await sleep(200);
  expect(await page.isVisible('#lt-body .lt-hc.lt-sorted[data-col="name"]'), 'the name header did not sort');
  // the names of the columns: one bar above the cards, each name over its column
  expect(await page.locator('#lt-body .lt-hrow').count() === 1, 'the column names are not one bar');
  const offs = await page.$$eval('#lt-body .lt-hc[data-col]', hs => hs.map(h => {
    const cell = document.querySelector(`#lt-body .lt-row .lt-c-${h.dataset.col}`);
    return cell ? Math.abs(h.getBoundingClientRect().left - cell.getBoundingClientRect().left) : 99;
  }));
  expect(offs.every(d => d < 1), `a column name is off its column: ${offs.join(', ')}`);
  const segAt = () => page.$eval('#lt-bar .lt-seg', el => Math.round(el.getBoundingClientRect().left));
  const before = await segAt();
  await page.click('[data-lt-cols]');
  await page.click('#lt-cols-pop input[data-col="size"]');
  await sleep(200);
  expect(await page.isVisible('#lt-body .lt-hc[data-col="size"]'), 'the size column did not appear');
  expect(await segAt() === before, 'the view switch moved with the columns');
  // «Строки: Компактные» in «Колонки» makes the rows lower
  const rowH = () => page.$eval('#lt-body .lt-row', r => r.getBoundingClientRect().height);
  const h1 = await rowH();
  await page.click('#lt-cols-pop [data-dense="1"]');
  await sleep(200);
  expect(await rowH() < h1, 'compact rows are not lower');
  await page.click('#lt-cols-pop [data-col-reset]');
  await page.keyboard.press('Escape');
  for (const v of ['cards', 'folders']) {
    await page.click(`#lt-bar .lt-seg-b[data-click-args='["${v}"]']`);
    await sleep(200);
    expect(await page.locator('#lt-body [data-mid]').count() > 0, `no recordings in the view ${v}`);
    expect(await segAt() === before, `the view switch moved in the view ${v}`);
    expect(await page.isEnabled('[data-lt-cols]'), `«Колонки» is off in the view ${v}`);
  }
  // in «Карточки» «Колонки» chooses the details of the cards
  await page.click(`#lt-bar .lt-seg-b[data-click-args='["cards"]']`);
  await sleep(200);
  await page.click('[data-lt-cols]');
  await page.click('#lt-cols-pop input[data-col="status"]');
  await sleep(200);
  expect(await page.locator('#lt-body .lt-tile .lt-st').count() === 0, 'the state stays on the cards after it was unticked');
  await page.click('#lt-cols-pop [data-col-reset]');
  await page.keyboard.press('Escape');
  await page.click(`#lt-bar .lt-seg-b[data-click-args='["table"]']`);
  await sleep(200);
  const barH = () => page.$eval('#lt-bar', el => Math.round(el.getBoundingClientRect().height + parseFloat(getComputedStyle(el).marginBottom)));
  const h0 = await barH();
  await page.click('#lt-body .lt-row .lt-cbx');
  await sleep(200);
  expect(await page.isVisible('#lt-bar.lt-selbar'), 'the selection bar did not show');
  expect(/В папку/.test(await page.textContent('#lt-bar')) && /Расшифровать/.test(await page.textContent('#lt-bar')), 'the selection bar lacks its actions');
  expect(await barH() === h0, 'the list moved when a recording was selected');
  await page.click('#lt-bar button[data-click="clearLibSelection"]');
  await page.fill('#lt-q', 'тема');
  await page.waitForSelector('#lt-body .lt-snip', { timeout: 6000 }).catch(() => {});
  expect(await page.locator('#lt-body .lt-snip').count() > 0, 'the search shows no places in the text');
  expect(/мест/.test(await page.textContent('#lt-count')), 'the count does not say how many places were found');
  await page.fill('#lt-q', '');
  await sleep(300);
  await page.click('#lt-body .lt-row .lt-c-name');
  await sleep(600);
  expect(await page.evaluate(() => state.appView) === 'library', 'a click did not open the recording');
});

// «Обработать всё» in the head of «Записи», the status's «Распознать» / «Анализ» and the feature cell's «Выбрать
// фичу» on hover and focus, in the same place (no width changes). CI has no models: the routes are answered here,
// and the recordings without a text or an analysis are made in the page only
await step('records process pending', async () => {
  await page.evaluate(() => switchAppView('libtable'));
  await until(() => !document.getElementById('libtable-view').classList.contains('hidden') && document.querySelector('#lt-body .lt-row'), 'records did not open');
  await until(() => document.getElementById('lt-process')?.disabled === true, 'the button is on while every recording is analysed');
  const sent = [];
  await page.route('**/api/library/process-pending', r => {
    const b = r.request().postDataJSON();
    sent.push(b);
    r.fulfill({ status: 200, contentType: 'application/json',
      body: JSON.stringify(b.dry_run ? { transcribe: 1, analyse: 1, analysis_ready: true } : { transcribe: b.transcribe ? 1 : 0, analyse: 1, analysis_waiting: 0, analysis_ready: true }) });
  });
  await page.route('**/api/meetings/*/retry', r => { sent.push({ retry: r.request().url() }); r.fulfill({ status: 200, contentType: 'application/json', body: '{}' }); });
  const ids = await page.evaluate(() => {
    const [a, b] = state.meetings;
    Object.assign(a, { status: 'added', has_transcript: false, has_summary: false, features: [] });
    Object.assign(b, { has_summary: false });
    // a recognition model «downloaded» for «Распознать» (requireRecognitionModel)
    const sel = document.getElementById('upload-model');
    if (sel && !sel.value) { sel.add(new Option('test', 'test-model')); sel.value = 'test-model'; window.__ltOpt = true; }
    window.__ltList = JSON.parse(JSON.stringify(state.meetings));
    renderLibTable();
    return { a: a.id, b: b.id };
  });
  // the list read again after an action would bring the analysed recordings back: the one made here is answered
  const list = await page.evaluate(() => window.__ltList);
  await page.route('**/api/meetings', r => (r.request().method() === 'GET'
    ? r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(list) }) : r.continue()));
  try {
    await until(() => document.getElementById('lt-process')?.disabled === false, 'the button is off with work left');
    // the search stays the last control, at the right edge
    expect(await page.evaluate(() => document.getElementById('lt-process').getBoundingClientRect().right
      <= document.querySelector('#libtable-view .tk-search').getBoundingClientRect().left), 'the button is not before the search');
    await page.click('#lt-process');
    await until(() => document.querySelector('div.modal-backdrop[role="dialog"]:not([id]) button[data-a="yes"]'), 'no confirmation with the counts');
    const text = await page.textContent('div.modal-backdrop[role="dialog"]:not([id])');
    const words = await page.evaluate(() => [t('ltProcessTr'), t('ltProcessAn')]);
    expect(text.includes(`${words[0]}: 1`) && text.includes(`${words[1]}: 1`), `the confirmation does not show the counts: ${text}`);
    await page.click('div.modal-backdrop[role="dialog"]:not([id]) button[data-a="yes"]');
    await until(() => document.getElementById('toast')?.textContent.includes(t('ltProcessDone').split(':')[0]), 'no toast with the result');
    expect(sent.some(b => b.dry_run) && sent.some(b => !b.dry_run && b.transcribe && b.analyse && !b.ids), `the batch was not sent: ${JSON.stringify(sent)}`);
    // the status: «Распознать» and «Анализ» in the place of the status, the same width
    const hoverSwap = async (sel, word) => {
      await until(s => document.querySelector(s), `no ${sel}`, 5000, sel);
      const w0 = await page.$eval(sel, e => e.getBoundingClientRect().width);
      await page.hover(sel);
      await until(([s, w]) => [...document.querySelector(s).querySelectorAll('span')].some(x => !x.children.length && x.textContent === w
        && getComputedStyle(x).visibility === 'visible'), `${sel} does not show «${word}» on hover`, 3000, [sel, word]);
      const w1 = await page.$eval(sel, e => e.getBoundingClientRect().width);
      expect(Math.abs(w1 - w0) < 0.5, `${sel} changed its width on hover: ${w0} -> ${w1}`);
    };
    await hoverSwap(`#lt-body [data-st-act="transcribe"][data-st-id="${ids.a}"]`, await page.evaluate(() => t('ltStTranscribe')));
    await page.click(`#lt-body [data-st-act="transcribe"][data-st-id="${ids.a}"]`);
    await until(() => !document.getElementById('libtable-view').classList.contains('hidden'), 'a click on the status left the section');
    await sleep(300);
    expect(sent.some(b => b.retry && b.retry.includes(`/api/meetings/${ids.a}/retry`)), '«Распознать» did not queue the recording');
    expect(await page.evaluate(() => state.appView) === 'libtable', 'a click on the status opened the recording');
    await hoverSwap(`#lt-body [data-st-act="analyse"][data-st-id="${ids.b}"]`, await page.evaluate(() => t('ltStAnalyse')));
    await page.click(`#lt-body [data-st-act="analyse"][data-st-id="${ids.b}"]`);
    await until(() => document.getElementById('toast')?.textContent.includes(t('ltAnalysisQueued')), '«Анализ» said nothing');
    expect(sent.some(b => !b.dry_run && JSON.stringify(b.ids) === `[${ids.b}]` && b.transcribe === false), `«Анализ» did not queue this recording: ${JSON.stringify(sent)}`);
    // the feature cell: «Выбрать фичу» in the place of «—», and the keyboard opens the menu of the features
    await page.mouse.move(2, 2);
    await hoverSwap(`#lt-body [data-ft-pick="${ids.a}"]`, await page.evaluate(() => t('ltFtChoose')));
    await page.mouse.move(2, 2);
    await page.focus(`#lt-body [data-ft-pick="${ids.a}"]`);
    await page.keyboard.press('Enter');
    await until(() => document.getElementById('text-menu'), 'Enter on «Выбрать фичу» opened no menu');
    expect(await page.evaluate(() => state.appView) === 'libtable', 'Enter on «Выбрать фичу» opened the recording');
    await page.evaluate(() => closeTextMenu());
  } finally {  // a failed check leaves no answered route and no model behind for the next steps
    await page.unrouteAll({ behavior: 'ignoreErrors' });
    await page.evaluate(async () => {
      if (window.__ltOpt) { const sel = document.getElementById('upload-model'); sel.querySelector('option[value="test-model"]')?.remove(); sel.value = sel.options[0]?.value || ''; }
      await loadMeetingsList();
    });
  }
});

// The buttons of a row of «Записи» (review): Shift, Ctrl or ⌘ on the status's action or the feature cell change the
// selection and run nothing; with several selected the feature cell is for all of them and the status's action for its
// row only; a click there closes the menus left open; «Распознать» of a recording with a text asks first; «Анализ»
// already queued says so; after Enter on «Распознать» the focus stays in the table; Tab stops at the current row only;
// the ring of the focus is drawn inside the button (the cell cut it)
await step('records row buttons', async () => {
  await page.evaluate(() => switchAppView('libtable'));
  await until(() => !document.getElementById('libtable-view').classList.contains('hidden') && document.querySelector('#lt-body .lt-row'), 'records did not open');
  const sent = [];
  let analyse = 1;
  await page.route('**/api/library/process-pending', r => {
    const b = r.request().postDataJSON();
    sent.push(b);
    r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ transcribe: 0, analyse, analysis_waiting: 0, analysis_ready: true }) });
  });
  await page.route('**/api/meetings/*/retry', r => { sent.push({ retry: r.request().url() }); r.fulfill({ status: 200, contentType: 'application/json', body: '{}' }); });
  const ids = await page.evaluate(() => {
    const [a, b, c] = state.meetings;
    Object.assign(a, { status: 'failed', transcript_model: null, has_transcript: false, has_summary: false });
    Object.assign(b, { status: 'completed', has_transcript: true, has_summary: false });
    Object.assign(c, { status: 'cleared', has_transcript: false, has_summary: false });
    const sel = document.getElementById('upload-model');
    if (sel && !sel.value) { sel.add(new Option('test', 'test-model')); sel.value = 'test-model'; window.__ltOpt = true; }
    window.__ltList = JSON.parse(JSON.stringify(state.meetings));
    state.multi.clear();
    LT.cur = null;
    renderLibTable();
    return { a: a.id, b: b.id, c: c.id };
  });
  const list = await page.evaluate(() => window.__ltList);
  await page.route('**/api/meetings', r => (r.request().method() === 'GET'
    ? r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(list) }) : r.continue()));
  const st = (id) => `#lt-body [data-st-id="${id}"]`, ft = (id) => `#lt-body [data-ft-pick="${id}"]`;
  const dialog = 'div.modal-backdrop[role="dialog"]:not([id])';
  try {
    await until(s => document.querySelector(s), 'no «Распознать» of the failed recording', 5000, st(ids.a));
    // Shift and Ctrl: the selection, no action
    await page.click(st(ids.a), { modifiers: ['Shift'] });
    await sleep(300);
    expect(!sent.some(b => b.retry), `Shift+click on «Распознать» queued the recording: ${JSON.stringify(sent)}`);
    expect(await page.evaluate(id => state.multi.has(id), ids.a), 'Shift+click on the status did not select the row');
    await page.click(ft(ids.b), { modifiers: ['Control'] });
    await sleep(200);
    expect(!(await page.evaluate(() => !!document.getElementById('text-menu'))), 'Ctrl+click on the feature cell opened its menu');
    expect(await page.evaluate(id => state.multi.has(id), ids.b), 'Ctrl+click on the feature cell did not select the row');
    // several selected: the feature cell of a selected row is for all of them, the status's action for its row only
    await page.evaluate(([a, b]) => {
      state.multi = new Set([a, b]); ltPaintPick();
      window.__ltFtReal = window.ltFeatureItems;
      window.ltFeatureItems = (l) => { window.__ltFtList = l.map(m => m.id); return window.__ltFtReal(l); };
    }, [ids.a, ids.b]);
    await page.click(ft(ids.a));
    await until(() => document.getElementById('text-menu'), 'the feature cell opened no menu with a selection');
    const forList = await page.evaluate(() => { window.ltFeatureItems = window.__ltFtReal; closeTextMenu(); return window.__ltFtList; });
    expect(JSON.stringify((forList || []).slice().sort()) === JSON.stringify([ids.a, ids.b].sort()), `the feature menu is not for the selection: ${forList}`);
    await page.click(st(ids.b));
    await until(() => document.getElementById('toast')?.textContent.includes(t('ltAnalysisQueued')), '«Анализ» said nothing');
    expect(sent.some(b => JSON.stringify(b.ids) === `[${ids.b}]`), `«Анализ» was not for its row only: ${JSON.stringify(sent)}`);
    expect(await page.evaluate(() => state.multi.size) === 2, 'the status\'s action changed the selection');
    await page.evaluate(() => clearLibSelection());
    // «Анализ» queued already: said
    analyse = 0;
    await page.click(st(ids.b));
    await until(() => document.getElementById('toast')?.textContent.includes(t('ltAnalysisBusy')), '«Анализ» queued already said nothing');
    analyse = 1;
    // a menu left open closes on a click on the status or the feature cell
    // the menu below the row, not over its buttons
    const ctx = (id) => page.evaluate(i => {
      const r = document.querySelector(`#lt-body [data-mid="${i}"]`).getBoundingClientRect();
      openRecordingContextMenu({ clientX: r.left + 30, clientY: r.bottom + 40, preventDefault() {}, stopPropagation() {} }, i);
    }, id);
    await ctx(ids.b);
    await until(() => vxShown('recording-context-menu'), 'the recording menu did not open');
    await page.click(ft(ids.b));
    await until(() => !vxShown('recording-context-menu') && document.getElementById('text-menu'), 'the recording menu stayed open over the feature menu');
    await page.evaluate(() => closeTextMenu());
    await ctx(ids.b);
    await until(() => vxShown('recording-context-menu'), 'the recording menu did not open again');
    await page.click(st(ids.b));
    await until(() => !vxShown('recording-context-menu'), 'the recording menu stayed open after the status\'s action');
    // a recording whose results were deleted: asked first, «Отмена» queues nothing
    const before = sent.filter(b => b.retry).length;
    await page.click(st(ids.c));
    await until(s => document.querySelector(`${s} button[data-a="no"]`), '«Распознать» of a cleared recording did not ask', 5000, dialog);
    await page.click(`${dialog} button[data-a="no"]`);
    await sleep(300);
    expect(sent.filter(b => b.retry).length === before, '«Распознать» of a cleared recording queued it without asking');
    // Tab: the buttons of the current row only
    await page.evaluate(id => { LT.cur = id; ltPaintPick(); document.getElementById('lt-scroll').focus(); }, ids.a);
    const tabs = await page.evaluate(id => {
      const all = [...document.querySelectorAll('#lt-body [data-mid] button')].filter(b => b.tabIndex >= 0);
      return { n: all.length, rows: new Set(all.map(b => b.closest('[data-mid]').dataset.mid)).size, mine: all.every(b => b.closest('[data-mid]').dataset.mid === String(id)) };
    }, ids.a);
    expect(tabs.n > 0 && tabs.rows === 1 && tabs.mine, `Tab stops at the buttons of many rows: ${JSON.stringify(tabs)}`);
    await page.keyboard.press('Tab');
    await until(id => document.activeElement?.closest('[data-mid]')?.dataset.mid === String(id), 'Tab from the table did not reach the current row', 2000, ids.a);
    // the ring inside the button: the cell (overflow hidden) cut the one drawn outside
    await page.focus(ft(ids.a));
    await page.keyboard.press('Shift+Tab');
    await page.keyboard.press('Tab');
    const ring = await page.evaluate(s => { const e = document.querySelector(s); return e.matches(':focus-visible') ? getComputedStyle(e).outlineOffset : 'no focus'; }, ft(ids.a));
    expect(ring === '-2px', `the ring of the feature cell is drawn outside: ${ring}`);
    // Enter on «Распознать»: the list is read again and drawn, the focus stays in the table and ↓ moves the row
    await page.focus(st(ids.a));
    await page.keyboard.press('Enter');
    await until(() => document.getElementById('toast')?.textContent.includes(t('ltQueuedN').split(':')[0]), '«Распознать» said nothing');
    await sleep(200);
    const where = await page.evaluate(() => [document.activeElement?.tagName, document.activeElement?.id, !!document.activeElement?.closest('#lt-scroll')]);
    expect(where[2], `the focus fell out of the table after «Распознать»: ${where}`);
    const cur0 = await page.evaluate(() => LT.cur);
    await page.keyboard.press('ArrowDown');
    expect(await page.evaluate(() => LT.cur) !== cur0, '↓ after «Распознать» did not move the row');
  } finally {
    await page.unrouteAll({ behavior: 'ignoreErrors' });
    await page.evaluate(async () => {
      if (window.__ltFtReal) window.ltFeatureItems = window.__ltFtReal;
      if (window.__ltOpt) { const sel = document.getElementById('upload-model'); sel.querySelector('option[value="test-model"]')?.remove(); sel.value = sel.options[0]?.value || ''; }
      closeTextMenu();
      hideContextMenu();
      state.multi.clear();
      await loadMeetingsList();
    });
  }
});

// Import: «＋ Импорт ▾» in the strip on top is a split button; its ▾ is a menu with an icon at each way to add;
// Ctrl+O and files dragged over the window work from any screen, with the veil «Отпустите, чтобы добавить файлы»
await step('import menu and drop veil', async () => {
  await page.evaluate(() => switchAppView('libtable'));
  await sleep(300);
  await page.click('#strip-import-more');
  await sleep(200);
  const rows = await page.$$eval('#imp-menu .imp-menu-row', els => els.map(e => [e.dataset.imp, !!e.querySelector('.imp-menu-ic svg')]));
  expect(rows.map(r => r[0]).join() === 'files,folder,link,all' && rows.every(r => r[1]), `the import menu: ${JSON.stringify(rows)}`);
  expect(/Ctrl\+O/.test(await page.textContent('#imp-menu')), 'the menu does not name Ctrl+O');
  await page.click('#imp-menu [data-imp="link"]');
  await sleep(400);
  expect(await page.isVisible('#modal-import') && await page.evaluate(() => document.activeElement?.id) === 'url-import-input', '«Ссылка» did not open the window at the link');
  await page.evaluate(() => closeModal('import'));
  await sleep(250);
  expect(!(await page.isVisible('#btn-new-recording')), 'the old import button of the sidebar is still there');
  await page.evaluate(() => switchAppView('dashboard'));
  await sleep(300);
  await page.keyboard.press('Control+o');
  await sleep(400);
  expect(await page.isVisible('#modal-import'), 'Ctrl+O did not open the import from «Главная»');
  await page.evaluate(() => closeModal('import'));
  await sleep(250);
  await page.evaluate(() => {
    const dt = new DataTransfer();
    dt.items.add(new File(['x'], 'call.mp3', { type: 'audio/mpeg' }));
    document.body.dispatchEvent(new DragEvent('dragenter', { bubbles: true, dataTransfer: dt }));
  });
  await sleep(200);
  expect(await page.isVisible('#drop-overlay') && /Отпустите/.test(await page.textContent('#drop-overlay-title')), 'no veil while files are dragged over «Главная»');
  await page.evaluate(() => hideDropOverlay());
});

// The import window in the mode of the ▾ menu's item (asked by the user: every item opened the same window):
// «＋ Импорт» itself opens everything; each mode says what it is in the head and shows only its own fields, the
// recognition card stays; the segmented control switches the mode; a second click on ▾ closes its menu; the split
// button stands as «● Запись ▾» (same height, radius and ▾)
await step('import window modes', async () => {
  await page.evaluate(() => switchAppView('libtable'));
  await sleep(300);
  const vis = (sel) => page.evaluate(s => { const el = document.querySelector(s); return !!el && el.getClientRects().length > 0; }, sel);
  const head = () => page.textContent('#imp-title');
  await page.click('#strip-import');
  await sleep(400);
  expect(await page.isVisible('#modal-import'), '«＋ Импорт» did not open the window');
  expect(await head() === 'Импорт' && await vis('#imp-empty') && await vis('#imp-link-row') && await vis('#imp-path-row'), '«＋ Импорт» does not show everything');
  expect(await vis('#imp-sound'), '«＋ Импорт» does not show the processing');
  expect(await page.getAttribute('#imp-modes [data-imp-mode="all"]', 'aria-checked') === 'true', 'the segment «Все параметры» is not chosen');
  await page.evaluate(() => closeModal('import'));
  await sleep(250);
  const modes = { files: ['Импорт файлов', '#imp-empty'], folder: ['Импорт папки', '#imp-folder-empty'], link: ['Импорт по ссылке', '#imp-link-row'] };
  for (const [mode, [title, own]] of Object.entries(modes)) {
    await page.click('#strip-import-more');
    await sleep(200);
    await page.click(`#imp-menu [data-imp="${mode}"]`);
    await sleep(400);
    expect(await head() === title, `${mode}: the head says «${await head()}»`);
    expect(await vis(own), `${mode}: its own field is not shown`);
    for (const other of ['#imp-empty', '#imp-folder-empty', '#imp-link-row', '#imp-path-row']) {
      const shown = await vis(other);
      const want = other === own || (mode === 'folder' && other === '#imp-path-row');
      expect(shown === want, `${mode}: ${other} is ${shown ? 'shown' : 'hidden'}`);
    }
    expect(await vis('#upload-model') && await vis('#upload-language') && await vis('#upload-speakers'), `${mode}: the recognition card is not whole`);
    expect(await page.getAttribute(`#imp-modes [data-imp-mode="${mode}"]`, 'aria-checked') === 'true', `${mode}: its segment is not chosen`);
    if (mode === 'link') {
      expect(await page.evaluate(() => document.activeElement?.id) === 'url-import-input', '«Ссылка»: the cursor is not in the link');
      expect(/YouTube/.test(await page.textContent('#modal-import .imp-link-lead')), '«Ссылка»: no hint of what a link can be');
    }
    await page.evaluate(() => closeModal('import'));
    await sleep(250);
  }
  // the segmented control switches the mode inside the window
  await page.evaluate(() => openImportDialog({ mode: 'files' }));
  await sleep(300);
  await page.click('#imp-modes [data-imp-mode="link"]');
  await sleep(200);
  expect(await head() === 'Импорт по ссылке' && await vis('#imp-link-row') && !(await vis('#imp-empty')), 'the segment did not switch to the link');
  await page.click('#imp-modes [data-imp-mode="all"]');
  await sleep(200);
  expect(await head() === 'Импорт' && await vis('#imp-empty') && await vis('#imp-path-row'), 'the segment did not switch to everything');
  await page.evaluate(() => closeModal('import'));
  await sleep(250);
  // Ctrl+O: the files mode
  await page.keyboard.press('Control+o');
  await sleep(400);
  expect(await head() === 'Импорт файлов', 'Ctrl+O did not open the files mode');
  await page.evaluate(() => closeModal('import'));
  await sleep(250);
  // a second click on ▾ closes its menu
  await page.click('#strip-import-more');
  await sleep(200);
  expect(await page.isVisible('#imp-menu'), 'the ▾ did not open its menu');
  await page.click('#strip-import-more');
  await sleep(200);
  expect(!(await page.isVisible('#imp-menu')), 'a second click on ▾ left its menu open');
  // the split button as «● Запись ▾»
  const box = await page.evaluate(() => {
    const r = (s) => { const b = document.querySelector(s).getBoundingClientRect(); return { top: Math.round(b.top), h: Math.round(b.height), w: Math.round(b.width) }; };
    const rad = (s) => getComputedStyle(document.querySelector(s)).borderTopLeftRadius;
    return { imp: r('.imp-split'), rec: r('.tb-rec-wrap'), impMore: r('#strip-import-more'), recMore: r('#tb-rec-more'), ri: rad('.imp-split'), rr: rad('.tb-rec-wrap') };
  });
  expect(box.imp.h === 32 && box.rec.h === 32 && box.imp.top === box.rec.top, `the split buttons differ: ${JSON.stringify(box)}`);
  expect(box.ri === box.rr && box.impMore.w === box.recMore.w && box.impMore.h === box.recMore.h, `the ▾ parts differ: ${JSON.stringify(box)}`);
});

// «Через минуту: …» goes by itself once a recording is going on (reported by the user: it stayed)
await step('meeting question expires', async () => {
  await page.evaluate(() => switchAppView('dashboard'));
  await sleep(500);
  await page.evaluate(() => hmShowAsk({ key: 'x', title: 'Синк', s: new Date(Date.now() + 60e3), e: new Date(Date.now() + 3600e3) }));
  expect(await page.isVisible('#hm-ask'), 'the question did not show');
  await page.evaluate(() => { window._realIsRecording = isRecording; window.isRecording = () => true; updateRecordButtonState(); });
  expect(!(await page.isVisible('#hm-ask')), 'the question stays while recording');
  await page.evaluate(() => { window.isRecording = window._realIsRecording; updateRecordButtonState(); });
});

// Главная opens with its widgets rising once: the fresh numbers drawn a moment later do not start the rise
// over (reported by the user: every card jerked twice)
await step('dashboard rises once', async () => {
  await page.evaluate(() => switchAppView('home'));
  await sleep(400);
  const dips = await page.evaluate(() => new Promise(done => {
    switchAppView('dashboard');
    setTimeout(() => renderDashboard(), 150);  // as the fresh numbers do
    const seen = [];
    const t0 = performance.now();
    (function look() {
      const w = document.querySelector('#db-grid > .db-w');
      if (w) seen.push(Number(getComputedStyle(w).opacity));
      if (performance.now() - t0 < 900) requestAnimationFrame(look); else done(seen);
    })();
  }));
  let top = 0, dip = 0;
  for (const o of dips) { top = Math.max(top, o); dip = Math.max(dip, top - o); }
  expect(dip < 0.2, `a widget faded out again while rising (by ${dip.toFixed(2)})`);
});

// Captions wait for the switch as a recording starts unless asked for, and never by themselves with «Не мешать
// на встречах» (asked by the user: they loaded a model during a meeting)
// Live captions in the look of the transcript's «Чат» (stage 5): a bubble for each line, the face and the name
// once for a run of one speaker, the last line with text lit; the phrase not shown yet adds no bubble
await step('live captions as a chat', async () => {
  const rows = await page.evaluate(() => {
    switchAppView('studio');
    // «Текст по ходу речи» off (on by default): the phrase still being spoken waits as a pending bubble
    const draftBox = document.getElementById('live-draft-toggle');
    const draftWas = draftBox.checked;
    draftBox.checked = false;
    [[1, 'Начнём с плана.', 'Мария'], [2, 'Я посмотрю сроки.', 'Анна'], [3, 'И проверю оценку.', 'Анна']]
      .forEach(([id, text, who]) => liveCap.lines.set(id, { id, text, who, lang: 'ru', translation: '' }));
    liveCap.partial = 'ещё говорит';
    syncStudioCaptions();
    const out = [...document.querySelectorAll('#studio-cap-rows > .cap-row')].map(e => ({ cls: e.className, bub: !!e.querySelector('.cap-bub') }));
    liveCap.lines.clear();
    liveCap.partial = '';
    capReset();
    draftBox.checked = draftWas;
    return out;
  });
  expect(rows.length === 4 && rows.every(r => r.bub), `the lines are not bubbles: ${JSON.stringify(rows)}`);
  expect(!/cap-cont/.test(rows[1].cls) && /cap-cont/.test(rows[2].cls), 'the face and the name are not once per run');
  expect(/cap-now/.test(rows[2].cls) && /cap-pending/.test(rows[3].cls) && !/cap-now/.test(rows[3].cls), `the last line is not lit: ${rows.map(r => r.cls).join(' | ')}`);
  await page.evaluate(() => switchAppView('library'));
});

// «Текст по ходу речи» (asked by the user: the phrase being spoken flickered, jumped and changed size as it was
// replaced each second): the words it keeps stay the same nodes, the new ones come one by one, the bubble never
// shrinks, the draft becomes the final line in place, and a draft has the metrics of a final line
await step('live draft grows word by word without jumps', async () => {
  // the studio fills the languages and reads the saved choices as it opens: a language set before that was undone
  // in the middle of the phrase (the view went from «Под фразой» to the original only, and the held size with it)
  await page.evaluate(() => switchAppView('studio'));
  for (let i = 0; i < 50 && !(await page.evaluate(() => [...document.getElementById('live-translate-select').options].some(o => o.value === 'en'))); i++) await sleep(100);
  await sleep(300);
  const run = () => page.evaluate(async () => {
    const box = (id) => document.getElementById(id);
    const was = { draft: box('live-draft-toggle').checked, tr: box('live-draft-tr-toggle').checked, lang: box('live-translate-select').value, view: studio.view };
    box('live-draft-toggle').checked = true;
    box('live-draft-tr-toggle').checked = true;
    const hasEn = [...box('live-translate-select').options].some(o => o.value === 'en');
    if (hasEn) box('live-translate-select').value = 'en';
    studio.view = 'under';
    liveCap.lines.clear();
    capReset();
    const wait = (ms) => new Promise(r => setTimeout(r, ms));
    const rowEl = () => document.querySelector('#studio-cap-rows > .cap-row');
    const view = () => document.getElementById('studio-cap-rows').className.replace(' cap-has-who', '');
    const metrics = (el) => { const cs = getComputedStyle(el); return [cs.fontSize, cs.lineHeight, cs.fontWeight, cs.fontStyle].join(' '); };
    const steps = [['Сегодня мы', 'Today we'], ['Сегодня мы обсудим', 'Today we will discuss'], ['Сегодня мы обсуждаем план', 'Today we discuss the plan']];
    const out = { firstAfterSet: [], sizes: [], same: true, row: true, text: [], tr: [] };
    let first = null, row = null, draftMetrics = '', trFirst = null;
    for (const [text, tr] of steps) {
      liveCap.partial = text;
      liveCap.partialTranslation = tr;
      syncStudioCaptions();
      out.firstAfterSet.push(rowEl().querySelectorAll('.cap-orig .cap-w').length);
      for (let i = 0; i < 40 && rowEl().querySelector('.cap-orig').textContent.trim() !== text; i++) {
        await wait(50);
        const r = rowEl().querySelector('.cap-bub').getBoundingClientRect();
        out.sizes.push([r.width, r.height, view()]);
      }
      const el = rowEl();
      const r = el.querySelector('.cap-bub').getBoundingClientRect();
      out.sizes.push([r.width, r.height, view()]);
      const w0 = el.querySelector('.cap-orig .cap-w');
      first = first || w0;
      out.same = out.same && w0 === first;
      row = row || el;
      out.row = out.row && el === row;
      if (hasEn) { const t0 = el.querySelector('.cap-tr .cap-w'); trFirst = trFirst || t0; out.same = out.same && t0 === trFirst; }
      out.text.push(el.querySelector('.cap-orig').textContent.trim());
      draftMetrics = metrics(el.querySelector('.cap-o'));
    }
    // final: the line comes and the phrase ends
    liveCap.lines.set(1, { id: 1, text: 'Сегодня мы обсуждаем план.', lang: 'ru', translation: hasEn ? 'Today we discuss the plan.' : '' });
    liveCap.partial = '';
    liveCap.partialTranslation = '';
    syncStudioCaptions();
    const fin = rowEl();
    const r = fin.querySelector('.cap-bub').getBoundingClientRect();
    out.sizes.push([r.width, r.height, view()]);
    out.finalSame = fin === row && document.querySelectorAll('#studio-cap-rows > .cap-row').length === 1 && !fin.classList.contains('cap-draft');
    out.finalFirst = fin.querySelector('.cap-orig .cap-w') === first;
    out.finalText = fin.querySelector('.cap-orig').textContent.trim();
    out.metrics = [draftMetrics, metrics(fin.querySelector('.cap-o'))];
    // with motion reduced the words come at once (the stable start still kept)
    liveCap.lines.clear();
    capReset();
    liveCap.partial = 'Один два три четыре';
    syncStudioCaptions();
    out.calm = rowEl().querySelectorAll('.cap-orig .cap-w').length;
    liveCap.partial = '';
    capReset();
    box('live-draft-toggle').checked = was.draft;
    box('live-draft-tr-toggle').checked = was.tr;
    box('live-translate-select').value = was.lang;
    studio.view = was.view;
    return out;
  });
  const out = await run();
  expect(JSON.stringify(out.firstAfterSet) === '[1,3,4]', `the new words did not come one by one: ${JSON.stringify(out.firstAfterSet)}`);
  expect(out.text.join('|') === 'Сегодня мы|Сегодня мы обсудим|Сегодня мы обсуждаем план', `the draft text: ${out.text.join('|')}`);
  expect(out.same && out.row, 'the words kept by an update are new nodes, or the draft row was replaced');
  expect(out.finalSame && out.finalFirst && out.finalText === 'Сегодня мы обсуждаем план.', `the final line is not the draft in place: ${JSON.stringify(out)}`);
  // a change of the view lets the held size go by design (capReleaseSizes): it is not expected here
  expect(out.sizes.every(s => s[2] === out.sizes[0][2]), `the view changed during the phrase: ${JSON.stringify(out.sizes)}`);
  const shrunk = out.sizes.findIndex((s, i) => i && (s[0] < out.sizes[i - 1][0] - 0.5 || s[1] < out.sizes[i - 1][1] - 0.5));
  expect(shrunk < 0, `the bubble shrank: ${JSON.stringify(out.sizes)}`);
  expect(out.metrics[0] === out.metrics[1], `a draft and a final line differ in size: ${out.metrics.join(' / ')}`);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  try {
    const calm = await run();
    expect(calm.calm === 4 && JSON.stringify(calm.firstAfterSet) === '[2,3,4]', `with motion reduced the words still wait: ${JSON.stringify(calm)}`);
  } finally { await page.emulateMedia({ reducedMotion: null }); }
  await page.evaluate(() => { liveCap.lines.clear(); capReset(); syncStudioCaptions(); switchAppView('library'); });
});

// Two hours of captions: the page keeps the last 300 lines (found in review: thousands, all sorted at each
// update), the document shows 150, the text let go stays for «Спросить» of a restarted session
await step('captions keep the last lines', async () => {
  const got = await page.evaluate(() => {
    liveCap.lines.clear();
    capReset();
    for (let id = 1; id <= 420; id++) liveCap.lines.set(id, { id, text: `Строка ${id}`, lang: 'ru', translation: '', at: id });
    syncStudioCaptions();
    const out = { kept: liveCap.lines.size, first: Math.min(...liveCap.lines.keys()), rows: document.querySelectorAll('#studio-cap-rows > .cap-row').length,
      gone: (liveCap.gone || []).length, goneFirst: ((liveCap.gone || [])[0] || {}).text };
    liveCap.lines.clear();
    liveCap.gone = [];
    capReset();
    syncStudioCaptions();
    return out;
  });
  expect(got.kept === 300 && got.first === 121 && got.rows === 150, `the lines kept: ${JSON.stringify(got)}`);
  expect(got.gone === 120 && got.goneFirst === 'Строка 1', `the text let go is lost: ${JSON.stringify(got)}`);
});

await step('captions do not start by themselves', async () => {
  // «Не мешать на встречах» holds them on a meeting only: a voice note recorded by hand starts with them
  const held = await page.evaluate(() => [
    captionsHeldAtStart({}, false),
    captionsHeldAtStart({ live_captions_auto: 'true', analysis_after_meetings: 'true' }, true),
    captionsHeldAtStart({ live_captions_auto: 'true', analysis_after_meetings: 'true' }, false),
    captionsHeldAtStart({ live_captions_auto: 'true', analysis_after_meetings: 'false' }, true),
    captionsHeldAtStart({ live_captions_auto: 'false', analysis_after_meetings: 'false' }, false),
  ]);
  expect(JSON.stringify(held) === '[true,true,false,false,true]', `the captions rule: ${held}`);
  await page.evaluate(() => openModal('settings', 'recording'));
  // the form is filled from the server (settings.js fillSystemInfo): read once it has been
  await until(() => !!(state.system && state.system.settings), 'the settings did not load', 8000);
  expect(!(await page.isChecked('#set-live-captions-auto')), 'captions are on by default');
  await page.evaluate(() => closeModal('settings'));
});

// The studio's row (asked by the user: the tabs and the captions' choices were two rows of the same buttons): the
// tabs and four chips of one height on one centre line; «Субтитры» switches, the language comes from a menu, the
// models and the gear open their popovers, Esc and a second click close them
await step('studio captions row', async () => {
  await page.evaluate(() => switchAppView('studio'));
  await sleep(600);  // the studio reads the saved choices of the captions as it opens
  await page.evaluate(() => {
    document.getElementById('live-captions-toggle').checked = false;
    document.getElementById('live-translate-select').value = '';
    studioConfigure();
  });
  await sleep(300);
  const boxes = await page.evaluate(() => ['st-cap-pill', 'st-tr-pill', 'st-models-pill', 'st-cap-more-btn'].map(id => {
    const r = document.getElementById(id).getBoundingClientRect();
    return [Math.round(r.height), Math.round(r.top + r.height / 2)];
  }));
  expect(boxes.every(b => b[0] === boxes[0][0] && Math.abs(b[1] - boxes[0][1]) <= 1), `the chips are not in line: ${JSON.stringify(boxes)}`);
  expect(await page.evaluate(() => document.querySelectorAll('#st-tab-text, #st-tab-notes, #st-tab-ask').length === 3
    && !document.querySelector('.st-cap-bar:not(.st-focus-bar)')), 'the tabs are missing or the old row of the captions is back');
  await page.click('#st-cap-pill');
  expect(await page.evaluate(() => document.getElementById('live-captions-toggle').checked
    && document.getElementById('st-cap-pill').getAttribute('aria-checked') === 'true'), '«Субтитры» did not turn the captions on');
  await page.click('#st-tr-pill');
  let item = -1;
  for (let i = 0; i < 20 && item < 0; i++) {
    await sleep(100);
    item = await page.evaluate(() => [...document.querySelectorAll('#text-menu button[data-i]')]
      .findIndex(b => b.textContent.trim() === langName('en')));
  }
  expect(item >= 0, 'the language menu did not open');
  expect(await page.evaluate(() => document.querySelector('#text-menu button[data-i]').textContent.trim() === t('liveNoTranslation')),
    '«Без перевода» is not first');
  await page.evaluate((i) => document.querySelectorAll('#text-menu button[data-i]')[i].click(), item);
  await sleep(200);
  expect(await page.evaluate(() => document.getElementById('live-translate-select').value === 'en'
    && document.getElementById('st-tr-pill-label').textContent === langName('en')), 'the language was not chosen');
  await page.click('#st-models-pill');
  await sleep(200);
  expect(await page.isVisible('#st-models-pop') && await page.isVisible('#studio-cap-model') && await page.isVisible('#studio-tr-model'),
    'the models popover did not open with its lists');
  await page.click('#st-models-pill');
  await sleep(200);
  expect(!(await page.isVisible('#st-models-pop')), 'a second click did not close the models popover');
  await page.click('#st-cap-more-btn');
  await sleep(200);
  expect(await page.isVisible('#studio-speech') && await page.isVisible('#live-draft-toggle'), 'the gear did not open its settings');
  await page.keyboard.press('Escape');
  await sleep(200);
  expect(!(await page.isVisible('#st-cap-more')), 'Esc did not close the gear');
  await page.evaluate(() => {
    document.getElementById('live-captions-toggle').checked = false;
    studioToggleCaptions(false);
    document.getElementById('live-translate-select').value = '';
    studioConfigure();
    switchAppView('library');
  });
});

// The studio's choices stay (asked by the user): «Субтитры», the language, «Качество / Скорость» and the models of the
// popover are settings on the server, chosen before a recording too; a reload on an empty localStorage (another
// port) shows them again, and Settings shows the same values
await step('studio choices kept', async () => {
  await page.route('**/api/live/models', r => r.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ installed: ['qwen3:8b', 'gemma4:e2b'], quality: 'qwen3:8b', fast: 'gemma4:e2b', auto: { quality: 'qwen3:8b', fast: 'gemma4:e2b' } }) }));
  const parakeet = () => { state.onnxInstalled = ['parakeet-v3']; };  // no model is downloaded in the test data
  await page.evaluate(() => switchAppView('studio'));
  await sleep(600);
  await page.evaluate(parakeet);
  // the studio fills the languages and reads the saved choices as it opens: setting the language before that is done
  // was undone by it (CI: the translation model list stayed hidden)
  for (let i = 0; i < 50 && !(await page.evaluate(() => [...document.getElementById('live-translate-select').options].some(o => o.value === 'en'))); i++) await sleep(100);
  await sleep(300);
  if (!(await page.evaluate(() => document.getElementById('live-captions-toggle').checked))) await page.click('#st-cap-pill');
  await page.evaluate(() => {
    document.getElementById('live-translate-select').value = 'en';
    studioConfigure();
    studioSetSpeed('fast');
    studioTranslateModelsChanged();
  });
  const openModels = async () => {
    if (!(await page.isVisible('#st-models-pop'))) await page.click('#st-models-pill');
    await sleep(200);
  };
  await openModels();
  let ready = false;
  for (let i = 0; i < 30 && !ready; i++) {
    await sleep(100);
    ready = await page.evaluate(() => [...document.getElementById('studio-tr-model').options].some(o => o.value === 'gemma4:e2b'));
  }
  expect(ready, 'the translation models are not listed');
  expect(await page.evaluate(() => !document.getElementById('studio-cap-model').disabled && !document.getElementById('studio-tr-model').disabled),
    'the model lists are locked before a recording');
  // the popover is opened right before each choice: a re-render of the studio may close it in between (CI timed
  // out «waiting for element to be visible» here)
  const choose = async (sel, value) => {
    for (let i = 0; i < 3; i++) {
      // the status poll refills the installed models from the server, which has none: put Parakeet back and draw the
      // lists at once (it was drawn only at the next tick, after the choice timed out)
      await page.evaluate(() => { state.onnxInstalled = ['parakeet-v3']; if (typeof renderStudioCapBar === 'function') renderStudioCapBar(); });
      await page.evaluate(() => {  // the translation language as the step set it: its model list shows only with one
        const sel = document.getElementById('live-translate-select');
        if (sel.value !== 'en') { sel.value = 'en'; studioConfigure(); }
      });
      await openModels();
      try { await page.selectOption(sel, value, { timeout: 2500 }); return; } catch (e) { if (i === 2) throw e; }
    }
  };
  await choose('#studio-cap-model', 'parakeet-v3');
  await choose('#studio-tr-model', 'gemma4:e2b');
  const keys = ['live_captions_auto', 'live_translate_to', 'live_speed', 'live_whisper_model', 'live_translate_model_fast', 'live_translate_model_quality'];
  const want = JSON.stringify(['true', 'en', 'fast', 'parakeet-v3', 'gemma4:e2b', '']);
  let saved = '';
  for (let i = 0; i < 30 && saved !== want; i++) {
    await sleep(100);
    saved = await page.evaluate((k) => fetch('/api/system').then(r => r.json()).then(d => JSON.stringify(k.map(x => d.settings[x] ?? null))), keys);
  }
  expect(saved === want, `the choices were not saved: ${saved}`);

  await page.evaluate(() => localStorage.clear());  // a launch on another port
  await page.reload();
  for (let i = 0; i < 30 && !(await page.evaluate(() => !!document.getElementById('first-run-wizard'))); i++) await sleep(100);
  await page.evaluate(() => { document.getElementById('first-run-wizard')?.remove(); switchAppView('studio'); });
  let shown = null;
  for (let i = 0; i < 40; i++) {
    await sleep(150);
    shown = await page.evaluate(() => ({ on: document.getElementById('live-captions-toggle').checked,
      pill: document.getElementById('st-cap-pill').getAttribute('aria-checked'),
      lang: document.getElementById('live-translate-select').value, speed: studio.speed,
      fast: document.getElementById('studio-speed-fast').classList.contains('tk-on') }));
    if (shown.on && shown.lang === 'en' && shown.fast) break;
  }
  expect(shown.on && shown.pill === 'true' && shown.lang === 'en' && shown.speed === 'fast' && shown.fast,
    `the studio did not show the saved choices after a reload: ${JSON.stringify(shown)}`);
  await openModels();
  let models = null;
  for (let i = 0; i < 30; i++) {
    await sleep(100);
    models = await page.evaluate(() => {
      state.onnxInstalled = ['parakeet-v3'];
      renderStudioCapBar();
      return [document.getElementById('studio-cap-model').value, document.getElementById('studio-tr-model').value];
    });
    if (models[0] === 'parakeet-v3' && models[1] === 'gemma4:e2b') break;
  }
  expect(models[0] === 'parakeet-v3' && models[1] === 'gemma4:e2b', `the models were not kept: ${models}`);
  if (process.env.PERSIST_SHOT) await page.locator('#st-models-pop').screenshot({ path: process.env.PERSIST_SHOT });
  await page.evaluate(() => closeStudioModelsPop());

  await page.evaluate(() => openModal('settings', 'recording'));
  // the studio's choices reach the form of Settings once saved (studio.js): waited for, not a fixed pause
  await until(() => {
    state.onnxInstalled = ['parakeet-v3'];
    renderLiveModelSelect();
    return document.getElementById('set-live-captions-auto').checked && document.getElementById('set-live-model').value === 'parakeet-v3';
  }, 'Settings did not take the choices', 5000).catch(() => {});  // the expect below says what it shows
  const inSettings = await page.evaluate(() => {
    state.onnxInstalled = ['parakeet-v3'];
    renderLiveModelSelect();
    return [document.getElementById('set-live-captions-auto').checked, document.getElementById('set-live-model').value];
  });
  expect(inSettings[0] === true && inSettings[1] === 'parakeet-v3', `Settings shows other values: ${inSettings}`);
  // Settings → the studio: the switch turned off there is off in the studio
  await page.evaluate(() => document.getElementById('set-live-captions-auto').click());  // the row may be folded
  let off = false;
  for (let i = 0; i < 30 && !off; i++) { await sleep(100); off = await page.evaluate(() => !document.getElementById('live-captions-toggle').checked); }
  expect(off, 'the switch of Settings did not reach the studio');
  await page.evaluate(() => closeModal('settings'));
  await page.evaluate(() => {
    studioSetModels({ caption_model: 'auto', translate_model: '' });
    document.getElementById('live-translate-select').value = '';
    studioConfigure();
    studioSetSpeed('quality');
    switchAppView('library');
  });
  await sleep(500);
  await page.unroute('**/api/live/models');
});

// The caption models not downloaded (asked by the user): the lists offer every model that fits the computer, the ones
// not downloaded in their own group with the size; choosing one asks, downloads (Ollama's pull) with its percent in the
// row, and the mode takes it when it is there; «Отмена» leaves the choice as it was. The mode's model missing: the line
// of the popover names it for «Быстро», the chip has an orange «!», a callout under it until ✕, its «Скачать» downloads
await step('caption models not downloaded', async () => {
  const FAST = 'hf.co/tencent/Hy-MT3-1.8B-GGUF:Q4_K_M';
  const BIG = 'hf.co/tencent/Hy-MT3-7B-GGUF:Q4_K_M';
  const fake = { installed: [BIG], pulls: [], progress: 0, done: false };
  await page.route('**/api/live/models', r => r.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ installed: fake.installed, quality: BIG, fast: fake.installed.includes('hy-mt3-1.8b') ? 'hy-mt3-1.8b' : BIG,
      auto: { quality: BIG, fast: fake.installed.includes('hy-mt3-1.8b') ? 'hy-mt3-1.8b' : BIG } }) }));
  await page.route('**/api/ollama/pull', r => { fake.pulls.push(JSON.parse(r.request().postData() || '{}').model); fake.progress = 1;
    return r.fulfill({ status: 200, contentType: 'application/json', body: '{"active": true}' }); });
  await page.route('**/api/ollama/status', async r => {
    const res = await r.fetch();
    const d = await res.json().catch(() => ({}));
    d.installed = true;
    d.pull_state = fake.done ? { active: false, model: FAST, progress: 100, logs: [] }
      : { active: fake.progress > 0, model: FAST, progress: fake.progress, logs: [] };
    d.translate_catalog = (d.translate_catalog || []).map(m => m.id === FAST && fake.done ? { ...m, installed: true, installed_as: 'hy-mt3-1.8b' } : m);
    await r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(d) });
  });
  // a settings read replaces state.system: Ollama stays «installed» in it too, or «Скачать» asks to install it
  await page.route('**/api/system', async r => {
    const res = await r.fetch();
    const d = await res.json().catch(() => ({}));
    if (d.ollama) d.ollama.installed = true;
    await r.fulfill({ status: res.status(), contentType: 'application/json', body: JSON.stringify(d) });
  });
  try {
    await page.evaluate(() => {
      state.system.ollama.installed = true;  // no question about installing Ollama
      saveUiSetting('live_translate_model_fast', '');
      switchAppView('studio');
    });
    await sleep(600);
    await page.evaluate(() => {
      document.getElementById('live-translate-select').value = 'en';
      studioConfigure();
      studioSetSpeed('fast');
      studioNeedSeen.dismissed = {};
      studioTranslateModelsChanged();
    });
    await until(() => !document.getElementById('st-need-hint').classList.contains('hidden'), 'the callout of the missing model is not shown');
    const hint = await page.evaluate(() => [document.getElementById('st-need-hint-text').textContent,
      !document.getElementById('st-models-need').classList.contains('hidden'), document.getElementById('st-models-pill').title]);
    expect(hint[0].includes('Hy-MT3 1.8B') && hint[1] && hint[2].includes('Hy-MT3 1.8B'), `the callout or the chip's mark is wrong: ${hint}`);
    await page.click('#st-need-hint .tb-rec-hint-x');
    await sleep(200);
    expect(!(await page.isVisible('#st-need-hint')) && await page.isVisible('#st-models-need'), '✕ did not hide the callout, or the mark went with it');

    await page.click('#st-models-pill');
    await until(() => [...document.getElementById('studio-tr-model').options].some(o => o.value === `dl:${'hf.co/tencent/Hy-MT3-1.8B-GGUF:Q4_K_M'}`),
      'the translation list does not offer the 1.8B not downloaded');
    const listed = await page.evaluate((id) => {
      const o = [...document.getElementById('studio-tr-model').options].find(x => x.value === `dl:${id}`);
      return [o.textContent, o.parentElement.label, document.getElementById('st-tr-offer-text').textContent,
        !document.getElementById('st-tr-offer').classList.contains('hidden'), t('capDlGroup'), t('studioSpeedFast')];
    }, FAST);
    expect(listed[0].includes('Hy-MT3 1.8B') && /1[,.]3/.test(listed[0]) && listed[1] === listed[4], `the 1.8B is listed without its size or group: ${listed}`);
    expect(listed[3] && listed[2].includes(listed[5]) && listed[2].includes('Hy-MT3 1.8B'), `the offer line does not name the model of «Быстро»: ${listed}`);

    // cancelled: the choice stays, nothing is downloaded
    await page.selectOption('#studio-tr-model', `dl:${FAST}`);
    await until(() => !!document.querySelector('.vx-dlg-foot button[data-a="yes"]'), 'choosing a model not downloaded asked nothing');
    const ask = await page.evaluate(() => [document.querySelector('.vx-dlg').textContent, t('studioSpeedFast')]);
    expect(ask[0].includes('Hy-MT3 1.8B') && ask[0].includes(ask[1]), `the question does not name the model and the mode: ${ask[0]}`);
    await page.click('.vx-dlg-foot button[data-a="no"]');
    await until(() => document.getElementById('studio-tr-model').value === '', 'cancel did not restore the choice');
    expect(fake.pulls.length === 0, 'cancel started a download');

    // confirmed: the pull, the percent in the row, then the mode takes the model
    if (!(await page.isVisible('#st-models-pop'))) await page.click('#st-models-pill');
    await page.selectOption('#studio-tr-model', `dl:${FAST}`);
    await until(() => !!document.querySelector('.vx-dlg-foot button[data-a="yes"]'), 'the question did not come again');
    await page.click('.vx-dlg-foot button[data-a="yes"]');
    for (let i = 0; i < 80 && !fake.pulls.length; i++) await sleep(100);
    expect(fake.pulls[0] === FAST, `the pull was not asked for the 1.8B: ${fake.pulls}`);
    // a status read older than the download (the settings' /api/system) says «not downloading» for a moment: the
    // choice waits for the download, it is not dropped (it was: the model would never have become the mode's)
    await until(() => capDl.pending.length === 1, 'the chosen download is not followed');
    const kept = await page.evaluate(() => {
      updateOllamaUI({ ...(state.system.ollama || {}), pull_state: { active: false, progress: 0, logs: [] } });
      capDlTick();
      return capDl.pending.map(p => p.key).join();
    });
    expect(kept === 'live_translate_model_fast', `a stale status read dropped the chosen download: «${kept}»`);
    fake.progress = 37;
    let row = null;
    for (let i = 0; i < 50 && !(row && row[0] === '37%' && row[1] === `dl:${FAST}`); i++) {
      await sleep(150);
      // the popover may be closed by a redraw of the studio meanwhile: the row is read with it open
      row = await page.evaluate(() => {
        if (document.getElementById('st-models-pop').classList.contains('hidden')) toggleStudioModelsPop();
        return [document.getElementById('st-tr-model-state').textContent, document.getElementById('studio-tr-model').value,
          JSON.stringify(capDl.pending.map(p => [p.key, p.id, p.pct])), JSON.stringify(state.ollamaPullState || {})];
      });
    }
    expect(row[0] === '37%' && row[1] === `dl:${FAST}`, `the row does not show the download: ${row}`);
    const slots = await page.evaluate(() => ['st-cap-model-gb', 'st-tr-model-gb', 'st-tr-offer-gb'].map(id => {
      const r = document.getElementById(id).getBoundingClientRect(); return [Math.round(r.left), Math.round(r.right)]; }));
    expect(slots.every(s => s[0] === slots[0][0] && s[1] === slots[0][1]), `the size slots moved: ${JSON.stringify(slots)}`);
    if (shots) await page.locator('#st-models-pop').screenshot({ path: `${shots}/capmodels-download.png` });
    fake.installed = [BIG, 'hy-mt3-1.8b'];
    fake.done = true;
    let saved = '';
    for (let i = 0; i < 60 && saved !== 'hy-mt3-1.8b'; i++) {
      await sleep(150);
      saved = await page.evaluate(() => fetch('/api/system').then(r => r.json()).then(d => d.settings.live_translate_model_fast || ''));
    }
    expect(saved === 'hy-mt3-1.8b', `the downloaded model did not become the choice of «Быстро»: «${saved}»`);

    // the callout's «Скачать» downloads the mode's model
    fake.installed = [BIG];
    fake.done = false;
    fake.progress = 0;
    await page.evaluate(() => { closeStudioModelsPop(); state.system.ollama.installed = true; saveUiSetting('live_translate_model_fast', ''); studioNeedSeen.dismissed = {}; studioTranslateModelsChanged(); });
    await until(() => !document.getElementById('st-need-hint').classList.contains('hidden'), 'the callout did not come back');
    await page.click('#st-need-hint .st-attn-btn');
    for (let i = 0; i < 80 && fake.pulls.length < 2; i++) await sleep(100);
    expect(fake.pulls.length === 2 && fake.pulls[1] === FAST && !(await page.isVisible('#st-need-hint')), `the callout's «Скачать» did not download: ${fake.pulls}`);
    fake.done = true;
    await sleep(1500);
  } finally {
    await page.unroute('**/api/ollama/pull');
    await page.unroute('**/api/ollama/status');
    await page.unroute('**/api/live/models');
    await page.unroute('**/api/system');
    await page.evaluate(() => {
      closeStudioModelsPop();
      saveUiSetting('live_translate_model_fast', '');
      document.getElementById('live-translate-select').value = '';
      studioConfigure();
      studioSetSpeed('quality');
      studioTranslateModelsChanged();
      switchAppView('library');
    });
    await sleep(300);
  }
});

// An online meeting of the calendar is recorded only once its call holds the microphone (reported by the user: the
// computer woke from sleep at the time of a meeting nobody joined and the recording started by the clock)
await step('an online meeting waits for its call', async () => {
  const mic = { app: null };
  await page.route('**/api/calls/status', r => r.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ supported: true, active: false, running: true, meeting_app: mic.app, mic_now: mic.app ? ['ms-teams.exe'] : [] }) }));
  await page.evaluate(() => {
    window.__hmSaved = { q: shellQuickRecord, rec: isRecording, load: hmLoadEvents, st: hmMeetingState, note: autoRecordNotice,
      events: home.events, started: new Set(home.started), warned: new Set(home.warned) };
    window.__hmRec = { starts: 0, on: false };
    shellQuickRecord = async () => { window.__hmRec.starts++; window.__hmRec.on = !window.__hmRec.on; };
    isRecording = () => window.__hmRec.on;
    hmLoadEvents = async () => {};
    hmMeetingState = () => 'on';
    autoRecordNotice = () => {};
    const now = Date.now();
    home.events = [{ key: 'scenario|call', title: 'Планёрка', online: true, attendees: [], s: new Date(now - 30e3), e: new Date(now + 30 * 60e3) }];
    hmAutoRec = null; hmJoin = null; hmCallWatch = null;
  });
  try {
    const idle = await page.evaluate(async () => { await hmJoinTick(); await hmAutoTick(); await hmJoinTick(); return [window.__hmRec.starts, hmCallWatch]; });
    expect(idle[0] === 0 && idle[1] === true, `the meeting was recorded by the clock without a call: ${idle}`);
    mic.app = 'teams';
    const first = await page.evaluate(async () => { await hmJoinTick(); return [window.__hmRec.starts, !!hmJoin]; });
    expect(first[0] === 0 && first[1], `a moment of the microphone started the recording: ${first}`);
    const joined = await page.evaluate(async () => {
      hmJoin.since -= 9e3;
      await hmJoinTick();
      return [window.__hmRec.starts, hmAutoRec && hmAutoRec.app, hmAutoRec && hmAutoRec.key];
    });
    expect(joined[0] === 1 && joined[1] === 'teams' && joined[2] === 'scenario|call', `the joined call was not recorded: ${joined}`);
    // the call goes on past the meeting's end in the calendar: the recording goes on, the next meeting does not start
    const over = await page.evaluate(async () => {
      const now = Date.now();
      home.events.push({ key: 'scenario|next', title: 'Следующая', online: true, attendees: [], s: new Date(now - 60e3), e: new Date(now + 30 * 60e3) });
      hmAutoRec.end = now - 5 * 60e3;
      await hmAutoTick(); await hmJoinTick();
      return [window.__hmRec.starts, window.__hmRec.on, !!hmAutoRec, hmAutoRec && hmAutoRec.overrun];
    });
    expect(over[0] === 1 && over[1] && over[2] && over[3], `the recording stopped at the calendar end while the call went on: ${over}`);
    // the call not seen for a while (let go, or the status unanswered): it stops by the clock
    const ended = await page.evaluate(async () => {
      hmAutoRec.seenAt = Date.now() - 60e3;
      await hmAutoTick();
      return [window.__hmRec.starts, window.__hmRec.on, !!hmAutoRec];
    });
    expect(ended[0] === 2 && !ended[1] && !ended[2], `the recording did not stop once the call let go: ${ended}`);
    // a recording made by hand during a meeting and stopped: the call still on does not start a new one
    const byHand = await page.evaluate(async () => {
      window.__hmRec.on = true; hmAutoRec = null;
      await hmJoinTick();
      window.__hmRec.on = false;
      hmJoin = { key: 'scenario|next', since: Date.now() - 60e3 };
      await hmJoinTick(); await hmJoinTick();
      return [window.__hmRec.starts, !!hmAutoRec, hmUserStopped().has('scenario|next')];
    });
    expect(byHand[0] === 2 && !byHand[1] && byHand[2], `a stop by hand was followed by a recording of the call: ${byHand}`);
  } finally {
    await page.unroute('**/api/calls/status');
    await page.evaluate(() => {
      const s = window.__hmSaved;
      shellQuickRecord = s.q; isRecording = s.rec; hmLoadEvents = s.load; hmMeetingState = s.st; autoRecordNotice = s.note;
      home.events = s.events; home.started = s.started; home.warned = s.warned;
      hmAutoRec = null; hmJoin = null; hmCallWatch = null; home.userStopped = new Set();
    });
  }
});

// A studio choice still on its way to the server is not undone by the settings read meanwhile (found in review:
// fillSystemInfo replaced the settings with the server's, the old «Качество» came back)
await step('a choice in flight survives a settings read', async () => {
  const cur = await page.evaluate(() => liveSettings().live_speed || 'quality');
  const other = cur === 'fast' ? 'quality' : 'fast';
  let release, held = 0, passed = 0;
  const gate = new Promise(r => { release = r; });
  await page.route('**/api/settings', async route => {
    if (route.request().method() === 'POST' && /live_speed/.test(route.request().postData() || '')) { held++; await gate; }
    await route.continue().catch(() => {});  // the held one may be reported handled already: it reaches the server all the same
    passed++;
  });
  try {
    await page.evaluate(s => studioSetSpeed(s), other);
    for (let i = 0; i < 30 && !held; i++) await sleep(100);
    expect(held === 1, 'the save was not held');
    await page.evaluate(() => fillSystemInfo());
    const mid = await page.evaluate(() => [liveSettings().live_speed, studio.speed]);
    expect(mid.every(v => v === other), `the settings read put the old choice back: ${mid}`);
  } finally {
    release();
    for (let i = 0; i < 30 && passed < held; i++) await sleep(100);
    await page.unroute('**/api/settings');
  }
  let saved = '';
  for (let i = 0; i < 30 && saved !== other; i++) {
    await sleep(100);
    saved = await page.evaluate(() => fetch('/api/system').then(r => r.json()).then(d => d.settings.live_speed));
  }
  expect(saved === other, `the choice did not reach the server: ${saved}`);
  await page.evaluate(() => fillSystemInfo());
  expect(await page.evaluate(() => liveSettings().live_speed) === other, 'a later read lost the choice');
  await page.evaluate(s => studioSetSpeed(s), cur);
});

// The dashboard: the first page, its widgets, «Настроить» adds and removes one, a period changes the numbers
await step('dashboard', async () => {
  await page.evaluate(() => { resetDashboard(); switchAppView('dashboard'); });  // the default layout, whatever was arranged before
  await sleep(1200);
  expect(await page.isVisible('#dashboard-view'), 'the dashboard did not open');
  expect(await page.locator('#db-grid .db-w').count() >= 8, 'the widgets are missing');
  // «Статистика»: its tiles; «Показатели» turns one on, keeps the list where it was scrolled, says the limit at 8
  expect(await page.locator('#db-grid .db-kts .db-kt').count() >= 2, 'no tiles in «Статистика»');
  await page.click('#db-grid .db-kc-btn');
  await sleep(200);
  expect(await page.isVisible('#db-grid .db-kc'), '«Показатели» did not open');
  const kpi0 = await page.evaluate(() => dbPrefs().kpis.length);
  await page.evaluate(() => { const l = document.querySelector('#db-grid .kc-list'); l.scrollTop = 60; });
  await page.click('#db-grid .kc-row:not(.on) .kc-cb >> nth=0');
  await sleep(200);
  expect(await page.evaluate(() => dbPrefs().kpis.length) === kpi0 + 1, 'a metric was not turned on');
  expect(await page.locator('#db-grid .db-kts .db-kt').count() === kpi0 + 1, 'its tile did not come');
  expect(await page.evaluate(() => document.querySelector('#db-grid .kc-list').scrollTop) > 0, 'the list jumped to its top');
  await page.evaluate(() => dbSave({ kpis: Object.keys(DB_KPI).slice(0, 8) }));
  await page.evaluate(() => dbKpiRedraw());
  expect(await page.isVisible('#db-grid .kc-lim'), 'no note at 8 of 8');
  await page.click('#db-grid .kc-row.full .kc-cb >> nth=0', { force: true });
  expect(await page.evaluate(() => document.querySelector('#db-grid .kc-lim').classList.contains('hit')), 'the note did not flash');
  expect(await page.evaluate(() => dbPrefs().kpis.length) === 8, 'a ninth metric was turned on');
  await page.click('#db-grid .kc-f .tk-btn >> nth=0');  // «По умолчанию»
  await page.click('#db-grid .kc-f .tk-btn-primary');
  // the look of a chart, kept, and the page stays where it is
  const scroll0 = await page.evaluate(() => { const g = document.getElementById('db-grid'); g.scrollTop = 120; return g.scrollTop; });
  await page.click('#db-grid .db-w-time .db-chsw button >> nth=2');
  await sleep(200);
  expect(await page.evaluate(() => dbPrefs().charts.time) === 'ring', 'the look of «Время во встречах» was not kept');
  expect(await page.evaluate(() => document.getElementById('db-grid').scrollTop) === scroll0, 'the switch moved the page');
  await page.evaluate(() => dbSave({ charts: {} }));
  await page.click('#db-edit-btn');
  await sleep(200);
  const before = await page.locator('#db-grid .db-w').count();
  await page.click('#db-grid .db-w .db-x >> nth=0');
  expect(await page.locator('#db-grid .db-w').count() === before - 1, 'a widget was not removed');
  await page.click('#db-drawer .db-lib-add >> nth=0');
  expect(await page.locator('#db-grid .db-w').count() === before, 'a widget was not added');
  await page.click('#db-drawer button:has-text("Сбросить")');
  // dragged, a widget lifts and a slot of its size shows where it lands, live; the drop keeps that order
  const ids = () => page.evaluate(() => dbPrefs().layout.map(w => w.id));
  const order0 = await ids();
  const box = async k => page.locator('#db-grid > .db-w').nth(k).boundingBox();
  const toTop = async () => {  // «Добавить» scrolled to the new widget, smoothly: wait until the grid is back at its top
    for (let k = 0, still = 0; k < 40 && still < 3; k++) {
      still = (await page.evaluate(() => { const g = document.getElementById('db-grid'); const was = g.scrollTop; g.scrollTop = 0; return was === 0; })) ? still + 1 : 0;
      await sleep(100);
    }
  };
  await toTop();
  const a = await box(0), b = await box(2);
  await page.mouse.move(a.x + 30, a.y + 12);
  await page.mouse.down();
  await page.mouse.move(a.x + 40, a.y + 30, { steps: 3 });
  await page.mouse.move(b.x + b.width - 20, b.y + b.height / 2, { steps: 12 });
  await sleep(300);
  expect(await page.locator('#db-grid > .db-slot').count() === 1, 'no slot while dragging');
  expect(await page.evaluate(() => [...document.querySelectorAll('#db-grid > .db-w:not(.db-lifted), #db-grid > .db-slot')]
    .findIndex(x => x.classList.contains('db-slot'))) === 2, 'the slot did not move to the third place');
  if (process.env.SHOTS) await page.screenshot({ path: `${process.env.SHOTS}/db-drag.png` });
  await page.mouse.up();
  await sleep(400);
  const order1 = await ids();
  expect(order1[2] === order0[0] && order1[0] === order0[1] && order1[1] === order0[2], `the drop did not keep the slot's place: ${order1.slice(0, 3)}`);
  expect(await page.locator('#db-grid > .db-slot, #db-grid > .db-lifted').count() === 0, 'the slot stayed after the drop');
  // Esc while dragging puts it back
  await toTop();
  const c = await box(0);
  await page.mouse.move(c.x + 30, c.y + 12);
  await page.mouse.down();
  await page.mouse.move(c.x + 300, c.y + 200, { steps: 10 });
  await page.keyboard.press('Escape');
  await page.mouse.up();
  await sleep(300);
  expect(JSON.stringify(await ids()) === JSON.stringify(order1), 'Esc did not cancel the drag');
  expect(await page.isVisible('#dashboard-view'), 'Esc while dragging left the dashboard');
  await page.click('#db-drawer button:has-text("Сбросить")');
  await page.click('#db-edit-btn');
  await page.click('#db-periods button >> nth=1');
  await until(() => DB.data && DB.data.period === 'month', 'the month did not come');
  expect(await page.evaluate(() => DB.data && DB.data.period === 'month' && document.querySelector('#db-periods button[aria-checked="true"]').textContent === 'Месяц'), 'the period did not change');
  await page.click('#db-periods button >> nth=0');
  await sleep(300);
});

// «Обзор» of a year and of any past period (asked by the user): ‹ goes back, the name says which one, «Текущий
// период» returns; the figures compared with the period before or the same days a year earlier. A year with no
// data has no time without meetings («—», found in review: 2088 h made up); «Нагрузка недели» and «Рабочий
// день» of a past period show its last week, named, not the current one (found in review)
await step('dashboard: a past year, the comparison', async () => {
  const year = new Date().getFullYear();
  const name = () => page.evaluate(() => document.querySelector('#db-nav .db-nav-name').textContent);
  await page.click('#db-periods button >> nth=3');
  await until(() => DB.data && DB.data.period === 'year', 'the year did not come');
  expect(await name() === String(year), `the current year is not named: ${await name()}`);
  expect(await page.locator('#db-nav button[data-click="dbToCurrent"]').count() === 0, '«Текущий период» on the current period');
  expect(await page.isDisabled('#db-nav button[data-click="dbShiftPeriod"] >> nth=1'), '› is open on the current period');
  expect(await page.evaluate(() => DB.data.buckets.length === 12 && DB.data.buckets[0].kind === 'month'), 'the year is not by month');
  await page.click('#db-nav button[data-click="dbShiftPeriod"] >> nth=0');
  await until(() => DB.data && DB.data.past && DB.data.start.endsWith('-01-01'), 'the year before did not come');
  expect(await name() === String(year - 1), `the year before is not named: ${await name()}`);
  expect(await page.evaluate(() => DB.data.start) === `${year - 1}-01-01`, 'not the year before');
  expect(!(await page.isDisabled('#db-nav button[data-click="dbShiftPeriod"] >> nth=1')), '› is shut on a past period');
  expect(await page.textContent('#db-nav button[data-click="dbToCurrent"]') === 'Текущий период', 'the way back is not «Текущий период»');
  // the seed has nothing in the year before: «Время без встреч» is «—» with no comparison under it
  const focus = () => page.evaluate(() => {
    const i = dbPrefs().kpis.indexOf('focus'), el = document.querySelectorAll('#db-grid .db-kts .db-kt')[i];
    return el ? [el.querySelector('.db-kt-n').textContent, el.querySelector('.db-kt-d').textContent] : null;
  });
  await until(() => document.querySelectorAll('#db-grid .db-kts .db-kt').length > 0, 'no tiles on the year before');
  expect(JSON.stringify(await focus()) === JSON.stringify(['—', '']), `the time without meetings of a year with no data: ${JSON.stringify(await focus())}`);
  // the week widgets: the last week of that year, named; nothing ahead in it
  const weeks = await page.evaluate(y => [calKey(dbWeekMonday()), calKey(dbMonday(new Date(y, 11, 31)))], year - 1);
  expect(weeks[0] === weeks[1], `not the last week of the year: ${weeks}`);
  await until(() => DB.past && DB.past.week && document.querySelector('#db-grid .db-w-load .db-week-name'), 'the week of «Нагрузка недели» is not named');
  expect(await page.evaluate(() => document.querySelector('#db-grid .db-w-load .db-week-name').textContent === dbWeekName(dbWeekMonday())), 'another week named');
  expect(await page.locator('#db-grid .db-w-load .k-plan').count() === 0, '«план» in the key of a past week');
  if (shots) await page.screenshot({ path: `${shots}/db-year-before.png` });
  // the period only redrawn (another comparison, the same week): the week is not asked again
  let asked = 0;
  const count = r => { if (/\/api\/(calendar\/range|worktime\?)/.test(r.url())) asked++; };
  page.on('request', count);
  await page.evaluate(() => dbReload());
  await sleep(500);
  page.off('request', count);
  expect(asked === 0, `the same week asked again: ${asked}`);
  await page.click('#db-nav button[data-click="dbToCurrent"]');
  await until(() => DB.data && !DB.data.past && DB.data.period === 'year', '«Текущий период» did not return');
  expect(await name() === String(year), '«Текущий период» did not name the current year');
  expect(await page.locator('#db-nav button[data-click="dbToCurrent"]').count() === 0, '«Текущий период» stayed');
  expect(await page.locator('#db-grid .db-w-load .db-week-name').count() === 0, 'the current week is named as a past one');
  // the week: «год назад» says so under the figures, «С предыдущим» back to the week before
  await page.click('#db-periods button >> nth=0');
  await until(() => DB.data && DB.data.period === 'week', 'the week did not come');
  const lines = () => page.evaluate(() => [...document.querySelectorAll('#db-grid .db-kt-d')].map(x => x.textContent).join(' | '));
  await page.click('#db-grid .db-w-kpis button[data-click="setDashCompare"] >> nth=1');
  await until(() => DB.data && DB.data.compare === 'year' && [...document.querySelectorAll('#db-grid .db-kt-d')].some(x => /год назад/.test(x.textContent)),
    'the figures are not compared with a year ago');
  expect(await page.evaluate(() => dbPrefs().compare) === 'year', 'the comparison was not kept');
  await page.click('#db-grid .db-w-kpis button[data-click="setDashCompare"] >> nth=0');
  await until(() => DB.data && DB.data.compare === 'prev', 'the comparison did not return');
  await sleep(200);
  expect(!/год назад/.test(await lines()), `still a year ago: ${await lines()}`);
  // the week before: «Нагрузка недели» of that week, named
  await page.click('#db-nav button[data-click="dbShiftPeriod"] >> nth=0');
  await until(() => DB.data && DB.data.past && DB.data.period === 'week', 'the week before did not come');
  await until(() => DB.past && DB.past.week && document.querySelector('#db-grid .db-w-load .db-week-name'), 'the week before is not named in «Нагрузка недели»');
  expect(await page.evaluate(() => DB.past.monday === DB.data.start && document.querySelector('#db-grid .db-w-load .db-week-name').textContent === dbSpanName()),
    '«Нагрузка недели» is not of the week shown');
  if (shots) await page.screenshot({ path: `${shots}/db-load-past-week.png` });
  await page.click('#db-nav button[data-click="dbToCurrent"]');
  await until(() => DB.data && !DB.data.past, 'the current week did not return');
});

// The templates editor: a click beside it asks before dropping unsaved edits, and closes at once when
// nothing changed (audit: edits were lost to a stray click)
await step('templates editor keeps edits', async () => {
  await page.evaluate(() => openTemplatesEditor());
  await sleep(300);
  await page.click('#templates-editor button[data-add]');
  await page.mouse.click(5, 5);
  await sleep(300);
  const asked = () => page.evaluate(() => [...document.querySelectorAll('[role="dialog"]')].some(d => d.id !== 'templates-editor' && /без сохранения/.test(d.textContent)));
  expect(await asked(), 'no question before dropping the edits');
  expect(await page.isVisible('#templates-editor'), 'the editor closed without asking');
  await page.keyboard.press('Escape');
  await sleep(300);
  expect(await page.isVisible('#templates-editor'), '«Отмена» in the question closed the editor');
  await page.evaluate(() => document.getElementById('templates-editor').remove());
  await page.evaluate(() => openTemplatesEditor());
  await sleep(300);
  await page.mouse.click(5, 5);
  await sleep(300);
  expect(!(await page.isVisible('#templates-editor')) && !(await asked()), 'an unchanged editor did not just close');
});

// A feature page closed while its redraw is on the way stays closed (audit: closed with Esc, it came back)
await step('feature page stays closed', async () => {
  const id = await page.evaluate(() => fetch('/api/features', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: 'Сценарий' }) }).then(r => r.json()).then(d => d.id));
  await page.evaluate(id => openFeaturePage(id), id);
  await sleep(500);
  expect(await page.isVisible('#feature-page'), 'the feature page did not open');
  await page.evaluate(() => { refreshFeaturePage(); document.getElementById('feature-page').remove(); });
  await sleep(600);
  expect(!(await page.isVisible('#feature-page')), 'the closed page came back');
  await page.evaluate(id => fetch(`/api/features/${id}`, { method: 'DELETE' }), id);
});

// The background poll of the library sends the list's ETag back and an unchanged list answers 304, not
// the whole JSON again (audit: megabytes every 30 s)
await step('library poll is cheap', async () => {
  expect(await page.evaluate(() => !!live.listEtag), 'the list came without an ETag');
  const statuses = [];
  const seen = r => { if (/\/api\/meetings$/.test(r.url())) statuses.push(r.status()); };
  page.on('response', seen);
  await page.evaluate(() => loadMeetingsList({ poll: true }));
  await page.evaluate(() => loadMeetingsList());
  await sleep(300);
  page.off('response', seen);
  expect(statuses[0] === 304 && statuses[1] === 200, `poll ${statuses[0]}, full ${statuses[1]}`);
  expect(await page.evaluate(() => state.meetings.length) > 0, 'the list is empty after the poll');
});

// A large library (audit K19): «Записи» draws its rows in parts as it is scrolled, every recording still selectable
// (Ctrl+A, the keys); the hidden list of the old sidebar is not drawn at all
await step('a large library is drawn in parts', async () => {
  const r = await page.evaluate(async () => {
    const wait = (ms) => new Promise(res => setTimeout(res, ms));
    const real = state.meetings;
    const base = real[0];
    state.meetings = [...real, ...Array.from({ length: 400 }, (_, i) => ({ ...base, id: 50000 + i, title: `Демо ${i}`,
      recorded_at: `2025-0${1 + (i % 9)}-1${i % 10} 10:00:00`, created_at: `2025-0${1 + (i % 9)}-1${i % 10} 10:00:00` }))];
    try {
      switchAppView('libtable');
      renderLibTable();
      await wait(100);
      const rows = () => document.querySelectorAll('#lt-body [data-mid]').length;
      const first = rows(), ids = LT.ids.length;
      const sidebar = document.querySelectorAll('#meetings-list [data-mid]').length;
      const order = libVisibleIds().length;
      // the keys reach a row not drawn yet
      const scroll = document.getElementById('lt-scroll');
      LT.cur = LT.ids[first - 1];
      scroll.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }));
      await wait(50);
      const next = LT.ids[first];
      const keyed = !!document.querySelector(`#lt-body [data-mid="${next}"].lt-cur`);
      scroll.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', code: 'KeyA', ctrlKey: true, bubbles: true }));
      const picked = state.multi.size;
      state.multi.clear();
      ltPaintPick();
      for (let i = 0; i < 30 && LT.rest.length; i++) { scroll.scrollTop = scroll.scrollHeight; await wait(80); }
      return { first, ids, sidebar, order, keyed, picked, all: rows(), more: !!document.getElementById('lt-more') };
    } finally {
      state.meetings = real;
      renderLibTable();
    }
  });
  expect(r.ids === r.order && r.ids > 400, `not every recording is in the table's order: ${JSON.stringify(r)}`);
  expect(r.first <= 160, `the first drawing drew ${r.first} rows`);
  expect(r.sidebar === 0, `the hidden sidebar drew ${r.sidebar} rows`);
  expect(r.keyed, 'the arrow key did not reach the next row, not drawn yet');
  expect(r.picked === r.ids, `Ctrl+A picked ${r.picked} of ${r.ids}`);
  expect(r.all === r.ids && !r.more, `scrolled to the end, ${r.all} of ${r.ids} rows drawn`);
});

// A progress event redraws only that recording's row of «Записи», not the sorted table of every recording
// (audit: each event rebuilt all rows); a change of its status still draws the whole table
await step('progress redraws one row', async () => {
  await page.evaluate(() => switchAppView('libtable'));
  await sleep(300);
  const r = await page.evaluate(async () => {
    const frame = () => new Promise(res => requestAnimationFrame(() => setTimeout(res, 0)));
    const m = state.meetings[0];
    const was = m.status;
    m.status = 'transcribing';
    m.progress = 10;
    renderLibTable();
    let full = 0;
    const real = window.renderLibTable;
    window.renderLibTable = (...a) => { full++; return real(...a); };
    handleLiveEvent({ type: 'progress', id: m.id, progress: 37, stage_text: 'x' });
    await frame();
    const row = document.querySelector(`#lt-body [data-mid="${m.id}"]`);
    const shown = row ? row.textContent.includes('37%') : false;
    const afterRow = full;
    handleLiveEvent({ type: 'progress', id: m.id, status: was, progress: 100 });
    await frame();
    window.renderLibTable = real;
    return { shown, afterRow, afterStatus: full };
  });
  expect(r.shown, 'the row does not show the new progress');
  expect(r.afterRow === 0, 'a progress event drew the whole list');
  expect(r.afterStatus === 1, 'a status change did not draw the list');
});

// The strip of the meeting («Пульт встреч»): a meeting within 15 minutes, one going on without a recording
// (its «Подключиться» joins the call), and the recording just made with its summary ready
await step('meeting strip', async () => {
  const sent = [];
  await page.route('**/api/meeting/join', r => { sent.push(r.request().postDataJSON()); r.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' }); });
  const setEvents = list => page.evaluate(list => {
    strip.events = list.map(([title, a, b]) => ({ key: `s|${title}`, title, s: new Date(Date.now() + a * 60e3), e: new Date(Date.now() + b * 60e3),
      attendees: [], online: true, join: 'https://teams.microsoft.com/l/meetup-join/19%3ameeting_s%40thread.v2/0' }));
    strip.configured = true; strip.at = Date.now(); strip.html = ''; renderStrip();
  }, list);
  const pill = () => page.textContent('#strip-pill-t');
  await setEvents([['Планёрка отдела', 4, 34]]);
  expect((await pill()).startsWith('Через'), `soon: ${await pill()}`);
  expect((await page.textContent('#strip-lead')) === 'Планёрка отдела', 'the meeting is not named');
  await setEvents([['Планёрка отдела', -6, 24]]);
  expect(await pill() === 'Идёт без записи', `going on: ${await pill()}`);
  await page.click('#strip-acts button:has-text("Подключиться")');
  await sleep(300);
  expect(sent.length === 1, 'the call was not joined');
  await page.click('#strip-acts button[aria-label^="Не записывать"]');
  expect(await pill() !== 'Идёт без записи', '«Не записывать» did not leave the meeting');
  await page.unroute('**/api/meeting/join');
  await setEvents([]);
  await page.evaluate(() => {
    const at = new Date().toISOString();
    state.meetings.unshift({ id: 9901, title: 'Созвон с подрядчиком', source: 'recording', status: 'completed', has_summary: 1, duration: 600, created_at: at, completed_at: at });
    strip.html = ''; renderStrip();
  });
  expect(await pill() === 'Итоги готовы', `ready: ${await pill()}`);
  await page.click('#strip-acts button:has-text("Скрыть")');
  expect(await pill() !== 'Итоги готовы', 'the summary was not hidden');
  await page.evaluate(() => { state.meetings = state.meetings.filter(m => m.id !== 9901); stripSeen.delete(9901); strip.at = 0; strip.html = ''; });
});

// «Назад» / «Вперёд» of the strip walk the sections visited, and are off where there is no step (asked by the user)
await step('back and forward buttons', async () => {
  await page.click('#rail-libtable'); await sleep(700);
  await page.click('#rail-tasks'); await sleep(700);
  expect(!(await page.isDisabled('#nav-back')), '«Назад» is off after two steps');
  await page.click('#nav-back'); await sleep(600);
  expect(await page.evaluate(() => state.appView) === 'libtable', '«Назад» did not go to «Записи»');
  expect(!(await page.isDisabled('#nav-fwd')), '«Вперёд» is off after a step back');
  await page.click('#nav-fwd'); await sleep(600);
  expect(await page.evaluate(() => state.appView) === 'tasks', '«Вперёд» did not come back to «Задачи»');
});

// While recording the capsule shows the way to the studio (asked by the user: it was not obvious): «Студия ›» between the
// sources and «Стоп», with the green outline while the captions are off; the time opens the studio, never stops; a hint
// under the chip once, kept closed as a setting across a reload
await step('recording capsule leads to the studio', async () => {
  const fake = () => page.evaluate(() => {
    window.__recOrig = window.__recOrig || [window.isRecording, window.shellQuickRecord]; window.__stops = 0;
    window.isRecording = () => true; window.shellQuickRecord = () => { window.__stops++; };
    document.getElementById('live-captions-toggle').checked = false;
    document.getElementById('studio-timer').textContent = '00:07'; switchAppView('home'); updateRecordButtonState(); });
  await fake();
  expect(await page.isVisible('#tb-rec-studio'), 'no «Студия» chip while recording');
  const boxes = await page.evaluate(() => ['tb-rec', 'tb-rec-studio', 'tb-rec-stop', 'tb-rec-wrap'].map(id => {
    const r = document.getElementById(id).getBoundingClientRect(); return [r.left, r.right, r.top + r.height / 2];
  }));
  expect(boxes[1][0] >= boxes[0][1] && boxes[2][0] >= boxes[1][1] && boxes[2][1] <= boxes[3][1] && Math.abs(boxes[1][2] - boxes[2][2]) < 1,
    `the chip is not between the time and «Стоп»: ${JSON.stringify(boxes)}`);
  expect(await page.evaluate(() => document.getElementById('tb-rec-studio').classList.contains('is-call')), 'captions off: the chip has no green outline');
  await page.evaluate(() => { document.getElementById('live-captions-toggle').checked = true; updateRecordButtonState(); });
  expect(await page.evaluate(() => { const c = document.getElementById('tb-rec-studio').classList; return c.contains('is-on') && !c.contains('is-call'); }),
    'captions on: the chip is not in the accent');
  await page.evaluate(() => { document.getElementById('live-captions-toggle').checked = false; updateRecordButtonState(); });
  // the hint: shown on the first recording, closed by ✕, not shown again after a reload
  expect(await page.isVisible('#tb-rec-hint'), 'no hint on the first recording');
  expect(/Субтитры и текст записи/.test(await page.textContent('#tb-rec-hint')), 'the hint says something else');
  await page.click('#tb-rec-hint .tb-rec-hint-x');
  expect(!(await page.isVisible('#tb-rec-hint')), '✕ did not close the hint');
  let seen = '';
  for (let i = 0; i < 30 && seen !== 'true'; i++) { await sleep(100); seen = await page.evaluate(() => fetch('/api/system').then(r => r.json()).then(d => d.settings.hint_studio_entry_seen)); }
  expect(seen === 'true', `the closed hint was not saved: ${seen}`);
  await page.reload();
  for (let i = 0; i < 40 && !(await page.evaluate(() => !!(state.system && state.system.settings))); i++) await sleep(100);
  for (let i = 0; i < 30 && !(await page.evaluate(() => !!document.getElementById('first-run-wizard'))); i++) await sleep(100);
  await page.evaluate(() => document.getElementById('first-run-wizard')?.remove());
  await fake();
  await sleep(200);
  expect(await page.isVisible('#tb-rec-studio') && !(await page.isVisible('#tb-rec-hint')), 'the hint came back after a reload');
  // the time opens the studio and does not stop; there the capsule keeps its width, its way to the studio inert
  const wHome = await page.evaluate(() => document.getElementById('tb-rec-wrap').getBoundingClientRect().width);
  await page.click('#tb-rec-clock');
  await sleep(300);
  const r = await page.evaluate(() => [state.appView, window.__stops, document.getElementById('tb-rec-studio').getAttribute('aria-disabled'),
    document.getElementById('tb-rec-wrap').getBoundingClientRect().width]);
  expect(r[0] === 'studio' && r[1] === 0, `the time did not open the studio alone: ${r}`);
  expect(r[2] === 'true' && Math.abs(r[3] - wHome) < 1, `in the studio the chip is not inert or the capsule changed its width: ${r} / ${wHome}`);
  await page.evaluate(() => switchAppView('libtable'));
  await page.click('#tb-rec-studio');
  await sleep(300);
  expect(await page.evaluate(() => state.appView) === 'studio', '«Студия ›» did not open the studio');
  await page.evaluate(() => { [window.isRecording, window.shellQuickRecord] = window.__recOrig; window.__recOrig = undefined;
    document.getElementById('live-captions-toggle').checked = false; updateRecordButtonState(); switchAppView('home'); });
});

// While recording, only «Стоп» of the red button stops; the time and the sources open the studio (asked by the user:
// a click on the microphone stopped the recording)
await step('recording time opens the studio', async () => {
  await page.evaluate(() => { window.__recOrig = [window.isRecording, window.shellQuickRecord]; window.__stops = 0;
    window.isRecording = () => true; window.shellQuickRecord = () => { window.__stops++; };
    document.getElementById('studio-timer').textContent = '01:23'; updateRecordButtonState(); switchAppView('home'); });
  await page.click('#tb-rec-clock');
  await sleep(300);
  let r = await page.evaluate(() => [state.appView, window.__stops]);
  expect(r[0] === 'studio' && r[1] === 0, `the time did not open the studio alone: ${r}`);
  await page.evaluate(() => { switchAppView('home'); updateRecordButtonState(); });
  await page.click('#tb-rec-dot', { force: true });
  await sleep(300);
  r = await page.evaluate(() => [state.appView, window.__stops]);
  expect(r[0] === 'studio' && r[1] === 0, `the dot stopped the recording: ${r}`);
  // in the studio the time does nothing more (inert); «Стоп», a button of its own, stops
  await page.evaluate(() => recButtonClick());
  await page.click('#tb-rec-stop');
  await sleep(200);
  expect(await page.evaluate(() => window.__stops) === 1, 'only «Стоп» must stop the recording');
  // the way to the studio from any section is the chip of the recording button; the strip no longer repeats it
  await page.evaluate(() => { switchAppView('libtable'); strip.html = ''; renderStrip(); });
  expect(!(await page.isVisible('#strip-acts button[data-click="openRecordStudio"]')), 'the strip still repeats the way to the studio');
  await page.click('#tb-rec-studio');
  await sleep(300);
  expect(await page.evaluate(() => state.appView) === 'studio', 'the «Студия» chip did not open the studio');
  await page.evaluate(() => { [window.isRecording, window.shellQuickRecord] = window.__recOrig; updateRecordButtonState(); switchAppView('home'); });
});

// Not recording, «Студия» stays in the capsule (asked by the user: no quick way to the studio without a recording): it
// opens the studio, where it is the current place, inert; the capsule keeps its width
await step('studio entry without a recording', async () => {
  await page.evaluate(() => { switchAppView('libtable'); updateRecordButtonState(); });
  expect(await page.isVisible('#tb-rec-studio'), 'no «Студия» in the capsule while not recording');
  const w0 = await page.evaluate(() => document.getElementById('tb-rec-wrap').getBoundingClientRect().width);
  await page.click('#tb-rec-studio');
  await until(() => state.appView === 'studio', '«Студия» did not open the studio without a recording');
  const r = await page.evaluate(() => [isRecording(), document.getElementById('tb-rec-studio').getAttribute('aria-current'),
    document.getElementById('tb-rec-wrap').getBoundingClientRect().width]);
  expect(!r[0] && r[1] === 'page' && Math.abs(r[2] - w0) < 1, `in the studio: recording, not current or the width moved: ${r} / ${w0}`);
  await page.evaluate(() => switchAppView('home'));
});

// «Очередь» as the island of the top strip and the load of the status bar: each opens its window next to it, Escape
// and a click outside close it
await step('queue and load windows', async () => {
  expect(await page.locator('#rail-jobs').count() === 0, 'the rail still has its «Очередь»');
  await page.evaluate(() => { state.queue = [{ id: 9902, state: 'running', kind: 'transcribe', title: 'Тест', progress: 40, position: 0 }]; renderJobsIsland(); });
  expect(await page.isVisible('#strip-island'), 'no island while a job runs');
  await page.click('#strip-island');
  await sleep(300);
  expect(await page.isVisible('#jobs-pop'), 'the queue window did not open');
  const r = await page.evaluate(() => [document.getElementById('jobs-pop').getBoundingClientRect(), document.getElementById('strip-island').getBoundingClientRect()].map(x => [x.top, x.right, x.bottom]));
  expect(r[0][0] >= r[1][2] && Math.abs(r[0][1] - r[1][1]) < 2, `the queue window is not under the island: ${JSON.stringify(r)}`);
  await page.keyboard.press('Escape');
  expect(!(await page.isVisible('#jobs-pop')), 'Escape did not close the queue window');
  await page.evaluate(() => { state.queue = []; renderJobsIsland(); clearTimeout(island.doneTimer); island.doneTimer = null; island.html = ''; document.getElementById('strip-island').classList.add('hidden'); });
  await page.click('#sb-load');
  await sleep(500);
  expect(await page.isVisible('#load-pop'), 'the load window did not open');
  expect((await page.textContent('#load-pop')).includes('CPU'), 'the load window has no processor');
  await page.mouse.click(700, 26);
  expect(!(await page.isVisible('#load-pop')), 'a click outside did not close the load window');
});

// The language and the dashboard follow the server, not only this origin's localStorage: when 8765 is
// busy the app starts on another port, whose storage is empty (audit: an English user got Russian)
await step('language from the server', async () => {
  await page.evaluate(() => fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ settings: { ui_lang: 'en', ui_dashboard: JSON.stringify({ period: 'month' }) } }) }));
  await page.evaluate(() => localStorage.clear());  // a launch on another port
  await page.reload();
  let lang = '';
  for (let i = 0; i < 40 && lang !== 'en'; i++) { await sleep(150); lang = await page.evaluate(() => state.uiLang); }
  expect(lang === 'en', 'the language of the server was not taken');
  expect(await page.evaluate(() => dbPrefs().period) === 'month', 'the dashboard layout of the server was not taken');
  // the first-run wizard of the fresh data folder opens a moment after the language: waited for, then removed
  // (removed before it opened, it covered the page for the steps after this one)
  for (let i = 0; i < 30 && !(await page.evaluate(() => !!document.getElementById('first-run-wizard'))); i++) await sleep(100);
  await page.evaluate(() => { document.getElementById('first-run-wizard')?.remove(); setUILanguage('ru'); dbSave({ period: 'week' }); });
  // the layout is saved 0.8 s after the last change: waited for, up to 5 s on a busy machine
  let kept = [];
  for (let i = 0; i < 25 && !(kept[0] === 'ru' && kept[1] === 'week'); i++) {
    await sleep(200);
    kept = await page.evaluate(() => fetch('/api/system').then(r => r.json()).then(d => [d.settings.ui_lang, JSON.parse(d.settings.ui_dashboard).period]));
  }
  expect(kept[0] === 'ru' && kept[1] === 'week', `a choice on the page was not kept on the server: ${kept}`);
});

// The strip: a failed calendar answer is not asked again at once (its redraw asked again: a request loop)
await step('strip back-off', async () => {
  let calls = 0;
  await page.route('**/api/calendar/range*', r => { calls++; return r.fulfill({ status: 404, body: '{}' }); });
  await page.evaluate(() => { strip.at = 0; strip.failAt = 0; renderStrip(); });
  await sleep(2000);
  await page.evaluate(() => { renderStrip(); renderStrip(); });
  await sleep(300);
  await page.unroute('**/api/calendar/range*');
  expect(calls >= 1 && calls <= 2, `the strip asked the calendar ${calls} times in 2 s after a failure`);
  await page.evaluate(() => { strip.failAt = 0; });
});

// Opening a recording, then back on the open one before the answer: the open one wins and the screen takes input
// again (the pending state of the first stayed: the text hidden and the screen inert)
await step('pending race', async () => {
  await page.evaluate(() => openMeeting(1));
  await sleep(1200);
  await page.route(/\/api\/meetings\/2$/, async r => { await new Promise(f => setTimeout(f, 1200)); await r.continue(); });
  await page.evaluate(() => { selectMeeting(2); selectMeeting(1); });
  await sleep(1300);  // the late answer for recording 2 has come
  await until(() => state.pendingMeetingId == null && !document.getElementById('workspace-content').classList.contains('rec-pending'),
    'the screen stayed pending', 5000).catch(() => {});  // the expect below says how it stayed
  await page.unroute(/\/api\/meetings\/2$/);
  const st = await page.evaluate(() => {
    const box = document.getElementById('workspace-content');
    return { pending: state.pendingMeetingId, cls: box.classList.contains('rec-pending'), inert: box.inert, id: state.activeMeeting && state.activeMeeting.id };
  });
  expect(st.pending == null && !st.cls && !st.inert && st.id === 1, `the screen stayed pending: ${JSON.stringify(st)}`);
});

// The queue's island: the ring alone when the strip tells about the only job (the queue's window is opened from
// here alone); «Готово» only after an island in sight and not after a cancel; its window closes with it
await step('queue island', async () => {
  // the only job is the recording the strip tells about: the ring alone, still opening the queue
  const r = await page.evaluate(() => {
    const m = state.meetings[0];
    state.queue = [{ id: m.id, state: 'running', kind: 'transcribe', title: m.title, progress: 30, position: 1 }];
    strip.kind = 'after'; strip.click = m.id;
    renderJobsIsland();
    const el = document.getElementById('strip-island');
    return { hidden: el.classList.contains('hidden'), cls: el.className, text: el.textContent.trim(), w: el.getBoundingClientRect().width };
  });
  expect(!r.hidden && /st-island-ring/.test(r.cls) && !r.text, 'no compact island');
  await page.evaluate(() => document.getElementById('strip-island').click());
  await sleep(300);
  expect(await page.isVisible('#jobs-pop'), 'the compact island does not open the queue');
  // the job ends: «Готово», and the window opened from the island closes with it
  await page.evaluate(() => { state.queue = []; renderJobsIsland(); });
  expect(/st-island-done/.test(await page.getAttribute('#strip-island', 'class')), 'no «Готово»');
  // «Готово» stays 2.6 s (pult.js doneTimer), then the queue is read again: up to 5 s on a slow runner
  const gone = () => {
    const shown = (id) => { const el = document.getElementById(id); return !!el && !el.classList.contains('hidden') && el.getClientRects().length > 0; };
    return !shown('strip-island') && !shown('jobs-pop');
  };
  await until(gone, 'the island or its window stayed', 5000);
  // cancelled: no «Готово»
  await page.evaluate(() => { const m = state.meetings[0]; state.queue = [{ id: m.id, state: 'running', kind: 'analysis', title: m.title, progress: 3, position: 1 }]; strip.kind = 'free'; renderJobsIsland(); islandCancelled(); renderJobsIsland(); state.queue = []; renderJobsIsland(); });
  expect(!(await page.isVisible('#strip-island')), '«Готово» after a cancel');
  // never visible: no «Готово»
  await page.evaluate(() => { state.queue = []; renderJobsIsland(); });
  expect(!(await page.isVisible('#strip-island')), '«Готово» with nothing before');
});

// «Не мешать на встречах»: the queue's window tells a meeting going on from the pause after it, the pause counts
// down; a held transcription starts now after the question «Расшифровать» asks during a meeting (reported by the
// user: «ждёт конца встречи» under a voice note with no meeting going on)
await step('queue window meeting states', async () => {
  let hold = { kind: 'meeting', reason: 'recording' };
  const ran = [];
  const json = (r, body) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/api/queue', r => json(r, [{ id: 9911, state: 'waiting', kind: 'transcribe', title: 'Заметка к планёрке', progress: 0, position: 1 },
    { id: 9912, state: 'waiting', kind: 'translate', lang: 'en', title: 'Обзор квартала', progress: 0, position: 2 }]));
  await page.route('**/api/queue/paused', r => json(r, { paused: false, meeting: true, hold }));
  await page.route('**/api/queue/*/run-now', r => { ran.push(r.request().url()); return json(r, { ok: true }); });
  try {
    await page.evaluate(() => { strip.kind = 'free'; return loadQueue(); });
    expect((await page.textContent('#strip-island')).includes('Ждут конца встречи'), 'the island does not say a meeting goes on');
    await page.click('#strip-island');
    await sleep(300);
    let sub = await page.textContent('#jobs-pop .vx-sub');
    expect(sub.startsWith('Идёт встреча'), `the window during a meeting: ${sub}`);
    // only the transcription waits for the meeting: «Начать сейчас» under it alone
    expect(await page.locator('#jobs-pop .vx-prow-go button').count() === 1, 'no «Начать сейчас» on the transcription alone');
    expect((await page.textContent('#jobs-pop .vx-prow-go button')).trim() === 'Начать сейчас', 'the button text');
    // the pause after the meeting: its time left, counting down
    hold = { kind: 'pause', reason: 'recording', until: Date.now() / 1000 + 100, left: 100 };
    await page.evaluate(() => loadQueue());
    sub = await page.textContent('#jobs-pop .vx-sub');
    expect(/^Пауза после встречи · 1:(40|39)/.test(sub), `the window during the pause: ${sub}`);
    expect(/^Пауза после встречи 1:(40|39)/.test((await page.textContent('#strip-island')).trim()), 'the island does not count the pause');
    expect(/начнётся через 1:(40|39)/.test(await page.textContent('#jobs-pop .vx-prow')), 'the item does not count the pause');
    await sleep(2100);
    sub = await page.textContent('#jobs-pop .vx-sub');
    expect(/^Пауза после встречи · 1:3\d/.test(sub), `the pause does not count down: ${sub}`);
    // «Начать сейчас»: the question first; «Отмена» starts nothing, «Да, начать сейчас» starts it
    await page.click('#jobs-pop .vx-prow-go button');
    await sleep(300);
    expect((await page.textContent('[role="dialog"] .vx-dlg')).includes('Пауза после встречи'), 'no question before the start');
    await page.click('[role="dialog"] button[data-a="no"]');
    await sleep(300);
    expect(ran.length === 0, 'started without «Да»');
    hold = { kind: 'meeting', reason: 'call' };
    await page.evaluate(() => loadQueue());
    if (!(await page.isVisible('#jobs-pop'))) await page.click('#strip-island');  // a click in the question closes it, as «Отменить всё»
    await sleep(300);
    await page.click('#jobs-pop .vx-prow-go button');
    await sleep(300);
    expect((await page.textContent('[role="dialog"] .vx-dlg')).includes('Идёт встреча'), 'the question during a meeting');
    await page.click('[role="dialog"] button[data-a="yes"]');
    await sleep(400);
    expect(ran.length === 1 && /\/api\/queue\/9911\/run-now$/.test(ran[0]), `run-now: ${ran}`);
    await page.evaluate(() => closeJobsPop());
  } finally {
    await page.unroute('**/api/queue');
    await page.unroute('**/api/queue/paused');
    await page.unroute('**/api/queue/*/run-now');
    await page.evaluate(() => loadQueue().catch(() => {}));
  }
});

// «Фоновая обработка» (app/queue_window.py): the automatic jobs wait until the computer is free or for the schedule;
// the island, the queue window and its item say which, and «Начать сейчас» lets one go after the question
await step('queue window background reason', async () => {
  let win = { kind: 'schedule', from: '19:00' };
  const ran = [];
  const json = (r, body) => r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
  await page.route('**/api/queue', r => json(r, [{ id: 9921, state: 'waiting', kind: 'transcribe', title: 'Обзор квартала', progress: 0, position: 1, window: true },
    { id: 9922, state: 'waiting', kind: 'translate', lang: 'en', title: 'Планёрка отдела', progress: 0, position: 2, window: false }]));
  await page.route('**/api/queue/paused', r => json(r, { paused: false, meeting: false, hold: {}, window: win }));
  await page.route('**/api/queue/*/run-now', r => { ran.push(r.request().url()); return json(r, { ok: true }); });
  try {
    await page.evaluate(() => { strip.kind = 'free'; return loadQueue(); });
    expect((await page.textContent('#strip-island')).includes('Ждут расписания: с 19:00'), `the island: ${await page.textContent('#strip-island')}`);
    await page.click('#strip-island');
    await sleep(300);
    const sub = await page.textContent('#jobs-pop .vx-sub');
    expect(sub.startsWith('Расшифровка и анализ ждут расписания: с 19:00'), `the window: ${sub}`);
    const rows = await page.$$eval('#jobs-pop .vx-prow .vx-val', els => els.map(e => e.textContent.trim()));
    expect(rows[0] === 'ждёт расписания: с 19:00', `the held item: ${rows}`);
    expect(rows[1] !== rows[0], `the translation does not wait for the schedule: ${rows}`);
    expect(await page.locator('#jobs-pop .vx-prow-go button').count() === 1, '«Начать сейчас» on the held item alone');
    if (process.env.SHOTS) await page.locator('#jobs-pop').screenshot({ path: `${process.env.SHOTS}/queue-when-window-schedule.png` });
    await page.click('#jobs-pop .vx-prow-go button');
    await sleep(300);
    const dlg = await page.textContent('[role="dialog"] .vx-dlg');
    expect(dlg.includes('Фоновая обработка') && dlg.includes('Ждёт расписания'), `the question: ${dlg}`);
    await page.click('[role="dialog"] button[data-a="yes"]');
    await sleep(400);
    expect(ran.length === 1 && /\/api\/queue\/9921\/run-now$/.test(ran[0]), `run-now: ${ran}`);
    win = { kind: 'idle' };
    await page.evaluate(() => loadQueue());
    expect((await page.textContent('#strip-island')).includes('Ждут свободного компьютера'), 'the island while the computer is busy');
    if (!(await page.isVisible('#jobs-pop'))) await page.click('#strip-island');
    await sleep(300);
    expect((await page.textContent('#jobs-pop .vx-prow .vx-val')).trim() === 'ждёт, пока компьютер свободен', 'the item while the computer is busy');
    if (process.env.SHOTS) await page.locator('#jobs-pop').screenshot({ path: `${process.env.SHOTS}/queue-when-window-idle.png` });
    await page.evaluate(() => closeJobsPop());
  } finally {
    await page.unroute('**/api/queue');
    await page.unroute('**/api/queue/paused');
    await page.unroute('**/api/queue/*/run-now');
    await page.evaluate(() => loadQueue().catch(() => {}));
  }
});

// «Настройки → Общие → Фоновая обработка»: the rows of the condition chosen, saved at once; its list sits where the
// other lists of the tab sit
await step('background processing settings', async () => {
  await page.evaluate(() => openModal('settings', 'general'));
  await sleep(400);
  const shown = id => page.evaluate(x => { const el = document.getElementById(x); return !!el && !el.classList.contains('hidden') && !!el.offsetParent; }, id);
  try {
    await page.selectOption('#set-queue-when', 'always');
    await sleep(200);
    expect(!(await shown('queue-load-row')) && !(await shown('queue-schedule-row')), '«Сразу» shows no condition');
    await page.selectOption('#set-queue-when', 'schedule');
    await sleep(200);
    expect(await shown('queue-schedule-row') && !(await shown('queue-load-row')), '«По расписанию» shows the schedule alone');
    await page.selectOption('#set-queue-from', '20:00');
    await page.selectOption('#set-queue-to', '07:30');
    let saved = {};
    for (let i = 0; i < 40 && !(saved.queue_when === 'schedule' && saved.queue_from === '20:00' && saved.queue_to === '07:30'); i++) {
      await sleep(150);
      saved = await page.evaluate(() => fetch('/api/system').then(r => r.json()).then(d => d.settings));
    }
    expect(saved.queue_when === 'schedule' && saved.queue_from === '20:00' && saved.queue_to === '07:30',
      `not saved: ${saved.queue_when} ${saved.queue_from} ${saved.queue_to}`);
    await page.selectOption('#set-queue-when', 'idle_or_schedule');
    await sleep(200);
    expect(await shown('queue-schedule-row') && await shown('queue-load-row'), 'either shows both conditions');
    // the list at the right edge as the other lists of the tab (measured, not by eye)
    const edges = await page.evaluate(() => ['set-queue-when', 'set-economy-for', 'set-queue-to', 'set-queue-gpu-max']
      .map(id => Math.round(document.getElementById(id).getBoundingClientRect().right)));
    expect(edges.every(x => Math.abs(x - edges[0]) <= 1), `the right edges: ${edges}`);
    // the time and the percent lists of one width, the label column of the load row not squeezed
    const w = await page.evaluate(() => ['set-queue-from', 'set-queue-to', 'set-queue-cpu-max', 'set-queue-gpu-max']
      .map(id => Math.round(document.getElementById(id).getBoundingClientRect().width)));
    expect(w.every(x => x === w[0]), `the widths: ${w}`);
    const text = await page.evaluate(() => Math.round(document.querySelector('#queue-load-row .sx-row-text').getBoundingClientRect().width));
    expect(text >= 200, `the text of the load row is squeezed to ${text}px`);
    if (process.env.SHOTS) {
      await page.evaluate(() => document.getElementById('set-queue-when').closest('.settings-card').scrollIntoView({ block: 'center' }));
      await sleep(200);
      await page.locator('#set-queue-when >> xpath=ancestor::div[contains(@class,"settings-card")]').screenshot({ path: `${process.env.SHOTS}/queue-when-settings.png` });
    }
  } finally {
    await page.selectOption('#set-queue-when', 'always').catch(() => {});
    await sleep(600);
    await page.evaluate(() => closeModal('settings')).catch(() => {});
  }
});

// Menus: one open at a time, a second press of the button closes its menu, Esc closes the menu on top only (one
// Esc closed «Нагрузка» and left the settings; «Показатели» and the drawer at once)
await step('one menu at a time', async () => {
  await page.evaluate(() => switchAppView('libtable')); await sleep(500);
  await page.click('#tb-rec-more'); await sleep(200);
  expect(await page.isVisible('#rec-menu'), 'rec menu did not open');
  await page.click('#strip-import-more'); await sleep(250);
  expect(await page.isVisible('#imp-menu'), 'import menu did not open');
  expect(!(await page.isVisible('#rec-menu')), '«● Запись ▾» stayed open with «Импорт ▾»');
  await page.click('#strip-import-more'); await sleep(250);
  expect(!(await page.isVisible('#imp-menu')), 'a second click did not close «Импорт ▾»');
  await page.click('#tb-rec-more'); await sleep(200);
  await page.click('#tb-rec-more'); await sleep(250);
  expect(!(await page.isVisible('#rec-menu')), 'a second click did not close «● Запись ▾»');
  await page.click('#tb-rec-more'); await sleep(200);
  await page.keyboard.press('Escape'); await sleep(200);
  expect(!(await page.isVisible('#rec-menu')), 'Esc did not close «● Запись ▾»');
});
await step('esc closes the top layer only', async () => {
  await page.evaluate(() => switchAppView('settings')); await sleep(600);
  const view = await page.evaluate(() => state.appView);
  await page.click('#sb-load'); await sleep(300);
  expect(await page.isVisible('#load-pop'), 'no load window');
  await page.keyboard.press('Escape'); await sleep(300);
  const after = await page.evaluate(() => state.appView);
  expect(!(await page.isVisible('#load-pop')) && after === view, `Esc: load ${await page.isVisible('#load-pop')}, view ${view} → ${after}`);
  // the recording's menus: Esc and a second click
  await page.evaluate(() => openMeeting(1)); await sleep(1200);
  await page.click('[data-click="openActiveRecordingMenu"]'); await sleep(250);
  expect(await page.isVisible('#recording-context-menu'), 'no ⋯ menu');
  await page.click('[data-click="openActiveRecordingMenu"]'); await sleep(350);
  expect(!(await page.isVisible('#recording-context-menu')), 'a second click did not close ⋯');
  await page.click('[data-click="openActiveRecordingMenu"]'); await sleep(250);
  await page.keyboard.press('Escape'); await sleep(350);
  expect(!(await page.isVisible('#recording-context-menu')), 'Esc did not close ⋯');
  // «Обзор»: «Показатели» over the drawer, one Esc each
  await page.evaluate(() => switchAppView('dashboard')); await sleep(1200);
  await page.evaluate(() => dbOpenDetail('meetings')); await sleep(600);
  await page.evaluate(() => dbKpiPanel()); await sleep(300);
  const st = () => page.evaluate(() => [DB.kpiCfg, !!DB_DETAIL.kind]);
  const s0 = await st();
  await page.keyboard.press('Escape'); await sleep(300);
  const s1 = await st();
  expect(s0[0] && s0[1] && !s1[0] && s1[1], `one Esc: ${JSON.stringify([s0, s1])}`);
  await page.keyboard.press('Escape'); await sleep(300);
  expect(!(await st())[1], 'the second Esc did not close the drawer');
  await page.evaluate(() => toggleDashEdit()); await sleep(300);
  await page.keyboard.press('Escape'); await sleep(300);
  expect(!(await page.evaluate(() => DB.edit)), 'Esc did not leave «Настроить»');
});

// The window «Фичи» (asked by the user): a drawer at the right edge over any section, opened from «Все фичи ▾» of
// «Обзор», «Фича ▾» of «Записи», the chip «Фича:» of a recording and the card «Фичи» of «Словарь»; a feature is
// made and renamed in it, Esc and a second click on its opener close it
await step('features drawer', async () => {
  const poll = async (f, what, ms = 4000) => {
    for (let t = 0; t < ms; t += 100) { if (await page.evaluate(f)) return; await sleep(100); }
    throw new Error(what);
  };
  const open = () => page.evaluate(() => featureDrawerOpen());
  await page.evaluate(() => switchAppView('dashboard')); await sleep(1200);
  await page.click('#db-feature-btn'); await sleep(250);
  await page.click('#text-menu button:has-text("Управлять фичами")');
  await poll(() => featureDrawerOpen(), '«Управлять фичами…» of «Обзор» did not open the drawer');
  await poll(() => document.getElementById('ft-drawer').getAnimations().every(a => a.playState === 'finished'), 'the drawer did not settle');
  const box = await page.evaluate(() => {
    const r = document.getElementById('ft-drawer').getBoundingClientRect(), s = document.getElementById('app-strip').getBoundingClientRect();
    return { w: Math.round(r.width), right: Math.round(window.innerWidth - r.right), top: Math.round(r.top - s.bottom), z: +getComputedStyle(document.getElementById('ft-drawer')).zIndex };
  });
  expect(box.w >= 370 && box.w <= 390 && box.right === 0 && box.top === 0 && box.z > 30 && box.z < 50, `the drawer's place: ${JSON.stringify(box)}`);
  await page.fill('#ft-dr-new', 'Окно фич');
  await page.click('#ft-dr-add');
  await poll(() => document.querySelector('#ft-dr-list .ft-dr-on')?.textContent.includes('Окно фич'), 'the new feature is not chosen in the list');
  const rows = await page.evaluate(() => [...document.querySelectorAll('#ft-dr-list .ft-dr-row')].map(r => Math.round(r.getBoundingClientRect().height)));
  expect(rows.every(h => h === 36), `rows not 36 px: ${rows}`);
  const fields = await page.evaluate(() => [...document.querySelectorAll('#ft-dr-form input.ft-dr-in')].map(i => Math.round(i.getBoundingClientRect().height)));
  expect(fields.length === 3 && fields.every(h => h === 32), `fields not 32 px: ${fields}`);
  await page.fill('#ft-dr-form [data-key="name"]', 'Окно фич 2');
  await page.keyboard.press('Tab');
  await poll(() => (state.features || []).some(f => f.name === 'Окно фич 2') && document.querySelector('#ft-dr-list .ft-dr-on')?.textContent.includes('Окно фич 2'), 'the rename did not reach the list');
  await page.keyboard.press('Escape');
  await poll(() => document.getElementById('ft-drawer').classList.contains('hidden'), 'Esc did not close the drawer');
  // «Записи»: «Фича ▾»
  await page.evaluate(() => switchAppView('libtable')); await sleep(600);
  await page.click('#lt-feature-btn'); await sleep(250);
  await page.click('#text-menu button:has-text("Управлять фичами")');
  await poll(() => featureDrawerOpen(), '«Управлять фичами…» of «Записи» did not open the drawer');
  expect(await page.evaluate(() => document.querySelector('#ft-dr-list .ft-dr-on')?.textContent.includes('Окно фич 2')), 'the chosen feature was lost');
  // «Словарь»: the card stays, «В отдельном окне» opens and a second press closes (the drawer covers the button:
  // pressed from the keyboard)
  await page.evaluate(() => switchAppView('dict')); await sleep(700);
  expect(await page.isVisible('#ft-dict-list') && await page.evaluate(() => document.querySelector('#ft-dict-list').textContent.includes('Окно фич 2')), 'the card «Фичи» of «Словарь» lacks the feature');
  await page.focus('#dc-ft-open');
  await page.keyboard.press('Enter');
  await poll(() => document.getElementById('ft-drawer').classList.contains('hidden'), 'a second click on the opener did not close the drawer');
  await page.click('#dc-ft-open');
  await poll(() => featureDrawerOpen(), '«В отдельном окне» did not open the drawer');
  await page.keyboard.press('Escape');
  await poll(() => document.getElementById('ft-drawer').classList.contains('hidden'), 'Esc did not close the drawer in «Словарь»');
  // the chip «Фича:» of a recording: «Изменить фичу…» chooses its feature
  const fid = await page.evaluate(() => state.features.find(f => f.name === 'Окно фич 2').id);
  await page.evaluate(id => fetch('/api/meetings/2/features', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids: [id] }) }), fid);
  await page.evaluate(() => { switchAppView('library'); return openMeeting(2); }); await sleep(1500);
  await page.click(`#meeting-features [data-ft="${fid}"]`); await sleep(400);
  await page.click('#tk-pop button:has-text("Изменить фичу")');
  await poll(() => featureDrawerOpen(), '«Изменить фичу…» did not open the drawer');
  expect(await page.evaluate(id => document.querySelector('#ft-dr-list .ft-dr-on')?.dataset.fid === String(id), fid), 'the feature of the recording is not chosen');
  await page.keyboard.press('Escape');
  await poll(() => document.getElementById('ft-drawer').classList.contains('hidden'), 'Esc did not close the drawer over a recording');
  expect(!(await open()), 'the drawer is still open');
  // the captions on the whole window go over everything: the drawer does not stay above them
  await page.evaluate(() => { switchAppView('studio'); openFeatureDrawer(); });
  await poll(() => featureDrawerOpen(), 'the drawer did not open over the studio');
  await page.evaluate(() => toggleStudioFocus(true));
  await poll(() => document.getElementById('ft-drawer').classList.contains('hidden'), 'the drawer stayed over the captions on the whole window');
  await page.evaluate(() => { toggleStudioFocus(false); switchAppView('home'); });
  await sleep(300);
  await page.evaluate(id => fetch(`/api/features/${id}`, { method: 'DELETE' }).then(() => loadFeatures()), fid);
});

// A stopped recording whose mix waits for the end of a meeting: the card says why and counts down, not 1 %
// «после встречи» for two minutes (reported by the user); the row shows the time left in place of the percent
await step('mix wait countdown', async () => {
  const meeting = await page.evaluate(() => fetch('/api/meetings/3').then(r => r.json()));
  const waitEnd = Date.now() / 1000 + 100;
  Object.assign(meeting, { id: 9902, title: 'Запись 14-05', status: 'mixing', progress: 1, mix_wait: waitEnd, mix_deleting: false,
    stage_text: 'Сведение дорожек: пауза на случай следующей встречи', segments: [], summaries: {}, transcript_versions: [], duration: 0 });
  await page.route(/\/api\/meetings\/9902(\/|\?|$)/, r => /\/api\/meetings\/9902(\?|$)/.test(r.request().url())
    ? r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(meeting) }) : r.fulfill({ status: 404, body: '{}' }));
  // the list the page polls (library.js pollMeetingsLoop) holds the row too: else a redraw drops it mid-step
  await page.route(/\/api\/meetings(\?.*)?$/, async r => {
    const headers = { ...r.request().headers() };
    delete headers['if-none-match'];  // always the whole list, so the row is added to it
    const res = await r.fetch({ headers });
    const list = await res.json().catch(() => null);
    if (!Array.isArray(list)) return r.fulfill({ response: res });
    const { segments, ...row } = meeting;
    if (!list.some(x => x.id === 9902)) list.unshift({ ...row, mix_wait: meeting.mix_wait });
    return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(list) });
  });
  await page.evaluate(m => {
    const row = { ...m };
    delete row.segments;
    state.meetings.unshift(row);
    renderMeetingsSidebar();
    return openMeeting(9902);
  }, meeting);
  const sub = () => page.textContent('#tx-rc-sub');
  await until(() => /^Начнётся через 1:[34]\d — пауза/.test(document.getElementById('tx-rc-sub')?.textContent || ''),
    'the card does not count down', 6000).catch(() => {});  // the expect below says what it shows
  const first = await sub();
  expect(/^Начнётся через 1:[34]\d — пауза/.test(first), `the card does not count down: «${first}»`);
  expect((await page.textContent('#tx-rc-title')) === 'Сведение дорожек', 'the card is not the mix');
  expect(!(await page.textContent('#tx-rc-pct')), 'the card still shows a percent');
  await until(f => (document.getElementById('tx-rc-sub')?.textContent || '') !== f, 'the countdown does not move', 5000, first);
  // the row of «Записи» counts down too (the old sidebar's list is not drawn: audit K19)
  const slot = await page.evaluate(async () => {
    const back = state.appView;
    switchAppView('libtable');
    await new Promise(r => setTimeout(r, 300));
    const text = document.querySelector('#lt-body [data-mid="9902"] [data-mix-until]')?.textContent || '';
    switchAppView(back);
    await new Promise(r => setTimeout(r, 300));
    return text;
  });
  expect(/^Сведение · 1:[34]\d$/.test(slot), `the row shows no time left: «${slot}»`);
  // a meeting going on: no countdown, the reason
  await page.evaluate(() => {
    for (const m of [state.activeMeeting, state.meetings.find(x => x.id === 9902)]) m.mix_wait = 0;
    renderMeetingsSidebar();
    renderTxModelBar();
  });
  expect((await sub()) === 'Начнётся после встречи', `during a meeting: «${await sub()}»`);
  expect(await page.isVisible('#tx-rc-mixnow'), '«Свести сейчас» is not offered while the mix waits');
  // which meeting holds it, and «Свести сейчас» lets it go (asked by the user: «откуда эта пауза»)
  await page.evaluate(() => { state.activeMeeting.mix_why = { kind: 'calendar', title: 'Планёрка', end: '11:30' }; renderTxModelBar(); });
  expect((await sub()) === 'Начнётся после встречи «Планёрка» (до 11:30)', `the meeting is not named: «${await sub()}»`);
  if (shots) await page.screenshot({ path: `${shots}/mix-wait-why.png` });
  let asked = '';
  await page.route('**/api/meetings/9902/mix-now', r => {
    asked = r.request().method();
    meeting.mix_wait = null;  // as the server: the mix starts, so the page's next poll no longer shows the wait
    r.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' });
  });
  await page.click('#tx-rc-mixnow');
  for (let i = 0; i < 30 && (asked !== 'POST' || await page.isVisible('#tx-rc-mixnow')); i++) await sleep(100);
  expect(asked === 'POST', '«Свести сейчас» did not ask the server');
  expect(!(await page.isVisible('#tx-rc-mixnow')), '«Свести сейчас» is still offered after the mix started');
  await page.evaluate(() => { delete state.activeMeeting.mix_why; });
  await page.evaluate(() => {
    state.activeMeeting.mix_wait = Date.now() / 1000 + 100;
    renderTxModelBar();
  });
});

await step('mix wait cleanup', async () => {
  await page.evaluate(() => {
    state.meetings = state.meetings.filter(m => m.id !== 9902);
    state.activeMeeting = null;
    renderMeetingsSidebar();
    return openMeeting(1);
  });
  await page.unroute(/\/api\/meetings\/9902(\/|\?|$)/);
  await page.unroute(/\/api\/meetings(\?.*)?$/);
  await sleep(800);
});

// A bulk delete that fails says why, in the server's words (reported by the user: only «возможно, они сейчас
// обрабатываются» was shown, for recordings whose mix waited)
await step('bulk delete reason', async () => {
  const why = 'Запись обрабатывается: обработка отменяется, удалите её через несколько секунд.';
  await page.route(/\/api\/meetings\/[12](\?|$)/, r => r.request().method() === 'DELETE'
    ? r.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: why }) }) : r.continue());
  const toast = await page.evaluate(async () => {
    const ask = window.confirmDeleteDialog;
    window.confirmDeleteDialog = async () => ({});
    state.multi = new Set([1, 2]);
    try { await bulkDelete(); } finally { window.confirmDeleteDialog = ask; }
    return document.getElementById('toast').textContent;
  });
  await page.unroute(/\/api\/meetings\/[12](\?|$)/);
  expect(toast.includes(`Не удалось удалить записей: 2. ${why}`), `the reason is not shown: «${toast}»`);
  expect(!toast.includes('возможно'), 'the guess is still shown');
  expect(await page.evaluate(() => [1, 2].every(id => state.meetings.some(m => m.id === id))), 'a recording went');
});

// The citations of an answer as the server reads them (app/library_qa.cited_numbers): the ranges [1-3] / [5–6] /
// [2, 4-5] give a link for each source, count in the list of the sources and leave the history sent with a follow-up
await step('citation ranges', async () => {
  const r = await page.evaluate(() => {
    const src = k => ({ n: k, meeting_id: 1, title: `Встреча ${k}`, start: 10 * k, text: `фрагмент ${k}` });
    const byN = Object.fromEntries([1, 2, 3, 4, 5, 6].map(k => [k, src(k)]));
    const box = document.createElement('div');
    box.textContent = 'Итог [1-3], сроки [5–6] и [2, 4-5]; ещё [9].';
    linkifyCitations(box, byN, 0);
    const chat = { items: [{ question: 'q', status: 'done', data: { found: true, answer: 'Итог [1-3] и [2, 4-5].' } }, {}] };
    return { links: [...box.querySelectorAll('.lib-cite')].map(b => b.textContent).join(','), rest: box.textContent.includes('[9]'),
      cited: [...citedNumbers('Итог [1-3], сроки [5–6] и [2, 4-5].')].sort().join(','), history: assistantHistory(chat, chat.items[1])[0].answer };
  });
  expect(r.links === '1,2,3,5,6,2,4,5' && r.rest, `the ranges are not links: ${JSON.stringify(r)}`);
  expect(r.cited === '1,2,3,4,5,6', `the ranges are not counted: ${r.cited}`);
  expect(r.history === 'Итог и.', `the history keeps the citations: ${r.history}`);
});

// A brief cites whole meetings: its marks name the meeting's date, not «▶ 00:00» (reported by the user)
await step('brief cites whole meetings', async () => {
  const r = await page.evaluate(() => {
    const item = { data: { mode: 'brief', sources: [{ n: 1, meeting_id: 1, title: 'Планёрка', date: '2026-11-12', start: 0, whole: true, text: '' }] } };
    const moment = { data: { sources: [{ n: 1, meeting_id: 1, title: 'Планёрка', date: '2026-11-12', start: 75, text: 'фраза' }] } };
    return [asRefLabel(item.data.sources[0], item), asRefLabel(moment.data.sources[0], moment), asRefTip(item.data.sources[0], item),
      asRefLabel({ n: 1, date: '2026-11-12', start: 0 }, { data: { mode: 'digest' } })];
  });
  expect(r[0] === '12.11' && r[1] === '01:15' && r[3] === '12.11', `the marks: ${JSON.stringify(r)}`);
  expect(r[2].includes('Планёрка') && !r[2].includes('00:00'), `the tooltip: ${r[2]}`);
});

// A speaker's name in the analysis is a button (asked by the user: «not that Дмитрий»): its menu renames the
// speaker or puts another person in its place, and the analysis shows the new name at once
await step('name chip in the analysis', async () => {
  await page.evaluate(() => { switchAppView('library'); openMeeting(1); });
  await sleep(1200);
  await page.evaluate(() => { switchWorkspaceTab('summary'); selectSummaryTab('protocol'); });
  await sleep(600);
  const chip = page.locator('#summary-content .name-ref', { hasText: 'Олег' }).first();
  await chip.click();
  await sleep(300);
  const items = await page.$$eval('#text-menu button', els => els.map(e => e.textContent.trim()));
  expect(items.includes('Переименовать участника…') && items.includes('Это другой человек…'), `the menu: ${items.join(' | ')}`);
  await page.locator('#text-menu button', { hasText: 'Это другой человек…' }).click();
  for (let i = 0; i < 30 && !(await page.locator('#text-menu button', { hasText: 'Другое имя…' }).count()); i++) await sleep(100);
  await page.locator('#text-menu button', { hasText: /^Мария$/ }).click();
  let text = '';
  for (let i = 0; i < 30 && !/готовит Мария/.test(text); i++) { await sleep(100); text = await page.textContent('#summary-content'); }
  expect(/готовит Мария/.test(text), 'the analysis does not show the other person');
  const back = await page.evaluate(async () => { await updateSpeaker('SPEAKER_01', 'Олег', null); return document.querySelector('#summary-content').textContent; });
  expect(/готовит Олег/.test(back), 'the name did not come back');
});

// The names in a brief: the speakers of the recordings it cites are buttons; «Это другой человек…» renames the
// speaker there and in the answer's text
await step('name chip in a brief', async () => {
  await page.evaluate(() => switchAppView('ask'));
  await sleep(500);
  await page.evaluate(async () => {
    for (let i = 0; i < 30 && !ASSIST.loaded; i++) await new Promise(res => setTimeout(res, 100));
    assistantNewChat();
    currentChat().items.push({ id: 993, question: 'Бриф', scope: state.askScope, scopeLabel: '', status: 'done', at: new Date().toISOString(),
      data: { found: true, mode: 'brief', answer: '- **Олег** готовит список [1]\n- Анна посмотрит сроки [2], Анна Петрова в копии',
        sources: [{ n: 1, meeting_id: 2, title: 'Созвон по проекту', date: '2026-11-20', start: 0, whole: true, text: '' },
          { n: 2, meeting_id: 3, title: 'Разбор итогов недели', date: '2026-11-21', start: 0, whole: true, text: '' }] } });
    renderAssistant();
  });
  await sleep(300);
  const chips = await page.$$eval('#ask-thread [data-as-answer="993"] .name-ref', els => els.map(e => e.textContent));
  expect(chips.join() === 'Олег,Анна', `the chips: ${chips.join()}`);  // «Анна Петрова» is someone else
  await page.locator('#ask-thread .name-ref', { hasText: 'Анна' }).click();
  await sleep(300);
  const items = await page.$$eval('#text-menu > *', els => els.map(e => e.textContent.trim()));
  expect(items.some(x => x.startsWith('Созвон по проекту')) && items.some(x => x.startsWith('Разбор итогов недели')), `the menu: ${items.join(' | ')}`);
  await page.locator('#text-menu button', { hasText: 'Это другой человек…' }).click();
  for (let i = 0; i < 30 && !(await page.locator('#text-menu button', { hasText: 'Другое имя…' }).count()); i++) await sleep(100);
  await page.locator('#text-menu button', { hasText: /^Мария$/ }).click();
  let r = null;
  for (let i = 0; i < 40; i++) {
    await sleep(100);
    r = await page.evaluate(async () => ({ answer: assistantFindItem(993).data.answer,
      spk: (await fetch('/api/meetings/3').then(x => x.json())).speakers.SPEAKER_02.name }));
    if (r.answer.includes('Мария посмотрит') && r.spk === 'Мария') break;
  }
  expect(r.answer === '- **Олег** готовит список [1]\n- Мария посмотрит сроки [2], Анна Петрова в копии' && r.spk === 'Мария', `after: ${JSON.stringify(r)}`);
  await page.evaluate(async () => {
    for (const id of [2, 3]) await fetch(`/api/meetings/${id}/speakers`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ speaker_id: 'SPEAKER_02', name: 'Анна' }) });
    const chat = currentChat();
    chat.items = chat.items.filter(i => i.id !== 993);
    renderAssistant();
  });
});

// A caption line keeps the name it was given while Teams' recent lines slide on (reported by the user: names came
// and went and the captions jumped)
await step('caption names stay', async () => {
  const r = await page.evaluate(() => {
    const keep = [_recStartTime, stPeople.teams];
    try {
      _recStartTime = Date.now() - 20e3;
      const ln = { text: 'давайте посмотрим план', wall: Date.now() - 10e3, wallEnd: Date.now() - 8e3 };
      stPeople.teams = { recent: [{ at: 9, name: 'Анна Смирнова', text: 'давайте посмотрим план' }] };
      const first = capSpeaker(ln);
      stPeople.teams = { recent: [] };  // the line Teams matched slid out of its recent ones
      return [first, capSpeaker(ln)];
    } finally { [_recStartTime, stPeople.teams] = keep; }
  });
  expect(r[0] === 'Анна Смирнова' && r[1] === 'Анна Смирнова', `the name did not stay: ${JSON.stringify(r)}`);
});

// «Нагрузка недели» on a Wednesday at noon: the hours passed and the hours ahead apart in the head, the days to
// come and the rest of today drawn as planned (grey, not hatched), «по плану» in their hints, the days above the
// norm by fact and by plan (reported by the user: the meetings still ahead of the week read as hours already spent).
// The week before: a tick at its hours of each day, in place, and the difference beside the day's hours
await step('load of the week: plan', async () => {
  const p2 = await browser.newPage({ viewport: { width: 1300, height: 860 }, timezoneId: 'Europe/Berlin' });
  try {
    await p2.clock.install({ time: new Date('2026-11-25T12:00:00+01:00') });
    const ev = (d, a, b) => ({ title: 'Встреча', start: `2026-11-${d}T${a}:00`, end: `2026-11-${d}T${b}:00`, all_day: false });
    const week = { configured: true, recordings: [], holidays: {}, events: [
      ev(23, '10:00', '12:00'), ev(23, '14:00', '15:30'),  // Monday: 3.5 h
      ev(24, '09:00', '14:00'),                            // Tuesday: 5 h, above the norm of 4
      ev(25, '10:00', '11:00'), ev(25, '14:00', '16:00'),  // today: 1 h passed, 2 h ahead
      ev(26, '10:00', '11:00'),                            // Thursday: 1 h planned
      ev(27, '09:00', '14:00'),                            // Friday: 5 h planned, above the norm by plan
    ] };
    const last = { configured: true, recordings: [], holidays: {}, events: [
      ev(16, '10:00', '12:00'),                            // Monday: 2 h
      ev(17, '08:00', '11:00'), ev(17, '12:00', '15:00'),  // Tuesday: 6 h
      ev(18, '10:00', '13:00'),                            // Wednesday: 3 h, as this one
      ev(20, '09:00', '13:00'),                            // Friday: 4 h
    ] };
    // the answer by the range asked: this week, or the one before
    await p2.route('**/api/calendar/range*', r => {
      const start = new URL(r.request().url()).searchParams.get('start') || '';
      return r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(start.startsWith('2026-11-16') ? last : week) });
    });
    await p2.goto(`${base}/?token=${token}`);
    await p2.waitForTimeout(1500);
    await p2.evaluate(() => { document.getElementById('first-run-wizard')?.remove(); setUILanguage('ru'); dbSave({ norm: 4, charts: { ...(dbPrefs().charts || {}), load: 'col' } }); resetDashboard(); switchAppView('dashboard'); });
    let got = null;
    for (let i = 0; i < 40 && !(got && got.cols === 5); i++) {
      await p2.waitForTimeout(150);
      got = await p2.evaluate(() => {
        const w = document.querySelector('#db-grid .db-w-load');
        if (!w) return null;
        const cols = [...w.querySelectorAll('.dbc-col')];
        return { head: (w.querySelector('.db-load-sum') || {}).textContent, cols: cols.length,
          plan: cols.map(c => c.querySelector('i').classList.contains('plan')), done: cols.map(c => !!c.querySelector('.dbc-done')),
          tips: cols.map(c => c.title), note: (w.querySelector('.db-load-over') || {}).textContent };
      });
    }
    expect(got && got.cols === 5, `the widget did not draw the week: ${JSON.stringify(got)}`);
    expect(got.head === 'Во встречах: 9,5 ч · впереди 8 ч', `the head: «${got.head}»`);
    expect(JSON.stringify(got.plan) === '[false,false,true,true,true]', `the planned columns: ${got.plan}`);
    expect(JSON.stringify(got.done) === '[false,false,true,false,false]', `today's hours passed are not solid: ${got.done}`);
    expect(/по плану/.test(got.tips[4]) && !/по плану/.test(got.tips[0]) && /впереди 2 ч/.test(got.tips[2]), `the hints: ${got.tips.join(' | ')}`);
    expect(got.note === 'Сверх нормы: вт; по плану: пт', `the note: «${got.note}»`);
    // the week before: in the hints, the differences beside the hours, the ticks at their hours (the scale is the
    // largest of the norm, the days and the days before: 6 h), the plan a solid grey and Friday's part above the
    // norm framed apart
    const cmp = async () => {
      for (let i = 0; i < 40; i++) {
        const r = await p2.evaluate(() => {
          const w = document.querySelector('#db-grid .db-w-load');
          const cols = [...w.querySelectorAll('.dbc-col')];
          const tick = c => { const s = c.querySelector('.dbc-prev'); if (!s) return null; const a = c.getBoundingClientRect(), b = s.getBoundingClientRect(); return (a.bottom - (b.top + b.bottom) / 2) / a.height; };
          const plan = w.querySelector('.dbc-col i.plan'), cs = plan && getComputedStyle(plan);
          return { tips: cols.map(c => c.title), dx: [...w.querySelectorAll('.dbc-dxs .dbc-dx')].map(x => x.textContent), ticks: cols.map(tick),
            planBg: cs && cs.backgroundColor, planImg: cs && cs.backgroundImage, ovp: cols.map(c => !!c.querySelector('.dbc-ovp')),
            key: [...w.querySelectorAll('.dbc-key span')].map(x => x.textContent) };
        });
        if (r.dx.length) return r;
        await p2.waitForTimeout(150);
      }
      return null;
    };
    const c = await cmp();
    expect(c && JSON.stringify(c.dx) === '["+1,5","−1","","+1","+1"]', `the differences: ${JSON.stringify(c && c.dx)}`);
    expect(c.tips[1] === 'вт, 24 нояб.: 5 ч · прошлая неделя 6 ч (−1)', `the hint with the week before: «${c.tips[1]}»`);
    const want = [2, 6, 3, null, 4].map(h => h && h / 6);
    expect(c.ticks.every((v, i) => (want[i] == null ? v == null : Math.abs(v - want[i]) < 0.03)), `the ticks of the week before: ${JSON.stringify(c.ticks)}`);
    expect(c.planBg === 'rgb(99, 99, 102)' && c.planImg === 'none', `the plan is not a solid grey: ${c.planBg} ${c.planImg}`);
    expect(JSON.stringify(c.ovp) === '[false,false,false,false,true]', `the planned part above the norm: ${c.ovp}`);
    expect(JSON.stringify(c.key) === '["прошло","по плану","прошлая неделя"]', `the key: ${c.key}`);
    // the other looks: the planned bars, the grey parts of the ring, the dashed line; in the bars the ticks in place,
    // the hours in one column and the differences in another
    const looks = {};
    for (const k of ['bar', 'ring', 'line']) {
      await p2.evaluate(kind => setDashChart('load', kind), k);
      looks[k] = await p2.evaluate(() => {
        const w = document.querySelector('#db-grid .db-w-load');
        return w.querySelectorAll('.dbc-hb-t b.plan, .dbc-ring-plan, .dbc-lg-bar u.plan, .dbc-plot i.plan, .dbc-l-line.plan').length;
      });
      if (k === 'bar') {
        const b = await p2.evaluate(() => {
          const w = document.querySelector('#db-grid .db-w-load');
          const rows = [...w.querySelectorAll('.dbc-hb')];
          const right = sel => rows.map(r => Math.round(r.querySelector(sel).getBoundingClientRect().right));
          const ticks = rows.map(r => { const t = r.querySelector('.dbc-hb-t'), s = t.querySelector('.dbc-prev'); if (!s) return null; const a = t.getBoundingClientRect(), x = s.getBoundingClientRect(); return ((x.left + x.right) / 2 - a.left) / a.width; });
          return { v: right('.dbc-hb-v'), dx: right('.dbc-dx'), ticks, text: rows.map(r => r.querySelector('.dbc-dx').textContent) };
        });
        expect(new Set(b.v).size === 1 && new Set(b.dx).size === 1 && b.dx[0] > b.v[0], `the hours and the differences out of their columns: ${JSON.stringify(b)}`);
        expect(b.ticks.every((v, i) => (want[i] == null ? v == null : Math.abs(v - want[i]) < 0.03)), `the ticks of the bars: ${JSON.stringify(b.ticks)}`);
        expect(JSON.stringify(b.text) === '["+1,5","−1","","+1","+1"]', `the differences of the bars: ${b.text}`);
      }
    }
    expect(looks.bar === 3 && looks.ring >= 6 && looks.line >= 4, `the other looks: ${JSON.stringify(looks)}`);
    await p2.evaluate(() => { setUILanguage('en'); dbRedrawWidget('load'); });
    const en = await p2.evaluate(() => document.querySelector('#db-grid .db-w-load .db-load-sum').textContent);
    expect(en === 'In meetings: 9.5 h · ahead 8 h', `the head in English: «${en}»`);
    await p2.evaluate(() => { setDashChart('load', 'col'); setUILanguage('ru'); });
    await p2.waitForTimeout(800);  // the language is kept on the server before the page closes
  } finally { await p2.close(); }
});

// Stored markup (the dashboard's saved summary, a translation's language from a restored backup) cannot run
// a page function: the summary is sanitized again when shown, and a failed image may only call its fallback;
// a stored colour goes into a style only as a colour
await step('stored markup runs nothing', async () => {
  const r = await page.evaluate(async () => {
    window.vxProbeHit = 0;
    window.vxProbe = function vxProbe() { window.vxProbeHit += 1; };
    const html = sanitizedHtml('<p>ok</p><img src="/nope.png" data-error="vxProbe"><button data-click="vxProbe">x</button>');
    const box = document.createElement('div');
    box.innerHTML = '<img src="/nope-2.png" data-error="vxProbe"><img class="vx-fb" src="/nope-3.png" data-error="removeElement" data-error-args=\'[{"$": "el"}]\'>';
    document.body.appendChild(box);
    await new Promise(res => setTimeout(res, 800));
    const left = box.querySelectorAll('img').length, fallback = !box.querySelector('.vx-fb');
    box.remove();
    const colors = [cssColor('#0A84FF'), cssColor('red;background:url(//x)', '#8E8E93'), cssColor('#abc')];
    return { html, hit: window.vxProbeHit, left, fallback, colors };
  });
  expect(JSON.stringify(r.colors) === '["#0A84FF","#8E8E93","#abc"]', `a stored colour went into a style as it was: ${r.colors}`);
  expect(!/data-|<img|<button/.test(r.html) && r.html.includes('<p>ok</p>'), `the saved summary keeps markup: ${r.html}`);
  expect(r.hit === 0, 'a failed image ran a page function that is no fallback');
  expect(r.fallback && r.left === 1, 'the fallback of a failed image did not run');
});

// --- The audit of the page (a review by another assistant): each finding fixed is held here ---

// A brief or a digest is kept with its conversation: it was never saved and was gone after a reload
await step('digest is saved with its conversation', async () => {
  let saved = '';
  const digest = /\/api\/library\/digest$/, chats = /\/api\/assistant\/chats$/;
  await page.route(digest, r => r.fulfill({ status: 200, contentType: 'application/json',
    body: JSON.stringify({ found: true, mode: 'digest', answer: 'Итог недели: решения приняты.', sources: [] }) }));
  await page.route(chats, r => {
    if (r.request().method() !== 'PUT') return r.continue();
    saved = r.request().postData() || '';
    return r.fulfill({ status: 200, contentType: 'application/json', body: '{"ok": true}' });
  });
  try {
    await page.evaluate(async () => {
      switchAppView('ask');
      await assistantLoad();
      const off = window.assistantModelOff;
      window.assistantModelOff = () => false;
      try { await makeDigest(7); } finally { window.assistantModelOff = off; }
    });
    const end = Date.now() + 4000;
    while (!saved.includes('Итог недели') && Date.now() < end) await sleep(100);
  } finally { await page.unroute(digest); await page.unroute(chats); }
  expect(saved.includes('Итог недели: решения приняты.'), 'the digest was not saved');
});

// A bulk action that is not a deletion says what failed, not «Не удалось удалить записей»
await step('bulk action errors name no deletion', async () => {
  const route = /\/api\/meetings\/1\/title$/;
  await page.route(route, r => r.request().method() === 'PATCH'
    ? r.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ detail: 'Название слишком длинное' }) }) : r.continue());
  let toast = '';
  try {
    toast = await page.evaluate(async () => {
      const ask = window.askText, sel = window.libSelectedInOrder;
      window.askText = async () => 'Итоги {n}';
      window.libSelectedInOrder = () => state.meetings.filter(m => m.id === 1);
      document.getElementById('toast').innerHTML = '';
      try { await bulkRename(); } finally { window.askText = ask; window.libSelectedInOrder = sel; }
      return document.getElementById('toast').textContent;
    });
  } finally { await page.unroute(route); }
  expect(toast.includes('Не выполнено для записей: 1. Название слишком длинное') && !toast.includes('удалить'), `the message: «${toast}»`);
});

// The models popover before the setting of unloading is read: it threw «idle is not defined»
await step('models popover without the unload setting', async () => {
  const r = await page.evaluate(() => {
    const s = (state.system && state.system.settings) || {};
    const had = s.idle_unload_minutes;
    delete s.idle_unload_minutes;
    let err = '';
    try { toggleModelsPop(); } catch (e) { err = e.message; } finally { s.idle_unload_minutes = had; }
    const text = document.querySelector('#models-pop .mp-idle-btn')?.textContent || '';
    closeModelsPop();
    return { err, text };
  });
  expect(!r.err && r.text, `the popover: ${JSON.stringify(r)}`);
});

// Captions switched off while they start: what the start gets is stopped (a server session, a worklet and a timer
// went on for the rest of the recording)
await step('captions stopped while they start', async () => {
  const calls = [];
  const start = /\/api\/live\/start$/, sess = /\/api\/live\/audit-race\//;
  await page.route(start, async r => {
    await new Promise(res => setTimeout(res, 700));
    await r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session: 'audit-race' }) });
  });
  await page.route(sess, r => { calls.push(r.request().url()); return r.fulfill({ status: 200, contentType: 'application/json', body: '{}' }); });
  let r;
  try {
    r = await page.evaluate(async () => {
      const ctx = new AudioContext();
      const stream = ctx.createMediaStreamDestination().stream;
      const run = startLiveCaptions(ctx, stream).catch(e => e.message);
      stopLiveCaptions();
      const err = await run;
      await new Promise(res => setTimeout(res, 300));
      const out = { err: err || '', session: liveCap.session, timer: liveCap.timer, node: !!liveCap.node, starting: !!liveCap.starting };
      ctx.close();
      return out;
    });
  } finally { await page.unroute(start); await page.unroute(sess); }
  expect(!r.session && !r.timer && !r.node && !r.starting && !r.err, `the captions after the stop: ${JSON.stringify(r)}`);
  expect(calls.some(u => u.endsWith('/audit-race/stop')), `the server session was not stopped: ${calls.join(', ')}`);
});

// A refusal is said: «Расшифровать заново…» and a new title showed success whatever the server answered
await step('refusals are not shown as success', async () => {
  const re = /\/api\/meetings\/1\/(reconfigure|title)$/;
  await page.route(re, r => ['POST', 'PATCH'].includes(r.request().method())
    ? r.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: 'Запись обрабатывается' }) }) : r.continue());
  let r;
  try {
    r = await page.evaluate(async () => {
      switchAppView('library');
      await openMeeting(1);
      document.getElementById('toast').innerHTML = '';
      state.contextMeetingId = 1;
      ctxOpenReconfigureModal();
      await submitReconfigure();
      const open = !document.getElementById('modal-reconfigure').classList.contains('hidden');
      const toast1 = document.getElementById('toast').textContent;
      closeModal('reconfigure');
      const before = state.activeMeeting.title;
      document.getElementById('meeting-title-input').value = `${before} (правка)`;
      await saveMeetingTitle();
      return { open, toast1, kept: state.activeMeeting.title === before, input: document.getElementById('meeting-title-input').value === before,
        toast2: document.getElementById('toast').textContent };
    });
  } finally { await page.unroute(re); }
  expect(r.open && r.toast1.includes('Запись обрабатывается') && !r.toast1.includes('Запущена'), `reprocessing: ${JSON.stringify(r)}`);
  expect(r.kept && r.input, `the title: ${JSON.stringify(r)}`);
});

// The period of the assistant is read by the day of the meeting (it read a field that does not exist, then the import)
await step('assistant period by the meeting day', async () => {
  const r = await page.evaluate(() => {
    const m0 = state.meetings[0], was = [m0.recorded_at, m0.created_at];
    m0.recorded_at = '2020-01-02 10:00:00'; m0.created_at = '2026-11-20 10:00:00';
    const found = assistantScopeIds({ type: 'period', from: '2020-01-01', to: '2020-01-03' }).includes(m0.id);
    [m0.recorded_at, m0.created_at] = was;
    return found;
  });
  expect(r, 'the period of the assistant reads the day of the import');
});

// The phrase under the playhead stays lit when a short one said inside it has ended
await step('phrase under the playhead over a short one', async () => {
  const r = await page.evaluate(() => {
    const items = [{ s: 0, e: 10 }, { s: 5, e: 6 }, { s: 20, e: 25 }];
    return [findActiveItem(items, 7, 0), findActiveItem(items, 5.5, 0), findActiveItem(items, 15, 0)];
  });
  expect(JSON.stringify(r) === '[0,1,-1]', `the phrase under the playhead: ${JSON.stringify(r)}`);
});

// Recordings of one name in one export do not write over each other
await step('export names of one export', async () => {
  const r = await page.evaluate(() => { const used = new Set(); return ['Итоги.docx', 'итоги.docx', 'Итоги.docx', 'План'].map(n => ltUniqueName(n, used)); });
  expect(JSON.stringify(r) === '["Итоги.docx","итоги (2).docx","Итоги (3).docx","План"]', `the names: ${JSON.stringify(r)}`);
});

// The toast of a saved recording says what waits: «Только запись» or the paused queue
await step('saved recording says what waits', async () => {
  const r = await page.evaluate(() => {
    const out = {};
    const eco = window.economyOn, paused = state.queuePaused;
    window.economyOn = () => true; out.eco = recordSavedKey();
    window.economyOn = () => false; state.queuePaused = true; out.paused = recordSavedKey();
    state.queuePaused = false; out.queued = recordSavedKey();
    window.economyOn = eco; state.queuePaused = paused;
    return out;
  });
  expect(r.eco === 'recordSavedEconomy' && r.paused === 'recordSavedPaused' && r.queued === 'recordSavedQueued', `the saved toast: ${JSON.stringify(r)}`);
});

// The search of the tasks does not find the empty fields («null»); the names of people have no Latin letter in a
// Russian one
await step('task search and given names', async () => {
  const r = await page.evaluate(() => {
    const q = TK.q;
    TK.q = 'null';
    const nullFound = tkMatchesPeopleAndSearch({ what: 'Прислать смету', who: null, meeting_title: null, quote: undefined });
    TK.q = q;
    return { nullFound, mixed: [...GIVEN_NAMES].filter(n => /[а-яё]/.test(n) && /[a-z]/.test(n)) };
  });
  expect(!r.nullFound, '«null» finds a task with empty fields');
  expect(!r.mixed.length, `names with Latin letters: ${r.mixed}`);
});

// «Изменить текст» of a task works in «Карточки» too (it looked for a row of the list only)
await step('task text edited in the cards', async () => {
  await page.evaluate(() => switchAppView('tasks'));
  await until(() => (TK.data.tasks || []).length > 0, 'no tasks', 5000);
  const r = await page.evaluate(() => {
    const view = TK.view;
    setTasksView('cards');
    const id = TK.data.tasks[0].id;
    editTaskText(id);
    const input = document.querySelector(`.tk-tcard[data-tid="${id}"] input.tk-row-edit`);
    const ok = !!input && document.activeElement === input;
    if (input) input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    setTasksView(view);
    return ok;
  });
  expect(r, 'no field to edit the text of a card');
});

// A column of «Записи» dropped on itself stays where it was (it went one place before the last)
await step('column dropped on itself stays', async () => {
  await page.evaluate(() => switchAppView('libtable'));
  await page.click('[data-lt-cols]');
  const r = await page.evaluate(() => {
    const before = ltPrefs().order.join(',');
    const row = document.querySelector('#lt-cols-pop [data-colrow]');
    const dt = new DataTransfer();
    row.dispatchEvent(new DragEvent('dragstart', { bubbles: true, dataTransfer: dt }));
    row.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: dt }));
    row.dispatchEvent(new DragEvent('dragend', { bubbles: true, dataTransfer: dt }));
    return { before, after: ltPrefs().order.join(',') };
  });
  await page.evaluate(() => closeLibTableColumnsMenu());
  expect(r.before === r.after, `the order changed: ${r.before} → ${r.after}`);
});

// One «Расшифровать заново» in the toolbar of the text; the one with the choices is in «⋯»
await step('one transcribe-again button', async () => {
  await page.evaluate(async () => { switchAppView('library'); await openMeeting(1); switchWorkspaceTab('transcript'); });
  await sleep(500);
  const r = await page.evaluate(() => {
    const shown = [...document.querySelectorAll('#tx-subbar button')].filter(b => b.getClientRects().length && /txRedo|recReconfigure/.test(b.dataset.click || ''));
    return shown.map(b => b.dataset.click);
  });
  expect(r.length === 1, `the buttons: ${r}`);
  await page.click('#tx-more-btn');
  await sleep(300);
  const menu = (await page.$$eval('#text-menu button', els => els.map(e => e.textContent))).join(' | ');
  await page.keyboard.press('Escape');
  expect(menu.includes('Расшифровать заново…'), `«Расшифровать заново…» is not in «⋯»: ${menu}`);
});

// The notices stand clear of the player's controls and the assistant's question (the notice of an update covered them)
await step('notices clear of the player and the question', async () => {
  const covered = async (sel) => page.evaluate((sel) => [...document.querySelectorAll(sel)].filter(b => b.getClientRects().length).filter(b => {
    const r = b.getBoundingClientRect();
    return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)?.closest('#toast');
  }).map(b => b.id || b.className), sel);
  const notice = () => page.evaluate(() => { document.getElementById('toast').innerHTML = ''; showToast('Доступна версия 9.9.9', { label: 'Подробнее', onClick: () => {} }); });
  await page.evaluate(async () => { switchAppView('library'); await openMeeting(1); });
  await sleep(600);
  await notice();
  await sleep(400);
  const player = await covered('.rp-right button, .rp-right input');
  await page.evaluate(() => switchAppView('ask'));
  await sleep(400);
  const ask = await covered('#library-ask-btn, #library-question');
  await page.evaluate(() => { document.getElementById('toast').innerHTML = ''; switchAppView('library'); });
  expect(!player.length && !ask.length, `covered by a notice: ${[...player, ...ask]}`);
});

// The hint of the strip without a calendar gives way with «…» (it was cut mid-word at 1100 px)
await step('strip hint ends with an ellipsis', async () => {
  await page.setViewportSize({ width: 1100, height: 700 });
  await sleep(500);
  const r = await page.evaluate(() => {
    const g = document.getElementById('strip-grow'), meta = document.getElementById('strip-meta');
    return { text: g.textContent, cut: g.scrollWidth > g.clientWidth, ell: getComputedStyle(g).textOverflow, meta: meta.textContent,
      kind: strip.kind, configured: strip.configured };
  });
  await page.setViewportSize({ width: 1300, height: 860 });
  if (r.kind !== 'free' || r.configured) return;  // a calendar in the data (an earlier step adds the demo one): no hint
  expect(r.text.includes('календар') && !r.meta && r.ell === 'ellipsis', `the hint: ${JSON.stringify(r)}`);
});

// The tab chosen shows the keyboard's ring
await step('the chosen tab shows the focus', async () => {
  await page.evaluate(async () => { switchAppView('library'); await openMeeting(1); switchWorkspaceTab('transcript'); });
  await sleep(300);
  await page.focus('#nav-transcript');
  await page.keyboard.press('Shift+Tab');
  await page.keyboard.press('Tab');
  const r = await page.evaluate(() => { const e = document.activeElement; const s = getComputedStyle(e); return { id: e.id, outline: s.outlineStyle, w: s.outlineWidth }; });
  expect(r.id !== 'nav-transcript' || (r.outline !== 'none' && r.w !== '0px'), `no ring: ${JSON.stringify(r)}`);
});

// «Выбрать своё имя» is one button in one place on the cards of «Сегодня» (a link in one, a button in the other)
await step('set my name: one button on the cards', async () => {
  await page.evaluate(() => switchAppView('home'));
  await sleep(1200);
  const r = await page.evaluate(() => [...document.querySelectorAll('#home-view [data-click="hmSetMyName"]')].filter(b => b.getClientRects().length).map(b => {
    const r = b.getBoundingClientRect(), card = b.closest('.db-w, .td-card, section, [class*="card"]')?.getBoundingClientRect();
    return { cls: b.className, h: Math.round(r.height), w: Math.round(r.width), dx: card ? Math.round(r.left - card.left) : null };
  }));
  if (r.length < 2) return;  // the name is set in the data: nothing to compare
  expect(new Set(r.map(x => `${x.cls}|${x.h}|${x.w}|${x.dx}`)).size === 1, `the buttons differ: ${JSON.stringify(r)}`);
});

// Esc in the window of an update over the settings closes that window only; the deletion question is a dialog
await step('esc over the settings closes the top window', async () => {
  await page.evaluate(async () => {
    openModal('settings', 'general');
    updateState.info = updateState.info || { current: '0.0.0', latest: { version: '0.0.1', notes: '' }, download: {} };
    await openUpdateDialog();
  });
  await sleep(300);
  await page.evaluate(() => document.body.focus());
  await page.keyboard.press('Escape');
  await sleep(300);
  const r = await page.evaluate(() => ({ dlg: !!document.getElementById('upd-dlg'), settings: !document.getElementById('modal-settings').classList.contains('hidden') }));
  await page.evaluate(() => { document.getElementById('upd-dlg')?.remove(); closeModal('settings'); });
  expect(!r.dlg && r.settings, `after Esc: ${JSON.stringify(r)}`);
  const role = await page.evaluate(async () => {
    const ask = confirmDeleteDialog(state.meetings[0]);
    const w = document.querySelector('[aria-labelledby="del-dlg-title"]');
    const out = w ? `${w.getAttribute('role')}|${w.getAttribute('aria-modal')}` : '';
    w?.querySelector('button[data-a="no"]')?.click();
    await ask;
    return out;
  });
  expect(role === 'dialog|true', `the deletion question: «${role}»`);
});

// The assistant's conversations as the window closes (found in the audit: what changed in the last half-second was
// lost): pagehide sends what changed since the last save at once, with keepalive, and the server has it
await step('assistant chats saved on window close', async () => {
  await page.evaluate(() => { switchAppView('ask'); return assistantLoad(); });
  await until(() => ASSIST.ready, 'the conversations did not load');
  const sent = [];
  const seen = r => { if (r.url().includes('/api/assistant/chats')) sent.push(`${r.method()} ${r.url().replace(/^.*\/api/, '/api')}`); };
  page.on('request', seen);
  const id = await page.evaluate(() => {
    const chat = newChatObject();
    chat.title = 'Проверка при закрытии окна';
    chat.items.push({ id: 1, question: 'Что решили?', status: 'done', data: { answer: 'План согласован.' } });
    ASSIST.chats.unshift(chat);
    assistantSaveSoon();  // the save of half a second later never comes: the window closes first
    window.dispatchEvent(new Event('pagehide'));
    return chat.id;
  });
  await sleep(900);
  page.off('request', seen);
  const stored = await page.evaluate(id => fetch('/api/assistant/chats').then(r => r.json()).then(d => d.chats.some(c => c.id === id && c.title === 'Проверка при закрытии окна')), id);
  await page.evaluate(id => { ASSIST.chats = ASSIST.chats.filter(c => c.id !== id); window.dispatchEvent(new Event('pagehide')); }, id);
  await sleep(300);
  const gone = await page.evaluate(id => fetch('/api/assistant/chats').then(r => r.json()).then(d => !d.chats.some(c => c.id === id)), id);
  expect(stored && gone && sent.includes('POST /api/assistant/chats/merge') && !sent.some(x => x.startsWith('PUT')),
    `the conversation on closing: ${JSON.stringify({ stored, gone, sent })}`);
});

// The search of a section (found in the audit: 280px at four places, in «Люди» in the list on the left): the last control of
// the head in «Записи», «Задачи», «Словарь» and «Люди», at one x, y and width, 32px high, at the window's minimum too
await step('one place for the search', async () => {
  const boxes = {};
  for (const [w, h] of [[1300, 860], [1100, 700]]) {
    await page.setViewportSize({ width: w, height: h });
    for (const v of ['libtable', 'tasks', 'dict', 'people']) {
      await page.evaluate(x => switchAppView(x), v);
      await until(x => !document.getElementById(`${x}-view`).classList.contains('hidden'), `${v} did not open`, 5000, v);
      await sleep(400);  // the section fades in
      boxes[`${v}@${w}`] = await page.evaluate(x => {
        const head = document.querySelector(`#${x}-view .vx-shead`);
        const s = head && head.querySelector('.tk-search');
        if (!s) return null;
        const b = s.getBoundingClientRect(), view = document.getElementById(`${x}-view`).getBoundingClientRect();
        const last = [...head.querySelectorAll('button, label, input')].filter(e => e.offsetParent && !s.contains(e))
          .every(e => e.getBoundingClientRect().right <= b.left + 1 || e.getBoundingClientRect().bottom <= b.top + 1);
        return { x: Math.round(b.left), y: Math.round(b.top), w: Math.round(b.width), h: Math.round(b.height), gap: Math.round(view.right - b.right), last };
      }, v);
    }
    const list = Object.entries(boxes).filter(([k]) => k.endsWith(`@${w}`));
    const bad = list.filter(([, b]) => !b || Math.abs(b.w - 236) > 1 || Math.abs(b.h - 32) > 1 || Math.abs(b.gap - 24) > 1 || !b.last
      || Math.abs(b.x - list[0][1].x) > 1 || Math.abs(b.y - list[0][1].y) > 1);
    expect(!bad.length, `the search is not in one place at ${w}px: ${JSON.stringify(Object.fromEntries(list))}`);
  }
  await page.setViewportSize({ width: 1300, height: 860 });
});

await browser.close();
if (errors.length) {
  console.error(errors.join('\n'));
  process.exit(1);
}
console.log('UI scenarios passed');
