import { useEffect, useState } from 'react';
import { Sparkles, Loader2, AlertTriangle, X, LayoutTemplate, ChevronRight, UserCircle, Pencil } from 'lucide-react';
import { agentApi, type Job, type Resume } from '../../api/agentApi';
import { BackgroundProfileModal, parseProfileContent, serializeProfileForm, type BackgroundProfileForm } from './BackgroundProfileModal';

interface Props {
  job: Job | null;
  onGenerated: (resume: Resume) => void;
  visible: boolean;
  onClose: () => void;
}

const LAYOUT_OPTIONS = [
  { id: 'classic', name: '经典双栏', desc: '深色侧边栏 + 白色主区' },
  { id: 'modern', name: '极简单栏', desc: '黑白灰配色 + 细横线分隔' },
  { id: 'minimal', name: '极清单栏', desc: '单栏居中大量留白' },
  { id: 'creative', name: '创意侧边栏', desc: '顶部色带 + 下双栏' },
  { id: 'table', name: '表格版式', desc: 'table 布局 + 正式商务风' },
  { id: 'timeline', name: '时间轴', desc: '轴线节点串联各段经历' },
];

const LAYOUT_ACCENT = '#2563eb';

/** 迷你页面缩略图：用色块线条直观展示各布局的排版风格 */
function LayoutThumb({ id }: { id: string }) {
  const line = (w: number | string, c = '#cbd5e1') => (
    <div key={`${c}-${w}`} style={{ width: w, height: 1.5, backgroundColor: c, borderRadius: 1 }} />
  );
  return (
    <div className="w-[30px] h-[40px] rounded-[3px] border border-slate-600/40 overflow-hidden shrink-0 bg-white flex shadow-sm">
      {id === 'classic' && (
        <>
          <div className="h-full flex flex-col gap-[3px] p-[3px]" style={{ width: 11, background: 'linear-gradient(160deg,#0d1b2a,#1b3a5c)' }}>
            <div className="w-[5px] h-[5px] rounded-full" style={{ border: `1px solid ${LAYOUT_ACCENT}` }} />
            {line('100%', '#5b7085')}
            {line('80%', '#5b7085')}
          </div>
          <div className="flex-1 flex flex-col gap-[3px] p-[3px]">
            {line('90%')}
            {line('70%')}
            {line('80%')}
          </div>
        </>
      )}
      {id === 'modern' && (
        <div className="flex-1 h-full flex flex-col items-center justify-center gap-[3px] px-[4px]">
          <div style={{ width: 12, height: 3, backgroundColor: '#334155', borderRadius: 1 }} />
          {line('85%')}
          {line('60%')}
          <div style={{ width: '90%', height: 1, backgroundColor: '#e2e8f0' }} />
          {line('75%')}
        </div>
      )}
      {id === 'minimal' && (
        <div className="flex-1 h-full flex flex-col items-center justify-center gap-[4px] px-[4px]">
          {line('60%', '#94a3b8')}
          <div style={{ width: 10, height: 1, backgroundColor: LAYOUT_ACCENT }} />
          {line('80%')}
          {line('70%')}
        </div>
      )}
      {id === 'creative' && (
        <div className="flex-1 h-full flex flex-col">
          <div className="w-full" style={{ height: 11, backgroundColor: LAYOUT_ACCENT }} />
          <div className="flex-1 flex">
            <div className="h-full" style={{ width: '40%', backgroundColor: '#e5e7eb' }} />
            <div className="flex-1 flex flex-col gap-[3px] p-[3px]">
              {line('85%')}
              {line('60%')}
            </div>
          </div>
        </div>
      )}
      {id === 'table' && (
        <div className="flex-1 h-full flex flex-col gap-[1.5px] p-[2.5px]" style={{ backgroundColor: '#94a3b8' }}>
          <div style={{ height: 7, backgroundColor: '#1e293b' }} />
          <div className="flex gap-[1.5px]" style={{ height: 5 }}>
            <div className="flex-1" style={{ backgroundColor: '#fff' }} />
            <div className="flex-1" style={{ backgroundColor: '#fff' }} />
            <div className="flex-1" style={{ backgroundColor: '#fff' }} />
          </div>
          <div className="flex-1 flex flex-col gap-[1.5px]">
            <div className="flex-1" style={{ backgroundColor: '#fff' }} />
            <div className="flex-1" style={{ backgroundColor: '#fff' }} />
          </div>
        </div>
      )}
      {id === 'timeline' && (
        <div className="flex-1 h-full flex flex-col px-[5px] py-[4px]">
          <div className="self-center" style={{ width: 12, height: 2.5, backgroundColor: '#334155', borderRadius: 1 }} />
          <div className="relative flex-1 mt-[3px]">
            <div className="absolute top-0 bottom-0" style={{ left: 2, width: 1.5, backgroundColor: '#94a3b8' }} />
            {[6, 40, 74].map(top => (
              <div key={top} className="absolute flex items-center gap-[3px]" style={{ top: `${top}%`, left: 0 }}>
                <div className="shrink-0 rounded-full" style={{ width: 5, height: 5, backgroundColor: LAYOUT_ACCENT }} />
                <div style={{ width: '70%', height: 1.5, backgroundColor: '#cbd5e1', borderRadius: 1 }} />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export function GenerateResumeInline({ job, onGenerated, visible, onClose }: Props) {
  const [profile, setProfile] = useState<BackgroundProfileForm | null>(null);
  const [profileOpen, setProfileOpen] = useState(false);
  const [layout, setLayout] = useState('classic');
  const [generating, setGenerating] = useState(false);
  const [progress, setProgress] = useState('');
  const [error, setError] = useState('');
  const [collapsed, setCollapsed] = useState(false);

  // 载入个人背景档案，回显到表单摘要
  useEffect(() => {
    if (!visible) return;
    agentApi.listBackgrounds().then(profiles => {
      if (profiles.length > 0) setProfile(parseProfileContent(profiles[0].content || ''));
    }).catch(() => {});
  }, [visible]);

  const handleSaveProfile = async (content: string) => {
    setProfile(parseProfileContent(content));
    setProfileOpen(false);
    try {
      const profiles = await agentApi.listBackgrounds();
      if (profiles.length > 0) {
        await agentApi.updateBackground(profiles[0].id, { content });
      } else {
        await agentApi.createBackground({ name: '默认', content });
      }
    } catch { /* */ }
  };

  if (!visible) return null;

  const handleGenerate = async () => {
    if (!job) return;
    setGenerating(true);
    setError('');
    setProgress('AI 正在生成简历，请稍候（约 1-2 分钟）…');

    try {
      const resume = await agentApi.generateResume(job.id, profile ? serializeProfileForm(profile) : '', layout);
      setProgress('');
      onGenerated(resume);
      setCollapsed(true);
    } catch (e: any) {
      setError(e.message || '生成失败，请重试');
      setProgress('');
    } finally {
      setGenerating(false);
    }
  };

  if (collapsed) {
    return (
      <button
        onClick={() => setCollapsed(false)}
        className="absolute left-0 top-1/2 -translate-y-1/2 z-10 bg-accent-purple/20 hover:bg-accent-purple/30 border border-accent-purple/30 rounded-r-lg px-1 py-3 text-accent-purple transition-colors"
        title="展开生成简历面板"
      >
        <ChevronRight size={14} />
      </button>
    );
  }

  return (
    <div className="absolute right-0 top-0 bottom-0 w-[320px] min-w-[280px] shrink-0 flex flex-col bg-surface-800/95 backdrop-blur-sm border-l border-slate-700/30 z-20 shadow-2xl">
      <div className="flex items-center justify-between px-3 py-2 border-b border-slate-700/30">
        <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-200">
          <Sparkles size={13} className="text-accent-purple" /> AI 生成简历
          {job && <span className="text-[10px] px-1 py-0.5 rounded bg-accent-blue/15 text-accent-blue font-normal">{job.title}</span>}
        </span>
        <button onClick={onClose} className="text-slate-500 hover:text-slate-300 p-1 rounded hover:bg-slate-700/40 transition-colors">
          <X size={14} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto scrollbar-thin p-3 space-y-3">
        <div>
          <label className="text-[11px] text-slate-400 mb-1 block">
            候选人背景 <span className="text-slate-600">（可选，点击填写）</span>
          </label>
          <button
            onClick={() => setProfileOpen(true)}
            disabled={generating}
            className="w-full text-left bg-surface-900/60 border border-slate-700/50 hover:border-accent-purple/40 rounded-md px-2.5 py-2 transition-colors disabled:opacity-40 group"
          >
            {profile && (profile.name.trim() || profile.projects.trim() || profile.education.trim() || profile.campus.trim() || profile.work.trim() || profile.skills.trim() || profile.summary.trim()) ? (
              <div className="space-y-1">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1 text-[11px] text-accent-purple"><UserCircle size={11} /> 个人背景档案</span>
                  <Pencil size={10} className="text-slate-600 group-hover:text-slate-400" />
                </div>
                <div className="flex flex-wrap gap-x-2 gap-y-0.5 text-[10px] text-slate-400">
                  {([['姓名', profile.name], ['性别', profile.gender], ['电话', profile.phone], ['邮箱', profile.email], ['籍贯', profile.hometown], ['意向', profile.intent]] as const)
                    .filter(([, v]) => v.trim())
                    .map(([k, v]) => <span key={k}><span className="text-slate-600">{k}</span> {v}</span>)}
                </div>
                {([['教育背景', profile.education], ['校园经历', profile.campus], ['工作经历', profile.work], ['项目经历', profile.projects], ['专业技能', profile.skills], ['自我评价', profile.summary]] as const)
                  .filter(([, v]) => v.trim())
                  .map(([k, v]) => (
                    <p key={k} className="text-[10px] text-slate-500">
                      <span className="text-slate-600">{k}：</span><span className="line-clamp-1 whitespace-pre-line">{v.trim()}</span>
                    </p>
                  ))}
              </div>
            ) : (
              <span className="flex items-center gap-1.5 text-[11px] text-slate-600">
                <UserCircle size={11} /> 填写个人信息、教育/工作/项目经历等（均选填）
              </span>
            )}
          </button>
        </div>

        <div>
          <label className="text-[11px] text-slate-400 mb-1 flex items-center gap-1">
            <LayoutTemplate size={11} /> 简历布局
          </label>
          <div className="grid grid-cols-2 gap-1.5">
            {LAYOUT_OPTIONS.map(lo => {
              const active = layout === lo.id;
              return (
                <button
                  key={lo.id}
                  onClick={() => setLayout(lo.id)}
                  disabled={generating}
                  className={`relative flex items-center gap-2 rounded-lg border p-2 text-left transition-all disabled:opacity-40 ${
                    active
                      ? 'border-accent-purple bg-accent-purple/10 ring-1 ring-accent-purple/40'
                      : 'border-slate-700/50 bg-surface-900/40 hover:border-slate-600/60 hover:bg-surface-900/60'
                  }`}
                >
                  <LayoutThumb id={lo.id} />
                  <div className="min-w-0">
                    <p className={`text-[11px] font-medium ${active ? 'text-accent-purple' : 'text-slate-300'}`}>{lo.name}</p>
                    <p className="text-[9px] text-slate-600 leading-tight mt-0.5">{lo.desc}</p>
                  </div>
                  {active && (
                    <div className="absolute top-1 right-1 w-3 h-3 rounded-full bg-accent-purple flex items-center justify-center">
                      <svg className="w-2 h-2 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="20 6 9 17 4 12" />
                      </svg>
                    </div>
                  )}
                </button>
              );
            })}
          </div>
        </div>

        {progress && (
          <div className="px-2.5 py-2 rounded-lg bg-accent-purple/10 border border-accent-purple/25 flex items-center gap-2">
            <Loader2 size={12} className="animate-spin text-accent-purple" />
            <span className="text-[11px] text-accent-purple">{progress}</span>
          </div>
        )}

        {error && (
          <div className="px-2.5 py-2 rounded-lg bg-red-500/10 border border-red-500/30 flex items-start gap-2">
            <AlertTriangle size={12} className="text-red-400 shrink-0 mt-0.5" />
            <p className="text-[11px] text-red-300/90 flex-1">{error}</p>
            <button onClick={() => setError('')} className="text-red-400 hover:text-red-300"><X size={12} /></button>
          </div>
        )}
      </div>

      <div className="shrink-0 px-3 py-2 border-t border-slate-700/30">
        <button
          onClick={handleGenerate}
          disabled={generating || !job}
          className="w-full flex items-center justify-center gap-1.5 px-3 py-1.5 text-xs bg-accent-purple text-white rounded-md hover:bg-accent-purple/85 disabled:opacity-40 transition-colors"
        >
          {generating ? <><Loader2 size={12} className="animate-spin" /> 生成中…</> : <><Sparkles size={12} /> 生成简历</>}
        </button>
      </div>

      <BackgroundProfileModal
        open={profileOpen}
        onClose={() => setProfileOpen(false)}
        content={profile ? serializeProfileForm(profile) : ''}
        onSave={handleSaveProfile}
      />
    </div>
  );
}
