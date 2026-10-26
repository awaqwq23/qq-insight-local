const settingsUI={page:'models',kind:'text',textDirty:false,textVersion:0};

function hideSettingKeys(){
 document.querySelectorAll('[data-toggle-key]').forEach(button=>{
  const field=document.getElementById(button.dataset.toggleKey);
  if(field)field.type='password';
  button.textContent='显示';button.setAttribute('aria-pressed','false');button.setAttribute('aria-label','显示新输入的 API Key');
 });
}

function showSettingsPage(page){
 if(!['models','usage','data'].includes(page))return;
 settingsUI.page=page;hideSettingKeys();
 document.querySelectorAll('[data-settings-panel]').forEach(panel=>panel.hidden=panel.dataset.settingsPanel!==page);
 document.querySelectorAll('[data-settings-tab]').forEach(button=>{
  if(button.dataset.settingsTab===page)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');
 });
}

function showAPIKind(kind){
 if(!['text','vision','speech'].includes(kind))return;
 settingsUI.kind=kind;hideSettingKeys();
 $('#analysis-api-card').hidden=kind!=='text';$('#media-api-card').hidden=kind==='text';
 document.querySelectorAll('[data-media-form]').forEach(form=>form.closest('.media-model-card').hidden=form.dataset.mediaForm!==kind);
 document.querySelectorAll('[data-api-kind]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.apiKind===kind)));
 document.querySelectorAll('.profile-tab').forEach(button=>button.classList.toggle('active',kind==='text'&&button.dataset.profileId===state.editingModelProfileId));
}

function updateAPISettingsSummary(){
 for(const kind of ['vision','speech']){
  const profile=state.settings?.mediaProfiles?.[kind];
  $(`#api-${kind}-state`).textContent=profile?.hasApiKey&&profile?.model?'已配置 · '+profile.model:'待配置';
  const badge=document.querySelector(`[data-media-form="${kind}"]`)?.closest('.media-model-card').querySelector('.api-status-badge');
  if(badge)badge.textContent=profile?.hasApiKey&&profile?.model?'已配置':'待配置';
 }
 const profile=currentModelProfile();
 if(profile){
  $('#model-editor-title').textContent=profile.name||'新配置';
  $('#model-active-state').textContent=profile.id===state.settings?.activeModelProfileId?'当前使用':'未启用';
 }
}

function canLeaveModelProfile(){
 return !settingsUI.textDirty||window.confirm('当前文字配置有未保存修改。放弃修改并切换配置？');
}

document.addEventListener('DOMContentLoaded',()=>{
 document.querySelectorAll('[data-settings-tab]').forEach(button=>button.addEventListener('click',()=>showSettingsPage(button.dataset.settingsTab)));
 document.querySelectorAll('[data-api-kind]').forEach(button=>button.addEventListener('click',()=>showAPIKind(button.dataset.apiKind)));
 document.addEventListener('click',event=>{
  const button=event.target.closest('[data-toggle-key]');if(!button)return;
  const field=document.getElementById(button.dataset.toggleKey);if(!field)return;
  const visible=field.type==='password';field.type=visible?'text':'password';button.textContent=visible?'隐藏':'显示';button.setAttribute('aria-pressed',String(visible));button.setAttribute('aria-label',(visible?'隐藏':'显示')+'新输入的 API Key');
 });
 $('#analysis-api-card').addEventListener('input',()=>{settingsUI.textVersion++;settingsUI.textDirty=true;$('#model-edit-status').textContent='有未保存修改';});
 $('#analysis-api-card').addEventListener('change',()=>{settingsUI.textVersion++;settingsUI.textDirty=true;$('#model-edit-status').textContent='有未保存修改';});
 $('#model-search').addEventListener('input',()=>{state.modelCatalog.page=0;renderModelCatalog();});
 showSettingsPage('models');showAPIKind('text');
});
