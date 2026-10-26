const {app,BrowserWindow}=require('electron');const assert=require('node:assert/strict');const path=require('node:path');const fs=require('node:fs');
app.whenReady().then(async()=>{
 const win=new BrowserWindow({show:false,width:1500,height:1150,webPreferences:{offscreen:true,contextIsolation:true,nodeIntegration:false}});
 const js=code=>win.webContents.executeJavaScript(`(async()=>{${code}})()`);
 try{
  await win.loadFile(path.join(__dirname,'../src/desktop/renderer/index.html'));
  const settings={activeModelProfileId:'synthetic',modelProfiles:[{id:'synthetic',name:'合成模型',model:'synthetic',provider:'openai-compatible',baseUrl:'https://example.test/v1',limits:{context_tokens:32768,tpm_tokens:12000,output_tokens:4096,recommended_messages:16,source:'合成测试'}}]};
  await js(`state.settings=${JSON.stringify(settings)};state.editingModelProfileId='synthetic';window.qqInsight={modelLimits:async()=>({context_tokens:1000000,tpm_tokens:0,output_tokens:4096,recommended_messages:3000,source:'接口元数据'}),saveSettings:async input=>{qa.saved=input;return state.settings;},testCapacity:async input=>{qa.test=input;return {settings:state.settings};}};window.qa={};renderModelProfiles();showView('settings');`);
  assert.equal(await js(`return $('#model-context').value;`),'32768');
  assert.match(await js(`return $('#model-recommendation').textContent;`),/16/);
  await js(`$('#model-id').value='other';await refreshModelLimits();`);
  assert.equal(await js(`return $('#model-context').value;`),'1000000');
  await js(`renderCapacity({context_tokens:1048576,output_tokens:65536,output_limit_tokens:393216,source:'合成元数据'});`);
  assert.equal(await js(`return $('#model-output').value;`),'65536');
  assert.equal(await js(`return $('#model-output').max;`),'393216');
  assert.match(await js(`return $('#model-recommendation').textContent;`),/模型侧输出 65,536.*393,216/);
  await js(`$('#model-context').value=64000;$('#model-output').value=8192;$('#model-tpm').value=20000;$('#model-protocol').value='responses';await saveModelProfile();`);
  assert.equal(await js(`return qa.saved.modelProfile.limits.context_tokens;`),64000);
  assert.equal(await js(`return qa.saved.modelProfile.protocol;`),'responses');
  const editedDuringLookup=await js(`
   window.qqInsight.modelLimits=()=>new Promise(resolve=>qa.resolveLimits=resolve);
   $('#model-id').value='synthetic-delayed';refreshModelLimits();
   $('#model-context').value=1048576;$('#model-output').value=131072;$('#model-output').dispatchEvent(new Event('input',{bubbles:true}));
   const saving=saveModelProfile();qa.resolveLimits({context_tokens:1000000,output_tokens:8192,source:'合成旧查询'});await saving;
   return qa.saved.modelProfile.limits.output_tokens;
  `);
  assert.equal(editedDuringLookup,131072,'late capacity results must not replace the user output before save');
  const editedDuringSave=await js(`
   window.qqInsight.saveSettings=input=>new Promise(resolve=>{qa.saved=input;qa.resolveSave=()=>resolve(state.settings);});
   $('#model-context').value=1048576;$('#model-output').value=131072;const saving=saveModelProfile();
   $('#model-output').value=196608;$('#model-output').dispatchEvent(new Event('input',{bubbles:true}));qa.resolveSave();await saving;
   return {submitted:qa.saved.modelProfile.limits.output_tokens,current:$('#model-output').value,status:$('#model-edit-status').textContent};
  `);
  assert.equal(editedDuringSave.submitted,131072);assert.equal(editedDuringSave.current,'196608');assert.match(editedDuringSave.status,/未保存/);
  await js(`renderCapacity({context_tokens:32768,test:{input_source:'local-imported',successful_messages:652,successful_input_tokens:27254,reason:'受限验收预算上限',at:'2026-10-13'}});`);
  assert.match(await js(`return $('#model-capacity-status').textContent;`),/分别统计/);
  assert.doesNotMatch(await js(`return $('#model-capacity-status').textContent;`),/1万条合成/);
  const cancel=await js(`const waiting=confirmReadingLimit(100,16);const open=$('#capacity-warning').open;$('#capacity-warning-cancel').click();return {open,accepted:await waiting};`);
  assert.deepEqual(cancel,{open:true,accepted:false});
  assert.equal(await js(`const waiting=confirmReadingLimit(100,16);$('#capacity-warning-continue').click();return await waiting;`),true);
  await js(`renderModelProfiles();showView('settings');showSettingsPage('models');showAPIKind('text');$('#model-advanced').open=true;document.getAnimations().forEach(a=>a.finish());$('#toast').textContent='';$('#toast').className='toast';$('#model-context').scrollIntoView({block:'center'});`);
  await new Promise(resolve=>setTimeout(resolve,350));
  fs.writeFileSync(path.join(__dirname,'../build/qa/ai-capacity-settings.png'),(await win.webContents.capturePage()).toPNG());
  console.log('Capacity renderer passed: auto-filled limits, manual values, saved settings and warning cancel/continue.');
 }catch(error){console.error(error);process.exitCode=1;}finally{win.destroy();app.exit(process.exitCode||0);}
});
