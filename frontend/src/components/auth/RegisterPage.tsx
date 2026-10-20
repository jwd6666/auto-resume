import { useState } from 'react';
import { ArrowLeft, Check, Copy, Mail, MessageCircle, Users } from 'lucide-react';

const REGISTER_EMAIL = '3434504164@qq.com';

interface RegisterPageProps {
  onBack: () => void;
}

function copyText(text: string): boolean {
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}

export function RegisterPage({ onBack }: RegisterPageProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    let ok = false;
    if (navigator.clipboard) {
      try {
        await navigator.clipboard.writeText(REGISTER_EMAIL);
        ok = true;
      } catch {
        ok = copyText(REGISTER_EMAIL);
      }
    } else {
      ok = copyText(REGISTER_EMAIL);
    }
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className="h-full overflow-y-auto scrollbar-thin flex items-center justify-center" style={{ background: '#0f172a' }}>
      <div className="w-full max-w-2xl mx-4 my-8">
        <div className="flex items-center gap-3 mb-6">
          <button
            onClick={onBack}
            className="w-9 h-9 rounded-lg border border-slate-700 flex items-center justify-center text-slate-400 hover:text-slate-200 hover:border-slate-500 transition-colors"
            style={{ background: '#0b1220' }}
            title="返回登录"
          >
            <ArrowLeft size={17} />
          </button>
          <div>
            <h1 className="text-2xl font-bold text-slate-100">注册账号</h1>
            <p className="text-sm text-slate-500 mt-0.5">以下两种方式任选其一，即可完成注册</p>
          </div>
        </div>

        <div className="card p-4 mb-4 flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-sky-500/15 flex items-center justify-center shrink-0">
            <Mail size={18} className="text-sky-400" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-xs text-slate-500">注册邮箱</div>
            <div className="text-sm text-slate-200 font-medium truncate">{REGISTER_EMAIL}</div>
          </div>
          <button
            onClick={handleCopy}
            className="shrink-0 inline-flex items-center gap-1.5 px-3 py-2 rounded-lg border border-slate-700 text-xs text-slate-300 hover:border-sky-500 hover:text-sky-300 transition-colors"
            style={{ background: '#0b1220' }}
          >
            {copied ? <Check size={14} className="text-emerald-400" /> : <Copy size={14} />}
            {copied ? '已复制' : '复制邮箱'}
          </button>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="card p-5 flex flex-col items-center text-center">
            <img
              src="./qrcode/douyin.png"
              alt="抖音二维码"
              className="w-44 h-44 object-contain rounded-lg bg-white p-1.5 mb-3"
            />
            <div className="text-sm font-semibold text-slate-200 mb-1.5 flex items-center gap-1.5">
              <Users size={15} className="text-slate-400" />
              抖音二维码
            </div>
            <p className="text-xs text-slate-500 leading-relaxed">
              抖音群二维码，进群联系群主即可注册
            </p>
          </div>

          <div className="card p-5 flex flex-col items-center text-center">
            <img
              src="./qrcode/gongzhonghao.png"
              alt="公众号二维码"
              className="w-44 h-44 object-contain rounded-lg bg-white p-1.5 mb-3"
            />
            <div className="text-sm font-semibold text-slate-200 mb-1.5 flex items-center gap-1.5">
              <MessageCircle size={15} className="text-slate-400" />
              公众号二维码
            </div>
            <p className="text-xs text-slate-500 leading-relaxed">
              微信扫码关注公众号，在公众号后台私信即可注册
            </p>
          </div>
        </div>

        <div className="card p-4 mt-4 space-y-2.5">
          <div className="flex gap-2.5">
            <span className="shrink-0 w-5 h-5 rounded-md bg-sky-500/15 text-sky-400 text-xs font-bold flex items-center justify-center">1</span>
            <p className="text-xs text-slate-400 leading-relaxed">
              方式一：发送邮件至 <span className="text-sky-300">{REGISTER_EMAIL}</span> 说明注册意向，获取抖音群二维码后进群联系群主完成注册
            </p>
          </div>
          <div className="flex gap-2.5">
            <span className="shrink-0 w-5 h-5 rounded-md bg-emerald-500/15 text-emerald-400 text-xs font-bold flex items-center justify-center">2</span>
            <p className="text-xs text-slate-400 leading-relaxed">
              方式二：扫描上方公众号二维码关注，在公众号后台直接私信注册
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
