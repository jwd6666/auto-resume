import { AlertTriangle, ExternalLink } from 'lucide-react';
import { openDownloadUrl, type UpdateInfo } from '../../api/updateApi';

interface ForceUpdateGateProps {
  update: UpdateInfo;
  currentVersion: string;
}

/** 强制更新拦截页：覆盖整个应用，仅允许前往下载新版本。 */
export function ForceUpdateGate({ update, currentVersion }: ForceUpdateGateProps) {
  const notesLines = (update.notes || '').split('\n').map((l) => l.trim()).filter(Boolean);

  return (
    <div className="h-full flex items-center justify-center bg-surface-850 p-6 animate-fade-in">
      <div className="card p-8 max-w-md w-full text-center">
        <div className="w-16 h-16 rounded-2xl bg-red-500/15 flex items-center justify-center mx-auto mb-5">
          <AlertTriangle size={30} className="text-red-400" />
        </div>
        <h1 className="text-lg font-bold text-slate-100">需要更新后才能继续使用</h1>
        <p className="text-sm text-slate-400 mt-2">
          当前版本 v{currentVersion} 已停用，请下载并安装 <span className="text-slate-200 font-medium">v{update.version}</span> 后重新打开应用。
        </p>
        {notesLines.length > 0 && (
          <ul className="mt-4 text-left text-xs text-slate-400 space-y-1 border border-slate-800 rounded-lg p-3 max-h-40 overflow-y-auto scrollbar-thin list-disc list-inside">
            {notesLines.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        )}
        <button
          onClick={() => openDownloadUrl(update.download_url)}
          className="mt-6 w-full inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-semibold text-white bg-red-500 hover:bg-red-400 transition-colors"
        >
          <ExternalLink size={15} /> 前往下载 v{update.version}
        </button>
        <p className="text-[11px] text-slate-600 mt-3">下载完成后安装新版本即可恢复使用</p>
      </div>
    </div>
  );
}
