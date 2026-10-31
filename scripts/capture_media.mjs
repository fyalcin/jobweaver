// Record the README clips from our own disposable fictional instances. Never accepts an existing deployment.
// Usage: node scripts/capture_media.mjs OUTPUT_DIR. Needs ffmpeg, Playwright and Chromium (as capture_demo.mjs).
// Frames are screenshots placed on a fixed timeline, so text stays sharp and the pace does not depend on the machine.
import { spawn, execFileSync } from 'node:child_process';
import http from 'node:http';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = resolve(import.meta.dirname, '..');
const output = resolve(process.argv[2] || 'output/release-media');
await mkdir(output, { recursive: true });

const FRAME = 1 / 15;
const TYPE_FRAMES = 2;
const env = Object.fromEntries(Object.entries(process.env).filter(([key]) =>
  !/TOKEN|SECRET|PASSWORD|API_KEY/i.test(key) && !key.startsWith('JOBWEAVER_')));
Object.assign(env, { PYTHON_DOTENV_DISABLED: '1', PYTHONDONTWRITEBYTECODE: '1' });

const freePort = async () => {
  const probe = http.createServer();
  await new Promise(done => probe.listen(0, '127.0.0.1', done));
  const { port } = probe.address();
  await new Promise(done => probe.close(done));
  return port;
};

async function withServer(args, extraEnv, run) {
  const port = await freePort();
  const child = spawn(join(root, '.venv/bin/python'), args(port), { cwd: root, env: { ...env, ...extraEnv }, stdio: 'ignore' });
  const base = `http://127.0.0.1:${port}`;
  try {
    const deadline = Date.now() + 30000;
    while (true) {
      try { if ((await fetch(`${base}/api/demo`)).ok) break; } catch { /* Wait for our child only. */ }
      if (child.exitCode !== null || Date.now() > deadline) throw new Error('The disposable instance did not start.');
      await delay(100);
    }
    await run(base);
  } finally {
    child.kill('SIGTERM');
    await new Promise(done => { if (child.exitCode !== null) return done(); child.once('exit', done); });
  }
}

async function record(browser, base, name, script) {
  const frames = await mkdtemp(join(tmpdir(), `jobweaver-${name}-`));
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 } });
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    return url.origin === base || ['data:', 'blob:'].includes(url.protocol) ? route.continue() : route.abort();
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const timeline = [];
  const shot = async (count = 1) => {
    const file = join(frames, `${String(timeline.length).padStart(5, '0')}.png`);
    await page.screenshot({ path: file, animations: 'disabled', caret: 'initial' });
    timeline.push({ file, seconds: count * FRAME });
  };
  const hold = seconds => shot(Math.round(seconds / FRAME));
  const type = async (locator, text) => {
    await locator.focus();
    for (const key of text) {
      await page.keyboard.type(key);
      await shot(TYPE_FRAMES);
    }
  };
  const replace = async (locator, text) => {
    await locator.fill('');
    await shot(3);
    await type(locator, text);
  };
  const scrollTo = async (target, seconds) => {
    const steps = Math.round(seconds / FRAME);
    const start = await page.evaluate(() => window.scrollY);
    for (let step = 1; step <= steps; step++) {
      const eased = 0.5 - Math.cos(Math.PI * step / steps) / 2;
      await page.evaluate(top => window.scrollTo({ top, behavior: 'instant' }), start + (target - start) * eased);
      await shot();
    }
  };
  try {
    await script({ page, context, hold, shot, type, replace, scrollTo });
    if (errors.length) throw new Error(`${name}: ${errors.join('; ')}`);
    const list = timeline.map(({ file, seconds }) => `file '${file}'\nduration ${seconds.toFixed(4)}`).join('\n');
    const concat = join(frames, 'frames.txt');
    await writeFile(concat, `${list}\nfile '${timeline.at(-1).file}'\n`);
    const input = ['-y', '-loglevel', 'error', '-f', 'concat', '-safe', '0', '-i', concat];
    execFileSync('ffmpeg', [...input, '-vf', 'fps=30,format=yuv420p', '-c:v', 'libx264', '-preset', 'slow', '-crf', '20',
      '-movflags', '+faststart', join(output, `${name}.mp4`)]);
    execFileSync('ffmpeg', [...input, '-vf',
      'fps=15,split[a][b];[a]palettegen=stats_mode=diff:max_colors=96[p];[b][p]paletteuse=dither=none:diff_mode=rectangle',
      join(output, `${name}.gif`)]);
  } finally {
    await context.close();
    await rm(frames, { recursive: true, force: true });
  }
}

const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
try {
  await withServer(port => ['scripts/demo.py', '--port', String(port)], {}, base => record(browser, base, 'hero', async ({ page, hold, type, scrollTo }) => {
    await page.goto(base);
    await page.getByRole('button', { name: 'Explore the demo' }).click();
    await page.locator('.calm-job-row').first().waitFor();
    await page.getByRole('button', { name: /^All \d+$/ }).click();
    await delay(300);
    await hold(1.4);
    await type(page.getByRole('textbox', { name: 'Search jobs' }), 'Cumulus');
    await hold(1);
    await page.locator('.calm-job-company').filter({ hasText: 'Cumulus Research' }).click();
    await page.locator('.job-hero-card').waitFor();
    await delay(300);
    await hold(1.6);
    const evidence = await page.locator('.match-evidence').evaluate(node => node.getBoundingClientRect().bottom + window.scrollY - window.innerHeight + 24);
    await scrollTo(Math.max(0, evidence), 2.6);
    await hold(1.4);
    await scrollTo(0, 1);
    await page.getByRole('tab', { name: 'Tailor Studio', exact: true }).click();
    await page.locator('.demo-document-page').first().waitFor();
    await delay(600);
    await hold(2.4);
  }));

  const data = await mkdtemp(join(tmpdir(), 'jobweaver-media-'));
  const fixture = `
import os, sys
from pathlib import Path
from jobweaver.demo_data import seed
seed(Path(os.environ['JOBWEAVER_DATA_DIR']))
import requests, urllib.request
from jobweaver import safe_fetch
def denied(*args, **kwargs):
    raise RuntimeError('Outbound HTTP disabled in disposable media fixture')
requests.sessions.Session.send = denied
urllib.request.urlopen = denied
safe_fetch.fetch_page = denied
import uvicorn
uvicorn.run('jobweaver.server:app', host='127.0.0.1', port=int(sys.argv[1]))
`;
  try {
    await withServer(port => ['-c', fixture, String(port)], { JOBWEAVER_DATA_DIR: data }, base => record(browser, base, 'cv-studio', async ({ page, context, hold, replace }) => {
      await page.goto(base);
      await page.getByLabel('Username', { exact: true }).fill('demo');
      await page.getByLabel('Password', { exact: true }).fill('demo');
      await page.getByRole('button', { name: 'Sign in', exact: true }).click();
      await page.getByRole('button', { name: 'Jobs', exact: true }).waitFor();
      const content = await readFile(join(root, 'base-typst/base-cv-moderner.typ'), 'utf8');
      const created = await context.request.post(`${base}/api/documents`, { data: { title: 'Research Software CV', engine: 'typst', content } });
      if (!created.ok()) throw new Error(`Could not create the sample CV: ${created.status()}`);
      await page.getByRole('button', { name: 'CV Library', exact: true }).click();
      await page.locator('.simple-editor-container').waitFor();
      await page.locator('.typst-page-card svg').first().waitFor({ timeout: 30000 });
      await delay(500);
      await hold(1.6);
      const fields = page.locator('.simple-editor-container input.input-base');
      await replace(fields.nth(0), 'Alex Example, PhD');
      await delay(1200);
      await hold(1.2);
      await replace(fields.nth(1), 'Atmospheric Data Scientist');
      await delay(1200);
      await hold(1.2);
      await page.locator('.studio-jumpbar-link').filter({ hasText: 'Experience' }).click();
      await delay(900);
      await hold(1);
      const experience = page.locator('.simple-section-card').filter({ has: page.locator('.simple-section-header').filter({ hasText: /Experience/i }) });
      await replace(experience.locator('input.input-base').first(), 'Lead Climate Programmer');
      await delay(1200);
      await hold(2.4);
    }));
  } finally {
    await rm(data, { recursive: true, force: true });
  }
} finally {
  await browser.close();
}
console.log(`Clips written to ${output}`);
