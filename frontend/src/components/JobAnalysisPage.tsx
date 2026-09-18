import { useState, useRef, useCallback, useEffect } from 'react';
import {
  ImagePlus, Sparkles, Copy, Check, Loader2,
  ChevronDown, ArrowRight, Briefcase, Target, TrendingUp,
  FileText, ImageIcon, Cpu, Settings, BookOpen, ListChecks, HelpCircle,
} from 'lucide-react';
import clsx from 'clsx';
import { agentApi, type CustomModel, type Job } from '../api/agentApi';
import { useJobs } from '../store/useJobs';

const isDev = location.port === '5173';
const isElectron = !!(window as any).autoresume?.apiBase;
const API_BASE = isDev ? '' : (isElectron ? (window as any).autoresume.apiBase : '');
const AGENT = `${API_BASE}/agent`;

interface JdParseResult {
  title: string;
  company: string | null;
  responsibilities: string[];
  requirements: string[];
  raw_text: string;
}

interface SkillItem {
  name: string;
  level: 'required' | 'preferred' | 'bonus';
  description: string;
}

interface KnowledgeItem {
  topic: string;
  description: string;
  resources: string[];
}

interface PlanPhase {
  phase: string;
  duration: string;
  goals: string[];
  actions: string[];
}

interface InterviewQuestion {
  category: string;
  question: string;
  hints: string[];
}

interface AnalysisResult {
  job_title: string;
  summary: string;
  skills: SkillItem[];
  knowledge: KnowledgeItem[];
  plan: PlanPhase[];
  interview_questions: InterviewQuestion[];
}

interface ProviderConfig {
  name: string;
  name_cn: string;
  type: string;
  base_url?: string;
  env_key: string;
  models: { id: string; name: string; multimodal?: boolean }[];
  default_model: string;
}

interface ModelOption {
  providerKey: string;
  modelId: string;
  label: string;
  hasKey: boolean;
}

async function parseJdImage(file: File): Promise<JdParseResult> {
  const fd = new FormData();
  fd.append('file', file);
  const r = await fetch(`${AGENT}/greeting-generator/parse-jd-image`, {
    method: 'POST',
    body: fd,
  });
  if (!r.ok) {
    let msg = 'JD图片识别失败';
    try { msg = await r.text(); } catch { /* */ }
    throw new Error(msg);
  }
  return r.json();
}

async function analyzeJob(params: { jd_text: string }): Promise<AnalysisResult> {
  const r = await fetch(`${AGENT}/job-analysis/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!r.ok) {
    let msg = '职位分析失败';
    try { msg = await r.text(); } catch { /* */ }
    throw new Error(msg);
  }
  return r.json();
}

const LEVEL_STYLES = {
  required: { bg: 'bg-red-500/15', text: 'text-red-400', label: '必备' },
  preferred: { bg: 'bg-amber-500/15', text: 'text-amber-400', label: '加分' },
  bonus: { bg: 'bg-green-500/15', text: 'text-green-400', label: '锦上添花' },
};

const SECTION_COLORS = ['#0ea5e9', '#8b5cf6', '#f97316', '#22c55e'];

export function JobAnalysisPage() {
  const [inputMode, setInputMode] = useState<'upload' | 'manual'>('upload');
  const [manualText, setManualText] = useState('');
  const [jdParsed, setJdParsed] = useState<JdParseResult | null>(null);
  const [parsing, setParsing] = useState(false);
  const [parseError, setParseError] = useState('');

  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState('');
  const [copiedSection, setCopiedSection] = useState<string | null>(null);

  const [modelOptions, setModelOptions] = useState<ModelOption[]>([]);
  const selectedProviderRef = useRef('');
  const selectedModelRef = useRef('');
  const [selectedLabel, setSelectedLabel] = useState('');
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false);
  const [modelReady, setModelReady] = useState<boolean | null>(null);

  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    skills: true, knowledge: true, plan: true, questions: true,
  });

  const jobList = useJobs((s) => s.jobs);
  const refreshJobs = useJobs((s) => s.refresh);
  const [jobDropdownOpen, setJobDropdownOpen] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadModels = useCallback(() => {
    agentApi.getSettings().then(s => {
      const providers = s.providers as Record<string, ProviderConfig>;
      const customModels: CustomModel[] = s.custom_models || [];
      const opts: ModelOption[] = [];
      for (const [key, pconfig] of Object.entries(providers)) {
        const hasKey = !!s.api_keys_set[key];
        for (const m of pconfig.models || []) {
          opts.push({ providerKey: key, modelId: m.id, label: `${pconfig.name_cn} · ${m.name}`, hasKey });
        }
      }
      for (const cm of customModels) {
        opts.push({ providerKey: `custom:${cm.id}`, modelId: cm.model_id, label: `自定义 · ${cm.display_name || cm.model_id}`, hasKey: true });
      }
      setModelOptions(opts.filter(o => o.hasKey || (o.providerKey === s.provider && o.modelId === s.model)));
      selectedProviderRef.current = s.provider;
      selectedModelRef.current = s.model;
      const current = opts.find(o => o.providerKey === s.provider && o.modelId === s.model);
      setSelectedLabel(current?.label || s.model);
      const hasKey = s.provider.startsWith('custom:') || s.provider === 'custom' ? true : !!s.api_keys_set[s.provider];
      setModelReady(hasKey);
    }).catch(() => setModelReady(false));
  }, []);

  useEffect(() => { loadModels(); }, [loadModels]);

  useEffect(() => {
    refreshJobs().catch(() => {});
  }, [refreshJobs]);

  useEffect(() => {
    const onLoadJob = (e: Event) => {
      const detail = (e as CustomEvent).detail;
      if (detail?.content) {
        setManualText(detail.content);
        setInputMode('manual');
        setJdParsed(null);
      }
    };
    window.addEventListener('job-analysis-load', onLoadJob);
    return () => window.removeEventListener('job-analysis-load', onLoadJob);
  }, []);

  useEffect(() => {
    const onModelsUpdated = () => loadModels();
    window.addEventListener('models-updated', onModelsUpdated);
    return () => window.removeEventListener('models-updated', onModelsUpdated);
  }, [loadModels]);

  const handleModelSelect = async (opt: ModelOption) => {
    try {
      await agentApi.updateSettings({ provider: opt.providerKey, model: opt.modelId });
      selectedProviderRef.current = opt.providerKey;
      selectedModelRef.current = opt.modelId;
      setSelectedLabel(opt.label);
      setModelReady(opt.hasKey);
      setModelDropdownOpen(false);
    } catch { /* */ }
  };

  const handleJobSelect = (job: Job) => {
    setManualText(job.content);
    setInputMode('manual');
    setJdParsed(null);
    setJobDropdownOpen(false);
  };

  const handleFileSelect = useCallback(async (file: File) => {
    setParsing(true);
    setParseError('');
    try {
      const r = await parseJdImage(file);
      setJdParsed(r);
    } catch (e: any) {
      setParseError(e.message || '图片识别失败');
    } finally {
      setParsing(false);
    }
  }, []);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFileSelect(file);
    e.target.value = '';
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files?.[0];
    if (file) handleFileSelect(file);
  };

  const handleDragOver = (e: React.DragEvent) => { e.preventDefault(); };

  const getJdText = () => {
    if (inputMode === 'manual') return manualText;
    if (jdParsed?.raw_text) return jdParsed.raw_text;
    return '';
  };

  const hasJd = !!(jdParsed?.raw_text) || !!(manualText.trim());

  const handleAnalyze = async () => {
    const jdText = getJdText();
    if (!jdText.trim()) {
      setAnalyzeError('请先上传JD图片或手动输入JD内容');
      return;
    }
    setAnalyzing(true);
    setAnalyzeError('');
    setResult(null);
    try {
      const r = await analyzeJob({ jd_text: jdText });
      setResult(r);
    } catch (e: any) {
      setAnalyzeError(e.message || '职位分析失败');
    } finally {
      setAnalyzing(false);
    }
  };

  const toggleSection = (key: string) => {
    setExpandedSections(prev => ({ ...prev, [key]: !prev[key] }));
  };

  const handleCopySection = async (key: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedSection(key);
      setTimeout(() => setCopiedSection(null), 2000);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      setCopiedSection(key);
      setTimeout(() => setCopiedSection(null), 2000);
    }
  };

  const buildCopyText = (key: string) => {
    if (!result) return '';
    switch (key) {
      case 'skills':
        return result.skills.map(s => `[${LEVEL_STYLES[s.level].label}] ${s.name}: ${s.description}`).join('\n');
      case 'knowledge':
        return result.knowledge.map(k => `${k.topic}: ${k.description}\n学习资源: ${k.resources.join(', ')}`).join('\n\n');
      case 'plan':
        return result.plan.map(p => `【${p.phase}】${p.duration}\n目标: ${p.goals.join('; ')}\n行动: ${p.actions.join('; ')}`).join('\n\n');
      case 'questions':
        return result.interview_questions.map(q => `[${q.category}] ${q.question}\n提示: ${q.hints.join('; ')}`).join('\n\n');
      default: return '';
    }
  };

  return (
    <div className="p-5 h-full flex flex-col animate-fade-in min-h-0">
      {/* Header */}
      <div className="flex items-center justify-between mb-4 flex-wrap gap-3 shrink-0">
        <div>
          <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            AI 职位分析
          </h1>
          <p className="text-sm text-slate-500 mt-0.5">分析职位技能要求，生成学习方案与面试题</p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          {/* Job selector */}
          <div className="relative">
            <span className="text-xs text-slate-400 mr-1.5">岗位管理</span>
            <button
              onClick={() => setJobDropdownOpen(v => !v)}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs transition-colors bg-surface-800/60 text-slate-300 border border-slate-700/50 hover:bg-surface-700/60"
            >
              <Briefcase size={12} className="shrink-0" />
              <span className="max-w-[160px] truncate">选择岗位 ({jobList.length})</span>
              <ChevronDown size={12} className="shrink-0" />
            </button>
            {jobDropdownOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setJobDropdownOpen(false)} />
                <div className="absolute right-0 top-full mt-1 w-72 max-h-72 overflow-y-auto scrollbar-thin bg-surface-800 border border-slate-700/60 rounded-xl shadow-2xl z-50 animate-fade-in">
                  <div className="p-2 border-b border-slate-700/30">
                    <p className="text-xs text-slate-400 px-2 py-1">点击岗位加载 JD 到分析区</p>
                  </div>
                  <div className="p-1.5 space-y-0.5">
                    {jobList.length === 0 ? (
                      <p className="text-xs text-slate-500 px-2.5 py-2">暂无岗位，请先到「岗位管理」添加</p>
                    ) : (
                      jobList.map(job => (
                        <button
                          key={job.id}
                          onClick={() => handleJobSelect(job)}
                          className="w-full text-left px-3 py-1.5 rounded-md text-xs text-slate-300 hover:bg-surface-700/40 transition-colors truncate"
                        >
                          {job.title}
                        </button>
                      ))
                    )}
                  </div>
                </div>
              </>
            )}
          </div>
          {/* Model selector */}
          <div className="relative">
            <span className="text-xs text-slate-400 mr-1.5">模型选择</span>
            <button
              onClick={() => setModelDropdownOpen(v => !v)}
              className={clsx(
                'inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs transition-colors',
                modelReady === false
                  ? 'bg-red-500/10 text-red-400 border border-red-500/30'
                  : 'bg-surface-800/60 text-slate-300 border border-slate-700/50 hover:bg-surface-700/60',
              )}
            >
              <Cpu size={12} className="shrink-0" />
              <span className="max-w-[160px] truncate">{selectedLabel || '选择模型'}</span>
              {modelReady === false && <span className="text-[10px] shrink-0">(未配置Key)</span>}
              <ChevronDown size={12} className="shrink-0" />
            </button>
            {modelDropdownOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setModelDropdownOpen(false)} />
                <div className="absolute right-0 top-full mt-1 w-72 max-h-96 overflow-y-auto scrollbar-thin bg-surface-800 border border-slate-700/60 rounded-xl shadow-2xl z-50 animate-fade-in">
                  <div className="p-2 border-b border-slate-700/30">
                    <p className="text-xs text-slate-400 px-2 py-1">选择 AI 模型（切换后自动保存）</p>
                  </div>
                  <div className="p-1.5 space-y-0.5">
                    {Object.entries(
                      modelOptions.reduce((acc, opt) => {
                        const providerName = opt.label.split(' · ')[0];
                        if (!acc[providerName]) acc[providerName] = [];
                        acc[providerName].push(opt);
                        return acc;
                      }, {} as Record<string, ModelOption[]>)
                    ).map(([providerName, opts]) => (
                      <div key={providerName}>
                        <div className="px-2 py-1.5 text-[11px] font-medium text-slate-500 uppercase tracking-wider">{providerName}</div>
                        {opts.map(opt => {
                          const isActive = selectedProviderRef.current === opt.providerKey && selectedModelRef.current === opt.modelId;
                          return (
                            <button
                              key={`${opt.providerKey}-${opt.modelId}`}
                              onClick={() => { handleModelSelect(opt); setModelDropdownOpen(false); }}
                              className={clsx(
                                'w-full text-left px-3 py-1.5 rounded-md text-xs flex items-center gap-1.5 transition-colors',
                                isActive ? 'bg-accent-blue/15 text-accent-blue' : 'text-slate-300 hover:bg-surface-700/40',
                              )}
                            >
                              {isActive && <Check size={11} className="shrink-0" />}
                              <span className={clsx('truncate', isActive ? '' : 'ml-3.5')}>{opt.label.split(' · ').slice(1).join(' · ') || opt.label}</span>
                            </button>
                          );
                        })}
                      </div>
                    ))}
                    {modelOptions.length === 0 && (
                      <p className="text-xs text-slate-500 px-2.5 py-2">暂无可用模型，请先配置API Key</p>
                    )}
                  </div>
                  <div className="p-2 border-t border-slate-700/30">
                    <button
                      onClick={() => { setModelDropdownOpen(false); window.dispatchEvent(new CustomEvent('navigate-model-management')); }}
                      className="w-full flex items-center gap-1.5 px-2 py-1.5 text-xs text-slate-400 hover:text-slate-200 hover:bg-surface-700/40 rounded-md transition-colors"
                    >
                      <Settings size={11} />
                      前往模型管理（配置Key、添加模型）
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </div>

      {/* Main layout */}
      <div className="flex-1 flex gap-4 min-h-0 lg:flex-row flex-col">
        {/* Left: Input */}
        <div className="flex-1 min-w-0 flex flex-col lg:max-w-[calc(50%-20px)]">
          <div className="card p-4 flex flex-col flex-1">
            <div className="mb-3">
              <h2 className="text-sm font-semibold text-slate-200">输入岗位JD</h2>
              <p className="text-xs text-slate-500 mt-0.5">上传图片或手动输入岗位JD详情</p>
            </div>

            <div className="flex gap-1 mb-3 p-0.5 bg-surface-900/60 rounded-lg w-fit">
              <button
                onClick={() => setInputMode('upload')}
                className={clsx(
                  'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all',
                  inputMode === 'upload' ? 'bg-accent-blue/20 text-accent-blue shadow-sm' : 'text-slate-400 hover:text-slate-300',
                )}
              >
                <ImageIcon size={13} /> 上传图片
              </button>
              <button
                onClick={() => setInputMode('manual')}
                className={clsx(
                  'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all',
                  inputMode === 'manual' ? 'bg-accent-blue/20 text-accent-blue shadow-sm' : 'text-slate-400 hover:text-slate-300',
                )}
              >
                <FileText size={13} /> 手动输入
              </button>
            </div>

            {inputMode === 'upload' && (
              <>
                <div
                  onClick={() => fileInputRef.current?.click()}
                  onDrop={handleDrop}
                  onDragOver={handleDragOver}
                  className={clsx(
                    'border-2 border-dashed rounded-xl flex flex-col items-center justify-center cursor-pointer hover:border-accent-blue/40 hover:bg-accent-blue/5 transition-all group',
                    parsing ? 'border-accent-blue/30 bg-accent-blue/5 pointer-events-none' : 'border-slate-600/60',
                    jdParsed ? 'p-4' : 'p-8',
                  )}
                >
                  {parsing ? (
                    <>
                      <Loader2 size={24} className="animate-spin text-accent-blue mb-2" />
                      <p className="text-sm text-slate-300">正在识别JD图片...</p>
                    </>
                  ) : jdParsed ? (
                    <>
                      <div className="w-10 h-10 rounded-xl bg-surface-800/60 flex items-center justify-center mb-2 group-hover:bg-accent-blue/10 transition-colors">
                        <ImagePlus size={18} className="text-slate-500 group-hover:text-accent-blue transition-colors" />
                      </div>
                      <p className="text-xs text-slate-400">点击重新上传岗位JD图片</p>
                      <p className="text-[10px] text-slate-600 mt-0.5">支持 JPG、PNG 格式</p>
                    </>
                  ) : (
                    <>
                      <div className="w-14 h-14 rounded-2xl bg-surface-800/60 flex items-center justify-center mb-3 group-hover:bg-accent-blue/10 transition-colors">
                        <ImagePlus size={24} className="text-slate-500 group-hover:text-accent-blue transition-colors" />
                      </div>
                      <p className="text-sm text-slate-300 mb-1">点击上传岗位JD图片</p>
                      <p className="text-xs text-slate-600">支持 JPG、PNG 格式</p>
                    </>
                  )}
                </div>
                {parseError && <p className="text-xs text-red-400 mt-2">{parseError}</p>}
                <input ref={fileInputRef} type="file" accept=".jpg,.jpeg,.png" className="hidden" onChange={handleFileChange} />
              </>
            )}

            {inputMode === 'manual' && (
              <textarea
                value={manualText}
                onChange={e => setManualText(e.target.value)}
                placeholder="请粘贴或输入岗位JD内容..."
                className="w-full flex-1 min-h-[160px] px-3 py-2.5 rounded-xl bg-surface-900/60 border border-slate-700/50 text-slate-200 text-sm resize-none focus:border-accent-blue/50 focus:outline-none focus:ring-1 focus:ring-accent-blue/30 placeholder:text-slate-600 scrollbar-thin"
              />
            )}

            {jdParsed && inputMode === 'upload' && (
              <div className="mt-3 rounded-xl bg-surface-900/40 border border-slate-700/30 overflow-hidden">
                <div className="px-3 py-2 flex items-center justify-between border-b border-slate-700/30">
                  <span className="text-xs font-medium text-slate-300">识别结果</span>
                  <div className="flex items-center gap-1.5">
                    <Check size={13} className="text-green-400" />
                    <span className="text-xs text-green-400">识别完成</span>
                  </div>
                </div>
                <div className="p-3 max-h-40 overflow-y-auto scrollbar-thin space-y-2 text-sm">
                  {jdParsed.title && (
                    <div>
                      <span className="text-xs font-semibold text-accent-blue">岗位</span>
                      <p className="text-slate-200 mt-0.5">{jdParsed.title}</p>
                    </div>
                  )}
                  {jdParsed.responsibilities.length > 0 && (
                    <div>
                      <span className="text-xs font-semibold text-green-400">职责</span>
                      <ul className="mt-0.5 space-y-0.5">
                        {jdParsed.responsibilities.map((r, i) => (
                          <li key={i} className="text-slate-300 text-xs flex gap-1.5">
                            <span className="text-slate-600 mt-0.5 shrink-0">•</span>
                            <span>{r}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {jdParsed.requirements.length > 0 && (
                    <div>
                      <span className="text-xs font-semibold text-purple-400">要求</span>
                      <ul className="mt-0.5 space-y-0.5">
                        {jdParsed.requirements.map((r, i) => (
                          <li key={i} className="text-slate-300 text-xs flex gap-1.5">
                            <span className="text-slate-600 mt-0.5 shrink-0">•</span>
                            <span>{r}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </div>
            )}

            <button
              onClick={handleAnalyze}
              disabled={analyzing || !hasJd}
              className={clsx(
                'w-full mt-3 py-3 rounded-xl font-medium text-sm flex items-center justify-center gap-2 transition-all shrink-0',
                analyzing || !hasJd
                  ? 'bg-surface-700/40 text-slate-500 cursor-not-allowed'
                  : 'bg-gradient-to-r from-purple-600 to-purple-500 text-white hover:from-purple-500 hover:to-purple-400 shadow-lg shadow-purple-500/20',
              )}
            >
              {analyzing ? (
                <><Loader2 size={16} className="animate-spin" /> AI正在分析职位...</>
              ) : (
                <><Sparkles size={16} /> 开始分析</>
              )}
            </button>
            {analyzeError && <p className="text-xs text-red-400 mt-2">{analyzeError}</p>}
          </div>
        </div>

        {/* Arrow */}
        <div className="hidden lg:flex items-center self-center shrink-0">
          <div className="w-10 h-10 rounded-full bg-surface-800/60 border border-slate-700/30 flex items-center justify-center">
            <ArrowRight size={18} className="text-accent-purple" />
          </div>
        </div>
        <div className="flex lg:hidden items-center justify-center shrink-0 py-1">
          <div className="w-8 h-8 rounded-full bg-surface-800/60 border border-slate-700/30 flex items-center justify-center rotate-90">
            <ArrowRight size={14} className="text-accent-purple" />
          </div>
        </div>

        {/* Right: Output */}
        <div className="flex-1 min-w-0 flex flex-col lg:max-w-[calc(50%-20px)] min-h-0">
          <div className="card p-4 flex flex-col flex-1 min-h-0 overflow-hidden">
            <div className="mb-3 flex items-center gap-2">
              <Briefcase size={15} className="text-accent-purple" />
              <div>
                <h2 className="text-sm font-semibold text-slate-200">职位分析结果</h2>
                <p className="text-xs text-slate-500 mt-0.5">技能要求 · 学习方案 · 面试问题</p>
              </div>
            </div>

            {result ? (
              <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin space-y-3 pr-0.5">
                {/* Summary */}
                <div className="rounded-xl bg-gradient-to-r from-purple-500/10 to-blue-500/10 border border-purple-500/20 p-3">
                  <div className="flex items-center gap-2 mb-1.5">
                    <Target size={14} className="text-accent-purple" />
                    <span className="text-sm font-semibold text-slate-200">{result.job_title}</span>
                  </div>
                  <p className="text-xs text-slate-400 leading-relaxed">{result.summary}</p>
                </div>

                {/* Skills */}
                <div className="rounded-xl bg-surface-900/40 border border-slate-700/30 overflow-hidden">
                  <button
                    onClick={() => toggleSection('skills')}
                    className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-surface-700/30 transition-colors"
                  >
                    <span className="flex items-center gap-2 text-sm font-semibold text-slate-200">
                      <div className="w-6 h-6 rounded-md flex items-center justify-center" style={{ backgroundColor: `${SECTION_COLORS[0]}20`, color: SECTION_COLORS[0] }}>
                        <BookOpen size={13} />
                      </div>
                      技能要求
                      <span className="text-[10px] text-slate-500 font-normal">{result.skills.length} 项</span>
                    </span>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={e => { e.stopPropagation(); handleCopySection('skills', buildCopyText('skills')); }}
                        className="p-1 rounded hover:bg-surface-700/40 text-slate-500 hover:text-slate-300"
                      >
                        {copiedSection === 'skills' ? <Check size={12} className="text-green-400" /> : <Copy size={12} />}
                      </button>
                      <ChevronDown size={14} className={clsx('text-slate-500 transition-transform', expandedSections.skills && 'rotate-180')} />
                    </div>
                  </button>
                  {expandedSections.skills && (
                    <div className="px-3 pb-3 space-y-2">
                      {result.skills.map((s, i) => {
                        const lv = LEVEL_STYLES[s.level] || LEVEL_STYLES.required;
                        return (
                          <div key={i} className="flex items-start gap-2 px-2.5 py-2 rounded-lg bg-surface-900/50">
                            <span className={clsx('text-[10px] px-1.5 py-0.5 rounded font-medium shrink-0 mt-0.5', lv.bg, lv.text)}>
                              {lv.label}
                            </span>
                            <div className="flex-1 min-w-0">
                              <p className="text-xs font-medium text-slate-200">{s.name}</p>
                              <p className="text-[11px] text-slate-400 mt-0.5 leading-relaxed">{s.description}</p>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>

                {/* Knowledge */}
                <div className="rounded-xl bg-surface-900/40 border border-slate-700/30 overflow-hidden">
                  <button
                    onClick={() => toggleSection('knowledge')}
                    className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-surface-700/30 transition-colors"
                  >
                    <span className="flex items-center gap-2 text-sm font-semibold text-slate-200">
                      <div className="w-6 h-6 rounded-md flex items-center justify-center" style={{ backgroundColor: `${SECTION_COLORS[1]}20`, color: SECTION_COLORS[1] }}>
                        <BookOpen size={13} />
                      </div>
                      知识点学习
                      <span className="text-[10px] text-slate-500 font-normal">{result.knowledge.length} 项</span>
                    </span>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={e => { e.stopPropagation(); handleCopySection('knowledge', buildCopyText('knowledge')); }}
                        className="p-1 rounded hover:bg-surface-700/40 text-slate-500 hover:text-slate-300"
                      >
                        {copiedSection === 'knowledge' ? <Check size={12} className="text-green-400" /> : <Copy size={12} />}
                      </button>
                      <ChevronDown size={14} className={clsx('text-slate-500 transition-transform', expandedSections.knowledge && 'rotate-180')} />
                    </div>
                  </button>
                  {expandedSections.knowledge && (
                    <div className="px-3 pb-3 space-y-2">
                      {result.knowledge.map((k, i) => (
                        <div key={i} className="px-2.5 py-2 rounded-lg bg-surface-900/50">
                          <p className="text-xs font-medium text-slate-200">{k.topic}</p>
                          <p className="text-[11px] text-slate-400 mt-0.5 leading-relaxed">{k.description}</p>
                          {k.resources.length > 0 && (
                            <div className="flex flex-wrap gap-1 mt-1.5">
                              {k.resources.map((r, ri) => (
                                <span key={ri} className="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-400">{r}</span>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Plan */}
                <div className="rounded-xl bg-surface-900/40 border border-slate-700/30 overflow-hidden">
                  <button
                    onClick={() => toggleSection('plan')}
                    className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-surface-700/30 transition-colors"
                  >
                    <span className="flex items-center gap-2 text-sm font-semibold text-slate-200">
                      <div className="w-6 h-6 rounded-md flex items-center justify-center" style={{ backgroundColor: `${SECTION_COLORS[2]}20`, color: SECTION_COLORS[2] }}>
                        <ListChecks size={13} />
                      </div>
                      学习方案
                      <span className="text-[10px] text-slate-500 font-normal">{result.plan.length} 阶段</span>
                    </span>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={e => { e.stopPropagation(); handleCopySection('plan', buildCopyText('plan')); }}
                        className="p-1 rounded hover:bg-surface-700/40 text-slate-500 hover:text-slate-300"
                      >
                        {copiedSection === 'plan' ? <Check size={12} className="text-green-400" /> : <Copy size={12} />}
                      </button>
                      <ChevronDown size={14} className={clsx('text-slate-500 transition-transform', expandedSections.plan && 'rotate-180')} />
                    </div>
                  </button>
                  {expandedSections.plan && (
                    <div className="px-3 pb-3 space-y-2">
                      {result.plan.map((p, i) => (
                        <div key={i} className="relative pl-6 pb-2">
                          {i < result.plan.length - 1 && <div className="absolute left-[7px] top-5 bottom-0 w-px bg-slate-700/50" />}
                          <div className="absolute left-0 top-1 w-3.5 h-3.5 rounded-full border-2 border-orange-400/60 bg-surface-900" />
                          <div className="rounded-lg bg-surface-900/50 p-2.5">
                            <div className="flex items-center gap-2 mb-1">
                              <span className="text-xs font-semibold text-slate-200">{p.phase}</span>
                              <span className="text-[10px] px-1.5 py-0.5 rounded bg-orange-500/15 text-orange-400">{p.duration}</span>
                            </div>
                            <div className="space-y-1 mb-1.5">
                              <p className="text-[10px] text-slate-500 font-medium">目标</p>
                              {p.goals.map((g, gi) => (
                                <p key={gi} className="text-[11px] text-slate-300 flex gap-1.5">
                                  <TrendingUp size={10} className="text-green-400 shrink-0 mt-0.5" />
                                  <span>{g}</span>
                                </p>
                              ))}
                            </div>
                            <div className="space-y-1">
                              <p className="text-[10px] text-slate-500 font-medium">行动</p>
                              {p.actions.map((a, ai) => (
                                <p key={ai} className="text-[11px] text-slate-400 flex gap-1.5">
                                  <span className="text-slate-600 mt-0.5 shrink-0">•</span>
                                  <span>{a}</span>
                                </p>
                              ))}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* Interview Questions */}
                <div className="rounded-xl bg-surface-900/40 border border-slate-700/30 overflow-hidden">
                  <button
                    onClick={() => toggleSection('questions')}
                    className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-surface-700/30 transition-colors"
                  >
                    <span className="flex items-center gap-2 text-sm font-semibold text-slate-200">
                      <div className="w-6 h-6 rounded-md flex items-center justify-center" style={{ backgroundColor: `${SECTION_COLORS[3]}20`, color: SECTION_COLORS[3] }}>
                        <HelpCircle size={13} />
                      </div>
                      面试问题
                      <span className="text-[10px] text-slate-500 font-normal">{result.interview_questions.length} 题</span>
                    </span>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={e => { e.stopPropagation(); handleCopySection('questions', buildCopyText('questions')); }}
                        className="p-1 rounded hover:bg-surface-700/40 text-slate-500 hover:text-slate-300"
                      >
                        {copiedSection === 'questions' ? <Check size={12} className="text-green-400" /> : <Copy size={12} />}
                      </button>
                      <ChevronDown size={14} className={clsx('text-slate-500 transition-transform', expandedSections.questions && 'rotate-180')} />
                    </div>
                  </button>
                  {expandedSections.questions && (
                    <div className="px-3 pb-3 space-y-2">
                      {result.interview_questions.map((q, i) => (
                        <div key={i} className="px-2.5 py-2 rounded-lg bg-surface-900/50">
                          <div className="flex items-center gap-2 mb-1">
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-green-500/15 text-green-400 font-medium">{q.category}</span>
                          </div>
                          <p className="text-xs text-slate-200 leading-relaxed">{q.question}</p>
                          {q.hints.length > 0 && (
                            <div className="mt-1.5 space-y-0.5">
                              <p className="text-[10px] text-slate-500">答题提示</p>
                              {q.hints.map((h, hi) => (
                                <p key={hi} className="text-[11px] text-slate-400 flex gap-1.5">
                                  <span className="text-slate-600 shrink-0">→</span>
                                  <span>{h}</span>
                                </p>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ) : analyzing ? (
              <div className="flex-1 flex items-center justify-center">
                <div className="w-full max-w-sm space-y-3 animate-pulse">
                  <div className="h-16 bg-surface-700/60 rounded-xl" />
                  <div className="h-24 bg-surface-700/60 rounded-xl" />
                  <div className="h-24 bg-surface-700/60 rounded-xl" />
                  <div className="h-20 bg-surface-700/60 rounded-xl" />
                </div>
              </div>
            ) : (
              <div className="flex-1 flex items-center justify-center">
                <div className="rounded-xl bg-surface-900/20 border border-dashed border-slate-700/30 p-8 flex flex-col items-center justify-center text-center">
                  <div className="w-14 h-14 rounded-2xl bg-surface-800/40 flex items-center justify-center mb-3">
                    <Briefcase size={22} className="text-slate-600" />
                  </div>
                  <p className="text-sm text-slate-500">分析结果将在此显示</p>
                  <p className="text-xs text-slate-600 mt-1">上传JD并点击「开始分析」</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
