// Own disposable demo only. Synthetic responses exercise states absent from the prepared examples.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import http from 'node:http';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve, join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = resolve(import.meta.dirname, '..');
const output = join(root, 'output/match-rating-ui');
const probe = http.createServer();
await new Promise(done => probe.listen(0, '127.0.0.1', done));
const port = probe.address().port;
await new Promise(done => probe.close(done));
const base = `http://127.0.0.1:${port}`;
const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !/TOKEN|SECRET|PASSWORD|API_KEY/i.test(key) && !key.startsWith('JOBWEAVER_')));
Object.assign(env, { PYTHON_DOTENV_DISABLED: '1', PYTHONDONTWRITEBYTECODE: '1' });
const child = spawn(join(root, '.venv/bin/python'), ['scripts/demo.py', '--port', String(port)], { cwd: root, env });
let logs = '', browser, page;
child.stdout.on('data', value => { logs = (logs + value).slice(-8000); });
child.stderr.on('data', value => { logs = (logs + value).slice(-8000); });
child.on('error', error => { logs += error.message; });
try {
  const deadline = Date.now() + 30000;
  while (true) {
    try { if ((await fetch(`${base}/api/demo`)).ok) break; } catch {}
    if (child.exitCode !== null || Date.now() > deadline) throw Error(`Demo did not start: ${logs}`);
    await delay(100);
  }
  assert.equal((await (await fetch(`${base}/api/demo`)).json()).demo, true);
  browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
  await context.addInitScript(() => localStorage.setItem('jobweaver.jobs-view.demo', JSON.stringify({ statusFilter: 'All', scrapeDateFilter: '__all', minMatchFilter: '85', sortConfig: { key: 'match_score', direction: 'desc' } })));
  let original, fixture;
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== base && !['data:', 'blob:'].includes(url.protocol)) return route.abort();
    if (url.pathname === '/api/jobs' && route.request().method() === 'GET') {
      original ||= await (await route.fetch()).json();
      const template = original.find(job => job.company === 'Cumulus Research') || original[0];
      const check = (requirement, coverage, importance = 'must') => ({ requirement, coverage, importance, posting_quote: `${requirement} required.`, cv_quote: coverage === 'missing' ? '' : `I used ${requirement}.` });
      fixture ||= ['Great', 'Good', 'Decent', 'Stretch', 'Poor', 'Blocked', 'Legacy', 'Unrated', 'Failed', 'Good', 'Good', 'Good'].map((rating, index) => ({ ...template, id: index === 0 ? template.id : `test-${index}`, title: `${rating} role ${index}`, company: `Fictional company ${index}`, date_scraped: '2026-10-28', status: ['new', 'interested', 'applied', 'interview', 'offer', 'rejected', 'new', 'not_interested', 'new', 'new', 'new', 'new'][index], applied: false, match_rating: ['Legacy', 'Failed'].includes(rating) ? null : rating, match_score: rating === 'Legacy' ? 99 : null, analysis_state: rating === 'Failed' ? 'failed' : 'complete', analysis_current: rating === 'Legacy' ? false : true, analysis_error: rating === 'Failed' ? 'Add your CV' : null, match_checks: ['Legacy', 'Unrated', 'Failed'].includes(rating) ? [] : [check('SQL', rating === 'Great' || rating === 'Good' ? 'shown' : 'missing'), check('Python', rating === 'Good' ? 'related' : rating === 'Poor' ? 'missing' : 'shown'), check('Git', 'related')], preference_conflicts: index === 3 ? [{ preference: 'Work location', notes_quote: 'I prefer Vienna.', posting_quote: 'Work in Linz.', severity: 'soft' }] : [], judgement_calls: ['Legacy', 'Unrated', 'Failed'].includes(rating) ? [] : [{ requirement: 'Git', if_missing: 'Stretch' }], cv_url: index === 0 ? template.cv_url : null, letter_url: index === 0 ? template.letter_url : null }));
      return route.fulfill({ json: fixture });
    }
    return route.continue();
  });
  page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(base);
  await page.getByRole('button', { name: 'Explore the demo' }).click();
  const rows = page.locator('.calm-job-row');
  await rows.first().waitFor();
  assert.equal(await page.getByRole('region', { name: 'Great jobs', exact: true }).locator('.calm-job-row').count(), 1);
  assert.equal(await page.getByRole('region', { name: 'Poor jobs', exact: true }).locator('.calm-job-row').count(), 0);
  await page.getByRole('button', { name: /^Poor 1$/ }).click();
  assert.equal(await page.getByRole('region', { name: 'Poor jobs', exact: true }).locator('.calm-job-row').count(), 1);
  await page.getByRole('button', { name: /^Blocked 1$/ }).click();
  assert.equal(await rows.count(), 12);
  assert.equal(await page.locator('.calm-batch-bar').count(), 0);
  await page.getByRole('checkbox', { name: 'Select Great role 0', exact: true }).check();
  await page.locator('.calm-batch-bar').waitFor();
  assert.equal(await page.locator('.job-detail-page').count(), 0, 'Selecting a row must not open it.');
  await page.getByRole('button', { name: 'Clear selection', exact: true }).click();
  assert.equal(await page.locator('.calm-batch-bar').count(), 0);
  await page.getByRole('button', { name: 'Actions for Great role 0', exact: true }).click();
  const menu = page.locator('.calm-row-menu');
  assert.equal(await menu.getByRole('link', { name: 'Download CV', exact: true }).count(), 1);
  for (const name of ['Edit job', 'Generate CV', 'Rate again', 'Delete job']) assert(await menu.getByRole('button', { name, exact: true }).isDisabled());
  assert.equal(await page.locator('.job-detail-page').count(), 0, 'Opening actions must not open the job.');
  await page.keyboard.press('Escape');
  assert.equal(await menu.count(), 0);
  assert(await page.getByRole('button', { name: 'Actions for Great role 0', exact: true }).evaluate(node => node === document.activeElement));
  await page.getByRole('button', { name: 'Actions for Good role 1', exact: true }).click();
  await page.getByRole('heading', { name: 'Jobs', exact: true }).click();
  assert.equal(await menu.count(), 0, 'Outside click closes the actions.');
  await page.getByRole('button', { name: /^Applied 4$/ }).click();
  assert.equal(await rows.count(), 4, 'Applied stage includes all pipeline statuses.');
  await page.getByRole('button', { name: /^All 12$/ }).click();
  await page.getByRole('button', { name: 'Filter', exact: true }).click();
  await page.getByLabel('Minimum rating', { exact: true }).selectOption('Good');
  assert.equal(await rows.count(), 5);
  await page.getByRole('button', { name: 'Remove Rating: Good or better', exact: true }).click();
  await page.getByRole('textbox', { name: 'Search jobs', exact: true }).fill('Legacy');
  assert.equal(await rows.count(), 1);
  assert.match(await rows.textContent(), /Needs re-rating/);
  assert(!/99|Strong Match|\/100/.test(await rows.textContent()));
  await rows.focus(); await page.keyboard.press('Enter');
  await page.getByRole('heading', { name: 'Match evidence', exact: false }).waitFor();
  assert.match(await page.locator('.match-evidence').textContent(), /No evidence checklist/);
  assert(await page.getByRole('button', { name: 'Re-rate', exact: true }).isDisabled());
  await page.getByRole('button', { name: 'Back to Jobs' }).click();
  await page.getByRole('textbox', { name: 'Search jobs', exact: true }).fill('Unrated');
  await rows.click();
  assert.match(await page.locator('.match-evidence').textContent(), /no checkable requirements/i);
  assert(!/historical|Analysis pending/.test(await page.locator('.match-evidence').textContent()));
  await page.getByRole('button', { name: 'Back to Jobs' }).click();
  await page.getByRole('textbox', { name: 'Search jobs', exact: true }).fill('Stretch');
  await rows.focus(); await page.keyboard.press('Space');
  await page.locator('.evidence-checklist').waitFor();
  assert.deepEqual(await page.locator('.evidence-coverage-pill').evaluateAll(els => els.map(el => el.dataset.coverage)), ['missing', 'related', 'shown']);
  assert.match(await page.locator('.match-evidence').textContent(), /I used Git\./);
  assert.match(await page.locator('.match-evidence').textContent(), /I prefer Vienna\./);
  assert.match(await page.locator('.match-evidence').textContent(), /would be Stretch/);
  await page.getByRole('button', { name: 'Back to Jobs' }).click();
  await page.getByRole('textbox', { name: 'Search jobs', exact: true }).fill('');
  await page.getByRole('button', { name: 'Filter', exact: true }).click();
  await page.getByRole('button', { name: 'Dark', exact: true }).click();
  await mkdir(output, { recursive: true });
  await page.screenshot({ path: join(output, 'behavior-dark.png'), animations: 'disabled' });
  await page.getByRole('button', { name: 'Light', exact: true }).click();
  await page.screenshot({ path: join(output, 'behavior-light.png'), animations: 'disabled' });
  for (const width of [320, 390]) {
    await page.setViewportSize({ width, height: 844 });
    const search = page.getByRole('textbox', { name: 'Search jobs', exact: true });
    await search.focus();
    await delay(250); // Focus styles transition for 200ms; inspect the settled indicator.
    const focus = await search.evaluate(element => {
      const style = getComputedStyle(element), bounds = element.getBoundingClientRect();
      const outlineWidth = parseFloat(style.outlineWidth);
      const outset = Math.max(0, outlineWidth + parseFloat(style.outlineOffset));
      const clips = [];
      for (let parent = element.parentElement; parent; parent = parent.parentElement) {
        if (['auto', 'scroll', 'hidden', 'clip'].includes(getComputedStyle(parent).overflowX)) {
          const box = parent.getBoundingClientRect();
          clips.push({ left: box.left + parent.clientLeft, right: box.left + parent.clientLeft + parent.clientWidth });
        }
      }
      return { outlineWidth, left: bounds.left - outset, right: bounds.right + outset, clips };
    });
    assert(focus.outlineWidth >= 2, 'The search field must retain a visible focus indicator.');
    assert(focus.clips.every(clip => focus.left >= clip.left && focus.right <= clip.right),
      `Search focus outline is clipped at ${width}px: ${JSON.stringify(focus)}`);
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Mobile list overflows horizontally.');
  }
  await page.screenshot({ path: join(output, 'behavior-mobile.png'), animations: 'disabled' });
  assert.deepEqual(errors, []);
  await writeFile(join(output, 'behavior-verification.json'), JSON.stringify({ localDisposableDemo: true, syntheticResponseStates: true, groupedRatings: true, legacyNotConverted: true, noRequirements: true, stagePipeline: true, thresholdFilter: true, rowKeyboard: true, selectionIsolation: true, overflowDownloads: true, demoWriteGuards: true, escapeAndOutsideClose: true, evidenceOrderAndQuotes: true, mobileNoOverflow: true, errors }, null, 2));
  console.log(`Rating browser regressions passed. Evidence: ${output}`);
} catch (error) {
  await mkdir(output, { recursive: true });
  if (page) {
    await page.screenshot({ path: join(output, 'behavior-failure.png') }).catch(() => {});
    await writeFile(join(output, 'behavior-failure.html'), await page.content()).catch(() => {});
  }
  throw error;
} finally {
  await browser?.close();
  child.kill('SIGTERM');
  await new Promise(done => { if (child.exitCode !== null) return done(); child.once('exit', done); });
  await mkdir(output, { recursive: true });
  await writeFile(join(output, 'behavior-demo-server.log'), logs);
}
