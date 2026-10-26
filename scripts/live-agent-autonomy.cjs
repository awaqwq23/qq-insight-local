// Explicit --run only; synthetic records and aggregate evidence. Never logs credentials or real QQ content.
const fs=require('node:fs'),path=require('node:path'),cp=require('node:child_process'),readline=require('node:readline');
const {createWorkspaceAgent}=require('../src/desktop/main/workspace-agent');
const {generate}=require('../src/desktop/main/model-gateway');
async function main(configuration){
 if(!process.argv.includes('--run'))throw Object.assign(new Error(),{code:'EXPLICIT_RUN_REQUIRED'});
 const root=path.resolve(__dirname,'..'),settings=configuration?null:JSON.parse(fs.readFileSync(path.join(process.env.APPDATA,'qq-insight-local/settings.json'),'utf8'));
 const saved=configuration?.profile||settings.modelProfiles.find(p=>/minimax/i.test(p.model)&&/^https:\/\/api\.(?:minimaxi\.com|minimax\.cn|minimax\.io)(?:\/|$)/i.test(p.baseUrl));
 const apiKey=configuration?.apiKey||fs.readFileSync(path.join(root,'.env.local'),'utf8').match(/sk-cp-[A-Za-z0-9_-]+/)?.[0];
 if(!saved||!apiKey)throw Object.assign(new Error(),{code:'MINIMAX_CONFIGURATION_UNAVAILABLE'});
 const profile={...saved,apiKeyEncrypted:undefined,limits:{...saved.limits,output_tokens:4096}};
 const directory=path.join(root,'build/live','autonomy-'+Date.now());fs.mkdirSync(directory,{recursive:true});
 const python='C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe';
 const fixture=cp.spawnSync(python,['tests/agent-autonomy-live-fixture.py',directory],{cwd:root,windowsHide:true,encoding:'utf8'});
 if(fixture.status!==0)throw Object.assign(new Error(),{code:'SYNTHETIC_FIXTURE_FAILED'});
 const core=cp.spawn(python,['src/core/assistant_core.py','--data-dir',directory],{cwd:root,windowsHide:true,stdio:['pipe','pipe','ignore'],env:{...process.env,PYTHONUTF8:'1'}});
 let serial=0;const pending=new Map();readline.createInterface({input:core.stdout}).on('line',line=>{const r=JSON.parse(line),p=pending.get(r.id);if(!p)return;pending.delete(r.id);r.error?p.reject(Object.assign(new Error(r.error.message),{code:r.error.code})):p.resolve(r.result);});
 const rpc=(method,params={})=>new Promise((resolve,reject)=>{const id=++serial;pending.set(id,{resolve,reject});core.stdin.write(JSON.stringify({id,jsonrpc:'2.0',method,params})+'\n');});
 const store={data:{activeAccountId:'synthetic',activePlatform:'qq',activeModelProfileId:profile.id,modelProfiles:[profile]},getModelApiKey:()=>apiKey};
 let calls=0,tokens=0,compressionCalls=0;const started=Date.now();let result,errorCode='';
 const controller=createWorkspaceAgent({rpc,settings:()=>store,generateImpl:async input=>{
  if(calls>=12||tokens+Buffer.byteLength(input.request.system+input.request.user)+input.request.max_tokens>180000)throw Object.assign(new Error('Synthetic acceptance budget reached.'),{code:'LIVE_TEST_LIMIT',knownNotSent:true});
  calls++;if(input.request.system.startsWith('先整理聊天记录'))compressionCalls++;
  const response=await generate({...input,timeoutMs:120000});tokens+=(response.usage.input_tokens||0)+(response.usage.output_tokens||0);
  console.log(JSON.stringify({stage:'model_call',call:calls,input_tokens:response.usage.input_tokens,output_tokens:response.usage.output_tokens}));return response;
 }});
 try{
  await rpc('ai.budget.save',{settings:{per_run_tokens:180000,daily_tokens:300000,monthly_tokens:500000,output_tokens:4096,monthly_cost:0}});
  const session=JSON.parse(fs.readFileSync(path.join(directory,'synthetic-session.json'),'utf8')).session_id;
  try{result=await controller.run({account_id:'synthetic',session_id:session,question:'今天所有的'});}catch(e){errorCode=e.code||'MODEL_REQUEST_FAILED';}
  const history=await rpc('workspace.chat.get',{account_id:'synthetic',session_id:session}),turn=history.items.at(-1);
  const contents=[];for(const file of turn.artifacts||[])if(file.mime==='text/markdown'){const data=await rpc('workspace.artifact',{account_id:'synthetic',artifact_id:file.artifact_id});contents.push(fs.readFileSync(data.path,'utf8'));}
  const text=contents.join('\n');
  const checks={completed:result?.status==='completed',markdown:contents.length>0,all_questions:(text.match(/你想读哪本合成书？/g)||[]).length===2,
   all_answers:(text.match(/答：合成故事集。\n保留空格  🙂\n```原文```/g)||[]).length===2,split_answers:(text.match(/补充回答分开发送。/g)||[]).length===2,
   excludes_uninvited:!text.includes('与邀请问答无关的合成问候。')&&!text.includes('慢慢来'),no_compression:compressionCalls===0};
  const evidence={version:JSON.parse(fs.readFileSync(path.join(root,'package.json'),'utf8')).version,source:'synthetic',model:profile.model,question:'今天所有的',old_clarification_turns:2,inactive_contacts:170,
   calls,tokens,compression_calls:compressionCalls,seconds:Math.round((Date.now()-started)/1000),error_code:errorCode,checks,ok:Object.values(checks).every(Boolean)};
  fs.writeFileSync(path.join(root,'build/qa/live-agent-autonomy.json'),JSON.stringify(evidence,null,2));console.log(JSON.stringify(evidence));if(!evidence.ok)process.exitCode=1;
 }finally{core.stdin.end();}
}
module.exports={run:main};
if(require.main===module)main().catch(error=>{console.log(JSON.stringify({ok:false,code:error.code||'ACCEPTANCE_UNAVAILABLE'}));process.exitCode=1;});
