import { BookOpen, LogIn, LogOut, Settings, User } from 'lucide-react';
import { useState } from 'react';
import { authApi } from '../../api/authApi';

interface TopNavProps {
  userAccount?: string | null;
  onLoggedOut?: () => void;
  onLogin?: () => void;
  onOpenSettings?: () => void;
}

export function TopNav({ userAccount, onLoggedOut, onLogin, onOpenSettings }: TopNavProps) {
  const [loggingOut, setLoggingOut] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const initial = (userAccount || '游').charAt(0).toUpperCase();

  // 两段式确认，避免原生 confirm() 在 Electron 下导致窗口焦点丢失
  const handleLogout = async () => {
    if (loggingOut) return;
    if (!confirming) {
      setConfirming(true);
      setTimeout(() => setConfirming(false), 3000);
      return;
    }
    setConfirming(false);
    setLoggingOut(true);
    try {
      await authApi.logout();
      onLoggedOut?.();
    } catch { /* 状态轮询会兜底 */ }
    finally { setLoggingOut(false); }
  };

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
        <a
          href="https://rcnchhlydglp.feishu.cn/wiki/KzNTwo9zDiqmuykXpXEctrD5nLd?from=from_copylink"
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
        >
          <BookOpen size={15} /> 使用教程
        </a>
        <button
          onClick={onOpenSettings}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-slate-400 hover:text-slate-200 hover:bg-slate-800/60"
        >
          <Settings size={15} /> 设置
        </button>
        {userAccount ? (
          <div className="flex items-center gap-2 pl-2 border-l border-slate-800">
            <span className="text-xs text-slate-400 max-w-40 truncate" title={userAccount}>{userAccount}</span>
            <button
              onClick={handleLogout}
              disabled={loggingOut}
              title="退出登录"
              className={`flex items-center gap-1 px-2 py-1.5 rounded-lg text-xs transition-colors disabled:opacity-50 ${
                confirming
                  ? 'text-red-300 bg-red-500/15'
                  : 'text-slate-400 hover:text-red-300 hover:bg-red-500/10'
              }`}
            >
              <LogOut size={14} /> {confirming ? '确认退出？' : '退出'}
            </button>
          </div>
        ) : onLogin ? (
          <div className="flex items-center gap-2 pl-2 border-l border-slate-800">
            <span className="text-xs text-slate-500">未登录</span>
            <button
              onClick={onLogin}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs text-sky-300 hover:text-sky-200 hover:bg-sky-500/10 transition-colors"
            >
              <LogIn size={14} /> 登录
            </button>
          </div>
        ) : null}
        <button className="w-8 h-8 rounded-full bg-gradient-to-br from-brand-600 to-purple-500 flex items-center justify-center text-white text-xs font-bold hover:shadow-lg hover:shadow-brand-500/30">
          {initial}
        </button>
      </div>
    </header>
  );
}
