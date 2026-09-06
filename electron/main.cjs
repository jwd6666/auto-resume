/**
 * Electron 主进程。
 * - 开发期：直接连 vite dev server (5173)，后端由 npm dev:py 单独启动
 * - 生产期：spawn 打包好的 auto-resume-backend.exe（含 patchright + chromium）；renderer 加载 frontend/dist
 */
const { app, BrowserWindow, shell, ipcMain, globalShortcut } = require('electron');
const path = require('path');
const fs = require('fs');
const { spawn } = require('child_process');

const isDev = process.env.NODE_ENV === 'development';
const BACKEND_PORT = 8765;
const FRONTEND_URL_DEV = 'http://127.0.0.1:5173';

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
    env: { ...process.env, AUTORESUME_PORT: String(BACKEND_PORT) },
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
      const req = http.get(`http://127.0.0.1:${BACKEND_PORT}/health`, (res) => {
        if (res.statusCode === 200) {
          resolve(true);
        } else {
          retry();
        }
        res.resume();
      });
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

  // IPC: 在系统浏览器中打开本地 HTML 文件并发送 Ctrl+P 打印
  ipcMain.handle('open-local-file-and-print', async (_event, filePath) => {
    if (!filePath || !fs.existsSync(filePath)) return { ok: false, error: '文件不存在' };
    const { exec } = require('child_process');
    const platform = process.platform;
    try {
      if (platform === 'win32') {
        // Windows: 用 start 命令打开默认浏览器
        exec(`start "" "${filePath}"`);
        // 等待浏览器加载后发送 Ctrl+P
        setTimeout(() => {
          exec('powershell -Command "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.SendKeys]::SendWait(\'^p\')"');
        }, 2000);
      } else if (platform === 'darwin') {
        exec(`open "${filePath}"`);
        setTimeout(() => {
          exec(`osascript -e 'tell application "System Events" to keystroke "p" using command down'`);
        }, 2000);
      } else {
        exec(`xdg-open "${filePath}"`);
      }
      return { ok: true };
    } catch (e) {
      return { ok: false, error: String(e) };
    }
  });

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createMainWindow();
  });
});

function killBackend() {
  if (!pyProcess) return;
  try { pyProcess.kill(); } catch (_) { /* noop */ }
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
