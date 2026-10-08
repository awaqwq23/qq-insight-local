const assert = require('node:assert/strict');
const http = require('node:http');
const { discoverModels, modelsEndpoint, normalizeModels } = require('../src/desktop/main/model-discovery');

async function withServer(handler, task) {
  const server = http.createServer(handler);
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  try {
    const address = server.address();
    await task(`http://127.0.0.1:${address.port}/v1`);
  } finally {
    await new Promise((resolve) => server.close(resolve));
  }
}

async function main() {
  assert.equal(modelsEndpoint('https://api.example.com/v1/'), 'https://api.example.com/v1/models');
  assert.deepEqual(normalizeModels({ data: [{ id: 'z' }, { id: 'a' }, { id: 'a' }] }), ['a', 'z']);

  await withServer((request, response) => {
    assert.equal(request.url, '/v1/models');
    assert.equal(request.headers.authorization, 'Bearer openai-secret');
    response.setHeader('content-type', 'application/json');
    response.end(JSON.stringify({ data: [{ id: 'gpt-test' }, { id: 'gpt-small' }] }));
  }, async (baseUrl) => {
    const result = await discoverModels({ provider: 'openai', baseUrl, apiKey: 'openai-secret' });
    assert.deepEqual(result.models, ['gpt-small', 'gpt-test']);
  });

  await withServer((request, response) => {
    assert.equal(request.url, '/v1/models?limit=1000');
    assert.equal(request.headers['x-api-key'], 'claude-secret');
    assert.equal(request.headers['anthropic-version'], '2023-06-01');
    assert.equal(request.headers.authorization, undefined);
    response.setHeader('content-type', 'application/json');
    response.end(JSON.stringify({ data: [{ id: 'claude-test' }] }));
  }, async (baseUrl) => {
    const result = await discoverModels({ provider: 'anthropic', baseUrl, apiKey: 'claude-secret' });
    assert.deepEqual(result.models, ['claude-test']);
  });

  await withServer((_request, response) => {
    response.statusCode = 401;
    response.setHeader('content-type', 'application/json');
    response.end(JSON.stringify({ error: { message: 'bad key' } }));
  }, async (baseUrl) => {
    await assert.rejects(
      discoverModels({ provider: 'openai-compatible', baseUrl, apiKey: 'bad' }),
      /HTTP 401：bad key/,
    );
  });

  console.log('model-discovery tests passed');
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
