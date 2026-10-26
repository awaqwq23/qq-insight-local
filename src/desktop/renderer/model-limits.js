const capacityUI={request:0,busy:false,outputLimit:null,edit:0};
function capacityFields(){return {context_tokens:Number($('#model-context').value),tpm_tokens:Number($('#model-tpm').value),output_tokens:Number($('#model-output').value),...(capacityUI.outputLimit?{output_limit_tokens:capacityUI.outputLimit}:{})};}
function renderCapacity(limits){
 if(!$('#model-context'))return;
 $('#model-context').value=limits?.context_tokens||32768;
 $('#model-tpm').value=limits?.tpm_tokens||0;
 capacityUI.outputLimit=limits?.output_limit_tokens||null;
 $('#model-output').max=capacityUI.outputLimit||1000000;
 $('#model-output').value=limits?.output_tokens||Math.min(65536,capacityUI.outputLimit||1000000,Math.floor(Number($('#model-context').value)/4));
 $('#model-capacity-source').textContent=limits?.source||'容量未知，暂用32768 Token保守额度。';
 const t=limits?.test;
 const successful=t?.input_source==='local-imported'?`真实记录压缩测试：已成功单段最多读取 ${formatNumber(t.successful_messages)} 条；成功请求最大输入 ${formatNumber(t.successful_input_tokens)} Token（两项分别统计）`:`已成功测试 ${formatNumber(t?.successful_messages)} 条 / ${formatNumber(t?.successful_input_tokens)} ${t?.input_measured?'接口返回输入':'保守预估输入'} Token`;
 $('#model-capacity-status').textContent=t?`${successful}；${t.reported_context_tokens?'接口报告上下文 '+formatNumber(t.reported_context_tokens):'未测得确切上下文上限'}。停止原因：${t.reason}。${t.input_source==='local-imported'?'原文容量与整次完成情况须另行验证':`1万条合成消息估算 ${t.estimated_10000_tokens?formatNumber(t.estimated_10000_tokens):'未知'} Token`}。测试时间 ${new Date(t.at).toLocaleString('zh-CN')}。`:'尚未测试；模型条数建议是估算，长消息、记忆和图片描述会占用更多额度。';
 updateCapacityRecommendation(limits);
}
function updateCapacityRecommendation(limits){
 const fields=capacityFields();
 const input=Math.max(0,Math.min(fields.context_tokens-fields.output_tokens-1024,fields.tpm_tokens?fields.tpm_tokens*.8-fields.output_tokens:10000000));
 const count=limits?.recommended_messages||Math.max(1,Math.min(10000,Math.floor((input-4096)/256)));
 $('#model-recommendation').textContent=`推荐每次最多读取 ${formatNumber(count)} 条（按每条256 Token保守估算）；模型侧输出 ${formatNumber(fields.output_tokens)} Token，实际仍取与AI预算输出较小值。${capacityUI.outputLimit?'接口输出上限 '+formatNumber(capacityUI.outputLimit)+' Token。':''}群画像长报告推荐65536；输出与输入共同占用上下文。TPM=0 表示未知 / 未配置。`;
}
async function refreshModelLimits(){
 const token=++capacityUI.request,edit=capacityUI.edit,profile=currentModelProfile();if(!profile)return;
 const catalog=state.modelCatalog;
 const metadata=catalog.baseUrl===$('#model-base-url').value&&catalog.provider===$('#model-provider').value?catalog.capabilities?.find(item=>item.id===$('#model-id').value)?.limits:null;
 if(metadata){renderCapacity(metadata);return;}
 const same=profile.model===$('#model-id').value&&profile.baseUrl===$('#model-base-url').value&&profile.provider===$('#model-provider').value;
 if(same&&profile.limits){renderCapacity(profile.limits);return;}
 if(!window.qqInsight?.modelLimits){renderCapacity(null);return;}
 try{const result=await window.qqInsight.modelLimits({model:$('#model-id').value,baseUrl:$('#model-base-url').value,provider:$('#model-provider').value});if(token===capacityUI.request&&edit===capacityUI.edit&&profile.id===currentModelProfile()?.id)renderCapacity(result);}catch{if(token===capacityUI.request&&edit===capacityUI.edit&&profile.id===currentModelProfile()?.id)renderCapacity(null);}
}
async function runCapacityTest(){
 if(capacityUI.busy)return;
 const maxMessages=Number($('#capacity-max-messages').value),maxTokens=Number($('#capacity-max-tokens').value);
 if(!Number.isInteger(maxMessages)||maxMessages<1||maxMessages>10000||!Number.isInteger(maxTokens)||maxTokens<2000||maxTokens>2000000){toast('请填写有效的测试条数与 Token 上限。','error');return;}
 capacityUI.busy=true;$('#capacity-test').disabled=true;$('#capacity-cancel').disabled=false;
 try{
  await saveModelProfile();const profileId=currentModelProfile().id;
  $('#model-capacity-status').textContent='正在测试合成消息，逐次用量将计入账本…';
  const result=await window.qqInsight.testCapacity({profileId,maxMessages,maxTokens});
  state.settings=result.settings;
  if(currentModelProfile()?.id===profileId)renderCapacity(currentModelProfile().limits);
  await loadUsage();
 }catch(error){$('#model-capacity-status').textContent=errorMessage(error);await loadUsage();}
 finally{capacityUI.busy=false;$('#capacity-test').disabled=false;$('#capacity-cancel').disabled=true;}
}
function confirmReadingLimit(count,recommended){
 const dialog=$('#capacity-warning');$('#capacity-warning-text').textContent=`本次选择 ${formatNumber(count)} 条，超过当前模型推荐的 ${formatNumber(recommended)} 条。长消息可能需要更多分块并触发预算、TPM 或输出截断。`;
 return new Promise(resolve=>{const finish=value=>{dialog.close();dialog.oncancel=null;resolve(value);};$('#capacity-warning-cancel').onclick=()=>finish(false);$('#capacity-warning-continue').onclick=()=>finish(true);dialog.oncancel=event=>{event.preventDefault();finish(false);};dialog.showModal();});
}
document.addEventListener('DOMContentLoaded',()=>{
 $('#model-capacity-fields').insertAdjacentHTML('beforeend',`<h4>模型容量与读取建议</h4><div class="model-form"><label class="field"><span>最大上下文 Token（含输入与输出）</span><input id="model-context" type="number" min="2048" max="10000000" value="32768"></label><label class="field"><span>TPM：每分钟 Token 限额（0 为未知）</span><input id="model-tpm" type="number" min="0" max="10000000" value="0"></label><label class="field"><span>单段最大输出 Token</span><input id="model-output" type="number" min="512" max="1000000" value="8192"></label></div><p id="model-capacity-source" class="field-hint"></p><p id="model-recommendation" class="field-hint"></p><details><summary>手动测试模型最大读取量（产生 API 用量）</summary><p class="field-hint">发送软件生成的合成讨论，不发送 QQ 正文。最多8次请求，受下方预算约束；总测试 Token 按保守预占累计限制。成功量是已验证下限，触发限流不能证明上下文上限。测试完成自动保存建议；改变模型、地址或密钥后需重新测试。</p><div class="model-form"><label class="field"><span>测试消息上限（1–10000）</span><input id="capacity-max-messages" type="number" min="1" max="10000" value="10000"></label><label class="field"><span>总测试 Token 上限（2000–2000000）</span><input id="capacity-max-tokens" type="number" min="2000" max="2000000" value="100000"></label></div><div class="form-actions"><button id="capacity-test" type="button" class="outline-button">保存配置并测试读取量</button><button id="capacity-cancel" type="button" class="text-button" disabled>取消测试</button></div></details><p id="model-capacity-status" class="field-hint" role="status" aria-live="polite"></p>`);
 document.body.insertAdjacentHTML('beforeend',`<dialog id="capacity-warning" class="modal-card" closedby="any" aria-labelledby="capacity-warning-title"><h2 id="capacity-warning-title">超过推荐读取条数</h2><p id="capacity-warning-text"></p><div class="form-actions"><button id="capacity-warning-cancel" class="outline-button">返回调整</button><button id="capacity-warning-continue" class="primary-button">仍按此范围分析</button></div></dialog>`);
 for(const id of ['model-context','model-tpm','model-output'])$(`#${id}`).addEventListener('input',()=>{capacityUI.edit++;updateCapacityRecommendation();});
 for(const id of ['model-id','model-base-url','model-provider'])$(`#${id}`).addEventListener('input',()=>refreshModelLimits());
 $('#model-provider').addEventListener('change',()=>refreshModelLimits());
 $('#capacity-test').addEventListener('click',runCapacityTest);
 $('#capacity-cancel').addEventListener('click',()=>window.qqInsight.cancelCapacity());
 window.qqInsight?.onCapacityProgress?.(payload=>{if(capacityUI.busy)$('#model-capacity-status').textContent=payload.message;});
});
