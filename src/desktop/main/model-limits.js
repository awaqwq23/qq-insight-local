// Limits are scoped to the endpoint and model. Unknown aliases must never inherit a family limit.
const {configurationFingerprint}=require('./model-capabilities');
const MAX=10000000;
const MAX_OUTPUT=1000000,RECOMMENDED_OUTPUT=65536;
function number(value,min=1,max=MAX){return Number.isInteger(value)&&value>=min&&value<=max?value:null;}
function metadataLimits(metadata={}){
 const context=number(metadata.context_length)||number(metadata.context_window)||number(metadata.max_context_tokens)||number(metadata.max_input_tokens);
 const output=number(metadata.max_output_tokens,512,MAX_OUTPUT)||number(metadata.max_completion_tokens,512,MAX_OUTPUT)||number(metadata.top_provider?.max_completion_tokens,512,MAX_OUTPUT);
 return context?{context_tokens:context,...(output?{output_limit_tokens:output,output_tokens:Math.min(RECOMMENDED_OUTPUT,output,Math.floor(context/4))}:{}),source:'模型接口元数据',basis:'metadata'}:null;
}
function officialLimits(profile){
 let host;try{host=new URL(profile.baseUrl).hostname;}catch{return null;}
 if(host==='api.openai.com'&&profile.model==='gpt-5.6-sol')return {context_tokens:1050000,source:'https://developers.openai.com/api/docs/models/gpt-5.6-sol',basis:'official',verified_at:'2026-10-13'};
 if(['api.minimaxi.com','api.minimax.io','api.minimax.cn'].includes(host)&&profile.model==='MiniMax-M3')return {context_tokens:1000000,source:'https://platform.minimax.io/docs/api-reference/text-openai-api',basis:'official',verified_at:'2026-10-13'};
 if((host==='dashscope.aliyuncs.com'||/^[a-z0-9-]+\.cn-beijing\.maas\.aliyuncs\.com$/.test(host))&&['deepseek-v4-pro','deepseek-v4-pro-0813'].includes(profile.model))
  return {context_tokens:1000000,source:'https://help.aliyun.com/zh/model-studio/deepseek-v4-pro',basis:'official',verified_at:'2026-10-12'};
 if(host==='api.deepseek.com'&&['deepseek-flash','deepseek-v4-pro'].includes(profile.model))
  return {context_tokens:1000000,output_limit_tokens:393216,source:'https://api-docs.deepseek.com/api/create-chat-completion/',basis:'official',verified_at:'2026-10-25'};
 return null;
}
function limitsFor(profile){
 const base=officialLimits(profile)||{context_tokens:32768,source:'未知模型：暂用保守额度，可手填或测试',basis:'fallback'};
 const saved=profile.limits||{};
 const test=saved.test?.fingerprint===configurationFingerprint(profile)?saved.test:null;
 const context=number(saved.context_tokens,2048)||base.context_tokens;
 const tpm=number(saved.tpm_tokens)||0;
 const outputLimit=Math.min(base.output_limit_tokens||MAX_OUTPUT,number(saved.output_limit_tokens,512,MAX_OUTPUT)||MAX_OUTPUT);
 const output=Math.min(number(saved.output_tokens,512,MAX_OUTPUT)||Math.min(RECOMMENDED_OUTPUT,Math.floor(context/4)),outputLimit,context-1024);
 const input=Math.max(0,Math.min(context-output-1024,tpm?Math.floor(tpm*.8)-output:MAX));
 const observed=test?.successful_request_bytes>8192?test.successful_request_bytes:null;
 return {...base,...saved,test,context_tokens:context,tpm_tokens:tpm,output_tokens:output,output_limit_tokens:outputLimit,
  input_tokens:Math.floor(Math.min(input,observed>0?observed*.8:MAX)),
  recommended_messages:Math.max(1,Math.min(10000,Math.floor((Math.min(input,observed>0?observed*.8:MAX)-4096)/256),test?.successful_messages?Math.floor(test.successful_messages*.8):10000)),
  source:saved.source||base.source,basis:saved.basis||base.basis};
}
function validateLimits(raw={}){
 const result={};
 for(const [key,min,max] of [['context_tokens',2048,MAX],['tpm_tokens',0,MAX],['output_tokens',512,MAX_OUTPUT],['output_limit_tokens',512,MAX_OUTPUT]]){
  if(raw[key]!==undefined){if(number(raw[key],min,max)===null)throw new Error('上下文、TPM 或输出额度超出允许范围。');result[key]=raw[key];}
 }
 return {...result,source:'手动设置',basis:'manual'};
}
module.exports={limitsFor,metadataLimits,officialLimits,validateLimits,MAX_OUTPUT,RECOMMENDED_OUTPUT};
