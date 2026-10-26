const {app,BrowserWindow}=require('electron');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
app.whenReady().then(async()=>{
 const win=new BrowserWindow({show:false,width:1540,height:1100,webPreferences:{offscreen:true,backgroundThrottling:false,contextIsolation:true,nodeIntegration:false}});
 const js=code=>win.webContents.executeJavaScript(`(async()=>{${code}})()`);
 const shot=async name=>{await js(`document.getAnimations().forEach(a=>a.finish());$('#toast').className='toast';$('#toast').textContent='';$('#core-state').textContent='合成测试核心';$('#sidebar-account-list').textContent='合成测试账号';window.scrollTo(0,0);`);await new Promise(r=>setTimeout(r,300));fs.mkdirSync(path.join(__dirname,'../build/qa'),{recursive:true});fs.writeFileSync(path.join(__dirname,`../build/qa/${name}.png`),(await win.webContents.capturePage()).toPNG());};
 try{
  await win.loadFile(path.join(__dirname,'../src/desktop/renderer/index.html'));
  await js(`
   state.settings={activeModelProfileId:'a',modelProfiles:[{id:'a',name:'OpenAI',provider:'openai',baseUrl:'https://example.test/v1',model:'gpt-synthetic',hasApiKey:true,builtIn:true},{id:'b',name:'MiniMax 合成配置',provider:'anthropic',baseUrl:'https://example.test/anthropic/v1',model:'synthetic-M3',hasApiKey:true}],mediaProfiles:{vision:{model:'vision-synthetic',baseUrl:'https://example.test/v1',hasApiKey:true},speech:{}}};
   state.editingModelProfileId='a';window.qa={saved:[],confirmations:0};window.confirm=()=>{qa.confirmations++;return false;};
   window.qqInsight={officialPrices:async()=>({}),discoverModels:async()=>({models:Array.from({length:40},(_,i)=>'synthetic-model-'+i)}),saveSettings:async value=>{qa.saved.push(value);if(value.modelProfile){const p=value.modelProfile;state.settings.modelProfiles=state.settings.modelProfiles.map(v=>v.id===p.id?{...v,...p,apiKey:undefined,hasApiKey:true}:v);state.settings.activeModelProfileId=p.id;}return state.settings;},rpc:async method=>method==='ai.usage.list'?{items:[]}:{} };
   renderModelProfiles();showView('settings');
  `);
  assert.equal(await js(`return $('#model-advanced').open;`),false);
  assert.equal(await js(`return $('#settings-usage').hidden&&$('#settings-data').hidden&&!$('#analysis-api-card').hidden;`),true);
  assert.equal(await js(`return $('#delete-model-profile').disabled;`),true);
  await js(`document.querySelector('[data-profile-id="b"]').click();`);
  assert.equal(await js(`return $('#model-active-state').textContent;`),'未启用');
  assert.equal(await js(`return state.settings.activeModelProfileId;`),'a');
  await shot('api-settings-text');
  await js(`$('#model-api-key').value='synthetic-typed-only';$('#model-api-key').dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('[data-toggle-key="model-api-key"]').click();`);
  assert.equal(await js(`return $('#model-api-key').type;`),'text');
  await js(`document.querySelector('[data-settings-tab="usage"]').click();document.querySelector('[data-settings-tab="models"]').click();document.querySelector('[data-api-kind="vision"]').click();`);
  assert.equal(await js(`return $('#model-api-key').type;`),'password');
  assert.equal(await js(`return $('#model-api-key').value;`),'synthetic-typed-only');
  assert.equal(await js(`return $('#analysis-api-card').hidden&&!$('#media-api-card').hidden&&!document.querySelector('[data-media-form="vision"]').closest('section').hidden&&document.querySelector('[data-media-form="speech"]').closest('section').hidden;`),true);
  await shot('api-settings-vision');
  await js(`document.querySelector('[data-profile-id="b"]').click();document.querySelector('[data-profile-id="a"]').click();`);
  assert.equal(await js(`return state.editingModelProfileId;`),'b');assert.equal(await js(`return qa.confirmations;`),1);
  await js(`$('#model-api-key').value='';await saveModelProfile();`);
  assert.equal(await js(`return qa.saved.at(-1).modelProfile.apiKey;`),'');
  assert.equal(await js(`return $('#model-active-state').textContent;`),'当前使用');
  await js(`await discoverModelOptions();$('#model-search').value='model-39';$('#model-search').dispatchEvent(new Event('input',{bubbles:true}));`);
  assert.equal(await js(`return document.querySelectorAll('.model-result').length;`),1);
  await js(`document.querySelector('.model-result').click();`);
  assert.equal(await js(`return $('#model-id').value;`),'synthetic-model-39');
  await js(`settingsUI.textDirty=false;window.qqInsight.discoverModels=()=>new Promise(resolve=>qa.resolve=resolve);qa.pending=discoverModelOptions();document.querySelector('[data-profile-id="a"]').click();qa.resolve({models:['stale-should-not-appear']});await qa.pending;`);
  assert.equal(await js(`return $('#model-options').children.length;`),0);
  assert.equal(await js(`return $('#model-id').value;`),'gpt-synthetic');
  await js(`showSettingsPage('models');showAPIKind('text');$('#model-advanced').open=true;`);await shot('api-settings-advanced');
  for(const width of [1200,1540]){
   win.setSize(width,1100);await new Promise(r=>setTimeout(r,80));
   assert.equal(await js(`return document.documentElement.scrollWidth<=window.innerWidth;`),true);
   assert.equal(await js(`const r=$('#save-model-profile').getBoundingClientRect();return r.width>0&&r.right<=innerWidth;`),true);
  }
  console.log('API settings renderer passed: categories, one editor, active vs editing, encrypted-key omission, mask reset, unsaved-switch guard, searchable catalog, stale response isolation and 1200/1540 layouts; synthetic only.');
 }catch(error){console.error(error);process.exitCode=1;}finally{win.destroy();app.exit(process.exitCode||0);}
});
