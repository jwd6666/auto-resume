/** 岗位管理面板 — 弹窗模式：新建/批量导入/批量管理/开关/更多菜单 */
import { useEffect, useState } from 'react';
import { Briefcase, Plus, Upload, ListChecks, X, Check, Loader2 } from 'lucide-react';
import { agentApi, type Job } from '../../api/agentApi';
import { DotMenu, Modal, formatDateTime, extractSkillTags } from './ui';

interface Props {
  open: boolean;
  onClose: () => void;
  selectedJob: Job | null;
  onSelect: (job: Job | null) => void;
}

const EMPTY_FORM = { title: '', content: '' };

export function JobPanel({ open, onClose, selectedJob, onSelect }: Props) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<Job | null>(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [showImport, setShowImport] = useState(false);
  const [importText, setImportText] = useState('');
  const [importing, setImporting] = useState(false);
  const [batchMode, setBatchMode] = useState(false);
  const [checked, setChecked] = useState<Set<number>>(new Set());

  const load = async () => {
    try {
      const list = await agentApi.listJobs();
      setJobs(list);
      if (list.length > 0 && !selectedJob) onSelect(list[0]);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const handleSubmit = async () => {
    if (!form.title.trim() || !form.content.trim()) return;
    try {
      const payload = {
        title: form.title,
        content: form.content,
      };
      if (editing) {
        const updated = await agentApi.updateJob(editing.id, payload);
        setJobs(jobs.map(j => j.id === updated.id ? updated : j));
        onSelect(updated);
      } else {
        const created = await agentApi.createJob(payload);
        setJobs([created, ...jobs]);
        onSelect(created);
      }
      setShowForm(false); setEditing(null); setForm(EMPTY_FORM);
    } catch (e: any) { alert(`保存失败：${e.message}`); }
  };

  const handleImport = async () => {
    const blocks = importText.split(/\n\s*(?:-{3,}|={3,})\s*\n/).map(b => b.trim()).filter(Boolean);
    if (blocks.length === 0) { alert('未识别到岗位块。每个块第一行为岗位名称，其余为 JD，块间用 --- 分隔'); return; }
    setImporting(true);
    try {
      const created: Job[] = [];
      for (const block of blocks) {
        const lines = block.split('\n');
        const title = lines[0].replace(/^#+\s*/, '').trim();
        const content = lines.slice(1).join('\n').trim();
        if (!title || !content) continue;
        created.push(await agentApi.createJob({ title, content }));
      }
      if (created.length === 0) { alert('解析失败：每个块需包含标题行与 JD 内容'); return; }
      setJobs([...created.reverse(), ...jobs]);
      onSelect(created[0]);
      setShowImport(false); setImportText('');
    } catch (e: any) { alert(`批量导入失败：${e.message}`); }
    finally { setImporting(false); }
  };

  const handleDelete = async (job: Job) => {
    if (!confirm(`确认删除岗位「${job.title}」？其下简历将一并删除`)) return;
    try {
      await agentApi.deleteJob(job.id);
      setJobs(jobs.filter(j => j.id !== job.id));
      if (selectedJob?.id === job.id) onSelect(jobs.find(j => j.id !== job.id) ?? null);
    } catch (e: any) { alert(`删除失败：${e.message}`); }
  };

  const handleBatchDelete = async () => {
    if (checked.size === 0) return;
    if (!confirm(`确认删除选中的 ${checked.size} 个岗位？`)) return;
    try {
      for (const id of checked) await agentApi.deleteJob(id);
      setJobs(jobs.filter(j => !checked.has(j.id)));
      if (selectedJob && checked.has(selectedJob.id)) onSelect(jobs.find(j => !checked.has(j.id)) ?? null);
      setChecked(new Set()); setBatchMode(false);
    } catch (e: any) { alert(`批量删除失败：${e.message}`); }
  };

  const toggleCheck = (id: number) => {
    const next = new Set(checked);
    if (next.has(id)) next.delete(id); else next.add(id);
    setChecked(next);
  };

  return (
    <Modal open={open} onClose={onClose} title="岗位管理" icon={<Briefcase size={15} className="text-accent-purple" />} badge={`岗位库 (${jobs.length})`}>
      <div className="flex flex-col min-h-0">
        <div className="flex items-center gap-1.5 mb-3">
          <button
            onClick={() => { setEditing(null); setForm(EMPTY_FORM); setShowForm(true); }}
            className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md bg-accent-purple/20 text-accent-purple hover:bg-accent-purple/30 transition-colors"
          >
            <Plus size={13} /> 新增岗位
          </button>
          <button
            onClick={() => setShowImport(true)}
            className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md bg-surface-700/50 text-slate-400 hover:text-slate-200 hover:bg-surface-700 transition-colors"
          >
            <Upload size={13} /> 批量导入
          </button>
          <button
            onClick={() => { setBatchMode(m => !m); setChecked(new Set()); }}
            className={`flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md transition-colors ${batchMode ? 'bg-accent-blue/20 text-accent-blue' : 'bg-surface-700/50 text-slate-400 hover:text-slate-200 hover:bg-surface-700'}`}
          >
            <ListChecks size={13} /> 批量管理
          </button>
        </div>

        {batchMode && (
          <div className="flex items-center gap-2 mb-2 px-2.5 py-1.5 rounded-md bg-accent-blue/10 border border-accent-blue/25 animate-fade-in">
            <button
              onClick={() => setChecked(checked.size === jobs.length ? new Set() : new Set(jobs.map(j => j.id)))}
              className="text-xs text-accent-blue hover:underline"
            >
              {checked.size === jobs.length ? '取消全选' : '全选'}
            </button>
            <span className="text-xs text-slate-500">已选 {checked.size} 项</span>
            <div className="flex-1" />
            <button onClick={handleBatchDelete} disabled={checked.size === 0} className="text-xs px-2 py-1 rounded bg-red-500/20 text-red-400 hover:bg-red-500/30 disabled:opacity-40">
              删除所选
            </button>
            <button onClick={() => { setBatchMode(false); setChecked(new Set()); }} className="text-xs text-slate-500 hover:text-slate-300">
              退出
            </button>
          </div>
        )}

        {showForm && (
          <div className="bg-surface-900/60 border border-slate-700/40 rounded-lg mb-3 p-3 space-y-2 animate-fade-in">
            <input value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} placeholder="岗位名称 *"
              className="w-full min-w-0 bg-surface-900/60 border border-slate-700/50 rounded-md px-2.5 py-1.5 text-sm text-slate-200 placeholder-slate-600 focus:border-accent-blue/50 focus:outline-none" />
            <textarea value={form.content} onChange={e => setForm({ ...form, content: e.target.value })} placeholder="粘贴岗位 JD 内容... *" rows={4}
              className="w-full bg-surface-900/60 border border-slate-700/50 rounded-md px-2.5 py-1.5 text-sm text-slate-200 placeholder-slate-600 focus:border-accent-blue/50 focus:outline-none resize-none" />
            <div className="flex gap-2 justify-end">
              <button onClick={() => { setShowForm(false); setEditing(null); }} className="px-2.5 py-1 text-xs text-slate-400 hover:text-slate-200 rounded-md hover:bg-slate-700/40">
                <X size={13} className="inline" /> 取消
              </button>
              <button onClick={handleSubmit} className="px-2.5 py-1 text-xs bg-accent-blue text-white rounded-md hover:bg-accent-blue/80">
                <Check size={13} className="inline" /> 保存
              </button>
            </div>
          </div>
        )}

        {showImport && (
          <div className="bg-surface-900/60 border border-slate-700/40 rounded-lg mb-3 p-3 space-y-2 animate-fade-in">
            <p className="text-xs text-slate-500">每个岗位块：第一行为岗位名称，其余为 JD；块之间用 <code className="text-accent-blue">---</code> 分隔</p>
            <textarea value={importText} onChange={e => setImportText(e.target.value)} rows={6}
              placeholder={'前端开发工程师\n负责公司前端架构...\n---\nAI 算法工程师\n负责模型训练...'}
              className="w-full bg-surface-900/60 border border-slate-700/50 rounded-md px-2.5 py-1.5 text-sm text-slate-200 placeholder-slate-600 focus:border-accent-blue/50 focus:outline-none resize-none font-mono" />
            <div className="flex gap-2 justify-end">
              <button onClick={() => setShowImport(false)} className="px-2.5 py-1 text-xs text-slate-400 hover:text-slate-200 rounded-md hover:bg-slate-700/40">取消</button>
              <button onClick={handleImport} disabled={importing} className="px-2.5 py-1 text-xs bg-accent-purple text-white rounded-md hover:bg-accent-purple/80 disabled:opacity-50">
                {importing ? <Loader2 size={13} className="inline animate-spin" /> : <Check size={13} className="inline" />} 导入
              </button>
            </div>
          </div>
        )}

        <div className="flex-1 overflow-y-auto scrollbar-thin space-y-2 pr-1">
          {loading ? (
            <p className="text-xs text-slate-600 text-center py-4">加载中...</p>
          ) : jobs.length === 0 ? (
            <p className="text-xs text-slate-600 text-center py-4">暂无岗位，请新增或批量导入</p>
          ) : (
            jobs.map(job => {
              const skills = extractSkillTags(job.content);
              return (
                <div
                  key={job.id}
                  onClick={() => { if (!batchMode) { onSelect(job); onClose(); } }}
                  className={`p-3 rounded-lg border transition-all ${batchMode ? 'cursor-default' : 'cursor-pointer'} ${
                    selectedJob?.id === job.id
                      ? 'bg-accent-blue/10 border-accent-blue/40'
                      : 'bg-surface-800/40 border-slate-700/30 hover:bg-surface-700/40'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    {batchMode && (
                      <input type="checkbox" checked={checked.has(job.id)} onChange={() => toggleCheck(job.id)}
                        onClick={e => e.stopPropagation()} className="accent-[#5b8def] shrink-0" />
                    )}
                    <p className={`flex-1 min-w-0 text-sm font-medium truncate ${selectedJob?.id === job.id ? 'text-accent-blue' : 'text-slate-200'}`}>
                      {job.title}
                    </p>
                    <DotMenu items={[
                      { label: '编辑', onClick: () => { setEditing(job);         setForm({ title: job.title, content: job.content }); setShowForm(true); } },
                      { label: '删除', danger: true, onClick: () => handleDelete(job) },
                    ]} />
                  </div>
                  <div className="flex flex-wrap items-center gap-1 mt-1.5">
                    {skills.map(s => (
                      <span key={s} className="text-[10px] px-1.5 py-0.5 rounded bg-surface-700/70 text-slate-400">{s}</span>
                    ))}
                  </div>
                  <p className="text-[11px] text-slate-600 mt-1.5">更新时间：{formatDateTime(job.updated_at || job.created_at)}</p>
                </div>
              );
            })
          )}
        </div>

        <p className="text-[11px] text-slate-600 mt-2 pt-2 border-t border-slate-700/30">共 {jobs.length} 个岗位</p>
      </div>
    </Modal>
  );
}
