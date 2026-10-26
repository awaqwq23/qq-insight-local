const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),assert=require('node:assert/strict');
const {createGuard}=require('../scripts/subscription-spend.cjs');
(async()=>{
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'subscription-'));let q={window_remaining:28,week_remaining:77};
 try{
  const file=path.join(dir,'quota.json'),guard=createGuard({file,quota:async()=>q});
  const a=await guard.reserve({},'synthetic');await guard.settle(a,{input_tokens:123,output_tokens:45});assert.equal(a.state,'measured');
  const b=await guard.reserve({},'unknown');await guard.settle(b);assert.equal(b.state,'unknown');
  const restored=createGuard({file,quota:async()=>q});assert.equal(restored.state.requests.length,2);
  q={window_remaining:9,week_remaining:77};await assert.rejects(restored.reserve({},'blocked'),e=>e.code==='SUBSCRIPTION_QUOTA_LIMIT');
  q={window_remaining:28,week_remaining:4};await assert.rejects(restored.reserve({},'blocked'),e=>e.code==='SUBSCRIPTION_QUOTA_LIMIT');
  q={};await assert.rejects(restored.reserve({},'unknown'),e=>e.code==='SUBSCRIPTION_QUOTA_UNAVAILABLE');
  assert.equal(restored.state.requests.length,2);console.log('Subscription guard passed: persisted usage, unknown calls, quota floors and no extra requests.');
  let offline=false;const settlement=createGuard({file:path.join(dir,'settle.json'),quota:async()=>{if(offline)throw Object.assign(new Error('quota unavailable'),{knownNotSent:true});return {window_remaining:80,week_remaining:70};}});
  const sent=await settlement.reserve({},'sent');offline=true;
  await settlement.settle(sent,{input_tokens:12,output_tokens:9});
  assert.equal(sent.state,'measured');assert.equal(sent.input_tokens,12);
  assert.equal(settlement.state.last_quota_refresh_failed,true);await assert.rejects(settlement.reserve({},'blocked after paid answer'));
 }finally{assert.equal(path.dirname(dir),path.resolve(os.tmpdir()));fs.rmSync(dir,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
