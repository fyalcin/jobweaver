import assert from 'node:assert/strict';
import fs from 'node:fs';
import { parseTypstDocument } from '../webapp/src/services/typstParser.js';
import { serializeTypstDocument } from '../webapp/src/services/typstSerializer.js';

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

// Simple Mode can add, change and remove the optional subtitle on both CV templates.
for (const template of ['base-typst/base-cv.typ', 'base-typst/base-cv-moderner.typ']) {
  const original = parseTypstDocument(fs.readFileSync(template, 'utf8'));
  assert.equal(original.supported, true, template);
  const write = (parsed, subtitle) => serializeTypstDocument(parsed.kind, { ...parsed.data, basics: { ...parsed.data.basics, subtitle } }, parsed.rawPreamble);
  const blank = parseTypstDocument(write(original, ''));
  assert.equal(blank.data.basics.subtitle, '', `${template}: subtitle removed`);
  const added = parseTypstDocument(write(blank, 'Data [Lead] Scientist'));
  assert.equal(added.supported, true, `${template}: stays in Simple Mode`);
  assert.equal(added.data.basics.subtitle, 'Data [Lead] Scientist', `${template}: subtitle added`);
  assert.deepEqual(added.data.sections, blank.data.sections, `${template}: body untouched`);
  assert.equal(added.data.basics.name, blank.data.basics.name, `${template}: name untouched`);
  const sameAsBody = 'Senior Software Developer';
  const changed = parseTypstDocument(write(added, sameAsBody));
  assert.equal(changed.data.basics.subtitle, sameAsBody, `${template}: subtitle may repeat body text`);
  // Each parse and write can add a blank line before the first section, so compare without blank lines.
  const lines = source => source.split('\n').filter(line => line.trim());
  assert.deepEqual(lines(write(changed, '')), lines(write(blank, '')), `${template}: removing restores the header`);
}
console.log('Subtitle regressions passed: add, change and remove on both CV templates.');

// Every header field can be changed, cleared and re-added in Simple Mode, and only that field moves.
const headerValues = { name: 'Dr Ada Lovelace', subtitle: 'Climate Modeller', email: 'ada@example.org', github: 'adagit', linkedin: 'ada-li', address: 'Graz, Austria', phone: '+43 660 1234567', residence: 'Rot-Weiss-Rot Karte' };
for (const template of ['base-typst/base-cv.typ', 'base-typst/base-cv-moderner.typ']) {
  const start = parseTypstDocument(fs.readFileSync(template, 'utf8'));
  const write = (parsed, key, value) => serializeTypstDocument(parsed.kind, { ...parsed.data, basics: { ...parsed.data.basics, [key]: value } }, parsed.rawPreamble);
  for (const [key, value] of Object.entries(headerValues)) {
    const changed = parseTypstDocument(write(start, key, value));
    assert.deepEqual(changed.data.basics, { ...start.data.basics, [key]: value }, `${template}: change ${key}`);
    assert.deepEqual(changed.data.sections, start.data.sections, `${template}: ${key} leaves the body alone`);
    const cleared = parseTypstDocument(write(changed, key, ''));
    assert.deepEqual(cleared.data.basics, { ...start.data.basics, [key]: '' }, `${template}: clear ${key}`);
    const again = parseTypstDocument(write(cleared, key, value));
    assert.equal(again.data.basics[key], value, `${template}: re-add ${key}`);
    assert.deepEqual(again.data.sections, start.data.sections, `${template}: re-adding ${key} leaves the body alone`);
  }
  // Reading and writing a document repeatedly must not change it.
  const once = serializeTypstDocument(start.kind, start.data, start.rawPreamble);
  const reread = parseTypstDocument(once);
  assert.equal(serializeTypstDocument(reread.kind, reread.data, reread.rawPreamble), once, `${template}: stable when rewritten`);
}
// The visible email changes with the link, and dates in the body are not mistaken for a phone number.
const standard = parseTypstDocument(fs.readFileSync('base-typst/base-cv.typ', 'utf8'));
const newEmail = serializeTypstDocument(standard.kind, { ...standard.data, basics: { ...standard.data.basics, email: 'ada@example.org' } }, standard.rawPreamble);
assert(newEmail.includes('[ada\\@example.org]') && !newEmail.includes('alex.muster'), 'The visible email must change.');
assert.equal(standard.data.basics.phone, '');
console.log('Header regressions passed: every field on both CV templates, and stable rewrites.');
