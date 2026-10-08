const {createHash}=require('node:crypto');
function capability(model,metadata={}){
 const id=model.toLowerCase();
 const inputs=metadata.input_modalities||metadata.architecture?.input_modalities||metadata.modalities?.input||[];
 const declared=Array.isArray(inputs)?inputs.map(value=>String(value).toLowerCase()):[];
 const speech=/^qwen3-asr-flash(?:-\d{4}-\d{2}-\d{2})?$/.test(id)||/^(whisper-1|gpt-(?:4o(?:-mini)?-)?transcribe(?:-\d{4}-\d{2}-\d{2})?)$/.test(id);
 const excluded=/tts|image-gen|gpt-image|dall-e|embedding|realtime|filetrans|transcribe|whisper|asr/.test(id);
 const vision=!excluded&&(/qwen.*-vl(?:-|$)|vision|^gpt-4o(?:-mini)?(?:-\d{4}-\d{2}-\d{2})?$|^claude-(?:3|sonnet-4|opus-4|haiku-4)|^gemini-.*(?:pro|flash)/.test(id)||declared.includes('image'));
 return {id:model,vision,speech,speech_protocol:id.startsWith('qwen3-asr-')?'qwen-asr':'transcription',evidence:declared.length?'接口能力元数据':'已知模型族候选',verified:false};
}
function configurationFingerprint(profile){return createHash('sha256').update(JSON.stringify([profile.provider,profile.baseUrl,profile.model,profile.protocol,profile.apiKeyEncrypted])).digest('hex');}
module.exports={capability,configurationFingerprint};
