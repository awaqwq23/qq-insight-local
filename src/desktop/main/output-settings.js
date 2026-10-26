const {limitsFor,validateLimits}=require('./model-limits');

// Both editors save one output preference; roll back the budget if the profile cannot persist.
function createOutputSettings({store,rpc}){
 let pending=Promise.resolve();
 const enqueue=action=>{const result=pending.then(action);pending=result.catch(()=>{});return result;};
 function validate(profile,output){
  validateLimits({output_tokens:output});
  if(!profile?.model)return;
  const limits=limitsFor(profile),maximum=Math.min(limits.output_limit_tokens,limits.context_tokens-1024);
  if(output>maximum)throw new Error(`输出额度超过当前模型/上下文允许的 ${maximum.toLocaleString('zh-CN')} Token，请降低输出或核对模型容量。`);
 }
 async function save(input,budgetSettings){
  const profile=input?.modelProfile;
  const current=store.data.modelProfiles.find(p=>p.id===store.data.activeModelProfileId);
  const existing=profile&&store.data.modelProfiles.find(p=>p.id===profile.id);
  const target=profile?{...existing,...profile,limits:{...existing?.limits,...profile.limits}}:current;
  const output=profile?.limits?.output_tokens??budgetSettings?.output_tokens;
  if(output===undefined)return input?store.save(input):rpc('ai.budget.save',{settings:budgetSettings});
  validate(target,output);
  const beforeBudget=await rpc('ai.budget.get'),changed={...(budgetSettings||{}),output_tokens:output};
  const budget=await rpc('ai.budget.save',{settings:changed});
  const before=structuredClone(store.data);
  try{
   if(input)store.save(input);
   else if(current?.model)store.save({modelProfile:{id:current.id,name:current.name,provider:current.provider,baseUrl:current.baseUrl,model:current.model,protocol:current.protocol||'chat',limits:{...current.limits,output_tokens:output}}});
  }catch(error){
   store.data=before;
   try{await rpc('ai.budget.save',{settings:Object.fromEntries(Object.keys(changed).map(key=>[key,beforeBudget[key]]))});}
   catch{throw new Error('输出设置保存失败，预算回滚也未完成，请重新读取设置后重试。');}
   throw error;
  }
  if(input)return store.publicValue();
  const saved=current?.model?store.publicValue().modelProfiles.find(p=>p.id===current.id):null;
  return {...budget,model_output:saved?{profile_id:saved.id,model:saved.model,baseUrl:saved.baseUrl,limits:saved.limits}:null};
 }
 return {saveBudget:settings=>enqueue(()=>save(null,settings)),saveSettings:input=>enqueue(()=>save(input||{},null))};
}
module.exports={createOutputSettings};
