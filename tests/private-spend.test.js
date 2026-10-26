const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {createGuard,requestBound,measuredBound}=require('../scripts/private-spend.cjs');
(async()=>{
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'private-spend-')),file=path.join(folder,'cost.json');let value=20;
 try{
  const guard=createGuard({file,balance:async()=>value}),request={system:'合成',user:'材料',max_tokens:65536};
  const one=await guard.reserve(request,'synthetic');assert.ok(one.cost_upper>.5);
  await guard.settle(one,{input_tokens:1000,output_tokens:1000,request_started_at:'2026-10-26T01:00:00+08:00'});assert.equal(guard.owned(),.005);
  const two=await guard.reserve(request,'unknown');await guard.settle(two,{});assert.equal(two.state,'unknown');assert.ok(guard.owned()>.5);
  const restored=createGuard({file,balance:async()=>value});assert.equal(restored.owned(),guard.owned());
  value=15.3;await assert.rejects(restored.reserve(request,'blocked'),e=>e.code==='PRIVATE_COST_LIMIT'&&e.knownNotSent);
  assert.equal(restored.state.requests.length,2);
  assert.ok(Math.abs(requestBound({...request,images:[{},{}]})-requestBound(request)-.004096)<1e-12);
  assert.equal(measuredBound({input_tokens:1000000,output_tokens:1000000,request_started_at:'2026-10-26T10:00:00+08:00'}),10);
  let offline=false;const settled=createGuard({file:path.join(folder,'post-send.json'),balance:async()=>{if(offline)throw new Error('offline');return 20;}});
  const paid=await settled.reserve(request,'paid');offline=true;await settled.settle(paid,{input_tokens:100,output_tokens:10,request_started_at:'2026-10-26T10:00:00+08:00'});
  assert.equal(paid.state,'measured_upper');assert.ok(settled.owned()>0);await assert.rejects(settled.reserve(request,'blocked'),e=>e.knownNotSent&&e.code==='BALANCE_UNAVAILABLE');
  console.log('Private 5 CNY spend guard passed: pre-send reservation, unknown charge retention, restart, shared-account decrease and image bound.');
 }finally{assert.equal(path.dirname(path.resolve(folder)),path.resolve(os.tmpdir()));fs.rmSync(folder,{recursive:true,force:true});}
})().catch(e=>{console.error(e);process.exitCode=1;});
