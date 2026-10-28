// Capture only the disposable demo. Requires an installed Playwright package and Chromium.
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.DEMO_URL || 'http://127.0.0.1:8001';
const output = resolve(process.argv[2] || 'output/release-media');
assert(['127.0.0.1', 'localhost'].includes(new URL(base).hostname), 'Capture only a local demo.');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 960 }, deviceScaleFactor: 1 });
  // Verify the demo also works without external fonts or other internet resources.
  const external = [];
  await context.route('**/*', route => {
    const url = new URL(route.request().url());
    if (url.origin === new URL(base).origin || ['data:', 'blob:'].includes(url.protocol)) return route.continue();
    external.push(url.origin);
    return route.abort();
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const demo = await (await context.request.get(`${base}/api/demo`)).json();
  assert.equal(demo.demo, true, 'Refuse to capture a normal instance.');
  await page.goto(base);
  await page.getByRole('button', { name: 'Explore the demo' }).click();
  await page.locator('.calm-job-company').filter({ hasText: 'Cumulus Research' }).waitFor();
  await page.getByRole('button', { name: /^All \d+$/ }).click();
  await page.getByRole('button', { name: /^Actions for/ }).first().click();
  assert.equal(await page.getByRole('button', { name: 'Edit job', exact: true }).isDisabled(), true);
  assert.equal(await page.getByRole('button', { name: 'Generate CV', exact: true }).isDisabled(), true);
  await page.keyboard.press('Escape');
  await page.screenshot({ animations: 'disabled', path: `${output}/01-jobs.png` });
  await page.getByRole('textbox', { name: 'Search jobs' }).fill('Cumulus');
  assert.equal(await page.locator('.calm-job-row').count(), 1);
  await page.locator('.calm-job-company').filter({ hasText: 'Cumulus Research' }).click();
  await page.getByText('Your Match Analysis', { exact: true }).waitFor();
  await page.screenshot({ animations: 'disabled', path: `${output}/02-fit.png` });
  await page.getByRole('tab', { name: 'Tailor Studio' }).click();
  await page.getByRole('heading', { name: 'Prepared application' }).waitFor();
  await page.locator('.demo-document-page').first().waitFor();
  await page.screenshot({ animations: 'disabled', path: `${output}/03-evidence.png` });
  const pdf = await context.request.get(`${base}${await page.getByRole('link', { name: 'Download PDF', exact: true }).getAttribute('href')}`);
  assert.equal(pdf.status(), 200);
  assert((await pdf.body()).subarray(0, 5).equals(Buffer.from('%PDF-')));
  await page.locator('.demo-document-page').first().scrollIntoViewIfNeeded();
  await page.screenshot({ animations: 'disabled', path: `${output}/04-letter.png` });
  await page.getByRole('button', { name: 'CV', exact: true }).click();
  await page.locator('.demo-document-page').first().scrollIntoViewIfNeeded();
  await page.screenshot({ animations: 'disabled', path: `${output}/05-cv.png` });
  await page.getByRole('button', { name: 'Back to Jobs' }).click();
  await page.getByRole('button', { name: 'Analytics', exact: true }).click();
  await page.getByText('Total Jobs', { exact: true }).waitFor();
  await page.screenshot({ animations: 'disabled', path: `${output}/06-analytics.png` });
  await page.getByRole('button', { name: 'Jobs', exact: true }).click();
  await page.getByRole('button', { name: /^All \d+$/ }).click();
  await page.getByRole('textbox', { name: 'Search jobs' }).fill('');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, 0));
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'Mobile page overflows horizontally.');
  await page.screenshot({ animations: 'disabled', path: `${output}/07-mobile.png` });
  assert.deepEqual(errors, []);
  await writeFile(`${output}/verification.json`, JSON.stringify({
    localDemo: true, login: true, groupedRatingList: true, search: true, disabledWrites: true,
    pdfDownload: true, analytics: true, mobileWidth: 390, horizontalOverflow: false,
    uncaughtErrors: errors, blockedExternalOrigins: [...new Set(external)],
    note: 'Screenshots show hand-prepared fictional examples. Media awaits owner approval.'
  }, null, 2));
  console.log(`Browser checks passed. Review screenshots in ${output}`);
} finally {
  await browser.close();
}
