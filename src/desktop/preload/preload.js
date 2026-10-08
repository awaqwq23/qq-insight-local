const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('qqInsight', {
  rpc: (method, params) => ipcRenderer.invoke('core:rpc', method, params),
  pickDatabase: (format) => ipcRenderer.invoke('database:pick', format),
  importDatabase: (input) => ipcRenderer.invoke('database:import', input),
  exportDatabase: (input) => ipcRenderer.invoke('database:export', input),
  runAI: (input) => ipcRenderer.invoke('ai:run', input),
  aiStatus: () => ipcRenderer.invoke('ai:status'),
  cancelAI: () => ipcRenderer.invoke('ai:cancel'),
  onAIProgress: (listener) => { const handler = (_, payload) => listener(payload); ipcRenderer.on('ai:progress', handler); return () => ipcRenderer.removeListener('ai:progress', handler); },
  openFavoritesFolder: () => ipcRenderer.invoke('media:open-favorites'),
  getSettings: () => ipcRenderer.invoke('settings:get'),
  saveSettings: (input) => ipcRenderer.invoke('settings:save', input),
  officialPrices: () => ipcRenderer.invoke('model:pricing'),
  discoverMediaModels: kind => ipcRenderer.invoke('model:discover-media',kind),
  testMediaModel: kind => ipcRenderer.invoke('model:test-media',kind),
  transcribeFile: () => ipcRenderer.invoke('model:transcribe-file'),
  discoverModels: (input) => ipcRenderer.invoke('model:discover', input),
  discoverSources: (platform) => ipcRenderer.invoke('source:discover', platform),
  prepareSource: (input) => ipcRenderer.invoke('source:prepare', input),
  cancelSourceUpdate: () => ipcRenderer.invoke('source:cancel-operation'),
  cancelKeyExtraction: () => ipcRenderer.invoke('source:cancel-operation'),
  onKeyProgress: (listener) => {
    const handler = (_, payload) => listener(payload);
    ipcRenderer.on('source:progress', handler);
    return () => ipcRenderer.removeListener('source:progress', handler);
  },
});
