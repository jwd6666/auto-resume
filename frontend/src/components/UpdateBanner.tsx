import { useState } from 'react';
import { AlertTriangle, Download, ExternalLink, X } from 'lucide-react';
import { openDownloadUrl, type UpdateInfo } from '../api/updateApi';

interface UpdateBannerProps {
  update: UpdateInfo;
  force: boolean;
  currentVersion: string;
  onSkip: (version: string) => void;
  onDismiss: () => void;
}

export function UpdateBanner({ update, force, currentVersion, onSkip, onDismiss }: UpdateBannerProps) {
  const [expanded, setExpanded] = useState(false);
  const notesLines = (update.notes || '').split('\n').map((l) => l.trim()).filter(Boolean);

  return (
    <div
      className={`px-5 py-2.5 border-b flex items-start gap-3 animate-fade-in ${
        force
          ? 'bg-red-500/15 border-red-500/40'
          : 'bg-brand-500/10 border-brand-500/25'
      }`}
    >
      {force ? (
        <AlertTriangle size={17} className="text-red-400 shrink-0 mt-0.5" />
      ) : (
        <Download size={16} className="text-brand-400 shrink-0 mt-0.5" />
      )}

      <div className="flex-1 min-w-0 text-sm">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={force ? 'text-red-300 font-semibold' : 'text-brand-300 font-semibold'}>
            {force ? '重要更新' : '发现新版本'} v{update.version}
          </span>
          <span className="text-xs text-slate-500">当前 v{currentVersion}</span>
          {notesLines.length > 0 && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="text-xs text-slate-400 hover:text-slate-200 underline underline-offset-2"
            >
              {expanded ? '收起' : '查看更新内容'}
            </button>
          )}
        </div>
        {expanded && notesLines.length > 0 && (
          <ul className="mt-1.5 space-y-0.5 text-xs text-slate-400 list-disc list-inside">
            {notesLines.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex items-center gap-2 shrink-0">
        <button
          onClick={() => openDownloadUrl(update.download_url)}
          className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-white transition-colors ${
            force
              ? 'bg-red-500 hover:bg-red-400'
              : 'bg-gradient-to-r from-brand-600 to-brand-500 hover:brightness-110'
          }`}
        >
          <ExternalLink size={13} /> 前往下载
        </button>
        {!force && (
          <>
            <button
              onClick={() => onSkip(update.version)}
              className="px-2 py-1.5 rounded-lg text-xs text-slate-500 hover:text-slate-300"
              title="此版本不再提醒"
            >
              跳过此版本
            </button>
            <button
              onClick={onDismiss}
              className="w-6 h-6 flex items-center justify-center rounded text-slate-500 hover:text-slate-300 hover:bg-white/5"
              title="本次不提醒"
            >
              <X size={14} />
            </button>
          </>
        )}
      </div>
    </div>
  );
}
