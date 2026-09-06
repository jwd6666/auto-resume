/** 简历 Agent 共享 UI 组件与工具函数 */
import { useEffect, useRef, useState } from 'react';
import { ChevronDown, MoreVertical, X } from 'lucide-react';

export function Modal({ open, onClose, title, icon, badge, children }: {
  open: boolean; onClose: () => void; title: string; icon?: React.ReactNode; badge?: string; children: React.ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" />
      <div
        className="relative bg-surface-800 border border-slate-700/60 rounded-xl shadow-2xl w-[560px] max-w-[92vw] max-h-[80vh] flex flex-col animate-fade-in"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-700/30 shrink-0">
          <span className="flex items-center gap-2 text-sm font-semibold text-slate-200">
            {icon} {title}
            {badge && <span className="text-[10px] px-1.5 py-0.5 rounded bg-accent-blue/15 text-accent-blue font-normal">{badge}</span>}
          </span>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300 p-1 rounded hover:bg-slate-700/40 transition-colors">
            <X size={16} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto scrollbar-thin px-5 py-4 min-h-0">
          {children}
        </div>
      </div>
    </div>
  );
}

export function Switch({ checked, onChange, disabled }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button
      onClick={e => { e.stopPropagation(); if (!disabled) onChange(!checked); }}
      className={`relative w-9 h-5 rounded-full transition-colors shrink-0 ${checked ? 'bg-accent-blue' : 'bg-slate-600/60'} ${disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
      title={checked ? '已启用' : '已停用'}
    >
      <span className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all ${checked ? 'left-[18px]' : 'left-0.5'}`} />
    </button>
  );
}

export interface MenuItem { label: string; danger?: boolean; onClick: () => void; }

export function DotMenu({ items }: { items: MenuItem[] }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  return (
    <div className="relative shrink-0" ref={ref} onClick={e => e.stopPropagation()}>
      <button
        onClick={() => setOpen(o => !o)}
        className={`p-1 rounded transition-colors ${open ? 'bg-slate-600/50 text-slate-200' : 'text-slate-500 hover:text-slate-300 hover:bg-slate-600/40'}`}
      >
        <MoreVertical size={14} />
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 flex flex-col bg-surface-700 border border-slate-600/50 rounded-md shadow-xl z-30 min-w-[110px] py-1 animate-fade-in">
          {items.map(it => (
            <button
              key={it.label}
              onClick={() => { setOpen(false); it.onClick(); }}
              className={`px-3 py-1.5 text-xs text-left transition-colors ${it.danger ? 'text-red-400 hover:bg-red-500/15' : 'text-slate-300 hover:bg-slate-600/50'}`}
            >
              {it.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function CollapseHeader({ icon, title, badge, collapsed, onToggle }: {
  icon: React.ReactNode; title: string; badge?: string; collapsed: boolean; onToggle: () => void;
}) {
  return (
    <button
      onClick={onToggle}
      className="w-full flex items-center justify-between px-3.5 py-2.5 hover:bg-surface-700/30 transition-colors rounded-t-xl"
    >
      <span className="flex items-center gap-2 text-sm font-semibold text-slate-200">
        {icon} {title}
        {badge && <span className="text-[10px] px-1.5 py-0.5 rounded bg-accent-blue/15 text-accent-blue font-normal">{badge}</span>}
      </span>
      <ChevronDown size={15} className={`text-slate-500 transition-transform ${collapsed ? '-rotate-90' : ''}`} />
    </button>
  );
}

export function formatBytes(n?: number | null): string {
  if (n == null || isNaN(n)) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

export function formatDateTime(iso?: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  const p = (x: number) => String(x).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

const SKILL_DICT = [
  'Node.js', 'Element Plus', 'Ant Design', 'uni-app', 'CI/CD', 'C++',
  'HTML', 'CSS', 'JavaScript', 'TypeScript', 'Vue', 'React', 'Webpack', 'Vite',
  'Pinia', 'Redux', 'ECharts', 'Tailwind', 'Git', 'Docker', 'Kubernetes',
  'Python', 'Java', 'Go', 'SQL', 'MySQL', 'PostgreSQL', 'Redis', 'MongoDB',
  'TensorFlow', 'PyTorch', 'Spring', 'Django', 'FastAPI', 'Flutter', 'Electron',
  'GraphQL', 'WebSocket', 'Linux', 'Nginx', 'Jenkins', 'Spark', 'Flink', 'Hadoop',
  '机器学习', '深度学习', '大模型', 'NLP', 'LLM', 'RAG', '微服务', '小程序',
  '性能优化', '工程化', '单元测试', 'Rust',
];

export function extractSkillTags(text: string, max = 6): string[] {
  if (!text) return [];
  const hits: string[] = [];
  for (const kw of SKILL_DICT) {
    if (hits.length >= max) break;
    const found = /[\u4e00-\u9fa5]/.test(kw)
      ? text.includes(kw)
      : new RegExp(`\\b${kw.replace(/[.+/]/g, m => '\\' + m)}\\b`, 'i').test(text);
    if (found) hits.push(kw);
  }
  return hits.filter(h => !(h === 'Node' && hits.includes('Node.js')));
}
