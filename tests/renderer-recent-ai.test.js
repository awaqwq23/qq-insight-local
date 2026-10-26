const {app,BrowserWindow}=require('electron');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
app.whenReady().then(async()=>{
 const win=new BrowserWindow({show:false,width:1540,height:900,webPreferences:{offscreen:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}});
 const js=code=>win.webContents.executeJavaScript(`(async()=>{${code}})()`),tick=()=>new Promise(r=>setTimeout(r,100));
 const shot=async name=>{await js(`document.getAnimations().forEach(a=>a.finish());$('#core-state').textContent='合成测试核心';$('#sidebar-account-list').textContent='合成测试账号';$('#toast').className='toast';$('#toast').textContent='';`);await new Promise(r=>setTimeout(r,300));fs.mkdirSync(path.join(__dirname,'../build/qa'),{recursive:true});fs.writeFileSync(path.join(__dirname,'../build/qa/'+name+'.png'),(await win.webContents.capturePage()).toPNG());};
 try{
  await win.loadFile(path.join(__dirname,'../src/desktop/renderer/index.html'));
  await js(`
   state.settings={activeAccountId:'synthetic',activePlatform:'qq'};state.conversations=[{id:'group',kind:'group',title:'合成课程项目群'}];
   const stamp='2026-10-27T02:30:00Z';
   window.qa={calls:[],slow:false,fail:false,sessions:{old:{id:'old',conversation_id:'group',title:'上周项目讨论',head_id:'turn-old',updated_at:stamp},latest:{id:'latest',conversation_id:'group',title:'今天的任务',head_id:'turn-latest',updated_at:stamp},peer:{id:'peer',conversation_id:'private',title:'与搭档讨论',head_id:'turn-peer',updated_at:stamp},global:{id:'global',conversation_id:'',title:'跨群总结',head_id:'turn-global',updated_at:stamp}}};
   qa.recent=[{...qa.sessions.old,kind:'chat',conversation_title:'合成课程项目群',conversation_kind:'group',status:'failed',preview:'继续上周的项目总结'}, {...qa.sessions.peer,kind:'chat',conversation_title:'合成搭档',conversation_kind:'c2c',status:'completed',preview:'私聊中的分工'}, {...qa.sessions.global,kind:'chat',conversation_title:'全局 AI Agent',conversation_kind:'global',status:'completed',preview:'<script>未执行的内容</script>'}, {id:'legacy',kind:'analysis',title:'summary',feature:'summary',conversation_id:'group',conversation_title:'合成课程项目群',conversation_kind:'group',status:'completed',preview:'旧版存档',updated_at:stamp}];
   window.qqInsight={rpc:async(method,p={})=>{
    qa.calls.push({method,p});
    if(method==='workspace.chat.recent'){const items=p.account_id==='synthetic'?qa.recent:[];if(qa.slow&&p.account_id==='synthetic')await new Promise(r=>setTimeout(r,150));if(qa.fail)throw new Error('合成读取失败');return {items:p.offset?items.slice(3):items.slice(0,3),has_more:!p.offset&&items.length>3,next_offset:3};}
    if(method==='workspace.chat.list')return {items:Object.values(qa.sessions).filter(s=>s.conversation_id===p.conversation_id&&s.id!=='old'),has_more:false};
    if(method==='workspace.chat.get'){const s=qa.sessions[p.session_id];return {session:s,items:[{id:s.head_id,question:s.id==='old'?'上周的原始问题':'另一个对话的问题',answer:'## 本轮重点\\n\\n这是有来源说明的合成回复，便于检查字体、行距与长段落。\\n\\n- 先核实项目分工和截止日期。\\n- 记录不明确的事项，继续追问时保留当前对话。',status:'completed',source_messages:5,steps:[],attachments:[],artifacts:[]}],branches:[],has_more:false,next_offset:50};}
    if(method==='chat.memory.coverage')return {total:120,compressed:80,read:80,unread:40,ranges:[{start:1,end:80}],remember:true};
    return {};
   }};
   showView('ai-history');await loadRecentAIHistory();
  `);
  assert.equal(await js(`return $('#recent-ai-list').querySelectorAll('[data-recent-ai]').length;`),3);
  assert.equal(await js(`return $('#recent-ai-list script')===null;`),true);
  assert.match(await js(`return $('#recent-ai-list').textContent;`),/群聊.*私聊.*全局/s);
  await js(`$('#recent-ai-more').click();`);await tick();
  assert.equal(await js(`return $('#recent-ai-list').querySelectorAll('[data-recent-ai]').length;`),4);
  assert.ok(await js(`return $('#recent-ai-list').getBoundingClientRect().height>200;`),'history is visible');
  await shot('recent-ai-history');
  await js(`qa.fail=true;await loadRecentAIHistory();qa.fail=false;`);
  assert.equal(await js(`return $('#recent-ai-list').querySelectorAll('[data-recent-ai]').length;`),4,'failed refresh preserves list');
  await js(`$('#recent-ai-list button').click();`);await tick();
  assert.equal(await js(`return workspaceUI.session;`),'old');
  assert.equal(await js(`return workspaceUI.conversation;`),'group');
  assert.equal(await js(`return state.activeConversation;`),'group');
  assert.match(await js(`return $('#workspace-agent-history').textContent;`),/上周的原始问题/);
  assert.equal(await js(`return $('#workspace-chat-menu').open;`),false);
  await js(`$('#workspace-chat-menu summary').click();`);assert.equal(await js(`return $('#workspace-chat-menu').open;`),true);
  await js(`$('#workspace-chat-menu summary').click();`);
  for(const [width,height] of [[1200,680],[1540,900]]){
   win.setSize(width,height);await tick();
   const layout=await js(`const r=$('#workspace-agent-history').getBoundingClientRect();return {width:r.width,height:r.height,font:getComputedStyle($('.workspace-answer')).fontSize,input:getComputedStyle($('#workspace-agent-question')).fontSize,overflow:document.documentElement.scrollWidth>innerWidth,bottom:$('#workspace-agent-run').getBoundingClientRect().bottom,viewport:innerHeight};`);
   assert.ok(layout.width>=820);assert.ok(layout.height>=180);assert.equal(layout.font,'16px');assert.equal(layout.input,'16px');assert.equal(layout.overflow,false);assert.ok(layout.bottom<=layout.viewport);
  }
  await shot('recent-ai-chat-layout');
  win.webContents.debugger.attach('1.3');
  await win.webContents.debugger.sendCommand('DOM.enable');await win.webContents.debugger.sendCommand('CSS.enable');
  const documentNode=await win.webContents.debugger.sendCommand('DOM.getDocument');
  const paragraph=await win.webContents.debugger.sendCommand('DOM.querySelector',{nodeId:documentNode.root.nodeId,selector:'.workspace-answer p'});
  const fonts=await win.webContents.debugger.sendCommand('CSS.getPlatformFontsForNode',{nodeId:paragraph.nodeId});
  console.log('Rendered chat fonts: '+fonts.fonts.map(f=>f.familyName).join(', '));win.webContents.debugger.detach();
  await js(`showView('ai-history');await loadRecentAIHistory();await openRecentAIHistory(recentAIUI.items[1],$('#recent-ai-list button'));`);
  assert.equal(await js(`return workspaceUI.conversation;`),'private');assert.equal(await js(`return workspaceUI.session;`),'peer');
  await js(`showView('ai-history');await loadRecentAIHistory();await openRecentAIHistory(recentAIUI.items[2],$('#recent-ai-list button'));`);
  assert.equal(await js(`return workspaceUI.conversation;`),'');assert.equal(await js(`return workspaceUI.session;`),'global');
  await js(`showView('ai-history');await loadRecentAIHistory();await loadRecentAIHistory(true);window.openGroupAI=async(cid,tab,feature)=>{qa.archive={cid,tab,feature};groupAI.conversation={id:cid};};window.loadAIHistory=async id=>qa.archive.job=id;await openRecentAIHistory(recentAIUI.items[3],$('#recent-ai-list button'));`);
  assert.deepEqual(await js(`return qa.archive;`),{cid:'group',tab:'history',feature:'summary',job:'legacy'});
  await js(`showView('ai-history');await loadRecentAIHistory();qa.slow=true;const pending=loadRecentAIHistory();state.settings.activeAccountId='other';await loadRecentAIHistory();await pending;`);
  assert.doesNotMatch(await js(`return $('#recent-ai-list').textContent;`),/上周|合成搭档|跨群总结/);
  console.log('Recent AI UI passed: all scopes, pagination, archive routing, exact older session, refresh failure, escaping, account race, readable 16px text and responsive chat area; synthetic only.');
 }catch(error){console.error(error);process.exitCode=1;}finally{win.destroy();app.exit(process.exitCode||0);}
});
