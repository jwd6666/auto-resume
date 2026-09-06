import { useState, useRef, useCallback } from 'react';
import { Wand2, Palette, Upload, Image as ImageIcon, XCircle } from 'lucide-react';
import { Modal } from './ui';
import { ACCENTS } from './editor/render';
import type { Job, Resume } from '../../api/agentApi';

export interface RestyleParams {
  style: string;
  accent: string;
  description: string;
  avatarBase64: string | null;
  refImageBase64: string | null;
}

interface Props {
  open: boolean;
  onClose: () => void;
  resume: Resume | null;
  job: Job | null;
  onConfirm: (params: RestyleParams) => void;
}

interface StyleOption {
  id: string;
  name: string;
  desc: string;
  preview: { left: string; right: string; accent: string };
}

const STYLE_OPTIONS: StyleOption[] = [
  {
    id: 'classic',
    name: '经典双栏',
    desc: '深色侧边栏 + 白色主区，传统正式',
    preview: { left: '30%', right: '70%', accent: '#4A5F7A' },
  },
  {
    id: 'modern',
    name: '现代简约',
    desc: '全白背景 + 主题色竖条，简洁专业',
    preview: { left: '3%', right: '97%', accent: '#2563eb' },
  },
  {
    id: 'minimal',
    name: '极清单栏',
    desc: '单栏居中大量留白，优雅极简',
    preview: { left: '0%', right: '100%', accent: '#2563eb' },
  },
  {
    id: 'creative',
    name: '创意侧边栏',
    desc: '顶部色带 + 下双栏，活力创意',
    preview: { left: '40%', right: '60%', accent: '#2563eb' },
  },
];

function fileToBase64(file: File, maxW = 800, maxH = 600): Promise<string> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(file);
    img.onload = () => {
      const canvas = document.createElement('canvas');
      let w = img.width;
      let h = img.height;
      if (w > maxW) { h = h * (maxW / w); w = maxW; }
      if (h > maxH) { w = w * (maxH / h); h = maxH; }
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext('2d');
      if (!ctx) { reject(new Error('canvas error')); return; }
      ctx.drawImage(img, 0, 0, w, h);
      const dataUrl = canvas.toDataURL(file.type || 'image/png', 0.85);
      URL.revokeObjectURL(url);
      resolve(dataUrl);
    };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('图片加载失败')); };
    img.src = url;
  });
}

export function RestyleResumeModal({ open, onClose, resume, job, onConfirm }: Props) {
  const [style, setStyle] = useState('classic');
  const [accent, setAccent] = useState(ACCENTS[0]);
  const [description, setDescription] = useState('');
  const [avatarBase64, setAvatarBase64] = useState<string | null>(null);
  const [avatarPreview, setAvatarPreview] = useState<string | null>(null);
  const [refImageBase64, setRefImageBase64] = useState<string | null>(null);
  const [refImagePreview, setRefImagePreview] = useState<string | null>(null);

  const avatarInputRef = useRef<HTMLInputElement>(null);
  const refImageInputRef = useRef<HTMLInputElement>(null);

  const handleAvatarUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const preview = URL.createObjectURL(file);
      setAvatarPreview(preview);
      const base64 = await fileToBase64(file, 200, 200);
      setAvatarBase64(base64);
    } catch {
      // ignore
    }
    e.target.value = '';
  }, []);

  const handleRefImageUpload = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const preview = URL.createObjectURL(file);
      setRefImagePreview(preview);
      const base64 = await fileToBase64(file, 800, 600);
      setRefImageBase64(base64);
    } catch {
      // ignore
    }
    e.target.value = '';
  }, []);

  const removeAvatar = useCallback(() => {
    setAvatarBase64(null);
    if (avatarPreview) URL.revokeObjectURL(avatarPreview);
    setAvatarPreview(null);
  }, [avatarPreview]);

  const removeRefImage = useCallback(() => {
    setRefImageBase64(null);
    if (refImagePreview) URL.revokeObjectURL(refImagePreview);
    setRefImagePreview(null);
  }, [refImagePreview]);

  const handleRestyle = () => {
    if (!resume) return;
    onConfirm({ style, accent, description, avatarBase64, refImageBase64 });
    onClose();
  };

  const handleClose = () => {
    onClose();
  };

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="重新排版简历"
      icon={<Wand2 size={15} className="text-amber-400" />}
      badge={resume?.title || job?.title}
    >
      <div className="space-y-4">
        <div>
          <label className="text-xs text-slate-400 mb-2 block">选择风格</label>
          <div className="grid grid-cols-2 gap-2">
            {STYLE_OPTIONS.map(opt => {
              const active = style === opt.id;
              return (
                <button
                  key={opt.id}
                  onClick={() => setStyle(opt.id)}
                  className={`relative rounded-lg border p-2.5 text-left transition-all ${
                    active
                      ? 'border-accent-blue bg-accent-blue/10 ring-1 ring-accent-blue/40'
                      : 'border-slate-700/50 bg-surface-900/40 hover:border-slate-600/60 hover:bg-surface-900/60'
                  }`}
                >
                  <div className="flex items-stretch gap-2 mb-1.5">
                    <div
                      className="rounded-sm shrink-0"
                      style={{
                        width: opt.preview.left === '0%' ? '0' : '28px',
                        height: '36px',
                        backgroundColor: opt.id === 'classic' ? '#4A5F7A' : opt.id === 'creative' ? accent : 'transparent',
                        borderLeft: opt.id === 'modern' ? `3px solid ${accent}` : 'none',
                        borderRadius: '2px',
                      }}
                    />
                    <div
                      className="rounded-sm flex-1"
                      style={{
                        height: '36px',
                        backgroundColor: '#f8f8f8',
                        borderRadius: '2px',
                      }}
                    >
                      {opt.id === 'minimal' && (
                        <div className="w-full h-full flex items-center justify-center">
                          <div style={{ width: '16px', height: '1px', backgroundColor: accent }} />
                        </div>
                      )}
                      {opt.id === 'creative' && (
                        <div style={{ width: '100%', height: '12px', backgroundColor: accent, borderRadius: '2px 2px 0 0' }} />
                      )}
                    </div>
                  </div>
                  <p className={`text-xs font-medium ${active ? 'text-accent-blue' : 'text-slate-300'}`}>{opt.name}</p>
                  <p className="text-[10px] text-slate-500 mt-0.5 leading-tight">{opt.desc}</p>
                  {active && (
                    <div className="absolute top-1.5 right-1.5 w-3.5 h-3.5 rounded-full bg-accent-blue flex items-center justify-center">
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

        <div>
          <label className="text-xs text-slate-400 mb-2 flex items-center gap-1.5">
            <Palette size={12} /> 主题色
          </label>
          <div className="flex items-center gap-3">
            {ACCENTS.map(a => (
              <button
                key={a}
                onClick={() => setAccent(a)}
                className={`relative w-6 h-6 rounded-full transition-all hover:scale-110 ${
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

        <div>
          <label className="text-xs text-slate-400 mb-1.5 block">
            补充描述 <span className="text-slate-600">(可选)</span>
          </label>
          <textarea
            value={description}
            onChange={e => setDescription(e.target.value.slice(0, 200))}
            placeholder="如：偏蓝色系、加大行距、技能标签用胶囊样式…"
            rows={2}
            className="w-full bg-surface-900/60 border border-slate-700/50 rounded-md px-3 py-2 text-sm text-slate-200 placeholder-slate-600/50 focus:border-accent-blue/50 focus:outline-none resize-none text-[12px] scrollbar-thin"
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-slate-400 mb-1.5 flex items-center gap-1">
              <ImageIcon size={11} /> 头像 <span className="text-slate-600">(可选)</span>
            </label>
            <input ref={avatarInputRef} type="file" accept="image/*" className="hidden" onChange={handleAvatarUpload} />
            {avatarPreview ? (
              <div className="relative w-12 h-12 rounded-full overflow-hidden border-2 border-slate-600/40 bg-surface-900">
                <img src={avatarPreview} alt="头像" className="w-full h-full object-cover" />
                <button
                  onClick={removeAvatar}
                  className="absolute -top-0.5 -right-0.5 w-4 h-4 rounded-full bg-red-500/80 text-white flex items-center justify-center hover:bg-red-500"
                >
                  <XCircle size={10} />
                </button>
              </div>
            ) : (
              <button
                onClick={() => avatarInputRef.current?.click()}
                className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded-md bg-surface-900/60 border border-slate-700/50 text-slate-400 hover:text-slate-200 hover:border-slate-600/60 transition-colors"
              >
                <Upload size={11} /> 上传头像
              </button>
            )}
          </div>

          <div>
            <label className="text-xs text-slate-400 mb-1.5 flex items-center gap-1">
              <ImageIcon size={11} /> 参考图 <span className="text-slate-600">(可选)</span>
            </label>
            <input ref={refImageInputRef} type="file" accept="image/*" className="hidden" onChange={handleRefImageUpload} />
            {refImagePreview ? (
              <div className="relative w-16 h-12 rounded-md overflow-hidden border border-slate-600/40 bg-surface-900">
                <img src={refImagePreview} alt="参考图" className="w-full h-full object-cover" />
                <button
                  onClick={removeRefImage}
                  className="absolute -top-0.5 -right-0.5 w-4 h-4 rounded-full bg-red-500/80 text-white flex items-center justify-center hover:bg-red-500"
                >
                  <XCircle size={10} />
                </button>
              </div>
            ) : (
              <button
                onClick={() => refImageInputRef.current?.click()}
                className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded-md bg-surface-900/60 border border-slate-700/50 text-slate-400 hover:text-slate-200 hover:border-slate-600/60 transition-colors"
              >
                <Upload size={11} /> 上传参考图
              </button>
            )}
            <p className="text-[10px] text-slate-600 mt-1">需多模态模型支持</p>
          </div>
        </div>

        <div className="flex gap-2 justify-end pt-2 border-t border-slate-700/30">
          <button
            onClick={handleClose}
            className="px-3.5 py-1.5 text-xs text-slate-400 hover:text-slate-200 rounded-md hover:bg-slate-700/40 transition-colors"
          >
            取消
          </button>
          <button
            onClick={handleRestyle}
            disabled={!resume}
            className="flex items-center gap-1.5 px-4 py-1.5 text-xs bg-amber-500/80 text-white rounded-md hover:bg-amber-500 disabled:opacity-40 transition-colors"
          >
            <Wand2 size={13} /> 重新排版
          </button>
        </div>
      </div>
    </Modal>
  );
}
