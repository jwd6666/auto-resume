/** 模型管理 — 对接后端 /agent/settings，支持自定义模型配置 + 选中激活 */
import { useEffect, useState } from 'react';
import { Check, Loader2, Zap, ZapOff, Plus, Trash2, Pencil, ListChecks } from 'lucide-react';
import { agentApi, type SettingsInfo, type CustomModel } from '../api/agentApi';
import { AddModelModal, type CustomModelData } from './AddModelModal';

export function ModelManagement() {
  const [settings, setSettings] = useState<SettingsInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, { success: boolean; message: string }>>({});
  // 选中的 provider + model
  const [selProvider, setSelProvider] = useState('');
  const [selModel, setSelModel] = useState('');

  // 添加模型弹窗
  const [showAddModal, setShowAddModal] = useState(false);
  // 编辑模型弹窗（非空时进入编辑模式）
  const [editData, setEditData] = useState<{ id: string } & Partial<CustomModelData> | null>(null);

  // 批量管理模式
  const [batchMode, setBatchMode] = useState(false);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [batchDeleting, setBatchDeleting] = useState(false);

  const customModels: CustomModel[] = settings?.custom_models || [];

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
      // 同步选中态的 model_id（用户可能改了模型 ID）
      if (selProvider === `custom:${editData.id}`) {
        setSelModel(updated.model_id);
      }
      setEditData(null);
      window.dispatchEvent(new CustomEvent('models-updated'));
    } catch (e: any) {
      alert(`更新模型失败：${e.message}`);
    }
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

  return (
    <div className="p-5 h-full flex flex-col animate-fade-in">
      {/* 页头 */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h1 className="text-xl font-bold text-slate-100">模型管理</h1>
          <p className="text-sm text-slate-500 mt-0.5">配置自定义 AI 模型，选中即激活</p>
        </div>
        <button
          onClick={() => setShowAddModal(true)}
          className="btn-primary"
        >
          <Plus size={14} /> 添加模型
        </button>
      </div>

      {selProvider.startsWith('custom:') && selModel ? (
        <div className="card p-3 mb-4 flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-accent-blue/20 to-accent-purple/20 flex items-center justify-center">
            <Zap size={18} className="text-accent-blue" />
          </div>
          <div>
            <p className="text-xs text-slate-500">当前使用</p>
            <p className="text-sm font-medium text-slate-200">
              {customModels.find(c => `custom:${c.id}` === selProvider)?.display_name || selModel}
            </p>
          </div>
        </div>
      ) : (
        <div className="card p-3 mb-4 flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-surface-800/60 flex items-center justify-center">
            <ZapOff size={18} className="text-slate-600" />
          </div>
          <div>
            <p className="text-xs text-slate-500">当前使用</p>
            <p className="text-sm font-medium text-slate-400">未设置 — 请添加并选中一个模型</p>
          </div>
        </div>
      )}

      <div className="flex items-center gap-2 mb-3">
        {customModels.length > 0 && (
          <button
            onClick={() => { setBatchMode(m => !m); setChecked(new Set()); }}
            className={`flex items-center gap-1 text-xs px-3 py-1.5 rounded-md transition-colors ${batchMode ? 'bg-accent-blue/20 text-accent-blue' : 'bg-surface-700/50 text-slate-400 hover:text-slate-200 hover:bg-surface-700'}`}
          >
            <ListChecks size={14} />
            批量删除
          </button>
        )}
      </div>

      {/* 批量操作工具栏 */}
      {batchMode && (
        <div className="flex items-center gap-2 mb-3 px-3 py-2 rounded-lg bg-accent-blue/10 border border-accent-blue/25 animate-fade-in">
          <button
            onClick={() => setChecked(checked.size === customModels.length && customModels.length > 0 ? new Set() : new Set(customModels.map(m => m.id)))}
            className="text-xs text-accent-blue hover:underline"
          >
            {checked.size === customModels.length && customModels.length > 0 ? '取消全选' : '全选'}
          </button>
          <span className="text-xs text-slate-500">已选 {checked.size} 项</span>
          <div className="flex-1" />
          <button
            onClick={handleBatchDelete}
            disabled={checked.size === 0 || batchDeleting}
            className="flex items-center gap-1 text-xs px-2.5 py-1 rounded bg-red-500/20 text-red-400 hover:bg-red-500/30 disabled:opacity-40"
          >
            {batchDeleting ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
            删除所选
          </button>
          <button onClick={() => { setBatchMode(false); setChecked(new Set()); }} className="text-xs text-slate-500 hover:text-slate-300">
            退出
          </button>
        </div>
      )}

      {/* 模型列表 */}
      <div className="flex-1 overflow-y-auto scrollbar-thin pr-1">
        {customModels.length === 0 ? (
          <div className="card py-12 text-center">
            <p className="text-sm text-slate-500">暂无模型</p>
            <p className="text-xs text-slate-600 mt-1">点击上方「添加模型」按钮新建</p>
          </div>
        ) : (
          <div className="space-y-2">
            {customModels.map(cm => {
              const cmKey = `custom:${cm.id}`;
              const isActive = selProvider === cmKey;
              const testRes = testResult[cmKey];
              const displayName = cm.display_name || cm.model_id;
              return (
                <div
                  key={cm.id}
                  className={`card p-3 transition-all ${isActive ? 'border-accent-blue/40' : ''}`}
                >
                  <div className="flex items-center gap-2">
                    {batchMode ? (
                      <input
                        type="checkbox"
                        checked={checked.has(cm.id)}
                        onChange={() => toggleCheck(cm.id)}
                        className="accent-[#5b8def] shrink-0"
                      />
                    ) : (
                      <button
                        onClick={() => activateModel(cmKey, cm.model_id)}
                        className={`w-5 h-5 rounded-full border-2 flex items-center justify-center transition-all shrink-0 ${
                          isActive ? 'border-accent-blue bg-accent-blue' : 'border-slate-600 hover:border-slate-400'
                        }`}
                      >
                        {isActive && <Check size={11} className="text-white" />}
                      </button>
                    )}
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <p className={`text-sm font-medium truncate ${isActive ? 'text-accent-blue' : 'text-slate-300'}`}>
                          {displayName}
                        </p>
                        {cm.multimodal && (
                          <span className="text-[10px] px-1 py-0.5 rounded bg-accent-purple/15 text-accent-purple">多模态</span>
                        )}
                        {cm.full_url && (
                          <span className="text-[10px] px-1 py-0.5 rounded bg-slate-600/30 text-slate-400">完整URL</span>
                        )}
                      </div>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-xs text-slate-500 font-mono truncate">{cm.model_id}</span>
                        <span className="text-xs text-slate-700">·</span>
                        <span className="text-xs text-slate-600 truncate">{cm.base_url}</span>
                      </div>
                    </div>
                    {!batchMode && (
                      <>
                        <button
                          onClick={() => handleEdit(cm)}
                          className="text-slate-500 hover:text-accent-blue transition-colors p-1 shrink-0"
                          title="编辑"
                        >
                          <Pencil size={13} />
                        </button>
                        <button
                          onClick={() => handleTest(cmKey, cm.model_id)}
                          disabled={testing === cmKey}
                          className="flex items-center gap-1 text-xs px-2 py-1 rounded-md bg-surface-700/40 text-slate-300 hover:bg-surface-700/60 disabled:opacity-50 shrink-0"
                          title="测试连接"
                        >
                          {testing === cmKey ? <Loader2 size={11} className="animate-spin" /> : <Zap size={11} />}
                          测试
                        </button>
                        <button
                          onClick={() => handleDeleteCustomModel(cm)}
                          className="text-slate-500 hover:text-red-400 transition-colors p-1 shrink-0"
                          title="删除"
                        >
                          <Trash2 size={13} />
                        </button>
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

      {/* 底部提示 */}
      <div className="mt-3 px-3 py-2 rounded-lg bg-surface-800/40 text-xs text-slate-500 flex items-center gap-2">
        <ZapOff size={12} />
        提示：选中模型即自动激活，Agent 简历优化功能将使用该模型进行 AI 对话和评估。
      </div>

      {/* 添加 / 编辑模型弹窗 */}
      {(showAddModal || editData) && (
        <AddModelModal
          onClose={() => { setShowAddModal(false); setEditData(null); }}
          onAdd={handleAddModel}
          onUpdate={handleUpdateModel}
          editData={editData || undefined}
        />
      )}
    </div>
  );
}
