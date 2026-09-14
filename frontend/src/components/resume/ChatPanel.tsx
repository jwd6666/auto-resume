import { useEffect, useRef, useState, forwardRef, useImperativeHandle, useCallback } from 'react';
import { useEditor, EditorContent } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Image from '@tiptap/extension-image';
import { Send, Sparkles, Loader2, ClipboardCheck, AlertTriangle, Gauge, Star, ChevronDown, ChevronUp, X, Check, Cpu, ImagePlus, StopCircle, MessageSquarePlus, Undo2 } from 'lucide-react';
import clsx from 'clsx';
import { agentApi, type ChatMessage, type Job, type Resume, type RefChip, type Scorecard, type HtmlPatch } from '../../api/agentApi';
import { DomTag } from './editor/DomTagExtension';
import { AssistantMessageRenderer } from './AssistantMessageRenderer';

export interface ChatPanelHandle {
  insertDomTag: (tagName: string, sectionId?: string, textContent?: string) => void;
}

interface Props {
  job: Job | null;
  resume: Resume | null;
  onResumeSaved: (r: Resume) => void;
  sourceHtml: string;
  onSourceHtmlChange: (html: string) => void;
}

const SECTION_LABELS: Record<string, string> = {
  basics: '基本信息', intro: '个人简介', work: '工作经历', project: '项目经历', edu: '教育经历', skill: '专业技能',
  summary: '自我评价', 'page-style': '页面样式',
};

function partLabel(id: string): string {
  if (SECTION_LABELS[id]) return SECTION_LABELS[id];
  if (id === 'full') return '完整简历';
  return id;
}

function applyHtmlPatch(sourceHtml: string, patch: HtmlPatch): string {
  let docHtml = sourceHtml;
  const isFullDoc = /<html/i.test(sourceHtml);
  if (!isFullDoc) {
    docHtml = `<!DOCTYPE html><html><head></head><body>${sourceHtml}</body></html>`;
  }
  const doc = new DOMParser().parseFromString(docHtml, 'text/html');
  const el = doc.querySelector(`[data-resume-section="${patch.resumePartId}"]`)
    || doc.querySelector(`[data-resume-part="${patch.resumePartId}"]`);
  if (!el) return sourceHtml;
  const parent = el.parentElement;
  if (!parent) return sourceHtml;
  const next = el.nextElementSibling;
  parent.removeChild(el);
  const container = doc.createElement('div');
  container.innerHTML = patch.newHtml;
  while (container.firstChild) {
    parent.insertBefore(container.firstChild, next);
  }
  if (isFullDoc) {
    return `<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n${doc.head.innerHTML}\n</head>\n<body>\n${doc.body.innerHTML}\n</body>\n</html>`;
  }
  return doc.body.innerHTML;
}

function extractHtmlPatchesFromText(text: string): { patches: HtmlPatch[]; cleanedText: string } {
  const patches: HtmlPatch[] = [];
  let cleaned = text;

  function parseJsonObject(str: string, start: number): { obj: any; end: number } | null {
    let depth = 0, inString = false, escaped = false;
    for (let i = start; i < str.length; i++) {
      const ch = str[i];
      if (escaped) { escaped = false; continue; }
      if (ch === '\\') { escaped = true; continue; }
      if (ch === '"') { inString = !inString; continue; }
      if (!inString) {
        if (ch === '{') depth++;
        else if (ch === '}') { depth--; if (depth === 0) {
          try {
            const obj = JSON.parse(str.slice(start, i + 1));
            return { obj, end: i + 1 };
          } catch { return null; }
        }}
      }
    }
    return null;
  }

  const markerRanges: Array<{start: number, end: number}> = [];
  const MARKER_START = '===HTML_PATCH===';
  const MARKER_END = '===HTML_END===';

  let searchStart = 0;
  while (true) {
    const startIdx = text.indexOf(MARKER_START, searchStart);
    if (startIdx === -1) break;
    const endIdx = text.indexOf(MARKER_END, startIdx + MARKER_START.length);
    if (endIdx === -1) break;
    const contentStart = startIdx + MARKER_START.length;
    const content = text.slice(contentStart, endIdx).trim();
    markerRanges.push({ start: startIdx, end: endIdx + MARKER_END.length });
    const jsonStart = content.indexOf('{');
    if (jsonStart >= 0) {
      const result = parseJsonObject(content, jsonStart);
      if (result && result.obj.newHtml !== undefined) {
        const partId = result.obj.resumeSectionId || result.obj.resumePartId;
        if (partId !== undefined) {
          patches.push({ resumePartId: partId, newHtml: result.obj.newHtml });
        }
      }
    }
    searchStart = endIdx + MARKER_END.length;
  }

  for (let i = markerRanges.length - 1; i >= 0; i--) {
    const r = markerRanges[i];
    cleaned = cleaned.slice(0, r.start) + '[PATCH]' + cleaned.slice(r.end);
  }

  const idRegex = /"(?:resumeSectionId|resumePartId)"\s*:\s*"([^"]*)"/g;
  let idMatch: RegExpExecArray | null;
  const foundRanges: Array<{start: number, end: number, patch: HtmlPatch}> = [];

  while ((idMatch = idRegex.exec(cleaned)) !== null) {
    const matchIdx = idMatch.index;
    if (markerRanges.some(r => matchIdx >= r.start && matchIdx < r.end)) continue;
    let braceStart = matchIdx;
    while (braceStart > 0 && cleaned[braceStart] !== '{') braceStart--;
    if (cleaned[braceStart] !== '{') continue;
    const result = parseJsonObject(cleaned, braceStart);
    if (result && result.obj.newHtml !== undefined) {
      const partId = result.obj.resumeSectionId || result.obj.resumePartId;
      if (partId !== undefined) {
        foundRanges.push({
          start: braceStart,
          end: result.end,
          patch: { resumePartId: partId, newHtml: result.obj.newHtml }
        });
      }
    }
  }

  if (foundRanges.length > 0) {
    foundRanges.sort((a, b) => b.start - a.start);
    for (const range of foundRanges) {
      patches.push(range.patch);
      cleaned = cleaned.slice(0, range.start) + '[PATCH]' + cleaned.slice(range.end);
    }
    patches.reverse();
  }

  return { patches, cleanedText: cleaned };
}

function ScorecardView({ scorecard, resumeId }: { scorecard: Scorecard; resumeId: number }) {
  const [expanded, setExpanded] = useState(true);
  return (
    <div className="rounded-xl bg-surface-700/50 border border-slate-600/20 overflow-hidden">
      <button
        onClick={() => setExpanded(e => !e)}
        className="w-full flex items-center justify-between px-3.5 py-2.5 hover:bg-surface-700/40 transition-colors"
      >
        <span className="flex items-center gap-2 text-sm font-semibold text-slate-200">
          <Gauge size={15} className="text-accent-purple" /> 匹配度评估
          <span className={`text-lg font-bold ${
            scorecard.overall_score >= 75 ? 'text-green-400' :
            scorecard.overall_score >= 50 ? 'text-amber-400' : 'text-red-400'
          }`}>{scorecard.overall_score}</span>
          <span className="text-xs text-slate-500">/100</span>
        </span>
        {expanded ? <ChevronUp size={14} className="text-slate-500" /> : <ChevronDown size={14} className="text-slate-500" />}
      </button>
      {expanded && (
        <div className="px-3.5 pb-3 space-y-2.5">
          <p className="text-xs text-slate-400">{scorecard.overall_summary}</p>
          {scorecard.items.map((item, i) => (
            <div key={i} className="px-3 py-2 rounded-lg bg-surface-900/40">
              <div className="flex items-center justify-between mb-1">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-slate-200">{item.competency}</span>
                  <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                    item.confidence === '高' ? 'bg-green-500/15 text-green-400' :
                    item.confidence === '中' ? 'bg-amber-500/15 text-amber-400' :
                    'bg-slate-500/15 text-slate-400'
                  }`}>{item.confidence}</span>
                </div>
                <span className={`text-sm font-bold ${
                  item.score >= 75 ? 'text-green-400' :
                  item.score >= 50 ? 'text-amber-400' : 'text-red-400'
                }`}>{item.score}</span>
              </div>
              <p className="text-[11px] text-slate-400 mb-1.5">{item.summary}</p>
              {item.evidence.length > 0 && (
                <div className="space-y-0.5 mb-1.5">
                  {item.evidence.map((ev, j) => (
                    <div key={j} className="text-[11px] text-slate-500 pl-2 border-l-2 border-slate-700">
                      <span className="text-slate-600">[{ev.source}]</span> {ev.quote}
                      {ev.why && <span className="text-slate-600"> → {ev.why}</span>}
                    </div>
                  ))}
                </div>
              )}
              <div className="flex gap-3">
                {item.gap && <p className="text-[11px] text-amber-400/70">⚠ {item.gap}</p>}
                {item.suggestion && <p className="text-[11px] text-accent-blue/70">💡 {item.suggestion}</p>}
              </div>
            </div>
          ))}
          {scorecard.needs_verification.length > 0 && (
            <div className="px-3 py-2 rounded-lg bg-amber-500/5 border border-amber-500/15">
              <p className="text-[11px] font-medium text-amber-400 mb-1">需要验证的点</p>
              <ul className="space-y-0.5">
                {scorecard.needs_verification.map((v, i) => (
                  <li key={i} className="text-[11px] text-slate-400">• {v}</li>
                ))}
              </ul>
            </div>
          )}

        </div>
      )}
    </div>
  );
}

function PatchCard({ patch, onApply, applied }: { patch: HtmlPatch; onApply: () => void; applied: boolean }) {
  const [showDetail, setShowDetail] = useState(false);
  return (
    <div className={`rounded-lg border px-3 py-2 text-xs ${
      applied ? 'bg-emerald-500/10 border-emerald-500/25' : 'bg-accent-purple/10 border-accent-purple/25'
    }`}>
      <div className="flex items-center justify-between">
        <span className="flex items-center gap-1.5">
          <span className="text-accent-purple">✏️</span>
          <span className="font-medium text-slate-200">修改：{partLabel(patch.resumePartId)}</span>
        </span>
        <div className="flex items-center gap-1.5">
          <button onClick={() => setShowDetail(!showDetail)} className="text-[10px] text-slate-400 hover:text-slate-200 underline">
            {showDetail ? '收起' : '详情'}
          </button>
          {!applied && (
            <button onClick={onApply} className="flex items-center gap-1 px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-400 hover:bg-emerald-500/30 transition-colors">
              <Check size={10} /> 应用
            </button>
          )}
          {applied && <span className="text-emerald-400 text-[10px]">已应用</span>}
        </div>
      </div>
      {showDetail && (
        <pre className="mt-1.5 p-2 rounded bg-surface-900/50 text-[10px] text-slate-300 whitespace-pre-wrap break-words max-h-40 overflow-auto scrollbar-thin">
          {patch.newHtml}
        </pre>
      )}
    </div>
  );
}

interface ModelOption {
  providerKey: string;
  modelId: string;
  label: string;
  hasKey: boolean;
}

export const ChatPanel = forwardRef<ChatPanelHandle, Props>(function ChatPanel({ job, resume, onResumeSaved, sourceHtml, onSourceHtmlChange }: Props, ref) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [modelReady, setModelReady] = useState<boolean | null>(null);
  const [evalLoading, setEvalLoading] = useState(false);
  const [appliedPatches, setAppliedPatches] = useState<Set<string>>(new Set());
  const [toolStatus, setToolStatus] = useState<string | null>(null);
  const [snapshotDepths, setSnapshotDepths] = useState<number[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const imageInputRef = useRef<HTMLInputElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  const [modelOptions, setModelOptions] = useState<ModelOption[]>([]);
  const selectedProviderRef = useRef('');
  const selectedModelRef = useRef('');
  const [selectedLabel, setSelectedLabel] = useState('');
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false);

  const editor = useEditor({
    extensions: [StarterKit, DomTag, Image.configure({ inline: false })],
    content: '',
    editorProps: {
      attributes: {
        class: 'tiptap-editor-body',
        'data-placeholder': '输入优化需求，如：请帮我优化项目经历部分...',
      },
      handleKeyDown: (view, event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
          event.preventDefault();
          handleSend();
          return true;
        }
        return false;
      },
      handlePaste: (view, event) => {
        const items = event.clipboardData?.items;
        if (!items) return false;
        for (let i = 0; i < items.length; i++) {
          const item = items[i];
          if (item.type.startsWith('image/')) {
            event.preventDefault();
            const file = item.getAsFile();
            if (!file) continue;
            const reader = new FileReader();
            reader.onload = () => {
              const src = reader.result as string;
              editor?.chain().focus().setImage({ src }).run();
            };
            reader.readAsDataURL(file);
            return true;
          }
        }
        return false;
      },
    },
    immediatelyRender: false,
  });

  useImperativeHandle(ref, () => ({
    insertDomTag: (tagName: string, sectionId?: string, textContent?: string) => {
      if (editor) {
        editor.commands.focus();
        (editor.commands as any).insertDomTag(tagName, sectionId, textContent);
      }
    },
  }), [editor]);

  const loadModels = useCallback(() => {
    agentApi.getSettings().then(s => {
      const providers = s.providers as Record<string, any>;
      const customModels = s.custom_models || [];
      const opts: ModelOption[] = [];
      for (const [key, pconfig] of Object.entries(providers)) {
        const hasKey = !!s.api_keys_set[key];
        for (const m of pconfig.models || []) {
          opts.push({
            providerKey: key,
            modelId: m.id,
            label: `${pconfig.name_cn} · ${m.name}`,
            hasKey,
          });
        }
      }
      for (const cm of customModels) {
        opts.push({
          providerKey: `custom:${cm.id}`,
          modelId: cm.model_id,
          label: `自定义 · ${cm.display_name || cm.model_id}`,
          hasKey: true,
        });
      }
      setModelOptions(opts.filter(o => o.hasKey || (o.providerKey === s.provider && o.modelId === s.model)));
      selectedProviderRef.current = s.provider;
      selectedModelRef.current = s.model;
      const current = opts.find(o => o.providerKey === s.provider && o.modelId === s.model);
      setSelectedLabel(current?.label || s.model);
      const hasKey = s.provider.startsWith('custom:') || s.provider === 'custom'
        ? true
        : !!s.api_keys_set[s.provider];
      setModelReady(hasKey);
    }).catch(() => setModelReady(false));
  }, []);

  useEffect(() => { loadModels(); }, [messages, loadModels]);

  useEffect(() => {
    const onModelsUpdated = () => loadModels();
    window.addEventListener('models-updated', onModelsUpdated);
    return () => window.removeEventListener('models-updated', onModelsUpdated);
  }, [loadModels]);

  useEffect(() => {
    if (!resume) { setMessages([]); return; }
    setLoadingHistory(true);
    agentApi.getConversation(resume.id)
      .then(conv => {
        if (conv?.messages) {
          try { setMessages(JSON.parse(conv.messages)); }
          catch { setMessages([]); }
        } else {
          setMessages([]);
        }
      })
      .catch(() => setMessages([]))
      .finally(() => setLoadingHistory(false));
  }, [resume?.id]);

  useEffect(() => {
    if (!resume?.id) return;
    const unsubscribe = agentApi.subscribeResumeFileChange(resume.id, async () => {
      try {
        const data = await agentApi.getResumeFile(resume.id);
        if (data.html && data.html !== sourceHtml) {
          onSourceHtmlChange(data.html);
          if (resume) onResumeSaved({ ...resume, rendered_html: data.html });
        }
      } catch { /* */ }
    });
    return unsubscribe;
  }, [resume?.id]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages]);

  const extractEditorContent = useCallback((): { text: string; tags: Array<{ tagName: string; sectionId: string; textContent: string }>; images: string[] } => {
    if (!editor) return { text: '', tags: [], images: [] };
    const json = editor.getJSON();
    const tags: Array<{ tagName: string; sectionId: string; textContent: string }> = [];
    const images: string[] = [];
    let textParts: string[] = [];

    function walk(node: any) {
      if (!node) return;
      if (node.type === 'domTag') {
        const tn = node.attrs?.tagName || 'div';
        const sid = node.attrs?.sectionId || '';
        const tc = node.attrs?.textContent || '';
        tags.push({ tagName: tn, sectionId: sid, textContent: tc });
        const label = sid ? `@${sid}` : `@${tn}`;
        textParts.push(label);
      } else if (node.type === 'image') {
        const src = node.attrs?.src;
        if (src && src.startsWith('data:')) {
          images.push(src);
          textParts.push('[图片]');
        } else if (src) {
          textParts.push(`[图片: ${src}]`);
        }
      } else if (node.type === 'text') {
        textParts.push(node.text || '');
      } else if (node.content && Array.isArray(node.content)) {
        for (const child of node.content) {
          walk(child);
        }
        if (['paragraph', 'heading'].includes(node.type)) {
          textParts.push('\n');
        }
      }
    }

    if (Array.isArray(json)) {
      for (const n of json) walk(n);
    } else if (json && json.content && Array.isArray(json.content)) {
      for (const n of json.content) walk(n);
    }

    return { text: textParts.join('').trim(), tags, images };
  }, [editor]);

  const buildSubmitJson = useCallback(() => {
    const { text, tags } = extractEditorContent();
    const doc: any = { text, tags: tags.map(t => ({ tagName: t.tagName, sectionId: t.sectionId, textContent: t.textContent })) };
    return JSON.stringify(doc);
  }, [extractEditorContent]);

  const handleImageUpload = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !editor) return;
    const reader = new FileReader();
    reader.onload = () => {
      const src = reader.result as string;
      editor.chain().focus().setImage({ src }).run();
    };
    reader.readAsDataURL(file);
    e.target.value = '';
  }, [editor]);

  const applyPatch = async (patch: HtmlPatch) => {
    const newHtml = applyHtmlPatch(sourceHtml, patch);
    if (newHtml === sourceHtml) return;
    onSourceHtmlChange(newHtml);
    setAppliedPatches(prev => new Set([...prev, `${patch.resumePartId}::${patch.newHtml}`]));
    if (resume) {
      try {
        const saved = await agentApi.updateResume(resume.id, { rendered_html: newHtml });
        onResumeSaved(saved);
      } catch { /* */ }
    }
  };

  const handleStop = () => {
    abortRef.current?.abort();
  };

  const handleSend = async () => {
    if (!job || !resume || streaming) return;
    const { text, tags, images } = extractEditorContent();
    if (!text.trim() && tags.length === 0 && images.length === 0) return;

    const fullContent = tags.length > 0
      ? tags.map(t => {
          const label = t.sectionId ? `${t.sectionId}(<${t.tagName}>)` : `<${t.tagName}>`;
          const content = t.textContent ? `\n该元素当前内容: ${t.textContent}` : '';
          return `引用元素: ${label}${content}`;
        }).join('\n') + `\n\n${text.trim()}`
      : text.trim();

    const userMsg: ChatMessage = { role: 'user', content: fullContent, images: images.length > 0 ? images : undefined };
    const newMessages = [...messages, userMsg];
    setMessages(newMessages);
    if (editor) editor.commands.clearContent();
    setStreaming(true);

    const abortController = new AbortController();
    abortRef.current = abortController;

    const assistantMsg: ChatMessage = { role: 'assistant', content: '', patches: [] };
    setMessages([...newMessages, assistantMsg]);

    try {
      let fullText = '';
      const collectedPatches: HtmlPatch[] = [];
      let turnSnapshotDepth: number | undefined;
      for await (const chunk of agentApi.chatStream(resume.id, job.id, newMessages, undefined, abortController.signal)) {
        if (chunk.type === 'snapshot_depth' && chunk.depth !== undefined) {
          turnSnapshotDepth = chunk.depth;
          setMessages(prev => {
            const copy = [...prev];
            const userIdx = copy.findIndex((m, i) => m.role === 'user' && i === newMessages.length - 1);
            if (userIdx >= 0) {
              copy[userIdx] = { ...copy[userIdx], snapshotDepth: chunk.depth };
            }
            return copy;
          });
          setSnapshotDepths(prev => [...prev, chunk.depth!]);
        } else if (chunk.type === 'text' && chunk.content) {
          fullText += chunk.content;
        } else if (chunk.type === 'patch' && chunk.resumePartId !== undefined && chunk.newHtml !== undefined) {
          const patch: HtmlPatch = { resumePartId: chunk.resumePartId, newHtml: chunk.newHtml };
          collectedPatches.push(patch);
          fullText += `\n[PATCH: ${partLabel(patch.resumePartId)}]\n`;
        } else if (chunk.type === 'tool_call' && chunk.toolName) {
          let argDesc = '';
          if (chunk.toolName === 'patch_file' && chunk.arguments?.old_str) {
            const s = String(chunk.arguments.old_str).replace(/\s+/g, ' ').trim().slice(0, 40);
            argDesc = `(替换: ${s}${String(chunk.arguments.old_str).length > 40 ? '...' : ''})`;
          } else if (chunk.toolName === 'patch_file' && chunk.arguments?.section_id) {
            argDesc = `(section: ${partLabel(chunk.arguments.section_id)})`;
          } else if (chunk.toolName === 'read_file' && chunk.arguments?.section_id) {
            argDesc = `(section: ${partLabel(chunk.arguments.section_id)})`;
          } else if (chunk.arguments?.path) {
            argDesc = `(${chunk.arguments.path})`;
          }
          setToolStatus(`正在调用工具: ${chunk.toolName} ${argDesc}`);
          fullText += `\n🔧 调用 ${chunk.toolName} ${argDesc}\n`;
        } else if (chunk.type === 'tool_result' && chunk.toolName) {
          const preview = chunk.result ? chunk.result.slice(0, 100) : '';
          setToolStatus(`工具 ${chunk.toolName} 完成: ${preview}`);
          fullText += `\n✅ ${chunk.toolName} 完成: ${preview}\n`;
        } else if (chunk.type === 'retry' && chunk.content) {
          fullText = `🔄 ${chunk.content}\n\n`;
        } else if (chunk.type === 'error' && chunk.content) {
          fullText += chunk.content;
        }
        setMessages(prev => {
          const copy = [...prev];
          copy[copy.length - 1] = { role: 'assistant', content: fullText, patches: collectedPatches.length > 0 ? [...collectedPatches] : undefined };
          return copy;
        });
      }
      setToolStatus(null);

      if (fullText.includes('HTML_PATCH')) {
        const parsed = extractHtmlPatchesFromText(fullText);
        if (parsed.patches.length > 0) {
          const existingKeys = new Set(collectedPatches.map(p => `${p.resumePartId}::${p.newHtml}`));
          for (const patch of parsed.patches) {
            const key = `${patch.resumePartId}::${patch.newHtml}`;
            if (!existingKeys.has(key)) {
              collectedPatches.push(patch);
              existingKeys.add(key);
            }
          }
          fullText = parsed.cleanedText;
          setMessages(prev => {
            const copy = [...prev];
            copy[copy.length - 1] = { role: 'assistant', content: fullText, patches: collectedPatches };
            return copy;
          });
        }
      }

      const finalMessages = [...newMessages, { role: 'assistant' as const, content: fullText, patches: collectedPatches.length > 0 ? collectedPatches : undefined }];
      await agentApi.saveConversation(resume.id, finalMessages.map(m => {
        const base: any = { role: m.role, content: m.content };
        if (m.references) base.references = m.references;
        if (m.scorecard) base.scorecard = m.scorecard;
        if (m.patches) base.patches = m.patches;
        if (m.snapshotDepth !== undefined) base.snapshotDepth = m.snapshotDepth;
        return base;
      }));

      if (collectedPatches.length > 0) {
        let currentHtml = sourceHtml;
        const newAppliedKeys: string[] = [];
        for (const patch of collectedPatches) {
          const patched = applyHtmlPatch(currentHtml, patch);
          if (patched !== currentHtml) {
            currentHtml = patched;
            newAppliedKeys.push(`${patch.resumePartId}::${patch.newHtml}`);
          }
        }
        if (currentHtml !== sourceHtml) {
          onSourceHtmlChange(currentHtml);
          setAppliedPatches(prev => {
            const next = new Set(prev);
            for (const k of newAppliedKeys) next.add(k);
            return next;
          });
          if (resume) {
            try {
              const saved = await agentApi.updateResume(resume.id, { rendered_html: currentHtml });
              onResumeSaved(saved);
            } catch { /* */ }
          }
        }
      }
    } catch (e: any) {
      if (abortController.signal.aborted) {
        setMessages(prev => {
          const copy = [...prev];
          const last = copy[copy.length - 1];
          if (last?.role === 'assistant') {
            copy[copy.length - 1] = { ...last, content: (last.content || '') + '\n\n⏹ 已停止生成' };
          }
          return copy;
        });
      } else {
        setMessages(prev => {
          const copy = [...prev];
          copy[copy.length - 1] = { role: 'assistant', content: `⚠️ 请求失败：${e.message}` };
          return copy;
        });
      }
    } finally {
      setStreaming(false);
      setToolStatus(null);
      abortRef.current = null;
    }
  };

  const handleRollback = async (userMsgIndex: number, targetDepth: number) => {
    if (!resume || streaming) return;
    try {
      const result = await agentApi.rollbackSnapshot(resume.id, targetDepth);
      if (result.ok && result.popped > 0) {
        const data = await agentApi.getResumeFile(resume.id);
        if (data.html && data.html !== sourceHtml) {
          onSourceHtmlChange(data.html);
          if (resume) onResumeSaved({ ...resume, rendered_html: data.html });
        }
        setMessages(prev => prev.slice(0, userMsgIndex));
        setSnapshotDepths(prev => prev.slice(0, prev.indexOf(targetDepth)));
        await agentApi.saveConversation(resume.id, messages.slice(0, userMsgIndex).map(m => {
          const base: any = { role: m.role, content: m.content };
          if (m.references) base.references = m.references;
          if (m.scorecard) base.scorecard = m.scorecard;
          if (m.patches) base.patches = m.patches;
          if (m.snapshotDepth !== undefined) base.snapshotDepth = m.snapshotDepth;
          return base;
        }));
      }
    } catch (e: any) {
      console.error('回滚失败:', e);
    }
  };

  const handleEvaluate = async () => {
    if (!job || !resume || evalLoading) return;
    setEvalLoading(true);
    try {
      const scorecard = await agentApi.generateScorecard({ job_id: job.id, resume_id: resume.id });
      const parts: string[] = [`📋 匹配度评估：${scorecard.overall_score}/100\n\n${scorecard.overall_summary}`];
      for (const item of scorecard.items) {
        parts.push(`【${item.competency}】${item.score}分（${item.confidence}置信）- ${item.summary}`);
        if (item.gap) parts.push(`  ⚠ 差距：${item.gap}`);
        if (item.suggestion) parts.push(`  💡 建议：${item.suggestion}`);
      }
      if (scorecard.needs_verification.length > 0) {
        parts.push(`\n需要验证：${scorecard.needs_verification.join('；')}`);
      }
      const evalMsg: ChatMessage = { role: 'assistant', content: parts.join('\n\n'), scorecard };
      setMessages(prev => [...prev, evalMsg]);
    } catch (e: any) {
      setMessages(prev => [...prev, { role: 'assistant', content: `⚠️ 评估失败：${e.message}` }]);
    } finally {
      setEvalLoading(false);
    }
  };

  const handleModelSelect = async (opt: ModelOption) => {
    try {
      await agentApi.updateSettings({ provider: opt.providerKey, model: opt.modelId });
      selectedProviderRef.current = opt.providerKey;
      selectedModelRef.current = opt.modelId;
      setSelectedLabel(opt.label);
      setModelReady(opt.hasKey);
      setModelDropdownOpen(false);
    } catch { /* */ }
  };

  const copyResult = () => {
    const last = messages.filter(m => m.role === 'assistant' && m.content).pop();
    if (last) navigator.clipboard.writeText(last.content);
  };

  const handleNewChat = () => {
    if (streaming) return;
    setMessages([]);
    setAppliedPatches(new Set());
    setSnapshotDepths([]);
    if (editor) editor.commands.clearContent();
    if (resume) {
      agentApi.saveConversation(resume.id, []).catch(() => {});
    }
  };

  if (!job || !resume) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-6">
         <div className="w-16 h-16 rounded-2xl bg-slate-800/60 flex items-center justify-center mb-3">
           <Sparkles size={24} className="text-slate-600" />
        </div>
        <p className="text-xs text-slate-500">请先选择岗位和简历</p>
        <p className="text-[11px] text-slate-600 mt-0.5">AI 将根据 JD + 简历内容提供优化建议</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {modelReady === false && (
        <div className="mx-3 mt-3 px-3 py-2 rounded-lg bg-red-500/10 border border-red-500/30 flex items-center gap-2 text-xs text-red-400">
          <AlertTriangle size={13} className="shrink-0" />
          <span>当前模型未配置 API Key，对话将失败。请在下方切换模型。</span>
        </div>
      )}

      <div ref={scrollRef} className="flex-1 overflow-y-auto scrollbar-thin space-y-3 p-3 pb-1">
        {loadingHistory ? (
          <div className="flex items-center justify-center py-8">
            <Loader2 size={18} className="animate-spin text-slate-600" />
          </div>
        ) : messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-4 text-center">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-accent-blue/20 to-accent-purple/20 flex items-center justify-center mb-2">
              <Sparkles size={16} className="text-accent-blue" />
            </div>
            <p className="text-xs text-slate-400">AI 简历顾问已就绪</p>
            <p className="text-[11px] text-slate-600 mt-0.5">
              基于岗位「{job.title}」+ 当前简历进行对话优化
            </p>
          </div>
        ) : (
          messages.map((msg, i) => (
            <div key={i} className={`flex items-start gap-1.5 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              {msg.role === 'user' && msg.snapshotDepth !== undefined && !streaming && (
                <button
                  onClick={() => handleRollback(i, msg.snapshotDepth!)}
                  className="shrink-0 mt-1 p-1 rounded-md text-slate-500 hover:text-amber-400 hover:bg-amber-500/10 transition-colors"
                  title="回滚到此消息发送前的状态"
                >
                  <Undo2 size={13} />
                </button>
              )}
              {msg.scorecard ? (
                <div className="w-full">
                  <ScorecardView scorecard={msg.scorecard} resumeId={resume!.id} />
                </div>
              ) : (
                <div
                  className={`max-w-[92%] rounded-xl px-3.5 py-2 text-sm break-words ${
                    msg.role === 'user'
                      ? 'bg-accent-blue/20 text-slate-200 border border-accent-blue/20 whitespace-pre-wrap'
                      : 'bg-surface-700/50 text-slate-300 border border-slate-600/20'
                  }`}
                >
                  {msg.patches && msg.patches.length > 0 && (
                    <div className="mb-2 space-y-1.5 border-b border-slate-600/20 pb-2">
                      <p className="text-[10px] text-slate-500">AI 修改了以下内容：</p>
                      {msg.patches.map((patch, pi) => (
                        <PatchCard
                          key={`${patch.resumePartId}-${pi}`}
                          patch={patch}
                          applied={appliedPatches.has(`${patch.resumePartId}::${patch.newHtml}`)}
                          onApply={() => applyPatch(patch)}
                        />
                      ))}
                    </div>
                  )}
                  {msg.role === 'assistant'
                    ? (msg.content ? <AssistantMessageRenderer content={msg.content} /> : (streaming && i === messages.length - 1 ? <span className="text-slate-500">思考中...</span> : null))
                    : (
                      <>
                        {msg.images && msg.images.length > 0 && (
                          <div className="flex flex-wrap gap-1.5 mb-1.5">
                            {msg.images.map((imgSrc, imgIdx) => (
                              <img key={imgIdx} src={imgSrc} alt="上传图片" className="max-h-32 max-w-[200px] rounded-md border border-slate-600/30 object-contain" />
                            ))}
                          </div>
                        )}
                        {msg.content}
                      </>
                    )
                  }
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {messages.length > 0 && !streaming && (
        <div className="flex gap-1 px-3 py-1">
          <button
            onClick={handleNewChat}
            className="flex items-center gap-1 text-[11px] px-2 py-1 rounded-md bg-surface-700/40 text-slate-400 hover:text-slate-200 hover:bg-surface-700/60"
          >
            <MessageSquarePlus size={11} /> 新聊天
          </button>
          <button
            onClick={copyResult}
            className="flex items-center gap-1 text-[11px] px-2 py-1 rounded-md bg-surface-700/40 text-slate-400 hover:text-slate-200 hover:bg-surface-700/60"
          >
            <ClipboardCheck size={11} /> 复制最后回复
          </button>
        </div>
      )}

      <div className="shrink-0 border-t border-slate-700/30 px-3 pt-2 pb-3">
        {toolStatus && (
          <div className="flex items-center gap-2 px-3 py-1.5 mb-2 text-xs text-accent-blue bg-accent-blue/10 rounded-lg border border-accent-blue/20">
            <Loader2 size={12} className="animate-spin" />
            {toolStatus}
          </div>
        )}

        <div className="flex items-center gap-2 mb-2">
          <div className="relative flex-1">
            <button
              onClick={() => setModelDropdownOpen(p => !p)}
              className={`w-full flex items-center justify-between gap-1 px-2.5 py-1 text-xs rounded-lg transition-colors ${
                modelReady === false
                  ? 'bg-red-500/10 text-red-400 border border-red-500/30'
                  : 'bg-surface-900/60 text-slate-400 border border-slate-700/40 hover:bg-surface-700/40'
              }`}
            >
              <span className="flex items-center gap-1.5 truncate">
                <Cpu size={11} className="shrink-0" />
                <span className="truncate">{selectedLabel || '选择模型'}</span>
                {modelReady === false && <span className="text-[10px] shrink-0">(未配置Key)</span>}
              </span>
              <ChevronDown size={11} className="shrink-0" />
            </button>
            {modelDropdownOpen && (
              <>
                <div className="fixed inset-0 z-40" onClick={() => setModelDropdownOpen(false)} />
                <div className="absolute left-0 bottom-full mb-1 z-50 w-full max-h-64 overflow-y-auto scrollbar-thin bg-surface-800 rounded-lg border border-slate-700/50 shadow-2xl animate-fade-in">
                  <div className="p-1 space-y-0.5">
                    {modelOptions.map((opt) => {
                      const isActive = selectedProviderRef.current === opt.providerKey && selectedModelRef.current === opt.modelId;
                      return (
                        <button
                          key={`${opt.providerKey}-${opt.modelId}`}
                          onClick={() => handleModelSelect(opt)}
                          className={`w-full text-left px-2.5 py-1.5 rounded-md text-xs flex items-center gap-1.5 transition-colors ${
                            isActive ? 'bg-accent-blue/15 text-accent-blue' : 'text-slate-300 hover:bg-surface-700/40'
                          }`}
                        >
                          {isActive && <Check size={10} className="shrink-0" />}
                          <span className={`truncate ${isActive ? '' : 'ml-3.5'}`}>{opt.label}</span>
                          {!opt.hasKey && <span className="text-[9px] text-slate-600 shrink-0 ml-auto">未配置</span>}
                        </button>
                      );
                    })}
                    {modelOptions.length === 0 && (
                      <p className="text-xs text-slate-500 px-2.5 py-2">暂无可用模型</p>
                    )}
                  </div>
                </div>
              </>
            )}
          </div>
        </div>

        <div className="flex gap-2 items-end">
          <div className="flex-1 flex flex-col">
            <div
              className="tiptap-editor-wrap bg-surface-900/60 border border-slate-700/50 rounded-lg focus-within:border-accent-blue/50 transition-colors"
              onClick={() => editor?.commands.focus()}
            >
              <EditorContent editor={editor} />
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <input ref={imageInputRef} type="file" accept="image/*" className="hidden"
              onChange={handleImageUpload} />
            <button
              onClick={() => imageInputRef.current?.click()}
              disabled={streaming}
              className="flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-lg bg-surface-700/50 text-slate-400 hover:text-slate-200 hover:bg-surface-700 disabled:opacity-40 transition-colors"
              title="上传图片到编辑器"
            >
              <ImagePlus size={13} />
              图片
            </button>
            <button
              onClick={handleEvaluate}
              disabled={evalLoading || streaming}
              className="flex items-center gap-1 px-2.5 py-1.5 text-xs rounded-lg bg-accent-purple/20 text-accent-purple hover:bg-accent-purple/30 disabled:opacity-40 transition-colors"
              title="生成匹配度评分卡"
            >
              {evalLoading ? <Loader2 size={13} className="animate-spin" /> : <Star size={13} />}
              评估
            </button>
            <button
              onClick={streaming ? handleStop : handleSend}
              disabled={!streaming && (!editor || !editor.getText().trim())}
              className={clsx(
                'flex items-center gap-1 px-2.5 py-1.5 text-xs transition-colors',
                streaming
                  ? 'bg-red-500/20 text-red-400 hover:bg-red-500/30 border border-red-500/30'
                  : 'btn-primary disabled:opacity-40',
              )}
            >
              {streaming ? <StopCircle size={13} /> : <Send size={13} />}
              {streaming ? '停止' : '发送'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
});
