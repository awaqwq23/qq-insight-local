const { app, BrowserWindow, dialog, ipcMain, safeStorage, shell } = require('electron');
const { spawn } = require('node:child_process');
const path = require('node:path');
const readline = require('node:readline');

const { SettingsStore } = require('./settings-store');
const { extractNtqqDatabaseKey } = require('./key-extractor');
const { discoverModels } = require('./model-discovery');
const { officialPrice }=require('./official-pricing');
const {testMedia,mediaConfiguration,meteredCall}=require('./media-gateway');
const fs=require('node:fs');
const { registerAI } = require('./ai-coordinator');
const { registerDatabaseTransfer } = require('./database-transfer');
const { stopQQ, prepareQQDatabase } = require('./qq-session');

let mainWindow;
let core;
let requestId = 0;
const pending = new Map();
const discoveredSources = new Map();
let settingsStore;
let activeSourceOperation = null;
let aiCoordinator;

function toIpcError(error) {
  if (error instanceof Error) return error;
  const converted = new Error(error?.message || '本地处理失败。');
  if (error?.code) converted.code = error.code;
  return converted;
}

function ipcSafe(handler) {
  return async (...args) => {
    try {
      return await handler(...args);
    } catch (error) {
      throw toIpcError(error);
    }
  };
}

function coreCommand() {
  if (app.isPackaged) {
    return { command: path.join(process.resourcesPath, 'core', 'qq-insight-core.exe'), args: [] };
  }
  const python = process.env.QQ_INSIGHT_PYTHON || 'py';
  return {
    command: python,
    args: [...(/^py(?:\.exe)?$/i.test(path.basename(python)) ? ['-3.14'] : []), path.join(app.getAppPath(), 'src', 'core', 'assistant_core.py')],
  };
}

function startCore() {
  const { command, args } = coreCommand();
  const dataDir = path.join(app.getPath('userData'), 'data');
  core = spawn(command, [...args, '--data-dir', dataDir], {
    stdio: ['pipe', 'pipe', 'pipe'],
    windowsHide: true,
    env: {
      ...process.env,
      PYTHONUTF8: '1',
      PYTHONPATH: app.isPackaged ? '' : path.join(app.getAppPath(), 'src', 'core'),
    },
  });
  readline.createInterface({ input: core.stdout }).on('line', (line) => {
    try {
      const payload = JSON.parse(line);
      if (payload.method === 'source.progress') {
        activeSourceOperation?.progress(payload.params.message, false);
        return;
      }
      const waiter = pending.get(payload.id);
      if (!waiter) return;
      pending.delete(payload.id);
      if (payload.error) waiter.reject(payload.error);
      else waiter.resolve(payload.result);
    } catch {
      // Ignore a malformed response; the affected request times out.
    }
  });
  core.stderr.on('data', (chunk) => console.error(`local core: ${chunk}`));
  core.on('error', (error) => rejectAll({ code: 'CORE_START_FAILED', message: `无法启动本地核心：${error.message}` }));
  core.on('exit', () => rejectAll({ code: 'CORE_STOPPED', message: '本地核心已经停止，请重启应用。' }));
}

function rejectAll(error) {
  for (const { reject } of pending.values()) reject(error);
  pending.clear();
}

function rpc(method, params = {}) {
  if (!core || !core.stdin.writable) return Promise.reject({ code: 'CORE_STOPPED', message: '本地核心未运行。' });
  const id = ++requestId;
  return new Promise((resolve, reject) => {
    const timeoutMs = ['source.prepare', 'source.import', 'source.manual_import', 'archive.export'].includes(method) ? 30 * 60 * 1000 : 120000;
    const timer = setTimeout(() => {
      pending.delete(id);
      reject({ code: 'CORE_TIMEOUT', message: '本地处理超时，请缩小范围或重启应用。' });
    }, timeoutMs);
    pending.set(id, {
      resolve: (value) => { clearTimeout(timer); resolve(value); },
      reject: (error) => { clearTimeout(timer); reject(error); },
    });
    core.stdin.write(`${JSON.stringify({ jsonrpc: '2.0', id, method, params })}\n`);
  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1540,
    height: 900,
    minWidth: 1180,
    minHeight: 680,
    backgroundColor: '#0d1220',
    title: 'QQ Insight',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: path.join(__dirname, '..', 'preload', 'preload.js'),
    },
  });
  mainWindow.loadFile(path.join(__dirname, '..', 'renderer', 'index.html'));
}

app.whenReady().then(() => {
  settingsStore = new SettingsStore(app, safeStorage);
  startCore();
  createWindow();
  const rendererMethods = new Set(['system.health', 'dashboard.overview', 'conversation.list', 'message.list', 'message.search', 'insights.work_digest', 'profile.save', 'profile.get', 'message.context', 'message.repair', 'conversation.pin', 'favorite.set', 'favorite.list', 'media.read', 'media.refresh', 'ai.catalog', 'group.get', 'group.save', 'ai.history', 'ai.item.update', 'ai.budget.get', 'ai.budget.save', 'ai.usage.list']);
  ipcMain.handle('core:rpc', ipcSafe((_, method, params) => {
    if (!rendererMethods.has(method)) throw new Error('该操作需要通过专用入口执行。');
    return rpc(method, params);
  }));
  registerDatabaseTransfer({ ipcMain, dialog, window: () => mainWindow, rpc, settings: () => settingsStore,
    getOperation: () => activeSourceOperation, setOperation: value => { activeSourceOperation = value; }, ipcSafe });
  ipcMain.handle('media:open-favorites', ipcSafe(async () => {
    const directory = path.join(app.getPath('userData'), 'data', 'favorites', 'media');
    require('node:fs').mkdirSync(directory, { recursive: true });
    const error = await shell.openPath(directory);
    if (error) throw new Error(error);
  }));
  aiCoordinator = registerAI({ ipcMain, rpc, settings: () => settingsStore, window: () => mainWindow, ipcSafe, busy: () => Boolean(activeSourceOperation) });
  ipcMain.handle('settings:get', () => settingsStore.publicValue());
  ipcMain.handle('settings:save', (_, input) => settingsStore.save(input));
  ipcMain.handle('model:discover', ipcSafe(async (_, input = {}) => {
    const apiKey = String(input.apiKey || '') || settingsStore.getModelApiKey(String(input.profileId || ''));
    return discoverModels({
      provider: String(input.provider || 'openai-compatible'),
      baseUrl: String(input.baseUrl || ''),
      apiKey,
    });
  }));
  ipcMain.handle('model:pricing',()=>({text:officialPrice(settingsStore.data.modelProfiles.find(p=>p.id===settingsStore.data.activeModelProfileId)),vision:officialPrice(settingsStore.data.mediaProfiles.vision),speech:officialPrice(settingsStore.data.mediaProfiles.speech)}));
  ipcMain.handle('model:discover-media',ipcSafe(async(_,kind)=>{
    if(!['vision','speech'].includes(kind))throw new Error('模型类型无效。');
    const profile=settingsStore.data.mediaProfiles[kind];const apiKey=settingsStore.getMediaApiKey(kind);
    return discoverModels({...profile,apiKey});
  }));
  let mediaBusy=false;
  ipcMain.handle('model:test-media',ipcSafe(async(_,kind)=>{
    if(mediaBusy)throw new Error('已有媒体测试或转写正在运行。');
    mediaBusy=true;try{return await testMedia({store:settingsStore,rpc,kind});}finally{mediaBusy=false;}
  }));
  ipcMain.handle('model:transcribe-file',ipcSafe(async()=>{
    if(mediaBusy)throw new Error('已有媒体测试或转写正在运行。');
    const {profile,apiKey}=mediaConfiguration(settingsStore,'speech');
    mediaBusy=true;
    try{
      const picked=await dialog.showOpenDialog(mainWindow,{title:'选择需要转写的本地语音（发送到语音 API）',properties:['openFile'],filters:[{name:'音频',extensions:['wav','mp3','m4a','webm','ogg','flac']}]});
      if(picked.canceled)return {cancelled:true};
      const filename=picked.filePaths[0];const stat=await fs.promises.stat(filename);
      if(!stat.isFile()||stat.size>24*1024*1024)throw new Error('请选择不超过24MB的音频文件。');
      const extension=path.extname(filename).slice(1).toLowerCase();const mime={wav:'audio/wav',mp3:'audio/mpeg',m4a:'audio/mp4',webm:'audio/webm',ogg:'audio/ogg',flac:'audio/flac'}[extension];
      if(!mime)throw new Error('不支持该语音文件格式。');
      return await meteredCall({rpc,profile,apiKey,kind:'speech',data:await fs.promises.readFile(filename),mime,filename:'audio.'+extension});
    }finally{mediaBusy=false;}
  }));
  ipcMain.handle('source:discover', async (_, platform = 'qq') => {
    const extraRoots = process.env.QQ_INSIGHT_SCAN_ROOT ? [process.env.QQ_INSIGHT_SCAN_ROOT] : [];
    const result = await rpc('source.discover', { platform, extra_roots: extraRoots });
    discoveredSources.clear();
    for (const item of result.items || []) {
      const account = settingsStore.publicValue().accounts[item.account_id] || {};
      const merged = {
        ...item,
        account_label: account.alias || item.account_label,
        has_database_key: Boolean(account.hasDatabaseKey),
      };
      discoveredSources.set(item.id, merged);
    }
    if (!settingsStore.data.activeAccountId && result.items?.length) {
      settingsStore.save({ activeAccountId: result.items[0].account_id });
    }
    const accounts = (result.accounts || []).map(item => ({ ...item,
      account_label: settingsStore.publicValue().accounts[item.account_id]?.alias || item.account_label }));
    return { ...result, accounts, items: [...discoveredSources.values()], settings: settingsStore.publicValue() };
  });
  ipcMain.handle('source:prepare', ipcSafe(async (_, input = {}) => {
    if (input.importMode && !['incremental', 'full'].includes(input.importMode)) {
      throw new Error('更新方式无效，请重新选择增量或全量更新。');
    }
    if (activeSourceOperation) throw new Error('已有导入或导出任务正在运行，请等待完成。');
    const source = discoveredSources.get(input.sourceId);
    if (!source) throw Object.assign(new Error('数据源列表已变化，请重新扫描。'), { code: 'SOURCE_STALE' });
    if (source.requires_decryption && !input.confirmed) {
      return {
        requiresConfirmation: true,
        automaticKeyExtraction: !source.has_database_key,
        accountId: source.account_id,
        accountLabel: source.account_label,
        message: source.has_database_key
          ? '点击确认后，应用会关闭 QQ，直接读取本机已有记录并更新索引。可勾选先联网同步。'
          : '点击确认后，应用会关闭 QQ，调用本机密钥助手取钥，然后解密导入本机已有记录。可勾选先联网同步。',
      };
    }
    let databaseKey = settingsStore.getDatabaseKey(source.account_id);
    let extractedAutomatically = false;
    const controller = new AbortController();
    const progress = (message, cancellable = true) => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('source:progress', { sourceId: source.id, message, cancellable });
      }
    };
    activeSourceOperation = { sourceId: source.id, accountId: source.account_id, controller, progress, cancellable: source.requires_decryption };
    try {
      if (source.requires_decryption && input.confirmed && !databaseKey) {
        await stopQQ({ onProgress: progress, signal: controller.signal });
        databaseKey = await extractNtqqDatabaseKey({
          appPath: app.getAppPath(),
          resourcesPath: process.resourcesPath,
          portableDir: process.env.PORTABLE_EXECUTABLE_DIR,
          executableDir: path.dirname(process.execPath),
          signal: controller.signal,
          timeoutMs: 2 * 60 * 1000,
          onProgress: progress,
        });
        extractedAutomatically = true;
      }

      if (source.requires_decryption && input.confirmed) {
        await prepareQQDatabase({
          sourcePath: source.path,
          signal: controller.signal,
          onProgress: progress,
          syncOnline: input.syncOnline === true,
        });
      }

      let result;
      try {
        if (controller.signal.aborted) throw new Error('已取消更新聊天记录。');
        if (activeSourceOperation) activeSourceOperation.cancellable = false;
        progress('正在检查、解密并导入本地数据库…', false);
        result = await rpc('source.prepare', {
          path: source.path,
          account_id: source.account_id,
          account_label: source.account_label,
          platform: source.platform,
          confirm_decryption: Boolean(input.confirmed),
          database_key: databaseKey,
          import_mode: input.importMode || 'incremental',
        });
      } catch (error) {
        if (!extractedAutomatically && databaseKey && error?.code === 'DECRYPTION_FAILED') {
          settingsStore.save({ account: { id: source.account_id, clearDatabaseKey: true } });
          source.has_database_key = false;
          throw Object.assign(new Error('已保存的密钥不再适用于当前数据库。旧密钥已清除；请再次点击获取聊天记录，并确认自动取钥风险。'), {
            code: 'KEY_REEXTRACT_CONFIRM_REQUIRED',
          });
        }
        throw error;
      }
      if (extractedAutomatically) {
        settingsStore.save({ account: { id: source.account_id, databaseKey } });
      }
      settingsStore.save({ activePlatform: source.platform, activeAccountId: source.account_id });
      return { ...result, settings: settingsStore.publicValue() };
    } finally {
      if (activeSourceOperation?.sourceId === source.id) activeSourceOperation = null;
    }
  }));
  ipcMain.handle('source:cancel-operation', () => {
    if (!activeSourceOperation || !activeSourceOperation.cancellable) return { cancelled: false };
    activeSourceOperation.controller.abort();
    return { cancelled: true };
  });
  ipcMain.handle('shell:openExternal', (_, url) => shell.openExternal(url));
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow(); });
});

app.on('before-quit', () => {
  aiCoordinator?.close();
  activeSourceOperation?.controller?.abort();
  if (core && !core.killed) core.kill();
});
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit(); });
