import { useState, useEffect, useRef } from 'react';
import clsx from 'clsx';
import { Play, Pause, Square, Trash2, LogIn, RefreshCw, Pencil, ChevronDown, FileText } from 'lucide-react';
import type { TaskInfo } from '../api/client';
import { openTaskWS } from '../api/client';
import { cityLabel } from '../constants/cities';
import { StatusBadge } from './StatusBadge';

interface LogEntry { ts: string; level: string; msg: string; }

interface Props {
  task: TaskInfo;
  active: boolean;
  onSelect: () => void;
  onStart: () => void;
  onPause: () => void;
  onResume: () => void;
  onStop: () => void;
  onLogin: () => void;
  onEdit: () => void;
  onDelete: () => void;
}

function InlineLogs({ taskId }: { taskId: string }) {
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setLogs([]);
    const ws = openTaskWS(taskId, (m) => {
      if (m.type === 'snapshot') {
        setLogs(m.logs || []);
      } else if (m.type === 'log') {
        setLogs((prev) => [...prev.slice(-199), m.entry]);
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
  }, [taskId]);

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight });
  }, [logs.length]);

  return (
    <div className="mt-2 rounded-lg border border-slate-700/50 bg-slate-950/60 overflow-hidden">
      <div className="flex items-center gap-1.5 px-2.5 py-1.5 border-b border-slate-700/40">
        <FileText size={11} className="text-brand-400" />
        <span className="text-[11px] text-slate-400 font-medium">运行日志</span>
      </div>
      <div ref={logRef} className="max-h-32 overflow-y-auto scrollbar-thin px-2.5 py-1.5 font-mono text-[11px] leading-relaxed space-y-0.5">
        {logs.length === 0 ? (
          <div className="text-[11px] text-slate-600 py-2 text-center">暂无日志</div>
        ) : (
          logs.slice(-50).map((l, i) => (
            <div key={i} className="flex gap-2">
              <span className="text-slate-600 shrink-0">{l.ts?.slice(11, 19) || ''}</span>
              <span className={clsx(
                'w-14 shrink-0',
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

export function TaskCard(props: Props) {
  const { task, active } = props;
  const [expanded, setExpanded] = useState(false);
  const loggingIn = task.status === 'launching' || task.status === 'awaiting_login';
  const running = task.status === 'running';
  const paused = task.status === 'paused';
  const idle = !loggingIn && !running && !paused;

  return (
    <div
      onClick={props.onSelect}
      className={clsx(
        'cursor-pointer rounded-lg border p-3 transition-colors',
        active ? 'border-brand-500 bg-brand-500/10' : 'border-slate-700 hover:border-slate-500 bg-slate-900/40'
      )}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-medium truncate">{task.name}</span>
          <StatusBadge status={task.status} />
          {!task.has_login && idle && (
            <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-500/20 text-amber-300">未登录</span>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <div className="text-xs text-slate-400 tabular-nums">{task.sent_today}/{task.daily_limit}</div>
          <button
            onClick={(e) => { e.stopPropagation(); setExpanded(v => !v); }}
            className={clsx(
              'p-0.5 rounded text-slate-500 hover:text-slate-300 hover:bg-slate-700/50 transition-transform',
              expanded && 'rotate-180'
            )}
            title={expanded ? '收起日志' : '展开日志'}
          >
            <ChevronDown size={14} />
          </button>
        </div>
      </div>

      {/* 子任务进度：每个子任务一行 关键词 · 城市名 · 已发/目标 */}
      {task.sub_tasks && task.sub_tasks.length > 0 ? (
        <div className="mt-1 space-y-0.5">
          {task.sub_tasks.map((sub, i) => {
            const sent = task.sub_sent_today?.[i] ?? 0;
            const isCurrent = running && task.current_sub_index === i;
            return (
              <div
                key={i}
                className={clsx(
                  'text-xs truncate flex items-center gap-1',
                  isCurrent ? 'text-brand-300' : 'text-slate-400'
                )}
              >
                <span className="opacity-60">#{i + 1}</span>
                <span className="truncate">{sub.filter.keyword || '(空)'}</span>
                <span className="opacity-60">· {cityLabel(sub.filter.city)}</span>
                <span className="ml-auto shrink-0">
                  {sent}/{sub.limit}
                </span>
              </div>
            );
          })}
        </div>
      ) : task.filter ? (
        <div className="mt-1 text-xs text-slate-400 truncate">
          {task.filter.keyword} · {cityLabel(task.filter.city)}
        </div>
      ) : null}

      <div className="mt-2 flex gap-1.5" onClick={(e) => e.stopPropagation()}>
        {/* 未登录、空闲：登录 + 开始 并排（开始会自动处理登录流程） */}
        {idle && !task.has_login && (
          <>
            <button
              onClick={props.onLogin}
              className="px-3 py-1 text-xs rounded bg-cyan-600 hover:bg-cyan-500 flex items-center gap-1 font-medium"
              title="仅登录账号，登录完成自动关闭浏览器"
            >
              <LogIn size={12} /> 登录
            </button>
            <button
              onClick={props.onStart}
              className="px-3 py-1 text-xs rounded bg-brand-600 hover:bg-brand-500 flex items-center gap-1 font-medium"
              title="开始任务（未登录时会先打开浏览器登录，再自动招呼）"
            >
              <Play size={12} /> 开始
            </button>
          </>
        )}

        {/* 已登录、空闲：开始 + 重新登录（小图标） */}
        {idle && task.has_login && (
          <>
            <button
              onClick={props.onStart}
              className="px-3 py-1 text-xs rounded bg-brand-600 hover:bg-brand-500 flex items-center gap-1 font-medium"
            >
              <Play size={12} /> 开始
            </button>
            <button
              onClick={props.onLogin}
              className="px-2 py-1 text-xs rounded text-slate-400 hover:text-cyan-300 hover:bg-cyan-500/10 flex items-center gap-1"
              title="重新登录（cookie 过期或换号时使用）"
            >
              <RefreshCw size={12} />
            </button>
          </>
        )}

        {/* 登录中：只能停止 */}
        {loggingIn && (
          <button onClick={props.onStop} className="px-2 py-1 text-xs rounded bg-slate-700 hover:bg-slate-600 flex items-center gap-1">
            <Square size={12} /> 停止登录
          </button>
        )}

        {/* 运行中：暂停 + 停止 */}
        {running && (
          <>
            <button onClick={props.onPause} className="px-2 py-1 text-xs rounded bg-amber-600 hover:bg-amber-500 flex items-center gap-1">
              <Pause size={12} /> 暂停
            </button>
            <button onClick={props.onStop} className="px-2 py-1 text-xs rounded bg-slate-700 hover:bg-slate-600 flex items-center gap-1">
              <Square size={12} /> 停止
            </button>
          </>
        )}

        {/* 暂停：继续 + 停止 */}
        {paused && (
          <>
            <button onClick={props.onResume} className="px-2 py-1 text-xs rounded bg-brand-600 hover:bg-brand-500 flex items-center gap-1">
              <Play size={12} /> 继续
            </button>
            <button onClick={props.onStop} className="px-2 py-1 text-xs rounded bg-slate-700 hover:bg-slate-600 flex items-center gap-1">
              <Square size={12} /> 停止
            </button>
          </>
        )}

        <button
          onClick={props.onEdit}
          className="ml-auto px-2 py-1 text-xs rounded text-slate-400 hover:text-cyan-300 hover:bg-cyan-500/10 flex items-center gap-1"
          title="编辑任务（运行中会先停止）"
        >
          <Pencil size={12} />
        </button>
        <button
          onClick={props.onDelete}
          className="px-2 py-1 text-xs rounded text-slate-400 hover:text-red-400 hover:bg-red-500/10 flex items-center gap-1"
          title="删除任务"
        >
          <Trash2 size={12} />
        </button>
      </div>

      {/* 展开的日志面板 */}
      {expanded && <InlineLogs taskId={task.id} />}
    </div>
  );
}
