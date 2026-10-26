const assert=require('node:assert/strict');
const fs=require('node:fs');const os=require('node:os');const path=require('node:path');
const {SettingsStore}=require('../src/desktop/main/settings-store');
const {limitsFor,metadataLimits,validateLimits}=require('../src/desktop/main/model-limits');
const {testCapacity}=require('../src/desktop/main/model-capacity-test');
const {waitForTokens}=require('../src/desktop/main/model-rate-limit');
const {generate}=require('../src/desktop/main/model-gateway');
async function main(){
 assert.equal(metadataLimits({context_length:128000}).context_tokens,128000);
 assert.equal(metadataLimits({context_length:'unknown'}),null);
 const official={id:'test',provider:'openai-compatible',baseUrl:'https://dashscope.aliyuncs.com/compatible-mode/v1',model:'deepseek-v4-pro-0813'};
 assert.equal(limitsFor(official).context_tokens,1000000);
 assert.equal(limitsFor({...official,baseUrl:'https://example.test/v1'}).basis,'fallback');
 const deepseek={model:'deepseek-flash',baseUrl:'https://api.deepseek.com/v1'};
 assert.equal(limitsFor(deepseek).output_tokens,65536);
 assert.equal(limitsFor({...deepseek,limits:{output_tokens:1000000}}).output_tokens,393216);
 assert.equal(limitsFor({...deepseek,limits:{output_tokens:131072}}).output_tokens,131072);
 assert.equal(limitsFor({...deepseek,limits:{output_tokens:4096}}).output_tokens,4096,'preserve an explicitly saved smaller value');
 assert.equal(limitsFor({baseUrl:'https://example.test',model:'unknown'}).output_tokens,8192);
 assert.equal(limitsFor({...deepseek,limits:{context_tokens:32768,output_tokens:65536}}).output_tokens,31744);
 assert.equal(validateLimits({output_tokens:65536}).output_tokens,65536);
 assert.throws(()=>validateLimits({output_tokens:1000001}));
 assert.equal(metadataLimits({context_length:1000000,max_output_tokens:32768}).output_limit_tokens,32768);
 const folder=fs.mkdtempSync(path.join(os.tmpdir(),'capacity-test-'));
 try{
 const store=new SettingsStore({getPath:()=>folder},{isEncryptionAvailable:()=>true,encryptString:value=>Buffer.from(value),decryptString:value=>value.toString()});
 store.save({modelProfile:{...official,apiKey:'synthetic-key',limits:{context_tokens:1000000,tpm_tokens:0,output_tokens:4096}}});
 const calls=[];
 const rpc=async(method,input)=>{calls.push({method,input});return {attempt:'synthetic-'+calls.length};};
 const generateImpl=async({request})=>{const messages=JSON.parse(request.user).messages;return {result:JSON.stringify({first:messages[0].id,last:messages.at(-1).id,count:messages.length}),usage:{input_tokens:messages.length*50,output_tokens:30}};};
 const result=await testCapacity({store,rpc,profileId:'test',maxMessages:10000,maxTokens:100000,generateImpl});
 assert.ok(result.successful_messages>0);assert.ok(result.reserved_tokens<=100000);assert.ok(result.attempts.length<=8);
 assert.equal(calls.filter(c=>c.method==='ai.call.reserve').length,calls.filter(c=>c.method==='ai.call.settle').length);
 const unknown=await testCapacity({store,rpc,profileId:'test',maxMessages:32,maxTokens:10000,generateImpl:async input=>{const result=await generateImpl(input);result.usage={};return result;}});
 assert.equal(unknown.input_measured,false);assert.equal(unknown.attempts[0].input_tokens,null);
 assert.equal(store.publicValue().modelProfiles.find(p=>p.id==='test').limits.test.successful_messages,unknown.successful_messages);
 const bounded=await testCapacity({store,rpc,profileId:'test',maxMessages:128,maxTokens:100000,generateImpl:async input=>{
  const count=JSON.parse(input.request.user).messages.length;if(count>40)throw Object.assign(new Error('bounded'),{code:'MODEL_CONTEXT_LIMIT',contextLimit:9000});return generateImpl(input);
 }});
 assert.ok(bounded.successful_messages>=38&&bounded.successful_messages<=40);assert.ok(bounded.failed_messages>bounded.successful_messages);assert.equal(bounded.reported_context_tokens,9000);
 const rate=await testCapacity({store,rpc,profileId:'test',maxMessages:64,maxTokens:100000,generateImpl:async()=>{throw Object.assign(new Error('rate'),{code:'MODEL_RATE_LIMIT',tpmLimit:20000});}});
 assert.equal(rate.reported_context_tokens,null);assert.equal(rate.failed_messages,null);assert.match(rate.reason,/限流/);
 const controller=new AbortController();controller.abort();const before=calls.length;
 await testCapacity({store,rpc,profileId:'test',maxTokens:10000,signal:controller.signal,generateImpl});assert.equal(calls.length,before);
 store.save({modelProfile:{...official,model:'other',apiKey:'synthetic-other'}});
 assert.equal(store.publicValue().modelProfiles.find(p=>p.id==='test').limits.test,null);
 const request={system:'synthetic',user:'synthetic',max_tokens:512};
 await assert.rejects(generate({profile:official,apiKey:'synthetic',request,fetchImpl:async()=>new Response(JSON.stringify({error:{message:'maximum context length is 8192. synthetic secret'}}),{status:400})}),e=>e.code==='MODEL_CONTEXT_LIMIT'&&e.contextLimit===8192&&!e.message.includes('secret'));
 await assert.rejects(generate({profile:official,apiKey:'synthetic',request,fetchImpl:async()=>new Response(JSON.stringify({error:{message:'TPM limit: 20000. synthetic secret'}}),{status:429})}),e=>e.code==='MODEL_RATE_LIMIT'&&e.tpmLimit===20000);
 const small={...official,limits:{tpm_tokens:1000}};await waitForTokens(small,600);
 const abort=new AbortController();const pending=waitForTokens(small,600,abort.signal);abort.abort();await assert.rejects(pending);
 console.log('Model limits passed: endpoint metadata, bounded probe, context interval, TPM separation, ledger, cancellation, stale result and redaction.');
 }finally{fs.rmSync(folder,{recursive:true,force:true});}
}
main().catch(error=>{console.error(error);process.exitCode=1;});
