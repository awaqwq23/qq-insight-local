const {generate,modelDescriptor}=require('./model-gateway');
const {configurationFingerprint}=require('./model-capabilities');
const {limitsFor}=require('./model-limits');
const {waitForTokens}=require('./model-rate-limit');
function syntheticRequest(count){
 const messages=Array.from({length:count},(_,i)=>({id:`synthetic-${i}`,sender:`member-${i%13}`,text:`合成讨论 ${i}: 项目资料将在周五提交，请核对分工与截止日期。编号 ${(i*2654435761>>>0).toString(16)}`}));
 return {system:'这是合成容量测试。只返回 JSON：{"first":"第一条消息id","last":"最后一条消息id","count":消息条数}。不要分析内容。',user:JSON.stringify({messages}),max_tokens:512,images:[]};
}
async function testCapacity({store,rpc,profileId,maxMessages=10000,maxTokens=100000,signal,progress=()=>{},generateImpl=generate}){
 if(!Number.isInteger(maxMessages)||maxMessages<1||maxMessages>10000||!Number.isInteger(maxTokens)||maxTokens<2000||maxTokens>2000000)throw new Error('测试上限须为1–10000条、2000–2000000 Token。');
 const original=store.data.modelProfiles.find(p=>p.id===profileId);
 const apiKey=original&&store.getModelApiKey(profileId);
 if(!original?.model||!apiKey)throw new Error('请先保存模型和 API Key。');
 const profile={...original},fingerprint=configurationFingerprint(profile),limits=limitsFor(profile);
 const attempts=[];let spent=0,successful=0,successfulInput=0,measured=false,successfulBytes=0,upper=0,reported=null,reason='测试上限',candidate=Math.min(32,maxMessages);
 // Charge conservative byte bounds even when usage is absent. At most eight calls, no unbounded retries.
 for(let i=0;i<8;i++){
  if(signal?.aborted){reason='已取消';break;}
  const request=syntheticRequest(candidate),estimate=Buffer.byteLength(request.system)+Buffer.byteLength(request.user)+512;
  const reserve=estimate+request.max_tokens;
  if(estimate>1000000){reason='单请求保守预占上限';break;}
  if(spent+reserve>maxTokens){reason='测试 Token 上限';break;}
  if(limits.tpm_tokens&&reserve>limits.tpm_tokens*.8){reason='TPM 安全额度';break;}
  progress(`容量测试：第 ${i+1}/8 次，${candidate} 条合成消息，最多预占 ${reserve} Token`);
  try{await waitForTokens(profile,reserve,signal,progress);}catch{reason='已取消';break;}
  const reservation=await rpc('ai.call.reserve',{model:modelDescriptor(profile),kind:'test_capacity',input_tokens:estimate,output_tokens:512});
  spent+=reserve;
  try{
   const response=await generateImpl({profile,apiKey,request,signal});
   let ok=false;try{const value=JSON.parse(response.result.replace(/^```(?:json)?\s*|\s*```$/g,''));ok=value.first==='synthetic-0'&&value.last===`synthetic-${candidate-1}`&&value.count===candidate;}catch{}
   await rpc('ai.call.settle',{attempt:reservation.attempt,usage:response.usage,state:ok?'completed':'invalid_output'});
   attempts.push({messages:candidate,input_tokens:response.usage?.input_tokens??null,ok});
   if(!ok){reason='合成首尾与条数校验未通过';break;}
   successful=candidate;measured=Number.isInteger(response.usage?.input_tokens);successfulInput=measured?response.usage.input_tokens:estimate;successfulBytes=estimate;
   if(candidate===maxMessages){reason='已达到消息上限';break;}
   candidate=upper?Math.floor((successful+upper)/2):Math.min(maxMessages,candidate*4);
   if(candidate<=successful){reason='已找到成功与失败区间';break;}
  }catch(error){
   await rpc('ai.call.settle',{attempt:reservation.attempt,usage:error.usage,known_not_sent:error.knownNotSent===true,state:signal?.aborted?'cancelled':'failed'});
   attempts.push({messages:candidate,ok:false,code:error.code||'MODEL_ERROR'});
   if(error.contextLimit)reported=error.contextLimit;
   if(error.tpmLimit)limits.tpm_tokens=error.tpmLimit;
   if(error.code!=='MODEL_CONTEXT_LIMIT'){reason=signal?.aborted?'已取消':error.code==='MODEL_RATE_LIMIT'?'触发限流，TPM 不能据此推算为上下文':error.message;break;}
   upper=candidate;candidate=Math.floor((successful+upper)/2);
   reason='已找到成功与失败区间';if(candidate<=successful)break;
  }
 }
 const result={fingerprint,at:new Date().toISOString(),successful_messages:successful,successful_input_tokens:successfulInput,input_measured:measured,successful_request_bytes:successfulBytes,
  failed_messages:upper||null,reported_context_tokens:reported,reason,attempts,reserved_tokens:spent,
  estimated_10000_tokens:successful?Math.ceil(successfulInput/successful*10000):null};
 store.recordCapacityTest(profileId,fingerprint,result,limits.tpm_tokens);
 return {...result,settings:store.publicValue()};
}
module.exports={testCapacity,syntheticRequest};
