/**
 * Preload: 暴露安全的 IPC 桥接方法给 renderer 进程。
 */
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('autoresume', {
  apiBase: 'http://127.0.0.1:8765',

  /** 在系统默认浏览器中打开本地 HTML 文件，并发送 Ctrl+P 触发打印 */
  openLocalFileAndPrint: (filePath) => ipcRenderer.invoke('open-local-file-and-print', filePath),
});
