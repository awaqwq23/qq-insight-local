// Explicit opt-in. Only the already configured DeepSeek key is decrypted, in memory.
const {app,safeStorage}=require('electron');
const fs=require('node:fs'),path=require('node:path');
if(!process.argv.includes('--run')){console.log('EXPLICIT_RUN_REQUIRED');app.exit(1);}
const root=path.resolve(__dirname,'..'),base=path.join(root,'data/private-acceptance');
const directory=JSON.parse(fs.readFileSync(path.join(base,'latest.json'),'utf8')).directory;
if(!path.resolve(directory).startsWith(base+path.sep))throw new Error('PRIVATE_DIRECTORY_INVALID');
const actual=path.join(app.getPath('appData'),'qq-insight-local'),auth=path.join(directory,'.auth');
fs.mkdirSync(auth,{recursive:true});
fs.writeFileSync(path.join(auth,'Local State'),JSON.stringify({os_crypt:JSON.parse(fs.readFileSync(path.join(actual,'Local State'),'utf8')).os_crypt}));
app.setPath('userData',auth);
(async()=>{
 let stage='startup';
 try{
  await app.whenReady();stage='configuration';
  const settings=JSON.parse(fs.readFileSync(path.join(actual,'settings.json'),'utf8'));
  if(process.argv.includes('--subscription')){
   const env=Object.fromEntries(fs.readFileSync(path.join(root,'.env.local'),'utf8').split(/\r?\n/).filter(s=>s.includes('=')&&!s.trimStart().startsWith('#')).map(s=>{const i=s.indexOf('=');return [s.slice(0,i).trim(),s.slice(i+1).trim().replace(/^['"]|['"]$/g,'')];}));
   const apiKey=env.MINIMAX_API_KEY;if(!apiKey?.startsWith('sk-cp-'))throw new Error('SUBSCRIPTION_KEY_REQUIRED');
   stage='subscription_acceptance';
   await require('./live-private-acceptance.cjs').run({directory,profile:{id:'private-subscription',model:'MiniMax-M3',provider:'anthropic',baseUrl:'https://api.minimax.cn/anthropic/v1',limits:{context_tokens:1000000,output_tokens:8192,output_limit_tokens:16384}},apiKey,account:settings.activeAccountId,subscription:true});return;
  }
  const profile=settings.modelProfiles.find(p=>p.id===settings.activeModelProfileId);
  if(!profile?.apiKeyEncrypted||new URL(profile.baseUrl).hostname!=='api.deepseek.com'||!profile.model.startsWith('deepseek-'))throw new Error('DEEPSEEK_CONFIGURATION_REQUIRED');
  if(!safeStorage.isEncryptionAvailable())throw new Error('KEY_UNAVAILABLE');
  const apiKey=safeStorage.decryptString(Buffer.from(profile.apiKeyEncrypted,'base64'));
  stage='private_acceptance';
  await require('./live-private-acceptance.cjs').run({directory,profile:{...profile,model:'deepseek-flash'},apiKey,account:settings.activeAccountId});
 }catch(error){console.log(JSON.stringify({stage,ok:false,code:error.code||'PRIVATE_ACCEPTANCE_FAILED'}));process.exitCode=1;}
 finally{app.exit(process.exitCode||0);}
})();
