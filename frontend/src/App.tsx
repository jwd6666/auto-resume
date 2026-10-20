import { useEffect, useState } from 'react';
import { Plus, Loader2 } from 'lucide-react';
import { TopNav } from './components/common/TopNav';
import { Sidebar } from './components/common/Sidebar';
import { WelcomeBanner } from './components/boss/WelcomeBanner';
import { StatsGrid } from './components/common/StatsGrid';
import { DashboardTasks } from './components/boss/DashboardTasks';
import { LogsPanel } from './components/boss/LogsPanel';
import { ResumeAgentCard } from './components/resume/ResumeAgentCard';
import { QuickActions } from './components/boss/QuickActions';
import { NewTaskModal } from './components/boss/NewTaskModal';
import { TaskCard } from './components/boss/TaskCard';
import { ModelManagement } from './components/settings/ModelManagement';
import { LoginPage } from './components/auth/LoginPage';
import { UpdateBanner } from './components/common/UpdateBanner';
import { ForceUpdateGate } from './components/common/ForceUpdateGate';
import { SystemSettingsPage } from './components/settings/SystemSettingsPage';
import { ResumeAgentPage } from './components/resume/ResumeAgentPage';
import { AICopyPage } from './components/boss/AICopyPage';
import { JobAnalysisPage } from './components/boss/JobAnalysisPage';
import { JobManagePage } from './components/boss/JobManagePage';
import { LoginGate } from './components/auth/LoginGate';
import { api, type TaskInfo } from './api/client';
import { authApi } from './api/authApi';
import { updateApi, type UpdateStatus } from './api/updateApi';
import { useTasks } from './store/useTasks';

type AuthPhase = 'checking' | 'guest' | 'active' | 'banned';

export default function App() {
  const { tasks, loading, refresh, selectedId, select, upsert } = useTasks();
  const [activeMenu, setActiveMenu] = useState('home');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [editing, setEditing] = useState<TaskInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [authPhase, setAuthPhase] = useState<AuthPhase>('checking');
  const [banReason, setBanReason] = useState<string | null>(null);
  const [userAccount, setUserAccount] = useState<string | null>(null);
  const [updateStatus, setUpdateStatus] = useState<UpdateStatus | null>(null);
  const [updateDismissed, setUpdateDismissed] = useState(false);
  const [skipped, setSkipped] = useState(false);
  const canUseApp = authPhase === 'active' || (authPhase === 'guest' && skipped);
  /** 自动打招呼等功能需登录：游客模式下拦截 */
  const loggedIn = authPhase === 'active';
  const requestLogin = () => window.dispatchEvent(new CustomEvent('request-login'));

  // 启动 + 轮询鉴权状态：未登录/被封禁时锁定在登录页
  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const s = await authApi.status();
        if (!alive) return;
        if (s.status === 'active') {
          setAuthPhase('active');
          setBanReason(null);
          setUserAccount(s.user?.account ?? null);
        } else if (s.status === 'banned') {
          setAuthPhase('banned');
          setBanReason(s.ban_reason);
        } else {
          setAuthPhase('guest');
          setBanReason(null);
        }
      } catch {
        /* sidecar 未就绪时保持 checking，显示加载页 */
      }
    };
    check();
    const t = setInterval(check, 5000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  useEffect(() => {
    // 打招呼任务接口需登录，游客模式不轮询（否则会刷 401 错误横幅）
    if (!loggedIn) return;
    refresh().catch((e) => setError(`后端连接失败：${e.message}`));
    const t = setInterval(() => { refresh().catch(() => {}); }, 5000);
    return () => clearInterval(t);
  }, [refresh, loggedIn]);

  // 登录后轮询更新状态（60s），sidecar 已缓存云端结果，本地接口开销极小
  useEffect(() => {
    if (!canUseApp) return;
    const poll = () => updateApi.check().then(setUpdateStatus).catch(() => {});
    poll();
    const t = setInterval(poll, 60000);
    return () => clearInterval(t);
  }, [canUseApp]);

  useEffect(() => {
    const handler = () => setActiveMenu('accounts');
    window.addEventListener('navigate-model-management', handler);
    return () => window.removeEventListener('navigate-model-management', handler);
  }, []);

  // 模型管理页等发出的「前往登录」请求：回到登录页
  useEffect(() => {
    const handler = () => setSkipped(false);
    window.addEventListener('request-login', handler);
    return () => window.removeEventListener('request-login', handler);
  }, []);

  const selected = tasks.find((t) => t.id === selectedId) ?? null;

  const handleAction = async (id: string, fn: () => Promise<unknown>) => {
    try { await fn(); await refresh(); }
    catch (e: any) { alert(`操作失败：${e.message}`); }
  };

  // 计算统计数据
  const todaySent = tasks.reduce((s, t) => s + (t.sent_today ?? 0), 0);
  const dailyLimit = tasks.reduce((s, t) => s + (t.daily_limit ?? 150), 0);
  const runningCount = tasks.filter((t) => t.status === 'running').length;

  // 渲染首页概览
  const renderHome = () => (
    <div className="p-5 space-y-4 animate-fade-in overflow-y-auto scrollbar-thin h-full">
      <WelcomeBanner />
      {loggedIn && (
        <StatsGrid todaySent={todaySent} dailyLimit={dailyLimit} runningTasks={runningCount} totalTasks={tasks.length} />
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
        {loggedIn ? (
          <DashboardTasks
            tasks={tasks}
            selectedId={selectedId}
            onSelect={select}
            onViewAll={() => setActiveMenu('tasks')}
            onCreateTask={() => { setEditing(null); setShowNew(true); }}
            onStart={(id) => handleAction(id, () => api.start(id))}
            onPause={(id) => handleAction(id, () => api.pause(id))}
            onResume={(id) => handleAction(id, () => api.resume(id))}
            onStop={(id) => handleAction(id, () => api.stop(id))}
            onLogin={(id) => handleAction(id, () => api.login(id))}
            onEdit={(id) => { const task = tasks.find(t => t.id === id); if (task) { setEditing(task); setShowNew(true); } }}
            onDelete={(id) => { if (confirm('确认删除此任务？')) handleAction(id, () => api.remove(id)); }}
            onRefreshLogin={(id) => handleAction(id, () => api.login(id))}
          />
        ) : (
          <LoginGate />
        )}
        <ResumeAgentCard onNavigate={() => setActiveMenu('resume')} />
        {loggedIn && <LogsPanel selectedTask={selected} />}
        <QuickActions
          onCreateTask={loggedIn ? () => { setEditing(null); setShowNew(true); } : requestLogin}
          onAICopy={() => setActiveMenu('ai-copy')}
          onSystemSettings={() => setActiveMenu('system-settings')}
        />
      </div>
    </div>
  );

  // 渲染任务管理
  const renderTasks = () => (
    <div className="p-5 h-full flex flex-col animate-fade-in">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold text-slate-100">任务管理</h1>
          <p className="text-sm text-slate-500 mt-0.5">管理所有自动招呼任务</p>
        </div>
        <button onClick={() => { setEditing(null); setShowNew(true); }} className="btn-primary">
          <Plus size={16} /> 新建任务
        </button>
      </div>
      <div className="flex-1 overflow-y-auto scrollbar-thin space-y-2 pr-1">
        {tasks.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <div className="w-16 h-16 rounded-2xl bg-slate-800/60 flex items-center justify-center mb-4">
              <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-slate-600">
                <rect x="3" y="3" width="18" height="18" rx="2" />
                <path d="M9 9h6v6H9z" />
              </svg>
            </div>
            <p className="text-sm text-slate-400">暂无任务</p>
            <p className="text-xs text-slate-600 mt-1">点击"新建任务"开始</p>
          </div>
        ) : (
          tasks.map((t) => (
            <TaskCard
              key={t.id}
              task={t}
              active={t.id === selectedId}
              onSelect={() => select(t.id)}
              onStart={() => handleAction(t.id, () => api.start(t.id))}
              onPause={() => handleAction(t.id, () => api.pause(t.id))}
              onResume={() => handleAction(t.id, () => api.resume(t.id))}
              onStop={() => handleAction(t.id, () => api.stop(t.id))}
              onLogin={() => handleAction(t.id, () => api.login(t.id))}
              onEdit={() => { setEditing(t); setShowNew(true); }}
              onDelete={() => { if (confirm(`确认删除任务「${t.name}」？`)) handleAction(t.id, () => api.remove(t.id)); }}
            />
          ))
        )}
      </div>
    </div>
  );

  // 占位页
  const renderPlaceholder = (title: string, subtitle: string) => (
    <div className="p-5 h-full flex flex-col animate-fade-in">
      <div className="mb-4">
        <h1 className="text-xl font-bold text-slate-100">{title}</h1>
        <p className="text-sm text-slate-500 mt-0.5">{subtitle}</p>
      </div>
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center">
          <div className="w-20 h-20 rounded-2xl bg-slate-800/60 flex items-center justify-center mb-4 mx-auto">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-slate-600">
              <path d="M12 2L2 7l10 5 10-5-10-5z" />
              <path d="M2 17l10 5 10-5" />
              <path d="M2 12l10 5 10-5" />
            </svg>
          </div>
          <p className="text-sm text-slate-400">功能开发中</p>
          <p className="text-xs text-slate-600 mt-1">此功能即将上线，敬请期待</p>
        </div>
      </div>
    </div>
  );

  const renderContent = () => {
    switch (activeMenu) {
      case 'home':
      case 'auto-greet': return renderHome();
      case 'tasks': return loggedIn ? renderTasks() : <LoginGate fullPage />;
      case 'templates': return renderPlaceholder('话术模板', '管理招呼话术模板');
      case 'accounts': return <ModelManagement />;
      case 'ai-copy': return null;
      case 'job-manage': return loggedIn ? <JobManagePage /> : <LoginGate fullPage title="岗位管理需要登录后使用" subtitle="登录后即可管理岗位与打招呼记录" />;
      case 'job-analysis': return null;
      case 'boss-config': return renderPlaceholder('BOSS配置', '配置 BOSS直聘 平台相关参数');
      case 'system-settings': return <SystemSettingsPage userAccount={userAccount} />;
      default: return renderHome();
    }
  };

  // 鉴权门卫：检查中 / 未登录 / 被封禁时只渲染登录相关界面
  if (authPhase === 'checking') {
    return (
      <div className="h-full flex flex-col items-center justify-center bg-surface-850 gap-3">
        <Loader2 size={28} className="animate-spin text-brand-400" />
        <p className="text-sm text-slate-500">正在连接服务...</p>
      </div>
    );
  }

  if (authPhase === 'banned') {
    return (
      <LoginPage
        initialStatus="banned"
        banReason={banReason}
        onLoggedIn={() => setAuthPhase('active')}
      />
    );
  }

  if (authPhase === 'guest' && !skipped) {
    return (
      <LoginPage
        initialStatus="not_logged_in"
        banReason={banReason}
        onLoggedIn={() => { setAuthPhase('active'); setSkipped(false); }}
        onSkip={() => setSkipped(true)}
      />
    );
  }

  // 强制更新：拦截整个应用，仅允许前往下载，无法关闭
  const forceUpdate = updateStatus?.should_prompt && updateStatus.force ? updateStatus.latest : null;
  if (forceUpdate) {
    return (
      <ForceUpdateGate update={forceUpdate} currentVersion={updateStatus?.current_version ?? ''} />
    );
  }

  return (
    <div className="h-full flex flex-col bg-surface-850">
      <TopNav
        userAccount={userAccount}
        onLoggedOut={() => { setAuthPhase('guest'); setUserAccount(null); setSkipped(false); }}
        onLogin={() => setSkipped(false)}
        onOpenSettings={() => setActiveMenu('system-settings')}
      />
      {/* 更新提示横幅（非强制）：可点击 X 本次关闭；强制更新由 ForceUpdateGate 拦截 */}
      {updateStatus?.should_prompt && updateStatus.latest && !updateDismissed && (
        <UpdateBanner
          update={updateStatus.latest}
          force={updateStatus.force}
          currentVersion={updateStatus.current_version}
          onSkip={async (version) => {
            await updateApi.skipVersion(version).catch(() => {});
            setUpdateStatus((s) => (s ? { ...s, should_prompt: false, skipped_version: version } : s));
          }}
          onDismiss={() => setUpdateDismissed(true)}
        />
      )}
      {error && (
        <div className="px-5 py-2 bg-red-500/20 text-red-300 text-sm border-b border-red-500/30">
          {error}
        </div>
      )}
      <div className="flex-1 flex overflow-hidden">
        <Sidebar active={activeMenu} onSelect={setActiveMenu} collapsed={sidebarCollapsed} onToggleCollapse={() => setSidebarCollapsed(c => !c)} />
        <main className="flex-1 overflow-hidden bg-surface-900/30">
          {/* ResumeAgentPage 始终挂载，切页面时只隐藏不卸载，保留聊天记录和编辑状态 */}
          <div className={`h-full ${activeMenu === 'resume' ? '' : 'hidden'}`}>
            <ResumeAgentPage />
          </div>
          {/* AICopyPage 始终挂载，切页面时只隐藏不卸载，保留生成状态 */}
          <div className={`h-full ${activeMenu === 'ai-copy' ? '' : 'hidden'}`}>
            <AICopyPage />
          </div>
          {/* JobAnalysisPage 始终挂载，切页面时只隐藏不卸载，保留分析状态 */}
          <div className={`h-full ${activeMenu === 'job-analysis' ? '' : 'hidden'}`}>
            <JobAnalysisPage />
          </div>
          {activeMenu !== 'resume' && activeMenu !== 'ai-copy' && activeMenu !== 'job-analysis' && renderContent()}
        </main>
      </div>
      <NewTaskModal
        open={showNew}
        editing={editing}
        onClose={() => { setShowNew(false); setEditing(null); }}
        onCreated={async (taskId) => { await refresh(); select(taskId); setActiveMenu('tasks'); }}
      />
    </div>
  );
}
