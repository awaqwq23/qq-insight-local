const { readOfficialRoster } = require('./qq-web-roster');

function registerRosterExport({ ipcMain, dialog, window, rpc, ipcSafe, BrowserWindow, readOnline = readOfficialRoster }) {
  let onlineBusy = false;
  ipcMain.handle('roster:export-full', ipcSafe(async (_, input = {}) => {
    if (!input || input.platform !== 'qq' || typeof input.account_id !== 'string' || typeof input.conversation_id !== 'string' || !input.conversation_id) throw new Error('请先选择 QQ 账号与群。');
    if (onlineBusy) throw new Error('已有官网名单导出正在进行，请先完成或关闭登录窗口。');
    onlineBusy = true;
    try {
      const scope = await rpc('roster.scope', { account_id: input.account_id, conversation_id: input.conversation_id, platform: 'qq' });
      const online = await readOnline({ BrowserWindow, parent: window(), scope });
      const selected = await dialog.showSaveDialog(window(), { title: '保存官网全体成员名单（原昵称／群名片）',
        defaultPath: `QQ-full-members-${Date.now()}.csv`, filters: [{ name: 'CSV 名单（UTF-8）', extensions: ['csv'] }] });
      if (selected.canceled || !selected.filePath) return null;
      return rpc('roster.export', { path: selected.filePath, account_id: scope.account_id, platform: 'qq', kind: 'full_members', conversation_id: input.conversation_id, online });
    } finally { onlineBusy = false; }
  }));
  ipcMain.handle('roster:export', ipcSafe(async (_, input = {}) => {
    if (!input || !['groups', 'members', 'cached_members'].includes(input.kind) || typeof input.account_id !== 'string' || !input.account_id.trim() || input.platform !== 'qq' ||
        (input.kind !== 'groups' && (typeof input.conversation_id !== 'string' || !input.conversation_id))) throw new Error('请先选择 QQ 账号及需要导出的群。');
    let info;
    if (input.kind === 'cached_members') {
      info = await rpc('roster.cache_info', { account_id: input.account_id, conversation_id: input.conversation_id, platform: 'qq' });
      const choice = await dialog.showMessageBox(window(), { type: 'info', title: '核对成员缓存',
        message: `本地成员缓存 ${info.count} 人，群资料人数 ${info.expected_count || '未知'}。`,
        detail: `${info.note}\n导入时间：${info.imported_at}\n如需补齐，请在QQ打开群成员列表并滚动加载，退出QQ后更新记录。`,
        buttons: ['导出这份缓存', '取消'], defaultId: info.count_matches ? 0 : 1, cancelId: 1 });
      if (choice.response !== 0) return null;
    }
    const selected = await dialog.showSaveDialog(window(), {
      title: input.kind === 'groups' ? '导出本地群列表（原名与备注双列）' : input.kind === 'cached_members' ? '导出QQ成员缓存（含未发言者）' : '导出本群已发言成员（原昵称与群名片双列）',
      defaultPath: `QQ-${input.kind}-${Date.now()}.csv`,
      filters: [{ name: 'CSV 名单（UTF-8）', extensions: ['csv'] }],
    });
    if (selected.canceled || !selected.filePath) return null;
    return rpc('roster.export', { path: selected.filePath, account_id: input.account_id, platform: 'qq', kind: input.kind, conversation_id: input.kind !== 'groups' ? input.conversation_id : '', ...(info ? {cache_stamp:info.imported_at} : {}) });
  }));
}

module.exports = { registerRosterExport };
