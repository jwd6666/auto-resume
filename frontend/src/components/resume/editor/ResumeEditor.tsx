import { useEffect, useRef, useState, useCallback, useMemo } from 'react';
import {
  Save, Download, Loader2, FileDown,
  AlertTriangle, X, FileText, Code2, Eye, Send, HardDrive, MousePointer2, Wand2,
} from 'lucide-react';
import { agentApi, type Job, type Resume } from '../../../api/agentApi';

const A4_H = 1123;

interface Props {
  resume: Resume | null;
  job: Job | null;
  onSaved: (r: Resume) => void;
  onInsertTag?: (tagName: string, sectionId?: string, textContent?: string) => void;
  sourceHtml: string;
  onSourceHtmlChange: (html: string) => void;
  onRestyle?: () => void;
}

function stripMediaPrintCss(css: string): string {
  let result = '';
  let cursor = 0;
  const marker = /@media\s+print\s*\{/gi;
  let match: RegExpExecArray | null;
  while ((match = marker.exec(css))) {
    const open = css.indexOf('{', match.index);
    let depth = 0;
    let end = -1;
    for (let i = open; i < css.length; i += 1) {
      if (css[i] === '{') depth += 1;
      else if (css[i] === '}') {
        depth -= 1;
        if (depth === 0) {
          end = i + 1;
          break;
        }
      }
    }
    if (end < 0) break;
    result += css.slice(cursor, match.index);
    cursor = end;
    marker.lastIndex = end;
  }
  return result + css.slice(cursor);
}

const IFRAME_SCRIPT = `
<script>
(function() {
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
    cleanup();
    active = false;
    document.body.style.cursor = '';
    window.parent.postMessage({ type: 'picker-picked', tagName: tagNm, sectionId: sectionId, textContent: textContent }, '*');
  }

  window.addEventListener('message', function(e) {
    if (!e.data) return;
    if (e.data.type === 'picker-activate') {
      active = true;
      document.body.style.cursor = 'crosshair';
      ensureUI();
    } else if (e.data.type === 'picker-deactivate') {
      active = false;
      document.body.style.cursor = '';
      cleanup();
    }
  });

  document.addEventListener('mousemove', onMove, true);
  document.addEventListener('click', onDocClick, true);
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && active) {
      active = false;
      document.body.style.cursor = '';
      cleanup();
      window.parent.postMessage({ type: 'picker-esc' }, '*');
    }
  });
})();

// 高度自适应上报：内容变化（图片加载/字体渲染/DOM变更）时通知父页面调整 iframe 高度
(function() {
  var lastH = 0;
  function reportH() {
    var b = document.body, d = document.documentElement;
    var h = Math.max(b ? b.scrollHeight : 0, d ? d.scrollHeight : 0);
    if (h > 0 && Math.abs(h - lastH) > 1) {
      lastH = h;
      window.parent.postMessage({ type: 'iframe-height', height: h }, '*');
    }
  }
  if (document.readyState === 'complete') setTimeout(reportH, 0);
  else window.addEventListener('load', function() { setTimeout(reportH, 0); });
  if (typeof ResizeObserver !== 'undefined') {
    var ro = new ResizeObserver(function() { reportH(); });
    if (document.body) ro.observe(document.body);
    if (document.documentElement) ro.observe(document.documentElement);
  }
  if (typeof MutationObserver !== 'undefined' && document.body) {
    new MutationObserver(function() { reportH(); }).observe(document.body, { childList: true, subtree: true, attributes: true });
  }
})();
</script>`;

export function ResumeEditor({ resume, job, onSaved, onInsertTag, sourceHtml, onSourceHtmlChange, onRestyle }: Props) {
  const [mode, setMode] = useState<'preview' | 'source'>('preview');
  const [pickerMode, setPickerMode] = useState(false);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState('');
  const [dirty, setDirty] = useState(false);

  const iframeRef = useRef<HTMLIFrameElement>(null);
  const sourceAreaRef = useRef<HTMLTextAreaElement>(null);
  const debounceRef = useRef<number | undefined>(undefined);
  const [filePath, setFilePath] = useState<string>('');
  const [iframeHeight, setIframeHeight] = useState(A4_H);

  const activatePicker = useCallback(() => {
    iframeRef.current?.contentWindow?.postMessage({ type: 'picker-activate' }, '*');
  }, []);

  const deactivatePicker = useCallback(() => {
    iframeRef.current?.contentWindow?.postMessage({ type: 'picker-deactivate' }, '*');
  }, []);

  useEffect(() => {
    if (pickerMode && mode === 'preview') {
      activatePicker();
    } else {
      deactivatePicker();
      if (!pickerMode) return;
      setPickerMode(false);
    }
  }, [pickerMode, mode, activatePicker, deactivatePicker]);

  useEffect(() => {
    const handler = (e: MessageEvent) => {
      if (e.data?.type === 'picker-picked') {
        const tagName = e.data.tagName || '';
        const sectionId = e.data.sectionId || '';
        const textContent = e.data.textContent || '';
        if (tagName && onInsertTag) onInsertTag(tagName, sectionId, textContent);
        setPickerMode(false);
      } else if (e.data?.type === 'picker-esc') {
        setPickerMode(false);
      } else if (e.data?.type === 'iframe-height' && typeof e.data.height === 'number') {
        setIframeHeight(Math.max(e.data.height, 200));
      }
    };
    window.addEventListener('message', handler);
    return () => window.removeEventListener('message', handler);
  }, [onInsertTag]);

  useEffect(() => {
    if (!pickerMode) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setPickerMode(false);
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [pickerMode]);

  useEffect(() => {
    if (!resume?.id) { setFilePath(''); return; }
    const unsubscribe = agentApi.subscribeResumeFileChange(resume.id, async (data: any) => {
      try {
        if (data.path) setFilePath(data.path);
        const fileData = await agentApi.getResumeFile(resume.id);
        if (fileData.path) setFilePath(fileData.path);
        if (fileData.html) {
          onSourceHtmlChange(fileData.html);
          setDirty(false);
        }
      } catch { /* */ }
    });
    agentApi.getResumeFile(resume.id).then(d => {
      if (d.path) setFilePath(d.path);
      if (d.html) onSourceHtmlChange(d.html);
    }).catch(() => {});
    return unsubscribe;
  }, [resume?.id]);

  const buildIframeSrc = useCallback((html: string) => {
    let body = html;
    const bodyMatch = body.match(/<body[^>]*>([\s\S]*)<\/body>/i);
    if (bodyMatch) body = bodyMatch[1];
    let css = '';
    const styleMatch = html.match(/<style[^>]*>([\s\S]*?)<\/style>/gi);
    if (styleMatch) {
      css = stripMediaPrintCss(styleMatch.join('\n'));
    }
    return `<!DOCTYPE html><html><head>${css ? `<style>html,body{margin:0;padding:0;background:#fff;position:relative;overflow:hidden;}</style>${css}` : '<style>html,body{margin:0;padding:0;background:#fff;overflow:hidden;}</style>'}</head><body>${body}${IFRAME_SCRIPT}</body></html>`;
  }, []);

  const iframeSrcdoc = useMemo(() => {
    if (!sourceHtml) return '';
    return buildIframeSrc(sourceHtml);
  }, [sourceHtml, buildIframeSrc]);

  useEffect(() => {
    if (iframeRef.current && iframeSrcdoc) {
      iframeRef.current.srcdoc = iframeSrcdoc;
    }
  }, [iframeSrcdoc]);

  const handleIframeLoad = useCallback(() => {
    const doc = iframeRef.current?.contentDocument;
    if (doc?.body) {
      requestAnimationFrame(() => {
        const h = doc.documentElement?.scrollHeight || doc.body.scrollHeight;
        if (h > 0) setIframeHeight(Math.max(h, 200));
      });
    }
    if (pickerMode && mode === 'preview') {
      activatePicker();
    }
  }, [pickerMode, mode, activatePicker]);

  const handleSourceChange = useCallback((val: string) => {
    onSourceHtmlChange(val);
    setDirty(true);
    window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      if (iframeRef.current) iframeRef.current.srcdoc = buildIframeSrc(val);
    }, 500);
  }, [onSourceHtmlChange, buildIframeSrc]);

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
      const printableHtml = html;
      w.document.open();
      w.document.write(printableHtml);
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
    <div className="flex flex-col min-h-full">
      <div className="no-print shrink-0 flex items-center gap-3 flex-wrap pb-3 mb-3 border-b border-slate-700/30">
        <div className="flex items-center gap-1 bg-surface-900/60 rounded-lg p-1">
          <button
            onClick={() => setMode('preview')}
            className={`flex items-center gap-1 px-2.5 py-1 text-xs rounded-md transition-colors ${
              mode === 'preview' ? 'bg-accent-blue/20 text-accent-blue' : 'text-slate-500 hover:text-slate-300'
            }`}
          >
            <Eye size={12} /> 预览
          </button>
          <button
            onClick={() => setMode('source')}
            className={`flex items-center gap-1 px-2.5 py-1 text-xs rounded-md transition-colors ${
              mode === 'source' ? 'bg-accent-blue/20 text-accent-blue' : 'text-slate-500 hover:text-slate-300'
            }`}
          >
            <Code2 size={12} /> 源码
          </button>
        </div>

        {mode === 'preview' && (
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
        )}

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

        {filePath && (
          <span className="flex items-center gap-1 text-xs text-slate-500 max-w-[220px] truncate" title={filePath}>
            <HardDrive size={11} className="shrink-0" />
            <span className="truncate">{filePath.split(/[\\/]/).pop()}</span>
          </span>
        )}
      </div>

      {err && (
        <div className="mb-3 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 flex items-start gap-2">
          <AlertTriangle size={13} className="text-red-400 shrink-0 mt-0.5" />
          <p className="text-xs text-red-300/90 flex-1">{err}</p>
          <button onClick={() => setErr('')} className="text-red-400 hover:text-red-300"><X size={13} /></button>
        </div>
      )}

      {mode === 'preview' ? (
        <iframe
          ref={iframeRef}
          srcDoc={iframeSrcdoc}
          onLoad={handleIframeLoad}
          className="print-resume-frame"
          style={{
            width: '100%',
            height: iframeHeight,
            border: 'none',
            background: '#fff',
            display: 'block',
            flexShrink: 0,
          }}
          sandbox={(window as any).autoresume ? undefined : "allow-scripts"}
        />
      ) : (
        <div className="flex flex-col" style={{ height: 'calc(100vh - 160px)' }}>
          <div className="flex-1 min-h-0">
            <textarea
              ref={sourceAreaRef}
              value={sourceHtml}
              onChange={e => handleSourceChange(e.target.value)}
              className="w-full h-full bg-surface-900/60 border border-slate-700/50 rounded-md px-3 py-2 text-[11px] text-slate-300 font-mono resize-none scrollbar-thin focus:border-accent-blue/50 focus:outline-none"
              spellCheck={false}
            />
          </div>
          <div className="shrink-0 flex items-center justify-end gap-2 pt-2">
            <button
              onClick={() => {}}
              className="flex items-center gap-1 px-2.5 py-1 text-xs rounded-lg bg-accent-blue/20 text-accent-blue hover:bg-accent-blue/30 transition-colors"
            >
              <Send size={11} /> 发给AI修改
            </button>
          </div>
        </div>
      )}

      <p className="no-print text-[11px] text-slate-600 mt-2 flex items-center gap-1 shrink-0">
        {pickerMode
          ? '🎯 元素选择模式：悬浮高亮，点击拾取元素标签插入对话，ESC退出'
          : '点击「元素选择」拾取简历模块标签插入AI对话；导出的HTML可直接用浏览器打开或打印为PDF'
        }
      </p>
    </div>
  );
}
