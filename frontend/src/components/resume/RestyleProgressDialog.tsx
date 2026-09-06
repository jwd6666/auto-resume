import { Loader2, AlertTriangle, Check, X, RotateCw } from 'lucide-react';

export interface RestyleProgressState {
  status: 'running' | 'done' | 'error';
  error?: string;
}

interface Props {
  state: RestyleProgressState;
  onDismiss: () => void;
  onRetry?: () => void;
}

export function RestyleProgressDialog({ state, onDismiss, onRetry }: Props) {
  if (state.status === 'done') {
    return (
      <div className="fixed bottom-5 right-5 z-[70] w-80 max-w-[calc(100vw-40px)] animate-fade-in">
        <div className="rounded-lg border border-emerald-500/30 bg-surface-800/95 backdrop-blur shadow-2xl px-3 py-2.5 flex items-center gap-2">
          <Check size={15} className="text-emerald-400 shrink-0" />
          <p className="text-xs font-medium text-emerald-300 flex-1">简历重排完成</p>
          <button onClick={onDismiss} className="text-slate-500 hover:text-slate-300 shrink-0">
            <X size={13} />
          </button>
        </div>
      </div>
    );
  }

  if (state.status === 'error') {
    return (
      <div className="fixed bottom-5 right-5 z-[70] w-80 max-w-[calc(100vw-40px)] animate-fade-in">
        <div className="rounded-lg border border-red-500/30 bg-surface-800/95 backdrop-blur shadow-2xl px-3 py-2.5 flex items-start gap-2">
          <AlertTriangle size={15} className="text-red-400 shrink-0 mt-0.5" />
          <div className="flex-1 min-w-0">
            <p className="text-xs font-medium text-red-300">简历重排失败</p>
            <p className="text-[11px] text-red-300/70 mt-0.5 break-words">{state.error || '未知错误'}</p>
          </div>
          {onRetry && (
            <button onClick={onRetry} className="text-red-400 hover:text-red-300 shrink-0" title="重试">
              <RotateCw size={13} />
            </button>
          )}
          <button onClick={onDismiss} className="text-slate-500 hover:text-slate-300 shrink-0">
            <X size={13} />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed bottom-5 right-5 z-[70] w-80 max-w-[calc(100vw-40px)] animate-fade-in">
      <div className="rounded-lg border border-amber-500/30 bg-surface-800/95 backdrop-blur shadow-2xl px-3 py-2.5 flex items-center gap-2">
        <Loader2 size={15} className="animate-spin text-amber-400 shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium text-amber-300">简历重排中…</p>
          <p className="text-[11px] text-amber-300/60 mt-0.5">约 1-2 分钟，可继续其他操作</p>
        </div>
        <button onClick={onDismiss} className="text-slate-500 hover:text-slate-300 shrink-0" title="关闭提示（不中断重排）">
          <X size={13} />
        </button>
      </div>
    </div>
  );
}
