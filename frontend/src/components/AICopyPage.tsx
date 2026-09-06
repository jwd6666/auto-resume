import { useState, useRef, useCallback, useEffect } from 'react';
import {
  ImagePlus, Sparkles, Copy, Check, Loader2,
  ChevronDown, ArrowRight, Briefcase, Target, TrendingUp, Star,
  FileText, ImageIcon, Cpu, Zap, Settings, User,
} from 'lucide-react';
import clsx from 'clsx';
import { agentApi, type SettingsInfo, type CustomModel } from '../api/agentApi';
import { PersonalInfoModal, loadPersonalInfo, buildPersonalInfoText } from './PersonalInfoModal';

const isDev = location.port === '5173';
const API_BASE = isDev ? '' : ((window as any).autoresume?.apiBase || 'http://127.0.0.1:8765');
const AGENT = `${API_BASE}/agent`;

interface JdParseResult {
  title: string;
  company: string | null;
  responsibilities: string[];
  requirements: string[];
  raw_text: string;
}

interface GreetingItem {
  index: number;
  text: string;
  style_label: string;
}

interface StyleOption {
  id: string;
  name: string;
  description: string;
}

const DEFAULT_STYLES: StyleOption[] = [
  { id: 'experience-match', name: '经验匹配型', description: '直接亮年限+核心技能，对标JD要求' },
  { id: 'project-result', name: '项目成果型', description: '用具体项目/数据说话，突出战绩' },
  { id: 'enthusiasm', name: '热情态度型', description: '表达对公司/岗位的强烈兴趣和认同' },
  { id: 'concise-direct', name: '简洁直接型', description: '一句话说清"我是谁+能做什么"' },
  { id: 'skill-keyword', name: '技能关键词型', description: '堆砌JD技术栈关键词，过筛选' },
  { id: 'learning-potential', name: '学习潜力型', description: '强调学习能力和适应速度' },
];

const NUMBER_COLORS = ['#0ea5e9', '#22c55e', '#8b5cf6', '#f97316', '#ec4899', '#14b8a6', '#eab308', '#6366f1'];

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

async function generateGreetings(params: {
  jd_text: string;
  style: string;
  count: number;
  existing_count: number;
  resume?: string;
  expect_jd?: string;
}): Promise<{ greetings: GreetingItem[]; suggestions: { icon: string; title: string; description: string }[] }> {
  const r = await fetch(`${AGENT}/greeting-generator/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!r.ok) {
    let msg = '话术生成失败';
    try { msg = await r.text(); } catch { /* */ }
    throw new Error(msg);
  }
  return r.json();
}



export function AICopyPage() {
  const [inputMode, setInputMode] = useState<'upload' | 'manual'>('upload');
  const [manualText, setManualText] = useState('');
  const [jdParsed, setJdParsed] = useState<JdParseResult | null>(null);
  const [parsing, setParsing] = useState(false);
  const [parseError, setParseError] = useState('');

  const [greetings, setGreetings] = useState<GreetingItem[]>([]);
  const [suggestions, setSuggestions] = useState<{ icon: string; title: string; description: string }[]>([]);
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState('');
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  const [selectedStyle, setSelectedStyle] = useState('experience-match');
  const [styleDropdownOpen, setStyleDropdownOpen] = useState(false);
  const [personalInfoOpen, setPersonalInfoOpen] = useState(false);

  const [modelOptions, setModelOptions] = useState<ModelOption[]>([]);
  const selectedProviderRef = useRef('');
  const selectedModelRef = useRef('');
  const [selectedLabel, setSelectedLabel] = useState('');
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false);
  const [modelReady, setModelReady] = useState<boolean | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadModels = useCallback(() => {
    agentApi.getSettings().then(s => {
      const providers = s.providers as Record<string, ProviderConfig>;
      const customModels: CustomModel[] = s.custom_models || [];
      const opts: ModelOption[] = [];
      for (const [key, pconfig] of Object.entries(providers)) {
        const hasKey = !!s.api_keys_set[key];
        for (const m of pconfig.models || []) {
          opts.push({
            providerKey: key,
            modelId: m.id,
            label: `${pconfig.name_cn} · ${m.name}`,
            hasKey,
          });
        }
      }
      for (const cm of customModels) {
        opts.push({
          providerKey: `custom:${cm.id}`,
          modelId: cm.model_id,
          label: `自定义 · ${cm.display_name || cm.model_id}`,
          hasKey: true,
        });
      }
      setModelOptions(opts.filter(o => o.hasKey || (o.providerKey === s.provider && o.modelId === s.model)));
      selectedProviderRef.current = s.provider;
      selectedModelRef.current = s.model;
      const current = opts.find(o => o.providerKey === s.provider && o.modelId === s.model);
      setSelectedLabel(current?.label || s.model);
      const hasKey = s.provider.startsWith('custom:') || s.provider === 'custom'
        ? true
        : !!s.api_keys_set[s.provider];
      setModelReady(hasKey);
    }).catch(() => setModelReady(false));
  }, []);

  useEffect(() => { loadModels(); }, [loadModels]);

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

  const handleFileSelect = useCallback(async (file: File) => {
    setParsing(true);
    setParseError('');
    try {
      const result = await parseJdImage(file);
      setJdParsed(result);
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

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const getJdText = () => {
    if (inputMode === 'manual') return manualText;
    if (jdParsed?.raw_text) return jdParsed.raw_text;
    return '';
  };

  const hasJd = !!(jdParsed?.raw_text) || !!(manualText.trim());



  const handleGenerate = async () => {
    const jdText = getJdText();
    if (!jdText.trim()) {
      setGenerateError('请先上传JD图片或手动输入JD内容');
      return;
    }
    setGenerating(true);
    setGenerateError('');
    const resumeText = buildPersonalInfoText();
    try {
      const result = await generateGreetings({
        jd_text: jdText,
        style: selectedStyle,
        count: 1,
        existing_count: greetings.length,
        resume: resumeText || undefined,
      });
      setGreetings(prev => [...prev, ...result.greetings.map(g => ({ ...g, index: prev.length }))]);
      if (result.suggestions?.length) {
        setSuggestions(result.suggestions);
      }
    } catch (e: any) {
      setGenerateError(e.message || '话术生成失败');
    } finally {
      setGenerating(false);
    }
  };

  const handleCopy = async (text: string, index: number) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedIndex(index);
      setTimeout(() => setCopiedIndex(null), 2000);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
      setCopiedIndex(index);
      setTimeout(() => setCopiedIndex(null), 2000);
    }
  };

  const currentStyle = DEFAULT_STYLES.find(s => s.id === selectedStyle) || DEFAULT_STYLES[0];

  return (
    <div className="p-5 h-full flex flex-col animate-fade-in min-h-0">
      {/* Header */}
      <div className="flex items-center justify-between mb-4 flex-wrap gap-3 shrink-0">
        <div>
          <h1 className="text-xl font-bold text-slate-100 flex items-center gap-2">
            AI话术生成
          </h1>
          <p className="text-sm text-slate-500 mt-0.5">使用AI生成个性化打招呼话术</p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          {/* Personal info button */}
          <button
            onClick={() => setPersonalInfoOpen(true)}
            className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-surface-800/60 border border-slate-700/50 text-xs text-slate-300 hover:bg-surface-700/60 transition-colors"
          >
            <User size={12} />
            个人信息
          </button>
          {/* Style dropdown */}
          <div className="relative">
            <span className="text-xs text-slate-400 mr-1.5">话术风格</span>
            <button
              onClick={() => setStyleDropdownOpen(v => !v)}
              className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg bg-surface-800/60 border border-slate-700/50 text-xs text-slate-300 hover:bg-surface-700/60 transition-colors"
            >
              <span>{currentStyle.name}</span>
              <ChevronDown size={12} className={clsx('text-slate-500 transition-transform', styleDropdownOpen && 'rotate-180')} />
            </button>
            {styleDropdownOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setStyleDropdownOpen(false)} />
                <div className="absolute right-0 top-full mt-1 w-56 bg-surface-800 border border-slate-700/60 rounded-xl shadow-2xl z-50 py-1.5 animate-fade-in">
                  {DEFAULT_STYLES.map(s => (
                    <button
                      key={s.id}
                      onClick={() => { setSelectedStyle(s.id); setStyleDropdownOpen(false); }}
                      className={clsx(
                        'w-full text-left px-3 py-2 text-xs flex items-center gap-2 transition-colors',
                        selectedStyle === s.id
                          ? 'text-accent-blue bg-accent-blue/10'
                          : 'text-slate-300 hover:bg-surface-700/50',
                      )}
                    >
                      {selectedStyle === s.id && <Check size={11} className="shrink-0" />}
                      <div className={clsx('flex-1', selectedStyle !== s.id && 'ml-3.5')}>
                        <p className="font-medium">{s.name}</p>
                        <p className="text-[10px] text-slate-500 mt-0.5">{s.description}</p>
                      </div>
                    </button>
                  ))}
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
                        <div className="px-2 py-1.5 text-[11px] font-medium text-slate-500 uppercase tracking-wider">
                          {providerName}
                        </div>
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

      {/* Main two-column layout */}
      <div className="flex-1 flex gap-4 min-h-0 lg:flex-row flex-col">
        {/* Left: Input area */}
        <div className="flex-1 min-w-0 flex flex-col lg:max-w-[calc(50%-20px)]">
          <div className="card p-4 flex flex-col flex-1">
            <div className="mb-3">
              <h2 className="text-sm font-semibold text-slate-200">输入岗位JD</h2>
              <p className="text-xs text-slate-500 mt-0.5">上传图片或手动输入岗位JD详情</p>
            </div>

            {/* Tab switch */}
            <div className="flex gap-1 mb-3 p-0.5 bg-surface-900/60 rounded-lg w-fit">
              <button
                onClick={() => setInputMode('upload')}
                className={clsx(
                  'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all',
                  inputMode === 'upload'
                    ? 'bg-accent-blue/20 text-accent-blue shadow-sm'
                    : 'text-slate-400 hover:text-slate-300',
                )}
              >
                <ImageIcon size={13} />
                上传图片
              </button>
              <button
                onClick={() => setInputMode('manual')}
                className={clsx(
                  'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all',
                  inputMode === 'manual'
                    ? 'bg-accent-blue/20 text-accent-blue shadow-sm'
                    : 'text-slate-400 hover:text-slate-300',
                )}
              >
                <FileText size={13} />
                手动输入
              </button>
            </div>

            {/* Upload area - always visible in upload mode */}
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
                      <p className="text-[10px] text-slate-600 mt-0.5">支持 JPG、PNG 格式，大小不超过 10MB</p>
                    </>
                  ) : (
                    <>
                      <div className="w-14 h-14 rounded-2xl bg-surface-800/60 flex items-center justify-center mb-3 group-hover:bg-accent-blue/10 transition-colors">
                        <ImagePlus size={24} className="text-slate-500 group-hover:text-accent-blue transition-colors" />
                      </div>
                      <p className="text-sm text-slate-300 mb-1">点击上传岗位JD图片</p>
                      <p className="text-xs text-slate-600">支持 JPG、PNG 格式，大小不超过 10MB</p>
                    </>
                  )}
                </div>
                {parseError && (
                  <p className="text-xs text-red-400 mt-2">{parseError}</p>
                )}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".jpg,.jpeg,.png"
                  className="hidden"
                  onChange={handleFileChange}
                />
              </>
            )}

            {/* Manual input */}
            {inputMode === 'manual' && (
              <textarea
                value={manualText}
                onChange={e => setManualText(e.target.value)}
                placeholder="请粘贴或输入岗位JD内容..."
                className="w-full flex-1 min-h-[160px] px-3 py-2.5 rounded-xl bg-surface-900/60 border border-slate-700/50 text-slate-200 text-sm resize-none focus:border-accent-blue/50 focus:outline-none focus:ring-1 focus:ring-accent-blue/30 placeholder:text-slate-600 scrollbar-thin"
              />
            )}

            {/* Parsed result */}
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

            {/* Generate button */}
            <button
              onClick={handleGenerate}
              disabled={generating || !hasJd}
              className={clsx(
                'w-full mt-3 py-3 rounded-xl font-medium text-sm flex items-center justify-center gap-2 transition-all shrink-0',
                generating || !hasJd
                  ? 'bg-surface-700/40 text-slate-500 cursor-not-allowed'
                  : 'bg-gradient-to-r from-blue-600 to-blue-500 text-white hover:from-blue-500 hover:to-blue-400 shadow-lg shadow-blue-500/20',
              )}
            >
              {generating ? (
                <>
                  <Loader2 size={16} className="animate-spin" />
                  AI正在生成话术...
                </>
              ) : (
                <>
                  <Sparkles size={16} />
                  生成话术
                </>
              )}
            </button>
            {generateError && (
              <p className="text-xs text-red-400 mt-2">{generateError}</p>
            )}
          </div>
        </div>

        {/* Arrow connector */}
        <div className="hidden lg:flex items-center self-center shrink-0">
          <div className="w-10 h-10 rounded-full bg-surface-800/60 border border-slate-700/30 flex items-center justify-center">
            <ArrowRight size={18} className="text-accent-blue" />
          </div>
        </div>
        <div className="flex lg:hidden items-center justify-center shrink-0 py-1">
          <div className="w-8 h-8 rounded-full bg-surface-800/60 border border-slate-700/30 flex items-center justify-center rotate-90">
            <ArrowRight size={14} className="text-accent-blue" />
          </div>
        </div>

        {/* Right: Output area */}
        <div className="flex-1 min-w-0 flex flex-col lg:max-w-[calc(50%-20px)] min-h-0">
          <div className="card p-4 flex flex-col flex-1 min-h-0 overflow-hidden">
            <div className="mb-3 flex items-center gap-2">
              <Star size={15} className="text-accent-purple" />
              <div>
                <h2 className="text-sm font-semibold text-slate-200">AI生成打招呼话术</h2>
                <p className="text-xs text-slate-500 mt-0.5">根据岗位JD生成个性化打招呼话术</p>
              </div>
            </div>

            {/* Greeting list */}
            <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin space-y-2.5 pr-0.5">
              {greetings.length > 0 ? (
                <>
                  {greetings.map((g, i) => (
                    <div
                      key={i}
                      className="rounded-xl bg-surface-900/40 border border-slate-700/30 p-3 flex gap-3 items-start group hover:border-slate-600/40 transition-all animate-slide-up"
                    >
                      <div
                        className="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold text-white shrink-0"
                        style={{ backgroundColor: NUMBER_COLORS[i % NUMBER_COLORS.length] }}
                      >
                        {String(i + 1).padStart(2, '0')}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5 mb-1">
                          <span
                            className="text-[10px] px-1.5 py-0.5 rounded font-medium"
                            style={{
                              backgroundColor: `${NUMBER_COLORS[i % NUMBER_COLORS.length]}20`,
                              color: NUMBER_COLORS[i % NUMBER_COLORS.length],
                            }}
                          >
                            {g.style_label}
                          </span>
                        </div>
                        <p className="text-sm text-slate-200 leading-relaxed">{g.text}</p>
                      </div>
                      <button
                        onClick={() => handleCopy(g.text, i)}
                        className={clsx(
                          'shrink-0 p-1.5 rounded-lg transition-all text-xs flex items-center gap-1',
                          copiedIndex === i
                            ? 'bg-green-500/15 text-green-400'
                            : 'bg-surface-800/40 text-slate-500 hover:text-slate-300 hover:bg-surface-700/50',
                        )}
                      >
                        {copiedIndex === i ? <Check size={13} /> : <Copy size={13} />}
                        {copiedIndex === i ? '已复制' : '复制'}
                      </button>
                    </div>
                  ))}
                  {generating && (
                    <div className="rounded-xl bg-surface-900/40 border border-slate-700/30 p-3 flex gap-3 items-start animate-pulse">
                      <div className="w-8 h-8 rounded-full bg-surface-700/60 shrink-0" />
                      <div className="flex-1 space-y-2">
                        <div className="h-3 bg-surface-700/60 rounded w-16" />
                        <div className="h-3 bg-surface-700/60 rounded w-full" />
                        <div className="h-3 bg-surface-700/60 rounded w-3/4" />
                      </div>
                    </div>
                  )}
                </>
              ) : generating ? (
                <div className="w-full">
                  <div className="rounded-xl bg-surface-900/40 border border-slate-700/30 p-3 flex gap-3 items-start animate-pulse">
                    <div className="w-8 h-8 rounded-full bg-surface-700/60 shrink-0" />
                    <div className="flex-1 space-y-2">
                      <div className="h-3 bg-surface-700/60 rounded w-16" />
                      <div className="h-3 bg-surface-700/60 rounded w-full" />
                      <div className="h-3 bg-surface-700/60 rounded w-3/4" />
                    </div>
                  </div>
                </div>
              ) : (
                <div className="rounded-xl bg-surface-900/20 border border-dashed border-slate-700/30 p-8 flex flex-col items-center justify-center text-center">
                  <div className="w-14 h-14 rounded-2xl bg-surface-800/40 flex items-center justify-center mb-3">
                    <Sparkles size={22} className="text-slate-600" />
                  </div>
                  <p className="text-sm text-slate-500">话术将在此显示</p>
                  <p className="text-xs text-slate-600 mt-1">上传JD并点击「生成话术」开始</p>
                </div>
              )}
            </div>

            {/* Suggestions */}
            {suggestions.length > 0 && (
              <div className="mt-4 pt-3 border-t border-slate-700/30 shrink-0">
                <p className="text-xs font-medium text-slate-400 mb-2">话术优化建议</p>
                <div className="grid grid-cols-3 gap-2">
                  {suggestions.map((s, i) => {
                    const icons = [<Briefcase key="b" size={14} />, <Target key="t" size={14} />, <TrendingUp key="tr" size={14} />];
                    const colors = ['#0ea5e9', '#22c55e', '#f97316'];
                    return (
                      <div key={i} className="rounded-lg bg-surface-900/30 border border-slate-700/20 p-2.5 text-center">
                        <div
                          className="w-7 h-7 rounded-lg flex items-center justify-center mx-auto mb-1.5"
                          style={{ backgroundColor: `${colors[i]}15`, color: colors[i] }}
                        >
                          {icons[i]}
                        </div>
                        <p className="text-xs font-medium text-slate-300">{s.title}</p>
                        <p className="text-[10px] text-slate-500 mt-0.5 leading-snug">{s.description}</p>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <PersonalInfoModal open={personalInfoOpen} onClose={() => setPersonalInfoOpen(false)} />
    </div>
  );
}
