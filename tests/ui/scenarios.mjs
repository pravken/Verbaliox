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

// Import: the model and the language in sight, the rest behind «Изменить» (8.3)
await step('import window', async () => {
  await page.evaluate(() => openImportDialog());
  await sleep(400);
  expect(await page.isVisible('#upload-model') && await page.isVisible('#upload-language'), 'model or language not shown');
  expect(!(await page.isVisible('#upload-speakers')), 'the rare options are open');
  await page.click('#imp-more-btn');
  await sleep(200);
  expect(await page.isVisible('#upload-speakers'), '«Изменить» did not open the options');
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
  // one short row (variant B): «Версия: … ▾», «Расшифровать заново», «⋯» and when the text was made
  expect(/Версия:/.test(await page.textContent('#tx-model-chip')), 'no version button');
  expect(await page.isVisible('#tx-redo-btn') && await page.isVisible('#tx-more-btn'), 'the row lacks its buttons');
  await page.click('#tx-model-chip');
  await sleep(200);
  const versions = await page.$$eval('#text-menu button', els => els.map(e => e.textContent));
  expect(versions.some(x => x.includes('✓')), `the version shown is not marked: ${versions.join(' | ')}`);
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

// After an update: a small wizard asks the settings a new version brings (asked by the user), once
await step('setup steps after an update', async () => {
  await page.evaluate(() => document.querySelectorAll('.modal-backdrop').forEach(m => m.id === 'first-run-wizard' && m.remove()));
  await page.evaluate(() => openSetupSteps({ holiday_country: '', setup_done: '[]' }));
  await page.waitForSelector('#setup-steps select[data-hol-country] option[value="RS"]', { state: 'attached' });
  await page.selectOption('#setup-steps select[data-hol-country]', 'RS');
  expect(!(await page.$('#setup-steps select[data-hol-subdiv]')), 'a region offered for a country without them');
  await page.click('#setup-steps button[data-a="next"]');
  await sleep(500);
  // then the news of the version, one step each: the last one closes the wizard
  for (let i = 0; i < 5 && await page.$('#setup-steps-dialog'); i++) {
    expect(await page.$('#setup-steps .frw-points li'), 'a news step without its points');
    await page.click('#setup-steps button[data-a="next"]');
    await sleep(400);
  }
  expect(!(await page.$('#setup-steps')), 'the wizard stayed open');
  const set = await page.evaluate(() => fetch('/api/system').then(r => r.json()).then(d => d.settings));
  expect(set.holiday_country === 'RS', `the country not saved: ${set.holiday_country}`);
  // answered: not asked again
  await page.evaluate(sv => openSetupSteps(sv), set);
  await sleep(400);
  expect(!(await page.$('#setup-steps')), 'asked again after it was answered');
  await page.evaluate(() => fetch('/api/settings', { method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ settings: { holiday_country: '', setup_done: '[]' } }) }));
});

// A calendar meeting about to start with a Teams link: «Подключиться» on its card joins the call (asked by the user)
await step('join a meeting call', async () => {
  const sent = [];
  await page.route('**/api/meeting/join', r => { sent.push(r.request().postDataJSON()); r.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' }); });
  await page.evaluate(() => {
    switchAppView('dashboard');
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
  expect(await page.locator('#feature-page .fp-person').count() > 0, 'no people on the card');
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
  await sleep(400);
  await page.evaluate(() => {
    document.getElementById('dayoff-from').value = '2026-03-02';
    document.getElementById('dayoff-to').value = '2026-03-04';
    document.getElementById('dayoff-title').value = 'Отпуск';
  });
  await page.click('button[data-click="addDayOff"]');
  await sleep(500);
  expect((await page.textContent('#dayoff-list')).includes('Отпуск'), 'the vacation is not listed');
  const set = await page.evaluate(() => fetch('/api/system').then(r => r.json()).then(d => d.settings));
  expect(JSON.parse(set.days_off)[0].to === '2026-03-04', `not saved: ${set.days_off}`);
  await page.click('#dayoff-list button[data-click="removeDayOff"]');
  await sleep(500);
  expect(!(await page.textContent('#dayoff-list')).includes('Отпуск'), 'the vacation was not removed');
  await page.evaluate(() => closeModal('settings'));
});

// The cloud choice keeps the speech settings: its consent is asked in Settings → Analysis (no stub here:
// the real server must accept the request)
await step('first run wizard, cloud', async () => {
  for (const url of ['**/api/models/setup', '**/api/onnx-models/**', '**/api/ffmpeg/install', '**/api/ollama/**']) {
    await page.route(url, r => r.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
  }
  let status = 0;
  const watch = r => { if (r.url().endsWith('/api/settings') && r.request().method() === 'POST' && !status) status = r.status(); };
  page.on('response', watch);
  await page.evaluate(() => openFirstRunWizard(state.system));
  await sleep(300);
  await page.click('#first-run-wizard button[data-pick="ai:cloud"]');
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
  await page.evaluate(() => closeModal('settings'));
});

// The calendar of a week or a month opens from the home page and closes with Esc
await step('calendar view', async () => {
  await page.evaluate(() => switchAppView('home'));
  await sleep(500);
  await page.click('button[data-click="openCalendarView"]');
  await sleep(600);
  expect(await page.isVisible('#cal-view .cal-week, #cal-view .cal-month'), 'the calendar did not open');
  await page.click('#cal-view button[data-cal="month"]');
  await sleep(500);
  expect(await page.isVisible('#cal-view .cal-month'), 'the month did not show');
  await page.click('#cal-view button[data-cal="week"]');
  await sleep(400);
  await page.keyboard.press('Escape');
  await sleep(200);
  expect(!(await page.$('#cal-view')), 'Esc did not close the calendar');
});

// The library as a table on the whole window: sorted by a header, a column added, a double click opens
await step('library table', async () => {
  await page.click('#lib-table-btn');
  await sleep(500);
  expect(await page.isVisible('#libtable-view'), 'the table did not open');
  const rows = await page.$$eval('#lt-table tr[data-mid]', trs => trs.length);
  expect(rows > 0, 'the table has no rows');
  await page.click('#lt-table th[data-col="name"]');
  await sleep(200);
  expect(await page.isVisible('#lt-table th.lt-sorted[data-col="name"]'), 'the name header did not sort');
  await page.click('button[data-click="openLibTableColumnsMenu"]');
  await page.click('#lt-cols-menu button[data-col="size"]');
  await sleep(200);
  expect(await page.isVisible('#lt-table th[data-col="size"]'), 'the size column did not appear');
  await page.click('#lt-cols-menu button[data-col="reset"]');
  await page.keyboard.press('Escape');
  await page.dblclick('#lt-table tr[data-mid] td.lt-c-name');
  await sleep(600);
  expect(await page.evaluate(() => state.appView) === 'library', 'a double click did not open the recording');
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

// The dashboard: the first page, its widgets, «Настроить» adds and removes one, a period changes the numbers
await step('dashboard', async () => {
  await page.evaluate(() => switchAppView('dashboard'));
  await sleep(1200);
  expect(await page.isVisible('#dashboard-view'), 'the dashboard did not open');
  expect(await page.locator('#db-grid .db-w').count() >= 8, 'the widgets are missing');
  expect(await page.isVisible('#db-hello .hm-greeting'), 'the greeting did not move to the dashboard');
  await page.click('#db-edit-btn');
  await sleep(200);
  const before = await page.locator('#db-grid .db-w').count();
  await page.click('#db-grid .db-w .db-x >> nth=0');
  expect(await page.locator('#db-grid .db-w').count() === before - 1, 'a widget was not removed');
  await page.click('#db-drawer .db-lib-add >> nth=0');
  expect(await page.locator('#db-grid .db-w').count() === before, 'a widget was not added');
  await page.click('#db-drawer button:has-text("Вернуть как было")');
  await page.click('#db-edit-btn');
  await page.click('#db-periods button >> nth=1');
  await sleep(600);
  expect((await page.textContent('#db-sub')).startsWith('Месяц'), 'the period did not change');
  await page.click('#db-periods button >> nth=0');
  await sleep(300);
});

await browser.close();
if (errors.length) {
  console.error(errors.join('\n'));
  process.exit(1);
}
console.log('UI scenarios passed');
