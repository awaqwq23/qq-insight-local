const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os'),cp=require('node:child_process'),readline=require('node:readline');
const {createWorkspaceAgent,registerWorkspaceAgent}=require('../src/desktop/main/workspace-agent');
const python='C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe';
function compressionResponse(input){
 if(!input.request.system.startsWith('先整理聊天记录'))return;
 const p=JSON.parse(input.request.user),groups=new Map();
 for(const row of p.messages){const alias=row[5]?.group,group=p.groups?.[alias]||alias;if(!groups.has(group))groups.set(group,row[0]);}
 return {result:JSON.stringify({summary:'合成压缩上下文，保留会话与发言者来源。',items:[...groups.values()].map(ref=>({title:'合成主题',body:'提交安排和确认，细节需回查原文。',evidence_ids:[ref]})),group_memory:[...groups].map(([cid,ref])=>({conversation_id:cid,body:'合成任务安排与交流。',evaluation:'合成样本有限。',evidence_ids:[ref]}))}),usage:{input_tokens:30,output_tokens:20}};
}
async function main(){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'workspace-agent-'));const seeded=cp.spawnSync(python,['tests/workspace-fixture.py',dir,'--autonomy'],{encoding:'utf8',windowsHide:true});assert.equal(seeded.status,0,seeded.stderr);
 const core=cp.spawn(python,['src/core/assistant_core.py','--data-dir',dir],{windowsHide:true,stdio:['pipe','pipe','ignore'],env:{...process.env,PYTHONUTF8:'1'}});
 let id=0;const pending=new Map();readline.createInterface({input:core.stdout}).on('line',line=>{const r=JSON.parse(line),p=pending.get(r.id);if(!p)return;pending.delete(r.id);r.error?p.reject(Object.assign(new Error(r.error.message),{code:r.error.code})):p.resolve(r.result);});
 const rpc=(method,params={})=>new Promise((resolve,reject)=>{const key=++id;pending.set(key,{resolve,reject});core.stdin.write(JSON.stringify({id:key,jsonrpc:'2.0',method,params})+'\n');});
 const profile={id:'synthetic',model:'synthetic',provider:'openai-compatible',baseUrl:'https://example.test/v1',limits:{context_tokens:262144,output_tokens:2048,basis:'manual'}};
 const store={data:{activeAccountId:'synthetic',activeModelProfileId:profile.id,modelProfiles:[profile],mediaProfiles:{vision:profile}},getModelApiKey:()=> 'synthetic-key',getMediaApiKey:()=> 'synthetic-key'};
 let pixelCalls=0;const requests=[];
 const generateImpl=async input=>{
  const compressed=compressionResponse(input);if(compressed)return compressed;
  if(input.request.images?.length){assert.match(input.request.images[0].data_url,/^data:image\/png;base64,/);pixelCalls++;return {result:'可见粉色背景、白色长耳兔子和圆眼睛，有可爱的卡通元素。',usage:{input_tokens:40,output_tokens:20}};}
  const p=JSON.parse(input.request.user);requests.push(p);const steps=p.steps;let action;
  const read=steps.find(s=>s.tool==='read_context'),ref=read?.result.messages?.[0]?.[0];const tool=(name,arguments)=>({action:'tool',name,arguments});
  if(p.question==='排序')action=steps.length?{action:'finish',answer:'已导出5行人名，同秒按本地ID排序。',evidence_ids:[]}:tool('export_order',{conversation_ids:['work'],start:p.time_boundaries.today_start,end:p.time_boundaries.now,title:'发言顺序'});
  else if(p.question==='表情'){
   const images=steps.find(s=>s.tool==='images'),reference=images?.result.items[0].reference;
   action=!images?tool('images',{conversation_ids:['stickers']}):!steps.some(s=>s.tool==='inspect_image')?tool('inspect_image',{reference,media_index:0}):!steps.some(s=>s.tool==='save_image')?tool('save_image',{reference,media_index:0,title:'合成兔子'}):{action:'finish',answer:'已根据实际像素保存合成兔子图片。',evidence_ids:[reference]};
  }else if(p.question==='越界')action=steps.length?{action:'finish',answer:'当前账号不能读取其他账号。',evidence_ids:[]}:tool('read_context',{conversation_ids:['foreign']});
  else if(!read)action=tool('read_context',{conversation_ids:p.question.startsWith('风格')?['work','fun','private-lin']:['work'],...(p.question.startsWith('风格')?{sender:'100001'}:{}),prefer_cache:false});
  else if(p.question==='工作'&&!steps.some(s=>s.tool==='write_markdown'))action=tool('write_markdown',{title:'工作任务',content:'# 任务\n\n核对测试报告的截止安排。',evidence_ids:[ref]});
  else action={action:'finish',answer:'合成分析完成，保留场景差异与待核实事项。',evidence_ids:[ref],...(!p.question.startsWith('风格')?{group_memory:[{conversation_id:'work',body:'围绕提交安排交流。',evaluation:'本段偏任务协调。',evidence_ids:[ref]}]}:{people_memory:[{subject:'100001',title:'表达差异',body:'群中较直接，私聊较柔和；样本不足以判断人格。',uncertainty:'合成样本',evidence_ids:[ref]}]})};
  return {result:JSON.stringify(action),usage:{input_tokens:30,output_tokens:20}};
 };
 const controller=createWorkspaceAgent({rpc,settings:()=>store,generateImpl});
 try{
  await rpc('ai.budget.save',{settings:{output_tokens:2048}});
  let compressionCalls=0;
  const cachedReader=createWorkspaceAgent({rpc,settings:()=>store,generateImpl:async input=>{
   const compressed=compressionResponse(input);if(compressed){compressionCalls++;return compressed;}
   const p=JSON.parse(input.request.user),read=p.steps.find(s=>s.tool==='read_context');
   if(!read)return {result:JSON.stringify({action:'tool',name:'read_context',arguments:{conversation_ids:['long']}}),usage:{input_tokens:20,output_tokens:10}};
   assert.equal(read.result.messages.length,0,'task model receives prepared summaries, not uncovered originals');
   assert.ok(read.result.summaries.length);
   return {result:JSON.stringify({action:'finish',answer:'基于压缩上下文回答。',evidence_ids:[read.result.summaries[0].evidence_ids[0]]}),usage:{input_tokens:20,output_tokens:10}};
  }});
  await cachedReader.run({account_id:'synthetic',question:'先总结聊天'});assert.equal(compressionCalls,1);
  await cachedReader.run({account_id:'synthetic',question:'改为分析画像与风格'});assert.equal(compressionCalls,1,'new preset reuses the neutral context');
  for(const question of ['工作','排序','风格（群聊和私聊）','今日重点','人物事件','表情','越界']){
   const result=await controller.run({account_id:'synthetic',question});assert.equal(result.status,'completed');if(['工作','排序','表情'].includes(question))assert.equal(result.artifacts.length,1);
  }
  assert.equal(pixelCalls,1);assert.ok(requests.some(r=>r.steps.some(s=>s.tool==='read_context'&&JSON.stringify(s.result).includes('慢慢来'))));
  const history=await rpc('workspace.history',{account_id:'synthetic'});assert.equal(history.items.length,9);assert.ok(history.items.some(r=>r.steps.some(s=>s.error)));
  let qaCalls=0;
  const qaQuestion='给我提取今天我请别人提问后，私聊中对方的问题和我的回答，原封不动做成md文件';
  const qaController=createWorkspaceAgent({rpc,settings:()=>store,generateImpl:async input=>{
   assert.ok(!input.request.system.startsWith('先整理聊天记录'),'short conversations must not invoke the compression model');
   qaCalls++;const p=JSON.parse(input.request.user),read=p.steps.find(s=>s.tool==='search_messages'),exported=p.steps.find(s=>s.tool==='export_messages');
   assert.equal(p.task.request,qaQuestion);assert.equal(p.source_scope.conversations,4);assert.equal(read.result.messages.length,11);
   assert.equal(read.result.short_context,true);assert.equal(read.result.summaries.length,0);
   let action;
   if(!p.steps.some(s=>s.incomplete_task))action={action:'finish',answer:'只核对一人，是否继续所有私聊？',evidence_ids:[read.result.messages[0][0]]};
   else if(!exported)action={action:'tool',name:'export_messages',arguments:{title:'合成私聊问答原文',sections:['qa-a','qa-b'].map(cid=>({heading:'合成问答 '+cid,references:read.result.messages.filter(row=>read.result.groups[row[5].group]===cid).map(row=>row[0]).reverse()}))}};
   else action={action:'finish',answer:'已提取两位合成对象的问题及全部回答，生成原文MD。',evidence_ids:[read.result.messages[0][0]]};
   return {result:JSON.stringify(action),usage:{input_tokens:30,output_tokens:20}};
  }});
  const qa=await qaController.run({account_id:'synthetic',question:qaQuestion});assert.equal(qa.status,'completed');assert.equal(qa.artifacts.length,1);
  const qaFile=await rpc('workspace.artifact',{account_id:'synthetic',artifact_id:qa.artifacts[0].artifact_id});const qaText=fs.readFileSync(qaFile.path,'utf8');
  assert.match(qaText,/答：合成故事集。\n保留空格  🙂\n```原文```/);assert.equal((qaText.match(/补充回答分开发送。/g)||[]).length,2);assert.doesNotMatch(qaText,/无关的合成问候|慢慢来/);
  await qaController.run({account_id:'synthetic',session_id:qa.session_id,question:'继续'});
  await qaController.run({account_id:'synthetic',session_id:qa.session_id,question:'今天所有的'});assert.equal(qaCalls,9);
  const usage=await rpc('ai.usage.list',{account_id:'synthetic',limit:200});assert.ok(usage.items.every(u=>u.feature==='workspace'));assert.ok(usage.items.some(u=>u.kind==='vision'));
  assert.equal((await rpc('workspace.history',{account_id:'other'})).items.length,0);
  const scoped=await rpc('workspace.chat.create',{account_id:'synthetic',conversation_id:'work'});
  const upload=async(filename,mime,data)=>rpc('workspace.attachment.add',{account_id:'synthetic',session_id:scoped.id,filename,mime,data_base64:data.toString('base64')});
  const attached=[await upload('合成图片.png','image/png',fs.readFileSync(path.join(__dirname,'../src/desktop/main/test-assets/vision.png'))),await upload('合成语音.wav','audio/wav',fs.readFileSync(path.join(__dirname,'../src/desktop/main/test-assets/speech.wav'))),await upload('合成文本.md','text/markdown',Buffer.from('🙂附件分页测试。'.repeat(1200)))];
  store.data.mediaProfiles.speech={...profile,protocol:'whisper'};
  let attachedVision=0,attachedSpeech=0;
  const multimodal=createWorkspaceAgent({rpc,settings:()=>store,transcribeImpl:async input=>{assert.ok(input.data.length>44);attachedSpeech++;return {result:'合成语音：七四二。',usage:{input_tokens:30,output_tokens:10,seconds:1}};},generateImpl:async input=>{
   if(input.request.images?.length){attachedVision++;assert.match(input.request.images[0].data_url,/^data:image\/png;base64,/);return {result:'合成蓝色像素图片。',usage:{input_tokens:30,output_tokens:10}};}
   const p=JSON.parse(input.request.user);assert.equal(p.conversation_id,'work');
   const observed=p.steps.filter(s=>s.tool==='inspect_attachment').map(s=>s.result),text=observed.filter(s=>s.filename==='合成文本.md').at(-1);
   assert.ok(observed.some(s=>s.description.includes('七四二')));assert.ok(observed.some(s=>s.description.includes('蓝色像素')));
   const action=text.has_more?{action:'tool',name:'inspect_attachment',arguments:{attachment_id:attached[2].id,offset:text.next_offset}}:{action:'finish',answer:'已读合成图片、语音和完整文本附件；这些不是QQ消息证据。',evidence_ids:[]};
   return {result:JSON.stringify(action),usage:{input_tokens:30,output_tokens:10}};
  }});
  const multimodalResult=await multimodal.run({account_id:'synthetic',session_id:scoped.id,conversation_id:'work',question:'读取这些用户附件',attachment_ids:attached.map(f=>f.id)});
  assert.equal(multimodalResult.status,'completed');assert.equal(attachedVision,1);assert.equal(attachedSpeech,1);
  const multimodalHistory=await rpc('workspace.chat.get',{account_id:'synthetic',session_id:scoped.id});assert.equal(multimodalHistory.items[0].attachments.length,3);assert.equal(multimodalHistory.items[0].source_messages,0);
  const mixedUsage=await rpc('ai.usage.list',{account_id:'synthetic',job_id:multimodalResult.run_id});assert.ok(mixedUsage.items.some(c=>c.kind==='speech'));assert.ok(mixedUsage.items.some(c=>c.kind==='vision'));
  const direct=createWorkspaceAgent({rpc,settings:()=>store,generateImpl:async input=>{const p=JSON.parse(input.request.user);assert.equal(p.conversation_id,'private-lin');assert.deepEqual(p.allowed_kinds,['c2c']);return {result:JSON.stringify({action:'finish',answer:'可以先直接聊天。',evidence_ids:[]}),usage:{input_tokens:20,output_tokens:10}};}});
  const privateChat=await rpc('workspace.chat.create',{account_id:'synthetic',conversation_id:'private-lin'});
  assert.equal((await direct.run({account_id:'synthetic',session_id:privateChat.id,conversation_id:'private-lin',question:'你好'})).status,'completed');
  let imageSteps=0;
  const patientImages=createWorkspaceAgent({rpc,settings:()=>store,generateImpl:async input=>{
   if(input.request.images?.length)return {result:'可见合成可爱图案。',usage:{input_tokens:10,output_tokens:5}};
   const p=JSON.parse(input.request.user);imageSteps++;const first=p.steps.find(s=>s.tool==='images'),ref=first?.result.items[0].reference;
   const action=imageSteps<=34?{action:'tool',name:'images',arguments:{conversation_ids:['stickers']}}:imageSteps===35?{action:'tool',name:'inspect_image',arguments:{reference:ref,media_index:0}}:imageSteps===36?{action:'tool',name:'save_image',arguments:{reference:ref,media_index:0,title:'合成'}}:{action:'finish',answer:'已保存一张合成图片。',evidence_ids:[ref]};
   return {result:JSON.stringify(action),usage:{input_tokens:20,output_tokens:10}};
  }});
  assert.equal((await patientImages.run({account_id:'synthetic',question:'找1个可爱表情包并保存'})).status,'completed');
  assert.equal(imageSteps,37,'image selection can continue beyond the ordinary 32-step limit');
  let portraitCalls=0;
  const portraits=createWorkspaceAgent({rpc,settings:()=>store,generateImpl:async input=>{
   const p=JSON.parse(input.request.user);portraitCalls++;
   if(p.feature==='profile')return {result:JSON.stringify({summary:'阶段画像',items:p.messages.map(row=>({title:'成员阶段画像',body:'语气：先核对；兴趣与性格倾向：待补充。',uncertainty:'少量合成样本，暂定。',subject:p.people[row[3]].qq,evidence_ids:[row[0]]}))}),usage:{input_tokens:20,output_tokens:20}};
   const done=p.steps.find(s=>s.tool==='analyze_members');
   return {result:JSON.stringify(done?{action:'finish',answer:'已保存此成员的阶段画像，未知部分后续补充。',evidence_ids:done.result.evidence_ids}:{action:'tool',name:'analyze_members',arguments:{conversation_id:'work',person_id:'100001',limit:100}}),usage:{input_tokens:20,output_tokens:10}};
  }});
  assert.equal((await portraits.run({account_id:'synthetic',conversation_id:'work',question:'分析本群成员100001的说话语气和暂定画像，先保存已有部分'})).status,'completed');
  assert.equal(portraitCalls,3,'native portrait analysis needs no contact-by-contact planning');
  let automaticDecisions=0;
  const automaticImage=createWorkspaceAgent({rpc,settings:()=>store,generateImpl:async input=>{
   if(input.request.images?.length)return {result:JSON.stringify({description:'可见合成可爱卡通，符合筛选条件。',suitable:true}),usage:{input_tokens:10,output_tokens:10}};
   automaticDecisions++;const p=JSON.parse(input.request.user),found=p.steps.find(s=>s.tool==='images');
   return {result:JSON.stringify(found?{action:'tool',name:'inspect_image',arguments:{reference:found.result.items[0].reference,media_index:0}}:{action:'tool',name:'images',arguments:{conversation_ids:['stickers']}}),usage:{input_tokens:20,output_tokens:10}};
  }});
  const automaticSaved=await automaticImage.run({account_id:'synthetic',question:'找1张可爱表情包并保存'});
  assert.equal(automaticSaved.status,'completed');assert.equal(automaticSaved.artifacts.length,1);assert.equal(automaticDecisions,2,'a suitable inspected image is saved immediately and the completed goal stops paid planning');
  const handlers=new Map(),chosen=path.join(dir,'native-selected.png');fs.copyFileSync(path.join(__dirname,'../src/desktop/main/test-assets/vision.png'),chosen);
  const nativeDialog={showOpenDialog:async()=>({canceled:false,filePaths:[chosen]})};
  registerWorkspaceAgent({ipcMain:{handle:(name,handler)=>handlers.set(name,handler)},rpc,settings:()=>store,window:()=>null,ipcSafe:handler=>handler,busy:()=>false,dialog:nativeDialog,shell:{}});
  const picked=await handlers.get('workspace:attachments.pick')(null,{account_id:'synthetic',session_id:scoped.id,path:'arbitrary-path-ignored'});
  assert.equal(picked.items[0].filename,'native-selected.png');assert.equal(picked.items[0].mime,'image/png');assert.ok(!JSON.stringify(picked).includes(dir));
  await assert.rejects(handlers.get('workspace:attachments.pick')(null,{account_id:'other',session_id:scoped.id}),/当前QQ/);
  nativeDialog.showOpenDialog=async()=>({canceled:false,filePaths:Array(5).fill(chosen)});await assert.rejects(handlers.get('workspace:attachments.pick')(null,{account_id:'synthetic',session_id:scoped.id}),/最多选择4/);
  nativeDialog.showOpenDialog=async()=>{store.data.activeAccountId='other';return {canceled:false,filePaths:[chosen]};};await assert.rejects(handlers.get('workspace:attachments.pick')(null,{account_id:'synthetic',session_id:scoped.id}),/账号已切换/);store.data.activeAccountId='synthetic';
  const dialog=createWorkspaceAgent({rpc,settings:()=>store,generateImpl:async input=>{
   const p=JSON.parse(input.request.user);
   if(p.question==='连续追问')assert.deepEqual(p.previous_turns.map(t=>t.answer),['本对话合成标记']);
   if(p.question==='修改首问'||p.question==='另起一题')assert.deepEqual(p.previous_turns,[]);
   return {result:JSON.stringify({action:'finish',answer:p.question==='首问'?'本对话合成标记':'完成对话回复',evidence_ids:[]}),usage:{input_tokens:20,output_tokens:10}};
  }});
  const first=await dialog.run({account_id:'synthetic',question:'首问'});
  assert.ok(first.session_id);
  await dialog.run({account_id:'synthetic',session_id:first.session_id,question:'连续追问'});
  await dialog.run({account_id:'synthetic',session_id:first.session_id,edit_run_id:first.run_id,question:'修改首问'});
  assert.equal((await rpc('workspace.chat.get',{account_id:'synthetic',session_id:first.session_id})).branches.length,2);
  await dialog.run({account_id:'synthetic',question:'另起一题'});
  await assert.rejects(controller.run({account_id:'other',question:'工作'}),/当前账号/);
  let repairStep=0;
  const repair=createWorkspaceAgent({rpc,settings:()=>store,generateImpl:async input=>{
   const compressed=compressionResponse(input);if(compressed)return compressed;
   const p=JSON.parse(input.request.user),read=p.steps.find(s=>s.tool==='read_context'),ref=read?.result.messages?.[0]?.[0];let value;
   if(repairStep++===0)return {result:'invalid-json',usage:{input_tokens:20,output_tokens:10}};
   if(!read)value={action:'tool',name:'read_context',arguments:{conversation_ids:['work'],prefer_cache:false}};
   else if(!p.steps.some(s=>s.rejected_finish))value={action:'finish',answer:'有效回答保留，错误人物观察跳过',evidence_ids:[ref],people_memory:[{subject:'999999',title:'错误标识',body:'不能接受',evidence_ids:[ref]}]};
   else value={action:'finish',answer:'修订后只保留有来源的群结论。',evidence_ids:[ref]};
   return {result:JSON.stringify(value),usage:{input_tokens:20,output_tokens:10}};
  }});
  const repaired=await repair.run({account_id:'synthetic',question:'结果修订测试'});assert.equal(repaired.status,'completed');assert.equal((await rpc('ai.usage.list',{job_id:repaired.run_id,account_id:'synthetic'})).items.filter(c=>c.state==='invalid_output').length,1);
  assert.ok((await rpc('workspace.history',{account_id:'synthetic'})).items.find(r=>r.id===repaired.run_id).steps.some(s=>s.name==='memory_validation'));
  let emptyStep=0;
  const empty=createWorkspaceAgent({rpc,settings:()=>store,generateImpl:async()=>{if(emptyStep++===0)throw Object.assign(new Error('empty'),{code:'MODEL_EMPTY',usage:{input_tokens:10,output_tokens:0}});return {result:JSON.stringify({action:'finish',answer:'请补充群名。',evidence_ids:[]}),usage:{input_tokens:20,output_tokens:10}};}});
  const recovered=await empty.run({account_id:'synthetic',question:'空返回重试'});assert.equal(recovered.status,'completed');assert.equal((await rpc('ai.usage.list',{job_id:recovered.run_id,account_id:'synthetic'})).items.length,2);
  const repeat=createWorkspaceAgent({rpc,settings:()=>store,generateImpl:async()=>({result:JSON.stringify({action:'tool',name:'read_context',arguments:{conversation_ids:['foreign']}}),usage:{input_tokens:20,output_tokens:10}})});
  await assert.rejects(repeat.run({account_id:'synthetic',question:'重复错误停止'}),/连续失败/);
  const slow=createWorkspaceAgent({rpc,settings:()=>store,generateImpl:input=>new Promise((resolve,reject)=>{const stop=()=>reject(Object.assign(new Error('cancelled'),{knownNotSent:true}));if(input.signal.aborted)stop();else input.signal.addEventListener('abort',stop,{once:true});})});
  const started=slow.run({account_id:'synthetic',question:'取消测试'});while(!slow.status().run_id)await new Promise(r=>setTimeout(r,10));await new Promise(r=>setTimeout(r,40));slow.cancel();await assert.rejects(started,/cancelled/);assert.equal(slow.status().running,false);
  await rpc('ai.budget.save',{settings:{output_tokens:65536,per_run_tokens:1000000,daily_tokens:1000000}});
  const liveOutputs=[];
  const liveOutput=createWorkspaceAgent({rpc,settings:()=>store,generateImpl:async input=>{
   liveOutputs.push(input.request.max_tokens);
   if(liveOutputs.length===1){await rpc('ai.budget.save',{settings:{output_tokens:131072}});return {result:JSON.stringify({action:'tool',name:'conversations',arguments:{}}),usage:{input_tokens:20,output_tokens:10}};}
   return {result:JSON.stringify({action:'finish',answer:'这是合成软件说明。',evidence_ids:[]}),usage:{input_tokens:20,output_tokens:10}};
  }});
  assert.equal((await liveOutput.run({account_id:'synthetic',question:'介绍软件功能'})).status,'completed');
  assert.deepEqual(liveOutputs,[65536,131072],'next Agent request follows the saved output, not the initial profile snapshot');
  profile.limits.output_tokens=131072;
  const fitsLargeOutput=createWorkspaceAgent({rpc,settings:()=>store,generateImpl:async input=>{
   assert.equal(input.request.max_tokens,131072);
   return {result:JSON.stringify({action:'finish',answer:'合成大输出容量检查通过。',evidence_ids:[]}),usage:{input_tokens:20,output_tokens:10}};
  }});
  assert.equal((await fitsLargeOutput.run({account_id:'synthetic',question:'说明本地软件功能'})).status,'completed','output reservation is not counted twice against the input limit');
  console.log('Workspace agent passed: real core tools for Markdown, ordered XLSX, group+private style, group memory, event summary, pixel inspection/favorite, account boundary, ledger, errors and cancellation; synthetic model only.');
 }finally{core.stdin.end();await new Promise(resolve=>core.on('exit',resolve));assert.ok(path.resolve(dir).startsWith(path.resolve(os.tmpdir())+path.sep));fs.rmSync(dir,{recursive:true,force:true});}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
