import { useState } from 'react';
import { Bot, Loader2, Lock, LogIn, User, ShieldAlert } from 'lucide-react';
import { authApi } from '../../api/authApi';
import { RegisterPage } from './RegisterPage';

interface LoginPageProps {
  initialStatus: 'not_logged_in' | 'banned' | null;
  banReason?: string | null;
  onLoggedIn: () => void;
  onSkip?: () => void;
}

export function LoginPage({ initialStatus, banReason, onLoggedIn, onSkip }: LoginPageProps) {
  const [account, setAccount] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showRegister, setShowRegister] = useState(false);
  const banned = initialStatus === 'banned';

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (account.trim().length < 3 || !password || loading) return;
    setLoading(true);
    setError(null);
    try {
      await authApi.login(account.trim(), password);
      onLoggedIn();
    } catch (err: any) {
      setError(err.message || '登录失败');
    } finally {
      setLoading(false);
    }
  };

  if (showRegister) {
    return <RegisterPage onBack={() => setShowRegister(false)} />;
  }

  return (
    <div className="h-full flex items-center justify-center" style={{ background: '#0f172a' }}>
      <div className="w-full max-w-sm mx-4">
        {/* Logo */}
        <div className="flex flex-col items-center mb-6">
          <div className="w-16 h-16 rounded-2xl bg-gradient-brand flex items-center justify-center mb-3 shadow-lg shadow-brand-500/25">
            <Bot size={34} className="text-white" strokeWidth={1.5} />
          </div>
          <h1 className="text-2xl font-bold text-slate-100">AutoResume</h1>
          <p className="text-sm text-slate-500 mt-1">AI 驱动的求职自动化助手</p>
        </div>

        {/* 封禁提示 */}
        {banned && (
          <div className="card p-3 mb-3 flex items-start gap-2 border-red-500/30">
            <ShieldAlert size={16} className="text-red-400 shrink-0 mt-0.5" />
            <div className="text-xs text-red-300 leading-relaxed">
              <div className="font-semibold">账户已被禁用</div>
              {banReason && <div className="text-red-400/80 mt-0.5">{banReason}</div>}
              <div className="text-slate-500 mt-0.5">如有疑问请联系管理员，或使用其他账号登录</div>
            </div>
          </div>
        )}

        {/* 登录表单 */}
        <form onSubmit={handleSubmit} className="card p-5 space-y-3">
          <div className="relative">
            <User size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              value={account}
              onChange={(e) => setAccount(e.target.value)}
              placeholder="账号"
              autoFocus
              className="w-full pl-9 pr-3 py-2.5 rounded-lg border border-slate-700 text-sm text-slate-200 placeholder:text-slate-600 outline-none focus:border-sky-500 transition-colors"
              style={{ background: '#0b1220' }}
            />
          </div>

          <div className="relative">
            <Lock size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="密码"
              autoComplete="current-password"
              className="w-full pl-9 pr-3 py-2.5 rounded-lg border border-slate-700 text-sm text-slate-200 placeholder:text-slate-600 outline-none focus:border-sky-500 transition-colors"
              style={{ background: '#0b1220' }}
            />
          </div>

          {error && (
            <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading || account.trim().length < 3 || !password}
            className="btn-primary w-full py-2.5 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? (
              <Loader2 size={16} className="animate-spin" />
            ) : (
              <LogIn size={16} />
            )}
            {loading ? '登录中...' : '登录'}
          </button>
        </form>

        <p className="text-center text-xs text-slate-600 mt-4">
          还没有账号？
          <button
            onClick={() => setShowRegister(true)}
            className="text-sky-400 hover:text-sky-300 font-medium ml-1 transition-colors"
          >
            立即注册
          </button>
        </p>

        {!banned && onSkip && (
          <button
            onClick={onSkip}
            className="w-full mt-3 py-2 rounded-lg border border-slate-700 text-xs text-slate-400 hover:text-slate-200 hover:border-slate-500 transition-colors"
            style={{ background: '#0b1220' }}
          >
            跳过登录，直接使用
          </button>
        )}
        {!banned && onSkip && (
          <p className="text-center text-[10px] text-slate-600 mt-2">
            跳过后可正常使用，自动打招呼、官方模型与添加自定义模型需登录
          </p>
        )}
      </div>
    </div>
  );
}
