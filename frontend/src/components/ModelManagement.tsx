/** 模型管理 — 官方模板（云端直连，开箱即用） + 我的模型（本地 sidecar） */
import { useEffect, useState } from 'react';
import { Check, Cloud, Loader2, Zap, ZapOff, Plus, Trash2, Pencil, ListChecks, Shield, User } from 'lucide-react';
import { agentApi, type SettingsInfo, type CustomModel } from '../api/agentApi';
import { authApi } from '../api/authApi';
import { AddModelModal, type CustomModelData } from './AddModelModal';

type TabKey = 'cloud' | 'mine';

export function ModelManagement() {
  const [settings, setSettings] = useState<SettingsInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, { success: boolean; message: string }>>({});
  const [selProvider, setSelProvider] = useState('');
  const [selModel, setSelModel] = useState('');

  const [showAddModal, setShowAddModal] = useState(false);
  const [editData, setEditData] = useState<{ id: string } & Partial<CustomModelData> | null>(null);
  const [cloudImportData, setCloudImportData] = useState<CustomModelData | null>(null);

  const [batchMode, setBatchMode] = useState(false);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [batchDeleting, setBatchDeleting] = useState(false);

  const [cloudTemplates, setCloudTemplates] = useState<any[] | null>(null);
  const [cloudLoading, setCloudLoading] = useState(false);
  const [cloudActivating, setCloudActivating] = useState<number | null>(null);

  const [activeTab, setActiveTab] = useState<TabKey>('mine');
  const [loggedIn, setLoggedIn] = useState(true);

  const requestLogin = () => window.dispatchEvent(new CustomEvent('request-login'));

  useEffect(() => {
    authApi.status().then(s => setLoggedIn(s.status === 'active')).catch(() => {});
  }, []);

  const customModels: CustomModel[] = settings?.custom_models || [];
  const isCloudActive = selProvider.startsWith('cloud:');
  const activeCloudId = isCloudActive ? parseInt(selProvider.split(':')[1]) : null;

  const load = async () => {
    try {
      const s = await agentApi.getSettings();
      setSettings(s);
      setSelProvider(s.provider);
      setSelModel(s.model);
    } catch (e: any) {
      console.error('加载设置失败', e);
    } finally {
      setLoading(false);
    }
  };

  const loadCloudTemplates = async () => {
    if (cloudTemplates !== null) return;
    setCloudLoading(true);
    try {
      const templates = await authApi.cloudModels();
      setCloudTemplates(templates);
    } catch {
    } finally {
      setCloudLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const activateModel = async (provider: string, model: string) => {
    try {
      await agentApi.updateSettings({ provider, model });
      await load();
      window.dispatchEvent(new CustomEvent('models-updated'));
    } catch (e: any) {
      alert(`激活模型失败：${e.message}`);
    }
  };

  const activateCloudModel = async (templateId: number) => {
    setCloudActivating(templateId);
    try {
      await authApi.cloudActivate(templateId);
      await load();
      window.dispatchEvent(new CustomEvent('models-updated'));
    } catch (e: any) {
      alert(`激活官方模型失败：${e.message}`);
    } finally {
      setCloudActivating(null);
    }
  };

  const handleTest = async (provider: string, model: string) => {
    setTesting(provider);
    try {
      const result = await agentApi.testConnection(provider, model);
      setTestResult(prev => ({ ...prev, [provider]: result }));
    } catch (e: any) {
      setTestResult(prev => ({ ...prev, [provider]: { success: false, message: e.message } }));
    } finally {
      setTesting(null);
    }
  };

  const handleAddModel = async (data: CustomModelData) => {
    try {
      const saved = await agentApi.addCustomModel(data);
      await activateModel(`custom:${saved.id}`, saved.model_id);
    } catch (e: any) {
      alert(`添加模型失败：${e.message}`);
    }
  };

  const handleDeleteCustomModel = async (cm: CustomModel) => {
    if (!confirm(`确认删除模型「${cm.display_name || cm.model_id}」？`)) return;
    try {
      await agentApi.deleteCustomModel(cm.id);
      if (selProvider === `custom:${cm.id}`) {
        await agentApi.updateSettings({ provider: '', model: '' });
      }
      await load();
      window.dispatchEvent(new CustomEvent('models-updated'));
    } catch (e: any) {
      alert(`删除失败：${e.message}`);
    }
  };

  const handleBatchDelete = async () => {
    if (checked.size === 0) return;
    if (!confirm(`确认删除选中的 ${checked.size} 个模型？`)) return;
    setBatchDeleting(true);
    try {
      const selId = selProvider.replace('custom:', '');
      let needClear = checked.has(selId);
      for (const id of checked) await agentApi.deleteCustomModel(id);
      if (needClear) await agentApi.updateSettings({ provider: '', model: '' });
      setChecked(new Set());
      setBatchMode(false);
      await load();
      window.dispatchEvent(new CustomEvent('models-updated'));
    } catch (e: any) {
      alert(`批量删除失败：${e.message}`);
    } finally {
      setBatchDeleting(false);
    }
  };

  const toggleCheck = (id: string) => {
    const next = new Set(checked);
    if (next.has(id)) next.delete(id); else next.add(id);
    setChecked(next);
  };

  const handleEdit = (cm: CustomModel) => {
    setEditData({
      id: cm.id,
      api_format: cm.api_format,
      base_url: cm.base_url,
      full_url: cm.full_url,
      model_id: cm.model_id,
      multimodal: cm.multimodal,
      model_series: cm.model_series,
      display_name: cm.display_name,
      context_input: cm.context_input,
      context_output: cm.context_output,
      tool_call_rounds: cm.tool_call_rounds,
    });
  };

  const handleUpdateModel = async (data: CustomModelData) => {
    if (!editData) return;
    try {
      const updated = await agentApi.updateCustomModel(editData.id, data);
      await load();
      if (selProvider === `custom:${editData.id}`) {
        setSelModel(updated.model_id);
      }
      setEditData(null);
      window.dispatchEvent(new CustomEvent('models-updated'));
    } catch (e: any) {
      alert(`更新模型失败：${e.message}`);
    }
  };

  const importAsCustom = (tpl: any) => {
    const data: CustomModelData = {
      api_format: tpl.api_format || 'openai_chat',
      base_url: tpl.base_url || '',
      full_url: tpl.full_url || false,
      model_id: tpl.model_id,
      multimodal: tpl.multimodal || false,
      api_key: '',
      model_series: tpl.model_series || 'default',
      display_name: tpl.display_name || tpl.model_id,
      context_input: tpl.context_input || 128000,
      context_output: tpl.context_output || 4096,
      tool_call_rounds: tpl.tool_call_rounds || 3,
    };
    setCloudImportData(data);
    setShowAddModal(true);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 size={24} className="animate-spin text-slate-600" />
      </div>
    );
  }

  if (!settings) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center">
        <p className="text-sm text-slate-500">无法加载设置</p>
        <p className="text-xs text-slate-600 mt-1">请确保后端服务已启动</p>
      </div>
    );
  }

  const activeDisplayName = (() => {
    if (isCloudActive && cloudTemplates) {
      const tpl = cloudTemplates.find((t: any) => t.id === activeCloudId);
      if (tpl) return tpl.display_name || tpl.model_id;
      return `官方模型 #${activeCloudId}`;
    }
    if (selProvider.startsWith('custom:')) {
      const cm = customModels.find(c => `custom:${c.id}` === selProvider);
      return cm?.display_name || cm?.model_id || selModel;
    }
    return selModel;
  })();

  return (
    <div className="p-5 h-full flex flex-col animate-fade-in">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold text-slate-100">模型管理</h1>
          <p className="text-sm text-slate-500 mt-0.5">选择 AI 模型，选中即激活</p>
          <p className="text-[11px] text-amber-400/70 mt-1">
            提示：使用 AI 功能时，你的简历与岗位内容会发送给所选模型的服务商；官方模型经云端服务器代理转发。
          </p>
        </div>
        <button
          onClick={() => {
            if (!loggedIn) {
              alert('添加自己的模型需要先登录');
              requestLogin();
              return;
            }
            setCloudImportData(null);
            setShowAddModal(true);
          }}
          className="btn-primary"
        >
          <Plus size={14} /> 添加模型
        </button>
      </div>

      {/* 当前使用 */}
      {selProvider ? (
        <div className="card p-3 mb-4 flex items-center gap-3">
          <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${isCloudActive ? 'bg-gradient-to-br from-emerald-500/20 to-accent-blue/20' : 'bg-gradient-to-br from-accent-blue/20 to-accent-purple/20'}`}>
            {isCloudActive ? <Shield size={18} className="text-emerald-400" /> : <Zap size={18} className="text-accent-blue" />}
          </div>
          <div>
            <p className="text-xs text-slate-500">当前使用</p>
            <p className="text-sm font-medium text-slate-200">{activeDisplayName}</p>
            {isCloudActive && <p className="text-[10px] text-emerald-400">通过云端代理，无需配置 API Key</p>}
          </div>
        </div>
      ) : (
        <div className="card p-3 mb-4 flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-surface-800/60 flex items-center justify-center">
            <ZapOff size={18} className="text-slate-600" />
          </div>
          <div>
            <p className="text-xs text-slate-500">当前使用</p>
            <p className="text-sm font-medium text-slate-400">未设置 — 请选择一个模型</p>
          </div>
        </div>
      )}

      {/* Tab */}
      <div className="flex items-center gap-1 mb-4 p-1 bg-surface-800/40 rounded-lg">
        <button
          onClick={() => { setActiveTab('cloud'); if (loggedIn) loadCloudTemplates(); }}
          className={`flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            activeTab === 'cloud' ? 'bg-surface-700/80 text-slate-100' : 'text-slate-500 hover:text-slate-300'
          }`}
        >
          <Shield size={14} />
          官方模型
          {isCloudActive && <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />}
          {cloudLoading && <Loader2 size={12} className="animate-spin" />}
        </button>
        <button
          onClick={() => setActiveTab('mine')}
          className={`flex items-center gap-1.5 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            activeTab === 'mine' ? 'bg-surface-700/80 text-slate-100' : 'text-slate-500 hover:text-slate-300'
          }`}
        >
          <User size={14} />
          我的模型
          {customModels.length > 0 && <span className="text-xs text-slate-500">({customModels.length})</span>}
        </button>
      </div>

      {/* ── 官方模型 ── */}
      {activeTab === 'cloud' && (
        <div className="flex-1 overflow-y-auto scrollbar-thin pr-1">
          <div className="px-1 py-2 text-xs text-slate-500 flex items-center gap-1.5">
            <Cloud size={12} />
            官方模型通过云端代理调用，无需配置 API Key，开箱即用。
          </div>
          {!loggedIn ? (
            <div className="card py-12 text-center">
              <Shield size={28} className="text-slate-600 mx-auto mb-3" />
              <p className="text-sm text-slate-400">官方模型需要登录后使用</p>
              <p className="text-xs text-slate-600 mt-1">登录后即可免配置调用云端官方模型</p>
              <button onClick={requestLogin} className="btn-primary mx-auto mt-4">
                前往登录
              </button>
            </div>
          ) : cloudLoading ? (
            <div className="flex items-center justify-center py-16"><Loader2 size={24} className="animate-spin text-slate-600" /></div>
          ) : cloudTemplates && cloudTemplates.length === 0 ? (
            <div className="card py-12 text-center">
              <p className="text-sm text-slate-500">暂无官方模型</p>
              <p className="text-xs text-slate-600 mt-1">管理员在云端后台添加并发布后即可看到</p>
            </div>
          ) : cloudTemplates ? (
            <div className="space-y-2">
              {cloudTemplates.map((tpl: any) => {
                const isActive = activeCloudId === tpl.id;
                const activating = cloudActivating === tpl.id;
                return (
                  <div key={tpl.id} className={`card p-3 transition-all ${isActive ? 'border-emerald-500/40' : ''}`}>
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => activateCloudModel(tpl.id)}
                        disabled={activating}
                        className={`w-5 h-5 rounded-full border-2 flex items-center justify-center transition-all shrink-0 ${
                          isActive ? 'border-emerald-400 bg-emerald-400' : 'border-slate-600 hover:border-slate-400'
                        }`}
                      >
                        {activating ? <Loader2 size={10} className="animate-spin text-white" /> : isActive ? <Check size={11} className="text-white" /> : null}
                      </button>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          <p className={`text-sm font-medium truncate ${isActive ? 'text-emerald-400' : 'text-slate-200'}`}>{tpl.display_name}</p>
                          {tpl.multimodal && <span className="text-[10px] px-1 py-0.5 rounded bg-accent-purple/15 text-accent-purple">多模态</span>}
                          {isActive && <span className="text-[10px] px-1 py-0.5 rounded bg-emerald-500/15 text-emerald-400">使用中</span>}
                        </div>
                        <div className="flex items-center gap-2 mt-0.5">
                          <span className="text-xs text-slate-500 font-mono truncate">{tpl.model_id}</span>
                          <span className="text-xs text-slate-700">·</span>
                          <span className="text-xs text-slate-600">{tpl.model_series && tpl.model_series !== 'default' ? tpl.model_series : 'OpenAI 兼容'}</span>
                          <span className="text-xs text-slate-700">·</span>
                          <span className="text-xs text-slate-600">{tpl.context_input?.toLocaleString()}/{tpl.context_output?.toLocaleString()}</span>
                        </div>
                      </div>
                      <button
                        onClick={() => importAsCustom(tpl)}
                        className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-md bg-surface-700/40 text-slate-400 hover:text-slate-200 hover:bg-surface-700/60 shrink-0"
                        title="复制到「我的模型」（需自己配 API Key）"
                      >
                        复制到我的
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : null}
        </div>
      )}

      {/* ── 我的模型 ── */}
      {activeTab === 'mine' && (
        <>
          <div className="px-1 py-2 text-xs text-slate-500 flex items-center gap-1.5">
            <User size={12} />
            我的模型走本地后端直连，需自行配置 API Key 和服务地址。
          </div>

          <div className="flex items-center gap-2 mb-2">
            {customModels.length > 0 && (
              <button
                onClick={() => { setBatchMode(m => !m); setChecked(new Set()); }}
                className={`flex items-center gap-1 text-xs px-3 py-1.5 rounded-md transition-colors ${batchMode ? 'bg-accent-blue/20 text-accent-blue' : 'bg-surface-700/50 text-slate-400 hover:text-slate-200 hover:bg-surface-700'}`}
              >
                <ListChecks size={14} /> 批量删除
              </button>
            )}
          </div>

          {batchMode && (
            <div className="flex items-center gap-2 mb-3 px-3 py-2 rounded-lg bg-accent-blue/10 border border-accent-blue/25 animate-fade-in">
              <button onClick={() => setChecked(checked.size === customModels.length && customModels.length > 0 ? new Set() : new Set(customModels.map(m => m.id)))} className="text-xs text-accent-blue hover:underline">
                {checked.size === customModels.length && customModels.length > 0 ? '取消全选' : '全选'}
              </button>
              <span className="text-xs text-slate-500">已选 {checked.size} 项</span>
              <div className="flex-1" />
              <button onClick={handleBatchDelete} disabled={checked.size === 0 || batchDeleting} className="flex items-center gap-1 text-xs px-2.5 py-1 rounded bg-red-500/20 text-red-400 hover:bg-red-500/30 disabled:opacity-40">
                {batchDeleting ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />} 删除所选
              </button>
              <button onClick={() => { setBatchMode(false); setChecked(new Set()); }} className="text-xs text-slate-500 hover:text-slate-300">退出</button>
            </div>
          )}

          <div className="flex-1 overflow-y-auto scrollbar-thin pr-1">
            {customModels.length === 0 ? (
              <div className="card py-12 text-center">
                <p className="text-sm text-slate-500">暂无自定义模型</p>
                <p className="text-xs text-slate-600 mt-1">点击「添加模型」新建，或从官方模型「复制到我的」</p>
              </div>
            ) : (
              <div className="space-y-2">
                {customModels.map(cm => {
                  const cmKey = `custom:${cm.id}`;
                  const isActive = selProvider === cmKey;
                  const testRes = testResult[cmKey];
                  const displayName = cm.display_name || cm.model_id;
                  return (
                    <div key={cm.id} className={`card p-3 transition-all ${isActive ? 'border-accent-blue/40' : ''}`}>
                      <div className="flex items-center gap-2">
                        {batchMode ? (
                          <input type="checkbox" checked={checked.has(cm.id)} onChange={() => toggleCheck(cm.id)} className="accent-[#5b8def] shrink-0" />
                        ) : (
                          <button onClick={() => activateModel(cmKey, cm.model_id)} className={`w-5 h-5 rounded-full border-2 flex items-center justify-center transition-all shrink-0 ${isActive ? 'border-accent-blue bg-accent-blue' : 'border-slate-600 hover:border-slate-400'}`}>
                            {isActive && <Check size={11} className="text-white" />}
                          </button>
                        )}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-1.5 flex-wrap">
                            <p className={`text-sm font-medium truncate ${isActive ? 'text-accent-blue' : 'text-slate-300'}`}>{displayName}</p>
                            {cm.multimodal && <span className="text-[10px] px-1 py-0.5 rounded bg-accent-purple/15 text-accent-purple">多模态</span>}
                            {cm.full_url && <span className="text-[10px] px-1 py-0.5 rounded bg-slate-600/30 text-slate-400">完整URL</span>}
                          </div>
                          <div className="flex items-center gap-2 mt-0.5">
                            <span className="text-xs text-slate-500 font-mono truncate">{cm.model_id}</span>
                            <span className="text-xs text-slate-700">·</span>
                            <span className="text-xs text-slate-600 truncate">{cm.base_url}</span>
                          </div>
                        </div>
                        {!batchMode && (
                          <>
                            <button onClick={() => handleEdit(cm)} className="text-slate-500 hover:text-accent-blue transition-colors p-1 shrink-0" title="编辑"><Pencil size={13} /></button>
                            <button onClick={() => handleTest(cmKey, cm.model_id)} disabled={testing === cmKey} className="flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-surface-700/40 text-slate-300 hover:bg-surface-700/60 disabled:opacity-50 shrink-0" title="测试连接">
                              {testing === cmKey ? <Loader2 size={11} className="animate-spin" /> : <Zap size={11} />} 测试
                            </button>
                            <button onClick={() => handleDeleteCustomModel(cm)} className="text-slate-500 hover:text-red-400 transition-colors p-1 shrink-0" title="删除"><Trash2 size={13} /></button>
                          </>
                        )}
                      </div>
                      {testRes && (
                        <div className={`mt-1.5 ml-7 text-xs ${testRes.success ? 'text-green-400' : 'text-red-400'}`}>
                          {testRes.success ? '✓ ' : '✗ '}{testRes.message}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </>
      )}

      {/* 添加 / 编辑模型弹窗 */}
      {(showAddModal || editData) && (
        <AddModelModal
          onClose={() => { setShowAddModal(false); setEditData(null); setCloudImportData(null); }}
          onAdd={handleAddModel}
          onUpdate={handleUpdateModel}
          editData={editData || undefined}
          prefilledData={cloudImportData || undefined}
        />
      )}
    </div>
  );
}
