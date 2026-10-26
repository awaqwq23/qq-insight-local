const {app,BrowserWindow}=require('electron');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
app.whenReady().then(async()=>{
 const win=new BrowserWindow({show:false,width:1540,height:1100,webPreferences:{offscreen:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}});
 const js=code=>win.webContents.executeJavaScript(`(async()=>{${code}})()`),tick=()=>new Promise(r=>setTimeout(r,100));
 const shot=async name=>{await js(`document.getAnimations().forEach(a=>a.finish());$('#toast').className='toast';$('#toast').textContent='';$('#core-state').textContent='合成测试核心';$('#sidebar-account-list').textContent='合成账号';`);await new Promise(r=>setTimeout(r,250));fs.mkdirSync(path.join(__dirname,'../build/qa'),{recursive:true});fs.writeFileSync(path.join(__dirname,`../build/qa/${name}.png`),(await win.webContents.capturePage()).toPNG());};
 try{
  await win.loadFile(path.join(__dirname,'../src/desktop/renderer/index.html'));
  await js(`
   state.settings={activeAccountId:'synthetic',activePlatform:'qq'};
   state.conversations=[{id:'group',title:'合成课程项目群',kind:'group'},{id:'private',title:'合成搭档',kind:'c2c'}];
   const stamp='2026-10-25T10:30:00Z';
   window.qa={calls:[],sessions:{},turns:{},serial:0,slow:false,self:{name:'合成自己',qq:'synthetic',uid:'u_self',identity:'课程学生',preferences:'简洁回答'},config:{prompt:'先核实来源',self_identity:'本群组长',peer_identity:'项目搭档',remember:true}};
   window.qqInsight={rpc:async(method,p={})=>{
    qa.calls.push({method,params:p});
    if(method==='workspace.chat.list')return {items:Object.values(qa.sessions).filter(s=>s.conversation_id===(p.conversation_id||'')),has_more:false};
    if(method==='workspace.chat.create'){const id='chat'+(++qa.serial),s={id,conversation_id:p.conversation_id||'',title:'新对话',head_id:'',updated_at:stamp};qa.sessions[id]=s;qa.turns[id]=[];return s;}
    if(method==='workspace.chat.get'){const s=qa.sessions[p.session_id];return {session:s,items:qa.turns[s.id],branches:[],has_more:false,next_offset:50};}
    if(method==='chat.memory.coverage'){if(qa.slow&&p.conversation_id==='group')await new Promise(r=>setTimeout(r,140));return {total:p.conversation_id==='group'?120:20,compressed:p.conversation_id==='group'?80:20,read:p.conversation_id==='group'?80:20,unread:p.conversation_id==='group'?40:0,ranges:p.conversation_id==='group'?[{start:1,end:60},{start:81,end:100}]:[{start:1,end:20}],remember:true};}
    if(method==='chat.settings.get')return {conversation:state.conversations.find(c=>c.id===p.conversation_id),settings:qa.config,remember_enabled:qa.config.remember,learned:{prompt:'根据本会话原始记录完善的合成Agent背景。'}};
    if(method==='chat.settings.save'){qa.config={...qa.config,...p.settings};return {};}
    if(method==='chat.memory.list')return {items:p.kind==='people'?[{name:'合成自己',qq:'synthetic',is_self:true,notice:'有来源的暂定画像',memories:[{memory_key:'person:self',body:'偏好先明确任务。',title:'本人观察'}]},{name:'合成搭档',qq:'100001',is_self:false,notice:'证据不足不猜测',memories:[]}]:p.kind==='messages'?[{message_id:'source',sender_name:'合成自己',local_time:'2026-10-25T10:30',text:'合成摘录消息',notice:'长消息可能截短。'}]:[{memory_key:'group:workspace',title:'会话概括',body:'本群讨论课程项目提交安排。',locked:true}],has_more:false,next_offset:30};
    if(method==='self.get')return qa.self;
    if(method==='self.save'){qa.self={...qa.self,...p.settings};return qa.self;}
    if(method==='self.memory')return {items:[{conversation:'合成课程项目群',body:'本人观察按来源保存。'}]};
    if(method==='message.list')return {items:[],has_more:false};
    return {};
   },runWorkspaceAgent:async p=>{qa.calls.push({method:'run',params:p});const id='turn'+(++qa.serial),s=qa.sessions[p.session_id];s.head_id=id;s.title=p.question.slice(0,24);qa.turns[s.id].push({id,question:p.question,answer:'可以继续追问，文件与记忆会按本会话保存。',status:'completed',error:'',source_messages:4,steps:[{name:'read_context',selected_messages:4,reused_messages:2,raw_messages:2},{name:'compress_context',compressed_messages:2}],attachments:p.attachment_ids.map(id=>({id,filename:'合成图片.png',mime:'image/png'})),artifacts:[]});return {status:'completed',session_id:s.id,run_id:id};},pickWorkspaceAttachments:async p=>({items:[{id:'attachment',filename:'合成图片.png',mime:'image/png',bytes:128}]}),cancelWorkspaceAgent:async()=>({cancelled:true})};
   await openConversationAgent('group');
  `);
  const groupSession=await js(`return workspaceUI.session;`);
  assert.equal(await js(`return workspaceUI.conversation;`),'group');
  assert.equal(await js(`const node=document.createElement('div');node.innerHTML=renderChatAnswer('## 合成标题\\n\\n**重点**\\n\\n- 一项\\n\\n<script>危险代码</script>');return !!node.querySelector('h4')&&!!node.querySelector('strong')&&!!node.querySelector('li')&&!node.querySelector('script');`),true);
  assert.equal(await js(`return $('#workspace-agent-view').classList.contains('active')&& !$('#group-ai-view').classList.contains('active');`),true);
  assert.match(await js(`return $('#workspace-chat-coverage').textContent;`),/40 条消息还未读取.*第1–60条.*第81–100条/);
  await js(`$('#chat-presets summary').click();$('#chat-preset-options button:nth-child(3)').click();`);
  assert.match(await js(`return $('#workspace-agent-question').value;`),/压缩上下文.*未覆盖.*包括我自己.*Agent背景/);
  assert.equal(await js(`return qa.calls.some(c=>c.method==='run');`),false);
  await js(`$('#workspace-agent-attach').click();`);await tick();
  assert.match(await js(`return $('#workspace-chat-attachments').textContent;`),/合成图片/);
  await js(`$('#workspace-agent-question').value='请根据原文总结本群的任务';$('#workspace-agent-form').requestSubmit();`);await tick();
  assert.match(await js(`return $('#workspace-agent-history').textContent;`),/复用 2 条.*待压缩 2 条.*2 条已保存/s);
  const sent=await js(`return qa.calls.find(c=>c.method==='run').params;`);
  assert.equal(sent.conversation_id,'group');assert.equal(sent.session_id,groupSession);assert.deepEqual(sent.attachment_ids,['attachment']);
  assert.equal(await js(`return getComputedStyle($('.agent-user-message')).marginLeft!=='0px';`),true);
  await js(`$('#workspace-agent-question').value='群里未发送草稿';await openConversationAgent('private');`);
  const privateSession=await js(`return workspaceUI.session;`);assert.notEqual(privateSession,groupSession);
  assert.doesNotMatch(await js(`return $('#workspace-agent-history').textContent;`),/根据原文总结本群/);
  await js(`await openChatMemory('settings');`);
  assert.equal(await js(`return $('#chat-peer-identity-field').hidden;`),false);
  await js(`$('#chat-peer-identity').value='仅此私聊的搭档';$('#chat-agent-settings').requestSubmit();`);await tick();
  const saved=await js(`return qa.calls.find(c=>c.method==='chat.settings.save').params;`);assert.equal(saved.conversation_id,'private');assert.equal(saved.settings.peer_identity,'仅此私聊的搭档');
  await js(`await loadChatMemoryTab('people');`);assert.match(await js(`return $('#chat-memory-items').textContent;`),/合成自己 · 我/);
  await shot('conversation-private-memory');
  await js(`closeChatMemory();await openConversationAgent('group');`);
  assert.equal(await js(`return workspaceUI.session;`),groupSession);assert.equal(await js(`return $('#workspace-agent-question').value;`),'群里未发送草稿');
  await shot('conversation-group-chat');
  await js(`await openChatMemory('messages');`);assert.match(await js(`return $('#chat-memory-items').textContent;`),/查看原消息/);
  await js(`await loadChatMemoryTab('conversation');`);assert.match(await js(`return $('#chat-memory-items').textContent;`),/本群讨论课程项目/);
  await shot('conversation-group-memory');
  await js(`closeChatMemory();showView('workspace-agent');await loadWorkspaceHistory();await openChatMemory();`);
  assert.equal(await js(`return workspaceUI.conversation;`),'');assert.equal(await js(`return $('#chat-self-settings').hidden;`),false);
  await js(`$('#chat-self-preferences').value='先列结论，再列证据';$('#chat-self-settings').requestSubmit();`);await tick();
  assert.equal(await js(`return qa.self.preferences;`),'先列结论，再列证据');
  await shot('conversation-self-settings');
  await js(`closeChatMemory();await openConversationAgent('group');qa.slow=true;const pending=refreshChatCoverage();await openConversationAgent('private');await pending;`);
  assert.doesNotMatch(await js(`return $('#workspace-chat-coverage').textContent;`),/40 条消息/);
  await js(`qa.slow=false;await openChatMemory('people');state.settings.activeAccountId='other';resetWorkspaceChats();`);
  assert.equal(await js(`return $('#chat-memory-dialog').open;`),false);
  assert.doesNotMatch(await js(`return $('#workspace-agent-history').textContent;`),/根据原文总结本群/);
  await js(`state.settings.activeAccountId='synthetic';await openConversationAgent('group');`);
  assert.match(await js(`return $('#chat-preset-options').textContent;`),/范围内全体成员画像/);
  await js(`$('#chat-presets').open=true;[...$('#chat-preset-options').querySelectorAll('button')].find(b=>b.textContent.includes('单成员画像')).click();`);await tick();
  assert.equal(await js(`return $('#chat-memory-dialog').open;`),true);
  await js(`[...$('#chat-memory-items').querySelectorAll('.chat-memory-person')].find(p=>p.textContent.includes('100001')).querySelector('button').click();`);
  assert.equal(await js(`return $('#chat-memory-dialog').open;`),false);
  assert.match(await js(`return $('#workspace-agent-question').value;`),/100001.*最近200条本人发言/);
  assert.match(await js(`return $('#workspace-agent-question').value;`),/阶段画像.*未知维度/);
  for(const [width,height] of [[1200,680],[1540,900],[1540,1100]]){win.setSize(width,height);await tick();assert.equal(await js(`return document.documentElement.scrollWidth<=innerWidth;`),true);assert.equal(await js(`return $('#workspace-agent-run').getBoundingClientRect().bottom<=innerHeight;`),true, 'composer stays in viewport');}
  assert.equal(await js(`return messageCard({id:'own',sender_qq:'synthetic',sender_name:'我',text:'本人的合成发言',direction:'incoming',media:[],replies:[]}).includes('message-row outgoing');`),true);
  assert.equal(await js(`return messageCard({id:'covered',sender_qq:'100001',sender_name:'合成人',text:'合成消息',direction:'incoming',media:[],replies:[],memory:{compressed:true,updated_at:'2026-10-25T10:30:00Z'}}).includes('已处理');`),true);
  console.log('Conversation chat UI passed: group/private/global separation, continuing history and drafts, preset fills only, attachment binding, coverage ranges, three memory views, private identities, self settings, stale response protection, own messages on right and narrow layout; synthetic only.');
 }catch(error){console.error(error);process.exitCode=1;}finally{win.destroy();app.exit(process.exitCode||0);}
});
