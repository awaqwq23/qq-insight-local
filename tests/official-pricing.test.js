const assert=require('node:assert/strict');
const {officialPrice,officialPriceCatalog}=require('../src/desktop/main/official-pricing');
for(const baseUrl of ['https://discovery-api.intern-ai.org.cn/v1','https://proxy.example.test/v1','https://api.deepseek.com/v1']){
 const price=officialPrice({baseUrl,model:'deepseek-v4-pro-0813'});
 assert.equal(price.provider,'DeepSeek');assert.equal(price.input_price,9);assert.equal(price.cached_input_price,0.3);assert.equal(price.off_peak.cached_input_price,0.15);assert.equal(price.time_schedule,'deepseek_beijing');assert.equal(price.reference_only,true);
}
const relay=officialPrice({baseUrl:'https://proxy.example.test/v1',model:'gpt-5.6-sol'});
assert.equal(relay.input_price,4);assert.equal(relay.output_price,20);assert.equal(relay.long_context.threshold,272000);assert.equal(relay.long_context.output_price,30);
assert.equal(officialPrice({baseUrl:'https://proxy.example.test/v1',model:'minimax-m3'}).long_context.threshold,512000);
assert.equal(officialPrice({baseUrl:'https://proxy.example.test/v1',model:'claude-opus-5-5'}).cache_write_1h_price,8);
assert.equal(officialPrice({baseUrl:'https://proxy.example.test/v1',model:'claude-haiku-5-5'}).long_context.cache_write_1h_price,1);
assert.equal(officialPrice({baseUrl:'https://proxy.example.test/v1',model:'unknown-gpt-custom'}),null);
assert.equal(officialPrice({baseUrl:'invalid',model:'gpt-5.6-sol'}),null);
const catalog=officialPriceCatalog();assert.equal(catalog['minimax-m3'].input_price,2.1);assert.equal(catalog['gpt-5.6'].model,'gpt-5.6-sol');assert.ok(Object.values(catalog).every(p=>p.source.startsWith('https://')&&p.verified_at));
console.log('Official pricing passed: publisher rates on all endpoints, explicit aliases, cached tokens, long context and unknown models.');
