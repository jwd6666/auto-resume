import { Eye, Play, Pause, Square, Edit2, Trash2, RefreshCw, LogIn, Plus } from 'lucide-react';
import clsx from 'clsx';
import type { TaskInfo } from '../../api/client';
import { cityLabel } from '../../constants/cities';
import { StatusBadge } from '../common/StatusBadge';

interface Props {
  tasks: TaskInfo[];
  selectedId?: string | null;
  onSelect: (id: string) => void;
  onViewAll: () => void;
  onCreateTask: () => void;
  onStart: (id: string) => void;
  onPause: (id: string) => void;
  onResume: (id: string) => void;
  onStop: (id: string) => void;
  onLogin: (id: string) => void;
  onEdit: (id: string) => void;
  onDelete: (id: string) => void;
  onRefreshLogin: (id: string) => void;
}

export function DashboardTasks({
  tasks, selectedId, onSelect, onViewAll, onCreateTask,
  onStart, onPause, onResume, onStop, onLogin, onEdit, onDelete, onRefreshLogin,
}: Props) {
  const displayTasks = tasks.slice(0, 4);

  return (
    <div className="card p-4 flex flex-col h-full animate-slide-up" style={{ animationDelay: '120ms' }}>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Eye size={16} className="text-brand-400" />
          <h3 className="text-sm font-semibold text-slate-200">自动招呼任务</h3>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={onCreateTask}
            className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium bg-brand-600 hover:bg-brand-500 text-white"
          >
            <Plus size={12} /> 新建任务
          </button>
          <button onClick={onViewAll} className="text-xs text-brand-400 hover:text-brand-300">
            查看全部 →
          </button>
        </div>
      </div>

      <div className="flex-1 space-y-2 overflow-y-auto scrollbar-thin pr-1">
        {displayTasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <div className="w-12 h-12 rounded-full bg-slate-800/60 flex items-center justify-center mb-2">
              <Eye size={20} className="text-slate-600" />
            </div>
            <p className="text-xs text-slate-500">暂无任务</p>
            <p className="text-[11px] text-slate-600 mt-0.5">点击右侧"创建新任务"开始</p>
          </div>
        ) : (
          displayTasks.map((t) => {
            const loggingIn = t.status === 'launching' || t.status === 'awaiting_login';
            const running = t.status === 'running';
            const paused = t.status === 'paused';
            const idle = !loggingIn && !running && !paused;
            const isSelected = t.id === selectedId;

            return (
              <div
                key={t.id}
                onClick={() => onSelect(t.id)}
                className={clsx(
                  'task-item group p-2.5 rounded-lg border cursor-pointer',
                  isSelected
                    ? 'border-brand-500 bg-brand-500/10'
                    : 'border-slate-700/40 bg-slate-900/40 hover:bg-slate-800/40 hover:border-slate-600/60'
                )}
              >
                <div className="flex items-center gap-2">
                  <div className="w-7 h-7 rounded-full bg-gradient-to-br from-brand-600 to-purple-500 flex items-center justify-center text-white text-[10px] font-bold shrink-0">
                    {t.name.charAt(0).toUpperCase()}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className="text-sm font-medium text-slate-200 truncate">{t.name}</span>
                      <StatusBadge status={t.status} />
                    </div>
                    <div className="text-[11px] text-slate-500 truncate">
                      {t.filter?.keyword || '(无关键词)'} · {cityLabel(t.filter?.city)}
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="text-xs text-slate-400 tabular-nums">{t.sent_today}/{t.daily_limit}</div>
                  </div>
                </div>

                {/* 操作按钮区 */}
                <div className="mt-2 flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
                  {/* 空闲 + 未登录：登录 + 开始 */}
                  {idle && !t.has_login && (
                    <>
                      <button
                        onClick={() => onLogin(t.id)}
                        className="px-2 py-1 text-xs rounded bg-cyan-600 hover:bg-cyan-500 flex items-center gap-1 font-medium"
                        title="仅登录账号"
                      >
                        <LogIn size={11} /> 登录
                      </button>
                      <button
                        onClick={() => onStart(t.id)}
                        className="px-2.5 py-1 text-xs rounded bg-brand-600 hover:bg-brand-500 flex items-center gap-1 font-medium"
                        title="开始任务"
                      >
                        <Play size={11} /> 开始
                      </button>
                    </>
                  )}

                  {/* 空闲 + 已登录：开始 + 刷新登录 */}
                  {idle && t.has_login && (
                    <>
                      <button
                        onClick={() => onStart(t.id)}
                        className="px-2.5 py-1 text-xs rounded bg-brand-600 hover:bg-brand-500 flex items-center gap-1 font-medium"
                      >
                        <Play size={11} /> 开始
                      </button>
                      <button
                        onClick={() => onRefreshLogin(t.id)}
                        className="p-1 rounded text-slate-500 hover:text-cyan-400 hover:bg-cyan-500/10"
                        title="刷新登录"
                      >
                        <RefreshCw size={13} />
                      </button>
                    </>
                  )}

                  {/* 登录中：停止 */}
                  {loggingIn && (
                    <button
                      onClick={() => onStop(t.id)}
                      className="px-2 py-1 text-xs rounded bg-slate-700 hover:bg-slate-600 flex items-center gap-1"
                    >
                      <Square size={11} /> 停止
                    </button>
                  )}

                  {/* 运行中：暂停 + 停止 */}
                  {running && (
                    <>
                      <button
                        onClick={() => onPause(t.id)}
                        className="px-2 py-1 text-xs rounded bg-amber-600 hover:bg-amber-500 flex items-center gap-1 font-medium"
                      >
                        <Pause size={11} /> 暂停
                      </button>
                      <button
                        onClick={() => onStop(t.id)}
                        className="px-2 py-1 text-xs rounded bg-slate-700 hover:bg-slate-600 flex items-center gap-1"
                      >
                        <Square size={11} /> 停止
                      </button>
                    </>
                  )}

                  {/* 暂停中：继续 + 停止 */}
                  {paused && (
                    <>
                      <button
                        onClick={() => onResume(t.id)}
                        className="px-2.5 py-1 text-xs rounded bg-brand-600 hover:bg-brand-500 flex items-center gap-1 font-medium"
                      >
                        <Play size={11} /> 继续
                      </button>
                      <button
                        onClick={() => onStop(t.id)}
                        className="px-2 py-1 text-xs rounded bg-slate-700 hover:bg-slate-600 flex items-center gap-1"
                      >
                        <Square size={11} /> 停止
                      </button>
                    </>
                  )}

                  {/* 编辑 + 删除 */}
                  <button
                    onClick={() => onEdit(t.id)}
                    className="p-1 rounded text-slate-500 hover:text-brand-400 hover:bg-brand-500/10 ml-auto"
                    title="编辑"
                  >
                    <Edit2 size={13} />
                  </button>
                  <button
                    onClick={() => onDelete(t.id)}
                    className="p-1 rounded text-slate-500 hover:text-red-400 hover:bg-red-500/10"
                    title="删除"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
