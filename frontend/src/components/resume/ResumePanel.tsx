/** 简历管理面板 — 弹窗模式：上传简历/批量导入/批量管理/AI生成简历 */
import { useEffect, useState, useRef } from 'react';
import { FileText, Upload, ListChecks, X, Loader2, AlertTriangle, Files, Sparkles, RotateCw } from 'lucide-react';
import { agentApi, type Resume, type Job } from '../../api/agentApi';
import { DotMenu, Modal, formatBytes, formatDateTime } from './ui';
import { GenerateResumeModal } from './GenerateResumeModal';

interface Props {
  open: boolean;
  onClose: () => void;
  job: Job | null;
  selectedResume: Resume | null;
  onSelect: (r: Resume | null) => void;
  onGenerate?: () => void;
  refreshTick?: number;
  autoClose?: boolean;
  /** 后台上传回调：交给页面层管理，关闭弹窗不影响上传进度 */
  onBgUpload?: (file: File) => void;
}

const UPLOAD_ACCEPT = '.pdf,.docx,.doc,.txt,.md,.png,.jpg,.jpeg,.bmp,.webp';

function wordCount(r: Resume): string {
  const html = r.rendered_html;
  if (html) {
    const text = html.replace(/<[^>]*>/g, '').replace(/\s+/g, '');
    return `${text.length} 字`;
  }
  return r.content ? `${r.content.length} 字` : '空';
}

export function ResumePanel({ open, onClose, job, selectedResume, onSelect, onGenerate, refreshTick, autoClose = true, onBgUpload }: Props) {
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [streamProgress, setStreamProgress] = useState('');
  const [streamError, setStreamError] = useState('');
  const [batchMode, setBatchMode] = useState(false);
  const [checked, setChecked] = useState<Set<number>>(new Set());
  const [generateModalOpen, setGenerateModalOpen] = useState(false);
  const [bgUploading, setBgUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const multiRef = useRef<HTMLInputElement>(null);
  const retryFileRef = useRef<File | null>(null);

  // 错误提示自动消失
  useEffect(() => {
    if (!streamError) return;
    const timer = setTimeout(() => setStreamError(''), 10000);
    return () => clearTimeout(timer);
  }, [streamError]);

  const load = async () => {
    if (!job) { setResumes([]); return; }
    setLoading(true);
    try {
      const list = await agentApi.listResumes(job.id);
      setResumes(list);
      if (list.length > 0 && !selectedResume) onSelect(list[0]);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [job?.id, refreshTick]);

  const handleUpload = async (file: File) => {
    const name = file.name.toLowerCase();
    if (!/\.(pdf|docx?|txt|md|png|jpe?g|bmp|webp)$/.test(name)) {
      alert('支持 PDF / Word / 图片 / TXT / Markdown 文件');
      return;
    }
    if (!job) return;
    if (onBgUpload) {
      // 后台模式：上传交给页面层，可关闭弹窗，AI 识别不受影响
      onBgUpload(file);
      return;
    }
    setUploading(true);
    setStreamError('');
    setStreamProgress('正在上传并AI生成简历…');

    try {
      const r = await agentApi.uploadAndGenerate(job.id, file);
      setResumes(prev => [r, ...prev]);
      onSelect(r);
      retryFileRef.current = null;
    } catch (e: any) {
      setStreamError(e.message || '上传生成简历失败');
      retryFileRef.current = file;
    } finally {
      setUploading(false);
      setBgUploading(false);
      setStreamProgress('');
    }
  };

  const handleBgRetry = async () => {
    if (!retryFileRef.current || !job) return;
    if (onBgUpload) {
      onBgUpload(retryFileRef.current);
      retryFileRef.current = null;
      setStreamError('');
      return;
    }
    setStreamError('');
    setBgUploading(true);
    setStreamProgress('后台重试上传中…');
    await handleUpload(retryFileRef.current);
  };

  const handleMultiUpload = async (files: FileList) => {
    const list = Array.from(files);
    if (list.length === 0 || !job) return;
    if (onBgUpload) {
      // 后台模式：逐个后台处理
      for (const f of list) {
        if (!/\.(pdf|docx?|txt|md|png|jpe?g|bmp|webp)$/i.test(f.name)) continue;
        onBgUpload(f);
      }
      return;
    }
    setUploading(true);
    setStreamError('');
    let ok = 0;
    for (let i = 0; i < list.length; i++) {
      const f = list[i];
      if (!/\.(pdf|docx?|txt|md|png|jpe?g|bmp|webp)$/i.test(f.name)) continue;
      setStreamProgress(`批量导入 ${i + 1}/${list.length}：${f.name}`);
      try {
        const r = await agentApi.uploadAndGenerate(job.id, f);
        setResumes(prev => [r, ...prev]);
        ok++;
      } catch (e: any) {
        setStreamError(`${f.name}：${e.message}`);
      }
    }
    setUploading(false);
    setStreamProgress('');
    if (ok > 0) alert(`成功导入 ${ok} 份简历`);
  };

  const handleDelete = async (r: Resume) => {
    if (!confirm(`确认删除简历「${r.title || r.id}」？磁盘文件将同步清理。`)) return;
    try {
      await agentApi.deleteResume(r.id);
      setResumes(resumes.filter(x => x.id !== r.id));
      if (selectedResume?.id === r.id) onSelect(resumes.find(x => x.id !== r.id) || null);
    } catch (e: any) { alert(`删除失败：${e.message}`); }
  };

  const handleBatchDelete = async () => {
    if (checked.size === 0) return;
    if (!confirm(`确认删除选中的 ${checked.size} 份简历？磁盘文件将同步清理。`)) return;
    try {
      for (const id of checked) await agentApi.deleteResume(id);
      setResumes(resumes.filter(r => !checked.has(r.id)));
      if (selectedResume && checked.has(selectedResume.id)) onSelect(resumes.find(r => !checked.has(r.id)) || null);
      setChecked(new Set());
      setBatchMode(false);
    } catch (e: any) { alert(`批量删除失败：${e.message}`); }
  };

  const toggleCheck = (id: number) => {
    const next = new Set(checked);
    if (next.has(id)) next.delete(id); else next.add(id);
    setChecked(next);
  };

  return (
    <Modal open={open} onClose={onClose} title="简历管理" icon={<FileText size={15} className="text-accent-blue" />} badge={`本地简历库 (${resumes.length})`}>
      <div className="flex flex-col min-h-0">
        <div className="flex items-center gap-1.5 mb-3 flex-wrap">
          <input ref={fileRef} type="file" accept={UPLOAD_ACCEPT} className="hidden"
            onChange={e => { const f = e.target.files?.[0]; if (f) handleUpload(f); e.target.value = ''; }} />
          <input ref={multiRef} type="file" accept={UPLOAD_ACCEPT} multiple className="hidden"
            onChange={e => { if (e.target.files) handleMultiUpload(e.target.files); e.target.value = ''; }} />
          <button
            onClick={() => fileRef.current?.click()}
            disabled={uploading || !job}
            className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md bg-accent-purple/20 text-accent-purple hover:bg-accent-purple/30 transition-colors disabled:opacity-40"
          >
            {uploading ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />} 上传简历
          </button>
          <button
            onClick={() => multiRef.current?.click()}
            disabled={uploading || !job}
            className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md bg-surface-700/50 text-slate-400 hover:text-slate-200 hover:bg-surface-700 transition-colors disabled:opacity-40"
          >
            <Files size={13} /> 批量导入
          </button>
          <button
            onClick={() => { setBatchMode(m => !m); setChecked(new Set()); }}
            className={`flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md transition-colors ${batchMode ? 'bg-accent-blue/20 text-accent-blue' : 'bg-surface-700/50 text-slate-400 hover:text-slate-200 hover:bg-surface-700'}`}
          >
            <ListChecks size={13} /> 批量管理
          </button>
          <button
            onClick={() => setGenerateModalOpen(true)}
            disabled={!job}
            className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md bg-accent-blue/20 text-accent-blue hover:bg-accent-blue/30 transition-colors disabled:opacity-40"
          >
            <Sparkles size={13} /> AI生成简历
          </button>
        </div>

        {uploading && (
          <div className="mb-2 px-3 py-2 rounded-md bg-accent-purple/10 border border-accent-purple/25 flex items-center gap-2 animate-fade-in">
            <Loader2 size={13} className="animate-spin text-accent-purple" />
            <span className="text-xs text-accent-purple">{streamProgress || 'AI处理中…'}</span>
          </div>
        )}

        {streamError && (
          <div className="mb-2 px-3 py-2 rounded-md bg-red-500/10 border border-red-500/30 flex items-start gap-2 animate-fade-in">
            <AlertTriangle size={14} className="text-red-400 shrink-0 mt-0.5" />
            <p className="flex-1 min-w-0 text-xs text-red-300/90">{streamError}</p>
            <button onClick={handleBgRetry} disabled={bgUploading} className="text-red-400 hover:text-red-300 shrink-0 disabled:opacity-40" title="后台重试">
              <RotateCw size={13} className={bgUploading ? 'animate-spin' : ''} />
            </button>
            <button onClick={() => { setStreamError(''); retryFileRef.current = null; }} className="text-red-400 hover:text-red-300 shrink-0"><X size={14} /></button>
          </div>
        )}

        {!job && <p className="text-xs text-amber-400/70 mb-2">请先选择或创建岗位</p>}

        {batchMode && (
          <div className="flex items-center gap-2 mb-2 px-2.5 py-1.5 rounded-md bg-accent-blue/10 border border-accent-blue/25 animate-fade-in">
            <button
              onClick={() => setChecked(checked.size === resumes.length ? new Set() : new Set(resumes.map(r => r.id)))}
              className="text-xs text-accent-blue hover:underline"
            >
              {checked.size === resumes.length ? '取消全选' : '全选'}
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

        <div className="flex-1 overflow-y-auto scrollbar-thin space-y-2 pr-1">
          {loading ? (
            <div className="flex items-center justify-center py-6">
              <Loader2 size={16} className="animate-spin text-slate-600" />
            </div>
          ) : resumes.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-6 text-center">
              <FileText size={20} className="text-slate-700 mb-2" />
              <p className="text-xs text-slate-500">暂无简历</p>
              <p className="text-xs text-slate-600 mt-0.5">上传 PDF / Word / 图片，AI 自动生成简历</p>
            </div>
          ) : (
            resumes.map(r => (
              <div
                key={r.id}
                onClick={() => { if (!batchMode) { onSelect(r); if (autoClose) onClose(); } }}
                className={`p-3 rounded-lg border transition-all ${batchMode ? 'cursor-default' : 'cursor-pointer'} ${
                  selectedResume?.id === r.id
                    ? 'bg-accent-blue/10 border-accent-blue/40'
                    : 'bg-surface-800/40 border-slate-700/30 hover:bg-surface-700/40'
                }`}
              >
                <div className="flex items-center gap-2">
                  {batchMode && (
                    <input type="checkbox" checked={checked.has(r.id)} onChange={() => toggleCheck(r.id)}
                      onClick={e => e.stopPropagation()} className="accent-[#5b8def] shrink-0" />
                  )}
                  <p className={`flex-1 min-w-0 text-sm font-medium truncate ${selectedResume?.id === r.id ? 'text-accent-blue' : 'text-slate-200'}`}>
                    {r.title || `简历 #${r.id}`}
                  </p>
                  <DotMenu items={[
                    { label: '删除', danger: true, onClick: () => handleDelete(r) },
                  ]} />
                </div>
                <div className="flex flex-wrap items-center gap-1 mt-1.5">
                  {r.file_type && <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-700/70 text-slate-400 uppercase">{r.file_type}</span>}
                  {r.file_size != null && <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-700/70 text-slate-400">{formatBytes(r.file_size)}</span>}
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-700/70 text-slate-400">{formatDateTime(r.updated_at || r.created_at).split(' ')[0]}</span>
                  {r.angle && <span className="text-[10px] px-1.5 py-0.5 rounded bg-accent-blue/10 text-accent-blue">{r.angle}</span>}
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-700/70 text-slate-500">{wordCount(r)}</span>
                </div>
              </div>
            ))
          )}
        </div>

        <p className="text-[11px] text-slate-600 mt-2 pt-2 border-t border-slate-700/30">共 {resumes.length} 份简历</p>
      </div>

      <GenerateResumeModal
        open={generateModalOpen}
        onClose={() => setGenerateModalOpen(false)}
        job={job}
        onGenerated={(r) => {
          setResumes(prev => [r, ...prev]);
          onSelect(r);
          if (onGenerate) onGenerate();
        }}
      />
    </Modal>
  );
}
