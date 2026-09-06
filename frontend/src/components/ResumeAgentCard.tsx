import { Sparkles, FileSearch, PenTool, Palette, Target } from 'lucide-react';

interface Props {
  onNavigate?: () => void;
}

export function ResumeAgentCard({ onNavigate }: Props) {
  const features = [
    { icon: <FileSearch size={13} />, label: '智能诊断', desc: 'AI 深度分析简历问题' },
    { icon: <PenTool size={13} />, label: '内容优化', desc: '优化表达，突出核心优势' },
    { icon: <Palette size={13} />, label: '格式美化', desc: '专业排版，提升阅读性' },
    { icon: <Target size={13} />, label: '匹配度分析', desc: '与目标岗位智能匹配' },
  ];

  return (
    <div className="card card-lift p-4 flex flex-col h-full relative overflow-hidden animate-slide-up" style={{ animationDelay: '140ms' }}>
      <div className="absolute -top-10 -right-10 w-32 h-32 rounded-full bg-gradient-to-br from-brand-500/10 to-purple-500/10 blur-3xl" />

      <div className="relative">
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-2">
            <Sparkles size={16} className="text-brand-400" />
            <h3 className="text-sm font-semibold text-slate-200">简历优化 Agent</h3>
          </div>
          <span className="badge-new">新功能</span>
        </div>
        <p className="text-[11px] text-slate-500 mb-3">AI 智能优化简历，提升竞争力</p>

        <button onClick={onNavigate} className="w-full py-2 rounded-lg bg-gradient-to-r from-brand-600 to-brand-500 hover:from-brand-500 hover:to-brand-400 text-white text-sm font-medium shadow-md shadow-brand-500/20 inline-flex items-center justify-center gap-1.5">
          <Sparkles size={14} />
          开始优化简历 →
        </button>

        <div className="mt-3 grid grid-cols-2 gap-2">
          {features.map((f, i) => (
            <div
              key={i}
              className="flex items-center gap-1.5 p-1.5 rounded-md hover:bg-slate-800/40 group"
            >
              <div className="w-5 h-5 rounded bg-brand-500/10 text-brand-400 flex items-center justify-center shrink-0 group-hover:bg-brand-500/20">
                {f.icon}
              </div>
              <div className="min-w-0">
                <div className="text-[11px] font-medium text-slate-300 truncate">{f.label}</div>
                <div className="text-[10px] text-slate-600 truncate">{f.desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
