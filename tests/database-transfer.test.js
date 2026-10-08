const assert = require('node:assert/strict');
const { registerDatabaseTransfer } = require('../src/desktop/main/database-transfer');

(async () => {
  const handlers = new Map();
  const calls = [];
  let active = null;
  let settingsValue = {};
  let cancel = false;
  const progress = [];
  registerDatabaseTransfer({
    ipcMain: { handle: (name, fn) => handlers.set(name, fn) },
    dialog: {
      showOpenDialog: async () => ({ canceled: cancel, filePaths: ['C:\\synthetic\\renamed.qqdb'] }),
      showSaveDialog: async () => ({ canceled: cancel, filePath: 'C:\\synthetic\\backup.db' }),
    },
    window: () => ({ isDestroyed: () => false, webContents: { send: (...args) => progress.push(args) } }),
    rpc: async (method, params) => {
      assert.equal(active.cancellable, false);
      calls.push({ method, params });
      active.progress('synthetic progress');
      return method === 'archive.export' ? { status: 'exported', message_count: 10 } : { status: 'merged', account_ids: ['synthetic'] };
    },
    settings: () => ({ save: value => { settingsValue = value; }, publicValue: () => settingsValue }),
    getOperation: () => active, setOperation: value => { active = value; }, ipcSafe: handler => handler,
  });
  const invoke = (name, value) => handlers.get(name)(null, value);
  await assert.rejects(invoke('database:pick', 'unknown'));
  const file = await invoke('database:pick', 'qq_encrypted');
  assert.equal(file.name, 'renamed.qqdb');
  assert.equal(file.path, undefined);
  await assert.rejects(invoke('database:import', { token: 'arbitrary-path', format: 'qq_encrypted' }));
  await assert.rejects(invoke('database:import', { token: file.token, format: 'app_db' }));
  active = {};
  await assert.rejects(invoke('database:import', { token: file.token, format: 'qq_encrypted' }));
  active = null;
  const result = await invoke('database:import', { token: file.token, format: 'qq_encrypted', accountId: 'synthetic', databaseKey: '0123456789abcdef' });
  assert.equal(result.settings.activeAccountId, 'synthetic');
  assert.equal(calls[0].method, 'source.manual_import');
  assert.equal(calls[0].params.database_key, '0123456789abcdef');
  assert.equal(settingsValue.databaseKey, undefined);
  assert.equal(active, null);
  assert.equal(progress[0][1].sourceId, 'manual-transfer');
  await invoke('database:export');
  assert.equal(calls[1].method, 'archive.export');
  cancel = true;
  assert.equal(await invoke('database:export'), null);
  assert.equal(calls.length, 2);
  console.log('database transfer: token binding, scope, key non-persistence, progress, concurrency and cancel passed');
})().catch(error => { console.error(error); process.exitCode = 1; });
