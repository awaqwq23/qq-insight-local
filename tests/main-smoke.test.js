// Actual main/preload/renderer/core integration with an isolated synthetic app directory.
const { app, BrowserWindow }=require('electron');
const {spawnSync}=require('node:child_process');
const fs=require('node:fs');const os=require('node:os');const path=require('node:path');const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');const folder=fs.mkdtempSync(path.join(os.tmpdir(),'qq-main-smoke-'));
app.setPath('userData',folder);app.getAppPath=()=>root;
const python=process.env.QQ_INSIGHT_PYTHON||'py';
const seeded=spawnSync(python,[...(/^py(?:\.exe)?$/i.test(path.basename(python))?['-3.14']:[]),path.join(__dirname,'ai-fixture.py'),path.join(folder,'data'),'--recent-ai'],{windowsHide:true,encoding:'utf8'});
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
    const defaults=await window.qqInsight.rpc('group.save',{account_id:'synthetic',conversation_id:'synthetic-group',settings:{compression:'strong',output_chars:1234}});
    await setAITab('history');
    let blocked=false;try{await window.qqInsight.rpc('ai.prepare',{});}catch{blocked=true;}
    let privateBlocked=0;for(const method of ['ai.call.reserve','ai.call.settle','ai.call.reuse','ai.media.save','roster.scope','roster.export','workspace.attachment.add','workspace.attachment.data','workspace.attachment.observed','workspace.context.commit','ai.context'])try{await window.qqInsight.rpc(method,{});}catch{privateBlocked++;}
    const ledger=await window.qqInsight.rpc('ai.usage.list',{limit:30});
    const prices=await window.qqInsight.officialPrices();
    try{await window.qqInsight.rpc('ai.pricing.apply',{catalog:{}});throw new Error('PRIVATE_PRICING_RPC_ALLOWED');}catch(error){if(error.message==='PRIVATE_PRICING_RPC_ALLOWED')throw error;}
    showView('settings');await loadUsage();await loadAIBudget();
    const outputProfile={id:'synthetic-output',name:'合成输出模型',provider:'openai-compatible',baseUrl:'https://api.deepseek.com/v1',model:'deepseek-flash',limits:{context_tokens:1048576,output_tokens:65536}};
    state.settings=await window.qqInsight.saveSettings({activeAccountId:'synthetic',modelProfile:outputProfile});
    await loadAIBudget();$('#budget-output').value=131072;const outputSaved=await saveAIBudget();
    const linkedSettings=await window.qqInsight.getSettings();
    const linkedOutput=linkedSettings.modelProfiles.find(p=>p.id==='synthetic-output').limits.output_tokens;
    state.settings=await window.qqInsight.saveSettings({modelProfile:outputProfile});
    await loadAIBudget();
    const savedMaximum=await saveAIBudget(null,true);
    const savedBudget=await window.qqInsight.rpc('ai.budget.get');
    const chat=await window.qqInsight.rpc('workspace.chat.create',{account_id:'synthetic',title:'合成对话'});
    await window.qqInsight.rpc('workspace.chat.rename',{account_id:'synthetic',session_id:chat.id,title:'独立保存的合成对话'});
    const chats=await window.qqInsight.rpc('workspace.chat.list',{account_id:'synthetic'});
    const chatDetail=await window.qqInsight.rpc('workspace.chat.get',{account_id:'synthetic',session_id:chat.id});
    let chatPrivateBlocked=false;try{await window.qqInsight.rpc('workspace.begin',{account_id:'synthetic',question:'不应发起'});}catch{chatPrivateBlocked=true;}
    showView('ai-history');await loadRecentAIHistory();
    const recent=await window.qqInsight.rpc('workspace.chat.recent',{account_id:'synthetic'});
    const savedHistory=recent.items.find(c=>c.title==='合成历史入口');
    await openRecentAIHistory(savedHistory,$('#recent-ai-list button'));
    const recentOpened=workspaceUI.session===savedHistory.id&&workspaceUI.conversation==='synthetic-group'&&$('#workspace-agent-history').textContent.includes('合成历史回复');
    await openConversationAgent('synthetic-group');
    const bound=await window.qqInsight.rpc('workspace.chat.get',{account_id:'synthetic',session_id:workspaceUI.session});
    await openChatMemory('settings');
    const chatSettings=await window.qqInsight.rpc('chat.settings.save',{account_id:'synthetic',conversation_id:'synthetic-group',settings:{prompt:'合成会话设定',self_identity:'本会话资料整理人',remember:true}});
    const coverage=await window.qqInsight.rpc('chat.memory.coverage',{account_id:'synthetic',conversation_id:'synthetic-group'});
    await window.qqInsight.rpc('self.save',{account_id:'synthetic',settings:{name:'合成我',identity:'合成学生身份'}});
    const self=await window.qqInsight.rpc('self.get',{account_id:'synthetic'});
    const scopedChat=bound.session.conversation_id==='synthetic-group'&&$('#workspace-agent-view').classList.contains('active')&&$('#chat-memory-dialog').open&&chatSettings.settings.prompt==='合成会话设定'&&typeof coverage.unread==='number'&&self.identity==='合成学生身份';
    closeChatMemory();
    return {recentOpened,outputSaved,linkedOutput,scopedChat,version:health.version,role,compression:defaults.compression,outputChars:defaults.output_chars,features:groupAI.catalog.length,blocked,scope:groupAI.conversation.id,privateBlocked,ledgerEmpty:ledger.items.length===0,mediaForms:document.querySelectorAll('[data-media-form]').length,pricingKeys:Object.keys(prices),savedMaximum,dailyBudget:savedBudget.daily_tokens,outputBudget:savedBudget.output_tokens,chatSaved:chats.items.some(c=>c.id===chat.id)&&chatDetail.session.title==='独立保存的合成对话'&&chatDetail.items.length===0,chatPrivateBlocked};
   })()`);
   assert.equal(result.version,JSON.parse(fs.readFileSync(path.join(root,'package.json'),'utf8')).version);assert.equal(result.features,8);assert.equal(result.role,'第一组组长');assert.equal(result.scope,'synthetic-group');assert.equal(result.blocked,true);
   assert.equal(result.privateBlocked,11);assert.equal(result.ledgerEmpty,true);assert.equal(result.mediaForms,2);assert.deepEqual(result.pricingKeys,['text','vision','speech']);
   assert.equal(result.savedMaximum,true);assert.equal(result.dailyBudget,100000000);assert.equal(result.outputBudget,65536);
   assert.equal(result.outputSaved,true);assert.equal(result.linkedOutput,131072);
   assert.equal(result.compression,'strong');assert.equal(result.outputChars,1234);
   assert.equal(result.scopedChat,true);assert.equal(result.chatSaved,true);assert.equal(result.chatPrivateBlocked,true);assert.equal(result.recentOpened,true);
   console.log('Actual main/preload/core integration passed: startup, group role, paged history, seven prompts and private RPC boundary.');
  }catch(error){console.error(error);process.exitCode=1;}finally{clearTimeout(deadline);app.quit();if(process.exitCode)app.exit(process.exitCode);}
 });
});
try { if(process.env.QQ_TEST_PACKAGED==='1'){
 Object.defineProperty(app,'isPackaged',{value:true});
 Object.defineProperty(process,'resourcesPath',{value:process.env.QQ_TEST_RESOURCES||path.join(root,'build/rel-staging/win-unpacked/resources')});
 require(path.join(process.resourcesPath,'app.asar/src/desktop/main/main.js'));
}else require('../src/desktop/main/main');
} catch(error){console.error(error);process.exit(1);}
