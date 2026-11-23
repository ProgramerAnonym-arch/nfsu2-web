// Browser-only Studio color treatment: settings and renderer wiring.
// No original game assets or WebGPU device are required by these checks.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as esbuild from 'esbuild';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const entry = "export { TONE } from './web/src/gpu/wgsl.ts'; export { checkSetting, DEFAULTS } from './web/src/app/settings.ts';";
const code = (await esbuild.build({
  stdin: { contents: entry, resolveDir: root, loader: 'ts' },
  bundle: true, format: 'esm', platform: 'neutral', write: false,
})).outputFiles[0].text;
const { TONE, checkSetting, DEFAULTS } = await import('data:text/javascript;base64,' + Buffer.from(code).toString('base64'));
const source = p => fs.readFileSync(path.join(root, p), 'utf8');

test('color_grade is off by default and validates both allowed values', () => {
  assert.equal(DEFAULTS.get('color_grade'), 'original');
  for (const value of ['original', 'studio']) {
    const result = checkSetting('color_grade', value);
    assert.equal(result?.ok, true);
    assert.equal(result?.env, 'NFSU2_COLOR_GRADE');
    assert.equal(result?.value, value);
  }
  assert.equal(checkSetting('color_grade', 'vivid')?.ok, false);
});

test('Studio is opt-in and the renderer does not draw directly into the canvas', () => {
  const subsystems = source('web/src/app/subsystems.ts');
  const gpu = source('web/src/gpu/index.ts');
  assert.match(subsystems, /colorGrade:\s*o\.env\.NFSU2_COLOR_GRADE === 'studio'/);
  assert.match(gpu, /const studio = opts\.colorGrade === 'studio'/);
  assert.match(gpu, /const direct =[^\n]+&& !studio;/);
  assert.match(gpu, /tone \|\| studio/);
  assert.match(gpu, /tsEnd, studio\)/);
  assert.match(source('web/src/gpu/encoder.ts'), /studio \? 1 : 0/);
});

test('the tone shader gates the optional grade behind a uniform', () => {
  assert.match(TONE, /@fragment fn fs_tone/);
  assert.match(TONE, /if \(tone\.w > 0\.5\)/);
  assert.match(TONE, /smoothstep\(0\.15, 0\.65, luma\)/);
  assert.match(TONE, /return vec4f\(c, 1\.0\)/);
});
