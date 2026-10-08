const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { prepareQQDatabase, sourceSignature, waitForDatabaseSettled, delay } = require('../src/desktop/main/qq-session');

(async () => {
  const calls = [];
  const dependencies = {
    stopQQ: async () => calls.push('stop'),
    waitForDatabaseSettled: async () => calls.push('settle'),
    syncQQBeforeImport: async () => calls.push('online'),
  };
  await prepareQQDatabase({ sourcePath: 'synthetic.db' }, dependencies);
  assert.deepEqual(calls, ['stop', 'settle']);
  calls.length = 0;
  await prepareQQDatabase({ sourcePath: 'synthetic.db', syncOnline: true }, dependencies);
  assert.deepEqual(calls, ['online']);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'qq-session-test-'));
  try {
    const source = path.join(dir, 'synthetic.db');
    fs.writeFileSync(source, 'synthetic only');
    const baseline = sourceSignature(source);
    fs.writeFileSync(`${source}-shm`, 'lock activity');
    assert.equal(sourceSignature(source), baseline);
    fs.writeFileSync(`${source}-wal`, 'new synthetic messages');
    assert.notEqual(sourceSignature(source), baseline);
    const controller = new AbortController();
    controller.abort();
    await assert.rejects(delay(1000, controller.signal), { code: 'SOURCE_UPDATE_CANCELLED' });
    await assert.rejects(waitForDatabaseSettled(source, { signal: controller.signal }), { code: 'SOURCE_UPDATE_CANCELLED' });
    await waitForDatabaseSettled(source, { quietMs: 0 });
    fs.writeFileSync(`${source}-journal`, 'busy');
    await assert.rejects(waitForDatabaseSettled(source, { timeoutMs: 1 }), { code: 'SOURCE_STILL_BUSY' });
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
  console.log('QQ session tests passed: local/online, SHM/WAL, cancellation, busy database');
})().catch((error) => { console.error(error); process.exitCode = 1; });
