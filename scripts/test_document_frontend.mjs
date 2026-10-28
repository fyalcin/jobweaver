import assert from 'node:assert/strict';
import fs from 'node:fs';
import { parseTypstDocument } from '../webapp/src/services/typstParser.js';
import { serializeTypstDocument } from '../webapp/src/services/typstSerializer.js';

const source = fs.readFileSync('base-typst/base-cv.typ', 'utf8')
  .replace('size: 9.5pt', 'size: 11pt').replace('font: ("Arial", "Helvetica Neue")', 'font: "Source Sans Pro"').replace('lang: "en"', 'lang: "de"');
const parsed = parseTypstDocument(source);
const serialized = serializeTypstDocument(parsed.kind, parsed.data, parsed.rawPreamble);
assert(serialized.includes('font: "Source Sans Pro"'));
assert(serialized.includes('size: 11pt'));
assert(serialized.includes('lang: "de"'));
const modern = parseTypstDocument(fs.readFileSync('base-typst/base-cv-moderner.typ', 'utf8'));
modern.data.basics.name = 'Synthetic "quoted"';
assert(serializeTypstDocument(modern.kind, modern.data).includes('name: "Synthetic \\"quoted\\""'));
assert.equal(parseTypstDocument('// GIMME_APPROVED test\n#set text(10pt)').supported, false);

// Execute the real batch callback using lightweight hook/API substitutes.
let payload;
const raw = fs.readFileSync('webapp/src/hooks/useBatchGen.js', 'utf8')
  .replace(/^import .*;$/gm, '')
  .replace('export function useBatchGen', 'function useBatchGen');
const run = new Function('useState', 'useRef', 'useCallback', 'useEffect', 'useApi', 'setInterval', raw + '\nreturn useBatchGen;');
let stateIndex = 0;
const hook = run((initial) => [stateIndex++ === 3 ? true : initial, () => {}], (initial) => ({ current: initial }),
  (callback) => callback, () => {}, () => ({ post: async (_, value) => { payload = value; return { data: {} }; } }), () => 1);
const batch = hook({ aiModel: 'mock', aiTone: '', addToast: () => {}, filteredJobs: [{ id: 'synthetic' }], fetchJobs: () => {} });
await batch.handleBatchGenerate(null, { engine: 'latex' });
assert.deepEqual(payload.job_ids, ['synthetic']);
assert.equal(payload.compact, true);
assert.equal(payload.engine, 'latex');
console.log('Frontend regressions passed: customized style/language, string escaping, reviewed-source protection, batch callback.');

// A completed request from an old job must not replace the newly selected job.
const jobHookSource = fs.readFileSync('webapp/src/hooks/useJobStudio.js', 'utf8')
  .replace(/^import .*;$/gm, '').replace('export function useJobStudio', 'function useJobStudio');
let hooks = [], cursor = 0, respond;
const useState = (initial) => {
  const slot = cursor++;
  if (!(slot in hooks)) hooks[slot] = initial;
  return [hooks[slot], (value) => { hooks[slot] = typeof value === 'function' ? value(hooks[slot]) : value; }];
};
const useRef = (initial) => {
  const slot = cursor++;
  if (!(slot in hooks)) hooks[slot] = { current: initial };
  return hooks[slot];
};
const jobFactory = new Function('useState', 'useRef', 'useCallback', 'useEffect', 'useApi',
  'compileTypstClient', 'uint8ArrayToBase64', 'downloadPdfBlob', jobHookSource + '\nreturn useJobStudio;');
const useJob = jobFactory(useState, useRef, (callback) => callback, () => {}, () => ({
  post: () => new Promise((resolve) => { respond = resolve; }),
}), () => {}, () => {}, () => {});
const renderJob = (id) => { cursor = 0; return useJob(id, () => {}); };
let studio = renderJob('old');
studio.setCvTex('old source');
studio = renderJob('old');
const pendingCompile = studio.compile();
renderJob('new');
respond({ data: { success: true, pdf_url: 'OLD.pdf', image_urls: ['OLD.png'] } });
assert.equal(await pendingCompile, false);
assert.equal(renderJob('new').cvDownloadUrl, null);
// Late AI output must not discard text typed while waiting.
hooks = []; studio = renderJob('one'); studio.setCvTex('first'); studio = renderJob('one');
const pendingEdit = studio.aiEdit('Select evidence');
studio.setCvTex('later typing'); renderJob('one');
respond({ data: { success: true, compile_success: true, modified_tex: 'AI output' } });
assert.equal(await pendingEdit, false);
assert.equal(renderJob('one').cvTex, 'later typing');

// A dead worker rejects every waiting request and can be replaced.
const workerSource = fs.readFileSync('webapp/src/services/typstWorkerClient.js', 'utf8')
  .replace(/export /g, '')
  .replace(/new URL\('\.\.\/workers\/typst\.worker\.js', import\.meta\.url\)/, '"synthetic-worker"');
const workers = [], timers = new Map(); let timerId = 0;
class SyntheticWorker {
  constructor() { workers.push(this); }
  postMessage(value) { this.message = value; }
  terminate() { this.terminated = true; }
}
const workerFactory = new Function('window', 'Worker', 'setTimeout', 'clearTimeout', workerSource +
  '\nreturn { compileTypstClient, terminateTypstWorker };');
const client = workerFactory({ Worker: SyntheticWorker, WebAssembly: {} }, SyntheticWorker,
  (callback) => { timers.set(++timerId, callback); return timerId; }, (id) => timers.delete(id));
const a = client.compileTypstClient('a'), b = client.compileTypstClient('b');
const failed = Promise.allSettled([a, b]);
[...timers.values()][0]();
assert((await failed).every((item) => item.status === 'rejected'));
assert.equal(timers.size, 0);
assert(workers[0].terminated);
const c = client.compileTypstClient('c');
workers[1].onmessage({ data: { type: 'SUCCESS', id: workers[1].message.id, result: 'fresh' } });
assert.equal((await c).result, 'fresh');
client.terminateTypstWorker();
console.log('Async regressions passed: job switching, edits during AI requests, worker timeout/recovery.');

// A callback retained by an old workspace must never send a write as the new user.
const { createAuthenticatedClient, advanceSession } = await import('../webapp/src/api/client.js');
const firstUser = createAuthenticatedClient();
let dispatched = 0;
firstUser.api.defaults.adapter = async config => {
  dispatched += 1;
  return { data: {}, status: 200, statusText: 'OK', headers: {}, config };
};
await firstUser.api.post('/jobs/example', { status: 'interested' });
advanceSession();
await assert.rejects(firstUser.api.post('/jobs/example', { status: 'applied' }), /session changed/);
assert.equal(dispatched, 1);
firstUser.dispose();
const secondUser = createAuthenticatedClient();
secondUser.api.defaults.adapter = firstUser.api.defaults.adapter;
await secondUser.api.get('/jobs');
assert.equal(dispatched, 2);
secondUser.dispose();
await assert.rejects(secondUser.api.post('/jobs/example'), /session changed/);
console.log('Session regressions passed: expired workspaces cannot dispatch later writes.');

// Queued operations keep polling; interrupted operations stop and expose retry guidance.
async function checkBackgroundHook(file, name, action, progressIndex) {
  const text = fs.readFileSync(file, 'utf8').replace(/^import .*;$/gm, '')
    .replace(`export function ${name}`, `function ${name}`);
  const values = [], messages = [];
  let index = 0, poll, cleared = 0, refreshed = 0;
  let status = 'queued';
  const factory = new Function('useState', 'useRef', 'useCallback', 'useEffect', 'useApi', 'setInterval', 'clearInterval', text + `\nreturn ${name};`);
  const hook = factory(initial => {
    const slot = index++;
    values[slot] = initial;
    return [initial, value => { values[slot] = value; }];
  }, initial => ({ current: initial }), callback => callback, () => {}, () => ({
    post: async () => ({ data: { success: true, task_id: 'queued-task', status: 'queued', stage: 'queued', total: 2 } }),
    get: async path => ({ data: path.includes('/status/') ? {
      status, stage: status, logs: [], processed: 0, total: 2, failed: 0,
      result: { message: 'Interrupted. Retry explicitly.' },
    } : path === '/jobs/unprocessed' ? { jobs: [] } : [] }),
  }), callback => { poll = callback; return 1; }, () => { cleared += 1; });
  const instance = hook({ user: { id: 1 }, aiTone: '', addToast: text => messages.push(text),
    filteredJobs: [{ id: 'fictional' }], fetchJobs: () => { refreshed += 1; } });
  await instance[action]();
  if (progressIndex !== null) assert.equal(values[progressIndex].status, 'queued');
  await poll();
  assert.equal(cleared, 0);
  status = 'interrupted';
  await poll();
  assert.equal(cleared, 1);
  assert.equal(refreshed, 1);
  assert(messages.includes('Interrupted. Retry explicitly.'));
}
await checkBackgroundHook('webapp/src/hooks/useBatchGen.js', 'useBatchGen', 'handleBatchGenerate', 1);
await checkBackgroundHook('webapp/src/hooks/useScraper.js', 'useScraper', 'handleScrape', null);
await checkBackgroundHook('webapp/src/hooks/useScraper.js', 'useScraper', 'handleStartReprocess', 13);
console.log('Background regressions passed: queued polling and interrupted cleanup for all three operations.');

await import('./test_ui_preferences.mjs');

await import('./test_match_rating_frontend.mjs');
