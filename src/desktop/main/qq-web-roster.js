const { randomUUID } = require('node:crypto');

const MEMBER_URL = 'https://qun.qq.com/member.html';
const PAGE_SIZE = 21; // Website st/end offsets are inclusive.
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));

function isMemberPage(url) {
  try { const value = new URL(url); return value.origin === 'https://qun.qq.com' && value.pathname === '/member.html'; }
  catch { return false; }
}

function allowedNavigation(url) {
  try {
    const value = new URL(url);
    return value.protocol === 'https:' && (value.hostname === 'qun.qq.com' || value.hostname === 'ptlogin2.qq.com' || value.hostname.endsWith('.ptlogin2.qq.com'));
  } catch { return false; }
}

function allowedManagerRequest(url, method) {
  const value = new URL(url);
  return value.origin === 'https://qun.qq.com' && ['GET', 'POST'].includes(method) &&
    ['/cgi-bin/qun_mgr/get_group_list', '/cgi-bin/qun_mgr/search_group_members'].includes(value.pathname);
}

async function collectMembers(readPage, checkAccount, progress = () => {}, pause = delay) {
  const members = new Map();
  let total;
  for (let start = 0; start < 100000; start += PAGE_SIZE) {
    await checkAccount();
    const page = await readPage(start, start + PAGE_SIZE - 1);
    await checkAccount();
    if (!page || page.ec !== 0) throw new Error('QQ群官网未允许读取名单，请确认登录、群权限或稍后重试；未导出不完整名单。');
    if (!Number.isInteger(page.count) || page.count < 1 || page.count > 100000 || !Array.isArray(page.mems) || page.mems.length > PAGE_SIZE) throw new Error('QQ群官网返回格式异常，未导出。');
    if (total === undefined) total = page.count;
    if (page.count !== total) throw new Error('读取期间群人数发生变化，请重新导出。');
    for (const member of page.mems) {
      if (!member || (typeof member.uin !== 'string' && !Number.isSafeInteger(member.uin)) || !/^[1-9]\d{4,19}$/.test(String(member.uin)) ||
          typeof member.nick !== 'string' || (member.card != null && typeof member.card !== 'string') || member.nick.length > 1000 || (member.card || '').length > 1000) throw new Error('QQ群官网成员字段无效，未导出。');
      const qq = String(member.uin);
      if (members.has(qq)) throw new Error('成员分页出现重复，名单可能已变化，请重新导出。');
      members.set(qq, { qq, nickname: member.nick, card: member.card || '' });
    }
    progress(`已读取 ${members.size} / ${total} 位成员`);
    if (members.size > total) throw new Error('官网成员人数不一致，未导出。');
    if (members.size === total) return { count: total, members: [...members.values()] };
    if (page.mems.length !== PAGE_SIZE) throw new Error('官网未返回完整成员分页，未导出。');
    await pause(350);
  }
  throw new Error('名单超过读取上限，未导出。');
}

async function readOfficialRoster({ BrowserWindow, parent, scope }) {
  if (!/^[1-9]\d{4,19}$/.test(scope.account_id) || !/^[1-9]\d{4,19}$/.test(scope.group_qq)) throw new Error('账号或群号无效。');
  const win = new BrowserWindow({ parent, width: 1100, height: 780,
    title: `请登录 QQ ${scope.account_id}，登录后自动读取当前群名单（关闭可取消）`,
    webPreferences: { partition: `qq-roster-${randomUUID()}`, nodeIntegration: false, contextIsolation: true, sandbox: true, webSecurity: true } });
  const ses = win.webContents.session;
  ses.setPermissionRequestHandler((_, __, callback) => callback(false));
  ses.setPermissionCheckHandler(() => false);
  ses.on('will-download', event => event.preventDefault());
  // The remote management page must never perform member/card/admin mutations.
  ses.webRequest.onBeforeRequest({ urls: ['*://*/cgi-bin/qun_mgr/*'] }, (details, callback) => {
    callback({ cancel: !allowedManagerRequest(details.url, details.method) });
  });
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  const guard = (event, url) => { if (!allowedNavigation(url)) event.preventDefault(); };
  win.webContents.on('will-navigate', guard);
  win.webContents.on('will-redirect', guard);
  win.webContents.on('page-title-updated', event => event.preventDefault());
  let timer;
  const cancelled = new Promise((_, reject) => win.once('closed', () => reject(new Error('已取消官网名单导出。'))));
  const expired = new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('登录或读取名单超时，请重新导出。')), 10 * 60 * 1000); });
  async function checkAccount() {
    if (win.isDestroyed()) throw new Error('已取消官网名单导出。');
    const cookies = await ses.cookies.get({ url: MEMBER_URL });
    const accounts = cookies.filter(cookie => ['uin', 'p_uin'].includes(cookie.name)).map(cookie => cookie.value.replace(/^o0*/, '')).filter(Boolean);
    if (!accounts.length) return false;
    if (accounts.some(account => account !== scope.account_id)) throw new Error('官网登录账号与当前 QQ 账号不一致，请关闭窗口并用对应账号重新登录。');
    if (!cookies.some(cookie => cookie.name === 'skey' && cookie.value)) return false;
    return true;
  }
  try {
    return await Promise.race([cancelled, expired, (async () => {
      await win.loadURL(`${MEMBER_URL}#gid=${scope.group_qq}`);
      while (true) {
        if (await checkAccount() && isMemberPage(win.webContents.getURL())) {
          const ready = await win.webContents.executeJavaScript('Boolean(window.QunHandler && typeof window.QunHandler.request === "function")');
          if (ready) break;
        }
        await delay(750);
      }
      const assertAccount = async () => {
        if (!await checkAccount() || !isMemberPage(win.webContents.getURL())) throw new Error('官网登录状态已变化，未导出。');
      };
      const result = await collectMembers(async (start, end) => {
        // Only fixed, validated decimal IDs/offsets enter this code; no credentials leave the page.
        const data = JSON.stringify({ gc: scope.group_qq, st: start, end, sort: 0 });
        return win.webContents.executeJavaScript(`new Promise((resolve,reject)=>{
          const timer=setTimeout(()=>reject(new Error('官网名单请求超时')),25000);
          window.QunHandler.request({type:'POST',url:'/cgi-bin/qun_mgr/search_group_members',data:${data},dataType:'json',timeout:20000,
            success:value=>{clearTimeout(timer);resolve({ec:value.ec,count:value.count,mems:Array.isArray(value.mems)?value.mems.map(m=>({uin:m.uin,nick:m.nick,card:m.card})):null});},
            error:()=>{clearTimeout(timer);reject(new Error('官网名单请求失败'));}});
        })`);
      }, assertAccount, message => { if (!win.isDestroyed()) win.setTitle(`正在导出全体成员：${message}（关闭可取消）`); });
      return { ...result, account_id: scope.account_id, group_qq: scope.group_qq };
    })()]);
  } finally {
    clearTimeout(timer);
    if (!win.isDestroyed()) win.destroy();
    await ses.clearStorageData().catch(() => {});
    await ses.clearCache().catch(() => {});
  }
}

module.exports = { readOfficialRoster, collectMembers, isMemberPage, allowedNavigation, allowedManagerRequest };
