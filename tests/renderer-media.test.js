const {app,BrowserWindow}=require('electron');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
app.whenReady().then(async()=>{
 const win=new BrowserWindow({show:false,width:1540,height:1120,webPreferences:{offscreen:true,backgroundThrottling:false,contextIsolation:true,nodeIntegration:false}});
 const js=code=>win.webContents.executeJavaScript(`(async()=>{${code}})()`);
 try{
  await win.loadFile(path.join(__dirname,'../src/desktop/renderer/index.html'));
  await js(`
   const price={basis:'official',unit:'token',provider:'合成服务商',region:'测试地域',input_price:0.8,output_price:2,currency:'CNY',verified_at:'2026-10-01',source:'https://example.test/pricing'};
   state.settings={activeModelProfileId:'synthetic',modelProfiles:[{id:'synthetic',name:'逻辑分析配置',provider:'openai-compatible',baseUrl:'https://example.test/v1',model:'synthetic-analysis-model',hasApiKey:true}],mediaProfiles:{vision:{baseUrl:'https://example.test/v1',model:'vision-model',hasApiKey:true},speech:{baseUrl:'https://example.test/v1',model:'speech-model',protocol:'qwen-asr',hasApiKey:true}}};
   window.qa={saved:[],offsets:[],tested:[]};
   window.qqInsight={saveSettings:async value=>{qa.saved.push(value);Object.assign(state.settings.mediaProfiles[value.mediaProfile.kind],value.mediaProfile);return state.settings;},officialPrices:async()=>({text:price,vision:price,speech:null}),discoverMediaModels:async()=>({models:['vision-model','speech-model','text-model'],capabilities:[{id:'vision-model',vision:true},{id:'speech-model',speech:true,speech_protocol:'qwen-asr'}]}),testMediaModel:async kind=>{qa.tested.push(kind);return {settings:state.settings,ok:true,message:'真实媒体识别测试通过'};},transcribeFile:async()=>({result:'合成转写文本'}),rpc:async(method,params)=>{
    if(method==='ai.usage.list'){qa.offsets.push(params.offset);return {has_more:params.offset===0,items:[{model:'合成文字模型',kind:'analysis',state:'completed',day:'2026-10-01',input_tokens:1200,output_tokens:300,cached_tokens:500,cost:0.002,pricing:price},{model:'未知定价模型',kind:'speech',state:'failed',day:'2026-10-01',input_tokens:null,output_tokens:null,cost:null}]};}
    return {};
   }};
   showView('settings');renderModelProfiles();await loadUsage();await loadOfficialPrices();
  `);
  await js("document.getAnimations().forEach(a=>a.finish());$('#toast').className='toast';$('#toast').textContent='';$('#core-state').textContent='合成测试核心';$('#sidebar-account-list').textContent='合成测试账号';");
  await new Promise(r=>setTimeout(r,500));fs.writeFileSync(path.join(__dirname,'../build/qa/analysis-api-settings.png'),(await win.webContents.capturePage()).toPNG());
  assert.match(await js(`return $('#ai-usage-body').textContent`),/费用未知/);
  assert.match(await js(`return $('#ai-usage-body').textContent`),/未返回/);
  assert.match(await js(`return $('#ai-usage-body').textContent`),/0.002000 CNY/);
  let models=await js(`await discoverMedia('vision');return [...$('#media-vision-candidates').options].map(o=>o.value);`);
  assert.deepEqual(models,['vision-model']);
  models=await js(`$('#media-vision-show-all').checked=true;renderMediaCandidates('vision');return $('#media-vision-candidates').options.length;`);assert.equal(models,3);
  await js(`await discoverMedia('speech');await testMediaModel('vision');await testMediaModel('speech');await loadUsage(30);`);
  assert.deepEqual(await js(`return qa.tested;`),['vision','speech']);
  assert.equal(await js(`return $('#ai-usage-next').disabled;`),true);
  assert.equal(await js(`return $('#ai-usage-prev').disabled;`),false);
  assert.equal(await js(`return qa.saved.every(v=>!!v.mediaProfile&&!v.modelProfile);`),true);
  await js(`$('#transcribe-file').click();`);await new Promise(r=>setTimeout(r,100));assert.equal(await js(`return $('#transcription-result').value;`),'合成转写文本');
  await js(`$('#media-model-settings').scrollIntoView({block:'start'});document.getAnimations().forEach(a=>a.finish());`);
  await new Promise(r=>setTimeout(r,200));fs.writeFileSync(path.join(__dirname,'../build/qa/media-settings.png'),(await win.webContents.capturePage()).toPNG());
  await js(`$('#ai-usage-body').scrollIntoView({block:'center'});`);await new Promise(r=>setTimeout(r,200));fs.writeFileSync(path.join(__dirname,'../build/qa/usage-ledger.png'),(await win.webContents.capturePage()).toPNG());
  console.log('Media renderer passed: independent forms, capability filtering, semantic tests, transcription, usage/unknown values, pagination.');
 }catch(error){console.error(error);process.exitCode=1;}finally{win.destroy();app.exit(process.exitCode||0);}
});
