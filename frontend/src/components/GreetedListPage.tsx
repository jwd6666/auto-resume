import { useEffect, useState, useCallback } from 'react';
import {
  MessageSquare, Trash2, ChevronDown, ChevronRight, Loader2,
} from 'lucide-react';
import clsx from 'clsx';
import { agentApi, type GreetedItem } from '../api/agentApi';

function formatTime(iso: string) {
  if (!iso) return '';
  const d = new Date(iso);
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

function getDayLabel(day: string) {
  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
  if (day === todayStr) return '今天';
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const yesterdayStr = `${yesterday.getFullYear()}-${String(yesterday.getMonth() + 1).padStart(2, '0')}-${String(yesterday.getDate()).padStart(2, '0')}`;
  if (day === yesterdayStr) return '昨天';
  return day;
}

export function GreetedListPage() {
  const [items, setItems] = useState<GreetedItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [batchMode, setBatchMode] = useState(false);
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async () => {
    try {
      const list = await agentApi.listGreetedRecent(3);
      setItems(list);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const toggleExpand = (id: number) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const handleBatchDelete = async () => {
    if (checked.size === 0) return;
    if (!confirm(`确认删除选中的 ${checked.size} 条记录？`)) return;
    setDeleting(true);
    try {
      await agentApi.batchDeleteGreeted(Array.from(checked));
      setItems(items.filter(i => !checked.has(i.id)));
      setChecked(new Set());
      setBatchMode(false);
    } catch (e: any) { alert(`删除失败：${e.message}`); }
    finally { setDeleting(false); }
  };

  const toggleCheck = (id: number) => {
    const next = new Set(checked);
    if (next.has(id)) next.delete(id); else next.add(id);
    setChecked(next);
  };

  const grouped: Record<string, GreetedItem[]> = {};
  for (const item of items) {
    const key = item.day;
    if (!grouped[key]) grouped[key] = [];
    grouped[key].push(item);
  }
  const sortedDays = Object.keys(grouped).sort((a, b) => b.localeCompare(a));

  return (
    <div className="p-5 h-full flex flex-col animate-fade-in">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <MessageSquare size={20} className="text-accent-blue" />
            招呼列表
          </h1>
          <p className="text-sm text-slate-500 mt-0.5">近 3 天已打招呼的岗位记录</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={load}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface-800/60 text-slate-400 hover:text-slate-200 hover:bg-surface-700/60 text-xs font-medium transition-colors"
          >
            刷新
          </button>
          <button
            onClick={() => { setBatchMode(m => !m); setChecked(new Set()); }}
            className={clsx(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
              batchMode ? 'bg-accent-blue/20 text-accent-blue' : 'bg-surface-800/60 text-slate-400 hover:text-slate-200 hover:bg-surface-700/60',
            )}
          >
            <Trash2 size={13} /> 批量删除
          </button>
        </div>
      </div>

      {batchMode && (
        <div className="flex items-center gap-2 mb-3 px-3 py-2 rounded-lg bg-accent-blue/10 border border-accent-blue/25 animate-fade-in">
          <button
            onClick={() => setChecked(checked.size === items.length ? new Set() : new Set(items.map(i => i.id)))}
            className="text-xs text-accent-blue hover:underline"
          >
            {checked.size === items.length ? '取消全选' : '全选'}
          </button>
          <span className="text-xs text-slate-500">已选 {checked.size} 项</span>
          <div className="flex-1" />
          <button onClick={handleBatchDelete} disabled={checked.size === 0 || deleting} className="text-xs px-2.5 py-1 rounded-md bg-red-500/20 text-red-400 hover:bg-red-500/30 disabled:opacity-40">
            {deleting ? <Loader2 size={11} className="inline animate-spin" /> : null} 删除所选
          </button>
          <button onClick={() => { setBatchMode(false); setChecked(new Set()); }} className="text-xs text-slate-500 hover:text-slate-300">
            退出
          </button>
        </div>
      )}

      <div className="flex-1 overflow-y-auto scrollbar-thin pr-1">
        {loading ? (
          <p className="text-xs text-slate-600 text-center py-8">加载中...</p>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <div className="w-16 h-16 rounded-2xl bg-surface-800/60 flex items-center justify-center mb-4">
              <MessageSquare size={28} className="text-slate-600" />
            </div>
            <p className="text-sm text-slate-400">暂无招呼记录</p>
            <p className="text-xs text-slate-600 mt-1">近 3 天打招呼的岗位将显示在此</p>
          </div>
        ) : (
          sortedDays.map(day => (
            <div key={day} className="mb-4">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-xs font-semibold text-slate-300 px-2 py-0.5 rounded bg-surface-800/60">
                  {getDayLabel(day)}
                </span>
                <span className="text-[10px] text-slate-600">{grouped[day].length} 条</span>
              </div>
              <div className="space-y-2">
                {grouped[day].map(item => {
                  const isExpanded = expanded.has(item.id);
                  const hasJd = !!(item.jd_text && item.jd_text.trim());
                  return (
                    <div
                      key={item.id}
                      className={clsx(
                        'rounded-xl border transition-all',
                        checked.has(item.id) ? 'bg-accent-blue/10 border-accent-blue/40' : 'bg-surface-800/40 border-slate-700/30 hover:bg-surface-700/40',
                      )}
                    >
                      <div className="flex items-center gap-2 px-3 py-2.5">
                        {batchMode && (
                          <input
                            type="checkbox"
                            checked={checked.has(item.id)}
                            onChange={() => toggleCheck(item.id)}
                            className="accent-[#5b8def] shrink-0"
                          />
                        )}
                        {hasJd && (
                          <button
                            onClick={() => toggleExpand(item.id)}
                            className="text-slate-500 hover:text-slate-300 shrink-0"
                          >
                            {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                          </button>
                        )}
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-slate-200 truncate">{item.title || '未知岗位'}</p>
                        </div>
                        <span className="text-[10px] text-slate-600 shrink-0">{formatTime(item.greeted_at)}</span>
                      </div>
                      {isExpanded && hasJd && (
                        <div className="px-3 pb-3 pt-0">
                          <div className="rounded-lg bg-surface-900/50 p-3 text-xs text-slate-400 leading-relaxed whitespace-pre-wrap max-h-[200px] overflow-y-auto scrollbar-thin">
                            {item.jd_text}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          ))
        )}
      </div>

      <p className="text-[11px] text-slate-600 mt-3 pt-2 border-t border-slate-700/30">共 {items.length} 条招呼记录</p>
    </div>
  );
}
