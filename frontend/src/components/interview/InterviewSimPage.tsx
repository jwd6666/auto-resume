import { useCallback, useEffect, useRef, useState } from 'react';
import {
  MessageCircleQuestion, Bot, User, Send, Loader2, RotateCw,
  ClipboardCheck, Briefcase, FileText, Sparkles, AlertCircle,
} from 'lucide-react';
import clsx from 'clsx';
import { agentApi, type InterviewQuestionnaire, type Resume } from '../../api/agentApi';
import { useJobs } from '../../store/useJobs';
import { Modal } from '../resume/ui';

interface ChatEntry {
  role: 'user' | 'assistant';
  content: string;
  hidden?: boolean;
  streaming?: boolean;
}

const REACTION_MARK = '<<<REACTION>>>';
const SPEECH_MARK = '<<<SPEECH>>>';

/** 拆分面试官输出：REACTION 为神态/动作，SPEECH 为口头提问 */
function parseInterviewerText(content: string): { reaction: string; speech: string } {
  const rIdx = content.indexOf(REACTION_MARK);
  const sIdx = content.indexOf(SPEECH_MARK);
  let reaction = '';
  let speech = content;

  if (rIdx !== -1) {
    const end = sIdx !== -1 ? sIdx : content.length;
    reaction = content.slice(rIdx + REACTION_MARK.length, end).trim();
    speech = sIdx !== -1 ? content.slice(sIdx + SPEECH_MARK.length) : '';
  } else if (sIdx !== -1) {
    speech = content.slice(sIdx + SPEECH_MARK.length);
  }

  return { reaction, speech: speech.trim() };
}

/** 过滤空消息并转为后端消息格式；includeHidden 用于携带开场的隐藏触发语 */
function toApiMessages(list: ChatEntry[], includeHidden = false) {
  return list
    .filter((m) => (includeHidden || !m.hidden) && m.content.trim())
    .map((m) => ({ role: m.role, content: m.content }));
}

export function InterviewSimPage() {
  const jobs = useJobs((s) => s.jobs);
  const refreshJobs = useJobs((s) => s.refresh);

  const [jobId, setJobId] = useState<number | ''>('');
  const [resumes, setResumes] = useState<Resume[]>([]);
  const [resumeId, setResumeId] = useState<number | ''>('');
  const [loadingResumes, setLoadingResumes] = useState(false);

  const [categories, setCategories] = useState<string[]>([]);
  const [selectedCategories, setSelectedCategories] = useState<Set<string>>(new Set());
  const [total, setTotal] = useState(7);
  const [background, setBackground] = useState('');

  const [questionnaire, setQuestionnaire] = useState<InterviewQuestionnaire | null>(null);
  const [phase, setPhase] = useState<'setup' | 'chat'>('setup');
  const [starting, setStarting] = useState(false);
  const [messages, setMessages] = useState<ChatEntry[]>([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState('');

  const [report, setReport] = useState<string | null>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [reporting, setReporting] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => { refreshJobs().catch(() => {}); }, [refreshJobs]);

  useEffect(() => {
    agentApi.getInterviewCategories().then(setCategories).catch(() => {});
  }, []);

  // 岗位变化 → 拉取该岗位下的简历
  useEffect(() => {
    if (!jobId) { setResumes([]); setResumeId(''); return; }
    let alive = true;
    setLoadingResumes(true);
    agentApi.listResumes(Number(jobId))
      .then((list) => {
        if (!alive) return;
        setResumes(list);
        setResumeId(list[0]?.id ?? '');
      })
      .catch(() => { if (alive) { setResumes([]); setResumeId(''); } })
      .finally(() => { if (alive) setLoadingResumes(false); });
    return () => { alive = false; };
  }, [jobId]);

  // 切换岗位/简历时终止当前面试，回到准备状态
  useEffect(() => {
    abortRef.current?.abort();
    setPhase('setup');
    setMessages([]);
    setQuestionnaire(null);
    setReport(null);
    setReportOpen(false);
    setError('');
  }, [jobId, resumeId]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const streamAssistant = useCallback(async (history: ChatEntry[], questionnaireMarkdown: string) => {
    if (!jobId || !resumeId) return;
    const controller = new AbortController();
    abortRef.current = controller;
    setStreaming(true);
    setError('');
    setMessages([...history, { role: 'assistant', content: '', streaming: true }]);

    let acc = '';
    try {
      for await (const ev of agentApi.interviewSimStream({
        jobId: Number(jobId),
        resumeId: Number(resumeId),
        messages: toApiMessages(history, true),
        userBackground: background.trim() || undefined,
        questionnaireMarkdown,
        signal: controller.signal,
      })) {
        if (ev.type === 'text') {
          acc += ev.content || '';
          setMessages((prev) => prev.map((m, i) => (i === prev.length - 1 ? { ...m, content: acc } : m)));
        } else if (ev.type === 'error') {
          setError(ev.content || '面试对话中断');
          break;
        }
      }
    } catch (e: any) {
      if (!controller.signal.aborted) setError(e.message || '面试对话失败');
    } finally {
      setMessages((prev) => {
        const last = prev[prev.length - 1];
        if (last && last.role === 'assistant' && !last.content.trim()) return prev.slice(0, -1);
        return prev.map((m, i) => (i === prev.length - 1 ? { ...m, streaming: false } : m));
      });
      setStreaming(false);
      abortRef.current = null;
    }
  }, [jobId, resumeId, background]);

  const startInterview = async () => {
    if (!jobId || !resumeId) { setError('请先选择岗位和简历'); return; }
    setStarting(true);
    setError('');
    try {
      const q = await agentApi.getInterviewQuestionnaire({
        jobId: Number(jobId),
        resumeId: Number(resumeId),
        total,
        categories: Array.from(selectedCategories),
      });
      setQuestionnaire(q);
      setReport(null);
      setPhase('chat');
      setInput('');
      const hiddenPrompt: ChatEntry = { role: 'user', content: '（候选人已就坐，请开始面试。）', hidden: true };
      setMessages([hiddenPrompt]);
      await streamAssistant([hiddenPrompt], q.questionnaire_markdown);
    } catch (e: any) {
      setError(e.message || '开始面试失败');
    } finally {
      setStarting(false);
    }
  };

  const sendAnswer = async () => {
    const text = input.trim();
    if (!text || streaming || starting) return;
    const history: ChatEntry[] = [...messages, { role: 'user', content: text }];
    setInput('');
    setMessages(history);
    await streamAssistant(history, questionnaire?.questionnaire_markdown || '');
  };

  const finishInterview = async () => {
    const history = toApiMessages(messages);
    if (!history.some((m) => m.role === 'user') || !history.some((m) => m.role === 'assistant')) {
      setError('还没有问答内容，先和面试官聊几句吧');
      return;
    }
    if (!jobId || !resumeId) return;
    setReporting(true);
    setError('');
    try {
      const res = await agentApi.generateInterviewReport({
        jobId: Number(jobId),
        resumeId: Number(resumeId),
        messages: history,
        userBackground: background.trim() || undefined,
      });
      setReport(res.report);
      setReportOpen(true);
    } catch (e: any) {
      setError(e.message || '生成面试报告失败');
    } finally {
      setReporting(false);
    }
  };

  const toggleCategory = (c: string) => {
    setSelectedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(c)) next.delete(c); else next.add(c);
      return next;
    });
  };

  const currentJob = jobs.find((j) => j.id === Number(jobId));
  const currentResume = resumes.find((r) => r.id === Number(resumeId));
  const canStart = !!jobId && !!resumeId && !starting && !streaming;
  const visibleMessages = messages.filter((m) => !m.hidden);

  return (
    <div className="p-5 h-full flex flex-col animate-fade-in min-h-0">
      {/* Header */}
      <div className="flex items-center justify-between mb-4 shrink-0 flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            <MessageCircleQuestion size={20} className="text-accent-purple" />
            AI 模拟面试
          </h1>
          <p className="text-sm text-slate-500 mt-0.5">AI 面试官根据岗位与简历出题，和你进行一轮真实对话</p>
        </div>
        {phase === 'chat' && (
          <div className="flex items-center gap-2">
            <button
              onClick={startInterview}
              disabled={streaming || starting}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-surface-800/60 border border-slate-700/50 text-xs text-slate-300 hover:bg-surface-700/60 transition-colors disabled:opacity-40"
            >
              <RotateCw size={13} /> 换一套题
            </button>
            <button
              onClick={finishInterview}
              disabled={reporting || streaming || starting}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg bg-accent-purple/15 border border-accent-purple/30 text-xs text-accent-purple hover:bg-accent-purple/25 transition-colors disabled:opacity-40"
            >
              {reporting ? <Loader2 size={13} className="animate-spin" /> : <ClipboardCheck size={13} />}
              {reporting ? '正在生成复盘…' : '结束面试并复盘'}
            </button>
          </div>
        )}
      </div>

      {error && (
        <div className="mb-3 shrink-0 flex items-center gap-2 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-xs text-red-300">
          <AlertCircle size={13} className="shrink-0" />
          <span className="flex-1">{error}</span>
          <button onClick={() => setError('')} className="text-red-400/70 hover:text-red-300">×</button>
        </div>
      )}

      <div className="flex-1 flex gap-4 min-h-0 lg:flex-row flex-col">
        {/* Left: setup */}
        <div className="w-full lg:w-[320px] shrink-0 flex flex-col min-h-0 overflow-y-auto scrollbar-thin pr-0.5">
          <div className="card p-4 space-y-3.5">
            <div>
              <h2 className="text-sm font-semibold text-slate-200">面试设置</h2>
              <p className="text-xs text-slate-500 mt-0.5">选择目标岗位与简历，AI 将围绕它们提问</p>
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1.5">目标岗位</label>
              <select
                value={jobId}
                onChange={(e) => setJobId(e.target.value ? Number(e.target.value) : '')}
                className="w-full px-3 py-2 rounded-lg bg-surface-900/60 border border-slate-700/50 text-sm text-slate-200 focus:outline-none focus:border-accent-blue/50"
              >
                <option value="">请选择岗位</option>
                {jobs.map((j) => (
                  <option key={j.id} value={j.id}>{j.title}</option>
                ))}
              </select>
              {jobs.length === 0 && (
                <p className="text-[11px] text-slate-500 mt-1.5">还没有岗位，请先到「岗位管理」添加</p>
              )}
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1.5">候选人简历</label>
              <select
                value={resumeId}
                onChange={(e) => setResumeId(e.target.value ? Number(e.target.value) : '')}
                disabled={!jobId || loadingResumes}
                className="w-full px-3 py-2 rounded-lg bg-surface-900/60 border border-slate-700/50 text-sm text-slate-200 focus:outline-none focus:border-accent-blue/50 disabled:opacity-40"
              >
                <option value="">{loadingResumes ? '加载中…' : '请选择简历'}</option>
                {resumes.map((r) => (
                  <option key={r.id} value={r.id}>{r.title || `简历 #${r.id}`}</option>
                ))}
              </select>
              {jobId && !loadingResumes && resumes.length === 0 && (
                <p className="text-[11px] text-slate-500 mt-1.5">该岗位下还没有简历，请先到「简历优化」上传</p>
              )}
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1.5">题目类型（不选则全部随机）</label>
              <div className="flex flex-wrap gap-1.5">
                {categories.map((c) => {
                  const active = selectedCategories.has(c);
                  return (
                    <button
                      key={c}
                      onClick={() => toggleCategory(c)}
                      disabled={phase === 'chat' && streaming}
                      className={clsx(
                        'px-2 py-1 rounded-md text-[11px] border transition-colors disabled:opacity-40',
                        active
                          ? 'bg-accent-blue/15 border-accent-blue/40 text-accent-blue'
                          : 'bg-surface-900/40 border-slate-700/40 text-slate-400 hover:text-slate-300',
                      )}
                    >
                      {c}
                    </button>
                  );
                })}
                {categories.length === 0 && <span className="text-[11px] text-slate-600">暂无题类</span>}
              </div>
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1.5">
                题目数量 <span className="text-slate-200 font-medium">{total}</span>
              </label>
              <input
                type="range"
                min={3}
                max={12}
                value={total}
                onChange={(e) => setTotal(Number(e.target.value))}
                className="w-full accent-sky-500"
              />
            </div>

            <div>
              <label className="block text-xs text-slate-400 mb-1.5">补充经历（可选）</label>
              <textarea
                value={background}
                onChange={(e) => setBackground(e.target.value)}
                placeholder="可粘贴简历之外的经历、项目亮点…"
                rows={3}
                className="w-full px-3 py-2 rounded-lg bg-surface-900/60 border border-slate-700/50 text-xs text-slate-200 resize-none focus:outline-none focus:border-accent-blue/50 placeholder:text-slate-600 scrollbar-thin"
              />
            </div>

            <button
              onClick={startInterview}
              disabled={!canStart}
              className={clsx(
                'w-full py-2.5 rounded-lg text-sm font-medium flex items-center justify-center gap-2 transition-all',
                canStart
                  ? 'bg-gradient-to-r from-purple-600 to-blue-600 text-white hover:from-purple-500 hover:to-blue-500 shadow-lg shadow-purple-500/20'
                  : 'bg-surface-700/40 text-slate-500 cursor-not-allowed',
              )}
            >
              {starting ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
              {starting ? '正在准备面试…' : phase === 'chat' ? '重新开始面试' : '开始面试'}
            </button>
          </div>

          {/* Question list */}
          {questionnaire && (
            <div className="card p-4 mt-3">
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-xs font-semibold text-slate-300">本场题单</h3>
                <span className="text-[10px] text-slate-500">{questionnaire.items.length} 题</span>
              </div>
              <div className="space-y-1.5 max-h-64 overflow-y-auto scrollbar-thin pr-0.5">
                {questionnaire.items.map((q, i) => (
                  <div key={q.id} className="flex gap-2 text-[11px] leading-snug">
                    <span className="text-slate-600 shrink-0">{i + 1}.</span>
                    <div className="min-w-0">
                      <span className="text-accent-blue/80">【{q.category}】</span>
                      <span className="text-slate-400">{q.text}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Right: chat */}
        <div className="flex-1 min-w-0 min-h-0 flex flex-col">
          <div className="card flex flex-col flex-1 min-h-0 overflow-hidden">
            <div className="px-4 py-2.5 border-b border-slate-700/30 flex items-center gap-2 shrink-0">
              <Bot size={15} className="text-accent-purple" />
              <span className="text-sm font-semibold text-slate-200">AI 面试官</span>
              {currentJob && (
                <span className="text-[11px] text-slate-500 flex items-center gap-1 ml-2">
                  <Briefcase size={11} /> {currentJob.title}
                </span>
              )}
              {currentResume && (
                <span className="text-[11px] text-slate-500 flex items-center gap-1">
                  <FileText size={11} /> {currentResume.title || `简历 #${currentResume.id}`}
                </span>
              )}
            </div>

            {/* Messages */}
            <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto scrollbar-thin px-4 py-4 space-y-4">
              {visibleMessages.length === 0 ? (
                <div className="h-full flex flex-col items-center justify-center text-center">
                  <div className="w-16 h-16 rounded-2xl bg-surface-800/60 flex items-center justify-center mb-4">
                    <MessageCircleQuestion size={28} className="text-slate-600" />
                  </div>
                  <p className="text-sm text-slate-400">选择岗位与简历，点击「开始面试」</p>
                  <p className="text-xs text-slate-600 mt-1">AI 面试官会根据 JD 和简历，在对话框里逐题提问</p>
                </div>
              ) : (
                visibleMessages.map((m, i) => {
                  if (m.role === 'user') {
                    return (
                      <div key={i} className="flex justify-end gap-2.5">
                        <div className="max-w-[80%] px-3.5 py-2.5 rounded-2xl rounded-tr-sm bg-brand-600/80 text-sm text-white whitespace-pre-wrap leading-relaxed">
                          {m.content}
                        </div>
                        <div className="w-7 h-7 rounded-full bg-surface-700 flex items-center justify-center shrink-0">
                          <User size={14} className="text-slate-400" />
                        </div>
                      </div>
                    );
                  }
                  const { reaction, speech } = parseInterviewerText(m.content);
                  return (
                    <div key={i} className="flex gap-2.5">
                      <div className="w-7 h-7 rounded-full bg-accent-purple/20 flex items-center justify-center shrink-0">
                        <Bot size={14} className="text-accent-purple" />
                      </div>
                      <div className="max-w-[82%] min-w-0">
                        {reaction && (
                          <p className="text-[11px] text-slate-500 italic mb-1.5 whitespace-pre-wrap">（{reaction}）</p>
                        )}
                        <div className="px-3.5 py-2.5 rounded-2xl rounded-tl-sm bg-surface-800/80 border border-slate-700/40 text-sm text-slate-200 whitespace-pre-wrap leading-relaxed">
                          {speech || (!reaction && m.content) || ''}
                          {m.streaming && <span className="inline-block w-1.5 h-4 ml-0.5 align-middle bg-accent-blue/70 animate-pulse" />}
                        </div>
                      </div>
                    </div>
                  );
                })
              )}
            </div>

            {/* Input */}
            <div className="border-t border-slate-700/30 p-3 shrink-0">
              <div className="flex items-end gap-2">
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      sendAnswer();
                    }
                  }}
                  disabled={phase !== 'chat' || streaming || starting}
                  rows={2}
                  placeholder={phase === 'chat' ? '输入你的回答，Enter 发送，Shift+Enter 换行' : '开始面试后可在此作答'}
                  className="flex-1 px-3 py-2 rounded-xl bg-surface-900/60 border border-slate-700/50 text-sm text-slate-200 resize-none focus:outline-none focus:border-accent-blue/50 placeholder:text-slate-600 scrollbar-thin disabled:opacity-50"
                />
                <button
                  onClick={sendAnswer}
                  disabled={phase !== 'chat' || streaming || starting || !input.trim()}
                  className={clsx(
                    'px-4 py-2.5 rounded-xl text-sm font-medium flex items-center gap-1.5 shrink-0 transition-colors',
                    phase === 'chat' && !streaming && !starting && input.trim()
                      ? 'bg-brand-600 text-white hover:bg-brand-500'
                      : 'bg-surface-700/40 text-slate-500 cursor-not-allowed',
                  )}
                >
                  {streaming ? <Loader2 size={15} className="animate-spin" /> : <Send size={15} />}
                  发送
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <Modal open={reportOpen} onClose={() => setReportOpen(false)} title="面试复盘报告" icon={<ClipboardCheck size={15} className="text-accent-purple" />}>
        <pre className="whitespace-pre-wrap break-words text-xs leading-relaxed text-slate-300 font-sans">
          {report || ''}
        </pre>
      </Modal>
    </div>
  );
}