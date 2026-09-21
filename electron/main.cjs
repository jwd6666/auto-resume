/**
 * Electron 主进程。
 * - 开发期：直接连 vite dev server (5173)，后端由 npm dev:py 单独启动
 * - 生产期：spawn 打包好的 auto-resume-backend.exe（含 patchright + chromium）；renderer 加载 frontend/dist
 */
const { app, BrowserWindow, shell, ipcMain, globalShortcut } = require('electron');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const { spawn } = require('child_process');

const isDev = process.env.NODE_ENV === 'development';
const BACKEND_PORT = 8765;
const FRONTEND_URL_DEV = 'http://127.0.0.1:5173';
const PROD_CLOUD_URL = 'https://agentht.jwdo.top';
const DEV_CLOUD_URL = 'http://127.0.0.1:8000';
// 云端管控服务器：开发环境 → 本地 127.0.0.1:8000；打包后 → 生产云端地址
// 环境变量最高优先（可覆盖），其次 cloud-config.json，最后按环境自动选择
function resolveCloudUrl() {
  if (process.env.AUTORESUME_CLOUD_URL) return process.env.AUTORESUME_CLOUD_URL;
  try {
    const cfg = JSON.parse(fs.readFileSync(path.join(__dirname, 'cloud-config.json'), 'utf-8'));
    if (cfg.cloudUrl) return cfg.cloudUrl;
  } catch { /* 无配置文件（未执行过打包） */ }
  return isDev ? DEV_CLOUD_URL : PROD_CLOUD_URL;
}
const CLOUD_URL = resolveCloudUrl();
// 应用版本号：与 package.json 的 version 一致，透传给 sidecar 用于更新检查对比
const APP_VERSION = app.getVersion() || '0.0.0-dev';
// 本地 sidecar 访问令牌：每次启动随机生成，注入 sidecar 并经 IPC 暴露给 renderer，
// 防止本机其他程序直接调用 sidecar 接口（读取简历、任务配置等）
const API_TOKEN = crypto.randomBytes(32).toString('hex');

let mainWindow = null;
let pyProcess = null;

/**
 * 打包后的 backend 路径。electron-builder 会把 backend/dist/auto-resume-backend
 * 整个目录拷到 resources/backend，里面是 PyInstaller onedir 输出（含 ms-playwright）。
 * 开发期不进入此函数。
 *
 * 跨平台：Windows 是 .exe，macOS/Linux 是无扩展名的可执行文件。
 */
function resolveBackendExePath() {
  const exeName = process.platform === 'win32' ? 'auto-resume-backend.exe' : 'auto-resume-backend';
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'backend', exeName);
  }
  return path.join(__dirname, '..', 'backend', 'dist', 'auto-resume-backend', exeName);
}

function startPythonBackend() {
  if (isDev) return;
  const exePath = resolveBackendExePath();
  if (!fs.existsSync(exePath)) {
    console.error('[backend] 未找到 backend exe，请先执行 npm run build:py');
    return;
  }
  const logFile = fs.openSync(path.join(app.getPath('userData'), 'backend.log'), 'a');
  pyProcess = spawn(exePath, [], {
    cwd: path.dirname(exePath),
    stdio: ['ignore', logFile, logFile],
    windowsHide: true,
    env: { ...process.env, AUTORESUME_PORT: String(BACKEND_PORT), AUTORESUME_CLOUD_URL: CLOUD_URL, AUTORESUME_APP_VERSION: APP_VERSION, AUTORESUME_API_TOKEN: API_TOKEN },
  });
  pyProcess.on('exit', (code) => {
    console.log(`[backend] exited with ${code}`);
    pyProcess = null;
  });
}

function waitForBackend(maxRetries = 30, interval = 1000) {
  return new Promise((resolve) => {
    const http = require('http');
    let attempts = 0;
    function check() {
      attempts++;
      const req = http.get(
        `http://127.0.0.1:${BACKEND_PORT}/health`,
        { headers: { 'X-Api-Token': API_TOKEN } },
        (res) => {
          if (res.statusCode === 200) {
            resolve(true);
          } else {
            retry();
          }
          res.resume();
        }
      );
      req.on('error', () => retry());
      req.setTimeout(2000, () => { req.destroy(); retry(); });
    }
    function retry() {
      if (attempts >= maxRetries) {
        resolve(false);
      } else {
        setTimeout(check, interval);
      }
    }
    check();
  });
}

function createMainWindow() {
  mainWindow = new BrowserWindow({
    width: 1180,
    height: 820,
    minWidth: 960,
    minHeight: 640,
    title: 'BOSS 直聘 自动招呼助手',
    backgroundColor: '#0f172a',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      webviewTag: true,
      preload: path.join(__dirname, 'preload.cjs'),
    },
  });

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });

  if (isDev) {
    mainWindow.loadURL(FRONTEND_URL_DEV);
    mainWindow.webContents.openDevTools({ mode: 'detach' });
  } else {
    // 打包后：renderer 走 frontend/dist 静态文件
    const indexHtml = app.isPackaged
      ? path.join(process.resourcesPath, 'app.asar.unpacked', 'frontend', 'dist', 'index.html')
      : path.join(__dirname, '..', 'frontend', 'dist', 'index.html');
    // electron-builder 默认会把 frontend/dist 打入 asar；通过 files 字段保证可读取
    mainWindow.loadFile(fs.existsSync(indexHtml) ? indexHtml : path.join(__dirname, '..', 'frontend', 'dist', 'index.html'));
  }
}

app.whenReady().then(async () => {
  // 禁用代理，避免 Clash 等系统代理拦截 localhost 请求导致 Failed to fetch
  const { session, dialog } = require('electron');
  session.defaultSession.setProxy({ proxyRules: 'direct://' });

  startPythonBackend();

  if (!isDev) {
    const ok = await waitForBackend();
    if (!ok) {
      dialog.showErrorBox(
        '后端启动失败',
        `无法连接到 http://127.0.0.1:${BACKEND_PORT}/health\n\n` +
        '可能原因：\n' +
        '1. 端口被其他程序占用\n' +
        '2. 杀毒软件拦截了后端进程\n' +
        '3. 后端 exe 损坏\n\n' +
        `日志文件：${path.join(app.getPath('userData'), 'backend.log')}`
      );
    }
  }

  createMainWindow();

  // IPC: 同步返回 sidecar 访问令牌（renderer 的 fetch/WS 需携带）
  ipcMain.on('get-api-token', (event) => {
    event.returnValue = API_TOKEN;
  });

  // IPC: 在系统浏览器中打开本地 HTML 文件并发送 Ctrl+P 打印
  // 安全：仅允许打开简历目录内的 .html 文件，路径全部来自后端返回值，
  // 且用 shell.openPath 打开而非拼接 shell 命令（防命令注入）
  const resumeStoreRoot = () =>
    isDev
      ? path.join(__dirname, '..', 'backend', 'data', 'resume_store')
      : path.join(app.getPath('appData'), 'AutoResume', 'resume_store');

  ipcMain.handle('open-local-file-and-print', async (_event, filePath) => {
    if (typeof filePath !== 'string' || !path.isAbsolute(filePath) || !fs.existsSync(filePath)) {
      return { ok: false, error: '文件不存在' };
    }
    const resolved = path.resolve(filePath);
    const rel = path.relative(resumeStoreRoot(), resolved);
    if (rel.startsWith('..') || path.isAbsolute(rel) || !resolved.toLowerCase().endsWith('.html')) {
      return { ok: false, error: '仅允许打开简历目录内的 HTML 文件' };
    }
    try {
      const openErr = await shell.openPath(resolved);
      if (openErr) return { ok: false, error: openErr };
      // 等待浏览器加载后发送打印快捷键（命令为静态字符串，无用户输入，无注入风险）
      const { exec } = require('child_process');
      const platform = process.platform;
      setTimeout(() => {
        try {
          if (platform === 'win32') {
            exec("powershell -Command \"Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait('^p')\"");
          } else if (platform === 'darwin') {
            exec("osascript -e 'tell application \"System Events\" to keystroke \"p\" using command down'");
          }
        } catch (_) { /* noop */ }
      }, 2000);
      return { ok: true };
    } catch (e) {
      return { ok: false, error: String(e) };
    }
  });

  // IPC: 在系统默认浏览器中打开外部链接（更新下载等）
  ipcMain.handle('open-external', async (_event, url) => {
    if (typeof url !== 'string' || !/^https?:\/\//i.test(url)) {
      return { ok: false, error: '仅支持 http/https 链接' };
    }
    await shell.openExternal(url);
    return { ok: true };
  });

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
  });
});

function killBackend() {
  if (!pyProcess) return;
  const pid = pyProcess.pid;
  try {
    if (process.platform === 'win32' && pid) {
      // TerminateProcess 不会终止子进程，必须用 taskkill /T 结束整个进程树
      // （backend 会 spawn Chromium，残留进程会锁住 ms-playwright 文件导致覆盖安装失败）
      require('child_process').exec(`taskkill /PID ${pid} /T /F`);
    } else {
      pyProcess.kill();
    }
  } catch (_) { /* noop */ }
  pyProcess = null;
}

app.on('window-all-closed', () => {
  // macOS 习惯：关闭最后一个窗口不退出 app；其他平台直接退出
  if (process.platform === 'darwin') return;
  killBackend();
  app.quit();
});

// macOS 上 quit 时确保后端被回收
app.on('before-quit', killBackend);
app.on('will-quit', killBackend);
