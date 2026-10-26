const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { SettingsStore } = require('../src/desktop/main/settings-store');

const safeStorage = {
  isEncryptionAvailable: () => true,
  encryptString: (value) => Buffer.from(value, 'utf8'),
  decryptString: (value) => value.toString('utf8'),
};

function storeAt(folder) {
  return new SettingsStore({ getPath: () => folder }, safeStorage);
}

function main() {
  const freshDir = fs.mkdtempSync(path.join(os.tmpdir(), 'qq-insight-settings-'));
  const fresh = storeAt(freshDir);
  assert.deepEqual(fresh.publicValue().modelProfiles.map((item) => item.id), ['openai-default', 'anthropic-default']);
  assert.equal(fresh.publicValue().modelProfiles[0].baseUrl, 'https://api.openai.com/v1');
  assert.equal(fresh.publicValue().modelProfiles[1].baseUrl, 'https://api.anthropic.com/v1');

  fresh.save({ modelProfile: {
    id: 'custom', name: 'Custom', provider: 'openai-compatible',
    baseUrl: 'https://example.com/v1', model: 'custom-model', apiKey: 'secret-value',
  } });
  assert.equal(fresh.getModelApiKey('custom'), 'secret-value');
  assert.equal(fresh.publicValue().modelProfiles.find(p=>p.id==='custom').protocol,'chat');
  fresh.save({modelProfile:{...fresh.data.modelProfiles.find(p=>p.id==='custom'),protocol:'responses'}});
  assert.equal(storeAt(freshDir).publicValue().modelProfiles.find(p=>p.id==='custom').protocol,'responses');
  assert.throws(()=>fresh.save({modelProfile:{id:'custom',protocol:'invalid'}}));
  assert.equal(fs.readFileSync(path.join(freshDir, 'settings.json'), 'utf8').includes('secret-value'), false);
  fresh.save({ deleteModelProfileId: 'openai-default' });
  assert.equal(fresh.publicValue().modelProfiles.some((item) => item.id === 'openai-default'), true);

  assert.equal(fresh.publicValue().messagePageSize, 100);
  fresh.save({messagePageSize: 240});
  assert.equal(storeAt(freshDir).publicValue().messagePageSize, 240);
  for (const size of [0, 501, 30.5, '100']) assert.throws(() => fresh.save({messagePageSize:size}));

  const legacyDir = fs.mkdtempSync(path.join(os.tmpdir(), 'qq-insight-legacy-'));
  fs.writeFileSync(path.join(legacyDir, 'settings.json'), JSON.stringify({
    activeModelProfileId: 'default',
    modelProfiles: [{ id: 'default', name: '默认 OpenAI 兼容接口', provider: 'openai-compatible', baseUrl: 'https://api.openai.com/v1', model: '' }],
  }));
  const migrated = storeAt(legacyDir).publicValue();
  assert.equal(migrated.activeModelProfileId, 'openai-default');
  assert.deepEqual(migrated.modelProfiles.map((item) => item.id), ['openai-default', 'anthropic-default']);
  assert.equal(migrated.modelProfiles[0].provider, 'openai');
  console.log('settings store defaults/migration tests passed');
}

main();
