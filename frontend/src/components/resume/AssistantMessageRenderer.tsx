import { useState, useCallback } from 'react';
import { Copy, CheckCheck } from 'lucide-react';

interface ParsedBlock {
  type: 'heading' | 'paragraph' | 'list' | 'ordered-list' | 'code' | 'tool-call' | 'tool-result' | 'patch-marker' | 'hr' | 'blockquote';
  level?: number;
  items?: string[];
  lang?: string;
  code?: string;
  icon?: string;
  toolName?: string;
  detail?: string;
  section?: string;
  text?: string;
}

function parseInline(text: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  let remaining = text;
  let key = 0;

  while (remaining.length > 0) {
    let handled = false;

    if (remaining[0] === '`') {
      const j = remaining.indexOf('`', 1);
      if (j !== -1) {
        nodes.push(<code key={key++} className="px-1 py-0.5 rounded bg-slate-700/60 text-accent-blue text-[12px] font-mono">{remaining.slice(1, j)}</code>);
        remaining = remaining.slice(j + 1);
        handled = true;
      }
    }

    if (!handled && remaining.startsWith('**')) {
      const j = remaining.indexOf('**', 2);
      if (j !== -1 && j > 2) {
        const inner = remaining.slice(2, j);
        if (inner.trim().length > 0) {
          nodes.push(<strong key={key++} className="font-semibold text-slate-100">{parseInline(inner)}</strong>);
          remaining = remaining.slice(j + 2);
          handled = true;
        }
      }
    }

    if (!handled && remaining[0] === '*' && remaining[1] !== '*') {
      const j = remaining.indexOf('*', 1);
      if (j !== -1 && j > 1 && remaining[j + 1] !== '*') {
        const inner = remaining.slice(1, j);
        if (inner.trim().length > 0 && !inner.includes('\n')) {
          nodes.push(<em key={key++} className="italic text-slate-200">{inner}</em>);
          remaining = remaining.slice(j + 1);
          handled = true;
        }
      }
    }

    if (!handled) {
      nodes.push(remaining[0]);
      remaining = remaining.slice(1);
    }
  }

  return nodes;
}

const TOOL_EMOJI_RE = /^[🔧✅⚠️💡📝🔍📊🎯✏️🛠️📦✨🔄📎💬🏷️]/;
const HEADING_RE = /^(#{1,4})\s+(.*)/;
const HR_RE = /^---+$/;
const CODE_FENCE_RE = /^```(\w*)/;
const BLOCKQUOTE_RE = /^>\s?(.*)/;
const UNORDERED_LIST_RE = /^(\s*)[-*+]\s+(.*)/;
const ORDERED_LIST_RE = /^\s*\d+[.)]\s+(.*)/;
const PATCH_RE = /^\[PATCH(?::\s*([^\]]+))?\]/;
const TOOL_CALL_RE = /^🔧\s*调用\s+(\S+)(.*)/;
const TOOL_RESULT_RE = /^✅\s*(.*)/;
const EMOJI_LINE_RE = /^([🔧✅⚠️💡📝🔍📊🎯✏️🛠️📦✨🔄📎💬🏷️])\s*(.*)/;

function parseMessageContent(raw: string): ParsedBlock[] {
  const lines = raw.split('\n');
  const blocks: ParsedBlock[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.trim() === '') {
      i++;
      continue;
    }

    if (HR_RE.test(line.trim())) {
      blocks.push({ type: 'hr' });
      i++;
      continue;
    }

    const headM = line.match(HEADING_RE);
    if (headM) {
      blocks.push({ type: 'heading', level: headM[1].length, text: headM[2].replace(/\s*#+\s*$/, '') });
      i++;
      continue;
    }

    const toolCallM = line.match(TOOL_CALL_RE);
    if (toolCallM) {
      blocks.push({ type: 'tool-call', icon: '🔧', toolName: toolCallM[1], detail: toolCallM[2].trim() });
      i++;
      continue;
    }

    const toolResultM = line.match(TOOL_RESULT_RE);
    if (toolResultM) {
      blocks.push({ type: 'tool-result', icon: '✅', detail: toolResultM[1] });
      i++;
      continue;
    }

    if (TOOL_EMOJI_RE.test(line)) {
      const m = line.match(EMOJI_LINE_RE);
      if (m) {
        blocks.push({ type: 'tool-call', icon: m[1], text: m[2] });
        i++;
        continue;
      }
    }

    const patchM = line.match(PATCH_RE);
    if (patchM) {
      blocks.push({ type: 'patch-marker', section: patchM[1] || '' });
      i++;
      continue;
    }

    if (BLOCKQUOTE_RE.test(line)) {
      const quoteLines: string[] = [];
      while (i < lines.length) {
        const qm = lines[i].match(BLOCKQUOTE_RE);
        if (qm) {
          quoteLines.push(qm[1]);
          i++;
        } else {
          break;
        }
      }
      blocks.push({ type: 'blockquote', text: quoteLines.join('\n') });
      continue;
    }

    const codeM = line.match(CODE_FENCE_RE);
    if (codeM) {
      const lang = codeM[1] || '';
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !CODE_FENCE_RE.test(lines[i])) {
        codeLines.push(lines[i]);
        i++;
      }
      if (i < lines.length) i++;
      blocks.push({ type: 'code', lang, code: codeLines.join('\n') });
      continue;
    }

    const ulM = line.match(UNORDERED_LIST_RE);
    if (ulM) {
      const items: string[] = [];
      while (i < lines.length) {
        const m = lines[i].match(UNORDERED_LIST_RE);
        if (m) {
          items.push(m[2]);
          i++;
        } else {
          break;
        }
      }
      blocks.push({ type: 'list', items });
      continue;
    }

    const olM = line.match(ORDERED_LIST_RE);
    if (olM) {
      const items: string[] = [];
      while (i < lines.length) {
        const m = lines[i].match(ORDERED_LIST_RE);
        if (m) {
          items.push(m[1]);
          i++;
        } else {
          break;
        }
      }
      blocks.push({ type: 'ordered-list', items });
      continue;
    }

    const paraLines: string[] = [];
    while (i < lines.length) {
      const l = lines[i];
      if (l.trim() === '') break;
      if (HEADING_RE.test(l) || CODE_FENCE_RE.test(l) || BLOCKQUOTE_RE.test(l) || HR_RE.test(l.trim())) break;
      if (PATCH_RE.test(l) || TOOL_CALL_RE.test(l) || TOOL_RESULT_RE.test(l) || TOOL_EMOJI_RE.test(l)) break;
      if (UNORDERED_LIST_RE.test(l) || ORDERED_LIST_RE.test(l)) break;
      paraLines.push(l);
      i++;
    }
    if (paraLines.length > 0) {
      blocks.push({ type: 'paragraph', text: paraLines.join('\n') });
    }
  }

  return blocks;
}

function CodeBlock({ lang, code }: { lang: string; code: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [code]);

  return (
    <div className="my-2 rounded-lg border border-slate-700/50 overflow-hidden bg-surface-900/80">
      <div className="flex items-center justify-between px-2.5 py-1 bg-slate-800/60 border-b border-slate-700/40">
        <span className="text-[10px] text-slate-500 font-mono">{lang || 'code'}</span>
        <button onClick={handleCopy} className="text-slate-500 hover:text-slate-300 transition-colors">
          {copied ? <CheckCheck size={12} className="text-emerald-400" /> : <Copy size={12} />}
        </button>
      </div>
      <pre className="px-3 py-2 text-[12px] leading-relaxed text-slate-300 overflow-x-auto scrollbar-thin font-mono">
        <code>{code}</code>
      </pre>
    </div>
  );
}

function ToolCallBlock({ icon, toolName, detail, text }: { icon?: string; toolName?: string; detail?: string; text?: string }) {
  const display = text || (toolName ? `调用 ${toolName} ${detail || ''}` : '');
  return (
    <div className="my-1.5 px-2.5 py-1.5 rounded-lg bg-accent-blue/8 border border-accent-blue/15 flex items-center gap-2 text-xs">
      <span className="shrink-0 text-sm">{icon || '🔧'}</span>
      <span className="text-accent-blue/80">{display}</span>
    </div>
  );
}

function ToolResultBlock({ detail }: { detail: string }) {
  return (
    <div className="my-1 px-2.5 py-1.5 rounded-lg bg-emerald-500/8 border border-emerald-500/15 flex items-center gap-2 text-xs">
      <span className="shrink-0 text-sm">✅</span>
      <span className="text-emerald-400/70 truncate">{detail}</span>
    </div>
  );
}

function PatchMarkerBlock({ section }: { section: string }) {
  return (
    <div className="my-1 px-2.5 py-1.5 rounded-lg bg-accent-purple/8 border border-accent-purple/15 flex items-center gap-2 text-xs">
      <span className="shrink-0 text-sm">✏️</span>
      <span className="text-accent-purple/70">修改{section ? `：${section}` : ''}</span>
    </div>
  );
}

function HeadingBlock({ level, text }: { level: number; text: string }) {
  const sizeClass = level <= 2 ? 'text-sm font-bold text-slate-100' : level === 3 ? 'text-[13px] font-semibold text-slate-200' : 'text-xs font-semibold text-slate-300';
  return (
    <div className={`mt-3 mb-1.5 flex items-center gap-2 ${sizeClass}`}>
      <div className="w-1 h-4 rounded-full bg-accent-blue/60 shrink-0" />
      {parseInline(text)}
    </div>
  );
}

function ParagraphBlock({ text }: { text: string }) {
  const parts = text.split(/\n/);
  return (
    <p className="my-1 text-[13px] leading-[1.7] text-slate-300">
      {parts.map((part, idx) => (
        <span key={idx}>
          {idx > 0 && <br />}
          {parseInline(part)}
        </span>
      ))}
    </p>
  );
}

function ListBlock({ items, ordered }: { items: string[]; ordered?: boolean }) {
  const Tag = ordered ? 'ol' : 'ul';
  return (
    <Tag className={`my-1.5 ml-1 space-y-1 ${ordered ? 'list-decimal' : 'list-disc'} pl-4`}>
      {items.map((item, idx) => (
        <li key={idx} className="text-[13px] leading-relaxed text-slate-300 marker:text-slate-600">
          {parseInline(item)}
        </li>
      ))}
    </Tag>
  );
}

function BlockquoteBlock({ text }: { text: string }) {
  return (
    <div className="my-1.5 border-l-2 border-accent-blue/40 pl-3 py-0.5 bg-accent-blue/5 rounded-r-md">
      <p className="text-[13px] leading-relaxed text-slate-400 italic">{parseInline(text)}</p>
    </div>
  );
}

function HrBlock() {
  return <div className="my-2 border-t border-slate-700/40" />;
}

export function AssistantMessageRenderer({ content }: { content: string }) {
  if (!content.trim()) return null;

  const blocks = parseMessageContent(content);
  if (blocks.length === 0) return null;

  return (
    <div className="space-y-0.5">
      {blocks.map((block, idx) => {
        switch (block.type) {
          case 'heading':
            return <HeadingBlock key={idx} level={block.level || 2} text={block.text || ''} />;
          case 'paragraph':
            return <ParagraphBlock key={idx} text={block.text || ''} />;
          case 'list':
            return <ListBlock key={idx} items={block.items || []} />;
          case 'ordered-list':
            return <ListBlock key={idx} items={block.items || []} ordered />;
          case 'code':
            return <CodeBlock key={idx} lang={block.lang || ''} code={block.code || ''} />;
          case 'tool-call':
            return <ToolCallBlock key={idx} icon={block.icon} toolName={block.toolName} detail={block.detail} text={block.text} />;
          case 'tool-result':
            return <ToolResultBlock key={idx} detail={block.detail || ''} />;
          case 'patch-marker':
            return <PatchMarkerBlock key={idx} section={block.section || ''} />;
          case 'blockquote':
            return <BlockquoteBlock key={idx} text={block.text || ''} />;
          case 'hr':
            return <HrBlock key={idx} />;
          default:
            return null;
        }
      })}
    </div>
  );
}
