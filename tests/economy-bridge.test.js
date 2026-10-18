const test=require('node:test');
const assert=require('node:assert/strict');
const {run}=require('../scripts/economy-bridge.cjs');
test('missing optional partner never starts inference',()=>{
  assert.throws(()=>run([]),/token-economy-root/);
  assert.throws(()=>run(['--token-economy-root','nonexistent-partner']),/ausente/);
  assert.throws(()=>run(['--shell','whoami']),/invalidos/);
});
