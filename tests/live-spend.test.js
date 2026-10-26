const assert=require('node:assert/strict');const {begin,settle}=require('../scripts/live-spend.cjs');
const initial={unit:'USD',baseline_used:100,owned_spend:24,last_meter_used:124,run_open:false,limit:30};
const opened=begin({unit:'USD',used:174},initial);assert.equal(opened.owned_spend,24);assert.equal(opened.baseline_used,150);
const charged=settle({unit:'USD',used:176},opened);assert.equal(charged.owned_spend,26);
const active=begin({unit:'USD',used:179},charged);assert.equal(active.owned_spend,29);assert.equal(active.baseline_used,150);
assert.throws(()=>begin({unit:'CNY',used:179},initial));assert.throws(()=>begin({unit:'USD',used:120},initial));
console.log('Live spend guard passed: idle shared-account use excluded, active-period changes counted, currency and counter resets blocked.');
