const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('qqInsight', {
  rpc: (method, params) => ipcRenderer.invoke('core:rpc', method, params),
  pickDatabase: (format) => ipcRenderer.invoke('database:pick', format),
  importDatabase: (input) => ipcRenderer.invoke('database:import', input),
  exportDatabase: (input) => ipcRenderer.invoke('database:export', input),
  exportRoster: (input) => ipcRenderer.invoke('roster:export', input),
  exportFullRoster: (input) => ipcRenderer.invoke('roster:export-full', input),
  runAI: (input) => ipcRenderer.invoke('ai:run', input),
  aiStatus: () => ipcRenderer.invoke('ai:status'),
  cancelAI: () => ipcRenderer.invoke('ai:cancel'),
  runWorkspaceAgent: input => ipcRenderer.invoke('workspace:run',input),
  pickWorkspaceAttachments: input => ipcRenderer.invoke('workspace:attachments.pick',input),
  cancelWorkspaceAgent: () => ipcRenderer.invoke('workspace:cancel'),
  workspaceAgentStatus: () => ipcRenderer.invoke('workspace:status'),
  workspaceArtifact: input => ipcRenderer.invoke('workspace:artifact',input),
  onWorkspaceProgress: listener => {const handler=(_,payload)=>listener(payload);ipcRenderer.on('workspace:progress',handler);return ()=>ipcRenderer.removeListener('workspace:progress',handler);},
  onAIProgress: (listener) => { const handler = (_, payload) => listener(payload); ipcRenderer.on('ai:progress', handler); return () => ipcRenderer.removeListener('ai:progress', handler); },
  openFavoritesFolder: () => ipcRenderer.invoke('media:open-favorites'),
  getSettings: () => ipcRenderer.invoke('settings:get'),
  saveSettings: (input) => ipcRenderer.invoke('settings:save', input),
  officialPrices: () => ipcRenderer.invoke('model:pricing'),
  discoverMediaModels: kind => ipcRenderer.invoke('model:discover-media',kind),
  testMediaModel: kind => ipcRenderer.invoke('model:test-media',kind),
  transcribeFile: () => ipcRenderer.invoke('model:transcribe-file'),
  discoverModels: (input) => ipcRenderer.invoke('model:discover', input),
  modelLimits: input => ipcRenderer.invoke('model:limits',input),
  testCapacity: input => ipcRenderer.invoke('model:test-capacity',input),
  cancelCapacity: () => ipcRenderer.invoke('model:cancel-capacity'),
  onCapacityProgress: listener => {const handler=(_,payload)=>listener(payload);ipcRenderer.on('model:capacity-progress',handler);return ()=>ipcRenderer.removeListener('model:capacity-progress',handler);},
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
