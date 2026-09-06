import { MessageCircle, Play } from 'lucide-react';

interface Props {
  todaySent: number;
  dailyLimit: number;
  runningTasks: number;
  totalTasks: number;
}

export function StatsGrid({ todaySent, dailyLimit, runningTasks, totalTasks }: Props) {
  const stats = [
    {
      label: '今日招呼',
      value: `${todaySent}`,
      suffix: `/ ${dailyLimit}`,
      icon: <MessageCircle size={18} />,
      sub: '账号数',
      subValue: `${totalTasks}`,
      color: 'from-brand-500 to-cyan-400',
      iconBg: 'bg-brand-500/15 text-brand-400',
    },
    {
      label: '运行中任务',
      value: `${runningTasks}`,
      suffix: '个任务',
      icon: <Play size={18} />,
      sub: '全部任务',
      subValue: `${totalTasks}`,
      color: 'from-emerald-500 to-teal-400',
      iconBg: 'bg-emerald-500/15 text-emerald-400',
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 animate-slide-up" style={{ animationDelay: '80ms' }}>
      {stats.map((s, i) => (
        <div key={i} className="card card-lift p-3.5 relative overflow-hidden">
          <div className={`absolute top-0 left-0 right-0 h-0.5 bg-gradient-to-r ${s.color} opacity-60`} />
          <div className="flex items-start justify-between mb-2">
            <span className="text-xs text-slate-400">{s.label}</span>
            <div className={`w-7 h-7 rounded-lg ${s.iconBg} flex items-center justify-center`}>
              {s.icon}
            </div>
          </div>
          <div className="flex items-baseline gap-1">
            <span className="text-2xl font-bold text-slate-100 tabular-nums">{s.value}</span>
            <span className="text-xs text-slate-500">{s.suffix}</span>
          </div>
          <div className="mt-1.5 flex items-center gap-1 text-[11px] text-slate-500">
            <span>{s.sub}</span>
            <span className="text-slate-400 font-medium">{s.subValue}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
