function incomplete(usage){return Object.assign(new Error('模型流式输出未完整结束，保留已完成分块；请检查输出额度或重试。'),{code:'MODEL_INCOMPLETE',usage});}
async function readResponses(response,signal){
 if(!/text\/event-stream/i.test(response.headers?.get('content-type')||'')){
  const text=await response.text();if(Buffer.byteLength(text)>4*1024*1024)throw Object.assign(new Error('模型输出过大。'),{code:'MODEL_RESPONSE_TOO_LARGE'});
  try{return JSON.parse(text);}catch{throw Object.assign(new Error('模型接口未返回有效JSON。'),{code:'MODEL_RESPONSE_INVALID'});}
 }
 let buffer='',bytes=0,final=null;const decoder=new TextDecoder();const reader=response.body.getReader();
 const consume=block=>{
  const data=block.split(/\r?\n/).filter(line=>line.startsWith('data:')).map(line=>line.slice(5).trimStart()).join('\n');
  if(!data||data==='[DONE]')return;
  let event;try{event=JSON.parse(data);}catch{throw Object.assign(new Error('模型流式数据无效。'),{code:'MODEL_RESPONSE_INVALID'});}
  if(['response.completed','response.incomplete','response.failed'].includes(event.type))final=event.response;
  if(event.type==='error')throw Object.assign(new Error('模型服务返回流式错误。'),{code:'MODEL_RESPONSE_INVALID'});
 };
 try{
  while(true){if(signal?.aborted)throw Object.assign(new Error('已取消。'),{code:'AI_CANCELLED'});const value=await reader.read();if(value.done)break;bytes+=value.value.byteLength;if(bytes>4*1024*1024)throw Object.assign(new Error('模型流式输出过大。'),{code:'MODEL_RESPONSE_TOO_LARGE'});buffer+=decoder.decode(value.value,{stream:true});const blocks=buffer.split(/\r?\n\r?\n/);buffer=blocks.pop();for(const block of blocks)consume(block);}
  buffer+=decoder.decode();if(buffer.trim())consume(buffer);
 }finally{reader.releaseLock();}
 if(!final)throw incomplete();
 return final;
}
function responseText(payload){return payload.output?.filter(item=>item.type==='message'&&item.role==='assistant').flatMap(item=>item.content||[]).filter(item=>item.type==='output_text').map(item=>item.text).join('\n')||payload.output_text;}
module.exports={readResponses,responseText};
