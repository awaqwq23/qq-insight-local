const chatMemoryUI={request:0,key:'',account:'',conversation:'',tab:'conversation',offset:0,parent:null};

async function openConversationAgent(id, panel='analysis'){
 const conversation=state.conversations.find(item=>item.id===id)||state.overview?.recent_conversations.find(item=>item.id===id);
 if(!conversation||!['group','c2c'].includes(conversation.kind))return toast('请选择已导入的群聊或私聊。','error');
 if(workspaceUI.conversation!==id||workspaceUI.scope!==activeScope().platform+'/'+activeScope().account_id+'/'+id)resetWorkspaceChats(id);
 showView('conversation-agent');const key=workspaceScope();
 await loadWorkspaceHistory();if(key!==workspaceScope())return;
 if(!workspaceUI.session)await createWorkspaceChat();
 await refreshChatCoverage();
 if(key!==workspaceScope())return;
 if(panel==='settings')await openChatMemory('settings');else $('#workspace-agent-question').focus();
}

function renderChatContext(){
 const cid=workspaceUI.conversation,conversation=state.conversations.find(item=>item.id===cid)||state.overview?.recent_conversations.find(item=>item.id===cid);
 $('#workspace-chat-back').hidden=!cid;$('#workspace-memory-open').textContent=cid?'记忆与设置':'我的设置';
 $('#workspace-chat-scope').textContent=cid?`${conversation?.title||'当前会话'} · 独立历史与三类记忆`:'本对话保留上下文 · 与其他对话分开';
 $('.agent-chat-list-label').innerHTML=cid?'本会话的对话 <span>自动保存到本机</span>':'我的对话 <span>自动保存到本机</span>';
 $('#workspace-scope-note').textContent=cid?'只访问本会话。记忆按需读取与完善；消息和附件发送到对应模型。':'默认读取当前账号群聊，涉及私聊请明确说明。消息和附件发送到对应模型。';
 $('#workspace-chat-coverage').hidden=!cid;
 const target=cid?'本会话':'指定会话';
 const presets=[['今日重点',`总结${target}今天聊了什么，指出与我相关的重点。结合新消息，按需复用已经压缩的上下文；说明实际覆盖范围。`],
  ['任务清单',`整理${target}最近一周与我有关的任务、截止时间和变更，生成Markdown文件。引用来源，未确定的事项保留为待核实。`],
  [conversation?.kind==='c2c'?'双方画像与身份':'群聊与成员画像',cid?(conversation?.kind==='c2c'?'短记录直接读本私聊原文；长记录优先压缩上下文，按需补充未覆盖部分；不清晰时回查原文。完善会话概括、我的身份和表达习惯、对方的身份和表达习惯。只保存有证据的观察，并更新本私聊的Agent背景；未读完明确说明。':'短记录直接读本群原文；长记录优先压缩上下文，按需补充未覆盖部分；不清晰时回查原文。完善群聊概括与群内成员（包括我自己）的画像和记忆，并更新本群Agent背景。只归纳有证据的身份、表达习惯和偏好；未发言或证据不足的人保持未知。说明未读取的范围。'):'短记录直接读指定会话原文，长记录复用压缩上下文、补充未覆盖部分并按需回源，完善会话概括、成员（含我）的画像和记忆，并更新对应Agent背景。请先确认需要分析哪个会话。'],
  ['人物风格',`根据${target}某个人的原始发言，归纳说话方式，生成可复用的风格Prompt。不能冒充本人或把推断当真实人格。请先确认需要分析谁。`],
  ['保存表情',`从${target}中找几个可爱的表情包，实际查看图片后保存文件。没有本地图片或识图配置时如实说明。`]];
 if(conversation?.kind==='group'){
  presets[2]=['范围内全体成员画像','短记录直接原文，长记录优先已有压缩上下文、按需补充未覆盖部分。分析本群最近1000条消息内所有实际发言者（包括我自己），按成员分批保存阶段画像。重点写语气和措辞、从近期话题推测兴趣（如游戏）、暂定性格倾向及习惯。已有多少先写多少，未知维度标待补充，保留原始依据与推测的区别，供后续继续完善，并更新本群Agent背景。'];
  presets.splice(3,0,['单成员画像（省费用）','@pick-member']);
 }
 $('#chat-preset-options').innerHTML=presets.map(([name,text])=>`<button type="button" data-chat-preset="${escapeHtml(text)}">${escapeHtml(name)}</button>`).join('');
 $('#chat-preset-options').querySelectorAll('button').forEach(button=>button.addEventListener('click',()=>{if($('#workspace-agent-question').disabled)return;$('#chat-presets').open=false;if(button.dataset.chatPreset==='@pick-member'){openChatMemory('people');return;}$('#workspace-agent-question').value=button.dataset.chatPreset;$('#workspace-agent-question').focus();}));
 if(cid)$('#workspace-agent-suggestions').hidden=true;
}

function coverageText(value){
 if(!value||typeof value.unread!=='number')return '正在读取消息进度…';
 const ranges=(value.ranges||[]).slice(0,8).map(range=>range.start===range.end?`第${range.start}条`:`第${range.start}–${range.end}条`).join('、');
 return `${value.unread} 条消息还未读取 · ${value.compressed} / ${value.total} 条已处理${ranges?'（'+ranges+'）':''}${(value.ranges||[]).length>8||value.more_ranges?'，另有更多区间':''}${value.remember===false?' · 记忆已暂停':''}`;
}

async function refreshChatCoverage(){
 const cid=workspaceUI.conversation,key=workspaceScope();if(!cid)return;
 try{const result=await rpc('chat.memory.coverage',{account_id:activeScope().account_id,conversation_id:cid});if(key!==workspaceScope())return;$('#workspace-chat-coverage').textContent=coverageText(result);$('#workspace-chat-coverage').title=result.notice||'';}catch(error){if(key===workspaceScope())$('#workspace-chat-coverage').textContent=errorMessage(error);}
}

function renderChatAttachments(){
 $('#workspace-chat-attachments').innerHTML=workspaceUI.attachments.map((file,index)=>`<span>${escapeHtml(file.filename)}<button class="text-button" type="button" data-remove-attachment="${index}" aria-label="移除附件 ${escapeHtml(file.filename)}" ${workspaceUI.busy?'disabled':''}>×</button></span>`).join('');
 $('#workspace-chat-attachments').querySelectorAll('button').forEach(button=>button.addEventListener('click',()=>{workspaceUI.attachments.splice(Number(button.dataset.removeAttachment),1);renderChatAttachments();}));
}

function closeChatMemory(){chatMemoryUI.request++;chatMemoryUI.parent=null;$('#chat-memory-dialog').close();}

async function backChatMemory(){
 const parent=chatMemoryUI.parent;
 if(!parent||parent.key!==workspaceScope()||parent.account!==activeScope().account_id)return closeChatMemory();
 chatMemoryUI.parent=null;
 const loading=openChatMemory('settings'),request=chatMemoryUI.request;
 await loading;if(request!==chatMemoryUI.request||!$('#chat-memory-dialog').open)return;
 for(const field of parent.fields){const node=$('#'+field.id);node.value=field.value;node.checked=field.checked;}
 $('#chat-open-self').focus();$('#chat-memory-dialog').scrollTop=parent.scroll;
}

async function openChatMemory(tab='conversation',self=false){
 const dialog=$('#chat-memory-dialog');if(!dialog.open||chatMemoryUI.key!==workspaceScope())chatMemoryUI.parent=null;
 chatMemoryUI.account=activeScope().account_id;chatMemoryUI.conversation=self?'':workspaceUI.conversation;chatMemoryUI.key=workspaceScope();
 if(!chatMemoryUI.account)return toast('请先选择QQ账号。','error');
 const own=!chatMemoryUI.conversation;
 $('#chat-memory-title').textContent=own?'全局 · 我的设置':'本会话 · 记忆与设置';$('#chat-memory-tabs').hidden=own;
 $('#chat-memory-close').textContent=chatMemoryUI.parent?'返回上一级':'关闭';
 $('#chat-memory-status').textContent='';$('#chat-self-observations').open=false;$('#chat-self-memory').replaceChildren();
 if(!dialog.open)dialog.showModal();
 await loadChatMemoryTab(own?'self':tab);
}

async function loadChatMemoryTab(tab,more=false){
 const token=++chatMemoryUI.request,key=chatMemoryUI.key,cid=chatMemoryUI.conversation,account=chatMemoryUI.account;
 chatMemoryUI.tab=tab;if(!more)chatMemoryUI.offset=0;
 const current=()=>token===chatMemoryUI.request&&key===workspaceScope()&&account===activeScope().account_id;
 for(const [id,show] of [['chat-agent-settings',tab==='settings'],['chat-self-settings',tab==='self'],['chat-memory-search-form',tab==='people']])$('#'+id).hidden=!show;
 $('#chat-memory-more').hidden=true;$('#chat-memory-coverage').textContent='';
 $('#chat-memory-tabs').querySelectorAll('button').forEach(button=>button.setAttribute('aria-current',button.dataset.memoryTab===tab?'page':'false'));
 if(!more)$('#chat-memory-items').replaceChildren();
 try{
  if(tab==='self'){
   const result=await rpc('self.get',{account_id:account});if(!current())return;
   for(const [id,field] of [['chat-self-name','name'],['chat-self-qq','qq'],['chat-self-uid','uid'],['chat-self-background','identity'],['chat-self-preferences','preferences']])$('#'+id).value=result[field]||'';
  }else if(tab==='settings'){
   const result=await rpc('chat.settings.get',{account_id:account,conversation_id:cid});if(!current())return;
   $('#chat-self-identity').value=result.settings.self_identity;$('#chat-peer-identity').value=result.settings.peer_identity;$('#chat-agent-prompt').value=result.settings.prompt;
   $('#chat-peer-identity-field').hidden=result.conversation.kind!=='c2c';$('#chat-legacy-history').hidden=result.conversation.kind!=='group';$('#chat-remember').checked=result.remember_enabled;
   $('#chat-learned-prompt').textContent=result.learned?.prompt||'读取原文，或复用长记录的有效上下文、按需补充及回源后，自动完善带来源的背景；不会覆盖人工设定。';
  }else{
   const [result,coverage]=await Promise.all([rpc('chat.memory.list',{account_id:account,conversation_id:cid,kind:tab,offset:chatMemoryUI.offset,limit:30,query:tab==='people'?$('#chat-memory-query').value.trim():''}),rpc('chat.memory.coverage',{account_id:account,conversation_id:cid})]);if(!current())return;
   $('#chat-memory-coverage').textContent=coverageText(coverage);$('#chat-memory-more').hidden=!result.has_more;chatMemoryUI.offset=result.next_offset;
   const memoryCard=(m,title='')=>`<article class="chat-memory-card"><h4>${escapeHtml(title||m.title||'会话观察')}${m.locked?' · 已锁定':''}</h4><p>${escapeHtml(m.body||'暂无足够证据。')}</p>${m.uncertainty?`<small>${escapeHtml(m.uncertainty)}</small>`:''}${m.stage==='partial'?'<small>阶段画像 · 可以先查看，后续继续补充</small>':''}${m.memory_key?`<details><summary>纠正或管理这条记忆</summary><textarea data-memory-correction="${escapeHtml(m.memory_key)}" maxlength="6000" rows="3">${escapeHtml(m.correction||m.body||'')}</textarea><div class="form-actions"><button type="button" class="text-button" data-memory-action="correct" data-memory-key="${escapeHtml(m.memory_key)}">保存更正并锁定</button><button type="button" class="text-button" data-memory-action="forget" data-memory-key="${escapeHtml(m.memory_key)}">忘记</button>${m.locked?`<button type="button" class="text-button" data-memory-action="unlock" data-memory-key="${escapeHtml(m.memory_key)}">恢复自动更新</button>`:''}</div></details>`:''}</article>`;
   const markup=result.items.map(item=>tab==='people'?`<section class="chat-memory-person"><h3>${escapeHtml(item.name||item.qq||item.uid||'未知成员')}${item.is_self?' · 我':''}</h3><small>${escapeHtml(item.qq||item.uid||'')} · ${escapeHtml(item.notice)}</small>${item.identity?`<p class="field-hint">用户设定：${escapeHtml(item.identity)}</p>`:''}${item.memories.map(m=>memoryCard(m)).join('')}</section>`:tab==='messages'?`<article class="chat-memory-card"><h4>${escapeHtml(item.sender_name||item.sender_qq||item.sender_key||'未知')} · ${escapeHtml(item.local_time)}</h4><p>${escapeHtml(item.text)}</p><small>${escapeHtml(item.notice)}</small><button class="text-button" type="button" data-memory-source="${escapeHtml(item.message_id)}">查看原消息</button></article>`:memoryCard(item)).join('');
   $('#chat-memory-items').insertAdjacentHTML('beforeend',markup||(!more?`<div class="empty">${result.paused?'本会话记忆已暂停，可在Agent设置恢复。':'尚无此类记忆；分析后按证据逐步完善。'}</div>`:''));
   if(tab==='people'&&state.conversations.find(c=>c.id===cid)?.kind==='group'){
    const sections=[...$('#chat-memory-items').querySelectorAll('.chat-memory-person')].slice(-result.items.length);
    result.items.forEach((person,index)=>{const id=person.qq||person.uid;if(!id||!sections[index])return;const button=document.createElement('button');button.type='button';button.className='text-button';button.textContent='分析此成员 / 继续完善';button.addEventListener('click',()=>{if(key!==workspaceScope()||account!==activeScope().account_id||workspaceUI.busy)return;closeChatMemory();$('#workspace-agent-question').value=`分析本群成员 QQ/UID：${id} 最近200条本人发言，仅取此成员以节省费用。重点写说话语气和措辞、从近期话题推测的兴趣（如游戏）、暂定性格倾向及习惯。已有内容先保存为阶段画像，未知维度标待补充，结合原有画像继续完善并保留依据。`;$('#workspace-agent-question').focus();});sections[index].append(button);});
   }
   $('#chat-memory-items').querySelectorAll('[data-memory-source]:not([data-bound])').forEach(button=>{button.dataset.bound='true';button.addEventListener('click',()=>{closeChatMemory();openMessageContext(button.dataset.memorySource);});});
   $('#chat-memory-items').querySelectorAll('[data-memory-action]:not([data-bound])').forEach(button=>{button.dataset.bound='true';button.addEventListener('click',async()=>{
    if(key!==workspaceScope())return;button.disabled=true;
    const input=[...$('#chat-memory-items').querySelectorAll('[data-memory-correction]')].find(node=>node.dataset.memoryCorrection===button.dataset.memoryKey);
    try{await rpc('ai.memory.update',{account_id:account,conversation_id:cid,memory_key:button.dataset.memoryKey,action:button.dataset.memoryAction,correction:input?.value||''});if(key===workspaceScope())await loadChatMemoryTab(tab);}catch(error){if(key===workspaceScope())$('#chat-memory-status').textContent=errorMessage(error);}finally{button.disabled=false;}
   });});
  }
 }catch(error){if(current())$('#chat-memory-status').textContent=errorMessage(error);}
}

document.addEventListener('DOMContentLoaded',()=>{
 renderChatContext();
 $('#workspace-chat-back').addEventListener('click',()=>openConversation(workspaceUI.conversation));
 $('#workspace-memory-open').addEventListener('click',()=>openChatMemory());$('#chat-memory-close').addEventListener('click',backChatMemory);
 $('#chat-memory-dialog').addEventListener('cancel',event=>{event.preventDefault();backChatMemory();});
 $('#chat-memory-tabs').querySelectorAll('button').forEach(button=>button.addEventListener('click',()=>loadChatMemoryTab(button.dataset.memoryTab)));
 $('#chat-memory-more').addEventListener('click',()=>loadChatMemoryTab(chatMemoryUI.tab,true));$('#chat-memory-search-form').addEventListener('submit',event=>{event.preventDefault();loadChatMemoryTab('people');});
 $('#chat-open-self').addEventListener('click',()=>{
  chatMemoryUI.parent={key:workspaceScope(),account:activeScope().account_id,scroll:$('#chat-memory-dialog').scrollTop,
   fields:[...$('#chat-agent-settings').querySelectorAll('input,textarea')].map(node=>({id:node.id,value:node.value,checked:node.checked}))};
  openChatMemory('self',true);
 });
 $('#chat-legacy-history').addEventListener('click',()=>{const cid=workspaceUI.conversation;closeChatMemory();openGroupAI(cid,'history');});
 $('#chat-agent-settings').addEventListener('submit',async event=>{
  event.preventDefault();const key=chatMemoryUI.key;
  try{await rpc('chat.settings.save',{account_id:chatMemoryUI.account,conversation_id:chatMemoryUI.conversation,settings:{prompt:$('#chat-agent-prompt').value,self_identity:$('#chat-self-identity').value,peer_identity:$('#chat-peer-identity').value,remember:$('#chat-remember').checked}});if(key===workspaceScope()){$('#chat-memory-status').textContent='会话设置已保存；人工设定优先，自动背景独立维护。';refreshChatCoverage();}}catch(error){if(key===workspaceScope())$('#chat-memory-status').textContent=errorMessage(error);}
 });
 $('#chat-self-settings').addEventListener('submit',async event=>{
  event.preventDefault();const key=chatMemoryUI.key;
  try{await rpc('self.save',{account_id:chatMemoryUI.account,settings:{name:$('#chat-self-name').value,qq:$('#chat-self-qq').value,uid:$('#chat-self-uid').value,identity:$('#chat-self-background').value,preferences:$('#chat-self-preferences').value}});if(key===workspaceScope())$('#chat-memory-status').textContent='我的设置已保存，后续聊天与Agent会按任务读取。';}catch(error){if(key===workspaceScope())$('#chat-memory-status').textContent=errorMessage(error);}
 });
 $('#chat-self-observations').addEventListener('toggle',async()=>{
  if(!$('#chat-self-observations').open)return;const key=chatMemoryUI.key,token=chatMemoryUI.request;
  try{const result=await rpc('self.memory',{account_id:chatMemoryUI.account});if(key!==workspaceScope()||token!==chatMemoryUI.request)return;$('#chat-self-memory').innerHTML=result.items.map(item=>`<article class="chat-memory-card"><h4>${escapeHtml(item.conversation)}</h4><p>${escapeHtml(item.body)}</p></article>`).join('')||'<p class="field-hint">尚无有证据的本人画像；可在对应会话使用画像预设。</p>';}catch(error){if(key===workspaceScope())$('#chat-memory-status').textContent=errorMessage(error);}
 });
 $('#workspace-agent-attach').addEventListener('click',async()=>{
  if(workspaceUI.busy)return;const key=workspaceScope();
  try{if(!workspaceUI.session)await createWorkspaceChat();if(key!==workspaceScope())return;const session=workspaceUI.session;const result=await window.qqInsight.pickWorkspaceAttachments({account_id:activeScope().account_id,session_id:session});if(key!==workspaceScope()||session!==workspaceUI.session)return;if(workspaceUI.attachments.length+result.items.length>4)throw new Error('每次最多4个附件，请先移除多余附件。');workspaceUI.attachments.push(...result.items);renderChatAttachments();}catch(error){if(key===workspaceScope())toast(errorMessage(error),'error');}
 });
 document.addEventListener('click',event=>{if(!$('#chat-presets').contains(event.target))$('#chat-presets').open=false;});
});
