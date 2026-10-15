import clsx from 'clsx';
import {
  Home, ListTodo, Users,
  Sparkles, Wand2, BarChart3, Plus, Settings,
  PanelLeftClose, PanelLeftOpen,
  Briefcase, Building2,
} from 'lucide-react';

interface MenuItem {
  icon: React.ReactNode;
  label: string;
  id: string;
  badge?: 'new';
}

interface MenuGroup {
  title: string;
  badge?: string;
  items: MenuItem[];
}

const groups: MenuGroup[] = [
  {
    title: '',
    items: [
      { icon: <Home size={17} />, label: '首页概览', id: 'home' },
    ],
  },
  {
    title: '自动招呼',
    items: [
      { icon: <ListTodo size={17} />, label: '任务管理', id: 'tasks' },
      { icon: <Briefcase size={17} />, label: '岗位管理', id: 'job-manage' },
      { icon: <Users size={17} />, label: '模型管理', id: 'accounts' },
    ],
  },
  {
    title: '平台',
    items: [
      { icon: <Building2 size={17} />, label: 'BOSS配置', id: 'boss-config' },
    ],
  },
  {
    title: '智能工具',
    badge: 'BETA',
    items: [
      { icon: <Sparkles size={17} />, label: '简历优化 Agent', id: 'resume', badge: 'new' },
      { icon: <Wand2 size={17} />, label: 'AI 话术生成', id: 'ai-copy', badge: 'new' },
      { icon: <BarChart3 size={17} />, label: '职位分析', id: 'job-analysis', badge: 'new' },
    ],
  },
  {
    title: '系统',
    items: [
      { icon: <Settings size={17} />, label: '系统设置', id: 'system-settings' },
    ],
  },
];

interface Props {
  active: string;
  onSelect: (id: string) => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
}

export function Sidebar({ active, onSelect, collapsed, onToggleCollapse }: Props) {
  return (
    <aside
      className={clsx(
        'shrink-0 border-r border-slate-800/80 bg-surface-850/50 flex flex-col sidebar-transition',
        collapsed ? 'w-16' : 'w-56',
      )}
    >
      {/* Toggle button */}
      <div className={clsx('shrink-0 py-3 px-2 flex items-center', collapsed ? 'justify-center' : 'justify-end')}>
        <button
          onClick={onToggleCollapse}
          className="p-1.5 rounded-md text-slate-500 hover:text-slate-300 hover:bg-slate-800/60 transition-colors"
          title={collapsed ? '展开侧边栏' : '收起侧边栏'}
        >
          {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
        </button>
      </div>

      {/* Menu */}
      <nav className="flex-1 overflow-y-auto scrollbar-thin px-2 space-y-4">
        {groups.map((group, gi) => (
          <div key={gi}>
            {group.title && (
              <div className={clsx('mb-1.5 flex items-center gap-1.5 sidebar-label-row', collapsed ? 'justify-center px-0' : 'px-3')}>
                {!collapsed && (
                  <>
                    <span className="text-[11px] font-medium text-slate-500 uppercase tracking-wider">
                      {group.title}
                    </span>
                    {group.badge && (
                      <span className="px-1 py-0.5 rounded bg-slate-700/80 text-[9px] font-bold text-slate-300">
                        {group.badge}
                      </span>
                    )}
                  </>
                )}
              </div>
            )}
            <div className="space-y-0.5">
              {group.items.map((item) => (
                <div
                  key={item.id}
                  onClick={() => onSelect(item.id)}
                  className={clsx('nav-item', active === item.id && 'active', collapsed && 'nav-item-collapsed')}
                  title={collapsed ? item.label : undefined}
                >
                  <span className="shrink-0">{item.icon}</span>
                  {!collapsed && (
                    <>
                      <span className="flex-1 truncate">{item.label}</span>
                      {item.badge === 'new' && (
                        <span className="badge-new shrink-0">新</span>
                      )}
                    </>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </nav>

      {/* Upgrade module */}
      <div className={clsx('border-t border-slate-800/80', collapsed ? 'p-2' : 'p-3')}>
        {collapsed ? (
          <div className="flex flex-col items-center gap-1">
            <Plus size={16} className="text-brand-400" />
            <button className="btn-upgrade text-[10px] py-1 px-2">Pro</button>
          </div>
        ) : (
          <div className="card p-3.5 relative overflow-hidden">
            <div className="absolute -top-6 -right-6 w-20 h-20 rounded-full bg-gradient-to-br from-brand-500/20 to-purple-500/20 blur-2xl" />
            <div className="relative">
              <div className="flex items-center gap-1.5 mb-1">
                <Plus size={14} className="text-brand-400" />
                <span className="text-sm font-semibold text-gradient">升级到Pro版</span>
              </div>
              <p className="text-[11px] text-slate-400 mb-3 leading-relaxed">
                解锁更多高级功能，AI 不限量
              </p>
              <button className="w-full btn-upgrade text-xs py-1.5">
                立即升级
              </button>
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}
