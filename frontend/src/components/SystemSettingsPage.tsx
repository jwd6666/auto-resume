import { useEffect, useState } from 'react';
import { Bell, CheckCircle2, KeyRound, Loader2, LogIn, RefreshCw, XCircle } from 'lucide-react';
import { updateApi, type UpdateStatus } from '../api/updateApi';
import { authApi } from '../api/authApi';

interface SystemSettingsPageProps {
  userAccount?: string | null;
}

const inputCls =
  'w-full px-2.5 py-1.5 bg-slate-900 border border-slate-700 rounded-md text-sm text-slate-200 placeholder:text-slate-600 outline-none focus:border-sky-500 transition-colors';

export function SystemSettingsPage({ userAccount }: SystemSettingsPageProps) {
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [saving, setSaving] = useState(false);
  const [checking, setChecking] = useState(false);

  // 修改密码表单
  const [oldPwd, setOldPwd] = useState('');
  const [newPwd, setNewPwd] = useState('');
  const [confirmPwd, setConfirmPwd] = useState('');
  const [changing, setChanging] = useState(false);
  const [pwdMsg, setPwdMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = () => updateApi.check().then(setStatus).catch(() => {});
  useEffect(() => { load(); }, []);

  const togglePrompt = async (enabled: boolean) => {
    setSaving(true);
    try {
      await updateApi.setPromptEnabled(enabled);
      await load();
    } catch { /* 轮询会兜底 */ }
    finally { setSaving(false); }
  };

  const checkNow = async () => {
    setChecking(true);
    try { setStatus(await updateApi.checkNow()); } catch { /* ignore */ }
    finally { setChecking(false); }
  };

  const changePassword = async () => {
    if (changing) return;
    if (!oldPwd) { setPwdMsg({ ok: false, text: '请输入原密码' }); return; }
    if (newPwd.length < 6) { setPwdMsg({ ok: false, text: '新密码至少 6 位' }); return; }
    if (newPwd !== confirmPwd) { setPwdMsg({ ok: false, text: '两次输入的新密码不一致' }); return; }
    setChanging(true);
    setPwdMsg(null);
    try {
      await authApi.changePassword(oldPwd, newPwd);
      setPwdMsg({ ok: true, text: '密码已更新' });
      setOldPwd(''); setNewPwd(''); setConfirmPwd('');
    } catch (e: any) {
      setPwdMsg({ ok: false, text: e.message || '修改失败，请稍后重试' });
    } finally { setChanging(false); }
  };

  return (
    <div className="p-5 h-full overflow-y-auto scrollbar-thin animate-fade-in">
      <div className="mb-4">
        <h1 className="text-xl font-bold text-slate-100">系统设置</h1>
        <p className="text-sm text-slate-500 mt-0.5">配置应用偏好</p>
      </div>

      {/* 账号安全 */}
      <div className="card p-5 max-w-2xl mb-4">
        <div className="flex items-center gap-2 mb-4">
          <KeyRound size={16} className="text-brand-400" />
          <h2 className="text-sm font-semibold text-slate-200">账号安全</h2>
        </div>

        {userAccount ? (
          <>
            <div className="flex items-center justify-between py-3 border-t border-slate-800/60">
              <div>
                <div className="text-sm text-slate-300">当前账号</div>
                <div className="text-xs text-slate-500 mt-0.5">{userAccount}</div>
              </div>
            </div>
            <div className="py-3 border-t border-slate-800/60 space-y-2.5">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5">
                <input
                  type="password"
                  value={oldPwd}
                  onChange={(e) => setOldPwd(e.target.value)}
                  placeholder="原密码"
                  autoComplete="current-password"
                  className={inputCls}
                />
                <input
                  type="password"
                  value={newPwd}
                  onChange={(e) => setNewPwd(e.target.value)}
                  placeholder="新密码（至少 6 位）"
                  autoComplete="new-password"
                  className={inputCls}
                />
                <input
                  type="password"
                  value={confirmPwd}
                  onChange={(e) => setConfirmPwd(e.target.value)}
                  placeholder="确认新密码"
                  autoComplete="new-password"
                  className={inputCls}
                />
              </div>
              <div className="flex items-center gap-3">
                <button
                  onClick={changePassword}
                  disabled={changing}
                  className="btn-primary text-xs disabled:opacity-50"
                >
                  {changing ? <Loader2 size={13} className="animate-spin" /> : <KeyRound size={13} />}
                  修改密码
                </button>
                {pwdMsg && (
                  <span className={`text-xs flex items-center gap-1 ${pwdMsg.ok ? 'text-emerald-400' : 'text-red-400'}`}>
                    {pwdMsg.ok ? <CheckCircle2 size={13} /> : <XCircle size={13} />}
                    {pwdMsg.text}
                  </span>
                )}
              </div>
            </div>
          </>
        ) : (
          <div className="flex items-center justify-between py-3 border-t border-slate-800/60">
            <div className="text-xs text-slate-500">登录后可修改账号密码</div>
            <button
              onClick={() => window.dispatchEvent(new Event('request-login'))}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs text-sky-300 hover:text-sky-200 hover:bg-sky-500/10 transition-colors"
            >
              <LogIn size={13} /> 前往登录
            </button>
          </div>
        )}
      </div>

      {/* 更新设置 */}
      <div className="card p-5 max-w-2xl">
        <div className="flex items-center gap-2 mb-4">
          <RefreshCw size={16} className="text-brand-400" />
          <h2 className="text-sm font-semibold text-slate-200">软件更新</h2>
        </div>

        {/* 当前版本 + 检查按钮 */}
        <div className="flex items-center justify-between py-3 border-t border-slate-800/60">
          <div>
            <div className="text-sm text-slate-300">当前版本</div>
            <div className="text-xs text-slate-500 mt-0.5">
              v{status?.current_version ?? '—'}
              {status?.last_checked_at && ` · 上次检查 ${new Date(status.last_checked_at + 'Z').toLocaleString('zh-CN')}`}
            </div>
          </div>
          <button
            onClick={checkNow}
            disabled={checking}
            className="btn-primary text-xs disabled:opacity-50"
          >
            {checking ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
            检查更新
          </button>
        </div>

        {/* 更新提示开关 */}
        <div className="flex items-center gap-4 py-3 border-t border-slate-800/60">
          <button
            role="switch"
            aria-checked={status?.prompt_enabled ?? true}
            disabled={saving || !status}
            onClick={() => togglePrompt(!(status?.prompt_enabled ?? true))}
            className={`relative w-11 h-6 rounded-full transition-colors shrink-0 disabled:opacity-50 ${
              status?.prompt_enabled ? 'bg-brand-500' : 'bg-slate-600'
            }`}
          >
            <span
              className={`absolute top-[2px] left-[2px] w-5 h-5 rounded-full bg-white shadow transition-all duration-200 ${
                status?.prompt_enabled ? 'translate-x-5' : 'translate-x-0'
              }`}
            />
          </button>
          <div>
            <div className="text-sm text-slate-300 flex items-center gap-1.5">
              <Bell size={13} className="text-slate-500" />
              更新提示
            </div>
            <div className="text-xs text-slate-500 mt-0.5">
              关闭后新版本不再弹横幅提醒，仍可手动检查更新（强制更新除外）
            </div>
          </div>
        </div>

        {/* 最近一次检查结果 */}
        {status && (
          <div className="py-3 border-t border-slate-800/60">
            {status.update_available ? (
              <div className="flex items-center gap-2 text-xs">
                <XCircle size={14} className="text-amber-400" />
                <span className="text-slate-400">
                  有可用新版本 <span className="text-slate-200 font-medium">v{status.latest?.version}</span>
                  {status.force && <span className="text-red-400">（强制更新）</span>}
                  {status.skipped_version === status.latest?.version && (
                    <span className="text-slate-500"> · 已跳过此版本的提醒</span>
                  )}
                </span>
              </div>
            ) : (
              <div className="flex items-center gap-2 text-xs text-slate-500">
                <CheckCircle2 size={14} className="text-emerald-400" />
                已是最新版本
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
