import assert from 'node:assert/strict';
import fs from 'node:fs';

// Run the real library hook while controlling when the compile response arrives.
const source = fs.readFileSync('webapp/src/hooks/useStudio.js', 'utf8')
  .replace(/^import .*;$/gm, '').replace('export function useStudio', 'function useStudio');
const factory = new Function('useState', 'useRef', 'useCallback', 'useEffect', 'useApi',
  'compileTypstClient', 'uint8ArrayToBase64', 'downloadPdfBlob', source + '\nreturn useStudio;');

function fixture(engine, compileSuccess = true) {
  const hooks = [], writes = [];
  let cursor = 0, finishCompile;
  let saved = { id: 'one', content: 'original', source_hash: 'original-hash', engine };
  const useState = initial => {
    const index = cursor++;
    if (!(index in hooks)) hooks[index] = initial;
    return [hooks[index], value => { hooks[index] = typeof value === 'function' ? value(hooks[index]) : value; }];
  };
  const useRef = initial => {
    const index = cursor++;
    if (!(index in hooks)) hooks[index] = { current: initial };
    return hooks[index];
  };
  const api = {
    get: async path => ({ data: path === '/documents' ? { documents: [] }
      : path === '/documents/one' ? { ...saved }
        : { id: 'other', content: 'other draft', source_hash: 'other-hash', engine } }),
    post: async (_, payload) => new Promise(resolve => {
      finishCompile = () => {
        saved = { ...saved, content: payload.content, source_hash: 'compiled-hash' };
        resolve({ data: { success: compileSuccess, ...saved, pdf_current: compileSuccess,
          error: compileSuccess ? null : { message: 'Fictional compilation failure' } } });
      };
    }),
    put: async (_, payload) => {
      writes.push(payload);
      if (payload.expected_source_hash !== saved.source_hash) throw Error('409: stale source');
      saved = { ...saved, content: payload.content, source_hash: 'saved-hash' };
      return { data: { ...saved, pdf_current: true } };
    },
  };
  const useStudio = factory(useState, useRef, callback => callback, () => {}, () => api,
    async () => ({ result: new Uint8Array([1]) }), () => 'fictional-pdf', () => {});
  return {
    render: () => { cursor = 0; return useStudio({ user: { username: 'fictional' }, activeTab: 'studio', addToast: () => {} }); },
    complete: () => { assert(finishCompile, 'The compile request must be pending.'); finishCompile(); },
    writes,
  };
}

for (const engine of ['typst', 'latex']) {
  for (const compileSuccess of [true, false]) {
    const test = fixture(engine, compileSuccess);
    let studio = test.render();
    await studio.selectDocument('one');
    studio = test.render(); studio.setDraftContent('compiled draft');
    studio = test.render();
    const compiling = studio.compileDocument();
    await Promise.resolve();
    studio.setDraftContent('newer typing');
    test.render(); test.complete(); await compiling;
    studio = test.render();
    assert.equal(studio.draftContent, 'newer typing', `${engine}: keep newer typing`);
    assert.equal(studio.isDirty, true, `${engine}: newer typing still needs saving`);
    assert.equal(await studio.saveDocument(), true, `${engine} ${compileSuccess ? 'successful' : 'failed'} compile: newer typing must remain saveable`);
    assert.equal(test.writes[0].expected_source_hash, 'compiled-hash');
    assert.equal(test.writes[0].content, 'newer typing');
    assert.equal(test.render().isDirty, false);
  }

  const switched = fixture(engine);
  let studio = switched.render(); await studio.selectDocument('one');
  studio = switched.render(); studio.setDraftContent('old document draft');
  studio = switched.render();
  const oldCompile = studio.compileDocument();
  await Promise.resolve();
  await studio.selectDocument('other'); switched.render();
  switched.complete(); await oldCompile;
  studio = switched.render();
  assert.equal(studio.activeDoc.id, 'other');
  assert.equal(studio.activeDoc.source_hash, 'other-hash');
  assert.equal(studio.draftContent, 'other draft');
}
console.log('Studio regressions passed: typing during compile remains saveable; old document responses stay isolated.');
