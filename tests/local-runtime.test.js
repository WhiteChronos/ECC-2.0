const assert = require('node:assert/strict');
const test = require('node:test');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');

test('successful download cannot approve unknown process termination', () => {
  const {preparationExitCode} = require('../scripts/local-runtime.cjs');
  assert.equal(preparationExitCode(0, true), 0);
  assert.notEqual(preparationExitCode(0, false), 0);
  assert.notEqual(preparationExitCode(0, undefined), 0);
  assert.equal(preparationExitCode(3, true), 3);
});

test('model selection and preparation accept only explicit local allowlist', () => {
  const runtime = require('../scripts/local-runtime.cjs');
  assert.deepEqual(runtime.parseAction(['--doctor', '--model', 'qwen3:4b']), {args:['--doctor'], model:'qwen3:4b', prepare:false});
  assert.deepEqual(runtime.parseAction(['--prepare-model', 'qwen3:4b']), {args:[], model:'qwen3:4b', prepare:true});
  assert.equal(runtime.parseAction(['--doctor']).model, 'qwen3:0.6b');
  assert.equal(runtime.parseAction(['--prepare-model','ecc-qwen3-4b-local']).model,'ecc-qwen3-4b-local');
  assert.equal(runtime.parseAction(['--prepare-model','qwen3:4b-instruct-2507-q4_K_M']).model,'qwen3:4b-instruct-2507-q4_K_M');
  for (const args of [['--model','remote:cloud'], ['--prepare-model','remote:cloud'], ['--doctor','--model','qwen3:4b','--model','qwen3:0.6b'], ['--prepare-model','qwen3:4b','extra']]) {
    assert.throws(() => runtime.parseAction(args));
  }
});

test('derived local model closes the thinking prefix before answer generation', () => {
  const body=fs.readFileSync(path.join(__dirname,'../scripts/Qwen3-4B-Local.Modelfile'),'utf8');
  assert.ok(body.startsWith('FROM qwen3:4b\n'));
  assert.ok(body.includes('<think>\n\n</think>\n\n'));
  assert.ok(!body.includes('user_id'));
});

test('isolated store copies verified layers and preserves divergent existing files', () => {
  const {prepareIsolatedBase}=require('../scripts/prepare-local-profile.cjs');
  const {createHash}=require('node:crypto');
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'ecc-profile-')),source=path.join(root,'source'),target=path.join(root,'target');
  const content=Buffer.from('own test weights'),digest=createHash('sha256').update(content).digest('hex');
  const relative='manifests/registry.ollama.ai/library/qwen3/4b';
  fs.mkdirSync(path.join(source,'blobs'),{recursive:true});fs.mkdirSync(path.dirname(path.join(source,relative)),{recursive:true});
  const layer={digest:'sha256:'+digest};
  fs.writeFileSync(path.join(source,'blobs','sha256-'+digest),content);
  fs.writeFileSync(path.join(source,relative),JSON.stringify({config:layer,layers:[layer]}));
  prepareIsolatedBase(source,target);
  const copied=path.join(target,'blobs','sha256-'+digest);
  assert.deepEqual(fs.readFileSync(copied),content);
  fs.writeFileSync(copied,'changed');
  assert.throws(()=>prepareIsolatedBase(source,target),/divergiu/);
  assert.equal(fs.readFileSync(copied,'utf8'),'changed');
  assert.deepEqual(fs.readFileSync(path.join(source,'blobs','sha256-'+digest)),content);
});

test('batch JSON is an explicit local action with bounded input', () => {
  const runtime = require('../scripts/local-runtime.cjs');
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ecc-batch-input-'));
  const file = path.join(root, 'batch.json');
  fs.writeFileSync(file, JSON.stringify({schemaVersion: 1, runId: 'fixture', requests: [{requestId:'one',taskId:'fixture',mode:'baseline',prompt:'hello',repetition:0,expectedChecks:['exact:hello']}]}));
  assert.deepEqual(runtime.validateArgs(['--batch-json', file]), ['--batch-json', file]);
  const data=JSON.parse(fs.readFileSync(file));
  fs.writeFileSync(file,JSON.stringify({...data,responseFormat:'json-string'}));
  assert.deepEqual(runtime.validateArgs(['--batch-json',file]),['--batch-json',file]);
  fs.writeFileSync(file,JSON.stringify({...data,responseFormat:'bad'}));
  assert.throws(() => runtime.validateArgs(['--batch-json',file]));
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
