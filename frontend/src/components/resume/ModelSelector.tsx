import { useEffect, useState } from 'react';
import { Cpu, ChevronDown, Settings, Loader2, Check, Zap, Shield } from 'lucide-react';
import { agentApi, type SettingsInfo, type CustomModel } from '../../api/agentApi';
import { authApi } from '../../api/authApi';

interface ProviderConfig {
  name: string;
  name_cn: string;
  type: string;
  base_url?: string;
  env_key: string;
  models: { id: string; name: string; multimodal?: boolean }[];
  default_model: string;
}

export function ModelSelector() {
  const [settings, setSettings] = useState<SettingsInfo | null>(null);
  const [cloudTemplates, setCloudTemplates] = useState<any[]>([]);
  const [open, setOpen] = useState(false);
  const [selProvider, setSelProvider] = useState('');
  const [selModel, setSelModel] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    agentApi.getSettings().then(s => {
      setSettings(s);
      setSelProvider(s.provider);
      setSelModel(s.model);
    }).catch(() => {});
    authApi.cloudModels().then(t => setCloudTemplates(t)).catch(() => {});
  }, []);

  const save = async (provider: string, model: string) => {
    setSaving(true);
    try {
      await agentApi.updateSettings({ provider, model });
      setSelProvider(provider);
      setSelModel(model);
      const s = await agentApi.getSettings();
      setSettings(s);
    } catch (e: any) {
      alert(`切换模型失败：${e.message}`);
    } finally {
      setSaving(false);
    }
  };

  if (!settings) {
    return (
      <div className="flex items-center gap-1.5 text-xs text-slate-500">
        <Loader2 size={12} className="animate-spin" />
        加载模型...
      </div>
    );
  }

  const providers = settings.providers as Record<string, ProviderConfig>;
  const customModels: CustomModel[] = settings.custom_models || [];

  const getLabel = () => {
    if (selProvider.startsWith('cloud:')) {
      const tid = parseInt(selProvider.split(':')[1]);
      const tpl = cloudTemplates.find(t => t.id === tid);
      return `官方 · ${tpl?.display_name || tpl?.model_id || `#${tid}`}`;
    }
    if (selProvider.startsWith('custom:')) {
      const cm = customModels.find(c => `custom:${c.id}` === selProvider);
      return `自定义 · ${cm?.display_name || cm?.model_id || selModel}`;
    }
    if (selProvider === 'custom') {
      return `自定义 · ${selModel}`;
    }
    const p = providers[selProvider];
    const modelName = p?.models?.find(m => m.id === selModel)?.name || selModel;
    return `${p?.name_cn || selProvider} · ${modelName}`;
  };

  const hasKey = selProvider.startsWith('cloud:')
    ? true
    : selProvider.startsWith('custom:') || selProvider === 'custom'
    ? true
    : !!settings.api_keys_set[selProvider];

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(!open)}
        className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs transition-colors ${
          hasKey
            ? 'bg-surface-700/40 text-slate-300 hover:bg-surface-700/60 border border-slate-700/40'
            : 'bg-red-500/10 text-red-400 hover:bg-red-500/20 border border-red-500/30'
        }`}
      >
        <Cpu size={12} />
        <span className="max-w-[180px] truncate">{getLabel()}</span>
        {!hasKey && <span className="text-[10px]">(未配置Key)</span>}
        {saving ? <Loader2 size={11} className="animate-spin" /> : <ChevronDown size={11} />}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 z-50 w-72 max-h-96 overflow-y-auto scrollbar-thin bg-surface-800 rounded-xl border border-slate-700/50 shadow-2xl animate-fade-in">
            <div className="p-2 border-b border-slate-700/30">
              <p className="text-xs text-slate-400 px-2 py-1">选择 AI 模型（切换后自动保存）</p>
            </div>

            <div className="p-1.5 space-y-0.5">
              {Object.entries(providers).map(([key, pconfig]) => {
                const isActive = selProvider === key;
                const keyConfigured = !!settings.api_keys_set[key];
                if (!keyConfigured && !isActive) return null;
                return (
                  <div key={key}>
                    <div className="px-2 py-1.5 text-[11px] font-medium text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
                      {pconfig.name_cn}
                      {keyConfigured
                        ? <span className="text-green-400 normal-case">✓</span>
                        : <span className="text-slate-600 normal-case">未配置</span>
                      }
                    </div>
                    {pconfig.models.map(m => {
                      const selected = isActive && selModel === m.id;
                      return (
                        <button
                          key={m.id}
                          onClick={() => { save(key, m.id); setOpen(false); }}
                          className={`w-full text-left px-3 py-1.5 rounded-md text-xs flex items-center gap-2 transition-colors ${
                            selected
                              ? 'bg-accent-blue/15 text-accent-blue'
                              : 'text-slate-300 hover:bg-surface-700/40'
                          }`}
                        >
                          {selected && <Check size={11} className="shrink-0" />}
                          <span className={`truncate ${selected ? '' : 'ml-3.5'}`}>{m.name}</span>
                          {m.multimodal && (
                            <span className="text-[9px] px-1 py-0.5 rounded bg-accent-purple/15 text-accent-purple shrink-0">多模态</span>
                          )}
                          <span className="text-slate-600 font-mono ml-auto text-[10px] truncate">{m.id}</span>
                        </button>
                      );
                    })}
                  </div>
                );
              })}

              {cloudTemplates.length > 0 && (
                <>
                  <div className="px-2 py-1.5 text-[11px] font-medium text-emerald-400/80 uppercase tracking-wider flex items-center gap-1.5 mt-1">
                    <Shield size={10} /> 官方模型（云端代理）
                  </div>
                  {cloudTemplates.map(tpl => {
                    const cloudKey = `cloud:${tpl.id}`;
                    const selected = selProvider === cloudKey;
                    return (
                      <button
                        key={cloudKey}
                        onClick={() => { save(cloudKey, tpl.model_id); setOpen(false); }}
                        className={`w-full text-left px-3 py-1.5 rounded-md text-xs flex items-center gap-2 transition-colors ${
                          selected
                            ? 'bg-emerald-500/15 text-emerald-400'
                            : 'text-slate-300 hover:bg-surface-700/40'
                        }`}
                      >
                        {selected && <Check size={11} className="shrink-0" />}
                        <span className={`truncate ${selected ? '' : 'ml-3.5'}`}>{tpl.display_name || tpl.model_id}</span>
                        {tpl.multimodal && (
                          <span className="text-[9px] px-1 py-0.5 rounded bg-accent-purple/15 text-accent-purple shrink-0">多模态</span>
                        )}
                      </button>
                    );
                  })}
                </>
              )}

              {customModels.length > 0 && (
                <>
                  <div className="px-2 py-1.5 text-[11px] font-medium text-slate-500 uppercase tracking-wider flex items-center gap-1.5 mt-1">
                    <Zap size={10} /> 自定义模型
                  </div>
                  {customModels.map(cm => {
                    const cmKey = `custom:${cm.id}`;
                    const selected = selProvider === cmKey;
                    const displayName = cm.display_name || cm.model_id;
                    return (
                      <button
                        key={cm.id}
                        onClick={() => { save(cmKey, cm.model_id); setOpen(false); }}
                        className={`w-full text-left px-3 py-1.5 rounded-md text-xs flex items-center gap-2 transition-colors ${
                          selected
                            ? 'bg-accent-blue/15 text-accent-blue'
                            : 'text-slate-300 hover:bg-surface-700/40'
                        }`}
                      >
                        {selected && <Check size={11} className="shrink-0" />}
                        <span className={`truncate ${selected ? '' : 'ml-3.5'}`}>{displayName}</span>
                        {cm.multimodal && (
                          <span className="text-[9px] px-1 py-0.5 rounded bg-accent-purple/15 text-accent-purple shrink-0">多模态</span>
                        )}
                      </button>
                    );
                  })}
                </>
              )}
            </div>

            <div className="p-2 border-t border-slate-700/30">
              <button
                onClick={() => { setOpen(false); window.dispatchEvent(new CustomEvent('navigate-model-management')); }}
                className="w-full flex items-center gap-1.5 px-2 py-1.5 text-xs text-slate-400 hover:text-slate-200 hover:bg-surface-700/40 rounded-md transition-colors"
              >
                <Settings size={11} />
                前往模型管理（配置Key、添加模型）
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
