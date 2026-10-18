const assert = require('node:assert/strict');
const test = require('node:test');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');

test('batch JSON is an explicit local action with bounded input', () => {
  const runtime = require('../scripts/local-runtime.cjs');
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ecc-batch-input-'));
  const file = path.join(root, 'batch.json');
  fs.writeFileSync(file, JSON.stringify({schemaVersion: 1, runId: 'fixture', requests: [{requestId:'one',taskId:'fixture',mode:'baseline',prompt:'hello',repetition:0,expectedChecks:['exact:hello']}]}));
  assert.deepEqual(runtime.validateArgs(['--batch-json', file]), ['--batch-json', file]);
  assert.throws(() => runtime.validateArgs(['--batch-json', path.join(root, 'absent.json')]));
});

test('runtime environment disables cloud and excludes API keys and proxies', () => {
  const runtime = require('../scripts/local-runtime.cjs');
  const env = runtime.runtimeEnvironment({SystemRoot: 'C:\\Windows', PATH: 'safe', OPENAI_API_KEY: 'fixture-only', HTTPS_PROXY: 'http://external'}, 'C:/runtime', 12345);
  assert.equal(env.OLLAMA_NO_CLOUD, '1');
  assert.equal(env.OLLAMA_HOST, '127.0.0.1:12345');
  assert.equal(env.OPENAI_API_KEY, undefined);
  assert.equal(env.HTTPS_PROXY, undefined);
  assert.equal(env.OLLAMA_MODELS, path.join('C:/runtime', 'models'));
});

test('runtime arguments forward only supported local actions', () => {
  const runtime = require('../scripts/local-runtime.cjs');
  assert.deepEqual(runtime.validateArgs(['--doctor']), ['--doctor']);
  assert.deepEqual(runtime.validateArgs(['--prompt', 'help me']), ['--prompt', 'help me']);
  assert.throws(() => runtime.validateArgs(['--url', 'https://example.com']));
  assert.throws(() => runtime.validateArgs(['--model', 'remote:cloud']));
});

test('a failed smoke replaces old acceptance with a new failed run', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ecc-local-acceptance-'));
  fs.mkdirSync(path.join(root, '.local-runtime'));
  const latest = path.join(root, '.local-runtime', 'latest-acceptance.json');
  fs.writeFileSync(latest, JSON.stringify({passed: true, runId: 'old'}));
  const code = await require('../scripts/local-runtime.cjs').main(['--smoke'], {root, directory: path.join(root, 'absent'), python: process.execPath});
  const result = JSON.parse(fs.readFileSync(latest));
  assert.equal(code, 1);
  assert.equal(result.passed, false);
  assert.notEqual(result.runId, 'old');
  assert.equal(result.realInferenceVerified, false);
});
