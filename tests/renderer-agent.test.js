const {app,BrowserWindow}=require('electron');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
app.whenReady().then(async()=>{
 const win=new BrowserWindow({show:false,width:1540,height:1120,webPreferences:{offscreen:true,contextIsolation:true,nodeIntegration:false,backgroundThrottling:false}});
 const js=code=>win.webContents.executeJavaScript(`(async()=>{${code}})()`);
 const tick=()=>new Promise(r=>setTimeout(r,90));
 try{
  await win.loadFile(path.join(__dirname,'../src/desktop/renderer/index.html'));
  await js(`
   state.settings={activeAccountId:'synthetic',activePlatform:'qq'};
   const stamp='2026-10-25T02:00:00Z';
   const turn=(id,question,answer,status='completed')=>({id,question,answer,status,error:status==='failed'?'合成接口故障':'',created_at:stamp,source_messages:5,steps:[{name:'read_context'}],artifacts:[]});
   const first=turn('done','整理工作群最近一周的任务','已生成合成工作清单。<script>不能执行</script>');first.artifacts=[{artifact_id:'synthetic-md',filename:'工作清单.md',bytes:321}];
   window.qa={calls:[],slow:false,slowChat:false,fail:false,sessions:{a:{id:'a',title:'项目工作计划',head_id:'bad',updated_at:stamp},b:{id:'b',title:'人物表达研究',head_id:'style',updated_at:stamp}},items:{a:[first,turn('bad','继续完善','', 'failed')],b:[turn('style','比较表达方式','另一个对话独有的风格结果')]},branches:{},serial:0};
   window.qqInsight={rpc:async(method,params)=>{
    qa.calls.push({method,params});
    if(method==='workspace.chat.list'){if(qa.slow&&params.account_id==='synthetic')await new Promise(r=>setTimeout(r,110));return {items:params.account_id==='synthetic'?Object.values(qa.sessions):[],has_more:false};}
    if(method==='workspace.chat.create'){const id='c'+(++qa.serial),s={id,title:'新对话',head_id:'',updated_at:stamp};qa.sessions[id]=s;qa.items[id]=[];return s;}
    if(method==='workspace.chat.get'){
     if(qa.slowChat&&params.session_id==='a')await new Promise(r=>setTimeout(r,110));
     const s=qa.sessions[params.session_id];return {session:s,items:qa.items[s.id],has_more:false,next_offset:50,branches:qa.branches[s.id]||qa.items[s.id].slice(-1).map(t=>({id:t.id,question:t.question,created_at:stamp}))};
    }
    if(method==='workspace.chat.rename'){qa.sessions[params.session_id].title=params.title;return {renamed:true};}
    if(method==='workspace.chat.select'){qa.sessions[params.session_id].head_id=params.head_id;return {selected:true};}
    if(method==='workspace.history.delete'){for(const id in qa.items)qa.items[id]=qa.items[id].filter(t=>t.id!==params.run_id);return {deleted:true};}
    return {};
   },runWorkspaceAgent:async input=>{
    qa.calls.push({method:'run',params:input});if(qa.fail)throw new Error('合成配置未完成');const s=qa.sessions[input.session_id];
    const old=qa.items[s.id].at(-1);if(input.edit_run_id){const i=qa.items[s.id].findIndex(t=>t.id===input.edit_run_id);qa.items[s.id]=qa.items[s.id].slice(0,i);}
    const t=turn('reply'+(++qa.serial),input.question,'按本对话要求修改后的合成结果。');qa.items[s.id].push(t);s.head_id=t.id;
    if(input.edit_run_id&&old)qa.branches[s.id]=[{id:old.id,question:old.question,created_at:stamp},{id:t.id,question:t.question,created_at:stamp}];
    return {status:'completed',run_id:t.id,session_id:s.id};
   },cancelWorkspaceAgent:async()=>({cancelled:true}),workspaceArtifact:async input=>{qa.calls.push({method:'artifact',params:input});return {saved:true};}};
   showView('workspace-agent');await loadWorkspaceHistory();
  `);
  assert.equal(await js(`return workspaceUI.session;`),'a');
  assert.equal(await js(`return $('#workspace-agent-history').querySelector('script')===null;`),true);
  await js(`document.querySelector('[data-workspace-artifact][data-action="save"]').click();`);await tick();
  assert.equal(await js(`return qa.calls.some(c=>c.method==='artifact'&&c.params.action==='save');`),true);
  await js(`document.querySelector('[data-delete-workspace]').click();`);await tick();
  assert.equal(await js(`return document.querySelector('[data-delete-workspace]')===null;`),true);
  await js(`$('#workspace-agent-question').value='未发送草稿甲';await selectWorkspaceChat('b');$('#workspace-agent-question').value='未发送草稿乙';await selectWorkspaceChat('a');`);
  assert.equal(await js(`return $('#workspace-agent-question').value;`),'未发送草稿甲');
  await js(`$('#workspace-agent-question').value='把清单改成三点';$('#workspace-agent-form').requestSubmit();`);await tick();
  assert.equal(await js(`return qa.calls.filter(c=>c.method==='run').at(-1).params.session_id;`),'a');
  await js(`document.querySelector('[data-edit-workspace="done"]').click();$('#workspace-agent-question').value='修改首问：只列今天的任务';$('#workspace-agent-form').requestSubmit();`);await tick();
  assert.equal(await js(`return qa.calls.filter(c=>c.method==='run').at(-1).params.edit_run_id;`),'done');
  assert.equal(await js(`return $('#workspace-chat-branch-field').hidden;`),false);
  await js(`$('#workspace-chat-rename').click();$('#workspace-chat-name').value='周报与任务整理';$('#workspace-chat-rename-form').requestSubmit();`);await tick();
  assert.equal(await js(`return $('#workspace-chat-title').textContent;`),'周报与任务整理');
  await js(`await createWorkspaceChat();`);
  assert.equal(await js(`return $('#workspace-agent-history').textContent.includes('另一个对话独有');`),false);
  await js(`qa.fail=true;$('#workspace-agent-question').value='配置好以后再发';$('#workspace-agent-form').requestSubmit();`);await tick();
  assert.equal(await js(`return $('#workspace-agent-question').value;`),'配置好以后再发');
  assert.equal(await js(`return $('#workspace-agent-run').disabled;`),false);
  const stayed=await js(`qa.fail=false;qa.slowChat=true;const pending=selectWorkspaceChat('a');await selectWorkspaceChat('b');await pending;return {title:$('#workspace-chat-title').textContent,body:$('#workspace-agent-history').textContent};`);
  assert.equal(stayed.title,'人物表达研究');assert.match(stayed.body,/另一个对话独有/);assert.doesNotMatch(stayed.body,/修改首问/);
  const leaked=await js(`qa.slow=true;const pending=loadWorkspaceHistory();state.settings.activeAccountId='other';await loadWorkspaceHistory();await pending;return $('#workspace-agent-history').textContent;`);
  assert.doesNotMatch(leaked,/另一个对话独有|工作清单/);
  await js(`state.settings.activeAccountId='synthetic';qa.slow=false;qa.slowChat=false;resetWorkspaceChats();await loadWorkspaceHistory();await selectWorkspaceChat('a');$('#workspace-agent-question').value='再加一列截止日期，保留上一轮的任务顺序';document.getAnimations().forEach(a=>a.finish());$('#toast').className='toast';$('#toast').textContent='';$('#core-state').textContent='合成测试核心';$('#sidebar-account-list').textContent='合成测试账号';`);
  for(const width of [1200,1540]){win.setSize(width,1120);await tick();assert.equal(await js(`return document.documentElement.scrollWidth<=innerWidth;`),true);}
  await new Promise(r=>setTimeout(r,300));fs.mkdirSync(path.join(__dirname,'../build/qa'),{recursive:true});fs.writeFileSync(path.join(__dirname,'../build/qa/workspace-agent-chats.png'),(await win.webContents.capturePage()).toPNG());
  console.log('Agent chat UI passed: separate saved chats, followup/session binding, edit/regenerate branch, rename, draft preservation, failed-send preservation, files, failure deletion, account/chat races and 1200/1540 layout; synthetic only.');
 }catch(error){console.error(error);process.exitCode=1;}finally{win.destroy();app.exit(process.exitCode||0);}
});
