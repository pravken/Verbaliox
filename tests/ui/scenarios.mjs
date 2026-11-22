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
const errors = [];
page.on('pageerror', e => errors.push(`page: ${e.message}`));
page.on('response', r => { if (r.status() >= 500) errors.push(`HTTP ${r.status()} ${r.url().replace(/\?.*/, '')}`); });

let n = 0;
const step = async (name, fn) => {
  try { await fn(); } catch (e) { errors.push(`${name}: ${e.message.split('\n')[0]}`); }
  if (shots) await page.screenshot({ path: `${shots}/${String(++n).padStart(2, '0')}-${name.replace(/\W+/g, '-')}.png` });
};
const expect = (ok, what) => { if (!ok) throw new Error(what); };
const sleep = (ms) => page.waitForTimeout(ms);

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
  await sleep(1500);
  expect(await page.locator('#transcript-container .segment-row').count() > 0, 'no transcript lines');
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
  await sleep(800);
  await page.evaluate(() => { openRecordTab('transcript'); setTxLayout('chat'); });
  await sleep(300);
  const bubbles = await page.locator('#transcript-inner .ch-bub.segment-row').count();
  expect(bubbles > 0, 'no bubbles in «Чат»');
  expect(await page.locator('#transcript-inner .ch-bub .ch-tm').count() === bubbles, 'a bubble without its time');
  const runs = await page.locator('#transcript-inner .ch-group').count();
  expect(await page.locator('#transcript-inner .ch-group > .ch-av').count() === runs, 'the face is not once per run');
  await page.evaluate(() => updatePlaybackHighlight(1, true));
  expect(await page.locator('#transcript-inner .ch-bub.segment-active').count() === 1, 'the phrase playing is not lit');
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
  expect(await page.isVisible('#recording-context-menu button[data-click="ctxExport"]'), 'no export in the menu');
  await page.evaluate(() => hideContextMenu());
  await sleep(250);
  // the same menu in a low window scrolls inside it; opened again in a tall one it has its whole height back
  const ctxAt = () => page.evaluate(() => {
    openRecordingContextMenu({ clientX: 300, clientY: 40, preventDefault() {}, stopPropagation() {} }, 1);
    return new Promise(ok => setTimeout(() => { const e = document.getElementById('recording-context-menu'), r = e.getBoundingClientRect();
      ok({ bottom: r.bottom, vh: innerHeight, max: e.style.maxHeight }); }, 250));
  });
  await page.setViewportSize({ width: 1300, height: 360 });
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

// Undo instead of a question: a task goes at once and comes back with «Отменить» (6.1)
await step('undo a removal', async () => {
  await page.evaluate(() => switchAppView('tasks'));
  await sleep(800);
  const before = await page.evaluate(() => TK.data.tasks.length);
  await page.evaluate(() => deleteTask(TK.data.tasks[0].id));
  await sleep(300);
  expect(await page.evaluate(() => TK.data.tasks.length) === before - 1, 'the task did not go');
  await page.click('#toast .toast-action');
  await sleep(300);
  expect(await page.evaluate(() => TK.data.tasks.length) === before, '«Отменить» did not bring it back');
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
  // the recommended set)
  await page.click('#first-run-wizard button[data-pick="ai:none"]');
  await page.click('#first-run-wizard button[data-a="next"]');
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
  await page.evaluate(() => fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ settings: { holiday_country: '', setup_done: '[]' } }) }));
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
  await sleep(800);
  expect(await page.$(`#cal-view [data-daykey="${day}"].cal-holday`), 'the day is not marked');
  await page.click(`#cal-view [data-daykey="${day}"]`, { button: 'right' });
  await sleep(200);
  await page.click('#text-menu button:has-text("Убрать выходной")');
  await sleep(800);
  expect(!(await page.$(`#cal-view [data-daykey="${day}"].cal-holday`)), 'the day off is not taken back');
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
  expect(await col.evaluate(el => getComputedStyle(el).cursor) === 'pointer', 'no hand over the day');
  const box = await col.boundingBox();
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
  await sleep(900);
  expect(await page.locator('#lt-body .lt-snip').count() > 0, 'the search shows no places in the text');
  expect(/мест/.test(await page.textContent('#lt-count')), 'the count does not say how many places were found');
  await page.fill('#lt-q', '');
  await sleep(300);
  await page.click('#lt-body .lt-row .lt-c-name');
  await sleep(600);
  expect(await page.evaluate(() => state.appView) === 'library', 'a click did not open the recording');
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
    [[1, 'Начнём с плана.', 'Мария'], [2, 'Я посмотрю сроки.', 'Анна'], [3, 'И проверю оценку.', 'Анна']]
      .forEach(([id, text, who]) => liveCap.lines.set(id, { id, text, who, lang: 'ru', translation: '' }));
    liveCap.partial = 'ещё говорит';
    syncStudioCaptions();
    const out = [...document.querySelectorAll('#studio-cap-rows > .cap-row')].map(e => ({ cls: e.className, bub: !!e.querySelector('.cap-bub') }));
    liveCap.lines.clear();
    liveCap.partial = '';
    capReset();
    return out;
  });
  expect(rows.length === 4 && rows.every(r => r.bub), `the lines are not bubbles: ${JSON.stringify(rows)}`);
  expect(!/cap-cont/.test(rows[1].cls) && /cap-cont/.test(rows[2].cls), 'the face and the name are not once per run');
  expect(/cap-now/.test(rows[2].cls) && /cap-pending/.test(rows[3].cls) && !/cap-now/.test(rows[3].cls), `the last line is not lit: ${rows.map(r => r.cls).join(' | ')}`);
  await page.evaluate(() => switchAppView('library'));
});

await step('captions do not start by themselves', async () => {
  const held = await page.evaluate(() => [
    captionsHeldAtStart({}),
    captionsHeldAtStart({ live_captions_auto: 'true', analysis_after_meetings: 'true' }),
    captionsHeldAtStart({ live_captions_auto: 'true', analysis_after_meetings: 'false' }),
    captionsHeldAtStart({ live_captions_auto: 'false', analysis_after_meetings: 'false' }),
  ]);
  expect(JSON.stringify(held) === '[true,true,false,true]', `the captions rule: ${held}`);
  await page.evaluate(() => openModal('settings', 'recording'));
  await sleep(600);
  expect(!(await page.isChecked('#set-live-captions-auto')), 'captions are on by default');
  await page.evaluate(() => closeModal('settings'));
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
  await sleep(600);
  expect(await page.evaluate(() => DB.data && DB.data.period === 'month' && document.querySelector('#db-periods button[aria-checked="true"]').textContent === 'Месяц'), 'the period did not change');
  await page.click('#db-periods button >> nth=0');
  await sleep(300);
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
  expect(await page.locator('#meetings-list [data-mid]').count() > 0, 'the list is empty after the poll');
});

// A progress event redraws only that recording's row, not the sorted list of every recording (audit:
// each event rebuilt all rows); a change of its status still draws the whole list
await step('progress redraws one row', async () => {
  await page.evaluate(() => switchAppView('library'));
  await sleep(300);
  const r = await page.evaluate(async () => {
    const frame = () => new Promise(res => requestAnimationFrame(() => setTimeout(res, 0)));
    const m = state.meetings[0];
    const was = m.status;
    m.status = 'transcribing';
    m.progress = 10;
    renderMeetingsSidebar();
    let full = 0;
    const real = window.renderMeetingsSidebar;
    window.renderMeetingsSidebar = (...a) => { full++; return real(...a); };
    handleLiveEvent({ type: 'progress', id: m.id, progress: 37, stage_text: 'x' });
    await frame();
    const row = document.querySelector(`#meetings-list [data-mid="${m.id}"]`);
    const shown = row ? row.textContent.includes('37%') : false;
    const afterRow = full;
    handleLiveEvent({ type: 'progress', id: m.id, status: was, progress: 100 });
    await frame();
    window.renderMeetingsSidebar = real;
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
  await page.click('#strip-acts button:has-text("Не записывать")');
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

// While recording, the time on the red button opens the studio and does not stop the recording (asked by the user)
await step('recording time opens the studio', async () => {
  await page.evaluate(() => { window.__recOrig = [window.isRecording, window.shellQuickRecord]; window.__stops = 0;
    window.isRecording = () => true; window.shellQuickRecord = () => { window.__stops++; };
    document.getElementById('studio-timer').textContent = '01:23'; updateRecordButtonState(); switchAppView('home'); });
  await page.click('#tb-rec-clock');
  await sleep(300);
  const r = await page.evaluate(() => [state.appView, window.__stops]);
  expect(r[0] === 'studio' && r[1] === 0, `the time did not open the studio alone: ${r}`);
  // in the studio the time is a part of the red button: its click stops as the rest of the button does
  await page.evaluate(() => updateRecordButtonState());
  await page.click('#tb-rec-clock');
  await sleep(200);
  expect(await page.evaluate(() => window.__stops) === 1, 'the time in the studio was a dead spot of the red button');
  await page.evaluate(() => { [window.isRecording, window.shellQuickRecord] = window.__recOrig; updateRecordButtonState(); switchAppView('home'); });
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
  await page.evaluate(() => { document.getElementById('first-run-wizard')?.remove(); setUILanguage('ru'); dbSave({ period: 'week' }); });
  await sleep(1200);
  const kept = await page.evaluate(() => fetch('/api/system').then(r => r.json()).then(d => [d.settings.ui_lang, JSON.parse(d.settings.ui_dashboard).period]));
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
  await sleep(2200);
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
  await sleep(2900);
  expect(!(await page.isVisible('#strip-island')) && !(await page.isVisible('#jobs-pop')), 'the island or its window stayed');
  // cancelled: no «Готово»
  await page.evaluate(() => { const m = state.meetings[0]; state.queue = [{ id: m.id, state: 'running', kind: 'analysis', title: m.title, progress: 3, position: 1 }]; strip.kind = 'free'; renderJobsIsland(); islandCancelled(); renderJobsIsland(); state.queue = []; renderJobsIsland(); });
  expect(!(await page.isVisible('#strip-island')), '«Готово» after a cancel');
  // never visible: no «Готово»
  await page.evaluate(() => { state.queue = []; renderJobsIsland(); });
  expect(!(await page.isVisible('#strip-island')), '«Готово» with nothing before');
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
  await page.evaluate(id => fetch(`/api/features/${id}`, { method: 'DELETE' }).then(() => loadFeatures()), fid);
});

await browser.close();
if (errors.length) {
  console.error(errors.join('\n'));
  process.exit(1);
}
console.log('UI scenarios passed');
