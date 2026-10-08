const assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {SettingsStore}=require('../src/desktop/main/settings-store');
const {capability,configurationFingerprint}=require('../src/desktop/main/model-capabilities');
const {officialPrice}=require('../src/desktop/main/official-pricing');
const {transcribe,meteredCall,wavSeconds}=require('../src/desktop/main/media-gateway');
async function main(){
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'qq-media-unit-'));
 const store=new SettingsStore({getPath:()=>dir},{isEncryptionAvailable:()=>true,encryptString:s=>Buffer.from(s),decryptString:b=>b.toString()});
 const current=store.data.activeModelProfileId;
 store.save({mediaProfile:{kind:'vision',baseUrl:'https://example.test/v1',model:'qwen-vl-plus',apiKey:'synthetic-vision'}});
 store.save({mediaProfile:{kind:'speech',baseUrl:'https://example.test/v1',model:'whisper-1',protocol:'transcription',apiKey:'synthetic-speech'}});
 assert.equal(store.getMediaApiKey('vision'),'synthetic-vision');assert.equal(store.getMediaApiKey('speech'),'synthetic-speech');
 assert.equal(store.data.activeModelProfileId,current);assert.ok(!JSON.stringify(store.publicValue()).includes('synthetic-vision'));
 const fp=configurationFingerprint(store.data.mediaProfiles.vision);store.recordMediaTest('vision',fp,{ok:true});assert.ok(store.publicValue().mediaProfiles.vision.test.ok);
 store.save({mediaProfile:{kind:'vision',baseUrl:'https://example.test/v1',model:'qwen-vl-max'}});assert.equal(store.publicValue().mediaProfiles.vision.test,null);
 store.recordMediaTest('vision',fp,{ok:true});assert.equal(store.publicValue().mediaProfiles.vision.test,null);
 assert.ok(capability('qwen-vl-plus').vision);assert.ok(capability('custom',{input_modalities:['image']}).vision);
 assert.ok(capability('gpt-4o-mini-transcribe').speech);assert.ok(capability('qwen3-asr-flash-2026-02-10').speech);
 for(const id of ['qwen3-asr-flash-realtime','qwen3-asr-flash-filetrans','gpt-image-1','deepseek-v3'])assert.ok(!capability(id).vision&&!capability(id).speech);
 assert.equal(officialPrice({baseUrl:'https://proxy.example.test/v1',model:'gpt-4o-mini'}),null);
 assert.equal(officialPrice({baseUrl:'https://dashscope-intl.aliyuncs.com/compatible-mode/v1',model:'qwen-vl-plus'}),null);
 const price=officialPrice({baseUrl:'https://dashscope.aliyuncs.com/compatible-mode/v1',model:'deepseek-v4-pro-0813'});
 assert.equal(price.input_price,9);assert.equal(price.off_peak.input_price,4.5);
 const data=fs.readFileSync(path.join(__dirname,'../src/desktop/main/test-assets/speech.wav'));assert.ok(wavSeconds(data)>1);
 const profile={provider:'openai-compatible',baseUrl:'https://example.test/v1',model:'qwen3-asr-flash',protocol:'qwen-asr'};
 let result=await transcribe({profile,apiKey:'synthetic',data,fetchImpl:async(url,init)=>{
  assert.ok(url.endsWith('/chat/completions'));const body=JSON.parse(init.body);assert.equal(body.messages.length,1);assert.ok(body.messages[0].content[0].input_audio.data.startsWith('data:audio/wav;base64,'));
  return new Response(JSON.stringify({choices:[{message:{content:'synthetic'},finish_reason:'stop'}],usage:{seconds:2,prompt_tokens:8,completion_tokens:3}}));
 }});assert.equal(result.usage.seconds,2);
 result=await transcribe({profile:{...profile,model:'whisper-1',protocol:'transcription'},apiKey:'synthetic',data,fetchImpl:async(url,init)=>{
  assert.ok(url.endsWith('/audio/transcriptions'));assert.equal(init.body.get('response_format'),'verbose_json');return new Response(JSON.stringify({text:'synthetic',duration:2}));
 }});assert.equal(result.usage.input_tokens,undefined);assert.equal(result.usage.seconds,2);
 await assert.rejects(()=>transcribe({profile,apiKey:'synthetic',data,fetchImpl:async()=>new Response('sensitive echoed body',{status:401})}),error=>!error.message.includes('sensitive')&&error.message.includes('401'));
 const calls=[];const rpc=async(method,params)=>{calls.push({method,params});return {attempt:'synthetic'};};
 await assert.rejects(()=>meteredCall({rpc,profile,apiKey:'synthetic',kind:'test_speech',data,transcribeImpl:async()=>{throw new Error('synthetic failure');}}));
 assert.deepEqual(calls.map(c=>c.method),['ai.call.reserve','ai.call.settle']);assert.equal(calls[1].params.state,'failed');
 console.log('Media API passed: independent secrets, stale tests, capability filters, provider prices, audio protocols, failure ledger.');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
