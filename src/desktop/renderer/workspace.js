function favoriteButton(id, index, enabled) {
  return `<button class="favorite-star ${enabled ? 'saved' : ''}" data-favorite="${escapeHtml(id)}" data-index="${index}" aria-label="${enabled ? '取消收藏' : '加入收藏'}" aria-pressed="${Boolean(enabled)}">${enabled ? '★' : '☆'}</button>`;
}

function messageCard(item, all = false) {
  const direction=item.direction!=='system' && (item.is_self || (item.sender_qq && item.sender_qq===activeScope().account_id)) ? 'outgoing' : item.direction;
  const imageOnly = Number.isInteger(item.favorite_media_index) && item.favorite_media_index >= 0;
  const media = (item.media || []).map((value, index) => {
    if (value.type !== 'image' || (imageOnly && index !== item.favorite_media_index)) return '';
    return `<figure class="message-media unavailable" data-image-message="${escapeHtml(item.id)}" data-image-index="${index}"><img alt="${escapeHtml(value.filename || '聊天图片')}" hidden /><div class="media-placeholder">正在查找本地图片…</div><figcaption>${favoriteButton(item.id, index, value.favorite)}<span>${escapeHtml(value.filename || '聊天图片')}</span></figcaption></figure>`;
  }).join('');
  return `<article class="message-row ${escapeHtml(direction)}" data-message-id="${escapeHtml(item.id)}"><div class="message-meta"><span>${escapeHtml(messageSender(item))}</span><time>${formatTime(item.sent_at)}</time>${item.memory?.compressed?`<span class="tag" title="${escapeHtml(item.memory.updated_at)}">已处理</span>`:''}${favoriteButton(item.id, -1, item.favorite)}</div>${all ? `<small>${escapeHtml(item.title)}</small>` : ''}<p>${escapeHtml(item.text)}</p>${(item.replies || []).map(reply => `<blockquote><small>引用 · ${escapeHtml(reply.sender || '')}</small><p>${escapeHtml(reply.text)}</p></blockquote>`).join('')}${media}<small>${escapeHtml(item.content_kind)}</small><button class="text-button context-link" data-context="${escapeHtml(item.id)}">查看上下文</button></article>`;
}

function renderMessages(items, container, all = false, append = false) {
  if (!append) { imageObservers.get(container)?.disconnect(); imageObservers.delete(container); }
  const markup = items.map(item => messageCard(item, all)).join('');
  if (append) container.insertAdjacentHTML('beforeend', markup);
  else container.innerHTML = markup || '<div class="message-empty">没有符合条件的消息。</div>';
  hydrateMessages(container);
}

function hydrateMessages(container) {
  const scope = activeScope();
  container.querySelectorAll('[data-favorite]:not([data-bound])').forEach(button => {
    button.dataset.bound = 'true';
    button.addEventListener('click', async () => {
      button.disabled = true;
      const enabled = button.getAttribute('aria-pressed') !== 'true';
      try {
        await rpc('favorite.set', { ...scope, message_id: button.dataset.favorite, media_index: Number(button.dataset.index), enabled });
        if (scope.account_id !== activeScope().account_id) return;
        document.querySelectorAll('[data-favorite]').forEach(node => {
          if (node.dataset.favorite !== button.dataset.favorite || node.dataset.index !== button.dataset.index) return;
          node.classList.toggle('saved', enabled);
          node.textContent = enabled ? '★' : '☆';
          node.setAttribute('aria-pressed', String(enabled));
          node.setAttribute('aria-label', enabled ? '取消收藏' : '加入收藏');
        });
        toast(enabled ? '已加入收藏' : '已取消收藏');
        if ($('#favorites-view').classList.contains('active')) await loadFavorites();
      } catch {} finally { button.disabled = false; }
    });
  });
  container.querySelectorAll('[data-context]:not([data-bound])').forEach(button => {
    button.dataset.bound = 'true';
    button.addEventListener('click', () => openMessageContext(button.dataset.context));
  });
  // Limit pending reads and load only visible images; large pages never queue hundreds of blobs.
  const observer = imageObservers.get(container) || new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      observer.unobserve(entry.target);
      imageQueue.push({ node: entry.target, scope });
    }
    drainImages();
  }, { rootMargin: '200px' });
  container.querySelectorAll('[data-image-message]:not([data-bound])').forEach(node => {
    node.dataset.bound = 'true';
    observer.observe(node);
  });
  imageObservers.set(container, observer);
}
const imageObservers = new WeakMap();
const imageQueue = [];
let imagesRunning = 0;
function drainImages() {
  while (imagesRunning < 2 && imageQueue.length) {
    const { node, scope } = imageQueue.shift();
    if (!node.isConnected || scope.account_id !== activeScope().account_id) continue;
    imagesRunning++;
    window.qqInsight.rpc('media.read', { ...scope, message_id: node.dataset.imageMessage, media_index: Number(node.dataset.imageIndex) }).then(result => {
      if (!node.isConnected) return;
      const image = node.querySelector('img');
      if (!result.available) { node.querySelector('.media-placeholder').textContent = result.message; return; }
      image.onload = () => { image.hidden = false; node.classList.remove('unavailable'); };
      image.onerror = () => { node.querySelector('.media-placeholder').textContent = '图片文件损坏或格式不受支持'; };
      image.src = result.data_url;
    }).catch(() => { if (node.isConnected) node.querySelector('.media-placeholder').textContent = '图片读取失败，可在设置中重新查找缓存'; })
      .finally(() => { imagesRunning--; drainImages(); });
  }
}

let favoritesRequest = 0;
let favoritesOffset = null;
async function loadFavorites(append = false) {
  const request = ++favoritesRequest;
  if (!activeScope().account_id) { $('#favorites-list').innerHTML = '<div class="empty">请先选择账号</div>'; return; }
  try {
    const scope = activeScope();
    const result = await rpc('favorite.list', { ...scope, query: $('#favorites-query').value.trim(), kind: $('#favorites-kind').value, order: $('#favorites-order').value, limit: state.settings?.messagePageSize || 100, offset: append ? favoritesOffset : 0 });
    if (request !== favoritesRequest || scope.account_id !== activeScope().account_id) return;
    renderMessages(result.items, $('#favorites-list'), true, append);
    favoritesOffset = result.next_offset;
    $('#favorites-more').hidden = !result.has_more;
  } catch {} 
}

async function openMessageContext(messageId) {
  showView('conversations');
  resetMessagePages();
  const request = ++state.messageRequest;
  const scope = activeScope();
  $('#message-list').innerHTML = '<div class="message-empty">正在定位消息上下文…</div>';
  try {
    const result = await rpc('message.context', { ...scope, message_id: messageId, limit: state.settings?.messagePageSize || 100, order: $('#message-order').value });
    if (request !== state.messageRequest || scope.account_id !== activeScope().account_id) return;
    state.activeConversation = result.conversation.id;
    $('#message-scope').value = 'conversation';
    $('#message-query').value = '';
    $('#message-sender').value = '';
    $('#message-direction').value = '';
    $('#message-header').innerHTML = `<div><h2>${escapeHtml(result.conversation.title)}</h2><p class="muted">已定位目标记录，显示附近消息</p></div><button id="leave-context" class="outline-button">返回完整会话</button>`;
    $('#leave-context').addEventListener('click', () => openConversation(result.conversation.id));
    $('#message-page-state').textContent = `消息上下文 · ${result.items.length} 条`;
    renderMessages(result.items, $('#message-list'));
    const target = [...$('#message-list').querySelectorAll('[data-message-id]')].find(node => node.dataset.messageId === result.target_id);
    target?.classList.add('context-target');
    target?.scrollIntoView({ block: 'center' });

    renderConversations(state.conversations);
    if (result.conversation.kind === 'group') {
      if (!state.conversations.some(item => item.id === result.conversation.id)) state.conversations.push(result.conversation);
    }
    attachConversationActions(result.conversation.id);
  } catch { if (request === state.messageRequest) $('#message-list').innerHTML = '<div class="message-empty">无法定位这条消息，请重新选择账号或刷新线索。</div>'; }
}

function showPinMenu(event, conversation) {
  if (conversation?.kind !== 'group') return;
  event.preventDefault();
  $('#pin-menu')?.remove();
  const menu = document.createElement('button');
  menu.id = 'pin-menu'; menu.className = 'pin-menu outline-button';
  menu.textContent = conversation.pinned ? '取消群置顶' : '置顶此群';
  menu.style.left = `${Math.min(event.clientX, innerWidth - 160)}px`;
  menu.style.top = `${Math.min(event.clientY, innerHeight - 60)}px`;
  const scope = activeScope();
  menu.addEventListener('click', async () => {
    menu.remove();
    try { await rpc('conversation.pin', { ...scope, conversation_id: conversation.id, pinned: !conversation.pinned }); await loadConversations(); } catch {}
  });
  document.body.append(menu); menu.focus();
  menu.addEventListener('blur', () => setTimeout(() => menu.remove(), 150));
  menu.addEventListener('keydown', event => { if (event.key === 'Escape') menu.remove(); });
}

document.addEventListener('DOMContentLoaded', () => {
  $('#favorites-filters').addEventListener('submit', event => { event.preventDefault(); loadFavorites(); });
  $('#favorites-order').addEventListener('change', () => loadFavorites());
  $('#favorites-kind').addEventListener('change', () => loadFavorites());
  $('#favorites-more').addEventListener('click', () => loadFavorites(true));
  $('#open-favorites-folder').addEventListener('click', () => window.qqInsight.openFavoritesFolder().catch(error => toast(errorMessage(error), 'error')));
  $('#save-history-settings').addEventListener('click', async () => {
    try { state.settings = await window.qqInsight.saveSettings({ messagePageSize: Number($('#message-page-size').value) }); resetMessagePages(); await loadMessages(); toast('分页设置已保存'); } catch (error) { toast(errorMessage(error), 'error'); }
  });
  $('#repair-messages').addEventListener('click', async event => {
    event.target.disabled = true;
    toast('正在重新解析本地消息，请稍候…');
    try { const result = await rpc('message.repair', activeScope()); await refreshData(); toast(`已修复 ${result.updated} 条消息投影。仍缺正文时请更新 QQ 数据库。`); } catch {} finally { event.target.disabled = false; }
  });
  $('#refresh-media').addEventListener('click', async () => {
    try { await rpc('media.refresh', { account_id: activeScope().account_id }); resetMessagePages(); await loadMessages(); toast('已重新查找图片缓存'); } catch {}
  });
});
