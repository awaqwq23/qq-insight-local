const workspaceUI={conversation:'',attachments:[],busy:false,request:0,listRequest:0,scope:'',session:'',chats:[],turns:[],offset:0,drafts:new Map(),edit:'',activeSession:'',activeAccount:'',progressRun:''};
const workspaceScope=()=>{const s=activeScope();return s.platform+'/'+s.account_id+'/'+workspaceUI.conversation;};

function resetWorkspaceChats(conversation=''){
 const accountKey=activeScope().platform+'/'+activeScope().account_id+'/';
 if(workspaceUI.scope.startsWith(accountKey)&&workspaceUI.session)workspaceUI.drafts.set(workspaceUI.session,{text:$('#workspace-agent-question').value,edit:workspaceUI.edit,attachments:workspaceUI.attachments});
 if(!workspaceUI.scope.startsWith(accountKey))workspaceUI.drafts.clear();
 if($('#chat-memory-dialog')?.open)closeChatMemory();
 workspaceUI.conversation=conversation;workspaceUI.attachments=[];
 workspaceUI.request++;workspaceUI.listRequest++;workspaceUI.scope=workspaceScope();workspaceUI.session='';workspaceUI.chats=[];workspaceUI.turns=[];workspaceUI.edit='';
 $('#workspace-chat-list').replaceChildren();$('#workspace-agent-history').replaceChildren();$('#workspace-agent-question').value='';$('#workspace-agent-status').textContent='';
 $('#workspace-chat-title').textContent='新对话';$('#workspace-chat-rename').disabled=true;
 for(const id of ['workspace-chat-rename-form','workspace-chat-edit-note','workspace-chat-branch-field','workspace-turn-more','workspace-chat-more'])$('#'+id).hidden=true;
}

function renderWorkspaceControls(){
 const own=workspaceUI.busy&&workspaceUI.activeSession===workspaceUI.session&&workspaceUI.activeAccount===activeScope().account_id;
 $('#workspace-agent-run').disabled=workspaceUI.busy;$('#workspace-agent-attach').disabled=workspaceUI.busy;$('#workspace-agent-cancel').hidden=!own;$('#workspace-agent-cancel').disabled=!own;$('#workspace-agent-question').disabled=own;
 $('#workspace-agent-run').textContent=workspaceUI.edit?'修改并重新生成':'发送';$('#workspace-chat-edit-note').hidden=!workspaceUI.edit;
 renderChatAttachments();
 $('#workspace-chat-branch').disabled=own;$('#workspace-chat-rename').disabled=!workspaceUI.session;
}

async function loadWorkspaceHistory(append=false){
 if(workspaceUI.scope!==workspaceScope())resetWorkspaceChats(workspaceUI.conversation);
 const scope=activeScope(),token=++workspaceUI.listRequest,key=workspaceScope();
 if(!scope.account_id||scope.platform!=='qq'){$('#workspace-agent-history').textContent='请先选择已导入记录的QQ账号。';return;}
 try{
  const result=await rpc('workspace.chat.list',{account_id:scope.account_id,conversation_id:workspaceUI.conversation,offset:append?workspaceUI.chats.length:0,limit:50});
  if(token!==workspaceUI.listRequest||key!==workspaceScope())return;
  workspaceUI.chats=append?[...workspaceUI.chats,...result.items]:result.items;renderWorkspaceChatList();$('#workspace-chat-more').hidden=!result.has_more;
  if(!workspaceUI.session&&workspaceUI.chats.length)await selectWorkspaceChat(workspaceUI.chats[0].id);
  else if(workspaceUI.session)await loadWorkspaceSession();
  else{$('#workspace-agent-history').innerHTML='<div class="agent-chat-empty"><h3>开始一个新对话</h3><p>可以连续追问、调整要求，或修改旧问题重新生成。每个对话独立保存。</p></div>';$('#workspace-agent-suggestions').hidden=!!workspaceUI.conversation;}
 }catch(error){if(token===workspaceUI.listRequest&&key===workspaceScope())$('#workspace-agent-status').textContent=errorMessage(error);}
 renderWorkspaceControls();
}

function renderWorkspaceChatList(){
 $('#workspace-chat-list').innerHTML=workspaceUI.chats.map(chat=>`<button class="agent-chat-item ${chat.id===workspaceUI.session?'active':''}" type="button" data-workspace-chat="${escapeHtml(chat.id)}" ${chat.id===workspaceUI.session?'aria-current="page"':''}><strong>${escapeHtml(chat.title)}</strong><small>${escapeHtml(new Date(chat.updated_at).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}))}${chat.status==='running'?' · 处理中':''}</small></button>`).join('');
 $('#workspace-chat-list').querySelectorAll('[data-workspace-chat]').forEach(button=>button.addEventListener('click',()=>{$('#workspace-chat-menu').open=false;selectWorkspaceChat(button.dataset.workspaceChat);}));
}

async function selectWorkspaceChat(id){
 if(workspaceUI.session)workspaceUI.drafts.set(workspaceUI.session,{text:$('#workspace-agent-question').value,edit:workspaceUI.edit,attachments:workspaceUI.attachments});
 workspaceUI.session=id;workspaceUI.offset=0;workspaceUI.turns=[];workspaceUI.request++;
 const draft=workspaceUI.drafts.get(id);workspaceUI.edit=draft?.edit||'';workspaceUI.attachments=draft?.attachments||[];$('#workspace-agent-question').value=draft?.text||'';
 $('#workspace-chat-rename-form').hidden=true;$('#workspace-agent-status').textContent='';$('#workspace-agent-history').replaceChildren();
 renderWorkspaceChatList();renderWorkspaceControls();await loadWorkspaceSession();
}

async function loadWorkspaceSession(older=false){
 const session=workspaceUI.session,scope=activeScope(),key=workspaceScope(),token=++workspaceUI.request;if(!session)return;
 const container=$('#workspace-agent-history');container.setAttribute('aria-busy','true');
 try{
  const result=await rpc('workspace.chat.get',{account_id:scope.account_id,session_id:session,offset:older?workspaceUI.offset:0,limit:50});
  if(token!==workspaceUI.request||key!==workspaceScope()||session!==workspaceUI.session)return;
  workspaceUI.turns=older?[...result.items,...workspaceUI.turns]:result.items;workspaceUI.offset=result.next_offset;
  $('#workspace-chat-title').textContent=result.session.title;if($('#workspace-chat-rename-form').hidden)$('#workspace-chat-name').value=result.session.title;$('#workspace-turn-more').hidden=!result.has_more;
  $('#workspace-chat-branch-field').hidden=result.branches.length<=1;
  $('#workspace-chat-branch').innerHTML=result.branches.map(branch=>`<option value="${escapeHtml(branch.id)}">${escapeHtml(new Date(branch.created_at).toLocaleString('zh-CN'))} · ${escapeHtml(branch.question.slice(0,36))}</option>`).join('');
  $('#workspace-chat-branch').value=result.session.head_id;
  renderWorkspaceTurns();refreshChatCoverage();$('#workspace-agent-suggestions').hidden=workspaceUI.turns.length>0||!!workspaceUI.conversation;renderWorkspaceControls();if(!older)container.scrollTop=container.scrollHeight;
 }catch(error){if(token===workspaceUI.request&&key===workspaceScope())$('#workspace-agent-status').textContent=errorMessage(error);}
 finally{if(token===workspaceUI.request)container.setAttribute('aria-busy','false');}
}

function renderChatAnswer(text){
 const inline=value=>escapeHtml(value).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\*\*([^*]+)\*\*/g,'<strong>$1</strong>');
 const lines=String(text).split('\n'),out=[];let paragraph=[],code=null,list='';
 const flush=()=>{if(paragraph.length){out.push('<p>'+inline(paragraph.join('\n'))+'</p>');paragraph=[];}if(list){out.push('</'+list+'>');list='';}};
 for(let i=0;i<lines.length;i++){
  const line=lines[i];
  if(/^\s*```/.test(line)){
   flush();if(code!==null){out.push('<pre><code>'+escapeHtml(code.join('\n'))+'</code></pre>');code=null;}else code=[];continue;
  }
  if(code!==null){code.push(line);continue;}
  const heading=line.match(/^(#{1,3})\s+(.+)$/),item=line.match(/^\s*(?:([-*])|\d+[.)])\s+(.+)$/);
  if(heading){flush();const level=heading[1].length+2;out.push('<h'+level+'>'+inline(heading[2])+'</h'+level+'>');}
  else if(item){if(paragraph.length)flush();const type=item[1]?'ul':'ol';if(type!==list){flush();out.push('<'+type+'>');list=type;}out.push('<li>'+inline(item[2])+'</li>');}
  else if(!line.trim())flush();
  else{if(list)flush();paragraph.push(line);}
 }
 flush();if(code!==null)out.push('<pre><code>'+escapeHtml(code.join('\n'))+'</code></pre>');
 return out.join('');
}

function renderWorkspaceTurns(){
 const container=$('#workspace-agent-history');
 container.innerHTML=workspaceUI.turns.map(run=>`<article class="agent-chat-turn"><div class="agent-user-message"><span>你</span><p>${escapeHtml(run.question)}</p><div class="chat-attachments">${(run.attachments||[]).map(file=>`<span>▧ ${escapeHtml(file.filename)}</span>`).join('')}</div><button class="text-button" type="button" data-edit-workspace="${escapeHtml(run.id)}" ${workspaceUI.busy?'disabled':''}>修改问题</button></div><div class="agent-assistant-message"><div class="agent-answer-heading"><strong>QQ Insight</strong><small>${escapeHtml(({running:'正在处理…',completed:'',failed:'失败',cancelled:'已取消',interrupted:'已中断'})[run.status]||'')}</small></div><div class="workspace-answer">${renderChatAnswer(run.answer||run.error||(run.status==='running'?'正在读取当前对话与聊天工作区…':''))}</div>${run.steps.length?`<details><summary>读取 ${formatNumber(run.source_messages||0)} 条来源消息 · 查看过程</summary><ol>${run.steps.map(step=>`<li>${escapeHtml(({chat_history:'回读本对话',conversations:'检索会话',people:'查找人物',read_context:'读取记录与上下文',search_messages:'批量检索聊天',export_messages:'导出消息原文',statistics:'原记录统计',export_order:'导出发言顺序',write_markdown:'生成Markdown',images:'检索图片',inspect_image:'读取图片像素',analyze_members:'分批完善成员阶段画像',compress_context:'保存压缩上下文',memory_validation:'人物观察校验',save_image:'保存图片',memory:'读取记忆',update_memory:'更新记忆',update_agent:'保存会话设定',update_self:'保存我的设置',attachments:'查找附件',inspect_attachment:'阅读附件'})[step.name]||step.name)}${step.selected_messages!==undefined?'：'+formatNumber(step.selected_messages)+' 条，复用 '+formatNumber(step.reused_messages||0)+' 条，'+(step.short_context||step.reading_mode==='original'?'原文读取 ':'待压缩 ')+formatNumber(step.raw_messages||0)+' 条':''}${step.compressed_messages!==undefined?'：'+formatNumber(step.compressed_messages)+' 条已保存':''}${step.missing_images?' · 跳过缺图 '+formatNumber(step.missing_images)+' 张':''}${step.notes?.length||step.validation_notes?.length?' · 跳过 '+formatNumber((step.notes||step.validation_notes).length)+' 条无效人物观察':''}${step.error?'：'+escapeHtml(step.error):''}</li>`).join('')}</ol></details>`:''}<div class="workspace-artifacts">${run.artifacts.map(file=>`<div><strong>${escapeHtml(file.filename)}</strong> <small>${formatNumber(file.bytes)} 字节</small><button class="text-button" data-workspace-artifact="${escapeHtml(file.artifact_id)}" data-action="open">打开</button><button class="text-button" data-workspace-artifact="${escapeHtml(file.artifact_id)}" data-action="save">另存为</button></div>`).join('')}</div><div class="agent-turn-actions"><button class="text-button" type="button" data-retry-workspace="${escapeHtml(run.id)}" ${workspaceUI.busy?'disabled':''}>重新生成</button>${['failed','cancelled','interrupted'].includes(run.status)?`<button class="text-button" type="button" data-delete-workspace="${escapeHtml(run.id)}">删除失败记录（保留账本）</button>`:''}</div></div></article>`).join('')||'<div class="agent-chat-empty"><h3>想聊些什么？</h3><p>本对话自动保存，可以随时回来继续。</p></div>';
 const scope=activeScope(),session=workspaceUI.session;
 container.querySelectorAll('[data-edit-workspace],[data-retry-workspace]').forEach(button=>button.addEventListener('click',()=>{
  const id=button.dataset.editWorkspace||button.dataset.retryWorkspace,run=workspaceUI.turns.find(row=>row.id===id);if(!run||workspaceUI.busy)return;
  workspaceUI.edit=id;workspaceUI.attachments=run.attachments||[];$('#workspace-agent-question').value=run.question;renderWorkspaceControls();$('#workspace-agent-question').focus();if(button.dataset.retryWorkspace)$('#workspace-agent-form').requestSubmit();
 }));
 container.querySelectorAll('[data-delete-workspace]').forEach(button=>button.addEventListener('click',async()=>{
  button.disabled=true;try{await rpc('workspace.history.delete',{account_id:scope.account_id,run_id:button.dataset.deleteWorkspace});if(session===workspaceUI.session&&scope.account_id===activeScope().account_id)await loadWorkspaceHistory();}catch(error){button.disabled=false;toast(errorMessage(error),'error');}
 }));
 container.querySelectorAll('[data-workspace-artifact]').forEach(button=>button.addEventListener('click',async()=>{
  button.disabled=true;try{await window.qqInsight.workspaceArtifact({account_id:scope.account_id,artifact_id:button.dataset.workspaceArtifact,action:button.dataset.action});}catch(error){toast(errorMessage(error),'error');}finally{button.disabled=false;}
 }));
}

async function createWorkspaceChat(){
 const scope=activeScope(),key=workspaceScope(),chat=await rpc('workspace.chat.create',{account_id:scope.account_id,conversation_id:workspaceUI.conversation});if(key!==workspaceScope())return '';
 await selectWorkspaceChat(chat.id);await loadWorkspaceHistory();return chat.id;
}

document.addEventListener('DOMContentLoaded',()=>{
 for(const id of ['workspace-chat-new','workspace-chat-create'])$('#'+id).addEventListener('click',()=>{$('#workspace-chat-menu').open=false;createWorkspaceChat().catch(error=>toast(errorMessage(error),'error'));});
 $('#workspace-chat-more').addEventListener('click',()=>loadWorkspaceHistory(true));$('#workspace-turn-more').addEventListener('click',()=>loadWorkspaceSession(true));
 $('#workspace-chat-rename').addEventListener('click',()=>{$('#workspace-chat-rename-form').hidden=false;$('#workspace-chat-name').focus();});
 $('#workspace-chat-rename-cancel').addEventListener('click',()=>$('#workspace-chat-rename-form').hidden=true);
 $('#workspace-chat-rename-form').addEventListener('submit',async event=>{
  event.preventDefault();const session=workspaceUI.session,scope=activeScope();
  try{await rpc('workspace.chat.rename',{session_id:session,account_id:scope.account_id,title:$('#workspace-chat-name').value});if(session===workspaceUI.session&&scope.account_id===activeScope().account_id){$('#workspace-chat-rename-form').hidden=true;await loadWorkspaceHistory();}}catch(error){toast(errorMessage(error),'error');}
 });
 $('#workspace-chat-branch').addEventListener('change',async()=>{
  const session=workspaceUI.session,scope=activeScope();try{await rpc('workspace.chat.select',{session_id:session,account_id:scope.account_id,head_id:$('#workspace-chat-branch').value});if(session===workspaceUI.session&&scope.account_id===activeScope().account_id){workspaceUI.edit='';renderWorkspaceControls();await loadWorkspaceSession();}}catch(error){toast(errorMessage(error),'error');}
 });
 $('#workspace-chat-edit-cancel').addEventListener('click',()=>{workspaceUI.edit='';workspaceUI.attachments=[];$('#workspace-agent-question').value='';renderWorkspaceControls();});
 $('#workspace-agent-form').addEventListener('submit',async event=>{
  event.preventDefault();if(workspaceUI.busy)return;
  const scope=activeScope(),question=$('#workspace-agent-question').value.trim(),key=workspaceScope();if(!scope.account_id||scope.platform!=='qq'||!question){toast('请选择QQ账号并填写问题。','error');return;}
  workspaceUI.busy=true;workspaceUI.activeAccount=scope.account_id;workspaceUI.activeSession=workspaceUI.session;renderWorkspaceControls();
  let session=workspaceUI.session,completed=false;const edit=workspaceUI.edit;
  try{
   if(!session)session=await createWorkspaceChat();if(!session||key!==workspaceScope())return;
   workspaceUI.activeSession=session;renderWorkspaceControls();$('#workspace-agent-status').textContent='正在读取本对话上下文…';
   const result=await window.qqInsight.runWorkspaceAgent({account_id:scope.account_id,session_id:session,conversation_id:workspaceUI.conversation,question,edit_run_id:edit,attachment_ids:workspaceUI.attachments.map(file=>file.id)});
   completed=true;
   if(session===workspaceUI.session&&key===workspaceScope())$('#workspace-agent-status').textContent=result.status==='completed'?'已保存，可以继续追问或修改。':({failed:'尚未完成，进度和文件已保存。',cancelled:'已取消，已完成部分已保留。'})[result.status]||result.status;
  }catch(error){if(session===workspaceUI.session&&key===workspaceScope())$('#workspace-agent-status').textContent=errorMessage(error);}
  finally{
   workspaceUI.busy=false;workspaceUI.activeSession='';workspaceUI.activeAccount='';
   if(session&&completed){workspaceUI.drafts.delete(session);if(session===workspaceUI.session&&key===workspaceScope()){workspaceUI.edit='';workspaceUI.attachments=[];if($('#workspace-agent-question').value.trim()===question)$('#workspace-agent-question').value='';}}
   renderWorkspaceControls();await loadWorkspaceHistory();
  }
 });
 $('#workspace-agent-question').addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();if(!workspaceUI.busy)$('#workspace-agent-form').requestSubmit();}});
 $('#workspace-agent-cancel').addEventListener('click',()=>window.qqInsight.cancelWorkspaceAgent());$('#workspace-agent-refresh').addEventListener('click',()=>loadWorkspaceHistory());
 $('#workspace-agent-suggestions').querySelectorAll('[data-question]').forEach(button=>button.addEventListener('click',()=>{$('#workspace-agent-question').value=button.dataset.question;$('#workspace-agent-question').focus();}));
 window.qqInsight?.onWorkspaceProgress?.(payload=>{
  if(payload.account_id!==activeScope().account_id||payload.session_id!==workspaceUI.session)return;$('#workspace-agent-status').textContent=payload.message;
  if(payload.run_id&&payload.run_id!==workspaceUI.progressRun){workspaceUI.progressRun=payload.run_id;loadWorkspaceHistory();}
 });
});
