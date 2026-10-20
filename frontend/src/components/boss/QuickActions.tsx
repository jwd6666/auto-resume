import { Plus, Sparkles, Settings } from 'lucide-react';

interface Props {
  onCreateTask: () => void;
  onAICopy: () => void;
  onSystemSettings: () => void;
}

export function QuickActions({ onCreateTask, onAICopy, onSystemSettings }: Props) {
  const actions = [
    {
      icon: <Plus size={20} />,
      label: '创建新任务',
      desc: '快速创建招呼任务',
      onClick: onCreateTask,
      gradient: 'from-brand-500 to-cyan-400',
      bgGradient: 'from-brand-500/10 to-cyan-500/5',
    },
    {
      icon: <Sparkles size={20} />,
      label: 'AI话术生成',
      desc: 'AI智能生成招呼话术',
      onClick: onAICopy,
      gradient: 'from-purple-500 to-pink-400',
      bgGradient: 'from-purple-500/10 to-pink-500/5',
    },
    {
      icon: <Settings size={20} />,
      label: '系统设置',
      desc: '配置账号与偏好',
      onClick: onSystemSettings,
      gradient: 'from-amber-500 to-orange-400',
      bgGradient: 'from-amber-500/10 to-orange-500/5',
    },
  ];

  return (
    <div className="card card-lift p-4 flex flex-col animate-slide-up" style={{ animationDelay: '180ms' }}>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-slate-200">快捷操作</h3>
        <span className="text-[11px] text-slate-500">常用功能</span>
      </div>

      <div className="grid grid-cols-2 gap-2 flex-1">
        {actions.map((action, i) => (
          <button
            key={i}
            onClick={action.onClick}
            className={`group relative overflow-hidden p-3 rounded-xl border border-slate-700/40 bg-gradient-to-br ${action.bgGradient} hover:border-slate-600/60 text-left`}
          >
            <div className={`absolute -top-4 -right-4 w-16 h-16 rounded-full bg-gradient-to-br ${action.gradient} opacity-10 blur-xl group-hover:opacity-20`} />
            <div className="relative">
              <div className={`w-9 h-9 rounded-lg bg-gradient-to-br ${action.gradient} flex items-center justify-center text-white shadow-lg mb-2 group-hover:scale-105`}>
                {action.icon}
              </div>
              <div className="text-sm font-medium text-slate-200 group-hover:text-white">
                {action.label}
              </div>
              <div className="text-[11px] text-slate-500 mt-0.5">
                {action.desc}
              </div>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
