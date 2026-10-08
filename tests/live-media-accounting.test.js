const {app,safeStorage}=require('electron');
const fs=require('node:fs');const os=require('node:os');const path=require('node:path');const assert=require('node:assert/strict');
const {spawn,spawnSync}=require('node:child_process');const readline=require('node:readline');
const {SettingsStore}=require('../src/desktop/main/settings-store');
const {testMedia}=require('../src/desktop/main/media-gateway');
const {createAICoordinator}=require('../src/desktop/main/ai-coordinator');
const {configurationFingerprint}=require('../src/desktop/main/model-capabilities');
app.setName('qq-insight-local');app.setPath('userData',path.join(process.env.APPDATA,'qq-insight-local'));
app.whenReady().then(async()=>{
 let core;const result={date:new Date().toISOString(),tests:[]};
 try{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'qq-media-live-'));const seed=spawnSync('py',['-3.14','tests/ai-fixture.py',dir],{windowsHide:true,encoding:'utf8',env:{...process.env,QQ_AI_TEST_VISION:'1'}});assert.equal(seed.status,0);
  core=spawn('py',['-3.14','src/core/assistant_core.py','--data-dir',dir],{windowsHide:true,stdio:['pipe','pipe','pipe'],env:{...process.env,PYTHONUTF8:'1'}});
  let index=0;const waiting=new Map();
  readline.createInterface({input:core.stdout}).on('line',line=>{const value=JSON.parse(line);const request=waiting.get(value.id);if(request){waiting.delete(value.id);clearTimeout(request.timer);value.error?request.reject(Object.assign(new Error(value.error.message),{code:value.error.code})):request.resolve(value.result);}});
  const rpc=(method,params={})=>new Promise((resolve,reject)=>{const id=++index;const timer=setTimeout(()=>reject(new Error('CORE_TIMEOUT')),150000);waiting.set(id,{resolve,reject,timer});core.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\n');});
  const saved=new SettingsStore(app,safeStorage);const active=saved.data.modelProfiles.find(item=>item.id===saved.data.activeModelProfileId);
  const profiles={vision:{...active,model:'qwen-vl-plus',protocol:'chat'},speech:{...active,model:'qwen3-asr-flash',protocol:'qwen-asr'}};
  const store={data:{...saved.data,mediaProfiles:profiles},getModelApiKey:id=>saved.getModelApiKey(id),getMediaApiKey:()=>saved.getModelApiKey(active.id),recordMediaTest:()=>{},publicValue:()=>({})};
  for(const kind of ['vision','speech']){const tested=await testMedia({store,rpc,kind});assert.equal(tested.ok,true,kind);result.tests.push({kind,ok:true,usage:tested.usage,official_price:tested.pricing});console.log(JSON.stringify({kind,ok:true}));}
  const coordinator=createAICoordinator({rpc,settings:()=>store});
  await rpc('group.save',{conversation_id:'synthetic-group',account_id:'synthetic',settings:{images:false,watch_people:['100001','100002','999999']}});
  const input={conversation_id:'synthetic-group',account_id:'synthetic',feature:'watch',options:{mode:'recent',limit:99}};
  assert.equal((await coordinator.run(input)).status,'completed');
  const history=await rpc('ai.history',{conversation_id:'synthetic-group',account_id:'synthetic',feature:'watch'});
  assert.deepEqual(history.report.coverage.watch_people.map(p=>p.status),['completed','completed','no_messages']);
  assert.equal((await coordinator.run(input)).status,'cached');result.tests.push({kind:'watch_all',ok:true,targets:history.report.coverage.watch_people.length});console.log(JSON.stringify({kind:'watch_all',ok:true}));
  await rpc('group.save',{conversation_id:'synthetic-group',account_id:'synthetic',settings:{images:true}});
  assert.equal((await coordinator.run({...input,feature:'summary'})).status,'completed');
  const ledger=await rpc('ai.usage.list');
  assert.ok(ledger.items.some(call=>call.kind==='vision'&&call.model==='qwen-vl-plus'));
  assert.ok(ledger.items.some(call=>call.kind==='analysis'&&call.model===active.model));
  assert.ok(ledger.items.every(call=>call.cost!==null));
  result.tests.push({kind:'independent_vision_analysis',ok:true});
  result.calls=ledger.items.map(call=>({kind:call.kind,model:call.model,input_tokens:call.input_tokens,output_tokens:call.output_tokens,seconds:call.seconds,cost:call.cost,currency:call.pricing.currency,state:call.state}));
  if(process.env.QQ_AI_CONFIGURE_MEDIA==='1'){
   for(const kind of ['vision','speech'])if(!saved.data.mediaProfiles[kind].baseUrl){
    saved.save({mediaProfile:{kind,copyTextProfile:true}});
    saved.save({mediaProfile:{kind,provider:active.provider,baseUrl:active.baseUrl,model:profiles[kind].model,protocol:profiles[kind].protocol}});
    saved.recordMediaTest(kind,configurationFingerprint(saved.data.mediaProfiles[kind]),{ok:true,message:'真实媒体识别测试通过'});
   }
  }
  result.ok=true;console.log(JSON.stringify({kind:'independent_vision_analysis',ok:true,calls:ledger.items.length}));
 }catch(error){result.ok=false;result.error=error.code||error.message;console.log(JSON.stringify({ok:false,error:result.error}));process.exitCode=1;}
 finally{fs.writeFileSync('build/qa/live-media-accounting.json',JSON.stringify(result,null,2));core?.kill();app.exit(process.exitCode||0);}
});
