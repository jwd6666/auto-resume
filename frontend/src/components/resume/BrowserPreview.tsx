import { useEffect, useRef, useState, useCallback, forwardRef, useImperativeHandle } from 'react';
import {
  ArrowLeft, ArrowRight, RotateCw, Globe, Lock, MousePointer2,
  X, FileText, Download, FileDown, Save, Loader2, Wand2,
  AlertTriangle, PanelLeftClose, PanelLeftOpen, FolderOpen,
} from 'lucide-react';
import { agentApi, type Job, type Resume } from '../../api/agentApi';

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
      tag = 'data-resume-section="' + el.getAttribute('data-resume-section') + '"';
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
      sendPickerResult({ tagName: tagNm, sectionId: sectionId, textContent: textContent });
  }

  function onKey(e) {
    if (e.key === 'Escape' && active) {
      window.__resumePickerDeactivate();
      sendPickerEsc();
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

    function sendPickerResult(data) {
      try { console.log('__RESUME_PICKER__' + JSON.stringify(data)); } catch(e) {}
      try { window.parent.postMessage({ type: '__RESUME_PICKER__', ...data }, '*'); } catch(e) {}
    }

    function sendPickerEsc() {
      try { console.log('__RESUME_PICKER_ESC__'); } catch(e) {}
      try { window.parent.postMessage({ type: '__RESUME_PICKER_ESC__' }, '*'); } catch(e) {}
    }

  document.addEventListener('mousemove', onMove, true);
  document.addEventListener('click', onDocClick, true);
  document.addEventListener('keydown', onKey, true);
})();
`;

function pathToFileUrl(p: string): string {
  if (!p) return '';
  if (p.startsWith('file:///')) return p;
  if (p.startsWith('file://')) return p;
  const normalized = p.replace(/\\/g, '/');
  if (normalized.startsWith('/')) return `file://${normalized}`;
  return `file:///${normalized}`;
}

const isElectron = typeof window !== 'undefined' && !!(window as any).autoresume?.apiBase;

export interface BrowserPreviewHandle {
  activatePicker: () => void;
  deactivatePicker: () => void;
  isPickerMode: () => boolean;
}

interface Props {
  resume: Resume | null;
  job: Job | null;
  sourceHtml: string;
  onSourceHtmlChange: (html: string) => void;
  onSaved: (r: Resume) => void;
  onInsertTag?: (tagName: string, sectionId?: string, textContent?: string) => void;
  onRestyle?: () => void;
  sidebarCollapsed?: boolean;
  onToggleSidebar?: () => void;
}

export const BrowserPreview = forwardRef<BrowserPreviewHandle, Props>(function BrowserPreview({
  resume, sourceHtml, onSourceHtmlChange, onSaved, onInsertTag, onRestyle,
  sidebarCollapsed, onToggleSidebar,
}, ref) {
  const [pickerMode, setPickerMode] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [err, setErr] = useState('');
  const [fileInfo, setFileInfo] = useState<{ id: number; path: string } | null>(null);
  const [canGoBack, setCanGoBack] = useState(false);
  const [canGoForward, setCanGoForward] = useState(false);

  const webviewRef = useRef<any>(null);
  const iframeRef = useRef<HTMLIFrameElement>(null);
  // webview 元素会随简历切换而重建，用 state 记录当前元素以便重新绑定事件监听
  const [webviewEl, setWebviewEl] = useState<any>(null);
  const setWebview = useCallback((el: any) => {
    webviewRef.current = el;
    setWebviewEl(el);
  }, []);
  const onInsertTagRef = useRef(onInsertTag);
  const onSourceChangeRef = useRef(onSourceHtmlChange);
  const prevSourceHtmlRef = useRef<string>(sourceHtml);

  useEffect(() => { onInsertTagRef.current = onInsertTag; }, [onInsertTag]);
  useEffect(() => { onSourceChangeRef.current = onSourceHtmlChange; }, [onSourceHtmlChange]);

  useEffect(() => {
    if (isElectron) return;
    const handler = (e: MessageEvent) => {
      if (e.data?.type === '__RESUME_PICKER__' && e.data?.tagName && onInsertTagRef.current) {
        onInsertTagRef.current(e.data.tagName, e.data.sectionId || '', e.data.textContent || '');
        setPickerMode(false);
      } else if (e.data?.type === '__RESUME_PICKER_ESC__') {
        setPickerMode(false);
      }
    };
    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, []);

  const activateIframePicker = useCallback(() => {
    const doc = iframeRef.current?.contentDocument;
    if (!doc) return;
    try {
      const script = doc.createElement('script');
      script.textContent = PICKER_SCRIPT;
      (doc.head || doc.documentElement).appendChild(script);
      (doc.defaultView as any)?.__resumePickerActivate?.();
    } catch { /* cross-origin */ }
  }, []);

  const deactivateIframePicker = useCallback(() => {
    try {
      (iframeRef.current?.contentDocument?.defaultView as any)?.__resumePickerDeactivate?.();
    } catch { /* */ }
  }, []);

  useEffect(() => {
    if (!sourceHtml) return;
    if (prevSourceHtmlRef.current === sourceHtml) return;
    if (!prevSourceHtmlRef.current) {
      prevSourceHtmlRef.current = sourceHtml;
      return;
    }
    prevSourceHtmlRef.current = sourceHtml;
    if (isElectron) {
      if (!webviewRef.current) return;
      const timer = setTimeout(() => {
        webviewRef.current?.reloadIgnoringCache?.() ?? webviewRef.current?.reload?.();
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [sourceHtml]);

  // 只有已解析出"当前这份简历"的本地文件路径时才用 file:// URL 挂载 webview。
  // 切换简历瞬间路径尚未解析时若先挂 http URL，之后 http→file:// 导航会被
  // Chromium 安全策略拦截，webview 卡在 http 页面导致本地头像无法显示。
  const fileReady = !!fileInfo && !!fileInfo.path && fileInfo.id === resume?.id;
  const currentUrl = fileReady && fileInfo ? pathToFileUrl(fileInfo.path) : (resume?.id != null ? agentApi.webviewResumeUrl(resume.id) : '');

  const runPickerAction = useCallback((fn: string) => {
    const wv = webviewRef.current;
    if (!wv || typeof wv.executeJavaScript !== 'function') return;
    try {
      wv.executeJavaScript(PICKER_SCRIPT, false);
      wv.executeJavaScript(`(window.${fn}) && window.${fn}()`, false);
    } catch { /* webview not ready */ }
  }, []);

  const activatePicker = useCallback(() => {
    setPickerMode(true);
    runPickerAction('__resumePickerActivate');
  }, [runPickerAction]);

  const deactivatePicker = useCallback(() => {
    setPickerMode(false);
    runPickerAction('__resumePickerDeactivate');
  }, [runPickerAction]);

  useImperativeHandle(ref, () => ({
    activatePicker,
    deactivatePicker,
    isPickerMode: () => pickerMode,
  }), [activatePicker, deactivatePicker, pickerMode]);

  useEffect(() => {
    if (pickerMode) {
      if (isElectron) {
        runPickerAction('__resumePickerActivate');
        try { webviewRef.current?.focus?.(); } catch { /* */ }
      } else {
        activateIframePicker();
      }
    } else {
      if (isElectron) {
        runPickerAction('__resumePickerDeactivate');
      } else {
        deactivateIframePicker();
      }
    }
  }, [pickerMode, runPickerAction, activateIframePicker, deactivateIframePicker]);

  useEffect(() => {
    if (!pickerMode) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setPickerMode(false);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [pickerMode]);

  const handleDidFinishLoad = useCallback(() => {
    const wv = webviewRef.current;
    if (!wv || typeof wv.executeJavaScript !== 'function') return;
    try {
      wv.executeJavaScript(PICKER_SCRIPT, false);
      if (pickerMode) {
        wv.executeJavaScript('window.__resumePickerActivate && window.__resumePickerActivate()', false);
      }
      try {
        setCanGoBack(wv.canGoBack());
        setCanGoForward(wv.canGoForward());
      } catch { /* */ }
    } catch { /* */ }
  }, [pickerMode]);

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

  useEffect(() => {
    const wv = webviewEl;
    if (!wv) return;
    const onDomReady = () => {
      try { wv.executeJavaScript(PICKER_SCRIPT, false); } catch { /* */ }
    };
    const onNavState = () => {
      try {
        setCanGoBack(wv.canGoBack());
        setCanGoForward(wv.canGoForward());
      } catch { /* */ }
    };
    wv.addEventListener('did-finish-load', handleDidFinishLoad);
    wv.addEventListener('dom-ready', onDomReady);
    wv.addEventListener('console-message', handleConsoleMessage);
    wv.addEventListener('did-navigate', onNavState);
    wv.addEventListener('did-navigate-in-page', onNavState);
    return () => {
      wv.removeEventListener('did-finish-load', handleDidFinishLoad);
      wv.removeEventListener('dom-ready', onDomReady);
      wv.removeEventListener('console-message', handleConsoleMessage);
      wv.removeEventListener('did-navigate', onNavState);
      wv.removeEventListener('did-navigate-in-page', onNavState);
    };
  }, [handleDidFinishLoad, handleConsoleMessage, webviewEl]);

  useEffect(() => {
    if (!resume?.id) { setFileInfo(null); return; }
    const unsubscribe = agentApi.subscribeResumeFileChange(resume.id, async (data: any) => {
      try {
        if (data.path) setFileInfo({ id: resume.id, path: data.path });
        const fileData = await agentApi.getResumeFile(resume.id);
        if (fileData.path) setFileInfo({ id: resume.id, path: fileData.path });
        if (fileData.html) {
          onSourceChangeRef.current(fileData.html);
          setDirty(false);
        }
        webviewRef.current?.reload?.();
      } catch { /* */ }
    });
    agentApi.getResumeFile(resume.id).then(d => {
      if (d.path) setFileInfo({ id: resume.id, path: d.path });
      if (d.html) onSourceChangeRef.current(d.html);
    }).catch(() => {});
    return unsubscribe;
  }, [resume?.id]);

  const handleReload = useCallback(() => {
    if (isElectron) {
      webviewRef.current?.reloadIgnoringCache?.() ?? webviewRef.current?.reload?.();
    } else if (iframeRef.current) {
      const doc = iframeRef.current.contentDocument;
      if (doc) {
        doc.open();
        doc.write(sourceHtml || '');
        doc.close();
      }
    }
  }, [sourceHtml]);

  const handleGoBack = useCallback(() => {
    if (isElectron) {
      const wv = webviewRef.current;
      if (!wv) return;
      wv.goBack?.();
      wv.reload?.();
    }
  }, []);

  const handleGoForward = useCallback(() => {
    if (isElectron) {
      const wv = webviewRef.current;
      if (!wv) return;
      wv.goForward?.();
      wv.reload?.();
    }
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

  const handleExportPdf = async () => {
    const html = resume?.rendered_html || sourceHtml || '';
    if (!html) return;
    try {
      if (resume && dirty) {
        const saved = await agentApi.updateResume(resume.id, { rendered_html: sourceHtml });
        onSaved(saved);
        setDirty(false);
      }
      if (resume) {
        const fileData = await agentApi.getResumeFile(resume.id);
        const fp = fileData.path;
        const autoresume = (window as any).autoresume;
        if (autoresume?.openLocalFileAndPrint) {
          const result = await autoresume.openLocalFileAndPrint(fp);
          if (!result?.ok) setErr(result?.error || '打开文件失败');
          return;
        }
      }
      const w = window.open('', '_blank');
      if (!w) { setErr('导出 PDF 需要打开新窗口，请允许浏览器弹窗后重试'); return; }
      w.document.open();
      w.document.write(html);
      w.document.close();
      const doPrint = () => {
        setTimeout(() => { try { w.focus(); w.print(); } catch { /* */ } }, 120);
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

  const displayName = resume?.title || (resume ? `简历 #${resume.id}` : '');
  const isFileUrl = currentUrl.startsWith('file://');

  return (
    <div className="flex flex-col h-full min-h-0 bg-surface-850">
      {/* Tab bar */}
      <div className="shrink-0 flex items-end bg-[#1a1f2e] border-b border-slate-700/30">
        <div className="flex items-center h-[34px] px-1 gap-0.5">
          {resume ? (
            <div className="flex items-center gap-1.5 px-3 h-[30px] rounded-t-lg bg-surface-900/80 border border-b-0 border-slate-700/30 text-xs text-slate-200 select-none">
              <FileText size={12} className="text-accent-blue shrink-0" />
              <span className="truncate max-w-[160px]">{displayName}</span>
            </div>
          ) : (
            <div className="flex items-center gap-1.5 px-3 h-[30px] rounded-t-lg text-xs text-slate-500 select-none">
              <Globe size={12} className="shrink-0" />
              新标签页
            </div>
          )}
        </div>
        <div className="flex-1" />
        {onToggleSidebar && (
          <button
            onClick={onToggleSidebar}
            className="mr-2 mb-1 p-1 rounded text-slate-500 hover:text-slate-300 hover:bg-slate-700/40 transition-colors"
            title={sidebarCollapsed ? '展开聊天面板' : '收起聊天面板'}
          >
            {sidebarCollapsed ? <PanelLeftOpen size={14} /> : <PanelLeftClose size={14} />}
          </button>
        )}
      </div>

      {/* Address bar */}
      <div className="shrink-0 flex items-center gap-1.5 px-2 py-1.5 bg-[#1a1f2e] border-b border-slate-700/20">
        <div className="flex items-center gap-0.5">
          <button
            onClick={handleGoBack}
            disabled={!canGoBack}
            className="p-1 rounded hover:bg-slate-700/40 text-slate-400 disabled:opacity-25 disabled:cursor-not-allowed transition-colors"
            title="后退"
          >
            <ArrowLeft size={13} />
          </button>
          <button
            onClick={handleGoForward}
            disabled={!canGoForward}
            className="p-1 rounded hover:bg-slate-700/40 text-slate-400 disabled:opacity-25 disabled:cursor-not-allowed transition-colors"
            title="前进"
          >
            <ArrowRight size={13} />
          </button>
          <button
            onClick={handleReload}
            className="p-1 rounded hover:bg-slate-700/40 text-slate-400 transition-colors"
            title="刷新"
          >
            <RotateCw size={13} />
          </button>
        </div>

        <div className="flex items-center gap-1.5 bg-[#0f1219] border border-slate-700/40 rounded-full px-3 py-1 flex-1 min-w-0">
          {isFileUrl ? <FolderOpen size={10} className="text-amber-400/70 shrink-0" /> : <Lock size={10} className="text-emerald-500/70 shrink-0" />}
          <span className="text-[11px] text-slate-400 truncate select-all">{currentUrl || 'about:blank'}</span>
        </div>

        <div className="flex items-center gap-0.5">
          <button
            onClick={() => setPickerMode(p => !p)}
            className={`p-1.5 rounded transition-colors ${
              pickerMode
                ? 'bg-green-500/20 text-green-400 hover:bg-green-500/30'
                : 'hover:bg-slate-700/40 text-slate-400 hover:text-slate-200'
            }`}
            title={pickerMode ? '退出元素选择 (Esc)' : '元素选择模式'}
          >
            <MousePointer2 size={13} />
          </button>

          {onRestyle && (
            <button
              onClick={onRestyle}
              className="p-1.5 rounded hover:bg-amber-500/20 text-slate-400 hover:text-amber-400 transition-colors"
              title="重新排版简历"
            >
              <Wand2 size={13} />
            </button>
          )}

          <button
            onClick={handleSave}
            disabled={saving}
            className={`p-1.5 rounded transition-colors ${
              dirty ? 'text-emerald-400 hover:bg-emerald-500/20' : 'text-slate-400 hover:bg-slate-700/40 hover:text-slate-200'
            } disabled:opacity-40`}
            title={dirty ? '保存修改' : '已保存'}
          >
            {saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
          </button>

          <button
            onClick={handleExportPdf}
            className="p-1.5 rounded hover:bg-slate-700/40 text-slate-400 hover:text-slate-200 transition-colors"
            title="导出 PDF"
          >
            <FileDown size={13} />
          </button>

          <button
            onClick={handleExportHtml}
            className="p-1.5 rounded hover:bg-slate-700/40 text-slate-400 hover:text-slate-200 transition-colors"
            title="导出 HTML"
          >
            <Download size={13} />
          </button>
        </div>
      </div>

      {/* Error bar */}
      {err && (
        <div className="shrink-0 mx-2 mt-1 px-3 py-1.5 rounded-lg bg-red-500/10 border border-red-500/30 flex items-center gap-2 text-xs text-red-300">
          <AlertTriangle size={12} className="shrink-0" />
          <span className="flex-1 truncate">{err}</span>
          <button onClick={() => setErr('')} className="text-red-400 hover:text-red-300 shrink-0">
            <X size={12} />
          </button>
        </div>
      )}

      {/* Picker mode indicator */}
      {pickerMode && (
        <div className="shrink-0 mx-2 mt-1 px-3 py-1.5 rounded-lg bg-green-500/10 border border-green-500/30 flex items-center gap-2 text-xs text-green-300">
          <MousePointer2 size={12} className="shrink-0" />
          <span>元素选择模式：悬浮高亮，点击拾取元素标签插入AI对话，ESC退出</span>
          <button onClick={() => setPickerMode(false)} className="text-green-400 hover:text-green-300 shrink-0 ml-auto">
            退出
          </button>
        </div>
      )}

      {/* Preview content */}
      <div className="flex-1 min-h-0 relative bg-white">
        {resume && sourceHtml ? (
          isElectron && fileReady ? (
            <webview
              ref={setWebview}
              src={currentUrl}
              partition="persist:resume-preview"
              style={{ width: '100%', height: '100%', display: 'inline-flex' }}
            />
          ) : (
            <iframe
              ref={iframeRef}
              srcDoc={sourceHtml}
              sandbox="allow-scripts allow-same-origin"
              style={{ width: '100%', height: '100%', border: 'none', background: '#fff' }}
              title="简历预览"
            />
          )
        ) : (
          <div className="h-full flex items-center justify-center bg-surface-900/50">
            <div className="text-center">
              <div className="w-16 h-16 rounded-2xl bg-slate-800/60 flex items-center justify-center mb-4 mx-auto">
                <Globe size={24} className="text-slate-600" />
              </div>
              <p className="text-sm text-slate-400">简历预览</p>
              <p className="text-xs text-slate-600 mt-1">
                {resume ? (isElectron && fileInfo ? '正在加载简历文件…' : 'AI 正在生成简历预览…') : '请先选择或上传简历'}
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Status bar */}
      <div className="shrink-0 flex items-center gap-2 px-3 py-1 bg-[#1a1f2e] border-t border-slate-700/20 text-[11px] text-slate-500">
        {isElectron && fileReady && fileInfo?.path && (
          <span className="truncate max-w-[300px]" title={fileInfo.path}>
            {fileInfo.path}
          </span>
        )}
        {!isElectron && resume && (
          <span>浏览器预览模式</span>
        )}
        <div className="flex-1" />
        {resume && (
          <span>{resume.file_type?.toUpperCase() || 'HTML'}</span>
        )}
      </div>
    </div>
  );
});
