import { useEffect, useRef, useState, useCallback } from 'react';
import {
  Save, Download, Loader2, FileDown,
  AlertTriangle, X, FileText, RefreshCw, Globe, MousePointer2, Wand2, Lock,
} from 'lucide-react';
import { agentApi, type Job, type Resume } from '../../../api/agentApi';

interface Props {
  resume: Resume | null;
  job: Job | null;
  onSaved: (r: Resume) => void;
  onInsertTag?: (tagName: string, sectionId?: string, textContent?: string) => void;
  sourceHtml: string;
  onSourceHtmlChange: (html: string) => void;
  onRestyle?: () => void;
}

/**
 * 在 webview 内运行的「元素选择器」脚本。
 * - 通过 window.__pickResume 暴露 activate/deactivate 供父层 executeJavaScript 调用
 * - 拾取结果用 console.log('__RESUME_PICKER__', JSON) 上报，父层监听 webview 的 console-message
 */
const PICKER_SCRIPT = `
(() => {
  if (window.__resumePickerInstalled) return;
  window.__resumePickerInstalled = true;

  var active = false;
  var hlOverlay = null;
  var tagLabel = null;

  function ensureUI() {
    if (hlOverlay) return;
    hlOverlay = document.createElement('div');
    hlOverlay.style.cssText = 'position:absolute;pointer-events:none;border:1.5px solid #22c55e;background:rgba(34,197,94,0.06);z-index:99990;transition:all 0.08s ease;display:none;border-radius:2px;';
    document.body.appendChild(hlOverlay);
    tagLabel = document.createElement('div');
    tagLabel.style.cssText = 'position:absolute;z-index:99991;pointer-events:none;display:none;font:11px/1.2 -apple-system,BlinkMacSystemFont,sans-serif;color:#166534;background:rgba(187,247,208,0.92);padding:1px 6px;border-radius:3px;white-space:nowrap;box-shadow:0 1px 3px rgba(0,0,0,0.12);';
    document.body.appendChild(tagLabel);
  }

  function rect(el) {
    var r = el.getBoundingClientRect();
    return { t: r.top + window.scrollY, l: r.left + window.scrollX, w: r.width, h: r.height };
  }

  function showFor(el) {
    if (!hlOverlay) return;
    var r = rect(el);
    hlOverlay.style.display = 'block';
    hlOverlay.style.top = r.t + 'px';
    hlOverlay.style.left = r.l + 'px';
    hlOverlay.style.width = r.w + 'px';
    hlOverlay.style.height = r.h + 'px';
    var tag = el.tagName.toLowerCase();
    if (el.getAttribute('data-resume-section')) {
      tag = 'data-resume-section=\"' + el.getAttribute('data-resume-section') + '\"';
    }
    tagLabel.textContent = tag;
    tagLabel.style.display = 'block';
    tagLabel.style.top = Math.max(r.t - 20, 0) + 'px';
    tagLabel.style.left = r.l + 'px';
  }

  function hide() {
    if (hlOverlay) hlOverlay.style.display = 'none';
    if (tagLabel) tagLabel.style.display = 'none';
  }

  function cleanup() {
    hide();
    if (hlOverlay) { hlOverlay.remove(); hlOverlay = null; }
    if (tagLabel) { tagLabel.remove(); tagLabel = null; }
  }

  function findSectionEl(el) {
    var walk = el;
    while (walk && walk !== document.body) {
      if (walk.getAttribute && walk.getAttribute('data-resume-section')) return walk;
      walk = walk.parentElement;
    }
    return null;
  }

  function onMove(e) {
    if (!active) return;
    var el = e.target;
    if (!el || el === hlOverlay || el === tagLabel || el === document.body || el === document.documentElement) {
      hide();
      return;
    }
    var target = findSectionEl(el) || el;
    ensureUI();
    showFor(target);
  }

  function onDocClick(e) {
    if (!active) return;
    if (e.target === hlOverlay || e.target === tagLabel) return;
    e.preventDefault();
    e.stopPropagation();
    var el = e.target;
    if (!el || el === document.body || el === document.documentElement) return;
    var target = findSectionEl(el) || el;
    var tagNm = target.tagName.toLowerCase();
    var sectionId = target.getAttribute('data-resume-section') || '';
    var textContent = (target.textContent || '').trim().slice(0, 300);
    window.__resumePickerDeactivate();
    console.log('__RESUME_PICKER__' + JSON.stringify({ tagName: tagNm, sectionId: sectionId, textContent: textContent }));
  }

  function onKey(e) {
    if (e.key === 'Escape' && active) {
      window.__resumePickerDeactivate();
      console.log('__RESUME_PICKER_ESC__');
    }
  }

  window.__resumePickerActivate = function() {
    active = true;
    document.body.style.cursor = 'crosshair';
    ensureUI();
  };

  window.__resumePickerDeactivate = function() {
    active = false;
    document.body.style.cursor = '';
    cleanup();
  };

  document.addEventListener('mousemove', onMove, true);
  document.addEventListener('click', onDocClick, true);
  document.addEventListener('keydown', onKey, true);
})();
`;

export function ResumeEditor({ resume, onSaved, onInsertTag, sourceHtml, onSourceHtmlChange, onRestyle }: Props) {
  const [pickerMode, setPickerMode] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const [dirty, setDirty] = useState(false);
  const [filePath, setFilePath] = useState<string>('');

  const webviewRef = useRef<any>(null);

  const resumeUrl = resume?.id != null ? agentApi.webviewResumeUrl(resume.id) : '';

  /** 向 webview 注入元素选择器脚本（幂等），返回是否成功 */
  const ensurePickerInstalled = useCallback((): boolean => {
    const wv = webviewRef.current;
    if (!wv || typeof wv.executeJavaScript !== 'function') return false;
    try {
      wv.executeJavaScript(PICKER_SCRIPT, false);
      return true;
    } catch {
      return false;
    }
  }, []);

  /** 向 webview 调用元素选择器的启用/停用函数 */
  const runPickerAction = useCallback((fn: string) => {
    const wv = webviewRef.current;
    if (!wv || typeof wv.executeJavaScript !== 'function') return;
    try {
      // 每次操作前先注入脚本，避免 webview 重新加载后脚本丢失导致功能失效
      wv.executeJavaScript(PICKER_SCRIPT, false);
      wv.executeJavaScript(`(window.${fn}) && window.${fn}()`, false);
    } catch { /* webview 未就绪 */ }
  }, []);

  const activatePicker = useCallback(() => runPickerAction('__resumePickerActivate'), [runPickerAction]);
  const deactivatePicker = useCallback(() => runPickerAction('__resumePickerDeactivate'), [runPickerAction]);

  useEffect(() => {
    if (pickerMode) activatePicker();
    else deactivatePicker();
  }, [pickerMode, activatePicker, deactivatePicker]);

  /** webview 加载完成后：重新注入选择器，若处于选择模式则激活 */
  const handleDidFinishLoad = useCallback(() => {
    const wv = webviewRef.current;
    if (!wv || typeof wv.executeJavaScript !== 'function') return;
    try {
      wv.executeJavaScript(PICKER_SCRIPT, false);
      if (pickerMode) {
        wv.executeJavaScript('window.__resumePickerActivate && window.__resumePickerActivate()', false);
      }
    } catch { /* */ }
  }, [pickerMode]);

  /** 选择模式开启后同时聚焦 webview，避免内部按钮拦截页面 keydown */
  useEffect(() => {
    if (!pickerMode) return;
    try { webviewRef.current?.focus?.(); } catch { /* */ }
  }, [pickerMode]);

  /** webview 触发 console 消息：捕获元素选择结果 */
  const handleConsoleMessage = useCallback((e: any) => {
    const msg = typeof e?.message === 'string' ? e.message : '';
    if (msg?.startsWith('__RESUME_PICKER__')) {
      try {
        const data = JSON.parse(msg.slice('__RESUME_PICKER__'.length));
        if (data?.tagName && onInsertTagRef.current) onInsertTagRef.current(data.tagName, data.sectionId || '', data.textContent || '');
        setPickerMode(false);
      } catch { /* */ }
    } else if (msg === '__RESUME_PICKER_ESC__') {
      setPickerMode(false);
    }
  }, []);

  const onInsertTagRef = useRef(onInsertTag);
  useEffect(() => { onInsertTagRef.current = onInsertTag; }, [onInsertTag]);

  useEffect(() => {
    const wv = webviewRef.current;
    if (!wv) return;
    const onDomReady = () => {
      try { wv.executeJavaScript(PICKER_SCRIPT, false); } catch { /* */ }
    };
    wv.addEventListener('did-finish-load', handleDidFinishLoad);
    wv.addEventListener('dom-ready', onDomReady);
    wv.addEventListener('console-message', handleConsoleMessage);
    return () => {
      wv.removeEventListener('did-finish-load', handleDidFinishLoad);
      wv.removeEventListener('dom-ready', onDomReady);
      wv.removeEventListener('console-message', handleConsoleMessage);
    };
  }, [handleDidFinishLoad, handleConsoleMessage, ensurePickerInstalled]);

  useEffect(() => {
    if (!pickerMode) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setPickerMode(false);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [pickerMode]);

  /** 订阅简历文件变更：AI 写入新文件后自动刷新内置浏览器 */
  useEffect(() => {
    if (!resume?.id) { setFilePath(''); return; }
    const unsubscribe = agentApi.subscribeResumeFileChange(resume.id, async (data: any) => {
      try {
        if (data.path) setFilePath(data.path);
        const fileData = await agentApi.getResumeFile(resume.id);
        if (fileData.path) setFilePath(fileData.path);
        if (fileData.html) {
          onSourceChangeRef.current(fileData.html);
          setDirty(false);
        }
        // 刷新内置浏览器，使磁盘文件的最新内容生效
        webviewRef.current?.reload?.();
      } catch { /* */ }
    });
    agentApi.getResumeFile(resume.id).then(d => {
      if (d.path) setFilePath(d.path);
      if (d.html) onSourceChangeRef.current(d.html);
    }).catch(() => {});
    return unsubscribe;
  }, [resume?.id]);

  const onSourceChangeRef = useRef(onSourceHtmlChange);
  useEffect(() => { onSourceChangeRef.current = onSourceHtmlChange; }, [onSourceHtmlChange]);

  const handleReload = useCallback(() => {
    webviewRef.current?.reloadIgnoringCache?.() ?? webviewRef.current?.reload?.();
  }, []);

  const handleSave = async () => {
    if (!resume) return;
    setSaving(true);
    setErr('');
    try {
      const updated = await agentApi.updateResume(resume.id, {
        rendered_html: sourceHtml,
      });
      setDirty(false);
      onSaved(updated);
    } catch (e: any) {
      setErr(e.message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const handleExportHtml = () => {
    const html = sourceHtml || '';
    if (!html) return;
    const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${(resume?.title || '我的简历').replace(/[\\/:*?"<>|]/g, '_')}.html`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1500);
  };

  /** 导出 PDF：先确保本地文件已写入，然后通过 Electron 在系统浏览器打开并 Ctrl+P */
  const handleExportPdf = async () => {
    const html = resume?.rendered_html || sourceHtml || '';
    if (!html) return;

    try {
      // 先保存最新 HTML 到后端（确保磁盘文件是最新的）
      if (resume && dirty) {
        const saved = await agentApi.updateResume(resume.id, { rendered_html: sourceHtml });
        onSaved(saved);
        setDirty(false);
      }

      if (resume) {
        // 获取磁盘文件路径
        const fileData = await agentApi.getResumeFile(resume.id);
        const filePath = fileData.path;

        // 通过 Electron IPC 在系统浏览器中打开文件并发送 Ctrl+P
        const autoresume = (window as any).autoresume;
        if (autoresume?.openLocalFileAndPrint) {
          const result = await autoresume.openLocalFileAndPrint(filePath);
          if (!result?.ok) {
            setErr(result?.error || '打开文件失败');
          }
          return;
        }
      }

      // 降级：非 Electron 环境（浏览器直接打开），使用旧的 window.open + print
      const w = window.open('', '_blank');
      if (!w) {
        setErr('导出 PDF 需要打开新窗口，请允许浏览器弹窗后重试');
        return;
      }
      w.document.open();
      w.document.write(html);
      w.document.close();
      const doPrint = () => {
        setTimeout(() => {
          try { w.focus(); w.print(); } catch { /* */ }
        }, 120);
      };
      if (w.document.readyState === 'complete') {
        setTimeout(doPrint, 500);
      } else {
        w.addEventListener('load', () => setTimeout(doPrint, 400));
        setTimeout(doPrint, 2800);
      }
    } catch (e: any) {
      setErr(e.message || '导出 PDF 失败');
    }
  };

  if (!resume) {
    return (
      <div className="flex-1 flex flex-col items-center justify-center text-center py-16">
        <FileText size={26} className="text-slate-700 mb-3" />
        <p className="text-sm text-slate-400">请先在左侧选择或上传简历</p>
        <p className="text-xs text-slate-600 mt-1">上传 PDF / Word / 图片，AI 自动生成简历</p>
      </div>
    );
  }

  if (!sourceHtml) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="card p-8 text-center max-w-md animate-fade-in">
          <div className="w-12 h-12 rounded-xl bg-accent-blue/15 flex items-center justify-center mx-auto mb-4">
            <FileText size={22} className="text-accent-blue" />
          </div>
          <h3 className="text-base font-semibold text-slate-200">暂无预览内容</h3>
          <p className="text-sm text-slate-500 mt-2 leading-relaxed">
            上传简历文件后，AI 将自动生成 HTML 简历并在此处预览。
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="no-print shrink-0 flex items-center gap-3 flex-wrap pb-3 mb-3 border-b border-slate-700/30">
        <button
          onClick={() => setPickerMode(p => !p)}
          className={`flex items-center gap-1.5 px-2.5 py-1 text-xs rounded-lg transition-colors ${
            pickerMode
              ? 'bg-green-500/20 text-green-400 border border-green-500/30'
              : 'bg-surface-900/60 text-slate-400 hover:text-slate-200 border border-transparent'
          }`}
          title={pickerMode ? '退出元素选择 (Esc)' : '元素选择模式'}
        >
          <MousePointer2 size={13} /> {pickerMode ? '选择中...' : '元素选择'}
        </button>

        {onRestyle && (
          <button
            onClick={onRestyle}
            className="flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-lg bg-amber-500/15 text-amber-400 hover:bg-amber-500/25 transition-colors"
            title="重新排版简历"
          >
            <Wand2 size={13} /> 重新排版
          </button>
        )}

        <div className="flex-1" />

        <button
          onClick={handleSave}
          disabled={saving}
          className={`flex items-center gap-1.5 text-xs px-3.5 py-1.5 rounded-lg transition-colors ${
            dirty ? 'bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30' : 'bg-slate-700/40 text-slate-500'
          }`}
        >
          {saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
          {dirty ? '保存修改' : '已保存'}
        </button>

        <button
          onClick={handleExportPdf}
          className="flex items-center gap-1.5 text-xs px-3.5 py-1.5 rounded-lg bg-accent-purple/20 text-accent-purple hover:bg-accent-purple/30 transition-colors"
          title="将网页简历原样导出为 PDF（浏览器打印另存为 PDF）"
        >
          <FileDown size={13} /> 导出 PDF
        </button>

        <button
          onClick={handleExportHtml}
          className="flex items-center gap-1.5 text-xs px-3.5 py-1.5 rounded-lg bg-accent-blue/20 text-accent-blue hover:bg-accent-blue/30 transition-colors"
        >
          <Download size={13} /> 导出 HTML
        </button>
      </div>

      {err && (
        <div className="mb-3 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 flex items-start gap-2">
          <AlertTriangle size={13} className="text-red-400 shrink-0 mt-0.5" />
          <p className="text-xs text-red-300/90 flex-1">{err}</p>
          <button onClick={() => setErr('')} className="text-red-400 hover:text-red-300"><X size={13} /></button>
        </div>
      )}

      {/* 内置浏览器地址栏 */}
      <div className="no-print shrink-0 flex items-center gap-2 mb-2 bg-surface-900/60 border border-slate-700/50 rounded-md px-2 py-1">
        <Globe size={13} className="text-accent-blue shrink-0" />
        <div className="flex items-center gap-1.5 bg-surface-800/80 border border-slate-700/40 rounded px-2 py-1 flex-1 min-w-0">
          <Lock size={11} className="text-emerald-400 shrink-0" />
          <span className="text-xs text-slate-400 truncate">{resumeUrl}</span>
        </div>
        <button
          onClick={handleReload}
          className="flex items-center gap-1 px-2 py-1 text-xs rounded-lg bg-surface-800 text-slate-300 hover:bg-surface-700 transition-colors"
          title="刷新预览"
        >
          <RefreshCw size={12} />
        </button>
        {filePath && (
          <span className="hidden lg:flex items-center gap-1 text-[11px] text-slate-500 max-w-[160px] truncate" title={filePath}>
            <span className="truncate">{filePath.split(/[\\/]/).pop()}</span>
          </span>
        )}
      </div>

      {/* 内置浏览器预览（Electron webview，真实渲染磁盘 HTML 文件） */}
      <div className="flex-1 min-h-0 relative border border-slate-700/50 rounded-md overflow-hidden bg-white">
        <webview
          ref={webviewRef}
          src={resumeUrl}
          partition="persist:resume-preview"
          style={{ width: '100%', height: '100%', display: 'inline-flex' }}
        />
      </div>
      <p className="no-print text-[11px] text-slate-600 mt-2 flex items-center gap-1 shrink-0">
        {pickerMode
          ? '🎯 元素选择模式：悬浮高亮，点击拾取元素标签插入对话，ESC退出'
          : '内置浏览器预览：真实渲染简历 HTML，跟随 AI 修改实时刷新；点击「元素选择」拾取简历模块标签插入AI对话'
        }
      </p>
    </div>
  );
}