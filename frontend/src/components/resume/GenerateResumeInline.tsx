import { useState } from 'react';
import { Sparkles, Loader2, AlertTriangle, X, Palette, ChevronRight } from 'lucide-react';
import { ACCENTS } from './editor/render';
import { agentApi, type Job, type Resume } from '../../api/agentApi';

interface Props {
  job: Job | null;
  onGenerated: (resume: Resume) => void;
  visible: boolean;
  onClose: () => void;
}

const PLACEHOLDER = `姓名：张三
求职意向：Python后端开发工程师
电话：138xxxx1234
邮箱：zhangsan@email.com
城市：北京

个人简介：
5年Python后端开发经验，擅长高并发系统设计与微服务架构。

工作经历：
XX科技有限公司 | Python高级工程师 | 2021.06 - 至今
• 主导用户中心微服务重构，QPS从500提升至5000
• 设计并实现分布式任务调度系统，日均处理200万+任务

教育经历：
XX大学 | 计算机科学与技术 | 本科 | 2015.09 - 2019.06

核心技能：
Python / FastAPI / Django / Redis / MySQL / Docker / Kubernetes`;

export function GenerateResumeInline({ job, onGenerated, visible, onClose }: Props) {
  const [background, setBackground] = useState('');
  const [accent, setAccent] = useState(ACCENTS[0]);
  const [generating, setGenerating] = useState(false);
  const [progress, setProgress] = useState('');
  const [error, setError] = useState('');
  const [collapsed, setCollapsed] = useState(false);

  if (!visible) return null;

  const handleGenerate = async () => {
    if (!job) return;
    setGenerating(true);
    setError('');
    setProgress('AI 正在生成简历，请稍候（约 1-2 分钟）…');

    try {
      const resume = await agentApi.generateResume(job.id, background.trim(), 'classic', accent);
      setProgress('');
      onGenerated(resume);
      setBackground('');
      setCollapsed(true);
    } catch (e: any) {
      setError(e.message || '生成失败，请重试');
      setProgress('');
    } finally {
      setGenerating(false);
    }
  };

  if (collapsed) {
    return (
      <button
        onClick={() => setCollapsed(false)}
        className="absolute left-0 top-1/2 -translate-y-1/2 z-10 bg-accent-purple/20 hover:bg-accent-purple/30 border border-accent-purple/30 rounded-r-lg px-1 py-3 text-accent-purple transition-colors"
        title="展开生成简历面板"
      >
        <ChevronRight size={14} />
      </button>
    );
  }

  return (
    <div className="absolute right-0 top-0 bottom-0 w-[320px] min-w-[280px] shrink-0 flex flex-col bg-surface-800/95 backdrop-blur-sm border-l border-slate-700/30 z-20 shadow-2xl">
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-700/30">
        <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-200">
          <Sparkles size={13} className="text-accent-purple" /> AI 生成简历
          {job && <span className="text-[10px] px-1 py-0.5 rounded bg-accent-blue/15 text-accent-blue font-normal">{job.title}</span>}
        </span>
        <button onClick={onClose} className="text-slate-500 hover:text-slate-300 p-1 rounded hover:bg-slate-700/40 transition-colors">
          <X size={14} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin p-3 space-y-3">
        <div>
          <label className="text-[11px] text-slate-400 mb-1 block">
            候选人背景 <span className="text-slate-600">（可选）</span>
          </label>
          <textarea
            value={background}
            onChange={e => setBackground(e.target.value)}
            placeholder={PLACEHOLDER}
            rows={10}
            className="w-full bg-surface-900/60 border border-slate-700/50 rounded-md px-2.5 py-2 text-[11px] text-slate-200 placeholder-slate-600/50 focus:border-accent-blue/50 focus:outline-none resize-none font-mono leading-relaxed scrollbar-thin"
            disabled={generating}
          />
        </div>

        <div>
          <label className="text-[11px] text-slate-400 mb-1.5 flex items-center gap-1">
            <Palette size={11} /> 主题色
          </label>
          <div className="flex items-center gap-2">
            {ACCENTS.map(a => (
              <button
                key={a}
                onClick={() => setAccent(a)}
                disabled={generating}
                className={`relative w-5 h-5 rounded-full transition-all hover:scale-110 disabled:opacity-40 ${
                  accent === a ? 'ring-2 ring-white/80 ring-offset-1 ring-offset-surface-800 scale-110' : ''
                }`}
                style={{ backgroundColor: a }}
              >
                {accent === a && (
                  <svg className="absolute inset-0 m-auto w-2.5 h-2.5 text-white drop-shadow" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                )}
              </button>
            ))}
          </div>
        </div>

        {progress && (
          <div className="px-2.5 py-2 rounded-lg bg-accent-purple/10 border border-accent-purple/25 flex items-center gap-2">
            <Loader2 size={12} className="animate-spin text-accent-purple" />
            <span className="text-[11px] text-accent-purple">{progress}</span>
          </div>
        )}

        {error && (
          <div className="px-2.5 py-2 rounded-lg bg-red-500/10 border border-red-500/30 flex items-start gap-2">
            <AlertTriangle size={12} className="text-red-400 shrink-0 mt-0.5" />
            <p className="text-[11px] text-red-300/90 flex-1">{error}</p>
            <button onClick={() => setError('')} className="text-red-400 hover:text-red-300"><X size={12} /></button>
          </div>
        )}
      </div>

      <div className="shrink-0 px-3 py-2 border-t border-slate-700/30">
        <button
          onClick={handleGenerate}
          disabled={generating || !job}
          className="w-full flex items-center justify-center gap-1.5 px-3 py-1.5 text-xs bg-accent-purple text-white rounded-md hover:bg-accent-purple/85 disabled:opacity-40 transition-colors"
        >
          {generating ? <><Loader2 size={12} className="animate-spin" /> 生成中…</> : <><Sparkles size={12} /> 生成简历</>}
        </button>
      </div>
    </div>
  );
}
