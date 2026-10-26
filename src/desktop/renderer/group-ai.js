const groupAI = { scope: null, conversation: null, catalog: [], request: 0, tab: 'analysis', busy: false, settings: null, historyRequest: 0, jobPage: 1, itemPage: 1, selectedJob: '' };

function attachConversationActions(id = '') {
  const conversation = state.conversations.find(item => item.id === id) || state.overview?.recent_conversations.find(item => item.id === id);
  const isConversation = ['group','c2c'].includes(conversation?.kind) && $('#message-scope').value === 'conversation';
  const isGroup = isConversation && conversation.kind === 'group';
  $('#message-header .conversation-actions')?.remove();
  $('#message-header').insertAdjacentHTML('beforeend', `<div class="conversation-actions">
    ${isConversation ? '<button type="button" class="primary-button" data-open-ai="analysis">AI聊天</button>' : ''}
    <details id="conversation-tools" class="conversation-tools">
      <summary class="outline-button">其他功能 <span aria-hidden="true">⌄</span></summary>
      <div class="conversation-tools-panel" aria-label="其他功能">
        ${isConversation ? `<p class="tools-section-label">会话</p>
        <button type="button" data-open-ai="settings">记忆与设置</button>
        <button type="button" data-open-ai="history">对话记录</button>` : ''}
        ${isGroup ? `<p class="tools-section-label">本群名单</p>
        <button type="button" data-export="members" title="QQ原昵称与群名片双列导出；仅包含已导入聊天中的发言成员，不是完整群成员名单">导出发言成员<small>本地聊天中发过言的人 · 双名称</small></button>
        <button type="button" data-export="cached_members" title="读取QQ独立成员缓存，包含未发言者；导出前核对人数，缓存可能缺失或过期">导出成员缓存<small>无需管理员 · 可含未发言者</small></button>
        <button type="button" data-export="full_members" title="在QQ群官网扫码登录，读取包含未发言者的名单，核对全部分页后导出；关闭窗口可取消">导出全体成员（官网）<small>需官网访问权限 · 登录后读取</small></button>` : ''}
        <p class="tools-section-label">当前账号</p>
        <button type="button" id="export-groups" data-export="groups" title="导出当前账号本地已导入群，包含群原名称与备注两列">导出群列表<small>群原名／群备注 · 双列导出</small></button>
      </div>
    </details>
  </div>`);
  const menu = $('#conversation-tools');
  const scope = activeScope();
  $('#message-header').querySelectorAll('[data-open-ai], [data-export]').forEach(button => button.addEventListener('click', () => {
    menu.open = false;
    if (menu.contains(button)) menu.querySelector('summary').focus();
    if (scope.account_id !== activeScope().account_id || scope.platform !== activeScope().platform || (isConversation && id !== state.activeConversation)) {
      toast('账号或会话已切换，请重新打开其他功能。'); return;
    }
    if (button.dataset.export) exportRoster(button.dataset.export, button.dataset.export === 'groups' ? '' : id, button);
    else openConversationAgent(id, button.dataset.openAi);
  }));
}
function groupParams() { return { ...groupAI.scope, conversation_id: groupAI.conversation.id }; }
function sameGroup(request) { return request === groupAI.request && groupAI.scope?.account_id === activeScope().account_id && groupAI.scope?.platform === activeScope().platform; }

async function openGroupAI(id, tab = 'analysis', feature = '') {
  const conversation = state.conversations.find(item => item.id === id);
  if (!conversation || conversation.kind !== 'group') { toast('请先从消息浏览中选择一个群。'); showView('conversations'); return; }
  groupAI.scope = activeScope(); groupAI.conversation = conversation;
  $('#ai-memory-list').replaceChildren();$('#ai-person-id').value='';$('#ai-person-cross-group').checked=false;
  groupAI.jobPage=1;groupAI.itemPage=1;groupAI.selectedJob='';
  $('#ai-history-jobs').replaceChildren();$('#ai-history-items').replaceChildren();$('#ai-history-summary').textContent='';$('#ai-history-memory').textContent='';$('#ai-history-detail').hidden=true;
  if($('#ai-history-stages')){$('#ai-history-stages').replaceChildren();$('#ai-history-stages').hidden=true;}
  const request = ++groupAI.request;
  $('#ai-group-title').textContent = conversation.title;
  $('#ai-status').textContent = '正在读取本群设置…';
  showView('group-ai');
  try {
    const [catalog, settings] = await Promise.all([rpc('ai.catalog'), rpc('group.get', groupParams())]);
    if (!sameGroup(request)) return;
    groupAI.catalog = catalog.items; groupAI.settings = settings;
    const choices = catalog.items.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
    for (const id of ['ai-feature','ai-history-feature']) {
      const previous = $(`#${id}`).value; $(`#${id}`).innerHTML = choices;
      if (catalog.items.some(item => item.id === previous)) $(`#${id}`).value = previous;
    }
    const scheduleItems=catalog.items.filter(item=>item.schedulable!==false);
    const previousSchedule=$('#group-schedule-feature').value;
    $('#group-schedule-feature').innerHTML=scheduleItems.map(item=>`<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join('');
    if(scheduleItems.some(item=>item.id===previousSchedule))$('#group-schedule-feature').value=previousSchedule;
    if (feature) { $('#ai-feature').value = feature; $('#ai-history-feature').value = feature; }
    renderGroupSettings(settings); renderPrompt();
    $('#ai-compression').value=settings.compression||'off';$('#ai-length').value=settings.output_chars||500;$('#ai-hierarchical').checked=!!settings.hierarchical;renderCompressionNotice();
    $('#ai-status').textContent = '';
    const model = state.settings?.modelProfiles?.find(item => item.id === state.settings.activeModelProfileId);
    if(model?.limits?.recommended_messages)$('#ai-limit').value=model.limits.recommended_messages;
    $('#ai-model-info').textContent = `当前模型：${model?.model || '尚未配置'}${model?.limits?' · 推荐每次最多 '+formatNumber(model.limits.recommended_messages)+' 条 · 上下文 '+formatNumber(model.limits.context_tokens)+' Token':''} · 本群角色：${settings.effective_role || '未设置'} · ${settings.images ? '已开启图像分析，每段最多2张' : '仅分析文字与引用，图片内容计入覆盖缺口'}`;
    await setAITab(tab);
  } catch { if (sameGroup(request)) $('#ai-status').textContent = '读取失败，请重新打开本群。'; }
}

async function setAITab(tab) {
  groupAI.tab = tab;
  for (const name of ['analysis','settings','history']) $(`#ai-${name}-panel`).hidden = name !== tab;
  document.querySelectorAll('[data-ai-tab]').forEach(button => button.classList.toggle('active',button.dataset.aiTab===tab));
  if (tab === 'history') await loadAIHistory();
}
function renderPrompt() {
  const personStyle=$('#ai-feature').value==='style';$('#ai-person-options').hidden=!personStyle;$('#ai-hierarchical').disabled=personStyle;if(personStyle)$('#ai-hierarchical').checked=true;
  const selected = groupAI.catalog.find(item => item.id === $('#ai-feature').value);
  $('#ai-prompt').textContent = (selected?.prompt || '')+`\n本次输出目标约 ${$('#ai-length').value} 字${$('#ai-hierarchical').checked?'（最终汇总）':'/段'}；消息压缩：${({off:'关闭',balanced:'适度',strong:'强力'})[$('#ai-compression').value]||'关闭'}。实际请求按本次字数覆盖默认长度规则。`;
}
function renderCompressionNotice(){$('#ai-compression-note').hidden=$('#ai-compression').value==='off';renderPrompt();}
function renderGroupSettings(settings) {
  const values = { 'group-category':'category','group-ai-role':'role','group-self-names':'self_names','group-interests':'interests','group-instructions':'instructions','group-favorite-limit':'favorite_daily_limit','group-favorite-storage':'favorite_storage_mb','group-schedule':'schedule_minutes','group-schedule-feature':'schedule_feature' };
  for (const [id,key] of Object.entries(values)) $(`#${id}`).value = settings[key];
  $('#group-compression').value=settings.compression||'off';$('#group-output-chars').value=settings.output_chars||500;
  $('#group-watch-people').value = settings.watch_people.join(', ');
  $('#group-watch-keywords').value = settings.watch_keywords.join(', ');
  for (const [id,key] of [['group-remember','remember'],['group-images','images'],['group-auto-favorite','auto_favorite'],['group-hierarchical','hierarchical']]) $(`#${id}`).checked = !!settings[key];
  const memory=settings.memory_stats || {items:0,people:0};
  $('#group-memory-status').textContent=`本群长期记忆 ${memory.items || 0} 条${memory.people?`，涉及 ${memory.people} 人`:''}`;
}
async function saveGroupSettings(event) {
  event.preventDefault();
  const settings = { category:$('#group-category').value,role:$('#group-ai-role').value,self_names:$('#group-self-names').value,
    watch_people:$('#group-watch-people').value.split(/[,，;；、\s]+/).map(value=>value.trim()).filter(Boolean),
    watch_keywords:$('#group-watch-keywords').value.split(/[,，\n]/).map(value=>value.trim()).filter(Boolean),
    interests:$('#group-interests').value,instructions:$('#group-instructions').value,remember:$('#group-remember').checked,
    images:$('#group-images').checked,auto_favorite:$('#group-auto-favorite').checked,
    favorite_daily_limit:Number($('#group-favorite-limit').value),favorite_storage_mb:Number($('#group-favorite-storage').value),
    schedule_minutes:Number($('#group-schedule').value),schedule_feature:$('#group-schedule-feature').value,
    compression:$('#group-compression').value,output_chars:Number($('#group-output-chars').value),hierarchical:$('#group-hierarchical').checked };
  const params = groupParams(); const request = groupAI.request;
  try { const result = await rpc('group.save',{...params,settings}); if (sameGroup(request)) { groupAI.settings=result; toast('本群设置已保存'); } } catch {}
}

async function startAI(event, jobId = '', featureOverride = '') {
  event?.preventDefault();
  if (groupAI.busy || !groupAI.conversation) return;
  const request = groupAI.request;
  const input = { ...groupParams(),feature:featureOverride || $('#ai-feature').value,options:{mode:$('#ai-mode').value,limit:Number($('#ai-limit').value),
    sender:$('#ai-sender').value.trim(),query:$('#ai-query').value.trim(),goal:$('#ai-goal').value,tone:$('#ai-tone').value,output_chars:Number($('#ai-length').value),compression:$('#ai-compression').value,hierarchical:$('#ai-hierarchical').checked,context_reuse:$('#ai-context-reuse').checked} };
  if(input.feature==='style'&&!jobId){input.options.person_id=$('#ai-person-id').value.trim();input.options.cross_group=$('#ai-person-cross-group').checked;if(!input.options.person_id||!input.options.cross_group){toast('请填写完整 QQ / UID 并选择当前账号跨群范围。','error');return;}}
  if(input.feature==='profile'&&input.options.sender){input.options.person_id=input.options.sender;delete input.options.sender;}
  if(!jobId&&(!Number.isInteger(input.options.output_chars)||input.options.output_chars<1||input.options.output_chars>20000)){toast('输出目标字数须为1–20000的整数。','error');return;}
  if (input.options.mode==='time') {
    input.options.start = Math.floor(new Date($('#ai-start').value).getTime()/1000);
    input.options.end = Math.floor(new Date($('#ai-end').value).getTime()/1000);
    if (!Number.isFinite(input.options.start) || !Number.isFinite(input.options.end) || input.options.end<=input.options.start) { toast('请选择有效的时间段。','error');return; }
  }
  if (jobId) input.job_id = jobId;
  const recommendation=state.settings?.modelProfiles?.find(item=>item.id===state.settings.activeModelProfileId)?.limits?.recommended_messages;
  if(!jobId&&recommendation&&input.options.limit>recommendation){if(!await confirmReadingLimit(input.options.limit,recommendation)||!sameGroup(request)||groupAI.busy)return;}
  groupAI.busy=true; $('#ai-run').disabled=true; $('#ai-cancel').disabled=false;
  $('#ai-status').textContent='正在准备本群分析…';
  try {
    const result=await window.qqInsight.runAI(input);
    if (!sameGroup(request)) return;
    $('#ai-status').textContent=result.message || (result.status==='completed'?'分析完成，已保存历史结果':`分析状态：${statusLabel(result.status)}`);
    $('#ai-history-feature').value=input.feature;
    groupAI.jobPage=1;groupAI.itemPage=1;groupAI.selectedJob=result.job_id || '';
    if(input.feature==='identity'){
      groupAI.settings=await rpc('group.get',groupParams());
      if(sameGroup(request)){renderGroupSettings(groupAI.settings);$('#ai-status').textContent=groupAI.settings.role?`已识别并填入本群角色：${groupAI.settings.role}`:'证据不足，未改动本群角色。';await setAITab('settings');}
    }else await setAITab('history');
  } catch(error) { if(sameGroup(request)){ $('#ai-status').textContent=errorMessage(error);toast(errorMessage(error),'error');await loadAIHistory(); } }
  finally {groupAI.busy=false;$('#ai-run').disabled=false;$('#ai-cancel').disabled=true;}
}
async function guessGroupRole(){
  if(groupAI.busy)return;
  $('#ai-mode').value='recent';
  $('#ai-limit').value=Math.max(500,Number($('#ai-limit').value)||500);
  await startAI(null,'','identity');
}
function statusLabel(status) { return ({queued:'等待分析',running:'分析中',completed:'已完成',failed:'失败 / 可继续',cancelled:'已取消',interrupted:'中断 / 可继续',cached:'复用历史',empty:'无新增消息'})[status] || status; }

async function loadAIMemories(){
  const request=groupAI.request;const scope=groupParams();const container=$('#ai-memory-list');container.textContent='正在读取…';
  try{
    const result=await rpc('ai.memory.list',scope);if(!sameGroup(request))return;
    container.innerHTML=result.items.map((item,index)=>`<article class="ai-result-card"><h3>${escapeHtml(item.subject==='group'?'群记忆':item.subject)} · ${escapeHtml(item.title||'记忆')}</h3><p>${escapeHtml(item.correction||item.body||'此条已忘记')}</p><small>${escapeHtml(item.uncertainty||'')}${item.locked?' · 已锁定':''}</small>${(item.drafts||[]).map(text=>`<pre>${escapeHtml(text)}</pre>`).join('')}<textarea aria-label="更正记忆" maxlength="6000" data-memory-text="${index}">${escapeHtml(item.correction||item.body||'')}</textarea><div class="ai-memory-actions"><button type="button" class="text-button" data-memory-action="correct" data-memory-index="${index}">更正并锁定</button><button type="button" class="text-button" data-memory-action="forget" data-memory-index="${index}">忘记并暂停此条</button><button type="button" class="text-button" data-memory-action="unlock" data-memory-index="${index}">解锁 / 解除暂停</button></div></article>`).join('')||'尚无记忆；成功分析且开启本群记忆后会积累有证据的成员画像。';
    container.querySelectorAll('[data-memory-action]').forEach(button=>button.addEventListener('click',async()=>{button.disabled=true;try{await rpc('ai.memory.update',{...scope,memory_key:result.items[Number(button.dataset.memoryIndex)].memory_key,action:button.dataset.memoryAction,correction:container.querySelector(`[data-memory-text="${button.dataset.memoryIndex}"]`).value});if(sameGroup(request))await loadAIMemories();}catch{button.disabled=false;}}));
  }catch{if(sameGroup(request))container.textContent='记忆读取失败，请刷新。';}
}

function resultCard(item) {
  const userStatus=({confirmed:'已确认',completed:'已完成',ignored:'已忽略',rejected:'已拒绝',saved:'已收藏'})[item.user_status] || '';
  const evidence=(item.evidence_ids||[]).map((id,index)=>`<button class="text-button" data-ai-evidence="${escapeHtml(id)}">原文 ${index+1}</button>`).join('');
  const action=(name,label)=>`<button class="text-button" data-item-action="${name}" data-item-id="${escapeHtml(item.id)}">${label}</button>`;
  return `<article class="ai-result-card" data-ai-item="${escapeHtml(item.id)}"><div class="section-title"><h3>${escapeHtml(item.title)}</h3>${item.feature==='watch'?`<small>特别关心：${escapeHtml(item.subject||'未配置')}</small>`:''}<span class="tag">${escapeHtml(item.category || '')} ${userStatus}${item.locked?' · 已锁定':''}</span></div><p>${escapeHtml(item.correction || item.body)}</p>${item.owner?`<small>责任 / 关系：${escapeHtml(item.owner)}　截止：${escapeHtml(item.due_text || '未知')}${item.due_at?`（${escapeHtml(item.due_at)}）`:''}</small>`:''}${item.uncertainty?`<p class="field-hint">待核实：${escapeHtml(item.uncertainty)}</p>`:''}${(item.drafts||[]).map(text=>`<div class="ai-draft"><p>${escapeHtml(text)}</p><button class="text-button" data-copy-draft>${item.feature==='style'?'复制风格 Prompt':'复制草稿'}</button></div>`).join('')}<div>${evidence}</div><div class="ai-item-actions">${item.feature==='collection'?action('save_favorite','加入收藏')+action('rejected','不喜欢')+(item.automatic?action('undo_favorite','撤销自动收藏'):''):action('confirmed','确认')+(item.feature==='work'?action('completed','完成'):'')+action('ignored','忽略')}${action(item.locked?'unlock':'lock',item.locked?'解锁':'锁定')}${item.feature==='profile'?action('forget','忘记此推断并暂停记忆'):''}</div><details><summary>更正内容</summary><textarea class="ai-correction" maxlength="4000">${escapeHtml(item.correction||item.body)}</textarea>${action('correct','保存更正并锁定')}</details></article>`;
}
function durationLabel(seconds){const value=Math.max(0,Number(seconds)||0);return value<1?'不足 1 秒':value<60?`${Math.round(value)} 秒`:`${Math.floor(value/60)} 分 ${Math.round(value%60)} 秒`;}
function compressionDescription(coverage){const reuse=coverage?.reused_messages?`复用 ${formatNumber(coverage.reused_messages)} 条已分析来源的压缩上下文 · 新读 ${formatNumber(coverage.raw_messages)} 条 · `:'';const c=coverage?.compression,h=coverage?.hierarchical;return reuse+(coverage?.output_chars?`目标 ${formatNumber(coverage.output_chars)} 字${h?'（最终汇总）':'/段'}`:'')+(h?` · 分段汇总：${formatNumber(h.map_chunks)} 段读取、${formatNumber(h.merge_calls)} 次汇总、${formatNumber(h.levels)} 层；请核实原文。`:'')+(c?` · ${c.mode==='strong'?'强力':'适度'}有损压缩：${formatNumber(c.original_messages)} 条 → ${formatNumber(c.sent_messages)} 条代表消息，折叠 ${formatNumber(c.folded)} 条，截短 ${formatNumber(c.shortened)} 处；材料 ${formatNumber(c.original_bytes)} → ${formatNumber(c.compressed_bytes)} 字节（非实际Token）；可能遗漏或失真，请核实原文。`:'');}
async function loadAIHistory(jobId = groupAI.selectedJob) {
  if (!groupAI.conversation) return;
  const previousJob=groupAI.selectedJob;
  groupAI.selectedJob=jobId || '';
  const request = groupAI.request; const historyRequest = ++groupAI.historyRequest; const feature = $('#ai-history-feature').value || 'work';
  // Keep the grid in place: removing it collapses the page and resets scroll while opening a report.
  if(!$('#ai-history-jobs').querySelector('.ai-job'))$('#ai-history-jobs').innerHTML='<p class="muted">正在读取本群分析记录…</p>';
  $('#ai-history-jobs').setAttribute('aria-busy','true');
  $('#ai-history-detail').hidden=!jobId;
  $('#ai-history-detail').setAttribute('aria-busy',jobId?'true':'false');
  if(jobId && previousJob!==jobId){$('#ai-history-summary').textContent='正在读取本次分析详情…';$('#ai-history-items').innerHTML='<p class="muted">正在读取详细结果…</p>';}
  $('#ai-history-jobs').querySelectorAll('.ai-job').forEach(card=>card.classList.toggle('selected',card.querySelector('[data-report-job]')?.dataset.reportJob===jobId));
  try {
    const result=await rpc('ai.history',{...groupParams(),feature,job_id:jobId,job_page:groupAI.jobPage,job_page_size:12,item_page:groupAI.itemPage,item_page_size:10});
    if (!sameGroup(request) || historyRequest !== groupAI.historyRequest || $('#ai-history-feature').value !== feature) return;
    const memory=result.memory || {items:0,people:0};
    $('#ai-history-memory').textContent=`已沉淀本群长期记忆 ${memory.items || 0} 条${memory.people?`，含 ${memory.people} 位成员`:''}；后续 AI 操作会读取并继续完善。`;
    const coverage=result.report?.coverage;
    $('#ai-history-detail').hidden=!jobId;
    $('#ai-history-summary').textContent=(result.report?.summary || '本次没有可显示的详细结果。')+(coverage?`\n分析 ${coverage.selected} 条消息 · 已完成 ${coverage.completed_messages??coverage.selected} 条 · ${coverage.completed_chunks??0}/${coverage.chunks} 个分块 · 图片/未知消息 ${coverage.media_or_unknown} 条${coverage.start?'\n消息时间：'+formatTime(coverage.start)+' 至 '+formatTime(coverage.end):''}`:'');
    if(coverage?.scope==='account_groups_person')$('#ai-history-summary').textContent+='\n跨群人物：'+coverage.person_id+' · 当前账号 '+coverage.source_groups+' 个已导入群。';
    if(coverage?.has_more)$('#ai-history-summary').textContent+='\n范围内还有更多消息，本次未全部覆盖；可增加条数或使用增量范围继续。';
    if(coverage?.watch_people?.length)$('#ai-history-summary').textContent+='\n逐人总结：'+coverage.watch_people.map(person=>person.target+' · '+({completed:'已分析',no_messages:'当前范围无消息',partial:'部分完成',pending:'待分析'}[person.status]||person.status)+' '+person.selected+' 条').join('；');
    if(coverage)$('#ai-history-summary').textContent+='\n'+compressionDescription(coverage);
    if(coverage?.validation_notes?.length)$('#ai-history-summary').textContent+='\n'+coverage.validation_notes.join('\n');
    let stages=$('#ai-history-stages');if(!stages){stages=document.createElement('details');stages.id='ai-history-stages';$('#ai-history-detail').append(stages);}
    stages.hidden=!coverage?.hierarchical;stages.innerHTML=coverage?.hierarchical?'<summary>分段与汇总过程（前100个阶段）</summary>'+(result.report?.stages||[]).map(stage=>`<article class="ai-job"><strong>${formatNumber(stage.index+1)} · ${stage.stage==='reduce'?'第'+formatNumber(stage.level)+'层汇总':'读取摘要'} · ${escapeHtml(statusLabel(stage.status))}</strong><p>${escapeHtml(stage.summary||'尚未生成摘要')}</p></article>`).join(''):'';
    const items=(result.report?.items || result.items || []).filter(item=>!item.forgotten);
    $('#ai-history-items').innerHTML=items.map(resultCard).join('') || '<div class="empty">本页没有可显示结果。</div>';
    $('#ai-history-jobs').innerHTML=result.jobs.map(job=>{const c=job.coverage||{};const range=c.start?`${formatTime(c.start)} 至 ${formatTime(c.end)}`:'本次范围无消息';return `<article class="ai-job ${job.id===jobId?'selected':''}"><button class="ai-job-open" data-report-job="${escapeHtml(job.id)}"><span class="ai-job-title">${escapeHtml(new Date(job.created_at).toLocaleString('zh-CN'))} · ${escapeHtml(job.feature_name || feature)}</span><span class="tag">${escapeHtml(statusLabel(job.status))}</span><span>耗时 ${escapeHtml(durationLabel(job.duration_seconds))} · 已完成 ${formatNumber(c.completed_messages||0)} / ${formatNumber(c.selected||0)} 条消息${c.failed_stage?' · 失败于'+(c.failed_stage==='reduce'?'汇总阶段':'含 '+formatNumber(c.failed_chunk_messages||0)+' 条消息的读取分块'):''} · ${formatNumber(c.chunks||0)} 个分块</span><small>消息时间：${escapeHtml(range)}</small><small>${escapeHtml(compressionDescription(c))}</small><small>${escapeHtml(job.model)} · ${formatNumber(job.usage.charged_tokens)} Token · ${escapeHtml(jobCost(job.calls||[],job.usage))}${job.usage.unknown_calls?'（含待核对预占）':''}</small></button>${['failed','cancelled','interrupted'].includes(job.status)?`<button class="outline-button" data-resume-job="${escapeHtml(job.id)}">继续未完成分块</button><button class="text-button" data-delete-job="${escapeHtml(job.id)}">删除失败记录</button>`:''}${job.error?`<small class="ai-job-error">${escapeHtml(job.error)}</small>`:''}<details><summary>逐次用量与费用</summary><div class="usage-scroll"><table class="usage-table"><tbody>${renderUsageRows(job.calls||[])}${job.calls_has_more?'<tr><td colspan="3">这里只显示最近200次调用，完整明细请在设置中分页查看。</td></tr>':''}</tbody></table></div></details></article>`;}).join('') || '<div class="empty">本功能还没有分析调用记录。</div>';
    const jobPaging=result.pagination?.jobs || {page:1,total:result.jobs.length,has_more:false};
    $('#ai-jobs-page-state').textContent=`第 ${jobPaging.page} 页 · 共 ${jobPaging.total} 次调用`;
    $('#ai-jobs-prev').disabled=jobPaging.page<=1;$('#ai-jobs-next').disabled=!jobPaging.has_more;
    const itemPaging=result.pagination?.items || {page:1,total:items.length,has_more:false};
    $('#ai-items-page-state').textContent=`第 ${itemPaging.page} 页 · 共 ${itemPaging.total} 条详情`;
    $('#ai-items-prev').disabled=itemPaging.page<=1;$('#ai-items-next').disabled=!itemPaging.has_more;
    $('#ai-history-items').querySelectorAll('[data-ai-evidence]').forEach(button=>button.addEventListener('click',()=>openMessageContext(button.dataset.aiEvidence)));
    $('#ai-history-items').querySelectorAll('[data-copy-draft]').forEach(button=>button.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(button.previousElementSibling.textContent);toast('草稿已复制，请自行发送');}catch{toast('复制失败，可选中文字手动复制。','error');}}));
    $('#ai-history-items').querySelectorAll('[data-item-action]').forEach(button=>button.addEventListener('click',async()=>{
      button.disabled=true;
      try{await rpc('ai.item.update',{...groupParams(),item_id:button.dataset.itemId,action:button.dataset.itemAction,correction:button.closest('[data-ai-item]').querySelector('.ai-correction').value});if(sameGroup(request))await loadAIHistory();}catch{}finally{button.disabled=false;}
    }));
    $('#ai-history-jobs').querySelectorAll('[data-delete-job]').forEach(button=>button.addEventListener('click',async()=>{button.disabled=true;try{await rpc('ai.history.delete',{...groupParams(),job_id:button.dataset.deleteJob});if(sameGroup(request)){groupAI.selectedJob='';groupAI.jobPage=1;await loadAIHistory('');toast('失败历史已删除，已合入条目和用量账本保留。');}}catch{button.disabled=false;}}));
    $('#ai-history-jobs').querySelectorAll('[data-report-job]').forEach(button=>button.addEventListener('click',()=>{groupAI.itemPage=1;loadAIHistory(button.dataset.reportJob);$('#ai-history-detail').scrollIntoView({block:'start'});}));
    $('#ai-history-jobs').querySelectorAll('[data-resume-job]').forEach(button=>button.addEventListener('click',()=>{ $('#ai-feature').value=feature;startAI(null,button.dataset.resumeJob); }));
  } catch {
    if(sameGroup(request) && historyRequest===groupAI.historyRequest){
      if(jobId){$('#ai-history-detail').hidden=false;$('#ai-history-summary').textContent='历史详情读取失败，已保留当前选择。请点击“刷新”重试。';}
      else if(!$('#ai-history-jobs').querySelector('.ai-job'))$('#ai-history-jobs').innerHTML='<div class="empty">历史结果读取失败，请点击“刷新”重试。</div>';
    }
  } finally {
    if(sameGroup(request) && historyRequest===groupAI.historyRequest){$('#ai-history-jobs').setAttribute('aria-busy','false');$('#ai-history-detail').setAttribute('aria-busy','false');}
  }
}

const budgetUI={loadVersion:0,editVersion:0,saving:false};
const budgetFields=[['budget-per-run','per_run_tokens'],['budget-daily','daily_tokens'],['budget-monthly','monthly_tokens'],['budget-output','output_tokens'],['budget-input-price','input_price'],['budget-output-price','output_price'],['budget-cost','monthly_cost'],['budget-currency','currency'],['budget-price-model','price_model']];
function renderAIBudget(budget,fill=true){
  const linked=budget.model_output,profile=state.settings?.modelProfiles?.find(item=>item.id===linked?.profile_id);
  if(profile&&profile.model===linked.model&&profile.baseUrl===linked.baseUrl){profile.limits=linked.limits;if(state.editingModelProfileId===profile.id&&!settingsUI.textDirty){++capacityUI.request;renderCapacity(profile.limits);}}
  for(const [id,key] of budgetFields){
    const node=$(`#${id}`);if(fill)node.value=budget[key]??'';
    const limit=budget.limits?.[key];if(limit){node.min=limit.min;node.max=limit.max;node.step='1';}
  }
  const model=state.settings?.modelProfiles?.find(item=>item.id===state.settings.activeModelProfileId),output=model?.limits?.output_tokens;
  $('#budget-effective-output').textContent=output?`已保存输出额度：预算 ${formatNumber(budget.output_tokens)}，当前模型 ${formatNumber(output)}；实际单次最多 ${formatNumber(Math.min(budget.output_tokens,output))} Token，还受输入与上下文、预算剩余额度约束。`:'群画像长报告推荐65536输出Token；请同时检查模型设置中的输出额度，实际取两者较小值。';
  $('#ai-budget-usage').textContent=`今日已用/预占 ${formatNumber(budget.daily_used)} / ${formatNumber(budget.daily_tokens)} Token，剩余 ${formatNumber(Math.max(0,budget.daily_tokens-budget.daily_used))}；本月 ${formatNumber(budget.monthly_used)} / ${formatNumber(budget.monthly_tokens)} Token；费用 ${budget.monthly_cost_used==null?'未知':Number(budget.monthly_cost_used).toFixed(4)+' '+budget.currency}；待核对请求 ${budget.uncertain_requests||0}；各币种费用：${Object.entries(budget.cost_totals||{}).map(([currency,cost])=>Number(cost).toFixed(6)+' '+currency).join(' / ')||'尚无'}；未知定价 ${budget.unknown_price_calls||0} 次`;
}
async function loadAIBudget(){
  const request=++budgetUI.loadVersion;const edit=budgetUI.editVersion;
  try{
    const budget=await rpc('ai.budget.get');if(request!==budgetUI.loadVersion)return;
    renderAIBudget(budget,edit===budgetUI.editVersion);loadOfficialPrices();
  }catch(error){if(request===budgetUI.loadVersion)$('#ai-budget-status').textContent='预算读取失败：'+errorMessage(error);}
}
async function saveAIBudget(event,useMaximum=false){
  event?.preventDefault();if(budgetUI.saving)return false;
  const form=$('#ai-budget-form');const status=$('#ai-budget-status');
  if(useMaximum){for(const id of ['budget-per-run','budget-daily','budget-monthly'])$(`#${id}`).value=$(`#${id}`).max;budgetUI.editVersion++;}
  const invalid=[...form.elements].find(node=>node.willValidate&&!node.checkValidity());
  if(invalid){status.textContent='预算未保存：'+(invalid.closest('.field')?.querySelector('span')?.textContent||'输入值')+'，'+invalid.validationMessage;invalid.reportValidity();return false;}
  budgetUI.saving=true;++budgetUI.loadVersion;
  const edit=budgetUI.editVersion;form.querySelectorAll('button').forEach(button=>button.disabled=true);status.textContent='正在保存预算…';
  try{
    const budget=await rpc('ai.budget.save',{settings:{per_run_tokens:Number($('#budget-per-run').value),daily_tokens:Number($('#budget-daily').value),monthly_tokens:Number($('#budget-monthly').value),output_tokens:Number($('#budget-output').value),monthly_cost:Number($('#budget-cost').value),currency:$('#budget-currency').value}});
    ++budgetUI.loadVersion;renderAIBudget(budget,edit===budgetUI.editVersion);
    status.textContent=`已保存并生效：输出 ${formatNumber(budget.output_tokens)}；单次分析 ${formatNumber(budget.per_run_tokens)}、每日 ${formatNumber(budget.daily_tokens)}、每月 ${formatNumber(budget.monthly_tokens)} Token。`+(edit!==budgetUI.editVersion?' 新修改尚未保存。':budget.model_output?'输出已同步当前模型；已发出的请求不变，后续请求使用新值。':'输出已保存；实际仍需有效的文字模型配置。');
    toast('AI 预算已保存并生效');return true;
  }catch(error){status.textContent='预算未保存：'+errorMessage(error);return false;}
  finally{budgetUI.saving=false;form.querySelectorAll('button').forEach(button=>button.disabled=false);}
}

document.addEventListener('DOMContentLoaded',()=>{
  attachConversationActions();
  document.addEventListener('click', event => {
    const menu = $('#conversation-tools');
    if (menu?.open && !menu.contains(event.target)) menu.open = false;
  });
  document.addEventListener('keydown', event => {
    const menu = $('#conversation-tools');
    if (event.key === 'Escape' && menu?.open) { menu.open = false; menu.querySelector('summary').focus(); }
  });
  $('#ai-back').addEventListener('click',()=>openConversation(groupAI.conversation.id));
  document.querySelectorAll('[data-ai-tab]').forEach(button=>button.addEventListener('click',()=>setAITab(button.dataset.aiTab)));
  $('#ai-feature').addEventListener('change',renderPrompt);
  $('#ai-compression').addEventListener('change',renderCompressionNotice);
  $('#ai-length').addEventListener('input',renderPrompt);
  $('#ai-hierarchical').addEventListener('change',renderPrompt);
  $('#group-settings-form').addEventListener('submit',saveGroupSettings);
  $('#group-guess-role').addEventListener('click',guessGroupRole);
  $('#ai-form').addEventListener('submit',startAI);
  $('#ai-cancel').addEventListener('click',async()=>{try{await window.qqInsight.cancelAI();$('#ai-status').textContent='正在取消分析…';}catch(error){toast(errorMessage(error),'error');}});
  $('#ai-history-feature').addEventListener('change',()=>{groupAI.jobPage=1;groupAI.itemPage=1;groupAI.selectedJob='';$('#ai-history-jobs').replaceChildren();loadAIHistory('');});
  $('#ai-memory-refresh').addEventListener('click',loadAIMemories);
  $('#ai-refresh-history').addEventListener('click',()=>loadAIHistory());
  $('#ai-close-detail').addEventListener('click',()=>{groupAI.selectedJob='';groupAI.itemPage=1;loadAIHistory('');});
  $('#ai-jobs-prev').addEventListener('click',()=>{if(groupAI.jobPage>1){groupAI.jobPage--;loadAIHistory();}});
  $('#ai-jobs-next').addEventListener('click',()=>{groupAI.jobPage++;loadAIHistory();});
  $('#ai-items-prev').addEventListener('click',()=>{if(groupAI.itemPage>1){groupAI.itemPage--;loadAIHistory();}});
  $('#ai-items-next').addEventListener('click',()=>{groupAI.itemPage++;loadAIHistory();});
  window.qqInsight?.onAIProgress?.(payload=>{if(payload.conversation_id===groupAI.conversation?.id&&payload.account_id===groupAI.scope?.account_id)$('#ai-status').textContent=payload.message;});
  $('#ai-budget-form').addEventListener('submit',event=>saveAIBudget(event));
  $('#ai-budget-form').addEventListener('input',()=>{budgetUI.editVersion++;$('#ai-budget-status').textContent='预算已修改，尚未保存。';});
  $('#budget-use-maximum').addEventListener('click',event=>saveAIBudget(event,true));
});
