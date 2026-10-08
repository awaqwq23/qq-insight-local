const {capability}=require('./model-capabilities');
const DEFAULT_TIMEOUT_MS = 15000;

function modelsEndpoint(baseUrl) {
  const normalized = String(baseUrl || '').trim().replace(/\/+$/, '');
  if (!normalized) throw Object.assign(new Error('请先填写 API Base URL。'), { code: 'MODEL_URL_REQUIRED' });
  let parsed;
  try {
    parsed = new URL(normalized);
  } catch {
    throw Object.assign(new Error('API Base URL 格式不正确。'), { code: 'MODEL_URL_INVALID' });
  }
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw Object.assign(new Error('API Base URL 必须使用 http 或 https。'), { code: 'MODEL_URL_INVALID' });
  }
  return `${normalized}/models`;
}

function normalizeModels(payload) {
  const items = Array.isArray(payload?.data)
    ? payload.data
    : Array.isArray(payload?.models)
      ? payload.models
      : [];
  return [...new Set(items.map((item) => typeof item === 'string' ? item : item?.id)
    .filter((id) => typeof id === 'string' && id.trim())
    .map((id) => id.trim()))].sort((a, b) => a.localeCompare(b));
}

async function discoverModels({ provider, baseUrl, apiKey, timeoutMs = DEFAULT_TIMEOUT_MS, fetchImpl = globalThis.fetch } = {}) {
  if (typeof fetchImpl !== 'function') {
    throw Object.assign(new Error('当前运行环境不支持读取模型列表。'), { code: 'MODEL_FETCH_UNAVAILABLE' });
  }
  if (!String(apiKey || '').trim()) {
    throw Object.assign(new Error('请先填写 API Key，或保存一枚可用的 API Key。'), { code: 'MODEL_KEY_REQUIRED' });
  }
  const anthropic = provider === 'anthropic';
  const headers = anthropic
    ? { 'x-api-key': apiKey, 'anthropic-version': '2023-06-01', accept: 'application/json' }
    : { Authorization: `Bearer ${apiKey}`, accept: 'application/json' };
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response;
  try {
    const endpoint = anthropic ? `${modelsEndpoint(baseUrl)}?limit=1000` : modelsEndpoint(baseUrl);
    response = await fetchImpl(endpoint, { method: 'GET', headers, signal: controller.signal });
  } catch (error) {
    if (error?.name === 'AbortError') {
      throw Object.assign(new Error('读取模型列表超时，请检查接口地址和网络。'), { code: 'MODEL_FETCH_TIMEOUT' });
    }
    throw Object.assign(new Error(`无法连接模型接口：${error?.message || '网络请求失败'}`), { code: 'MODEL_FETCH_FAILED' });
  } finally {
    clearTimeout(timer);
  }
  if (!response.ok) {
    let detail = '';
    try {
      const body = await response.json();
      detail = body?.error?.message || body?.message || '';
    } catch {}
    const suffix = detail ? `：${String(detail).slice(0, 240)}` : '';
    throw Object.assign(new Error(`模型接口返回 HTTP ${response.status}${suffix}`), { code: 'MODEL_FETCH_HTTP_ERROR' });
  }
  let payload;
  try {
    payload = await response.json();
  } catch {
    throw Object.assign(new Error('模型接口没有返回有效的 JSON。'), { code: 'MODEL_FETCH_INVALID_RESPONSE' });
  }
  const models = normalizeModels(payload);
  if (!models.length) {
    throw Object.assign(new Error('接口请求成功，但没有返回可选择的模型。仍可手动填写模型名称。'), { code: 'MODEL_LIST_EMPTY' });
  }
  const raw=Array.isArray(payload.data)?payload.data:Array.isArray(payload.models)?payload.models:[];
  return { models, capabilities:models.map(id=>capability(id,raw.find(value=>value?.id===id)||{})) };
}

module.exports = { discoverModels, modelsEndpoint, normalizeModels };
