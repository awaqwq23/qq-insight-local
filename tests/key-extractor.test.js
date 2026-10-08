const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { extractNtqqDatabaseKey, findKeyHelper, parseExtractedKey, safeProgressMessage } = require('../src/desktop/main/key-extractor');

async function run() {
  assert.equal(parseExtractedKey('加密密钥: 0123456789abcdef\n'), '0123456789abcdef');
  const emitted = new Set();
  assert.equal(
    safeProgressMessage('QQ 进程已启动。PID: 1', emitted),
    '正在等待 QQ 初始化账号数据库，请不要关闭新启动的 QQ。',
  );

  const folder = fs.mkdtempSync(path.join(os.tmpdir(), 'qq-insight-key-test-'));
  const nested = path.join(folder, 'tools', 'qq-win-db-key-master', 'scripts', 'windows', 'ntqq', 'windows_ntqq_get_key.ps1');
  fs.mkdirSync(path.dirname(nested), { recursive: true });
  fs.writeFileSync(nested, '# synthetic helper', 'utf8');
  assert.equal(findKeyHelper({ appPath: folder }), nested);
  const helper = path.join(folder, 'fake-helper.ps1');
  fs.writeFileSync(helper, '[Console]::OutputEncoding=[Text.Encoding]::UTF8\nWrite-Host "正在自动检测已安装的QQ"\nStart-Sleep -Seconds 30\n', 'utf8');
  const previous = process.env.QQ_INSIGHT_KEY_HELPER;
  process.env.QQ_INSIGHT_KEY_HELPER = helper;
  const progress = [];
  const started = Date.now();
  try {
    await assert.rejects(
      extractNtqqDatabaseKey({ timeoutMs: 350, onProgress: (message) => progress.push(message) }),
      (error) => error.code === 'KEY_EXTRACTION_TIMEOUT',
    );
    assert.ok(Date.now() - started < 5000, 'timeout must return control promptly');
    assert.ok(progress.some((message) => message.includes('密钥助手')));

    const controller = new AbortController();
    const pending = extractNtqqDatabaseKey({ timeoutMs: 5000, signal: controller.signal });
    setTimeout(() => controller.abort(), 200);
    await assert.rejects(pending, (error) => error.code === 'KEY_EXTRACTION_CANCELLED');
  } finally {
    if (previous === undefined) delete process.env.QQ_INSIGHT_KEY_HELPER;
    else process.env.QQ_INSIGHT_KEY_HELPER = previous;
    fs.rmSync(folder, { recursive: true, force: true });
  }
  console.log('key extractor timeout/cancel tests passed');
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
