// Official model-price references apply to every endpoint; reseller bills may differ.
const VERIFIED='2026-10-13';
const ALI='https://help.aliyun.com/zh/model-studio/model-pricing';
const OPENAI='https://developers.openai.com/api/docs/pricing';
const DEEPSEEK='https://api-docs.deepseek.com/zh-cn/quick_start/pricing/';
const MINIMAX='https://platform.minimax.cn/docs/guides/pricing-paygo';
const CLAUDE='https://platform.claude.com/docs/en/about-claude/pricing';
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
 'gpt-5.6-sol':{input_price:4,output_price:20,cached_input_price:0.4,cache_write_price:5,long_context:{threshold:272000,input_price:8,output_price:30,cached_input_price:0.8,cache_write_price:10}},
 'gpt-6-astra':{input_price:10,output_price:50,cached_input_price:1,cache_write_price:12.5,long_context:{threshold:272000,input_price:20,output_price:75,cached_input_price:2,cache_write_price:25}},
 'gpt-6.1-sol':{input_price:2,output_price:10,cached_input_price:0.1,cache_write_price:2.5,long_context:{threshold:272000,input_price:4,output_price:15,cached_input_price:0.2,cache_write_price:5}},
 'gpt-6-luna':{input_price:0.1,output_price:0.5,cached_input_price:0.01,cache_write_price:0.125,long_context:{threshold:272000,input_price:0.2,output_price:0.75,cached_input_price:0.02,cache_write_price:0.25}},
 'gpt-5.3-codex':{input_price:1.75,output_price:14,cached_input_price:0.175},
 'gpt-4o-mini':{input_price:0.15,output_price:0.6,cached_input_price:0.075},
 'gpt-4o':{input_price:2.5,output_price:10,cached_input_price:1.25},
 'gpt-4o-mini-transcribe':{input_price:1.25,output_price:5},
 'gpt-4o-transcribe':{input_price:2.5,output_price:10},
 'whisper-1':{unit:'second',second_price:0.006/60},
};
const deepseek={
 'deepseek-v4-pro':{input_price:9,output_price:27,cached_input_price:0.3,time_schedule:'deepseek_beijing',off_peak:{input_price:4.5,output_price:13.5,cached_input_price:0.15}},
 'deepseek-flash':{input_price:2,output_price:8,cached_input_price:0.04,time_schedule:'deepseek_beijing',off_peak:{input_price:1,output_price:4,cached_input_price:0.02}},
};
const minimax={
 'MiniMax-M3':{input_price:2.1,output_price:8.4,cached_input_price:0.42,long_context:{threshold:512000,input_price:4.2,output_price:16.8,cached_input_price:0.84}},
 'MiniMax-M2.7':{input_price:2.1,output_price:8.4,cached_input_price:0.42,cache_write_price:2.625},
 'MiniMax-M2.7-highspeed':{input_price:4.2,output_price:16.8,cached_input_price:0.42,cache_write_price:2.625},
 'MiniMax-M2.5':{input_price:2.1,output_price:8.4,cached_input_price:0.21,cache_write_price:2.625},
 'MiniMax-M2.5-highspeed':{input_price:4.2,output_price:16.8,cached_input_price:0.21,cache_write_price:2.625},
 'MiniMax-M2.1':{input_price:2.1,output_price:8.4,cached_input_price:0.21,cache_write_price:2.625},
 'MiniMax-M2':{input_price:2.1,output_price:8.4,cached_input_price:0.21},
};
const claude={
 'claude-opus-5-5':{input_price:4,output_price:20,cached_input_price:0.2},
 'claude-sonnet-5-5':{input_price:2,output_price:10,cached_input_price:0.1},
 'claude-haiku-5-5':{input_price:0.1,output_price:0.5,cached_input_price:0.01,long_context:{threshold:100000,input_price:0.5,output_price:2.5,cached_input_price:0.05,cache_write_price:0.625,cache_write_1h_price:1}},
 'claude-opus-5':{input_price:5,output_price:25,cached_input_price:0.5},
 'claude-sonnet-5':{input_price:2,output_price:10,cached_input_price:0.2},
 'claude-opus-4-8':{input_price:5,output_price:25,cached_input_price:0.5},
 'claude-opus-4-7':{input_price:5,output_price:25,cached_input_price:0.5},
 'claude-opus-4-6':{input_price:5,output_price:25,cached_input_price:0.5},
 'claude-sonnet-4-6':{input_price:3,output_price:15,cached_input_price:0.3},
 'claude-haiku-4-5':{input_price:1,output_price:5,cached_input_price:0.1},
};
const aliases={'deepseek-v4-pro-0813':'deepseek-v4-pro','deepseek-v4-flash':'deepseek-flash','deepseek-v4-flash-vision-exp':'deepseek-flash','gpt-5.6':'gpt-5.6-sol'};
function officialPrice(profile){
 try{new URL(profile?.baseUrl);}catch{return null;}
 const model=aliases[profile.model]||Object.keys(minimax).find(id=>id.toLowerCase()===String(profile.model).toLowerCase())||profile.model;
 let record,provider,currency,region,source;
 if(deepseek[model]){record=deepseek[model];provider='DeepSeek';currency='CNY';source=DEEPSEEK;region='官方人民币价';}
 else if(openai[model]){record=openai[model];provider='OpenAI';currency='USD';source=OPENAI;region='标准API';}
 else if(minimax[model]){record=minimax[model];provider='MiniMax';currency='CNY';source=MINIMAX;region='中国标准API';}
 else if(claude[model]){record=claude[model];provider='Anthropic';currency='USD';source=CLAUDE;region='全球标准API';record={cache_write_price:record.input_price*1.25,cache_write_1h_price:record.input_price*2,...record};}
 else if(ali[model]){record=ali[model];provider='阿里云百炼';currency='CNY';region='华北2（北京）参考价';source=ALI;}
 if(!record)return null;
 return {unit:'token',provider,currency,region,source,verified_at:provider==='阿里云百炼'?'2026-10-01':VERIFIED,basis:'official',model,
  reference_only:true,note:'按模型官方价估算，非服务商实际账单',...record};
}
function officialPriceCatalog(){return Object.fromEntries([...new Set([...Object.keys(ali),...Object.keys(openai),...Object.keys(deepseek),...Object.keys(minimax),...Object.keys(claude),...Object.keys(aliases),...Object.keys(minimax).map(id=>id.toLowerCase())])].map(model=>[model,officialPrice({baseUrl:'https://example.test/v1',model})]));}
module.exports={officialPrice,officialPriceCatalog};
