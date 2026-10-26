const { createHash } = require('node:crypto');
const {officialPrice}=require('./official-pricing');
const {limitsFor}=require('./model-limits');
const {readResponses,responseText}=require('./responses-parser');

function modelDescriptor(profile) {
  return { id: profile.id, provider: profile.provider, model: profile.model,
    endpoint_hash: createHash('sha256').update(profile.baseUrl+(profile.protocol==='responses'?'|responses':'')).digest('hex'),pricing:officialPrice(profile),limits:limitsFor(profile) };
}
function failure(code, message, extra = {}) { return Object.assign(new Error(message), { code, ...extra }); }

async function generate({ profile, apiKey, request, signal, timeoutMs = request?.max_tokens>8192?1800000:120000, fetchImpl = globalThis.fetch }) {
  if (!apiKey || !profile?.model) throw failure('MODEL_REQUIRED', '请在设置中保存可用的 API Key 和模型名称。', { knownNotSent: true });
  let base;
  try { base = new URL(profile.baseUrl); } catch { throw failure('MODEL_URL_INVALID', '模型接口地址无效。', { knownNotSent: true }); }
  if (!['https:', 'http:'].includes(base.protocol) || base.username || base.password) throw failure('MODEL_URL_INVALID', '模型接口地址无效。', { knownNotSent: true });
  if (signal?.aborted) throw failure('AI_CANCELLED', '已取消分析。', { knownNotSent: true });
  const anthropic = profile.provider === 'anthropic';
  const responses=profile.protocol==='responses'&&!anthropic;
  const images = request.images || [];
  const content = [{ type: 'text', text: request.user }];
  for (const image of images) {
    if (!/^data:image\/(png|jpeg|gif|webp);base64,/.test(image.data_url)) throw failure('IMAGE_FORMAT', '图像模型仅接受 PNG、JPEG、GIF 或 WebP。', { knownNotSent: true });
    content.push({ type: 'text', text: `图片来源消息 ${image.message_id}，media_index=${image.media_index}` });
    if (anthropic) {
      const [, mime, data] = image.data_url.match(/^data:([^;]+);base64,(.+)$/);
      content.push({ type: 'image', source: { type: 'base64', media_type: mime, data } });
    } else content.push({ type: 'image_url', image_url: { url: image.data_url, detail: 'low' } });
  }
  const endpoint = `${profile.baseUrl.replace(/\/+$/, '')}/${anthropic ? 'messages' : responses?'responses':'chat/completions'}`;
  const headers = anthropic ? { 'x-api-key': apiKey, 'anthropic-version': '2023-06-01' } : { Authorization: `Bearer ${apiKey}` };
  const body = responses?{model:profile.model,instructions:request.system,input:[{role:'user',content:content.map(item=>item.type==='text'?{type:'input_text',text:item.text}:{type:'input_image',image_url:item.image_url.url,detail:'low'})}],max_output_tokens:request.max_tokens,store:false,stream:true,reasoning:{effort:'low'}}:anthropic
    ? { model: profile.model, max_tokens: request.max_tokens, system: request.system, messages: [{ role: 'user', content: images.length ? content : request.user }] }
    : { model: profile.model, max_tokens: request.max_tokens, stream: false,
      messages: [{ role: 'system', content: request.system }, { role: 'user', content: images.length ? content : request.user }] };
  // These endpoints document the option. Do not send provider-specific fields elsewhere.
  if(request.json_mode===true&&!anthropic&&!responses&&base.hostname==='api.deepseek.com')body.response_format={type:'json_object'};
  if (!anthropic && /(?:^|\.)maas\.aliyuncs\.com$|(?:^|\.)dashscope\.aliyuncs\.com$/.test(base.hostname)) body.enable_thinking = false;
  if (!anthropic && base.hostname==='api.deepseek.com')body.thinking={type:'disabled'};
  // This exact Shanghai model was live-checked with the documented DeepSeek switch.
  if(!anthropic&&!responses&&base.hostname==='discovery-api.intern-ai.org.cn'&&profile.model==='deepseek-v4-pro-0813')body.thinking={type:'disabled'};
  const minimax=!anthropic&&!responses&&['api.minimaxi.com','api.minimax.io','api.minimax.cn'].includes(base.hostname);
  if(minimax){body.reasoning_split=true;if(profile.model==='MiniMax-M3')body.thinking={type:'disabled'};}
  const timeout = AbortSignal.timeout(timeoutMs);
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout;
  let response;
  const requestStartedAt=new Date().toISOString();
  try {
    response = await fetchImpl(endpoint, { method: 'POST', headers: { ...headers, 'content-type': 'application/json' },
      body: JSON.stringify(body), redirect: 'error', signal: combined });
    if (!response.ok) {
      // Never surface arbitrary provider responses that may echo prompts or secrets.
      const descriptions = { 400: '模型或请求参数不兼容，请检查模型名称及图像开关', 401: 'API Key 无效', 403: '当前密钥没有该模型权限', 404: '模型名称或接口路径不存在', 429: '接口限流或服务额度不足' };
      let detail='';try{const value=await response.json();detail=String(value.error?.message||(typeof value.error==='string'?value.error:'')||value.message||value.base_resp?.status_msg||(typeof value.detail==='string'?value.detail:'')).slice(0,2000);}catch{}
      // Extract only whitelisted numbers/classifications; never expose provider text.
      const context=/maximum context length (?:is|of)\s*(\d+)|max(?:imum)?[_ ]context[_ ](?:length|tokens)\D{0,12}(\d+)|上下文(?:长度)?(?:限制|上限)\D{0,12}(\d+)/i.exec(detail);
      const tpm=/\bTPM[_ -]*(?:limit|max|限制|限额|上限)\D{0,8}(\d+)|tokens per min(?:ute)?\D{0,20}limit\D{0,8}(\d+)/i.exec(detail);
      const contextLimit=context&&Number(context.slice(1).find(Boolean));const tpmLimit=tpm&&Number(tpm.slice(1).find(Boolean));
      if(response.status===429){const retry=response.headers?.get('retry-after');const seconds=retry&&Number(retry);const delay=Number.isFinite(seconds)&&seconds>0?seconds*1000:retry?Date.parse(retry)-Date.now():60000;const rateKind=/TPM|tokens per min/i.test(detail)?'tpm':/RPM|requests per min/i.test(detail)?'rpm':/quota|balance|insufficient|余额|用尽|不足/i.test(detail)?'quota':/context|上下文/i.test(detail)?'context':/concurr|并发/i.test(detail)?'concurrency':/moderation|content.filter|安全|审核|敏感/i.test(detail)?'content':'unknown';throw failure('MODEL_RATE_LIMIT',rateKind==='quota'?'接口返回服务额度不足（HTTP 429），请检查服务额度或更换有额度的配置；这不是已确认的上下文超限，已完成分段保留。':'接口限流；TPM 与上下文限制不同，请降低每段读取量或等待额度恢复。',{rateKind,knownNotSent:true,retryAfterMs:Math.min(300000,Math.max(1000,Number.isFinite(delay)&&delay>0?delay:60000)),tpmLimit:tpmLimit>0&&tpmLimit<=10000000?tpmLimit:null});}
      if([400,413,422].includes(response.status)&&(context||/context_length_exceeded|context window|too many tokens|上下文.*(?:超出|超过)/i.test(detail)))throw failure('MODEL_CONTEXT_LIMIT','请求超过模型上下文限制，请降低读取量。',{contextLimit:contextLimit>=2048&&contextLimit<=10000000?contextLimit:null});
      throw failure('MODEL_HTTP_ERROR', `模型接口 HTTP ${response.status}：${descriptions[response.status] || '服务暂时不可用'}。`);
    }
    let payload;
    if(responses)payload=await readResponses(response,combined);
    else{const text=await response.text();if(text.length>2*1024*1024)throw failure('MODEL_RESPONSE_TOO_LARGE','模型返回过大，未收录。');try{payload=JSON.parse(text);}catch{throw failure('MODEL_RESPONSE_INVALID','模型接口未返回有效JSON。');}}
    const usage = { input_tokens: anthropic||responses ? payload.usage?.input_tokens : payload.usage?.prompt_tokens,
      output_tokens: anthropic||responses ? payload.usage?.output_tokens : payload.usage?.completion_tokens,
      cached_tokens: anthropic ? payload.usage?.cache_read_input_tokens || 0 : payload.usage?.prompt_tokens_details?.cached_tokens ?? payload.usage?.prompt_cache_hit_tokens ?? 0,
      seconds:payload.usage?.seconds,request_started_at:requestStartedAt,
      request_id: String(payload.id || response.headers?.get('x-request-id') || '').slice(0, 160) };
    if (anthropic && Number.isInteger(usage.input_tokens)) usage.input_tokens += (payload.usage.cache_read_input_tokens || 0) + (payload.usage.cache_creation_input_tokens || 0);
    const writeDetails=anthropic?payload.usage?.cache_creation:payload.usage?.input_tokens_details||payload.usage?.prompt_tokens_details;
    const writes=anthropic?payload.usage?.cache_creation_input_tokens:writeDetails?.cache_creation_tokens??writeDetails?.cache_write_tokens;
    if(Number.isInteger(writes)&&writes>=0){usage.cache_write_1h_tokens=writeDetails?.ephemeral_1h_input_tokens||0;usage.cache_write_tokens=Math.max(0,writes-usage.cache_write_1h_tokens);}
    if(responses)usage.cached_tokens=payload.usage?.input_tokens_details?.cached_tokens||0;
    const stop = responses?(payload.status==='completed'?'stop':payload.incomplete_details?.reason==='max_output_tokens'?'length':payload.status):anthropic ? payload.stop_reason : payload.choices?.[0]?.finish_reason;
    if (!['stop', 'end_turn', 'stop_sequence'].includes(stop)) throw failure('MODEL_INCOMPLETE', stop==='length'||stop==='max_tokens'?`模型输出达到 ${request.max_tokens} Token 额度而被截断。请在 AI 设置提高单段输出额度，或缩小分析范围；思考 Token 也可能占用输出额度。`:'模型拒绝或未正常完成，结果未保存；请调整分析范围后重试。', { usage });
    let result = responses?responseText(payload):anthropic ? payload.content?.filter(item => item.type === 'text').map(item => item.text).join('\n') : payload.choices?.[0]?.message?.content;
    if(minimax&&typeof result==='string')result=result.replace(/^\s*<think>[\s\S]*?<\/think>\s*/i,'');
    if (typeof result !== 'string' || !result.trim()) throw failure('MODEL_EMPTY', '模型没有返回可用分析内容。', { usage });
    return { result, usage };
  } catch (error) {
    if (signal?.aborted) throw failure('AI_CANCELLED', '已取消分析；已发出的请求用量可能待核对。');
    if (timeout.aborted) throw failure('MODEL_TIMEOUT', '模型请求超时，保留已完成分块，可稍后继续。');
    if (error.code?.startsWith('MODEL_') || error.code === 'IMAGE_FORMAT') throw error;
    throw failure('MODEL_NETWORK', '无法连接模型接口，请检查网络和接口地址。');
  }
}

module.exports = { generate, modelDescriptor };
