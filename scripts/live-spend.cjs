// The cap belongs to this acceptance run, not other programs sharing the API account.
function begin(observed,saved){
 if(observed.unit!==saved.unit)throw Object.assign(new Error('Billing unit changed'),{code:'BILLING_UNIT_CHANGED'});
 if(Number.isFinite(saved.last_meter_used)&&observed.used<saved.last_meter_used)throw Object.assign(new Error('Counter reset'),{code:'BILLING_COUNTER_RESET'});
 const state={...saved};
 if(saved.run_open===false&&Number.isFinite(saved.last_meter_used))state.baseline_used+=observed.used-saved.last_meter_used;
 state.owned_spend=Math.max(state.owned_spend||0,observed.used-state.baseline_used);
 state.last_meter_used=observed.used;state.run_open=true;return state;
}
function settle(observed,state){
 if(observed.unit!==state.unit||observed.used<state.last_meter_used)throw Object.assign(new Error('Billing changed'),{code:'BILLING_COUNTER_CHANGED'});
 return {...state,owned_spend:Math.max(state.owned_spend,observed.used-state.baseline_used),last_meter_used:observed.used};
}
module.exports={begin,settle};
