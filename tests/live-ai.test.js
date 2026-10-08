// Explicit live verification: synthetic prompts only, keys remain in safeStorage.
const { app, safeStorage } = require('electron');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawn, spawnSync } = require('node:child_process');
const readline = require('node:readline');
const { SettingsStore } = require('../src/desktop/main/settings-store');
const { createAICoordinator } = require('../src/desktop/main/ai-coordinator');
app.setName('qq-insight-local');
app.setPath('userData',path.join(process.env.APPDATA,'qq-insight-local'));
app.whenReady().then(async()=>{
 const vision=process.env.QQ_AI_TEST_VISION==='1';
 let core;
 const outcomes=[];
 try {
  const data=fs.mkdtempSync(path.join(os.tmpdir(),'qq-ai-live-'));
  const seed=spawnSync('py',['-3.14','tests/ai-fixture.py',data],{windowsHide:true,encoding:'utf8'});
  if(seed.status!==0) throw new Error('SYNTHETIC_SETUP_FAILED');
  core=spawn('py',['-3.14','src/core/assistant_core.py','--data-dir',data],{windowsHide:true,stdio:['pipe','pipe','pipe'],env:{...process.env,PYTHONUTF8:'1'}});
  let next=0;const pending=new Map();
  readline.createInterface({input:core.stdout}).on('line',line=>{const value=JSON.parse(line);const waiter=pending.get(value.id);if(!waiter)return;pending.delete(value.id);clearTimeout(waiter.timer);value.error?waiter.reject(Object.assign(new Error(value.error.message),{code:value.error.code})):waiter.resolve(value.result);});
  const rpc=(method,params={})=>new Promise((resolve,reject)=>{const id=++next;const timer=setTimeout(()=>reject(new Error('CORE_TIMEOUT')),150000);pending.set(id,{resolve,reject,timer});core.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\n');});
  const saved=new SettingsStore(app,safeStorage);
  const original=saved.data.modelProfiles.find(item=>item.id===saved.data.activeModelProfileId);
  const profile={...original,model:process.env.QQ_AI_TEST_MODEL || (vision?'qwen-vl-plus':'deepseek-v3')};
  const testStore={data:{activeModelProfileId:profile.id,modelProfiles:[profile]},getModelApiKey:id=>saved.getModelApiKey(id)};
  const coordinator=createAICoordinator({rpc,settings:()=>testStore});
  for(const feature of (vision?['summary']:['work','summary','reply','collection','watch','profile'])){
   try {
    const result=await coordinator.run({conversation_id:'synthetic-group',account_id:'synthetic',feature,options:{mode:'recent',limit:100,goal:'礼貌确认第一组会按新截止时间提交',tone:'温和简洁'}});
    const history=await rpc('ai.history',{conversation_id:'synthetic-group',account_id:'synthetic',feature});
    if(result.status!=='completed'||!history.items.length)throw new Error('NO_VALID_ITEMS');
    if(feature==='reply'&&!history.items.some(item=>item.drafts.length))throw new Error('NO_REPLY_DRAFTS');
    if(feature==='work'&&history.items.some(item=>item.title.includes('收到')))throw new Error('ACK_AS_TASK');
    if(vision&&history.report.coverage.images_sent!==1)throw new Error('VISION_NOT_SENT');
    const second=await coordinator.run({conversation_id:'synthetic-group',account_id:'synthetic',feature,options:{mode:'recent',limit:100,goal:'礼貌确认第一组会按新截止时间提交',tone:'温和简洁'}});
    if(second.status!=='cached')throw new Error('CACHE_MISS');
    outcomes.push({feature,ok:true,items:history.items.length,usage:history.jobs[0].usage});
    console.log(JSON.stringify(outcomes.at(-1)));
   }catch(error){outcomes.push({feature,ok:false,code:error.code||error.message});console.log(JSON.stringify(outcomes.at(-1)));break;}
  }
  const ok=outcomes.length===(vision?1:7)&&outcomes.every(item=>item.ok);
  fs.mkdirSync('build/qa',{recursive:true});fs.writeFileSync(vision?'build/qa/live-vision.json':'build/qa/live-ai.json',JSON.stringify({date:new Date().toISOString(),model:profile.model,ok,outcomes},null,2));
  if(ok&&!vision&&process.env.QQ_AI_FIX_MODEL==='1'){
   saved.save({modelProfile:{id:profile.id,name:profile.name,provider:profile.provider,baseUrl:profile.baseUrl,model:profile.model}});
   console.log('Configured model corrected after seven successful synthetic analyses.');
  }
  if(!ok)process.exitCode=1;
 }catch(error){console.log(JSON.stringify({ok:false,code:error.code||'LIVE_TEST_FAILED'}));process.exitCode=1;}
 finally{core?.kill();app.quit();}
});
