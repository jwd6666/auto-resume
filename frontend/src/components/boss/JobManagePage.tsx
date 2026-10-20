import { useEffect, useState, useCallback } from 'react';
import {
  Briefcase, Plus, Trash2, ChevronDown, ChevronRight, Check, Loader2, Upload,
  MessageSquare, Download, CheckCircle2, Pencil, X,
} from 'lucide-react';
import clsx from 'clsx';
import { agentApi, type Job, type GreetedItem } from '../../api/agentApi';
import { useJobs } from '../../store/useJobs';

const EMPTY_FORM = { title: '', content: '' };

function formatDate(iso: string) {
  if (!iso) return '';
  const d = new Date(iso);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

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

export function JobManagePage() {
  const jobs = useJobs((s) => s.jobs);
  const refreshJobs = useJobs((s) => s.refresh);
  const upsert = useJobs((s) => s.upsert);
  const upsertMany = useJobs((s) => s.upsertMany);
  const remove = useJobs((s) => s.remove);
  const removeMany = useJobs((s) => s.removeMany);
  const [jobTitles, setJobTitles] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editForm, setEditForm] = useState(EMPTY_FORM);
  const [editSaving, setEditSaving] = useState(false);
  const [batchMode, setBatchMode] = useState(false);
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [showAdd, setShowAdd] = useState(false);
  const [showBatchAdd, setShowBatchAdd] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [batchText, setBatchText] = useState('');
  const [saving, setSaving] = useState(false);

  const [showGreeted, setShowGreeted] = useState(false);
  const [greetedItems, setGreetedItems] = useState<GreetedItem[]>([]);
  const [greetedLoading, setGreetedLoading] = useState(false);
  const [greetedExpanded, setGreetedExpanded] = useState<Set<number>>(new Set());
  const [greetedChecked, setGreetedChecked] = useState<Set<number>>(new Set());
  const [greetedDeleting, setGreetedDeleting] = useState(false);
  const [importedIds, setImportedIds] = useState<Set<number>>(new Set());
  const [importingIds, setImportingIds] = useState<Set<number>>(new Set());

  const loadJobs = useCallback(async () => {
    try {
      await refreshJobs();
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [refreshJobs]);

  useEffect(() => { setJobTitles(new Set(jobs.map(j => j.title.trim()))); }, [jobs]);

  const loadGreeted = useCallback(async () => {
    setGreetedLoading(true);
    try {
      const list = await agentApi.listGreetedRecent(3);
      setGreetedItems(list);
    } catch (e) { console.error(e); }
    finally { setGreetedLoading(false); }
  }, []);

  useEffect(() => { loadJobs(); }, [loadJobs]);
  useEffect(() => { if (showGreeted) loadGreeted(); }, [showGreeted, loadGreeted]);

  const toggleExpand = (id: number) => {
    if (editingId === id) return;
    setExpanded(prev => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  };

  const startEdit = (job: Job) => {
    setEditingId(job.id);
    setEditForm({ title: job.title, content: job.content });
    setExpanded(prev => new Set(prev).add(job.id));
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditForm(EMPTY_FORM);
  };

  const saveEdit = async () => {
    if (!editingId || !editForm.title.trim() || !editForm.content.trim()) return;
    setEditSaving(true);
    try {
      const updated = await agentApi.updateJob(editingId, { title: editForm.title, content: editForm.content });
      upsert(updated);
      setJobTitles(prev => {
        const n = new Set(prev);
        const old = jobs.find(j => j.id === editingId);
        if (old) n.delete(old.title.trim());
        n.add(editForm.title.trim());
        return n;
      });
      setEditingId(null);
      setEditForm(EMPTY_FORM);
    } catch (e: any) { alert(`保存失败：${e.message}`); }
    finally { setEditSaving(false); }
  };

  const handleAdd = async () => {
    if (!form.title.trim() || !form.content.trim()) return;
    setSaving(true);
    try {
      const created = await agentApi.createJob({ title: form.title, content: form.content });
      upsert(created);
      setJobTitles(prev => new Set(prev).add(form.title.trim()));
      setForm(EMPTY_FORM);
      setShowAdd(false);
    } catch (e: any) { alert(`新增失败：${e.message}`); }
    finally { setSaving(false); }
  };

  const handleBatchAdd = async () => {
    const blocks = batchText.split(/\n\s*(?:-{3,}|={3,})\s*\n/).map(b => b.trim()).filter(Boolean);
    if (blocks.length === 0) { alert('未识别到岗位块。每个块第一行为岗位名称，其余为 JD，块间用 --- 分隔'); return; }
    setSaving(true);
    try {
      const items: { title: string; content: string }[] = [];
      for (const block of blocks) {
        const lines = block.split('\n');
        const title = lines[0].replace(/^#+\s*/, '').trim();
        const content = lines.slice(1).join('\n').trim();
        if (title && content) items.push({ title, content });
      }
      if (items.length === 0) { alert('解析失败：每个块需包含标题行与 JD 内容'); return; }
      const created = await agentApi.batchCreateJobs(items);
      upsertMany(created);
      setJobTitles(prev => { const n = new Set(prev); items.forEach(i => n.add(i.title.trim())); return n; });
      setShowBatchAdd(false);
      setBatchText('');
    } catch (e: any) { alert(`批量新增失败：${e.message}`); }
    finally { setSaving(false); }
  };

  const handleDelete = async (job: Job) => {
    if (!confirm(`确认删除岗位「${job.title}」？`)) return;
    try {
      await agentApi.deleteJob(job.id);
      remove(job.id);
      setJobTitles(prev => { const n = new Set(prev); n.delete(job.title.trim()); return n; });
      setExpanded(prev => { const n = new Set(prev); n.delete(job.id); return n; });
      if (editingId === job.id) cancelEdit();
    } catch (e: any) { alert(`删除失败：${e.message}`); }
  };

  const handleBatchDelete = async () => {
    if (checked.size === 0) return;
    if (!confirm(`确认删除选中的 ${checked.size} 个岗位？`)) return;
    try {
      for (const id of checked) await agentApi.deleteJob(id);
      const removed = jobs.filter(j => checked.has(j.id));
      removeMany([...checked]);
      setJobTitles(prev => { const n = new Set(prev); removed.forEach(j => n.delete(j.title.trim())); return n; });
      setChecked(new Set());
      setBatchMode(false);
    } catch (e: any) { alert(`批量删除失败：${e.message}`); }
  };

  const toggleCheck = (id: number) => {
    const next = new Set(checked);
    if (next.has(id)) next.delete(id); else next.add(id);
    setChecked(next);
  };

  const handleAnalyze = (job: Job) => {
    window.dispatchEvent(new CustomEvent('job-analysis-load', { detail: { title: job.title, content: job.content } }));
  };

  const handleImportGreeted = async (item: GreetedItem) => {
    const jdText = item.jd_text?.trim();
    if (!jdText) { alert('该记录无 JD 内容，无法导入'); return; }
    setImportingIds(prev => new Set(prev).add(item.id));
    try {
      const created = await agentApi.createJob({ title: item.title || '未知岗位', content: jdText });
      upsert(created);
      setJobTitles(prev => new Set(prev).add((item.title || '未知岗位').trim()));
      setImportedIds(prev => new Set(prev).add(item.id));
      setGreetedChecked(prev => { const n = new Set(prev); n.delete(item.id); return n; });
    } catch (e: any) { alert(`导入失败：${e.message}`); }
    finally { setImportingIds(prev => { const n = new Set(prev); n.delete(item.id); return n; }); }
  };

  const handleBatchImportGreeted = async () => {
    const selected = greetedItems.filter(i => greetedChecked.has(i.id) && i.jd_text?.trim() && !importedIds.has(i.id));
    if (selected.length === 0) { alert('请选择含 JD 内容且未导入的记录'); return; }
    setImportingIds(prev => { const n = new Set(prev); selected.forEach(i => n.add(i.id)); return n; });
    try {
      const items = selected.map(i => ({ title: i.title || '未知岗位', content: i.jd_text!.trim() }));
      const created = await agentApi.batchCreateJobs(items);
      upsertMany(created);
      setJobTitles(prev => { const n = new Set(prev); items.forEach(i => n.add(i.title.trim())); return n; });
      selected.forEach(i => setImportedIds(prev => new Set(prev).add(i.id)));
      setGreetedChecked(new Set());
    } catch (e: any) { alert(`批量导入失败：${e.message}`); }
    finally { setImportingIds(new Set()); }
  };

  const handleGreetedBatchDelete = async () => {
    if (greetedChecked.size === 0) return;
    if (!confirm(`确认删除选中的 ${greetedChecked.size} 条记录？`)) return;
    setGreetedDeleting(true);
    try {
      await agentApi.batchDeleteGreeted(Array.from(greetedChecked));
      setGreetedItems(greetedItems.filter(i => !greetedChecked.has(i.id)));
      setGreetedChecked(new Set());
    } catch (e: any) { alert(`删除失败：${e.message}`); }
    finally { setGreetedDeleting(false); }
  };

  const toggleGreetedCheck = (id: number) => {
    setGreetedChecked(prev => { const n = new Set(prev); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  };

  const greetedGrouped: Record<string, GreetedItem[]> = {};
  for (const item of greetedItems) {
    const key = item.day;
    if (!greetedGrouped[key]) greetedGrouped[key] = [];
    greetedGrouped[key].push(item);
  }
  const sortedDays = Object.keys(greetedGrouped).sort((a, b) => b.localeCompare(a));

  return (
    <div className="p-5 h-full flex flex-col animate-fade-in">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold text-slate-100">岗位管理</h1>
          <p className="text-sm text-slate-500 mt-0.5">管理岗位列表，点击岗位可加载到职位分析</p>
        </div>
        <div className="flex items-center gap-2">
          {jobs.length > 0 && (
            <button
              onClick={() => { setBatchMode(m => !m); setChecked(new Set()); if (editingId) cancelEdit(); }}
              className={clsx(
                'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
                batchMode ? 'bg-accent-blue/20 text-accent-blue' : 'bg-surface-800/60 text-slate-400 hover:text-slate-200 hover:bg-surface-700/60',
              )}
            >
              <Trash2 size={13} /> {batchMode ? '退出批量' : '批量删除'}
            </button>
          )}
          <button
            onClick={() => { setShowAdd(true); setShowBatchAdd(false); }}
            className="btn-primary"
          >
            <Plus size={14} /> 新增岗位
          </button>
          <button
            onClick={() => { setShowBatchAdd(true); setShowAdd(false); }}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface-800/60 text-slate-400 hover:text-slate-200 hover:bg-surface-700/60 text-xs font-medium transition-colors"
          >
            <Upload size={13} /> 批量新增
          </button>
        </div>
      </div>

      {batchMode && (
        <div className="flex items-center gap-2 mb-3 px-3 py-2 rounded-lg bg-accent-blue/10 border border-accent-blue/25 animate-fade-in">
          <button
            onClick={() => setChecked(checked.size === jobs.length ? new Set() : new Set(jobs.map(j => j.id)))}
            className="text-xs text-accent-blue hover:underline"
          >
            {checked.size === jobs.length ? '取消全选' : '全选'}
          </button>
          <span className="text-xs text-slate-500">已选 {checked.size} 项</span>
          <div className="flex-1" />
          <button onClick={handleBatchDelete} disabled={checked.size === 0} className="text-xs px-2.5 py-1 rounded-md bg-red-500/20 text-red-400 hover:bg-red-500/30 disabled:opacity-40">
            删除所选
          </button>
          <button onClick={() => { setBatchMode(false); setChecked(new Set()); }} className="text-xs text-slate-500 hover:text-slate-300">
            退出
          </button>
        </div>
      )}

      {showAdd && (
        <div className="bg-surface-900/60 border border-slate-700/40 rounded-xl mb-3 p-4 space-y-3 animate-fade-in">
          <input
            value={form.title}
            onChange={e => setForm({ ...form, title: e.target.value })}
            placeholder="岗位名称 *"
            className="w-full bg-surface-900/60 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:border-accent-blue/50 focus:outline-none"
          />
          <textarea
            value={form.content}
            onChange={e => setForm({ ...form, content: e.target.value })}
            placeholder="岗位描述 JD *"
            rows={5}
            className="w-full bg-surface-900/60 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:border-accent-blue/50 focus:outline-none resize-none"
          />
          <div className="flex gap-2 justify-end">
            <button onClick={() => { setShowAdd(false); setForm(EMPTY_FORM); }} className="px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200 rounded-md hover:bg-slate-700/40">
              取消
            </button>
            <button onClick={handleAdd} disabled={saving || !form.title.trim() || !form.content.trim()} className="px-3 py-1.5 text-xs bg-accent-purple text-white rounded-md hover:bg-accent-purple/80 disabled:opacity-50">
              {saving ? <Loader2 size={13} className="inline animate-spin" /> : <Check size={13} className="inline" />} 保存
            </button>
          </div>
        </div>
      )}

      {showBatchAdd && (
        <div className="bg-surface-900/60 border border-slate-700/40 rounded-xl mb-3 p-4 space-y-3 animate-fade-in">
          <p className="text-xs text-slate-500">每个岗位块：第一行为岗位名称，其余为 JD；块之间用 <code className="text-accent-blue">---</code> 分隔</p>
          <textarea
            value={batchText}
            onChange={e => setBatchText(e.target.value)}
            rows={8}
            placeholder={'前端开发工程师\n负责公司前端架构...\nVue3 + TypeScript\n---\nAI 算法工程师\n负责模型训练...\nPyTorch + NLP'}
            className="w-full bg-surface-900/60 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:border-accent-blue/50 focus:outline-none resize-none font-mono"
          />
          <div className="flex gap-2 justify-end">
            <button onClick={() => { setShowBatchAdd(false); setBatchText(''); }} className="px-3 py-1.5 text-xs text-slate-400 hover:text-slate-200 rounded-md hover:bg-slate-700/40">
              取消
            </button>
            <button onClick={handleBatchAdd} disabled={saving || !batchText.trim()} className="px-3 py-1.5 text-xs bg-accent-purple text-white rounded-md hover:bg-accent-purple/80 disabled:opacity-50">
              {saving ? <Loader2 size={13} className="inline animate-spin" /> : <Check size={13} className="inline" />} 导入
            </button>
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto scrollbar-thin space-y-2 pr-1">
        {loading ? (
          <p className="text-xs text-slate-600 text-center py-8">加载中...</p>
        ) : jobs.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <div className="w-16 h-16 rounded-2xl bg-surface-800/60 flex items-center justify-center mb-4">
              <Briefcase size={28} className="text-slate-600" />
            </div>
            <p className="text-sm text-slate-400">暂无岗位</p>
            <p className="text-xs text-slate-600 mt-1">点击「新增岗位」或从下方「招呼记录」导入</p>
          </div>
        ) : (
          jobs.map(job => {
            const isExpanded = expanded.has(job.id);
            const isEditing = editingId === job.id;
            return (
              <div
                key={job.id}
                className={clsx(
                  'rounded-xl border transition-all',
                  isEditing ? 'bg-accent-purple/5 border-accent-purple/30' :
                  checked.has(job.id) ? 'bg-accent-blue/10 border-accent-blue/40' :
                  'bg-surface-800/40 border-slate-700/30 hover:bg-surface-700/40',
                )}
              >
                <div className="flex items-center gap-2 px-3 py-2.5">
                  {batchMode && (
                    <input
                      type="checkbox"
                      checked={checked.has(job.id)}
                      onChange={() => toggleCheck(job.id)}
                      className="accent-[#5b8def] shrink-0"
                    />
                  )}
                  <button
                    onClick={() => toggleExpand(job.id)}
                    className="text-slate-500 hover:text-slate-300 shrink-0"
                  >
                    {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                  </button>
                  {isEditing ? (
                    <input
                      value={editForm.title}
                      onChange={e => setEditForm({ ...editForm, title: e.target.value })}
                      className="flex-1 min-w-0 bg-surface-900/60 border border-accent-purple/30 rounded-md px-2 py-0.5 text-sm text-slate-200 focus:outline-none"
                    />
                  ) : (
                    <p
                      className="flex-1 min-w-0 text-sm font-medium text-slate-200 truncate cursor-pointer hover:text-accent-blue transition-colors"
                      onClick={() => { if (!batchMode && !isEditing) handleAnalyze(job); }}
                      title="点击加载到职位分析"
                    >
                      {job.title}
                    </p>
                  )}
                  <span className="text-[10px] text-slate-600 shrink-0">{formatDate(job.updated_at || job.created_at)}</span>
                  {isEditing ? (
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        onClick={saveEdit}
                        disabled={editSaving || !editForm.title.trim() || !editForm.content.trim()}
                        className="px-2 py-0.5 rounded-md bg-accent-purple/20 text-accent-purple hover:bg-accent-purple/30 text-[11px] font-medium transition-colors disabled:opacity-40"
                      >
                        {editSaving ? <Loader2 size={11} className="inline animate-spin" /> : <Check size={11} className="inline" />} 保存
                      </button>
                      <button
                        onClick={cancelEdit}
                        className="px-2 py-0.5 rounded-md bg-surface-700/40 text-slate-400 hover:text-slate-200 text-[11px] transition-colors"
                      >
                        <X size={11} className="inline" /> 取消
                      </button>
                    </div>
                  ) : !batchMode && (
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        onClick={() => startEdit(job)}
                        className="text-slate-600 hover:text-accent-purple transition-colors"
                        title="编辑"
                      >
                        <Pencil size={13} />
                      </button>
                      <button
                        onClick={() => handleDelete(job)}
                        className="text-slate-600 hover:text-red-400 transition-colors"
                        title="删除"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  )}
                </div>
                {isExpanded && (
                  <div className="px-3 pb-3 pt-0">
                    {isEditing ? (
                      <textarea
                        value={editForm.content}
                        onChange={e => setEditForm({ ...editForm, content: e.target.value })}
                        rows={8}
                        className="w-full bg-surface-900/60 border border-accent-purple/30 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none resize-none"
                      />
                    ) : (
                      <div className="rounded-lg bg-surface-900/50 p-3 text-xs text-slate-400 leading-relaxed whitespace-pre-wrap max-h-[200px] overflow-y-auto scrollbar-thin">
                        {job.content}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>

      <div className="mt-3 pt-2 border-t border-slate-700/30">
        <button
          onClick={() => setShowGreeted(v => !v)}
          className="flex items-center gap-2 w-full text-left"
        >
          {showGreeted ? <ChevronDown size={14} className="text-slate-500" /> : <ChevronRight size={14} className="text-slate-500" />}
          <MessageSquare size={14} className="text-accent-blue" />
          <span className="text-sm font-medium text-slate-300">招呼记录</span>
          <span className="text-[11px] text-slate-600">近 3 天打招呼的岗位，可导入到上方岗位列表</span>
        </button>
      </div>

      {showGreeted && (
        <div className="mt-2 flex flex-col min-h-[200px] max-h-[400px] animate-fade-in">
          <div className="flex items-center gap-2 mb-2">
            <button
              onClick={loadGreeted}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-surface-800/60 text-slate-400 hover:text-slate-200 hover:bg-surface-700/60 text-[11px] font-medium transition-colors"
            >
              刷新
            </button>
            <div className="flex-1" />
            <button
              onClick={() => {
                setGreetedChecked(greetedChecked.size === greetedItems.length ? new Set() : new Set(greetedItems.map(i => i.id)));
              }}
              className="text-[11px] text-accent-blue hover:underline"
            >
              {greetedChecked.size === greetedItems.length && greetedItems.length > 0 ? '取消全选' : '全选'}
            </button>
            <button
              onClick={handleBatchImportGreeted}
              disabled={greetedChecked.size === 0 || importingIds.size > 0}
              className={clsx(
                'flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-medium transition-colors',
                greetedChecked.size > 0 ? 'bg-accent-purple/20 text-accent-purple hover:bg-accent-purple/30' : 'bg-surface-800/40 text-slate-600 cursor-not-allowed',
              )}
            >
              <Download size={11} /> 批量导入 ({greetedChecked.size})
            </button>
            <button
              onClick={handleGreetedBatchDelete}
              disabled={greetedChecked.size === 0 || greetedDeleting}
              className={clsx(
                'flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-medium transition-colors',
                greetedChecked.size > 0 ? 'bg-red-500/20 text-red-400 hover:bg-red-500/30' : 'bg-surface-800/40 text-slate-600 cursor-not-allowed',
              )}
            >
              {greetedDeleting ? <Loader2 size={10} className="animate-spin" /> : <Trash2 size={11} />} 批量删除 ({greetedChecked.size})
            </button>
          </div>

          <div className="flex-1 overflow-y-auto scrollbar-thin pr-1">
            {greetedLoading ? (
              <p className="text-xs text-slate-600 text-center py-6">加载中...</p>
            ) : greetedItems.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 text-center">
                <MessageSquare size={20} className="text-slate-700 mb-2" />
                <p className="text-xs text-slate-500">暂无招呼记录</p>
              </div>
            ) : (
              sortedDays.map(day => (
                <div key={day} className="mb-3">
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="text-[11px] font-semibold text-slate-400 px-1.5 py-0.5 rounded bg-surface-800/60">
                      {getDayLabel(day)}
                    </span>
                    <span className="text-[10px] text-slate-600">{greetedGrouped[day].length} 条</span>
                  </div>
                  <div className="space-y-1.5">
                    {greetedGrouped[day].map(item => {
                      const isExpanded = greetedExpanded.has(item.id);
                      const hasJd = !!(item.jd_text && item.jd_text.trim());
                      const isImporting = importingIds.has(item.id);
                      const isImported = importedIds.has(item.id);
                      const alreadyInJobs = !isImported && jobTitles.has((item.title || '').trim());
                      const isChecked = greetedChecked.has(item.id);
                      return (
                        <div
                          key={item.id}
                          className={clsx(
                            'rounded-lg border transition-all',
                            isImported ? 'bg-accent-purple/5 border-accent-purple/20' :
                            isChecked ? 'bg-accent-blue/10 border-accent-blue/40' :
                            alreadyInJobs ? 'bg-surface-800/30 border-slate-700/20' :
                            'bg-surface-800/40 border-slate-700/30 hover:bg-surface-700/40',
                          )}
                        >
                          <div className="flex items-center gap-2 px-2.5 py-1.5">
                            <input
                              type="checkbox"
                              checked={isChecked}
                              onChange={() => toggleGreetedCheck(item.id)}
                              className="accent-[#5b8def] shrink-0"
                            />
                            {hasJd && (
                              <button
                                onClick={() => setGreetedExpanded(prev => { const n = new Set(prev); if (n.has(item.id)) n.delete(item.id); else n.add(item.id); return n; })}
                                className="text-slate-500 hover:text-slate-300 shrink-0"
                              >
                                {isExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                              </button>
                            )}
                            <p className={clsx(
                              'flex-1 min-w-0 text-xs font-medium truncate',
                              isImported ? 'text-slate-500' : 'text-slate-200',
                            )}>
                              {item.title || '未知岗位'}
                            </p>
                            <span className="text-[10px] text-slate-600 shrink-0">{formatTime(item.greeted_at)}</span>
                            {isImported ? (
                              <span className="flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-accent-purple/15 text-accent-purple text-[10px] font-medium shrink-0">
                                <CheckCircle2 size={10} /> 已导入
                              </span>
                            ) : alreadyInJobs ? (
                              <span className="px-1.5 py-0.5 rounded bg-surface-700/40 text-slate-500 text-[10px] font-medium shrink-0">已存在</span>
                            ) : hasJd ? (
                              <button
                                onClick={() => handleImportGreeted(item)}
                                disabled={isImporting}
                                className="flex items-center gap-0.5 px-2 py-0.5 rounded-md bg-accent-purple/15 text-accent-purple hover:bg-accent-purple/25 text-[10px] font-medium transition-colors disabled:opacity-50 shrink-0"
                              >
                                {isImporting ? <Loader2 size={10} className="animate-spin" /> : <Download size={10} />} 导入
                              </button>
                            ) : (
                              <span className="px-1.5 py-0.5 rounded bg-surface-700/40 text-slate-600 text-[10px] shrink-0">无 JD</span>
                            )}
                          </div>
                          {isExpanded && hasJd && (
                            <div className="px-2.5 pb-2 pt-0">
                              <div className="rounded-md bg-surface-900/50 p-2 text-[11px] text-slate-400 leading-relaxed whitespace-pre-wrap max-h-[120px] overflow-y-auto scrollbar-thin">
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

          <p className="text-[10px] text-slate-600 mt-1">近 3 天共 {greetedItems.length} 条招呼记录</p>
        </div>
      )}

      <p className="text-[11px] text-slate-600 mt-2">共 {jobs.length} 个岗位</p>
    </div>
  );
}
