// Reads the configured key in memory; synthetic acceptance never opens the actual QQ database.
const {app,safeStorage}=require('electron');
const fs=require('node:fs'),path=require('node:path');
const authDir=path.join(__dirname,'../build/autonomy-auth'),actualDir=path.join(app.getPath('appData'),'qq-insight-local');
fs.mkdirSync(authDir,{recursive:true});
// Reuse only the encrypted OS key in an isolated, ignored runtime; never open/write the actual profile.
const localState=JSON.parse(fs.readFileSync(path.join(actualDir,'Local State'),'utf8'));
fs.writeFileSync(path.join(authDir,'Local State'),JSON.stringify({os_crypt:localState.os_crypt}));
app.setPath('userData',authDir);
(async()=>{
 let stage='startup';
 try{
  await app.whenReady();
  stage='read_configuration';
  const settings=JSON.parse(fs.readFileSync(path.join(actualDir,'settings.json'),'utf8'));
  const profile=settings.modelProfiles.find(p=>p.id===settings.activeModelProfileId);
  if(!profile?.apiKeyEncrypted||!safeStorage.isEncryptionAvailable())throw Object.assign(new Error(),{code:'ACTIVE_MODEL_KEY_UNAVAILABLE'});
  stage='decrypt_configured_key';const apiKey=safeStorage.decryptString(Buffer.from(profile.apiKeyEncrypted,'base64'));
  stage='synthetic_acceptance';
  await require('./live-agent-autonomy.cjs').run({profile,apiKey});
 }catch(error){console.log(JSON.stringify({ok:false,stage,kind:error.name,code:error.code||'ACCEPTANCE_UNAVAILABLE'}));process.exitCode=1;}
 finally{app.exit(process.exitCode||0);}
})();
