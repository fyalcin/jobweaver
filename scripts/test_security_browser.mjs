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
from demo_data import seed
seed(Path(os.environ['JOBWEAVER_DATA_DIR']))
# Give the fictional job a supported Typst CV for its Simple Mode editor.
draft = Path(os.environ['JOBWEAVER_DATA_DIR']) / 'profiles/demo/drafts/CumulusResearch_demo_01'
(draft / 'cv_demo_01.typ').write_text(Path('base-typst/base-cv.typ').read_text())
(draft / 'sources.json').write_text('{"cv":"typ"}')
import auth, db, user_assets
db.create_user('fresh', auth.hash_password('fictional-fresh-password'))
user_assets.ensure_user_dirs('fresh')
import requests, urllib.request, safe_fetch
def denied(*args, **kwargs):
    raise RuntimeError('Outbound HTTP disabled in disposable browser fixture')
requests.sessions.Session.send = denied
urllib.request.urlopen = denied
safe_fetch.fetch_page = denied
import uvicorn
uvicorn.run('server:app', host='127.0.0.1', port=int(sys.argv[1]))
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
  assert.equal(await experienceSection.locator('.simple-section-body').count(), 0);
  await experienceHeader.click();
  await experienceSection.locator('.simple-section-body').waitFor({ timeout: 3000 });
  await experienceHeader.click();
  await experienceSection.locator('.simple-section-body').waitFor({ state: 'detached' });
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
  await page.getByText('Live WASM', { exact: true }).waitFor();
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
