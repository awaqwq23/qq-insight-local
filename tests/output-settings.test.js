const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
const {SettingsStore}=require('../src/desktop/main/settings-store');
const {createOutputSettings}=require('../src/desktop/main/output-settings');

async function main(){
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'output-save-'));
 const safe={isEncryptionAvailable:()=>true,encryptString:value=>Buffer.from(value),decryptString:value=>value.toString()};
 const open=()=>new SettingsStore({getPath:()=>folder},safe),store=open();
 const profile={id:'synthetic-output',name:'合成模型',provider:'openai-compatible',baseUrl:'https://api.deepseek.com/v1',model:'deepseek-flash',limits:{context_tokens:1048576,output_tokens:65536},apiKey:'synthetic-key'};
 store.save({modelProfile:profile});let budget={per_run_tokens:10000000,daily_tokens:100000000,monthly_tokens:1000000000,output_tokens:65536};
 let failCore=false,failRollback=false,saves=0;
 const rpc=async(method,input)=>{
  if(method==='ai.budget.get')return structuredClone(budget);
  assert.equal(method,'ai.budget.save');saves++;
  if(failCore){failCore=false;throw new Error('synthetic-core-save');}
  if(failRollback&&budget.output_tokens===131072&&input.settings.output_tokens===65536){failRollback=false;throw new Error('synthetic-rollback');}
  budget={...budget,...input.settings};return structuredClone(budget);
 };
 const link=createOutputSettings({store,rpc});
 try{
  const first=await link.saveBudget({output_tokens:131072});
  assert.equal(first.output_tokens,131072);assert.equal(first.model_output.limits.output_tokens,131072);
  assert.equal(open().data.modelProfiles.find(p=>p.id===profile.id).limits.output_tokens,131072,'survives settings restart');
  assert.equal(store.getModelApiKey(profile.id),'synthetic-key');
  const {apiKey,...publicProfile}=profile;
  await link.saveSettings({modelProfile:{...publicProfile,limits:{...profile.limits,output_tokens:65536}}});
  assert.equal(budget.output_tokens,65536,'model editor also updates the global output');
  assert.equal(store.data.modelProfiles.find(p=>p.id===profile.id).limits.output_tokens,65536);
  const old=structuredClone(store.data),oldBudget=structuredClone(budget),count=saves;
  await assert.rejects(link.saveBudget({output_tokens:500000}),/超过/);
  assert.equal(saves,count);assert.deepEqual(store.data,old);assert.deepEqual(budget,oldBudget);
  failCore=true;await assert.rejects(link.saveBudget({output_tokens:131072}),/synthetic-core-save/);
  assert.deepEqual(store.data,old);assert.deepEqual(budget,oldBudget);
  const persist=store.persist;store.persist=()=>{throw new Error('synthetic-disk-save');};
  await assert.rejects(link.saveBudget({output_tokens:131072,daily_tokens:90000000}),/synthetic-disk-save/);
  store.persist=persist;assert.deepEqual(store.data,old);assert.deepEqual(budget,oldBudget,'rolls back every changed budget field');
  assert.equal(open().data.modelProfiles.find(p=>p.id===profile.id).limits.output_tokens,65536);
  store.persist=()=>{throw new Error('synthetic-disk-save');};failRollback=true;
  await assert.rejects(link.saveBudget({output_tokens:131072}),/回滚也未完成/);
  store.persist=persist;assert.equal(budget.output_tokens,131072);assert.deepEqual(store.data,old);
  await link.saveBudget({output_tokens:65536});assert.equal(budget.output_tokens,65536);
  await Promise.all([link.saveBudget({output_tokens:131072}),link.saveBudget({output_tokens:65536})]);
  assert.equal(budget.output_tokens,65536);assert.equal(store.data.modelProfiles.find(p=>p.id===profile.id).limits.output_tokens,65536);
  assert.equal(store.getModelApiKey(profile.id),'synthetic-key');
  console.log('Output settings passed: linked editors, restart, key preservation, model/context bounds, core failure, disk rollback and serialized saves; synthetic only.');
 }finally{assert.equal(path.dirname(path.resolve(folder)),path.resolve(os.tmpdir()));fs.rmSync(folder,{recursive:true,force:true});}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
