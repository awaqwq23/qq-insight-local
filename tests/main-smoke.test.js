// Actual main/preload/renderer/core integration with an isolated synthetic app directory.
const { app, BrowserWindow }=require('electron');
const {spawnSync}=require('node:child_process');
const fs=require('node:fs');const os=require('node:os');const path=require('node:path');const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');const folder=fs.mkdtempSync(path.join(os.tmpdir(),'qq-main-smoke-'));
app.setPath('userData',folder);app.getAppPath=()=>root;
const python=process.env.QQ_INSIGHT_PYTHON||'py';
const seeded=spawnSync(python,[...(/^py(?:\.exe)?$/i.test(path.basename(python))?['-3.14']:[]),path.join(__dirname,'ai-fixture.py'),path.join(folder,'data')],{windowsHide:true,encoding:'utf8'});
if(seeded.status!==0)throw new Error('SYNTHETIC_SETUP_FAILED');
const deadline=setTimeout(()=>{console.error('Integration startup timed out');process.exitCode=1;app.quit();},20000);
app.on('browser-window-created',(_,win)=>{
 win.hide();
 win.webContents.once('did-finish-load',async()=>{
  try{
   const result=await win.webContents.executeJavaScript(`(async()=>{
    for(let i=0;i<100&&!state.settings;i++)await new Promise(r=>setTimeout(r,30));
    const health=await window.qqInsight.rpc('system.health');
    state.settings.activeAccountId='synthetic';state.settings.activePlatform='qq';
    const conversations=await window.qqInsight.rpc('conversation.list',{account_id:'synthetic',platform:'qq'});
    state.conversations=conversations.items;
    await openGroupAI('synthetic-group','settings');
    const role=document.querySelector('#group-ai-role').value;
    await setAITab('history');
    let blocked=false;try{await window.qqInsight.rpc('ai.prepare',{});}catch{blocked=true;}
    let privateBlocked=0;for(const method of ['ai.call.reserve','ai.call.settle','ai.call.reuse','ai.media.save'])try{await window.qqInsight.rpc(method,{});}catch{privateBlocked++;}
    const ledger=await window.qqInsight.rpc('ai.usage.list',{limit:30});
    const prices=await window.qqInsight.officialPrices();
    showView('settings');await loadUsage();await loadAIBudget();
    const savedMaximum=await saveAIBudget(null,true);
    const savedBudget=await window.qqInsight.rpc('ai.budget.get');
    return {version:health.version,role,features:groupAI.catalog.length,blocked,scope:groupAI.conversation.id,privateBlocked,ledgerEmpty:ledger.items.length===0,mediaForms:document.querySelectorAll('[data-media-form]').length,pricingKeys:Object.keys(prices),savedMaximum,dailyBudget:savedBudget.daily_tokens,outputBudget:savedBudget.output_tokens};
   })()`);
   assert.equal(result.version,'0.5.0-rel');assert.equal(result.features,7);assert.equal(result.role,'第一组组长');assert.equal(result.scope,'synthetic-group');assert.equal(result.blocked,true);
   assert.equal(result.privateBlocked,4);assert.equal(result.ledgerEmpty,true);assert.equal(result.mediaForms,2);assert.deepEqual(result.pricingKeys,['text','vision','speech']);
   assert.equal(result.savedMaximum,true);assert.equal(result.dailyBudget,100000000);assert.equal(result.outputBudget,4096);
   console.log('Actual main/preload/core integration passed: startup, group role, paged history, seven prompts and private RPC boundary.');
  }catch(error){console.error(error);process.exitCode=1;}finally{clearTimeout(deadline);app.quit();if(process.exitCode)app.exit(process.exitCode);}
 });
});
try { if(process.env.QQ_TEST_PACKAGED==='1'){
 Object.defineProperty(app,'isPackaged',{value:true});
 Object.defineProperty(process,'resourcesPath',{value:path.join(root,'build/rel-staging/win-unpacked/resources')});
 require(path.join(process.resourcesPath,'app.asar/src/desktop/main/main.js'));
}else require('../src/desktop/main/main');
} catch(error){console.error(error);process.exit(1);}
