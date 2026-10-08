const { createHash } = require('node:crypto');
const {officialPrice}=require('./official-pricing');

function modelDescriptor(profile) {
  return { id: profile.id, provider: profile.provider, model: profile.model,
    endpoint_hash: createHash('sha256').update(profile.baseUrl).digest('hex'),pricing:officialPrice(profile) };
}
function failure(code, message, extra = {}) { return Object.assign(new Error(message), { code, ...extra }); }

async function generate({ profile, apiKey, request, signal, timeoutMs = 120000, fetchImpl = globalThis.fetch }) {
  if (!apiKey || !profile?.model) throw failure('MODEL_REQUIRED', '请在设置中保存可用的 API Key 和模型名称。', { knownNotSent: true });
  let base;
  try { base = new URL(profile.baseUrl); } catch { throw failure('MODEL_URL_INVALID', '模型接口地址无效。', { knownNotSent: true }); }
  if (!['https:', 'http:'].includes(base.protocol) || base.username || base.password) throw failure('MODEL_URL_INVALID', '模型接口地址无效。', { knownNotSent: true });
  if (signal?.aborted) throw failure('AI_CANCELLED', '已取消分析。', { knownNotSent: true });
  const anthropic = profile.provider === 'anthropic';
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
  const endpoint = `${profile.baseUrl.replace(/\/+$/, '')}/${anthropic ? 'messages' : 'chat/completions'}`;
  const headers = anthropic ? { 'x-api-key': apiKey, 'anthropic-version': '2023-06-01' } : { Authorization: `Bearer ${apiKey}` };
  const body = anthropic
    ? { model: profile.model, max_tokens: request.max_tokens, system: request.system, messages: [{ role: 'user', content: images.length ? content : request.user }] }
    : { model: profile.model, max_tokens: request.max_tokens, stream: false,
      messages: [{ role: 'system', content: request.system }, { role: 'user', content: images.length ? content : request.user }] };
  // These endpoints document the option. Do not send provider-specific fields elsewhere.
  if (!anthropic && /(?:^|\.)maas\.aliyuncs\.com$|(?:^|\.)dashscope\.aliyuncs\.com$/.test(base.hostname)) body.enable_thinking = false;
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
      throw failure('MODEL_HTTP_ERROR', `模型接口 HTTP ${response.status}：${descriptions[response.status] || '服务暂时不可用'}。`);
    }
    const text = await response.text();
    if (text.length > 2 * 1024 * 1024) throw failure('MODEL_RESPONSE_TOO_LARGE', '模型返回过大，未收录。');
    let payload;
    try { payload = JSON.parse(text); } catch { throw failure('MODEL_RESPONSE_INVALID', '模型接口未返回有效 JSON。'); }
    const usage = { input_tokens: anthropic ? payload.usage?.input_tokens : payload.usage?.prompt_tokens,
      output_tokens: anthropic ? payload.usage?.output_tokens : payload.usage?.completion_tokens,
      cached_tokens: anthropic ? payload.usage?.cache_read_input_tokens || 0 : payload.usage?.prompt_tokens_details?.cached_tokens ?? payload.usage?.prompt_cache_hit_tokens ?? 0,
      seconds:payload.usage?.seconds,request_started_at:requestStartedAt,
      request_id: String(payload.id || response.headers?.get('x-request-id') || '').slice(0, 160) };
    if (anthropic && Number.isInteger(usage.input_tokens)) usage.input_tokens += (payload.usage.cache_read_input_tokens || 0) + (payload.usage.cache_creation_input_tokens || 0);
    const stop = anthropic ? payload.stop_reason : payload.choices?.[0]?.finish_reason;
    if (!['stop', 'end_turn', 'stop_sequence'].includes(stop)) throw failure('MODEL_INCOMPLETE', '模型输出被截断、拒绝或未正常完成，请调整范围或输出额度后重试。', { usage });
    const result = anthropic ? payload.content?.filter(item => item.type === 'text').map(item => item.text).join('\n') : payload.choices?.[0]?.message?.content;
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
