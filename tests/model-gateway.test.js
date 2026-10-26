const assert=require('node:assert/strict');
const {generate}=require('../src/desktop/main/model-gateway');
const {createAICoordinator}=require('../src/desktop/main/ai-coordinator');

async function main(){
 const profile={id:'fake',model:'synthetic',provider:'openai-compatible',baseUrl:'https://example.test/v1'};
 const request={system:'synthetic system',user:'synthetic material',max_tokens:512,images:[]};
 await generate({profile:{...profile,model:'deepseek-flash',baseUrl:'https://api.deepseek.com'},apiKey:'synthetic-secret',request:{...request,json_mode:true,system:'Return JSON only.'},fetchImpl:async(url,input)=>{assert.deepEqual(JSON.parse(input.body).response_format,{type:'json_object'});return new Response(JSON.stringify({choices:[{finish_reason:'stop',message:{content:'{"ok":true}'}}],usage:{prompt_tokens:10,completion_tokens:5}}));}});
 const timeout=AbortSignal.timeout;let wait;
 try{
  AbortSignal.timeout=ms=>{wait=ms;return timeout(ms);};
  const long=await generate({profile,apiKey:'synthetic-secret',request:{...request,max_tokens:65536},fetchImpl:async(url,input)=>{
   assert.equal(JSON.parse(input.body).max_tokens,65536);
   return new Response(JSON.stringify({choices:[{finish_reason:'stop',message:{content:'合成完整长报告。'.repeat(3000)}}],usage:{prompt_tokens:30,completion_tokens:20000}}));
  }});
  assert.equal(wait,1800000);assert.equal(long.result.length,'合成完整长报告。'.repeat(3000).length);
 }finally{AbortSignal.timeout=timeout;}
 let sent;
 const result=await generate({profile,apiKey:'synthetic-secret',request,fetchImpl:async(url,input)=>{
  sent={url,input,body:JSON.parse(input.body)};
  return new Response(JSON.stringify({id:'synthetic-request',choices:[{finish_reason:'stop',message:{content:'{"summary":"ok","items":[]}'}}],usage:{prompt_tokens:20,completion_tokens:10}}));
 }});
 assert.equal(sent.url,'https://example.test/v1/chat/completions');assert.equal(sent.input.redirect,'error');
 assert.equal(sent.input.headers.Authorization,'Bearer synthetic-secret');assert.equal(result.usage.input_tokens,20);
 assert.deepEqual(sent.body.messages.map(item=>item.role),['system','user']);
 const image={message_id:'synthetic',media_index:0,data_url:'data:image/png;base64,eA=='};
 await generate({profile:{...profile,provider:'anthropic'},apiKey:'synthetic-secret',request:{...request,images:[image]},fetchImpl:async(url,input)=>{
  const body=JSON.parse(input.body);assert.equal(url,'https://example.test/v1/messages');assert.equal(body.system,request.system);
  assert.equal(input.headers['x-api-key'],'synthetic-secret');assert.equal(body.messages[0].content[2].source.media_type,'image/png');
  return new Response(JSON.stringify({stop_reason:'end_turn',content:[{type:'text',text:'{}'}],usage:{input_tokens:20,output_tokens:5,cache_read_input_tokens:10}}));
 }});
 await assert.rejects(generate({profile,apiKey:'key',request,fetchImpl:async()=>new Response('secret reflected',{status:401})}),error=>error.message.includes('401')&&!error.message.includes('reflected'));
 await assert.rejects(generate({profile,apiKey:'key',request,fetchImpl:async()=>new Response(JSON.stringify({choices:[{finish_reason:'length',message:{content:'partial'}}],usage:{prompt_tokens:20,completion_tokens:512}}))}),error=>error.code==='MODEL_INCOMPLETE'&&error.usage.output_tokens===512);
 const controller=new AbortController();controller.abort();
 let called=false;
 await assert.rejects(generate({profile,apiKey:'key',request,signal:controller.signal,fetchImpl:async()=>{called=true;}}),error=>error.knownNotSent);
 assert.equal(called,false);
 const calls=[];
 const settings={data:{activeModelProfileId:'fake',modelProfiles:[profile]},getModelApiKey:()=> 'synthetic-key'};
 const coordinator=createAICoordinator({settings:()=>settings,rpc:async(method,params)=>{
  calls.push(method);
  if(method==='group.get')return {images:false};
  if(method==='ai.prepare')return {status:'queued',job_id:'job'};
  if(method==='ai.next')throw new Error('Budget exceeded');
  if(method==='ai.fail')return {status:'failed'};
 },generateImpl:async()=>{called=true;}});
 await assert.rejects(coordinator.run({conversation_id:'group',account_id:'synthetic',feature:'work'}));
 assert.equal(called,false);assert.ok(calls.includes('ai.fail'));assert.equal(coordinator.status().running,false);
 let nextCalls=0,commitCalls=0,resumes=0,generated=0;
 const correcting=createAICoordinator({settings:()=>settings,rpc:async(method,input)=>{
  if(method==='group.get')return {images:false};if(method==='ai.prepare')return {job_id:'synthetic-correction'};
  if(method==='ai.next')return ++nextCalls>2?{done:true,status:'ready'}:{...request,done:false,index:0,total:1,attempt:'synthetic-'+nextCalls,user:'{"messages":[{"id":"m0"}]}' };
  if(method==='ai.commit'){if(++commitCalls===1)throw Object.assign(new Error('Invalid evidence'),{code:'AI_EVIDENCE_INVALID'});return {committed:true};}
  if(method==='ai.resume'){resumes++;return {status:'queued'};}if(method==='ai.finish')return {status:'completed'};
 },generateImpl:async input=>{generated++;if(generated===2){assert.match(input.request.system,/逐字复制/);assert.match(input.request.system,/Invalid evidence/);assert.match(input.request.system,/跨群综合结论放items/);}return {result:'{}',usage:{input_tokens:10,output_tokens:5}};}});
 assert.equal((await correcting.run({account_id:'synthetic',conversation_id:'group',feature:'summary'})).status,'completed');
 assert.equal(resumes,1);assert.equal(commitCalls,2);assert.equal(generated,2);
 let limitedCalls=0,limitedNext=0,limitedResumes=0,unbilled=0;
 const limited=createAICoordinator({settings:()=>settings,rpc:async(method,input)=>{
  if(method==='group.get')return {images:false};if(method==='ai.prepare')return {job_id:'synthetic-limit'};
  if(method==='ai.next')return ++limitedNext>2?{done:true,status:'ready'}:{...request,done:false,index:0,total:1,attempt:'rate-'+limitedNext,user:'{"messages":[]}' };
  if(method==='ai.fail'){assert.equal(input.known_not_sent,true);unbilled++;return {status:'failed'};}
  if(method==='ai.resume'){limitedResumes++;return {status:'queued'};}if(method==='ai.finish')return {status:'completed'};return {};
 },generateImpl:async()=>{if(++limitedCalls===1)throw Object.assign(new Error('Rate limit'),{code:'MODEL_RATE_LIMIT',knownNotSent:true,retryAfterMs:1});return {result:'{}',usage:{input_tokens:10,output_tokens:5}};}});
 assert.equal((await limited.run({account_id:'synthetic',conversation_id:'group',feature:'summary'})).status,'completed');assert.equal(limitedResumes,1);assert.equal(unbilled,1);assert.equal(limitedCalls,2);
 let quotaCalls=0,quotaResumes=0;
 const quota=createAICoordinator({settings:()=>settings,rpc:async(method)=>{
  if(method==='group.get')return {images:false};if(method==='ai.prepare')return {job_id:'synthetic-quota'};
  if(method==='ai.next')return {...request,done:false,index:0,total:1,attempt:'quota-attempt',user:'{"messages":[]}'};
  if(method==='ai.resume')quotaResumes++;return {};
 },generateImpl:async()=>{quotaCalls++;throw Object.assign(new Error('Service quota'),{code:'MODEL_RATE_LIMIT',rateKind:'quota',knownNotSent:true});}});
 await assert.rejects(quota.run({account_id:'synthetic',conversation_id:'group',feature:'summary'}),e=>e.rateKind==='quota');assert.equal(quotaCalls,1);assert.equal(quotaResumes,0);
 await assert.rejects(generate({profile,apiKey:'synthetic',request,fetchImpl:async()=>new Response(JSON.stringify({error:{message:'insufficient quota, sensitive synthetic payload'}}),{status:429})}),e=>e.rateKind==='quota'&&e.message.includes('不是已确认的上下文超限')&&!e.message.includes('sensitive'));
 const responseProfile={...profile,protocol:'responses'};
 const terminal={type:'response.completed',response:{id:'synthetic-response',status:'completed',output:[{type:'message',role:'assistant',content:[{type:'output_text',text:'{"summary":"合成结果","items":[]}'}]}],usage:{input_tokens:25,output_tokens:15,input_tokens_details:{cached_tokens:5}}}};
 const responseResult=await generate({profile:responseProfile,apiKey:'synthetic-key',request:{...request,images:[image]},fetchImpl:async(url,input)=>{
  const body=JSON.parse(input.body);assert.equal(url,'https://example.test/v1/responses');assert.equal(body.store,false);assert.equal(body.stream,true);assert.equal(body.max_output_tokens,512);assert.equal(body.instructions,request.system);
  assert.equal(body.input[0].content[1].type,'input_text');assert.match(body.input[0].content[1].text,/media_index=0/);assert.equal(body.input[0].content[2].type,'input_image');
  const bytes=new TextEncoder().encode('data: '+JSON.stringify(terminal)+'\n\n');
  return new Response(new ReadableStream({start(controller){for(let i=0;i<bytes.length;i+=7)controller.enqueue(bytes.slice(i,i+7));controller.close();}}),{headers:{'content-type':'text/event-stream'}});
 }});
 assert.equal(JSON.parse(responseResult.result).summary,'合成结果');assert.equal(responseResult.usage.cached_tokens,5);
 const cachedWrite=await generate({profile:{...profile,provider:'anthropic'},apiKey:'synthetic',request,fetchImpl:async()=>new Response(JSON.stringify({stop_reason:'end_turn',content:[{type:'text',text:'{}'}],usage:{input_tokens:100,output_tokens:10,cache_read_input_tokens:20,cache_creation_input_tokens:30,cache_creation:{ephemeral_5m_input_tokens:10,ephemeral_1h_input_tokens:20}}}))});
 assert.equal(cachedWrite.usage.input_tokens,150);assert.equal(cachedWrite.usage.cache_write_tokens,10);assert.equal(cachedWrite.usage.cache_write_1h_tokens,20);
 const sse=value=>new Response('data: '+JSON.stringify(value)+'\n\n',{headers:{'content-type':'text/event-stream'}});
 await assert.rejects(generate({profile:responseProfile,apiKey:'synthetic',request,fetchImpl:async()=>sse({type:'response.output_text.delta',delta:'partial'})}),e=>e.code==='MODEL_INCOMPLETE');
 await assert.rejects(generate({profile:responseProfile,apiKey:'synthetic',request,fetchImpl:async()=>sse({type:'response.incomplete',response:{status:'incomplete',incomplete_details:{reason:'max_output_tokens'},usage:{input_tokens:10,output_tokens:512}}})}),e=>e.code==='MODEL_INCOMPLETE'&&e.usage.output_tokens===512);
 await assert.rejects(generate({profile:responseProfile,apiKey:'synthetic',request,fetchImpl:async()=>new Response('invalid')}),e=>e.code==='MODEL_RESPONSE_INVALID');
 await generate({profile:{...profile,baseUrl:'https://api.minimaxi.com/v1',model:'MiniMax-M3'},apiKey:'synthetic',request,fetchImpl:async(url,input)=>{const body=JSON.parse(input.body);assert.equal(body.thinking.type,'disabled');assert.equal(body.reasoning_split,true);return new Response(JSON.stringify({choices:[{finish_reason:'stop',message:{content:'<think>synthetic reasoning</think>{"ok":true}'}}]}));}}).then(r=>assert.equal(JSON.parse(r.result).ok,true));
 await generate({profile:{...profile,baseUrl:'https://discovery-api.intern-ai.org.cn/v1',model:'deepseek-v4-pro-0813'},apiKey:'synthetic',request,fetchImpl:async(url,input)=>{assert.equal(JSON.parse(input.body).thinking.type,'disabled');return new Response(JSON.stringify({choices:[{finish_reason:'stop',message:{content:'{}'}}]}));}});
 console.log('Model gateway passed: OpenAI-compatible/Anthropic, image payload, usage, HTTP redaction, truncation, cancellation, budget gate.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
