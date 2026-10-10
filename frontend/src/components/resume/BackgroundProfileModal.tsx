/** 个人背景档案弹窗：表单化录入个人信息，保存为 profile content 文本，生成简历时自动注入 */
import { useEffect, useRef, useState } from 'react';
import { UserCircle, Plus, Trash2, Upload, XCircle } from 'lucide-react';
import { agentApi } from '../../api/agentApi';
import { Modal } from './ui';

export interface BackgroundProfileForm {
  name: string;
  gender: string;
  phone: string;
  email: string;
  hometown: string;
  intent: string;
  avatar: string;
  education: string;
  campus: string;
  honors: string;
  work: string;
  projects: string;
  skills: string;
  summary: string;
}

const EMPTY_FORM: BackgroundProfileForm = {
  name: '', gender: '', phone: '', email: '', hometown: '', intent: '', avatar: '',
  education: '', campus: '', honors: '', work: '', projects: '', skills: '', summary: '',
};

/** content 文本标签 → 表单字段（含旧标签别名，保证老数据可解析） */
const LABEL_TO_FIELD: Record<string, keyof BackgroundProfileForm> = {
  '姓名': 'name', '性别': 'gender', '电话': 'phone', '邮箱': 'email', '籍贯': 'hometown',
  '求职意向': 'intent', '头像': 'avatar',
  '教育背景': 'education', '教育经历': 'education',
  '校园经历': 'campus', '校园实践': 'campus',
  '荣誉证书': 'honors', '获奖证书': 'honors', '荣誉奖项': 'honors',
  '工作经历': 'work',
  '项目经历': 'projects',
  '专业技能': 'skills', '核心技能': 'skills',
  '自我评价': 'summary', '个人简介': 'summary',
};

/** 单行字段（其余为多行文本域） */
const SINGLE_FIELDS = new Set<keyof BackgroundProfileForm>(['name', 'gender', 'phone', 'email', 'hometown', 'intent', 'avatar']);

/** 序列化顺序 */
const SERIAL_ORDER: [string, keyof BackgroundProfileForm][] = [
  ['姓名', 'name'], ['性别', 'gender'], ['电话', 'phone'], ['邮箱', 'email'], ['籍贯', 'hometown'], ['求职意向', 'intent'], ['头像', 'avatar'],
  ['教育背景', 'education'], ['校园经历', 'campus'], ['荣誉证书', 'honors'], ['工作经历', 'work'], ['项目经历', 'projects'], ['专业技能', 'skills'], ['自我评价', 'summary'],
];

/** 把 profile content 文本解析回表单字段；无法识别的旧内容并入「项目经历」 */
export function parseProfileContent(content: string): BackgroundProfileForm {
  const form: BackgroundProfileForm = { ...EMPTY_FORM };
  if (!content || !content.trim()) return form;
  const buckets: Partial<Record<keyof BackgroundProfileForm, string[]>> = {};
  const leftover: string[] = [];
  let current: keyof BackgroundProfileForm | null = null;
  for (const line of content.split('\n')) {
    const m = line.match(/^([\u4e00-\u9fa5A-Za-z]{2,6})[：:]\s*(.*)$/);
    if (m && LABEL_TO_FIELD[m[1]]) {
      current = LABEL_TO_FIELD[m[1]];
      const v = m[2].trim();
      if (SINGLE_FIELDS.has(current)) buckets[current] = [v];
      else if (v) (buckets[current] ??= []).push(v);
      continue;
    }
    if (current && !SINGLE_FIELDS.has(current)) (buckets[current] ??= []).push(line);
    else leftover.push(line);
  }
  for (const [, key] of SERIAL_ORDER) form[key] = (buckets[key] || []).join('\n').trim();
  const extra = leftover.join('\n').trim();
  if (extra) form.projects = form.projects ? extra + '\n' + form.projects : extra;
  return form;
}

/** 表单字段序列化为 profile content 文本（空字段不落盘） */
export function serializeProfileForm(f: BackgroundProfileForm): string {
  const parts: string[] = [];
  for (const [label, key] of SERIAL_ORDER) {
    const v = f[key].trim();
    if (!v) continue;
    parts.push(SINGLE_FIELDS.has(key) ? `${label}：${v}` : `${label}：\n${v}`);
  }
  return parts.join('\n');
}

const inputCls = 'w-full bg-surface-900/60 border border-slate-700/50 rounded-md px-2.5 py-1.5 text-xs text-slate-200 placeholder:text-slate-600 focus:border-accent-blue/50 focus:outline-none transition-colors';
const labelCls = 'text-[11px] text-slate-400 mb-1 block';

const MULTI_FIELDS: { key: keyof BackgroundProfileForm; label: string; rows: number; placeholder: string }[] = [
  { key: 'education', label: '教育背景', rows: 3, placeholder: 'XX大学 | 计算机科学与技术 | 本科 | 2015.09 - 2019.06' },
  { key: 'campus', label: '校园经历', rows: 3, placeholder: '校学生会 | 技术部部长 | 2016.09 - 2018.06\n• 组织校园编程大赛，吸引 200+ 人参与\n• ...' },
  { key: 'work', label: '工作经历', rows: 4, placeholder: 'XX科技有限公司 | Java高级工程师 | 2021.06 - 至今\n• 负责自动化系统核心模块开发…' },
  { key: 'projects', label: '项目经历', rows: 4, placeholder: 'XX管理系统 | 核心开发 | 2022.03 - 2023.06\n• 负责订单模块设计，支撑日均 10 万笔订单\n• ...' },
  { key: 'skills', label: '专业技能', rows: 2, placeholder: 'Java / SpringBoot / MySQL / Linux / Oracle' },
  { key: 'summary', label: '自我评价', rows: 2, placeholder: '3年自动化系统开发经验，具备独立搭建部署项目能力，团队合作意识强…' },
];

interface Props {
  open: boolean;
  onClose: () => void;
  /** 当前已保存的 profile content（用于回填表单） */
  content: string;
  onSave: (content: string) => void;
}

export function BackgroundProfileModal({ open, onClose, content, onSave }: Props) {
  const [form, setForm] = useState<BackgroundProfileForm>(EMPTY_FORM);
  // 荣誉证书以多行数组形式管理，与 form.honors（换行拼接）双向同步
  const [honorList, setHonorList] = useState<string[]>([]);
  // 头像上传中 / 上传失败信息 / 头像文件已不存在（预览加载失败）
  const [avatarUploading, setAvatarUploading] = useState(false);
  const [avatarError, setAvatarError] = useState('');
  const [avatarBroken, setAvatarBroken] = useState(false);
  const avatarInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      const parsed = parseProfileContent(content);
      setForm(parsed);
      setHonorList(parsed.honors ? parsed.honors.split('\n').filter(x => x.trim()) : []);
      setAvatarError('');
      setAvatarBroken(false);
    }
  }, [open, content]);

  const set = (key: keyof BackgroundProfileForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    setForm(prev => ({ ...prev, [key]: e.target.value }));

  // 头像上传：保存到安装目录 data/avatars，仅记录返回的绝对路径
  const handleAvatarUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setAvatarError('');
    setAvatarUploading(true);
    try {
      const { path } = await agentApi.uploadAvatar(file);
      setAvatarBroken(false);
      setForm(prev => ({ ...prev, avatar: path }));
    } catch (err: any) {
      setAvatarError(err?.message || '头像上传失败');
    } finally {
      setAvatarUploading(false);
    }
  };

  const removeAvatar = () => {
    setForm(prev => ({ ...prev, avatar: '' }));
    setAvatarBroken(false);
  };

  const avatarUrl = form.avatar ? agentApi.avatarPreviewUrl(agentApi.avatarFilename(form.avatar)) : '';

  const handleSave = () => {
    const honors = honorList.map(s => s.trim()).filter(Boolean).join('\n');
    onSave(serializeProfileForm({ ...form, honors }));
  };

  return (
    <Modal open={open} onClose={onClose} title="个人背景信息" icon={<UserCircle size={15} className="text-accent-purple" />}>
      <div className="space-y-3">
        <p className="text-[11px] text-slate-500">以下信息均为可选，保存后在生成简历、AI 修改简历时自动注入。</p>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>姓名</label>
            <input value={form.name} onChange={set('name')} placeholder="张三" className={inputCls} />
          </div>
          <div>
            <label className={labelCls}>性别</label>
            <select value={form.gender} onChange={set('gender')} className={inputCls}>
              <option value="">未填写</option>
              <option value="男">男</option>
              <option value="女">女</option>
            </select>
          </div>
          <div>
            <label className={labelCls}>电话</label>
            <input value={form.phone} onChange={set('phone')} placeholder="138xxxx1234" className={inputCls} />
          </div>
          <div>
            <label className={labelCls}>邮箱</label>
            <input value={form.email} onChange={set('email')} placeholder="zhangsan@email.com" className={inputCls} />
          </div>
          <div>
            <label className={labelCls}>籍贯</label>
            <input value={form.hometown} onChange={set('hometown')} placeholder="四川成都" className={inputCls} />
          </div>
          <div>
            <label className={labelCls}>求职意向</label>
            <input value={form.intent} onChange={set('intent')} placeholder="Java后端开发工程师" className={inputCls} />
          </div>
        </div>

        <div>
          <label className={labelCls}>
            头像 <span className="text-slate-600">(可选，生成简历时自动嵌入头像框)</span>
          </label>
          <div className="flex items-center gap-3">
            <input ref={avatarInputRef} type="file" accept="image/*" className="hidden" onChange={handleAvatarUpload} />
            {form.avatar && !avatarBroken ? (
              <div className="relative w-14 h-14 rounded-full overflow-hidden border-2 border-slate-600/40 bg-surface-900 shrink-0 group">
                <img
                  src={avatarUrl}
                  alt="头像"
                  className="w-full h-full object-cover cursor-pointer"
                  onClick={() => avatarInputRef.current?.click()}
                  onError={() => setAvatarBroken(true)}
                />
                <button
                  onClick={removeAvatar}
                  className="absolute -top-0.5 -right-0.5 w-4 h-4 rounded-full bg-red-500/80 text-white flex items-center justify-center hover:bg-red-500"
                  title="移除头像"
                >
                  <XCircle size={10} />
                </button>
              </div>
            ) : (
              <button
                onClick={() => avatarInputRef.current?.click()}
                disabled={avatarUploading}
                className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs rounded-md bg-surface-900/60 border border-slate-700/50 text-slate-400 hover:text-slate-200 hover:border-slate-600/60 transition-colors disabled:opacity-40 shrink-0"
              >
                <Upload size={11} /> {avatarUploading ? '上传中…' : '上传头像'}
              </button>
            )}
            <p className="text-[10px] text-slate-600 leading-relaxed">
              保存在安装目录 data/avatars 下；生成简历时以本地绝对路径嵌入简历头像框{avatarBroken && form.avatar ? '（原头像文件已不存在，请重新上传）' : ''}
            </p>
          </div>
          {avatarError && <p className="text-[10px] text-red-400 mt-1">{avatarError}</p>}
        </div>

        {MULTI_FIELDS.map(mf => (
          <div key={mf.key}>
            <label className={labelCls}>{mf.label}</label>
            <textarea
              value={form[mf.key]}
              onChange={set(mf.key)}
              placeholder={mf.placeholder}
              rows={mf.rows}
              className={`${inputCls} resize-none leading-relaxed scrollbar-thin`}
            />
          </div>
        ))}

        <div>
          <label className={labelCls}>荣誉证书</label>
          <div className="space-y-2">
            {honorList.length === 0 && (
              <p className="text-[11px] text-slate-600">暂无荣誉证书，点击下方按钮添加</p>
            )}
            {honorList.map((cert, idx) => (
              <div key={idx} className="flex items-center gap-2">
                <input
                  value={cert}
                  onChange={e => setHonorList(prev => prev.map((c, i) => (i === idx ? e.target.value : c)))}
                  placeholder="如：英语六级证书 / 全国大学生竞赛一等奖"
                  className={inputCls}
                />
                <button
                  onClick={() => setHonorList(prev => prev.filter((_, i) => i !== idx))}
                  className="p-1.5 rounded-md text-slate-500 hover:text-red-400 hover:bg-red-500/10 transition-colors shrink-0"
                  title="删除该证书"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
            <button
              onClick={() => setHonorList(prev => [...prev, ''])}
              className="flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs font-medium bg-accent-purple/10 text-accent-purple hover:bg-accent-purple/20 transition-colors"
            >
              <Plus size={12} /> 添加证书
            </button>
          </div>
        </div>

        <div className="flex gap-2 justify-end pt-2 border-t border-slate-700/30 sticky bottom-0 bg-surface-800/95 backdrop-blur-sm -mx-5 px-5 pb-0 -mb-4 py-3">
          <button
            onClick={onClose}
            className="px-3.5 py-1.5 text-xs text-slate-400 hover:text-slate-200 rounded-md hover:bg-slate-700/40 transition-colors"
          >
            取消
          </button>
          <button
            onClick={handleSave}
            className="flex items-center gap-1.5 px-4 py-1.5 text-xs bg-accent-purple text-white rounded-md hover:bg-accent-purple/85 transition-colors"
          >
            <UserCircle size={13} /> 保存
          </button>
        </div>
      </div>
    </Modal>
  );
}
