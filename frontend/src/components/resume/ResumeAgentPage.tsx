import { useState, useEffect, useCallback, useRef } from 'react';
import { Briefcase, FileText, Loader2, AlertTriangle, X, RotateCw, Check, Sparkles } from 'lucide-react';
import type { Job, Resume } from '../../api/agentApi';
import { agentApi } from '../../api/agentApi';
import { JobPanel } from './JobPanel';
import { ResumePanel } from './ResumePanel';
import { ChatPanel, type ChatPanelHandle } from './ChatPanel';
import { BrowserPreview, type BrowserPreviewHandle } from './BrowserPreview';
import { RestyleResumeModal, type RestyleParams } from './RestyleResumeModal';
import { RestyleProgressDialog, type RestyleProgressState } from './RestyleProgressDialog';
import { GenerateResumeInline } from './GenerateResumeInline';

interface UploadTask {
  id: number;
  filename: string;
  status: 'uploading' | 'error' | 'done';
  mode: 'modal' | 'toast';
  message?: string;
  retryFile?: File;
  jobId?: number;
}

const DEFAULT_RATIO = 0.38;
const MIN_RATIO = 0.2;
const MAX_RATIO = 0.65;

export function ResumeAgentPage() {
  const [job, setJob] = useState<Job | null>(null);
  const [resume, setResume] = useState<Resume | null>(null);
  const [resumeTick, setResumeTick] = useState(0);
  const [jobModalOpen, setJobModalOpen] = useState(false);
  const [resumeModalOpen, setResumeModalOpen] = useState(false);
  const [restyleModalOpen, setRestyleModalOpen] = useState(false);
  const [restyleProgress, setRestyleProgress] = useState<RestyleProgressState | null>(null);
  const restyleAbortRef = useRef<AbortController | null>(null);
  const restyleParamsRef = useRef<RestyleParams | null>(null);
  const restyleResumeIdRef = useRef<number | null>(null);
  const [sourceHtml, setSourceHtml] = useState('');
  const [generatePanelOpen, setGeneratePanelOpen] = useState(false);

  const [splitRatio, setSplitRatio] = useState(DEFAULT_RATIO);
  const [dragging, setDragging] = useState(false);
  const [chatCollapsed, setChatCollapsed] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const chatPanelRef = useRef<ChatPanelHandle>(null);
  const browserPreviewRef = useRef<BrowserPreviewHandle>(null);

  // ── 后台上传任务（关闭弹窗不影响进度）──
  const [uploadTasks, setUploadTasks] = useState<UploadTask[]>([]);
  const uploadIdRef = useRef(0);
  const abortControllersRef = useRef<Map<number, AbortController>>(new Map());

  const updateTask = useCallback((id: number, patch: Partial<UploadTask>) => {
    setUploadTasks(prev => prev.map(t => (t.id === id ? { ...t, ...patch } : t)));
  }, []);

  const removeTask = useCallback((id: number) => {
    setUploadTasks(prev => prev.filter(t => t.id !== id));
  }, []);

  const runUpload = useCallback(async (jobId: number, file: File, id: number) => {
    const controller = new AbortController();
    abortControllersRef.current.set(id, controller);
    updateTask(id, { status: 'uploading', message: undefined, retryFile: file, jobId });
    try {
      await agentApi.uploadAndGenerate(jobId, file, undefined, controller.signal);
      updateTask(id, { status: 'done' });
      setResumeTick(t => t + 1);
      setTimeout(() => setUploadTasks(prev => prev.filter(t => t.id !== id)), 3000);
    } catch (e: any) {
      if (controller.signal.aborted || e?.name === 'AbortError') {
        removeTask(id);
        return;
      }
      updateTask(id, { status: 'error', message: e.message || '上传生成简历失败' });
    } finally {
      abortControllersRef.current.delete(id);
    }
  }, [updateTask, removeTask]);

  const startBgUpload = useCallback((jobId: number, file: File) => {
    const id = ++uploadIdRef.current;
    setUploadTasks(prev => [...prev, { id, filename: file.name, status: 'uploading', mode: 'modal', retryFile: file, jobId }]);
    runUpload(jobId, file, id);
  }, [runUpload]);

  const retryUpload = useCallback((id: number) => {
    const task = uploadTasks.find(t => t.id === id);
    if (!task?.retryFile || !task.jobId) return;
    runUpload(task.jobId, task.retryFile, id);
  }, [uploadTasks, runUpload]);

  const abortUpload = useCallback((id: number) => {
    abortControllersRef.current.get(id)?.abort();
    removeTask(id);
  }, [removeTask]);

  const abortAllModal = useCallback(() => {
    setUploadTasks(prev => {
      prev.filter(t => t.mode === 'modal').forEach(t => {
        abortControllersRef.current.get(t.id)?.abort();
      });
      return prev.filter(t => t.mode !== 'modal');
    });
  }, []);

  const toBackgroundAll = useCallback(() => {
    setUploadTasks(prev => prev.map(t => (t.mode === 'modal' ? { ...t, mode: 'toast' } : t)));
  }, []);

  useEffect(() => {
    if (resume?.rendered_html) {
      setSourceHtml(resume.rendered_html);
    } else {
      setSourceHtml('');
    }
  }, [resume?.id]);

  const handleResumeSelect = (r: Resume | null) => {
    if (!r) { setResume(null); setSourceHtml(''); return; }
    setResumeModalOpen(false);
    setResume(r);
    if (r.rendered_html) {
      setSourceHtml(r.rendered_html);
    } else {
      setSourceHtml('');
    }
  };

  const handleResumeSaved = (r: Resume) => {
    setResume(r);
    setResumeTick(t => t + 1);
    if (r.rendered_html) {
      setSourceHtml(r.rendered_html);
    } else {
      setSourceHtml('');
    }
  };

  const runRestyle = useCallback(async (resumeId: number, params: RestyleParams) => {
    restyleAbortRef.current = new AbortController();
    restyleParamsRef.current = params;
    restyleResumeIdRef.current = resumeId;
    setRestyleProgress({ status: 'running' });

    try {
      let finalResumeId: number | null = null;
      for await (const chunk of agentApi.restyleResumeStream(
        resumeId,
        params.style,
        params.accent,
        params.description,
        params.avatarBase64 || undefined,
        params.refImageBase64 || undefined,
      )) {
        if (chunk.type === 'done' && chunk.resume_id) {
          finalResumeId = chunk.resume_id;
        } else if (chunk.type === 'error' && chunk.content) {
          setRestyleProgress({ status: 'error', error: chunk.content });
          return;
        }
      }

      if (finalResumeId) {
        const updated = await agentApi.getResume(finalResumeId);
        setResume(updated);
        setResumeTick(t => t + 1);
        setSourceHtml(updated.rendered_html || '');
        setRestyleProgress({ status: 'done' });
        setTimeout(() => setRestyleProgress(null), 4000);
      } else {
        setRestyleProgress({ status: 'error', error: '重新排版未返回有效结果，请重试' });
      }
    } catch (e: any) {
      if (restyleAbortRef.current?.signal.aborted) return;
      let msg = e.message || '重新排版失败';
      try {
        const parsed = JSON.parse(msg);
        if (parsed.detail) msg = parsed.detail;
      } catch { /* keep */ }
      setRestyleProgress({ status: 'error', error: msg });
    }
  }, []);

  const handleRestyleConfirm = useCallback((params: RestyleParams) => {
    if (!resume) return;
    setRestyleModalOpen(false);
    runRestyle(resume.id, params);
  }, [resume, runRestyle]);

  const handleRestyleRetry = useCallback(() => {
    const params = restyleParamsRef.current;
    const resumeId = restyleResumeIdRef.current;
    if (!params || !resumeId) return;
    runRestyle(resumeId, params);
  }, [runRestyle]);

  const handleRestyleDismiss = useCallback(() => {
    setRestyleProgress(null);
  }, []);

  const handleSourceHtmlChange = (html: string) => {
    setSourceHtml(html);
  };

  const handleInsertTag = useCallback((tagName: string, sectionId?: string, textContent?: string) => {
    chatPanelRef.current?.insertDomTag(tagName, sectionId, textContent);
  }, []);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (chatCollapsed) return;
    e.preventDefault();
    setDragging(true);
  }, [chatCollapsed]);

  useEffect(() => {
    if (!dragging) return;
    const handleMouseMove = (e: MouseEvent) => {
      if (!containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const ratio = (e.clientX - rect.left) / rect.width;
      setSplitRatio(Math.min(MAX_RATIO, Math.max(MIN_RATIO, ratio)));
    };
    const handleMouseUp = () => {
      setDragging(false);
    };
    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
  }, [dragging]);

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <div className="shrink-0 px-5 pt-4 pb-3 border-b border-slate-700/30">
        <div className="flex items-center justify-between mb-2">
          <div>
            <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
              简历优化 Agent
              <span className="text-xs px-1.5 py-0.5 rounded bg-accent-blue/20 text-accent-blue font-normal">AI修改</span>
            </h1>
            <p className="text-sm text-slate-500 mt-0.5">AI一键生成简历 → 智能修改 → 导出</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setJobModalOpen(true)}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-slate-700/40 bg-surface-800/40 hover:bg-surface-700/40 transition-colors text-sm"
          >
            <Briefcase size={14} className="text-accent-purple" />
            <span className="text-slate-300">岗位：</span>
            <span className="text-accent-blue font-medium truncate max-w-[200px]">{job?.title || '未选择'}</span>
          </button>
          <button
            onClick={() => setResumeModalOpen(true)}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-slate-700/40 bg-surface-800/40 hover:bg-surface-700/40 transition-colors text-sm"
          >
            <FileText size={14} className="text-accent-blue" />
            <span className="text-slate-300">简历：</span>
            <span className="text-accent-blue font-medium truncate max-w-[200px]">{resume?.title || '未选择'}</span>
          </button>
          <button
            onClick={() => setGeneratePanelOpen(p => !p)}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border transition-colors text-sm ${
              generatePanelOpen
                ? 'border-accent-purple/40 bg-accent-purple/10 text-accent-purple'
                : 'border-slate-700/40 bg-surface-800/40 hover:bg-surface-700/40 text-slate-300'
            }`}
          >
            <Sparkles size={14} className="text-accent-purple" />
            AI 生成简历
          </button>
        </div>
      </div>

      <JobPanel open={jobModalOpen} onClose={() => setJobModalOpen(false)} selectedJob={job} onSelect={(j) => { setJob(j); setResume(null); }} />
      <ResumePanel open={resumeModalOpen} onClose={() => setResumeModalOpen(false)} job={job} selectedResume={resume} onSelect={handleResumeSelect} onGenerate={() => setResumeTick(t => t + 1)} refreshTick={resumeTick} autoClose={false} onBgUpload={job ? (file) => startBgUpload(job.id, file) : undefined} />

      {/* 上传进度：居中弹窗模式（后台继续 / 关闭中断） */}
      {uploadTasks.some(t => t.mode === 'modal') && (
        <div className="fixed inset-0 z-[80] flex items-center justify-center">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={abortAllModal} />
          <div className="relative bg-surface-800 border border-slate-700/60 rounded-xl shadow-2xl w-[420px] max-w-[92vw] animate-fade-in">
            <div className="px-5 py-3 border-b border-slate-700/30 flex items-center gap-2">
              <Loader2 size={14} className="animate-spin text-accent-blue" />
              <span className="text-sm font-semibold text-slate-200">AI 识别简历</span>
            </div>
            <div className="px-5 py-4 space-y-2 max-h-[40vh] overflow-y-auto scrollbar-thin">
              {uploadTasks.filter(t => t.mode === 'modal').map(task => (
                <div key={task.id} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-surface-900/50 border border-slate-700/40">
                  {task.status === 'uploading' && <Loader2 size={13} className="animate-spin text-accent-blue shrink-0" />}
                  {task.status === 'error' && <AlertTriangle size={13} className="text-red-400 shrink-0" />}
                  {task.status === 'done' && <Check size={13} className="text-emerald-400 shrink-0" />}
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-slate-200 truncate">{task.filename}</p>
                    <p className={`text-[11px] mt-0.5 ${
                      task.status === 'error' ? 'text-red-300/90' : task.status === 'done' ? 'text-emerald-300/90' : 'text-slate-400'
                    }`}>
                      {task.status === 'uploading' && '正在上传并 AI 识别简历…'}
                      {task.status === 'done' && '生成完成'}
                      {task.status === 'error' && (task.message || '上传失败')}
                    </p>
                  </div>
                </div>
              ))}
            </div>
            <div className="px-5 py-3 border-t border-slate-700/30 flex gap-2 justify-end">
              <button
                onClick={abortAllModal}
                className="px-3 py-1.5 text-xs rounded-lg bg-surface-700/50 text-slate-400 hover:text-red-400 hover:bg-red-500/10 transition-colors"
              >
                关闭并中断
              </button>
              <button
                onClick={toBackgroundAll}
                className="px-3 py-1.5 text-xs rounded-lg bg-accent-blue/20 text-accent-blue hover:bg-accent-blue/30 transition-colors"
              >
                后台继续
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 后台上传 Toast（点「后台继续」后显示，关闭仅隐藏通知，上传继续） */}
      {uploadTasks.some(t => t.mode === 'toast') && (
        <div className="fixed bottom-5 right-5 z-[70] flex flex-col gap-2 w-80 max-w-[calc(100vw-40px)]">
          {uploadTasks.filter(t => t.mode === 'toast').map(task => (
            <div
              key={task.id}
              className={`rounded-lg border px-3 py-2.5 shadow-2xl bg-surface-800/95 backdrop-blur animate-fade-in flex items-start gap-2 ${
                task.status === 'error'
                  ? 'border-red-500/30'
                  : task.status === 'done'
                    ? 'border-emerald-500/30'
                    : 'border-accent-blue/30'
              }`}
            >
              {task.status === 'uploading' && <Loader2 size={15} className="animate-spin text-accent-blue shrink-0 mt-0.5" />}
              {task.status === 'error' && <AlertTriangle size={15} className="text-red-400 shrink-0 mt-0.5" />}
              {task.status === 'done' && <Check size={15} className="text-emerald-400 shrink-0 mt-0.5" />}
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium text-slate-200 truncate">{task.filename}</p>
                <p className={`text-[11px] mt-0.5 ${
                  task.status === 'error' ? 'text-red-300/90' : task.status === 'done' ? 'text-emerald-300/90' : 'text-slate-400'
                }`}>
                  {task.status === 'uploading' && 'AI 识别简历中，可继续其他操作…'}
                  {task.status === 'done' && '生成完成，已加入简历库'}
                  {task.status === 'error' && (task.message || '上传失败')}
                </p>
              </div>
              {task.status === 'error' && (
                <button onClick={() => retryUpload(task.id)} className="text-red-400 hover:text-red-300 shrink-0" title="重试">
                  <RotateCw size={13} />
                </button>
              )}
              <button onClick={() => removeTask(task.id)} className="text-slate-500 hover:text-slate-300 shrink-0">
                <X size={13} />
              </button>
            </div>
          ))}
        </div>
      )}

      <div ref={containerRef} className="flex-1 flex min-h-0 overflow-hidden">
        {!chatCollapsed && (
          <div style={{ width: `${splitRatio * 100}%` }} className="min-w-[280px] flex flex-col overflow-hidden">
            <ChatPanel
              ref={chatPanelRef}
              job={job}
              resume={resume}
              onResumeSaved={handleResumeSaved}
              sourceHtml={sourceHtml}
              onSourceHtmlChange={handleSourceHtmlChange}
            />
          </div>
        )}

        {!chatCollapsed && (
          <div
            onMouseDown={handleMouseDown}
            className={`split-handle shrink-0 ${dragging ? 'split-handle-active' : ''}`}
          />
        )}

        <div className="flex-1 min-w-[300px] min-h-0 flex flex-col overflow-hidden relative">
          <BrowserPreview
            ref={browserPreviewRef}
            resume={resume}
            job={job}
            onSaved={handleResumeSaved}
            onInsertTag={handleInsertTag}
            sourceHtml={sourceHtml}
            onSourceHtmlChange={handleSourceHtmlChange}
            onRestyle={() => setRestyleModalOpen(true)}
            sidebarCollapsed={chatCollapsed}
            onToggleSidebar={() => setChatCollapsed(c => !c)}
          />
          <GenerateResumeInline
            job={job}
            onGenerated={(r) => {
              setResume(r);
              setResumeTick(t => t + 1);
              if (r.rendered_html) setSourceHtml(r.rendered_html);
              setGeneratePanelOpen(false);
            }}
            visible={generatePanelOpen}
            onClose={() => setGeneratePanelOpen(false)}
          />
        </div>
      </div>

      <RestyleResumeModal
        open={restyleModalOpen}
        onClose={() => setRestyleModalOpen(false)}
        resume={resume}
        job={job}
        onConfirm={handleRestyleConfirm}
      />

      {restyleProgress && (
        <RestyleProgressDialog
          state={restyleProgress}
          onDismiss={handleRestyleDismiss}
          onRetry={restyleProgress.status === 'error' ? handleRestyleRetry : undefined}
        />
      )}
    </div>
  );
}
