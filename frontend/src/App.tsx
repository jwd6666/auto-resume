import { useEffect, useState } from 'react';
import { Plus } from 'lucide-react';
import { TopNav } from './components/TopNav';
import { Sidebar } from './components/Sidebar';
import { WelcomeBanner } from './components/WelcomeBanner';
import { StatsGrid } from './components/StatsGrid';
import { DashboardTasks } from './components/DashboardTasks';
import { LogsPanel } from './components/LogsPanel';
import { ResumeAgentCard } from './components/ResumeAgentCard';
import { QuickActions } from './components/QuickActions';
import { NewTaskModal } from './components/NewTaskModal';
import { TaskCard } from './components/TaskCard';
import { ModelManagement } from './components/ModelManagement';
import { ResumeAgentPage } from './components/resume/ResumeAgentPage';
import { AICopyPage } from './components/AICopyPage';
import { JobAnalysisPage } from './components/JobAnalysisPage';
import { api, type TaskInfo } from './api/client';
import { useTasks } from './store/useTasks';

export default function App() {
  const { tasks, loading, refresh, selectedId, select, upsert } = useTasks();
  const [activeMenu, setActiveMenu] = useState('home');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [editing, setEditing] = useState<TaskInfo | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    refresh().catch((e) => setError(`后端连接失败：${e.message}`));
    const t = setInterval(() => { refresh().catch(() => {}); }, 5000);
    return () => clearInterval(t);
  }, [refresh]);

  useEffect(() => {
    const handler = () => setActiveMenu('accounts');
    window.addEventListener('navigate-model-management', handler);
    return () => window.removeEventListener('navigate-model-management', handler);
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
      <StatsGrid todaySent={todaySent} dailyLimit={dailyLimit} runningTasks={runningCount} totalTasks={tasks.length} />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 items-start">
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
        <ResumeAgentCard onNavigate={() => setActiveMenu('resume')} />
        <LogsPanel selectedTask={selected} />
        <QuickActions
          onCreateTask={() => { setEditing(null); setShowNew(true); }}
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
      case 'tasks': return renderTasks();
      case 'templates': return renderPlaceholder('话术模板', '管理招呼话术模板');
      case 'accounts': return <ModelManagement />;
      case 'ai-copy': return null;
      case 'job-analysis': return null;
      case 'system-settings': return renderPlaceholder('系统设置', '配置账号与偏好');
      default: return renderHome();
    }
  };

  return (
    <div className="h-full flex flex-col bg-surface-850">
      <TopNav />
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
