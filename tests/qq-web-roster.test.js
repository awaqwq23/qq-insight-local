const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');
const { readOfficialRoster, collectMembers, isMemberPage, allowedNavigation, allowedManagerRequest } = require('../src/desktop/main/qq-web-roster');
const { registerRosterExport } = require('../src/desktop/main/roster-export');
const member = n => ({ uin: 100000+n, nick: `synthetic ${n}`, card: n ? '' : '合成群名片' });
const page = (rows, count=rows.length) => ({ ec: 0, count, mems: rows });

(async () => {
  const rows = Array.from({length:43}, (_, i) => member(i));
  const offsets = [], checks = [];
  const result = await collectMembers(async (start,end) => { offsets.push([start,end]);return page(rows.slice(start,end+1),rows.length); }, async () => checks.push(true), () => {}, async () => {});
  assert.deepEqual(offsets,[[0,20],[21,41],[42,62]]);
  assert.equal(checks.length,6); assert.equal(result.count,43);
  assert.equal(result.members[0].nickname,'synthetic 0'); assert.equal(result.members[0].card,'合成群名片');
  for (const invalid of [null,{ec:1},page([],0),page([],2),page([member(0),member(0)]),page([{uin:'100000',nick:1}]),page([{uin:Number.MAX_SAFE_INTEGER+1,nick:'x'}]),page([{uin:'100000',nick:'x',card:{}}])]) {
    await assert.rejects(collectMembers(async () => invalid, async () => {}, () => {}, async () => {}));
  }
  await assert.rejects(collectMembers(async start=>page(start?rows.slice(21,22):rows.slice(0,21),start?23:22),async()=>{},()=>{},async()=>{}),/人数发生变化/);
  await assert.rejects(collectMembers(async start=>page(start?[member(0)]:rows.slice(0,21),22),async()=>{},()=>{},async()=>{}),/重复/);
  await assert.rejects(collectMembers(async()=>page([member(0)]),async()=>{throw Error('wrong account')},()=>{},async()=>{}),/wrong account/);
  assert(isMemberPage('https://qun.qq.com/member.html#gid=900001'));
  assert(!isMemberPage('https://qun.qq.com.evil.test/member.html'));
  assert(!allowedNavigation('file:///local'));
  assert(!allowedNavigation('https://evil.test'));
  assert(allowedNavigation('https://xui.ptlogin2.qq.com/cgi-bin/xlogin'));
  for (const endpoint of ['set_group_card','delete_group_member','set_group_admin','get_friend_list']) assert(!allowedManagerRequest('https://qun.qq.com/cgi-bin/qun_mgr/'+endpoint,'POST'));
  assert(allowedManagerRequest('https://qun.qq.com/cgi-bin/qun_mgr/search_group_members','POST'));
  assert(!allowedManagerRequest('http://qun.qq.com/cgi-bin/qun_mgr/search_group_members','POST'));

  let fake, wrongAccount=false;
  class FakeWindow extends EventEmitter {
    constructor(options) {
      super(); fake=this;this.options=options;this.dead=false;this.cleared=false;this.cacheCleared=false;
      this.webContents=new EventEmitter();
      this.webContents.session={setPermissionRequestHandler:()=>{},setPermissionCheckHandler:()=>{},on:()=>{},
        webRequest:{onBeforeRequest:(_,fn)=>this.filter=fn},
        cookies:{get:async()=>[{name:'uin',value:wrongAccount?'o10000002':'o010000001'},{name:'skey',value:'synthetic-only'}]},
        clearStorageData:async()=>this.cleared=true,clearCache:async()=>this.cacheCleared=true};
      this.webContents.setWindowOpenHandler=()=>{};
      this.webContents.getURL=()=> 'https://qun.qq.com/member.html';
      this.webContents.executeJavaScript=async code=>code.startsWith('Boolean')?true:page([member(0)]);
    }
    async loadURL() {} isDestroyed(){return this.dead} setTitle(){}
    destroy(){this.dead=true;this.emit('closed')}
  }
  const scope={account_id:'10000001',group_qq:'900001'};
  const snapshot=await readOfficialRoster({BrowserWindow:FakeWindow,parent:null,scope});
  assert.equal(snapshot.count,1);assert.equal(snapshot.account_id,scope.account_id);
  assert(fake.dead&&fake.cleared&&fake.cacheCleared);
  assert(!fake.options.webPreferences.partition.startsWith('persist:'));
  assert.equal(fake.options.webPreferences.nodeIntegration,false);assert(fake.options.webPreferences.sandbox);
  wrongAccount=true;
  await assert.rejects(readOfficialRoster({BrowserWindow:FakeWindow,parent:null,scope}),/账号不一致/);
  assert(fake.dead&&fake.cleared&&fake.cacheCleared);

  const handlers = new Map(), calls = [];
  let cancel=false, fail=false, release;
  registerRosterExport({ipcMain:{handle:(name,fn)=>handlers.set(name,fn)},ipcSafe:fn=>fn,window:()=>null,
    dialog:{showSaveDialog:async()=>({canceled:cancel,filePath:'native-selected.csv'})},
    rpc:async(method,params)=>{calls.push({method,params});return method==='roster.scope'?{account_id:'10000001',group_qq:'900001'}:{count:43}},
    readOnline:async()=>{if(fail)throw Error('website denied');if(release)await new Promise(resolve=>release=resolve);return {...result,account_id:'10000001',group_qq:'900001'}}});
  const input={account_id:'10000001',conversation_id:'group',platform:'qq',path:'untrusted.csv',online:{members:[]}};
  const run=()=>handlers.get('roster:export-full')(null,input);
  await run();
  assert.equal(calls[1].params.path,'native-selected.csv');assert.equal(calls[1].params.online.members.length,43);
  assert.equal(calls[1].params.kind,'full_members');
  cancel=true;assert.equal(await run(),null);assert.equal(calls.length,3);
  cancel=false;fail=true;await assert.rejects(run(),/website denied/);fail=false;
  release=true;const pending=run();await new Promise(resolve=>setImmediate(resolve));await assert.rejects(run(),/已有官网/);release();await pending;
  console.log('QQ web roster passed: pagination, completeness, account checks, duplicates, navigation, read-only endpoints, trusted path, cancellation, failure and concurrency.');
})().catch(error=>{console.error(error);process.exitCode=1;});
