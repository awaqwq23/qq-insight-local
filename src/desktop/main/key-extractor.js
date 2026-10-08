const fs = require('node:fs');
const path = require('node:path');
const { spawn } = require('node:child_process');

const HELPER_RELATIVE_PATH = path.join(
  'qq-win-db-key-master',
  'scripts',
  'windows',
  'ntqq',
  'windows_ntqq_get_key.ps1',
);

function uniquePaths(values) {
  const seen = new Set();
  return values.filter((value) => {
    if (!value) return false;
    const normalized = path.resolve(value).toLowerCase();
    if (seen.has(normalized)) return false;
    seen.add(normalized);
    return true;
  });
}

function findKeyHelper({ appPath, resourcesPath, portableDir, executableDir } = {}) {
  const roots = uniquePaths([
    process.env.QQ_INSIGHT_KEY_HELPER && path.dirname(process.env.QQ_INSIGHT_KEY_HELPER),
    appPath,
    portableDir,
    portableDir && path.dirname(portableDir),
    portableDir && path.dirname(path.dirname(portableDir)),
    executableDir,
    executableDir && path.dirname(executableDir),
    executableDir && path.dirname(path.dirname(executableDir)),
    resourcesPath && path.dirname(resourcesPath),
    resourcesPath && path.dirname(path.dirname(resourcesPath)),
    resourcesPath && path.dirname(path.dirname(path.dirname(resourcesPath))),
    path.resolve(__dirname, '..', '..', '..'),
  ]);
  const explicit = process.env.QQ_INSIGHT_KEY_HELPER;
  const candidates = uniquePaths([
    explicit,
    ...roots.flatMap((root) => [path.join(root, 'tools', HELPER_RELATIVE_PATH), path.join(root, HELPER_RELATIVE_PATH)]),
  ]);
  return candidates.find((candidate) => fs.existsSync(candidate) && fs.statSync(candidate).isFile()) || '';
}

function parseExtractedKey(output) {
  const matches = [...String(output).matchAll(/加密密钥:\s*([\x20-\x7e]{16})(?:\s|$)/g)];
  return matches.at(-1)?.[1] || '';
}

function safeProgressMessage(output, emitted) {
  const stages = [
    ['正在自动检测已安装的QQ', '正在检测 QQ 安装与版本…'],
    ['=== 静态分析结果 ===', '已定位加密函数，正在启动专用 QQ 进程…'],
    ['正在启动 QQ 进程并附加调试器', 'QQ 正在启动；若出现登录窗口，请登录需要导入的账号。'],
    ['QQ 进程已启动', '正在等待 QQ 初始化账号数据库，请不要关闭新启动的 QQ。'],
    ['wrapper.node 已加载', 'QQ 组件已加载，正在等待数据库密钥…'],
    ['找到密钥:', '已获取密钥，正在验证并导入聊天记录…'],
  ];
  for (const [marker, message] of stages) {
    if (output.includes(marker) && !emitted.has(marker)) {
      emitted.add(marker);
      return message;
    }
  }
  return '';
}

function terminateProcessTree(child) {
  if (!child || child.killed || !child.pid) return;
  if (process.platform === 'win32') {
    const killer = spawn('taskkill.exe', ['/PID', String(child.pid), '/T', '/F'], {
      windowsHide: true,
      stdio: 'ignore',
    });
    killer.unref();
  } else {
    child.kill('SIGKILL');
  }
}

function extractNtqqDatabaseKey(options = {}) {
  const scriptPath = findKeyHelper(options);
  if (!scriptPath) {
    return Promise.reject(Object.assign(new Error('未找到本机 NTQQ 密钥提取助手。请将 qq-win-db-key-master 放在项目 tools 目录或便携程序旁，或设置 QQ_INSIGHT_KEY_HELPER 后重试。'), {
      code: 'KEY_HELPER_NOT_FOUND',
    }));
  }

  const powershell = path.join(
    process.env.SystemRoot || 'C:\\Windows',
    'System32',
    'WindowsPowerShell',
    'v1.0',
    'powershell.exe',
  );
  return new Promise((resolve, reject) => {
    const onProgress = typeof options.onProgress === 'function' ? options.onProgress : () => {};
    const timeoutMs = Number.isFinite(options.timeoutMs) ? options.timeoutMs : 2 * 60 * 1000;
    const signal = options.signal;
    let settled = false;
    let waitingNotice;
    const child = spawn(powershell, [
      '-NoLogo',
      '-NoProfile',
      '-NonInteractive',
      '-ExecutionPolicy',
      'Bypass',
      '-Command',
      '$global:LASTEXITCODE=0; & $env:QQ_INSIGHT_KEY_SCRIPT',
    ], {
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...process.env, QQ_INSIGHT_KEY_SCRIPT: scriptPath },
    });
    let output = '';
    let outputBytes = 0;
    const emitted = new Set();
    const maxOutputBytes = 2 << 20;
    const cleanup = () => {
      clearTimeout(timeout);
      clearTimeout(waitingNotice);
      signal?.removeEventListener('abort', abort);
    };
    const fail = (error, terminate = false) => {
      if (settled) return;
      settled = true;
      cleanup();
      if (terminate) terminateProcessTree(child);
      output = '';
      reject(error);
    };
    const succeed = (key) => {
      if (settled) return;
      settled = true;
      cleanup();
      output = '';
      resolve(key);
    };
    const abort = () => fail(Object.assign(new Error('已取消自动获取数据库密钥。'), {
      code: 'KEY_EXTRACTION_CANCELLED',
    }), true);
    onProgress('正在启动本机密钥助手…');
    const timeout = setTimeout(() => {
      fail(Object.assign(new Error('两分钟内未取得数据库密钥。请完全退出所有 QQ 进程后重试，并在新出现的 QQ 窗口登录目标账号。'), {
        code: 'KEY_EXTRACTION_TIMEOUT',
      }), true);
    }, timeoutMs);
    waitingNotice = setTimeout(() => {
      if (!settled) onProgress('仍在等待 QQ 登录或账号数据库初始化；可点击“取消取钥”立即停止。');
    }, 15 * 1000);
    if (signal?.aborted) {
      abort();
      return;
    }
    signal?.addEventListener('abort', abort, { once: true });
    const append = (chunk) => {
      outputBytes += chunk.length;
      if (outputBytes <= maxOutputBytes) {
        output += chunk.toString('utf8');
        const message = safeProgressMessage(output, emitted);
        if (message) onProgress(message);
      }
    };
    child.stdout.on('data', append);
    child.stderr.on('data', append);
    child.on('error', () => {
      fail(Object.assign(new Error('无法启动本机 NTQQ 密钥提取助手。'), {
        code: 'KEY_HELPER_START_FAILED',
      }));
    });
    child.on('close', () => {
      if (settled) return;
      const key = parseExtractedKey(output);
      if (!key) {
        fail(Object.assign(new Error('未能自动取得该账号的数据库密钥。请完全退出现有 QQ，再点击重试，并在新启动的 QQ 窗口登录目标账号。'), {
          code: 'KEY_EXTRACTION_FAILED',
        }));
        return;
      }
      succeed(key);
    });
  });
}

module.exports = { extractNtqqDatabaseKey, findKeyHelper, parseExtractedKey, safeProgressMessage };
