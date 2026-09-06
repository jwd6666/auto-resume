import { useState } from 'react';
import { Sparkles, Loader2, X, AlertTriangle, Palette } from 'lucide-react';
import { Modal } from './ui';
import { ACCENTS } from './editor/render';
import { agentApi, type Job } from '../../api/agentApi';

interface Props {
  open: boolean;
  onClose: () => void;
  job: Job | null;
  onGenerated: (resume: any) => void;
}

const PLACEHOLDER = `姓名：张三
求职意向：Python后端开发工程师
电话：138xxxx1234
邮箱：zhangsan@email.com
城市：北京

个人简介：
5年Python后端开发经验，擅长高并发系统设计与微服务架构，有大型项目从0到1经验。

工作经历：
XX科技有限公司 | Python高级工程师 | 2021.06 - 至今
• 主导用户中心微服务重构，QPS从500提升至5000，P99延迟降低60%
• 设计并实现分布式任务调度系统，日均处理200万+任务零丢失
• 搭建统一监控告警平台，故障发现时间从30分钟缩短至3分钟

YY互联网公司 | 后端开发工程师 | 2019.07 - 2021.05
• 负责核心交易系统开发，支撑日均50万笔交易
• 优化数据库查询性能，慢查询数量减少80%

教育经历：
XX大学 | 计算机科学与技术 | 本科 | 2015.09 - 2019.06

核心技能：
Python / FastAPI / Django / Redis / MySQL / Docker / Kubernetes / Kafka`;

export function GenerateResumeModal({ open, onClose, job, onGenerated }: Props) {
  const [background, setBackground] = useState('');
  const [accent, setAccent] = useState(ACCENTS[0]);
  const [generating, setGenerating] = useState(false);
  const [progress, setProgress] = useState('');
  const [error, setError] = useState('');

  const handleGenerate = async () => {
    if (!job) return;
    const text = background.trim();
    if (!text) { setError('请输入候选人背景信息'); return; }

    setGenerating(true);
    setError('');
    setProgress('AI 正在生成简历，请稍候（约 1-2 分钟）…');

    try {
      const resume = await agentApi.generateResume(job.id, text, 'classic', accent);
      setProgress('');
      onGenerated(resume);
      onClose();
      setBackground('');
    } catch (e: any) {
      setError(e.message || '生成失败，请重试');
      setProgress('');
    } finally {
      setGenerating(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={generating ? () => {} : onClose}
      title="AI 生成简历"
      icon={<Sparkles size={15} className="text-accent-purple" />}
      badge={job?.title}
    >
      <div className="space-y-4">
        <div>
          <label className="text-xs text-slate-400 mb-1.5 block">
            候选人背景信息 <span className="text-red-400">*</span>
          </label>
          <textarea
            value={background}
            onChange={e => setBackground(e.target.value)}
            placeholder={PLACEHOLDER}
            rows={14}
            className="w-full bg-surface-900/60 border border-slate-700/50 rounded-md px-3 py-2 text-sm text-slate-200 placeholder-slate-600/50 focus:border-accent-blue/50 focus:outline-none resize-none font-mono text-[12px] leading-relaxed scrollbar-thin"
            disabled={generating}
          />
          <p className="text-[11px] text-slate-600 mt-1">
            请输入候选人的真实信息：姓名、联系方式、工作经历、项目经历、教育经历、技能等。AI 会根据目标岗位 JD 生成针对性简历。
          </p>
        </div>

        <div>
          <label className="text-xs text-slate-400 mb-2 flex items-center gap-1.5">
            <Palette size={12} /> 主题色
          </label>
          <div className="flex items-center gap-3">
            {ACCENTS.map(a => (
              <button
                key={a}
                onClick={() => setAccent(a)}
                disabled={generating}
                className={`relative w-6 h-6 rounded-full transition-all hover:scale-110 disabled:opacity-40 ${
                  accent === a ? 'ring-2 ring-white/80 ring-offset-2 ring-offset-surface-800 scale-110' : ''
                }`}
                style={{ backgroundColor: a }}
              >
                {accent === a && (
                  <svg className="absolute inset-0 m-auto w-3 h-3 text-white drop-shadow" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                )}
              </button>
            ))}
          </div>
        </div>

        {progress && (
          <div className="px-3 py-2.5 rounded-lg bg-accent-purple/10 border border-accent-purple/25 flex items-center gap-2 animate-fade-in">
            <Loader2 size={14} className="animate-spin text-accent-purple" />
            <span className="text-xs text-accent-purple">{progress}</span>
          </div>
        )}

        {error && (
          <div className="px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 flex items-start gap-2">
            <AlertTriangle size={14} className="text-red-400 shrink-0 mt-0.5" />
            <p className="text-xs text-red-300/90 flex-1">{error}</p>
            <button onClick={() => setError('')} className="text-red-400 hover:text-red-300"><X size={14} /></button>
          </div>
        )}

        <div className="flex gap-2 justify-end pt-2 border-t border-slate-700/30">
          <button
            onClick={onClose}
            disabled={generating}
            className="px-3.5 py-1.5 text-xs text-slate-400 hover:text-slate-200 rounded-md hover:bg-slate-700/40 disabled:opacity-40 transition-colors"
          >
            取消
          </button>
          <button
            onClick={handleGenerate}
            disabled={generating || !background.trim() || !job}
            className="flex items-center gap-1.5 px-4 py-1.5 text-xs bg-accent-purple text-white rounded-md hover:bg-accent-purple/85 disabled:opacity-40 transition-colors"
          >
            {generating ? <><Loader2 size={13} className="animate-spin" /> 生成中…</> : <><Sparkles size={13} /> 生成简历</>}
          </button>
        </div>
      </div>
    </Modal>
  );
}
