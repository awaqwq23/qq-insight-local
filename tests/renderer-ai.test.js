const { app, BrowserWindow } = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
app.whenReady().then(async()=>{
 const win=new BrowserWindow({show:false,width:1540,height:1120,webPreferences:{offscreen:true,backgroundThrottling:false,contextIsolation:true,nodeIntegration:false}});
 const js=code=>win.webContents.executeJavaScript(`(async()=>{${code}})()`);
 const shot=async name=>{await js("document.getAnimations().forEach(a=>a.finish());$('#toast').className='toast';$('#toast').textContent='';$('#core-state').textContent='合成测试核心';$('#sidebar-account-list').textContent='合成测试账号';");await new Promise(r=>setTimeout(r,250));fs.writeFileSync(path.join(__dirname,`../build/qa/${name}.png`),(await win.webContents.capturePage()).toPNG());};
 try {
  await win.loadFile(path.join(__dirname,'../src/desktop/renderer/index.html'));
  const initial=await js(`
   state.settings={activeAccountId:'synthetic',activePlatform:'qq',modelProfiles:[{id:'test',model:'synthetic-model'}],activeModelProfileId:'test',messagePageSize:40};
   const groups=[{id:'group-a',title:'第一组 · 课程项目',kind:'group',message_count:50},{id:'group-b',title:'读书讨论群',kind:'group'},{id:'private',title:'私聊',kind:'c2c'}];
   state.conversations=groups;
   const base={category:'项目',role:'第一组组长',effective_role:'第一组组长',self_names:'小王',watch_people:['10001'],watch_keywords:['提交'],interests:'实用资料',instructions:'优先通知变更',remember:true,images:false,image_model:'',auto_favorite:false,favorite_daily_limit:10,favorite_storage_mb:200,schedule_minutes:0,schedule_feature:'work',memory_stats:{items:8,people:2}};
   const items=[{id:'work',name:'工作概要'},{id:'summary',name:'群聊速读'},{id:'reply',name:'沟通分析与回复建议'},{id:'collection',name:'智能收藏推荐'},{id:'watch',name:'特别关心动态'},{id:'profile',name:'群与成员画像 / 记忆'},{id:'identity',name:'我的角色识别',schedulable:false},{id:'style',name:'跨群人物风格 / Prompt',schedulable:false}].map(x=>({...x,prompt:x.name+'的合成 Prompt'}));
   window.qa={calls:[],settings:{'group-a':base,'group-b':{...base,role:'普通成员',effective_role:'普通成员'}},fail:false,slow:false};
   window.qqInsight={rpc:async(method,params={})=>{
    qa.calls.push({method,params});
    if(method==='ai.catalog')return {items};
    if(method==='group.get')return {...qa.settings[params.conversation_id]};
    if(method==='group.save')return qa.settings[params.conversation_id]={...params.settings,effective_role:params.settings.role};
    if(method==='message.list')return {items:[],has_more:false};
    if(method==='conversation.list')return {items:groups};
    if(method==='ai.history'){
     if(qa.historyFail)throw new Error('合成历史读取失败');
     const group=params.conversation_id;
     if(qa.slow && params.job_id==='old')await new Promise(r=>setTimeout(r,70));
     const item={id:'item-'+group,feature:params.feature,title:group==='group-a'?'提交课程报告':'读书讨论',body:'请在周五之前提交报告，截止时间已由周四改到周五。',category:'明确需要我做',evidence_ids:['m-'+group],owner:'第一组组长',due_text:'周五',drafts:[]};
     const detail={...item,title:params.job_id==='old'?'旧版本事项':item.title};
     return {items:group==='group-a'?[item]:[],report:params.job_id?{summary:params.job_id==='old'?'旧版本摘要':'当前摘要',items:[detail],coverage:{selected:50,completed_messages:50,start:1700000000,end:1700000100,completed_chunks:1,chunks:1,media_or_unknown:0}}:null,jobs:[{id:'old',feature:params.feature,feature_name:items.find(x=>x.id===params.feature)?.name,status:'completed',model:'synthetic-model',created_at:'2026-09-23T10:00:00Z',updated_at:'2026-09-23T10:00:03Z',duration_seconds:3,coverage:{selected:50,completed_messages:50,start:1700000000,end:1700000100,chunks:1},calls:[],usage:{charged_tokens:1772,cost_totals:{}}},{id:'retry',feature:params.feature,feature_name:items.find(x=>x.id===params.feature)?.name,status:'cancelled',model:'synthetic-model',created_at:'2026-09-23T11:00:00Z',updated_at:'2026-09-23T11:00:02Z',duration_seconds:2,coverage:{selected:20,completed_messages:0,failed_chunk_messages:20,failed_stage:'map',start:1700000000,end:1700000050,chunks:1},calls:[],usage:{charged_tokens:1000,unknown_calls:1,cost_totals:{}}}],pagination:{jobs:{page:1,total:2,has_more:false},items:{page:1,total:1,has_more:false}},memory:{items:8,people:2}};
    }
    if(method==='ai.memory.list')return {items:[{memory_key:'auto:10001',subject:'10001',title:'表达习惯',body:'合成短句表达',evidence_ids:['m-group-a']}]};
    if(method==='ai.memory.update'||method==='ai.history.delete')return {updated:true};
    if(method==='ai.item.update')return {updated:true};
    if(method==='ai.budget.get')return {per_run_tokens:100000,daily_tokens:300000,monthly_tokens:3000000,output_tokens:4096,monthly_cost:0,currency:'CNY',price_model:'',daily_used:0,monthly_used:0,monthly_cost_used:null,uncertain_requests:0};
    if(method==='message.context')return {items:[{id:params.message_id,conversation_id:'group-a',text:'提交报告',sent_at:1700000000,media:[],replies:[],direction:'incoming'}],target_id:params.message_id,conversation:groups[0]};
    return {};
   },runAI:async input=>{qa.calls.push({method:'runAI',params:input});if(qa.fail)throw new Error('合成网络失败');if(input.feature==='identity')qa.settings[input.conversation_id]={...qa.settings[input.conversation_id],role:'AI识别的课程负责人',effective_role:'AI识别的课程负责人'};return {status:'completed',job_id:'new'};},cancelAI:async()=>({cancelled:true})};
   await openConversation('private');const privateButtons=document.querySelectorAll('[data-open-ai]').length;
   await openConversation('group-a');const groupButtons=[...document.querySelectorAll('[data-open-ai]')].map(x=>x.textContent);
   await openGroupAI('group-a');
   return {privateButtons,groupButtons,features:$('#ai-feature').options.length,prompt:$('#ai-prompt').textContent,globalDigest:!!document.querySelector('[data-view="digest"]'),multiPC:/多电脑|换电脑|跨电脑/.test(document.body.textContent)};
  `);
  assert.equal(initial.privateButtons,3);assert.deepEqual(initial.groupButtons,['AI聊天','记忆与设置','对话记录']);assert.equal(initial.features,8);assert.match(initial.prompt,/工作概要/);assert.equal(initial.globalDigest,false);assert.equal(initial.multiPC,false);assert.equal(await js(`return !!document.querySelector('[data-view="profile"]');`),false);
  await shot('ai-analysis');
  const settings=await js(`await setAITab('settings');$('#group-ai-role').value='课程负责人';$('#group-watch-people').value='10001,10002';await saveGroupSettings({preventDefault(){}});return qa.settings['group-a'];`);
  assert.equal(settings.role,'课程负责人');assert.deepEqual(settings.watch_people,['10001','10002']);await shot('ai-settings');
  assert.equal(await js(`await guessGroupRole();return $('#group-ai-role').value;`),'AI识别的课程负责人');
  await js(`await setAITab('analysis');$('#ai-length').value=1234;$('#ai-compression').value='strong';renderCompressionNotice();`);await shot('ai-compression');
  const analysis=await js(`$('#ai-feature').value='work';$('#ai-mode').value='incremental';$('#ai-goal').value='整理本组工作';$('#ai-length').value=1234;$('#ai-compression').value='strong';$('#ai-hierarchical').checked=true;renderCompressionNotice();await startAI();return {input:qa.calls.find(x=>x.method==='runAI'&&x.params.feature==='work').params,history:$('#ai-history-summary').textContent,item:$('#ai-history-items').textContent,busy:groupAI.busy};`);
  assert.equal(analysis.input.conversation_id,'group-a');assert.equal(analysis.input.options.mode,'incremental');assert.match(analysis.item,/提交课程报告/);assert.equal(analysis.busy,false);await shot('ai-history');
  assert.equal(analysis.input.options.output_chars,1234);assert.equal(analysis.input.options.compression,'strong');
  assert.equal(analysis.input.options.hierarchical,true);
  assert.equal(await js(`return $('#ai-length').tagName;`),'INPUT');
  assert.equal(await js(`return $('#ai-compression-note').hidden;`),false);
  assert.equal(await js(`const before=qa.calls.filter(x=>x.method==='runAI').length;$('#ai-length').value=0;await startAI();$('#ai-length').value=500;return qa.calls.filter(x=>x.method==='runAI').length===before;`),true);
  const clickedHistory=await js(`await loadAIHistory('');document.querySelector('[data-report-job="old"]').click();await new Promise(r=>setTimeout(r,150));return {hidden:$('#ai-history-detail').hidden,tab:groupAI.tab,job:groupAI.selectedJob,body:$('#ai-history-items').textContent};`);
  assert.equal(clickedHistory.hidden,false);assert.equal(clickedHistory.tab,'history');assert.equal(clickedHistory.job,'old');assert.match(clickedHistory.body,/旧版本事项/);
  assert.match(await js(`await loadAIHistory('old');return $('#ai-history-items').textContent;`),/旧版本事项/);
  const historyLoading=await js(`qa.slow=true;const card=document.querySelector('[data-report-job="old"]');const pending=loadAIHistory('old');const retained=card.isConnected;await pending;return retained;`);
  assert.equal(historyLoading,true,'Opening a report must not remove the history grid and collapse the page');
  const historyFailure=await js(`qa.historyFail=true;await loadAIHistory('old');qa.historyFail=false;return {hidden:$('#ai-history-detail').hidden,job:groupAI.selectedJob,cards:document.querySelectorAll('.ai-job').length,message:$('#ai-history-summary').textContent};`);
  assert.equal(historyFailure.hidden,false);assert.equal(historyFailure.job,'old');assert.equal(historyFailure.cards,2);assert.match(historyFailure.message,/刷新/);
  const closedHistory=await js(`const pending=loadAIHistory('old');$('#ai-close-detail').click();await pending;await new Promise(r=>setTimeout(r,100));return {hidden:$('#ai-history-detail').hidden,job:groupAI.selectedJob};`);
  assert.equal(closedHistory.hidden,true);assert.equal(closedHistory.job,'');
  assert.match(await js(`qa.slow=true;await Promise.all([loadAIHistory('old'),loadAIHistory('new')]);return $('#ai-history-summary').textContent;`),/当前摘要/);
  const groupB=await js(`await openGroupAI('group-b','history');return {body:$('#ai-history-items').textContent,role:$('#group-ai-role').value};`);
  assert.doesNotMatch(groupB.body,/提交课程报告/);assert.equal(groupB.role,'普通成员');
  const retry=await js(`await openGroupAI('group-a','history');qa.fail=true;await startAI();const failure=$('#ai-status').textContent;qa.fail=false;await startAI(null,'retry');return {failure,disabled:$('#ai-run').disabled,last:qa.calls.filter(x=>x.method==='runAI').at(-1).params};`);
  assert.match(retry.failure,/网络失败/);assert.equal(retry.disabled,false);assert.equal(retry.last.job_id,'retry');
  const people=await js(`await openGroupAI('group-a');$('#ai-feature').value='style';renderPrompt();const shown=!$('#ai-person-options').hidden;const before=qa.calls.filter(x=>x.method==='runAI').length;await startAI();const blocked=qa.calls.filter(x=>x.method==='runAI').length===before;$('#ai-person-id').value='10001';$('#ai-person-cross-group').checked=true;await startAI();const input=qa.calls.filter(x=>x.method==='runAI').at(-1).params;await loadAIMemories();const memory=$('#ai-memory-list').textContent;document.querySelector('[data-memory-action=correct]').click();await new Promise(r=>setTimeout(r,40));document.querySelector('[data-delete-job]').click();await new Promise(r=>setTimeout(r,40));return {shown,blocked,input,memory,corrected:qa.calls.some(x=>x.method==='ai.memory.update'),deleted:qa.calls.some(x=>x.method==='ai.history.delete')};`);
  assert.equal(people.shown,true);assert.equal(people.blocked,true);assert.equal(people.input.options.person_id,'10001');assert.equal(people.input.options.cross_group,true);assert.match(people.memory,/短句/);assert.equal(people.corrected,true);assert.equal(people.deleted,true);
  await js(`$('#ai-memory-list').closest('details').open=true;`);await shot('ai-person-memory');
  await js(`await setAITab('analysis');$('#ai-feature').value='style';renderPrompt();`);await shot('ai-person-style');
  const context=await js(`await openMessageContext('m-group-a');return $('.context-target')?.dataset.messageId;`);assert.equal(context,'m-group-a');
  console.log('Group AI renderer passed: group-only role inference, eight functions, cross-group opt-in, memory controls, failure deletion, paged history cards, isolated memory, versions/races, failure/resume and evidence context.');
 }catch(error){console.error(error);process.exitCode=1;}finally{win.destroy();app.exit(process.exitCode||0);}
});
