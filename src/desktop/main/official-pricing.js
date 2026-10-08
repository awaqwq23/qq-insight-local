// Official list-price snapshot. Never apply origin-provider rates to reseller endpoints.
const VERIFIED='2026-10-01';
const ALI='https://help.aliyun.com/zh/model-studio/model-pricing';
const OPENAI='https://developers.openai.com/api/docs/pricing';
const ali={
 'deepseek-v4-pro':{input_price:12,output_price:24,cached_input_price:1,source:'https://help.aliyun.com/zh/model-studio/deepseek-v4-pro'},
 'deepseek-v4-pro-0813':{input_price:9,output_price:27,cached_input_price:0.9,time_schedule:'beijing_08_22',off_peak:{input_price:4.5,output_price:13.5,cached_input_price:0.45},cache_source:'https://help.aliyun.com/zh/model-studio/deepseek-v4-pro'},
 'deepseek-v3':{input_price:2,output_price:8,cached_input_price:0.4,source:'https://help.aliyun.com/zh/model-studio/deepseek-v3'},
 'deepseek-v3.2':{input_price:2,output_price:3,cached_input_price:0.4},
 'qwen-vl-plus':{input_price:0.8,output_price:2,cached_input_price:0.16},
 'qwen-vl-max':{input_price:1.6,output_price:4,cached_input_price:0.32},
 'qwen3-asr-flash':{unit:'second',second_price:0.00022},
 'qwen3-asr-flash-2025-09-08':{unit:'second',second_price:0.00022},
 'qwen3-asr-flash-2026-02-10':{unit:'second',second_price:0.00022},
};
const openai={
 'gpt-4o-mini':{input_price:0.15,output_price:0.6,cached_input_price:0.075},
 'gpt-4o':{input_price:2.5,output_price:10,cached_input_price:1.25},
 'gpt-4o-mini-transcribe':{input_price:1.25,output_price:5},
 'gpt-4o-transcribe':{input_price:2.5,output_price:10},
 'whisper-1':{unit:'second',second_price:0.006/60},
};
function officialPrice(profile){
 let host;try{host=new URL(profile.baseUrl).hostname.toLowerCase();}catch{return null;}
 let record,provider,currency,region,source;
 if(host==='dashscope.aliyuncs.com'||/^[a-z0-9-]+\.cn-beijing\.maas\.aliyuncs\.com$/.test(host)){
  record=ali[profile.model];provider='阿里云百炼';currency='CNY';region='华北2（北京）';source=ALI;
 }else if(host==='api.openai.com'){
  record=openai[profile.model];provider='OpenAI';currency='USD';region='标准API';source=OPENAI;
 }
 if(!record)return null;
 if(provider==='OpenAI')source='https://developers.openai.com/api/docs/models/'+profile.model;
 return {unit:'token',provider,currency,region,source,verified_at:VERIFIED,basis:'official',...record};
}
module.exports={officialPrice};
