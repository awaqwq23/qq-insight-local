// Explicit opt-in live acceptance. Credentials arrive on stdin only; never log or persist them.
const fs=require('node:fs');const path=require('node:path');
const root=path.resolve(__dirname,'..');
const cp=require('node:child_process');const readline=require('node:readline');
const PYTHON='C:/Users/Administrator/AppData/Local/Programs/Python/Python314/python.exe';
const baseRelay='https://app.soruxgpt.com/api/codex';
async function relayBilling(secrets){
 const response=await fetch(baseRelay+'/usage',{headers:{Authorization:'Bearer '+secrets.sorux},redirect:'error',signal:AbortSignal.timeout(20000)});
 if(!response.ok)throw Object.assign(new Error('Billing unavailable'),{code:'BILLING_UNAVAILABLE'});
 const value=await response.json(),unit=String(value.currency||value.unit||'').toUpperCase();
 if(!['USD','CNY','RMB'].includes(unit)||!Number.isFinite(value.used))throw Object.assign(new Error('Billing unit unknown'),{code:'BILLING_UNIT_UNKNOWN'});
 return {used:value.used,unit};
}
async function syntheticAcceptance(secrets){
 const intern=process.argv.includes('--intern'),meter=()=>intern?Promise.resolve({used:0,unit:'TOKEN'}):relayBilling(secrets);
 const observed=await meter(),statePath=path.join(root,'build/qa/live-spend-state.json');
 let state=fs.existsSync(statePath)?JSON.parse(fs.readFileSync(statePath,'utf8').replace(/^\uFEFF/,'')):{baseline_used:observed.used,unit:observed.unit,limit:30};
 if(!intern){
  if(state.owned_spend===undefined){
   const receipts=fs.readdirSync(path.join(root,'build/qa')).filter(name=>/^live-volume.*\.json$/.test(name)).map(name=>{try{return JSON.parse(fs.readFileSync(path.join(root,'build/qa',name),'utf8'));}catch{return null;}}).filter(r=>r?.provider==='sorux'&&r.billing_unit===state.unit&&r.requests>0&&r.reported_debit>=0&&r.reported_debit<=30);
   const recorded=Math.max(0,...receipts.map(r=>r.reported_debit));
   if(receipts.length)Object.assign(state,{owned_spend:recorded,last_meter_used:state.baseline_used+recorded,run_open:false});
  }
  state=require('./live-spend.cjs').begin(observed,state);
 }
 if(!intern)fs.writeFileSync(statePath,JSON.stringify(state));const before={...observed,used:intern?0:state.baseline_used};
 console.log(JSON.stringify({stage:'billing',unit:before.unit,limit:30,spent:observed.used-before.used}));
 const local=process.argv.includes('--local');
 const directory=local?path.join(process.env.APPDATA,'qq-insight-local/data'):path.join(root,'build/live/synthetic-'+Date.now());
 let scope={account_id:'synthetic',conversation_id:'synthetic-group'};
 if(local){const lookup=cp.spawnSync(PYTHON,['scripts/live-scope.py',directory],{cwd:root,windowsHide:true,input:JSON.stringify({scope_hint:secrets.scope_hint,resume_profile:secrets.resume_latest?(intern?'intern-live':'sorux-live'):null,compression:secrets.only}),encoding:'utf8',env:{...process.env,PYTHONUTF8:'1'}});if(lookup.status!==0)throw Object.assign(new Error('Scope unavailable or busy'),{code:'LOCAL_SCOPE_UNAVAILABLE'});scope=JSON.parse(lookup.stdout);console.log(JSON.stringify({stage:'scope',source:'local-imported',total_messages:scope.total}));}
 else{fs.mkdirSync(directory,{recursive:true});const seed=cp.spawnSync(PYTHON,['scripts/live-fixture.py',directory],{cwd:root,windowsHide:true,encoding:'utf8',env:{...process.env,PYTHONUTF8:'1'}});if(seed.status!==0)throw Object.assign(new Error('Seed failed'),{code:'SEED_FAILED'});}
 const core=cp.spawn(PYTHON,['src/core/assistant_core.py','--data-dir',directory],{cwd:root,windowsHide:true,stdio:['pipe','pipe','ignore'],env:{...process.env,PYTHONUTF8:'1'}});
 let next=0;const pending=new Map();readline.createInterface({input:core.stdout}).on('line',line=>{try{const value=JSON.parse(line),entry=pending.get(value.id);if(!entry)return;pending.delete(value.id);value.error?entry.reject(Object.assign(new Error('Core request failed'),{code:value.error.code})):entry.resolve(value.result);}catch{}});
 const rpc=(method,params={})=>new Promise((resolve,reject)=>{const id=++next;pending.set(id,{resolve,reject});core.stdin.write(JSON.stringify({jsonrpc:'2.0',id,method,params})+'\n');});
 const {generate}=require('../src/desktop/main/model-gateway');const {createAICoordinator}=require('../src/desktop/main/ai-coordinator');
 const profile={id:intern?'intern-live':'sorux-live',provider:'custom',protocol:intern?'chat':'responses',model:intern?secrets.model:'gpt-5.6-sol',baseUrl:intern?secrets.baseUrl:baseRelay,limits:{context_tokens:secrets.context||262144,tpm_tokens:secrets.tpm||0,output_tokens:secrets.output||2048,basis:'manual',source:'本次受限验收配置'}};
 let expected=0,requests=0,rate=0,lastJob='',largestRequestBytes=0,largestChunkMessages=0,largestInputTokens=0;const outcomes=[];
 const coordinator=createAICoordinator({rpc,settings:()=>({data:{activeModelProfileId:profile.id,modelProfiles:[profile]},getModelApiKey:()=>intern?secrets.intern:secrets.sorux}),progress:p=>{if(p.job_id)lastJob=p.job_id;if(/正在分析第|正在汇总|等待 \d+ 秒|本段结果未通过/.test(p.message))console.log(JSON.stringify({stage:'chunk',message:p.message}));},generateImpl:async input=>{
  const current=await meter();const spent=current.used-before.used;const tokenBound=Buffer.byteLength(input.request.system)+Buffer.byteLength(input.request.user)+input.request.max_tokens+512;
  // Reserve against UTF-8 bytes (a conservative token bound), with at least three times the
  // highest observed debit per byte. The floor also protects the first request of a new run.
  const ceiling=current.unit==='USD'?0.00005:0.00035;const reservation=tokenBound*Math.max(rate,ceiling);
  if(requests>=(intern?128:64)||(!intern&&spent+reservation>30))throw Object.assign(new Error('Live spend limit reached'),{code:'LIVE_SPEND_LIMIT',knownNotSent:true});
  requests++;const result=await generate({...input,timeoutMs:180000});largestRequestBytes=Math.max(largestRequestBytes,tokenBound-input.request.max_tokens);largestChunkMessages=Math.max(largestChunkMessages,JSON.parse(input.request.user).messages.length);largestInputTokens=Math.max(largestInputTokens,result.usage.input_tokens||0);const after=await meter();if(!intern){state=require('./live-spend.cjs').settle(after,state);fs.writeFileSync(statePath,JSON.stringify(state));}const debit=Math.max(0,after.used-current.used);rate=Math.max(rate,debit/tokenBound*3);console.log(JSON.stringify({stage:'call',ok:true,input_tokens:result.usage.input_tokens,output_tokens:result.usage.output_tokens,...(!intern?{reported_debit:debit,unit:after.unit,total_reported_debit:after.used-before.used}:{})}));return result;
 }});
 try{
  if(local){const group=await rpc('group.get',{account_id:scope.account_id,conversation_id:scope.conversation_id});await rpc('group.save',{account_id:scope.account_id,conversation_id:scope.conversation_id,settings:{...group,images:false,remember:false,auto_favorite:false,schedule_minutes:0}});}
  await rpc('ai.budget.save',{settings:{per_run_tokens:5000000,daily_tokens:10000000,monthly_tokens:100000000,output_tokens:profile.limits.output_tokens,monthly_cost:0}});
  for(const [compression,limit] of [['off',1001],['balanced',3001],['strong',5001]].filter(([mode])=>!secrets.only||mode===secrets.only)){
   expected=limit;console.log(JSON.stringify({stage:'begin',compression,limit}));
   try{
    let result,resume=scope.resume_job||'',narrowed=0;
    while(true){try{result=await coordinator.run({account_id:scope.account_id,conversation_id:scope.conversation_id,feature:'summary',...(resume?{job_id:resume}:{}),options:{mode:'recent',compression,limit,output_chars:secrets.chars||500,hierarchical:secrets.hierarchical===true}});break;}catch(error){if(!intern&&error.code==='LIVE_SPEND_LIMIT'&&requests<64&&profile.limits.context_tokens>12288&&narrowed<5){const billing=await meter();if(billing.used-before.used>=29.8)throw error;profile.limits.context_tokens=Math.max(12288,Math.floor(profile.limits.context_tokens/2));resume=lastJob;narrowed++;console.log(JSON.stringify({stage:'spend_narrowed',context_tokens:profile.limits.context_tokens}));continue;}throw error;}}
    const history=await rpc('ai.history',{account_id:scope.account_id,conversation_id:scope.conversation_id,feature:'summary',job_id:result.job_id});const coverage=history.report?.coverage;const ok=result.status==='completed'&&coverage.selected===limit&&coverage.completed_messages===limit&&!!history.report.summary;const outcome={compression,limit,ok,status:result.status,completed_messages:coverage?.completed_messages,chunks:coverage?.chunks,hierarchical:coverage?.hierarchical,usage:history.jobs.find(job=>job.id===result.job_id)?.usage};outcomes.push(outcome);console.log(JSON.stringify({stage:'result',...outcome}));if(!ok)break;
   }catch(error){outcomes.push({compression,limit,ok:false,code:error.code||'LIVE_FAILED'});console.log(JSON.stringify({stage:'result',...outcomes.at(-1)}));break;}
  }
  const after=await meter();const report={at:new Date().toISOString(),model:profile.model,provider:intern?'intern':'sorux',scope:local?'local-imported':'synthetic',outcomes,requests,largest_request_bytes:largestRequestBytes,largest_chunk_messages:largestChunkMessages,largest_input_tokens:largestInputTokens,reported_debit:intern?null:after.used-before.used,billing_unit:after.unit,spend_limit:intern?null:30};fs.writeFileSync(path.join(root,'build/qa/live-volume-'+(intern?'intern-':'')+(local?'local':'synthetic')+(secrets.only?'-'+secrets.only:'')+(secrets.hierarchical?'-hierarchical':'')+'.json'),JSON.stringify(report,null,2));
 }finally{core.stdin.end();try{if(local){const restore=cp.spawnSync(PYTHON,['scripts/live-scope.py',directory,'--restore'],{cwd:root,windowsHide:true,input:JSON.stringify(scope),encoding:'utf8',env:{...process.env,PYTHONUTF8:'1'}});console.log(JSON.stringify({stage:'settings_restored',ok:restore.status===0}));}}finally{setTimeout(()=>core.kill(),1000).unref();if(!intern){const latest=await meter();state=require('./live-spend.cjs').settle(latest,state);state.run_open=false;fs.writeFileSync(statePath,JSON.stringify(state));}}}
}
async function discover(secrets){
 for(const [name,base] of [['intern','https://discovery-api.intern-ai.org.cn/v1'],['minimax','https://api.minimaxi.com/v1'],['sorux','https://app.soruxgpt.com/api/codex']]){
  try{
   const response=await fetch(base+'/models',{headers:{Authorization:'Bearer '+secrets[name]},redirect:'error',signal:AbortSignal.timeout(20000)});
   const payload=await response.json().catch(()=>({}));const items=payload.data||payload.models||[];
   const models=Array.isArray(items)?items.map(value=>typeof value==='string'?{id:value}:{id:value.id,context_length:value.context_length,context_window:value.context_window}).filter(value=>value.id):[];
   console.log(JSON.stringify({provider:name,status:response.status,models}));
  }catch(error){console.log(JSON.stringify({provider:name,code:error.cause?.code||error.name}));}
 }
}
async function probe(secrets){
 for(const [name,base,model] of [['intern','https://discovery-api.intern-ai.org.cn/v1','deepseek-v4-pro-0813'],['minimax','https://api.minimaxi.com/v1','MiniMax-M3'],['minimax','https://api.minimax.cn/v1','MiniMax-M3'],['minimax','https://api.minimaxi.com/anthropic/v1','MiniMax-M3']]){
  try{const anthropic=base.includes('/anthropic/');const response=await fetch(base+(anthropic?'/messages':'/chat/completions'),{method:'POST',headers:{...(anthropic?{'x-api-key':secrets[name],'anthropic-version':'2023-06-01'}:{Authorization:'Bearer '+secrets[name]}),'content-type':'application/json'},redirect:'error',signal:AbortSignal.timeout(45000),body:JSON.stringify({model,max_tokens:128,stream:false,messages:[{role:'user',content:'Return only JSON: {"ok":true}'}],...(name==='minimax'?{thinking:{type:'disabled'},...(!anthropic?{reasoning_split:true}:{})}:{})})});const payload=await response.json().catch(()=>({}));console.log(JSON.stringify({provider:name,host:new URL(base).hostname,protocol:anthropic?'anthropic':'chat',status:response.status,error_code:typeof payload.base_resp?.status_code==='number'?payload.base_resp.status_code:null,stop:payload.choices?.[0]?.finish_reason,usage:payload.usage?{input_tokens:payload.usage.prompt_tokens,output_tokens:payload.usage.completion_tokens}:null,has_output:!!(payload.choices?.[0]?.message?.content||payload.content?.length)}));}catch(error){console.log(JSON.stringify({provider:name,code:error.cause?.code||error.name}));}
 }
 for(const endpoint of ['https://app.soruxgpt.com/api/codex/usage','https://app.soruxgpt.com/api/codex/pricing']){
  try{const response=await fetch(endpoint,{headers:{Authorization:'Bearer '+secrets.sorux},redirect:'error',signal:AbortSignal.timeout(20000)});const payload=await response.json().catch(()=>({}));const numeric={};const visit=(value,prefix='')=>{if(!value||typeof value!=='object')return;for(const [key,item] of Object.entries(value)){if(typeof item==='number'&&/price|cost|usd|balance|quota|used|remaining/i.test(key))numeric[prefix+key]=item;else if(item&&typeof item==='object'&&prefix.length<100)visit(item,prefix+key+'.');}};visit(payload);console.log(JSON.stringify({provider:'sorux',path:new URL(endpoint).pathname,status:response.status,numeric}));}catch(error){console.log(JSON.stringify({provider:'sorux',code:error.cause?.code||error.name}));}
 }
}
async function relayProbe(secrets){
 const base='https://app.soruxgpt.com/api/codex';
 const usage=async()=>{const r=await fetch(base+'/usage',{headers:{Authorization:'Bearer '+secrets.sorux},redirect:'error',signal:AbortSignal.timeout(20000)});const p=await r.json();const unit=String(p.currency||p.unit||'').toUpperCase();return {used:p.used,currency:['USD','CNY','RMB'].includes(unit)?unit:null,fields:Object.keys(p).filter(k=>!/^user|account|key|token$/i.test(k))};};
 const before=await usage();console.log(JSON.stringify({provider:'sorux',billing_currency:before.currency,billing_fields:before.fields}));
 const {generate}=require('../src/desktop/main/model-gateway');
 try{const r=await generate({profile:{id:'relay',model:'gpt-5.6-sol',provider:'custom',protocol:'responses',baseUrl:base},apiKey:secrets.sorux,request:{system:'Return only valid JSON.',user:'Return {"ok":true}.',max_tokens:512},timeoutMs:60000,fetchImpl:async(url,input)=>{const response=await fetch(url,input);if(!response.ok){const p=await response.clone().json().catch(()=>({}));const message=String(p.error?.message||p.message||'');console.log(JSON.stringify({provider:'sorux',status:response.status,parameter_hints:['stream','max_output_tokens','instructions','store','input','reasoning'].filter(k=>message.includes(k))}));}return response;}});console.log(JSON.stringify({provider:'sorux',ok:JSON.parse(r.result).ok===true,usage:{input_tokens:r.usage.input_tokens,output_tokens:r.usage.output_tokens}}));}catch(error){console.log(JSON.stringify({provider:'sorux',code:error.code||'RELAY_PROBE_FAILED'}));}
 const after=await usage();console.log(JSON.stringify({provider:'sorux',reported_used_delta:Number((after.used-before.used).toFixed(6)),currency:after.currency}));
}
async function main(secrets){if(process.argv.includes('--probe'))await probe(secrets);else if(process.argv.includes('--relay-probe'))await relayProbe(secrets);else if(process.argv.includes('--synthetic')||process.argv.includes('--local'))await syntheticAcceptance(secrets);else if(process.argv.includes('--billing'))console.log(JSON.stringify(await relayBilling(secrets)));else await discover(secrets);}
process.stdin.setEncoding('utf8');if(process.stdin.isTTY)process.stdin.setRawMode(true);
let input='';process.stdin.on('data',chunk=>{input+=chunk;let secrets;try{secrets=JSON.parse(input.trim());}catch{return;}input='';process.stdin.pause();if(process.stdin.isTTY)process.stdin.setRawMode(false);main(secrets).catch(()=>{console.log('LIVE_RUN_FAILED');process.exitCode=1;});});
console.log('READY_FOR_CREDENTIALS');
