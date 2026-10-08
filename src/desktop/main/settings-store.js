const fs = require('node:fs');
const path = require('node:path');
const { configurationFingerprint } = require('./model-capabilities');

const DEFAULTS = {
  version: 3,
  mediaProfiles: {vision:{id:"media-vision",provider:"openai-compatible",baseUrl:"",model:"",protocol:"chat",apiKeyEncrypted:""},speech:{id:"media-speech",provider:"openai-compatible",baseUrl:"",model:"",protocol:"qwen-asr",apiKeyEncrypted:""}},
  messagePageSize: 100,
  activePlatform: 'qq',
  activeAccountId: '',
  autoDiscover: true,
  accounts: {},
  activeModelProfileId: 'openai-default',
  modelProfiles: [
    {
      id: 'openai-default',
      name: 'OpenAI',
      provider: 'openai',
      baseUrl: 'https://api.openai.com/v1',
      model: '',
      apiKeyEncrypted: '',
      builtIn: true,
    },
    {
      id: 'anthropic-default',
      name: 'Anthropic / Claude',
      provider: 'anthropic',
      baseUrl: 'https://api.anthropic.com/v1',
      model: '',
      apiKeyEncrypted: '',
      builtIn: true,
    },
  ],
};

function withDefaultModelProfiles(parsed) {
  const profiles = Array.isArray(parsed.modelProfiles) ? parsed.modelProfiles.map((item) => ({ ...item })) : [];
  const legacyIndex = profiles.findIndex((item) => item.id === 'default');
  if (legacyIndex >= 0 && !profiles.some((item) => item.id === 'openai-default')) {
    profiles[legacyIndex] = {
      ...profiles[legacyIndex],
      id: 'openai-default',
      name: profiles[legacyIndex].name === '默认 OpenAI 兼容接口' ? 'OpenAI' : profiles[legacyIndex].name,
      provider: profiles[legacyIndex].baseUrl === 'https://api.openai.com/v1' ? 'openai' : profiles[legacyIndex].provider,
      builtIn: true,
    };
  }
  for (const builtIn of DEFAULTS.modelProfiles) {
    const index = profiles.findIndex((item) => item.id === builtIn.id);
    if (index < 0) profiles.push(structuredClone(builtIn));
    else profiles[index] = { ...profiles[index], builtIn: true };
  }
  return profiles;
}

class SettingsStore {
  constructor(app, safeStorage) {
    this.safeStorage = safeStorage;
    this.file = path.join(app.getPath('userData'), 'settings.json');
    this.data = this.load();
  }

  load() {
    try {
      const parsed = JSON.parse(fs.readFileSync(this.file, 'utf8'));
      const modelProfiles = withDefaultModelProfiles(parsed);
      const activeModelProfileId = parsed.activeModelProfileId === 'default'
        ? 'openai-default'
        : modelProfiles.some((item) => item.id === parsed.activeModelProfileId)
          ? parsed.activeModelProfileId
          : DEFAULTS.activeModelProfileId;
      return {
        ...DEFAULTS,
        ...parsed,
        version: DEFAULTS.version,
        messagePageSize: Number.isInteger(parsed.messagePageSize) && parsed.messagePageSize >= 20 && parsed.messagePageSize <= 500 ? parsed.messagePageSize : 100,
        accounts: parsed.accounts || {},
        activeModelProfileId,
        modelProfiles,
        mediaProfiles: Object.fromEntries(["vision","speech"].map(kind=>[kind,{...DEFAULTS.mediaProfiles[kind],...(parsed.mediaProfiles?.[kind]||{})}])),
      };
    } catch {
      return structuredClone(DEFAULTS);
    }
  }

  publicValue() {
    return {
      version: this.data.version,
      messagePageSize: this.data.messagePageSize,
      activePlatform: this.data.activePlatform,
      activeAccountId: this.data.activeAccountId,
      autoDiscover: this.data.autoDiscover,
      activeModelProfileId: this.data.activeModelProfileId,
      accounts: Object.fromEntries(Object.entries(this.data.accounts).map(([id, account]) => [id, {
        alias: account.alias || '',
        hasDatabaseKey: Boolean(account.databaseKeyEncrypted),
      }])),
      mediaProfiles: Object.fromEntries(Object.entries(this.data.mediaProfiles).map(([kind,profile])=>[kind,{id:profile.id,provider:profile.provider,baseUrl:profile.baseUrl,model:profile.model,protocol:profile.protocol,hasApiKey:Boolean(profile.apiKeyEncrypted),test:profile.test?.fingerprint===configurationFingerprint(profile)?profile.test:null}])),
      modelProfiles: this.data.modelProfiles.map((profile) => ({
        id: profile.id,
        name: profile.name,
        provider: profile.provider,
        baseUrl: profile.baseUrl,
        model: profile.model,
        hasApiKey: Boolean(profile.apiKeyEncrypted),
        builtIn: Boolean(profile.builtIn),
      })),
    };
  }

  save(input = {}) {
    if(input.mediaProfile) this.saveMediaProfile(input.mediaProfile);
    if (input.messagePageSize !== undefined) {
      if (!Number.isInteger(input.messagePageSize) || input.messagePageSize < 20 || input.messagePageSize > 500) throw new Error('每页条数须为 20 至 500 的整数。');
      this.data.messagePageSize = input.messagePageSize;
    }
    if (['qq', 'wechat'].includes(input.activePlatform)) this.data.activePlatform = input.activePlatform;
    if (typeof input.activeAccountId === 'string') this.data.activeAccountId = input.activeAccountId.slice(0, 160);
    if (typeof input.autoDiscover === 'boolean') this.data.autoDiscover = input.autoDiscover;

    if (input.account && typeof input.account.id === 'string') {
      const id = input.account.id.slice(0, 160);
      const existing = this.data.accounts[id] || {};
      const next = { ...existing, alias: String(input.account.alias || '').trim().slice(0, 80) };
      if (input.account.clearDatabaseKey) next.databaseKeyEncrypted = '';
      if (typeof input.account.databaseKey === 'string' && input.account.databaseKey.length) {
        if (input.account.databaseKey.length !== 16) throw new Error('QQ 数据库密钥必须是 16 个字符。');
        next.databaseKeyEncrypted = this.encrypt(input.account.databaseKey);
      }
      this.data.accounts[id] = next;
    }

    if (input.modelProfile && typeof input.modelProfile.id === 'string') {
      const raw = input.modelProfile;
      const id = raw.id.replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 80) || `profile-${Date.now()}`;
      const existing = this.data.modelProfiles.find((item) => item.id === id) || {};
      const profile = {
        ...existing,
        id,
        name: String(raw.name || '未命名配置').trim().slice(0, 80),
        provider: String(raw.provider || 'openai-compatible').slice(0, 40),
        baseUrl: this.validateBaseUrl(raw.baseUrl),
        model: String(raw.model || '').trim().slice(0, 160),
      };
      if (raw.clearApiKey) profile.apiKeyEncrypted = '';
      if (typeof raw.apiKey === 'string' && raw.apiKey.length) profile.apiKeyEncrypted = this.encrypt(raw.apiKey);
      const index = this.data.modelProfiles.findIndex((item) => item.id === id);
      if (index >= 0) this.data.modelProfiles[index] = profile;
      else this.data.modelProfiles.push(profile);
      this.data.activeModelProfileId = id;
    }

    if (typeof input.activeModelProfileId === 'string' && this.data.modelProfiles.some((item) => item.id === input.activeModelProfileId)) {
      this.data.activeModelProfileId = input.activeModelProfileId;
    }
    const deleteTarget = this.data.modelProfiles.find((item) => item.id === input.deleteModelProfileId);
    if (typeof input.deleteModelProfileId === 'string' && !deleteTarget?.builtIn && this.data.modelProfiles.length > 2) {
      this.data.modelProfiles = this.data.modelProfiles.filter((item) => item.id !== input.deleteModelProfileId);
      if (!this.data.modelProfiles.some((item) => item.id === this.data.activeModelProfileId)) {
        this.data.activeModelProfileId = this.data.modelProfiles[0].id;
      }
    }
    this.persist();
    return this.publicValue();
  }

  saveMediaProfile(raw) {
    const kind=raw.kind;
    if(!['vision','speech'].includes(kind))throw new Error('媒体模型类型无效。');
    const previous=this.data.mediaProfiles[kind];
    const original=raw.copyTextProfile?this.data.modelProfiles.find(value=>value.id===this.data.activeModelProfileId):null;
    const profile=original?{...previous,provider:original.provider,baseUrl:original.baseUrl,apiKeyEncrypted:original.apiKeyEncrypted}: {...previous};
    if(!raw.copyTextProfile){
      profile.provider=String(raw.provider||'openai-compatible').slice(0,40);
      profile.baseUrl=this.validateBaseUrl(raw.baseUrl);
      profile.model=String(raw.model||'').trim().slice(0,160);
      profile.protocol=kind==='vision'?'chat':raw.protocol==='transcription'?'transcription':'qwen-asr';
      if(raw.clearApiKey)profile.apiKeyEncrypted='';
      if(typeof raw.apiKey==='string'&&raw.apiKey)profile.apiKeyEncrypted=this.encrypt(raw.apiKey);
    }
    if(configurationFingerprint(previous)!==configurationFingerprint(profile))delete profile.test;
    this.data.mediaProfiles[kind]=profile;
  }

  getMediaApiKey(kind) {return this.decrypt(this.data.mediaProfiles[kind]?.apiKeyEncrypted||'');}
  recordMediaTest(kind,fingerprint,result) {
    const profile=this.data.mediaProfiles[kind];
    if(configurationFingerprint(profile)===fingerprint){profile.test={fingerprint,...result,at:new Date().toISOString()};this.persist();}
  }

  getDatabaseKey(accountId) {
    const encrypted = this.data.accounts[accountId]?.databaseKeyEncrypted;
    return encrypted ? this.decrypt(encrypted) : '';
  }

  getModelApiKey(profileId) {
    const encrypted = this.data.modelProfiles.find((item) => item.id === profileId)?.apiKeyEncrypted;
    return encrypted ? this.decrypt(encrypted) : '';
  }

  encrypt(value) {
    if (!this.safeStorage.isEncryptionAvailable()) throw new Error('当前系统无法使用安全存储，密钥未保存。');
    return this.safeStorage.encryptString(value).toString('base64');
  }

  decrypt(value) {
    try {
      return this.safeStorage.decryptString(Buffer.from(value, 'base64'));
    } catch {
      return '';
    }
  }

  validateBaseUrl(value) {
    const normalized = String(value || '').trim().replace(/\/$/, '');
    if (!normalized) return '';
    const parsed = new URL(normalized);
    if (!['http:', 'https:'].includes(parsed.protocol)) throw new Error('API 地址必须使用 http 或 https。');
    return normalized.slice(0, 500);
  }

  persist() {
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    const temporary = `${this.file}.tmp`;
    fs.writeFileSync(temporary, JSON.stringify(this.data, null, 2), { encoding: 'utf8', mode: 0o600 });
    fs.renameSync(temporary, this.file);
  }
}

module.exports = { SettingsStore };
