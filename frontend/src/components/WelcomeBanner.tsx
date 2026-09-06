import { Bot } from 'lucide-react';

export function WelcomeBanner() {
  const hour = new Date().getHours();
  const greeting = hour < 6 ? '凌晨好' : hour < 12 ? '早上好' : hour < 18 ? '下午好' : '晚上好';

  return (
    <div className="card card-lift p-5 flex items-center gap-5 animate-slide-up">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-lg font-bold text-slate-100">{greeting}，a</span>
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse-slow" />
        </div>
        <p className="text-sm text-slate-400">
          让 AI 帮你高效触达，智能优化，收获更多优质回复
        </p>
      </div>

      {/* AI illustration placeholder */}
      <div className="shrink-0 w-28 h-28 rounded-xl bg-gradient-to-br from-brand-500/15 to-purple-500/10 border border-slate-700/50 flex items-center justify-center relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-brand-500/5 via-transparent to-purple-500/10" />
        <div className="absolute top-3 right-3 w-8 h-8 rounded-full bg-brand-500/10 blur-md" />
        <div className="absolute bottom-2 left-2 w-6 h-6 rounded-full bg-purple-500/10 blur-md" />
        <Bot size={42} className="text-brand-400/80 relative z-10" strokeWidth={1.2} />
      </div>
    </div>
  );
}
