/** 评估面板 — AI 生成评分卡 + 导出 */
import { useState } from 'react';
import { Gauge, Loader2, FileDown, Star } from 'lucide-react';
import { agentApi, type Job, type Resume, type Scorecard } from '../../api/agentApi';

interface Props {
  job: Job | null;
  resume: Resume | null;
}

export function EvaluationPanel({ job, resume }: Props) {
  const [scorecard, setScorecard] = useState<Scorecard | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleGenerate = async () => {
    if (!job || !resume) return;
    setLoading(true);
    setError(null);
    setScorecard(null);
    try {
      const result = await agentApi.generateScorecard({
        job_id: job.id,
        resume_id: resume.id,
      });
      setScorecard(result);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  if (!job || !resume) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center">
        <div className="w-14 h-14 rounded-2xl bg-slate-800/60 flex items-center justify-center mb-3">
          <Gauge size={20} className="text-slate-600" />
        </div>
        <p className="text-sm text-slate-500">请先选择岗位和简历</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-1.5">
          <Gauge size={15} /> 匹配度评估
        </h3>
        <button
          onClick={handleGenerate}
          disabled={loading}
          className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md bg-accent-blue/20 text-accent-blue hover:bg-accent-blue/30 disabled:opacity-50"
        >
          {loading ? <Loader2 size={13} className="animate-spin" /> : <Star size={13} />}
          {loading ? '分析中...' : '生成评分卡'}
        </button>
      </div>

      {error && (
        <div className="mb-3 px-3 py-2 rounded-md bg-red-500/10 text-red-400 text-xs">
          {error}
        </div>
      )}

      <div className="flex-1 overflow-y-auto scrollbar-thin">
        {!scorecard && !loading && (
          <div className="flex flex-col items-center justify-center py-8 text-center">
            <p className="text-xs text-slate-600">AI 将分析简历与 JD 的匹配度</p>
            <p className="text-xs text-slate-600 mt-1">生成能力项评分 + 证据引用 + 改进建议</p>
          </div>
        )}

        {scorecard && (
          <div className="space-y-3 animate-fade-in">
            {/* 总分 */}
            <div className="card p-4 text-center">
              <p className="text-xs text-slate-500 mb-1">综合评分</p>
              <p className={`text-3xl font-bold ${
                scorecard.overall_score >= 75 ? 'text-green-400' :
                scorecard.overall_score >= 50 ? 'text-amber-400' : 'text-red-400'
              }`}>
                {scorecard.overall_score}
                <span className="text-lg text-slate-500">/100</span>
              </p>
              <p className="text-xs text-slate-400 mt-2 max-w-md">{scorecard.overall_summary}</p>
            </div>

            {/* 能力项 */}
            {scorecard.items.map((item, i) => (
              <div key={i} className="card p-3">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-slate-200">{item.competency}</span>
                    <span className={`text-xs px-1.5 py-0.5 rounded ${
                      item.confidence === '高' ? 'bg-green-500/15 text-green-400' :
                      item.confidence === '中' ? 'bg-amber-500/15 text-amber-400' :
                      'bg-slate-500/15 text-slate-400'
                    }`}>{item.confidence}</span>
                  </div>
                  <span className={`text-lg font-bold ${
                    item.score >= 75 ? 'text-green-400' :
                    item.score >= 50 ? 'text-amber-400' : 'text-red-400'
                  }`}>{item.score}</span>
                </div>
                <p className="text-xs text-slate-400 mb-2">{item.summary}</p>
                {item.evidence.length > 0 && (
                  <div className="space-y-1 mb-2">
                    {item.evidence.map((ev, j) => (
                      <div key={j} className="text-xs text-slate-500 pl-2 border-l-2 border-slate-700">
                        <span className="text-slate-600">[{ev.source}]</span> {ev.quote}
                        {ev.why && <span className="text-slate-600"> → {ev.why}</span>}
                      </div>
                    ))}
                  </div>
                )}
                <div className="flex gap-3">
                  {item.gap && (
                    <p className="text-xs text-amber-400/70">⚠ {item.gap}</p>
                  )}
                  {item.suggestion && (
                    <p className="text-xs text-accent-blue/70">💡 {item.suggestion}</p>
                  )}
                </div>
              </div>
            ))}

            {/* 需验证 */}
            {scorecard.needs_verification.length > 0 && (
              <div className="card p-3 border-amber-500/20">
                <p className="text-xs font-medium text-amber-400 mb-1.5">需要候选人验证的点</p>
                <ul className="space-y-1">
                  {scorecard.needs_verification.map((v, i) => (
                    <li key={i} className="text-xs text-slate-400">• {v}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* 导出 */}
            <div className="flex gap-2">
              <button
                onClick={() => window.open(agentApi.exportUrl('markdown', resume.id), '_blank')}
                className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md bg-surface-700/40 text-slate-300 hover:bg-surface-700/60"
              >
                <FileDown size={13} /> 导出 Markdown
              </button>
              <button
                onClick={() => window.open(agentApi.exportUrl('pdf', resume.id), '_blank')}
                className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md bg-surface-700/40 text-slate-300 hover:bg-surface-700/60"
              >
                <FileDown size={13} /> 导出 PDF
              </button>
              <button
                onClick={() => window.open(agentApi.exportUrl('word', resume.id), '_blank')}
                className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-md bg-surface-700/40 text-slate-300 hover:bg-surface-700/60"
              >
                <FileDown size={13} /> 导出 Word
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
