// Visual regression of the actual Studio WGSL fragment shader using a synthetic texture.
// Does not require NFSU2 game assets. Run from web/: node --test test/studio-gpu.test.mjs
// GitHub Actions installs Playwright's Chromium (software WebGPU / SwiftShader).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import path from 'node:path';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import * as esbuild from 'esbuild';
import { chromium } from 'playwright';

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const bundled = await esbuild.build({ entryPoints: [path.join(web, 'src/gpu/wgsl.ts')],
  bundle: true, platform: 'neutral', format: 'esm', write: false });
const { TONE } = await import('data:text/javascript;base64,' +
  Buffer.from(bundled.outputFiles[0].text).toString('base64'));

test('Studio shader compiles and renders original and graded pictures in Chromium WebGPU', { timeout: 120000 }, async () => {
  const browser = await chromium.launch({ headless: true, args: [
    '--enable-unsafe-webgpu', '--enable-features=Vulkan', '--use-angle=swiftshader',
    '--enable-dawn-features=allow_unsafe_apis', '--disable-vulkan-surface',
  ] });
  try {
    const page = await browser.newPage();
    const output = await page.evaluate(async code => {
      if (!navigator.gpu) throw new Error('navigator.gpu unavailable in Chromium');
      const adapter = await navigator.gpu.requestAdapter({ powerPreference: 'low-power' });
      if (!adapter) throw new Error('WebGPU adapter unavailable: Chromium software WebGPU not enabled');
      const device = await adapter.requestDevice();
      try {
        const w = 256, h = 128, row = w * 4;
        const source = new Uint8Array(row * h);
        for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
          const l = x / (w - 1), p = (y * w + x) * 4;
          if (y < h / 2) {
            const n = Math.round(255 * l);
            source.set([n, n, n, 255], p);
          } else {
            // A cool night road leading into warm streetlamp highlights (synthetic).
            source.set([Math.round(15 + 222 * l), Math.round(24 + 182 * l),
              Math.round(52 + 150 * l), 255], p);
          }
        }
        const src = device.createTexture({size: [w, h], format: 'rgba8unorm',
          usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST});
        device.queue.writeTexture({ texture: src }, source, { bytesPerRow: row }, { width: w, height: h });
        const module = device.createShaderModule({ label: 'project Studio tone shader', code });
        const diag = await module.getCompilationInfo();
        const errors = diag.messages.filter(m => m.type === 'error').map(m => m.message);
        if (errors.length) throw new Error('WGSL compilation: ' + errors.join(' | '));
        const pipe = device.createRenderPipeline({ layout: 'auto',
          vertex: { module, entryPoint: 'vs_full' },
          fragment: { module, entryPoint: 'fs_tone', targets: [{ format: 'rgba8unorm' }] },
          primitive: { topology: 'triangle-list' }});
        const sampler = device.createSampler({ magFilter: 'nearest', minFilter: 'nearest' });
        const tone = device.createBuffer({size: 16, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST});
        const bind = device.createBindGroup({layout: pipe.getBindGroupLayout(0), entries: [
          {binding: 0, resource: src.createView()}, {binding: 1, resource: sampler},
          {binding: 2, resource: {buffer: tone}},
        ]});
        const outputs = [];
        for (const grade of [0, 1]) {
          const dst = device.createTexture({size:[w,h],format:'rgba8unorm',
            usage: GPUTextureUsage.RENDER_ATTACHMENT | GPUTextureUsage.COPY_SRC});
          const read = device.createBuffer({size: row * h,
            usage: GPUBufferUsage.MAP_READ | GPUBufferUsage.COPY_DST});
          device.queue.writeBuffer(tone, 0, new Float32Array([1, 1, 0, grade]));
          const commands = device.createCommandEncoder();
          const pass = commands.beginRenderPass({colorAttachments:[{
            view: dst.createView(), loadOp: 'clear', storeOp: 'store',
            clearValue: [0, 0, 0, 1],
          }]});
          pass.setPipeline(pipe); pass.setBindGroup(0, bind); pass.draw(3); pass.end();
          commands.copyTextureToBuffer({texture: dst},{buffer: read, bytesPerRow: row},{width:w,height:h});
          device.queue.submit([commands.finish()]);
          await read.mapAsync(GPUMapMode.READ);
          const pixels = new Uint8ClampedArray(read.getMappedRange().slice(0));
          const el = document.createElement('canvas');
          el.width = w; el.height = h;
          const ctx = el.getContext('2d');
          if (!ctx) throw new Error('Canvas 2D not available to encode GPU comparison');
          ctx.putImageData(new ImageData(pixels,w,h),0,0);
          const png = el.toDataURL('image/png');
          outputs.push({png, pixels: Array.from(pixels)});
          read.unmap(); read.destroy(); dst.destroy();
        }
        src.destroy(); tone.destroy();
        // Only pixels, not screenshots of licensed game assets, leave this page.
        return { outputs, source: Array.from(source) };
      } finally {
        device.destroy();
      }
    }, TONE);

    const [original, studio] = output.outputs.map(o => o.pixels);
    assert.equal(original.length, output.source.length);
    let originalMax = 0, gradeMax = 0, gradeChanged = 0, gradeAlpha = 0;
    for (let i = 0; i < original.length; i += 4) {
      for (let c = 0; c < 3; c++) {
        originalMax = Math.max(originalMax, Math.abs(original[i+c] - output.source[i+c]));
        const d = Math.abs(studio[i+c] - original[i+c]);
        gradeMax = Math.max(gradeMax, d);
        if (d >= 2) gradeChanged++;
      }
      if (studio[i+3] !== 255 || original[i+3] !== 255) gradeAlpha++;
    }
    assert.ok(originalMax <= 2, 'Original path changed source pixels (maximum difference ' + originalMax + ')');
    assert.ok(gradeChanged > 1000, 'Studio color pass produced no visible RGB changes');
    assert.ok(gradeMax < 32, 'Studio treatment is too strong (maximum difference ' + gradeMax + ')');
    assert.equal(gradeAlpha, 0, 'Output alpha must stay opaque');

    const dir = path.join(web, 'test-artifacts/studio-grade');
    fs.mkdirSync(dir, { recursive: true });
    for (let i = 0; i < 2; i++) {
      const png = output.outputs[i].png;
      assert.ok(png.startsWith('data:image/png;base64,'));
      fs.writeFileSync(path.join(dir, i === 0 ? 'original.png' : 'studio.png'),
        Buffer.from(png.slice('data:image/png;base64,'.length), 'base64'));
    }
    console.log('WebGPU synthetic validation: original max error:', originalMax,
      '| changed Studio channels:', gradeChanged, '| maximum Studio delta:', gradeMax);
  } finally { await browser.close(); }
});
