const assert = require('node:assert/strict');
const { registerRosterExport } = require('../src/desktop/main/roster-export');

(async () => {
  let canceled = false;
  const handlers = new Map();
  const calls = [];
  registerRosterExport({ ipcMain: { handle: (name, fn) => handlers.set(name, fn) },
    dialog: { showSaveDialog: async () => ({ canceled, filePath: 'synthetic.csv' }) }, window: () => null,
    rpc: async (method, params) => { calls.push({ method, params }); return { count: 2 }; }, ipcSafe: fn => fn });
  const input = { kind: 'members', account_id: 'synthetic', platform: 'qq', conversation_id: 'group', path: 'untrusted.csv' };
  const handler = handlers.get('roster:export');
  await handler(null, input);
  assert.deepEqual(calls[0], { method: 'roster.export', params: { kind: 'members', account_id: 'synthetic', platform: 'qq', conversation_id: 'group', path: 'synthetic.csv' } });
  canceled = true;
  assert.equal(await handler(null, input), null);
  assert.equal(calls.length, 1);
  for (const value of [null, {}, { ...input, kind: 'bad' }, { ...input, account_id: '' }, { ...input, conversation_id: '' }, { ...input, platform: 'wechat' }]) await assert.rejects(handler(null, value));
  const cachedHandlers=new Map(), cachedCalls=[];
  let accept=false;
  registerRosterExport({ipcMain:{handle:(n,f)=>cachedHandlers.set(n,f)},ipcSafe:f=>f,window:()=>null,
    dialog:{showMessageBox:async(_,options)=>{assert.equal(options.defaultId,1);return {response:accept?0:1}},showSaveDialog:async()=>({filePath:'cache.csv'})},
    rpc:async(method,params)=>{cachedCalls.push({method,params});return method==='roster.cache_info'?{count:2,expected_count:3,count_matches:false,imported_at:'stamp',note:'partial'}:{count:2}}});
  const cachedInput={...input,kind:'cached_members'};
  assert.equal(await cachedHandlers.get('roster:export')(null,cachedInput),null);
  assert.equal(cachedCalls.length,1);
  accept=true;await cachedHandlers.get('roster:export')(null,cachedInput);
  assert.equal(cachedCalls[2].params.cache_stamp,'stamp');assert.equal(cachedCalls[2].params.conversation_id,'group');
  console.log('Roster export passed: scope validation, native chosen path, cancellation.');
})().catch(error => { console.error(error); process.exitCode = 1; });
