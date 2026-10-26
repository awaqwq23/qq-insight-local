const { app, BrowserWindow } = require('electron');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

app.whenReady().then(async () => {
  const win = new BrowserWindow({ show: false, width: 1540, height: 1000, webPreferences: { offscreen: true, backgroundThrottling: false, contextIsolation: true, nodeIntegration: false } });
  try {
    await win.loadFile(path.join(__dirname, '../src/desktop/renderer/index.html'));
    const result = await win.webContents.executeJavaScript(`(async () => {
      const requests = [];
      const settings = {activeAccountId:'synthetic',activePlatform:'qq',accounts:{},modelProfiles:[]};
      state.settings = settings;
      window.qqInsight = {
        pickDatabase: async format => ({token:'synthetic-token',name:'合成测试.db',format}),
        importDatabase: async input => {
          requests.push({...input});
          if ($('#manual-key').value) throw new Error('key was not cleared');
          return {status:'merged',added:205,skipped:3,settings};
        },
        exportDatabase: async () => ({message_count:205}),
        discoverSources: async () => ({items:[],accounts:[{account_id:'synthetic',account_label:'合成离线账号',offline:true}],settings}),
        rpc: async method => method === 'system.health' ? {message_count:205} : method === 'dashboard.overview' ? {recent_conversations:[],message_count:205} : {items:[]},
      };
      showView('settings');showSettingsPage('data');
      $('#manual-format').value='qq_encrypted'; updateManualFormat();
      const encryptedKeyVisible=getComputedStyle($('#manual-key-field')).display !== 'none';
      await pickDatabase(); $('#manual-key').value='0123456789abcdef';
      await importDatabase();
      const importStatus=$('#transfer-status').textContent;
      const offlineAccount=$('#sidebar-account-list').textContent;
      $('#manual-format').value='app_db'; updateManualFormat();
      const hidden=getComputedStyle($('#manual-account-field')).display === 'none' && getComputedStyle($('#manual-key-field')).display === 'none';
      const invalidated=state.manualFile===null && $('#manual-import').disabled;
      await pickDatabase(); await importDatabase(); await exportDatabase();
      const exportStatus=$('#transfer-status').textContent;
      window.qqInsight.importDatabase=async()=>{throw new Error('合成文件不兼容')};
      await importDatabase();
      const recovered=!state.transferBusy && !$('#manual-import').disabled && $('#transfer-status').textContent.includes('不兼容');
      $('#toast').className='toast';
      return {requests,encryptedKeyVisible,importStatus,offlineAccount,hidden,invalidated,exportStatus,recovered};
    })()`);
    assert.equal(result.encryptedKeyVisible, true);
    assert.equal(result.requests[0].format, 'qq_encrypted');
    assert.equal(result.requests[0].databaseKey, '0123456789abcdef');
    assert.equal(result.requests[1].format, 'app_db');
    assert.match(result.importStatus, /新增 205 条，保留已有 3 条/);
    assert.match(result.offlineAccount, /本地记录 · 可浏览/);
    assert.equal(result.hidden, true);
    assert.equal(result.invalidated, true);
    assert.match(result.exportStatus, /导出完成，共 205 条/);
    assert.equal(result.recovered, true);
    await win.webContents.executeJavaScript(`showView('settings');showSettingsPage('data'); $('#core-state').textContent='合成测试核心'; $('#manual-format').value='qq_encrypted'; updateManualFormat(); document.getAnimations().forEach(animation => animation.finish());`);
    await new Promise(resolve => setTimeout(resolve, 350));
    const screenshot = await win.webContents.capturePage();
    fs.mkdirSync(path.join(__dirname, '../build/qa'), { recursive: true });
    fs.writeFileSync(path.join(__dirname, '../build/qa/database-transfer.png'), screenshot.toPNG());
    console.log('renderer transfer: import types, key clearing, offline account, export, failure recovery passed');
    app.exit(0);
  } catch (error) {
    console.error(error);
    app.exit(1);
  }
});
