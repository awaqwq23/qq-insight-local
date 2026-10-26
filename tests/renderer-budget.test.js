const {app,BrowserWindow}=require('electron');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
app.whenReady().then(async()=>{
 const win=new BrowserWindow({show:false,width:1540,height:1120,webPreferences:{offscreen:true,backgroundThrottling:false,contextIsolation:true,nodeIntegration:false}});
 const js=code=>win.webContents.executeJavaScript(`(async()=>{${code}})()`);
 try{
  await win.loadFile(path.join(__dirname,'../src/desktop/renderer/index.html'));
  await js(`
   state.settings={modelProfiles:[]};
   window.qa={budget:{per_run_tokens:100000,daily_tokens:300000,monthly_tokens:3000000,output_tokens:4096,monthly_cost:0,currency:'CNY',daily_used:280000,monthly_used:280000},saves:[],fail:false,delay:false};
   window.qqInsight={officialPrices:async()=>({}),rpc:async(method,params)=>{
    if(method==='ai.budget.get'){if(qa.delay)return new Promise(resolve=>qa.resolve=()=>resolve({...qa.before}));return {...qa.budget};}
    if(method==='ai.budget.save'){qa.saves.push(params.settings);if(qa.fail)throw new Error('合成保存失败');qa.budget={...qa.budget,...params.settings};return {...qa.budget};}
    return {};
   }};
   showView('settings');showSettingsPage('usage');await loadAIBudget();
  `);
  const invalid=await js(`$('#budget-per-run').value=1000000000;return {saved:await saveAIBudget(),status:$('#ai-budget-status').textContent,count:qa.saves.length};`);
  assert.equal(invalid.saved,false);assert.match(invalid.status,/预算未保存/);assert.equal(invalid.count,0);
  const maximum=await js(`await saveAIBudget(null,true);return {saved:qa.saves.at(-1),status:$('#ai-budget-status').textContent};`);
  assert.equal(maximum.saved.per_run_tokens,10000000);assert.equal(maximum.saved.daily_tokens,100000000);assert.equal(maximum.saved.monthly_tokens,1000000000);
  assert.equal(maximum.saved.output_tokens,4096);assert.equal(maximum.saved.monthly_cost,0);assert.match(maximum.status,/已保存并生效/);
  assert.equal(await js(`$('#budget-output').value=65536;return await saveAIBudget();`),true);
  assert.equal(await js(`return qa.saves.at(-1).output_tokens;`),65536);
  assert.equal(await js(`return $('#budget-output').max;`),'1000000');
  await js(`state.settings.modelProfiles=[{id:'synthetic',limits:{output_tokens:4096}}];state.settings.activeModelProfileId='synthetic';renderAIBudget(qa.budget);`);
  assert.match(await js(`return $('#budget-effective-output').textContent;`),/预算 65,536.*当前模型 4,096.*实际单次最多 4,096/);
  await js(`state.settings.modelProfiles[0].limits.output_tokens=65536;renderAIBudget(qa.budget);`);
  assert.match(await js(`return $('#budget-effective-output').textContent;`),/实际单次最多 65,536/);
  const failure=await js(`qa.fail=true;await saveAIBudget();return {status:$('#ai-budget-status').textContent,disabled:$('#budget-use-maximum').disabled};`);
  assert.match(failure.status,/预算未保存.*合成保存失败/);assert.equal(failure.disabled,false);
  const stale=await js(`qa.fail=false;qa.delay=true;qa.before={...qa.budget,daily_tokens:300000};const load=loadAIBudget();await saveAIBudget(null,true);qa.resolve();await load;return $('#budget-daily').value;`);
  assert.equal(stale,'100000000');
  const edited=await js(`const load=loadAIBudget();$('#budget-daily').value='500000';$('#budget-daily').dispatchEvent(new Event('input',{bubbles:true}));qa.resolve();await load;return {value:$('#budget-daily').value,status:$('#ai-budget-status').textContent};`);
  assert.equal(edited.value,'500000');assert.match(edited.status,/尚未保存/);
  await js(`qa.delay=false;await saveAIBudget(null,true);$('#ai-budget-form').scrollIntoView({block:'center'});document.getAnimations().forEach(a=>a.finish());$('#toast').className='toast';$('#toast').textContent='';$('#core-state').textContent='合成测试核心';$('#sidebar-account-list').textContent='合成测试账号';`);
  await new Promise(r=>setTimeout(r,400));fs.writeFileSync(path.join(__dirname,'../build/qa/budget-settings.png'),(await win.webContents.capturePage()).toPNG());
  console.log('Budget renderer passed: invalid input, saved maximum, output preserved, persistent error, stale reads and edit protection.');
 }catch(error){console.error(error);process.exitCode=1;}finally{win.destroy();app.exit(process.exitCode||0);}
});
