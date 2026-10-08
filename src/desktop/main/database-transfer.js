const path = require('node:path');
const { randomUUID } = require('node:crypto');

// Renderer supplies a file-selection token, never an arbitrary filesystem path.
function registerDatabaseTransfer({ ipcMain, dialog, window, rpc, settings, getOperation, setOperation, ipcSafe }) {
  const files = new Map();
  const formats = new Set(['qq_encrypted', 'qq_plain', 'app_db']);
  ipcMain.handle('database:pick', ipcSafe(async (_, format) => {
    if (!formats.has(format)) throw new Error('请选择支持的数据库类型。');
    const result = await dialog.showOpenDialog(window(), {
      title: '选择要导入的数据库', properties: ['openFile'],
      filters: [{ name: '数据库', extensions: ['db', 'qqdb', 'sqlite', 'sqlite3', 'bak'] }, { name: '所有文件', extensions: ['*'] }],
    });
    if (result.canceled) return null;
    const token = randomUUID();
    files.clear();
    files.set(token, { path: result.filePaths[0], format });
    return { token, name: path.basename(result.filePaths[0]), format };
  }));
  async function run(operation) {
    if (getOperation()) throw new Error('已有导入或导出任务正在运行，请等待完成。');
    const current = {
      sourceId: 'manual-transfer', cancellable: false,
      progress: (message) => {
        const win = window();
        if (win && !win.isDestroyed()) win.webContents.send('source:progress', { sourceId: 'manual-transfer', message, cancellable: false });
      },
    };
    setOperation(current);
    try { return await operation(); } finally { setOperation(null); }
  }
  ipcMain.handle('database:import', ipcSafe(async (_, input = {}) => {
    const file = files.get(input.token);
    if (!file || file.format !== input.format) throw new Error('请重新选择要导入的文件。');
    return run(async () => {
      const result = await rpc('source.manual_import', {
        path: file.path, format: file.format, account_id: String(input.accountId || '').trim(),
        database_key: String(input.databaseKey || ''), import_mode: input.importMode || 'incremental',
      });
      const accountId = result.account_id || result.account_ids?.[0];
      if (accountId) settings().save({ activePlatform: 'qq', activeAccountId: accountId });
      return { ...result, settings: settings().publicValue() };
    });
  }));
  ipcMain.handle('database:export', ipcSafe(async (_, input = {}) => {
    const result = await dialog.showSaveDialog(window(), {
      title: '导出所有账号的数据库（请使用新文件名）',
      defaultPath: `QQ-Insight-${new Date().toISOString().replace(/[:.]/g, '-')}.db`,
      filters: [{ name: 'QQ Insight 数据库', extensions: ['db'] }],
    });
    if (result.canceled || !result.filePath) return null;
    return run(() => rpc('archive.export', { path: result.filePath }));
  }));
}

module.exports = { registerDatabaseTransfer };
