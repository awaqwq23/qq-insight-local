const recentAIUI={items:[],request:0,scope:'',next:0};
const recentAIScope=()=>activeScope().platform+'/'+activeScope().account_id;
const recentAIStatus=value=>({running:'处理中',completed:'已完成',cached:'已完成',failed:'失败',cancelled:'已取消',interrupted:'已中断',empty:'无匹配记录'})[value]||'已保存';
const recentAIFeature=value=>({work:'工作概要',summary:'群聊速读',reply:'回复建议',collection:'收藏推荐',watch:'特别关注',identity:'我的角色',style:'人物风格',profile:'群与成员画像'})[value]||'AI分析';

async function loadRecentAIHistory(append=false){
 const scope=activeScope(),key=recentAIScope(),token=++recentAIUI.request;
 if(recentAIUI.scope!==key){recentAIUI.items=[];recentAIUI.next=0;}
 recentAIUI.scope=key;renderRecentAIHistory();
 const status=$('#ai-history-status'),list=$('#recent-ai-list');list.setAttribute('aria-busy','true');
 $('#recent-ai-more').hidden=true;status.textContent='正在读取历史记录…';
 try{
  if(!scope.account_id||scope.platform!=='qq'){status.textContent='请选择已导入记录的QQ账号。';return;}
  const result=await rpc('workspace.chat.recent',{account_id:scope.account_id,offset:append?recentAIUI.next:0,limit:50});
  if(token!==recentAIUI.request||key!==recentAIScope()||!$('#ai-history-view').classList.contains('active'))return;
  recentAIUI.items=[...new Map([...(append?recentAIUI.items:[]),...result.items].map(item=>[item.kind+item.id,item])).values()];recentAIUI.next=result.next_offset;
  renderRecentAIHistory();$('#recent-ai-more').hidden=!result.has_more;
  status.textContent=recentAIUI.items.length?`已显示 ${recentAIUI.items.length} 项 · 最近更新在前`:'';
 }catch(error){if(token===recentAIUI.request&&key===recentAIScope()){status.textContent=errorMessage(error);$('#recent-ai-more').hidden=!append;}}
 finally{if(token===recentAIUI.request)list.setAttribute('aria-busy','false');}
}

function renderRecentAIHistory(){
 const list=$('#recent-ai-list');
 list.innerHTML=recentAIUI.items.map((item,index)=>{
  const source=item.conversation_id?(item.conversation_kind==='c2c'?'私聊':'群聊')+' · '+item.conversation_title:'全局 AI Agent';
  const title=item.kind==='analysis'?recentAIFeature(item.feature):item.title;
  return `<button type="button" class="recent-ai-item" data-recent-ai="${index}"><span class="recent-ai-icon" aria-hidden="true">${item.kind==='analysis'?'◇':'✦'}</span><span class="recent-ai-copy"><span class="recent-ai-source">${escapeHtml(source)}${item.kind==='analysis'?' · 旧版分析':''}</span><strong>${escapeHtml(title)}</strong><span class="recent-ai-preview">${escapeHtml(item.preview||'打开查看已保存的对话')}</span></span><span class="recent-ai-meta"><time datetime="${escapeHtml(item.updated_at)}">${escapeHtml(new Date(item.updated_at).toLocaleString('zh-CN',{year:'numeric',month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit'}))}</time><span>${escapeHtml(recentAIStatus(item.status))} · 打开 →</span></span></button>`;
 }).join('')||'<div class="recent-ai-empty"><h2>还没有 AI 历史记录</h2><p>群聊、私聊与全局 AI 的对话会按最近更新时间出现在这里。</p></div>';
 list.querySelectorAll('[data-recent-ai]').forEach(button=>button.addEventListener('click',()=>openRecentAIHistory(recentAIUI.items[Number(button.dataset.recentAi)],button)));
}

async function openRecentAIHistory(item,button){
 const scope=activeScope(),key=recentAIScope(),token=++recentAIUI.request;
 button.disabled=true;
 try{
  // Resolve the session again before navigation: the list is only an account-scoped preview.
  const session=item.kind==='chat'?(await rpc('workspace.chat.get',{account_id:scope.account_id,session_id:item.id,limit:1})).session:null;
  if(token!==recentAIUI.request||key!==recentAIScope()||!$('#ai-history-view').classList.contains('active'))return;
  const cid=session?session.conversation_id:item.conversation_id;
  if(cid&&!state.conversations.some(c=>c.id===cid))state.conversations.push({id:cid,title:item.conversation_title,kind:item.conversation_kind});
  if(cid)state.activeConversation=cid;
  if(item.kind==='analysis'){
   await openGroupAI(cid,'history',item.feature);
   if(key===recentAIScope()&&groupAI.conversation?.id===cid)await loadAIHistory(item.id);
  }else{
   resetWorkspaceChats(cid||'');showView(cid?'conversation-agent':'workspace-agent',false);
   await selectWorkspaceChat(session.id);
   if(key===recentAIScope()&&workspaceUI.session===session.id)await loadWorkspaceHistory();
  }
 }catch(error){if(key===recentAIScope())toast(errorMessage(error),'error');}
 finally{button.disabled=false;}
}

document.addEventListener('DOMContentLoaded',()=>{
 $('#recent-ai-refresh').addEventListener('click',()=>loadRecentAIHistory());
 $('#recent-ai-more').addEventListener('click',()=>loadRecentAIHistory(true));
});
