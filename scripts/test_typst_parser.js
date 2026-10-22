import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { execSync } from 'child_process';
import { parseTypstDocument } from '../webapp/src/services/typstParser.js';
import { serializeTypstDocument } from '../webapp/src/services/typstSerializer.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const root = path.resolve(__dirname, '..');

const testFiles = [
  'base-typst/base-cv-moderner.typ',
  'base-typst/base-cv.typ',
  'base-typst/base-cl.typ',
  'base-typst/base-cv-moderner.typ',
  'base-typst/base-cv.typ',
  'base-typst/base-cl.typ',
];

let allPassed = true;

for (const relPath of testFiles) {
  const fullPath = path.join(root, relPath);
  if (!fs.existsSync(fullPath)) {
    console.log(`Skipping non-existent: ${relPath}`);
    continue;
  }
  const content = fs.readFileSync(fullPath, 'utf-8');
  const parsed = parseTypstDocument(content);

  console.log(`\n--- Testing ${relPath} ---`);
  console.log(`Supported: ${parsed.supported}, Kind: ${parsed.kind}`);

  if (!parsed.supported) {
    console.error(`FAILED: ${relPath} could not be parsed:`, parsed.reason);
    allPassed = false;
    continue;
  }

  console.log(`Basics Name: "${parsed.data?.basics?.name}"`);
  if (parsed.data?.sections) {
    console.log(`Sections count: ${parsed.data.sections.length}`);
    for (const sec of parsed.data.sections) {
      console.log(`  - ${sec.title} (${sec.type}): ${sec.entries ? sec.entries.length + ' entries' : (sec.groups ? sec.groups.length + ' groups' : 'text')}`);
    }
  } else if (parsed.data?.paragraphs) {
    console.log(`Cover Letter Paragraphs: ${parsed.data.paragraphs.length}`);
  }

  const tmpTyp = path.join(root, 'scratch_test.typ');
  const tmpPdf = path.join(root, 'scratch_test.pdf');

  // Test Serialization & Compilation
  try {
    const reserialized = serializeTypstDocument(parsed.kind, parsed.data);
    console.log(`Serialized length: ${reserialized.length} chars`);

    // Verify round-trip parsing
    const reparsed = parseTypstDocument(reserialized);
    if (!reparsed.supported) {
      console.error(`FAILED: Round-trip re-parsing failed for ${relPath}:`, reparsed.reason);
      allPassed = false;
    } else {
      console.log(`Round-trip re-parsing: SUCCESS (Kind: ${reparsed.kind})`);
    }

    // Test that reserialized Typst compiles cleanly
    fs.writeFileSync(tmpTyp, reserialized, 'utf-8');
    execSync(`typst compile scratch_test.typ scratch_test.pdf`, { cwd: root, stdio: 'pipe' });
    console.log(`Typst CLI Compilation: SUCCESS`);

    // Test adding and removing bullets dynamically (for CVs)
    if (parsed.data?.sections) {
      const expSec = parsed.data.sections.find((s) => s.type === 'entries' && s.entries?.length > 0);
      if (expSec) {
        const origCount = expSec.entries[0].bullets.length;
        expSec.entries[0].bullets.push('Dynamically added achievement bullet via Simple Mode!');
        const withAdded = serializeTypstDocument(parsed.kind, parsed.data);
        fs.writeFileSync(tmpTyp, withAdded, 'utf-8');
        execSync(`typst compile scratch_test.typ scratch_test.pdf`, { cwd: root, stdio: 'pipe' });
        console.log(`  + Dynamic bullet add verification: SUCCESS (bullets: ${origCount} -> ${origCount + 1})`);

        expSec.entries[0].bullets.pop();
        const withRemoved = serializeTypstDocument(parsed.kind, parsed.data);
        fs.writeFileSync(tmpTyp, withRemoved, 'utf-8');
        execSync(`typst compile scratch_test.typ scratch_test.pdf`, { cwd: root, stdio: 'pipe' });
        console.log(`  - Dynamic bullet remove verification: SUCCESS`);
      }
    }
  } catch (err) {
    console.error(`Serialization or compile error for ${relPath}:`, err.stderr ? err.stderr.toString() : err.message);
    allPassed = false;
  } finally {
    if (fs.existsSync(tmpTyp)) fs.unlinkSync(tmpTyp);
    if (fs.existsSync(tmpPdf)) fs.unlinkSync(tmpPdf);
  }
}

if (!allPassed) {
  console.error('\nSOME TESTS FAILED');
  process.exit(1);
} else {
  console.log('\nALL TYPST PARSER/SERIALIZER/COMPILATION TESTS PASSED!');
}
