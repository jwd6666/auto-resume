/** 添加模型弹窗 — 自定义配置 + 测试连通性 + 完整错误透传 */
import { useState } from 'react';
import { X, Loader2, ChevronDown, Eye, EyeOff, AlertCircle, CheckCircle2 } from 'lucide-react';
import { agentApi } from '../api/agentApi';

export interface CustomModelData {
  api_format: string;
  base_url: string;
  full_url: boolean;
  model_id: string;
  multimodal: boolean;
  api_key: string;
  // 高级配置
  model_series: string;
  display_name: string;
  context_input: number;
  context_output: number;
  tool_call_rounds: number;
}

interface Props {
  onClose: () => void;
  /** 添加模式回调（添加模式下必传） */
  onAdd?: (model: CustomModelData) => void;
  /** 编辑模式回调（编辑模式下必传） */
  onUpdate?: (model: CustomModelData) => void;
  /** 编辑模式初始数据（含 id）；提供则进入编辑模式 */
  editData?: { id: string } & Partial<CustomModelData>;
}

const DEFAULTS: CustomModelData = {
  api_format: 'openai_chat',
  base_url: '',
  full_url: false,
  model_id: '',
  multimodal: false,
  api_key: '',
  model_series: 'default',
  display_name: '',
  context_input: 184000,
  context_output: 16000,
  tool_call_rounds: 0,
};

const API_FORMATS = [
  { value: 'openai_chat', label: 'OpenAI Chat Completions 格式' },
  { value: 'openai_responses', label: 'OpenAI Responses 格式 (预留)' },
  { value: 'anthropic', label: 'Anthropic Messages 格式 (预留)' },
];

const MODEL_SERIES = [
  { value: 'default', label: '默认' },
  { value: 'gpt', label: 'GPT 系列' },
  { value: 'claude', label: 'Claude 系列' },
  { value: 'gemini', label: 'Gemini 系列' },
  { value: 'glm', label: 'GLM 系列' },
  { value: 'qwen', label: '通义千问系列' },
  { value: 'deepseek', label: 'DeepSeek 系列' },
];

export function AddModelModal({ onClose, onAdd, onUpdate, editData }: Props) {
  const isEdit = !!editData;
  // 初始化表单：编辑模式用 editData 覆盖默认值，api_key 始终置空（编辑时留空=保留原值）
  const [form, setForm] = useState<CustomModelData>(() => {
    if (!editData) return { ...DEFAULTS };
    return {
      ...DEFAULTS,
      ...editData,
      api_key: '',  // 编辑模式不回显密钥，留空表示保留原值
    };
  });
  const [showKey, setShowKey] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(!!editData && !!(editData.model_series || editData.display_name || editData.tool_call_rounds));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [testing, setTesting] = useState(false);
  const [testError, setTestError] = useState<string>('');
  const [testSuccess, setTestSuccess] = useState(false);

  const update = <K extends keyof CustomModelData>(key: K, value: CustomModelData[K]) => {
    setForm(prev => ({ ...prev, [key]: value }));
    // 清除该字段错误
    if (errors[key]) setErrors(prev => { const n = { ...prev }; delete n[key]; return n; });
    // 清除测试结果
    setTestError('');
    setTestSuccess(false);
  };

  const validate = (): boolean => {
    const errs: Record<string, string> = {};
    if (!form.base_url.trim()) {
      errs.base_url = '请填写自定义请求地址';
    } else if (!/^https?:\/\//.test(form.base_url.trim())) {
      errs.base_url = '地址必须以 http:// 或 https:// 开头';
    }
    if (!form.model_id.trim()) {
      errs.model_id = '请填写模型 ID';
    }
    // 添加模式必填 API 密钥；编辑模式可留空（保留原值）
    if (!isEdit && !form.api_key.trim()) {
      errs.api_key = '请填写 API 密钥';
    }
    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const handleTest = async () => {
    if (!validate()) return;
    setTesting(true);
    setTestError('');
    setTestSuccess(false);

    try {
      // 通过后端代理发起测试，避免浏览器 CORS 拦截
      // 编辑模式下 api_key 可为空，传 existing_model_id 让后端用已存储的密钥
      const result = await agentApi.testCustomModel({
        base_url: form.base_url.trim(),
        full_url: form.full_url,
        model_id: form.model_id.trim(),
        api_key: form.api_key.trim(),
        existing_model_id: isEdit && editData ? editData.id : undefined,
      });

      if (result.success) {
        setTestSuccess(true);
        // 延迟一下再回调，让用户看到成功状态
        setTimeout(() => {
          if (isEdit) {
            onUpdate?.({ ...form });
          } else {
            onAdd?.({ ...form });
          }
          onClose();
        }, 600);
      } else if (result.error_type === 'no_api_key') {
        setTestError(result.message || '请填写 API 密钥后再测试。');
      } else if (result.status_code !== undefined) {
        // HTTP 错误：完整展示状态码 + 响应体
        setTestError(
          `HTTP ${result.status_code} ${result.status_text || 'Unknown'}\n\n响应体:\n${result.body || '(空)'}`
        );
      } else if (result.error_type === 'timeout') {
        setTestError(result.message || '请求超时（15秒），请检查网络或 API 地址是否正确。');
      } else if (result.error_type === 'URLError') {
        setTestError(
          `网络错误\n\n类型: URLError\n消息: ${result.message || '(无)'}\n\n可能原因:\n1. API 地址不正确或不可达\n2. DNS 解析失败\n3. 服务端拒绝连接`
        );
      } else {
        setTestError(
          `请求异常\n\n类型: ${result.error_type || 'Unknown'}\n消息: ${result.message || '(无)'}`
        );
      }
    } catch (e: any) {
      // 调用后端代理本身失败（后端未启动 / 后端返回 4xx/5xx）
      setTestError(
        `后端代理请求失败\n\n类型: ${e.name || 'Unknown'}\n消息: ${e.message || String(e)}\n\n请确认后端服务已启动。`
      );
    } finally {
      setTesting(false);
    }
  };

  const handleReset = () => {
    setForm({ ...DEFAULTS });
    setErrors({});
    setTestError('');
    setTestSuccess(false);
    setShowKey(false);
  };

  const inputCls = (field: string) =>
    `w-full px-3 py-2 rounded-lg bg-surface-900/60 border text-sm text-slate-200 transition-colors focus:outline-none ${
      errors[field]
        ? 'border-red-500/50 focus:border-red-500/60 focus:ring-1 focus:ring-red-500/30'
        : 'border-slate-700/50 focus:border-accent-blue/50 focus:ring-1 focus:ring-accent-blue/30'
    }`;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in" onClick={onClose}>
      <div
        className="w-full max-w-lg max-h-[90vh] overflow-y-auto scrollbar-thin bg-surface-800 rounded-xl border border-slate-700/50 shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700/40">
          <h2 className="text-lg font-bold text-slate-100">{isEdit ? '编辑模型' : '添加模型'}</h2>
          <button onClick={onClose} className="text-slate-500 hover:text-slate-300 transition-colors">
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-4">
          {/* Tab 标签（只有自定义配置） */}
          <div className="text-xs font-medium text-slate-400 uppercase tracking-wide">自定义配置</div>

          {/* 1. API 格式 */}
          <div>
            <label className="flex items-center gap-1 text-sm text-slate-300 mb-1.5">
              API 格式<span className="text-red-400">*</span>
            </label>
            <select
              value={form.api_format}
              onChange={e => update('api_format', e.target.value)}
              className={inputCls('api_format')}
            >
              {API_FORMATS.map(f => (
                <option key={f.value} value={f.value}>{f.label}</option>
              ))}
            </select>
          </div>

          {/* 2. 自定义请求地址 */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="flex items-center gap-1 text-sm text-slate-300">
                自定义请求地址<span className="text-red-400">*</span>
              </label>
              <label className="flex items-center gap-1.5 cursor-pointer select-none">
                <span className="text-xs text-slate-500">完整 URL</span>
                <button
                  type="button"
                  onClick={() => update('full_url', !form.full_url)}
                  className={`w-9 h-5 rounded-full transition-colors relative shrink-0 ${form.full_url ? 'bg-accent-blue' : 'bg-slate-600'}`}
                >
                  <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform ${form.full_url ? 'translate-x-4' : 'translate-x-0'}`} />
                </button>
              </label>
            </div>
            <input
              type="text"
              value={form.base_url}
              onChange={e => update('base_url', e.target.value)}
              className={inputCls('base_url')}
              placeholder="例如 https://api.openai.com/v1"
            />
            {errors.base_url && <p className="text-xs text-red-400 mt-1">{errors.base_url}</p>}
            <div className="mt-1.5 flex items-start gap-1.5 px-2.5 py-1.5 rounded-md bg-accent-blue/10 text-xs text-accent-blue/80">
              {form.full_url
                ? '已开启完整 URL 模式，将直接使用你输入的地址发起请求，不自动拼接 /chat/completions。'
                : '请填写兼容 OpenAI API 的服务端点地址，不要以斜杠结尾。/chat/completions 将会被补充到你填写的地址末尾。'}
            </div>
          </div>

          {/* 3. 模型 ID */}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="flex items-center gap-1 text-sm text-slate-300">
                模型 ID<span className="text-red-400">*</span>
              </label>
              <label className="flex items-center gap-1.5 cursor-pointer select-none">
                <span className="text-xs text-slate-500">多模态</span>
                <button
                  type="button"
                  onClick={() => update('multimodal', !form.multimodal)}
                  className={`w-9 h-5 rounded-full transition-colors relative shrink-0 ${form.multimodal ? 'bg-accent-blue' : 'bg-slate-600'}`}
                >
                  <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform ${form.multimodal ? 'translate-x-4' : 'translate-x-0'}`} />
                </button>
              </label>
            </div>
            <input
              type="text"
              value={form.model_id}
              onChange={e => update('model_id', e.target.value)}
              className={inputCls('model_id')}
              placeholder="输入模型 ID"
            />
            {errors.model_id && <p className="text-xs text-red-400 mt-1">{errors.model_id}</p>}
          </div>

          {/* 4. API 密钥 */}
          <div>
            <label className="flex items-center gap-1 text-sm text-slate-300 mb-1.5">
              API 密钥{!isEdit && <span className="text-red-400">*</span>}
              {isEdit && <span className="text-xs text-slate-600 ml-1">（留空则保留原密钥）</span>}
            </label>
            <div className="relative">
              <input
                type={showKey ? 'text' : 'password'}
                value={form.api_key}
                onChange={e => update('api_key', e.target.value)}
                className={inputCls('api_key') + ' pr-10'}
                placeholder={isEdit ? '留空则不修改（保留原密钥）' : '输入 API 密钥'}
              />
              <button
                type="button"
                onClick={() => setShowKey(!showKey)}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
              >
                {showKey ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            </div>
            {errors.api_key && <p className="text-xs text-red-400 mt-1">{errors.api_key}</p>}
          </div>

          {/* 5. 高级配置 */}
          <div className="border border-slate-700/40 rounded-lg overflow-hidden">
            <button
              type="button"
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="w-full px-3 py-2 flex items-center justify-between text-sm text-slate-300 hover:bg-surface-700/30 transition-colors"
            >
              <span>高级配置</span>
              <ChevronDown size={14} className={`transition-transform ${showAdvanced ? 'rotate-180' : ''}`} />
            </button>
            {showAdvanced && (
              <div className="px-3 pb-3 pt-1 space-y-3 border-t border-slate-700/30 animate-fade-in">
                {/* 模型系列 */}
                <div>
                  <label className="block text-xs text-slate-400 mb-1">模型系列</label>
                  <select
                    value={form.model_series}
                    onChange={e => update('model_series', e.target.value)}
                    className={inputCls('model_series')}
                  >
                    {MODEL_SERIES.map(s => (
                      <option key={s.value} value={s.value}>{s.label}</option>
                    ))}
                  </select>
                  <p className="text-xs text-slate-600 mt-1">针对特定模型系列优化了 Prompt 和超参，未选择时使用默认配置。</p>
                </div>

                {/* 模型展示名称 */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="block text-xs text-slate-400">模型展示名称</label>
                    <span className="text-xs text-slate-600">{form.display_name.length}/32</span>
                  </div>
                  <input
                    type="text"
                    value={form.display_name}
                    onChange={e => update('display_name', e.target.value.slice(0, 32))}
                    maxLength={32}
                    className={inputCls('display_name')}
                    placeholder="在模型列表中展示的名称"
                  />
                  <p className="text-xs text-slate-600 mt-1">在模型列表中展示的名称，未设置时默认显示 Model ID。</p>
                </div>

                {/* 上下文窗口 */}
                <div>
                  <label className="block text-xs text-slate-400 mb-1">上下文窗口</label>
                  <div className="flex items-center gap-2">
                    <div className="flex-1">
                      <input
                        type="number"
                        value={form.context_input}
                        onChange={e => update('context_input', Number(e.target.value) || 0)}
                        className={inputCls('context_input')}
                        placeholder="输入"
                      />
                      <p className="text-xs text-slate-600 mt-0.5">输入</p>
                    </div>
                    <div className="flex-1">
                      <input
                        type="number"
                        value={form.context_output}
                        onChange={e => update('context_output', Number(e.target.value) || 0)}
                        className={inputCls('context_output')}
                        placeholder="输出"
                      />
                      <p className="text-xs text-slate-600 mt-0.5">输出</p>
                    </div>
                  </div>
                </div>

                {/* 工具调用轮次 */}
                <div>
                  <label className="block text-xs text-slate-400 mb-1">工具调用轮次</label>
                  <input
                    type="number"
                    value={form.tool_call_rounds}
                    onChange={e => update('tool_call_rounds', Number(e.target.value) || 0)}
                    className={inputCls('tool_call_rounds')}
                    placeholder="预留"
                  />
                </div>
              </div>
            )}
          </div>

          {/* 错误展示区域 */}
          {testError && (
            <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-3 animate-fade-in">
              <div className="flex items-center gap-1.5 text-red-400 text-sm font-medium mb-1">
                <AlertCircle size={14} />
                连接失败
              </div>
              <pre className="text-xs text-red-300 whitespace-pre-wrap break-all font-mono max-h-40 overflow-y-auto scrollbar-thin">
                {testError}
              </pre>
            </div>
          )}

          {/* 成功提示 */}
          {testSuccess && (
            <div className="rounded-lg border border-green-500/40 bg-green-500/10 p-3 animate-fade-in">
              <div className="flex items-center gap-1.5 text-green-400 text-sm font-medium">
                <CheckCircle2 size={14} />
                连接成功，正在添加模型...
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-5 py-4 border-t border-slate-700/40">
          <button
            onClick={handleReset}
            disabled={testing}
            className="px-4 py-2 rounded-lg text-sm text-slate-400 hover:text-slate-200 hover:bg-surface-700/40 transition-colors disabled:opacity-50"
          >
            重置
          </button>
          <button
            onClick={handleTest}
            disabled={testing}
            className="btn-primary inline-flex items-center gap-1.5 disabled:opacity-60"
          >
            {testing ? (
              <>
                <Loader2 size={15} className="animate-spin" />
                测试中...
              </>
            ) : testSuccess ? (
              <>
                <CheckCircle2 size={15} />
                {isEdit ? '已保存' : '添加成功'}
              </>
            ) : (
              isEdit ? '保存修改' : '添加模型'
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
