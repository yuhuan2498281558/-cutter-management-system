const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { parse, compileScript, compileTemplate } = require('@vue/compiler-sfc');

const filename = path.resolve(__dirname, '../index.vue');
const id = 'home-shell-compile-test';

test('home shell script and template compile', () => {
  const { descriptor, errors } = parse(fs.readFileSync(filename, 'utf8'), { filename });
  assert.deepEqual(errors, []);
  const script = compileScript(descriptor, { id });
  assert.deepEqual(compileTemplate({ source: descriptor.template.content, filename, id,
    compilerOptions: { bindingMetadata: script.bindings } }).errors, []);
});

test('home shell imports only the components it renders', () => {
  const { descriptor } = parse(fs.readFileSync(filename, 'utf8'), { filename });
  const { imports } = compileScript(descriptor, { id });
  const components = Object.entries(imports).filter(([, binding]) => binding.source.endsWith('.vue'));
  assert.deepEqual(components.map(([name]) => name).sort(), ['BimfaceModel', 'LeftPanel', 'ToolChangeOverview']);
  for (const [name, binding] of components) assert.equal(binding.isUsedInTemplate, true, name);
});
