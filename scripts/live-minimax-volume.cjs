// Explicitly authorized live check. Input credentials stay on stdin and in memory.
const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),readline=require('node:readline');
const root=path.resolve(__dirname,'..');
const python='C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe';
async function run({profile,apiKey,resumeDirectory='',resumeJob='',styleOnly=false}){
 if(!/minimax/i.test(profile?.model||'')||!apiKey)throw new Error('MINIMAX_CONFIGURATION_REQUIRED');
 if(resumeDirectory&&!/^minimax-\d+$/.test(resumeDirectory))throw new Error('SYNTHETIC_DIRECTORY_REQUIRED');
 const dir=path.join(root,'build/live',resumeDirectory||'minimax-'+Date.now());fs.mkdirSync(dir,{recursive:true});
 if(!resumeDirectory){const seed=cp.spawnSync(python,['scripts/live-minimax-fixture.py',dir],{cwd:root,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'},encoding:'utf8'});if(seed.status!==0)throw new Error('SYNTHETIC_FIXTURE_FAILED');}
 const core=cp.spawn(python,['src/core/assistant_core.py','--data-dir',dir],{cwd:root,windowsHide:true,stdio:['pipe','pipe','ignore'],env:{...process.env,PYTHONUTF8:'1'}});
 let id=0;const pending=new Map();readline.createInterface({input:core.stdout}).on('line',line=>{try{const r=JSON.parse(line),p=pending.get(r.id);if(!p)return;pending.delete(r.id);r.error?p.reject(Object.assign(new Error(r.error.message||'CORE_FAILURE'),{code:r.error.code})):p.resolve(r.result);}catch{}});
 const rpc=(method,params={})=>new Promise((resolve,reject)=>{const key=++id;pending.set(key,{resolve,reject});core.stdin.write(JSON.stringify({jsonrpc:'2.0',id:key,method,params})+'\n');});
 const {generate}=require('../src/desktop/main/model-gateway'),{createAICoordinator}=require('../src/desktop/main/ai-coordinator');
 let calls=0,lastJob='',charged=0;const stages=[];const scope={account_id:'volume',conversation_id:'volume-main'};
 const coordinator=createAICoordinator({rpc,settings:()=>({data:{activeModelProfileId:profile.id,modelProfiles:[profile]},getModelApiKey:()=>apiKey}),progress:p=>{if(p.job_id)lastJob=p.job_id;},generateImpl:async input=>{
  if(calls>=24||charged+Buffer.byteLength(input.request.system+input.request.user)+input.request.max_tokens>500000)throw Object.assign(new Error('LIVE_TEST_LIMIT'),{code:'LIVE_TEST_LIMIT',knownNotSent:true});
  calls++;const result=await generate({...input,timeoutMs:180000});fs.writeFileSync(path.join(dir,'synthetic-response-'+Date.now()+'.json'),result.result);charged+=(result.usage.input_tokens||0)+(result.usage.output_tokens||0);console.log(JSON.stringify({stage:'call',number:calls,input_tokens:result.usage.input_tokens,output_tokens:result.usage.output_tokens}));return result;
 }});
 try{
  await rpc('ai.budget.save',{settings:{per_run_tokens:500000,daily_tokens:1000000,monthly_tokens:2000000,output_tokens:8192,monthly_cost:0}});
  for(const [feature,limit,extra] of [['summary',3000,{}],['style',3000,{person_id:'100001',cross_group:true}]].filter(([feature])=>!styleOnly||feature==='style')){
   const start=Date.now();let status='failed',code='';lastJob='';
   try{const result=await coordinator.run({...scope,feature,...(resumeJob&&feature==='style'?{job_id:resumeJob}:{}),options:{mode:'recent',limit,compression:'off',hierarchical:false,output_chars:800,...extra}});lastJob=result.job_id;status=result.status;}catch(e){code=e.code||'MODEL_REQUEST_FAILED';console.log(JSON.stringify({stage:'failure',code,message:code.startsWith('AI_')?e.message:'模型请求未完成'}));}
   const history=await rpc('ai.history',{...scope,feature,job_id:lastJob});const job=history.jobs.find(j=>j.id===lastJob);const c=job?.coverage||{};
   const memory=await rpc('ai.memory.list',scope);
   const outcome={feature,status,code,requested_limit:limit,selected:c.selected||0,completed_messages:c.completed_messages||0,failed_chunk_messages:c.failed_chunk_messages||0,failed_stage:c.failed_stage||'',source_groups:c.source_groups||1,has_more:!!c.has_more,chunks:c.chunks||0,seconds:(Date.now()-start)/1000,usage:job?.usage,call_count:job?.calls?.length,invalid_output_calls:job?.calls?.filter(call=>call.state==='invalid_output').length,people_remembered:new Set(memory.items.filter(m=>m.kind==='person').map(m=>m.subject)).size,prompt_created:feature==='style'?!!history.report?.items.some(item=>item.drafts?.length):undefined};
   outcome.ok=status==='completed'&&outcome.completed_messages===outcome.selected&&(feature!=='summary'||outcome.selected===3000)&&(feature!=='style'||outcome.prompt_created);
   stages.push(outcome);console.log(JSON.stringify({stage:'result',...outcome}));if(!outcome.ok)break;
  }
  fs.mkdirSync(path.join(root,'build/qa'),{recursive:true});fs.writeFileSync(path.join(root,'build/qa/live-minimax-3000.json'),JSON.stringify({at:new Date().toISOString(),model:profile.model,source:'synthetic',calls,stages,scope_note:'3000条主群消息，另600条用于跨群同人验证；不读取真实QQ聊天。'},null,2));
 }finally{core.stdin.end();setTimeout(()=>core.kill(),1000).unref();}
}
let input='';process.stdin.setEncoding('utf8');process.stdin.on('data',chunk=>input+=chunk);process.stdin.on('end',()=>{let config;try{config=JSON.parse(input);}catch{console.log('MINIMAX_CONFIGURATION_REQUIRED');process.exitCode=1;return;}input='';run(config).catch(()=>{console.log('LIVE_CHECK_FAILED');process.exitCode=1;});});
