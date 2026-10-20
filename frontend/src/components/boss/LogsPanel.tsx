import { useState, useEffect, useRef } from 'react';
import { FileText, Inbox } from 'lucide-react';
import clsx from 'clsx';
import type { TaskInfo } from '../../api/client';
import { openTaskWS } from '../../api/client';

interface LogEntry { ts: string; level: string; msg: string; }

interface Props {
  selectedTask: TaskInfo | null;
}

export function LogsPanel({ selectedTask }: Props) {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setLogs([]);
    if (wsRef.current) { wsRef.current.close(); wsRef.current = null; }

    if (!selectedTask) return;

    const taskId = selectedTask.id;

    const ws = openTaskWS(taskId, (m) => {
      if (m.type === 'snapshot') {
        setLogs(m.logs || []);
      } else if (m.type === 'log') {
        setLogs((prev) => [...prev.slice(-499), m.entry]);
      }
    });
    wsRef.current = ws;

    const ping = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send('ping');
    }, 25_000);

    return () => {
      clearInterval(ping);
      ws.close();
      wsRef.current = null;
    };
  }, [selectedTask?.id]);

  // 自动滚动到底部
  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [logs.length]);

  return (
    <div className="card p-4 flex flex-col h-[420px] animate-slide-up" style={{ animationDelay: '160ms' }}>
      {/* 标题 + 当前任务名 */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          {selectedTask ? (
            <>
              <div className="w-5 h-5 rounded-full bg-gradient-to-br from-brand-600 to-purple-500 flex items-center justify-center text-white text-[9px] font-bold shrink-0">
                {selectedTask.name.charAt(0).toUpperCase()}
              </div>
              <span className="text-xs text-slate-300 truncate">{selectedTask.name}</span>
            </>
          ) : (
            <span className="text-xs text-slate-500">未选中任务</span>
          )}
        </div>
      </div>

      {/* Tab */}
      <div className="flex items-center gap-4 mb-3 border-b border-slate-700/50">
        <button
          className="flex items-center gap-1.5 pb-2 text-sm font-medium relative text-slate-100"
        >
          <FileText size={14} /> 运行日志
          <span className="absolute -bottom-px left-0 right-0 h-0.5 bg-gradient-to-r from-brand-500 to-purple-500 rounded-full" />
        </button>
      </div>

      {/* 日志内容 */}
      <div ref={logRef} className="flex-1 min-h-0 overflow-y-auto scrollbar-thin font-mono text-[11px] leading-relaxed space-y-0.5">
        {!selectedTask ? (
          <div className="h-full flex flex-col items-center justify-center text-center py-6">
            <div className="w-10 h-10 rounded-full bg-slate-800/60 flex items-center justify-center mb-2">
              <Inbox size={18} className="text-slate-600" />
            </div>
            <p className="text-xs text-slate-500">未选中任务</p>
            <p className="text-[11px] text-slate-600 mt-0.5">请在左侧"自动招呼任务"中选择一个任务</p>
          </div>
        ) : logs.length === 0 ? (
          <div className="h-full flex flex-col items-center justify-center text-center py-6">
            <div className="w-10 h-10 rounded-full bg-slate-800/60 flex items-center justify-center mb-2">
              <Inbox size={18} className="text-slate-600" />
            </div>
            <p className="text-xs text-slate-500">暂无运行日志</p>
            <p className="text-[11px] text-slate-600 mt-0.5">任务运行记录将显示在这里</p>
          </div>
        ) : (
          logs.map((l, i) => (
            <div key={i} className="flex gap-2">
              <span className="text-slate-600 shrink-0">{l.ts?.slice(11, 19) || ''}</span>
              <span className={clsx(
                'w-16 shrink-0',
                l.level === 'ERROR' && 'text-red-400',
                l.level === 'WARN' && 'text-amber-300',
                l.level === 'SUCCESS' && 'text-emerald-300',
                l.level === 'INFO' && 'text-slate-400',
              )}>{l.level}</span>
              <span className="text-slate-300 break-all">{l.msg}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
