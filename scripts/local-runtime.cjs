'use strict';

const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');
const { spawn } = require('node:child_process');
const { randomUUID } = require('node:crypto');

function runtimeEnvironment(parent, directory, port) {
  const allowed = new Set(['systemroot', 'windir', 'path', 'temp', 'tmp', 'comspec', 'processor_architecture', 'number_of_processors']);
  const env = Object.fromEntries(Object.entries(parent).filter(([key]) => allowed.has(key.toLowerCase())));
  return { ...env, USERPROFILE: path.join(directory, 'runtime-home'), OLLAMA_HOST: `127.0.0.1:${port}`,
    OLLAMA_MODELS: path.join(directory, 'models'), OLLAMA_NO_CLOUD: '1', OLLAMA_CONTEXT_LENGTH: '4096',
    OLLAMA_NUM_PARALLEL: '1', OLLAMA_KEEP_ALIVE: '5m', ECC_LOCAL_ONLY: '1', ECC_SKIP_LLM_SUMMARY: '1',
    PYTHONIOENCODING: 'utf-8', PYTHONUTF8: '1' };
}

const LOCAL_MODELS = new Set(['qwen3:0.6b', 'qwen3:4b']);

function parseAction(input) {
  if (input[0] === '--prepare-model') {
    if (input.length !== 2 || !LOCAL_MODELS.has(input[1])) throw new Error('Modelo local nao permitido.');
    return {args:[], model:input[1], prepare:true};
  }
  const index = input.indexOf('--model');
  const model = index < 0 ? 'qwen3:0.6b' : input[index + 1];
  if (!LOCAL_MODELS.has(model) || (index >= 0 && index !== input.length - 2)) throw new Error('Modelo local nao permitido.');
  const args = index < 0 ? [...input] : input.slice(0, index);
  validateBaseArgs(args);
  return {args, model, prepare:false};
}

function validateArgs(args) { parseAction(args); return args; }

function validateBaseArgs(args) {
  if (args.length === 2 && args[0] === '--batch-json') {
    const stat = fs.lstatSync(args[1]);
    if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 16 * 1024 * 1024) throw new Error('Arquivo de lote invalido.');
    const data = JSON.parse(fs.readFileSync(args[1], 'utf8').replace(/^\uFEFF/, ''));
    const id = value => typeof value === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(value);
    const keys = (value, names) => value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).sort().join(',') === names.sort().join(',');
    if (!keys(data,['schemaVersion','runId','requests']) || data.schemaVersion !== 1 || !id(data.runId) || !Array.isArray(data.requests) || data.requests.length < 1 || data.requests.length > 18) throw new Error('Schema de lote invalido.');
    const seen = new Set();
    for (const r of data.requests) {
      if (!keys(r,['requestId','taskId','mode','prompt','repetition','expectedChecks']) || !id(r.requestId) || !id(r.taskId) || seen.has(r.requestId) || !['baseline','optimized'].includes(r.mode) || !Number.isInteger(r.repetition) || r.repetition < 0 || r.repetition > 2 || typeof r.prompt !== 'string' || !Buffer.byteLength(r.prompt) || Buffer.byteLength(r.prompt) > 16384 || !Array.isArray(r.expectedChecks) || !r.expectedChecks.length || r.expectedChecks.length > 100 || r.expectedChecks.some(c => typeof c !== 'string' || c.length > 4096 || !/^(exact|contains):.+/s.test(c))) throw new Error('Pedido de lote invalido.');
      seen.add(r.requestId);
    }
    return args;
  }
  if (!args.length) return [];
  if (args.length === 1 && ['--doctor', '--smoke'].includes(args[0])) return args;
  if (args.length === 2 && args[0] === '--prompt' && args[1].length <= 16384) return args;
  throw new Error('Use --doctor, --smoke, --prompt texto ou nenhum argumento para chat.');
}

async function availablePort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return port;
}

async function runRuntime(args, context) {
  const action = parseAction(args);
  args = action.args;
  const { root } = context;
  const codexRoot = path.resolve(root, '../..');
  const directory = context.directory || process.env.ECC_OLLAMA_DIR || path.join(codexRoot, 'toolchains', 'ollama-0.40.5');
  const executable = path.join(directory, 'runtime', 'ollama.exe');
  const python = context.python || process.env.ECC_PYTHON || [path.join(root, '.venv', 'Scripts', 'python.exe'), path.join(codexRoot, 'ecc-validation-py', 'Scripts', 'python.exe')].find(file => fs.existsSync(file));
  if (!fs.existsSync(executable) || !python || !fs.existsSync(python)) throw new Error('Runtime ou Python ausente. Consulte docs/ECC-LOCAL.md.');
  fs.mkdirSync(path.join(directory, 'runtime-home'), { recursive: true });
  const outputDir = path.join(root, '.local-runtime');
  fs.mkdirSync(outputDir, { recursive: true });
  const port = await availablePort();
  const env = runtimeEnvironment(process.env, directory, port);
  env.PYTHONPATH = path.join(root, 'src');
  const logFile = path.join(outputDir, 'ollama.log');
  const log = fs.openSync(logFile, 'w');
  const server = spawn(executable, ['serve'], { cwd: directory, env, shell: false, windowsHide: true, stdio: ['ignore', log, log] });
  const serverClosed = new Promise(resolve => server.once('close', resolve));
  fs.closeSync(log);
  let serverError;
  server.once('error', error => { serverError = error; });
  let client;
  let clientClosed;
  const stop = () => { if (client && client.exitCode === null) client.kill(); if (server.exitCode === null) server.kill(); };
  process.once('SIGINT', stop);
  process.once('SIGTERM', stop);
  try {
    let ready = false;
    for (let attempt = 0; attempt < 60; attempt++) {
      if (serverError || server.exitCode !== null) throw new Error('Ollama nao iniciou; veja .local-runtime/ollama.log.');
      try {
        const response = await fetch(`http://127.0.0.1:${port}/api/version`, { signal: AbortSignal.timeout(500), redirect: 'error' });
        if (response.ok && (await response.json()).version === '0.40.5') { ready = true; break; }
      } catch { /* bounded readiness polling, no inference retry */ }
      await new Promise(resolve => setTimeout(resolve, 500));
    }
    if (!ready) throw new Error('Prazo excedido ao iniciar Ollama.');
    const smoke = args[0] === '--smoke';
    const structured = !action.prepare && (smoke || args[0] === '--batch-json');
    const command = action.prepare ? executable : python;
    const clientArgs = action.prepare ? ['pull', action.model] : ['-m', 'llm.cli.local', '--url', `http://127.0.0.1:${port}`, '--model', action.model, ...args];
    client = spawn(command, clientArgs,
      { cwd: root, env, shell: false, windowsHide: true, stdio: structured ? ['ignore', 'pipe', 'inherit'] : 'inherit' });
    clientClosed = new Promise(resolve => client.once('close', resolve));
    let output = '';
    if (structured) client.stdout.on('data', chunk => { output += chunk.toString('utf8'); if (Buffer.byteLength(output) > 16 * 1024 * 1024) client.kill(); });
    const deadline = setTimeout(stop, action.prepare ? 1800000 : 3340000);
    let code;
    try {
      code = await new Promise((resolve, reject) => { client.once('error', reject); client.once('close', resolve); });
    } finally { clearTimeout(deadline); }
    if (structured) {
      const result = JSON.parse(output);
      context.result = { ...result, runtimeOwnedByLauncher: true, cloudDisabled: true, allEccSurfacesVerified: false };
    }
    return typeof code === 'number' ? code : 1;
  } finally {
    stop();
    const waits = [serverClosed, ...(clientClosed ? [clientClosed] : [])];
    context.directProcessesTerminated = await Promise.race([
      Promise.all(waits).then(() => true),
      new Promise(resolve => { const timer = setTimeout(() => resolve(false), 5000); timer.unref(); }),
    ]);
    process.removeListener('SIGINT', stop);
    process.removeListener('SIGTERM', stop);
  }
}

function writeAtomic(file, value) {
  const temporary = `${file}.${randomUUID()}.tmp`;
  fs.writeFileSync(temporary, JSON.stringify(value, null, 2));
  fs.renameSync(temporary, file);
}

function preparationExitCode(code, directProcessesTerminated) {
  return code === 0 && directProcessesTerminated === true ? 0 : (code || 1);
}

async function main(args = process.argv.slice(2), options = {}) {
  const context = { root: options.root || path.resolve(__dirname, '..'), ...options };
  const smoke = args[0] === '--smoke';
  const batch = args[0] === '--batch-json';
  const structured = smoke || batch;
  const runId = randomUUID();
  const startedAt = new Date().toISOString();
  const outputDir = path.join(context.root, '.local-runtime');
  const latest = path.join(outputDir, batch ? 'latest-batch.json' : 'latest-acceptance.json');
  if (structured) {
    fs.mkdirSync(outputDir, { recursive: true });
    writeAtomic(latest, {runId, startedAt, state: 'running', passed: false, realInferenceVerified: false});
  }
  let code = 1;
  try { code = await runRuntime(args, context); }
  catch (error) {
    context.result = {passed: false, realInferenceVerified: false, code: 'LOCAL_RUNTIME_FAILED', errorType: error.name};
    console.error(`ECC local: ${error.message}`);
  }
  if (structured) {
    const result = {...context.result, requestRunId: context.result?.runId ?? null, runId, startedAt, checkedAt: new Date().toISOString(),
      directProcessesTerminated: context.directProcessesTerminated ?? true,
      descendantsTerminationVerified: false,
      terminationScope: 'Somente processos diretos pertencentes ao iniciador; descendentes nao afirmados.',
      allEccSurfacesVerified: false};
    result.passed = code === 0 && result.passed === true && result.directProcessesTerminated;
    result.state = result.passed ? 'completed' : (result.directProcessesTerminated ? 'failed' : 'unknown');
    writeAtomic(path.join(outputDir, `${batch ? 'batch' : 'acceptance'}-${runId}.json`), result);
    writeAtomic(latest, result);
    console.log(JSON.stringify(result, null, 2));
    if (!batch) console.log('Resultado salvo em .local-runtime/latest-acceptance.json');
    return result.passed ? 0 : 1;
  }
  return args[0] === '--prepare-model' ? preparationExitCode(code, context.directProcessesTerminated) : code;
}

module.exports = { runtimeEnvironment, validateArgs, parseAction, preparationExitCode, main };
if (require.main === module) main().then(code => { process.exitCode = code; }).catch(error => {
  console.error(`ECC local: ${error.message}`); process.exitCode = 1;
});
