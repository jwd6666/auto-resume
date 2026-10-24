/** 简历 Agent 后端 API 封装（/agent 前缀） */
// 开发环境（Vite dev server）使用相对路径走 proxy，避免系统代理拦截 localhost 请求
// 生产环境（Electron）使用 preload 注入的绝对路径
import { authHeaders, withTokenQuery } from './common';

const isDev = location.port === '5173';
const isElectron = !!(window as any).autoresume?.apiBase;
const API_BASE = isDev ? '' : (isElectron ? (window as any).autoresume.apiBase : '');

const AGENT = `${API_BASE}/agent`;

// ── Types ──

export interface Job {
  id: number;
  title: string;
  content: string;
  created_at: string;
  updated_at?: string;
}

export interface GreetedItem {
  id: number;
  task_id: string;
  job_key: string;
  day: string;
  greeted_at: string;
  title: string;
  company: string;
  jd_text: string;
}

export interface Resume {
  id: number;
  job_id: number;
  title?: string;
  content: string;
  structured?: string | null;
  rendered_html?: string | null;
  current_template?: string | null;
  enabled?: boolean;
  file_type?: string;
  file_size?: number;
  version: number;
  background_profile_id?: number;
  angle?: string;
  created_at: string;
  updated_at?: string;
}

export interface RefChip {
  id: string;
  type: 'section' | 'entry' | 'field' | 'highlight' | 'full-resume' | 'html-part';
  label: string;
  section: string;
  index?: number;
  fieldPath?: string;
  sourceJson: any;
  sourceHtml: string;
  resumePartId?: string;
}

export interface HtmlPatch {
  resumePartId: string;
  newHtml: string;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  reasoning?: string;
  images?: string[];
  references?: RefChip[];
  scorecard?: Scorecard;
  patches?: HtmlPatch[];
  snapshotDepth?: number;
}

export interface BackgroundProfile {
  id: number;
  name: string;
  content: string;
  created_at: string;
  updated_at?: string;
}

export interface ScoreCardItem {
  competency: string;
  score: number;
  confidence: string;
  summary: string;
  evidence: { source: string; quote: string; why?: string }[];
  gap?: string;
  suggestion?: string;
}

export interface Scorecard {
  overall_score: number;
  overall_summary: string;
  items: ScoreCardItem[];
  needs_verification: string[];
}

export interface InterviewQuestionnaireItem {
  id: string;
  category: string;
  text: string;
}

export interface InterviewQuestionnaire {
  categories_used: string[];
  items: InterviewQuestionnaireItem[];
  questionnaire_markdown: string;
}

export interface CustomModel {
  id: string;
  api_format: string;
  base_url: string;
  full_url: boolean;
  model_id: string;
  multimodal: boolean;
  api_key_set: string; // "••••••" 或 ""
  model_series: string;
  display_name: string;
  context_input: number;
  context_output: number;
  tool_call_rounds: number;
}

export interface SettingsInfo {
  provider: string;
  model: string;
  api_keys_set: Record<string, string>;
  providers: Record<string, any>;
  custom: {
    base_url: string;
    api_key_set: string;
    model: string;
  };
  custom_models: CustomModel[];
  is_cloud?: boolean;
  cloud_template_id?: number;
}

// ── Jobs ──

export const agentApi = {
  async listJobs(): Promise<Job[]> {
    const r = await fetch(`${AGENT}/jobs`, { headers: authHeaders() });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async createJob(data: Partial<Job>): Promise<Job> {
    const r = await fetch(`${AGENT}/jobs`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(data),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async updateJob(id: number, data: Partial<Job>): Promise<Job> {
    const r = await fetch(`${AGENT}/jobs/${id}`, {
      method: 'PUT',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(data),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async deleteJob(id: number): Promise<void> {
    const r = await fetch(`${AGENT}/jobs/${id}`, { method: 'DELETE', headers: authHeaders() });
    if (!r.ok) throw new Error(await r.text());
  },

  // ── Resumes ──

  async listResumes(jobId?: number): Promise<Resume[]> {
    const params = jobId ? `?job_id=${jobId}` : '';
    const r = await fetch(`${AGENT}/resumes${params}`, { headers: authHeaders() });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async getResume(id: number): Promise<Resume> {
    const r = await fetch(`${AGENT}/resumes/${id}`, { headers: authHeaders() });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async createResume(data: { job_id: number; title?: string; content?: string; structured?: string; background_profile_id?: number; file_type?: string; file_size?: number }): Promise<Resume> {
    const r = await fetch(`${AGENT}/resumes`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(data),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async generateResume(jobId: number, background: string, style?: string, accent?: string): Promise<Resume> {
    const r = await fetch(`${AGENT}/resumes/generate`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ job_id: jobId, background, style: style || 'classic', accent: accent || '#2563eb' }),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async *generateResumeStream(
    jobId: number,
    background: string,
    style?: string,
    accent?: string,
  ): AsyncGenerator<{ type: string; content?: string; resume_id?: number }> {
    const r = await fetch(`${AGENT}/resumes/generate/stream`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ job_id: jobId, background, style: style || 'classic', accent: accent || '#2563eb' }),
    });
    if (!r.ok || !r.body) throw new Error(await r.text());

    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              yield data;
              if (data.type === 'done' || data.type === 'error') return;
            } catch { /* skip */ }
          }
        }
      }
    } catch (e: any) {
      yield { type: 'error', content: `连接中断: ${e.message || '网络错误'}` };
    }
  },

  async createFromTemplate(jobId: number, template: string, accent?: string): Promise<Resume> {
    const r = await fetch(`${AGENT}/resumes/create-from-template`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ job_id: jobId, template, accent }),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async *restyleResumeStream(
    resumeId: number,
    style: string,
    accent: string,
    description?: string,
    avatarBase64?: string,
    referenceImageBase64?: string,
  ): AsyncGenerator<{ type: string; content?: string; resume_id?: number }> {
    const r = await fetch(`${AGENT}/resumes/${resumeId}/restyle/stream`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        style,
        accent,
        description: description || '',
        avatar_base64: avatarBase64 || null,
        reference_image_base64: referenceImageBase64 || null,
      }),
    });
    if (!r.ok || !r.body) {
      let msg = '重新排版失败';
      try { msg = await r.text(); } catch { /* */ }
      throw new Error(msg);
    }

    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              yield data;
              if (data.type === 'done' || data.type === 'error') return;
            } catch { /* skip */ }
          }
        }
      }
    } catch (e: any) {
      yield { type: 'error', content: `连接中断: ${e.message || '网络错误'}` };
    }
  },

  async updateResume(id: number, data: Partial<Resume>): Promise<Resume> {
    const r = await fetch(`${AGENT}/resumes/${id}`, {
      method: 'PUT',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(data),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async deleteResume(id: number): Promise<void> {
    const r = await fetch(`${AGENT}/resumes/${id}`, { method: 'DELETE', headers: authHeaders() });
    if (!r.ok) throw new Error(await r.text());
  },

  // ── Chat ──

  async getConversation(resumeId: number): Promise<{ id: number; messages: string } | null> {
    const r = await fetch(`${AGENT}/chat/conversations/${resumeId}`, { headers: authHeaders() });
    if (r.status === 404) return null;
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async saveConversation(resumeId: number, messages: ChatMessage[]): Promise<void> {
    await fetch(`${AGENT}/chat/conversations`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ resume_id: resumeId, messages }),
    });
  },

  async rollbackSnapshot(resumeId: number, targetDepth: number): Promise<{ ok: boolean; message: string; popped: number; current_depth: number }> {
    const r = await fetch(`${AGENT}/chat/rollback`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ resume_id: resumeId, target_depth: targetDepth }),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  /** 流式对话，返回 AsyncGenerator */
  async *chatStream(
    resumeId: number,
    jobId: number,
    messages: ChatMessage[],
    userBackground?: string,
    signal?: AbortSignal,
  ): AsyncGenerator<{ type: 'text' | 'reasoning' | 'reasoning_to_text' | 'text_to_reasoning' | 'patch' | 'tool_call' | 'tool_result' | 'error' | 'done' | 'warning' | 'snapshot_depth'; content?: string; resumePartId?: string; newHtml?: string; toolName?: string; arguments?: any; result?: string; depth?: number }> {
    const r = await fetch(`${AGENT}/chat/stream`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ resume_id: resumeId, job_id: jobId, messages, user_background: userBackground }),
      signal,
    });
    if (!r.ok || !r.body) throw new Error(await r.text());

    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
                if (data.type === 'text') yield { type: 'text', content: data.content };
                else if (data.type === 'reasoning') yield { type: 'reasoning', content: data.content };
                else if (data.type === 'reasoning_to_text') yield { type: 'reasoning_to_text', content: data.content };
                else if (data.type === 'text_to_reasoning') yield { type: 'text_to_reasoning', content: data.content };
                else if (data.type === 'patch') yield { type: 'patch', resumePartId: data.resumePartId, newHtml: data.newHtml };
              else if (data.type === 'tool_call') yield { type: 'tool_call', toolName: data.name, arguments: data.arguments };
              else if (data.type === 'tool_result') yield { type: 'tool_result', toolName: data.name, result: data.result };
              else if (data.type === 'snapshot_depth') yield { type: 'snapshot_depth', depth: data.depth };
              else if (data.type === 'error') { yield { type: 'error', content: data.content }; return; }
              else if (data.type === 'warning') yield { type: 'warning', content: data.content };
              else if (data.type === 'done') { yield { type: 'done' }; return; }
            } catch { /* skip */ }
          }
        }
      }
    } catch (e: any) {
      yield { type: 'error', content: `[连接中断: ${e.message || '网络错误'}]` };
    }
  },

  // ── Interview Sim ──

  /** 可供选择的面试题类型 */
  async getInterviewCategories(): Promise<string[]> {
    const r = await fetch(`${AGENT}/interview-sim/question-categories`, { headers: authHeaders() });
    if (!r.ok) throw new Error(await r.text());
    const data = await r.json();
    return data.categories || [];
  },

  /** 为本场面试抽样题单（不调用 LLM） */
  async getInterviewQuestionnaire(params: {
    jobId: number;
    resumeId: number;
    total?: number;
    categories?: string[];
    backgroundProfileId?: number;
  }): Promise<InterviewQuestionnaire> {
    const q = new URLSearchParams({
      job_id: String(params.jobId),
      resume_id: String(params.resumeId),
      total: String(params.total ?? 7),
    });
    if (params.backgroundProfileId != null) {
      q.set('background_profile_id', String(params.backgroundProfileId));
    }
    for (const c of params.categories || []) q.append('categories', c);
    const r = await fetch(`${AGENT}/interview-sim/questionnaire?${q.toString()}`, { headers: authHeaders() });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  /** 模拟面试流式对话：AI 面试官按题单提问/追问 */
  async *interviewSimStream(params: {
    jobId: number;
    resumeId: number;
    messages: { role: string; content: string }[];
    userBackground?: string;
    questionnaireMarkdown?: string;
    signal?: AbortSignal;
  }): AsyncGenerator<{ type: 'text' | 'error' | 'done'; content?: string }> {
    const r = await fetch(`${AGENT}/interview-sim/stream`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        job_id: params.jobId,
        resume_id: params.resumeId,
        messages: params.messages,
        user_background: params.userBackground || undefined,
        questionnaire_markdown: params.questionnaireMarkdown || undefined,
      }),
      signal: params.signal,
    });
    if (!r.ok || !r.body) {
      let msg = '模拟面试请求失败';
      try { msg = await r.text(); } catch { /* */ }
      throw new Error(msg);
    }

    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              if (data.type === 'text') yield { type: 'text', content: data.content };
              else if (data.type === 'error') { yield { type: 'error', content: data.content }; return; }
              else if (data.type === 'done') { yield { type: 'done' }; return; }
            } catch { /* skip */ }
          }
        }
      }
    } catch (e: any) {
      yield { type: 'error', content: `连接中断: ${e.message || '网络错误'}` };
    }
  },

  /** 面试结束后生成复盘报告（Markdown） */
  async generateInterviewReport(data: {
    jobId: number;
    resumeId: number;
    messages: { role: string; content: string }[];
    userBackground?: string;
  }): Promise<{ report: string }> {
    const r = await fetch(`${AGENT}/interview-sim/report`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        job_id: data.jobId,
        resume_id: data.resumeId,
        messages: data.messages,
        user_background: data.userBackground || undefined,
      }),
    });
    if (!r.ok) {
      let msg = '生成面试报告失败';
      try { msg = await r.text(); } catch { /* */ }
      throw new Error(msg);
    }
    return r.json();
  },

  /** 获取简历磁盘文件最新内容 */
  async getResumeFile(resumeId: number): Promise<{ resume_id: number; html: string; path: string }> {
    const r = await fetch(`${AGENT}/resumes/${resumeId}/file`, { headers: authHeaders() });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  /**
   * 内置浏览器预览（Electron webview）用：返回可加载简历原始 HTML 的绝对 URL。
   * dev 走 Vite 时 API_BASE 为空，需直接指向后端端口。
   * webview 无法携带自定义请求头，令牌通过查询参数传递。
   */
  webviewResumeUrl(resumeId: number): string {
    const base = isDev
      ? 'http://127.0.0.1:8765'
      : (window as any).autoresume?.apiBase || '';
    return withTokenQuery(`${base}${AGENT.replace(API_BASE, '')}/resumes/${resumeId}/resume.html`);
  },

  /** 订阅简历文件变更 WebSocket，返回关闭函数 */
  subscribeResumeFileChange(
    resumeId: number,
    onFileChange: (data: { type: string; resume_id: number; path: string }) => void,
  ): () => void {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    // WebSocket 无法携带自定义请求头，令牌通过查询参数传递
    const wsUrl = withTokenQuery(isDev
      ? `${proto}//${location.host}${AGENT}/ws/resume/${resumeId}`
      : `${API_BASE.replace(/^http/, 'ws')}${AGENT.replace(API_BASE, '')}/ws/resume/${resumeId}`);
    let ws: WebSocket | null = null;
    let closed = false;

    const connect = () => {
      if (closed) return;
      ws = new WebSocket(wsUrl);
      ws.onopen = () => {
      };
      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          if (data.type === 'file_changed') {
            onFileChange(data);
          }
        } catch { /* skip */ }
      };
      ws.onclose = () => {
        if (!closed) {
          // 断线重连（3 秒后）
          setTimeout(connect, 3000);
        }
      };
      ws.onerror = () => {
        try { ws?.close(); } catch { /* */ }
      };
    };
    connect();

    return () => {
      closed = true;
      try { ws?.close(); } catch { /* */ }
    };
  },

  // ── Upload ──

  /** 上传简历文件 → 后端自动提取文本 + 结构化 + 生成HTML → 返回完整Resume */
  async uploadAndGenerate(jobId: number, file: File, accent?: string, signal?: AbortSignal): Promise<Resume> {
    const fd = new FormData();
    fd.append('file', file);
    const params = new URLSearchParams({ job_id: String(jobId), accent: accent || '#2563eb' });
    const r = await fetch(`${AGENT}/uploads/upload-resume?${params}`, {
      method: 'POST',
      headers: authHeaders(),
      body: fd,
      signal,
    });
    if (!r.ok) {
      let msg = await r.text();
      try { msg = JSON.parse(msg).detail || msg; } catch { /* keep */ }
      throw new Error(msg || '上传生成简历失败');
    }
    return r.json();
  },

  /** 流式版：上传简历文件 → 逐步推送 parse/generate 进度 → 最终返回 resume_id */
  async *uploadAndGenerateStream(
    jobId: number,
    file: File,
    accent?: string,
  ): AsyncGenerator<{ type: string; phase?: string; content?: string; resume_id?: number }> {
    const fd = new FormData();
    fd.append('file', file);
    const params = new URLSearchParams({ job_id: String(jobId), accent: accent || '#2563eb' });
    const r = await fetch(`${AGENT}/uploads/upload-resume/stream?${params}`, {
      method: 'POST',
      headers: authHeaders(),
      body: fd,
    });
    if (!r.ok || !r.body) {
      let msg = '上传生成简历失败';
      try { msg = await r.text(); } catch { /* */ }
      throw new Error(msg);
    }

    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              yield data;
              if (data.type === 'done' || data.type === 'error') return;
            } catch { /* skip */ }
          }
        }
      }
    } catch (e: any) {
      yield { type: 'error', content: `连接中断: ${e.message || '网络错误'}` };
    }
  },

  async uploadResumePdf(file: File): Promise<{ filename: string; text: string; parser: string; warning?: string }> {
    const fd = new FormData();
    fd.append('file', file);
    const r = await fetch(`${AGENT}/uploads/parse-resume-background`, {
      method: 'POST',
      headers: authHeaders(),
      body: fd,
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  /** 上传候选人头像 → 固定保存到安装目录 data/avatars，返回本地绝对路径（生成简历时发给模型引用） */
  async uploadAvatar(file: File): Promise<{ path: string; filename: string }> {
    const fd = new FormData();
    fd.append('file', file);
    const r = await fetch(`${AGENT}/uploads/avatar`, {
      method: 'POST',
      headers: authHeaders(),
      body: fd,
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  /** 头像预览 URL：<img> 无法携带请求头，令牌走查询参数（与 webview 加载一致） */
  avatarPreviewUrl(filename: string): string {
    const base = isDev
      ? 'http://127.0.0.1:8765'
      : (window as any).autoresume?.apiBase || '';
    return withTokenQuery(`${base}${AGENT.replace(API_BASE, '')}/avatars/${encodeURIComponent(filename)}`);
  },

  /** 从头像绝对路径提取文件名（用于生成预览 URL） */
  avatarFilename(path: string): string {
    const segs = path.split(/[\\/]/);
    return segs[segs.length - 1] || '';
  },

  async *uploadResumePdfStream(file: File): AsyncGenerator<{ type: string; content?: string; parser?: string; warning?: string | null }> {
    const fd = new FormData();
    fd.append('file', file);
    const r = await fetch(`${AGENT}/uploads/parse-resume-background/stream`, {
      method: 'POST',
      headers: authHeaders(),
      body: fd,
    });
    if (!r.ok || !r.body) throw new Error(await r.text());

    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              yield data;
              if (data.type === 'done' || data.type === 'error') return;
            } catch { /* skip */ }
          }
        }
      }
    } catch (e: any) {
      yield { type: 'error', content: `连接中断: ${e.message || '网络错误'}。模型可能输出不完整。` };
    }
  },

  // ── Export ──

  exportUrl(type: 'markdown' | 'pdf' | 'word', resumeId: number, extra?: string): string {
    const q = extra ? `?${extra}` : '';
    // 导出链接经 window.open 直接访问后端，无法携带自定义请求头，令牌走查询参数
    return withTokenQuery(`${AGENT}/export/${type}/${resumeId}${q}`);
  },

  // ── Evaluation ──

  async generateScorecard(data: {
    job_id: number;
    resume_id: number;
    transcript?: string;
    user_background?: string;
  }): Promise<Scorecard> {
    const r = await fetch(`${AGENT}/evaluation/scorecard`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(data),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  // ── Background Profiles ──

  async listBackgrounds(): Promise<BackgroundProfile[]> {
    const r = await fetch(`${AGENT}/background/profiles`, { headers: authHeaders() });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async createBackground(data: { name: string; content: string }): Promise<BackgroundProfile> {
    const r = await fetch(`${AGENT}/background/profiles`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(data),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async updateBackground(id: number, data: { name?: string; content?: string }): Promise<BackgroundProfile> {
    const r = await fetch(`${AGENT}/background/profiles/${id}`, {
      method: 'PUT',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(data),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async deleteBackground(id: number): Promise<void> {
    const r = await fetch(`${AGENT}/background/profiles/${id}`, { method: 'DELETE', headers: authHeaders() });
    if (!r.ok) throw new Error(await r.text());
  },

  // ── Settings ──

  async getSettings(): Promise<SettingsInfo> {
    const r = await fetch(`${AGENT}/settings`, { headers: authHeaders() });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async updateSettings(data: {
    provider: string;
    model: string;
    api_keys?: Record<string, string>;
    custom_base_url?: string;
    custom_api_key?: string;
    custom_model?: string;
  }): Promise<void> {
    const r = await fetch(`${AGENT}/settings`, {
      method: 'PUT',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(data),
    });
    if (!r.ok) throw new Error(await r.text());
  },

  async testConnection(provider: string, model: string, apiKey?: string, baseUrl?: string): Promise<{ success: boolean; message: string }> {
    const r = await fetch(`${AGENT}/settings/test`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ provider, model, api_key: apiKey, base_url: baseUrl }),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  // ── Custom Models ──

  async addCustomModel(data: {
    api_format: string;
    base_url: string;
    full_url: boolean;
    model_id: string;
    multimodal: boolean;
    api_key: string;
    model_series: string;
    display_name: string;
    context_input: number;
    context_output: number;
    tool_call_rounds: number;
  }): Promise<CustomModel> {
    const r = await fetch(`${AGENT}/settings/custom-models`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(data),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async deleteCustomModel(modelId: string): Promise<void> {
    const r = await fetch(`${AGENT}/settings/custom-models/${modelId}`, { method: 'DELETE', headers: authHeaders() });
    if (!r.ok) throw new Error(await r.text());
  },

  /**
   * 更新自定义模型。api_key 留空或 '••••••' 表示保留原值。
   * 只传需要更新的字段即可。
   */
  async updateCustomModel(modelId: string, data: {
    api_format?: string;
    base_url?: string;
    full_url?: boolean;
    model_id?: string;
    multimodal?: boolean;
    api_key?: string;
    model_series?: string;
    display_name?: string;
    context_input?: number;
    context_output?: number;
    tool_call_rounds?: number;
  }): Promise<CustomModel> {
    const r = await fetch(`${AGENT}/settings/custom-models/${modelId}`, {
      method: 'PUT',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(data),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  /**
   * 通过后端代理测试自定义模型连通性（避免浏览器 CORS 拦截）。
   * 完整返回 HTTP 状态码、响应体、错误类型，由前端组装展示。
   * 编辑模式下 api_key 可为空或 '••••••'，需同时传 existing_model_id 以便后端查找已存储的密钥。
   */
  async testCustomModel(data: {
    base_url: string;
    full_url: boolean;
    model_id: string;
    api_key: string;
    existing_model_id?: string;
  }): Promise<{
    success: boolean;
    status_code?: number;
    status_text?: string;
    body?: string;
    error_type?: string;
    message?: string;
  }> {
    const r = await fetch(`${AGENT}/settings/test-custom-model`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(data),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async batchCreateJobs(jobs: { title: string; content: string }[]): Promise<Job[]> {
    const r = await fetch(`${AGENT}/jobs/batch`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ jobs }),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },

  async listGreetedRecent(days: number = 3): Promise<GreetedItem[]> {
    const r = await fetch(`${API_BASE}/api/tasks/greeted-recent?days=${days}`, { headers: authHeaders() });
    if (!r.ok) throw new Error(await r.text());
    const data = await r.json();
    return data.items || [];
  },

  async batchDeleteGreeted(ids: number[]): Promise<{ ok: boolean; deleted: number }> {
    const r = await fetch(`${API_BASE}/api/tasks/greeted-batch-delete`, {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ ids }),
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },
};
