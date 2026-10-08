const fs=require('node:fs');const path=require('node:path');
const {generate,modelDescriptor}=require('./model-gateway');
const {configurationFingerprint}=require('./model-capabilities');
function wavSeconds(data){
 if(data.length<44||data.toString('ascii',0,4)!=='RIFF'||data.toString('ascii',8,12)!=='WAVE')return null;
 let rate=0,size=0;
 for(let i=12;i+8<=data.length;){const type=data.toString('ascii',i,i+4);const length=data.readUInt32LE(i+4);if(i+8+length>data.length)break;if(type==='fmt '&&length>=16)rate=data.readUInt32LE(i+16);if(type==='data')size+=length;i+=8+length+(length%2);}
 return rate&&size?size/rate:null;
}
async function transcribe({profile,apiKey,data,mime='audio/wav',filename='audio.wav',signal,fetchImpl=globalThis.fetch}){
 if(!apiKey||!profile.model)throw Object.assign(new Error('请先保存语音模型和 API Key。'),{knownNotSent:true});
 const url=new URL(profile.baseUrl);
 if(!['https:','http:'].includes(url.protocol)||url.username||url.password)throw Object.assign(new Error('语音接口地址无效。'),{knownNotSent:true});
 if(signal?.aborted)throw Object.assign(new Error('已取消语音识别。'),{knownNotSent:true});
 const headers={Authorization:`Bearer ${apiKey}`};let body,endpoint;
 if(profile.protocol==='qwen-asr'){
  headers['content-type']='application/json';endpoint='chat/completions';
  body=JSON.stringify({model:profile.model,stream:false,messages:[{role:'user',content:[{type:'input_audio',input_audio:{data:`data:${mime};base64,${data.toString('base64')}`}}]}],asr_options:{enable_itn:false}});
 }else{
  endpoint='audio/transcriptions';body=new FormData();body.set('model',profile.model);body.set('file',new Blob([data],{type:mime}),filename);body.set('response_format',profile.model==='whisper-1'?'verbose_json':'json');
 }
 const timeout=AbortSignal.timeout(120000);const combined=signal?AbortSignal.any([timeout,signal]):timeout;
 try{
  const response=await fetchImpl(`${profile.baseUrl.replace(/\/+$/,'')}/${endpoint}`,{method:'POST',headers,body,redirect:'error',signal:combined});
  if(!response.ok)throw Object.assign(new Error(`语音接口 HTTP ${response.status}，请检查模型、语音协议和权限。`),{code:'MODEL_HTTP_ERROR'});
  const raw=await response.text();if(raw.length>2*1024*1024)throw new Error('语音响应过大');
  const payload=JSON.parse(raw);const u=payload.usage||{};
  const usage={input_tokens:u.prompt_tokens??u.input_tokens,output_tokens:u.completion_tokens??u.output_tokens,cached_tokens:u.prompt_tokens_details?.cached_tokens||0,seconds:u.seconds??payload.duration??wavSeconds(data),request_id:String(payload.id||response.headers.get('x-request-id')||'').slice(0,160)};
  const result=profile.protocol==='qwen-asr'?payload.choices?.[0]?.message?.content:payload.text;
  if(typeof result!=='string')throw Object.assign(new Error('语音接口未返回转写文本。'),{code:'MODEL_INVALID',usage});
  if(profile.protocol==='qwen-asr'&&payload.choices?.[0]?.finish_reason!=='stop')throw Object.assign(new Error('语音转写未完整结束。'),{code:'MODEL_INCOMPLETE',usage});
  return {result,usage};
 }catch(error){
  if(error.code?.startsWith('MODEL_'))throw error;
  throw new Error(signal?.aborted?'已取消语音识别；用量可能待核对。':timeout.aborted?'语音识别超时；用量可能待核对。':'语音接口连接或返回格式异常。');
 }
}
function mediaConfiguration(store,kind){
 const profile=store.data.mediaProfiles?.[kind];const apiKey=profile&&store.getMediaApiKey(kind);
 if(!profile?.baseUrl||!profile?.model||!apiKey)throw new Error(`请先在设置中保存独立${kind==='vision'?'识图':'语音'} API、模型和密钥。`);
 return {profile:{...profile,apiKeyEncrypted:undefined},apiKey,fingerprint:configurationFingerprint(profile)};
}
async function meteredCall({rpc,profile,apiKey,kind,request,data,mime,filename,signal,job_id='',chunk_idx=-1,generateImpl=generate,transcribeImpl=transcribe}){
 const speech=kind.endsWith('speech');const seconds=speech?(wavSeconds(data)??300):undefined;
 const reserved=await rpc('ai.call.reserve',{model:modelDescriptor(profile),kind,input_tokens:speech?Math.ceil(seconds*100)+512:Math.max(8192,Buffer.byteLength(request.user||'')+4096),output_tokens:speech?4096:request.max_tokens,seconds,job_id,chunk_idx});
 try{
  const response=speech?await transcribeImpl({profile,apiKey,data,mime,filename,signal}):await generateImpl({profile,apiKey,request,signal});
  await rpc('ai.call.settle',{attempt:reserved.attempt,usage:response.usage,state:'completed'});
  return {...response,attempt:reserved.attempt,pricing:reserved.pricing};
 }catch(error){await rpc('ai.call.settle',{attempt:reserved.attempt,usage:error.usage,known_not_sent:error.knownNotSent===true,state:signal?.aborted?'cancelled':'failed'});throw error;}
}
async function testMedia({store,rpc,kind}){
 if(!['vision','speech'].includes(kind))throw new Error('测试类型无效。');
 const {profile,apiKey,fingerprint}=mediaConfiguration(store,kind);let passed=false,response;
 try{
  if(kind==='vision'){
   const data=fs.readFileSync(path.join(__dirname,'test-assets/vision.png'));
   response=await meteredCall({rpc,profile,apiKey,kind:'test_vision',request:{system:'Inspect the supplied pixels. Return only JSON: {"color":"one English color name"}.',user:'What is the dominant color of this image?',images:[{message_id:'synthetic',media_index:0,data_url:`data:image/png;base64,${data.toString('base64')}`}],max_tokens:256}});
   try{passed=JSON.parse(response.result.replace(/^```(?:json)?\s*|\s*```$/g,'').trim()).color?.toLowerCase()==='blue';}catch{}
  }else{
   response=await meteredCall({rpc,profile,apiKey,kind:'test_speech',data:fs.readFileSync(path.join(__dirname,'test-assets/speech.wav')),mime:'audio/wav',filename:'synthetic.wav'});
   passed=/seven[\s,.-]*four[\s,.-]*two|7[\s,.-]*4[\s,.-]*2/i.test(response.result);
  }
  store.recordMediaTest(kind,fingerprint,{ok:passed,message:passed?'真实媒体识别测试通过':'接口已返回，但未通过合成内容识别校验'});
  return {ok:passed,usage:response.usage,attempt:response.attempt,pricing:response.pricing,message:passed?'真实媒体识别测试通过，调用已记入用量账本。':'接口已返回，但未通过识别校验；调用已记录，不能视为能力验证成功。',settings:store.publicValue()};
 }catch(error){store.recordMediaTest(kind,fingerprint,{ok:false,message:error.message});throw error;}
}
module.exports={transcribe,wavSeconds,mediaConfiguration,meteredCall,testMedia};
