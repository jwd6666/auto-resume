import { BookOpen, Settings, User } from 'lucide-react';

export function TopNav() {
  return (
    <header className="h-14 flex items-center px-5 border-b border-slate-800/80 bg-surface-850/95 backdrop-blur-sm shrink-0 glass-nav">
      {/* Logo + title */}
      <div className="flex items-center gap-2.5">
        <div className="w-8 h-8 rounded-lg bg-gradient-brand flex items-center justify-center shadow-md shadow-brand-500/30">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
        </div>
        <span className="font-semibold text-slate-100 text-[15px]">BOSS直聘 自动招呼助手</span>
        <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-gradient-to-r from-amber-500 to-orange-500 text-white">
          专业版
        </span>
      </div>

      {/* Slogan */}
      <div className="flex-1 text-center text-xs text-slate-500 tracking-wide">
        智能触达每一次机会，高效连接合适人才
      </div>

      {/* Right entries */}
      <div className="flex items-center gap-2">
        <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-slate-200 hover:bg-slate-800/60">
          <BookOpen size={15} /> 使用教程
        </button>
        <button className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-slate-200 hover:bg-slate-800/60">
          <Settings size={15} /> 设置
        </button>
        <button className="w-8 h-8 rounded-full bg-gradient-to-br from-brand-600 to-purple-500 flex items-center justify-center text-white text-xs font-bold hover:shadow-lg hover:shadow-brand-500/30">
          a
        </button>
      </div>
    </header>
  );
}
