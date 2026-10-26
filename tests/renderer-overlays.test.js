const {app,BrowserWindow}=require('electron');
const assert=require('node:assert/strict'),path=require('node:path');

app.whenReady().then(async()=>{
 const win=new BrowserWindow({show:false,width:1280,height:900,webPreferences:{offscreen:true,backgroundThrottling:false,contextIsolation:true,nodeIntegration:false}});
 const js=code=>win.webContents.executeJavaScript(`(async()=>{${code}})()`),tick=()=>new Promise(resolve=>setTimeout(resolve,100));
 const mouse=async(type,x,y)=>{win.webContents.sendInputEvent({type,x:Math.round(x),y:Math.round(y),button:'left',clickCount:1});await tick();};
 const click=async(x,y)=>{await mouse('mouseDown',x,y);await mouse('mouseUp',x,y);};
 const clickNode=async selector=>{const point=await js(`const node=document.querySelector(${JSON.stringify(selector)});node.scrollIntoView({block:'center'});const r=node.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};`);await click(point.x,point.y);};
 try{
  const page=process.env.QQ_TEST_PACKAGED==='1'?path.join(process.env.QQ_TEST_RESOURCES,'app.asar/src/desktop/renderer/index.html'):path.join(__dirname,'../src/desktop/renderer/index.html');
  await win.loadFile(page);
  await js(`
   state.settings={activeAccountId:'synthetic',activePlatform:'qq'};state.conversations=[{id:'group',title:'合成项目群',kind:'group'}];
   window.qa={writes:0,cancels:0,underlying:0};
   document.body.insertAdjacentHTML('beforeend','<button id="qa-underlying" style="position:fixed;left:0;top:0;width:30px;height:30px;z-index:1">底层操作</button>');$('#qa-underlying').onclick=()=>qa.underlying++;
   window.qqInsight={rpc:async(method)=>{
    if(method==='chat.settings.get')return {conversation:state.conversations[0],settings:{self_identity:'已保存身份',peer_identity:'',prompt:'已保存设定'},remember_enabled:true};
    if(method==='self.get')return {name:'合成本人',identity:'合成身份',preferences:'合成偏好'};
    if(method.endsWith('.save'))qa.writes++;
    return {items:[],total:0,unread:0,ranges:[]};
   },cancelSourceUpdate:async()=>{qa.cancels++;return {cancelled:true};}};
   resetWorkspaceChats('group');showView('conversation-agent');await openChatMemory('settings');
   $('#chat-agent-prompt').value='尚未保存的上级设定';$('#chat-self-identity').value='尚未保存的上级身份';$('#chat-remember').checked=false;
   $('#chat-open-self').click();
  `);await tick();
  assert.equal(await js(`return $('#chat-self-settings').hidden;`),false);
  await click(5,5);
  assert.equal(await js(`return $('#chat-memory-dialog').open&&!$('#chat-agent-settings').hidden;`),true,'blank backdrop returns to the parent settings');
  assert.deepEqual(await js(`return [$('#chat-agent-prompt').value,$('#chat-self-identity').value,$('#chat-remember').checked,qa.writes];`),['尚未保存的上级设定','尚未保存的上级身份',false,0]);
  assert.equal(await js(`return document.activeElement.id;`),'chat-open-self');

  // Native dialogs must dismiss only the top layer, including when DOM order differs from opening order.
  await js(`$('#chat-open-self').click();`);await tick();
  await js(`window.qa.warning=confirmReadingLimit(100,1);`);
  await click(5,5);
  assert.equal(await js(`return await qa.warning;`),false,'outside click resolves as cancel, not approval');
  assert.equal(await js(`return $('#chat-memory-dialog').open&&!$('#chat-self-settings').hidden;`),true);
  await js(`$('#chat-memory-title').click();`);
  assert.equal(await js(`return $('#chat-memory-dialog').open;`),true,'inside clicks do not dismiss');
  const inside=await js(`const r=$('#chat-memory-title').getBoundingClientRect();return {x:r.x+10,y:r.y+10};`);
  await mouse('mouseDown',inside.x,inside.y);await mouse('mouseUp',5,5);
  assert.equal(await js(`return !$('#chat-self-settings').hidden;`),true,'dragging out must not dismiss');
  await mouse('mouseDown',5,5);await mouse('mouseUp',inside.x,inside.y);
  assert.equal(await js(`return !$('#chat-self-settings').hidden;`),true,'dragging in must not dismiss');
  await js(`$('#chat-memory-close').click();`);await tick();
  assert.equal(await js(`return $('#chat-memory-dialog').open&&!$('#chat-agent-settings').hidden;`),true,'close button returns one logical level too');
  await click(5,5);assert.equal(await js(`return $('#chat-memory-dialog').open;`),false);

  await js(`window.qa.warning=confirmReadingLimit(100,1);await openChatMemory('settings');`);
  await click(5,5);assert.equal(await js(`return !$('#chat-memory-dialog').open&&$('#capacity-warning').open;`),true,'opening order takes precedence over DOM order');
  await click(5,5);assert.equal(await js(`return await qa.warning;`),false);

  await js(`await openChatMemory('settings');`);await clickNode('#chat-open-self');
  win.webContents.sendInputEvent({type:'keyDown',keyCode:'Escape'});win.webContents.sendInputEvent({type:'keyUp',keyCode:'Escape'});await tick();
  assert.deepEqual(await js(`return {open:$('#chat-memory-dialog').open,settings:!$('#chat-agent-settings').hidden,tab:chatMemoryUI.tab};`),{open:true,settings:true,tab:'settings'},'Escape returns only one logical level');
  await js(`resetWorkspaceChats();`);assert.equal(await js(`return $('#chat-memory-dialog').open;`),false,'scope change closes the entire old dialog');

  await js(`state.pendingSource={sourceId:'synthetic'};showDecryptModal({message:'合成读取说明'});`);
  const card=await js(`const r=$('#decrypt-modal .modal-card').getBoundingClientRect();return {x:r.x+15,y:r.y+15};`);
  await click(card.x,card.y);assert.equal(await js(`return $('#decrypt-modal').classList.contains('visible');`),true);
  await mouse('mouseDown',card.x,card.y);await mouse('mouseUp',5,5);
  assert.equal(await js(`return $('#decrypt-modal').classList.contains('visible');`),true);
  await mouse('mouseDown',5,5);await mouse('mouseUp',card.x,card.y);
  assert.equal(await js(`return $('#decrypt-modal').classList.contains('visible');`),true);
  await click(5,5);assert.equal(await js(`return $('#decrypt-modal').classList.contains('visible');`),false);
  await js(`state.pendingSource={sourceId:'synthetic'};showDecryptModal({message:'合成写入中'});state.decrypting=true;$('#cancel-decrypt').disabled=true;`);
  await click(5,5);assert.deepEqual(await js(`return [$('#decrypt-modal').classList.contains('visible'),qa.cancels];`),[true,0],'non-cancellable write is protected');
  await js(`$('#cancel-decrypt').disabled=false;`);await click(5,5);
  assert.deepEqual(await js(`return [$('#decrypt-modal').classList.contains('visible'),qa.cancels,qa.writes];`),[true,1,0],'outside click uses the existing asynchronous cancellation');
  assert.equal(await js(`return qa.underlying;`),0,'backdrop clicks must not activate the underlying page');
  await js(`state.decrypting=false;closeDecryptModal();`);
  console.log('Overlay UI passed: native backdrop clicks, nested parent drafts/focus, top-only and opening order, inside/drag guards, Escape, scope cleanup, cancellation and protected writes; synthetic only.');
 }catch(error){console.error(error);process.exitCode=1;}finally{win.destroy();app.exit(process.exitCode||0);}
});
