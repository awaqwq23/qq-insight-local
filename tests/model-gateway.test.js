const assert=require('node:assert/strict');
const {generate}=require('../src/desktop/main/model-gateway');
const {createAICoordinator}=require('../src/desktop/main/ai-coordinator');

async function main(){
 const profile={id:'fake',model:'synthetic',provider:'openai-compatible',baseUrl:'https://example.test/v1'};
 const request={system:'synthetic system',user:'synthetic material',max_tokens:512,images:[]};
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
 console.log('Model gateway passed: OpenAI-compatible/Anthropic, image payload, usage, HTTP redaction, truncation, cancellation, budget gate.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
