// Only the user's explicitly authorized MiniMax subscription; never switch to balance keys.
const fs=require('node:fs');
let cachedQuota;
async function readQuota(apiKey){
 if(cachedQuota?.key===apiKey&&Date.now()-cachedQuota.at<10000&&cachedQuota.value.window_remaining>=20&&cachedQuota.value.week_remaining>=10)return cachedQuota.value;
 try{
 let response;
 for(let attempt=0;attempt<2;attempt++){
  try{response=await fetch('https://www.minimax.cn/v1/token_plan/remains',{headers:{Authorization:'Bearer '+apiKey},redirect:'error',signal:AbortSignal.timeout(25000)});break;}
  catch(error){if(attempt)throw error;await new Promise(resolve=>setTimeout(resolve,500));}
 }
 if(!response.ok)throw Object.assign(new Error('订阅额度查询失败，未继续推理。'),{code:'SUBSCRIPTION_QUOTA_UNAVAILABLE',knownNotSent:true});
 const data=await response.json(),q=data.model_remains?.find(r=>r.model_name==='general');
 if(data.base_resp?.status_code!==0||!q)throw Object.assign(new Error('无法确认可用订阅。'),{code:'SUBSCRIPTION_QUOTA_UNAVAILABLE',knownNotSent:true});
 const value={window_remaining:q.current_interval_remaining_percent,week_remaining:q.current_weekly_remaining_percent,window_end:q.end_time,week_end:q.weekly_end_time};cachedQuota={key:apiKey,at:Date.now(),value};return value;
 }catch(error){error.code='SUBSCRIPTION_QUOTA_UNAVAILABLE';error.knownNotSent=true;throw error;}
}
function createGuard({file,quota}){
 const state=fs.existsSync(file)?JSON.parse(fs.readFileSync(file,'utf8')):{billing_mode:'subscription',source:'https://platform.minimax.cn/docs/m-plan/faq',requests:[]};
 const persist=()=>fs.writeFileSync(file,JSON.stringify(state,null,2));
 async function observe(){const q=await quota();if(!Number.isFinite(q.window_remaining)||!Number.isFinite(q.week_remaining))throw Object.assign(new Error('无法确认订阅额度，未继续调用。'),{code:'SUBSCRIPTION_QUOTA_UNAVAILABLE',knownNotSent:true});state.quota=q;persist();return q;}
 return {state,owned:()=>0,
  async reserve(request,label){
   const q=await observe();
   if(q.window_remaining<10||q.week_remaining<5)throw Object.assign(new Error('订阅额度接近保护线，停止调用，避免转入额外积分。'),{code:'SUBSCRIPTION_QUOTA_LIMIT',knownNotSent:true});
   const entry={case:label,state:'reserved'};state.requests.push(entry);persist();return entry;
  },
  async settle(entry,usage,notSent=false){entry.state=notSent?'not_sent':Number.isInteger(usage?.input_tokens)&&Number.isInteger(usage?.output_tokens)?'measured':'unknown';if(usage){entry.input_tokens=usage.input_tokens;entry.output_tokens=usage.output_tokens;}persist();try{await observe();}catch{state.last_quota_refresh_failed=true;persist();}}
 };
}
module.exports={createGuard,readQuota};
