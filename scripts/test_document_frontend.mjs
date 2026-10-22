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
const run = new Function('useState', 'useRef', 'useCallback', 'useEffect', 'api', 'setInterval', raw + '\nreturn useBatchGen;');
let stateIndex = 0;
const hook = run((initial) => [stateIndex++ === 3 ? true : initial, () => {}], (initial) => ({ current: initial }),
  (callback) => callback, () => {}, { post: async (_, value) => { payload = value; return { data: {} }; } }, () => 1);
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
const jobFactory = new Function('useState', 'useRef', 'useCallback', 'useEffect', 'api',
  'compileTypstClient', 'uint8ArrayToBase64', 'downloadPdfBlob', jobHookSource + '\nreturn useJobStudio;');
const useJob = jobFactory(useState, useRef, (callback) => callback, () => {}, {
  post: () => new Promise((resolve) => { respond = resolve; }),
}, () => {}, () => {}, () => {});
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
