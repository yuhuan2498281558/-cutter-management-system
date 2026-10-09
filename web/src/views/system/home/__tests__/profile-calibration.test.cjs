const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const ts = require('typescript');
const context = { exports: {} };
vm.runInNewContext(ts.transpileModule(fs.readFileSync(path.join(__dirname, '../profileCalibration.ts'), 'utf8'),
  { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, context);
const { PROFILE_CALIBRATION: c, ringPositionPercent } = context.exports;

test('calibration matches the actual PDF bytes and physical ring range', () => {
  const pdf = fs.readFileSync(path.resolve(__dirname, '../../../../../public/static/home/changle-geology-profile.pdf'));
  assert.equal(crypto.createHash('sha256').update(pdf).digest('hex'), c.sha256);
  assert.equal(c.startRing, 0);
  assert.equal(c.endRing, 2800);
});

test('marker uses ring midpoint while progress uses ring end, without text-origin offset', () => {
  for (const ring of [1, 300, 400, 487, 2800]) {
    const middle = ringPositionPercent(ring) / 100 * c.pdfWidth;
    const end = ringPositionPercent(ring, 'end') / 100 * c.pdfWidth;
    assert.ok(Math.abs(end - middle - c.xPerRing / 2) < 1e-8);
    assert.ok(Math.abs(middle - (c.startX + (ring - 0.5) * c.xPerRing)) < 1e-8);
  }
  assert.ok(Math.abs(ringPositionPercent(400) / 100 * c.pdfWidth - 2296.449543514779) < 1e-8);
});
