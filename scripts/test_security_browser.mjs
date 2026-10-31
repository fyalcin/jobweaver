// Start our own fictional instance. Never accepts a URL for an existing deployment.
// Requires an installed Playwright and Chromium (as does capture_demo.mjs).
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import http from 'node:http';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = resolve(import.meta.dirname, '..');
const data = await mkdtemp(join(tmpdir(), 'jobweaver-browser-security-'));
const probe = http.createServer();
await new Promise(done => probe.listen(0, '127.0.0.1', done));
const port = probe.address().port;
await new Promise(done => probe.close(done));
const base = `http://127.0.0.1:${port}`;
const env = Object.fromEntries(Object.entries(process.env).filter(([key]) =>
  !/TOKEN|SECRET|PASSWORD|API_KEY/i.test(key) && !key.startsWith('JOBWEAVER_')));
Object.assign(env, { JOBWEAVER_DATA_DIR: data, PYTHON_DOTENV_DISABLED: '1', PYTHONDONTWRITEBYTECODE: '1' });
const fixture = `
import os, sys
from pathlib import Path
from jobweaver.demo_data import seed
seed(Path(os.environ['JOBWEAVER_DATA_DIR']))
# Give the fictional job a supported Typst CV for its Simple Mode editor.
draft = Path(os.environ['JOBWEAVER_DATA_DIR']) / 'profiles/demo/drafts/CumulusResearch_demo_01'
(draft / 'cv_demo_01.typ').write_text(Path('base-typst/base-cv.typ').read_text())
(draft / 'sources.json').write_text('{"cv":"typ"}')
from jobweaver import auth, db, user_assets
db.create_user('fresh', auth.hash_password('fictional-fresh-password'))
user_assets.ensure_user_dirs('fresh')
import requests, urllib.request
from jobweaver import safe_fetch
def denied(*args, **kwargs):
    raise RuntimeError('Outbound HTTP disabled in disposable browser fixture')
requests.sessions.Session.send = denied
urllib.request.urlopen = denied
safe_fetch.fetch_page = denied
import uvicorn
uvicorn.run('jobweaver.server:app', host='127.0.0.1', port=int(sys.argv[1]))
`;
const child = spawn(join(root, '.venv/bin/python'), ['-c', fixture, String(port)], { cwd: root, env });
let serverLog = '';
let spawnFailed = false;
child.on('error', error => { serverLog = error.message; spawnFailed = true; });
child.stdout.on('data', value => { serverLog = (serverLog + value).slice(-5000); });
child.stderr.on('data', value => { serverLog = (serverLog + value).slice(-5000); });
const output = join(root, 'output/security-browser');
let browser, attacker, page;
const errors = [];
try {
  const deadline = Date.now() + 30000;
  while (true) {
    try { if ((await fetch(`${base}/api/demo`)).ok) break; } catch { /* Wait for our child only. */ }
    if (spawnFailed || child.exitCode !== null || Date.now() > deadline) throw new Error(`Fixture failed: ${serverLog}`);
    await delay(100);
  }
  browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
  page = await context.newPage();
  page.on('pageerror', error => errors.push(error.stack || error.message));
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    return ['127.0.0.1', 'localhost'].includes(url.hostname) || ['data:', 'blob:'].includes(url.protocol)
      ? route.continue() : route.abort();
  });
  const login = async (username, password) => {
    await page.getByLabel('Username', { exact: true }).fill(username);
    await page.getByLabel('Password', { exact: true }).fill(password);
    await page.getByRole('button', { name: 'Sign in', exact: true }).click();
    await page.getByRole('button', { name: 'Jobs', exact: true }).waitFor();
  };
  let releaseOldRequest;
  await page.route('**/api/profile/notes', async route => {
    if (!releaseOldRequest) {
      await new Promise(done => {
        releaseOldRequest = async () => {
          await route.fulfill({ status: 401, contentType: 'application/json', body: '{"detail":"Expired old session"}' });
          done();
        };
      });
    } else await route.continue();
  });
  await page.goto(base);
  await login('fresh', 'fictional-fresh-password');
  await page.getByRole('button', { name: 'Add Job', exact: true }).click();
  await page.locator('textarea').fill('PRIVATE FICTIONAL DRAFT FROM FIRST USER');
  await page.getByRole('button', { name: 'Sign out', exact: true }).click();
  await login('demo', 'demo');
  await page.getByRole('button', { name: 'Add Job', exact: true }).click();
  assert.equal(await page.locator('textarea').inputValue(), '', 'A different user inherited a draft');
  assert(releaseOldRequest, 'Expected to hold the old session request');
  await releaseOldRequest();
  await delay(250);
  assert.equal(await page.getByRole('button', { name: 'Jobs', exact: true }).count(), 1,
    'An old session response signed the new user out');

  await page.getByRole('button', { name: 'Jobs', exact: true }).click();
  await page.getByRole('button', { name: /^All \d+$/ }).click();
  await page.locator('.calm-job-company').filter({ hasText: 'Cumulus Research' }).click();
  await page.getByRole('tab', { name: 'Tailor Studio', exact: true }).click();
  await page.locator('.simple-editor-container').waitFor();
  const experienceSection = page.locator('.simple-section-card').filter({
    has: page.locator('.simple-section-header').filter({ hasText: /Experience/i }),
  });
  const experienceHeader = experienceSection.locator('.simple-section-header');
  assert.equal(await experienceSection.locator('.simple-section-body').count(), 1);
  await experienceHeader.click();
  await experienceSection.locator('.simple-section-body').waitFor({ state: 'detached' });
  await experienceHeader.click();
  await experienceSection.locator('.simple-section-body').waitFor({ timeout: 3000 });

  // Typst has no autosave here and Finalize needs a saved build: Compile must stay reachable until built.
  const jobCompile = page.locator('.job-studio-container .studio-btn-compile');
  // The default template has no subtitle yet: adding one must stay in Simple Mode and still build natively.
  const subtitleField = page.locator('.simple-editor-container input.input-base').nth(1);
  assert.equal(await subtitleField.inputValue(), '');
  await subtitleField.fill('Atmospheric Data Scientist');
  assert.equal(await subtitleField.inputValue(), 'Atmospheric Data Scientist');
  await jobCompile.waitFor();

  // The form stays editable during a compile, and newer typing still counts as unbuilt afterwards.
  let releaseHeldBuild;
  const heldBuild = new Promise(done => { releaseHeldBuild = done; });
  await page.route('**/documents/compile', async route => {
    const response = await route.fetch();
    await heldBuild;
    await route.fulfill({ response });
  });
  const startedBuild = page.waitForRequest(request => new URL(request.url()).pathname.endsWith('/documents/compile'));
  const finishedBuild = page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/documents/compile'));
  await jobCompile.click();
  await startedBuild;
  assert(await subtitleField.isEnabled(), 'The form must stay editable during a compile.');
  await subtitleField.fill('Climate Data Scientist');
  releaseHeldBuild();
  await finishedBuild;
  await page.unroute('**/documents/compile');
  await page.waitForFunction(() => !document.querySelector('.job-studio-container .studio-btn-compile')?.disabled);
  assert.equal(await subtitleField.inputValue(), 'Climate Data Scientist', 'Typing during a compile was lost.');
  assert(await jobCompile.isVisible(), 'Text typed during a compile still needs building.');

  const builtDraft = page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/documents/compile'));
  await jobCompile.click();
  assert.equal((await (await builtDraft).json()).success, true);
  await jobCompile.waitFor({ state: 'hidden' });
  const finalized = page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/documents/finalize'));
  await page.locator('.studio-btn-save-final').click();
  assert.equal((await finalized).status(), 200, 'A built Typst draft must finalize.');
  // A failed finalize must say why and offer Compile, including in Editor view on a phone.
  await page.route('**/documents/finalize', route => route.fulfill({ status: 409, contentType: 'application/json', body: '{"detail":"cv: unsaved changes. Compile this version first."}' }));
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('.studio-btn-save-final').click();
  await page.locator('.studio-error-card').waitFor();
  await jobCompile.waitFor();
  await page.unroute('**/documents/finalize');
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.getByRole('button', { name: 'Back to Jobs' }).click();

  assert.equal((await context.request.put(`${base}/api/config`, { data: {
    document_model: 'custom/fictional-local-model', letter_verifier_model: null,
  } })).status(), 200);
  await page.reload();
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByLabel('Letter verification model').waitFor();
  await page.waitForFunction(() => document.querySelector('#letter-verifier-model option:checked')?.textContent.includes('custom/fictional-local-model'));
  assert.match(await page.getByLabel('Letter verification model').locator('option:checked').innerText(), /custom\/fictional-local-model/);

  const docs = [];
  for (const [engine, content] of [
    ['latex', '\\documentclass{article}\\begin{document}Fictional LaTeX CV\\end{document}'],
    ['typst', '#set page(paper: "a4")\n= Fictional Typst CV\nSafe browser fixture.'],
  ]) {
    const response = await context.request.post(`${base}/api/documents`, { data: {
      title: `Fictional ${engine} CV`, engine, content,
    } });
    assert.equal(response.status(), 200);
    const document = await response.json();
    assert.equal(document.has_pdf, true, JSON.stringify(document.error));
    const pdf = await context.request.get(`${base}${document.pdf_url}`);
    assert((await pdf.body()).subarray(0, 5).equals(Buffer.from('%PDF-')));
    docs.push(document);
  }
  await page.getByRole('button', { name: 'CV Library', exact: true }).click();
  await page.getByRole('combobox', { name: 'Select active studio document' }).selectOption(docs[1].id);
  await page.getByRole('toolbar', { name: 'PDF preview zoom and pages' }).waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  assert(await page.locator('.studio-btn-delete-mobile').isVisible(), 'Phones must be able to delete a CV.');
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.locator('.typst-page-card svg').waitFor();

  // Editing during a real native compile must leave the newer draft saveable.
  await page.getByRole('combobox', { name: 'Select active studio document' }).selectOption(docs[0].id);
  const editor = page.locator('.studio-textarea');
  await editor.waitFor();
  await page.waitForFunction(() => document.querySelector('.studio-textarea')?.value.includes('Fictional LaTeX CV'));
  const originalSource = await editor.inputValue();
  const compilePath = `/api/documents/${docs[0].id}/compile`;
  let releaseCompile, compileSaved;
  const savedCompile = new Promise(done => { compileSaved = done; });
  await page.route(`**${compilePath}`, async route => {
    const response = await route.fetch();
    await new Promise(release => { releaseCompile = release; compileSaved(); });
    await route.fulfill({ response });
  });
  await editor.fill(originalSource.replace('Fictional LaTeX CV', 'Compiled fictional CV'));
  await editor.press('Control+Enter');
  await Promise.race([savedCompile, delay(30000, undefined, { ref: false }).then(() => { throw Error('Native compile did not reach the response gate.'); })]);
  const newerSource = originalSource.replace('Fictional LaTeX CV', 'Newer typing after compile started');
  await editor.fill(newerSource);
  releaseCompile();
  await page.waitForFunction(() => {
    const button = [...document.querySelectorAll('button')].find(node => node.title.includes('Recompile document'));
    return button && !button.disabled;
  });
  const savedDraft = page.waitForResponse(response => response.request().method() === 'PUT'
    && new URL(response.url()).pathname === `/api/documents/${docs[0].id}`);
  await editor.press('Control+s');
  assert.equal((await savedDraft).status(), 200, 'Newer typing became unsaveable after compilation.');
  const persisted = await (await context.request.get(`${base}/api/documents/${docs[0].id}`)).json();
  assert.equal(persisted.content, newerSource);
  await page.unroute(`**${compilePath}`);

  // Failed native builds also save source; repairing that source must still work.
  const invalidSource = originalSource.replace('\\begin{document}', '\\begin{document}\\DefinitelyUndefinedCommand');
  await editor.fill(invalidSource);
  const failedCompile = page.waitForResponse(response => new URL(response.url()).pathname === compilePath);
  await editor.press('Control+Enter');
  assert.equal((await (await failedCompile).json()).success, false);
  await page.waitForFunction(() => {
    const button = [...document.querySelectorAll('button')].find(node => node.title.includes('Recompile document'));
    return button && !button.disabled;
  });
  await editor.fill(newerSource);
  const repairedDraft = page.waitForResponse(response => response.request().method() === 'PUT'
    && new URL(response.url()).pathname === `/api/documents/${docs[0].id}`);
  await editor.press('Control+s');
  assert.equal((await repairedDraft).status(), 200, 'A failed build left the repaired source unsaveable.');
  await page.getByRole('combobox', { name: 'Select active studio document' }).selectOption(docs[1].id);
  await page.locator('.typst-page-card svg').waitFor();

  attacker = http.createServer((_, response) => {
    response.setHeader('Content-Type', 'text/html');
    response.end('<!doctype html><title>Fictional foreign origin</title>');
  });
  await new Promise(done => attacker.listen(0, '127.0.0.1', done));
  const otherOrigin = `http://127.0.0.1:${attacker.address().port}`;
  assert.equal((await context.request.get(`${base}/api/cv`, { headers: { Origin: otherOrigin } })).status(), 403);
  const foreignPage = await context.newPage();
  await foreignPage.goto(otherOrigin);
  const readable = await foreignPage.evaluate(async target => {
    try { const response = await fetch(`${target}/api/cv`, { credentials: 'include' }); return response.ok; }
    catch { return false; }
  }, base);
  assert.equal(readable, false, 'Another local browser origin read private CV data');
  assert.equal((await context.request.get(`${base}/api/auth/me`, { headers: { Host: 'foreign.invalid' } })).status(), 400);
  await foreignPage.close();

  await mkdir(output, { recursive: true });
  await page.screenshot({ path: join(output, 'typst-library.png'), animations: 'disabled' });
  assert.deepEqual(errors, []);
  const result = { accountDraftIsolation: true, explicitVerifierRoute: true,
    oldSessionResponseIsolation: true,
    jobSimpleModeSections: true,
    jobTypstCompileThenFinalize: true,
    formEditableDuringCompile: true,
    editsDuringCompileRemainSaveable: true,
    failedCompileCanBeRepaired: true,
    isolatedLatexAndTypstPdf: true, browserTypstPreview: true, hostileOriginBlocked: true,
    hostileHostBlocked: true, uncaughtErrors: errors, fictionalDataOnly: true };
  await writeFile(join(output, 'verification.json'), JSON.stringify(result, null, 2));
  await rm(join(output, 'failure.json'), { force: true });
  console.log(JSON.stringify(result));
} catch (error) {
  await mkdir(output, { recursive: true });
  await writeFile(join(output, 'failure.json'), JSON.stringify({ message: error.message, errors,
    text: page ? await page.locator('body').innerText().catch(() => '') : '', serverLog }, null, 2));
  throw error;
} finally {
  if (browser) await browser.close();
  if (attacker) await new Promise(done => attacker.close(done));
  if (!spawnFailed && child.exitCode === null && child.signalCode === null) {
    const stopped = new Promise(done => child.once('close', done));
    child.kill('SIGTERM');
    await Promise.race([stopped, delay(3000)]);
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL');
    await stopped;
  }
  await rm(data, { recursive: true, force: true });
}
