// Explicitly opted-in real-model acceptance. Synthetic records; credentials on stdin only.
const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),readline=require('node:readline');
const {createWorkspaceAgent}=require('../src/desktop/main/workspace-agent');
const python='C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe';
async function run({profile,apiKey,resumeDirectory='',startCase=0}){
 if(!/minimax/i.test(profile?.model||'')||!apiKey)throw new Error('CONFIG_REQUIRED');
 if(resumeDirectory&&!/^workspace-\d+$/.test(resumeDirectory)||!Number.isInteger(startCase)||startCase<0||startCase>6)throw new Error('SYNTHETIC_SCOPE_REQUIRED');
 const root=path.resolve(__dirname,'..'),dir=path.join(root,'build/live',resumeDirectory||'workspace-'+Date.now());fs.mkdirSync(dir,{recursive:true});
 if(!resumeDirectory){const seed=cp.spawnSync(python,['tests/workspace-fixture.py',dir],{cwd:root,windowsHide:true,encoding:'utf8'});if(seed.status!==0)throw new Error('FIXTURE_FAILED');}
 const core=cp.spawn(python,['src/core/assistant_core.py','--data-dir',dir],{cwd:root,windowsHide:true,stdio:['pipe','pipe','ignore'],env:{...process.env,PYTHONUTF8:'1'}});
 let next=0;const pending=new Map();readline.createInterface({input:core.stdout}).on('line',line=>{const r=JSON.parse(line),p=pending.get(r.id);if(!p)return;pending.delete(r.id);r.error?p.reject(Object.assign(new Error(r.error.message),{code:r.error.code})):p.resolve(r.result);});
 const rpc=(method,params={})=>new Promise((resolve,reject)=>{const id=++next;pending.set(id,{resolve,reject});core.stdin.write(JSON.stringify({id,jsonrpc:'2.0',method,params})+'\n');});
 const store={data:{activeAccountId:'synthetic',activeModelProfileId:profile.id,modelProfiles:[profile],mediaProfiles:{vision:profile}},getModelApiKey:()=>apiKey,getMediaApiKey:()=>apiKey};
 let calls=0,pixelCalls=0,charged=0;const {generate}=require('../src/desktop/main/model-gateway');
 const controller=createWorkspaceAgent({rpc,settings:()=>store,generateImpl:async input=>{
  if(calls>=90||charged+Buffer.byteLength(input.request.system+input.request.user)+input.request.max_tokens>1000000)throw Object.assign(new Error('LIVE_TEST_LIMIT'),{code:'LIVE_TEST_LIMIT',knownNotSent:true});
  calls++;if(input.request.images?.length)pixelCalls++;
  const result=await generate({...input,timeoutMs:180000});fs.appendFileSync(path.join(dir,'synthetic-actions.jsonl'),JSON.stringify({image:!!input.request.images?.length,result:result.result})+'\n');charged+=(result.usage.input_tokens||0)+(result.usage.output_tokens||0);
  console.log(JSON.stringify({stage:'call',number:calls,image:!!input.request.images?.length,input_tokens:result.usage.input_tokens,output_tokens:result.usage.output_tokens}));return result;
 }});
 const cases=[
  ['today','帮我看一下合成工作项目群今天的消息，总结他们聊了什么，对我作为资料整理人重点关注哪些。'],
  ['markdown','帮我看一下最近一周工作群我有什么任务，做成md文件。'],
  ['excel','帮我统计合成工作项目群今天零点到现在的发言先后顺序，只要人名的Excel文档。'],
  ['style','帮我总结合成小林这个人在所有群聊和我私聊的说话方式，比较场景差异，不做确定性格诊断。'],
  ['events','统计合成小林在群聊里说的话、做的事情，区分已经完成、计划和不确定。'],
  ['stickers','帮我存一个合成表情分享群中可爱的表情包，先实际看图判断。'],
  ['cached','再总结一下合成工作项目群今天的重点，优先使用已经分析过的压缩上下文。'],
 ];
 core.on('exit',()=>{for(const p of pending.values())p.reject(new Error('CORE_EXIT'));pending.clear();});
 const previous=startCase?JSON.parse(fs.readFileSync(path.join(root,'build/qa/live-workspace-agent.json'),'utf8')):null;
 const outcomes=previous?previous.outcomes.filter(r=>r.ok&&cases.slice(0,startCase).some(([name])=>name===r.case)):[];
 try{
  await rpc('ai.budget.save',{settings:{per_run_tokens:500000,daily_tokens:2000000,monthly_tokens:3000000,output_tokens:8192,monthly_cost:0}});
  for(const [name,question] of cases.slice(startCase)){
   let result,error='',code='';const started=Date.now(),beforePixels=pixelCalls;
   try{result=await controller.run({account_id:'synthetic',question});}catch(e){error=e.message;code=e.code||'FAILED';}
   const h=(await rpc('workspace.history',{account_id:'synthetic'})).items[0];
   const usage=await rpc('ai.usage.list',{job_id:h.id,account_id:'synthetic',limit:200});
   const artifactMimes=h.artifacts.map(f=>f.mime);let ok=result?.status==='completed'&&!!h.answer;
   const checked=cp.spawnSync(python,['tests/verify-workspace-live.py',dir,h.id],{cwd:root,encoding:'utf8',windowsHide:true});
   if(checked.status!==0)throw new Error('COVERAGE_CHECK_FAILED');const coverage=JSON.parse(checked.stdout);
   if(name==='markdown')ok=ok&&artifactMimes.includes('text/markdown');
   if(name==='excel')ok=ok&&artifactMimes.includes('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')&&JSON.stringify(coverage.excel_names)===JSON.stringify(['人名','合成我','合成小林','合成小周','合成小林','合成小周']);
   if(name==='style')ok=ok&&h.source_messages>=5&&coverage.source_kinds.includes('c2c')&&coverage.source_kinds.includes('group');
   if(name==='events')ok=ok&&!coverage.source_kinds.includes('c2c')&&coverage.source_groups.includes('work')&&coverage.source_groups.includes('fun');
   if(name==='today'||name==='cached')ok=ok&&coverage.source_groups.length===1&&coverage.source_groups[0]==='work'&&!coverage.source_ids.includes('syn-yesterday');
   if(name==='cached')ok=ok&&coverage.reused_messages>0;
   if(name==='stickers')ok=ok&&pixelCalls>beforePixels&&artifactMimes.some(m=>m.startsWith('image/'));
   const entry={case:name,ok,status:h.status,code,error,seconds:(Date.now()-started)/1000,tools:h.steps.map(s=>({name:s.name,error:s.error})),source_messages:h.source_messages,coverage,artifacts:artifactMimes,input_tokens:usage.items.reduce((n,u)=>n+(u.input_tokens||0),0),output_tokens:usage.items.reduce((n,u)=>n+(u.output_tokens||0),0),cost_estimate:usage.items.reduce((n,u)=>n+(u.cost||0),0),calls:usage.items.length};
   outcomes.push(entry);console.log(JSON.stringify({stage:'result',...entry}));
   fs.writeFileSync(path.join(dir,name+'-synthetic-answer.json'),JSON.stringify({answer:h.answer,steps:h.steps,artifacts:h.artifacts},null,2));
   if(!ok)break;
  }
  fs.mkdirSync(path.join(root,'build/qa'),{recursive:true});fs.writeFileSync(path.join(root,'build/qa/live-workspace-agent.json'),JSON.stringify({at:new Date().toISOString(),model:profile.model,source:'synthetic',calls,pixel_calls:pixelCalls,charged_tokens:outcomes.reduce((n,o)=>n+o.input_tokens+o.output_tokens,0),outcomes},null,2));
 }finally{core.stdin.end();setTimeout(()=>core.kill(),1000).unref();}
}
let input='';process.stdin.setEncoding('utf8');process.stdin.on('data',chunk=>input+=chunk);process.stdin.on('end',()=>{let value;try{value=JSON.parse(input);}catch{console.log('CONFIG_REQUIRED');process.exitCode=1;return;}input='';run(value).catch(()=>{console.log('LIVE_WORKSPACE_CHECK_FAILED');process.exitCode=1;});});
