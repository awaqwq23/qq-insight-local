// Cost ceiling for this explicit private acceptance run; no model keys are persisted.
const fs=require('node:fs');
const LIMIT=4.75; // Leave 0.25 CNY below the user's hard 5 CNY ceiling.
function requestBound(request){
 // Official Flash vision guide: at most 1024 input tokens per image (verified 2026-10-26).
 const input=Buffer.byteLength(JSON.stringify({system:request.system,user:request.user}),'utf8')+4096+(request.images?.length||0)*1024;
 return (input*2+request.max_tokens*8)/1000000;
}
function measuredBound(usage){
 if(!Number.isInteger(usage?.input_tokens)||!Number.isInteger(usage?.output_tokens)||usage.input_tokens<0||usage.output_tokens<0)return null;
 const d=new Date(usage.request_started_at||''),parts=Number.isNaN(d.getTime())?null:new Intl.DateTimeFormat('en-US',{timeZone:'Asia/Shanghai',weekday:'short',hour:'numeric',hourCycle:'h23'}).formatToParts(d);
 const hour=parts&&Number(parts.find(p=>p.type==='hour').value),weekday=parts?.find(p=>p.type==='weekday').value;
 const peak=!parts||(!['Sat','Sun'].includes(weekday)&&((hour>=9&&hour<12)||(hour>=14&&hour<18)));
 return (usage.input_tokens*(peak?2:1)+usage.output_tokens*(peak?8:4))/1000000;
}
function createGuard({file,balance}){
 const state=fs.existsSync(file)?JSON.parse(fs.readFileSync(file,'utf8')):{limit_cny:5,reservation_limit_cny:LIMIT,price_source:'https://api-docs.deepseek.com/zh-cn/quick_start/pricing/',verified_at:'2026-10-26',baseline:null,account_decrease:0,requests:[]};
 const persist=()=>fs.writeFileSync(file,JSON.stringify(state,null,2));
 const owned=()=>state.requests.reduce((n,r)=>n+r.cost_upper,0);
 async function observe(){const value=await balance();if(state.baseline===null)state.baseline=value;state.account_decrease=Math.max(state.account_decrease,state.baseline-value,0);persist();return value;}
 return {
  state,owned,
  async reserve(request,label){
   let available;try{available=await observe();}catch(error){error.code='BALANCE_UNAVAILABLE';error.knownNotSent=true;throw error;}
   const bound=requestBound(request),used=Math.max(owned(),state.account_decrease);
   if(used+bound>LIMIT||available<bound)throw Object.assign(new Error('已达到本次5元测试预算保护线，未发送下一请求。'),{code:'PRIVATE_COST_LIMIT',knownNotSent:true});
   const entry={case:label,state:'reserved',cost_upper:bound,reserved:bound};state.requests.push(entry);persist();return entry;
  },
  async settle(entry,usage,notSent=false){
   const measured=measuredBound(usage);entry.cost_upper=notSent?0:measured??entry.reserved;entry.state=notSent?'not_sent':measured===null?'unknown':'measured_upper';
   if(usage){entry.input_tokens=usage.input_tokens??null;entry.output_tokens=usage.output_tokens??null;}
   persist();
   if(entry.cost_upper>entry.reserved+.000001)throw Object.assign(new Error('实际用量超出预占边界，停止后续调用。'),{code:'PRIVATE_COST_BOUND_CHANGED'});
   try{await observe();}catch{state.last_balance_refresh_failed=true;persist();}
  }
 };
}
module.exports={createGuard,requestBound,measuredBound};
