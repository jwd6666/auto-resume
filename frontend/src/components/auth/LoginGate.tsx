/** 登录门卫：未登录（游客模式）时拦截自动打招呼相关功能。 */
import { Shield } from 'lucide-react';

interface Props {
  /** true=整页展示（任务管理/岗位管理页）；false=卡片嵌入首页栅格 */
  fullPage?: boolean;
  title?: string;
  subtitle?: string;
}

export function LoginGate({
  fullPage = false,
  title = '自动打招呼功能需要登录后使用',
  subtitle = '登录后即可创建并运行打招呼任务',
}: Props) {
  const requestLogin = () => window.dispatchEvent(new CustomEvent('request-login'));

  const inner = (
    <div
      className={
        fullPage
          ? 'card py-16 text-center'
          : 'card p-6 h-full min-h-[220px] flex flex-col items-center justify-center text-center'
      }
    >
      <Shield size={fullPage ? 28 : 24} className="text-slate-600 mx-auto mb-3" />
      <p className="text-sm text-slate-400">{title}</p>
      <p className="text-xs text-slate-600 mt-1">{subtitle}</p>
      <button onClick={requestLogin} className="btn-primary mx-auto mt-4">
        前往登录
      </button>
    </div>
  );

  if (fullPage) {
    return (
      <div className="p-5 h-full flex items-center justify-center animate-fade-in">
        <div className="w-full max-w-md">{inner}</div>
      </div>
    );
  }
  return inner;
}
