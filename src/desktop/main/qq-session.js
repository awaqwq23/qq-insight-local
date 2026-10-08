const fs = require('node:fs');
const path = require('node:path');
const { execFile, spawn } = require('node:child_process');

const delay = (ms, signal) => new Promise((resolve, reject) => {
  const timer = setTimeout(done, ms);
  function done() {
    signal?.removeEventListener('abort', abort);
    resolve();
  }
  function abort() {
    clearTimeout(timer);
    reject(Object.assign(new Error('已取消更新聊天记录。'), { code: 'SOURCE_UPDATE_CANCELLED' }));
  }
  if (signal?.aborted) abort();
  else signal?.addEventListener('abort', abort, { once: true });
});

function run(file, args, options = {}) {
  return new Promise((resolve) => {
    execFile(file, args, { windowsHide: true, timeout: options.timeout || 15000 }, (error, stdout = '', stderr = '') => {
      resolve({ ok: !error, stdout: String(stdout), stderr: String(stderr), error });
    });
  });
}

async function isQQRunning() {
  const result = await run('tasklist.exe', ['/FI', 'IMAGENAME eq QQ.exe', '/FO', 'CSV', '/NH']);
  if (!result.ok) throw Object.assign(new Error('无法检查 QQ 进程状态，请稍后重试。'), { code: 'QQ_PROCESS_CHECK_FAILED' });
  return /"QQ\.exe"/i.test(result.stdout);
}

async function findRunningQQPath() {
  const powershell = path.join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
  const result = await run(powershell, ['-NoLogo', '-NoProfile', '-NonInteractive', '-Command',
    "Get-Process -Name QQ -ErrorAction SilentlyContinue | Where-Object Path | Select-Object -First 1 -ExpandProperty Path"], { timeout: 10000 });
  const candidate = result.stdout.trim().split(/\r?\n/)[0];
  return candidate && fs.existsSync(candidate) ? candidate : '';
}

async function findQQExecutable() {
  const running = await findRunningQQPath();
  if (running) return running;
  const candidates = [
    process.env.QQ_INSIGHT_QQ_EXE,
    path.join(process.env.ProgramFiles || 'C:\\Program Files', 'Tencent', 'QQNT', 'QQ.exe'),
    path.join(process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)', 'Tencent', 'QQNT', 'QQ.exe'),
    path.join(process.env['ProgramFiles(x86)'] || 'C:\\Program Files (x86)', 'talk', 'QQ.exe'),
    path.join(process.env.LOCALAPPDATA || '', 'Programs', 'QQ', 'QQ.exe'),
  ].filter(Boolean);
  return candidates.find((candidate) => fs.existsSync(candidate)) || '';
}

async function waitUntilStopped(timeoutMs = 15000, signal) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (!await isQQRunning()) return true;
    await delay(500, signal);
  }
  return !await isQQRunning();
}

async function stopQQ({ onProgress = () => {}, signal } = {}) {
  await delay(0, signal);
  if (!await isQQRunning()) return;
  onProgress('正在关闭 QQ，等待聊天数据库安全落盘…');
  await run('taskkill.exe', ['/IM', 'QQ.exe', '/T'], { timeout: 12000 });
  if (await waitUntilStopped(8000, signal)) return;
  onProgress('QQ 未正常退出，正在结束残留进程…');
  await run('taskkill.exe', ['/IM', 'QQ.exe', '/T', '/F'], { timeout: 12000 });
  if (!await waitUntilStopped(8000, signal)) {
    throw Object.assign(new Error('无法关闭 QQ。请手动完全退出 QQ 后重试。'), { code: 'QQ_STOP_FAILED' });
  }
}

function sourceSignature(sourcePath) {
  // SHM is lock coordination, not message content; it can keep changing forever.
  return ['', '-wal'].map((suffix) => {
    try {
      const stat = fs.statSync(`${sourcePath}${suffix}`);
      return `${stat.size}:${Math.trunc(stat.mtimeMs)}`;
    } catch {
      return 'missing';
    }
  }).join('|');
}

async function waitForDatabaseSettled(sourcePath, { signal, timeoutMs = 10000, quietMs = 1500 } = {}) {
  const deadline = Date.now() + timeoutMs;
  let unchangedSince = Date.now();
  let last = sourceSignature(sourcePath);
  while (Date.now() < deadline) {
    await delay(750, signal);
    const next = sourceSignature(sourcePath);
    if (next !== last) {
      last = next;
      unchangedSince = Date.now();
    }
    const journal = `${sourcePath}-journal`;
    if (!fs.existsSync(journal) && Date.now() - unchangedSince >= quietMs) return;
  }
  throw Object.assign(new Error('QQ 已退出，但聊天数据库仍在变化。请稍等片刻后重试。'), { code: 'SOURCE_STILL_BUSY' });
}

async function syncQQBeforeImport({ sourcePath, signal, onProgress = () => {}, syncTimeoutMs = 180000 } = {}) {
  const executable = await findQQExecutable();
  if (!executable) throw Object.assign(new Error('未找到 QQ.exe，请先安装或启动一次 QQ。'), { code: 'QQ_NOT_FOUND' });
  await stopQQ({ onProgress, signal });
  if (signal?.aborted) throw Object.assign(new Error('已取消更新聊天记录。'), { code: 'SOURCE_UPDATE_CANCELLED' });
  onProgress('正在启动 QQ 并同步聊天记录；如出现登录窗口，请登录当前账号…');
  const baseline = sourceSignature(sourcePath);
  const child = spawn(executable, [], { detached: true, stdio: 'ignore', windowsHide: false });
  let launchError;
  child.once('error', () => { launchError = true; });
  child.unref();
  const startedAt = Date.now();
  let last = baseline;
  let changedAt = 0;
  let lastChangeAt = startedAt;
  try {
    while (Date.now() - startedAt < syncTimeoutMs) {
      await delay(1000, signal);
      if (launchError) throw Object.assign(new Error('QQ 启动失败，请检查安装后重试。'), { code: 'QQ_START_FAILED' });
      if (!await isQQRunning()) {
        throw Object.assign(new Error('QQ 在同步完成前退出。请重新尝试并完成登录。'), { code: 'QQ_EXITED_DURING_SYNC' });
      }
      const next = sourceSignature(sourcePath);
      if (next !== last) {
        last = next;
        changedAt ||= Date.now();
        lastChangeAt = Date.now();
        onProgress('检测到聊天数据库更新，正在等待 QQ 完成同步…');
      }
      const elapsed = Date.now() - startedAt;
      onProgress(`正在等待 QQ 同步（${Math.floor(elapsed / 1000)} 秒）；请确认已登录目标账号…`);
      if (changedAt && elapsed >= 12000 && Date.now() - lastChangeAt >= 6000) break;
      if (!changedAt && elapsed >= 15000) {
        onProgress('未检测到本地数据库更新，将读取已有记录；无法确认在线历史是否完整。');
        break;
      }
    }
    if (Date.now() - startedAt >= syncTimeoutMs) {
      throw Object.assign(new Error('等待 QQ 登录或同步超时。请确认网络与账号状态后重试。'), { code: 'QQ_SYNC_TIMEOUT' });
    }
  } finally {
    await stopQQ({ onProgress });
  }
  onProgress('QQ 已退出，正在等待聊天数据库完成落盘…');
  await waitForDatabaseSettled(sourcePath, { signal });
  onProgress('聊天数据库已就绪，正在解密并更新本地索引…');
}

async function prepareQQDatabase({ sourcePath, signal, onProgress = () => {}, syncOnline = false } = {}, dependencies = {}) {
  const stop = dependencies.stopQQ || stopQQ;
  const settle = dependencies.waitForDatabaseSettled || waitForDatabaseSettled;
  const sync = dependencies.syncQQBeforeImport || syncQQBeforeImport;
  if (syncOnline) return sync({ sourcePath, signal, onProgress });
  onProgress('正在准备读取本机已有聊天记录…');
  await stop({ signal, onProgress });
  await settle(sourcePath, { signal });
  onProgress('本地数据库已就绪，正在解密并更新索引…');
}

module.exports = {
  delay,
  prepareQQDatabase,
  findQQExecutable,
  isQQRunning,
  sourceSignature,
  stopQQ,
  syncQQBeforeImport,
  waitForDatabaseSettled,
};
