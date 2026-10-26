// Explicit opt-in: secrets travel over a private pipe and are encrypted by Electron safeStorage.
const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process');
const electron=require('electron');
if(typeof electron==='string'){
 let raw='';process.stdin.setEncoding('utf8');if(process.stdin.isTTY)process.stdin.setRawMode(true);
 process.stdin.on('data',chunk=>{raw+=chunk;try{JSON.parse(raw);}catch{return;}process.stdin.pause();if(process.stdin.isTTY)process.stdin.setRawMode(false);const child=cp.spawn(electron,[__filename],{windowsHide:true,env:{...process.env,QQ_INSIGHT_PRIVATE_PROFILE_INPUT:raw},stdio:['ignore','inherit','inherit']});raw='';child.on('exit',code=>{process.exitCode=code||0;});});console.log('READY_FOR_CREDENTIALS');
}else{
 const {app,safeStorage}=electron;app.setPath('userData',path.join(app.getPath('appData'),'qq-insight-local'));
 let raw=process.env.QQ_INSIGHT_PRIVATE_PROFILE_INPUT||'',stage='input';delete process.env.QQ_INSIGHT_PRIVATE_PROFILE_INPUT;(async()=>{try{
  const input=JSON.parse(raw);raw='';await app.whenReady();if(!safeStorage.isEncryptionAvailable())throw new Error('ENCRYPTION_UNAVAILABLE');
  stage='store';const {SettingsStore}=require('../src/desktop/main/settings-store');const store=new SettingsStore(app,safeStorage),active=store.data.activeModelProfileId;
  stage='receipt';const receipt=JSON.parse(fs.readFileSync(path.join(__dirname,'../build/qa/live-volume-local-strong-hierarchical.json'),'utf8'));
  if(receipt.provider!=='sorux'||receipt.scope!=='local-imported'||receipt.largest_input_tokens<1||receipt.largest_chunk_messages<1)throw new Error('RECEIPT_UNAVAILABLE');
  stage='save';store.save({modelProfile:{id:'sorux-live',name:'ChatGPT 受限测试（可继续历史任务）',provider:'custom',protocol:'responses',baseUrl:'https://app.soruxgpt.com/api/codex',model:receipt.model,apiKey:input.apiKey,limits:{context_tokens:32768,tpm_tokens:0,output_tokens:2048}},activeModelProfileId:active});input.apiKey='';
  const profile=store.data.modelProfiles.find(p=>p.id==='sorux-live'),fingerprint=require('../src/desktop/main/model-capabilities').configurationFingerprint(profile);
  store.recordCapacityTest(profile.id,fingerprint,{fingerprint,at:receipt.at,input_source:'local-imported',compression:'strong',successful_messages:receipt.largest_chunk_messages,successful_input_tokens:receipt.largest_input_tokens,input_measured:true,successful_request_bytes:receipt.largest_request_bytes,reported_context_tokens:null,reason:'本次测试约29.59美元，已停止继续消费；原文1001条完成，轻度3001条及分段强力5001条仍未全部完成',estimated_10000_tokens:null},0);
  console.log(JSON.stringify({saved:true,encrypted:true,active_profile_preserved:store.data.activeModelProfileId===active,recommended_messages:store.publicValue().modelProfiles.find(p=>p.id==='sorux-live').limits.recommended_messages}));app.quit();
 }catch(error){console.log(JSON.stringify({code:'PROFILE_SAVE_FAILED',stage,kind:error.name}));app.exit(1);}})();
}
