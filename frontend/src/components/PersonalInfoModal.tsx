import { useState, useEffect } from 'react';
import { User, Save, RotateCcw, Trash2, X, Plus } from 'lucide-react';

export const STORAGE_KEY = 'ai-greeting-personal-info';

export interface PersonalInfo {
  name: string;
  job_title: string;
  target_position: string;
  work_years: string;
  core_skills: string;
  project_experience: string;
  campus_experience: string;
  personal_advantages: string;
  other_info: string;
  honor_certificates: string[];
}

// 仅取字符串类型字段，供单行/多行文本框渲染使用
type StringInfoKey = {
  [K in keyof PersonalInfo]: PersonalInfo[K] extends string ? K : never;
}[keyof PersonalInfo];

export const EMPTY_INFO: PersonalInfo = {
  name: '', job_title: '', target_position: '', work_years: '',
  core_skills: '', project_experience: '', campus_experience: '', personal_advantages: '',
  other_info: '', honor_certificates: [],
};

export const INFO_FIELDS: { key: StringInfoKey; label: string; placeholder: string; multiline?: boolean }[] = [
  { key: 'name', label: '姓名', placeholder: '你的姓名' },
  { key: 'job_title', label: '求职岗位', placeholder: '如：全栈开发工程师' },
  { key: 'target_position', label: '目标岗位', placeholder: '如：AI全栈开发 / 后端工程师' },
  { key: 'work_years', label: '工作年限', placeholder: '如：5年' },
  { key: 'core_skills', label: '核心技能', placeholder: '多个技能用逗号分隔，如：Python, React, 大模型应用' },
  { key: 'project_experience', label: '项目经历', placeholder: '简述1-3个核心项目及成果...', multiline: true },
  { key: 'campus_experience', label: '校园经历', placeholder: '如：学生会干部、社团活动、志愿服务等校园经历...', multiline: true },
  { key: 'personal_advantages', label: '个人优势', placeholder: '如：快速学习能力、跨团队协作经验...', multiline: true },
  { key: 'other_info', label: '其他补充信息', placeholder: '任何想补充的信息...', multiline: true },
];

export function loadPersonalInfo(): PersonalInfo {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      return {
        ...EMPTY_INFO,
        ...parsed,
        honor_certificates: Array.isArray(parsed?.honor_certificates) ? parsed.honor_certificates : [],
      };
    }
  } catch { /* */ }
  return { ...EMPTY_INFO };
}

export function buildPersonalInfoText(): string {
  const info = loadPersonalInfo();
  const parts: string[] = [];
  if (info.name) parts.push(`姓名：${info.name}`);
  if (info.job_title) parts.push(`求职岗位：${info.job_title}`);
  if (info.target_position) parts.push(`目标岗位：${info.target_position}`);
  if (info.work_years) parts.push(`工作年限：${info.work_years}`);
  if (info.core_skills) parts.push(`核心技能：${info.core_skills}`);
  if (info.project_experience) parts.push(`项目经历：${info.project_experience}`);
  if (info.campus_experience) parts.push(`校园经历：${info.campus_experience}`);
  const certs = (info.honor_certificates || []).map(c => c.trim()).filter(Boolean);
  if (certs.length) parts.push(`荣誉证书：${certs.join('、')}`);
  if (info.personal_advantages) parts.push(`个人优势：${info.personal_advantages}`);
  if (info.other_info) parts.push(`其他信息：${info.other_info}`);
  return parts.join('\n');
}

export function PersonalInfoModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [info, setInfo] = useState<PersonalInfo>(EMPTY_INFO);
  const [toast, setToast] = useState('');

  useEffect(() => {
    if (open) setInfo(loadPersonalInfo());
  }, [open]);

  const showToast = (msg: string) => {
    setToast(msg);
    setTimeout(() => setToast(''), 2000);
  };

  const handleSave = () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(info));
    showToast('已保存到本地');
  };

  const handleLoad = () => {
    const saved = loadPersonalInfo();
    if (JSON.stringify(saved) === JSON.stringify(EMPTY_INFO)) {
      showToast('本地无已保存数据');
    } else {
      setInfo(saved);
      showToast('已读取本地数据');
    }
  };

  const handleClear = () => {
    if (!confirm('确认清空本地缓存？此操作不可恢复。')) return;
    localStorage.removeItem(STORAGE_KEY);
    setInfo({ ...EMPTY_INFO });
    showToast('本地缓存已清空');
  };

  const updateField = (key: StringInfoKey, value: string) => {
    setInfo(prev => ({ ...prev, [key]: value }));
  };

  const updateCert = (idx: number, value: string) => {
    setInfo(prev => {
      const list = [...prev.honor_certificates];
      list[idx] = value;
      return { ...prev, honor_certificates: list };
    });
  };

  const addCert = () => {
    setInfo(prev => ({ ...prev, honor_certificates: [...prev.honor_certificates, ''] }));
  };

  const removeCert = (idx: number) => {
    setInfo(prev => ({ ...prev, honor_certificates: prev.honor_certificates.filter((_, i) => i !== idx) }));
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={onClose}>
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" />
      <div
        className="relative w-full max-w-lg mx-4 bg-surface-800 border border-slate-700/60 rounded-2xl shadow-2xl animate-fade-in max-h-[85vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700/30 shrink-0">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-accent-blue/15 flex items-center justify-center">
              <User size={16} className="text-accent-blue" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-slate-200">个人信息</h3>
              <p className="text-[10px] text-slate-500 mt-0.5">数据仅保存在当前客户端，用于提升话术匹配度</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg text-slate-500 hover:text-slate-300 hover:bg-surface-700/50 transition-colors">
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto scrollbar-thin px-5 py-4 space-y-3">
          {INFO_FIELDS.map(f => (
            <div key={f.key}>
              <label className="block text-xs text-slate-400 mb-1">{f.label}</label>
              {f.multiline ? (
                <textarea
                  value={info[f.key]}
                  onChange={e => updateField(f.key, e.target.value)}
                  placeholder={f.placeholder}
                  rows={3}
                  className="w-full px-3 py-2 rounded-lg bg-surface-900/60 border border-slate-700/50 text-slate-200 text-sm resize-none focus:border-accent-blue/50 focus:outline-none focus:ring-1 focus:ring-accent-blue/30 placeholder:text-slate-600 scrollbar-thin"
                />
              ) : (
                <input
                  type="text"
                  value={info[f.key]}
                  onChange={e => updateField(f.key, e.target.value)}
                  placeholder={f.placeholder}
                  className="w-full px-3 py-2 rounded-lg bg-surface-900/60 border border-slate-700/50 text-slate-200 text-sm focus:border-accent-blue/50 focus:outline-none focus:ring-1 focus:ring-accent-blue/30 placeholder:text-slate-600"
                />
              )}
            </div>
          ))}

          <div>
            <label className="block text-xs text-slate-400 mb-1">荣誉证书</label>
            <div className="space-y-2">
              {info.honor_certificates.length === 0 && (
                <p className="text-[11px] text-slate-600">暂无荣誉证书，点击下方按钮添加</p>
              )}
              {info.honor_certificates.map((cert, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  <input
                    type="text"
                    value={cert}
                    onChange={e => updateCert(idx, e.target.value)}
                    placeholder="如：英语六级证书 / 全国大学生竞赛一等奖"
                    className="flex-1 px-3 py-2 rounded-lg bg-surface-900/60 border border-slate-700/50 text-slate-200 text-sm focus:border-accent-blue/50 focus:outline-none focus:ring-1 focus:ring-accent-blue/30 placeholder:text-slate-600"
                  />
                  <button
                    onClick={() => removeCert(idx)}
                    className="p-2 rounded-lg text-slate-500 hover:text-red-400 hover:bg-red-500/10 transition-colors shrink-0"
                    title="删除该证书"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              ))}
              <button
                onClick={addCert}
                className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-medium bg-accent-blue/10 text-accent-blue hover:bg-accent-blue/20 transition-colors"
              >
                <Plus size={12} /> 添加证书
              </button>
            </div>
          </div>
        </div>

        <div className="px-5 py-3 border-t border-slate-700/30 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-2">
            <button
              onClick={handleSave}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-accent-blue/15 text-accent-blue hover:bg-accent-blue/25 transition-colors"
            >
              <Save size={12} /> 保存本地
            </button>
            <button
              onClick={handleLoad}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-surface-700/40 text-slate-400 hover:text-slate-200 hover:bg-surface-700/60 transition-colors"
            >
              <RotateCcw size={12} /> 读取本地
            </button>
            <button
              onClick={handleClear}
              className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
            >
              <Trash2 size={12} /> 清空缓存
            </button>
          </div>
          {toast && (
            <span className="text-xs text-green-400 animate-fade-in">{toast}</span>
          )}
        </div>
      </div>
    </div>
  );
}
