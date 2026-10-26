const {configurationFingerprint}=require('./model-capabilities');
const {limitsFor}=require('./model-limits');
const windows=new Map();
async function waitForTokens(profile,tokens,signal,progress=()=>{}){
 const tpm=limitsFor(profile).tpm_tokens;if(!tpm)return;
 const cap=Math.floor(tpm*.8);
 if(tokens>cap)throw Object.assign(new Error('本段请求超过 TPM 安全额度，请降低读取量或输出额度。'),{knownNotSent:true,code:'MODEL_RATE_LIMIT'});
 const key=configurationFingerprint(profile);
 let announced=false;
 while(true){
  if(signal?.aborted)throw Object.assign(new Error('已取消。'),{knownNotSent:true});
  const now=Date.now(),entries=(windows.get(key)||[]).filter(item=>now-item.at<60000);
  windows.set(key,entries);
  if(entries.reduce((sum,item)=>sum+item.tokens,0)+tokens<=cap){entries.push({at:now,tokens});return;}
  const delay=Math.max(1,60000-(now-entries[0].at));if(!announced){progress(`等待 TPM 额度恢复，约 ${Math.ceil(delay/1000)} 秒…`);announced=true;}
  await new Promise((resolve,reject)=>{const done=()=>{clearTimeout(timer);signal?.removeEventListener('abort',abort);resolve();};const abort=()=>{clearTimeout(timer);signal?.removeEventListener('abort',abort);reject(Object.assign(new Error('已取消。'),{knownNotSent:true}));};const timer=setTimeout(done,Math.min(delay,1000));signal?.addEventListener('abort',abort,{once:true});});
 }
}
module.exports={waitForTokens};
