const state = {
  conversations: [],
  conversationCursor: null,
  conversationRequest: 0,
  messageRequest: 0,
  messageCursors: [null],
  messagePage: 0,
  messageNext: null,
  activeConversation: null,
  overview: null,
  settings: null,
  sources: [],
  importedAccounts: [],
  manualFile: null,
  transferBusy: false,
  pendingSource: null,
  decrypting: false,
  cancelRequested: false,
  editingModelProfileId: null,
  modelCatalog: { profileId: '', models: [], page: 0 },
};

const MODEL_PAGE_SIZE = 18;

const $ = (selector) => document.querySelector(selector);
const formatNumber = (value) => new Intl.NumberFormat('zh-CN').format(value || 0);
const formatTime = (value) => value ? new Date(value * 1000).toLocaleString('zh-CN', { hour12: false }) : '暂无时间';
const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]));

function displayImageUrl(value) {
  const ref = String(value || '').trim();
  if (/^data:image\/(?:png|jpe?g|webp);base64,/i.test(ref)) return ref;
  const local = localFileUrl(ref);
  if (local) return local;
  try {
    const url = new URL(ref);
    if (url.protocol === 'https:' && /^(?:q[1-4]|p)\.qlogo\.cn$/i.test(url.hostname)) return url.href;
  } catch {}
  return '';
}

function conversationAvatar(item, className = 'conversation-badge') {
  const source = displayImageUrl(item.avatar_ref);
  const fallback = item.kind === 'group' ? '群' : String(item.peer_qq || item.display_name || '私').slice(0, 2);
  return `<span class="${className} ${item.kind}">${source ? `<img src="${escapeHtml(source)}" alt="" loading="lazy" />` : escapeHtml(fallback)}</span>`;
}

function toast(message, type = 'info') {
  const node = $('#toast');
  node.textContent = message;
  node.className = `toast visible ${type}`;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { node.className = 'toast'; }, 4600);
}

function errorMessage(error) {
  const message = error?.message || error?.data?.message || String(error || '') || '本地处理失败';
  return message
    .replace(/^Error invoking remote method '[^']+':\s*/i, '')
    .replace(/^Error:\s*/i, '');
}

function rpc(method, params = {}) {
  return window.qqInsight.rpc(method, params).catch((error) => {
    toast(errorMessage(error), 'error');
    throw error;
  });
}

function activeScope() {
  return {
    platform: state.settings?.activePlatform || 'qq',
    account_id: state.settings?.activeAccountId || null,
  };
}

function showView(name, load=true) {
  if(name==='workspace-agent' && workspaceUI.conversation)resetWorkspaceChats();
  const view=name==='conversation-agent'?'workspace-agent':name;
  $('.app-shell').classList.toggle('chat-focus',view==='workspace-agent');
  if($('#workspace-chat-menu'))$('#workspace-chat-menu').open=false;
  document.querySelectorAll('.view').forEach((node) => node.classList.toggle('active', node.id === `${view}-view`));
  document.querySelectorAll('.nav-item').forEach((node) => node.classList.toggle('active', node.dataset.view === (name==='conversation-agent'?'conversations':name)));
  if (name === 'favorites') loadFavorites();
  if (name === 'workspace-agent' || name === 'conversation-agent') {renderChatContext();if(load)loadWorkspaceHistory();}
  if (name === 'ai-history') loadRecentAIHistory();
  if (name === 'settings') { loadAIBudget(); renderMediaSettings(); loadUsage(); }
  $('#page-title').textContent = {
    dashboard: '今日概览', conversations: '消息浏览', digest: '工作概要', settings: '设置中心', favorites: '我的收藏', 'group-ai': '群 AI 工作台', 'workspace-agent':'全局 AI Agent', 'conversation-agent':'会话 AI 聊天', 'ai-history':'历史记录',
  }[name];
}

function renderOverview(data) {
  state.overview = data;
  $('#stats-grid').innerHTML = [
    ['已导入消息', formatNumber(data.message_count), '当前软件与账号'],
    ['会话范围', formatNumber(data.conversation_count), '群聊和私聊'],
    ['非文本提示', formatNumber(data.nontext_count), '图片、表情、系统等'],
    ['最新记录', formatTime(data.latest_timestamp), '来自本地数据库'],
  ].map(([label, value, hint]) => `<article class="stat-card"><span>${label}</span><strong>${value}</strong><small>${hint}</small></article>`).join('');
  $('#recent-list').innerHTML = data.recent_conversations.length
    ? data.recent_conversations.map((item) => `<button class="recent-item" data-conversation="${escapeHtml(item.id)}">${conversationAvatar(item)}<span><strong>${escapeHtml(item.title)}</strong><small>${formatTime(item.updated_at)}</small></span><b>›</b></button>`).join('')
    : '<div class="empty">当前账号尚未导入数据</div>';
  document.querySelectorAll('[data-conversation]').forEach((node) => node.addEventListener('click', () => openConversation(node.dataset.conversation)));
}

function renderConversations(items) {
  state.conversations = items;
  const filtered = items;
  $('#conversation-list').innerHTML = filtered.length
    ? filtered.map((item) => `<button class="conversation-item ${state.activeConversation === item.id ? 'selected' : ''}" data-id="${escapeHtml(item.id)}">${conversationAvatar(item)}<span class="conversation-copy"><strong>${item.pinned ? '📌 ' : ''}${escapeHtml(item.title)}</strong><small>${item.peer_qq ? `${item.kind === 'group' ? '群号' : 'QQ'} ${escapeHtml(item.peer_qq)} · ` : ''}${formatNumber(item.message_count)} 条 · ${formatTime(item.updated_at)}</small></span></button>`).join('')
    : '<div class="empty">当前账号没有可显示的会话</div>';
  if (state.conversationCursor) $('#conversation-list').insertAdjacentHTML('beforeend', '<button id="conversation-more" class="outline-button">加载更多会话</button>');
  $('#conversation-more')?.addEventListener('click', () => loadConversations(true));
  document.querySelectorAll('.conversation-item').forEach((node) => {
    node.addEventListener('click', () => openConversation(node.dataset.id));
    node.addEventListener('contextmenu', event => showPinMenu(event, items.find(item => item.id === node.dataset.id)));
  });
}

async function loadConversations(append = false) {
  const request = ++state.conversationRequest;
  if (append && $('#conversation-more')) $('#conversation-more').disabled = true;
  try {
    const result = await rpc('conversation.list', { ...activeScope(), query: $('#conversation-search').value.trim(), cursor: append ? state.conversationCursor : null });
    if (request !== state.conversationRequest) return;
    state.conversationCursor = result.next_cursor;
    renderConversations(append ? [...state.conversations, ...result.items] : result.items);
  } catch {
    if (request === state.conversationRequest) {
      if (append) renderConversations(state.conversations);
      else $('#conversation-list').innerHTML = '<div class="empty">会话加载失败，请重新搜索。</div>';
    }
  }
}

async function refreshData() {
  const scope = activeScope();
  const [overview] = await Promise.all([
    rpc('dashboard.overview', scope), loadConversations(),
  ]);
  if (scope.account_id !== activeScope().account_id || scope.platform !== activeScope().platform) return;
  renderOverview(overview);
  resetMessagePages();
  await loadMessages();
  if ($('#favorites-view').classList.contains('active')) await loadFavorites();
}

async function refresh() {
  const health = await rpc('system.health');
  $('#core-state').textContent = health.message_count ? `本地索引 · ${formatNumber(health.message_count)} 条` : '本地核心已就绪';
  $('#core-state').classList.add('ready');
  await refreshData();
}

async function openConversation(id) {
  state.activeConversation = id;
  $('#message-scope').value = 'conversation';
  showView('conversations');
  renderConversations(state.conversations);
  resetMessagePages();
  await loadMessages();
}

function resetMessagePages() {
  ++state.messageRequest;
  state.messageCursors = [null];
  state.messagePage = 0;
  state.messageNext = null;
  $('#message-newer').disabled = true;
  $('#message-older').disabled = true;
}

async function loadMessages(page = 0) {
  const all = $('#message-scope').value === 'account';
  const id = state.activeConversation;
  const request = ++state.messageRequest;
  const conversation = state.conversations.find((item) => item.id === id) || state.overview?.recent_conversations.find((item) => item.id === id);
  const title = all ? '当前账号全部会话' : conversation?.title || '当前会话';
  $('#message-header').innerHTML = `<div><p class="eyebrow">CHAT HISTORY</p><h2>${escapeHtml(title)}</h2><p class="muted">全部已导入历史每页 ${state.settings?.messagePageSize || 100} 条；筛选覆盖全部已导入记录。</p></div>`;
  attachConversationActions(all ? '' : id);
  $('#message-newer').disabled = true;
  $('#message-older').disabled = true;
  if (!all && !id) {
    $('#message-page-state').textContent = '请选择会话或搜索全部会话';
    $('#message-list').innerHTML = '<div class="message-empty">请选择会话，或将范围切换为“当前账号全部会话”。</div>';
    return;
  }
  $('#message-list').innerHTML = '<div class="message-empty loading">正在读取本地消息…</div>';
  $('#message-page-state').textContent = '正在查询…';
  try {
    const params = { ...activeScope(), limit: $('#message-mode').value === 'all' ? (state.settings?.messagePageSize || 100) : 100, order: $('#message-order').value, recent: $('#message-mode').value === 'recent', query: $('#message-query').value.trim(), sender: $('#message-sender').value.trim(), direction: $('#message-direction').value, cursor: state.messageCursors[page] };
    if (!all) params.conversation_id = id;
    const result = await rpc(all ? 'message.search' : 'message.list', params);
    if (request !== state.messageRequest) return;
    state.messagePage = page;
    state.messageNext = result.next_cursor;
    const items = result.items;
    renderMessages(items, $('#message-list'), all);
    $('#message-list').scrollTop = 0;
    $('#message-page-state').textContent = `第 ${page + 1} 页 · ${items.length} 条${result.has_more ? ($('#message-mode').value === 'recent' ? ' · 切换“全部记录”继续浏览' : '') : ' · 已到本方向末尾'}`;
    $('#message-newer').disabled = page === 0;
    $('#message-older').disabled = $('#message-mode').value !== 'all' || !result.has_more;
  } catch {
    if (request !== state.messageRequest) return;
    $('#message-list').innerHTML = '<div class="message-empty">读取失败，请点击“搜索 / 筛选”重试。</div>';
    $('#message-page-state').textContent = '查询失败';
  }
}

function messageSender(item) {
  if (item.direction === 'outgoing') return '我方/本机';
  if (item.direction === 'system') return '系统';
  const name = item.sender_name || '对方/群成员';
  return item.sender_qq ? `${name} · QQ ${item.sender_qq}` : name;
}

function localFileUrl(value) {
  const path = String(value || '').trim();
  if (!/^(?:[a-z]:[\\/]|\\\\)/i.test(path)) return '';
  return `file:///${path.replace(/\\/g, '/').split('/').map((part, index) => index ? encodeURIComponent(part) : part).join('/')}`;
}

async function runDigest(conversationId = state.activeConversation) {
  await openGroupAI(conversationId, 'history', 'work');
}

function uniqueAccounts() {
  const map = new Map(state.importedAccounts.map(account => [account.account_id, account]));
  for (const source of state.sources) {
    const existing = map.get(source.account_id);
    if (!existing || existing.offline || (source.source_kind === 'plaintext' && existing.source_kind !== 'plaintext')) map.set(source.account_id, source);
  }
  return [...map.values()];
}

function avatarFallback(source) {
  const raw = `${source.account_id || ''} ${source.account_label || ''}`;
  const qqNumber = raw.match(/\d{3,}/)?.[0];
  return qqNumber ? qqNumber.slice(0, 3) : String(source.account_label || 'QQ').trim().slice(0, 3).toUpperCase();
}

function accountAvatar(source) {
  const avatar = displayImageUrl(source.avatar_ref || source.avatar_data_url);
  if (/^data:image\/(?:png|jpe?g|webp);base64,/i.test(avatar)) {
    return `<span class="account-avatar"><img src="${escapeHtml(avatar)}" alt="" /></span>`;
  }
  if (avatar) return `<span class="account-avatar"><img src="${escapeHtml(avatar)}" alt="" loading="lazy" /></span>`;
  return `<span class="account-avatar">${escapeHtml(avatarFallback(source))}</span>`;
}

function renderAccountRail() {
  const platform = state.settings?.activePlatform || 'qq';
  const accounts = uniqueAccounts();
  document.querySelectorAll('.platform-switch[data-platform]').forEach((node) => {
    node.classList.toggle('active', node.dataset.platform === platform);
  });
  $('#account-rail-title').textContent = platform === 'qq' ? 'QQ 账号' : '微信账号';

  if (platform !== 'qq') {
    $('#sidebar-account-list').innerHTML = '<div class="rail-empty">微信账号适配器尚未接入。后续账号会直接显示在这里。</div>';
    $('#sidebar-scan').disabled = true;
    $('#active-context').textContent = '微信 / 待接入';
    return;
  }

  $('#sidebar-scan').disabled = false;
  $('#sidebar-account-list').innerHTML = accounts.length
    ? accounts.map((source) => `<button class="sidebar-account ${state.settings?.activeAccountId === source.account_id ? 'active' : ''}" data-account-id="${escapeHtml(source.account_id)}" title="${escapeHtml(source.account_label)}" aria-label="${escapeHtml(source.account_label)}">${accountAvatar(source)}<span class="account-copy"><strong>${escapeHtml(source.account_label)}</strong><small>${source.offline ? '本地记录 · 可浏览' : source.last_imported_at ? '已导入 · 可同步' : source.requires_decryption ? '已发现 · 待解密' : '已发现 · 可导入'}</small></span></button>`).join('')
    : '<div class="rail-empty">未发现 QQ 账号。应用会自动扫描标准数据目录。</div>';
  document.querySelectorAll('.sidebar-account').forEach((node) => node.addEventListener('click', () => selectAccount(node.dataset.accountId)));

  const active = accounts.find((source) => source.account_id === state.settings?.activeAccountId) || accounts[0];
  $('#active-context').textContent = active ? `QQ / ${active.account_label}` : 'QQ / 未发现账号';
  renderSyncActions(active);
}

function renderSyncActions(source) {
  const label = source?.last_imported_at ? '更新聊天记录' : '获取聊天记录';
  $('#sync-button').textContent = label;
  $('#hero-sync').textContent = label;
}

function renderSources() {
  const container = $('#source-list');
  if (state.settings?.activePlatform === 'wechat') {
    container.innerHTML = '<div class="empty">微信适配器尚未实现。接口已保留，后续接入不会改动消息与分析层。</div>';
    return;
  }
  container.innerHTML = state.sources.length
    ? state.sources.map((source) => `<button class="source-item ${state.settings?.activeAccountId === source.account_id ? 'selected' : ''}" data-source-id="${source.id}" data-account-id="${escapeHtml(source.account_id)}" title="${escapeHtml(source.account_label)}" aria-label="${escapeHtml(source.account_label)}"><span class="source-icon">${source.source_kind === 'plaintext' ? '✓' : '🔒'}</span><span><strong>${escapeHtml(source.account_label)}</strong><small>${source.source_kind === 'plaintext' ? '明文快照，可直接导入' : '加密数据库，确认风险后自动取钥'} · ${formatNumber(Math.round(source.size / 1048576))} MB${source.last_imported_at ? ' · 已导入' : ''}</small></span><b>${source.last_imported_at ? '更新' : '获取'}</b></button>`).join('')
    : '<div class="empty">未在标准目录中发现 nt_msg.db。请确认本机已登录过 NTQQ。</div>';
  document.querySelectorAll('.source-item').forEach((node) => node.addEventListener('click', async () => {
    await selectAccount(node.dataset.accountId);
    await prepareSource(node.dataset.sourceId);
  }));
  renderAccountEditor();
}

function renderAccountEditor() {
  const id = state.settings?.activeAccountId;
  const account = state.settings?.accounts?.[id] || {};
  $('#account-alias').value = account.alias || '';
  $('#database-key-state').textContent = account.hasDatabaseKey
    ? '已自动获取并验证该账号的密钥；密钥由 Windows 安全存储加密。'
    : '首次导入加密数据库时会自动获取并验证密钥，无需手动输入。';
}

async function discoverSources() {
  $('#scan-sources').disabled = true;
  $('#sidebar-scan').disabled = true;
  try {
    const result = await window.qqInsight.discoverSources(state.settings?.activePlatform || 'qq');
    state.sources = result.items || [];
    state.importedAccounts = result.accounts || [];
    state.settings = result.settings || state.settings;
    const accounts = uniqueAccounts();
    if (accounts.length && !accounts.some((item) => item.account_id === state.settings.activeAccountId)) {
      state.settings = await window.qqInsight.saveSettings({ activeAccountId: accounts[0].account_id });
    }
    renderAccountRail();
    renderSources();
    renderPlatformOptions();
    $('#manual-accounts').innerHTML = accounts.map(account => `<option value="${escapeHtml(account.account_id)}">${escapeHtml(account.account_label)}</option>`).join('');
  } catch (error) {
    toast(errorMessage(error), 'error');
  } finally {
    $('#scan-sources').disabled = false;
    $('#sidebar-scan').disabled = state.settings?.activePlatform !== 'qq';
  }
}

function preferredSource(accountId) {
  return state.sources
    .filter((item) => item.account_id === accountId)
    .sort((a, b) => Number(a.requires_decryption) - Number(b.requires_decryption))[0];
}

async function syncCurrent() {
  if (state.settings?.activePlatform !== 'qq') {
    showView('settings');
    toast('微信接口已预留，当前版本只实现 QQ。');
    return;
  }
  if (!state.sources.length) await discoverSources();
  const source = preferredSource(state.settings?.activeAccountId);
  if (!source) {
    showView('settings');
    toast('当前账号没有可自动更新的数据源，可在设置中手动导入数据库。');
    return;
  }
  await prepareSource(source.id);
}

function updateManualFormat() {
  const format = $('#manual-format').value;
  state.manualFile = null;
  $('#manual-file-name').textContent = '尚未选择文件';
  $('#manual-import').disabled = true;
  $('#manual-key').value = '';
  $('#manual-key-field').hidden = format !== 'qq_encrypted';
  $('#manual-account-field').hidden = format === 'app_db';
  $('#manual-mode-field').hidden = format === 'app_db';

  $('#manual-hint').textContent = format === 'app_db'
    ? '选择本软件导出的 .db 或旧版 assistant.db。合并新增记录并补充缺失正文、图片；完整正文冲突保留副本。'
    : format === 'qq_encrypted'
      ? '支持 NTQQ 加密消息库（含 QQ 文件头）。请输入对应密钥；不会启动 QQ 或自动取钥。请先退出使用该库的 QQ。'
      : '选择消息数据库；同目录的明文联系人、群资料库会一起导入。请确认账号归属。';
}

function setTransferBusy(busy) {
  state.transferBusy = busy;
  document.querySelectorAll('#database-transfer-card input, #database-transfer-card select, #database-transfer-card button').forEach(node => { node.disabled = busy; });
  $('#manual-import').disabled = busy || !state.manualFile;
}

async function pickDatabase() {
  try {
    const file = await window.qqInsight.pickDatabase($('#manual-format').value);
    if (!file) return;
    state.manualFile = file;
    $('#manual-file-name').textContent = file.name;
    $('#manual-import').disabled = false;
    if (!$('#manual-account').value) $('#manual-account').value = state.settings?.activeAccountId || '';
  } catch (error) { toast(errorMessage(error), 'error'); }
}

async function importDatabase(event) {
  event?.preventDefault();
  if (!state.manualFile || state.transferBusy) return;
  const input = { token: state.manualFile.token, format: $('#manual-format').value,
    accountId: $('#manual-account').value.trim(), databaseKey: $('#manual-key').value, importMode: $('#manual-mode').value };
  $('#manual-key').value = '';
  setTransferBusy(true);
  $('#transfer-status').textContent = '正在导入数据库，请等待；写入期间暂不可取消…';
  try {
    const result = await window.qqInsight.importDatabase(input);
    state.settings = result.settings || state.settings;
    state.activeConversation = null;
    const summary = result.status === 'merged'
      ? `合并完成：新增 ${formatNumber(result.added)} 条，保留已有 ${formatNumber(result.skipped)} 条。`
      : importResultMessage(result);
    $('#transfer-status').textContent = summary;
    toast(summary, 'success');
    await discoverSources();
    await refresh();
  } catch (error) {
    $('#transfer-status').textContent = errorMessage(error);
    toast(errorMessage(error), 'error');
  } finally { input.databaseKey = ''; setTransferBusy(false); }
}

async function exportDatabase() {
  if (state.transferBusy) return;
  setTransferBusy(true);
  $('#transfer-status').textContent = '请选择备份保存位置…';
  try {
    const result = await window.qqInsight.exportDatabase();
    $('#transfer-status').textContent = result ? `导出完成，共 ${formatNumber(result.message_count)} 条消息。可选择“本软件的数据库 / 备份”重新导入。${result.media ? ` 图片：已携带 ${result.media.included} 张，本机缺失 ${result.media.missing} 张。` : ''}` : '已取消导出。';
  } catch (error) {
    $('#transfer-status').textContent = errorMessage(error);
    toast(errorMessage(error), 'error');
  } finally { setTransferBusy(false); }
}

async function exportRoster(kind, conversationId = '', button) {
  const scope = activeScope();
  if (!scope.account_id || scope.platform !== 'qq') { toast('请先选择 QQ 账号。', 'error'); return; }
  if (button) button.disabled = true;
  try {
    const input = { ...scope, kind, conversation_id: conversationId };
    if (kind === 'full_members') toast('请在QQ官网窗口登录当前账号。全部分页人数核对一致后选择保存位置；关闭窗口可取消。');
    const result = await (kind === 'full_members' ? window.qqInsight.exportFullRoster(input) : window.qqInsight.exportRoster(input));
    if (result) toast(`已导出 ${formatNumber(result.count)} 项。${result.note}`);
  } catch (error) { toast(errorMessage(error), 'error'); }
  finally { if (button) button.disabled = false; }
}

function importResultMessage(result) {
  if (result.status === 'already_imported') return '消息与资料没有变化，本地索引已是最新。';
  const changes = result.changes || {};
  const metadata = result.metadata || {};
  const changedProfiles = (metadata.profiles || 0) + (metadata.groups || 0) + (metadata.local_avatars || 0);
  const mode = result.import_mode === 'full' ? '全量校验' : '增量更新';
  return `${mode}完成：新增 ${formatNumber(changes.added)} 条，变化 ${formatNumber(changes.updated)} 条，更新资料 ${formatNumber(changedProfiles)} 项。${result.warnings?.length ? '部分资料未完成，下次更新将重试。' : ''}`;
}

async function prepareSource(sourceId) {
  $('#sync-button').disabled = true;
  try {
    const importMode = $('#import-mode').value;
    const result = await window.qqInsight.prepareSource({ sourceId, importMode });
    if (result.requiresConfirmation) {
      state.pendingSource = { sourceId, importMode, ...result };
      showDecryptModal(result);
      return;
    }
    state.settings = result.settings || state.settings;
    toast(importResultMessage(result), result.warnings?.length ? 'info' : 'success');
    await discoverSources();
    await refreshData();
  } catch (error) {
    toast(errorMessage(error), 'error');
  } finally {
    $('#sync-button').disabled = false;
  }
}

function showDecryptModal(result) {
  state.cancelRequested = false;
  $('#decrypt-message').textContent = `${result.message} ${state.pendingSource?.importMode === 'full' ? '本次选择全量：重新解析全部记录，耗时较长。' : '本次选择增量：仅解析新增和变化记录；首次导入会建立完整索引。'}`;
  $('#decrypt-risk-title').textContent = result.automaticKeyExtraction ? '自动取钥可能触发 QQ 风控' : '即将读取并更新本地聊天索引';
  $('#decrypt-risk-detail').textContent = result.automaticKeyExtraction
    ? '依赖的开源工具会启动 QQ 并进行动态调试。取钥完成后关闭 QQ，解密导入本机已有记录。该操作可能导致 QQ 异常、账号限制或封号。'
    : '使用已保存的密钥，关闭 QQ 后直接解密已有记录。需要拉取新记录时，可勾选先联网同步，并在 QQ 中登录目标账号。';
  $('#sync-online').checked = false;
  $('#decrypt-modal').classList.add('visible');
  $('#decrypt-modal').setAttribute('aria-hidden', 'false');
  $('#confirm-decrypt').textContent = result.automaticKeyExtraction ? '我已了解风险，继续自动取钥' : '确认读取并更新';
}

function closeDecryptModal() {
  $('#decrypt-modal').classList.remove('visible');
  $('#decrypt-modal').setAttribute('aria-hidden', 'true');
  state.pendingSource = null;
}

async function confirmDecrypt() {
  if (!state.pendingSource || state.decrypting) return;
  state.decrypting = true;
  state.cancelRequested = false;
  $('#confirm-decrypt').disabled = true;
  $('#cancel-decrypt').disabled = false;
  $('#cancel-decrypt').textContent = '取消更新';
  $('#sync-online').disabled = true;
  $('#confirm-decrypt').textContent = state.pendingSource.automaticKeyExtraction ? '正在自动获取密钥…' : '正在准备读取本地记录…';
  try {
    const result = await window.qqInsight.prepareSource({
      sourceId: state.pendingSource.sourceId,
      confirmed: true,
      syncOnline: $('#sync-online').checked,
      importMode: state.pendingSource.importMode,
    });
    state.settings = result.settings || state.settings;
    closeDecryptModal();
    toast(importResultMessage(result), result.warnings?.length ? 'info' : 'success');
    await discoverSources();
    await refreshData();
  } catch (error) {
    if (state.cancelRequested) {
      closeDecryptModal();
      toast('已停止更新聊天记录。');
    } else {
      toast(errorMessage(error), 'error');
    }
  } finally {
    state.decrypting = false;
    $('#sync-online').disabled = false;
    $('#confirm-decrypt').disabled = false;
    $('#cancel-decrypt').disabled = false;
    $('#cancel-decrypt').textContent = '取消';
    $('#confirm-decrypt').textContent = '重试读取聊天记录';
  }
}

async function cancelDecrypt() {
  if (!state.decrypting) {
    closeDecryptModal();
    return;
  }
  state.cancelRequested = true;
  $('#cancel-decrypt').disabled = true;
  $('#cancel-decrypt').textContent = '正在停止…';
  $('#decrypt-risk-detail').textContent = '正在停止密钥助手或 QQ 同步流程…';
  try {
    const result = await window.qqInsight.cancelSourceUpdate();
    if (!result.cancelled) {
      state.cancelRequested = false;
      $('#cancel-decrypt').textContent = '正在写入索引，暂不可取消';
    }
  } catch (error) {
    state.cancelRequested = false;
    $('#cancel-decrypt').disabled = false;
    $('#cancel-decrypt').textContent = '取消更新';
    toast(errorMessage(error), 'error');
  }
}

async function selectAccount(accountId) {
  if (!accountId) return;
  state.settings = await window.qqInsight.saveSettings({ activePlatform: 'qq', activeAccountId: accountId });
  state.activeConversation = null;
  groupAI.request++; groupAI.conversation = null;
  resetWorkspaceChats();
  if($('#workspace-agent-view').classList.contains('active'))loadWorkspaceHistory();
  if($('#ai-history-view').classList.contains('active'))loadRecentAIHistory();
  if ($('#group-ai-view').classList.contains('active')) showView('conversations');
  resetMessagePages();
  renderAccountRail();
  renderSources();
  await refreshData();
}

function renderPlatformOptions() {
  document.querySelectorAll('.platform-option').forEach((node) => node.classList.toggle('active', node.dataset.platform === state.settings?.activePlatform));
  renderAccountRail();
}

async function switchPlatform(platform) {
  state.settings = await window.qqInsight.saveSettings({ activePlatform: platform });
  state.activeConversation = null;
  groupAI.request++; groupAI.conversation = null;
  resetWorkspaceChats();
  if($('#workspace-agent-view').classList.contains('active'))loadWorkspaceHistory();
  if($('#ai-history-view').classList.contains('active'))loadRecentAIHistory();
  if ($('#group-ai-view').classList.contains('active')) showView('conversations');
  resetMessagePages();
  renderPlatformOptions();
  await discoverSources();
  renderAccountRail();
  await refreshData();
  if (platform === 'wechat') toast('已切换到微信入口；数据适配器将在后续版本实现。');
}

async function saveAccountSettings() {
  const id = state.settings?.activeAccountId;
  if (!id) return toast('请先扫描并选择一个 QQ 账号。', 'error');
  state.settings = await window.qqInsight.saveSettings({
    account: { id, alias: $('#account-alias').value },
  });
  toast('账号设置已安全保存。', 'success');
  await discoverSources();
}

function currentModelProfile() {
  const id = state.editingModelProfileId || state.settings?.activeModelProfileId;
  return state.settings?.modelProfiles.find((item) => item.id === id) || state.settings?.modelProfiles[0];
}

function resetModelCatalog() {
  state.modelCatalog = { profileId: '', models: [], page: 0 };
  $('#model-options').innerHTML = '';
  $('#model-results-panel').hidden = true;
  $('#model-search').value = '';
}

function renderModelCatalog() {
  const { models } = state.modelCatalog;
  if (!models.length) {
    $('#model-results-panel').hidden = true;
    return;
  }
  const query=$('#model-search').value.trim().toLowerCase();
  const filtered=models.filter(model=>model.toLowerCase().includes(query));
  const pages = Math.max(1, Math.ceil(filtered.length / MODEL_PAGE_SIZE));
  state.modelCatalog.page = Math.min(Math.max(0, state.modelCatalog.page), pages - 1);
  const start = state.modelCatalog.page * MODEL_PAGE_SIZE;
  const selected = $('#model-id').value;
  $('#model-results').innerHTML = filtered.slice(start, start + MODEL_PAGE_SIZE)
    .map((model) => `<button class="model-result ${model === selected ? 'selected' : ''}" type="button" data-model-id="${escapeHtml(model)}" title="${escapeHtml(model)}">${escapeHtml(model)}</button>`)
    .join('');
  document.querySelectorAll('.model-result').forEach((node) => node.addEventListener('click', () => {
    $('#model-id').value = node.dataset.modelId;
    settingsUI.textVersion++;settingsUI.textDirty=true;$('#model-edit-status').textContent='有未保存修改';
    renderModelCatalog();
    refreshModelLimits();
  }));
  $('#model-results-count').textContent = query?`匹配 ${formatNumber(filtered.length)} / ${formatNumber(models.length)} 个`:`共 ${formatNumber(models.length)} 个`;
  if(!filtered.length)$('#model-results').textContent='没有匹配的模型，可修改搜索词或手动填写。';
  $('#model-page-state').textContent = `第 ${state.modelCatalog.page + 1} / ${pages} 页`;
  $('#model-page-prev').disabled = state.modelCatalog.page === 0;
  $('#model-page-next').disabled = state.modelCatalog.page >= pages - 1;
  $('#model-results-panel').hidden = false;
}

function renderModelProfiles() {
  ++capacityUI.request;
  const profiles = state.settings?.modelProfiles || [];
  if (!state.editingModelProfileId) state.editingModelProfileId = state.settings?.activeModelProfileId || profiles[0]?.id;
  $('#model-profile-tabs').innerHTML = profiles.map((profile) => `<button class="profile-tab ${profile.id === state.editingModelProfileId ? 'active' : ''}" data-profile-id="${escapeHtml(profile.id)}" type="button"><span class="profile-tab-heading"><strong>${escapeHtml(profile.name)}</strong>${profile.id===state.settings.activeModelProfileId?'<b class="profile-current">使用中</b>':''}</span><small>${escapeHtml(profile.model || '未选择模型')}</small></button>`).join('');
  document.querySelectorAll('.profile-tab').forEach((node) => node.addEventListener('click', () => {
    if(node.dataset.profileId===state.editingModelProfileId){showAPIKind('text');return;}
    if(!canLeaveModelProfile())return;
    state.editingModelProfileId = node.dataset.profileId;
    renderModelProfiles();
    showAPIKind('text');
  }));
  const profile = currentModelProfile();
  if (!profile) return;
  resetModelCatalog();
  $('#model-name').value = profile.name || '';
  $('#model-provider').value = profile.provider || 'openai-compatible';
  $('#model-protocol').value=profile.protocol||'chat';
  $('#model-base-url').value = profile.baseUrl || '';
  $('#model-id').value = profile.model || '';
  renderCapacity(profile.limits);
  $('#model-api-key').value = '';
  $('#model-api-key').type='password';
  settingsUI.textDirty=false;$('#model-edit-status').textContent='';
  updateAPISettingsSummary();hideSettingKeys();
  showAPIKind(settingsUI.kind);
  $('#model-key-state').textContent = profile.hasApiKey ? 'API Key 已使用 Windows 安全存储加密。' : '尚未保存 API Key。';
  $('#delete-model-profile').disabled = Boolean(profile.builtIn);
  $('#delete-model-profile').title = profile.builtIn ? 'OpenAI 与 Anthropic 默认配置不可删除' : '';
}

function addModelProfile() {
  if(!canLeaveModelProfile())return;
  const id = `profile-${Date.now()}`;
  state.settings.modelProfiles.push({ id, name: '新模型配置', provider: 'openai-compatible', baseUrl: '', model: '', hasApiKey: false });
  state.editingModelProfileId = id;
  renderModelProfiles();
  showAPIKind('text');$('#model-name').focus();
}

async function saveModelProfile() {
  const profile = currentModelProfile();
  if (!profile) return;
  ++capacityUI.request;
  const edit=settingsUI.textVersion;
  const saved = await window.qqInsight.saveSettings({
    modelProfile: {
      id: profile.id,
      name: $('#model-name').value,
      provider: $('#model-provider').value,
      protocol:$('#model-protocol').value,
      baseUrl: $('#model-base-url').value,
      model: $('#model-id').value,
      apiKey: $('#model-api-key').value,
      limits: capacityFields(),
    },
  });
  const current=currentModelProfile(),unchanged=state.editingModelProfileId===profile.id&&edit===settingsUI.textVersion;
  state.settings=saved;
  if(current&&!state.settings.modelProfiles.some(item=>item.id===current.id))state.settings.modelProfiles.push(current);
  if(unchanged){state.editingModelProfileId=state.settings.activeModelProfileId;renderModelProfiles();$('#model-edit-status').textContent='已保存并用于分析，输出额度已同步';}
  else $('#model-edit-status').textContent='提交的配置已保存；当前输入还有未保存修改。';
  loadAIBudget();
  toast('模型配置已保存并设为当前配置。', 'success');
}

async function discoverModelOptions() {
  const profile = currentModelProfile();
  if (!profile) return;
  const selected={id:profile.id,provider:$('#model-provider').value,url:$('#model-base-url').value,key:$('#model-api-key').value};
  const current=()=>currentModelProfile()?.id===selected.id&&$('#model-provider').value===selected.provider&&$('#model-base-url').value===selected.url&&$('#model-api-key').value===selected.key;
  const button = $('#discover-models');
  button.disabled = true;
  button.textContent = '正在读取…';
  $('#model-key-state').textContent = '正在连接接口并读取可用模型…';
  try {
    const result = await window.qqInsight.discoverModels({
      profileId: profile.id,
      provider: $('#model-provider').value,
      baseUrl: $('#model-base-url').value,
      apiKey: $('#model-api-key').value,
    });
    if(!current())return;
    $('#model-options').innerHTML = result.models.map((model) => `<option value="${escapeHtml(model)}"></option>`).join('');
    state.modelCatalog = { profileId: profile.id, models: result.models, capabilities:result.capabilities,baseUrl:$('#model-base-url').value,provider:$('#model-provider').value, page: 0 };
    if (!$('#model-id').value && result.models.length === 1) $('#model-id').value = result.models[0];
    renderModelCatalog();
    await refreshModelLimits();
    if(!current())return;
    $('#model-key-state').textContent = `已读取 ${formatNumber(result.models.length)} 个可用模型，请在“模型名称”中选择。`;
    toast(`已读取 ${formatNumber(result.models.length)} 个模型。`, 'success');
  } catch (error) {
    if(!current())return;
    $('#model-key-state').textContent = errorMessage(error);
    toast(errorMessage(error), 'error');
  } finally {
    button.disabled = false;
    button.textContent = '读取模型';
  }
}

function applyProviderDefault() {
  const provider = $('#model-provider').value;
  const input = $('#model-base-url');
  const known = ['https://api.openai.com/v1', 'https://api.anthropic.com/v1', 'https://api.deepseek.com/v1'];
  if (!input.value || known.includes(input.value)) {
    input.value = provider === 'anthropic'
      ? 'https://api.anthropic.com/v1'
      : provider === 'deepseek'
        ? 'https://api.deepseek.com/v1'
        : provider === 'openai' || provider === 'openai-compatible'
          ? 'https://api.openai.com/v1'
          : '';
  }
  resetModelCatalog();
}

async function deleteModelProfile() {
  const profile = currentModelProfile();
  const id = profile?.id;
  if (profile?.builtIn) return toast('OpenAI 与 Anthropic 默认配置不可删除。');
  if (!id || state.settings.modelProfiles.length <= 2) return toast('至少保留 OpenAI 与 Anthropic 默认配置。');
  state.settings = await window.qqInsight.saveSettings({ deleteModelProfileId: id });
  state.editingModelProfileId = state.settings.activeModelProfileId;
  renderModelProfiles();
  toast('模型配置已删除。', 'success');
}

document.addEventListener('DOMContentLoaded', async () => {
  $('#manual-format').addEventListener('change', updateManualFormat);
  $('#pick-database').addEventListener('click', pickDatabase);
  $('#manual-import-form').addEventListener('submit', importDatabase);
  $('#export-database').addEventListener('click', exportDatabase);
  document.querySelectorAll('.nav-item').forEach((node) => node.addEventListener('click', () => showView(node.dataset.view)));
  document.querySelectorAll('[data-go]').forEach((node) => node.addEventListener('click', () => showView(node.dataset.go)));
  document.querySelectorAll('.platform-option').forEach((node) => node.addEventListener('click', () => switchPlatform(node.dataset.platform)));
  document.querySelectorAll('.platform-switch[data-platform]').forEach((node) => node.addEventListener('click', () => switchPlatform(node.dataset.platform)));
  $('.platform-more').addEventListener('click', () => {
    showView('settings');
    toast('更多聊天软件将通过独立适配器接入。');
  });
  $('#sync-button').addEventListener('click', syncCurrent);
  $('#hero-sync').addEventListener('click', syncCurrent);
  $('#scan-sources').addEventListener('click', () => discoverSources());
  $('#sidebar-scan').addEventListener('click', () => discoverSources());
  $('#save-account').addEventListener('click', saveAccountSettings);
  $('#cancel-decrypt').addEventListener('click', cancelDecrypt);
  let decryptBackdropDown=false;
  $('#decrypt-modal').addEventListener('pointerdown',event=>{decryptBackdropDown=event.target===$('#decrypt-modal');});
  $('#decrypt-modal').addEventListener('pointerup',event=>{decryptBackdropDown=decryptBackdropDown&&event.target===$('#decrypt-modal');});
  $('#decrypt-modal').addEventListener('pointercancel',()=>{decryptBackdropDown=false;});
  $('#decrypt-modal').addEventListener('click',event=>{if(decryptBackdropDown&&event.target===$('#decrypt-modal'))$('#cancel-decrypt').click();decryptBackdropDown=false;});
  $('#confirm-decrypt').addEventListener('click', confirmDecrypt);
  let conversationSearchTimer;
  $('#conversation-search').addEventListener('input', () => {
    ++state.conversationRequest;
    clearTimeout(conversationSearchTimer);
    conversationSearchTimer = setTimeout(() => loadConversations(), 250);
  });
  $('#message-filters').addEventListener('submit', (event) => {
    event.preventDefault();
    $('#message-mode').value = 'all';
    resetMessagePages();
    loadMessages();
  });
  for (const selector of ['#message-scope', '#message-mode', '#message-direction', '#message-order']) {
    $(selector).addEventListener('change', () => { resetMessagePages(); loadMessages(); });
  }
  for (const selector of ['#message-query', '#message-sender']) {
    $(selector).addEventListener('input', () => {
      resetMessagePages();
      $('#message-page-state').textContent = '筛选条件已更改，请点击搜索';
    });
  }
  $('#message-newer').addEventListener('click', () => loadMessages(state.messagePage - 1));
  $('#message-older').addEventListener('click', () => {
    state.messageCursors[state.messagePage + 1] = state.messageNext;
    loadMessages(state.messagePage + 1);
  });
  $('#add-model-profile').addEventListener('click', addModelProfile);
  $('#save-model-profile').addEventListener('click',()=>saveModelProfile().catch(error=>toast(errorMessage(error),'error')));
  $('#discover-models').addEventListener('click', discoverModelOptions);
  $('#model-provider').addEventListener('change', applyProviderDefault);
  $('#model-id').addEventListener('input', renderModelCatalog);
  $('#model-page-prev').addEventListener('click', () => {
    state.modelCatalog.page -= 1;
    renderModelCatalog();
  });
  $('#model-page-next').addEventListener('click', () => {
    state.modelCatalog.page += 1;
    renderModelCatalog();
  });
  $('#delete-model-profile').addEventListener('click', deleteModelProfile);

  try {
    window.qqInsight.onKeyProgress?.((payload) => {
      if (state.transferBusy && payload.sourceId === 'manual-transfer') {
        $('#transfer-status').textContent = payload.message;
        return;
      }
      if (!state.decrypting || !state.pendingSource || payload.sourceId !== state.pendingSource.sourceId) return;
      $('#decrypt-risk-detail').textContent = payload.message;
      $('#confirm-decrypt').textContent = payload.message;
      if (payload.cancellable === false) {
        $('#cancel-decrypt').disabled = true;
        $('#cancel-decrypt').textContent = '导入中，暂不可取消';
      }
    });
    state.settings = await window.qqInsight.getSettings();
    $('#message-page-size').value = state.settings.messagePageSize || 100;
    renderPlatformOptions();
    renderModelProfiles();
    await discoverSources();
    await refresh();
  } catch (error) {
    $('#core-state').textContent = '本地核心连接失败';
    toast(errorMessage(error), 'error');
  }
});
